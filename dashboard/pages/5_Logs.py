"""Logs & Events — Dashboard page.

Provides a filterable, read-only view of all system events across
6 categories: EXECUTION, ADVISORY, BREADTH, META, SYSTEM, USER_ACTION.

Phase F.4 — Visualization & Human Control Plane.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import streamlit as st

# Add src to Python path for imports
_root = str(Path(__file__).resolve().parent.parent.parent)
src_path = os.path.join(_root, "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)
if _root not in sys.path:
    sys.path.insert(0, _root)

from persistence.db import PersistenceDB
from visualization.audit_logger import UIAuditLogger
from visualization.mode_banner import get_mode_color, get_mode_label, get_mode_emoji

# ──────────────────────────────────────────────────────
# Page config
# ──────────────────────────────────────────────────────

st.set_page_config(
    page_title="Logs & Events",
    page_icon="L",
    layout="wide",
)

st.title("Logs & Events")

# ──────────────────────────────────────────────────────
# Initialize
# ──────────────────────────────────────────────────────

db = PersistenceDB()
audit_logger = UIAuditLogger(db)
system_mode = st.session_state.get("system_mode", "ADVISORY")

# ──────────────────────────────────────────────────────
# Mode Banner
# ──────────────────────────────────────────────────────

mode_emoji = get_mode_emoji(system_mode)
mode_label = get_mode_label(system_mode)
st.markdown(
    f'<div style="background-color:{get_mode_color(system_mode)}; color:white; '
    f'padding:8px; border-radius:4px; font-weight:bold;">'
    f'{mode_emoji} {mode_label}</div>',
    unsafe_allow_html=True,
)

st.divider()

# ──────────────────────────────────────────────────────
# Filters
# ──────────────────────────────────────────────────────

col1, col2, col3 = st.columns(3)

with col1:
    category_filter = st.selectbox(
        "Event Category",
        ["ALL", "EXECUTION", "ADVISORY", "BREADTH", "META", "SYSTEM", "USER_ACTION"],
        index=0,
    )

with col2:
    event_type_filter = st.text_input(
        "Event Type",
        placeholder="e.g. CHART_OPENED, ACTION_TAKEN",
    )

with col3:
    limit = st.number_input(
        "Max Events",
        min_value=10,
        max_value=1000,
        value=100,
        step=10,
    )

# ──────────────────────────────────────────────────────
# Fetch events
# ──────────────────────────────────────────────────────

conn = db._get_conn()
if conn is not None:
    try:
        query = "SELECT * FROM ui_events WHERE 1=1"
        params = []

        if category_filter != "ALL":
            query += " AND event_category = ?"
            params.append(category_filter)

        if event_type_filter:
            query += " AND event_type LIKE ?"
            params.append(f"%{event_type_filter}%")

        query += " ORDER BY event_id DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        events = [dict(r) for r in rows]
    except Exception as e:
        st.error(f"Error querying events: {e}")
        events = []
else:
    st.warning("Database not available")
    events = []

# ──────────────────────────────────────────────────────
# Display
# ──────────────────────────────────────────────────────

st.subheader(f"Events ({len(events)} shown)")

if not events:
    st.info("No events found matching filters.")
else:
    for event in events:
        event_type = event.get("event_type", "UNKNOWN")
        category = event.get("event_category", "SYSTEM")
        mode = event.get("system_mode", "UNKNOWN")
        created_at = event.get("created_at", "")
        event_data_str = event.get("event_data", "{}")

        # Color code by category
        category_colors = {
            "EXECUTION": "#4CAF50",
            "ADVISORY": "#2196F3",
            "BREADTH": "#9C27B0",
            "META": "#FF9800",
            "SYSTEM": "#607D8B",
            "USER_ACTION": "#F44336",
        }
        cat_color = category_colors.get(category, "#757575")

        with st.expander(
            f"[{category}] {event_type} — {created_at[:19] if created_at else 'N/A'}",
            expanded=False,
        ):
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown(f"**Type:** `{event_type}`")
                st.markdown(f"**Category:** `{category}`")
            with col_b:
                st.markdown(f"**Mode:** `{mode}`")
                st.markdown(f"**Time:** `{created_at}`")

            try:
                event_data = json.loads(event_data_str)
                st.json(event_data)
            except (json.JSONDecodeError, TypeError):
                st.code(event_data_str)

    # Export buttons
    st.divider()
    col_export1, col_export2 = st.columns(2)

    with col_export1:
        if st.button("Export as JSON", use_container_width=True):
            export_data = json.dumps(events, indent=2, default=str)
            st.download_button(
                label="Download JSON",
                data=export_data,
                file_name="ui_events.json",
                mime="application/json",
            )

    with col_export2:
        if st.button("Export as CSV", use_container_width=True):
            import csv
            import io

            if events:
                output = io.StringIO()
                writer = csv.DictWriter(output, fieldnames=events[0].keys())
                writer.writeheader()
                writer.writerows(events)
                st.download_button(
                    label="Download CSV",
                    data=output.getvalue(),
                    file_name="ui_events.csv",
                    mime="text/csv",
                )

# ──────────────────────────────────────────────────────
# Verbosity Control (sidebar)
# ──────────────────────────────────────────────────────

# Note: Verbosity control is in the main app.py sidebar
