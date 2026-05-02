# Meta-Optimization Operations

**System Version:** v1.2.0
**Phase:** E — Meta-Optimization Plane

---

## Overview

The Meta-Optimization Plane provides self-optimization, leverage simulation, policy evolution, LLM-driven tuning, and cross-strategy mutation capabilities. All outputs are advisory proposals — never auto-applied.

---

## Capabilities

### E.1 Self-Optimizing PnL Maximization

**Purpose:** Evaluate whether Hermes parameter adjustments would improve risk-adjusted returns.

**How to Run:**
1. Dashboard → Meta-Optimization → Run Capabilities → "Run Self-Optimization"
2. System checks gating conditions (≥300 fills, drawdown <15%, no recent kill-switch)
3. If gated, shows blocking reason
4. If allowed, generates optimization proposal
5. Review proposal in Proposals tab
6. Click Adopt / Reject / Ignore

**Gating Conditions:**
- Minimum 300 fills in database
- Current drawdown < 15%
- No kill-switch triggers in last 30 days
- Quarterly change limit not reached (1 per quarter)
- 30-day cooling-off since last adoption

**What It Changes:**
- Conflict resolution thresholds (DISAGREEMENT_THRESHOLD, etc.)
- Confidence boundary thresholds
- Correlation threshold
- Scoring weights

**What It Cannot Change:**
- Risk limits (frozen)
- Position sizing formula
- Kill switch threshold
- Execution engine code

---

### E.2 Auto-Leverage Escalation (Advisory Only)

**Purpose:** Simulate what performance would look like at higher leverage levels.

**How to Run:**
1. Dashboard → Meta-Optimization → Run Capabilities → "Run Leverage Evaluation"
2. System checks gating conditions (stability, drawdown, fills)
3. Generates leverage report with simulated scenarios
4. Review report in Proposals tab
5. Click Acknowledge / Reject / Ignore

**Important:** Leverage changes require manual editing of `config/risk_limits.yaml` between sessions. The dashboard only shows simulations.

**Maximum Simulated Leverage:**
- SMALL profile: 1.5x
- MEDIUM profile: 2.0x
- LARGE profile: 3.0x

---

### E.3 Policy Evolution

**Purpose:** Evaluate whether system policies should evolve based on accumulated evidence.

**How to Run:**
1. Dashboard → Meta-Optimization → Run Capabilities → "Run Policy Review"
2. System checks gating conditions (no pending expansions, quarterly limit)
3. Analyzes expansion history, family directives, scaling utilization
4. Generates policy change proposal
5. Review proposal in Proposals tab
6. Click Adopt / Reject / Ignore

**Policies That Can Evolve:**
- Expansion pool composition
- Expansion order
- Family assignment rules
- Correlation threshold
- Scaling profile limits

**Policies That Are Immutable:**
- risk_limits.yaml (frozen)
- Execution engine code
- Position sizing formula
- Kill switch mechanism

---

### E.4 LLM-Driven Parameter Tuning

**Purpose:** Use LLM as hypothesis generator for parameter improvements.

**How to Run:**
1. Dashboard → Meta-Optimization → Run Capabilities → "Run LLM Tuning"
2. System checks gating conditions (≥200 fills, no recent adoption)
3. LLM generates hypotheses about parameter changes
4. System evaluates each hypothesis offline
5. If improvement found, generates tuning proposal
6. Review proposal in Proposals tab
7. Click Adopt / Reject / Ignore

**LLM Role:**
- Generates hypotheses ("What if we tighten X?")
- Plans search strategies
- Interprets results

**LLM Cannot:**
- Deploy changes
- Access live broker
- Modify config files

---

### E.5 Cross-Strategy Mutation (R&D)

**Purpose:** Generate and test new strategy variants.

**How to Run:**
1. Dashboard → Meta-Optimization → Strategy Variants tab
2. Click "Create Variant" (or use code: `StrategyMutator().create_variant()`)
3. Variant enters BACKTEST stage
4. Advance through SHADOW → PAPER → ADMISSION
5. Review for admission criteria
6. If admitted, enters 60-day COOLING stage

