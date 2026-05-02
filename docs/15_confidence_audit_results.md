# Confidence Contribution Audit — Phase 8.5, Step 1

**Date**: 2026-04-29
**Status**: Measurement only — no code modified

## Objective

Determine whether `total_confidence >= 0.50` (R-02 gate) is
mathematically reachable under the current aggregation model:

```
total_confidence = mean(all agent confidences)
```

---

## BTCUSD_50D (1843 bars audited)

### Per-Agent Confidence Statistics

| Agent | Mean | Median | StDev | Min | Max | p25 | p50 | p75 | p90 | p95 |
|-------|------|--------|-------|-----|-----|-----|-----|-----|-----|-----|
| Ichimoku | 0.0099 | 0.0087 | 0.0058 | 0.0003 | 0.0315 | 0.0059 | 0.0087 | 0.0125 | 0.0189 | 0.0222 |
| Volatility | 0.6234 | 0.6500 | 0.1474 | 0.2300 | 0.8000 | 0.5300 | 0.6500 | 0.7400 | 0.8000 | 0.8000 |
| AMT | 0.0863 | 0.0750 | 0.0669 | 0.0000 | 0.3430 | 0.0250 | 0.0750 | 0.1250 | 0.1778 | 0.2250 |
| Wyckoff | 0.7091 | 0.7251 | 0.0727 | 0.4462 | 0.8000 | 0.6685 | 0.7251 | 0.7667 | 0.7870 | 0.7939 |

### Mean Confidence (Composite) Statistics

| Metric | Value |
|--------|-------|
| Mean | 0.3572 |
| Median | 0.3628 |
| StDev | 0.0437 |
| Min | 0.2100 |
| Max | 0.4644 |
| p25 | 0.3300 |
| p50 | 0.3628 |
| p75 | 0.3885 |
| p90 | 0.4072 |
| p95 | 0.4194 |

### R-02 Threshold Crossing

| Threshold | Bars | % |
|-----------|------|---|
| >= 0.40 | 272 | 14.8% |
| >= 0.45 | 9 | 0.5% |
| >= 0.50 | 0 | 0.0% |

### Per-Agent Shortfall Contribution

Average contribution to R-02 shortfall per agent.
(Higher = agent pulls mean further below 0.50)

| Agent | Avg Shortfall Contribution |
|-------|---------------------------|
| Ichimoku | 0.1225 |
| Volatility | 0.0056 |
| AMT | 0.1034 |
| Wyckoff | 0.0001 |

### Confidence Correlation Matrix

| | Ichimoku | Volatility | AMT | Wyckoff |
|---|---|---|---|---|
| Ichimoku | 1.000 | 0.040 | 0.287 | 0.064 |
| Volatility | 0.040 | 1.000 | -0.014 | -0.046 |
| AMT | 0.287 | -0.014 | 1.000 | -0.001 |
| Wyckoff | 0.064 | -0.046 | -0.001 | 1.000 |

### Confidence Distribution (Bar Counts)

**Ichimoku**:

| Bucket | Count |
|--------|-------|
| [0.0,0.1) | 1843 |
| [0.1,0.2) | 0 |
| [0.2,0.3) | 0 |
| [0.3,0.4) | 0 |
| [0.4,0.5) | 0 |
| [0.5,0.6) | 0 |
| [0.6,0.7) | 0 |
| [0.7,0.8) | 0 |
| [0.8,0.9) | 0 |
| [0.9,1.0] | 0 |

**Volatility**:

| Bucket | Count |
|--------|-------|
| [0.0,0.1) | 0 |
| [0.1,0.2) | 0 |
| [0.2,0.3) | 60 |
| [0.3,0.4) | 113 |
| [0.4,0.5) | 186 |
| [0.5,0.6) | 362 |
| [0.6,0.7) | 385 |
| [0.7,0.8) | 504 |
| [0.8,0.9) | 233 |
| [0.9,1.0] | 0 |

**AMT**:

| Bucket | Count |
|--------|-------|
| [0.0,0.1) | 1124 |
| [0.1,0.2) | 562 |
| [0.2,0.3) | 143 |
| [0.3,0.4) | 14 |
| [0.4,0.5) | 0 |
| [0.5,0.6) | 0 |
| [0.6,0.7) | 0 |
| [0.7,0.8) | 0 |
| [0.8,0.9) | 0 |
| [0.9,1.0] | 0 |

**Wyckoff**:

| Bucket | Count |
|--------|-------|
| [0.0,0.1) | 0 |
| [0.1,0.2) | 0 |
| [0.2,0.3) | 0 |
| [0.3,0.4) | 0 |
| [0.4,0.5) | 41 |
| [0.5,0.6) | 116 |
| [0.6,0.7) | 535 |
| [0.7,0.8) | 1151 |
| [0.8,0.9) | 0 |
| [0.9,1.0] | 0 |

---

## SPY_50D (333 bars audited)

### Per-Agent Confidence Statistics

