from __future__ import annotations

import pytest

from prompt_enhancer.application.discovery import (
    AcceptCandidate,
    MergeCandidates,
    RejectCandidate,
    RejectionReason,
    SplitCandidate,
    TaskCategory,
)


def test_accept_and_reject_are_explicit_versioned_review_commands() -> None:
    accepted = AcceptCandidate(
        candidate_id="a" * 64,
        expected_discovery_version="metadata-v1",
        task_category=TaskCategory.BUG_FIX,
    )
    rejected = RejectCandidate(
        candidate_id="b" * 64,
        expected_discovery_version="metadata-v1",
        reason=RejectionReason.WRONG_GROUPING,
    )

    assert accepted.task_category is TaskCategory.BUG_FIX
    assert rejected.reason is RejectionReason.WRONG_GROUPING
    assert not hasattr(accepted, "session")
    assert not hasattr(rejected, "provider_session")


def test_merge_requires_distinct_reviewed_candidates() -> None:
    with pytest.raises(ValueError, match="at least two"):
        MergeCandidates(
            candidate_ids=("a" * 64,),
            expected_discovery_version="metadata-v1",
        )

    with pytest.raises(ValueError, match="duplicate"):
        MergeCandidates(
            candidate_ids=("a" * 64, "a" * 64),
            expected_discovery_version="metadata-v1",
        )


def test_split_requires_disjoint_nonempty_session_partitions() -> None:
    command = SplitCandidate(
        candidate_id="f" * 64,
        partitions=(("a" * 64,), ("b" * 64, "c" * 64)),
        expected_discovery_version="metadata-v1",
        task_categories=(TaskCategory.BUG_FIX, TaskCategory.RESEARCH_DESIGN),
    )

    assert len(command.partitions) == 2

    with pytest.raises(ValueError, match="multiple split partitions"):
        SplitCandidate(
            candidate_id="f" * 64,
            partitions=(("a" * 64,), ("a" * 64,)),
            expected_discovery_version="metadata-v1",
        )

    with pytest.raises(ValueError, match="cannot be empty"):
        SplitCandidate(
            candidate_id="f" * 64,
            partitions=(("a" * 64,), ()),
            expected_discovery_version="metadata-v1",
        )


def test_split_categories_must_align_with_created_task_revisions() -> None:
    with pytest.raises(ValueError, match="align with partitions"):
        SplitCandidate(
            candidate_id="f" * 64,
            partitions=(("a" * 64,), ("b" * 64,)),
            expected_discovery_version="metadata-v1",
            task_categories=(TaskCategory.FEATURE_IMPLEMENTATION,),
        )
