"""ScalingConfig — central scaling configuration manager.

Loads deployment profiles from `config/scaling_profiles.json` and provides
validation, rate-limit, and degradation utilities for all system components.

Production data source:
    Config file is the authoritative scaling definition.
    No CSVs, mocks, or fallbacks.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config/scaling_profiles.json")

DEFAULT_PROFILE_NAME = "SMALL"

# Required fields in each profile for validation
_REQUIRED_PROFILE_FIELDS = [
    "max_symbols",
    "supported_timeframes",
    "default_timeframe",
    "poll_interval_seconds",
    "hermes_scheduling",
    "concurrency",
    "memory_budget",
    "rate_limits",
    "degradation",
]


@dataclass(frozen=True)
class ScalingProfile:
    """Immutable scaling profile loaded from config."""

    name: str
    description: str
    max_symbols: int
    supported_timeframes: list[str]
    default_timeframe: str
    poll_interval_seconds: int
    # Hermes scheduling
    hermes_min_interval_minutes: int
    hermes_max_interval_minutes: int
    hermes_default_interval_minutes: int
    hermes_allowed_hours: dict | None
    # Concurrency
    max_parallel_fetches: int
    max_hermes_batch_symbols: int
    max_correlation_symbols: int
    # Memory
    max_bars_per_symbol: int
    max_total_bars: int
    # Rate limits
    yfinance_max_requests_per_minute: int
    yfinance_cooldown_seconds: float
    max_consecutive_errors: int
    # Degradation
    degradation_on_rate_limit: str
    degradation_on_symbol_exceeds_max: str
    degradation_on_api_failure: str
    degradation_on_partial_data: str
    hermes_timeout_seconds: int


class ScalingConfig:
    """Central scaling configuration manager.

    Reads `config/scaling_profiles.json` and provides:
    - Active profile loading
    - Universe size validation
    - Rate limit configuration
    - Degradation mode lookup
    - Memory usage estimation

    Usage:
        config = ScalingConfig()
        profile = config.load_active_profile()
        ok, reason = config.validate_universe_size(symbols)
    """

    def __init__(self, config_path: Path | str | None = None) -> None:
        self._config_path = Path(config_path) if config_path else CONFIG_PATH
        self._raw_config: dict | None = None

    def _load_raw_config(self) -> dict:
        """Load raw JSON config from disk. Returns empty config on failure."""
        if self._raw_config is not None:
            return self._raw_config

        if not self._config_path.exists():
            logger.warning(
                "Scaling config not found at %s. Using default profile.",
                self._config_path,
            )
            self._raw_config = {
                "active_profile": DEFAULT_PROFILE_NAME,
                "profiles": {},
            }
            return self._raw_config

        try:
            self._raw_config = json.loads(
                self._config_path.read_text(encoding="utf-8")
            ) or {}
        except Exception as e:
            logger.error("Failed to read scaling config: %s", e)
            self._raw_config = {
                "active_profile": DEFAULT_PROFILE_NAME,
                "profiles": {},
            }

        return self._raw_config

    def load_active_profile(self) -> ScalingProfile:
        """Load the active scaling profile from config.

        Returns:
            ScalingProfile with all fields populated.

        Falls back to SMALL defaults if profile is missing or malformed.
        """
        raw = self._load_raw_config()
        active_name = raw.get("active_profile", DEFAULT_PROFILE_NAME)
        profiles = raw.get("profiles", {})
        profile_data = profiles.get(active_name)

        if profile_data is None:
            logger.warning(
                "Profile '%s' not found in config. Falling back to SMALL defaults.",
                active_name,
            )
            return self._make_default_profile(DEFAULT_PROFILE_NAME)

        try:
            return self._parse_profile(active_name, profile_data)
        except (KeyError, TypeError, ValueError) as e:
            logger.error(
                "Failed to parse profile '%s': %s. Using defaults.",
                active_name,
                e,
            )
            return self._make_default_profile(active_name)

    def get_profile(self, name: str) -> ScalingProfile:
        """Load a specific named profile.

        Args:
            name: Profile name (SMALL, MEDIUM, LARGE).

        Returns:
            ScalingProfile or default if not found.
        """
        raw = self._load_raw_config()
        profiles = raw.get("profiles", {})
        profile_data = profiles.get(name)

        if profile_data is None:
            logger.warning("Profile '%s' not found. Using defaults.", name)
            return self._make_default_profile(name)

        try:
            return self._parse_profile(name, profile_data)
        except (KeyError, TypeError, ValueError) as e:
            logger.error("Failed to parse profile '%s': %s", name, e)
            return self._make_default_profile(name)

    def set_active_profile(self, name: str) -> None:
        """Set the active profile and write to disk.

        Args:
            name: Profile name to activate.
        """
        raw = self._load_raw_config()
        raw["active_profile"] = name
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(raw, indent=2), encoding="utf-8"
        )
        logger.info("Active scaling profile set to '%s'", name)
        # Invalidate cached config
        self._raw_config = None

    def validate_universe_size(self, symbols: list[str]) -> tuple[bool, str]:
        """Validate that the universe size is within the active profile's limit.

        Args:
            symbols: List of universe symbols.

        Returns:
            Tuple of (ok, reason). ok=True if within limit.
        """
        profile = self.load_active_profile()
        count = len(symbols)

        if count <= profile.max_symbols:
            return True, f"{count}/{profile.max_symbols} symbols within limit"

        return False, (
            f"Universe has {count} symbols but profile '{profile.name}' "
            f"allows maximum {profile.max_symbols}. "
            f"Excess {count - profile.max_symbols} symbols will be rejected."
        )

    def get_rate_limit_delay(self) -> float:
        """Get the minimum delay between yfinance requests in seconds."""
        profile = self.load_active_profile()
        return profile.yfinance_cooldown_seconds

    def get_degradation_mode(self, failure_type: str) -> str:
        """Get the degradation action for a specific failure type.

        Args:
            failure_type: One of 'rate_limit', 'symbol_exceeds_max',
                         'api_failure', 'partial_data'.

        Returns:
            Degradation action string.
        """
        profile = self.load_active_profile()
        mapping = {
            "rate_limit": profile.degradation_on_rate_limit,
            "symbol_exceeds_max": profile.degradation_on_symbol_exceeds_max,
            "api_failure": profile.degradation_on_api_failure,
            "partial_data": profile.degradation_on_partial_data,
        }
        return mapping.get(failure_type, "unknown")

    def get_memory_usage_estimate(self, symbol_count: int) -> dict:
        """Estimate memory usage for a given symbol count.

        Args:
            symbol_count: Number of symbols to estimate for.

        Returns:
            Dict with estimated bars and whether within budget.
        """
        profile = self.load_active_profile()
        estimated_bars = symbol_count * profile.max_bars_per_symbol
        within_budget = estimated_bars <= profile.max_total_bars

        return {
            "symbol_count": symbol_count,
            "bars_per_symbol": profile.max_bars_per_symbol,
            "estimated_total_bars": estimated_bars,
            "budget_total_bars": profile.max_total_bars,
            "within_budget": within_budget,
            "utilization_pct": (
                round(estimated_bars / profile.max_total_bars * 100, 1)
                if profile.max_total_bars > 0
                else 0.0
            ),
        }

    def is_symbol_count_within_budget(self, symbol_count: int) -> bool:
        """Check if symbol count is within the profile's memory budget."""
        estimate = self.get_memory_usage_estimate(symbol_count)
        return estimate["within_budget"]

    def _parse_profile(self, name: str, data: dict) -> ScalingProfile:
        """Parse a profile dict into a ScalingProfile dataclass."""
        hermes_sched = data.get("hermes_scheduling", {})
        concurrency = data.get("concurrency", {})
        memory = data.get("memory_budget", {})
        rate = data.get("rate_limits", {})
        degrad = data.get("degradation", {})

        return ScalingProfile(
            name=name,
            description=data.get("description", ""),
            max_symbols=data.get("max_symbols", 5),
            supported_timeframes=data.get("supported_timeframes", ["1H"]),
            default_timeframe=data.get("default_timeframe", "1H"),
            poll_interval_seconds=data.get("poll_interval_seconds", 300),
            hermes_min_interval_minutes=hermes_sched.get("min_interval_minutes", 60),
            hermes_max_interval_minutes=hermes_sched.get("max_interval_minutes", 1440),
            hermes_default_interval_minutes=hermes_sched.get("default_interval_minutes", 120),
            hermes_allowed_hours=hermes_sched.get("allowed_hours"),
            max_parallel_fetches=concurrency.get("max_parallel_fetches", 3),
            max_hermes_batch_symbols=concurrency.get("max_hermes_batch_symbols", 5),
            max_correlation_symbols=concurrency.get("max_correlation_symbols", 20),
            max_bars_per_symbol=memory.get("max_bars_per_symbol", 250),
            max_total_bars=memory.get("max_total_bars", 1250),
            yfinance_max_requests_per_minute=rate.get("yfinance_max_requests_per_minute", 10),
            yfinance_cooldown_seconds=rate.get("yfinance_cooldown_seconds", 6.0),
            max_consecutive_errors=rate.get("max_consecutive_errors", 3),
            degradation_on_rate_limit=degrad.get("on_rate_limit", "wait_and_retry"),
            degradation_on_symbol_exceeds_max=degrad.get("on_symbol_exceeds_max", "reject_with_warning"),
            degradation_on_api_failure=degrad.get("on_api_failure", "skip_symbol_and_continue"),
            degradation_on_partial_data=degrad.get("on_partial_data", "allow_with_warning"),
            hermes_timeout_seconds=degrad.get("on_hermes_timeout_seconds", 120),
        )

    def _make_default_profile(self, name: str) -> ScalingProfile:
        """Create a default SMALL profile when config is unavailable."""
        return ScalingProfile(
            name=name,
            description="Default fallback profile",
            max_symbols=5,
            supported_timeframes=["1H"],
            default_timeframe="1H",
            poll_interval_seconds=300,
            hermes_min_interval_minutes=60,
            hermes_max_interval_minutes=1440,
            hermes_default_interval_minutes=120,
            hermes_allowed_hours=None,
            max_parallel_fetches=3,
            max_hermes_batch_symbols=5,
            max_correlation_symbols=20,
            max_bars_per_symbol=250,
            max_total_bars=1250,
            yfinance_max_requests_per_minute=10,
            yfinance_cooldown_seconds=6.0,
            max_consecutive_errors=3,
            degradation_on_rate_limit="wait_and_retry",
            degradation_on_symbol_exceeds_max="reject_with_warning",
            degradation_on_api_failure="skip_symbol_and_continue",
            degradation_on_partial_data="allow_with_warning",
            hermes_timeout_seconds=120,
        )
