"""Allowlisted App Server DTOs for explicit local text analysis.

The documented ``thread/read`` ``ThreadItem`` union contains many highly
sensitive item families. This module projects a bounded newest suffix containing
only text from ``userMessage``, ``agentMessage``, and ``plan``. Reasoning,
commands and output, diffs, paths, tool arguments and results, images, searches,
reviews, omitted older structures, and unknown future item types do not enter a
boundary DTO. Older-prefix truncation is distinguished from an unclassified
omission so a separately bounded recent analysis window can prove its own
completeness without claiming complete provider history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from ....application.analysis.text_contracts import (
    MAX_ACTION_REVIEW_DESCRIPTORS,
    MAX_ACTION_REVIEW_PREVIEW_CHARACTERS,
    MAX_ACTION_REVIEW_TOTAL_CHARACTERS,
    MAX_ACTION_REVIEW_TOOL_NAME_CHARACTERS,
    MAX_REDACTED_MESSAGE_CHARACTERS,
)
from ....application.analysis.evidence_contracts import ActionFamily, ActionState
from ....domain import ToolCategory
from .errors import CodexCompatibilityError, CodexThreadStructureLimitError


TEXT_CONTENT_ADAPTER_VERSION = "0.7.0"
TEXT_CONTENT_SCHEMA_VERSION = "codex-thread-item-text-v8"


class CodexTextItemKind(StrEnum):
    USER_MESSAGE = "user_message"
    AGENT_MESSAGE = "agent_message"
    PLAN = "plan"


class _PrivateWireModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )


class RawCodexTextFragment(_PrivateWireModel):
    """One private allowlisted fragment; never persistence-safe."""

    turn_id: SecretStr = Field(repr=False)
    item_id: SecretStr = Field(repr=False)
    content_index: int = Field(ge=0)
    segment_index: int = Field(default=0, ge=0)
    kind: CodexTextItemKind
    text: SecretStr = Field(
        repr=False,
        min_length=1,
        max_length=MAX_REDACTED_MESSAGE_CHARACTERS,
    )


class RawCodexActionDescriptor(_PrivateWireModel):
    """One bounded private action descriptor from the selected provider read."""

    source_event_id: SecretStr = Field(repr=False, min_length=1, max_length=16_384)
    event_kind: str = Field(pattern=r"^(tool_start|tool_end|artifact)$")
    tool_name: SecretStr = Field(
        repr=False,
        min_length=1,
        max_length=MAX_ACTION_REVIEW_TOOL_NAME_CHARACTERS,
    )
    invocation_preview: SecretStr = Field(
        repr=False,
        min_length=1,
        max_length=MAX_ACTION_REVIEW_PREVIEW_CHARACTERS,
    )
    result_or_effect_preview: SecretStr | None = Field(
        default=None,
        repr=False,
        min_length=1,
        max_length=MAX_ACTION_REVIEW_PREVIEW_CHARACTERS,
    )
    invocation_truncated: bool
    result_or_effect_truncated: bool
    candidate_metadata_complete: bool = False
    candidate_sequence: int | None = Field(
        default=None,
        ge=0,
        le=4_000_000_000,
    )
    candidate_tool_category: ToolCategory | None = None
    candidate_occurred_at: datetime | None = None
    candidate_duration_ms: int | None = Field(default=None, ge=0)
    candidate_family: ActionFamily | None = None
    candidate_state: ActionState | None = None

    @model_validator(mode="after")
    def exact_candidate_metadata(self) -> "RawCodexActionDescriptor":
        required = (
            self.candidate_sequence,
            self.candidate_occurred_at,
            self.candidate_family,
            self.candidate_state,
        )
        if self.candidate_metadata_complete != all(
            value is not None for value in required
        ):
            raise ValueError("candidate metadata completeness is incoherent")
        if not self.candidate_metadata_complete and any(
            value is not None
            for value in (
                self.candidate_tool_category,
                self.candidate_sequence,
                self.candidate_occurred_at,
                self.candidate_duration_ms,
                self.candidate_family,
                self.candidate_state,
            )
        ):
            raise ValueError("incomplete candidate metadata cannot carry values")
        if self.candidate_occurred_at is not None and (
            self.candidate_occurred_at.tzinfo is None
            or self.candidate_occurred_at.utcoffset() != timedelta(0)
        ):
            raise ValueError("candidate metadata timestamp must be UTC")
        return self


class RawCodexTextThread(_PrivateWireModel):
    """Minimized private result of one explicit ``thread/read`` call."""

    thread_id: SecretStr = Field(repr=False)
    fragments: tuple[RawCodexTextFragment, ...] = Field(repr=False)
    extraction_complete: bool
    older_history_truncated: bool
    unclassified_omission: bool
    action_descriptors: tuple[RawCodexActionDescriptor, ...] = Field(
        default=(),
        repr=False,
        max_length=MAX_ACTION_REVIEW_DESCRIPTORS,
    )
    action_descriptor_extraction_complete: bool = False

    @model_validator(mode="after")
    def validate_completeness_partition(self) -> RawCodexTextThread:
        if self.extraction_complete != (
            not self.older_history_truncated and not self.unclassified_omission
        ):
            raise ValueError("Codex text extraction completeness is inconsistent")
        descriptor_ids = tuple(
            item.source_event_id.get_secret_value()
            for item in self.action_descriptors
        )
        if len(set(descriptor_ids)) != len(descriptor_ids):
            raise ValueError("Codex action descriptor identifiers must be unique")
        return self


@dataclass(frozen=True, slots=True)
class CodexTextContentLimits:
    """Post-decode newest-suffix bounds below the transport frame ceiling."""

    max_turns_per_session: int = 500
    max_items_per_turn: int = 500
    max_total_items: int = 5_000
    max_user_content_parts_per_item: int = 32
    max_text_fragments_per_session: int = 2_000
    max_characters_per_fragment: int = MAX_REDACTED_MESSAGE_CHARACTERS
    max_total_text_characters: int = 1_000_000

    def __post_init__(self) -> None:
        values = (
            self.max_turns_per_session,
            self.max_items_per_turn,
            self.max_total_items,
            self.max_user_content_parts_per_item,
            self.max_text_fragments_per_session,
            self.max_characters_per_fragment,
            self.max_total_text_characters,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in values):
            raise ValueError("Codex text-content limits must be positive integers")
        if self.max_characters_per_fragment > MAX_REDACTED_MESSAGE_CHARACTERS:
            raise ValueError("Codex text fragment bound exceeds the analysis contract")
        if self.max_total_items < self.max_items_per_turn:
            raise ValueError("Codex total item bound cannot be below the per-turn bound")
        if self.max_total_text_characters < self.max_characters_per_fragment:
            raise ValueError("Codex total text bound cannot be below the fragment bound")


ADMITTED_THREAD_ITEM_TYPES = frozenset({"userMessage", "agentMessage", "plan"})
DISCARDED_THREAD_ITEM_TYPES = frozenset(
    {
        "reasoning",
        "commandExecution",
        "fileChange",
        "mcpToolCall",
        "dynamicToolCall",
        "collabToolCall",
        "collabAgentToolCall",
        "hookPrompt",
        "subAgentActivity",
        "webSearch",
        "imageView",
        "sleep",
        "imageGeneration",
        "enteredReviewMode",
        "exitedReviewMode",
        "contextCompaction",
    }
)
_TEXT_USER_INPUT_TYPE = "text"
DISCARDED_USER_INPUT_TYPES = frozenset(
    {"image", "localImage", "skill", "mention"}
)
_AGENT_PHASES = frozenset({"commentary", "final_answer"})
_ACTION_DESCRIPTOR_ITEM_TYPES = frozenset(
    {"commandExecution", "fileChange", "mcpToolCall", "webSearch", "imageView"}
)


def _bounded_string(
    value: object,
    *,
    field: str,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str) or (not value and not allow_empty):
        raise CodexCompatibilityError(f"provider {field} has an unsupported shape")
    if len(value) > maximum:
        raise CodexThreadStructureLimitError(
            f"provider {field} exceeded the character bound"
        )
    if "\x00" in value:
        raise CodexCompatibilityError(f"provider {field} contains an unsupported control")
    return value


def _parse_fragments(
    *,
    turn_id: str,
    item_id: str,
    content_index: int,
    kind: CodexTextItemKind,
    text: object,
    limits: CodexTextContentLimits,
) -> tuple[tuple[RawCodexTextFragment, ...], bool]:
    if not isinstance(text, str):
        raise CodexCompatibilityError("provider text item has an unsupported shape")
    if "\x00" in text:
        raise CodexCompatibilityError(
            "provider text item contains an unsupported control"
        )
    private_text = text
    if not private_text.strip():
        return (), False

    # Oversized message bodies are a normal property of long coding sessions,
    # not a reason to reject the whole session.  Retain a bounded newest suffix
    # and split it into contract-sized fragments before redaction/windowing.
    truncated = len(private_text) > limits.max_total_text_characters
    if truncated:
        private_text = private_text[-limits.max_total_text_characters :]
    pieces = tuple(
        private_text[start : start + limits.max_characters_per_fragment]
        for start in range(0, len(private_text), limits.max_characters_per_fragment)
    )
    if len(pieces) > limits.max_text_fragments_per_session:
        pieces = pieces[-limits.max_text_fragments_per_session :]
        truncated = True
    return (
        tuple(
            RawCodexTextFragment(
                turn_id=SecretStr(turn_id),
                item_id=SecretStr(item_id),
                content_index=content_index,
                segment_index=segment_index,
                kind=kind,
                text=SecretStr(piece),
            )
            for segment_index, piece in enumerate(pieces)
        ),
        truncated,
    )


def _encode_source_event_identity(*components: str) -> str:
    """Mirror the content-free mapper's injective source-event identity."""

    return "".join(f"{len(component)}:{component}" for component in components)


