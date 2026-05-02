"""DriftDetector — detects performance degradation after meta-optimization adoptions.

Phase E.6 of the meta-optimization plane.
Monitors 30-day rolling Sharpe and other metrics to detect optimization chasing noise.
Triggers auto-reversion when degradation exceeds thresholds.
"""

from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime

from src.analytics.engine import AnalyticsEngine
from src.persistence.db import PersistenceDB

from src.meta.models import (
    DriftAuditReport,
    DriftMetric,
    DriftSeverity,
    MetaCapability,
)

logger = logging.getLogger(__name__)

# Drift detection thresholds
MILD_THRESHOLD = 0.1
MODERATE_THRESHOLD = 0.2
SEVERE_THRESHOLD = 0.3
CRITICAL_DD_THRESHOLD = 0.15
AUTO_REVERT_DD_THRESHOLD = 0.15
REVERT_COOLDOWN_DAYS = 90


class DriftDetector:
    """Detects performance degradation after meta-optimization adoptions.

    Monitors rolling metrics and compares against post-adoption baselines.
    Triggers reversion when degradation exceeds thresholds.

    Usage:
        detector = DriftDetector()
        report = detector.check_drift()
    """

    def __init__(
        self,
        analytics: AnalyticsEngine | None = None,
        db: PersistenceDB | None = None,
    ) -> None:
        self._analytics = analytics or AnalyticsEngine()
        self._db = db or PersistenceDB()

    def check_drift(self) -> DriftAuditReport:
        """Check for performance drift since last adoption.

        Returns:
            DriftAuditReport with severity and metrics.
        """
        logger.info("Checking for performance drift")

        # Find last adopted proposal
        last_adoption = self._last_adoption()
        if not last_adoption:
            return DriftAuditReport(
                report_id=f"drift_{uuid.uuid4().hex[:12]}",
                severity=DriftSeverity.NONE.value,
                metrics=[],
                adopted_proposal_id=None,
                days_since_adoption=0,
                reversion_recommended=False,
                created_at=datetime.now().isoformat(),
            )

        proposal_id = last_adoption["proposal_id"]
        adopted_at = datetime.fromisoformat(last_adoption["decided_at"])
        days_since = (datetime.now() - adopted_at).days

        # Compute current metrics
        strategy_report = self._analytics.strategy_performance(limit=1000)
        current_sharpe = self._compute_sharpe(strategy_report)

        # Get baseline metrics from proposal
        baseline_sharpe = last_adoption.get("baseline_sharpe", current_sharpe)
        if isinstance(baseline_sharpe, str):
            try:
                baseline_sharpe = float(baseline_sharpe)
            except (ValueError, TypeError):
                baseline_sharpe = current_sharpe

        # Compute drift metrics
        metrics: list[DriftMetric] = []

        # Sharpe drift
        sharpe_change = current_sharpe - baseline_sharpe
        sharpe_drift = DriftMetric(
            metric_name="sharpe_ratio",
            baseline_value=baseline_sharpe,
            current_value=current_sharpe,
            change=sharpe_change,
            threshold=SEVERE_THRESHOLD,
            breached=sharpe_change < -SEVERE_THRESHOLD,
        )
        metrics.append(sharpe_drift)

        # Drawdown drift
        risk_report = self._analytics.risk_utilization(limit=1000)
        current_dd = risk_report.max_drawdown_observed
        dd_drift = DriftMetric(
            metric_name="max_drawdown",
            baseline_value=0.0,  # Assume baseline DD was acceptable
            current_value=current_dd,
            change=current_dd,
            threshold=CRITICAL_DD_THRESHOLD,
            breached=current_dd > CRITICAL_DD_THRESHOLD,
        )
        metrics.append(dd_drift)

        # Determine severity
        severity = self._determine_severity(metrics)

        # Check if auto-revert is needed
        reversion_recommended = severity in (
            DriftSeverity.SEVERE.value,
            DriftSeverity.CRITICAL.value,
        )

        report = DriftAuditReport(
            report_id=f"drift_{uuid.uuid4().hex[:12]}",
            severity=severity,
            metrics=metrics,
            adopted_proposal_id=proposal_id,
            days_since_adoption=days_since,
            reversion_recommended=reversion_recommended,
            reversion_reason=(
                f"Performance degradation detected: {severity}"
                if reversion_recommended
                else None
            ),
            created_at=datetime.now().isoformat(),
        )

        # Auto-revert if critical
        if severity == DriftSeverity.CRITICAL.value:
            self._auto_revert(proposal_id)

        logger.info(
            "Drift check complete: severity=%s, reversion=%s",
            severity,
            reversion_recommended,
        )

        return report

    def _determine_severity(self, metrics: list[DriftMetric]) -> str:
        """Determine drift severity from metrics."""
        severity_order = {
            DriftSeverity.NONE.value: 0,
            DriftSeverity.MILD.value: 1,
            DriftSeverity.MODERATE.value: 2,
            DriftSeverity.SEVERE.value: 3,
            DriftSeverity.CRITICAL.value: 4,
        }
        max_severity = DriftSeverity.NONE
        max_severity_level = 0

        for metric in metrics:
            if metric.metric_name == "sharpe_ratio":
                change = abs(metric.change)
                if change > SEVERE_THRESHOLD:
                    severity = DriftSeverity.SEVERE
                elif change > MODERATE_THRESHOLD:
                    severity = DriftSeverity.MODERATE
                elif change > MILD_THRESHOLD:
                    severity = DriftSeverity.MILD
                else:
                    severity = DriftSeverity.NONE

                severity_level = severity_order.get(severity.value, 0)
                if severity_level > max_severity_level:
                    max_severity = severity
                    max_severity_level = severity_level

            elif metric.metric_name == "max_drawdown":
                if metric.current_value > CRITICAL_DD_THRESHOLD:
                    severity = DriftSeverity.CRITICAL
                elif metric.current_value > AUTO_REVERT_DD_THRESHOLD:
                    severity = DriftSeverity.SEVERE
                else:
                    severity = DriftSeverity.NONE

                severity_level = severity_order.get(severity.value, 0)
                if severity_level > max_severity_level:
                    max_severity = severity
                    max_severity_level = severity_level

        return max_severity.value

    def _auto_revert(self, proposal_id: str) -> None:
        """Auto-revert an adopted proposal due to critical drift."""
        logger.warning(
            "Auto-reverting proposal %s due to critical performance drift",
            proposal_id,
        )

        try:
            conn = self._db._get_conn()
            conn.execute(
                """UPDATE meta_proposals
                   SET status = 'REVERTED', reverted_at = ?, revert_reason = ?
                   WHERE proposal_id = ?""",
                (
                    datetime.now().isoformat(),
                    "Auto-reverted due to critical drift",
                    proposal_id,
                ),
            )
            conn.commit()
        except Exception as e:
            logger.error("Failed to auto-revert proposal: %s", e)

    def _last_adoption(self) -> dict | None:
        """Get the last adopted proposal across all capabilities."""
        try:
            conn = self._db._get_conn()
            row = conn.execute(
                """SELECT proposal_id, capability, decided_at, proposed_config
                   FROM meta_proposals
                   WHERE status = 'ADOPTED'
                   ORDER BY decided_at DESC LIMIT 1"""
            ).fetchone()
            if row is None:
                return None

            # Extract baseline_sharpe from proposed_config if available
            proposed_config = json.loads(row["proposed_config"] or "{}")
            baseline_sharpe = proposed_config.get("baseline_sharpe", 0.0)

            return {
                "proposal_id": row["proposal_id"],
                "capability": row["capability"],
                "decided_at": row["decided_at"],
                "baseline_sharpe": baseline_sharpe,
            }
        except Exception:
            return None

    def _compute_sharpe(self, strategy_report) -> float:
        """Compute Sharpe ratio from strategy performance data."""
        if strategy_report.total_trades == 0 or not strategy_report.fill_history:
            return 0.0

        returns = [f.pnl for f in strategy_report.fill_history]
        if not returns:
            return 0.0

        mean_return = sum(returns) / len(returns)
        if len(returns) < 2:
            return 0.0

        variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
        std_return = math.sqrt(variance) if variance > 0 else 0.0

        if std_return == 0:
            return 0.0

        return mean_return / std_return


# Need json import for _last_adoption
import json  # noqa: E402
