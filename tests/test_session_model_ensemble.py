from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json

from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest

from test_requirement_action_evidence import (
    _Repository as _RequirementActionRecoveryRepositoryBase,
)
from test_requirement_plan_evidence import (
    _Repository as _RequirementPlanReviewRepository,
)

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.analysis.model_ensemble import (
    MODEL_ENSEMBLE_MODEL_COUNT,
    ModelExpertRole,
)
from prompt_enhancer.application.analysis.evidence_contracts import (
    ActionEvidence,
    ActionFamily,
    ActionState,
    EphemeralTypedEvidenceProjection,
    TypedEvidenceKind,
    TypedEvidenceOpportunityKind,
    TypedEvidenceProvenance,
    VerificationEvidence,
    VerificationMethod,
    VerificationOutcome,
)
from prompt_enhancer.application.providers import (
    CapabilityKey,
    DecoderDescriptor,
    ProviderIdentity,
    ProviderSurface,
    SchemaArtifactKind,
    SchemaArtifactProvenance,
)
from prompt_enhancer.application.analysis.session_model_ensemble import (
    LEGACY_MODEL_ENSEMBLE_CONFIRMATION,
    MODEL_ENSEMBLE_CONFIRMATION,
    ModelEnsembleConfirmationError,
    ModelEnsembleConsentError,
    ModelEnsembleExecutionError,
    ModelEnsembleRuntimeCleanupError,
    ModelEnsemblePersistenceError,
    REQUIREMENT_ACTION_BINDING_INVALID_FINGERPRINT,
    REQUIREMENT_ACTION_BINDING_INVALID_SCHEMA_VERSION,
    SessionModelEnsembleRunRecord,
    SessionModelEnsembleService,
    RequirementActionEvidenceSource,
    RequirementPlanEvidenceSource,
    RequirementVerificationEvidenceSource,
    VERIFIED_REQUIREMENT_METRIC_ALGORITHM_ID,
    VERIFIED_REQUIREMENT_METRIC_ALGORITHM_VERSION,
    VERIFIED_REQUIREMENT_METRIC_RUBRIC_VERSION,
)
from prompt_enhancer.application.analysis.metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_6,
    METRIC_PROJECTION_V2_VERSION_7,
    METRIC_PROJECTION_V2_VERSION_8,
)
from prompt_enhancer.application.analysis.provider_evidence import (
    RequirementActionCandidateManifestOverflowError,
)
from prompt_enhancer.application.analysis.requirement_action_evidence import (
    ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION,
    ConfirmedRequirementActionLink,
    InMemoryRequirementActionReviewContextStore,
    RequirementActionCandidate,
    RequirementActionCandidateManifest,
    REQUIREMENT_ACTION_DECISION_CONFIRMATION,
    REQUIREMENT_ACTION_EVIDENCE_FILE_VERSION,
    REQUIREMENT_ACTION_IMPORT_CONFIRMATION,
    RequirementActionDecisionCommand,
    RequirementActionDecisionKind,
    RequirementActionEvidenceFileV1,
    RequirementActionEvidenceService,
    RequirementActionLinkEntry,
    RequirementActionEvidenceSnapshot,
    RequirementActionNotFoundError,
    RequirementActionRequirement,
    SealedRunRequirementActionSource,
    requirement_action_candidate_manifest_fingerprint,
    requirement_action_candidate_metadata_fingerprint,
    requirement_action_evidence_snapshot_fingerprint,
    requirement_plan_snapshot_fingerprint,
)
from prompt_enhancer.application.analysis.requirement_plan_evidence import (
    REQUIREMENT_PLAN_DECISION_CONFIRMATION,
    REQUIREMENT_PLAN_EVIDENCE_FILE_VERSION,
    REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
    REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
    ConfirmedRequirementEvidence,
    InMemoryRequirementPlanReviewContextStore,
    RequirementCoordinate,
    RequirementDisposition,
    RequirementPlanDecisionCommand,
    RequirementPlanDecisionKind,
    RequirementPlanEvidenceService,
    RequirementPlanEvidenceSnapshot,
    RequirementPlanProducerReceipt,
    RequirementPlanProducer,
    SealedRunRequirementPlanSource,
)
from prompt_enhancer.application.analysis.semantic_units import SemanticUnitReconciler
from prompt_enhancer.application.analysis.model_ensemble_watch import (
    MODEL_ENSEMBLE_WATCH_CONFIRMATION,
    MODEL_ENSEMBLE_WATCH_PROGRESS_TOTAL,
    ModelEnsembleWatchLease,
    ModelEnsembleCanonicalHead,
    ModelEnsembleWatchRecord,
    ModelEnsembleWatchService,
    ModelEnsembleWatchState,
    ModelEnsembleTrajectoryPage,
)
from prompt_enhancer.application.analysis.text_analysis_presets import (
    COACHING_PROFILE_V1,
)
from prompt_enhancer.application.analysis.text_contracts import (
    ACTION_REVIEW_DESCRIPTOR_ALGORITHM_VERSION,
    EphemeralRedactedActionDescriptor,
    EphemeralRedactedMessage,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextRole,
)
from prompt_enhancer.application.analysis.text_source import TextAnalysisPurpose
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.domain import (
    DataTier,
    EventKind,
    Provider,
    SafeSession,
    SessionState,
    ToolCategory,
)
from prompt_enhancer.infrastructure.text_models.model_ensemble import (
    MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION,
    SerialModelEnsembleRunner,
)
from prompt_enhancer.infrastructure.text_models.probabilistic_metrics import (
    LocalProbabilisticMetricRunner,
)
from prompt_enhancer.interfaces.http.browser_session import CSRF_HEADER
from prompt_enhancer.interfaces.http.requirement_plan_evidence_routes import (
    REQUIREMENT_PLAN_EVIDENCE_MEDIA_TYPE,
)


SESSION_ID = "a" * 64


def _persist_api_session(database: Database) -> None:
    database.persist_session(
        SafeSession(
            provider=Provider.CODEX,
            installation_id="b" * 64,
            project_id="c" * 64,
            session_id=SESSION_ID,
            provider_version="example-provider-1",
            adapter_version="example-adapter-1",
            source_schema_version="example-schema-1",
            started_at=datetime(2040, 1, 1, tzinfo=UTC),
            terminal_state=SessionState.UNKNOWN,
            events_complete=False,
        ),
        (),
    )
WINDOW_ID = "b" * 64
TOKEN = "example_model_ensemble_api_token_1234567890"


def _id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _context(
    *,
    action_state: ActionState = ActionState.COMPLETED,
) -> P1TextAnalysisInput:
    messages = (
        EphemeralRedactedMessage(
            message_id=_id("fictional-request"),
            sequence=0,
            role=TextRole.USER,
            kind=TextMessageKind.REQUEST,
            language=TextLanguage.ENGLISH,
            text=SecretStr(
                "Build a fictional loopback dashboard with explicit tests and boundaries."
            ),
        ),
        EphemeralRedactedMessage(
            message_id=_id("fictional-response"),
            sequence=1,
            role=TextRole.AGENT,
            kind=TextMessageKind.RESPONSE,
            language=TextLanguage.ENGLISH,
            text=SecretStr(
                "Implemented the fictional dashboard and ran the synthetic checks."
            ),
        ),
    )
    return P1TextAnalysisInput(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        provider_version="example-provider-v1",
        adapter_version="example-adapter-v1",
        source_schema_version="example-source-v1",
        content_schema_version="example-content-v1",
        redactor_version="example-redactor-v1",
        text_extraction_complete=True,
        available_message_kinds=frozenset(
            {TextMessageKind.REQUEST, TextMessageKind.RESPONSE}
        ),
        analysis_window_fingerprint=WINDOW_ID,
        focus_message_id=messages[0].message_id,
        observed_message_count=2,
        eligible_message_count=2,
        messages=messages,
        task_profile=COACHING_PROFILE_V1.task_profile,
        action_descriptor_algorithm_version=(
            ACTION_REVIEW_DESCRIPTOR_ALGORITHM_VERSION
        ),
        action_descriptor_extraction_complete=True,
        action_descriptors=(
            EphemeralRedactedActionDescriptor(
                source_reference_id=_id("r7-safe-event"),
                event_kind=EventKind.TOOL_END,
                candidate_metadata_fingerprint_version=(
                    ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION
                ),
                candidate_metadata_fingerprint=(
                    requirement_action_candidate_metadata_fingerprint(
                        source_reference_id=_id("r7-safe-event"),
                        sequence=4,
                        event_kind=EventKind.TOOL_END,
                        tool_category=ToolCategory.FILE_WRITE,
                        occurred_at=R7_NOW - timedelta(seconds=2),
                        duration_ms=50,
                        family=ActionFamily.FILE_CHANGE,
                        state=action_state,
                    )
                ),
                tool_name=SecretStr("example-write-tool"),
                invocation_preview=SecretStr(
                    '{"target":"example-output.txt"}'
                ),
                result_or_effect_preview=SecretStr(
                    '{"status":"example-written"}'
                ),
                invocation_truncated=False,
                result_or_effect_truncated=False,
                redactor_version="example-redactor-v1",
            ),
        ),
    )


def _context_with_candidate_metadata_override(
    *,
    include_receipt: bool = True,
    sequence: int = 4,
    tool_category: ToolCategory | None = ToolCategory.FILE_WRITE,
    occurred_at: datetime | None = None,
    duration_ms: int | None = 50,
    family: ActionFamily = ActionFamily.FILE_CHANGE,
    state: ActionState = ActionState.COMPLETED,
) -> P1TextAnalysisInput:
    context = _context()
    descriptor = context.action_descriptors[0]
    if include_receipt:
        metadata_fingerprint = requirement_action_candidate_metadata_fingerprint(
            source_reference_id=descriptor.source_reference_id,
            sequence=sequence,
            event_kind=descriptor.event_kind,
            tool_category=tool_category,
            occurred_at=(
                R7_NOW - timedelta(seconds=2)
                if occurred_at is None
                else occurred_at
            ),
            duration_ms=duration_ms,
            family=family,
            state=state,
        )
        version = ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION
    else:
        metadata_fingerprint = None
        version = None
    return context.model_copy(
        update={
            "action_descriptors": (
                descriptor.model_copy(
                    update={
                        "candidate_metadata_fingerprint_version": version,
                        "candidate_metadata_fingerprint": metadata_fingerprint,
                    }
                ),
            )
        }
    )


class _Policy:
    consent = True

    def has_active_consent(self, provider: Provider, tier: DataTier) -> bool:
        return self.consent and provider is Provider.CODEX and tier is DataTier.REDACTED_CONTENT

    def selection_is_indexed(
        self,
        provider: Provider,
        *,
        project_ids: frozenset[str],
        session_ids: frozenset[str],
    ) -> bool:
        return provider is Provider.CODEX and not project_ids and session_ids == {SESSION_ID}


class _Compatibility:
    def require_compatible(self, provider: str) -> object:
        if provider != "codex":
            raise ValueError("unsupported")
        return object()


class _Identifiers:
    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str:
        return _id("\x1f".join((namespace, *values)))

    def fingerprint_secret(
        self,
        namespace: str,
        values: tuple[str, ...],
        secret: SecretStr,
    ) -> str:
        return _id(
            "\x1f".join((namespace, *values, secret.get_secret_value()))
        )


