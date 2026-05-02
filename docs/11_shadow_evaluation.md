# Phase 8: Shadow-Mode Evaluation — Hermes v1 vs v2

**Status:** Enhanced — multi-symbol, rolling windows, distribution KPIs
**Date:** 2026-04-29

## Objective

Run Hermes v1 (rule-based, execution) and v2 (agent-based, observation) on the same bar sequence and compare behavioral KPIs. v1 drives all trading decisions. v2 runs passively — logged but never executed.

## Methodology

```
CSV bars → TradingEngine(v1) → v1 decisions + fills + metrics
         → HermesCoordinator(v2) → v2 decisions (logged only)
```

- Both versions process the same 101 bars from `data/sample/spy_1h.csv`
- v2 runs on each bar using a sliding window of up to 52 bars (Ichimoku warmup)
- Per-bar comparison logged to `logs/shadow_comparison_<ts>.json`
- Summary KPIs logged to `logs/shadow_kpis_<ts>.json`

## KPI Definitions

| KPI | Definition | Why It Matters |
|-----|-----------|----------------|
| **v2 CASH %** | % of bars where v2 issued CASH directive | Measures defensive posture frequency |
| **v2 SCALE_DOWN %** | % of bars with SCALE_DOWN | Measures caution without full exit |
| **v2 FULL %** | % of bars with FULL directive | Measures aggression/confidence |
| **v2 Avg Confidence** | Mean confidence across all bars | Measures information quality |
| **v2 Confidence p10/p50/p90** | Percentile distribution of confidence | Shows confidence spread and tail risk |
| **v2 Confidence Std** | Standard deviation of confidence | Measures consistency |
| **v2 Composite p10/p90** | Percentile distribution of composite score | Shows score spread |
| **v2 Regime Distribution** | Count per regime (trending/ranging/INDETERMINATE) | Shows regime sensitivity |
| **Regime Agreement %** | % of bars where v1 regime == v2 regime | Measures version alignment |
| **v1 CASH %** | % of bars with all-zero allocations | v1's defensive frequency |
| **v1 Signals Total** | Total signals generated | Trading activity |
| **Streaks (max/avg)** | Max and avg consecutive bars in same directive | Measures behavioral persistence |
| **Directive Transitions** | Count of directive changes (FULL↔SCALE↔CASH) | Measures decision stability |
| **Conflict Frequency** | % of bars where score dispersion > 0.5 | Measures agent disagreement |
| **Drawdown Response Bars** | Bars from negative composite to CASH directive | Measures reaction speed |

## Initial Run Findings (101 bars, SPY 1h)

### v1 (Execution)
- **CASH bars:** 100% — v1 produced almost no active allocations
- **Signals:** 1 total, 1 fill
- **Regimes:** Not exposed per-bar (runs internally)

### v2 (Shadow)
- **FULL bars:** 0.0% — v2 never went full conviction
- **SCALE_DOWN bars:** 88.1% — v2 was predominantly cautious
- **CASH bars:** 11.9% — v2 went defensive ~12 bars (bars 29-41, when agents detected negative composite)
- **Avg confidence:** 0.306 — consistently low confidence (below 0.5 threshold for FULL)
- **Regimes:** ranging (28 bars, first ~20), INDETERMINATE (73 bars, majority)

### Regime Agreement
- **0.0%** — v1 does not expose per-bar regime to comparison layer (runs internally in policy engine). This is expected and does not indicate disagreement.

### Key Observations

1. **v2 is appropriately cautious on limited data** — 101 bars is too few for Ichimoku/AMT agents to produce high-confidence signals
2. **v2 correctly transitions to CASH when agents disagree** — bars 29-41 show negative composite scores triggering CASH
3. **v2 NEVER reached FULL** — confidence remained below threshold throughout, suggesting agents need more data or real market dynamics
4. **v2 detected regime shift** — from "ranging" to "INDETERMINATE" at bar 28, indicating agent disagreement
5. **Behavior is monotonic** — no erratic switching between FULL/CASH, which is desirable

## What These Findings Mean

| Finding | Implication |
|---------|------------|
| v2 CASH at 11.9% | Agent disagreement correctly triggers defensive posture |
| v2 never FULL | Agents need more data or live market dynamics for high confidence |
| v2 avg confidence 0.306 | Expected on limited CSV data; should improve with live bars |
| v1 100% CASH | v1's rule-based policy is very conservative (by design) |
| No erratic switching | Hermes v2 state machine is working correctly |

