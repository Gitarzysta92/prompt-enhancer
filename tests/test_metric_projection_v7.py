from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr, ValidationError

from prompt_enhancer.application.analysis.evidence_contracts import (
    ActionFamily,
    ActionState,
    TypedEvidenceProvenance,
)
from prompt_enhancer.application.analysis.metric_contract_v2 import MetricValueStateV2
from prompt_enhancer.application.analysis.metric_evidence_readiness_v2 import (
    METRIC_EVIDENCE_REQUIREMENTS_V2_R7,
    MetricEvidenceAvailabilityState,
    MetricEvidenceContributor,
    MetricEvidenceReadinessReason,
    metric_evidence_readiness_row,
)
from prompt_enhancer.application.analysis.metric_projection_v6 import (
    project_metric_states_v6,
)
from prompt_enhancer.application.analysis.metric_projection_v7 import (
    METRIC_PROJECTION_V7_VERSION,
    REASON_REQUIREMENT_ACTION_CONFIRMATION_REQUIRED,
    REASON_REQUIREMENT_ACTION_INVALID,
    REASON_REQUIREMENT_ACTION_OVERFLOW,
    REASON_REQUIREMENT_ACTION_SOURCE_INCOMPLETE,
    REASON_REQUIREMENT_ACTION_UNAVAILABLE,
    project_metric_states_v7,
)
from prompt_enhancer.application.analysis.provider_evidence import (
    SAFE_EVENT_EVIDENCE_DECODER_KEY,
    SAFE_EVENT_EVIDENCE_DECODER_VERSION_4,
)
from prompt_enhancer.application.analysis.requirement_action_evidence import (
    ConfirmedRequirementActionLink,
    REQUIREMENT_ACTION_METRIC_KEY,
    RequirementActionCandidate,
    RequirementActionCandidateManifest,
    RequirementActionEvidenceSnapshot,
    RequirementActionRequirement,
    requirement_action_candidate_manifest_fingerprint,
    requirement_action_evidence_snapshot_fingerprint,
    requirement_plan_snapshot_fingerprint,
)
from prompt_enhancer.application.analysis.requirement_plan_evidence import (
    REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
    ConfirmedPlanEvidence,
    ConfirmedRequirementEvidence,
    ExcludedRequirementClause,
    PlanCoordinate,
    RequirementCoordinate,
    RequirementDisposition,
    RequirementPlanEvidenceSnapshot,
    RequirementPlanExclusionReason,
    RequirementPlanProducerReceipt,
)
from prompt_enhancer.application.analysis.semantic_units import SemanticUnitReconciler
from prompt_enhancer.application.analysis.text_contracts import (
    EphemeralRedactedMessage,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextRole,
    TextTaskProfile,
)
from prompt_enhancer.application.providers import (
    CapabilityKey,
    DecoderDescriptor,
    ProviderIdentity,
    ProviderSurface,
    SchemaArtifactKind,
    SchemaArtifactProvenance,
)
from prompt_enhancer.domain import EventKind, Provider, ToolCategory
from prompt_enhancer.infrastructure.providers.claude_code_hooks.text_source import (
    TEXT_ADAPTER_VERSION as CLAUDE_TEXT_ADAPTER_VERSION,
    TEXT_SOURCE_SCHEMA_VERSION as CLAUDE_TEXT_SOURCE_SCHEMA_VERSION,
)
from prompt_enhancer.infrastructure.providers.claude_code_hooks.transcript_adapter import (
    TRANSCRIPT_ADAPTER_VERSION,
    TRANSCRIPT_SOURCE_SCHEMA_VERSION,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.content_contracts import (
    TEXT_CONTENT_ADAPTER_VERSION,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.contracts import (
    ADAPTER_VERSION as CODEX_EVENT_ADAPTER_VERSION,
    SOURCE_SCHEMA_VERSION as CODEX_SOURCE_SCHEMA_VERSION,
)


def _id(label: str) -> str:
    return hashlib.sha256(f"synthetic-v7:{label}".encode()).hexdigest()


class _Ids:
    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str:
        return hashlib.sha256("\x1f".join((namespace, *values)).encode()).hexdigest()

    def fingerprint_secret(self, namespace, values, secret):  # type: ignore[no-untyped-def]
        return hashlib.sha256(
            "\x1f".join((namespace, *values, secret.get_secret_value())).encode()
        ).hexdigest()


IDS = _Ids()
PRODUCER_RECEIPT = RequirementPlanProducerReceipt(
    claim_fingerprint=_id("producer-claim"),
)


def _context(
    *,
    with_request: bool = True,
    provider: Provider = Provider.SYNTHETIC,
    adapter_version: str = "synthetic-adapter.1",
    source_schema_version: str = "synthetic-source.1",
) -> P1TextAnalysisInput:
    request = EphemeralRedactedMessage(
        message_id=_id("request"),
        sequence=1,
        role=TextRole.USER,
        kind=TextMessageKind.REQUEST,
        language=TextLanguage.ENGLISH,
        text=SecretStr(
            "Create the fictional export. Add a bounded test. Document the result."
        ),
    )
    plan = EphemeralRedactedMessage(
        message_id=_id("plan"),
        sequence=2,
        role=TextRole.AGENT,
        kind=TextMessageKind.PLAN,
        language=TextLanguage.ENGLISH,
        text=SecretStr("Implement the export. Run the bounded test."),
    )
    messages = (request, plan) if with_request else (plan,)
    return P1TextAnalysisInput(
        provider=provider,
        session_id=_id("session"),
        provider_version="synthetic.1",
        adapter_version=adapter_version,
        source_schema_version=source_schema_version,
        content_schema_version="synthetic-content.1",
        redactor_version="synthetic-redactor.1",
        text_extraction_complete=True,
        available_message_kinds=frozenset(item.kind for item in messages),
        analysis_window_fingerprint=_id("window"),
        focus_message_id=messages[0].message_id,
        observed_message_count=len(messages),
        eligible_message_count=len(messages),
        messages=messages,
        task_profile=TextTaskProfile(applicability=()),
    )


def _safe_event_descriptor(
    context: P1TextAnalysisInput,
    *,
    adapter_version: str | None = None,
    source_schema_version: str | None = None,
) -> DecoderDescriptor:
    return DecoderDescriptor(
        provider=ProviderIdentity(key=context.provider.value),
        surface=ProviderSurface.OPERATIONAL_EVENTS,
        adapter_version=adapter_version or context.adapter_version,
        decoder_key=SAFE_EVENT_EVIDENCE_DECODER_KEY,
        decoder_version=SAFE_EVENT_EVIDENCE_DECODER_VERSION_4,
        wire_schema_family="synthetic-safe-events",
        canonical_schema_version=(
            source_schema_version or context.source_schema_version
        ),
        schema_artifact=SchemaArtifactProvenance(
            artifact_key="synthetic-safe-events",
            artifact_version="1",
            kind=SchemaArtifactKind.SYNTHETIC,
        ),
        capabilities=(CapabilityKey.TOOL_EVENTS,),
    )


def _plan_snapshot(
    context: P1TextAnalysisInput,
    classifications: tuple[bool, ...],
) -> RequirementPlanEvidenceSnapshot:
    plan_id = _id("plan-unit")
    requirements = tuple(
        sorted(
            (
                ConfirmedRequirementEvidence(
                    requirement_id=_id(f"requirement-{index}"),
                    coordinate=RequirementCoordinate(
                        message_sequence=1,
                        clause_index=index,
                    ),
                    disposition=RequirementDisposition.LINKED,
                    linked_plan_ids=(plan_id,),
                )
                for index, active in enumerate(classifications)
                if active
            ),
            key=lambda item: item.requirement_id,
        )
    )
    excluded = tuple(
        ExcludedRequirementClause(
            coordinate=RequirementCoordinate(
                message_sequence=1,
                clause_index=index,
            ),
            reason=RequirementPlanExclusionReason.NOT_REQUIREMENT,
        )
        for index, active in enumerate(classifications)
        if not active
    )
    return RequirementPlanEvidenceSnapshot(
        session_id=context.session_id,
        source_window_fingerprint=context.analysis_window_fingerprint,
        confirmation_id=_id("plan-confirmation"),
        proposal_id=_id("plan-proposal"),
        producer_receipt=PRODUCER_RECEIPT,
        review_rubric_version=REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
        requirements=requirements,
        excluded_user_clauses=excluded,
        plan_items=(
            ConfirmedPlanEvidence(
                plan_id=plan_id,
                coordinate=PlanCoordinate(message_sequence=2, clause_index=0),
            ),
        ),
        complete_user_clause_classification=True,
    )


def _manifest(
    context: P1TextAnalysisInput,
    states: tuple[ActionState, ...],
    descriptor: DecoderDescriptor | None = None,
):  # type: ignore[no-untyped-def]
    descriptor = descriptor or _safe_event_descriptor(context)
    provenance = TypedEvidenceProvenance(
        provider=context.provider,
        provider_version=context.provider_version,
        adapter_version=descriptor.adapter_version,
        decoder_key=SAFE_EVENT_EVIDENCE_DECODER_KEY,
        decoder_version=SAFE_EVENT_EVIDENCE_DECODER_VERSION_4,
        source_schema_version=descriptor.canonical_schema_version,
        extraction_complete=True,
    )
    actions = tuple(
        RequirementActionCandidate(
            candidate_index=index,
            action_id=_id(f"action-{index}"),
            source_reference_id=_id(f"event-{index}"),
            sequence=(index + 1) * 4,
            event_kind=EventKind.TOOL_END,
            tool_category=ToolCategory.COMMAND,
            occurred_at=datetime(2040, 1, 1, 10, index, tzinfo=UTC),
            family=ActionFamily.COMMAND,
            state=state,
        )
        for index, state in enumerate(states)
    )
    provisional = RequirementActionCandidateManifest(
        session_id=context.session_id,
        source_run_id=_id("source-run"),
        source_window_fingerprint=context.analysis_window_fingerprint,
        provenance=provenance,
        extraction_complete=True,
        enumeration_complete=True,
        actions=actions,
        manifest_fingerprint="0" * 64,
    )
    return provisional.model_copy(
        update={
            "manifest_fingerprint": (
                requirement_action_candidate_manifest_fingerprint(provisional)
            )
        }
    )


def _action_snapshot(
    context: P1TextAnalysisInput,
    plan: RequirementPlanEvidenceSnapshot,
    states: tuple[ActionState, ...],
    links: tuple[tuple[int, ...], ...],
    descriptor: DecoderDescriptor | None = None,
) -> RequirementActionEvidenceSnapshot:
    manifest = _manifest(context, states, descriptor)
    requirements = tuple(
        RequirementActionRequirement(
            requirement_index=index,
            requirement_id=item.requirement_id,
            coordinate=item.coordinate,
        )
        for index, item in enumerate(plan.requirements)
    )
    provisional = RequirementActionEvidenceSnapshot(
        session_id=context.session_id,
        source_run_id=manifest.source_run_id,
        source_window_fingerprint=context.analysis_window_fingerprint,
        requirement_plan_confirmation_id=plan.confirmation_id,
        requirement_plan_evidence_fingerprint=(
            requirement_plan_snapshot_fingerprint(plan, IDS)
        ),
            confirmation_id=_id("action-confirmation"),
            proposal_id=_id("action-proposal"),
            reviewed_descriptor_set_fingerprint=_id("reviewed-descriptors"),
            producer_receipt=PRODUCER_RECEIPT,
        candidate_manifest=manifest,
        requirements=requirements,
        links=tuple(
            ConfirmedRequirementActionLink(
                requirement_id=requirement.requirement_id,
                action_ids=tuple(
                    sorted(manifest.actions[index].action_id for index in indexes)
                ),
            )
            for requirement, indexes in zip(requirements, links, strict=True)
        ),
        complete_requirement_enumeration=True,
        complete_action_candidate_enumeration=True,
        complete_requirement_link_classification=True,
        evidence_fingerprint=_id("action-evidence"),
    )
    return provisional.model_copy(
        update={
            "evidence_fingerprint": (
                requirement_action_evidence_snapshot_fingerprint(
                    provisional,
                    IDS,
                )
            )
        }
    )


def _project(
    context: P1TextAnalysisInput,
    plan: RequirementPlanEvidenceSnapshot,
    action: RequirementActionEvidenceSnapshot | None,
    *,
    candidate_manifest_overflow: bool = False,
    candidate_source_incomplete: bool = False,
    requirement_action_binding_invalid: bool = False,
    requirement_action_descriptor: DecoderDescriptor | None = None,
):  # type: ignore[no-untyped-def]
    reconciliation = SemanticUnitReconciler(IDS).reconcile(context).reconciliation
    states = project_metric_states_v7(
        context=context,
        reconciliation=reconciliation,
        id_factory=IDS,
        requirement_plan_evidence=plan,
        requirement_action_evidence=action,
        requirement_action_descriptor=(
            requirement_action_descriptor or _safe_event_descriptor(context)
        ),
        candidate_manifest_overflow=candidate_manifest_overflow,
        candidate_source_incomplete=candidate_source_incomplete,
        requirement_action_binding_invalid=requirement_action_binding_invalid,
    )
    assert len(states) == 20
    assert {item.projection_version for item in states} == {
        METRIC_PROJECTION_V7_VERSION
    }
    return states, next(
        item for item in states if item.metric_key == REQUIREMENT_ACTION_METRIC_KEY
    )


def test_absent_requirement_action_authority_is_named_unknown_and_preserves_r6() -> None:
    context = _context()
    plan = _plan_snapshot(context, (True, True, True))
    states, state = _project(context, plan, None)

    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.explanation_code == REASON_REQUIREMENT_ACTION_UNAVAILABLE
    assert state.numerator is state.denominator is state.numeric_value is None
    assert state.statistics.capability_available is False
    assert state.statistics.eligible_count == 3
    assert state.statistics.unknown_count == 3

    reconciliation = SemanticUnitReconciler(IDS).reconcile(context).reconciliation
    inherited = project_metric_states_v6(
        context=context,
        reconciliation=reconciliation,
        id_factory=IDS,
        requirement_plan_evidence=plan,
    )
    inherited_by_key = {item.metric_key: item for item in inherited}
    for item in states:
        if item.metric_key == REQUIREMENT_ACTION_METRIC_KEY:
            continue
        expected = inherited_by_key[item.metric_key].model_copy(
            update={"projection_version": METRIC_PROJECTION_V7_VERSION}
        )
        assert item == expected


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("projection_version", "metric-contract-v2-projection-6"),
        ("explanation_code", REASON_REQUIREMENT_ACTION_CONFIRMATION_REQUIRED),
        ("value_state", "abstained"),
        ("statistics.source_complete", False),
        ("statistics.met_count", 1),
    ),
)
def test_unavailable_nonempty_denominator_is_an_exact_r7_only_shape(
    field: str,
    value: object,
) -> None:
    context = _context()
    _, state = _project(context, _plan_snapshot(context, (True, True, True)), None)
    payload = state.model_dump(mode="json")
    if field.startswith("statistics."):
        payload["statistics"][field.removeprefix("statistics.")] = value
        if field == "statistics.met_count":
            payload["statistics"]["unknown_count"] = 2
    else:
        payload[field] = value

    with pytest.raises(
        ValidationError,
        match="unavailable opportunity family cannot be eligible",
    ):
        type(state).model_validate(payload)


