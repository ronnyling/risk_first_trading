"""Fetch ~2 months of SPY 1H historical data via yfinance.

Saves to data/historical/spy_1h_2m.csv with canonical schema:
    timestamp, open, high, low, close, volume

Usage:
    python scripts/fetch_historical.py
    python scripts/fetch_historical.py --symbol SPY --months 2 --interval 1h
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

logger = logging.getLogger("fetch_historical")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch historical hourly bars via yfinance")
    parser.add_argument("--symbol", default="SPY", help="Symbol (default: SPY)")
    parser.add_argument("--months", type=int, default=2, help="Months of history (default: 2)")
    parser.add_argument("--interval", default="1h", help="Bar interval (default: 1h)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed: pip install yfinance")
        sys.exit(1)

    days_back = args.months * 30 + 10  # extra margin for weekends/holidays
    start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    end_date = datetime.now().strftime("%Y-%m-%d")

    logger.info("Fetching %s %s bars from %s to %s", args.symbol, args.interval, start_date, end_date)

    ticker = yf.Ticker(args.symbol)
    df = ticker.history(start=start_date, end=end_date, interval=args.interval)

    if df.empty:
        logger.error("No data returned for %s", args.symbol)
        sys.exit(1)

    logger.info("Fetched %d bars", len(df))

    # Ensure output directory exists
    out_dir = Path(_root) / "data" / "historical"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"{args.symbol.lower()}_{args.interval}_{args.months}m.csv"

    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])
        for ts, row in df.iterrows():
            writer.writerow([
                str(ts),
                f"{row['Open']:.6f}",
                f"{row['High']:.6f}",
                f"{row['Low']:.6f}",
                f"{row['Close']:.6f}",
                f"{row['Volume']:.0f}",
            ])

    logger.info("Saved %d bars to %s", len(df), out_path)

    # Print summary
    first_ts = str(df.index[0])
    last_ts = str(df.index[-1])
    logger.info("Date range: %s → %s", first_ts, last_ts)
    logger.info("Close range: %.2f – %.2f", df["Close"].min(), df["Close"].max())


if __name__ == "__main__":
    main()