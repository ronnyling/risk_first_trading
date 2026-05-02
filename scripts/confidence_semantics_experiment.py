"""Confidence Semantics Experiment — Phase 8.5, Step 2.

Shadow-only experiment comparing 3 aggregation models against baseline.
Each model is evaluated independently; results are not chained.

No production code modified. No thresholds changed.
"""

from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from src.core.types import Bar, Regime
from src.hermes.agents.base import MarketState
from src.hermes.agents.stub_agents import (
    AMTAgent,
    IchimokuAgent,
    VolatilityAgent,
    WyckoffAgent,
)
from src.hermes.conflict import (
    DISAGREEMENT_THRESHOLD,
    FLIP_RISK_THRESHOLD,
    LOW_CONFIDENCE_THRESHOLD,
    ConflictInput,
    ConflictResolver,
)

DATASETS = {
    "BTCUSD_50D": "data/shadow/btcusd_1h_50d.csv",
    "SPY_50D": "data/shadow/spy_1h_50d.csv",
}

MIN_BARS = 52
R02_THRESHOLD = LOW_CONFIDENCE_THRESHOLD  # 0.50 — NOT changed


# --- Aggregation Models ---

def model_baseline(confidences: dict[str, float]) -> float:
    """Current model: simple arithmetic mean."""
    vals = list(confidences.values())
    return sum(vals) / len(vals)


def model_structural_primary(confidences: dict[str, float]) -> float:
    """Structural agents drive, validation agents dampen.
    
    Structural: Ichimoku, Wyckoff (trend + effort/result)
    Validation: AMT, Volatility (value + regime)
    """
    structural = (confidences["Ichimoku"] + confidences["Wyckoff"]) / 2
    validation = (confidences["AMT"] + confidences["Volatility"]) / 2
    return structural * 0.7 + validation * 0.3


def model_max_structural(confidences: dict[str, float]) -> float:
    """Single strongest structural agent dominates.
    
    Uses max(Ichimoku, Wyckoff) as primary confidence driver.
    """
    structural = max(confidences["Ichimoku"], confidences["Wyckoff"])
    validation = (confidences["AMT"] + confidences["Volatility"]) / 2
    return structural * 0.6 + validation * 0.4


MODELS = {
    "Baseline (mean)": model_baseline,
    "Structural-primary": model_structural_primary,
    "Max-structural": model_max_structural,
}


