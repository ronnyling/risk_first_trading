# Operations Documentation Version

**System Version:** v1.3.0
**Last Updated:** 2026-05-02
**Phases Implemented:** 1-9 (Phase F = Visualization & Human Control Plane)
**Test Suite:** 1258 passed (+92 Phase F), 4 pre-existing failures

---

## Documentation Inventory

| # | Document | Type | Status |
|---|----------|------|--------|
| 01 | `01_startup_shutdown.md` | Playbook | Complete |
| 02 | `02_daily_operations.md` | Playbook | Complete |
| 03 | `03_hermes_operations.md` | Playbook | Complete |
| 04 | `04_risk_drawdown_response.md` | Playbook | Complete |
| 05 | `05_broker_disconnect.md` | Runbook | Complete |
| 06 | `06_data_feed_failure.md` | Runbook | Complete |
| 07 | `07_hermes_scheduling_failure.md` | Runbook | Complete |
| 08 | `08_stale_streaming_data.md` | Runbook | Complete |
| 09 | `09_unexpected_drawdown.md` | Runbook | Complete |
| 10 | `10_engine_crash_recovery.md` | Runbook | Complete |
| 11 | `11_scaling_degradation.md` | Runbook | Complete |
| 12 | `12_decision_boundaries.md` | Reference | Complete |
| 13 | `13_meta_optimization.md` | Reference | Complete |

## Visualization Package (Phase F)

| Module | Purpose | Status |
|--------|---------|--------|
| `src/visualization/models.py` | Data models (ChartContainerConfig, PriceContextData, etc.) | Complete |
| `src/visualization/family_mapping.py` | Canonical indicator ↔ strategy family mapping | Complete |
| `src/visualization/chart_container.py` | Component A — Mode-aware chart wrapper | Complete |
| `src/visualization/price_context_chart.py` | Component B — Candlestick chart with context | Complete |
| `src/visualization/indicator_overlay.py` | Component C — Indicator rendering from mapping | Complete |
| `src/visualization/decision_annotations.py` | Component D — Decision explanation overlays | Complete |
| `src/visualization/correlation_context.py` | Component E — Correlation heatmap and context | Complete |
| `src/visualization/mode_banner.py` | Component F — Global mode indicator | Complete |
| `src/visualization/mode_resolver.py` | System mode detection | Complete |
| `src/visualization/indicator_cache.py` | Layer 1 — Indicator computation cache | Complete |
| `src/visualization/snapshot_store.py` | Layer 2 — Analysis snapshot store | Complete |
| `src/visualization/render_cache.py` | Layer 3 — UI Plotly figure cache | Complete |
| `src/visualization/audit_logger.py` | UI interaction logging | Complete |
| `dashboard/pages/5_Logs.py` | Logs & Events page | Complete |

## Change Log

| Date | Phase | Change |
|------|-------|--------|
| 2026-05-02 | Phase F | Visualization & Human Control Plane (6 components, 3 caching layers, audit logging) |
| 2026-05-02 | Phase E | Meta-Optimization Plane (self-optimization, leverage, policy, LLM, mutation) |
| 2026-05-02 | Phase 7 | Continuous Breadth Expansion Workflow (A→B→C→D) |
| 2026-05-02 | Phase 6 | Initial creation of all playbooks and runbooks |
| 2026-05-02 | Phase 5 | Scaling strategies implemented (profiles, rate limits, timeout) |
| 2026-05-02 | Phase 4 | Analytics & reporting layers |
| 2026-05-02 | Phase 3 | Portfolio correlation modeling |
| 2026-05-02 | Phase 2 | Live streaming data ingestion |
| 2026-05-02 | Phase 1 | Hermes scheduling |