@pytest.mark.parametrize(
    "plan_drift",
    ("wrong_window", "unconfirmed"),
)
@pytest.mark.parametrize(
    "early_marker",
    ("unavailable", "overflow", "source_incomplete", "binding_invalid"),
)
def test_invalid_r6_plan_never_defines_an_early_r7_action_denominator(
    plan_drift: str,
    early_marker: str,
) -> None:
    context = _context()
    plan = _plan_snapshot(context, (True, True, True))
    if plan_drift == "wrong_window":
        plan = plan.model_copy(update={"source_window_fingerprint": _id("wrong")})
    else:
        plan = plan.model_copy(
            update={"complete_user_clause_classification": False}
        )
    kwargs = {
        "candidate_manifest_overflow": early_marker == "overflow",
        "candidate_source_incomplete": early_marker == "source_incomplete",
        "requirement_action_binding_invalid": early_marker == "binding_invalid",
    }
    states, action = _project(context, plan, None, **kwargs)
    decomposition = next(
        item for item in states if item.metric_key == "logic.decomposition_coverage"
    )

    assert decomposition.explanation_code != "reviewed_requirement_plan_links"
    assert decomposition.statistics.eligible_count == 0
    assert action.statistics.eligible_count == 0
    assert action.statistics.unknown_count == 0


