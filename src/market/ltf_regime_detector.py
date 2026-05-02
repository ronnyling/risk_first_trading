"""LTF Regime Detector — Non-predictive regime classification for lower timeframes.

Uses only closed bars. No centered indicators, no future data.
"""

from __future__ import annotations

import logging
import statistics
from src.core.types import Bar

logger = logging.getLogger(__name__)


class LTFRegimeDetector:
    """Classifies LTF regime from recent closed-bar history.

    Outputs one of: TRENDING, RANGING, VOLATILE.

    Volatility floor: if ATR < floor_pct * median ATR → RANGING.
    This prevents false regime flips during low-liquidity periods.
    """

    def __init__(
        self,
        lookback: int = 16,
        vol_threshold_high: float = 0.02,
        vol_threshold_low: float = 0.008,
        floor_pct: float = 0.5,
        vol_floor_lookback: int = 20,
    ) -> None:
        self._lookback = lookback
        self._vol_threshold_high = vol_threshold_high
        self._vol_threshold_low = vol_threshold_low
        self._floor_pct = floor_pct
        self._vol_floor_lookback = vol_floor_lookback
        self._current: str = "UNKNOWN"

    @property
    def current(self) -> str:
        return self._current

    def _atr(self, bars: list[Bar]) -> float | None:
        if len(bars) < 2:
            return None
        recent = bars[-min(len(bars), self._lookback):]
        trs: list[float] = []
        for i in range(1, len(recent)):
            high = recent[i].high
            low = recent[i].low
            prev_close = recent[i - 1].close
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
        return sum(trs) / len(trs) if trs else None

    def _median_atr(self, bars: list[Bar]) -> float | None:
        """Median ATR over a longer window for volatility floor."""
        if len(bars) < 3:
            return None
        recent = bars[-min(len(bars), self._vol_floor_lookback):]
        trs: list[float] = []
        for i in range(1, len(recent)):
            high = recent[i].high
            low = recent[i].low
            prev_close = recent[i - 1].close
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)
        return statistics.median(trs) if trs else None

    def _directional_strength(self, bars: list[Bar]) -> float:
        recent = bars[-min(len(bars), self._lookback):]
        if len(recent) < 2:
            return 0.0
        total_range = 0.0
        net_move = 0.0
        for i in range(1, len(recent)):
            total_range += recent[i].high - recent[i].low
            net_move += recent[i].close - recent[i - 1].close
        return net_move / total_range if total_range > 0 else 0.0

    def update(self, bars: list[Bar]) -> str:
        """Classify LTF regime from closed-bar history only."""
        atr = self._atr(bars)
        if atr is None:
            self._current = "UNKNOWN"
            return self._current

        price = bars[-1].close
        if price == 0:
            self._current = "UNKNOWN"
            return self._current

        norm_vol = atr / price

        # Volatility floor: suppress false signals in low-ATR environments
        med_atr = self._median_atr(bars)
        if med_atr is not None and med_atr > 0:
            floor_threshold = self._floor_pct * med_atr / price
            if norm_vol < floor_threshold:
                self._current = "RANGING"
                logger.debug(
                    "LTF Regime: %s (vol=%.4f < floor=%.4f)",
                    self._current, norm_vol, floor_threshold,
                )
                return self._current

        direction = self._directional_strength(bars)
        abs_dir = abs(direction)

        if norm_vol > self._vol_threshold_high:
            self._current = "VOLATILE"
        elif abs_dir > 0.3 and norm_vol <= self._vol_threshold_high:
            self._current = "TRENDING"
        else:
            self._current = "RANGING"

        logger.debug(
            "LTF Regime: %s (vol=%.4f, dir=%.3f)", self._current, norm_vol, direction
        )
        return self._current