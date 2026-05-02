# Hermes v2.1 Semantics Proposal

**Date**: 2026-04-29
**Status**: Shadow-only proposal — no production code modified
**Justified by**: Phases 8.4 (veto) + 8.5 (confidence) experiments

## Executive Summary

Phase 8.4 proved that the arithmetic-mean confidence aggregation model was suppressing valid structural convergence. Phase 8.4 proved that over-broad veto semantics were producing false CASH directives. This document formalizes both findings into Hermes v2.1 semantics.

**Core principle**: Not all agents are epistemically equal. Confidence should not be democratically averaged.

---

## What Changes

### 1. Confidence Aggregation: Role-Aware Composition

**Current v2** (`scoring.py`):
```python
total_confidence = sum(confidences) / n  # arithmetic mean
```

**Proposed v2.1**:
```python
total_confidence = α * max_structural + (1 - α) * validation_mean
# where:
#   max_structural = max(Ichimoku, Wyckoff)
#   validation_mean = mean(AMT, Volatility)
#   α = 0.6
```

**α = 0.6 is derived from Phase 8.5 exploratory results and used here as a representative value for semantics validation, not as a finalized production constant.** The value was selected because it produced the highest confidence ceiling (0.6865 on BTCUSD, 0.6849 on SPY) while maintaining validation agent influence.

#### Why Structural Agents Dominate

| Agent | Domain | Epistemic Role |
|-------|--------|---------------|
| Ichimoku | Equilibrium / Trend | Structural — defines market regime |
| Wyckoff | Effort vs Result | Structural — validates directional conviction |
| AMT | Auction / Value | Validation — confirms or dampens, never leads |
| Volatility | Volatility Regime | Validation — measures risk environment, not direction |

Structural agents answer "what is the market doing?"
Validation agents answer "is it safe to act on that?"

These are asymmetric questions. Confidence should reflect that asymmetry.

#### Why Validation Agents Dampen But Do Not Decide

AMT is intentionally conservative (score capped at ±0.5, confidence capped at 0.5). This is by design — AMT systematically disagrees with trend sensors because it measures balance vs discovery, not direction. Giving AMT equal voting power in confidence aggregation dilutes the signal from agents that are correctly identifying structure.

Volatility measures compression/expansion — orthogonal to direction. It should influence confidence magnitude, not determine it.

---

### 2. Veto Authority: Volatility-Only R-01

**Current v2** (`conflict.py` line 80):
```python
if inputs.score_dispersion > DISAGREEMENT_THRESHOLD:  # 0.60
    # Any agent disagreement → CASH
```

**Proposed v2.1**:
```python
# R-01 fires only when Volatility opposes composite direction
volatility_opposes = (
    vol_score * composite_score < 0  # volatility score opposes composite
    and abs(vol_score) > VETO_THRESHOLD  # meaningful opposition
)
if volatility_opposes:
    # Volatility-only veto → CASH
```

#### Why Volatility-Only Veto

Phase 8.4 demonstrated:
- Standard dispersion-based R-01 fired on 5.2% (BTC) and 6.5% (SPY) of bars
- Volatility-only veto: 0 fires on both datasets
- **100% reduction** in false CASH directives
- Volatility never falsely vetoed — it IS the correct integrity gate

When AMT or Ichimoku disagree with the composite, that's normal inter-agent variation. When Volatility opposes the composite, that's a genuine risk signal.

---

## What Does NOT Change

| Component | Status | Reason |
|-----------|--------|--------|
| R-02 threshold (0.50) | **Unchanged** | Governance contract — proven correct by Phase 8.5 |
| R-03 (flip risk) | **Unchanged** | Works as designed |
| R-04 (normal operation) | **Unchanged** | Works as designed |
| Agent score math | **Unchanged** | Scores remain in [-1, +1] |
| Agent confidence math | **Unchanged** | Individual confidences remain in [0, 1] |
| Position sizing (HPS-001) | **Unchanged** | Independent layer |
| Risk layer | **Unchanged** | Independent layer |
| Broker adapter | **Unchanged** | Independent layer |

---

## Resolution Hierarchy (v2.1)

```
1. Volatility Veto (R-01):
   Volatility score opposes composite AND abs(vol_score) > threshold
   → CASH

2. Confidence Gate (R-02):
   total_confidence = α * max_structural + (1-α) * validation_mean
   if total_confidence < 0.50 → SCALE_DOWN

3. Flip Risk (R-03):
   |composite_score - previous_composite| >= 0.80 → SCALE_DOWN

4. Normal (R-04):
   Classify by regime → FULL, SCALE_DOWN, or CASH
```

---

## Evidence Trail

| Claim | Evidence | Experiment |
|-------|----------|------------|
| Arithmetic mean suppresses confidence | Max mean 0.4644, never crosses 0.50 | Phase 8.5 Step 1 |
| Max-structural reaches 0.68+ | 1658/1843 bars cross 0.50 (BTC) | Phase 8.5 Step 2 |
| Dispersion veto produces false CASH | 5.2% BTC, 6.5% SPY | Phase 8.4 |
| Volatility-only eliminates false CASH | 0 fires on both datasets | Phase 8.4 |
| Volatility never falsely vetoes | 0 incorrect vetoes | Phase 8.4 |

---

## Next Step

Phase 8.6 shadow experiment: Run 4 configurations combining both semantics changes to validate the complete v2.1 proposal before any production code modification.

| Config | Confidence | Veto | Purpose |
|--------|-----------|------|---------|
| A | mean(all) | any-agent | Baseline (current v2) |
| B | mean(all) | Volatility-only | Phase 8.4 only |
| C | max-structural | any-agent | Phase 8.5 only |
| D | max-structural | Volatility-only | v2.1 combined |