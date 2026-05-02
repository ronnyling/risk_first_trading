"""Abstract broker interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.types import Fill, Order, PortfolioState, Position


class Broker(ABC):
    """Abstract base class for broker implementations.

    Capability flags:
        supports_market_price_updates: If True, the engine will call
            update_market_price() each bar with the current close price.
            MockBroker needs this; live brokers (IB) provide their own prices.
    """

    supports_market_price_updates: bool = False

    @abstractmethod
    def submit_order(self, order: Order) -> Fill | None:
        """Submit an order. Returns Fill if executed, None if rejected."""
        ...

    @abstractmethod
    def get_positions(self) -> dict[str, Position]:
        """Return current open positions keyed by symbol."""
        ...

    @abstractmethod
    def get_portfolio_state(self) -> PortfolioState:
        """Return a snapshot of the current portfolio state."""
        ...

    @abstractmethod
    def get_trade_history(self) -> list:
        """Return all completed trades."""
        ...

    def update_market_price(self, symbol: str, price: float) -> None:
        """Update the current market price for a symbol (no-op by default).

        Override in brokers that need externally-supplied price updates
        (e.g., MockBroker during CSV replay).
        """
