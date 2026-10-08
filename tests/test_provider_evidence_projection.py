from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from prompt_enhancer.application.analysis.evidence_contracts import (
    ActionFamily,
    ActionState,
    DecisionState,
    RationaleState,
    TypedEvidenceKind,
    TypedEvidenceOpportunityKind,
    VerificationMethod,
    VerificationOutcome,
    EphemeralTypedEvidenceProjection,
    TypedEvidenceProvenance,
)
from prompt_enhancer.application.analysis.provider_evidence import (
    SAFE_EVENT_EVIDENCE_DECODER_KEY,
    SAFE_EVENT_EVIDENCE_DECODER_VERSION,
    SAFE_EVENT_EVIDENCE_DECODER_VERSION_3,
    SafeEventTypedEvidenceProjector,
    bind_semantic_unit_opportunities,
    derive_requirement_action_candidate_manifest,
    requirement_action_candidate_manifest_fingerprint,
)
from prompt_enhancer.application.analysis.objective_metric_projection import (
    project_objective_metric_overrides,
)
from prompt_enhancer.application.analysis.text_contracts import MetricValueState
from prompt_enhancer.application.analysis.semantic_units import (
    SemanticUnitExtractionBasis,
    SemanticUnitKind,
    SemanticUnitLifecycle,
    SemanticUnitReceipt,
    SemanticUnitReconciliation,
)
from prompt_enhancer.application.providers import (
    CapabilityKey,
    DecoderDescriptor,
    ProviderIdentity,
    ProviderSurface,
    SchemaArtifactKind,
    SchemaArtifactProvenance,
)
from prompt_enhancer.domain import (
    EventKind,
    Provider,
    SafeEvent,
    SafeSession,
    SessionState,
    ToolCategory,
)


SESSION_ID = "a" * 64


class _Source:
    def __init__(
        self,
        session: SafeSession | None,
        events: tuple[SafeEvent, ...],
    ) -> None:
        self.session = session
        self.events = events

    def get_session(self, session_id: str) -> SafeSession | None:
        assert session_id == SESSION_ID
        return self.session

    def get_session_events(self, session_id: str) -> tuple[SafeEvent, ...]:
        assert session_id == SESSION_ID
        return self.events


class _Ids:
    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str:
        assert namespace == "typed-safe-event-evidence-v2"
        return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()


def _descriptor(
    *capabilities: CapabilityKey,
    decoder_version: str = SAFE_EVENT_EVIDENCE_DECODER_VERSION,
) -> DecoderDescriptor:
    return DecoderDescriptor(
        provider=ProviderIdentity(key="codex"),
        surface=ProviderSurface.OPERATIONAL_EVENTS,
        adapter_version="synthetic-adapter-v1",
        decoder_key=SAFE_EVENT_EVIDENCE_DECODER_KEY,
        decoder_version=decoder_version,
        wire_schema_family="synthetic-safe-events",
        canonical_schema_version="synthetic-schema-v1",
        schema_artifact=SchemaArtifactProvenance(
            artifact_key="synthetic-safe-events",
            artifact_version="1",
            kind=SchemaArtifactKind.SYNTHETIC,
        ),
        capabilities=capabilities,
    )


DESCRIPTOR = _descriptor(
    CapabilityKey.TOOL_EVENTS,
    CapabilityKey.DECISION_EVENTS,
    CapabilityKey.VERIFICATION_EVENTS,
)
#: The same decoder, additionally authorized to enumerate and link the two
#: denominator families a safe-event graph can legitimately carry.
AUTHORITATIVE_DESCRIPTOR = _descriptor(
    CapabilityKey.TOOL_EVENTS,
    CapabilityKey.DECISION_EVENTS,
    CapabilityKey.VERIFICATION_EVENTS,
    CapabilityKey.REQUIREMENT_OPPORTUNITIES,
    CapabilityKey.REQUIREMENT_EVIDENCE_LINKS,
    CapabilityKey.VERIFICATION_TASK_OPPORTUNITIES,
    CapabilityKey.VERIFICATION_TASK_EVIDENCE_LINKS,
)


