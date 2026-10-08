from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event, Lock

import pytest
from pydantic import SecretStr

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.application.analysis.session_quality_aggregation import (
    SessionQualityAggregationService,
    SessionQualitySelection,
)
from prompt_enhancer.application.analysis.session_text_service import (
    SESSION_TEXT_ANALYSIS_CONFIRMATION,
    SessionTextAnalysisConflictError,
    SessionTextAnalysisCompatibilityError,
    SessionTextAnalysisCooperativeStop,
    SessionTextAnalysisConfirmationError,
    SessionTextAnalysisConsentError,
    SessionTextAnalysisExecutionError,
    SessionTextAnalysisInputError,
    SessionTextAnalysisPersistenceError,
    SessionTextAnalysisSelectionError,
    SessionTextAnalysisService,
    SessionTextAnalysisSourceError,
)
from prompt_enhancer.application.analysis.redaction_preview import (
    REDACTION_PREVIEW_CONFIRMATION,
    AnalysisApproval,
    InMemoryRedactionPreviewStore,
    RedactionPreviewConsumedError,
    RedactionPreviewExpiredError,
    RedactionPreviewMismatchError,
)
from prompt_enhancer.application.analysis.text_baselines import (
    DEFAULT_TEXT_METRIC_ENGINE,
    DeterministicTextFeatureExtractor,
    TEXT_METRIC_ALGORITHM_ID,
    TEXT_METRIC_ALGORITHM_VERSION,
    TEXT_METRIC_DEFINITIONS,
    TextMetricEngine,
)
from prompt_enhancer.application.analysis.text_analysis_presets import (
    COACHING_PROFILE_V1,
    STANDARD_ENGINEERING_V1,
    TextAnalysisPresetId,
)
from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_DEFINITIONS,
    COACHING_METRIC_PACK_KEY,
    COACHING_METRIC_PACK_VERSION,
)
from prompt_enhancer.application.analysis.text_contracts import (
    ApplicabilityBasis,
    ConstraintKind,
    DeliverableSlot,
    EphemeralRedactedMessage,
    MetricApplicability,
    MetricApplicabilityDecision,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextRole,
    TextTaskProfile,
)
from prompt_enhancer.application.analysis.text_source import (
    TextAnalysisPurpose,
    TextAnalysisSelection,
    TextSourceFailureReason,
    TextSourceReadError,
    TextSourceAccessGrant,
)
from prompt_enhancer.application.persistence import (
    AnalysisRunStatus,
    SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
    SessionAnalysisCompletionAuthority,
    SessionAnalysisPublicationRejectedError,
    SessionAnalysisResultRecord,
    SessionAnalysisRunDraft,
    SessionAnalysisRunRecord,
)
from prompt_enhancer.domain import DataTier, Provider
from prompt_enhancer.database import Database
from prompt_enhancer.infrastructure.identifiers import LocalArtifactIdFactory
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.privacy import Pseudonymizer


NOW = datetime(2042, 3, 4, 9, 0, tzinfo=UTC)
SESSION_ID = "a" * 64
WINDOW_ID = "b" * 64


def test_session_analysis_schema_contract_is_decoupled_from_storage() -> None:
    assert SESSION_ANALYSIS_RUN_SCHEMA_VERSION == 21


def test_shared_session_run_id_issuance_matches_the_existing_domain() -> None:
    factory = LocalArtifactIdFactory(Pseudonymizer(bytes(range(32))))
    values = (
        "synthetic-retry",
        Provider.SYNTHETIC.value,
        SESSION_ID,
        "synthetic-pack-v1",
        "1",
    )
    assert factory.session_analysis_run_id(
        "synthetic-retry",
        Provider.SYNTHETIC,
        SESSION_ID,
        "synthetic-pack-v1",
        1,
    ) == factory.fingerprint("session-analysis-run-v1", values)


@pytest.mark.parametrize("invalid_version", (1.5, "1", None, True))
def test_shared_session_run_id_rejects_non_integer_versions(
    invalid_version: object,
) -> None:
    factory = LocalArtifactIdFactory(Pseudonymizer(bytes(range(32))))
    with pytest.raises(ValueError, match="metric pack version must be positive"):
        factory.session_analysis_run_id(
            "synthetic-retry",
            Provider.SYNTHETIC,
            SESSION_ID,
            "synthetic-pack-v1",
            invalid_version,  # type: ignore[arg-type]
        )


class TickingClock:
    def __init__(self) -> None:
        self.calls = 0
        self._lock = Lock()

    def __call__(self) -> datetime:
        with self._lock:
            value = NOW + timedelta(seconds=self.calls)
            self.calls += 1
            return value


class MutablePreviewClock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class MemoryAccessPolicy:
    def __init__(self, *, consent: bool = True, indexed: bool = True) -> None:
        self.consent = consent
        self.indexed = indexed
        self.consent_calls = 0
        self.index_calls = 0

    def has_active_consent(self, provider: Provider, tier: DataTier) -> bool:
        self.consent_calls += 1
        assert provider is Provider.SYNTHETIC
        assert tier is DataTier.REDACTED_CONTENT
        return self.consent

    def selection_is_indexed(
        self,
        provider: Provider,
        *,
        project_ids: frozenset[str],
        session_ids: frozenset[str],
    ) -> bool:
        self.index_calls += 1
        assert provider is Provider.SYNTHETIC
        assert project_ids == frozenset()
        assert session_ids == frozenset((SESSION_ID,))
        return self.indexed


class MemoryCompatibilityPolicy:
    def __init__(self, *, compatible: bool = True) -> None:
        self.compatible = compatible
        self.calls = 0

    def require_compatible(self, provider: str) -> object:
        self.calls += 1
        assert provider == Provider.SYNTHETIC.value
        if not self.compatible:
            raise RuntimeError("synthetic compatibility blocked")
        return object()


