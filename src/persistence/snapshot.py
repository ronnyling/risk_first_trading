"""Snapshot writer to communicate state to the dashboard."""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

class StateSnapshotWriter:
    def __init__(self, output_path: str = "data/state_snapshot.json"):
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        
    def write(self, snapshot: dict) -> None:
        """
        Snapshot must contain:
        - profile
        - ladder_state
        - equity
        - drawdown_pct
        - open_trades (list of dicts)
        - blocked_trades (count or list)
        - health (dict with broker_status, op_mode, blacklisted_markets)
        """
        # Inject timestamp
        snapshot["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            # Write temp file and rename for atomic write
            temp_path = self.output_path.with_suffix(".json.tmp")
            with open(temp_path, "w") as f:
                json.dump(snapshot, f, indent=2)
            temp_path.replace(self.output_path)
        except Exception as e:
            logger.error(f"Failed to write state snapshot: {e}")
