"""CsvMarketDataAdapter — CSV-based market data adapter.

Wraps the existing load_csv() + in-memory bar list behind the
MarketDataAdapter interface. Behavior-preserving: same bars, same order.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.core.types import Bar
from src.market.adapter import MarketDataAdapter
from src.market.data_loader import load_csv

logger = logging.getLogger(__name__)


class CsvMarketDataAdapter(MarketDataAdapter):
    """CSV-based market data adapter.

    Loads all bars into memory at start(), then yields them one at a time
    via get_next_bar(). Supports reset() for replay loops.
    """

    def __init__(self, filepath: str | Path) -> None:
        super().__init__()
        self._filepath = Path(filepath)
        self._bars: list[Bar] = []
        self._index: int = 0

    def start(self) -> None:
        """Load all bars from CSV into memory."""
        self._bars = load_csv(self._filepath)
        self._index = 0
        self._bars_processed = 0
        logger.info(
            "CsvMarketDataAdapter started: %d bars from %s",
            len(self._bars),
            self._filepath,
        )

    def stop(self) -> None:
        """No-op for CSV adapter."""
        logger.info(
            "CsvMarketDataAdapter stopped: %d bars processed",
            self._bars_processed,
        )

    def get_next_bar(self) -> Bar | None:
        """Return the next bar, or None at end of file."""
        if self._index >= len(self._bars):
            return None
        bar = self._bars[self._index]
        self._index += 1
        self._increment_bar_count()
        return bar

    def get_history(self, n: int) -> list[Bar]:
        """Return the last n bars including the current one."""
        end = self._index
        start = max(0, end - n)
        return self._bars[start:end]

    @property
    def source_name(self) -> str:
        return "csv"

    @property
    def is_live(self) -> bool:
        return False

    def reset(self) -> None:
        """Reset to the beginning for replay."""
        self._index = 0
        self._bars_processed = 0
        logger.debug("CsvMarketDataAdapter reset to bar 0")


class _LegacyFeedAdapter(MarketDataAdapter):
    """Internal adapter that wraps a MarketFeed for backward compatibility.

    Allows the engine to accept both old-style MarketFeed and new MarketDataAdapter.
    """

    def __init__(self, feed: "MarketFeed") -> None:  # noqa: F821
        super().__init__()
        self._feed = feed

    def start(self) -> None:
        pass  # Legacy feed is already loaded

    def stop(self) -> None:
        pass  # Legacy feed has no cleanup

    def get_next_bar(self) -> Bar | None:
        try:
            bar = next(self._feed)
            self._increment_bar_count()
            return bar
        except StopIteration:
            return None

    def get_history(self, n: int) -> list[Bar]:
        return self._feed.get_history(n)

    @property
    def source_name(self) -> str:
        return "legacy_feed"

    @property
    def is_live(self) -> bool:
        return False
