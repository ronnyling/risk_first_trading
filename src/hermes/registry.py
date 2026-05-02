"""AgentRegistry - manages Hermes v2 market agents."""

from __future__ import annotations

import logging
from typing import Sequence

from src.hermes.agents.base import MarketAgent, MarketState, AgentOutput

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Manages registered market agents for Hermes v2.

    Responsibilities:
        - Register/deregister agents
        - Retrieve agents by name or domain
        - Run all agents against a MarketState
    """

    def __init__(self) -> None:
        self._agents: dict[str, MarketAgent] = {}

    def register(self, agent: MarketAgent) -> None:
        """Register an agent. Raises ValueError if name already registered."""
        if agent.name in self._agents:
            raise ValueError(f"Agent '{agent.name}' already registered")
        self._agents[agent.name] = agent
        logger.info("Registered agent: %s (%s)", agent.name, agent.domain)

    def deregister(self, name: str) -> MarketAgent:
        """Remove and return an agent by name."""
        if name not in self._agents:
            raise KeyError(f"Agent '{name}' not registered")
        agent = self._agents.pop(name)
        logger.info("Deregistered agent: %s", name)
        return agent

    def get(self, name: str) -> MarketAgent:
        """Get an agent by name."""
        if name not in self._agents:
            raise KeyError(f"Agent '{name}' not registered")
        return self._agents[name]

    @property
    def agent_names(self) -> list[str]:
        """List of registered agent names."""
        return list(self._agents.keys())

    @property
    def agent_count(self) -> int:
        return len(self._agents)

    def run_all(self, market_state: MarketState) -> list[AgentOutput]:
        """Run all registered agents against the given market state.

        Returns list of AgentOutput in registration order.
        """
        outputs: list[AgentOutput] = []
        for agent in self._agents.values():
            output = agent.run(market_state)
            outputs.append(output)
        return outputs
