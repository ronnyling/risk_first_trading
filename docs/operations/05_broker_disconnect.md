# Broker Disconnect Runbook

## Symptoms

- Dashboard shows "Alpaca disconnected" banner (red)
- Engine logs: `ERROR` with reconnect attempts
- HealthEvents: `ALPACA_DISCONNECTED` + `EXECUTION_PAUSED`
- Engine: execution paused, no new orders placed

## Cause Hypotheses

1. **TWS/Gateway crashed** (most common)
2. **Network connectivity lost** (internet down, firewall)
3. **API key expired/revoked** (Alpaca account issue)
4. **TWS API disabled** (settings changed)
5. **Port mismatch** (config vs TWS settings)

## Verification Steps

```bash
# 1. Check if TWS/Gateway is running
tasklist | findstr java

# 2. Check network connectivity
ping google.com

# 3. Check API keys
echo $ALPACA_API_KEY
echo $ALPACA_SECRET_KEY

# 4. Check port configuration
python -c "import yaml; c=yaml.safe_load(open('config/engine.yaml')); print(f'Config port: {c[\"ib\"][\"port\"]}')"

# 5. Check engine logs for reconnect attempts
Select-String -Path logs\engine.log -Pattern "reconnect|Alpaca" | Select-Object -Last 10
```

## Safe Actions

1. **If TWS crashed:**
   - Restart TWS application
   - Wait for "Connected" status in TWS
   - Engine auto-reconnects (up to 3 attempts)
   - Verify: dashboard shows "Alpaca restored" toast

2. **If network lost:**
   - Restore internet connectivity
   - Engine auto-reconnects
   - Verify: health indicator returns to green

3. **If API key issue:**
   - Update `.env` with valid credentials
   - Restart engine
   - Verify: "AlpacaBroker initialized successfully" in logs

4. **If port mismatch:**
   - Correct `config/engine.yaml` → `ib.port`
   - Restart engine
   - Verify: connection succeeds

## Actions Explicitly NOT Allowed

- **DO NOT** modify `config/risk_limits.yaml`
- **DO NOT** force-close positions manually without checking reconciliation
- **DO NOT** restart engine while TWS is still reconnecting
- **DO NOT** change API keys without verifying account status first

## Recovery Verification

1. Dashboard shows "Alpaca restored" toast
2. Engine logs: `"Alpaca connection healthy"`
3. HealthEvents: `ALPACA_RESTORED` + `EXECUTION_RESUMED`
4. Next cycle completes normally
5. Open positions match broker state

## Escalation

- If TWS won't restart: check Java version, reinstall TWS
- If API keys invalid: log into Alpaca dashboard, regenerate keys
- If all 3 reconnects fail: engine exits, restart manually
- If issue persists: contact broker support
