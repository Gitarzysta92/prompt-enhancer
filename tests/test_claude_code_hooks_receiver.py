"""Claude Code hook receiver: content-free, consent-gated, silent, always 0.

Every payload here is fictional.  The canary strings below must never appear
in the ledger, in any model repr, on stdout, or on stderr.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import io
import json
from pathlib import Path
import re
import sqlite3

import pytest

from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.domain import DataTier, EventKind, Provider, ToolCategory
from prompt_enhancer.infrastructure.providers import claude_code_hooks as hooks
from prompt_enhancer.infrastructure.providers.claude_code_hooks import receiver as receiver_module
from prompt_enhancer.infrastructure.providers.claude_code_hooks.contracts import (
    HookEventName,
    SessionEndReason,
    SessionStartSource,
    categorize_tool_name,
    project_display_label,
)
from prompt_enhancer.infrastructure.providers.claude_code_hooks.ledger import (
    HookLedgerConsentInactive,
    HookLedgerUnavailable,
    receiver_append,
)
from prompt_enhancer.infrastructure.providers.claude_code_hooks.receiver import (
    ReceiverStatus,
    minimize_payload,
    receive,
)
from prompt_enhancer.privacy import Pseudonymizer, load_pseudonymizer


CANARY_PROMPT = "CANARY-PROMPT-please refactor the billing module for acme"
CANARY_TOOL_INPUT = "CANARY-TOOL-INPUT-cat /home/example-user/secrets.txt"
CANARY_TOOL_RESPONSE = "CANARY-TOOL-RESPONSE-sk-example-0000000000"
CANARY_TRANSCRIPT = "/home/example-user/.claude/projects/CANARY-TRANSCRIPT.jsonl"
CANARY_CWD = "/srv/example-workspaces/CANARY-PROJECT-DIR"
CANARY_SESSION = "CANARY-SESSION-0000-1111-2222"
CANARY_TOOL_USE = "CANARY-TOOLUSE-toolu_01example"
CANARY_MESSAGE = "CANARY-NOTIFICATION-Claude needs permission for Bash"
CANARIES = (
    CANARY_PROMPT,
    CANARY_TOOL_INPUT,
    CANARY_TOOL_RESPONSE,
    CANARY_TRANSCRIPT,
    CANARY_CWD,
    CANARY_SESSION,
    CANARY_TOOL_USE,
    CANARY_MESSAGE,
    "example-user",
    "acme",
    "toolu_01example",
)

KEY = Pseudonymizer(b"\x11" * 32)
T0 = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


def _payload(name: str, **extra: object) -> dict[str, object]:
    base: dict[str, object] = {
        "session_id": CANARY_SESSION,
        "transcript_path": CANARY_TRANSCRIPT,
        "cwd": CANARY_CWD,
        "hook_event_name": name,
        "permission_mode": "default",
    }
    base.update(extra)
    return base


def _stdin(payload: object) -> io.BytesIO:
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


def _assert_no_canary(text: str) -> None:
    for canary in CANARIES:
        assert canary not in text, canary


@pytest.fixture
def app_home(tmp_path: Path) -> Path:
    settings = AppSettings(home=tmp_path)
    bootstrap_local_application(settings)
    return tmp_path


@pytest.fixture
def consented_home(app_home: Path) -> Path:
    Database(app_home / "metrics.sqlite3").grant_consent(
        Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT
    )
    return app_home


def _ledger_dump(home: Path) -> str:
    connection = sqlite3.connect(home / "metrics.sqlite3")
    try:
        rows = []
        for table in ("claude_code_hook_sessions", "claude_code_hook_events"):
            for row in connection.execute(f"SELECT * FROM {table}").fetchall():
                rows.append(repr(row))
        return "\n".join(rows)
    finally:
        connection.close()


# --- contract -------------------------------------------------------------


def test_receiver_source_reads_only_allowlisted_payload_keys() -> None:
    source = Path(receiver_module.__file__).read_text(encoding="utf-8")
    forbidden = (
        "transcript_path", "tool_input", "tool_response",
        "message", "custom_instructions", "stop_hook_active",
    )
    # Every payload.get(...) call must name an allowlisted key.
    for key in re.findall(r'payload\.get\("([a-z_]+)"\)', source):
        assert key in receiver_module.ALLOWED_PAYLOAD_KEYS, key
    # Forbidden names may appear only in the docstring that lists them.
    body = source.split('"""', 2)[2]
    for name in forbidden:
        assert f'"{name}"' not in body, name
    # `prompt` is read in exactly one place, guarded by the titles switch.
    assert body.count('payload.get("prompt")') == 1
    assert 'session_title_from_prompt(payload.get("prompt"))' in body


