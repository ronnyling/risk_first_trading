"""Canonical indicator ↔ strategy family mapping (Single Source of Truth).

This mapping is authoritative. Every chart in the system must render
indicators from this definition. Any violation is a bug.

Phase F.1 — Visualization & Human Control Plane.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────


class IndicatorRole(Enum):
    """Role of an indicator within a strategy family's visual spec."""

    REQUIRED = "REQUIRED"  # Must always appear on charts
    OPTIONAL = "OPTIONAL"  # May appear if available
    FORBIDDEN = "FORBIDDEN"  # Must never appear


class AnnotationType(Enum):
    """Type of decision annotation overlay."""

    ENTRY_ZONE = "entry_zone"  # Shaded band, not a line
    INVALIDATION_ZONE = "invalidation_zone"  # Region where thesis breaks
    EXIT_CRITERIA = "exit_criteria"  # Logical condition, not fixed price
    CONFIDENCE = "confidence"  # Score label
    DIRECTIVE = "directive"  # SCALE_IN, HOLD, CASH, etc.


# ──────────────────────────────────────────────────────
# Data Models
# ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class IndicatorSpec:
    """Specification for a single indicator within a family.

    Attributes:
        name: Machine identifier (e.g. "sma_fast", "rsi").
        role: REQUIRED, OPTIONAL, or FORBIDDEN.
        display_name: Human label for chart legend.
        source: Which module computes the indicator.
    """

    name: str
    role: IndicatorRole
    display_name: str
    source: str


@dataclass(frozen=True)
class AnnotationSpec:
    """Specification for a decision annotation overlay.

    Attributes:
        annotation_type: Type of annotation (entry, invalidation, etc.).
        display_name: Human label for the annotation.
        rendering: How to render ("shaded_band", "dashed_line", "label_only").
    """

    annotation_type: AnnotationType
    display_name: str
    rendering: str


@dataclass(frozen=True)
class StrategyFamilyVisualSpec:
    """Complete visual specification for one strategy family.

    Attributes:
        family_id: Canonical family identifier.
        display_name: Human-readable family name.
        indicators: All indicator specifications for this family.
        annotations: All annotation specifications for this family.
        forbidden_indicators: Names that must never appear on charts.
    """

    family_id: str
    display_name: str
    indicators: list[IndicatorSpec] = field(default_factory=list)
    annotations: list[AnnotationSpec] = field(default_factory=list)
    forbidden_indicators: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────
# Canonical Mapping
# ──────────────────────────────────────────────────────

# Common annotation specs reused across families
_ENTRY_ZONE_ANNOTATION = AnnotationSpec(
    annotation_type=AnnotationType.ENTRY_ZONE,
    display_name="Entry Zone",
    rendering="shaded_band",
)

_INVALIDATION_ANNOTATION = AnnotationSpec(
    annotation_type=AnnotationType.INVALIDATION_ZONE,
    display_name="Invalidation",
    rendering="shaded_band",
)

_EXIT_CRITERIA_ANNOTATION = AnnotationSpec(
    annotation_type=AnnotationType.EXIT_CRITERIA,
    display_name="Exit Criteria",
    rendering="label_only",
)

_CONFIDENCE_ANNOTATION = AnnotationSpec(
    annotation_type=AnnotationType.CONFIDENCE,
    display_name="Confidence",
    rendering="label_only",
)

_DIRECTIVE_ANNOTATION = AnnotationSpec(
    annotation_type=AnnotationType.DIRECTIVE,
    display_name="Directive",
    rendering="label_only",
)

_COMMON_ANNOTATIONS = [
    _ENTRY_ZONE_ANNOTATION,
    _INVALIDATION_ANNOTATION,
    _EXIT_CRITERIA_ANNOTATION,
    _CONFIDENCE_ANNOTATION,
    _DIRECTIVE_ANNOTATION,
]


