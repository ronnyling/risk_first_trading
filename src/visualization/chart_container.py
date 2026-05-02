"""Component A — ChartContainer: Mode-aware wrapper enforcing governance.

Wraps all chart rendering in a consistent container with:
- Mode-specific banners (LIVE / ADVISORY / META_LOCKDOWN)
- Interactivity restrictions (disabled in META_LOCKDOWN)
- Audit logging (USER_ACTION: CHART_VIEW events)

Phase F.2 — Visualization & Human Control Plane.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Mode banner configuration
MODE_BANNERS = {
    "LIVE": {"color": "green", "label": "LIVE DATA"},
    "ADVISORY": {"color": "blue", "label": "HISTORICAL SNAPSHOT"},
    "META_LOCKDOWN": {"color": "orange", "label": "META-OPTIMIZATION MODE — EXECUTION FROZEN"},
    "EXECUTION_STOPPED": {"color": "blue", "label": "HISTORICAL SNAPSHOT"},
}


def get_mode_banner(system_mode: str) -> dict[str, str]:
    """Get banner configuration for a system mode.

    Returns dict with 'color' and 'label' keys.
    Unknown modes default to ADVISORY.
    """
    return MODE_BANNERS.get(system_mode, MODE_BANNERS["ADVISORY"])


def render_chart_container(
    system_mode: str,
    symbol: str,
    timeframe: str,
    chart_id: str,
    snapshot_id: str | None = None,
    show_banner: bool = True,
    interactive: bool | None = None,
    audit_logger: Any = None,
) -> dict[str, Any]:
    """Render a mode-aware chart container.

    Args:
        system_mode: Current system mode.
        symbol: Symbol being charted.
        timeframe: Timeframe of the chart.
        chart_id: Unique ID for logging.
        snapshot_id: Links to analysis snapshot store.
        show_banner: Whether to display the mode banner.
        interactive: Override interactivity. If None, derived from mode.
        audit_logger: UIAuditLogger instance for logging events.

    Returns:
        Dict with rendering metadata (banner config, interactivity flag, etc.)
    """
    # Resolve interactivity from mode if not overridden
    if interactive is None:
        interactive = system_mode != "META_LOCKDOWN"

    # Get banner
    banner = get_mode_banner(system_mode) if show_banner else None

    # Log the chart view event
    event_data = {
        "chart_id": chart_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "snapshot_id": snapshot_id,
        "system_mode": system_mode,
        "interactive": interactive,
    }

    if audit_logger is not None:
        try:
            audit_logger.log_event(
                event_type="CHART_OPENED",
                event_category="USER_ACTION",
                event_data=event_data,
                system_mode=system_mode,
            )
        except Exception as e:
            logger.warning("Failed to log chart view: %s", e)

    return {
        "banner": banner,
        "interactive": interactive,
        "symbol": symbol,
        "timeframe": timeframe,
        "chart_id": chart_id,
        "snapshot_id": snapshot_id,
    }


def render_banner_html(system_mode: str, last_updated: str = "") -> str:
    """Render the mode banner as HTML string.

    Used by both ChartContainer and ModeBanner (Component F).
    """
    banner = get_mode_banner(system_mode)
    updated_text = f" | Last updated: {last_updated}" if last_updated else ""
    return (
        f'<div style="background-color:{banner["color"]}; color:white; '
        f'padding:8px; border-radius:4px; font-weight:bold;">'
        f'{banner["label"]}{updated_text}</div>'
    )
