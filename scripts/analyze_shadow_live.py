"""Phase 14: Analyze shadow live run results.

Reads the CSV log produced by run_shadow_live.py and produces a structured report
covering directive distribution, confidence behavior, FTMO compliance, and
drawdown ladder stage transitions.

Usage:
    python scripts/analyze_shadow_live.py logs/shadow_live_20260501.csv
    python scripts/analyze_shadow_live.py logs/shadow_live_20260501.csv --output reports/shadow_live_analysis.json
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import statistics
import sys
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

logger = logging.getLogger("analyze_shadow_live")


def load_log(csv_path: str) -> list[dict]:
    """Load shadow live log CSV into list of dicts."""
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def compute_directive_distribution(rows: list[dict]) -> dict[str, float]:
    """Compute directive distribution as percentages."""
    directives = [r.get("directive", "UNKNOWN") for r in rows]
    total = len(directives)
    if total == 0:
        return {}
    counts = {}
    for d in directives:
        counts[d] = counts.get(d, 0) + 1
    return {d: round(c / total * 100, 1) for d, c in sorted(counts.items())}


def compute_confidence_distribution(rows: list[dict]) -> dict[str, float]:
    """Compute confidence percentiles."""
    confidences = []
    for r in rows:
        try:
            c = float(r.get("confidence", 0))
            if c > 0:
                confidences.append(c)
        except (ValueError, TypeError):
            pass
    if not confidences:
        return {"p10": 0, "p25": 0, "p50": 0, "p75": 0, "p90": 0, "mean": 0, "std": 0}

    confidences.sort()
    n = len(confidences)

    def percentile(p: float) -> float:
        idx = int(p * n)
        idx = min(idx, n - 1)
        return confidences[idx]

    return {
        "p10": round(percentile(0.10), 6),
        "p25": round(percentile(0.25), 6),
        "p50": round(percentile(0.50), 6),
        "p75": round(percentile(0.75), 6),
        "p90": round(percentile(0.90), 6),
        "mean": round(statistics.mean(confidences), 6),
        "std": round(statistics.stdev(confidences), 6) if len(confidences) > 1 else 0.0,
    }


def compute_composite_distribution(rows: list[dict]) -> dict[str, float]:
    """Compute composite score percentiles."""
    scores = []
    for r in rows:
        try:
            s = float(r.get("composite_score", 0))
            scores.append(s)
        except (ValueError, TypeError):
            pass
    if not scores:
        return {"p10": 0, "p50": 0, "p90": 0, "mean": 0}

    scores.sort()
    n = len(scores)

    def percentile(p: float) -> float:
        idx = int(p * n)
        idx = min(idx, n - 1)
        return scores[idx]

    return {
        "p10": round(percentile(0.10), 6),
        "p50": round(percentile(0.50), 6),
        "p90": round(percentile(0.90), 6),
        "mean": round(statistics.mean(scores), 6),
    }


def detect_oscillation(rows: list[dict]) -> int:
    """Count FULL<->CASH reversals (should be zero)."""
    count = 0
    prev = None
    for r in rows:
        d = r.get("directive")
        if prev == "FULL" and d == "CASH":
            count += 1
        elif prev == "CASH" and d == "FULL":
            count += 1
        prev = d
    return count


def compute_directive_streaks(rows: list[dict]) -> dict[str, dict]:
    """Compute max and average streak lengths for each directive."""
    streaks: dict[str, list[int]] = {}
    current_streak: dict[str, int] = {}

    for r in rows:
        d = r.get("directive", "UNKNOWN")
        for key in list(current_streak.keys()):
            if key != d:
                if current_streak[key] > 0:
                    streaks.setdefault(key, []).append(current_streak[key])
                current_streak[key] = 0
        current_streak[d] = current_streak.get(d, 0) + 1

    # Flush remaining
    for key, val in current_streak.items():
        if val > 0:
            streaks.setdefault(key, []).append(val)

    result = {}
    for key, vals in streaks.items():
        result[key] = {
            "max": max(vals),
            "mean": round(statistics.mean(vals), 1) if vals else 0,
            "count": len(vals),
        }
    return result


def compute_dd_stage_distribution(rows: list[dict]) -> dict[str, float]:
    """Compute drawdown stage distribution."""
    stages = [r.get("dd_stage", "UNKNOWN") for r in rows]
    total = len(stages)
    if total == 0:
        return {}
    counts = {}
    for s in stages:
        counts[s] = counts.get(s, 0) + 1
    return {s: round(c / total * 100, 1) for s, c in sorted(counts.items())}


def compute_ftmo_compliance(rows: list[dict]) -> dict:
    """Compute FTMO compliance statistics."""
    total = len(rows)
    compliant_count = sum(1 for r in rows if r.get("ftmo_compliant", "True") == "True")
    halt_count = sum(1 for r in rows if r.get("ftmo_action") == "HALT")
    reduce_count = sum(1 for r in rows if r.get("ftmo_action") == "REDUCE")

    return {
        "total_bars": total,
        "compliant_bars": compliant_count,
        "compliance_pct": round(compliant_count / total * 100, 1) if total > 0 else 0,
        "halt_events": halt_count,
        "reduce_events": reduce_count,
    }


def compute_directive_transitions(rows: list[dict]) -> int:
    """Count number of directive transitions."""
    transitions = 0
    prev = None
    for r in rows:
        d = r.get("directive")
        if prev is not None and d != prev:
            transitions += 1
        prev = d
    return transitions


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Phase 14 shadow live run")
    parser.add_argument("csv_path", help="Path to shadow live log CSV")
    parser.add_argument("--output", default=None, help="Output JSON path (default: same dir as CSV)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    csv_path = args.csv_path
    if not Path(csv_path).is_absolute():
        csv_path = str(Path(_root) / csv_path)

    logger.info("Loading log: %s", csv_path)
    rows = load_log(csv_path)
    logger.info("Loaded %d rows", len(rows))

    # --- Directive Distribution ---
    directive_dist = compute_directive_distribution(rows)
    logger.info("=== DIRECTIVE DISTRIBUTION ===")
    for d, pct in directive_dist.items():
        logger.info("  %s: %.1f%%", d, pct)

    # --- Confidence Distribution ---
    conf_dist = compute_confidence_distribution(rows)
    logger.info("=== CONFIDENCE DISTRIBUTION ===")
    for k, v in conf_dist.items():
        logger.info("  %s: %.6f", k, v)

    # --- Composite Distribution ---
    comp_dist = compute_composite_distribution(rows)
    logger.info("=== COMPOSITE SCORE DISTRIBUTION ===")
    for k, v in comp_dist.items():
        logger.info("  %s: %.6f", k, v)

    # --- Oscillation Check ---
    oscillations = detect_oscillation(rows)
    logger.info("=== OSCILLATION CHECK ===")
    logger.info("  FULL<->CASH reversals: %d", oscillations)
    if oscillations > 0:
        logger.warning("  WARNING: Oscillation detected — expected 0")
    else:
        logger.info("  OK: No oscillation")

    # --- Directive Streaks ---
    streaks = compute_directive_streaks(rows)
    logger.info("=== DIRECTIVE STREAKS ===")
    for directive, stats in streaks.items():
        logger.info("  %s: max=%d, mean=%.1f, count=%d",
                     directive, stats["max"], stats["mean"], stats["count"])

    # --- DD Stage Distribution ---
    dd_dist = compute_dd_stage_distribution(rows)
    logger.info("=== DRAWDOWN STAGE DISTRIBUTION ===")
    for stage, pct in dd_dist.items():
        logger.info("  %s: %.1f%%", stage, pct)

    # --- FTMO Compliance ---
    ftmo = compute_ftmo_compliance(rows)
    logger.info("=== FTMO COMPLIANCE ===")
    logger.info("  Compliant: %d/%d (%.1f%%)", ftmo["compliant_bars"], ftmo["total_bars"], ftmo["compliance_pct"])
    logger.info("  HALT events: %d", ftmo["halt_events"])
    logger.info("  REDUCE events: %d", ftmo["reduce_events"])

    # --- Directive Transitions ---
    transitions = compute_directive_transitions(rows)
    logger.info("=== DIRECTIVE TRANSITIONS ===")
    logger.info("  Total transitions: %d", transitions)

    # --- Summary ---
    total_bars = len(rows)
    first_ts = rows[0].get("timestamp", "?") if rows else "?"
    last_ts = rows[-1].get("timestamp", "?") if rows else "?"

    logger.info("=== RUN SUMMARY ===")
    logger.info("  Total bars: %d", total_bars)
    logger.info("  Time range: %s -> %s", first_ts[:19], last_ts[:19])

    # --- Acceptance Criteria ---
    logger.info("=== ACCEPTANCE CRITERIA ===")
    checks = [
        ("No directive oscillation", oscillations == 0),
        ("CASH remains rare (<5%)", directive_dist.get("CASH", 0) < 5.0),
        ("FTMO compliance >95%", ftmo["compliance_pct"] > 95),
        ("No HALT events", ftmo["halt_events"] == 0),
        ("Confidence p90 - p25 < 0.2", conf_dist["p90"] - conf_dist["p25"] < 0.2),
        ("At least 100 bars processed", total_bars >= 100),
    ]
    all_pass = True
    for name, passed in checks:
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        logger.info("  [%s] %s", status, name)

    if all_pass:
        logger.info("=== ALL ACCEPTANCE CRITERIA MET ===")
    else:
        logger.warning("=== SOME CRITERIA FAILED — DIAGNOSE ===")

    # --- Write structured report ---
    report = {
        "dataset": csv_path,
        "total_bars": total_bars,
        "time_range": {"first": first_ts, "last": last_ts},
        "directive_distribution": directive_dist,
        "confidence_distribution": conf_dist,
        "composite_distribution": comp_dist,
        "oscillations": oscillations,
        "directive_streaks": streaks,
        "dd_stage_distribution": dd_dist,
        "ftmo_compliance": ftmo,
        "directive_transitions": transitions,
        "acceptance": {name: passed for name, passed in checks},
        "all_pass": all_pass,
    }

    if args.output:
        report_path = Path(args.output)
    else:
        report_path = Path(csv_path).with_suffix(".analysis.json")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Report saved: %s", report_path)


if __name__ == "__main__":
    main()
