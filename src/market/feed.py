"""Market feed: iterates bars and provides history to strategies."""

from __future__ import annotations

from collections.abc import Iterator
from src.core.types import Bar


class MarketFeed:
    """Iterates over historical bars, providing a sliding window of history."""

    def __init__(self, bars: list[Bar]) -> None:
        self._bars = bars
        self._index = 0

    def __len__(self) -> int:
        return len(self._bars)

    def __iter__(self) -> Iterator[Bar]:
        return self

    def __next__(self) -> Bar:
        if self._index >= len(self._bars):
            raise StopIteration
        bar = self._bars[self._index]
        self._index += 1
        return bar

    def get_history(self, n: int) -> list[Bar]:
        """Return the last n bars including the current one."""
        end = self._index
        start = max(0, end - n)
        return self._bars[start:end]

    @property
    def current_index(self) -> int:
        return self._index

    def reset(self) -> None:
        self._index = 0