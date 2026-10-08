"""Claude Code hook adapter: ledger -> ProviderAdapter -> ordinary ingestion.

The end-to-end test is the important one: fictional hook payloads go through
the real receiver, the real ledger, the real adapter, and the real ingestion
service, and the resulting rows in the main tables carry no canary and are
indistinguishable in shape from any other provider's.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import io
import json
from pathlib import Path
import re
import sqlite3

import pytest

from prompt_enhancer.adapters.base import AdapterHealth
from prompt_enhancer.application.providers import (
    CapabilityKey,
    CapabilityState,
    CompatibilityReasonCode,
    CompatibilityState,
    ExtractionCompletenessState,
    ProviderCompatibilityService,
    TrustedProviderRegistry,
)
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.domain import (
    DataTier,
    EventKind,
    EventTimeBasis,
    Provider,
    SessionState,
    ToolCategory,
)
from prompt_enhancer.infrastructure.providers.claude_code_hooks.adapter import (
    CLAUDE_CODE_HOOKS_DECODER_DESCRIPTOR,
    ClaudeCodeHookAdapter,
    ClaudeCodeHooksCompatibilityProbe,
    ClaudeHookLifecycleError,
    ClaudeHookScopeError,
)
from prompt_enhancer.infrastructure.providers.claude_code_hooks.receiver import (
    ReceiverStatus,
    receive,
)
from prompt_enhancer.ingestion import ConsentRequiredError


CANARY_CWD = "/srv/example-workspaces/CANARY-HOOK-PROJECT"
CANARY_SESSION = "CANARY-HOOK-SESSION-abc"
CANARY_PROMPT = "CANARY-PROMPT-add retries to the acme uploader"
CANARY_TOOL_INPUT = "CANARY-TOOL-INPUT-pytest tests/ -q"
CANARY_TOOL_OUT = "CANARY-TOOL-OUTPUT-3 passed"
CANARY_TRANSCRIPT = "/home/example-user/.claude/projects/CANARY-TRANSCRIPT.jsonl"
CANARIES = (
    CANARY_CWD, CANARY_SESSION, CANARY_PROMPT, CANARY_TOOL_INPUT,
    CANARY_TOOL_OUT, CANARY_TRANSCRIPT, "example-user", "acme", "toolu_",
)
T0 = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)


def _payload(name: str, session: str = CANARY_SESSION, cwd: str = CANARY_CWD, **extra: object) -> io.BytesIO:
    payload: dict[str, object] = {
        "session_id": session, "transcript_path": CANARY_TRANSCRIPT, "cwd": cwd,
        "hook_event_name": name,
    }
    payload.update(extra)
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


def _dump_whole_database(path: Path) -> str:
    connection = sqlite3.connect(path)
    try:
        chunks = []
        tables = [r[0] for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        for table in tables:
            for row in connection.execute(f'SELECT * FROM "{table}"').fetchall():
                chunks.append(repr(row))
        return "\n".join(chunks)
    finally:
        connection.close()


@pytest.fixture
def home(tmp_path: Path) -> Path:
    bootstrap_local_application(AppSettings(home=tmp_path))
    Database(tmp_path / "metrics.sqlite3").grant_consent(
        Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT
    )
    return tmp_path


def _drive_one_session(home: Path, *, session: str = CANARY_SESSION, cwd: str = CANARY_CWD, start: datetime = T0) -> None:
    settings = AppSettings(home=home)
    clock = iter(start + timedelta(seconds=i) for i in range(50))
    now = lambda: next(clock)  # noqa: E731
    steps = [
        _payload("SessionStart", session, cwd, source="startup"),
        _payload("UserPromptSubmit", session, cwd, prompt="Add retries to the uploader\n" + CANARY_PROMPT),
        _payload("PreToolUse", session, cwd, tool_name="Bash", tool_use_id="toolu_1",
                 tool_input={"command": CANARY_TOOL_INPUT}),
        _payload("PostToolUse", session, cwd, tool_name="Bash", tool_use_id="toolu_1",
                 tool_input={"command": CANARY_TOOL_INPUT}, tool_response={"stdout": CANARY_TOOL_OUT}),
        _payload("PreToolUse", session, cwd, tool_name="Edit", tool_use_id="toolu_2", tool_input={}),
        _payload("Stop", session, cwd, stop_hook_active=False),
        _payload("SessionEnd", session, cwd, reason="prompt_input_exit"),
    ]
    for step in steps:
        assert receive(step, settings=settings, now=now).status is ReceiverStatus.APPENDED


def test_adapter_requires_probe_and_scopes_reads_to_the_snapshot(home: Path) -> None:
    _drive_one_session(home)
    adapter = ClaudeCodeHookAdapter(Database(home / "metrics.sqlite3").claude_hook_ledger())
    with pytest.raises(ClaudeHookLifecycleError):
        adapter.list_sessions()
    probe = adapter.probe()
    assert probe.health is AdapterHealth.READY
    assert probe.provider is Provider.CLAUDE_CODE
    assert probe.supports_content is False and probe.supports_watch is False
    page = adapter.list_sessions(limit=10)
    assert len(page.sessions) == 1 and page.next_cursor is None
    session = page.sessions[0]
    assert session.provider is Provider.CLAUDE_CODE
    assert session.terminal_state is SessionState.COMPLETED
    assert session.events_complete is False
    assert session.source_project_display_name is not None
    assert session.source_project_display_name.get_secret_value() == "CANARY-HOOK-PROJECT"
    assert session.source_session_display_name is not None
    assert session.source_session_display_name.get_secret_value() == "Add retries to the uploader"
    # Identifiers yielded are already pseudonyms.
    assert re.fullmatch(r"[a-f0-9]{64}", session.source_session_id.get_secret_value())
    assert re.fullmatch(r"[a-f0-9]{64}", session.source_project_id.get_secret_value())

    snapshot = adapter.read_session(session)
    kinds = [e.kind for e in snapshot.events]
    assert kinds == [
        EventKind.SESSION_START, EventKind.TURN_START, EventKind.TOOL_START,
        EventKind.TOOL_END, EventKind.TOOL_START, EventKind.TURN_END, EventKind.SESSION_END,
    ]
    tool_end = snapshot.events[3]
    assert tool_end.tool_category is ToolCategory.COMMAND
    assert tool_end.success is True and tool_end.duration_ms == 1000
    unpaired = snapshot.events[4]
    assert unpaired.tool_category is ToolCategory.FILE_WRITE
    assert unpaired.success is None and unpaired.duration_ms is None
    assert all(e.usage is None for e in snapshot.events)
    assert all(
        event.time_basis is EventTimeBasis.RECEIVER_OBSERVED
        for event in snapshot.events
    )

    # A session that was not listed in this snapshot cannot be read.
    stranger = session.model_copy(update={"source_session_id": session.source_session_id.__class__("f" * 64)})
    with pytest.raises(ClaudeHookScopeError):
        adapter.read_session(stranger)
    adapter.close()
    with pytest.raises(ClaudeHookLifecycleError):
        adapter.probe()


def test_adapter_pages_with_opaque_keyset_cursors(home: Path) -> None:
    for index in range(5):
        _drive_one_session(home, session=f"session-{index}", start=T0 + timedelta(hours=index))
    adapter = ClaudeCodeHookAdapter(Database(home / "metrics.sqlite3").claude_hook_ledger())
    adapter.probe()
    first = adapter.list_sessions(limit=2)
    assert len(first.sessions) == 2 and first.next_cursor == "p1"
    second = adapter.list_sessions(cursor="p1", limit=2)
    assert len(second.sessions) == 2 and second.next_cursor == "p2"
    third = adapter.list_sessions(cursor="p2", limit=2)
    assert len(third.sessions) == 1 and third.next_cursor is None
    seen = {s.source_session_id.get_secret_value() for p in (first, second, third) for s in p.sessions}
    assert len(seen) == 5
    with pytest.raises(ClaudeHookScopeError):
        adapter.list_sessions(cursor="p1", limit=2)  # consumed cursor
    with pytest.raises(ClaudeHookScopeError):
        adapter.list_sessions(cursor="p9", limit=2)


def test_terminal_state_maps_only_documented_end_reasons(home: Path) -> None:
    settings = AppSettings(home=home)
    for index, (reason, expected) in enumerate((
        ("prompt_input_exit", SessionState.COMPLETED),
        ("logout", SessionState.INTERRUPTED),
        ("clear", SessionState.UNKNOWN),
        ("other", SessionState.UNKNOWN),
        ("something-new", SessionState.UNKNOWN),
    )):
        session = f"s-{index}"
        receive(_payload("SessionStart", session, source="startup"), settings=settings,
                now=lambda i=index: T0 + timedelta(hours=i))
        receive(_payload("SessionEnd", session, reason=reason), settings=settings,
                now=lambda i=index: T0 + timedelta(hours=i, minutes=1))
    receive(_payload("Stop", "s-live"), settings=settings, now=lambda: T0 + timedelta(hours=9))
    adapter = ClaudeCodeHookAdapter(Database(home / "metrics.sqlite3").claude_hook_ledger())
    adapter.probe()
    states = [s.terminal_state for s in adapter.list_sessions(limit=50).sessions]
    assert states == [
        SessionState.COMPLETED, SessionState.INTERRUPTED, SessionState.UNKNOWN,
        SessionState.UNKNOWN, SessionState.UNKNOWN, SessionState.UNKNOWN,
    ]


def test_end_to_end_ingestion_persists_pseudonymous_content_free_rows(home: Path) -> None:
    _drive_one_session(home)
    application = bootstrap_local_application(AppSettings(home=home))
    adapter = ClaudeCodeHookAdapter(application.database.claude_hook_ledger())
    report = application.create_ingestion_service().ingest(adapter)
    assert report.sessions_seen == 1
    assert report.events_seen == 7

    rows = application.database.list_sessions(limit=50, offset=0)
    claude_rows = [r for r in rows if r.get("provider") == "claude_code"]
    assert len(claude_rows) == 1
    session_id = str(claude_rows[0]["session_id"])
    assert re.fullmatch(r"[a-f0-9]{64}", session_id)
    safe_session = application.database.get_session(session_id)
    assert safe_session is not None
    assert safe_session.provider is Provider.CLAUDE_CODE
    assert safe_session.terminal_state is SessionState.COMPLETED
    assert safe_session.project_display_name == "CANARY-HOOK-PROJECT"
    assert safe_session.session_display_name == "Add retries to the uploader"
    events = application.database.get_session_events(session_id)
    assert [e.kind for e in events] == [
        EventKind.SESSION_START, EventKind.TURN_START, EventKind.TOOL_START,
        EventKind.TOOL_END, EventKind.TOOL_START, EventKind.TURN_END, EventKind.SESSION_END,
    ]
    assert events[3].duration_ms == 1000 and events[3].success is True
    assert all(
        event.time_basis is EventTimeBasis.RECEIVER_OBSERVED for event in events
    )
    # Second ingestion is idempotent.
    again = application.create_ingestion_service().ingest(
        ClaudeCodeHookAdapter(application.database.claude_hook_ledger())
    )
    assert again.sessions_inserted == 0 and again.events_inserted == 0

    dump = _dump_whole_database(home / "metrics.sqlite3")
    for canary in CANARIES:
        assert canary not in dump, canary


def test_ingestion_refuses_without_claude_consent(tmp_path: Path) -> None:
    application = bootstrap_local_application(AppSettings(home=tmp_path))
    adapter = ClaudeCodeHookAdapter(application.database.claude_hook_ledger())
    with pytest.raises(ConsentRequiredError):
        application.create_ingestion_service().ingest(adapter)


def test_same_directory_yields_the_same_project_for_two_sessions(home: Path) -> None:
    _drive_one_session(home, session="one")
    _drive_one_session(home, session="two", cwd="D:\\srv\\example-workspaces\\CANARY-HOOK-PROJECT", start=T0 + timedelta(hours=1))
    _drive_one_session(home, session="three", cwd="/srv/other/CANARY-OTHER", start=T0 + timedelta(hours=2))
    application = bootstrap_local_application(AppSettings(home=home))
    application.create_ingestion_service().ingest(
        ClaudeCodeHookAdapter(application.database.claude_hook_ledger())
    )
    rows = [r for r in application.database.list_sessions(limit=50, offset=0) if r.get("provider") == "claude_code"]
    projects = {str(r["project_id"]) for r in rows}
    # Windows drive syntax is a different normalized path than the POSIX one,
    # so 'two' is its own project; 'three' is another.  Never merged by label.
    assert len(rows) == 3 and len(projects) == 3


def test_compatibility_probe_reports_degraded_unknown_completeness_and_registers(home: Path) -> None:
    _drive_one_session(home)
    ledger = Database(home / "metrics.sqlite3").claude_hook_ledger()
    probe = ClaudeCodeHooksCompatibilityProbe(ledger)
    report = probe.check()
    assert report.state is CompatibilityState.DEGRADED
    assert report.extraction.state is ExtractionCompletenessState.UNKNOWN
    assert report.extraction.observed_units == 7
    assert {c.key for c in report.capabilities} == set(CLAUDE_CODE_HOOKS_DECODER_DESCRIPTOR.capabilities)
    token_usage = next(
        item for item in report.capabilities if item.key is CapabilityKey.TOKEN_USAGE
    )
    assert token_usage.state is CapabilityState.UNKNOWN
    assert token_usage.reason_code is CompatibilityReasonCode.OPTIONAL_CAPABILITY_MISSING
    assert all(
        item.state is CapabilityState.SUPPORTED
        for item in report.capabilities
        if item.key is not CapabilityKey.TOKEN_USAGE
    )
    assert [r.code for r in report.reasons] == [
        CompatibilityReasonCode.PROVIDER_VERSION_UNKNOWN,
        CompatibilityReasonCode.COMPLETE_DELIVERY_UNPROVEN,
        CompatibilityReasonCode.EPHEMERAL_DESCRIPTORS_UNAVAILABLE,
        CompatibilityReasonCode.OPTIONAL_CAPABILITY_MISSING,
    ]
    # No opportunity, link, or message-content capability is ever claimed.
    forbidden = {k for k in CapabilityKey if k.value.endswith(("_opportunities", "_links"))} | {
        CapabilityKey.USER_MESSAGES, CapabilityKey.AGENT_MESSAGES, CapabilityKey.PLAN_MESSAGES,
        CapabilityKey.VERIFICATION_EVENTS, CapabilityKey.DECISION_EVENTS, CapabilityKey.LIVE_UPDATES,
    }
    assert not forbidden & set(CLAUDE_CODE_HOOKS_DECODER_DESCRIPTOR.capabilities)
    assert CapabilityKey.EVENT_TIMING in CLAUDE_CODE_HOOKS_DECODER_DESCRIPTOR.capabilities
    # TOKEN_USAGE is supplied by the loopback OTLP receiver (decoder version 2).
    assert CapabilityKey.TOKEN_USAGE in CLAUDE_CODE_HOOKS_DECODER_DESCRIPTOR.capabilities

    registry = TrustedProviderRegistry((CLAUDE_CODE_HOOKS_DECODER_DESCRIPTOR,))
    service = ProviderCompatibilityService(registry, (probe,))
    refreshed = service.refresh(
        "claude_code", "operational_events",
        decoder_key=CLAUDE_CODE_HOOKS_DECODER_DESCRIPTOR.decoder_key,
        decoder_version=CLAUDE_CODE_HOOKS_DECODER_DESCRIPTOR.decoder_version,
    )
    assert refreshed.state is CompatibilityState.DEGRADED


def test_compatibility_probe_is_unavailable_when_the_ledger_cannot_be_read() -> None:
    from prompt_enhancer.infrastructure.providers.claude_code_hooks.ledger import SqliteClaudeHookLedger

    def broken_scope(*, readonly: bool = False):
        raise sqlite3.OperationalError("no store")

    probe = ClaudeCodeHooksCompatibilityProbe(SqliteClaudeHookLedger(broken_scope, lambda: None))
    report = probe.check()
    assert report.state is CompatibilityState.UNAVAILABLE
    assert all(c.state is CapabilityState.UNKNOWN for c in report.capabilities)
    assert [r.code for r in report.reasons] == [CompatibilityReasonCode.PROVIDER_UNAVAILABLE]

    adapter = ClaudeCodeHookAdapter(SqliteClaudeHookLedger(broken_scope, lambda: None))
    assert adapter.probe().health is AdapterHealth.UNAVAILABLE
    with pytest.raises(ClaudeHookLifecycleError):
        adapter.list_sessions()
