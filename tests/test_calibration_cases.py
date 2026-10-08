"""Known-answer reviewed cases, expiry, consent and atomic local persistence.

All sources below are isolated synthetic fixtures. No provider home is read.
"""
from contextlib import closing
from datetime import timedelta
import hashlib
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from prompt_enhancer.api import API_TOKEN_HEADER
from prompt_enhancer.application.analysis.calibration_cases import (
    CALIBRATION_CASE_VERSION, MAX_REVIEW_RECEIPTS, REVIEW_LIFETIME,
    CalibrationReviewError, CalibrationReviewService, prepare_calibration_case,
)
from prompt_enhancer.application.analysis.calibration_ratings import (
    CALIBRATION_METRIC_KEYS, CALIBRATION_RATING_VERSION, LEGACY_CALIBRATION_RATING_VERSION,
    RatingLabel, RatingSubmission,
)
from prompt_enhancer.application.analysis.model_judge import JUDGE_PROMPT_VERSION, render_window
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database, DatabaseError, _MIGRATION_1
from prompt_enhancer.domain import DataTier, Provider
from prompt_enhancer.infrastructure.sqlite import migrations
from prompt_enhancer.interfaces.http.browser_session import CSRF_HEADER
from tests.test_calibration_ratings import _transcript
from tests.test_structured_model_replies import NOW, SESSION, _window


def _case(**changes):
    return prepare_calibration_case(**{
        "session_id": SESSION, "provider": Provider.SYNTHETIC,
        "window_fingerprint": "b" * 64, "rendered_window": render_window(_window()), **changes,
    })


def _reviews(*, enabled=True, consent=True, clock=lambda: NOW, read_case=None, provider_for=None):
    return CalibrationReviewService(
        read_case=read_case or (lambda sid, _budget: _case(session_id=sid)),
        provider_for=provider_for or (lambda _sid: Provider.SYNTHETIC),
        has_consent=consent if callable(consent) else lambda _provider: consent,
        enabled=enabled, clock=clock,
    )


def test_case_identity_is_canonical_and_binds_every_evidence_dimension():
    case = _case()
    reordered = json.dumps(json.loads(render_window(_window())), indent=3, sort_keys=True)
    assert _case(rendered_window=reordered).case_fingerprint == case.case_fingerprint
    assert len({
        case.case_fingerprint, _case(session_id="e" * 64).case_fingerprint,
        _case(provider=Provider.CODEX).case_fingerprint,
        _case(window_fingerprint="f" * 64).case_fingerprint,
        _case(rendered_window=render_window(_window()).replace("example module", "example package")).case_fingerprint,
    }) == 5
    assert "example module" not in repr(case)


@pytest.mark.parametrize("defect", (
    "duplicate-key", "wrong-schema", "wrong-authority", "no-anchor", "empty", "duplicate-sequence",
    "nonuser-anchor", "boolean-sequence", "extra-record-field", "oversize", "missing-fingerprint",
))
def test_invalid_case_never_gets_a_fingerprint(defect):
    data = json.loads(render_window(_window()))
    fingerprint = "b" * 64
    if defect == "duplicate-key":
        rendered = render_window(_window()).replace('"available":true', '"available":false,"available":true')
    else:
        if defect == "wrong-schema": data["schema"] = "example-unknown-schema"
        elif defect == "wrong-authority": data["authority"] = "instructions"
        elif defect == "no-anchor": data["task_anchor_retained"] = False
        elif defect == "empty": data["records"] = []
        elif defect == "duplicate-sequence": data["records"].append(data["records"][0].copy())
        elif defect == "nonuser-anchor": data["records"][0]["role"] = "agent"
        elif defect == "boolean-sequence": data["records"][0]["sequence"] = True
        elif defect == "extra-record-field": data["records"][0]["extra"] = "example"
        elif defect == "oversize": data["records"][0]["content"] = "example " * 3_000
        elif defect == "missing-fingerprint": fingerprint = "0" * 64
        rendered = json.dumps(data)
    with pytest.raises(CalibrationReviewError, match="^calibration_window_unavailable$"):
        _case(rendered_window=rendered, window_fingerprint=fingerprint)


