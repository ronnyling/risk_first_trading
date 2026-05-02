import json
from pathlib import Path
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

class UniverseReader:
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.pointer_file = self.data_dir / "universe_current.json"

    def get_active_universe(self) -> Dict:
        """
        Reads universe_current.json to find the active version,
        then loads and returns that version's data.
        """
        if not self.pointer_file.exists():
            logger.warning(f"Universe pointer {self.pointer_file} not found.")
            return {"markets": {}}

        try:
            with open(self.pointer_file, "r") as f:
                pointer = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing {self.pointer_file}: {e}")
            return {"markets": {}}

        current_version_file = pointer.get("current_version_file")
        if not current_version_file:
            logger.warning("No current_version_file specified in pointer.")
            return {"markets": {}}

        version_path = self.data_dir / current_version_file
        if not version_path.exists():
            logger.error(f"Universe version file {version_path} not found.")
            return {"markets": {}}

        try:
            with open(version_path, "r") as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing {version_path}: {e}")
            return {"markets": {}}

    def get_enabled_markets(self) -> List[str]:
        """Returns a list of symbols that are currently active in the universe."""
        univ = self.get_active_universe()
        return list(univ.get("markets", {}).keys())

    def get_market_bucket(self, symbol: str) -> Optional[str]:
        univ = self.get_active_universe()
        market = univ.get("markets", {}).get(symbol)
        if market:
            return market.get("bucket")
        return None

    def get_enabled_families(self, symbol: str) -> List[str]:
        univ = self.get_active_universe()
        market = univ.get("markets", {}).get(symbol)
        if market:
            return market.get("enabled_families", [])
        return []
