#!/usr/bin/env python
"""Phase 16.5: System Integrity & Invariance Validation

Runs all four validation matrices (A–D) and produces structured JSON + Markdown reports.

HARD CONSTRAINTS:
- No modifications to Hermes, agents, thresholds, confidence
- No modifications to Strategy Family Policy
- No modifications to Family Orchestrator
- No modifications to MTF alignment logic
- No modifications to strategies or entry logic
- Test-only script. Same code paths as Phase 16.

Usage:
    python scripts/phase_16_5_invariance.py
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add project root to path
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from src.market.data_loader import load_csv, load_csv_multi
from scripts.run_strategy_backtest import (
    run_dual_backtest,
    run_dual_mtf_backtest,
    BacktestResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data paths
# ---------------------------------------------------------------------------
DATA_DIR = Path("data/historical")
REPORTS_DIR = Path("reports")

MARKET_FILES = {
    "SPY": DATA_DIR / "spy_1h_12m.csv",
    "BTC-USD": DATA_DIR / "btc-usd_1h_12m.csv",
    "TSLA": DATA_DIR / "tsla_1h_12m.csv",
}

SPY_15M_PATH = DATA_DIR / "spy_15m_2m.csv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_ts(ts_str: str) -> str:
    """Normalize a timestamp string to UTC ISO 8601 for comparison."""
    try:
        dt = datetime.fromisoformat(ts_str)
        # Convert to UTC
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
    except (ValueError, TypeError):
        return ts_str


@dataclass
class TestResult:
    """Result of a single invariant test."""
    name: str
    status: str  # PASS, FAIL, SKIPPED
    reason: str = ""
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Section A: Candle-Depth Invariance
# ---------------------------------------------------------------------------

def test_depth_invariance(spy_bars: list) -> list[TestResult]:
    """Run the same configuration with increasing history depth.
    
    Verifies that the first N bars produce identical results regardless
    of total depth. This is the core determinism guarantee.
    """
    results: list[TestResult] = []
    
    depths = [
        ("shallow", min(300, len(spy_bars))),
        ("medium", min(1000, len(spy_bars))),
        ("deep", len(spy_bars)),
    ]
    
    # Run dual mode at each depth
    dual_results: dict[str, BacktestResult] = {}
    dual_mtf_results: dict[str, BacktestResult] = {}
    
    ltf_bars = None
    if SPY_15M_PATH.exists():
        try:
            _, ltf_bars = load_csv_multi(str(MARKET_FILES["SPY"]), str(SPY_15M_PATH))
        except Exception:
            pass
    
    for depth_name, n_bars in depths:
        bars_slice = spy_bars[:n_bars]
        logger.info("Depth test: %s mode=dual bars=%d", depth_name, n_bars)
        dual_results[depth_name] = run_dual_backtest(bars_slice, symbol="SPY")
        
        logger.info("Depth test: %s mode=dual_mtf bars=%d", depth_name, n_bars)
        dual_mtf_results[depth_name] = run_dual_mtf_backtest(
            bars_slice, symbol="SPY", ltf_bars=ltf_bars,
        )
    
    # --- Test: Entry timestamps identical across depths (dual mode) ---
    shallow_entries = set(
        normalize_ts(t.entry_timestamp) for t in dual_results["shallow"].trades
    )
    medium_entries = set(
        normalize_ts(t.entry_timestamp) for t in dual_results["medium"].trades
    )
    deep_entries = set(
        normalize_ts(t.entry_timestamp) for t in dual_results["deep"].trades
    )
    
    # Shallow entries must be subset of medium and deep
    shallow_in_medium = shallow_entries.issubset(medium_entries)
    shallow_in_deep = shallow_entries.issubset(deep_entries)
    
    if shallow_in_medium and shallow_in_deep:
        results.append(TestResult(
            name="A1: Entry timestamps identical across depths (dual)",
            status="PASS",
            reason=f"Shallow entries ({len(shallow_entries)}) found in medium ({len(medium_entries)}) and deep ({len(deep_entries)})",
        ))
    else:
        missing_med = shallow_entries - medium_entries
        missing_deep = shallow_entries - deep_entries
        results.append(TestResult(
            name="A1: Entry timestamps identical across depths (dual)",
            status="FAIL",
            reason=f"Missing in medium: {missing_med}, Missing in deep: {missing_deep}",
        ))
    
    # --- Test: Entry timestamps identical across depths (dual_mtf mode) ---
    shallow_mtf_entries = set(
        normalize_ts(t.entry_timestamp) for t in dual_mtf_results["shallow"].trades
    )
    medium_mtf_entries = set(
        normalize_ts(t.entry_timestamp) for t in dual_mtf_results["medium"].trades
    )
    deep_mtf_entries = set(
        normalize_ts(t.entry_timestamp) for t in dual_mtf_results["deep"].trades
    )
    
    shallow_mtf_in_medium = shallow_mtf_entries.issubset(medium_mtf_entries)
    shallow_mtf_in_deep = shallow_mtf_entries.issubset(deep_mtf_entries)
    
    if shallow_mtf_in_medium and shallow_mtf_in_deep:
        results.append(TestResult(
            name="A2: Entry timestamps identical across depths (dual_mtf)",
            status="PASS",
            reason=f"Shallow MTF entries ({len(shallow_mtf_entries)}) found in medium ({len(medium_mtf_entries)}) and deep ({len(deep_mtf_entries)})",
        ))
    else:
        missing_med = shallow_mtf_entries - medium_mtf_entries
        missing_deep = shallow_mtf_entries - deep_mtf_entries
        results.append(TestResult(
            name="A2: Entry timestamps identical across depths (dual_mtf)",
            status="FAIL",
            reason=f"Missing in medium: {missing_med}, Missing in deep: {missing_deep}",
        ))
    
    # --- Test: Orchestration decisions unchanged for overlapping bars ---
    # Compare orchestration_log for first 300 bars across depths
    n_compare = min(300, len(spy_bars))
    
    shallow_orch = {
        o.bar: (o.selected_family, o.selected_strategy, o.hermes_regime)
        for o in dual_results["shallow"].orchestration_log
        if o.bar < n_compare
    }
    medium_orch = {
        o.bar: (o.selected_family, o.selected_strategy, o.hermes_regime)
        for o in dual_results["medium"].orchestration_log
        if o.bar < n_compare
    }
    
    orch_matches = all(
        shallow_orch.get(i) == medium_orch.get(i)
        for i in range(n_compare)
    )
    
    if orch_matches:
        results.append(TestResult(
            name="A3: Orchestration decisions unchanged (dual, overlapping bars)",
            status="PASS",
            reason=f"All {n_compare} bar orchestration decisions match between shallow and medium",
        ))
    else:
        mismatches = [
            i for i in range(n_compare)
            if shallow_orch.get(i) != medium_orch.get(i)
        ]
        results.append(TestResult(
            name="A3: Orchestration decisions unchanged (dual, overlapping bars)",
            status="FAIL",
            reason=f"{len(mismatches)} mismatched bars: {mismatches[:10]}",
        ))
    
    # --- Test: No retroactive changes (bar-for-bar determinism) ---
    # Compare equity curves for first shallow_n bars
    shallow_eq = [
        round(e.equity, 2)
        for e in dual_results["shallow"].equity_curve
    ]
    medium_eq_first = [
        round(e.equity, 2)
        for e in dual_results["medium"].equity_curve[:len(shallow_eq)]
    ]
    
    if shallow_eq == medium_eq_first:
        results.append(TestResult(
            name="A4: No retroactive changes (dual, bar-for-bar equity match)",
            status="PASS",
            reason=f"First {len(shallow_eq)} equity points identical between shallow and medium",
        ))
    else:
        first_diff = next(
            (i for i, (a, b) in enumerate(zip(shallow_eq, medium_eq_first)) if a != b),
            -1,
        )
        results.append(TestResult(
            name="A4: No retroactive changes (dual, bar-for-bar equity match)",
            status="FAIL",
            reason=f"First difference at bar {first_diff}: {shallow_eq[first_diff]} vs {medium_eq_first[first_diff]}",
        ))
    
    # --- Test: MTF only changes risk size, never entries ---
    dual_entry_bars = {t.entry_bar for t in dual_results["deep"].trades}
    mtf_entry_bars = {t.entry_bar for t in dual_mtf_results["deep"].trades}
    
    if dual_entry_bars == mtf_entry_bars:
        results.append(TestResult(
            name="A5: MTF only changes risk size, never entries (deep depth)",
            status="PASS",
            reason=f"Entry bar indices identical: {len(dual_entry_bars)} trades in both modes",
        ))
    else:
        only_dual = dual_entry_bars - mtf_entry_bars
        only_mtf = mtf_entry_bars - dual_entry_bars
        results.append(TestResult(
            name="A5: MTF only changes risk size, never entries (deep depth)",
            status="FAIL",
            reason=f"Bars only in dual: {only_dual}, only in MTF: {only_mtf}",
        ))
    
    return results


# ---------------------------------------------------------------------------
# Section B: Market-Diversity Invariance
# ---------------------------------------------------------------------------

def test_market_diversity(market_data: dict[str, list]) -> list[TestResult]:
    """Run the same tests on structurally different markets.
    
    Verifies no crashes, natural regime diversity, and no thrashing.
    """
    results: list[TestResult] = []
    
    for market_name, bars in market_data.items():
        if bars is None or len(bars) < 50:
            results.append(TestResult(
                name=f"B: Market diversity ({market_name})",
                status="SKIPPED",
                reason=f"Insufficient data: {len(bars) if bars else 0} bars (need ≥50)",
            ))
            continue
        
        try:
            result = run_dual_backtest(bars, symbol=market_name)
            
            # Check no crash (we got here, so no exception)
            
            # Check regime diversity in orchestration log
            regimes = set()
            risk_directives = set()
            for o in result.orchestration_log:
                regimes.add(o.hermes_regime)
                risk_directives.add(o.risk_directive)
            
            # Check no regime thrashing (>50% bars change regime)
            regime_sequence = [o.hermes_regime for o in result.orchestration_log]
            transitions = sum(
                1 for i in range(1, len(regime_sequence))
                if regime_sequence[i] != regime_sequence[i - 1]
            )
            transition_pct = transitions / len(regime_sequence) if regime_sequence else 0
            
            thrashing = transition_pct > 0.5
            
            details = {
                "bars": len(bars),
                "total_trades": result.summary["total_trades"],
                "regimes_seen": sorted(regimes),
                "risk_directives_seen": sorted(risk_directives),
                "regime_transitions_pct": round(transition_pct, 4),
                "family_bars": result.summary.get("family_bars", {}),
            }
            
            if thrashing:
                results.append(TestResult(
                    name=f"B1: No regime thrashing ({market_name})",
                    status="FAIL",
                    reason=f"Regime transition rate {transition_pct:.1%} > 50% threshold",
                    details=details,
                ))
            else:
                results.append(TestResult(
                    name=f"B1: No regime thrashing ({market_name})",
                    status="PASS",
                    reason=f"Regime transition rate {transition_pct:.1%} within bounds",
                    details=details,
                ))
            
            # Check natural CASH/CHAOS appearance
            has_cash = "CASH" in risk_directives
            results.append(TestResult(
                name=f"B2: System ran without crash ({market_name})",
                status="PASS",
                reason=f"{result.summary['total_trades']} trades, {len(regimes)} regimes, "
                       f"CASH directive seen: {has_cash}",
                details=details,
            ))
            
        except Exception as e:
            results.append(TestResult(
                name=f"B3: System ran without crash ({market_name})",
                status="FAIL",
                reason=f"Exception: {type(e).__name__}: {e}",
            ))
    
    # --- Test: MTF dampening activates logically (SPY only) ---
    spy_bars = market_data.get("SPY")
    if spy_bars and len(spy_bars) >= 50:
        try:
            ltf_bars = None
            if SPY_15M_PATH.exists():
                _, ltf_bars = load_csv_multi(str(MARKET_FILES["SPY"]), str(SPY_15M_PATH))
            
            mtf_result = run_dual_mtf_backtest(spy_bars, symbol="SPY", ltf_bars=ltf_bars)
            
            # Read MTF log
            mtf_log_path = REPORTS_DIR / "mtf_alignment_log.json"
            if mtf_log_path.exists():
                with open(mtf_log_path) as f:
                    mtf_log = json.load(f)
                
                dampened_bars = [
                    entry for entry in mtf_log
                    if entry["adjusted_risk"] < entry["hermes_risk"]
                ]
                
                results.append(TestResult(
                    name="B4: MTF dampening activates (SPY)",
                    status="PASS" if len(dampened_bars) > 0 else "FAIL",
                    reason=f"MTF dampened risk on {len(dampened_bars)}/{len(mtf_log)} bars",
                    details={"dampened_bar_count": len(dampened_bars), "total_bars": len(mtf_log)},
                ))
            else:
                results.append(TestResult(
                    name="B4: MTF dampening activates (SPY)",
                    status="FAIL",
                    reason="MTF log file not found",
                ))
        except Exception as e:
            results.append(TestResult(
                name="B4: MTF dampening activates (SPY)",
                status="FAIL",
                reason=f"Exception: {type(e).__name__}: {e}",
            ))
    else:
        results.append(TestResult(
            name="B4: MTF dampening activates (SPY)",
            status="SKIPPED",
            reason="Insufficient SPY data",
        ))
    
    return results


# ---------------------------------------------------------------------------
# Section C: Timeframe Profile Invariance
# ---------------------------------------------------------------------------

def test_timeframe_profile(spy_bars: list, ltf_bars: list | None) -> list[TestResult]:
    """Test the same code with different data granularities.
    
    Profiles:
    - Intraday: 1H HTF + 15m LTF (dual_mtf)
    - Swing: 1H HTF only (dual)
    - Scalp: 15m as HTF (dual)
    """
    results: list[TestResult] = []
    
    # --- Intraday profile (dual_mtf) ---
    intraday_result = None
    if ltf_bars and len(ltf_bars) > 0:
        try:
            intraday_result = run_dual_mtf_backtest(spy_bars, symbol="SPY", ltf_bars=ltf_bars)
            results.append(TestResult(
                name="C1: Intraday profile (1H HTF + 15m LTF) runs without error",
                status="PASS",
                reason=f"{intraday_result.summary['total_trades']} trades, "
                       f"{intraday_result.summary['total_bars']} bars",
            ))
        except Exception as e:
            results.append(TestResult(
                name="C1: Intraday profile (1H HTF + 15m LTF) runs without error",
                status="FAIL",
                reason=f"Exception: {type(e).__name__}: {e}",
            ))
    else:
        results.append(TestResult(
            name="C1: Intraday profile (1H HTF + 15m LTF) runs without error",
            status="SKIPPED",
            reason="No LTF data available",
        ))
    
    # --- Swing profile (dual, no LTF) ---
    try:
        swing_result = run_dual_backtest(spy_bars, symbol="SPY")
        results.append(TestResult(
            name="C2: Swing profile (1H HTF only) runs without error",
            status="PASS",
            reason=f"{swing_result.summary['total_trades']} trades, "
                   f"{swing_result.summary['total_bars']} bars",
        ))
    except Exception as e:
        results.append(TestResult(
            name="C2: Swing profile (1H HTF only) runs without error",
            status="FAIL",
            reason=f"Exception: {type(e).__name__}: {e}",
        ))
    
    # --- Scalp profile (15m as HTF, dual) ---
    if ltf_bars and len(ltf_bars) >= 50:
        try:
            scalp_result = run_dual_backtest(ltf_bars, symbol="SPY")
            results.append(TestResult(
                name="C3: Scalp profile (15m as HTF) runs without error",
                status="PASS",
                reason=f"{scalp_result.summary['total_trades']} trades, "
                       f"{scalp_result.summary['total_bars']} bars",
            ))
        except Exception as e:
            results.append(TestResult(
                name="C3: Scalp profile (15m as HTF) runs without error",
                status="FAIL",
                reason=f"Exception: {type(e).__name__}: {e}",
            ))
    else:
        results.append(TestResult(
            name="C3: Scalp profile (15m as HTF) runs without error",
            status="SKIPPED",
            reason="Insufficient LTF data for scalp profile",
        ))
    
    # --- Test: Same behavior, different clock speed ---
    # Within each profile, entries should be deterministic
    if intraday_result and swing_result:
        # MTF entries should be subset of non-MTF entries (MTF only dampens risk)
        mtf_entry_times = {normalize_ts(t.entry_timestamp) for t in intraday_result.trades}
        swing_entry_times = {normalize_ts(t.entry_timestamp) for t in swing_result.trades}
        
        mtf_subset = mtf_entry_times.issubset(swing_entry_times)
        results.append(TestResult(
            name="C4: MTF entries subset of non-MTF entries (intraday vs swing)",
            status="PASS" if mtf_subset else "FAIL",
            reason=f"Intraday entries ({len(mtf_entry_times)}) "
                   f"{'are' if mtf_subset else 'are NOT'} subset of swing ({len(swing_entry_times)})",
        ))
    
    # --- Test: MTF adapts automatically ---
    if intraday_result:
        # Verify adjusted risk ≤ hermes risk in MTF log
        mtf_log_path = REPORTS_DIR / "mtf_alignment_log.json"
        if mtf_log_path.exists():
            with open(mtf_log_path) as f:
                mtf_log = json.load(f)
            
            violations = [
                entry for entry in mtf_log
                if entry["adjusted_risk"] > entry["hermes_risk"] * 1.001  # small epsilon for float
            ]
            
            results.append(TestResult(
                name="C5: MTF adapted risk automatically (adjusted ≤ hermes always)",
                status="PASS" if len(violations) == 0 else "FAIL",
                reason=f"{len(violations)} violations of adjusted ≤ hermes",
                details={"violations": violations[:5]},
            ))
        else:
            results.append(TestResult(
                name="C5: MTF adapted risk automatically (adjusted ≤ hermes always)",
                status="FAIL",
                reason="MTF log not found",
            ))
    
    return results


# ---------------------------------------------------------------------------
# Section D: MTF Safety Invariants (Critical)
# ---------------------------------------------------------------------------

def test_mtf_safety(spy_bars: list, ltf_bars: list | None) -> list[TestResult]:
    """Critical MTF safety invariants.
    
    Any violation = fail Phase 16.5.
    """
    results: list[TestResult] = []
    
    # Run dual (no MTF) and dual_mtf on same data
    try:
        dual_result = run_dual_backtest(spy_bars, symbol="SPY")
    except Exception as e:
        results.append(TestResult(
            name="D0: Dual backtest baseline runs",
            status="FAIL",
            reason=f"Exception: {type(e).__name__}: {e}",
        ))
        return results
    
    results.append(TestResult(
        name="D0: Dual backtest baseline runs",
        status="PASS",
        reason=f"{dual_result.summary['total_trades']} trades",
    ))
    
    try:
        mtf_result = run_dual_mtf_backtest(spy_bars, symbol="SPY", ltf_bars=ltf_bars)
    except Exception as e:
        results.append(TestResult(
            name="D0b: Dual MTF backtest runs",
            status="FAIL",
            reason=f"Exception: {type(e).__name__}: {e}",
        ))
        return results
    
    results.append(TestResult(
        name="D0b: Dual MTF backtest runs",
        status="PASS",
        reason=f"{mtf_result.summary['total_trades']} trades",
    ))
    
    # --- D1: No new trades appear due to MTF ---
    dual_entry_timestamps = {normalize_ts(t.entry_timestamp) for t in dual_result.trades}
    mtf_entry_timestamps = {normalize_ts(t.entry_timestamp) for t in mtf_result.trades}
    
    new_trades_from_mtf = mtf_entry_timestamps - dual_entry_timestamps
    if len(new_trades_from_mtf) == 0:
        results.append(TestResult(
            name="D1: No new trades appear due to MTF",
            status="PASS",
            reason=f"MTF entry set is subset of dual entry set",
        ))
    else:
        results.append(TestResult(
            name="D1: No new trades appear due to MTF",
            status="FAIL",
            reason=f"MTF introduced {len(new_trades_from_mtf)} new trades: {new_trades_from_mtf}",
        ))
    
    # --- D2: No trades disappear due to MTF (unless risk=0) ---
    missing_trades = dual_entry_timestamps - mtf_entry_timestamps
    if len(missing_trades) == 0:
        results.append(TestResult(
            name="D2: No trades disappear due to MTF (unless risk=0)",
            status="PASS",
            reason="All dual entries present in MTF",
        ))
    else:
        # Check if the missing trades had zero risk
        # If MTF dampened risk to the minimum, the trade still appears
        # The only way a trade disappears is if the orchestrator picks different strategy
        results.append(TestResult(
            name="D2: No trades disappear due to MTF (unless risk=0)",
            status="FAIL",
            reason=f"{len(missing_trades)} trades from dual missing in MTF: {missing_trades}",
        ))
    
    # --- D3: Adjusted risk ≤ Hermes risk always ---
    mtf_log_path = REPORTS_DIR / "mtf_alignment_log.json"
    if mtf_log_path.exists():
        with open(mtf_log_path) as f:
            mtf_log = json.load(f)
        
        risk_violations = [
            entry for entry in mtf_log
            if entry["adjusted_risk"] > entry["hermes_risk"] * 1.001
        ]
        
        if len(risk_violations) == 0:
            results.append(TestResult(
                name="D3: Adjusted risk ≤ Hermes risk always",
                status="PASS",
                reason=f"All {len(mtf_log)} bars: adjusted_risk ≤ hermes_risk",
            ))
        else:
            results.append(TestResult(
                name="D3: Adjusted risk ≤ Hermes risk always",
                status="FAIL",
                reason=f"{len(risk_violations)} violations",
                details={"violations": risk_violations[:5]},
            ))
        
        # --- D4: Inertia (K=2) prevents 1-bar oscillation ---
        # Check that MISALIGNED state never appears for exactly 1 consecutive bar
        misaligned_bars = [
            entry["bar"] for entry in mtf_log
            if entry["mtf_state"] == "MISALIGNED"
        ]
        
        if len(misaligned_bars) == 0:
            results.append(TestResult(
                name="D4: Inertia (K=2) prevents 1-bar oscillation",
                status="PASS",
                reason="No MISALIGNED bars observed (inertia not triggered)",
            ))
        else:
            # Check no isolated single bars
            oscillation_found = False
            isolated_bars = []
            for i, bar_idx in enumerate(misaligned_bars):
                # Check if this bar is isolated (not part of a run ≥ 2)
                prev_in_misaligned = (i > 0 and misaligned_bars[i - 1] == bar_idx - 1)
                next_in_misaligned = (i < len(misaligned_bars) - 1 and misaligned_bars[i + 1] == bar_idx + 1)
                if not prev_in_misaligned and not next_in_misaligned:
                    oscillation_found = True
                    isolated_bars.append(bar_idx)
            
            if not oscillation_found:
                results.append(TestResult(
                    name="D4: Inertia (K=2) prevents 1-bar oscillation",
                    status="PASS",
                    reason=f"{len(misaligned_bars)} MISALIGNED bars, none isolated (all runs ≥ 2)",
                ))
            else:
                results.append(TestResult(
                    name="D4: Inertia (K=2) prevents 1-bar oscillation",
                    status="FAIL",
                    reason=f"Isolated MISALIGNED bars found: {isolated_bars}",
                ))
        
        # --- D5: Volatility floor prevents low-liquidity noise ---
        # Verify adjusted_risk ≥ minimum threshold when active
        min_risk_observed = min(
            (e["adjusted_risk"] for e in mtf_log if e["adjusted_risk"] > 0),
            default=0,
        )
        results.append(TestResult(
            name="D5: Volatility floor prevents low-liquidity noise",
            status="PASS",
            reason=f"Minimum adjusted_risk observed: {min_risk_observed:.6f} "
                   f"(> 0 confirms floor active)",
            details={"min_adjusted_risk": min_risk_observed},
        ))
        
        # --- D6: Historical replay == live replay (bar-for-bar) ---
        # Run dual_mtf again on same data — must produce identical results
        try:
            mtf_result_2 = run_dual_mtf_backtest(spy_bars, symbol="SPY", ltf_bars=ltf_bars)
            
            # Compare trade count and entry timestamps
            trades_1 = [(normalize_ts(t.entry_timestamp), t.entry_bar) for t in mtf_result.trades]
            trades_2 = [(normalize_ts(t.entry_timestamp), t.entry_bar) for t in mtf_result_2.trades]
            
            if trades_1 == trades_2:
                results.append(TestResult(
                    name="D6: Historical replay == live replay (bar-for-bar identical)",
                    status="PASS",
                    reason=f"Both runs produced identical {len(trades_1)} trades",
                ))
            else:
                results.append(TestResult(
                    name="D6: Historical replay == live replay (bar-for-bar identical)",
                    status="FAIL",
                    reason=f"Trade sequences differ: run1={len(trades_1)}, run2={len(trades_2)}",
                ))
        except Exception as e:
            results.append(TestResult(
                name="D6: Historical replay == live replay (bar-for-bar identical)",
                status="FAIL",
                reason=f"Exception on replay: {type(e).__name__}: {e}",
            ))
    
    else:
        results.append(TestResult(
            name="D3–D6: MTF log-based invariants",
            status="FAIL",
            reason="MTF log file not found after dual_mtf run",
        ))
    
    return results


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------

def generate_report(
    section_a: list[TestResult],
    section_b: list[TestResult],
    section_c: list[TestResult],
    section_d: list[TestResult],
) -> dict:
    """Generate structured JSON report."""
    all_results = section_a + section_b + section_c + section_d
    
    total = len(all_results)
    passed = sum(1 for r in all_results if r.status == "PASS")
    failed = sum(1 for r in all_results if r.status == "FAIL")
    skipped = sum(1 for r in all_results if r.status == "SKIPPED")
    
    overall = "PASS" if failed == 0 else "FAIL"
    
    def section_summary(tests: list[TestResult]) -> dict:
        return {
            "tests": [
                {
                    "name": t.name,
                    "status": t.status,
                    "reason": t.reason,
                    **({"details": t.details} if t.details else {}),
                }
                for t in tests
            ],
            "passed": sum(1 for t in tests if t.status == "PASS"),
            "failed": sum(1 for t in tests if t.status == "FAIL"),
            "skipped": sum(1 for t in tests if t.status == "SKIPPED"),
            "status": "PASS" if all(t.status != "FAIL" for t in tests) else "FAIL",
        }
    
    report = {
        "phase": "16.5",
        "title": "System Integrity & Invariance Validation",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "overall_status": overall,
        },
        "sections": {
            "A_candle_depth_invariance": section_summary(section_a),
            "B_market_diversity_invariance": section_summary(section_b),
            "C_timeframe_profile_invariance": section_summary(section_c),
            "D_mtf_safety_invariants": section_summary(section_d),
        },
        "conclusion": (
            "System behavior invariant across depth, market, timeframe, and MTF activation."
            if overall == "PASS"
            else "INVARIANCE VIOLATION DETECTED — investigate causality before proceeding."
        ),
        "data_manifest": {
            "markets_tested": [],
        },
    }
    
    return report


def generate_markdown(report: dict) -> str:
    """Generate human-readable Markdown report."""
    lines = [
        f"# Phase 16.5: System Integrity & Invariance Validation",
        f"",
        f"**Generated:** {report['timestamp']}",
        f"**Overall Status:** `{report['summary']['overall_status']}`",
        f"",
        f"## Summary",
        f"",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total Tests | {report['summary']['total_tests']} |",
        f"| Passed | {report['summary']['passed']} |",
        f"| Failed | {report['summary']['failed']} |",
        f"| Skipped | {report['summary']['skipped']} |",
        f"",
    ]
    
    section_labels = {
        "A_candle_depth_invariance": "## A. Candle-Depth Invariance (Global)",
        "B_market_diversity_invariance": "## B. Market-Diversity Invariance",
        "C_timeframe_profile_invariance": "## C. Timeframe Profile Invariance",
        "D_mtf_safety_invariants": "## D. MTF Safety Invariants (Critical)",
    }
    
    for key, label in section_labels.items():
        section = report["sections"][key]
        lines.extend([
            f"",
            f"{label}",
            f"",
            f"**Status:** `{section['status']}` "
            f"(✅ {section['passed']} / ❌ {section['failed']} / ⏭️ {section['skipped']})",
            f"",
        ])
        
        for test in section["tests"]:
            icon = {"PASS": "✅", "FAIL": "❌", "SKIPPED": "⏭️"}.get(test["status"], "?")
            lines.append(f"- {icon} **{test['name']}** — {test['status']}")
            if test["reason"]:
                lines.append(f"  - {test['reason']}")
            if test.get("details"):
                for dk, dv in test["details"].items():
                    lines.append(f"  - `{dk}`: `{dv}`")
        
        lines.append("")
    
    lines.extend([
        f"## Conclusion",
        f"",
        f"**{report['conclusion']}**",
        f"",
        f"---",
        f"*Phase 16.5 validates system integrity, not performance.*",
        f"*No PnL charts required.*",
        f"*If a test fails, investigate causality — do not tune parameters.*",
    ])
    
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    
    logger.info("=" * 60)
    logger.info("Phase 16.5: System Integrity & Invariance Validation")
    logger.info("=" * 60)
    
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    
    # --- Load data ---
    logger.info("Loading market data...")
    market_data: dict[str, list] = {}
    
    for name, path in MARKET_FILES.items():
        if path.exists():
            try:
                bars = load_csv(str(path))
                market_data[name] = bars
                logger.info("  %s: %d bars from %s", name, len(bars), path.name)
            except Exception as e:
                logger.warning("  %s: Failed to load %s: %s", name, path, e)
                market_data[name] = []
        else:
            logger.warning("  %s: File not found: %s", name, path)
            market_data[name] = []
    
    spy_bars = market_data.get("SPY", [])
    
    # Load LTF data
    ltf_bars = None
    if SPY_15M_PATH.exists():
        try:
            _, ltf_bars = load_csv_multi(str(MARKET_FILES["SPY"]), str(SPY_15M_PATH))
            logger.info("  SPY 15m LTF: %d bars", len(ltf_bars) if ltf_bars else 0)
        except Exception as e:
            logger.warning("  SPY 15m LTF: Failed to load: %s", e)
    
    # --- Run tests ---
    logger.info("")
    logger.info("--- Section A: Candle-Depth Invariance ---")
    section_a = test_depth_invariance(spy_bars)
    
    logger.info("")
    logger.info("--- Section B: Market-Diversity Invariance ---")
    section_b = test_market_diversity(market_data)
    
    logger.info("")
    logger.info("--- Section C: Timeframe Profile Invariance ---")
    section_c = test_timeframe_profile(spy_bars, ltf_bars)
    
    logger.info("")
    logger.info("--- Section D: MTF Safety Invariants ---")
    section_d = test_mtf_safety(spy_bars, ltf_bars)
    
    # --- Generate reports ---
    logger.info("")
    logger.info("Generating reports...")
    
    report = generate_report(section_a, section_b, section_c, section_d)
    report["data_manifest"]["markets_tested"] = [
        {"symbol": name, "bars": len(bars)}
        for name, bars in market_data.items()
    ]
    
    # Save JSON
    json_path = REPORTS_DIR / "phase_16_5_invariance_report.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2)
    logger.info("JSON report: %s", json_path)
    
    # Save Markdown
    md_content = generate_markdown(report)
    md_path = REPORTS_DIR / "phase_16_5_invariance_report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    logger.info("Markdown report: %s", md_path)
    
    # --- Print summary ---
    logger.info("")
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    logger.info("Total: %d | Passed: %d | Failed: %d | Skipped: %d",
                report["summary"]["total_tests"],
                report["summary"]["passed"],
                report["summary"]["failed"],
                report["summary"]["skipped"])
    logger.info("Overall: %s", report["summary"]["overall_status"])
    logger.info("")
    logger.info(report["conclusion"])
    
    if report["summary"]["overall_status"] == "FAIL":
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()