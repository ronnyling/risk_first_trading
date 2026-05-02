"""Component F — ModeBanner: Global mode indicator at top of every page.

Renders the system mode as a colored banner with label and timestamp.

Phase F.2 — Visualization & Human Control Plane.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

MODE_COLORS = {
    "LIVE": "green",
    "ADVISORY": "blue",
    "META_LOCKDOWN": "orange",
}

MODE_LABELS = {
    "LIVE": "LIVE TRADING — Real money at risk",
    "ADVISORY": "ADVISORY ONLY — No execution",
    "META_LOCKDOWN": "META-OPTIMIZATION LOCKDOWN — Execution frozen",
}


def get_mode_color(system_mode: str) -> str:
    """Get the color for a system mode."""
    return MODE_COLORS.get(system_mode, "gray")


def get_mode_label(system_mode: str) -> str:
    """Get the label for a system mode."""
    return MODE_LABELS.get(system_mode, "Unknown mode")


def render_mode_banner(
    system_mode: str,
    last_updated: str = "",
    execution_active: bool = False,
) -> dict[str, Any]:
    """Build mode banner data for rendering.

    Args:
        system_mode: Current system mode.
        last_updated: ISO timestamp of last state change.
        execution_active: Whether engine is running.

    Returns:
        Dict with color, label, html, timestamp, mode.
    """
    if not last_updated:
        last_updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    color = get_mode_color(system_mode)
    label = get_mode_label(system_mode)
    html = (
        f'<div style="background-color:{color}; color:white; '
        f'padding:8px; border-radius:4px; font-weight:bold;">'
        f'{label} | Last updated: {last_updated}</div>'
    )

    return {
        "color": color,
        "label": label,
        "html": html,
        "timestamp": last_updated,
        "mode": system_mode,
        "execution_active": execution_active,
    }


def get_mode_emoji(system_mode: str) -> str:
    """Get emoji for a system mode (for text-based displays)."""
    emojis = {
        "LIVE": "🔴",
        "ADVISORY": "🔵",
        "META_LOCKDOWN": "🟠",
    }
    return emojis.get(system_mode, "⚪")