class _Source:
    provider = Provider.CODEX
    purpose = TextAnalysisPurpose.TEXT_ANALYSIS
    read_only = True
    requires_explicit_selection = True

    def __init__(self) -> None:
        self.read_count = 0
        self.message_limits: list[int] = []
        self.action_state = ActionState.COMPLETED
        self.context_override: P1TextAnalysisInput | None = None

    def read(self, *, selection, grant, task_profile):
        self.read_count += 1
        self.message_limits.append(selection.max_messages)
        assert selection.session_id == SESSION_ID
        assert 1 <= selection.max_messages <= 100
        assert selection.max_characters == 100_000
        assert grant.local_only and not grant.content_persistence_allowed
        assert task_profile == COACHING_PROFILE_V1.task_profile
        if self.context_override is not None:
            return self.context_override
        return _context(action_state=self.action_state)


class _Repository:
    def __init__(self) -> None:
        self.items: dict[str, SessionModelEnsembleRunRecord] = {}
        self.semantic_units = {}

    def save_completed(self, run: SessionModelEnsembleRunRecord, **_values) -> None:  # type: ignore[no-untyped-def]
        if run.run_id in self.items:
            raise ValueError("duplicate")
        self.items[run.run_id] = run
        if _values.get("semantic_units") is not None:
            self.semantic_units[run.run_id] = _values["semantic_units"]

    def get(self, run_id: str):
        return self.items.get(run_id)

    def get_latest(self, session_id: str):
        rows = [value for value in self.items.values() if value.session_id == session_id]
        return max(rows, key=lambda item: item.receipt.completed_at) if rows else None

    def save_metric_projection(self, run: SessionModelEnsembleRunRecord, **_values) -> None:  # type: ignore[no-untyped-def]
        if run.run_id not in self.items:
            raise ValueError("missing")
        self.items[run.run_id] = run

    def get_semantic_unit_reconciliation(self, run_id: str):  # type: ignore[no-untyped-def]
        return self.semantic_units.get(run_id)

    def delete_for_privacy(self, run_id: str) -> bool:
        return self.items.pop(run_id, None) is not None


class _WatchRepository:
    def __init__(self) -> None:
        self.record: ModelEnsembleWatchRecord | None = None

    def enable(self, *, watch_id, provider, project_id, session_id, max_messages=100, now):  # type: ignore[no-untyped-def]
        self.record = ModelEnsembleWatchRecord(
            watch_id=watch_id,
            provider=provider,
            project_id=project_id,
            session_id=session_id,
            max_messages=max_messages,
            state=ModelEnsembleWatchState.QUEUED,
            generation=0,
            progress_completed=0,
            progress_total=MODEL_ENSEMBLE_WATCH_PROGRESS_TOTAL,
            next_check_at=now,
            created_at=now,
            updated_at=now,
        )
        return self.record

    def disable(self, watch_id, *, now):  # type: ignore[no-untyped-def]
        if self.record is None or self.record.watch_id != watch_id:
            raise ValueError("missing")
        self.record = self.record.model_copy(
            update={"state": ModelEnsembleWatchState.DISABLED, "updated_at": now}
        )
        return self.record

    def get(self, watch_id):  # type: ignore[no-untyped-def]
        return self.record if self.record is not None and self.record.watch_id == watch_id else None

    def get_active(self):  # type: ignore[no-untyped-def]
        if self.record is None or self.record.state is ModelEnsembleWatchState.DISABLED:
            return None
        return self.record

    def get_for_session(self, session_id):  # type: ignore[no-untyped-def]
        if self.record is None or self.record.session_id != session_id:
            return None
        return self.record

    def canonical_head(self, watch_id):  # type: ignore[no-untyped-def]
        if self.record is None or self.record.watch_id != watch_id:
            raise ValueError("missing")
        return ModelEnsembleCanonicalHead(
            watch=self.record,
            head_run_id=self.record.latest_run_id,
            head_generation=(
                None if self.record.latest_run_id is None else self.record.generation
            ),
        )

    def get_attempt(self, attempt_id):  # type: ignore[no-untyped-def]
        return None

    def get_attempt_stages(self, attempt_id):  # type: ignore[no-untyped-def]
        return ()

    def get_attempt_snapshot(self, attempt_id):  # type: ignore[no-untyped-def]
        return None

    def list_attempts(self, watch_id, *, limit):  # type: ignore[no-untyped-def]
        assert self.record is not None and self.record.watch_id == watch_id
        assert 1 <= limit <= 60
        return ()

    def request_refresh(self, watch_id, *, now):  # type: ignore[no-untyped-def]
        if (
            self.record is None
            or self.record.watch_id != watch_id
            or self.record.state is ModelEnsembleWatchState.DISABLED
        ):
            raise ValueError("missing")
        self.record = self.record.model_copy(
            update={"next_check_at": now, "updated_at": now}
        )
        return self.record

    def list_publications(self, watch_id, *, before_generation, limit):  # type: ignore[no-untyped-def]
        if self.record is None or self.record.watch_id != watch_id:
            raise ValueError("missing")
        assert before_generation is None
        assert 1 <= limit <= 60
        return ModelEnsembleTrajectoryPage(
            watch_id=watch_id,
            head_run_id=None,
            head_generation=None,
            points=(),
            next_before_generation=None,
        )

    def claim_due(self, **_values):  # type: ignore[no-untyped-def]
        if self.record is None or self.record.state not in {
            ModelEnsembleWatchState.QUEUED,
            ModelEnsembleWatchState.IDLE,
            ModelEnsembleWatchState.FAILED,
        }:
            return None
        now = _values["now"]
        duration = _values["lease_duration"]
        lease = ModelEnsembleWatchLease(
            watch_id=self.record.watch_id,
            owner=_values["owner"],
            token="e" * 64,
            expires_at=now + duration,
        )
        self.record = self.record.model_copy(
            update={
                "state": ModelEnsembleWatchState.RUNNING,
                "generation": self.record.generation + 1,
                "progress_completed": 0,
                "lease_owner": lease.owner,
                "lease_token": lease.token,
                "lease_expires_at": lease.expires_at,
                "updated_at": now,
            }
        )
        return self.record, lease

    def heartbeat(self, lease: ModelEnsembleWatchLease, **_values):  # type: ignore[no-untyped-def]
        assert self.record is not None and self.record.lease_token == lease.token
        expires_at = _values["now"] + _values["lease_duration"]
        renewed = lease.model_copy(update={"expires_at": expires_at})
        self.record = self.record.model_copy(
            update={
                "progress_completed": _values["progress_completed"],
                "lease_expires_at": expires_at,
                "updated_at": _values["now"],
            }
        )
        return self.record, renewed

    def complete(self, lease: ModelEnsembleWatchLease, **_values):  # type: ignore[no-untyped-def]
        assert self.record is not None and self.record.lease_token == lease.token
        run = _values["outcome"].run
        self.record = self.record.model_copy(
            update={
                "state": ModelEnsembleWatchState.IDLE,
                "progress_completed": MODEL_ENSEMBLE_WATCH_PROGRESS_TOTAL,
                "latest_run_id": run.run_id,
                "latest_input_fingerprint": run.input_fingerprint,
                "last_error_code": None,
                "next_check_at": _values["next_check_at"],
                "lease_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
                "updated_at": _values["now"],
            }
        )
        return self.record

    def fail(self, lease: ModelEnsembleWatchLease, **_values):  # type: ignore[no-untyped-def]
        raise AssertionError("not used")


def _execute(spec, stage, payload, device):  # type: ignore[no-untyped-def]
    rows = []
    for case in payload["cases"]:
        if stage in {"retrieval", "reranking"}:
            rows.append(
                {
                    "case_id": case["case_id"],
                    "scores": [
                        {"fragment_id": fragment_id, "score": 1.0 / (index + 1)}
                        for index, fragment_id in enumerate(case["candidate_ids"])
                    ],
                }
            )
        elif stage == ModelExpertRole.SCOPE_NLI.value:
            rows.append(
                {
                    "case_id": case["case_id"],
                    "entailment": 0.9,
                    "neutral": 0.05,
                    "contradiction": 0.05,
                }
            )
        else:
            rows.append({"case_id": case["case_id"], "label": "present"})
    return {
        "schema_version": MODEL_ENSEMBLE_RUNNER_SCHEMA_VERSION,
        "model_key": spec.identity.model_key,
        "status": "completed",
        "error_code": None,
        "device": "cpu",
        "rows": rows,
        "runtime": {
            "inference_latency_ms": 1.0,
            "peak_cuda_allocated_mb": 0.0,
            "process_rss_after_load_and_inference_mb": 100.0,
        },
    }


def _service(
    policy: _Policy | None = None,
    *,
    with_semantic_units: bool = False,
):
    source = _Source()
    repository = _Repository()
    service = SessionModelEnsembleService(
        policy or _Policy(),
        repository,
        lambda provider: source,
        _Compatibility(),
        _Identifiers(),
        SerialModelEnsembleRunner(executor=_execute, device="cpu"),
        semantic_unit_reconciler=(
            SemanticUnitReconciler(_Identifiers())
            if with_semantic_units
            else None
        ),
    )
    return service, source, repository


def test_service_seals_ten_compatibility_slots_once_and_stores_no_text() -> None:
    service, source, repository = _service()
    request = {
        "provider": Provider.CODEX,
        "session_id": SESSION_ID,
        "confirmation": MODEL_ENSEMBLE_CONFIRMATION,
        "idempotency_key": "example-model-ensemble-0001",
    }

    first = service.run(**request)
    second = service.run(**request)

    assert first.applied is True
    assert second.applied is False
    assert source.read_count == 1
    assert len(first.run.receipt.experts) == MODEL_ENSEMBLE_MODEL_COUNT
    assert len(first.run.receipt.metrics) == 20
    assert len(first.run.receipt.typed_metrics) == 20
    assert first.run.receipt.metric_publication_v2 is not None
    assert first.run.receipt.metric_publication_v2.canonical_live_snapshot is True
    assert first.run.receipt.metric_publication_v2.compatibility_preview is False
    assert first.run.receipt.metric_publication_v2.model_stage_consumed is False
    assert len(first.run.receipt.metric_publication_v2.metrics) == 20
    assert first.run.receipt.metric_projection_version == "coaching-typed-projection-v1"
    assert sum(
        item.value_state.value == "known"
        for item in first.run.receipt.typed_metrics
    ) >= 1
    typed_by_key = {
        item.metric_key: item for item in first.run.receipt.typed_metrics
    }
    assert all(
        typed_by_key[key].value_state.value == "unknown"
        for key in (
            "logic.hypothesis_test_linkage",
            "logic.requirement_action_traceability",
            "outcome.agent_claim_grounding",
            "outcome.first_pass_verification",
            "outcome.verified_requirement_coverage",
        )
    )
    assert len(first.run.receipt.model_votes) == first.run.receipt.chunk_count * 20 * 4
    assert all(item.unloaded_after_stage for item in first.run.receipt.experts)
    assert repository.get(first.run.run_id) is not None
    serialized = first.model_dump_json()
    assert "fictional" not in serialized.lower()
    assert '"content_persisted":false' in serialized
    assert '"product_metric_eligible":false' in serialized


def test_service_atomically_persists_content_free_semantic_unit_heads() -> None:
    service, _source, repository = _service(with_semantic_units=True)

    outcome = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="example-semantic-unit-run-0001",
    )

    reconciliation = repository.get_semantic_unit_reconciliation(
        outcome.run.run_id
    )
    assert reconciliation is not None
    assert reconciliation.session_id == SESSION_ID
    assert len(reconciliation.heads) == 1
    assert reconciliation.heads[0].kind.value == "request_revision"
    serialized = reconciliation.model_dump_json()
    assert "fictional" not in serialized.lower()

    publication = outcome.run.receipt.metric_publication_v2
    assert publication is not None
    states = {item.state.metric_key: item.state for item in publication.metrics}
    assert (publication.known_count, publication.not_applicable_count) == (3, 1)
    assert states["prompt.task_definition_coverage"].value_state.value == "known"
    assert states["outcome.verification_strategy_adequacy"].value_state.value == "known"
    assert states["collaboration.rework_candidate_rate"].value_state.value == "unknown"
    assert states["collaboration.rework_candidate_rate"].explanation_code == (
        "confirmed_lifecycle_service_unavailable"
    )
    assert states["collaboration.ambiguity_resolution"].value_state.value == "unknown"
    assert states["collaboration.ambiguity_resolution"].numeric_value is None
    assert states["collaboration.ambiguity_resolution"].explanation_code == (
        "confirmed_lifecycle_service_unavailable"
    )