@pytest.mark.parametrize("blocked", ("disabled", "no-consent", "consent-error", "unknown-session"))
def test_review_authorizes_before_any_source_read(blocked):
    def consent(_provider):
        if blocked == "consent-error": raise RuntimeError("synthetic detail must not leak")
        return blocked != "no-consent"
    service = _reviews(
        enabled=blocked != "disabled", consent=consent,
        provider_for=lambda _sid: None if blocked == "unknown-session" else Provider.SYNTHETIC,
        read_case=lambda *_args: pytest.fail("no source read is authorized"),
    )
    with pytest.raises(CalibrationReviewError) as error:
        service.issue(SESSION)
    assert "synthetic detail" not in str(error.value)
    assert service._receipts == {}


def test_receipts_are_ephemeral_bounded_metadata_and_fail_closed():
    now = [NOW]
    consent = [True]
    service = _reviews(clock=lambda: now[0], consent=lambda _provider: consent[0])
    first = service.issue(SESSION)
    assert service.resolve(first.review_id, SESSION).case_fingerprint == first.case_fingerprint
    assert first.expires_at == NOW + REVIEW_LIFETIME
    assert not first.persisted and first.local_only
    assert "example module" not in repr(service._receipts)
    with pytest.raises(CalibrationReviewError, match="^calibration_review_mismatch$"):
        service.resolve(first.review_id, "e" * 64)
    with pytest.raises(CalibrationReviewError, match="^calibration_review_missing$"):
        _reviews().resolve(first.review_id, SESSION)
    consent[0] = False
    with pytest.raises(CalibrationReviewError, match="^calibration_review_consent_required$"):
        service.resolve(first.review_id, SESSION)
    consent[0] = True
    now[0] += REVIEW_LIFETIME
    with pytest.raises(CalibrationReviewError, match="^calibration_review_expired$"):
        service.resolve(first.review_id, SESSION)
    for _ in range(MAX_REVIEW_RECEIPTS + 1): service.issue(SESSION)
    assert len(service._receipts) == MAX_REVIEW_RECEIPTS
    with pytest.raises(CalibrationReviewError, match="^calibration_review_missing$"):
        service.resolve(first.review_id, SESSION)


def test_receipt_keeps_the_case_that_was_shown_not_a_later_source_read():
    cases = iter((_case(), _case(window_fingerprint="e" * 64)))
    service = _reviews(read_case=lambda *_args: next(cases))
    old = service.issue(SESSION)
    new = service.issue(SESSION)
    assert old.case_fingerprint != new.case_fingerprint
    assert service.resolve(old.review_id, SESSION).case_fingerprint == old.case_fingerprint
    assert service.resolve(new.review_id, SESSION).case_fingerprint == new.case_fingerprint


@pytest.mark.parametrize("defect", ("foreign-session", "foreign-provider", "consent-revoked-during-read"))
def test_review_rechecks_source_ownership_and_consent_after_read(defect):
    consent = [True]
    def read_case(*_args):
        if defect == "consent-revoked-during-read": consent[0] = False
        return _case(**({"session_id": "e" * 64} if defect == "foreign-session" else {"provider": Provider.CODEX} if defect == "foreign-provider" else {}))
    service = _reviews(consent=lambda _provider: consent[0], read_case=read_case)
    with pytest.raises(CalibrationReviewError): service.issue(SESSION)
    assert service._receipts == {}


def _application(tmp_path, monkeypatch):
    source = tmp_path / "example-provider"
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(source))
    _transcript(source, "example-session", 0)
    settings = AppSettings(home=tmp_path / "example-application", session_reader_enabled=True)
    application = bootstrap_local_application(settings)
    application.database.grant_consent(Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT)
    application.create_claude_local_source_service().index(max_sessions=1)
    return application


