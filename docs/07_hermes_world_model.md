# Hermes World Model — Regime-First Architecture

## Purpose

This document updates the agent's world model to reflect the architectural shift from strategy-centric intelligence to regime- and risk-centric intelligence. No trading rules are changed here; this is a governance and interpretation update required before formalizing Hermes mechanics.

---

## Core Architectural Change (Authoritative)

### Old Assumption (Deprecated)

- Strategies are the primary decision units
- The black box selects, promotes, or degrades strategies directly
- Capital allocation is strategy-first

### New Assumption (Authoritative)

- Market regime and risk directives are the primary decision units
- Strategies are execution modules operating only when permitted
- Capital allocation is risk-first, conditional on regime confidence

**Hermes is upstream of all strategies.**

---

## Ontology (New Canon)

### Decision Layers

| Layer | Name | Role |
|-------|------|------|
| Layer 1 | Hermes | Regime & Risk Authority |
| Layer 2 | Strategy Families | Edge Logic Selection |
| Layer 3 | Executable Systems | Deterministic Trade Execution |

### Authority Hierarchy

- Hermes directives are non-appealable by strategies
- Strategies cannot self-activate, self-scale, or self-override
- Human governance overrides Hermes only out of band (no mid-session changes)

---

## What Hermes Decides (And What It Does Not)

### Hermes Decides

- Market regime (e.g., trending, ranging, volatile)
- Regime confidence (probabilistic, not binary)
- Volatility state (when available)
- Risk directive: Full Size / Scale-Down / Cash
- Which strategy family is allowed to operate

### Hermes Does NOT Decide

- Exact entries or exits
- Indicator thresholds
- Candlestick patterns
- Micro price action

---

## Strategy Role (Reframed)

### Strategies Are

- Execution engines
- Telemetry providers
- Replaceable components

### Strategies Are NOT

- Regime classifiers
- Risk allocators
- Capital decision authorities

---

## Performance Interpretation Rules (Critical)

All strategy performance must be interpreted conditional on Hermes context:

1. **Metrics are evaluated per regime**, not globally
2. **Reduced trade frequency** under Scale-Down or Cash is non-actionable
3. **Underperformance outside a strategy's valid regime** does not imply degradation
4. **Hermes restricting a strategy** is considered correct behavior, not failure

---

## Relationship to SPG-001 (Strategy Promotion Gate)

SPG-001 remains valid and enforced. Clarifications:

- Strategy states (Candidate → Retired) are unchanged
- Promotion, degradation, and retirement decisions must factor Hermes directives
- **A strategy may not be degraded solely due to inactivity caused by Hermes** (SPG-001 clarification)
- Hermes itself is not promoted or retired under SPG-001

---

## Black-Box Definition (Updated)

### The Black Box Is Now

A **Regime → Risk → Permission Engine**

### The Black Box Is NOT

A strategy selector or entry optimizer

### Hermes Is Evaluated On

- Regime classification stability
- Drawdown control
- Capital preservation during uncertainty
- Alignment between regime confidence and risk exposure

---

## Invariants (Non-Negotiable)

1. **No mid-session authority changes**
2. **No PnL-based overrides of Hermes**
3. **No strategy stacking across families**
4. **Deterministic execution remains in Layer 3**

---

## Readiness Gate

With this world model in place, the system is now ready to:

1. Formalize Hermes scoring rules
2. Define conflict resolution logic
3. Lock position sizing per risk directive

No further architectural changes are required before those steps.

---

## Document History

| Version | Date | Change |
|---------|------|--------|
| 1.0 | 2026-04-29 | Initial world model — regime-first architecture |