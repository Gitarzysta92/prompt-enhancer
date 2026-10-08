from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from pydantic import SecretStr, ValidationError

from prompt_enhancer.application.analysis.metric_contract_v2 import (
    METRIC_CONTRACTS_V2,
    MetricValueStateV2,
)
from prompt_enhancer.application.analysis.metric_evidence_readiness_v2 import (
    METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION,
    METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_3,
    METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_4,
    METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_5,
    METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_6,
    METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_7,
    METRIC_EVIDENCE_REQUIREMENTS_V2,
    METRIC_EVIDENCE_REQUIREMENTS_V2_R4,
    METRIC_EVIDENCE_REQUIREMENTS_V2_R6,
    METRIC_EVIDENCE_REQUIREMENTS_V2_R7,
    SUPPORTED_METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSIONS,
    MetricEvidenceAvailabilityState,
    MetricEvidenceContributor,
    MetricEvidenceReadinessProjectionV2,
    MetricEvidenceReadinessReason,
    metric_evidence_readiness_row,
    project_metric_evidence_readiness_v2,
)
from prompt_enhancer.application.analysis.metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_8,
    MetricStateV2,
    OpportunityStatistics,
    _issue_metric_state_projection,
    project_metric_states_v2,
)
from prompt_enhancer.application.analysis.metric_projection_v3 import (
    project_metric_states_v3,
)
from prompt_enhancer.application.analysis.metric_projection_v4 import (
    project_metric_states_v4,
)
from prompt_enhancer.application.analysis.metric_projection_v5 import (
    project_metric_states_v5,
)
from prompt_enhancer.application.analysis.metric_projection_v6 import (
    project_metric_states_v6,
)
from prompt_enhancer.application.analysis.metric_publication_v2 import (
    metric_publication_v2_fingerprint,
    publish_metric_states_v2,
)
from prompt_enhancer.application.analysis.objective_metric_projection import (
    ObjectiveMetricOverride,
    ObjectiveWithholdingCause,
)
from prompt_enhancer.application.analysis.requirement_plan_evidence import (
    RequirementPlanEvidenceSnapshot,
)
from prompt_enhancer.application.analysis.semantic_units import (
    SemanticUnitReconciler,
)
from prompt_enhancer.application.analysis.text_contracts import (
    ConstraintKind,
    DeliverableSlot,
    EphemeralRedactedMessage,
    MetricFraction,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextRole,
    TextTaskProfile,
)
from prompt_enhancer.application.persistence import MetricValueState
from prompt_enhancer.application.providers import CapabilityKey
from prompt_enhancer.domain import Provider


def _id(label: str) -> str:
    return hashlib.sha256(f"synthetic-readiness:{label}".encode()).hexdigest()


class _Ids:
    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str:
        return hashlib.sha256("\x1f".join((namespace, *values)).encode()).hexdigest()

    def fingerprint_secret(
        self,
        namespace: str,
        values: tuple[str, ...],
        secret: SecretStr,
    ) -> str:
        return hashlib.sha256(
            "\x1f".join((namespace, *values, secret.get_secret_value())).encode()
        ).hexdigest()


IDS = _Ids()
PROVENANCE = {
    "provider": Provider.SYNTHETIC,
    "provider_version": "synthetic.1",
    "adapter_version": "synthetic-adapter.1",
    "source_schema_version": "synthetic-source.1",
}


def _message(
    label: str,
    sequence: int,
    role: TextRole,
    kind: TextMessageKind,
    text: str,
    *,
    supersedes: tuple[str, ...] = (),
) -> EphemeralRedactedMessage:
    return EphemeralRedactedMessage(
        message_id=_id(label),
        sequence=sequence,
        role=role,
        kind=kind,
        language=TextLanguage.ENGLISH,
        text=SecretStr(text),
        supersedes_message_ids=supersedes,
    )


def _context(
    messages: tuple[EphemeralRedactedMessage, ...],
    *,
    label: str,
    complete: bool = True,
    task_profile: TextTaskProfile | None = None,
) -> P1TextAnalysisInput:
    focus = next(
        message
        for message in reversed(messages)
        if message.role is TextRole.USER
        and message.kind in {TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}
    )
    return P1TextAnalysisInput(
        provider=Provider.SYNTHETIC,
        session_id=_id("session"),
        provider_version="synthetic.1",
        adapter_version="synthetic-adapter.1",
        source_schema_version="synthetic-source.1",
        content_schema_version="synthetic-content.1",
        redactor_version="synthetic-redactor.1",
        text_extraction_complete=complete,
        available_message_kinds=frozenset(item.kind for item in messages),
        analysis_window_fingerprint=_id(f"window:{label}"),
        focus_message_id=focus.message_id,
        observed_message_count=len(messages),
        eligible_message_count=len(messages) if complete else len(messages) + 5,
        messages=messages,
        task_profile=task_profile or TextTaskProfile(applicability=()),
    )


