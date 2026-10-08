"""Decoder 4: the verification-task denominator is a reviewed task.

One current accepted task revision containing the session is the only
denominator this decoder will declare; every verification receipt in the
session (a test or build tool end with an exit status, or an explicit
verification event) links to it.  No revision, more than one revision, or no
task source means no task family - first-pass stays unknown, never 1/1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib

from prompt_enhancer.application.analysis.evidence_contracts import (
    TypedEvidenceKind,
    TypedEvidenceOpportunityKind,
    VerificationEvidence,
    VerificationOutcome,
)
from prompt_enhancer.application.analysis.objective_metric_projection import (
    project_objective_metric_overrides_v3,
)
from prompt_enhancer.application.analysis.provider_evidence import (
    SAFE_EVENT_EVIDENCE_DECODER_CURRENT_VERSION,
    SAFE_EVENT_EVIDENCE_DECODER_KEY,
    SAFE_EVENT_EVIDENCE_DECODER_VERSION_3,
    SAFE_EVENT_EVIDENCE_DECODER_VERSION_4,
    SafeEventTypedEvidenceProjector,
)
from prompt_enhancer.application.analysis.text_contracts import MetricValueState
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
FIRST_PASS = "outcome.first_pass_verification"
TASK_CAPABILITIES = (
    CapabilityKey.TOOL_EVENTS,
    CapabilityKey.VERIFICATION_EVENTS,
    CapabilityKey.VERIFICATION_TASK_OPPORTUNITIES,
    CapabilityKey.VERIFICATION_TASK_EVIDENCE_LINKS,
)


class _Source:
    def __init__(self, session: SafeSession, events: tuple[SafeEvent, ...]) -> None:
        self.session = session
        self.events = events

    def get_session(self, session_id: str) -> SafeSession | None:
        return self.session if session_id == SESSION_ID else None

    def get_session_events(self, session_id: str) -> tuple[SafeEvent, ...]:
        return self.events


class _Ids:
    def __init__(self) -> None:
        self.namespaces: list[str] = []

    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str:
        self.namespaces.append(namespace)
        return hashlib.sha256(("|".join((namespace, *values))).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _Revision:
    task_id: str
    revision: int


class _Tasks:
    def __init__(self, revisions: tuple[_Revision, ...], *, fail: bool = False) -> None:
        self.revisions = revisions
        self.fail = fail
        self.calls: list[str] = []

    def list_current_revisions_for_session(self, session_id: str) -> tuple[_Revision, ...]:
        self.calls.append(session_id)
        if self.fail:
            raise RuntimeError("task store unavailable")
        return self.revisions


def _descriptor(
    *,
    provider: str = "codex",
    adapter_version: str = "synthetic-adapter-v1",
    schema_version: str = "synthetic-schema-v1",
    decoder_version: str = SAFE_EVENT_EVIDENCE_DECODER_VERSION_4,
    capabilities: tuple[CapabilityKey, ...] = TASK_CAPABILITIES,
) -> DecoderDescriptor:
    return DecoderDescriptor(
        provider=ProviderIdentity(key=provider),
        surface=ProviderSurface.OPERATIONAL_EVENTS,
        adapter_version=adapter_version,
        decoder_key=SAFE_EVENT_EVIDENCE_DECODER_KEY,
        decoder_version=decoder_version,
        wire_schema_family="synthetic-safe-events",
        canonical_schema_version=schema_version,
        schema_artifact=SchemaArtifactProvenance(
            artifact_key="synthetic-safe-events",
            artifact_version="1",
            kind=SchemaArtifactKind.SYNTHETIC,
        ),
        capabilities=capabilities,
    )


def _session(provider: Provider = Provider.CODEX, *, adapter_version: str = "synthetic-adapter-v1", schema_version: str = "synthetic-schema-v1") -> SafeSession:
    return SafeSession(
        provider=provider,
        installation_id="b" * 64,
        project_id="c" * 64,
        session_id=SESSION_ID,
        provider_version="synthetic-provider-v1",
        adapter_version=adapter_version,
        source_schema_version=schema_version,
        started_at=datetime(2040, 1, 1, tzinfo=UTC),
        terminal_state=SessionState.COMPLETED,
        events_complete=True,
    )


def _event(ordinal: int, kind: EventKind, *, category: ToolCategory | None = None, success: bool | None = None) -> SafeEvent:
    return SafeEvent(
        session_id=SESSION_ID,
        event_id=f"{ordinal:x}" * 64,
        kind=kind,
        sequence=ordinal,
        occurred_at=datetime(2040, 1, 1, 10, ordinal, tzinfo=UTC),
        tool_category=category,
        success=success,
    )


def _verifications(projection) -> list[VerificationEvidence]:
    return [record for record in projection.records if isinstance(record, VerificationEvidence)]


def test_current_decoder_is_task_scoped() -> None:
    assert SAFE_EVENT_EVIDENCE_DECODER_CURRENT_VERSION == SAFE_EVENT_EVIDENCE_DECODER_VERSION_4


def test_one_accepted_revision_makes_first_pass_numeric_from_test_receipts() -> None:
    tasks = _Tasks((_Revision("d" * 64, 2),))
    ids = _Ids()
    events = (
        _event(1, EventKind.TOOL_START, category=ToolCategory.FILE_WRITE),
        _event(2, EventKind.TOOL_END, category=ToolCategory.TEST, success=True),
        _event(3, EventKind.TOOL_END, category=ToolCategory.TEST, success=False),
        _event(4, EventKind.TOOL_END, category=ToolCategory.COMMAND, success=True),
    )
    descriptor = _descriptor()
    projection = SafeEventTypedEvidenceProjector(_Source(_session(), events), ids, descriptor, tasks=tasks).project(
        provider=Provider.CODEX, session_id=SESSION_ID
    )

    assert projection is not None
    assert tasks.calls == [SESSION_ID]
    assert projection.declared_opportunity_kinds == frozenset({TypedEvidenceOpportunityKind.VERIFICATION_TASK})
    assert len(projection.eligible_verification_task_reference_ids) == 1
    task_ref = projection.eligible_verification_task_reference_ids[0]
    assert "typed-reviewed-task-evidence-v4" in ids.namespaces
    verifications = _verifications(projection)
    # Two test receipts, both linked to the reviewed task; the plain command is an action only.
    assert [item.outcome for item in verifications] == [VerificationOutcome.PASSED, VerificationOutcome.FAILED]
    assert all(item.verification_task_reference_ids == (task_ref,) for item in verifications)

    result = project_objective_metric_overrides_v3(projection, descriptor)
    first_pass = result[FIRST_PASS]
    assert first_pass.value_state is MetricValueState.KNOWN
    assert first_pass.numerator == 1 and first_pass.denominator == 1
    assert first_pass.explanation_code == "typed_first_verification_outcomes"


def test_first_receipt_failing_is_zero_over_one_not_unknown() -> None:
    tasks = _Tasks((_Revision("d" * 64, 1),))
    events = (
        _event(1, EventKind.TOOL_END, category=ToolCategory.BUILD, success=False),
        _event(2, EventKind.TOOL_END, category=ToolCategory.TEST, success=True),
    )
    descriptor = _descriptor()
    projection = SafeEventTypedEvidenceProjector(_Source(_session(), events), _Ids(), descriptor, tasks=tasks).project(
        provider=Provider.CODEX, session_id=SESSION_ID
    )
    assert projection is not None
    first_pass = project_objective_metric_overrides_v3(projection, descriptor)[FIRST_PASS]
    assert first_pass.value_state is MetricValueState.KNOWN
    assert first_pass.numerator == 0 and first_pass.denominator == 1


def test_no_verification_receipt_keeps_first_pass_unknown_not_zero() -> None:
    tasks = _Tasks((_Revision("d" * 64, 1),))
    events = (
        _event(1, EventKind.TOOL_START, category=ToolCategory.FILE_WRITE),
        _event(2, EventKind.TOOL_END, category=ToolCategory.FILE_WRITE, success=True),
    )
    descriptor = _descriptor()
    projection = SafeEventTypedEvidenceProjector(_Source(_session(), events), _Ids(), descriptor, tasks=tasks).project(
        provider=Provider.CODEX, session_id=SESSION_ID
    )
    assert projection is not None
    assert len(projection.eligible_verification_task_reference_ids) == 1
    first_pass = project_objective_metric_overrides_v3(projection, descriptor)[FIRST_PASS]
    assert first_pass.value_state is MetricValueState.UNKNOWN
    assert first_pass.explanation_code == "typed_first_verification_unresolved"
    assert first_pass.numerator is None


def test_zero_or_ambiguous_or_failing_task_sources_declare_no_task_family() -> None:
    events = (_event(1, EventKind.TOOL_END, category=ToolCategory.TEST, success=True),)
    descriptor = _descriptor()
    for tasks in (
        None,
        _Tasks(()),
        _Tasks((_Revision("d" * 64, 1), _Revision("e" * 64, 1))),
        _Tasks((_Revision("d" * 64, 1),), fail=True),
    ):
        projection = SafeEventTypedEvidenceProjector(_Source(_session(), events), _Ids(), descriptor, tasks=tasks).project(
            provider=Provider.CODEX, session_id=SESSION_ID
        )
        assert projection is not None
        assert projection.declared_opportunity_kinds == frozenset()
        assert projection.eligible_verification_task_reference_ids == ()
        # The receipt itself is still emitted - it just has no task to link to.
        assert [item.verification_task_reference_ids for item in _verifications(projection)] == [()]
        first_pass = project_objective_metric_overrides_v3(projection, descriptor)[FIRST_PASS]
        assert first_pass.value_state is MetricValueState.UNKNOWN
        assert first_pass.explanation_code == "typed_objective_opportunity_authority_missing"


def test_decoder_four_never_mints_task_identity_from_an_event() -> None:
    """Unlike frozen decoder 2, an explicit verification event is a receipt only."""

    tasks = _Tasks((_Revision("d" * 64, 1),))
    events = (
        _event(1, EventKind.VERIFICATION, success=True),
        _event(2, EventKind.VERIFICATION, success=True),
    )
    ids = _Ids()
    projection = SafeEventTypedEvidenceProjector(_Source(_session(), events), ids, _descriptor(), tasks=tasks).project(
        provider=Provider.CODEX, session_id=SESSION_ID
    )
    assert projection is not None
    assert len(projection.eligible_verification_task_reference_ids) == 1
    task_ref = projection.eligible_verification_task_reference_ids[0]
    assert all(item.verification_task_reference_ids == (task_ref,) for item in _verifications(projection))

    # Decoder 3 stays exactly as it was: receipts, no task family, even with a task source.
    legacy = _descriptor(decoder_version=SAFE_EVENT_EVIDENCE_DECODER_VERSION_3)
    legacy_projection = SafeEventTypedEvidenceProjector(_Source(_session(), events), _Ids(), legacy, tasks=tasks).project(
        provider=Provider.CODEX, session_id=SESSION_ID
    )
    assert legacy_projection is not None
    assert legacy_projection.declared_opportunity_kinds == frozenset()
    assert tasks.calls == [SESSION_ID]  # decoder 3 never consulted the task source


def test_per_provider_descriptor_serves_claude_sessions() -> None:
    codex = _descriptor()
    claude = _descriptor(provider="claude_code", adapter_version="claude-transcripts-adapter-x", schema_version="claude-transcripts-schema-x")
    projector = SafeEventTypedEvidenceProjector(
        _Source(
            _session(Provider.CLAUDE_CODE, adapter_version="claude-transcripts-adapter-x", schema_version="claude-transcripts-schema-x"),
            (_event(1, EventKind.TOOL_END, category=ToolCategory.TEST, success=True),),
        ),
        _Ids(),
        codex,
        tasks=_Tasks((_Revision("d" * 64, 1),)),
        descriptors={Provider.CLAUDE_CODE: claude},
    )
    assert projector.descriptor is codex
    assert projector.descriptor_for(Provider.CLAUDE_CODE) is claude
    assert projector.descriptor_for(Provider.CODEX) is codex

    projection = projector.project(provider=Provider.CLAUDE_CODE, session_id=SESSION_ID)
    assert projection is not None
    assert projection.provenance.provider is Provider.CLAUDE_CODE
    assert projection.provenance.adapter_version == "claude-transcripts-adapter-x"
    assert TypedEvidenceKind.VERIFICATION in projection.declared_kinds
    first_pass = project_objective_metric_overrides_v3(projection, claude)[FIRST_PASS]
    assert first_pass.value_state is MetricValueState.KNOWN and first_pass.numerator == 1


def test_provider_descriptor_must_share_the_decoder() -> None:
    import pytest

    with pytest.raises(ValueError):
        SafeEventTypedEvidenceProjector(
            _Source(_session(), ()),
            _Ids(),
            _descriptor(),
            descriptors={Provider.CLAUDE_CODE: _descriptor(provider="claude_code", decoder_version=SAFE_EVENT_EVIDENCE_DECODER_VERSION_3)},
        )
    with pytest.raises(ValueError):
        SafeEventTypedEvidenceProjector(
            _Source(_session(), ()),
            _Ids(),
            _descriptor(),
            descriptors={Provider.CLAUDE_CODE: _descriptor(provider="codex")},
        )
