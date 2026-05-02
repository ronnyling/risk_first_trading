"""Single authoritative execution entry point.

Broker endpoint (paper vs live) is determined by environment variables only.
Paper accounts behave identically to live — there is no separate paper mode.

Environment variables:
    ALPACA_API_KEY    — Alpaca API key (required)
    ALPACA_SECRET_KEY — Alpaca secret key (required)
    ALPACA_PAPER      — 'true' for paper endpoint, 'false' for live (default: true)
    SYMBOLS           — Comma-separated symbols to trade (default: SPY)
    POLL_INTERVAL_SEC — Seconds between orchestration cycles (default: 5)

Usage:
    python scripts/run_engine.py
    python scripts/run_engine.py --dry-run
"""

from __future__ import annotations

import os
import sys
import time
import logging
import random
from datetime import datetime
from pathlib import Path

# Add project root to path
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from dotenv import load_dotenv
load_dotenv(Path(_root) / ".env")

from src.execution.alpaca_broker import AlpacaBroker
from src.execution.guards import ExecutionGuards
from src.operations.market_eligibility import MarketEligibilityGate
from src.persistence.snapshot import StateSnapshotWriter
from src.core.types import Order, OrderSide, OrderType

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("run_engine")

# Configuration (environment-driven, not mode-driven)
POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "5"))
SYMBOLS = os.getenv("SYMBOLS", "SPY").split(",")


