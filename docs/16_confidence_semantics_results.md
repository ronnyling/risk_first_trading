# Confidence Semantics Experiment — Phase 8.5, Step 2

**Date**: 2026-04-29
**Status**: Shadow-only — no production code modified
**Constraint**: R-02 threshold stays at 0.50 (governance contract)

## Hypothesis

Treating agents as having distinct epistemic roles produces a different
`total_confidence` than simple averaging, potentially reaching >= 0.50
in trending markets.

## Models

| Model | Formula | Rationale |
|-------|---------|-----------|
| **Baseline** | `mean(all)` | Current behavior |
| **Structural-primary** | `mean(Ichimoku, Wyckoff) * 0.7 + mean(AMT, Volatility) * 0.3` | Structural drivers, validation dampeners |
| **Max-structural** | `max(Ichimoku, Wyckoff) * 0.6 + mean(AMT, Volatility) * 0.4` | Strongest structural dominates |

**Each model is evaluated independently against the baseline.**
**Results are not chained or reused.**

---

## BTCUSD_50D (1843 bars)

### Confidence Distribution Comparison

| Model | Mean | Median | p25 | p50 | p75 | p90 | p95 | Max |
|-------|------|--------|-----|-----|-----|-----|-----|-----|
| Baseline (mean) | 0.3572 | 0.3628 | 0.3300 | 0.3628 | 0.3885 | 0.4072 | 0.4194 | 0.4644 |
| Structural-primary | 0.3581 | 0.3623 | 0.3403 | 0.3623 | 0.3832 | 0.3985 | 0.4060 | 0.4415 |
| Max-structural | 0.5674 | 0.5748 | 0.5407 | 0.5748 | 0.6056 | 0.6288 | 0.6384 | 0.6865 |

### R-02 Threshold Crossing

| Model | Bars >= 0.45 | Bars >= 0.50 | R-02 Fires |
|-------|-------------|-------------|------------|
| Baseline (mean) | 9 (0.5%) | 0 (0.0%) | 1744 |
| Structural-primary | 0 (0.0%) | 0 (0.0%) | 1744 |
| Max-structural | 1768 (95.9%) | 1658 (90.0%) | 183 |

### Directive Distribution

| Model | FULL | SCALE_DOWN | CASH |
|-------|------|------------|------|
| Baseline (mean) | 0 | 1744 | 99 |
| Structural-primary | 0 | 1744 | 99 |
| Max-structural | 1561 | 183 | 99 |

### Improvement Over Baseline

**Structural-primary** vs Baseline:
- Mean: +0.0009 (improved)
- p90: -0.0087 (decreased)
- Max: -0.0229 (decreased)
- R-02 fires reduced by: 0
**Max-structural** vs Baseline:
- Mean: +0.2102 (improved)
- p90: +0.2216 (improved)
- Max: +0.2221 (improved)
- R-02 fires reduced by: 1561
---

## SPY_50D (333 bars)

### Confidence Distribution Comparison

| Model | Mean | Median | p25 | p50 | p75 | p90 | p95 | Max |
|-------|------|--------|-----|-----|-----|-----|-----|-----|
| Baseline (mean) | 0.3632 | 0.3708 | 0.3295 | 0.3708 | 0.3941 | 0.4147 | 0.4264 | 0.4608 |
| Structural-primary | 0.3633 | 0.3675 | 0.3414 | 0.3675 | 0.3853 | 0.4035 | 0.4094 | 0.4361 |
| Max-structural | 0.5759 | 0.5810 | 0.5440 | 0.5810 | 0.6109 | 0.6354 | 0.6460 | 0.6849 |

### R-02 Threshold Crossing

| Model | Bars >= 0.45 | Bars >= 0.50 | R-02 Fires |
|-------|-------------|-------------|------------|
| Baseline (mean) | 2 (0.6%) | 0 (0.0%) | 309 |
| Structural-primary | 0 (0.0%) | 0 (0.0%) | 309 |
| Max-structural | 332 (99.7%) | 312 (93.7%) | 21 |

### Directive Distribution

| Model | FULL | SCALE_DOWN | CASH |
|-------|------|------------|------|
| Baseline (mean) | 0 | 309 | 24 |
| Structural-primary | 0 | 309 | 24 |
| Max-structural | 288 | 21 | 24 |

### Improvement Over Baseline

**Structural-primary** vs Baseline:
- Mean: +0.0001 (improved)
- p90: -0.0112 (decreased)
- Max: -0.0247 (decreased)
- R-02 fires reduced by: 0
**Max-structural** vs Baseline:
- Mean: +0.2127 (improved)
- p90: +0.2207 (improved)
- Max: +0.2241 (improved)
- R-02 fires reduced by: 288
---

## Cross-Dataset Summary

| Dataset | Model | Max Mean | Bars >= 0.50 | R-02 Fires |
|---------|-------|----------|-------------|------------|
| BTCUSD_50D | Baseline (mean) | 0.4644 | 0/1843 | 1744 |
| BTCUSD_50D | Structural-primary | 0.4415 | 0/1843 | 1744 |
| BTCUSD_50D | Max-structural | 0.6865 | 1658/1843 | 183 |
| SPY_50D | Baseline (mean) | 0.4608 | 0/333 | 309 |
| SPY_50D | Structural-primary | 0.4361 | 0/333 | 309 |
| SPY_50D | Max-structural | 0.6849 | 312/333 | 21 |

## Verdict

- **BTCUSD_50D**: At least one model crossed 0.50 — aggregation semantics were the binding constraint
- **SPY_50D**: At least one model crossed 0.50 — aggregation semantics were the binding constraint

### Interpretation

If any model crosses 0.50, the current mean model was structurally
suppressing confidence. If no model crosses, the agents' individual
confidence ranges are the fundamental constraint.