def test_minimized_event_type_holds_only_two_bounded_labels() -> None:
    fields = set(hooks.MinimizedHookEvent.model_fields)
    for content_field in ("prompt", "tool_input", "tool_response", "cwd",
                          "transcript_path", "tool_name", "message", "session_id"):
        assert content_field not in fields
    string_fields = {
        name for name, field in hooks.MinimizedHookEvent.model_fields.items()
        if field.annotation is str or str(field.annotation) == "str | None"
    }
    # Only pseudonyms, versions, and the two minimized labels are string-typed.
    assert string_fields <= {
        "contract_version", "receiver_version", "hook_session_id", "hook_project_id",
        "project_display_label", "session_display_label", "tool_use_ref",
    }


def test_tool_names_reduce_to_categories_and_mcp_servers_are_not_kept() -> None:
    assert categorize_tool_name("Bash") is ToolCategory.COMMAND
    assert categorize_tool_name("Read") is ToolCategory.FILE_READ
    assert categorize_tool_name("Grep") is ToolCategory.SEARCH
    assert categorize_tool_name("Edit") is ToolCategory.FILE_WRITE
    assert categorize_tool_name("WebFetch") is ToolCategory.NETWORK
    assert categorize_tool_name("Task") is ToolCategory.SUBAGENT
    assert categorize_tool_name("mcp__acme-internal-jira__create_issue") is ToolCategory.MCP
    assert categorize_tool_name("SomethingNew") is ToolCategory.UNKNOWN
    assert categorize_tool_name(None) is ToolCategory.UNKNOWN


def test_project_display_label_is_a_bounded_basename_and_never_a_home_dir() -> None:
    assert project_display_label(CANARY_CWD) == "CANARY-PROJECT-DIR"
    assert project_display_label("C:\\Work\\prompt-enhancer") == "prompt-enhancer"
    assert project_display_label("/home/example-user") is None
    assert project_display_label("C:\\Users\\example-user") is None
    assert project_display_label("relative/path") is None
    assert project_display_label(None) is None


# --- minimize ---------------------------------------------------------------


def test_minimize_discards_content_and_pseudonymizes_identifiers() -> None:
    event = minimize_payload(
        _payload("PostToolUse", tool_name="Bash", tool_use_id=CANARY_TOOL_USE,
                 tool_input={"command": CANARY_TOOL_INPUT},
                 tool_response={"stdout": CANARY_TOOL_RESPONSE}),
        pseudonymizer=KEY, received_at=T0,
    )
    assert event is not None
    assert event.hook_event_name is HookEventName.POST_TOOL_USE
    assert event.event_kind is EventKind.TOOL_END
    assert event.tool_category is ToolCategory.COMMAND
    assert event.success is True
    assert re.fullmatch(r"[a-f0-9]{64}", event.hook_session_id)
    assert re.fullmatch(r"[a-f0-9]{64}", event.hook_project_id)
    assert event.tool_use_ref is not None and re.fullmatch(r"[a-f0-9]{64}", event.tool_use_ref)
    assert event.project_display_label == "CANARY-PROJECT-DIR"
    _assert_no_canary(repr(event))
    _assert_no_canary(event.model_dump_json())