def load_csv(path: str) -> list[Bar]:
    bars: list[Bar] = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bars.append(Bar(
                timestamp=row["timestamp"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            ))
    return bars


def compute_percentiles(values: list[float]) -> dict[str, float]:
    s = sorted(values)
    n = len(s)
    def pct(p: float) -> float:
        idx = p * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        return s[lo] + frac * (s[hi] - s[lo])
    return {
        "p25": pct(0.25),
        "p50": pct(0.50),
        "p75": pct(0.75),
        "p90": pct(0.90),
        "p95": pct(0.95),
    }


def run_experiment(dataset_name: str, csv_path: str) -> dict:
    bars = load_csv(csv_path)
    n_bars = len(bars)

    agents = [
        IchimokuAgent(),
        VolatilityAgent(),
        AMTAgent(),
        WyckoffAgent(),
    ]
    resolver = ConflictResolver()

    # Per-bar agent outputs (computed once, shared across models)
    bar_agent_outputs: list[dict[str, float]] = []

    for i in range(MIN_BARS, n_bars):
        window = bars[i - MIN_BARS : i + 1]
        state = MarketState(
            bars=window,
            regime=Regime.RANGING,
            regime_confidence=0.5,
            volatility=None,
            timestamp=window[-1].timestamp,
        )
        outputs = {}
        for agent in agents:
            out = agent.run(state)
            outputs[agent.name] = out.confidence
        bar_agent_outputs.append(outputs)

    # For each model, compute alternative total_confidence and apply R-02
    model_results = {}
    for model_name, model_fn in MODELS.items():
        alt_confidences = []
        directives = {"FULL": 0, "SCALE_DOWN": 0, "CASH": 0}
        r02_fires = 0

        for idx, confidences in enumerate(bar_agent_outputs):
            alt_conf = model_fn(confidences)
            alt_confidences.append(alt_conf)

            # Compute scores using baseline agent confidences for scoring
            # (we only change the confidence aggregation, not the score)
            scores = []
            agent_confs_for_scoring = []
            for agent in agents:
                # Re-run to get scores (agents are stateless, deterministic)
                window = bars[idx + MIN_BARS - MIN_BARS : idx + MIN_BARS + 1]
                state = MarketState(
                    bars=window,
                    regime=Regime.RANGING,
                    regime_confidence=0.5,
                    volatility=None,
                    timestamp=window[-1].timestamp,
                )
                out = agent.run(state)
                scores.append(out.score)
                agent_confs_for_scoring.append(out.confidence)

            # Composite score (weighted by individual confidences)
            composite_score = sum(s * c for s, c in zip(scores, agent_confs_for_scoring))

            # Score dispersion
            score_dispersion = statistics.stdev(scores) if len(scores) >= 2 else 0.0

            # Apply HCR-001 with alternative confidence
            prev_score = composite_score if idx == 0 else prev_composite
            prev_directive = "SCALE_DOWN" if idx == 0 else prev_directive_val
            prev_regime = "ranging" if idx == 0 else prev_regime_val

            inputs = ConflictInput(
                composite_score=composite_score,
                total_confidence=alt_conf,
                score_dispersion=score_dispersion,
                previous_composite_score=prev_score,
                previous_regime=prev_regime,
                previous_risk_directive=prev_directive,
                previous_allowed_family=None,
            )
            output = resolver.resolve(inputs)

            directives[output.risk_directive] += 1
            if output.resolution_path == "R-02":
                r02_fires += 1

            prev_composite = composite_score
            prev_directive_val = output.risk_directive
            prev_regime_val = output.regime

        n = len(alt_confidences)
        stats = {
            "mean": statistics.mean(alt_confidences),
            "median": statistics.median(alt_confidences),
            "min": min(alt_confidences),
            "max": max(alt_confidences),
            **compute_percentiles(alt_confidences),
        }

        bars_above_50 = sum(1 for c in alt_confidences if c >= R02_THRESHOLD)
        bars_above_45 = sum(1 for c in alt_confidences if c >= 0.45)

        model_results[model_name] = {
            "stats": stats,
            "bars_above_45": bars_above_45,
            "bars_above_50": bars_above_50,
            "directives": directives,
            "r02_fires": r02_fires,
            "n_bars": n,
        }

    return {
        "dataset": dataset_name,
        "n_bars": n_bars - MIN_BARS,
        "models": model_results,
    }


def format_report(results: list[dict]) -> str:
    lines = [
        "# Confidence Semantics Experiment — Phase 8.5, Step 2",
        "",
        "**Date**: 2026-04-29",
        "**Status**: Shadow-only — no production code modified",
        "**Constraint**: R-02 threshold stays at 0.50 (governance contract)",
        "",
        "## Hypothesis",
        "",
        "Treating agents as having distinct epistemic roles produces a different",
        "`total_confidence` than simple averaging, potentially reaching >= 0.50",
        "in trending markets.",
        "",
        "## Models",
        "",
        "| Model | Formula | Rationale |",
        "|-------|---------|-----------|",
        "| **Baseline** | `mean(all)` | Current behavior |",
        "| **Structural-primary** | `mean(Ichimoku, Wyckoff) * 0.7 + mean(AMT, Volatility) * 0.3` | Structural drivers, validation dampeners |",
        "| **Max-structural** | `max(Ichimoku, Wyckoff) * 0.6 + mean(AMT, Volatility) * 0.4` | Strongest structural dominates |",
        "",
        "**Each model is evaluated independently against the baseline.**",
        "**Results are not chained or reused.**",
        "",
        "---",
        "",
    ]

    for r in results:
        ds = r["dataset"]
        lines += [f"## {ds} ({r['n_bars']} bars)", ""]

        # Confidence statistics comparison
        lines += [
            "### Confidence Distribution Comparison",
            "",
            "| Model | Mean | Median | p25 | p50 | p75 | p90 | p95 | Max |",
            "|-------|------|--------|-----|-----|-----|-----|-----|-----|",
        ]
        for model_name, m in r["models"].items():
            s = m["stats"]
            lines.append(
                f"| {model_name} "
                f"| {s['mean']:.4f} "
                f"| {s['median']:.4f} "
                f"| {s['p25']:.4f} "
                f"| {s['p50']:.4f} "
                f"| {s['p75']:.4f} "
                f"| {s['p90']:.4f} "
                f"| {s['p95']:.4f} "
                f"| {s['max']:.4f} |"
            )

        lines += [
            "",
            "### R-02 Threshold Crossing",
            "",
            "| Model | Bars >= 0.45 | Bars >= 0.50 | R-02 Fires |",
            "|-------|-------------|-------------|------------|",
        ]
        for model_name, m in r["models"].items():
            n = m["n_bars"]
            pct45 = m["bars_above_45"] / n * 100 if n > 0 else 0
            pct50 = m["bars_above_50"] / n * 100 if n > 0 else 0
            lines.append(
                f"| {model_name} "
                f"| {m['bars_above_45']} ({pct45:.1f}%) "
                f"| {m['bars_above_50']} ({pct50:.1f}%) "
                f"| {m['r02_fires']} |"
            )

        lines += [
            "",
            "### Directive Distribution",
            "",
            "| Model | FULL | SCALE_DOWN | CASH |",
            "|-------|------|------------|------|",
        ]
        for model_name, m in r["models"].items():
            d = m["directives"]
            lines.append(
                f"| {model_name} "
                f"| {d['FULL']} "
                f"| {d['SCALE_DOWN']} "
                f"| {d['CASH']} |"
            )

        lines += [
            "",
            "### Improvement Over Baseline",
            "",
        ]
        baseline = r["models"]["Baseline (mean)"]
        for model_name, m in r["models"].items():
            if model_name == "Baseline (mean)":
                continue
            delta_mean = m["stats"]["mean"] - baseline["stats"]["mean"]
            delta_max = m["stats"]["max"] - baseline["stats"]["max"]
            delta_p90 = m["stats"]["p90"] - baseline["stats"]["p90"]
            delta_r02 = baseline["r02_fires"] - m["r02_fires"]
            lines.append(
                f"**{model_name}** vs Baseline:\n"
                f"- Mean: {delta_mean:+.4f} "
                f"({'improved' if delta_mean > 0 else 'decreased'})\n"
                f"- p90: {delta_p90:+.4f} "
                f"({'improved' if delta_p90 > 0 else 'decreased'})\n"
                f"- Max: {delta_max:+.4f} "
                f"({'improved' if delta_max > 0 else 'decreased'})\n"
                f"- R-02 fires reduced by: {delta_r02}"
            )

        lines += ["---", ""]

    # Cross-dataset summary
    lines += [
        "## Cross-Dataset Summary",
        "",
        "| Dataset | Model | Max Mean | Bars >= 0.50 | R-02 Fires |",
        "|---------|-------|----------|-------------|------------|",
    ]
    for r in results:
        ds = r["dataset"]
        for model_name, m in r["models"].items():
            lines.append(
                f"| {ds} | {model_name} "
                f"| {m['stats']['max']:.4f} "
                f"| {m['bars_above_50']}/{m['n_bars']} "
                f"| {m['r02_fires']} |"
            )

    lines += [
        "",
        "## Verdict",
        "",
    ]

    for r in results:
        ds = r["dataset"]
        baseline_max = r["models"]["Baseline (mean)"]["stats"]["max"]
        any_crossed = False
        best_model = ""
        best_max = 0.0
        for model_name, m in r["models"].items():
            if m["bars_above_50"] > 0:
                any_crossed = True
            if m["stats"]["max"] > best_max:
                best_max = m["stats"]["max"]
                best_model = model_name

        if any_crossed:
            lines.append(
                f"- **{ds}**: At least one model crossed 0.50 — "
                f"aggregation semantics were the binding constraint"
            )
        else:
            gap = R02_THRESHOLD - best_max
            gap_pct = (1 - best_max / R02_THRESHOLD) * 100
            lines.append(
                f"- **{ds}**: No model crossed 0.50 — "
                f"best was {best_model} at {best_max:.4f} "
                f"(gap: {gap:.4f}, {gap_pct:.1f}% below threshold)"
            )

    lines += [
        "",
        "### Interpretation",
        "",
        "If any model crosses 0.50, the current mean model was structurally",
        "suppressing confidence. If no model crosses, the agents' individual",
        "confidence ranges are the fundamental constraint.",
        "",
    ]

    return "\n".join(lines)


def main() -> None:
    print("=" * 60)
    print("  CONFIDENCE SEMANTICS EXPERIMENT — Phase 8.5, Step 2")
    print("=" * 60)

    results = []
    for name, path in DATASETS.items():
        full_path = Path(_root) / path
        if not full_path.exists():
            print(f"\n[SKIP] {name}: {full_path} not found")
            continue

        print(f"\n[EXPERIMENT] {name} ...", end=" ", flush=True)
        r = run_experiment(name, str(full_path))
        results.append(r)

        baseline_max = r["models"]["Baseline (mean)"]["stats"]["max"]
        best_model = max(r["models"].items(), key=lambda x: x[1]["stats"]["max"])
        print(f"done.")
        print(f"  Baseline max: {baseline_max:.4f}")
        print(f"  Best model: {best_model[0]} (max: {best_model[1]['stats']['max']:.4f})")
        print(f"  Bars >= 0.50: {best_model[1]['bars_above_50']}/{r['n_bars']}")

    if not results:
        print("\n[ERROR] No datasets found")
        return

    report = format_report(results)
    out_path = Path(_root) / "docs" / "16_confidence_semantics_results.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"\n[REPORT] {out_path}")

    # Print verdict
    print("\n" + "=" * 60)
    print("  VERDICT")
    print("=" * 60)
    for r in results:
        ds = r["dataset"]
        baseline_max = r["models"]["Baseline (mean)"]["stats"]["max"]
        best = max(r["models"].items(), key=lambda x: x[1]["stats"]["max"])
        any_crossed = any(m["bars_above_50"] > 0 for m in r["models"].values())
        if any_crossed:
            print(f"\n  {ds}: AGGREGATION WAS THE CONSTRAINT (model crossed 0.50)")
        else:
            print(f"\n  {ds}: AGENTS ARE THE CONSTRAINT (best: {best[0]} = {best[1]['stats']['max']:.4f})")


if __name__ == "__main__":
    main()