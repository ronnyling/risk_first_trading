"""Daily summary report for paper-trading sessions.

Queries the persistence DB and produces a structured JSON report
covering fills, vetoes, portfolio state, and strategy performance.

Usage:
    python scripts/daily_report.py                    # Today's summary
    python scripts/daily_report.py --date 2026-04-29  # Specific date
    python scripts/daily_report.py --days 7           # Last 7 days
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path


DB_PATH = Path("data/trading_state.db")
LOG_DIR = Path("logs")


def get_connection() -> sqlite3.Connection:
    """Open a read-only connection to the persistence DB."""
    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def generate_report(conn: sqlite3.Connection, date_str: str) -> dict:
    """Generate a daily summary report for the given date (YYYY-MM-DD)."""
    day_start = f"{date_str}T00:00:00"
    day_end = f"{date_str}T23:59:59"

    report = {
        "date": date_str,
        "generated_at": datetime.now().isoformat(),
    }

    # Engine runs on this day
    runs = conn.execute(
        "SELECT COUNT(*) as cnt FROM engine_runs WHERE started_at BETWEEN ? AND ?",
        (day_start, day_end),
    ).fetchone()["cnt"]
    report["engine_runs"] = runs

    # Fills on this day
    fills = conn.execute(
        "SELECT COUNT(*) as cnt FROM fills WHERE timestamp BETWEEN ? AND ?",
        (day_start, day_end),
    ).fetchone()["cnt"]
    report["total_fills"] = fills

    # Vetoes on this day
    vetoes = conn.execute(
        "SELECT COUNT(*) as cnt FROM vetoes WHERE timestamp BETWEEN ? AND ?",
        (day_start, day_end),
    ).fetchone()["cnt"]
    report["total_vetoes"] = vetoes

    # Kill switch events (vetoes with kill switch reason)
    kill_events = conn.execute(
        "SELECT COUNT(*) as cnt FROM vetoes WHERE timestamp BETWEEN ? AND ? AND reason LIKE '%Kill switch%'",
        (day_start, day_end),
    ).fetchone()["cnt"]
    report["kill_switch_events"] = kill_events

    # Fill details by strategy
    strategy_fills = conn.execute(
        """SELECT strategy_id, COUNT(*) as cnt, SUM(pnl) as total_pnl, SUM(commission) as total_commission
           FROM fills WHERE timestamp BETWEEN ? AND ?
           GROUP BY strategy_id""",
        (day_start, day_end),
    ).fetchall()

    strategies = {}
    for row in strategy_fills:
        sid = row["strategy_id"] or "unknown"
        strategies[sid] = {
            "fills": row["cnt"],
            "pnl": round(row["total_pnl"] or 0.0, 2),
            "commission": round(row["total_commission"] or 0.0, 2),
        }
    report["strategies"] = strategies

    # Veto reasons breakdown
    veto_reasons = conn.execute(
        """SELECT reason, COUNT(*) as cnt FROM vetoes
           WHERE timestamp BETWEEN ? AND ?
           GROUP BY reason ORDER BY cnt DESC""",
        (day_start, day_end),
    ).fetchall()
    report["vetoes_by_reason"] = {row["reason"]: row["cnt"] for row in veto_reasons}

    # Portfolio state from most recent engine run
    last_run = conn.execute(
        """SELECT final_portfolio_value, final_pnl
           FROM engine_runs WHERE started_at BETWEEN ? AND ?
           ORDER BY run_id DESC LIMIT 1""",
        (day_start, day_end),
    ).fetchone()

    if last_run and last_run["final_portfolio_value"] is not None:
        report["portfolio_value"] = round(last_run["final_portfolio_value"], 2)
        report["portfolio_pnl"] = round(last_run["final_pnl"] or 0.0, 2)
        if last_run["final_portfolio_value"] > 0:
            report["portfolio_pnl_pct"] = round(
                (last_run["final_pnl"] or 0.0) / last_run["final_portfolio_value"] * 100, 2
            )
    else:
        report["portfolio_value"] = None
        report["portfolio_pnl"] = None
        report["portfolio_pnl_pct"] = None

    # Strategy states
    strat_states = conn.execute(
        "SELECT strategy_id, state FROM strategy_states"
    ).fetchall()
    for row in strat_states:
        sid = row["strategy_id"]
        if sid in strategies:
            strategies[sid]["state"] = row["state"]

    # Risk summary
    report["risk_summary"] = {
        "kill_active": kill_events > 0,
        "vetoes_by_reason": report["vetoes_by_reason"],
    }

    # Regime changes on this day
    regimes = conn.execute(
        "SELECT COUNT(*) as cnt FROM regime_changes WHERE timestamp BETWEEN ? AND ?",
        (day_start, day_end),
    ).fetchone()["cnt"]
    report["regime_changes"] = regimes

    return report


def print_report(report: dict) -> None:
    """Print a human-readable summary to console."""
    print("=" * 60)
    print(f"DAILY REPORT: {report['date']}")
    print("=" * 60)
    print(f"  Engine runs:     {report['engine_runs']}")
    print(f"  Total fills:     {report['total_fills']}")
    print(f"  Total vetoes:    {report['total_vetoes']}")
    print(f"  Kill switch:     {report['kill_switch_events']} event(s)")
    print(f"  Regime changes:  {report['regime_changes']}")
    print()

    if report.get("portfolio_value") is not None:
        print(f"  Portfolio value: ${report['portfolio_value']:,.2f}")
        pnl = report.get("portfolio_pnl", 0) or 0
        pnl_pct = report.get("portfolio_pnl_pct", 0) or 0
        print(f"  Portfolio PnL:   ${pnl:,.2f} ({pnl_pct:+.2f}%)")
    else:
        print("  Portfolio:       No data")
    print()

    if report.get("strategies"):
        print("  Strategies:")
        for sid, data in report["strategies"].items():
            state = data.get("state", "unknown")
            print(f"    {sid}: fills={data['fills']}, pnl=${data['pnl']:+.2f}, state={state}")
    print()

    if report.get("vetoes_by_reason"):
        print("  Veto reasons:")
        for reason, count in report["vetoes_by_reason"].items():
            print(f"    [{count}] {reason}")
    print("=" * 60)


def main() -> None:
    # Parse arguments
    date_str = datetime.now().strftime("%Y-%m-%d")
    days = 1

    if "--date" in sys.argv:
        idx = sys.argv.index("--date")
        if idx + 1 < len(sys.argv):
            date_str = sys.argv[idx + 1]
    elif "--days" in sys.argv:
        idx = sys.argv.index("--days")
        if idx + 1 < len(sys.argv):
            days = int(sys.argv[idx + 1])

    conn = get_connection()

    if days > 1:
        # Multi-day report
        all_reports = []
        for i in range(days):
            d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            report = generate_report(conn, d)
            all_reports.append(report)
            print_report(report)
            print()

        # Save combined report
        report_path = LOG_DIR / f"daily_report_{date_str}_last{days}days.json"
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(all_reports, f, indent=2, default=str)
        print(f"Multi-day report saved to {report_path}")
    else:
        # Single day report
        report = generate_report(conn, date_str)
        print_report(report)

        # Save to file
        report_path = LOG_DIR / f"daily_report_{date_str}.json"
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\nReport saved to {report_path}")

    conn.close()


if __name__ == "__main__":
    main()