FAMILY_VISUAL_SPECS: dict[str, StrategyFamilyVisualSpec] = {
    # ── Structural Fractal ──────────────────────────
    "structural_fractal": StrategyFamilyVisualSpec(
        family_id="structural_fractal",
        display_name="Structural Fractal",
        indicators=[
            IndicatorSpec(
                name="price_candles",
                role=IndicatorRole.REQUIRED,
                display_name="Price (OHLC)",
                source="core.types.Bar",
            ),
            IndicatorSpec(
                name="ema_fast",
                role=IndicatorRole.REQUIRED,
                display_name="EMA Fast (20)",
                source="pullback_continuation._compute_ema",
            ),
            IndicatorSpec(
                name="ema_slow",
                role=IndicatorRole.REQUIRED,
                display_name="EMA Slow (50)",
                source="pullback_continuation._compute_ema",
            ),
            IndicatorSpec(
                name="sma_fast",
                role=IndicatorRole.REQUIRED,
                display_name="SMA Fast (10)",
                source="sma_crossover._sma",
            ),
            IndicatorSpec(
                name="sma_slow",
                role=IndicatorRole.REQUIRED,
                display_name="SMA Slow (20)",
                source="sma_crossover._sma",
            ),
            IndicatorSpec(
                name="market_structure",
                role=IndicatorRole.REQUIRED,
                display_name="Market Structure",
                source="pullback_continuation (derived from EMA alignment)",
            ),
            IndicatorSpec(
                name="pivot_high",
                role=IndicatorRole.OPTIONAL,
                display_name="Pivot High",
                source="sma_crossover._check_pivots",
            ),
            IndicatorSpec(
                name="pivot_low",
                role=IndicatorRole.OPTIONAL,
                display_name="Pivot Low",
                source="sma_crossover._check_pivots",
            ),
            IndicatorSpec(
                name="ichimoku_cloud",
                role=IndicatorRole.OPTIONAL,
                display_name="Ichimoku Cloud",
                source="hermes.agents.IchimokuAgent",
            ),
        ],
        annotations=_COMMON_ANNOTATIONS,
        forbidden_indicators=["vwap", "mean_reversion_bands", "rsi", "bollinger_bands"],
    ),
    # ── Mean Reversion ──────────────────────────────
    "mean_reversion": StrategyFamilyVisualSpec(
        family_id="mean_reversion",
        display_name="Mean Reversion",
        indicators=[
            IndicatorSpec(
                name="price_candles",
                role=IndicatorRole.REQUIRED,
                display_name="Price (OHLC)",
                source="core.types.Bar",
            ),
            IndicatorSpec(
                name="rsi",
                role=IndicatorRole.REQUIRED,
                display_name="RSI (14)",
                source="rsi_mean_reversion._rsi / vwap_reversion._compute_rsi",
            ),
            IndicatorSpec(
                name="vwap",
                role=IndicatorRole.REQUIRED,
                display_name="VWAP",
                source="vwap_reversion._compute_vwap",
            ),
            IndicatorSpec(
                name="value_area",
                role=IndicatorRole.REQUIRED,
                display_name="Value Area (VAH / VAL / POC)",
                source="amt_value_reversion._compute_value_area",
            ),
            IndicatorSpec(
                name="bollinger_bands",
                role=IndicatorRole.OPTIONAL,
                display_name="Bollinger Bands (20, 2)",
                source="hermes.agents.VolatilityAgent (BB width)",
            ),
            IndicatorSpec(
                name="atr",
                role=IndicatorRole.OPTIONAL,
                display_name="ATR (14)",
                source="hermes.agents.VolatilityAgent",
            ),
        ],
        annotations=_COMMON_ANNOTATIONS,
        forbidden_indicators=["sma_crossover", "ema_fast", "ema_slow", "pivot_high", "pivot_low", "swing_high_low"],
    ),
    # ── Liquidity / SMC ─────────────────────────────
    "liquidity_smc": StrategyFamilyVisualSpec(
        family_id="liquidity_smc",
        display_name="Liquidity / SMC",
        indicators=[
            IndicatorSpec(
                name="price_candles",
                role=IndicatorRole.REQUIRED,
                display_name="Price (OHLC)",
                source="core.types.Bar",
            ),
            IndicatorSpec(
                name="swing_high",
                role=IndicatorRole.REQUIRED,
                display_name="Swing High (20-bar)",
                source="stop_run_fade._swing_levels / simple_breakout highest_high",
            ),
            IndicatorSpec(
                name="swing_low",
                role=IndicatorRole.REQUIRED,
                display_name="Swing Low (20-bar)",
                source="stop_run_fade._swing_levels / simple_breakout lowest_low",
            ),
            IndicatorSpec(
                name="highest_high",
                role=IndicatorRole.REQUIRED,
                display_name="Highest High (20-bar)",
                source="simple_breakout.on_bar",
            ),
            IndicatorSpec(
                name="lowest_low",
                role=IndicatorRole.REQUIRED,
                display_name="Lowest Low (20-bar)",
                source="simple_breakout.on_bar",
            ),
            IndicatorSpec(
                name="wyckoff_effort_result",
                role=IndicatorRole.OPTIONAL,
                display_name="Wyckoff Effort/Result Ratio",
                source="hermes.agents.WyckoffAgent",
            ),
            IndicatorSpec(
                name="volume_profile",
                role=IndicatorRole.OPTIONAL,
                display_name="Volume Profile",
                source="core.types.Bar.volume",
            ),
        ],
        annotations=_COMMON_ANNOTATIONS,
        forbidden_indicators=["sma_fast", "sma_slow", "ema_fast", "ema_slow", "rsi", "vwap", "bollinger_bands"],
    ),
}


# ──────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────


def get_family_spec(family_id: str) -> StrategyFamilyVisualSpec:
    """Get visual spec for a family. Raises ValueError if unknown."""
    if family_id not in FAMILY_VISUAL_SPECS:
        raise ValueError(f"Unknown strategy family: {family_id}")
    return FAMILY_VISUAL_SPECS[family_id]


def validate_indicator_set(
    family_id: str, rendered_indicators: list[str]
) -> tuple[bool, list[str]]:
    """Validate that rendered indicators match the family spec.

    Returns (is_valid, list_of_violations).
    """
    spec = get_family_spec(family_id)
    violations: list[str] = []
    forbidden_names = set(spec.forbidden_indicators)
    for indicator in rendered_indicators:
        if indicator in forbidden_names:
            violations.append(
                f"Forbidden indicator '{indicator}' in family '{family_id}'"
            )
    return len(violations) == 0, violations


def validate_family_mapping() -> list[str]:
    """Validate the entire mapping at import time.

    Returns list of issues found (empty = valid).
    """
    issues: list[str] = []
    for family_id, spec in FAMILY_VISUAL_SPECS.items():
        if spec.family_id != family_id:
            issues.append(f"Family key mismatch: '{family_id}' != '{spec.family_id}'")
        required_count = sum(
            1 for i in spec.indicators if i.role == IndicatorRole.REQUIRED
        )
        if required_count < 1:
            issues.append(f"Family '{family_id}' has no REQUIRED indicators")
        if len(spec.annotations) < 1:
            issues.append(f"Family '{family_id}' has no annotations")
    return issues


# Validate on import
_validation_issues = validate_family_mapping()
if _validation_issues:
    for issue in _validation_issues:
        logger.warning("Family mapping validation: %s", issue)
