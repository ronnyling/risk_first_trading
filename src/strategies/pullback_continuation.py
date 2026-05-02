"""Pullback Continuation strategy — trend-following within structural_fractal family.

Rules (execution layer only):
  Entry (LONG):
    1. Trend established: EMA(20) > EMA(50) (uptrend)
    2. Pullback: price retraces to EMA(20) zone (dynamic support)
    3. Confirmation: close > EMA(20) after touching/breaching it
    4. Entry at close of confirmation bar

  Exit:
    - Close when EMA(20) crosses below EMA(50) (trend reversal)
    - Or when price closes below EMA(50) (stop-level)

Strategy only emits entry signals. Stop/TP management is execution-layer.
"""

from __future__ import annotations

import logging

from src.core.types import Bar, Direction, Fill, Signal
from src.policy.strategy_family_policy import StrategyFamily
from src.strategies.base import Strategy, StrategyMetadata

logger = logging.getLogger(__name__)

DEFAULT_EMA_FAST = 20
DEFAULT_EMA_SLOW = 50
DEFAULT_PULLBACK_TOLERANCE = 0.002  # 0.2%


class PullbackContinuationStrategy(Strategy):
    """Trend-following: enter on pullback to EMA in established uptrend."""

    def __init__(
        self,
        ema_fast: int = DEFAULT_EMA_FAST,
        ema_slow: int = DEFAULT_EMA_SLOW,
        pullback_tolerance: float = DEFAULT_PULLBACK_TOLERANCE,
    ) -> None:
        self._ema_fast_period = ema_fast
        self._ema_slow_period = ema_slow
        self._pullback_tolerance = pullback_tolerance
        self._metadata = StrategyMetadata(
            strategy_id="pullback_continuation_v1",
            version="1.0",
            asset_class="crypto",
            style="trend",
            timeframe="1h",
            known_failure_regimes=["ranging"],
            max_allocation_pct=0.3,
            expected_trade_frequency="daily",
            family="structural_fractal",
        )
        self._position: Direction = Direction.FLAT

    @property
    def metadata(self) -> StrategyMetadata:
        return self._metadata

    @property
    def family(self) -> StrategyFamily:
        return StrategyFamily.STRUCTURAL_FRACTAL

    @property
    def timeframe(self) -> str:
        return "1h"

    @property
    def name(self) -> str:
        return "pullback_continuation_v1"

    def _compute_ema(self, closes: list[float], period: int) -> float:
        """Compute EMA for given closes list over specified period.

        Uses proper EMA with multiplier 2/(period+1).
        Falls back to SMA if insufficient data.
        """
        if len(closes) < period:
            return sum(closes) / len(closes) if closes else 0.0

        # Seed with SMA of first 'period' values
        sma = sum(closes[:period]) / period
        multiplier = 2.0 / (period + 1)

        ema = sma
        for price in closes[period:]:
            ema = (price - ema) * multiplier + ema

        return ema

    def on_bar(self, bar: Bar, bars_history: list[Bar]) -> Signal | None:
        """Check for pullback continuation entry."""
        min_bars = self._ema_slow_period + 1
        if len(bars_history) < min_bars:
            return None

        # Compute EMAs from all bars including current
        closes = [b.close for b in bars_history]
        ema_fast = self._compute_ema(closes, self._ema_fast_period)
        ema_slow = self._compute_ema(closes, self._ema_slow_period)

        # Check for exit conditions first (reversal)
        if self._position == Direction.LONG:
            # Trend reversal: EMA(fast) crosses below EMA(slow)
            if ema_fast < ema_slow:
                self._position = Direction.FLAT
                return Signal(
                    strategy_id=self.metadata.strategy_id,
                    timestamp=bar.timestamp,
                    symbol="BTC/USD",
                    direction=Direction.SHORT,
                    strength=0.5,
                    metadata={
                        "ema_fast": ema_fast,
                        "ema_slow": ema_slow,
                        "exit_type": "trend_reversal",
                    },
                )
            # Stop-level: close below EMA(slow)
            if bar.close < ema_slow:
                self._position = Direction.FLAT
                return Signal(
                    strategy_id=self.metadata.strategy_id,
                    timestamp=bar.timestamp,
                    symbol="BTC/USD",
                    direction=Direction.SHORT,
                    strength=0.5,
                    metadata={
                        "ema_fast": ema_fast,
                        "ema_slow": ema_slow,
                        "exit_type": "stop_level",
                    },
                )

        # Entry conditions (only when flat)
        if self._position == Direction.FLAT:
            # 1. Trend established: EMA(fast) > EMA(slow)
            if ema_fast <= ema_slow:
                return None

            # 2. Pullback: low touched EMA(fast) zone (within tolerance)
            lower_bound = ema_fast * (1 - self._pullback_tolerance)
            upper_bound = ema_fast * (1 + self._pullback_tolerance)
            touched_pullback = bar.low <= upper_bound

            if not touched_pullback:
                return None

            # 3. Confirmation: close > EMA(fast)
            if bar.close <= ema_fast:
                return None

            # All conditions met — emit LONG signal
            self._position = Direction.LONG
            return Signal(
                strategy_id=self.metadata.strategy_id,
                timestamp=bar.timestamp,
                symbol="BTC/USD",
                direction=Direction.LONG,
                strength=min((bar.close - ema_fast) / ema_fast, 1.0) if ema_fast > 0 else 0.0,
                metadata={
                    "ema_fast": ema_fast,
                    "ema_slow": ema_slow,
                    "entry_type": "pullback_continuation",
                },
            )

        return None

    def on_fill(self, fill: Fill) -> None:
        """Track position state."""
        if fill.side.value == "buy" and self._position == Direction.FLAT:
            self._position = Direction.LONG
        elif fill.side.value == "sell" and self._position == Direction.LONG:
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
