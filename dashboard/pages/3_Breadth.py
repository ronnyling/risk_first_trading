"""Breadth Expansion Workflow — Dashboard page.

Provides the HITL control surface for the continuous breadth expansion
workflow (Phases A→B→C→D). Operators can run audits, review proposals,
and approve/reject/ignore expansion decisions.
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

from breadth.analyzer import EdgeAnalyzer
from breadth.expander import SymbolExpander
from breadth.family_enforcer import FamilyEnforcer
from breadth.models import BreadthWorkflowState, WorkflowPhase
from breadth.timeframe_evaluator import TimeframeEvaluator
from breadth.workflow import BreadthWorkflow
from persistence.db import PersistenceDB

# ──────────────────────────────────────────────────────
# Page config
# ──────────────────────────────────────────────────────

st.set_page_config(
    page_title="Breadth Expansion",
    page_icon="B",
    layout="wide",
)

st.title("Breadth Expansion Workflow")

# ── Phase F: Mode Banner ──────────────────────────────
try:
    from visualization.mode_banner import render_mode_banner, get_mode_emoji
    _sys_mode = st.session_state.get("system_mode", "ADVISORY")
    _mode_data = render_mode_banner(_sys_mode)
    st.markdown(_mode_data["html"], unsafe_allow_html=True)
except Exception:
    pass

# ──────────────────────────────────────────────────────
# Session state
# ──────────────────────────────────────────────────────

if "breadth_workflow" not in st.session_state:
    st.session_state["breadth_workflow"] = None

# ──────────────────────────────────────────────────────
# Initialize workflow
# ──────────────────────────────────────────────────────

workflow: BreadthWorkflow = st.session_state.get("breadth_workflow")
if workflow is None:
    workflow = BreadthWorkflow()
    st.session_state["breadth_workflow"] = workflow

state: BreadthWorkflowState = workflow.get_state()

# ──────────────────────────────────────────────────────
# Phase indicator
# ──────────────────────────────────────────────────────

phase_colors = {
    WorkflowPhase.IDLE: "⚪",
    WorkflowPhase.AUDIT: "🔵",
    WorkflowPhase.EXPANSION: "🟡",
    WorkflowPhase.FAMILY: "🟢",
    WorkflowPhase.TIMEFRAME: "🟠",
    WorkflowPhase.AWAITING_HIL: "🔴",
    WorkflowPhase.COMPLETE: "✅",
}

current_phase_icon = phase_colors.get(state.phase, "⚪")
st.markdown(f"### {current_phase_icon} Current Phase: **{state.phase.value}**")

if state.started_at:
    st.caption(f"Cycle started: {state.started_at}")

# ──────────────────────────────────────────────────────
# Action buttons
# ──────────────────────────────────────────────────────

col1, col2, col3, col4 = st.columns(4)

with col1:
    if st.button("🔄 Start New Audit", use_container_width=True):
        with st.spinner("Running breadth audit..."):
            state = workflow.start_cycle()
            st.rerun()

with col2:
    if state.phase == WorkflowPhase.AUDIT and state.audit_report:
        if st.button("📊 Generate Proposal", use_container_width=True):
            with st.spinner("Generating expansion proposal..."):
                state = workflow.advance_to_expansion()
                st.rerun()

with col3:
    if state.phase == WorkflowPhase.AWAITING_HIL and state.expansion_proposal:
        if st.button("✅ Approve", use_container_width=True, type="primary"):
            with st.spinner("Applying expansion..."):
                state = workflow.approve_expansion("Operator approved via dashboard")
                st.rerun()

with col4:
    if state.phase == WorkflowPhase.AWAITING_HIL and state.expansion_proposal:
        if st.button("❌ Reject", use_container_width=True):
            state = workflow.reject_expansion("Operator rejected via dashboard")
            st.rerun()

# Ignore button (separate row)
if state.phase == WorkflowPhase.AWAITING_HIL and state.expansion_proposal:
    if st.button("⏸ Ignore", use_container_width=False):
        state = workflow.ignore_proposal()
        st.rerun()

st.divider()

# ──────────────────────────────────────────────────────
# Tabs
# ──────────────────────────────────────────────────────

tab_audit, tab_proposal, tab_family, tab_timeframe, tab_history = st.tabs([
    "📋 Audit Report",
    "📦 Expansion Proposal",
    "👨‍👩‍👧‍👦 Family Enforcement",
    "⏱ Timeframe Proposal",
    "📜 History",
])

# ──────────────────────────────────────────────────────
# Tab 1: Audit Report
# ──────────────────────────────────────────────────────

with tab_audit:
    if state.audit_report is None:
        st.info("No audit report yet. Click 'Start New Audit' to begin.")
    else:
        report = state.audit_report

        st.subheader("Current Universe")
        st.write(f"**Symbols ({len(report.current_symbols)}):** {', '.join(report.current_symbols)}")
        st.write(f"**Scaling Profile:** {report.current_scaling_profile}")
        st.write(f"**Data Points Used:** {report.data_points_used}")

        st.subheader("Strategy × Regime Expectancy")
        if report.strategy_regime_expectancy:
            expectancy_data = []
            for s in report.strategy_regime_expectancy:
                expectancy_data.append({
                    "Strategy": s.strategy_id,
                    "Regime": s.regime,
                    "Trades": s.total_trades,
                    "Win Rate": f"{s.win_rate:.1%}",
                    "Avg PnL": f"{s.avg_pnl:.4f}",
                    "Expectancy": f"{s.expectancy:.4f}",
                })
            st.dataframe(expectancy_data, use_container_width=True)
        else:
            st.info("No strategy expectancy data available.")

        st.subheader("Confidence Buckets")
        if report.confidence_buckets:
            bucket_data = []
            for b in report.confidence_buckets:
                bucket_data.append({
                    "Bucket": b.bucket_label,
                    "Trades": b.trade_count,
                    "Win Rate": f"{b.win_rate:.1%}",
                    "Avg PnL": f"{b.avg_pnl:.4f}",
                })
            st.dataframe(bucket_data, use_container_width=True)
        else:
            st.info("No confidence bucket data available.")

        st.subheader("Correlation Clusters")
        if report.correlation_clusters:
            for cluster in report.correlation_clusters:
                st.write(
                    f"**Cluster {cluster.cluster_id}** ({len(cluster.symbols)} symbols, "
                    f"avg |r|={cluster.avg_internal_correlation:.2f}): "
                    f"{', '.join(cluster.symbols)}"
                )
        else:
            st.info("No correlation clusters computed.")

        st.subheader("Recommendations")
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.metric("Positive Edge Strategies", len(report.positive_edge_strategies))
            if report.positive_edge_strategies:
                st.write(", ".join(report.positive_edge_strategies))
        with col_b:
            st.metric("Diversifying Symbols", len(report.diversifying_symbols))
            if report.diversifying_symbols:
                st.write(", ".join(report.diversifying_symbols))
        with col_c:
            st.metric("Redundant Symbols", len(report.redundant_symbols))
            if report.redundant_symbols:
                st.write(", ".join(report.redundant_symbols))

# ──────────────────────────────────────────────────────
# Tab 2: Expansion Proposal
# ──────────────────────────────────────────────────────

with tab_proposal:
    if state.expansion_proposal is None:
        st.info("No expansion proposal yet. Run an audit first, then generate a proposal.")
    else:
        proposal = state.expansion_proposal

        # Status badge
        status_colors = {
            "PENDING": "🟡",
            "APPROVED": "🟢",
            "REJECTED": "🔴",
            "IGNORED": "⚪",
        }
        st.subheader(
            f"{status_colors.get(proposal.status, '⚪')} Proposal: {proposal.status}"
        )

        st.write(f"**Proposal ID:** {proposal.proposal_id}")
        st.write(f"**Created:** {proposal.created_at}")
        if proposal.decided_at:
            st.write(f"**Decided:** {proposal.decided_at}")
        if proposal.decision_reason:
            st.write(f"**Reason:** {proposal.decision_reason}")

        st.subheader("Current Universe")
        st.write(f"**{len(proposal.current_symbols)} symbols:** {', '.join(proposal.current_symbols)}")

        st.subheader("Proposed Additions")
        if proposal.proposed_additions:
            additions_data = []
            for c in proposal.proposed_additions:
                additions_data.append({
                    "Symbol": c.symbol,
                    "Pool": c.pool,
                    "Bucket": c.bucket,
                    "Avg |r|": f"{c.avg_correlation_with_existing:.3f}",
                    "Max |r|": f"{c.max_correlation_with_existing:.3f}",
                    "Low Corr": "✅" if c.is_low_correlation else "❌",
                })
            st.dataframe(additions_data, use_container_width=True)
        else:
            st.info("No candidates proposed.")

        st.subheader("Risk Impact")
        if proposal.risk_impacts:
            risk_data = []
            for r in proposal.risk_impacts:
                risk_data.append({
                    "Symbol": r.symbol,
                    "Projected Risk": f"{r.projected_portfolio_risk:.4f}",
                    "Risk Change": f"{r.risk_change:.4f}",
                    "Corr-Adjusted": f"{r.correlation_adjusted_change:.4f}",
                    "Within Budget": "✅" if r.within_budget else "❌",
                })
            st.dataframe(risk_data, use_container_width=True)

        st.subheader("Summary")
        st.write(f"**Total Symbols After:** {proposal.total_symbols_after}")
        st.write(f"**Within Profile Limit:** {'✅' if proposal.within_profile_limit else '❌'}")
        st.write(f"**Correlation Diversity Score:** {proposal.correlation_diversity_score:.2f}")
        st.write(f"**Scaling Profile:** {proposal.scaling_profile}")

# ──────────────────────────────────────────────────────
# Tab 3: Family Enforcement
# ──────────────────────────────────────────────────────

with tab_family:
    if not state.family_directives:
        st.info("No family directives yet. Approve an expansion proposal first.")
    else:
        st.subheader("Family Assignments")
        for directive in state.family_directives:
            if hasattr(directive, "symbol"):
                st.write(
                    f"**{directive.symbol}** ({directive.bucket}): "
                    f"{', '.join(directive.assigned_families)}"
                )

# ──────────────────────────────────────────────────────
# Tab 4: Timeframe Proposal
# ──────────────────────────────────────────────────────

with tab_timeframe:
    if state.timeframe_proposal is None:
        st.info(
            "No timeframe proposal. This phase is optional and only activates "
            "when gating conditions are met (MEDIUM/LARGE profile, stable breadth)."
        )
    else:
        tf = state.timeframe_proposal
        st.subheader(f"Timeframe Proposal: {tf.status}")
        st.write(f"**Current:** {tf.current_timeframe}")
        st.write(f"**Proposed:** {tf.proposed_timeframe}")
        st.write(f"**Symbols Affected:** {len(tf.symbols_affected)}")
        st.write(f"**Opportunity Increase:** {tf.marginal_opportunity_increase:.0%}")
        st.write(f"**HTF/LTF Alignment:** {tf.htf_ltf_alignment_score:.2f}")
        st.write(f"**Risk Impact:** {tf.risk_impact_summary}")

# ──────────────────────────────────────────────────────
# Tab 5: History
# ──────────────────────────────────────────────────────

with tab_history:
    st.subheader("Workflow History")

    # In-memory history
    if state.history:
        st.markdown("**Current Cycle Events:**")
        for event in reversed(state.history):
            st.write(
                f"- [{event.get('created_at', '')}] "
                f"**{event.get('phase', '')}** — {event.get('event_type', '')}"
            )
            data = event.get("event_data", {})
            if data:
                st.json(data)
    else:
        st.info("No events in current cycle.")

    # Database history
    st.subheader("All Past Events")
    try:
        db = PersistenceDB()
        history = db.get_workflow_history(limit=20)
        if history:
            for event in history:
                st.write(
                    f"- [{event['created_at']}] "
                    f"**{event['workflow_phase']}** — {event['event_type']}"
                )
        else:
            st.info("No workflow events recorded yet.")
    except Exception as e:
        st.warning(f"Could not load history: {e}")
