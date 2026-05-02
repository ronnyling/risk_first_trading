# Operational Runbook

## Purpose

This document defines the procedures for safely operating the Hermes trading system. It is the single source of truth for startup, monitoring, incident response, and shutdown.

**There is exactly one execution path.** Paper vs live is a broker endpoint choice — not a runtime mode.

**This is a gate document. Follow it every session.**

---

## 1. Pre-Flight Checklist

Before every execution session, verify all items:

| # | Check | How to Verify | Pass Criteria |
|---|-------|---------------|---------------|
| 1 | TWS/Gateway running | TWS window visible or Gateway process running | Application responding |
| 2 | API connection enabled | TWS → Edit → Global Configuration → API → Enable ActiveX and Socket Clients | Checked |
| 3 | Port matches config | TWS port = 7497 (paper) or 7496 (live) | Matches `config/engine.yaml` → `ib.port` |
| 4 | Broker credentials | `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` set in `.env` | Env vars present |
| 5 | Risk config frozen | `sha256sum config/risk_limits.yaml` matches expected hash | Checksum matches |
| 6 | No stale processes | `tasklist | findstr python` shows no orphan engines | No stale processes |
| 7 | Disk space available | Check drive free space | > 1 GB free |
| 8 | Config reviewed | `config/engine.yaml` inspected | No unexpected changes |

### Pre-Flight Commands

```bash
# Step 5: Verify risk config integrity
python -c "import hashlib; h=hashlib.sha256(open('config/risk_limits.yaml','rb').read()).hexdigest(); print(h); assert h == 'ba52189a8bc08313e887bac379378c9dbd4d9fc7382058f9c0c4d253eadb91a1', 'CHECKSUM MISMATCH'"
```

---

## 2. Startup Procedure

### Option A: CSV Replay (Offline / Testing)

```bash
python scripts/run_demo.py
```

- Uses historical CSV data (`data/sample/btcusd_1h.csv`)
- Runs through `TradingEngine` with `MockBroker`
- Single pass through the data

### Option B: Production Execution (Alpaca)

```bash
python scripts/run_engine.py
```

- Connects to Alpaca via `AlpacaBroker`
- Paper vs live determined by `ALPACA_PAPER` env var
- Environment-driven configuration via `.env`

### Expected Startup Output

```
2026-05-02 09:30:00 [INFO] run_engine: Starting Hermes Engine (single execution path)
2026-05-02 09:30:00 [INFO] run_engine: Symbols: ['SPY'] | Poll interval: 5s
2026-05-02 09:30:00 [INFO] run_engine: AlpacaBroker initialized successfully
2026-05-02 09:30:00 [INFO] run_engine: Entering main orchestration loop...
```

---

## 3. Healthy State Indicators

What "normal" looks like during operation:

### Log Indicators

| Indicator | Where | Healthy Pattern |
|-----------|-------|-----------------|
| Heartbeat | `logs/engine.log` | `HEARTBEAT: engine alive at ...` every 30s |
| Cycle completion | `logs/engine.log` | `Cycle N complete: bars=X fills=Y vetoes=Z` |
| No CRITICAL | `logs/engine.json` | Zero entries with `"level": "CRITICAL"` |
| No ERROR | `logs/engine.json` | Zero entries with `"level": "ERROR"` |
| Kill switch | `logs/engine.log` | **Never** appears during normal operation |

### Persistence Indicators

```bash
# Quick DB health check
python -c "
import sqlite3
conn = sqlite3.connect('data/trading_state.db')
runs = conn.execute('SELECT COUNT(*) FROM engine_runs WHERE finished_at IS NOT NULL').fetchone()[0]
fills = conn.execute('SELECT COUNT(*) FROM fills').fetchone()[0]
vetoes = conn.execute('SELECT COUNT(*) FROM vetoes').fetchone()[0]
print(f'Runs: {runs}, Fills: {fills}, Vetoes: {vetoes}')
conn.close()
"
```

### Behavioral Indicators

- Fills occur roughly once per bar per active strategy (when signals fire)
- Veto count is low relative to fill count (< 50% veto ratio is normal)
- Portfolio value changes gradually (no sudden 50% drops)
- Strategy states remain `active` (no unexpected suspensions)

---

## 4. Alert Thresholds

### Severity Levels

| Level | Meaning | Operator Action |
|-------|---------|-----------------|
| **INFO** | Normal operational events | Log and continue |
| **WARN** | Anomaly that resolved or is recoverable | Note pattern, monitor |
| **CRITICAL** | System integrity at risk | Investigate immediately |
| **STOP** | Safety boundary breached | Halt and investigate |

