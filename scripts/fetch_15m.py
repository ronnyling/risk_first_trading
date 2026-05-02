"""Fetch ~55 days of SPY 15m historical data via yfinance.

yfinance limits 15m data to 60 days max.
Saves to data/historical/spy_15m_2m.csv with canonical schema.

Usage:
    python scripts/fetch_15m.py
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, timedelta
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

try:
    import yfinance as yf
except ImportError:
    print("yfinance not installed: pip install yfinance")
    sys.exit(1)

# 55 days to stay well within yfinance 60-day limit
start_date = (datetime.now() - timedelta(days=55)).strftime("%Y-%m-%d")
end_date = datetime.now().strftime("%Y-%m-%d")

print(f"Fetching SPY 15m bars from {start_date} to {end_date}")

ticker = yf.Ticker("SPY")
df = ticker.history(start=start_date, end=end_date, interval="15m")

if df.empty:
    print("ERROR: No 15m data returned")
    sys.exit(1)

print(f"Fetched {len(df)} bars")

out_path = Path(_root) / "data" / "historical" / "spy_15m_2m.csv"

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

print(f"Saved {len(df)} bars to {out_path}")
print(f"Date range: {df.index[0]} -> {df.index[-1]}")
print(f"Close range: {df['Close'].min():.2f} - {df['Close'].max():.2f}")