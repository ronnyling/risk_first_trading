"""Strategy registry: loads strategy metadata from YAML, instantiates strategies."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
from typing import Any

import yaml

from src.strategies.base import Strategy

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config/strategies.yaml")


def load_strategy_config(config_path: Path | None = None) -> list[dict[str, Any]]:
    """Load strategy definitions from YAML config."""
    path = config_path or CONFIG_PATH
    with open(path) as f:
        data = yaml.safe_load(f)
    return data.get("strategies", [])


def instantiate_strategy(entry: dict[str, Any]) -> Strategy:
    """Dynamically import and instantiate a strategy from config entry."""
    module_path = entry["module"]
    class_name = entry["class"]
    params = entry.get("params", {})

    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    instance = cls(**params)
    return instance


def load_strategies(config_path: Path | None = None) -> list[Strategy]:
    """Load all enabled strategies from config."""
    entries = load_strategy_config(config_path)
    strategies: list[Strategy] = []

    for entry in entries:
        if not entry.get("enabled", True):
            logger.info("Skipping disabled strategy: %s", entry.get("id", "?"))
            continue
        try:
            strat = instantiate_strategy(entry)
            strategies.append(strat)
            logger.info("Loaded strategy: %s", strat.metadata.strategy_id)
        except Exception:
            logger.exception("Failed to load strategy: %s", entry)

    return strategies