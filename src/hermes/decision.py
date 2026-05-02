"""HermesDecision — immutable canonical output from Hermes v2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class HermesDecision:
    """Immutable output from one Hermes v2 evaluation cycle.

    This is the single object emitted per cycle. It is:
    - immutable (frozen dataclass)
    - audit-logged
    - EA-serializable

    Consumers: engine, persistence, allocation bridge.
    Strategies never see this directly.
    """
    # From conflict resolution (HCR-001)
    regime: str                        # resolved regime name
    composite_score: float             # [-1.0, +1.0]
    confidence: float                  # [0.0, 1.0]
    risk_directive: str                # "FULL" | "SCALE_DOWN" | "CASH"
    allowed_strategy_family: str | None  # "trend" | "mean_reversion" | "breakout" | None

    # From position sizing (HPS-001)
    per_trade_risk: float              # fraction of equity per trade
    portfolio_risk: float              # total portfolio risk budget

    # Metadata
    timestamp: datetime                # when this decision was made
    agent_scores: dict[str, float]     # individual agent scores for audit
    agent_confidences: dict[str, float]  # individual agent confidences
    reasoning: str = ""                # human-readable resolution path

    def __post_init__(self) -> None:
        if not (-1.0 <= self.composite_score <= 1.0):
            raise ValueError(f"composite_score {self.composite_score} not in [-1.0, +1.0]")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence {self.confidence} not in [0.0, 1.0]")
        if self.risk_directive not in ("FULL", "SCALE_DOWN", "CASH"):
            raise ValueError(f"Invalid risk_directive: {self.risk_directive}")
        if self.per_trade_risk < 0.0:
            raise ValueError(f"per_trade_risk {self.per_trade_risk} is negative")
        if self.portfolio_risk < 0.0:
            raise ValueError(f"portfolio_risk {self.portfolio_risk} is negative")