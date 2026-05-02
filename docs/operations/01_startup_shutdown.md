# Startup & Shutdown Playbook

## Purpose

Step-by-step procedures for starting and stopping all system components safely.

---

## Pre-Flight Checklist

Before every session, verify all items:

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
| 9 | Scaling profile correct | Dashboard sidebar shows correct profile | Profile matches intended deployment |

### Pre-Flight Commands

```bash
# Step 5: Verify risk config integrity
python -c "import hashlib; h=hashlib.sha256(open('config/risk_limits.yaml','rb').read()).hexdigest(); print(h); assert h == 'ba52189a8bc08313e887bac379378c9dbd4d9fc7382058f9c0c4d253eadb91a1', 'CHECKSUM MISMATCH'"

# Step 6: Check for stale processes
tasklist | findstr python
```

---

## Startup Procedure

### Step 1: Start the Engine

```bash
python scripts/run_engine.py
```

**Expected output:**
```
2026-05-02 09:30:00 [INFO] run_engine: Starting Hermes Engine (single execution path)
2026-05-02 09:30:00 [INFO] run_engine: Symbols: ['SPY'] | Poll interval: 5s
2026-05-02 09:30:00 [INFO] run_engine: AlpacaBroker initialized successfully
2026-05-02 09:30:00 [INFO] run_engine: Entering main orchestration loop...
```

### Step 2: Start the Dashboard

```bash
streamlit run dashboard/app.py
```

**Verify:** Dashboard loads at `http://localhost:8501` and shows health indicators.

### Step 3: Start Scheduler (Optional — Scheduled Mode Only)

```bash
python -m src.hermes.scheduler
```

**Verify:** Scheduler log shows "Hermes scheduler started".

**Alternative:** Use the "Start Scheduler" button in the dashboard sidebar.

### Step 4: Start Streaming (Optional — Streaming Mode Only)

Use the dashboard sidebar:
1. Select "Streaming" in the Data Mode section
2. Verify stream health shows "N fresh, 0 stale, 0 dead"

---

## Shutdown Procedure

### Graceful Shutdown (Preferred)

Shutdown components in reverse order:

**Step 1:** Stop streaming (if active)
- Dashboard sidebar → Data Mode → "Stop Streaming"

**Step 2:** Stop scheduler (if running)
- Dashboard sidebar → "Stop Scheduler"
- Or: delete `data/.hermes_scheduler_lock`

**Step 3:** Stop the engine
- Press `Ctrl+C` in the engine terminal

**Expected shutdown sequence:**
1. `ShutdownHandler` catches SIGINT
2. Current bar finishes processing
3. Broker disconnects (if live)
4. Persistence DB flushes and closes
5. Final state summary logged
6. Process exits cleanly

**Step 4:** Close dashboard
- Close the browser tab
- Stop Streamlit with `Ctrl+C` in its terminal

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

## Post-Shutdown Verification

| Check | Command | Expected |
|-------|---------|----------|
| No orphan processes | `tasklist | findstr python` | No output |
| DB integrity | Open `data/trading_state.db` in SQLite browser | Tables intact |
| Scheduler lock cleared | `dir data\.hermes_scheduler_lock` | File not found |
| Logs complete | `tail -5 logs/engine.log` | Clean exit message |
