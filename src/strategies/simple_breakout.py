"""Simple Breakout strategy ?" dumb, deterministic, no indicators. Modified for Entry Symmetry (Long + Short)."""

from __future__ import annotations

import logging

from src.core.types import Bar, Direction, Fill, Signal
from src.policy.strategy_family_policy import StrategyFamily
from src.strategies.base import Strategy, StrategyMetadata

logger = logging.getLogger(__name__)

LOOKBACK = 20


class SimpleBreakoutStrategy(Strategy):
    """Simple breakout: long when close breaks above N-bar high, short when close breaks below N-bar low."""

    def __init__(
        self,
        lookback: int = 20,                
        min_breakout_pct: float = 0.001,    
    ) -> None:
        self._lookback = lookback
        self._min_breakout_pct = min_breakout_pct
        self._metadata = StrategyMetadata(
            strategy_id="simple_breakout_v1",
            version="1.1",
            asset_class="crypto",
            style="breakout",
            timeframe="1h",
            known_failure_regimes=["ranging"],
            max_allocation_pct=0.3,
            expected_trade_frequency="daily",
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
        return "simple_breakout_v1"

    def on_bar(self, bar: Bar, bars_history: list[Bar]) -> Signal | None:
        if len(bars_history) < self._lookback + 1:
            return None

        # Compute highest high and lowest low over last N bars (excluding current)
        lookback_bars = bars_history[-(self._lookback + 1):-1]
        highest_high = max(b.high for b in lookback_bars)
        lowest_low = min(b.low for b in lookback_bars)

        # Cond Exits
        if self._position == Direction.LONG and bar.close < lowest_low:
            self._position = Direction.FLAT
            return Signal(
                strategy_id=self.metadata.strategy_id,
                timestamp=bar.timestamp,
                symbol="BTC/USD",
                direction=Direction.FLAT,
                strength=1.0,
            )
        elif self._position == Direction.SHORT and bar.close > highest_high:
            self._position = Direction.FLAT
            return Signal(
                strategy_id=self.metadata.strategy_id,
                timestamp=bar.timestamp,
                symbol="BTC/USD",
                direction=Direction.FLAT,
                strength=1.0,
            )

        # Entry triggers
        breakout_up_pct = (bar.close - highest_high) / highest_high if highest_high > 0 else 0.0
        breakout_dn_pct = (lowest_low - bar.close) / lowest_low if lowest_low > 0 else 0.0

        if bar.close > highest_high and breakout_up_pct >= self._min_breakout_pct and self._position != Direction.LONG:
            self._position = Direction.LONG
            return Signal(
                strategy_id=self.metadata.strategy_id,
                timestamp=bar.timestamp,
                symbol="BTC/USD",
                direction=Direction.LONG,
                strength=min(breakout_up_pct * 10, 1.0),
                metadata={
                    "highest_high": highest_high,
                    "entry_price": bar.close,
                },
            )

        if bar.close < lowest_low and breakout_dn_pct >= self._min_breakout_pct and self._position != Direction.SHORT:
            self._position = Direction.SHORT
            return Signal(
                strategy_id=self.metadata.strategy_id,
                timestamp=bar.timestamp,
                symbol="BTC/USD",
                direction=Direction.SHORT,
                strength=min(breakout_dn_pct * 10, 1.0),
                metadata={
                    "lowest_low": lowest_low,
                    "entry_price": bar.close,
                },
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
