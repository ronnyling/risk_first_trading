from dataclasses import dataclass
from typing import List
import logging

logger = logging.getLogger(__name__)

@dataclass
class MarketStats:
    symbol: str
    profit_factor: float
    max_drawdown_pct: float
    trade_count: int

class MarketEligibilityGate:
    """
    Implements Market Eligibility Rules (CTA 17).
    Maintains a whitelist, blacklist, and executes a sanity check for new markets.
    """
    def __init__(self):
        self.whitelist = {
            "EUR/USD", "GBP/USD", "USD/JPY",  # Major FX
            "ES", "NQ",                       # Index CFDs
            "BTC/USD", "ETH/USD"              # Crypto Majors
        }
        self.blacklist = set()
        
    def check_eligibility(self, market: str) -> bool:
        if market in self.whitelist:
            return True
        if market in self.blacklist:
            logger.warning(f"Market {market} blocked (Blacklisted)")
            return False
            
        # Conditionally eligible - needs sanity check runtime evaluation
        return True
        
    def run_sanity_check(self, stats: MarketStats) -> bool:
        """
        Runs the fail-gracefully sanity check on conditional markets.
        Uses balanced/aggressive historical/recent stats.
        """
        if stats.symbol in self.whitelist:
            return True
            
        # Catastrophic failure -> Blacklist
        if stats.profit_factor < 0.5 or stats.max_drawdown_pct > 0.15 or stats.trade_count > 500:
            logger.warning(f"Market {stats.symbol} failed sanity check catastrophically. Blacklisting.")
            self.blacklist.add(stats.symbol)
            return False
            
        # Acceptable bounds (near 1.0 PF, bounded DD)
        if stats.profit_factor >= 0.9 and stats.max_drawdown_pct <= 0.10:
            return True
            
        # If criteria fail but DD remains small -> Acceptable (fails gracefully)
        if stats.max_drawdown_pct <= 0.05:
            logger.info(f"Market {stats.symbol} failed PF target but failed gracefully (DD small). Allowed.")
            return True
            
        logger.warning(f"Market {stats.symbol} rejected by sanity check.")
        return False
