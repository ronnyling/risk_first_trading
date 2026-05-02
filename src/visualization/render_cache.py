"""Layer 3 — UI Render Cache.

Per-session Plotly figure cache. Lives in Streamlit session_state.
Enables fast tab switching and scrolling without re-rendering.

Phase F.3 — Visualization & Human Control Plane.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)

MAX_CACHE_SIZE = 100


class UIRenderCache:
    """Per-session Plotly figure cache.

    Can operate in two modes:
    1. Streamlit mode: uses st.session_state (default)
    2. Standalone mode: uses internal OrderedDict (for testing/non-Streamlit)
    """

    CACHE_KEY = "_chart_render_cache"

    def __init__(self, session_state: Any = None) -> None:
        """Initialize the render cache.

        Args:
            session_state: Streamlit session_state dict. If None, uses standalone mode.
        """
        self._standalone_cache: OrderedDict[str, Any] = OrderedDict()
        self._use_streamlit = False
        self._session_state = None

        if session_state is not None:
            try:
                if self.CACHE_KEY not in session_state:
                    session_state[self.CACHE_KEY] = {}
                self._session_state = session_state
                self._use_streamlit = True
            except Exception:
                # Fallback to standalone mode
                pass

    def _get_cache(self) -> dict[str, Any]:
        """Get the active cache dict."""
        if self._use_streamlit and self._session_state is not None:
            return self._session_state[self.CACHE_KEY]
        return self._standalone_cache

    def get(self, snapshot_id: str) -> Any | None:
        """Retrieve cached Plotly figure. Returns None on miss."""
        cache = self._get_cache()
        return cache.get(snapshot_id)

    def put(self, snapshot_id: str, figure: Any) -> None:
        """Cache a Plotly figure. Evicts oldest if >= MAX_CACHE_SIZE."""
        cache = self._get_cache()

        if self._use_streamlit:
            # Streamlit mode: simple dict with size check
            if len(cache) >= MAX_CACHE_SIZE:
                # Evict oldest key (FIFO)
                oldest_key = next(iter(cache))
                del cache[oldest_key]
            cache[snapshot_id] = figure
        else:
            # Standalone mode: use OrderedDict for FIFO
            if len(self._standalone_cache) >= MAX_CACHE_SIZE:
                self._standalone_cache.popitem(last=False)
            self._standalone_cache[snapshot_id] = figure

    def invalidate(self, snapshot_id: str) -> None:
        """Remove a specific cached figure."""
        cache = self._get_cache()
        cache.pop(snapshot_id, None)

    def clear(self) -> None:
        """Clear entire render cache."""
        cache = self._get_cache()
        cache.clear()

    def size(self) -> int:
        """Return number of cached figures."""
        return len(self._get_cache())

    def has(self, snapshot_id: str) -> bool:
        """Check if a snapshot is cached."""
        return snapshot_id in self._get_cache()
