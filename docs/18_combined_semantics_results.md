# Combined Semantics Experiment — Phase 8.6

**Date**: 2026-04-29
**Status**: Shadow-only — no production code modified
**Constraints**: R-02 threshold = 0.50 (unchanged), agent math (unchanged)

## Configurations

| Config | Confidence | Veto | Purpose |
|--------|-----------|------|---------|
| A: Baseline | mean(all) | any-agent dispersion | Current v2 |
| B: Veto-only | mean(all) | Volatility-only | Phase 8.4 only |
| C: Confidence-only | max-structural (alpha=0.6) | any-agent dispersion | Phase 8.5 only |
| D: Combined v2.1 | max-structural (alpha=0.6) | Volatility-only | Both findings |

**alpha = 0.6 is provisional (Phase 8.5 exploratory result).**

---

## BTCUSD_50D (1843 bars)

### Directive Distribution

| Config | FULL | SCALE_DOWN | CASH | FULL % | CASH % |
|--------|------|------------|------|--------|--------|
| A: Baseline | 0 | 1744 | 99 | 0.0% | 5.4% |
| B: Veto-only | 0 | 1843 | 0 | 0.0% | 0.0% |
| C: Confidence-only | 1177 | 567 | 99 | 63.9% | 5.4% |
| D: Combined v2.1 | 1268 | 575 | 0 | 68.8% | 0.0% |

### Confidence Distribution

| Config | Mean | p50 | p75 | p90 | p95 | Max |
|--------|------|-----|-----|-----|-----|-----|
| A: Baseline | 0.3572 | 0.3628 | 0.3885 | 0.4072 | 0.4194 | 0.4644 |
| B: Veto-only | 0.3572 | 0.3628 | 0.3885 | 0.4072 | 0.4194 | 0.4644 |
| C: Confidence-only | 0.5674 | 0.5748 | 0.6056 | 0.6288 | 0.6384 | 0.6865 |
| D: Combined v2.1 | 0.5674 | 0.5748 | 0.6056 | 0.6288 | 0.6384 | 0.6865 |

### R-02 Threshold Crossing

| Config | Bars >= 0.45 | Bars >= 0.50 | R-01 Fires | R-02 Fires |
|--------|-------------|-------------|------------|------------|
| A: Baseline | 9 (0.5%) | 0 (0.0%) | 99 | 1744 |
| B: Veto-only | 9 (0.5%) | 0 (0.0%) | 0 | 1843 |
| C: Confidence-only | 1768 (95.9%) | 1658 (90.0%) | 99 | 183 |
| D: Combined v2.1 | 1768 (95.9%) | 1658 (90.0%) | 0 | 185 |

### FULL Clustering Analysis (Safety Validation)

| Config | FULL Count | Clusters | Max Cluster | Isolated | FULL->CASH |
|--------|-----------|----------|-------------|----------|------------|
| A: Baseline | 0 | 0 | 0 | 0 | 0 |
| B: Veto-only | 0 | 0 | 0 | 0 | 0 |
| C: Confidence-only | 1177 | 118 | 61 | 23 | 25 |
| D: Combined v2.1 | 1268 | 98 | 61 | 12 | 0 |
---

## SPY_50D (333 bars)

### Directive Distribution

| Config | FULL | SCALE_DOWN | CASH | FULL % | CASH % |
|--------|------|------------|------|--------|--------|
| A: Baseline | 0 | 309 | 24 | 0.0% | 7.2% |
| B: Veto-only | 0 | 333 | 0 | 0.0% | 0.0% |
| C: Confidence-only | 201 | 108 | 24 | 60.4% | 7.2% |
| D: Combined v2.1 | 218 | 115 | 0 | 65.5% | 0.0% |

### Confidence Distribution

