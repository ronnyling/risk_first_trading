"""Generate Phase 18 metadata JSON from frozen source-of-truth modules.

Phase 18: Reflection only. No logic. No trading decisions.

This script reads frozen modules and emits a JSON metadata file
that the HTML guide renders. The JSON is the ONLY contract between
Python and HTML.

SAFETY CONSTRAINTS:
- No conditional trading logic
- No new classes or abstractions
- No imports of engine, execution, market, hermes internals
- Deterministic output (same source = same JSON, modulo timestamp)
- Hash detection for staleness (not enforcement)
"""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Frozen source-of-truth imports (READ-ONLY)
# ---------------------------------------------------------------------------
from src.profiles.presets import PRESETS, list_preset_ids
from src.policy.strategy_family_policy import StrategyFamily, StrategyFamilyPolicy
from src.orchestration.family_orchestrator import FAMILY_PRIORITY
from src.policy.mtf_alignment_policy import _ALIGNMENT_MATRIX

# Paths to frozen source files (for hash computation)
_SOURCE_FILES: list[Path] = [
    Path("src/profiles/schema.py"),
    Path("src/profiles/presets.py"),
    Path("src/policy/strategy_family_policy.py"),
    Path("src/orchestration/family_orchestrator.py"),
    Path("src/policy/mtf_alignment_policy.py"),
]

_CONFIG_FILES: list[Path] = [
    Path("config/risk_limits.yaml"),
    Path("config/strategies.yaml"),
]


# ---------------------------------------------------------------------------
# Human-readable descriptions (static strings, not derived from logic)
# ---------------------------------------------------------------------------

_FAMILY_DESCRIPTIONS: dict[str, str] = {
    "structural_fractal": (
        "Trend-following strategies that exploit structural breakouts, "
        "fractal patterns, and directional momentum."
    ),
    "mean_reversion": (
        "Range-bound strategies that exploit mean-reversion signals, "
        "RSI extremes, and Bollinger band bounces."
    ),
    "liquidity_smc": (
        "Smart Money Concepts (SMC) strategies that exploit liquidity "
        "sweeps, order blocks, and institutional footprints."
    ),
    "chaos_optional": (
        "Chaos-theory strategies (permission gate only). "
        "Activated during volatile regimes when explicitly enabled."
    ),
}

_FAMILY_LABELS: dict[str, str] = {
    "structural_fractal": "Structural Fractal",
    "mean_reversion": "Mean Reversion",
    "liquidity_smc": "Liquidity / SMC",
    "chaos_optional": "Chaos (Optional)",
}

_REGIME_LABELS: dict[str, str] = {
    "TRENDING": "Trending — directional momentum",
    "RANGING": "Ranging — range-bound conditions",
    "VOLATILE": "Volatile — high uncertainty",
}

_DIRECTIVE_LABELS: dict[str, str] = {
    "FULL": "Full Risk",
    "SCALE_DOWN": "Scale Down",
    "CASH": "Cash (No Trades)",
}

_MTF_STATE_DESCRIPTIONS: dict[str, str] = {
    "ALIGNED": "HTF and LTF agree — full risk allowed",
    "MISALIGNED": "HTF and LTF disagree — risk dampened by 50%",
    "NEUTRAL": "No dampening applied (volatile HTF or CASH)",
}


# ---------------------------------------------------------------------------
# Helper: compute source hash
# ---------------------------------------------------------------------------

