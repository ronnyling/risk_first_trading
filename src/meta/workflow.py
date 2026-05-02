"""MetaWorkflow — orchestrates the meta-optimization plane.

Chains E.1-E.5 capabilities into a governed workflow with HITL gates.
State machine:
    IDLE → GATING → EVALUATING → AWAITING_HIL → APPLYING → MONITORING → COMPLETE
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from src.persistence.db import PersistenceDB

from src.meta.drift_detector import DriftDetector
from src.meta.leverage_simulator import LeverageSimulator
from src.meta.llm_tuner import LLMTuner
from src.meta.models import (
    DriftAuditReport,
    MetaCapability,
    MetaWorkflowPhase,
    MetaWorkflowState,
    OptimizationProposal,
    PolicyProposal,
    ProposalStatus,
)
from src.meta.optimizer import SelfOptimizer
from src.meta.policy_evolver import PolicyEvolver
from src.meta.strategy_mutator import StrategyMutator

logger = logging.getLogger(__name__)


class MetaWorkflow:
    """Orchestrates the meta-optimization plane.

    State machine:
        IDLE → GATING → EVALUATING → AWAITING_HIL
                                      → (ADOPT) → APPLYING → MONITORING → COMPLETE
                                      → (REJECT) → IDLE
                                      → (IGNORE) → IDLE
        IDLE → MONITORING → (DRIFT) → REVERTING → IDLE

    Usage:
        workflow = MetaWorkflow()
        state = workflow.run_optimization()
        state = workflow.run_leverage_evaluation()
    """

    def __init__(
        self,
        optimizer: SelfOptimizer | None = None,
        leverage_simulator: LeverageSimulator | None = None,
        policy_evolver: PolicyEvolver | None = None,
        llm_tuner: LLMTuner | None = None,
        strategy_mutator: StrategyMutator | None = None,
        drift_detector: DriftDetector | None = None,
        db: PersistenceDB | None = None,
    ) -> None:
        self._optimizer = optimizer or SelfOptimizer(db=db)
        self._leverage = leverage_simulator or LeverageSimulator(db=db)
        self._policy = policy_evolver or PolicyEvolver(db=db)
        self._llm = llm_tuner or LLMTuner(db=db)
        self._mutator = strategy_mutator or StrategyMutator(db=db)
        self._drift = drift_detector or DriftDetector(db=db)
        self._db = db or PersistenceDB()
        self._state = MetaWorkflowState()

    def run_optimization(self) -> MetaWorkflowState:
        """Run the self-optimization capability.

        Returns:
            MetaWorkflowState with proposal if one was generated.
        """
        logger.info("Running self-optimization")
        self._state.phase = MetaWorkflowPhase.GATING
        self._state.active_capability = MetaCapability.OPTIMIZER.value
        self._state.started_at = datetime.now().isoformat()
        self._state.last_updated = self._state.started_at

        # Check gating
        allowed, reason = self._optimizer.check_gating()
        if not allowed:
            self._state.phase = MetaWorkflowPhase.BLOCKED
            self._record_event(
                MetaWorkflowPhase.BLOCKED.value,
                "GATING_FAILED",
                {"capability": MetaCapability.OPTIMIZER.value, "reason": reason},
            )
            return self._state

        # Evaluate
        self._state.phase = MetaWorkflowPhase.EVALUATING
        proposal = self._optimizer.optimize()

        if proposal is None:
            self._state.phase = MetaWorkflowPhase.IDLE
            self._record_event(
                MetaWorkflowPhase.EVALUATING.value,
                "NO_IMPROVEMENT",
                {"capability": MetaCapability.OPTIMIZER.value},
            )
            return self._state

        # Present for HITL
        self._state.proposal = proposal
        self._state.phase = MetaWorkflowPhase.AWAITING_HIL
        self._state.last_updated = datetime.now().isoformat()

        self._record_event(
            MetaWorkflowPhase.AWAITING_HIL.value,
            "PROPOSAL_READY",
            {
                "capability": MetaCapability.OPTIMIZER.value,
                "proposal_id": proposal.proposal_id,
            },
        )

        return self._state

    def run_leverage_evaluation(self) -> MetaWorkflowState:
        """Run the leverage evaluation capability.

        Returns:
            MetaWorkflowState with report if one was generated.
        """
        logger.info("Running leverage evaluation")
        self._state.phase = MetaWorkflowPhase.GATING
        self._state.active_capability = MetaCapability.LEVERAGE.value
        self._state.started_at = datetime.now().isoformat()
        self._state.last_updated = self._state.started_at

        # Check gating
        allowed, reason = self._leverage.check_gating()
        if not allowed:
            self._state.phase = MetaWorkflowPhase.BLOCKED
            self._record_event(
                MetaWorkflowPhase.BLOCKED.value,
                "GATING_FAILED",
                {"capability": MetaCapability.LEVERAGE.value, "reason": reason},
            )
            return self._state

        # Evaluate
        self._state.phase = MetaWorkflowPhase.EVALUATING
        report = self._leverage.evaluate()

        if report is None:
            self._state.phase = MetaWorkflowPhase.IDLE
            self._record_event(
                MetaWorkflowPhase.EVALUATING.value,
                "NO_REPORT",
                {"capability": MetaCapability.LEVERAGE.value},
            )
            return self._state

        # Present for HITL
        self._state.proposal = report
        self._state.phase = MetaWorkflowPhase.AWAITING_HIL
        self._state.last_updated = datetime.now().isoformat()

        self._record_event(
            MetaWorkflowPhase.AWAITING_HIL.value,
            "REPORT_READY",
            {
                "capability": MetaCapability.LEVERAGE.value,
                "report_id": report.report_id,
            },
        )

        return self._state

    def run_policy_review(self) -> MetaWorkflowState:
        """Run the policy evolution capability.

        Returns:
            MetaWorkflowState with proposal if one was generated.
        """
        logger.info("Running policy review")
        self._state.phase = MetaWorkflowPhase.GATING
        self._state.active_capability = MetaCapability.POLICY.value
        self._state.started_at = datetime.now().isoformat()
        self._state.last_updated = self._state.started_at

        # Check gating
        allowed, reason = self._policy.check_gating()
        if not allowed:
            self._state.phase = MetaWorkflowPhase.BLOCKED
            self._record_event(
                MetaWorkflowPhase.BLOCKED.value,
                "GATING_FAILED",
                {"capability": MetaCapability.POLICY.value, "reason": reason},
            )
            return self._state

        # Evaluate
        self._state.phase = MetaWorkflowPhase.EVALUATING
        proposal = self._policy.review()

        if proposal is None:
            self._state.phase = MetaWorkflowPhase.IDLE
            self._record_event(
                MetaWorkflowPhase.EVALUATING.value,
                "NO_CHANGES",
                {"capability": MetaCapability.POLICY.value},
            )
            return self._state

        # Present for HITL
        self._state.proposal = proposal
        self._state.phase = MetaWorkflowPhase.AWAITING_HIL
        self._state.last_updated = datetime.now().isoformat()

        self._record_event(
            MetaWorkflowPhase.AWAITING_HIL.value,
            "PROPOSAL_READY",
            {
                "capability": MetaCapability.POLICY.value,
                "proposal_id": proposal.proposal_id,
            },
        )

        return self._state

    def run_llm_tuning(self) -> MetaWorkflowState:
        """Run the LLM tuning capability.

        Returns:
            MetaWorkflowState with proposal if one was generated.
        """
        logger.info("Running LLM tuning")
        self._state.phase = MetaWorkflowPhase.GATING
        self._state.active_capability = MetaCapability.LLM.value
        self._state.started_at = datetime.now().isoformat()
        self._state.last_updated = self._state.started_at

        # Check gating
        allowed, reason = self._llm.check_gating()
        if not allowed:
            self._state.phase = MetaWorkflowPhase.BLOCKED
            self._record_event(
                MetaWorkflowPhase.BLOCKED.value,
                "GATING_FAILED",
                {"capability": MetaCapability.LLM.value, "reason": reason},
            )
            return self._state

        # Evaluate
        self._state.phase = MetaWorkflowPhase.EVALUATING
        proposal = self._llm.tune()

        if proposal is None:
            self._state.phase = MetaWorkflowPhase.IDLE
            self._record_event(
                MetaWorkflowPhase.EVALUATING.value,
                "NO_IMPROVEMENT",
                {"capability": MetaCapability.LLM.value},
            )
            return self._state

        # Present for HITL
        self._state.proposal = proposal
        self._state.phase = MetaWorkflowPhase.AWAITING_HIL
        self._state.last_updated = datetime.now().isoformat()

        self._record_event(
            MetaWorkflowPhase.AWAITING_HIL.value,
            "PROPOSAL_READY",
            {
                "capability": MetaCapability.LLM.value,
                "proposal_id": proposal.proposal_id,
            },
        )

        return self._state

    def check_drift(self) -> MetaWorkflowState:
        """Check for performance drift.

        Returns:
            MetaWorkflowState with drift report.
        """
        logger.info("Checking for performance drift")
        self._state.phase = MetaWorkflowPhase.MONITORING
        self._state.active_capability = "DRIFT"
        self._state.started_at = datetime.now().isoformat()
        self._state.last_updated = self._state.started_at

        report = self._drift.check_drift()
        self._state.drift_report = report

        if report.reversion_recommended:
            self._record_event(
                MetaWorkflowPhase.MONITORING.value,
                "DRIFT_DETECTED",
                {
                    "severity": report.severity,
                    "reversion_recommended": True,
                    "proposal_id": report.adopted_proposal_id,
                },
            )
        else:
            self._record_event(
                MetaWorkflowPhase.MONITORING.value,
                "DRIFT_OK",
                {"severity": report.severity},
            )

        self._state.phase = MetaWorkflowPhase.IDLE
        self._state.last_updated = datetime.now().isoformat()

        return self._state

    def adopt_proposal(self, reason: str = "") -> MetaWorkflowState:
        """HITL: Adopt the current proposal.

        Args:
            reason: Optional reason for adoption.

        Returns:
            Updated MetaWorkflowState.
        """
        if self._state.proposal is None:
            raise ValueError("No proposal to adopt.")
        if self._state.phase != MetaWorkflowPhase.AWAITING_HIL:
            raise ValueError(f"Cannot adopt: current phase is {self._state.phase.value}")

        logger.info("HITL: Proposal ADOPTED — %s", reason)
        self._state.last_updated = datetime.now().isoformat()

        # Update proposal status
        proposal = self._state.proposal
        if hasattr(proposal, "proposal_id"):
            try:
                self._db.update_meta_proposal_status(
                    proposal.proposal_id, "ADOPTED", reason
                )
            except Exception as e:
                logger.warning("Failed to persist adoption: %s", e)

        # Record event
        self._record_event(
            MetaWorkflowPhase.AWAITING_HIL.value,
            "DECISION",
            {
                "proposal_id": getattr(proposal, "proposal_id", "unknown"),
                "decision": "ADOPTED",
                "reason": reason,
            },
        )

        # Move to APPLYING
        self._state.phase = MetaWorkflowPhase.APPLYING
        self._state.last_updated = datetime.now().isoformat()

        # Move to MONITORING
        self._state.phase = MetaWorkflowPhase.MONITORING
        self._state.last_updated = datetime.now().isoformat()

        # Move to COMPLETE
        self._state.phase = MetaWorkflowPhase.COMPLETE
        self._state.last_updated = datetime.now().isoformat()

        self._record_event(
            MetaWorkflowPhase.COMPLETE.value,
            "CYCLE_COMPLETE",
            {"next": "IDLE"},
        )

        # Reset for next cycle
        self._state.phase = MetaWorkflowPhase.IDLE
        self._state.proposal = None
        self._state.active_capability = None

        return self._state

    def reject_proposal(self, reason: str = "") -> MetaWorkflowState:
        """HITL: Reject the current proposal.

        Args:
            reason: Optional reason for rejection.

        Returns:
            Updated MetaWorkflowState.
        """
        if self._state.proposal is None:
            raise ValueError("No proposal to reject.")
        if self._state.phase != MetaWorkflowPhase.AWAITING_HIL:
            raise ValueError(f"Cannot reject: current phase is {self._state.phase.value}")

        logger.info("HITL: Proposal REJECTED — %s", reason)
        self._state.last_updated = datetime.now().isoformat()

        # Update proposal status
        proposal = self._state.proposal
        if hasattr(proposal, "proposal_id"):
            try:
                self._db.update_meta_proposal_status(
                    proposal.proposal_id, "REJECTED", reason
                )
            except Exception as e:
                logger.warning("Failed to persist rejection: %s", e)

        # Record event
        self._record_event(
            MetaWorkflowPhase.AWAITING_HIL.value,
            "DECISION",
            {
                "proposal_id": getattr(proposal, "proposal_id", "unknown"),
                "decision": "REJECTED",
                "reason": reason,
            },
        )

        # Return to IDLE
        self._state.phase = MetaWorkflowPhase.IDLE
        self._state.proposal = None
        self._state.active_capability = None
        self._state.last_updated = datetime.now().isoformat()

        return self._state

    def ignore_proposal(self) -> MetaWorkflowState:
        """HITL: Ignore the current proposal.

        Returns:
            Updated MetaWorkflowState.
        """
        if self._state.proposal is None:
            raise ValueError("No proposal to ignore.")
        if self._state.phase != MetaWorkflowPhase.AWAITING_HIL:
            raise ValueError(f"Cannot ignore: current phase is {self._state.phase.value}")

        logger.info("HITL: Proposal IGNORED")
        self._state.last_updated = datetime.now().isoformat()

        # Update proposal status
        proposal = self._state.proposal
        if hasattr(proposal, "proposal_id"):
            try:
                self._db.update_meta_proposal_status(
                    proposal.proposal_id, "IGNORED"
                )
            except Exception as e:
                logger.warning("Failed to persist ignore: %s", e)

        # Record event
        self._record_event(
            MetaWorkflowPhase.AWAITING_HIL.value,
            "DECISION",
            {
                "proposal_id": getattr(proposal, "proposal_id", "unknown"),
                "decision": "IGNORED",
            },
        )

        # Return to IDLE
        self._state.phase = MetaWorkflowPhase.IDLE
        self._state.proposal = None
        self._state.active_capability = None
        self._state.last_updated = datetime.now().isoformat()

        return self._state

    def get_state(self) -> MetaWorkflowState:
        """Return current workflow state."""
        return self._state

    def _record_event(
        self, phase: str, event_type: str, event_data: dict
    ) -> None:
        """Record a workflow event to the audit trail."""
        event = {
            "phase": phase,
            "event_type": event_type,
            "event_data": event_data,
            "created_at": datetime.now().isoformat(),
        }
        self._state.history.append(event)

        try:
            self._db.record_workflow_event(phase, event_type, event_data)
        except Exception as e:
            logger.debug("Failed to persist workflow event: %s", e)
