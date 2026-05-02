"""Data models for persisted trading state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class StrategyState(Enum):
    """Lifecycle state for a strategy (SPG-001)."""
    CANDIDATE = "candidate"
    APPROVED = "approved"
    PROBATIONARY = "probationary"
    ACTIVE = "active"
    DEGRADED = "degraded"
    SUSPENDED = "suspended"
    RETIRED = "retired"


@dataclass
class FillRecord:
    """Persisted fill record."""
    fill_id: int | None = None
    order_id: str = ""
    symbol: str = ""
    side: str = ""  # "buy" or "sell"
    quantity: float = 0.0
    fill_price: float = 0.0
    commission: float = 0.0
    pnl: float = 0.0
    strategy_id: str = ""
    timestamp: str = ""  # ISO format
    bar_index: int = 0


@dataclass
class AllocationRecord:
    """Persisted Hermes allocation decision."""
    allocation_id: int | None = None
    bar_index: int = 0
    timestamp: str = ""
    regime: str = ""
    strategy_id: str = ""
    active: bool = False
    weight: float = 0.0
    reason: str = ""
    portfolio_value: float = 0.0


@dataclass
class RegimeRecord:
    """Persisted regime detection event."""
    regime_id: int | None = None
    bar_index: int = 0
    timestamp: str = ""
    regime: str = ""


@dataclass
class VetoRecord:
    """Persisted risk veto event."""
    veto_id: int | None = None
    bar_index: int = 0
    timestamp: str = ""
    order_id: str = ""
    strategy_id: str = ""
    reason: str = ""


@dataclass
class StrategyStateRecord:
    """Persisted strategy lifecycle state."""
    strategy_id: str = ""
    state: str = StrategyState.ACTIVE.value
    activated_at: str = ""
    deactivated_at: str = ""
    total_fills: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    notes: str = ""