class MemorySessionAnalysisRepository:
    def __init__(self) -> None:
        self.runs: dict[str, SessionAnalysisRunRecord] = {}
        self.results: dict[str, tuple[SessionAnalysisResultRecord, ...]] = {}
        self.begin_count = 0
        self.complete_count = 0
        self.fail_count = 0

    def begin(
        self,
        draft: SessionAnalysisRunDraft,
        *,
        completion_authority: SessionAnalysisCompletionAuthority | None = None,
    ) -> None:
        del completion_authority
        self.begin_count += 1
        if draft.run_id in self.runs:
            raise RuntimeError("duplicate synthetic run")
        self.runs[draft.run_id] = SessionAnalysisRunRecord(
            draft=draft,
            status=AnalysisRunStatus.RUNNING,
        )

    def complete(
        self,
        run_id: str,
        results: tuple[SessionAnalysisResultRecord, ...],
        *,
        finished_at: datetime,
        completion_authority: SessionAnalysisCompletionAuthority | None = None,
    ) -> None:
        del completion_authority
        self.complete_count += 1
        current = self.runs[run_id]
        if current.status is not AnalysisRunStatus.RUNNING:
            raise RuntimeError("synthetic run is already terminal")
        self.results[run_id] = results
        self.runs[run_id] = SessionAnalysisRunRecord(
            draft=current.draft,
            status=AnalysisRunStatus.COMPLETED,
            finished_at=finished_at,
        )

    def fail(self, run_id: str, *, finished_at: datetime, failure_code: str) -> None:
        self.fail_count += 1
        current = self.runs[run_id]
        self.runs[run_id] = SessionAnalysisRunRecord(
            draft=current.draft,
            status=AnalysisRunStatus.FAILED,
            finished_at=finished_at,
            failure_code=failure_code,
        )

    def get(self, run_id: str) -> SessionAnalysisRunRecord | None:
        return self.runs.get(run_id)

    def list_for_session(
        self, session_id: str, *, limit: int = 100, offset: int = 0
    ) -> tuple[SessionAnalysisRunRecord, ...]:
        del limit, offset
        return tuple(
            record for record in self.runs.values() if record.draft.session_id == session_id
        )

    def get_latest_completed(
        self, session_id: str
    ) -> SessionAnalysisRunRecord | None:
        matching = tuple(
            record
            for record in self.list_for_session(session_id)
            if record.status is AnalysisRunStatus.COMPLETED
        )
        return matching[-1] if matching else None

    def get_results(
        self, run_id: str
    ) -> tuple[SessionAnalysisResultRecord, ...]:
        return self.results.get(run_id, ())

    def delete_for_privacy(self, run_id: str) -> bool:
        self.results.pop(run_id, None)
        return self.runs.pop(run_id, None) is not None


class BeginRaceRepository(MemorySessionAnalysisRepository):
    """Pretend another process persisted the identical draft first."""

    def begin(
        self,
        draft: SessionAnalysisRunDraft,
        *,
        completion_authority: SessionAnalysisCompletionAuthority | None = None,
    ) -> None:
        super().begin(draft, completion_authority=completion_authority)
        raise RuntimeError("synthetic competing writer")


class FailingBeginRepository(MemorySessionAnalysisRepository):
    def begin(
        self,
        draft: SessionAnalysisRunDraft,
        *,
        completion_authority: SessionAnalysisCompletionAuthority | None = None,
    ) -> None:
        del draft, completion_authority
        self.begin_count += 1
        raise RuntimeError("PRIVATE-PERSISTENCE-ERROR-CANARY")


class RecordingSource:
    provider = Provider.SYNTHETIC
    purpose = TextAnalysisPurpose.TEXT_ANALYSIS
    read_only = True
    requires_explicit_selection = True

    def __init__(
        self,
        *,
        fail: bool = False,
        failure_reason: TextSourceFailureReason | None = None,
        available_message_kinds: frozenset[TextMessageKind] | None = None,
    ) -> None:
        self.fail = fail
        self.failure_reason = failure_reason
        self.available_message_kinds = (
            frozenset(TextMessageKind)
            if available_message_kinds is None
            else available_message_kinds
        )
        self.read_count = 0
        self.selections: list[TextAnalysisSelection] = []
        self.grants: list[TextSourceAccessGrant] = []
        self.task_profiles: list[TextTaskProfile] = []

    def read(
        self,
        *,
        selection: TextAnalysisSelection,
        grant: TextSourceAccessGrant,
        task_profile: TextTaskProfile,
    ) -> P1TextAnalysisInput:
        self.read_count += 1
        self.selections.append(selection)
        self.grants.append(grant)
        self.task_profiles.append(task_profile)
        if self.fail:
            raise RuntimeError("PRIVATE-SOURCE-ERROR-CANARY")
        if self.failure_reason is not None:
            raise TextSourceReadError(self.failure_reason)
        return _context(
            task_profile,
            available_message_kinds=self.available_message_kinds,
        )


class RecordingSourceFactory:
    def __init__(self, source: RecordingSource) -> None:
        self.source = source
        self.call_count = 0

    def __call__(self, provider: Provider) -> RecordingSource:
        self.call_count += 1
        assert provider is Provider.SYNTHETIC
        return self.source


class BlockingRecordingSource(RecordingSource):
    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()

    def read(
        self,
        *,
        selection: TextAnalysisSelection,
        grant: TextSourceAccessGrant,
        task_profile: TextTaskProfile,
    ) -> P1TextAnalysisInput:
        self.entered.set()
        assert self.release.wait(timeout=5)
        return super().read(
            selection=selection,
            grant=grant,
            task_profile=task_profile,
        )


class FailingMetricEngine:
    registry = DEFAULT_TEXT_METRIC_ENGINE.registry
    engine_version = "synthetic-failing-engine-1"
    algorithm_id = "synthetic.failing.algorithm"
    algorithm_version = "1"
    rubric_version = "synthetic-rubric-1"
    model_plan_identity = ("model", "none")

    def compute(self, *args: object, **kwargs: object) -> tuple[()]:
        del args, kwargs
        raise RuntimeError("PRIVATE-METRIC-ERROR-CANARY")


class AlternateSyntheticExtractor(DeterministicTextFeatureExtractor):
    algorithm_id = "rules.synthetic.alternate"
    algorithm_version = "example-2"


