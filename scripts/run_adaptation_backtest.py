#!/usr/bin/env python
"""Phase 22: Profile-Aware Adaptation Backtest Runner.

Runs backtests across all 4 risk appetite profiles and compares results.
Uses run_dual_mtf_backtest with the risk_profile parameter.

Usage:
    python scripts/run_adaptation_backtest.py
    python scripts/run_adaptation_backtest.py --profile balanced
    python scripts/run_adaptation_backtest.py --profile ftmo_safe --asset SPY
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.market.data_loader import load_csv, load_csv_multi
from src.profiles.presets import RISK_PROFILES, list_risk_profile_ids
from scripts.run_strategy_backtest import run_dual_mtf_backtest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ASSETS = {
    "BTC": "data/historical/btc-usd_1h_12m.csv",
    "SPY": "data/historical/spy_1h_12m.csv",
    "TSLA": "data/historical/tsla_1h_12m.csv",
}

REPORTS_DIR = Path("reports/adaptation")


def run_single_backtest(
    data_path: str,
    symbol: str,
    risk_profile: str,
    ltf_path: str | None = None,
) -> dict:
    """Run a single backtest with the given risk profile.

    Returns:
        Summary dict from the backtest result.
    """
    data_file = Path(data_path)
    if not data_file.exists():
        logger.warning("Data file not found: %s", data_path)
        return {"error": f"Data file not found: {data_path}"}

    # Load data
    if ltf_path and Path(ltf_path).exists():
        htf_bars, ltf_bars_data = load_csv_multi(str(data_file), ltf_path)
    else:
        htf_bars = load_csv(str(data_file))
        ltf_bars_data = None

    if not htf_bars:
        logger.warning("No bars loaded from %s", data_path)
        return {"error": "No bars loaded"}

    logger.info(
        "Running %s | %s | profile=%s (%d bars)",
        symbol, data_path, risk_profile, len(htf_bars),
    )

    result = run_dual_mtf_backtest(
        bars=htf_bars,
        symbol=symbol,
        ltf_bars=ltf_bars_data,
        risk_profile=risk_profile,
    )

    return result.summary


def run_adaptation_backtest(
    profiles: list[str] | None = None,
    assets: dict[str, str] | None = None,
) -> dict[str, dict]:
    """Run backtests with each risk appetite profile and collect results.

    Args:
        profiles: List of profile names. None = all 4.
        assets: Dict of symbol→data_path. None = default ASSETS.

    Returns:
        Dict of (asset, profile) → summary.
    """
    if profiles is None:
        profiles = list_risk_profile_ids()
    if assets is None:
        assets = ASSETS

    results: dict[str, dict] = {}

    for profile_name in profiles:
        for asset_name, data_path in assets.items():
            # Determine LTF path
            ltf_path = None
            data_file = Path(data_path)
            ltf_candidate = data_file.parent / "spy_15m_2m.csv"
            if ltf_candidate.exists():
                ltf_path = str(ltf_candidate)

            key = f"{asset_name}_{profile_name}"
            summary = run_single_backtest(
                data_path=data_path,
                symbol=asset_name,
                risk_profile=profile_name,
                ltf_path=ltf_path,
            )
            results[key] = summary

            # Print quick summary
            if "error" in summary:
                print(f"  {key}: ERROR - {summary['error']}")
            else:
                print(
                    f"  {key}: trades={summary.get('total_trades', 0)}, "
                    f"pnl={summary.get('total_pnl', 0):.2f}, "
                    f"win_rate={summary.get('win_rate', 0):.1%}, "
                    f"max_dd={summary.get('max_drawdown_pct', 0):.1%}"
                )

    return results


def save_results(results: dict[str, dict], output_dir: Path) -> Path:
    """Save all results to a JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "adaptation_results.json"

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\nSaved results to: {output_path}")
    return output_path


def generate_comparison_table(results: dict[str, dict]) -> str:
    """Generate a markdown comparison table from results."""
    lines = [
        "# Risk Profile Comparison",
        "",
        "| Asset | Profile | Trades | PnL | Win Rate | Max DD | Profit Factor |",
        "|-------|---------|--------|-----|----------|--------|---------------|",
    ]

    for key, summary in sorted(results.items()):
        if "error" in summary:
            lines.append(f"| {key} | - | ERROR | {summary['error']} | - | - | - |")
            continue

        parts = key.rsplit("_", 1)
        asset = parts[0] if len(parts) > 1 else key
        profile = parts[1] if len(parts) > 1 else "unknown"

        lines.append(
            f"| {asset} | {profile} "
            f"| {summary.get('total_trades', 0)} "
            f"| {summary.get('total_pnl', 0):.2f} "
            f"| {summary.get('win_rate', 0):.1%} "
            f"| {summary.get('max_drawdown_pct', 0):.1%} "
            f"| {summary.get('profit_factor', 'inf')} |"
        )

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 22: Profile-Aware Adaptation Backtest"
    )
    parser.add_argument(
        "--profile",
        choices=list_risk_profile_ids(),
        default=None,
        help="Run specific profile only (default: all)",
    )
    parser.add_argument(
        "--asset",
        choices=list(ASSETS.keys()),
        default=None,
        help="Run specific asset only (default: all)",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPORTS_DIR),
        help="Output directory for reports",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    profiles = [args.profile] if args.profile else None
    assets = {args.asset: ASSETS[args.asset]} if args.asset else None

    print("=" * 60)
    print("Phase 22: Risk Appetite Profile Adaptation Backtest")
    print("=" * 60)
    print(f"Profiles: {profiles or list_risk_profile_ids()}")
    print(f"Assets: {list((assets or ASSETS).keys())}")
    print()

    results = run_adaptation_backtest(profiles=profiles, assets=assets)

    output_dir = Path(args.output_dir)
    save_results(results, output_dir)

    # Generate comparison table
    table = generate_comparison_table(results)
    table_path = output_dir / "comparison_table.md"
    with open(table_path, "w") as f:
        f.write(table)
    print(f"Saved comparison table to: {table_path}")
    print()
    print(table)


if __name__ == "__main__":
    main()
