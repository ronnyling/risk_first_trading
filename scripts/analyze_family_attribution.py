#!/usr/bin/env python
"""Phase 21: Family Attribution Analysis.

Reads per-asset backtest results and produces family-level PnL attribution.

Usage:
    python scripts/analyze_family_attribution.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPORTS_DIR = Path("reports/portfolio")
OUTPUT_PATH = REPORTS_DIR / "family_attribution.json"

MIN_TRADES_FOR_INFERENCE = 5


def load_result(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def analyze() -> dict:
    """Analyze family attribution across all assets."""
    assets = ["BTC", "SPY", "TSLA"]

    # Combined stats across assets
    combined: dict[str, dict] = {
        "STRUCTURAL_FRACTAL": {"pnl": 0.0, "trades": 0, "wins": 0, "r_values": []},
        "MEAN_REVERSION": {"pnl": 0.0, "trades": 0, "wins": 0, "r_values": []},
    }

    per_asset: dict[str, dict] = {}

    for asset in assets:
        path = REPORTS_DIR / f"{asset}_intraday.json"
        result = load_result(path)
        if result is None:
            continue

        trades = result.get("trades", [])
        asset_stats: dict[str, dict] = {}

        for family in ["STRUCTURAL_FRACTAL", "MEAN_REVERSION"]:
            fam_trades = [t for t in trades if t.get("strategy_family") == family]
            pnl = sum(t["pnl"] for t in fam_trades)
            wins = sum(1 for t in fam_trades if t["pnl"] > 0)
            r_vals = [t["r_multiple"] for t in fam_trades]
            count = len(fam_trades)

            asset_stats[family] = {
                "pnl": round(pnl, 2),
                "trades": count,
                "wins": wins,
                "win_rate": round(wins / count, 4) if count > 0 else 0.0,
                "avg_r": round(sum(r_vals) / len(r_vals), 4) if r_vals else 0.0,
            }

            combined[family]["pnl"] += pnl
            combined[family]["trades"] += count
            combined[family]["wins"] += wins
            combined[family]["r_values"].extend(r_vals)

        per_asset[asset] = asset_stats

    # Compute combined stats
    combined_output: dict[str, dict] = {}
    for family in ["STRUCTURAL_FRACTAL", "MEAN_REVERSION"]:
        cs = combined[family]
        count = cs["trades"]
        has_enough = count >= MIN_TRADES_FOR_INFERENCE

        combined_output[family] = {
            "pnl": round(cs["pnl"], 2),
            "trades": count,
            "wins": cs["wins"],
            "win_rate": round(cs["wins"] / count, 4) if count > 0 else 0.0,
            "avg_r": round(sum(cs["r_values"]) / len(cs["r_values"]), 4) if cs["r_values"] else 0.0,
            "sufficient_sample": has_enough,
            "inference_note": "reliable" if has_enough else f"insufficient sample ({count} < {MIN_TRADES_FOR_INFERENCE})",
        }

    output = {
        "description": (
            "Family attribution across BTC, SPY, TSLA. "
            "intraday_default profile. Only execution-validated strategies included."
        ),
        "min_trades_for_inference": MIN_TRADES_FOR_INFERENCE,
        "per_asset": per_asset,
        "combined": combined_output,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(output, f, indent=2)

    # Print summary
    print("\n" + "=" * 70)
    print("  FAMILY ATTRIBUTION")
    print("=" * 70)
    for family in ["STRUCTURAL_FRACTAL", "MEAN_REVERSION"]:
        cs = combined_output[family]
        print(f"\n  {family}:")
        print(f"    PnL:      ${cs['pnl']:>10,.2f}")
        print(f"    Trades:   {cs['trades']:>10d}")
        print(f"    Win rate: {cs['win_rate']:>10.1%}")
        print(f"    Avg R:    {cs['avg_r']:>10.4f}")
        print(f"    Sample:   {cs['inference_note']}")
    print("\n" + "=" * 70)
    print(f"  Saved: {OUTPUT_PATH}")

    return output


if __name__ == "__main__":
    analyze()