### Alert Conditions

| Condition | Severity | Auto-Response | Operator Action |
|-----------|----------|---------------|-----------------|
| Kill switch cooldown expired | INFO | Trading resumes | Note it, continue |
| Fill timeout (30s, no fill) | WARN | Order cancelled | Check broker connection |
| Reconnect attempt triggered | WARN | System retries | Monitor pattern |
| 3/3 reconnects failed | CRITICAL | Engine exits | Restart manually |
| Kill switch triggered (DD > 25%) | CRITICAL | Trading paused 100 bars | Observe recovery |
| Broker connection lost | CRITICAL | Reconnect attempts | Check TWS/network |
| Unhandled exception in engine | CRITICAL | Engine crashes | Check traceback, fix |
| Risk config changed mid-session | STOP | **None — must observe** | **HALT immediately** |
| DB write failure | CRITICAL | May lose audit trail | Check disk/permissions |

### What NOT to Alert On

- Vetoed orders (this is normal risk behavior)
- Strategy allocating weight = 0 (Hermes is doing its job)
- Regime changes (expected market behavior)
- Kill switch triggering once (system designed for this)

---

## 5. Incident Response Procedures

### Scenario A: Broker Connection Lost

**Symptoms:** Logs show `ERROR` with reconnect attempts, or engine exits.

**Procedure:**
1. Check if TWS/Gateway is still running (look at TWS window)
2. If TWS crashed → restart TWS, wait for API to be ready, restart engine
3. If network issue → check internet connectivity
4. If reconnects succeeded → system self-healed, note in log, continue monitoring
5. If all 3 reconnects failed → engine exits, restart manually:
   ```bash
   python scripts/run_engine.py
   ```

**Do NOT:** Restart engine while TWS is still reconnecting. Wait for TWS to be fully ready.

### Scenario B: Kill Switch Triggered

**Symptoms:** `KILL SWITCH TRIGGERED: drawdown XX.X% > 25.0%` in logs.

**Procedure:**
1. **Do NOT intervene.** This is by design.
2. System auto-pauses for 100 bars (cooldown period)
3. After cooldown, trading resumes automatically
4. If kill switch triggers **3+ times in one session:**
   - Stop the engine (Ctrl+C)
   - Review strategy behavior
   - Check if market conditions have fundamentally changed
   - Consider running stress tests before restarting

**Do NOT:** Lower kill switch threshold to prevent future triggers. The threshold is frozen.

### Scenario C: Unexpected Order Rejection

**Symptoms:** Broker rejects an order (not a risk veto).

**Procedure:**
1. Check `vetoes` table: `SELECT * FROM vetoes ORDER BY veto_id DESC LIMIT 10;`
2. If reason contains risk layer text → expected behavior, no action
3. If broker rejected → check:
   - Contract validity (symbol, exchange, currency)
   - Market hours (is market open?)
   - Position limits in account
   - Order size vs. allowed minimums

### Scenario D: Disk or Database Issues

**Symptoms:** DB write errors, log files missing, disk full warnings.

**Procedure:**
1. Check disk space: `dir data\` and `dir logs\`
2. If logs too large → safe to archive old `logs/engine.log.*` backups
3. If DB locked → check for stale Python processes: `tasklist | findstr python`
4. Kill any orphan processes, then restart
5. If DB corrupted → delete `data/trading_state.db` (will recreate on next start; historical data lost but system recovers)

### Scenario E: Engine Loop Stuck

**Symptoms:** No heartbeat logs for > 2 minutes, no cycle completion messages.

**Procedure:**
1. Check if engine process is still alive: `tasklist | findstr python`
2. If alive but stuck → send SIGINT (Ctrl+C in terminal) for graceful shutdown
3. If not responding → kill process, check logs for last known state
4. Restart engine

---

## 6. Shutdown Procedure

### Graceful Shutdown (Preferred)

```bash
# Press Ctrl+C in the terminal running the engine
```

**What happens:**
1. `ShutdownHandler` catches SIGINT
2. Current bar finishes processing
3. Broker disconnects (if live)
4. Persistence DB flushes and closes
5. Final state summary logged
6. Process exits cleanly

### Verify Clean Shutdown

```bash
# Check logs for completion message
grep "ENGINE COMPLETE" logs/engine.log

# Check no orphan processes
tasklist | findstr python