def _readiness(
    context: P1TextAnalysisInput,
    *,
    conversational: dict[str, object] | None = None,
    objective: dict[str, ObjectiveMetricOverride] | None = None,
) -> MetricEvidenceReadinessProjectionV2:
    reconciliation = SemanticUnitReconciler(IDS).reconcile(context).reconciliation
    publication = publish_metric_states_v2(
        project_metric_states_v2(
            context=context,
            reconciliation=reconciliation,
            id_factory=IDS,
            conversational_results=conversational,
            objective_overrides=objective,
        )
    )
    return project_metric_evidence_readiness_v2(publication, **PROVENANCE)


def _readiness_v3(
    context: P1TextAnalysisInput,
    *,
    objective: dict[str, ObjectiveMetricOverride] | None = None,
) -> MetricEvidenceReadinessProjectionV2:
    reconciliation = SemanticUnitReconciler(IDS).reconcile(context).reconciliation
    publication = publish_metric_states_v2(
        project_metric_states_v3(
            context=context,
            reconciliation=reconciliation,
            id_factory=IDS,
            objective_overrides=objective,
        )
    )
    return project_metric_evidence_readiness_v2(publication, **PROVENANCE)


def _readiness_v4(
    context: P1TextAnalysisInput,
) -> MetricEvidenceReadinessProjectionV2:
    reconciliation = SemanticUnitReconciler(IDS).reconcile(context).reconciliation
    publication = publish_metric_states_v2(
        project_metric_states_v4(
            context=context,
            reconciliation=reconciliation,
            id_factory=IDS,
        )
    )
    return project_metric_evidence_readiness_v2(publication, **PROVENANCE)


def _readiness_v5(
    context: P1TextAnalysisInput,
    *,
    objective: dict[str, ObjectiveMetricOverride] | None = None,
) -> MetricEvidenceReadinessProjectionV2:
    reconciliation = SemanticUnitReconciler(IDS).reconcile(context).reconciliation
    publication = publish_metric_states_v2(
        project_metric_states_v5(
            context=context,
            reconciliation=reconciliation,
            id_factory=IDS,
            objective_overrides=objective,
        )
    )
    return project_metric_evidence_readiness_v2(publication, **PROVENANCE)


def _readiness_v6(
    context: P1TextAnalysisInput,
    *,
    evidence: RequirementPlanEvidenceSnapshot | None = None,
) -> MetricEvidenceReadinessProjectionV2:
    reconciliation = SemanticUnitReconciler(IDS).reconcile(context).reconciliation
    publication = publish_metric_states_v2(
        project_metric_states_v6(
            context=context,
            reconciliation=reconciliation,
            id_factory=IDS,
            requirement_plan_evidence=evidence,
        )
    )
    return project_metric_evidence_readiness_v2(publication, **PROVENANCE)


def _single_request_context(*, complete: bool = True) -> P1TextAnalysisInput:
    return _context(
        (
            _message(
                "readiness-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                "Create the fictional widget report.",
            ),
        ),
        label="readiness",
        complete=complete,
    )


def _by_key(projection: MetricEvidenceReadinessProjectionV2) -> dict[str, object]:
    return {item.metric_key: item for item in projection.metrics}


def test_readiness_covers_every_contract_and_restates_run_provenance() -> None:
    projection = _readiness(_single_request_context())

    assert len(projection.metrics) == len(METRIC_CONTRACTS_V2) == 20
    assert tuple(item.metric_key for item in projection.metrics) == tuple(
        item.metric_key for item in METRIC_CONTRACTS_V2
    )
    assert projection.catalog_version == METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION
    assert projection.provider is Provider.SYNTHETIC
    assert projection.provider_version == "synthetic.1"
    assert projection.adapter_version == "synthetic-adapter.1"
    assert projection.source_schema_version == "synthetic-source.1"
    assert projection.metric_projection_version == "metric-contract-v2-projection-2"
    assert projection.canonical_live_snapshot is True
    assert projection.compatibility_preview is False
    assert projection.calibration_state == "not_assessed"
    assert projection.product_metric_eligible is False
    assert all(item.calibration_state == "not_assessed" for item in projection.metrics)
    assert all(item.product_metric_eligible is False for item in projection.metrics)
    for item in projection.metrics:
        contract = next(
            entry
            for entry in METRIC_CONTRACTS_V2
            if entry.metric_key == item.metric_key
        )
        assert item.contract_fingerprint == contract.fingerprint
        assert item.evidence_authority is contract.evidence_authority
        assert item.denominator_basis is contract.denominator_basis


def test_readiness_restates_the_sealed_publication_commitment() -> None:
    context = _single_request_context()
    reconciliation = SemanticUnitReconciler(IDS).reconcile(context).reconciliation
    publication = publish_metric_states_v2(
        project_metric_states_v2(
            context=context,
            reconciliation=reconciliation,
            id_factory=IDS,
        )
    )

    projection = project_metric_evidence_readiness_v2(publication, **PROVENANCE)

    assert projection.publication_fingerprint == metric_publication_v2_fingerprint(
        publication
    )
    assert projection.contract_set_fingerprint == (
        publication.contract_set_fingerprint
    )
    assert projection.publication_key == publication.publication_key
    assert projection.publication_source is publication.source


