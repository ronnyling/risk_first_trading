"""AMT Value Area Reversion strategy — mean reversion at value area boundaries.

Rules (execution layer only):
  Compute VAH, VAL, POC over last N=20 bars.
  Long Entry: low <= VAL AND close > VAL (tested VAL, held above)
  Short Entry: high >= VAH AND close < VAH (tested VAH, held below)
  Stop Long: close < VAL
  Stop Short: close > VAH
  TP: POC (mean reversion to fair value)

Strategy only emits entry signals. Stop/TP management is execution-layer.
"""

from __future__ import annotations

import logging

from src.core.types import Bar, Direction, Fill, Signal
from src.policy.strategy_family_policy import StrategyFamily
from src.strategies.base import Strategy, StrategyMetadata

logger = logging.getLogger(__name__)

LOOKBACK = 20
VALUE_AREA_PCT = 0.70  # 70% of range as value area


class AMTValueReversionStrategy(Strategy):
    """Mean reversion at AMT value area boundaries.

    Tunable parameters (identical defaults to frozen version):
        lookback: Number of bars for value area computation (α7)
        value_area_pct: Percentage of range as value area (α8)
    """

    def __init__(
        self,
        lookback: int = 20,            # α7: value area computation window
        value_area_pct: float = 0.70,  # α8: value area percentage of range
    ) -> None:
        self._lookback = lookback
        self._value_area_pct = value_area_pct
        self._metadata = StrategyMetadata(
            strategy_id="amt_value_reversion_v1",
            version="1.0",
            asset_class="crypto",
            style="mean_reversion",
            timeframe="1h",
            known_failure_regimes=["trending"],
            max_allocation_pct=0.3,
            expected_trade_frequency="daily",
            family="mean_reversion",
        )
        self._position: Direction = Direction.FLAT

    @property
    def metadata(self) -> StrategyMetadata:
        return self._metadata

    @property
    def family(self) -> StrategyFamily:
        return StrategyFamily.MEAN_REVERSION

    @property
    def timeframe(self) -> str:
        return "1h"

    @property
    def name(self) -> str:
        return "amt_value_reversion_v1"

    def _compute_value_area(self, bars: list[Bar]) -> tuple[float, float, float]:
        """Compute VAH, VAL, POC from recent bars."""
        window = bars[-self._lookback:]
        highs = [b.high for b in window]
        lows = [b.low for b in window]
        closes = [b.close for b in window]

        range_high = max(highs)
        range_low = min(lows)
        total_range = range_high - range_low

        if total_range <= 0:
            mid = closes[-1]
            return mid, mid, mid

        # POC approximation: midpoint of range
        poc = (range_high + range_low) / 2

        # Value area centered on midpoint
        va_half = total_range * self._value_area_pct / 2
        vah = poc + va_half
        val = poc - va_half

        return vah, val, poc

    def on_bar(self, bar: Bar, bars_history: list[Bar]) -> Signal | None:
        """Check for value area rejection entry."""
        if len(bars_history) < self._lookback + 1:
            return None

        # Compute value area from bars BEFORE current (no look-ahead)
        prior_bars = bars_history[:-1]
        vah, val, poc = self._compute_value_area(prior_bars)

        if self._position == Direction.FLAT:
            # Long entry: tested VAL, closed above
            if bar.low <= val and bar.close > val:
                self._position = Direction.LONG
                return Signal(
                    strategy_id=self.metadata.strategy_id,
                    timestamp=bar.timestamp,
                    symbol="SPY",
                    direction=Direction.LONG,
                    strength=min((bar.close - val) / val, 1.0) if val > 0 else 0.0,
                    metadata={"vah": vah, "val": val, "poc": poc, "entry_type": "long_val"},
                )

            # Short entry: tested VAH, closed below
            if bar.high >= vah and bar.close < vah:
                self._position = Direction.SHORT
                return Signal(
                    strategy_id=self.metadata.strategy_id,
                    timestamp=bar.timestamp,
                    symbol="SPY",
                    direction=Direction.SHORT,
                    strength=min((vah - bar.close) / vah, 1.0) if vah > 0 else 0.0,
                    metadata={"vah": vah, "val": val, "poc": poc, "entry_type": "short_vah"},
                )

        return None

    def on_fill(self, fill: Fill) -> None:
        """Track position state."""
        if fill.side.value == "buy" and self._position == Direction.FLAT:
            self._position = Direction.LONG
        elif fill.side.value == "sell" and self._position == Direction.FLAT:
            self._position = Direction.SHORT
        else:
            # Closing fill
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

    def reset_position(self) -> None:
        """Reset position state (for backtest stop/TP exits)."""
        self._position = Direction.FLAT