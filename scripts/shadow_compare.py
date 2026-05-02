"""Shadow comparison: Hermes v1 vs v2 side-by-side on CSV replay.

Runs both versions on the same bar sequence:
  - v1 drives execution (unchanged, default behavior)
  - v2 runs in observation-only mode (logged, never executed)

Supports:
  - Multiple CSV files (per-symbol + aggregate KPIs)
  - Rolling window analysis (--window N)
  - Distribution-aware KPIs (percentiles, streaks, transitions)

Usage:
    python scripts/shadow_compare.py
    python scripts/shadow_compare.py --config config/engine.yaml
    python scripts/shadow_compare.py --csv data/sample/spy_1h.csv
    python scripts/shadow_compare.py --csv data/sample/spy_1h.csv data/sample/btcusd_1h.csv
    python scripts/shadow_compare.py --csv data/sample/spy_1h.csv --window 20
"""

from __future__ import annotations

import json
import logging
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field

import yaml

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.types import Bar, Direction, Fill, Order, OrderSide, PortfolioState, Regime, Signal
from src.core.clock import SimClock
from src.core.events import EventBus
from src.market.data_loader import load_csv
from src.market.csv_adapter import CsvMarketDataAdapter
from src.market.regime import RegimeDetector
from src.strategies.sma_crossover import SMACrossoverStrategy
from src.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
from src.hermes.policy import Policy
from src.hermes.metrics import MetricsTracker
from src.hermes.agent import HermesAgent, StrategyAllocation
from src.hermes.coordinator import HermesCoordinator, AccountState, PreviousState
from src.hermes.agents.stub_agents import (
    IchimokuAgent, VolatilityAgent, AMTAgent, WyckoffAgent,
)
from src.hermes.registry import AgentRegistry
from src.hermes.scoring import ScoringEngine
from src.hermes.conflict import ConflictResolver
from src.hermes.sizing import PositionSizer
from src.hermes.agents.base import MarketState
from src.risk.layer import RiskLayer, RiskLimits
from src.execution.mock_broker import MockBroker
from src.engine.runner import TradingEngine

logger = logging.getLogger("shadow_compare")


# ---------------------------------------------------------------------------
# Per-bar comparison record
# ---------------------------------------------------------------------------

@dataclass
class BarComparison:
    """One bar's v1 vs v2 snapshot."""
    bar_ts: str
    bar_idx: int

    # v1 outputs
    v1_regime: str | None = None
    v1_allocations: dict[str, float] = field(default_factory=dict)
    v1_risk_posture: str = "NORMAL"
    v1_signals: int = 0
    v1_fills: int = 0

    # v2 outputs
    v2_regime: str | None = None
    v2_risk_directive: str = "FULL"
    v2_composite_score: float = 0.0
    v2_confidence: float = 0.0
    v2_allowed_family: str | None = None
    v2_agent_scores: dict[str, float] = field(default_factory=dict)
    v2_agent_confidences: dict[str, float] = field(default_factory=dict)

    # Agent score dispersion (max - min across agents)
    v2_score_dispersion: float = 0.0

    # Agreement
    regime_match: bool = False


# ---------------------------------------------------------------------------
# Summary KPIs (distribution-aware)
# ---------------------------------------------------------------------------

@dataclass
class ShadowKPIs:
    """Aggregated comparison metrics with distribution awareness."""
    total_bars: int = 0
    symbol: str = ""  # source symbol for multi-symbol runs

    # v1 metrics
    v1_cash_pct: float = 0.0
    v1_signals_total: int = 0
    v1_fills_total: int = 0
    v1_regimes: dict[str, int] = field(default_factory=dict)

    # v2 directive distribution
    v2_cash_pct: float = 0.0
    v2_scale_down_pct: float = 0.0
    v2_full_pct: float = 0.0
    v2_regimes: dict[str, int] = field(default_factory=dict)

    # v2 confidence distribution (not just mean)
    v2_avg_confidence: float = 0.0
    v2_confidence_p10: float = 0.0
    v2_confidence_p50: float = 0.0
    v2_confidence_p90: float = 0.0
    v2_confidence_std: float = 0.0

    # v2 composite score distribution
    v2_avg_composite: float = 0.0
    v2_composite_p10: float = 0.0
    v2_composite_p90: float = 0.0

    # Streak metrics (within window, not across windows)
    v2_scale_down_streak_max: int = 0
    v2_scale_down_streak_avg: float = 0.0
    v2_cash_streak_max: int = 0

    # Stability
    v2_directive_transitions: int = 0  # how often directive changes
    v2_conflict_frequency: float = 0.0  # % bars where agent score dispersion > 0.5

    # Drawdown response latency
    v2_drawdown_response_bars: int = -1  # bars from first negative composite to CASH (-1 = never)

    # Agreement
    regime_agreement_pct: float = 0.0
    regime_disagreements: list[str] = field(default_factory=list)


