"""EdgeAnalyzer — produces a BreadthAuditReport from analytics + correlation data.

Phase A of the continuous breadth expansion workflow.
Uses existing AnalyticsEngine and CorrelationEngine to answer factual questions
about where edge exists in the current universe.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime

from src.analytics.engine import AnalyticsEngine
from src.analytics.models import HermesReport, StrategyReport
from src.hermes.correlation import CorrelationEngine, CorrelationMatrix
from src.operations.scaling import ScalingConfig
from src.operations.universe_reader import UniverseReader
from src.persistence.db import PersistenceDB

from src.breadth.models import (
    BreadthAuditReport,
    ConfidenceBucket,
    CorrelationCluster,
    StrategyRegimeExpectancy,
)

logger = logging.getLogger(__name__)


class EdgeAnalyzer:
    """Produces a BreadthAuditReport from analytics + correlation data.

    Runs AnalyticsEngine queries and CorrelationEngine to compute:
    - Strategy × regime expectancy
    - Confidence bucket PnL distribution
    - Correlation clusters (connected components)
    - Diversifying vs redundant symbol identification

    Usage:
        analyzer = EdgeAnalyzer()
        report = analyzer.run_audit()
    """

    def __init__(
        self,
        analytics: AnalyticsEngine | None = None,
        correlation_engine: CorrelationEngine | None = None,
        scaling_config: ScalingConfig | None = None,
        universe_reader: UniverseReader | None = None,
        db: PersistenceDB | None = None,
    ) -> None:
        self._analytics = analytics or AnalyticsEngine()
        self._correlation_engine = correlation_engine or CorrelationEngine()
        self._scaling = scaling_config or ScalingConfig()
        self._universe = universe_reader or UniverseReader()
        self._db = db or PersistenceDB()

    def run_audit(self) -> BreadthAuditReport:
        """Execute the full breadth audit.

        Steps:
        1. Load current universe symbols
        2. Compute strategy × regime expectancy from fills + hermes_runs
        3. Compute confidence bucket PnL distribution
        4. Compute correlation matrix on current universe
        5. Extract correlation clusters (connected components)
        6. Identify positive-edge strategies
        7. Identify diversifying vs redundant symbols
        8. Package into BreadthAuditReport
        """
        profile = self._scaling.load_active_profile()
        current_symbols = self._universe.get_enabled_markets()

        # Step 2: Strategy × regime expectancy
        strategy_report = self._analytics.strategy_performance()
        hermes_report = self._analytics.hermes_outcomes()
        strategy_regime_expectancy = self._compute_strategy_regime_expectancy(
            strategy_report, hermes_report
        )

        # Step 3: Confidence buckets
        confidence_buckets = self._compute_confidence_buckets(hermes_report)

        # Step 4: Correlation matrix (using bar data from persistence or live)
        # For the audit, we compute correlation from available market states
        # If no live data available, we use an empty matrix
        correlation = self._compute_correlation_for_audit(current_symbols)

        # Step 5: Correlation clusters
        correlation_clusters = self._extract_correlation_clusters(correlation)

        # Step 6: Positive-edge strategies
        positive_edge = [
            s.strategy_id
            for s in strategy_regime_expectancy
            if s.expectancy > 0 and s.total_trades >= 3
        ]

        # Step 7: Diversifying vs redundant symbols
        diversifying = self._identify_diversifying_symbols(
            correlation_clusters, current_symbols
        )
        redundant = self._identify_redundant_symbols(
            correlation_clusters, current_symbols
        )

        # Compute data points used
        data_points = (
            strategy_report.total_trades
            + hermes_report.total_decisions
            + correlation.pair_count
        )

        report = BreadthAuditReport(
            strategy_regime_expectancy=strategy_regime_expectancy,
            confidence_buckets=confidence_buckets,
            correlation_clusters=correlation_clusters,
            high_correlation_pairs=correlation.high_pairs,
            correlation_summary=correlation.summary(),
            current_symbols=current_symbols,
            current_scaling_profile=profile.name,
            positive_edge_strategies=positive_edge,
            diversifying_symbols=diversifying,
            redundant_symbols=redundant,
            computed_at=datetime.now().isoformat(),
            data_points_used=data_points,
        )

        # Persist the report
        try:
            self._db.record_breadth_audit(report)
        except Exception as e:
            logger.warning("Failed to persist breadth audit: %s", e)

        logger.info(
            "Breadth audit complete: %d symbols, %d positive-edge strategies, "
            "%d diversifying, %d redundant",
            len(current_symbols),
            len(positive_edge),
            len(diversifying),
            len(redundant),
        )

        return report

    def _compute_strategy_regime_expectancy(
        self,
        strategy_report: StrategyReport,
        hermes_report: HermesReport,
    ) -> list[StrategyRegimeExpectancy]:
        """Compute expectancy per strategy per regime.

        Cross-references strategy performance with Hermes regime data.
        When regime-level granularity is unavailable, uses aggregate stats.
        """
        result: list[StrategyRegimeExpectancy] = []

        if strategy_report.total_trades == 0:
            return result

        # Build regime distribution from hermes report
        regime_dist = hermes_report.regime_distribution
        total_hermes_decisions = hermes_report.total_decisions

        if total_hermes_decisions == 0:
            # No Hermes data — use aggregate strategy stats with "UNKNOWN" regime
            wins = strategy_report.winning_trades
            losses = strategy_report.losing_trades
            total = strategy_report.total_trades
            win_rate = strategy_report.win_rate
            avg_pnl = strategy_report.avg_trade_pnl

            # Compute expectancy
            avg_win = (
                sum(f.pnl for f in strategy_report.fill_history if f.pnl > 0) / wins
                if wins > 0
                else 0.0
            )
            avg_loss = (
                abs(
                    sum(f.pnl for f in strategy_report.fill_history if f.pnl <= 0)
                )
                / losses
                if losses > 0
                else 0.0
            )
            expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

            result.append(
                StrategyRegimeExpectancy(
                    strategy_id=strategy_report.strategy_id,
                    regime="UNKNOWN",
                    total_trades=total,
                    win_rate=win_rate,
                    avg_pnl=avg_pnl,
                    expectancy=expectancy,
                )
            )
        else:
            # Distribute strategy stats across regimes proportionally
            for regime, count in regime_dist.items():
                regime_fraction = count / total_hermes_decisions
                regime_trades = max(1, int(strategy_report.total_trades * regime_fraction))

                win_rate = strategy_report.win_rate
                avg_pnl = strategy_report.avg_trade_pnl

                # Estimate expectancy using overall stats (regime-specific
                # granularity requires per-regime fill data which isn't available)
                avg_win = (
                    sum(
                        f.pnl
                        for f in strategy_report.fill_history
                        if f.pnl > 0
                    )
                    / max(1, strategy_report.winning_trades)
                )
                avg_loss = (
                    abs(
                        sum(
                            f.pnl
                            for f in strategy_report.fill_history
                            if f.pnl <= 0
                        )
                    )
                    / max(1, strategy_report.losing_trades)
                )
                expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

                result.append(
                    StrategyRegimeExpectancy(
                        strategy_id=strategy_report.strategy_id,
                        regime=regime,
                        total_trades=regime_trades,
                        win_rate=win_rate,
                        avg_pnl=avg_pnl,
                        expectancy=expectancy,
                    )
                )

        return result

    def _compute_confidence_buckets(
        self, hermes_report: HermesReport
    ) -> list[ConfidenceBucket]:
        """Bucket decisions by confidence range and compute PnL stats.

        Buckets: 0.0-0.2, 0.2-0.4, 0.4-0.6, 0.6-0.8, 0.8-1.0
        """
        # Hermes report has aggregate stats but not per-decision PnL.
        # We use the directive distribution and high_confidence_trades count
        # to build approximate buckets.
        buckets: list[ConfidenceBucket] = []

        total_decisions = hermes_report.total_decisions
        if total_decisions == 0:
            return buckets

        # Build buckets from available data
        avg_conf = hermes_report.avg_confidence
        high_conf = hermes_report.high_confidence_trades

        # Estimate distribution: high_conf (>0.7) vs rest
        low_conf_count = total_decisions - high_conf

        if low_conf_count > 0:
            buckets.append(
                ConfidenceBucket(
                    bucket_label="0.0-0.7",
                    trade_count=low_conf_count,
                    avg_pnl=0.0,  # No per-bucket PnL available
                    total_pnl=0.0,
                    win_rate=0.0,
                )
            )

        if high_conf > 0:
            buckets.append(
                ConfidenceBucket(
                    bucket_label="0.7-1.0",
                    trade_count=high_conf,
                    avg_pnl=0.0,
                    total_pnl=0.0,
                    win_rate=0.0,
                )
            )

        return buckets

    def _compute_correlation_for_audit(
        self, symbols: list[str]
    ) -> CorrelationMatrix:
        """Compute correlation matrix for the audit.

        If no live market states are available, returns an empty matrix.
        The full correlation computation requires bar data from streaming
        or snapshot mode.
        """
        # For the audit, we attempt to build market states from the universe
        # In production, this would use live data from StreamFetcher or snapshot
        try:
            from src.market.live_data import fetch_bars
            from src.hermes.agents.base import Bar, MarketState

            market_states = []
            for symbol in symbols:
                try:
                    bars = fetch_bars(symbol, count=200, interval="1h")
                    if bars and len(bars) >= 20:
                        ms = MarketState(
                            symbol=symbol,
                            bars=bars,
                            timestamp=bars[-1].timestamp if bars else datetime.now(),
                            regime="UNKNOWN",
                        )
                        market_states.append(ms)
                except Exception:
                    logger.debug("Could not fetch bars for %s during audit", symbol)
                    continue

            if len(market_states) >= 2:
                return self._correlation_engine.compute(market_states)
        except Exception as e:
            logger.debug("Correlation computation skipped during audit: %s", e)

        # Return empty matrix if computation not possible
        return CorrelationMatrix(
            symbols=symbols,
            matrix={},
            high_pairs=[],
            computed_at=datetime.now(),
        )

    def _extract_correlation_clusters(
        self, matrix: CorrelationMatrix
    ) -> list[CorrelationCluster]:
        """Extract connected components from high_correlation_pairs.

        Uses Union-Find to group symbols into clusters where
        each pair has |r| > threshold.
        """
        if not matrix.high_pairs:
            # Each symbol is its own cluster
            return [
                CorrelationCluster(
                    cluster_id=i,
                    symbols=[sym],
                    avg_internal_correlation=0.0,
                )
                for i, sym in enumerate(matrix.symbols)
            ]

        # Union-Find
        parent: dict[str, str] = {s: s for s in matrix.symbols}

        def find(x: str) -> str:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: str, y: str) -> None:
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        # Union highly correlated pairs
        for sym_a, sym_b, _ in matrix.high_pairs:
            union(sym_a, sym_b)

        # Group by root
        groups: dict[str, list[str]] = defaultdict(list)
        for sym in matrix.symbols:
            groups[find(sym)].append(sym)

        # Build clusters
        clusters: list[CorrelationCluster] = []
        for idx, (root, members) in enumerate(sorted(groups.items())):
            # Compute average internal correlation
            internal_corrs: list[float] = []
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    corr = matrix.get(members[i], members[j])
                    if corr != 0.0:  # Skip unknown correlations
                        internal_corrs.append(abs(corr))

            avg_corr = (
                sum(internal_corrs) / len(internal_corrs)
                if internal_corrs
                else 0.0
            )

            clusters.append(
                CorrelationCluster(
                    cluster_id=idx,
                    symbols=members,
                    avg_internal_correlation=avg_corr,
                )
            )

        return clusters

    def _identify_diversifying_symbols(
        self,
        clusters: list[CorrelationCluster],
        all_symbols: list[str],
    ) -> list[str]:
        """Symbols not in any multi-symbol cluster are diversifying.

        A single-symbol cluster means the symbol has no high-correlation
        peers in the current universe — it's a diversifier.
        """
        diversifying: list[str] = []
        for cluster in clusters:
            if len(cluster.symbols) == 1:
                diversifying.extend(cluster.symbols)
        return diversifying

    def _identify_redundant_symbols(
        self,
        clusters: list[CorrelationCluster],
        all_symbols: list[str],
    ) -> list[str]:
        """Symbols in oversized clusters (3+) are flagged as redundant.

        In a 3+ symbol cluster, all members are highly correlated,
        meaning they provide redundant exposure.
        """
        redundant: list[str] = []
        for cluster in clusters:
            if len(cluster.symbols) >= 3:
                redundant.extend(cluster.symbols)
        return redundant
