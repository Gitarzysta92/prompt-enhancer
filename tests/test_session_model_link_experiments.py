from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib

from pydantic import SecretStr
import pytest

from prompt_enhancer.application.analysis.model_link_experiments import (
    MODEL_LINK_CONFIRMATION,
    ModelExperimentDevice,
    ModelLinkAnnotationLabel,
    ModelLinkConsentError,
    ModelLinkModelIdentity,
    ModelLinkPairScore,
    ModelLinkRunnerResult,
    ModelLinkStoredExperiment,
    SessionModelLinkExperimentService,
)
from prompt_enhancer.application.analysis.text_analysis_presets import (
    COACHING_PROFILE_V1,
)
from prompt_enhancer.application.analysis.text_contracts import (
    EphemeralRedactedMessage,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextRole,
)
from prompt_enhancer.application.analysis.text_source import TextAnalysisPurpose
from prompt_enhancer.domain import DataTier, Provider


SESSION_ID = "a" * 64
WINDOW_ID = "b" * 64
NOW = datetime(2040, 1, 1, 12, tzinfo=UTC)


def _id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _context() -> P1TextAnalysisInput:
    messages = (
        EphemeralRedactedMessage(
            message_id=_id("request-1"),
            sequence=0,
            role=TextRole.USER,
            kind=TextMessageKind.REQUEST,
            language=TextLanguage.ENGLISH,
            text=SecretStr("Build a fictional loopback status card."),
        ),
        EphemeralRedactedMessage(
            message_id=_id("plan-1"),
            sequence=1,
            role=TextRole.AGENT,
            kind=TextMessageKind.PLAN,
            language=TextLanguage.ENGLISH,
            text=SecretStr("Plan the fictional status card and its synthetic tests."),
        ),
        EphemeralRedactedMessage(
            message_id=_id("response-1"),
            sequence=2,
            role=TextRole.AGENT,
            kind=TextMessageKind.RESPONSE,
            language=TextLanguage.ENGLISH,
            text=SecretStr("Implemented the fictional loopback card with synthetic tests."),
        ),
        EphemeralRedactedMessage(
            message_id=_id("request-2"),
            sequence=3,
            role=TextRole.USER,
            kind=TextMessageKind.FEEDBACK,
            language=TextLanguage.ENGLISH,
            text=SecretStr("Make the fictional card compact on mobile."),
        ),
        EphemeralRedactedMessage(
            message_id=_id("response-2"),
            sequence=4,
            role=TextRole.AGENT,
            kind=TextMessageKind.RESPONSE,
            language=TextLanguage.ENGLISH,
            text=SecretStr("Adjusted the fictional card for a compact mobile layout."),
        ),
    )
    return P1TextAnalysisInput(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        provider_version="example-provider-1",
        adapter_version="example-adapter-1",
        source_schema_version="example-source-1",
        content_schema_version="example-content-1",
        redactor_version="example-redactor-1",
        text_extraction_complete=True,
        available_message_kinds=frozenset(
            {
                TextMessageKind.REQUEST,
                TextMessageKind.FEEDBACK,
                TextMessageKind.RESPONSE,
                TextMessageKind.PLAN,
            }
        ),
        analysis_window_fingerprint=WINDOW_ID,
        focus_message_id=_id("request-2"),
        observed_message_count=len(messages),
        eligible_message_count=len(messages),
        messages=messages,
        task_profile=COACHING_PROFILE_V1.task_profile,
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


class _Source:
    provider = Provider.CODEX
    purpose = TextAnalysisPurpose.TEXT_ANALYSIS
    read_only = True
    requires_explicit_selection = True

    def __init__(self) -> None:
        self.read_count = 0

    def read(self, *, selection, grant, task_profile):
        self.read_count += 1
        assert selection.session_id == SESSION_ID
        assert grant.per_run_confirmation_active
        assert not grant.content_persistence_allowed
        assert task_profile == COACHING_PROFILE_V1.task_profile
        return _context()


class _Runner:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, request):
        self.calls += 1
        scores = []
        for case in request.cases:
            for index, candidate in enumerate(case.candidates):
                scores.append(
                    ModelLinkPairScore(
                        query_message_id=case.query_message_id,
                        candidate_message_id=candidate.message_id,
                        qwen_score=0.9 - index * 0.2,
                        bge_score=(0.5 + index if case.query_sequence == 0 else 0.9 - index),
                    )
                )
        qwen = ModelLinkModelIdentity(
            key="qwen3_embedding_06b",
            repository_id="Qwen/Qwen3-Embedding-0.6B",
            revision="c" * 40,
            license_spdx="Apache-2.0",
            tokenizer_id="Qwen/Qwen3-Embedding-0.6B:" + "c" * 40,
            backend_key="qwen3_embedding_last_token_v1",
        )
        bge = ModelLinkModelIdentity(
            key="bge_reranker_v2_m3",
            repository_id="BAAI/bge-reranker-v2-m3",
            revision="d" * 40,
            license_spdx="Apache-2.0",
            tokenizer_id="BAAI/bge-reranker-v2-m3:" + "d" * 40,
            backend_key="bge_reranker_sequence_classifier_v1",
        )
        return ModelLinkRunnerResult(
            resolved_device=ModelExperimentDevice.CUDA,
            qwen_model=qwen,
            bge_model=bge,
            scores=tuple(scores),
        )