def test_typed_provider_verification_updates_only_the_measured_evidence_lane() -> None:
    class _EvidenceProjector:
        descriptor = DecoderDescriptor(
            provider=ProviderIdentity(key="codex"),
            surface=ProviderSurface.OPERATIONAL_EVENTS,
            adapter_version="example-adapter-v1",
            decoder_key="example-events",
            decoder_version="1",
            wire_schema_family="example-events-v1",
            canonical_schema_version="example-source-v1",
            schema_artifact=SchemaArtifactProvenance(
                artifact_key="example-events",
                artifact_version="1",
                kind=SchemaArtifactKind.SYNTHETIC,
            ),
            capabilities=(
                CapabilityKey.VERIFICATION_EVENTS,
                CapabilityKey.VERIFICATION_TASK_OPPORTUNITIES,
                CapabilityKey.VERIFICATION_TASK_EVIDENCE_LINKS,
            ),
        )

        def project(self, *, provider, session_id):  # type: ignore[no-untyped-def]
            assert provider is Provider.CODEX and session_id == SESSION_ID
            task_id = _id("typed-verification-task")
            return EphemeralTypedEvidenceProjection(
                session_id=SESSION_ID,
                provenance=TypedEvidenceProvenance(
                    provider=Provider.CODEX,
                    provider_version="example-provider-v1",
                    adapter_version="example-adapter-v1",
                    decoder_key="example-events",
                    decoder_version="1",
                    source_schema_version="example-source-v1",
                    extraction_complete=True,
                ),
                declared_kinds=frozenset({TypedEvidenceKind.VERIFICATION}),
                declared_opportunity_kinds=frozenset(
                    {TypedEvidenceOpportunityKind.VERIFICATION_TASK}
                ),
                eligible_verification_task_reference_ids=(task_id,),
                records=(
                    VerificationEvidence(
                        evidence_id=_id("typed-verification"),
                        sequence=0,
                        source_reference_id=_id("typed-source"),
                        method=VerificationMethod.TEST,
                        outcome=VerificationOutcome.PASSED,
                        receipt_reference_ids=(_id("typed-receipt"),),
                        verification_task_reference_ids=(task_id,),
                    ),
                ),
            )

    source = _Source()
    repository = _Repository()
    service = SessionModelEnsembleService(
        _Policy(),
        repository,
        lambda provider: source,
        _Compatibility(),
        _Identifiers(),
        LocalProbabilisticMetricRunner(
            executor=_execute,
            device="cpu",
            deep_enabled=False,
        ),
        typed_evidence_projector=_EvidenceProjector(),
    )

    outcome = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="example-objective-evidence-0001",
    )
    measured = next(
        item
        for item in outcome.run.receipt.typed_metrics
        if item.metric_key == "outcome.first_pass_verification"
    )
    predicted = next(
        item
        for item in outcome.run.receipt.predictive_projection.metrics
        if item.metric_key == "outcome.first_pass_verification"
    )
    publication = outcome.run.receipt.metric_publication_v2
    assert publication is not None
    published = next(
        item
        for item in publication.metrics
        if item.state.metric_key == "outcome.first_pass_verification"
    )
    assert (measured.value_state.value, measured.numerator, measured.denominator) == (
        "known",
        1,
        1,
    )
    assert measured.explanation_code == "typed_first_verification_outcomes"
    assert measured.algorithm_id == "typed-objective-evidence"
    assert measured.engine_version == "typed-objective-evidence-v2"
    assert measured.observed_message_count == measured.eligible_message_count == 1
    assert measured.coverage == 1.0
    assert predicted.state.value == "unavailable"
    assert published.state.value_state.value == "known"
    assert (published.state.numerator, published.state.denominator) == (1, 1)
    assert published.state.evidence_authority.value == "objective_receipt"
    assert publication.objective_measured_count == 1
    assert predicted.mean is None and predicted.density_bins == ()


def test_service_withholds_a_rubric_scored_on_an_unowned_focus_turn() -> None:
    """The live service seam must not publish a borrowed-ownership rubric."""

    base = _context()
    feedback = EphemeralRedactedMessage(
        message_id=_id("fictional-feedback"),
        sequence=2,
        role=TextRole.USER,
        kind=TextMessageKind.FEEDBACK,
        language=TextLanguage.ENGLISH,
        text=SecretStr("A neutral fictional remark about the dashboard."),
    )
    messages = (*base.messages, feedback)
    focused = base.model_copy(
        update={
            "messages": messages,
            "focus_message_id": feedback.message_id,
            "available_message_kinds": frozenset(item.kind for item in messages),
            "observed_message_count": len(messages),
            "eligible_message_count": len(messages),
        }
    )

    class _FeedbackFocusSource(_Source):
        def read(self, *, selection, grant, task_profile):  # type: ignore[no-untyped-def]
            super().read(selection=selection, grant=grant, task_profile=task_profile)
            return focused

    service = SessionModelEnsembleService(
        _Policy(),
        _Repository(),
        lambda provider: _FeedbackFocusSource(),
        _Compatibility(),
        _Identifiers(),
        LocalProbabilisticMetricRunner(
            executor=_execute,
            device="cpu",
            deep_enabled=False,
        ),
        semantic_unit_reconciler=SemanticUnitReconciler(_Identifiers()),
    )

    outcome = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="example-unowned-focus-rubric-01",
    )

    publication = outcome.run.receipt.metric_publication_v2
    assert publication is not None
    states = {item.state.metric_key: item.state for item in publication.metrics}
    for metric_key in (
        "prompt.task_definition_coverage",
        "prompt.problem_evidence_quality",
        "prompt.context_sufficiency",
    ):
        assert states[metric_key].value_state.value == "unknown"
        assert states[metric_key].numeric_value is None
        assert states[metric_key].statistics.met_count == 0
        assert (
            states[metric_key].explanation_code
            == "rubric_opportunity_not_focus_owned"
        )


def test_undeclared_opportunity_authority_keeps_the_evidence_lane_unknown() -> None:
    """The same typed graph, from a decoder that never declared the denominator.

    Losing the objective authority must withhold the value, not fail the run
    and not fall back to the conversational lane.
    """

    class _EvidenceProjector:
        descriptor = DecoderDescriptor(
            provider=ProviderIdentity(key="codex"),
            surface=ProviderSurface.OPERATIONAL_EVENTS,
            adapter_version="example-adapter-v1",
            decoder_key="example-events",
            decoder_version="1",
            wire_schema_family="example-events-v1",
            canonical_schema_version="example-source-v1",
            schema_artifact=SchemaArtifactProvenance(
                artifact_key="example-events",
                artifact_version="1",
                kind=SchemaArtifactKind.SYNTHETIC,
            ),
            capabilities=(CapabilityKey.VERIFICATION_EVENTS,),
        )

        def project(self, *, provider, session_id):  # type: ignore[no-untyped-def]
            task_id = _id("typed-verification-task")
            return EphemeralTypedEvidenceProjection(
                session_id=SESSION_ID,
                provenance=TypedEvidenceProvenance(
                    provider=Provider.CODEX,
                    provider_version="example-provider-v1",
                    adapter_version="example-adapter-v1",
                    decoder_key="example-events",
                    decoder_version="1",
                    source_schema_version="example-source-v1",
                    extraction_complete=True,
                ),
                declared_kinds=frozenset({TypedEvidenceKind.VERIFICATION}),
                declared_opportunity_kinds=frozenset(
                    {TypedEvidenceOpportunityKind.VERIFICATION_TASK}
                ),
                eligible_verification_task_reference_ids=(task_id,),
                records=(
                    VerificationEvidence(
                        evidence_id=_id("typed-verification"),
                        sequence=0,
                        source_reference_id=_id("typed-source"),
                        method=VerificationMethod.TEST,
                        outcome=VerificationOutcome.PASSED,
                        receipt_reference_ids=(_id("typed-receipt"),),
                        verification_task_reference_ids=(task_id,),
                    ),
                ),
            )

    service = SessionModelEnsembleService(
        _Policy(),
        _Repository(),
        lambda provider: _Source(),
        _Compatibility(),
        _Identifiers(),
        LocalProbabilisticMetricRunner(
            executor=_execute,
            device="cpu",
            deep_enabled=False,
        ),
        typed_evidence_projector=_EvidenceProjector(),
    )

    outcome = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="example-unauthorized-evidence-01",
    )

    publication = outcome.run.receipt.metric_publication_v2
    assert publication is not None
    published = next(
        item
        for item in publication.metrics
        if item.state.metric_key == "outcome.first_pass_verification"
    )
    assert published.state.value_state.value == "unknown"
    assert published.state.numeric_value is None
    assert publication.objective_measured_count == 0


def test_denominator_authority_without_outcome_capability_stays_unknown() -> None:
    """An adapter unable to observe outcomes must not publish a synthetic 0/N."""

    class _EvidenceProjector:
        descriptor = DecoderDescriptor(
            provider=ProviderIdentity(key="codex"),
            surface=ProviderSurface.OPERATIONAL_EVENTS,
            adapter_version="example-adapter-v1",
            decoder_key="example-events",
            decoder_version="1",
            wire_schema_family="example-events-v1",
            canonical_schema_version="example-source-v1",
            schema_artifact=SchemaArtifactProvenance(
                artifact_key="example-events",
                artifact_version="1",
                kind=SchemaArtifactKind.SYNTHETIC,
            ),
            capabilities=(
                CapabilityKey.VERIFICATION_TASK_OPPORTUNITIES,
                CapabilityKey.VERIFICATION_TASK_EVIDENCE_LINKS,
            ),
        )

        def project(self, *, provider, session_id):  # type: ignore[no-untyped-def]
            assert provider is Provider.CODEX and session_id == SESSION_ID
            return EphemeralTypedEvidenceProjection(
                session_id=SESSION_ID,
                provenance=TypedEvidenceProvenance(
                    provider=Provider.CODEX,
                    provider_version="example-provider-v1",
                    adapter_version="example-adapter-v1",
                    decoder_key="example-events",
                    decoder_version="1",
                    source_schema_version="example-source-v1",
                    extraction_complete=True,
                ),
                declared_kinds=frozenset(),
                declared_opportunity_kinds=frozenset(
                    {TypedEvidenceOpportunityKind.VERIFICATION_TASK}
                ),
                eligible_verification_task_reference_ids=(
                    _id("unobservable-verification-task"),
                ),
                records=(),
            )

    service = SessionModelEnsembleService(
        _Policy(),
        _Repository(),
        lambda provider: _Source(),
        _Compatibility(),
        _Identifiers(),
        LocalProbabilisticMetricRunner(
            executor=_execute,
            device="cpu",
            deep_enabled=False,
        ),
        typed_evidence_projector=_EvidenceProjector(),
    )

    outcome = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="example-missing-outcome-capability-01",
    )
    publication = outcome.run.receipt.metric_publication_v2
    assert publication is not None
    published = next(
        item
        for item in publication.metrics
        if item.state.metric_key == "outcome.first_pass_verification"
    )
    assert published.state.value_state.value == "unknown"
    assert published.state.numeric_value is None
    assert published.state.statistics.capability_available is False
    assert published.state.explanation_code == (
        "typed_verification_outcome_capability_missing"
    )
    assert publication.objective_measured_count == 0


