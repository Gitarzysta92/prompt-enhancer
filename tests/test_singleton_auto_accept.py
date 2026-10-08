"""Single-session candidates are accepted automatically, visibly as automation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER
from prompt_enhancer.application.discovery.auto_accept import (
    AUTO_ACCEPT_SOURCE,
    SingletonCandidateAutoAccepter,
)
from prompt_enhancer.application.persistence import CandidateDecisionStatus
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.domain import DataTier, Provider


T0 = datetime(2026, 3, 3, 9, 0, tzinfo=UTC)


def _transcript(claude_home: Path, session: str, minute: int, project_name: str = "autoaccept") -> None:
    # Distinct projects give distinct single-session candidates; sessions in
    # one project close in time are grouped by discovery and left to a person.
    project = claude_home / "projects" / f"-srv-example-{project_name}"
    project.mkdir(parents=True, exist_ok=True)
    at = (T0 + timedelta(minutes=minute)).isoformat().replace("+00:00", "Z")
    cwd = f"/srv/example/{project_name}"
    lines = [
        json.dumps({"type": "user", "message": {"role": "user", "content": f"Prompt {session}"}, "timestamp": at, "sessionId": session, "cwd": cwd, "version": "2.1.0"}),
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Done."}]}, "timestamp": at, "sessionId": session, "cwd": cwd, "version": "2.1.0"}),
    ]
    (project / f"{session}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_singletons_are_accepted_with_automation_provenance_and_idempotently(tmp_path: Path, monkeypatch) -> None:
    claude_home = tmp_path / "claude-home"
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(claude_home))
    for index in range(3):
        _transcript(claude_home, f"sess-{index}", index * 120, project_name=f"proj-{index}")
    # Two sessions of one project close together form a grouping a person reviews.
    _transcript(claude_home, "sess-pair-a", 10, project_name="paired")
    _transcript(claude_home, "sess-pair-b", 12, project_name="paired")
    application = bootstrap_local_application(AppSettings(home=tmp_path / "app"))
    database = application.database
    database.grant_consent(Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT)
    application.create_claude_local_source_service().index(max_sessions=10)
    sessions = [database.get_session(str(row["session_id"])) for row in database.list_sessions(limit=10, offset=0)]
    discovery = application.create_discovery_persistence_service().discover_and_persist(sessions)
    assert discovery.candidates_created >= 1
    repository = database.task_repository()
    undecided = repository.list_candidates(status=CandidateDecisionStatus.UNDECIDED, limit=50, offset=0)
    singletons = [item for item in undecided if len(item.candidate.session_ids) == 1]
    grouped = [item for item in undecided if len(item.candidate.session_ids) > 1]
    assert len(singletons) == 3 and len(grouped) == 1

    accepter = SingletonCandidateAutoAccepter(repository, application.create_task_review_service())
    result = accepter.run(provider=Provider.CLAUDE_CODE)
    assert result.accepted == len(singletons) and result.failed == 0
    assert result.skipped_multi_session == 1

    decided = repository.list_candidates(status=CandidateDecisionStatus.DECIDED, limit=50, offset=0)
    assert len(decided) == len(singletons)
    assert all(item.decision_source == AUTO_ACCEPT_SOURCE for item in decided)
    assert all(item.decision_action is not None and item.decision_action.value == "accept" for item in decided)
    for item in decided:
        session_id = item.candidate.session_ids[0]
        revisions = repository.list_current_revisions_for_session(session_id)
        assert len(revisions) == 1 and revisions[0].task_type == "unknown"
        decisions = repository.list_decisions(item.candidate.candidate_id)
        assert len(decisions) == 1 and decisions[0].decision_source == AUTO_ACCEPT_SOURCE

    # A second pass finds nothing new; nothing is duplicated.
    again = accepter.run(provider=Provider.CLAUDE_CODE)
    assert again.accepted == 0 and again.failed == 0
    assert len(repository.list_candidates(status=CandidateDecisionStatus.DECIDED, limit=50, offset=0)) == len(singletons)
    # Another provider's filter touches nothing here.
    assert accepter.run(provider=Provider.CODEX).examined == 0


def test_onboarding_refresh_auto_accepts_and_exposes_provenance(tmp_path: Path, monkeypatch) -> None:
    claude_home = tmp_path / "claude-home"
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(claude_home))
    _transcript(claude_home, "sess-a", 0, project_name="alpha")
    _transcript(claude_home, "sess-b", 300, project_name="beta")
    settings = AppSettings(home=tmp_path / "app")
    application = bootstrap_local_application(settings)
    client = TestClient(application.create_http_app(), base_url="http://127.0.0.1")
    headers = {API_TOKEN_HEADER: settings.api_token_path.read_text(encoding="utf-8").strip()}
    accepted = client.post("/v1/onboarding/accept", headers=headers, json={"providers": ["claude_code"]})
    assert accepted.status_code == 200, accepted.text

    decided = client.get("/v1/discovery/candidates?status=decided&limit=50&offset=0", headers=headers)
    assert decided.status_code == 200, decided.text
    items = decided.json()["candidates"]
    assert items, "singletons should have been accepted during the first index"
    assert all(item["decision_source"] == "automation" and item["decision_action"] == "accept" for item in items)
    # Every auto-accepted session now has exactly one current reviewed revision.
    repository = application.database.task_repository()
    for item in items:
        assert len(repository.list_current_revisions_for_session(item["candidate"]["session_ids"][0])) == 1


def test_project_timeline_shows_sessions_and_task_windows(tmp_path: Path, monkeypatch) -> None:
    claude_home = tmp_path / "claude-home"
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(claude_home))
    _transcript(claude_home, "sess-a", 0, project_name="gamma")
    _transcript(claude_home, "sess-b", 600, project_name="gamma")  # ten hours later: separate candidate
    settings = AppSettings(home=tmp_path / "app")
    application = bootstrap_local_application(settings)
    client = TestClient(application.create_http_app(), base_url="http://127.0.0.1")
    headers = {API_TOKEN_HEADER: settings.api_token_path.read_text(encoding="utf-8").strip()}
    assert client.post("/v1/onboarding/accept", headers=headers, json={"providers": ["claude_code"]}).status_code == 200
    project_id = str(application.database.list_sessions(limit=5, offset=0)[0]["project_id"])

    assert client.get(f"/v1/projects/{project_id}/timeline").status_code == 401
    assert client.get(f"/v1/projects/{'f' * 64}/timeline", headers=headers).status_code == 404
    response = client.get(f"/v1/projects/{project_id}/timeline", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["contract_version"] == "project-timeline.v1"
    assert body["providers"] == ["claude_code"] and body["sessions_drawn"] == 2 and body["truncated"] is False
    assert [s["display_name"] for s in body["sessions"]] == ["Prompt sess-a", "Prompt sess-b"]
    assert body["first_started_at"] < body["last_ended_at"]
    assert sum(day["sessions"] for day in body["activity"]) == 2
    # Every auto-accepted singleton is a task window spanning its one session.
    tasks = body["tasks"]
    assert len(tasks) >= 1 and all(task["lifecycle_state"] and task["task_type"] == "unknown" for task in tasks)
    for task in tasks:
        assert task["started_at"] is not None and task["ended_at"] is not None and task["started_at"] <= task["ended_at"]
        assert task["display_name"] in ("Prompt sess-a", "Prompt sess-b")
    assert "/srv/" not in response.text