def test_unconfirmed_review_is_awaiting_not_a_zero() -> None:
    context = _context()
    plan = _plan_snapshot(context, (True, True, True))
    unconfirmed = RequirementActionEvidenceSnapshot(
        session_id=context.session_id,
        source_window_fingerprint=context.analysis_window_fingerprint,
    )

    _, state = _project(context, plan, unconfirmed)

    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.explanation_code == REASON_REQUIREMENT_ACTION_CONFIRMATION_REQUIRED
    assert state.statistics.eligible_count == 3
    assert state.statistics.unknown_count == 3


@pytest.mark.parametrize(
    (
        "marker",
        "reason",
        "capability_available",
        "source_complete",
    ),
    (
        (
            "unavailable",
            REASON_REQUIREMENT_ACTION_UNAVAILABLE,
            False,
            True,
        ),
        (
            "awaiting",
            REASON_REQUIREMENT_ACTION_CONFIRMATION_REQUIRED,
            True,
            True,
        ),
        (
            "source_incomplete",
            REASON_REQUIREMENT_ACTION_SOURCE_INCOMPLETE,
            True,
            False,
        ),
        (
            "binding_invalid",
            REASON_REQUIREMENT_ACTION_INVALID,
            True,
            False,
        ),
        (
            "overflow",
            REASON_REQUIREMENT_ACTION_OVERFLOW,
            True,
            True,
        ),
    ),
)
def test_every_unresolved_marker_preserves_the_reviewed_r6_denominator(
    marker: str,
    reason: str,
    capability_available: bool,
    source_complete: bool,
) -> None:
    context = _context()
    plan = _plan_snapshot(context, (True, True, True))
    evidence = None
    if marker == "awaiting":
        evidence = RequirementActionEvidenceSnapshot(
            session_id=context.session_id,
            source_window_fingerprint=context.analysis_window_fingerprint,
        )
    _, state = _project(
        context,
        plan,
        evidence,
        candidate_manifest_overflow=marker == "overflow",
        candidate_source_incomplete=marker == "source_incomplete",
        requirement_action_binding_invalid=marker == "binding_invalid",
    )

    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.explanation_code == reason
    assert state.statistics.capability_available is capability_available
    assert state.statistics.source_complete is source_complete
    assert state.statistics.eligible_count == 3
    assert state.statistics.unknown_count == 3
    assert (
        state.statistics.met_count,
        state.statistics.not_met_count,
        state.statistics.pending_count,
    ) == (0, 0, 0)


