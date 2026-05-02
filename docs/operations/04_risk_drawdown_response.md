# Risk & Drawdown Response Playbook

## Purpose

How to monitor and respond to risk events, drawdowns, and kill switch triggers.

---

## Drawdown Monitoring

### Where to Check

| Source | Location | What It Shows |
|--------|----------|---------------|
| Dashboard main page | Status dot | Overall system health |
| Engine logs | `logs/engine.log` | Kill switch triggers, drawdown % |
| Persistence DB | `data/trading_state.db` → `fills` table | Cumulative PnL |
| Analytics page | Risk tab | Max drawdown, veto rate |

### Thresholds

| Threshold | Value | System Response |
|-----------|-------|-----------------|
| Warning | 10% drawdown | `global_risk_down` policy activates (50% position reduction) |
| Maximum | 20% drawdown | `max_drawdown_pct` limit in risk config |
| Kill switch | 25% drawdown | Trading paused for 100 bars cooldown |
| FTMO daily | 5% daily loss | FTMO-specific: halt trading for the day |

---

## Kill Switch Response

### What Happens

1. Engine detects drawdown > 25%
2. `KILL SWITCH TRIGGERED` logged
3. All trading paused for 100 bars (cooldown period)
4. After cooldown, trading resumes automatically
5. Health event emitted: `EXECUTION_PAUSED`

### Step-by-Step Response

1. **Do NOT intervene.** This is by design.
2. Wait for the 100-bar cooldown to complete
3. Monitor logs for "trading resumed" message
4. If kill switch triggers **3+ times in one session:**
   - Stop the engine (Ctrl+C)
   - Review strategy behavior
   - Check if market conditions have fundamentally changed
   - Consider running stress tests before restarting

### What NOT to Do

- **DO NOT** lower the kill switch threshold in `config/risk_limits.yaml`
- **DO NOT** restart the engine to "reset" the kill switch
- **DO NOT** manually override position limits
- **DO NOT** increase risk parameters to "recover" losses

---

## FTMO-Specific Procedures

### Daily Loss Limit

| Check | Threshold | Action |
|-------|-----------|--------|
| Daily PnL | > -5% | WARNING: reduce position sizes |
| Daily PnL | > -4% | CAUTION: approaching limit |
| Daily PnL | > -5% | HALT: stop trading for the day |

### Max Drawdown Limit

| Check | Threshold | Action |
|-------|-----------|--------|
| Total drawdown | > -10% | WARNING: review strategy performance |
| Total drawdown | > -15% | CRITICAL: consider pausing strategies |
| Total drawdown | > -20% | HALT: stop engine, investigate |

### FTMO Breach Response

1. Stop engine immediately: `Ctrl+C`
2. Do NOT attempt to "trade out" of the breach
3. Document the breach:
   - Date/time
   - Drawdown percentage
   - Strategies involved
   - Market conditions
4. Review and adjust before next session
5. If FTMO account is lost: document lessons learned

---

## Position Sizing Review

### When to Review

- After any kill switch trigger
- After 3+ consecutive losing trades
- When switching scaling profiles
- When changing universe size
- Weekly during normal operations

### How to Review

1. Check current sizing parameters in `config/engine.yaml`:
   - `max_position_pct: 0.95`
   - `max_risk_per_trade: 0.01` (1%)
   - `max_portfolio_risk: 0.05` (5%)

2. Review actual position sizes in fills table
3. Compare to intended sizing
4. Adjust only between sessions (never mid-session)

### Adjustment Procedure

1. Stop engine
2. Edit `config/engine.yaml` (or Hermes sizing config)
3. Run pre-flight checks
4. Restart engine
5. Monitor first few trades carefully

---

## Post-Drawdown Review Checklist

After any significant drawdown event:

| # | Check | Question |
|---|-------|----------|
| 1 | Market conditions | Was there an unusual market event? |
| 2 | Strategy behavior | Did strategies behave as designed? |
| 3 | Risk layer | Did risk controls activate correctly? |
| 4 | Hermes decisions | Were Hermes recommendations appropriate? |
| 5 | Position sizing | Were positions sized correctly? |
| 6 | Correlation | Did correlation warnings appear before drawdown? |
| 7 | Kill switch | Did kill switch trigger and recover properly? |
| 8 | Execution | Were fills at expected prices? |

---

## Escalation

| Situation | Action |
|-----------|--------|
| Kill switch triggers once | Normal — observe recovery |
| Kill switch triggers 2-3x in one session | Stop engine, review strategies |
| Kill switch triggers 5+ times | Stop engine, full strategy review required |
| Drawdown exceeds FTMO limits | Stop engine, document breach |
| Unknown cause of drawdown | Capture logs, check DB, do not restart until understood |
