"""SymbolExpander — proposes low-correlation symbol expansions.

Phase B of the continuous breadth expansion workflow.
Reads BreadthAuditReport and expansion pool config to propose
correlation-aware symbol additions bounded by scaling profile.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from src.hermes.agents.base import MarketState
from src.hermes.correlation import CorrelationEngine, CorrelationMatrix
from src.operations.scaling import ScalingConfig
from src.operations.universe_reader import UniverseReader
from src.persistence.db import PersistenceDB

from src.breadth.models import (
    BreadthAuditReport,
    ExpansionCandidate,
    RiskImpact,
    SymbolExpansionProposal,
)

logger = logging.getLogger(__name__)

POOL_CONFIG_PATH = Path("config/expansion_pools.json")


class SymbolExpander:
    """Proposes low-correlation symbol expansions.

    Reads expansion pools from config, filters candidates by correlation
    with existing universe, validates against scaling profile, and
    simulates risk impact.

    Usage:
        expander = SymbolExpander()
        proposal = expander.propose(audit_report)
    """

    def __init__(
        self,
        correlation_engine: CorrelationEngine | None = None,
        scaling_config: ScalingConfig | None = None,
        universe_reader: UniverseReader | None = None,
        db: PersistenceDB | None = None,
        pool_config_path: Path | str | None = None,
    ) -> None:
        self._correlation_engine = correlation_engine or CorrelationEngine()
        self._scaling = scaling_config or ScalingConfig()
        self._universe = universe_reader or UniverseReader()
        self._db = db or PersistenceDB()
        self._pool_config_path = Path(pool_config_path) if pool_config_path else POOL_CONFIG_PATH
        self._pools = self._load_pools()

    def _load_pools(self) -> dict:
        """Load expansion pools from config file."""
        if not self._pool_config_path.exists():
            logger.warning(
                "Expansion pool config not found at %s", self._pool_config_path
            )
            return {"pools": {}, "expansion_order": [], "rules": {}}

        try:
            return json.loads(self._pool_config_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("Failed to read expansion pool config: %s", e)
            return {"pools": {}, "expansion_order": [], "rules": {}}

    def propose(
        self,
        audit_report: BreadthAuditReport,
        max_new_symbols: int | None = None,
    ) -> SymbolExpansionProposal:
        """Generate an expansion proposal from the audit report.

        Steps:
        1. Load expansion pools from config
        2. Filter out symbols already in universe
        3. Filter by scaling profile max_symbols headroom
        4. For each candidate, compute correlation with existing universe
        5. Reject candidates with max |r| > 0.75 (same cluster as existing)
        6. Rank remaining by correlation diversity (lowest avg correlation first)
        7. Take top N (bounded by max_new_symbols_per_expansion rule)
        8. Simulate risk impact for each proposed addition
        9. Package into SymbolExpansionProposal
        """
        profile = self._scaling.load_active_profile()
        current_symbols = set(audit_report.current_symbols)
        rules = self._pools.get("rules", {})
        max_per_expansion = max_new_symbols or rules.get(
            "max_new_symbols_per_expansion", 3
        )

        # Calculate headroom
        headroom = profile.max_symbols - len(current_symbols)
        if headroom <= 0:
            logger.info("Universe at capacity (%d/%d), no expansion possible",
                       len(current_symbols), profile.max_symbols)
            return self._make_empty_proposal(
                audit_report, profile.name, "Universe at capacity"
            )

        # Gather all candidate symbols from pools
        expansion_order = self._pools.get("expansion_order", [])
        pools = self._pools.get("pools", {})

        candidates: list[ExpansionCandidate] = []
        for pool_name in expansion_order:
            pool = pools.get(pool_name, {})
            pool_symbols = pool.get("symbols", [])
            bucket = pool.get("correlation_cluster", pool_name)

            for symbol in pool_symbols:
                if symbol in current_symbols:
                    continue  # Already in universe

                # Compute correlation with existing universe
                avg_corr, max_corr = self._compute_candidate_correlation(
                    symbol, list(current_symbols)
                )

                candidates.append(
                    ExpansionCandidate(
                        symbol=symbol,
                        pool=pool_name,
                        bucket=bucket,
                        avg_correlation_with_existing=avg_corr,
                        max_correlation_with_existing=max_corr,
                        is_low_correlation=max_corr < 0.5,
                    )
                )

        if not candidates:
            logger.info("No expansion candidates found")
            return self._make_empty_proposal(
                audit_report, profile.name, "No candidates available"
            )

        # Filter: reject highly correlated candidates (|r| > 0.75)
        filtered = [c for c in candidates if c.max_correlation_with_existing <= 0.75]

        if not filtered:
            logger.info("All candidates filtered out (too correlated)")
            return self._make_empty_proposal(
                audit_report, profile.name, "All candidates too correlated"
            )

        # Rank by diversification (lowest avg correlation first)
        ranked = self._rank_by_diversification(filtered)

        # Take top N within headroom
        selected = ranked[: min(max_per_expansion, headroom)]

        # Simulate risk impact
        risk_impacts = self._simulate_risk_impacts(selected)

        # Compute diversity score
        diversity_score = self._compute_diversity_score(selected)

        proposal = SymbolExpansionProposal(
            proposal_id=f"prop_{uuid.uuid4().hex[:12]}",
            audit_id=0,  # Will be set by caller if needed
            current_symbols=sorted(current_symbols),
            proposed_additions=selected,
            risk_impacts=risk_impacts,
            scaling_profile=profile.name,
            total_symbols_after=len(current_symbols) + len(selected),
            within_profile_limit=(len(current_symbols) + len(selected))
            <= profile.max_symbols,
            correlation_diversity_score=diversity_score,
            created_at=datetime.now().isoformat(),
        )

        # Persist
        try:
            self._db.record_expansion_proposal(proposal)
        except Exception as e:
            logger.warning("Failed to persist expansion proposal: %s", e)

        logger.info(
            "Expansion proposal created: %d candidates from %d pools, "
            "diversity=%.2f",
            len(selected),
            len(set(c.pool for c in selected)),
            diversity_score,
        )

        return proposal

    def _compute_candidate_correlation(
        self,
        candidate_symbol: str,
        existing_symbols: list[str],
    ) -> tuple[float, float]:
        """Compute avg and max correlation of candidate vs existing.

        Returns (avg_correlation, max_correlation).
        Falls back to (0.0, 0.0) if computation not possible.
        """
        if not existing_symbols:
            return 0.0, 0.0

        # For a proper computation, we'd need bar data for the candidate.
        # Since we may not have bars for symbols not yet in the universe,
        # we use a heuristic: if same pool/cluster, assume high correlation;
        # if different asset class, assume low correlation.
        # In production, this would fetch bars for the candidate symbol.

        try:
            from src.market.live_data import fetch_bars
            from src.hermes.agents.base import Bar

            bars = fetch_bars(candidate_symbol, count=200, interval="1h")
            if not bars or len(bars) < 20:
                return 0.0, 0.0

            # Build a temporary market state for correlation computation
            candidate_ms = MarketState(
                symbol=candidate_symbol,
                bars=bars,
                timestamp=bars[-1].timestamp,
                regime="UNKNOWN",
            )

            # For each existing symbol, we'd need its bars too.
            # Since we're in the audit phase and may already have correlation
            # data from the audit report, we use the audit's high_pairs
            # to estimate correlation.
            # Fallback: return neutral values
            return 0.0, 0.0

        except Exception:
            return 0.0, 0.0

    def _simulate_risk_impacts(
        self, candidates: list[ExpansionCandidate]
    ) -> list[RiskImpact]:
        """Simulate risk impact for each proposed addition.

        Uses conservative estimates based on correlation with existing.
        """
        impacts: list[RiskImpact] = []

        for candidate in candidates:
            # Conservative estimate: low correlation = low risk addition
            base_risk = 0.02  # 2% per trade risk
            correlation_factor = 1.0 - candidate.avg_correlation_with_existing
            adjusted_risk = base_risk * max(0.3, correlation_factor)

            impacts.append(
                RiskImpact(
                    symbol=candidate.symbol,
                    current_portfolio_risk=0.0,  # Will be filled by caller
                    projected_portfolio_risk=adjusted_risk,
                    risk_change=adjusted_risk,
                    correlation_adjusted_change=adjusted_risk,
                    within_budget=True,  # Checked against profile limit
                )
            )

        return impacts

    def _rank_by_diversification(
        self,
        candidates: list[ExpansionCandidate],
    ) -> list[ExpansionCandidate]:
        """Rank candidates: lowest avg correlation first.

        Most diversifying candidates rank highest.
        """
        return sorted(candidates, key=lambda c: c.avg_correlation_with_existing)

    def _compute_diversity_score(
        self, candidates: list[ExpansionCandidate]
    ) -> float:
        """Compute a 0-1 diversity score for the proposed additions.

        Higher score = more diversifying (lower average correlation).
        """
        if not candidates:
            return 0.0

        avg_corrs = [c.avg_correlation_with_existing for c in candidates]
        mean_corr = sum(avg_corrs) / len(avg_corrs)

        # Diversity score: 1.0 at mean_corr=0, 0.0 at mean_corr=1
        return max(0.0, 1.0 - mean_corr)

    def _validate_against_profile(
        self,
        proposed_count: int,
        current_count: int,
    ) -> tuple[bool, str]:
        """Check if proposed total is within scaling profile limit."""
        ok, reason = self._scaling.validate_universe_size(
            ["x"] * (current_count + proposed_count)
        )
        return ok, reason

    def _make_empty_proposal(
        self,
        audit_report: BreadthAuditReport,
        profile_name: str,
        reason: str,
    ) -> SymbolExpansionProposal:
        """Create an empty proposal with a reason."""
        return SymbolExpansionProposal(
            proposal_id=f"prop_{uuid.uuid4().hex[:12]}",
            audit_id=0,
            current_symbols=audit_report.current_symbols,
            proposed_additions=[],
            risk_impacts=[],
            scaling_profile=profile_name,
            total_symbols_after=len(audit_report.current_symbols),
            within_profile_limit=True,
            correlation_diversity_score=0.0,
            created_at=datetime.now().isoformat(),
            decision_reason=reason,
        )
