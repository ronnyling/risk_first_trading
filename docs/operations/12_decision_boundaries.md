# Decision Boundaries

## Purpose

Explicit statements of what operators may do, must not do, and what requires different levels of intervention.

---

## What Operators MAY Do

These actions are safe and can be performed at any time:

| Action | How | Impact |
|--------|-----|--------|
| Change scaling profile | Dashboard → Scaling Profile selector | Immediate: limits change, no restart needed |
| Adjust Hermes schedule interval | Dashboard → Run mode → Scheduled → interval | Persists to config, next cycle uses new interval |
| Trigger manual Hermes run | Dashboard → "Trigger Hermes" button | One-time run, no lasting config change |
| Accept Hermes proposals | Dashboard → proposals section | Updates universe version |
| Decline Hermes proposals | Dashboard → proposals section | Archives proposal, no universe change |
| Start/stop StreamFetcher | Dashboard → Data Mode → Streaming | Session-only, does not persist |
| Start/stop scheduler | Dashboard → scheduler section | Creates/removes lock file |
| Review analytics | Dashboard → Analytics page | Read-only, no impact |
| Export reports | Dashboard → Analytics → CSV export | Creates files, no system impact |
| Archive & reset | Dashboard → State Management | Moves Hermes artifacts to archive |
| Restore from archive | Dashboard → State Management | Copies archived files back |
| View operations docs | Dashboard → Help / Ops | Read-only |

---

## What Operators MUST NOT Do

These actions are prohibited and could compromise system integrity:

| Prohibited Action | Why | Consequence |
|-------------------|-----|-------------|
| Edit `config/risk_limits.yaml` during a session | Risk spine must be stable during execution | Could cause unexpected risk behavior |
| Modify SQLite DB while engine is running | DB integrity, concurrent access | Could corrupt audit trail |
| Force-close positions without broker reconciliation | May close wrong positions | Could cause position mismatch |
| Lower kill switch threshold | Safety boundary, frozen config | Could disable critical safety mechanism |
| Modify Hermes agent logic | Agents are deterministic, tested | Could break decision quality |
| Change broker endpoint without pre-flight | Connection may fail mid-session | Could cause execution failure |
| Run scheduler daemon without monitoring | Scheduler is a background process | Could miss failures |
| Set poll interval below 60 seconds | yfinance rate limits | Could trigger API bans |
| Use CSV data in production | Production requires live data | Could cause stale/false signals |
| Bypass universe size validation | Scaling limits protect resources | Could cause OOM or timeouts |
| Disable staleness checking | Stale data is dangerous | Could cause bad decisions |
| Run multiple scheduler instances | Lock file mechanism single-instance | Could cause duplicate runs |
| Auto-apply meta-optimization proposals | All changes require HITL approval | Could destabilize system |
| Bypass drift detection | Safety mechanism against over-optimization | Could cause silent degradation |
| Override cooling-off periods | Protection against optimization churn | Could destabilize system |
| Deploy LLM changes directly | LLM is advisory only | Could introduce untested parameters |
| Edit risk_limits.yaml during session | Frozen config | Requires stress test re-verification |
| Run meta-optimization more than quarterly | Frequency limits | Could cause optimization chasing |

---

## What Requires Engine Restart

These changes take effect only after engine restart:

| Change | Config File | Restart Required |
|--------|-------------|-----------------|
| Universe symbols | `data/universe_current.json` | Yes (engine caches symbols at start) |
| Broker connection settings | `config/engine.yaml` | Yes (connection established at start) |
| Risk parameters | `config/risk_limits.yaml` | Yes (loaded once at start) |
| Engine interval | `config/engine.yaml` → `engine.interval` | Yes (set at start) |
| Strategy parameters | `config/strategies.yaml` | Yes (loaded once at start) |

---

## What Requires Config Change (Between Sessions Only)

These changes must be made when the engine is NOT running:

| Change | Config File | Verification Required |
|--------|-------------|----------------------|
| Risk limits modification | `config/risk_limits.yaml` | Stress test re-verification (SHA-256 update) |
| Kill switch threshold | `config/risk_limits.yaml` | Full stress test suite |
| Max leverage | `config/risk_limits.yaml` | Full stress test suite |
| Max drawdown | `config/risk_limits.yaml` | Full stress test suite |
| Scaling profile limits | `config/scaling_profiles.json` | Test with target universe size |
| Hermes agent parameters | `src/hermes/agents/` | Agent evaluation tests |
| Correlation threshold | `src/hermes/correlation.py` | Correlation tests |

---

## Escalation Matrix

| Situation | Operator Can Handle | Requires Developer | Requires Full Stop |
|-----------|--------------------|--------------------|-------------------|
| Scheduler not running | Yes — start it | | |
| StreamFetcher stale | Yes — restart streaming | | |
| Proposal to review | Yes — accept/decline | | |
| Scaling limit exceeded | Yes — switch profile | | |
| Hermes run failed | Check logs, retry | If persistent | |
| Broker disconnect | Yes — follow runbook | | |
| Kill switch triggered | Yes — wait for cooldown | If 3+ triggers | |
| Drawdown > 20% | | | Yes — stop engine |
| Engine crash | Yes — restart | If repeats | If unknown cause |
| DB corruption | | | Yes — delete DB, restart |
| Risk config changed mid-session | | | Yes — halt immediately |
| Unknown error | Capture logs | Yes — investigate | If safety-related |

---

## Configuration Freeze Rules

| Config | Frozen? | Version | SHA-256 |
|--------|---------|---------|---------|
| `config/risk_limits.yaml` | YES | 1.0.0 | `ba52189a8bc08313e887bac379378c9dbd4d9fc7382058f9c0c4d253eadb91a1` |
| `config/engine.yaml` | No | — | — |
| `config/hermes_policy.yaml` | No | — | — |
| `config/strategies.yaml` | No | — | — |
| `config/scaling_profiles.json` | No | — | — |
| `data/hermes_agentic_config.json` | No | — | — |

**Frozen configs** require:
1. Written justification for change
2. Full stress test re-verification
3. Updated SHA-256 checksum
4. Updated version number
5. Completion report review
