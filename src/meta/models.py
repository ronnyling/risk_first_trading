"""Data models for the meta-optimization plane (Phase E).

Immutable dataclasses for optimization proposals, leverage reports,
policy changes, LLM tuning results, strategy variants, and drift audits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ──────────────────────────────────────────────────────
# Common enums
# ──────────────────────────────────────────────────────


class MetaCapability(Enum):
    """Which meta-optimization capability produced this output."""

    OPTIMIZER = "OPTIMIZER"
    LEVERAGE = "LEVERAGE"
    POLICY = "POLICY"
    LLM = "LLM"
    MUTATION = "MUTATION"


class ProposalStatus(Enum):
    """Lifecycle status of a meta-optimization proposal."""

    PENDING = "PENDING"
    ADOPTED = "ADOPTED"
    REJECTED = "REJECTED"
    IGNORED = "IGNORED"
    REVERTED = "REVERTED"


class VariantStage(Enum):
    """Pipeline stage for a strategy variant."""

    BACKTEST = "BACKTEST"
    SHADOW = "SHADOW"
    PAPER = "PAPER"
    ADMISSION = "ADMISSION"
    COOLING = "COOLING"
    LIVE = "LIVE"


class DriftSeverity(Enum):
    """Severity of detected performance drift."""

    NONE = "NONE"
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    CRITICAL = "CRITICAL"


# ──────────────────────────────────────────────────────
# E.1 Self-Optimizer models
# ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParameterChange:
    """A single parameter change in an optimization proposal."""

    param_name: str
    current_value: float
    proposed_value: float
    tuning_range_min: float
    tuning_range_max: float


@dataclass(frozen=True)
class WalkForwardWindow:
    """Result of one walk-forward validation window."""

    window_id: int
    train_pct: float
    test_pct: float
    in_sample_sharpe: float
    out_of_sample_sharpe: float
    in_sample_trades: int
    out_of_sample_trades: int


@dataclass(frozen=True)
class MonteCarloResult:
    """Result of Monte Carlo significance testing."""

    n_permutations: int
    p_value: float
    ci_lower: float
    ci_upper: float
    baseline_sharpe_mean: float
    proposed_sharpe_mean: float


@dataclass(frozen=True)
class OptimizationProposal:
    """Proposal to change Hermes parameters for improved risk-adjusted returns."""

    proposal_id: str
    capability: str  # MetaCapability.OPTIMIZER.value
    changes: list[ParameterChange]
    baseline_sharpe: float
    proposed_sharpe: float
    baseline_sortino: float
    proposed_sortino: float
    baseline_calmar: float
    proposed_calmar: float
    walk_forward: list[WalkForwardWindow]
    monte_carlo: MonteCarloResult
    overfitting_checks: dict  # regime_stability, sensitivity, etc.
    validation_passed: bool
    rejection_reason: str | None = None
    status: str = ProposalStatus.PENDING.value
    created_at: str = ""
    decided_at: str | None = None
    decision_reason: str | None = None


# ──────────────────────────────────────────────────────
# E.2 Leverage Simulator models
# ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class LeverageScenario:
    """Simulated outcome at a specific leverage level."""

    leverage: float
    simulated_sharpe: float
    simulated_sortino: float
    simulated_max_dd: float
    simulated_calmar: float
    kill_switch_probability: float
    percentile_5_pnl: float
    percentile_50_pnl: float
    percentile_95_pnl: float
    time_to_recovery_bars: int


@dataclass(frozen=True)
class LeverageReport:
    """Complete leverage evaluation report for HITL review."""

    report_id: str
    capability: str  # MetaCapability.LEVERAGE.value
    current_leverage: float
    scaling_profile: str
    max_simulated_leverage: float
    stability_days: int
    stability_max_dd: float
    scenarios: list[LeverageScenario]
    gating_passed: bool
    gating_reason: str
    status: str = ProposalStatus.PENDING.value
    created_at: str = ""
    decided_at: str | None = None
    decision_reason: str | None = None


# ──────────────────────────────────────────────────────
# E.3 Policy Evolution models
# ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class PolicyEvidence:
    """Evidence supporting a policy change proposal."""

    source: str  # e.g. "expansion_proposals", "workflow_history"
    metric: str  # e.g. "approval_rate", "diversity_score"
    value: float
    description: str


@dataclass(frozen=True)
class PolicyChange:
    """A single policy change in a proposal."""

    policy_name: str
    config_file: str
    current_value: str
    proposed_value: str
    backup_path: str | None = None


@dataclass(frozen=True)
class PolicyProposal:
    """Proposal to evolve a system policy based on accumulated evidence."""

    proposal_id: str
    capability: str  # MetaCapability.POLICY.value
    changes: list[PolicyChange]
    evidence: list[PolicyEvidence]
    rollback_available: bool
    rollback_path: str | None = None
    status: str = ProposalStatus.PENDING.value
    created_at: str = ""
    decided_at: str | None = None
    decision_reason: str | None = None


# ──────────────────────────────────────────────────────
# E.4 LLM Tuner models
# ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class LLMHypothesis:
    """A hypothesis generated by the LLM about parameter improvement."""

    hypothesis_id: str
    hypothesis_text: str
    parameters_affected: list[str]
    reasoning: str
    confidence: float  # LLM's self-assessed confidence [0, 1]


@dataclass(frozen=True)
class LLMTuningProposal:
    """Proposal from LLM-driven parameter tuning."""

    proposal_id: str
    capability: str  # MetaCapability.LLM.value
    hypothesis: LLMHypothesis
    candidate_config: dict  # param_name → proposed_value
    baseline_metrics: dict  # metric_name → value
    projected_metrics: dict  # metric_name → value
    walk_forward: list[WalkForwardWindow]
    monte_carlo: MonteCarloResult
    validation_passed: bool
    rejection_reason: str | None = None
    status: str = ProposalStatus.PENDING.value
    created_at: str = ""
    decided_at: str | None = None
    decision_reason: str | None = None


# ──────────────────────────────────────────────────────
# E.5 Strategy Mutation models
# ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class StrategyVariant:
    """A strategy variant generated by the mutation R&D layer."""

    variant_id: str
    parent_strategy: str
    mutation_type: str  # PARAM | COMBO | SPECIALIZE | HYBRID
    parameters: dict  # variant-specific parameter overrides
    stage: str  # VariantStage value
    stage_entered_at: str
    backtest_results: dict = field(default_factory=dict)
    shadow_results: dict = field(default_factory=dict)
    paper_results: dict = field(default_factory=dict)
    admission_decision: str | None = None  # ADMITTED | REJECTED | DEFERRED
    cooling_off_end: str | None = None
    created_at: str = ""


@dataclass(frozen=True)
class AdmissionReview:
    """HITL review of a strategy variant for admission."""

    variant_id: str
    sharpe: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    regime_coverage: dict  # regime → trade_count
    correlation_with_parent: float
    catastrophic_loss: bool  # True if any single-day loss > 5%
    all_criteria_met: bool
    criteria_details: dict  # criterion → (passed, value, threshold)


# ──────────────────────────────────────────────────────
# E.6 Drift Detection models
# ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class DriftMetric:
    """A single metric comparison for drift detection."""

    metric_name: str
    baseline_value: float
    current_value: float
    change: float
    threshold: float
    breached: bool


@dataclass(frozen=True)
class DriftAuditReport:
    """Report of performance drift detection."""

    report_id: str
    severity: str  # DriftSeverity value
    metrics: list[DriftMetric]
    adopted_proposal_id: str | None
    days_since_adoption: int
    reversion_recommended: bool
    reversion_reason: str | None = None
    created_at: str = ""


# ──────────────────────────────────────────────────────
# Workflow models
# ──────────────────────────────────────────────────────


class MetaWorkflowPhase(Enum):
    """Current phase of the meta-optimization workflow."""

    IDLE = "IDLE"
    GATING = "GATING"
    EVALUATING = "EVALUATING"
    AWAITING_HIL = "AWAITING_HIL"
    APPLYING = "APPLYING"
    MONITORING = "MONITORING"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"


@dataclass
class MetaWorkflowState:
    """Current state of the meta-optimization workflow."""

    phase: MetaWorkflowPhase = MetaWorkflowPhase.IDLE
    active_capability: str | None = None
    proposal: object | None = None  # OptimizationProposal | LeverageReport | etc.
    drift_report: DriftAuditReport | None = None
    history: list[dict] = field(default_factory=list)
    started_at: str = ""
    last_updated: str = ""
