"""Hermes stress-test suite: runs the engine under adverse conditions.

Each scenario exercises a specific failure mode and produces an audit report.
Run: python scripts/stress_test.py
Output: reports/stress_test_{scenario}.json + console summary
"""

from __future__ import annotations

import json
import logging
import math
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.types import Bar, Direction, Regime
from src.market.data_loader import load_csv
from src.market.feed import MarketFeed
from src.market.regime import RegimeDetector
from src.strategies.sma_crossover import SMACrossoverStrategy
from src.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from src.hermes.policy import Policy
from src.hermes.metrics import MetricsTracker
from src.hermes.agent import HermesAgent
from src.risk.layer import RiskLayer, RiskLimits
from src.execution.mock_broker import MockBroker
from src.engine.runner import TradingEngine
from src.core.events import EventBus

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("stress_test")
logger.setLevel(logging.INFO)

REPORTS_DIR = Path("reports")


@dataclass
class ScenarioResult:
    scenario: str
    description: str
    bars_processed: int = 0
    total_signals: int = 0
    total_orders: int = 0
    total_fills: int = 0
    total_vetoes: int = 0
    kill_switch_triggered: bool = False
    final_portfolio_value: float = 0.0
    final_pnl: float = 0.0
    final_drawdown: float = 0.0
    max_allocation_violation: bool = False
    audit_trail_complete: bool = True
    allocation_log: list[dict] = field(default_factory=list)
    assertions_passed: list[str] = field(default_factory=list)
    assertions_failed: list[str] = field(default_factory=list)


def _build_bars(
    base_price: float,
    count: int,
    *,
    trend_slope: float = 0.0,
    volatility: float = 0.005,
    crash_start: int | None = None,
    crash_pct: float = 0.0,
    crash_bars: int = 1,
) -> list[Bar]:
    """Generate synthetic bars with optional crash injection."""
    bars = []
    price = base_price
    start = datetime(2025, 1, 1)
    for i in range(count):
        ts = start + timedelta(hours=i)

        if crash_start and crash_start <= i < crash_start + crash_bars:
            # Inject crash
            price *= (1 - crash_pct / crash_bars)
        else:
            # Normal movement
            change = trend_slope + volatility * (hash(str(i)) % 200 - 100) / 100
            price *= (1 + change)

        price = max(price, 1.0)

        high = price * (1 + abs(volatility) * 0.5)
        low = price * (1 - abs(volatility) * 0.5)
        low = max(low, 1.0)

        bars.append(Bar(
            timestamp=ts,
            open=price * 0.999,
            high=high,
            low=low,
            close=price,
            volume=1000.0,
        ))
    return bars


def _run_scenario(
    name: str,
    description: str,
    bars: list[Bar],
    strategies: list,
    risk_limits: RiskLimits | None = None,
    slippage_bps: float = 5.0,
    commission_bps: float = 1.0,
    initial_capital: float = 100_000.0,
) -> ScenarioResult:
    """Run a single stress-test scenario and return the result."""
    feed = MarketFeed(bars)
    metrics = MetricsTracker()
    for s in strategies:
        metrics.register_strategy(s.metadata.strategy_id)

    policy = Policy()
    hermes = HermesAgent(policy, metrics)
    risk_layer = RiskLayer(risk_limits)
    broker = MockBroker(
        initial_capital=initial_capital,
        slippage_bps=slippage_bps,
        commission_bps=commission_bps,
    )
    regime_detector = RegimeDetector(lookback=20)
    bus = EventBus()

    # Track vetoes and kills
    vetoes: list[str] = []
    kills: list[str] = []

    bus.subscribe("order_vetoed", lambda o, r: vetoes.append(r))
    bus.subscribe("fill", lambda f: None)

    engine = TradingEngine(
        feed=feed,
        strategies=strategies,
        hermes=hermes,
        risk_layer=risk_layer,
        broker=broker,
        regime_detector=regime_detector,
        event_bus=bus,
        quantity_per_signal=0.001,
    )

    report = engine.run()

    # Build result
    result = ScenarioResult(
        scenario=name,
        description=description,
        bars_processed=report.bars_processed,
        total_signals=report.total_signals,
        total_orders=report.total_orders,
        total_fills=report.total_fills,
        total_vetoes=report.total_vetoes,
        kill_switch_triggered=risk_layer.is_kill_active,
        final_portfolio_value=report.final_portfolio.total_value if report.final_portfolio else 0.0,
        final_pnl=report.final_portfolio.total_pnl if report.final_portfolio else 0.0,
        final_drawdown=report.final_portfolio.drawdown if report.final_portfolio else 0.0,
        allocation_log=report.allocation_log,
    )

    # --- Assertions ---
    assertions_passed = []
    assertions_failed = []

    # Assertion: audit trail complete (every allocation has a reason)
    audit_complete = True
    for entry in report.allocation_log:
        for sid, alloc in entry.get("allocations", {}).items():
            if not alloc.get("reason"):
                audit_complete = False
                break
    result.audit_trail_complete = audit_complete

    if audit_complete:
        assertions_passed.append("audit_trail_complete")
    else:
        assertions_failed.append("audit_trail_complete")

    # Assertion: no strategy exceeded its max_allocation_pct
    max_violation = False
    for entry in report.allocation_log:
        for sid, alloc in entry.get("allocations", {}).items():
            weight = alloc.get("weight", 0.0)
            # Find the strategy to get its max
            for s in strategies:
                if s.metadata.strategy_id == sid:
                    if weight > s.metadata.max_allocation_pct + 0.001:
                        max_violation = True
                        break
    result.max_allocation_violation = max_violation

    if not max_violation:
        assertions_passed.append("allocation_within_limits")
    else:
        assertions_failed.append("allocation_within_limits")

    result.assertions_passed = assertions_passed
    result.assertions_failed = assertions_failed

    return result


