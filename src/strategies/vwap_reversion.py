"""VWAP Reversion strategy — mean reversion at VWAP with RSI confirmation.

Rules (execution layer only):
  Entry (LONG):
    1. Price is below VWAP (below fair value)
    2. RSI(14) < 35 (oversold confirmation)
    3. Price closes above VWAP after being below (reversion start)

  Entry (SHORT):
    1. Price is above VWAP (above fair value)
    2. RSI(14) > 65 (overbought confirmation)
    3. Price closes below VWAP after being above (reversion start)

  Exit:
    - Long: RSI > 60 or price closes below VWAP by > 0.5%
    - Short: RSI < 40 or price closes above VWAP by > 0.5%

Strategy only emits entry signals. Stop/TP management is execution-layer.
"""

from __future__ import annotations

import logging

from src.core.types import Bar, Direction, Fill, Signal
from src.policy.strategy_family_policy import StrategyFamily
from src.strategies.base import Strategy, StrategyMetadata

logger = logging.getLogger(__name__)

DEFAULT_RSI_PERIOD = 14
DEFAULT_RSI_OVERSOLD = 35
DEFAULT_RSI_OVERBOUGHT = 65
DEFAULT_VWAP_DEVIATION = 0.005  # 0.5%


class VWAPReversionStrategy(Strategy):
    """Mean reversion at VWAP with RSI confirmation."""

    def __init__(
        self,
        rsi_period: int = DEFAULT_RSI_PERIOD,
        rsi_oversold: float = DEFAULT_RSI_OVERSOLD,
        rsi_overbought: float = DEFAULT_RSI_OVERBOUGHT,
        vwap_deviation: float = DEFAULT_VWAP_DEVIATION,
    ) -> None:
        self._rsi_period = rsi_period
        self._rsi_oversold = rsi_oversold
        self._rsi_overbought = rsi_overbought
        self._vwap_deviation = vwap_deviation
        self._metadata = StrategyMetadata(
            strategy_id="vwap_reversion_v1",
            version="1.0",
            asset_class="crypto",
            style="mean_reversion",
            timeframe="1h",
            known_failure_regimes=["trending"],
            max_allocation_pct=0.25,
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
        return "vwap_reversion_v1"

    def _compute_vwap(self, bars: list[Bar]) -> float:
        """Compute VWAP from session bars.

        VWAP = cumsum(close * volume) / cumsum(volume)
        For backtest purposes, session reset is daily (simplified).
        """
        if not bars:
            return 0.0

        cumulative_pv = 0.0
        cumulative_vol = 0.0

        for bar in bars:
            cumulative_pv += bar.close * bar.volume
            cumulative_vol += bar.volume

        if cumulative_vol == 0:
            return bars[-1].close

        return cumulative_pv / cumulative_vol

    def _compute_rsi(self, bars: list[Bar]) -> float:
        """Compute RSI from bars using standard Wilder smoothing."""
        if len(bars) < self._rsi_period + 1:
            return 50.0  # neutral when insufficient data

        # Calculate price changes
        changes = [bars[i].close - bars[i - 1].close for i in range(1, len(bars))]

        # Initial average gain/loss
        gains = [max(c, 0) for c in changes[:self._rsi_period]]
        losses = [abs(min(c, 0)) for c in changes[:self._rsi_period]]

        avg_gain = sum(gains) / self._rsi_period
        avg_loss = sum(losses) / self._rsi_period

        # Wilder smoothing
        for i in range(self._rsi_period, len(changes)):
            gain = max(changes[i], 0)
            loss = abs(min(changes[i], 0))
            avg_gain = (avg_gain * (self._rsi_period - 1) + gain) / self._rsi_period
            avg_loss = (avg_loss * (self._rsi_period - 1) + loss) / self._rsi_period

        # Both zero means no movement — neutral RSI
        if avg_gain == 0 and avg_loss == 0:
            return 50.0
        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_bar(self, bar: Bar, bars_history: list[Bar]) -> Signal | None:
        """Check for VWAP reversion entry."""
        min_bars = self._rsi_period + 2
        if len(bars_history) < min_bars:
            return None

        # Compute VWAP and RSI from all bars including current
        vwap = self._compute_vwap(bars_history)
        rsi = self._compute_rsi(bars_history)

        # Get previous bar's close relative to VWAP
        prev_bar = bars_history[-2]
        prev_below_vwap = prev_bar.close < vwap
        prev_above_vwap = prev_bar.close > vwap

        # Exit conditions (check first)
        if self._position == Direction.LONG:
            # Exit long: RSI > 60 or close below VWAP by > 0.5%
            if rsi > 60 or bar.close < vwap * (1 - self._vwap_deviation):
                self._position = Direction.FLAT
                return Signal(
                    strategy_id=self.metadata.strategy_id,
                    timestamp=bar.timestamp,
                    symbol="BTC/USD",
                    direction=Direction.SHORT,
                    strength=0.5,
                    metadata={
                        "vwap": vwap,
                        "rsi": rsi,
                        "exit_type": "long_exit",
                    },
                )

        elif self._position == Direction.SHORT:
            # Exit short: RSI < 40 or close above VWAP by > 0.5%
            if rsi < 40 or bar.close > vwap * (1 + self._vwap_deviation):
                self._position = Direction.FLAT
                return Signal(
                    strategy_id=self.metadata.strategy_id,
                    timestamp=bar.timestamp,
                    symbol="BTC/USD",
                    direction=Direction.LONG,
                    strength=0.5,
                    metadata={
                        "vwap": vwap,
                        "rsi": rsi,
                        "exit_type": "short_exit",
                    },
                )

        # Entry conditions (only when flat)
        if self._position == Direction.FLAT:
            # Long entry: prev close < VWAP, RSI < 35, current close > VWAP
            if prev_below_vwap and rsi < self._rsi_oversold and bar.close > vwap:
                self._position = Direction.LONG
                return Signal(
                    strategy_id=self.metadata.strategy_id,
                    timestamp=bar.timestamp,
                    symbol="BTC/USD",
                    direction=Direction.LONG,
                    strength=min((vwap - bar.close) / vwap, 1.0) if vwap > 0 else 0.0,
                    metadata={
                        "vwap": vwap,
                        "rsi": rsi,
                        "entry_type": "long_vwap_reversion",
                    },
                )

            # Short entry: prev close > VWAP, RSI > 65, current close < VWAP
            if prev_above_vwap and rsi > self._rsi_overbought and bar.close < vwap:
                self._position = Direction.SHORT
                return Signal(
                    strategy_id=self.metadata.strategy_id,
                    timestamp=bar.timestamp,
                    symbol="BTC/USD",
                    direction=Direction.SHORT,
                    strength=min((bar.close - vwap) / vwap, 1.0) if vwap > 0 else 0.0,
                    metadata={
                        "vwap": vwap,
                        "rsi": rsi,
                        "entry_type": "short_vwap_reversion",
                    },
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
