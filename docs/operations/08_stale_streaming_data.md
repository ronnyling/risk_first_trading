# Stale Streaming Data Runbook

## Symptoms

- Dashboard shows "Stream: 0 fresh, N stale, N dead"
- Hermes runs using streaming mode fall back to snapshot
- Buffer status: `STALE` or `DEAD` for multiple symbols
- StreamFetcher thread may have stopped

## Cause Hypotheses

1. **yfinance rate limiting** (too many requests)
2. **StreamFetcher thread crashed** (exception in poll loop)
3. **Network connectivity issue** (intermittent failures)
4. **Poll interval too short** (overwhelming API)
5. **Stale threshold too aggressive** (buffers go STALE quickly)

## Verification Steps

```bash
# 1. Check StreamFetcher status
# Dashboard sidebar → Data Mode → health summary

# 2. Check if streaming is enabled
# Dashboard sidebar → Data Mode → should show "Streaming"

# 3. Check for yfinance errors in logs
Select-String -Path logs\engine.log -Pattern "StreamFetcher|yfinance" | Select-Object -Last 10

# 4. Check buffer details programmatically
python -c "
# If stream_fetcher is accessible
# health = stream_fetcher.get_health_summary()
# for sym, status in health.items():
#     print(f'{sym}: {status}')
print('Check dashboard sidebar for stream health')
"
```

## Safe Actions

1. **If all buffers DEAD:**
   - The system automatically falls back to snapshot mode
   - No data loss — Hermes uses direct `fetch_bars()` calls
   - To restart streaming: stop and restart from dashboard

2. **If rate limited:**
   - Stop streaming: dashboard → "Stop Streaming"
   - Wait 5-10 minutes
   - Increase poll interval in scaling profile
   - Restart streaming

3. **If thread crashed:**
   - Stop streaming: dashboard → "Stop Streaming"
   - Restart streaming: dashboard → select "Streaming" mode
   - Check logs for crash reason

4. **If buffers STALE (not DEAD):**
   - Buffers still usable for Hermes
   - Next poll cycle should refresh them
   - If persistent: increase `stale_threshold_seconds`

5. **Adjusting parameters:**
   - `poll_interval_seconds`: Increase if rate limited (default: 300s)
   - `stale_threshold_seconds`: Increase if buffers go STALE too fast (default: 300s)
   - These are set in `StreamFetcher` initialization (via scaling profile)

## Actions Explicitly NOT Allowed

- **DO NOT** set poll interval below 60 seconds
- **DO NOT** disable staleness checking
- **DO NOT** use stale data for position sizing decisions
- **DO NOT** run multiple StreamFetcher instances

## Recovery Verification

1. Dashboard shows "Stream: N fresh, 0 stale, 0 dead"
2. Hermes runs in streaming mode use buffer data
3. No fallback to snapshot messages in logs
4. StreamFetcher thread running (check via dashboard)

## Escalation

- If yfinance blocks all requests: wait 1 hour, reduce poll frequency
- If specific symbol always DEAD: check if symbol is valid
- If StreamFetcher keeps crashing: check Python threading, increase timeout
- If streaming unreliable: use snapshot mode (default, recommended)