def scenario_baseline(data_path: Path) -> ScenarioResult:
    """Scenario 1: Normal operation with both strategies (baseline)."""
    bars = load_csv(data_path)
    strategies = [
        SMACrossoverStrategy(fast_period=10, slow_period=30),
        RSIMeanReversionStrategy(rsi_period=14, oversold=30, overbought=70),
    ]
    return _run_scenario(
        name="baseline",
        description="Normal operation with SMA + RSI strategies on sample data",
        bars=bars,
        strategies=strategies,
    )


def scenario_single_strategy(data_path: Path) -> ScenarioResult:
    """Scenario 2: Only SMA strategy enabled."""
    bars = load_csv(data_path)
    strategies = [
        SMACrossoverStrategy(fast_period=10, slow_period=30),
    ]
    return _run_scenario(
        name="single_strategy",
        description="Only SMA crossover strategy — tests allocation stability with one strategy",
        bars=bars,
        strategies=strategies,
    )


def scenario_conflicting_strategies(data_path: Path) -> ScenarioResult:
    """Scenario 3: Two trend-style strategies that may produce opposing signals."""
    bars = load_csv(data_path)
    # Both are trend-style but with very different parameters — may conflict
    strategies = [
        SMACrossoverStrategy(fast_period=5, slow_period=15),  # aggressive fast
        SMACrossoverStrategy(fast_period=30, slow_period=100),  # slow, counter-signal
    ]
    return _run_scenario(
        name="conflicting_strategies",
        description="Two SMA strategies with conflicting periods — tests Hermes handling opposing signals",
        bars=bars,
        strategies=strategies,
    )


def scenario_extreme_slippage(data_path: Path) -> ScenarioResult:
    """Scenario 4: High slippage degrades execution."""
    bars = load_csv(data_path)
    strategies = [
        SMACrossoverStrategy(fast_period=10, slow_period=30),
        RSIMeanReversionStrategy(rsi_period=14, oversold=30, overbought=70),
    ]
    return _run_scenario(
        name="extreme_slippage",
        description="50 bps slippage (10x normal) — tests execution layer degradation",
        bars=bars,
        strategies=strategies,
        slippage_bps=50.0,
    )


def scenario_prolonged_drawdown(data_path: Path) -> ScenarioResult:
    """Scenario 5: Inject price crash to trigger kill switch."""
    bars = load_csv(data_path)
    # Inject a 30% crash starting at bar 50
    bars = _build_bars(
        base_price=bars[0].close,
        count=len(bars),
        volatility=0.002,
        crash_start=50,
        crash_pct=0.30,
        crash_bars=5,
    )
    strategies = [
        SMACrossoverStrategy(fast_period=10, slow_period=30),
        RSIMeanReversionStrategy(rsi_period=14, oversold=30, overbought=70),
    ]
    result = _run_scenario(
        name="prolonged_drawdown",
        description="30% price crash at bar 50 — tests kill switch + cooldown + recovery",
        bars=bars,
        strategies=strategies,
    )
    # Extra assertion: kill switch should have triggered
    if result.total_vetoes > 0:
        result.assertions_passed.append("vetoes_occurred_during_crash")
    else:
        result.assertions_failed.append("vetoes_occurred_during_crash")

    return result


