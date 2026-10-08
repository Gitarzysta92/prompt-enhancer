"""Synthetic run-identity tests for reviewed task-profile denominators."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib

from pydantic import SecretStr

from prompt_enhancer.application.analysis.declared_task_profiles import (
    DeclaredTaskProfileRecord,
)
from prompt_enhancer.application.analysis.metric_contract_v2 import MetricValueStateV2
from prompt_enhancer.application.analysis.semantic_units import SemanticUnitReconciler
from prompt_enhancer.application.analysis.session_model_ensemble import (
    MODEL_ENSEMBLE_CONFIRMATION,
    MetricProfileSource,
    ModelEnsembleSourceError,
    SessionModelEnsembleService,
)
from prompt_enhancer.application.analysis.text_contracts import (
    ConstraintKind,
    DeliverableSlot,
)
from prompt_enhancer.domain import Provider
from prompt_enhancer.infrastructure.text_models.model_ensemble import (
    SerialModelEnsembleRunner,
)

from test_session_model_ensemble import (
    SESSION_ID,
    _Compatibility,
    _Identifiers,
    _Policy,
    _Repository,
    _context,
    _execute,
)


NOW = datetime(2049, 2, 3, 4, 5, 6, tzinfo=UTC)


def _digest(label: str) -> str:
    return hashlib.sha256(f"synthetic-profile-run:{label}".encode()).hexdigest()


def _declaration(
    *,
    revision: int = 1,
    previous_profile_id: str | None = None,
    expected_outcome_count: int = 3,
) -> DeclaredTaskProfileRecord:
    return DeclaredTaskProfileRecord(
        profile_id=_digest(f"profile:{revision}"),
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        revision=revision,
        previous_profile_id=previous_profile_id,
        constraint_kinds=(ConstraintKind.COST, ConstraintKind.PRIVACY),
        expected_outcome_count=expected_outcome_count,
        deliverable_slots=(DeliverableSlot.ARTIFACT, DeliverableSlot.FORMAT),
        profile_fingerprint=_digest(f"values:{revision}"),
        idempotency_key_digest=_digest(f"retry:{revision}"),
        command_fingerprint=_digest(f"command:{revision}"),
        confirmed_at=NOW,
    )


class _ProfileReader:
    def __init__(self, declaration: DeclaredTaskProfileRecord | None) -> None:
        self.declaration = declaration
        self.read_count = 0

    def get_latest(self, provider: Provider, session_id: str):
        self.read_count += 1
        assert provider is Provider.CODEX
        assert session_id == SESSION_ID
        return self.declaration


class _ProfileSource:
    provider = Provider.CODEX
    read_only = True
    requires_explicit_selection = True

    def __init__(self) -> None:
        self.read_count = 0
        self.profiles = []

    def read(self, *, selection, grant, task_profile):
        del selection
        assert grant.local_only and not grant.content_persistence_allowed
        self.read_count += 1
        self.profiles.append(task_profile)
        context = _context()
        request = context.messages[0].model_copy(
            update={
                "text": SecretStr(
                    "Create a local only report in JSON within the budget. "
                    "It must return exactly three rows. "
                    "Add a regression test that must pass."
                )
            }
        )
        return context.model_copy(
            update={
                "messages": (request, context.messages[1]),
                "focus_message_id": request.message_id,
                "task_profile": task_profile,
            }
        )


def _service(reader: _ProfileReader):
    source = _ProfileSource()
    repository = _Repository()
    identifiers = _Identifiers()
    service = SessionModelEnsembleService(
        _Policy(),
        repository,
        lambda _provider: source,
        _Compatibility(),
        identifiers,
        SerialModelEnsembleRunner(executor=_execute, device="cpu"),
        clock=lambda: NOW,
        semantic_unit_reconciler=SemanticUnitReconciler(identifiers),
        declared_task_profile_reader=reader,
    )
    return service, source, repository


def _state(run, key: str):
    publication = run.receipt.metric_publication_v2
    assert publication is not None
    return next(item.state for item in publication.metrics if item.state.metric_key == key)


def test_declared_profile_resolves_three_metrics_and_binds_exact_r5_run() -> None:
    declaration = _declaration()
    reader = _ProfileReader(declaration)
    service, source, _repository = _service(reader)

    first = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="synthetic-profile-run-0001",
    )
    replay = service.run(
        provider=Provider.CODEX,
        session_id=SESSION_ID,
        confirmation=MODEL_ENSEMBLE_CONFIRMATION,
        idempotency_key="synthetic-profile-run-0001",
    )

    assert first.applied is True
    assert replay.applied is False
    assert replay.run == first.run
    assert source.read_count == 1
    assert reader.read_count == 2
    binding = first.run.metric_profile_binding
    assert binding is not None
    assert binding.profile_source is MetricProfileSource.DECLARED_TASK_PROFILE
    assert binding.profile_id == declaration.profile_id
    assert binding.profile_revision == declaration.revision
    assert binding.profile_fingerprint == declaration.profile_fingerprint
    assert binding.source_window_fingerprint == first.run.input_fingerprint

    constraints = _state(first.run, "prompt.constraint_precision")
    acceptance = _state(first.run, "prompt.acceptance_testability")
    deliverables = _state(first.run, "prompt.deliverable_contract")
    assert constraints.value_state is MetricValueStateV2.KNOWN
    assert (constraints.numerator, constraints.denominator) == (2, 2)
    assert acceptance.value_state is MetricValueStateV2.KNOWN
    assert (acceptance.numerator, acceptance.denominator) == (2, 3)
    assert deliverables.value_state is MetricValueStateV2.KNOWN
    assert (deliverables.numerator, deliverables.denominator) == (2, 2)


def test_profile_revision_changes_request_identity_even_for_same_retry_key() -> None:
    first_declaration = _declaration()
    reader = _ProfileReader(first_declaration)
    service, source, _repository = _service(reader)
    request = {
        "provider": Provider.CODEX,
        "session_id": SESSION_ID,
        "confirmation": MODEL_ENSEMBLE_CONFIRMATION,
        "idempotency_key": "synthetic-profile-identity-0001",
    }

    first = service.run(**request)
    reader.declaration = _declaration(
        revision=2,
        previous_profile_id=first_declaration.profile_id,
        expected_outcome_count=4,
    )
    second = service.run(**request)

    assert first.run.run_id != second.run.run_id
    assert first.run.request_fingerprint != second.run.request_fingerprint
    assert source.read_count == 2
    assert second.run.metric_profile_binding is not None
    assert second.run.metric_profile_binding.profile_revision == 2
    assert (_state(second.run, "prompt.acceptance_testability").denominator) == 4


def test_source_cannot_ignore_the_reviewed_profile_and_publish_default_values() -> None:
    reader = _ProfileReader(_declaration())
    source = _ProfileSource()

    def ignoring_read(*, selection, grant, task_profile):
        del selection, grant, task_profile
        source.read_count += 1
        return _context()

    source.read = ignoring_read  # type: ignore[method-assign]
    identifiers = _Identifiers()
    service = SessionModelEnsembleService(
        _Policy(),
        _Repository(),
        lambda _provider: source,
        _Compatibility(),
        identifiers,
        SerialModelEnsembleRunner(executor=_execute, device="cpu"),
        clock=lambda: NOW,
        semantic_unit_reconciler=SemanticUnitReconciler(identifiers),
        declared_task_profile_reader=reader,
    )

    try:
        service.run(
            provider=Provider.CODEX,
            session_id=SESSION_ID,
            confirmation=MODEL_ENSEMBLE_CONFIRMATION,
            idempotency_key="synthetic-profile-source-0001",
        )
    except ModelEnsembleSourceError:
        pass
    else:
        raise AssertionError("a source that ignored the bound profile was accepted")
