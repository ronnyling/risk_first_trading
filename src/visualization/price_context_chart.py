"""Component B — PriceContextChart: Always-on market context chart.

Renders candlestick charts from OHLC bars. Independent of live trading.
Renderable even when execution is stopped.

Phase F.2 — Visualization & Human Control Plane.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def compute_chart_title(symbol: str, timeframe: str, strategy_family: str = "") -> str:
    """Compute the chart title string."""
    family_label = f" — {strategy_family.replace('_', ' ').title()}" if strategy_family else ""
    return f"{symbol} {timeframe}{family_label}"


def validate_bars(bars: list[Any], min_bars: int = 52) -> tuple[bool, str | None]:
    """Validate bar data for chart rendering.

    Returns (is_valid, warning_message).
    """
    if len(bars) == 0:
        return False, "No data available"
    if len(bars) < min_bars:
        return True, f"Insufficient data: {len(bars)}/{min_bars} bars required"
    return True, None


def build_price_context(
    symbol: str,
    timeframe: str,
    bars: list[Any],
    strategy_family: str = "structural_fractal",
    hermes_decision: Any = None,
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Build price context data for chart rendering.

    Returns dict with:
        - title: Chart title
        - symbol: Symbol
        - timeframe: Timeframe
        - bars_valid: Whether bars are valid
        - bar_count: Number of bars
        - warning: Warning message, if any
        - strategy_family: Strategy family
        - has_decision: Whether a HermesDecision is provided
        - snapshot_id: Snapshot ID
    """
    title = compute_chart_title(symbol, timeframe, strategy_family)
    is_valid, warning = validate_bars(bars)

    return {
        "title": title,
        "symbol": symbol,
        "timeframe": timeframe,
        "bars_valid": is_valid,
        "bar_count": len(bars),
        "warning": warning,
        "strategy_family": strategy_family,
        "has_decision": hermes_decision is not None,
        "snapshot_id": snapshot_id,
    }


def get_timeframe_format(timeframe: str) -> str:
    """Return date format string for a timeframe."""
    formats = {
        "1m": "%H:%M",
        "5m": "%H:%M",
        "15m": "%H:%M",
        "30m": "%H:%M",
        "1H": "%Y-%m-%d %H:%M",
        "4H": "%Y-%m-%d %H:%M",
        "1D": "%Y-%m-%d",
        "1W": "%Y-%m-%d",
    }
    return formats.get(timeframe, "%Y-%m-%d %H:%M")
