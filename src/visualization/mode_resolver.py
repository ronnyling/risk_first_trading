"""System mode detection and resolution.

Determines the current system mode from engine and workflow state.

Phase F.5 — Visualization & Human Control Plane.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModeTransition:
    """Record of a mode transition."""

    old_mode: str
    new_mode: str
    trigger: str
    timestamp: str


class SystemModeResolver:
    """Resolves current system mode from engine and workflow state.

    Modes:
        LIVE — Engine active, real money at risk.
        ADVISORY — No execution, Hermes proposals only.
        META_LOCKDOWN — Meta-optimization proposal pending.
    """

    VALID_MODES = ("LIVE", "ADVISORY", "META_LOCKDOWN")

    def __init__(self) -> None:
        self._current_mode: str = "ADVISORY"
        self._previous_mode: str = "ADVISORY"

    @property
    def current_mode(self) -> str:
        """Return the current system mode."""
        return self._current_mode

    @property
    def previous_mode(self) -> str:
        """Return the previous system mode."""
        return self._previous_mode

    def resolve_mode(
        self,
        execution_active: bool = False,
        meta_proposals_pending: bool = False,
        meta_lockdown_active: bool = False,
    ) -> str:
        """Resolve current system mode from state.

        Args:
            execution_active: Whether the trading engine is running.
            meta_proposals_pending: Whether meta-optimization proposals exist.
            meta_lockdown_active: Whether meta-lockdown is active.

        Returns:
            Mode string: "LIVE", "ADVISORY", or "META_LOCKDOWN".
        """
        old_mode = self._current_mode

        if meta_lockdown_active:
            new_mode = "META_LOCKDOWN"
        elif execution_active:
            new_mode = "LIVE"
        else:
            new_mode = "ADVISORY"

        if new_mode != old_mode:
            self._previous_mode = old_mode
            self._current_mode = new_mode
            logger.info(
                "System mode transition: %s → %s",
                old_mode,
                new_mode,
            )

        return new_mode

    def set_mode(self, mode: str) -> None:
        """Manually set the system mode (for testing or explicit control)."""
        if mode not in self.VALID_MODES:
            raise ValueError(f"Invalid mode: {mode}. Must be one of {self.VALID_MODES}")
        old_mode = self._current_mode
        if mode != old_mode:
            self._previous_mode = old_mode
            self._current_mode = mode
            logger.info("System mode set: %s → %s", old_mode, mode)

    def is_interactive(self) -> bool:
        """Whether charts should be interactive in current mode."""
        return self._current_mode != "META_LOCKDOWN"

    def is_live(self) -> bool:
        """Whether system is in live trading mode."""
        return self._current_mode == "LIVE"

    def is_advisory(self) -> bool:
        """Whether system is in advisory-only mode."""
        return self._current_mode == "ADVISORY"

    def is_lockdown(self) -> bool:
        """Whether system is in meta-optimization lockdown."""
        return self._current_mode == "META_LOCKDOWN"