def _session(*, complete: bool = True) -> SafeSession:
    return SafeSession(
        provider=Provider.CODEX,
        installation_id="b" * 64,
        project_id="c" * 64,
        session_id=SESSION_ID,
        provider_version="synthetic-provider-v1",
        adapter_version="synthetic-adapter-v1",
        source_schema_version="synthetic-schema-v1",
        started_at=datetime(2040, 1, 1, tzinfo=UTC),
        terminal_state=SessionState.COMPLETED,
        events_complete=complete,
    )


def _event(
    ordinal: int,
    kind: EventKind,
    *,
    category: ToolCategory | None = None,
    success: bool | None = None,
    duration_ms: int | None = None,
) -> SafeEvent:
    return SafeEvent(
        session_id=SESSION_ID,
        event_id=f"{ordinal:x}" * 64,
        kind=kind,
        sequence=ordinal,
        occurred_at=datetime(2040, 1, 1, 10, ordinal, tzinfo=UTC),
        tool_category=category,
        success=success,
        duration_ms=duration_ms,
    )


def test_projects_content_free_actions_decisions_and_verification() -> None:
    projection = SafeEventTypedEvidenceProjector(
        _Source(
            _session(),
            (
                _event(1, EventKind.TOOL_START, category=ToolCategory.FILE_WRITE),
                _event(
                    2,
                    EventKind.TOOL_END,
                    category=ToolCategory.TEST,
                    success=True,
                ),
                _event(3, EventKind.DECISION, success=True),
            ),
        ),
        _Ids(),
        DESCRIPTOR,
    ).project(provider=Provider.CODEX, session_id=SESSION_ID)

    assert projection is not None
    assert projection.provenance.extraction_complete is True
    assert projection.declared_kinds == frozenset(
        {
            TypedEvidenceKind.ACTION,
            TypedEvidenceKind.DECISION,
            TypedEvidenceKind.VERIFICATION,
        }
    )
    assert len(projection.records) == 4
    first, second, verification, decision = projection.records
    assert (first.family, first.state) == (
        ActionFamily.FILE_CHANGE,
        ActionState.STARTED,
    )
    assert (second.family, second.state) == (
        ActionFamily.COMMAND,
        ActionState.COMPLETED,
    )
    assert (verification.method, verification.outcome) == (
        VerificationMethod.TEST,
        VerificationOutcome.PASSED,
    )
    assert verification.receipt_reference_ids == ("2" * 64,)
    assert (decision.state, decision.rationale_state) == (
        DecisionState.ACCEPTED,
        RationaleState.UNKNOWN,
    )
    assert [item.sequence for item in projection.records] == [4, 8, 10, 13]


def test_derives_exact_content_free_requirement_action_candidate_manifest() -> None:
    projection = SafeEventTypedEvidenceProjector(
        _Source(
            _session(),
            (
                _event(1, EventKind.TOOL_START, category=ToolCategory.FILE_WRITE),
                _event(
                    2,
                    EventKind.TOOL_END,
                    category=ToolCategory.TEST,
                    success=True,
                ),
                _event(3, EventKind.DECISION, success=True),
            ),
        ),
        _Ids(),
        DESCRIPTOR,
    ).project(provider=Provider.CODEX, session_id=SESSION_ID)
    assert projection is not None

    manifest = derive_requirement_action_candidate_manifest(
        projection,
        source_run_id="d" * 64,
        source_window_fingerprint="e" * 64,
        safe_events=(
            _event(1, EventKind.TOOL_START, category=ToolCategory.FILE_WRITE),
            _event(
                2,
                EventKind.TOOL_END,
                category=ToolCategory.TEST,
                success=True,
            ),
            _event(3, EventKind.DECISION, success=True),
        ),
    )

    assert manifest.session_id == SESSION_ID
    assert manifest.provenance == projection.provenance
    assert manifest.extraction_complete is True
    assert manifest.enumeration_complete is True
    assert [item.candidate_index for item in manifest.actions] == [0, 1]
    assert [item.source_reference_id for item in manifest.actions] == [
        "1" * 64,
        "2" * 64,
    ]
    assert [item.state for item in manifest.actions] == [
        ActionState.STARTED,
        ActionState.COMPLETED,
    ]
    assert [item.event_kind for item in manifest.actions] == [
        EventKind.TOOL_START,
        EventKind.TOOL_END,
    ]
    assert [item.tool_category for item in manifest.actions] == [
        ToolCategory.FILE_WRITE,
        ToolCategory.TEST,
    ]
    assert all(item.occurred_at.tzinfo is UTC for item in manifest.actions)
    assert manifest.manifest_fingerprint == (
        requirement_action_candidate_manifest_fingerprint(manifest)
    )
    payload = manifest.model_dump(mode="json")
    assert "requirement_reference_ids" not in repr(payload)
    assert "hypothesis_reference_ids" not in repr(payload)


