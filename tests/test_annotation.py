"""Annotation paths (ADR 0017): the agent surface behind the allowance switch, and
the central annotation server with its own dataset store."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER
from prompt_enhancer.application.analysis.calibration_ratings import CALIBRATION_METRIC_KEYS
from prompt_enhancer.application.analysis.model_judge import (
    JUDGE_PROMPT_VERSION,
    JUDGE_WINDOW_SCHEMA_VERSION,
)
from prompt_enhancer.application.local_models import HardwareSummary
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings

from tests.test_model_judge import STUB, T0


def _transcripts(claude_home: Path, sessions: tuple[str, ...]) -> None:
    project = claude_home / "projects" / "-srv-example-annotate"
    project.mkdir(parents=True, exist_ok=True)
    for index, session in enumerate(sessions):
        at = (T0 + timedelta(minutes=index)).isoformat().replace("+00:00", "Z")
        lines = [
            json.dumps({"type": "user", "message": {"role": "user", "content": f"Please tighten the retry policy in module {index} and run the tests."}, "timestamp": at, "sessionId": session, "cwd": "/srv/example/annotate", "version": "2.1.0"}),
            json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Done; tests pass."}]}, "timestamp": at, "sessionId": session, "cwd": "/srv/example/annotate", "version": "2.1.0"}),
        ]
        (project / f"{session}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _bootstrap(tmp_path: Path, monkeypatch):
    claude_home = tmp_path / "claude-home"
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(claude_home))
    _transcripts(claude_home, ("annotate-a", "annotate-b"))
    stub = tmp_path / "stub.py"
    stub.write_text(STUB, encoding="utf-8")
    monkeypatch.setenv("PROMPT_ENHANCER_LLAMA_SERVER", str(stub))
    settings = AppSettings(home=tmp_path / "app")
    application = bootstrap_local_application(settings)
    original = type(application).create_local_model_service

    def stubbed_model_service(self):
        models = original(self)
        models._popen = lambda command, **kw: subprocess.Popen([sys.executable, str(stub), *command[1:]], **kw)  # noqa: SLF001
        models._hardware = lambda b: HardwareSummary(llama_server_path=str(b) if b else None)  # noqa: SLF001
        return models

    monkeypatch.setattr(type(application), "create_local_model_service", stubbed_model_service)
    client = TestClient(application.create_http_app(), base_url="http://127.0.0.1")
    headers = {API_TOKEN_HEADER: settings.api_token_path.read_text(encoding="utf-8").strip()}
    accepted = client.post("/v1/onboarding/accept", headers=headers, json={"providers": ["claude_code"]})
    assert accepted.status_code == 200, accepted.text
    return application, settings, client, headers


def test_agent_annotation_path_behind_allowance(tmp_path: Path, monkeypatch) -> None:
    application, settings, client, headers = _bootstrap(tmp_path, monkeypatch)

    # Off by default; every agent route answers 403 until the person flips the switch.
    state = client.get("/v1/annotation/allowance", headers=headers)
    assert state.status_code == 200 and state.json()["agent_allowed"] is False
    assert "see that content" in state.json()["note"]
    for closed in ("/v1/annotation/work?model=codex-gpt", "/v1/annotation/work/" + "a" * 64):
        response = client.get(closed, headers=headers)
        assert response.status_code in {403, 422}, closed
    denied = client.get("/v1/annotation/work?model=codex-gpt", headers=headers)
    assert denied.status_code == 403 and denied.json()["detail"]["code"] == "allowance_required"

    # The metaprompt itself is safe to read any time - it contains no session content.
    meta = client.get("/v1/annotation/metaprompt", headers=headers)
    assert meta.status_code == 200, meta.text
    body = meta.json()
    assert set(body["questions"]) == set(CALIBRATION_METRIC_KEYS)
    assert set(body["labels"]) == {"low", "medium", "high", "cannot_judge"}
    assert "JSON" in body["reply_format"]
    assert body["prompt_version"] == JUDGE_PROMPT_VERSION

    # Flip the allowance on.
    flipped = client.post("/v1/annotation/allowance", headers=headers, json={"agent_allowed": True})
    assert flipped.status_code == 200 and flipped.json()["agent_allowed"] is True

    # Work list: both sessions pending for this agent.
    work = client.get("/v1/annotation/work?model=codex-gpt", headers=headers)
    assert work.status_code == 200, work.text
    items = work.json()["items"]
    assert len(items) == 2 and work.json()["remaining"] == 2
    session_id = items[0]["session_id"]
    assert items[0]["provider"] == "claude_code" and items[0]["project_id"]

    # The window is the redacted analysis window, never the raw transcript.
    window = client.get(f"/v1/annotation/work/{session_id}", headers=headers)
    assert window.status_code == 200, window.text
    rendered_window = json.loads(window.json()["window"])
    assert rendered_window["task_anchor_retained"] is True
    assert rendered_window["records"][0]["role"] == "user"
    assert set(window.json()["questions"]) == set(CALIBRATION_METRIC_KEYS)
    fingerprint = window.json()["window_fingerprint"]
    assert len(fingerprint) == 64 and fingerprint != "0" * 64

    # Submit labels; stored as ordinary model judgments under agent:<name>.
    labels = {CALIBRATION_METRIC_KEYS[0]: "high", CALIBRATION_METRIC_KEYS[1]: "medium", CALIBRATION_METRIC_KEYS[2]: "cannot_judge"}
    submitted = client.post("/v1/annotation/annotations", headers=headers, json={"session_id": session_id, "model_name": "codex-gpt", "window_fingerprint": fingerprint, "case_fingerprint": window.json()["case_fingerprint"], "case_version": window.json()["case_version"], "labels": labels})
    assert submitted.status_code == 201, submitted.text
    assert submitted.json() == {"contract_version": "annotation.v1", "session_id": session_id, "model_alias": "agent:codex-gpt", "stored": 3}
    stored = application.database.model_judgment_repository().list(session_id=session_id, model_alias="agent:codex-gpt")
    assert len(stored) == 3 and all(j.model_identity == "codex-gpt" for j in stored)
    # Provenance: every judgment names the window the source actually sealed.
    assert {j.window_fingerprint for j in stored} == {fingerprint}
    assert {j.case_fingerprint for j in stored} == {window.json()["case_fingerprint"]}

    # The annotated session leaves this agent's work list; unknown metric keys are rejected.
    again = client.get("/v1/annotation/work?model=codex-gpt", headers=headers).json()
    assert session_id not in {item["session_id"] for item in again["items"]} and again["remaining"] == 1
    bad = client.post("/v1/annotation/annotations", headers=headers, json={"session_id": session_id, "model_name": "codex-gpt", "window_fingerprint": fingerprint, "labels": {"made.up_key": "high"}})
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "labels_invalid"

    # Flip the allowance off again - the surface closes immediately.
    client.post("/v1/annotation/allowance", headers=headers, json={"agent_allowed": False})
    assert client.get(f"/v1/annotation/work/{session_id}", headers=headers).status_code == 403

    # Capability flag advertises the surface.
    capabilities = client.get("/v1/capabilities", headers=headers)
    assert capabilities.status_code == 200 and capabilities.json()["annotation"] is True


def test_annotate_remotely_via_embedded_central_server(tmp_path: Path, monkeypatch) -> None:
    application, settings, client, headers = _bootstrap(tmp_path, monkeypatch)

    # The read-only disclosure names the exact boundary before any batch can be sent.
    assert client.get("/v1/annotation/remote/disclosure").status_code == 401
    disclosure = client.get("/v1/annotation/remote/disclosure", headers=headers)
    assert disclosure.status_code == 200, disclosure.text
    assert disclosure.json() == {
        "contract_version": "annotation.v1",
        "destination": "embedded central server (this machine)",
        "redacted_windows_retained": True,
        "pseudonymous_session_ids_retained": True,
        "pseudonymous_project_ids_retained": True,
        "raw_transcripts_sent": False,
        "model_policy": "configured_active_model_at_submission",
        "active_model_alias": None,
    }

    # No configured model is active on the central side yet -> the batch fails closed.
    weights = tmp_path / "tiny.gguf"
    weights.write_bytes(b"GGUF" + b"\0" * 4092)
    assert client.post("/v1/local-models", headers=headers, json={"alias": "stub-central", "path": str(weights)}).status_code == 201
    early = client.post("/v1/annotation/remote/submit", headers=headers, json={"limit": 2})
    assert early.status_code == 409 and early.json()["detail"]["code"] == "no_central_model"

    assert client.post("/v1/local-models/stub-central/activate", headers=headers, json={"device": "cpu"}).status_code == 200
    try:
        active_disclosure = client.get("/v1/annotation/remote/disclosure", headers=headers)
        assert active_disclosure.status_code == 200
        assert active_disclosure.json()["active_model_alias"] == "stub-central"
        assert active_disclosure.json()["destination"] == disclosure.json()["destination"]

        # The explicit "annotate remotely" action: redacted windows + pseudonymous ids to the central server.
        result = client.post("/v1/annotation/remote/submit", headers=headers, json={"limit": 2})
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["destination"] == "embedded central server (this machine)"
        assert body["submitted"] == 2 and body["annotated"] == 2
        assert body["model_identity"] == "stub-central" and body["stored_locally_as"] == "central:stub-central"

        # Central dataset: submissions + labels landed in the central store.
        central_db = settings.home / "central-annotations.sqlite3"
        assert central_db.exists()
        with sqlite3.connect(central_db) as connection:
            rows = connection.execute("SELECT user_label, provider, window_chars, labels_json, model_identity, prompt_version FROM central_annotations").fetchall()
        assert len(rows) == 2
        for user_label, provider, window_chars, labels_json, model_identity, prompt_version in rows:
            assert user_label == "owner" and provider == "claude_code" and window_chars > 0
            assert set(json.loads(labels_json)) == set(CALIBRATION_METRIC_KEYS)
            assert model_identity == "stub-central"
            assert prompt_version == JUDGE_PROMPT_VERSION

        # Returned labels are recorded locally as central:<model> judgments - same comparable store.
        local = application.database.model_judgment_repository().list(model_alias="central:stub-central")
        assert len(local) == 2 * len(CALIBRATION_METRIC_KEYS)

        # Idempotent: already-central-annotated sessions are not resubmitted.
        second = client.post("/v1/annotation/remote/submit", headers=headers, json={"limit": 2})
        assert second.status_code == 200 and second.json()["submitted"] == 0 and second.json()["annotated"] == 0

        # The central route can also be called directly (this is what the VPS will expose).
        direct_window = json.dumps(
            {
                "schema": JUDGE_WINDOW_SCHEMA_VERSION,
                "authority": "untrusted_evidence",
                "available": True,
                "task_anchor_retained": True,
                "earlier_records_omitted": False,
                "records": [
                    {
                        "sequence": 0,
                        "role": "user",
                        "content": "Please fix the synthetic retry test.",
                    },
                    {
                        "sequence": 1,
                        "role": "agent",
                        "content": "Done; synthetic tests pass.",
                    },
                ],
            },
            separators=(",", ":"),
        )
        direct = client.post("/central/v1/annotations/batch", headers=headers, json={
            "user_label": "someone.else",
            "items": [{"session_id": "f" * 64, "provider": "codex", "window": direct_window}],
        })
        assert direct.status_code == 200, direct.text
        assert direct.json()["stored"] == 1 and direct.json()["annotations"][0]["session_id"] == "f" * 64
        with sqlite3.connect(central_db) as connection:
            count = connection.execute("SELECT COUNT(*) FROM central_annotations").fetchone()[0]
        assert count == 3
    finally:
        client.post("/v1/local-models/stub-central/deactivate", headers=headers)
