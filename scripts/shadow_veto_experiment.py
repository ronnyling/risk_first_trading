"""Shadow Experiment 8.4: Volatility-Only Veto Semantics

Tests whether restricting R-01 veto authority to Volatility alone
(until now, ANY agent disagreement triggers R-01) allows FULL to fire.

Baseline: Standard HCR-001 (any agent dispersion > 0.60 → R-01 CASH)
Experiment: Volatility-only veto (R-01 fires only when Volatility
  opposes the unmodified composite direction AND abs(vol_score) > VETO_THRESHOLD)

Composite direction refers to the unmodified composite score calculated
from ALL agents (AMT, Ichimoku, Volatility, Wyckoff) via ScoringEngine.

VETO_THRESHOLD = 0.3 is an experimental probe, NOT a recommendation.
This script runs exactly one threshold to differentiate noise from
meaningful volatility disagreement. No parameter sweep.

Shadow-only — no execution, no promotion, no threshold changes.
No production code modified.

Usage:
    python scripts/shadow_veto_experiment.py
    python scripts/shadow_veto_experiment.py --csv data/shadow/spy_1h_50d.csv
    python scripts/shadow_veto_experiment.py --veto-threshold 0.3
"""

from __future__ import annotations

import json
import logging
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.types import Bar, Regime
from src.market.data_loader import load_csv
from src.hermes.agents.base import MarketState
from src.hermes.agents.stub_agents import (
    IchimokuAgent, VolatilityAgent, AMTAgent, WyckoffAgent,
)
from src.hermes.coordinator import (
    AccountState, HermesCoordinator, PreviousState,
)
from src.hermes.decision import HermesDecision
from src.hermes.registry import AgentRegistry
from src.hermes.scoring import ScoringEngine
from src.hermes.conflict import (
    ConflictResolver, ConflictInput,
    DISAGREEMENT_THRESHOLD, FLIP_RISK_THRESHOLD,
    _classify_regime, _map_regime_to_family,
)
from src.hermes.sizing import PositionSizer, SizingInput

logger = logging.getLogger("shadow_veto_experiment")


# ---------------------------------------------------------------------------
# Experimental coordinator: Volatility-only R-01 veto
# ---------------------------------------------------------------------------