def test_minimize_maps_every_lifecycle_hook_and_skips_notification() -> None:
    cases = {
        "SessionStart": (EventKind.SESSION_START, {"source": "resume"}),
        "SessionEnd": (EventKind.SESSION_END, {"reason": "logout"}),
        "UserPromptSubmit": (EventKind.TURN_START, {"prompt": "Describe the request\n" + CANARY_PROMPT}),
        "PreToolUse": (EventKind.TOOL_START, {"tool_name": "Read", "tool_input": {"file_path": CANARY_TOOL_INPUT}}),
        "Stop": (EventKind.TURN_END, {"stop_hook_active": False}),
        "SubagentStop": (EventKind.SUBAGENT_END, {"stop_hook_active": False}),
        "PreCompact": (EventKind.COMPACTION, {"trigger": "auto", "custom_instructions": CANARY_PROMPT}),
        "SomeFutureHook": (EventKind.UNKNOWN, {}),
    }
    for name, (kind, extra) in cases.items():
        event = minimize_payload(_payload(name, **extra), pseudonymizer=KEY, received_at=T0)
        assert event is not None, name
        assert event.event_kind is kind, name
        _assert_no_canary(repr(event))
    assert minimize_payload(
        _payload("Notification", message=CANARY_MESSAGE), pseudonymizer=KEY, received_at=T0
    ) is None
    start = minimize_payload(_payload("SessionStart", source="resume"), pseudonymizer=KEY, received_at=T0)
    assert start is not None and start.session_start_source is SessionStartSource.RESUME
    end = minimize_payload(_payload("SessionEnd", reason="logout"), pseudonymizer=KEY, received_at=T0)
    assert end is not None and end.session_end_reason is SessionEndReason.LOGOUT
    pre = minimize_payload(_payload("PreToolUse", tool_name="Read"), pseudonymizer=KEY, received_at=T0)
    assert pre is not None and pre.success is None


def test_minimize_rejects_missing_or_unsafe_session_identifier() -> None:
    for bad in (None, "", "x" * 300, "with\nnewline", 12345):
        payload = _payload("Stop")
        payload["session_id"] = bad
        with pytest.raises(ValueError):
            minimize_payload(payload, pseudonymizer=KEY, received_at=T0)


def test_same_directory_yields_same_project_pseudonym_across_sessions() -> None:
    a = minimize_payload(_payload("Stop"), pseudonymizer=KEY, received_at=T0)
    b_payload = _payload("Stop"); b_payload["session_id"] = "other-session"
    b_payload["cwd"] = "D:\\srv\\example-workspaces\\CANARY-PROJECT-DIR\\"
    b = minimize_payload(b_payload, pseudonymizer=KEY, received_at=T0)
    assert a is not None and b is not None
    assert a.hook_session_id != b.hook_session_id
    # Different drive syntax -> different normalized path; same posix path -> same id.
    c_payload = _payload("Stop"); c_payload["session_id"] = "third"
    c_payload["cwd"] = CANARY_CWD + "/"
    c = minimize_payload(c_payload, pseudonymizer=KEY, received_at=T0)
    assert c is not None and c.hook_project_id == a.hook_project_id