def test_availability_states_partition_the_twenty_metrics() -> None:
    projection = _readiness(_single_request_context())

    total = (
        projection.measured_count
        + projection.pending_count
        + projection.no_opportunity_count
        + projection.capability_missing_count
        + projection.source_incomplete_count
        + projection.evidence_unresolved_count
        + projection.abstained_count
        + projection.execution_error_count
    )
    assert total == 20


def test_missing_extractors_report_metric_specific_requirements() -> None:
    projection = _readiness(_single_request_context())
    by_key = _by_key(projection)
    expected = {
        "collaboration.ambiguity_resolution": (
            MetricEvidenceReadinessReason.AMBIGUITY_EPISODE_EXTRACTION_REQUIRED
        ),
        "collaboration.clarification_yield": (
            MetricEvidenceReadinessReason.CLARIFICATION_EPISODE_EXTRACTION_REQUIRED
        ),
        "collaboration.exploration_conversion": (
            MetricEvidenceReadinessReason.HYPOTHESIS_EPISODE_EXTRACTION_REQUIRED
        ),
        "collaboration.scope_change_discipline": (
            MetricEvidenceReadinessReason.SCOPE_CHANGE_EPISODE_EXTRACTION_REQUIRED
        ),
        "logic.decomposition_coverage": (
            MetricEvidenceReadinessReason.REQUIREMENT_UNIT_EXTRACTION_REQUIRED
        ),
        "logic.open_loop_closure": (
            MetricEvidenceReadinessReason.OPEN_LOOP_EPISODE_EXTRACTION_REQUIRED
        ),
    }

    for metric_key, reason in expected.items():
        item = by_key[metric_key]
        assert (
            item.availability_state
            is MetricEvidenceAvailabilityState.CAPABILITY_MISSING
        )
        assert item.reason_code is reason
        assert item.observed_contributors == ()
        assert set(item.missing_contributors) == set(item.required_contributors)
    # Six distinct requirements, not one shared "unobservable" bucket.
    assert len({item.reason_code for item in by_key.values()}) > 1
    assert len(set(expected.values())) == 6


def test_objective_metrics_name_the_exact_adapter_authority_set() -> None:
    projection = _readiness(_single_request_context())
    by_key = _by_key(projection)

    expected = {
        "logic.hypothesis_test_linkage": (
            MetricEvidenceReadinessReason
            .HYPOTHESIS_CHAIN_ADAPTER_CAPABILITIES_REQUIRED,
            {
                CapabilityKey.HYPOTHESIS_OPPORTUNITIES,
                CapabilityKey.HYPOTHESIS_EVIDENCE_LINKS,
                CapabilityKey.TOOL_EVENTS,
                CapabilityKey.DECISION_EVENTS,
                CapabilityKey.VERIFICATION_EVENTS,
            },
        ),
        "logic.requirement_action_traceability": (
            MetricEvidenceReadinessReason
            .REQUIREMENT_ACTION_ADAPTER_CAPABILITIES_REQUIRED,
            {
                CapabilityKey.REQUIREMENT_OPPORTUNITIES,
                CapabilityKey.REQUIREMENT_EVIDENCE_LINKS,
                CapabilityKey.TOOL_EVENTS,
            },
        ),
        "outcome.agent_claim_grounding": (
            MetricEvidenceReadinessReason
            .MATERIAL_CLAIM_VERIFICATION_ADAPTER_CAPABILITIES_REQUIRED,
            {
                CapabilityKey.MATERIAL_CLAIM_OPPORTUNITIES,
                CapabilityKey.MATERIAL_CLAIM_EVIDENCE_LINKS,
                CapabilityKey.VERIFICATION_EVENTS,
            },
        ),
        "outcome.first_pass_verification": (
            MetricEvidenceReadinessReason
            .VERIFICATION_TASK_OUTCOME_ADAPTER_CAPABILITIES_REQUIRED,
            {
                CapabilityKey.VERIFICATION_TASK_OPPORTUNITIES,
                CapabilityKey.VERIFICATION_TASK_EVIDENCE_LINKS,
                CapabilityKey.VERIFICATION_EVENTS,
            },
        ),
        "outcome.verified_requirement_coverage": (
            MetricEvidenceReadinessReason
            .REQUIREMENT_VERIFICATION_ADAPTER_CAPABILITIES_REQUIRED,
            {
                CapabilityKey.REQUIREMENT_OPPORTUNITIES,
                CapabilityKey.REQUIREMENT_EVIDENCE_LINKS,
                CapabilityKey.VERIFICATION_EVENTS,
            },
        ),
    }
    for metric_key, (reason, capabilities) in expected.items():
        item = by_key[metric_key]
        assert (
            item.availability_state
            is MetricEvidenceAvailabilityState.CAPABILITY_MISSING
        )
        assert item.reason_code is reason
        assert set(item.required_adapter_capabilities) == capabilities
        assert (
            MetricEvidenceContributor.DECLARED_OBJECTIVE_OPPORTUNITY_SET
            in item.missing_contributors
        )
    assert projection.objective_metric_count == 5
    assert projection.objective_measurable_count == 0
    assert projection.objective_measured_count == 0


