"""Simple pub/sub event bus for decoupled communication between components."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)


# Health Event Constants
class HealthEvents:
    """Constants for health-related events."""
    
    # Alpaca Events
    ALPACA_DISCONNECTED = "ALPACA_DISCONNECTED"
    ALPACA_RESTORED = "ALPACA_RESTORED"
    
    # Execution Events
    EXECUTION_PAUSED = "EXECUTION_PAUSED"
    EXECUTION_RESUMED = "EXECUTION_RESUMED"
    
    # Hermes Agentic Events
    HERMES_UNAVAILABLE = "HERMES_UNAVAILABLE"
    HERMES_RUN_COMPLETED = "HERMES_RUN_COMPLETED"
    HERMES_RESTORED = "HERMES_RESTORED"
    
    # Data Feed Events
    DATA_STALE = "DATA_STALE"
    DATA_FEED_RESTORED = "DATA_FEED_RESTORED"
    
    # File System Events
    FILE_SYSTEM_DEGRADED = "FILE_SYSTEM_DEGRADED"
    FILE_SYSTEM_RESTORED = "FILE_SYSTEM_RESTORED"
    
    # Policy Events
    POLICY_DEGRADED = "POLICY_DEGRADED"
    POLICY_RESTORED = "POLICY_RESTORED"
    
    # Scaling Events
    SCALING_LIMIT_EXCEEDED = "SCALING_LIMIT_EXCEEDED"
    SCALING_DEGRADATION_ACTIVE = "SCALING_DEGRADATION_ACTIVE"
    SCALING_RATE_LIMITED = "SCALING_RATE_LIMITED"
    SCALING_TIMEOUT_PARTIAL = "SCALING_TIMEOUT_PARTIAL"

class EventBus:
    """Lightweight synchronous event bus.

    Components emit events by name; subscribers receive them in registration order.
    Used for audit logging, metric updates, and cross-component notifications.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[..., Any]]] = defaultdict(list)

    def subscribe(self, event_name: str, handler: Callable[..., Any]) -> None:
        self._handlers[event_name].append(handler)

    def unsubscribe(self, event_name: str, handler: Callable[..., Any]) -> None:
        if handler in self._handlers[event_name]:
            self._handlers[event_name].remove(handler)

    def emit(self, event_name: str, *args: Any, **kwargs: Any) -> None:
        for handler in self._handlers.get(event_name, []):
            try:
                handler(*args, **kwargs)
            except Exception:
                logger.exception("Error in handler %s for event %s", handler, event_name)

    def clear(self) -> None:
        self._handlers.clear()