def test_session_title_is_first_prompt_line_only_bounded_and_switchable() -> None:
    from prompt_enhancer.infrastructure.providers.claude_code_hooks.receiver import session_titles_enabled

    prompt = "  Add retries to the uploader for the demo project  \n" + "CANARY-SECOND-LINE " * 3 + "\n" + CANARY_TOOL_INPUT
    event = minimize_payload(_payload("UserPromptSubmit", prompt=prompt), pseudonymizer=KEY, received_at=T0)
    assert event is not None
    assert event.session_display_label == "Add retries to the uploader for the demo project"
    assert "CANARY-SECOND-LINE" not in event.model_dump_json()
    long_event = minimize_payload(_payload("UserPromptSubmit", prompt="x" * 500), pseudonymizer=KEY, received_at=T0)
    assert long_event is not None and long_event.session_display_label is not None
    assert len(long_event.session_display_label) <= 96 and long_event.session_display_label.endswith("...")
    path_event = minimize_payload(_payload("UserPromptSubmit", prompt="/home/example-user/secret.txt\nreal request"), pseudonymizer=KEY, received_at=T0)
    assert path_event is not None and path_event.session_display_label is None
    off = minimize_payload(_payload("UserPromptSubmit", prompt=CANARY_PROMPT), pseudonymizer=KEY, received_at=T0, titles=False)
    assert off is not None and off.session_display_label is None
    other = minimize_payload(_payload("Stop", prompt=CANARY_PROMPT), pseudonymizer=KEY, received_at=T0)
    assert other is not None and other.session_display_label is None
    assert session_titles_enabled({}) is True
    assert session_titles_enabled({"PROMPT_ENHANCER_CLAUDE_SESSION_TITLES": "0"}) is False
    assert session_titles_enabled({"PROMPT_ENHANCER_CLAUDE_SESSION_TITLES": "off"}) is False


def test_receiver_persists_the_first_title_and_keeps_it(consented_home: Path) -> None:
    settings = AppSettings(home=consented_home)
    clock = iter(T0 + timedelta(seconds=i) for i in range(10))
    now = lambda: next(clock)  # noqa: E731
    receive(_stdin(_payload("SessionStart", source="startup")), settings=settings, now=now)
    receive(_stdin(_payload("UserPromptSubmit", prompt="First request title\nCANARY-BODY")), settings=settings, now=now)
    receive(_stdin(_payload("UserPromptSubmit", prompt="Second request CANARY-LATER")), settings=settings, now=now)
    connection = sqlite3.connect(consented_home / "metrics.sqlite3")
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute("SELECT session_display_label FROM claude_code_hook_sessions").fetchone()
        assert row["session_display_label"] == "First request title"
    finally:
        connection.close()
    dump = _ledger_dump(consented_home)
    assert "CANARY-BODY" not in dump and "CANARY-LATER" not in dump


# --- receiver end to end ------------------------------------------------------


def test_receiver_appends_nothing_without_consent(app_home: Path) -> None:
    outcome = receive(_stdin(_payload("Stop")), settings=AppSettings(home=app_home))
    assert outcome.status is ReceiverStatus.CONSENT_INACTIVE
    assert _ledger_dump(app_home) == ""


def test_receiver_appends_nothing_when_store_is_absent(tmp_path: Path) -> None:
    outcome = receive(_stdin(_payload("Stop")), settings=AppSettings(home=tmp_path))
    # No key exists either, and it must not have been created.
    assert outcome.status is ReceiverStatus.KEY_UNAVAILABLE
    assert not (tmp_path / "pseudonym.key").exists()
    assert not (tmp_path / "metrics.sqlite3").exists()