def _profile(
    *,
    expected_outcomes: int = 1,
    conversation_applicability: MetricApplicability = MetricApplicability.UNKNOWN,
) -> TextTaskProfile:
    return TextTaskProfile(
        applicability=tuple(
            MetricApplicabilityDecision(
                metric_key=definition.key,
                applicability=(
                    MetricApplicability.NOT_APPLICABLE
                    if definition.key == "logic.plan_state_accounting"
                    else conversation_applicability
                    if definition.key == "logic.conversation_loop_closure"
                    else MetricApplicability.APPLICABLE
                ),
                basis=ApplicabilityBasis.USER_SELECTED,
            )
            for definition in TEXT_METRIC_DEFINITIONS
        ),
        expected_constraint_kinds=(ConstraintKind.PRIVACY, ConstraintKind.SAFETY),
        expected_deliverable_slots=(DeliverableSlot.ARTIFACT, DeliverableSlot.FORMAT),
        expected_outcome_count=expected_outcomes,
    )


def _message(
    value: str,
    sequence: int,
    text: str,
    *,
    role: TextRole,
    kind: TextMessageKind,
) -> EphemeralRedactedMessage:
    return EphemeralRedactedMessage(
        message_id=value * 64,
        sequence=sequence,
        role=role,
        kind=kind,
        language=TextLanguage.ENGLISH,
        text=SecretStr(text),
    )


def _context(
    profile: TextTaskProfile,
    *,
    available_message_kinds: frozenset[TextMessageKind] = frozenset(TextMessageKind),
) -> P1TextAnalysisInput:
    messages = (
        _message(
            "1",
            0,
            (
                "Build an example PNG dashboard for engineering users so they can "
                "review results. Processing must stay local and safe. The export "
                "must exist and synthetic tests must pass. Which theme should be used?"
            ),
            role=TextRole.USER,
            kind=TextMessageKind.REQUEST,
        ),
        _message(
            "2",
            1,
            "Build the example dashboard and verify the synthetic export.",
            role=TextRole.AGENT,
            kind=TextMessageKind.PLAN,
        ),
        _message(
            "3",
            2,
            "The example theme will use navy.",
            role=TextRole.AGENT,
            kind=TextMessageKind.RESPONSE,
        ),
    )
    return P1TextAnalysisInput(
        provider=Provider.SYNTHETIC,
        session_id=SESSION_ID,
        provider_version="synthetic-1",
        adapter_version="synthetic-adapter-1",
        source_schema_version="synthetic-source-1",
        content_schema_version="redacted-message-1",
        redactor_version="synthetic-redactor-1",
        text_extraction_complete=True,
        available_message_kinds=available_message_kinds,
        analysis_window_fingerprint=WINDOW_ID,
        focus_message_id="1" * 64,
        observed_message_count=len(messages),
        eligible_message_count=5,
        messages=messages,
        task_profile=profile,
    )


def _service(
    *,
    policy: MemoryAccessPolicy | None = None,
    repository: MemorySessionAnalysisRepository | None = None,
    source: RecordingSource | None = None,
    compatibility: MemoryCompatibilityPolicy | None = None,
    metric_engine: object = DEFAULT_TEXT_METRIC_ENGINE,
    clock: object | None = None,
    preview_store: InMemoryRedactionPreviewStore | None = None,
) -> tuple[
    SessionTextAnalysisService,
    MemorySessionAnalysisRepository,
    RecordingSource,
    RecordingSourceFactory,
]:
    repository = repository or MemorySessionAnalysisRepository()
    source = source or RecordingSource()
    factory = RecordingSourceFactory(source)
    service = SessionTextAnalysisService(
        policy or MemoryAccessPolicy(),
        repository,
        factory,
        compatibility or MemoryCompatibilityPolicy(),
        LocalArtifactIdFactory(Pseudonymizer(bytes(range(32)))),
        schema_version=8,
        metric_engine=metric_engine,  # type: ignore[arg-type]
        clock=clock or TickingClock(),  # type: ignore[arg-type]
        preview_store=preview_store,
    )
    return service, repository, source, factory


def _run(
    service: SessionTextAnalysisService,
    *,
    profile: TextTaskProfile | None = None,
    confirmation: str = SESSION_TEXT_ANALYSIS_CONFIRMATION,
    idempotency_key: str = "example-run-1",
):
    return service.run(
        provider=Provider.SYNTHETIC,
        session_id=SESSION_ID,
        task_profile=profile or _profile(),
        confirmation=confirmation,
        idempotency_key=idempotency_key,
        max_messages=20,
        max_characters=20_000,
    )


def _run_preset(
    service: SessionTextAnalysisService,
    *,
    preset_id: TextAnalysisPresetId = TextAnalysisPresetId.STANDARD_ENGINEERING_V1,
    confirmation: str = SESSION_TEXT_ANALYSIS_CONFIRMATION,
    idempotency_key: str = "example-preset-run-1",
    selected_metric_keys: tuple[str, ...] | None = None,
):
    return service.run_preset(
        provider=Provider.SYNTHETIC,
        session_id=SESSION_ID,
        preset_id=preset_id,
        confirmation=confirmation,
        idempotency_key=idempotency_key,
        selected_metric_keys=selected_metric_keys,
    )


def test_automation_preset_checks_every_blocking_boundary_and_marks_commit() -> None:
    service, repository, source, _factory = _service()
    checkpoints: list[int] = []
    committed: list[bool] = []
    metric_key = COACHING_METRIC_DEFINITIONS[0].key

    outcome = service.run_preset(
        provider=Provider.SYNTHETIC,
        session_id=SESSION_ID,
        preset_id=TextAnalysisPresetId.COACHING_PROFILE_V1,
        confirmation=SESSION_TEXT_ANALYSIS_CONFIRMATION,
        idempotency_key="example-automation-boundaries",
        selected_metric_keys=(metric_key,),
        completion_authority=SessionAnalysisCompletionAuthority(
            job_id="7" * 64,
            automation_grant_id="8" * 64,
            lease_owner="9" * 64,
            lease_token="a" * 64,
        ),
        cooperative_check=lambda: checkpoints.append(len(checkpoints) + 1),
        publication_committed_callback=lambda: committed.append(True),
    )

    assert outcome.status is AnalysisRunStatus.COMPLETED
    assert outcome.result_count == 1
    assert source.read_count == 1
    assert repository.begin_count == repository.complete_count == 1
    assert checkpoints == list(range(1, 14))
    assert committed == [True]


