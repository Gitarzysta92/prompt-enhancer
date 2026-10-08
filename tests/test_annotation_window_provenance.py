"""Provenance of annotation-written model judgments (ADR 0017, ADR 0013 section 4).

Both annotation write paths - the agent surface and the central round trip -
used to store the reserved all-zero ``window_fingerprint``, which claims a
window no source ever sealed. These tests pin the sealed fingerprint end to end
and the fail-closed behaviour around it. Everything here is synthetic: fictional
session ids, a fictional project path, and one invented sentence of transcript.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.analysis.calibration_ratings import (
    CALIBRATION_METRIC_KEYS,
    RatingLabel,
)
from prompt_enhancer.application.analysis.model_judge import (
    ZERO_WINDOW_FINGERPRINT,
    ModelJudgment,
    rehydrate_persisted_judgment,
)
from prompt_enhancer.application.annotation import (
    CentralAnnotation,
    CentralBatchResult,
    RemoteAnnotationClient,
    RemoteSubmitRequest,
)

from tests.test_annotation import _bootstrap


_AGENT = "example-agent"
_ALIAS = f"agent:{_AGENT}"
_LABELS = {key: "medium" for key in CALIBRATION_METRIC_KEYS}
_EXAMPLE_FINGERPRINT = "b" * 64
_UNSEALED_SESSION = "c" * 64
_PROJECT_DIRECTORY = "-srv-example-annotate"


def _allow(client, headers) -> None:
    response = client.post("/v1/annotation/allowance", headers=headers, json={"agent_allowed": True})
    assert response.status_code == 200, response.text


def _work_items(client, headers) -> list[dict]:
    response = client.get(f"/v1/annotation/work?model={_AGENT}", headers=headers)
    assert response.status_code == 200, response.text
    return list(response.json()["items"])


def _window(client, headers, session_id: str) -> dict:
    response = client.get(f"/v1/annotation/work/{session_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _submit(client, headers, session_id: str, fingerprint: str, labels: dict[str, str] | None = None):
    return client.post(
        "/v1/annotation/annotations",
        headers=headers,
        json={
            "session_id": session_id,
            "model_name": _AGENT,
            "window_fingerprint": fingerprint,
            "labels": dict(labels or _LABELS),
        },
    )


def _grow_every_session(tmp_path: Path) -> None:
    """Append one synthetic turn to each transcript, moving the sealed window.

    The source reads the transcript when the window is requested, so the next
    read seals a different window without any re-index step.
    """

    project = tmp_path / "claude-home" / "projects" / _PROJECT_DIRECTORY
    at = datetime(2026, 1, 2, tzinfo=UTC).isoformat().replace("+00:00", "Z")
    for path in sorted(project.glob("*.jsonl")):
        first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "type": "user",
                        "message": {"role": "user", "content": "Also add a regression test for the retry backoff."},
                        "timestamp": at,
                        "sessionId": first["sessionId"],
                        "cwd": "/srv/example/annotate",
                        "version": "2.1.0",
                    }
                )
                + "\n"
            )


def _stored_fingerprints(settings, session_id: str, alias: str) -> set[str]:
    """Read the persisted column directly, outside the repository's rehydration."""

    with sqlite3.connect(settings.database_path) as connection:
        rows = connection.execute(
            "SELECT window_fingerprint FROM model_judgments WHERE session_id = ? AND model_alias = ?",
            (session_id, alias),
        ).fetchall()
    return {value for (value,) in rows}


# ----- Path A: the agent surface -----


def test_agent_path_persists_the_sealed_window_fingerprint(tmp_path: Path, monkeypatch) -> None:
    """The persisted column, the rehydrated record, and the API window all agree."""

    application, settings, client, headers = _bootstrap(tmp_path, monkeypatch)
    _allow(client, headers)
    session_id = _work_items(client, headers)[0]["session_id"]
    handed_out = _window(client, headers, session_id)["window_fingerprint"]
    assert handed_out != ZERO_WINDOW_FINGERPRINT and len(handed_out) == 64

    assert _submit(client, headers, session_id, handed_out).status_code == 201

    assert _stored_fingerprints(settings, session_id, _ALIAS) == {handed_out}

    stored = application.database.model_judgment_repository().list(session_id=session_id, model_alias=_ALIAS)
    assert len(stored) == len(CALIBRATION_METRIC_KEYS)
    assert {judgment.window_fingerprint for judgment in stored} == {handed_out}