@pytest.mark.parametrize(
    "missing_authority",
    ("proposal_id", "producer_receipt", "review_rubric_version"),
)
def test_shape_invalid_plan_snapshot_cannot_define_the_r7_denominator(
    missing_authority: str,
) -> None:
    context = _context()
    malformed = _plan_snapshot(context, (True, True, True)).model_copy(
        update={missing_authority: None}
    )

    states, action = _project(context, malformed, None)
    decomposition = next(
        item for item in states if item.metric_key == "logic.decomposition_coverage"
    )

    assert decomposition.value_state is MetricValueStateV2.UNKNOWN
    assert decomposition.statistics.eligible_count == 0
    assert action.statistics.eligible_count == 0
    assert action.statistics.unknown_count == 0


def test_pending_reviewed_r6_denominator_is_inherited_as_all_unknown() -> None:
    context = _context()
    plan = _plan_snapshot(context, (True, True, True))
    pending = plan.requirements[0].model_copy(
        update={
            "disposition": RequirementDisposition.PENDING,
            "linked_plan_ids": (),
        }
    )
    plan = plan.model_copy(
        update={"requirements": (pending, *plan.requirements[1:])}
    )

    states, action = _project(context, plan, None)
    decomposition = next(
        item for item in states if item.metric_key == "logic.decomposition_coverage"
    )

    assert decomposition.value_state is MetricValueStateV2.PENDING
    assert decomposition.statistics.eligible_count == 3
    assert decomposition.statistics.met_count == 2
    assert decomposition.statistics.pending_count == 1
    assert (
        decomposition.censoring_lower_bound,
        decomposition.censoring_upper_bound,
    ) == (2 / 3, 1.0)
    assert action.statistics.eligible_count == 3
    assert action.statistics.unknown_count == 3


