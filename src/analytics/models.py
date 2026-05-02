"""Data models for analytics reports.

These are immutable, serializable report structures produced by AnalyticsEngine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from src.persistence.models import FillRecord, VetoRecord


@dataclass(frozen=True)
class SessionReport:
    """Summary report for a single engine run.

    Attributes:
        run_id: Engine run ID.
        started_at: Run start timestamp (ISO format).
        finished_at: Run finish timestamp (ISO format), or None.
        bars_processed: Number of bars processed.
        total_signals: Total signals generated.
        total_orders: Total orders submitted.
        total_fills: Total fills received.
        total_vetoes: Total orders vetoed.
        final_portfolio_value: Final portfolio value, or None.
        final_pnl: Final PnL, or None.
        fill_details: List of FillRecord for this run.
        veto_details: List of VetoRecord for this run.
    """
    run_id: int = 0
    started_at: str = ""
    finished_at: str | None = None
    bars_processed: int = 0
    total_signals: int = 0
    total_orders: int = 0
    total_fills: int = 0
    total_vetoes: int = 0
    final_portfolio_value: float | None = None
    final_pnl: float | None = None
    fill_details: list = field(default_factory=list)
    veto_details: list = field(default_factory=list)


@dataclass(frozen=True)
class StrategyReport:
    """Performance report for a single strategy.

    Attributes:
        strategy_id: Strategy identifier.
        total_trades: Total fills (trades) for this strategy.
        winning_trades: Trades with positive PnL.
        losing_trades: Trades with negative PnL.
        total_pnl: Sum of PnL across all trades.
        win_rate: winning_trades / total_trades.
        avg_trade_pnl: Average PnL per trade.
        max_drawdown: Maximum drawdown observed.
        fill_history: List of FillRecord for this strategy.
    """
    strategy_id: str = "ALL"
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    avg_trade_pnl: float = 0.0
    max_drawdown: float = 0.0
    fill_history: list = field(default_factory=list)


@dataclass(frozen=True)
class RiskReport:
    """Risk utilization report.

    Attributes:
        total_drawdown_events: Number of veto events.
        max_drawdown_observed: Maximum drawdown percentage observed.
        avg_drawdown: Average drawdown across all fills.
        risk_budget_utilization: Fraction of risk budget used.
        veto_rate: vetoes / (fills + vetoes).
        veto_history: List of VetoRecord.
    """
    total_drawdown_events: int = 0
    max_drawdown_observed: float = 0.0
    avg_drawdown: float = 0.0
    risk_budget_utilization: float = 0.0
    veto_rate: float = 0.0
    veto_history: list = field(default_factory=list)


@dataclass(frozen=True)
class HermesReport:
    """Hermes decision quality and outcome tracking report.

    Attributes:
        total_runs: Total Hermes runs recorded.
        total_decisions: Total per-symbol decisions.
        directive_distribution: Count of each risk_directive.
        regime_distribution: Count of each regime.
        avg_confidence: Average confidence across decisions.
        high_confidence_trades: Decisions with confidence > 0.7 that led to fills.
        alert_count: Total alerts generated.
    """
    total_runs: int = 0
    total_decisions: int = 0
    directive_distribution: dict = field(default_factory=dict)
    regime_distribution: dict = field(default_factory=dict)
    avg_confidence: float = 0.0
    high_confidence_trades: int = 0
    alert_count: int = 0
