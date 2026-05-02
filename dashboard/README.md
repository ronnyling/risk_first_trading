# Hermes Observability Dashboard

Single-page production observability interface for the Hermes Trading System.

## Core Principles

1. **Read-only main surface** — the main page shows state only. No buttons that mutate state.
2. **All actions in the sidebar** — reset, restore, Hermes controls, diagnostics live in the hamburger panel.
3. **Truthful display** — no mock data, no placeholders. If a value is not real, it is not rendered.
4. **Calm when healthy** — a healthy system looks boring. Attention is only demanded when human judgment is required.

## How to Run

```bash
pip install streamlit pandas plotly pyyaml
streamlit run dashboard/app.py
```

## Layout

### Main Page (Read-Only)
- **Status dot** — green/yellow/red based on snapshot age
- **System Health** — Broker Connection, Account Value, Drawdown (with progress bar)
- **Risk & Protection** — Risk Profile, Risk Stage, Portfolio Risk, Open Positions count
- **Open Positions** — paginated table with filters
- **Trade History** — broker-confirmed fills (not signals or intents)
- **Hermes Advisory** — collapsed expander with proposals, alerts, handoffs
- **Universe Policy** — collapsed expander with version, diff, rollback

### Sidebar (All Actions)
- Auto-refresh toggle
- Trade filters (symbol, direction)
- Hermes controls (enable, run mode, schedule)
- Reset Runtime State (with confirmation)
- Restore Archived State
- Diagnostics (raw state JSON)

## Data Sources

| Source | Path | Written By |
|--------|------|-----------|
| Engine state | `data/state_snapshot.json` | `run_engine.py` |
| Health events | `data/health_events.jsonl` | `EventLogWriter` |
| Hermes proposals | `data/hermes_proposals/*.json` | Hermes Agentic |
| Hermes alerts | `data/hermes_alerts/*.json` | Hermes Agentic |
| Universe policy | `data/universe_*.json` | Streamlit / Hermes |
| Live policy | `config/policy.yaml` | Streamlit / Hermes |

## Architecture

- Decoupled from execution — if the dashboard crashes, trading continues
- Cross-process event bridge via JSONL file (`health_events.jsonl`)
- Auto-refresh every 5 seconds (configurable)