def test_unchanged_legacy_head_gets_a_new_revision_bound_r8_run() -> None:
    service, source, repository = _service()
    first = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="example-model-ensemble-legacy-0001",
    )
    legacy_receipt = first.run.receipt.model_copy(
        update={
            "metric_projection_version": None,
            "metric_projection_completed_at": None,
            "typed_metrics": (),
        }
    )
    repository.items[first.run.run_id] = first.run.model_copy(
        update={"receipt": legacy_receipt}
    )

    upgraded = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="example-model-ensemble-legacy-0002",
        reuse_latest=True,
        prior_run_id=first.run.run_id,
    )

    assert upgraded.applied is True
    assert upgraded.run.run_id != first.run.run_id
    assert len(upgraded.run.receipt.typed_metrics) == 20
    assert upgraded.run.requirement_verification_evidence_binding is not None
    assert source.read_count == 2


@pytest.mark.parametrize(
    "confirmation",
    (MODEL_ENSEMBLE_CONFIRMATION, LEGACY_MODEL_ENSEMBLE_CONFIRMATION),
)
def test_current_cascade_confirmation_preserves_legacy_request_compatibility(
    confirmation: str,
) -> None:
    service, source, _ = _service()

    outcome = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=confirmation,
        idempotency_key="example-confirmation-compat-0001",
    )

    assert outcome.applied is True
    assert source.read_count == 1


def test_unknown_cascade_confirmation_fails_before_source_access() -> None:
    service, source, _ = _service()

    with pytest.raises(ModelEnsembleConfirmationError):
        service.run(
            provider=Provider.CODEX,
            session_id=SESSION_ID,
            confirmation="run_unspecified_remote_models",
            idempotency_key="example-confirmation-invalid-0001",
        )

    assert source.read_count == 0


def test_consent_fails_before_the_local_source_or_models() -> None:
    policy = _Policy()
    policy.consent = False
    service, source, repository = _service(policy)

    with pytest.raises(ModelEnsembleConsentError):
        service.run(
            provider=Provider.CODEX,
            session_id=SESSION_ID,
            confirmation=MODEL_ENSEMBLE_CONFIRMATION,
            idempotency_key="example-model-ensemble-0002",
        )

    assert source.read_count == 0
    assert repository.items == {}


def test_private_api_returns_only_content_free_shadow_receipts(tmp_path) -> None:
    service, source, _ = _service()
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    _persist_api_session(database)
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        session_model_ensemble_service=service,
    )
    path = f"/v1/sessions/{SESSION_ID}/model-ensemble-runs"
    headers = {
        API_TOKEN_HEADER: TOKEN,
        "Idempotency-Key": "example-model-ensemble-0003",
    }

    with TestClient(app, base_url="http://127.0.0.1") as client:
        unauthorized = client.post(
            path,
            json={"confirmation": MODEL_ENSEMBLE_CONFIRMATION},
            headers={"Idempotency-Key": "example-model-ensemble-0003"},
        )
        rejected = client.post(
            path,
            json={
                "confirmation": MODEL_ENSEMBLE_CONFIRMATION,
                "transcript": "SYNTHETIC_PRIVATE_CANARY",
            },
            headers=headers,
        )
        response = client.post(
            path,
            json={"confirmation": MODEL_ENSEMBLE_CONFIRMATION},
            headers=headers,
        )
        latest = client.get(f"{path}/latest", headers={API_TOKEN_HEADER: TOKEN})

    assert unauthorized.status_code == 401
    assert rejected.status_code == 422
    assert rejected.json() == {"detail": "request validation failed"}
    assert response.status_code == latest.status_code == 200
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["pragma"] == "no-cache"
    payload = response.json()["run"]
    assert payload["model_count"] == 10
    assert len(payload["experts"]) == 10
    assert payload["metric_publication_v2"]["source"] == "live_projection"
    assert payload["metric_publication_v2"]["canonical_live_snapshot"] is True
    assert payload["metric_publication_v2"]["compatibility_preview"] is False
    assert len(payload["metric_publication_v2"]["metrics"]) == 20
    assert payload["metric_profile_binding"] == {
        "profile_source": "coaching_profile_v1_unconfigured",
        "profile_id": None,
        "profile_revision": None,
        "profile_fingerprint": (
            "4cf952d189fd817c3959540a18538b76b161aa3a03d810cb967cafc7f284be71"
        ),
        "profile_schema_version": "coaching-profile-v1-unconfigured",
        "profile_policy_version": "server-preset-v1",
        "local_only": True,
        "content_persisted": False,
    }
    assert payload["content_persisted"] is False
    assert payload["product_metric_eligible"] is False
    assert "source_window_fingerprint" not in response.text
    assert "fragment_id" not in response.text
    assert "SYNTHETIC_PRIVATE_CANARY" not in response.text
    assert source.read_count == 1


def test_private_watch_api_enables_without_reading_and_can_be_disabled(tmp_path) -> None:
    ensemble, source, _ = _service()
    watch_repository = _WatchRepository()
    watch = ModelEnsembleWatchService(
        watch_repository,
        ensemble,
        clock=lambda: datetime(2040, 1, 2, 3, 4, tzinfo=UTC),
        poll_interval=timedelta(seconds=60),
    )
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    _persist_api_session(database)
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        session_model_ensemble_service=ensemble,
        model_ensemble_watch_service=watch,
    )
    headers = {API_TOKEN_HEADER: TOKEN}
    path = f"/v1/sessions/{SESSION_ID}/model-ensemble-watch"

    with TestClient(app, base_url="http://127.0.0.1") as client:
        missing_session_head = client.get(
            f"/v2/sessions/{SESSION_ID}/model-ensemble-head", headers=headers
        )
        unauthorized = client.put(
            path,
            json={
                "project_id": "c" * 64,
                "max_messages": 25,
                "confirmation": MODEL_ENSEMBLE_WATCH_CONFIRMATION,
            },
        )
        rejected = client.put(
            path,
            headers=headers,
            json={
                "project_id": "c" * 64,
                "confirmation": MODEL_ENSEMBLE_WATCH_CONFIRMATION,
                "transcript": "SYNTHETIC_PRIVATE_CANARY",
            },
        )
        enabled = client.put(
            path,
            headers=headers,
            json={
                "project_id": "c" * 64,
                "max_messages": 25,
                "confirmation": MODEL_ENSEMBLE_WATCH_CONFIRMATION,
            },
        )
        active = client.get("/v1/model-ensemble-watch/active", headers=headers)
        watch_id = enabled.json()["watch"]["watch_id"]
        canonical = client.get(
            "/v2/model-ensemble-watch/active/head", headers=headers
        )
        session_canonical = client.get(
            f"/v2/sessions/{SESSION_ID}/model-ensemble-head", headers=headers
        )
        attempts = client.get(
            f"/v2/model-ensemble-watches/{watch_id}/attempts", headers=headers
        )
        trajectory = client.get(
            f"/v1/model-ensemble-watches/{watch_id}/trajectory?limit=12",
            headers=headers,
        )
        refreshed = client.post(
            f"/v1/model-ensemble-watches/{watch_id}/refresh",
            headers=headers,
        )
        disabled = client.delete(
            f"/v1/model-ensemble-watches/{watch_id}", headers=headers
        )

    assert unauthorized.status_code == 401
    assert missing_session_head.status_code == 404
    assert missing_session_head.headers["cache-control"] == "no-store, private"
    assert missing_session_head.headers["pragma"] == "no-cache"
    assert rejected.status_code == 422
    assert rejected.json() == {"detail": "request validation failed"}
    assert (
        enabled.status_code
        == active.status_code
        == trajectory.status_code
        == refreshed.status_code
        == disabled.status_code
        == canonical.status_code
        == session_canonical.status_code
        == attempts.status_code
        == 200
    )
    assert enabled.headers["cache-control"] == "no-store, private"
    assert enabled.headers["pragma"] == "no-cache"
    assert enabled.json()["watch"]["state"] == "queued"
    assert enabled.json()["watch"]["max_messages"] == 25
    assert enabled.json()["latest_run"] is None
    assert active.json() == enabled.json()
    assert canonical.json()["schema_version"] == "analysis-snapshot-v2"
    assert canonical.json()["head_run_id"] is None
    assert canonical.json()["latest_attempt"] is None
    assert session_canonical.json() == canonical.json()
    assert session_canonical.headers["cache-control"] == "no-store, private"
    assert session_canonical.headers["pragma"] == "no-cache"
    assert attempts.json()["attempts"] == []
    assert trajectory.headers["cache-control"] == "no-store, private"
    assert trajectory.headers["pragma"] == "no-cache"
    assert refreshed.headers["cache-control"] == "no-store, private"
    assert trajectory.json() == {
        "watch_id": watch_id,
        "head_run_id": None,
        "head_generation": None,
        "points": [],
        "next_before_generation": None,
        "content_persisted": False,
        "calibrated_as_truth": False,
    }
    assert disabled.json()["watch"]["state"] == "disabled"
    assert source.read_count == 0
    assert "SYNTHETIC_PRIVATE_CANARY" not in rejected.text


def test_watch_worker_runs_all_ten_progress_boundaries_and_coalesces_unchanged_input() -> None:
    ensemble, source, repository = _service()
    watch_repository = _WatchRepository()
    watch = ModelEnsembleWatchService(
        watch_repository,
        ensemble,
        clock=lambda: datetime(2040, 1, 2, 3, 4, tzinfo=UTC),
        poll_interval=timedelta(seconds=60),
    )
    enabled = watch.enable(
        provider=Provider.CODEX,
        project_id="c" * 64,
        session_id=SESSION_ID,
        max_messages=25,
        confirmation=MODEL_ENSEMBLE_WATCH_CONFIRMATION,
    )

    first = watch.run_once()
    assert enabled.state is ModelEnsembleWatchState.QUEUED
    assert enabled.max_messages == 25
    assert first is not None and first.state is ModelEnsembleWatchState.IDLE
    assert first.generation == 1
    assert first.progress_completed == 10
    assert first.latest_run_id is not None
    assert source.read_count == 1
    assert source.message_limits == [25]
    assert len(repository.items) == 1

    # Make the same watch due again. The source is read to observe the local
    # snapshot, but an unchanged fingerprint reuses the sealed run and stores
    # no duplicate result graph.
    assert watch_repository.record is not None
    watch_repository.record = watch_repository.record.model_copy(
        update={"next_check_at": datetime(2040, 1, 2, 3, 4, tzinfo=UTC)}
    )
    second = watch.run_once()
    assert second is not None and second.state is ModelEnsembleWatchState.IDLE
    assert second.generation == 2
    assert second.latest_run_id == first.latest_run_id
    assert source.read_count == 2
    assert len(repository.items) == 1


def test_watch_recomputes_unchanged_input_after_the_execution_plan_changes() -> None:
    ensemble, source, repository = _service()
    watch_repository = _WatchRepository()
    watch = ModelEnsembleWatchService(
        watch_repository,
        ensemble,
        clock=lambda: datetime(2040, 1, 2, 3, 4, tzinfo=UTC),
        poll_interval=timedelta(seconds=60),
    )
    watch.enable(
        provider=Provider.CODEX,
        project_id="c" * 64,
        session_id=SESSION_ID,
        max_messages=25,
        confirmation=MODEL_ENSEMBLE_WATCH_CONFIRMATION,
    )
    first = watch.run_once()
    assert first is not None and first.latest_run_id is not None
    prior = repository.items[first.latest_run_id]
    current_plan_fingerprint = prior.receipt.plan_fingerprint

    # Model an immutable receipt created by an older observation policy.  The
    # source window is unchanged, but the current plan must supersede it.
    repository.items[first.latest_run_id] = prior.model_copy(
        update={
            "receipt": prior.receipt.model_copy(
                update={"plan_fingerprint": "f" * 64}
            )
        }
    )
    assert watch_repository.record is not None
    watch_repository.record = watch_repository.record.model_copy(
        update={"next_check_at": datetime(2040, 1, 2, 3, 4, tzinfo=UTC)}
    )

    second = watch.run_once()

    assert second is not None and second.latest_run_id is not None
    assert second.latest_run_id != first.latest_run_id
    assert source.read_count == 2
    assert len(repository.items) == 2
    current = repository.items[second.latest_run_id]
    assert current.receipt.plan_fingerprint != "f" * 64
    assert current.receipt.plan_fingerprint == current_plan_fingerprint


