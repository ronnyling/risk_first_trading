"""Shared data types for the Hermes trading framework."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Direction(Enum):
    FLAT = 0
    LONG = 1
    SHORT = -1


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class Regime(Enum):
    TRENDING = "trending"
    RANGING = "ranging"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


class RiskPosture(Enum):
    CONSERVATIVE = "conservative"
    NORMAL = "normal"
    REDUCED = "reduced"


@dataclass
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    strategy_id: str
    timestamp: datetime
    symbol: str
    direction: Direction
    strength: float  # 0.0-1.0
    metadata: dict = field(default_factory=dict)


@dataclass
class Order:
    order_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    symbol: str = ""
    side: OrderSide = OrderSide.BUY
    quantity: float = 0.0
    order_type: OrderType = OrderType.MARKET
    price: float | None = None
    strategy_id: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Fill:
    order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    fill_price: float
    commission: float
    timestamp: datetime
    strategy_id: str = ""
    pnl: float = 0.0


@dataclass
class Position:
    symbol: str
    quantity: float
    avg_entry_price: float
    unrealized_pnl: float
    strategy_id: str


@dataclass
class Trade:
    trade_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    symbol: str = ""
    side: OrderSide = OrderSide.BUY
    quantity: float = 0.0
    entry_price: float = 0.0
    exit_price: float = 0.0
    pnl: float = 0.0
    strategy_id: str = ""
    entry_time: datetime = field(default_factory=datetime.now)
    exit_time: datetime = field(default_factory=datetime.now)


@dataclass
class StrategyMetrics:
    """Performance metrics for a single strategy."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    avg_trade_pnl: float = 0.0
    current_drawdown: float = 0.0
    bars_since_last_trade: int = 0


@dataclass
class PortfolioState:
    """Snapshot of the entire portfolio."""
    cash: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    total_value: float = 0.0
    total_pnl: float = 0.0
    drawdown: float = 0.0
    peak_value: float = 0.0
    leverage: float = 0.0
    exposure_pct: float = 0.0