| Agent | Mean | Median | StDev | Min | Max | p25 | p50 | p75 | p90 | p95 |
|-------|------|--------|-------|-----|-----|-----|-----|-----|-----|-----|
| Ichimoku | 0.0091 | 0.0068 | 0.0066 | 0.0003 | 0.0264 | 0.0039 | 0.0068 | 0.0133 | 0.0199 | 0.0232 |
| Volatility | 0.5804 | 0.6200 | 0.1710 | 0.2300 | 0.8000 | 0.4400 | 0.6200 | 0.7400 | 0.7700 | 0.8000 |
| AMT | 0.1455 | 0.1278 | 0.0713 | 0.0000 | 0.3198 | 0.1000 | 0.1278 | 0.1864 | 0.2534 | 0.2746 |
| Wyckoff | 0.7179 | 0.7290 | 0.0624 | 0.5340 | 0.7998 | 0.6784 | 0.7290 | 0.7705 | 0.7885 | 0.7950 |

### Mean Confidence (Composite) Statistics

| Metric | Value |
|--------|-------|
| Mean | 0.3632 |
| Median | 0.3708 |
| StDev | 0.0434 |
| Min | 0.2389 |
| Max | 0.4608 |
| p25 | 0.3295 |
| p50 | 0.3708 |
| p75 | 0.3941 |
| p90 | 0.4147 |
| p95 | 0.4264 |

### R-02 Threshold Crossing

| Threshold | Bars | % |
|-----------|------|---|
| >= 0.40 | 73 | 21.9% |
| >= 0.45 | 2 | 0.6% |
| >= 0.50 | 0 | 0.0% |

### Per-Agent Shortfall Contribution

Average contribution to R-02 shortfall per agent.
(Higher = agent pulls mean further below 0.50)

| Agent | Avg Shortfall Contribution |
|-------|---------------------------|
| Ichimoku | 0.1227 |
| Volatility | 0.0108 |
| AMT | 0.0886 |
| Wyckoff | 0.0000 |

### Confidence Correlation Matrix

| | Ichimoku | Volatility | AMT | Wyckoff |
|---|---|---|---|---|
| Ichimoku | 1.000 | -0.063 | 0.370 | -0.516 |
| Volatility | -0.063 | 1.000 | -0.205 | -0.101 |
| AMT | 0.370 | -0.205 | 1.000 | -0.084 |
| Wyckoff | -0.516 | -0.101 | -0.084 | 1.000 |

### Confidence Distribution (Bar Counts)

**Ichimoku**:

| Bucket | Count |
|--------|-------|
| [0.0,0.1) | 333 |
| [0.1,0.2) | 0 |
| [0.2,0.3) | 0 |
| [0.3,0.4) | 0 |
| [0.4,0.5) | 0 |
| [0.5,0.6) | 0 |
| [0.6,0.7) | 0 |
| [0.7,0.8) | 0 |
| [0.8,0.9) | 0 |
| [0.9,1.0] | 0 |

**Volatility**:

| Bucket | Count |
|--------|-------|
| [0.0,0.1) | 0 |
| [0.1,0.2) | 0 |
| [0.2,0.3) | 26 |
| [0.3,0.4) | 36 |
| [0.4,0.5) | 39 |
| [0.5,0.6) | 62 |
| [0.6,0.7) | 61 |
| [0.7,0.8) | 79 |
| [0.8,0.9) | 30 |
| [0.9,1.0] | 0 |

**AMT**:

| Bucket | Count |
|--------|-------|
| [0.0,0.1) | 77 |
| [0.1,0.2) | 182 |
| [0.2,0.3) | 68 |
| [0.3,0.4) | 6 |
| [0.4,0.5) | 0 |
| [0.5,0.6) | 0 |
| [0.6,0.7) | 0 |
| [0.7,0.8) | 0 |
| [0.8,0.9) | 0 |
| [0.9,1.0] | 0 |

**Wyckoff**:

| Bucket | Count |
|--------|-------|
| [0.0,0.1) | 0 |
| [0.1,0.2) | 0 |
| [0.2,0.3) | 0 |
| [0.3,0.4) | 0 |
| [0.4,0.5) | 0 |
| [0.5,0.6) | 17 |
| [0.6,0.7) | 95 |
| [0.7,0.8) | 221 |
| [0.8,0.9) | 0 |
| [0.9,1.0] | 0 |

---

## Combined Analysis

### Key Question: Is mean >= 0.50 reachable?

- **BTCUSD_50D**: NO — max mean confidence: 0.4644 (92.9% of 0.50 threshold)
- **SPY_50D**: NO — max mean confidence: 0.4608 (92.2% of 0.50 threshold)

### Bottleneck Identification

The agent with the highest avg shortfall contribution is the primary
bottleneck preventing mean >= 0.50.

- **BTCUSD_50D**: Top bottleneck = Ichimoku (avg shortfall: 0.1225)
- **SPY_50D**: Top bottleneck = Ichimoku (avg shortfall: 0.1227)

### Interpretation

If mean never reaches 0.50, the question becomes:

1. Is this because agent confidence ceilings are individually too low?
2. Or because the arithmetic mean model structurally dilutes high-confidence agents?

Step 2 (confidence_semantics_experiment.py) tests whether role-aware
aggregation changes the outcome.
