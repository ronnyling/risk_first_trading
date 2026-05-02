from dataclasses import dataclass
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)

@dataclass
class ProfileCaps:
    max_open_trades: int
    max_total_risk_r: float
    per_symbol_cap: int

class ConcurrencyGate:
    """
    Implements Phase P7 - Concurrency & Exposure Review.
    Captures opportunities without increasing per-trade risk by mechanically 
    managing idle capital leakage through strict profile-aware concurrency rules.
    """
    def __init__(self):
        # Concurrency Matrix
        self.caps = {
            "ftmo_safe": ProfileCaps(1, 0.5, 1),
            "ftmo_safe_plus": ProfileCaps(2, 1.0, 1), # 1-2
            "conservative": ProfileCaps(2, 1.5, 1),
            "balanced": ProfileCaps(3, 2.0, 2),
            "aggressive": ProfileCaps(5, 3.0, 2)
        }
        
        # Example Correlation Buckets
        self.buckets = {
            "AAPL": "TECH",
            "MSFT": "TECH",
            "NVDA": "TECH",
            "QQQ": "TECH",
            "SPY": "INDEX",
            "DIA": "INDEX",
            "EUR/USD": "FX_MAJOR",
            "GBP/USD": "FX_MAJOR",
            "USD/JPY": "FX_MAJOR",
            "BTC/USD": "CRYPTO",
            "ETH/USD": "CRYPTO"
        }

    def _get_bucket(self, symbol: str) -> str:
        return self.buckets.get(symbol, "ISOLATED")

    def check_trade_allowed(self, profile: str, new_trade_symbol: str, new_trade_risk_r: float, open_trades: List[Dict]) -> tuple[bool, str]:
        """
        open_trades list of dicts:
        {
            "symbol": "AAPL",
            "risk_r": 0.5
        }
        """
        caps = self.caps.get(profile)
        if not caps:
            # Fallback to ftmo_safe if unknown
            caps = self.caps["ftmo_safe"]
            
        current_open_trades = len(open_trades)
        current_total_risk_r = sum(t.get("risk_r", 0.0) for t in open_trades)
        
        symbol_counts = {}
        bucket_counts = {}
        for t in open_trades:
            sym = t.get("symbol")
            symbol_counts[sym] = symbol_counts.get(sym, 0) + 1
            bucket = self._get_bucket(sym)
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
            
        # 1. Max Open Trades
        if current_open_trades >= caps.max_open_trades:
            reason = f"Concurrency limit reached ({caps.max_open_trades})"
            logger.info(f"Trade blocked: {reason}")
            return False, reason
            
        # 2. Max Total Risk
        if (current_total_risk_r + new_trade_risk_r) > caps.max_total_risk_r:
            reason = f"Exposure limit reached. Total would be {current_total_risk_r + new_trade_risk_r}R > {caps.max_total_risk_r}R"
            logger.info(f"Trade blocked: {reason}")
            return False, reason
            
        # 3. Per-Symbol Cap
        if symbol_counts.get(new_trade_symbol, 0) >= caps.per_symbol_cap:
            reason = f"Per-symbol cap reached for {new_trade_symbol} ({caps.per_symbol_cap})"
            logger.info(f"Trade blocked: {reason}")
            return False, reason
            
        # 4. Correlation Bucket Blocking
        new_bucket = self._get_bucket(new_trade_symbol)
        if new_bucket != "ISOLATED":
            bucket_count = bucket_counts.get(new_bucket, 0)
            if profile == "balanced" and bucket_count >= 1:
                reason = f"Correlation bucket '{new_bucket}' cap reached for balanced (1)"
                logger.info(f"Trade blocked: {reason}")
                return False, reason
            elif profile == "aggressive" and bucket_count >= 2:
                reason = f"Correlation bucket '{new_bucket}' cap reached for aggressive (2)"
                logger.info(f"Trade blocked: {reason}")
                return False, reason
            elif profile not in ["balanced", "aggressive"] and bucket_count >= 1:
                reason = f"Correlation bucket '{new_bucket}' cap reached for {profile} (1)"
                logger.info(f"Trade blocked: {reason}")
                return False, reason
                
        return True, ""
