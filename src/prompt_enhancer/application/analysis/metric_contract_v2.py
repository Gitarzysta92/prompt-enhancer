"""Metric-science contract V2: a new versioned registry beside the frozen V1.

V1 (``all-20-factor-contracts-v1``) stays byte-identical.  Persisted predictive
receipts are validated against frozen V1 identities, so this module never edits
``probabilistic_metrics``; it registers a second, independently fingerprinted
registry that historical receipts can be rehydrated alongside.

What V2 changes, and why:

* ``outcome.verification_strategy_adequacy`` is corrected from an
  objective-evidence contract to a **conversational D+S** contract
  (``ObservationScope.CONVERSATION`` + ``EvidenceLane.DETERMINISTIC_SMALL``).
  The metric observes whether a verification strategy was *stated* for an
  exactly-owned request revision.  A stated strategy is not an executed check,
  so V2 also drops its outcome-forecast target.  Executed verification stays
  with the five objective-lane contracts.
* ``PENDING`` becomes a first-class, typed value state.  V1 could only push a
  whole metric to ``unknown`` when any episode touched the right edge of the
  window.  V2 marks the individual right-censored *opportunity* as pending and
  keeps the remaining opportunities measured, publishing censoring bounds
  instead of a point value.
* Denominators are declared per contract as an exact opportunity basis rather
  than being whatever a lexical rule happened to match.
* "No opportunity" is separated from "no evidence": a contract declares whether
  a provable empty opportunity set means ``not_applicable`` or ``unknown``.

Objective-evidence precedence is preserved: a contract whose authority is
``EvidenceAuthority.OBJECTIVE_RECEIPT`` may never publish a known value from
conversational material, whatever an assistant claimed in prose.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
from types import MappingProxyType

from ...domain import SAFE_VERSION_PATTERN
from .probabilistic_metrics import (
    EvidenceLane,
    FactorContract,
    MetricWorkspaceView,
    ObservationScope,
    PredictiveMetricTarget,
    PROBABILISTIC_METRIC_CONTRACTS,
    metric_workspace_view,
)
from .semantic_units import SemanticUnitKind


METRIC_CONTRACT_REGISTRY_VERSION_V2 = "all-20-factor-contracts-v2"
METRIC_CONTRACT_VERSION_V2 = "probabilistic-metric-contract-v2"
METRIC_CONTRACT_V2_SCHEMA_VERSION = 1
#: Registries a caller may rehydrate.  V1 is frozen, not deleted.
SUPPORTED_METRIC_CONTRACT_REGISTRIES = (
    "all-20-factor-contracts-v1",
    METRIC_CONTRACT_REGISTRY_VERSION_V2,
)


def _safe(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a content-free version identifier")
    return value


class MetricValueStateV2(StrEnum):
    """Persistable value states, including first-class right-censored pending.

    ``PENDING`` is temporal: an eligible opportunity exists and its outcome is
    still undetermined at the right edge of the observed window.  It is not a
    synonym for ``UNKNOWN`` (missing capability or unclassifiable evidence) and
    never a synonym for ``NOT_APPLICABLE`` (no opportunity at all).
    """

    KNOWN = "known"
    PENDING = "pending"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    ABSTAINED = "abstained"
    EXECUTION_ERROR = "execution_error"


class OpportunityState(StrEnum):
    """Outcome of exactly one owned opportunity."""

    MET = "met"
    NOT_MET = "not_met"
    PENDING = "pending"
    UNKNOWN = "unknown"


class DenominatorBasis(StrEnum):
    """Where a contract's exact denominator comes from.

    ``RUBRIC_FACTORS`` scores one canonical opportunity against a fixed factor
    list.  The other three enumerate opportunities and never invent them.
    """

    RUBRIC_FACTORS = "rubric_factors"
    SEMANTIC_UNIT_OPPORTUNITIES = "semantic_unit_opportunities"
    DECLARED_PROFILE_SLOTS = "declared_profile_slots"
    OBJECTIVE_OPPORTUNITIES = "objective_opportunities"


class OpportunitySelector(StrEnum):
    """Which semantic-unit heads form the denominator.

    Every selector excludes superseded heads: a superseded unit was replaced by
    its successor and must not be counted twice.
    """

    CANONICAL_ACTIVE_REVISION = "canonical_active_revision"
    ACTIVE_UNITS = "active_units"
    CLASSIFIED_FEEDBACK_UNITS = "classified_feedback_units"
    NOT_UNIT_BASED = "not_unit_based"


class PendingPolicy(StrEnum):
    """Whether an opportunity of this contract can be right-censored at all."""

    IMMEDIATE = "immediate"
    RIGHT_CENSORED_OPPORTUNITY = "right_censored_opportunity"


class NoOpportunityOutcome(StrEnum):
    """What a *provable* empty opportunity set means for this contract."""

    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class EvidenceAuthority(StrEnum):
    """Highest authority allowed to publish a known value.

    ``OBJECTIVE_RECEIPT`` outranks ``CONVERSATION``.  A conversational
    projection may never resolve an objective contract, and no volume of
    assistant prose upgrades a conversational observation into a receipt.
    """

    CONVERSATION = "conversation"
    OBJECTIVE_RECEIPT = "objective_receipt"


@dataclass(frozen=True, slots=True)
class MetricContractV2:
    """One versioned V2 metric-science contract."""

    metric_key: str
    contract_version: str
    observation_unit: str
    scope: ObservationScope
    lane: EvidenceLane
    target: PredictiveMetricTarget
    workspace_view: MetricWorkspaceView
    factors: tuple[FactorContract, ...]
    closure_horizon: str
    denominator_basis: DenominatorBasis
    opportunity_selector: OpportunitySelector
    pending_policy: PendingPolicy
    no_opportunity_outcome: NoOpportunityOutcome
    evidence_authority: EvidenceAuthority
    opportunity_unit_kind: SemanticUnitKind | None = None
    supersedes_contract_version: str = "probabilistic-metric-contract-v1"

    def __post_init__(self) -> None:
        _safe(self.metric_key)
        _safe(self.contract_version)
        _safe(self.observation_unit)
        _safe(self.closure_horizon)
        _safe(self.supersedes_contract_version)
        if not self.factors or len(self.factors) > 8:
            raise ValueError("metric contracts require one to eight factors")
        keys = tuple(item.factor_key for item in self.factors)
        if len(set(keys)) != len(keys):
            raise ValueError("metric factor keys must be unique")
        unit_based = (
            self.denominator_basis is DenominatorBasis.SEMANTIC_UNIT_OPPORTUNITIES
            or self.opportunity_selector is not OpportunitySelector.NOT_UNIT_BASED
        )
        if unit_based != (self.opportunity_unit_kind is not None):
            raise ValueError(
                "unit-based contracts require exactly one semantic-unit kind"
            )
        if (
            self.evidence_authority is EvidenceAuthority.OBJECTIVE_RECEIPT
            and self.denominator_basis
            is not DenominatorBasis.OBJECTIVE_OPPORTUNITIES
        ):
            raise ValueError(
                "objective contracts must enumerate objective opportunities"
            )
        if (
            self.denominator_basis is DenominatorBasis.OBJECTIVE_OPPORTUNITIES
            and self.evidence_authority is not EvidenceAuthority.OBJECTIVE_RECEIPT
        ):
            raise ValueError(
                "objective opportunity sets require objective evidence authority"
            )
        if (
            self.pending_policy is PendingPolicy.IMMEDIATE
            and self.closure_horizon != "immediate"
        ):
            raise ValueError("immediate contracts cannot declare a closure horizon")
        if (
            self.pending_policy is PendingPolicy.RIGHT_CENSORED_OPPORTUNITY
            and self.closure_horizon == "immediate"
        ):
            raise ValueError("right-censored contracts require a closure horizon")

    @property
    def objective_evidence_required(self) -> bool:
        return self.evidence_authority is EvidenceAuthority.OBJECTIVE_RECEIPT

    @property
    def fingerprint(self) -> str:
        payload = {
            "registry": METRIC_CONTRACT_REGISTRY_VERSION_V2,
            "schema": METRIC_CONTRACT_V2_SCHEMA_VERSION,
            "metric_key": self.metric_key,
            "contract_version": self.contract_version,
            "observation_unit": self.observation_unit,
            "scope": self.scope.value,
            "lane": self.lane.value,
            "target": self.target.value,
            "workspace_view": self.workspace_view.value,
            "closure_horizon": self.closure_horizon,
            "denominator_basis": self.denominator_basis.value,
            "opportunity_selector": self.opportunity_selector.value,
            "opportunity_unit_kind": (
                None
                if self.opportunity_unit_kind is None
                else self.opportunity_unit_kind.value
            ),
            "pending_policy": self.pending_policy.value,
            "no_opportunity_outcome": self.no_opportunity_outcome.value,
            "evidence_authority": self.evidence_authority.value,
            "supersedes_contract_version": self.supersedes_contract_version,
            "factors": [
                {
                    "key": item.factor_key,
                    "description": item.description,
                    "scale": item.scale.value,
                    "weight": item.weight,
                    "critical": item.critical,
                }
                for item in self.factors
            ],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


_V1_BY_KEY = {item.metric_key: item for item in PROBABILISTIC_METRIC_CONTRACTS}


def _inherited_factors(metric_key: str) -> tuple[FactorContract, ...]:
    """Reuse the reviewed V1 factor list unless V2 explicitly restates it."""

    return _V1_BY_KEY[metric_key].factors


def _contract(
    metric_key: str,
    observation_unit: str,
    scope: ObservationScope,
    lane: EvidenceLane,
    *,
    denominator_basis: DenominatorBasis,
    opportunity_selector: OpportunitySelector,
    no_opportunity_outcome: NoOpportunityOutcome,
    evidence_authority: EvidenceAuthority,
    opportunity_unit_kind: SemanticUnitKind | None = None,
    closure_horizon: str = "immediate",
    pending_policy: PendingPolicy = PendingPolicy.IMMEDIATE,
    target: PredictiveMetricTarget = PredictiveMetricTarget.METRIC_VALUE,
    factors: tuple[FactorContract, ...] | None = None,
) -> MetricContractV2:
    return MetricContractV2(
        metric_key=metric_key,
        contract_version=METRIC_CONTRACT_VERSION_V2,
        observation_unit=observation_unit,
        scope=scope,
        lane=lane,
        target=target,
        workspace_view=metric_workspace_view(metric_key),
        factors=_inherited_factors(metric_key) if factors is None else factors,
        closure_horizon=closure_horizon,
        denominator_basis=denominator_basis,
        opportunity_selector=opportunity_selector,
        pending_policy=pending_policy,
        no_opportunity_outcome=no_opportunity_outcome,
        evidence_authority=evidence_authority,
        opportunity_unit_kind=opportunity_unit_kind,
    )


def _rubric(
    metric_key: str,
    observation_unit: str,
    *,
    no_opportunity_outcome: NoOpportunityOutcome,
) -> MetricContractV2:
    """A fixed factor rubric scored on the one canonical request revision."""

    return _contract(
        metric_key,
        observation_unit,
        ObservationScope.FOCUS_REQUEST,
        EvidenceLane.DETERMINISTIC_SMALL,
        denominator_basis=DenominatorBasis.RUBRIC_FACTORS,
        opportunity_selector=OpportunitySelector.CANONICAL_ACTIVE_REVISION,
        opportunity_unit_kind=SemanticUnitKind.REQUEST_REVISION,
        no_opportunity_outcome=no_opportunity_outcome,
        evidence_authority=EvidenceAuthority.CONVERSATION,
    )


def _profile_slots(
    metric_key: str,
    observation_unit: str,
) -> MetricContractV2:
    """A denominator the user's task profile declared explicitly.

    An empty declaration is not zero and is not "no opportunity": it means the
    caller never told us what to expect, so the contract abstains as unknown.
    """

    return _contract(
        metric_key,
        observation_unit,
        ObservationScope.FOCUS_REQUEST,
        EvidenceLane.DETERMINISTIC_SMALL,
        denominator_basis=DenominatorBasis.DECLARED_PROFILE_SLOTS,
        opportunity_selector=OpportunitySelector.NOT_UNIT_BASED,
        no_opportunity_outcome=NoOpportunityOutcome.UNKNOWN,
        evidence_authority=EvidenceAuthority.CONVERSATION,
    )


def _episode(
    metric_key: str,
    observation_unit: str,
    unit_kind: SemanticUnitKind,
    closure_horizon: str,
    *,
    lane: EvidenceLane = EvidenceLane.DETERMINISTIC_SMALL,
) -> MetricContractV2:
    """A conversational episode counted once per exactly-owned unit."""

    return _contract(
        metric_key,
        observation_unit,
        ObservationScope.CONVERSATION,
        lane,
        denominator_basis=DenominatorBasis.SEMANTIC_UNIT_OPPORTUNITIES,
        opportunity_selector=OpportunitySelector.ACTIVE_UNITS,
        opportunity_unit_kind=unit_kind,
        no_opportunity_outcome=NoOpportunityOutcome.NOT_APPLICABLE,
        evidence_authority=EvidenceAuthority.CONVERSATION,
        closure_horizon=closure_horizon,
        pending_policy=PendingPolicy.RIGHT_CENSORED_OPPORTUNITY,
    )


def _objective(
    metric_key: str,
    observation_unit: str,
    *,
    lane: EvidenceLane,
    closure_horizon: str = "immediate",
    pending_policy: PendingPolicy = PendingPolicy.IMMEDIATE,
) -> MetricContractV2:
    return _contract(
        metric_key,
        observation_unit,
        ObservationScope.OBJECTIVE_EVIDENCE,
        lane,
        denominator_basis=DenominatorBasis.OBJECTIVE_OPPORTUNITIES,
        opportunity_selector=OpportunitySelector.NOT_UNIT_BASED,
        no_opportunity_outcome=NoOpportunityOutcome.NOT_APPLICABLE,
        evidence_authority=EvidenceAuthority.OBJECTIVE_RECEIPT,
        closure_horizon=closure_horizon,
        pending_policy=pending_policy,
        target=PredictiveMetricTarget.OUTCOME_FORECAST,
    )


#: The corrected verification-strategy factor list.  V1 asked whether an
#: executed verification had a valid oracle; V2 asks whether the conversation
#: *stated* a strategy for an exactly-owned request revision.  ``execution`` is
#: deliberately absent: executed checks belong to the objective lane.
_VERIFICATION_STRATEGY_FACTORS_V2 = (
    FactorContract(
        factor_key="requirement",
        description=(
            "The request revision carries a requirement whose verification "
            "strategy can be discussed."
        ),
        critical=True,
    ),
    FactorContract(
        factor_key="method",
        description="A verification method is stated for that requirement.",
        critical=True,
    ),
    FactorContract(
        factor_key="oracle",
        description="A stated pass or fail boundary accompanies the method.",
    ),
    FactorContract(
        factor_key="scope",
        description="The stated strategy is bounded to the requested scope.",
    ),
    FactorContract(
        factor_key="edge_strategy",
        description="Negative or edge cases are addressed when applicable.",
    ),
)


METRIC_CONTRACTS_V2: tuple[MetricContractV2, ...] = (
    _rubric(
        "prompt.task_definition_coverage",
        "canonical_request_revision",
        no_opportunity_outcome=NoOpportunityOutcome.NOT_APPLICABLE,
    ),
    # A diagnostic intent cannot be *proved absent* from typed units, so an
    # empty set stays unknown rather than claiming the request was not one.
    _rubric(
        "prompt.problem_evidence_quality",
        "canonical_request_revision",
        no_opportunity_outcome=NoOpportunityOutcome.UNKNOWN,
    ),
    _rubric(
        "prompt.context_sufficiency",
        "canonical_request_revision",
        no_opportunity_outcome=NoOpportunityOutcome.NOT_APPLICABLE,
    ),
    _profile_slots("prompt.constraint_precision", "declared_constraint_kind"),
    _profile_slots("prompt.acceptance_testability", "declared_expected_outcome"),
    _profile_slots("prompt.deliverable_contract", "declared_deliverable_slot"),
    _episode(
        "collaboration.ambiguity_resolution",
        "ambiguity_episode",
        SemanticUnitKind.AMBIGUITY,
        "episode_closed_or_right_censored",
    ),
    _episode(
        "collaboration.clarification_yield",
        "clarification_question",
        SemanticUnitKind.CLARIFICATION,
        "answer_and_downstream_use",
    ),
    _episode(
        "collaboration.exploration_conversion",
        "exploration_hypothesis",
        SemanticUnitKind.HYPOTHESIS,
        "evidence_action_completed",
        lane=EvidenceLane.DETERMINISTIC_SMALL_OBJECTIVE,
    ),
    _episode(
        "collaboration.scope_change_discipline",
        "scope_change_episode",
        SemanticUnitKind.SCOPE_CHANGE,
        "updated_plan_or_completion",
    ),
    # Feedback units are closed by construction, so this contract is immediate:
    # the residual uncertainty is the rework class, which is epistemic.
    _contract(
        "collaboration.rework_candidate_rate",
        "classified_feedback_episode",
        ObservationScope.CONVERSATION,
        EvidenceLane.DETERMINISTIC_SMALL,
        denominator_basis=DenominatorBasis.SEMANTIC_UNIT_OPPORTUNITIES,
        opportunity_selector=OpportunitySelector.CLASSIFIED_FEEDBACK_UNITS,
        opportunity_unit_kind=SemanticUnitKind.FEEDBACK,
        no_opportunity_outcome=NoOpportunityOutcome.NOT_APPLICABLE,
        evidence_authority=EvidenceAuthority.CONVERSATION,
    ),
    _episode(
        "logic.decomposition_coverage",
        "active_requirement",
        SemanticUnitKind.REQUIREMENT,
        "plan_item_or_right_censored",
        lane=EvidenceLane.DETERMINISTIC_SMALL_RETRIEVAL,
    ),
    _objective(
        "logic.hypothesis_test_linkage",
        "hypothesis_episode",
        lane=EvidenceLane.DETERMINISTIC_SMALL_OBJECTIVE,
        closure_horizon="objective_check_completed",
        pending_policy=PendingPolicy.RIGHT_CENSORED_OPPORTUNITY,
    ),
    _contract(
        "logic.decision_rationale_coverage",
        "material_decision",
        ObservationScope.CONVERSATION,
        EvidenceLane.DETERMINISTIC_SMALL,
        denominator_basis=DenominatorBasis.SEMANTIC_UNIT_OPPORTUNITIES,
        opportunity_selector=OpportunitySelector.ACTIVE_UNITS,
        opportunity_unit_kind=SemanticUnitKind.DECISION,
        no_opportunity_outcome=NoOpportunityOutcome.NOT_APPLICABLE,
        evidence_authority=EvidenceAuthority.CONVERSATION,
    ),
    # An action that started but has not reported an outcome is right-censored,
    # not a measured failure to trace the requirement.
    _objective(
        "logic.requirement_action_traceability",
        "active_requirement",
        lane=EvidenceLane.DETERMINISTIC_SMALL_RETRIEVAL,
        closure_horizon="action_completed_or_right_censored",
        pending_policy=PendingPolicy.RIGHT_CENSORED_OPPORTUNITY,
    ),
    _episode(
        "logic.open_loop_closure",
        "open_loop_episode",
        SemanticUnitKind.OPEN_LOOP,
        "episode_end_or_right_censored",
    ),
    _objective(
        "outcome.agent_claim_grounding",
        "material_completion_claim",
        lane=EvidenceLane.DETERMINISTIC_SMALL_OBJECTIVE,
    ),
    # Corrected in V2: a *stated* strategy is conversational evidence.
    _contract(
        "outcome.verification_strategy_adequacy",
        "active_request_revision",
        ObservationScope.CONVERSATION,
        EvidenceLane.DETERMINISTIC_SMALL,
        denominator_basis=DenominatorBasis.SEMANTIC_UNIT_OPPORTUNITIES,
        opportunity_selector=OpportunitySelector.ACTIVE_UNITS,
        opportunity_unit_kind=SemanticUnitKind.REQUEST_REVISION,
        no_opportunity_outcome=NoOpportunityOutcome.NOT_APPLICABLE,
        evidence_authority=EvidenceAuthority.CONVERSATION,
        closure_horizon="strategy_stated_or_right_censored",
        pending_policy=PendingPolicy.RIGHT_CENSORED_OPPORTUNITY,
        target=PredictiveMetricTarget.METRIC_VALUE,
        factors=_VERIFICATION_STRATEGY_FACTORS_V2,
    ),
    # A task whose first executable check has not run yet is pending; only an
    # observed first outcome may resolve it in either direction.
    _objective(
        "outcome.first_pass_verification",
        "eligible_verification_task",
        lane=EvidenceLane.OBJECTIVE_ONLY,
        closure_horizon="first_outcome_or_right_censored",
        pending_policy=PendingPolicy.RIGHT_CENSORED_OPPORTUNITY,
    ),
    _objective(
        "outcome.verified_requirement_coverage",
        "active_requirement",
        lane=EvidenceLane.OBJECTIVE_ONLY,
    ),
)


_CONTRACT_V2_BY_KEY = MappingProxyType(
    {item.metric_key: item for item in METRIC_CONTRACTS_V2}
)
if len(_CONTRACT_V2_BY_KEY) != 20:
    raise RuntimeError("metric contract V2 must contain exactly twenty metrics")
if set(_CONTRACT_V2_BY_KEY) != set(_V1_BY_KEY):
    raise RuntimeError("metric contract V2 must preserve every V1 metric key")
if (
    sum(
        1
        for item in METRIC_CONTRACTS_V2
        if item.evidence_authority is EvidenceAuthority.OBJECTIVE_RECEIPT
    )
    != 5
):
    raise RuntimeError("V2 must keep exactly five objective-evidence contracts")


def metric_contract_v2(metric_key: str) -> MetricContractV2:
    try:
        return _CONTRACT_V2_BY_KEY[metric_key]
    except KeyError:
        raise ValueError("metric is outside the V2 contract registry") from None


def metric_contract_v2_keys() -> tuple[str, ...]:
    return tuple(_CONTRACT_V2_BY_KEY)


def metric_contract_v2_set_fingerprint() -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "registry": METRIC_CONTRACT_REGISTRY_VERSION_V2,
                "contracts": [
                    (item.metric_key, item.fingerprint)
                    for item in METRIC_CONTRACTS_V2
                ],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()


__all__ = [
    "DenominatorBasis",
    "EvidenceAuthority",
    "METRIC_CONTRACTS_V2",
    "METRIC_CONTRACT_REGISTRY_VERSION_V2",
    "METRIC_CONTRACT_V2_SCHEMA_VERSION",
    "METRIC_CONTRACT_VERSION_V2",
    "MetricContractV2",
    "MetricValueStateV2",
    "NoOpportunityOutcome",
    "OpportunitySelector",
    "OpportunityState",
    "PendingPolicy",
    "SUPPORTED_METRIC_CONTRACT_REGISTRIES",
    "metric_contract_v2",
    "metric_contract_v2_keys",
    "metric_contract_v2_set_fingerprint",
]
