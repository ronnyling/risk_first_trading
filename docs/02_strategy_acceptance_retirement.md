# Strategy Promotion Gate

## Document ID: SPG-001

## Purpose

The Strategy Promotion Gate defines the lifecycle, acceptance criteria, monitoring rules, and retirement conditions for all trading strategies.

**No strategy may enter, remain, or be removed from the system outside this gate.**

---

## Strategy Lifecycle States

Each strategy exists in exactly one state at any time:

```
Candidate → Approved (Inactive) → Probationary (Active) → Active
                                                             ↓
                                                          Degraded
                                                             ↓
                                                          Suspended
                                                             ↓
                                                           Retired
```

| State | Description | Trading? |
|-------|-------------|----------|
| `Candidate` | Research-only, not connected to live trading | No |
| `Approved` | Passed gate criteria but not yet trading | No |
| `Probationary` | Trading with restricted allocation | Yes (capped) |
| `Active` | Fully eligible for Hermes allocation | Yes |
| `Degraded` | Reduced eligibility due to issues | Yes (reduced) |
| `Suspended` | Temporarily disabled | No |
| `Retired` | Permanently removed from live consideration | No |

State transitions are persisted in `strategy_states` table and require justification.

---

## Entry Preconditions (Candidate → Approved)

A strategy may be approved only if ALL conditions are met:

### Structural Requirements

- Deterministic, non-learning logic
- No access to portfolio state, other strategies, or capital
- Emits only `Signal` objects
- Implements full `Strategy` interface (`on_bar`, `on_fill`, `metadata`)
- All `StrategyMetadata` fields populated

### Backtest & Research Evidence

| Criterion | Threshold | Measurement Window |
|-----------|-----------|-------------------|
| Out-of-sample Sharpe | ≥ 1.0 | Full test period (min 3 months equivalent) |
| Max drawdown | ≤ 15% | Full test period |
| Win rate | ≥ 40% (trend), ≥ 50% (mean-reversion) | Full test period |
| Minimum trades | ≥ 30 | Full test period |
| No regime-specific failure | Pass in ≥ 2 of 3 regimes | Trending, ranging, volatile |

### Redundancy Check

- Correlation to existing active strategies ≤ 0.7 (rolling 30-day window)
- Behavioral differentiation documented

**If any condition fails → strategy remains Candidate.**

---

## Promotion to Probationary (Approved → Probationary)

A strategy enters live trading in Probationary state.

### Constraints

- Max allocation ≤ 25% of strategy allocation cap
- Cannot be the sole active strategy (minimum 2 strategies must be active)
- Hermes may down-weight but not up-weight beyond probation cap

### Duration

- Minimum: 1 full evaluation window (2–4 weeks of live trading)
- Cannot be shortened by human decision

---

## Promotion to Active (Probationary → Active)

A probationary strategy may become Active only if ALL are true:

- No rule violations during probation
- No unexpected risk behavior (veto rate < 50%)
- Performance consistent with backtest expectations (no material deviation)
- Adds diversification or defensive value to the pool
- Human reviewer approves promotion with written rationale

**Promotion is a governance decision, not automatic.**

---

## Ongoing Monitoring (Active State)

Active strategies are continuously evaluated on:

| Metric | Measurement | Threshold |
|--------|-------------|-----------|
| Rolling Sharpe | 50-trade window | Flag if < 0.5 |
| Max drawdown | From peak | Flag if > 20% |
| Win rate | 50-trade window | Flag if < 35% |
| Zero trades | While market favorable | Flag if > 100 bars |
| Correlation with portfolio DD | Rolling | Flag if > 0.8 |
| Veto frequency | Per session | Flag if > 50% of orders |

Hermes may adjust weights, but state changes are governed by this gate.

---

## Degradation Rules (Active → Degraded)

A strategy is Degraded if ANY occur:

| Condition | Trigger |
|-----------|---------|
| Rolling Sharpe drops below | 0.5 (50-trade window) |
| Drawdown exceeds | 20% from peak |
| Win rate drops below | 35% (50-trade window) |
| Zero trades for | 100+ bars while market favorable |
| Correlation with portfolio drawdown | > 0.8 (systemic risk) |

