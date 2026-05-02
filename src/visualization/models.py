"""Data models for the Visualization & Human Control Plane (Phase F).

Immutable dataclasses for chart configuration, overlay data, and mode state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ──────────────────────────────────────────────────────
# Component A — ChartContainer
# ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ChartContainerConfig:
    """Configuration for a ChartContainer wrapper.

    Attributes:
        system_mode: Current system mode (LIVE | ADVISORY | META_LOCKDOWN).
        symbol: Symbol being displayed (e.g. "BTC/USD").
        timeframe: Timeframe of the chart (e.g. "1H").
        chart_id: Unique ID for audit logging.
        snapshot_id: Links to analysis snapshot store, if available.
        show_banner: Whether to render the mode banner.
        interactive: Whether chart is interactive (False in META_LOCKDOWN).
    """

    system_mode: str
    symbol: str
    timeframe: str
    chart_id: str
    snapshot_id: str | None = None
    show_banner: bool = True
    interactive: bool = True


# ──────────────────────────────────────────────────────
# Component B — PriceContextChart
# ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class PriceContextData:
    """Data for the PriceContextChart component.

    Attributes:
        symbol: Symbol being displayed.
        timeframe: Timeframe of the chart.
        bars: OHLC bars (snapshot or live).
        strategy_family: Drives which indicators overlay.
        hermes_decision: Hermes decision for annotations, if available.
        snapshot_id: Links to analysis snapshot store.
    """

    symbol: str
    timeframe: str
    bars: list[Any] = field(default_factory=list)  # list[Bar]
    strategy_family: str = "structural_fractal"
    hermes_decision: Any = None  # HermesDecision | None
    snapshot_id: str | None = None


# ──────────────────────────────────────────────────────
# Component C — IndicatorOverlayLayer
# ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class IndicatorOverlayData:
    """Data for the IndicatorOverlayLayer component.

    Attributes:
        strategy_family: Key into FAMILY_VISUAL_SPECS.
        precomputed_indicators: Indicator name → computed values mapping.
    """

    strategy_family: str
    precomputed_indicators: dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────────────
# Component D — DecisionAnnotationLayer
# ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class DecisionAnnotationData:
    """Data for the DecisionAnnotationLayer component.

    Attributes:
        hermes_decision: The Hermes decision object, if available.
        entry_zone: (low, high) price range for entry zone shading.
        invalidation_zone: (low, high) price range for invalidation shading.
        exit_criteria: Logical exit condition label.
        confidence_label: Human-readable confidence score.
        directive_label: Risk directive text (e.g. "SCALE_IN").
        strategy_family: Drives annotation rendering style.
    """

    hermes_decision: Any = None  # HermesDecision | None
    entry_zone: tuple[float, float] | None = None
    invalidation_zone: tuple[float, float] | None = None
    exit_criteria: str | None = None
    confidence_label: str | None = None
    directive_label: str | None = None
    strategy_family: str = "structural_fractal"


# ──────────────────────────────────────────────────────
# Component E — CorrelationContextLayer
# ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class CorrelationContextData:
    """Data for the CorrelationContextLayer component.

    Attributes:
        correlation_matrix: CorrelationMatrix object, if available.
        correlated_symbols: Symbols with |r| > threshold.
        diversification_score: 0-1 score (higher = more diversified).
        redundancy_warnings: Human-readable warnings.
        current_symbol: Highlighted symbol in the view.
    """

    correlation_matrix: Any = None  # CorrelationMatrix | None
    correlated_symbols: list[str] = field(default_factory=list)
    diversification_score: float = 0.0
    redundancy_warnings: list[str] = field(default_factory=list)
    current_symbol: str | None = None


# ──────────────────────────────────────────────────────
# Component F — ModeBanner
# ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ModeBannerConfig:
    """Configuration for the ModeBanner component.

    Attributes:
        system_mode: Current system mode (LIVE | ADVISORY | META_LOCKDOWN).
        execution_active: Whether the engine is currently running.
        last_updated: ISO timestamp of last state change.
    """

    system_mode: str
    execution_active: bool = False
    last_updated: str = ""
