# Unexpected Drawdown Runbook

## Symptoms

- Portfolio value decreasing faster than expected
- Multiple consecutive losing trades
- Kill switch triggered
- FTMO daily loss approaching limit
- Hermes issuing CASH directives for multiple symbols

## Cause Hypotheses

1. **Market regime change** (trending → ranging or vice versa)
2. **Strategy underperformance** (strategy not suited to current conditions)
3. **Correlation concentration** (multiple correlated positions losing together)
4. **Position sizing too aggressive** (risk per trade too high)
5. **Unusual market event** (flash crash, news event)

## Verification Steps

```bash
# 1. Check current drawdown
python -c "
import sqlite3
conn = sqlite3.connect('data/trading_state.db')
fills = conn.execute('SELECT pnl FROM fills ORDER BY fill_id').fetchall()
cumulative = sum(f[0] for f in fills)
print(f'Cumulative PnL: {cumulative:.2f}')
print(f'Total fills: {len(fills)}')
conn.close()
"

# 2. Check recent fills
python -c "
import sqlite3
conn = sqlite3.connect('data/trading_state.db')
rows = conn.execute('SELECT symbol, side, fill_price, pnl, timestamp FROM fills ORDER BY fill_id DESC LIMIT 10').fetchall()
for r in rows:
    print(f'{r[4]}: {r[0]} {r[1]} @ {r[2]} PnL={r[3]:.2f}')
conn.close()
"

# 3. Check Hermes recent decisions
# Dashboard sidebar → Last Run Findings → per-symbol decisions

# 4. Check regime detection
# Hermes reasoning includes regime labels
```

## Safe Actions

### Drawdown Ladder Response

| Stage | Drawdown | Action |
|-------|----------|--------|
| NORMAL | < 10% | Continue monitoring |
| WARNING | 10-15% | Review strategy performance, reduce position sizes |
| PROTECTIVE | 15-20% | Pause new entries, review existing positions |
| SURVIVAL | 20-25% | Prepare for kill switch, manual intervention may be needed |
| CRITICAL | > 25% | Kill switch activates, wait for cooldown |

### Step-by-Step Response

1. **Assess severity:**
   - Check dashboard: status dot, health indicators
   - Check logs: last 10 fills and their PnL
   - Check Hermes: current risk directive

2. **If drawdown < 15%:**
   - Continue monitoring
   - Review Hermes recommendations
   - Check if market conditions have changed
   - Consider reducing position sizes via config (between sessions)

3. **If drawdown 15-20%:**
   - Stop opening new positions
   - Review existing position sizes
   - Check correlation warnings
   - Consider closing largest losing positions

4. **If drawdown > 20%:**
   - Stop engine: `Ctrl+C`
   - Document the situation
   - Review all open positions with broker
   - Do NOT restart until root cause identified

5. **After kill switch:**
   - Wait 100 bars for cooldown
   - Trading resumes automatically
   - Monitor closely for recurrence
   - If 3+ triggers: full stop and review

## Actions Explicitly NOT Allowed

- **DO NOT** increase risk parameters to "recover" losses
- **DO NOT** lower kill switch threshold
- **DO NOT** remove stop losses
- **DO NOT** double down on losing positions
- **DO NOT** restart engine repeatedly without understanding cause

## Recovery Verification

1. Drawdown stabilizes and begins recovering
2. Kill switch stops triggering
3. Successive trades show improving PnL
4. Hermes directives return to FULL/REDUCE (not all CASH)
5. Portfolio value trend turns positive

## Escalation

- If drawdown continues after kill switch cooldown: stop engine, full review
- If FTMO limits breached: document, may need to abandon challenge
- If root cause unclear: capture all logs, do not restart
- If market event is unprecedented: consider pausing until volatility subsides