def test_measured_metric_reports_every_contributor_and_exact_counts() -> None:
    context = _single_request_context()
    result = SimpleNamespace(
        value_state=MetricValueState.KNOWN,
        fraction=MetricFraction(numerator=2, denominator=3),
        explanation_code="synthetic_rubric_result",
    )

    item = _by_key(
        _readiness(
            context,
            conversational={"prompt.task_definition_coverage": result},
        )
    )["prompt.task_definition_coverage"]

    assert item.availability_state is MetricEvidenceAvailabilityState.MEASURED
    assert item.reason_code is (
        MetricEvidenceReadinessReason.MEASURED_FROM_OWNED_OPPORTUNITIES
    )
    assert item.value_state is MetricValueStateV2.KNOWN
    assert (item.eligible_count, item.met_count, item.not_met_count) == (3, 2, 1)
    assert item.resolved_count == 3
    assert (item.censoring_lower_bound, item.censoring_upper_bound) == (
        2 / 3,
        2 / 3,
    )
    assert item.missing_contributors == ()
    assert set(item.observed_contributors) == set(
        METRIC_EVIDENCE_REQUIREMENTS_V2[item.metric_key].required_contributors
    )


def test_unowned_rubric_focus_is_a_metric_specific_capability_requirement() -> None:
    context = _context(
        (
            _message(
                "owned-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                "Create the fictional widget report.",
            ),
            _message(
                "focus-feedback",
                2,
                TextRole.USER,
                TextMessageKind.FEEDBACK,
                "A neutral fictional remark.",
            ),
        ),
        label="unowned-focus",
    )
    result = SimpleNamespace(
        value_state=MetricValueState.KNOWN,
        fraction=MetricFraction(numerator=3, denominator=3),
        explanation_code="synthetic_rubric_result",
    )

    item = _by_key(
        _readiness(
            context,
            conversational={"prompt.task_definition_coverage": result},
        )
    )["prompt.task_definition_coverage"]

    assert (
        item.availability_state is MetricEvidenceAvailabilityState.CAPABILITY_MISSING
    )
    assert item.reason_code is (
        MetricEvidenceReadinessReason.FOCUS_OWNED_REQUEST_REVISION_REQUIRED
    )
    assert item.eligible_count == item.met_count == 0
    assert item.observed_contributors == ()


def test_pending_objective_metric_keeps_censoring_bounds() -> None:
    override = ObjectiveMetricOverride(
        value_state=MetricValueState.UNKNOWN,
        explanation_code="synthetic_first_pass_open",
        resolved_opportunity_count=1,
        eligible_opportunity_count=2,
        met_opportunity_count=1,
    )

    projection = _readiness(
        _single_request_context(),
        objective={"outcome.first_pass_verification": override},
    )
    item = _by_key(projection)["outcome.first_pass_verification"]

    assert (
        item.availability_state
        is MetricEvidenceAvailabilityState.PENDING_RIGHT_CENSORED
    )
    assert item.reason_code is (
        MetricEvidenceReadinessReason.OPPORTUNITY_RIGHT_CENSORED
    )
    assert (item.censoring_lower_bound, item.censoring_upper_bound) == (0.5, 1.0)
    assert (item.pending_count, item.resolved_count, item.eligible_count) == (
        1,
        1,
        2,
    )
    # A right-censored opportunity proves the denominator and the classifier.
    assert set(item.observed_contributors) == set(item.required_contributors)
    assert projection.objective_measurable_count == 1
    assert projection.objective_measured_count == 0


def test_empty_objective_set_is_no_opportunity_not_capability_missing() -> None:
    override = ObjectiveMetricOverride(
        value_state=MetricValueState.NOT_APPLICABLE,
        explanation_code="typed_verification_task_set_empty",
    )

    projection = _readiness(
        _single_request_context(),
        objective={"outcome.first_pass_verification": override},
    )
    item = _by_key(projection)["outcome.first_pass_verification"]

    assert item.availability_state is MetricEvidenceAvailabilityState.NO_OPPORTUNITY
    assert item.reason_code is (
        MetricEvidenceReadinessReason.NO_ELIGIBLE_OPPORTUNITY_OBSERVED
    )
    assert item.eligible_count == 0
    assert projection.objective_measurable_count == 1
    assert projection.objective_measured_count == 0


