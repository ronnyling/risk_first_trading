"""Trading Horizon Profiles — pure configuration layer for timeframe/risk dispatch.

This package defines:
- TradingProfile: frozen schema for a trading horizon profile
- ProfileResolver: dependency-injection layer that loads a profile and
  exposes resolved values for existing components (risk, MTF, families)
- Built-in presets: scalping, intraday_default, swing, position_macro
- Risk appetite profiles: aggressive, balanced, conservative, ftmo_safe

Phase 17: Config plumbing only. No logic changes.
Phase 22: Added risk appetite profiles and DrawdownProfile.
"""

from src.profiles.resolver import ProfileResolver
from src.profiles.schema import (
    FamiliesConfig,
    MTFConfig,
    RiskConfig,
    TimeframeConfig,
    TradingProfile,
)
from src.profiles.drawdown_profile import DrawdownProfile

__all__ = [
    "DrawdownProfile",
    "FamiliesConfig",
    "MTFConfig",
    "ProfileResolver",
    "RiskConfig",
    "TimeframeConfig",
    "TradingProfile",
]
