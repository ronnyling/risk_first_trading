"""Phase 15: FTMO Dry-Run Simulation — backtest with FTMO evaluation rules.

Runs a backtest that simulates FTMO evaluation mechanics on historical data
for all 3 assets (SPY, BTC, TSLA). Validates that the ftmo_safe profile
respects FTMO limits across diverse market conditions.

Usage:
    python scripts/run_ftmo_dryrun.py                          # All assets
    python scripts/run_ftmo_dryrun.py --asset SPY              # SPY only
    python scripts/run_ftmo_dryrun.py --asset BTC              # BTC only
    python scripts/run_ftmo_dryrun.py --asset TSLA             # TSLA only
    python scripts/run_ftmo_dryrun.py --equity 100000          # Custom starting equity
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from src.core.types import Bar, Regime
from src.hermes.agents.base import MarketState
from src.hermes.agents.stub_agents import (
    IchimokuAgent,
    VolatilityAgent,
    AMTAgent,
    WyckoffAgent,
)
from src.hermes.coordinator import (
    AccountState,
    HermesCoordinator,
    PreviousState,
)
from src.hermes.registry import AgentRegistry
from src.hermes.scoring import ScoringEngine
from src.hermes.conflict import ConflictResolver
from src.hermes.sizing import PositionSizer
from src.risk.drawdown_ladder import DrawdownLadder
from src.risk.ftmo_guard import FTMOConfig, FTMOGuard
from src.profiles.presets import RISK_PROFILES
from src.profiles.resolver import ProfileResolver
from src.execution.mock_broker import MockBroker
from src.market.data_loader import load_csv

logger = logging.getLogger("ftmo_dryrun")

# --- Asset configuration ---
ASSETS = {
    "SPY": "data/historical/spy_1h_12m.csv",
    "BTC": "data/historical/btc-usd_1h_12m.csv",
    "TSLA": "data/historical/tsla_1h_12m.csv",
}

REPORTS_DIR = Path("reports/ftmo_dryrun")
MIN_BARS = 52


def make_coordinator(risk_profile: str = "ftmo_safe") -> tuple[HermesCoordinator, DrawdownLadder, FTMOGuard, dict]:
    """Build Hermes v2 coordinator with profile-derived parameters."""
    profile_data = RISK_PROFILES[risk_profile]
    resolver = ProfileResolver.from_risk_profile(risk_profile)

    registry = AgentRegistry()
    registry.register(IchimokuAgent())
    registry.register(VolatilityAgent())
    registry.register(AMTAgent())
    registry.register(WyckoffAgent())

    sizing = PositionSizer(
        ladder=DrawdownLadder.from_profile(profile_data.get("drawdown_ladder", {})),
        ftmo_config=FTMOConfig(**profile_data.get("ftmo", {})),
    )

    coordinator = HermesCoordinator(
        registry=registry,
        scoring=ScoringEngine(),
        conflict=ConflictResolver(),
        sizing=sizing,
    )

    return coordinator, sizing.ladder, sizing.ftmo_guard or FTMOGuard(), {
        "base_risk": resolver.base_risk,
        "max_portfolio_risk": resolver.max_portfolio_risk,
    }


def run_dryrun_single(
    csv_path: str,
    symbol: str,
    initial_equity: float,
    risk_profile: str = "ftmo_safe",
) -> dict:
    """Run FTMO dry-run simulation for a single asset.

    Returns detailed results dict.
    """
    bars = load_csv(csv_path)
    if not bars:
        return {"error": f"No data loaded from {csv_path}"}

    logger.info("Running FTMO dry-run: %s (%d bars, equity=$%.0f)", symbol, len(bars), initial_equity)

    # Build coordinator
    coordinator, ladder, ftmo_guard, risk_params = make_coordinator(risk_profile)

    # Build broker (for fill simulation)
    broker = MockBroker(
        initial_capital=initial_equity,
        slippage_bps=5.0,
        commission_bps=1.0,
    )

    # Tracking
    equity_curve: list[dict] = []
    daily_pnl: list[dict] = []
    violations: list[dict] = []
    dd_stages: list[dict] = []
    trades: list[dict] = []
    previous: PreviousState | None = None

    current_date = None
    daily_start_equity = initial_equity
    peak_equity = initial_equity
    bars_processed = 0
    total_fills = 0
    total_vetoes = 0

    for i, bar in enumerate(bars):
        if i < MIN_BARS:
            continue

        window = bars[max(0, i - MIN_BARS): i + 1]

        # Date boundary detection
        bar_date = bar.timestamp[:10] if isinstance(bar.timestamp, str) else str(bar.timestamp)[:10]
        if bar_date != current_date:
            if current_date is not None:
                # Record daily PnL
                daily_pnl.append({
                    "date": current_date,
                    "start_equity": daily_start_equity,
                    "end_equity": broker.get_portfolio_state().total_value,
                    "pnl": broker.get_portfolio_state().total_value - daily_start_equity,
                })
            current_date = bar_date
            daily_start_equity = broker.get_portfolio_state().total_value
            ftmo_guard.update_daily(
                equity=daily_start_equity,
                bar_timestamp=bar.timestamp,
            )

        # Update market price
        broker.update_market_price(symbol, bar.close)

        # Build MarketState
        ms = MarketState(
            bars=window,
            regime=Regime.RANGING,
            regime_confidence=0.5,
            volatility=None,
            timestamp=bar.timestamp,
        )

        # Account state
        portfolio = broker.get_portfolio_state()
        equity = portfolio.total_value
        drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0

        acc = AccountState(
            equity=equity,
            peak_equity=peak_equity,
            current_drawdown=drawdown,
            max_risk_per_trade=risk_params["base_risk"],
            max_portfolio_risk=risk_params["max_portfolio_risk"],
        )

        # Hermes v2 cycle
        decision = coordinator.run_cycle(ms, acc, previous)

        # Drawdown ladder
        dd_state = ladder.evaluate(
            current_drawdown=drawdown,
            confidence=decision.confidence,
        )
        dd_stages.append({
            "bar": bars_processed,
            "stage": dd_state.stage,
            "multiplier": dd_state.size_multiplier,
        })

        # FTMO guard check
        ftmo_check = ftmo_guard.check(equity=equity, peak_equity=peak_equity)

        if not ftmo_check.compliant:
            for v in ftmo_check.violations:
                violations.append({
                    "bar": bars_processed,
                    "date": bar_date,
                    "violation": v,
                    "action": ftmo_check.action,
                })
                logger.warning("FTMO violation: %s (action=%s)", v, ftmo_check.action)

        # Simulate execution based on directive
        if ftmo_check.action == "HALT":
            # FTMO halt: close all positions
            positions = broker.get_positions()
            if symbol in positions:
                from src.core.types import Order, OrderSide
                order = Order(
                    order_id=f"ftmo-halt-{bars_processed}",
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=positions[symbol].quantity,
                    timestamp=bar.timestamp,
                    strategy_id="ftmo_dryrun",
                )
                fill = broker.submit_order(order)
                if fill:
                    total_fills += 1
        elif decision.risk_directive == "CASH":
            # CASH: close all positions
            positions = broker.get_positions()
            if symbol in positions:
                from src.core.types import Order, OrderSide
                order = Order(
                    order_id=f"cash-close-{bars_processed}",
                    symbol=symbol,
                    side=OrderSide.SELL,
                    quantity=positions[symbol].quantity,
                    timestamp=bar.timestamp,
                    strategy_id="ftmo_dryrun",
                )
                fill = broker.submit_order(order)
                if fill:
                    total_fills += 1
        elif decision.risk_directive in ("FULL", "SCALE_DOWN"):
            # Compute position size based on risk
            risk_pct = decision.per_trade_risk
            if decision.risk_directive == "SCALE_DOWN":
                risk_pct *= 0.5  # Scale down

            # Apply FTMO REDUCE if needed
            if ftmo_check.action == "REDUCE":
                risk_pct *= 0.5

            risk_amount = equity * risk_pct
            qty = risk_amount / bar.close if bar.close > 0 else 0

            if qty > 0 and decision.composite_score > 0:
                from src.core.types import Order, OrderSide
                # Check if we already have a position
                positions = broker.get_positions()
                if symbol not in positions or positions[symbol].quantity <= 0:
                    order = Order(
                        order_id=f"entry-{bars_processed}",
                        symbol=symbol,
                        side=OrderSide.BUY,
                        quantity=qty,
                        timestamp=bar.timestamp,
                        strategy_id="ftmo_dryrun",
                    )
                    fill = broker.submit_order(order)
                    if fill:
                        total_fills += 1
                        trades.append({
                            "bar": bars_processed,
                            "date": bar_date,
                            "side": "BUY",
                            "qty": qty,
                            "price": fill.fill_price,
                        })
            elif qty > 0 and decision.composite_score < 0:
                # Bearish: close if we have a position
                positions = broker.get_positions()
                if symbol in positions and positions[symbol].quantity > 0:
                    from src.core.types import Order, OrderSide
                    order = Order(
                        order_id=f"exit-{bars_processed}",
                        symbol=symbol,
                        side=OrderSide.SELL,
                        quantity=positions[symbol].quantity,
                        timestamp=bar.timestamp,
                        strategy_id="ftmo_dryrun",
                    )
                    fill = broker.submit_order(order)
                    if fill:
                        total_fills += 1
                        trades.append({
                            "bar": bars_processed,
                            "date": bar_date,
                            "side": "SELL",
                            "qty": positions[symbol].quantity,
                            "price": fill.fill_price,
                        })

        # Update peak equity
        portfolio = broker.get_portfolio_state()
        equity = portfolio.total_value
        if equity > peak_equity:
            peak_equity = equity

        # Record equity curve point (every 10 bars)
        if bars_processed % 10 == 0:
            equity_curve.append({
                "bar": bars_processed,
                "date": bar_date,
                "equity": round(equity, 2),
                "drawdown": round(drawdown, 4),
                "stage": dd_state.stage,
            })

        # Previous state
        previous = PreviousState(
            composite_score=decision.composite_score,
            regime=decision.regime,
            risk_directive=decision.risk_directive,
            allowed_strategy_family=decision.allowed_strategy_family,
        )

        bars_processed += 1

    # Final daily PnL
    if current_date:
        portfolio = broker.get_portfolio_state()
        daily_pnl.append({
            "date": current_date,
            "start_equity": daily_start_equity,
            "end_equity": portfolio.total_value,
            "pnl": portfolio.total_value - daily_start_equity,
        })

    # --- Results ---
    portfolio = broker.get_portfolio_state()
    final_equity = portfolio.total_value
    total_return = (final_equity - initial_equity) / initial_equity
    max_drawdown = (peak_equity - final_equity) / peak_equity if peak_equity > 0 else 0.0
    profit_target = initial_equity * 1.10
    passed = final_equity >= profit_target and len(violations) == 0

    # DD stage summary
    stage_counts = {}
    for ds in dd_stages:
        stage = ds["stage"]
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

    # Daily loss violations
    daily_loss_violations = [v for v in violations if "Daily loss" in v.get("violation", "")]

    result = {
        "symbol": symbol,
        "csv_path": csv_path,
        "initial_equity": initial_equity,
        "final_equity": round(final_equity, 2),
        "total_return_pct": round(total_return * 100, 2),
        "peak_equity": round(peak_equity, 2),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "profit_target": round(profit_target, 2),
        "passed": passed,
        "bars_processed": bars_processed,
        "total_fills": total_fills,
        "total_trades": len(trades),
        "violations": violations,
        "violation_count": len(violations),
        "daily_loss_violations": len(daily_loss_violations),
        "dd_stages": stage_counts,
        "equity_curve": equity_curve,
        "daily_pnl": daily_pnl,
        "trades": trades[:50],  # Limit to first 50 for report size
    }

    return result


def save_results(results: dict[str, dict], output_dir: Path) -> Path:
    """Save all results to a JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "evaluation_summary.json"

    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    return output_path