def test_watch_api_does_not_substitute_an_unbound_historical_run(tmp_path) -> None:
    ensemble, _, repository = _service()
    watch_repository = _WatchRepository()
    watch = ModelEnsembleWatchService(
        watch_repository,
        ensemble,
        clock=lambda: datetime(2040, 1, 2, 3, 4, tzinfo=UTC),
        poll_interval=timedelta(seconds=60),
    )
    watch.enable(
        provider=Provider.CODEX,
        project_id="c" * 64,
        session_id=SESSION_ID,
        max_messages=25,
        confirmation=MODEL_ENSEMBLE_WATCH_CONFIRMATION,
    )
    completed = watch.run_once()
    assert completed is not None and completed.latest_run_id is not None
    assert repository.get_latest(SESSION_ID) is not None

    # Reconfiguring a watch intentionally clears its bound head.  The API must
    # not replace that absence with an older or manually-created session run.
    watch.enable(
        provider=Provider.CODEX,
        project_id="c" * 64,
        session_id=SESSION_ID,
        max_messages=50,
        confirmation=MODEL_ENSEMBLE_WATCH_CONFIRMATION,
    )
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        session_model_ensemble_service=ensemble,
        model_ensemble_watch_service=watch,
    )

    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get(
            "/v1/model-ensemble-watch/active",
            headers={API_TOKEN_HEADER: TOKEN},
        )
        snapshot = client.get(
            f"/v2/model-ensemble-snapshots/{completed.latest_run_id}",
            headers={API_TOKEN_HEADER: TOKEN},
        )
        unchanged = client.get(
            f"/v2/model-ensemble-snapshots/{completed.latest_run_id}",
            headers={
                API_TOKEN_HEADER: TOKEN,
                "If-None-Match": f'"{completed.latest_run_id}"',
            },
        )
        nonexistent_id = "f" * 64
        nonexistent = client.get(
            f"/v2/model-ensemble-snapshots/{nonexistent_id}",
            headers={
                API_TOKEN_HEADER: TOKEN,
                "If-None-Match": f'"{nonexistent_id}"',
            },
        )

    assert response.status_code == 200
    assert response.json()["watch"]["has_result"] is False
    assert response.json()["latest_run"] is None
    assert snapshot.status_code == 200
    assert snapshot.headers["cache-control"] == "no-store, private"
    assert snapshot.headers["pragma"] == "no-cache"
    assert snapshot.headers["etag"] == f'"{completed.latest_run_id}"'
    assert snapshot.json()["run_id"] == completed.latest_run_id
    assert unchanged.status_code == 304
    assert unchanged.headers["cache-control"] == "no-store, private"
    assert unchanged.headers["pragma"] == "no-cache"
    assert unchanged.content == b""
    assert nonexistent.status_code == 404


@dataclass
class _FailingService:
    error_type: type[ModelEnsembleExecutionError] = ModelEnsembleExecutionError

    def run(self, **values):
        raise self.error_type("SYNTHETIC_PRIVATE_CANARY")

    def latest(self, session_id: str):
        return None


@pytest.mark.parametrize("error_type,code,message", [
    (ModelEnsembleExecutionError, "local_model_ensemble_execution_failed", "local model ensemble execution failed"),
    (ModelEnsembleRuntimeCleanupError, "model_ensemble_cleanup_unconfirmed", "local model cleanup was not confirmed; new model runs are paused"),
], ids=["ordinary-failure", "cleanup-unconfirmed"])
def test_api_discards_model_exception_details(tmp_path, error_type, code, message) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    _persist_api_session(database)
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        session_model_ensemble_service=_FailingService(error_type),  # type: ignore[arg-type]
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.post(
            f"/v1/sessions/{SESSION_ID}/model-ensemble-runs",
            json={"confirmation": MODEL_ENSEMBLE_CONFIRMATION},
            headers={
                API_TOKEN_HEADER: TOKEN,
                "Idempotency-Key": "example-model-ensemble-0004",
            },
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": code,
            "message": message,
        }
    }
    assert "SYNTHETIC_PRIVATE_CANARY" not in response.text


R7_NOW = datetime(2040, 2, 3, 4, 5, tzinfo=UTC)


class _R7PlanReader:
    def __init__(self, snapshot: RequirementPlanEvidenceSnapshot) -> None:
        self.snapshot = snapshot

    def latest_snapshot(self, session_id: str) -> RequirementPlanEvidenceSnapshot:
        assert session_id == SESSION_ID
        return self.snapshot


class _R7ActionReader:
    def __init__(self, snapshot: RequirementActionEvidenceSnapshot) -> None:
        self.snapshot = snapshot

    def latest_snapshot(self, session_id: str) -> RequirementActionEvidenceSnapshot:
        assert session_id == SESSION_ID
        return self.snapshot


class _RequirementActionRecoveryRepository(
    _RequirementActionRecoveryRepositoryBase
):
    def __init__(
        self,
        ids: _Identifiers,
        initial_snapshot: RequirementActionEvidenceSnapshot,
    ) -> None:
        super().__init__(ids)
        assert initial_snapshot.confirmation_id is not None
        self.initial_snapshot = initial_snapshot
        self.heads[
            (
                initial_snapshot.session_id,
                initial_snapshot.source_window_fingerprint,
            )
        ] = initial_snapshot.confirmation_id

    def snapshot(
        self,
        session_id: str,
        source_window_fingerprint: str,
    ) -> RequirementActionEvidenceSnapshot:
        head = self.heads.get((session_id, source_window_fingerprint))
        if head == self.initial_snapshot.confirmation_id:
            return self.initial_snapshot
        return super().snapshot(session_id, source_window_fingerprint)

    def latest_snapshot(
        self,
        session_id: str,
    ) -> RequirementActionEvidenceSnapshot:
        assert session_id == self.initial_snapshot.session_id
        return self.snapshot(
            session_id,
            self.initial_snapshot.source_window_fingerprint,
        )


class _FixedLatestRunRepository:
    def __init__(self, run: SessionModelEnsembleRunRecord) -> None:
        self.run = run

    def get_latest(self, session_id: str) -> SessionModelEnsembleRunRecord:
        assert session_id == self.run.session_id
        return self.run


class _R7ActionProjector:
    descriptor = DecoderDescriptor(
        provider=ProviderIdentity(key="codex"),
        surface=ProviderSurface.OPERATIONAL_EVENTS,
        adapter_version="example-adapter-v1",
        decoder_key="safe-event-evidence",
        decoder_version="4",
        wire_schema_family="example-safe-events-v1",
        canonical_schema_version="example-source-v1",
        schema_artifact=SchemaArtifactProvenance(
            artifact_key="example-safe-events",
            artifact_version="1",
            kind=SchemaArtifactKind.SYNTHETIC,
        ),
        capabilities=(CapabilityKey.TOOL_EVENTS,),
    )

    def __init__(self) -> None:
        self.state = ActionState.COMPLETED
        self.include_extra = False
        self.manifest_count = 0
        self.overflow_from_manifest_call: int | None = None

    @staticmethod
    def _provenance() -> TypedEvidenceProvenance:
        return TypedEvidenceProvenance(
            provider=Provider.CODEX,
            provider_version="example-provider-v1",
            adapter_version="example-adapter-v1",
            decoder_key="safe-event-evidence",
            decoder_version="4",
            source_schema_version="example-source-v1",
            extraction_complete=True,
        )

    def project(self, *, provider, session_id):  # type: ignore[no-untyped-def]
        assert provider is Provider.CODEX and session_id == SESSION_ID
        return EphemeralTypedEvidenceProjection(
            session_id=SESSION_ID,
            provenance=self._provenance(),
            declared_kinds=frozenset({TypedEvidenceKind.ACTION}),
            records=(
                ActionEvidence(
                    evidence_id=_id("r7-action"),
                    sequence=4,
                    source_reference_id=_id("r7-safe-event"),
                    family=ActionFamily.FILE_CHANGE,
                    state=self.state,
                ),
                *(
                    (
                        ActionEvidence(
                            evidence_id=_id("r7-new-action"),
                            sequence=5,
                            source_reference_id=_id("r7-new-safe-event"),
                            family=ActionFamily.COMMAND,
                            state=ActionState.COMPLETED,
                        ),
                    )
                    if self.include_extra
                    else ()
                ),
            ),
        )

    def requirement_action_candidate_manifest(
        self,
        *,
        provider: Provider,
        session_id: str,
        source_run_id: str,
        source_window_fingerprint: str,
        projection: EphemeralTypedEvidenceProjection | None = None,
    ) -> RequirementActionCandidateManifest:
        assert provider is Provider.CODEX and session_id == SESSION_ID
        if projection is not None:
            assert projection.session_id == session_id
        self.manifest_count += 1
        if (
            self.overflow_from_manifest_call is not None
            and self.manifest_count >= self.overflow_from_manifest_call
        ):
            raise RequirementActionCandidateManifestOverflowError(
                "synthetic candidate overflow"
            )
        provisional = RequirementActionCandidateManifest(
            session_id=session_id,
            source_run_id=source_run_id,
            source_window_fingerprint=source_window_fingerprint,
            provenance=self._provenance(),
            extraction_complete=True,
            enumeration_complete=True,
            actions=(
                RequirementActionCandidate(
                    candidate_index=0,
                    action_id=_id("r7-action"),
                    source_reference_id=_id("r7-safe-event"),
                    sequence=4,
                    event_kind=EventKind.TOOL_END,
                    tool_category=ToolCategory.FILE_WRITE,
                    occurred_at=R7_NOW - timedelta(seconds=2),
                    duration_ms=50,
                    family=ActionFamily.FILE_CHANGE,
                    state=self.state,
                ),
                *(
                    (
                        RequirementActionCandidate(
                            candidate_index=1,
                            action_id=_id("r7-new-action"),
                            source_reference_id=_id("r7-new-safe-event"),
                            sequence=5,
                            event_kind=EventKind.TOOL_END,
                            tool_category=ToolCategory.COMMAND,
                            occurred_at=R7_NOW - timedelta(seconds=1),
                            duration_ms=75,
                            family=ActionFamily.COMMAND,
                            state=ActionState.COMPLETED,
                        ),
                    )
                    if self.include_extra
                    else ()
                ),
            ),
            manifest_fingerprint="0" * 64,
        )
        return provisional.model_copy(
            update={
                "manifest_fingerprint": (
                    requirement_action_candidate_manifest_fingerprint(
                        provisional
                    )
                )
            }
        )


def _r7_requirement_plan() -> RequirementPlanEvidenceSnapshot:
    return RequirementPlanEvidenceSnapshot(
        session_id=SESSION_ID,
        source_window_fingerprint=WINDOW_ID,
        confirmation_id=_id("r7-plan-confirmation"),
        proposal_id=_id("r7-plan-proposal"),
        producer_receipt=RequirementPlanProducerReceipt(
            claim_fingerprint=_id("r7-plan-producer")
        ),
        review_rubric_version=REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
        requirements=(
            ConfirmedRequirementEvidence(
                requirement_id=_id("r7-requirement"),
                coordinate=RequirementCoordinate(
                    message_sequence=0,
                    clause_index=0,
                ),
                disposition=RequirementDisposition.NOT_LINKED,
            ),
        ),
        complete_user_clause_classification=True,
    )


