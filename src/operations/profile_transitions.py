from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class ProfileMetrics:
    active_trading_days: int
    profit_factor: float
    max_drawdown: float
    equity_curve_slope: float  # Positive = >0
    in_protective_ladder: bool
    htf_regime_trending_ratio: float  # Ratio of recent time spent in TRENDING
    
    # FTMO specific
    ftmo_passed: bool
    ftmo_violations: int
    max_eval_dd_ratio: float  # Max DD / Allowed DD (e.g. 0.5 for 50%)
    survival_in_last_20pct: bool

class ProfileTransitionGate:
    """
    Implements the Profile Transition State Machine (CTA 16).
    Transitions occur sequentially strictly via rules:
    ftmo_safe -> ftmo_safe_plus -> conservative -> balanced -> aggressive
    """
    def __init__(self, initial_profile: str = "ftmo_safe"):
        self.current_profile = initial_profile
        
    def _log_transition(self, old: str, new: str, reason: str):
        logger.info(f"PROFILE TRANSITION: {old} -> {new}. Reason: {reason}")
        self.current_profile = new
        
    def evaluate(self, metrics: ProfileMetrics) -> str:
        old_profile = self.current_profile
        
        # 1. ftmo_safe -> ftmo_safe_plus
        if self.current_profile == "ftmo_safe":
            if (metrics.ftmo_passed and 
                metrics.ftmo_violations == 0 and
                metrics.max_eval_dd_ratio <= 0.5 and
                metrics.active_trading_days >= 10 and
                not metrics.survival_in_last_20pct):
                self._log_transition(self.current_profile, "ftmo_safe_plus", "Passed FTMO evaluation cleanly")
                
        # 2. ftmo_safe_plus -> conservative
        elif self.current_profile == "ftmo_safe_plus":
            if (metrics.active_trading_days >= 15 and
                metrics.profit_factor >= 1.2 and
                metrics.max_drawdown <= 0.001): # 0.10% = 0.001
                self._log_transition(self.current_profile, "conservative", "Validated funded account stability")
                
        # 3. conservative -> balanced
        elif self.current_profile == "conservative":
            if (metrics.active_trading_days >= 20 and
                metrics.equity_curve_slope > 0 and
                not metrics.in_protective_ladder):
                self._log_transition(self.current_profile, "balanced", "Core growth unlocked")
                
        # 4. balanced -> aggressive
        elif self.current_profile == "balanced":
            # Note: HTF regime predominantly TRENDING is modeled here as >0.6 ratio
            if (metrics.htf_regime_trending_ratio > 0.6 and
                metrics.profit_factor >= 1.3 and
                metrics.max_drawdown <= 0.0025): # 0.25% = 0.0025
                self._log_transition(self.current_profile, "aggressive", "Alpha extraction unlocked")
                
        # 5. Downgrade (aggressive -> balanced)
        elif self.current_profile == "aggressive":
            if metrics.max_drawdown > 0.0025 or metrics.htf_regime_trending_ratio <= 0.6:
                self._log_transition(self.current_profile, "balanced", "Downgrade: DD exceeded threshold or regime degraded")

        return self.current_profile
