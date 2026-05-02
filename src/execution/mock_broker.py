"""Mock broker for simulated trading (paper trading / replay)."""

from __future__ import annotations

import logging
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


class MockBroker(Broker):
    """Simulated broker for offline replay and paper trading.

    Features:
    - Configurable initial capital
    - Configurable slippage (basis points)
    - Position tracking
    - Trade history
    """

    supports_market_price_updates: bool = True

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        slippage_bps: float = 5.0,
        commission_bps: float = 1.0,
    ) -> None:
        self._cash = initial_capital
        self._initial_capital = initial_capital
        self._positions: dict[str, Position] = {}
        self._trades: list[Trade] = []
        self._slippage_bps = slippage_bps
        self._commission_bps = commission_bps
        self._current_price: dict[str, float] = {}

    def update_market_price(self, symbol: str, price: float) -> None:
        """Update the current market price for a symbol (called by engine each bar)."""
        self._current_price[symbol] = price

    def _apply_slippage(self, price: float, side: OrderSide) -> float:
        """Apply slippage to the fill price."""
        slip = price * (self._slippage_bps / 10_000)
        if side == OrderSide.BUY:
            return price + slip  # pay more
        return price - slip  # receive less

    def _calc_commission(self, quantity: float, price: float) -> float:
        """Calculate commission."""
        return abs(quantity * price * self._commission_bps / 10_000)

    def submit_order(self, order: Order) -> Fill | None:
        """Execute an order with slippage and commission."""
        market_price = self._current_price.get(order.symbol)
        if market_price is None:
            logger.warning("No market price for %s — rejecting order", order.symbol)
            return None

        fill_price = self._apply_slippage(market_price, order.side)
        commission = self._calc_commission(order.quantity, fill_price)

        # Check if we have enough cash for a buy
        if order.side == OrderSide.BUY:
            cost = order.quantity * fill_price + commission
            if cost > self._cash:
                logger.warning(
                    "Insufficient cash: need %.2f, have %.2f",
                    cost,
                    self._cash,
                )
                return None
            self._cash -= cost
        else:
            # Selling: check if we have enough position
            pos = self._positions.get(order.symbol)
            if pos is None or pos.quantity < order.quantity:
                logger.warning(
                    "Insufficient position to sell %s: need %.4f",
                    order.symbol,
                    order.quantity,
                )
                return None
            self._cash += order.quantity * fill_price - commission

        # Update positions
        self._update_position(order.symbol, order.side, order.quantity, fill_price)

        fill = Fill(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            fill_price=fill_price,
            commission=commission,
            timestamp=order.timestamp,
            strategy_id=order.strategy_id,
        )

        logger.debug(
            "Filled: %s %s %.4f @ %.2f (commission: %.2f)",
            order.side.value,
            order.symbol,
            order.quantity,
            fill_price,
            commission,
        )

        return fill

    def _update_position(
        self, symbol: str, side: OrderSide, quantity: float, fill_price: float
    ) -> None:
        """Update position after a fill."""
        pos = self._positions.get(symbol)

        if side == OrderSide.BUY:
            if pos is None:
                self._positions[symbol] = Position(
                    symbol=symbol,
                    quantity=quantity,
                    avg_entry_price=fill_price,
                    unrealized_pnl=0.0,
                    strategy_id="",
                )
            else:
                total_cost = pos.avg_entry_price * pos.quantity + fill_price * quantity
                pos.quantity += quantity
                pos.avg_entry_price = total_cost / pos.quantity if pos.quantity else 0.0
        else:
            if pos is not None:
                pos.quantity -= quantity
                if pos.quantity <= 0:
                    # Close position
                    trade = Trade(
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        entry_price=pos.avg_entry_price,
                        exit_price=fill_price,
                        pnl=(fill_price - pos.avg_entry_price) * quantity,
                        strategy_id=pos.strategy_id,
                    )
                    self._trades.append(trade)
                    del self._positions[symbol]

    def get_positions(self) -> dict[str, Position]:
        """Return current positions with unrealized PnL."""
        result = {}
        for symbol, pos in self._positions.items():
            market_price = self._current_price.get(symbol, pos.avg_entry_price)
            pos.unrealized_pnl = (market_price - pos.avg_entry_price) * pos.quantity
            result[symbol] = pos
        return result

    def get_portfolio_state(self) -> PortfolioState:
        """Return current portfolio state."""
        positions = self.get_positions()
        total_position_value = sum(
            p.quantity * self._current_price.get(p.symbol, p.avg_entry_price)
            for p in positions.values()
        )
        total_unrealized = sum(p.unrealized_pnl for p in positions.values())
        total_value = self._cash + total_position_value

        # Drawdown calculation
        peak = max(self._initial_capital, total_value)
        drawdown = (peak - total_value) / peak if peak > 0 else 0.0

        # Exposure
        exposure_pct = total_position_value / total_value if total_value > 0 else 0.0

        # Leverage (simplified: gross exposure / equity)
        leverage = total_position_value / total_value if total_value > 0 else 0.0

        return PortfolioState(
            cash=self._cash,
            positions=positions,
            total_value=total_value,
            total_pnl=total_value - self._initial_capital,
            drawdown=drawdown,
            peak_value=peak,
            leverage=leverage,
            exposure_pct=exposure_pct,
        )

    def get_trade_history(self) -> list[Trade]:
        return list(self._trades)