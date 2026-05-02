"""Confidence Contribution Audit — Phase 8.5, Step 1.

Measurement only. Proves whether total_confidence >= 0.50 is
mathematically reachable under the current aggregation model.

No production code modified. Shadow-only diagnostic.
"""

from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path

# Ensure project root on path
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

MIN_BARS = 52  # Ichimoku requirement


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


def run_audit(dataset_name: str, csv_path: str) -> dict:
    bars = load_csv(csv_path)
    n_bars = len(bars)

    agents = [
        IchimokuAgent(),
        VolatilityAgent(),
        AMTAgent(),
        WyckoffAgent(),
    ]
    agent_names = [a.name for a in agents]
    n_agents = len(agents)

    # Per-bar records
    bar_confidences: dict[str, list[float]] = {name: [] for name in agent_names}
    bar_means: list[float] = []

    # Per-bar detail for correlation and shortfall analysis
    bar_records: list[dict[str, float]] = []

    for i in range(MIN_BARS, n_bars):
        window = bars[i - MIN_BARS : i + 1]
        state = MarketState(
            bars=window,
            regime=Regime.RANGING,
            regime_confidence=0.5,
            volatility=None,
            timestamp=window[-1].timestamp,
        )

        confidences = {}
        for agent in agents:
            out = agent.run(state)
            confidences[agent.name] = out.confidence
            bar_confidences[agent.name].append(out.confidence)

        mean_conf = sum(confidences.values()) / n_agents
        bar_means.append(mean_conf)
        bar_records.append(confidences)

    # --- Aggregate Statistics ---

    # Per-agent stats
    agent_stats = {}
    for name in agent_names:
        vals = bar_confidences[name]
        agent_stats[name] = {
            "mean": statistics.mean(vals),
            "median": statistics.median(vals),
            "stdev": statistics.stdev(vals) if len(vals) >= 2 else 0.0,
            "min": min(vals),
            "max": max(vals),
            **compute_percentiles(vals),
        }

    # Mean confidence stats
    mean_stats = {
        "mean": statistics.mean(bar_means),
        "median": statistics.median(bar_means),
        "stdev": statistics.stdev(bar_means) if len(bar_means) >= 2 else 0.0,
        "min": min(bar_means),
        "max": max(bar_means),
        **compute_percentiles(bar_means),
    }

    # Count bars where mean >= 0.50
    bars_above_50 = sum(1 for m in bar_means if m >= 0.50)
    bars_above_45 = sum(1 for m in bar_means if m >= 0.45)
    bars_above_40 = sum(1 for m in bar_means if m >= 0.40)

    # Per-agent shortfall contribution
    # For each bar: shortfall = 0.50 - mean
    # Agent contribution = (0.50 - agent_confidence) / n_agents
    shortfall_by_agent = {name: 0.0 for name in agent_names}
    for rec in bar_records:
        for name in agent_names:
            shortfall_by_agent[name] += max(0, (0.50 - rec[name])) / n_agents
    avg_shortfall = {name: shortfall_by_agent[name] / len(bar_records) for name in agent_names}

    # Confidence correlation matrix (Pearson)
    correlation = {}
    for n1 in agent_names:
        for n2 in agent_names:
            if n1 == n2:
                correlation[f"{n1}:{n2}"] = 1.0
            else:
                v1 = bar_confidences[n1]
                v2 = bar_confidences[n2]
                m1 = statistics.mean(v1)
                m2 = statistics.mean(v2)
                s1 = statistics.stdev(v1) if len(v1) >= 2 else 0.0
                s2 = statistics.stdev(v2) if len(v2) >= 2 else 0.0
                if s1 > 0 and s2 > 0:
                    cov = statistics.mean((a - m1) * (b - m2) for a, b in zip(v1, v2))
                    corr = cov / (s1 * s2)
                else:
                    corr = 0.0
                correlation[f"{n1}:{n2}"] = corr

    # Confidence distribution per agent (histogram buckets)
    buckets = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    distributions = {}
    for name in agent_names:
        dist = {}
        for b_idx in range(len(buckets) - 1):
            lo, hi = buckets[b_idx], buckets[b_idx + 1]
            count = sum(1 for v in bar_confidences[name] if lo <= v < hi)
            dist[f"[{lo:.1f},{hi:.1f})"] = count
        # Include 1.0 in last bucket
        dist[f"[{buckets[-2]:.1f},{buckets[-1]:.1f}]"] = dist.pop(f"[{buckets[-2]:.1f},{buckets[-1]:.1f})")
        dist[f"[{buckets[-2]:.1f},{buckets[-1]:.1f}]"] += sum(1 for v in bar_confidences[name] if v == 1.0)
        distributions[name] = dist

    return {
        "dataset": dataset_name,
        "n_bars_audited": len(bar_means),
        "agent_stats": agent_stats,
        "mean_confidence_stats": mean_stats,
        "bars_above_threshold": {
            ">= 0.40": bars_above_40,
            ">= 0.45": bars_above_45,
            ">= 0.50": bars_above_50,
        },
        "avg_shortfall_by_agent": avg_shortfall,
        "correlation": correlation,
        "distributions": distributions,
    }