def test_cooperative_stop_after_run_begin_escapes_without_generic_relabel() -> None:
    service, repository, _source, _factory = _service()
    calls = 0

    def stop_after_begin() -> None:
        nonlocal calls
        calls += 1
        if calls == 5:
            raise SessionTextAnalysisCooperativeStop(
                "automation_publication_deadline_exceeded"
            )

    with pytest.raises(SessionTextAnalysisCooperativeStop) as raised:
        service.run_preset(
            provider=Provider.SYNTHETIC,
            session_id=SESSION_ID,
            preset_id=TextAnalysisPresetId.COACHING_PROFILE_V1,
            confirmation=SESSION_TEXT_ANALYSIS_CONFIRMATION,
            idempotency_key="example-automation-stop",
            selected_metric_keys=(COACHING_METRIC_DEFINITIONS[0].key,),
            completion_authority=SessionAnalysisCompletionAuthority(
                job_id="7" * 64,
                automation_grant_id="8" * 64,
                lease_owner="9" * 64,
                lease_token="a" * 64,
            ),
            cooperative_check=stop_after_begin,
        )

    assert raised.value.reason_code == "automation_publication_deadline_exceeded"
    assert repository.begin_count == 1
    assert repository.complete_count == repository.fail_count == 0


def test_deadline_observed_after_failing_provider_read_outranks_source_error() -> None:
    service, repository, source, _factory = _service(
        source=RecordingSource(fail=True)
    )
    calls = 0

    def stop_after_provider_returns() -> None:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise SessionTextAnalysisCooperativeStop(
                "automation_publication_deadline_exceeded"
            )

    with pytest.raises(SessionTextAnalysisCooperativeStop):
        service.run_preset(
            provider=Provider.SYNTHETIC,
            session_id=SESSION_ID,
            preset_id=TextAnalysisPresetId.COACHING_PROFILE_V1,
            confirmation=SESSION_TEXT_ANALYSIS_CONFIRMATION,
            idempotency_key="example-provider-deadline-stop",
            selected_metric_keys=(COACHING_METRIC_DEFINITIONS[0].key,),
            cooperative_check=stop_after_provider_returns,
        )

    assert source.read_count == 1
    assert repository.runs == {}


def test_deadline_observed_after_failing_compute_outranks_execution_error() -> None:
    service, repository, _source, _factory = _service(
        metric_engine=FailingMetricEngine()
    )
    calls = 0

    def stop_after_compute_returns() -> None:
        nonlocal calls
        calls += 1
        if calls == 7:
            raise SessionTextAnalysisCooperativeStop(
                "automation_publication_deadline_exceeded"
            )

    with pytest.raises(SessionTextAnalysisCooperativeStop):
        service.run_preset(
            provider=Provider.SYNTHETIC,
            session_id=SESSION_ID,
            preset_id=TextAnalysisPresetId.STANDARD_ENGINEERING_V1,
            confirmation=SESSION_TEXT_ANALYSIS_CONFIRMATION,
            idempotency_key="example-compute-deadline-stop",
            cooperative_check=stop_after_compute_returns,
        )

    assert repository.begin_count == 1
    assert repository.fail_count == 0


class PublicationRejectingRepository(MemorySessionAnalysisRepository):
    def complete(
        self,
        run_id: str,
        results: tuple[SessionAnalysisResultRecord, ...],
        *,
        finished_at: datetime,
        completion_authority: SessionAnalysisCompletionAuthority | None = None,
    ) -> None:
        del results, completion_authority
        current = self.runs[run_id]
        self.runs[run_id] = SessionAnalysisRunRecord(
            draft=current.draft,
            status=AnalysisRunStatus.FAILED,
            finished_at=finished_at,
            failure_code="automation_publication_deadline_exceeded",
        )
        raise SessionAnalysisPublicationRejectedError(
            "automation_publication_deadline_exceeded"
        )


def test_atomic_publication_rejection_preserves_fixed_cooperative_reason() -> None:
    repository = PublicationRejectingRepository()
    service, _repository, _source, _factory = _service(repository=repository)

    with pytest.raises(SessionTextAnalysisCooperativeStop) as raised:
        service.run_preset(
            provider=Provider.SYNTHETIC,
            session_id=SESSION_ID,
            preset_id=TextAnalysisPresetId.COACHING_PROFILE_V1,
            confirmation=SESSION_TEXT_ANALYSIS_CONFIRMATION,
            idempotency_key="example-automation-rejection",
            selected_metric_keys=(COACHING_METRIC_DEFINITIONS[0].key,),
            completion_authority=SessionAnalysisCompletionAuthority(
                job_id="7" * 64,
                automation_grant_id="8" * 64,
                lease_owner="9" * 64,
                lease_token="a" * 64,
            ),
            cooperative_check=lambda: None,
        )

    assert raised.value.reason_code == "automation_publication_deadline_exceeded"
    assert repository.fail_count == 0


def test_completed_automation_replay_marks_publication_before_any_checkpoint() -> None:
    service, repository, source, _factory = _service()
    committed: list[bool] = []
    authority = SessionAnalysisCompletionAuthority(
        job_id="7" * 64,
        automation_grant_id="8" * 64,
        lease_owner="9" * 64,
        lease_token="a" * 64,
    )
    values = {
        "provider": Provider.SYNTHETIC,
        "session_id": SESSION_ID,
        "preset_id": TextAnalysisPresetId.COACHING_PROFILE_V1,
        "confirmation": SESSION_TEXT_ANALYSIS_CONFIRMATION,
        "idempotency_key": "example-automation-replay",
        "selected_metric_keys": (COACHING_METRIC_DEFINITIONS[0].key,),
        "completion_authority": authority,
        "publication_committed_callback": lambda: committed.append(True),
    }

    first = service.run_preset(cooperative_check=lambda: None, **values)

    def unexpected_checkpoint() -> None:
        raise AssertionError("completed replay must win before deadline checks")

    replay = service.run_preset(
        cooperative_check=unexpected_checkpoint,
        **values,
    )

    assert first.applied is True
    assert replay.applied is False
    assert source.read_count == 1
    assert repository.complete_count == 1
    assert committed == [True, True]


def _preview_approval(
    inspection,
    *,
    expected_binding=None,
    idempotency_key: str = "example-preview-run-1",
) -> AnalysisApproval:
    return AnalysisApproval(
        preview_id=inspection.receipt.preview_id,
        confirmation=REDACTION_PREVIEW_CONFIRMATION,
        idempotency_key=idempotency_key,
        expected_binding=expected_binding or inspection.receipt.binding,
    )


