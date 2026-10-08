"""Claude transcript adapter: full history from the owner's transcript files.

Fictional transcripts only.  The adapter is the primary Claude source when
present: provider timestamps, tokens from message.usage, tool errors, titles;
hooks yield no events for a session a transcript covers; an earlier hook
ingest is superseded without a sequence conflict.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import io
import json
from pathlib import Path
import sqlite3
import threading

import pytest

from prompt_enhancer.adapters.base import AdapterHealth
from prompt_enhancer.application.runtime_cancellation import (
    RuntimeCooperativeStop,
    runtime_request_scope,
)
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.domain import DataTier, EventKind, Provider, ToolCategory
from prompt_enhancer.infrastructure.providers.claude_code_hooks.receiver import receive
from prompt_enhancer.infrastructure.providers.claude_code_hooks.transcript_adapter import (
    ClaudeTranscriptAdapter,
    parse_events,
    read_head,
    scan_transcripts,
)


T0 = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
CWD = "/srv/example-workspaces/transcript-demo"
SESSION_A = "aaaa1111-example-session-a"
SESSION_B = "bbbb2222-example-session-b"
CANARY = "CANARY-TRANSCRIPT-BODY-acme"


def _rec(kind: str, content: object, at: datetime, session: str, **extra: object) -> str:
    record: dict[str, object] = {"type": kind, "message": {"role": kind, "content": content}, "timestamp": at.isoformat().replace("+00:00", "Z"),
                                 "sessionId": session, "cwd": CWD, "version": "2.1.0", "uuid": f"u-{at.timestamp()}"}
    record.update(extra)
    return json.dumps(record)


def write_session(claude_home: Path, session: str, start: datetime, *, with_error: bool = False) -> Path:
    project_dir = claude_home / "projects" / "-srv-example-workspaces-transcript-demo"
    project_dir.mkdir(parents=True, exist_ok=True)
    usage = {"input_tokens": 1200, "output_tokens": 340, "cache_read_input_tokens": 800, "cache_creation_input_tokens": 0}
    lines = [
        json.dumps({"type": "summary", "summary": "ignored", "leafUuid": "x"}),
        _rec("user", f"Add retries to the uploader\n{CANARY}", start, session),
        json.dumps({"type": "assistant", "timestamp": (start + timedelta(seconds=3)).isoformat().replace("+00:00", "Z"), "sessionId": session, "cwd": CWD, "version": "2.1.0",
                    "message": {"role": "assistant", "model": "claude-opus-5", "usage": usage,
                                "content": [{"type": "text", "text": "Looking."}, {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "pytest -q"}}]}}),
        _rec("user", [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "1 failed" if with_error else "3 passed", "is_error": with_error}], start + timedelta(seconds=9), session),
        json.dumps({"type": "assistant", "timestamp": (start + timedelta(seconds=20)).isoformat().replace("+00:00", "Z"), "sessionId": session, "cwd": CWD, "version": "2.1.0",
                    "message": {"role": "assistant", "model": "claude-opus-5", "usage": {"input_tokens": 1500, "output_tokens": 500, "cache_read_input_tokens": 1200, "cache_creation_input_tokens": 64},
                                "content": [{"type": "text", "text": "Done."}]}}),
        json.dumps({"type": "system", "subtype": "compact_boundary", "timestamp": (start + timedelta(seconds=25)).isoformat().replace("+00:00", "Z"), "sessionId": session}),
        _rec("user", "Now add tests", start + timedelta(seconds=30), session),
        json.dumps({"type": "assistant", "timestamp": (start + timedelta(seconds=40)).isoformat().replace("+00:00", "Z"), "sessionId": session, "cwd": CWD, "version": "2.1.0",
                    "message": {"role": "assistant", "model": "claude-opus-5", "usage": {"input_tokens": 100, "output_tokens": 50}, "content": [{"type": "text", "text": "Added."}]}}),
    ]
    path = project_dir / f"{session}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
    claude_home = tmp_path / "claude-home"
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(claude_home))
    settings = AppSettings(home=tmp_path / "app")
    bootstrap_local_application(settings)
    Database(settings.database_path).grant_consent(Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT)
    return settings, claude_home


def test_scan_head_and_parse_are_deterministic_and_bounded(env) -> None:
    settings, claude_home = env
    path = write_session(claude_home, SESSION_A, T0, with_error=True)
    files = scan_transcripts(claude_home)
    assert [f.stem for f in files] == [SESSION_A]
    head = read_head(path)
    assert head.cwd == CWD and head.version == "2.1.0" and head.first_at == T0
    assert head.title == "Add retries to the uploader"
    parsed = parse_events(path, SESSION_A)
    kinds = [e.kind for e in parsed.events if e.kind is not EventKind.USAGE]
    assert kinds == [
        EventKind.SESSION_START, EventKind.TURN_START, EventKind.TOOL_START, EventKind.TOOL_END,
        EventKind.TURN_END, EventKind.COMPACTION, EventKind.TURN_START, EventKind.TURN_END,
    ]
    non_usage = [e for e in parsed.events if e.kind is not EventKind.USAGE]
    assert [e.sequence for e in non_usage] == list(range(len(non_usage)))
    tool_end = next(e for e in parsed.events if e.kind is EventKind.TOOL_END)
    # "pytest -q" is classified as a TEST run (content-free; the command is dropped).
    assert tool_end.tool_category is ToolCategory.TEST and tool_end.success is False and tool_end.duration_ms == 6000
    usage = [e for e in parsed.events if e.kind is EventKind.USAGE]
    assert len(usage) == 3 and usage[0].usage is not None
    assert usage[0].usage.input_tokens == 1200 and usage[0].usage.cached_input_tokens == 800 and usage[0].usage.model_id == "claude-opus-5"
    assert all(e.sequence >= 3_000_000 for e in usage)
    assert parsed.complete is True and parsed.first_at == T0 and parsed.last_at == T0 + timedelta(seconds=40)


def test_transcript_scan_and_parse_honor_background_shutdown(env) -> None:
    _settings, claude_home = env
    path = write_session(claude_home, SESSION_A, T0)
    cancelled = threading.Event()
    cancelled.set()

    with runtime_request_scope(cancelled), pytest.raises(
        RuntimeCooperativeStop, match="^claude_transcript_scan_cancelled$"
    ):
        scan_transcripts(claude_home)
    with runtime_request_scope(cancelled), pytest.raises(
        RuntimeCooperativeStop, match="^claude_transcript_parse_cancelled$"
    ):
        parse_events(path, SESSION_A)


@pytest.mark.parametrize(
    "bad_record",
    [
        {
            "type": "assistant",
            "timestamp": (T0 + timedelta(seconds=1)).isoformat(),
            "message": {"content": [{"type": "future_action", "payload": {}}]},
        },
        {
            "type": "user",
            "timestamp": (T0 + timedelta(seconds=1)).isoformat(),
            "message": {"content": {"type": "text", "text": "bad shape"}},
        },
        {
            "type": "user",
            "timestamp": (T0 + timedelta(seconds=1)).isoformat(),
            "message": {"content": [{"type": "text", "text": 123}]},
        },
        {
            "type": "assistant",
            "timestamp": (T0 + timedelta(seconds=1)).isoformat(),
            "message": "bad shape",
        },
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "example-tool-call",
                        "name": "Bash",
                        "input": {"command": "example-command"},
                    }
                ]
            },
        },
        {
            "type": "assistant",
            "timestamp": (T0 + timedelta(seconds=1)).isoformat(),
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "example-tool-call",
                        "name": "Bash",
                        "input": "not-an-object",
                    }
                ]
            },
        },
    ],
)
def test_unknown_malformed_or_untimed_action_rows_fail_closed(
    tmp_path: Path,
    bad_record: dict[str, object],
) -> None:
    path = tmp_path / "example-session.jsonl"
    valid = json.loads(_rec("user", "Example request.", T0, SESSION_A))
    path.write_text(
        "\n".join(json.dumps(item) for item in (valid, bad_record)) + "\n",
        encoding="utf-8",
    )

    parsed = parse_events(path, "example-session")

    assert parsed.complete is False
    assert parsed.action_descriptor_extraction_complete is False
    assert CANARY not in "".join(repr(e) for e in parsed.events)


@pytest.mark.parametrize("result_between", [False, True])
def test_duplicate_tool_use_identity_fails_action_completeness(
    tmp_path: Path,
    result_between: bool,
) -> None:
    """A provider ID cannot identify two different invocations/effects."""

    duplicate_ref = "example-duplicate-tool"
    first = _rec(
        "assistant",
        [{
            "type": "tool_use",
            "id": duplicate_ref,
            "name": "Bash",
            "input": {"command": "example-test-command"},
        }],
        T0,
        SESSION_A,
    )
    result = _rec(
        "user",
        [{
            "type": "tool_result",
            "tool_use_id": duplicate_ref,
            "content": "synthetic result",
            "is_error": False,
        }],
        T0 + timedelta(seconds=1),
        SESSION_A,
    )
    second = _rec(
        "assistant",
        [{
            "type": "tool_use",
            "id": duplicate_ref,
            "name": "Read",
            "input": {"file_path": "/srv/example/input.txt"},
        }],
        T0 + timedelta(seconds=2),
        SESSION_A,
    )
    final_result = _rec(
        "user",
        [{
            "type": "tool_result",
            "tool_use_id": duplicate_ref,
            "content": "synthetic final result",
            "is_error": False,
        }],
        T0 + timedelta(seconds=3),
        SESSION_A,
    )
    rows = [first]
    if result_between:
        rows.append(result)
    rows.extend((second, final_result))
    path = tmp_path / "example-duplicate-session.jsonl"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    parsed = parse_events(path, "example-duplicate-session")

    assert parsed.complete is False
    assert parsed.action_descriptor_extraction_complete is False


def test_adapter_lists_reads_and_ingests_history_with_titles_and_tokens(env) -> None:
    settings, claude_home = env
    write_session(claude_home, SESSION_A, T0)
    write_session(claude_home, SESSION_B, T0 - timedelta(days=3))
    application = bootstrap_local_application(settings)
    adapter = ClaudeTranscriptAdapter(application.pseudonymizer)
    probe = adapter.probe()
    assert probe.health is AdapterHealth.READY and probe.supports_content is True
    page = adapter.list_sessions(limit=10)
    assert len(page.sessions) == 2 and page.next_cursor is None
    titles = {s.source_session_display_name.get_secret_value() for s in page.sessions if s.source_session_display_name}
    assert titles == {"Add retries to the uploader"}
    assert all(s.source_project_display_name is not None and s.source_project_display_name.get_secret_value() == "transcript-demo" for s in page.sessions)
    snapshot = adapter.read_session(page.sessions[0])
    assert snapshot.session.events_complete is True
    assert snapshot.session.provider_version == "2.1.0"

    report = application.create_ingestion_service().ingest(adapter)
    assert report.sessions_seen == 2 and report.events_seen == 22  # 2 × (8 hook-space + 3 usage)
    rows = [r for r in application.database.list_sessions(limit=50, offset=0) if r.get("provider") == "claude_code"]
    assert len(rows) == 2
    assert {r["session_display_name"] for r in rows} == {"Add retries to the uploader"}
    assert {r["project_display_name"] for r in rows} == {"transcript-demo"}
    session_id = str(rows[0]["session_id"])
    metrics = {m["key"]: m for m in application.database.get_session_metrics(session_id)}
    token_metric = next((m for k, m in metrics.items() if "token" in str(k)), None)
    assert token_metric is not None and token_metric.get("numeric_value") not in (None, 0)
    connection = sqlite3.connect(settings.database_path)
    try:
        dump = "\n".join(repr(r) for t in [x[0] for x in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")] for r in connection.execute(f'SELECT * FROM "{t}"'))
        # Migration 52: Claude labels carry provenance in the label tables (not the plain columns).
        label_rows = connection.execute(
            "SELECT provider_value, provider_source, observation_method, extractor_version FROM session_display_labels WHERE session_id=?",
            (session_id,),
        ).fetchall()
        project_rows = connection.execute(
            "SELECT provider_value, provider_source, observation_method FROM project_display_labels WHERE project_id=?",
            (str(rows[0]["project_id"]),),
        ).fetchall()
        plain_columns = connection.execute(
            "SELECT s.display_name, p.display_name FROM sessions s JOIN projects p ON p.project_id=s.project_id WHERE s.session_id=?",
            (session_id,),
        ).fetchone()
    finally:
        connection.close()
    assert CANARY not in dump and SESSION_A not in dump and CWD not in dump
    assert label_rows == [("Add retries to the uploader", "provider_first_prompt", "transcript_head", "claude-code-display-labels-v1")]
    assert project_rows == [("transcript-demo", "provider_path_basename", "transcript_head")]
    assert plain_columns == (None, None)


def test_transcript_supersedes_an_earlier_hook_ingest_without_sequence_conflict(env) -> None:
    settings, claude_home = env
    # 1) hook capture + index first (receiver-clock events at sequence 0..)
    clock = iter(T0 + timedelta(seconds=i) for i in range(20))
    for name, extra in (("SessionStart", {"source": "startup"}), ("UserPromptSubmit", {"prompt": "Add retries to the uploader"}),
                        ("PreToolUse", {"tool_name": "Bash", "tool_use_id": "t1"}), ("PostToolUse", {"tool_name": "Bash", "tool_use_id": "t1"}), ("Stop", {})):
        payload = {"session_id": SESSION_A, "cwd": CWD, "hook_event_name": name, **extra}
        receive(io.BytesIO(json.dumps(payload).encode()), settings=settings, now=lambda: next(clock))
    application = bootstrap_local_application(settings)
    service = application.create_claude_local_source_service()
    first = service.index(max_sessions=50)
    assert first.sessions_seen == 1
    rows = [r for r in application.database.list_sessions(limit=50, offset=0) if r.get("provider") == "claude_code"]
    session_id = str(rows[0]["session_id"])
    hook_events = application.database.get_session_events(session_id)
    assert len(hook_events) == 5 and all(e.sequence < 1_000_000 for e in hook_events)

    # 2) the transcript for the same session appears; re-index
    write_session(claude_home, SESSION_A, T0)
    application = bootstrap_local_application(settings)
    service = application.create_claude_local_source_service()
    second = service.index(max_sessions=50)
    assert second.sessions_seen >= 1
    rows = [r for r in application.database.list_sessions(limit=50, offset=0) if r.get("provider") == "claude_code"]
    assert len(rows) == 1 and str(rows[0]["session_id"]) == session_id  # same catalog session
    events = application.database.get_session_events(session_id)
    kinds = [e.kind for e in events if e.kind is not EventKind.USAGE]
    assert EventKind.COMPACTION in kinds  # transcript-only event is present
    assert len([e for e in events if e.kind is EventKind.USAGE]) == 3
    # No duplicated hook-origin tool events: exactly one TOOL_START / TOOL_END.
    assert kinds.count(EventKind.TOOL_START) == 1 and kinds.count(EventKind.TOOL_END) == 1
    safe = application.database.get_session(session_id)
    assert safe is not None and safe.source_schema_version == "claude-code-transcripts.jsonl.v1"

    # 3) hooks keep recording for this session, but the hook adapter no longer
    #    lists it: the transcript owns it entirely.
    hook_adapter = application.create_claude_hook_adapter()
    hook_adapter.probe()
    assert hook_adapter.list_sessions(limit=10).sessions == ()
    # Re-indexing is idempotent: the supersede guard no longer matches.
    third = application.create_claude_local_source_service().index(max_sessions=50)
    assert third.events_inserted == 0
    assert len(application.database.get_session_events(session_id)) == len(events)


def test_status_reports_transcript_reading_honestly(env) -> None:
    settings, _ = env
    application = bootstrap_local_application(settings)
    status = application.create_claude_local_source_service().status()
    assert status.reads_transcripts is True and status.persists_content is False


def test_shell_commands_classify_as_test_or_build_without_keeping_text() -> None:
    from prompt_enhancer.infrastructure.providers.claude_code_hooks.contracts import classify_command

    assert classify_command("pytest tests -q") is ToolCategory.TEST
    assert classify_command("./.venv/Scripts/python.exe -m pytest tests -x") is ToolCategory.TEST
    assert classify_command("npm run test:unit") is ToolCategory.TEST
    assert classify_command("npx vitest run --maxWorkers=4") is ToolCategory.TEST
    assert classify_command("cd frontend && npm ci && npm run build") is ToolCategory.BUILD
    assert classify_command("npm run build && npm test") is ToolCategory.TEST
    assert classify_command("npx tsc --noEmit") is ToolCategory.BUILD
    assert classify_command("cargo build --release") is ToolCategory.BUILD
    assert classify_command("make") is ToolCategory.BUILD
    assert classify_command("git status") is ToolCategory.COMMAND
    assert classify_command("echo pytest") is ToolCategory.COMMAND
    assert classify_command("") is ToolCategory.COMMAND
    assert classify_command(None) is ToolCategory.COMMAND
    # Only the leading part of a long command is examined.
    assert classify_command("echo " + "x" * 1000 + " && pytest") is ToolCategory.COMMAND


def test_reindex_of_a_growing_session_supersedes_the_provisional_tail(env) -> None:
    """A still-running session is re-indexed as it grows: the provisional
    trailing turn_end from the first parse moves once real events extend the
    file, and the full re-parse replaces the stored event set instead of
    failing the sequence-identity invariant (the bug behind 'last refresh
    reported an error')."""

    settings, claude_home = env
    project_dir = claude_home / "projects" / "-srv-example-workspaces-transcript-demo"
    project_dir.mkdir(parents=True, exist_ok=True)
    session = "cccc3333-example-growing"
    start = T0

    # Snapshot 1: mid-turn - the assistant answered and started a tool that
    # has not finished yet. The parser closes the open turn provisionally.
    lines = [
        _rec("user", "Please fix the flaky retry test", start, session),
        json.dumps({"type": "assistant", "timestamp": (start + timedelta(seconds=5)).isoformat().replace("+00:00", "Z"), "sessionId": session, "cwd": CWD, "version": "2.1.0",
                    "message": {"role": "assistant", "model": "claude-opus-5", "usage": {"input_tokens": 100, "output_tokens": 20},
                                "content": [{"type": "text", "text": "On it."}, {"type": "tool_use", "id": "toolu_g1", "name": "Bash", "input": {"command": "pytest -q"}}]}}),
    ]
    path = project_dir / f"{session}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    application = bootstrap_local_application(settings)
    service = application.create_claude_local_source_service()
    first = service.index(max_sessions=10)
    assert first.sessions_inserted >= 1
    database = Database(settings.database_path)
    # find our session by matching event shape instead of private ids
    sessions = [str(row["session_id"]) for row in database.list_sessions(limit=50, offset=0)]
    target = None
    for sid in sessions:
        kinds = [e.kind for e in database.get_session_events(sid)]
        if EventKind.TOOL_START in kinds and EventKind.TOOL_END not in kinds:
            target = sid
            break
    assert target is not None, "growing session not found after first index"
    first_kinds = [e.kind for e in database.get_session_events(target)]
    assert EventKind.TURN_END in first_kinds  # provisional closure of the open turn

    # Snapshot 2: the session continued - the tool finished and a new prompt
    # arrived, so the real turn_end lands at a different position than the
    # provisional one. Re-indexing must supersede, not crash.
    lines += [
        _rec("user", [{"type": "tool_result", "tool_use_id": "toolu_g1", "content": "3 passed", "is_error": False}], start + timedelta(seconds=30), session),
        json.dumps({"type": "assistant", "timestamp": (start + timedelta(seconds=40)).isoformat().replace("+00:00", "Z"), "sessionId": session, "cwd": CWD, "version": "2.1.0",
                    "message": {"role": "assistant", "model": "claude-opus-5", "usage": {"input_tokens": 200, "output_tokens": 40}, "content": [{"type": "text", "text": "Fixed."}]}}),
        _rec("user", "Great, now update the docs", start + timedelta(seconds=60), session),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    second = service.index(max_sessions=10)  # raised IngestionError before the fix
    assert second.sessions_updated >= 1 or second.sessions_inserted >= 1
    kinds = [e.kind for e in database.get_session_events(target)]
    assert EventKind.TOOL_END in kinds  # the real tool completion is stored
