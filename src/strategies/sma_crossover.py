"""Example trend-following strategy: SMA crossover. Modified for Entry Symmetry and HTF Confirmation."""

from __future__ import annotations

import logging

from src.core.types import Bar, Direction, Fill, Signal
from src.strategies.base import Strategy, StrategyMetadata

logger = logging.getLogger(__name__)


class SMACrossoverStrategy(Strategy):
    """Simple SMA crossover: long when fast > slow, short when fast < slow.
    Includes HTF confirmation logic and pivot structure tracking."""

    def __init__(self, fast_period: int = 10, slow_period: int = 20) -> None:
        self._fast_period = fast_period
        self._slow_period = slow_period
        self._metadata = StrategyMetadata(
            strategy_id="sma_crossover_v1",
            version="1.1",
            asset_class="crypto",
            style="trend",
            timeframe="1h",
            known_failure_regimes=["ranging", "volatile"],
            max_allocation_pct=0.3,
            expected_trade_frequency="daily",
            family="structural_fractal",
        )
        self._position: Direction = Direction.FLAT
        
        # Track pivots for trailing stops
        self._last_pivot_low: float | None = None
        self._last_pivot_high: float | None = None

    @property
    def metadata(self) -> StrategyMetadata:
        return self._metadata

    def _sma(self, bars: list[Bar], period: int, offset: int = 0) -> float | None:
        if len(bars) < period + offset:
            return None
        closes = [b.close for b in bars[-(period + offset): len(bars) - offset if offset > 0 else None]]
        return sum(closes) / period

    def _check_pivots(self, bars: list[Bar]) -> None:
        if len(bars) < 5:
            return
            
        # pivotlow(low, 2, 2)
        p0, p1, p2, p3, p4 = bars[-5], bars[-4], bars[-3], bars[-2], bars[-1]
        
        if p2.low < p0.low and p2.low < p1.low and p2.low < p3.low and p2.low < p4.low:
            self._last_pivot_low = p2.low
            
        # pivothigh(high, 2, 2)
        if p2.high > p0.high and p2.high > p1.high and p2.high > p3.high and p2.high > p4.high:
            self._last_pivot_high = p2.high

    def _htf_confirmation(self, bars: list[Bar]) -> tuple[bool, bool]:
        """Simulate HTF confirmation logic using 3x periods."""
        htf_fast_period = self._fast_period * 3
        htf_slow_period = self._slow_period * 3
        
        fma = self._sma(bars, htf_fast_period)
        sma = self._sma(bars, htf_slow_period)
        fma1 = self._sma(bars, htf_fast_period, offset=1)
        sma1 = self._sma(bars, htf_slow_period, offset=1)
        
        if None in (fma, sma, fma1, sma1):
            return True, True  # Bypass if not enough data
            
        long_align = fma > sma and fma > fma1 and sma > sma1
        
        short_align_base = fma < sma
        short_align_strong = fma < sma and fma < fma1 and sma < sma1
        
        # Simple structural integrity (higher low for long, lower high for short)
        # Fix 1: Shorts allow EITHER lower-high OR strong negative slope.
        # Since Python currently relies on MA alignment, we strictly enforce strong negative slope for shorts.
        short_align = short_align_strong
        
        return long_align, short_align

    def on_bar(self, bar: Bar, bars_history: list[Bar]) -> Signal | None:
        self._check_pivots(bars_history)
        
        fast = self._sma(bars_history, self._fast_period)
        slow = self._sma(bars_history, self._slow_period)

        if fast is None or slow is None:
            return None

        # Exit conditions crossunder for long, crossover for short
        if self._position == Direction.LONG and fast < slow:
            self._position = Direction.FLAT
            return Signal(
                strategy_id=self.metadata.strategy_id,
                timestamp=bar.timestamp,
                symbol="BTC/USD",
                direction=Direction.FLAT,
                strength=1.0,
            )
        elif self._position == Direction.SHORT and fast > slow:
            self._position = Direction.FLAT
            return Signal(
                strategy_id=self.metadata.strategy_id,
                timestamp=bar.timestamp,
                symbol="BTC/USD",
                direction=Direction.FLAT,
                strength=1.0,
            )

        # Entry triggers
        is_long_trigger = fast > slow
        is_short_trigger = fast < slow
        
        htf_ok_long, htf_ok_short = self._htf_confirmation(bars_history)

        new_direction = Direction.FLAT
        if is_long_trigger and htf_ok_long and self._position != Direction.LONG:
            new_direction = Direction.LONG
        elif is_short_trigger and htf_ok_short and self._position != Direction.SHORT:
            new_direction = Direction.SHORT

        if new_direction == Direction.FLAT or new_direction == self._position:
            return None

        self._position = new_direction
        strength = min(abs(fast - slow) / slow, 1.0) if slow else 0.0

        return Signal(
            strategy_id=self.metadata.strategy_id,
            timestamp=bar.timestamp,
            symbol="BTC/USD",
            direction=new_direction,
            strength=strength,
            metadata={
                "fast_sma": fast, 
                "slow_sma": slow,
                "last_pivot_low": self._last_pivot_low,
                "last_pivot_high": self._last_pivot_high
            },
        )

    def on_fill(self, fill: Fill) -> None:
        if fill.side.value == "sell" and self._position == Direction.LONG:
            self._position = Direction.FLAT
        elif fill.side.value == "buy" and self._position == Direction.SHORT:
            self._position = Direction.FLAT

    def on_reconcile(self, positions: dict) -> None:
        """Reconcile strategy state with broker positions on startup."""
        for sym, pos in positions.items():
            if pos.quantity != 0:
                self._position = Direction.LONG if pos.quantity > 0 else Direction.SHORT
                logger.info(
                    "Reconciled %s: %s %s qty=%.4f",
                    self.metadata.strategy_id, sym, self._position.name, pos.quantity,
                )
