"""Component E — CorrelationContextLayer: Correlation heatmap and context.

Shows correlation relationships between symbols for Breadth Expansion
and Meta-Optimization charts.

Phase F.2 — Visualization & Human Control Plane.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_correlation_context(
    correlation_matrix: Any = None,
    correlated_symbols: list[str] | None = None,
    diversification_score: float = 0.0,
    redundancy_warnings: list[str] | None = None,
    current_symbol: str | None = None,
) -> dict[str, Any]:
    """Build correlation context data for rendering.

    Returns dict with:
        - has_data: Whether correlation data is available
        - symbols: List of all symbols in the matrix
        - matrix_data: Nested dict of correlation values
        - high_pairs: List of (sym_a, sym_b, r) with |r| > 0.75
        - diversification_score: 0-1 score
        - diversification_label: Human-readable label
        - diversification_color: Color for the score badge
        - redundancy_warnings: List of warning strings
        - current_symbol: Highlighted symbol
    """
    if correlation_matrix is None:
        return {
            "has_data": False,
            "symbols": [],
            "matrix_data": {},
            "high_pairs": [],
            "diversification_score": 0.0,
            "diversification_label": "No data",
            "diversification_color": "#9E9E9E",
            "redundancy_warnings": [],
            "current_symbol": current_symbol,
        }

    # Extract matrix data
    symbols = getattr(correlation_matrix, "symbols", [])
    matrix_dict = getattr(correlation_matrix, "matrix", {})
    high_pairs = getattr(correlation_matrix, "high_pairs", [])

    # Build nested dict for heatmap
    matrix_data = {}
    for sym_a in symbols:
        matrix_data[sym_a] = {}
        for sym_b in symbols:
            if sym_a == sym_b:
                matrix_data[sym_a][sym_b] = 1.0
            else:
                key = (sym_a, sym_b) if (sym_a, sym_b) in matrix_dict else (sym_b, sym_a)
                matrix_data[sym_a][sym_b] = matrix_dict.get(key, 0.0)

    # Diversification score coloring
    if diversification_score > 0.7:
        div_color = "#4CAF50"  # Green
        div_label = "Well Diversified"
    elif diversification_score > 0.4:
        div_color = "#FFC107"  # Amber
        div_label = "Moderately Diversified"
    else:
        div_color = "#F44336"  # Red
        div_label = "Concentrated"

    return {
        "has_data": True,
        "symbols": symbols,
        "matrix_data": matrix_data,
        "high_pairs": high_pairs,
        "diversification_score": diversification_score,
        "diversification_label": div_label,
        "diversification_color": div_color,
        "redundancy_warnings": redundancy_warnings or [],
        "current_symbol": current_symbol,
    }


def format_high_pairs(high_pairs: list[tuple[str, str, float]]) -> list[dict[str, Any]]:
    """Format high correlation pairs for display.

    Returns list of dicts with sym_a, sym_b, correlation, severity.
    """
    formatted = []
    for sym_a, sym_b, r in sorted(high_pairs, key=lambda x: abs(x[2]), reverse=True):
        if abs(r) > 0.90:
            severity = "CRITICAL"
        elif abs(r) > 0.75:
            severity = "HIGH"
        else:
            severity = "MODERATE"
        formatted.append({
            "sym_a": sym_a,
            "sym_b": sym_b,
            "correlation": r,
            "abs_correlation": abs(r),
            "severity": severity,
        })
    return formatted
