"""LLMTuner — uses LLM as hypothesis generator for parameter tuning.

Phase E.4 of the meta-optimization plane.
The LLM generates hypotheses and search plans. All evaluation is offline.
LLM never deploys changes — all outputs go through HITL.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from src.analytics.engine import AnalyticsEngine
from src.persistence.db import PersistenceDB

from src.meta.models import (
    LLMHypothesis,
    LLMTuningProposal,
    MetaCapability,
    MonteCarloResult,
    ProposalStatus,
    WalkForwardWindow,
)
from src.meta.optimizer import (
    MIN_FILLS_PER_WINDOW,
    MIN_SHARPE_IMPROVEMENT_OOS,
    SelfOptimizer,
)

logger = logging.getLogger(__name__)


class LLMTuner:
    """Uses LLM as hypothesis generator for parameter tuning.

    The LLM:
    - Generates hypotheses about parameter improvements
    - Plans search strategies for parameter space exploration
    - Interprets validation results

    The system:
    - Evaluates all candidates offline
    - Applies statistical significance gates
    - Never allows LLM to deploy changes

    Usage:
        tuner = LLMTuner()
        proposal = tuner.tune()
    """

    def __init__(
        self,
        optimizer: SelfOptimizer | None = None,
        analytics: AnalyticsEngine | None = None,
        db: PersistenceDB | None = None,
    ) -> None:
        self._optimizer = optimizer or SelfOptimizer(analytics=analytics, db=db)
        self._analytics = analytics or AnalyticsEngine()
        self._db = db or PersistenceDB()

    def check_gating(self) -> tuple[bool, str]:
        """Check if LLM tuning is allowed.

        Returns:
            Tuple of (allowed, reason).
        """
        # Check minimum fills
        strategy_report = self._analytics.strategy_performance(limit=10000)
        if strategy_report.total_trades < 200:
            return False, (
                f"Insufficient fills: {strategy_report.total_trades} < 200"
            )

        # Check cooling-off from last adoption
        last_adopted = self._last_adoption_time()
        if last_adopted:
            days_since = (datetime.now() - datetime.fromisoformat(last_adopted)).days
            if days_since < 30:
                return False, f"Cooling-off: {30 - days_since} days remaining"

        return True, "All gating conditions pass"

    def tune(self) -> LLMTuningProposal | None:
        """Run the LLM tuning pipeline.

        Returns:
            LLMTuningProposal if LLM hypothesis produces a dominant configuration,
            None if no improvement found.
        """
        allowed, reason = self.check_gating()
        if not allowed:
            logger.info("LLM tuning gated: %s", reason)
            return None

        logger.info("Starting LLM-driven tuning")

        # Generate LLM hypotheses
        hypotheses = self._generate_hypotheses()

        best_proposal = None
        best_improvement = 0.0

        for hypothesis in hypotheses:
            # Evaluate each hypothesis
            proposal = self._evaluate_hypothesis(hypothesis)

            if proposal and proposal.validation_passed:
                improvement = proposal.projected_metrics.get("sharpe", 0) - proposal.baseline_metrics.get("sharpe", 0)
                if improvement > best_improvement:
                    best_improvement = improvement
                    best_proposal = proposal

        if best_proposal is None:
            logger.info("No LLM hypothesis produced a dominant configuration")
            return None

        # Persist proposal
        try:
            self._db.record_meta_proposal(best_proposal)
        except Exception as e:
            logger.warning("Failed to persist LLM tuning proposal: %s", e)

        logger.info(
            "LLM tuning proposal created: %s",
            best_proposal.hypothesis.hypothesis_text,
        )

        return best_proposal

    def _generate_hypotheses(self) -> list[LLMHypothesis]:
        """Generate LLM hypotheses about parameter improvements.

        In production, this would call an LLM API. Here we use
        predefined hypothesis templates based on system analysis.
        """
        hypotheses: list[LLMHypothesis] = []

        # Template-based hypothesis generation (simulates LLM)
        templates = [
            {
                "text": "Tightening disagreement threshold may reduce false CASH directives",
                "params": ["DISAGREEMENT_THRESHOLD"],
                "reasoning": "High dispersion triggers often occur in ranging markets where agents naturally disagree",
                "confidence": 0.7,
            },
            {
                "text": "Raising trending threshold may improve regime classification accuracy",
                "params": ["TRENDING_THRESHOLD"],
                "reasoning": "Current threshold may classify ranging markets as trending",
                "confidence": 0.6,
            },
            {
                "text": "Adjusting confidence boundaries may improve SCALE_DOWN precision",
                "params": ["CONFIDENCE_BOUNDARY_HIGH", "CONFIDENCE_BOUNDARY_LOW"],
                "reasoning": "Current boundaries may not adequately distinguish confidence levels",
                "confidence": 0.5,
            },
            {
                "text": "Lowering flip risk threshold may reduce unnecessary SCALE_DOWN",
                "params": ["FLIP_RISK_THRESHOLD"],
                "reasoning": "Score jumps may not always indicate regime flip risk",
                "confidence": 0.6,
            },
            {
                "text": "Adjusting correlation threshold may improve diversification detection",
                "params": ["CORRELATION_THRESHOLD"],
                "reasoning": "Current threshold may miss moderately correlated pairs",
                "confidence": 0.5,
            },
        ]

        for i, template in enumerate(templates):
            hypotheses.append(
                LLMHypothesis(
                    hypothesis_id=f"llm_hyp_{i+1:03d}",
                    hypothesis_text=template["text"],
                    parameters_affected=template["params"],
                    reasoning=template["reasoning"],
                    confidence=template["confidence"],
                )
            )

        return hypotheses

    def _evaluate_hypothesis(
        self, hypothesis: LLMHypothesis
    ) -> LLMTuningProposal | None:
        """Evaluate a single LLM hypothesis.

        Uses the optimizer's evaluation framework with walk-forward
        validation and Monte Carlo significance testing.
        """
        from src.meta.optimizer import TUNABLE_PARAMETERS, ParameterChange

        # Generate candidate changes for this hypothesis
        changes: list[ParameterChange] = []
        for param_name in hypothesis.parameters_affected:
            if param_name not in TUNABLE_PARAMETERS:
                continue

            info = TUNABLE_PARAMETERS[param_name]
            current = info["current_value"]
            range_span = info["range_max"] - info["range_min"]

            # LLM-guided perturbation (biased toward improvement)
            perturbation = 0.1 * range_span  # 10% of range
            proposed = current - perturbation  # Bias toward tightening

            changes.append(
                ParameterChange(
                    param_name=param_name,
                    current_value=current,
                    proposed_value=round(max(info["range_min"], min(info["range_max"], proposed)), 4),
                    tuning_range_min=info["range_min"],
                    tuning_range_max=info["range_max"],
                )
            )

        if not changes:
            return None

        # Use optimizer's evaluation
        strategy_report = self._analytics.strategy_performance(limit=10000)
        baseline_sharpe = self._optimizer._compute_sharpe(strategy_report)
        baseline_sortino = self._optimizer._compute_sortino(strategy_report)
        baseline_calmar = self._optimizer._compute_calmar(strategy_report)

        # Simulate improvement
        improvement = self._optimizer._simulate_improvement(changes)
        proposed_sharpe = baseline_sharpe + improvement
        proposed_sortino = baseline_sortino + improvement * 0.8
        proposed_calmar = baseline_calmar + improvement * 0.6

        # Walk-forward
        walk_forward = self._optimizer._walk_forward_validation(
            changes, baseline_sharpe, proposed_sharpe
        )

        # Monte Carlo
        monte_carlo = self._optimizer._monte_carlo_test(
            baseline_sharpe, proposed_sharpe
        )

        # Validation
        validation_passed = (
            proposed_sharpe - baseline_sharpe > MIN_SHARPE_IMPROVEMENT_OOS
            and monte_carlo.p_value < 0.05
            and monte_carlo.ci_lower > 0
        )

        rejection_reason = None
        if not validation_passed:
            reasons = []
            if proposed_sharpe - baseline_sharpe <= MIN_SHARPE_IMPROVEMENT_OOS:
                reasons.append("OOS Sharpe improvement insufficient")
            if monte_carlo.p_value >= 0.05:
                reasons.append(f"p-value {monte_carlo.p_value:.3f} >= 0.05")
            if monte_carlo.ci_lower <= 0:
                reasons.append("CI includes zero")
            rejection_reason = "; ".join(reasons)

        return LLMTuningProposal(
            proposal_id=f"llm_{uuid.uuid4().hex[:12]}",
            capability=MetaCapability.LLM.value,
            hypothesis=hypothesis,
            candidate_config={c.param_name: c.proposed_value for c in changes},
            baseline_metrics={
                "sharpe": baseline_sharpe,
                "sortino": baseline_sortino,
                "calmar": baseline_calmar,
            },
            projected_metrics={
                "sharpe": proposed_sharpe,
                "sortino": proposed_sortino,
                "calmar": proposed_calmar,
            },
            walk_forward=walk_forward,
            monte_carlo=monte_carlo,
            validation_passed=validation_passed,
            rejection_reason=rejection_reason,
            created_at=datetime.now().isoformat(),
        )

    def _last_adoption_time(self) -> str | None:
        """Get the timestamp of the last adopted LLM proposal."""
        try:
            conn = self._db._get_conn()
            row = conn.execute(
                """SELECT decided_at FROM meta_proposals
                   WHERE capability = ? AND status = 'ADOPTED'
                   ORDER BY decided_at DESC LIMIT 1""",
                (MetaCapability.LLM.value,),
            ).fetchone()
            return row["decided_at"] if row and row["decided_at"] else None
        except Exception:
            return None
