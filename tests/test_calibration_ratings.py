"""Blind calibration ratings: frozen sample, upsert, progress, export, HTTP.

Synthetic sessions only, in an isolated application home.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER
from prompt_enhancer.application.analysis.calibration_ratings import (
    CALIBRATION_METRIC_KEYS,
    CalibrationRatingService,
    RatingLabel,
    RatingSubmission,
    stratified_selection,
)
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.domain import DataTier, Provider


T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def _transcript(claude_home: Path, session: str, minute: int) -> None:
    project = claude_home / "projects" / "-srv-example-calib"
    project.mkdir(parents=True, exist_ok=True)
    at = (T0 + timedelta(minutes=minute)).isoformat().replace("+00:00", "Z")
    lines = [
        json.dumps({"type": "user", "message": {"role": "user", "content": f"Prompt for {session}"}, "timestamp": at, "sessionId": session, "cwd": "/srv/example/calib", "version": "2.1.0"}),
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Done."}]}, "timestamp": at, "sessionId": session, "cwd": "/srv/example/calib", "version": "2.1.0"}),
    ]
    (project / f"{session}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_stratified_selection_is_deterministic_and_round_robin() -> None:
    rows = [{"session_id": f"{i:064x}", "provider": "codex" if i % 3 else "claude_code"} for i in range(1, 31)]
    first = stratified_selection(rows, size=8)
    second = stratified_selection(list(reversed(rows)), size=8)
    assert [row["session_id"] for row in first] == [row["session_id"] for row in second]
    providers = [row["provider"] for row in first]
    # Both providers are represented and alternate while both have members.
    assert providers[:4] == ["claude_code", "codex", "claude_code", "codex"]
    assert stratified_selection(rows, size=100) == stratified_selection(rows, size=100)
    assert len(stratified_selection(rows, size=100)) == 30


def test_service_freezes_sample_and_records_ratings(tmp_path: Path, monkeypatch) -> None:
    claude_home = tmp_path / "claude-home"
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(claude_home))
    for index in range(5):
        _transcript(claude_home, f"sess-{index}", index)
    application = bootstrap_local_application(AppSettings(home=tmp_path / "app"))
    application.database.grant_consent(Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT)
    assert application.create_claude_local_source_service().index(max_sessions=50).sessions_seen == 5

    service = CalibrationRatingService(
        application.database,
        application.database.calibration_rating_repository(),
        application.pseudonymizer,
        sample_size=3,
        clock=lambda: T0,
    )
    sample = service.sample()
    assert len(sample.members) == 3 and sample.target_size == 3
    assert sample.metric_keys == CALIBRATION_METRIC_KEYS
    assert all(member.provider is Provider.CLAUDE_CODE for member in sample.members)
    assert all(member.session_display_name for member in sample.members)
    # Frozen once full: a second call (even after more sessions exist) returns the same sample.
    _transcript(claude_home, "sess-late", 99)
    application.create_claude_local_source_service().index(max_sessions=50)
    assert service.sample().sample_id == sample.sample_id
    assert [m.session_id for m in service.sample().members] == [m.session_id for m in sample.members]

    target = sample.members[0].session_id
    progress = service.rate(
        RatingSubmission(
            rater_label="Owner",
            session_id=target,
            ratings={CALIBRATION_METRIC_KEYS[0]: RatingLabel.HIGH, CALIBRATION_METRIC_KEYS[1]: RatingLabel.CANNOT_JUDGE},
        )
    )
    assert progress.rated_sessions == 1 and progress.rater_count == 1 and progress.sample_size == 3
    assert progress.metrics[0].high == 1 and progress.metrics[1].cannot_judge == 1 and progress.metrics[2].rated_sessions == 0
    # Re-rating the same metric replaces the label and bumps the revision; the rater is a pseudonym.
    service.rate(RatingSubmission(rater_label="Owner", session_id=target, ratings={CALIBRATION_METRIC_KEYS[0]: RatingLabel.LOW}))
    ratings = service.ratings_for("Owner")
    first = next(r for r in ratings if r.metric_key == CALIBRATION_METRIC_KEYS[0])
    assert first.label is RatingLabel.LOW and first.revision == 2
    assert first.rater_id != "Owner" and len(first.rater_id) == 64
    assert service.ratings_for("Someone else") == ()
    # Sample view for a rater marks which metrics they already rated.
    view = service.sample(rater_label="Owner")
    assert view.members[0].rated_metric_keys == tuple(sorted((CALIBRATION_METRIC_KEYS[0], CALIBRATION_METRIC_KEYS[1])))
    assert view.members[1].rated_metric_keys == ()

    export = service.export()
    assert export.sample_id == sample.sample_id and len(export.rows) == 2
    dumped = export.model_dump_json()
    assert "Owner" not in dumped and "Prompt for" not in dumped and "Done." not in dumped

    try:
        service.rate(RatingSubmission(rater_label="Owner", session_id="f" * 64, ratings={CALIBRATION_METRIC_KEYS[0]: RatingLabel.LOW}))
    except ValueError as error:
        assert "not part" in str(error)
    else:
        raise AssertionError("expected rejection for an unsampled session")


def test_http_calibration_routes(tmp_path: Path, monkeypatch) -> None:
    claude_home = tmp_path / "claude-home"
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(claude_home))
    settings = AppSettings(home=tmp_path / "app")
    application = bootstrap_local_application(settings)
    client = TestClient(application.create_http_app(), base_url="http://127.0.0.1")
    headers = {API_TOKEN_HEADER: settings.api_token_path.read_text(encoding="utf-8").strip()}

    assert client.get("/v1/calibration/sample").status_code == 401
    empty = client.get("/v1/calibration/sample", headers=headers)
    assert empty.status_code == 409 and empty.json()["detail"]["code"] == "calibration_sample_empty"

    _transcript(claude_home, "sess-a", 1)
    _transcript(claude_home, "sess-b", 2)
    accepted = client.post("/v1/onboarding/accept", headers=headers, json={"providers": ["claude_code"]})
    assert accepted.status_code == 200, accepted.text

    sample = client.get("/v1/calibration/sample?rater_label=Owner", headers=headers)
    assert sample.status_code == 200, sample.text
    body = sample.json()
    assert body["contract_version"] == "calibration-ratings.v1" and len(body["members"]) == 2
    session_id = body["members"][0]["session_id"]
    rated = client.put(
        "/v1/calibration/ratings",
        headers=headers,
        json={"rater_label": "Owner", "session_id": session_id, "ratings": {"prompt.task_definition_coverage": "medium"}},
    )
    assert rated.status_code == 200, rated.text
    assert rated.json()["rated_sessions"] == 1
    bad = client.put(
        "/v1/calibration/ratings",
        headers=headers,
        json={"rater_label": "Owner", "session_id": session_id, "ratings": {"not.a.metric": "medium"}},
    )
    assert bad.status_code == 422
    mine = client.get("/v1/calibration/ratings?rater_label=Owner", headers=headers).json()
    assert len(mine) == 1 and mine[0]["label"] == "medium"
    progress = client.get("/v1/calibration/progress", headers=headers).json()
    assert progress["sample_size"] == 2 and progress["rater_count"] == 1
    export = client.get("/v1/calibration/export", headers=headers)
    assert export.status_code == 200 and len(export.json()["rows"]) == 1
    assert "Owner" not in export.text


def test_under_filled_unrated_sample_is_redrawn_when_more_sessions_arrive(tmp_path: Path, monkeypatch) -> None:
    """A sample drawn before a second provider was loaded must not stay Codex-only forever."""

    claude_home = tmp_path / "claude-home"
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(claude_home))
    _transcript(claude_home, "sess-0", 0)
    application = bootstrap_local_application(AppSettings(home=tmp_path / "app"))
    application.database.grant_consent(Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT)
    application.create_claude_local_source_service().index(max_sessions=50)
    service = CalibrationRatingService(
        application.database,
        application.database.calibration_rating_repository(),
        application.pseudonymizer,
        sample_size=4,
        clock=lambda: T0,
    )
    first = service.sample()
    assert len(first.members) == 1 and first.target_size == 4

    # More sessions appear; nothing rated yet -> the sample grows towards its target.
    for index in range(1, 6):
        _transcript(claude_home, f"sess-{index}", index)
    application.create_claude_local_source_service().index(max_sessions=50)
    grown = service.sample()
    assert len(grown.members) == 4 and grown.sample_id != first.sample_id

    # Once a rating exists the sample is frozen even if more sessions arrive.
    service.rate(RatingSubmission(rater_label="Owner", session_id=grown.members[0].session_id, ratings={CALIBRATION_METRIC_KEYS[0]: RatingLabel.LOW}))
    small = CalibrationRatingService(
        application.database, application.database.calibration_rating_repository(), application.pseudonymizer, sample_size=8, clock=lambda: T0,
    )
    assert small.sample().sample_id == grown.sample_id
    assert len(small.sample().members) == 4
