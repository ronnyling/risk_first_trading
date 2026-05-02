"""Built-in trading horizon profiles — preset configurations only.

Phase 17: Values only. No logic. No conditionals.

Each preset is a canonical dict that can be loaded via:
    TradingProfile(**PRESETS["intraday_default"])
    ProfileResolver.from_preset("intraday_default")

All 4 presets set max_portfolio_risk explicitly for self-containment.
Custom profiles may omit it to inherit from config/risk_limits.yaml.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Canonical preset profiles (dict form)
# ---------------------------------------------------------------------------

PRESETS: dict[str, dict[str, Any]] = {
    # -----------------------------------------------------------------------
    # Scalping
    # -----------------------------------------------------------------------
    "scalping": {
        "profile_id": "scalping",
        "description": (
            "Scalping profile: fast timeframes, tight risk, "
            "structural + mean reversion families only"
        ),
        "timeframes": {
            "hermes_htf": "15m",
            "mtf_ltf": "5m",
            "execution_tf": ("1m",),  # strictly < mtf_ltf "5m"
        },
        "risk": {
            "base_risk": 0.0025,       # 0.25%
            "max_portfolio_risk": 0.01, # 1%
        },
        "mtf": {
            "inertia_bars": 2,
            "volatility_floor_pct": 0.4,
        },
        "families": {
            "structural_fractal": True,
            "mean_reversion": True,
            "liquidity_smc": False,
            "chaos_optional": False,
        },
    },

    # -----------------------------------------------------------------------
    # Intraday (Default)
    # -----------------------------------------------------------------------
    "intraday_default": {
        "profile_id": "intraday_default",
        "description": (
            "Default intraday profile: 1H Hermes HTF, 15m MTF LTF, "
            "structural + mean reversion families"
        ),
        "timeframes": {
            "hermes_htf": "1H",
            "mtf_ltf": "15m",
            "execution_tf": ("5m",),  # strictly < mtf_ltf "15m"
        },
        "risk": {
            "base_risk": 0.005,         # 0.5%
            "max_portfolio_risk": 0.025, # 2.5%
        },
        "mtf": {
            "inertia_bars": 3,
            "volatility_floor_pct": 0.5,
        },
        "families": {
            "structural_fractal": True,
            "mean_reversion": True,
            "liquidity_smc": False,
            "chaos_optional": False,
        },
    },

    # -----------------------------------------------------------------------
    # Swing
    # -----------------------------------------------------------------------
    "swing": {
        "profile_id": "swing",
        "description": (
            "Swing profile: 4H Hermes HTF, 1H MTF LTF, "
            "structural + mean reversion + liquidity families"
        ),
        "timeframes": {
            "hermes_htf": "4H",
            "mtf_ltf": "1H",
            "execution_tf": ("15m",),  # strictly < mtf_ltf "1H"
        },
        "risk": {
            "base_risk": 0.015,         # 1.5%
            "max_portfolio_risk": 0.05,  # 5%
        },
        "mtf": {
            "inertia_bars": 3,
            "volatility_floor_pct": 0.5,
        },
        "families": {
            "structural_fractal": True,
            "mean_reversion": True,
            "liquidity_smc": True,
            "chaos_optional": False,
        },
    },

    # -----------------------------------------------------------------------
    # Position / Macro
    # -----------------------------------------------------------------------
    "position_macro": {
        "profile_id": "position_macro",
        "description": (
            "Position/macro profile: 1D Hermes HTF, 4H MTF LTF, "
            "structural + liquidity families"
        ),
        "timeframes": {
            "hermes_htf": "1D",
            "mtf_ltf": "4H",
            "execution_tf": ("1H",),  # strictly < mtf_ltf "4H"
        },
        "risk": {
            "base_risk": 0.035,         # 3.5%
            "max_portfolio_risk": 0.10,  # 10%
        },
        "mtf": {
            "inertia_bars": 5,
            "volatility_floor_pct": 0.4,
        },
        "families": {
            "structural_fractal": True,
            "mean_reversion": False,
            "liquidity_smc": True,
            "chaos_optional": False,
        },
    },
}


def list_preset_ids() -> list[str]:
    """Return sorted list of available preset profile IDs."""
    return sorted(PRESETS.keys())


# ---------------------------------------------------------------------------
# Risk Appetite Profiles (Phase 22)
# ---------------------------------------------------------------------------
# These profiles configure the DrawdownLadder and FTMO guard behavior.
# They are separate from the timeframe presets above.

RISK_PROFILES: dict[str, dict[str, Any]] = {
    # -----------------------------------------------------------------------
    # Aggressive: higher risk, wider thresholds, fast recovery
    # -----------------------------------------------------------------------
    "aggressive": {
        "profile_id": "aggressive",
        "description": "Aggressive: higher risk, wider thresholds, fast recovery",
        "drawdown_ladder": {
            "growth_threshold": 0.07,      # 7% (wider)
            "protective_threshold": 0.12,  # 12% (wider)
            "growth_multiplier": 1.0,
            "protective_multiplier_range": (0.6, 0.8),
            "survival_multiplier": 0.3,
            "confidence_filter_growth": 0.0,
            "confidence_filter_protective": 0.5,
            "confidence_filter_survival": 0.7,
        },
        "risk": {
            "base_risk": 0.01,        # 1% per trade
            "max_portfolio_risk": 0.05,
        },
        "ftmo": {
            "max_daily_loss_pct": 0.05,
            "max_total_drawdown_pct": 0.10,
        },
        "families": {
            "growth": ["STRUCTURAL_FRACTAL", "MEAN_REVERSION", "LIQUIDITY_SMC"],
            "protective": ["STRUCTURAL_FRACTAL", "MEAN_REVERSION"],
            "survival": ["MEAN_REVERSION", "STRUCTURAL_FRACTAL"],
        },
        "family_weights": {
            "STRUCTURAL_FRACTAL": 1.0,
            "MEAN_REVERSION": 1.0,
            "LIQUIDITY_SMC": 0.8,
        },
    },

    # -----------------------------------------------------------------------
    # Balanced: moderate risk, smooth equity curve priority
    # -----------------------------------------------------------------------
    "balanced": {
        "profile_id": "balanced",
        "description": "Balanced: moderate risk, smooth equity curve priority",
        "drawdown_ladder": {
            "growth_threshold": 0.05,
            "protective_threshold": 0.10,
            "growth_multiplier": 1.0,
            "protective_multiplier_range": (0.5, 0.7),
            "survival_multiplier": 0.2,
            "confidence_filter_growth": 0.0,
            "confidence_filter_protective": 0.6,
            "confidence_filter_survival": 0.8,
        },
        "risk": {
            "base_risk": 0.005,       # 0.5% per trade
            "max_portfolio_risk": 0.025,
        },
        "ftmo": {
            "max_daily_loss_pct": 0.05,
            "max_total_drawdown_pct": 0.10,
        },
        "families": {
            "growth": ["STRUCTURAL_FRACTAL", "MEAN_REVERSION"],
            "protective": ["MEAN_REVERSION"],
            "survival": ["MEAN_REVERSION"],
        },
        "family_weights": {
            "STRUCTURAL_FRACTAL": 1.0,
            "MEAN_REVERSION": 0.9,
            "LIQUIDITY_SMC": 0.6,
        },
    },

    # -----------------------------------------------------------------------
    # Conservative: lower risk, tighter filters, early protection
    # -----------------------------------------------------------------------
    "conservative": {
        "profile_id": "conservative",
        "description": "Conservative: lower risk, tighter filters, early protection",
        "drawdown_ladder": {
            "growth_threshold": 0.03,      # 3% (tighter)
            "protective_threshold": 0.07,  # 7% (tighter)
            "growth_multiplier": 0.8,
            "protective_multiplier_range": (0.3, 0.5),
            "survival_multiplier": 0.1,
            "confidence_filter_growth": 0.3,
            "confidence_filter_protective": 0.7,
            "confidence_filter_survival": 0.85,
        },
        "risk": {
            "base_risk": 0.0025,      # 0.25% per trade
            "max_portfolio_risk": 0.01,
        },
        "ftmo": {
            "max_daily_loss_pct": 0.04,   # tighter than FTMO requirement
            "max_total_drawdown_pct": 0.08,  # tighter than FTMO requirement
        },
        "families": {
            "growth": ["MEAN_REVERSION", "STRUCTURAL_FRACTAL"],
            "protective": ["MEAN_REVERSION"],
            "survival": ["MEAN_REVERSION"],
        },
        "family_weights": {
            "STRUCTURAL_FRACTAL": 1.0,
            "MEAN_REVERSION": 0.8,
            "LIQUIDITY_SMC": 0.5,
        },
    },

    # -----------------------------------------------------------------------
    # FTMO-Safe: pass evaluation, strictest limits, survival bias
    # -----------------------------------------------------------------------
    "ftmo_safe": {
        "profile_id": "ftmo_safe",
        "description": "FTMO-Safe: pass evaluation, strictest limits, survival bias",
        "drawdown_ladder": {
            "growth_threshold": 0.03,      # 3% (very tight)
            "protective_threshold": 0.06,  # 6% (very tight)
            "growth_multiplier": 0.7,
            "protective_multiplier_range": (0.3, 0.5),
            "survival_multiplier": 0.15,
            "confidence_filter_growth": 0.4,
            "confidence_filter_protective": 0.7,
            "confidence_filter_survival": 0.9,
        },
        "risk": {
            "base_risk": 0.003,       # 0.3% per trade
            "max_portfolio_risk": 0.015,
        },
        "ftmo": {
            "max_daily_loss_pct": 0.045,  # 4.5% (buffer below 5% FTMO limit)
            "max_total_drawdown_pct": 0.09,  # 9% (buffer below 10% FTMO limit)
            "profit_target_pct": 0.10,
            "consistency_max_pct": 0.05,
        },
        "families": {
            "growth": ["MEAN_REVERSION", "STRUCTURAL_FRACTAL"],
            "protective": ["MEAN_REVERSION"],
            "survival": ["MEAN_REVERSION"],
        },
        "family_weights": {
            "STRUCTURAL_FRACTAL": 1.0,
            "MEAN_REVERSION": 0.6,
            "LIQUIDITY_SMC": 0.4,
        },
    },

    # -----------------------------------------------------------------------
    # FTMO-Safe Plus: post-evaluation, increased expectancy
    # -----------------------------------------------------------------------
    "ftmo_safe_plus": {
        "profile_id": "ftmo_safe_plus",
        "description": "FTMO-Safe Plus: increased capital efficiency, same safety envelope",
        "drawdown_ladder": {
            "growth_threshold": 0.03,      
            "protective_threshold": 0.06,  
            "growth_multiplier": 0.9,      # increased from 0.7
            "protective_multiplier_range": (0.5, 0.7),  # increased from 0.3-0.5
            "survival_multiplier": 0.15,
            "confidence_filter_growth": 0.3, # lowered from 0.4
            "confidence_filter_protective": 0.7,
            "confidence_filter_survival": 0.9,
        },
        "risk": {
            "base_risk": 0.003,       
            "max_portfolio_risk": 0.015,
        },
        "ftmo": {
            "max_daily_loss_pct": 0.045,
            "max_total_drawdown_pct": 0.09,
            "profit_target_pct": 0.10,
            "consistency_max_pct": 0.05,
            "survival_mode": "MEAN_REVERSION_ONLY",
        },
        "families": {
            "growth": ["MEAN_REVERSION", "STRUCTURAL_FRACTAL"],
            "protective": ["MEAN_REVERSION"],
            "survival": ["MEAN_REVERSION"],
        },
        "family_weights": {
            "STRUCTURAL_FRACTAL": 1.0,
            "MEAN_REVERSION": 0.8,
            "LIQUIDITY_SMC": 0.5,
        },
    },
}


def list_risk_profile_ids() -> list[str]:
    """Return sorted list of available risk appetite profile IDs."""
    return sorted(RISK_PROFILES.keys())