def test_preview_approval_uses_exact_context_without_second_read_or_text_persistence(
) -> None:
    policy = MemoryAccessPolicy()
    compatibility = MemoryCompatibilityPolicy()
    service, repository, source, factory = _service(
        policy=policy,
        compatibility=compatibility,
    )

    preview = service.prepare_preset_preview(
        provider=Provider.SYNTHETIC,
        session_id=SESSION_ID,
        preset_id=TextAnalysisPresetId.STANDARD_ENGINEERING_V1,
    )
    assert source.read_count == factory.call_count == 1
    assert repository.runs == {}
    assert "Build an example" in preview.messages[0].text.get_secret_value()
    assert "Build an example" not in repr(preview)

    outcome = service.approve_preview(_preview_approval(preview))

    assert outcome.status is AnalysisRunStatus.COMPLETED
    assert source.read_count == factory.call_count == 1
    assert policy.consent_calls == policy.index_calls == 2
    assert compatibility.calls == 2
    persisted = "".join(
        record.model_dump_json() for record in repository.runs.values()
    ) + "".join(
        result.model_dump_json()
        for results in repository.results.values()
        for result in results
    )
    assert "Build an example" not in persisted
    assert "example theme" not in persisted


def test_preview_binding_mismatch_is_non_consuming_then_approval_is_one_shot(
) -> None:
    service, repository, source, _factory = _service()
    preview = service.prepare_preset_preview(
        provider=Provider.SYNTHETIC,
        session_id=SESSION_ID,
        preset_id=TextAnalysisPresetId.STANDARD_ENGINEERING_V1,
    )
    mismatched = preview.receipt.binding.model_copy(
        update={"exact_model": "different-local-model"}
    )

    with pytest.raises(RedactionPreviewMismatchError):
        service.approve_preview(
            _preview_approval(preview, expected_binding=mismatched)
        )

    outcome = service.approve_preview(_preview_approval(preview))
    assert outcome.status is AnalysisRunStatus.COMPLETED
    assert source.read_count == 1
    assert repository.complete_count == 1
    with pytest.raises(RedactionPreviewConsumedError):
        service.approve_preview(_preview_approval(preview))
    assert repository.complete_count == 1


def test_expired_preview_cannot_compute_or_persist() -> None:
    clock = MutablePreviewClock()
    preview_store = InMemoryRedactionPreviewStore(
        clock=clock,
        token_factory=lambda: "d" * 64,
    )
    service, repository, source, _factory = _service(
        clock=clock,
        preview_store=preview_store,
    )
    preview = service.prepare_preset_preview(
        provider=Provider.SYNTHETIC,
        session_id=SESSION_ID,
        preset_id=TextAnalysisPresetId.STANDARD_ENGINEERING_V1,
    )
    clock.advance(timedelta(minutes=10))

    with pytest.raises(RedactionPreviewExpiredError):
        service.approve_preview(_preview_approval(preview))

    assert source.read_count == 1
    assert repository.runs == {}


def test_preview_approval_rechecks_revoked_consent_before_compute() -> None:
    policy = MemoryAccessPolicy()
    service, repository, source, _factory = _service(policy=policy)
    preview = service.prepare_preset_preview(
        provider=Provider.SYNTHETIC,
        session_id=SESSION_ID,
        preset_id=TextAnalysisPresetId.STANDARD_ENGINEERING_V1,
    )
    policy.consent = False

    with pytest.raises(SessionTextAnalysisConsentError):
        service.approve_preview(_preview_approval(preview))

    assert source.read_count == 1
    assert repository.runs == {}
    with pytest.raises(RedactionPreviewConsumedError):
        service.approve_preview(_preview_approval(preview))


@pytest.mark.parametrize(
    ("policy", "confirmation", "error_type"),
    (
        (
            MemoryAccessPolicy(consent=False),
            SESSION_TEXT_ANALYSIS_CONFIRMATION,
            SessionTextAnalysisConsentError,
        ),
        (
            MemoryAccessPolicy(indexed=False),
            SESSION_TEXT_ANALYSIS_CONFIRMATION,
            SessionTextAnalysisSelectionError,
        ),
        (
            MemoryAccessPolicy(),
            "not-confirmed",
            SessionTextAnalysisConfirmationError,
        ),
    ),
)
def test_denial_happens_before_source_creation_or_read(
    policy: MemoryAccessPolicy,
    confirmation: str,
    error_type: type[Exception],
) -> None:
    service, repository, source, factory = _service(policy=policy)

    with pytest.raises(error_type):
        _run(service, confirmation=confirmation)

    assert factory.call_count == 0
    assert source.read_count == 0
    assert repository.begin_count == 0


def test_incompatible_provider_is_blocked_before_source_creation_or_read() -> None:
    compatibility = MemoryCompatibilityPolicy(compatible=False)
    service, repository, source, factory = _service(
        compatibility=compatibility
    )

    with pytest.raises(SessionTextAnalysisCompatibilityError):
        _run(service)

    assert compatibility.calls == 1
    assert factory.call_count == source.read_count == 0
    assert repository.begin_count == 0


@pytest.mark.parametrize(
    "profile",
    (
        TextTaskProfile(applicability=()),
        _profile().model_copy(
            update={
                "applicability": tuple(
                    decision.model_copy(
                        update={"basis": ApplicabilityBasis.TASK_PROFILE}
                    )
                    for decision in _profile().applicability
                )
            }
        ),
    ),
)
def test_application_boundary_requires_complete_user_selected_profile_before_access(
    profile: TextTaskProfile,
) -> None:
    policy = MemoryAccessPolicy()
    service, repository, source, factory = _service(policy=policy)

    with pytest.raises(SessionTextAnalysisInputError):
        _run(service, profile=profile)

    assert policy.consent_calls == policy.index_calls == 0
    assert factory.call_count == source.read_count == 0
    assert repository.begin_count == 0


