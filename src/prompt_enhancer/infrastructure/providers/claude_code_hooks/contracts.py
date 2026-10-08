"""Versioned, content-free contract for Claude Code hook payloads.

Claude Code invokes a configured hook command once per lifecycle event and
writes one JSON object to that command's stdin.  The object carries a session
identifier, the working directory, a transcript path, the hook event name, and
event-specific fields - several of which are content: the submitted prompt,
tool input, tool response, notification text, and compaction instructions.

This module defines the *only* fields the receiver may look at and the *only*
shape it may produce.  Everything else in the payload is never read.  The
minimized event carries no text, no path, and no raw identifier: session and
tool-use identities are HMAC pseudonyms, the working directory survives only as
a project pseudonym plus a bounded basename display label, and a tool name is
reduced to a closed category before it is discarded.

The receiver never reads ``transcript_path``.  It has no timestamp of its own
from the provider; the receipt clock is stamped by the receiver at the moment
Claude Code synchronously invokes it, and that provenance is carried in
``SOURCE_SCHEMA_VERSION`` rather than by inventing a provider-reported time.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
import hashlib
import posixpath
import re
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ....display_labels import (
    PROJECT_DISPLAY_NAME_MAX_LENGTH,
    SESSION_DISPLAY_NAME_MAX_LENGTH,
    minimize_private_display_name,
)
from ....domain import (
    PSEUDONYM_PATTERN,
    EventKind,
    Provider,
    StrictModel,
    ToolCategory,
)


CONTRACT_VERSION = "claude-code-hooks.v1"
RECEIVER_VERSION = "claude-code-hook-receiver-1"
ADAPTER_VERSION = "claude-code-hooks-adapter-1"
SOURCE_SCHEMA_VERSION = "claude-code-hooks.receipt-clock.v1"
UNKNOWN_PROVIDER_VERSION = "unknown"
HOOK_INSTALLATION_MARKER = "claude-code-hooks-local-v1"

MAX_HOOK_PAYLOAD_BYTES = 16 * 1024 * 1024
MAX_HOOK_EVENTS_PER_SESSION = 250_000
MAX_TOOL_PAIRING_WINDOW = timedelta(hours=6)

PSEUDONYM_NAMESPACE_SESSION = "claude_code:hook-session"
PSEUDONYM_NAMESPACE_PROJECT = "claude_code:hook-project"
PSEUDONYM_NAMESPACE_TOOL_USE = "claude_code:hook-tool-use"


class HookEventName(StrEnum):
    """Closed set of Claude Code hook event names the contract understands.

    ``NOTIFICATION`` is recognised so that it can be deliberately skipped: its
    only distinguishing field is free text, and the receiver does not read it.
    Any other name is recorded as ``UNKNOWN`` so a provider that adds a new
    hook leaves an honest, content-free trace instead of vanishing.
    """

    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    NOTIFICATION = "Notification"
    STOP = "Stop"
    SUBAGENT_STOP = "SubagentStop"
    PRE_COMPACT = "PreCompact"
    UNKNOWN = "unknown"


class SessionStartSource(StrEnum):
    STARTUP = "startup"
    RESUME = "resume"
    CLEAR = "clear"
    COMPACT = "compact"
    UNKNOWN = "unknown"


class SessionEndReason(StrEnum):
    CLEAR = "clear"
    LOGOUT = "logout"
    PROMPT_INPUT_EXIT = "prompt_input_exit"
    OTHER = "other"
    UNKNOWN = "unknown"


class CompactTrigger(StrEnum):
    MANUAL = "manual"
    AUTO = "auto"
    UNKNOWN = "unknown"


# The mapping is deliberately keyed on public built-in tool names only.  A name
# outside this table - including every ``mcp__server__tool`` name, which can
# reveal a private server - is reduced to a category and then dropped.
_BUILTIN_TOOL_CATEGORIES: dict[str, ToolCategory] = {
    "Read": ToolCategory.FILE_READ,
    "NotebookRead": ToolCategory.FILE_READ,
    "Glob": ToolCategory.SEARCH,
    "Grep": ToolCategory.SEARCH,
    "LS": ToolCategory.SEARCH,
    "Write": ToolCategory.FILE_WRITE,
    "Edit": ToolCategory.FILE_WRITE,
    "MultiEdit": ToolCategory.FILE_WRITE,
    "NotebookEdit": ToolCategory.FILE_WRITE,
    "Bash": ToolCategory.COMMAND,
    "PowerShell": ToolCategory.COMMAND,
    "WebFetch": ToolCategory.NETWORK,
    "WebSearch": ToolCategory.NETWORK,
    "Task": ToolCategory.SUBAGENT,
    "Agent": ToolCategory.SUBAGENT,
    "TodoWrite": ToolCategory.OTHER,
    "TodoRead": ToolCategory.OTHER,
    "TaskCreate": ToolCategory.OTHER,
    "TaskUpdate": ToolCategory.OTHER,
    "TaskList": ToolCategory.OTHER,
    "TaskGet": ToolCategory.OTHER,
    "AskUserQuestion": ToolCategory.OTHER,
    "EnterPlanMode": ToolCategory.OTHER,
    "ExitPlanMode": ToolCategory.OTHER,
    "Skill": ToolCategory.OTHER,
    "ToolSearch": ToolCategory.OTHER,
}

_HOOK_EVENT_KINDS: dict[HookEventName, EventKind] = {
    HookEventName.SESSION_START: EventKind.SESSION_START,
    HookEventName.SESSION_END: EventKind.SESSION_END,
    HookEventName.USER_PROMPT_SUBMIT: EventKind.TURN_START,
    HookEventName.PRE_TOOL_USE: EventKind.TOOL_START,
    HookEventName.POST_TOOL_USE: EventKind.TOOL_END,
    HookEventName.STOP: EventKind.TURN_END,
    HookEventName.SUBAGENT_STOP: EventKind.SUBAGENT_END,
    HookEventName.PRE_COMPACT: EventKind.COMPACTION,
    HookEventName.UNKNOWN: EventKind.UNKNOWN,
}


# Deterministic, content-free classification of a shell command into the
# closed TEST / BUILD categories.  Only the leading program words are matched;
# the command text itself is never kept.  Anything unmatched stays COMMAND.
COMMAND_CLASSIFY_MAX_CHARS = 400
_TEST_PROGRAMS = frozenset(
    {
        "pytest", "py.test", "tox", "nox", "vitest", "jest", "mocha", "ava", "karma",
        "cypress", "playwright", "phpunit", "rspec", "minitest", "ctest", "busted",
        "prove", "elixir", "mix", "swift", "flutter", "bun", "deno", "go", "cargo",
        "dotnet", "mvn", "mvnw", "gradle", "gradlew", "make", "npm", "pnpm", "yarn",
        "npx", "bundle", "rake", "unittest", "behave", "nosetests", "ginkgo",
    }
)
_TEST_WORDS = frozenset({"test", "tests", "spec", "check", "verify", "e2e", "rspec", "unittest"})
_ALWAYS_TEST = frozenset(
    {"pytest", "py.test", "tox", "nox", "vitest", "jest", "mocha", "ava", "karma",
     "cypress", "playwright", "phpunit", "rspec", "minitest", "ctest", "busted",
     "unittest", "behave", "nosetests", "ginkgo"}
)
_ALWAYS_BUILD = frozenset({"tsc", "webpack", "esbuild", "rollup", "ninja", "gcc", "g++", "clang", "clang++", "javac", "rustc", "cl"})
_BUILD_WORDS = frozenset({"build", "compile", "package", "assemble", "install", "bundle", "dist"})
_BUILD_PROGRAMS = frozenset(
    {"npm", "pnpm", "yarn", "npx", "bun", "cargo", "go", "dotnet", "mvn", "mvnw", "gradle",
     "gradlew", "make", "cmake", "docker", "podman", "bazel", "vite", "next", "nuxt", "swift", "flutter", "mix", "zig"}
)


def classify_command(command: object) -> ToolCategory:
    """Classify a shell command as TEST, BUILD, or COMMAND without keeping it."""

    if not isinstance(command, str) or not command.strip():
        return ToolCategory.COMMAND
    head = command[:COMMAND_CLASSIFY_MAX_CHARS]
    # Look at each simple command in a pipeline / chain; the first that is a
    # recognised test or build invocation decides (test outranks build).
    found_build = False
    for segment in _split_segments(head):
        words = [word for word in segment.split() if word]
        # Skip environment assignments and common runners/prefixes.
        while words and ("=" in words[0] or words[0] in {"time", "sudo", "env", "exec", "nice", "uv", "poetry", "pipenv", "hatch", "pdm"}):
            words.pop(0)
        if words and words[0] in {"run"} and len(words) > 1:
            words.pop(0)
        # Package runners execute the named tool: classify the tool itself.
        if len(words) > 1 and words[0].rsplit("/", 1)[-1].lower() in {"npx", "bunx", "pnpx"}:
            words.pop(0)
        if not words:
            continue
        program = words[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
        if program.startswith("./"):
            program = program[2:]
        if program.endswith(".exe") or program.endswith(".cmd") or program.endswith(".bat"):
            program = program.rsplit(".", 1)[0]
        if program in {"python", "python3", "py"} and len(words) > 2 and words[1] == "-m":
            program = words[2].lower()
            words = words[2:]
        rest = [word.lower() for word in words[1:]]
        if program in _ALWAYS_TEST:
            return ToolCategory.TEST
        if program in _TEST_PROGRAMS and any(
            word in _TEST_WORDS or word.startswith("test") for word in rest
        ):
            return ToolCategory.TEST
        if program in _ALWAYS_BUILD:
            found_build = True
            continue
        if program in _BUILD_PROGRAMS and any(
            word in _BUILD_WORDS or word.startswith("build") for word in rest
        ):
            found_build = True
            continue
        if program == "make" and (not rest or rest[0] in {"all", "-j", "-c"}):
            found_build = True
    return ToolCategory.BUILD if found_build else ToolCategory.COMMAND


def _split_segments(text: str) -> list[str]:
    segments: list[str] = []
    current: list[str] = []
    index = 0
    while index < len(text):
        two = text[index : index + 2]
        if two in {"&&", "||"} or text[index] in {";", "|", "\n"}:
            segments.append("".join(current))
            current = []
            index += 2 if two in {"&&", "||"} else 1
            continue
        current.append(text[index])
        index += 1
    segments.append("".join(current))
    return [segment.strip() for segment in segments if segment.strip()]


def categorize_tool_name(tool_name: object) -> ToolCategory:
    """Reduce a provider tool name to a closed category; the name is not kept."""

    if not isinstance(tool_name, str) or not tool_name:
        return ToolCategory.UNKNOWN
    if tool_name.startswith("mcp__"):
        return ToolCategory.MCP
    return _BUILTIN_TOOL_CATEGORIES.get(tool_name, ToolCategory.UNKNOWN)


def hook_event_kind(name: HookEventName) -> EventKind:
    return _HOOK_EVENT_KINDS[name]


def parse_hook_event_name(value: object) -> HookEventName:
    if isinstance(value, str):
        try:
            return HookEventName(value)
        except ValueError:
            return HookEventName.UNKNOWN
    return HookEventName.UNKNOWN


def _closed(enum: type[StrEnum], value: object, unknown: StrEnum) -> StrEnum:
    if isinstance(value, str):
        try:
            return enum(value)
        except ValueError:
            return unknown
    return unknown


def parse_session_start_source(value: object) -> SessionStartSource:
    return _closed(SessionStartSource, value, SessionStartSource.UNKNOWN)  # type: ignore[return-value]


def parse_session_end_reason(value: object) -> SessionEndReason:
    return _closed(SessionEndReason, value, SessionEndReason.UNKNOWN)  # type: ignore[return-value]


def parse_compact_trigger(value: object) -> CompactTrigger:
    return _closed(CompactTrigger, value, CompactTrigger.UNKNOWN)  # type: ignore[return-value]


def lexical_cwd(value: str) -> str:
    """Normalize path syntax without filesystem access or symlink resolution.

    Mirrors the Codex mapper so a directory yields the same project identity
    regardless of which provider observed it.
    """

    portable = value.replace("\\", "/")
    normalized = posixpath.normpath(portable)
    drive_match = re.match(r"^([A-Za-z]):(/.*)?$", normalized)
    if drive_match:
        tail = drive_match.group(2) or "/"
        normalized = f"{drive_match.group(1).casefold()}:{tail}"
    return normalized


def normalized_project_path(cwd: object) -> str | None:
    if not isinstance(cwd, str) or not cwd:
        return None
    normalized = lexical_cwd(cwd)
    if normalized in ("", "."):
        return None
    if not (
        normalized.startswith("/") or re.match(r"^[a-z]:/", normalized) is not None
    ):
        return None
    return normalized


def project_identity_material(cwd: object, session_id: str) -> str:
    """Raw project identity fed to the HMAC; the path itself is never stored."""

    normalized = normalized_project_path(cwd)
    if normalized is not None:
        return normalized
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return f"missing-cwd-{digest}"


def project_display_label(cwd: object) -> str | None:
    """Bounded basename label, or None when the directory names a person."""

    normalized = normalized_project_path(cwd)
    if normalized is None:
        return None
    trimmed = normalized.rstrip("/")
    if not trimmed or re.fullmatch(r"[a-z]:", trimmed) is not None:
        return None
    components = tuple(component for component in trimmed.split("/") if component)
    if len(components) >= 2 and components[-2].casefold() in {"home", "users"}:
        return None
    return minimize_private_display_name(
        posixpath.basename(trimmed), max_length=PROJECT_DISPLAY_NAME_MAX_LENGTH
    )


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("hook identifiers must be 64-character HMAC pseudonyms")
    return value


#: A title taken from a prompt is cut at a word boundary well below the column
#: bound so lists stay readable and as little of the prompt as possible is kept.
SESSION_TITLE_SOFT_LIMIT = 96


def session_title_from_prompt(prompt: object) -> str | None:
    """Bounded one-line private title from the first non-empty prompt line.

    Nothing beyond that first line is ever read into the result; the
    minimizer additionally refuses absolute paths and control characters, and
    long lines are shortened at a word boundary with an ellipsis.
    """

    if not isinstance(prompt, str) or not prompt:
        return None
    for line in prompt.splitlines():
        candidate = line.strip()
        if candidate:
            minimized = minimize_private_display_name(
                candidate, max_length=SESSION_DISPLAY_NAME_MAX_LENGTH
            )
            if minimized is None or len(minimized) <= SESSION_TITLE_SOFT_LIMIT:
                return minimized
            head = minimized[: SESSION_TITLE_SOFT_LIMIT - 3]
            cut = head.rfind(" ")
            if cut >= SESSION_TITLE_SOFT_LIMIT // 2:
                head = head[:cut]
            # Re-minimize so the stored label is a fixed point of the minimizer.
            return minimize_private_display_name(
                head.rstrip(" ,;:-") + "...", max_length=SESSION_DISPLAY_NAME_MAX_LENGTH
            )
    return None


class MinimizedHookEvent(StrictModel):
    """The only record shape the receiver may hand to the ledger.

    Every field is either a closed enum, a bounded label, a pseudonym, or a
    non-negative number.  There is no field that could hold prompt text, tool
    input or output, a path, a transcript reference, or a raw identifier, so a
    receiver bug cannot smuggle content past the type.
    """

    contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    receiver_version: Literal[RECEIVER_VERSION] = RECEIVER_VERSION
    provider: Literal[Provider.CLAUDE_CODE] = Provider.CLAUDE_CODE
    hook_session_id: str
    hook_project_id: str
    project_display_label: str | None = Field(default=None, repr=False)
    session_display_label: str | None = Field(default=None, repr=False)
    hook_event_name: HookEventName
    event_kind: EventKind
    received_at: datetime
    tool_category: ToolCategory | None = None
    tool_use_ref: str | None = None
    session_start_source: SessionStartSource | None = None
    session_end_reason: SessionEndReason | None = None
    compact_trigger: CompactTrigger | None = None
    success: bool | None = None

    _validate_ids = field_validator("hook_session_id", "hook_project_id")(_pseudonym)

    @field_validator("tool_use_ref")
    @classmethod
    def validate_tool_use_ref(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @field_validator("project_display_label")
    @classmethod
    def validate_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if minimize_private_display_name(
            value, max_length=PROJECT_DISPLAY_NAME_MAX_LENGTH
        ) != value:
            raise ValueError("project display label must already be minimized")
        return value

    @field_validator("session_display_label")
    @classmethod
    def validate_session_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if minimize_private_display_name(
            value, max_length=SESSION_DISPLAY_NAME_MAX_LENGTH
        ) != value:
            raise ValueError("session display label must already be minimized")
        return value

    @field_validator("received_at")
    @classmethod
    def validate_received_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("hook receipt time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_shape(self) -> "MinimizedHookEvent":
        if self.event_kind is not hook_event_kind(self.hook_event_name):
            raise ValueError("hook event kind does not match its hook event name")
        is_tool = self.hook_event_name in (
            HookEventName.PRE_TOOL_USE,
            HookEventName.POST_TOOL_USE,
        )
        if (self.tool_category is not None or self.tool_use_ref is not None) and not is_tool:
            raise ValueError("tool fields are permitted only on tool hooks")
        if is_tool and self.tool_category is None:
            raise ValueError("tool hooks must carry a tool category")
        if self.session_start_source is not None and (
            self.hook_event_name is not HookEventName.SESSION_START
        ):
            raise ValueError("session start source is permitted only on SessionStart")
        if self.session_end_reason is not None and (
            self.hook_event_name is not HookEventName.SESSION_END
        ):
            raise ValueError("session end reason is permitted only on SessionEnd")
        if self.compact_trigger is not None and (
            self.hook_event_name is not HookEventName.PRE_COMPACT
        ):
            raise ValueError("compaction trigger is permitted only on PreCompact")
        if self.success is not None and self.hook_event_name is not HookEventName.POST_TOOL_USE:
            raise ValueError("success is asserted only by PostToolUse")
        if self.session_display_label is not None and (
            self.hook_event_name is not HookEventName.USER_PROMPT_SUBMIT
        ):
            raise ValueError("a session title is derived only from UserPromptSubmit")
        return self
