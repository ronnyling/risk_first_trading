# Experiment Results: Hermes v2 Agent Conflict Analysis

**Date:** 2026-04-29
**Status:** COMPLETE
**Data:** SPY 50d (385 bars), BTCUSD 50d (1,895 bars)

---

## Executive Summary

Hermes v2 has **never emitted FULL** on any real market data. The system is stuck in permanent SCALE_DOWN (94%) + CASH (6%) with zero FULL bars across both symbols and 2,280 total bars analyzed.

The root cause is **not** what we hypothesized. The experiment revealed that R-02 (low confidence gate) is **irrelevant** because R-01 (dispersion gate) fires first on every single bar. The problem is structural agent disagreement, not confidence suppression.

---

## Audit Results

### Agent Behavior Profiles (Identical Pattern Across Both Symbols)

| Agent | Score Avg | Conf Avg | Conf<0.3 | Alignment | Conflict Participation |
|-------|-----------|----------|----------|-----------|----------------------|
| **AMT** | +0.286 (SPY) / +0.182 (BTC) | 0.134 / 0.085 | 98-99% | 50-58% aligned | 47-54% |
| **Ichimoku** | +0.014 / +0.003 | 0.025 / 0.029 | **100%** | 42-53% aligned | 50-61% |
| **Volatility** | -0.003 / +0.049 | 0.548 / 0.616 | 4-12% | **96-99% aligned** | 0.3-2.3% |
| **Wyckoff** | -0.001 / +0.005 | 0.685 / 0.702 | 1-5% | **structurally contrarian** (50-59% opposite) | 53-61% |

### Key Finding: The Confidence Hierarchy Is Inverted

```
Wyckoff:     conf=0.70  (highest, but 50-59% opposite to composite)
Volatility:  conf=0.58  (high, 96-99% aligned with composite)
AMT:         conf=0.10  (structurally capped, always low)
Ichimoku:    conf=0.03  (near-zero, 100% below R-02 threshold)
```

**The most confident agents disagree most. The most aligned agents have moderate confidence. The least confident agents are noise.**

This creates an irreconcilable conflict: Wyckoff's high confidence prevents CASH from being the "right" answer, but its contrarian direction prevents FULL from being the "right" answer either.

### Conflict Frequency

| Symbol | Conflict Bars | Conflict % | R-01 Would Fire (dispersion > 0.60) |
|--------|--------------|------------|-------------------------------------|
| SPY | 301 / 385 | 78.2% | YES, every bar |
| BTCUSD | 1,549 / 1,895 | 81.7% | YES, every bar |

---

## Experiment Results: R-02 Bypass

### Hypothesis Tested
> "R-02 (total_confidence < 0.50) is the primary blocker preventing FULL."

### Method
- Baseline: Standard HCR-001 (all rules enforced)
- Experimental: R-02 bypassed when Ichimoku + Volatility confidence >= 0.4
- Everything else identical

### Results

| Metric | SPY Baseline | SPY Experiment | BTCUSD Baseline | BTCUSD Experiment |
|--------|-------------|---------------|-----------------|-------------------|
| FULL % | 0.0% | 0.0% | 0.0% | 0.0% |
| SCALE_DOWN % | 93.5% | 93.5% | 94.8% | 94.8% |
| CASH % | 6.5% | 6.5% | 5.2% | 5.2% |
| R-02 Bypassed | 0 bars | **0 bars** | 0 bars | **0 bars** |
| Directive Shifts | - | **none** | - | **none** |

### Verdict: HYPOTHESIS REJECTED

R-02 was bypassed on **zero bars** because R-01 (dispersion > 0.60) fires first on **every bar**. R-02 never gets a chance to execute. The experiment produced identical results to baseline because the modification was structurally unreachable.

**The bottleneck is R-01 (agent disagreement), not R-02 (confidence).**

---

## Root Cause Analysis

### The Dispersion Trap

1. AMT and Ichimoku produce scores near zero (0.003-0.286) with near-zero confidence (0.03-0.13)
2. Wyckoff produces scores near zero (0.005) but with HIGH confidence (0.70) and CONTRARIAN direction
3. Volatility produces scores with HIGH variance (std=0.80-0.84) and HIGH confidence (0.55-0.62)

This guarantees: `max(scores) - min(scores) > 0.60` on every bar → R-01 → CASH/INDETERMINATE

### Why R-01 Is Correct (And Should Not Be Bypassed)

R-01 is the integrity gate. When agents fundamentally disagree about direction, the system SHOULD go to CASH. The problem is not the rule — it's the agents.

### Why AMT and Ichimoku Are Dead Weight

- **AMT**: Confidence capped at 0.5 (per design), but actual output is 0.08-0.13. Adds noise to score but zero useful signal.
- **Ichimoku**: Confidence 0.025-0.029. Essentially random. Adds dispersion without adding information.

These two agents contribute nothing to composite score quality while guaranteeing R-01 fires.

### The Wyckoff Paradox

Wyckoff is the highest-confidence agent (0.70) and the most contrarian (50-59% opposite to composite). This is either:
- **A bug**: Wyckoff's evaluation logic is inverted or misaligned with the other agents
- **A feature**: Wyckoff correctly identifies contrarian opportunities that the composite ignores

If Wyckoff were aligned with Volatility (instead of contrarian), composite score would be consistently positive, R-01 would not fire, and FULL would be reachable.

---

## Actionable Conclusions

### What NOT To Do
- Do NOT relax R-01 thresholds (dispersion gate is correct)
- Do NOT relax R-02 thresholds (irrelevant — R-01 fires first)
- Do NOT add more agents (more disagreement = more R-01 fires)
- Do NOT tune scoring weights (structural problem, not parametric)

### What TO Do (Ordered by Impact)

1. **Retire AMT and Ichimoku agents** (or fix their confidence calibration)
   - They contribute zero signal and guarantee R-01 fires
   - Removing them would cut dispersion dramatically

2. **Investigate Wyckoff's contrarian alignment**
   - Is Wyckoff's 50-59% opposite rate a bug or a feature?
   - If Wyckoff were aligned with Volatility, FULL would be reachable

3. **Re-run audit after agent changes**
   - The goal: conflict frequency drops below 20%
   - Then R-01 fires rarely, R-02 becomes the actual gate, and FULL becomes reachable

4. **Only then does R-02 matter**
   - If agent changes reduce dispersion, R-02 becomes the binding constraint
   - At that point, the confidence calibration work becomes relevant

---

## Files Delivered

| File | Purpose |
|------|---------|
| `docs/12_agent_roles.md` | Agent contribution metrics and role assignment |
| `scripts/shadow_compare.py` | Extended with `AgentAuditAnalyzer` (--audit-agents) |
| `scripts/shadow_experiment.py` | R-02 bypass experiment |
| `tests/test_shadow_compare.py` | 11 audit tests |
| `docs/13_experiment_results.md` | This document |

---

## One-Sentence Conclusion

**FULL never fires because AMT and Ichimoku produce noise that guarantees agent dispersion exceeds R-01's threshold on every bar — R-02 is irrelevant until these agents are fixed or retired.**