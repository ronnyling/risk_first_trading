"""CorrelationEngine — computes cross-asset correlation for portfolio-level Hermes reasoning.

Computes pairwise Pearson correlation from return series of universe symbols.
Used by HermesCoordinator to adjust risk budgeting and ranking.

Production data source:
    yfinance is considered a production live-data adapter for Hermes advisory
    runs until the Alpaca data subscription is formally enabled.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from src.hermes.agents.base import MarketState

logger = logging.getLogger(__name__)

# Minimum overlapping bars required for correlation computation
MIN_OVERLAPPING_BARS = 20


@dataclass(frozen=True)
class CorrelationMatrix:
    """Pairwise correlation matrix for universe symbols.

    Attributes:
        symbols: List of symbols in the matrix.
        matrix: Dict mapping (sym_a, sym_b) → correlation coefficient [-1.0, +1.0].
        high_pairs: List of (sym_a, sym_b, correlation) where |r| > threshold.
        computed_at: Timestamp of computation.
        threshold: Correlation threshold used for high_pairs detection.
    """
    symbols: list[str]
    matrix: dict[tuple[str, str], float]
    high_pairs: list[tuple[str, str, float]]
    computed_at: datetime
    threshold: float = 0.75

    def get(self, sym_a: str, sym_b: str) -> float:
        """Get correlation between two symbols.

        Returns 1.0 if same symbol, 0.0 if pair not found.
        """
        if sym_a == sym_b:
            return 1.0
        key = (sym_a, sym_b) if (sym_a, sym_b) in self.matrix else (sym_b, sym_a)
        return self.matrix.get(key, 0.0)

    def is_highly_correlated(self, sym_a: str, sym_b: str) -> bool:
        """True if |correlation| > threshold."""
        return abs(self.get(sym_a, sym_b)) > self.threshold

    @property
    def pair_count(self) -> int:
        """Number of unique pairs in the matrix."""
        return len(self.matrix)

    @property
    def high_pair_count(self) -> int:
        """Number of highly correlated pairs."""
        return len(self.high_pairs)

    def summary(self) -> dict[str, float | int]:
        """Summary statistics of the correlation matrix."""
        if not self.matrix:
            return {"pairs": 0, "mean": 0.0, "max": 0.0, "high_pairs": 0}

        values = list(self.matrix.values())
        return {
            "pairs": len(values),
            "mean": sum(values) / len(values),
            "max": max(abs(v) for v in values),
            "high_pairs": len(self.high_pairs),
        }


class CorrelationEngine:
    """Computes rolling correlation matrix from bar data.

    Uses log returns from close prices, aligned by timestamp (inner join).
    Computes Pearson correlation coefficient for each pair.

    Usage:
        engine = CorrelationEngine(window=50, threshold=0.75)
        matrix = engine.compute(market_states)
        if matrix.is_highly_correlated("BTC/USD", "ETH/USD"):
            # Apply concentration warning
    """

    def __init__(
        self,
        window: int = 50,
        threshold: float = 0.75,
        min_overlapping_bars: int = MIN_OVERLAPPING_BARS,
    ) -> None:
        """Initialize the correlation engine.

        Args:
            window: Number of bars for return series computation.
            threshold: |r| > threshold → highly correlated.
            min_overlapping_bars: Minimum overlapping bars for valid correlation.
        """
        self._window = window
        self._threshold = threshold
        self._min_overlapping = min_overlapping_bars

    def compute(
        self,
        market_states: list[MarketState],
        max_symbols: int | None = None,
    ) -> CorrelationMatrix:
        """Compute correlation matrix from market state bars.

        Args:
            market_states: One MarketState per universe symbol.
            max_symbols: Optional cap on number of symbols. If exceeded,
                takes top N by bar count (most data = most reliable).

        Returns:
            CorrelationMatrix with pairwise correlations.
        """
        # Scaling guard: truncate to max_symbols if provided
        if max_symbols and len(market_states) > max_symbols:
            logger.warning(
                "Correlation: %d symbols exceeds limit %d. Using top %d by bar count.",
                len(market_states), max_symbols, max_symbols,
            )
            market_states = sorted(
                market_states, key=lambda ms: len(ms.bars), reverse=True
            )[:max_symbols]

        if len(market_states) < 2:
            # Can't compute correlation with fewer than 2 symbols
            return CorrelationMatrix(
                symbols=[ms.symbol for ms in market_states],
                matrix={},
                high_pairs=[],
                computed_at=datetime.now(),
                threshold=self._threshold,
            )

        # Extract close prices and compute log returns per symbol
        returns_dict: dict[str, list[float]] = {}
        timestamps_dict: dict[str, list[datetime]] = {}

        for ms in market_states:
            symbol = ms.symbol or f"unknown_{len(returns_dict)}"
            bars = ms.bars[-self._window:]  # Use last N bars

            if len(bars) < 2:
                continue

            closes = [b.close for b in bars]
            times = [b.timestamp for b in bars]

            # Compute log returns
            log_returns = []
            return_times = []
            for i in range(1, len(closes)):
                if closes[i - 1] > 0:
                    ret = math.log(closes[i] / closes[i - 1])
                    log_returns.append(ret)
                    return_times.append(times[i])

            returns_dict[symbol] = log_returns
            timestamps_dict[symbol] = return_times

        # Align return series by timestamp (inner join)
        symbols = list(returns_dict.keys())
        aligned_returns = self._align_returns(symbols, returns_dict, timestamps_dict)

        # Compute pairwise correlation
        matrix: dict[tuple[str, str], float] = {}
        high_pairs: list[tuple[str, str, float]] = []

        for i in range(len(symbols)):
            for j in range(i + 1, len(symbols)):
                sym_a = symbols[i]
                sym_b = symbols[j]

                ret_a = aligned_returns.get(sym_a, [])
                ret_b = aligned_returns.get(sym_b, [])

                if len(ret_a) < self._min_overlapping or len(ret_b) < self._min_overlapping:
                    # Insufficient data — correlation unknown
                    corr = 0.0
                else:
                    corr = self._pearson_correlation(ret_a, ret_b)

                matrix[(sym_a, sym_b)] = corr

                if abs(corr) > self._threshold:
                    high_pairs.append((sym_a, sym_b, corr))

        logger.info(
            "Correlation matrix computed: %d symbols, %d pairs, %d high pairs",
            len(symbols), len(matrix), len(high_pairs),
        )

        return CorrelationMatrix(
            symbols=symbols,
            matrix=matrix,
            high_pairs=high_pairs,
            computed_at=datetime.now(),
            threshold=self._threshold,
        )

    def _align_returns(
        self,
        symbols: list[str],
        returns_dict: dict[str, list[float]],
        timestamps_dict: dict[str, list[datetime]],
    ) -> dict[str, list[float]]:
        """Align return series by timestamp (inner join).

        Only keeps timestamps present in all symbol series.
        """
        if len(symbols) < 2:
            return returns_dict

        # Find common timestamps
        common_times = set(timestamps_dict[symbols[0]])
        for sym in symbols[1:]:
            common_times &= set(timestamps_dict[sym])

        if not common_times:
            # No overlapping timestamps — return empty
            return {sym: [] for sym in symbols}

        # Extract aligned returns
        aligned: dict[str, list[float]] = {}
        for sym in symbols:
            times = timestamps_dict[sym]
            rets = returns_dict[sym]
            sym_aligned = []
            for t, r in zip(times, rets):
                if t in common_times:
                    sym_aligned.append(r)
            aligned[sym] = sym_aligned

        return aligned

    def _pearson_correlation(self, x: list[float], y: list[float]) -> float:
        """Compute Pearson correlation coefficient between two series.

        Returns 0.0 if series are empty or have zero variance.
        """
        n = min(len(x), len(y))
        if n < 2:
            return 0.0

        x_arr = np.array(x[:n])
        y_arr = np.array(y[:n])

        # Compute means
        mean_x = np.mean(x_arr)
        mean_y = np.mean(y_arr)

        # Compute deviations
        dx = x_arr - mean_x
        dy = y_arr - mean_y

        # Compute correlation
        numerator = np.sum(dx * dy)
        denominator = np.sqrt(np.sum(dx ** 2) * np.sum(dy ** 2))

        if denominator == 0:
            return 0.0

        return float(numerator / denominator)
