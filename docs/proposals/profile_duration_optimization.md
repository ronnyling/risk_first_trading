# Profile Duration & Optimization Proposal

## 1. Executive Summary
This proposal refines the temporal thresholds and state-transition requirements for the Hermes Trading System's profile state machine. The goal is to maximize time spent in the `balanced` state while creating an asymmetric, quick-downgrade logic for the `aggressive` state to protect alpha.

## 2. Transition Rule Refinements

### A. Maximizing `balanced` State Duration
Currently, the system transitions to `aggressive` after 30 trades of high performance. This is too eager.
*   **Proposed Rule:** Require a minimum of **40 active trading days** (approx. 2 months) in `balanced` before an upgrade to `aggressive` can even be considered, regardless of the Profit Factor in the last 30 trades.
*   **Rationale:** The `balanced` profile banks 50% partials at ~0.9R, producing an incredibly smooth equity curve. Lingering here longer guarantees that the account buffer is massively robust before attempting to ride full runners.

### B. Strict Gating for `aggressive` Entry
The current rule states "Market regime predominantly TRENDING on HTF".
*   **Proposed Refinement:** Require `TRENDING` on HTF *AND* a verified `GROWTH` state on the drawdown ladder for at least 5 consecutive days.
*   **Rationale:** Aggressive trailing requires exceptionally clean structures. If the ladder dips into `PROTECTIVE` even once, the market is likely becoming choppy. 

### C. Asymmetric Downgrade (`aggressive` -> `balanced`)
We want to upgrade slowly but downgrade violently.
*   **Proposed Rule (Fast Downgrade):** 
    1. If a single trade hits the full 1R stop-loss (i.e., fails to hit the trailing activation trigger) while in `aggressive`, instantly downgrade to `balanced`.
    2. If the HTF regime shifts to `VOLATILE` or `RANGING` for more than 2 consecutive hours, instantly downgrade to `balanced`.
*   **Rationale:** Aggressive extraction only works when trades immediately run. A full 1R loss indicates structure is breaking down. Downgrading immediately saves capital, letting `balanced` handle the chop with its partial TPs.