def format_report(results: list[dict]) -> str:
    lines = [
        "# Confidence Contribution Audit — Phase 8.5, Step 1",
        "",
        "**Date**: 2026-04-29",
        "**Status**: Measurement only — no code modified",
        "",
        "## Objective",
        "",
        "Determine whether `total_confidence >= 0.50` (R-02 gate) is",
        "mathematically reachable under the current aggregation model:",
        "",
        "```",
        "total_confidence = mean(all agent confidences)",
        "```",
        "",
        "---",
        "",
    ]

    for r in results:
        ds = r["dataset"]
        lines += [
            f"## {ds} ({r['n_bars_audited']} bars audited)",
            "",
            "### Per-Agent Confidence Statistics",
            "",
            "| Agent | Mean | Median | StDev | Min | Max | p25 | p50 | p75 | p90 | p95 |",
            "|-------|------|--------|-------|-----|-----|-----|-----|-----|-----|-----|",
        ]
        for name, stats in r["agent_stats"].items():
            lines.append(
                f"| {name} "
                f"| {stats['mean']:.4f} "
                f"| {stats['median']:.4f} "
                f"| {stats['stdev']:.4f} "
                f"| {stats['min']:.4f} "
                f"| {stats['max']:.4f} "
                f"| {stats['p25']:.4f} "
                f"| {stats['p50']:.4f} "
                f"| {stats['p75']:.4f} "
                f"| {stats['p90']:.4f} "
                f"| {stats['p95']:.4f} |"
            )

        lines += [
            "",
            "### Mean Confidence (Composite) Statistics",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Mean | {r['mean_confidence_stats']['mean']:.4f} |",
            f"| Median | {r['mean_confidence_stats']['median']:.4f} |",
            f"| StDev | {r['mean_confidence_stats']['stdev']:.4f} |",
            f"| Min | {r['mean_confidence_stats']['min']:.4f} |",
            f"| Max | {r['mean_confidence_stats']['max']:.4f} |",
            f"| p25 | {r['mean_confidence_stats']['p25']:.4f} |",
            f"| p50 | {r['mean_confidence_stats']['p50']:.4f} |",
            f"| p75 | {r['mean_confidence_stats']['p75']:.4f} |",
            f"| p90 | {r['mean_confidence_stats']['p90']:.4f} |",
            f"| p95 | {r['mean_confidence_stats']['p95']:.4f} |",
            "",
            "### R-02 Threshold Crossing",
            "",
            "| Threshold | Bars | % |",
            "|-----------|------|---|",
        ]
        n = r["n_bars_audited"]
        for label, count in r["bars_above_threshold"].items():
            pct = count / n * 100 if n > 0 else 0
            lines.append(f"| {label} | {count} | {pct:.1f}% |")

        lines += [
            "",
            "### Per-Agent Shortfall Contribution",
            "",
            "Average contribution to R-02 shortfall per agent.",
            "(Higher = agent pulls mean further below 0.50)",
            "",
            "| Agent | Avg Shortfall Contribution |",
            "|-------|---------------------------|",
        ]
        for name, val in r["avg_shortfall_by_agent"].items():
            lines.append(f"| {name} | {val:.4f} |")

        lines += [
            "",
            "### Confidence Correlation Matrix",
            "",
        ]
        agents_list = list(r["agent_stats"].keys())
        header = "| | " + " | ".join(agents_list) + " |"
        sep = "|---" + "|---" * len(agents_list) + "|"
        lines += [header, sep]
        for n1 in agents_list:
            row = f"| {n1} |"
            for n2 in agents_list:
                key = f"{n1}:{n2}"
                val = r["correlation"].get(key, 0.0)
                row += f" {val:.3f} |"
            lines.append(row)

        lines += [
            "",
            "### Confidence Distribution (Bar Counts)",
            "",
        ]
        for name in agents_list:
            dist = r["distributions"][name]
            lines.append(f"**{name}**:")
            lines.append("")
            lines.append("| Bucket | Count |")
            lines.append("|--------|-------|")
            for bucket, count in dist.items():
                lines.append(f"| {bucket} | {count} |")
            lines.append("")

        lines += ["---", ""]

    # Combined analysis
    lines += [
        "## Combined Analysis",
        "",
        "### Key Question: Is mean >= 0.50 reachable?",
        "",
    ]
    for r in results:
        ds = r["dataset"]
        mx = r["mean_confidence_stats"]["max"]
        above = r["bars_above_threshold"][">= 0.50"]
        if above > 0:
            lines.append(f"- **{ds}**: YES — {above} bars reached >= 0.50 (max mean: {mx:.4f})")
        else:
            lines.append(f"- **{ds}**: NO — max mean confidence: {mx:.4f} ({mx/0.50*100:.1f}% of 0.50 threshold)")

    lines += [
        "",
        "### Bottleneck Identification",
        "",
        "The agent with the highest avg shortfall contribution is the primary",
        "bottleneck preventing mean >= 0.50.",
        "",
    ]
    for r in results:
        ds = r["dataset"]
        sorted_shortfall = sorted(r["avg_shortfall_by_agent"].items(), key=lambda x: -x[1])
        top = sorted_shortfall[0]
        lines.append(f"- **{ds}**: Top bottleneck = {top[0]} (avg shortfall: {top[1]:.4f})")

    lines += [
        "",
        "### Interpretation",
        "",
        "If mean never reaches 0.50, the question becomes:",
        "",
        "1. Is this because agent confidence ceilings are individually too low?",
        "2. Or because the arithmetic mean model structurally dilutes high-confidence agents?",
        "",
        "Step 2 (confidence_semantics_experiment.py) tests whether role-aware",
        "aggregation changes the outcome.",
        "",
    ]

    return "\n".join(lines)


