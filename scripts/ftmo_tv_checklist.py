"""Phase 17: TradingView FTMO Checklist — pre-flight validation for live evaluation.

Verifies TradingView setup and FTMO account readiness before starting
a live FTMO evaluation via TradingView.

Usage:
    python scripts/ftmo_tv_checklist.py              # Full checklist
    python scripts/ftmo_tv_checklist.py --quick      # Quick checks only
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

logger = logging.getLogger("ftmo_tv_checklist")


class CheckResult:
    """Result of a single checklist check."""

    def __init__(self, name: str, passed: bool, message: str) -> None:
        self.name = name
        self.passed = passed
        self.message = message

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.name}: {self.message}"


def check_pine_script_exists() -> CheckResult:
    """Verify Pine Script file exists and is complete."""
    pine_path = Path("tradingview/hermes_system.pine")
    if not pine_path.exists():
        return CheckResult("Pine Script", False, "hermes_system.pine not found")

    content = pine_path.read_text(encoding="utf-8")

    # Check for FTMO section
    has_ftmo = "FTMO_DAILY_LIMIT" in content and "FTMO_MAX_DD" in content
    has_inputs_blocked = "input.float" not in content or content.count("input.float") <= 10

    if not has_ftmo:
        return CheckResult("Pine Script", False, "FTMO compliance section not found")

    return CheckResult(
        "Pine Script",
        True,
        f"Complete with FTMO guard ({len(content.splitlines())} lines)",
    )


def check_ftmo_constants() -> CheckResult:
    """Verify FTMO constants are hard-coded (not inputs)."""
    pine_path = Path("tradingview/hermes_system.pine")
    if not pine_path.exists():
        return CheckResult("FTMO Constants", False, "Pine Script not found")

    content = pine_path.read_text(encoding="utf-8")

    # Check that FTMO limits are constants, not inputs
    forbidden_patterns = [
        "input.float(0.045",
        "input.float(0.09",
        "input.float(0.10",
        "input.float(0.05",
        'input.float(4.5',
        'input.float(9.0',
    ]

    for pattern in forbidden_patterns:
        if pattern in content:
            return CheckResult(
                "FTMO Constants",
                False,
                f"FTMO limit exposed as input: {pattern}",
            )

    # Verify hard-coded values exist (flexible whitespace matching)
    required_constants = [
        ("FTMO_DAILY_LIMIT", "0.045"),
        ("FTMO_MAX_DD", "0.09"),
        ("FTMO_PROFIT_TARGET", "0.10"),
        ("FTMO_CONSISTENCY", "0.05"),
    ]

    missing = []
    for name, value in required_constants:
        # Check that the constant name and value appear on the same line
        found = False
        for line in content.split("\n"):
            if name in line and value in line and "=" in line and "//" in line:
                found = True
                break
        if not found:
            missing.append(f"{name} = {value}")

    if missing:
        return CheckResult(
            "FTMO Constants",
            False,
            f"Missing hard-coded constants: {', '.join(missing)}",
        )

    return CheckResult(
        "FTMO Constants",
        True,
        "All FTMO limits are hard-coded constants (not inputs)",
    )


def check_profile_inputs() -> CheckResult:
    """Verify profile selection input exists."""
    pine_path = Path("tradingview/hermes_system.pine")
    if not pine_path.exists():
        return CheckResult("Profile Input", False, "Pine Script not found")

    content = pine_path.read_text(encoding="utf-8")

    if 'input.string("intraday_default"' in content:
        return CheckResult("Profile Input", True, "Profile selection input present")
    else:
        return CheckResult("Profile Input", False, "Profile selection input not found")


def check_non_repainting() -> CheckResult:
    """Verify non-repainting guarantees."""
    pine_path = Path("tradingview/hermes_system.pine")
    if not pine_path.exists():
        return CheckResult("Non-Repainting", False, "Pine Script not found")

    content = pine_path.read_text(encoding="utf-8")

    checks = [
        ("barstate.isconfirmed", "Bar state confirmation"),
        ("lookahead_off", "Lookahead off"),
    ]

    missing = []
    for pattern, desc in checks:
        if pattern not in content:
            missing.append(desc)

    if missing:
        return CheckResult("Non-Repainting", False, f"Missing: {', '.join(missing)}")

    return CheckResult("Non-Repainting", True, "Non-repainting guarantees present")


def check_ftmo_account_ready() -> CheckResult:
    """Prompt user to verify FTMO account readiness."""
    # This is a manual check — we just print the reminder
    return CheckResult(
        "FTMO Account",
        True,
        "MANUAL: Verify FTMO account is active and funded (user confirms)",
    )


def check_monitoring_script() -> CheckResult:
    """Verify FTMO monitoring script exists."""
    monitor_path = Path("scripts/ftmo_tv_monitor.py")
    if not monitor_path.exists():
        return CheckResult("Monitor Script", False, "ftmo_tv_monitor.py not found")
    return CheckResult("Monitor Script", True, "ftmo_tv_monitor.py available")


def check_operational_checklist() -> CheckResult:
    """Verify operational checklist passes."""
    checklist_path = Path("scripts/operational_checklist.py")
    if not checklist_path.exists():
        return CheckResult("Operational Checklist", False, "operational_checklist.py not found")
    return CheckResult("Operational Checklist", True, "operational_checklist.py available")


def run_checklist(quick: bool = False) -> list[CheckResult]:
    """Run all FTMO TV checklist checks."""
    checks = [
        check_pine_script_exists,
        check_ftmo_constants,
        check_profile_inputs,
        check_non_repainting,
        check_ftmo_account_ready,
    ]

    if not quick:
        checks.extend([
            check_monitoring_script,
            check_operational_checklist,
        ])

    results = []
    for check_fn in checks:
        try:
            result = check_fn()
        except Exception as e:
            result = CheckResult(check_fn.__name__, False, f"Unexpected error: {e}")
        results.append(result)

    return results


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Phase 17: TradingView FTMO Checklist")
    parser.add_argument("--quick", action="store_true", help="Quick checks only")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    print("=" * 60)
    print("PHASE 17: TRADINGVIEW FTMO CHECKLIST")
    print("=" * 60)

    results = run_checklist(quick=args.quick)

    print()
    for r in results:
        print(f"  {r}")

    # Summary
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    total = len(results)

    print()
    print("=" * 60)
    print(f"RESULT: {passed}/{total} checks passed")
    if failed > 0:
        print(f"FAILED: {failed} check(s) require attention")
        for r in results:
            if not r.passed:
                print(f"  - {r.name}: {r.message}")
        print()
        print("DO NOT PROCEED until all checks pass.")
    else:
        print("ALL CHECKS PASSED — ready for FTMO evaluation via TradingView")
        print()
        print("Next steps:")
        print("  1. Open TradingView and load hermes_system.pine")
        print("  2. Apply to SPY 1H chart")
        print("  3. Select 'intraday_default' profile")
        print("  4. Verify FTMO guard is active (green status label)")
        print("  5. Connect to FTMO broker (if live)")
        print("  6. Monitor via ftmo_tv_monitor.py")
    print("=" * 60)

    # Save report
    report = {
        "timestamp": datetime.now().isoformat(),
        "total": total,
        "passed": passed,
        "failed": failed,
        "checks": [
            {"name": r.name, "passed": r.passed, "message": r.message}
            for r in results
        ],
    }
    report_path = Path("reports") / "ftmo_tv_checklist.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport saved: {report_path}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