def test_measured_objective_count_is_separate_from_adapter_readiness() -> None:
    override = ObjectiveMetricOverride(
        value_state=MetricValueState.KNOWN,
        explanation_code="synthetic_first_pass_closed",
        numerator=1,
        denominator=2,
        resolved_opportunity_count=2,
        eligible_opportunity_count=2,
        met_opportunity_count=1,
    )

    projection = _readiness(
        _single_request_context(),
        objective={"outcome.first_pass_verification": override},
    )

    assert projection.objective_measurable_count == 1
    assert projection.objective_measured_count == 1


def test_incomplete_source_is_distinguished_from_a_missing_capability() -> None:
    result = SimpleNamespace(
        value_state=MetricValueState.KNOWN,
        fraction=MetricFraction(numerator=2, denominator=3),
        explanation_code="synthetic_rubric_result",
    )

    item = _by_key(
        _readiness(
            _single_request_context(complete=False),
            conversational={"prompt.task_definition_coverage": result},
        )
    )["prompt.task_definition_coverage"]

    assert (
        item.availability_state is MetricEvidenceAvailabilityState.SOURCE_INCOMPLETE
    )
    assert item.reason_code is (
        MetricEvidenceReadinessReason.SOURCE_RECONCILIATION_INCOMPLETE
    )


def test_unresolved_classification_is_not_reported_as_no_opportunity() -> None:
    context = _context(
        (
            _message(
                "unresolved-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                "Create the fictional widget report.",
            ),
            _message(
                "unresolved-feedback",
                2,
                TextRole.USER,
                TextMessageKind.FEEDBACK,
                "A neutral fictional comment with no classifiable cue.",
            ),
        ),
        label="unresolved",
    )

    item = _by_key(_readiness(context))["collaboration.rework_candidate_rate"]

    assert (
        item.availability_state
        is MetricEvidenceAvailabilityState.EVIDENCE_UNRESOLVED
    )
    assert item.reason_code is (
        MetricEvidenceReadinessReason.OPPORTUNITY_CLASSIFICATION_UNRESOLVED
    )
    assert item.eligible_count == 1
    assert item.unknown_count == 1
    assert item.resolved_count == 0


def test_declared_profile_absence_has_its_own_reason() -> None:
    item = _by_key(_readiness(_single_request_context()))[
        "prompt.constraint_precision"
    ]

    assert (
        item.availability_state
        is MetricEvidenceAvailabilityState.EVIDENCE_UNRESOLVED
    )
    assert item.reason_code is (
        MetricEvidenceReadinessReason.DECLARED_PROFILE_SLOTS_ABSENT
    )


def test_current_readiness_catalog_is_append_only_and_reads_r5_twenty_rows() -> None:
    projection = _readiness_v5(_single_request_context())

    assert METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION == (
        METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_7
    )
    assert SUPPORTED_METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSIONS[-3:] == (
        METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_5,
        METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_6,
        METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION_7,
    )
    assert projection.metric_projection_version == "metric-contract-v2-projection-5"
    assert len(projection.metrics) == 20
    assert tuple(item.metric_key for item in projection.metrics) == tuple(
        item.metric_key for item in METRIC_CONTRACTS_V2
    )
    assert sum(
        (
            projection.measured_count,
            projection.pending_count,
            projection.no_opportunity_count,
            projection.capability_missing_count,
            projection.source_incomplete_count,
            projection.evidence_unresolved_count,
            projection.abstained_count,
            projection.execution_error_count,
        )
    ) == 20


def test_r6_decomposition_names_reviewed_enumeration_and_disposition_authority() -> None:
    item = _by_key(_readiness_v6(_single_request_context()))[
        "logic.decomposition_coverage"
    ]
    requirement = METRIC_EVIDENCE_REQUIREMENTS_V2_R6[
        "logic.decomposition_coverage"
    ]

    assert item.availability_state is MetricEvidenceAvailabilityState.CAPABILITY_MISSING
    assert item.reason_code is (
        MetricEvidenceReadinessReason.REVIEWED_REQUIREMENT_PLAN_SERVICE_REQUIRED
    )
    assert item.required_contributors == requirement.required_contributors
    assert item.required_contributors == (
        MetricEvidenceContributor.REVIEWED_REQUIREMENT_ENUMERATION,
        MetricEvidenceContributor.REVIEWED_REQUIREMENT_PLAN_DISPOSITION,
    )
    assert item.observed_contributors == ()


def test_r6_service_without_confirmation_names_the_exact_user_action() -> None:
    context = _single_request_context()
    item = _by_key(
        _readiness_v6(
            context,
            evidence=RequirementPlanEvidenceSnapshot(
                session_id=context.session_id,
                source_window_fingerprint=context.analysis_window_fingerprint,
            ),
        )
    )["logic.decomposition_coverage"]

    assert item.value_state is MetricValueStateV2.UNKNOWN
    assert item.capability_available is True
    assert item.source_complete is True
    assert item.availability_state is (
        MetricEvidenceAvailabilityState.EVIDENCE_UNRESOLVED
    )
    assert item.reason_code is (
        MetricEvidenceReadinessReason
        .REVIEWED_REQUIREMENT_PLAN_CONFIRMATION_REQUIRED
    )
    assert item.observed_contributors == ()
    assert item.missing_contributors == item.required_contributors


