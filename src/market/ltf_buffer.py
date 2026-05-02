"""LTF Buffer — Maps closed 15m bars to their parent 1H bar windows.

Used by dual_mtf backtest to feed true 15m data to the LTFRegimeDetector
instead of reusing 1H bars (which is semantically wrong).

Rules:
- Each 1H bar covers exactly 4 15m bars
- Only closed bars are exposed (no future data)
- UTC-normalized timestamps for cross-timezone safety
"""

from __future__ import annotations

import logging
from datetime import timedelta
from src.core.types import Bar

logger = logging.getLogger(__name__)

# 15m = 15 minutes; 4 per 1H bar
_15M = timedelta(minutes=15)
_1H = timedelta(hours=1)


def _to_utc_naive(ts) -> "datetime":
    """Convert timestamp to timezone-naive UTC datetime for consistent comparison."""
    import pandas as pd

    dt = pd.to_datetime(ts)
    if dt.tzinfo is not None:
        dt = dt.tz_convert("UTC").tz_localize(None)
    return dt.to_pydatetime()


class LTFBuffer:
    """Rolling buffer of closed 15m bars aligned to 1H bar boundaries.

    Given a list of 15m bars, provides:
    - get_bars_for_htf(htf_bar): the 4 closed 15m bars in this 1H window
    - get_recent(n): last n closed 15m bars (for LTFRegimeDetector warm-up)
    """

    def __init__(self, ltf_bars: list[Bar]) -> None:
        # Pre-normalize all LTF timestamps to UTC naive
        self._ltf_bars = ltf_bars
        self._timestamps = [_to_utc_naive(b.timestamp) for b in ltf_bars]
        logger.info(
            "LTFBuffer initialized with %d bars (%s to %s)",
            len(ltf_bars),
            self._timestamps[0] if self._timestamps else "N/A",
            self._timestamps[-1] if self._timestamps else "N/A",
        )

    def get_bars_for_htf(self, htf_bar: Bar) -> list[Bar]:
        """Return closed 15m bars that fall within [htf_ts, htf_ts + 1h).

        A 15m bar at timestamp T is considered to "belong" to the 1H bar
        if T >= htf_ts AND T < htf_ts + 1h.

        Returns up to 4 bars (one per 15m slot).
        """
        htf_ts = _to_utc_naive(htf_bar.timestamp)
        htf_end = htf_ts + _1H

        result: list[Bar] = []
        for i, ts in enumerate(self._timestamps):
            if ts >= htf_ts and ts < htf_end:
                result.append(self._ltf_bars[i])
            elif ts >= htf_end:
                break  # sorted, no more matches

        return result

    def get_recent(self, n: int) -> list[Bar]:
        """Return last n closed 15m bars from the entire buffer."""
        return self._ltf_bars[-n:] if n <= len(self._ltf_bars) else list(self._ltf_bars)

    @property
    def total_bars(self) -> int:
        return len(self._ltf_bars)

    @property
    def ltf_data_available(self) -> bool:
        return len(self._ltf_bars) > 0