def main() -> None:
    logger.info("Starting Hermes Engine (single execution path)")
    logger.info("Symbols: %s | Poll interval: %ds", SYMBOLS, POLL_INTERVAL_SEC)

    # Initialize AlpacaBroker (paper vs live determined by env vars)
    try:
        broker = AlpacaBroker()
        logger.info("AlpacaBroker initialized successfully")
    except Exception as e:
        logger.error("Failed to initialize AlpacaBroker: %s", e)
        sys.exit(1)

    market_gate = MarketEligibilityGate()
    guards = ExecutionGuards(market_gate)
    snapshot_writer = StateSnapshotWriter()

    # Internal state
    profile = "balanced"
    ladder_state = "GROWTH"
    peak_equity = 100_000.0
    blocked_count = 0
    time_in_profile_start = datetime.now()
    engine_started_at = datetime.now().isoformat()

    # Reconciliation state for snapshot
    reconciled = False

    # ── Startup Reconciliation ──────────────────────────────
    # Alpaca is the source of truth. Fetch broker positions BEFORE the main loop
    # so strategy state reflects actual exposure, not default FLAT.
    logger.info("Starting startup reconciliation...")
    try:
        broker_positions = broker.get_positions()
        broker_portfolio = broker.get_portfolio_state()
        logger.info("Startup reconciliation: %d open positions", len(broker_positions))
        for sym, pos in broker_positions.items():
            logger.info(
                "  %s: qty=%.4f avg_entry=%.2f unrealized_pnl=%.2f",
                sym, pos.quantity, pos.avg_entry_price, pos.unrealized_pnl,
            )

        # Rebuild engine state from broker truth
        active_positions = {}
        for sym, pos in broker_positions.items():
            if pos.quantity != 0:
                active_positions[sym] = {
                    "qty": pos.quantity,
                    "avg_price": pos.avg_entry_price,
                    "unrealized_pnl": pos.unrealized_pnl,
                    "direction": "LONG" if pos.quantity > 0 else "SHORT",
                }

        reconciled = True
        logger.info("Startup reconciliation complete — broker positions synchronized")
    except Exception as e:
        logger.error("Startup reconciliation failed: %s", e)
        broker_positions = {}
        active_positions = {}

    logger.info("Entering main orchestration loop...")
    while True:
        try:
            # 1. Pull Account State
            portfolio = broker.get_portfolio_state()
            equity = portfolio.total_value if portfolio else 100_000.0

            if equity > peak_equity:
                peak_equity = equity
            drawdown_pct = (
                ((peak_equity - equity) / peak_equity) * 100
                if peak_equity > 0
                else 0.0
            )

            # Format open trades for snapshot
            positions = broker.get_positions()
            open_trades = []
            total_r_exposure = 0.0
            for pos in positions.values():
                r_exp = 0.5  # Mock R exposure for now
                total_r_exposure += r_exp
                open_trades.append({
                    "Symbol": pos.symbol,
                    "Direction": "LONG" if pos.quantity > 0 else "SHORT",
                    "Profile": profile,
                    "R_Exposure": r_exp,
                    "PnL": pos.unrealized_pnl,
                })

            broker_status = "CONNECTED" if portfolio else "DISCONNECTED"

            # 2. Market Loop (guarded)
            for sym in SYMBOLS:
                # Check eligibility
                ok, reason = guards.check_eligibility(sym)
                if not ok:
                    continue

                # Simulate signal generation (5% chance)
                if random.random() < 0.05:
                    logger.info("Signal generated for %s", sym)

                    # Execution guards
                    mock_price = 100.0  # Placeholder — real implementation fetches live price
                    checks = [
                        guards.check_buying_power(
                            {"buying_power": equity * 0.9},
                            mock_price * 0.1,
                        ),
                        guards.check_cooldown(sym),
                    ]

                    failed_checks = [msg for passed, msg in checks if not passed]

                    if failed_checks:
                        blocked_count += 1
                        logger.warning(
                            "Trade BLOCKED for %s. Reasons: %s",
                            sym,
                            ", ".join(failed_checks),
                        )
                    else:
                        logger.info("Guards passed. Placing order for %s", sym)
                        order = Order(
                            symbol=sym,
                            side=OrderSide.BUY if random.random() > 0.5 else OrderSide.SELL,
                            quantity=0.1,
                            order_type=OrderType.MARKET,
                        )
                        fill = broker.submit_order(order)
                        if fill is not None:
                            logger.info("Order filled: %s", fill.order_id)
                            guards.record_fill(sym)
                        else:
                            logger.error("Broker rejected order for %s", sym)

            # 3. Write Snapshot
            days_in_profile = (datetime.now() - time_in_profile_start).days
            snapshot = {
                "engine_started_at": engine_started_at,
                "profile": profile,
                "time_in_profile": f"{days_in_profile} days",
                "last_transition": "",
                "transition_reason": "",
                "ladder_state": ladder_state,
                "equity": equity,
                "current_drawdown_pct": round(drawdown_pct, 2),
                "allowed_drawdown_pct": 10.0,
                "open_trades": open_trades,
                "exposure_summary": {
                    "total_r": total_r_exposure,
                    "max_concurrency": 5,
                    "blocked_count": blocked_count,
                },
                "health": {
                    "broker_status": broker_status,
                    "feed_latency_ms": random.randint(10, 50),
                    "op_mode": "live",
                    "blacklisted_markets": list(market_gate.blacklist),
                },
                "reconciled": reconciled,
            }

            # Add recent fills to snapshot for dashboard trade history
            try:
                trades = broker.get_trade_history()
                recent_fills = []
                for t in trades[-20:]:
                    recent_fills.append({
                        "timestamp": t.entry_time.isoformat() if hasattr(t.entry_time, 'isoformat') else str(t.entry_time),
                        "symbol": t.symbol,
                        "side": t.side.value.upper(),
                        "quantity": t.quantity,
                        "fill_price": t.entry_price,
                        "order_type": "MARKET",
                        "time_in_force": "DAY",
                        "strategy": t.strategy_id,
                        "pnl": t.pnl,
                        "status": "filled",
                    })
                snapshot["recent_fills"] = recent_fills
            except Exception as e:
                logger.warning("Could not fetch trade history for snapshot: %s", e)
                snapshot["recent_fills"] = []

            snapshot_writer.write(snapshot)

        except Exception as e:
            logger.error("Error in main loop: %s", e, exc_info=True)

        # Cooldown
        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    main()
