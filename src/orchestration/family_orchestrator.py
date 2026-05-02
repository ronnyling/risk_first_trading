"""Family Orchestrator — enforces family exclusivity per asset per bar.

Given a set of allowed families (from Hermes/Policy) and available strategies,
selects exactly one strategy to execute on each bar. At most one family may
be active per asset per bar.

Priority order (fixed, no tuning):
  STRUCTURAL_FRACTAL > MEAN_REVERSION > LIQUIDITY_SMC > CHAOS_OPTIONAL
"""

from __future__ import annotations

from dataclasses import dataclass

from src.policy.strategy_family_policy import StrategyFamily
from src.strategies.base import Strategy


# Fixed priority order — structural dominates, chaos is fallback
FAMILY_PRIORITY: list[StrategyFamily] = [
    StrategyFamily.STRUCTURAL_FRACTAL,
    StrategyFamily.MEAN_REVERSION,
    StrategyFamily.LIQUIDITY_SMC,
    StrategyFamily.CHAOS_OPTIONAL,
]


@dataclass(frozen=True)
class OrchestrationResult:
    """Result of family selection for one bar."""
    selected_family: StrategyFamily | None
    selected_strategy_name: str | None
    allowed_families: frozenset[StrategyFamily]
    reason: str  # "priority_match", "no_allowed_families", "no_matching_strategy"


def select_strategy(
    allowed_families: frozenset[StrategyFamily],
    strategies: dict[str, Strategy],
) -> OrchestrationResult:
    """Select one strategy from allowed families by priority.

    Args:
        allowed_families: Families permitted by Hermes + Policy this bar.
        strategies: Available strategies keyed by strategy_id.

    Returns:
        OrchestrationResult with selected strategy (or None) and reason.
    """
    if not allowed_families:
        return OrchestrationResult(
            selected_family=None,
            selected_strategy_name=None,
            allowed_families=allowed_families,
            reason="no_allowed_families",
        )

    # Walk priority order, find first family that:
    # 1. Is in allowed_families
    # 2. Has a matching strategy (via metadata.family string matching family.value)
    for family in FAMILY_PRIORITY:
        if family not in allowed_families:
            continue
        for strat in strategies.values():
            strat_family = strat.metadata.family
            if strat_family == family.value:
                return OrchestrationResult(
                    selected_family=family,
                    selected_strategy_name=strat.metadata.strategy_id,
                    allowed_families=allowed_families,
                    reason="priority_match",
                )

    # Families allowed but no matching strategy loaded
    return OrchestrationResult(
        selected_family=None,
        selected_strategy_name=None,
        allowed_families=allowed_families,
        reason="no_matching_strategy",
    )