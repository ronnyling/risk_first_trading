"""Abstract MarketAgent contract and MarketState dataclass for Hermes v2."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from src.core.types import Bar, Regime


@dataclass(frozen=True)
class MarketState:
    """Immutable snapshot of market data passed to agents each cycle.

    Agents observe this — they never access strategy state, portfolio, or PnL.
    """
    bars: list[Bar]              # recent price history (last N bars)
    regime: Regime               # from RegimeDetector
    regime_confidence: float     # [0.0, 1.0]
    volatility: float | None     # annualized vol, if available
    timestamp: datetime          # current bar timestamp
    symbol: str = ""             # universe symbol (e.g. "BTC/USD", "ETH/USD")


@dataclass(frozen=True)
class AgentOutput:
    """Immutable output from a single market agent.

    score: [-1.0, +1.0] — negative = bearish, positive = bullish
    confidence: [0.0, 1.0] — how confident the agent is in its assessment
    """
    agent_name: str
    score: float
    confidence: float
    reasoning: str = ""  # optional, for audit trail

    def __post_init__(self) -> None:
        if not (-1.0 <= self.score <= 1.0):
            raise ValueError(
                f"Agent {self.agent_name}: score {self.score} not in [-1.0, +1.0]"
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"Agent {self.agent_name}: confidence {self.confidence} not in [0.0, 1.0]"
            )


class MarketAgent(ABC):
    """Abstract base for Hermes v2 market analysis agents.

    Invariants:
        - No access to other agents
        - No access to strategy PnL
        - No access to portfolio state
        - No side effects
        - Output is deterministic given the same input
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique agent identifier (e.g., 'AMT', 'Wyckoff')."""
        ...

    @property
    @abstractmethod
    def domain(self) -> str:
        """Domain description (e.g., 'Auction / Value')."""
        ...

    @abstractmethod
    def observe(self, market_state: MarketState) -> dict:
        """Extract relevant observations from market state.

        Returns an agent-specific observation dict.
        Pure function — no side effects.
        """
        ...

    @abstractmethod
    def evaluate(self, observation: dict) -> AgentOutput:
        """Produce a score and confidence from observations.

        Returns AgentOutput with score in [-1.0, +1.0] and confidence in [0.0, 1.0].
        Pure function — no side effects.
        """
        ...

    def run(self, market_state: MarketState) -> AgentOutput:
        """Full pipeline: observe then evaluate. Non-overridable."""
        observation = self.observe(market_state)
        return self.evaluate(observation)