def test_candidate_manifest_never_claims_complete_enumeration_from_partial_source() -> None:
    projection = SafeEventTypedEvidenceProjector(
        _Source(
            _session(complete=False),
            (_event(1, EventKind.TOOL_START, category=ToolCategory.FILE_WRITE),),
        ),
        _Ids(),
        DESCRIPTOR,
    ).project(provider=Provider.CODEX, session_id=SESSION_ID)
    assert projection is not None

    manifest = derive_requirement_action_candidate_manifest(
        projection,
        source_run_id="d" * 64,
        source_window_fingerprint="e" * 64,
        safe_events=(
            _event(1, EventKind.TOOL_START, category=ToolCategory.FILE_WRITE),
        ),
    )

    assert len(manifest.actions) == 1
    assert manifest.extraction_complete is False
    assert manifest.enumeration_complete is False


def test_candidate_manifest_never_treats_undeclared_empty_action_family_as_exact() -> None:
    projection = EphemeralTypedEvidenceProjection(
        session_id=SESSION_ID,
        provenance=TypedEvidenceProvenance(
            provider=Provider.CODEX,
            provider_version="synthetic-provider-v1",
            adapter_version="synthetic-adapter-v1",
            decoder_key=SAFE_EVENT_EVIDENCE_DECODER_KEY,
            decoder_version=SAFE_EVENT_EVIDENCE_DECODER_VERSION,
            source_schema_version="synthetic-schema-v1",
            extraction_complete=True,
        ),
        declared_kinds=frozenset(),
        records=(),
    )

    manifest = derive_requirement_action_candidate_manifest(
        projection,
        source_run_id="d" * 64,
        source_window_fingerprint="e" * 64,
        safe_events=(),
    )

    assert manifest.actions == ()
    assert manifest.extraction_complete is True
    assert manifest.enumeration_complete is False


def test_projector_issues_reviewable_candidate_metadata_without_private_content() -> None:
    events = (
        _event(
            1,
            EventKind.TOOL_END,
            category=ToolCategory.BUILD,
            success=True,
            duration_ms=321,
        ),
    )
    manifest = SafeEventTypedEvidenceProjector(
        _Source(_session(), events),
        _Ids(),
        DESCRIPTOR,
    ).requirement_action_candidate_manifest(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        source_run_id="d" * 64,
        source_window_fingerprint="e" * 64,
    )

    assert manifest is not None
    candidate = manifest.actions[0]
    assert candidate.event_kind is EventKind.TOOL_END
    assert candidate.tool_category is ToolCategory.BUILD
    assert candidate.duration_ms == 321
    assert candidate.occurred_at == events[0].occurred_at
    assert set(candidate.model_dump()) == {
        "candidate_index",
        "action_id",
        "source_reference_id",
        "sequence",
        "event_kind",
        "tool_category",
        "occurred_at",
        "duration_ms",
        "family",
        "state",
    }


def test_candidate_manifest_rejects_a_growing_mixed_event_snapshot() -> None:
    first = _event(1, EventKind.TOOL_START, category=ToolCategory.FILE_WRITE)
    second = _event(2, EventKind.TOOL_END, category=ToolCategory.FILE_WRITE)

    class _GrowingSource(_Source):
        def __init__(self) -> None:
            super().__init__(_session(), (first,))
            self.reads = 0

        def get_session_events(self, session_id: str) -> tuple[SafeEvent, ...]:
            assert session_id == SESSION_ID
            self.reads += 1
            return (first,) if self.reads == 1 else (first, second)

    projector = SafeEventTypedEvidenceProjector(
        _GrowingSource(),
        _Ids(),
        DESCRIPTOR,
    )

    with pytest.raises(ValueError, match="exactly cover"):
        projector.requirement_action_candidate_manifest(
            provider=Provider.CODEX,
            session_id=SESSION_ID,
            source_run_id="d" * 64,
            source_window_fingerprint="e" * 64,
        )


