"""CSV data loader for historical OHLCV bars."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from core.types import Bar

logger = logging.getLogger(__name__)


def load_csv(filepath: str | Path) -> list[Bar]:
    """Load OHLCV data from a CSV file.

    Expected columns: timestamp, open, high, low, close, volume
    Timestamp format: ISO 8601 or common datetime formats.
    """
    df = pd.read_csv(filepath)

    # Normalize column names
    df.columns = [c.strip().lower() for c in df.columns]

    required = {"timestamp", "open", "high", "low", "close", "volume"}
    if not required.issubset(set(df.columns)):
        missing = required - set(df.columns)
        raise ValueError(f"CSV missing required columns: {missing}")

    bars: list[Bar] = []
    for _, row in df.iterrows():
        ts = pd.to_datetime(row["timestamp"])
        bars.append(
            Bar(
                timestamp=ts.to_pydatetime(),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )
        )

    logger.info("Loaded %d bars from %s", len(bars), filepath)
    return bars


def load_csv_multi(
    htf_path: str | Path,
    ltf_path: str | Path | None = None,
) -> tuple[list[Bar], list[Bar] | None]:
    """Load HTF bars and optionally LTF bars from CSV files.

    Both files are normalized to UTC timestamps for cross-timezone safety.
    Returns (htf_bars, ltf_bars) or (htf_bars, None) if ltf_path is None/missing.

    Raises ValueError if LTF data is requested but file is missing or invalid.
    """
    htf_bars = load_csv(htf_path)

    if ltf_path is None:
        logger.info("No LTF path provided; returning HTF bars only")
        return htf_bars, None

    ltf_file = Path(ltf_path)
    if not ltf_file.exists():
        logger.warning("LTF file not found at %s; returning HTF bars only", ltf_path)
        return htf_bars, None

    ltf_bars = load_csv(ltf_file)

    # Validate LTF bar spacing (should be ~15 minutes between bars)
    if len(ltf_bars) >= 2:
        from datetime import timedelta

        gaps: list[timedelta] = []
        for i in range(1, min(20, len(ltf_bars))):
            gap = ltf_bars[i].timestamp - ltf_bars[i - 1].timestamp
            gaps.append(gap)
        median_gap = sorted(gaps)[len(gaps) // 2]
        expected = timedelta(minutes=15)
        tolerance = timedelta(minutes=5)
        if abs(median_gap - expected) > tolerance:
            logger.warning(
                "LTF bar spacing median=%s; expected ~15m. Data may not be 15m bars.",
                median_gap,
            )

    logger.info("Loaded %d HTF bars + %d LTF bars", len(htf_bars), len(ltf_bars))
    return htf_bars, ltf_bars