def test_bound_ratings_roundtrip_export_and_batch_failure_are_atomic(tmp_path, monkeypatch):
    application = _application(tmp_path, monkeypatch)
    service = application.create_calibration_rating_service()
    sid = service.sample().members[0].session_id
    review = service.review(sid)
    labels = {key: RatingLabel.HIGH for key in CALIBRATION_METRIC_KEYS}
    service.rate(RatingSubmission(rater_label="Example rater", session_id=sid, ratings=labels, review_id=review.review_id))
    original = service.ratings_for("Example rater")
    assert len(original) == 3
    assert {row.rating_version for row in original} == {CALIBRATION_RATING_VERSION}
    assert {row.case_fingerprint for row in original} == {review.case_fingerprint}
    assert {row.window_fingerprint for row in original} == {review.window_fingerprint}
    assert all(row.revision == 1 for row in original)
    assert service.export().rows[0].case_fingerprint == review.case_fingerprint
    assert "Prompt for" not in service.export().model_dump_json()
    with application.database._connection() as connection:
        connection.execute("CREATE TRIGGER example_rating_failure BEFORE INSERT ON calibration_ratings WHEN NEW.metric_key = 'outcome.verification_strategy_adequacy' BEGIN SELECT RAISE(ABORT, 'synthetic storage failure'); END")
        connection.commit()
    with pytest.raises(DatabaseError, match="^local database operation failed$"):
        service.rate(RatingSubmission(rater_label="Example rater", session_id=sid, ratings={key: RatingLabel.LOW for key in labels}, review_id=review.review_id))
    assert service.ratings_for("Example rater") == original
    assert application.create_calibration_rating_service().ratings_for("Example rater") == original


def test_http_review_is_authenticated_local_no_store_and_receipt_bound(tmp_path, monkeypatch):
    application = _application(tmp_path, monkeypatch)
    sid = application.create_calibration_rating_service().sample().members[0].session_id
    headers = {API_TOKEN_HEADER: application.settings.api_token_path.read_text().strip()}
    with TestClient(application.create_http_app(), base_url="http://127.0.0.1") as client:
        request = {"session_id": sid, "window_characters": 15000}
        assert client.post("/v1/calibration/review", json=request).status_code == 401
        result = client.post("/v1/calibration/review", json=request, headers=headers)
        assert result.status_code == 200
        assert result.headers["cache-control"] == "no-store, private"
        assert result.headers["pragma"] == "no-cache"
        case = result.json()
        assert case["records"][0]["role"] == "user" and case["case_version"] == CALIBRATION_CASE_VERSION
        body = {"session_id": sid, "rater_label": "Example rater", "ratings": {CALIBRATION_METRIC_KEYS[0]: "high"}, "review_id": case["review_id"]}
        assert client.put("/v1/calibration/ratings", headers=headers, json=body).status_code == 200
        bad = client.put("/v1/calibration/ratings", headers=headers, json={**body, "review_id": "0" * 32})
        assert bad.status_code == 409 and bad.json()["detail"]["code"] == "calibration_review_missing"
        rows = client.get("/v1/calibration/ratings?rater_label=Example%20rater", headers=headers).json()
        assert rows[0]["case_fingerprint"] == case["case_fingerprint"] and rows[0]["revision"] == 1
        assert client.post("/v1/calibration/review", headers=headers, json={**request, "window_characters": 100000}).status_code == 422
        assert client.post("/v1/calibration/review", headers=headers, json={**request, "session_id": "e" * 64}).status_code == 422