def _compute_source_hash() -> str:
    """Compute SHA-256 of all source + config files for staleness detection."""
    h = hashlib.sha256()
    for path in _SOURCE_FILES + _CONFIG_FILES:
        if path.exists():
            h.update(path.read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Metadata extraction (pure data extraction, no logic)
# ---------------------------------------------------------------------------

def _extract_profiles() -> dict:
    """Extract profile metadata from PRESETS dict."""
    profiles = {}
    for preset_id in list_preset_ids():
        preset = PRESETS[preset_id]
        tf = preset["timeframes"]
        risk = preset["risk"]
        mtf = preset["mtf"]
        fam = preset["families"]

        # execution_tf: tuple from presets, list in JSON
        exec_tf = list(tf["execution_tf"])

        profiles[preset_id] = {
            "profile_id": preset_id,
            "description": preset["description"],
            "timeframes": {
                "hermes_htf": tf["hermes_htf"],
                "mtf_ltf": tf["mtf_ltf"],
                "execution_tf": exec_tf,
            },
            "risk": {
                "base_risk": risk["base_risk"],
                "base_risk_pct": round(risk["base_risk"] * 100, 2),
                "max_portfolio_risk": risk["max_portfolio_risk"],
                "max_portfolio_risk_pct": round(risk["max_portfolio_risk"] * 100, 1),
            },
            "mtf": {
                "inertia_bars": mtf["inertia_bars"],
                "volatility_floor_pct": mtf["volatility_floor_pct"],
            },
            "families": {
                "structural_fractal": fam["structural_fractal"],
                "mean_reversion": fam["mean_reversion"],
                "liquidity_smc": fam["liquidity_smc"],
                "chaos_optional": fam["chaos_optional"],
            },
        }
    return profiles


def _extract_strategy_families() -> dict:
    """Extract strategy family metadata from frozen enums and policy."""
    # Enum values
    enum_values = []
    for member in StrategyFamily:
        enum_values.append({
            "id": member.value,
            "label": _FAMILY_LABELS.get(member.value, member.value),
            "description": _FAMILY_DESCRIPTIONS.get(member.value, ""),
        })

    # Permission matrix — extract from frozen PERMISSION_MATRIX
    permission_matrix = {}
    policy = StrategyFamilyPolicy()
    for (regime, directive), families in policy.PERMISSION_MATRIX.items():
        key = f"{regime}_{directive}"
        permission_matrix[key] = [f.value for f in families]

    # Orchestrator priority
    orchestrator_priority = [f.value for f in FAMILY_PRIORITY]

    return {
        "enum_values": enum_values,
        "permission_matrix": permission_matrix,
        "orchestrator_priority": orchestrator_priority,
    }


def _extract_mtf_alignment() -> dict:
    """Extract MTF alignment metadata from frozen alignment matrix."""
    matrix = {}
    for (htf, ltf), (state, factor) in _ALIGNMENT_MATRIX.items():
        key = f"{htf}_{ltf}"
        matrix[key] = {
            "state": state,
            "risk_factor": factor,
            "state_description": _MTF_STATE_DESCRIPTIONS.get(state, ""),
        }

    return {
        "states": ["ALIGNED", "MISALIGNED", "NEUTRAL"],
        "matrix": matrix,
        "rules": {
            "inertia_description": (
                "MISALIGNED state only activates after K consecutive "
                "misaligned LTF bars. If misalignment persists for fewer "
                "than K bars, it is treated as NEUTRAL."
            ),
            "dampening_description": (
                "MTF may only dampen risk (factor <= 1.0). "
                "MTF never increases risk above the Hermes level."
            ),
            "trade_generation": (
                "MTF never generates trades. Only Hermes + Policy can "
                "enable strategy families."
            ),
            "never_does": [
                "Generate entry or exit signals",
                "Increase risk above Hermes level",
                "Override regime classification",
                "Activate strategies directly",
            ],
        },
        "state_descriptions": _MTF_STATE_DESCRIPTIONS,
        "regime_labels": _REGIME_LABELS,
        "directive_labels": _DIRECTIVE_LABELS,
    }


def _extract_risk_limits() -> dict:
    """Extract hard risk limits from frozen config/risk_limits.yaml."""
    path = Path("config/risk_limits.yaml")
    if not path.exists():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f)
    # Remove governance header comments (already parsed by yaml)
    return {
        "max_leverage": data.get("max_leverage", 1.0),
        "max_drawdown_pct": data.get("max_drawdown_pct", 0.20),
        "max_allocation_per_strategy_pct": data.get("max_allocation_per_strategy_pct", 0.40),
        "max_total_exposure_pct": data.get("max_total_exposure_pct", 0.90),
        "kill_switch_drawdown_pct": data.get("kill_switch_drawdown_pct", 0.25),
        "cooldown_bars_after_kill": data.get("cooldown_bars_after_kill", 100),
    }


