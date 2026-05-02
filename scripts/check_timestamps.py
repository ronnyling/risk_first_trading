"""Diagnostic: Check timestamp formats in both CSVs."""
import csv
from pathlib import Path

root = Path(__file__).resolve().parent.parent

print("=== 1H CSV (first 5 rows) ===")
with open(root / "data/historical/spy_1h_2m.csv") as f:
    r = csv.reader(f)
    header = next(r)
    print(f"Header: {header}")
    for i, row in enumerate(r):
        if i >= 5:
            break
        print(f"  Row {i}: {row[0]}")

print("\n=== 15m CSV (first 10 rows) ===")
with open(root / "data/historical/spy_15m_2m.csv") as f:
    r = csv.reader(f)
    header = next(r)
    print(f"Header: {header}")
    for i, row in enumerate(r):
        if i >= 10:
            break
        print(f"  Row {i}: {row[0]}")

print("\n=== 15m CSV (rows 3-6, to see alignment with 1H) ===")
with open(root / "data/historical/spy_15m_2m.csv") as f:
    r = csv.reader(f)
    next(r)  # skip header
    for i, row in enumerate(r):
        if 3 <= i <= 6:
            print(f"  Row {i}: {row[0]}")