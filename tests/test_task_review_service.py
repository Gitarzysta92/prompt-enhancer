from __future__ import annotations

from datetime import UTC, datetime

import pytest

from prompt_enhancer.application.discovery import (
    AcceptCandidate,
    MergeCandidates,
    RejectionReason,
    RejectCandidate,
    SplitCandidate,
    TaskCategory,
)
from prompt_enhancer.application.discovery.review import (
    CandidateNotFoundError,
    InvalidTaskReviewError,
    StaleCandidateError,
    TaskReviewService,
)
from prompt_enhancer.application.persistence import (
    DecisionAction,
    TaskCandidateRecord,
)
from prompt_enhancer.domain import Provider


NOW = datetime(2026, 5, 3, 12, 0, tzinfo=UTC)


class _Ids:
    def decision_id(self, idempotency_key: str) -> str:
        return "d" * 64

    def task_id(self, decision_id: str, output_ordinal: int) -> str:
        return f"{output_ordinal + 1:x}" * 64

    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str:
        return "f" * 64


class _Repository:
    def __init__(self, *candidates: TaskCandidateRecord, applied: bool = True) -> None:
        self.candidates = {item.candidate_id: item for item in candidates}
        self.applied = applied
        self.calls = []

    def get_candidate(self, candidate_id: str):
        return self.candidates.get(candidate_id)

    def apply_review_decision(
        self, decision, output_revisions, *, expected_discovery_version
    ) -> bool:
        self.calls.append((decision, output_revisions, expected_discovery_version))
        return self.applied


def _candidate(
    candidate_character: str,
    session_characters: tuple[str, ...],
    *,
    project_character: str = "1",
    version: str = "metadata-v1",
) -> TaskCandidateRecord:
    return TaskCandidateRecord(
        candidate_id=candidate_character * 64,
        provider=Provider.SYNTHETIC,
        installation_id="0" * 64,
        project_id=project_character * 64,
        session_ids=tuple(character * 64 for character in session_characters),
        signals=(),
        confidence=None,
        observed_count=0,
        eligible_count=0,
        coverage=0,
        discovery_version=version,
        input_fingerprint="e" * 64,
        created_at=NOW,
    )


def _service(repository: _Repository) -> TaskReviewService:
    return TaskReviewService(repository, _Ids(), clock=lambda: NOW)


def test_accept_builds_one_confirmed_revision_and_is_retry_aware() -> None:
    candidate = _candidate("a", ("3", "4"))
    repository = _Repository(candidate, applied=False)

    result = _service(repository).apply(
        AcceptCandidate(
            candidate_id=candidate.candidate_id,
            expected_discovery_version="metadata-v1",
            task_category=TaskCategory.BUG_FIX,
        ),
        idempotency_key="example-review-0001",
    )

    decision, revisions, expected_version = repository.calls[0]
    assert result.applied is False
    assert result.action is DecisionAction.ACCEPT
    assert result.output_revisions == (("1" * 64, 1),)
    assert expected_version == "metadata-v1"
    assert decision.candidate_ids == (candidate.candidate_id,)
    assert decision.decision_code is None
    assert revisions[0].task_type == "bug_fix"
    assert revisions[0].lifecycle_state == "confirmed"
    assert revisions[0].session_ids == candidate.session_ids


def test_reject_records_only_a_content_free_reason() -> None:
    candidate = _candidate("a", ("3",))
    repository = _Repository(candidate)

    result = _service(repository).apply(
        RejectCandidate(
            candidate_id=candidate.candidate_id,
            expected_discovery_version="metadata-v1",
            reason=RejectionReason.WRONG_GROUPING,
        ),
        idempotency_key="example-review-0002",
    )

    decision, revisions, _ = repository.calls[0]
    assert result.output_revisions == ()
    assert decision.action is DecisionAction.REJECT
    assert decision.decision_code == "wrong_grouping"
    assert revisions == ()


def test_merge_is_canonical_and_rejects_overlap_or_cross_project_scope() -> None:
    first = _candidate("a", ("3",))
    second = _candidate("b", ("4",))
    repository = _Repository(first, second)
    command = MergeCandidates(
        candidate_ids=(second.candidate_id, first.candidate_id),
        expected_discovery_version="metadata-v1",
    )

    _service(repository).apply(command, idempotency_key="example-review-0003")

    decision, revisions, _ = repository.calls[0]
    assert decision.candidate_ids == (first.candidate_id, second.candidate_id)
    assert revisions[0].session_ids == first.session_ids + second.session_ids

    overlapping = _candidate("c", ("3",))
    with pytest.raises(InvalidTaskReviewError, match="overlapping"):
        _service(_Repository(first, overlapping)).apply(
            MergeCandidates(
                candidate_ids=(first.candidate_id, overlapping.candidate_id),
                expected_discovery_version="metadata-v1",
            ),
            idempotency_key="example-review-0004",
        )

    other_project = _candidate("c", ("5",), project_character="2")
    with pytest.raises(InvalidTaskReviewError, match="cross"):
        _service(_Repository(first, other_project)).apply(
            MergeCandidates(
                candidate_ids=(first.candidate_id, other_project.candidate_id),
                expected_discovery_version="metadata-v1",
            ),
            idempotency_key="example-review-0005",
        )


def test_split_requires_exact_coverage_and_builds_distinct_outputs() -> None:
    candidate = _candidate("a", ("3", "4", "5"))
    repository = _Repository(candidate)

    result = _service(repository).apply(
        SplitCandidate(
            candidate_id=candidate.candidate_id,
            partitions=(("3" * 64,), ("4" * 64, "5" * 64)),
            expected_discovery_version="metadata-v1",
        ),
        idempotency_key="example-review-0006",
    )

    assert result.output_revisions == (("1" * 64, 1), ("2" * 64, 1))
    _, revisions, _ = repository.calls[0]
    assert tuple(item.task_type for item in revisions) == ("unknown", "unknown")

    with pytest.raises(InvalidTaskReviewError, match="exactly cover"):
        _service(_Repository(candidate)).apply(
            SplitCandidate(
                candidate_id=candidate.candidate_id,
                partitions=(("3" * 64,), ("4" * 64,)),
                expected_discovery_version="metadata-v1",
            ),
            idempotency_key="example-review-0007",
        )


def test_missing_stale_and_content_like_requests_fail_before_writes() -> None:
    candidate = _candidate("a", ("3",), version="metadata-v2")
    repository = _Repository(candidate)

    with pytest.raises(CandidateNotFoundError, match="does not exist"):
        _service(_Repository()).apply(
            AcceptCandidate(
                candidate_id="b" * 64,
                expected_discovery_version="metadata-v1",
            ),
            idempotency_key="example-review-0008",
        )
    with pytest.raises(StaleCandidateError, match="stale"):
        _service(repository).apply(
            AcceptCandidate(
                candidate_id=candidate.candidate_id,
                expected_discovery_version="metadata-v1",
            ),
            idempotency_key="example-review-0009",
        )
    with pytest.raises(InvalidTaskReviewError, match="content-free"):
        _service(repository).apply(
            AcceptCandidate(
                candidate_id=candidate.candidate_id,
                expected_discovery_version="metadata-v2",
            ),
            idempotency_key="a prompt-like retry key with spaces",
        )
    assert repository.calls == []
