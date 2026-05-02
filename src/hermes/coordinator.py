"""HermesCoordinator - orchestrates one Hermes v2 evaluation cycle."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime

from src.hermes.agents.base import MarketState
from src.hermes.conflict import ConflictInput, ConflictResolver
from src.hermes.correlation import CorrelationMatrix
from src.hermes.decision import HermesDecision
from src.hermes.registry import AgentRegistry
from src.hermes.scoring import ScoringEngine
from src.hermes.sizing import PositionSizer, SizingInput

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccountState:
    """Current account state for position sizing."""
    equity: float
    peak_equity: float
    current_drawdown: float  # fraction, e.g. 0.10 = 10%
    max_risk_per_trade: float
    max_portfolio_risk: float


@dataclass(frozen=True)
class PreviousState:
    """State from the previous Hermes cycle."""
    composite_score: float = 0.0
    regime: str = "ranging"
    risk_directive: str = "FULL"
    allowed_strategy_family: str | None = None


class HermesCoordinator:
    """Orchestrates one Hermes v2 evaluation cycle.

    Execution loop:
        1. Collect agent outputs (via AgentRegistry)
        2. Validate agent outputs (reject on missing/out-of-range)
        3. Compute derived metrics (ScoringEngine)
        4. Resolve conflicts (ConflictResolver / HCR-001)
        5. Apply position sizing (PositionSizer / HPS-001)
        6. Emit HermesDecision

    Components are injected via constructor for testability.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        scoring: ScoringEngine,
        conflict: ConflictResolver,
        sizing: PositionSizer,
    ) -> None:
        self._registry = registry
        self._scoring = scoring
        self._conflict = conflict
        self._sizing = sizing

    def run_cycle(
        self,
        market_state: MarketState,
        account_state: AccountState,
        previous_state: PreviousState | None = None,
    ) -> HermesDecision:
        """Execute one complete Hermes v2 cycle. Deterministic."""
        prev = previous_state or PreviousState()

        # Step 1: Collect agent outputs
        agent_outputs = self._registry.run_all(market_state)

        # Step 2: Validate agent outputs
        valid_scores: list[float] = []
        valid_confidences: list[float] = []
        agent_scores_map: dict[str, float] = {}
        agent_confidences_map: dict[str, float] = {}

        for output in agent_outputs:
            # Validation gate
            if not (-1.0 <= output.score <= 1.0) or not (0.0 <= output.confidence <= 1.0):
                logger.warning(
                    "Agent %s output rejected: score=%s confidence=%s",
                    output.agent_name, output.score, output.confidence,
                )
                # Fail-safe: force CASH on any invalid output
                return self._make_cash_decision(
                    agent_scores_map, agent_confidences_map, market_state,
                    reasoning=f"Agent {output.agent_name} produced invalid output. Forced CASH.",
                )

            valid_scores.append(output.score)
            valid_confidences.append(output.confidence)
            agent_scores_map[output.agent_name] = output.score
            agent_confidences_map[output.agent_name] = output.confidence

        # Step 3: Compute derived metrics
        scoring_result = self._scoring.compute(valid_scores, valid_confidences)

        # Step 4: Resolve conflicts (HCR-001)
        conflict_input = ConflictInput(
            composite_score=scoring_result.composite_score,
            total_confidence=scoring_result.total_confidence,
            score_dispersion=scoring_result.score_dispersion,
            previous_composite_score=prev.composite_score,
            previous_regime=prev.regime,
            previous_risk_directive=prev.risk_directive,
            previous_allowed_family=prev.allowed_strategy_family,
        )
        conflict_output = self._conflict.resolve(conflict_input)

        # Step 5: Position sizing (HPS-001)
        sizing_input = SizingInput(
            risk_directive=conflict_output.risk_directive,
            confidence=scoring_result.total_confidence,
            current_drawdown=account_state.current_drawdown,
            max_risk_per_trade=account_state.max_risk_per_trade,
            max_portfolio_risk=account_state.max_portfolio_risk,
        )
        sizing_output = self._sizing.compute(sizing_input)

        # Step 6: Emit HermesDecision
        # Use effective_risk_directive from sizing (may override conflict output,
        # e.g., CRITICAL drawdown forces CASH regardless of conflict resolution)
        effective_directive = sizing_output.effective_risk_directive
        decision = HermesDecision(
            regime=conflict_output.regime,
            composite_score=scoring_result.composite_score,
            confidence=scoring_result.total_confidence,
            risk_directive=effective_directive,
            allowed_strategy_family=(
                conflict_output.allowed_strategy_family
                if effective_directive != "CASH" else None
            ),
            per_trade_risk=sizing_output.per_trade_risk,
            portfolio_risk=sizing_output.portfolio_risk,
            timestamp=market_state.timestamp,
            agent_scores=agent_scores_map,
            agent_confidences=agent_confidences_map,
            reasoning=f"{conflict_output.reasoning} | {sizing_output.reasoning}",
        )

        logger.info(
            "Hermes v2 decision: regime=%s, risk_directive=%s, "
            "composite=%.3f, confidence=%.3f, family=%s",
            decision.regime, decision.risk_directive,
            decision.composite_score, decision.confidence,
            decision.allowed_strategy_family,
        )

        return decision

    def run_batch(
        self,
        market_states: list[MarketState],
        account_state: AccountState,
        previous_states: dict[str, PreviousState] | None = None,
        correlation: CorrelationMatrix | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, HermesDecision]:
        """Execute one Hermes v2 cycle over multiple market states.

        Portfolio-level intelligence:
            1. Run agents on each symbol independently (per-symbol analysis)
            2. Rank symbols by composite score (correlation-adjusted if provided)
            3. Apply portfolio-level risk budgeting (correlation-adjusted if provided)
            4. Cross-symbol conflict and concentration detection
            5. Emit per-symbol decisions

        Args:
            market_states: One MarketState per universe symbol.
            account_state: Shared account state for sizing.
            previous_states: Optional per-symbol previous states for conflict resolver.
            correlation: Optional correlation matrix for portfolio-level adjustments.
            timeout_seconds: Optional timeout. If exceeded, returns partial results.

        Returns:
            Dict mapping symbol → HermesDecision.
        """
        if not market_states:
            logger.warning("run_batch called with no market states")
            return {}

        prev = previous_states or {}
        decisions: dict[str, HermesDecision] = {}
        total_portfolio_risk = 0.0
        batch_timed_out = False
        start_time = time.monotonic() if timeout_seconds else None

        # Step 1-6: Run the 6-step cycle for each symbol independently
        for ms in market_states:
            # Timeout check
            if timeout_seconds and start_time is not None:
                elapsed = time.monotonic() - start_time
                if elapsed > timeout_seconds:
                    logger.warning(
                        "Hermes batch timeout reached after %d symbols (%.1fs > %.1fs limit). "
                        "%d symbols skipped.",
                        len(decisions),
                        elapsed,
                        timeout_seconds,
                        len(market_states) - len(decisions),
                    )
                    batch_timed_out = True
                    break

            symbol = ms.symbol or f"unknown_{len(decisions)}"
            previous = prev.get(symbol)

            decision = self.run_cycle(ms, account_state, previous)
            decisions[symbol] = decision
            total_portfolio_risk += decision.portfolio_risk

        # Step 7: Portfolio-level post-processing
        # Compute correlation-adjusted total risk if correlation matrix provided
        if correlation is not None and len(decisions) > 1:
            adjusted_total = self._compute_correlation_adjusted_risk(decisions, correlation)
        else:
            adjusted_total = total_portfolio_risk

        # Step 7b: If total portfolio risk exceeds max, scale down lowest-ranked symbols
        if adjusted_total > account_state.max_portfolio_risk and len(decisions) > 1:
            # Rank by composite_score (with correlation penalty if available)
            if correlation is not None:
                ranked = self._rank_with_correlation(decisions, correlation)
            else:
                ranked = sorted(decisions.items(), key=lambda x: x[1].composite_score)

            excess = adjusted_total - account_state.max_portfolio_risk

            for symbol, decision in ranked:
                if excess <= 0:
                    break
                # Scale down this symbol's risk
                reduction = min(excess, decision.portfolio_risk)
                new_portfolio_risk = max(0.0, decision.portfolio_risk - reduction)
                excess -= reduction

                # Update decision with scaled risk
                decisions[symbol] = HermesDecision(
                    regime=decision.regime,
                    composite_score=decision.composite_score,
                    confidence=decision.confidence,
                    risk_directive="SCALE_DOWN" if new_portfolio_risk < decision.portfolio_risk else decision.risk_directive,
                    allowed_strategy_family=decision.allowed_strategy_family,
                    per_trade_risk=decision.per_trade_risk,
                    portfolio_risk=new_portfolio_risk,
                    timestamp=decision.timestamp,
                    agent_scores=decision.agent_scores,
                    agent_confidences=decision.agent_confidences,
                    reasoning=(
                        f"{decision.reasoning} | "
                        f"{'Correlation-adjusted ' if correlation else ''}"
                        f"Portfolio risk cap: scaled from {decision.portfolio_risk:.6f} to {new_portfolio_risk:.6f}"
                    ),
                )

            logger.info(
                "Portfolio risk cap applied: adjusted_total=%.6f → max=%.6f",
                adjusted_total,
                account_state.max_portfolio_risk,
            )

        # Step 8: Cross-symbol conflict detection
        if len(decisions) > 1:
            directives = {d.risk_directive for d in decisions.values()}
            if len(directives) > 1 and "CASH" in directives:
                # Some symbols say CASH, others say trade — flag in reasoning
                for symbol, decision in decisions.items():
                    if decision.risk_directive != "CASH":
                        decisions[symbol] = HermesDecision(
                            regime=decision.regime,
                            composite_score=decision.composite_score,
                            confidence=decision.confidence,
                            risk_directive=decision.risk_directive,
                            allowed_strategy_family=decision.allowed_strategy_family,
                            per_trade_risk=decision.per_trade_risk,
                            portfolio_risk=decision.portfolio_risk,
                            timestamp=decision.timestamp,
                            agent_scores=decision.agent_scores,
                            agent_confidences=decision.agent_confidences,
                            reasoning=f"{decision.reasoning} | Cross-symbol conflict: some symbols recommend CASH",
                        )

        # Step 8b: Correlation concentration warning
        if correlation is not None and len(decisions) > 1:
            for sym_a, sym_b, corr_val in correlation.high_pairs:
                if sym_a in decisions and sym_b in decisions:
                    d_a = decisions[sym_a]
                    d_b = decisions[sym_b]
                    if d_a.risk_directive != "CASH" and d_b.risk_directive != "CASH":
                        # Both active and highly correlated → concentration warning
                        for sym in (sym_a, sym_b):
                            d = decisions[sym]
                            decisions[sym] = HermesDecision(
                                regime=d.regime,
                                composite_score=d.composite_score,
                                confidence=d.confidence,
                                risk_directive=d.risk_directive,
                                allowed_strategy_family=d.allowed_strategy_family,
                                per_trade_risk=d.per_trade_risk,
                                portfolio_risk=d.portfolio_risk,
                                timestamp=d.timestamp,
                                agent_scores=d.agent_scores,
                                agent_confidences=d.agent_confidences,
                                reasoning=f"{d.reasoning} | Concentration warning: {sym_a}↔{sym_b} correlation={corr_val:.2f}",
                            )

        logger.info(
            "Hermes batch completed: %d symbols evaluated, directives=%s",
            len(decisions),
            {s: d.risk_directive for s, d in decisions.items()},
        )

        # Step 9: If batch timed out, annotate all decisions
        if batch_timed_out:
            skipped = len(market_states) - len(decisions)
            for sym, d in decisions.items():
                decisions[sym] = HermesDecision(
                    regime=d.regime,
                    composite_score=d.composite_score,
                    confidence=d.confidence,
                    risk_directive=d.risk_directive,
                    allowed_strategy_family=d.allowed_strategy_family,
                    per_trade_risk=d.per_trade_risk,
                    portfolio_risk=d.portfolio_risk,
                    timestamp=d.timestamp,
                    agent_scores=d.agent_scores,
                    agent_confidences=d.agent_confidences,
                    reasoning=f"{d.reasoning} | BATCH_TIMEOUT: {skipped} symbols skipped due to timeout",
                )

        return decisions

    def _compute_correlation_adjusted_risk(
        self,
        decisions: dict[str, HermesDecision],
        corr_matrix: CorrelationMatrix,
    ) -> float:
        """Compute total risk adjusted for pairwise correlations.

        For highly correlated pairs, count only the max risk (not sum).
        For uncorrelated assets, count full risk.
        """
        symbols = list(decisions.keys())
        counted: set[str] = set()
        adjusted_total = 0.0

        for sym_a in symbols:
            if sym_a in counted:
                continue
            risk_a = decisions[sym_a].portfolio_risk
            counted.add(sym_a)
            max_risk_in_group = risk_a

            for sym_b in symbols:
                if sym_b in counted:
                    continue
                if corr_matrix.is_highly_correlated(sym_a, sym_b):
                    risk_b = decisions[sym_b].portfolio_risk
                    max_risk_in_group = max(max_risk_in_group, risk_b)
                    counted.add(sym_b)

            adjusted_total += max_risk_in_group

        return adjusted_total

    def _rank_with_correlation(
        self,
        decisions: dict[str, HermesDecision],
        corr_matrix: CorrelationMatrix,
    ) -> list[tuple[str, HermesDecision]]:
        """Rank symbols with correlation penalty.

        For each symbol, compute effective_score = composite_score - correlation_penalty.
        Diversifying assets naturally rank higher.
        """
        scores: dict[str, float] = {}
        symbols = list(decisions.keys())

        for sym in symbols:
            base = decisions[sym].composite_score
            penalty = 0.0
            for other in symbols:
                if other == sym:
                    continue
                corr = abs(corr_matrix.get(sym, other))
                if corr > 0.75 and decisions[other].composite_score > base:
                    # Higher-scored correlated asset pulls this one down
                    penalty += corr * 0.1  # 10% penalty per highly correlated higher peer
            scores[sym] = base - penalty

        ranked = sorted(scores.keys(), key=lambda s: scores[s])
        return [(s, decisions[s]) for s in ranked]

    def _make_cash_decision(
        self,
        agent_scores: dict[str, float],
        agent_confidences: dict[str, float],
        market_state: MarketState,
        reasoning: str,
    ) -> HermesDecision:
        """Produce a fail-safe CASH decision."""
        return HermesDecision(
            regime="INDETERMINATE",
            composite_score=0.0,
            confidence=0.0,
            risk_directive="CASH",
            allowed_strategy_family=None,
            per_trade_risk=0.0,
            portfolio_risk=0.0,
            timestamp=market_state.timestamp,
            agent_scores=agent_scores,
            agent_confidences=agent_confidences,
            reasoning=reasoning,
        )