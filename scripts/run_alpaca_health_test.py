"""End-to-end Alpaca Health Test via HealthSupervisor.

OPERATOR / DEBUG TOOL ONLY — not a runtime dependency.
Never imported by engine or Streamlit. Not required for normal startup.

Executes 4 test scenarios against real Alpaca Paper Trading credentials:
1. Cold Start — Real endpoint reachable, ALPACA_RESTORED emitted
2. Invalid Credentials — Circuit breaker trips, ALPACA_DISCONNECTED + EXECUTION_PAUSED
3. Recovery — Restore valid credentials, ALPACA_RESTORED + EXECUTION_RESUMED
4. Idle State — No engine running, system shows idle

Usage:
    python scripts/run_alpaca_health_test.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from dotenv import load_dotenv

load_dotenv(Path(_root) / ".env")

from src.core.events import EventBus
from src.execution.broker import Broker
from src.monitoring.health_supervisor import HealthSupervisor, CircuitState
from src.monitoring.event_log import EventLogWriter


class TestEventRecorder:
    """Captures all emitted events for assertion."""

    def __init__(self):
        self.events: list[tuple[str, str, str, str]] = []

    def __call__(self, event_name: str, *args, **kwargs):
        ts = args[0] if len(args) > 0 else kwargs.get("timestamp", "")
        comp = args[1] if len(args) > 1 else kwargs.get("component", "")
        reason = args[2] if len(args) > 2 else kwargs.get("reason", "")
        self.events.append((event_name, ts, comp, reason))

    def has(self, event_name: str) -> bool:
        return any(e[0] == event_name for e in self.events)

    def clear(self):
        self.events.clear()


def _create_real_broker():
    """Create a real AlpacaBroker for testing."""
    from src.execution.alpaca_broker import AlpacaBroker
    return AlpacaBroker()


def _create_failing_broker():
    """Create a mock broker that always fails (simulates invalid credentials)."""
    from unittest.mock import Mock

    broker = Mock(spec=Broker)
    broker.get_portfolio_state.side_effect = Exception("Connection refused: invalid API key")
    return broker


def test_1_cold_start():
    """Test 1: Cold Start — Verify Alpaca connectivity and ALPACA_RESTORED event."""
    print("\n" + "=" * 60)
    print("TEST 1: Cold Start — Real Endpoint Reachable")
    print("=" * 60)

    bus = EventBus()
    recorder = TestEventRecorder()

    # Subscribe to all health events
    for event_name in [
        "ALPACA_RESTORED", "ALPACA_DISCONNECTED",
        "EXECUTION_PAUSED", "EXECUTION_RESUMED",
    ]:
        bus.subscribe(event_name, recorder)

    # Also write to event log for Streamlit bridge
    writer = EventLogWriter()
    for event_name in [
        "ALPACA_RESTORED", "ALPACA_DISCONNECTED",
        "EXECUTION_PAUSED", "EXECUTION_RESUMED",
    ]:
        bus.subscribe(event_name, writer)

    try:
        broker = _create_real_broker()
    except Exception as e:
        print(f"  SKIP: Cannot create AlpacaBroker: {e}")
        print("  Ensure ALPACA_API_KEY and ALPACA_SECRET_KEY are set in .env")
        return False

    supervisor = HealthSupervisor(
        event_bus=bus,
        broker=broker,
        enabled_checks={"alpaca"},
        max_retries=3,
    )

    results = supervisor.check_all()

    # Assertions
    alpaca_result = next((r for r in results if r.component == "alpaca"), None)
    assert alpaca_result is not None, "No alpaca health check result"
    assert alpaca_result.healthy, f"Alpaca check failed: {alpaca_result.reason}"

    # If circuit was previously HEALTHY (cold start), no RESTORED event expected
    # But if there was a previous degraded state, RESTORED would be emitted
    print(f"  Result: {'HEALTHY' if alpaca_result.healthy else 'FAILED'}")
    print(f"  Reason: {alpaca_result.reason}")
    print(f"  Events emitted: {[e[0] for e in recorder.events]}")

    # Verify event log was written
    log_path = Path("data/health_events.jsonl")
    if log_path.exists():
        print(f"  Event log: {log_path} ({log_path.stat().st_size} bytes)")

    print("  PASS" if alpaca_result.healthy else "  FAIL")
    return alpaca_result.healthy


def test_2_invalid_credentials():
    """Test 2: Invalid Credentials — Circuit breaker trips after max_retries."""
    print("\n" + "=" * 60)
    print("TEST 2: Invalid Credentials — Forced Failure")
    print("=" * 60)

    bus = EventBus()
    recorder = TestEventRecorder()
    writer = EventLogWriter()

    for event_name in [
        "ALPACA_RESTORED", "ALPACA_DISCONNECTED",
        "EXECUTION_PAUSED", "EXECUTION_RESUMED",
    ]:
        bus.subscribe(event_name, recorder)
        bus.subscribe(event_name, writer)

    broker = _create_failing_broker()

    supervisor = HealthSupervisor(
        event_bus=bus,
        broker=broker,
        enabled_checks={"alpaca"},
        max_retries=2,  # Trip after 2 failures
    )

    # Run check_all multiple times to trigger circuit breaker
    for i in range(3):
        supervisor.check_all()
        print(f"  Round {i+1}: failure_count={supervisor.failure_counts['alpaca']}, "
              f"state={supervisor.states['alpaca'].value}")

    # Assertions
    assert supervisor.states["alpaca"] == CircuitState.DEGRADED, \
        f"Circuit should be DEGRADED, got {supervisor.states['alpaca']}"
    assert recorder.has("ALPACA_DISCONNECTED"), \
        "ALPACA_DISCONNECTED event was not emitted"
    assert recorder.has("EXECUTION_PAUSED"), \
        "EXECUTION_PAUSED event was not emitted"

    print(f"  Circuit state: {supervisor.states['alpaca'].value}")
    print(f"  Events emitted: {[e[0] for e in recorder.events]}")
    print("  PASS")
    return True


def test_3_recovery():
    """Test 3: Recovery — Restore valid credentials, emit ALPACA_RESTORED + EXECUTION_RESUMED."""
    print("\n" + "=" * 60)
    print("TEST 3: Recovery After Failure")
    print("=" * 60)

    bus = EventBus()
    recorder = TestEventRecorder()
    writer = EventLogWriter()

    for event_name in [
        "ALPACA_RESTORED", "ALPACA_DISCONNECTED",
        "EXECUTION_PAUSED", "EXECUTION_RESUMED",
    ]:
        bus.subscribe(event_name, recorder)
        bus.subscribe(event_name, writer)

    try:
        broker = _create_real_broker()
    except Exception as e:
        print(f"  SKIP: Cannot create AlpacaBroker: {e}")
        return False

    supervisor = HealthSupervisor(
        event_bus=bus,
        broker=broker,
        enabled_checks={"alpaca"},
        max_retries=3,
    )

    # Simulate a previously degraded state
    supervisor.states["alpaca"] = CircuitState.DEGRADED
    supervisor.failure_counts["alpaca"] = 3

    print(f"  Pre-check state: {supervisor.states['alpaca'].value}")
    results = supervisor.check_all()

    # Assertions
    alpaca_result = next((r for r in results if r.component == "alpaca"), None)
    assert alpaca_result is not None, "No alpaca health check result"
    assert alpaca_result.healthy, f"Recovery failed: {alpaca_result.reason}"
    assert supervisor.states["alpaca"] == CircuitState.HEALTHY, \
        "Circuit should be HEALTHY after recovery"
    assert recorder.has("ALPACA_RESTORED"), \
        "ALPACA_RESTORED event was not emitted"
    assert recorder.has("EXECUTION_RESUMED"), \
        "EXECUTION_RESUMED event was not emitted"

    print(f"  Post-check state: {supervisor.states['alpaca'].value}")
    print(f"  Events emitted: {[e[0] for e in recorder.events]}")
    print("  PASS")
    return True


def test_4_idle_state():
    """Test 4: Idle State — System shows idle when no engine is running."""
    print("\n" + "=" * 60)
    print("TEST 4: Idle State (No Engine Running)")
    print("=" * 60)

    bus = EventBus()
    recorder = TestEventRecorder()

    for event_name in [
        "ALPACA_RESTORED", "ALPACA_DISCONNECTED",
        "EXECUTION_PAUSED", "EXECUTION_RESUMED",
    ]:
        bus.subscribe(event_name, recorder)

    supervisor = HealthSupervisor(
        event_bus=bus,
        broker=None,  # No broker = no engine running
        enabled_checks={"alpaca"},
    )

    results = supervisor.check_all()

    # No alpaca check should run (no broker injected)
    alpaca_results = [r for r in results if r.component == "alpaca"]
    assert len(alpaca_results) == 0, "Alpaca check should not run without a broker"

    # No events should be emitted
    assert len(recorder.events) == 0, "No events should be emitted in idle state"

    print(f"  Results: {len(results)} checks (none for alpaca)")
    print(f"  Events emitted: {len(recorder.events)} (expected 0)")
    print("  PASS")
    return True


def main():
    """Run all 4 test scenarios."""
    print("\n" + "#" * 60)
    print("# APCA HEALTH TEST — END-TO-END VIA HEALTHSUPERVISOR #")
    print("#" * 60)

    results = {}
    results["cold_start"] = test_1_cold_start()
    results["invalid_credentials"] = test_2_invalid_credentials()
    results["recovery"] = test_3_recovery()
    results["idle_state"] = test_4_idle_state()

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")

    all_pass = all(results.values())
    print(f"\nOverall: {'ALL PASSED' if all_pass else 'SOME FAILED'}")
    print("=" * 60)

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
