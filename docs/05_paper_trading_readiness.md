> **DEPRECATED** — This document describes a historical paper-trading gate process.
> Paper vs live is now a broker endpoint choice, not a runtime mode.
> See `docs/06_operational_runbook.md` for current procedures.
> See `scripts/run_engine.py` for the single authoritative entry point.

# Paper-Trading Readiness Gate

## Purpose

This document defines the mandatory checklist that must be satisfied before connecting the Hermes trading framework to Interactive Brokers for live paper trading. Each item must be verified and signed off before proceeding.

**This is a gate, not a suggestion. Skipping items here risks financial loss in later stages.**

---

## Readiness Checklist

### ✅ Phase 1: Architecture Validation

- [x] **Separation of concerns** — Strategies, Hermes, Risk, Execution are independent layers
- [x] **No circular authority** — Risk can veto Hermes; Hermes cannot override Risk
- [x] **Deterministic risk spine** — `risk/layer.py` produces identical results for identical inputs
- [x] **Audit trail** — Every allocation, veto, and fill has a reason string
- [x] **68/68 unit tests pass** — Core abstractions are mechanically sound (updated 2026-04-29)

### ✅ Phase 2: Stress Testing

- [x] **7 stress scenarios executed** — Baseline, single strategy, conflicting, slippage, drawdown, regime shifts, over-allocation
- [x] **Dashboard generated** — `reports/stress_test_dashboard.html`
- [x] **Audit trail complete** across all scenarios
- [x] **No allocation limit violations** in any scenario
- [ ] **Scenario-specific vetoes validated** — Requires larger position sizes to stress risk layer harder

### ✅ Phase 3: Persistence Layer

- [x] **SQLite schema defined** — `src/persistence/models.py`
- [x] **DB layer implemented** — `src/persistence/db.py`
- [x] **Engine integration** — `scripts/paper_trade.py` persists fills, vetoes, strategy states via event bus hooks
- [x] **State migration verified** — 7 fills stored in `data/trading_state.db` without slowing engine

### ✅ Phase 4: Paper-Trading Infrastructure

- [x] **Structured JSON logging** — `JsonLogFormatter` writes machine-readable JSON to `logs/paper_trading.json`
- [x] **Log rotation** — `RotatingFileHandler` with 100MB max, 30-day retention
- [x] **Graceful shutdown** — `ShutdownHandler` catches SIGINT/SIGTERM, flushes DB, saves state
- [x] **Health-check logging** — `HealthChecker` emits periodic heartbeats
- [x] **Error recovery** — Engine try/except with logging; individual order failures don't crash the loop
- [x] **Configurable via YAML** — `config/paper_trading.yaml` with all operational parameters

### ✅ Phase 5: Risk Layer Freeze

- [x] **Risk limits reviewed** — All 6 values in `config/risk_limits.yaml` confirmed appropriate for paper trading
- [x] **Kill switch tested end-to-end** — Verified via stress-test suite: trigger → block → cooldown → resume
- [x] **Risk layer marked semi-immutable** — `config/risk_limits.yaml` frozen at v1.0.0 with SHA-256 checksum. Changes require written justification + full stress-test re-run
- [x] **No risk layer changes without sign-off** — Governance header added to config file

### ✅ Phase 6: IB Connection Readiness

- [x] **IB broker adapter created** — `src/execution/ib_broker.py` with `IBBroker(Broker)`
- [x] **Capability flag implemented** — `supports_market_price_updates=False` on IBBroker, engine guards call
- [x] **Connection parameters** — Host, port, client ID configured in `config/paper_trading.yaml`
- [x] **Order types validated** — Only MARKET orders allowed in Phase 6 (limit orders rejected by validation)
- [x] **Position limits** — `max_order_notional` and `max_position_notional` caps enforced pre-submission
- [x] **Connection retry logic** — Configurable `reconnect_attempts` with `reconnect_delay_seconds`
- [x] **Timeout handling** — `fill_timeout_seconds` with automatic cancellation and partial fill handling
- [x] **Entry point wired** — `--source live` creates IBBroker; `--dry-run` validates connection only
- [x] **Graceful shutdown** — IB disconnect in both shutdown callback and finally block
- [x] **Contract remapping** — IBBroker remaps strategy symbols to configured `default_symbol` (SPY) at contract boundary
- [x] **Live connection verified** — TWS connected, account DU000 detected, `Stock(SPY, SMART, USD)` contract resolves
- [x] **Dry-run validated** — Connect → detect account → clean disconnect, no errors
- [x] **IB account configured** — Paper trading account DU000 active on TWS port 7497
- [x] **IB gateway installed** — TWS running and API connection confirmed (server version 176)
- [ ] **Market data subscriptions** — Required data feeds active for traded instruments (user action required for real-time fills)