def test_candidate_manifest_overflow_fails_closed_without_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projection = SafeEventTypedEvidenceProjector(
        _Source(
            _session(),
            (
                _event(1, EventKind.TOOL_START, category=ToolCategory.FILE_WRITE),
                _event(2, EventKind.TOOL_END, category=ToolCategory.FILE_WRITE),
            ),
        ),
        _Ids(),
        DESCRIPTOR,
    ).project(provider=Provider.CODEX, session_id=SESSION_ID)
    assert projection is not None
    monkeypatch.setattr(
        "prompt_enhancer.application.analysis.provider_evidence.MAX_REQUIREMENT_ACTION_CANDIDATES",
        1,
    )

    with pytest.raises(ValueError, match="exceeds its bound"):
        derive_requirement_action_candidate_manifest(
            projection,
            source_run_id="d" * 64,
            source_window_fingerprint="e" * 64,
            safe_events=(
                _event(1, EventKind.TOOL_START, category=ToolCategory.FILE_WRITE),
                _event(2, EventKind.TOOL_END, category=ToolCategory.FILE_WRITE),
            ),
        )


def test_incomplete_event_stream_stays_explicit_and_empty_is_valid() -> None:
    projection = SafeEventTypedEvidenceProjector(
        _Source(_session(complete=False), ()),
        _Ids(),
        DESCRIPTOR,
    ).project(provider=Provider.CODEX, session_id=SESSION_ID)

    assert projection is not None
    assert projection.provenance.extraction_complete is False
    assert projection.records == ()


def test_current_safe_events_without_semantic_links_never_become_numeric() -> None:
    projection = SafeEventTypedEvidenceProjector(
        _Source(
            _session(),
            (
                _event(
                    1,
                    EventKind.TOOL_END,
                    category=ToolCategory.TEST,
                    success=True,
                ),
            ),
        ),
        _Ids(),
        DESCRIPTOR,
    ).project(provider=Provider.CODEX, session_id=SESSION_ID)

    assert projection is not None
    result = project_objective_metric_overrides(projection, DESCRIPTOR)
    assert len(result) == 5
    assert all(
        item.value_state is MetricValueState.UNKNOWN for item in result.values()
    )


def test_missing_or_wrong_provider_session_is_not_projected() -> None:
    projector = SafeEventTypedEvidenceProjector(
        _Source(None, ()), _Ids(), DESCRIPTOR
    )
    assert projector.project(provider=Provider.CODEX, session_id=SESSION_ID) is None

    projector = SafeEventTypedEvidenceProjector(
        _Source(_session(), ()), _Ids(), DESCRIPTOR
    )
    assert (
        projector.project(provider=Provider.CLAUDE_CODE, session_id=SESSION_ID)
        is None
    )


def test_projection_rejects_descriptor_without_authoritative_capabilities() -> None:
    projector = SafeEventTypedEvidenceProjector(
        _Source(
            _session(),
            (_event(1, EventKind.TOOL_END, category=ToolCategory.TEST),),
        ),
        _Ids(),
        _descriptor(CapabilityKey.USER_MESSAGES),
    )

    with pytest.raises(ValueError, match="not authorized"):
        projector.project(provider=Provider.CODEX, session_id=SESSION_ID)


def test_tool_only_descriptor_skips_undeclared_verification_evidence() -> None:
    projection = SafeEventTypedEvidenceProjector(
        _Source(
            _session(),
            (
                _event(
                    1,
                    EventKind.TOOL_END,
                    category=ToolCategory.TEST,
                    success=True,
                ),
                _event(2, EventKind.VERIFICATION, success=True),
            ),
        ),
        _Ids(),
        _descriptor(CapabilityKey.TOOL_EVENTS),
    ).project(provider=Provider.CODEX, session_id=SESSION_ID)

    assert projection is not None
    assert projection.declared_kinds == frozenset({TypedEvidenceKind.ACTION})
    assert len(projection.records) == 1
    assert projection.records[0].kind is TypedEvidenceKind.ACTION


