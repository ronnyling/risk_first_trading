"""Phase 16: Alert dispatcher — console + file backends for critical events.

Lightweight alert system that dispatches alerts to console and file.
No webhooks — simplicity and reliability over feature richness.

Usage:
    from src.operations.alerts import AlertDispatcher, AlertSeverity

    dispatcher = AlertDispatcher()
    dispatcher.dispatch(
        severity=AlertSeverity.CRITICAL,
        message="Kill switch triggered",
        context={"drawdown": 0.25, "threshold": 0.25},
    )

Alert triggers (integrated into key components):
    - FTMO daily loss approaching limit (>80%)
    - FTMO max drawdown approaching limit (>80%)
    - Kill switch triggered
    - Strategy suspended/retired
    - Hermes CASH directive active for >10 consecutive bars
    - Engine disconnection/reconnection
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger("alerts")

# Default alert file path
_DEFAULT_ALERT_PATH = Path("data/alerts.json")


class AlertSeverity(Enum):
    """Alert severity levels."""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertRecord:
    """Immutable alert record."""

    def __init__(
        self,
        severity: AlertSeverity,
        message: str,
        context: dict[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> None:
        self.severity = severity
        self.message = message
        self.context = context or {}
        self.timestamp = timestamp or datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "severity": self.severity.value,
            "message": self.message,
            "context": self.context,
        }

    def to_console_str(self) -> str:
        """Human-readable console string."""
        prefix = {
            AlertSeverity.INFO: "[INFO]",
            AlertSeverity.WARNING: "[WARN]",
            AlertSeverity.CRITICAL: "[CRIT]",
        }[self.severity]
        return f"{prefix} {self.message}"

    @classmethod
    def from_dict(cls, data: dict) -> AlertRecord:
        return cls(
            severity=AlertSeverity(data["severity"]),
            message=data["message"],
            context=data.get("context", {}),
            timestamp=data.get("timestamp"),
        )


class AlertDispatcher:
    """Dispatches alerts to console and file backends.

    Features:
    - Console output with color-coded severity
    - File persistence (append-only JSONL)
    - Optional persistence DB integration
    """

    def __init__(
        self,
        alert_path: Path | str | None = None,
        persist_to_db: bool = False,
    ) -> None:
        self._alert_path = Path(alert_path) if alert_path else _DEFAULT_ALERT_PATH
        self._persist_to_db = persist_to_db
        self._db = None

        # Ensure alert directory exists
        self._alert_path.parent.mkdir(parents=True, exist_ok=True)

    def dispatch(
        self,
        severity: AlertSeverity,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> AlertRecord:
        """Dispatch an alert to all configured backends.

        Returns the AlertRecord for auditing.
        """
        record = AlertRecord(severity=severity, message=message, context=context)

        # Console output
        self._dispatch_console(record)

        # File persistence
        self._dispatch_file(record)

        # DB persistence (if configured)
        if self._persist_to_db:
            self._dispatch_db(record)

        return record

    def _dispatch_console(self, record: AlertRecord) -> None:
        """Output alert to console with appropriate log level."""
        msg = record.to_console_str()
        if record.severity == AlertSeverity.CRITICAL:
            logger.critical(msg)
        elif record.severity == AlertSeverity.WARNING:
            logger.warning(msg)
        else:
            logger.info(msg)

    def _dispatch_file(self, record: AlertRecord) -> None:
        """Append alert to JSONL file."""
        try:
            with open(self._alert_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict(), default=str) + "\n")
        except Exception as e:
            logger.error("Failed to write alert to file: %s", e)

    def _dispatch_db(self, record: AlertRecord) -> None:
        """Persist alert to SQLite database."""
        try:
            if self._db is None:
                from src.persistence.db import PersistenceDB
                self._db = PersistenceDB()
            self._db.record_alert(record)
        except Exception as e:
            logger.error("Failed to write alert to DB: %s", e)

    def get_recent_alerts(self, limit: int = 50) -> list[AlertRecord]:
        """Read recent alerts from the alert file."""
        if not self._alert_path.exists():
            return []

        alerts = []
        try:
            with open(self._alert_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            # Read last N lines
            for line in lines[-limit:]:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        alerts.append(AlertRecord.from_dict(data))
                    except (json.JSONDecodeError, KeyError):
                        pass
        except Exception as e:
            logger.error("Failed to read alerts: %s", e)

        return alerts


# --- Convenience functions for common alert scenarios ---

def dispatch_ftmo_alert(
    dispatcher: AlertDispatcher,
    daily_loss_pct: float,
    daily_limit_pct: float,
    action: str,
) -> AlertRecord:
    """Dispatch FTMO-related alert."""
    severity = AlertSeverity.CRITICAL if action == "HALT" else AlertSeverity.WARNING
    return dispatcher.dispatch(
        severity=severity,
        message=f"FTMO {action}: daily loss {daily_loss_pct:.2%} (limit: {daily_limit_pct:.2%})",
        context={
            "daily_loss_pct": daily_loss_pct,
            "daily_limit_pct": daily_limit_pct,
            "action": action,
        },
    )


def dispatch_kill_switch_alert(
    dispatcher: AlertDispatcher,
    drawdown_pct: float,
    threshold_pct: float,
) -> AlertRecord:
    """Dispatch kill switch trigger alert."""
    return dispatcher.dispatch(
        severity=AlertSeverity.CRITICAL,
        message=f"Kill switch triggered: drawdown {drawdown_pct:.2%} > threshold {threshold_pct:.2%}",
        context={
            "drawdown_pct": drawdown_pct,
            "threshold_pct": threshold_pct,
        },
    )


def dispatch_ladder_alert(
    dispatcher: AlertDispatcher,
    stage: str,
    previous_stage: str,
    drawdown_pct: float,
) -> AlertRecord:
    """Dispatch drawdown ladder stage transition alert."""
    severity = AlertSeverity.WARNING if stage in ("PROTECTIVE", "SURVIVAL") else AlertSeverity.INFO
    return dispatcher.dispatch(
        severity=severity,
        message=f"Drawdown ladder: {previous_stage} -> {stage} (DD={drawdown_pct:.2%})",
        context={
            "stage": stage,
            "previous_stage": previous_stage,
            "drawdown_pct": drawdown_pct,
        },
    )


def dispatch_cash_prolonged_alert(
    dispatcher: AlertDispatcher,
    consecutive_bars: int,
    threshold: int = 10,
) -> AlertRecord:
    """Dispatch alert when CASH directive is active for too long."""
    return dispatcher.dispatch(
        severity=AlertSeverity.WARNING,
        message=f"Hermes CASH directive active for {consecutive_bars} bars (threshold: {threshold})",
        context={
            "consecutive_bars": consecutive_bars,
            "threshold": threshold,
        },
    )
