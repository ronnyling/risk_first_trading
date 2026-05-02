# Hermes Conflict Resolution Logic

## Document ID: HCR-001

## Status: Authoritative Specification — Agent-Consumable

---

## 1. Scope & Authority

- Applies only to Hermes (Layer 1)
- Governs agent disagreement, uncertainty, and transitions
- Executes before any strategy permission or sizing logic
- Outputs are non-appealable in-session

---

## 2. Inputs (Canonical)

Hermes receives, per evaluation cycle:

```yaml
inputs:
  agents:
    - name: AMT
      score: float       # [-1.0, +1.0]
      confidence: float  # [0.0, 1.0]
    - name: Wyckoff
      score: float
      confidence: float
    - name: Ichimoku
      score: float
      confidence: float
    - name: Volatility   # optional
      score: float
      confidence: float
  previous_state:
    regime: enum
    confidence: float
    risk_directive: enum
```

---

## 3. Derived Quantities (Required)

Hermes computes:

```yaml
derived:
  weighted_scores: sum(score_i * confidence_i)
  total_confidence: mean(confidence_i)
  score_dispersion: stddev(score_i)
```

---

## 4. Conflict Detection Rules

### Rule CR-01 — Agent Disagreement

```yaml
condition:
  score_dispersion > 0.60
action:
  conflict_state: TRUE
```

**Meaning:** Agents are expressing directional disagreement. No regime clarity exists.

### Rule CR-02 — Low Confidence

```yaml
condition:
  total_confidence < 0.50
action:
  confidence_state: LOW
```

**Meaning:** Signals exist but are not trustworthy.

### Rule CR-03 — Regime Flip Risk

```yaml
condition:
  abs(weighted_scores - previous_state.composite_score) >= 0.80
action:
  transition_state: UNSTABLE
```

**Meaning:** Sudden regime reversal detected. High whipsaw probability.

---

## 5. Resolution Hierarchy (Strict Order)

Hermes resolves states in this exact order:

1. **Integrity** (highest)
2. **Uncertainty**
3. **Continuation**
4. **Opportunity** (lowest)

No lower rule may override a higher one.

---

## 6. Resolution Logic (Deterministic)

### Resolution R-01 — Integrity First

```yaml
if conflict_state == TRUE:
  output.risk_directive = CASH
  output.allowed_strategy_family = NONE
  output.regime = INDETERMINATE
  terminate_evaluation = TRUE
```

**Rationale:** Capital preservation beats interpretation. No strategy is allowed under disagreement.

### Resolution R-02 — Low Confidence

```yaml
if confidence_state == LOW:
  output.risk_directive = SCALE_DOWN
  output.allowed_strategy_family = previous_state.allowed_strategy_family
```

**Rationale:** Maintain continuity. Reduce exposure, not context.

### Resolution R-03 — Unstable Transitions

```yaml
if transition_state == UNSTABLE:
  output.risk_directive = SCALE_DOWN
  output.regime = previous_state.regime
```

**Rationale:** Regime shifts require confirmation over time. No instant full-risk flips allowed.

### Resolution R-04 — Normal Operation

```yaml
if no conflict_state
  and confidence_state != LOW
  and transition_state != UNSTABLE:
  output.regime = classify(weighted_scores)
  output.risk_directive = determine_by_confidence(confidence)
  output.allowed_strategy_family = map_regime_to_family(regime)
```

---

## 7. Time Stability Rules (Anti-Thrash)

### Rule TS-01 — Minimum Persistence

```yaml
regime_min_duration = N bars  # configurable (e.g., 3–5)
```

Hermes may not flip regimes unless persistence threshold is met. Until then, `previous_state.regime` remains authoritative.

### Rule TS-02 — No Mid-Session Changes

```yaml
if session_open == TRUE:
  prohibit:
    - regime change
    - risk_directive escalation
```

Only de-escalation is permitted mid-session.

---

## 8. Failure Modes (Explicit)

Hermes MUST default to:

```yaml
risk_directive = CASH
allowed_strategy_family = NONE
```

When:

- Any agent output is missing
- Any confidence value is NaN
- Any score is outside bounds
- System state is UNKNOWN

**Fail-safe bias is mandatory.**

---

## 9. Output Contract (Strict)

Hermes must emit exactly one resolution per cycle:

```yaml
output:
  regime: enum
  composite_score: float
  confidence: float
  risk_directive: enum       # FULL / SCALE_DOWN / CASH
  allowed_strategy_family: enum | NONE
```

No auxiliary signals. No soft suggestions. No discretionary text.

---

## 10. Non-Negotiable Invariants

1. Hermes never escalates risk during disagreement
2. Hermes never resolves uncertainty by voting majority
3. Hermes prefers continuity over prediction
4. Hermes protects capital before opportunity
5. Strategies cannot override or reinterpret outcomes

---

## 11. Hybrid Model (Family + Per-Strategy)

Hermes v2 operates with a two-tier allocation model:

### Tier 1: Family-Level Gating (Authoritative, Coarse, Fast)

Conflict resolution outputs `allowed_strategy_family`:
- `trend` — only trend strategies may operate
- `mean_reversion` — only mean-reversion strategies may operate
- `breakout` — only breakout strategies may operate
- `NONE` — no strategies allowed

This is the **coarse, safety-first** layer.

### Tier 2: Per-Strategy Allocation (Downstream, Fine, Optional)

Within an allowed family, existing per-strategy weighting logic applies:
- Hermes evaluates each strategy's metrics
- Weights are clamped to strategy's `max_allocation_pct`
- Degraded strategies receive reduced allocation

This is the **fine-grained optimization** layer.

### Mapping

```
StrategyMetadata.style  →  strategy family
  "trend"              →  trend
  "mean_reversion"     →  mean_reversion
  "breakout"           →  breakout
```

### Behavior

| State | Family Gate | Per-Strategy |
|-------|-------------|-------------|
| Normal operation | `map_regime_to_family(regime)` | Full weighting logic |
| Low confidence | `previous_state.allowed_strategy_family` | Reduced weights |
| Unstable transition | `previous_state.allowed_strategy_family` | Reduced weights |
| Conflict/disagreement | `NONE` | All forced to zero |
| Failure/missing data | `NONE` | All forced to zero |

---

## 12. Readiness Flag

```yaml
conflict_resolution: COMPLETE
```

---

## Document History

| Version | Date | Change |
|---------|------|--------|
| 1.0 | 2026-04-29 | Initial conflict resolution specification with hybrid model |