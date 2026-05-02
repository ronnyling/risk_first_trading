"""
Phase P8 - Capital Scaling Playbook (2x / 5x / 10x)
Phase P1 - Capital Allocation Policy
"""

from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class AllocationPolicy:
    core_capital_pct: float
    aggressive_capital_pct: float
    max_markets: int

class CapitalScalingPlaybook:
    def __init__(self, current_multiplier: int = 1):
        self.current_multiplier = current_multiplier
        
    def get_allocation_policy(self, profile: str) -> AllocationPolicy:
        """
        P1: Capital Allocation Policy
        - ftmo_safe / ftmo_safe_plus: minimal capital
        - balanced: core capital (smooth compounding)
        - aggressive: conditional, capped capital
        """
        if profile in ["ftmo_safe", "ftmo_safe_plus"]:
            return AllocationPolicy(0.10, 0.0, 1 * self.current_multiplier)
        elif profile == "conservative":
            return AllocationPolicy(0.30, 0.0, 2 * self.current_multiplier)
        elif profile == "balanced":
            return AllocationPolicy(0.60, 0.0, 3 * self.current_multiplier)
        elif profile == "aggressive":
            return AllocationPolicy(0.60, 0.30, 5 * self.current_multiplier)
            
        return AllocationPolicy(0.0, 0.0, 1)

    def apply_scaling_event(self, factor: int):
        """
        P8: predefined, mechanical scaling playbook.
        factor = 2 (2x), 5 (5x), 10 (10x)
        """
        logger.info(f"Scaling event triggered: {factor}x Capital")
        self.current_multiplier = factor
        if factor == 2:
            logger.info("2x Scale: Increasing markets, aggressive enabled, correlation caps relaxed slightly.")
        elif factor == 5:
            logger.info("5x Scale: Splitting capital into multiple sub-accounts. Adding redundancy.")
        elif factor >= 10:
            logger.info("10x Scale: Institutional discipline. Multi-broker (IBKR), Futures/FX added.")
