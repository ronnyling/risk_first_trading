"""Combined Semantics Experiment — Phase 8.6.

Runs 4 configurations combining veto and confidence semantics.
Each configuration is evaluated independently.

Configs:
  A: Baseline (mean confidence, any-agent dispersion veto)
  B: Veto-only (mean confidence, volatility-only veto)
  C: Confidence-only (max-structural confidence, any-agent dispersion veto)
  D: Combined v2.1 (max-structural confidence, volatility-only veto)

Shadow-only. No production code modified.
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

DATASETS = {
    "BTCUSD_50D": "data/shadow/btcusd_1h_50d.csv",
    "SPY_50D": "data/shadow/spy_1h_50d.csv",
}

MIN_BARS = 52
R02_THRESHOLD = 0.50
VETO_THRESHOLD = 0.3  # from Phase 8.4
ALPHA = 0.6  # provisional — from Phase 8.5


# --- Confidence Aggregation Models ---

def conf_mean(confidences: dict[str, float]) -> float:
    vals = list(confidences.values())
    return sum(vals) / len(vals)


def conf_max_structural(confidences: dict[str, float]) -> float:
    structural = max(confidences["Ichimoku"], confidences["Wyckoff"])
    validation = (confidences["AMT"] + confidences["Volatility"]) / 2
    return ALPHA * structural + (1 - ALPHA) * validation


# --- Veto Models ---

def veto_any_agent(score_dispersion: float) -> bool:
    """Current v2: any agent dispersion > 0.60."""
    return score_dispersion > 0.60


def veto_volatility_only(
    vol_score: float, composite_score: float, abs_vol: float
) -> bool:
    """Phase 8.4: only Volatility opposes composite."""
    return (vol_score * composite_score < 0) and (abs_vol > VETO_THRESHOLD)


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
        "p25": pct(0.25), "p50": pct(0.50), "p75": pct(0.75),
        "p90": pct(0.90), "p95": pct(0.95),
    }


def analyze_full_clusters(directives: list[str]) -> dict:
    """Analyze FULL directive clustering patterns."""
    full_indices = [i for i, d in enumerate(directives) if d == "FULL"]
    if not full_indices:
        return {"count": 0, "clusters": 0, "max_cluster": 0, "isolated": 0}

    # Find clusters (consecutive FULL bars)
    clusters = []
    current = [full_indices[0]]
    for i in range(1, len(full_indices)):
        if full_indices[i] == full_indices[i - 1] + 1:
            current.append(full_indices[i])
        else:
            clusters.append(current)
            current = [full_indices[i]]
    clusters.append(current)

    isolated = sum(1 for c in clusters if len(c) == 1)
    return {
        "count": len(full_indices),
        "clusters": len(clusters),
        "max_cluster": max(len(c) for c in clusters),
        "isolated": isolated,
    }


def run_config(
    config_name: str,
    agents: list,
    conf_fn,
    use_vol_veto: bool,
    bars: list[Bar],
    bar_agent_data: list[dict],
) -> dict:
    """Run a single configuration across all bars."""
    n = len(bars)
    alt_confidences = []
    directives = {"FULL": 0, "SCALE_DOWN": 0, "CASH": 0}
    directive_sequence = []
    r01_fires = 0
    r02_fires = 0

    for idx in range(n):
        data = bar_agent_data[idx]
        scores = data["scores"]
        confidences = data["confidences"]

        # Alternative confidence
        alt_conf = conf_fn(confidences)
        alt_confidences.append(alt_conf)

        # Composite score (weighted by individual confidences)
        composite_score = sum(s * c for s, c in zip(scores, confidences.values()))

        # Score dispersion
        score_dispersion = statistics.stdev(scores) if len(scores) >= 2 else 0.0

        # Volatility agent score
        vol_score = data["vol_score"]

        # Veto check
        if use_vol_veto:
            veto_fires = veto_volatility_only(
                vol_score, composite_score, abs(vol_score)
            )
        else:
            veto_fires = veto_any_agent(score_dispersion)

        if veto_fires:
            directive = "CASH"
            r01_fires += 1
        elif alt_conf < R02_THRESHOLD:
            directive = "SCALE_DOWN"
            r02_fires += 1
        else:
            # R-04: classify by composite score
            if composite_score >= 0.3 or composite_score <= -0.3:
                directive = "FULL"
            else:
                directive = "SCALE_DOWN"

        directives[directive] += 1
        directive_sequence.append(directive)

    # Stats
    n_bars = len(alt_confidences)
    stats = {
        "mean": statistics.mean(alt_confidences),
        "median": statistics.median(alt_confidences),
        "min": min(alt_confidences),
        "max": max(alt_confidences),
        **compute_percentiles(alt_confidences),
    }

    bars_above_45 = sum(1 for c in alt_confidences if c >= 0.45)
    bars_above_50 = sum(1 for c in alt_confidences if c >= R02_THRESHOLD)

    full_analysis = analyze_full_clusters(directive_sequence)

    # FULL-then-CASH transitions (to check if FULL coincides with veto)
    full_then_cash = 0
    for i in range(1, len(directive_sequence)):
        if directive_sequence[i - 1] == "FULL" and directive_sequence[i] == "CASH":
            full_then_cash += 1

    return {
        "config": config_name,
        "stats": stats,
        "bars_above_45": bars_above_45,
        "bars_above_50": bars_above_50,
        "directives": directives,
        "directive_sequence": directive_sequence,
        "r01_fires": r01_fires,
        "r02_fires": r02_fires,
        "n_bars": n_bars,
        "full_analysis": full_analysis,
        "full_then_cash": full_then_cash,
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

    # Pre-compute agent outputs once
    bar_agent_data = []
    for i in range(MIN_BARS, n_bars):
        window = bars[i - MIN_BARS : i + 1]
        state = MarketState(
            bars=window,
            regime=Regime.RANGING,
            regime_confidence=0.5,
            volatility=None,
            timestamp=window[-1].timestamp,
        )
        scores = []
        confidences = {}
        vol_score = 0.0
        for agent in agents:
            out = agent.run(state)
            scores.append(out.score)
            confidences[agent.name] = out.confidence
            if agent.name == "Volatility":
                vol_score = out.score
        bar_agent_data.append({
            "scores": scores,
            "confidences": confidences,
            "vol_score": vol_score,
        })

    experiment_bars = bars[MIN_BARS:]

    configs = [
        ("A: Baseline", conf_mean, False),
        ("B: Veto-only", conf_mean, True),
        ("C: Confidence-only", conf_max_structural, False),
        ("D: Combined v2.1", conf_max_structural, True),
    ]

    results = {}
    for name, conf_fn, use_vol_veto in configs:
        results[name] = run_config(
            name, agents, conf_fn, use_vol_veto,
            experiment_bars, bar_agent_data,
        )

    return {
        "dataset": dataset_name,
        "n_bars": len(experiment_bars),
        "configs": results,
    }


def format_report(results: list[dict]) -> str:
    lines = [
        "# Combined Semantics Experiment — Phase 8.6",
        "",
        "**Date**: 2026-04-29",
        "**Status**: Shadow-only — no production code modified",
        "**Constraints**: R-02 threshold = 0.50 (unchanged), agent math (unchanged)",
        "",
        "## Configurations",
        "",
        "| Config | Confidence | Veto | Purpose |",
        "|--------|-----------|------|---------|",
        "| A: Baseline | mean(all) | any-agent dispersion | Current v2 |",
        "| B: Veto-only | mean(all) | Volatility-only | Phase 8.4 only |",
        "| C: Confidence-only | max-structural (alpha=0.6) | any-agent dispersion | Phase 8.5 only |",
        "| D: Combined v2.1 | max-structural (alpha=0.6) | Volatility-only | Both findings |",
        "",
        "**alpha = 0.6 is provisional (Phase 8.5 exploratory result).**",
        "",
        "---",
        "",
    ]

    for r in results:
        ds = r["dataset"]
        lines += [f"## {ds} ({r['n_bars']} bars)", ""]

        # Directive distribution
        lines += [
            "### Directive Distribution",
            "",
            "| Config | FULL | SCALE_DOWN | CASH | FULL % | CASH % |",
            "|--------|------|------------|------|--------|--------|",
        ]
        for name, c in r["configs"].items():
            d = c["directives"]
            n = c["n_bars"]
            fpct = d["FULL"] / n * 100 if n > 0 else 0
            cpct = d["CASH"] / n * 100 if n > 0 else 0
            lines.append(
                f"| {name} | {d['FULL']} | {d['SCALE_DOWN']} | {d['CASH']} "
                f"| {fpct:.1f}% | {cpct:.1f}% |"
            )

        # Confidence stats
        lines += [
            "",
            "### Confidence Distribution",
            "",
            "| Config | Mean | p50 | p75 | p90 | p95 | Max |",
            "|--------|------|-----|-----|-----|-----|-----|",
        ]
        for name, c in r["configs"].items():
            s = c["stats"]
            lines.append(
                f"| {name} | {s['mean']:.4f} | {s['p50']:.4f} "
                f"| {s['p75']:.4f} | {s['p90']:.4f} | {s['p95']:.4f} "
                f"| {s['max']:.4f} |"
            )

        # Threshold crossing
        lines += [
            "",
            "### R-02 Threshold Crossing",
            "",
            "| Config | Bars >= 0.45 | Bars >= 0.50 | R-01 Fires | R-02 Fires |",
            "|--------|-------------|-------------|------------|------------|",
        ]
        for name, c in r["configs"].items():
            n = c["n_bars"]
            pct45 = c["bars_above_45"] / n * 100 if n > 0 else 0
            pct50 = c["bars_above_50"] / n * 100 if n > 0 else 0
            lines.append(
                f"| {name} | {c['bars_above_45']} ({pct45:.1f}%) "
                f"| {c['bars_above_50']} ({pct50:.1f}%) "
                f"| {c['r01_fires']} | {c['r02_fires']} |"
            )

        # FULL clustering analysis
        lines += [
            "",
            "### FULL Clustering Analysis (Safety Validation)",
            "",
            "| Config | FULL Count | Clusters | Max Cluster | Isolated | FULL->CASH |",
            "|--------|-----------|----------|-------------|----------|------------|",
        ]
        for name, c in r["configs"].items():
            fa = c["full_analysis"]
            lines.append(
                f"| {name} | {fa['count']} | {fa['clusters']} "
                f"| {fa['max_cluster']} | {fa['isolated']} "
                f"| {c['full_then_cash']} |"
            )

        lines += ["---", ""]

    # Cross-dataset summary
    lines += [
        "## Cross-Dataset Summary",
        "",
        "| Dataset | Config | FULL | CASH | FULL Clusters | FULL->CASH |",
        "|---------|--------|------|------|---------------|------------|",
    ]
    for r in results:
        ds = r["dataset"]
        for name, c in r["configs"].items():
            fa = c["full_analysis"]
            lines.append(
                f"| {ds} | {name} | {c['directives']['FULL']} "
                f"| {c['directives']['CASH']} | {fa['clusters']} "
                f"| {c['full_then_cash']} |"
            )

    # Safety verdict
    lines += [
        "",
        "## Safety Validation",
        "",
        "### FULL Appearance Patterns",
        "",
    ]
    for r in results:
        ds = r["dataset"]
        d = r["configs"]["D: Combined v2.1"]
        fa = d["full_analysis"]
        lines.append(f"**{ds} — Config D (Combined v2.1)**:")
        lines.append(f"- FULL count: {fa['count']}/{d['n_bars']}")
        lines.append(f"- FULL clusters: {fa['clusters']}")
        lines.append(f"- Max cluster size: {fa['max_cluster']}")
        lines.append(f"- Isolated (single-bar) FULLs: {fa['isolated']}")
        lines.append(f"- FULL->CASH transitions: {d['full_then_cash']}")
        lines.append("")

    lines += [
        "### FULL-Volatility Coincidence Check",
        "",
        "Does FULL appear when Volatility is opposing (veto condition)?",
        "",
    ]
    for r in results:
        ds = r["dataset"]
        d = r["configs"]["D: Combined v2.1"]
        lines.append(
            f"- **{ds}**: FULL->CASH transitions = {d['full_then_cash']} "
            f"({'CLEAN' if d['full_then_cash'] == 0 else 'NEEDS REVIEW'})"
        )

    lines += [
        "",
        "### CASH Frequency Band",
        "",
    ]
    for r in results:
        ds = r["dataset"]
        baseline_cash = r["configs"]["A: Baseline"]["directives"]["CASH"]
        combined_cash = r["configs"]["D: Combined v2.1"]["directives"]["CASH"]
        baseline_pct = baseline_cash / r["n_bars"] * 100
        combined_pct = combined_cash / r["n_bars"] * 100
        lines.append(
            f"- **{ds}**: Baseline CASH={baseline_cash} ({baseline_pct:.1f}%), "
            f"Combined CASH={combined_cash} ({combined_pct:.1f}%)"
        )

    # Final verdict
    lines += [
        "",
        "## Verdict",
        "",
    ]
    for r in results:
        ds = r["dataset"]
        d = r["configs"]["D: Combined v2.1"]
        a = r["configs"]["A: Baseline"]
        fa = d["full_analysis"]

        full_appears = d["directives"]["FULL"] > 0
        cash_reasonable = d["directives"]["CASH"] <= a["directives"]["CASH"]
        no_isolated = fa["isolated"] <= fa["count"] * 0.1  # <10% isolated
        no_full_cash = d["full_then_cash"] == 0

        checks = [
            ("FULL appears", full_appears),
            ("CASH within baseline band", cash_reasonable),
            ("FULL clusters (not isolated spikes)", no_isolated or fa["clusters"] <= 3),
            ("No FULL->CASH transitions", no_full_cash),
        ]

        passed = sum(1 for _, ok in checks if ok)
        total = len(checks)

        lines.append(f"### {ds}")
        for label, ok in checks:
            mark = "PASS" if ok else "FAIL"
            lines.append(f"- [{mark}] {label}")
        lines.append(f"**Result**: {passed}/{total} checks passed")
        lines.append("")

    lines += [
        "### Overall Interpretation",
        "",
        "If Config D passes all safety checks, the v2.1 semantics are validated",
        "for promotion to production code (subject to user approval).",
        "",
        "If Config D fails safety checks, the semantics need refinement before",
        "any production code modification.",
        "",
    ]

    return "\n".join(lines)


def main() -> None:
    print("=" * 60)
    print("  COMBINED SEMANTICS EXPERIMENT — Phase 8.6")
    print("=" * 60)

    results = []
    for name, path in DATASETS.items():
        full_path = Path(_root) / path
        if not full_path.exists():
            print(f"\n[SKIP] {name}: not found")
            continue

        print(f"\n[EXPERIMENT] {name} ...", end=" ", flush=True)
        r = run_experiment(name, str(full_path))
        results.append(r)

        d = r["configs"]["D: Combined v2.1"]
        a = r["configs"]["A: Baseline"]
        print(f"done.")
        print(f"  A (Baseline): FULL={a['directives']['FULL']}, CASH={a['directives']['CASH']}")
        print(f"  D (Combined): FULL={d['directives']['FULL']}, CASH={d['directives']['CASH']}")
        print(f"  D FULL clusters: {d['full_analysis']['clusters']}, "
              f"max={d['full_analysis']['max_cluster']}, "
              f"FULL->CASH: {d['full_then_cash']}")

    if not results:
        print("\n[ERROR] No datasets found")
        return

    report = format_report(results)
    out_path = Path(_root) / "docs" / "18_combined_semantics_results.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"\n[REPORT] {out_path}")

    # Print verdict
    print("\n" + "=" * 60)
    print("  VERDICT")
    print("=" * 60)
    for r in results:
        ds = r["dataset"]
        d = r["configs"]["D: Combined v2.1"]
        a = r["configs"]["A: Baseline"]
        fa = d["full_analysis"]
        print(f"\n  {ds}:")
        print(f"    FULL: {a['directives']['FULL']} (baseline) -> {d['directives']['FULL']} (v2.1)")
        print(f"    CASH: {a['directives']['CASH']} (baseline) -> {d['directives']['CASH']} (v2.1)")
        print(f"    FULL clusters: {fa['clusters']}, max_size: {fa['max_cluster']}")
        print(f"    FULL->CASH: {d['full_then_cash']}")


if __name__ == "__main__":
    main()