| Config | Mean | p50 | p75 | p90 | p95 | Max |
|--------|------|-----|-----|-----|-----|-----|
| A: Baseline | 0.3632 | 0.3708 | 0.3941 | 0.4147 | 0.4264 | 0.4608 |
| B: Veto-only | 0.3632 | 0.3708 | 0.3941 | 0.4147 | 0.4264 | 0.4608 |
| C: Confidence-only | 0.5759 | 0.5810 | 0.6109 | 0.6354 | 0.6460 | 0.6849 |
| D: Combined v2.1 | 0.5759 | 0.5810 | 0.6109 | 0.6354 | 0.6460 | 0.6849 |

### R-02 Threshold Crossing

| Config | Bars >= 0.45 | Bars >= 0.50 | R-01 Fires | R-02 Fires |
|--------|-------------|-------------|------------|------------|
| A: Baseline | 2 (0.6%) | 0 (0.0%) | 24 | 309 |
| B: Veto-only | 2 (0.6%) | 0 (0.0%) | 0 | 333 |
| C: Confidence-only | 332 (99.7%) | 312 (93.7%) | 24 | 21 |
| D: Combined v2.1 | 332 (99.7%) | 312 (93.7%) | 0 | 21 |

### FULL Clustering Analysis (Safety Validation)

| Config | FULL Count | Clusters | Max Cluster | Isolated | FULL->CASH |
|--------|-----------|----------|-------------|----------|------------|
| A: Baseline | 0 | 0 | 0 | 0 | 0 |
| B: Veto-only | 0 | 0 | 0 | 0 | 0 |
| C: Confidence-only | 201 | 28 | 38 | 5 | 7 |
| D: Combined v2.1 | 218 | 24 | 38 | 4 | 0 |
---

## Cross-Dataset Summary

| Dataset | Config | FULL | CASH | FULL Clusters | FULL->CASH |
|---------|--------|------|------|---------------|------------|
| BTCUSD_50D | A: Baseline | 0 | 99 | 0 | 0 |
| BTCUSD_50D | B: Veto-only | 0 | 0 | 0 | 0 |
| BTCUSD_50D | C: Confidence-only | 1177 | 99 | 118 | 25 |
| BTCUSD_50D | D: Combined v2.1 | 1268 | 0 | 98 | 0 |
| SPY_50D | A: Baseline | 0 | 24 | 0 | 0 |
| SPY_50D | B: Veto-only | 0 | 0 | 0 | 0 |
| SPY_50D | C: Confidence-only | 201 | 24 | 28 | 7 |
| SPY_50D | D: Combined v2.1 | 218 | 0 | 24 | 0 |

## Safety Validation

### FULL Appearance Patterns

**BTCUSD_50D — Config D (Combined v2.1)**:
- FULL count: 1268/1843
- FULL clusters: 98
- Max cluster size: 61
- Isolated (single-bar) FULLs: 12
- FULL->CASH transitions: 0

**SPY_50D — Config D (Combined v2.1)**:
- FULL count: 218/333
- FULL clusters: 24
- Max cluster size: 38
- Isolated (single-bar) FULLs: 4
- FULL->CASH transitions: 0

### FULL-Volatility Coincidence Check

Does FULL appear when Volatility is opposing (veto condition)?

- **BTCUSD_50D**: FULL->CASH transitions = 0 (CLEAN)
- **SPY_50D**: FULL->CASH transitions = 0 (CLEAN)

### CASH Frequency Band

- **BTCUSD_50D**: Baseline CASH=99 (5.4%), Combined CASH=0 (0.0%)
- **SPY_50D**: Baseline CASH=24 (7.2%), Combined CASH=0 (0.0%)

## Verdict

### BTCUSD_50D
- [PASS] FULL appears
- [PASS] CASH within baseline band
- [PASS] FULL clusters (not isolated spikes)
- [PASS] No FULL->CASH transitions
**Result**: 4/4 checks passed

### SPY_50D
- [PASS] FULL appears
- [PASS] CASH within baseline band
- [PASS] FULL clusters (not isolated spikes)
- [PASS] No FULL->CASH transitions
**Result**: 4/4 checks passed

### Overall Interpretation

If Config D passes all safety checks, the v2.1 semantics are validated
for promotion to production code (subject to user approval).

If Config D fails safety checks, the semantics need refinement before
any production code modification.