def test_r5_inherits_r4_lifecycle_and_r3_open_loop_contributor_contracts() -> None:
    by_key = _by_key(_readiness_v5(_single_request_context()))

    for metric_key, requirement in METRIC_EVIDENCE_REQUIREMENTS_V2_R4.items():
        item = by_key[metric_key]
        assert item.availability_state is (
            MetricEvidenceAvailabilityState.CAPABILITY_MISSING
        )
        assert item.reason_code is (
            MetricEvidenceReadinessReason.CONFIRMED_LIFECYCLE_SERVICE_REQUIRED
        )
        assert item.required_contributors == requirement.required_contributors
        assert item.observed_contributors == ()
        assert item.missing_contributors == item.required_contributors

    open_loop = by_key["logic.open_loop_closure"]
    assert open_loop.reason_code is (
        MetricEvidenceReadinessReason.EXPLICIT_PLAN_EPISODE_REQUIRED
    )
    assert open_loop.required_contributors == (
        MetricEvidenceContributor.DOCUMENTED_PLAN_MESSAGE,
        MetricEvidenceContributor.EXPLICIT_PLAN_SUPERSESSION_LINK,
    )


def test_r4_rows_remain_frozen_while_r5_stops_claiming_empty_profile_input() -> None:
    context = _single_request_context()
    r4 = _by_key(_readiness_v4(context))
    r5 = _by_key(_readiness_v5(context))
    profile_metrics = {
        "prompt.constraint_precision",
        "prompt.acceptance_testability",
        "prompt.deliverable_contract",
    }

    for metric_key in set(r4) - profile_metrics:
        assert r5[metric_key] == r4[metric_key]
    for metric_key in profile_metrics:
        assert r4[metric_key].observed_contributors == (
            MetricEvidenceContributor.DECLARED_TASK_PROFILE,
        )
        assert r5[metric_key].observed_contributors == ()
        assert r5[metric_key].missing_contributors == (
            MetricEvidenceContributor.DECLARED_TASK_PROFILE,
            MetricEvidenceContributor.CANONICAL_REQUEST_TEXT,
        )
        assert r5[metric_key].value_state is MetricValueStateV2.UNKNOWN
        assert r5[metric_key].reason_code is (
            MetricEvidenceReadinessReason.DECLARED_PROFILE_SLOTS_ABSENT
        )


def test_r5_configured_profile_families_are_known_with_exact_contributors() -> None:
    profile = TextTaskProfile(
        applicability=(),
        expected_constraint_kinds=(ConstraintKind.PRIVACY, ConstraintKind.COST),
        expected_outcome_count=3,
        expected_deliverable_slots=(
            DeliverableSlot.ARTIFACT,
            DeliverableSlot.FORMAT,
        ),
    )
    context = _context(
        (
            _message(
                "r5-configured-profile-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                (
                    "Create a private report. "
                    "The report must return exactly three rows. "
                    "Validate that the report exists without errors."
                ),
            ),
        ),
        label="r5-configured-profile",
        task_profile=profile,
    )
    by_key = _by_key(_readiness_v5(context))
    expected_counts = {
        "prompt.constraint_precision": (1, 2),
        "prompt.acceptance_testability": (2, 3),
        "prompt.deliverable_contract": (1, 2),
    }

    for metric_key, (met, eligible) in expected_counts.items():
        item = by_key[metric_key]
        assert item.value_state is MetricValueStateV2.KNOWN
        assert item.availability_state is MetricEvidenceAvailabilityState.MEASURED
        assert (item.met_count, item.eligible_count) == (met, eligible)
        assert item.observed_contributors == (
            MetricEvidenceContributor.DECLARED_TASK_PROFILE,
            MetricEvidenceContributor.CANONICAL_REQUEST_TEXT,
        )
        assert item.missing_contributors == ()


def test_r5_partial_profile_keeps_unconfigured_families_unknown_not_na() -> None:
    context = _context(
        (
            _message(
                "r5-partial-profile-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                "Create a private report.",
            ),
        ),
        label="r5-partial-profile",
        task_profile=TextTaskProfile(
            applicability=(),
            expected_constraint_kinds=(ConstraintKind.PRIVACY,),
        ),
    )
    by_key = _by_key(_readiness_v5(context))

    configured = by_key["prompt.constraint_precision"]
    assert configured.value_state is MetricValueStateV2.KNOWN
    assert (configured.met_count, configured.eligible_count) == (1, 1)
    for metric_key in (
        "prompt.acceptance_testability",
        "prompt.deliverable_contract",
    ):
        item = by_key[metric_key]
        assert item.value_state is MetricValueStateV2.UNKNOWN
        assert item.value_state is not MetricValueStateV2.NOT_APPLICABLE
        assert item.availability_state is (
            MetricEvidenceAvailabilityState.EVIDENCE_UNRESOLVED
        )
        assert item.reason_code is (
            MetricEvidenceReadinessReason.DECLARED_PROFILE_SLOTS_ABSENT
        )
        assert item.eligible_count == 0
        assert item.observed_contributors == ()


