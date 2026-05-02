# Data Feed Failure Runbook

## Symptoms

- Dashboard shows "Data feed stale" warning
- Engine logs: `RuntimeError` from `fetch_bars()`
- HealthEvents: `DATA_STALE`
- Hermes runs fail with "Insufficient completed bars" error
- StreamFetcher buffers: all DEAD

## Cause Hypotheses

1. **yfinance API failure** (rate limiting, outage)
2. **Market closed** (weekends, holidays)
3. **Network timeout** (slow connection)
4. **Symbol delisted** (ticker no longer valid)
5. **Insufficient bar count** (< 52 completed bars)

## Verification Steps

```bash
# 1. Test yfinance connectivity directly
python -c "
import yfinance as yf
t = yf.Ticker('BTC-USD')
df = t.history(period='5d', interval='1h')
print(f'Got {len(df)} bars')
print(df.tail(3))
"

# 2. Check if market is open
python -c "
from datetime import datetime
now = datetime.now()
print(f'Current time: {now}')
print(f'Day of week: {now.strftime(\"%A\")}')
"

# 3. Check streaming buffer status (if streaming mode)
# Dashboard sidebar → Data Mode → health summary

# 4. Check for rate limiting errors
Select-String -Path logs\engine.log -Pattern "yfinance|fetch_bars|RuntimeError" | Select-Object -Last 10
```

## Safe Actions

1. **If yfinance rate limited:**
   - Wait 5-10 minutes for rate limit to reset
   - Reduce polling frequency in scaling profile
   - Switch to snapshot mode if streaming is problematic

2. **If market closed:**
   - This is expected behavior
   - No action needed — system uses last available bars
   - Verify next trading day: data resumes normally

3. **If network timeout:**
   - Check internet connection
   - Retry after network restores
   - Engine retries automatically on next cycle

4. **If symbol delisted:**
   - Remove symbol from universe
   - Dashboard → accept/decline proposals to update universe
   - Or manually edit `data/universe_current.json`

5. **If insufficient bars:**
   - Wait for more data to accumulate
   - Check if market was recently added to universe
   - For new symbols: 52+ bars needed (52 hours for 1H bars)

## Actions Explicitly NOT Allowed

- **DO NOT** use CSV fallback data in production
- **DO NOT** lower the minimum bar count threshold (52 bars)
- **DO NOT** modify `fetch_bars()` to return partial data
- **DO NOT** disable incomplete bar filtering

## Recovery Verification

1. `fetch_bars()` succeeds for all symbols
2. Dashboard health indicator returns to green
3. Hermes runs complete successfully
4. Streaming buffers return to FRESH (if streaming mode)

## Escalation

- If yfinance is down for > 1 hour: check yfinance status page
- If specific symbol consistently fails: check if delisted
- If all symbols fail: check network, try different DNS
- If issue persists > 24 hours: contact data provider
