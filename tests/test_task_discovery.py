from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import hmac

import pytest

from prompt_enhancer.application.discovery import (
    CandidateIdError,
    CandidateIdentity,
    InvalidDiscoveryInputError,
    SignalDirection,
    TaskDiscoveryEngine,
)
from prompt_enhancer.domain import Provider, SafeSession, SessionState


BASE_TIME = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)


class _SyntheticCandidateIdFactory:
    """Deterministic HMAC factory containing only a fictional test key."""

    def __init__(self) -> None:
        self.identities: list[CandidateIdentity] = []

    def create(self, identity: CandidateIdentity) -> str:
        self.identities.append(identity)
        payload = "|".join(
            (
                identity.discovery_version,
                identity.provider.value,
                identity.installation_id,
                identity.project_id,
                *identity.session_ids,
            )
        )
        return hmac.new(b"synthetic-discovery-key" * 2, payload.encode(), hashlib.sha256).hexdigest()


def _session(
    session_id: str,
    *,
    start: timedelta,
    duration: timedelta | None,
    state: SessionState,
    project_id: str = "1" * 64,
) -> SafeSession:
    started_at = BASE_TIME + start
    return SafeSession(
        provider=Provider.SYNTHETIC,
        installation_id="0" * 64,
        project_id=project_id,
        session_id=session_id * 64,
        provider_version="synthetic-1",
        adapter_version="0.1.0",
        source_schema_version="synthetic-1",
        started_at=started_at,
        ended_at=None if duration is None else started_at + duration,
        terminal_state=state,
        events_complete=duration is not None,
    )


def test_discovery_is_stable_reviewable_and_keeps_session_distinct_from_task() -> None:
    first = _session(
        "a",
        start=timedelta(),
        duration=timedelta(minutes=30),
        state=SessionState.INTERRUPTED,
    )
    continuation = _session(
        "b",
        start=timedelta(hours=1),
        duration=timedelta(minutes=30),
        state=SessionState.COMPLETED,
    )
    distant = _session(
        "c",
        start=timedelta(hours=6),
        duration=timedelta(minutes=10),
        state=SessionState.COMPLETED,
    )
    other_project = _session(
        "d",
        start=timedelta(minutes=15),
        duration=timedelta(minutes=5),
        state=SessionState.COMPLETED,
        project_id="2" * 64,
    )

    forward = TaskDiscoveryEngine(_SyntheticCandidateIdFactory()).discover(
        (first, continuation, distant, other_project)
    )
    reverse = TaskDiscoveryEngine(_SyntheticCandidateIdFactory()).discover(
        (other_project, distant, continuation, first)
    )

    assert tuple(candidate.candidate_id for candidate in forward.candidates) == tuple(
        candidate.candidate_id for candidate in reverse.candidates
    )
    assert tuple(candidate.session_ids for candidate in forward.candidates) == (
        (first.session_id, continuation.session_id),
        (distant.session_id,),
        (other_project.session_id,),
    )
    assert all(not hasattr(candidate, "task_id") for candidate in forward.candidates)

    linked = forward.candidates[0]
    assert linked.confidence is not None
    assert linked.coverage == 1
    assert linked.observed_count == linked.eligible_count == 3
    assert {signal.key for signal in linked.signals} == {
        "discovery.temporal_proximity",
        "discovery.terminal_continuity",
    }

    assert len(forward.boundaries) == 1
    boundary = forward.boundaries[0]
    assert boundary.left_session_id == continuation.session_id
    assert boundary.right_session_id == distant.session_id
    assert boundary.confidence is not None and boundary.confidence > 0.5


def test_missing_end_time_remains_partial_evidence_instead_of_zero() -> None:
    open_session = _session(
        "a",
        start=timedelta(),
        duration=None,
        state=SessionState.UNKNOWN,
    )
    next_session = _session(
        "b",
        start=timedelta(minutes=30),
        duration=timedelta(minutes=5),
        state=SessionState.COMPLETED,
    )

    result = TaskDiscoveryEngine(_SyntheticCandidateIdFactory()).discover(
        (open_session, next_session)
    )

    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.session_ids == (open_session.session_id, next_session.session_id)
    assert candidate.observed_count == 1
    assert candidate.eligible_count == 3
    assert candidate.coverage == pytest.approx(1 / 3)

    temporal, terminal = candidate.signals
    assert temporal.evidence_code == "start_gap_without_end_time"
    assert temporal.observed_count == 1
    assert temporal.eligible_count == 2
    assert temporal.coverage == 0.5
    assert terminal.direction is SignalDirection.UNKNOWN
    assert terminal.confidence is None
    assert terminal.coverage == 0


def test_project_is_a_hard_scope_boundary_without_invented_pair_evidence() -> None:
    left = _session(
        "a",
        start=timedelta(),
        duration=timedelta(minutes=10),
        state=SessionState.INTERRUPTED,
        project_id="1" * 64,
    )
    right = _session(
        "b",
        start=timedelta(minutes=11),
        duration=timedelta(minutes=10),
        state=SessionState.INTERRUPTED,
        project_id="2" * 64,
    )

    result = TaskDiscoveryEngine(_SyntheticCandidateIdFactory()).discover((left, right))

    assert len(result.candidates) == 2
    assert result.boundaries == ()
    assert all(candidate.signals == () for candidate in result.candidates)
    assert all(candidate.confidence is None for candidate in result.candidates)


def test_id_factory_receives_canonical_safe_identity() -> None:
    later = _session(
        "a",
        start=timedelta(minutes=20),
        duration=timedelta(minutes=5),
        state=SessionState.COMPLETED,
    )
    earlier = _session(
        "f",
        start=timedelta(),
        duration=timedelta(minutes=5),
        state=SessionState.INTERRUPTED,
    )
    factory = _SyntheticCandidateIdFactory()

    TaskDiscoveryEngine(factory).discover((later, earlier))

    assert len(factory.identities) == 1
    assert factory.identities[0].session_ids == tuple(
        sorted((earlier.session_id, later.session_id))
    )


def test_invalid_or_duplicate_inputs_fail_with_sanitized_errors() -> None:
    session = _session(
        "a",
        start=timedelta(),
        duration=timedelta(minutes=5),
        state=SessionState.COMPLETED,
    )

    with pytest.raises(InvalidDiscoveryInputError, match="duplicate session"):
        TaskDiscoveryEngine(_SyntheticCandidateIdFactory()).discover((session, session))

    class _InvalidFactory:
        def create(self, identity: CandidateIdentity) -> str:
            return "not-a-pseudonym"

    with pytest.raises(CandidateIdError, match="invalid pseudonym"):
        TaskDiscoveryEngine(_InvalidFactory()).discover((session,))


def test_empty_discovery_batch_is_valid_and_does_not_call_factory() -> None:
    factory = _SyntheticCandidateIdFactory()

    result = TaskDiscoveryEngine(factory).discover(())

    assert result.candidates == ()
    assert result.boundaries == ()
    assert factory.identities == []
