"""MTF Alignment Policy — Pure, stateless risk refinement.

Compares HTF (1H) and LTF (15m) regime classifications.
Dampens risk when regimes are misaligned. Never increases risk.

Invariant: MTF may only dampen risk. MTF may never generate trades.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

MTFState = Literal["ALIGNED", "MISALIGNED", "NEUTRAL"]
RiskMultiplier = float


@dataclass(frozen=True)
class MTFPolicyOutput:
    """Immutable output from MTF alignment check."""
    adjusted_risk_multiplier: float
    mtf_state: MTFState


# Canonical alignment matrix
# (htf_regime, ltf_regime) -> (mtf_state, risk_multiplier_factor)
_ALIGNMENT_MATRIX: dict[tuple[str, str], tuple[MTFState, float]] = {
    # trending HTF
    ("TRENDING", "TRENDING"): ("ALIGNED", 1.0),
    ("TRENDING", "RANGING"):  ("MISALIGNED", 0.5),
    ("TRENDING", "VOLATILE"): ("MISALIGNED", 0.5),
    # ranging HTF
    ("RANGING", "RANGING"):   ("ALIGNED", 1.0),
    ("RANGING", "TRENDING"):  ("MISALIGNED", 0.5),
    ("RANGING", "VOLATILE"):  ("MISALIGNED", 0.5),
    # volatile HTF
    ("VOLATILE", "TRENDING"): ("NEUTRAL", 1.0),
    ("VOLATILE", "RANGING"):  ("NEUTRAL", 1.0),
    ("VOLATILE", "VOLATILE"): ("NEUTRAL", 1.0),
    # CASH always NEUTRAL
    ("CASH", "TRENDING"):     ("NEUTRAL", 1.0),
    ("CASH", "RANGING"):      ("NEUTRAL", 1.0),
    ("CASH", "VOLATILE"):     ("NEUTRAL", 1.0),
    ("CASH", "UNKNOWN"):      ("NEUTRAL", 1.0),
    ("CASH", "CASH"):         ("NEUTRAL", 1.0),
}


class MTFAlignmentPolicy:
    """Stateless policy that dampens risk during HTF/LTF misalignment.

    Inertia rule: MISALIGNED state only activates if
    ltf_regime != htf_regime for K consecutive closed LTF bars.

    Args:
        inertia_k: Number of consecutive misaligned bars required before
                   activating MISALIGNED dampening.
    """

    def __init__(self, inertia_k: int = 3) -> None:
        self._inertia_k = inertia_k
        self._consecutive_misaligned: int = 0

    def evaluate(
        self,
        htf_regime: str,
        ltf_regime: str,
        hermes_risk_multiplier: float,
    ) -> MTFPolicyOutput:
        """Evaluate MTF alignment and return adjusted risk multiplier.

        Args:
            htf_regime: Regime from Hermes (TRENDING, RANGING, VOLATILE, CASH, UNKNOWN)
            ltf_regime: Regime from LTF detector (TRENDING, RANGING, VOLATILE, UNKNOWN)
            hermes_risk_multiplier: Risk multiplier from Hermes sizing

        Returns:
            MTFPolicyOutput with adjusted_risk_multiplier and mtf_state
        """
        # Normalize to uppercase for matching (handles both str and Regime enum)
        htf_val = htf_regime.value if hasattr(htf_regime, "value") else htf_regime
        ltf_val = ltf_regime.value if hasattr(ltf_regime, "value") else ltf_regime
        htf_key = str(htf_val).upper() if htf_val else "UNKNOWN"
        ltf_key = str(ltf_val).upper() if ltf_val else "UNKNOWN"

        # Default: neutral (no change)
        key = (htf_key, ltf_key)
        if key not in _ALIGNMENT_MATRIX:
            # Unknown regime combination → NEUTRAL (no change)
            logger.debug(
                "MTF: NEUTRAL (unknown combo htf=%s ltf=%s)", htf_key, ltf_key
            )
            return MTFPolicyOutput(
                adjusted_risk_multiplier=hermes_risk_multiplier,
                mtf_state="NEUTRAL",
            )

        mtf_state, factor = _ALIGNMENT_MATRIX[key]

        # Apply inertia rule for MISALIGNED state
        if mtf_state == "MISALIGNED":
            if ltf_key != htf_key:
                self._consecutive_misaligned += 1
            else:
                self._consecutive_misaligned = 0

            if self._consecutive_misaligned < self._inertia_k:
                # Not enough consecutive bars → treat as NEUTRAL
                logger.debug(
                    "MTF: NEUTRAL (inertia %d/%d)",
                    self._consecutive_misaligned, self._inertia_k,
                )
                return MTFPolicyOutput(
                    adjusted_risk_multiplier=hermes_risk_multiplier,
                    mtf_state="NEUTRAL",
                )
        else:
            # Reset counter when not misaligned
            self._consecutive_misaligned = 0

        # Apply risk adjustment
        adjusted = hermes_risk_multiplier * factor
        logger.debug(
            "MTF: %s (htf=%s, ltf=%s) risk %.4f → %.4f",
            mtf_state, htf_key, ltf_key, hermes_risk_multiplier, adjusted,
        )

        return MTFPolicyOutput(
            adjusted_risk_multiplier=adjusted,
            mtf_state=mtf_state,
        )

    def reset(self) -> None:
        """Reset inertia counter. Call at start of each run."""
        self._consecutive_misaligned = 0