"""SQLite persistence layer for the Hermes trading framework.

Stores fills, allocation decisions, regime changes, vetoes, and strategy lifecycle state.
All writes are append-only for auditability.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from src.persistence.models import (
    AllocationRecord,
    FillRecord,
    RegimeRecord,
    StrategyState,
    StrategyStateRecord,
    VetoRecord,
)

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/trading_state.db")


class PersistenceDB:
    """SQLite-backed persistence for trading state.

    Features:
    - Append-only writes (immutable audit trail)
    - JSON-structured log export
    - Strategy lifecycle tracking
    - Thread-safe (uses connection per call)
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get or create a database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        conn = self._get_conn()
        conn.executescript("""
                CREATE TABLE IF NOT EXISTS fills (
                    fill_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    fill_price REAL NOT NULL,
                    commission REAL NOT NULL DEFAULT 0.0,
                    pnl REAL NOT NULL DEFAULT 0.0,
                    strategy_id TEXT NOT NULL DEFAULT '',
                    timestamp TEXT NOT NULL,
                    bar_index INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS allocations (
                    allocation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bar_index INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    regime TEXT NOT NULL DEFAULT '',
                    strategy_id TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 0,
                    weight REAL NOT NULL DEFAULT 0.0,
                    reason TEXT NOT NULL DEFAULT '',
                    portfolio_value REAL NOT NULL DEFAULT 0.0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS regime_changes (
                    regime_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bar_index INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    regime TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS vetoes (
                    veto_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bar_index INTEGER NOT NULL,
                    timestamp TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

            CREATE TABLE IF NOT EXISTS strategy_states (
                strategy_id TEXT PRIMARY KEY,
                state TEXT NOT NULL DEFAULT 'active',
                activated_at TEXT NOT NULL DEFAULT (datetime('now')),
                deactivated_at TEXT DEFAULT NULL,
                total_fills INTEGER NOT NULL DEFAULT 0,
                total_pnl REAL NOT NULL DEFAULT 0.0,
                max_drawdown REAL NOT NULL DEFAULT 0.0,
                notes TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS engine_runs (
                run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT DEFAULT NULL,
                bars_processed INTEGER NOT NULL DEFAULT 0,
                total_signals INTEGER NOT NULL DEFAULT 0,
                total_orders INTEGER NOT NULL DEFAULT 0,
                total_fills INTEGER NOT NULL DEFAULT 0,
                total_vetoes INTEGER NOT NULL DEFAULT 0,
                final_portfolio_value REAL DEFAULT NULL,
                final_pnl REAL DEFAULT NULL,
                config_snapshot TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS alert_records (
                alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                context TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS hermes_runs (
                hermes_run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                run_mode TEXT NOT NULL DEFAULT 'Manual',
                data_mode TEXT NOT NULL DEFAULT 'snapshot',
                markets_evaluated INTEGER NOT NULL DEFAULT 0,
                proposals_generated INTEGER NOT NULL DEFAULT 0,
                alerts_generated INTEGER NOT NULL DEFAULT 0,
                per_symbol_decisions TEXT NOT NULL DEFAULT '{}',
                correlation_data TEXT DEFAULT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS breadth_audits (
                audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                computed_at TEXT NOT NULL,
                current_symbols TEXT NOT NULL,
                scaling_profile TEXT NOT NULL,
                positive_edge_strategies TEXT NOT NULL,
                diversifying_symbols TEXT NOT NULL,
                redundant_symbols TEXT NOT NULL,
                correlation_summary TEXT NOT NULL,
                strategy_regime_expectancy TEXT NOT NULL,
                confidence_buckets TEXT NOT NULL,
                full_report TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS expansion_proposals (
                proposal_id TEXT PRIMARY KEY,
                audit_id INTEGER NOT NULL,
                current_symbols TEXT NOT NULL,
                proposed_additions TEXT NOT NULL,
                risk_impacts TEXT NOT NULL,
                scaling_profile TEXT NOT NULL,
                total_symbols_after INTEGER NOT NULL,
                within_profile_limit INTEGER NOT NULL,
                correlation_diversity_score REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at TEXT NOT NULL,
                decided_at TEXT,
                decision_reason TEXT
            );

            CREATE TABLE IF NOT EXISTS breadth_workflow_history (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                workflow_phase TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_data TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS meta_optimization_runs (
                run_id TEXT PRIMARY KEY,
                capability TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                status TEXT NOT NULL DEFAULT 'RUNNING',
                gating_result TEXT NOT NULL DEFAULT '{}',
                result_summary TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS meta_proposals (
                proposal_id TEXT PRIMARY KEY,
                run_id TEXT DEFAULT '',
                capability TEXT NOT NULL,
                proposal_type TEXT NOT NULL,
                current_config TEXT NOT NULL DEFAULT '{}',
                proposed_config TEXT NOT NULL DEFAULT '{}',
                baseline_metrics TEXT NOT NULL DEFAULT '{}',
                projected_metrics TEXT NOT NULL DEFAULT '{}',
                validation_results TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at TEXT NOT NULL,
                decided_at TEXT,
                decision_reason TEXT,
                reverted_at TEXT,
                revert_reason TEXT
            );

            CREATE TABLE IF NOT EXISTS meta_strategy_variants (
                variant_id TEXT PRIMARY KEY,
                parent_strategy TEXT NOT NULL,
                mutation_type TEXT NOT NULL,
                parameters TEXT NOT NULL DEFAULT '{}',
                stage TEXT NOT NULL DEFAULT 'BACKTEST',
                stage_entered_at TEXT NOT NULL,
                backtest_results TEXT DEFAULT '{}',
                shadow_results TEXT DEFAULT '{}',
                paper_results TEXT DEFAULT '{}',
                admission_decision TEXT,
                cooling_off_end TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- Phase F: Visualization & Human Control Plane tables

            CREATE TABLE IF NOT EXISTS indicator_cache (
                cache_key TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                indicator_name TEXT NOT NULL,
                indicator_version TEXT NOT NULL,
                lookback_hash TEXT NOT NULL,
                computed_values TEXT NOT NULL,
                computed_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                bar_start_idx INTEGER NOT NULL,
                bar_end_idx INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS analysis_snapshots (
                snapshot_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                strategy_family TEXT NOT NULL,
                bars_used TEXT NOT NULL,
                indicator_outputs TEXT NOT NULL,
                correlation_context TEXT,
                decision_metadata TEXT,
                hermes_reasoning TEXT,
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ui_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                event_category TEXT NOT NULL,
                event_data TEXT NOT NULL,
                system_mode TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        conn.commit()
        logger.info("Persistence DB initialized at %s", self._db_path)

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # --- Fill Records ---

    def record_fill(self, fill: FillRecord) -> int:
        """Record a fill. Returns the fill_id."""
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO fills
               (order_id, symbol, side, quantity, fill_price, commission, pnl,
                strategy_id, timestamp, bar_index)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                fill.order_id,
                fill.symbol,
                fill.side,
                fill.quantity,
                fill.fill_price,
                fill.commission,
                fill.pnl,
                fill.strategy_id,
                fill.timestamp,
                fill.bar_index,
            ),
        )
        conn.commit()
        return cursor.lastrowid or 0

    def get_fills(self, limit: int = 100) -> list[FillRecord]:
        """Get recent fills."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM fills ORDER BY fill_id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            FillRecord(
                fill_id=r["fill_id"],
                order_id=r["order_id"],
                symbol=r["symbol"],
                side=r["side"],
                quantity=r["quantity"],
                fill_price=r["fill_price"],
                commission=r["commission"],
                pnl=r["pnl"],
                strategy_id=r["strategy_id"],
                timestamp=r["timestamp"],
                bar_index=r["bar_index"],
            )
            for r in rows
        ]

    # --- Allocation Records ---

    def record_allocation(self, alloc: AllocationRecord) -> int:
        """Record an allocation decision. Returns the allocation_id."""
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO allocations
               (bar_index, timestamp, regime, strategy_id, active, weight,
                reason, portfolio_value)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                alloc.bar_index,
                alloc.timestamp,
                alloc.regime,
                alloc.strategy_id,
                1 if alloc.active else 0,
                alloc.weight,
                alloc.reason,
                alloc.portfolio_value,
            ),
        )
        conn.commit()
        return cursor.lastrowid or 0

    def get_allocations(self, limit: int = 200) -> list[AllocationRecord]:
        """Get recent allocation decisions."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM allocations ORDER BY allocation_id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            AllocationRecord(
                allocation_id=r["allocation_id"],
                bar_index=r["bar_index"],
                timestamp=r["timestamp"],
                regime=r["regime"],
                strategy_id=r["strategy_id"],
                active=bool(r["active"]),
                weight=r["weight"],
                reason=r["reason"],
                portfolio_value=r["portfolio_value"],
            )
            for r in rows
        ]

    # --- Regime Records ---

    def record_regime(self, regime: RegimeRecord) -> int:
        """Record a regime detection event."""
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO regime_changes (bar_index, timestamp, regime)
               VALUES (?, ?, ?)""",
            (regime.bar_index, regime.timestamp, regime.regime),
        )
        conn.commit()
        return cursor.lastrowid or 0

    # --- Veto Records ---

    def record_veto(self, veto: VetoRecord) -> int:
        """Record a risk veto event."""
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO vetoes (bar_index, timestamp, order_id, strategy_id, reason)
               VALUES (?, ?, ?, ?, ?)""",
            (veto.bar_index, veto.timestamp, veto.order_id, veto.strategy_id, veto.reason),
        )
        conn.commit()
        return cursor.lastrowid or 0

    def get_vetoes(self, limit: int = 100) -> list[VetoRecord]:
        """Get recent vetoes."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM vetoes ORDER BY veto_id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            VetoRecord(
                veto_id=r["veto_id"],
                bar_index=r["bar_index"],
                timestamp=r["timestamp"],
                order_id=r["order_id"],
                strategy_id=r["strategy_id"],
                reason=r["reason"],
            )
            for r in rows
        ]

    # --- Strategy State ---

    def set_strategy_state(
        self,
        strategy_id: str,
        state: StrategyState,
        notes: str = "",
    ) -> None:
        """Set or update a strategy's lifecycle state."""
        conn = self._get_conn()
        now = datetime.now().isoformat()
        existing = conn.execute(
            "SELECT strategy_id FROM strategy_states WHERE strategy_id = ?",
            (strategy_id,),
        ).fetchone()

        if existing:
            updates = {"state": state.value, "notes": notes}
            if state in (StrategyState.SUSPENDED, StrategyState.RETIRED):
                updates["deactivated_at"] = now
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE strategy_states SET {set_clause} WHERE strategy_id = ?",
                (*updates.values(), strategy_id),
            )
        else:
            conn.execute(
                """INSERT INTO strategy_states
                   (strategy_id, state, activated_at, notes)
                   VALUES (?, ?, ?, ?)""",
                (strategy_id, state.value, now, notes),
            )
        conn.commit()
        logger.info("Strategy %s state -> %s", strategy_id, state.value)

    def get_strategy_state(self, strategy_id: str) -> StrategyStateRecord | None:
        """Get a strategy's current state."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM strategy_states WHERE strategy_id = ?",
            (strategy_id,),
        ).fetchone()
        if row is None:
            return None
        return StrategyStateRecord(
            strategy_id=row["strategy_id"],
            state=row["state"],
            activated_at=row["activated_at"],
            deactivated_at=row["deactivated_at"],
            total_fills=row["total_fills"],
            total_pnl=row["total_pnl"],
            max_drawdown=row["max_drawdown"],
            notes=row["notes"],
        )

    def get_all_strategy_states(self) -> list[StrategyStateRecord]:
        """Get all strategy states."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM strategy_states ORDER BY strategy_id"
        ).fetchall()
        return [
            StrategyStateRecord(
                strategy_id=r["strategy_id"],
                state=r["state"],
                activated_at=r["activated_at"],
                deactivated_at=r["deactivated_at"],
                total_fills=r["total_fills"],
                total_pnl=r["total_pnl"],
                max_drawdown=r["max_drawdown"],
                notes=r["notes"],
            )
            for r in rows
        ]

    # --- Engine Runs ---

    def start_engine_run(self, config: dict | None = None) -> int:
        """Record the start of an engine run. Returns the run_id."""
        conn = self._get_conn()
        cursor = conn.execute(
            """INSERT INTO engine_runs (started_at, config_snapshot)
               VALUES (?, ?)""",
            (datetime.now().isoformat(), json.dumps(config or {})),
        )
        conn.commit()
        return cursor.lastrowid or 0

    def finish_engine_run(
        self,
        run_id: int,
        *,
        bars_processed: int = 0,
        total_signals: int = 0,
        total_orders: int = 0,
        total_fills: int = 0,
        total_vetoes: int = 0,
        final_portfolio_value: float | None = None,
        final_pnl: float | None = None,
    ) -> None:
        """Record the completion of an engine run."""
        conn = self._get_conn()
        conn.execute(
            """UPDATE engine_runs SET
               finished_at = ?,
               bars_processed = ?,
               total_signals = ?,
               total_orders = ?,
               total_fills = ?,
               total_vetoes = ?,
               final_portfolio_value = ?,
               final_pnl = ?
               WHERE run_id = ?""",
            (
                datetime.now().isoformat(),
                bars_processed,
                total_signals,
                total_orders,
                total_fills,
                total_vetoes,
                final_portfolio_value,
                final_pnl,
                run_id,
            ),
        )
        conn.commit()

    # --- Alert Records ---

    def record_alert(self, alert) -> int:
        """Record an alert. Accepts AlertRecord or dict with severity/message/context.

        Returns the alert_id.
        """
        conn = self._get_conn()

        if hasattr(alert, "to_dict"):
            data = alert.to_dict()
        elif isinstance(alert, dict):
            data = alert
        else:
            data = {
                "severity": getattr(alert, "severity", "INFO"),
                "message": getattr(alert, "message", str(alert)),
                "context": getattr(alert, "context", {}),
            }

        severity = data.get("severity", "INFO")
        if hasattr(severity, "value"):
            severity = severity.value

        context = data.get("context", {})
        if not isinstance(context, str):
            context = json.dumps(context, default=str)

        cursor = conn.execute(
            """INSERT INTO alert_records (timestamp, severity, message, context)
               VALUES (?, ?, ?, ?)""",
            (
                data.get("timestamp", datetime.now().isoformat()),
                severity,
                data.get("message", ""),
                context,
            ),
        )
        conn.commit()
        return cursor.lastrowid or 0

    def get_alerts(self, limit: int = 100) -> list[dict]:
        """Get recent alerts."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM alert_records ORDER BY alert_id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            {
                "alert_id": r["alert_id"],
                "timestamp": r["timestamp"],
                "severity": r["severity"],
                "message": r["message"],
                "context": r["context"],
            }
            for r in rows
        ]

    # --- Summary ---

    def record_hermes_run(
        self,
        hermes_run_id: str,
        started_at: str,
        completed_at: str | None = None,
        run_mode: str = "Manual",
        data_mode: str = "snapshot",
        markets_evaluated: int = 0,
        proposals_generated: int = 0,
        alerts_generated: int = 0,
        per_symbol_decisions: dict | None = None,
        correlation_data: dict | None = None,
    ) -> None:
        """Record a Hermes run for analytics.

        Args:
            hermes_run_id: Unique run identifier.
            started_at: ISO timestamp of run start.
            completed_at: ISO timestamp of run completion.
            run_mode: "Manual" or "Scheduled".
            data_mode: "snapshot" or "streaming".
            markets_evaluated: Number of markets evaluated.
            proposals_generated: Number of proposals generated.
            alerts_generated: Number of alerts generated.
            per_symbol_decisions: Dict of per-symbol decision data.
            correlation_data: Correlation matrix data.
        """
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO hermes_runs
               (hermes_run_id, started_at, completed_at, run_mode, data_mode,
                markets_evaluated, proposals_generated, alerts_generated,
                per_symbol_decisions, correlation_data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                hermes_run_id,
                started_at,
                completed_at,
                run_mode,
                data_mode,
                markets_evaluated,
                proposals_generated,
                alerts_generated,
                json.dumps(per_symbol_decisions or {}),
                json.dumps(correlation_data) if correlation_data else None,
            ),
        )
        conn.commit()
        logger.info("Hermes run recorded: %s", hermes_run_id)

    # --- Summary ---

    def get_summary(self) -> dict:
        """Get a summary of all persisted data."""
        conn = self._get_conn()
        fills = conn.execute("SELECT COUNT(*) as cnt FROM fills").fetchone()["cnt"]
        allocs = conn.execute("SELECT COUNT(*) as cnt FROM allocations").fetchone()["cnt"]
        vetoes = conn.execute("SELECT COUNT(*) as cnt FROM vetoes").fetchone()["cnt"]
        regimes = conn.execute("SELECT COUNT(*) as cnt FROM regime_changes").fetchone()["cnt"]
        strategies = conn.execute("SELECT COUNT(*) as cnt FROM strategy_states").fetchone()["cnt"]
        runs = conn.execute("SELECT COUNT(*) as cnt FROM engine_runs").fetchone()["cnt"]

        return {
            "db_path": str(self._db_path),
            "total_fills": fills,
            "total_allocations": allocs,
            "total_vetoes": vetoes,
            "total_regime_changes": regimes,
            "total_strategies": strategies,
            "total_engine_runs": runs,
        }

    # --- Breadth Audit ---

    def record_breadth_audit(self, report) -> int:
        """Persist a breadth audit report. Returns audit_id.

        Args:
            report: BreadthAuditReport instance.

        Returns:
            The auto-generated audit_id.
        """
        conn = self._get_conn()
        from dataclasses import asdict
        full_report = json.dumps(asdict(report), default=str)
        cursor = conn.execute(
            """INSERT INTO breadth_audits
               (computed_at, current_symbols, scaling_profile,
                positive_edge_strategies, diversifying_symbols, redundant_symbols,
                correlation_summary, strategy_regime_expectancy, confidence_buckets,
                full_report)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report.computed_at,
                json.dumps(report.current_symbols),
                report.current_scaling_profile,
                json.dumps(report.positive_edge_strategies),
                json.dumps(report.diversifying_symbols),
                json.dumps(report.redundant_symbols),
                json.dumps(report.correlation_summary),
                json.dumps([asdict(s) for s in report.strategy_regime_expectancy], default=str),
                json.dumps([asdict(c) for c in report.confidence_buckets], default=str),
                full_report,
            ),
        )
        conn.commit()
        audit_id = cursor.lastrowid or 0
        logger.info("Breadth audit recorded: id=%d", audit_id)
        return audit_id

    def get_latest_breadth_audit(self) -> dict | None:
        """Retrieve the most recent breadth audit."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM breadth_audits ORDER BY audit_id DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            return {
                "audit_id": row["audit_id"],
                "computed_at": row["computed_at"],
                "current_symbols": json.loads(row["current_symbols"]),
                "scaling_profile": row["scaling_profile"],
                "positive_edge_strategies": json.loads(row["positive_edge_strategies"]),
                "diversifying_symbols": json.loads(row["diversifying_symbols"]),
                "redundant_symbols": json.loads(row["redundant_symbols"]),
                "correlation_summary": json.loads(row["correlation_summary"]),
                "full_report": json.loads(row["full_report"]),
            }
        except Exception:
            return None

    # --- Expansion Proposals ---

    def record_expansion_proposal(self, proposal) -> None:
        """Persist an expansion proposal.

        Args:
            proposal: SymbolExpansionProposal instance.
        """
        conn = self._get_conn()
        from dataclasses import asdict
        conn.execute(
            """INSERT OR REPLACE INTO expansion_proposals
               (proposal_id, audit_id, current_symbols, proposed_additions,
                risk_impacts, scaling_profile, total_symbols_after,
                within_profile_limit, correlation_diversity_score, status,
                created_at, decided_at, decision_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                proposal.proposal_id,
                proposal.audit_id,
                json.dumps(proposal.current_symbols),
                json.dumps([asdict(c) for c in proposal.proposed_additions], default=str),
                json.dumps([asdict(r) for r in proposal.risk_impacts], default=str),
                proposal.scaling_profile,
                proposal.total_symbols_after,
                1 if proposal.within_profile_limit else 0,
                proposal.correlation_diversity_score,
                proposal.status,
                proposal.created_at,
                proposal.decided_at,
                proposal.decision_reason,
            ),
        )
        conn.commit()
        logger.info("Expansion proposal recorded: %s", proposal.proposal_id)

    def update_proposal_status(
        self, proposal_id: str, status: str, reason: str | None = None
    ) -> None:
        """Update the status of an expansion proposal.

        Args:
            proposal_id: The proposal to update.
            status: New status (APPROVED, REJECTED, IGNORED).
            reason: Optional decision reason.
        """
        conn = self._get_conn()
        conn.execute(
            """UPDATE expansion_proposals
               SET status = ?, decided_at = ?, decision_reason = ?
               WHERE proposal_id = ?""",
            (status, datetime.now().isoformat(), reason, proposal_id),
        )
        conn.commit()
        logger.info("Proposal %s status -> %s", proposal_id, status)

    def get_pending_proposals(self) -> list[dict]:
        """Retrieve all proposals with PENDING status."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM expansion_proposals WHERE status = 'PENDING' ORDER BY created_at DESC"
            ).fetchall()
            return [
                {
                    "proposal_id": r["proposal_id"],
                    "audit_id": r["audit_id"],
                    "scaling_profile": r["scaling_profile"],
                    "total_symbols_after": r["total_symbols_after"],
                    "status": r["status"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        except Exception:
            return []

    def get_latest_proposal(self) -> dict | None:
        """Retrieve the most recent expansion proposal."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM expansion_proposals ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            return {
                "proposal_id": row["proposal_id"],
                "audit_id": row["audit_id"],
                "status": row["status"],
                "scaling_profile": row["scaling_profile"],
                "total_symbols_after": row["total_symbols_after"],
                "correlation_diversity_score": row["correlation_diversity_score"],
                "created_at": row["created_at"],
                "decided_at": row["decided_at"],
                "decision_reason": row["decision_reason"],
            }
        except Exception:
            return None

    # --- Workflow History ---

    def record_workflow_event(
        self, phase: str, event_type: str, event_data: dict
    ) -> None:
        """Record a workflow event to the audit trail.

        Args:
            phase: Workflow phase (AUDIT, EXPANSION, FAMILY, etc.).
            event_type: Event type (PHASE_ENTERED, PROPOSAL_CREATED, DECISION, etc.).
            event_data: Event payload as dict.
        """
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO breadth_workflow_history
               (workflow_phase, event_type, event_data, created_at)
               VALUES (?, ?, ?, ?)""",
            (phase, event_type, json.dumps(event_data, default=str), datetime.now().isoformat()),
        )
        conn.commit()

    def get_workflow_history(self, limit: int = 50) -> list[dict]:
        """Retrieve recent workflow history events.

        Args:
            limit: Maximum number of events to return.

        Returns:
            List of workflow event dicts, most recent first.
        """
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM breadth_workflow_history ORDER BY event_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {
                    "event_id": r["event_id"],
                    "workflow_phase": r["workflow_phase"],
                    "event_type": r["event_type"],
                    "event_data": json.loads(r["event_data"]),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        except Exception:
            return []

    # --- Meta-Optimization Methods ---

    def record_meta_optimization_run(
        self,
        run_id: str,
        capability: str,
        started_at: str,
        completed_at: str | None = None,
        status: str = "RUNNING",
        gating_result: dict | None = None,
        result_summary: dict | None = None,
    ) -> None:
        """Record a meta-optimization run.

        Args:
            run_id: Unique run identifier.
            capability: Which capability (OPTIMIZER, LEVERAGE, POLICY, LLM, MUTATION).
            started_at: ISO timestamp of run start.
            completed_at: ISO timestamp of run completion.
            status: Run status (RUNNING, COMPLETED, BLOCKED, FAILED).
            gating_result: Gating check results.
            result_summary: Outcome metrics.
        """
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO meta_optimization_runs
               (run_id, capability, started_at, completed_at, status,
                gating_result, result_summary)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                capability,
                started_at,
                completed_at,
                status,
                json.dumps(gating_result or {}),
                json.dumps(result_summary or {}),
            ),
        )
        conn.commit()
        logger.info("Meta-optimization run recorded: %s", run_id)

    def record_meta_proposal(self, proposal) -> None:
        """Record a meta-optimization proposal.

        Args:
            proposal: OptimizationProposal, LeverageReport, PolicyProposal,
                      or LLMTuningProposal instance.
        """
        conn = self._get_conn()

        # Extract common fields
        proposal_id = getattr(proposal, "proposal_id", getattr(proposal, "report_id", "unknown"))
        capability = getattr(proposal, "capability", "UNKNOWN")

        # Convert proposal to dict for storage
        from dataclasses import asdict
        try:
            proposal_dict = asdict(proposal)
        except Exception:
            proposal_dict = {"raw": str(proposal)}

        conn.execute(
            """INSERT OR REPLACE INTO meta_proposals
               (proposal_id, capability, proposal_type, current_config,
                proposed_config, baseline_metrics, projected_metrics,
                validation_results, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                proposal_id,
                capability,
                capability,
                json.dumps(proposal_dict, default=str),
                json.dumps(proposal_dict, default=str),
                json.dumps(getattr(proposal, "baseline_metrics", {}), default=str),
                json.dumps(getattr(proposal, "projected_metrics", {}), default=str),
                json.dumps(proposal_dict, default=str),
                getattr(proposal, "status", "PENDING"),
                getattr(proposal, "created_at", datetime.now().isoformat()),
            ),
        )
        conn.commit()
        logger.info("Meta-proposal recorded: %s", proposal_id)

    def update_meta_proposal_status(
        self, proposal_id: str, status: str, reason: str | None = None
    ) -> None:
        """Update the status of a meta-optimization proposal.

        Args:
            proposal_id: The proposal to update.
            status: New status (ADOPTED, REJECTED, IGNORED, REVERTED).
            reason: Optional decision reason.
        """
        conn = self._get_conn()
        now = datetime.now().isoformat()
        conn.execute(
            """UPDATE meta_proposals
               SET status = ?, decided_at = ?, decision_reason = ?
               WHERE proposal_id = ?""",
            (status, now, reason, proposal_id),
        )
        conn.commit()
        logger.info("Meta-proposal %s status -> %s", proposal_id, status)

    def get_meta_proposals(
        self, status: str | None = None, limit: int = 50
    ) -> list[dict]:
        """Retrieve meta-optimization proposals.

        Args:
            status: Filter by status (PENDING, ADOPTED, etc.). None = all.
            limit: Maximum number of proposals to return.

        Returns:
            List of proposal dicts, most recent first.
        """
        conn = self._get_conn()
        try:
            if status:
                rows = conn.execute(
                    """SELECT * FROM meta_proposals
                       WHERE status = ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM meta_proposals
                       ORDER BY created_at DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
            return [
                {
                    "proposal_id": r["proposal_id"],
                    "capability": r["capability"],
                    "status": r["status"],
                    "created_at": r["created_at"],
                    "decided_at": r["decided_at"],
                    "decision_reason": r["decision_reason"],
                }
                for r in rows
            ]
        except Exception:
            return []

    def record_strategy_variant(self, variant) -> None:
        """Record a strategy variant.

        Args:
            variant: StrategyVariant instance.
        """
        conn = self._get_conn()
        conn.execute(
            """INSERT OR REPLACE INTO meta_strategy_variants
               (variant_id, parent_strategy, mutation_type, parameters,
                stage, stage_entered_at, backtest_results, shadow_results,
                paper_results, admission_decision, cooling_off_end, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                variant.variant_id,
                variant.parent_strategy,
                variant.mutation_type,
                json.dumps(variant.parameters, default=str),
                variant.stage,
                variant.stage_entered_at,
                json.dumps(variant.backtest_results, default=str),
                json.dumps(variant.shadow_results, default=str),
                json.dumps(variant.paper_results, default=str),
                variant.admission_decision,
                variant.cooling_off_end,
                variant.created_at,
            ),
        )
        conn.commit()
        logger.info("Strategy variant recorded: %s", variant.variant_id)

    def get_meta_proposals_count_by_capability_and_status(
        self, capability: str, status: str, since: str | None = None
    ) -> int:
        """Count meta proposals for a capability with a given status.

        Args:
            capability: The capability to filter by.
            status: The status to filter by.
            since: ISO timestamp to filter from. None = all time.

        Returns:
            Count of matching proposals.
        """
        conn = self._get_conn()
        try:
            if since:
                row = conn.execute(
                    """SELECT COUNT(*) as cnt FROM meta_proposals
                       WHERE capability = ? AND status = ? AND created_at >= ?""",
                    (capability, status, since),
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT COUNT(*) as cnt FROM meta_proposals
                       WHERE capability = ? AND status = ?""",
                    (capability, status),
                ).fetchone()
            return row["cnt"] if row else 0
        except Exception:
            return 0