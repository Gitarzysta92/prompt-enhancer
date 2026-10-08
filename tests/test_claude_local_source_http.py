"""The composed loopback app serves the hook-captured Claude Code source."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import io
import json
from pathlib import Path

from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.infrastructure.providers.claude_code_hooks.receiver import (
    ReceiverStatus,
    receive,
)


T0 = datetime(2026, 8, 18, 10, 0, tzinfo=UTC)
CANARY_CWD = "/srv/example-workspaces/CANARY-HTTP-PROJECT"


def _composed(tmp_path: Path) -> tuple[TestClient, dict[str, str], AppSettings]:
    settings = AppSettings(home=tmp_path)
    application = bootstrap_local_application(settings)
    client = TestClient(application.create_http_app(), base_url="http://127.0.0.1")
    token = settings.api_token_path.read_text(encoding="utf-8").strip()
    return client, {API_TOKEN_HEADER: token}, settings


def _hook(name: str, **extra: object) -> io.BytesIO:
    payload: dict[str, object] = {
        "session_id": "CANARY-HTTP-SESSION", "cwd": CANARY_CWD,
        "transcript_path": "/home/example-user/.claude/x.jsonl", "hook_event_name": name,
    }
    payload.update(extra)
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


def test_claude_source_routes_require_auth_and_report_capability(tmp_path: Path) -> None:
    client, headers, _ = _composed(tmp_path)
    assert client.get("/v1/local-sources/claude-code").status_code == 401
    capabilities = client.get("/v1/capabilities", headers=headers).json()
    assert capabilities["claude_code_local_source"] is True
    assert capabilities["codex_local_source"] is True
    status = client.get("/v1/local-sources/claude-code", headers=headers)
    assert status.status_code == 200
    body = status.json()
    assert body["consent_active"] is False
    assert body["captured_sessions"] == 0 and body["indexed_sessions"] == 0
    assert body["capture_channel"] == "claude_code_hooks"
    # The owner-authorized transcript adapter (ADR 0011) is the primary Claude source.
    assert body["reads_transcripts"] is True and body["persists_content"] is False


def test_claude_source_consent_capture_index_roundtrip(tmp_path: Path) -> None:
    client, headers, settings = _composed(tmp_path)
    # Indexing without consent fails closed.
    assert client.post("/v1/local-sources/claude-code/index", headers=headers, json={}).status_code == 403
    # Hook events without consent are dropped by the receiver.
    assert receive(_hook("Stop"), settings=settings, now=lambda: T0).status is ReceiverStatus.CONSENT_INACTIVE

    granted = client.post("/v1/local-sources/claude-code/consents/local-history", headers=headers)
    assert granted.status_code == 200 and granted.json()["consent_active"] is True

    clock = iter(T0 + timedelta(seconds=i) for i in range(20))
    now = lambda: next(clock)  # noqa: E731
    for step in (
        _hook("SessionStart", source="startup"),
        _hook("UserPromptSubmit", prompt="Fix the demo build\nCANARY-PROMPT"),
        _hook("PreToolUse", tool_name="Bash", tool_use_id="toolu_9", tool_input={"command": "CANARY"}),
        _hook("PostToolUse", tool_name="Bash", tool_use_id="toolu_9", tool_input={}, tool_response={"stdout": "CANARY"}),
        _hook("Stop"),
    ):
        assert receive(step, settings=settings, now=now).status is ReceiverStatus.APPENDED

    status = client.get("/v1/local-sources/claude-code", headers=headers).json()
    assert status["captured_sessions"] == 1 and status["captured_events"] == 5
    assert status["indexed_sessions"] == 0

    indexed = client.post("/v1/local-sources/claude-code/index", headers=headers, json={"max_sessions": 50})
    assert indexed.status_code == 200
    report = indexed.json()
    assert report["sessions_seen"] == 1 and report["events_seen"] == 5

    status = client.get("/v1/local-sources/claude-code", headers=headers).json()
    assert status["indexed_sessions"] == 1 and status["indexed_projects"] == 1

    # The indexed session is visible in the shared catalog with its provider.
    sessions = client.get("/v1/sessions?limit=50&offset=0", headers=headers)
    assert sessions.status_code == 200
    providers = {row["provider"] for row in sessions.json()["sessions"]}
    assert "claude_code" in providers
    text = sessions.text
    for canary in ("CANARY-HTTP-SESSION", CANARY_CWD, "example-user", "CANARY-PROMPT", "toolu_9"):
        assert canary not in text

    revoked = client.delete("/v1/local-sources/claude-code/consents/local-history", headers=headers)
    assert revoked.status_code == 200 and revoked.json()["consent_active"] is False
    assert receive(_hook("Stop"), settings=settings, now=now).status is ReceiverStatus.CONSENT_INACTIVE
    # Revocation does not delete what was captured; the status says so by count.
    assert client.get("/v1/local-sources/claude-code", headers=headers).json()["captured_events"] == 5


def test_claude_code_compatibility_is_served_by_the_composed_app(tmp_path: Path) -> None:
    client, headers, _ = _composed(tmp_path)
    cached = client.get("/v1/providers/claude_code/compatibility", headers=headers)
    assert cached.status_code == 200, cached.text
    body = cached.json()
    assert body["provider"] == "claude_code"
    # With no transcript root in the isolated home the text window is
    # unavailable, so the hook ledger speaks for the provider: an
    # operational-event surface, never a text surface.  (With a root present
    # the transcript text window is primary - see test_onboarding.)
    assert body["capability"] == "operational_events"
    assert body["adapter_family"] == "claude_code_hooks"
    assert body["adapter_version"] == "claude-code-hooks-adapter-1"
    assert body["content_schema_version"] == "claude-code-hooks.receipt-clock.v1"
    assert body["state"] == "untested" and body["reason_code"] == "not_checked"

    checked = client.post("/v1/providers/claude_code/compatibility/check", headers=headers)
    assert checked.status_code == 200, checked.text
    body = checked.json()
    assert body["state"] == "degraded"
    assert body["capability_state"] == "supported"
    assert body["reason_code"] == "degraded_extraction"
    assert body["provider_version"] == "unknown"

    # Codex keeps its text-window contract untouched.
    codex = client.get("/v1/providers/codex/compatibility", headers=headers)
    assert codex.status_code == 200
    assert codex.json()["capability"] == "session_text_analysis"
