#!/usr/bin/env python
"""Phase 21: Master Report Generator.

Combines all analysis outputs into a single Phase 21 portfolio analysis report.

Usage:
    python scripts/generate_phase21_report.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

REPORTS_DIR = Path("reports/portfolio")
OUTPUT_MD = Path("reports/phase21_portfolio_analysis.md")
OUTPUT_JSON = Path("reports/phase21_portfolio_analysis.json")


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def generate_markdown(attribution: dict, matrix: dict, stress: dict, summary: dict) -> str:
    """Generate the Phase 21 markdown report."""
    lines: list[str] = []

    lines.append("# Phase 21 — Portfolio-Level Analysis & Attribution")
    lines.append("")
    lines.append(f"**Generated**: {datetime.now().isoformat()}")
    lines.append(f"**Profile**: intraday_default (1H HTF — matches native data timeframe)")
    lines.append("")

    # --- Scope ---
    lines.append("## 1. Scope & Boundaries")
    lines.append("")
    lines.append("**What was analyzed:**")
    lines.append("- STRUCTURAL_FRACTAL (simple_breakout_v1) — execution-validated")
    lines.append("- MEAN_REVERSION (amt_value_reversion_v1) — execution-validated")
    lines.append("- Assets: BTC, SPY, TSLA on 1H data")
    lines.append("- Profile: intraday_default (1H HTF matches data)")
    lines.append("")
    lines.append("**What was excluded and why:**")
    lines.append("- LIQUIDITY_SMC: No execution-validated strategy in backtest engine")
    lines.append("- Scalping/position_macro profiles: Timeframe mismatch would contaminate attribution")
    lines.append("- Pullback continuation, SMA crossover, RSI mean reversion, VWAP reversion, stop-run fade: Not validated in Python execution engine")
    lines.append("")
    lines.append("**Boundary rules (addendum):**")
    lines.append("- Primary analysis set: execution-validated strategies only")
    lines.append("- Additional strategies included only as diagnostic, not decisive")
    lines.append("- Low-frequency family rule: No inference from cells with < 5 trades")
    lines.append("- No implicit remediation: Underperformance documented, not corrected")
    lines.append("")

    # --- Family Attribution ---
    lines.append("## 2. Family Attribution")
    lines.append("")
    if attribution:
        combined = attribution.get("combined", {})
        lines.append("| Family | PnL | Trades | Win Rate | Avg R | Sample |")
        lines.append("|--------|-----|--------|----------|-------|--------|")
        for fam in ["STRUCTURAL_FRACTAL", "MEAN_REVERSION"]:
            cs = combined.get(fam, {})
            lines.append(
                f"| {fam} | ${cs.get('pnl', 0):,.2f} | {cs.get('trades', 0)} "
                f"| {cs.get('win_rate', 0):.1%} | {cs.get('avg_r', 0):.4f} "
                f"| {cs.get('inference_note', 'N/A')} |"
            )
        lines.append("")

        # Per-asset breakdown
        per_asset = attribution.get("per_asset", {})
        if per_asset:
            lines.append("### Per-Asset Breakdown")
            lines.append("")
            for asset, stats in per_asset.items():
                lines.append(f"**{asset}:**")
                for fam in ["STRUCTURAL_FRACTAL", "MEAN_REVERSION"]:
                    fs = stats.get(fam, {})
                    if fs.get("trades", 0) > 0:
                        lines.append(
                            f"  - {fam}: ${fs['pnl']:,.2f} "
                            f"({fs['trades']} trades, {fs.get('win_rate', 0):.1%} win rate)"
                        )
                    else:
                        lines.append(f"  - {fam}: No trades")
                lines.append("")

    # --- Regime × Family Matrix ---
    lines.append("## 3. Regime × Family Matrix")
    lines.append("")
    if matrix:
        combined_matrix = matrix.get("combined_matrix", {})
        lines.append("| Regime | Family | Trades | Win Rate | Avg R | PnL | Sample |")
        lines.append("|--------|--------|--------|----------|-------|-----|--------|")
        for regime in ["trending", "ranging", "volatile"]:
            for family in ["STRUCTURAL_FRACTAL", "MEAN_REVERSION"]:
                cell = combined_matrix.get(regime, {}).get(family, {})
                lines.append(
                    f"| {regime} | {family} | {cell.get('trades', 0)} "
                    f"| {cell.get('win_rate', 0):.1%} | {cell.get('avg_r', 0):.4f} "
                    f"| ${cell.get('pnl', 0):,.2f} | {cell.get('label', 'N/A')} |"
                )
        lines.append("")

    # --- Stress Analysis ---
    lines.append("## 4. Stress & Correlation Analysis")
    lines.append("")
    if stress:
        per_asset_stress = stress.get("per_asset", {})
        for asset, data in per_asset_stress.items():
            lines.append(f"### {asset}")
            lines.append(f"- Total PnL: ${data.get('total_pnl', 0):,.2f}")
            corr = data.get("loss_correlation", {})
            lines.append(f"- Loss correlation: {corr.get('correlation_note', 'N/A')}")
            worst = data.get("worst_drawdowns", [])
            if worst:
                w = worst[0]
                lines.append(f"- Worst drawdown: {w.get('drawdown_pct', 0):.1%} over {w.get('duration_bars', 0)} bars")
                la = w.get("loss_attribution", {})
                if la.get("losses_by_family"):
                    lines.append(f"  - Losses by family: {la['losses_by_family']}")
            lines.append("")

    # --- Gaps ---
    lines.append("## 5. Documented Gaps")
    lines.append("")
    lines.append("| Gap | Reason | Future Phase |")
    lines.append("|-----|--------|-------------|")
    lines.append("| LIQUIDITY_SMC not in attribution | No execution-validated strategy | Phase 20.5 (integration) |")
    lines.append("| Profile sensitivity not analyzed | Only intraday_default matches 1H data | Phase 22 |")
    lines.append("| Scalping/position_macro skipped | Timeframe mismatch | Phase 22 |")
    lines.append("| ETH not included | No historical data | Data acquisition |")
    lines.append("")

    # --- Next Steps ---
    lines.append("## 6. Next Phase")
    lines.append("")
    lines.append("Capital Allocation & Risk Budgeting — using attribution insights to inform position sizing and portfolio construction.")
    lines.append("")

    return "\n".join(lines)


def generate() -> None:
    """Generate the master Phase 21 report."""
    attribution = load_json(REPORTS_DIR / "family_attribution.json")
    matrix = load_json(REPORTS_DIR / "regime_family_matrix.json")
    stress = load_json(REPORTS_DIR / "stress_analysis.json")
    summary = load_json(REPORTS_DIR / "summary.json")

    if not any([attribution, matrix, stress, summary]):
        print("Error: No analysis results found. Run analysis scripts first.")
        sys.exit(1)

    # Generate markdown
    md_content = generate_markdown(attribution, matrix, stress, summary)
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_MD, "w") as f:
        f.write(md_content)
    print(f"Markdown report saved: {OUTPUT_MD}")

    # Generate JSON
    json_output = {
        "generated_at": datetime.now().isoformat(),
        "profile": "intraday_default",
        "attribution": attribution,
        "regime_family_matrix": matrix,
        "stress_analysis": stress,
        "summary": summary,
    }
    with open(OUTPUT_JSON, "w") as f:
        json.dump(json_output, f, indent=2)
    print(f"JSON report saved: {OUTPUT_JSON}")


if __name__ == "__main__":
    generate()