def _percentile(values: list[float], p: float) -> float:
    """Compute the p-th percentile of a sorted list of values."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * p
    f = int(k)
    c = f + 1
    if c >= len(sorted_v):
        return sorted_v[-1]
    d = k - f
    return sorted_v[f] + d * (sorted_v[c] - sorted_v[f])


def _compute_streaks(directives: list[str], target: str) -> tuple[int, float]:
    """Compute max and average streak length for a given directive.

    Streaks are computed within the full window — not across windows
    in rolling analysis.
    """
    streaks: list[int] = []
    current = 0
    for d in directives:
        if d == target:
            current += 1
        else:
            if current > 0:
                streaks.append(current)
            current = 0
    if current > 0:
        streaks.append(current)
    if not streaks:
        return 0, 0.0
    return max(streaks), statistics.mean(streaks)


def compute_kpis(comparisons: list[BarComparison], symbol: str = "") -> ShadowKPIs:
    """Aggregate per-bar comparisons into summary KPIs."""
    kpis = ShadowKPIs(total_bars=len(comparisons), symbol=symbol)
    if not comparisons:
        return kpis

    # --- v1 metrics ---
    v1_cash = 0
    v1_signals = 0
    v1_fills = 0
    regime_matches = 0
    disagreements = []

    # --- v2 distribution collections ---
    v2_confidences: list[float] = []
    v2_composites: list[float] = []
    v2_directives: list[str] = []
    v2_score_dispersions: list[float] = []

    # --- v2 directive counts ---
    v2_cash = 0
    v2_scale = 0
    v2_full = 0

    for c in comparisons:
        # v1 allocations
        all_zero = all(w == 0.0 for w in c.v1_allocations.values()) if c.v1_allocations else True
        if all_zero:
            v1_cash += 1
        v1_signals += c.v1_signals
        v1_fills += c.v1_fills

        # v1 regimes
        r = c.v1_regime or "unknown"
        kpis.v1_regimes[r] = kpis.v1_regimes.get(r, 0) + 1

        # v2 directive distribution
        directive = c.v2_risk_directive
        v2_directives.append(directive)
        if directive == "CASH":
            v2_cash += 1
        elif directive == "SCALE_DOWN":
            v2_scale += 1
        elif directive == "FULL":
            v2_full += 1

        # v2 confidence + composite distributions
        v2_confidences.append(c.v2_confidence)
        v2_composites.append(c.v2_composite_score)
        v2_score_dispersions.append(c.v2_score_dispersion)

        # v2 regimes
        r2 = c.v2_regime or "unknown"
        kpis.v2_regimes[r2] = kpis.v2_regimes.get(r2, 0) + 1

        # Regime agreement
        if c.v1_regime == c.v2_regime:
            regime_matches += 1
        else:
            disagreements.append(
                f"bar {c.bar_idx} ({c.bar_ts}): v1={c.v1_regime} v2={c.v2_regime}"
            )

    n = kpis.total_bars

    # --- v1 summary ---
    kpis.v1_cash_pct = v1_cash / n
    kpis.v1_signals_total = v1_signals
    kpis.v1_fills_total = v1_fills

    # --- v2 directive summary ---
    kpis.v2_cash_pct = v2_cash / n
    kpis.v2_scale_down_pct = v2_scale / n
    kpis.v2_full_pct = v2_full / n

    # --- v2 confidence distribution ---
    kpis.v2_avg_confidence = statistics.mean(v2_confidences)
    kpis.v2_confidence_p10 = _percentile(v2_confidences, 0.1)
    kpis.v2_confidence_p50 = _percentile(v2_confidences, 0.5)
    kpis.v2_confidence_p90 = _percentile(v2_confidences, 0.9)
    kpis.v2_confidence_std = statistics.stdev(v2_confidences) if len(v2_confidences) > 1 else 0.0

    # --- v2 composite distribution ---
    kpis.v2_avg_composite = statistics.mean(v2_composites)
    kpis.v2_composite_p10 = _percentile(v2_composites, 0.1)
    kpis.v2_composite_p90 = _percentile(v2_composites, 0.9)

    # --- Streak metrics (within this window) ---
    sd_max, sd_avg = _compute_streaks(v2_directives, "SCALE_DOWN")
    kpis.v2_scale_down_streak_max = sd_max
    kpis.v2_scale_down_streak_avg = sd_avg
    cash_max, _ = _compute_streaks(v2_directives, "CASH")
    kpis.v2_cash_streak_max = cash_max

    # --- Directive transitions ---
    transitions = 0
    for i in range(1, len(v2_directives)):
        if v2_directives[i] != v2_directives[i - 1]:
            transitions += 1
    kpis.v2_directive_transitions = transitions

    # --- Conflict frequency (score dispersion > 0.5) ---
    conflict_count = sum(1 for d in v2_score_dispersions if d > 0.5)
    kpis.v2_conflict_frequency = conflict_count / n

    # --- Drawdown response latency ---
    # Find first bar with negative composite score, then find next CASH bar
    first_neg_idx = -1
    for i, c in enumerate(comparisons):
        if c.v2_composite_score < 0:
            first_neg_idx = i
            break
    if first_neg_idx >= 0:
        for i in range(first_neg_idx, len(comparisons)):
            if comparisons[i].v2_risk_directive == "CASH":
                kpis.v2_drawdown_response_bars = i - first_neg_idx
                break

    # --- Regime agreement ---
    kpis.regime_agreement_pct = regime_matches / n
    kpis.regime_disagreements = disagreements[:20]

    return kpis


# ---------------------------------------------------------------------------
# Shadow runner
# ---------------------------------------------------------------------------

class ShadowRunner:
    """Runs v1 (execution) + v2 (observation) on the same bars."""

    def __init__(self, config_path: str = "config/engine.yaml") -> None:
        with open(config_path) as f:
            self._config = yaml.safe_load(f)

    def run_single(self, csv_path: str) -> tuple[ShadowKPIs, list[BarComparison]]:
        """Execute shadow comparison for one CSV. Returns (KPIs, per-bar comparisons)."""
        bars = load_csv(csv_path)
        symbol = Path(csv_path).stem.replace("_1h", "").upper()
        logger.info("Loaded %d bars from %s (symbol=%s)", len(bars), csv_path, symbol)

        # --- v1 setup (execution) ---
        policy = Policy(Path(self._config["hermes"]["policy_path"]))
        metrics = MetricsTracker()
        hermes_v1 = HermesAgent(policy, metrics)

        risk_config = self._config["risk"]
        risk_limits = RiskLimits(
            max_leverage=risk_config["max_leverage"],
            max_drawdown_pct=risk_config["max_drawdown_pct"],
            max_allocation_per_strategy_pct=risk_config["max_allocation_per_strategy_pct"],
            max_total_exposure_pct=risk_config["max_total_exposure_pct"],
            kill_switch_drawdown_pct=risk_config["kill_switch_drawdown_pct"],
            cooldown_bars_after_kill=risk_config["cooldown_bars_after_kill"],
        )
        risk_layer = RiskLayer(limits=risk_limits)

        broker_config = self._config["broker"]
        broker = MockBroker(
            initial_capital=broker_config["initial_capital"],
            slippage_bps=broker_config["slippage_bps"],
            commission_bps=broker_config["commission_bps"],
        )

        regime_detector = RegimeDetector()

        strategies = [
            SMACrossoverStrategy(),
            RSIMeanReversionStrategy(),
        ]

        engine = TradingEngine(
            feed=CsvMarketDataAdapter(csv_path),
            strategies=strategies,
            hermes=hermes_v1,
            risk_layer=risk_layer,
            broker=broker,
            regime_detector=regime_detector,
            event_bus=EventBus(),
            quantity_per_signal=self._config["engine"]["quantity_per_signal"],
        )

        # --- v2 setup (observation only) ---
        registry = AgentRegistry()
        registry.register(IchimokuAgent())
        registry.register(VolatilityAgent())
        registry.register(AMTAgent())
        registry.register(WyckoffAgent())

        v2_coordinator = HermesCoordinator(
            registry=registry,
            scoring=ScoringEngine(),
            conflict=ConflictResolver(),
            sizing=PositionSizer(),
        )

        # --- Run v1 engine (execution) ---
        logger.info("Running v1 engine for %s...", symbol)
        report = engine.run()
        logger.info(
            "v1 complete: %d bars, %d signals, %d fills",
            report.bars_processed, report.total_signals, report.total_fills,
        )

        # --- Run v2 comparison on same bars ---
        logger.info("Running v2 shadow comparison on %d bars...", len(bars))
        comparisons = self._compare_v2_on_bars(bars, v2_coordinator)

        # Enrich comparisons with v1 data
        self._enrich_with_v1(comparisons, report)

        # --- Compute KPIs ---
        kpis = compute_kpis(comparisons, symbol=symbol)

        # Enrich with v1 report data
        kpis.v1_signals_total = report.total_signals
        kpis.v1_fills_total = report.total_fills

        return kpis, comparisons

    def run(
        self,
        csv_paths: list[str] | None = None,
        window: int = 0,
        audit_agents: bool = False,
    ) -> list[ShadowKPIs]:
        """Execute shadow comparison. Returns list of KPIs (one per symbol + optional windows)."""
        if not csv_paths:
            csv_paths = [self._config["engine"]["csv_path"]]

        all_kpis: list[ShadowKPIs] = []
        # Store per-symbol comparisons for audit
        per_symbol_comparisons: list[tuple[str, list[BarComparison]]] = []

        for csv_path in csv_paths:
            kpis, comparisons = self.run_single(csv_path)
            all_kpis.append(kpis)
            symbol = kpis.symbol
            per_symbol_comparisons.append((symbol, comparisons))

            # --- Rolling window analysis ---
            if window > 0 and len(comparisons) >= window:
                window_kpis = self._compute_rolling_windows(comparisons, window, kpis.symbol)
                all_kpis.extend(window_kpis)

            # --- Log results ---
            self._log_results(kpis, comparisons, csv_path)

        # --- Aggregate KPIs for multi-symbol ---
        if len(csv_paths) > 1:
            aggregate = self._aggregate_kpis(all_kpis[:len(csv_paths)])
            all_kpis.append(aggregate)
            self._log_aggregate(aggregate)

        # --- Print summary ---
        self._print_summary(all_kpis)

        # --- Agent audit (if requested) ---
        if audit_agents:
            for symbol, comparisons in per_symbol_comparisons:
                self._run_agent_audit(comparisons, symbol)

        return all_kpis

    def _run_agent_audit(
        self,
        comparisons: list[BarComparison],
        symbol: str,
    ) -> None:
        """Run agent contribution audit on pre-computed comparisons."""
        analyzer = AgentAuditAnalyzer(comparisons, symbol=symbol)
        results = analyzer.analyze()
        analyzer.print_report()

        # Save audit JSON
        log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        audit_path = log_dir / f"agent_audit_{symbol}_{ts}.json"
        with open(audit_path, "w") as f:
            json.dump(results, f, indent=2)
        logger.info("Agent audit log: %s", audit_path)

    def _compare_v2_on_bars(
        self,
        bars: list[Bar],
        coordinator: HermesCoordinator,
    ) -> list[BarComparison]:
        """Run v2 coordinator on each bar (observation only, no execution)."""
        comparisons: list[BarComparison] = []
        previous: PreviousState | None = None
        warmup = 52

        for i, bar in enumerate(bars):
            history = bars[max(0, i - warmup):i + 1]

            ms = MarketState(
                bars=history,
                regime=Regime.RANGING,
                regime_confidence=0.5,
                volatility=None,
                timestamp=bar.timestamp,
            )

            equity = self._config["broker"]["initial_capital"]
            acc = AccountState(
                equity=equity,
                peak_equity=equity,
                current_drawdown=0.0,
                max_risk_per_trade=0.01,
                max_portfolio_risk=0.05,
            )

            decision = coordinator.run_cycle(ms, acc, previous)

            # Compute score dispersion
            scores = list(decision.agent_scores.values())
            dispersion = max(scores) - min(scores) if len(scores) > 1 else 0.0

            comp = BarComparison(
                bar_ts=bar.timestamp.isoformat(),
                bar_idx=i,
                v2_regime=decision.regime,
                v2_risk_directive=decision.risk_directive,
                v2_composite_score=decision.composite_score,
                v2_confidence=decision.confidence,
                v2_allowed_family=decision.allowed_strategy_family,
                v2_agent_scores=dict(decision.agent_scores),
                v2_agent_confidences=dict(decision.agent_confidences),
                v2_score_dispersion=dispersion,
            )

            comparisons.append(comp)

            previous = PreviousState(
                composite_score=decision.composite_score,
                regime=decision.regime,
                risk_directive=decision.risk_directive,
                allowed_strategy_family=decision.allowed_strategy_family,
            )

        return comparisons

    def _enrich_with_v1(
        self,
        comparisons: list[BarComparison],
        report,
    ) -> None:
        """Enrich comparisons with v1 allocation data from engine report."""
        # Map allocation log to bar indices if available
        if hasattr(report, 'allocation_log') and report.allocation_log:
            for entry in report.allocation_log:
                bar_idx = entry.get('bar_idx', -1)
                if 0 <= bar_idx < len(comparisons):
                    allocs = entry.get('allocations', {})
                    comparisons[bar_idx].v1_allocations = allocs
                    comparisons[bar_idx].v1_regime = entry.get('regime')
                    comparisons[bar_idx].v1_signals = entry.get('signals', 0)
                    comparisons[bar_idx].v1_fills = entry.get('fills', 0)

    def _compute_rolling_windows(
        self,
        comparisons: list[BarComparison],
        window_size: int,
        symbol: str,
    ) -> list[ShadowKPIs]:
        """Compute KPIs for rolling windows.

        Note: Streak metrics are computed within each window, not across windows.
        This means a streak of 10 SCALE_DOWN bars in window 1 does not carry
        into window 2 — each window is independent.
        """
        window_kpis: list[ShadowKPIs] = []
        step = max(1, window_size // 2)  # 50% overlap

        for start in range(0, len(comparisons) - window_size + 1, step):
            window_comps = comparisons[start:start + window_size]
            kpis = compute_kpis(window_comps, symbol=f"{symbol}:w{start}-{start + window_size}")
            window_kpis.append(kpis)

        return window_kpis

    def _aggregate_kpis(self, per_symbol_kpis: list[ShadowKPIs]) -> ShadowKPIs:
        """Aggregate KPIs across multiple symbols."""
        if not per_symbol_kpis:
            return ShadowKPIs(symbol="AGGREGATE")

        total_bars = sum(k.total_bars for k in per_symbol_kpis)
        if total_bars == 0:
            return ShadowKPIs(symbol="AGGREGATE")

        agg = ShadowKPIs(total_bars=total_bars, symbol="AGGREGATE")

        # Weighted averages
        for k in per_symbol_kpis:
            w = k.total_bars / total_bars
            agg.v2_avg_confidence += k.v2_avg_confidence * w
            agg.v2_confidence_std += k.v2_confidence_std * w
            agg.v2_cash_pct += k.v2_cash_pct * w
            agg.v2_scale_down_pct += k.v2_scale_down_pct * w
            agg.v2_full_pct += k.v2_full_pct * w
            agg.v2_conflict_frequency += k.v2_conflict_frequency * w
            agg.v1_cash_pct += k.v1_cash_pct * w
            agg.v1_signals_total += k.v1_signals_total
            agg.v1_fills_total += k.v1_fills_total

        return agg

    def _log_results(
        self,
        kpis: ShadowKPIs,
        comparisons: list[BarComparison],
        csv_path: str,
    ) -> None:
        """Log comparison results as JSON + human-readable summary."""
        log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        symbol = kpis.symbol or "unknown"

        # --- JSON log (per-bar) ---
        json_path = log_dir / f"shadow_comparison_{symbol}_{ts}.json"
        records = []
        for c in comparisons:
            records.append({
                "bar_ts": c.bar_ts,
                "bar_idx": c.bar_idx,
                "v1_regime": c.v1_regime,
                "v1_allocations": c.v1_allocations,
                "v1_risk_posture": c.v1_risk_posture,
                "v1_signals": c.v1_signals,
                "v1_fills": c.v1_fills,
                "v2_regime": c.v2_regime,
                "v2_risk_directive": c.v2_risk_directive,
                "v2_composite_score": c.v2_composite_score,
                "v2_confidence": c.v2_confidence,
                "v2_allowed_family": c.v2_allowed_family,
                "v2_agent_scores": c.v2_agent_scores,
                "v2_agent_confidences": c.v2_agent_confidences,
                "v2_score_dispersion": c.v2_score_dispersion,
            })

        with open(json_path, "w") as f:
            json.dump(records, f, indent=2)
        logger.info("Per-bar comparison log: %s", json_path)

        # --- Summary KPIs JSON ---
        kpi_path = log_dir / f"shadow_kpis_{symbol}_{ts}.json"
        kpi_data = _kpi_to_dict(kpis)
        with open(kpi_path, "w") as f:
            json.dump(kpi_data, f, indent=2)
        logger.info("Summary KPIs: %s", kpi_path)

    def _log_aggregate(self, agg: ShadowKPIs) -> None:
        """Log aggregate KPIs."""
        log_dir = Path("logs")
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        kpi_path = log_dir / f"shadow_kpis_AGGREGATE_{ts}.json"
        kpi_data = _kpi_to_dict(agg)
        with open(kpi_path, "w") as f:
            json.dump(kpi_data, f, indent=2)
        logger.info("Aggregate KPIs: %s", kpi_path)

    def _print_summary(self, all_kpis: list[ShadowKPIs]) -> None:
        """Print human-readable summary for all KPI sets."""
        print("\n" + "=" * 70)
        print("SHADOW COMPARISON: Hermes v1 vs v2")
        print("=" * 70)

        for kpis in all_kpis:
            if kpis.symbol == "AGGREGATE":
                print("\n" + "-" * 70)
                print("AGGREGATE (all symbols)")
                print("-" * 70)
            elif ":w" in kpis.symbol:
                # Rolling window — compact output
                continue  # skip printing individual windows
            else:
                print(f"\n--- {kpis.symbol} ({kpis.total_bars} bars) ---")

            print(f"  v1 CASH:          {kpis.v1_cash_pct:.1%}  (signals={kpis.v1_signals_total}, fills={kpis.v1_fills_total})")
            print(f"  v2 FULL:          {kpis.v2_full_pct:.1%}")
            print(f"  v2 SCALE_DOWN:    {kpis.v2_scale_down_pct:.1%}")
            print(f"  v2 CASH:          {kpis.v2_cash_pct:.1%}")
            print(f"  v2 Confidence:    avg={kpis.v2_avg_confidence:.3f}  p10={kpis.v2_confidence_p10:.3f}  p50={kpis.v2_confidence_p50:.3f}  p90={kpis.v2_confidence_p90:.3f}  std={kpis.v2_confidence_std:.3f}")
            print(f"  v2 Composite:     avg={kpis.v2_avg_composite:.3f}  p10={kpis.v2_composite_p10:.3f}  p90={kpis.v2_composite_p90:.3f}")
            print(f"  v2 Regimes:       {kpis.v2_regimes}")
            print(f"  Streaks:          SCALE_DOWN max={kpis.v2_scale_down_streak_max} avg={kpis.v2_scale_down_streak_avg:.1f}  CASH max={kpis.v2_cash_streak_max}")
            print(f"  Transitions:      {kpis.v2_directive_transitions}")
            print(f"  Conflict freq:    {kpis.v2_conflict_frequency:.1%}")
            resp = f"{kpis.v2_drawdown_response_bars} bars" if kpis.v2_drawdown_response_bars >= 0 else "never"
            print(f"  Drawdown resp:    {resp}")
            print(f"  Regime agreement: {kpis.regime_agreement_pct:.1%}")

        # Print rolling window summary if present
        windows = [k for k in all_kpis if ":w" in k.symbol]
        if windows:
            print(f"\n--- Rolling Windows ({len(windows)} windows) ---")
            for w in windows:
                short = w.symbol.split(":")[1]
                print(f"  {short}: conf_avg={w.v2_avg_confidence:.3f}  FULL={w.v2_full_pct:.0%}  SCALE={w.v2_scale_down_pct:.0%}  CASH={w.v2_cash_pct:.0%}  transitions={w.v2_directive_transitions}")

        print("=" * 70)


class AgentAuditAnalyzer:
    """Analyzes per-agent contributions from shadow comparison data.

    Measures:
    - Per-agent score/confidence distributions
    - Conflict attribution (which agents drive conflicts)
    - Alignment analysis (aligned vs opposite to composite)
    - Confidence suppression (who prevents confidence from rising)
    - Pairwise agent disagreement frequency

    This is measurement only — no logic, thresholds, or behaviors are changed.
    """

    def __init__(self, comparisons: list[BarComparison], symbol: str = "") -> None:
        self._comparisons = comparisons
        self._symbol = symbol
        self._agent_names: list[str] = []
        self._conflict_bars: list[BarComparison] = []
        self._results: dict = {}

    def analyze(self) -> dict:
        """Run all audit analyses and return structured results."""
        if not self._comparisons:
            return {"symbol": self._symbol, "total_bars": 0, "agents": {}}

        # Discover agent names from first comparison with data
        for c in self._comparisons:
            if c.v2_agent_scores:
                self._agent_names = sorted(c.v2_agent_scores.keys())
                break

        if not self._agent_names:
            return {"symbol": self._symbol, "total_bars": len(self._comparisons), "agents": {}}

        # Identify conflict bars (dispersion > 0.5)
        self._conflict_bars = [
            c for c in self._comparisons if c.v2_score_dispersion > 0.5
        ]

        agent_metrics = {}
        for name in self._agent_names:
            agent_metrics[name] = self._analyze_agent(name)

        # Pairwise disagreement
        pairwise = self._pairwise_disagreement()

        # Findings
        findings = self._generate_findings(agent_metrics, pairwise)

        self._results = {
            "symbol": self._symbol,
            "total_bars": len(self._comparisons),
            "total_conflict_bars": len(self._conflict_bars),
            "conflict_pct": len(self._conflict_bars) / len(self._comparisons) if self._comparisons else 0.0,
            "agents": agent_metrics,
            "pairwise_disagreement": pairwise,
            "findings": findings,
        }

        return self._results

    def _get_agent_scores(self, name: str) -> list[float]:
        """Extract all scores for an agent across all bars."""
        return [
            c.v2_agent_scores[name]
            for c in self._comparisons
            if name in c.v2_agent_scores
        ]

    def _get_agent_confidences(self, name: str) -> list[float]:
        """Extract all confidences for an agent across all bars."""
        return [
            c.v2_agent_confidences[name]
            for c in self._comparisons
            if name in c.v2_agent_confidences
        ]

    def _analyze_agent(self, name: str) -> dict:
        """Compute all metrics for a single agent."""
        scores = self._get_agent_scores(name)
        confidences = self._get_agent_confidences(name)

        if not scores:
            return {"error": f"No data for agent {name}"}

        # --- 3.1 Distribution metrics ---
        score_mean = statistics.mean(scores)
        score_std = statistics.stdev(scores) if len(scores) > 1 else 0.0
        conf_mean = statistics.mean(confidences)
        conf_p10 = _percentile(confidences, 0.1)
        conf_p50 = _percentile(confidences, 0.5)
        conf_p90 = _percentile(confidences, 0.9)
        conf_below_03_pct = sum(1 for c in confidences if c < 0.3) / len(confidences)

        # --- 3.2 Conflict attribution ---
        conflict_participation_pct = 0.0
        conflict_max_outlier_pct = 0.0

        if self._conflict_bars:
            participating = 0
            max_outlier = 0
            for c in self._conflict_bars:
                if name not in c.v2_agent_scores:
                    continue
                agent_score = c.v2_agent_scores[name]
                # Agent participated if its score sign differs from composite sign
                composite = c.v2_composite_score
                if (agent_score > 0) != (composite > 0) and composite != 0.0:
                    participating += 1
                # Agent is max outlier if |score - composite| is highest
                agent_dist = abs(agent_score - composite)
                all_dists = [
                    abs(c.v2_agent_scores[n] - composite)
                    for n in c.v2_agent_scores
                ]
                if all_dists and agent_dist == max(all_dists):
                    max_outlier += 1

            n_conflict = len(self._conflict_bars)
            conflict_participation_pct = participating / n_conflict
            conflict_max_outlier_pct = max_outlier / n_conflict

        # --- 3.3 Alignment analysis ---
        aligned_count = 0
        opposite_count = 0
        aligned_confidences: list[float] = []
        opposite_confidences: list[float] = []

        for c in self._comparisons:
            if name not in c.v2_agent_scores:
                continue
            agent_score = c.v2_agent_scores[name]
            composite = c.v2_composite_score
            conf = c.v2_agent_confidences.get(name, 0.0)

            if composite == 0.0:
                continue  # skip zero-composite bars

            if (agent_score > 0) == (composite > 0):
                aligned_count += 1
                aligned_confidences.append(conf)
            else:
                opposite_count += 1
                opposite_confidences.append(conf)

        total_directional = aligned_count + opposite_count
        aligned_pct = aligned_count / total_directional if total_directional > 0 else 0.0
        opposite_pct = opposite_count / total_directional if total_directional > 0 else 0.0
        conf_aligned = statistics.mean(aligned_confidences) if aligned_confidences else 0.0
        conf_opposite = statistics.mean(opposite_confidences) if opposite_confidences else 0.0

        # --- 3.4 Confidence suppression ---
        # Correlation with composite confidence
        composite_confidences = [c.v2_confidence for c in self._comparisons]
        correlation = _pearson_correlation(confidences, composite_confidences)

        # Low-confidence attribution: % of low-conf bars where this agent has lowest confidence
        low_conf_bars = [
            c for c in self._comparisons if c.v2_confidence < 0.3
        ]
        low_conf_attribution = 0.0
        if low_conf_bars:
            lowest_count = 0
            for c in low_conf_bars:
                if name not in c.v2_agent_confidences:
                    continue
                agent_conf = c.v2_agent_confidences[name]
                all_confs = list(c.v2_agent_confidences.values())
                if all_confs and agent_conf == min(all_confs):
                    lowest_count += 1
            low_conf_attribution = lowest_count / len(low_conf_bars)

        # --- Conflict-by-regime segmentation ---
        conflict_by_regime: dict[str, dict] = {}
        regime_conflict_counts: dict[str, int] = {}
        regime_total_counts: dict[str, int] = {}

        for c in self._comparisons:
            regime = c.v2_regime or "unknown"
            regime_total_counts[regime] = regime_total_counts.get(regime, 0) + 1
            if c.v2_score_dispersion > 0.5 and name in c.v2_agent_scores:
                regime_conflict_counts[regime] = regime_conflict_counts.get(regime, 0) + 1

        for regime in regime_total_counts:
            total = regime_total_counts[regime]
            conflicts = regime_conflict_counts.get(regime, 0)
            conflict_by_regime[regime] = {
                "total_bars": total,
                "conflict_bars": conflicts,
                "conflict_pct": conflicts / total if total > 0 else 0.0,
            }

        return {
            "score": {
                "mean": round(score_mean, 4),
                "std": round(score_std, 4),
            },
            "confidence": {
                "mean": round(conf_mean, 4),
                "p10": round(conf_p10, 4),
                "p50": round(conf_p50, 4),
                "p90": round(conf_p90, 4),
                "below_03_pct": round(conf_below_03_pct, 4),
            },
            "conflict_attribution": {
                "participation_pct": round(conflict_participation_pct, 4),
                "max_outlier_pct": round(conflict_max_outlier_pct, 4),
            },
            "alignment": {
                "aligned_pct": round(aligned_pct, 4),
                "opposite_pct": round(opposite_pct, 4),
                "confidence_when_aligned": round(conf_aligned, 4),
                "confidence_when_opposite": round(conf_opposite, 4),
            },
            "confidence_suppression": {
                "correlation_with_composite": round(correlation, 4),
                "low_confidence_attribution_pct": round(low_conf_attribution, 4),
            },
            "conflict_by_regime": conflict_by_regime,
        }

    def _pairwise_disagreement(self) -> dict[str, float]:
        """Compute pairwise agent disagreement frequency."""
        pairwise: dict[str, float] = {}
        n = len(self._agent_names)

        for i in range(n):
            for j in range(i + 1, n):
                name_a = self._agent_names[i]
                name_b = self._agent_names[j]
                disagreements = 0
                total = 0

                for c in self._comparisons:
                    if name_a not in c.v2_agent_scores or name_b not in c.v2_agent_scores:
                        continue
                    score_a = c.v2_agent_scores[name_a]
                    score_b = c.v2_agent_scores[name_b]
                    total += 1
                    # Disagree if one is positive and the other negative (or zero)
                    if (score_a > 0) != (score_b > 0) and score_a != 0.0 and score_b != 0.0:
                        disagreements += 1

                key = f"{name_a}_{name_b}"
                pairwise[key] = disagreements / total if total > 0 else 0.0

        return pairwise

    def _generate_findings(
        self, agent_metrics: dict, pairwise: dict[str, float]
    ) -> list[str]:
        """Auto-generate key findings from computed metrics."""
        findings: list[str] = []

        if not agent_metrics:
            return ["No agent data available"]

        # Find highest conflict participant
        max_participation = 0.0
        max_participant = ""
        for name, metrics in agent_metrics.items():
            if "conflict_attribution" in metrics:
                pct = metrics["conflict_attribution"]["participation_pct"]
                if pct > max_participation:
                    max_participation = pct
                    max_participant = name

        if max_participant and max_participation > 0.6:
            findings.append(
                f"{max_participant} is the primary conflict driver "
                f"({max_participation:.0%} participation)"
            )

        # Find lowest confidence agent
        min_conf = 1.0
        min_conf_agent = ""
        for name, metrics in agent_metrics.items():
            if "confidence" in metrics:
                mean_c = metrics["confidence"]["mean"]
                if mean_c < min_conf:
                    min_conf = mean_c
                    min_conf_agent = name

        if min_conf_agent:
            findings.append(
                f"{min_conf_agent} has lowest avg confidence ({min_conf:.3f})"
            )

        # Find most contrarian agent
        max_opposite = 0.0
        most_contrarian = ""
        for name, metrics in agent_metrics.items():
            if "alignment" in metrics:
                opp = metrics["alignment"]["opposite_pct"]
                if opp > max_opposite:
                    max_opposite = opp
                    most_contrarian = name

        if most_contrarian and max_opposite > 0.4:
            findings.append(
                f"{most_contrarian} is structurally contrarian "
                f"({max_opposite:.0%} opposite to composite)"
            )

        # Find highest pairwise disagreement
        max_pw = 0.0
        max_pw_pair = ""
        for pair, freq in pairwise.items():
            if freq > max_pw:
                max_pw = freq
                max_pw_pair = pair

        if max_pw_pair and max_pw > 0.4:
            findings.append(
                f"Highest pairwise disagreement: {max_pw_pair} ({max_pw:.0%})"
            )

        # AMT structural ceiling
        if "AMT" in agent_metrics:
            amt_conf = agent_metrics["AMT"]["confidence"]["mean"]
            findings.append(
                f"AMTAgent confidence capped at 0.5 (mean={amt_conf:.3f}), "
                f"structurally dragging composite confidence below R-02 threshold"
            )

        return findings

    def print_report(self) -> None:
        """Print human-readable audit report."""
        if not self._results:
            self.analyze()

        r = self._results
        print(f"\n{'=' * 70}")
        print(f"AGENT CONTRIBUTION AUDIT: {self._symbol} ({r['total_bars']} bars)")
        print(f"{'=' * 70}")
        print(f"  Conflict bars: {r['total_conflict_bars']} ({r['conflict_pct']:.1%})")

        # --- Agent Distributions ---
        print(f"\n--- Agent Distributions ---")
        print(f"  {'Agent':<14} {'Score avg':>10} {'Score std':>10} {'Conf avg':>10} {'Conf p50':>10} {'Conf<0.3':>10}")
        for name, m in r["agents"].items():
            if "error" in m:
                continue
            s = m["score"]
            c = m["confidence"]
            print(
                f"  {name:<14} {s['mean']:>+10.4f} {s['std']:>10.4f} "
                f"{c['mean']:>10.4f} {c['p50']:>10.4f} {c['below_03_pct']:>9.1%}"
            )

        # --- Conflict Attribution ---
        print(f"\n--- Conflict Attribution ({r['total_conflict_bars']} conflict bars) ---")
        print(f"  {'Agent':<14} {'Participation%':>15} {'Max Outlier%':>14}")
        for name, m in r["agents"].items():
            if "error" in m or "conflict_attribution" not in m:
                continue
            ca = m["conflict_attribution"]
            print(
                f"  {name:<14} {ca['participation_pct']:>14.1%} "
                f"{ca['max_outlier_pct']:>13.1%}"
            )

        # --- Alignment ---
        print(f"\n--- Alignment ---")
        print(
            f"  {'Agent':<14} {'Aligned%':>10} {'Opposite%':>10} "
            f"{'Conf(aligned)':>14} {'Conf(opp)':>10}"
        )
        for name, m in r["agents"].items():
            if "error" in m or "alignment" not in m:
                continue
            a = m["alignment"]
            print(
                f"  {name:<14} {a['aligned_pct']:>9.1%} {a['opposite_pct']:>9.1%} "
                f"{a['confidence_when_aligned']:>13.3f} {a['confidence_when_opposite']:>9.3f}"
            )

        # --- Confidence Suppression ---
        print(f"\n--- Confidence Suppression ---")
        print(
            f"  {'Agent':<14} {'Correlation(w/comp)':>20} {'LowConf Attribution':>20}"
        )
        for name, m in r["agents"].items():
            if "error" in m or "confidence_suppression" not in m:
                continue
            cs = m["confidence_suppression"]
            print(
                f"  {name:<14} {cs['correlation_with_composite']:>19.3f} "
                f"{cs['low_confidence_attribution_pct']:>19.1%}"
            )

        # --- Conflict by Regime ---
        print(f"\n--- Conflict by Regime ---")
        all_regimes: set[str] = set()
        for m in r["agents"].values():
            if "conflict_by_regime" in m:
                all_regimes.update(m["conflict_by_regime"].keys())

        for regime in sorted(all_regimes):
            print(f"  Regime: {regime}")
            for name, m in r["agents"].items():
                if "conflict_by_regime" not in m:
                    continue
                if regime in m["conflict_by_regime"]:
                    rb = m["conflict_by_regime"][regime]
                    print(
                        f"    {name:<14} bars={rb['total_bars']:<5} "
                        f"conflicts={rb['conflict_bars']:<5} "
                        f"conflict_pct={rb['conflict_pct']:.1%}"
                    )

        # --- Pairwise Disagreement ---
        print(f"\n--- Pairwise Disagreement ---")
        for pair, freq in sorted(r["pairwise_disagreement"].items(), key=lambda x: -x[1]):
            print(f"  {pair:<35} {freq:.1%}")

        # --- Findings ---
        print(f"\n--- Key Findings ---")
        for i, finding in enumerate(r["findings"], 1):
            print(f"  {i}. {finding}")

        print(f"{'=' * 70}")


def _pearson_correlation(x: list[float], y: list[float]) -> float:
    """Compute Pearson correlation between two lists."""
    n = min(len(x), len(y))
    if n < 2:
        return 0.0

    x_slice = x[:n]
    y_slice = y[:n]

    mean_x = statistics.mean(x_slice)
    mean_y = statistics.mean(y_slice)

    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x_slice, y_slice))
    std_x = statistics.stdev(x_slice)
    std_y = statistics.stdev(y_slice)

    if std_x == 0.0 or std_y == 0.0:
        return 0.0

    return cov / ((n - 1) * std_x * std_y)


def _kpi_to_dict(kpis: ShadowKPIs) -> dict:
    """Convert KPIs to JSON-serializable dict."""
    return {
        "symbol": kpis.symbol,
        "total_bars": kpis.total_bars,
        "v1": {
            "cash_pct": round(kpis.v1_cash_pct, 4),
            "signals_total": kpis.v1_signals_total,
            "fills_total": kpis.v1_fills_total,
            "regimes": kpis.v1_regimes,
        },
        "v2": {
            "cash_pct": round(kpis.v2_cash_pct, 4),
            "scale_down_pct": round(kpis.v2_scale_down_pct, 4),
            "full_pct": round(kpis.v2_full_pct, 4),
            "regimes": kpis.v2_regimes,
            "confidence": {
                "avg": round(kpis.v2_avg_confidence, 4),
                "p10": round(kpis.v2_confidence_p10, 4),
                "p50": round(kpis.v2_confidence_p50, 4),
                "p90": round(kpis.v2_confidence_p90, 4),
                "std": round(kpis.v2_confidence_std, 4),
            },
            "composite": {
                "avg": round(kpis.v2_avg_composite, 4),
                "p10": round(kpis.v2_composite_p10, 4),
                "p90": round(kpis.v2_composite_p90, 4),
            },
            "streaks": {
                "scale_down_max": kpis.v2_scale_down_streak_max,
                "scale_down_avg": round(kpis.v2_scale_down_streak_avg, 2),
                "cash_max": kpis.v2_cash_streak_max,
            },
            "directive_transitions": kpis.v2_directive_transitions,
            "conflict_frequency": round(kpis.v2_conflict_frequency, 4),
            "drawdown_response_bars": kpis.v2_drawdown_response_bars,
        },
        "agreement": {
            "regime_agreement_pct": round(kpis.regime_agreement_pct, 4),
            "regime_disagreements": kpis.regime_disagreements,
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    import argparse
    parser = argparse.ArgumentParser(description="Hermes v1 vs v2 shadow comparison")
    parser.add_argument("--config", default="config/engine.yaml", help="Config path")
    parser.add_argument("--csv", nargs="+", default=None, help="CSV path(s) — supports multiple")
    parser.add_argument("--window", type=int, default=0, help="Rolling window size (0 = disabled)")
    parser.add_argument("--audit-agents", action="store_true", help="Run agent contribution audit after comparison")
    args = parser.parse_args()

    runner = ShadowRunner(config_path=args.config)
    all_kpis = runner.run(csv_paths=args.csv, window=args.window, audit_agents=args.audit_agents)

    # Exit code: 0 if any KPI set has confidence avg > 0 (v2 is producing output)
    if any(k.v2_avg_confidence > 0 for k in all_kpis):
        sys.exit(0)
    else:
        logger.warning("v2 produced no confidence across all runs")
        sys.exit(1)


if __name__ == "__main__":
    main()