class _Repository:
    def __init__(self) -> None:
        self.items: dict[str, ModelLinkStoredExperiment] = {}

    def save_completed(self, run, links) -> None:
        if run.run_id in self.items:
            raise ValueError("duplicate")
        self.items[run.run_id] = ModelLinkStoredExperiment(run=run, links=links)

    def get(self, run_id: str):
        return self.items.get(run_id)

    def get_latest(self, session_id: str):
        matching = [item for item in self.items.values() if item.run.session_id == session_id]
        return max(matching, key=lambda item: item.run.finished_at) if matching else None

    def append_annotation(self, annotation, *, expected_revision: int) -> bool:
        item = self.items.get(annotation.run_id)
        if item is None or annotation.link_id not in {link.link_id for link in item.links}:
            return False
        current = max(
            (
                value.revision
                for value in item.annotations
                if value.link_id == annotation.link_id
            ),
            default=0,
        )
        if current != expected_revision:
            return False
        self.items[annotation.run_id] = ModelLinkStoredExperiment(
            run=item.run,
            links=item.links,
            annotations=(*item.annotations, annotation),
        )
        return True


def _service(policy: _Policy | None = None):
    policy = policy or _Policy()
    source = _Source()
    runner = _Runner()
    repository = _Repository()
    ticks = iter(
        (
            NOW,
            NOW + timedelta(seconds=2),
            NOW + timedelta(seconds=3),
            NOW + timedelta(seconds=4),
        )
    )
    service = SessionModelLinkExperimentService(
        policy,
        repository,
        lambda provider: source,
        _Compatibility(),
        _Identifiers(),
        runner,
        clock=lambda: next(ticks),
    )
    return service, source, runner, repository


def test_model_link_experiment_returns_transient_review_items_and_persists_no_text() -> None:
    service, source, runner, repository = _service()
    result = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_LINK_CONFIRMATION,
        device=ModelExperimentDevice.CUDA,
        idempotency_key="example-model-link-run-0001",
    )

    assert result.applied is True
    assert source.read_count == runner.calls == 1
    assert result.experiment.run.query_count == 2
    assert result.experiment.run.link_count == 3
    assert result.experiment.run.agreement_count == 1
    assert len(result.suggestions) == 3
    assert "fictional" not in repr(result)
    assert "fictional" not in result.model_dump_json()
    stored = repository.get(result.experiment.run.run_id)
    assert stored is not None
    assert "fictional" not in stored.model_dump_json()
    assert all(not hasattr(link, "query_excerpt") for link in stored.links)


def test_model_link_experiment_retry_does_not_reread_or_rerun_models() -> None:
    service, source, runner, _ = _service()
    request = dict(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_LINK_CONFIRMATION,
        device=ModelExperimentDevice.CUDA,
        idempotency_key="example-model-link-run-0002",
    )
    first = service.run(**request)
    second = service.run(**request)

    assert first.applied is True
    assert second.applied is False
    assert second.suggestions == ()
    assert source.read_count == runner.calls == 1


def test_model_link_consent_denial_occurs_before_source_and_runner() -> None:
    policy = _Policy()
    policy.consent = False
    service, source, runner, _ = _service(policy)

    with pytest.raises(ModelLinkConsentError):
        service.run(
            provider=Provider.CODEX,
            session_id=SESSION_ID,
            confirmation=MODEL_LINK_CONFIRMATION,
            device=ModelExperimentDevice.CUDA,
            idempotency_key="example-model-link-run-0003",
        )
    assert source.read_count == runner.calls == 0


def test_model_link_annotations_are_revisioned_without_provider_reads() -> None:
    service, source, runner, repository = _service()
    outcome = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_LINK_CONFIRMATION,
        device=ModelExperimentDevice.CUDA,
        idempotency_key="example-model-link-run-0004",
    )
    link_id = outcome.experiment.links[0].link_id

    first = service.annotate(
        run_id=outcome.experiment.run.run_id,
        link_id=link_id,
        label=ModelLinkAnnotationLabel.RELEVANT,
        expected_revision=0,
    )
    second = service.annotate(
        run_id=outcome.experiment.run.run_id,
        link_id=link_id,
        label=ModelLinkAnnotationLabel.INCORRECT,
        expected_revision=1,
    )

    assert (first.revision, second.revision) == (1, 2)
    assert source.read_count == runner.calls == 1
    stored = repository.get(outcome.experiment.run.run_id)
    assert stored is not None
    assert [item.label for item in stored.annotations] == [
        ModelLinkAnnotationLabel.RELEVANT,
        ModelLinkAnnotationLabel.INCORRECT,
    ]
