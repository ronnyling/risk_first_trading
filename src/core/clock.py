"""Simulated clock for deterministic bar-by-bar replay."""

from __future__ import annotations

from datetime import datetime


class SimClock:
    """Tracks the current simulation time, advancing bar-by-bar."""

    def __init__(self) -> None:
        self._current: datetime | None = None
        self._bar_index: int = 0

    @property
    def now(self) -> datetime:
        if self._current is None:
            raise RuntimeError("Clock not started. Call advance() first.")
        return self._current

    @property
    def bar_index(self) -> int:
        return self._bar_index

    def advance(self, timestamp: datetime) -> None:
        self._current = timestamp
        self._bar_index += 1

    def reset(self) -> None:
        self._current = None
        self._bar_index = 0