def test_complete_review_resolves_completed_failed_and_explicit_empty_links() -> None:
    context = _context()
    plan = _plan_snapshot(context, (True, True, True))
    action = _action_snapshot(
        context,
        plan,
        (ActionState.COMPLETED, ActionState.FAILED),
        ((0,), (1,), ()),
    )

    _, state = _project(context, plan, action)

    assert state.value_state is MetricValueStateV2.KNOWN
    assert (state.numerator, state.denominator, state.numeric_value) == (
        1,
        3,
        1 / 3,
    )
    readiness = metric_evidence_readiness_row(state)
    assert readiness.availability_state is MetricEvidenceAvailabilityState.MEASURED
    assert readiness.required_contributors == (
        MetricEvidenceContributor.REVIEWED_REQUIREMENT_ENUMERATION,
        MetricEvidenceContributor.REVIEWED_REQUIREMENT_ACTION_LINK,
        MetricEvidenceContributor.SAFE_ACTION_CANDIDATE_ENUMERATION,
    )
    assert readiness.required_contributors == (
        METRIC_EVIDENCE_REQUIREMENTS_V2_R7[
            REQUIREMENT_ACTION_METRIC_KEY
        ].required_contributors
    )
    assert readiness.observed_contributors == readiness.required_contributors
    assert readiness.missing_contributors == ()