class VetoExperimentalCoordinator(HermesCoordinator):
    """Coordinator with Volatility-only R-01 veto semantics.

    Modification (shadow-only):
      R-01 (score_dispersion > 0.60 → CASH) is replaced with a
      Volatility-only veto that fires when:
        1. Volatility score opposes the unmodified composite direction
           (composite score from ALL agents via ScoringEngine)
        2. abs(volatility_score) > VETO_THRESHOLD

    If Volatility does not oppose composite, R-01 never fires regardless
    of how high dispersion is. This tests whether Volatility alone can
    serve as an intelligent integrity gate.

    R-02 (low confidence), R-03 (score jump), R-04 (normal) remain enforced.
    """

    VETO_THRESHOLD: float = 0.3  # experimental probe, NOT a recommendation

    def run_cycle(
        self,
        market_state: MarketState,
        account_state: AccountState,
        previous: PreviousState | None = None,
    ) -> HermesDecision:
        """Run one v2 evaluation cycle with volatility-only veto logic."""
        # 1. Collect agent outputs (identical to baseline)
        outputs = {}
        for output in self._registry.run_all(market_state):
            outputs[output.agent_name] = output

        agent_scores = {name: out.score for name, out in outputs.items()}
        agent_confidences = {name: out.confidence for name, out in outputs.items()}

        # 2. Scoring (identical to baseline — uses ALL agents)
        scoring_result = self._scoring.compute(
            scores=list(agent_scores.values()),
            confidences=list(agent_confidences.values()),
        )

        # 3. Experimental conflict resolution
        prev = PreviousState(
            composite_score=0.0, regime="ranging",
            risk_directive="FULL", allowed_strategy_family=None,
        ) if previous is None else previous

        conflict_input = ConflictInput(
            composite_score=scoring_result.composite_score,
            total_confidence=scoring_result.total_confidence,
            score_dispersion=scoring_result.score_dispersion,
            previous_composite_score=prev.composite_score,
            previous_regime=prev.regime,
            previous_risk_directive=prev.risk_directive,
            previous_allowed_family=prev.allowed_strategy_family,
        )

        conflict_output = self._experimental_resolve(conflict_input, agent_scores)

        # 4. Position sizing (identical to baseline)
        sizing_input = SizingInput(
            confidence=scoring_result.total_confidence,
            risk_directive=conflict_output.risk_directive,
            current_drawdown=account_state.current_drawdown,
            max_risk_per_trade=account_state.max_risk_per_trade,
            max_portfolio_risk=account_state.max_portfolio_risk,
        )
        sizing_result = self._sizing.compute(sizing_input)

        # 5. Build decision (identical to baseline)
        return HermesDecision(
            regime=conflict_output.regime,
            composite_score=scoring_result.composite_score,
            confidence=scoring_result.total_confidence,
            risk_directive=conflict_output.risk_directive,
            allowed_strategy_family=conflict_output.allowed_strategy_family,
            per_trade_risk=sizing_result.per_trade_risk,
            portfolio_risk=sizing_result.portfolio_risk,
            timestamp=market_state.timestamp,
            agent_scores=agent_scores,
            agent_confidences=agent_confidences,
            reasoning=conflict_output.reasoning,
        )

    def _experimental_resolve(
        self,
        inputs: ConflictInput,
        agent_scores: dict[str, float],
    ) -> "ConflictOutput":
        """Apply HCR-001 with Volatility-only R-01 veto.

        Composite direction = unmodified composite score from ALL agents.

        R-01 (VOLATILITY-ONLY VETO):
          Fires when Volatility opposes composite direction AND
          abs(volatility_score) > VETO_THRESHOLD.
          Standard dispersion-based R-01 is DISABLED.
        R-02 (confidence < 0.50 → SCALE_DOWN): ENFORCED
        R-03 (score jump >= 0.80 → SCALE_DOWN): ENFORCED
        R-04 (normal → FULL): ENFORCED
        """
        from src.hermes.conflict import ConflictOutput

        vol_score = agent_scores.get("Volatility", 0.0)
        composite = inputs.composite_score  # from ALL agents

        # R-01: Volatility-Only Veto
        # Veto fires when Volatility opposes composite direction
        # AND its magnitude exceeds the threshold
        vol_opposes_composite = (vol_score * composite) < 0
        vol_magnitude_strong = abs(vol_score) > self.VETO_THRESHOLD

        veto_fired = vol_opposes_composite and vol_magnitude_strong

        if veto_fired:
            return ConflictOutput(
                regime="INDETERMINATE",
                risk_directive="CASH",
                allowed_strategy_family=None,
                reasoning=(
                    f"R-01-VOL: volatility_score={vol_score:.3f} opposes "
                    f"composite={composite:.3f} (|{vol_score:.3f}| > "
                    f"{self.VETO_THRESHOLD}). Volatility veto."
                ),
                resolution_path="R-01",
            )

        # R-02: Low Confidence — ENFORCED
        if inputs.total_confidence < 0.50:
            return ConflictOutput(
                regime=inputs.previous_regime,
                risk_directive="SCALE_DOWN",
                allowed_strategy_family=inputs.previous_allowed_family,
                reasoning=(
                    f"CR-02: total_confidence={inputs.total_confidence:.3f} "
                    f"< 0.50. Signals untrustworthy."
                ),
                resolution_path="R-02",
            )

        # R-03: Unstable Transitions — ENFORCED
        score_jump = abs(
            inputs.composite_score - inputs.previous_composite_score
        )
        if score_jump >= FLIP_RISK_THRESHOLD:
            return ConflictOutput(
                regime=inputs.previous_regime,
                risk_directive="SCALE_DOWN",
                allowed_strategy_family=inputs.previous_allowed_family,
                reasoning=(
                    f"CR-03: score_jump={score_jump:.3f} "
                    f">= {FLIP_RISK_THRESHOLD}. Regime flip risk."
                ),
                resolution_path="R-03",
            )

        # R-04: Normal Operation
        regime = _classify_regime(inputs.composite_score)
        family = _map_regime_to_family(regime)

        return ConflictOutput(
            regime=regime,
            risk_directive="FULL",
            allowed_strategy_family=family,
            reasoning=(
                f"R-04: Normal. composite={inputs.composite_score:.3f}, "
                f"regime={regime}, family={family}, "
                f"vol_score={vol_score:.3f} (no veto)"
            ),
            resolution_path="R-04",
        )


# ---------------------------------------------------------------------------
# Experiment runner
# ---------------------------------------------------------------------------

