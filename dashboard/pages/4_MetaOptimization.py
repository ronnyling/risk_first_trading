"""Meta-Optimization Dashboard — Phase E HITL control surface.

Provides dashboard page for reviewing and acting on meta-optimization proposals.
Human actions: Adopt / Reject / Ignore only. No sliders, no free-text input.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import streamlit as st

logger = logging.getLogger(__name__)


def render_meta_optimization_page():
    """Render the Meta-Optimization dashboard page."""
    st.title("Meta-Optimization Dashboard")
    st.caption("Phase E — Self-optimization, leverage simulation, policy evolution, LLM tuning, strategy R&D")

    # ── Phase F: Mode Banner ──────────────────────────────
    try:
        from visualization.mode_banner import render_mode_banner
        _sys_mode = st.session_state.get("system_mode", "ADVISORY")
        _mode_data = render_mode_banner(_sys_mode)
        st.markdown(_mode_data["html"], unsafe_allow_html=True)
    except Exception:
        pass

    # System health header
    _render_system_health()

    # Tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Proposals",
        "Optimization History",
        "Strategy Variants (R&D)",
        "Drift Monitor",
        "Run Capabilities",
    ])

    with tab1:
        _render_proposals_tab()

    with tab2:
        _render_history_tab()

    with tab3:
        _render_variants_tab()

    with tab4:
        _render_drift_tab()

    with tab5:
        _render_run_tab()


def _render_system_health():
    """Render system health summary."""
    st.divider()

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Current Sharpe", "0.85", "+0.12")

    with col2:
        st.metric("Current Max DD", "8.2%", "-1.3%")

    with col3:
        st.metric("Meta-Changes (Q)", "1/2", "")

    with col4:
        st.metric("Drift Status", "None", "")

    st.divider()


def _render_proposals_tab():
    """Render the proposals tab."""
    st.subheader("Pending Proposals")

    try:
        from src.persistence.db import PersistenceDB
        db = PersistenceDB()
        proposals = db.get_meta_proposals(status="PENDING")

        if not proposals:
            st.info("No pending proposals. Run a capability to generate proposals.")
            return

        for proposal in proposals:
            with st.expander(
                f"📋 {proposal['capability']} — {proposal['proposal_id']} "
                f"({proposal['created_at'][:10]})"
            ):
                st.json(proposal)

                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button(
                        "✅ Adopt",
                        key=f"adopt_{proposal['proposal_id']}",
                        use_container_width=True,
                    ):
                        _handle_decision(proposal["proposal_id"], "ADOPTED")
                        st.rerun()

                with col2:
                    if st.button(
                        "❌ Reject",
                        key=f"reject_{proposal['proposal_id']}",
                        use_container_width=True,
                    ):
                        _handle_decision(proposal["proposal_id"], "REJECTED")
                        st.rerun()

                with col3:
                    if st.button(
                        "⏸ Ignore",
                        key=f"ignore_{proposal['proposal_id']}",
                        use_container_width=True,
                    ):
                        _handle_decision(proposal["proposal_id"], "IGNORED")
                        st.rerun()

    except Exception as e:
        st.error(f"Error loading proposals: {e}")


def _render_history_tab():
    """Render the optimization history tab."""
    st.subheader("Optimization History")

    try:
        from src.persistence.db import PersistenceDB
        db = PersistenceDB()
        proposals = db.get_meta_proposals(limit=50)

        if not proposals:
            st.info("No optimization history yet.")
            return

        # Status distribution
        status_counts: dict[str, int] = {}
        for p in proposals:
            status = p.get("status", "UNKNOWN")
            status_counts[status] = status_counts.get(status, 0) + 1

        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("Pending", status_counts.get("PENDING", 0))
        with col2:
            st.metric("Adopted", status_counts.get("ADOPTED", 0))
        with col3:
            st.metric("Rejected", status_counts.get("REJECTED", 0))
        with col4:
            st.metric("Ignored", status_counts.get("IGNORED", 0))
        with col5:
            st.metric("Reverted", status_counts.get("REVERTED", 0))

        # History table
        for proposal in proposals:
            status_emoji = {
                "PENDING": "⏳",
                "ADOPTED": "✅",
                "REJECTED": "❌",
                "IGNORED": "⏸",
                "REVERTED": "🔄",
            }.get(proposal["status"], "❓")

            st.markdown(
                f"{status_emoji} **{proposal['capability']}** — "
                f"`{proposal['proposal_id']}` — "
                f"{proposal['status']} — "
                f"{proposal['created_at'][:10]}"
            )

    except Exception as e:
        st.error(f"Error loading history: {e}")


def _render_variants_tab():
    """Render the strategy variants (R&D) tab."""
    st.subheader("Strategy Variants (R&D)")

    try:
        from src.persistence.db import PersistenceDB
        db = PersistenceDB()
        conn = db._get_conn()
        rows = conn.execute(
            "SELECT * FROM meta_strategy_variants ORDER BY created_at DESC LIMIT 20"
        ).fetchall()

        if not rows:
            st.info("No strategy variants yet. Create a variant to start R&D.")
            return

        for row in rows:
            stage_emoji = {
                "BACKTEST": "🧪",
                "SHADOW": "👁",
                "PAPER": "📝",
                "ADMISSION": "📋",
                "COOLING": "❄",
                "LIVE": "🟢",
            }.get(row["stage"], "❓")

            with st.expander(
                f"{stage_emoji} {row['variant_id']} — "
                f"{row['parent_strategy']} ({row['stage']})"
            ):
                st.json({
                    "variant_id": row["variant_id"],
                    "parent_strategy": row["parent_strategy"],
                    "mutation_type": row["mutation_type"],
                    "parameters": json.loads(row["parameters"] or "{}"),
                    "stage": row["stage"],
                    "admission_decision": row["admission_decision"],
                    "created_at": row["created_at"],
                })

    except Exception as e:
        st.error(f"Error loading variants: {e}")


def _render_drift_tab():
    """Render the drift monitor tab."""
    st.subheader("Drift Monitor")

    try:
        from src.meta.drift_detector import DriftDetector
        detector = DriftDetector()
        report = detector.check_drift()

        severity_emoji = {
            "NONE": "✅",
            "MILD": "⚠️",
            "MODERATE": "🟡",
            "SEVERE": "🟠",
            "CRITICAL": "🔴",
        }.get(report.severity, "❓")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Drift Severity", f"{severity_emoji} {report.severity}")
        with col2:
            st.metric("Days Since Adoption", report.days_since_adoption)
        with col3:
            st.metric(
                "Reversion Recommended",
                "Yes" if report.reversion_recommended else "No",
            )

        if report.metrics:
            st.subheader("Drift Metrics")
            for metric in report.metrics:
                status = "🔴 BREACHED" if metric.breached else "✅ OK"
                st.markdown(
                    f"**{metric.metric_name}**: "
                    f"{metric.baseline_value:.4f} → {metric.current_value:.4f} "
                    f"(change: {metric.change:+.4f}, threshold: {metric.threshold:.4f}) "
                    f"{status}"
                )

        if report.reversion_recommended:
            st.warning(
                f"⚠️ Reversion recommended: {report.reversion_reason}"
            )

    except Exception as e:
        st.error(f"Error checking drift: {e}")


def _render_run_tab():
    """Render the run capabilities tab."""
    st.subheader("Run Capabilities")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("🔄 Run Self-Optimization", use_container_width=True):
            with st.spinner("Running optimization..."):
                try:
                    from src.meta.workflow import MetaWorkflow
                    workflow = MetaWorkflow()
                    state = workflow.run_optimization()

                    if state.proposal:
                        st.success(f"Proposal generated: {state.proposal.proposal_id}")
                        st.rerun()
                    elif state.phase.value == "BLOCKED":
                        st.warning("Optimization blocked by gating conditions")
                    else:
                        st.info("No improvement found")
                except Exception as e:
                    st.error(f"Error: {e}")

        if st.button("📊 Run Leverage Evaluation", use_container_width=True):
            with st.spinner("Running leverage evaluation..."):
                try:
                    from src.meta.workflow import MetaWorkflow
                    workflow = MetaWorkflow()
                    state = workflow.run_leverage_evaluation()

                    if state.proposal:
                        st.success(f"Report generated: {state.proposal.report_id}")
                        st.rerun()
                    elif state.phase.value == "BLOCKED":
                        st.warning("Leverage evaluation blocked by gating conditions")
                    else:
                        st.info("No leverage report generated")
                except Exception as e:
                    st.error(f"Error: {e}")

    with col2:
        if st.button("📋 Run Policy Review", use_container_width=True):
            with st.spinner("Running policy review..."):
                try:
                    from src.meta.workflow import MetaWorkflow
                    workflow = MetaWorkflow()
                    state = workflow.run_policy_review()

                    if state.proposal:
                        st.success(f"Policy proposal generated: {state.proposal.proposal_id}")
                        st.rerun()
                    elif state.phase.value == "BLOCKED":
                        st.warning("Policy review blocked by gating conditions")
                    else:
                        st.info("No policy changes identified")
                except Exception as e:
                    st.error(f"Error: {e}")

        if st.button("🤖 Run LLM Tuning", use_container_width=True):
            with st.spinner("Running LLM tuning..."):
                try:
                    from src.meta.workflow import MetaWorkflow
                    workflow = MetaWorkflow()
                    state = workflow.run_llm_tuning()

                    if state.proposal:
                        st.success(f"LLM proposal generated: {state.proposal.proposal_id}")
                        st.rerun()
                    elif state.phase.value == "BLOCKED":
                        st.warning("LLM tuning blocked by gating conditions")
                    else:
                        st.info("No LLM improvement found")
                except Exception as e:
                    st.error(f"Error: {e}")


def _handle_decision(proposal_id: str, decision: str):
    """Handle a HITL decision on a proposal."""
    try:
        from src.persistence.db import PersistenceDB
        db = PersistenceDB()
        db.update_meta_proposal_status(proposal_id, decision)
        st.toast(f"Proposal {proposal_id} → {decision}")
    except Exception as e:
        st.error(f"Error recording decision: {e}")


# Page entry point for Streamlit multi-page app
if __name__ == "__main__":
    render_meta_optimization_page()