def _r7_action_snapshot(
    *,
    plan: RequirementPlanEvidenceSnapshot,
    manifest: RequirementActionCandidateManifest,
    identifiers: _Identifiers,
    label: str,
) -> RequirementActionEvidenceSnapshot:
    requirements = tuple(
        RequirementActionRequirement(
            requirement_index=index,
            requirement_id=item.requirement_id,
            coordinate=item.coordinate,
        )
        for index, item in enumerate(plan.requirements)
    )
    plan_fingerprint = requirement_plan_snapshot_fingerprint(plan, identifiers)
    provisional = RequirementActionEvidenceSnapshot(
        session_id=SESSION_ID,
        source_run_id=manifest.source_run_id,
        source_window_fingerprint=manifest.source_window_fingerprint,
        requirement_plan_confirmation_id=plan.confirmation_id,
        requirement_plan_evidence_fingerprint=plan_fingerprint,
        confirmation_id=_id(f"{label}-confirmation"),
        proposal_id=_id(f"{label}-proposal"),
        reviewed_descriptor_set_fingerprint=_id(f"{label}-descriptors"),
        producer_receipt=RequirementPlanProducerReceipt(
            claim_fingerprint=_id(f"{label}-producer")
        ),
        candidate_manifest=manifest,
        requirements=requirements,
        links=(
            ConfirmedRequirementActionLink(
                requirement_id=requirements[0].requirement_id,
                action_ids=(manifest.actions[0].action_id,),
            ),
        ),
        complete_requirement_enumeration=True,
        complete_action_candidate_enumeration=True,
        complete_requirement_link_classification=True,
        evidence_fingerprint="0" * 64,
    )
    return provisional.model_copy(
        update={
            "evidence_fingerprint": (
                requirement_action_evidence_snapshot_fingerprint(
                    provisional, identifiers
                )
            )
        }
    )


def _r7_metric_state(run: SessionModelEnsembleRunRecord):  # type: ignore[no-untyped-def]
    publication = run.receipt.metric_publication_v2
    assert publication is not None
    return next(
        item.state
        for item in publication.metrics
        if item.state.metric_key == "logic.requirement_action_traceability"
    )


def _r7_candidate_test_service(
    projector: _R7ActionProjector,
    *,
    source: _Source | None = None,
) -> tuple[
    SessionModelEnsembleService,
    _Repository,
    InMemoryRequirementActionReviewContextStore,
]:
    identifiers = _Identifiers()
    repository = _Repository()
    plan = _r7_requirement_plan()
    action_contexts = InMemoryRequirementActionReviewContextStore(
        clock=lambda: R7_NOW,
        monotonic_clock=lambda: 100.0,
        candidate_binding_key=b"r" * 32,
    )
    selected_source = _Source() if source is None else source
    service = SessionModelEnsembleService(
        _Policy(),
        repository,
        lambda provider: selected_source,
        _Compatibility(),
        identifiers,
        LocalProbabilisticMetricRunner(
            executor=_execute,
            device="cpu",
            deep_enabled=False,
        ),
        clock=lambda: R7_NOW,
        typed_evidence_projector=projector,
        semantic_unit_reconciler=SemanticUnitReconciler(identifiers),
        requirement_plan_evidence_reader=_R7PlanReader(plan),
        requirement_action_evidence_reader=_R7ActionReader(
            RequirementActionEvidenceSnapshot(
                session_id=SESSION_ID,
                source_window_fingerprint=WINDOW_ID,
            )
        ),
        requirement_action_review_contexts=action_contexts,
    )
    return service, repository, action_contexts


def test_r8_reviewed_plan_without_verification_reader_is_unavailable() -> None:
    service, repository, _ = _r7_candidate_test_service(_R7ActionProjector())

    result = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="example-r8-no-verification-reader-0001",
    )

    run = result.run
    assert repository.get(run.run_id) == run
    assert run.requirement_plan_evidence_binding is not None
    assert (
        run.requirement_plan_evidence_binding.evidence_source
        is RequirementPlanEvidenceSource.REVIEWED_REQUIREMENT_PLAN
    )
    binding = run.requirement_verification_evidence_binding
    assert binding is not None
    assert (
        binding.evidence_source
        is RequirementVerificationEvidenceSource.UNAVAILABLE
    )
    publication = run.receipt.metric_publication_v2
    assert publication is not None
    assert publication.projection_version == METRIC_PROJECTION_V2_VERSION_8
    state = next(
        metric.state
        for metric in publication.metrics
        if metric.state.metric_key == "outcome.verified_requirement_coverage"
    )
    assert state.value_state.value == "unknown"
    assert state.numeric_value is None
    assert state.explanation_code == "requirement_verification_evidence_unavailable"
    assert state.statistics.eligible_count == 1
    typed = next(
        metric
        for metric in run.receipt.typed_metrics
        if metric.metric_key == "outcome.verified_requirement_coverage"
    )
    assert typed.engine_version == (
        "reviewed-requirement-verification-objective-projection-v1"
    )
    assert typed.algorithm_id == VERIFIED_REQUIREMENT_METRIC_ALGORITHM_ID
    assert typed.algorithm_version == VERIFIED_REQUIREMENT_METRIC_ALGORITHM_VERSION
    assert typed.rubric_version == VERIFIED_REQUIREMENT_METRIC_RUBRIC_VERSION


def test_session_r7_candidate_overflow_is_bound_and_preflight_races_fail_closed() -> None:
    overflow_projector = _R7ActionProjector()
    overflow_projector.overflow_from_manifest_call = 1
    service, repository, action_contexts = _r7_candidate_test_service(
        overflow_projector
    )

    overflow = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="example-r7-overflow-0001",
    )

    binding = overflow.run.requirement_action_evidence_binding
    assert binding is not None
    assert (
        binding.evidence_source
        is RequirementActionEvidenceSource.CANDIDATE_MANIFEST_OVERFLOW
    )
    state = _r7_metric_state(overflow.run)
    assert state.value_state.value == "unknown"
    assert state.explanation_code == "requirement_action_evidence_overflow"
    with pytest.raises(RequirementActionNotFoundError):
        action_contexts.source_contract(
            SESSION_ID,
            overflow.run.run_id,
            METRIC_PROJECTION_V2_VERSION_7,
        )
    assert len(repository.items) == 1

    race_projector = _R7ActionProjector()
    race_projector.overflow_from_manifest_call = 2
    race_service, race_repository, _ = _r7_candidate_test_service(race_projector)
    with pytest.raises(
        ModelEnsemblePersistenceError,
        match="candidate source changed during analysis",
    ):
        race_service.run(
            provider=Provider.CODEX,
            session_id=SESSION_ID,
            confirmation=MODEL_ENSEMBLE_CONFIRMATION,
            idempotency_key="example-r7-overflow-race-0002",
        )
    assert race_repository.items == {}


@pytest.mark.parametrize(
    "drift",
    ("absent", "wrong_hash", "state", "category", "time", "sequence"),
)
def test_session_r7_candidate_metadata_drift_fails_closed_before_publish(
    drift: str,
) -> None:
    source = _Source()
    if drift == "absent":
        context = _context_with_candidate_metadata_override(
            include_receipt=False
        )
    elif drift == "state":
        context = _context_with_candidate_metadata_override(
            state=ActionState.FAILED
        )
    elif drift == "category":
        context = _context_with_candidate_metadata_override(
            tool_category=ToolCategory.COMMAND
        )
    elif drift == "time":
        context = _context_with_candidate_metadata_override(
            occurred_at=R7_NOW - timedelta(seconds=3)
        )
    elif drift == "sequence":
        context = _context_with_candidate_metadata_override(sequence=8)
    else:
        context = _context_with_candidate_metadata_override()
        descriptor = context.action_descriptors[0]
        context = context.model_copy(
            update={
                "action_descriptors": (
                    descriptor.model_copy(
                        update={
                            "candidate_metadata_fingerprint": "f" * 64
                        }
                    ),
                )
            }
        )
    source.context_override = context
    service, repository, action_contexts = _r7_candidate_test_service(
        _R7ActionProjector(),
        source=source,
    )

    outcome = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key=f"example-r7-candidate-metadata-{drift}",
    )

    binding = outcome.run.requirement_action_evidence_binding
    assert binding is not None
    assert (
        binding.evidence_source
        is RequirementActionEvidenceSource.CANDIDATE_SOURCE_INCOMPLETE
    )
    state = _r7_metric_state(outcome.run)
    assert state.value_state.value == "unknown"
    assert state.explanation_code == "requirement_action_candidate_source_incomplete"
    assert len(repository.items) == 1
    with pytest.raises(RequirementActionNotFoundError):
        action_contexts.source_contract(
            SESSION_ID,
            outcome.run.run_id,
            METRIC_PROJECTION_V2_VERSION_7,
        )


