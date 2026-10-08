from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from prompt_enhancer.application.discovery import TaskDiscoveryEngine
from prompt_enhancer.application.discovery.storage import (
    DiscoveryPersistenceService,
    DiscoveryStorageConflictError,
)
from prompt_enhancer.domain import Provider, SafeSession, SessionState
from prompt_enhancer.infrastructure.identifiers import LocalArtifactIdFactory
from prompt_enhancer.privacy import Pseudonymizer


NOW = datetime(2026, 5, 4, 10, 0, tzinfo=UTC)


class _Repository:
    def __init__(self) -> None:
        self.records = {}

    def get_candidate(self, candidate_id: str):
        return self.records.get(candidate_id)

    def add_candidate(self, candidate) -> None:
        self.records[candidate.candidate_id] = candidate


def _sessions() -> tuple[SafeSession, SafeSession]:
    common = {
        "provider": Provider.SYNTHETIC,
        "installation_id": "0" * 64,
        "project_id": "1" * 64,
        "provider_version": "synthetic-1",
        "adapter_version": "0.1.0",
        "source_schema_version": "synthetic-1",
        "events_complete": False,
    }
    return (
        SafeSession(
            **common,
            session_id="a" * 64,
            started_at=NOW,
            ended_at=None,
            terminal_state=SessionState.UNKNOWN,
        ),
        SafeSession(
            **common,
            session_id="b" * 64,
            started_at=NOW + timedelta(minutes=20),
            ended_at=None,
            terminal_state=SessionState.COMPLETED,
        ),
    )


def _service(repository: _Repository) -> DiscoveryPersistenceService:
    identifiers = LocalArtifactIdFactory(Pseudonymizer(bytes(range(32))))
    return DiscoveryPersistenceService(
        TaskDiscoveryEngine(identifiers),
        repository,
        identifiers,
        clock=lambda: NOW,
    )


def test_discovery_records_round_trip_unknown_signal_evidence_and_are_idempotent() -> None:
    repository = _Repository()
    service = _service(repository)

    first = service.discover_and_persist(_sessions())
    second = service.discover_and_persist(reversed(_sessions()))

    assert first.candidates_created == 1
    assert first.candidates_existing == 0
    assert second.candidates_created == 0
    assert second.candidates_existing == 1
    record = next(iter(repository.records.values()))
    assert record.provider is Provider.SYNTHETIC
    assert len(record.input_fingerprint) == 64
    assert record.coverage == pytest.approx(1 / 3)
    assert record.signals[1].direction.value == "unknown"
    assert record.signals[1].confidence is None
    assert "content" not in record.model_dump()


def test_stable_candidate_id_cannot_be_reused_for_different_evidence() -> None:
    repository = _Repository()
    service = _service(repository)
    service.discover_and_persist(_sessions())
    candidate_id, record = next(iter(repository.records.items()))
    repository.records[candidate_id] = record.model_copy(
        update={"input_fingerprint": "9" * 64}
    )

    with pytest.raises(DiscoveryStorageConflictError, match="immutable evidence"):
        service.discover_and_persist(_sessions())
