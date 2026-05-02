"""StreamingBarBuffer — per-symbol rolling bar buffer for live streaming data.

Maintains a bounded deque of bars that can be updated incrementally.
Used by StreamFetcher to provide fresh data to Hermes without full re-fetch.

Production data source:
    yfinance is considered a production live-data adapter for Hermes advisory
    runs until the Alpaca data subscription is formally enabled.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from src.core.types import Bar

logger = logging.getLogger(__name__)


class BufferStatus(Enum):
    """Status of a streaming bar buffer."""
    FRESH = "fresh"       # updated within staleness threshold
    STALE = "stale"       # not updated within threshold
    DEAD = "dead"         # never updated or explicitly killed


@dataclass
class StreamingBarBuffer:
    """Per-symbol rolling bar buffer for live streaming data.

    Attributes:
        symbol: Universe symbol (e.g., "BTC/USD").
        bars: Bounded deque of Bar objects (newest appended right).
        last_updated: Timestamp of last successful update.
        status: Current freshness status.
        stale_threshold_seconds: Seconds since last update before STALE.
        max_bars: Maximum bars to retain in the buffer.
    """
    symbol: str
    bars: deque = field(default_factory=lambda: deque(maxlen=250))
    last_updated: datetime | None = None
    status: BufferStatus = BufferStatus.DEAD
    stale_threshold_seconds: int = 300  # 5 minutes
    max_bars: int = 250

    def __post_init__(self) -> None:
        """Ensure deque uses max_bars for maxlen."""
        if self.bars.maxlen != self.max_bars:
            # Re-create deque with correct maxlen
            existing = list(self.bars)
            self.bars = deque(existing, maxlen=self.max_bars)

    def update(self, new_bars: list[Bar]) -> int:
        """Append new bars to the buffer, dropping oldest if over capacity.

        Only appends bars with timestamps newer than the current newest bar.

        Args:
            new_bars: List of Bar objects to append.

        Returns:
            Number of new bars actually added.
        """
        if not new_bars:
            return 0

        # Determine the cutoff: only add bars newer than what we have
        if self.bars:
            newest_ts = self.bars[-1].timestamp
            if isinstance(newest_ts, datetime):
                filtered = [b for b in new_bars if b.timestamp > newest_ts]
            else:
                filtered = new_bars
        else:
            filtered = new_bars

        if not filtered:
            return 0

        added = 0
        for bar in filtered:
            self.bars.append(bar)
            added += 1

        self.last_updated = datetime.now()
        if self.status == BufferStatus.DEAD:
            self.status = BufferStatus.FRESH
        else:
            self.status = self.check_freshness()

        logger.debug(
            "Buffer %s: added %d bars (total: %d, status: %s)",
            self.symbol, added, len(self.bars), self.status.value,
        )
        return added

    def get_snapshot(self, count: int = 200) -> list[Bar]:
        """Return the last N bars as a list.

        Args:
            count: Maximum number of bars to return.

        Returns:
            List of Bar objects, oldest first.
        """
        n = min(count, len(self.bars))
        if n == 0:
            return []
        return list(self.bars)[-n:]

    def check_freshness(self) -> BufferStatus:
        """Check if the buffer is fresh, stale, or dead.

        Returns:
            BufferStatus based on time since last update.
        """
        if self.last_updated is None:
            return BufferStatus.DEAD

        elapsed = (datetime.now() - self.last_updated).total_seconds()

        if elapsed <= self.stale_threshold_seconds:
            return BufferStatus.FRESH
        else:
            return BufferStatus.STALE

    def is_usable(self) -> bool:
        """True if buffer has data that can be used for Hermes evaluation.

        FRESH and STALE buffers are usable. DEAD buffers are not.
        """
        if self.status == BufferStatus.DEAD:
            return False
        if len(self.bars) == 0:
            return False
        return True

    @property
    def bar_count(self) -> int:
        """Number of bars in the buffer."""
        return len(self.bars)

    @property
    def oldest_timestamp(self) -> datetime | None:
        """Timestamp of the oldest bar, or None if empty."""
        if not self.bars:
            return None
        ts = self.bars[0].timestamp
        return ts if isinstance(ts, datetime) else None

    @property
    def newest_timestamp(self) -> datetime | None:
        """Timestamp of the newest bar, or None if empty."""
        if not self.bars:
            return None
        ts = self.bars[-1].timestamp
        return ts if isinstance(ts, datetime) else None
