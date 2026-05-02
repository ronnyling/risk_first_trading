"""Component D — DecisionAnnotationLayer: Explain why a proposal exists.

Overlays decision context on charts:
- Entry zone (shaded band, never a line)
- Invalidation zone (shaded band)
- Exit criteria (logical label, not fixed price)
- Confidence score
- Directive label

Phase F.2 — Visualization & Human Control Plane.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_decision_annotations(
    hermes_decision: Any = None,
    entry_zone: tuple[float, float] | None = None,
    invalidation_zone: tuple[float, float] | None = None,
    exit_criteria: str | None = None,
    confidence_label: str | None = None,
    directive_label: str | None = None,
    strategy_family: str = "structural_fractal",
) -> dict[str, Any]:
    """Build decision annotation data for rendering.

    Extracts annotation data from HermesDecision if provided,
    and merges with explicit overrides.

    Returns dict with:
        - has_annotations: Whether any annotations are available
        - entry_zone: (low, high) tuple or None
        - invalidation_zone: (low, high) tuple or None
        - exit_criteria: Logical condition string or None
        - confidence_label: Human-readable confidence
        - directive_label: Risk directive text
        - strategy_family: Family for rendering style
    """
    # Extract from HermesDecision if provided
    if hermes_decision is not None:
        if confidence_label is None:
            conf = getattr(hermes_decision, "confidence", None)
            if conf is not None:
                if conf >= 0.75:
                    level = "HIGH"
                elif conf >= 0.50:
                    level = "MEDIUM"
                else:
                    level = "LOW"
                confidence_label = f"{level} ({conf:.2f})"

        if directive_label is None:
            directive_label = getattr(hermes_decision, "risk_directive", None)

    has_annotations = any([
        entry_zone is not None,
        invalidation_zone is not None,
        exit_criteria is not None,
        confidence_label is not None,
        directive_label is not None,
    ])

    return {
        "has_annotations": has_annotations,
        "entry_zone": entry_zone,
        "invalidation_zone": invalidation_zone,
        "exit_criteria": exit_criteria,
        "confidence_label": confidence_label,
        "directive_label": directive_label,
        "strategy_family": strategy_family,
    }


def get_annotation_style(annotation_type: str) -> dict[str, str]:
    """Get rendering style for an annotation type.

    Returns dict with color, opacity, line_style.
    """
    styles = {
        "entry_zone": {
            "color": "rgba(76, 175, 80, 0.2)",  # Green, semi-transparent
            "border_color": "rgba(76, 175, 80, 0.6)",
            "line_style": "solid",
        },
        "invalidation_zone": {
            "color": "rgba(244, 67, 54, 0.2)",  # Red, semi-transparent
            "border_color": "rgba(244, 67, 54, 0.6)",
            "line_style": "dash",
        },
        "exit_criteria": {
            "color": "#FF9800",  # Orange
            "border_color": "#FF9800",
            "line_style": "dot",
        },
        "confidence": {
            "color": "#2196F3",  # Blue
            "border_color": "#2196F3",
            "line_style": "solid",
        },
        "directive": {
            "color": "#9C27B0",  # Purple
            "border_color": "#9C27B0",
            "line_style": "solid",
        },
    }
    return styles.get(annotation_type, {
        "color": "#757575",
        "border_color": "#757575",
        "line_style": "solid",
    })


def format_confidence(confidence: float) -> str:
    """Format a confidence value into a human-readable label."""
    if confidence >= 0.75:
        level = "HIGH"
    elif confidence >= 0.50:
        level = "MEDIUM"
    else:
        level = "LOW"
    return f"{level} ({confidence:.2f})"