## Next Steps

1. **Run on larger dataset** — Use full market hours data for more meaningful comparison
2. **Run on live IB shadow** — Compare v2 behavior on real market data
3. **Monitor CASH frequency** — Should stabilize at reasonable levels (not 100%, not 0%)
4. **Observe confidence trajectory** — Should increase with more data

## Promotion Criteria

Do NOT promote v2 to execution until:

- [ ] Confidence avg > 0.5 on live data
- [ ] CASH frequency between 5-30%
- [ ] No erratic FULL↔CASH switching (state transitions are gradual)
- [ ] Regime detection aligns with observable market structure
- [ ] 50+ trading days of shadow observation completed

## 50-Day Shadow Evaluation (2026-02-09 → 2026-04-28)

### Data Sources

| Symbol | Source | Bars | Resolution | Calendar Window | Notes |
|--------|--------|------|------------|-----------------|-------|
| SPY | yfinance (Yahoo) | 385 | 1h | Feb 9 – Apr 28, 2026 | US market hours only (~7.5h/day) |
| BTCUSD | ccxt (Binance) | 1,895 | 1h | Feb 9 – Apr 29, 2026 | 24/7 crypto market |

**Fetched via:** `scripts/fetch_shadow_data.py` (one-shot, frozen, no forward-fill)
**Saved to:** `data/shadow/spy_1h_50d.csv`, `data/shadow/btcusd_1h_50d.csv`

### Multi-Symbol Full Dataset Results

#### SPY (385 bars, ~55 trading days)

| Metric | Value | Target |
|--------|-------|--------|
| v2 FULL | 0.0% | — |
| v2 SCALE_DOWN | 93.5% | — |
| v2 CASH | 6.5% | 5-30% ✅ |
| Avg Confidence | 0.348 | >0.5 ❌ |
| Confidence p10/p50/p90 | 0.295 / 0.373 / 0.419 | — |
| Confidence Std | 0.090 | — |
| Composite p10/p90 | -0.650 / 0.680 | — |
| Regimes | ranging(35) + INDETERMINATE(350) | — |
| SCALE_DOWN streak max | 83 | — |
| CASH streak max | 7 | — |
| Transitions | 20 | — |
| Conflict freq | 78.2% | — |
| Drawdown response | 8 bars | — |

#### BTCUSD (1,895 bars, ~80 calendar days)

| Metric | Value | Target |
|--------|-------|--------|
| v2 FULL | 0.0% | — |
| v2 SCALE_DOWN | 94.8% | — |
| v2 CASH | 5.2% | 5-30% ⚠️ |
| Avg Confidence | 0.358 | >0.5 ❌ |
| Confidence p10/p50/p90 | 0.295 / 0.367 / 0.414 | — |
| Confidence Std | 0.057 | — |
| Composite p10/p90 | -0.665 / 0.737 | — |
| Regimes | ranging(331) + INDETERMINATE(1564) | — |
| SCALE_DOWN streak max | 331 | — |
| CASH streak max | 15 | — |
| Transitions | 58 | — |
| Conflict freq | 81.7% | — |
| Drawdown response | 304 bars | — |

### SPY Rolling Window Analysis (20-bar windows, 37 windows)

