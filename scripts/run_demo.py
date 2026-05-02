"""Demo script: runs the Hermes trading engine on sample data."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.market.data_loader import load_csv
from src.market.feed import MarketFeed
from src.market.regime import RegimeDetector
from src.strategies.sma_crossover import SMACrossoverStrategy
from src.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from src.hermes.policy import Policy
from src.hermes.metrics import MetricsTracker
from src.hermes.agent import HermesAgent
from src.risk.layer import RiskLayer
from src.execution.mock_broker import MockBroker
from src.engine.runner import TradingEngine
from src.core.events import EventBus


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger = logging.getLogger("run_demo")

    # 1. Load data
    data_path = Path("data/sample/btcusd_1h.csv")
    logger.info("Loading data from %s", data_path)
    bars = load_csv(data_path)
    logger.info("Loaded %d bars", len(bars))

    # 2. Create feed
    feed = MarketFeed(bars)

    # 3. Create strategies
    strategies = [
        SMACrossoverStrategy(fast_period=10, slow_period=30),
        RSIMeanReversionStrategy(rsi_period=14, oversold=30, overbought=70),
    ]
    for s in strategies:
        logger.info("Strategy: %s (style=%s, max_alloc=%.0f%%)",
                     s.metadata.strategy_id, s.metadata.style,
                     s.metadata.max_allocation_pct * 100)

    # 4. Create Hermes
    metrics = MetricsTracker()
    for s in strategies:
        metrics.register_strategy(s.metadata.strategy_id)
    policy = Policy()  # loads from config/hermes_policy.yaml
    hermes = HermesAgent(policy, metrics)

    # 5. Create risk layer
    risk_layer = RiskLayer()

    # 6. Create broker
    broker = MockBroker(
        initial_capital=100_000.0,
        slippage_bps=5.0,
        commission_bps=1.0,
    )

    # 7. Create regime detector
    regime_detector = RegimeDetector(lookback=20)

    # 8. Create event bus (for logging)
    bus = EventBus()
    bus.subscribe("fill", lambda f: logger.info(
        "FILL: %s %s %.6f @ %.2f (strategy=%s)",
        f.side.value, f.symbol, f.quantity, f.fill_price, f.strategy_id
    ))
    bus.subscribe("order_vetoed", lambda o, r: logger.info(
        "VETOED: %s — %s", o.order_id, r
    ))

    # 9. Create engine
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

    # 10. Run
    logger.info("=" * 60)
    logger.info("STARTING TRADING ENGINE")
    logger.info("=" * 60)

    report = engine.run()

    # 11. Print results
    logger.info("=" * 60)
    logger.info("ENGINE REPORT")
    logger.info("=" * 60)
    logger.info("Bars processed: %d", report.bars_processed)
    logger.info("Total signals:  %d", report.total_signals)
    logger.info("Total orders:   %d", report.total_orders)
    logger.info("Total fills:    %d", report.total_fills)
    logger.info("Total vetoes:   %d", report.total_vetoes)

    if report.final_portfolio:
        p = report.final_portfolio
        logger.info("-" * 40)
        logger.info("Final Portfolio:")
        logger.info("  Cash:        $%.2f", p.cash)
        logger.info("  Total Value: $%.2f", p.total_value)
        logger.info("  Total PnL:   $%.2f", p.total_pnl)
        logger.info("  Drawdown:    %.2f%%", p.drawdown * 100)
        logger.info("  Leverage:    %.2fx", p.leverage)
        logger.info("  Exposure:    %.2f%%", p.exposure_pct * 100)

    if report.trade_history:
        logger.info("-" * 40)
        logger.info("Trade History (%d trades):", len(report.trade_history))
        for t in report.trade_history:
            logger.info("  %s %s %.6f: entry=%.2f exit=%.2f pnl=$%.2f",
                         t.side.value, t.symbol, t.quantity,
                         t.entry_price, t.exit_price, t.pnl)

    # Print strategy metrics
    logger.info("-" * 40)
    logger.info("Strategy Metrics:")
    for sid, m in metrics.get_all_metrics().items():
        logger.info("  %s:", sid)
        logger.info("    Trades: %d (W:%d L:%d)", m.total_trades, m.winning_trades, m.losing_trades)
        logger.info("    PnL:    $%.2f", m.total_pnl)
        logger.info("    Win Rate: %.1f%%", m.win_rate * 100)
        logger.info("    Max DD:  %.2f%%", m.max_drawdown * 100)
        logger.info("    Sharpe:  %.2f", m.sharpe_ratio)

    logger.info("=" * 60)
    logger.info("DONE")


if __name__ == "__main__":
    main()