def _extract_strategies() -> dict:
    """Extract registered strategies from config/strategies.yaml."""
    path = Path("config/strategies.yaml")
    if not path.exists():
        return {"registered": []}

    with open(path) as f:
        data = yaml.safe_load(f)

    # Map strategy style to family (static mapping, not logic)
    STYLE_TO_FAMILY: dict[str, str] = {
        "trend": "structural_fractal",
        "mean_reversion": "mean_reversion",
        "breakout": "liquidity_smc",
    }

    registered = []
    for entry in data.get("strategies", []):
        # Read strategy metadata from module (if importable)
        style = "unknown"
        timeframe = "unknown"
        description = ""
        try:
            import importlib
            module = importlib.import_module(entry["module"])
            cls = getattr(module, entry["class"])
            # Create a temporary instance to read metadata
            params = entry.get("params", {})
            instance = cls(**params)
            meta = instance.metadata
            style = meta.style
            timeframe = meta.timeframe
            description = (
                f"{meta.style.replace('_', ' ').title()} strategy "
                f"on {meta.timeframe} timeframe"
            )
        except Exception:
            # If import fails, use config data
            description = f"Strategy {entry.get('id', '?')}"

        family = STYLE_TO_FAMILY.get(style, "unknown")

        registered.append({
            "id": entry.get("id", "unknown"),
            "module": entry.get("module", ""),
            "class": entry.get("class", ""),
            "family": family,
            "style": style,
            "timeframe": timeframe,
            "description": description,
        })

    return {"registered": registered}


def _extract_guardrails() -> dict:
    """Static guardrail strings. No logic derivation."""
    return {
        "system_will": [
            "Classify market regime (trending / ranging / volatile / cash)",
            "Dampen risk when HTF and LTF regimes are misaligned",
            "Enforce family exclusivity (one family per asset per bar)",
            "Apply priority ordering: structural > mean_reversion > liquidity > chaos",
            "Enforce hard risk limits (drawdown, exposure, kill switch)",
            "Generate TradingView-ready YAML configs",
            "Dampen risk by factor 0.5x when regimes disagree",
            "Reset inertia counter when alignment restores",
        ],
        "system_will_not": [
            "Repaint signals - entries are fixed at bar close",
            "Force trades when no family is allowed",
            "Promote risk above Hermes sizing",
            "Infer trading style from price action",
            "Override risk layer kill switch",
            "Execute strategies outside their declared timeframe",
            "Increase risk during MTF misalignment",
            "Generate entries from MTF alignment check",
        ],
    }


# ---------------------------------------------------------------------------
# Main: generate metadata
# ---------------------------------------------------------------------------

def generate_metadata() -> dict:
    """Extract all metadata from frozen modules. No logic. No conditionals."""
    now = datetime.datetime.now(datetime.timezone.utc)

    return {
        "$schema": "phase18_metadata_v1",
        "generated_at": now.isoformat(),
        "source_hash": _compute_source_hash(),
        "timeframes": {
            "canonical_order": ["1m", "5m", "15m", "30m", "1H", "4H", "1D", "1W"],
            "description": "Ascending resolution order (1m lowest, 1W highest)",
        },
        "strategy_families": _extract_strategy_families(),
        "mtf_alignment": _extract_mtf_alignment(),
        "risk_limits": _extract_risk_limits(),
        "profiles": _extract_profiles(),
        "guardrails": _extract_guardrails(),
        "strategies": _extract_strategies(),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    output_dir = Path("reports/phase18_guide")
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = generate_metadata()
    output_path = output_dir / "metadata.json"
    output_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False))

    print(f"Phase 18 metadata generated: {output_path}")
    print(f"  Schema: {metadata['$schema']}")
    print(f"  Profiles: {list(metadata['profiles'].keys())}")
    print(f"  Source hash: {metadata['source_hash'][:16]}...")