def test_receiver_appends_a_content_free_record_with_consent(consented_home: Path, capsys) -> None:
    settings = AppSettings(home=consented_home)
    clock = iter(T0 + timedelta(seconds=i) for i in range(100))
    now = lambda: next(clock)  # noqa: E731
    sequence = [
        _payload("SessionStart", source="startup"),
        _payload("UserPromptSubmit", prompt="Plan the demo refactor\n" + CANARY_PROMPT),
        _payload("PreToolUse", tool_name="Bash", tool_use_id=CANARY_TOOL_USE,
                 tool_input={"command": CANARY_TOOL_INPUT}),
        _payload("PostToolUse", tool_name="Bash", tool_use_id=CANARY_TOOL_USE,
                 tool_input={"command": CANARY_TOOL_INPUT},
                 tool_response={"stdout": CANARY_TOOL_RESPONSE}),
        _payload("Notification", message=CANARY_MESSAGE),
        _payload("PreCompact", trigger="auto", custom_instructions=CANARY_PROMPT),
        _payload("Stop", stop_hook_active=False),
        _payload("SessionEnd", reason="prompt_input_exit"),
    ]
    statuses = [receive(_stdin(p), settings=settings, now=now).status for p in sequence]
    assert statuses == [
        ReceiverStatus.APPENDED, ReceiverStatus.APPENDED, ReceiverStatus.APPENDED,
        ReceiverStatus.APPENDED, ReceiverStatus.SKIPPED_NOTIFICATION,
        ReceiverStatus.APPENDED, ReceiverStatus.APPENDED, ReceiverStatus.APPENDED,
    ]
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""

    dump = _ledger_dump(consented_home)
    _assert_no_canary(dump)
    connection = sqlite3.connect(consented_home / "metrics.sqlite3")
    connection.row_factory = sqlite3.Row
    try:
        session = connection.execute("SELECT * FROM claude_code_hook_sessions").fetchone()
        assert session["event_count"] == 7
        assert session["session_start_source"] == "startup"
        assert session["session_end_reason"] == "prompt_input_exit"
        assert session["ended_at"] is not None
        assert session["project_display_label"] == "CANARY-PROJECT-DIR"
        assert session["session_display_label"] == "Plan the demo refactor"
        events = connection.execute(
            "SELECT * FROM claude_code_hook_events ORDER BY sequence"
        ).fetchall()
        assert [e["sequence"] for e in events] == list(range(7))
        assert [e["event_kind"] for e in events] == [
            "session_start", "turn_start", "tool_start", "tool_end",
            "compaction", "turn_end", "session_end",
        ]
        tool_end = events[3]
        assert tool_end["success"] == 1
        assert tool_end["duration_ms"] == 1000  # PostToolUse one second after PreToolUse
        assert tool_end["tool_category"] == "command"
        assert tool_end["tool_use_ref"] == events[2]["tool_use_ref"]
        assert events[4]["compact_trigger"] == "auto"
        # No column anywhere holds a name, path, or text.
        columns = {c[1] for c in connection.execute("PRAGMA table_info(claude_code_hook_events)")}
        assert not columns & {"tool_name", "cwd", "prompt", "transcript_path", "message"}
    finally:
        connection.close()


def test_receiver_reopens_a_resumed_session(consented_home: Path) -> None:
    settings = AppSettings(home=consented_home)
    clock = iter(T0 + timedelta(seconds=i) for i in range(10))
    now = lambda: next(clock)  # noqa: E731
    receive(_stdin(_payload("SessionEnd", reason="logout")), settings=settings, now=now)
    receive(_stdin(_payload("SessionStart", source="resume")), settings=settings, now=now)
    connection = sqlite3.connect(consented_home / "metrics.sqlite3")
    connection.row_factory = sqlite3.Row
    try:
        session = connection.execute("SELECT * FROM claude_code_hook_sessions").fetchone()
        assert session["ended_at"] is None and session["session_end_reason"] is None
        assert session["event_count"] == 2
    finally:
        connection.close()


def test_receiver_survives_garbage_oversized_and_non_object_input(consented_home: Path, capsys) -> None:
    settings = AppSettings(home=consented_home)
    assert receive(io.BytesIO(b"\xff\xfe not json"), settings=settings).status is ReceiverStatus.INVALID_PAYLOAD
    assert receive(io.BytesIO(b"[1,2,3]"), settings=settings).status is ReceiverStatus.INVALID_PAYLOAD
    assert receive(io.BytesIO(b""), settings=settings).status is ReceiverStatus.INVALID_PAYLOAD
    big = io.BytesIO(b"{" + b" " * (hooks.__dict__["contracts"].MAX_HOOK_PAYLOAD_BYTES + 10) + b"}")
    assert receive(big, settings=settings).status is ReceiverStatus.INVALID_PAYLOAD
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""
    assert _ledger_dump(consented_home) == ""


