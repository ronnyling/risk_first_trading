# Hermes Trading System — TradingView Port

Phase 19: Logic-Equivalent · Non-Repainting · Config-Driven

## Overview

This is a behavior-equivalent port of the Python Hermes trading system to TradingView Pine Script v5. It uses `strategy()` mode for backtesting with built-in position management.

**This port does NOT redesign, extend, or shortcut any logic.** It reflects the frozen Python source exactly.

## Three-Layer Timeframe Hierarchy

| Layer | Input | Role | What It Does |
|-------|-------|------|-------------|
| **HTF** | `hermesHTF` | Authority | Regime detection, agent evaluation, conflict resolution, family policy |
| **LTF** | `mtfLTF` | Diagnostic | MTF alignment check only (regime comparison for dampening) |
| **Exec** | `execTF` | Signal Timing | Strategy indicator computation and entry/exit signals |

**Critical:** MTF alignment compares HTF vs LTF (`mtfLTF`), NOT HTF vs Execution TF.

## Installation

1. Open TradingView (https://www.tradingview.com/)
2. Open Pine Editor (bottom panel)
3. Delete any existing code
4. Paste the contents of `hermes_system.pine`
5. Click "Add to Chart"

## Configuration

### Profile Selection

Select a preset profile from the dropdown. Each profile auto-configures:

| Profile | HTF | LTF | Exec | Base Risk | Families |
|---------|-----|-----|------|-----------|----------|
| `scalping` | 15m | 5m | 1m | 0.25% | Structural, Mean Rev |
| `intraday_default` | 1H | 15m | 5m | 0.50% | Structural, Mean Rev |
| `swing` | 4H | 1H | 15m | 1.50% | Structural, Mean Rev, Liquidity |
| `position_macro` | 1D | 4H | 1H | 3.50% | Structural, Liquidity |

### Manual Override

You can override any profile setting by changing the input values directly:

- **Timeframes:** Change `Hermes HTF`, `MTF LTF`, `Execution TF` (in minutes)
- **Risk:** Adjust `Base Risk %` and `Max Portfolio Risk %`
- **MTF:** Adjust `MTF Inertia Bars` and `Volatility Floor %`
- **Families:** Toggle individual family enablement

### Single Entry Path

Multiple signals within the same family (e.g., SMA crossover AND breakout both firing) collapse into a **single** `strategy.entry()` decision per bar. There is exactly one entry path per bar.

## What the Script Renders

### Logic (frozen, no modification)
- 4 Hermes agents (Ichimoku, Volatility, AMT, Wyckoff)
- Scoring engine (weighted composite)
- Conflict resolver (HCR-001)
- Position sizer (HPS-001)
- Strategy family policy (permission matrix)
- Orchestrator (priority selection)
- MTF alignment (inertia + dampening)
- Strategy signals (SMA, RSI, Breakout, AMT Value, Pullback Continuation, VWAP Reversion)

### Visual Output (validation only, no logic influence)
- Background color: MTF alignment state (green=aligned, yellow=misaligned)
- Bar color: Risk dampening indicator (orange when dampened)
- Labels: HTF regime, active strategy family
- Shapes: Entry triangles (green=long, red=exit)

## Non-Repainting Guarantees

- All logic wrapped in `barstate.isconfirmed` (bar close only)
- `request.security()` with `lookahead=barmerge.lookahead_off`
- HTF values constant across LTF bars within same HTF bar
- All persistent state uses `var` (survives recalculation)

## Validation Against Python

Run the equivalence tests to verify behavior matches:

```bash
PYTHONPATH=. python -m pytest tests/test_phase19_equivalence.py -v
```

These tests verify:
- Scoring engine produces identical composite scores
- Conflict resolver applies same HCR-001 rules
- Position sizer applies same HPS-001 rules
- Strategy family policy uses same permission matrix
- Orchestrator uses same priority order
- MTF alignment uses same inertia and dampening logic
- Pine Script file contains all required components

## Source of Truth

This script reflects exactly:
- `src/profiles/presets.py` — profile configurations
- `src/policy/strategy_family_policy.py` — permission matrix
- `src/orchestration/family_orchestrator.py` — priority order
- `src/policy/mtf_alignment_policy.py` — MTF dampening logic
- `src/hermes/conflict.py` — HCR-001 conflict resolution
- `src/hermes/sizing.py` — HPS-001 position sizing
- `src/hermes/scoring.py` — scoring engine
- `src/hermes/stub_agents.py` — 4 market agents
- `src/market/regime.py` — regime detection

## What This Script Does NOT Do

- Make trading decisions beyond what Python specifies
- Contain trading logic not present in Python
- Auto-detect trading style
- Modify Hermes, MTF, Policy, Orchestrator, or Strategies
- Use lookahead or future bar access
- Repaint signals
- Expose FTMO limits as user inputs (hard-coded only)

## FTMO Compliance (Phase 17)

The Pine Script includes hard-coded FTMO compliance logic matching the `ftmo_safe` profile.

### Hard-Coded Limits (NOT User Inputs)

```
FTMO_DAILY_LIMIT   = 0.045    // 4.5% daily loss limit (buffer below FTMO 5%)
FTMO_MAX_DD        = 0.09     // 9% max drawdown (buffer below FTMO 10%)
FTMO_PROFIT_TARGET = 0.10     // 10% profit target to pass
FTMO_CONSISTENCY   = 0.05     // 5% max single-trade contribution
```

**These values cannot be changed inside TradingView.** This enforces non-tamperable profile control, matching the Python system's design principle.

### How FTMO Guard Works

1. **Daily loss tracking:** Tracks equity at day start. If daily loss >= 4.5%, forces CASH and closes all positions.
2. **Max drawdown tracking:** Tracks all-time peak equity. If drawdown >= 9%, forces CASH and stops trading.
3. **Profit target:** If equity reaches 110% of initial capital, the evaluation is considered passing.
4. **Visual indicators:**
   - Green label: FTMO OK
   - Orange label: FTMO WARNING (approaching limit)
   - Red label: FTMO BREACHED (limit hit)
   - Red background: Active FTMO breach

### FTMO Evaluation Checklist

Before starting a live FTMO evaluation:

1. Run `python scripts/ftmo_tv_checklist.py` to verify readiness
2. Open TradingView and load `hermes_system.pine`
3. Apply to SPY 1H chart
4. Select `intraday_default` profile
5. Verify FTMO guard is active (green status label in top-right)
6. Connect to FTMO broker (if live)
7. Monitor via `python scripts/ftmo_tv_monitor.py --status`

### FTMO Monitoring

Use the Python monitoring script for independent compliance verification:

```bash
# Check FTMO limits
python scripts/ftmo_tv_monitor.py --status

# Analyze exported trades
python scripts/ftmo_tv_monitor.py --trades trades.csv
```

## What Comes Next

After validating this port:
- ~~Live execution (IB) with rolling BarStore~~ → TradingView execution (Phase 17)
- FTMO evaluation via TradingView (Phase 17)
- Strategy expansion
- Alpha tuning (last)
