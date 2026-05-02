"""Hermes Observability Dashboard — Single cascading page.

Production observability interface. Read-only main surface.
All actions consolidated to the sidebar (hamburger panel).

Data sources:
    data/state_snapshot.json   — engine state (written by run_engine.py)
    data/health_events.jsonl   — health events (written by EventLogWriter)
    data/hermes_*.json         — Hermes proposals, alerts, runs
    data/universe_*.json       — universe policy versions
    config/policy.yaml         — live policy config
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml
from streamlit_autorefresh import st_autorefresh

# Add src to Python path for imports
_root = str(Path(__file__).resolve().parent.parent)
src_path = os.path.join(_root, "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)
# Also add project root so internal `from src.*` imports resolve
if _root not in sys.path:
    sys.path.insert(0, _root)

from core.events import HealthEvents
from monitoring.event_log import DEFAULT_LOG_PATH, read_new_events
from market.live_data import fetch_bars
from market.regime import RegimeDetector
from hermes.agents.base import MarketState
from hermes.agents.stub_agents import IchimokuAgent, VolatilityAgent, AMTAgent, WyckoffAgent
from hermes.coordinator import AccountState, HermesCoordinator, PreviousState
from hermes.registry import AgentRegistry
from hermes.scoring import ScoringEngine
from hermes.conflict import ConflictResolver
from hermes.sizing import PositionSizer
from operations.universe_reader import UniverseReader
from core.types import Bar, Regime

# ──────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────

st.set_page_config(
    page_title="Hermes Observability",
    page_icon="H",
    layout="wide",
    initial_sidebar_state="expanded",
)

SNAPSHOT_PATH = Path("data/state_snapshot.json")
POLICY_PATH = Path("config/policy.yaml")
UNIVERSE_POINTER_PATH = Path("data/universe_current.json")
HEALTH_LOG_PATH = Path(DEFAULT_LOG_PATH)

# ──────────────────────────────────────────────────────
# Session state defaults
# ──────────────────────────────────────────────────────

if "auto_refresh" not in st.session_state:
    st.session_state["auto_refresh"] = True
if "health_notifications" not in st.session_state:
    st.session_state["health_notifications"] = []
if "execution_paused" not in st.session_state:
    st.session_state["execution_paused"] = False
if "last_event_line_offset" not in st.session_state:
    st.session_state["last_event_line_offset"] = 0
if "last_event_timestamp" not in st.session_state:
    st.session_state["last_event_timestamp"] = ""
if "confirm_reset" not in st.session_state:
    st.session_state["confirm_reset"] = False
if "show_readme" not in st.session_state:
    st.session_state["show_readme"] = False
if "hermes_running" not in st.session_state:
    st.session_state["hermes_running"] = False
if "hermes_cancel" not in st.session_state:
    st.session_state["hermes_cancel"] = False
if "hermes_last_result" not in st.session_state:
    st.session_state["hermes_last_result"] = None
if "stream_fetcher" not in st.session_state:
    st.session_state["stream_fetcher"] = None
if "stream_mode" not in st.session_state:
    st.session_state["stream_mode"] = "snapshot"
if "breadth_workflow" not in st.session_state:
    st.session_state["breadth_workflow"] = None
if "meta_workflow" not in st.session_state:
    st.session_state["meta_workflow"] = None
if "system_mode" not in st.session_state:
    st.session_state["system_mode"] = "ADVISORY"
if "log_verbosity" not in st.session_state:
    st.session_state["log_verbosity"] = "LOW"


# ──────────────────────────────────────────────────────
# Helper functions (defined before any UI code)
# ──────────────────────────────────────────────────────


def load_snapshot() -> dict:
    if not SNAPSHOT_PATH.exists():
        return {}
    try:
        return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_hermes_files(directory: str) -> list[Path]:
    p = Path(directory)
    if not p.exists():
        return []
    return sorted(p.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)


def format_duration(td: timedelta) -> str:
    total_seconds = int(td.total_seconds())
    if total_seconds < 60:
        return f"{total_seconds}s"
    if total_seconds < 3600:
        m, s = divmod(total_seconds, 60)
        return f"{m}m {s}s"
    h, remainder = divmod(total_seconds, 3600)
    m, s = divmod(remainder, 60)
    return f"{h}h {m}m"


# ──────────────────────────────────────────────────────
# Universe resolution & multi-symbol helpers
# ──────────────────────────────────────────────────────

def _resolve_universe_symbols() -> list[str]:
    """Read the active universe and return the list of symbol strings.

    Reads universe_current.json → resolves the version file → extracts
    market keys.  Returns an empty list when no universe is configured.
    """
    if not UNIVERSE_POINTER_PATH.exists():
        return []
    ptr = load_json(UNIVERSE_POINTER_PATH)
    if not ptr:
        return []
    version_file = ptr.get("current_version_file")
    if not version_file:
        return []
    univ_path = Path("data") / version_file
    univ_data = load_json(univ_path)
    if not univ_data:
        return []
    markets = univ_data.get("markets", {})
    return list(markets.keys())


def _format_symbol_list(symbols: list[str], max_display: int = 2) -> str:
    """Format a symbol list for sidebar display.

    If <= max_display symbols, show all.  Otherwise show first max_display
    + '+N more'.
    """
    if not symbols:
        return "no symbols"
    if len(symbols) <= max_display:
        return ", ".join(symbols)
    shown = symbols[:max_display]
    remaining = len(symbols) - max_display
    return f"{', '.join(shown)} +{remaining} more"


def _build_market_states_live(mode: str = "snapshot") -> list[MarketState]:
    """Build MarketStates from live data for all universe symbols.

    Uses UniverseReader to resolve the active universe, then fetches
    live bars via yfinance for each symbol.

    Args:
        mode: "snapshot" (default) — fetch bars directly via fetch_bars().
              "streaming" — read from StreamFetcher buffers, fallback to
              snapshot if buffer is DEAD or missing.

    Raises:
        RuntimeError: If no universe symbols are configured or any
            symbol's live data is unavailable.

    Production data source:
        yfinance is considered a production live-data adapter for Hermes
        advisory runs until the Alpaca data subscription is formally enabled.
    """
    reader = UniverseReader()
    symbols = reader.get_enabled_markets()
    if not symbols:
        raise RuntimeError("No universe symbols configured")

    # Scaling validation: check universe size against active profile
    try:
        from src.operations.scaling import ScalingConfig
        _scale_cfg = ScalingConfig()
        _ok, _reason = _scale_cfg.validate_universe_size(symbols)
        if not _ok:
            _profile = _scale_cfg.load_active_profile()
            st.warning(f"Universe scaling limit: {_reason}")
            symbols = symbols[:_profile.max_symbols]
    except Exception:
        pass  # Scaling config unavailable — proceed with all symbols

    regime_detector = RegimeDetector()
    market_states: list[MarketState] = []

    # Streaming mode: read from buffers
    stream_fetcher = st.session_state.get("stream_fetcher") if mode == "streaming" else None

    for symbol in symbols:
        bars = None

        if stream_fetcher is not None:
            buffer = stream_fetcher.get_buffer(symbol)
            if buffer is not None and buffer.is_usable():
                bars = buffer.get_snapshot(200)
                # Time alignment: filter to bars <= minimum newest timestamp
                # (applied later when all symbols are collected)

        # Fallback to snapshot mode
        if bars is None:
            bars = fetch_bars(symbol)  # raises on failure

        regime = regime_detector.update(bars)
        market_states.append(MarketState(
            symbol=symbol,
            bars=bars,
            regime=regime,
            regime_confidence=0.5,
            volatility=None,
            timestamp=bars[-1].timestamp,
        ))

    # Time alignment for streaming mode
    if mode == "streaming" and stream_fetcher is not None and len(market_states) > 1:
        _align_streaming_timestamps(market_states, stream_fetcher)

    return market_states


def _align_streaming_timestamps(
    market_states: list[MarketState],
    stream_fetcher,
) -> None:
    """Align all MarketStates to the minimum newest timestamp across buffers.

    This ensures all symbols see bars up to the same point in time,
    preventing temporal misalignment in Hermes reasoning.
    """
    # Find the minimum newest timestamp across all buffers
    min_newest = None
    for ms in market_states:
        buffer = stream_fetcher.get_buffer(ms.symbol)
        if buffer is not None:
            newest = buffer.newest_timestamp
            if newest is not None:
                if min_newest is None or newest < min_newest:
                    min_newest = newest

    if min_newest is None:
        return

    # Filter each market state's bars to timestamps <= min_newest
    for i, ms in enumerate(market_states):
        aligned_bars = [b for b in ms.bars if b.timestamp <= min_newest]
        if len(aligned_bars) < 52:
            # Not enough aligned bars — keep original (agent will handle)
            continue
        market_states[i] = MarketState(
            symbol=ms.symbol,
            bars=aligned_bars,
            regime=ms.regime,
            regime_confidence=ms.regime_confidence,
            volatility=ms.volatility,
            timestamp=aligned_bars[-1].timestamp,
        )


# Human-readable labels for health event types
_HEALTH_EVENT_LABELS: dict[str, str] = {
    HealthEvents.ALPACA_DISCONNECTED: "Alpaca disconnected",
    HealthEvents.ALPACA_RESTORED: "Alpaca restored",
    HealthEvents.EXECUTION_PAUSED: "Execution paused",
    HealthEvents.EXECUTION_RESUMED: "Execution resumed",
    HealthEvents.DATA_STALE: "Data feed stale",
    HealthEvents.DATA_FEED_RESTORED: "Data feed restored",
    HealthEvents.HERMES_UNAVAILABLE: "Hermes unavailable",
    HealthEvents.HERMES_RESTORED: "Hermes restored",
    HealthEvents.HERMES_RUN_COMPLETED: "Hermes run completed",
    HealthEvents.FILE_SYSTEM_DEGRADED: "File system degraded",
    HealthEvents.FILE_SYSTEM_RESTORED: "File system restored",
    HealthEvents.POLICY_DEGRADED: "Policy degraded",
    HealthEvents.POLICY_RESTORED: "Policy restored",
}


def archive_and_reset() -> tuple[int, str]:
    """Archive all Hermes artifacts and reset to clean idle state."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_base = Path("archive") / f"pre_reset_{timestamp}"
    dirs_to_reset = [
        Path("data/hermes_runs"),
        Path("data/hermes_proposals"),
        Path("data/hermes_alerts"),
        Path("docs/hermes_actions"),
    ]
    archived_count = 0
    for d in dirs_to_reset:
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.is_file() and f.name != ".gitkeep":
                rel = f.relative_to(Path("."))
                dest = archive_base / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), str(dest))
                archived_count += 1
    reason_path = archive_base / "RESET_REASON.md"
    reason_path.parent.mkdir(parents=True, exist_ok=True)
    reason_path.write_text(
        f"# System Reset\n\n**Date:** {datetime.now().isoformat()}\n"
        f"**Trigger:** Operator-initiated via Streamlit\n"
        f"**Files archived:** {archived_count}\n",
        encoding="utf-8",
    )
    return archived_count, str(archive_base)


