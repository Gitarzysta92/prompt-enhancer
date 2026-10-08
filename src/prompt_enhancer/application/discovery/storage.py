"""Map deterministic discovery output into immutable persistence records."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from ...domain import SafeSession
from ..persistence import CandidateSignalRecord, TaskCandidateRecord, TaskRepository
from .contracts import DiscoveryBatch, DiscoverySignal, TaskCandidate
from .engine import TaskDiscoveryEngine


class DiscoveryFingerprintFactory(Protocol):
    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str: ...


class DiscoveryStorageConflictError(RuntimeError):
    """A stable candidate ID already owns different immutable evidence."""


@dataclass(frozen=True, slots=True)
class DiscoveryPersistResult:
    batch: DiscoveryBatch
    candidates_created: int
    candidates_existing: int


def _number_code(value: float | None) -> str:
    return "unknown" if value is None else f"n:{float(value).hex()}"


def _signal_fingerprint_parts(signal: DiscoverySignal) -> tuple[str, ...]:
    return (
        signal.key,
        f"i:{signal.version}",
        *signal.session_ids,
        signal.direction.value,
        _number_code(signal.confidence),
        _number_code(signal.weight),
        signal.evidence_code,
        f"i:{signal.observed_count}",
        f"i:{signal.eligible_count}",
        _number_code(signal.coverage),
        _number_code(signal.numeric_evidence),
        signal.evidence_unit or "unknown",
    )


def _record_parts(candidate: TaskCandidate) -> tuple[str, ...]:
    signal_parts = tuple(
        value for signal in candidate.signals for value in _signal_fingerprint_parts(signal)
    )
    return (
        candidate.discovery_version,
        candidate.provider.value,
        candidate.installation_id,
        candidate.project_id,
        *candidate.session_ids,
        *signal_parts,
        _number_code(candidate.confidence),
        f"i:{candidate.observed_count}",
        f"i:{candidate.eligible_count}",
        _number_code(candidate.coverage),
    )


def _same_immutable_candidate(
    left: TaskCandidateRecord, right: TaskCandidateRecord
) -> bool:
    return left.model_dump(exclude={"created_at"}) == right.model_dump(
        exclude={"created_at"}
    )


class DiscoveryPersistenceService:
    """Discover and append reviewable candidates without mutating prior runs."""

    def __init__(
        self,
        engine: TaskDiscoveryEngine,
        repository: TaskRepository,
        fingerprints: DiscoveryFingerprintFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._engine = engine
        self._repository = repository
        self._fingerprints = fingerprints
        self._clock = clock

    def discover_and_persist(
        self, sessions: Iterable[SafeSession]
    ) -> DiscoveryPersistResult:
        batch = self._engine.discover(sessions)
        created_at = self._clock()
        created = 0
        existing_count = 0
        for candidate in batch.candidates:
            record = self._to_record(candidate, created_at)
            existing = self._repository.get_candidate(candidate.candidate_id)
            if existing is not None:
                if not _same_immutable_candidate(existing, record):
                    raise DiscoveryStorageConflictError(
                        "candidate identifier conflicts with immutable evidence"
                    )
                existing_count += 1
                continue
            self._repository.add_candidate(record)
            created += 1
        return DiscoveryPersistResult(
            batch=batch,
            candidates_created=created,
            candidates_existing=existing_count,
        )

    def _to_record(
        self, candidate: TaskCandidate, created_at: datetime
    ) -> TaskCandidateRecord:
        return TaskCandidateRecord(
            candidate_id=candidate.candidate_id,
            provider=candidate.provider,
            installation_id=candidate.installation_id,
            project_id=candidate.project_id,
            session_ids=candidate.session_ids,
            signals=tuple(
                CandidateSignalRecord(
                    key=signal.key,
                    version=signal.version,
                    session_ids=signal.session_ids,
                    direction=signal.direction,
                    confidence=signal.confidence,
                    weight=signal.weight,
                    evidence_code=signal.evidence_code,
                    observed_count=signal.observed_count,
                    eligible_count=signal.eligible_count,
                    coverage=signal.coverage,
                    numeric_evidence=signal.numeric_evidence,
                    evidence_unit=signal.evidence_unit,
                )
                for signal in candidate.signals
            ),
            confidence=candidate.confidence,
            observed_count=candidate.observed_count,
            eligible_count=candidate.eligible_count,
            coverage=candidate.coverage,
            discovery_version=candidate.discovery_version,
            input_fingerprint=self._fingerprints.fingerprint(
                "task-candidate-input-v1", _record_parts(candidate)
            ),
            created_at=created_at,
        )
