# Capital Allocation Policy Proposal

## 1. Executive Summary
This policy defines a deterministic, profile-driven capital allocation model for the Hermes Trading System. Rather than scaling risk per trade (which is handled intrinsically by the ladder), this policy dictates the *total deployable account equity* assigned to the execution engine based on its current operational profile.

## 2. Allocation Framework
Allocation is strictly coupled to the `ProfileTransitionGate` states. 

### A. Minimal Capital Allocation (`ftmo_safe`, `ftmo_safe_plus`)
*   **Purpose:** Evaluation survival and post-pass bridge validation.
*   **Total Equity Allocation:** **10%** of total liquid account equity.
*   **Rationale:** The objective here is edge validation and capital protection. Drawdowns on 10% equity ensure minimal real-dollar risk while passing funding criteria.

### B. Core Capital Allocation (`conservative`, `balanced`)
*   **Purpose:** Smooth compounding and low-variance growth.
*   **Total Equity Allocation:** **60%** of total liquid account equity.
*   **Rationale:** `balanced` is the core workhorse of Hermes. It captures the vast majority of steady trend movements and mean-reversion bounces. Assigning the bulk of capital here maximizes edge without exposing the entire book to aggressive drawdowns.

### C. Conditional Capped Capital (`aggressive`)
*   **Purpose:** Alpha extraction, right-tail capture during strong regimes.
*   **Total Equity Allocation:** **30%** of total liquid account equity.
*   **Rationale:** Aggressive trailing logic results in lower win rates but massive right-tail payouts. Capping this allocation at 30% prevents the inevitable string of break-even/small-loss trades (which occur while hunting runners) from excessively dragging the total portfolio equity.

## 3. Auditing and Enforcement
*   Allocation limits must be injected at the `ExecutionEngine` initialization level.
*   When a profile transition occurs via the `ProfileTransitionGate`, a callback must adjust the `max_portfolio_equity` variable within the broker adapter.
*   Reallocation happens only when all open positions are flat, preventing margin calls or partial liquidations during active trades.