def test_agent_path_replay_is_idempotent_and_keeps_one_fingerprint(tmp_path: Path, monkeypatch) -> None:
    application, settings, client, headers = _bootstrap(tmp_path, monkeypatch)
    _allow(client, headers)
    session_id = _work_items(client, headers)[0]["session_id"]
    fingerprint = _window(client, headers, session_id)["window_fingerprint"]

    assert _submit(client, headers, session_id, fingerprint).status_code == 201
    assert _submit(client, headers, session_id, fingerprint).status_code == 201

    stored = application.database.model_judgment_repository().list(session_id=session_id, model_alias=_ALIAS)
    assert len(stored) == len(CALIBRATION_METRIC_KEYS)
    assert _stored_fingerprints(settings, session_id, _ALIAS) == {fingerprint}


def test_agent_path_rejects_labels_for_a_window_that_has_changed(tmp_path: Path, monkeypatch) -> None:
    """A session that grew after the agent read it seals to a different window."""

    application, _settings, client, headers = _bootstrap(tmp_path, monkeypatch)
    _allow(client, headers)
    session_id = _work_items(client, headers)[0]["session_id"]
    stale = _window(client, headers, session_id)["window_fingerprint"]

    _grow_every_session(tmp_path)
    current = _window(client, headers, session_id)["window_fingerprint"]
    assert current != stale, "the grown window must seal to a new identity"

    refused = _submit(client, headers, session_id, stale)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "window_fingerprint_mismatch"
    repository = application.database.model_judgment_repository()
    assert not repository.list(session_id=session_id, model_alias=_ALIAS)

    # Re-reading and judging the new window is accepted, and names that window.
    assert _submit(client, headers, session_id, current).status_code == 201
    assert {j.window_fingerprint for j in repository.list(session_id=session_id, model_alias=_ALIAS)} == {current}


def test_agent_path_rejects_reserved_malformed_and_foreign_fingerprints(tmp_path: Path, monkeypatch) -> None:
    application, _settings, client, headers = _bootstrap(tmp_path, monkeypatch)
    _allow(client, headers)
    session_id = _work_items(client, headers)[0]["session_id"]

    reserved = _submit(client, headers, session_id, ZERO_WINDOW_FINGERPRINT)
    assert reserved.status_code == 422 and reserved.json()["detail"]["code"] == "window_fingerprint_invalid"

    for malformed in ("", "not-hex", "B" * 64, "b" * 63, "b" * 65):
        assert _submit(client, headers, session_id, malformed).status_code == 422, malformed

    # Well formed, but not the fingerprint of this session's window.
    foreign = _submit(client, headers, session_id, _EXAMPLE_FINGERPRINT)
    assert foreign.status_code == 409 and foreign.json()["detail"]["code"] == "window_fingerprint_mismatch"

    # An omitted fingerprint is a contract error, never a silent zero.
    absent = client.post(
        "/v1/annotation/annotations",
        headers=headers,
        json={"session_id": session_id, "model_name": _AGENT, "labels": dict(_LABELS)},
    )
    assert absent.status_code == 422

    assert not application.database.model_judgment_repository().list(session_id=session_id)


def test_window_fingerprint_of_a_second_session_does_not_carry_over(tmp_path: Path, monkeypatch) -> None:
    """Each session's labels are bound to that session's own sealed window."""

    application, _settings, client, headers = _bootstrap(tmp_path, monkeypatch)
    _allow(client, headers)
    items = _work_items(client, headers)
    assert len(items) >= 2
    first, second = items[0]["session_id"], items[1]["session_id"]
    first_fingerprint = _window(client, headers, first)["window_fingerprint"]
    second_fingerprint = _window(client, headers, second)["window_fingerprint"]
    assert first_fingerprint != second_fingerprint

    crossed = _submit(client, headers, second, first_fingerprint)
    assert crossed.status_code == 409 and crossed.json()["detail"]["code"] == "window_fingerprint_mismatch"

    assert _submit(client, headers, first, first_fingerprint).status_code == 201
    assert _submit(client, headers, second, second_fingerprint).status_code == 201
    repository = application.database.model_judgment_repository()
    assert {j.window_fingerprint for j in repository.list(session_id=first, model_alias=_ALIAS)} == {first_fingerprint}
    assert {j.window_fingerprint for j in repository.list(session_id=second, model_alias=_ALIAS)} == {second_fingerprint}


# ----- domain and persistence guards -----


def _judgment_fields() -> dict[str, object]:
    return {
        "session_id": "a" * 64,
        "metric_key": CALIBRATION_METRIC_KEYS[0],
        "label": RatingLabel.MEDIUM,
        "model_alias": _ALIAS,
        "model_identity": _AGENT,
        "prompt_version": "judge-v1",
        "judged_at": datetime(2026, 1, 1, tzinfo=UTC),
    }


