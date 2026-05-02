"""Adapter mapping Hermes v2 decisions to v1 StrategyAllocation format.

Hermes v2 produces a HermesDecision (regime, risk_directive, composite_score).
TradingEngine expects list[StrategyAllocation] from HermesAgent.

This adapter bridges the gap without modifying either interface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.hermes.agent import StrategyAllocation
from src.hermes.decision import HermesDecision
from src.strategies.base import StrategyMetadata

logger = logging.getLogger(__name__)


class HermesV2Adapter:
    """Maps HermesDecision → list[StrategyAllocation] for TradingEngine.

    Strategy family filtering:
    - If decision.allowed_strategy_family is set, only strategies in that family are active
    - If decision.allowed_strategy_family is None (CASH), all strategies are inactive

    Weight calculation:
    - FULL directive: weight = 1.0 (strategy runs at full allocation)
    - SCALE_DOWN directive: weight scaled by confidence
    - CASH directive: weight = 0.0 (all strategies inactive)
    """

    def adapt(
        self,
        decision: HermesDecision,
        strategies: list[StrategyMetadata],
    ) -> list[StrategyAllocation]:
        """Convert a Hermes v2 decision into v1-compatible allocations.

        Args:
            decision: The Hermes v2 decision output.
            strategies: Metadata for all registered strategies.

        Returns:
            List of StrategyAllocation (one per strategy).
        """
        allocations: list[StrategyAllocation] = []

        for meta in strategies:
            sid = meta.strategy_id
            # Use metadata.family for family matching (string or StrategyFamily enum)
            if meta.family is None:
                family = "unknown"
            elif hasattr(meta.family, "value"):
                family = meta.family.value  # StrategyFamily enum
            else:
                family = meta.family  # already a string

            if decision.risk_directive == "CASH":
                # All strategies inactive
                allocations.append(StrategyAllocation(
                    strategy_id=sid,
                    active=False,
                    weight=0.0,
                    reason=f"v2 CASH directive: {decision.reasoning}",
                ))
            elif decision.allowed_strategy_family is not None:
                # Family filtering: only matching family is active
                is_match = family == decision.allowed_strategy_family
                weight = self._compute_weight(decision) if is_match else 0.0
                allocations.append(StrategyAllocation(
                    strategy_id=sid,
                    active=is_match,
                    weight=weight,
                    reason=(
                        f"v2 family={decision.allowed_strategy_family}, "
                        f"match={is_match}: {decision.reasoning}"
                    ),
                ))
            else:
                # No family constraint: all active, scaled by confidence
                weight = self._compute_weight(decision)
                allocations.append(StrategyAllocation(
                    strategy_id=sid,
                    active=True,
                    weight=weight,
                    reason=f"v2 directive={decision.risk_directive}: {decision.reasoning}",
                ))

        return allocations

    def _compute_weight(self, decision: HermesDecision) -> float:
        """Compute strategy weight from decision risk_directive + confidence.

        FULL: weight = confidence (capped at 1.0)
        SCALE_DOWN: weight = confidence * 0.5 (reduced exposure)
        """
        if decision.risk_directive == "FULL":
            return min(decision.confidence, 1.0)
        elif decision.risk_directive == "SCALE_DOWN":
            return min(decision.confidence * 0.5, 0.5)
        else:
            return 0.0