def scenario_rapid_regime_shifts(data_path: Path) -> ScenarioResult:
    """Scenario 6: Price data with rapid regime changes."""
    bars = load_csv(data_path)
    # Create oscillating price to force rapid regime changes
    oscillated = []
    for i, bar in enumerate(bars):
        # Alternate between trending up and trending down every 15 bars
        cycle = (i // 15) % 2
        factor = 1.015 if cycle == 0 else 0.985
        new_bar = Bar(
            timestamp=bar.timestamp,
            open=bar.open * factor,
            high=bar.high * factor,
            low=bar.low * factor,
            close=bar.close * factor,
            volume=bar.volume,
        )
        oscillated.append(new_bar)

    strategies = [
        SMACrossoverStrategy(fast_period=10, slow_period=30),
        RSIMeanReversionStrategy(rsi_period=14, oversold=30, overbought=70),
    ]
    return _run_scenario(
        name="rapid_regime_shifts",
        description="Oscillating price forcing frequent regime changes — tests Hermes adaptability",
        bars=oscillated,
        strategies=strategies,
    )


def scenario_over_allocation(data_path: Path) -> ScenarioResult:
    """Scenario 7: Risk layer must veto excess exposure."""
    bars = load_csv(data_path)
    # Both strategies with very aggressive parameters
    strategies = [
        SMACrossoverStrategy(fast_period=5, slow_period=15),
        RSIMeanReversionStrategy(rsi_period=7, oversold=25, overbought=75),
    ]
    # Use tight risk limits to force vetoes
    tight_limits = RiskLimits(
        max_leverage=0.5,
        max_drawdown_pct=0.10,
        max_allocation_per_strategy_pct=0.30,
        max_total_exposure_pct=0.60,
        kill_switch_drawdown_pct=0.15,
        cooldown_bars_after_kill=50,
    )
    result = _run_scenario(
        name="over_allocation",
        description="Tight risk limits + aggressive strategies — tests risk layer veto enforcement",
        bars=bars,
        strategies=strategies,
        risk_limits=tight_limits,
    )

    # Assertion: vetoes should have occurred
    if result.total_vetoes > 0:
        result.assertions_passed.append("vetoes_enforced")
    else:
        result.assertions_failed.append("vetoes_enforced")

    return result


def run_all_scenarios() -> list[ScenarioResult]:
    """Run all stress-test scenarios and return results."""
    data_path = Path("data/sample/btcusd_1h.csv")
    if not data_path.exists():
        logger.error("Sample data not found at %s", data_path)
        sys.exit(1)

    scenarios = [
        lambda: scenario_baseline(data_path),
        lambda: scenario_single_strategy(data_path),
        lambda: scenario_conflicting_strategies(data_path),
        lambda: scenario_extreme_slippage(data_path),
        lambda: scenario_prolonged_drawdown(data_path),
        lambda: scenario_rapid_regime_shifts(data_path),
        lambda: scenario_over_allocation(data_path),
    ]

    results = []
    for i, scenario_fn in enumerate(scenarios, 1):
        result = scenario_fn()
        results.append(result)
        logger.info("[%d/7] %s — %d assertions passed, %d failed",
                    i, result.scenario,
                    len(result.assertions_passed),
                    len(result.assertions_failed))

    return results


def save_reports(results: list[ScenarioResult]) -> None:
    """Save individual JSON reports and a summary."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    for r in results:
        report_path = REPORTS_DIR / f"stress_test_{r.scenario}.json"
        with open(report_path, "w") as f:
            json.dump(asdict(r), f, indent=2, default=str)
        logger.info("Saved report: %s", report_path)

    # Summary
    summary = {
        "timestamp": datetime.now().isoformat(),
        "total_scenarios": len(results),
        "all_passed": all(not r.assertions_failed for r in results),
        "scenarios": [
            {
                "name": r.scenario,
                "description": r.description,
                "bars": r.bars_processed,
                "signals": r.total_signals,
                "orders": r.total_orders,
                "fills": r.total_fills,
                "vetoes": r.total_vetoes,
                "kill_triggered": r.kill_switch_triggered,
                "final_pnl": r.final_pnl,
                "final_drawdown": r.final_drawdown,
                "assertions_passed": r.assertions_passed,
                "assertions_failed": r.assertions_failed,
            }
            for r in results
        ],
    }

    summary_path = REPORTS_DIR / "stress_test_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    logger.info("Saved summary: %s", summary_path)


def print_summary(results: list[ScenarioResult]) -> None:
    """Print a formatted summary table to console."""
    print("\n" + "=" * 90)
    print("HERMES STRESS TEST RESULTS")
    print("=" * 90)

    for r in results:
        status = "PASS" if not r.assertions_failed else "FAIL"
        print(f"\n[{status}] {r.scenario}")
        print(f"  {r.description}")
        print(f"  Bars: {r.bars_processed} | Signals: {r.total_signals} | "
              f"Fills: {r.total_fills} | Vetoes: {r.total_vetoes}")
        print(f"  Final PnL: ${r.final_pnl:,.2f} | Drawdown: {r.final_drawdown:.2%}")
        print(f"  Kill switch: {'YES' if r.kill_switch_triggered else 'no'}")
        print(f"  Audit trail: {'complete' if r.audit_trail_complete else 'INCOMPLETE'}")
        if r.assertions_passed:
            print(f"  Passed: {', '.join(r.assertions_passed)}")
        if r.assertions_failed:
            print(f"  FAILED: {', '.join(r.assertions_failed)}")

    all_passed = all(not r.assertions_failed for r in results)
    print("\n" + "=" * 90)
    print(f"OVERALL: {'ALL SCENARIOS PASSED' if all_passed else 'SOME SCENARIOS FAILED'}")
    print("=" * 90 + "\n")


if __name__ == "__main__":
    results = run_all_scenarios()
    save_reports(results)
    print_summary(results)

    # Exit with error if any scenario failed
    if any(r.assertions_failed for r in results):
        sys.exit(1)