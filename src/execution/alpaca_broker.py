"""Alpaca Broker — Real Paper Trading broker implementing the Broker ABC.

This is the ONLY sanctioned broker implementation for Alpaca connectivity.
All methods make real API calls to https://paper-api.alpaca.markets.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest, MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide as AlpacaOrderSide, OrderStatus, TimeInForce

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


class AlpacaBroker(Broker):
    """Real Alpaca Paper Trading broker implementing the Broker ABC.

    Wraps alpaca-py TradingClient. Every method makes a real API call.
    No fallback to mock data. No simulation.

    Usage:
        broker = AlpacaBroker()
        state = broker.get_portfolio_state()
        fill = broker.submit_order(order)
    """

    supports_market_price_updates: bool = False  # Alpaca provides its own prices

    def __init__(self) -> None:
        api_key = os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("ALPACA_SECRET_KEY")
        if not api_key or not secret_key:
            raise ValueError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in .env"
            )
        self.client = TradingClient(api_key, secret_key, paper=True)
        # Track peak equity for drawdown calculation
        self._peak_equity: float = 0.0
        self._trade_history: list[Trade] = []
        logger.info("AlpacaBroker initialized (paper mode)")

    @staticmethod
    def _is_fractional(order: Order) -> bool:
        """Detect whether an order is fractional.

        Alpaca requires DAY time-in-force for fractional orders.
        Fractional = qty is not an integer, qty < 1, or notional is set.
        """
        qty = order.quantity
        # Non-integer qty (e.g. 0.03)
        if qty != int(qty):
            return True
        # Qty < 1 is inherently fractional
        if qty < 1:
            return True
        # Notional orders are always fractional
        if getattr(order, "notional", None) is not None:
            return True
        return False

    def submit_order(self, order: Order) -> Fill | None:
        """Submit an order to Alpaca. Returns Fill if executed, None if rejected."""
        try:
            side = (
                AlpacaOrderSide.BUY
                if order.side == OrderSide.BUY
                else AlpacaOrderSide.SELL
            )

            # Alpaca requires DAY for all fractional orders (error 42210000)
            tif = TimeInForce.DAY if self._is_fractional(order) else TimeInForce.GTC

            if order.order_type == "limit" and order.price is not None:
                req = LimitOrderRequest(
                    symbol=order.symbol,
                    qty=order.quantity,
                    limit_price=order.price,
                    side=side,
                    time_in_force=tif,
                    client_order_id=order.order_id,
                )
            else:
                req = MarketOrderRequest(
                    symbol=order.symbol,
                    qty=order.quantity,
                    side=side,
                    time_in_force=tif,
                    client_order_id=order.order_id,
                )

            logger.debug(
                "Alpaca order payload: symbol=%s side=%s qty=%.4f "
                "tif=%s fractional=%s type=%s",
                order.symbol, order.side.value, order.quantity,
                tif.value, self._is_fractional(order), order.order_type,
            )

            res = self.client.submit_order(req)
            filled_qty = float(res.filled_qty) if res.filled_qty else 0.0
            fill_price = float(res.filled_avg_price) if res.filled_avg_price else 0.0

            if filled_qty == 0.0:
                # Order accepted by Alpaca but not filled (e.g. sizing rounded to zero)
                logger.warning(
                    "Order accepted but NOT filled: %s %s requested_qty=%.4f status=%s",
                    order.side.value, order.symbol, order.quantity, res.status,
                )
                return None

            fill = Fill(
                order_id=str(res.id),
                symbol=res.symbol,
                side=order.side,
                quantity=filled_qty,
                fill_price=fill_price,
                commission=0.0,  # Alpaca paper has zero commission
                timestamp=datetime.now(),
                strategy_id=order.strategy_id,
            )
            logger.info(
                "Order filled: %s %s %.4f @ %.2f",
                order.side.value,
                res.symbol,
                fill.quantity,
                fill_price,
            )
            return fill

        except Exception as e:
            logger.error("Alpaca order failed: %s", e)
            return None

    def get_positions(self) -> dict[str, Position]:
        """Return current open positions keyed by symbol."""
        result: dict[str, Position] = {}
        try:
            positions = self.client.get_all_positions()
            for p in positions:
                result[p.symbol] = Position(
                    symbol=p.symbol,
                    quantity=float(p.qty),
                    avg_entry_price=float(p.avg_entry_price),
                    unrealized_pnl=float(p.unrealized_pl),
                    strategy_id="alpaca",
                )
        except Exception as e:
            logger.error("Failed to get Alpaca positions: %s", e)
        return result

    def get_portfolio_state(self) -> PortfolioState:
        """Return current portfolio state via real Alpaca API call."""
        try:
            account = self.client.get_account()
            positions = self.get_positions()

            equity = float(account.equity)
            cash = float(account.cash)

            # Update peak for drawdown calculation
            if equity > self._peak_equity:
                self._peak_equity = equity

            # Calculate total position value
            total_position_value = sum(
                pos.quantity * (pos.avg_entry_price + pos.unrealized_pnl / pos.quantity if pos.quantity else 0)
                for pos in positions.values()
            )
            total_unrealized = sum(p.unrealized_pnl for p in positions.values())

            # Drawdown
            drawdown = 0.0
            if self._peak_equity > 0:
                drawdown = (self._peak_equity - equity) / self._peak_equity

            # Exposure
            exposure_pct = total_position_value / equity if equity > 0 else 0.0

            # Leverage
            leverage = total_position_value / equity if equity > 0 else 0.0

            state = PortfolioState(
                cash=cash,
                positions=positions,
                total_value=equity,
                total_pnl=float(account.equity) - float(account.last_equity)
                if hasattr(account, "last_equity")
                else 0.0,
                drawdown=drawdown,
                peak_value=self._peak_equity,
                leverage=leverage,
                exposure_pct=exposure_pct,
            )
            logger.debug(
                "Portfolio: equity=%.2f, cash=%.2f, drawdown=%.4f",
                equity,
                cash,
                drawdown,
            )
            return state

        except Exception as e:
            logger.error("Failed to get Alpaca portfolio state: %s", e)
            # Return a minimal state so callers don't crash
            return PortfolioState(cash=0.0, total_value=0.0)

    def get_trade_history(self) -> list[Trade]:
        """Return filled orders from Alpaca.

        Uses get_orders(status="closed") then filters for filled_qty > 0.
        This respects alpaca-py's enum validation (only "open"/"closed"/"all" allowed).
        Activities are not used — they are only needed for dividends, fees, transfers.
        """
        try:
            request = GetOrdersRequest(status="closed")
            orders = self.client.get_orders(request)
            trades: list[Trade] = []
            for order in orders:
                filled_qty = float(order.filled_qty) if order.filled_qty else 0.0
                filled_price = float(order.filled_avg_price) if order.filled_avg_price else 0.0

                # Skip orders that were never filled
                if filled_qty <= 0:
                    continue

                side = (
                    OrderSide.BUY
                    if order.side == AlpacaOrderSide.BUY
                    else OrderSide.SELL
                )
                filled_at = (
                    order.filled_at
                    if isinstance(order.filled_at, datetime)
                    else datetime.now()
                )
                trades.append(
                    Trade(
                        trade_id=str(order.id),
                        symbol=order.symbol,
                        side=side,
                        quantity=filled_qty,
                        entry_price=filled_price,
                        exit_price=filled_price,
                        pnl=0.0,  # PnL not available on order object
                        strategy_id=order.client_order_id or "alpaca",
                        entry_time=filled_at,
                        exit_time=filled_at,
                    )
                )
            self._trade_history = trades
            logger.debug("Fetched %d filled orders from Alpaca", len(trades))
            return trades

        except Exception as e:
            logger.error("Failed to get Alpaca trade history: %s", e)
            return self._trade_history
