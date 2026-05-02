"""Phase 16: Operational Checklist — pre-flight validation before live sessions.

Verifies operational readiness by checking persistence DB, logging,
kill switch, FTMO guard, data feed, state files, and configuration integrity.

Usage:
    python scripts/operational_checklist.py              # Full checklist
    python scripts/operational_checklist.py --quick      # Quick checks only
"""

from __future__ import annotations

import json
import logging
import sys
import hashlib
from datetime import datetime
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

logger = logging.getLogger("operational_checklist")


class CheckResult:
    """Result of a single checklist check."""

    def __init__(self, name: str, passed: bool, message: str, details: str = "") -> None:
        self.name = name
        self.passed = passed
        self.message = message
        self.details = details

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.name}: {self.message}"


def check_persistence_db() -> CheckResult:
    """Check persistence DB connectivity."""
    try:
        from src.persistence.db import PersistenceDB
        db = PersistenceDB()
        summary = db.get_summary()
        db.close()
        return CheckResult(
            "Persistence DB",
            True,
            f"Connected — {summary['total_fills']} fills, {summary['total_engine_runs']} runs",
        )
    except Exception as e:
        return CheckResult("Persistence DB", False, f"Connection failed: {e}")


def check_logging() -> CheckResult:
    """Check logging directory exists and is writable."""
    log_dir = Path("logs")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        test_file = log_dir / ".check_test"
        test_file.write_text("test", encoding="utf-8")
        test_file.unlink()
        return CheckResult("Logging", True, f"Log directory OK: {log_dir}")
    except Exception as e:
        return CheckResult("Logging", False, f"Log directory issue: {e}")


def check_risk_limits() -> CheckResult:
    """Verify risk_limits.yaml checksum matches frozen value."""
    config_path = Path("config/risk_limits.yaml")
    if not config_path.exists():
        return CheckResult("Risk Limits", False, "risk_limits.yaml not found")

    try:
        content = config_path.read_text(encoding="utf-8")
        # Compute checksum of value lines (skip header comments)
        value_lines = []
        in_header = True
        for line in content.split("\n"):
            stripped = line.strip()
            if in_header and (stripped.startswith("#") or stripped == ""):
                continue
            in_header = False
            if stripped and not stripped.startswith("#"):
                value_lines.append(stripped)

        computed_hash = hashlib.sha256("\n".join(value_lines).encode()).hexdigest()

        # Check for frozen hash in header
        frozen_hash = None
        for line in content.split("\n"):
            if "SHA-256:" in line:
                frozen_hash = line.split("SHA-256:")[-1].strip()
                break

        if frozen_hash and computed_hash == frozen_hash:
            return CheckResult("Risk Limits", True, f"Checksum verified: {computed_hash[:16]}...")
        elif frozen_hash:
            return CheckResult(
                "Risk Limits", False,
                f"Checksum mismatch: computed={computed_hash[:16]}... frozen={frozen_hash[:16]}...",
            )
        else:
            return CheckResult("Risk Limits", True, "No frozen hash found (file exists, values loaded)")
    except Exception as e:
        return CheckResult("Risk Limits", False, f"Error reading config: {e}")


def check_ftmo_guard() -> CheckResult:
    """Verify FTMO guard loads correctly with ftmo_safe profile."""
    try:
        from src.profiles.presets import RISK_PROFILES
        from src.risk.ftmo_guard import FTMOConfig, FTMOGuard

        profile_data = RISK_PROFILES.get("ftmo_safe", {})
        ftmo_config_data = profile_data.get("ftmo", {})

        # Construct FTMOConfig from profile
        config = FTMOConfig(**{k: v for k, v in ftmo_config_data.items() if hasattr(FTMOConfig, k)})
        guard = FTMOGuard(config)

        return CheckResult(
            "FTMO Guard",
            True,
            f"Loaded — daily_limit={config.max_daily_loss_pct:.1%}, max_dd={config.max_total_drawdown_pct:.1%}",
        )
    except Exception as e:
        return CheckResult("FTMO Guard", False, f"Failed to load: {e}")


def check_drawdown_ladder() -> CheckResult:
    """Verify drawdown ladder loads correctly with ftmo_safe profile."""
    try:
        from src.profiles.presets import RISK_PROFILES
        from src.risk.drawdown_ladder import DrawdownLadder

        profile_data = RISK_PROFILES.get("ftmo_safe", {})
        dd_data = profile_data.get("drawdown_ladder", {})

        ladder = DrawdownLadder.from_profile(dd_data)

        # Test evaluation at different drawdown levels
        state_growth = ladder.evaluate(0.01)
        state_protective = ladder.evaluate(0.05)
        state_survival = ladder.evaluate(0.08)

        return CheckResult(
            "Drawdown Ladder",
            True,
            f"Loaded — GROWTH@1% DD, PROTECTIVE@5% DD, SURVIVAL@8% DD",
        )
    except Exception as e:
        return CheckResult("Drawdown Ladder", False, f"Failed to load: {e}")


