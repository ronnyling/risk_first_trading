"""3-stage drawdown-aware risk state machine.

Stages:
    GROWTH:     0-5% drawdown   → full alpha expression
    PROTECTIVE: 5-10% drawdown  → reduced sizing, quality filter
    SURVIVAL:   >10% drawdown   → MR-only, minimal sizing

Risk formula:
    TotalRisk = BaseRisk × AlignmentMultiplier × DrawdownMultiplier

Boundary precision: >= for threshold checks (exactly 5.00% = Protective,
exactly 10.00% = Survival).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.policy.strategy_family_policy import StrategyFamily

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DrawdownState:
    """Current state of the drawdown ladder."""
    stage: str                        # "GROWTH" | "PROTECTIVE" | "SURVIVAL"
    drawdown_pct: float               # current drawdown as fraction [0.0, 1.0)
    size_multiplier: float            # [0.0, 1.0]
    allowed_families: frozenset[str]  # family names allowed in this stage
    confidence_filter: float          # minimum confidence threshold [0.0, 1.0]
    reasoning: str


@dataclass(frozen=True)
class DrawdownProfile:
    """Immutable drawdown ladder configuration for a risk appetite profile."""
    growth_threshold: float
    protective_threshold: float
    growth_multiplier: float
    protective_multiplier_min: float
    protective_multiplier_max: float
    survival_multiplier: float
    confidence_filter_growth: float
    confidence_filter_protective: float
    confidence_filter_survival: float
    allowed_families_growth: frozenset[str] = field(default_factory=lambda: frozenset({
        StrategyFamily.STRUCTURAL_FRACTAL.value,
        StrategyFamily.MEAN_REVERSION.value,
        StrategyFamily.LIQUIDITY_SMC.value,
    }))
    allowed_families_protective: frozenset[str] = field(default_factory=lambda: frozenset({
        StrategyFamily.STRUCTURAL_FRACTAL.value,
        StrategyFamily.MEAN_REVERSION.value,
    }))
    allowed_families_survival: frozenset[str] = field(default_factory=lambda: frozenset({
        StrategyFamily.MEAN_REVERSION.value,
    }))


# Default profile matching the original 2-band system's intent
_DEFAULT_PROFILE = DrawdownProfile(
    growth_threshold=0.05,
    protective_threshold=0.10,
    growth_multiplier=1.0,
    protective_multiplier_min=0.5,
    protective_multiplier_max=0.7,
    survival_multiplier=0.2,
    confidence_filter_growth=0.0,
    confidence_filter_protective=0.6,
    confidence_filter_survival=0.8,
    allowed_families_growth=frozenset({
        StrategyFamily.STRUCTURAL_FRACTAL.value,
        StrategyFamily.MEAN_REVERSION.value,
        StrategyFamily.LIQUIDITY_SMC.value,
    }),
    allowed_families_protective=frozenset({
        StrategyFamily.STRUCTURAL_FRACTAL.value,
        StrategyFamily.MEAN_REVERSION.value,
    }),
    allowed_families_survival=frozenset({StrategyFamily.MEAN_REVERSION.value}),
)


def drawdown_profile_from_dict(data: dict[str, Any]) -> DrawdownProfile:
    """Construct a DrawdownProfile from a raw dict (e.g., from RISK_PROFILES)."""
    # Normalize family lists to frozensets
    families = data.get("families", {})
    fam_growth = frozenset(families.get("growth", [
        StrategyFamily.STRUCTURAL_FRACTAL.value,
        StrategyFamily.MEAN_REVERSION.value,
        StrategyFamily.LIQUIDITY_SMC.value,
    ]))
    fam_protective = frozenset(families.get("protective", [
        StrategyFamily.STRUCTURAL_FRACTAL.value,
        StrategyFamily.MEAN_REVERSION.value,
    ]))
    fam_survival = frozenset(families.get("survival", [
        StrategyFamily.MEAN_REVERSION.value,
    ]))

    mult_range = data.get("protective_multiplier_range", (0.5, 0.7))
    if isinstance(mult_range, (list, tuple)) and len(mult_range) == 2:
        prot_min, prot_max = float(mult_range[0]), float(mult_range[1])
    else:
        prot_min, prot_max = 0.5, 0.7

    return DrawdownProfile(
        growth_threshold=data.get("growth_threshold", 0.05),
        protective_threshold=data.get("protective_threshold", 0.10),
        growth_multiplier=data.get("growth_multiplier", 1.0),
        protective_multiplier_min=prot_min,
        protective_multiplier_max=prot_max,
        survival_multiplier=data.get("survival_multiplier", 0.2),
        confidence_filter_growth=data.get("confidence_filter_growth", 0.0),
        confidence_filter_protective=data.get("confidence_filter_protective", 0.6),
        confidence_filter_survival=data.get("confidence_filter_survival", 0.8),
        allowed_families_growth=fam_growth,
        allowed_families_protective=fam_protective,
        allowed_families_survival=fam_survival,
    )


class DrawdownLadder:
    """3-stage drawdown-aware risk state machine.

    Each stage constrains: size multiplier, allowed families, confidence filter.

    Usage:
        ladder = DrawdownLadder()
        state = ladder.evaluate(current_drawdown=0.03)
        # state.stage == "GROWTH"
        # state.size_multiplier == 1.0

        risk = ladder.compute_total_risk(
            base_risk=0.01,
            alignment_multiplier=1.0,
            drawdown_multiplier=state.size_multiplier,
        )
    """

    def __init__(self, profile: DrawdownProfile | None = None) -> None:
        self._profile = profile or _DEFAULT_PROFILE

    @classmethod
    def from_profile(cls, data: dict[str, Any]) -> DrawdownLadder:
        """Create a ladder from a raw profile dict (e.g., from RISK_PROFILES)."""
        return cls(profile=drawdown_profile_from_dict(data))

    @property
    def profile(self) -> DrawdownProfile:
        return self._profile

    def evaluate(
        self,
        current_drawdown: float,
        confidence: float = 0.0,
    ) -> DrawdownState:
        """Evaluate current drawdown and return state with multipliers.

        Args:
            current_drawdown: Fraction of peak equity lost (0.0 = at peak).
            confidence: Signal confidence [0.0, 1.0]. Used for protective
                stage multiplier interpolation.

        Returns:
            DrawdownState with stage, multiplier, allowed families, etc.
        """
        p = self._profile

        # --- GROWTH: 0 to growth_threshold (exclusive) ---
        if current_drawdown < p.growth_threshold:
            return DrawdownState(
                stage="GROWTH",
                drawdown_pct=current_drawdown,
                size_multiplier=p.growth_multiplier,
                allowed_families=p.allowed_families_growth,
                confidence_filter=p.confidence_filter_growth,
                reasoning=(
                    f"DD={current_drawdown:.4f} < {p.growth_threshold:.4f} → GROWTH. "
                    f"Full alpha expression."
                ),
            )

        # --- PROTECTIVE: growth_threshold <= dd < protective_threshold ---
        if current_drawdown < p.protective_threshold:
            # Interpolate protective multiplier based on confidence
            # Higher confidence → higher multiplier (closer to max)
            t = max(0.0, min(1.0, confidence))  # clamp
            prot_mult = (
                p.protective_multiplier_min
                + t * (p.protective_multiplier_max - p.protective_multiplier_min)
            )
            return DrawdownState(
                stage="PROTECTIVE",
                drawdown_pct=current_drawdown,
                size_multiplier=prot_mult,
                allowed_families=p.allowed_families_protective,
                confidence_filter=p.confidence_filter_protective,
                reasoning=(
                    f"DD={current_drawdown:.4f} ∈ [{p.growth_threshold:.4f}, "
                    f"{p.protective_threshold:.4f}) → PROTECTIVE. "
                    f"Multiplier={prot_mult:.4f}, conf={confidence:.2f}."
                ),
            )

        # --- SURVIVAL: dd >= protective_threshold ---
        return DrawdownState(
            stage="SURVIVAL",
            drawdown_pct=current_drawdown,
            size_multiplier=p.survival_multiplier,
            allowed_families=p.allowed_families_survival,
            confidence_filter=p.confidence_filter_survival,
            reasoning=(
                f"DD={current_drawdown:.4f} >= {p.protective_threshold:.4f} → SURVIVAL. "
                f"MR-only, minimal sizing."
            ),
        )

    def compute_total_risk(
        self,
        base_risk: float,
        alignment_multiplier: float,
        drawdown_multiplier: float,
    ) -> float:
        """TotalRisk = BaseRisk × AlignmentMultiplier × DrawdownMultiplier.

        Args:
            base_risk: From profile (e.g., 0.005 for balanced).
            alignment_multiplier: From MTF alignment (1.0 aligned, 0.5 misaligned).
            drawdown_multiplier: From DrawdownState.size_multiplier.

        Returns:
            Total risk fraction per trade.
        """
        return base_risk * alignment_multiplier * drawdown_multiplier
