"""Owner-authorized on-demand session reader (ADR 0011).

All transcript content here is fictional.  The reader is off by default,
opens exactly one file, and persists nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import io
import json
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest

from prompt_enhancer.api import API_TOKEN_HEADER
from prompt_enhancer.application.analysis.session_reader import (
    ReaderRole,
    ReaderSource,
    SessionReadError,
    SessionReadFailure,
    SessionReaderService,
    SessionTranscript,
)
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.domain import DataTier, Provider
from prompt_enhancer.infrastructure.providers.claude_code_hooks.adapter import ClaudeCodeHookAdapter
from prompt_enhancer.infrastructure.providers.claude_code_hooks.receiver import receive
from prompt_enhancer.infrastructure.providers.claude_code_hooks.transcript_reader import (
    ClaudeTranscriptReader,
    catalog_session_id_for,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.content_contracts import (
    CodexTextItemKind,
    RawCodexTextFragment,
    RawCodexTextThread,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.session_reader import transcript_from_thread
from prompt_enhancer.privacy import Pseudonymizer
from pydantic import SecretStr


RAW_SESSION = "0f0f0f0f-example-claude-session-uuid"
OTHER_SESSION = "1a1a1a1a-example-other-session-uuid"
T0 = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)
CWD = "/srv/example-workspaces/reader-demo"


def _line(kind: str, content: object, at: datetime, extra: dict | None = None) -> str:
    record = {"type": kind, "message": {"role": kind, "content": content}, "timestamp": at.isoformat().replace("+00:00", "Z"),
              "sessionId": RAW_SESSION, "cwd": CWD, "version": "2.1.0", "uuid": "u-" + at.isoformat()}
    if extra:
        record.update(extra)
    return json.dumps(record)


def _write_transcript(claude_home: Path, session: str, lines: list[str]) -> Path:
    project_dir = claude_home / "projects" / "-srv-example-workspaces-reader-demo"
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / f"{session}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def fictional_lines() -> list[str]:
    return [
        json.dumps({"type": "summary", "summary": "Reader demo", "leafUuid": "x"}),
        _line("user", "Please add retries to the demo uploader", T0),
        _line("assistant", [{"type": "text", "text": "I will look at the uploader first."},
                            {"type": "tool_use", "id": "toolu_1", "name": "Read", "input": {"file_path": "src/uploader.py"}}], T0 + timedelta(seconds=3)),
        _line("user", [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "def upload(): ...  # 40 lines"}], T0 + timedelta(seconds=4)),
        _line("assistant", [{"type": "text", "text": "Added a bounded retry with backoff."}], T0 + timedelta(seconds=30)),
        json.dumps({"type": "system", "subtype": "compact_boundary", "content": "ignored"}),
    ]


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> tuple[AppSettings, Path]:
    claude_home = tmp_path / "claude-home"
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(claude_home))
    monkeypatch.setenv("PROMPT_ENHANCER_SESSION_READER", "enabled")
    settings = AppSettings.from_env({"PROMPT_ENHANCER_HOME": str(tmp_path / "app"), "PROMPT_ENHANCER_SESSION_READER": "enabled"})
    bootstrap_local_application(settings)
    Database(settings.database_path).grant_consent(Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT)
    return settings, claude_home


def _capture_and_index(settings: AppSettings) -> str:
    """Capture one hook session and index it; return its catalog session id."""

    clock = iter(T0 + timedelta(seconds=i) for i in range(10))
    for name in ("SessionStart", "Stop"):
        payload = {"session_id": RAW_SESSION, "cwd": CWD, "hook_event_name": name, "source": "startup"}
        receive(io.BytesIO(json.dumps(payload).encode()), settings=settings, now=lambda: next(clock))
    application = bootstrap_local_application(settings)
    application.create_ingestion_service().ingest(ClaudeCodeHookAdapter(application.database.claude_hook_ledger()))
    rows = [r for r in application.database.list_sessions(limit=50, offset=0) if r.get("provider") == "claude_code"]
    assert len(rows) == 1
    return str(rows[0]["session_id"])


def test_pseudonym_chain_matches_the_catalog_identity(home) -> None:
    settings, _ = home
    catalog_id = _capture_and_index(settings)
    pseudonymizer = bootstrap_local_application(settings).pseudonymizer
    assert catalog_session_id_for(pseudonymizer, RAW_SESSION) == catalog_id
    assert catalog_session_id_for(pseudonymizer, OTHER_SESSION) != catalog_id


def test_claude_reader_opens_only_the_matching_file_and_renders_turns(home) -> None:
    settings, claude_home = home
    catalog_id = _capture_and_index(settings)
    _write_transcript(claude_home, RAW_SESSION, fictional_lines())
    _write_transcript(claude_home, OTHER_SESSION, [_line("user", "OTHER-SESSION-CANARY", T0)])
    reader = ClaudeTranscriptReader(bootstrap_local_application(settings).pseudonymizer)
    transcript = reader.read(catalog_id)
    assert transcript.provider is Provider.CLAUDE_CODE and transcript.source is ReaderSource.CLAUDE_TRANSCRIPT_FILE
    assert transcript.provider_version == "2.1.0"
    assert transcript.persisted is False and transcript.local_only is True
    roles = [t.role for t in transcript.turns]
    assert roles == [ReaderRole.USER, ReaderRole.ASSISTANT, ReaderRole.TOOL_CALL, ReaderRole.TOOL_RESULT, ReaderRole.ASSISTANT]
    assert transcript.turns[0].text == "Please add retries to the demo uploader"
    assert transcript.turns[2].tool_name == "Read" and "uploader.py" in transcript.turns[2].text
    assert transcript.turns[3].text.startswith("def upload()")
    assert transcript.turn_count_total == 5 and transcript.truncated is False
    assert transcript.turns[0].at == T0
    assert "OTHER-SESSION-CANARY" not in transcript.model_dump_json()


def test_claude_reader_fails_closed_on_unknown_format_missing_file_and_bounds(home) -> None:
    settings, claude_home = home
    catalog_id = _capture_and_index(settings)
    reader = ClaudeTranscriptReader(bootstrap_local_application(settings).pseudonymizer)
    with pytest.raises(SessionReadError) as missing:
        reader.read(catalog_id)
    assert missing.value.reason is SessionReadFailure.SESSION_NOT_FOUND
    _write_transcript(claude_home, RAW_SESSION, [json.dumps({"kind": "future-format", "payload": "x"})])
    with pytest.raises(SessionReadError) as unknown:
        reader.read(catalog_id)
    assert unknown.value.reason is SessionReadFailure.FORMAT_UNRECOGNIZED
    _write_transcript(claude_home, RAW_SESSION, [_line("user", "y" * 30_000, T0)])
    transcript = reader.read(catalog_id)
    assert len(transcript.turns[0].text) == 20_000 and transcript.turns[0].truncated is True


def test_service_gates_on_enabled_flag_catalog_and_consent(home) -> None:
    settings, claude_home = home
    catalog_id = _capture_and_index(settings)
    _write_transcript(claude_home, RAW_SESSION, fictional_lines())
    application = bootstrap_local_application(settings)
    reader = ClaudeTranscriptReader(application.pseudonymizer)
    disabled = SessionReaderService(application.database, {Provider.CLAUDE_CODE: reader}, enabled=False)
    with pytest.raises(SessionReadError) as off:
        disabled.read(catalog_id)
    assert off.value.reason is SessionReadFailure.READER_DISABLED
    enabled = SessionReaderService(application.database, {Provider.CLAUDE_CODE: reader}, enabled=True)
    assert len(enabled.read(catalog_id).turns) == 5
    with pytest.raises(SessionReadError) as unknown:
        enabled.read("f" * 64)
    assert unknown.value.reason is SessionReadFailure.SESSION_UNKNOWN
    application.database.revoke_consent(Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT)
    with pytest.raises(SessionReadError) as consent:
        enabled.read(catalog_id)
    assert consent.value.reason is SessionReadFailure.CONSENT_REQUIRED


def test_http_route_is_absent_when_disabled_and_serves_by_default(tmp_path: Path, monkeypatch) -> None:
    claude_home = tmp_path / "claude-home"
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(claude_home))
    # Owner direction (2026-08-19): the reader is on by default. Explicitly
    # disabled, the capability is false and the route is absent.
    disabled_settings = AppSettings.from_env({"PROMPT_ENHANCER_HOME": str(tmp_path / "disabled"), "PROMPT_ENHANCER_SESSION_READER": "disabled"})
    disabled_app = bootstrap_local_application(disabled_settings)
    client = TestClient(disabled_app.create_http_app(), base_url="http://127.0.0.1")
    headers = {API_TOKEN_HEADER: disabled_settings.api_token_path.read_text(encoding="utf-8").strip()}
    assert client.get("/v1/capabilities", headers=headers).json()["raw_transcripts"] is False
    assert client.get(f"/v1/sessions/{'a' * 64}/transcript", headers=headers).status_code == 404
    assert AppSettings(home=tmp_path / "plain").session_reader_enabled is True

    settings = AppSettings.from_env({"PROMPT_ENHANCER_HOME": str(tmp_path / "app"), "PROMPT_ENHANCER_SESSION_READER": "enabled"})
    bootstrap_local_application(settings)
    Database(settings.database_path).grant_consent(Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT)
    catalog_id = _capture_and_index(settings)
    _write_transcript(claude_home, RAW_SESSION, fictional_lines())
    application = bootstrap_local_application(settings)
    client = TestClient(application.create_http_app(), base_url="http://127.0.0.1")
    headers = {API_TOKEN_HEADER: settings.api_token_path.read_text(encoding="utf-8").strip()}
    assert client.get("/v1/capabilities", headers=headers).json()["raw_transcripts"] is True
    assert client.get(f"/v1/sessions/{catalog_id}/transcript").status_code == 401
    response = client.get(f"/v1/sessions/{catalog_id}/transcript", headers=headers)
    assert response.status_code == 200, response.text
    assert "no-store" in response.headers["cache-control"]
    body = response.json()
    assert body["source"] == "claude_transcript_file" and body["persisted"] is False
    assert [t["role"] for t in body["turns"]][:2] == ["user", "assistant"]
    # Nothing from the transcript reached the store.
    connection = sqlite3.connect(settings.database_path)
    try:
        dump = "\n".join(repr(r) for t in [x[0] for x in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")] for r in connection.execute(f'SELECT * FROM "{t}"'))
    finally:
        connection.close()
    assert "add retries to the demo uploader" not in dump and "uploader.py" not in dump
    # Consent revoked -> 403.
    application.database.revoke_consent(Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT)
    assert client.get(f"/v1/sessions/{catalog_id}/transcript", headers=headers).status_code == 403


def test_codex_thread_maps_to_turns_without_redaction_and_bounded() -> None:
    def fragment(turn: str, item: str, kind: CodexTextItemKind, text: str, index: int = 0, segment: int = 0) -> RawCodexTextFragment:
        return RawCodexTextFragment(turn_id=SecretStr(turn), item_id=SecretStr(item), content_index=index, segment_index=segment, kind=kind, text=SecretStr(text))

    thread = RawCodexTextThread(
        thread_id=SecretStr("thread-1"),
        fragments=(
            fragment("t1", "i1", CodexTextItemKind.USER_MESSAGE, "Refactor the "),
            fragment("t1", "i1", CodexTextItemKind.USER_MESSAGE, "discovery inbox", segment=1),
            fragment("t1", "i2", CodexTextItemKind.PLAN, "1. read 2. change 3. test"),
            fragment("t1", "i3", CodexTextItemKind.AGENT_MESSAGE, "Done; tests pass."),
        ),
        extraction_complete=True,
        older_history_truncated=False,
        unclassified_omission=False,
    )
    transcript = transcript_from_thread("b" * 64, thread, "0.144.5")
    assert isinstance(transcript, SessionTranscript)
    assert [(t.role, t.text) for t in transcript.turns] == [
        (ReaderRole.USER, "Refactor the discovery inbox"),
        (ReaderRole.PLAN, "1. read 2. change 3. test"),
        (ReaderRole.ASSISTANT, "Done; tests pass."),
    ]
    assert transcript.source is ReaderSource.CODEX_APP_SERVER and transcript.provider_version == "0.144.5"
