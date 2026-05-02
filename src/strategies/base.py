"""Abstract base class and metadata for black-box strategies."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from src.core.types import Bar, Fill, Signal

logger = logging.getLogger(__name__)


@dataclass
class StrategyMetadata:
    """Mandatory metadata contract for every strategy.

    Hermes reasons about strategies entirely through this metadata + outcomes.
    It never inspects indicator logic.
    """

    strategy_id: str
    version: str
    asset_class: str  # "crypto", "equity", "forex"
    style: str  # "trend", "mean_reversion", "breakout"
    timeframe: str  # "1h", "4h", "1d"
    known_failure_regimes: list[str] = field(default_factory=list)
    max_allocation_pct: float = 0.3  # hard cap from strategy side
    expected_trade_frequency: str = "daily"  # "daily", "weekly", "monthly"
    family: str | None = None  # strategy family membership string (e.g. "structural_fractal")


class Strategy(ABC):
    """Abstract base class for all black-box strategies.

    Strategies are opaque units that:
    - Receive market bars and return signals
    - Have zero knowledge of portfolio state, other strategies, or capital
    - Never dynamically allocate capital
    """

    @property
    @abstractmethod
    def metadata(self) -> StrategyMetadata:
        """Return the strategy's metadata contract."""
        ...

    @abstractmethod
    def on_bar(self, bar: Bar, bars_history: list[Bar]) -> Signal | None:
        """Process a new bar and optionally emit a signal.

        Args:
            bar: The current bar.
            bars_history: Previous bars (including current). bars_history[-1] == bar.

        Returns:
            A Signal if the strategy wants to trade, None otherwise.
        """
        ...

    @abstractmethod
    def on_fill(self, fill: Fill) -> None:
        """Notify the strategy of a fill (for internal state tracking).

        The strategy does NOT decide position sizing or capital allocation.
        This is purely for its internal bookkeeping (e.g. tracking entry price).
        """
        ...

    def start(self) -> None:
        """Called when the strategy is activated. Override for setup logic."""
        logger.info("Strategy %s started", self.metadata.strategy_id)

    def on_reconcile(self, positions: dict) -> None:
        """Reconcile strategy state with broker positions on startup.

        Called once before the main loop starts. Strategy must:
        - NOT re-enter positions that already exist
        - Resume exit logic for existing positions
        - Default: no-op (strategies that track state should override)
        """
        pass

    def stop(self) -> None:
        """Called when the strategy is deactivated. Override for cleanup logic."""
        logger.info("Strategy %s stopped", self.metadata.strategy_id)