def test_standard_preset_is_server_owned_bounded_and_explicitly_provenanced() -> None:
    source = RecordingSource(
        available_message_kinds=frozenset(
            {
                TextMessageKind.REQUEST,
                TextMessageKind.RESPONSE,
                TextMessageKind.PLAN,
            }
        )
    )
    service, repository, _, factory = _service(source=source)

    outcome = _run_preset(service)

    assert outcome.analysis_profile_key == "standard_engineering"
    assert outcome.analysis_profile_version == 1
    assert factory.call_count == source.read_count == 1
    assert source.selections[0].max_messages == 100
    assert source.selections[0].max_characters == 100_000
    assert source.task_profiles == [STANDARD_ENGINEERING_V1.task_profile]
    profile = source.task_profiles[0]
    assert all(
        decision.applicability is MetricApplicability.APPLICABLE
        and decision.basis is ApplicabilityBasis.TASK_PROFILE
        for decision in profile.applicability
    )
    assert tuple(slot.value for slot in profile.expected_goal_slots) == (
        "action",
        "target",
        "outcome",
    )
    assert profile.expected_constraint_kinds == ()
    assert profile.expected_deliverable_slots == ()
    assert profile.expected_outcome_count is None
    stored = repository.get(outcome.run_id)
    assert stored is not None
    assert stored.draft.analysis_profile_key == "standard_engineering"
    assert stored.draft.analysis_profile_version == 1
    results = {
        item.observation.key: item
        for item in repository.get_results(outcome.run_id)
    }
    for key in (
        "prompt.constraint_resolution",
        "prompt.deliverable_contract",
        "logic.requirement_action_traceability",
        "logic.decision_rationale_coverage",
    ):
        assert results[key].value_state.value == "abstained"
        assert results[key].observation.numeric_value is None
    assert results["prompt.constraint_resolution"].explanation_code == "denominator_unknown"
    assert results["prompt.deliverable_contract"].explanation_code == "denominator_unknown"
    assert results["logic.requirement_action_traceability"].explanation_code == "message_kind_unavailable"
    assert results["logic.decision_rationale_coverage"].explanation_code == "message_kind_unavailable"


def test_coaching_preset_produces_twenty_typed_results_in_its_own_immutable_pack() -> None:
    source = RecordingSource(
        available_message_kinds=frozenset(
            {
                TextMessageKind.REQUEST,
                TextMessageKind.RESPONSE,
                TextMessageKind.PLAN,
            }
        )
    )
    service, repository, _, _ = _service(source=source)

    outcome = _run_preset(
        service,
        preset_id=TextAnalysisPresetId.COACHING_PROFILE_V1,
        idempotency_key="example-coaching-run-1",
    )

    assert outcome.result_count == 20
    assert outcome.analysis_profile_key == "coaching_profile"
    assert source.task_profiles == [COACHING_PROFILE_V1.task_profile]
    stored = repository.get(outcome.run_id)
    assert stored is not None
    assert stored.draft.metric_pack_key == COACHING_METRIC_PACK_KEY
    assert stored.draft.metric_pack_version == COACHING_METRIC_PACK_VERSION
    assert stored.draft.selected_metric_keys == tuple(
        sorted(definition.key for definition in COACHING_METRIC_DEFINITIONS)
    )
    results = repository.get_results(outcome.run_id)
    assert tuple(
        (item.observation.key, item.observation.version) for item in results
    ) == tuple(
        (definition.key, definition.version)
        for definition in COACHING_METRIC_DEFINITIONS
    )
    by_key = {item.observation.key: item for item in results}
    assert by_key["outcome.first_pass_verification"].value_state.value == "abstained"
    assert by_key["outcome.first_pass_verification"].observation.numeric_value is None


@pytest.mark.parametrize(
    "selected_metric_keys",
    (
        ("prompt.context_sufficiency",),
        (
            "collaboration.rework_candidate_rate",
            "logic.decomposition_coverage",
            "prompt.context_sufficiency",
        ),
    ),
)
def test_explicit_coaching_scope_persists_only_selected_metrics(
    selected_metric_keys: tuple[str, ...],
) -> None:
    service, repository, source, _factory = _service()

    outcome = _run_preset(
        service,
        preset_id=TextAnalysisPresetId.COACHING_PROFILE_V1,
        idempotency_key=f"example-scoped-{len(selected_metric_keys)}",
        selected_metric_keys=selected_metric_keys,
    )

    assert outcome.result_count == len(selected_metric_keys)
    assert source.read_count == 1
    persisted = repository.get_results(outcome.run_id)
    assert tuple(item.observation.key for item in persisted) == selected_metric_keys
    stored = repository.get(outcome.run_id)
    assert stored is not None
    assert stored.draft.selected_metric_keys == selected_metric_keys
    assert not (
        {definition.key for definition in COACHING_METRIC_DEFINITIONS}
        - set(selected_metric_keys)
    ).intersection(item.observation.key for item in persisted)


def test_explicit_coaching_scope_is_fingerprinted_and_cannot_drift_on_retry() -> None:
    one_metric = ("prompt.context_sufficiency",)
    three_metrics = (
        "collaboration.rework_candidate_rate",
        "logic.decomposition_coverage",
        "prompt.context_sufficiency",
    )
    service, repository, source, _factory = _service()
    first = _run_preset(
        service,
        preset_id=TextAnalysisPresetId.COACHING_PROFILE_V1,
        idempotency_key="example-scope-stable",
        selected_metric_keys=one_metric,
    )
    first_draft = repository.runs[first.run_id].draft

    with pytest.raises(SessionTextAnalysisConflictError):
        _run_preset(
            service,
            preset_id=TextAnalysisPresetId.COACHING_PROFILE_V1,
            idempotency_key="example-scope-stable",
            selected_metric_keys=three_metrics,
        )

    assert source.read_count == 1
    assert repository.complete_count == 1
    assert tuple(
        item.observation.key for item in repository.get_results(first.run_id)
    ) == one_metric

    other_service, other_repository, _, _ = _service()
    other = _run_preset(
        other_service,
        preset_id=TextAnalysisPresetId.COACHING_PROFILE_V1,
        idempotency_key="example-scope-stable",
        selected_metric_keys=three_metrics,
    )
    other_draft = other_repository.runs[other.run_id].draft
    assert other.run_id == first.run_id
    assert other_draft.request_fingerprint != first_draft.request_fingerprint
    assert (
        other_draft.model_plan_fingerprint
        != first_draft.model_plan_fingerprint
    )


