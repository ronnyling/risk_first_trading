"""Main trading engine — wires all components and runs bar-by-bar replay."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

from src.core.clock import SimClock
from src.core.events import EventBus, HealthEvents
from src.core.types import (
    Bar,
    Direction,
    Fill,
    Order,
    OrderSide,
    PortfolioState,
    Regime,
    Signal,
)
from src.execution.broker import Broker
from src.execution.mock_broker import MockBroker
from src.hermes.agent import HermesAgent, StrategyAllocation
from src.market.adapter import MarketDataAdapter
from src.market.feed import MarketFeed  # backward compat
from src.market.regime import RegimeDetector
from src.monitoring.health_supervisor import HealthSupervisor
from src.risk.layer import RiskLayer
from src.strategies.base import Strategy

logger = logging.getLogger(__name__)


@dataclass
class EngineReport:
    """Summary report after an engine run completes."""
    bars_processed: int = 0
    total_signals: int = 0
    total_orders: int = 0
    total_fills: int = 0
    total_vetoes: int = 0
    final_portfolio: PortfolioState | None = None
    trade_history: list = field(default_factory=list)
    allocation_log: list[dict] = field(default_factory=list)


class TradingEngine:
    """Main loop: wires everything, runs bar-by-bar replay.

    Data flow per bar:
    1. Update market price in broker
    2. Update regime detector
    3. Hermes evaluates allocations
    4. Collect signals from active strategies
    5. Convert signals to orders (weighted by allocation)
    6. Risk layer vetoes
    7. Submit to broker
    8. Notify strategies of fills
    9. Update metrics
    10. Log everything
    """

    def __init__(
        self,
        feed: MarketFeed | MarketDataAdapter,
        strategies: list[Strategy],
        hermes: HermesAgent,
        risk_layer: RiskLayer,
        broker: Broker,
        regime_detector: RegimeDetector,
        event_bus: EventBus | None = None,
        quantity_per_signal: float = 0.001,  # BTC quantity per signal unit
        bar_delay: float = 0.0,  # seconds to sleep between bars (0 = instant)
    ) -> None:
        # DI boundary enforcement: reject incompatible broker types
        if not isinstance(broker, Broker):
            raise TypeError(
                f"TradingEngine requires a Broker ABC implementation, "
                f"got {type(broker).__name__}. Use AlpacaBroker, not AlpacaAdapter."
            )

        # Accept both MarketFeed (legacy) and MarketDataAdapter (new).
        if isinstance(feed, MarketFeed):
            # Wrap legacy MarketFeed in an adapter for uniform interface
            from src.market.csv_adapter import _LegacyFeedAdapter
            self._feed: MarketDataAdapter = _LegacyFeedAdapter(feed)
        else:
            self._feed = feed

        # Guard: reject CSV market data + live broker hybrid configurations.
        # CSV replay is a test/debug tool only. Production execution must use
        # live market data with a live broker, or MockBroker with CSV data.
        is_csv_feed = (
            hasattr(self._feed, 'source_name')
            and isinstance(self._feed.source_name, str)
            and 'csv' in self._feed.source_name.lower()
        )
        if is_csv_feed and not isinstance(broker, MockBroker):
            raise ValueError(
                f"Hybrid configuration rejected: CSV market data cannot be combined "
                f"with a live broker ({type(broker).__name__}). "
                f"Use MockBroker for CSV replay or use a live market data adapter "
                f"with a live broker."
            )

        self._strategies = {s.metadata.strategy_id: s for s in strategies}
        self._hermes = hermes
        self._risk = risk_layer
        self._broker = broker
        self._regime = regime_detector
        self._bus = event_bus or EventBus()
        self._clock = SimClock()
        self._qty_per_signal = quantity_per_signal
        self._bar_delay = bar_delay

        # Initialize Health Supervisor
        # Disable health checks for MockBroker (test environment)
        # Disable market_feed/hermes checks for CSV-based feeds (historical data is always "stale")
        enabled_checks = None
        if hasattr(broker, '__class__') and 'Mock' in broker.__class__.__name__:
            enabled_checks = set()  # Disable all checks for mock broker
        elif hasattr(self._feed, 'source_name') and 'csv' in self._feed.source_name.lower():
            enabled_checks = {"alpaca", "file_system", "policy"}  # Skip market_feed and hermes for CSV
        
        self._health_supervisor = HealthSupervisor(
            event_bus=self._bus,
            broker=self._broker,
            market_feed=self._feed,
            enabled_checks=enabled_checks,
        )

        # Initialize Persistence Writer (event-driven audit trail)
        try:
            from src.persistence.writer import PersistenceWriter
            self._persistence = PersistenceWriter(event_bus=self._bus)
        except Exception as e:
            logger.warning("PersistenceWriter not available: %s", e)
            self._persistence = None

        self._allocation_log: list[dict] = []
        self._last_signals: dict[str, Signal] = {}

    def run(self) -> EngineReport:
        """Execute the main trading loop over all bars in the feed."""
        report = EngineReport()

        logger.info("Engine starting: source=%s, %d strategies",
                     self._feed.source_name, len(self._strategies))

        # Initialize data adapter
        self._feed.start()

        # Start all strategies
        for strat in self._strategies.values():
            strat.start()

        while True:
            # Health check before processing bar
            health_results = self._health_supervisor.check_all()
            critical_failures = [r for r in health_results if not r.healthy and r.component in ["alpaca", "market_feed"]]
            
            if critical_failures:
                logger.warning("Critical health check failures detected, pausing execution")
                # Emit execution paused event if not already emitted
                self._bus.emit(
                    HealthEvents.EXECUTION_PAUSED,
                    datetime.now().isoformat(),
                    "engine",
                    "Critical dependency degraded"
                )
                # Continue loop but skip processing (pause behavior)
                # In a real implementation, we might want to break or sleep
                # For now, we'll log and continue checking
                time.sleep(5)  # Wait before re-checking
                continue

            bar = self._feed.get_next_bar()
            if bar is None:
                break
            self._clock.advance(bar.timestamp)
            report.bars_processed += 1

            # Track bar index for persistence
            if self._persistence is not None:
                self._persistence.advance_bar()

            # 1. Update market price (only for brokers that need it)
            if self._broker.supports_market_price_updates:
                symbol = "BTC/USD"
                self._broker.update_market_price(symbol, bar.close)

            # 2. Get history and update regime
            history = self._feed.get_history(50)
            regime = self._regime.update(history)

            # 3. Tick cooldowns
            self._hermes.tick_cooldowns()
            self._risk.tick_cooldown()

            # 4. Get portfolio state
            portfolio = self._broker.get_portfolio_state()

            # 5. Hermes evaluates allocations
            meta_list = [s.metadata for s in self._strategies.values()]
            allocations = self._hermes.evaluate(
                meta_list, regime, portfolio.drawdown
            )

            # Log allocations
            alloc_entry = {
                "bar": report.bars_processed,
                "timestamp": bar.timestamp.isoformat(),
                "regime": regime.value,
                "portfolio_value": portfolio.total_value,
                "allocations": {
                    sid: {"active": a.active, "weight": a.weight, "reason": a.reason}
                    for sid, a in allocations.items()
                },
            }
            self._allocation_log.append(alloc_entry)

            # 6. Collect signals from active strategies
            for sid, alloc in allocations.items():
                strat = self._strategies.get(sid)
                if strat is None or not alloc.active:
                    continue

                bars_history = self._feed.get_history(50)
                signal = strat.on_bar(bar, bars_history)

                if signal is not None:
                    report.total_signals += 1
                    self._last_signals[sid] = signal

                    # 7. Convert signal to order
                    order = self._signal_to_order(signal, alloc, bar)
                    if order is None:
                        continue

                    report.total_orders += 1

                    # 8. Risk layer vetoes
                    portfolio = self._broker.get_portfolio_state()
                    veto = self._risk.check_order(order, portfolio)

                    if not veto.approved:
                        report.total_vetoes += 1
                        self._bus.emit("order_vetoed", order, veto.reason)
                        logger.debug("Vetoed: %s — %s", order.order_id, veto.reason)
                        continue

                    # 9. Submit to broker
                    fill = self._broker.submit_order(order)
                    if fill is not None:
                        report.total_fills += 1
                        strat.on_fill(fill)
                        self._hermes.metrics.record_fill(fill)
                        self._bus.emit("fill", fill)
                    else:
                        self._bus.emit("order_rejected", order)

            # Increment bars since trade for all strategies
            for sid in self._strategies:
                if sid not in self._last_signals:
                    self._hermes.metrics.increment_bars_since_trade(sid)

            # 10. Delay between bars (if configured)
            if self._bar_delay > 0:
                time.sleep(self._bar_delay)

        # End of run
        self._feed.stop()

        for strat in self._strategies.values():
            strat.stop()

        report.final_portfolio = self._broker.get_portfolio_state()
        report.trade_history = self._broker.get_trade_history()
        report.allocation_log = self._allocation_log

        logger.info(
            "Engine finished: %d bars, %d signals, %d orders, %d fills, %d vetoes",
            report.bars_processed,
            report.total_signals,
            report.total_orders,
            report.total_fills,
            report.total_vetoes,
        )

        return report

    def _signal_to_order(
        self, signal: Signal, allocation: StrategyAllocation, bar: Bar
    ) -> Order | None:
        """Convert a strategy signal to an order, sized by Hermes allocation."""
        if signal.direction == Direction.FLAT:
            # Signal to close — create a sell order for existing position
            positions = self._broker.get_positions()
            pos = positions.get(signal.symbol)
            if pos is None or pos.quantity <= 0:
                return None
            return Order(
                symbol=signal.symbol,
                side=OrderSide.SELL,
                quantity=pos.quantity,
                strategy_id=signal.strategy_id,
                timestamp=bar.timestamp,
            )

        if signal.direction == Direction.LONG:
            # Size based on allocation weight
            quantity = self._qty_per_signal * allocation.weight * 100  # scale up
            if quantity <= 0:
                return None
            return Order(
                symbol=signal.symbol,
                side=OrderSide.BUY,
                quantity=quantity,
                strategy_id=signal.strategy_id,
                timestamp=bar.timestamp,
            )

        if signal.direction == Direction.SHORT:
            # Size based on allocation weight
            quantity = self._qty_per_signal * allocation.weight * 100  # scale up
            if quantity <= 0:
                return None
            return Order(
                symbol=signal.symbol,
                side=OrderSide.SELL,
                quantity=quantity,
                strategy_id=signal.strategy_id,
                timestamp=bar.timestamp,
            )

        return None