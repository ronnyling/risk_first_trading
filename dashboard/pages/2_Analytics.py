"""Analytics & Reporting page for Hermes Observability Dashboard.

Provides structured reports over persistence data:
- Session summaries
- Strategy performance
- Risk utilization
- Hermes outcome tracking

All reports support CSV export.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

# Add src to Python path for imports
_root = str(Path(__file__).resolve().parent.parent.parent)
src_path = os.path.join(_root, "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)
if _root not in sys.path:
    sys.path.insert(0, _root)

from analytics.engine import AnalyticsEngine
from analytics.models import SessionReport, StrategyReport, RiskReport, HermesReport

st.set_page_config(
    page_title="Hermes Analytics",
    page_icon="A",
    layout="wide",
)

st.title("Analytics & Reports")

# ── Phase F: Mode Banner ──────────────────────────────
try:
    from visualization.mode_banner import render_mode_banner
    _sys_mode = st.session_state.get("system_mode", "ADVISORY")
    _mode_data = render_mode_banner(_sys_mode)
    st.markdown(_mode_data["html"], unsafe_allow_html=True)
except Exception:
    pass

# Initialize analytics engine
try:
    analytics = AnalyticsEngine()
except Exception as e:
    st.error(f"Failed to initialize analytics: {e}")
    st.stop()

# ── Tab navigation ──────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs([
    "Sessions", "Strategies", "Risk", "Hermes"
])


# ── Helper: CSV export button ────────────────────────────
def _add_csv_export(report, filename: str) -> None:
    """Add a CSV export button for a report."""
    import tempfile
    from dataclasses import asdict

    data = asdict(report)
    # Flatten complex fields
    flat = {}
    for k, v in data.items():
        if isinstance(v, list):
            flat[k] = f"{len(v)} items"
        elif isinstance(v, dict):
            flat[k] = json.dumps(v)
        else:
            flat[k] = v

    csv_lines = [",".join(flat.keys()), ",".join(str(v) for v in flat.values())]
    csv_content = "\n".join(csv_lines)

    st.download_button(
        label="Export CSV",
        data=csv_content,
        file_name=filename,
        mime="text/csv",
        key=f"csv_{filename}",
    )


# ══════════════════════════════════════════════════════════
# Tab 1: Session Summary
# ══════════════════════════════════════════════════════════
with tab1:
    st.markdown("#### Session Summary")

    col1, col2 = st.columns([3, 1])
    with col2:
        run_id_input = st.number_input(
            "Run ID (0 = latest)",
            min_value=0,
            value=0,
            key="session_run_id",
        )

    run_id = run_id_input if run_id_input > 0 else None

    try:
        session = analytics.session_summary(run_id=run_id)

        if session.run_id == 0:
            st.info("No engine runs found in the database.")
        else:
            # Metrics row
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric("Run ID", session.run_id)
            with m2:
                st.metric("Bars Processed", session.bars_processed)
            with m3:
                st.metric("Fills", session.total_fills)
            with m4:
                st.metric("Vetoes", session.total_vetoes)

            # Timing
            if session.started_at:
                st.caption(f"Started: {session.started_at}")
            if session.finished_at:
                st.caption(f"Finished: {session.finished_at}")

            # Portfolio
            if session.final_portfolio_value is not None:
                st.metric("Final Portfolio Value", f"${session.final_portfolio_value:,.2f}")
            if session.final_pnl is not None:
                st.metric("Final PnL", f"${session.final_pnl:,.2f}")

            # Export
            _add_csv_export(session, f"session_{session.run_id}.csv")

    except Exception as e:
        st.error(f"Error loading session summary: {e}")


# ══════════════════════════════════════════════════════════
# Tab 2: Strategy Performance
# ══════════════════════════════════════════════════════════
with tab2:
    st.markdown("#### Strategy Performance")

    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        strategy_id = st.text_input(
            "Strategy ID (empty = all)",
            "",
            key="perf_strategy_id",
        )
    with col2:
        since_date = st.date_input(
            "Since",
            value=None,
            key="perf_since",
        )
    with col3:
        st.write("")  # spacer
        st.write("")

    since_str = since_date.isoformat() if since_date else None
    sid = strategy_id if strategy_id.strip() else None

    try:
        report = analytics.strategy_performance(strategy_id=sid, since=since_str)

        if report.total_trades == 0:
            st.info("No trades found for the selected criteria.")
        else:
            # Metrics row
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric("Total Trades", report.total_trades)
            with m2:
                st.metric("Win Rate", f"{report.win_rate:.1%}")
            with m3:
                st.metric("Total PnL", f"${report.total_pnl:,.2f}")
            with m4:
                st.metric("Avg Trade PnL", f"${report.avg_trade_pnl:,.2f}")

            m5, m6 = st.columns(2)
            with m5:
                st.metric("Winning Trades", report.winning_trades)
            with m6:
                st.metric("Losing Trades", report.losing_trades)

            if report.max_drawdown > 0:
                st.metric("Max Drawdown", f"${report.max_drawdown:,.2f}")

            # Fill history
            if report.fill_history:
                st.markdown("**Recent Fills**")
                fills_df = pd.DataFrame([
                    {
                        "timestamp": f.timestamp,
                        "symbol": f.symbol,
                        "side": f.side,
                        "quantity": f.quantity,
                        "fill_price": f.fill_price,
                        "pnl": f.pnl,
                        "strategy": f.strategy_id,
                    }
                    for f in report.fill_history[-20:]  # last 20
                ])
                st.dataframe(fills_df, use_container_width=True, hide_index=True)

            _add_csv_export(report, f"strategy_{report.strategy_id}.csv")

    except Exception as e:
        st.error(f"Error loading strategy performance: {e}")


# ══════════════════════════════════════════════════════════
# Tab 3: Risk Utilization
# ══════════════════════════════════════════════════════════
with tab3:
    st.markdown("#### Risk Utilization")

    col1, col2 = st.columns([2, 1])
    with col2:
        since_date_risk = st.date_input(
            "Since",
            value=None,
            key="risk_since",
        )

    since_str_risk = since_date_risk.isoformat() if since_date_risk else None

    try:
        risk = analytics.risk_utilization(since=since_str_risk)

        # Metrics row
        m1, m2, m3 = st.columns(3)
        with m1:
            st.metric("Veto Rate", f"{risk.veto_rate:.1%}")
        with m2:
            st.metric("Max Drawdown", f"${risk.max_drawdown_observed:,.2f}")
        with m3:
            st.metric("Risk Budget Used", f"{risk.risk_budget_utilization:.1%}")

        m4, m5 = st.columns(2)
        with m4:
            st.metric("Avg Drawdown", f"${risk.avg_drawdown:,.2f}")
        with m5:
            st.metric("Veto Events", risk.total_drawdown_events)

        # Veto history
        if risk.veto_history:
            st.markdown("**Recent Vetoes**")
            veto_df = pd.DataFrame([
                {
                    "timestamp": v.timestamp,
                    "order_id": v.order_id,
                    "strategy": v.strategy_id,
                    "reason": v.reason,
                }
                for v in risk.veto_history[-20:]  # last 20
            ])
            st.dataframe(veto_df, use_container_width=True, hide_index=True)

        _add_csv_export(risk, "risk_utilization.csv")

    except Exception as e:
        st.error(f"Error loading risk utilization: {e}")


# ══════════════════════════════════════════════════════════
# Tab 4: Hermes Outcomes
# ══════════════════════════════════════════════════════════
with tab4:
    st.markdown("#### Hermes Decision Quality")

    col1, col2 = st.columns([2, 1])
    with col2:
        since_date_hermes = st.date_input(
            "Since",
            value=None,
            key="hermes_since",
        )

    since_str_hermes = since_date_hermes.isoformat() if since_date_hermes else None

    try:
        hermes = analytics.hermes_outcomes(since=since_str_hermes)

        if hermes.total_runs == 0:
            st.info("No Hermes runs found. Run Hermes at least once to see outcomes.")
        else:
            # Metrics row
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric("Total Runs", hermes.total_runs)
            with m2:
                st.metric("Total Decisions", hermes.total_decisions)
            with m3:
                st.metric("Avg Confidence", f"{hermes.avg_confidence:.3f}")
            with m4:
                st.metric("Alerts", hermes.alert_count)

            # Directive distribution
            if hermes.directive_distribution:
                st.markdown("**Directive Distribution**")
                dir_df = pd.DataFrame([
                    {"Directive": k, "Count": v}
                    for k, v in hermes.directive_distribution.items()
                ])
                st.dataframe(dir_df, use_container_width=True, hide_index=True)

            # Regime distribution
            if hermes.regime_distribution:
                st.markdown("**Regime Distribution**")
                reg_df = pd.DataFrame([
                    {"Regime": k, "Count": v}
                    for k, v in hermes.regime_distribution.items()
                ])
                st.dataframe(reg_df, use_container_width=True, hide_index=True)

            _add_csv_export(hermes, "hermes_outcomes.csv")

    except Exception as e:
        st.error(f"Error loading Hermes outcomes: {e}")