def test_tool_only_capability_set_cannot_declare_any_denominator() -> None:
    """A `tool_events`-only descriptor (the r2/r3 composition root) keeps all five unknown.

    Decoder 4 ships four capabilities and a reviewed-task denominator; see
    test_task_scoped_evidence.py.  This test pins the tool-only contract.
    """

    shipped = _descriptor(CapabilityKey.TOOL_EVENTS)
    projection = SafeEventTypedEvidenceProjector(
        _Source(
            _session(),
            (
                _event(1, EventKind.TOOL_START, category=ToolCategory.FILE_WRITE),
                _event(
                    2,
                    EventKind.TOOL_END,
                    category=ToolCategory.TEST,
                    success=True,
                ),
                _event(3, EventKind.DECISION, success=True),
                _event(4, EventKind.VERIFICATION, success=True),
            ),
        ),
        _Ids(),
        shipped,
    ).project(provider=Provider.CODEX, session_id=SESSION_ID)

    assert projection is not None
    assert projection.declared_opportunity_kinds == frozenset()
    assert projection.eligible_verification_task_reference_ids == ()
    result = project_objective_metric_overrides(projection, shipped)
    assert len(result) == 5
    assert all(
        item.value_state is MetricValueState.UNKNOWN
        and item.numerator is None
        and item.denominator is None
        for item in result.values()
    )
    assert all(
        item.explanation_code == "typed_objective_opportunity_authority_missing"
        for item in result.values()
    )


def test_undeclared_decision_event_is_skipped_not_fatal() -> None:
    projection = SafeEventTypedEvidenceProjector(
        _Source(
            _session(),
            (
                _event(1, EventKind.TOOL_END, category=ToolCategory.FILE_WRITE),
                _event(2, EventKind.DECISION, success=True),
            ),
        ),
        _Ids(),
        _descriptor(CapabilityKey.TOOL_EVENTS),
    ).project(provider=Provider.CODEX, session_id=SESSION_ID)

    assert projection is not None
    assert projection.declared_kinds == frozenset({TypedEvidenceKind.ACTION})
    assert tuple(item.kind for item in projection.records) == (
        TypedEvidenceKind.ACTION,
    )


def test_verification_task_denominator_requires_explicit_capabilities() -> None:
    events = (
        _event(1, EventKind.VERIFICATION, success=True),
        _event(2, EventKind.TOOL_END, category=ToolCategory.TEST, success=False),
    )

    unauthorized = SafeEventTypedEvidenceProjector(
        _Source(_session(), events), _Ids(), DESCRIPTOR
    ).project(provider=Provider.CODEX, session_id=SESSION_ID)
    authorized = SafeEventTypedEvidenceProjector(
        _Source(_session(), events), _Ids(), AUTHORITATIVE_DESCRIPTOR
    ).project(provider=Provider.CODEX, session_id=SESSION_ID)

    assert unauthorized is not None
    assert unauthorized.declared_opportunity_kinds == frozenset()
    assert unauthorized.eligible_verification_task_reference_ids == ()
    assert authorized is not None
    assert authorized.declared_opportunity_kinds == frozenset(
        {TypedEvidenceOpportunityKind.VERIFICATION_TASK}
    )
    # Exactly one task: the explicit verification event.  The tool end is a
    # category inference and must never receive a task identity.
    assert len(authorized.eligible_verification_task_reference_ids) == 1
    linked = tuple(
        item
        for item in authorized.records
        if item.kind is TypedEvidenceKind.VERIFICATION
        and item.verification_task_reference_ids
    )
    assert len(linked) == 1
    assert linked[0].source_reference_id == "1" * 64


