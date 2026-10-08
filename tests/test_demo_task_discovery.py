from __future__ import annotations

from prompt_enhancer.application.persistence import CandidateDecisionStatus
from prompt_enhancer.cli import main
from prompt_enhancer.database import Database


def test_demo_persists_one_reviewable_candidate_idempotently(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))
    monkeypatch.setenv("PROMPT_ENHANCER_HOST", "127.0.0.1")

    assert main(["demo"]) == 0
    assert main(["demo"]) == 0

    database = Database(tmp_path / "metrics.sqlite3")
    pending = database.task_repository().list_candidates(
        status=CandidateDecisionStatus.UNDECIDED
    )
    assert len(pending) == 1
    assert len(pending[0].candidate.session_ids) == 2
    assert pending[0].candidate.signals
    assert pending[0].candidate.discovery_version == "metadata-v1"
