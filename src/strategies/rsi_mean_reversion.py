"""Example mean-reversion strategy: RSI-based. Modified for Entry Symmetry (Long + Short)."""

from __future__ import annotations

import logging

from src.core.types import Bar, Direction, Fill, Signal
from src.strategies.base import Strategy, StrategyMetadata

logger = logging.getLogger(__name__)


class RSIMeanReversionStrategy(Strategy):
    """RSI mean-reversion: long when oversold, short when overbought."""

    def __init__(
        self,
        rsi_period: int = 14,           
        oversold: float = 30.0,         
        overbought: float = 70.0,       
        min_distance_pct: float = 0.005,  
    ) -> None:
        self._rsi_period = rsi_period
        self._oversold = oversold
        self._overbought = overbought
        self._min_distance_pct = min_distance_pct
        self._metadata = StrategyMetadata(
            strategy_id="rsi_mean_reversion_v1",
            version="1.1",
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

    def _rsi(self, bars: list[Bar]) -> float | None:
        if len(bars) < self._rsi_period + 1:
            return None

        closes = [b.close for b in bars[-(self._rsi_period + 1) :]]
        gains: list[float] = []
        losses: list[float] = []

        for i in range(1, len(closes)):
            delta = closes[i] - closes[i - 1]
            if delta > 0:
                gains.append(delta)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(delta))

        avg_gain = sum(gains) / len(gains) if gains else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def on_bar(self, bar: Bar, bars_history: list[Bar]) -> Signal | None:
        rsi = self._rsi(bars_history)
        if rsi is None:
            return None

        # Cond_Exit Logic
        if self._position == Direction.LONG and rsi > self._overbought:
            self._position = Direction.FLAT
            return Signal(
                strategy_id=self.metadata.strategy_id,
                timestamp=bar.timestamp,
                symbol="BTC/USD",
                direction=Direction.FLAT,
                strength=1.0,
                metadata={"rsi": rsi},
            )
        elif self._position == Direction.SHORT and rsi < self._oversold:
            self._position = Direction.FLAT
            return Signal(
                strategy_id=self.metadata.strategy_id,
                timestamp=bar.timestamp,
                symbol="BTC/USD",
                direction=Direction.FLAT,
                strength=1.0,
                metadata={"rsi": rsi},
            )

        # Entry triggers
        if rsi < self._oversold and self._position != Direction.LONG:
            self._position = Direction.LONG
            strength = (self._oversold - rsi) / self._oversold
            return Signal(
                strategy_id=self.metadata.strategy_id,
                timestamp=bar.timestamp,
                symbol="BTC/USD",
                direction=Direction.LONG,
                strength=min(strength, 1.0),
                metadata={"rsi": rsi},
            )

        if rsi > self._overbought and self._position != Direction.SHORT:
            self._position = Direction.SHORT
            strength = (rsi - self._overbought) / self._overbought
            return Signal(
                strategy_id=self.metadata.strategy_id,
                timestamp=bar.timestamp,
                symbol="BTC/USD",
                direction=Direction.SHORT,
                strength=min(strength, 1.0),
                metadata={"rsi": rsi},
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
