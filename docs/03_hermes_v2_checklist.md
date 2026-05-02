# Hermes v2 Upgrade Checklist

## Prerequisites (Must be complete before v2 work)

- **Hermes World Model** (`docs/07_hermes_world_model.md`) — Regime-first architecture governance
- **SPG-001** (`docs/02_strategy_acceptance_retirement.md`) — Strategy Promotion Gate with 7-state lifecycle
- **Strategy Pool** — Both strategies in Probationary state under SPG-001

## Current State (v1)
- Rule-based allocation via YAML policy
- 5 hardcoded rules (regime matching, drawdown pause, risk-down, correlation cap)
- No learning, no adaptation
- All decisions deterministic based on current state

## Target State (v2)
- ML-powered allocation policy
- Adaptive to market conditions
- Correlation-aware portfolio construction
- Persistent state and audit trail

---

## Upgrade Checklist

### 1. Persistent State Layer
- [ ] Add SQLite database for strategy state
- [ ] Store strategy lifecycle (Candidate/Approved/Probationary/Active/Degraded/Suspended/Retired per SPG-001)
- [ ] Store allocation history
- [ ] Store regime history
- [ ] Store all fills and trades
- [ ] Implement state migration (v1 in-memory → v2 SQLite)

### 2. Correlation Matrix
- [ ] Add return correlation tracking between strategies
- [ ] Implement rolling correlation window (30-day default)
- [ ] Add correlation-aware allocation capping
- [ ] Add correlation matrix to Hermes evaluation input
- [ ] Alert when pairwise correlation exceeds 0.8

### 3. ML Allocation Policy
- [ ] Design feature vector for policy input:
  - Regime (one-hot: trending, ranging, volatile)
  - Strategy metrics (Sharpe, drawdown, win_rate, bars_since_trade)
  - Portfolio metrics (total drawdown, exposure, leverage)
  - Correlation matrix (flattened)
  - Recent performance (last N fills)
- [ ] Implement online learning (lightweight, reversible)
- [ ] Add confidence intervals on allocation decisions
- [ ] Add A/B testing framework (rule-based vs ML)
- [ ] Implement rollback if ML policy underperforms

### 4. Enhanced Degradation Detection
- [ ] Implement rolling Sharpe calculation
- [ ] Add drawdown streak tracking
- [ ] Add trade frequency anomaly detection
- [ ] Add automatic suspension triggers
- [ ] Add re-validation pipeline

### 5. Regime-Adaptive Parameters
- [ ] Allow strategy parameters to shift with regime
- [ ] Add regime-specific allocation caps
- [ ] Add regime transition handling (smooth handoff)
- [ ] Add regime confidence scoring

### 6. Multi-Asset Support
- [ ] Extend strategy metadata to support multiple symbols
- [ ] Add asset-level risk limits
- [ ] Add cross-asset correlation tracking
- [ ] Add portfolio-level diversification scoring

### 7. Monitoring & Observability
- [ ] Add Prometheus metrics export
- [ ] Add Grafana dashboards for:
  - Strategy PnL over time
  - Hermes allocation decisions
  - Risk layer veto rate
  - Regime detection accuracy
- [ ] Add structured JSON logging
- [ ] Add strategy performance reports

### 8. Governance Automation
- [ ] Implement automated strategy health checks
- [ ] Add email/Slack notifications for degradation events
- [ ] Add weekly performance report generation
- [ ] Add monthly pool composition review

---

## Migration Path

### v1 → v2 Transition
1. Keep v1 running while developing v2
2. Run v2 in shadow mode (parallel, no live decisions)
3. Compare v1 vs v2 allocation decisions
4. Gradually increase v2's authority
5. Full cutover when v2 is validated

### Rollback Plan
- v1 rule-based policy always available as fallback
- ML policy can be disabled per-strategy
- Risk layer is unchanged (architectural invariant)
- All state changes logged and reversible

---

## Dependencies for v2

### ML Stack
- scikit-learn (or lighter: River for online learning)
- numpy, pandas for feature engineering
- Optional: PyTorch for neural policy (future)

### Infrastructure
- SQLite for persistent state
- Optional: Redis for real-time correlation cache
- Optional: Prometheus + Grafana for monitoring

---

## Timeline Estimate

| Phase | Scope | Estimate |
|-------|-------|----------|
| Persistent state | SQLite + migration | 1 week |
| Correlation matrix | Tracking + allocation cap | 1 week |
| ML policy v1 | Linear model, online learning | 2 weeks |
| Enhanced degradation | Rolling metrics, auto-suspend | 1 week |
| Monitoring | Prometheus + dashboards | 1 week |
| Testing + validation | Shadow mode, A/B comparison | 2 weeks |
| **Total** | | **8 weeks** |