def test_real_repository_aggregates_overlap_across_distinct_scope_plans(
    tmp_path,
) -> None:
    database = Database(tmp_path / "scope-aggregation.sqlite3")
    database.initialize()
    pseudonymizer = Pseudonymizer(bytes(range(32)))
    IngestionService(database, pseudonymizer).ingest(SyntheticAdapter())
    session_ids = tuple(
        row["session_id"] for row in database.list_sessions(limit=10)
    )
    assert len(session_ids) == 2

    class MultiSessionPolicy:
        def has_active_consent(
            self, provider: Provider, tier: DataTier
        ) -> bool:
            return (
                provider is Provider.SYNTHETIC
                and tier is DataTier.REDACTED_CONTENT
            )

        def selection_is_indexed(
            self,
            provider: Provider,
            *,
            project_ids: frozenset[str],
            session_ids: frozenset[str],
        ) -> bool:
            return (
                provider is Provider.SYNTHETIC
                and not project_ids
                and len(session_ids) == 1
            )

    class MultiSessionSource(RecordingSource):
        def read(
            self,
            *,
            selection: TextAnalysisSelection,
            grant: TextSourceAccessGrant,
            task_profile: TextTaskProfile,
        ) -> P1TextAnalysisInput:
            del grant
            session_id = selection.session_id
            return _context(task_profile).model_copy(
                update={
                    "session_id": session_id,
                    "analysis_window_fingerprint": session_id,
                }
            )

    repository = database.session_analysis_run_repository()
    source = MultiSessionSource()
    service = SessionTextAnalysisService(
        MultiSessionPolicy(),  # type: ignore[arg-type]
        repository,
        lambda provider: source
        if provider is Provider.SYNTHETIC
        else (_ for _ in ()).throw(ValueError("unsupported synthetic provider")),
        MemoryCompatibilityPolicy(),
        LocalArtifactIdFactory(pseudonymizer),
        schema_version=SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
        clock=TickingClock(),
    )
    first_scope = ("prompt.context_sufficiency",)
    second_scope = (
        "logic.decomposition_coverage",
        "prompt.context_sufficiency",
    )
    outcomes = (
        service.run_preset(
            provider=Provider.SYNTHETIC,
            session_id=session_ids[0],
            preset_id=TextAnalysisPresetId.COACHING_PROFILE_V1,
            confirmation=SESSION_TEXT_ANALYSIS_CONFIRMATION,
            idempotency_key="example-real-scope-a",
            selected_metric_keys=first_scope,
        ),
        service.run_preset(
            provider=Provider.SYNTHETIC,
            session_id=session_ids[1],
            preset_id=TextAnalysisPresetId.COACHING_PROFILE_V1,
            confirmation=SESSION_TEXT_ANALYSIS_CONFIRMATION,
            idempotency_key="example-real-scope-ab",
            selected_metric_keys=second_scope,
        ),
    )
    runs = tuple(repository.get(outcome.run_id) for outcome in outcomes)
    assert all(run is not None for run in runs)
    assert runs[0].draft.model_plan_fingerprint != runs[1].draft.model_plan_fingerprint  # type: ignore[union-attr]

    aggregate = SessionQualityAggregationService(
        repository,
        definitions=COACHING_METRIC_DEFINITIONS,
        analysis_profile_key=COACHING_PROFILE_V1.analysis_profile_key,
        analysis_profile_version=COACHING_PROFILE_V1.analysis_profile_version,
        metric_pack_key=COACHING_METRIC_PACK_KEY,
        metric_pack_version=COACHING_METRIC_PACK_VERSION,
    ).aggregate(SessionQualitySelection(session_ids=session_ids))
    by_key = {metric.metric_key: metric for metric in aggregate.metrics}
    shared = by_key["prompt.context_sufficiency"]
    second_only = by_key["logic.decomposition_coverage"]
    assert len(shared.compatibility_cohorts) == 1
    assert shared.compatibility_cohorts[0].result_count == 2
    assert shared.not_selected_run_count == 0
    assert second_only.present_result_count == 1
    assert second_only.not_selected_run_count == 1
    assert second_only.missing_result_count == 0


def test_unknown_coaching_scope_fails_before_policy_or_provider_access() -> None:
    policy = MemoryAccessPolicy()
    service, repository, source, factory = _service(policy=policy)

    with pytest.raises(SessionTextAnalysisInputError):
        _run_preset(
            service,
            preset_id=TextAnalysisPresetId.COACHING_PROFILE_V1,
            idempotency_key="example-unknown-scope",
            selected_metric_keys=("prompt.not_registered",),
        )

    assert policy.consent_calls == policy.index_calls == 0
    assert factory.call_count == source.read_count == 0
    assert repository.begin_count == 0


def test_unknown_preset_is_rejected_before_policy_or_source_access() -> None:
    policy = MemoryAccessPolicy()
    service, repository, source, factory = _service(policy=policy)

    with pytest.raises(SessionTextAnalysisInputError):
        _run_preset(service, preset_id="private-preset")  # type: ignore[arg-type]

    assert policy.consent_calls == policy.index_calls == 0
    assert factory.call_count == source.read_count == 0
    assert repository.begin_count == 0


def test_completed_run_maps_all_ten_metrics_and_preserves_partial_typed_states() -> None:
    service, repository, source, factory = _service()

    outcome = _run(service)

    assert outcome.status is AnalysisRunStatus.COMPLETED
    assert outcome.result_count == 10
    assert outcome.applied is True
    assert outcome.analysis_profile_key == "explicit.user-profile"
    assert outcome.analysis_profile_version == 1
    assert factory.call_count == source.read_count == 1
    assert repository.begin_count == repository.complete_count == 1
    stored = repository.get_results(outcome.run_id)
    assert len(stored) == 10
    assert {item.observation.key for item in stored} == {
        definition.key for definition in TEXT_METRIC_DEFINITIONS
    }
    assert all(item.observation.observed_count == 3 for item in stored)
    assert all(item.observation.eligible_count == 5 for item in stored)
    assert all(item.observation.coverage == pytest.approx(0.6) for item in stored)
    assert any(item.fraction_denominator is not None for item in stored)
    assert next(
        item
        for item in stored
        if item.observation.key == "logic.plan_state_accounting"
    ).value_state.value == "not_applicable"
    assert next(
        item
        for item in stored
        if item.observation.key == "logic.conversation_loop_closure"
    ).value_state.value == "unknown"
    assert all(item.algorithm_id == TEXT_METRIC_ALGORITHM_ID for item in stored)
    assert all(item.algorithm_version == TEXT_METRIC_ALGORITHM_VERSION for item in stored)
    assert all(item.model_id is None for item in stored)
    assert all("Build an example" not in item.model_dump_json() for item in stored)
    assert source.grants[0].per_run_confirmation_active is True
    assert source.grants[0].content_persistence_allowed is False


