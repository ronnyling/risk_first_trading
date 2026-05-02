"""Shadow Experiment: Test whether FULL absence is due to over-constraint or genuine uncertainty.

Runs the same bar sequence twice:
  1. Baseline v2 (unchanged HCR-001)
  2. Experimental v2 (R-02 conditionally bypassed when structural agents agree)

Decision criterion:
  - If FULL appears in experiment but not baseline → over-constraint confirmed
  - If FULL absent in both → genuine uncertainty dominates

This script does NOT modify production code. It creates a temporary
ShadowCoordinator that wraps HermesCoordinator with modified conflict logic.
Shadow-only — no execution, no promotion, no threshold changes.

Usage:
    python scripts/shadow_experiment.py
    python scripts/shadow_experiment.py --csv data/sample/spy_1h.csv
    python scripts/shadow_experiment.py --csv data/shadow/spy_1h_50d.csv data/shadow/btcusd_1h_50d.csv
"""

from __future__ import annotations

import json
import logging
import statistics
import sys
from dataclasses import dataclass
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
from src.hermes.conflict import ConflictResolver, ConflictInput
from src.hermes.sizing import PositionSizer, SizingInput

logger = logging.getLogger("shadow_experiment")


# ---------------------------------------------------------------------------
# Experimental coordinator: R-02 bypass when structural agents agree
# ---------------------------------------------------------------------------

class ShadowExperimentalCoordinator(HermesCoordinator):
    """Coordinator with conditionally relaxed R-02 (low confidence gate).

    Modification (shadow-only):
      R-02 (total_confidence < 0.5 → SCALE_DOWN) is bypassed when:
        - IchimokuAgent confidence >= HIGH_THRESHOLD
        - VolatilityAgent confidence >= HIGH_THRESHOLD

    R-01 (dispersion → CASH) and R-03 (score jump → SCALE_DOWN) remain enforced.
    R-04 (normal operation) remains enforced.
    """

    HIGH_THRESHOLD = 0.4  # Minimum confidence for structural agents to bypass R-02

    def run_cycle(
        self,
        market_state: MarketState,
        account_state: AccountState,
        previous: PreviousState | None = None,
    ) -> HermesDecision:
        """Run one v2 evaluation cycle with experimental conflict logic."""
        # 1. Collect agent outputs (identical to baseline)
        outputs = {}
        for output in self._registry.run_all(market_state):
            outputs[output.agent_name] = output

        agent_scores = {name: out.score for name, out in outputs.items()}
        agent_confidences = {name: out.confidence for name, out in outputs.items()}

        # 2. Scoring (identical to baseline)
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

        conflict_output = self._experimental_resolve(conflict_input, agent_confidences)

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
        agent_confidences: dict[str, float],
    ) -> "ConflictOutput":
        """Apply HCR-001 with experimental R-02 bypass.

        R-01 (dispersion > 0.60 → CASH): ENFORCED
        R-02 (confidence < 0.50 → SCALE_DOWN): BYPASSED when:
          - Ichimoku confidence >= 0.4
          - Volatility confidence >= 0.4
        R-03 (score jump >= 0.80 → SCALE_DOWN): ENFORCED
        R-04 (normal): ENFORCED
        """
        from src.hermes.conflict import (
            DISAGREEMENT_THRESHOLD, FLIP_RISK_THRESHOLD,
            TRENDING_THRESHOLD, RANGING_LOWER,
            _classify_regime, _map_regime_to_family,
            ConflictOutput,
        )

        # R-01: Integrity First — ENFORCED
        if inputs.score_dispersion > DISAGREEMENT_THRESHOLD:
            return ConflictOutput(
                regime="INDETERMINATE",
                risk_directive="CASH",
                allowed_strategy_family=None,
                reasoning=(
                    f"CR-01: score_dispersion={inputs.score_dispersion:.3f} "
                    f"> {DISAGREEMENT_THRESHOLD}. Agents disagree."
                ),
                resolution_path="R-01",
            )

        # R-02: Low Confidence — EXPERIMENTAL BYPASS
        ichimoku_conf = agent_confidences.get("Ichimoku", 0.0)
        volatility_conf = agent_confidences.get("Volatility", 0.0)
        r02_bypassed = (
            ichimoku_conf >= self.HIGH_THRESHOLD
            and volatility_conf >= self.HIGH_THRESHOLD
        )

        if inputs.total_confidence < 0.50 and not r02_bypassed:
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

        extra = ""
        if r02_bypassed:
            extra = (
                f" [R-02 BYPASS: Ichimoku={ichimoku_conf:.3f}, "
                f"Volatility={volatility_conf:.3f} >= {self.HIGH_THRESHOLD}]"
            )

        return ConflictOutput(
            regime=regime,
            risk_directive="FULL",
            allowed_strategy_family=family,
            reasoning=(
                f"R-04: Normal. composite={inputs.composite_score:.3f}, "
                f"regime={regime}, family={family}{extra}"
            ),
            resolution_path="R-04",
        )


