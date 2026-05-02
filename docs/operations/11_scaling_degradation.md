# Scaling Degradation Runbook

## Symptoms

- Dashboard warning: "Universe scaling limit: N symbols exceeds maximum"
- Hermes batch timeout warnings in logs
- Rate limiting active (yfinance cooldown messages)
- Partial results from Hermes runs
- Correlation engine using fewer symbols than configured

## Cause Hypotheses

1. **Universe expanded beyond profile limit** (too many symbols)
2. **Rate limiting by yfinance** (API throttling)
3. **Hermes batch timeout** (too many symbols for time budget)
4. **Memory pressure** (too many bars in buffers)
5. **Wrong scaling profile active** (SMALL for LARGE universe)

## Verification Steps

```bash
# 1. Check current scaling profile
python -c "
import json
config = json.loads(open('config/scaling_profiles.json').read())
print(f'Active profile: {config[\"active_profile\"]}')
profile = config['profiles'][config['active_profile']]
print(f'Max symbols: {profile[\"max_symbols\"]}')
print(f'Timeout: {profile[\"degradation\"][\"on_hermes_timeout_seconds\"]}s')
"

# 2. Check universe size
python -c "
import json
univ = json.loads(open('data/universe_current.json').read())
version_file = univ.get('current_version_file', '')
if version_file:
    data = json.loads(open(f'data/{version_file}').read())
    symbols = list(data.get('markets', {}).keys())
    print(f'Universe: {len(symbols)} symbols')
    print(f'Symbols: {symbols}')
"

# 3. Check for timeout warnings
Select-String -Path logs\engine.log -Pattern "BATCH_TIMEOUT|timeout|scaling" | Select-Object -Last 10

# 4. Check for rate limit messages
Select-String -Path logs\engine.log -Pattern "rate.limit|cooldown|yfinance" | Select-Object -Last 10
```

## Safe Actions

### If Universe Exceeds Profile Max

1. **Option A: Switch to larger profile**
   - Dashboard → Scaling Profile → select MEDIUM or LARGE
   - System immediately applies new limits

2. **Option B: Reduce universe**
   - Remove symbols from universe
   - Dashboard → accept/decline proposals to update universe
   - Or manually edit `data/universe_current.json`

3. **Option C: Accept truncation**
   - System automatically truncates to profile max
   - Excess symbols are skipped with warning
   - No data loss, just incomplete analysis

### If Rate Limited

1. **Increase poll interval:**
   - Switch to larger profile (MEDIUM/LARGE have shorter cooldowns)
   - Or accept slower polling in current profile

2. **Wait for rate limit reset:**
   - yfinance rate limits typically reset in 5-10 minutes
   - System continues with available data

3. **Reduce symbol count:**
   - Fewer symbols = fewer API calls
   - Stay within rate limit budget

### If Hermes Batch Timeout

1. **Increase timeout:**
   - Edit `config/scaling_profiles.json` → `on_hermes_timeout_seconds`
   - Increase from default (120s SMALL, 300s LARGE)
   - Restart scheduler/dashboard

2. **Reduce universe:**
   - Fewer symbols = faster batch completion
   - Stays within time budget

3. **Accept partial results:**
   - Timeout returns decisions for processed symbols
   - Skipped symbols get timeout annotation
   - Next run processes all symbols (fresh start)

### If Memory Pressure

1. **Reduce max_bars_per_symbol:**
   - Edit scaling profile → `memory_budget.max_bars_per_symbol`
   - Default: 250 bars per symbol

2. **Reduce universe:**
   - Fewer symbols = less total memory
   - Stays within `max_total_bars` budget

## Actions Explicitly NOT Allowed

- **DO NOT** set poll interval below 60 seconds
- **DO NOT** disable rate limiting
- **DO NOT** increase max_symbols without testing
- **DO NOT** bypass scaling validation in dashboard

## Recovery Verification

1. No more scaling warnings in logs
2. Hermes runs complete without timeout
3. All symbols processed (no truncation)
4. Rate limit messages stop
5. Memory usage within budget

## Escalation

- If scaling limits consistently too low: consider upgrading profile
- If yfinance rate limits persistent: consider alternative data provider
- If Hermes always times out: investigate agent performance, optimize code
- If memory consistently exhausted: reduce universe or upgrade hardware