@pytest.mark.parametrize(
    (
        "provider",
        "text_adapter_version",
        "text_source_schema_version",
        "event_adapter_version",
        "event_source_schema_version",
    ),
    (
        (
            Provider.CODEX,
            TEXT_CONTENT_ADAPTER_VERSION,
            CODEX_SOURCE_SCHEMA_VERSION,
            CODEX_EVENT_ADAPTER_VERSION,
            CODEX_SOURCE_SCHEMA_VERSION,
        ),
        (
            Provider.CLAUDE_CODE,
            CLAUDE_TEXT_ADAPTER_VERSION,
            CLAUDE_TEXT_SOURCE_SCHEMA_VERSION,
            TRANSCRIPT_ADAPTER_VERSION,
            TRANSCRIPT_SOURCE_SCHEMA_VERSION,
        ),
    ),
)
def test_real_provider_text_and_safe_event_planes_are_validated_separately(
    provider: Provider,
    text_adapter_version: str,
    text_source_schema_version: str,
    event_adapter_version: str,
    event_source_schema_version: str,
) -> None:
    context = _context(
        provider=provider,
        adapter_version=text_adapter_version,
        source_schema_version=text_source_schema_version,
    )
    descriptor = _safe_event_descriptor(
        context,
        adapter_version=event_adapter_version,
        source_schema_version=event_source_schema_version,
    )
    plan = _plan_snapshot(context, (True, False, False))
    action = _action_snapshot(
        context,
        plan,
        (ActionState.COMPLETED,),
        ((0,),),
        descriptor,
    )

    _, state = _project(
        context,
        plan,
        action,
        requirement_action_descriptor=descriptor,
    )

    assert state.value_state is MetricValueStateV2.KNOWN
    assert (state.numerator, state.denominator) == (1, 1)

    _, invalid = _project(
        context,
        plan,
        action,
        requirement_action_descriptor=_safe_event_descriptor(context),
    )
    assert invalid.value_state is MetricValueStateV2.UNKNOWN
    assert invalid.explanation_code == REASON_REQUIREMENT_ACTION_INVALID