@dataclass
class VetoExperimentResult:
    """Result from comparing baseline vs volatility-only veto on one symbol."""
    symbol: str
    total_bars: int
    baseline: dict
    experimental: dict
    full_appeared_in_experiment: bool
    full_appeared_in_baseline: bool
    veto_count: int
    directive_shifts: dict[str, int]
    baseline_r01_count: int
    experiment_veto_count_detail: dict  # breakdown of veto vs no-veto


def run_veto_experiment(
    csv_path: str,
    config_path: str = "config/engine.yaml",
    veto_threshold: float = 0.3,
) -> VetoExperimentResult:
    """Run baseline vs volatility-only veto on the same bars."""
    with open(config_path) as f:
        config = yaml.safe_load(f)

    bars = load_csv(csv_path)
    symbol = Path(csv_path).stem.replace("_1h", "").upper()
    logger.info("Loaded %d bars from %s (symbol=%s)", len(bars), csv_path, symbol)

    equity = config["broker"]["initial_capital"]

    # --- Shared setup ---
    def make_coordinator():
        registry = AgentRegistry()
        registry.register(IchimokuAgent())
        registry.register(VolatilityAgent())
        registry.register(AMTAgent())
        registry.register(WyckoffAgent())
        return HermesCoordinator(
            registry=registry,
            scoring=ScoringEngine(),
            conflict=ConflictResolver(),
            sizing=PositionSizer(),
        )

    def make_veto_coordinator():
        registry = AgentRegistry()
        registry.register(IchimokuAgent())
        registry.register(VolatilityAgent())
        registry.register(AMTAgent())
        registry.register(WyckoffAgent())
        coord = VetoExperimentalCoordinator(
            registry=registry,
            scoring=ScoringEngine(),
            conflict=ConflictResolver(),
            sizing=PositionSizer(),
        )
        coord.VETO_THRESHOLD = veto_threshold
        return coord

    baseline_coord = make_coordinator()
    veto_coord = make_veto_coordinator()

    warmup = 52

    baseline_decisions: list[dict] = []
    veto_decisions: list[dict] = []
    veto_count = 0
    baseline_r01_count = 0
    directive_shifts: dict[str, int] = {}
    veto_detail = {"vol_veto_fired": 0, "vol_no_veto": 0}

    for i, bar in enumerate(bars):
        history = bars[max(0, i - warmup):i + 1]

        ms = MarketState(
            bars=history,
            regime=Regime.RANGING,
            regime_confidence=0.5,
            volatility=None,
            timestamp=bar.timestamp,
        )

        acc = AccountState(
            equity=equity,
            peak_equity=equity,
            current_drawdown=0.0,
            max_risk_per_trade=0.01,
            max_portfolio_risk=0.05,
        )

        # Baseline
        prev_b = PreviousState(
            composite_score=baseline_decisions[-1]["composite_score"] if baseline_decisions else 0.0,
            regime=baseline_decisions[-1]["regime"] if baseline_decisions else "ranging",
            risk_directive=baseline_decisions[-1]["risk_directive"] if baseline_decisions else "FULL",
            allowed_strategy_family=baseline_decisions[-1]["allowed_family"] if baseline_decisions else None,
        )
        bd = baseline_coord.run_cycle(ms, acc, prev_b)
        baseline_decisions.append({
            "bar_idx": i,
            "regime": bd.regime,
            "risk_directive": bd.risk_directive,
            "composite_score": bd.composite_score,
            "confidence": bd.confidence,
            "allowed_family": bd.allowed_strategy_family,
        })

        if bd.risk_directive == "CASH" and "CR-01" in bd.reasoning:
            baseline_r01_count += 1

        # Experimental (volatility-only veto)
        prev_e = PreviousState(
            composite_score=veto_decisions[-1]["composite_score"] if veto_decisions else 0.0,
            regime=veto_decisions[-1]["regime"] if veto_decisions else "ranging",
            risk_directive=veto_decisions[-1]["risk_directive"] if veto_decisions else "FULL",
            allowed_strategy_family=veto_decisions[-1]["allowed_family"] if veto_decisions else None,
        )
        ed = veto_coord.run_cycle(ms, acc, prev_e)
        veto_decisions.append({
            "bar_idx": i,
            "regime": ed.regime,
            "risk_directive": ed.risk_directive,
            "composite_score": ed.composite_score,
            "confidence": ed.confidence,
            "allowed_family": ed.allowed_strategy_family,
            "reasoning": ed.reasoning,
        })

        # Track veto events
        if "R-01-VOL" in ed.reasoning:
            veto_count += 1
            veto_detail["vol_veto_fired"] += 1
        else:
            veto_detail["vol_no_veto"] += 1

        # Track directive shifts
        if bd.risk_directive != ed.risk_directive:
            shift = f"{bd.risk_directive}->{ed.risk_directive}"
            directive_shifts[shift] = directive_shifts.get(shift, 0) + 1

    # --- Compute summary stats ---
    baseline_directives = [d["risk_directive"] for d in baseline_decisions]
    veto_directives = [d["risk_directive"] for d in veto_decisions]
    baseline_conf = [d["confidence"] for d in baseline_decisions]
    veto_conf = [d["confidence"] for d in veto_decisions]
    baseline_composites = [d["composite_score"] for d in baseline_decisions]
    veto_composites = [d["composite_score"] for d in veto_decisions]

    def summarize(directives, confs, composites):
        total = len(directives)
        return {
            "total_bars": total,
            "full_pct": directives.count("FULL") / total if total else 0,
            "scale_down_pct": directives.count("SCALE_DOWN") / total if total else 0,
            "cash_pct": directives.count("CASH") / total if total else 0,
            "avg_confidence": statistics.mean(confs) if confs else 0,
            "confidence_p50": _percentile(confs, 0.5) if confs else 0,
            "avg_composite": statistics.mean(composites) if composites else 0,
            "composite_abs_mean": statistics.mean([abs(c) for c in composites]) if composites else 0,
        }

    baseline_summary = summarize(baseline_directives, baseline_conf, baseline_composites)
    veto_summary = summarize(veto_directives, veto_conf, veto_composites)

    result = VetoExperimentResult(
        symbol=symbol,
        total_bars=len(bars),
        baseline=baseline_summary,
        experimental=veto_summary,
        full_appeared_in_experiment="FULL" in veto_directives,
        full_appeared_in_baseline="FULL" in baseline_directives,
        veto_count=veto_count,
        directive_shifts=directive_shifts,
        baseline_r01_count=baseline_r01_count,
        experiment_veto_count_detail=veto_detail,
    )

    return result


