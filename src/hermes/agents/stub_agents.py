"""Real indicator-based market agents for Hermes v2.

Each agent:
  - Consumes MarketState only
  - Produces (score, confidence)
  - Is stateless per cycle
  - Is deterministic (same input → same output)
  - Never references PnL, positions, or strategies

Replaces the original stub agents with library-based indicator math.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import ta

from src.hermes.agents.base import AgentOutput, MarketAgent, MarketState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bars_to_df(bars: list) -> pd.DataFrame:
    """Convert list[Bar] to pandas DataFrame for ta library consumption."""
    return pd.DataFrame({
        "open": [b.open for b in bars],
        "high": [b.high for b in bars],
        "low": [b.low for b in bars],
        "close": [b.close for b in bars],
        "volume": [b.volume for b in bars],
    })


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    """Safe division avoiding zero."""
    return a / b if b != 0 else default


def _clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Agent 1: Ichimoku (Equilibrium / Trend)
# ---------------------------------------------------------------------------

class IchimokuAgent(MarketAgent):
    """Ichimoku Cloud agent using ta.trend.IchimokuIndicator.

    Uses visual=False (default) to avoid look-ahead bias on Senkou spans.
    Requires minimum 52 bars (window3 default).

    Domain: Equilibrium
    Responsibility: trend vs range

    Score: price_vs_cloud + tk_cross alignment, clamped to [-1, +1].
    Confidence: cloud thickness (structural clarity) dominant,
                price alignment secondary. Clamped to [0, 1].
    """

    MIN_BARS = 52

    @property
    def name(self) -> str:
        return "Ichimoku"

    @property
    def domain(self) -> str:
        return "Equilibrium"

    def observe(self, market_state: MarketState) -> dict:
        bars = market_state.bars
        if len(bars) < self.MIN_BARS:
            return {"sufficient_data": False}

        df = _bars_to_df(bars)

        # ta library: visual=False → spans NOT shifted (no look-ahead)
        ich = ta.trend.IchimokuIndicator(
            high=df["high"], low=df["low"],
            window1=9, window2=26, window3=52,
            visual=False,
        )

        # ta v0.11.0 API: conversion_line = Tenkan-sen, base_line = Kijun-sen
        tenkan = ich.ichimoku_conversion_line()
        kijun = ich.ichimoku_base_line()
        span_a = ich.ichimoku_a()
        span_b = ich.ichimoku_b()

        price = df["close"].iloc[-1]
        tk_val = tenkan.iloc[-1]
        kij_val = kijun.iloc[-1]
        sa_val = span_a.iloc[-1]
        sb_val = span_b.iloc[-1]

        cloud_top = max(sa_val, sb_val)
        cloud_bottom = min(sa_val, sb_val)
        cloud_thickness = _safe_div(cloud_top - cloud_bottom, cloud_top, 0.0)

        # Price vs cloud position
        cloud_mid = (cloud_top + cloud_bottom) / 2
        price_vs_cloud = _safe_div(price - cloud_mid, cloud_mid, 0.0)

        # TK cross direction: tenkan above kijun = bullish
        tk_cross = _safe_div(tk_val - kij_val, kij_val, 0.0)

        # Span separation (wider cloud = stronger trend)
        # Use abs() to measure magnitude only — direction is already
        # captured by price_vs_cloud and tk_cross.
        span_sep = abs(_safe_div(sa_val - sb_val, sb_val, 0.0))

        return {
            "sufficient_data": True,
            "price_vs_cloud": price_vs_cloud,
            "tk_cross": tk_cross,
            "cloud_thickness": cloud_thickness,
            "span_sep": span_sep,
        }

    def evaluate(self, observation: dict) -> AgentOutput:
        if not observation.get("sufficient_data", False):
            return AgentOutput(
                agent_name=self.name, score=0.0, confidence=0.0,
                reasoning="Ichimoku: insufficient data",
            )

        pv = observation["price_vs_cloud"]
        tk = observation["tk_cross"]
        ct = observation["cloud_thickness"]

        # Score: price position + TK alignment
        # Price above cloud → positive, below → negative
        # TK cross reinforces
        raw_score = pv * 3 + tk * 2
        score = _clamp(raw_score)

        # Confidence: structural clarity (cloud thickness) dominant,
        # price alignment secondary. Prevents price spikes from
        # inflating confidence during sharp moves.
        alignment = abs(pv)
        confidence = _clamp(ct * 0.6 + alignment * 0.4, 0.0, 1.0)

        return AgentOutput(
            agent_name=self.name,
            score=score,
            confidence=confidence,
            reasoning=(
                f"Ichimoku: price_vs_cloud={pv:.4f}, tk_cross={tk:.4f}, "
                f"cloud_thickness={ct:.4f}"
            ),
        )


# ---------------------------------------------------------------------------
# Agent 2: Volatility (Regime)
# ---------------------------------------------------------------------------

class VolatilityAgent(MarketAgent):
    """Volatility regime agent using ATR and Bollinger Bands.

    ATR for range-based volatility measurement.
    BB width for compression/expansion detection.
    Requires minimum 20 bars.

    Domain: Volatility Regime
    Responsibility: compression vs expansion

    NOTE: score encodes risk regime, NOT price direction.
          Positive score = compression (breakout potential).
          Negative score = expansion (caution).
          This agent functions as a regime breaker, not a directional signal.
    """

    MIN_BARS = 20

    @property
    def name(self) -> str:
        return "Volatility"

    @property
    def domain(self) -> str:
        return "Volatility Regime"

    def observe(self, market_state: MarketState) -> dict:
        bars = market_state.bars
        if len(bars) < self.MIN_BARS:
            return {"sufficient_data": False}

        df = _bars_to_df(bars)

        # ATR (14-period)
        atr = ta.volatility.AverageTrueRange(
            high=df["high"], low=df["low"], close=df["close"], window=14,
        )
        atr_vals = atr.average_true_range()

        # Bollinger Bands (20-period, 2 std)
        bb = ta.volatility.BollingerBands(
            close=df["close"], window=20, window_dev=2,
        )
        bb_width = bb.bollinger_wband()

        # ATR percentile rank (current ATR vs recent history)
        current_atr = atr_vals.iloc[-1]
        recent_atr = atr_vals.iloc[-20:]
        atr_rank = _safe_div(
            (recent_atr < current_atr).sum(), len(recent_atr), 0.5,
        )

        # BB compression: low width = compression
        current_bb_width = bb_width.iloc[-1]
        recent_bb = bb_width.iloc[-20:]
        bb_rank = _safe_div(
            (recent_bb < current_bb_width).sum(), len(recent_bb), 0.5,
        )

        # Compression detection: compare recent avg to earlier avg
        mid = len(atr_vals) // 2
        early_avg = atr_vals.iloc[max(0, mid - 10):mid].mean()
        recent_avg = atr_vals.iloc[mid:].mean()
        compression = _safe_div(early_avg - recent_avg, early_avg, 0.0)

        return {
            "sufficient_data": True,
            "atr_rank": atr_rank,
            "bb_rank": bb_rank,
            "compression": compression,
        }

    def evaluate(self, observation: dict) -> AgentOutput:
        if not observation.get("sufficient_data", False):
            return AgentOutput(
                agent_name=self.name, score=0.0, confidence=0.0,
                reasoning="Volatility: insufficient data",
            )

        atr_rank = observation["atr_rank"]
        bb_rank = observation["bb_rank"]
        compression = observation["compression"]

        # Score: compression → mild bullish (breakout potential)
        # Expansion → cautious
        # Combined from ATR rank + BB rank + raw compression
        vol_signal = (atr_rank + bb_rank) / 2 - 0.5  # [-0.5, +0.5]
        raw_score = compression * 10 - vol_signal  # compression positive
        score = _clamp(raw_score)

        # Confidence: consistency between ATR and BB signals
        consistency = 1.0 - abs(atr_rank - bb_rank)
        confidence = _clamp(consistency * 0.6 + 0.2, 0.0, 1.0)

        return AgentOutput(
            agent_name=self.name,
            score=score,
            confidence=confidence,
            reasoning=(
                f"Volatility: atr_rank={atr_rank:.3f}, bb_rank={bb_rank:.3f}, "
                f"compression={compression:.4f}"
            ),
        )


# ---------------------------------------------------------------------------
# Agent 3: AMT (Auction Market Theory)
# ---------------------------------------------------------------------------

class AMTAgent(MarketAgent):
    """Auction Market Theory agent using value area approximation.

    Approximates Value Area High/Low from OHLC data.
    Conservative output: score capped at ±0.5, confidence capped at 0.5.
    Requires minimum 20 bars.

    Domain: Auction / Value
    Responsibility: balance vs discovery

    NOTE: Value area construction is intentionally crude (range-midpoint based).
          AMT will systematically disagree with trend sensors.
          Low confidence is expected behavior, not noise.
          Do not classify AMT as 'dead weight' without comparing against
          its own domain (balance vs discovery).
    """

    MIN_BARS = 20
    VALUE_AREA_PCT = 0.70  # 70% of range as value area

    @property
    def name(self) -> str:
        return "AMT"

    @property
    def domain(self) -> str:
        return "Auction / Value"

    def observe(self, market_state: MarketState) -> dict:
        bars = market_state.bars
        if len(bars) < self.MIN_BARS:
            return {"sufficient_data": False}

        # Use recent window for value area calculation
        window = bars[-20:]
        highs = np.array([b.high for b in window])
        lows = np.array([b.low for b in window])
        closes = np.array([b.close for b in window])
        volumes = np.array([b.volume for b in window])

        # Approximate POC: price level with highest volume-weighted activity
        # Use mid-price of each bar weighted by volume
        mid_prices = (highs + lows) / 2

        # Value area: centered on range midpoint (simple approximation)
        range_high = highs.max()
        range_low = lows.min()
        total_range = range_high - range_low

        if total_range <= 0:
            return {"sufficient_data": True, "discovery_ratio": 0.0,
                    "balance_ratio": 1.0, "price_position": 0.0}

        va_half = total_range * self.VALUE_AREA_PCT / 2
        range_mid = (range_high + range_low) / 2
        vah = range_mid + va_half
        val = range_mid - va_half

        # Current price position relative to value area
        price = closes[-1]
        if price > vah:
            # Discovery above value
            price_position = (price - vah) / total_range
            discovery_ratio = price_position
            balance_ratio = 0.0
        elif price < val:
            # Discovery below value
            price_position = (val - price) / total_range
            discovery_ratio = price_position
            balance_ratio = 0.0
        else:
            # Inside value area (balance)
            discovery_ratio = 0.0
            price_position = 0.0
            balance_ratio = 1.0 - (vah - price) / (vah - val) if vah != val else 0.5

        # Time outside value: count bars closing outside VA
        outside_count = sum(
            1 for c in closes if c > vah or c < val
        )
        time_outside_ratio = outside_count / len(closes)

        return {
            "sufficient_data": True,
            "discovery_ratio": discovery_ratio,
            "balance_ratio": balance_ratio,
            "price_position": price_position,
            "time_outside": time_outside_ratio,
        }

    def evaluate(self, observation: dict) -> AgentOutput:
        if not observation.get("sufficient_data", False):
            return AgentOutput(
                agent_name=self.name, score=0.0, confidence=0.0,
                reasoning="AMT: insufficient data",
            )

        discovery = observation["discovery_ratio"]
        time_outside = observation["time_outside"]
        price_pos = observation["price_position"]

        # Score: discovery outside value → directional
        # Conservative: capped at ±0.5
        raw_score = price_pos * 2 + time_outside
        score = _clamp(raw_score, -0.5, 0.5)

        # Confidence: conservative cap at 0.5
        confidence = _clamp(
            (discovery + time_outside) * 0.5,
            0.0, 0.5,
        )

        return AgentOutput(
            agent_name=self.name,
            score=score,
            confidence=confidence,
            reasoning=(
                f"AMT: discovery={discovery:.4f}, time_outside={time_outside:.3f}, "
                f"price_pos={price_pos:.4f}"
            ),
        )


# ---------------------------------------------------------------------------
# Agent 4: Wyckoff (Effort vs Result)
# ---------------------------------------------------------------------------

class WyckoffAgent(MarketAgent):
    """Wyckoff effort/result agent using volume-range analysis.

    Measures alignment between volume (effort) and price range (result).
    Absorption = large volume + small range (potential reversal).
    Effortless trend = small volume + large range (strong directional).
    Requires minimum 20 bars.

    Domain: Effort vs Result
    Responsibility: accumulation vs distribution
    """

    MIN_BARS = 20

    @property
    def name(self) -> str:
        return "Wyckoff"

    @property
    def domain(self) -> str:
        return "Effort vs Result"

    def observe(self, market_state: MarketState) -> dict:
        bars = market_state.bars
        if len(bars) < self.MIN_BARS:
            return {"sufficient_data": False}

        df = _bars_to_df(bars)

        # True Range computed manually (no standalone TrueRange in ta v0.11.0)
        high = df["high"]
        low = df["low"]
        close = df["close"]
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)

        volumes = df["volume"]
        closes = df["close"]

        # Split into two halves for comparison
        mid = len(bars) // 2
        first_half = slice(0, mid)
        second_half = slice(mid, None)

        # Average TR (result) per half
        avg_tr_first = tr.iloc[first_half].mean()
        avg_tr_second = tr.iloc[second_half].mean()

        # Average volume (effort) per half
        avg_vol_first = volumes.iloc[first_half].mean()
        avg_vol_second = volumes.iloc[second_half].mean()

        # Effort/result ratio
        # High volume + small range = absorption (potential reversal)
        # Low volume + large range = effortless move
        effort_ratio = _safe_div(avg_vol_second, avg_vol_first, 1.0)
        result_ratio = _safe_div(avg_tr_second, avg_tr_first, 1.0)

        # Direction: close change
        price_change = _safe_div(
            closes.iloc[-1] - closes.iloc[mid],
            closes.iloc[mid], 0.0,
        )

        # Absorption detection: high effort, low result
        absorption = effort_ratio / result_ratio if result_ratio > 0 else effort_ratio

        return {
            "sufficient_data": True,
            "price_change": price_change,
            "effort_ratio": effort_ratio,
            "result_ratio": result_ratio,
            "absorption": absorption,
        }

    def evaluate(self, observation: dict) -> AgentOutput:
        if not observation.get("sufficient_data", False):
            return AgentOutput(
                agent_name=self.name, score=0.0, confidence=0.0,
                reasoning="Wyckoff: insufficient data",
            )

        price_change = observation["price_change"]
        effort = observation["effort_ratio"]
        result = observation["result_ratio"]
        absorption = observation["absorption"]

        # Score: direction * alignment
        # High absorption + positive price → distribution (selling into strength)
        # High absorption + negative price → accumulation (buying into weakness)
        # Low absorption + directional move → trend continuation
        if absorption > 1.5:
            # Absorption present: opposing to price direction
            raw_score = -price_change * absorption * 2
        else:
            # Effort/result aligned: trend continuation
            raw_score = price_change * effort

        score = _clamp(raw_score)

        # Confidence: clarity of effort/result alignment
        # Close to 1.0 = aligned, far from 1.0 = ambiguous
        alignment = 1.0 - min(abs(effort - result) / max(effort, result, 0.01), 1.0)
        confidence = _clamp(alignment * 0.6 + 0.2, 0.0, 1.0)

        return AgentOutput(
            agent_name=self.name,
            score=score,
            confidence=confidence,
            reasoning=(
                f"Wyckoff: price_change={price_change:.4f}, effort={effort:.3f}, "
                f"result={result:.3f}, absorption={absorption:.3f}"
            ),
        )