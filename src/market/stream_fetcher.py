"""StreamFetcher — background data fetcher that maintains live bar buffers.

Polls yfinance at configurable intervals and updates per-symbol
StreamingBarBuffer instances with fresh bar data.

Production data source:
    yfinance is considered a production live-data adapter for Hermes advisory
    runs until the Alpaca data subscription is formally enabled.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

from src.market.live_data import fetch_bars
from src.market.streaming_buffer import BufferStatus, StreamingBarBuffer

logger = logging.getLogger(__name__)


class StreamFetcher:
    """Background data fetcher that maintains live bar buffers.

    Polls yfinance at configurable intervals and updates per-symbol
    StreamingBarBuffer instances. Thread-safe.

    Usage:
        fetcher = StreamFetcher(symbols=["BTC/USD", "ETH/USD", "SOL/USD"])
        fetcher.start()
        # ... later ...
        buffer = fetcher.get_buffer("BTC/USD")
        bars = buffer.get_snapshot(200)
        fetcher.stop()
    """

    def __init__(
        self,
        symbols: list[str],
        poll_interval_seconds: int = 300,
        bar_interval: str = "1h",
        stale_threshold_seconds: int = 300,
        max_bars: int = 250,
        rate_limit_cooldown_seconds: float = 0.0,
        fetch_timeout_seconds: float = 30.0,
    ) -> None:
        """Initialize the stream fetcher.

        Args:
            symbols: Universe symbols to fetch.
            poll_interval_seconds: Seconds between fetch cycles (default: 300 = 5 min).
            bar_interval: Bar interval for yfinance (default: "1h").
            stale_threshold_seconds: Seconds before buffer goes STALE (default: 300).
            max_bars: Maximum bars per buffer (default: 250).
            rate_limit_cooldown_seconds: Minimum seconds between yfinance calls (default: 0).
            fetch_timeout_seconds: Maximum seconds per symbol fetch (default: 30).
        """
        self._symbols = list(symbols)
        self._poll_interval = poll_interval_seconds
        self._bar_interval = bar_interval
        self._max_bars = max_bars
        self._rate_limit_cooldown = rate_limit_cooldown_seconds
        self._fetch_timeout = fetch_timeout_seconds
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Initialize buffers
        self._buffers: dict[str, StreamingBarBuffer] = {}
        for sym in symbols:
            self._buffers[sym] = StreamingBarBuffer(
                symbol=sym,
                stale_threshold_seconds=stale_threshold_seconds,
                max_bars=max_bars,
            )

        # Error tracking
        self._consecutive_errors: dict[str, int] = {sym: 0 for sym in symbols}
        self._max_consecutive_errors = 3

        logger.info(
            "StreamFetcher initialized: %d symbols, poll=%ds, stale=%ds",
            len(symbols), poll_interval_seconds, stale_threshold_seconds,
        )

    def start(self) -> None:
        """Start the background polling thread."""
        if self._running:
            logger.warning("StreamFetcher already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="stream-fetcher",
            daemon=True,
        )
        self._thread.start()
        logger.info("StreamFetcher started")

    def stop(self) -> None:
        """Stop the background polling thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        self._thread = None
        logger.info("StreamFetcher stopped")

    def _poll_loop(self) -> None:
        """Main polling loop. Runs until stopped."""
        # Initial fetch
        self._fetch_all()

        while self._running:
            time.sleep(self._poll_interval)
            if self._running:
                self._fetch_all()

    def _fetch_all(self) -> None:
        """Fetch new bars for all symbols with rate-limit enforcement."""
        for i, symbol in enumerate(self._symbols):
            if not self._running:
                break
            self._fetch_symbol(symbol)
            # Rate limit enforcement: wait between consecutive yfinance calls
            if i < len(self._symbols) - 1 and self._rate_limit_cooldown > 0:
                time.sleep(self._rate_limit_cooldown)

    def _fetch_symbol(self, symbol: str) -> None:
        """Fetch new bars for a single symbol and update its buffer."""
        try:
            bars = fetch_bars(symbol, interval=self._bar_interval, count=self._max_bars)
            with self._lock:
                buffer = self._buffers.get(symbol)
                if buffer is not None:
                    added = buffer.update(bars)
                    if added > 0:
                        logger.debug(
                            "StreamFetcher: %s updated with %d new bars (total: %d)",
                            symbol, added, buffer.bar_count,
                        )
                    self._consecutive_errors[symbol] = 0

        except Exception as e:
            with self._lock:
                self._consecutive_errors[symbol] = (
                    self._consecutive_errors.get(symbol, 0) + 1
                )
                errors = self._consecutive_errors[symbol]

            logger.warning(
                "StreamFetcher: fetch failed for %s (attempt %d/%d): %s",
                symbol, errors, self._max_consecutive_errors, e,
            )

            if errors >= self._max_consecutive_errors:
                with self._lock:
                    buffer = self._buffers.get(symbol)
                    if buffer is not None:
                        buffer.status = BufferStatus.DEAD
                logger.error(
                    "StreamFetcher: buffer for %s marked DEAD after %d consecutive errors",
                    symbol, errors,
                )

    def get_buffer(self, symbol: str) -> StreamingBarBuffer | None:
        """Get the buffer for a specific symbol."""
        with self._lock:
            return self._buffers.get(symbol)

    def get_all_buffers(self) -> dict[str, StreamingBarBuffer]:
        """Get all buffers (copy)."""
        with self._lock:
            return dict(self._buffers)

    def is_healthy(self) -> bool:
        """True if all buffers are FRESH."""
        with self._lock:
            return all(
                buf.status == BufferStatus.FRESH
                for buf in self._buffers.values()
            )

    @property
    def running(self) -> bool:
        """Whether the fetcher is currently polling."""
        return self._running

    @property
    def symbol_count(self) -> int:
        """Number of symbols being tracked."""
        return len(self._symbols)

    def get_health_summary(self) -> dict[str, str]:
        """Get a summary of buffer health status.

        Returns:
            Dict mapping symbol → status string (e.g., "FRESH", "STALE", "DEAD").
        """
        with self._lock:
            return {
                sym: buf.status.value
                for sym, buf in self._buffers.items()
            }
