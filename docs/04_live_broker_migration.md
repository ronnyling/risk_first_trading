# Live Broker Migration Plan

## Purpose
Provide a step-by-step plan to migrate from `MockBroker` to a live broker (IBKR/Alpaca),
while maintaining safety at every stage.

---

## Current State
- `MockBroker` executes simulated orders with configurable slippage and commission
- Paper trading mode via CSV replay
- No real money at risk

## Target State
- Live broker integration (Interactive Brokers or Alpaca)
- Real-time market data feed
- Live order execution with risk controls
- Production-grade logging and monitoring

---

## Migration Steps

### Step 1: Real-Time Data Feed
**Status: Not started**

Replace `MarketFeed` (CSV replay) with a live data source.

| Task | Details |
|------|---------|
| Choose data provider | IBKR TWS API, Alpaca, CCXT (crypto), Polygon.io |
| Implement `LiveFeed` class | Same interface as `MarketFeed`, but pushes real-time bars |
| Add websocket support | For sub-minute bar updates |
| Add data validation | Reject stale/out-of-order bars |
| Add data logging | Store all incoming bars to SQLite |

**Interface contract:**
```python
class LiveFeed(MarketFeed):
    def subscribe(self, symbol: str) -> None: ...
    def on_bar(self, callback: Callable) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
```

### Step 2: Live Broker Integration
**Status: Not started**

Replace `MockBroker` with a real broker.

| Task | Details |
|------|---------|
| Implement `IBBroker` class | Uses `ib_insync` or IBKR TWS API |
| Implement `AlpacaBroker` class | Uses `alpaca-py` |
| Add connection management | Auto-reconnect, heartbeat |
| Add order state tracking | Track PENDING → FILLED → CANCELLED |
| Add fill confirmation | Verify fills match expected price (within slippage tolerance) |
| Add error handling | Network errors, rejected orders, position limits |

**Interface contract (same as MockBroker):**
```python
class IBBroker(Broker):
    def submit_order(self, order: Order) -> Fill | None: ...
    def get_positions(self) -> dict[str, Position]: ...
    def get_portfolio_state(self) -> PortfolioState: ...
    def get_trade_history(self) -> list[Trade]: ...
```

### Step 3: Risk Layer Hardening
**Status: Not started**

Enhance risk controls for live trading.

| Task | Details |
|------|---------|
| Add max order size limit | Per-order notional cap |
| Add daily loss limit | Stop trading if daily PnL < threshold |
| Add position size validation | Verify order doesn't exceed position limits |
| Add order rate limiting | Max N orders per minute |
| Add market hours check | Only trade during market hours |
| Add kill switch persistence | Save kill switch state to disk |
| Add emergency close-all | One button to close all positions |

### Step 4: Order Management
**Status: Not started**

Replace simple market orders with proper order management.

| Task | Details |
|------|---------|
| Add limit orders | Support `OrderType.LIMIT` with price |
| Add stop-loss orders | Automatic stop-loss per strategy |
| Add take-profit orders | Automatic take-profit per strategy |
| Add order amendment | Modify/cancel pending orders |
| Add partial fill handling | Track partially filled orders |
| Add order timeout | Cancel unfilled orders after N seconds |

### Step 5: Live Monitoring
**Status: Not started**

Add real-time monitoring for live trading.

| Task | Details |
|------|---------|
| Add live dashboard | Web UI showing positions, PnL, allocations |
| Add alerts | Email/Slack on: fill, veto, kill switch, degradation |
| Add trade journal | Auto-log every trade with metadata |
| Add daily PnL report | End-of-day summary |
| Add anomaly detection | Flag unusual activity (e.g., rapid fills, large losses) |

### Step 6: Deployment
**Status: Not started**

| Task | Details |
|------|---------|
| Choose hosting | VPS (AWS, GCP, or local) |
| Add process management | systemd or Docker |
| Add log rotation | Prevent disk overflow |
| Add backup strategy | Daily config + state backup |
| Add runbook | Step-by-step recovery procedures |

---

## Safety Protocol

### Pre-Launch Checklist

- [ ] All 26 unit tests passing
- [ ] Paper trading runs for ≥ 2 weeks without issues
- [ ] MockBroker results match expected behavior
- [ ] Risk layer vetoes are working correctly
- [ ] Kill switch tested and verified
- [ ] Emergency close-all tested
- [ ] Logging is working and capturing all events
- [ ] Alerts are configured and tested
- [ ] Runbook is written and reviewed
- [ ] Human reviewer has signed off

### Go-Live Sequence

1. **Day 1-3**: Paper trading on live data (no real orders)
2. **Day 4-7**: Live data + live broker in paper mode (Alpaca paper, IBKR demo)
3. **Day 8-14**: Live trading with minimum capital (≤ $1,000)
4. **Day 15-30**: Gradual capital increase based on performance
5. **Day 31+**: Full capital deployment

### Rollback Plan

At any point:
1. Kill switch → stops all new orders
2. Emergency close-all → closes all positions
3. Disconnect broker → no new orders, positions held
4. Revert to MockBroker → resume replay mode

---

## Broker Comparison

| Feature | IBKR | Alpaca | CCXT |
|---------|------|--------|------|
| Markets | Stocks, futures, options, forex | Stocks, crypto | Crypto only |
| API quality | Complex (TWS) | Simple REST | Exchange-specific |
| Paper trading | Yes (demo account) | Yes (paper mode) | No (need separate) |
| Data quality | Excellent | Good | Varies |
| Commission | Low | Zero (stocks) | Varies |
| Python SDK | `ib_insync` | `alpaca-py` | `ccxt` |
| Rate limits | Moderate | Generous | Varies |

### Recommendation

For Hermes v1: **Alpaca** (simplest API, paper mode, zero commission on stocks)
For Hermes v2: **IBKR** (broader market access, better data, more order types)
For crypto-only: **CCXT** (access to 100+ exchanges)

---

## File Changes Required

### New Files
```
src/execution/
├── ib_broker.py          # IBKR integration
├── alpaca_broker.py      # Alpaca integration
├── live_feed.py          # Real-time data feed
└── order_manager.py      # Advanced order management

src/monitoring/
├── dashboard.py          # Web dashboard
├── alerts.py             # Email/Slack alerts
└── journal.py            # Trade journal

src/persistence/
├── database.py           # SQLite state store
└── migrations.py         # Schema migrations

docs/
├── runbook.md            # Recovery procedures
└── deployment.md         # Deployment guide
```

### Modified Files
```
src/risk/layer.py         # Add live-specific risk checks
src/engine/runner.py      # Add live mode support
config/
├── broker.yaml           # Broker connection settings
└── alerts.yaml           # Alert configuration
```

---

## Estimated Timeline

| Step | Scope | Estimate |
|------|-------|----------|
| Real-time data feed | LiveFeed + websocket | 1 week |
| IBKR/Alpaca broker | Broker integration | 2 weeks |
| Risk hardening | Live-specific controls | 1 week |
| Order management | Limit/stop/partial fills | 1 week |
| Monitoring | Dashboard + alerts | 2 weeks |
| Deployment + testing | VPS, Docker, runbook | 1 week |
| Paper trading validation | 2 weeks live paper | 2 weeks |
| **Total** | | **10 weeks** |