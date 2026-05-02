"""Hermes portfolio allocation agent (rule-based v1 with ML-ready interface)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.core.types import Regime, RiskPosture, StrategyMetrics
from src.strategies.base import StrategyMetadata
from src.hermes.metrics import MetricsTracker
from src.hermes.policy import Policy

logger = logging.getLogger(__name__)


@dataclass
class StrategyAllocation:
    """Hermes output for a single strategy."""
    strategy_id: str
    active: bool
    weight: float  # 0.0-1.0 (within strategy's max_allocation_pct)
    reason: str  # human-readable, for audit trail


class HermesAgent:
    """Portfolio-level allocation agent.

    Hermes v1 is rule-based: it uses the Policy engine to evaluate
    conditions and produce allocations. The interface is designed so that
    the policy engine can later be replaced with ML without changing callers.

    Responsibilities:
    - Decide which strategies are active/inactive
    - Set capital weights per strategy (within metadata caps)
    - Set global risk posture

    What Hermes does NOT do:
    - Generate trade signals
    - Inspect indicator logic
    - Allocate capital inside a strategy
    """

    def __init__(self, policy: Policy, metrics: MetricsTracker) -> None:
        self._policy = policy
        self._metrics = metrics
        self._risk_posture: RiskPosture = RiskPosture.NORMAL
        self._paused_strategies: dict[str, int] = {}  # strategy_id -> bars remaining

    @property
    def metrics(self) -> MetricsTracker:
        return self._metrics

    @property
    def risk_posture(self) -> RiskPosture:
        return self._risk_posture

    def set_risk_posture(self, posture: RiskPosture) -> None:
        self._risk_posture = posture

    def pause_strategy(self, strategy_id: str, cooldown_bars: int) -> None:
        """Temporarily pause a strategy for a number of bars."""
        self._paused_strategies[strategy_id] = cooldown_bars
        logger.info(
            "Hermes: pausing %s for %d bars", strategy_id, cooldown_bars
        )

    def tick_cooldowns(self) -> None:
        """Decrement all pause cooldowns. Called once per bar."""
        expired = []
        for sid, remaining in self._paused_strategies.items():
            self._paused_strategies[sid] = remaining - 1
            if remaining - 1 <= 0:
                expired.append(sid)
        for sid in expired:
            del self._paused_strategies[sid]
            logger.info("Hermes: unpausing %s (cooldown expired)", sid)

    def evaluate(
        self,
        strategies: list[StrategyMetadata],
        regime: Regime,
        portfolio_drawdown: float,
    ) -> dict[str, StrategyAllocation]:
        """Evaluate allocation for all strategies given current market state.

        This is the core Hermes method. For each strategy:
        1. Check if it's paused
        2. Get its performance metrics
        3. Run policy evaluation
        4. Clamp weight to strategy's max_allocation_pct
        5. Produce allocation with reason string

        Returns: {strategy_id: StrategyAllocation}
        """
        allocations: dict[str, StrategyAllocation] = {}

        for meta in strategies:
            sid = meta.strategy_id

            # Check pause
            if sid in self._paused_strategies:
                allocations[sid] = StrategyAllocation(
                    strategy_id=sid,
                    active=False,
                    weight=0.0,
                    reason=f"Paused (cooldown: {self._paused_strategies[sid]} bars remaining)",
                )
                continue

            # Get metrics
            metrics = self._metrics.get_metrics(sid)

            # Run policy
            action, weight, reason = self._policy.evaluate(
                regime=regime,
                strategy_style=meta.style,
                strategy_metrics=metrics,
                portfolio_drawdown=portfolio_drawdown,
                risk_posture=self._risk_posture,
            )

            # Apply action
            if action == "pause":
                cooldown = 50  # default
                self.pause_strategy(sid, cooldown)
                allocations[sid] = StrategyAllocation(
                    strategy_id=sid, active=False, weight=0.0, reason=reason
                )
                continue

            # Clamp weight to strategy's max allocation
            clamped_weight = min(weight, meta.max_allocation_pct)

            active = clamped_weight > 0.0

            allocations[sid] = StrategyAllocation(
                strategy_id=sid,
                active=active,
                weight=clamped_weight,
                reason=reason,
            )

            logger.debug(
                "Hermes: %s -> active=%s, weight=%.2f, reason=%s",
                sid, active, clamped_weight, reason,
            )

        return allocations