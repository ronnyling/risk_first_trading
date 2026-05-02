# Profitability Phase Mandate (Orchestration & Deployment)

## P1: Capital Allocation Policy
*   **ftmo_safe / ftmo_safe_plus:** Allocate minimal capital (evaluation/survival mode).
*   **balanced:** Allocate core capital (smooth compounding, low variance). ~60% allocation.
*   **aggressive:** Allocate conditional, capped capital (right-tail capture, alpha extraction). ~30% max allocation.
*   *Implementation:* See `src/operations/capital_scaling.py`

## P2: Time-in-Profile Optimization
*   **Remain longer in balanced:** Maximize time spent in the core compounding state. Evaluated strictly by `ProfileTransitionGate`.
*   **Gate aggressive entry:** Enter only during strong HTF TRENDING regimes (`htf_regime_trending_ratio > 0.6`).
*   **Asymmetric downgrade:** Downgrade from `aggressive` to `balanced` faster than the upgrade path (protect alpha extraction gains). Triggered on slight DD or regime decay.
*   *Implementation:* See `src/operations/profile_transitions.py`

## P3: Market Breadth Expansion
*   Admit markets only if they fail gracefully under `balanced` and `aggressive` profiles.
*   Uses `MarketEligibilityGate` for sanity checking without parameter tuning.
*   Shortlist evaluated by Hermes Agentic (external submodule: `external/hermes-agentic/`).
*   Data contracts for parsing Hermes outputs are in `src/hermes/agentic_models.py`.
*   *Implementation:* See `src/operations/market_eligibility.py`

## P4: Execution Efficiency
*   Review IB execution patterns and propose improvements.
*   Evaluate order types (e.g., limit vs. market on breakout/fade).
*   Implement throttling controls via `ExecutionGuards` (`check_cooldown`, `check_spread`).
*   *Implementation:* See `src/execution/guards.py`
