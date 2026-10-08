"""Read-only, version-gated reader for the owner's own Claude Code transcripts.

Owner-authorized on 2026-08-19 (ADR 0011).  Claude Code stores each session as
a JSON-lines file under ``<claude home>/projects/<encoded cwd>/<session id>.jsonl``.
This reader never stores, never sends, and never modifies anything: it lists
transcript filenames, re-derives the catalog pseudonym for each stem through
the same HMAC chain the hook receiver and ingestion use, opens only the one file
that matches the requested session, and returns a bounded transcript to the
dashboard for display.  The raw session identifier is never persisted; it is
recovered from the filename at read time and dropped.

Format gating: only lines whose top-level ``type`` is ``user`` or
``assistant`` and whose ``message`` is an object are read.  Text blocks become
turns; ``tool_use`` blocks become tool-call turns carrying the tool name and a
bounded input excerpt; ``tool_result`` blocks become bounded tool-result turns.
Every other line is skipped.  A non-empty file that yields no recognised line
fails closed as ``format_unrecognized`` rather than rendering guesses.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path

from ....application.analysis.session_reader import (
    MAX_READER_TURNS,
    MAX_TOOL_CHARACTERS,
    MAX_TRANSCRIPT_CHARACTERS,
    MAX_TURN_CHARACTERS,
    ReaderRole,
    ReaderSource,
    ReaderTurn,
    SessionReadError,
    SessionReadFailure,
    SessionTranscript,
    clip,
)
from ....domain import Provider
from ....privacy import Pseudonymizer
from .contracts import HOOK_INSTALLATION_MARKER, PSEUDONYM_NAMESPACE_SESSION


CLAUDE_HOME_ENV = "PROMPT_ENHANCER_CLAUDE_HOME"
MAX_TRANSCRIPT_FILES_SCANNED = 20_000
MAX_TRANSCRIPT_FILE_BYTES = 64 * 1024 * 1024
MAX_TRANSCRIPT_LINES = 200_000
_RECOGNIZED_TYPES = ("user", "assistant")


def default_claude_home(environment: dict[str, str] | None = None, override_file: Path | None = None) -> Path:
    """Explicit env var, then an owner-supplied override file, then ~/.claude."""

    env = os.environ if environment is None else environment
    explicit = env.get(CLAUDE_HOME_ENV)
    if explicit:
        return Path(explicit)
    if override_file is not None:
        try:
            if override_file.is_file() and not override_file.is_symlink():
                text = override_file.read_text(encoding="utf-8").strip().splitlines()
                if text and text[0].strip():
                    return Path(text[0].strip())
        except OSError:
            pass
    return Path.home() / ".claude"


def catalog_session_id_for(pseudonymizer: Pseudonymizer, raw_session_id: str) -> str:
    """The exact chain the hook receiver and the ingestion service apply."""

    hook_session_id = pseudonymizer.pseudonymize(PSEUDONYM_NAMESPACE_SESSION, raw_session_id)
    installation_id = pseudonymizer.pseudonymize(
        f"{Provider.CLAUDE_CODE.value}:installation", HOOK_INSTALLATION_MARKER
    )
    return pseudonymizer.pseudonymize(
        f"{Provider.CLAUDE_CODE.value}:session:{installation_id}", hook_session_id
    )


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


def _text_of(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return ""


def _turns_from_line(record: dict[str, object]) -> list[ReaderTurn]:
    kind = record.get("type")
    message = record.get("message")
    if kind not in _RECOGNIZED_TYPES or not isinstance(message, dict):
        return []
    at = _timestamp(record.get("timestamp"))
    role = ReaderRole.USER if kind == "user" else ReaderRole.ASSISTANT
    content = message.get("content")
    turns: list[ReaderTurn] = []
    if isinstance(content, str):
        text, truncated = clip(content, MAX_TURN_CHARACTERS)
        if text.strip():
            turns.append(ReaderTurn(role=role, text=text, at=at, truncated=truncated))
        return turns
    if not isinstance(content, list):
        return turns
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text" and isinstance(block.get("text"), str):
            text, truncated = clip(block["text"], MAX_TURN_CHARACTERS)
            if text.strip():
                turns.append(ReaderTurn(role=role, text=text, at=at, truncated=truncated))
        elif block_type == "tool_use":
            name = block.get("name")
            tool_name = name if isinstance(name, str) and name else None
            try:
                rendered = json.dumps(block.get("input"), ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError):
                rendered = ""
            text, truncated = clip(rendered, MAX_TOOL_CHARACTERS)
            turns.append(ReaderTurn(role=ReaderRole.TOOL_CALL, text=text, at=at, tool_name=tool_name and tool_name[:120], truncated=truncated))
        elif block_type == "tool_result":
            text, truncated = clip(_text_of(block.get("content")), MAX_TOOL_CHARACTERS)
            turns.append(ReaderTurn(role=ReaderRole.TOOL_RESULT, text=text, at=at, truncated=truncated))
    return turns


class ClaudeTranscriptReader:
    """Reads one transcript file on demand; keeps nothing."""

    provider = Provider.CLAUDE_CODE

    def __init__(self, pseudonymizer: Pseudonymizer, claude_home: Path | None = None) -> None:
        self._pseudonymizer = pseudonymizer
        self._claude_home = claude_home

    def _home(self) -> Path:
        return self._claude_home if self._claude_home is not None else default_claude_home()

    def locate(self, catalog_session_id: str) -> Path | None:
        """Find the transcript whose stem re-derives to the requested pseudonym."""

        projects = self._home() / "projects"
        if not projects.is_dir():
            return None
        scanned = 0
        try:
            for project_dir in sorted(projects.iterdir()):
                if not project_dir.is_dir() or project_dir.is_symlink():
                    continue
                for candidate in sorted(project_dir.glob("*.jsonl")):
                    scanned += 1
                    if scanned > MAX_TRANSCRIPT_FILES_SCANNED:
                        raise SessionReadError(SessionReadFailure.LIMIT_EXCEEDED)
                    if candidate.is_symlink() or not candidate.is_file():
                        continue
                    stem = candidate.stem
                    if not stem or len(stem) > 256:
                        continue
                    if catalog_session_id_for(self._pseudonymizer, stem) == catalog_session_id:
                        return candidate
        except OSError:
            raise SessionReadError(SessionReadFailure.SOURCE_UNAVAILABLE) from None
        return None

    def read(self, catalog_session_id: str) -> SessionTranscript:
        path = self.locate(catalog_session_id)
        if path is None:
            raise SessionReadError(SessionReadFailure.SESSION_NOT_FOUND)
        try:
            size = path.stat().st_size
        except OSError:
            raise SessionReadError(SessionReadFailure.SOURCE_UNAVAILABLE) from None
        if size > MAX_TRANSCRIPT_FILE_BYTES:
            raise SessionReadError(SessionReadFailure.LIMIT_EXCEEDED)

        turns: list[ReaderTurn] = []
        total_turns = 0
        characters = 0
        recognised_lines = 0
        non_empty_lines = 0
        provider_version: str | None = None
        truncated = False
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for index, line in enumerate(handle):
                    if index >= MAX_TRANSCRIPT_LINES:
                        truncated = True
                        break
                    if not line.strip():
                        continue
                    non_empty_lines += 1
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(record, dict):
                        continue
                    if provider_version is None:
                        version = record.get("version")
                        if isinstance(version, str) and 0 < len(version) <= 64:
                            provider_version = version
                    line_turns = _turns_from_line(record)
                    if record.get("type") in _RECOGNIZED_TYPES and isinstance(record.get("message"), dict):
                        recognised_lines += 1
                    for turn in line_turns:
                        total_turns += 1
                        if len(turns) >= MAX_READER_TURNS or characters + len(turn.text) > MAX_TRANSCRIPT_CHARACTERS:
                            truncated = True
                            continue
                        turns.append(turn)
                        characters += len(turn.text)
        except OSError:
            raise SessionReadError(SessionReadFailure.SOURCE_UNAVAILABLE) from None

        if non_empty_lines > 0 and recognised_lines == 0:
            raise SessionReadError(SessionReadFailure.FORMAT_UNRECOGNIZED)
        return SessionTranscript(
            provider=Provider.CLAUDE_CODE,
            session_id=catalog_session_id,
            source=ReaderSource.CLAUDE_TRANSCRIPT_FILE,
            provider_version=provider_version if provider_version and provider_version.replace(".", "").replace("-", "").isalnum() else None,
            turns=tuple(turns),
            turn_count_total=total_turns,
            truncated=truncated,
            read_at=datetime.now(UTC),
        )


__all__ = (
    "CLAUDE_HOME_ENV",
    "ClaudeTranscriptReader",
    "catalog_session_id_for",
    "default_claude_home",
)
