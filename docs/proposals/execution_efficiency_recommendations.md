# Execution Efficiency Recommendations

## 1. Executive Summary
This document reviews the execution mechanics (specifically interacting with IB and the Mock Broker) and proposes optimizations to order types, throttling, and slippage controls to squeeze fractional R-multiples out of the existing trading logic.

## 2. Order Type Optimization
Currently, the system defaults heavily to Market orders upon signal generation at the close of the bar.
*   **Recommendation for `LIQUIDITY_SMC` (Stop-Run Fade):** 
    Instead of entering via market order at the close of the failure bar, submit a **Limit Order** at the broken swing high/low. Because the strategy fades a false breakout, price frequently re-tests the boundary. This saves significant slippage and improves the RR ratio.
*   **Recommendation for `STRUCTURAL_FRACTAL`:**
    Continue using Market Orders for entry to guarantee participation in momentum. However, trailing stops must be held locally in memory and submitted as **Stop-Market** orders to the broker only when triggered, hiding intent from the book.

## 3. Throttling and Re-entry Control
*   **Issue:** Rapid consecutive signals on lower timeframes (e.g., executing multiple 1m breakout signals in a chopping range).
*   **Recommendation:** Implement a hard cooldown timer at the orchestration layer. Once a position is closed, the system must wait a minimum of **3 execution bars** (e.g., 15 minutes on a 5m exec chart) before re-entering the same ticker in the same direction.

## 4. Slippage and Spread Guards
*   **Issue:** News events or low-liquidity rollover periods can cause massive spread expansion, turning a 1R risk into a 1.5R realized loss.
*   **Recommendation:** Implement a dynamic spread check via the data feed. If `(ask - bid) > (ATR * 0.1)`, the execution engine must reject the Hermes signal and log a "Spread Too Wide" veto. This mathematically protects the expectancy of the `balanced` and `aggressive` models from execution degradation.