def test_receiver_main_is_silent_and_exits_zero_even_on_failure(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(_stdin(_payload("Stop"))))
    assert receiver_module.main() == 0
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""
    assert not (tmp_path / "metrics.sqlite3").exists()


def test_receiver_append_refuses_a_store_older_than_the_ledger(tmp_path: Path) -> None:
    store = tmp_path / "metrics.sqlite3"
    connection = sqlite3.connect(store)
    connection.execute("PRAGMA user_version = 44")
    connection.commit(); connection.close()
    event = minimize_payload(_payload("Stop"), pseudonymizer=KEY, received_at=T0)
    assert event is not None
    with pytest.raises(HookLedgerUnavailable):
        receiver_append(store, KEY, event)


def test_receiver_append_refuses_without_consent_row(app_home: Path) -> None:
    event = minimize_payload(_payload("Stop"), pseudonymizer=KEY, received_at=T0)
    assert event is not None
    with pytest.raises(HookLedgerConsentInactive):
        receiver_append(app_home / "metrics.sqlite3", KEY, event)


def test_ledger_rows_are_immutable_and_cascade_only(consented_home: Path) -> None:
    settings = AppSettings(home=consented_home)
    receive(_stdin(_payload("Stop")), settings=settings)
    connection = sqlite3.connect(consented_home / "metrics.sqlite3")
    # Foreign-key enforcement can only be switched on outside a transaction.
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("UPDATE claude_code_hook_events SET sequence = 99")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM claude_code_hook_events")
        connection.execute("DELETE FROM claude_code_hook_sessions")
        assert connection.execute("SELECT COUNT(*) FROM claude_code_hook_events").fetchone()[0] == 0
    finally:
        connection.close()


def test_load_pseudonymizer_never_creates_a_key(tmp_path: Path) -> None:
    from prompt_enhancer.privacy import PrivacyBoundaryError

    with pytest.raises(PrivacyBoundaryError):
        load_pseudonymizer(tmp_path / "pseudonym.key")
    assert not (tmp_path / "pseudonym.key").exists()


def test_cli_consent_and_config_commands_write_nothing_private(tmp_path: Path, monkeypatch, capsys) -> None:
    from prompt_enhancer.cli import main

    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))
    assert main(["claude-consent-grant", "local-history"]) == 0
    assert Database(tmp_path / "metrics.sqlite3").has_active_consent(
        Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT
    )
    assert main(["claude-consent-revoke", "local-history"]) == 0
    assert not Database(tmp_path / "metrics.sqlite3").has_active_consent(
        Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT
    )
    capsys.readouterr()
    assert main(["claude-hooks-config"]) == 0
    out = capsys.readouterr().out
    config = json.loads(out)
    assert set(config["hooks"]) == {
        "SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse",
        "PostToolUse", "Stop", "SubagentStop", "PreCompact",
    }
    for entry in config["hooks"].values():
        assert entry[0]["hooks"][0]["command"].endswith("-m prompt_enhancer claude-hook")
    assert "Notification" not in config["hooks"]


def test_prompt_titles_are_shortened_at_a_word_boundary() -> None:
    from prompt_enhancer.infrastructure.providers.claude_code_hooks.contracts import (
        SESSION_TITLE_SOFT_LIMIT,
        session_title_from_prompt,
    )

    assert session_title_from_prompt("Add retries to the uploader") == "Add retries to the uploader"
    words = " ".join(f"word{i}" for i in range(40))
    title = session_title_from_prompt(words + "\nsecond line never read")
    assert title is not None and len(title) <= SESSION_TITLE_SOFT_LIMIT and title.endswith("...")
    assert not title[:-3].endswith(" ") and "second" not in title
    assert words.startswith(title[:-3])
    unbroken = session_title_from_prompt("x" * 300)
    assert unbroken is not None and len(unbroken) == SESSION_TITLE_SOFT_LIMIT and unbroken.endswith("...")
