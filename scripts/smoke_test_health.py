"""10-second smoke test: Alpaca health lifecycle.

OPERATOR / DEBUG TOOL ONLY — not a runtime dependency.
Never imported by engine or Streamlit. Not required for normal startup.

Phases:
1. Valid credentials → verify health check succeeds
2. Invalid credentials → verify ALPACA_DISCONNECTED + EXECUTION_PAUSED
3. Restore valid → verify ALPACA_RESTORED + EXECUTION_RESUMED

Usage:
    python scripts/smoke_test_health.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from dotenv import load_dotenv
load_dotenv(Path(_root) / ".env")

from src.core.events import EventBus
from src.execution.broker import Broker
from src.monitoring.health_supervisor import HealthSupervisor, CircuitState
from src.monitoring.event_log import EventLogWriter


class EventCollector:
    """Collects events for quick assertion."""
    def __init__(self):
        self.events: list[str] = []

    def __call__(self, event_name: str, *args, **kwargs):
        self.events.append(event_name)

    def has(self, name: str) -> bool:
        return name in self.events

    def reset(self):
        self.events.clear()


def main():
    print("\n" + "=" * 50)
    print("SMOKE TEST: Alpaca Health Lifecycle")
    print("=" * 50)

    bus = EventBus()
    collector = EventCollector()
    writer = EventLogWriter()

    for ev in ["ALPACA_RESTORED", "ALPACA_DISCONNECTED", "EXECUTION_PAUSED", "EXECUTION_RESUMED"]:
        bus.subscribe(ev, collector)
        bus.subscribe(ev, writer)

    # --- Phase 1: Valid credentials ---
    print("\n[Phase 1] Valid credentials...")
    try:
        from src.execution.alpaca_broker import AlpacaBroker
        real_broker = AlpacaBroker()
        supervisor = HealthSupervisor(
            event_bus=bus, broker=real_broker,
            enabled_checks={"alpaca"}, max_retries=2,
        )
        results = supervisor.check_all()
        ok = any(r.component == "alpaca" and r.healthy for r in results)
        print(f"  Health check: {'PASS' if ok else 'FAIL'}")
        print(f"  State: {supervisor.states['alpaca'].value}")
    except Exception as e:
        print(f"  SKIP: {e}")
        return 1

    # --- Phase 2: Invalid credentials ---
    print("\n[Phase 2] Invalid credentials...")
    from unittest.mock import Mock
    bad_broker = Mock(spec=Broker)
    bad_broker.get_portfolio_state.side_effect = Exception("Invalid API key")

    supervisor2 = HealthSupervisor(
        event_bus=bus, broker=bad_broker,
        enabled_checks={"alpaca"}, max_retries=2,
    )
    for _ in range(3):
        supervisor2.check_all()

    disconnected = collector.has("ALPACA_DISCONNECTED")
    paused = collector.has("EXECUTION_PAUSED")
    print(f"  ALPACA_DISCONNECTED: {'EMITTED' if disconnected else 'MISSING'}")
    print(f"  EXECUTION_PAUSED:    {'EMITTED' if paused else 'MISSING'}")
    print(f"  Circuit state: {supervisor2.states['alpaca'].value}")

    # --- Phase 3: Recovery ---
    print("\n[Phase 3] Recovery (restore valid credentials)...")
    collector.reset()
    supervisor3 = HealthSupervisor(
        event_bus=bus, broker=real_broker,
        enabled_checks={"alpaca"}, max_retries=2,
    )
    supervisor3.states["alpaca"] = CircuitState.DEGRADED
    supervisor3.failure_counts["alpaca"] = 3

    results3 = supervisor3.check_all()
    restored = collector.has("ALPACA_RESTORED")
    resumed = collector.has("EXECUTION_RESUMED")
    print(f"  ALPACA_RESTORED: {'EMITTED' if restored else 'MISSING'}")
    print(f"  EXECUTION_RESUMED: {'EMITTED' if resumed else 'MISSING'}")
    print(f"  Circuit state: {supervisor3.states['alpaca'].value}")

    # --- Summary ---
    all_ok = ok and disconnected and paused and restored and resumed
    print("\n" + "=" * 50)
    print(f"RESULT: {'ALL PASSED' if all_ok else 'SOME FAILED'}")
    print("=" * 50)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
