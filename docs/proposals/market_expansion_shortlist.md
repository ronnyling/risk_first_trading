# Market Expansion Shortlist

## 1. Executive Summary
Following the mandate to use `MarketEligibilityGate` for evaluating additional markets, this document outlines the target shortlist. These markets will be run through the simulation engine using strictly `balanced` and `aggressive` profiles. No parameters will be tuned. 

## 2. Expansion Targets

### Tier 1: Liquidity & Structural Trends (Immediate Testing)
These instruments exhibit similar macro-structural behavior to our whitelist (EUR/USD, ES, NQ, BTC).
*   **Gold (XAU/USD):** Known for massive, persistent structural trends. Will test if the fast `VOLATILE` transitions trigger too many BE exits.
*   **Crude Oil (WTI/USD):** High liquidity, strong directional moves driven by macro supply/demand.
*   **Dow Jones (YM):** Slightly different beta compared to NQ/ES, but highly liquid.
*   **Solana (ETH/SOL or SOL/USD):** To capture crypto beta when BTC dominance drops.

### Tier 2: FX Crosses (Secondary Testing)
*   **AUD/JPY & EUR/JPY:** JPY crosses often provide cleaner trends than USD crosses during Asian and early London sessions.
*   **GBP/JPY:** High volatility, strong stop-run behaviors (excellent test for `LIQUIDITY_SMC`).

## 3. Success Criteria (Fail-Gracefully Protocol)
Each market will be processed through the existing `MarketEligibilityGate.run_sanity_check()`:
1.  **Profit Factor Target:** $\ge 0.9$
2.  **Max Drawdown Cap:** $\le 10\%$
3.  If PF is between $0.8$ and $0.9$ but DD is $\le 5\%$, the market will be allowed (it fails gracefully in chop without burning capital).
4.  If DD exceeds $10\%$ or PF falls below $0.5$, it will be permanently added to the `blacklist`.