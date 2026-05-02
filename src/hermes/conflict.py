"""ConflictResolver - implements HCR-001 deterministic resolution logic."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConflictInput:
    """Inputs to the conflict resolution process."""
    composite_score: float
    total_confidence: float
    score_dispersion: float
    previous_composite_score: float
    previous_regime: str
    previous_risk_directive: str
    previous_allowed_family: str | None


@dataclass(frozen=True)
class ConflictOutput:
    """Deterministic output from conflict resolution."""
    regime: str
    risk_directive: str
    allowed_strategy_family: str | None
    reasoning: str
    resolution_path: str  # which rule fired: R-01, R-02, R-03, or R-04


# --- HCR-001 thresholds ---
DISAGREEMENT_THRESHOLD = 0.60   # CR-01: score_dispersion
LOW_CONFIDENCE_THRESHOLD = 0.50  # CR-02: total_confidence
FLIP_RISK_THRESHOLD = 0.80       # CR-03: composite_score jump

# Regime classification thresholds (score -> regime)
TRENDING_THRESHOLD = 0.3
RANGING_UPPER = 0.3
RANGING_LOWER = -0.3


def _classify_regime(composite_score: float) -> str:
    """Map composite_score to regime name."""
    if composite_score >= TRENDING_THRESHOLD:
        return "trending"
    elif composite_score <= RANGING_LOWER:
        return "trending"  # strongly negative = trending (down)
    else:
        return "ranging"


def _map_regime_to_family(regime: str) -> str | None:
    """Map regime to allowed strategy family (StrategyFamily.value strings)."""
    mapping = {
        "trending": "structural_fractal",
        "ranging": "mean_reversion",
        "volatile": None,
    }
    return mapping.get(regime)


class ConflictResolver:
    """Implements HCR-001 conflict resolution logic.

    Resolution hierarchy (strict order):
        1. Integrity (R-01): disagreement -> CASH
        2. Uncertainty (R-02): low confidence -> SCALE_DOWN
        3. Continuation (R-03): unstable transition -> SCALE_DOWN
        4. Opportunity (R-04): normal operation -> classify normally
    """

    def resolve(self, inputs: ConflictInput) -> ConflictOutput:
        """Apply HCR-001 rules in strict priority order.

        Returns a single ConflictOutput. Deterministic.
        """
        # R-01: Integrity First — agent disagreement
        if inputs.score_dispersion > DISAGREEMENT_THRESHOLD:
            return ConflictOutput(
                regime="INDETERMINATE",
                risk_directive="CASH",
                allowed_strategy_family=None,
                reasoning=(
                    f"CR-01: score_dispersion={inputs.score_dispersion:.3f} "
                    f"> {DISAGREEMENT_THRESHOLD}. Agents disagree."
                ),
                resolution_path="R-01",
            )

        # R-02: Low Confidence
        if inputs.total_confidence < LOW_CONFIDENCE_THRESHOLD:
            return ConflictOutput(
                regime=inputs.previous_regime,
                risk_directive="SCALE_DOWN",
                allowed_strategy_family=inputs.previous_allowed_family,
                reasoning=(
                    f"CR-02: total_confidence={inputs.total_confidence:.3f} "
                    f"< {LOW_CONFIDENCE_THRESHOLD}. Signals untrustworthy."
                ),
                resolution_path="R-02",
            )

        # R-03: Unstable Transitions — regime flip risk
        score_jump = abs(
            inputs.composite_score - inputs.previous_composite_score
        )
        if score_jump >= FLIP_RISK_THRESHOLD:
            return ConflictOutput(
                regime=inputs.previous_regime,
                risk_directive="SCALE_DOWN",
                allowed_strategy_family=inputs.previous_allowed_family,
                reasoning=(
                    f"CR-03: score_jump={score_jump:.3f} "
                    f">= {FLIP_RISK_THRESHOLD}. Regime flip risk."
                ),
                resolution_path="R-03",
            )

        # R-04: Normal Operation
        regime = _classify_regime(inputs.composite_score)
        family = _map_regime_to_family(regime)

        return ConflictOutput(
            regime=regime,
            risk_directive="FULL",
            allowed_strategy_family=family,
            reasoning=(
                f"R-04: Normal. composite={inputs.composite_score:.3f}, "
                f"regime={regime}, family={family}"
            ),
            resolution_path="R-04",
        )