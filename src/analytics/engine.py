"""Analytics Engine — queries persistence data and produces structured reports.

Turns existing persistence (fills, allocations, vetoes, engine_runs, alerts)
into decision-grade reporting for operator review.

Production data source:
    All data comes from PersistenceDB (SQLite). No CSVs, mocks, or fallbacks.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from src.analytics.models import (
    HermesReport,
    RiskReport,
    SessionReport,
    StrategyReport,
)
from src.persistence.db import PersistenceDB
from src.persistence.models import FillRecord, VetoRecord

logger = logging.getLogger(__name__)


class AnalyticsEngine:
    """Central analytics query engine over persistence data.

    Queries SQLite tables (fills, allocations, vetoes, engine_runs, etc.)
    and produces structured report objects.

    Usage:
        engine = AnalyticsEngine()
        session = engine.session_summary()  # latest run
        strategy = engine.strategy_performance("my_strategy")
        risk = engine.risk_utilization()
        hermes = engine.hermes_outcomes()
    """

    def __init__(self, db: PersistenceDB | None = None) -> None:
        """Initialize analytics engine.

        Args:
            db: PersistenceDB instance. If None, creates default.
        """
        self._db = db or PersistenceDB()

    def session_summary(self, run_id: int | None = None) -> SessionReport:
        """Generate a session summary for a specific engine run or latest.

        Args:
            run_id: Engine run ID. If None, uses the latest run.

        Returns:
            SessionReport with run metrics.
        """
        conn = self._db._get_conn()

        if run_id is not None:
            row = conn.execute(
                "SELECT * FROM engine_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM engine_runs ORDER BY run_id DESC LIMIT 1"
            ).fetchone()

        if row is None:
            return SessionReport()

        # Get fills and vetoes
        fills = self._db.get_fills(limit=10000)
        vetoes = self._db.get_vetoes(limit=10000)

        return SessionReport(
            run_id=row["run_id"],
            started_at=row["started_at"] or "",
            finished_at=row["finished_at"],
            bars_processed=row["bars_processed"] or 0,
            total_signals=row["total_signals"] or 0,
            total_orders=row["total_orders"] or 0,
            total_fills=row["total_fills"] or 0,
            total_vetoes=row["total_vetoes"] or 0,
            final_portfolio_value=row["final_portfolio_value"],
            final_pnl=row["final_pnl"],
            fill_details=fills,
            veto_details=vetoes,
        )

    def strategy_performance(
        self,
        strategy_id: str | None = None,
        since: str | None = None,
        limit: int = 1000,
    ) -> StrategyReport:
        """Per-strategy PnL, win rate, trade count, drawdown.

        Args:
            strategy_id: Strategy to filter by. None = all strategies.
            since: ISO timestamp to filter from. None = all time.
            limit: Maximum number of fills to analyze (default: 1000).

        Returns:
            StrategyReport with performance metrics.
        """
        conn = self._db._get_conn()
        query = "SELECT * FROM fills WHERE 1=1"
        params: list = []

        if strategy_id:
            query += " AND strategy_id = ?"
            params.append(strategy_id)
        if since:
            query += " AND timestamp >= ?"
            params.append(since)

        query += " ORDER BY fill_id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()

        fills = [
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

        if not fills:
            return StrategyReport(strategy_id=strategy_id or "ALL")

        wins = [f for f in fills if f.pnl > 0]
        losses = [f for f in fills if f.pnl <= 0]
        total_pnl = sum(f.pnl for f in fills)
        max_dd = self._compute_max_drawdown(fills)

        return StrategyReport(
            strategy_id=strategy_id or "ALL",
            total_trades=len(fills),
            winning_trades=len(wins),
            losing_trades=len(losses),
            total_pnl=total_pnl,
            win_rate=len(wins) / len(fills) if fills else 0.0,
            avg_trade_pnl=total_pnl / len(fills) if fills else 0.0,
            max_drawdown=max_dd,
            fill_history=fills,
        )

    def risk_utilization(self, since: str | None = None, limit: int = 5000) -> RiskReport:
        """Risk budget usage, drawdown history, veto rate.

        Args:
            since: ISO timestamp to filter from. None = all time.
            limit: Maximum number of records to analyze (default: 5000).

        Returns:
            RiskReport with risk metrics.
        """
        conn = self._db._get_conn()

        # Get vetoes
        veto_query = "SELECT * FROM vetoes WHERE 1=1"
        veto_params: list = []
        if since:
            veto_query += " AND timestamp >= ?"
            veto_params.append(since)
        veto_query += " ORDER BY veto_id DESC LIMIT ?"
        veto_params.append(limit)

        veto_rows = conn.execute(veto_query, veto_params).fetchall()
        vetoes = [
            VetoRecord(
                veto_id=r["veto_id"],
                bar_index=r["bar_index"],
                timestamp=r["timestamp"],
                order_id=r["order_id"],
                strategy_id=r["strategy_id"],
                reason=r["reason"],
            )
            for r in veto_rows
        ]

        # Get fills for drawdown calculation
        fill_query = "SELECT * FROM fills WHERE 1=1"
        fill_params: list = []
        if since:
            fill_query += " AND timestamp >= ?"
            fill_params.append(since)
        fill_query += " ORDER BY fill_id DESC LIMIT ?"
        fill_params.append(limit)

        fill_rows = conn.execute(fill_query, fill_params).fetchall()
        fills = [
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
            for r in fill_rows
        ]

        total_fills = len(fills)
        total_vetoes = len(vetoes)
        veto_rate = total_vetoes / (total_fills + total_vetoes) if (total_fills + total_vetoes) > 0 else 0.0

        max_dd = self._compute_max_drawdown(fills)
        avg_dd = self._compute_avg_drawdown(fills)

        return RiskReport(
            total_drawdown_events=total_vetoes,
            max_drawdown_observed=max_dd,
            avg_drawdown=avg_dd,
            risk_budget_utilization=min(max_dd / 0.20, 1.0) if max_dd > 0 else 0.0,  # vs 20% max
            veto_rate=veto_rate,
            veto_history=vetoes,
        )

    def hermes_outcomes(self, since: str | None = None) -> HermesReport:
        """Hermes decision quality tracking.

        Reads from hermes_runs table and cross-references with fills
        to determine decision accuracy.

        Args:
            since: ISO timestamp to filter from. None = all time.

        Returns:
            HermesReport with decision metrics.
        """
        conn = self._db._get_conn()

        # Query hermes_runs table (may not exist yet)
        try:
            query = "SELECT * FROM hermes_runs WHERE 1=1"
            params: list = []
            if since:
                query += " AND started_at >= ?"
                params.append(since)
            query += " ORDER BY started_at DESC"

            rows = conn.execute(query, params).fetchall()
        except Exception:
            # Table may not exist yet
            rows = []

        if not rows:
            return HermesReport()

        total_runs = len(rows)
        total_decisions = 0
        directive_dist: dict[str, int] = {}
        regime_dist: dict[str, int] = {}
        confidences: list[float] = []
        high_conf_count = 0

        for row in rows:
            try:
                decisions_json = row["per_symbol_decisions"] or "{}"
                decisions = json.loads(decisions_json) if isinstance(decisions_json, str) else decisions_json

                for sym, dec in decisions.items():
                    total_decisions += 1
                    directive = dec.get("risk_directive", "UNKNOWN")
                    regime = dec.get("regime", "UNKNOWN")
                    confidence = dec.get("confidence", 0.0)

                    directive_dist[directive] = directive_dist.get(directive, 0) + 1
                    regime_dist[regime] = regime_dist.get(regime, 0) + 1
                    confidences.append(confidence)

                    if confidence > 0.7:
                        high_conf_count += 1
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

        # Get alert count
        try:
            alert_rows = conn.execute("SELECT COUNT(*) as cnt FROM alert_records").fetchone()
            alert_count = alert_rows["cnt"] if alert_rows else 0
        except Exception:
            alert_count = 0

        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

        return HermesReport(
            total_runs=total_runs,
            total_decisions=total_decisions,
            directive_distribution=directive_dist,
            regime_distribution=regime_dist,
            avg_confidence=avg_conf,
            high_confidence_trades=high_conf_count,
            alert_count=alert_count,
        )

    def export_csv(self, report, path: Path) -> Path:
        """Export any report as CSV file.

        Args:
            report: SessionReport, StrategyReport, RiskReport, or HermesReport.
            path: Output CSV file path.

        Returns:
            Path to the written CSV file.
        """
        data = asdict(report)
        # Flatten: remove nested lists (fill_history, veto_history)
        flat_data = {}
        for k, v in data.items():
            if isinstance(v, list):
                # Skip complex nested lists for CSV header row
                flat_data[k] = f"{len(v)} items"
            elif isinstance(v, dict):
                flat_data[k] = json.dumps(v)
            else:
                flat_data[k] = v

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=flat_data.keys())
            writer.writeheader()
            writer.writerow(flat_data)

        logger.info("Report exported to %s", path)
        return path

    def export_json(self, report) -> dict:
        """Export any report as JSON-serializable dict.

        Args:
            report: SessionReport, StrategyReport, RiskReport, or HermesReport.

        Returns:
            JSON-serializable dict.
        """
        data = asdict(report)
        # Convert non-serializable types
        for k, v in data.items():
            if isinstance(v, dict):
                # Ensure all dict values are JSON-serializable
                data[k] = {
                    str(kk): vv for kk, vv in v.items()
                }
        return data

    def _compute_max_drawdown(self, fills: list[FillRecord]) -> float:
        """Compute maximum drawdown from fill PnL history."""
        if not fills:
            return 0.0

        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0

        for fill in fills:
            cumulative += fill.pnl
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        return max_dd

    def _compute_avg_drawdown(self, fills: list[FillRecord]) -> float:
        """Compute average drawdown from fill PnL history."""
        if not fills:
            return 0.0

        cumulative = 0.0
        peak = 0.0
        drawdowns: list[float] = []

        for fill in fills:
            cumulative += fill.pnl
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            drawdowns.append(dd)

        return sum(drawdowns) / len(drawdowns) if drawdowns else 0.0