def test_fresh_r7_run_accepts_native_reviewed_plan_for_the_next_exact_run(
    tmp_path,
) -> None:
    identifiers = _Identifiers()
    source = _Source()
    session_repository = _Repository()
    initial_plan = _r7_requirement_plan()
    plan_reader = _R7PlanReader(initial_plan)
    action_reader = _R7ActionReader(
        RequirementActionEvidenceSnapshot(
            session_id=SESSION_ID,
            source_window_fingerprint=WINDOW_ID,
        )
    )
    wall_clock = [R7_NOW]
    plan_contexts = InMemoryRequirementPlanReviewContextStore(
        clock=lambda: wall_clock[0],
        monotonic_clock=lambda: 100.0,
    )
    action_contexts = InMemoryRequirementActionReviewContextStore(
        clock=lambda: wall_clock[0],
        monotonic_clock=lambda: 100.0,
        candidate_binding_key=b"r" * 32,
    )
    service = SessionModelEnsembleService(
        _Policy(),
        session_repository,
        lambda provider: source,
        _Compatibility(),
        identifiers,
        LocalProbabilisticMetricRunner(
            executor=_execute,
            device="cpu",
            deep_enabled=False,
        ),
        clock=lambda: wall_clock[0],
        typed_evidence_projector=_R7ActionProjector(),
        semantic_unit_reconciler=SemanticUnitReconciler(identifiers),
        requirement_plan_evidence_reader=plan_reader,
        requirement_plan_review_contexts=plan_contexts,
        requirement_action_evidence_reader=action_reader,
        requirement_action_review_contexts=action_contexts,
    )

    first = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="example-fresh-r7-plan-source-0001",
    )
    first_publication = first.run.receipt.metric_publication_v2
    assert first_publication is not None
    assert first_publication.projection_version == METRIC_PROJECTION_V2_VERSION_8
    assert first.run.requirement_plan_evidence_binding is not None
    assert (
        first.run.requirement_plan_evidence_binding.evidence_source
        is RequirementPlanEvidenceSource.REVIEWED_REQUIREMENT_PLAN
    )

    class _PlanRepositoryWithInitialAuthority(_RequirementPlanReviewRepository):
        def __init__(self) -> None:
            super().__init__()
            assert initial_plan.confirmation_id is not None
            self.heads[(SESSION_ID, WINDOW_ID)] = initial_plan.confirmation_id

        def snapshot(  # type: ignore[no-untyped-def]
            self,
            session_id: str,
            source_window_fingerprint: str,
        ):
            head = self.heads.get((session_id, source_window_fingerprint))
            if head == initial_plan.confirmation_id:
                return initial_plan
            return super().snapshot(session_id, source_window_fingerprint)

    plan_repository = _PlanRepositoryWithInitialAuthority()
    plan_service = RequirementPlanEvidenceService(
        plan_repository,
        SealedRunRequirementPlanSource(session_repository, plan_contexts),
        identifiers,
        review_contexts=plan_contexts,
        clock=lambda: wall_clock[0],
    )
    contract = plan_service.contract(SESSION_ID)
    assert contract.expected_source_run_id == first.run.run_id
    assert contract.source_projection_version == METRIC_PROJECTION_V2_VERSION_8
    database = Database(tmp_path / "fresh-r7-plan.sqlite3")
    database.initialize()
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        requirement_plan_evidence_service=plan_service,
        user_presence_confirmation=lambda _request, _body: None,
    )
    base = f"/v1/sessions/{SESSION_ID}/requirement-plan-evidence"
    document: dict[str, object] = {
        "schema_version": REQUIREMENT_PLAN_EVIDENCE_FILE_VERSION,
        "session_id": contract.session_id,
        "expected_source_run_id": contract.expected_source_run_id,
        "source_window_fingerprint": contract.source_window_fingerprint,
        "expected_predecessor_confirmation_id": (
            contract.expected_predecessor_confirmation_id
        ),
        "registry_version": contract.registry_version,
        "contract_set_fingerprint": contract.contract_set_fingerprint,
        "metric_key": contract.metric_key,
        "metric_contract_fingerprint": contract.metric_contract_fingerprint,
        "source_projection_version": contract.source_projection_version,
        "clause_algorithm": contract.clause_algorithm,
        "review_rubric_version": contract.review_rubric_version,
        "nonce": _id("fresh-r7-requirement-plan-file"),
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "producer": {
            "kind": "local_coding_agent",
            "producer_id": "synthetic-r7-plan-agent",
            "producer_version": "synthetic.1",
            "model_id": "synthetic-local-model",
            "authority": "untrusted_provenance_claim",
        },
        "contains_prose": False,
        "contains_scores": False,
        "contains_authoritative_model_judgment_claims": False,
        "contains_untrusted_structured_proposals": True,
        "contains_objective_receipt_claims": False,
        "complete_user_clause_classification": True,
        "requirements": [
            {
                "coordinate": {"message_sequence": 0, "clause_index": 0},
                "disposition": "not_linked",
                "plan_indexes": [],
            }
        ],
        "excluded_user_clauses": [],
        "plan_items": [],
    }

    def canonical_payload(value: dict[str, object]) -> bytes:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")

    projection_mismatch = dict(document)
    projection_mismatch["source_projection_version"] = (
        METRIC_PROJECTION_V2_VERSION_6
    )
    stale_source = dict(document)
    stale_source["expected_source_run_id"] = _id("stale-r7-plan-source")
    payload = canonical_payload(document)
    file_headers = {
        API_TOKEN_HEADER: TOKEN,
        "Content-Type": REQUIREMENT_PLAN_EVIDENCE_MEDIA_TYPE,
    }
    with TestClient(app, base_url="http://127.0.0.1") as client:
        contract_response = client.get(
            f"{base}/contract",
            headers={API_TOKEN_HEADER: TOKEN},
        )
        mismatched_projection = client.post(
            f"{base}/preview",
            headers=file_headers,
            content=canonical_payload(projection_mismatch),
        )
        mismatched_source = client.post(
            f"{base}/preview",
            headers=file_headers,
            content=canonical_payload(stale_source),
        )
        preview_response = client.post(
            f"{base}/preview",
            headers=file_headers,
            content=payload,
        )
        digest = hashlib.sha256(payload).hexdigest()
        imported = client.post(
            f"{base}/import",
            headers={
                **file_headers,
                "Idempotency-Key": "synthetic-r7-plan-import-0001",
                "X-Requirement-Plan-Payload-SHA256": digest,
                "X-Requirement-Plan-Confirmation": (
                    REQUIREMENT_PLAN_IMPORT_CONFIRMATION
                ),
            },
            content=payload,
        )
        proposal_id = imported.json()["proposal"]["proposal_id"]
        token_only_decision = client.post(
            f"{base}/proposals/{proposal_id}/decision",
            headers={
                API_TOKEN_HEADER: TOKEN,
                "Idempotency-Key": "synthetic-r7-token-decision-denied",
            },
            json=RequirementPlanDecisionCommand(
                expected_source_run_id=first.run.run_id,
                decision=RequirementPlanDecisionKind.CONFIRM,
                confirmation=REQUIREMENT_PLAN_DECISION_CONFIRMATION,
                review_receipt_id="1" * 64,
                manifest_fingerprint="2" * 64,
                reviewed_graph_fingerprint="3" * 64,
                reviewed_candidate_set_fingerprint="4" * 64,
                complete_review_acknowledged=True,
            ).model_dump(mode="json"),
        )
        browser = client.get("/auth/session")
        native_headers = {
            CSRF_HEADER: browser.json()["csrf_token"],
            "Origin": "http://127.0.0.1",
        }
        review = client.post(
            f"{base}/proposals/{proposal_id}/review",
            headers=native_headers,
            json={
                "expected_source_run_id": first.run.run_id,
                "confirmation": "open_exact_local_requirement_plan_clause_review",
            },
        )
        review_body = review.json()
        decided = client.post(
            f"{base}/proposals/{proposal_id}/decision",
            headers={
                **native_headers,
                "Idempotency-Key": "synthetic-r7-plan-native-decision-0001",
            },
            json=RequirementPlanDecisionCommand(
                expected_source_run_id=first.run.run_id,
                decision=RequirementPlanDecisionKind.CONFIRM,
                confirmation=REQUIREMENT_PLAN_DECISION_CONFIRMATION,
                review_receipt_id=review_body["review_receipt_id"],
                manifest_fingerprint=review_body["manifest_fingerprint"],
                reviewed_graph_fingerprint=review_body[
                    "reviewed_graph_fingerprint"
                ],
                reviewed_candidate_set_fingerprint=review_body[
                    "reviewed_candidate_set_fingerprint"
                ],
                complete_review_acknowledged=True,
            ).model_dump(mode="json"),
        )

    assert contract_response.status_code == 200
    assert contract_response.json()["source_projection_version"] == (
        METRIC_PROJECTION_V2_VERSION_8
    )
    for mismatch in (mismatched_projection, mismatched_source):
        assert mismatch.status_code == 409
        assert mismatch.json()["detail"]["code"] == (
            "requirement_plan_source_window_stale"
        )
    assert preview_response.status_code == 200
    assert imported.status_code == 201
    assert imported.json()["proposal"]["status"] == "proposed"
    assert token_only_decision.status_code == 403
    assert review.status_code == 200
    assert decided.status_code == 201
    assert decided.json()["proposal"]["confirmation_authority"] == (
        "owned_native_user_presence"
    )

    reviewed_snapshot = plan_service.snapshot_for_window(SESSION_ID, WINDOW_ID)
    plan_reader.snapshot = reviewed_snapshot
    wall_clock[0] += timedelta(seconds=1)
    next_run = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="example-fresh-r7-plan-next-run-0002",
        reuse_latest=True,
        prior_run_id=first.run.run_id,
    )
    assert next_run.applied is True
    assert next_run.run.run_id != first.run.run_id
    next_publication = next_run.run.receipt.metric_publication_v2
    assert next_publication is not None
    assert next_publication.projection_version == METRIC_PROJECTION_V2_VERSION_8
    binding = next_run.run.requirement_plan_evidence_binding
    assert binding is not None
    assert (
        binding.evidence_source
        is RequirementPlanEvidenceSource.REVIEWED_REQUIREMENT_PLAN
    )
    assert binding.confirmation_id == reviewed_snapshot.confirmation_id
    assert binding.proposal_id == reviewed_snapshot.proposal_id
    assert binding.evidence_fingerprint == requirement_plan_snapshot_fingerprint(
        reviewed_snapshot,
        identifiers,
    )
    decomposition = next(
        item.state
        for item in next_publication.metrics
        if item.state.metric_key == "logic.decomposition_coverage"
    )
    assert (
        decomposition.value_state.value,
        decomposition.explanation_code,
        decomposition.numerator,
        decomposition.denominator,
    ) == ("known", "reviewed_requirement_plan_links", 0, 1)

    with TestClient(app, base_url="http://127.0.0.1") as client:
        stale_after_next_run = client.post(
            f"{base}/preview",
            headers=file_headers,
            content=payload,
        )
    assert stale_after_next_run.status_code == 409
    assert stale_after_next_run.json()["detail"]["code"] == (
        "requirement_plan_source_window_stale"
    )


