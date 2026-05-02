"""Policy engine: loads YAML rules and evaluates conditions for Hermes."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.core.types import Regime, RiskPosture, StrategyMetrics

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config/hermes_policy.yaml")


@dataclass
class PolicyRule:
    name: str
    condition: str
    action: str
    params: dict[str, Any]


class Policy:
    """Deterministic policy engine for Hermes v1.

    Evaluates simple condition-action rules against current state.
    Designed to be transparent and explainable — every decision has a reason.
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self._rules: list[PolicyRule] = []
        self._load(config_path or CONFIG_PATH)

    def _load(self, path: Path) -> None:
        if not path.exists():
            logger.warning("Policy config not found at %s, using defaults", path)
            self._rules = self._default_rules()
            return

        with open(path) as f:
            data = yaml.safe_load(f)

        for r in data.get("rules", []):
            self._rules.append(
                PolicyRule(
                    name=r["name"],
                    condition=r["condition"],
                    action=r["action"],
                    params=r.get("params", {}),
                )
            )
        logger.info("Loaded %d policy rules", len(self._rules))

    def _default_rules(self) -> list[PolicyRule]:
        return [
            PolicyRule(
                name="trend_regime",
                condition="regime == 'trending'",
                action="activate_style",
                params={"style": "trend", "weight": 0.8},
            ),
            PolicyRule(
                name="range_regime",
                condition="regime == 'ranging'",
                action="activate_style",
                params={"style": "mean_reversion", "weight": 0.7},
            ),
            PolicyRule(
                name="drawdown_pause",
                condition="strategy.drawdown > 0.15",
                action="pause_strategy",
                params={"cooldown_bars": 50},
            ),
            PolicyRule(
                name="global_risk_down",
                condition="portfolio.drawdown > 0.10",
                action="reduce_all",
                params={"scale": 0.5},
            ),
        ]

    def evaluate(
        self,
        regime: Regime,
        strategy_style: str,
        strategy_metrics: StrategyMetrics,
        portfolio_drawdown: float,
        risk_posture: RiskPosture,
    ) -> tuple[str, float, str]:
        """Evaluate rules against current state.

        Returns: (action, weight, reason)
        """
        # Check global risk first — highest priority
        if portfolio_drawdown > 0.10:
            return ("reduce_all", 0.5, f"Portfolio drawdown {portfolio_drawdown:.1%} > 10%")

        # Check strategy-level drawdown pause
        if strategy_metrics.current_drawdown > 0.15:
            return (
                "pause",
                0.0,
                f"Strategy drawdown {strategy_metrics.current_drawdown:.1%} > 15%",
            )

        # Check risk posture
        if risk_posture == RiskPosture.CONSERVATIVE:
            return ("reduce_all", 0.3, "Conservative posture active")

        if risk_posture == RiskPosture.REDUCED:
            return ("reduce_all", 0.6, "Reduced posture active")

        # Regime-based allocation
        regime_name = regime.value

        # Trending regime → favor trend strategies
        if regime_name == "trending" and strategy_style == "trend":
            return ("activate", 0.8, f"Trending regime matches trend strategy")

        if regime_name == "trending" and strategy_style == "mean_reversion":
            return ("reduce", 0.3, f"Trending regime penalizes mean-reversion")

        # Ranging regime → favor mean-reversion
        if regime_name == "ranging" and strategy_style == "mean_reversion":
            return ("activate", 0.7, f"Ranging regime matches mean-reversion strategy")

        if regime_name == "ranging" and strategy_style == "trend":
            return ("reduce", 0.3, f"Ranging regime penalizes trend strategy")

        # Volatile → reduce everything
        if regime_name == "volatile":
            return ("reduce_all", 0.4, "Volatile regime — reducing exposure")

        # Default: normal allocation
        return ("activate", 0.5, "Default allocation (no specific rule matched)")

    @property
    def rules(self) -> list[PolicyRule]:
        return list(self._rules)