def test_unavailable_codex_like_kinds_are_persisted_as_abstentions_not_zeroes() -> None:
    source = RecordingSource(
        available_message_kinds=frozenset(
            {
                TextMessageKind.REQUEST,
                TextMessageKind.RESPONSE,
                TextMessageKind.PLAN,
            }
        )
    )
    service, repository, _, _ = _service(source=source)

    outcome = _run(service)

    results = {
        item.observation.key: item
        for item in repository.get_results(outcome.run_id)
    }
    for key in (
        "logic.requirement_action_traceability",
        "logic.decision_rationale_coverage",
    ):
        assert results[key].value_state.value == "abstained"
        assert results[key].observation.numeric_value is None
        assert results[key].fraction_numerator is None
        assert results[key].explanation_code == "message_kind_unavailable"


def test_sequential_retry_and_changed_request_are_decided_before_provider_read() -> None:
    service, _, source, factory = _service()
    first = _run(service)

    retry = _run(service)

    assert first.run_id == retry.run_id
    assert retry.status is AnalysisRunStatus.COMPLETED
    assert retry.applied is False
    assert retry.result_count == 10
    assert source.read_count == factory.call_count == 1

    with pytest.raises(SessionTextAnalysisConflictError):
        _run(service, profile=_profile(expected_outcomes=2))
    assert source.read_count == factory.call_count == 1


def test_concurrent_duplicate_reads_provider_once_in_one_process() -> None:
    service, repository, source, factory = _service()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(lambda _: _run(service), range(2)))

    assert {outcome.run_id for outcome in outcomes} == {outcomes[0].run_id}
    assert sorted(outcome.applied for outcome in outcomes) == [False, True]
    assert source.read_count == factory.call_count == 1
    assert repository.begin_count == repository.complete_count == 1


def test_matching_begin_race_returns_existing_without_a_second_read() -> None:
    repository = BeginRaceRepository()
    service, _, source, factory = _service(repository=repository)

    outcome = _run(service)

    assert outcome.status is AnalysisRunStatus.RUNNING
    assert outcome.applied is False
    assert outcome.result_count == 0
    assert source.read_count == factory.call_count == 1


def test_begin_failure_without_a_race_winner_is_sanitized() -> None:
    repository = FailingBeginRepository()
    service, _, source, factory = _service(repository=repository)

    with pytest.raises(SessionTextAnalysisPersistenceError) as raised:
        _run(service)

    assert "PRIVATE-PERSISTENCE-ERROR-CANARY" not in str(raised.value)
    assert raised.value.__cause__ is None
    assert repository.runs == {}
    assert source.read_count == factory.call_count == 1


def test_queued_new_run_rechecks_consent_inside_command_lock() -> None:
    policy = MemoryAccessPolicy()
    source = BlockingRecordingSource()
    service, repository, _, factory = _service(policy=policy, source=source)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_run, service, idempotency_key="example-run-first")
        assert source.entered.wait(timeout=5)
        second = pool.submit(_run, service, idempotency_key="example-run-second")
        policy.consent = False
        source.release.set()

        assert first.result(timeout=5).status is AnalysisRunStatus.COMPLETED
        with pytest.raises(SessionTextAnalysisConsentError):
            second.result(timeout=5)

    assert source.read_count == factory.call_count == 1
    assert repository.begin_count == repository.complete_count == 1


def test_source_failure_is_sanitized_and_creates_no_run() -> None:
    service, repository, source, _ = _service(source=RecordingSource(fail=True))

    with pytest.raises(SessionTextAnalysisSourceError) as raised:
        _run(service)

    assert "PRIVATE-SOURCE-ERROR-CANARY" not in str(raised.value)
    assert raised.value.reason is TextSourceFailureReason.PROVIDER_UNAVAILABLE
    assert raised.value.__cause__ is None
    assert source.read_count == 1
    assert repository.runs == {}


@pytest.mark.parametrize("reason", tuple(TextSourceFailureReason))
def test_source_failure_reason_crosses_service_boundary_without_provider_data(
    reason: TextSourceFailureReason,
) -> None:
    service, repository, source, _ = _service(
        source=RecordingSource(failure_reason=reason)
    )

    with pytest.raises(SessionTextAnalysisSourceError) as raised:
        _run(service)

    assert source.read_count == 1
    assert raised.value.reason is reason
    assert raised.value.code == reason.value
    assert str(raised.value) == reason.value
    assert raised.value.__cause__ is None
    assert repository.runs == {}


def test_metric_failure_marks_run_failed_with_only_a_safe_code() -> None:
    service, repository, _, _ = _service(metric_engine=FailingMetricEngine())

    with pytest.raises(SessionTextAnalysisExecutionError) as raised:
        _run(service)

    assert "PRIVATE-METRIC-ERROR-CANARY" not in str(raised.value)
    assert raised.value.__cause__ is None
    assert repository.fail_count == 1
    record = next(iter(repository.runs.values()))
    assert record.status is AnalysisRunStatus.FAILED
    assert record.failure_code == SessionTextAnalysisExecutionError.code
    assert repository.get_results(record.draft.run_id) == ()


def test_composed_engine_identity_drives_plan_and_result_provenance() -> None:
    alternate = TextMetricEngine(extractor=AlternateSyntheticExtractor())
    service, repository, _, _ = _service(metric_engine=alternate)

    outcome = _run(service)

    record = repository.runs[outcome.run_id]
    results = repository.get_results(outcome.run_id)
    assert record.draft.metric_engine_version == alternate.engine_version
    assert all(item.algorithm_id == alternate.algorithm_id for item in results)
    assert all(item.algorithm_version == alternate.algorithm_version for item in results)

    default_service, default_repository, _, _ = _service()
    default_outcome = _run(default_service, idempotency_key="example-run-2")
    default_record = default_repository.runs[default_outcome.run_id]
    assert (
        record.draft.model_plan_fingerprint
        != default_record.draft.model_plan_fingerprint
    )