# ---------------------------------------------------------------------------
# Experiment runner
# ---------------------------------------------------------------------------

@dataclass
class ExperimentResult:
    """Result from comparing baseline vs experimental on one symbol."""
    symbol: str
    total_bars: int
    baseline: dict
    experimental: dict
    full_appeared_in_experiment: bool
    full_appeared_in_baseline: bool
    r02_bypass_count: int
    directive_shifts: dict[str, int]  # e.g. {"SCALE_DOWN→FULL": 5}


def run_experiment(
    csv_path: str,
    config_path: str = "config/engine.yaml",
) -> ExperimentResult:
    """Run baseline vs experimental v2 on the same bars."""
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

    def make_exp_coordinator():
        registry = AgentRegistry()
        registry.register(IchimokuAgent())
        registry.register(VolatilityAgent())
        registry.register(AMTAgent())
        registry.register(WyckoffAgent())
        return ShadowExperimentalCoordinator(
            registry=registry,
            scoring=ScoringEngine(),
            conflict=ConflictResolver(),
            sizing=PositionSizer(),
        )

    baseline_coord = make_coordinator()
    exp_coord = make_exp_coordinator()

    warmup = 52

    baseline_decisions: list[dict] = []
    exp_decisions: list[dict] = []
    r02_bypass_count = 0
    directive_shifts: dict[str, int] = {}

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

        # Experimental
        prev_e = PreviousState(
            composite_score=exp_decisions[-1]["composite_score"] if exp_decisions else 0.0,
            regime=exp_decisions[-1]["regime"] if exp_decisions else "ranging",
            risk_directive=exp_decisions[-1]["risk_directive"] if exp_decisions else "FULL",
            allowed_strategy_family=exp_decisions[-1]["allowed_family"] if exp_decisions else None,
        )
        ed = exp_coord.run_cycle(ms, acc, prev_e)
        exp_decisions.append({
            "bar_idx": i,
            "regime": ed.regime,
            "risk_directive": ed.risk_directive,
            "composite_score": ed.composite_score,
            "confidence": ed.confidence,
            "allowed_family": ed.allowed_strategy_family,
            "reasoning": ed.reasoning,
        })

        # Track R-02 bypasses
        if "R-02 BYPASS" in ed.reasoning:
            r02_bypass_count += 1

        # Track directive shifts
        if bd.risk_directive != ed.risk_directive:
            shift = f"{bd.risk_directive}→{ed.risk_directive}"
            directive_shifts[shift] = directive_shifts.get(shift, 0) + 1

    # --- Compute summary stats ---
    baseline_directives = [d["risk_directive"] for d in baseline_decisions]
    exp_directives = [d["risk_directive"] for d in exp_decisions]
    baseline_conf = [d["confidence"] for d in baseline_decisions]
    exp_conf = [d["confidence"] for d in exp_decisions]

    def summarize(directives: list[str], confs: list[float]) -> dict:
        total = len(directives)
        return {
            "total_bars": total,
            "full_pct": directives.count("FULL") / total if total else 0,
            "scale_down_pct": directives.count("SCALE_DOWN") / total if total else 0,
            "cash_pct": directives.count("CASH") / total if total else 0,
            "avg_confidence": statistics.mean(confs) if confs else 0,
            "confidence_p50": _percentile(confs, 0.5) if confs else 0,
        }

    baseline_summary = summarize(baseline_directives, baseline_conf)
    exp_summary = summarize(exp_directives, exp_conf)

    result = ExperimentResult(
        symbol=symbol,
        total_bars=len(bars),
        baseline=baseline_summary,
        experimental=exp_summary,
        full_appeared_in_experiment="FULL" in exp_directives,
        full_appeared_in_baseline="FULL" in baseline_directives,
        r02_bypass_count=r02_bypass_count,
        directive_shifts=directive_shifts,
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

def print_experiment_result(result: ExperimentResult) -> None:
    """Print human-readable experiment comparison."""
    print(f"\n{'=' * 70}")
    print(f"SHADOW EXPERIMENT: {result.symbol} ({result.total_bars} bars)")
    print(f"{'=' * 70}")

    print(f"\n--- Baseline v2 (unchanged HCR-001) ---")
    b = result.baseline
    print(f"  FULL:          {b['full_pct']:.1%}")
    print(f"  SCALE_DOWN:    {b['scale_down_pct']:.1%}")
    print(f"  CASH:          {b['cash_pct']:.1%}")
    print(f"  Avg Confidence: {b['avg_confidence']:.3f}")
    print(f"  Conf p50:      {b['confidence_p50']:.3f}")

    print(f"\n--- Experimental v2 (R-02 bypass) ---")
    e = result.experimental
    print(f"  FULL:          {e['full_pct']:.1%}")
    print(f"  SCALE_DOWN:    {e['scale_down_pct']:.1%}")
    print(f"  CASH:          {e['cash_pct']:.1%}")
    print(f"  Avg Confidence: {e['avg_confidence']:.3f}")
    print(f"  Conf p50:      {e['confidence_p50']:.3f}")

    print(f"\n--- Experiment Details ---")
    print(f"  R-02 bypassed:     {result.r02_bypass_count} bars")
    print(f"  Directive shifts:  {result.directive_shifts}")
    print(f"  FULL in baseline:  {result.full_appeared_in_baseline}")
    print(f"  FULL in experiment: {result.full_appeared_in_experiment}")

    # --- Verdict ---
    print(f"\n--- Verdict ---")
    if result.full_appeared_in_experiment and not result.full_appeared_in_baseline:
        print("  [WARN] OVER-CONSTRAINT CONFIRMED")
        print("  FULL appears in experiment but not baseline.")
        print("  R-02 is structurally preventing FULL from firing.")
        print("  The system is too conservative, not the market too uncertain.")
    elif not result.full_appeared_in_experiment and not result.full_appeared_in_baseline:
        print("  [OK] UNCERTAINTY DOMINATES")
        print("  FULL absent in both baseline and experiment.")
        print("  R-02 bypass was not sufficient to produce FULL.")
        print("  The market period genuinely lacked convergence.")
    else:
        print("  [INFO] UNEXPECTED: FULL appeared in baseline")
        print("  This contradicts the hypothesis that R-02 blocks FULL.")

    print(f"{'=' * 70}")


def save_experiment_result(result: ExperimentResult) -> Path:
    """Save experiment result as JSON."""
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = log_dir / f"experiment_{result.symbol}_{ts}.json"
    with open(path, "w") as f:
        json.dump({
            "symbol": result.symbol,
            "total_bars": result.total_bars,
            "baseline": result.baseline,
            "experimental": result.experimental,
            "full_appeared_in_experiment": result.full_appeared_in_experiment,
            "full_appeared_in_baseline": result.full_appeared_in_baseline,
            "r02_bypass_count": result.r02_bypass_count,
            "directive_shifts": result.directive_shifts,
        }, f, indent=2)
    logger.info("Experiment result saved: %s", path)
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
    parser = argparse.ArgumentParser(description="Shadow experiment: baseline vs R-02 bypass")
    parser.add_argument("--config", default="config/engine.yaml", help="Config path")
    parser.add_argument("--csv", nargs="+", default=None, help="CSV path(s)")
    args = parser.parse_args()

    csv_paths = args.csv or [
        str(p) for p in Path("data/shadow").glob("*_50d.csv")
    ] if Path("data/shadow").exists() else [args.csv[0]] if args.csv else []

    if not csv_paths:
        print("No CSV files found. Use --csv or place files in data/shadow/")
        sys.exit(1)

    results = []
    for csv_path in csv_paths:
        result = run_experiment(csv_path, config_path=args.config)
        results.append(result)
        print_experiment_result(result)
        save_experiment_result(result)

    # --- Cross-symbol summary ---
    if len(results) > 1:
        print(f"\n{'=' * 70}")
        print("CROSS-SYMBOL SUMMARY")
        print(f"{'=' * 70}")
        for r in results:
            print(
                f"  {r.symbol}: baseline_FULL={r.baseline['full_pct']:.1%} "
                f"exp_FULL={r.experimental['full_pct']:.1%} "
                f"bypasses={r.r02_bypass_count} "
                f"FULL_in_exp={r.full_appeared_in_experiment}"
            )
        print(f"{'=' * 70}")

    # Exit code: 0 if experiment produced FULL, 1 if not
    if any(r.full_appeared_in_experiment for r in results):
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()