def test_model_judgment_refuses_the_reserved_fingerprint_but_legacy_rows_stay_readable() -> None:
    fields = _judgment_fields()

    with pytest.raises(ValidationError):
        ModelJudgment(**fields, window_fingerprint=ZERO_WINDOW_FINGERPRINT)
    assert ModelJudgment(**fields, window_fingerprint=_EXAMPLE_FINGERPRINT).window_fingerprint == _EXAMPLE_FINGERPRINT

    # Rows written before this rule stay readable and keep the value they were
    # written with: absent provenance is shown, never quietly back-filled.
    legacy = rehydrate_persisted_judgment({**fields, "window_fingerprint": ZERO_WINDOW_FINGERPRINT})
    assert legacy.window_fingerprint == ZERO_WINDOW_FINGERPRINT
    # The exemption is opt-in per read; plain validation still fails closed.
    with pytest.raises(ValidationError):
        ModelJudgment.model_validate({**fields, "window_fingerprint": ZERO_WINDOW_FINGERPRINT})


def test_repository_reads_legacy_rows_but_refuses_to_write_the_reserved_value(tmp_path: Path, monkeypatch) -> None:
    application, settings, client, headers = _bootstrap(tmp_path, monkeypatch)
    _allow(client, headers)
    session_id = _work_items(client, headers)[0]["session_id"]
    fingerprint = _window(client, headers, session_id)["window_fingerprint"]
    assert _submit(client, headers, session_id, fingerprint).status_code == 201
    repository = application.database.model_judgment_repository()

    # Stand in for a row written by the pre-fix annotation code.
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            "UPDATE model_judgments SET window_fingerprint = ? WHERE session_id = ? AND metric_key = ?",
            (ZERO_WINDOW_FINGERPRINT, session_id, CALIBRATION_METRIC_KEYS[0]),
        )
        connection.commit()

    stored = repository.list(session_id=session_id, model_alias=_ALIAS)
    assert {j.window_fingerprint for j in stored} == {ZERO_WINDOW_FINGERPRINT, fingerprint}

    # Reading it is allowed; writing it back out is not.
    legacy = next(j for j in stored if j.window_fingerprint == ZERO_WINDOW_FINGERPRINT)
    with pytest.raises(ValueError):
        repository.upsert(legacy)


# ----- Path B: the central round trip -----


def test_central_round_trip_records_the_window_it_actually_sealed(tmp_path: Path, monkeypatch) -> None:
    application, _settings, client, headers = _bootstrap(tmp_path, monkeypatch)
    _allow(client, headers)
    expected = {
        item["session_id"]: _window(client, headers, item["session_id"])["window_fingerprint"]
        for item in _work_items(client, headers)
    }

    weights = tmp_path / "tiny.gguf"
    weights.write_bytes(b"GGUF" + b"\0" * 4092)
    assert client.post("/v1/local-models", headers=headers, json={"alias": "stub-central", "path": str(weights)}).status_code == 201
    assert client.post("/v1/local-models/stub-central/activate", headers=headers, json={"device": "cpu"}).status_code == 200
    try:
        result = client.post("/v1/annotation/remote/submit", headers=headers, json={"limit": 2})
        assert result.status_code == 200, result.text
        assert result.json()["stored_locally_as"] == "central:stub-central"
    finally:
        client.post("/v1/local-models/stub-central/deactivate", headers=headers)

    stored = application.database.model_judgment_repository().list(model_alias="central:stub-central")
    assert stored
    for judgment in stored:
        assert judgment.window_fingerprint == expected[judgment.session_id]
        assert judgment.window_fingerprint != ZERO_WINDOW_FINGERPRINT


def test_central_labels_for_a_session_this_run_never_sealed_are_not_recorded(tmp_path: Path, monkeypatch) -> None:
    """A central reply naming an unsent session stores nothing locally."""

    application, _settings, client, headers = _bootstrap(tmp_path, monkeypatch)
    _allow(client, headers)
    service, _central, _remote = application.create_annotation_services()
    repository = application.database.model_judgment_repository()
    sent: list[str] = []

    def _impostor(batch) -> CentralBatchResult:
        assert batch.items, "the client must still seal and send real windows"
        sent.extend(item.session_id for item in batch.items)
        return CentralBatchResult(
            stored=1,
            annotations=(
                CentralAnnotation(
                    session_id=_UNSEALED_SESSION,
                    labels={key: RatingLabel.HIGH for key in CALIBRATION_METRIC_KEYS},
                ),
            ),
            model_identity="example-central",
        )

    remote = RemoteAnnotationClient(
        service,
        submit=_impostor,
        destination="synthetic central server (test)",
        user_label="example-owner",
        list_sessions=application.database.list_sessions,
    )
    outcome = remote.submit_batch(RemoteSubmitRequest(limit=2))

    assert sent and _UNSEALED_SESSION not in sent
    assert outcome.submitted > 0
    assert outcome.stored_locally_as is None
    assert not repository.list(model_alias="central:example-central")
    assert not repository.list(session_id=_UNSEALED_SESSION)
