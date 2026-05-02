#!/usr/bin/env python
"""Phase 21: Regime × Family Matrix Analysis.

Builds a regime × family matrix showing expectancy, trade count, and PnL per cell.

Usage:
    python scripts/analyze_regime_family_matrix.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPORTS_DIR = Path("reports/portfolio")
OUTPUT_PATH = REPORTS_DIR / "regime_family_matrix.json"

REGIMES = ["trending", "ranging", "volatile"]
FAMILIES = ["STRUCTURAL_FRACTAL", "MEAN_REVERSION"]
MIN_TRADES_FOR_INFERENCE = 5


def load_result(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def analyze() -> dict:
    """Build regime × family matrix across all assets."""
    assets = ["BTC", "SPY", "TSLA"]

    # Combined matrix
    matrix: dict[str, dict[str, dict]] = {}
    for regime in REGIMES:
        matrix[regime] = {}
        for family in FAMILIES:
            matrix[regime][family] = {"pnl": 0.0, "trades": 0, "wins": 0, "r_values": []}

    per_asset: dict[str, dict] = {}

    for asset in assets:
        path = REPORTS_DIR / f"{asset}_intraday.json"
        result = load_result(path)
        if result is None:
            continue

        trades = result.get("trades", [])
        asset_matrix: dict[str, dict] = {}

        for regime in REGIMES:
            asset_matrix[regime] = {}
            for family in FAMILIES:
                cell_trades = [
                    t for t in trades
                    if t.get("regime_at_entry", "").lower() == regime
                    and t.get("strategy_family") == family
                ]
                pnl = sum(t["pnl"] for t in cell_trades)
                wins = sum(1 for t in cell_trades if t["pnl"] > 0)
                r_vals = [t["r_multiple"] for t in cell_trades]
                count = len(cell_trades)

                asset_matrix[regime][family] = {
                    "pnl": round(pnl, 2),
                    "trades": count,
                    "wins": wins,
                    "win_rate": round(wins / count, 4) if count > 0 else 0.0,
                    "avg_r": round(sum(r_vals) / len(r_vals), 4) if r_vals else 0.0,
                }

                # Accumulate to combined
                matrix[regime][family]["pnl"] += pnl
                matrix[regime][family]["trades"] += count
                matrix[regime][family]["wins"] += wins
                matrix[regime][family]["r_values"].extend(r_vals)

        per_asset[asset] = asset_matrix

    # Compute combined cell stats
    combined_matrix: dict[str, dict[str, dict]] = {}
    for regime in REGIMES:
        combined_matrix[regime] = {}
        for family in FAMILIES:
            cell = matrix[regime][family]
            count = cell["trades"]
            has_enough = count >= MIN_TRADES_FOR_INFERENCE
            combined_matrix[regime][family] = {
                "pnl": round(cell["pnl"], 2),
                "trades": count,
                "wins": cell["wins"],
                "win_rate": round(cell["wins"] / count, 4) if count > 0 else 0.0,
                "avg_r": round(sum(cell["r_values"]) / len(cell["r_values"]), 4) if cell["r_values"] else 0.0,
                "sufficient_sample": has_enough,
                "label": "reliable" if has_enough else f"low count ({count})",
            }

    output = {
        "description": (
            "Regime × Family matrix across BTC, SPY, TSLA. "
            "intraday_default profile. Only execution-validated families included."
        ),
        "min_trades_for_inference": MIN_TRADES_FOR_INFERENCE,
        "per_asset": per_asset,
        "combined_matrix": combined_matrix,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    # Print ASCII matrix
    print("\n" + "=" * 80)
    print("  REGIME × FAMILY MATRIX (Combined)")
    print("=" * 80)
    print(f"\n  {'Regime':<12} {'Family':<22} {'Trades':>7} {'Win%':>7} {'Avg R':>8} {'PnL':>10} {'Sample'}")
    print("  " + "-" * 76)
    for regime in REGIMES:
        for family in FAMILIES:
            cell = combined_matrix[regime][family]
            print(
                f"  {regime:<12} {family:<22} {cell['trades']:>7d} "
                f"{cell['win_rate']:>6.1%} {cell['avg_r']:>8.4f} "
                f"${cell['pnl']:>9,.2f}  {cell['label']}"
            )
        print()
    print("=" * 80)
    print(f"  Saved: {OUTPUT_PATH}")

    return output


if __name__ == "__main__":
    analyze()
