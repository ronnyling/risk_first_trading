# Hermes Scheduling Failure Runbook

## Symptoms

- Scheduler not firing runs at expected interval
- Dashboard shows "No scheduled runs yet" or old last-run time
- Lock file exists but no active scheduler process
- Config file shows `run_mode: "Scheduled"` but runs not occurring

## Cause Hypotheses

1. **Scheduler daemon not running** (most common)
2. **Lock file stale** (>30 min old, blocking new runs)
3. **Config file corrupted** (invalid JSON)
4. **Allowed hours window blocking** (current hour outside window)
5. **Run failing silently** (status = "error" in config)
6. **Minimum interval not met** (< 15 min configured)

## Verification Steps

```bash
# 1. Check if scheduler process is running
tasklist | findstr python

# 2. Check lock file
type data\.hermes_scheduler_lock

# 3. Check scheduler config
type data\hermes_agentic_config.json

# 4. Check scheduler logs (if running in separate terminal)
# Look for "Scheduler firing run" or "Scheduler loop error"

# 5. Check if allowed hours are blocking
python -c "
from datetime import datetime
hour = datetime.now().hour
print(f'Current hour: {hour}')
# Compare with config allowed_hours
"
```

## Safe Actions

1. **If scheduler not running:**
   - Start it: `python -m src.hermes.scheduler`
   - Or use dashboard: sidebar → "Start Scheduler"
   - Verify: lock file created, runs start appearing

2. **If lock file stale:**
   - Delete the lock file: `del data\.hermes_scheduler_lock`
   - Scheduler will create new lock on next cycle
   - Verify: new run appears in activity log

3. **If config corrupted:**
   - Restore from backup or recreate:
   ```json
   {
     "enabled": true,
     "run_mode": "Scheduled",
     "schedule": {
       "type": "interval",
       "interval_minutes": 60,
       "allowed_hours": null
     }
   }
   ```
   - Restart scheduler

4. **If allowed hours blocking:**
   - Either wait for allowed window
   - Or update config to include current hour
   - Or set `allowed_hours: null` for 24/7 operation

5. **If run failing:**
   - Check `last_run_status` in config
   - Check Hermes logs for error details
   - Fix the underlying issue (usually data or broker)
   - Scheduler will retry on next interval

## Actions Explicitly NOT Allowed

- **DO NOT** set interval below 15 minutes (enforced minimum)
- **DO NOT** run multiple scheduler instances simultaneously
- **DO NOT** modify scheduler to auto-execute trades
- **DO NOT** bypass the lock file mechanism

## Recovery Verification

1. Lock file exists with recent timestamp
2. `last_run_at` in config updates after each run
3. `last_run_status` shows "completed"
4. New run summary appears in `data/hermes_runs/`
5. Dashboard activity log shows new run

## Escalation

- If scheduler crashes repeatedly: check Python environment
- If runs always fail: check data/broker connectivity
- If lock file keeps going stale: investigate long-running Hermes calls
- If config keeps getting corrupted: check disk permissions
