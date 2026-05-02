"""Trading Horizon Profile schema — frozen, immutable, config-only.

Phase 17: No logic. Values only. Validation only.

Timeframe ordering convention (ascending):
    1m < 5m < 15m < 30m < 1H < 4H < 1D < 1W
"""

from __future__ import annotations

from dataclasses import dataclass


# Canonical timeframe ordering (ascending resolution)
_TIMEFRAME_ORDER: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1H": 60,
    "4H": 240,
    "1D": 1440,
    "1W": 10080,
}


def _tf_rank(tf: str) -> int:
    """Return numeric rank for a timeframe string. Raises ValueError if unknown."""
    if tf not in _TIMEFRAME_ORDER:
        raise ValueError(
            f"Unknown timeframe '{tf}'. "
            f"Supported: {sorted(_TIMEFRAME_ORDER.keys(), key=lambda k: _TIMEFRAME_ORDER[k])}"
        )
    return _TIMEFRAME_ORDER[tf]


@dataclass(frozen=True)
class TimeframeConfig:
    """Timeframe configuration for a trading horizon profile.

    Attributes:
        hermes_htf: Higher timeframe for Hermes regime detection (e.g., "1H", "4H")
        mtf_ltf: Lower timeframe for MTF alignment (e.g., "15m", "1H")
        execution_tf: Strategy execution timeframe(s), ascending, all < mtf_ltf
    """

    hermes_htf: str
    mtf_ltf: str
    execution_tf: tuple[str, ...]

    def validate(self) -> None:
        """Validate timeframe ordering. Fail-fast with descriptive ValueError."""
        # HTF must be strictly greater than LTF
        htf_rank = _tf_rank(self.hermes_htf)
        ltf_rank = _tf_rank(self.mtf_ltf)

        if htf_rank <= ltf_rank:
            raise ValueError(
                f"hermes_htf '{self.hermes_htf}' must be strictly greater than "
                f"mtf_ltf '{self.mtf_ltf}'"
            )

        if not self.execution_tf:
            raise ValueError("execution_tf must contain at least one timeframe")

        # Each execution TF must be strictly ascending and strictly less than mtf_ltf
        prev_rank = 0
        for tf in self.execution_tf:
            rank = _tf_rank(tf)
            if rank <= prev_rank:
                raise ValueError(
                    f"execution_tf must be strictly ascending. "
                    f"Got '{tf}' (rank {rank}) after previous (rank {prev_rank})"
                )
            if rank >= ltf_rank:
                raise ValueError(
                    f"execution_tf '{tf}' must be strictly less than "
                    f"mtf_ltf '{self.mtf_ltf}'"
                )
            prev_rank = rank


@dataclass(frozen=True)
class RiskConfig:
    """Risk configuration for a trading horizon profile.

    Attributes:
        base_risk: Fraction of equity per trade (e.g., 0.01 = 1%)
        max_portfolio_risk: Total portfolio risk budget. None = inherit from
            config/risk_limits.yaml (frozen authoritative hard limit).
    """

    base_risk: float
    max_portfolio_risk: float | None = None

    def validate(self) -> None:
        """Validate risk bounds. Fail-fast with descriptive ValueError."""
        if not (0.001 <= self.base_risk <= 0.10):
            raise ValueError(
                f"base_risk {self.base_risk} out of bounds. "
                f"Must be between 0.001 (0.1%) and 0.10 (10%)"
            )

        if self.max_portfolio_risk is not None:
            if not (0.0 <= self.max_portfolio_risk <= 0.20):
                raise ValueError(
                    f"max_portfolio_risk {self.max_portfolio_risk} out of bounds. "
                    f"Must be between 0.0 and 0.20 (20%)"
                )


@dataclass(frozen=True)
class MTFConfig:
    """MTF alignment configuration for a trading horizon profile.

    Attributes:
        inertia_bars: Consecutive misaligned bars before dampening activates
        volatility_floor_pct: LTF regime detector volatility floor percentage
    """

    inertia_bars: int
    volatility_floor_pct: float

    def validate(self) -> None:
        """Validate MTF parameters. Fail-fast with descriptive ValueError."""
        if not (1 <= self.inertia_bars <= 20):
            raise ValueError(
                f"inertia_bars {self.inertia_bars} out of bounds. "
                f"Must be between 1 and 20"
            )

        if not (0.1 <= self.volatility_floor_pct <= 1.0):
            raise ValueError(
                f"volatility_floor_pct {self.volatility_floor_pct} out of bounds. "
                f"Must be between 0.1 and 1.0"
            )


@dataclass(frozen=True)
class FamiliesConfig:
    """Strategy family permissions for a trading horizon profile.

    At least one family must be enabled.
    """

    structural_fractal: bool
    mean_reversion: bool
    liquidity_smc: bool
    chaos_optional: bool

    @property
    def enabled_count(self) -> int:
        return sum([
            self.structural_fractal,
            self.mean_reversion,
            self.liquidity_smc,
            self.chaos_optional,
        ])

    def validate(self) -> None:
        """Validate that at least one family is enabled."""
        if self.enabled_count == 0:
            raise ValueError(
                "At least one strategy family must be enabled"
            )


@dataclass(frozen=True)
class TradingProfile:
    """Immutable trading horizon profile — pure configuration, no logic.

    A profile declares:
    - Timeframe hierarchy (HTF → LTF → execution)
    - Risk parameters (per-trade, portfolio)
    - MTF alignment parameters
    - Which strategy families are permitted

    Profiles do NOT contain:
    - Conditional logic
    - Strategy-specific rules
    - Timeframe detection
    """

    profile_id: str
    description: str
    timeframes: TimeframeConfig
    risk: RiskConfig
    mtf: MTFConfig
    families: FamiliesConfig

    def validate(self) -> None:
        """Validate entire profile. Fail-fast — first error raises ValueError."""
        if not self.profile_id:
            raise ValueError("profile_id must not be empty")

        self.timeframes.validate()
        self.risk.validate()
        self.mtf.validate()
        self.families.validate()
