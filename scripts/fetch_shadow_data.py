"""Fetch 50-day 1h OHLCV datasets for shadow evaluation.

Usage:
    python scripts/fetch_shadow_data.py

Outputs:
    data/shadow/spy_1h_50d.csv
    data/shadow/btcusd_1h_50d.csv

Constraints:
    - No synthetic data, no forward-fill, no back-fill
    - Gaps preserved as-is
    - Same calendar window for both symbols
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("data/shadow")
MIN_SPY_BARS = 350
MIN_BTC_BARS = 1000
TRADING_DAYS = 50


def fetch_spy() -> pd.DataFrame:
    """Fetch SPY 1h bars via yfinance for last 50 complete trading days."""
    import yfinance as yf

    logger.info("Fetching SPY 1h data via yfinance...")

    # Fetch extra calendar days to ensure we get 50 trading days
    # ~80 calendar days covers 50 trading days with weekends/holidays
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=80)

    ticker = yf.Ticker("SPY")
    df = ticker.history(
        start=start_dt.strftime("%Y-%m-%d"),
        end=end_dt.strftime("%Y-%m-%d"),
        interval="1h",
        auto_adjust=True,
    )

    if df.empty:
        raise RuntimeError("yfinance returned empty DataFrame for SPY")

    # Normalize to standard schema
    df = df.reset_index()
    # yfinance columns: Datetime, Open, High, Low, Close, Volume
    # The index name may vary; find the datetime column
    dt_col = None
    for col in df.columns:
        if "date" in str(col).lower() or "datetime" in str(col).lower():
            dt_col = col
            break
    if dt_col is None:
        dt_col = df.columns[0]

    result = pd.DataFrame({
        "timestamp": pd.to_datetime(df[dt_col]),
        "open": df["Open"].astype(float),
        "high": df["High"].astype(float),
        "low": df["Low"].astype(float),
        "close": df["Close"].astype(float),
        "volume": df["Volume"].astype(float),
    })

    # Remove timezone info for consistency
    if result["timestamp"].dt.tz is not None:
        result["timestamp"] = result["timestamp"].dt.tz_localize(None)

    # Sort by timestamp ascending
    result = result.sort_values("timestamp").reset_index(drop=True)

    logger.info("SPY: fetched %d bars, range %s to %s",
                len(result), result["timestamp"].iloc[0], result["timestamp"].iloc[-1])
    return result


def fetch_btcusd(start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
    """Fetch BTCUSD 1h bars via ccxt (Binance) for the same calendar window."""
    import ccxt

    logger.info("Fetching BTCUSD 1h data via ccxt (Binance)...")
    exchange = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "spot"}})

    # Convert to milliseconds for ccxt
    since_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    all_candles: list[list] = []
    limit = 1000  # Binance max per request

    while since_ms < end_ms:
        candles = exchange.fetch_ohlcv("BTC/USDT", "1h", since=since_ms, limit=limit)
        if not candles:
            break

        all_candles.extend(candles)
        last_ts = candles[-1][0]

        # Move past the last candle
        since_ms = last_ts + 3600 * 1000  # +1 hour in ms

        if len(candles) < limit:
            break

        # Rate limit courtesy
        time.sleep(0.5)

    if not all_candles:
        raise RuntimeError("ccxt returned no candles for BTC/USDT")

    result = pd.DataFrame(all_candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
    result["timestamp"] = pd.to_datetime(result["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
    result = result.sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)

    logger.info("BTCUSD: fetched %d bars, range %s to %s",
                len(result), result["timestamp"].iloc[0], result["timestamp"].iloc[-1])
    return result


def validate(df: pd.DataFrame, name: str, min_bars: int) -> None:
    """Validate fetched data."""
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{name}: missing columns: {missing}")

    # Allow 5% tolerance on bar count (trading holidays, early closes)
    min_acceptable = int(min_bars * 0.95)
    if len(df) < min_acceptable:
        raise ValueError(f"{name}: only {len(df)} bars, expected >= {min_acceptable}")
    elif len(df) < min_bars:
        logger.warning("%s: %d bars below target %d (holiday/early close gap acceptable)",
                       name, len(df), min_bars)

    # Check for NaN in OHLC
    ohlc_cols = ["open", "high", "low", "close"]
    nan_count = df[ohlc_cols].isna().sum().sum()
    if nan_count > 0:
        logger.warning("%s: %d NaN values in OHLC — gaps preserved as-is", name, nan_count)

    logger.info("%s: validated — %d bars, schema OK", name, len(df))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Fetch SPY to get the calendar window
    spy_df = fetch_spy()

    # Use SPY's date range to define the window for BTC
    spy_start = spy_df["timestamp"].iloc[0]
    spy_end = spy_df["timestamp"].iloc[-1]
    logger.info("Calendar window: %s to %s", spy_start, spy_end)

    # Step 2: Fetch BTCUSD for the same window
    btc_df = fetch_btcusd(spy_start, spy_end)

    # Step 3: Validate
    validate(spy_df, "SPY", MIN_SPY_BARS)
    validate(btc_df, "BTCUSD", MIN_BTC_BARS)

    # Step 4: Save
    spy_path = OUTPUT_DIR / "spy_1h_50d.csv"
    btc_path = OUTPUT_DIR / "btcusd_1h_50d.csv"

    spy_df.to_csv(spy_path, index=False)
    btc_df.to_csv(btc_path, index=False)

    logger.info("Saved: %s (%d bars)", spy_path, len(spy_df))
    logger.info("Saved: %s (%d bars)", btc_path, len(btc_df))
    logger.info("Done. Files are frozen — do not modify.")


if __name__ == "__main__":
    main()