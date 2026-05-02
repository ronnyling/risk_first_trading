"""Deterministic risk veto layer — hard limits that Hermes cannot override."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

from src.core.types import Order, PortfolioState, OrderSide

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config/risk_limits.yaml")


@dataclass
class RiskLimits:
    """Hard risk constraints. These are architectural, not negotiable."""
    max_leverage: float = 1.0
    max_drawdown_pct: float = 0.20
    max_allocation_per_strategy_pct: float = 0.40
    max_total_exposure_pct: float = 0.90
    kill_switch_drawdown_pct: float = 0.25
    cooldown_bars_after_kill: int = 100


@dataclass
class OrderVeto:
    """Result of risk check on an order."""
    approved: bool
    order: Order | None = None
    reason: str = ""


class RiskLayer:
    """Deterministic veto layer that can override all other components.

    Responsibilities:
    - Enforce hard limits (leverage, drawdown, allocation, exposure)
    - Kill switch
    - Cool-down rules

    Hermes may request changes inside allowed envelopes,
    but cannot exceed hard constraints.
    """

    def __init__(self, limits: RiskLimits | None = None) -> None:
        self._limits = limits or self._load_defaults()
        self._kill_active = False
        self._kill_cooldown = 0
        self._strategy_allocations: dict[str, float] = {}

    def _load_defaults(self) -> RiskLimits:
        """Try to load from YAML, fall back to defaults."""
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                data = yaml.safe_load(f)
            return RiskLimits(**data)
        return RiskLimits()

    @property
    def limits(self) -> RiskLimits:
        return self._limits

    @property
    def is_kill_active(self) -> bool:
        return self._kill_active

    def update_strategy_allocations(self, allocations: dict[str, float]) -> None:
        """Update the risk layer with current strategy allocations."""
        self._strategy_allocations = dict(allocations)

    def check_order(self, order: Order, portfolio: PortfolioState) -> OrderVeto:
        """Deterministically check if an order is allowed.

        Returns OrderVeto with approved=True if allowed, or approved=False with reason.
        """
        # Kill switch check (already active)
        if self._kill_active:
            return OrderVeto(
                approved=False,
                order=order,
                reason=f"Kill switch active (cooldown: {self._kill_cooldown} bars)",
            )

        # Kill switch trigger (check BEFORE max drawdown so it activates)
        if portfolio.drawdown > self._limits.kill_switch_drawdown_pct:
            self._kill_active = True
            self._kill_cooldown = self._limits.cooldown_bars_after_kill
            logger.critical(
                "KILL SWITCH TRIGGERED: drawdown %.1f%% > %.1f%%",
                portfolio.drawdown * 100,
                self._limits.kill_switch_drawdown_pct * 100,
            )
            return OrderVeto(
                approved=False, order=order, reason="Kill switch triggered"
            )

        # Max drawdown check (below kill threshold but still too high)
        if portfolio.drawdown > self._limits.max_drawdown_pct:
            return OrderVeto(
                approved=False,
                order=order,
                reason=f"Drawdown {portfolio.drawdown:.1%} exceeds max {self._limits.max_drawdown_pct:.1%}",
            )

        # Exposure check
        if portfolio.exposure_pct > self._limits.max_total_exposure_pct:
            return OrderVeto(
                approved=False,
                order=order,
                reason=f"Exposure {portfolio.exposure_pct:.1%} exceeds max {self._limits.max_total_exposure_pct:.1%}",
            )

        # Leverage check
        if portfolio.leverage > self._limits.max_leverage:
            return OrderVeto(
                approved=False,
                order=order,
                reason=f"Leverage {portfolio.leverage:.2f}x exceeds max {self._limits.max_leverage:.2f}x",
            )

        # Per-strategy allocation check
        strat_alloc = self._strategy_allocations.get(order.strategy_id, 0.0)
        if strat_alloc > self._limits.max_allocation_per_strategy_pct:
            return OrderVeto(
                approved=False,
                order=order,
                reason=f"Strategy {order.strategy_id} allocation {strat_alloc:.1%} exceeds max {self._limits.max_allocation_per_strategy_pct:.1%}",
            )

        return OrderVeto(approved=True, order=order, reason="Approved")

    def tick_cooldown(self) -> None:
        """Decrement kill switch cooldown. Called once per bar."""
        if self._kill_active:
            self._kill_cooldown -= 1
            if self._kill_cooldown <= 0:
                self._kill_active = False
                self._kill_cooldown = 0
                logger.info("Kill switch cooldown expired — trading resumed")

    def check_portfolio(self, portfolio: PortfolioState) -> str:
        """Check overall portfolio health. Returns action string."""
        if self._kill_active:
            return "kill"

        if portfolio.drawdown > self._limits.kill_switch_drawdown_pct:
            return "kill"

        if portfolio.drawdown > self._limits.max_drawdown_pct:
            return "reduce"

        if portfolio.exposure_pct > self._limits.max_total_exposure_pct:
            return "reduce"

        return "hold"