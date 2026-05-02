"""Profile transition gates and objective criteria evaluation.

This module implements the objective transition criteria for expanding
profitability profiles (e.g., ftmo_safe -> ftmo_safe_plus). Profile
expansion is mandatory but requires passing strict, auditable criteria.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FTMOMetrics:
    """Metrics collected during an FTMO evaluation period."""
    passed_evaluation: bool
    max_drawdown_pct: float
    daily_violations: int
    total_violations: int
    active_trading_days: int
    survival_breaches_final_20pct: int


class ProfileTransitionGate:
    """Evaluates whether a profile transition is permitted based on metrics."""

    @staticmethod
    def can_upgrade_to_safe_plus(metrics: FTMOMetrics) -> bool:
        """Evaluate if the strict criteria for upgrading to ftmo_safe_plus are met.
        
        REQUIRED CONDITIONS (ALL MUST PASS):
        1. FTMO evaluation PASSED (firm confirmation)
        2. Max drawdown during evaluation <= 50% of allowed DD (<= 4.5%)
        3. Zero FTMO violations (daily or total)
        4. >= 10 active trading days logged
        5. No Survival-mode breaches in final 20% of evaluation period
        """
        if not metrics.passed_evaluation:
            return False
            
        if metrics.max_drawdown_pct > 0.045:
            return False
            
        if metrics.daily_violations > 0 or metrics.total_violations > 0:
            return False
            
        if metrics.active_trading_days < 10:
            return False
            
        if metrics.survival_breaches_final_20pct > 0:
            return False
            
        return True
