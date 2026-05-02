"""Event Log — Cross-process event bridge via JSONL file.

The EventBus is in-process and synchronous. Streamlit runs in a separate
process. This module bridges them:

1. EventLogWriter subscribes to EventBus and appends events to a JSONL file.
2. Streamlit reads new lines from the JSONL file on each refresh cycle,
   using byte-offset + timestamp deduplication to avoid replay.

File format: one JSON object per line (JSONL / newline-delimited JSON).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_LOG_PATH = "data/health_events.jsonl"


class EventLogWriter:
    """Writes EventBus events to a JSONL file for cross-process consumption.

    Subscribe this as an event handler for all health events:

        writer = EventLogWriter()
        for event_name in HealthEvents.__dict__:
            if not event_name.startswith("_"):
                event_bus.subscribe(event_name, writer)
    """

    def __init__(self, log_path: str = DEFAULT_LOG_PATH) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(
        self, event_name: str, *args: Any, **kwargs: Any
    ) -> None:
        """Handle an EventBus event — append to JSONL file.

        Accepts both positional args (timestamp, component, reason) and
        keyword args for flexibility with different event signatures.
        """
        # Extract positional args from EventBus.emit signature:
        # emit(event_name, timestamp, component, reason)
        timestamp = args[0] if len(args) > 0 else kwargs.get("timestamp", "")
        component = args[1] if len(args) > 1 else kwargs.get("component", "")
        reason = args[2] if len(args) > 2 else kwargs.get("reason", "")

        entry = {
            "event": event_name,
            "timestamp": str(timestamp),
            "component": str(component),
            "reason": str(reason),
        }

        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.error("Failed to write event log: %s", e)


def read_new_events(
    log_path: str = DEFAULT_LOG_PATH,
    last_offset: int = 0,
    last_timestamp: str = "",
) -> tuple[list[dict], int, str]:
    """Read only new events from the JSONL file.

    Args:
        log_path: Path to the JSONL event log.
        last_offset: Byte offset of the last read position.
        last_timestamp: ISO timestamp of the last processed event.

    Returns:
        Tuple of (new_events, new_offset, new_timestamp).
    """
    path = Path(log_path)
    if not path.exists():
        return [], last_offset, last_timestamp

    new_events: list[dict] = []
    new_offset = last_offset
    new_timestamp = last_timestamp

    try:
        with open(path, "r", encoding="utf-8") as f:
            f.seek(last_offset)

            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    # Deduplication: skip if timestamp <= last processed
                    event_ts = event.get("timestamp", "")
                    if event_ts and event_ts <= last_timestamp:
                        continue
                    new_events.append(event)
                except json.JSONDecodeError:
                    continue

            new_offset = f.tell()

        if new_events:
            new_timestamp = new_events[-1].get("timestamp", new_timestamp)

    except Exception as e:
        logger.error("Failed to read event log: %s", e)

    return new_events, new_offset, new_timestamp