| Window | Avg Confidence | FULL% | SCALE% | CASH% | Transitions | Notes |
|--------|---------------|-------|--------|-------|-------------|-------|
| w0-20 | 0.014 | 0% | 100% | 0% | 0 | Warmup period |
| w10-30 | 0.176 | 0% | 100% | 0% | 0 | Agents learning |
| w20-40 | 0.338 | 0% | 95% | 5% | 2 | First CASH signal |
| w40-60 | 0.354 | 0% | 100% | 0% | 0 | Stable |
| w60-80 | 0.335 | 0% | 100% | 0% | 0 | Stable |
| w80-100 | 0.365 | 0% | 100% | 0% | 0 | Confidence rising |
| w100-120 | 0.364 | 0% | 75% | 25% | 1 | CASH cluster |
| w110-130 | 0.383 | 0% | 70% | 30% | 4 | Highest CASH |
| w120-140 | 0.381 | 0% | 90% | 10% | 4 | Transitioning |
| w140-160 | 0.390 | 0% | 95% | 5% | 1 | Stabilizing |
| w160-180 | 0.369 | 0% | 100% | 0% | 0 | Stable |
| w180-200 | 0.383 | 0% | 100% | 0% | 0 | Stable |
| w200-220 | 0.341 | 0% | 100% | 0% | 0 | Confidence dip |
| w220-240 | 0.365 | 0% | 95% | 5% | 2 | Minor CASH |
| w240-260 | 0.388 | 0% | 90% | 10% | 1 | — |
| w250-270 | 0.404 | 0% | 70% | 30% | 2 | Peak confidence |
| w260-280 | 0.400 | 0% | 75% | 25% | 3 | — |
| w270-290 | 0.383 | 0% | 95% | 5% | 2 | — |
| w280-300 | 0.373 | 0% | 100% | 0% | 0 | Stable |
| w300-320 | 0.362 | 0% | 100% | 0% | 0 | — |
| w320-340 | 0.379 | 0% | 100% | 0% | 0 | — |
| w340-360 | 0.346 | 0% | 95% | 5% | 2 | — |
| w350-370 | 0.345 | 0% | 95% | 5% | 2 | — |
| w360-380 | 0.350 | 0% | 65% | 35% | 2 | Final window |

**Confidence trend:** Warmup (0.014) → steady-state (0.33-0.40) → peak at w250-270 (0.404) → slight regression to 0.35

### 50-Day Key Observations

1. **v2 NEVER reached FULL conviction** — confidence peaked at 0.404 (window w250-270), still below 0.5 threshold
2. **CASH frequency within target band** — SPY 6.5%, BTCUSD 5.2% (target: 5-30%)
3. **No erratic switching** — SCALE_DOWN streaks dominant (83 max on SPY, 331 on BTCUSD)
4. **Confidence shows initial upward trend** — from warmup (0.014) to steady-state (~0.35-0.40), but plateaus
5. **Conflict frequency high** (78-82%) — agents consistently disagree on regime classification
6. **BTCUSD drawdown response much slower** — 304 bars vs SPY's 8 bars
7. **Regime detection stable** — primarily INDETERMINATE with occasional ranging
8. **Behavior is monotonic** — no erratic FULL↔CASH switching observed

### Promotion Criteria Status (50-Day)

- [ ] Confidence avg > 0.5 on live data — **NOT MET** (avg 0.348 SPY / 0.358 BTCUSD)
- [ ] CASH frequency between 5-30% — **MET** ✅ (6.5% SPY / 5.2% BTCUSD)
- [ ] No erratic FULL↔CASH switching — **MET** ✅ (monotonic behavior)
- [ ] Regime detection aligns with observable market structure — **PARTIAL** (high INDETERMINATE)
- [x] 50+ trading days of shadow observation completed — **MET** ✅ (55+ trading days)

**Overall: 2/5 criteria met, 1 partial, 2 not met. Promotion NOT recommended yet.**

## Multi-Symbol and Rolling Windows

Shadow comparison supports multiple CSV files and rolling window analysis:

```bash
# Single symbol
python scripts/shadow_compare.py --csv data/sample/spy_1h.csv

# Multi-symbol
python scripts/shadow_compare.py --csv data/sample/spy_1h.csv data/sample/btcusd_1h.csv

# With rolling windows (default window size: 20 bars)
python scripts/shadow_compare.py --csv data/sample/spy_1h.csv data/sample/btcusd_1h.csv --window 20
```

Rolling windows reveal:
- **Per-segment confidence trends** — is confidence improving over time?
- **Directive stability** — does the system oscillate or stay stable within windows?
- **Segment-to-segment transitions** — how often do directives change between windows?

### Multi-Symbol Aggregate KPIs

When running on multiple symbols, aggregate KPIs combine all bars across symbols into a single summary. Per-symbol KPIs are also reported individually.

## Running the Shadow Comparison

```bash
python scripts/shadow_compare.py --csv data/sample/spy_1h.csv
python scripts/shadow_compare.py --config config/engine.yaml
```

## Config Switch

```yaml
hermes:
  version: "v1"      # "v1" (default), "v2" (promote), "shadow" (observe)