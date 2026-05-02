# Hermes-Centric Trading Framework

A modular, autonomous trading framework where strategies are black boxes and Hermes learns portfolio-level allocation.

## Architecture

```
Market Data (live or CSV) → Regime Detection → Hermes (Allocation) → Risk Veto → Broker (AlpacaBroker or MockBroker)
                                                                                         ↓
Strategies (black-box) ──→ Signals ───────────────────────────────────────────────────→ Orders
```

**There is exactly one execution path.** Paper vs live is a broker endpoint choice — not a runtime mode.

## Key Principles

- **Single execution path**: `TradingEngine` is the only orchestrator; paper vs live is determined by broker configuration only
- **Strategies are black boxes**: they generate signals, not allocate capital
- **Hermes allocates**: it decides when and how much to deploy each strategy
- **Risk is absolute**: deterministic veto layer that Hermes cannot override
- **All decisions are logged**: full audit trail for every allocation, veto, and fill
- **Hybrid CSV+live broker is forbidden**: the engine rejects CSV market data combined with a live broker

## Quick Start

```bash
pip install -e .
python scripts/run_demo.py          # Local replay with MockBroker
python scripts/run_engine.py        # Production (Alpaca — paper or live via env vars)
```

## Structure

- `src/core/` — Shared types, events, clock
- `src/strategies/` — Black-box strategy implementations
- `src/market/` — Data loading, regime detection, feed
- `src/hermes/` — Portfolio allocation agent (rule-based v1)
- `src/risk/` — Deterministic risk veto layer
- `src/execution/` — Broker interface + AlpacaBroker + MockBroker
- `src/engine/` — Main trading loop (TradingEngine — the single orchestrator)
- `src/monitoring/` — HealthSupervisor, event logging
- `config/` — YAML configuration files (`engine.yaml` is the primary config)
- `data/` — Historical data (CSV)
- `tests/` — Unit tests