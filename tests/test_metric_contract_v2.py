"""Contract-level guarantees for metric-science contract V2.

These tests pin the V2 registry identity and prove that adding it left the
frozen V1 registry byte-identical, so persisted V1 receipts keep rehydrating.
"""

from __future__ import annotations

import pytest

from prompt_enhancer.application.analysis.metric_contract_v2 import (
    DenominatorBasis,
    EvidenceAuthority,
    METRIC_CONTRACTS_V2,
    METRIC_CONTRACT_REGISTRY_VERSION_V2,
    METRIC_CONTRACT_VERSION_V2,
    MetricContractV2,
    MetricValueStateV2,
    NoOpportunityOutcome,
    OpportunitySelector,
    PendingPolicy,
    SUPPORTED_METRIC_CONTRACT_REGISTRIES,
    metric_contract_v2,
    metric_contract_v2_keys,
    metric_contract_v2_set_fingerprint,
)
from prompt_enhancer.application.analysis.probabilistic_metrics import (
    EvidenceLane,
    EVIDENCE_LANE_METRIC_KEYS,
    FactorContract,
    MetricWorkspaceView,
    ObservationScope,
    PROBABILISTIC_CONTRACT_REGISTRY_VERSION,
    PROBABILISTIC_METRIC_CONTRACTS,
    PredictiveMetricTarget,
    probabilistic_contract_set_fingerprint,
    probabilistic_metric_contract,
)
from prompt_enhancer.application.analysis.semantic_units import SemanticUnitKind
from prompt_enhancer.application.persistence import MetricValueState


V1_SET_FINGERPRINT = (
    "918affdc3feb734de4870fd0e58308c279b657839f833c8007439e862fe1ef04"
)
V2_SET_FINGERPRINT = (
    "02eac63391eb48351f5c8c197d62897895234e2334d388a530d6e6812a18aa67"
)


def test_v2_preserves_every_v1_metric_key() -> None:
    assert len(METRIC_CONTRACTS_V2) == 20
    assert set(metric_contract_v2_keys()) == {
        item.metric_key for item in PROBABILISTIC_METRIC_CONTRACTS
    }


def test_v1_registry_is_untouched_by_v2() -> None:
    # V1 receipts are validated against these identities. Adding V2 must not
    # move a single byte of the frozen registry.
    assert PROBABILISTIC_CONTRACT_REGISTRY_VERSION == "all-20-factor-contracts-v1"
    assert probabilistic_contract_set_fingerprint() == V1_SET_FINGERPRINT
    assert SUPPORTED_METRIC_CONTRACT_REGISTRIES == (
        "all-20-factor-contracts-v1",
        METRIC_CONTRACT_REGISTRY_VERSION_V2,
    )


def test_v2_registry_identity_is_pinned() -> None:
    assert METRIC_CONTRACT_REGISTRY_VERSION_V2 == "all-20-factor-contracts-v2"
    assert metric_contract_v2_set_fingerprint() == V2_SET_FINGERPRINT
    assert metric_contract_v2_set_fingerprint() != probabilistic_contract_set_fingerprint()


def test_every_v2_contract_fingerprint_differs_from_v1() -> None:
    for contract in METRIC_CONTRACTS_V2:
        v1 = probabilistic_metric_contract(contract.metric_key)
        assert contract.contract_version == METRIC_CONTRACT_VERSION_V2
        assert contract.supersedes_contract_version == v1.contract_version
        assert contract.fingerprint != v1.fingerprint


def test_verification_strategy_is_corrected_to_conversational_deterministic_small() -> None:
    v1 = probabilistic_metric_contract("outcome.verification_strategy_adequacy")
    assert v1.scope is ObservationScope.OBJECTIVE_EVIDENCE
    assert v1.objective_evidence_required is True

    v2 = metric_contract_v2("outcome.verification_strategy_adequacy")
    assert v2.scope is ObservationScope.CONVERSATION
    assert v2.lane is EvidenceLane.DETERMINISTIC_SMALL
    assert v2.objective_evidence_required is False
    assert v2.evidence_authority is EvidenceAuthority.CONVERSATION
    # A stated strategy is a metric value, not a forecast of an executed check.
    assert v2.target is PredictiveMetricTarget.METRIC_VALUE
    assert v2.workspace_view is MetricWorkspaceView.REASONING
    # Its denominator is an exactly-owned request revision, and the right edge
    # of a window leaves an opportunity pending rather than failed.
    assert v2.denominator_basis is DenominatorBasis.SEMANTIC_UNIT_OPPORTUNITIES
    assert v2.opportunity_unit_kind is SemanticUnitKind.REQUEST_REVISION
    assert v2.pending_policy is PendingPolicy.RIGHT_CENSORED_OPPORTUNITY
    assert {factor.factor_key for factor in v2.factors} == {
        "requirement",
        "method",
        "oracle",
        "scope",
        "edge_strategy",
    }


