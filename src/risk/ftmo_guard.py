"""FTMO-style compliance guard.

Enforces hard limits independent of the drawdown ladder:
- Daily loss limit: 5% of starting daily equity
- Max drawdown: 10% of peak equity
- Profit target tracking
- Consistency rule (optional)

FTMOGuard can force HALT even if DrawdownLadder says GROWTH.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FTMOConfig:
    """FTMO evaluation rules."""
    max_daily_loss_pct: float = 0.05       # 5% of starting daily equity
    max_total_drawdown_pct: float = 0.10   # 10% of peak equity
    profit_target_pct: float = 0.10        # 10% target to pass
    consistency_max_pct: float = 0.05      # no single trade > 5% of total profit


@dataclass(frozen=True)
class FTMOCheck:
    """Result of FTMO compliance check."""
    compliant: bool
    daily_loss_remaining: float     # remaining daily loss budget (fraction)
    total_drawdown_remaining: float # remaining DD budget (fraction)
    violations: tuple[str, ...]     # immutable list of violation descriptions
    action: str                     # "ALLOW" | "REDUCE" | "HALT"


@dataclass
class FTMOGuard:
    """Enforces FTMO-style evaluation rules.

    Responsibilities:
    - Track daily equity start/peak
    - Enforce daily loss limit
    - Enforce max drawdown limit
    - Produce compliance status per bar

    Usage:
        guard = FTMOGuard(FTMOConfig())
        guard.update_daily(equity=100_000, bar_timestamp=bar.timestamp)
        check = guard.check(equity=current_equity, peak_equity=peak_equity)
        if not check.compliant:
            # Force protective sizing or HALT
    """

    config: FTMOConfig = field(default_factory=FTMOConfig)
    # Internal tracking state (mutable)
    _current_date: date | None = field(default=None, repr=False)
    _daily_start_equity: float = field(default=0.0, repr=False)
    _daily_peak_equity: float = field(default=0.0, repr=False)
    _violations: list[str] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        """Initialize mutable tracking state."""
        self._current_date = None
        self._daily_start_equity = 0.0
        self._daily_peak_equity = 0.0
        self._violations = []

    def update_daily(self, equity: float, bar_timestamp: datetime | date) -> None:
        """Reset daily tracking at day boundary.

        Args:
            equity: Current equity value.
            bar_timestamp: Bar's timestamp (datetime or date).
        """
        # Extract date from datetime or use date directly
        if isinstance(bar_timestamp, datetime):
            bar_date = bar_timestamp.date()
        else:
            bar_date = bar_timestamp

        if self._current_date is None or bar_date != self._current_date:
            # New day — reset daily tracking
            self._current_date = bar_date
            self._daily_start_equity = equity
            self._daily_peak_equity = equity
            logger.debug(
                "FTMO daily reset: date=%s, start_equity=%.2f",
                bar_date, equity,
            )
        else:
            # Same day — update peak
            if equity > self._daily_peak_equity:
                self._daily_peak_equity = equity

    def check(self, equity: float, peak_equity: float) -> FTMOCheck:
        """Check FTMO compliance.

        Args:
            equity: Current equity.
            peak_equity: All-time peak equity.

        Returns:
            FTMOCheck with compliance status and remaining budgets.
        """
        violations: list[str] = []
        action = "ALLOW"

        # --- Daily loss check ---
        if self._daily_start_equity > 0:
            daily_loss = (self._daily_start_equity - equity) / self._daily_start_equity
            daily_loss = max(0.0, daily_loss)  # only count losses
            daily_remaining = max(0.0, self.config.max_daily_loss_pct - daily_loss)
        else:
            daily_loss = 0.0
            daily_remaining = self.config.max_daily_loss_pct

        if daily_loss >= self.config.max_daily_loss_pct:
            violations.append(
                f"Daily loss {daily_loss:.4f} >= limit {self.config.max_daily_loss_pct:.4f}"
            )
            action = "HALT"
        elif daily_loss >= self.config.max_daily_loss_pct * 0.8:
            # 80% of daily limit reached — reduce
            violations.append(
                f"Daily loss {daily_loss:.4f} approaching limit "
                f"({self.config.max_daily_loss_pct:.4f})"
            )
            if action != "HALT":
                action = "REDUCE"

        # --- Total drawdown check ---
        if peak_equity > 0:
            total_dd = (peak_equity - equity) / peak_equity
            total_dd = max(0.0, total_dd)
            dd_remaining = max(0.0, self.config.max_total_drawdown_pct - total_dd)
        else:
            total_dd = 0.0
            dd_remaining = self.config.max_total_drawdown_pct

        if total_dd >= self.config.max_total_drawdown_pct:
            violations.append(
                f"Total drawdown {total_dd:.4f} >= limit {self.config.max_total_drawdown_pct:.4f}"
            )
            action = "HALT"
        elif total_dd >= self.config.max_total_drawdown_pct * 0.8:
            violations.append(
                f"Total drawdown {total_dd:.4f} approaching limit "
                f"({self.config.max_total_drawdown_pct:.4f})"
            )
            if action != "HALT":
                action = "REDUCE"

        is_compliant = len(violations) == 0

        if violations:
            for v in violations:
                logger.warning("FTMO violation: %s", v)

        return FTMOCheck(
            compliant=is_compliant,
            daily_loss_remaining=daily_remaining,
            total_drawdown_remaining=dd_remaining,
            violations=tuple(violations),
            action=action,
        )

    def is_compliant(self, equity: float, peak_equity: float) -> bool:
        """Quick compliance check (no details)."""
        return self.check(equity, peak_equity).compliant