def _percentile(values: list[float], p: float) -> float:
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


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def print_veto_result(result: VetoExperimentResult) -> None:
    """Print human-readable veto experiment comparison."""
    print(f"\n{'=' * 70}")
    print(f"VETO EXPERIMENT 8.4: {result.symbol} ({result.total_bars} bars)")
    print(f"Volatility-only R-01 veto (threshold={0.3})")
    print(f"{'=' * 70}")

    print(f"\n--- Baseline v2 (standard HCR-001) ---")
    b = result.baseline
    print(f"  FULL:           {b['full_pct']:.1%}")
    print(f"  SCALE_DOWN:     {b['scale_down_pct']:.1%}")
    print(f"  CASH:           {b['cash_pct']:.1%}")
    print(f"  Avg Confidence: {b['avg_confidence']:.3f}")
    print(f"  Conf p50:       {b['confidence_p50']:.3f}")
    print(f"  Avg Composite:  {b['avg_composite']:.4f}")
    print(f"  |Composite| avg:{b['composite_abs_mean']:.4f}")
    print(f"  R-01 fires:     {result.baseline_r01_count} bars")

    print(f"\n--- Experimental (Volatility-only veto) ---")
    e = result.experimental
    print(f"  FULL:           {e['full_pct']:.1%}")
    print(f"  SCALE_DOWN:     {e['scale_down_pct']:.1%}")
    print(f"  CASH:           {e['cash_pct']:.1%}")
    print(f"  Avg Confidence: {e['avg_confidence']:.3f}")
    print(f"  Conf p50:       {e['confidence_p50']:.3f}")
    print(f"  Avg Composite:  {e['avg_composite']:.4f}")
    print(f"  |Composite| avg:{e['composite_abs_mean']:.4f}")
    print(f"  Vol veto fires: {result.veto_count} bars")

    print(f"\n--- Comparison ---")
    print(f"  Baseline R-01 fires:   {result.baseline_r01_count}")
    print(f"  Experiment vol vetoes: {result.veto_count}")
    print(f"  Veto reduction:        {result.baseline_r01_count - result.veto_count} bars "
          f"({(1 - result.veto_count / max(result.baseline_r01_count, 1)):.1%} fewer)")
    print(f"  Directive shifts:      {result.directive_shifts}")
    print(f"  FULL in baseline:      {result.full_appeared_in_baseline}")
    print(f"  FULL in experiment:    {result.full_appeared_in_experiment}")

    # --- Verdict ---
    print(f"\n--- Verdict ---")
    if result.full_appeared_in_experiment and not result.full_appeared_in_baseline:
        print("  [OK] VOLATILITY VETO UNLOCKS FULL")
        print("  FULL appears in experiment but not baseline.")
        print("  Restricting R-01 veto to Volatility alone allows convergence.")
        print("  Volatility is the correct integrity gate.")
    elif result.full_appeared_in_experiment and result.full_appeared_in_baseline:
        print("  [INFO] FULL appeared in both — baseline already reachable")
    elif result.veto_count < result.baseline_r01_count:
        print("  [PARTIAL] VETO REDUCTION WITHOUT FULL")
        print(f"  R-01 fires dropped from {result.baseline_r01_count} to {result.veto_count}.")
        print("  Volatility-only veto reduces CASH frequency but FULL still absent.")
        print("  Additional agent changes may be needed (e.g., AMT/Ichimoku retirement).")
    else:
        print("  [FAIL] NO IMPACT")
        print("  Volatility-only veto produces identical results to baseline.")
        print("  The problem is not R-01 semantics — it is structural.")

    print(f"{'=' * 70}")


