"""Claude Code text-analysis source: the P1 local rubric over a transcript.

Mirrors the Codex app-server text source exactly, but reads the owner's local
transcript file (ADR 0011) instead of an app-server thread.  Everything after
the fragment list - redaction, language detection, focus selection, windowing,
scope accounting and the ``P1TextAnalysisInput`` contract - is the shared
Codex implementation; only the fragment extraction and provenance differ.

Fragments: user text blocks become ``USER_MESSAGE``; assistant text blocks
``AGENT_MESSAGE``; ``TodoWrite`` and ``ExitPlanMode`` tool inputs become
``PLAN`` (the todo list is the agent's plan of record in Claude Code).  Tool
results, thinking blocks, slash-command echoes and meta rows are not messages
and are skipped.  The raw text never leaves this process: the shared source
redacts it locally before the P1 pipeline sees anything.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import StringIO
import json
from pathlib import Path

from pydantic import SecretStr

from ....application.analysis.text_contracts import (
    MAX_REDACTED_MESSAGE_CHARACTERS,
    P1TextAnalysisInput,
    TextTaskProfile,
)
from ....application.analysis.text_source import (
    TextAnalysisSelection,
    TextSourceAccessGrant,
    TextSourceFailureReason,
    TextSourceReadError,
)
from ....application.ingestion import SourceIdentifierProtector
from ....application.providers import (
    CapabilityKey,
    CapabilityObservation,
    CapabilityState,
    CompatibilityReason,
    CompatibilityReasonCode,
    CompatibilityState,
    DecoderDescriptor,
    ExtractionCompleteness,
    ExtractionCompletenessState,
    ProviderCompatibilityReport,
    ProviderIdentity,
    ProviderSurface,
    SchemaArtifactKind,
    SchemaArtifactProvenance,
)
from ....domain import Provider
from ...language import DeterministicEnglishPolishDetector
from ...redaction import DeterministicLocalRedactor
from ..codex_app_server.client import CodexServerInfo
from ..codex_app_server.content_contracts import (
    CodexTextContentLimits,
    CodexTextItemKind,
    RawCodexActionDescriptor,
    RawCodexTextFragment,
    RawCodexTextThread,
)
from ..codex_app_server.content_source import CodexTextAnalysisSource
from .transcript_adapter import parse_events, read_head, scan_transcripts
from .transcript_reader import MAX_TRANSCRIPT_FILE_BYTES, MAX_TRANSCRIPT_LINES


TEXT_ADAPTER_VERSION = "claude-code-transcripts-text-adapter-1"
TEXT_SOURCE_SCHEMA_VERSION = "claude-code-transcripts.text.v1"
PLAN_TOOL_NAMES = frozenset({"TodoWrite", "ExitPlanMode"})
_KNOWN_NON_MESSAGE_TYPES = frozenset({"system", "summary", "queue-operation"})
_USER_CONTENT_BLOCK_TYPES = frozenset({"text", "tool_result"})
_ASSISTANT_CONTENT_BLOCK_TYPES = frozenset(
    {"text", "thinking", "redacted_thinking", "tool_use"}
)
# Claude Code echoes slash commands and local command output as user rows.
_ECHO_PREFIXES = (
    "<command-name>",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "<system-reminder>",
)


# Record and message-block types the text decoder classifies.  An unknown
# message-bearing record or an unknown content block means text could be
# missing from the window, so the probe reports the surface degraded rather
# than claiming completeness (the same posture as the Codex schema preflight).
KNOWN_MESSAGE_RECORD_TYPES = frozenset({"user", "assistant"})
KNOWN_CONTENT_BLOCK_TYPES = frozenset(
    {"text", "tool_use", "tool_result", "thinking", "redacted_thinking", "image", "document"}
)
PROBE_MAX_FILES = 64
PROBE_MAX_LINES_PER_FILE = 400

CLAUDE_CODE_TEXT_WINDOW_DECODER_DESCRIPTOR = DecoderDescriptor(
    provider=ProviderIdentity(key="claude_code"),
    surface=ProviderSurface.TEXT_WINDOW,
    adapter_version=TEXT_ADAPTER_VERSION,
    decoder_key="claude-code.transcripts.text-window",
    decoder_version="1",
    wire_schema_family="claude-code.transcripts.jsonl.v1",
    canonical_schema_version=TEXT_SOURCE_SCHEMA_VERSION,
    schema_artifact=SchemaArtifactProvenance(
        artifact_key="claude-code.transcripts.observed-structure",
        artifact_version="1",
        kind=SchemaArtifactKind.MINIMIZED,
    ),
    capabilities=(
        CapabilityKey.USER_MESSAGES,
        CapabilityKey.AGENT_MESSAGES,
        CapabilityKey.PLAN_MESSAGES,
    ),
    tested_provider_versions=(),
)


def _plan_text(name: str, tool_input: object) -> str:
    if not isinstance(tool_input, dict):
        return ""
    if name == "ExitPlanMode":
        plan = tool_input.get("plan")
        return plan if isinstance(plan, str) else ""
    todos = tool_input.get("todos")
    if not isinstance(todos, list):
        return ""
    lines: list[str] = []
    for todo in todos:
        if not isinstance(todo, dict):
            continue
        content = todo.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        status = todo.get("status")
        marker = status if isinstance(status, str) and status else "pending"
        lines.append(f"- [{marker}] {content.strip()}")
    return "\n".join(lines)


def _is_echo(text: str) -> bool:
    stripped = text.lstrip()
    return any(stripped.startswith(prefix) for prefix in _ECHO_PREFIXES)


def extract_fragments(
    path: Path,
    *,
    limits: CodexTextContentLimits,
    snapshot_text: str | None = None,
    snapshot_complete: bool = True,
) -> RawCodexTextThread:
    """Read one transcript file into the shared raw-fragment thread shape."""

    fragments: list[RawCodexTextFragment] = []
    total_chars = 0
    turn = 0
    # Anything the bounds drop or clip is an omission the window cannot
    # classify; only the fragment cap (oldest dropped) is older-history
    # truncation.  The thread contract requires exactly that partition.
    omission = not snapshot_complete
    if snapshot_text is None and path.stat().st_size > MAX_TRANSCRIPT_FILE_BYTES:
        omission = True
    with (
        StringIO(snapshot_text)
        if snapshot_text is not None
        else path.open("r", encoding="utf-8", errors="replace")
    ) as handle:
        for line_no, line in enumerate(handle):
            if line_no >= MAX_TRANSCRIPT_LINES:
                omission = True
                break
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                omission = True
                continue
            if not isinstance(record, dict):
                omission = True
                continue
            if record.get("isMeta") is True:
                continue
            kind = record.get("type")
            message = record.get("message")
            if kind in _KNOWN_NON_MESSAGE_TYPES:
                continue
            if kind not in ("user", "assistant"):
                omission = True
                continue
            if not isinstance(message, dict):
                omission = True
                continue
            content = message.get("content")
            blocks: list[tuple[CodexTextItemKind, str]] = []
            if isinstance(content, str):
                if kind == "user" and not _is_echo(content):
                    blocks.append((CodexTextItemKind.USER_MESSAGE, content))
                elif kind == "assistant":
                    blocks.append((CodexTextItemKind.AGENT_MESSAGE, content))
            elif isinstance(content, list):
                allowed_block_types = (
                    _USER_CONTENT_BLOCK_TYPES
                    if kind == "user"
                    else _ASSISTANT_CONTENT_BLOCK_TYPES
                )
                for block in content:
                    if not isinstance(block, dict):
                        omission = True
                        continue
                    block_type = block.get("type")
                    if block_type not in allowed_block_types:
                        omission = True
                        continue
                    if block_type == "text" and isinstance(block.get("text"), str):
                        text = block["text"]
                        if kind == "user":
                            if not _is_echo(text):
                                blocks.append((CodexTextItemKind.USER_MESSAGE, text))
                        else:
                            blocks.append((CodexTextItemKind.AGENT_MESSAGE, text))
                    elif block_type == "tool_use" and kind == "assistant":
                        name = block.get("name")
                        if isinstance(name, str) and name in PLAN_TOOL_NAMES:
                            plan = _plan_text(name, block.get("input"))
                            if plan.strip():
                                blocks.append((CodexTextItemKind.PLAN, plan))
                    elif block_type == "text":
                        omission = True
            else:
                omission = True
            if not blocks:
                continue
            if any(item_kind is CodexTextItemKind.USER_MESSAGE for item_kind, _ in blocks):
                turn += 1
            for index, (item_kind, text) in enumerate(blocks):
                if not text.strip():
                    continue
                clipped = text[: min(limits.max_characters_per_fragment, MAX_REDACTED_MESSAGE_CHARACTERS)]
                if len(clipped) < len(text):
                    omission = True
                total_chars += len(clipped)
                fragments.append(
                    RawCodexTextFragment(
                        turn_id=SecretStr(f"turn-{max(turn, 1)}"),
                        item_id=SecretStr(f"line-{line_no}"),
                        content_index=index,
                        kind=item_kind,
                        text=SecretStr(clipped),
                    )
                )
            if total_chars > limits.max_total_text_characters:
                omission = True
                break
    older_truncated = False
    if len(fragments) > limits.max_text_fragments_per_session:
        fragments = fragments[-limits.max_text_fragments_per_session :]
        older_truncated = True
    return RawCodexTextThread(
        thread_id=SecretStr(path.stem),
        fragments=tuple(fragments),
        extraction_complete=not older_truncated and not omission,
        older_history_truncated=older_truncated,
        unclassified_omission=omission,
    )


class ClaudeTranscriptTextAnalysisSource(CodexTextAnalysisSource):
    """The shared local text source, fed from a Claude Code transcript file."""

    provider = Provider.CLAUDE_CODE
    text_adapter_version = TEXT_ADAPTER_VERSION
    text_source_schema_version = TEXT_SOURCE_SCHEMA_VERSION

    def __init__(
        self,
        pseudonymizer: SourceIdentifierProtector,
        *,
        locate: Callable[[str], Path | None],
        redactor: DeterministicLocalRedactor | None = None,
        language_detector: DeterministicEnglishPolishDetector | None = None,
        text_limits: CodexTextContentLimits | None = None,
    ) -> None:
        super().__init__(
            pseudonymizer,
            redactor=redactor,
            language_detector=language_detector,
            text_limits=text_limits,
            client_factory=self._no_client,
        )
        self._locate = locate

    @staticmethod
    def _no_client():  # pragma: no cover - the transcript source never opens a client
        raise TextSourceReadError(TextSourceFailureReason.PROVIDER_UNAVAILABLE)

    @staticmethod
    def _bounded_snapshot(path: Path) -> tuple[str, bool]:
        """Capture one process-only transcript view for every downstream parser.

        The extra byte distinguishes an exact bounded snapshot from a prefix.
        Oversized input remains parseable only as explicitly incomplete; it is
        never allowed to establish requirement-action review authority.
        """

        with path.open("rb") as handle:
            payload = handle.read(MAX_TRANSCRIPT_FILE_BYTES + 1)
        complete = len(payload) <= MAX_TRANSCRIPT_FILE_BYTES
        if not complete:
            payload = payload[:MAX_TRANSCRIPT_FILE_BYTES]
        return payload.decode("utf-8", errors="replace"), complete

    def read(
        self,
        *,
        selection: TextAnalysisSelection,
        grant: TextSourceAccessGrant,
        task_profile: TextTaskProfile,
    ) -> P1TextAnalysisInput:
        self._require_matching_grant(selection, grant)
        try:
            path = self._locate(selection.session_id)
        except OSError:
            raise TextSourceReadError(TextSourceFailureReason.PROVIDER_UNAVAILABLE) from None
        if path is None:
            raise TextSourceReadError(TextSourceFailureReason.SELECTION_SNAPSHOT_MISS)
        try:
            snapshot_text, snapshot_complete = self._bounded_snapshot(path)
            head = read_head(path, snapshot_text=snapshot_text)
            thread = extract_fragments(
                path,
                limits=self._text_limits,
                snapshot_text=snapshot_text,
                snapshot_complete=snapshot_complete,
            )
            parsed = parse_events(
                path,
                path.stem,
                snapshot_text=snapshot_text,
            )
        except OSError:
            raise TextSourceReadError(TextSourceFailureReason.PROVIDER_UNAVAILABLE) from None
        stable = snapshot_complete
        event_sequence_by_source = {
            item.source_event_id.get_secret_value(): item.sequence
            for item in parsed.events
        }
        ordered_action_details = tuple(
            sorted(
                parsed.action_details,
                key=lambda item: event_sequence_by_source.get(
                    item.source_event_id.get_secret_value(),
                    4_000_000_001,
                ),
            )
        )
        descriptors_exactly_mapped = (
            len(ordered_action_details) == len(parsed.action_details)
            and all(
                item.source_event_id.get_secret_value()
                in event_sequence_by_source
                for item in ordered_action_details
            )
        )
        thread = thread.model_copy(
            update={
                "action_descriptors": tuple(
                    RawCodexActionDescriptor(
                        source_event_id=item.source_event_id,
                        event_kind=item.event_kind.value,
                        candidate_metadata_complete=True,
                        candidate_sequence=(
                            event_sequence_by_source[
                                item.source_event_id.get_secret_value()
                            ]
                            * 4
                        ),
                        candidate_tool_category=item.tool_category,
                        candidate_occurred_at=item.occurred_at,
                        candidate_duration_ms=item.duration_ms,
                        candidate_family=item.family,
                        candidate_state=item.state,
                        tool_name=item.tool_name,
                        invocation_preview=item.invocation_preview,
                        result_or_effect_preview=(
                            item.result_or_effect_preview
                        ),
                        invocation_truncated=item.invocation_truncated,
                        result_or_effect_truncated=(
                            item.result_or_effect_truncated
                        ),
                    )
                    for item in ordered_action_details
                ),
                "action_descriptor_extraction_complete": (
                    stable
                    and parsed.action_descriptor_extraction_complete
                    and descriptors_exactly_mapped
                    and thread.extraction_complete
                ),
            }
        )
        return self._analysis_input(
            thread=thread,
            selection=selection,
            task_profile=task_profile,
            server_info=CodexServerInfo(
                provider_version=head.version or "unknown",
                source_schema_version=TEXT_SOURCE_SCHEMA_VERSION,
            ),
        )


@dataclass(frozen=True, slots=True)
class TranscriptStructureSample:
    files: int
    unknown_record_types: int
    unknown_block_types: int
    provider_version: str


def sample_transcript_structure(claude_home: Path) -> TranscriptStructureSample:
    """Read only the type keys of the newest transcripts; no content is kept."""

    files = scan_transcripts(claude_home)[:PROBE_MAX_FILES]
    unknown_records = 0
    unknown_blocks = 0
    version = "unknown"
    for index, entry in enumerate(files):
        if index == 0:
            try:
                version = read_head(entry.path).version or "unknown"
            except OSError:
                version = "unknown"
        try:
            with entry.path.open("r", encoding="utf-8", errors="replace") as handle:
                for line_no, line in enumerate(handle):
                    if line_no >= PROBE_MAX_LINES_PER_FILE:
                        break
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(record, dict):
                        continue
                    message = record.get("message")
                    if not isinstance(message, dict):
                        continue
                    if record.get("type") not in KNOWN_MESSAGE_RECORD_TYPES:
                        unknown_records += 1
                        continue
                    content = message.get("content")
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") not in KNOWN_CONTENT_BLOCK_TYPES:
                                unknown_blocks += 1
        except OSError:
            continue
    return TranscriptStructureSample(
        files=len(files),
        unknown_record_types=unknown_records,
        unknown_block_types=unknown_blocks,
        provider_version=version,
    )


@dataclass(frozen=True, slots=True)
class ClaudeTranscriptTextWindowProbe:
    """Compatibility report for the transcript text window (structure only)."""

    claude_home: Callable[[], Path]
    _clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC), repr=False)

    @property
    def descriptor(self) -> DecoderDescriptor:
        return CLAUDE_CODE_TEXT_WINDOW_DECODER_DESCRIPTOR

    def check(self) -> ProviderCompatibilityReport:
        try:
            checked_at = self._clock().astimezone(UTC)
        except Exception:
            checked_at = datetime.now(UTC)
        try:
            home = self.claude_home()
            if not (home / "projects").is_dir():
                raise FileNotFoundError
            sample = sample_transcript_structure(home)
        except Exception:
            return ProviderCompatibilityReport(
                descriptor=self.descriptor,
                provider_version="unknown",
                state=CompatibilityState.UNAVAILABLE,
                capabilities=tuple(
                    CapabilityObservation(
                        key=capability,
                        state=CapabilityState.UNKNOWN,
                        reason_code=CompatibilityReasonCode.PROVIDER_UNAVAILABLE,
                    )
                    for capability in self.descriptor.capabilities
                ),
                extraction=ExtractionCompleteness(state=ExtractionCompletenessState.NONE, observed_units=0),
                reasons=(CompatibilityReason(code=CompatibilityReasonCode.PROVIDER_UNAVAILABLE),),
                checked_at=checked_at,
            )
        unknown = sample.unknown_record_types + sample.unknown_block_types
        if unknown:
            state = CompatibilityState.DEGRADED
            extraction = ExtractionCompleteness(
                state=ExtractionCompletenessState.UNKNOWN,
                observed_units=sample.files,
                unknown_units=min(unknown, 10_000_000),
            )
            reasons = (CompatibilityReason(code=CompatibilityReasonCode.UNKNOWN_UNION_VARIANT),)
        else:
            state = CompatibilityState.COMPATIBLE
            extraction = ExtractionCompleteness(
                state=ExtractionCompletenessState.COMPLETE,
                observed_units=sample.files,
                eligible_units=sample.files,
                coverage=1.0,
            )
            reasons = (
                CompatibilityReason(
                    code=(
                        CompatibilityReasonCode.PROVIDER_VERSION_UNKNOWN
                        if sample.provider_version == "unknown"
                        else CompatibilityReasonCode.PROVIDER_VERSION_UNTESTED
                    )
                ),
            )
        return ProviderCompatibilityReport(
            descriptor=self.descriptor,
            provider_version=sample.provider_version,
            state=state,
            capabilities=tuple(
                CapabilityObservation(key=capability, state=CapabilityState.SUPPORTED)
                for capability in self.descriptor.capabilities
            ),
            extraction=extraction,
            reasons=reasons,
            checked_at=checked_at,
        )


__all__ = (
    "CLAUDE_CODE_TEXT_WINDOW_DECODER_DESCRIPTOR",
    "ClaudeTranscriptTextAnalysisSource",
    "ClaudeTranscriptTextWindowProbe",
    "PLAN_TOOL_NAMES",
    "TEXT_ADAPTER_VERSION",
    "TEXT_SOURCE_SCHEMA_VERSION",
    "extract_fragments",
    "sample_transcript_structure",
)
