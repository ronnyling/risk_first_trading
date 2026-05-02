"""Execution Guards module to enforce live trading discipline."""

import logging
from datetime import datetime, timedelta

from src.core.types import Order
from src.operations.market_eligibility import MarketEligibilityGate
from src.operations.concurrency import ConcurrencyGate

logger = logging.getLogger(__name__)

class ExecutionGuards:
    def __init__(self, market_gate: MarketEligibilityGate, concurrency_gate: ConcurrencyGate = None):
        self.market_gate = market_gate
        self.concurrency_gate = concurrency_gate or ConcurrencyGate()
        self.last_fill_times: dict[str, datetime] = {}
        self.cooldown_minutes = 15  # configurable cooldown
        
    def check_market_open(self, clock_data: dict) -> tuple[bool, str]:
        if not clock_data.get("is_open", False):
            return False, "Market is closed."
        return True, ""

    def check_buying_power(self, account_data: dict, estimated_cost: float) -> tuple[bool, str]:
        bp = account_data.get("buying_power", 0.0)
        if estimated_cost > bp:
            return False, f"Insufficient buying power: need {estimated_cost}, have {bp}"
        return True, ""

    def check_spread(self, ask: float, bid: float, atr: float, threshold: float = 0.1) -> tuple[bool, str]:
        if atr <= 0:
            return True, ""
        spread = ask - bid
        if spread > (atr * threshold):
            return False, f"Spread too wide: {spread:.4f} > max {atr*threshold:.4f}"
        return True, ""

    def check_cooldown(self, symbol: str) -> tuple[bool, str]:
        last_fill = self.last_fill_times.get(symbol)
        if last_fill:
            elapsed = (datetime.now() - last_fill).total_seconds() / 60.0
            if elapsed < self.cooldown_minutes:
                return False, f"Cooldown active for {symbol}: {elapsed:.1f}m < {self.cooldown_minutes}m"
        return True, ""

    def check_eligibility(self, symbol: str) -> tuple[bool, str]:
        if not self.market_gate.check_eligibility(symbol):
            return False, f"Market {symbol} is blacklisted or ineligible."
        return True, ""

    def check_concurrency(self, profile: str, symbol: str, risk_r: float, open_trades: list[dict]) -> tuple[bool, str]:
        """Validates Phase P7 Concurrency & Exposure rules."""
        return self.concurrency_gate.check_trade_allowed(profile, symbol, risk_r, open_trades)

    def record_fill(self, symbol: str):
        """Call this when a fill actually occurs to start cooldown."""
        self.last_fill_times[symbol] = datetime.now()
