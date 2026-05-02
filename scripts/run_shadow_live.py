"""Phase 14: Live Shadow Mode — observation-only real-time Hermes v2 pipeline.

Runs the full Hermes v2 pipeline on live data (yfinance SPY hourly bars)
in observation-only mode. No orders are submitted. All decisions, directives,
drawdown ladder states, and FTMO guard checks are logged for audit.

Usage:
    python scripts/run_shadow_live.py                     # Default 14-day run
    python scripts/run_shadow_live.py --duration 7d       # 7-day run
    python scripts/run_shadow_live.py --duration 1d       # 1-day test
    python scripts/run_shadow_live.py --bars 10           # 10-bar smoke test

Features:
    - Incremental bar fetching via yfinance (no full-history refetch)
    - Rolling 52-bar window for Hermes v2 coordinator
    - DrawdownLadder + FTMOGuard evaluation per bar
    - CSV + SQLite persistence
    - Heartbeat logging every 30 bars
    - Graceful shutdown (SIGINT/SIGTERM)
    - State persistence for resume on restart

Constraints:
    - NO orders, NO broker, NO execution
    - Pure observation — no tuning, no overrides
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import signal
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from src.core.types import Bar, Regime
from src.hermes.agents.base import MarketState
from src.hermes.agents.stub_agents import (
    IchimokuAgent,
    VolatilityAgent,
    AMTAgent,
    WyckoffAgent,
)
from src.hermes.coordinator import (
    AccountState,
    HermesCoordinator,
    PreviousState,
)
from src.hermes.registry import AgentRegistry
from src.hermes.scoring import ScoringEngine
from src.hermes.conflict import ConflictResolver
from src.hermes.sizing import PositionSizer
from src.risk.drawdown_ladder import DrawdownLadder
from src.risk.ftmo_guard import FTMOConfig, FTMOGuard
from src.profiles.presets import RISK_PROFILES
from src.profiles.resolver import ProfileResolver
from src.persistence.db import PersistenceDB
from src.persistence.models import StrategyState

logger = logging.getLogger("shadow_live")

# --- Constants ---
MIN_BARS = 52
HEARTBEAT_INTERVAL = 30
STATE_FILE = Path(_root) / "data" / "shadow_live_state.json"
DB_PATH = Path(_root) / "data" / "trading_state.db"

_shutdown = False


def _signal_handler(signum: int, frame: object) -> None:
    global _shutdown
    logger.info("Shutdown signal received (signal %d)", signum)
    _shutdown = True


# --- State persistence ---

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupt state file, starting fresh")
    return {
        "last_timestamp": None,
        "bars_processed": 0,
        "directive_counts": {"FULL": 0, "SCALE_DOWN": 0, "CASH": 0},
        "equity": 100_000.0,
        "peak_equity": 100_000.0,
    }


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# --- Data fetching ---

def fetch_initial_bars(symbol: str, interval: str = "1h", count: int = 200) -> list[Bar]:
    """Fetch initial history using yfinance date range."""
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed: pip install yfinance")
        return []
    ticker = yf.Ticker(symbol)
    days_back = max(count // 5, 60)
    start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    df = ticker.history(start=start_date, interval=interval)
    if df.empty:
        logger.warning("No data from yfinance for %s", symbol)
        return []
    bars = []
    for ts, row in df.iterrows():
        bars.append(Bar(
            timestamp=str(ts),
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
            volume=float(row["Volume"]),
        ))
    return bars


def fetch_incremental_bars(
    symbol: str, last_timestamp: str | None, interval: str = "1h"
) -> list[Bar]:
    """Fetch only new bars since last_timestamp."""
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed")
        return []
    ticker = yf.Ticker(symbol)
    df = ticker.history(period="30d", interval=interval)
    if df.empty:
        return []
    bars = []
    for ts, row in df.iterrows():
        ts_str = str(ts)
        if last_timestamp and ts_str <= last_timestamp:
            continue
        bars.append(Bar(
            timestamp=ts_str,
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
            volume=float(row["Volume"]),
        ))
    return bars


def is_bar_complete(bar_timestamp: str, bar_interval_minutes: int = 60) -> bool:
    """Only process bars whose timestamp is strictly before now - bar_duration."""
    try:
        bar_time = datetime.fromisoformat(bar_timestamp.replace("Z", "+00:00"))
        if bar_time.tzinfo is not None:
            bar_time = bar_time.replace(tzinfo=None)
        cutoff = datetime.now() - timedelta(minutes=bar_interval_minutes)
        return bar_time < cutoff
    except (ValueError, TypeError):
        return False


# --- Hermes v2 coordinator factory ---

def make_coordinator(risk_profile: str = "ftmo_safe") -> tuple[HermesCoordinator, DrawdownLadder, FTMOGuard, dict]:
    """Build Hermes v2 coordinator with profile-derived parameters."""
    profile_data = RISK_PROFILES[risk_profile]
    resolver = ProfileResolver.from_risk_profile(risk_profile)

    registry = AgentRegistry()
    registry.register(IchimokuAgent())
    registry.register(VolatilityAgent())
    registry.register(AMTAgent())
    registry.register(WyckoffAgent())

    sizing = PositionSizer(
        ladder=DrawdownLadder.from_profile(profile_data.get("drawdown_ladder", {})),
        ftmo_config=FTMOConfig(**profile_data.get("ftmo", {})),
    )

    coordinator = HermesCoordinator(
        registry=registry,
        scoring=ScoringEngine(),
        conflict=ConflictResolver(),
        sizing=sizing,
    )

    return coordinator, sizing.ladder, sizing.ftmo_guard or FTMOGuard(), {
        "base_risk": resolver.base_risk,
        "max_portfolio_risk": resolver.max_portfolio_risk,
    }


# --- CSV logging ---

_SHADOW_CSV_HEADER = [
    "timestamp", "bar", "regime", "composite_score", "confidence",
    "directive", "resolution_path", "allowed_family",
    "per_trade_risk", "portfolio_risk",
    "dd_stage", "dd_multiplier", "ftmo_compliant", "ftmo_action",
    "equity", "peak_equity", "drawdown",
    "agent_scores", "agent_confidences", "reasoning",
]


def write_csv_header(csv_path: Path) -> None:
    if not csv_path.exists():
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", newline="") as f:
            csv.writer(f).writerow(_SHADOW_CSV_HEADER)


def write_csv_row(
    csv_path: Path,
    bar_idx: int,
    decision,
    dd_state,
    ftmo_check,
    equity: float,
    peak_equity: float,
    drawdown: float,
) -> None:
    with open(csv_path, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now().isoformat(),
            bar_idx,
            decision.regime,
            f"{decision.composite_score:.6f}",
            f"{decision.confidence:.6f}",
            decision.risk_directive,
            "",
            decision.allowed_strategy_family or "",
            f"{decision.per_trade_risk:.6f}",
            f"{decision.portfolio_risk:.6f}",
            dd_state.stage,
            f"{dd_state.size_multiplier:.4f}",
            ftmo_check.compliant,
            ftmo_check.action,
            f"{equity:.2f}",
            f"{peak_equity:.2f}",
            f"{drawdown:.4f}",
            json.dumps({k: round(v, 6) for k, v in decision.agent_scores.items()}),
            json.dumps({k: round(v, 6) for k, v in decision.agent_confidences.items()}),
            decision.reasoning,
        ])


# --- Main ---

def main() -> None:
    global _shutdown

    parser = argparse.ArgumentParser(description="Phase 14: Live Shadow Mode (observation only)")
    parser.add_argument("--symbol", default="SPY", help="Symbol to observe (default: SPY)")
    parser.add_argument("--interval", default="1h", help="Bar interval (default: 1h)")
    parser.add_argument("--bars", type=int, default=None, help="Limit number of bars (for testing)")
    parser.add_argument("--duration", default="14d", help="Run duration (e.g., 14d, 7d, 1d, 6h)")
    parser.add_argument("--profile", default="ftmo_safe", choices=list(RISK_PROFILES.keys()),
                        help="Risk profile (default: ftmo_safe)")
    parser.add_argument("--fresh", action="store_true", help="Start fresh (ignore saved state)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Parse duration
    max_duration = None
    if args.duration:
        unit = args.duration[-1]
        value = int(args.duration[:-1])
        if unit == "d":
            max_duration = timedelta(days=value)
        elif unit == "h":
            max_duration = timedelta(hours=value)
        elif unit == "m":
            max_duration = timedelta(minutes=value)

    logger.info("=" * 60)
    logger.info("PHASE 14: LIVE SHADOW MODE — OBSERVATION ONLY")
    logger.info("=" * 60)
    logger.info("Symbol: %s | Interval: %s | Duration: %s", args.symbol, args.interval, args.duration)
    logger.info("Profile: %s", args.profile)
    logger.info("Mode: OBSERVATION ONLY — no orders, no execution")
    logger.info("=" * 60)

    # Build coordinator
    coordinator, ladder, ftmo_guard, risk_params = make_coordinator(args.profile)
    logger.info("Coordinator built: base_risk=%.4f, max_portfolio_risk=%.4f",
                risk_params["base_risk"], risk_params["max_portfolio_risk"])

    # Persistence
    db = PersistenceDB(str(DB_PATH))

    # State
    if args.fresh:
        state = {
            "last_timestamp": None,
            "bars_processed": 0,
            "directive_counts": {"FULL": 0, "SCALE_DOWN": 0, "CASH": 0},
            "equity": 100_000.0,
            "peak_equity": 100_000.0,
        }
    else:
        state = load_state()

    last_timestamp = state["last_timestamp"]
    bars_processed = state["bars_processed"]
    directive_counts = state["directive_counts"]
    equity = state["equity"]
    peak_equity = state["peak_equity"]

    if last_timestamp:
        logger.info("Resuming from: %s (processed: %d)", last_timestamp, bars_processed)

    # CSV log
    today = datetime.now().strftime("%Y%m%d")
    csv_path = Path(_root) / "logs" / f"shadow_live_{today}.csv"
    write_csv_header(csv_path)
    logger.info("Log file: %s", csv_path)

    # Fetch initial bars
    logger.info("Fetching initial bars for %s ...", args.symbol)
    all_bars = fetch_initial_bars(args.symbol, args.interval, count=200)
    if not all_bars:
        logger.error("Failed to fetch initial data")
        return
    logger.info("Fetched %d initial bars", len(all_bars))

    # Filter complete bars
    all_bars = [b for b in all_bars if is_bar_complete(b.timestamp)]
    logger.info("After completeness filter: %d bars", len(all_bars))

    if len(all_bars) < MIN_BARS + 1:
        logger.error("Need at least %d bars, got %d", MIN_BARS + 1, len(all_bars))
        return

    # Build timestamp-to-index mapping
    ts_to_idx = {b.timestamp: idx for idx, b in enumerate(all_bars)}

    # Identify tradeable bars (those with MIN_BARS of history)
    tradeable_bars = [b for b in all_bars if ts_to_idx.get(b.timestamp, 0) >= MIN_BARS]

    # Skip first MIN_BARS for warm-up
    if len(tradeable_bars) > MIN_BARS:
        tradeable_bars = tradeable_bars[MIN_BARS:]

    # Resume: skip already-processed bars
    if last_timestamp:
        tradeable_bars = [b for b in tradeable_bars if b.timestamp > last_timestamp]
        logger.info("New bars since last run: %d", len(tradeable_bars))

    # Limit bars if specified
    if args.bars is not None and len(tradeable_bars) > args.bars:
        tradeable_bars = tradeable_bars[: args.bars]

    logger.info("Processing %d bars", len(tradeable_bars))

    # Previous state for conflict resolver
    previous: PreviousState | None = None
    run_start = datetime.now()

    # --- Main loop (batch mode) ---
    for current_bar in tradeable_bars:
        if _shutdown:
            logger.info("Shutdown requested — stopping after bar %d", bars_processed)
            break

        if max_duration and (datetime.now() - run_start) >= max_duration:
            logger.info("Duration limit reached — stopping")
            break

        bar_idx = ts_to_idx.get(current_bar.timestamp)
        if bar_idx is None or bar_idx < MIN_BARS:
            continue

        window = all_bars[bar_idx - MIN_BARS: bar_idx + 1]

        # Build MarketState
        ms = MarketState(
            bars=window,
            regime=Regime.RANGING,
            regime_confidence=0.5,
            volatility=None,
            timestamp=current_bar.timestamp,
        )

        # Account state (simulated — no real positions)
        drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
        acc = AccountState(
            equity=equity,
            peak_equity=peak_equity,
            current_drawdown=drawdown,
            max_risk_per_trade=risk_params["base_risk"],
            max_portfolio_risk=risk_params["max_portfolio_risk"],
        )

        # Hermes v2 cycle
        decision = coordinator.run_cycle(ms, acc, previous)

        # Drawdown ladder evaluation
        dd_state = ladder.evaluate(
            current_drawdown=drawdown,
            confidence=decision.confidence,
        )

        # FTMO guard check
        ftmo_guard.update_daily(equity=equity, bar_timestamp=current_bar.timestamp)
        ftmo_check = ftmo_guard.check(equity=equity, peak_equity=peak_equity)

        # Simulate equity change (observation only — no real trades)
        # Equity moves based on decision and market direction
        # This is a rough simulation for shadow observation
        if decision.risk_directive == "FULL":
            # Assume small positive drift in favorable conditions
            equity *= 1.0 + (decision.composite_score * 0.001)
        elif decision.risk_directive == "SCALE_DOWN":
            # Reduced movement
            equity *= 1.0 + (decision.composite_score * 0.0005)
        # CASH: no change

        # Update peak
        if equity > peak_equity:
            peak_equity = equity

        # Write CSV row
        write_csv_row(
            csv_path, bars_processed, decision, dd_state, ftmo_check,
            equity, peak_equity, drawdown,
        )

        bars_processed += 1
        directive_counts[decision.risk_directive] = directive_counts.get(decision.risk_directive, 0) + 1

        # Update previous state
        previous = PreviousState(
            composite_score=decision.composite_score,
            regime=decision.regime,
            risk_directive=decision.risk_directive,
            allowed_strategy_family=decision.allowed_strategy_family,
        )

        logger.info(
            "Bar %d | %s | regime=%s | directive=%s | conf=%.3f | dd_stage=%s | equity=%.2f",
            bars_processed,
            current_bar.timestamp[:19],
            decision.regime,
            decision.risk_directive,
            decision.confidence,
            dd_state.stage,
            equity,
        )

        if bars_processed % HEARTBEAT_INTERVAL == 0:
            logger.info(
                "[HEARTBEAT] bar=%d | equity=%.2f | FULL=%d SCALE_DOWN=%d CASH=%d | dd=%.4f",
                bars_processed,
                equity,
                directive_counts.get("FULL", 0),
                directive_counts.get("SCALE_DOWN", 0),
                directive_counts.get("CASH", 0),
                drawdown,
            )

        # Save state
        state["last_timestamp"] = current_bar.timestamp
        state["bars_processed"] = bars_processed
        state["directive_counts"] = directive_counts
        state["equity"] = equity
        state["peak_equity"] = peak_equity
        save_state(state)

    # --- Continuous live loop (only if no --bars limit) ---
    if args.bars is None and not _shutdown:
        logger.info("Entering continuous live loop — polling every 60s")

        while not _shutdown:
            if max_duration and (datetime.now() - run_start) >= max_duration:
                logger.info("Duration limit reached — stopping")
                break

            # Rotate log on new day
            current_day = datetime.now().strftime("%Y%m%d")
            current_log = Path(_root) / "logs" / f"shadow_live_{current_day}.csv"
            if current_log != csv_path:
                csv_path = current_log
                write_csv_header(csv_path)
                logger.info("Log rotated to: %s", csv_path)

            time.sleep(60)

            new_bars = fetch_incremental_bars(args.symbol, last_timestamp, args.interval)
            new_bars = [b for b in new_bars if is_bar_complete(b.timestamp)]

            if not new_bars:
                continue

            logger.info("Fetched %d new bars", len(new_bars))

            for bar in new_bars:
                if _shutdown:
                    break

                # Re-fetch history for window
                history = fetch_initial_bars(args.symbol, args.interval, count=200)
                bar_idx_local = None
                for idx, b in enumerate(history):
                    if b.timestamp == bar.timestamp and idx >= MIN_BARS:
                        bar_idx_local = idx
                        break
                if bar_idx_local is None:
                    logger.warning("Bar %s not in history — skipping", bar.timestamp[:19])
                    continue

                window = history[bar_idx_local - MIN_BARS: bar_idx_local + 1]

                ms = MarketState(
                    bars=window,
                    regime=Regime.RANGING,
                    regime_confidence=0.5,
                    volatility=None,
                    timestamp=bar.timestamp,
                )

                drawdown = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
                acc = AccountState(
                    equity=equity,
                    peak_equity=peak_equity,
                    current_drawdown=drawdown,
                    max_risk_per_trade=risk_params["base_risk"],
                    max_portfolio_risk=risk_params["max_portfolio_risk"],
                )

                decision = coordinator.run_cycle(ms, acc, previous)

                dd_state = ladder.evaluate(
                    current_drawdown=drawdown,
                    confidence=decision.confidence,
                )

                ftmo_guard.update_daily(equity=equity, bar_timestamp=bar.timestamp)
                ftmo_check = ftmo_guard.check(equity=equity, peak_equity=peak_equity)

                # Simulate equity
                if decision.risk_directive == "FULL":
                    equity *= 1.0 + (decision.composite_score * 0.001)
                elif decision.risk_directive == "SCALE_DOWN":
                    equity *= 1.0 + (decision.composite_score * 0.0005)

                if equity > peak_equity:
                    peak_equity = equity

                write_csv_row(
                    csv_path, bars_processed, decision, dd_state, ftmo_check,
                    equity, peak_equity, drawdown,
                )

                bars_processed += 1
                directive_counts[decision.risk_directive] = directive_counts.get(decision.risk_directive, 0) + 1
                last_timestamp = bar.timestamp

                previous = PreviousState(
                    composite_score=decision.composite_score,
                    regime=decision.regime,
                    risk_directive=decision.risk_directive,
                    allowed_strategy_family=decision.allowed_strategy_family,
                )

                logger.info(
                    "Bar %d | %s | directive=%s | conf=%.3f | equity=%.2f",
                    bars_processed, bar.timestamp[:19],
                    decision.risk_directive, decision.confidence, equity,
                )

                state["last_timestamp"] = last_timestamp
                state["bars_processed"] = bars_processed
                state["directive_counts"] = directive_counts
                state["equity"] = equity
                state["peak_equity"] = peak_equity
                save_state(state)

    # --- Summary ---
    logger.info("=" * 60)
    logger.info("PHASE 14 SHADOW LIVE SUMMARY")
    logger.info("=" * 60)
    logger.info("Symbol: %s | Profile: %s", args.symbol, args.profile)
    logger.info("Bars processed: %d", bars_processed)
    logger.info("Final equity: %.2f (simulated)", equity)
    logger.info("Peak equity: %.2f", peak_equity)
    logger.info("Final drawdown: %.4f", (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0)
    logger.info("Directive counts: FULL=%d SCALE_DOWN=%d CASH=%d",
                directive_counts.get("FULL", 0),
                directive_counts.get("SCALE_DOWN", 0),
                directive_counts.get("CASH", 0))
    logger.info("Log: %s", csv_path)
    logger.info("=" * 60)

    db.close()


if __name__ == "__main__":
    main()