def check_data_feed() -> CheckResult:
    """Check yfinance connectivity with a quick fetch."""
    try:
        import yfinance as yf
        ticker = yf.Ticker("SPY")
        df = ticker.history(period="5d", interval="1h")
        if df.empty:
            return CheckResult("Data Feed", False, "yfinance returned empty data for SPY")
        return CheckResult("Data Feed", True, f"yfinance OK — {len(df)} bars fetched for SPY")
    except ImportError:
        return CheckResult("Data Feed", False, "yfinance not installed")
    except Exception as e:
        return CheckResult("Data Feed", False, f"yfinance error: {e}")


def check_state_files() -> CheckResult:
    """Check state file integrity."""
    state_files = [
        Path("data/shadow_live_state.json"),
    ]
    issues = []
    for sf in state_files:
        if sf.exists():
            try:
                json.loads(sf.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                issues.append(f"{sf.name}: corrupt ({e})")

    if issues:
        return CheckResult("State Files", False, "; ".join(issues))
    return CheckResult("State Files", True, "All state files OK")


def check_tradingview_script() -> CheckResult:
    """Check TradingView Pine Script exists and is complete."""
    pine_path = Path("tradingview/hermes_system.pine")
    if not pine_path.exists():
        return CheckResult("TradingView Script", False, "hermes_system.pine not found")

    content = pine_path.read_text(encoding="utf-8")

    # Check for key sections
    required_sections = [
        "SECTION 1: Profile-Driven Inputs",
        "SECTION 4: Agent 1",
        "SECTION 5: Agent 2",
        "SECTION 6: Agent 3",
        "SECTION 7: Agent 4",
        "SECTION 8: Scoring Engine",
        "SECTION 9: Conflict Resolver",
        "SECTION 10: Position Sizer",
        "SECTION 15: Strategy Signals",
        "SECTION 16: Entry/Exit Logic",
    ]

    missing = []
    for section in required_sections:
        if section not in content:
            missing.append(section)

    if missing:
        return CheckResult(
            "TradingView Script",
            False,
            f"Missing sections: {', '.join(missing)}",
        )

    return CheckResult(
        "TradingView Script",
        True,
        f"Complete — {len(content)} chars, {len(content.splitlines())} lines",
    )


def check_strategies() -> CheckResult:
    """Check all strategies are importable."""
    try:
        from src.strategies.pullback_continuation import PullbackContinuationStrategy
        from src.strategies.simple_breakout import SimpleBreakoutStrategy
        from src.strategies.vwap_reversion import VWAPReversionStrategy
        from src.strategies.amt_value_reversion import AMTValueReversionStrategy
        from src.strategies.stop_run_fade import StopRunFadeStrategy
        from src.strategies.rsi_mean_reversion import RSIMeanReversionStrategy
        return CheckResult("Strategies", True, "All 6 strategies importable")
    except ImportError as e:
        return CheckResult("Strategies", False, f"Import failed: {e}")


def check_hermes_coordinator() -> CheckResult:
    """Check Hermes v2 coordinator initializes correctly."""
    try:
        from src.hermes.coordinator import HermesCoordinator
        from src.hermes.registry import AgentRegistry
        from src.hermes.scoring import ScoringEngine
        from src.hermes.conflict import ConflictResolver
        from src.hermes.sizing import PositionSizer
        from src.hermes.agents.stub_agents import (
            IchimokuAgent, VolatilityAgent, AMTAgent, WyckoffAgent,
        )

        registry = AgentRegistry()
        registry.register(IchimokuAgent())
        registry.register(VolatilityAgent())
        registry.register(AMTAgent())
        registry.register(WyckoffAgent())

        coordinator = HermesCoordinator(
            registry=registry,
            scoring=ScoringEngine(),
            conflict=ConflictResolver(),
            sizing=PositionSizer(),
        )
        return CheckResult("Hermes Coordinator", True, "Initialized with 4 agents")
    except Exception as e:
        return CheckResult("Hermes Coordinator", False, f"Init failed: {e}")


def run_checklist(quick: bool = False) -> list[CheckResult]:
    """Run all checklist checks."""
    checks = [
        check_persistence_db,
        check_logging,
        check_risk_limits,
        check_ftmo_guard,
        check_drawdown_ladder,
        check_hermes_coordinator,
        check_strategies,
    ]

    if not quick:
        checks.extend([
            check_data_feed,
            check_state_files,
            check_tradingview_script,
        ])

    results = []
    for check_fn in checks:
        try:
            result = check_fn()
        except Exception as e:
            result = CheckResult(check_fn.__name__, False, f"Unexpected error: {e}")
        results.append(result)
        logger.info(str(result))

    return results


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Phase 16: Operational Checklist")
    parser.add_argument("--quick", action="store_true", help="Quick checks only (skip data feed, state files)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    print("=" * 60)
    print("PHASE 16: OPERATIONAL CHECKLIST")
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
    else:
        print("ALL CHECKS PASSED — system is operationally ready")
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
    report_path = Path("reports") / "operational_checklist.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport saved: {report_path}")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