def test_started_or_unknown_links_are_right_censored_and_completed_wins() -> None:
    context = _context()
    plan = _plan_snapshot(context, (True, True, True))
    action = _action_snapshot(
        context,
        plan,
        (
            ActionState.STARTED,
            ActionState.UNKNOWN,
            ActionState.COMPLETED,
            ActionState.CANCELLED,
        ),
        ((0,), (1,), (0, 2, 3)),
    )

    _, state = _project(context, plan, action)

    assert state.value_state is MetricValueStateV2.PENDING
    assert state.numerator is state.denominator is None
    assert (state.censoring_lower_bound, state.censoring_upper_bound) == (
        1 / 3,
        1.0,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("censoring_lower_bound", None),
        ("censoring_upper_bound", None),
        ("censoring_lower_bound", 0.25),
        ("censoring_upper_bound", 0.9),
    ),
)
def test_pending_state_rejects_missing_or_forged_exact_bounds(
    field: str,
    value: float | None,
) -> None:
    context = _context()
    plan = _plan_snapshot(context, (True, True, True))
    action = _action_snapshot(
        context,
        plan,
        (ActionState.COMPLETED, ActionState.STARTED),
        ((0,), (1,), ()),
    )
    _, state = _project(context, plan, action)
    payload = state.model_dump(mode="json")
    payload[field] = value

    with pytest.raises(ValidationError):
        type(state).model_validate(payload)


def test_confirmed_empty_r6_requirement_set_is_na_only_with_exact_authorities() -> None:
    context = _context()
    plan = _plan_snapshot(context, (False, False, False))
    action = _action_snapshot(context, plan, (), ())

    _, state = _project(context, plan, action)

    assert state.value_state is MetricValueStateV2.NOT_APPLICABLE
    assert state.statistics.eligible_count == 0
    assert state.numerator is state.denominator is state.numeric_value is None


def test_forged_requirement_or_candidate_binding_fails_closed() -> None:
    context = _context()
    plan = _plan_snapshot(context, (True, True, True))
    action = _action_snapshot(
        context,
        plan,
        (ActionState.COMPLETED,),
        ((0,), (), ()),
    )
    forged_manifest = action.candidate_manifest.model_copy(  # type: ignore[union-attr]
        update={"manifest_fingerprint": _id("forged-manifest")}
    )
    forged = action.model_copy(update={"candidate_manifest": forged_manifest})

    _, state = _project(context, plan, forged)

    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.explanation_code == REASON_REQUIREMENT_ACTION_INVALID
    assert state.numerator is state.denominator is None


def test_forged_native_review_or_r6_authority_fingerprint_fails_closed() -> None:
    context = _context()
    plan = _plan_snapshot(context, (True, True, True))
    action = _action_snapshot(
        context,
        plan,
        (ActionState.COMPLETED,),
        ((0,), (), ()),
    )

    for forged in (
        action.model_copy(
            update={"evidence_fingerprint": _id("forged-action-authority")}
        ),
        action.model_copy(
            update={
                "requirement_plan_evidence_fingerprint": _id(
                    "forged-r6-authority"
                )
            }
        ),
    ):
        _, state = _project(context, plan, forged)
        assert state.value_state is MetricValueStateV2.UNKNOWN
        assert state.explanation_code == REASON_REQUIREMENT_ACTION_INVALID
        assert state.numerator is state.denominator is None


