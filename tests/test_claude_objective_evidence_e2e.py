"""End to end: a Claude Code session, an accepted task, a passing test run.

The transcript adapter classifies the shell command as a TEST receipt, the
discovery engine proposes a candidate, a person accepts it, and the real
model-ensemble service (decoder 4, per-provider descriptor, Claude text
source) publishes outcome.first_pass_verification = 1/1 as an objective
receipt. Synthetic transcript in an isolated Claude home.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER
from prompt_enhancer.application.discovery import AcceptCandidate, TaskReviewService
from prompt_enhancer.application.discovery.contracts import TaskCategory
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.domain import DataTier, Provider
from prompt_enhancer.infrastructure.identifiers import LocalArtifactIdFactory


T0 = datetime(2026, 3, 2, 9, 0, tzinfo=UTC)
SESSION = "1d2e3f40-aaaa-4bbb-8ccc-000000000001"
CWD = "/srv/example/workspaces/e2e-demo"


def _row(kind: str, content: object, second: int) -> str:
    at = (T0 + timedelta(seconds=second)).isoformat().replace("+00:00", "Z")
    return json.dumps({"type": kind, "timestamp": at, "sessionId": SESSION, "cwd": CWD, "version": "2.1.0",
                       "message": {"role": kind, "content": content}})


def _write(claude_home: Path) -> None:
    project = claude_home / "projects" / "-srv-example-workspaces-e2e-demo"
    project.mkdir(parents=True, exist_ok=True)
    lines = [
        _row("user", "Please make the uploader retry three times and prove it with the tests.", 0),
        _row("assistant", [{"type": "text", "text": "I will add the retry and run the suite."},
                           {"type": "tool_use", "id": "toolu_1", "name": "Edit", "input": {"file_path": "/srv/example/uploader.py", "old_string": "x", "new_string": "y"}}], 5),
        _row("user", [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"}], 6),
        _row("assistant", [{"type": "tool_use", "id": "toolu_2", "name": "Bash", "input": {"command": "pytest tests/test_uploader.py -q"}}], 10),
        _row("user", [{"type": "tool_result", "tool_use_id": "toolu_2", "content": "3 passed", "is_error": False}], 20),
        _row("assistant", [{"type": "text", "text": "Done: three retries, and the three uploader tests pass."}], 25),
    ]
    (project / f"{SESSION}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_claude_session_with_accepted_task_publishes_first_pass_verification(tmp_path: Path, monkeypatch) -> None:
    claude_home = tmp_path / "claude-home"
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(claude_home))
    _write(claude_home)
    settings = AppSettings(home=tmp_path / "app")
    application = bootstrap_local_application(settings)
    database = application.database
    database.grant_consent(Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT)
    assert application.create_claude_local_source_service().index(max_sessions=10).sessions_seen == 1
    row = database.list_sessions(limit=5, offset=0)[0]
    assert row["provider"] == "claude_code"
    session_id = str(row["session_id"])

    # Propose and accept the task so the session has one current accepted revision.
    sessions = [database.get_session(session_id)]
    discovery = application.create_discovery_persistence_service().discover_and_persist(sessions)
    candidate = discovery.batch.candidates[0]
    identifiers = LocalArtifactIdFactory(application.pseudonymizer)
    review = TaskReviewService(database.task_repository(), identifiers).apply(
        AcceptCandidate(
            candidate_id=candidate.candidate_id,
            expected_discovery_version=candidate.discovery_version,
            task_category=TaskCategory.FEATURE_IMPLEMENTATION,
        ),
        idempotency_key="example-e2e-accept-1",
    )
    assert len(review.output_revisions) == 1
    assert len(database.task_repository().list_current_revisions_for_session(session_id)) == 1

    # The composed typed-evidence projector (decoder 4, Claude descriptor) turns
    # the classified test run into a verification receipt linked to the
    # accepted task, and the objective projection publishes 1/1.
    from prompt_enhancer.application.analysis.objective_metric_projection import (
        project_objective_metric_overrides_v3,
    )

    projector = application.create_typed_evidence_projector()
    projection = projector.project(provider=Provider.CLAUDE_CODE, session_id=session_id)
    assert projection is not None
    assert projection.provenance.provider is Provider.CLAUDE_CODE
    assert projection.provenance.adapter_version == "claude-code-transcripts-adapter-1"
    assert len(projection.eligible_verification_task_reference_ids) == 1
    overrides = project_objective_metric_overrides_v3(projection, projector.descriptor_for(Provider.CLAUDE_CODE))
    first_pass = overrides["outcome.first_pass_verification"]
    assert (first_pass.value_state.value, first_pass.numerator, first_pass.denominator) == ("known", 1, 1)
    assert first_pass.explanation_code == "typed_first_verification_outcomes"

    # Without an accepted task the same session declares no task family.
    other = application.create_typed_evidence_projector()
    database.task_repository()  # the repository is shared; simulate "no revision" via a fresh store below
    from prompt_enhancer.application.analysis.provider_evidence import SafeEventTypedEvidenceProjector

    class _NoTasks:
        def list_current_revisions_for_session(self, _session_id: str):
            return ()

    bare = SafeEventTypedEvidenceProjector(
        database,
        identifiers,
        other.descriptor,
        tasks=_NoTasks(),
        descriptors={Provider.CLAUDE_CODE: other.descriptor_for(Provider.CLAUDE_CODE)},
    ).project(provider=Provider.CLAUDE_CODE, session_id=session_id)
    assert bare is not None and bare.eligible_verification_task_reference_ids == ()
    bare_first = project_objective_metric_overrides_v3(bare, other.descriptor_for(Provider.CLAUDE_CODE))["outcome.first_pass_verification"]
    assert bare_first.value_state.value == "unknown"

    # The session-analysis routes resolve the session's provider instead of
    # assuming Codex: the preview for this Claude session is served (200) rather
    # than failing as an unknown Codex thread.
    client = TestClient(application.create_http_app(), base_url="http://127.0.0.1")
    headers = {API_TOKEN_HEADER: settings.api_token_path.read_text(encoding="utf-8").strip()}
    preview = client.post(
        f"/v1/sessions/{session_id}/quality-analysis-previews",
        headers=headers,
        json={"preset_id": "coaching_profile_v1"},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["binding"]["provider"] == "claude_code"


def test_p1_publication_preview_carries_objective_first_pass_for_claude(tmp_path: Path, monkeypatch) -> None:
    """The automatic P1 run's V2 preview shows first-pass 1/1 from evidence - no ensemble click."""

    from prompt_enhancer.application.analysis.session_text_service import SESSION_TEXT_ANALYSIS_CONFIRMATION
    from prompt_enhancer.application.analysis.text_analysis_presets import TextAnalysisPresetId
    from prompt_enhancer.application.providers import (
        CapabilityKey,
        ProviderSurface,
        ProviderSurfaceCompatibilityPolicy,
    )

    claude_home = tmp_path / "claude-home"
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(claude_home))
    _write(claude_home)
    settings = AppSettings(home=tmp_path / "app")
    application = bootstrap_local_application(settings)
    client = TestClient(application.create_http_app(), base_url="http://127.0.0.1")
    headers = {API_TOKEN_HEADER: settings.api_token_path.read_text(encoding="utf-8").strip()}
    # One consent: index, discovery and singleton auto-accept all happen here.
    assert client.post("/v1/onboarding/accept", headers=headers, json={"providers": ["claude_code"]}).status_code == 200
    session_id = str(application.database.list_sessions(limit=5, offset=0)[0]["session_id"])
    assert len(application.database.task_repository().list_current_revisions_for_session(session_id)) == 1

    catalog = application.create_provider_compatibility_catalog()
    catalog.refresh("claude_code", ProviderSurface.TEXT_WINDOW)
    policy = ProviderSurfaceCompatibilityPolicy(
        catalog,
        surface=ProviderSurface.TEXT_WINDOW,
        required_capabilities=(CapabilityKey.USER_MESSAGES, CapabilityKey.AGENT_MESSAGES, CapabilityKey.PLAN_MESSAGES),
    )
    outcome = application.create_session_text_analysis_service(policy).run_preset(
        provider=Provider.CLAUDE_CODE,
        session_id=session_id,
        preset_id=TextAnalysisPresetId.COACHING_PROFILE_V1,
        confirmation=SESSION_TEXT_ANALYSIS_CONFIRMATION,
        idempotency_key="example-e2e-p1-1",
    )
    preview = client.get(f"/v1/quality-analysis/runs/{outcome.run_id}/metric-v2-compatibility-preview", headers=headers)
    assert preview.status_code == 200, preview.text
    metrics = preview.json()["publication"]["metrics"]
    first_pass = next(item for item in metrics if item["state"]["metric_key"] == "outcome.first_pass_verification")
    assert first_pass["state"]["value_state"] == "known", first_pass
    assert (first_pass["state"]["numerator"], first_pass["state"]["denominator"]) == (1, 1)
    assert first_pass["state"]["evidence_authority"] == "objective_receipt"

    # The run detail and latest-run routes overlay the same objective value on the
    # result row, with typed-evidence provenance instead of the rubric's.
    for path in (f"/v1/quality-analysis/runs/{outcome.run_id}", f"/v1/sessions/{session_id}/quality-analysis-runs/latest"):
        detail = client.get(path, headers=headers)
        assert detail.status_code == 200, detail.text
        row = next(item for item in detail.json()["results"] if item["key"] == "outcome.first_pass_verification")
        assert row["value_state"] == "known" and row["fraction"] == {"numerator": 1, "denominator": 1}, row
        assert row["algorithm_id"] == "typed-objective-evidence"
        assert row["explanation_code"] == "typed_first_verification_outcomes"


