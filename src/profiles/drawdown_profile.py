"""DrawdownProfile — re-exported from risk module for convenience.

The actual implementation lives in src/risk/drawdown_ladder.py.
This module exists to satisfy the plan's file structure and to keep
the profiles package self-contained for consumers.
"""

from src.risk.drawdown_ladder import DrawdownProfile

__all__ = ["DrawdownProfile"]
