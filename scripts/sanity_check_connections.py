"""Connection Sanity Check - Alpaca + Hermes + Health Pipeline.

Comprehensive operator diagnostic that validates all connections and
configuration state independently. Reports pass/fail for each component,
identifies configuration gaps, and suggests fixes.

Checks:
1. Alpaca API Connectivity
2. Alpaca Credentials Validity
3. Hermes Agentic Configuration
4. HealthSupervisor Integration
5. Event Log Bridge
6. Streamlit Dashboard State
7. Policy & Filesystem

Usage:
    python scripts/sanity_check_connections.py
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

from dotenv import load_dotenv
load_dotenv(Path(_root) / ".env")


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """Result of a single sanity check."""
    name: str
    passed: bool
    message: str
    status: str  # PASS, FAIL, WARN, PENDING, PARTIAL

    def __str__(self) -> str:
        icon = {"PASS": "[PASS]", "FAIL": "[FAIL]", "WARN": "[WARN]", "PENDING": "[PEND]", "PARTIAL": "[PART]"}
        return f"  {icon.get(self.status, '[????]')}  {self.name:<35} {self.message}"


# ---------------------------------------------------------------------------
# Check 1: Alpaca API Connectivity
# ---------------------------------------------------------------------------

def check_alpaca_api() -> CheckResult:
    """Test Alpaca API connectivity via AlpacaBroker.get_portfolio_state()."""
    try:
        from src.execution.alpaca_broker import AlpacaBroker
        broker = AlpacaBroker()
        state = broker.get_portfolio_state()

        if state is None:
            return CheckResult("Alpaca API Connection", False, "get_portfolio_state() returned None", "FAIL")

        equity = state.total_value
        num_positions = len(state.positions)
        cash = state.cash

        detail = f"equity: ${equity:,.2f}, cash: ${cash:,.2f}, positions: {num_positions}"
        return CheckResult("Alpaca API Connection", True, detail, "PASS")
    except ValueError as e:
        # Missing env vars
        return CheckResult("Alpaca API Connection", False, f"Missing credentials: {e}", "FAIL")
    except Exception as e:
        return CheckResult("Alpaca API Connection", False, f"API error: {e}", "FAIL")


# ---------------------------------------------------------------------------
# Check 2: Alpaca Credentials Validity
# ---------------------------------------------------------------------------

def check_alpaca_credentials() -> CheckResult:
    """Validate Alpaca credentials by reading env vars directly."""
    api_key = os.getenv("ALPACA_API_KEY", "")
    secret_key = os.getenv("ALPACA_SECRET_KEY", "")
    base_url = os.getenv("ALPACA_BASE_URL", "")

    issues = []
    if not api_key:
        issues.append("ALPACA_API_KEY missing")
    elif not api_key.startswith("PK"):
        issues.append(f"ALPACA_API_KEY prefix '{api_key[:2]}' (expected 'PK' for paper)")

    if not secret_key:
        issues.append("ALPACA_SECRET_KEY missing")

    if not base_url:
        issues.append("ALPACA_BASE_URL not set (AlpacaBroker uses paper=True auto-detection)")
    elif "/v2" not in base_url:
        issues.append(f"ALPACA_BASE_URL missing /v2 suffix: {base_url}")

    if issues:
        return CheckResult("Alpaca Credentials", False, "; ".join(issues), "WARN")

    # Determine mode from key prefix
    mode = "paper" if api_key.startswith("PK") else "live"
    detail = f"{mode} mode, key prefix: {api_key[:4]}..., base_url: {base_url}"
    return CheckResult("Alpaca Credentials", True, detail, "PASS")


# ---------------------------------------------------------------------------
# Check 3: Hermes Agentic Configuration
# ---------------------------------------------------------------------------

def check_hermes_config() -> CheckResult:
    """Check Hermes Agentic LLM configuration."""
    hermes_dir = Path("external/hermes-agentic")
    hermes_env = hermes_dir / ".env"
    hermes_env_example = hermes_dir / ".env.example"
    runs_dir = Path("data/hermes_runs")

    issues = []
    info = []

    # Check submodule exists
    if hermes_dir.exists():
        info.append("submodule exists")
    else:
        issues.append("submodule missing")

    # Check .env in submodule
    if hermes_env.exists():
        info.append("submodule .env present")
    else:
        issues.append("no external/hermes-agentic/.env (only .env.example)")

    # Check LLM API keys in parent .env
    has_openrouter = bool(os.getenv("HERMES_OPENROUTER_API_KEY"))
    has_google = bool(os.getenv("GOOGLE_API_KEY"))
    has_xiaomi = bool(os.getenv("XIAOMI_API_KEY"))

    if has_openrouter:
        info.append("HERMES_OPENROUTER_API_KEY configured")
    if has_google:
        info.append("GOOGLE_API_KEY configured")
    if has_xiaomi:
        info.append("XIAOMI_API_KEY configured")

    if not (has_openrouter or has_google or has_xiaomi):
        issues.append("no LLM API key in .env (HERMES_OPENROUTER_API_KEY / GOOGLE_API_KEY / XIAOMI_API_KEY)")

    # Check runs directory
    if runs_dir.exists():
        run_files = list(runs_dir.glob("*.json"))
        if run_files:
            latest = max(run_files, key=lambda f: f.stat().st_mtime)
            info.append(f"{len(run_files)} run file(s), latest: {latest.name}")
        else:
            info.append("data/hermes_runs/ empty (no runs yet)")
    else:
        issues.append("data/hermes_runs/ missing")

    if issues:
        status = "FAIL"
        return CheckResult("Hermes Agentic Config", False, "; ".join(issues), status)

    return CheckResult("Hermes Agentic Config", True, "; ".join(info), "PASS")


# ---------------------------------------------------------------------------
# Check 4: HealthSupervisor Integration
# ---------------------------------------------------------------------------

def check_health_supervisor() -> CheckResult:
    """Create HealthSupervisor with EventBus and run check_all()."""
    try:
        from src.core.events import EventBus
        from src.monitoring.health_supervisor import HealthSupervisor
        from src.monitoring.event_log import EventLogWriter

        bus = EventBus()
        writer = EventLogWriter()

        # Subscribe writer to all health events
        from src.core.events import HealthEvents
        for attr in dir(HealthEvents):
            if not attr.startswith("_"):
                event_name = getattr(HealthEvents, attr)
                bus.subscribe(event_name, writer)

        # Try to create broker
        broker = None
        broker_status = "not injected"
        try:
            from src.execution.alpaca_broker import AlpacaBroker
            broker = AlpacaBroker()
            broker_status = "AlpacaBroker created"
        except Exception as e:
            broker_status = f"AlpacaBroker failed: {e}"

        # Create supervisor with all checks
        supervisor = HealthSupervisor(
            event_bus=bus,
            broker=broker,
            enabled_checks={"alpaca", "hermes_agentic", "file_system", "policy"},
            max_retries=2,
        )

        results = supervisor.check_all()

        # Summarize results
        summary = []
        all_healthy = True
        for r in results:
            icon = "[OK]" if r.healthy else "[!!]"
            summary.append(f"{icon} {r.component}: {r.reason}")
            if not r.healthy:
                all_healthy = False

        detail = f"broker={broker_status}; checks={len(results)}: " + "; ".join(summary)
        status = "PASS" if all_healthy else "PARTIAL"
        return CheckResult("HealthSupervisor Pipeline", all_healthy, detail, status)

    except Exception as e:
        return CheckResult("HealthSupervisor Pipeline", False, f"Init failed: {e}", "FAIL")


# ---------------------------------------------------------------------------
# Check 5: Event Log Bridge
# ---------------------------------------------------------------------------

def check_event_log_bridge() -> CheckResult:
    """Check if data/health_events.jsonl exists and has events."""
    log_path = Path("data/health_events.jsonl")

    if not log_path.exists():
        return CheckResult(
            "Event Log Bridge",
            True,
            "No data/health_events.jsonl - no engine run yet (expected)",
            "PENDING",
        )

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        if not lines:
            return CheckResult("Event Log Bridge", True, "JSONL file empty", "PENDING")

        # Parse events
        events = []
        for line in lines:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        event_types = {}
        for ev in events:
            t = ev.get("event", "unknown")
            event_types[t] = event_types.get(t, 0) + 1

        breakdown = ", ".join(f"{k}: {v}" for k, v in sorted(event_types.items()))
        return CheckResult(
            "Event Log Bridge",
            True,
            f"{len(events)} events - {breakdown}",
            "PASS",
        )
    except Exception as e:
        return CheckResult("Event Log Bridge", False, f"Read error: {e}", "WARN")


# ---------------------------------------------------------------------------
# Check 6: Streamlit Dashboard State
# ---------------------------------------------------------------------------

def check_dashboard_state() -> CheckResult:
    """Verify dashboard/app.py imports work and read_new_events() functions."""
    app_path = Path("dashboard/app.py")

    if not app_path.exists():
        return CheckResult("Streamlit Dashboard", False, "dashboard/app.py not found", "FAIL")

    try:
        # Test that the critical imports and functions work
        from monitoring.event_log import read_new_events, DEFAULT_LOG_PATH

        # Test read_new_events with nonexistent file (should return empty)
        events, offset, ts = read_new_events(
            log_path="data/health_events_nonexistent.jsonl",
            last_offset=0,
            last_timestamp="",
        )
        if events != []:
            return CheckResult(
                "Streamlit Dashboard",
                False,
                "read_new_events() returned non-empty for nonexistent file",
                "WARN",
            )

        # Test with actual log if it exists
        actual_events, actual_offset, actual_ts = read_new_events(
            log_path=DEFAULT_LOG_PATH,
            last_offset=0,
            last_timestamp="",
        )

        detail = (
            f"app.py exists ({app_path.stat().st_size} bytes), "
            f"read_new_events OK, "
            f"actual log: {len(actual_events)} events"
        )
        return CheckResult("Streamlit Dashboard", True, detail, "PASS")

    except ImportError as e:
        return CheckResult("Streamlit Dashboard", False, f"Import failed: {e}", "FAIL")
    except Exception as e:
        return CheckResult("Streamlit Dashboard", False, f"Error: {e}", "WARN")


# ---------------------------------------------------------------------------
# Check 7: Policy & Filesystem
# ---------------------------------------------------------------------------

def check_policy_filesystem() -> CheckResult:
    """Check data/universe_current.json and data/hermes_runs/ writability."""
    issues = []
    info = []

    # Policy check
    policy_path = Path("data/universe_current.json")
    if policy_path.exists():
        try:
            with open(policy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            version_file = data.get("current_version_file", "unknown")
            info.append(f"universe_current.json -> {version_file}")
        except Exception as e:
            issues.append(f"universe_current.json corrupt: {e}")
    else:
        issues.append("universe_current.json missing")

    # Filesystem writability check
    runs_dir = Path("data/hermes_runs")
    try:
        runs_dir.mkdir(parents=True, exist_ok=True)
        test_file = runs_dir / ".sanity_check"
        test_file.write_text("test", encoding="utf-8")
        test_file.unlink()
        info.append("data/hermes_runs/ writable")
    except Exception as e:
        issues.append(f"Filesystem not writable: {e}")

    # Check data directories exist
    data_dirs = [
        "data/hermes_runs",
        "data/hermes_proposals",
        "data/hermes_alerts",
        "data/historical",
    ]
    missing = [d for d in data_dirs if not Path(d).exists()]
    if missing:
        issues.append(f"Missing dirs: {', '.join(missing)}")
    else:
        info.append("All data dirs present")

    if issues:
        return CheckResult("Policy & Filesystem", False, "; ".join(issues), "FAIL")

    return CheckResult("Policy & Filesystem", True, "; ".join(info), "PASS")


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(results: list[CheckResult]) -> None:
    """Print the formatted sanity check report."""
    print()
    print("=" * 60)
    print("  CONNECTION SANITY CHECK")
    print("=" * 60)
    print()

    for i, r in enumerate(results, 1):
        print(f"  [{i}] {r}")

    # Collect issues
    issues = []
    actions = []
    for r in results:
        if r.status == "FAIL":
            issues.append(r.message)
        elif r.status == "WARN":
            issues.append(f"[WARN] {r.name}: {r.message}")

    # Hermes-specific issues
    hermes_result = next((r for r in results if r.name == "Hermes Agentic Config"), None)
    if hermes_result and hermes_result.status == "FAIL":
        actions.append("Configure at least one LLM provider key in .env:")
        actions.append("  -> Set HERMES_OPENROUTER_API_KEY in .env")
        actions.append("  -> Or set GOOGLE_API_KEY / XIAOMI_API_KEY")
        actions.append("  -> Or create external/hermes-agentic/.env with API keys")

    # Event log issues
    event_result = next((r for r in results if r.name == "Event Log Bridge"), None)
    if event_result and event_result.status == "PENDING":
        actions.append("No engine has been run with the event bridge yet:")
        actions.append("  -> Run: python scripts/smoke_test_health.py")
        actions.append("  -> Run: python scripts/run_alpaca_health_test.py")

    # Print issues
    if issues:
        print()
        print("-" * 60)
        print("  ISSUES FOUND")
        print("-" * 60)
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")

    # Print recommended actions
    if actions:
        print()
        print("-" * 60)
        print("  RECOMMENDED ACTIONS")
        print("-" * 60)
        for action in actions:
            print(f"  {action}")

    # Overall verdict
    failed = sum(1 for r in results if r.status == "FAIL")
    warned = sum(1 for r in results if r.status == "WARN")
    passed = sum(1 for r in results if r.status == "PASS")
    pending = sum(1 for r in results if r.status in ("PENDING", "PARTIAL"))
    total = len(results)

    print()
    print("=" * 60)
    if failed == 0 and warned == 0:
        print(f"  VERDICT: ALL CLEAR - {passed}/{total} checks passed")
    elif failed == 0:
        print(f"  VERDICT: MOSTLY OK - {passed} passed, {warned} warnings, {pending} pending")
    else:
        print(f"  VERDICT: ISSUES DETECTED - {passed} passed, {failed} failed, {warned} warnings")
    print("=" * 60)
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """Run all sanity checks and print report."""
    results: list[CheckResult] = []

    checks = [
        ("[1] Alpaca API Connectivity", check_alpaca_api),
        ("[2] Alpaca Credentials", check_alpaca_credentials),
        ("[3] Hermes Agentic Config", check_hermes_config),
        ("[4] HealthSupervisor Pipeline", check_health_supervisor),
        ("[5] Event Log Bridge", check_event_log_bridge),
        ("[6] Streamlit Dashboard", check_dashboard_state),
        ("[7] Policy & Filesystem", check_policy_filesystem),
    ]

    for label, check_fn in checks:
        try:
            result = check_fn()
        except Exception as e:
            result = CheckResult(
                label.split("] ", 1)[-1],
                False,
                f"Unexpected error: {e}\n{traceback.format_exc()}",
                "FAIL",
            )
        results.append(result)

    generate_report(results)

    # Exit code: 0 if no failures
    failed = sum(1 for r in results if r.status == "FAIL")
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
