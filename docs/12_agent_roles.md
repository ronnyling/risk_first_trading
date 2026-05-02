# Hermes v2 Agent Roles — Formalized

**Status:** Documentation only — no logic changes
**Date:** 2026-04-29

## Purpose

Make implicit agent roles explicit before any experimentation. Prevents semantic drift and makes future weighting/gating decisions auditable.

## Agent Registry

| Agent | Domain | Role | Confidence Range | MIN_BARS |
|-------|--------|------|-----------------|----------|
| IchimokuAgent | Equilibrium | Structural regime detector | 0.0 – 1.0 | 52 |
| WyckoffAgent | Effort vs Result | Intent confirmation | 0.0 – ~0.8 | 20 |
| VolatilityAgent | Volatility Regime | Risk breaker / uncertainty detector | 0.0 – ~0.8 | 20 |
| AMTAgent | Auction / Value | Discovery validator | 0.0 – **0.5 (hard cap)** | 20 |

---

## Agent-by-Agent Specification

### IchimokuAgent — Structural Regime Detector

**Intended Role:** Determines whether the market is in trend or equilibrium (range).

**Mechanism:**
- Price position relative to Ichimoku cloud (above = bullish, below = bearish)
- Tenkan/Kijun cross direction (TK cross reinforces trend)
- Cloud thickness (thicker = stronger trend signal)

**Score semantics:**
- Positive = price above cloud, TK bullish → trending up
- Negative = price below cloud, TK bearish → trending down
- Near zero = price inside cloud → range/equilibrium

**Confidence semantics:**
- Scales with cloud clarity (thickness) + price alignment strength
- High confidence = clear cloud position + strong TK alignment
- Low confidence = price inside cloud or ambiguous TK cross

**Expected behavior:**
- Should be the primary regime classifier
- May disagree with Wyckoff on direction (intentional — different domain)
- 52-bar warmup means it is silent/zero for early bars

**Why this matters:** Ichimoku is the only agent with a 52-bar warmup. During warmup, it outputs score=0, confidence=0, which drags composite confidence down and can trigger R-02.

---

### WyckoffAgent — Intent Confirmation

**Intended Role:** Confirms whether price movement is supported by volume (effort) or is unconvincing (result without effort).

**Mechanism:**
- Splits bar history into two halves
- Compares average volume (effort) and average true range (result) between halves
- Detects absorption (high volume + small range = potential reversal)

**Score semantics:**
- Absorption present (effort/result > 1.5): contrarian signal (opposing price direction)
- Effort/result aligned: trend continuation signal
- Score direction = interpreted market direction

**Confidence semantics:**
- Scales with effort/result alignment clarity
- Max ~0.8 (alignment × 0.6 + 0.2)
- High confidence = clean effort/result match
- Low confidence = ambiguous volume/range relationship

**Expected behavior:**
- Often aligns with Ichimoku on trend direction
- May produce contrarian signals during absorption events
- Structural ceiling of ~0.8 confidence

---

### VolatilityAgent — Risk Breaker / Uncertainty Detector

**Intended Role:** Detects volatility regime transitions (compression → expansion, or vice versa).

**Mechanism:**
- ATR percentile rank (current ATR vs recent history)
- Bollinger Band width rank (expansion vs compression)
- Raw compression metric (early vs recent ATR average)

**Score semantics:**
- Compression → mild bullish (breakout potential)
- Expansion → cautious (volatility = risk)
- Combined from ATR rank, BB rank, and raw compression

**Confidence semantics:**
- Scales with ATR/BB consistency (how aligned are the two signals)
- Max ~0.8 (consistency × 0.6 + 0.2)
- High confidence = ATR and BB agree on regime
- Low confidence = ATR and BB disagree

**Expected behavior:**
- Often the primary conflict driver (different domain than trend agents)
- May disagree with Ichimoku/Wyckoff on direction (intentional — measures volatility, not direction)
- Structural ceiling of ~0.8 confidence

**Why this matters:** VolatilityAgent is the "risk breaker." Its role is to detect uncertainty, so disagreement with trend agents is by design, not pathology.

---

### AMTAgent — Discovery Validator

**Intended Role:** Determines whether price is in value area (balance) or discovering new prices outside value (discovery phase).

**Mechanism:**
- Approximates Value Area High/Low from OHLC data
- Measures price position relative to value area
- Counts time spent outside value area

**Score semantics:**
- Discovery above value → positive (upward discovery)
- Discovery below value → negative (downward discovery)
- Inside value area → near zero (balance)
- **Hard-capped at ±0.5** (conservative design)

**Confidence semantics:**
- **Hard-capped at 0.5** (conservative design: `(discovery + time_outside) × 0.5`)
- This is the lowest confidence ceiling of any agent
- Intentionally conservative: AMT approximates value area from OHLC only (no tick data)

**Expected behavior:**
- Should rarely be the strongest directional signal
- Acts as a validator: confirms or denies discovery phase
- **Structural confidence ceiling at 0.5 is the primary driver of low composite confidence**

**Critical structural observation:** AMTAgent's confidence cap of 0.5 means it can never contribute more than 0.5 to the mean confidence calculation. With 4 agents, this creates a structural ceiling on `total_confidence` that makes R-02 (total_confidence < 0.5) fire on nearly every bar.

---

## Interaction Patterns

### Healthy Alignment (Expected)
- Ichimoku + Wyckoff agree on direction → high composite score
- VolatilityAgent confirms low volatility → confidence rises
- AMTAgent confirms discovery → validates direction

### Healthy Disagreement (Expected)
- VolatilityAgent disagrees with trend agents → uncertainty detected
- Wyckoff detects absorption → contrarian signal vs Ichimoku
- These are different domains measuring different things

### Pathological Pattern (Structural)
- AMT confidence cap (0.5) drags mean confidence below R-02 threshold (0.5)
- R-02 fires → SCALE_DOWN regardless of other agents' confidence
- FULL can never appear even when Ichimoku + Wyckoff + Volatility agree

---

## Key Structural Constraints

1. **AMTAgent confidence ceiling (0.5)** — lowest of any agent, drags composite down
2. **WyckoffAgent confidence ceiling (~0.8)** — `alignment × 0.6 + 0.2` formula
3. **VolatilityAgent confidence ceiling (~0.8)** — same formula structure
4. **IchimokuAgent 52-bar warmup** — zero confidence during warmup period
5. **R-02 threshold (0.5)** — mean confidence must exceed 0.5 to avoid SCALE_DOWN
6. **R-01 threshold (0.60)** — score dispersion must stay below 0.60 to avoid CASH

These constraints interact: with AMT capped at 0.5 and three agents typically producing 0.3-0.6 confidence, the mean rarely exceeds 0.5 → R-02 fires → FULL never appears.