def test_session_r7_review_context_authority_and_reuse_are_exact() -> None:
    identifiers = _Identifiers()
    source = _Source()
    repository = _Repository()
    plan = _r7_requirement_plan()
    plan_reader = _R7PlanReader(plan)
    action_reader = _R7ActionReader(
        RequirementActionEvidenceSnapshot(
            session_id=SESSION_ID,
            source_window_fingerprint=WINDOW_ID,
        )
    )
    projector = _R7ActionProjector()
    action_contexts = InMemoryRequirementActionReviewContextStore(
        clock=lambda: R7_NOW,
        monotonic_clock=lambda: 100.0,
        candidate_binding_key=b"r" * 32,
    )
    service = SessionModelEnsembleService(
        _Policy(),
        repository,
        lambda provider: source,
        _Compatibility(),
        identifiers,
        LocalProbabilisticMetricRunner(
            executor=_execute,
            device="cpu",
            deep_enabled=False,
        ),
        clock=lambda: R7_NOW,
        typed_evidence_projector=projector,
        semantic_unit_reconciler=SemanticUnitReconciler(identifiers),
        requirement_plan_evidence_reader=plan_reader,
        requirement_action_evidence_reader=action_reader,
        requirement_action_review_contexts=action_contexts,
    )

    first = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="example-r7-awaiting-0001",
    )

    first_publication = first.run.receipt.metric_publication_v2
    assert first_publication is not None
    assert first_publication.projection_version == METRIC_PROJECTION_V2_VERSION_8
    assert first.run.requirement_plan_evidence_binding is not None
    assert (
        first.run.requirement_plan_evidence_binding.evidence_source
        is RequirementPlanEvidenceSource.REVIEWED_REQUIREMENT_PLAN
    )
    assert first.run.requirement_action_evidence_binding is not None
    assert (
        first.run.requirement_action_evidence_binding.evidence_source
        is RequirementActionEvidenceSource.AWAITING_REVIEW
    )
    awaiting_state = _r7_metric_state(first.run)
    assert awaiting_state.value_state.value == "unknown"
    assert awaiting_state.explanation_code == (
        "requirement_action_evidence_confirmation_required"
    )
    assert source.read_count == 1
    # One content-free preflight enters request identity; one exact recheck
    # closes growth/overflow races before the run is sealed.
    assert projector.manifest_count == 2

    source_contract = SealedRunRequirementActionSource(
        repository, action_contexts
    ).current_source_contract(SESSION_ID)
    assert source_contract.expected_source_run_id == first.run.run_id
    assert source.read_count == 1

    action_reader.snapshot = _r7_action_snapshot(
        plan=plan,
        manifest=source_contract.candidate_manifest,
        identifiers=identifiers,
        label="r7-reviewed",
    )
    original_source_run = repository.items[first.run.run_id]
    assert original_source_run.requirement_plan_evidence_binding is not None
    source_plan_binding = original_source_run.requirement_plan_evidence_binding
    original_publication = original_source_run.receipt.metric_publication_v2
    assert original_publication is not None
    lineage_attacks = (
        original_source_run.model_copy(
            update={"session_id": _id("r7-foreign-session")}
        ),
        original_source_run.model_copy(
            update={"input_fingerprint": _id("r7-foreign-window")}
        ),
        original_source_run.model_copy(
            update={
                "requirement_plan_evidence_binding": (
                    source_plan_binding.model_copy(
                        update={
                            "confirmation_id": _id(
                                "r7-foreign-plan-confirmation"
                            )
                        }
                    )
                )
            }
        ),
        original_source_run.model_copy(
            update={
                "requirement_plan_evidence_binding": (
                    source_plan_binding.model_copy(
                        update={
                            "evidence_fingerprint": _id(
                                "r7-foreign-plan-fingerprint"
                            )
                        }
                    )
                )
            }
        ),
        original_source_run.model_copy(
            update={
                "receipt": original_source_run.receipt.model_copy(
                    update={
                        "metric_publication_v2": (
                            original_publication.model_copy(
                                update={
                                    "projection_version": (
                                        "metric-contract-v2-projection-5"
                                    )
                                }
                            )
                        )
                    }
                )
            }
        ),
    )
    for index, attacked_source_run in enumerate(lineage_attacks):
        repository.items[first.run.run_id] = attacked_source_run
        attacked = service.run(
            provider=Provider.CODEX,
            session_id=SESSION_ID,
            confirmation=MODEL_ENSEMBLE_CONFIRMATION,
            idempotency_key=f"example-r7-lineage-attack-{index:04d}",
        )
        assert attacked.applied is True
        assert attacked.run.requirement_action_evidence_binding is not None
        assert (
            attacked.run.requirement_action_evidence_binding.evidence_source
            is RequirementActionEvidenceSource.BINDING_INVALID
        )
        attacked_binding = attacked.run.requirement_action_evidence_binding
        assert attacked_binding.evidence_fingerprint == (
            REQUIREMENT_ACTION_BINDING_INVALID_FINGERPRINT
        )
        assert attacked_binding.evidence_schema_version == (
            REQUIREMENT_ACTION_BINDING_INVALID_SCHEMA_VERSION
        )
        assert all(
            value is None
            for value in (
                attacked_binding.source_run_id,
                attacked_binding.requirement_plan_confirmation_id,
                attacked_binding.requirement_plan_evidence_fingerprint,
                attacked_binding.candidate_manifest_fingerprint,
                attacked_binding.confirmation_id,
                attacked_binding.proposal_id,
                attacked_binding.reviewed_descriptor_set_fingerprint,
            )
        )
        attacked_state = _r7_metric_state(attacked.run)
        assert attacked_state.explanation_code == (
            "requirement_action_evidence_invalid"
        )
        repository.items[first.run.run_id] = original_source_run

    reviewed = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="example-r7-reviewed-0002",
        reuse_latest=True,
        prior_run_id=first.run.run_id,
    )

    assert reviewed.applied is True
    assert reviewed.run.run_id != first.run.run_id
    assert reviewed.run.request_fingerprint != first.run.request_fingerprint
    assert reviewed.run.requirement_action_evidence_binding is not None
    assert (
        reviewed.run.requirement_action_evidence_binding.evidence_source
        is RequirementActionEvidenceSource.REVIEWED_REQUIREMENT_ACTION
    )
    reviewed_state = _r7_metric_state(reviewed.run)
    assert (
        reviewed_state.value_state.value,
        reviewed_state.numerator,
        reviewed_state.denominator,
    ) == ("known", 1, 1)

    unchanged = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="example-r7-reviewed-0003",
        reuse_latest=True,
        prior_run_id=reviewed.run.run_id,
    )
    assert unchanged.applied is False
    assert unchanged.run.run_id == reviewed.run.run_id

    projector.include_extra = True
    same_window_drift = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="example-r7-new-action-0004",
        reuse_latest=True,
        prior_run_id=reviewed.run.run_id,
    )
    assert same_window_drift.applied is True
    assert same_window_drift.run.run_id != reviewed.run.run_id
    assert same_window_drift.run.requirement_action_evidence_binding is not None
    assert (
            same_window_drift.run.requirement_action_evidence_binding.evidence_source
            is RequirementActionEvidenceSource.CANDIDATE_SOURCE_INCOMPLETE
        )
    drifted_state = _r7_metric_state(same_window_drift.run)
    assert drifted_state.value_state.value == "unknown"

    reads_before_replay = source.read_count
    exact_replay = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="example-r7-reviewed-0002",
        reuse_latest=True,
        prior_run_id=reviewed.run.run_id,
    )
    assert exact_replay.applied is False
    assert exact_replay.run.run_id == reviewed.run.run_id
    assert source.read_count == reads_before_replay

    projector.include_extra = False
    projector.state = ActionState.FAILED
    source.action_state = ActionState.FAILED
    stale_confirmed_snapshot = action_reader.snapshot
    stale_manifest = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="example-r7-stale-manifest-0005",
        reuse_latest=True,
        prior_run_id=same_window_drift.run.run_id,
    )
    assert stale_manifest.run.requirement_action_evidence_binding is not None
    assert (
        stale_manifest.run.requirement_action_evidence_binding.evidence_source
        is RequirementActionEvidenceSource.BINDING_INVALID
    )
    assert _r7_metric_state(stale_manifest.run).explanation_code == (
        "requirement_action_evidence_invalid"
    )

    recovery_repository = _RequirementActionRecoveryRepository(
        identifiers,
        stale_confirmed_snapshot,
    )
    recovery_service = RequirementActionEvidenceService(
        recovery_repository,
        SealedRunRequirementActionSource(
            _FixedLatestRunRepository(stale_manifest.run),
            action_contexts,
        ),
        identifiers,
        review_contexts=action_contexts,
        clock=lambda: R7_NOW,
    )
    recovery_contract = recovery_service.contract(SESSION_ID)
    assert recovery_contract.expected_predecessor_confirmation_id == (
        stale_confirmed_snapshot.confirmation_id
    )
    recovery_file = RequirementActionEvidenceFileV1(
        schema_version=REQUIREMENT_ACTION_EVIDENCE_FILE_VERSION,
        session_id=SESSION_ID,
        expected_source_run_id=stale_manifest.run.run_id,
        source_window_fingerprint=WINDOW_ID,
        requirement_plan_confirmation_id=(
            recovery_contract.requirement_plan_confirmation_id
        ),
        requirement_plan_evidence_fingerprint=(
            recovery_contract.requirement_plan_evidence_fingerprint
        ),
        candidate_manifest_fingerprint=(
            recovery_contract.candidate_manifest.manifest_fingerprint
        ),
        expected_predecessor_confirmation_id=(
            recovery_contract.expected_predecessor_confirmation_id
        ),
        nonce=_id("r7-recovery-nonce"),
        created_at=R7_NOW,
        expires_at=R7_NOW + timedelta(hours=1),
        producer=RequirementPlanProducer(
            kind="local_coding_agent",
            producer_id="synthetic-recovery-agent",
            producer_version="synthetic.1",
            model_id="synthetic-model",
            authority="untrusted_provenance_claim",
        ),
        complete_requirement_enumeration=True,
        complete_action_candidate_enumeration=True,
        complete_requirement_link_classification=True,
        links=(
            RequirementActionLinkEntry(
                requirement_index=0,
                action_candidate_indexes=(0,),
            ),
        ),
        contains_action_state_claims=False,
        contains_objective_proof_claims=False,
        contains_metric_values=False,
        contains_prose=False,
        contains_paths=False,
    )
    recovery_payload = json.dumps(
        recovery_file.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    recovery_preview = recovery_service.preview(
        session_id=SESSION_ID,
        payload=recovery_payload,
        now=R7_NOW,
    )
    recovery_proposal, created = recovery_service.import_file(
        session_id=SESSION_ID,
        payload=recovery_payload,
        expected_payload_sha256=recovery_preview.payload_sha256,
        confirmation=REQUIREMENT_ACTION_IMPORT_CONFIRMATION,
        idempotency_key="r7-recovery-proposal-0001",
        now=R7_NOW,
    )
    assert created is True
    recovery_review = recovery_service.review_proposal(
        session_id=SESSION_ID,
        proposal_id=recovery_proposal.proposal.proposal_id,
        expected_source_run_id=stale_manifest.run.run_id,
    )
    recovery_decision, applied = recovery_service.decide(
        session_id=SESSION_ID,
        proposal_id=recovery_proposal.proposal.proposal_id,
        command=RequirementActionDecisionCommand(
            expected_source_run_id=stale_manifest.run.run_id,
            decision=RequirementActionDecisionKind.CONFIRM,
            confirmation=REQUIREMENT_ACTION_DECISION_CONFIRMATION,
            review_receipt_id=recovery_review.review_receipt_id,
            reviewed_graph_fingerprint=(
                recovery_review.reviewed_graph_fingerprint
            ),
            candidate_manifest_fingerprint=(
                recovery_review.candidate_manifest_fingerprint
            ),
            reviewed_candidate_set_fingerprint=(
                recovery_review.reviewed_candidate_set_fingerprint
            ),
            reviewed_descriptor_set_fingerprint=(
                recovery_review.reviewed_descriptor_set_fingerprint
            ),
            complete_review_acknowledged=True,
            all_requirements_and_candidates_acknowledged=True,
            all_linked_action_semantics_reviewed=True,
        ),
        idempotency_key="r7-recovery-decision-0001",
    )
    assert applied is True
    assert recovery_decision.decision is not None
    action_reader.snapshot = recovery_repository.latest_snapshot(SESSION_ID)

    changed = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="example-r7-changed-0005",
        reuse_latest=True,
        prior_run_id=stale_manifest.run.run_id,
    )
    assert changed.applied is True
    assert changed.run.run_id != reviewed.run.run_id
    assert changed.run.request_fingerprint != reviewed.run.request_fingerprint
    changed_state = _r7_metric_state(changed.run)
    assert (changed_state.numerator, changed_state.denominator) == (0, 1)

    stale_run_manifest = projector.requirement_action_candidate_manifest(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        source_run_id=_id("r7-absent-source-run"),
        source_window_fingerprint=WINDOW_ID,
    )
    action_reader.snapshot = _r7_action_snapshot(
        plan=plan,
        manifest=stale_run_manifest,
        identifiers=identifiers,
        label="r7-stale-run",
    )
    stale_run = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="example-r7-stale-run-0006",
        reuse_latest=True,
        prior_run_id=changed.run.run_id,
    )
    assert stale_run.applied is True
    assert stale_run.run.run_id != changed.run.run_id
    assert stale_run.run.requirement_action_evidence_binding is not None
    assert (
        stale_run.run.requirement_action_evidence_binding.evidence_source
        is RequirementActionEvidenceSource.BINDING_INVALID
    )
    stale_state = _r7_metric_state(stale_run.run)
    assert stale_state.value_state.value == "unknown"
    assert stale_state.explanation_code == "requirement_action_evidence_invalid"

    stale_window = _id("r7-stale-window")
    stale_window_manifest = projector.requirement_action_candidate_manifest(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        source_run_id=first.run.run_id,
        source_window_fingerprint=stale_window,
    )
    action_reader.snapshot = _r7_action_snapshot(
        plan=plan,
        manifest=stale_window_manifest,
        identifiers=identifiers,
        label="r7-stale-window",
    )
    stale_window_outcome = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="example-r7-stale-window-0007",
        reuse_latest=True,
        prior_run_id=stale_run.run.run_id,
    )
    assert stale_window_outcome.applied is True
    assert stale_window_outcome.run.requirement_action_evidence_binding is not None
    assert (
        stale_window_outcome.run.requirement_action_evidence_binding.evidence_source
        is RequirementActionEvidenceSource.BINDING_INVALID
    )
    assert _r7_metric_state(stale_window_outcome.run).explanation_code == (
        "requirement_action_evidence_invalid"
    )
