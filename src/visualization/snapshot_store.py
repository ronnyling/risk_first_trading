"""Layer 2 — Analysis Snapshot Store.

Frozen snapshot of all data used to produce a proposal, audit, or simulation.
Charts load ONLY from snapshots — never recompute logic.

Phase F.3 — Visualization & Human Control Plane.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class AnalysisSnapshotStore:
    """SQLite-backed analysis snapshot store.

    Creates frozen snapshots of all data used for proposals/audits/simulations.
    Charts load from snapshots only — never recompute.
    """

    def __init__(self, db: Any = None) -> None:
        self._db = db

    def _get_conn(self) -> Any:
        """Get database connection."""
        if self._db is not None:
            return self._db._get_conn()
        return None

    def create_snapshot(
        self,
        source_type: str,
        source_id: str,
        symbol: str,
        timeframe: str,
        strategy_family: str,
        bars: list[Any],
        indicator_outputs: dict[str, Any],
        correlation_context: dict | None,
        decision_metadata: dict,
        hermes_reasoning: str = "",
        created_by: str = "system",
    ) -> str:
        """Create a frozen snapshot. Returns snapshot_id.

        Args:
            source_type: "hermes_proposal" | "breadth_audit" | "meta_optimization" | "leverage_simulation"
            source_id: proposal_id, audit_id, run_id, etc.
            symbol: Symbol the snapshot is for.
            timeframe: Timeframe of the data.
            strategy_family: Strategy family for indicator mapping.
            bars: OHLC bar data (will be serialized to JSON).
            indicator_outputs: Precomputed indicator values.
            correlation_context: CorrelationMatrix data, if any.
            decision_metadata: HermesDecision fields.
            hermes_reasoning: Full reasoning text.
            created_by: Who created the snapshot.
        """
        snapshot_id = f"snap_{source_type}_{source_id}_{symbol.replace('/', '')}_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()

        # Serialize bars — extract OHLCV from Bar objects
        bars_json = []
        for bar in bars:
            if hasattr(bar, "__dict__"):
                bars_json.append({
                    "timestamp": str(getattr(bar, "timestamp", "")),
                    "open": getattr(bar, "open", 0.0),
                    "high": getattr(bar, "high", 0.0),
                    "low": getattr(bar, "low", 0.0),
                    "close": getattr(bar, "close", 0.0),
                    "volume": getattr(bar, "volume", 0.0),
                })
            elif isinstance(bar, dict):
                bars_json.append(bar)
            else:
                bars_json.append({"data": str(bar)})

        conn = self._get_conn()
        if conn is None:
            logger.warning("AnalysisSnapshotStore: no DB connection, snapshot not persisted")
            return snapshot_id

        try:
            conn.execute(
                """INSERT INTO analysis_snapshots
                   (snapshot_id, source_type, source_id, symbol, timeframe,
                    strategy_family, bars_used, indicator_outputs,
                    correlation_context, decision_metadata, hermes_reasoning,
                    created_at, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id,
                    source_type,
                    source_id,
                    symbol,
                    timeframe,
                    strategy_family,
                    json.dumps(bars_json),
                    json.dumps(indicator_outputs),
                    json.dumps(correlation_context) if correlation_context else None,
                    json.dumps(decision_metadata),
                    hermes_reasoning,
                    now,
                    created_by,
                ),
            )
            conn.commit()
            logger.info("AnalysisSnapshot: created %s for %s/%s", snapshot_id, symbol, timeframe)
        except Exception as e:
            logger.warning("AnalysisSnapshotStore.create_snapshot failed: %s", e)

        return snapshot_id

    def get_snapshot(self, snapshot_id: str) -> dict | None:
        """Retrieve a snapshot by ID. Returns None if not found."""
        conn = self._get_conn()
        if conn is None:
            return None

        try:
            row = conn.execute(
                "SELECT * FROM analysis_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
            if row is None:
                return None
            return dict(row)
        except Exception as e:
            logger.warning("AnalysisSnapshotStore.get_snapshot failed: %s", e)
            return None

    def get_snapshots_for_source(
        self, source_type: str, source_id: str
    ) -> list[dict]:
        """Retrieve all snapshots for a given proposal/audit/run."""
        conn = self._get_conn()
        if conn is None:
            return []

        try:
            rows = conn.execute(
                """SELECT snapshot_id, source_type, source_id, symbol, timeframe,
                          strategy_family, created_at, created_by
                   FROM analysis_snapshots
                   WHERE source_type = ? AND source_id = ?
                   ORDER BY created_at DESC""",
                (source_type, source_id),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning("AnalysisSnapshotStore.get_snapshots_for_source failed: %s", e)
            return []

    def list_recent(self, limit: int = 50) -> list[dict]:
        """List recent snapshots with metadata (no full data)."""
        conn = self._get_conn()
        if conn is None:
            return []

        try:
            rows = conn.execute(
                """SELECT snapshot_id, source_type, source_id, symbol, timeframe,
                          strategy_family, created_at, created_by
                   FROM analysis_snapshots
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning("AnalysisSnapshotStore.list_recent failed: %s", e)
            return []
