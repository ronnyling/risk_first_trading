# Engine Crash Recovery Runbook

## Symptoms

- Engine process no longer running (`tasklist | findstr python` returns nothing)
- No heartbeat logs for > 2 minutes
- Dashboard shows stale state (status dot: `!`)
- No recent fills or cycle completions in logs

## Cause Hypotheses

1. **Unhandled exception** (most common — check traceback)
2. **Out of memory** (large universe, many bars)
3. **DB lock contention** (SQLite locked by another process)
4. **OS killed process** (Windows resource limits)
5. **Manual termination** (someone killed the process)

## Verification Steps

```bash
# 1. Check if process is alive
tasklist | findstr python

# 2. Check last log entries
Get-Content logs\engine.log -Tail 20

# 3. Check for crash traceback
Select-String -Path logs\engine.log -Pattern "Traceback|Exception|CRITICAL" | Select-Object -Last 10

# 4. Check DB integrity
python -c "
import sqlite3
conn = sqlite3.connect('data/trading_state.db')
try:
    conn.execute('SELECT COUNT(*) FROM fills')
    print('DB OK: fills table accessible')
except Exception as e:
    print(f'DB ERROR: {e}')
conn.close()
"

# 5. Check for orphan lock files
dir data\.hermes_scheduler_lock
```

## Safe Actions

### Step 1: Identify the Cause

Read the last 50 lines of `logs/engine.log`:
```bash
Get-Content logs\engine.log -Tail 50
```

Look for:
- `Traceback` — Python exception (most common)
- `KILL SWITCH` — drawdown trigger (not a crash)
- `CRITICAL` — health supervisor detected issue
- `signal` — process received termination signal

### Step 2: Check State Consistency

```bash
# Verify last engine run completed
python -c "
import sqlite3
conn = sqlite3.connect('data/trading_state.db')
row = conn.execute('SELECT * FROM engine_runs ORDER BY run_id DESC LIMIT 1').fetchone()
if row:
    print(f'Last run: {row[0]}, finished: {row[2]}, bars: {row[3]}')
else:
    print('No engine runs recorded')
conn.close()
"
```

### Step 3: Reconcile Positions

```bash
# Check broker state (if connected)
# Compare with engine state
# Ensure no orphan orders
```

### Step 4: Clean Up

1. Remove stale scheduler lock if present:
   ```bash
   del data\.hermes_scheduler_lock
   ```

2. Stop any orphan StreamFetcher threads:
   - Dashboard → Data Mode → "Stop Streaming"

### Step 5: Restart Engine

```bash
python scripts/run_engine.py
```

### Step 6: Verify Recovery

1. Engine starts without errors
2. First cycle completes: `Cycle 1 complete: bars=X fills=Y vetoes=Z`
3. Heartbeat logs resume
4. Dashboard status dot returns to `O`

## Actions Explicitly NOT Allowed

- **DO NOT** restart without checking logs for crash cause
- **DO NOT** delete `data/trading_state.db` (unless corrupted beyond repair)
- **DO NOT** modify risk config to "prevent" the crash
- **DO NOT** restart if the crash was due to a code bug (fix the bug first)

## Recovery Verification

1. Engine process running (`tasklist | findstr python`)
2. Heartbeat logs appearing every 30s
3. Cycle completions logged
4. No ERROR or CRITICAL in new logs
5. Dashboard shows healthy state
6. Positions match broker state

## Escalation

- If crash repeats: capture full traceback, check GitHub issues
- If DB corrupted: delete DB, restart (historical data lost, system recovers)
- If OOM: reduce universe size (scaling profile), reduce `max_bars_per_symbol`
- If DB lock: check for orphan Python processes, kill them
- If unknown cause: capture all logs, do not restart until understood