def save_veto_result(result: VetoExperimentResult) -> Path:
    """Save veto experiment result as JSON."""
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = log_dir / f"veto_experiment_{result.symbol}_{ts}.json"
    with open(path, "w") as f:
        json.dump({
            "symbol": result.symbol,
            "total_bars": result.total_bars,
            "veto_threshold": 0.3,
            "baseline": result.baseline,
            "experimental": result.experimental,
            "full_appeared_in_experiment": result.full_appeared_in_experiment,
            "full_appeared_in_baseline": result.full_appeared_in_baseline,
            "veto_count": result.veto_count,
            "baseline_r01_count": result.baseline_r01_count,
            "directive_shifts": result.directive_shifts,
            "experiment_veto_count_detail": result.experiment_veto_count_detail,
        }, f, indent=2)
    logger.info("Veto experiment result saved: %s", path)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    import argparse
    parser = argparse.ArgumentParser(
        description="Shadow experiment 8.4: Volatility-only R-01 veto"
    )
    parser.add_argument("--config", default="config/engine.yaml", help="Config path")
    parser.add_argument("--csv", nargs="+", default=None, help="CSV path(s)")
    parser.add_argument(
        "--veto-threshold", type=float, default=0.3,
        help="Volatility veto threshold (experimental probe, not normative)"
    )
    args = parser.parse_args()

    csv_paths = args.csv or [
        str(p) for p in Path("data/shadow").glob("*_50d.csv")
    ] if Path("data/shadow").exists() else [args.csv[0]] if args.csv else []

    if not csv_paths:
        print("No CSV files found. Use --csv or place files in data/shadow/")
        sys.exit(1)

    results = []
    for csv_path in csv_paths:
        result = run_veto_experiment(
            csv_path, config_path=args.config, veto_threshold=args.veto_threshold,
        )
        results.append(result)
        print_veto_result(result)
        save_veto_result(result)

    # --- Cross-symbol summary ---
    if len(results) > 1:
        print(f"\n{'=' * 70}")
        print("CROSS-SYMBOL SUMMARY")
        print(f"{'=' * 70}")
        print(f"  {'Symbol':<8} {'Baseline R-01':>14} {'Vol Vetoes':>12} "
              f"{'Reduction':>10} {'FULL exp':>10}")
        print(f"  {'-'*8} {'-'*14} {'-'*12} {'-'*10} {'-'*10}")
        for r in results:
            reduction = 1 - r.veto_count / max(r.baseline_r01_count, 1)
            print(
                f"  {r.symbol:<8} {r.baseline_r01_count:>14} {r.veto_count:>12} "
                f"{reduction:>9.1%} {str(r.full_appeared_in_experiment):>10}"
            )
        print(f"{'=' * 70}")

    # Exit code: 0 if FULL appeared in any experiment, 1 if not
    if any(r.full_appeared_in_experiment for r in results):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()