"""Visualization package — components, caching, and audit for the dashboard.

Phase F: Visualization & Human Control Plane.
"""

from src.visualization.family_mapping import (
    FAMILY_VISUAL_SPECS,
    IndicatorRole,
    AnnotationType,
    IndicatorSpec,
    AnnotationSpec,
    StrategyFamilyVisualSpec,
    get_family_spec,
    validate_indicator_set,
)
from src.visualization.models import (
    ChartContainerConfig,
    PriceContextData,
    IndicatorOverlayData,
    DecisionAnnotationData,
    CorrelationContextData,
    ModeBannerConfig,
)
from src.visualization.mode_resolver import SystemModeResolver

__all__ = [
    "FAMILY_VISUAL_SPECS",
    "IndicatorRole",
    "AnnotationType",
    "IndicatorSpec",
    "AnnotationSpec",
    "StrategyFamilyVisualSpec",
    "get_family_spec",
    "validate_indicator_set",
    "ChartContainerConfig",
    "PriceContextData",
    "IndicatorOverlayData",
    "DecisionAnnotationData",
    "CorrelationContextData",
    "ModeBannerConfig",
    "SystemModeResolver",
]