def generate_comparison_table(results: dict[str, dict]) -> str:
    """Generate a markdown comparison table from results."""
    lines = [
        "# FTMO Dry-Run Evaluation Results",
        "",
        f"**Profile:** ftmo_safe | **Generated:** {datetime.now().isoformat()[:19]}",
        "",
        "| Asset | Trades | Return | Max DD | Violations | Verdict |",
        "|-------|--------|--------|--------|------------|---------|",
    ]

    for key, result in sorted(results.items()):
        if "error" in result:
            lines.append(f"| {key} | - | ERROR | {result['error']} | - | - |")
            continue

        verdict = "PASS" if result["passed"] else "FAIL"
        lines.append(
            f"| {result['symbol']} "
            f"| {result['total_trades']} "
            f"| {result['total_return_pct']:+.2f}% "
            f"| {result['max_drawdown_pct']:.2f}% "
            f"| {result['violation_count']} "
            f"| **{verdict}** |"
        )

    lines.append("")
    lines.append("## FTMO Limits (ftmo_safe profile)")
    lines.append("")
    lines.append("| Limit | Value | Buffer |")
    lines.append("|-------|-------|--------|")
    lines.append("| Daily Loss | 4.5% | 0.5% below FTMO 5% |")
    lines.append("| Max Drawdown | 9.0% | 1.0% below FTMO 10% |")
    lines.append("| Profit Target | 10% | Standard FTMO |")
    lines.append("| Consistency | 5% max per trade | Standard FTMO |")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 15: FTMO Dry-Run Simulation")
    parser.add_argument(
        "--asset",
        choices=list(ASSETS.keys()),
        default=None,
        help="Run specific asset only (default: all)",
    )
    parser.add_argument(
        "--equity",
        type=float,
        default=100_000.0,
        help="Starting equity (default: 100000)",
    )
    parser.add_argument(
        "--profile",
        default="ftmo_safe",
        choices=list(RISK_PROFILES.keys()),
        help="Risk profile (default: ftmo_safe)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    assets = {args.asset: ASSETS[args.asset]} if args.asset else ASSETS

    print("=" * 60)
    print("Phase 15: FTMO Dry-Run Simulation")
    print("=" * 60)
    print(f"Assets: {list(assets.keys())}")
    print(f"Equity: ${args.equity:,.0f}")
    print(f"Profile: {args.profile}")
    print()

    results = {}

    for asset_name, data_path in assets.items():
        data_file = Path(data_path)
        if not data_file.is_absolute():
            data_file = Path(_root) / data_file

        if not data_file.exists():
            print(f"  {asset_name}: SKIPPED — data file not found: {data_file}")
            results[asset_name] = {"error": f"Data file not found: {data_file}"}
            continue

        result = run_dryrun_single(
            csv_path=str(data_file),
            symbol=asset_name,
            initial_equity=args.equity,
            risk_profile=args.profile,
        )
        results[asset_name] = result

        if "error" in result:
            print(f"  {asset_name}: ERROR — {result['error']}")
        else:
            verdict = "PASS" if result["passed"] else "FAIL"
            print(
                f"  {asset_name}: trades={result['total_trades']}, "
                f"return={result['total_return_pct']:+.2f}%, "
                f"max_dd={result['max_drawdown_pct']:.2f}%, "
                f"violations={result['violation_count']}, "
                f"verdict={verdict}"
            )

    # Save results
    output_path = save_results(results, REPORTS_DIR)
    print(f"\nResults saved to: {output_path}")

    # Generate comparison table
    table = generate_comparison_table(results)
    table_path = REPORTS_DIR / "evaluation_table.md"
    with open(table_path, "w") as f:
        f.write(table)
    print(f"Comparison table: {table_path}")

    # Save individual asset results
    for asset_name, result in results.items():
        asset_path = REPORTS_DIR / f"{asset_name.lower()}_evaluation.json"
        with open(asset_path, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"  {asset_name} detailed: {asset_path}")

    # Print summary
    print()
    print(table)
    print()

    # Final verdict
    all_passed = all(r.get("passed", False) for r in results.values() if "error" not in r)
    any_passed = any(r.get("passed", False) for r in results.values() if "error" not in r)
    all_errored = all("error" in r for r in results.values())

    if all_errored:
        print("VERDICT: INCONCLUSIVE — all assets errored")
        sys.exit(1)
    elif all_passed:
        print("VERDICT: ALL ASSETS PASSED — ready for Phase 17")
        sys.exit(0)
    elif any_passed:
        print("VERDICT: PARTIAL PASS — at least one asset passed, review details")
        sys.exit(0)
    else:
        print("VERDICT: ALL FAILED — do not proceed to Phase 17")
        sys.exit(1)


if __name__ == "__main__":
    main()
