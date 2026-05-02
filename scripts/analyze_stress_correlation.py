#!/usr/bin/env python
"""Phase 21: Stress & Correlation Analysis.

Identifies worst drawdown windows and attributes losses to families.
Checks whether families lose together or independently.

Usage:
    python scripts/analyze_stress_correlation.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPORTS_DIR = Path("reports/portfolio")
OUTPUT_PATH = REPORTS_DIR / "stress_analysis.json"

TOP_N_DRAWDOWNS = 5


def load_result(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def find_drawdown_windows(equity_curve: list[dict], top_n: int = 5) -> list[dict]:
    """Identify the worst drawdown windows from equity curve."""
    if not equity_curve:
        return []

    peak = equity_curve[0]["equity"]
    peak_idx = 0
    windows: list[dict] = []
    current_dd_start = None
    current_dd_low = peak
    current_dd_low_idx = 0

    for i, point in enumerate(equity_curve):
        eq = point["equity"]
        if eq > peak:
            # New peak — close any open drawdown window
            if current_dd_start is not None:
                dd_depth = (current_dd_low - peak_at_start) / peak_at_start if peak_at_start > 0 else 0
                windows.append({
                    "start_bar": current_dd_start,
                    "end_bar": i - 1,
                    "start_timestamp": equity_curve[current_dd_start]["timestamp"],
                    "end_timestamp": equity_curve[i - 1]["timestamp"],
                    "peak_equity": round(peak_at_start, 2),
                    "trough_equity": round(current_dd_low, 2),
                    "drawdown_pct": round(abs(dd_depth), 4),
                    "duration_bars": i - current_dd_start,
                })
            peak = eq
            peak_idx = i
            current_dd_start = None
            current_dd_low = eq
        else:
            if current_dd_start is None:
                current_dd_start = i
                peak_at_start = peak
            if eq < current_dd_low:
                current_dd_low = eq
                current_dd_low_idx = i

    # Close any open window at end
    if current_dd_start is not None:
        dd_depth = (current_dd_low - peak_at_start) / peak_at_start if peak_at_start > 0 else 0
        windows.append({
            "start_bar": current_dd_start,
            "end_bar": len(equity_curve) - 1,
            "start_timestamp": equity_curve[current_dd_start]["timestamp"],
            "end_timestamp": equity_curve[-1]["timestamp"],
            "peak_equity": round(peak_at_start, 2),
            "trough_equity": round(current_dd_low, 2),
            "drawdown_pct": round(abs(dd_depth), 4),
            "duration_bars": len(equity_curve) - current_dd_start,
        })

    # Sort by drawdown depth (worst first) and return top N
    windows.sort(key=lambda w: w["drawdown_pct"], reverse=True)
    return windows[:top_n]


def attribute_window_losses(trades: list[dict], window: dict) -> dict:
    """Attribute losses within a drawdown window to families."""
    family_losses: dict[str, float] = {}
    family_count: dict[str, int] = {}

    for trade in trades:
        exit_bar = trade.get("exit_bar", 0)
        if window["start_bar"] <= exit_bar <= window["end_bar"]:
            fam = trade.get("strategy_family", "UNKNOWN")
            pnl = trade.get("pnl", 0.0)
            if pnl < 0:
                family_losses[fam] = family_losses.get(fam, 0.0) + abs(pnl)
                family_count[fam] = family_count.get(fam, 0) + 1

    return {
        "losses_by_family": {k: round(v, 2) for k, v in family_losses.items()},
        "losing_trades_by_family": family_count,
        "total_loss": round(sum(family_losses.values()), 2),
    }


def check_loss_correlation(trades: list[dict]) -> dict:
    """Check whether SF and MR losses co-occur during the same periods."""
    # Group trades by exit bar
    bar_trades: dict[int, list[dict]] = {}
    for trade in trades:
        bar = trade.get("exit_bar", 0)
        bar_trades.setdefault(bar, []).append(trade)

    # Count bars where both families have losing trades
    co_occurrence = 0
    sf_only_losses = 0
    mr_only_losses = 0
    bars_with_losses = 0

    for bar, bar_trade_list in bar_trades.items():
        losers = [t for t in bar_trade_list if t.get("pnl", 0) < 0]
        if not losers:
            continue

        bars_with_losses += 1
        families_with_losses = set(t.get("strategy_family") for t in losers)

        has_sf = "STRUCTURAL_FRACTAL" in families_with_losses
        has_mr = "MEAN_REVERSION" in families_with_losses

        if has_sf and has_mr:
            co_occurrence += 1
        elif has_sf:
            sf_only_losses += 1
        elif has_mr:
            mr_only_losses += 1

    return {
        "bars_with_losses": bars_with_losses,
        "co_occurrence": co_occurrence,
        "sf_only_losses": sf_only_losses,
        "mr_only_losses": mr_only_losses,
        "correlation_note": (
            "families lose independently"
            if co_occurrence == 0
            else f"families co-lose in {co_occurrence}/{bars_with_losses} loss bars"
        ),
    }


def analyze() -> dict:
    """Run stress and correlation analysis across all assets."""
    assets = ["BTC", "SPY", "TSLA"]
    all_results: dict[str, dict] = {}

    for asset in assets:
        path = REPORTS_DIR / f"{asset}_intraday.json"
        result = load_result(path)
        if result is None:
            continue

        equity_curve = result.get("equity_curve", [])
        trades = result.get("trades", [])

        # Find worst drawdown windows
        dd_windows = find_drawdown_windows(equity_curve, TOP_N_DRAWDOWNS)

        # Attribute losses to families
        for window in dd_windows:
            loss_attr = attribute_window_losses(trades, window)
            window["loss_attribution"] = loss_attr

        # Check loss correlation
        correlation = check_loss_correlation(trades)

        all_results[asset] = {
            "total_trades": len(trades),
            "total_pnl": round(sum(t.get("pnl", 0) for t in trades), 2),
            "worst_drawdowns": dd_windows,
            "loss_correlation": correlation,
        }

    output = {
        "description": (
            "Stress and correlation analysis across BTC, SPY, TSLA. "
            "intraday_default profile. Identifies worst drawdowns and "
            "attributes losses to families."
        ),
        "top_n_drawdowns": TOP_N_DRAWDOWNS,
        "per_asset": all_results,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    # Print summary
    print("\n" + "=" * 70)
    print("  STRESS & CORRELATION ANALYSIS")
    print("=" * 70)
    for asset, data in all_results.items():
        print(f"\n  {asset}:")
        print(f"    Total PnL: ${data['total_pnl']:,.2f}")
        print(f"    Trades: {data['total_trades']}")
        print(f"    Loss correlation: {data['loss_correlation']['correlation_note']}")
        if data["worst_drawdowns"]:
            worst = data["worst_drawdowns"][0]
            print(f"    Worst DD: {worst['drawdown_pct']:.1%} over {worst['duration_bars']} bars")
            la = worst.get("loss_attribution", {})
            if la.get("losses_by_family"):
                print(f"    DD loss by family: {la['losses_by_family']}")
    print("\n" + "=" * 70)
    print(f"  Saved: {OUTPUT_PATH}")

    return output


if __name__ == "__main__":
    analyze()
