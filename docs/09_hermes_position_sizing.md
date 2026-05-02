# Hermes Position Sizing Logic

## Document ID: HPS-001

## Status: Authoritative Specification (Agent-Consumable)

---

## 1. Scope & Authority

Applies only after:

- World Model (`07`) ✅
- Conflict Resolution (`08`) ✅

Executed by Hermes (Layer 1) only. Governs capital exposure, not entries. Outputs are non-appealable in-session.

---

## 2. Inputs (Canonical)

```yaml
inputs:
  hermes_output:
    regime: enum
    composite_score: float       # [-1.0, +1.0]
    confidence: float            # [0.0, 1.0]
    risk_directive: enum         # FULL | SCALE_DOWN | CASH
    allowed_strategy_family: enum | NONE

  account_state:
    equity: float
    peak_equity: float
    current_drawdown: float      # % from peak

  limits:
    max_risk_per_trade: float    # e.g., 1.0%
    max_portfolio_risk: float    # e.g., 5.0%
    max_allocation_pct: float    # per-strategy cap
    max_position_size: float     # absolute cap
```

---

## 3. Derived Quantities

```yaml
derived:
  drawdown_band:
    NORMAL: current_drawdown < 10%
    STRESSED: 10% <= current_drawdown < 20%
    CRITICAL: current_drawdown >= 20%
```

---

## 4. Risk Directives (Semantic Mapping)

| Conceptual Directive | Exposure Meaning |
|---------------------|-----------------|
| FULL | Normal capital deployment |
| SCALE_DOWN | Reduced capital deployment |
| CASH | Zero exposure |

This layer does not rename enums. Mapping is conceptual only.

---

## 5. Position Sizing Resolution (Strict)

### PS-01 — CASH Directive (Absolute)

```yaml
if risk_directive == CASH:
  per_trade_risk = 0.0
  portfolio_risk = 0.0
  allow_new_positions = FALSE
  scale_existing = DECREASE_ONLY
  terminate
```

**Invariant:** CASH overrides everything.

### PS-02 — SCALE_DOWN Directive

```yaml
if risk_directive == SCALE_DOWN:
  per_trade_risk = max_risk_per_trade * scale_factor
  portfolio_risk = max_portfolio_risk * scale_factor
```

Where:

```yaml
scale_factor:
  confidence >= 0.75: 0.75
  0.50 <= confidence < 0.75: 0.50
  confidence < 0.50: 0.25
```

Rules:
- No pyramiding
- No risk escalation
- Existing positions may only be reduced or held

### PS-03 — FULL Directive

```yaml
if risk_directive == FULL:
  per_trade_risk = max_risk_per_trade
  portfolio_risk = max_portfolio_risk
```

Subject to drawdown constraints (see PS-04).

### PS-04 — Drawdown-Based Overrides (Hard Constraints)

```yaml
if drawdown_band == STRESSED:
  per_trade_risk = per_trade_risk * 0.50
  portfolio_risk = portfolio_risk * 0.50

if drawdown_band == CRITICAL:
  per_trade_risk = 0.0
  portfolio_risk = 0.0
  force_risk_directive = CASH
```

**Drawdown constraints override confidence.**

---

## 6. Family-Level Capital Gating

```yaml
if allowed_strategy_family == NONE:
  disallow_all_new_positions = TRUE
  per_strategy_allocation = 0.0
```

Otherwise:

```yaml
eligible_strategies = strategies where
  strategy.family == allowed_strategy_family
```

Only eligible strategies may receive allocation.

---

## 7. Per-Strategy Allocation (Downstream Only)

Hermes does not compute individual strategy weights. It outputs only:

```yaml
allocation_budget:
  per_trade_risk
  portfolio_risk
  eligible_strategies
```

Downstream allocation engine may distribute capital only within the allowed family. Hermes does not rank strategies.

---

## 8. Anti-Escalation Rules

### AR-01 — No In-Session Risk Increase

```yaml
if session_active == TRUE:
  prohibit:
    - increasing per_trade_risk
    - increasing portfolio_risk
```

Only reductions are allowed mid-session.

### AR-02 — No Instant Re-Leverage

```yaml
if previous_risk_directive in [CASH, SCALE_DOWN]
  and risk_directive == FULL:
  require:
    - regime persistence met
    - confidence >= 0.75
```

---

## 9. Failure Modes (Fail-Safe)

Hermes MUST force:

```yaml
risk_directive = CASH
per_trade_risk = 0.0
portfolio_risk = 0.0
```

If:

- Any input is missing
- Equity <= 0
- Drawdown is NaN
- Confidence out of bounds
- Allocation engine state unknown

---

## 10. Output Contract (Strict)

Hermes emits exactly one sizing resolution per cycle:

```yaml
output:
  risk_directive: enum
  per_trade_risk: float
  portfolio_risk: float
  allowed_strategy_family: enum | NONE
```

No percentages. No suggestions. No weights.

---

## 11. Invariants (Non-Negotiable)

1. Hermes never sizes based on PnL
2. Hermes never escalates risk under uncertainty
3. Hermes never allocates across families
4. Hermes always prefers survival over opportunity
5. Hermes sizing is deterministic

---

## 12. Readiness Flag

```yaml
position_sizing: COMPLETE
```

---

## Document History

| Version | Date | Change |
|---------|------|--------|
| 1.0 | 2026-04-29 | Initial position sizing specification |