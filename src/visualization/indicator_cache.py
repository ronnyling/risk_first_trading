"""Layer 1 — Indicator Computation Cache.

Precomputed indicators stored outside UI. Never recomputed during rendering.
Backed by SQLite with TTL-based expiry.

Phase F.3 — Visualization & Human Control Plane.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


class IndicatorCache:
    """SQLite-backed indicator computation cache.

    Keyed by (symbol, timeframe, indicator_name, indicator_version, lookback_hash).
    TTL-based expiry: 1 hour for live mode, no expiry for snapshot mode.
    """

    def __init__(self, db: Any = None) -> None:
        self._db = db

    def _get_conn(self) -> Any:
        """Get database connection."""
        if self._db is not None:
            return self._db._get_conn()
        return None

    def compute_cache_key(
        self,
        symbol: str,
        timeframe: str,
        indicator_name: str,
        indicator_version: str,
        bars_hash: str,
    ) -> str:
        """Compute deterministic cache key from inputs."""
        raw = f"{symbol}|{timeframe}|{indicator_name}|{indicator_version}|{bars_hash}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def compute_bars_hash(self, bars: list[Any]) -> str:
        """Compute a hash of bar data for cache keying.

        Uses first bar timestamp + last bar timestamp + count for efficiency.
        """
        if not bars:
            return "empty"
        first_ts = str(getattr(bars[0], "timestamp", ""))
        last_ts = str(getattr(bars[-1], "timestamp", ""))
        raw = f"{first_ts}|{last_ts}|{len(bars)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, cache_key: str) -> list[float] | None:
        """Retrieve cached indicator values. Returns None if miss or expired."""
        conn = self._get_conn()
        if conn is None:
            return None

        try:
            row = conn.execute(
                "SELECT computed_values, expires_at FROM indicator_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            if row is None:
                return None

            # Check expiry
            expires_at = datetime.fromisoformat(row["expires_at"])
            if datetime.now(timezone.utc) > expires_at:
                conn.execute(
                    "DELETE FROM indicator_cache WHERE cache_key = ?", (cache_key,)
                )
                conn.commit()
                return None

            return json.loads(row["computed_values"])
        except Exception as e:
            logger.warning("IndicatorCache.get failed: %s", e)
            return None

    def put(
        self,
        cache_key: str,
        symbol: str,
        timeframe: str,
        indicator_name: str,
        indicator_version: str,
        bars_hash: str,
        values: list[float],
        bar_start_idx: int,
        bar_end_idx: int,
        ttl_seconds: int = 3600,
    ) -> None:
        """Store computed indicator values."""
        conn = self._get_conn()
        if conn is None:
            return

        try:
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(seconds=ttl_seconds)
            conn.execute(
                """INSERT OR REPLACE INTO indicator_cache
                   (cache_key, symbol, timeframe, indicator_name, indicator_version,
                    lookback_hash, computed_values, computed_at, expires_at,
                    bar_start_idx, bar_end_idx)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cache_key,
                    symbol,
                    timeframe,
                    indicator_name,
                    indicator_version,
                    bars_hash,
                    json.dumps(values),
                    now.isoformat(),
                    expires_at.isoformat(),
                    bar_start_idx,
                    bar_end_idx,
                ),
            )
            conn.commit()
        except Exception as e:
            logger.warning("IndicatorCache.put failed: %s", e)

    def invalidate(self, symbol: str, timeframe: str) -> int:
        """Invalidate all cached indicators for a symbol+timeframe. Returns count."""
        conn = self._get_conn()
        if conn is None:
            return 0

        try:
            cursor = conn.execute(
                "DELETE FROM indicator_cache WHERE symbol = ? AND timeframe = ?",
                (symbol, timeframe),
            )
            conn.commit()
            count = cursor.rowcount
            if count > 0:
                logger.info(
                    "IndicatorCache: invalidated %d entries for %s/%s",
                    count, symbol, timeframe,
                )
            return count
        except Exception as e:
            logger.warning("IndicatorCache.invalidate failed: %s", e)
            return 0

    def clear_expired(self) -> int:
        """Remove all expired cache entries. Returns count removed."""
        conn = self._get_conn()
        if conn is None:
            return 0

        try:
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.execute(
                "DELETE FROM indicator_cache WHERE expires_at < ?", (now,)
            )
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            logger.warning("IndicatorCache.clear_expired failed: %s", e)
            return 0