### ✅ Phase 7: Market Data Adapter Layer

- [x] **MarketDataAdapter ABC** — `src/market/adapter.py` with `start()`, `stop()`, `get_next_bar()`, `get_history(n)`, `bars_processed`, `source_name`, `is_live`
- [x] **CsvMarketDataAdapter** — `src/market/csv_adapter.py` wraps CSV bars behind adapter interface
- [x] **_LegacyFeedAdapter** — backward-compatible shim for existing `MarketFeed` consumers
- [x] **IBMarketDataAdapter** — `src/market/ib_adapter.py` fetches IB historical bars, `from_config()` classmethod
- [x] **ShadowDataAdapter** — `src/market/shadow_adapter.py` runs CSV+IB in lockstep, logs structured comparison JSON
- [x] **Engine refactored** — `TradingEngine` accepts `MarketFeed | MarketDataAdapter`, zero behavioral change
- [x] **Entry point refactored** — `paper_trade.py` uses `CsvMarketDataAdapter` directly
- [x] **18 adapter tests** — `tests/test_market_adapter.py` validates ABC contract, CSV adapter, legacy adapter
- [x] **68/68 tests passing** — zero regressions

### ✅ Phase 8: Operational Readiness

- [x] **Runbook created** — `docs/06_operational_runbook.md` with startup, shutdown, monitoring, and rollback procedures
- [x] **Alert thresholds defined** — 9 conditions with severity levels and operator actions documented
- [x] **Daily review process** — `scripts/daily_report.py` generates structured JSON summary from persistence DB
- [x] **Incident response** — 5 scenarios documented (IB disconnect, kill switch, order rejection, disk/DB, stuck engine)
- [x] **Rollback plan** — `--source csv` flag provides full system on MockBroker with zero IB dependency

---

## Blocking Criteria

**DO NOT PROCEED to live paper trading if ANY of the following are true:**

1. Unit tests fail
2. Stress-test audit trail is incomplete
3. Kill switch has not been verified end-to-end
4. Risk layer has been modified without review
5. Graceful shutdown is not implemented
6. IB connection has not been tested with a simple order

---

## Sign-Off

| Phase | Status | Verified By | Date |
|-------|--------|-------------|------|
| 1. Architecture | ✅ Complete | Automated tests (26/26) | 2026-04-28 |
| 2. Stress Testing | ✅ Complete | 7 scenarios, dashboard | 2026-04-28 |
| 3. Persistence | ✅ Complete | SQLite + event bus hooks | 2026-04-28 |
| 4. Paper-Trading Infra | ✅ Complete | JSON logging, shutdown, health | 2026-04-28 |
| 5. Risk Freeze | ✅ Complete | Frozen v1.0.0, SHA-256 verified | 2026-04-28 |
| 6. IB Connection | ✅ Complete | 50/50 tests + live TWS connect + order submit | 2026-04-29 |
| 7. Adapter Layer | ✅ Complete | 68/68 tests, ABC + CSV + IB + Shadow | 2026-04-29 |
| 8. Operational | ✅ Complete | Runbook + daily report + 68/68 tests | 2026-04-29 |

---

## Next Steps (Ordered)

1. ~~Complete Phase 3 — Integrate persistence layer with TradingEngine~~ ✅
2. ~~Complete Phase 4 — Add structured logging, graceful shutdown, health checks~~ ✅
3. ~~Complete Phase 5 — Review and freeze risk limits~~ ✅
4. ~~Test IB connection — Start with a single instrument, single order~~ ✅
5. **Begin paper trading** — 24-72 hour dry-run observation period, then proceed to full paper trading

---

## What Paper Trading Validates

Paper trading is NOT about making money. It validates:

- **Latency** — Can the engine process market data fast enough?
- **Order flow** — Do orders route correctly through IB?
- **Position tracking** — Does the engine's state match IB's state?
- **Error handling** — How does the system behave when IB rejects an order?
- **Data quality** — Is the market data feed reliable and complete?
- **Operational maturity** — Can you run this system for 8+ hours without intervention?

---

## What Paper Trading Does NOT Validate

- **Strategy profitability** — Use backtesting for that
- **Risk model accuracy** — Use stress testing for that
- **ML model performance** — Use offline evaluation for that
- **Capital efficiency** — That comes with real capital and real slippage