def _bounded_json_preview(value: object) -> tuple[SecretStr, bool]:
    try:
        rendered = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        raise CodexCompatibilityError(
            "provider action descriptor has an unsupported shape"
        ) from None
    if not rendered or "\x00" in rendered:
        raise CodexCompatibilityError(
            "provider action descriptor contains unsupported content"
        )
    truncated = len(rendered) > MAX_ACTION_REVIEW_PREVIEW_CHARACTERS
    if truncated:
        rendered = rendered[:MAX_ACTION_REVIEW_PREVIEW_CHARACTERS]
    return SecretStr(rendered), truncated


def _action_descriptor(
    *,
    thread_id: str,
    turn_id: str,
    item_id: str,
    item_type: str,
    item: dict[str, object],
) -> RawCodexActionDescriptor:
    if item_type == "commandExecution":
        command = item.get("command")
        if not isinstance(command, str) or not command.strip():
            raise CodexCompatibilityError("provider command descriptor is incomplete")
        tool_name = "commandExecution"
        invocation_value = {"command": command, "cwd": item.get("cwd")}
        effect_value = {
            "aggregatedOutput": item.get("aggregatedOutput"),
            "exitCode": item.get("exitCode"),
            "status": item.get("status"),
            "success": item.get("success"),
        }
    elif item_type == "fileChange":
        changes = item.get("changes")
        if not isinstance(changes, list):
            raise CodexCompatibilityError("provider file-change descriptor is incomplete")
        tool_name = "fileChange"
        invocation_value = {"operation": "fileChange"}
        effect_value = {
            "changes": changes,
            "status": item.get("status"),
            "success": item.get("success"),
        }
    elif item_type == "mcpToolCall":
        tool = item.get("tool") or item.get("name")
        if not isinstance(tool, str) or not tool.strip():
            raise CodexCompatibilityError("provider MCP descriptor is incomplete")
        tool_name = tool
        invocation_value = {
            "server": item.get("server"),
            "tool": tool,
            "arguments": item.get("arguments"),
        }
        effect_value = {
            "result": item.get("result"),
            "status": item.get("status"),
            "success": item.get("success"),
        }
    elif item_type == "webSearch":
        query = item.get("query") or item.get("searchQuery")
        if not isinstance(query, str) or not query.strip():
            raise CodexCompatibilityError("provider web-search descriptor is incomplete")
        tool_name = "webSearch"
        invocation_value = {"query": query}
        effect_value = {
            "result": item.get("result"),
            "results": item.get("results"),
            "status": item.get("status"),
            "success": item.get("success"),
        }
    elif item_type == "imageView":
        target = item.get("path") or item.get("imagePath")
        if not isinstance(target, str) or not target.strip():
            raise CodexCompatibilityError("provider image-view descriptor is incomplete")
        tool_name = "imageView"
        invocation_value = {"target": target}
        effect_value = {
            "status": item.get("status"),
            "success": item.get("success"),
        }
    else:  # pragma: no cover - caller is a closed allowlist
        raise CodexCompatibilityError("provider action descriptor type is unsupported")
    if len(tool_name) > MAX_ACTION_REVIEW_TOOL_NAME_CHARACTERS or "\x00" in tool_name:
        raise CodexCompatibilityError("provider action tool name is unsupported")
    invocation, invocation_truncated = _bounded_json_preview(invocation_value)
    effect, effect_truncated = _bounded_json_preview(effect_value)
    return RawCodexActionDescriptor(
        source_event_id=SecretStr(
            _encode_source_event_identity(
                thread_id, "turn", turn_id, "item", item_id
            )
        ),
        event_kind="tool_end",
        tool_name=SecretStr(tool_name),
        invocation_preview=invocation,
        result_or_effect_preview=effect,
        invocation_truncated=invocation_truncated,
        result_or_effect_truncated=effect_truncated,
    )


