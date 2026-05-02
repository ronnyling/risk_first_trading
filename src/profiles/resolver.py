"""Profile Resolver — dependency-injection layer for Trading Horizon Profiles.

Phase 17: Config plumbing only. No logic changes.

Loads a TradingProfile and exposes resolved values as immutable properties.
No control flow, no conditionals — pure accessor layer.

Fallback behavior for max_portfolio_risk:
- If profile.risk.max_portfolio_risk is not None -> use it
- If profile.risk.max_portfolio_risk is None -> read from config/risk_limits.yaml
  (frozen authoritative hard limit)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from src.profiles.presets import PRESETS, RISK_PROFILES
from src.profiles.schema import (
    FamiliesConfig,
    MTFConfig,
    RiskConfig,
    TimeframeConfig,
    TradingProfile,
)
from src.risk.drawdown_ladder import DrawdownProfile, drawdown_profile_from_dict

logger = logging.getLogger(__name__)

# Path to frozen risk limits (authoritative fallback)
_RISK_LIMITS_PATH = Path("config/risk_limits.yaml")
_DEFAULT_MAX_PORTFOLIO_RISK = 0.05  # 5% — matching frozen risk_limits.yaml


def _load_risk_limits_default() -> float:
    """Read max_portfolio_risk from frozen risk_limits.yaml. Fail-safe to 0.05."""
    if not _RISK_LIMITS_PATH.exists():
        logger.warning(
            "risk_limits.yaml not found at %s, using default %.2f%%",
            _RISK_LIMITS_PATH,
            _DEFAULT_MAX_PORTFOLIO_RISK * 100,
        )
        return _DEFAULT_MAX_PORTFOLIO_RISK

    with open(_RISK_LIMITS_PATH) as f:
        data = yaml.safe_load(f)

    value = data.get("max_total_exposure_pct", _DEFAULT_MAX_PORTFOLIO_RISK)
    logger.debug("Resolved max_portfolio_risk fallback from risk_limits.yaml: %.2f%%", value * 100)
    return value


def _build_profile_from_dict(data: dict[str, Any]) -> TradingProfile:
    """Construct a TradingProfile from a raw dict (YAML-loaded or programmatic)."""
    tf_data = data["timeframes"]
    risk_data = data["risk"]
    mtf_data = data["mtf"]
    fam_data = data["families"]

    # Normalize execution_tf: YAML lists become tuples
    exec_tf = tf_data["execution_tf"]
    if isinstance(exec_tf, list):
        exec_tf = tuple(exec_tf)

    return TradingProfile(
        profile_id=data["profile_id"],
        description=data.get("description", ""),
        timeframes=TimeframeConfig(
            hermes_htf=tf_data["hermes_htf"],
            mtf_ltf=tf_data["mtf_ltf"],
            execution_tf=exec_tf,
        ),
        risk=RiskConfig(
            base_risk=risk_data["base_risk"],
            max_portfolio_risk=risk_data.get("max_portfolio_risk"),
        ),
        mtf=MTFConfig(
            inertia_bars=mtf_data["inertia_bars"],
            volatility_floor_pct=mtf_data["volatility_floor_pct"],
        ),
        families=FamiliesConfig(
            structural_fractal=fam_data["structural_fractal"],
            mean_reversion=fam_data["mean_reversion"],
            liquidity_smc=fam_data["liquidity_smc"],
            chaos_optional=fam_data["chaos_optional"],
        ),
    )


class ProfileResolver:
    """Loads a TradingProfile and provides resolved values for existing components.

    This is a dependency-injection layer. It does NOT contain:
    - Conditional logic ("if scalping then...")
    - Style detection
    - Any behavior modification

    It simply loads config and returns values.

    Usage:
        resolver = ProfileResolver.from_preset("intraday_default")
        # or
        resolver = ProfileResolver.from_yaml(Path("config/profiles/my_profile.yaml"))

        # Inject into existing constructors:
        base_risk = resolver.base_risk
        max_portfolio_risk = resolver.max_portfolio_risk
        inertia_k = resolver.mtf_inertia_k
        floor_pct = resolver.ltf_floor_pct
        enabled = resolver.enabled_families
    """

    def __init__(self, profile: TradingProfile) -> None:
        """Initialize resolver with a validated TradingProfile."""
        profile.validate()
        self._profile = profile
        # Pre-resolve the max_portfolio_risk fallback once
        self._resolved_max_portfolio_risk: float = (
            profile.risk.max_portfolio_risk
            if profile.risk.max_portfolio_risk is not None
            else _load_risk_limits_default()
        )
        # Pre-resolve enabled families
        self._enabled_families = self._resolve_families(profile.families)
        # Drawdown profile (None for timeframe-only presets)
        self._drawdown_profile: DrawdownProfile | None = None

        logger.info(
            "ProfileResolver loaded: profile=%s, base_risk=%.4f, max_portfolio_risk=%.4f",
            profile.profile_id,
            profile.risk.base_risk,
            self._resolved_max_portfolio_risk,
        )

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_preset(cls, profile_id: str) -> ProfileResolver:
        """Load a built-in preset profile by ID.

        Args:
            profile_id: One of "scalping", "intraday_default", "swing", "position_macro"

        Raises:
            ValueError: If profile_id is not a known preset.
        """
        if profile_id not in PRESETS:
            available = sorted(PRESETS.keys())
            raise ValueError(
                f"Unknown preset profile '{profile_id}'. "
                f"Available: {available}"
            )
        profile = _build_profile_from_dict(PRESETS[profile_id])
        return cls(profile)

    @classmethod
    def from_yaml(cls, path: Path) -> ProfileResolver:
        """Load a custom profile from a YAML file.

        Args:
            path: Path to a YAML profile file.

        Raises:
            ValueError: If the YAML is malformed or fails validation.
            FileNotFoundError: If the file does not exist.
        """
        if not path.exists():
            raise FileNotFoundError(f"Profile YAML not found: {path}")

        with open(path) as f:
            data = yaml.safe_load(f)

        profile = _build_profile_from_dict(data)
        return cls(profile)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProfileResolver:
        """Load a custom profile from a raw dict.

        Args:
            data: Dict matching the TradingProfile schema.

        Raises:
            ValueError: If the dict is malformed or fails validation.
        """
        profile = _build_profile_from_dict(data)
        return cls(profile)

    @classmethod
    def from_risk_profile(cls, profile_id: str) -> ProfileResolver:
        """Load a risk appetite profile by ID.

        Risk appetite profiles configure the DrawdownLadder and FTMO guard.
        They are separate from the timeframe presets.

        Args:
            profile_id: One of "aggressive", "balanced", "conservative", "ftmo_safe"

        Raises:
            ValueError: If profile_id is not a known risk profile.
        """
        if profile_id not in RISK_PROFILES:
            available = sorted(RISK_PROFILES.keys())
            raise ValueError(
                f"Unknown risk profile '{profile_id}'. "
                f"Available: {available}"
            )
        risk_data = RISK_PROFILES[profile_id]

        # Build a minimal TradingProfile from the risk data
        # Use sensible defaults for timeframe/mtf/families
        profile_dict = {
            "profile_id": risk_data["profile_id"],
            "description": risk_data.get("description", ""),
            "timeframes": {
                "hermes_htf": "1H",
                "mtf_ltf": "15m",
                "execution_tf": ("5m",),
            },
            "risk": risk_data["risk"],
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
        }
        profile = _build_profile_from_dict(profile_dict)
        resolver = cls(profile)

        # Attach the drawdown profile from risk profile data
        resolver._drawdown_profile = drawdown_profile_from_dict(
            risk_data.get("drawdown_ladder", {})
        )

        return resolver

    # ------------------------------------------------------------------
    # Resolved properties (immutable accessors)
    # ------------------------------------------------------------------

    @property
    def profile(self) -> TradingProfile:
        """The underlying validated TradingProfile."""
        return self._profile

    @property
    def profile_id(self) -> str:
        """Profile identifier."""
        return self._profile.profile_id

    @property
    def base_risk(self) -> float:
        """Base risk per trade (fraction of equity)."""
        return self._profile.risk.base_risk

    @property
    def max_portfolio_risk(self) -> float:
        """Max portfolio risk budget.

        Returns profile value if set, otherwise falls back to risk_limits.yaml.
        """
        return self._resolved_max_portfolio_risk

    @property
    def mtf_inertia_k(self) -> int:
        """MTF alignment inertia bars."""
        return self._profile.mtf.inertia_bars

    @property
    def ltf_floor_pct(self) -> float:
        """LTF regime detector volatility floor percentage."""
        return self._profile.mtf.volatility_floor_pct

    @property
    def hermes_htf(self) -> str:
        """Hermes higher timeframe (e.g., "1H", "4H")."""
        return self._profile.timeframes.hermes_htf

    @property
    def mtf_ltf(self) -> str:
        """MTF lower timeframe (e.g., "15m", "1H")."""
        return self._profile.timeframes.mtf_ltf

    @property
    def execution_tf(self) -> tuple[str, ...]:
        """Strategy execution timeframe(s), ascending."""
        return self._profile.timeframes.execution_tf

    @property
    def enabled_families(self) -> frozenset:
        """Set of enabled StrategyFamily values.

        Returns:
            frozenset of StrategyFamily enum members that are enabled.
        """
        return self._enabled_families

    @property
    def drawdown_profile(self) -> DrawdownProfile | None:
        """Drawdown ladder configuration for risk appetite profiles.

        Returns DrawdownProfile if loaded via from_risk_profile(), None otherwise.
        """
        return self._drawdown_profile

    @property
    def risk_profile_id(self) -> str | None:
        """Risk appetite profile ID, if loaded via from_risk_profile()."""
        if self._drawdown_profile is not None:
            return self._profile.profile_id
        return None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_families(families: FamiliesConfig) -> frozenset:
        """Map FamiliesConfig booleans to a frozenset of StrategyFamily values."""
        from src.policy.strategy_family_policy import StrategyFamily

        enabled: set = set()
        if families.structural_fractal:
            enabled.add(StrategyFamily.STRUCTURAL_FRACTAL)
        if families.mean_reversion:
            enabled.add(StrategyFamily.MEAN_REVERSION)
        if families.liquidity_smc:
            enabled.add(StrategyFamily.LIQUIDITY_SMC)
        if families.chaos_optional:
            enabled.add(StrategyFamily.CHAOS_OPTIONAL)
        return frozenset(enabled)
