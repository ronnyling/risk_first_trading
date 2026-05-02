"""Hermes Scheduler — fires Hermes runs on a time-based schedule.

Standalone daemon process that reads schedule config, checks for overlap,
and triggers `trigger_hermes_run()` at configured intervals.

Hermes remains advisory: this scheduler only fires runs, it never
mutates execution state.

Usage:
    python -m src.heremes.scheduler

Configuration:
    data/hermes_agentic_config.json — schedule settings
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("data/hermes_agentic_config.json")
LOCK_FILE = Path("data/.hermes_scheduler_lock")
STALE_LOCK_THRESHOLD_SECONDS = 1800  # 30 minutes
MIN_INTERVAL_MINUTES = 15
SLEEP_INTERVAL_SECONDS = 60  # check schedule every minute


def _read_config() -> dict:
    """Read scheduler config from disk. Returns empty dict on failure."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    except Exception as e:
        logger.error("Failed to read scheduler config: %s", e)
        return {}


def _write_config(config: dict) -> None:
    """Write scheduler config to disk."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")


def _acquire_lock(run_id: str) -> bool:
    """Acquire the scheduler lock file. Returns True if lock acquired.

    If lock exists and is stale (>30 min), it is cleaned up.
    """
    if LOCK_FILE.exists():
        try:
            lock_data = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
            lock_age = datetime.now().isoformat()
            lock_ts = lock_data.get("timestamp", "")
            if lock_ts:
                try:
                    lock_time = datetime.fromisoformat(lock_ts)
                    age_seconds = (datetime.now() - lock_time).total_seconds()
                    if age_seconds < STALE_LOCK_THRESHOLD_SECONDS:
                        logger.info(
                            "Scheduler lock held by run %s (age: %.0fs). Skipping.",
                            lock_data.get("run_id", "unknown"),
                            age_seconds,
                        )
                        return False
                    else:
                        logger.warning(
                            "Stale scheduler lock (age: %.0fs). Cleaning up.",
                            age_seconds,
                        )
                except (ValueError, TypeError):
                    logger.warning("Malformed lock timestamp. Cleaning up.")
        except (json.JSONDecodeError, KeyError):
            logger.warning("Malformed lock file. Cleaning up.")

    # Write lock
    lock_data = {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(),
    }
    LOCK_FILE.write_text(json.dumps(lock_data), encoding="utf-8")
    return True


def _release_lock() -> None:
    """Release the scheduler lock file."""
    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
    except Exception as e:
        logger.warning("Failed to release scheduler lock: %s", e)


def _should_fire(config: dict) -> bool:
    """Check if a run should fire based on schedule config.

    Returns True if:
    - Scheduler is enabled
    - run_mode is 'Scheduled'
    - Enough time has passed since last run
    - Current hour is within allowed_hours window
    """
    if not config.get("enabled", False):
        return False

    if config.get("run_mode") != "Scheduled":
        return False

    schedule = config.get("schedule", {})
    if not isinstance(schedule, dict):
        return False

    schedule_type = schedule.get("type", "")
    if schedule_type != "interval":
        return False

    interval_minutes = schedule.get("interval_minutes", 60)
    if interval_minutes < MIN_INTERVAL_MINUTES:
        logger.warning(
            "Interval %d min below minimum %d min. Using minimum.",
            interval_minutes,
            MIN_INTERVAL_MINUTES,
        )
        interval_minutes = MIN_INTERVAL_MINUTES

    # Check allowed_hours window
    allowed_hours = schedule.get("allowed_hours")
    if allowed_hours and isinstance(allowed_hours, dict):
        current_hour = datetime.now().hour
        start_hour = allowed_hours.get("start", 0)
        end_hour = allowed_hours.get("end", 23)
        if not (start_hour <= current_hour <= end_hour):
            logger.debug(
                "Current hour %d outside allowed window [%d, %d]",
                current_hour,
                start_hour,
                end_hour,
            )
            return False

    # Check if enough time has passed since last run
    last_run_at = config.get("last_run_at")
    if last_run_at:
        try:
            last_run_time = datetime.fromisoformat(last_run_at)
            elapsed_minutes = (datetime.now() - last_run_time).total_seconds() / 60
            if elapsed_minutes < interval_minutes:
                logger.debug(
                    "Only %.1f min since last run (interval: %d min). Waiting.",
                    elapsed_minutes,
                    interval_minutes,
                )
                return False
        except (ValueError, TypeError):
            pass  # Malformed timestamp, allow fire

    return True


def _fire_run() -> dict:
    """Fire a scheduled Hermes run.

    Returns the result dict from trigger_hermes_run().
    """
    import uuid
    from datetime import datetime as dt

    run_id = f"scheduled_{dt.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:6]}"

    logger.info("Scheduler firing run %s", run_id)

    # Import and call trigger_hermes_run with run_mode="Scheduled"
    # We import here to avoid circular imports and to allow the scheduler
    # to be launched independently of the dashboard
    try:
        # Add project root to path for imports
        project_root = str(Path(__file__).resolve().parent.parent.parent)
        src_path = os.path.join(project_root, "src")
        if src_path not in sys.path:
            sys.path.insert(0, src_path)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        from dashboard.app import trigger_hermes_run
        result = trigger_hermes_run(run_mode="Scheduled")
    except Exception as e:
        logger.error("Failed to execute scheduled run: %s", e)
        result = {
            "run_id": run_id,
            "status": "error",
            "error": str(e),
        }

    return result


def _update_config_after_run(config: dict, result: dict) -> dict:
    """Update config with run metadata after completion."""
    config["last_run_id"] = result.get("run_id")
    config["last_run_at"] = datetime.now().isoformat()
    config["last_run_status"] = result.get("status", "unknown")
    return config


def run_scheduler() -> None:
    """Main scheduler loop. Runs until interrupted."""
    logger.info("Hermes scheduler started")

    # Set up signal handlers for graceful shutdown
    running = True

    def handle_signal(signum, frame):
        nonlocal running
        logger.info("Scheduler received signal %d, shutting down...", signum)
        running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    while running:
        try:
            config = _read_config()

            if _should_fire(config):
                import uuid
                run_id = f"scheduled_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{str(uuid.uuid4())[:6]}"

                if _acquire_lock(run_id):
                    try:
                        result = _fire_run()
                        config = _update_config_after_run(config, result)
                        _write_config(config)
                        logger.info(
                            "Scheduled run completed: status=%s",
                            result.get("status"),
                        )
                    finally:
                        _release_lock()

            time.sleep(SLEEP_INTERVAL_SECONDS)

        except Exception as e:
            logger.error("Scheduler loop error: %s", e)
            time.sleep(SLEEP_INTERVAL_SECONDS)

    logger.info("Hermes scheduler stopped")
    _release_lock()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    run_scheduler()