**Admission Criteria:**
- Sharpe > 0.5
- Max drawdown < 15%
- Win rate > 45%
- Minimum 30 trades
- Active in ≥ 2 regimes
- Correlation with parent < 0.7
- No catastrophic single-day loss (> 5%)

---

## Drift Detection

**Purpose:** Detect performance degradation after meta-optimization adoptions.

**How It Works:**
1. After any adoption, system monitors 30-day rolling Sharpe
2. Compares against post-adoption baseline
3. If degradation exceeds thresholds, triggers reversion

**Severity Levels:**
- NONE: No degradation
- MILD: Sharpe drops 0.1-0.2 (warning)
- MODERATE: Sharpe drops 0.2-0.3 (alert + reversion proposal)
- SEVERE: Sharpe drops > 0.3 (auto-revert)
- CRITICAL: Drawdown > 15% (auto-revert + 90-day disable)

**Auto-Revert:**
- Triggers on SEVERE or CRITICAL
- Restores backup config file
- Disables capability for 90 days

---

## Decision Boundaries

### What Operators MAY Do

| Action | How | Impact |
|--------|-----|--------|
| Run self-optimization | Dashboard button | Generates proposal |
| Run leverage evaluation | Dashboard button | Generates report |
| Run policy review | Dashboard button | Generates proposal |
| Run LLM tuning | Dashboard button | Generates proposal |
| Adopt proposal | Dashboard button | Applies config change |
| Reject proposal | Dashboard button | Archives proposal |
| Ignore proposal | Dashboard button | Archives proposal |
| Create strategy variant | Dashboard/code | Starts R&D pipeline |
| Review drift status | Dashboard tab | Shows current drift |

### What Operators MUST NOT Do

| Prohibited Action | Why |
|-------------------|-----|
| Auto-apply changes | All changes require HITL approval |
| Edit risk_limits.yaml during session | Frozen config |
| Bypass drift detection | Safety mechanism |
| Override cooling-off periods | Protection against over-optimization |
| Run capabilities more than quarterly | Frequency limits |
| Deploy LLM changes directly | LLM is advisory only |

---

## Frequency Limits

| Limit | Scope |
|-------|-------|
| 1 adopted change per capability per quarter | Per capability |
| 2 total adopted changes per quarter | Cross-capability |
| 30-day cooling-off between adoptions | Per capability |
| 90-day disable after reversion | Per capability |

---

## Troubleshooting

### Optimization Blocked

**Symptom:** "Optimization blocked by gating conditions"

**Common Causes:**
- Insufficient fills (< 300)
- High drawdown (> 15%)
- Recent kill-switch trigger
- Quarterly limit reached
- Cooling-off period active

**Resolution:** Wait for conditions to improve, or check if system is in drawdown.

### Leverage Evaluation Blocked

**Symptom:** "Leverage evaluation blocked by gating conditions"

**Common Causes:**
- Max drawdown > 10%
- Insufficient fills (< 100)
- Current drawdown > 5%

**Resolution:** Wait for stable trading period.

### Drift Detected

**Symptom:** Drift Monitor shows SEVERE or CRITICAL

**Resolution:**
1. Check if a recent adoption caused degradation
2. If auto-reverted, review the reversion event
3. Consider rejecting the reverted proposal
4. Wait for system to stabilize before next optimization

---

## Emergency Procedures

### Disable All Meta-Optimization

If meta-optimization is causing issues:

1. Set `config/meta_optimization.json` → `enabled: false`
2. All capabilities will return BLOCKED status
3. Re-enable when ready

### Force Revert a Proposal

If a proposal was adopted and is causing issues:

1. Dashboard → Meta-Optimization → Optimization History
2. Find the adopted proposal
3. System will auto-revert if drift is detected
4. Or manually restore from `config/*.bak.{timestamp}` backup
