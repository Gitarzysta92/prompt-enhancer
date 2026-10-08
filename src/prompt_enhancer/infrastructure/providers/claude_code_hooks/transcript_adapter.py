"""Read-only ``ProviderAdapter`` over the owner's Claude Code transcript files.

Owner-authorized (ADR 0011) and, per the owner's direction, the default
Claude Code source: it indexes every session under ``<claude home>/projects``
— history included — with the provider's own timestamps, per-response token
usage from ``message.usage``, tool calls with their results and ``is_error``,
compaction markers, the project from ``cwd``, and a title from the first
prompt.  Hooks remain the live signal; where a transcript exists it is the
single source of record for events so nothing is counted twice.

Identity is the same chain the hook receiver uses (session pseudonym from the
filename stem, project pseudonym from the normalized ``cwd``), so a session
captured by both channels resolves to one catalog row.  Nothing is written,
nothing is modified, and no raw identifier is persisted.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
import json
from pathlib import Path

from pydantic import SecretStr

from ....application.runtime_cancellation import raise_if_runtime_cancelled

from ....adapters.base import AdapterHealth, AdapterProbe, ProviderAdapter
from ....application.analysis.text_contracts import (
    MAX_ACTION_REVIEW_DESCRIPTORS,
    MAX_ACTION_REVIEW_PREVIEW_CHARACTERS,
    MAX_ACTION_REVIEW_TOOL_NAME_CHARACTERS,
    MAX_ACTION_REVIEW_TOTAL_CHARACTERS,
)
from ....application.analysis.evidence_contracts import ActionFamily, ActionState
from ....application.analysis.provider_evidence import (
    requirement_action_family_for_tool_category,
    requirement_action_state_for_event,
)
from ....domain import (
    DataTier,
    EventKind,
    EventTimeBasis,
    Provider,
    SessionState,
    SourceEvent,
    SourceSession,
    SourceSessionPage,
    SourceSessionSnapshot,
    ToolCategory,
    UsageCounterKind,
    UsageRecord,
    UsageScope,
)
from ....privacy import Pseudonymizer
from .contracts import (
    HOOK_INSTALLATION_MARKER,
    PSEUDONYM_NAMESPACE_PROJECT,
    PSEUDONYM_NAMESPACE_SESSION,
    UNKNOWN_PROVIDER_VERSION,
    categorize_tool_name,
    classify_command,
    project_display_label,
    project_identity_material,
    session_title_from_prompt,
)
from .transcript_reader import (
    MAX_TRANSCRIPT_FILE_BYTES,
    MAX_TRANSCRIPT_FILES_SCANNED,
    MAX_TRANSCRIPT_LINES,
    default_claude_home,
)


TRANSCRIPT_ADAPTER_VERSION = "claude-code-transcripts-adapter-1"
TRANSCRIPT_SOURCE_SCHEMA_VERSION = "claude-code-transcripts.jsonl.v1"
MAX_TRANSCRIPT_PAGE_SIZE = 500
MAX_TRANSCRIPT_PAGES = 200
HEAD_LINES = 60
USAGE_SEQUENCE_BASE = 3_000_000  # disjoint from hook (0+) and OTLP (1_000_000+) usage
_KNOWN_TYPES = {"user", "assistant", "system", "summary", "queue-operation"}
_USER_CONTENT_BLOCK_TYPES = frozenset({"text", "tool_result"})
_ASSISTANT_CONTENT_BLOCK_TYPES = frozenset(
    {"text", "thinking", "redacted_thinking", "tool_use"}
)


class TranscriptAdapterError(RuntimeError):
    pass


class TranscriptScopeError(TranscriptAdapterError):
    pass


class TranscriptLifecycleError(TranscriptAdapterError):
    pass


@dataclass(frozen=True, slots=True)
class TranscriptFile:
    path: Path
    stem: str
    modified_at: datetime
    size: int


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _safe_version(value: object) -> str | None:
    if isinstance(value, str) and 0 < len(value) <= 64 and all(c.isalnum() or c in "._+-" for c in value):
        return value
    return None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def scan_transcripts(claude_home: Path) -> tuple[TranscriptFile, ...]:
    """Every transcript file, newest modified first; bounded and symlink-free."""

    projects = claude_home / "projects"
    if not projects.is_dir():
        return ()
    found: list[TranscriptFile] = []
    scanned = 0
    for project_dir in sorted(projects.iterdir()):
        raise_if_runtime_cancelled("claude_transcript_scan_cancelled")
        if not project_dir.is_dir() or project_dir.is_symlink():
            continue
        for candidate in sorted(project_dir.glob("*.jsonl")):
            raise_if_runtime_cancelled("claude_transcript_scan_cancelled")
            scanned += 1
            if scanned > MAX_TRANSCRIPT_FILES_SCANNED:
                raise TranscriptAdapterError("transcript scan exceeded its file bound")
            if candidate.is_symlink() or not candidate.is_file():
                continue
            stem = candidate.stem
            if not stem or len(stem) > 256:
                continue
            try:
                stat = candidate.stat()
            except OSError:
                continue
            if stat.st_size > MAX_TRANSCRIPT_FILE_BYTES:
                continue
            found.append(TranscriptFile(
                path=candidate, stem=stem,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC), size=stat.st_size,
            ))
    found.sort(key=lambda item: (item.modified_at, item.stem), reverse=True)
    return tuple(found)


@dataclass(frozen=True, slots=True)
class TranscriptHead:
    cwd: str | None
    first_at: datetime | None
    title: str | None
    version: str | None


def read_head(
    path: Path,
    *,
    snapshot_text: str | None = None,
) -> TranscriptHead:
    """Metadata from the first lines only, so listing thousands of files stays cheap."""

    cwd = None
    first_at = None
    title = None
    version = None
    try:
        with (
            StringIO(snapshot_text)
            if snapshot_text is not None
            else path.open("r", encoding="utf-8", errors="replace")
        ) as handle:
            for index, line in enumerate(handle):
                if index >= HEAD_LINES:
                    break
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict):
                    continue
                if cwd is None and isinstance(record.get("cwd"), str):
                    cwd = record["cwd"]
                if version is None:
                    version = _safe_version(record.get("version"))
                at = _timestamp(record.get("timestamp"))
                if at is not None and (first_at is None or at < first_at):
                    first_at = at
                if title is None and record.get("type") == "user":
                    message = record.get("message")
                    if isinstance(message, dict):
                        content = message.get("content")
                        text = content if isinstance(content, str) else None
                        if text is None and isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                                    text = block["text"]
                                    break
                        if text is not None:
                            title = session_title_from_prompt(text)
                if cwd is not None and first_at is not None and title is not None and version is not None:
                    break
    except OSError:
        pass
    return TranscriptHead(cwd=cwd, first_at=first_at, title=title, version=version)


@dataclass(frozen=True, slots=True)
class ParsedTranscript:
    events: tuple[SourceEvent, ...]
    action_details: tuple["TranscriptActionDetail", ...]
    action_descriptor_extraction_complete: bool
    first_at: datetime | None
    last_at: datetime | None
    complete: bool


@dataclass(frozen=True, slots=True)
class TranscriptActionDetail:
    """Private bounded action detail; consumed only by the local review source."""

    source_event_id: SecretStr
    event_kind: EventKind
    tool_category: ToolCategory | None
    occurred_at: datetime
    duration_ms: int | None
    family: ActionFamily
    state: ActionState
    tool_name: SecretStr
    invocation_preview: SecretStr
    result_or_effect_preview: SecretStr | None
    invocation_truncated: bool
    result_or_effect_truncated: bool


def _private_json_preview(value: object) -> tuple[SecretStr, bool]:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        rendered = "unsupported"
    if not rendered or "\x00" in rendered:
        rendered = "unsupported"
    truncated = len(rendered) > MAX_ACTION_REVIEW_PREVIEW_CHARACTERS
    if truncated:
        rendered = rendered[:MAX_ACTION_REVIEW_PREVIEW_CHARACTERS]
    return SecretStr(rendered), truncated


def parse_events(
    path: Path,
    stem: str,
    *,
    snapshot_text: str | None = None,
) -> ParsedTranscript:
    """Deterministic event stream from one transcript; provider-reported times."""

    events: list[SourceEvent] = []
    sequence = 0
    usage_sequence = 0
    first_at: datetime | None = None
    last_at: datetime | None = None
    complete = True
    action_descriptor_complete = True
    action_details: list[TranscriptActionDetail] = []
    action_descriptor_characters = 0
    open_tools: dict[
        str,
        tuple[datetime | None, ToolCategory, str, SecretStr, bool],
    ] = {}
    seen_tool_refs: set[str] = set()
    last_assistant_at: datetime | None = None
    turn_open = False

    def emit(kind: EventKind, at: datetime, **fields: object) -> str:
        nonlocal sequence
        source_event_id = f"{stem}:e:{sequence}"
        events.append(SourceEvent(
            source_event_id=SecretStr(source_event_id),
            kind=kind, sequence=sequence, occurred_at=at,
            time_basis=EventTimeBasis.PROVIDER_REPORTED, **fields,  # type: ignore[arg-type]
        ))
        sequence += 1
        return source_event_id

    def add_action_detail(detail: TranscriptActionDetail) -> None:
        nonlocal action_descriptor_complete, action_descriptor_characters
        characters = (
            len(detail.tool_name.get_secret_value())
            + len(detail.invocation_preview.get_secret_value())
            + (
                0
                if detail.result_or_effect_preview is None
                else len(detail.result_or_effect_preview.get_secret_value())
            )
        )
        if (
            len(action_details) >= MAX_ACTION_REVIEW_DESCRIPTORS
            or action_descriptor_characters + characters
            > MAX_ACTION_REVIEW_TOTAL_CHARACTERS
        ):
            action_descriptor_complete = False
            return
        action_details.append(detail)
        action_descriptor_characters += characters

    try:
        with (
            StringIO(snapshot_text)
            if snapshot_text is not None
            else path.open("r", encoding="utf-8", errors="replace")
        ) as handle:
            for index, line in enumerate(handle):
                raise_if_runtime_cancelled("claude_transcript_parse_cancelled")
                if index >= MAX_TRANSCRIPT_LINES:
                    complete = False
                    break
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    complete = False
                    action_descriptor_complete = False
                    continue
                if not isinstance(record, dict):
                    complete = False
                    action_descriptor_complete = False
                    continue
                kind = record.get("type")
                if kind not in _KNOWN_TYPES:
                    complete = False
                    action_descriptor_complete = False
                    continue
                if kind in {"summary", "queue-operation"}:
                    # These provider bookkeeping rows carry no user text or
                    # action event and are intentionally outside the event set.
                    continue
                at = _timestamp(record.get("timestamp"))
                if at is None:
                    # Never substitute an earlier timestamp while claiming the
                    # event time was provider-reported. An action-bearing row
                    # without a usable time makes the exact event set incomplete.
                    complete = False
                    action_descriptor_complete = False
                    continue
                if first_at is None or at < first_at:
                    first_at = at
                if last_at is None or at > last_at:
                    last_at = at
                if kind == "system":
                    if record.get("subtype") == "compact_boundary":
                        emit(EventKind.COMPACTION, at)
                    continue
                message = record.get("message")
                if kind not in ("user", "assistant"):
                    continue
                if not isinstance(message, dict):
                    complete = False
                    action_descriptor_complete = False
                    continue
                content = message.get("content")
                if isinstance(content, list):
                    blocks = content
                elif isinstance(content, str):
                    blocks = [{"type": "text", "text": content}]
                else:
                    complete = False
                    action_descriptor_complete = False
                    continue
                allowed_block_types = (
                    _USER_CONTENT_BLOCK_TYPES
                    if kind == "user"
                    else _ASSISTANT_CONTENT_BLOCK_TYPES
                )
                malformed_or_unknown_block = any(
                    not isinstance(block, dict)
                    or block.get("type") not in allowed_block_types
                    for block in blocks
                )
                if malformed_or_unknown_block:
                    complete = False
                    action_descriptor_complete = False
                if kind == "user":
                    if any(
                        isinstance(block, dict)
                        and block.get("type") == "text"
                        and not isinstance(block.get("text"), str)
                        for block in blocks
                    ):
                        complete = False
                        action_descriptor_complete = False
                    has_text = any(
                        isinstance(block, dict)
                        and block.get("type") == "text"
                        and isinstance(block.get("text"), str)
                        and block["text"].strip()
                        for block in blocks
                    )
                    for block in blocks:
                        if not isinstance(block, dict) or block.get("type") != "tool_result":
                            continue
                        ref = block.get("tool_use_id")
                        opened = open_tools.pop(ref, None) if isinstance(ref, str) else None
                        duration = None
                        category = ToolCategory.UNKNOWN
                        if opened is not None:
                            (
                                opened_at,
                                category,
                                tool_name,
                                invocation_preview,
                                invocation_truncated,
                            ) = opened
                            if opened_at is not None and at >= opened_at:
                                duration = round((at - opened_at).total_seconds() * 1000)
                        is_error = block.get("is_error")
                        success = (
                            (not is_error)
                            if isinstance(is_error, bool)
                            else None
                        )
                        end_source_id = emit(
                            EventKind.TOOL_END,
                            at,
                            duration_ms=duration,
                            success=success,
                            tool_category=category,
                        )
                        if opened is None:
                            complete = False
                            action_descriptor_complete = False
                        else:
                            result_preview, result_truncated = _private_json_preview(
                                {
                                    "content": block.get("content"),
                                    "is_error": is_error,
                                }
                            )
                            add_action_detail(
                                TranscriptActionDetail(
                                    source_event_id=SecretStr(end_source_id),
                                    event_kind=EventKind.TOOL_END,
                                    tool_category=category,
                                    occurred_at=at,
                                    duration_ms=duration,
                                    family=(
                                        requirement_action_family_for_tool_category(
                                            category
                                        )
                                    ),
                                    state=requirement_action_state_for_event(
                                        EventKind.TOOL_END,
                                        success,
                                    ),
                                    tool_name=SecretStr(tool_name),
                                    invocation_preview=invocation_preview,
                                    result_or_effect_preview=result_preview,
                                    invocation_truncated=invocation_truncated,
                                    result_or_effect_truncated=result_truncated,
                                )
                            )
                            if invocation_truncated or result_truncated:
                                action_descriptor_complete = False
                    if has_text:
                        if turn_open and last_assistant_at is not None:
                            emit(EventKind.TURN_END, last_assistant_at)
                        emit(EventKind.TURN_START, at)
                        turn_open = True
                else:
                    last_assistant_at = at
                    for block in blocks:
                        if (
                            isinstance(block, dict)
                            and block.get("type") == "text"
                            and not isinstance(block.get("text"), str)
                        ):
                            complete = False
                            action_descriptor_complete = False
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            category = categorize_tool_name(block.get("name"))
                            tool_input = block.get("input")
                            if category is ToolCategory.COMMAND:
                                # Deterministic test/build recognition; the
                                # command text is classified and dropped.
                                command = tool_input.get("command") if isinstance(tool_input, dict) else None
                                category = classify_command(command)
                            ref = block.get("id")
                            name = block.get("name")
                            tool_name = (
                                name
                                if isinstance(name, str)
                                and 0 < len(name) <= MAX_ACTION_REVIEW_TOOL_NAME_CHARACTERS
                                and "\x00" not in name
                                else "unsupported"
                            )
                            invocation_preview, invocation_truncated = (
                                _private_json_preview(tool_input)
                            )
                            start_source_id = emit(
                                EventKind.TOOL_START,
                                at,
                                tool_category=category,
                            )
                            add_action_detail(
                                TranscriptActionDetail(
                                    source_event_id=SecretStr(start_source_id),
                                    event_kind=EventKind.TOOL_START,
                                    tool_category=category,
                                    occurred_at=at,
                                    duration_ms=None,
                                    family=(
                                        requirement_action_family_for_tool_category(
                                            category
                                        )
                                    ),
                                    state=requirement_action_state_for_event(
                                        EventKind.TOOL_START,
                                        None,
                                    ),
                                    tool_name=SecretStr(tool_name),
                                    invocation_preview=invocation_preview,
                                    result_or_effect_preview=None,
                                    invocation_truncated=invocation_truncated,
                                    result_or_effect_truncated=False,
                                )
                            )
                            if (
                                tool_name == "unsupported"
                                or invocation_truncated
                                or not isinstance(tool_input, dict)
                                or not isinstance(ref, str)
                                or not ref
                            ):
                                if not isinstance(tool_input, dict):
                                    complete = False
                                action_descriptor_complete = False
                            else:
                                if ref in seen_tool_refs:
                                    # Provider tool-use identity must be
                                    # one-to-one for the whole transcript.
                                    # Reuse before or after a result makes the
                                    # eventual effect semantically ambiguous;
                                    # never overwrite the original invocation.
                                    complete = False
                                    action_descriptor_complete = False
                                else:
                                    seen_tool_refs.add(ref)
                                    open_tools[ref] = (
                                        at,
                                        category,
                                        tool_name,
                                        invocation_preview,
                                        invocation_truncated,
                                    )
                    usage = message.get("usage")
                    if isinstance(usage, dict):
                        model = _safe_version(message.get("model"))
                        events.append(SourceEvent(
                            source_event_id=SecretStr(f"{stem}:u:{usage_sequence}"),
                            kind=EventKind.USAGE, sequence=USAGE_SEQUENCE_BASE + usage_sequence,
                            occurred_at=at, time_basis=EventTimeBasis.PROVIDER_REPORTED,
                            usage=UsageRecord(
                                input_tokens=_int(usage.get("input_tokens")),
                                cached_input_tokens=_int(usage.get("cache_read_input_tokens")),
                                cache_creation_tokens=_int(usage.get("cache_creation_input_tokens")),
                                output_tokens=_int(usage.get("output_tokens")),
                                model_id=model, provider_reported=True,
                                counter_kind=UsageCounterKind.DELTA, scope=UsageScope.REQUEST,
                            ),
                        ))
                        usage_sequence += 1
    except OSError:
        raise TranscriptAdapterError("transcript file could not be read") from None
    if turn_open and last_assistant_at is not None:
        emit(EventKind.TURN_END, last_assistant_at)
    if open_tools:
        # Started actions remain reviewable; the start descriptor above is
        # complete even though no provider result has arrived yet.
        open_tools.clear()
    if first_at is not None:
        events.insert(0, SourceEvent(
            source_event_id=SecretStr(f"{stem}:start"), kind=EventKind.SESSION_START,
            sequence=0, occurred_at=first_at, time_basis=EventTimeBasis.PROVIDER_REPORTED,
        ))
    # A turn end is only known once the next prompt arrives, so emission order
    # can lag time order; sequences must follow provider time. Stable-sort the
    # hook-space events by timestamp (ties keep emission order) and renumber;
    # usage events keep their own sequence space.
    hook_space = [(event.occurred_at, index, event) for index, event in enumerate(events) if event.kind is not EventKind.USAGE]
    hook_space.sort(key=lambda item: (item[0], item[1]))
    usage_events = [event for event in events if event.kind is EventKind.USAGE]
    renumbered: list[SourceEvent] = []
    for next_sequence, (_, _, event) in enumerate(hook_space):
        renumbered.append(event.model_copy(update={"sequence": next_sequence}))
    events = renumbered + usage_events
    return ParsedTranscript(
        events=tuple(events),
        action_details=tuple(action_details),
        action_descriptor_extraction_complete=(
            complete and action_descriptor_complete
        ),
        first_at=first_at,
        last_at=last_at,
        complete=complete,
    )


class ClaudeTranscriptAdapter(ProviderAdapter):
    """Lists and reads the owner's transcript files; construction reads nothing."""

    provider = Provider.CLAUDE_CODE
    # Every read is a full re-parse of the file, so a newer snapshot is the
    # authority on the whole event set. A still-running session legitimately
    # re-derives event identities (a provisional trailing turn_end moves once
    # the next prompt closes the turn), so ingestion may replace this
    # adapter's stored events instead of failing the sequence invariant.
    snapshot_authoritative = True

    def __init__(self, pseudonymizer: Pseudonymizer, claude_home: Path | None = None) -> None:
        self._pseudonymizer = pseudonymizer
        self._claude_home = claude_home
        self._health = AdapterHealth.UNAVAILABLE
        self._probed = False
        self._closed = False
        self._snapshot: tuple[TranscriptFile, ...] = ()
        self._cursors: dict[str, int] = {}
        self._cursor_counter = 0
        self._page_count = 0
        self._listed: dict[str, tuple[SourceSession, TranscriptFile]] = {}
        self._provider_version = UNKNOWN_PROVIDER_VERSION

    @property
    def required_consent_tier(self) -> DataTier:
        return DataTier.REDACTED_CONTENT

    @property
    def requires_explicit_selection(self) -> bool:
        return False

    def home(self) -> Path:
        return self._claude_home if self._claude_home is not None else default_claude_home()

    def probe(self) -> AdapterProbe:
        if self._closed:
            raise TranscriptLifecycleError("transcript adapter is closed")
        self._probed = True
        self._health = AdapterHealth.READY if (self.home() / "projects").is_dir() else AdapterHealth.UNAVAILABLE
        if self._health is AdapterHealth.READY:
            # Ingestion requires one provider version per run; take it from
            # the newest transcript so every listed session reports the same.
            try:
                newest = scan_transcripts(self.home())[:1]
            except TranscriptAdapterError:
                newest = ()
            if newest:
                version = read_head(newest[0].path).version
                if version is not None:
                    self._provider_version = version
        return AdapterProbe(
            provider=self.provider, provider_version=self._provider_version,
            adapter_version=TRANSCRIPT_ADAPTER_VERSION, source_schema_version=TRANSCRIPT_SOURCE_SCHEMA_VERSION,
            supports_metadata=True, supports_content=True, supports_watch=False, health=self._health,
        )

    def _ready(self) -> None:
        if self._closed:
            raise TranscriptLifecycleError("transcript adapter is closed")
        if not self._probed or self._health is not AdapterHealth.READY:
            raise TranscriptLifecycleError("a successful probe is required before source access")

    def hook_session_id(self, stem: str) -> str:
        return self._pseudonymizer.pseudonymize(PSEUDONYM_NAMESPACE_SESSION, stem)

    def covered_hook_session_ids(self) -> frozenset[str]:
        """Hook-space session pseudonyms that have a transcript file."""

        return frozenset(self.hook_session_id(item.stem) for item in scan_transcripts(self.home()))

    def _session_for(self, item: TranscriptFile) -> SourceSession:
        head = read_head(item.path)
        project_material = project_identity_material(head.cwd, item.stem)
        label = project_display_label(head.cwd)
        started = head.first_at or item.modified_at
        return SourceSession(
            provider=Provider.CLAUDE_CODE,
            source_installation_id=SecretStr(HOOK_INSTALLATION_MARKER),
            source_project_id=SecretStr(self._pseudonymizer.pseudonymize(PSEUDONYM_NAMESPACE_PROJECT, project_material)),
            source_session_id=SecretStr(self.hook_session_id(item.stem)),
            provider_version=self._provider_version,
            adapter_version=TRANSCRIPT_ADAPTER_VERSION,
            source_schema_version=TRANSCRIPT_SOURCE_SCHEMA_VERSION,
            started_at=started,
            source_activity_at=item.modified_at if item.modified_at >= started else started,
            ended_at=None,
            terminal_state=SessionState.UNKNOWN,
            events_complete=False,
            source_project_display_name=None if label is None else SecretStr(label),
            source_session_display_name=None if head.title is None else SecretStr(head.title),
        )

    def list_sessions(self, *, cursor: str | None = None, limit: int = 100) -> SourceSessionPage:
        self._ready()
        if limit < 1 or limit > MAX_TRANSCRIPT_PAGE_SIZE:
            raise ValueError("limit must be within the configured page bound")
        if cursor is None:
            self._snapshot = scan_transcripts(self.home())
            self._cursors.clear()
            self._cursor_counter = 0
            self._page_count = 0
            self._listed.clear()
            start = 0
        else:
            try:
                start = self._cursors.pop(cursor)
            except KeyError:
                raise TranscriptScopeError("pagination cursor is not part of this snapshot") from None
        if self._page_count >= MAX_TRANSCRIPT_PAGES:
            raise TranscriptAdapterError("session listing exceeded the page bound")
        window = self._snapshot[start:start + limit]
        sessions: list[SourceSession] = []
        for item in window:
            session = self._session_for(item)
            self._listed[session.source_session_id.get_secret_value()] = (session, item)
            sessions.append(session)
        self._page_count += 1
        next_cursor = None
        if start + limit < len(self._snapshot):
            self._cursor_counter += 1
            next_cursor = f"p{self._cursor_counter}"
            self._cursors[next_cursor] = start + limit
        return SourceSessionPage(sessions=tuple(sessions), next_cursor=next_cursor)

    def read_session(self, session: SourceSession) -> SourceSessionSnapshot:
        self._ready()
        key = session.source_session_id.get_secret_value()
        listed = self._listed.get(key)
        if listed is None or listed[0] != session:
            raise TranscriptScopeError("session is not part of the current listed snapshot")
        _, item = listed
        parsed = parse_events(item.path, item.stem)
        enriched = session.model_copy(update={
            "started_at": parsed.first_at or session.started_at,
            "source_activity_at": parsed.last_at or session.source_activity_at,
            "events_complete": parsed.complete,
        })
        return SourceSessionSnapshot(session=enriched, events=parsed.events)

    def read_events(self, session: SourceSession) -> Iterator[SourceEvent]:
        yield from self.read_session(session).events

    def health(self) -> AdapterHealth:
        return self._health

    def close(self) -> None:
        self._closed = True
        self._health = AdapterHealth.UNAVAILABLE
        self._snapshot = ()
        self._listed.clear()


TranscriptCoverage = Callable[[str], bool]

__all__ = (
    "TRANSCRIPT_ADAPTER_VERSION",
    "TRANSCRIPT_SOURCE_SCHEMA_VERSION",
    "ClaudeTranscriptAdapter",
    "TranscriptAdapterError",
    "TranscriptCoverage",
    "parse_events",
    "read_head",
    "scan_transcripts",
)
