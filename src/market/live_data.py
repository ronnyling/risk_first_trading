"""Live market data fetcher using yfinance.

Production live-data adapter for Hermes advisory runs.
Fetches OHLCV bars from Yahoo Finance for any symbol in the universe.

yfinance is considered a production live-data adapter for Hermes advisory
runs until the Alpaca data subscription is formally enabled.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from src.core.types import Bar

logger = logging.getLogger(__name__)


def _universe_to_yfinance_symbol(symbol: str) -> str:
    """Convert universe symbol to yfinance format.

    Convention:
        BTC/USD → BTC-USD
        ETH/USD → ETH-USD
        SOL/USD → SOL-USD
        SPY     → SPY (unchanged)
        BTC-USD → BTC-USD (unchanged)
    """
    return symbol.replace("/", "-")


def _is_bar_complete(bar_timestamp: str, bar_interval_minutes: int = 60) -> bool:
    """Check if a bar is complete (not currently forming).

    Only returns bars whose timestamp is strictly before
    now - bar_duration. Prevents agents from seeing partial candles.
    """
    try:
        if isinstance(bar_timestamp, datetime):
            bar_time = bar_timestamp
        else:
            bar_time = datetime.fromisoformat(str(bar_timestamp).replace("Z", "+00:00"))
        if bar_time.tzinfo is not None:
            bar_time = bar_time.replace(tzinfo=None)
        cutoff = datetime.now() - timedelta(minutes=bar_interval_minutes)
        return bar_time < cutoff
    except (ValueError, TypeError):
        return False


def fetch_bars(
    symbol: str,
    interval: str = "1h",
    count: int = 200,
    include_incomplete: bool = False,
) -> list[Bar]:
    """Fetch live OHLCV bars for a symbol via yfinance.

    Args:
        symbol: Universe symbol (e.g., "BTC/USD", "ETH/USD", "SPY").
        interval: Bar interval (default: "1h").
        count: Number of bars to fetch (default: 200).
        include_incomplete: If True, include current forming bar (default: False).

    Returns:
        list[Bar] with at least count bars of completed OHLCV data.

    Raises:
        RuntimeError: If yfinance returns empty data or symbol is invalid.

    Production status:
        yfinance is considered a production live-data adapter for Hermes
        advisory runs until the Alpaca data subscription is formally enabled.
    """
    try:
        import yfinance as yf
    except ImportError:
        raise RuntimeError(
            "yfinance is not installed. Install with: pip install yfinance"
        )

    yf_symbol = _universe_to_yfinance_symbol(symbol)
    days_back = max(count // 5, 60)  # extra margin for weekends/holidays
    start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")

    logger.info(
        "Fetching %d %s bars for %s (yfinance: %s) from %s",
        count, interval, symbol, yf_symbol, start_date,
    )

    try:
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(start=start_date, interval=interval)
    except Exception as e:
        raise RuntimeError(
            f"yfinance failed to fetch data for {symbol} (yfinance: {yf_symbol}): {e}"
        ) from e

    if df is None or df.empty:
        raise RuntimeError(
            f"yfinance returned empty data for {symbol} (yfinance: {yf_symbol}). "
            f"Symbol may be delisted, markets may be closed, or network may be unavailable."
        )

    # Convert to Bar objects
    bars: list[Bar] = []
    for ts, row in df.iterrows():
        ts_py = ts.to_pydatetime()
        bars.append(Bar(
            timestamp=ts_py,
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
            volume=float(row["Volume"]),
        ))

    # Filter incomplete bars unless requested
    if not include_incomplete:
        bars = [b for b in bars if _is_bar_complete(b.timestamp)]

    # Validate minimum bar count
    if len(bars) < 52:
        raise RuntimeError(
            f"Insufficient completed bars for {symbol}: got {len(bars)}, "
            f"need at least 52 (agents require minimum 52-bar window). "
            f"Markets may be closed or data unavailable."
        )

    logger.info(
        "Fetched %d completed bars for %s (yfinance: %s)",
        len(bars), symbol, yf_symbol,
    )

    return bars