def restore_archive(archive_dir: Path) -> int:
    """Restore archived artifacts back to live directories."""
    restored_count = 0
    for item in archive_dir.rglob("*"):
        if item.is_file() and item.name != "RESET_REASON.md":
            parts = item.parts
            try:
                reset_idx = next(i for i, p in enumerate(parts) if p.startswith("pre_reset_"))
                live_rel = Path(*parts[reset_idx + 1:])
                live_dest = Path(".") / live_rel
                live_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(item), str(live_dest))
                restored_count += 1
            except (StopIteration, IndexError):
                continue
    return restored_count


def trigger_hermes_run(cancel_check=None, run_mode: str = "Manual", data_mode: str = "snapshot") -> dict:
    """Evaluate all active universe symbols in a single Hermes batch run.

    Builds MarketStates from live data for all universe symbols,
    runs Hermes agents on each via a single coordinator invocation,
    and writes per-symbol run summary, proposals, and alerts to disk.

    Args:
        cancel_check: Optional callable that returns True if cancelled.
        run_mode: Attribution label — "Manual" or "Scheduled".
        data_mode: "snapshot" for direct fetch, "streaming" for buffer reads.

    Returns:
        Dict with run_id, per-symbol decisions, proposals, alerts, and status.
    """
    import uuid
    from datetime import datetime as dt

    run_id = f"{run_mode.lower()}_{dt.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:6]}"
    started_at = dt.now()
    results = {
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "status": "running",
        "markets_evaluated": 0,
        "symbols_analyzed": [],
        "per_symbol_decisions": {},
        "proposals": [],
        "alerts": [],
        "error": None,
    }

    try:
        # Check cancel before loading data
        if cancel_check and cancel_check():
            results["status"] = "cancelled"
            return results

        # ── Resolve universe symbols and build MarketStates from LIVE data ──
        # Production data source: yfinance (raises on failure)
        market_states = _build_market_states_live(mode=data_mode)

        if not market_states:
            results["status"] = "error"
            results["error"] = "No universe symbols configured"
            return results

        # ── Build AccountState (shared across all symbols) ──
        snapshot = {}
        snp_path = Path("data/state_snapshot.json")
        if snp_path.exists():
            try:
                snapshot = json.loads(snp_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        equity = snapshot.get("equity", 100_000.0)
        dd_pct = snapshot.get("current_drawdown_pct", 0.0) / 100.0

        account_state = AccountState(
            equity=equity,
            peak_equity=equity / (1.0 - dd_pct) if dd_pct < 1.0 else equity,
            current_drawdown=dd_pct,
            max_risk_per_trade=0.01,
            max_portfolio_risk=0.05,
        )

        # Check cancel before running agents
        if cancel_check and cancel_check():
            results["status"] = "cancelled"
            return results

        # ── Build coordinator (shared across all symbols) ──
        registry = AgentRegistry()
        registry.register(IchimokuAgent())
        registry.register(VolatilityAgent())
        registry.register(AMTAgent())
        registry.register(WyckoffAgent())

        coordinator = HermesCoordinator(
            registry=registry,
            scoring=ScoringEngine(),
            conflict=ConflictResolver(),
            sizing=PositionSizer(),
        )

        # ── SINGLE coordinator invocation — batch evaluation ──
        # Hermes studies the whole opportunity set at once.
        # Compute correlation matrix for portfolio-level adjustments
        from src.hermes.correlation import CorrelationEngine
        corr_engine = CorrelationEngine(window=50, threshold=0.75)
        corr_matrix = corr_engine.compute(market_states)

        decisions = coordinator.run_batch(
            market_states, account_state, correlation=corr_matrix,
        )

        # ── Generate per-symbol proposals and alerts from batch decisions ──
        proposals_generated = 0
        alerts_generated = 0
        symbol_decisions: dict[str, dict] = {}

        for symbol, decision in decisions.items():
            decision_dict = {
                "regime": decision.regime,
                "risk_directive": decision.risk_directive,
                "composite_score": round(decision.composite_score, 4),
                "confidence": round(decision.confidence, 4),
                "allowed_family": decision.allowed_strategy_family,
                "per_trade_risk": round(decision.per_trade_risk, 6),
                "portfolio_risk": round(decision.portfolio_risk, 6),
                "reasoning": decision.reasoning,
                "agent_scores": {k: round(v, 4) for k, v in decision.agent_scores.items()},
                "agent_confidences": {k: round(v, 4) for k, v in decision.agent_confidences.items()},
            }
            symbol_decisions[symbol] = decision_dict

            # ── Generate proposal if risk_directive is not CASH ──
            if decision.risk_directive != "CASH" and decision.allowed_strategy_family:
                symbol_safe = symbol.replace("/", "_")
                proposal = {
                    "symbol": symbol,
                    "asset_class": _classify_asset_class(symbol),
                    "family_fit": {
                        decision.allowed_strategy_family: True,
                    },
                    "proposed_bucket": decision.allowed_strategy_family.upper(),
                    "suitability_score": decision.confidence,
                    "confidence_level": (
                        "HIGH" if decision.confidence > 0.7
                        else "MEDIUM" if decision.confidence > 0.4
                        else "LOW"
                    ),
                    "notes": [
                        f"Regime: {decision.regime}",
                        f"Composite score: {decision.composite_score:.3f}",
                        f"Risk directive: {decision.risk_directive}",
                        decision.reasoning,
                    ],
                    "risk_flags": [],
                    "requires_human_review": decision.risk_directive == "SCALE_DOWN",
                    "hermes_run_id": run_id,
                    "timestamp": started_at.isoformat(),
                }
                props_dir = Path("data/hermes_proposals")
                props_dir.mkdir(parents=True, exist_ok=True)
                prop_file = props_dir / f"proposal_{run_id}_{symbol_safe}.json"
                prop_file.write_text(json.dumps(proposal, indent=2, default=str), encoding="utf-8")
                results["proposals"].append(proposal)
                proposals_generated += 1

            # ── Generate alert if confidence < 0.4 ──
            if decision.confidence < 0.4:
                symbol_safe = symbol.replace("/", "_")
                alert = {
                    "alert_id": f"alert_{run_id}_{symbol_safe}",
                    "event_type": "REGIME_REANALYSIS",
                    "symbol": symbol,
                    "trigger_reason": f"Low confidence: {decision.confidence:.3f}",
                    "confidence_scores": dict(decision.agent_confidences),
                    "affected_families": (
                        [decision.allowed_strategy_family]
                        if decision.allowed_strategy_family
                        else []
                    ),
                    "action": "REVIEW",
                    "recommendation": "Consider manual review due to low agent consensus",
                    "requires_human_review": True,
                    "hermes_run_id": run_id,
                    "timestamp": started_at.isoformat(),
                }
                alerts_dir = Path("data/hermes_alerts")
                alerts_dir.mkdir(parents=True, exist_ok=True)
                alert_file = alerts_dir / f"alert_{run_id}_{symbol_safe}.json"
                alert_file.write_text(json.dumps(alert, indent=2, default=str), encoding="utf-8")
                results["alerts"].append(alert)
                alerts_generated += 1

        # ── Write run summary ──
        completed_at = dt.now()
        run_summary = {
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "run_mode": run_mode,
            "data_mode": data_mode,
            "total_markets_evaluated": len(market_states),
            "symbols_analyzed": [ms.symbol for ms in market_states],
            "proposals_generated": proposals_generated,
            "alerts_generated": alerts_generated,
            "per_symbol_decisions": symbol_decisions,
            "correlation": {
                "computed_at": corr_matrix.computed_at.isoformat(),
                "high_pairs": [
                    {"sym_a": a, "sym_b": b, "correlation": round(c, 4)}
                    for a, b, c in corr_matrix.high_pairs
                ],
                "matrix_summary": {
                    f"{a}→{b}": round(c, 4)
                    for (a, b), c in corr_matrix.matrix.items()
                },
            } if corr_matrix is not None else None,
        }

        runs_dir = Path("data/hermes_runs")
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_file = runs_dir / f"run_{run_id}.json"
        run_file.write_text(json.dumps(run_summary, indent=2, default=str), encoding="utf-8")

        # Persist Hermes run to SQLite for analytics
        try:
            from src.persistence.db import PersistenceDB
            db = PersistenceDB()
            db.record_hermes_run(
                hermes_run_id=run_id,
                started_at=started_at.isoformat(),
                completed_at=completed_at.isoformat(),
                run_mode=run_mode,
                data_mode=data_mode,
                markets_evaluated=len(market_states),
                proposals_generated=proposals_generated,
                alerts_generated=alerts_generated,
                per_symbol_decisions=symbol_decisions,
                correlation_data=run_summary.get("correlation"),
            )
        except Exception as e:
            # Non-fatal: analytics persistence is supplementary
            pass

        results["markets_evaluated"] = len(market_states)
        results["symbols_analyzed"] = [ms.symbol for ms in market_states]
        results["per_symbol_decisions"] = symbol_decisions
        results["status"] = "completed"
        results["completed_at"] = completed_at.isoformat()

    except Exception as e:
        results["status"] = "error"
        results["error"] = str(e)

    return results


def _classify_asset_class(symbol: str) -> str:
    """Classify a symbol as 'crypto' or 'equity' based on common patterns."""
    crypto_suffixes = ("USD", "USDT", "USDC", "BTC", "ETH")
    upper = symbol.upper()
    # BTC/USD, ETH/USD, SOL/USD etc. → crypto
    # SPY, AAPL, QQQ → equity
    base = upper.split("/")[0] if "/" in upper else upper
    if any(base.endswith(s) for s in ("BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "DOT")):
        return "crypto"
    if "/" in upper:
        # BTC/USD, ETH/USD → crypto
        return "crypto"
    return "equity"


def handle_proposal_action(filepath: Path, action: str, data: dict) -> None:
    archive_dir = Path("data/hermes_archive")
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest_path = archive_dir / filepath.name
    if action == "ACCEPT":
        update_universe(
            data["symbol"],
            data["family_fit"],
            data.get("proposed_bucket", "UNKNOWN"),
            data.get("hermes_run_id", "manual"),
        )
        data["action_taken"] = "ACCEPTED"
        data["action_timestamp"] = datetime.now().isoformat()
        dest_path.write_text(json.dumps(data, indent=4), encoding="utf-8")
        filepath.unlink()
        st.toast(f"Accepted {data['symbol']}")
    elif action == "DECLINE":
        data["action_taken"] = "DECLINED"
        data["action_timestamp"] = datetime.now().isoformat()
        dest_path.write_text(json.dumps(data, indent=4), encoding="utf-8")
        filepath.unlink()
        st.toast(f"Declined {data['symbol']}")


def handle_alert_action(filepath: Path, action: str, data: dict) -> None:
    archive_dir = Path("data/hermes_archive")
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest_path = archive_dir / filepath.name
    data["action_taken"] = action
    data["action_timestamp"] = datetime.now().isoformat()
    dest_path.write_text(json.dumps(data, indent=4), encoding="utf-8")
    filepath.unlink()
    st.toast(f"Alert marked as {action}")


def update_universe(symbol: str, families: dict, bucket: str, run_id: str) -> None:
    if POLICY_PATH.exists():
        policy = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8")) or {}
    else:
        policy = {"markets": {}, "strategy_families": {}, "policy_rules": {}}
    policy.setdefault("markets", {})
    enabled_fams = [f for f, v in families.items() if v]
    policy["markets"][symbol] = {
        "state": "ACTIVE",
        "bucket": bucket,
        "enabled_families": enabled_fams,
        "rationale": f"Approved via Hermes run {run_id}",
    }
    POLICY_PATH.write_text(yaml.safe_dump(policy, sort_keys=False), encoding="utf-8")

    current_version_file = None
    if UNIVERSE_POINTER_PATH.exists():
        ptr = load_json(UNIVERSE_POINTER_PATH)
        if ptr:
            current_version_file = ptr.get("current_version_file")

    univ_content = {"markets": {}}
    if current_version_file:
        univ_path = Path("data") / current_version_file
        if univ_path.exists():
            univ_content = load_json(univ_path) or {"markets": {}}

    version_num = 1
    if "version" in univ_content:
        try:
            version_num = int(univ_content["version"].replace("v", "")) + 1
        except (ValueError, AttributeError):
            pass

    new_version_str = f"v{version_num:03d}"
    new_univ = {
        "version": new_version_str,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "created_by": "STREAMLIT_APPROVAL",
        "source": "HERMES_AGENTIC",
        "hermes_run_id": run_id,
        "change_summary": [
            f"ADD {symbol}",
            f"ENABLE {', '.join(enabled_fams)}",
            f"ASSIGN BUCKET {bucket}",
        ],
        "markets": univ_content.get("markets", {}),
    }
    new_univ["markets"][symbol] = {"bucket": bucket, "enabled_families": enabled_fams}
    new_filename = f"universe_{new_version_str}.json"
    (Path("data") / new_filename).write_text(json.dumps(new_univ, indent=4), encoding="utf-8")
    UNIVERSE_POINTER_PATH.write_text(
        json.dumps({"current_version_file": new_filename}, indent=4), encoding="utf-8"
    )


def rollback_universe(version_to_restore: str) -> None:
    univ_files = list(Path("data").glob("universe_v*.json"))
    max_v = 0
    for f in univ_files:
        try:
            v_num = int(f.stem.split("_v")[1])
            max_v = max(max_v, v_num)
        except (ValueError, IndexError):
            pass
    new_version_str = f"v{(max_v + 1):03d}"
    target_path = Path("data") / f"universe_{version_to_restore}.json"
    target_univ = load_json(target_path) or {"markets": {}}
    new_univ = {
        "version": new_version_str,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "created_by": "STREAMLIT_ROLLBACK",
        "source": "MANUAL",
        "hermes_run_id": None,
        "change_summary": [f"ROLLBACK to {version_to_restore}"],
        "markets": target_univ.get("markets", {}),
    }
    new_filename = f"universe_{new_version_str}.json"
    (Path("data") / new_filename).write_text(json.dumps(new_univ, indent=4), encoding="utf-8")
    UNIVERSE_POINTER_PATH.write_text(
        json.dumps({"current_version_file": new_filename}, indent=4), encoding="utf-8"
    )


def handle_health_event(event_type: str, timestamp: str, component: str, reason: str) -> None:
    if timestamp and timestamp <= st.session_state.get("last_event_timestamp", ""):
        return
    notification = {
        "type": event_type,
        "timestamp": timestamp,
        "component": component,
        "reason": reason,
        "displayed": False,
    }
    st.session_state["health_notifications"].append(notification)
    if event_type == HealthEvents.EXECUTION_PAUSED:
        st.session_state["execution_paused"] = True
    elif event_type == HealthEvents.EXECUTION_RESUMED:
        st.session_state["execution_paused"] = False
        for n in st.session_state["health_notifications"]:
            if n["type"] in (HealthEvents.ALPACA_DISCONNECTED, HealthEvents.EXECUTION_PAUSED):
                n["displayed"] = True


def read_and_process_new_events() -> None:
    new_events, new_offset, new_ts = read_new_events(
        log_path=DEFAULT_LOG_PATH,
        last_offset=st.session_state["last_event_line_offset"],
        last_timestamp=st.session_state["last_event_timestamp"],
    )
    st.session_state["last_event_line_offset"] = new_offset
    if new_ts:
        st.session_state["last_event_timestamp"] = new_ts
    for event in new_events:
        handle_health_event(
            event.get("event", ""),
            event.get("timestamp", ""),
            event.get("component", ""),
            event.get("reason", ""),
        )


# ──────────────────────────────────────────────────────
# Event processing & auto-refresh
# ──────────────────────────────────────────────────────

read_and_process_new_events()

if st.session_state["auto_refresh"]:
    st_autorefresh(interval=5000, limit=None, key="dashboard_autorefresh")

# ──────────────────────────────────────────────────────
# Load state
# ──────────────────────────────────────────────────────

state = load_snapshot()

# ──────────────────────────────────────────────────────
# SIDEBAR — All actions and settings
# ──────────────────────────────────────────────────────

with st.sidebar:
    st.header("Controls")

    st.session_state["auto_refresh"] = st.checkbox(
        "Auto-refresh (5s)",
        value=st.session_state["auto_refresh"],
        help="Poll the engine for new state every 5 seconds.",
    )

    st.divider()

    # Trade Filters
    st.markdown("### Trade Filters")
    filter_symbol = st.text_input("Symbol", "", placeholder="Filter by symbol...")
    filter_dir = st.selectbox("Direction", ["All", "LONG", "SHORT"])

    st.divider()

    # Hermes Controls
    st.markdown("### Hermes (Advisory)")
    cfg_file = Path("data/hermes_agentic_config.json")
    hermes_cfg = load_json(cfg_file) or {
        "enabled": False,
        "run_mode": "Manual",
        "schedule": {"type": "interval", "interval_minutes": 60, "allowed_hours": None},
        "last_run_id": None,
        "last_run_at": None,
        "last_run_status": None,
    }

    hermes_on = st.toggle("Enable Hermes", value=hermes_cfg.get("enabled", False))
    run_mode = st.selectbox(
        "Run mode",
        ["Manual", "Scheduled"],
        index=0 if hermes_cfg.get("run_mode") == "Manual" else 1,
    )

    # Schedule configuration
    schedule_config = hermes_cfg.get("schedule", {})
    if not isinstance(schedule_config, dict):
        schedule_config = {"type": "interval", "interval_minutes": 60, "allowed_hours": None}

    if run_mode == "Scheduled":
        interval_minutes = st.number_input(
            "Run every N minutes",
            min_value=15,
            max_value=1440,
            value=schedule_config.get("interval_minutes", 60),
            help="Minimum 15 minutes. Hermes will run at this interval.",
        )
        allowed_hours = schedule_config.get("allowed_hours")
        hour_col1, hour_col2 = st.columns(2)
        with hour_col1:
            hour_start = st.number_input(
                "Start hour",
                min_value=0,
                max_value=23,
                value=allowed_hours.get("start", 0) if isinstance(allowed_hours, dict) else 0,
                help="Earliest hour (0-23) for scheduled runs",
            )
        with hour_col2:
            hour_end = st.number_input(
                "End hour",
                min_value=0,
                max_value=23,
                value=allowed_hours.get("end", 23) if isinstance(allowed_hours, dict) else 23,
                help="Latest hour (0-23) for scheduled runs",
            )
        schedule_config = {
            "type": "interval",
            "interval_minutes": interval_minutes,
            "allowed_hours": {"start": hour_start, "end": hour_end},
        }

        # Scheduler status
        last_run_at = hermes_cfg.get("last_run_at")
        if last_run_at:
            try:
                last_dt = datetime.fromisoformat(last_run_at)
                last_age = format_duration(datetime.now() - last_dt)
                last_status = hermes_cfg.get("last_run_status", "unknown")
                st.caption(f"Last scheduled run: {last_age} ago ({last_status})")
            except (ValueError, TypeError):
                st.caption("Last scheduled run: unknown")
        else:
            st.caption("No scheduled runs yet")

        # Scheduler daemon control
        lock_file = Path("data/.hermes_scheduler_lock")
        scheduler_running = lock_file.exists()
        if scheduler_running:
            st.caption("Scheduler daemon: active")
            if st.button("Stop Scheduler", use_container_width=True):
                try:
                    lock_file.unlink()
                    st.toast("Scheduler lock released")
                except Exception:
                    pass
                st.rerun()
        else:
            if st.button("Start Scheduler", use_container_width=True, type="primary"):
                st.toast("Scheduler daemon started (run: python -m src.heremes.scheduler)")
    else:
        schedule_config = {"type": "interval", "interval_minutes": 60, "allowed_hours": None}

    # Show current saved state
    hermes_status_label = "Enabled" if hermes_cfg.get("enabled") else "Disabled"
    st.caption(f"Current: {hermes_cfg.get('run_mode', 'Manual')} · {hermes_status_label}")

    # Mode explanation
    if run_mode == "Manual":
        st.caption("Manual — Operator triggers Hermes research on demand")
    else:
        st.caption("Scheduled — Hermes runs on schedule (requires scheduler daemon)")

    # ── Manual Trigger ──
    if run_mode == "Manual" and hermes_on:
        if st.session_state.get("hermes_running"):
            # Show progress + cancel button while running
            st.info("Hermes is running...")
            if st.button("Cancel", use_container_width=True):
                st.session_state["hermes_cancel"] = True
                st.rerun()
        else:
            # Show trigger button
            if st.button("Trigger Hermes", use_container_width=True, type="primary"):
                st.session_state["hermes_running"] = True
                st.session_state["hermes_cancel"] = False
                st.rerun()

        # Execute the run if running flag is set
        if st.session_state.get("hermes_running") and not st.session_state.get("hermes_cancel"):
            with st.spinner("Running Hermes agents..."):
                result = trigger_hermes_run(
                    cancel_check=lambda: st.session_state.get("hermes_cancel", False)
                )
            st.session_state["hermes_running"] = False
            st.session_state["hermes_cancel"] = False
            st.session_state["hermes_last_result"] = result

            if result["status"] == "completed":
                n = result.get("markets_evaluated", 0)
                st.toast(f"Hermes evaluated {n} market{'s' if n != 1 else ''} in one run")
            elif result["status"] == "cancelled":
                st.toast("Hermes run cancelled")
            elif result["status"] == "error":
                st.toast(f"Hermes error: {result['error']}")
            st.rerun()

        # Cancelled state
        if st.session_state.get("hermes_cancel"):
            st.session_state["hermes_running"] = False
            st.session_state["hermes_cancel"] = False
            st.toast("Hermes run cancelled")
            st.rerun()

    # ── Last Run Result (if any) ──
    last_result = st.session_state.get("hermes_last_result")
    if last_result and last_result.get("status") == "completed":
        st.divider()
        st.markdown("**Last Run Findings**")

        # Run metadata
        st.caption(f"Run: {last_result.get('run_id', '?')}")
        n_evaluated = last_result.get("markets_evaluated", 0)
        symbols = last_result.get("symbols_analyzed", [])
        st.caption(f"Hermes evaluated {n_evaluated} markets in one run")

        # Per-symbol summaries
        per_symbol = last_result.get("per_symbol_decisions", {})
        for symbol, dec in per_symbol.items():
            with st.expander(
                f"{symbol} — {dec.get('regime', '?')} / {dec.get('risk_directive', '?')}",
                expanded=False,
            ):
                st.caption(
                    f"Score: {dec.get('composite_score', 0):.3f} | "
                    f"Confidence: {dec.get('confidence', 0):.3f}"
                )
                if dec.get("allowed_family"):
                    st.caption(f"Family: {dec['allowed_family']}")
                reasoning = dec.get("reasoning", "")
                if reasoning:
                    st.caption(f"Reasoning: {reasoning[:150]}{'...' if len(reasoning) > 150 else ''}")

                # Agent scores
                agent_scores = dec.get("agent_scores", {})
                if agent_scores:
                    st.markdown("**Agent Scores**")
                    for agent, score in agent_scores.items():
                        conf = dec.get("agent_confidences", {}).get(agent, 0)
                        st.caption(f"{agent}: {score:+.3f} (conf={conf:.3f})")

        # Proposals
        proposals = last_result.get("proposals", [])
        if proposals:
            st.markdown("**Proposals**")
            for p in proposals:
                st.caption(
                    f"{p['symbol']} → {p.get('proposed_bucket', '?')} "
                    f"({p.get('confidence_level', '?')})"
                )

        # Alerts
        alerts = last_result.get("alerts", [])
        if alerts:
            for a in alerts:
                st.warning(f"{a.get('symbol', '?')}: {a.get('trigger_reason', '?')}")

    # Hermes activity log — shows what Hermes has actually done
    hermes_run_dir = Path("data/hermes_runs")
    hermes_prop_dir = Path("data/hermes_proposals")
    hermes_alert_dir = Path("data/hermes_alerts")
    hermes_action_dir = Path("docs/hermes_actions")

    run_files = sorted(
        hermes_run_dir.glob("*.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    ) if hermes_run_dir.exists() else []
    prop_files = sorted(
        hermes_prop_dir.glob("*.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    ) if hermes_prop_dir.exists() else []
    alert_files = sorted(
        hermes_alert_dir.glob("*.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    ) if hermes_alert_dir.exists() else []
    action_files = sorted(
        hermes_action_dir.glob("*.md"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    ) if hermes_action_dir.exists() else []

    # Latest run summary
    if run_files:
        latest_run = load_json(run_files[0])
        if latest_run:
            run_ts = latest_run.get("completed_at", latest_run.get("started_at", ""))
            try:
                run_dt = datetime.fromisoformat(run_ts)
                run_age = format_duration(datetime.now() - run_dt)
                n = latest_run.get("total_markets_evaluated", 0)
                symbols = latest_run.get("symbols_analyzed", [])
                symbol_display = _format_symbol_list(symbols)
                run_mode_label = latest_run.get("run_mode", "Manual")
                mode_prefix = "⏱" if run_mode_label == "Scheduled" else "▶"
                st.caption(f"{mode_prefix} Last run: {run_age} ago — {run_mode_label} — {n} market{'s' if n != 1 else ''} evaluated ({symbol_display})")
            except (ValueError, TypeError):
                st.caption(f"Last run: {run_ts}")
            proposals_gen = latest_run.get("proposals_generated", 0)
            alerts_gen = latest_run.get("alerts_generated", 0)
            if proposals_gen or alerts_gen:
                st.caption(f"Produced: {proposals_gen} proposal{'s' if proposals_gen != 1 else ''}, {alerts_gen} alert{'s' if alerts_gen != 1 else ''}")
    else:
        st.caption("No runs yet. Hermes has not been triggered.")

    # Pending items summary
    pending_count = len(prop_files) + len(alert_files)
    action_count = len(action_files)
    if pending_count > 0 or action_count > 0:
        parts = []
        if pending_count:
            parts.append(f"{pending_count} pending item{'s' if pending_count != 1 else ''}")
        if action_count:
            parts.append(f"{action_count} action{'s' if action_count != 1 else ''} completed")
        st.caption(" | ".join(parts))
    elif run_files:
        st.caption("No pending items. All clear.")

    if (
        hermes_on != hermes_cfg.get("enabled")
        or run_mode != hermes_cfg.get("run_mode")
        or schedule_config != hermes_cfg.get("schedule")
    ):
        new_cfg = {
            "enabled": hermes_on,
            "run_mode": run_mode,
            "schedule": schedule_config,
            "last_run_id": hermes_cfg.get("last_run_id"),
            "last_run_at": hermes_cfg.get("last_run_at"),
            "last_run_status": hermes_cfg.get("last_run_status"),
        }
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        cfg_file.write_text(json.dumps(new_cfg, indent=2), encoding="utf-8")
        flag_path = Path("data/hermes_agentic_flag.json")
        flag_path.write_text(json.dumps({"enabled": hermes_on}, indent=2), encoding="utf-8")
        # Visual feedback
        status = "Enabled" if hermes_on else "Disabled"
        st.toast(f"Hermes config saved: {run_mode} · {status}")
        st.rerun()

    st.divider()

    # Scaling Profile Controls
    st.markdown("### Scaling Profile")
    try:
        from src.operations.scaling import ScalingConfig
        _scaling_cfg = ScalingConfig()
        _active_profile = _scaling_cfg.load_active_profile()
        _profile_names = ["SMALL", "MEDIUM", "LARGE"]
        _current_idx = _profile_names.index(_active_profile.name) if _active_profile.name in _profile_names else 0
        _selected_profile = st.selectbox(
            "Active Profile",
            _profile_names,
            index=_current_idx,
            help="SMALL=5 symbols, MEDIUM=20, LARGE=50. Controls rate limits, timeouts, and degradation.",
        )
        if _selected_profile != _active_profile.name:
            _scaling_cfg.set_active_profile(_selected_profile)
            st.toast(f"Scaling profile changed to {_selected_profile}")
            st.rerun()
        st.caption(
            f"Max: {_active_profile.max_symbols} symbols | "
            f"TF: {', '.join(_active_profile.supported_timeframes)} | "
            f"Poll: {_active_profile.poll_interval_seconds}s | "
            f"Timeout: {_active_profile.hermes_timeout_seconds}s"
        )
    except Exception:
        st.caption("Scaling profile: unavailable")

    st.divider()

    # Data Mode Controls
    st.markdown("### Data Mode")
    data_mode = st.selectbox(
        "Data source",
        ["Snapshot", "Streaming"],
        index=0 if st.session_state.get("stream_mode", "snapshot") == "snapshot" else 1,
        help="Snapshot: fetch bars on each run. Streaming: maintain live buffers.",
    )
    new_stream_mode = "snapshot" if data_mode == "Snapshot" else "streaming"

    if new_stream_mode == "streaming":
        from src.market.streaming_buffer import BufferStatus

        fetcher = st.session_state.get("stream_fetcher")
        if fetcher is None:
            # Initialize streaming fetcher with rate-limit-aware settings
            try:
                from src.operations.universe_reader import UniverseReader
                from src.operations.scaling import ScalingConfig
                reader = UniverseReader()
                symbols = reader.get_enabled_markets()
                if symbols:
                    from src.market.stream_fetcher import StreamFetcher
                    _scale_cfg = ScalingConfig()
                    _scale_profile = _scale_cfg.load_active_profile()
                    fetcher = StreamFetcher(
                        symbols=symbols,
                        rate_limit_cooldown_seconds=_scale_profile.yfinance_cooldown_seconds,
                        fetch_timeout_seconds=float(_scale_profile.hermes_timeout_seconds),
                    )
                    fetcher.start()
                    st.session_state["stream_fetcher"] = fetcher
                    st.toast(f"Streaming started: {len(symbols)} symbols (cooldown: {_scale_profile.yfinance_cooldown_seconds}s)")
            except Exception as e:
                st.error(f"Failed to start streaming: {e}")

        if fetcher is not None:
            health = fetcher.get_health_summary()
            fresh_count = sum(1 for s in health.values() if s == "fresh")
            stale_count = sum(1 for s in health.values() if s == "stale")
            dead_count = sum(1 for s in health.values() if s == "dead")
            st.caption(f"Stream: {fresh_count} fresh, {stale_count} stale, {dead_count} dead")
            if st.button("Stop Streaming", use_container_width=True):
                fetcher.stop()
                st.session_state["stream_fetcher"] = None
                st.toast("Streaming stopped")
                st.rerun()
    else:
        # Stop streaming if switching to snapshot
        fetcher = st.session_state.get("stream_fetcher")
        if fetcher is not None:
            fetcher.stop()
            st.session_state["stream_fetcher"] = None

    st.session_state["stream_mode"] = new_stream_mode

    st.divider()

    # State Management (combined)
    st.markdown("### State Management")
    st.caption("Archive & Reset: moves Hermes research files to archive. Open positions and broker state are NOT affected.")

    # Reset action
    if st.session_state.get("confirm_reset"):
        st.warning(
            "This archives Hermes research artifacts only. "
            "Open positions and broker state are NOT affected. "
            "The engine will reconcile to broker state on restart."
        )
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Yes, reset", type="primary", use_container_width=True):
                count, archive_path = archive_and_reset()
                st.toast(f"Archived {count} files to {archive_path}")
                st.session_state["confirm_reset"] = False
                st.rerun()
        with col2:
            if st.button("Cancel", use_container_width=True):
                st.session_state["confirm_reset"] = False
                st.rerun()
    else:
        if st.button("Archive & Reset", use_container_width=True):
            st.session_state["confirm_reset"] = True
            st.rerun()

    st.divider()

    # Restore action (inline, compact)
    archive_root = Path("archive")
    if archive_root.exists():
        archives = sorted(
            [d for d in archive_root.iterdir() if d.is_dir() and d.name.startswith("pre_reset_")],
            key=lambda x: x.name,
            reverse=True,
        )
        if archives:
            archive_names = [a.name for a in archives]
            selected = st.selectbox("Restore from archive", archive_names)
            if st.button("Restore", use_container_width=True):
                selected_dir = archive_root / selected
                restored = restore_archive(selected_dir)
                st.toast(f"Restored {restored} files from {selected}")
                st.rerun()
        else:
            st.caption("No archived states to restore.")
    else:
        st.caption("No archived states to restore.")

    st.divider()

    # Diagnostics
    with st.expander("Diagnostics"):
        st.json(state)

    st.divider()

    # Operations Help
    st.markdown("### Help / Ops")
    if st.button("Operations Playbooks", use_container_width=True):
        st.session_state["show_ops_docs"] = True
        st.rerun()

    st.divider()
    if st.button("Dashboard Guide", use_container_width=True):
        st.session_state["show_readme"] = True
        st.rerun()


# ──────────────────────────────────────────────────────
# MAIN PAGE — Read-only situational awareness
# ──────────────────────────────────────────────────────

# Status dot
now = datetime.now()
snapshot_ts = state.get("timestamp", "")
dot = "?"
age = None
if snapshot_ts:
    try:
        snapshot_time = datetime.strptime(snapshot_ts, "%Y-%m-%d %H:%M:%S")
        age = now - snapshot_time
        if age < timedelta(seconds=30):
            dot = "O"
        elif age < timedelta(minutes=5):
            dot = "~"
        else:
            dot = "!"
    except ValueError:
        pass

# Title
# ── Phase F: Mode Banner ──────────────────────────────
try:
    from visualization.mode_banner import render_mode_banner, get_mode_emoji
    from visualization.mode_resolver import SystemModeResolver
    _sys_mode = st.session_state.get("system_mode", "ADVISORY")
    _mode_data = render_mode_banner(_sys_mode)
    st.markdown(_mode_data["html"], unsafe_allow_html=True)
except Exception:
    pass  # Graceful degradation if visualization package not available

title_col, info_col, refresh_col = st.columns([5, 1, 1])
with title_col:
    st.title(f"Hermes Observability  {dot}")
with info_col:
    if st.button("i", key="readme_btn", help="Dashboard Guide"):
        st.session_state["show_readme"] = True
with refresh_col:
    st.caption(f"Updated {format_duration(age) if age else '—'} ago")

# README viewer (triggered by button) — uses expander for Streamlit < 1.33 compatibility
if st.session_state.get("show_readme"):
    readme_path = Path(__file__).parent / "README.md"
    if readme_path.exists():
        with st.expander("Dashboard Guide", expanded=True):
            st.markdown(readme_path.read_text(encoding="utf-8"))
            if st.button("Close"):
                st.session_state["show_readme"] = False
                st.rerun()
    else:
        st.session_state["show_readme"] = False

# Operations docs viewer (triggered by button)
if st.session_state.get("show_ops_docs"):
    ops_dir = Path(__file__).parent.parent / "docs" / "operations"
    if ops_dir.exists():
        ops_files = sorted(ops_dir.glob("*.md"))
        if ops_files:
            with st.expander("Operations Playbooks & Runbooks", expanded=True):
                doc_names = [f.stem for f in ops_files]
                selected_doc = st.selectbox("Select document", doc_names)
                selected_path = ops_dir / f"{selected_doc}.md"
                if selected_path.exists():
                    st.markdown(selected_path.read_text(encoding="utf-8"))
                if st.button("Close", key="close_ops"):
                    st.session_state["show_ops_docs"] = False
                    st.rerun()
        else:
            st.session_state["show_ops_docs"] = False
    else:
        st.session_state["show_ops_docs"] = False

# Health notification banners
for notification in st.session_state["health_notifications"]:
    if notification.get("displayed"):
        continue
    event_type = notification["type"]
    timestamp = notification["timestamp"]
    reason = notification["reason"]
    label = _HEALTH_EVENT_LABELS.get(event_type, event_type)

    if event_type in (
        HealthEvents.ALPACA_RESTORED,
        HealthEvents.DATA_FEED_RESTORED,
        HealthEvents.HERMES_RESTORED,
        HealthEvents.FILE_SYSTEM_RESTORED,
        HealthEvents.POLICY_RESTORED,
    ):
        st.toast(f"{label} ({timestamp})")
        notification["displayed"] = True
    elif event_type == HealthEvents.HERMES_RUN_COMPLETED:
        st.toast(f"{label} ({timestamp})")
        notification["displayed"] = True
    elif event_type == HealthEvents.ALPACA_DISCONNECTED:
        st.error(f"{label} — execution paused ({timestamp})")
    elif event_type == HealthEvents.DATA_STALE:
        st.warning(f"{label} — last update {reason} ({timestamp})")
    elif event_type == HealthEvents.HERMES_UNAVAILABLE:
        st.warning(f"{label} — {reason} ({timestamp})")
    elif event_type == HealthEvents.FILE_SYSTEM_DEGRADED:
        st.error(f"{label} — {reason} ({timestamp})")
    elif event_type == HealthEvents.POLICY_DEGRADED:
        st.error(f"{label} — {reason} ({timestamp})")
    elif event_type == HealthEvents.EXECUTION_PAUSED:
        st.error(f"{label} — {reason} ({timestamp})")

if not state:
    st.warning("Waiting for engine state snapshot...")
    st.stop()

# ── System Health ────────────────────────────────────
st.markdown("#### System Health")

engine_started = state.get("engine_started_at", "")
uptime_str = "—"
if engine_started:
    try:
        started_dt = datetime.fromisoformat(engine_started)
        uptime_str = format_duration(now - started_dt)
    except (ValueError, TypeError):
        pass

broker_raw = state.get("health", {}).get("broker_status", "UNKNOWN")
if st.session_state.get("execution_paused"):
    broker_label = "PAUSED"
    broker_delta = "Alpaca disconnected"
elif broker_raw == "CONNECTED":
    broker_label = "LIVE"
    broker_delta = None
else:
    broker_label = broker_raw
    broker_delta = None

col1, col2, col3 = st.columns(3)
with col1:
    st.metric(
        "Broker Connection",
        broker_label,
        delta=broker_delta,
        help="Alpaca connection status. LIVE = connected and executing trades.",
    )
with col2:
    equity = state.get("equity", 0.0)
    st.metric(
        "Account Value",
        f"${equity:,.2f}",
        help="Total account value including unrealized PnL from open positions.",
    )
with col3:
    dd_val = state.get("current_drawdown_pct", 0.0)
    dd_max = state.get("allowed_drawdown_pct", 10.0)
    st.metric(
        "Drawdown",
        f"{dd_val}%",
        delta=f"Limit: {dd_max}%",
        delta_color="inverse",
        help="Current drawdown from peak equity. The limit is a safety threshold — reaching it activates protective measures.",
    )

# Reconciliation status
if state.get("reconciled"):
    st.success("Broker positions synchronized")
else:
    st.warning("Waiting for broker position sync...")

# Drawdown progress bar
dd_ratio = min(dd_val / dd_max, 1.0) if dd_max > 0 else 0
st.progress(dd_ratio, text=f"Drawdown: {dd_val:.1f}% / {dd_max:.1f}%")

# Uptime (compact, secondary)
st.caption(f"Engine uptime: {uptime_str}")

st.divider()

# ── Risk & Protection ───────────────────────────────
st.markdown("#### Risk & Protection")

prof_col1, prof_col2 = st.columns(2)
with prof_col1:
    st.metric(
        "Risk Profile",
        state.get("profile", "—").upper(),
        help="Controls position sizing and concurrency limits. Progresses as account stabilizes.",
    )
with prof_col2:
    st.metric(
        "Risk Stage",
        state.get("ladder_state", "—"),
        help="Drawdown protection level: GROWTH = full sizing, PROTECTIVE = reduced, SURVIVAL = minimal.",
    )

# Transition info (only when real data exists)
transition = state.get("last_transition", "")
reason_text = state.get("transition_reason", "")
if transition and reason_text:
    st.info(f"**Profile change:** {transition} — {reason_text}")

# Exposure summary — current state
exp = state.get("exposure_summary", {})
open_trades = state.get("open_trades", [])
open_count = len(open_trades)
max_concurrency = exp.get("max_concurrency", 5)

exp_col1, exp_col2 = st.columns(2)
with exp_col1:
    total_r = exp.get("total_r", 0.0)
    st.metric(
        "Portfolio Risk",
        f"{total_r:.2f} R",
        help="Total risk currently at stake across open positions, measured in risk units (R).",
    )
with exp_col2:
    st.metric(
        "Open Positions",
        f"{open_count} / {max_concurrency}",
        help="Current open positions vs maximum allowed by risk profile.",
    )

# Trades guarded (historical) — only show if > 0
blocked = exp.get("blocked_count", 0)
if blocked > 0:
    st.caption(
        f"Trades guarded: {blocked} since engine start (protective behavior, not errors)"
    )

st.divider()

# ── Open Positions ──────────────────────────────────
st.markdown("#### Open Positions")

trades_df = pd.DataFrame(open_trades)
if trades_df.empty:
    st.caption("No open positions. All capital is unallocated.")
else:
    if filter_symbol:
        trades_df = trades_df[trades_df["Symbol"].str.contains(filter_symbol, case=False, na=False)]
    if filter_dir != "All":
        trades_df = trades_df[trades_df["Direction"] == filter_dir]

    if trades_df.empty:
        st.caption("No positions match the current filter.")
    else:
        PAGE_SIZE = 10
        total_rows = len(trades_df)
        total_pages = max(1, (total_rows + PAGE_SIZE - 1) // PAGE_SIZE)
        page = st.number_input("Page", 1, total_pages, 1, key="trade_page")
        start = (page - 1) * PAGE_SIZE
        page_df = trades_df.iloc[start : start + PAGE_SIZE]

        st.dataframe(
            page_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Symbol": st.column_config.TextColumn("Market"),
                "Direction": st.column_config.TextColumn("Side"),
                "Profile": st.column_config.TextColumn("Profile"),
                "R_Exposure": st.column_config.ProgressColumn(
                    "Risk (R)", format="%.2f", min_value=0.0, max_value=2.0,
                    help="Position risk as a fraction of account risk budget.",
                ),
                "PnL": st.column_config.NumberColumn("Unrealized PnL", format="$ %.2f"),
            },
        )
        st.caption(f"Showing {start + 1}-{min(start + PAGE_SIZE, total_rows)} of {total_rows}")

st.divider()

# Trade History — broker-confirmed executions only
st.markdown("#### Trade History")

recent_fills = state.get("recent_fills", [])
if not recent_fills:
    st.caption(
        "No trades executed yet. This table shows broker-confirmed "
        "fills only — not signals or intents."
    )
else:
    fills_df = pd.DataFrame(recent_fills)
    # Sort most recent first
    if "timestamp" in fills_df.columns:
        fills_df = fills_df.sort_values("timestamp", ascending=False)

    PAGE_SIZE = 10
    total_rows = len(fills_df)
    total_pages = max(1, (total_rows + PAGE_SIZE - 1) // PAGE_SIZE)
    page = st.number_input("Page", 1, total_pages, 1, key="fills_page")
    start = (page - 1) * PAGE_SIZE
    page_df = fills_df.iloc[start : start + PAGE_SIZE]

    st.dataframe(
        page_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "timestamp": st.column_config.TextColumn("Time"),
            "symbol": st.column_config.TextColumn("Symbol"),
            "side": st.column_config.TextColumn("Side"),
            "quantity": st.column_config.NumberColumn("Qty", format="%.4f"),
            "fill_price": st.column_config.NumberColumn("Fill Price", format="%.2f"),
            "strategy": st.column_config.TextColumn("Strategy"),
            "pnl": st.column_config.NumberColumn("Realized PnL", format="$ %.2f"),
        },
    )
    st.caption(f"Showing {start + 1}-{min(start + PAGE_SIZE, total_rows)} of {total_rows}")

st.divider()

# Hermes Advisory — collapsed by default
prop_count = len(list(Path("data/hermes_proposals").glob("*.json"))) if Path("data/hermes_proposals").exists() else 0
alert_count = len(list(Path("data/hermes_alerts").glob("*.json"))) if Path("data/hermes_alerts").exists() else 0
handoff_count = len(list(Path("docs/hermes_actions").glob("*.md"))) if Path("docs/hermes_actions").exists() else 0

hermes_parts = []
if prop_count > 0:
    hermes_parts.append(f"{prop_count} proposal{'s' if prop_count != 1 else ''}")
if alert_count > 0:
    hermes_parts.append(f"{alert_count} alert{'s' if alert_count != 1 else ''}")
if handoff_count > 0:
    hermes_parts.append(f"{handoff_count} handoff{'s' if handoff_count != 1 else ''}")
hermes_status = ", ".join(hermes_parts) if hermes_parts else "No pending items"

with st.expander(f"Hermes Advisory — {hermes_status}", expanded=False):
    # Latest run
    run_files = get_hermes_files("data/hermes_runs")
    if run_files:
        latest_run = load_json(run_files[0])
        if latest_run:
            ts_str = latest_run.get("completed_at", latest_run.get("started_at", "Unknown"))
            try:
                ts_str = datetime.fromisoformat(ts_str).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                pass
            n = latest_run.get("total_markets_evaluated", 0)
            symbols = latest_run.get("symbols_analyzed", [])
            symbol_display = _format_symbol_list(symbols)
            st.caption(
                f"Last run: {ts_str} — "
                f"{n} market{'s' if n != 1 else ''} evaluated ({symbol_display}), "
                f"{latest_run.get('proposals_generated', 0)} proposals, "
                f"{latest_run.get('alerts_generated', 0)} alerts"
            )

            # Per-symbol decision summaries
            per_symbol = latest_run.get("per_symbol_decisions", {})
            if per_symbol:
                st.markdown("**Per-Symbol Decisions**")
                for sym, dec in per_symbol.items():
                    st.caption(
                        f"{sym}: {dec.get('regime', '?')} / "
                        f"{dec.get('risk_directive', '?')} "
                        f"(score={dec.get('composite_score', 0):.3f}, "
                        f"conf={dec.get('confidence', 0):.3f})"
                    )

    # Alerts
    alert_files = get_hermes_files("data/hermes_alerts")
    if alert_files:
        st.markdown("**Alerts**")
        for a_file in alert_files:
            alert = load_json(a_file)
            if not alert:
                continue
            if alert.get("event_type") == "BUCKET_CONFLICT":
                st.warning(
                    f"Correlation Conflict: {alert.get('bucket')} — "
                    f"{', '.join(alert.get('symbols', []))}"
                )
            elif alert.get("event_type") == "REGIME_REANALYSIS":
                st.info(f"Regime Reanalysis: {alert.get('symbol')} — {alert.get('trigger_reason', '')}")

            ac1, ac2 = st.columns([1, 1])
            with ac1:
                if st.button("Accept", key=f"a_acc_{alert.get('alert_id')}"):
                    handle_alert_action(a_file, "ACCEPT", alert)
                    st.rerun()
            with ac2:
                if st.button("Decline", key=f"a_dec_{alert.get('alert_id')}"):
                    handle_alert_action(a_file, "DECLINE", alert)
                    st.rerun()

    # Proposals
    prop_files = get_hermes_files("data/hermes_proposals")
    if prop_files:
        st.markdown("**Proposals**")
        for p_file in prop_files:
            prop = load_json(p_file)
            if not prop:
                continue
            st.markdown(f"**{prop.get('symbol', '?')}** ({prop.get('asset_class', '?')})")
            st.caption(
                f"Bucket: {prop.get('proposed_bucket', '?')} | "
                f"Suitability: {prop.get('suitability_score', '?')} "
                f"({prop.get('confidence_level', '?')})"
            )
            families = [k for k, v in prop.get("family_fit", {}).items() if v]
            if families:
                st.caption(f"Families: {', '.join(families)}")

            c_a, c_d = st.columns([1, 1])
            with c_a:
                if st.button("Accept", key=f"p_acc_{prop.get('symbol', 'x')}"):
                    handle_proposal_action(p_file, "ACCEPT", prop)
                    st.rerun()
            with c_d:
                if st.button("Decline", key=f"p_dec_{prop.get('symbol', 'x')}"):
                    handle_proposal_action(p_file, "DECLINE", prop)
                    st.rerun()

    # Handoffs
    handoff_dir = Path("docs/hermes_actions")
    if handoff_dir.exists():
        handoffs = sorted(handoff_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
        if handoffs:
            st.markdown("**Action Handoffs**")
            completed_actions = []
            if POLICY_PATH.exists():
                policy_data = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8")) or {}
                completed_actions = (
                    policy_data.get("hermes_action_handoff", {}).get("completed_actions", [])
                )
            for h_file in handoffs:
                status = "Done" if h_file.name in completed_actions else "Pending"
                with st.expander(f"[{status}] {h_file.name}"):
                    st.markdown(h_file.read_text(encoding="utf-8"))

    if not (run_files or alert_files or prop_files or (handoff_dir.exists() and any(handoff_dir.glob("*.md")))):
        st.caption("No Hermes artifacts. Hermes is idle — no proposals or alerts pending.")

# ── Portfolio Correlation Matrix ──────────────────────────────
# Show correlation data from latest Hermes run
_corr_run_files = get_hermes_files("data/hermes_runs") if Path("data/hermes_runs").exists() else []
if _corr_run_files:
    _latest_corr_run = load_json(_corr_run_files[0])
    _corr_data = _latest_corr_run.get("correlation") if _latest_corr_run else None
    if _corr_data and _corr_data.get("high_pairs"):
        high_pairs = _corr_data["high_pairs"]
        with st.expander(f"Portfolio Correlation — {len(high_pairs)} high pair{'s' if len(high_pairs) != 1 else ''}", expanded=False):
            for pair in high_pairs:
                sym_a = pair.get("sym_a", "?")
                sym_b = pair.get("sym_b", "?")
                corr_val = pair.get("correlation", 0)
                st.caption(f"{sym_a} ↔ {sym_b}: {corr_val:.3f}")
            matrix_summary = _corr_data.get("matrix_summary", {})
            if matrix_summary:
                st.markdown("**All Pairs**")
                for pair_key, corr_val in matrix_summary.items():
                    st.caption(f"{pair_key}: {corr_val:.3f}")

# Universe Policy — collapsed by default
univ_data = None
active_version_file = None
if UNIVERSE_POINTER_PATH.exists():
    ptr = load_json(UNIVERSE_POINTER_PATH)
    if ptr:
        active_version_file = ptr.get("current_version_file")
if active_version_file:
    univ_data = load_json(Path("data") / active_version_file)

univ_version = univ_data.get("version", "?") if univ_data else "?"
univ_source = univ_data.get("source", "?") if univ_data else "?"

with st.expander(f"Universe Policy — {univ_version} · {univ_source}", expanded=False):
    if univ_data:
        univ_ts = univ_data.get("created_at", "?")
        st.caption(f"Version: {univ_version} | Updated: {univ_ts} | Source: {univ_source}")

        changes = univ_data.get("change_summary", [])
        if changes:
            st.markdown("**Recent changes:**")
            for ch in changes:
                st.caption(f"- {ch}")

        if univ_version.startswith("v"):
            try:
                v_num = int(univ_version[1:])
                if v_num > 1:
                    prev_version = f"v{(v_num - 1):03d}"
                    prev_data = load_json(Path("data") / f"universe_{prev_version}.json")
                    if prev_data:
                        curr_markets = univ_data.get("markets", {})
                        prev_markets = prev_data.get("markets", {})
                        added = set(curr_markets.keys()) - set(prev_markets.keys())
                        removed = set(prev_markets.keys()) - set(curr_markets.keys())
                        if added:
                            st.success(f"Added: {', '.join(added)}")
                        if removed:
                            st.error(f"Removed: {', '.join(removed)}")
                        if not (added or removed):
                            st.caption("No market changes from previous version.")
            except (ValueError, AttributeError):
                pass

        st.markdown("---")
        if st.button("Rollback to previous version", key="rollback_btn"):
            if univ_version.startswith("v"):
                try:
                    v_num = int(univ_version[1:])
                    if v_num > 1:
                        prev_version = f"v{(v_num - 1):03d}"
                        rollback_universe(prev_version)
                        st.toast(f"Rolled back to {prev_version}")
                        st.rerun()
                except (ValueError, AttributeError):
                    pass
    else:
        st.caption("No universe policy found.")
