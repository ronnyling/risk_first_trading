"""Simple regime detector based on volatility and trend strength."""

from __future__ import annotations

import logging
import math
from src.core.types import Bar, Regime

logger = logging.getLogger(__name__)


class RegimeDetector:
    """Classifies market regime from recent bar history.

    Uses a simple, deterministic approach:
    - ATR-based volatility classification
    - Directional movement for trend detection

    This is intentionally simple — Hermes reasons about regimes, not indicators.
    """

    def __init__(
        self,
        lookback: int = 20,
        vol_threshold_high: float = 0.02,
        vol_threshold_low: float = 0.008,
    ) -> None:
        self._lookback = lookback
        self._vol_threshold_high = vol_threshold_high
        self._vol_threshold_low = vol_threshold_low
        self._current: Regime = Regime.UNKNOWN

    @property
    def current(self) -> Regime:
        return self._current

    def _atr(self, bars: list[Bar]) -> float | None:
        """Average True Range over the lookback window."""
        if len(bars) < 2:
            return None

        recent = bars[-min(len(bars), self._lookback) :]
        trs: list[float] = []
        for i in range(1, len(recent)):
            high = recent[i].high
            low = recent[i].low
            prev_close = recent[i - 1].close
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)

        return sum(trs) / len(trs) if trs else None

    def _directional_strength(self, bars: list[Bar]) -> float:
        """Normalized net direction over the lookback window. Range: -1 to +1."""
        recent = bars[-min(len(bars), self._lookback) :]
        if len(recent) < 2:
            return 0.0

        total_range = 0.0
        net_move = 0.0
        for i in range(1, len(recent)):
            total_range += recent[i].high - recent[i].low
            net_move += recent[i].close - recent[i - 1].close

        if total_range == 0:
            return 0.0
        return net_move / total_range

    def update(self, bars: list[Bar]) -> Regime:
        """Classify the current regime from bar history."""
        atr = self._atr(bars)
        if atr is None:
            self._current = Regime.UNKNOWN
            return self._current

        # Normalize ATR as fraction of price
        price = bars[-1].close
        if price == 0:
            self._current = Regime.UNKNOWN
            return self._current

        norm_vol = atr / price
        direction = self._directional_strength(bars)
        abs_dir = abs(direction)

        if norm_vol > self._vol_threshold_high:
            self._current = Regime.VOLATILE
        elif abs_dir > 0.3 and norm_vol <= self._vol_threshold_high:
            self._current = Regime.TRENDING
        else:
            self._current = Regime.RANGING

        logger.debug(
            "Regime: %s (vol=%.4f, dir=%.3f)", self._current.value, norm_vol, direction
        )
        return self._current