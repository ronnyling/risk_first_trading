"""ShadowDataAdapter — parallel data-source comparison.

Runs two MarketDataAdapters (primary + secondary) in lockstep.
Returns only primary bars to the engine; logs differences for validation.

Usage:
    shadow = ShadowDataAdapter(primary=csv_adapter, secondary=ib_adapter)
    shadow.start()
    bar = shadow.get_next_bar()  # returns CSV bar, logs IB comparison
    shadow.stop()
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.core.types import Bar
from src.market.adapter import MarketDataAdapter

logger = logging.getLogger(__name__)

# Dedicated comparator logger — writes to a separate JSON file
_comparator_logger = logging.getLogger("data.comparator")


class ShadowDataAdapter(MarketDataAdapter):
    """Runs two adapters in parallel, logs differences, returns primary bars.

    Primary drives trading. Secondary is collected for comparison.
    Differences are logged as structured JSON for offline analysis.
    """

    def __init__(
        self,
        primary: MarketDataAdapter,
        secondary: MarketDataAdapter,
        log_path: str | Path | None = None,
    ) -> None:
        super().__init__()
        self._primary = primary
        self._secondary = secondary
        self._comparisons: list[dict] = []
        self._log_path = Path(log_path) if log_path else None

    def start(self) -> None:
        """Start both adapters."""
        self._primary.start()
        self._secondary.start()
        self._bars_processed = 0
        self._comparisons = []
        logger.info(
            "ShadowDataAdapter started: primary=%s, secondary=%s",
            self._primary.source_name,
            self._secondary.source_name,
        )

    def stop(self) -> None:
        """Stop both adapters and flush comparison log."""
        self._primary.stop()
        self._secondary.stop()

        # Write comparison log
        if self._log_path and self._comparisons:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "w") as f:
                for entry in self._comparisons:
                    f.write(json.dumps(entry, default=str) + "\n")
            logger.info(
                "ShadowDataAdapter: %d comparisons written to %s",
                len(self._comparisons), self._log_path,
            )

        # Summary stats
        if self._comparisons:
            deltas = [c.get("close_delta", 0) for c in self._comparisons if c.get("close_delta") is not None]
            if deltas:
                avg_delta = sum(abs(d) for d in deltas) / len(deltas)
                max_delta = max(abs(d) for d in deltas)
                missing = sum(1 for c in self._comparisons if c.get("secondary_missing"))
                logger.info(
                    "ShadowDataAdapter summary: %d comparisons, avg|Δclose|=%.4f, max|Δclose|=%.4f, missing_bars=%d",
                    len(deltas), avg_delta, max_delta, missing,
                )

        logger.info(
            "ShadowDataAdapter stopped: %d bars processed",
            self._bars_processed,
        )

    def get_next_bar(self) -> Bar | None:
        """Get next bar from primary, compare with secondary if available."""
        primary_bar = self._primary.get_next_bar()
        if primary_bar is None:
            return None

        # Try to get corresponding secondary bar
        secondary_bar = self._secondary.get_next_bar()

        # Log comparison
        comparison = {
            "timestamp": primary_bar.timestamp.isoformat(),
            "primary_source": self._primary.source_name,
            "secondary_source": self._secondary.source_name,
        }

        if secondary_bar is not None:
            comparison["primary_close"] = primary_bar.close
            comparison["secondary_close"] = secondary_bar.close
            comparison["close_delta"] = round(primary_bar.close - secondary_bar.close, 6)
            comparison["primary_volume"] = primary_bar.volume
            comparison["secondary_volume"] = secondary_bar.volume
            comparison["ts_match"] = primary_bar.timestamp == secondary_bar.timestamp

            if abs(comparison["close_delta"]) > 0.01:
                logger.warning(
                    "Bar delta: %s primary=%.2f secondary=%.2f delta=%.4f",
                    primary_bar.timestamp, primary_bar.close,
                    secondary_bar.close, comparison["close_delta"],
                )
        else:
            comparison["secondary_missing"] = True
            logger.debug("Secondary has no bar at %s", primary_bar.timestamp)

        self._comparisons.append(comparison)
        _comparator_logger.info(json.dumps(comparison, default=str))

        self._increment_bar_count()
        return primary_bar

    def get_history(self, n: int) -> list[Bar]:
        """Delegate to primary adapter."""
        return self._primary.get_history(n)

    @property
    def source_name(self) -> str:
        return f"shadow({self._primary.source_name}+{self._secondary.source_name})"

    @property
    def is_live(self) -> bool:
        return self._primary.is_live

    @property
    def comparison_count(self) -> int:
        return len(self._comparisons)

    @property
    def comparisons(self) -> list[dict]:
        return list(self._comparisons)