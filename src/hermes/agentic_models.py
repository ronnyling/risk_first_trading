"""
Hermes Agentic Data Contracts (PARSING ONLY)

This module defines the Pydantic schemas for artifacts produced by the
external Hermes Agentic AI system (Git submodule: external/hermes-agentic/).

DO NOT add generation logic, advisory logic, or file I/O here.
The external submodule writes artifacts to:
  - data/hermes_runs/
  - data/hermes_proposals/
  - data/hermes_alerts/
  - docs/hermes_actions/*.md

Streamlit and test scripts consume these artifacts.
"""

from pydantic import BaseModel
from typing import Literal, Dict, List, Optional
from datetime import datetime


class MarketContext(BaseModel):
    symbol: str
    asset_class: str
    liquidity_metrics: dict
    volatility_metrics: dict
    historical_regimes: List[str]
    backtest_metadata: dict


class HermesMarketRecommendation(BaseModel):
    symbol: str
    asset_class: str
    family_fit: Dict[str, bool]    # {"STRUCTURAL": True, "MEAN_REVERSION": False}
    proposed_bucket: Optional[str] = None
    suitability_score: float       # 0.0 - 1.0
    confidence_level: Literal["LOW", "MEDIUM", "HIGH"]
    notes: List[str]
    risk_flags: List[str]
    requires_human_review: bool
    hermes_run_id: str
    timestamp: datetime


class HermesRunSummary(BaseModel):
    run_id: str
    started_at: datetime
    completed_at: datetime
    total_markets_scanned: int
    proposals_generated: int
    alerts_generated: int = 0


class HermesAlert(BaseModel):
    alert_id: str
    event_type: Literal["REGIME_REANALYSIS", "BUCKET_CONFLICT"]
    symbol: Optional[str] = None  # For regime reanalysis
    symbols: Optional[List[str]] = None  # For conflicts
    trigger_reason: Optional[str] = None
    bucket: Optional[str] = None
    confidence_scores: Optional[Dict[str, float]] = None
    affected_families: Optional[List[str]] = None
    action: Optional[str] = None
    recommendation: Optional[str] = None
    requires_human_review: bool
    hermes_run_id: str
    timestamp: datetime


class HermesActionHandoff(BaseModel):
    symbol: str
    rationale: str
    required_code_changes: str
    action_id: str
    timestamp: datetime
