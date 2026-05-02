"""UI Audit Logger — logs all UI interactions to persistence.

Captures chart views, proposal actions, mode transitions, and
snapshot accesses as part of the audit trail.

Phase F.6 — Visualization & Human Control Plane.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class UIAuditLogger:
    """Logs all UI interactions to the SQLite ui_events table.

    Every user action, chart view, and mode transition is recorded
    as part of the system's audit trail.
    """

    def __init__(self, db: Any = None) -> None:
        self._db = db
        self._verbosity: str = "LOW"

    @property
    def verbosity(self) -> str:
        """Current verbosity level."""
        return self._verbosity

    @verbosity.setter
    def verbosity(self, level: str) -> None:
        """Set verbosity level (LOW, MEDIUM, HIGH)."""
        if level not in ("LOW", "MEDIUM", "HIGH"):
            raise ValueError(f"Invalid verbosity: {level}")
        self._verbosity = level

    def _get_conn(self) -> Any:
        """Get database connection."""
        if self._db is not None:
            return self._db._get_conn()
        return None

    def log_event(
        self,
        event_type: str,
        event_category: str,
        event_data: dict,
        system_mode: str,
    ) -> None:
        """Log a UI event.

        Always writes to DB. Conditionally writes to JSONL based on verbosity.

        Args:
            event_type: Event type (e.g. "CHART_OPENED", "ACTION_TAKEN").
            event_category: Category (e.g. "USER_ACTION", "SYSTEM").
            event_data: Event-specific data dict.
            system_mode: Current system mode.
        """
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()

        record = {
            "event_type": event_type,
            "event_category": event_category,
            "event_data": event_data,
            "system_mode": system_mode,
            "created_at": now,
        }

        # Always log to DB if available
        if conn is not None:
            try:
                conn.execute(
                    """INSERT INTO ui_events
                       (event_type, event_category, event_data, system_mode, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        event_type,
                        event_category,
                        json.dumps(event_data),
                        system_mode,
                        now,
                    ),
                )
                conn.commit()
            except Exception as e:
                logger.warning("UIAuditLogger.log_event failed: %s", e)

        # Console logging based on verbosity
        if self._verbosity == "HIGH":
            logger.info("UI_EVENT: %s [%s] mode=%s data=%s", event_type, event_category, system_mode, event_data)
        elif self._verbosity == "MEDIUM" and event_category == "USER_ACTION":
            logger.info("UI_EVENT: %s [%s] mode=%s", event_type, event_category, system_mode)
        elif self._verbosity == "LOW" and event_type in ("ACTION_TAKEN", "MODE_SWITCHED"):
            logger.info("UI_EVENT: %s mode=%s", event_type, system_mode)

    def log_chart_view(
        self, chart_id: str, snapshot_id: str | None, system_mode: str
    ) -> None:
        """Log a chart view event."""
        self.log_event(
            event_type="CHART_OPENED",
            event_category="USER_ACTION",
            event_data={
                "chart_id": chart_id,
                "snapshot_id": snapshot_id,
            },
            system_mode=system_mode,
        )

    def log_proposal_action(
        self, proposal_id: str, action: str, reason: str, system_mode: str
    ) -> None:
        """Log a proposal action (approve/reject/ignore)."""
        self.log_event(
            event_type="ACTION_TAKEN",
            event_category="USER_ACTION",
            event_data={
                "proposal_id": proposal_id,
                "action": action,
                "reason": reason,
            },
            system_mode=system_mode,
        )

    def log_mode_transition(
        self, old_mode: str, new_mode: str, trigger: str
    ) -> None:
        """Log a system mode transition."""
        self.log_event(
            event_type="MODE_SWITCHED",
            event_category="SYSTEM",
            event_data={
                "old_mode": old_mode,
                "new_mode": new_mode,
                "trigger": trigger,
            },
            system_mode=new_mode,
        )

    def log_snapshot_access(
        self, snapshot_id: str, source_type: str, source_id: str, system_mode: str
    ) -> None:
        """Log a snapshot access event."""
        self.log_event(
            event_type="SNAPSHOT_ACCESSED",
            event_category="SYSTEM",
            event_data={
                "snapshot_id": snapshot_id,
                "source_type": source_type,
                "source_id": source_id,
            },
            system_mode=system_mode,
        )

    def log_cache_event(
        self, event_type: str, cache_key: str, indicator_name: str, system_mode: str
    ) -> None:
        """Log a cache hit/miss event."""
        self.log_event(
            event_type=event_type,
            event_category="SYSTEM",
            event_data={
                "cache_key": cache_key,
                "indicator_name": indicator_name,
            },
            system_mode=system_mode,
        )

    def get_events(
        self,
        event_type: str | None = None,
        event_category: str | None = None,
        system_mode: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Retrieve UI events with optional filters."""
        conn = self._get_conn()
        if conn is None:
            return []

        query = "SELECT * FROM ui_events WHERE 1=1"
        params: list[Any] = []

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        if event_category:
            query += " AND event_category = ?"
            params.append(event_category)
        if system_mode:
            query += " AND system_mode = ?"
            params.append(system_mode)

        query += " ORDER BY event_id DESC LIMIT ?"
        params.append(limit)

        try:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning("UIAuditLogger.get_events failed: %s", e)
            return []