def test_decoder_v3_never_turns_event_identity_into_task_identity() -> None:
    descriptor = _descriptor(
        CapabilityKey.TOOL_EVENTS,
        CapabilityKey.VERIFICATION_EVENTS,
        CapabilityKey.VERIFICATION_TASK_OPPORTUNITIES,
        CapabilityKey.VERIFICATION_TASK_EVIDENCE_LINKS,
        decoder_version=SAFE_EVENT_EVIDENCE_DECODER_VERSION_3,
    )
    projection = SafeEventTypedEvidenceProjector(
        _Source(
            _session(),
            (
                _event(1, EventKind.VERIFICATION, success=True),
                _event(2, EventKind.VERIFICATION, success=False),
            ),
        ),
        _Ids(),
        descriptor,
    ).project(provider=Provider.CODEX, session_id=SESSION_ID)

    assert projection is not None
    assert projection.provenance.decoder_version == "3"
    assert projection.declared_opportunity_kinds == frozenset()
    assert projection.eligible_verification_task_reference_ids == ()
    receipts = tuple(
        item
        for item in projection.records
        if item.kind is TypedEvidenceKind.VERIFICATION
    )
    assert len(receipts) == 2
    assert all(item.verification_task_reference_ids == () for item in receipts)


def test_explicit_verification_events_make_first_pass_numeric() -> None:
    projection = SafeEventTypedEvidenceProjector(
        _Source(
            _session(),
            (
                _event(1, EventKind.VERIFICATION, success=True),
                _event(2, EventKind.VERIFICATION, success=False),
            ),
        ),
        _Ids(),
        AUTHORITATIVE_DESCRIPTOR,
    ).project(provider=Provider.CODEX, session_id=SESSION_ID)

    assert projection is not None
    first_pass = project_objective_metric_overrides(
        projection, AUTHORITATIVE_DESCRIPTOR
    )["outcome.first_pass_verification"]

    assert first_pass.value_state is MetricValueState.KNOWN
    assert (first_pass.numerator, first_pass.denominator) == (1, 2)


def test_no_explicit_verification_event_is_an_empty_authoritative_task_set() -> None:
    projection = SafeEventTypedEvidenceProjector(
        _Source(
            _session(),
            (_event(1, EventKind.TOOL_END, category=ToolCategory.TEST, success=True),),
        ),
        _Ids(),
        AUTHORITATIVE_DESCRIPTOR,
    ).project(provider=Provider.CODEX, session_id=SESSION_ID)

    assert projection is not None
    result = project_objective_metric_overrides(projection, AUTHORITATIVE_DESCRIPTOR)

    assert (
        result["outcome.first_pass_verification"].value_state
        is MetricValueState.NOT_APPLICABLE
    )
    # A requirement family the reconciler cannot own stays unknown, never N/A.
    assert (
        result["logic.requirement_action_traceability"].value_state
        is MetricValueState.UNKNOWN
    )


def test_complete_semantic_requirement_set_becomes_authoritative_denominator() -> None:
    projection = SafeEventTypedEvidenceProjector(
        _Source(_session(), ()),
        _Ids(),
        DESCRIPTOR,
    ).project(provider=Provider.CODEX, session_id=SESSION_ID)
    assert projection is not None
    requirement = SemanticUnitReceipt(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        receipt_id="1" * 64,
        unit_id="2" * 64,
        unit_digest="3" * 64,
        revision=1,
        kind=SemanticUnitKind.REQUIREMENT,
        lifecycle=SemanticUnitLifecycle.CLOSED,
        extraction_basis=SemanticUnitExtractionBasis.TYPED_PROVIDER_EVENT,
        owner_source_digest="4" * 64,
        source_digests=("4" * 64,),
        source_version_digest="5" * 64,
        first_sequence=1,
        closed_at_sequence=1,
    )
    reconciliation = SemanticUnitReconciliation(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        analysis_window_fingerprint="6" * 64,
        source_complete=True,
        reconciliation_id="7" * 64,
        heads=(requirement,),
        appended=(requirement,),
        unchanged_receipt_ids=(),
        retained_unobserved_unit_count=0,
    )

    bound = bind_semantic_unit_opportunities(
        projection, reconciliation, AUTHORITATIVE_DESCRIPTOR
    )
    without_link_authority = bind_semantic_unit_opportunities(
        projection, reconciliation, DESCRIPTOR
    )

    assert bound is not None
    assert bound.eligible_requirement_reference_ids == (requirement.unit_id,)
    assert (
        TypedEvidenceOpportunityKind.REQUIREMENT
        in bound.declared_opportunity_kinds
    )
    assert without_link_authority is not None
    assert without_link_authority.eligible_requirement_reference_ids == ()
    assert without_link_authority.declared_opportunity_kinds == frozenset()
