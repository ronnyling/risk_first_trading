"""Performance metrics tracker for strategies and portfolio."""

from __future__ import annotations

import math
import logging
from src.core.types import Fill, StrategyMetrics

logger = logging.getLogger(__name__)


class MetricsTracker:
    """Tracks per-strategy and portfolio-level performance metrics.

    Hermes uses these metrics to make allocation decisions.
    """

    def __init__(self) -> None:
        self._strategy_metrics: dict[str, StrategyMetrics] = {}
        self._strategy_pnl_history: dict[str, list[float]] = {}
        self._strategy_peak: dict[str, float] = {}

    def register_strategy(self, strategy_id: str) -> None:
        if strategy_id not in self._strategy_metrics:
            self._strategy_metrics[strategy_id] = StrategyMetrics()
            self._strategy_pnl_history[strategy_id] = []
            self._strategy_peak[strategy_id] = 0.0

    def record_fill(self, fill: Fill) -> None:
        """Record a fill and update metrics for the strategy."""
        sid = fill.strategy_id
        if sid not in self._strategy_metrics:
            self.register_strategy(sid)

        m = self._strategy_metrics[sid]
        m.total_trades += 1
        m.total_pnl += (fill.pnl - fill.commission)

        self._strategy_pnl_history[sid].append(fill.pnl)

        if fill.pnl > 0:
            m.winning_trades += 1
        elif fill.pnl < 0:
            m.losing_trades += 1
        m.win_rate = m.winning_trades / m.total_trades if m.total_trades else 0.0
        m.avg_trade_pnl = m.total_pnl / m.total_trades if m.total_trades else 0.0

        # Update peak and drawdown
        peak = self._strategy_peak.get(sid, 0.0)
        if m.total_pnl > peak:
            peak = m.total_pnl
            self._strategy_peak[sid] = peak

        if peak > 0:
            m.current_drawdown = (peak - m.total_pnl) / peak
            m.max_drawdown = max(m.max_drawdown, m.current_drawdown)

        # Update sharpe (simplified: annualized from trade returns)
        history = self._strategy_pnl_history[sid]
        if len(history) >= 2:
            mean_ret = sum(history) / len(history)
            variance = sum((r - mean_ret) ** 2 for r in history) / len(history)
            std_ret = math.sqrt(variance) if variance > 0 else 0.0
            m.sharpe_ratio = (mean_ret / std_ret * math.sqrt(252)) if std_ret > 0 else 0.0

    def reset_bars_since_trade(self, strategy_id: str) -> None:
        if strategy_id in self._strategy_metrics:
            self._strategy_metrics[strategy_id].bars_since_last_trade = 0

    def increment_bars_since_trade(self, strategy_id: str) -> None:
        if strategy_id in self._strategy_metrics:
            self._strategy_metrics[strategy_id].bars_since_last_trade += 1

    def get_metrics(self, strategy_id: str) -> StrategyMetrics:
        self.register_strategy(strategy_id)
        return self._strategy_metrics[strategy_id]

    def get_all_metrics(self) -> dict[str, StrategyMetrics]:
        return dict(self._strategy_metrics)