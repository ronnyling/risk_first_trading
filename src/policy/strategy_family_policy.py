"""Strategy Family Policy — maps HermesDecision → allowed strategy families.

This is a pure-function layer. It:
- Reads only HermesDecision fields
- Returns allowed strategy families + risk multiplier passthrough
- Never inspects price, indicators, orders, or market data

CONSTRAINTS (Phase 10):
- Hermes is single-timeframe only (no MTF alignment)
- CHAOS_OPTIONAL is a permission gate, not a tactic
- Returns allowed set; downstream selects at most one per asset
- No tactical rules (ATR multipliers, stop distances, etc.)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from src.hermes.decision import HermesDecision

logger = logging.getLogger(__name__)


class StrategyFamily(Enum):
    """Canonical strategy families — policy-only, not executable."""

    STRUCTURAL_FRACTAL = "structural_fractal"
    MEAN_REVERSION = "mean_reversion"
    LIQUIDITY_SMC = "liquidity_smc"
    CHAOS_OPTIONAL = "chaos_optional"


@dataclass(frozen=True)
class PolicyOutput:
    """Immutable output from Strategy Family Policy evaluation.

    Attributes:
        allowed_families: Families permitted to operate this bar.
            Downstream orchestration selects at most one per asset.
        risk_multiplier: Passthrough from Hermes (per_trade_risk).
            Policy does not modify this value.
    """

    allowed_families: frozenset[StrategyFamily]
    risk_multiplier: float


class StrategyFamilyPolicy:
    """Pure function: HermesDecision → allowed strategy families.

    Regime mapping (Option A — no new enums):
      trending  → DISCOVERY equivalent   → STRUCTURAL_FRACTAL
      ranging   → BALANCE equivalent     → MEAN_REVERSION
      volatile  → Exhaustion equivalent  → LIQUIDITY_SMC, CHAOS_OPTIONAL
      unknown   → CASH equivalent        → empty set

    CASH directive always → empty set regardless of regime.
    """

    # (regime, risk_directive) → allowed families
    PERMISSION_MATRIX: dict[tuple[str, str], frozenset[StrategyFamily]] = {
        # trending → STRUCTURAL_FRACTAL (trend-following)
        ("trending", "FULL"): frozenset({StrategyFamily.STRUCTURAL_FRACTAL}),
        ("trending", "SCALE_DOWN"): frozenset({StrategyFamily.STRUCTURAL_FRACTAL}),
        # ranging → MEAN_REVERSION (range-bound)
        ("ranging", "FULL"): frozenset({StrategyFamily.MEAN_REVERSION}),
        ("ranging", "SCALE_DOWN"): frozenset({StrategyFamily.MEAN_REVERSION}),
        # volatile → LIQUIDITY_SMC + CHAOS_OPTIONAL (permission gate only)
        ("volatile", "FULL"): frozenset(
            {StrategyFamily.LIQUIDITY_SMC, StrategyFamily.CHAOS_OPTIONAL}
        ),
        ("volatile", "SCALE_DOWN"): frozenset(
            {StrategyFamily.LIQUIDITY_SMC, StrategyFamily.CHAOS_OPTIONAL}
        ),
        # CASH → nothing (all regimes)
        ("trending", "CASH"): frozenset(),
        ("ranging", "CASH"): frozenset(),
        ("volatile", "CASH"): frozenset(),
        # unknown → nothing (all directives)
        ("unknown", "FULL"): frozenset(),
        ("unknown", "SCALE_DOWN"): frozenset(),
        ("unknown", "CASH"): frozenset(),
    }

    _DEFAULT_FAMILIES: frozenset[StrategyFamily] = frozenset()

    def evaluate(self, decision: HermesDecision) -> PolicyOutput:
        """Map a Hermes decision to allowed strategy families.

        Args:
            decision: Immutable HermesDecision from the current evaluation cycle.

        Returns:
            PolicyOutput with allowed families and risk multiplier passthrough.
        """
        key = (decision.regime, decision.risk_directive)
        families = self.PERMISSION_MATRIX.get(key, self._DEFAULT_FAMILIES)

        if families:
            logger.debug(
                "Policy: regime=%s directive=%s -> families=%s",
                decision.regime,
                decision.risk_directive,
                [f.value for f in families],
            )
        else:
            logger.debug(
                "Policy: regime=%s directive=%s -> no families allowed",
                decision.regime,
                decision.risk_directive,
            )

        return PolicyOutput(
            allowed_families=families,
            risk_multiplier=decision.per_trade_risk,
        )