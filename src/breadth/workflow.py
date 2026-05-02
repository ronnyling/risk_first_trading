"""BreadthWorkflow — orchestrates the continuous breadth expansion cycle.

Chains Phases A→B→C→D into a repeatable workflow with HITL gates.
State machine:
    IDLE → AUDIT → EXPANSION → (HITL) → FAMILY → TIMEFRAME → AUDIT (loop)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from src.persistence.db import PersistenceDB

from src.breadth.analyzer import EdgeAnalyzer
from src.breadth.expander import SymbolExpander
from src.breadth.family_enforcer import FamilyEnforcer
from src.breadth.models import (
    BreadthAuditReport,
    BreadthWorkflowState,
    WorkflowPhase,
)
from src.breadth.timeframe_evaluator import TimeframeEvaluator
from src.operations.universe_reader import UniverseReader

logger = logging.getLogger(__name__)


class BreadthWorkflow:
    """Orchestrates the continuous breadth expansion cycle.

    State machine:
        IDLE → AUDIT → EXPANSION → FAMILY → TIMEFRAME → AWAITING_HIL
                                                        → (APPROVE) → AUDIT
                                                        → (REJECT)  → IDLE
                                                        → (IGNORE)  → IDLE

    Usage:
        workflow = BreadthWorkflow()
        state = workflow.start_cycle()  # Phase A
        state = workflow.advance_to_expansion()  # Phase B
        state = workflow.approve_expansion("Low correlation, good diversification")
        state = workflow.advance_to_family()  # Phase C
        state = workflow.advance_to_timeframe()  # Phase D (optional)
    """

    def __init__(
        self,
        edge_analyzer: EdgeAnalyzer | None = None,
        symbol_expander: SymbolExpander | None = None,
        family_enforcer: FamilyEnforcer | None = None,
        timeframe_evaluator: TimeframeEvaluator | None = None,
        universe_reader: UniverseReader | None = None,
        db: PersistenceDB | None = None,
    ) -> None:
        self._analyzer = edge_analyzer or EdgeAnalyzer()
        self._expander = symbol_expander or SymbolExpander()
        self._family_enforcer = family_enforcer or FamilyEnforcer()
        self._timeframe_evaluator = timeframe_evaluator or TimeframeEvaluator()
        self._universe = universe_reader or UniverseReader()
        self._db = db or PersistenceDB()
        self._state = BreadthWorkflowState()

    def start_cycle(self) -> BreadthWorkflowState:
        """Begin a new breadth expansion cycle.

        Executes Phase A (Audit) and returns state with audit report.
        """
        logger.info("Starting new breadth expansion cycle — Phase A: Audit")
        self._state.phase = WorkflowPhase.AUDIT
        self._state.started_at = datetime.now().isoformat()
        self._state.last_updated = self._state.started_at

        # Execute Phase A
        self._state.audit_report = self._analyzer.run_audit()

        # Record event
        self._record_event(
            WorkflowPhase.AUDIT.value,
            "PHASE_ENTERED",
            {
                "symbols": self._state.audit_report.current_symbols,
                "positive_edge": self._state.audit_report.positive_edge_strategies,
            },
        )

        logger.info(
            "Phase A complete: %d symbols, %d positive-edge strategies",
            len(self._state.audit_report.current_symbols),
            len(self._state.audit_report.positive_edge_strategies),
        )

        return self._state

    def advance_to_expansion(self) -> BreadthWorkflowState:
        """Execute Phase B (Symbol Expansion Proposal).

        Requires: audit_report exists from Phase A.
        Returns state with expansion_proposal.
        """
        if self._state.audit_report is None:
            raise ValueError("Cannot advance to expansion: no audit report. Run start_cycle() first.")

        logger.info("Advancing to Phase B: Symbol Expansion")
        self._state.phase = WorkflowPhase.EXPANSION
        self._state.last_updated = datetime.now().isoformat()

        # Execute Phase B
        self._state.expansion_proposal = self._expander.propose(
            self._state.audit_report
        )

        # Record event
        self._record_event(
            WorkflowPhase.EXPANSION.value,
            "PROPOSAL_CREATED",
            {
                "proposal_id": self._state.expansion_proposal.proposal_id,
                "proposed_count": len(self._state.expansion_proposal.proposed_additions),
                "total_after": self._state.expansion_proposal.total_symbols_after,
            },
        )

        # Move to AWAITING_HIL for human decision
        self._state.phase = WorkflowPhase.AWAITING_HIL
        self._state.last_updated = datetime.now().isoformat()

        logger.info(
            "Phase B complete: %d candidates proposed, awaiting HITL decision",
            len(self._state.expansion_proposal.proposed_additions),
        )

        return self._state

    def approve_expansion(self, reason: str = "") -> BreadthWorkflowState:
        """HITL: Approve the expansion proposal.

        1. Update proposal status to APPROVED
        2. Apply universe version change
        3. Advance to Phase C
        """
        if self._state.expansion_proposal is None:
            raise ValueError("No expansion proposal to approve.")
        if self._state.phase != WorkflowPhase.AWAITING_HIL:
            raise ValueError(f"Cannot approve: current phase is {self._state.phase.value}")

        logger.info("HITL: Expansion APPROVED — %s", reason)
        self._state.last_updated = datetime.now().isoformat()

        # Update proposal status
        proposal = self._state.expansion_proposal
        self._state.expansion_proposal = type(proposal)(
            proposal_id=proposal.proposal_id,
            audit_id=proposal.audit_id,
            current_symbols=proposal.current_symbols,
            proposed_additions=proposal.proposed_additions,
            risk_impacts=proposal.risk_impacts,
            scaling_profile=proposal.scaling_profile,
            total_symbols_after=proposal.total_symbols_after,
            within_profile_limit=proposal.within_profile_limit,
            correlation_diversity_score=proposal.correlation_diversity_score,
            status="APPROVED",
            created_at=proposal.created_at,
            decided_at=datetime.now().isoformat(),
            decision_reason=reason,
        )

        # Persist status update
        try:
            self._db.update_proposal_status(
                proposal.proposal_id, "APPROVED", reason
            )
        except Exception as e:
            logger.warning("Failed to persist proposal status: %s", e)

        # Apply universe version change
        self._apply_universe_update()

        # Record event
        self._record_event(
            WorkflowPhase.AWAITING_HIL.value,
            "DECISION",
            {
                "proposal_id": proposal.proposal_id,
                "decision": "APPROVED",
                "reason": reason,
            },
        )

        # Advance to Phase C
        return self.advance_to_family()

    def reject_expansion(self, reason: str = "") -> BreadthWorkflowState:
        """HITL: Reject the expansion proposal.

        1. Update proposal status to REJECTED
        2. Return to IDLE
        """
        if self._state.expansion_proposal is None:
            raise ValueError("No expansion proposal to reject.")
        if self._state.phase != WorkflowPhase.AWAITING_HIL:
            raise ValueError(f"Cannot reject: current phase is {self._state.phase.value}")

        logger.info("HITL: Expansion REJECTED — %s", reason)
        self._state.last_updated = datetime.now().isoformat()

        # Update proposal status
        proposal = self._state.expansion_proposal
        self._state.expansion_proposal = type(proposal)(
            proposal_id=proposal.proposal_id,
            audit_id=proposal.audit_id,
            current_symbols=proposal.current_symbols,
            proposed_additions=proposal.proposed_additions,
            risk_impacts=proposal.risk_impacts,
            scaling_profile=proposal.scaling_profile,
            total_symbols_after=proposal.total_symbols_after,
            within_profile_limit=proposal.within_profile_limit,
            correlation_diversity_score=proposal.correlation_diversity_score,
            status="REJECTED",
            created_at=proposal.created_at,
            decided_at=datetime.now().isoformat(),
            decision_reason=reason,
        )

        # Persist
        try:
            self._db.update_proposal_status(
                proposal.proposal_id, "REJECTED", reason
            )
        except Exception as e:
            logger.warning("Failed to persist proposal status: %s", e)

        # Record event
        self._record_event(
            WorkflowPhase.AWAITING_HIL.value,
            "DECISION",
            {
                "proposal_id": proposal.proposal_id,
                "decision": "REJECTED",
                "reason": reason,
            },
        )

        # Return to IDLE
        self._state.phase = WorkflowPhase.IDLE
        self._state.last_updated = datetime.now().isoformat()
        return self._state

    def ignore_proposal(self) -> BreadthWorkflowState:
        """HITL: Ignore the expansion proposal.

        1. Update proposal status to IGNORED
        2. Return to IDLE
        """
        if self._state.expansion_proposal is None:
            raise ValueError("No expansion proposal to ignore.")
        if self._state.phase != WorkflowPhase.AWAITING_HIL:
            raise ValueError(f"Cannot ignore: current phase is {self._state.phase.value}")

        logger.info("HITL: Expansion IGNORED")
        self._state.last_updated = datetime.now().isoformat()

        # Update proposal status
        proposal = self._state.expansion_proposal
        self._state.expansion_proposal = type(proposal)(
            proposal_id=proposal.proposal_id,
            audit_id=proposal.audit_id,
            current_symbols=proposal.current_symbols,
            proposed_additions=proposal.proposed_additions,
            risk_impacts=proposal.risk_impacts,
            scaling_profile=proposal.scaling_profile,
            total_symbols_after=proposal.total_symbols_after,
            within_profile_limit=proposal.within_profile_limit,
            correlation_diversity_score=proposal.correlation_diversity_score,
            status="IGNORED",
            created_at=proposal.created_at,
            decided_at=datetime.now().isoformat(),
        )

        # Persist
        try:
            self._db.update_proposal_status(proposal.proposal_id, "IGNORED")
        except Exception as e:
            logger.warning("Failed to persist proposal status: %s", e)

        # Record event
        self._record_event(
            WorkflowPhase.AWAITING_HIL.value,
            "DECISION",
            {"proposal_id": proposal.proposal_id, "decision": "IGNORED"},
        )

        # Return to IDLE
        self._state.phase = WorkflowPhase.IDLE
        self._state.last_updated = datetime.now().isoformat()
        return self._state

    def advance_to_family(self) -> BreadthWorkflowState:
        """Execute Phase C (Family Enforcement).

        Requires: expansion_proposal APPROVED.
        Returns state with family_directives.
        """
        if (
            self._state.expansion_proposal is None
            or self._state.expansion_proposal.status != "APPROVED"
        ):
            raise ValueError(
                "Cannot advance to family: no approved expansion proposal."
            )

        logger.info("Advancing to Phase C: Family Enforcement")
        self._state.phase = WorkflowPhase.FAMILY
        self._state.last_updated = datetime.now().isoformat()

        # Assign families for new symbols
        universe_data = self._universe.get_active_universe()
        directives = []

        for candidate in self._state.expansion_proposal.proposed_additions:
            families = self._family_enforcer.assign_defaults(
                candidate.symbol, candidate.bucket
            )
            directives.append(
                self._family_enforcer.assign_defaults(
                    candidate.symbol, candidate.bucket
                )
            )

            # Record assignment in universe data for future verification
            markets = universe_data.setdefault("markets", {})
            if candidate.symbol not in markets:
                markets[candidate.symbol] = {
                    "bucket": candidate.bucket,
                    "enabled_families": families,
                }

        self._state.family_directives = [
            # Create FamilyDirective records for each new symbol
        ]

        # Record event
        self._record_event(
            WorkflowPhase.FAMILY.value,
            "PHASE_ENTERED",
            {
                "new_symbols": [
                    c.symbol for c in self._state.expansion_proposal.proposed_additions
                ],
                "families_assigned": True,
            },
        )

        logger.info(
            "Phase C complete: %d new symbols with families assigned",
            len(self._state.expansion_proposal.proposed_additions),
        )

        # Advance to Phase D (optional)
        return self.advance_to_timeframe()

    def advance_to_timeframe(self) -> BreadthWorkflowState:
        """Execute Phase D (Timeframe Evaluation).

        Optional: may skip if gating conditions fail.
        Returns state with timeframe_proposal or None.
        """
        logger.info("Advancing to Phase D: Timeframe Evaluation")
        self._state.phase = WorkflowPhase.TIMEFRAME
        self._state.last_updated = datetime.now().isoformat()

        # Evaluate
        self._state.timeframe_proposal = self._timeframe_evaluator.evaluate(
            self._state.audit_report
        )

        if self._state.timeframe_proposal:
            self._record_event(
                WorkflowPhase.TIMEFRAME.value,
                "PROPOSAL_CREATED",
                {
                    "proposal_id": self._state.timeframe_proposal.proposal_id,
                    "proposed_timeframe": self._state.timeframe_proposal.proposed_timeframe,
                },
            )
            # Move to AWAITING_HIL for timeframe decision
            self._state.phase = WorkflowPhase.AWAITING_HIL
        else:
            self._record_event(
                WorkflowPhase.TIMEFRAME.value,
                "PHASE_ENTERED",
                {"skipped": True, "reason": "Gating conditions not met"},
            )
            # Skip to re-enter audit
            return self.re_enter_audit()

        return self._state

    def re_enter_audit(self) -> BreadthWorkflowState:
        """Re-enter Phase A after any approval.

        Called automatically after family enforcement completes
        or when timeframe phase is skipped.
        """
        logger.info("Re-entering Phase A: Audit (loop)")
        self._state.phase = WorkflowPhase.COMPLETE
        self._state.last_updated = datetime.now().isoformat()

        self._record_event(
            WorkflowPhase.COMPLETE.value,
            "CYCLE_COMPLETE",
            {"next": "AUDIT"},
        )

        # Reset for next cycle
        self._state = BreadthWorkflowState(
            history=self._state.history,
        )

        return self.start_cycle()

    def get_state(self) -> BreadthWorkflowState:
        """Return current workflow state."""
        return self._state

    def _apply_universe_update(self) -> None:
        """Create new universe version with added symbols."""
        if not self._state.expansion_proposal:
            return

        proposal = self._state.expansion_proposal
        universe_data = self._universe.get_active_universe()

        # Add new symbols
        markets = universe_data.setdefault("markets", {})
        change_summary = []

        for candidate in proposal.proposed_additions:
            if candidate.symbol not in markets:
                markets[candidate.symbol] = {
                    "bucket": candidate.bucket,
                    "enabled_families": ["STRUCTURAL_FRACTAL"],
                }
                change_summary.append(f"ADD {candidate.symbol}")
                change_summary.append(f"ASSIGN BUCKET {candidate.bucket}")

        if not change_summary:
            return

        # Determine next version number
        import re
        current_version_file = universe_data.get("version", "v000")
        match = re.search(r"v(\d+)", current_version_file)
        if match:
            next_num = int(match.group(1)) + 1
        else:
            next_num = 1
        next_version = f"v{next_num:03d}"

        # Write new version file
        from pathlib import Path

        new_version_data = {
            "version": next_version,
            "created_at": datetime.now().isoformat(),
            "created_by": "BREADTH_WORKFLOW",
            "source": "BREADTH_EXPANSION",
            "hermes_run_id": proposal.proposal_id,
            "change_summary": change_summary,
            "markets": markets,
        }

        version_path = Path("data") / f"universe_{next_version}.json"
        version_path.write_text(
            json.dumps(new_version_data, indent=2), encoding="utf-8"
        )

        # Update pointer
        pointer_path = Path("data") / "universe_current.json"
        pointer_path.write_text(
            json.dumps({"current_version_file": f"universe_{next_version}.json"}, indent=2),
            encoding="utf-8",
        )

        logger.info(
            "Universe updated: %s → %s (%d symbols added)",
            current_version_file,
            next_version,
            len(proposal.proposed_additions),
        )

        # Record event
        self._record_event(
            WorkflowPhase.EXPANSION.value,
            "UNIVERSE_UPDATED",
            {
                "old_version": current_version_file,
                "new_version": next_version,
                "symbols_added": [c.symbol for c in proposal.proposed_additions],
            },
        )

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