def parse_text_thread_read(
    result: object,
    limits: CodexTextContentLimits | None = None,
) -> RawCodexTextThread:
    """Project the newest bounded allowlisted suffix of a documented read."""

    effective_limits = limits or CodexTextContentLimits()
    if not isinstance(result, dict):
        raise CodexCompatibilityError("provider text read has an unsupported shape")
    thread = result.get("thread")
    if not isinstance(thread, dict):
        raise CodexCompatibilityError("provider text read has an unsupported shape")
    thread_id = _bounded_string(
        thread.get("id"), field="thread identifier", maximum=4_096
    )
    turns = thread.get("turns")
    if not isinstance(turns, list):
        raise CodexCompatibilityError("provider text turns have an unsupported shape")

    # ``thread/read`` returns the complete decoded thread and has no documented
    # server-side window. Walk newest-to-oldest and retain only a chronological
    # suffix. Omitted older structures are never inspected and make extraction
    # explicitly incomplete; malformed or individually oversized selected
    # structures still fail closed.
    turn_start = max(0, len(turns) - effective_limits.max_turns_per_session)
    older_history_truncated = turn_start > 0
    unclassified_omission = False
    newest_fragments: list[RawCodexTextFragment] = []
    newest_action_descriptors: list[RawCodexActionDescriptor] = []
    total_action_descriptor_characters = 0
    action_descriptor_extraction_complete = not older_history_truncated
    remaining_items = effective_limits.max_total_items
    total_characters = 0
    projection_full = False

    for turn_index in range(len(turns) - 1, turn_start - 1, -1):
        if remaining_items == 0:
            older_history_truncated = True
            break
        turn = turns[turn_index]
        if not isinstance(turn, dict):
            raise CodexCompatibilityError("provider text turn has an unsupported shape")
        turn_id = _bounded_string(
            turn.get("id"), field="turn identifier", maximum=4_096
        )
        items = turn.get("items")
        if not isinstance(items, list):
            raise CodexCompatibilityError("provider text items have an unsupported shape")

        selected_item_count = min(
            len(items),
            effective_limits.max_items_per_turn,
            remaining_items,
        )
        item_start = len(items) - selected_item_count
        if item_start > 0:
            older_history_truncated = True
            action_descriptor_extraction_complete = False
        remaining_items -= selected_item_count

        for item_index in range(len(items) - 1, item_start - 1, -1):
            item = items[item_index]
            if not isinstance(item, dict):
                raise CodexCompatibilityError("provider text item has an unsupported shape")
            item_type = item.get("type")
            if not isinstance(item_type, str) or not item_type:
                raise CodexCompatibilityError("provider text item type is unsupported")
            if item_type in DISCARDED_THREAD_ITEM_TYPES:
                if item_type in _ACTION_DESCRIPTOR_ITEM_TYPES:
                    try:
                        item_id = _bounded_string(
                            item.get("id"),
                            field="action item identifier",
                            maximum=4_096,
                        )
                        if len(newest_action_descriptors) >= MAX_ACTION_REVIEW_DESCRIPTORS:
                            action_descriptor_extraction_complete = False
                        else:
                            descriptor = _action_descriptor(
                                thread_id=thread_id,
                                turn_id=turn_id,
                                item_id=item_id,
                                item_type=item_type,
                                item=item,
                            )
                            descriptor_characters = (
                                len(descriptor.tool_name.get_secret_value())
                                + len(
                                    descriptor.invocation_preview.get_secret_value()
                                )
                                + (
                                    0
                                    if descriptor.result_or_effect_preview is None
                                    else len(
                                        descriptor.result_or_effect_preview.get_secret_value()
                                    )
                                )
                            )
                            if (
                                total_action_descriptor_characters
                                + descriptor_characters
                                > MAX_ACTION_REVIEW_TOTAL_CHARACTERS
                            ):
                                action_descriptor_extraction_complete = False
                            else:
                                newest_action_descriptors.append(descriptor)
                                total_action_descriptor_characters += (
                                    descriptor_characters
                                )
                    except CodexCompatibilityError:
                        action_descriptor_extraction_complete = False
                elif item_type in {
                    "dynamicToolCall",
                    "collabToolCall",
                    "collabAgentToolCall",
                    "subAgentActivity",
                    "imageGeneration",
                }:
                    # These current documented variants do not map to the
                    # safe action receipt family.  If a future metadata mapper
                    # admits one, exact descriptor/candidate matching below
                    # will fail closed until its shape is allowlisted here.
                    pass
                continue
            if item_type not in ADMITTED_THREAD_ITEM_TYPES:
                # Never inspect an unknown variant's payload. It cannot become
                # admitted merely by adding a text-like field, but its presence
                # means this adapter cannot prove that extraction is complete.
                unclassified_omission = True
                action_descriptor_extraction_complete = False
                continue

            item_id = _bounded_string(
                item.get("id"), field="text item identifier", maximum=4_096
            )
            item_fragments: list[RawCodexTextFragment] = []
            if item_type == "userMessage":
                content = item.get("content")
                if not isinstance(content, list):
                    raise CodexCompatibilityError(
                        "provider user message has an unsupported shape"
                    )
                content_start = max(
                    0,
                    len(content)
                    - effective_limits.max_user_content_parts_per_item,
                )
                if content_start > 0:
                    older_history_truncated = True
                for content_index in range(content_start, len(content)):
                    part = content[content_index]
                    if not isinstance(part, dict):
                        raise CodexCompatibilityError(
                            "provider user input has an unsupported shape"
                        )
                    part_type = part.get("type")
                    if not isinstance(part_type, str) or not part_type:
                        raise CodexCompatibilityError(
                            "provider user input type is unsupported"
                        )
                    if part_type != _TEXT_USER_INPUT_TYPE:
                        if part_type not in DISCARDED_USER_INPUT_TYPES:
                            # As with an unknown ThreadItem, inspect only its tag
                            # and conservatively mark extraction incomplete.
                            unclassified_omission = True
                        continue
                    fragments, text_truncated = _parse_fragments(
                        turn_id=turn_id,
                        item_id=item_id,
                        content_index=content_index,
                        kind=CodexTextItemKind.USER_MESSAGE,
                        text=part.get("text"),
                        limits=effective_limits,
                    )
                    if text_truncated:
                        older_history_truncated = True
                    item_fragments.extend(fragments)
            else:
                phase = item.get("phase")
                if item_type == "agentMessage" and (
                    phase is not None and phase not in _AGENT_PHASES
                ):
                    raise CodexCompatibilityError("provider agent phase is unsupported")
                fragments, text_truncated = _parse_fragments(
                    turn_id=turn_id,
                    item_id=item_id,
                    content_index=0,
                    kind=(
                        CodexTextItemKind.AGENT_MESSAGE
                        if item_type == "agentMessage"
                        else CodexTextItemKind.PLAN
                    ),
                    text=item.get("text"),
                    limits=effective_limits,
                )
                if text_truncated:
                    older_history_truncated = True
                item_fragments.extend(fragments)

            item_characters = sum(
                len(fragment.text.get_secret_value())
                for fragment in item_fragments
            )
            if (
                len(newest_fragments) + len(item_fragments)
                > effective_limits.max_text_fragments_per_session
                or total_characters + item_characters
                > effective_limits.max_total_text_characters
            ):
                older_history_truncated = True
                action_descriptor_extraction_complete = False
                projection_full = True
                break
            newest_fragments.extend(reversed(item_fragments))
            total_characters += item_characters

        if projection_full:
            break
        if remaining_items == 0 and (turn_index > turn_start or item_start > 0):
            older_history_truncated = True
            action_descriptor_extraction_complete = False
            break

    return RawCodexTextThread(
        thread_id=SecretStr(thread_id),
        fragments=tuple(reversed(newest_fragments)),
        extraction_complete=not older_history_truncated and not unclassified_omission,
        older_history_truncated=older_history_truncated,
        unclassified_omission=unclassified_omission,
        action_descriptors=tuple(reversed(newest_action_descriptors)),
        action_descriptor_extraction_complete=(
            action_descriptor_extraction_complete
            and not older_history_truncated
            and not unclassified_omission
            and not any(
                item.invocation_truncated or item.result_or_effect_truncated
                for item in newest_action_descriptors
            )
        ),
    )