**Important (SPG-001 + Hermes World Model):** A strategy may NOT be degraded solely due to inactivity caused by Hermes restricting it. If Hermes has reduced a strategy's weight or paused it as part of regime-based risk management, the resulting inactivity is correct behavior, not a degradation trigger. See `docs/07_hermes_world_model.md` for details.

### Effects of Degradation

- Reduced allocation ceiling (Hermes caps at 50% of normal max)
- Increased scrutiny (weekly human review required)
- Logged in `strategy_states` with reason

---

## Suspension Rules (Degraded → Suspended)

A strategy is Suspended if:

- Multiple degradation periods without recovery (≥ 2 degradation episodes in 30 days)
- Risk-layer interventions escalate (kill switch triggered by this strategy's positions)
- Structural assumption appears invalid
- Human reviewer decides suspension is warranted

**Suspended strategies do not trade. Hermes allocates 0.**

---

## Retirement Rules (Any → Retired)

A strategy is Retired if:

- Assumptions are proven invalid
- Structural flaw discovered
- Redundant with a superior alternative
- Fails recovery after suspension
- Suspended for > 30 days without resolution

**Retirement is permanent for the given strategy ID/version.** A retired strategy cannot be reinstated. A new version must go through the full gate from Candidate.

---

## Reinstatement Policy

| Current State | Can Recover? | Path |
|---------------|-------------|------|
| Suspended | Yes | Fixes → full acceptance criteria → Probationary (min 1 week dry run) |
| Retired | **No** | Must be submitted as a new Candidate (new version ID) |

---

## Governance & Authority

| Decision | Authority |
|----------|-----------|
| Candidate → Approved | Human reviewer (written rationale required) |
| Approved → Probationary | Human reviewer |
| Probationary → Active | Human reviewer |
| Active → Degraded | Automatic (MetricsTracker detection) |
| Degraded → Suspended | Automatic (escalation) or Human |
| Suspended → Retired | Automatic (timeout) or Human |
| Any state change | Persisted in `strategy_states` with timestamp + reason |

**Hermes cannot promote or retire strategies.** It can only adjust weights within allowed envelopes.

---

## Non-Negotiable Rules

1. **No mid-session state changes** — All transitions happen between sessions
2. **No promotion based on short-term PnL** — Minimum evaluation windows are enforced
3. **No exceptions for "promising" behavior** — Gate criteria are mechanical, not subjective
4. **No strategy without persistence** — Every state change is recorded in SQLite
5. **Retirement is permanent** — No reinstatement, no exceptions

---

## Governance Cadence

| Review | Frequency | Action |
|--------|-----------|--------|
| Strategy health check | Every run | Hermes auto-detects degradation |
| Performance review | Weekly | Human reviews Degraded/Suspended strategies |
| Pool composition review | Monthly | Review correlation, diversification, retire if needed |
| Acceptance criteria review | Quarterly | Adjust thresholds based on market conditions |

---

## Audit Trail

Every state change must be logged with:

- Strategy ID and version
- Timestamp
- Previous state → New state
- Reason (human-readable)
- Trigger (auto-detect, human, time-based)

Example:
```
2026-04-29T10:00:00 | sma_crossover_v1 | Candidate → Approved | Reason: Passes all acceptance criteria, Sharpe 1.2, DD 8% | Trigger: human
2026-04-29T10:05:00 | sma_crossover_v1 | Approved → Probationary | Reason: Entering live evaluation | Trigger: human
2026-05-15T10:00:00 | sma_crossover_v1 | Probationary → Active | Reason: 2-week eval clean, Sharpe 1.1 live | Trigger: human
2026-06-01T10:00:00 | sma_crossover_v1 | Active → Degraded | Reason: Rolling Sharpe dropped to 0.4 | Trigger: auto-detect
2026-06-08T10:00:00 | sma_crossover_v1 | Degraded → Suspended | Reason: No recovery after 7 days | Trigger: auto-detect
2026-07-08T10:00:00 | sma_crossover_v1 | Suspended → Retired | Reason: 30-day suspension timeout | Trigger: auto-detect
```

---

## Current Strategy Pool

| Strategy | State | Promoted | Notes |
|----------|-------|----------|-------|
| sma_crossover | Probationary | 2026-04-29 | Original strategy, entering live eval |
| rsi_mean_reversion | Probationary | 2026-04-29 | Original strategy, entering live eval |

---

## Operating Principle

**A strategy earns its place by surviving discipline, not by looking clever.**