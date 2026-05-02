"""Component C — IndicatorOverlayLayer: Render indicators from family mapping.

Renders precomputed indicators based on the canonical strategy family mapping.
Never computes indicators — only renders precomputed data.
Blocks forbidden indicators at render time.

Phase F.2 — Visualization & Human Control Plane.
"""

from __future__ import annotations

import logging
from typing import Any

from src.visualization.family_mapping import (
    FAMILY_VISUAL_SPECS,
    IndicatorRole,
    get_family_spec,
    validate_indicator_set,
)

logger = logging.getLogger(__name__)

# Deterministic color palette per indicator type
INDICATOR_COLORS = {
    "price_candles": "#000000",
    "ema_fast": "#2196F3",      # Blue
    "ema_slow": "#1565C0",      # Dark blue
    "sma_fast": "#4CAF50",      # Green
    "sma_slow": "#2E7D32",      # Dark green
    "market_structure": "#9C27B0",  # Purple
    "pivot_high": "#FF9800",    # Orange
    "pivot_low": "#FF5722",     # Deep orange
    "ichimoku_cloud": "#607D8B",  # Blue grey
    "rsi": "#F44336",           # Red
    "vwap": "#E91E63",          # Pink
    "value_area": "#795548",    # Brown
    "bollinger_bands": "#00BCD4",  # Cyan
    "atr": "#FFC107",           # Amber
    "swing_high": "#FF9800",    # Orange
    "swing_low": "#FF5722",     # Deep orange
    "highest_high": "#795548",  # Brown
    "lowest_low": "#8D6E63",    # Light brown
    "wyckoff_effort_result": "#607D8B",  # Blue grey
    "volume_profile": "#9E9E9E",  # Grey
}


def get_indicator_color(indicator_name: str) -> str:
    """Get deterministic color for an indicator."""
    return INDICATOR_COLORS.get(indicator_name, "#757575")


def render_indicator_overlay(
    strategy_family: str,
    precomputed_indicators: dict[str, Any],
) -> dict[str, Any]:
    """Validate and prepare indicator overlay data for rendering.

    Args:
        strategy_family: Key into FAMILY_VISUAL_SPECS.
        precomputed_indicators: Indicator name → computed values mapping.

    Returns:
        Dict with:
            - is_valid: Whether validation passed
            - violations: List of violation messages
            - rendered_indicators: Dict of indicator_name → {values, color, display_name}
            - missing_required: List of required indicators not in data
    """
    # Validate family exists
    try:
        spec = get_family_spec(strategy_family)
    except ValueError as e:
        return {
            "is_valid": False,
            "violations": [str(e)],
            "rendered_indicators": {},
            "missing_required": [],
        }

    # Validate forbidden indicators
    is_valid, violations = validate_indicator_set(
        strategy_family, list(precomputed_indicators.keys())
    )

    # Check for missing required indicators
    required_names = {
        ind.name for ind in spec.indicators if ind.role == IndicatorRole.REQUIRED
    }
    available_names = set(precomputed_indicators.keys())
    # price_candles is always available from OHLC data
    missing_required = [
        name for name in required_names
        if name not in available_names and name != "price_candles"
    ]

    # Build rendered indicators dict
    rendered_indicators = {}
    for ind_spec in spec.indicators:
        if ind_spec.name in precomputed_indicators:
            rendered_indicators[ind_spec.name] = {
                "values": precomputed_indicators[ind_spec.name],
                "color": get_indicator_color(ind_spec.name),
                "display_name": ind_spec.display_name,
                "role": ind_spec.role.value,
            }

    return {
        "is_valid": is_valid,
        "violations": violations,
        "rendered_indicators": rendered_indicators,
        "missing_required": missing_required,
    }


def get_family_indicators(family_id: str) -> list[dict[str, str]]:
    """Get list of indicator specs for a family.

    Returns list of dicts with name, role, display_name, source.
    """
    spec = get_family_spec(family_id)
    return [
        {
            "name": ind.name,
            "role": ind.role.value,
            "display_name": ind.display_name,
            "source": ind.source,
        }
        for ind in spec.indicators
    ]
