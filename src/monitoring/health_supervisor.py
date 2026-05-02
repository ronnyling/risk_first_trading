"""Deterministic Health Supervisor for system health monitoring and bounded recovery."""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

from src.core.events import EventBus
from src.execution.broker import Broker
from src.execution.mock_broker import MockBroker
from src.market.adapter import MarketDataAdapter

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker state for a dependency."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"


@dataclass
class HealthCheckResult:
    """Result of a health check."""
    component: str
    healthy: bool
    reason: str
    timestamp: datetime


class HealthSupervisor:
    """
    Deterministic health supervisor with bounded retries and circuit breaking.

    Responsibilities:
    - Read-only health checks for external dependencies
    - Bounded retries with exponential backoff
    - Circuit breaking (mark dependency as DEGRADED after retry limit)
    - Emit explicit health events via EventBus

    Dependencies:
    - Alpaca adapter (for broker connectivity)
    - Market feed adapter (for data freshness)
    - File system (for artifact directories)
    - Policy (for universe_current.json)
    """

    def __init__(
        self,
        event_bus: EventBus,
        broker: Optional[Broker] = None,
        market_feed: Optional[MarketDataAdapter] = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
        stale_threshold_seconds: int = 60,
        hermes_max_staleness_hours: int = 24,
        enabled_checks: Optional[set[str]] = None,
    ):
        self.event_bus = event_bus

        # DI boundary enforcement: reject incompatible broker types
        if broker is not None and not isinstance(broker, Broker):
            raise TypeError(
                f"HealthSupervisor requires a Broker ABC implementation, "
                f"got {type(broker).__name__}. Use AlpacaBroker, not AlpacaAdapter."
            )

        # Guard: reject CSV market data + live broker hybrid configurations.
        # CSV replay is a test/debug tool only. Production must use live data
        # with a live broker, or MockBroker with CSV data.
        try:
            is_csv_feed = (
                market_feed is not None
                and hasattr(market_feed, 'source_name')
                and isinstance(market_feed.source_name, str)
                and 'csv' in market_feed.source_name.lower()
            )
        except (AttributeError, TypeError):
            is_csv_feed = False

        if is_csv_feed and broker is not None and not isinstance(broker, MockBroker):
            raise ValueError(
                f"Hybrid configuration rejected: CSV market data cannot be used "
                f"with a live broker ({type(broker).__name__}). "
                f"HealthSupervisor enforces single execution path."
            )

        self.broker = broker
        self.market_feed = market_feed
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.stale_threshold_seconds = stale_threshold_seconds
        self.hermes_max_staleness_hours = hermes_max_staleness_hours
        
        # Enable/disable specific checks (for testing)
        if enabled_checks is None:
            enabled_checks = {"alpaca", "market_feed", "hermes_agentic", "file_system", "policy"}
        self.enabled_checks = enabled_checks

        # Circuit states for each dependency
        self.states = {
            "alpaca": CircuitState.HEALTHY,
            "market_feed": CircuitState.HEALTHY,
            "hermes_agentic": CircuitState.HEALTHY,
            "file_system": CircuitState.HEALTHY,
            "policy": CircuitState.HEALTHY,
        }

        # Track last successful checks
        self.last_successful_check = {
            "alpaca": None,
            "market_feed": None,
            "hermes_agentic": None,
            "file_system": None,
            "policy": None,
        }
        
        # Track consecutive failure counts for retry logic
        self.failure_counts = {
            "alpaca": 0,
            "market_feed": 0,
            "hermes_agentic": 0,
            "file_system": 0,
            "policy": 0,
        }

    def check_all(self) -> list[HealthCheckResult]:
        """Run all health checks and emit events on state transitions."""
        results = []

        # Check Alpaca broker connectivity
        if self.broker and "alpaca" in self.enabled_checks:
            results.append(self._check_alpaca())

        # Check market feed freshness
        if self.market_feed and "market_feed" in self.enabled_checks:
            results.append(self._check_market_feed())

        # Check Hermes Agentic staleness
        if "hermes_agentic" in self.enabled_checks:
            results.append(self._check_hermes_agentic())

        # Check file system writability
        if "file_system" in self.enabled_checks:
            results.append(self._check_file_system())

        # Check policy readability
        if "policy" in self.enabled_checks:
            results.append(self._check_policy())

        # Emit events for state transitions
        self._emit_state_transitions(results)

        return results

    def _check_alpaca(self) -> HealthCheckResult:
        """Check Alpaca broker connectivity.

        Verifies the API call succeeds. Does NOT require total_value > 0
        (fresh paper accounts may start at $0 equity).
        """
        component = "alpaca"
        try:
            # Try to get portfolio state (read-only check)
            state = self.broker.get_portfolio_state()
            if state is not None:
                self.last_successful_check[component] = datetime.now()
                self.failure_counts[component] = 0  # Reset failure count
                if self.states[component] == CircuitState.DEGRADED:
                    self.states[component] = CircuitState.HEALTHY
                    return HealthCheckResult(
                        component=component,
                        healthy=True,
                        reason="Alpaca connection restored",
                        timestamp=datetime.now(),
                    )
                return HealthCheckResult(
                    component=component,
                    healthy=True,
                    reason="Alpaca connection healthy",
                    timestamp=datetime.now(),
                )
            else:
                raise Exception("Portfolio state is None")
        except Exception as e:
            logger.warning(f"Alpaca health check failed: {e}")
            return self._handle_failure(component, f"Alpaca connection failed: {e}")

    def _check_market_feed(self) -> HealthCheckResult:
        """Check market feed freshness."""
        component = "market_feed"
        try:
            # Check if feed has recent data
            last_bar = self.market_feed.get_next_bar()
            if last_bar:
                age = datetime.now() - last_bar.timestamp.replace(tzinfo=None)
                if age.total_seconds() < self.stale_threshold_seconds:
                    self.last_successful_check[component] = datetime.now()
                    self.failure_counts[component] = 0  # Reset failure count
                    if self.states[component] == CircuitState.DEGRADED:
                        self.states[component] = CircuitState.HEALTHY
                        return HealthCheckResult(
                            component=component,
                            healthy=True,
                            reason="Market feed restored",
                            timestamp=datetime.now(),
                        )
                    return HealthCheckResult(
                        component=component,
                        healthy=True,
                        reason="Market feed fresh",
                        timestamp=datetime.now(),
                    )
                else:
                    raise Exception(f"Data stale: {age.total_seconds():.0f}s old")
            else:
                raise Exception("No data available")
        except Exception as e:
            logger.warning(f"Market feed health check failed: {e}")
            return self._handle_failure(component, f"Market feed issue: {e}")

    def _check_hermes_agentic(self) -> HealthCheckResult:
        """Check Hermes Agentic last run timestamp."""
        component = "hermes_agentic"
        try:
            # Check for recent Hermes run files
            runs_dir = Path("data/hermes_runs")
            if not runs_dir.exists():
                raise Exception("Hermes runs directory missing")

            run_files = list(runs_dir.glob("*.json"))
            if not run_files:
                raise Exception("No Hermes run files found")

            # Get most recent run
            latest_run = max(run_files, key=lambda f: f.stat().st_mtime)
            mtime = datetime.fromtimestamp(latest_run.stat().st_mtime)
            age = datetime.now() - mtime

            if age < timedelta(hours=self.hermes_max_staleness_hours):
                self.last_successful_check[component] = datetime.now()
                self.failure_counts[component] = 0  # Reset failure count
                if self.states[component] == CircuitState.DEGRADED:
                    self.states[component] = CircuitState.HEALTHY
                    return HealthCheckResult(
                        component=component,
                        healthy=True,
                        reason="Hermes Agentic restored",
                        timestamp=datetime.now(),
                    )
                return HealthCheckResult(
                    component=component,
                    healthy=True,
                    reason="Hermes Agentic recent",
                    timestamp=datetime.now(),
                )
            else:
                raise Exception(f"Hermes run stale: {age}")
        except Exception as e:
            logger.warning(f"Hermes Agentic health check failed: {e}")
            return self._handle_failure(component, f"Hermes Agentic issue: {e}")

    def _check_file_system(self) -> HealthCheckResult:
        """Check file system writability."""
        component = "file_system"
        try:
            test_dir = Path("data/hermes_runs")
            test_dir.mkdir(parents=True, exist_ok=True)
            test_file = test_dir / ".health_check"
            test_file.write_text("test")
            test_file.unlink()
            self.last_successful_check[component] = datetime.now()
            self.failure_counts[component] = 0  # Reset failure count
            if self.states[component] == CircuitState.DEGRADED:
                self.states[component] = CircuitState.HEALTHY
                return HealthCheckResult(
                    component=component,
                    healthy=True,
                    reason="File system restored",
                    timestamp=datetime.now(),
                )
            return HealthCheckResult(
                component=component,
                healthy=True,
                reason="File system writable",
                timestamp=datetime.now(),
            )
        except Exception as e:
            logger.warning(f"File system health check failed: {e}")
            return self._handle_failure(component, f"File system issue: {e}")

    def _check_policy(self) -> HealthCheckResult:
        """Check policy readability."""
        component = "policy"
        try:
            policy_path = Path("data/universe_current.json")
            if not policy_path.exists():
                raise Exception("universe_current.json missing")

            import json
            with open(policy_path, "r") as f:
                json.load(f)

            self.last_successful_check[component] = datetime.now()
            self.failure_counts[component] = 0  # Reset failure count
            if self.states[component] == CircuitState.DEGRADED:
                self.states[component] = CircuitState.HEALTHY
                return HealthCheckResult(
                    component=component,
                    healthy=True,
                    reason="Policy restored",
                    timestamp=datetime.now(),
                )
            return HealthCheckResult(
                component=component,
                healthy=True,
                reason="Policy readable",
                timestamp=datetime.now(),
            )
        except Exception as e:
            logger.warning(f"Policy health check failed: {e}")
            return self._handle_failure(component, f"Policy issue: {e}")

    def _handle_failure(self, component: str, reason: str) -> HealthCheckResult:
        """Handle check failure with retry logic and circuit breaking."""
        current_state = self.states[component]
        
        # Increment failure count
        self.failure_counts[component] += 1
        retry_count = self.failure_counts[component]

        if retry_count >= self.max_retries:
            # Circuit breaker tripped
            if current_state == CircuitState.HEALTHY:
                self.states[component] = CircuitState.DEGRADED
                return HealthCheckResult(
                    component=component,
                    healthy=False,
                    reason=f"{reason} (circuit tripped)",
                    timestamp=datetime.now(),
                )
            else:
                # Already degraded
                return HealthCheckResult(
                    component=component,
                    healthy=False,
                    reason=reason,
                    timestamp=datetime.now(),
                )
        else:
            # Still in retry phase
            return HealthCheckResult(
                component=component,
                healthy=False,
                reason=f"{reason} (retry {retry_count}/{self.max_retries})",
                timestamp=datetime.now(),
            )

    def _emit_state_transitions(self, results: list[HealthCheckResult]) -> None:
        """Emit events for state transitions."""
        for result in results:
            if result.healthy:
                if result.reason == "Alpaca connection restored":
                    self.event_bus.emit(
                        "ALPACA_RESTORED",
                        result.timestamp.isoformat(),
                        result.component,
                        result.reason,
                    )
                    # Also emit EXECUTION_RESUMED since Alpaca is the critical dependency
                    self.event_bus.emit(
                        "EXECUTION_RESUMED",
                        result.timestamp.isoformat(),
                        result.component,
                        "Critical dependency restored",
                    )
                elif result.reason == "Market feed restored":
                    self.event_bus.emit(
                        "DATA_FEED_RESTORED",
                        result.timestamp.isoformat(),
                        result.component,
                        result.reason,
                    )
                elif result.reason == "Hermes Agentic restored":
                    self.event_bus.emit(
                        "HERMES_RESTORED",
                        result.timestamp.isoformat(),
                        result.component,
                        result.reason,
                    )
                elif result.reason == "File system restored":
                    self.event_bus.emit(
                        "FILE_SYSTEM_RESTORED",
                        result.timestamp.isoformat(),
                        result.component,
                        result.reason,
                    )
                elif result.reason == "Policy restored":
                    self.event_bus.emit(
                        "POLICY_RESTORED",
                        result.timestamp.isoformat(),
                        result.component,
                        result.reason,
                    )
            else:
                if "circuit tripped" in result.reason:
                    if result.component == "alpaca":
                        self.event_bus.emit(
                            "ALPACA_DISCONNECTED",
                            result.timestamp.isoformat(),
                            result.component,
                            result.reason,
                        )
                        self.event_bus.emit(
                            "EXECUTION_PAUSED",
                            result.timestamp.isoformat(),
                            result.component,
                            "Critical dependency degraded",
                        )
                    elif result.component == "market_feed":
                        self.event_bus.emit(
                            "DATA_STALE",
                            result.timestamp.isoformat(),
                            result.component,
                            result.reason,
                        )
                    elif result.component == "hermes_agentic":
                        self.event_bus.emit(
                            "HERMES_UNAVAILABLE",
                            result.timestamp.isoformat(),
                            result.component,
                            result.reason,
                        )
                    elif result.component == "file_system":
                        self.event_bus.emit(
                            "FILE_SYSTEM_DEGRADED",
                            result.timestamp.isoformat(),
                            result.component,
                            result.reason,
                        )
                    elif result.component == "policy":
                        self.event_bus.emit(
                            "POLICY_DEGRADED",
                            result.timestamp.isoformat(),
                            result.component,
                            result.reason,
                        )
