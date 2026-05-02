"""PolicyEvolver — evaluates and proposes system policy changes based on evidence.

Phase E.3 of the meta-optimization plane.
Analyzes workflow history, expansion proposals, and system performance
to identify policy evolution opportunities. All outputs are advisory.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from src.analytics.engine import AnalyticsEngine
from src.persistence.db import PersistenceDB

from src.meta.models import (
    MetaCapability,
    PolicyChange,
    PolicyEvidence,
    PolicyProposal,
    ProposalStatus,
)

logger = logging.getLogger(__name__)

# Immutable policies — never proposed for change
IMMUTABLE_POLICIES = {
    "risk_limits.yaml",
    "engine.yaml",
    "strategies.yaml",
}

# Policy change limits
MAX_CHANGES_PER_POLICY_PER_QUARTER = 1


class PolicyEvolver:
    """Evaluates and proposes system policy changes based on evidence.

    Analyzes accumulated evidence from workflow history, expansion proposals,
    and performance data to identify policy evolution opportunities.

    Usage:
        evolver = PolicyEvolver()
        proposal = evolver.review()
    """

    def __init__(
        self,
        analytics: AnalyticsEngine | None = None,
        db: PersistenceDB | None = None,
    ) -> None:
        self._analytics = analytics or AnalyticsEngine()
        self._db = db or PersistenceDB()

    def check_gating(self) -> tuple[bool, str]:
        """Check if policy review is allowed.

        Returns:
            Tuple of (allowed, reason).
        """
        # Check for active expansion proposals
        try:
            pending = self._db.get_pending_proposals()
            if pending:
                return False, f"{len(pending)} pending expansion proposal(s)"
        except Exception:
            pass

        # Check quarterly change limit
        if self._policy_changes_this_quarter() >= MAX_CHANGES_PER_POLICY_PER_QUARTER:
            return False, "Quarterly policy change limit reached"

        return True, "All gating conditions pass"

    def review(self) -> PolicyProposal | None:
        """Run the full policy review.

        Returns:
            PolicyProposal if evidence supports a change, None otherwise.
        """
        allowed, reason = self.check_gating()
        if not allowed:
            logger.info("Policy review gated: %s", reason)
            return None

        logger.info("Starting policy review")

        # Gather evidence from multiple sources
        evidence: list[PolicyEvidence] = []
        evidence.extend(self._analyze_expansion_history())
        evidence.extend(self._analyze_family_directives())
        evidence.extend(self._analyze_scaling_utilization())

        if not evidence:
            logger.info("No evidence for policy changes")
            return None

        # Generate policy change proposals
        changes = self._generate_policy_changes(evidence)

        if not changes:
            logger.info("No actionable policy changes identified")
            return None

        proposal = PolicyProposal(
            proposal_id=f"pol_{uuid.uuid4().hex[:12]}",
            capability=MetaCapability.POLICY.value,
            changes=changes,
            evidence=evidence,
            rollback_available=True,
            created_at=datetime.now().isoformat(),
        )

        # Persist proposal
        try:
            self._db.record_meta_proposal(proposal)
        except Exception as e:
            logger.warning("Failed to persist policy proposal: %s", e)

        logger.info(
            "Policy proposal created: %d changes from %d evidence sources",
            len(changes),
            len(set(e.source for e in evidence)),
        )

        return proposal

    def _analyze_expansion_history(self) -> list[PolicyEvidence]:
        """Analyze expansion proposal history for policy insights."""
        evidence: list[PolicyEvidence] = []

        try:
            conn = self._db._get_conn()
            rows = conn.execute(
                """SELECT scaling_profile, status, COUNT(*) as cnt
                   FROM expansion_proposals
                   GROUP BY scaling_profile, status"""
            ).fetchall()

            pool_approvals: dict[str, dict] = {}
            for row in rows:
                profile = row["scaling_profile"]
                status = row["status"]
                cnt = row["cnt"]
                if profile not in pool_approvals:
                    pool_approvals[profile] = {}
                pool_approvals[profile][status] = cnt

            for profile, stats in pool_approvals.items():
                total = sum(stats.values())
                approved = stats.get("APPROVED", 0)
                if total > 0:
                    approval_rate = approved / total
                    evidence.append(
                        PolicyEvidence(
                            source="expansion_proposals",
                            metric="approval_rate",
                            value=round(approval_rate, 4),
                            description=(
                                f"Profile {profile}: {approved}/{total} proposals "
                                f"approved ({approval_rate:.0%})"
                            ),
                        )
                    )
        except Exception as e:
            logger.debug("Could not analyze expansion history: %s", e)

        return evidence

    def _analyze_family_directives(self) -> list[PolicyEvidence]:
        """Analyze family directive history for assignment mismatches."""
        evidence: list[PolicyEvidence] = []

        try:
            conn = self._db._get_conn()
            rows = conn.execute(
                """SELECT event_data FROM breadth_workflow_history
                   WHERE event_type = 'PHASE_ENTERED' AND workflow_phase = 'FAMILY'
                   ORDER BY created_at DESC LIMIT 20"""
            ).fetchall()

            mismatch_count = 0
            for row in rows:
                data = json.loads(row["event_data"]) if isinstance(row["event_data"], str) else row["event_data"]
                if data.get("families_assigned"):
                    # Count as evidence that family assignment is active
                    pass

            if rows:
                evidence.append(
                    PolicyEvidence(
                        source="workflow_history",
                        metric="family_assignment_active",
                        value=float(len(rows)),
                        description=f"{len(rows)} family assignment events recorded",
                    )
                )
        except Exception as e:
            logger.debug("Could not analyze family directives: %s", e)

        return evidence

    def _analyze_scaling_utilization(self) -> list[PolicyEvidence]:
        """Analyze scaling profile utilization for capacity insights."""
        evidence: list[PolicyEvidence] = []

        try:
            from src.operations.universe_reader import UniverseReader
            reader = UniverseReader()
            symbols = reader.get_enabled_markets()

            from src.operations.scaling import ScalingConfig
            scaling = ScalingConfig()
            profile = scaling.load_active_profile()

            utilization = len(symbols) / profile.max_symbols if profile.max_symbols > 0 else 0

            evidence.append(
                PolicyEvidence(
                    source="scaling_profiles",
                    metric="universe_utilization",
                    value=round(utilization, 4),
                    description=(
                        f"Universe utilization: {len(symbols)}/{profile.max_symbols} "
                        f"({utilization:.0%})"
                    ),
                )
            )
        except Exception as e:
            logger.debug("Could not analyze scaling utilization: %s", e)

        return evidence

    def _generate_policy_changes(
        self, evidence: list[PolicyEvidence]
    ) -> list[PolicyChange]:
        """Generate policy change proposals from evidence."""
        changes: list[PolicyChange] = []

        for ev in evidence:
            if ev.metric == "approval_rate" and ev.value < 0.3:
                # Low approval rate suggests expansion pool needs refresh
                changes.append(
                    PolicyChange(
                        policy_name="expansion_pool_refresh",
                        config_file="config/expansion_pools.json",
                        current_value="current",
                        proposed_value="review_and_refresh",
                    )
                )

            elif ev.metric == "universe_utilization" and ev.value > 0.8:
                # High utilization suggests scaling profile may need upgrade
                changes.append(
                    PolicyChange(
                        policy_name="scaling_profile_upgrade",
                        config_file="config/scaling_profiles.json",
                        current_value="SMALL",
                        proposed_value="MEDIUM",
                    )
                )

        return changes

    def _policy_changes_this_quarter(self) -> int:
        """Count adopted policy changes in the current quarter."""
        try:
            conn = self._db._get_conn()
            now = datetime.now()
            quarter_start = datetime(now.year, ((now.month - 1) // 3) * 3 + 1, 1)
            row = conn.execute(
                """SELECT COUNT(*) as cnt FROM meta_proposals
                   WHERE capability = ? AND status = 'ADOPTED'
                   AND created_at >= ?""",
                (MetaCapability.POLICY.value, quarter_start.isoformat()),
            ).fetchone()
            return row["cnt"] if row else 0
        except Exception:
            return 0
