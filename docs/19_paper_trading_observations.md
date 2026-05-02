> **DEPRECATED** — This document describes historical paper-trading observations.
> Paper vs live is now a broker endpoint choice, not a runtime mode.
> See `docs/06_operational_runbook.md` for current procedures.

# Phase 9: Paper Trading Observations

**Date Started**: ___
**Symbol**: SPY (1h bars)
**Hermes Version**: v2.1 (max-structural confidence, volatility-only veto)
**Initial Capital**: $100,000

## Run Configuration

| Parameter | Value |
|-----------|-------|
| Confidence model | max_structural (alpha=0.6) |
| Veto model | volatility_only |
| Veto threshold | 0.3 |
| R-02 threshold | 0.50 |
| Fill assumption | Close of bar that triggered decision |
| Slippage | 0 bps |
| Commission | 0 bps |

## Daily Observations

### Day 1
- First bar directive: ___
- Directive transitions observed: ___
- Oscillation detected: ___
- Notes: ___

### Day 2
- Directive transitions: ___
- Notes: ___

### Day 3
- Directive transitions: ___
- Notes: ___

## Weekly Summary

### Week 1
| Metric | Value |
|--------|-------|
| FULL bars | ___ |
| SCALE_DOWN bars | ___ |
| CASH bars | ___ |
| Directive transitions | ___ |
| Largest transition cluster | ___ |
| Final equity | ___ |
| Max drawdown | ___ |
| Trades executed | ___ |
| Notes | ___ |

### Week 2
| Metric | Value |
|--------|-------|
| FULL bars | ___ |
| SCALE_DOWN bars | ___ |
| CASH bars | ___ |
| Directive transitions | ___ |
| Largest transition cluster | ___ |
| Final equity | ___ |
| Max drawdown | ___ |
| Trades executed | ___ |
| Notes | ___ |

## Behavioral Analysis

### FULL Appearance Patterns
- Does FULL appear in clustered phases? ___
- Are FULL phases sustained (multi-bar)? ___
- Is FULL isolated to single bars? ___

### CASH Appearance Patterns
- Does CASH appear only during real destabilization? ___
- Is CASH frequency within baseline band (5-7%)? ___

### SCALE_DOWN Behavior
- Does SCALE_DOWN dominate early/uncertain periods? ___
- Is SCALE_DOWN a transition state between FULL and CASH? ___

### Directive Transitions
- Most common transition: ___
- Most rare transition: ___
- Any oscillation patterns (A->B->A->B)? ___
- Transition clustering analysis: ___

## Safety Validation

- [ ] No oscillation between FULL ↔ CASH
- [ ] FULL appears in clustered phases
- [ ] SCALE_DOWN dominates early/uncertain periods
- [ ] CASH appears only during real destabilization
- [ ] All decisions are deterministic and explainable
- [ ] Log file complete and auditable

## Post-Run Verdict

**Behavioral correctness**: ___
**Operational stability**: ___
**Ready for Phase 10 (IB integration)?**: ___

## Notes

_Use this section for any observations not captured above._