def test_r5_inherits_objective_receipt_bound_withholding_reason() -> None:
    item = _by_key(
        _readiness_v5(
            _single_request_context(),
            objective={
                "outcome.agent_claim_grounding": ObjectiveMetricOverride(
                    value_state=MetricValueState.UNKNOWN,
                    explanation_code=(
                        "typed_objective_opportunity_count_exceeds_receipt_bound"
                    ),
                    withholding_cause=(
                        ObjectiveWithholdingCause.OPPORTUNITY_BOUND_EXCEEDED
                    ),
                )
            },
        )
    )["outcome.agent_claim_grounding"]

    assert item.availability_state is (
        MetricEvidenceAvailabilityState.EVIDENCE_UNRESOLVED
    )
    assert item.reason_code is (
        MetricEvidenceReadinessReason.OPPORTUNITY_SET_EXCEEDS_RECEIPT_BOUND
    )


def test_readiness_serializes_no_identifiers_or_text() -> None:
    canary = "synthetic-private-canary-readiness-7c31"
    context = _context(
        (
            _message(
                "private-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                canary,
            ),
        ),
        label="privacy",
    )

    projection = _readiness(context)
    payload = projection.model_dump_json()

    assert canary not in payload
    assert context.session_id not in payload
    assert context.focus_message_id not in payload
    assert context.analysis_window_fingerprint not in payload


def test_a_forged_measured_readiness_row_is_rejected() -> None:
    projection = _readiness(_single_request_context())
    payload = projection.model_dump()
    payload["metrics"][0]["availability_state"] = (
        MetricEvidenceAvailabilityState.MEASURED.value
    )

    with pytest.raises(ValidationError, match="measured"):
        MetricEvidenceReadinessProjectionV2.model_validate(payload)


def test_forged_availability_counts_are_rejected() -> None:
    projection = _readiness(_single_request_context())
    payload = projection.model_dump()
    payload["measured_count"] = payload["measured_count"] + 1

    with pytest.raises(ValidationError, match="counts are inconsistent"):
        MetricEvidenceReadinessProjectionV2.model_validate(payload)


def test_r3_open_loop_readiness_names_the_exact_structural_evidence() -> None:
    plan = _message(
        "r3-plan",
        2,
        TextRole.AGENT,
        TextMessageKind.PLAN,
        "Plan the fictional export.",
    )
    context = _context(
        (
            _message(
                "r3-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                "Create the fictional export.",
            ),
            plan,
            _message(
                "r3-action",
                3,
                TextRole.AGENT,
                TextMessageKind.ACTION,
                "Completed the fictional export.",
                supersedes=(plan.message_id,),
            ),
        ),
        label="r3-open-loop-readiness",
    )

    projection = _readiness_v3(context)
    item = _by_key(projection)["logic.open_loop_closure"]

    assert projection.metric_projection_version == "metric-contract-v2-projection-3"
    assert item.availability_state is MetricEvidenceAvailabilityState.MEASURED
    assert item.reason_code is (
        MetricEvidenceReadinessReason.MEASURED_FROM_OWNED_OPPORTUNITIES
    )
    assert item.required_contributors == (
        MetricEvidenceContributor.DOCUMENTED_PLAN_MESSAGE,
        MetricEvidenceContributor.EXPLICIT_PLAN_SUPERSESSION_LINK,
    )
    assert item.observed_contributors == item.required_contributors
    assert (item.met_count, item.eligible_count) == (1, 1)


def test_r3_unlinked_plan_readiness_preserves_pending_bounds() -> None:
    context = _context(
        (
            _message(
                "pending-request",
                1,
                TextRole.USER,
                TextMessageKind.REQUEST,
                "Create the fictional export.",
            ),
            _message(
                "pending-plan",
                2,
                TextRole.AGENT,
                TextMessageKind.PLAN,
                "Plan the fictional export.",
            ),
        ),
        label="r3-pending-readiness",
    )

    item = _by_key(_readiness_v3(context))["logic.open_loop_closure"]

    assert item.availability_state is (
        MetricEvidenceAvailabilityState.PENDING_RIGHT_CENSORED
    )
    assert item.pending_count == 1
    assert (item.censoring_lower_bound, item.censoring_upper_bound) == (0.0, 1.0)


def test_r3_no_plan_is_actionable_unknown_not_no_opportunity() -> None:
    item = _by_key(_readiness_v3(_single_request_context()))[
        "logic.open_loop_closure"
    ]

    assert item.availability_state is MetricEvidenceAvailabilityState.CAPABILITY_MISSING
    assert item.reason_code is (
        MetricEvidenceReadinessReason.EXPLICIT_PLAN_EPISODE_REQUIRED
    )
    assert item.value_state is MetricValueStateV2.UNKNOWN
    assert item.eligible_count == 0


