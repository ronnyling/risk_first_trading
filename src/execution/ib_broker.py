"""Interactive Brokers paper-trading adapter.

Uses ib_insync to connect to TWS/IB Gateway paper account.
Market orders only (Phase 6 constraint). Extra-conservative order size caps.

Usage:
    broker = IBBroker.from_config(ib_config_dict)
    broker.connect()
    fill = broker.submit_order(order)
    broker.disconnect()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

from src.core.types import (
    Fill,
    Order,
    OrderSide,
    PortfolioState,
    Position,
    Trade,
)
from src.execution.broker import Broker

logger = logging.getLogger(__name__)


@dataclass
class IBConfig:
    """IB connection and safety configuration."""

    host: str = "127.0.0.1"
    port: int = 7497  # 7497 = TWS paper, 4002 = Gateway paper
    client_id: int = 1
    account: str = ""  # empty = auto-detect

    # Safety caps (extra-conservative for paper trading)
    max_order_notional: float = 500.0  # max dollar value per order
    max_position_notional: float = 1000.0  # max dollar value per position

    # Timeout and retry
    fill_timeout_seconds: float = 30.0
    reconnect_attempts: int = 3
    reconnect_delay_seconds: float = 5.0

    # Instrument defaults
    default_symbol: str = "SPY"
    default_exchange: str = "SMART"
    default_currency: str = "USD"


class IBBroker(Broker):
    """Interactive Brokers paper-trading adapter.

    Implements the Broker ABC for IB TWS/IB Gateway connections.
    Designed for Phase 6 validation: market orders only, extra-conservative caps,
    explicit handling for rejects, partials, and disconnects.

    Capability flags:
        supports_market_price_updates = False  (IB provides its own prices)
    """

    supports_market_price_updates: bool = False

    def __init__(self, config: IBConfig | None = None) -> None:
        self._config = config or IBConfig()
        self._ib = None  # ib_insync.IB instance, created on connect
        self._connected = False
        self._account: str = self._config.account
        self._positions: dict[str, Position] = {}
        self._trades: list[Trade] = []
        self._filled_orders: list[Fill] = []

    @classmethod
    def from_config(cls, config_dict: dict) -> IBBroker:
        """Create IBBroker from a YAML config dictionary (the ib: section)."""
        ib_config = IBConfig(
            host=config_dict.get("host", "127.0.0.1"),
            port=config_dict.get("port", 7497),
            client_id=config_dict.get("client_id", 1),
            account=config_dict.get("account", ""),
            max_order_notional=config_dict.get("max_order_notional", 500.0),
            max_position_notional=config_dict.get("max_position_notional", 1000.0),
            fill_timeout_seconds=config_dict.get("fill_timeout_seconds", 30.0),
            reconnect_attempts=config_dict.get("reconnect_attempts", 3),
            reconnect_delay_seconds=config_dict.get("reconnect_delay_seconds", 5.0),
            default_symbol=config_dict.get("default_symbol", "SPY"),
            default_exchange=config_dict.get("default_exchange", "SMART"),
            default_currency=config_dict.get("default_currency", "USD"),
        )
        return cls(config=ib_config)

    # --- Connection Management ---

    def connect(self) -> None:
        """Connect to IB TWS/Gateway. Raises on failure."""
        try:
            from ib_insync import IB
        except ImportError:
            raise RuntimeError(
                "ib_insync is not installed. Run: pip install ib_insync"
            )

        for attempt in range(1, self._config.reconnect_attempts + 1):
            try:
                logger.info(
                    "Connecting to IB: %s:%d (client_id=%d, attempt %d/%d)",
                    self._config.host,
                    self._config.port,
                    self._config.client_id,
                    attempt,
                    self._config.reconnect_attempts,
                )
                # Create a fresh IB instance per attempt to avoid stale state
                self._ib = IB()
                self._ib.connect(
                    self._config.host,
                    self._config.port,
                    clientId=self._config.client_id,
                )
                self._connected = True

                # Resolve account if not specified
                if not self._account:
                    accounts = self._ib.managedAccounts()
                    if accounts:
                        self._account = accounts[0]
                    else:
                        raise RuntimeError("No managed accounts found on IB connection")

                logger.info(
                    "Connected to IB — account: %s",
                    self._account,
                )
                return

            except Exception as e:
                logger.warning(
                    "IB connection attempt %d/%d failed: %s",
                    attempt,
                    self._config.reconnect_attempts,
                    e,
                )
                if attempt < self._config.reconnect_attempts:
                    time.sleep(self._config.reconnect_delay_seconds)

        raise RuntimeError(
            f"Failed to connect to IB after {self._config.reconnect_attempts} attempts"
        )

    def disconnect(self) -> None:
        """Disconnect from IB gracefully."""
        if self._ib and self._connected:
            try:
                self._ib.disconnect()
                logger.info("Disconnected from IB")
            except Exception as e:
                logger.error("Error during IB disconnect: %s", e)
            finally:
                self._connected = False

    def is_connected(self) -> bool:
        """Check if still connected to IB."""
        if not self._ib or not self._connected:
            return False
        try:
            return self._ib.isConnected()
        except Exception:
            self._connected = False
            return False

    def _ensure_connected(self) -> None:
        """Verify connection; attempt reconnect if lost."""
        if not self.is_connected():
            logger.warning("IB connection lost — attempting reconnect")
            self._connected = False
            self.connect()

    # --- Contract Mapping ---

    def _make_contract(self, symbol: str) -> object:
        """Create an IB Contract for the given symbol.

        Phase 6: Maps any symbol to the configured default_symbol.
        Strategies may emit crypto symbols (BTC/USD) from CSV replay,
        but IB stock adapter resolves only valid equity tickers.
        """
        from ib_insync import Stock

        ib_symbol = self._config.default_symbol
        if symbol != ib_symbol:
            logger.debug(
                "Remapping symbol %s -> %s for IB contract", symbol, ib_symbol
            )

        return Stock(
            ib_symbol,
            self._config.default_exchange,
            self._config.default_currency,
        )

    # --- Order Size Validation ---

    def _validate_order(self, order: Order, last_price: float) -> str | None:
        """Pre-submission validation. Returns error reason or None if OK."""
        notional = order.quantity * last_price

        # Market orders only (Phase 6)
        from src.core.types import OrderType
        if order.order_type != OrderType.MARKET:
            return f"Only MARKET orders allowed in Phase 6, got {order.order_type.value}"

        # Order size cap
        if notional > self._config.max_order_notional:
            return (
                f"Order notional ${notional:.2f} exceeds cap "
                f"${self._config.max_order_notional:.2f}"
            )

        # Position size cap (buy only — sell reduces position)
        if order.side == OrderSide.BUY:
            current_pos = self._positions.get(order.symbol)
            current_notional = 0.0
            if current_pos is not None:
                current_notional = current_pos.quantity * last_price
            projected = current_notional + notional
            if projected > self._config.max_position_notional:
                return (
                    f"Projected position ${projected:.2f} would exceed cap "
                    f"${self._config.max_position_notional:.2f}"
                )

        return None

    # --- Core Broker Interface ---

    def submit_order(self, order: Order) -> Fill | None:
        """Submit a market order to IB.

        Returns Fill if executed, None if rejected/failed.
        Handles: immediate fill, rejection, timeout, partial fill, disconnect.
        """
        self._ensure_connected()

        contract = self._make_contract(order.symbol)

        # Get market price for validation (best-effort, not blocking).
        # Market data is an IB account-level entitlement, not a TWS setting.
        # For market orders, fill status comes from orderStatus, not ticks.
        last_price = None
        try:
            ticker = self._ib.reqMktData(contract, '', False, False)
            time.sleep(1.0)  # brief wait for market data
            last_price = ticker.last
            if last_price is None or last_price <= 0:
                if ticker.bid and ticker.ask and ticker.bid > 0 and ticker.ask > 0:
                    last_price = (ticker.bid + ticker.ask) / 2.0
            self._ib.cancelMktData(contract)
        except Exception as e:
            logger.debug("Market data unavailable for %s: %s", order.symbol, e)

        # Validate order size (skip if no price available — submit anyway for market orders)
        if last_price is not None and last_price > 0:
            error_reason = self._validate_order(order, last_price)
            if error_reason:
                logger.warning("Order rejected: %s", error_reason)
                return None
        else:
            logger.info(
                "No market data for %s — submitting without notional validation", order.symbol
            )

        # Build IB order
        from ib_insync import MarketOrder as IBMarketOrder

        ib_order = IBMarketOrder(
            action="BUY" if order.side == OrderSide.BUY else "SELL",
            totalQuantity=order.quantity,
        )

        # Submit
        try:
            ib_trade = self._ib.placeOrder(contract, ib_order)
            logger.info(
                "IB order submitted: %s %s %.4f %s (orderId=%s)",
                order.side.value,
                contract.symbol,
                order.quantity,
                order.order_type.value,
                ib_trade.order.orderId,
            )
        except Exception as e:
            logger.error("IB order submission failed: %s", e)
            return None

        # Wait for fill with timeout
        fill = self._wait_for_fill(ib_trade, order)

        if fill is not None:
            self._filled_orders.append(fill)
            self._update_local_position(fill)

        return fill

    def _wait_for_fill(self, ib_trade, order: Order) -> Fill | None:
        """Poll for order fill status with timeout.

        Returns Fill on success, None on rejection/timeout/partial-with-timeout.
        """
        deadline = time.time() + self._config.fill_timeout_seconds

        while time.time() < deadline:
            # Check connection
            if not self.is_connected():
                logger.warning("IB disconnected while waiting for fill on %s", order.order_id)
                return None

            status = ib_trade.orderStatus.status
            filled_qty = ib_trade.orderStatus.filled

            if status == "Filled":
                # Determine actual fill price
                avg_fill_price = ib_trade.orderStatus.avgFillPrice
                if avg_fill_price is None or avg_fill_price <= 0:
                    avg_fill_price = ib_trade.orderStatus.lastFillPrice or 0.0

                commission = 0.0
                if ib_trade.orderStatus.commission is not None:
                    commission = ib_trade.orderStatus.commission

                fill = Fill(
                    order_id=order.order_id,
                    symbol=order.symbol,
                    side=order.side,
                    quantity=filled_qty if filled_qty > 0 else order.quantity,
                    fill_price=avg_fill_price,
                    commission=commission,
                    timestamp=datetime.now(),
                    strategy_id=order.strategy_id,
                )

                logger.info(
                    "IB fill: %s %s %.4f @ %.2f (commission: %.2f)",
                    fill.side.value,
                    fill.symbol,
                    fill.quantity,
                    fill.fill_price,
                    fill.commission,
                )
                return fill

            elif status in ("Cancelled", "Inactive"):
                logger.warning(
                    "IB order %s %s: %s",
                    order.order_id,
                    order.symbol,
                    status,
                )
                return None

            elif status == "Rejected":
                reject_reason = ib_trade.orderStatus.warningText or "unknown"
                logger.warning(
                    "IB order rejected: %s — %s", order.order_id, reject_reason
                )
                return None

            # Partial fill — keep waiting
            if filled_qty and filled_qty > 0 and filled_qty < order.quantity:
                logger.debug(
                    "Partial fill on %s: %.4f / %.4f — waiting",
                    order.order_id,
                    filled_qty,
                    order.quantity,
                )

            time.sleep(0.5)

        # Timeout — cancel remaining
        logger.warning(
            "Fill timeout (%.0fs) for order %s — cancelling",
            self._config.fill_timeout_seconds,
            order.order_id,
        )
        try:
            self._ib.cancelOrder(ib_trade.order)
        except Exception as e:
            logger.error("Failed to cancel timed-out order %s: %s", order.order_id, e)

        # If there was a partial fill, return it
        if ib_trade.orderStatus.filled and ib_trade.orderStatus.filled > 0:
            fill = Fill(
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                quantity=ib_trade.orderStatus.filled,
                fill_price=ib_trade.orderStatus.avgFillPrice or 0.0,
                commission=ib_trade.orderStatus.commission or 0.0,
                timestamp=datetime.now(),
                strategy_id=order.strategy_id,
            )
            self._filled_orders.append(fill)
            self._update_local_position(fill)
            logger.warning(
                "Returning partial fill: %.4f / %.4f",
                fill.quantity,
                order.quantity,
            )
            return fill

        return None

    def _update_local_position(self, fill: Fill) -> None:
        """Update local position tracking after a fill."""
        symbol = fill.symbol
        pos = self._positions.get(symbol)

        if fill.side == OrderSide.BUY:
            if pos is None:
                self._positions[symbol] = Position(
                    symbol=symbol,
                    quantity=fill.quantity,
                    avg_entry_price=fill.fill_price,
                    unrealized_pnl=0.0,
                    strategy_id=fill.strategy_id,
                )
            else:
                total_cost = pos.avg_entry_price * pos.quantity + fill.fill_price * fill.quantity
                pos.quantity += fill.quantity
                pos.avg_entry_price = total_cost / pos.quantity if pos.quantity else 0.0
        else:
            if pos is not None:
                # Record trade on close
                trade = Trade(
                    symbol=symbol,
                    side=fill.side,
                    quantity=fill.quantity,
                    entry_price=pos.avg_entry_price,
                    exit_price=fill.fill_price,
                    pnl=(fill.fill_price - pos.avg_entry_price) * fill.quantity,
                    strategy_id=fill.strategy_id,
                )
                self._trades.append(trade)

                pos.quantity -= fill.quantity
                if pos.quantity <= 0:
                    del self._positions[symbol]

    def get_positions(self) -> dict[str, Position]:
        """Return current positions from local tracking.

        For live positions, IB would be queried directly. During CSV replay,
        local tracking is sufficient since fills drive state.
        """
        self._ensure_connected()

        # Sync from IB if connected
        try:
            ib_positions = self._ib.positions()
            result: dict[str, Position] = {}
            for p in ib_positions:
                symbol = p.contract.symbol
                if p.position != 0:
                    result[symbol] = Position(
                        symbol=symbol,
                        quantity=abs(p.position),
                        avg_entry_price=p.avgCost / abs(p.position) if p.position != 0 else 0.0,
                        unrealized_pnl=0.0,
                        strategy_id="",
                    )
            # Merge with local (local wins for strategy_id tracking)
            for symbol, local_pos in self._positions.items():
                if symbol not in result:
                    result[symbol] = local_pos
            return result
        except Exception as e:
            logger.warning("Failed to query IB positions, using local: %s", e)
            return dict(self._positions)

    def get_portfolio_state(self) -> PortfolioState:
        """Return portfolio state from IB account summary."""
        self._ensure_connected()

        try:
            account_summary = self._ib.accountSummary()
            account_values = {v.tag: v.value for v in account_summary}

            equity = float(account_values.get("NetLiquidation", 0.0))
            cash = float(account_values.get("CashBalance", 0.0))
            gross_position_value = float(account_values.get("GrossPositionValue", 0.0))

            positions = self.get_positions()
            total_position_value = sum(
                p.quantity * p.avg_entry_price for p in positions.values()
            )

            # Use IB's PnL if available
            total_pnl = equity - self._config.max_order_notional * 10  # rough fallback
            try:
                pnl_value = float(account_values.get("UnrealizedPnL", 0.0))
                realized_pnl = float(account_values.get("RealizedPnL", 0.0))
                total_pnl = pnl_value + realized_pnl
            except (ValueError, TypeError):
                pass

            # Drawdown (approximate — would need historical peak tracking)
            drawdown = 0.0
            peak = equity
            exposure_pct = gross_position_value / equity if equity > 0 else 0.0
            leverage = gross_position_value / equity if equity > 0 else 0.0

            return PortfolioState(
                cash=cash,
                positions=positions,
                total_value=equity,
                total_pnl=total_pnl,
                drawdown=drawdown,
                peak_value=peak,
                leverage=leverage,
                exposure_pct=exposure_pct,
            )

        except Exception as e:
            logger.error("Failed to get IB portfolio state: %s — using local", e)
            # Fallback to local tracking
            positions = self.get_positions()
            total_value = sum(
                p.quantity * p.avg_entry_price for p in positions.values()
            )
            return PortfolioState(
                cash=0.0,
                positions=positions,
                total_value=total_value,
                total_pnl=0.0,
                drawdown=0.0,
                peak_value=total_value,
                leverage=0.0,
                exposure_pct=1.0 if total_value > 0 else 0.0,
            )

    def get_trade_history(self) -> list[Trade]:
        """Return locally tracked completed trades."""
        return list(self._trades)