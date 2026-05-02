# Hermes Operations Playbook

## Purpose

How to operate Hermes: manual runs, scheduled runs, interpreting outputs, managing proposals and alerts.

---

## Manual Trigger Procedure

### Via Dashboard

1. Open dashboard sidebar
2. Ensure "Enable Hermes" is ON
3. Set Run mode to "Manual"
4. Click "Trigger Hermes"
5. Wait for spinner to complete
6. Review results in sidebar "Last Run Findings"

### What Happens During a Manual Run

1. Universe symbols resolved from `universe_current.json`
2. Live bars fetched for each symbol via yfinance
3. MarketStates built with regime detection
4. CorrelationMatrix computed across all symbols
5. HermesCoordinator.run_batch() evaluates all symbols
6. Per-symbol proposals written to `data/hermes_proposals/`
7. Low-confidence alerts written to `data/hermes_alerts/`
8. Run summary written to `data/hermes_runs/`
9. Run persisted to SQLite `hermes_runs` table

---

## Scheduled Run Management

### Starting the Scheduler

**Option A: Dashboard**
1. Set Run mode to "Scheduled" in sidebar
2. Configure interval (15-1440 minutes)
3. Configure allowed hours (optional)
4. Click "Start Scheduler"

**Option B: Command Line**
```bash
python -m src.hermes.scheduler
```

### Configuring Schedule

| Parameter | Range | Default | Description |
|-----------|-------|---------|-------------|
| Interval | 15-1440 min | 60 min | Minimum time between runs |
| Allowed hours start | 0-23 | 0 | Earliest hour for runs |
| Allowed hours end | 0-23 | 23 | Latest hour for runs |

**Note:** Minimum interval is enforced at 15 minutes. Interval below 15 min is automatically raised.

### Monitoring Scheduler Health

In the dashboard sidebar:
- **Last scheduled run:** Shows time since last run and status
- **Scheduler daemon:** Shows "active" if running, with stop button

### Stopping the Scheduler

**Option A:** Dashboard → "Stop Scheduler" button
**Option B:** Delete the lock file: `del data\.hermes_scheduler_lock`

---

## Interpreting Hermes Outputs

### Risk Directives

| Directive | Meaning | Operator Action |
|-----------|---------|-----------------|
| `FULL` | Full risk budget available | Normal trading allowed |
| `REDUCE` | Risk budget partially consumed | Consider smaller positions |
| `SCALE_DOWN` | Portfolio risk exceeds cap | Review and potentially close positions |
| `CASH` | No trading recommended | Do not open new positions |

### Regime Labels

| Regime | Market Condition | Strategy Implication |
|--------|------------------|---------------------|
| `trending` | Strong directional move | Trend-following strategies favored |
| `ranging` | Sideways/consolidation | Mean-reversion strategies favored |
| `INDETERMINATE` | Cannot determine | CASH recommended |

### Confidence Scores

| Range | Level | Meaning |
|-------|-------|---------|
| > 0.7 | HIGH | Strong agent consensus |
| 0.4 - 0.7 | MEDIUM | Moderate consensus |
| < 0.4 | LOW | Weak consensus — triggers alert |

### Correlation Warnings

- `Concentration warning: BTC/USD↔ETH/USD correlation=0.85`
- Means: These two assets are highly correlated
- Implication: Holding both increases concentration risk
- Action: Consider reducing one, or accept higher portfolio correlation

### Agent Score Interpretation

Each agent outputs:
- **Score:** -1.0 (bearish) to +1.0 (bullish)
- **Confidence:** 0.0 (uncertain) to 1.0 (certain)

High confidence + high score = strong signal
High confidence + low score = strong bearish signal
Low confidence = agent is uncertain, weigh less

---

## Proposal Workflow

### Reviewing Proposals

Proposals appear in:
1. Dashboard sidebar: "Last Run Findings" → Proposals section
2. Files: `data/hermes_proposals/proposal_*.json`

### Accepting a Proposal

1. In dashboard sidebar, find the proposal
2. Click "Accept"
3. Universe is automatically updated with new version
4. Proposal archived to `data/hermes_archive/`

### Declining a Proposal

1. In dashboard sidebar, find the proposal
2. Click "Decline"
3. Proposal archived to `data/hermes_archive/`

### Universe Versioning

Each acceptance/decline creates a new universe version:
- `data/universe_v001.json` → `data/universe_v002.json`
- `data/universe_current.json` points to active version
- Rollback available via dashboard State Management

---

## Alert Workflow

### Types of Alerts

| Alert Type | Trigger | Action Required |
|------------|---------|-----------------|
| `REGIME_REANALYSIS` | Confidence < 0.4 | Review market conditions |
| Low confidence | Agent consensus weak | Consider manual analysis |
| Correlation warning | Highly correlated positions | Review portfolio concentration |

### Reviewing Alerts

Alerts appear in:
1. Dashboard sidebar: alerts section
2. Files: `data/hermes_alerts/alert_*.json`

### Taking Action

1. Read the alert trigger reason
2. Check per-symbol decision details
3. Decide: accept recommendation or override manually
4. Mark as reviewed in dashboard

### Archiving Resolved Alerts

Alerts are automatically archived when action is taken via the dashboard.
