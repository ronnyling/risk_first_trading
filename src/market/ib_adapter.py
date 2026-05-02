"""IBMarketDataAdapter — Interactive Brokers market data adapter.

Subscribes to IB historical/real-time bars and returns Bar objects
through the standard MarketDataAdapter interface.

Usage:
    adapter = IBMarketDataAdapter.from_config(ib_config_dict)
    adapter.start()
    bar = adapter.get_next_bar()  # blocks until bar available
    adapter.stop()
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from src.core.types import Bar
from src.market.adapter import MarketDataAdapter

logger = logging.getLogger(__name__)


class IBMarketDataAdapter(MarketDataAdapter):
    """IB-based market data adapter.

    Connects to TWS/IB Gateway and fetches hourly bars for a configured symbol.
    Bars are buffered internally; get_next_bar() returns them sequentially.

    Supports two modes:
    - Historical: fetches N bars at start() via reqHistoricalData
    - Streaming: subscribes to real-time bars (future extension)
    """

    def __init__(
        self,
        ib_connection,  # ib_insync.IB instance (already connected)
        symbol: str = "SPY",
        exchange: str = "SMART",
        currency: str = "USD",
        duration: str = "1 W",
        bar_size: str = "1 hour",
        what_to_show: str = "TRADES",
        use_rth: bool = True,
    ) -> None:
        super().__init__()
        self._ib = ib_connection
        self._symbol = symbol
        self._exchange = exchange
        self._currency = currency
        self._duration = duration
        self._bar_size = bar_size
        self._what_to_show = what_to_show
        self._use_rth = use_rth
        self._bars: list[Bar] = []
        self._index: int = 0

    @classmethod
    def from_config(cls, ib_config: dict, data_config: dict | None = None) -> IBMarketDataAdapter:
        """Create from engine.yaml ib: + market_data: sections."""
        from ib_insync import IB

        ib = IB()
        ib.connect(
            ib_config.get("host", "127.0.0.1"),
            ib_config.get("port", 7497),
            clientId=ib_config.get("client_id", 1),
        )
        data_cfg = data_config or {}
        return cls(
            ib_connection=ib,
            symbol=ib_config.get("default_symbol", "SPY"),
            exchange=ib_config.get("default_exchange", "SMART"),
            currency=ib_config.get("default_currency", "USD"),
            duration=data_cfg.get("duration", "1 W"),
            bar_size=data_cfg.get("bar_size", "1 hour"),
            what_to_show=data_cfg.get("what_to_show", "TRADES"),
            use_rth=data_cfg.get("use_rth", True),
        )

    def start(self) -> None:
        """Fetch historical bars from IB."""
        from ib_insync import Stock

        contract = Stock(self._symbol, self._exchange, self._currency)

        logger.info(
            "IBMarketDataAdapter: requesting %s %s %s bars for %s",
            self._duration, self._bar_size, self._what_to_show, self._symbol,
        )

        try:
            ib_bars = self._ib.reqHistoricalData(
                contract,
                endDateTime="",
                durationStr=self._duration,
                barSizeSetting=self._bar_size,
                whatToShow=self._what_to_show,
                useRTH=self._use_rth,
                formatDate=1,
            )
        except Exception as e:
            logger.error("Failed to fetch IB historical data: %s", e)
            ib_bars = []

        self._bars = []
        for ib_bar in (ib_bars or []):
            ts = ib_bar.date
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
            elif ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            self._bars.append(Bar(
                timestamp=ts,
                open=float(ib_bar.open),
                high=float(ib_bar.high),
                low=float(ib_bar.low),
                close=float(ib_bar.close),
                volume=float(ib_bar.volume),
            ))

        self._index = 0
        self._bars_processed = 0
        logger.info(
            "IBMarketDataAdapter started: %d bars for %s",
            len(self._bars), self._symbol,
        )

    def stop(self) -> None:
        """No-op — IB connection managed externally."""
        logger.info(
            "IBMarketDataAdapter stopped: %d bars processed",
            self._bars_processed,
        )

    def get_next_bar(self) -> Bar | None:
        """Return the next historical bar, or None at end."""
        if self._index >= len(self._bars):
            return None
        bar = self._bars[self._index]
        self._index += 1
        self._increment_bar_count()
        return bar

    def get_history(self, n: int) -> list[Bar]:
        """Return the last n bars including current."""
        end = self._index
        start = max(0, end - n)
        return self._bars[start:end]

    @property
    def source_name(self) -> str:
        return "ib"

    @property
    def is_live(self) -> bool:
        return False  # historical fetch; streaming TBD

    def reset(self) -> None:
        """Reset index for re-iteration."""
        self._index = 0
        self._bars_processed = 0