def test_session_timeline_route_is_content_free_and_pairs_tools(tmp_path: Path, monkeypatch) -> None:
    claude_home = tmp_path / "claude-home"
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(claude_home))
    _write(claude_home)
    settings = AppSettings(home=tmp_path / "app")
    application = bootstrap_local_application(settings)
    application.database.grant_consent(Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT)
    application.create_claude_local_source_service().index(max_sessions=10)
    session_id = str(application.database.list_sessions(limit=5, offset=0)[0]["session_id"])
    client = TestClient(application.create_http_app(), base_url="http://127.0.0.1")
    headers = {API_TOKEN_HEADER: settings.api_token_path.read_text(encoding="utf-8").strip()}

    assert client.get(f"/v1/sessions/{session_id}/timeline").status_code == 401
    missing = client.get(f"/v1/sessions/{'f' * 64}/timeline", headers=headers)
    assert missing.status_code == 404
    response = client.get(f"/v1/sessions/{session_id}/timeline", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["contract_version"] == "session-timeline.v1" and body["provider"] == "claude_code"
    assert body["session_display_name"]  # title from the first prompt, nothing else textual
    assert body["counts"]["turns"] >= 1
    # Two tool spans: the Edit (file_write) and the pytest run (test, passed).
    categories = [(tool["category"], tool["verification"], tool["success"]) for tool in body["tools"]]
    assert ("file_write", False, None) in categories  # no is_error key -> outcome unknown, never assumed
    assert ("test", True, True) in categories
    assert body["counts"]["verifications_passed"] == 1 and body["counts"]["verifications_failed"] == 0
    assert all(tool["ended_at"] is not None for tool in body["tools"])
    # No prompt text, command text or path leaks into the timeline.
    text = response.text
    assert "pytest" not in text and "/srv/" not in text and "test_uploader" not in text  # the title keeps its first-prompt words; commands and paths never appear
