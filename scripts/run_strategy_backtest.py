#!/usr/bin/env python
"""Phase 11: Simple Breakout A/B Backtest.

Mode A (baseline): Strategy executes every valid signal, fixed 1% risk.
Mode B (hermes): Strategy gated by Hermes v2.1 + Strategy Family Policy.

Usage:
    python scripts/run_strategy_backtest.py --strategy simple_breakout --mode baseline
    python scripts/run_strategy_backtest.py --strategy simple_breakout --mode hermes
    python scripts/run_strategy_backtest.py --strategy simple_breakout --mode both
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.types import Bar, Direction, Fill, OrderSide, Signal
from src.hermes.agents.base import MarketState
from src.hermes.agents.stub_agents import (
    AMTAgent,
    IchimokuAgent,
    VolatilityAgent,
    WyckoffAgent,
)
from src.hermes.coordinator import AccountState, HermesCoordinator, PreviousState
from src.hermes.conflict import ConflictResolver
from src.hermes.registry import AgentRegistry
from src.hermes.scoring import ScoringEngine
from src.hermes.sizing import PositionSizer
from src.market.data_loader import load_csv, load_csv_multi
from src.market.regime import RegimeDetector
from src.market.ltf_regime_detector import LTFRegimeDetector
from src.market.ltf_buffer import LTFBuffer
from src.orchestration.family_orchestrator import OrchestrationResult, select_strategy
from src.policy.mtf_alignment_policy import MTFAlignmentPolicy
from src.policy.strategy_family_policy import StrategyFamily, StrategyFamilyPolicy
from src.risk.drawdown_ladder import DrawdownLadder, DrawdownProfile
from src.risk.ftmo_guard import FTMOGuard, FTMOConfig
from src.profiles.presets import RISK_PROFILES
from src.strategies.simple_breakout import LOOKBACK as BREAKOUT_LOOKBACK, SimpleBreakoutStrategy
from src.strategies.amt_value_reversion import LOOKBACK as MR_LOOKBACK, AMTValueReversionStrategy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Strategy Registry
# ---------------------------------------------------------------------------
STRATEGY_REGISTRY = {
    "simple_breakout": SimpleBreakoutStrategy,
    "amt_value_reversion": AMTValueReversionStrategy,
}

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BASE_RISK = 0.01  # 1% equity per trade
INITIAL_EQUITY = 100_000.0
DATA_PATH = Path("data/historical/spy_1h_2m.csv")
REPORTS_DIR = Path("reports")


@dataclass
class OpenPosition:
    symbol: str
    side: str
    quantity: float
    entry_price: float
    stop_price: float
    tp_price: float
    entry_bar: int
    entry_timestamp: datetime
    risk_per_unit: float
    # Phase 21: family/regime attribution captured at entry time
    strategy_family: str = ""
    regime_at_entry: str = ""
    risk_directive: str = ""


@dataclass
class TradeRecord:
    symbol: str
    side: str
    quantity: float
    entry_price: float
    exit_price: float
    entry_bar: int
    exit_bar: int
    entry_timestamp: str
    exit_timestamp: str
    pnl: float
    r_multiple: float
    regime_at_entry: str
    exit_reason: str
    # Hermes gating context (mode B only)
    risk_directive: str = ""
    allowed_families: str = ""
    strategy_family: str = ""


@dataclass
class EquityPoint:
    bar: int
    timestamp: str
    equity: float


@dataclass
class GatingLogEntry:
    bar: int
    timestamp: str
    signal_direction: str
    gate_reason: str
    hermes_regime: str
    risk_directive: str
    allowed_families: str
    strategy_family: str
    strategy_id: str


@dataclass
class OrchestrationLogEntry:
    bar: int
    timestamp: str
    hermes_regime: str
    risk_directive: str
    allowed_families: str
    selected_family: str
    selected_strategy: str
    reason: str


@dataclass
class BacktestResult:
    mode: str
    trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    gating_log: list[GatingLogEntry] = field(default_factory=list)
    orchestration_log: list[OrchestrationLogEntry] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stop/TP Management (execution layer)
# ---------------------------------------------------------------------------

def compute_stop(bars: list[Bar], bar_idx: int, lookback: int = BREAKOUT_LOOKBACK) -> float:
    """Lowest low over last N bars at time of entry (for long positions)."""
    start = max(0, bar_idx - lookback)
    return min(b.low for b in bars[start:bar_idx])


def compute_stop_short(bars: list[Bar], bar_idx: int, lookback: int = BREAKOUT_LOOKBACK) -> float:
    """Highest high over last N bars at time of entry (for short positions)."""
    start = max(0, bar_idx - lookback)
    return max(b.high for b in bars[start:bar_idx])


def check_exit(pos: OpenPosition, bar: Bar) -> tuple[bool, str, float]:
    """Check if stop or TP hit. Returns (should_exit, reason, exit_price)."""
    if pos.side == "buy":
        # Long: stop below, TP above
        if bar.low <= pos.stop_price:
            return True, "stop", pos.stop_price
        if bar.high >= pos.tp_price:
            return True, "tp", pos.tp_price
    else:
        # Short: stop above, TP below
        if bar.high >= pos.stop_price:
            return True, "stop", pos.stop_price
        if bar.low <= pos.tp_price:
            return True, "tp", pos.tp_price
    return False, "", 0.0


# ---------------------------------------------------------------------------
# Backtest Engine
# ---------------------------------------------------------------------------

def run_backtest(
    bars: list[Bar],
    mode: str,
    symbol: str = "SPY",
    strategy_name: str = "simple_breakout",
) -> BacktestResult:
    """Run A/B backtest on bars.

    Mode A (baseline): Fixed 1% risk, every signal executes.
    Mode B (hermes): Hermes + Family Policy gating, risk_multiplier sizing.
    """
    strat_cls = STRATEGY_REGISTRY.get(strategy_name)
    if strat_cls is None:
        raise ValueError(f"Unknown strategy: {strategy_name}. Available: {list(STRATEGY_REGISTRY.keys())}")
    strategy = strat_cls()
    result = BacktestResult(mode=mode)

    equity = INITIAL_EQUITY
    peak_equity = equity
    open_position: OpenPosition | None = None
    bars_history: list[Bar] = []

    # Hermes components (mode B only)
    hermes_policy = StrategyFamilyPolicy()
    regime_detector = RegimeDetector()
    prev_state = PreviousState()

    if mode == "hermes":
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

    total_trades = 0
    winning_trades = 0
    total_pnl = 0.0
    r_values: list[float] = []
    max_drawdown = 0.0
    max_dd_duration = 0
    current_dd_duration = 0
    trades_gated = 0
    gate_reasons: dict[str, int] = {}
    regimes_at_entry: list[str] = []

    for i, bar in enumerate(bars):
        bars_history.append(bar)
        timestamp_str = bar.timestamp.isoformat()

        # --- Position management ---
        if open_position is not None:
            should_exit, reason, exit_price = check_exit(open_position, bar)
            if should_exit:
                pnl = (exit_price - open_position.entry_price) * open_position.quantity
                if open_position.side == "sell":
                    pnl = -pnl

                r_mult = 0.0
                if open_position.risk_per_unit > 0:
                    r_mult = pnl / (open_position.risk_per_unit * open_position.quantity)

                trade = TradeRecord(
                    symbol=open_position.symbol,
                    side=open_position.side,
                    quantity=open_position.quantity,
                    entry_price=open_position.entry_price,
                    exit_price=exit_price,
                    entry_bar=open_position.entry_bar,
                    exit_bar=i,
                    entry_timestamp=open_position.entry_timestamp.isoformat(),
                    exit_timestamp=timestamp_str,
                    pnl=pnl,
                    r_multiple=r_mult,
                    regime_at_entry="",
                    exit_reason=reason,
                )
                result.trades.append(trade)
                total_trades += 1
                total_pnl += pnl
                r_values.append(r_mult)
                if pnl > 0:
                    winning_trades += 1

                equity += pnl
                strategy.reset_position()
                open_position = None

        # --- Mark-to-market ---
        unrealized = 0.0
        if open_position is not None:
            unrealized = (bar.close - open_position.entry_price) * open_position.quantity
            if open_position.side == "sell":
                unrealized = -unrealized

        current_equity = equity + unrealized
        result.equity_curve.append(EquityPoint(
            bar=i,
            timestamp=timestamp_str,
            equity=current_equity,
        ))

        if current_equity > peak_equity:
            peak_equity = current_equity
            current_dd_duration = 0
        dd = (peak_equity - current_equity) / peak_equity if peak_equity > 0 else 0.0
        if dd > max_drawdown:
            max_drawdown = dd
        if dd > 0:
            current_dd_duration += 1
            if current_dd_duration > max_dd_duration:
                max_dd_duration = current_dd_duration

        # --- Strategy evaluation ---
        if open_position is not None:
            continue  # don't enter new while in position

        signal = strategy.on_bar(bar, bars_history)
        if signal is None:
            continue

        # Determine entry direction
        is_long = signal.direction == Direction.LONG
        is_short = signal.direction == Direction.SHORT
        entry_side = "buy" if is_long else "sell"

        # --- Mode A: Baseline ---
        if mode == "baseline":
            if is_long:
                stop = compute_stop(bars_history, i)
                risk_per_unit = bar.close - stop
                tp = bar.close + 2 * risk_per_unit
            else:
                stop = compute_stop_short(bars_history, i)
                risk_per_unit = stop - bar.close
                tp = bar.close - 2 * risk_per_unit

            if risk_per_unit <= 0:
                risk_per_unit = 1.0  # fallback

            risk_amount = equity * BASE_RISK
            quantity = risk_amount / risk_per_unit

            open_position = OpenPosition(
                symbol=symbol,
                side=entry_side,
                quantity=quantity,
                entry_price=bar.close,
                stop_price=stop,
                tp_price=tp,
                entry_bar=i,
                entry_timestamp=bar.timestamp,
                risk_per_unit=risk_per_unit,
            )
            regimes_at_entry.append("baseline")

        # --- Mode B: Hermes-gated ---
        elif mode == "hermes":
            # Single regime source: RegimeDetector (same as engine)
            regime = regime_detector.update(bars_history)

            # Build MarketState for Hermes
            market_state = MarketState(
                bars=bars_history[-50:],
                regime=regime,
                regime_confidence=0.5,
                volatility=None,
                timestamp=bar.timestamp,
            )

            # AccountState for sizing
            dd_frac = (peak_equity - current_equity) / peak_equity if peak_equity > 0 else 0.0
            account_state = AccountState(
                equity=current_equity,
                peak_equity=peak_equity,
                current_drawdown=dd_frac,
                max_risk_per_trade=BASE_RISK,
                max_portfolio_risk=0.05,
            )

            # Run Hermes cycle
            decision = coordinator.run_cycle(market_state, account_state, prev_state)

            # Evaluate Strategy Family Policy
            policy_output = hermes_policy.evaluate(decision)

            # Check gating — use strategy's declared family
            strat_family = strategy.family
            allowed = strat_family in policy_output.allowed_families

            if not allowed:
                gate_reason = "family_mismatch"
                if decision.risk_directive == "CASH":
                    gate_reason = "cash_directive"
                elif len(policy_output.allowed_families) == 0:
                    gate_reason = "empty_set"

                result.gating_log.append(GatingLogEntry(
                    bar=i,
                    timestamp=timestamp_str,
                    signal_direction=signal.direction.name,
                    gate_reason=gate_reason,
                    hermes_regime=decision.regime,
                    risk_directive=decision.risk_directive,
                    allowed_families=str(policy_output.allowed_families),
                    strategy_family=str(strat_family),
                    strategy_id=strategy.name,
                ))
                trades_gated += 1
                gate_reasons[gate_reason] = gate_reasons.get(gate_reason, 0) + 1

                # Reset strategy position state — signal was gated, not executed
                strategy.reset_position()

                # Update prev_state for next cycle
                prev_state = PreviousState(
                    composite_score=decision.composite_score,
                    regime=decision.regime,
                    risk_directive=decision.risk_directive,
                    allowed_strategy_family=decision.allowed_strategy_family,
                )
                continue

            # Gating passed — execute with Hermes sizing
            if is_long:
                stop = compute_stop(bars_history, i)
                risk_per_unit = bar.close - stop
                tp = bar.close + 2 * risk_per_unit
            else:
                stop = compute_stop_short(bars_history, i)
                risk_per_unit = stop - bar.close
                tp = bar.close - 2 * risk_per_unit

            if risk_per_unit <= 0:
                risk_per_unit = 1.0

            risk_pct = decision.per_trade_risk
            if risk_pct <= 0:
                risk_pct = BASE_RISK * 0.25  # minimum sizing

            risk_amount = current_equity * risk_pct
            quantity = risk_amount / risk_per_unit

            open_position = OpenPosition(
                symbol=symbol,
                side=entry_side,
                quantity=quantity,
                entry_price=bar.close,
                stop_price=stop,
                tp_price=tp,
                entry_bar=i,
                entry_timestamp=bar.timestamp,
                risk_per_unit=risk_per_unit,
            )
            regimes_at_entry.append(decision.regime)

            # Update prev_state
            prev_state = PreviousState(
                composite_score=decision.composite_score,
                regime=decision.regime,
                risk_directive=decision.risk_directive,
                allowed_strategy_family=decision.allowed_strategy_family,
            )

    # Close any open position at end
    if open_position is not None and len(bars) > 0:
        last_bar = bars[-1]
        pnl = (last_bar.close - open_position.entry_price) * open_position.quantity
        r_mult = pnl / (open_position.risk_per_unit * open_position.quantity) if open_position.risk_per_unit > 0 else 0.0
        trade = TradeRecord(
            symbol=open_position.symbol,
            side=open_position.side,
            quantity=open_position.quantity,
            entry_price=open_position.entry_price,
            exit_price=last_bar.close,
            entry_bar=open_position.entry_bar,
            exit_bar=len(bars) - 1,
            entry_timestamp=open_position.entry_timestamp.isoformat(),
            exit_timestamp=last_bar.timestamp.isoformat(),
            pnl=pnl,
            r_multiple=r_mult,
            regime_at_entry="",
            exit_reason="end_of_data",
        )
        result.trades.append(trade)
        total_trades += 1
        total_pnl += pnl
        r_values.append(r_mult)
        if pnl > 0:
            winning_trades += 1

    # Compute summary
    avg_r = sum(r_values) / len(r_values) if r_values else 0.0
    win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
    gross_profit = sum(r for r in r_values if r > 0)
    gross_loss = abs(sum(r for r in r_values if r < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    result.summary = {
        "mode": mode,
        "total_bars": len(bars),
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": total_trades - winning_trades,
        "win_rate": round(win_rate, 4),
        "total_pnl": round(total_pnl, 2),
        "avg_r_per_trade": round(avg_r, 4),
        "max_drawdown_pct": round(max_drawdown, 4),
        "max_drawdown_duration_bars": max_dd_duration,
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else "inf",
        "trades_gated": trades_gated,
        "gate_reasons": gate_reasons,
    }

    return result


def run_dual_backtest(
    bars: list[Bar],
    symbol: str = "SPY",
) -> BacktestResult:
    """Run dual-family orchestration backtest.

    Both strategies loaded, orchestrator selects one per bar.
    Only the selected strategy may emit signals.
    """
    strategies = {
        "simple_breakout_v1": SimpleBreakoutStrategy(),
        "amt_value_reversion_v1": AMTValueReversionStrategy(),
    }
    result = BacktestResult(mode="dual")

    equity = INITIAL_EQUITY
    peak_equity = equity
    open_position: OpenPosition | None = None
    bars_history: list[Bar] = []

    hermes_policy = StrategyFamilyPolicy()
    regime_detector = RegimeDetector()
    prev_state = PreviousState()

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

    total_trades = 0
    winning_trades = 0
    total_pnl = 0.0
    r_values: list[float] = []
    max_drawdown = 0.0
    max_dd_duration = 0
    current_dd_duration = 0
    trades_gated = 0
    gate_reasons: dict[str, int] = {}
    family_bars: dict[str, int] = {"STRUCTURAL_FRACTAL": 0, "MEAN_REVERSION": 0, "NONE": 0}
    family_switches = 0
    last_selected_family: str | None = None

    # Phase 21: per-family and per-regime tracking
    family_pnl: dict[str, float] = {"STRUCTURAL_FRACTAL": 0.0, "MEAN_REVERSION": 0.0, "NONE": 0.0}
    family_trades: dict[str, int] = {"STRUCTURAL_FRACTAL": 0, "MEAN_REVERSION": 0, "NONE": 0}
    family_wins: dict[str, int] = {"STRUCTURAL_FRACTAL": 0, "MEAN_REVERSION": 0, "NONE": 0}
    family_r_values: dict[str, list[float]] = {"STRUCTURAL_FRACTAL": [], "MEAN_REVERSION": [], "NONE": []}
    regime_pnl: dict[str, float] = {}
    regime_trades: dict[str, int] = {}
    directive_pnl: dict[str, float] = {}
    directive_trades: dict[str, int] = {}

    for i, bar in enumerate(bars):
        bars_history.append(bar)
        timestamp_str = bar.timestamp.isoformat()

        # --- Position management ---
        if open_position is not None:
            should_exit, reason, exit_price = check_exit(open_position, bar)
            if should_exit:
                pnl = (exit_price - open_position.entry_price) * open_position.quantity
                if open_position.side == "sell":
                    pnl = -pnl

                r_mult = 0.0
                if open_position.risk_per_unit > 0:
                    r_mult = pnl / (open_position.risk_per_unit * open_position.quantity)

                trade = TradeRecord(
                    symbol=open_position.symbol,
                    side=open_position.side,
                    quantity=open_position.quantity,
                    entry_price=open_position.entry_price,
                    exit_price=exit_price,
                    entry_bar=open_position.entry_bar,
                    exit_bar=i,
                    entry_timestamp=open_position.entry_timestamp.isoformat(),
                    exit_timestamp=timestamp_str,
                    pnl=pnl,
                    r_multiple=r_mult,
                    regime_at_entry=open_position.regime_at_entry,
                    exit_reason=reason,
                    risk_directive=open_position.risk_directive,
                    strategy_family=open_position.strategy_family,
                )
                result.trades.append(trade)
                total_trades += 1
                total_pnl += pnl
                r_values.append(r_mult)
                if pnl > 0:
                    winning_trades += 1

                # Phase 21: attribute to family and regime
                fam = open_position.strategy_family or "NONE"
                family_pnl[fam] = family_pnl.get(fam, 0.0) + pnl
                family_trades[fam] = family_trades.get(fam, 0) + 1
                family_wins[fam] = family_wins.get(fam, 0) + (1 if pnl > 0 else 0)
                family_r_values.setdefault(fam, []).append(r_mult)

                reg = open_position.regime_at_entry or "UNKNOWN"
                regime_pnl[reg] = regime_pnl.get(reg, 0.0) + pnl
                regime_trades[reg] = regime_trades.get(reg, 0) + 1

                directive = open_position.risk_directive or "UNKNOWN"
                directive_pnl[directive] = directive_pnl.get(directive, 0.0) + pnl
                directive_trades[directive] = directive_trades.get(directive, 0) + 1

                equity += pnl
                open_position = None

        # --- Mark-to-market ---
        unrealized = 0.0
        if open_position is not None:
            unrealized = (bar.close - open_position.entry_price) * open_position.quantity
            if open_position.side == "sell":
                unrealized = -unrealized

        current_equity = equity + unrealized
        result.equity_curve.append(EquityPoint(bar=i, timestamp=timestamp_str, equity=current_equity))

        if current_equity > peak_equity:
            peak_equity = current_equity
            current_dd_duration = 0
        dd = (peak_equity - current_equity) / peak_equity if peak_equity > 0 else 0.0
        if dd > max_drawdown:
            max_drawdown = dd
        if dd > 0:
            current_dd_duration += 1
            if current_dd_duration > max_dd_duration:
                max_dd_duration = current_dd_duration

        # --- Strategy evaluation ---
        if open_position is not None:
            continue

        # Hermes cycle
        regime = regime_detector.update(bars_history)
        market_state = MarketState(bars=bars_history[-50:], regime=regime, regime_confidence=0.5, volatility=None, timestamp=bar.timestamp)
        dd_frac = (peak_equity - current_equity) / peak_equity if peak_equity > 0 else 0.0
        account_state = AccountState(equity=current_equity, peak_equity=peak_equity, current_drawdown=dd_frac, max_risk_per_trade=BASE_RISK, max_portfolio_risk=0.05)
        decision = coordinator.run_cycle(market_state, account_state, prev_state)
        policy_output = hermes_policy.evaluate(decision)

        # Family selection via orchestrator
        orch_result = select_strategy(policy_output.allowed_families, strategies)

        # Track family bars
        fam_key = orch_result.selected_family.name if orch_result.selected_family else "NONE"
        family_bars[fam_key] = family_bars.get(fam_key, 0) + 1

        # Track family switches
        if fam_key != "NONE" and fam_key != last_selected_family:
            if last_selected_family is not None and last_selected_family != "NONE":
                family_switches += 1
            last_selected_family = fam_key

        result.orchestration_log.append(OrchestrationLogEntry(
            bar=i, timestamp=timestamp_str, hermes_regime=decision.regime,
            risk_directive=decision.risk_directive, allowed_families=str(policy_output.allowed_families),
            selected_family=fam_key, selected_strategy=orch_result.selected_strategy_name or "NONE", reason=orch_result.reason,
        ))

        if orch_result.selected_strategy_name is None:
            trades_gated += 1
            gate_reasons["no_strategy"] = gate_reasons.get("no_strategy", 0) + 1
            prev_state = PreviousState(composite_score=decision.composite_score, regime=decision.regime, risk_directive=decision.risk_directive, allowed_strategy_family=decision.allowed_strategy_family)
            continue

        # Get signal from selected strategy
        strategy = strategies[orch_result.selected_strategy_name]
        signal = strategy.on_bar(bar, bars_history)
        if signal is None:
            prev_state = PreviousState(composite_score=decision.composite_score, regime=decision.regime, risk_directive=decision.risk_directive, allowed_strategy_family=decision.allowed_strategy_family)
            continue

        is_long = signal.direction == Direction.LONG
        entry_side = "buy" if is_long else "sell"

        if is_long:
            stop = compute_stop(bars_history, i)
            risk_per_unit = bar.close - stop
            tp = bar.close + 2 * risk_per_unit
        else:
            stop = compute_stop_short(bars_history, i)
            risk_per_unit = stop - bar.close
            tp = bar.close - 2 * risk_per_unit

        if risk_per_unit <= 0:
            risk_per_unit = 1.0

        risk_pct = decision.per_trade_risk
        if risk_pct <= 0:
            risk_pct = BASE_RISK * 0.25

        risk_amount = current_equity * risk_pct
        quantity = risk_amount / risk_per_unit

        open_position = OpenPosition(symbol=symbol, side=entry_side, quantity=quantity, entry_price=bar.close, stop_price=stop, tp_price=tp, entry_bar=i, entry_timestamp=bar.timestamp, risk_per_unit=risk_per_unit, strategy_family=fam_key, regime_at_entry=decision.regime, risk_directive=decision.risk_directive)

        prev_state = PreviousState(composite_score=decision.composite_score, regime=decision.regime, risk_directive=decision.risk_directive, allowed_strategy_family=decision.allowed_strategy_family)

    # Close any open position at end
    if open_position is not None and len(bars) > 0:
        last_bar = bars[-1]
        pnl = (last_bar.close - open_position.entry_price) * open_position.quantity
        r_mult = pnl / (open_position.risk_per_unit * open_position.quantity) if open_position.risk_per_unit > 0 else 0.0
        trade = TradeRecord(symbol=open_position.symbol, side=open_position.side, quantity=open_position.quantity, entry_price=open_position.entry_price, exit_price=last_bar.close, entry_bar=open_position.entry_bar, exit_bar=len(bars) - 1, entry_timestamp=open_position.entry_timestamp.isoformat(), exit_timestamp=last_bar.timestamp.isoformat(), pnl=pnl, r_multiple=r_mult, regime_at_entry=open_position.regime_at_entry, exit_reason="end_of_data", risk_directive=open_position.risk_directive, strategy_family=open_position.strategy_family)
        result.trades.append(trade)
        total_trades += 1
        total_pnl += pnl
        r_values.append(r_mult)
        if pnl > 0:
            winning_trades += 1

        # Phase 21: attribute end-of-data trade
        fam = open_position.strategy_family or "NONE"
        family_pnl[fam] = family_pnl.get(fam, 0.0) + pnl
        family_trades[fam] = family_trades.get(fam, 0) + 1
        family_wins[fam] = family_wins.get(fam, 0) + (1 if pnl > 0 else 0)
        family_r_values.setdefault(fam, []).append(r_mult)

    avg_r = sum(r_values) / len(r_values) if r_values else 0.0
    win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
    gross_profit = sum(r for r in r_values if r > 0)
    gross_loss = abs(sum(r for r in r_values if r < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Phase 21: compute per-family stats
    family_stats = {}
    for fam in ["STRUCTURAL_FRACTAL", "MEAN_REVERSION"]:
        f_trades = family_trades.get(fam, 0)
        f_r = family_r_values.get(fam, [])
        family_stats[fam] = {
            "pnl": round(family_pnl.get(fam, 0.0), 2),
            "trades": f_trades,
            "wins": family_wins.get(fam, 0),
            "win_rate": round(family_wins.get(fam, 0) / f_trades, 4) if f_trades > 0 else 0.0,
            "avg_r": round(sum(f_r) / len(f_r), 4) if f_r else 0.0,
        }

    result.summary = {
        "mode": "dual", "total_bars": len(bars), "total_trades": total_trades,
        "winning_trades": winning_trades, "losing_trades": total_trades - winning_trades,
        "win_rate": round(win_rate, 4), "total_pnl": round(total_pnl, 2),
        "avg_r_per_trade": round(avg_r, 4), "max_drawdown_pct": round(max_drawdown, 4),
        "max_drawdown_duration_bars": max_dd_duration,
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else "inf",
        "trades_gated": trades_gated, "gate_reasons": gate_reasons,
        "family_bars": family_bars, "family_switches": family_switches,
        "family_stats": family_stats,
        "regime_pnl": {k: round(v, 2) for k, v in regime_pnl.items()},
        "regime_trades": regime_trades,
        "directive_pnl": {k: round(v, 2) for k, v in directive_pnl.items()},
        "directive_trades": directive_trades,
    }
    return result


def run_dual_mtf_backtest(
    bars: list[Bar],
    symbol: str = "SPY",
    ltf_bars: list[Bar] | None = None,
    risk_profile: str | None = None,
) -> BacktestResult:
    """Run dual-family orchestration with MTF + Drawdown Ladder + FTMO.

    Identical to run_dual_backtest except:
    - MTF alignment policy dampens risk when HTF/LTF regimes conflict
    - LTF regime detector runs on TRUE 15m bars when available (via LTFBuffer)
    - When LTF data is unavailable, MTF state = NEUTRAL (no effect)
    - Phase 22: DrawdownLadder evaluates risk per bar
    - Phase 22: FTMOGuard enforces daily/total loss limits

    Args:
        bars: HTF bars for backtest.
        symbol: Asset symbol.
        ltf_bars: Optional LTF bars for MTF alignment.
        risk_profile: Risk appetite profile name (aggressive/balanced/conservative/ftmo_safe).
            If None, uses default DrawdownLadder with BASE_RISK.
    """
    # --- Phase 22: Initialize drawdown ladder and FTMO guard from profile ---
    if risk_profile and risk_profile in RISK_PROFILES:
        rp = RISK_PROFILES[risk_profile]
        ladder = DrawdownLadder.from_profile(rp["drawdown_ladder"])
        ftmo_config = FTMOConfig(**rp["ftmo"])
        ftmo_guard = FTMOGuard(config=ftmo_config)
        base_risk = rp["risk"]["base_risk"]
        max_portfolio_risk = rp["risk"]["max_portfolio_risk"]
        logger.info(
            "Phase 22: Using risk profile '%s' (base_risk=%.4f, max_portfolio_risk=%.4f)",
            risk_profile, base_risk, max_portfolio_risk,
        )
    else:
        ladder = DrawdownLadder()
        ftmo_guard = None
        base_risk = BASE_RISK
        max_portfolio_risk = 0.05
    strategies = {
        "simple_breakout_v1": SimpleBreakoutStrategy(),
        "amt_value_reversion_v1": AMTValueReversionStrategy(),
    }
    result = BacktestResult(mode="dual_mtf")

    equity = INITIAL_EQUITY
    peak_equity = equity
    open_position: OpenPosition | None = None
    bars_history: list[Bar] = []

    hermes_policy = StrategyFamilyPolicy()
    regime_detector = RegimeDetector()
    ltf_detector = LTFRegimeDetector()
    mtf_policy = MTFAlignmentPolicy()
    prev_state = PreviousState()

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

    total_trades = 0
    winning_trades = 0
    total_pnl = 0.0
    r_values: list[float] = []
    max_drawdown = 0.0
    max_dd_duration = 0
    current_dd_duration = 0
    trades_gated = 0
    gate_reasons: dict[str, int] = {}
    family_bars: dict[str, int] = {"STRUCTURAL_FRACTAL": 0, "MEAN_REVERSION": 0, "NONE": 0}
    family_switches = 0
    last_selected_family: str | None = None
    mtf_log: list[dict] = []

    # Phase 21: per-family and per-regime tracking
    family_pnl: dict[str, float] = {"STRUCTURAL_FRACTAL": 0.0, "MEAN_REVERSION": 0.0, "NONE": 0.0}
    family_trades: dict[str, int] = {"STRUCTURAL_FRACTAL": 0, "MEAN_REVERSION": 0, "NONE": 0}
    family_wins: dict[str, int] = {"STRUCTURAL_FRACTAL": 0, "MEAN_REVERSION": 0, "NONE": 0}
    family_r_values: dict[str, list[float]] = {"STRUCTURAL_FRACTAL": [], "MEAN_REVERSION": [], "NONE": []}
    regime_pnl: dict[str, float] = {}
    regime_trades: dict[str, int] = {}
    directive_pnl: dict[str, float] = {}
    directive_trades: dict[str, int] = {}

    # Phase 22: drawdown ladder and FTMO tracking
    dd_state_log: list[dict] = []
    ftmo_compliance_log: list[dict] = []

    # Phase 16: Use TRUE 15m data via LTFBuffer when available
    ltf_data_available = ltf_bars is not None and len(ltf_bars) > 0
    ltf_buffer: LTFBuffer | None = LTFBuffer(ltf_bars) if ltf_data_available else None
    if ltf_data_available:
        logger.info("MTF: Using TRUE 15m data (%d bars)", len(ltf_bars))
    else:
        logger.info("MTF: No 15m data; LTF regime will be UNKNOWN")

    for i, bar in enumerate(bars):
        bars_history.append(bar)
        timestamp_str = bar.timestamp.isoformat()

        # --- Position management ---
        if open_position is not None:
            should_exit, reason, exit_price = check_exit(open_position, bar)
            if should_exit:
                pnl = (exit_price - open_position.entry_price) * open_position.quantity
                if open_position.side == "sell":
                    pnl = -pnl
                r_mult = 0.0
                if open_position.risk_per_unit > 0:
                    r_mult = pnl / (open_position.risk_per_unit * open_position.quantity)
                trade = TradeRecord(
                    symbol=open_position.symbol, side=open_position.side,
                    quantity=open_position.quantity, entry_price=open_position.entry_price,
                    exit_price=exit_price, entry_bar=open_position.entry_bar, exit_bar=i,
                    entry_timestamp=open_position.entry_timestamp.isoformat(),
                    exit_timestamp=timestamp_str, pnl=pnl, r_multiple=r_mult,
                    regime_at_entry=open_position.regime_at_entry, exit_reason=reason,
                    risk_directive=open_position.risk_directive,
                    strategy_family=open_position.strategy_family,
                )
                result.trades.append(trade)
                total_trades += 1
                total_pnl += pnl
                r_values.append(r_mult)
                if pnl > 0:
                    winning_trades += 1

                # Phase 21: attribute to family and regime
                fam = open_position.strategy_family or "NONE"
                family_pnl[fam] = family_pnl.get(fam, 0.0) + pnl
                family_trades[fam] = family_trades.get(fam, 0) + 1
                family_wins[fam] = family_wins.get(fam, 0) + (1 if pnl > 0 else 0)
                family_r_values.setdefault(fam, []).append(r_mult)

                reg = open_position.regime_at_entry or "UNKNOWN"
                regime_pnl[reg] = regime_pnl.get(reg, 0.0) + pnl
                regime_trades[reg] = regime_trades.get(reg, 0) + 1

                directive = open_position.risk_directive or "UNKNOWN"
                directive_pnl[directive] = directive_pnl.get(directive, 0.0) + pnl
                directive_trades[directive] = directive_trades.get(directive, 0) + 1

                equity += pnl
                open_position = None

        # --- Mark-to-market ---
        unrealized = 0.0
        if open_position is not None:
            unrealized = (bar.close - open_position.entry_price) * open_position.quantity
            if open_position.side == "sell":
                unrealized = -unrealized
        current_equity = equity + unrealized
        result.equity_curve.append(EquityPoint(bar=i, timestamp=timestamp_str, equity=current_equity))
        if current_equity > peak_equity:
            peak_equity = current_equity
            current_dd_duration = 0
        dd = (peak_equity - current_equity) / peak_equity if peak_equity > 0 else 0.0
        if dd > max_drawdown:
            max_drawdown = dd
        if dd > 0:
            current_dd_duration += 1
            if current_dd_duration > max_dd_duration:
                max_dd_duration = current_dd_duration

        # --- Strategy evaluation ---
        if open_position is not None:
            continue

        # Hermes cycle
        regime = regime_detector.update(bars_history)
        market_state = MarketState(bars=bars_history[-50:], regime=regime, regime_confidence=0.5, volatility=None, timestamp=bar.timestamp)
        dd_frac = (peak_equity - current_equity) / peak_equity if peak_equity > 0 else 0.0
        account_state = AccountState(equity=current_equity, peak_equity=peak_equity, current_drawdown=dd_frac, max_risk_per_trade=base_risk, max_portfolio_risk=max_portfolio_risk)
        decision = coordinator.run_cycle(market_state, account_state, prev_state)
        policy_output = hermes_policy.evaluate(decision)

        # --- MTF alignment (risk refinement only) ---
        # Phase 16: Feed TRUE 15m bars to LTF detector via LTFBuffer
        if ltf_buffer is not None:
            ltf_window = ltf_buffer.get_bars_for_htf(bar)
            if ltf_window:
                ltf_regime = ltf_detector.update(ltf_window)
            else:
                ltf_regime = "UNKNOWN"
        else:
            ltf_regime = "UNKNOWN"
        mtf_output = mtf_policy.evaluate(regime, ltf_regime, decision.per_trade_risk)
        adjusted_risk = mtf_output.adjusted_risk_multiplier

        # --- Phase 22: Drawdown ladder evaluation ---
        dd_state = ladder.evaluate(
            current_drawdown=dd_frac,
            confidence=decision.confidence,
        )

        # --- Phase 22: FTMO compliance check ---
        ftmo_halt = False
        ftmo_reduce = False
        if ftmo_guard is not None:
            ftmo_guard.update_daily(equity=current_equity, bar_timestamp=bar.timestamp)
            ftmo_check = ftmo_guard.check(equity=current_equity, peak_equity=peak_equity)
            if ftmo_check.action == "HALT":
                ftmo_halt = True
            elif ftmo_check.action == "REDUCE":
                ftmo_reduce = True
            ftmo_compliance_log.append({
                "bar": i,
                "equity": round(current_equity, 2),
                "peak_equity": round(peak_equity, 2),
                "ftmo_action": ftmo_check.action,
                "daily_loss_remaining": round(ftmo_check.daily_loss_remaining, 4),
                "total_dd_remaining": round(ftmo_check.total_drawdown_remaining, 4),
                "violations": list(ftmo_check.violations),
            })

        # --- Phase 22: Risk formula ---
        # TotalRisk = BaseRisk × AlignmentMultiplier × DrawdownMultiplier
        total_risk = ladder.compute_total_risk(
            base_risk=base_risk,
            alignment_multiplier=adjusted_risk,
            drawdown_multiplier=dd_state.size_multiplier,
        )

        # FTMO override
        if ftmo_halt:
            total_risk = 0.0
        elif ftmo_reduce:
            total_risk *= 0.5

        # Track drawdown ladder state
        dd_state_log.append({
            "bar": i,
            "stage": dd_state.stage,
            "drawdown_pct": round(dd_frac, 4),
            "size_multiplier": dd_state.size_multiplier,
            "total_risk": round(total_risk, 6),
            "ftmo_halt": ftmo_halt,
            "ftmo_reduce": ftmo_reduce,
        })

        # Family selection via orchestrator
        orch_result = select_strategy(policy_output.allowed_families, strategies)

        # Track family bars
        fam_key = orch_result.selected_family.name if orch_result.selected_family else "NONE"
        family_bars[fam_key] = family_bars.get(fam_key, 0) + 1
        if fam_key != "NONE" and fam_key != last_selected_family:
            if last_selected_family is not None and last_selected_family != "NONE":
                family_switches += 1
            last_selected_family = fam_key

        # Log MTF state with coverage ratio
        htf_regime_str = regime.value if hasattr(regime, "value") else str(regime)
        ltf_regime_str = ltf_regime.value if hasattr(ltf_regime, "value") else str(ltf_regime)

        # LTF coverage ratio (how many of the expected 4 bars were present)
        if ltf_buffer is not None:
            ltf_window_for_log = ltf_buffer.get_bars_for_htf(bar)
            ltf_bars_count = len(ltf_window_for_log)
        else:
            ltf_bars_count = 0
        ltf_coverage_ratio = ltf_bars_count / 4.0

        mtf_log.append({
            "bar": i,
            "htf_regime": htf_regime_str,
            "ltf_regime": ltf_regime_str if ltf_data_available else "UNKNOWN",
            "mtf_state": mtf_output.mtf_state,
            "hermes_risk": decision.per_trade_risk,
            "adjusted_risk": adjusted_risk,
            "selected_family": fam_key,
            "selected_strategy": orch_result.selected_strategy_name or "NONE",
            "ltf_bars_count": ltf_bars_count,
            "ltf_coverage_ratio": ltf_coverage_ratio,
        })

        result.orchestration_log.append(OrchestrationLogEntry(
            bar=i, timestamp=timestamp_str, hermes_regime=decision.regime,
            risk_directive=decision.risk_directive, allowed_families=str(policy_output.allowed_families),
            selected_family=fam_key, selected_strategy=orch_result.selected_strategy_name or "NONE", reason=orch_result.reason,
        ))

        if orch_result.selected_strategy_name is None:
            trades_gated += 1
            gate_reasons["no_strategy"] = gate_reasons.get("no_strategy", 0) + 1
            prev_state = PreviousState(composite_score=decision.composite_score, regime=decision.regime, risk_directive=decision.risk_directive, allowed_strategy_family=decision.allowed_strategy_family)
            continue

        # Get signal from selected strategy
        strategy = strategies[orch_result.selected_strategy_name]
        signal = strategy.on_bar(bar, bars_history)
        if signal is None:
            prev_state = PreviousState(composite_score=decision.composite_score, regime=decision.regime, risk_directive=decision.risk_directive, allowed_strategy_family=decision.allowed_strategy_family)
            continue

        is_long = signal.direction == Direction.LONG
        entry_side = "buy" if is_long else "sell"

        if is_long:
            stop = compute_stop(bars_history, i)
            risk_per_unit = bar.close - stop
            tp = bar.close + 2 * risk_per_unit
        else:
            stop = compute_stop_short(bars_history, i)
            risk_per_unit = stop - bar.close
            tp = bar.close - 2 * risk_per_unit

        if risk_per_unit <= 0:
            risk_per_unit = 1.0

        # Phase 22: Use total_risk (BaseRisk × AlignmentMult × DrawdownMult)
        risk_pct = total_risk
        if risk_pct <= 0:
            risk_pct = base_risk * 0.25

        risk_amount = current_equity * risk_pct
        quantity = risk_amount / risk_per_unit

        open_position = OpenPosition(symbol=symbol, side=entry_side, quantity=quantity, entry_price=bar.close, stop_price=stop, tp_price=tp, entry_bar=i, entry_timestamp=bar.timestamp, risk_per_unit=risk_per_unit, strategy_family=fam_key, regime_at_entry=decision.regime, risk_directive=decision.risk_directive)

        prev_state = PreviousState(composite_score=decision.composite_score, regime=decision.regime, risk_directive=decision.risk_directive, allowed_strategy_family=decision.allowed_strategy_family)

    # Close any open position at end
    if open_position is not None and len(bars) > 0:
        last_bar = bars[-1]
        pnl = (last_bar.close - open_position.entry_price) * open_position.quantity
        r_mult = pnl / (open_position.risk_per_unit * open_position.quantity) if open_position.risk_per_unit > 0 else 0.0
        trade = TradeRecord(symbol=open_position.symbol, side=open_position.side, quantity=open_position.quantity, entry_price=open_position.entry_price, exit_price=last_bar.close, entry_bar=open_position.entry_bar, exit_bar=len(bars) - 1, entry_timestamp=open_position.entry_timestamp.isoformat(), exit_timestamp=last_bar.timestamp.isoformat(), pnl=pnl, r_multiple=r_mult, regime_at_entry=open_position.regime_at_entry, exit_reason="end_of_data", risk_directive=open_position.risk_directive, strategy_family=open_position.strategy_family)
        result.trades.append(trade)
        total_trades += 1
        total_pnl += pnl
        r_values.append(r_mult)
        if pnl > 0:
            winning_trades += 1

        # Phase 21: attribute end-of-data trade
        fam = open_position.strategy_family or "NONE"
        family_pnl[fam] = family_pnl.get(fam, 0.0) + pnl
        family_trades[fam] = family_trades.get(fam, 0) + 1
        family_wins[fam] = family_wins.get(fam, 0) + (1 if pnl > 0 else 0)
        family_r_values.setdefault(fam, []).append(r_mult)

    avg_r = sum(r_values) / len(r_values) if r_values else 0.0
    win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
    gross_profit = sum(r for r in r_values if r > 0)
    gross_loss = abs(sum(r for r in r_values if r < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Phase 21: compute per-family stats
    family_stats = {}
    for fam in ["STRUCTURAL_FRACTAL", "MEAN_REVERSION"]:
        f_trades = family_trades.get(fam, 0)
        f_r = family_r_values.get(fam, [])
        family_stats[fam] = {
            "pnl": round(family_pnl.get(fam, 0.0), 2),
            "trades": f_trades,
            "wins": family_wins.get(fam, 0),
            "win_rate": round(family_wins.get(fam, 0) / f_trades, 4) if f_trades > 0 else 0.0,
            "avg_r": round(sum(f_r) / len(f_r), 4) if f_r else 0.0,
        }

    result.summary = {
        "mode": "dual_mtf", "total_bars": len(bars), "total_trades": total_trades,
        "winning_trades": winning_trades, "losing_trades": total_trades - winning_trades,
        "win_rate": round(win_rate, 4), "total_pnl": round(total_pnl, 2),
        "avg_r_per_trade": round(avg_r, 4), "max_drawdown_pct": round(max_drawdown, 4),
        "max_drawdown_duration_bars": max_dd_duration,
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else "inf",
        "trades_gated": trades_gated, "gate_reasons": gate_reasons,
        "family_bars": family_bars, "family_switches": family_switches,
        "family_stats": family_stats,
        "regime_pnl": {k: round(v, 2) for k, v in regime_pnl.items()},
        "regime_trades": regime_trades,
        "directive_pnl": {k: round(v, 2) for k, v in directive_pnl.items()},
        "directive_trades": directive_trades,
        "ltf_data_available": ltf_data_available,
        "mtf_log_summary": {"total_bars": len(mtf_log)},
        # Phase 22: drawdown ladder and FTMO logs
        "risk_profile": risk_profile,
        "drawdown_ladder_log": dd_state_log,
        "ftmo_compliance_log": ftmo_compliance_log,
        "ftmo_final_status": {
            "guard_active": ftmo_guard is not None,
            "max_drawdown": round(max_drawdown, 4),
            "total_pnl": round(total_pnl, 2),
        },
    }

    # Save MTF log
    mtf_log_path = REPORTS_DIR / "mtf_alignment_log.json"
    mtf_log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(mtf_log_path, "w") as f:
        json.dump(mtf_log, f, indent=2)
    print(f"  MTF alignment log: {mtf_log_path}")

    return result


def save_result(result: BacktestResult, output_path: Path) -> None:
    """Save backtest result to JSON."""
    output = {
        "mode": result.mode,
        "summary": result.summary,
        "trades": [
            {
                "symbol": t.symbol,
                "side": t.side,
                "quantity": round(t.quantity, 6),
                "entry_price": round(t.entry_price, 2),
                "exit_price": round(t.exit_price, 2),
                "entry_bar": t.entry_bar,
                "exit_bar": t.exit_bar,
                "entry_timestamp": t.entry_timestamp,
                "exit_timestamp": t.exit_timestamp,
                "pnl": round(t.pnl, 2),
                "r_multiple": round(t.r_multiple, 4),
                "exit_reason": t.exit_reason,
                "strategy_family": t.strategy_family,
                "regime_at_entry": t.regime_at_entry,
                "risk_directive": t.risk_directive,
            }
            for t in result.trades
        ],
        "equity_curve": [
            {"bar": e.bar, "timestamp": e.timestamp, "equity": round(e.equity, 2)}
            for e in result.equity_curve
        ],
    }

    if result.orchestration_log:
        output["orchestration_log"] = [
            {
                "bar": o.bar,
                "timestamp": o.timestamp,
                "hermes_regime": o.hermes_regime,
                "risk_directive": o.risk_directive,
                "allowed_families": o.allowed_families,
                "selected_family": o.selected_family,
                "selected_strategy": o.selected_strategy,
                "reason": o.reason,
            }
            for o in result.orchestration_log
        ]

    if result.gating_log:
        output["gating_log"] = [
            {
                "bar": g.bar,
                "timestamp": g.timestamp,
                "signal_direction": g.signal_direction,
                "gate_reason": g.gate_reason,
                "hermes_regime": g.hermes_regime,
                "risk_directive": g.risk_directive,
                "allowed_families": g.allowed_families,
                "strategy_family": g.strategy_family,
                "strategy_id": g.strategy_id,
            }
            for g in result.gating_log
        ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Saved: {output_path}")
    print(f"  Trades: {result.summary['total_trades']}")
    print(f"  Win rate: {result.summary['win_rate']:.1%}")
    print(f"  Avg R: {result.summary['avg_r_per_trade']:.2f}")
    print(f"  Max DD: {result.summary['max_drawdown_pct']:.1%}")
    if result.gating_log:
        print(f"  Trades gated: {result.summary['trades_gated']}")
        print(f"  Gate reasons: {result.summary['gate_reasons']}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 11: Simple Breakout A/B Backtest")
    parser.add_argument("--strategy", default="simple_breakout", help="Strategy name")
    parser.add_argument("--mode", choices=["baseline", "hermes", "both", "dual", "dual_mtf"], default="both",
                        help="Run mode: baseline, hermes, both, dual, or dual_mtf")
    parser.add_argument("--data", default=str(DATA_PATH), help="CSV data path")
    parser.add_argument("--symbol", default="SPY", help="Trading symbol")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Load data
    data_path = Path(args.data)
    if not data_path.exists():
        print(f"Error: Data file not found: {data_path}")
        sys.exit(1)

    # Auto-detect LTF data: look for spy_15m_2m.csv in same directory as 1H file
    ltf_path = data_path.parent / "spy_15m_2m.csv"
    if args.mode == "dual_mtf" and ltf_path.exists():
        htf_bars, ltf_bars_data = load_csv_multi(str(data_path), str(ltf_path))
        print(f"Loaded {len(htf_bars)} HTF bars + {len(ltf_bars_data or [])} LTF bars")
    else:
        htf_bars = load_csv(str(data_path))
        ltf_bars_data = None
        print(f"Loaded {len(htf_bars)} bars from {data_path}")

    bars = htf_bars

    modes = []
    if args.mode == "both":
        modes = ["baseline", "hermes"]
    else:
        modes = [args.mode]

    for mode in modes:
        print(f"\n{'='*60}")
        print(f"Running: {args.strategy} | Mode: {mode}")
        print(f"{'='*60}")

        if mode == "dual":
            result = run_dual_backtest(bars, symbol=args.symbol)
        elif mode == "dual_mtf":
            result = run_dual_mtf_backtest(bars, symbol=args.symbol, ltf_bars=ltf_bars_data)
        else:
            result = run_backtest(bars, mode, symbol=args.symbol, strategy_name=args.strategy)
        output_path = REPORTS_DIR / f"strategy_backtest_{mode}.json"
        save_result(result, output_path)


if __name__ == "__main__":
    main()