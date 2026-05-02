"""MarketDataAdapter — abstract interface for market data sources.

Strategies consume Bar objects and never know where data comes from.
This ABC defines the contract that all data sources (CSV, IB, vendor) must fulfill.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.types import Bar


class MarketDataAdapter(ABC):
    """Abstract market-data authority.

    Implementations provide bars to the TradingEngine.
    Strategies only see Bar objects — they never interact with this interface directly.

    Lifecycle: create → start() → get_next_bar() calls → stop()
    """

    def __init__(self) -> None:
        self._bars_processed: int = 0

    @abstractmethod
    def start(self) -> None:
        """Initialize connections, subscriptions, state.

        Called once before the engine loop begins.
        For CSV: loads the file. For IB: connects and subscribes.
        """

    @abstractmethod
    def stop(self) -> None:
        """Clean shutdown.

        Called once after the engine loop ends.
        For CSV: no-op. For IB: disconnects.
        """

    @abstractmethod
    def get_next_bar(self) -> Bar | None:
        """Return the next bar, or None if no more data.

        For CSV: returns bars sequentially from the loaded file.
        For IB: blocks until the next bar arrives (polling/event-driven).
        """

    @abstractmethod
    def get_history(self, n: int) -> list[Bar]:
        """Return the last n bars including the current one.

        Used by strategies for indicator lookback (e.g., SMA(20) needs 20 bars).
        """

    @property
    def bars_processed(self) -> int:
        """Number of bars returned by get_next_bar() so far."""
        return self._bars_processed

    def _increment_bar_count(self) -> None:
        """Subclasses call this after returning a bar from get_next_bar()."""
        self._bars_processed += 1

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Human-readable source identifier, e.g. 'csv', 'ib', 'polygon'."""

    @property
    @abstractmethod
    def is_live(self) -> bool:
        """True if real-time data, False if replay/historical."""

    def reset(self) -> None:
        """Reset to the beginning. Optional — not all adapters support this.

        CSV adapter supports it. IB live adapter raises NotImplementedError.
        """
        raise NotImplementedError(f"{self.source_name} does not support reset")