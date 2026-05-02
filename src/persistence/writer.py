"""Persistence Writer — bridges EventBus events to SQLite persistence.

Subscribes to engine events (fill, veto, regime change) and writes them
to PersistenceDB for audit trail. Non-blocking, fail-safe (errors logged, not raised).
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.core.events import EventBus
from src.core.types import Fill, Order
from src.persistence.db import PersistenceDB
from src.persistence.models import FillRecord, VetoRecord

logger = logging.getLogger(__name__)


class PersistenceWriter:
    """Subscribes to EventBus events and persists them to SQLite.

    Events handled:
        "fill"           → FillRecord (append-only)
        "order_vetoed"   → VetoRecord (append-only)

    Usage:
        writer = PersistenceWriter(event_bus, db)
        # Writer is now active — events are persisted automatically.
    """

    def __init__(
        self,
        event_bus: EventBus,
        db: PersistenceDB | None = None,
    ) -> None:
        self._db = db or PersistenceDB()
        self._bar_index: int = 0  # tracks current bar for record context

        # Subscribe to engine events
        event_bus.subscribe("fill", self._on_fill)
        event_bus.subscribe("order_vetoed", self._on_veto)

        logger.info("PersistenceWriter initialized")

    def advance_bar(self) -> None:
        """Increment bar index. Called by engine at start of each bar."""
        self._bar_index += 1

    def _on_fill(self, fill: Fill) -> None:
        """Handle fill event — persist to DB."""
        try:
            record = FillRecord(
                order_id=fill.order_id,
                symbol=fill.symbol,
                side=fill.side.value if hasattr(fill.side, "value") else str(fill.side),
                quantity=fill.quantity,
                fill_price=fill.fill_price,
                commission=fill.commission,
                pnl=fill.pnl,
                strategy_id=fill.strategy_id,
                timestamp=fill.timestamp.isoformat() if hasattr(fill.timestamp, "isoformat") else str(fill.timestamp),
                bar_index=self._bar_index,
            )
            self._db.record_fill(record)
        except Exception as e:
            logger.error("Failed to persist fill: %s", e)

    def _on_veto(self, order: Order, reason: str) -> None:
        """Handle order_vetoed event — persist to DB."""
        try:
            record = VetoRecord(
                bar_index=self._bar_index,
                timestamp=datetime.now().isoformat(),
                order_id=order.order_id if hasattr(order, "order_id") else str(order),
                strategy_id=order.strategy_id if hasattr(order, "strategy_id") else "",
                reason=reason,
            )
            self._db.record_veto(record)
        except Exception as e:
            logger.error("Failed to persist veto: %s", e)