def test_incomplete_extraction_cannot_turn_empty_or_failed_links_into_negatives() -> None:
    context = _context()
    plan = _plan_snapshot(context, (True, True, True))
    action = _action_snapshot(
        context,
        plan,
        (ActionState.FAILED,),
        ((0,), (), ()),
    )
    manifest = action.candidate_manifest
    assert manifest is not None
    incomplete_provenance = manifest.provenance.model_copy(
        update={"extraction_complete": False}
    )
    incomplete_manifest = manifest.model_copy(
        update={
            "provenance": incomplete_provenance,
            "extraction_complete": False,
            "enumeration_complete": False,
        }
    )
    forged = action.model_copy(update={"candidate_manifest": incomplete_manifest})

    _, state = _project(context, plan, forged)

    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.explanation_code == REASON_REQUIREMENT_ACTION_INVALID


def test_readiness_distinguishes_absent_awaiting_and_invalid_r7_authority() -> None:
    context = _context()
    plan = _plan_snapshot(context, (True, True, True))
    _, absent = _project(context, plan, None)
    awaiting_snapshot = RequirementActionEvidenceSnapshot(
        session_id=context.session_id,
        source_window_fingerprint=context.analysis_window_fingerprint,
    )
    _, awaiting = _project(context, plan, awaiting_snapshot)
    _, invalid = _project(
        context,
        plan,
        awaiting_snapshot,
        requirement_action_binding_invalid=True,
    )

    absent_row = metric_evidence_readiness_row(absent)
    awaiting_row = metric_evidence_readiness_row(awaiting)
    invalid_row = metric_evidence_readiness_row(invalid)
    assert absent_row.reason_code is (
        MetricEvidenceReadinessReason.REVIEWED_REQUIREMENT_ACTION_SERVICE_REQUIRED
    )
    assert awaiting_row.reason_code is (
        MetricEvidenceReadinessReason
        .REVIEWED_REQUIREMENT_ACTION_CONFIRMATION_REQUIRED
    )
    assert invalid_row.reason_code is (
        MetricEvidenceReadinessReason.REVIEWED_REQUIREMENT_ACTION_BINDING_INVALID
    )


def test_candidate_manifest_overflow_is_named_unknown() -> None:
    context = _context()
    plan = _plan_snapshot(context, (True, True, True))
    action = _action_snapshot(context, plan, (), ((), (), ()))
    _, state = _project(
        context,
        plan,
        action,
        candidate_manifest_overflow=True,
    )

    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.explanation_code == REASON_REQUIREMENT_ACTION_OVERFLOW
    assert state.statistics.eligible_count == 3
    assert state.statistics.unknown_count == 3
    assert state.numerator is state.denominator is state.numeric_value is None


def test_readiness_refines_awaiting_empty_vs_overflow_from_closed_r7_codes() -> None:
    context = _context()
    plan = _plan_snapshot(context, (False, False, False))
    awaiting_snapshot = RequirementActionEvidenceSnapshot(
        session_id=context.session_id,
        source_window_fingerprint=context.analysis_window_fingerprint,
    )
    _, awaiting = _project(context, plan, awaiting_snapshot)
    _, unavailable = _project(context, plan, None)
    _, overflow = _project(
        context,
        plan,
        None,
        candidate_manifest_overflow=True,
    )

    assert awaiting.statistics.eligible_count == 0
    assert unavailable.statistics.eligible_count == 0
    assert overflow.statistics.eligible_count == 0
    assert metric_evidence_readiness_row(awaiting).reason_code is (
        MetricEvidenceReadinessReason
        .REVIEWED_REQUIREMENT_ACTION_CONFIRMATION_REQUIRED
    )
    assert metric_evidence_readiness_row(unavailable).reason_code is (
        MetricEvidenceReadinessReason.REVIEWED_REQUIREMENT_ACTION_SERVICE_REQUIRED
    )
    assert metric_evidence_readiness_row(overflow).reason_code is (
        MetricEvidenceReadinessReason.OPPORTUNITY_SET_EXCEEDS_RECEIPT_BOUND
    )
    arbitrary = awaiting.model_copy(update={"explanation_code": "arbitrary_reason"})
    with pytest.raises(ValueError, match="unrecognized reason"):
        metric_evidence_readiness_row(arbitrary)