def test_browser_review_and_rating_require_same_origin_csrf_without_reading_on_denial(tmp_path, monkeypatch):
    application = _application(tmp_path, monkeypatch)
    sid = application.create_calibration_rating_service().sample().members[0].session_id
    observed = []
    original = CalibrationReviewService.issue

    def record_issue(self, session_id, window_characters=15000):
        observed.append(session_id)
        return original(self, session_id, window_characters)

    monkeypatch.setattr(CalibrationReviewService, "issue", record_issue)
    with TestClient(application.create_http_app(), base_url="http://127.0.0.1") as client:
        csrf = client.get("/auth/session").json()["csrf_token"]
        headers = {"Origin": "http://127.0.0.1", CSRF_HEADER: csrf}
        request = {"session_id": sid, "window_characters": 6000}
        for invalid_headers in (
            {}, {"Origin": "http://127.0.0.1"},
            {**headers, "Origin": "https://example.invalid"},
            {**headers, CSRF_HEADER: "example-invalid-proof"},
        ):
            denied = client.post("/v1/calibration/review", headers=invalid_headers, json=request)
            assert denied.status_code == 403
            assert observed == []
            assert denied.headers["cache-control"] == "no-store, private"
        result = client.post("/v1/calibration/review", headers=headers, json=request)
        assert result.status_code == 200 and observed == [sid]
        assert result.headers["cache-control"] == "no-store, private"
        assert result.headers["pragma"] == "no-cache"
        case = result.json()
        body = {"session_id": sid, "rater_label": "Example rater", "ratings": {CALIBRATION_METRIC_KEYS[0]: "high"}, "review_id": case["review_id"]}
        assert client.put("/v1/calibration/ratings", headers={"Origin": "http://127.0.0.1"}, json=body).status_code == 403
        assert client.get("/v1/calibration/ratings?rater_label=Example%20rater").json() == []
        assert client.put("/v1/calibration/ratings", headers=headers, json=body).status_code == 200
        rows = client.get("/v1/calibration/ratings?rater_label=Example%20rater").json()
        assert len(rows) == 1 and rows[0]["case_fingerprint"] == case["case_fingerprint"]


def test_v60_migration_keeps_historical_labels_unbound_without_backfilling(tmp_path):
    path = tmp_path / "example-calibration.sqlite3"
    scripts = (_MIGRATION_1,) + tuple(getattr(migrations, f"MIGRATION_{version}") for version in range(2, 61))
    stamp = NOW.isoformat()
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for script in scripts: connection.executescript(script)
        connection.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)")
        connection.executemany("INSERT INTO schema_migrations VALUES(?,?,?)", [(version, hashlib.sha256(script.encode()).hexdigest(), stamp) for version, script in enumerate(scripts, 1)])
        connection.execute("INSERT INTO installations VALUES(?,?,?)", ("1" * 64, "synthetic", stamp))
        connection.execute("INSERT INTO projects(project_id,installation_id,provider,created_at) VALUES(?,?,?,?)", ("2" * 64, "1" * 64, "synthetic", stamp))
        connection.execute("INSERT INTO sessions(session_id,installation_id,project_id,provider,provider_version,adapter_version,source_schema_version,started_at,terminal_state,events_complete,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (SESSION, "1" * 64, "2" * 64, "synthetic", "example-v1", "example-v1", "example-v1", stamp, "completed", 1, stamp, stamp))
        connection.execute("INSERT INTO calibration_ratings VALUES(?,?,?,?,?,?,?)", ("3" * 64, SESSION, CALIBRATION_METRIC_KEYS[0], "high", LEGACY_CALIBRATION_RATING_VERSION, stamp, 2))
        connection.execute("INSERT INTO model_judgments VALUES(?,?,?,?,?,?,?,?)", (SESSION, CALIBRATION_METRIC_KEYS[0], "example-model", "high", "example-model.gguf", JUDGE_PROMPT_VERSION, "b" * 64, stamp))
        connection.execute("PRAGMA user_version=60")
        connection.commit()
    database = Database(path)
    database.initialize()
    database.initialize()
    rating = database.calibration_rating_repository().list_ratings()[0]
    judgment = database.model_judgment_repository().list()[0]
    assert rating.label is judgment.label is RatingLabel.HIGH
    assert rating.revision == 2 and rating.rating_version == LEGACY_CALIBRATION_RATING_VERSION
    assert rating.case_fingerprint is rating.window_fingerprint is rating.case_version is None
    assert judgment.case_fingerprint is judgment.case_version is None
    assert judgment.window_fingerprint == "b" * 64
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
