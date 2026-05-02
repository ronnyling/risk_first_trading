#!/usr/bin/env python
"""A/B/Dual Backtest Comparison Analysis.

Reads reports/strategy_backtest_{mode}.json and produces side-by-side comparison.

Usage:
    python scripts/analyze_strategy_comparison.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPORTS_DIR = Path("reports")


def load_report(path: Path) -> dict | None:
    """Load a backtest report JSON. Returns None if not found."""
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def format_val(v: float | str | int) -> str:
    """Format a value for display."""
    if isinstance(v, float):
        if abs(v) < 1.0 and v != 0:
            return f"{v:.1%}"
        return f"{v:.4f}"
    return str(v)


def delta_str(a: float | str, b: float | str, lower_is_better: bool = False) -> str:
    """Format comparison delta string."""
    if isinstance(a, str) or isinstance(b, str):
        return "N/A"
    delta = b - a
    sign = "+" if delta > 0 else ""
    if lower_is_better:
        good = delta < 0
    else:
        good = delta > 0
    marker = "[+]" if good else "[-]"
    return f"{sign}{delta:.4f} {marker}"


def main() -> None:
    baseline = load_report(REPORTS_DIR / "strategy_backtest_baseline.json")
    hermes = load_report(REPORTS_DIR / "strategy_backtest_hermes.json")
    dual = load_report(REPORTS_DIR / "strategy_backtest_dual.json")

    if not baseline:
        print("Error: baseline report not found"); sys.exit(1)

    bs = baseline["summary"]
    has_hermes = hermes is not None
    has_dual = dual is not None
    hs = hermes["summary"] if has_hermes else None
    ds = dual["summary"] if has_dual else None

    # Title
    print("\n" + "=" * 80)
    print("  STRATEGY BACKTEST COMPARISON")
    print("=" * 80)
    print(f"  Data: {bs['total_bars']} bars")
    if has_hermes:
        print(f"  Baseline: strategy_backtest_baseline.json")
        print(f"  Hermes:   strategy_backtest_hermes.json")
    if has_dual:
        print(f"  Dual:     strategy_backtest_dual.json")
    print("=" * 80)

    # Header
    if has_dual:
        print(f"\n{'Metric':<30} {'Baseline':>14} {'Hermes':>14} {'Dual System':>14}")
    else:
        print(f"\n{'Metric':<30} {'Baseline (A)':>15} {'Hermes (B)':>15}")
    print("-" * 74)

    # Trade metrics
    rows = [
        ("Total trades", "total_trades", False),
        ("Winning trades", "winning_trades", False),
        ("Losing trades", "losing_trades", True),
        ("Win rate", "win_rate", False),
        ("Total PnL", "total_pnl", False),
        ("Avg R / trade", "avg_r_per_trade", False),
        ("Max drawdown %", "max_drawdown_pct", True),
        ("Max DD duration", "max_drawdown_duration_bars", True),
        ("Profit factor", "profit_factor", False),
    ]

    for label, key, lower_better in rows:
        a = bs.get(key, 0)
        b = hs.get(key, 0) if hs else "N/A"
        d = ds.get(key, 0) if ds else "N/A"

        a_str = format_val(a) if isinstance(a, (int, float)) else str(a)
        b_str = format_val(b) if isinstance(b, (int, float)) else str(b)
        d_str = format_val(d) if isinstance(d, (int, float)) else str(d)

        if has_dual:
            print(f"{label:<30} {a_str:>14} {b_str:>14} {d_str:>14}")
        elif has_hermes:
            delta = delta_str(a, b, lower_better)
            print(f"{label:<30} {a_str:>15} {b_str:>15} {delta:>12}")

    # Gating stats
    print()
    print("-" * 74)

    if has_hermes and hs.get("trades_gated", 0) > 0:
        print(f"{'Hermes trades gated':<30} {hs['trades_gated']:>14}")
        for reason, count in hs.get("gate_reasons", {}).items():
            print(f"  {reason:<28} {count:>14}")

    if has_dual and ds.get("trades_gated", 0) > 0:
        print(f"{'Dual trades gated':<30} {ds['trades_gated']:>14}")
        for reason, count in ds.get("gate_reasons", {}).items():
            print(f"  {reason:<28} {count:>14}")

    # Dual system bar exposure
    if has_dual and ds.get("family_bars"):
        print()
        print("-" * 74)
        print("FAMILY BAR EXPOSURE (Dual System):")
        total_bars = ds.get("total_bars", 1)
        for fam, count in ds["family_bars"].items():
            pct = count / total_bars if total_bars > 0 else 0
            print(f"  {fam:<30} {count:>6} bars  ({pct:.1%})")
        print(f"  {'Family switches':<30} {ds.get('family_switches', 0):>6}")

    print()
    print("-" * 74)

    # Interpretation
    print("\nINTERPRETATION:")

    if has_hermes:
        if hs["max_drawdown_pct"] < bs["max_drawdown_pct"]:
            print("  [PASS] Hermes REDUCED max drawdown")
        else:
            print("  [FAIL] Hermes did NOT reduce max drawdown")

        if hs["avg_r_per_trade"] > bs["avg_r_per_trade"]:
            print("  [PASS] Hermes IMPROVED avg R per trade")
        else:
            print("  [FAIL] Hermes did NOT improve avg R per trade")

        if hs["total_trades"] < bs["total_trades"]:
            print(f"  [PASS] Hermes SKIPPED {bs['total_trades'] - hs['total_trades']} trades")

    if has_dual:
        print()
        if ds["max_drawdown_pct"] <= bs["max_drawdown_pct"]:
            print("  [PASS] Dual system REDUCED max drawdown vs baseline")
        else:
            print("  [FAIL] Dual system did NOT reduce max drawdown")

        # Check no overlapping trades
        dual_trades = dual.get("trades", [])
        overlap = False
        for i in range(len(dual_trades)):
            for j in range(i + 1, len(dual_trades)):
                t1, t2 = dual_trades[i], dual_trades[j]
                # Check if bars overlap
                if (t1["entry_bar"] <= t2["exit_bar"] and
                    t2["entry_bar"] <= t1["exit_bar"]):
                    overlap = True
        if not overlap:
            print("  [PASS] No overlapping trades between families")
        else:
            print("  [FAIL] Overlapping trades detected")

        # Family exposure
        fb = ds.get("family_bars", {})
        active = sum(v for k, v in fb.items() if k != "NONE")
        if active > 0:
            print(f"  [PASS] Both families traded ({active} bars active)")
        else:
            print("  [FAIL] No active family bars")

    print()

    # Save comparison JSON
    comparison = {
        "baseline": bs,
    }
    if has_hermes:
        comparison["hermes"] = hs
    if has_dual:
        comparison["dual"] = ds
        comparison["dual_analysis"] = {
            "family_bars": ds.get("family_bars", {}),
            "family_switches": ds.get("family_switches", 0),
            "drawdown_vs_baseline": ds["max_drawdown_pct"] <= bs["max_drawdown_pct"],
        }

    output_path = REPORTS_DIR / "strategy_comparison.json"
    with open(output_path, "w") as f:
        json.dump(comparison, f, indent=2)
    print(f"Saved comparison: {output_path}")


if __name__ == "__main__":
    main()