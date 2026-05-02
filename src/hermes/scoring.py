"""ScoringEngine - pure math, stateless. No thresholds, no decisions."""

from __future__ import annotations

import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class ScoringResult:
    """Result of aggregating agent outputs."""
    composite_score: float
    total_confidence: float
    score_dispersion: float


class ScoringEngine:
    """Aggregates agent scores into composite metrics.

    This module performs ONLY math. It contains no thresholds,
    no decision logic, and no regime classification.

    composite_score = sum(score_i * confidence_i)
    total_confidence = mean(confidence_i)
    score_dispersion = stdev(score_i)
    """

    def compute(
        self,
        scores: list[float],
        confidences: list[float],
    ) -> ScoringResult:
        """Compute composite metrics from agent outputs.

        Args:
            scores: list of agent scores, each in [-1.0, +1.0]
            confidences: list of agent confidences, each in [0.0, 1.0]

        Returns:
            ScoringResult with composite_score, total_confidence, score_dispersion
        """
        if not scores:
            return ScoringResult(
                composite_score=0.0,
                total_confidence=0.0,
                score_dispersion=0.0,
            )

        n = len(scores)

        # Weighted composite normalized by total confidence
        # composite = sum(s_i * c_i) / sum(c_i) to bound result to [-1.0, +1.0]
        weighted_sum = sum(s * c for s, c in zip(scores, confidences))
        total_confidence = sum(confidences)
        composite_score = weighted_sum / total_confidence if total_confidence > 0 else 0.0

        # Mean confidence
        mean_confidence = total_confidence / n

        # Score dispersion (stdev)
        if n >= 2:
            score_dispersion = statistics.stdev(scores)
        else:
            score_dispersion = 0.0

        return ScoringResult(
            composite_score=composite_score,
            total_confidence=mean_confidence,
            score_dispersion=score_dispersion,
        )