def main() -> None:
    print("=" * 60)
    print("  CONFIDENCE CONTRIBUTION AUDIT — Phase 8.5, Step 1")
    print("=" * 60)

    results = []
    for name, path in DATASETS.items():
        full_path = Path(_root) / path
        if not full_path.exists():
            print(f"\n[SKIP] {name}: {full_path} not found")
            continue

        print(f"\n[AUDIT] {name} ...", end=" ", flush=True)
        r = run_audit(name, str(full_path))
        results.append(r)

        mx = r["mean_confidence_stats"]["max"]
        above = r["bars_above_threshold"][">= 0.50"]
        print(f"done. max_mean={mx:.4f}, bars>=0.50={above}/{r['n_bars_audited']}")

    if not results:
        print("\n[ERROR] No datasets found")
        return

    report = format_report(results)
    out_path = Path(_root) / "docs" / "15_confidence_audit_results.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"\n[REPORT] {out_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    for r in results:
        ds = r["dataset"]
        mx = r["mean_confidence_stats"]["max"]
        above = r["bars_above_threshold"][">= 0.50"]
        sorted_shortfall = sorted(r["avg_shortfall_by_agent"].items(), key=lambda x: -x[1])
        top_bottleneck = sorted_shortfall[0]
        print(f"\n  {ds}:")
        print(f"    Max mean confidence: {mx:.4f} ({mx/0.50*100:.1f}% of 0.50)")
        print(f"    Bars >= 0.50: {above}/{r['n_bars_audited']}")
        print(f"    Top bottleneck: {top_bottleneck[0]} (shortfall: {top_bottleneck[1]:.4f})")


if __name__ == "__main__":
    main()