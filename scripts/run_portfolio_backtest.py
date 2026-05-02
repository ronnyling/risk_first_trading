#!/usr/bin/env python
"""Phase 21: Multi-Asset Portfolio Backtest Runner.

Runs the dual_mtf backtest across all available assets using the
intraday_default profile (1H HTF matches native data timeframe).

Usage:
    python scripts/run_portfolio_backtest.py
    python scripts/run_portfolio_backtest.py --assets BTC SPY
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.market.data_loader import load_csv, load_csv_multi
from scripts.run_strategy_backtest import (
    BacktestResult,
    run_dual_mtf_backtest,
    save_result,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("portfolio_backtest")

REPORTS_DIR = Path("reports/portfolio")

# Asset definitions — 1H data only (matches intraday_default profile HTF)
ASSETS: dict[str, dict] = {
    "BTC": {
        "data_path": Path("data/historical/btc-usd_1h_12m.csv"),
        "ltf_path": None,  # No BTC LTF data
        "symbol": "BTC/USD",
    },
    "SPY": {
        "data_path": Path("data/historical/spy_1h_12m.csv"),
        "ltf_path": Path("data/historical/spy_15m_2m.csv"),
        "symbol": "SPY",
    },
    "TSLA": {
        "data_path": Path("data/historical/tsla_1h_12m.csv"),
        "ltf_path": None,  # No TSLA LTF data
        "symbol": "TSLA",
    },
}

# Profile: intraday_default only (1H HTF matches native data timeframe)
# Other profiles are deferred — timeframe mismatch would contaminate attribution
PROFILE = "intraday_default"


def run_all() -> dict[str, BacktestResult]:
    """Run portfolio backtest across all assets."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    results: dict[str, BacktestResult] = {}

    for asset_name, asset_def in ASSETS.items():
        logger.info("Running %s backtest...", asset_name)

        if not asset_def["data_path"].exists():
            logger.warning("Data file not found: %s — skipping", asset_def["data_path"])
            continue

        # Load HTF bars
        htf_bars = load_csv(str(asset_def["data_path"]))

        # Load LTF bars if available
        ltf_bars = None
        if asset_def["ltf_path"] and asset_def["ltf_path"].exists():
            _, ltf_bars = load_csv_multi(
                str(asset_def["data_path"]), str(asset_def["ltf_path"])
            )

        # Run backtest
        result = run_dual_mtf_backtest(htf_bars, symbol=asset_def["symbol"], ltf_bars=ltf_bars)

        # Save per-asset result
        output_path = REPORTS_DIR / f"{asset_name}_intraday.json"
        save_result(result, output_path)

        results[asset_name] = result

        # Print summary
        s = result.summary
        logger.info(
            "  %s: %d trades, %.1f%% win rate, $%.0f PnL, %.1f%% max DD",
            asset_name,
            s["total_trades"],
            s["win_rate"] * 100,
            s["total_pnl"],
            s["max_drawdown_pct"] * 100,
        )

    return results


def save_aggregate_summary(results: dict[str, BacktestResult]) -> None:
    """Save cross-asset aggregate summary."""
    summary = {
        "profile": PROFILE,
        "description": (
            "Phase 21 portfolio backtest — intraday_default profile only. "
            "1H data matches profile HTF. Analysis covers STRUCTURAL_FRACTAL and "
            "MEAN_REVERSION families only (execution-validated strategies)."
        ),
        "assets": {},
        "aggregate": {
            "total_trades": 0,
            "total_pnl": 0.0,
            "total_bars": 0,
        },
        "family_stats_combined": {
            "STRUCTURAL_FRACTAL": {"pnl": 0.0, "trades": 0, "wins": 0},
            "MEAN_REVERSION": {"pnl": 0.0, "trades": 0, "wins": 0},
        },
    }

    for asset_name, result in results.items():
        s = result.summary
        summary["assets"][asset_name] = {
            "total_bars": s["total_bars"],
            "total_trades": s["total_trades"],
            "win_rate": s["win_rate"],
            "total_pnl": s["total_pnl"],
            "avg_r_per_trade": s["avg_r_per_trade"],
            "max_drawdown_pct": s["max_drawdown_pct"],
            "profit_factor": s["profit_factor"],
            "trades_gated": s["trades_gated"],
            "family_stats": s.get("family_stats", {}),
            "regime_pnl": s.get("regime_pnl", {}),
            "regime_trades": s.get("regime_trades", {}),
        }

        summary["aggregate"]["total_trades"] += s["total_trades"]
        summary["aggregate"]["total_pnl"] += s["total_pnl"]
        summary["aggregate"]["total_bars"] += s["total_bars"]

        # Combine family stats
        for fam in ["STRUCTURAL_FRACTAL", "MEAN_REVERSION"]:
            fs = s.get("family_stats", {}).get(fam, {})
            summary["family_stats_combined"][fam]["pnl"] += fs.get("pnl", 0.0)
            summary["family_stats_combined"][fam]["trades"] += fs.get("trades", 0)
            summary["family_stats_combined"][fam]["wins"] += fs.get("wins", 0)

    # Compute combined win rates
    for fam in ["STRUCTURAL_FRACTAL", "MEAN_REVERSION"]:
        fs = summary["family_stats_combined"][fam]
        if fs["trades"] > 0:
            fs["win_rate"] = round(fs["wins"] / fs["trades"], 4)
        else:
            fs["win_rate"] = 0.0

    output_path = REPORTS_DIR / "summary.json"
    with open(output_path, "w") as f:
        json.dump(summary, f, indent=2)
    logger.info("Aggregate summary saved: %s", output_path)


def main() -> None:
    """Run all portfolio backtests and save results."""
    logger.info("=" * 60)
    logger.info("Phase 21: Portfolio Backtest")
    logger.info("Profile: %s (1H HTF — matches native data)", PROFILE)
    logger.info("Assets: %s", ", ".join(ASSETS.keys()))
    logger.info("=" * 60)

    results = run_all()

    if results:
        save_aggregate_summary(results)
        logger.info("Done. %d assets processed.", len(results))
    else:
        logger.error("No assets processed. Check data files.")


if __name__ == "__main__":
    main()