def test_objective_evidence_precedence_is_preserved() -> None:
    objective = {
        contract.metric_key
        for contract in METRIC_CONTRACTS_V2
        if contract.evidence_authority is EvidenceAuthority.OBJECTIVE_RECEIPT
    }
    # Exactly the five evidence-lane metrics keep objective authority; the
    # corrected verification-strategy contract is deliberately not among them.
    assert objective == set(EVIDENCE_LANE_METRIC_KEYS)
    assert "outcome.verification_strategy_adequacy" not in objective
    for key in objective:
        contract = metric_contract_v2(key)
        assert contract.denominator_basis is DenominatorBasis.OBJECTIVE_OPPORTUNITIES
        assert contract.scope is ObservationScope.OBJECTIVE_EVIDENCE
        assert contract.opportunity_selector is OpportunitySelector.NOT_UNIT_BASED


def test_pending_is_a_first_class_value_state() -> None:
    assert MetricValueStateV2.PENDING.value == "pending"
    # Every legacy state survives so a V1 result can be restated in V2 terms.
    assert {item.value for item in MetricValueState} <= {
        item.value for item in MetricValueStateV2
    }


def test_simple_no_opportunity_cases_are_not_applicable() -> None:
    # Absence of an episode in a complete window is "nothing to measure".
    for key in (
        "collaboration.ambiguity_resolution",
        "collaboration.clarification_yield",
        "collaboration.scope_change_discipline",
        "collaboration.rework_candidate_rate",
        "logic.decomposition_coverage",
        "logic.decision_rationale_coverage",
        "logic.open_loop_closure",
        "outcome.verification_strategy_adequacy",
    ):
        assert (
            metric_contract_v2(key).no_opportunity_outcome
            is NoOpportunityOutcome.NOT_APPLICABLE
        )
    # A diagnostic intent cannot be proved absent, so it stays unknown.
    assert (
        metric_contract_v2("prompt.problem_evidence_quality").no_opportunity_outcome
        is NoOpportunityOutcome.UNKNOWN
    )
    # A profile that declared no slots told us nothing; it did not tell us zero.
    for key in (
        "prompt.constraint_precision",
        "prompt.acceptance_testability",
        "prompt.deliverable_contract",
    ):
        contract = metric_contract_v2(key)
        assert contract.denominator_basis is DenominatorBasis.DECLARED_PROFILE_SLOTS
        assert contract.no_opportunity_outcome is NoOpportunityOutcome.UNKNOWN


def test_pending_policy_matches_the_declared_closure_horizon() -> None:
    for contract in METRIC_CONTRACTS_V2:
        if contract.pending_policy is PendingPolicy.IMMEDIATE:
            assert contract.closure_horizon == "immediate"
        else:
            assert contract.closure_horizon != "immediate"


def test_unit_based_contracts_declare_exactly_one_opportunity_kind() -> None:
    for contract in METRIC_CONTRACTS_V2:
        unit_based = (
            contract.opportunity_selector is not OpportunitySelector.NOT_UNIT_BASED
        )
        assert unit_based == (contract.opportunity_unit_kind is not None)


def test_unknown_metric_key_is_rejected() -> None:
    with pytest.raises(ValueError):
        metric_contract_v2("prompt.not_a_metric")


def _contract(**overrides: object) -> MetricContractV2:
    base: dict[str, object] = {
        "metric_key": "logic.open_loop_closure",
        "contract_version": METRIC_CONTRACT_VERSION_V2,
        "observation_unit": "open_loop_episode",
        "scope": ObservationScope.CONVERSATION,
        "lane": EvidenceLane.DETERMINISTIC_SMALL,
        "target": PredictiveMetricTarget.METRIC_VALUE,
        "workspace_view": MetricWorkspaceView.REASONING,
        "factors": (FactorContract(factor_key="open_loop", description="x"),),
        "closure_horizon": "episode_end_or_right_censored",
        "denominator_basis": DenominatorBasis.SEMANTIC_UNIT_OPPORTUNITIES,
        "opportunity_selector": OpportunitySelector.ACTIVE_UNITS,
        "pending_policy": PendingPolicy.RIGHT_CENSORED_OPPORTUNITY,
        "no_opportunity_outcome": NoOpportunityOutcome.NOT_APPLICABLE,
        "evidence_authority": EvidenceAuthority.CONVERSATION,
        "opportunity_unit_kind": SemanticUnitKind.OPEN_LOOP,
    }
    base.update(overrides)
    return MetricContractV2(**base)  # type: ignore[arg-type]


def test_contract_rejects_objective_authority_without_objective_denominator() -> None:
    with pytest.raises(ValueError):
        _contract(evidence_authority=EvidenceAuthority.OBJECTIVE_RECEIPT)


def test_contract_rejects_objective_denominator_without_objective_authority() -> None:
    with pytest.raises(ValueError):
        _contract(
            denominator_basis=DenominatorBasis.OBJECTIVE_OPPORTUNITIES,
            opportunity_selector=OpportunitySelector.NOT_UNIT_BASED,
            opportunity_unit_kind=None,
        )


def test_contract_rejects_unit_kind_without_a_unit_selector() -> None:
    with pytest.raises(ValueError):
        _contract(opportunity_unit_kind=None)


def test_contract_rejects_a_pending_policy_without_a_horizon() -> None:
    with pytest.raises(ValueError):
        _contract(closure_horizon="immediate")
