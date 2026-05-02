"""FamilyEnforcer — ensures correct strategy family assignment per symbol per regime.

Phase C of the continuous breadth expansion workflow.
Assigns default families based on bucket and verifies family switching
after Hermes batch runs.
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.hermes.decision import HermesDecision

from src.breadth.models import FamilyDirective

logger = logging.getLogger(__name__)

# Default families by bucket — conservative defaults for new symbols
DEFAULT_FAMILIES_BY_BUCKET: dict[str, list[str]] = {
    "CRYPTO_MAJOR": ["STRUCTURAL_FRACTAL", "MEAN_REVERSION", "LIQUIDITY_SMC"],
    "CRYPTO_ALT": ["STRUCTURAL_FRACTAL", "MEAN_REVERSION"],
    "EQUITIES": ["STRUCTURAL_FRACTAL", "MEAN_REVERSION"],
    "EQUITIES_ETF": ["STRUCTURAL_FRACTAL", "MEAN_REVERSION"],
    "FX": ["MEAN_REVERSION", "LIQUIDITY_SMC"],
    "FX_MAJOR": ["MEAN_REVERSION", "LIQUIDITY_SMC"],
    "COMMODITY": ["STRUCTURAL_FRACTAL"],
}


class FamilyEnforcer:
    """Ensures correct strategy family assignment per symbol per regime.

    Responsibilities:
    1. Assign default enabled_families based on bucket
    2. Verify family switching after Hermes batch runs
    3. Track manual overrides

    Usage:
        enforcer = FamilyEnforcer()
        families = enforcer.assign_defaults("SPY", "EQUITIES")
    """

    def assign_defaults(self, symbol: str, bucket: str) -> list[str]:
        """Return default enabled_families for a symbol based on bucket.

        Args:
            symbol: The symbol to assign families to.
            bucket: The asset class bucket (e.g., "CRYPTO_MAJOR", "EQUITIES").

        Returns:
            List of strategy family names to enable.
        """
        families = DEFAULT_FAMILIES_BY_BUCKET.get(bucket)
        if families is None:
            logger.warning(
                "Unknown bucket '%s' for symbol '%s', using STRUCTURAL_FRACTAL only",
                bucket,
                symbol,
            )
            return ["STRUCTURAL_FRACTAL"]

        return list(families)  # Return a copy

    def verify_family_switching(
        self,
        hermes_decisions: dict[str, HermesDecision],
        universe_data: dict,
    ) -> list[FamilyDirective]:
        """Verify that family switching occurred correctly after a Hermes run.

        Compares HermesDecision.allowed_strategy_family with the
        enabled_families in the universe data.

        Args:
            hermes_decisions: Per-symbol Hermes decisions from the latest run.
            universe_data: Universe version data with enabled_families per symbol.

        Returns:
            List of FamilyDirective records for audit logging.
        """
        directives: list[FamilyDirective] = []
        markets = universe_data.get("markets", {})

        for symbol, decision in hermes_decisions.items():
            market_data = markets.get(symbol, {})
            bucket = market_data.get("bucket", "UNKNOWN")
            assigned_families = market_data.get("enabled_families", [])

            family_used = decision.allowed_strategy_family
            regime = decision.regime

            # Check if the used family is in the assigned list
            correct_switch = None
            if family_used and assigned_families:
                correct_switch = family_used in assigned_families

            directives.append(
                FamilyDirective(
                    symbol=symbol,
                    bucket=bucket,
                    assigned_families=assigned_families,
                    regime_used=regime,
                    family_used=family_used,
                    correct_switch=correct_switch,
                    timestamp=datetime.now().isoformat(),
                )
            )

            if correct_switch is False:
                logger.warning(
                    "Family mismatch for %s: used '%s' but only '%s' enabled",
                    symbol,
                    family_used,
                    assigned_families,
                )

        return directives
