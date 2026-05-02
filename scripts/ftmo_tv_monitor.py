"""Phase 17: TradingView FTMO Monitor — independent compliance verification.

Reads TradingView trade data (exported CSV or manual entry) and applies
FTMO rules independently to verify compliance. Generates daily reports.

Usage:
    python scripts/ftmo_tv_monitor.py                           # Check latest state
    python scripts/ftmo_tv_monitor.py --trades trades.csv       # Analyze exported trades
    python scripts/ftmo_tv_monitor.py --status                  # Current compliance status
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from src.risk.ftmo_guard import FTMOConfig, FTMOGuard

logger = logging.getLogger("ftmo_tv_monitor")

REPORTS_DIR = Path("reports/ftmo_tv")

# FTMO limits (matching Pine Script hard-coded values)
FTMO_LIMITS = FTMOConfig(
    max_daily_loss_pct=0.045,     # 4.5% (buffer below 5%)
    max_total_drawdown_pct=0.09,  # 9% (buffer below 10%)
    profit_target_pct=0.10,       # 10% target
    consistency_max_pct=0.05,     # 5% max per trade
)


def load_trades_csv(csv_path: str) -> list[dict]:
    """Load TradingView exported trades CSV."""
    trades = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trades.append(row)
    return trades


def analyze_trades(trades: list[dict], initial_equity: float = 100_000.0) -> dict:
    """Analyze trades against FTMO rules.

    Expects trades with columns: date, side, qty, price, pnl (or similar).
    """
    guard = FTMOGuard(FTMO_LIMITS)
    equity = initial_equity
    peak_equity = initial_equity
    daily_start = initial_equity
    current_date = None

    violations = []
    equity_curve = [{"date": "start", "equity": equity}]
    daily_summary = []

    for trade in trades:
        trade_date = trade.get("date", trade.get("Date", ""))[:10]

        # Day boundary
        if trade_date != current_date:
            if current_date is not None:
                daily_summary.append({
                    "date": current_date,
                    "start_equity": daily_start,
                    "end_equity": equity,
                    "pnl": equity - daily_start,
                })
            current_date = trade_date
            daily_start = equity
            guard.update_daily(equity=equity, bar_timestamp=trade_date)

        # Extract PnL
        pnl = float(trade.get("pnl", trade.get("PnL", trade.get("profit", 0))))
        equity += pnl

        if equity > peak_equity:
            peak_equity = equity

        # Check FTMO compliance
        check = guard.check(equity=equity, peak_equity=peak_equity)
        if not check.compliant:
            for v in check.violations:
                violations.append({
                    "date": trade_date,
                    "violation": v,
                    "action": check.action,
                    "equity": equity,
                })

        equity_curve.append({"date": trade_date, "equity": round(equity, 2)})

    # Final daily summary
    if current_date:
        daily_summary.append({
            "date": current_date,
            "start_equity": daily_start,
            "end_equity": equity,
            "pnl": equity - daily_start,
        })

    total_return = (equity - initial_equity) / initial_equity
    max_dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
    profit_target = initial_equity * (1 + FTMO_LIMITS.profit_target_pct)
    passed = equity >= profit_target and len(violations) == 0

    return {
        "initial_equity": initial_equity,
        "final_equity": round(equity, 2),
        "peak_equity": round(peak_equity, 2),
        "total_return_pct": round(total_return * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "profit_target": round(profit_target, 2),
        "target_reached": equity >= profit_target,
        "violations": violations,
        "violation_count": len(violations),
        "passed": passed,
        "total_trades": len(trades),
        "equity_curve": equity_curve,
        "daily_summary": daily_summary,
    }


def save_report(result: dict, output_dir: Path) -> Path:
    """Save analysis report."""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"ftmo_monitor_{ts}.json"
    report_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    return report_path


def print_status(result: dict) -> None:
    """Print human-readable status."""
    print("=" * 60)
    print("FTMO COMPLIANCE STATUS (TradingView Monitor)")
    print("=" * 60)
    print(f"  Initial equity:  ${result['initial_equity']:,.2f}")
    print(f"  Final equity:    ${result['final_equity']:,.2f}")
    print(f"  Peak equity:     ${result['peak_equity']:,.2f}")
    print(f"  Total return:    {result['total_return_pct']:+.2f}%")
    print(f"  Max drawdown:    {result['max_drawdown_pct']:.2f}%")
    print(f"  Profit target:   ${result['profit_target']:,.2f}")
    print(f"  Target reached:  {'YES' if result['target_reached'] else 'NO'}")
    print(f"  Total trades:    {result['total_trades']}")
    print(f"  Violations:      {result['violation_count']}")
    print()

    if result["violations"]:
        print("  VIOLATIONS:")
        for v in result["violations"]:
            print(f"    [{v['date']}] {v['violation']} (action={v['action']})")
        print()

    verdict = "PASS" if result["passed"] else "FAIL"
    print(f"  VERDICT: **{verdict}**")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 17: FTMO TradingView Monitor")
    parser.add_argument("--trades", default=None, help="Path to TradingView exported trades CSV")
    parser.add_argument("--status", action="store_true", help="Show current compliance status")
    parser.add_argument("--equity", type=float, default=100_000.0, help="Starting equity")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.trades:
        logger.info("Loading trades from: %s", args.trades)
        trades = load_trades_csv(args.trades)
        logger.info("Loaded %d trades", len(trades))

        result = analyze_trades(trades, initial_equity=args.equity)
        print_status(result)

        report_path = save_report(result, REPORTS_DIR)
        print(f"\nReport saved: {report_path}")

        sys.exit(0 if result["passed"] else 1)
    elif args.status:
        # Show FTMO limits (no trades to analyze)
        print("=" * 60)
        print("FTMO LIMITS (ftmo_safe profile — hard-coded)")
        print("=" * 60)
        print(f"  Daily loss limit:   {FTMO_LIMITS.max_daily_loss_pct:.1%}")
        print(f"  Max drawdown:       {FTMO_LIMITS.max_total_drawdown_pct:.1%}")
        print(f"  Profit target:      {FTMO_LIMITS.profit_target_pct:.1%}")
        print(f"  Consistency max:    {FTMO_LIMITS.consistency_max_pct:.1%}")
        print()
        print("  To analyze trades: --trades <path_to_csv>")
        print("=" * 60)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