# Check DB has run record
python -c "
import sqlite3
conn = sqlite3.connect('data/trading_state.db')
row = conn.execute('SELECT * FROM engine_runs ORDER BY run_id DESC LIMIT 1').fetchone()
print(f'Run {row[0]}: finished_at={row[2]}, bars={row[3]}, fills={row[6]}')
conn.close()
"
```

### Forced Shutdown (Last Resort)

```bash
# Windows: kill by process name (kills ALL python processes)
taskkill /F /IM python.exe

# Or find specific PID
tasklist | findstr python
taskkill /F /PID <pid>
```

**Warning:** Forced shutdown may lose in-flight state. Check DB integrity after.

---

## 7. Rollback Plan: Mock Broker Fallback

If live broker integration fails persistently, the system runs on CSV + MockBroker:

```bash
python scripts/run_demo.py
```

**What this gives you:**
- Full strategy execution (SMA crossover, RSI mean reversion)
- Full Hermes allocation decisions
- Full risk layer enforcement (kill switch, drawdown limits)
- Full persistence (fills, vetoes, allocations in SQLite)
- Full structured logging

**What this does NOT give you:**
- Real market data (uses historical CSV)
- Real broker fills (simulated by MockBroker)
- Real-world latency and slippage

**When to use rollback:**
- IB TWS is down and cannot be restarted
- IB API is behaving unexpectedly
- You need to validate system behavior without broker dependency
- During IB Gateway updates or maintenance

**No code changes required.** The `run_demo.py` script uses `MockBroker` with CSV data.

---

## 8. Daily Review Process

After each trading session, run the daily report:

```bash
python scripts/daily_report.py                    # Today's summary
python scripts/daily_report.py --date 2026-04-29  # Specific date
python scripts/daily_report.py --days 7           # Last 7 days
```

### What to Review

| Item | Healthy Pattern | Investigate If |
|------|-----------------|----------------|
| Total fills | > 0 (strategies are active) | 0 fills in a full session |
| Veto ratio | < 50% of orders | > 80% vetoed |
| Kill switch events | 0 | > 2 in one day |
| Portfolio PnL | Small, gradual changes | > 5% single-day swing |
| Broker disconnects | 0 | > 0 |
| Strategy states | All `active` | Any `suspended` or `retired` |
| Fill prices | Close to market price at signal time | Significant deviation |

### Report Output

Reports are saved to `logs/daily_report_YYYY-MM-DD.json` in structured JSON format for programmatic analysis.

---

## 9. Configuration Reference

### Key Configuration Paths

| Config | File | Frozen? |
|--------|------|---------|
| Risk limits | `config/risk_limits.yaml` | Yes (v1.0.0, SHA-256 verified) |
| Engine config | `config/engine.yaml` | No (can be edited between sessions) |
| Hermes policy | `config/hermes_policy.yaml` | No |
| Strategy params | `config/strategies.yaml` | No |

### Critical Safety Values

| Parameter | Value | Source |
|-----------|-------|--------|
| Kill switch threshold | 25% drawdown | `risk_limits.yaml` |
| Cooldown after kill | 100 bars | `risk_limits.yaml` |
| Max leverage | 1.0x | `risk_limits.yaml` |
| Max total exposure | 90% | `risk_limits.yaml` |
| IB fill timeout | 30 seconds | `engine.yaml` |
| IB reconnect attempts | 3 | `engine.yaml` |
| Health heartbeat | 30 seconds | `engine.yaml` |

### Prohibited Mid-Session Actions

- **DO NOT** edit `config/risk_limits.yaml` during a session
- **DO NOT** restart the engine without checking for stale processes
- **DO NOT** lower risk thresholds to avoid kill switches
- **DO NOT** modify the DB while the engine is running

---

## 10. Emergency Contacts and Escalation

| Situation | Action |
|-----------|--------|
| IB TWS unresponsive | Restart TWS application |
| Kill switch keeps triggering | Stop engine, run stress tests, review strategies |
| DB corruption | Delete DB, restart (data lost, system recovers) |
| Unknown error | Capture full traceback, check `logs/engine.log`, do not restart until understood |
| System appears healthy but behavior is unexpected | Run `python scripts/daily_report.py` and review |

---

## Appendix: Log File Locations

| File | Purpose | Rotation |
|------|---------|----------|
| `logs/engine.log` | Human-readable text log | 100MB, 30 backups |
| `logs/engine.json` | Machine-readable JSON log | 100MB, 30 backups |
| `logs/daily_report_YYYY-MM-DD.json` | Daily summary reports | No rotation |
| `data/trading_state.db` | SQLite persistence | No rotation |