def test_r3_objective_withholding_causes_remain_distinct_in_readiness() -> None:
    context = _single_request_context()
    extraction_incomplete = ObjectiveMetricOverride(
        value_state=MetricValueState.UNKNOWN,
        explanation_code="typed_objective_extraction_incomplete",
        withholding_cause=ObjectiveWithholdingCause.EXTRACTION_INCOMPLETE,
    )
    receipt_bound = ObjectiveMetricOverride(
        value_state=MetricValueState.UNKNOWN,
        explanation_code="typed_objective_opportunity_count_exceeds_receipt_bound",
        withholding_cause=ObjectiveWithholdingCause.OPPORTUNITY_BOUND_EXCEEDED,
    )

    incomplete_item = _by_key(
        _readiness_v3(
            context,
            objective={"outcome.agent_claim_grounding": extraction_incomplete},
        )
    )["outcome.agent_claim_grounding"]
    bound_item = _by_key(
        _readiness_v3(
            context,
            objective={"outcome.agent_claim_grounding": receipt_bound},
        )
    )["outcome.agent_claim_grounding"]

    assert incomplete_item.availability_state is (
        MetricEvidenceAvailabilityState.SOURCE_INCOMPLETE
    )
    assert incomplete_item.reason_code is (
        MetricEvidenceReadinessReason.SOURCE_RECONCILIATION_INCOMPLETE
    )
    assert incomplete_item.capability_available is True
    assert incomplete_item.source_complete is False
    assert incomplete_item.observed_contributors == ()
    assert bound_item.availability_state is (
        MetricEvidenceAvailabilityState.EVIDENCE_UNRESOLVED
    )
    assert bound_item.reason_code is (
        MetricEvidenceReadinessReason.OPPORTUNITY_SET_EXCEEDS_RECEIPT_BOUND
    )
    assert bound_item.capability_available is True
    assert bound_item.source_complete is True


def test_r1_known_rubric_readiness_does_not_claim_focus_ownership() -> None:
    context = _single_request_context()
    reconciliation = SemanticUnitReconciler(IDS).reconcile(context).reconciliation
    result = SimpleNamespace(
        value_state=MetricValueState.KNOWN,
        fraction=MetricFraction(numerator=3, denominator=3),
        explanation_code="synthetic-rubric-known",
    )
    r2_states = project_metric_states_v2(
        context=context,
        reconciliation=reconciliation,
        id_factory=IDS,
        conversational_results={"prompt.task_definition_coverage": result},
    )
    r1_states = tuple(
        state.model_copy(
            update={"projection_version": "metric-contract-v2-projection-1"}
        )
        for state in r2_states
    )
    publication = publish_metric_states_v2(
        _issue_metric_state_projection(r1_states, compatibility=False)
    )

    item = _by_key(
        project_metric_evidence_readiness_v2(publication, **PROVENANCE)
    )["prompt.task_definition_coverage"]

    assert item.availability_state is MetricEvidenceAvailabilityState.MEASURED
    assert item.reason_code is (
        MetricEvidenceReadinessReason.MEASURED_UNDER_SUPERSEDED_PROJECTION_IDENTITY
    )
    assert (
        MetricEvidenceContributor.FOCUS_OWNED_REQUEST_REVISION
        not in item.observed_contributors
    )
    assert (
        MetricEvidenceContributor.FOCUS_OWNED_REQUEST_REVISION
        in item.missing_contributors
    )
def test_r8_verified_requirement_readiness_never_invents_a_verifier_receipt() -> None:
    contract = next(
        item
        for item in METRIC_CONTRACTS_V2
        if item.metric_key == "outcome.verified_requirement_coverage"
    )
    state = MetricStateV2(
        metric_key=contract.metric_key,
        contract_version=contract.contract_version,
        contract_fingerprint=contract.fingerprint,
        evidence_authority=contract.evidence_authority,
        value_state=MetricValueStateV2.KNOWN,
        explanation_code="app_issued_verified_requirement_coverage",
        numerator=1,
        denominator=1,
        numeric_value=1.0,
        censoring_lower_bound=1.0,
        censoring_upper_bound=1.0,
        statistics=OpportunityStatistics(
            metric_key=contract.metric_key,
            denominator_basis=contract.denominator_basis,
            opportunity_unit_kind=contract.opportunity_unit_kind,
            capability_available=True,
            source_complete=True,
            eligible_count=1,
            met_count=1,
            not_met_count=0,
            pending_count=0,
            unknown_count=0,
            superseded_excluded_count=0,
            distinct_owner_count=1,
        ),
        projection_version=METRIC_PROJECTION_V2_VERSION_8,
    )

    row = metric_evidence_readiness_row(state)

    assert row.observed_contributors == (
        MetricEvidenceContributor.DECLARED_OBJECTIVE_OPPORTUNITY_SET,
    )
    assert MetricEvidenceContributor.TYPED_VERIFICATION_RECEIPT in (
        row.missing_contributors
    )
