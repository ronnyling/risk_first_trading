"""Stop-Run Fade strategy ? dumb, deterministic, no indicators.

Rules (execution layer only):
  Entry (LONG):
    1. Stop run below: price goes below swing low and fails
    2. Entry: SHORT when price goes above swing high and fails (stop run above -> short)
"""

from __future__ import annotations

import logging

from src.core.types import Bar, Direction, Fill, Signal
from src.policy.strategy_family_policy import StrategyFamily
from src.strategies.base import Strategy, StrategyMetadata

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK = 20
DEFAULT_EPSILON_PCT = 0.001  # 0.1%


class StopRunFadeStrategy(Strategy):
    """Fade false breakouts at liquidity levels (stop-run reversal).
    Modified for Entry Symmetry (Long + Short).
    stop run below -> long, stop run above -> short.
    """

    def __init__(
        self,
        lookback: int = DEFAULT_LOOKBACK,
        epsilon_pct: float = DEFAULT_EPSILON_PCT,
    ) -> None:
        self._lookback = lookback
        self._epsilon_pct = epsilon_pct
        self._metadata = StrategyMetadata(
            strategy_id="stop_run_fade_v1",
            version="1.1",
            asset_class="crypto",
            style="liquidity",
            timeframe="1h",
            known_failure_regimes=["trending"],
            max_allocation_pct=0.15,
            expected_trade_frequency="monthly",
            family="liquidity_smc",
        )
        self._position: Direction = Direction.FLAT

    @property
    def metadata(self) -> StrategyMetadata:
        return self._metadata

    @property
    def family(self) -> StrategyFamily:
        return StrategyFamily.LIQUIDITY_SMC

    @property
    def timeframe(self) -> str:
        return "1h"

    @property
    def name(self) -> str:
        return "stop_run_fade_v1"

    def _swing_levels(self, bars_history: list[Bar]) -> tuple[float, float] | None:
        if len(bars_history) < self._lookback + 1:
            return None

        prior = bars_history[-(self._lookback + 1) : -1]
        swing_high = max(b.high for b in prior)
        swing_low = min(b.low for b in prior)
        return swing_high, swing_low

    def _range_is_valid(self, swing_high: float, swing_low: float) -> bool:
        return swing_high > swing_low

    def on_bar(self, bar: Bar, bars_history: list[Bar]) -> Signal | None:
        levels = self._swing_levels(bars_history)
        if levels is None:
            return None

        swing_high, swing_low = levels

        if not self._range_is_valid(swing_high, swing_low):
            return None

        epsilon = self._epsilon_pct * bar.close

        # Cond Exits
        if self._position == Direction.LONG:
            # TP: hit swing high
            if bar.close >= swing_high:
                self._position = Direction.FLAT
                return Signal(
                    strategy_id=self.metadata.strategy_id,
                    timestamp=bar.timestamp,
                    symbol="BTC/USD",
                    direction=Direction.FLAT,
                    strength=1.0,
                )
            # Stop: goes below lowest low (handled by exit logic or execution logic usually)
            
        elif self._position == Direction.SHORT:
            # TP: hit swing low
            if bar.close <= swing_low:
                self._position = Direction.FLAT
                return Signal(
                    strategy_id=self.metadata.strategy_id,
                    timestamp=bar.timestamp,
                    symbol="BTC/USD",
                    direction=Direction.FLAT,
                    strength=1.0,
                )

        # Entry logic
        if self._position == Direction.FLAT:
            # stop run below -> long
            stop_run_below = bar.low < swing_low - epsilon
            failure_below = bar.close > swing_low
            
            if stop_run_below and failure_below:
                self._position = Direction.LONG
                return Signal(
                    strategy_id=self.metadata.strategy_id,
                    timestamp=bar.timestamp,
                    symbol="BTC/USD",
                    direction=Direction.LONG,
                    strength=1.0,
                    metadata={"entry_type": "stop_run_fade_long"},
                )

            # stop run above -> short
            stop_run_above = bar.high > swing_high + epsilon
            failure_above = bar.close < swing_high
            
            if stop_run_above and failure_above:
                self._position = Direction.SHORT
                return Signal(
                    strategy_id=self.metadata.strategy_id,
                    timestamp=bar.timestamp,
                    symbol="BTC/USD",
                    direction=Direction.SHORT,
                    strength=1.0,
                    metadata={"entry_type": "stop_run_fade_short"},
                )

        return None

    def on_fill(self, fill: Fill) -> None:
        pass

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
        self._position = Direction.FLAT
