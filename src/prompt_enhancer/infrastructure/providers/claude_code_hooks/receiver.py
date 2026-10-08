"""The process Claude Code invokes for each configured hook event.

Its obligations, in priority order:

1. **Never disturb the user's session.**  For several hook types Claude Code
   feeds the hook's stdout back to the model or uses it to decide permissions,
   and a non-zero exit surfaces an error in the session.  This receiver
   therefore writes nothing to stdout or stderr and always exits ``0``, even
   when it drops the event.
2. **Never persist content.**  Only the keys in :data:`ALLOWED_PAYLOAD_KEYS`
   are read.  ``tool_input``, ``tool_response``, ``message``,
   ``custom_instructions`` and ``transcript_path`` are never accessed.
   ``prompt`` is read for exactly one purpose - deriving a bounded one-line
   private session title from its first line so a person can find their own
   session by name - and only while :data:`SESSION_TITLES_ENV` is not ``0``.
   The only record shape the receiver can build is :class:`MinimizedHookEvent`,
   whose sole text-bearing fields are the two minimized display labels.
3. **Never initialize state.**  It loads an existing pseudonym key and appends
   to an existing, migrated store.  If either is missing, or if
   ``claude_code`` local-history consent is not active, it does nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from enum import StrEnum
import json
import os
import sys
from typing import BinaryIO

from ....config import AppSettings
from ....domain import StrictModel
from ....privacy import Pseudonymizer, PrivacyBoundaryError, load_pseudonymizer
from .contracts import (
    MAX_HOOK_PAYLOAD_BYTES,
    PSEUDONYM_NAMESPACE_PROJECT,
    PSEUDONYM_NAMESPACE_SESSION,
    PSEUDONYM_NAMESPACE_TOOL_USE,
    HookEventName,
    MinimizedHookEvent,
    categorize_tool_name,
    hook_event_kind,
    parse_compact_trigger,
    parse_hook_event_name,
    parse_session_end_reason,
    parse_session_start_source,
    project_display_label,
    project_identity_material,
    session_title_from_prompt,
)
from .ledger import (
    HookLedgerConsentInactive,
    HookLedgerUnavailable,
    receiver_append,
)


# The complete set of payload keys this module is permitted to read.  A test
# asserts that no other payload key name appears anywhere in this file.
ALLOWED_PAYLOAD_KEYS = frozenset(
    {"session_id", "cwd", "hook_event_name", "source", "reason", "tool_name",
     "tool_use_id", "trigger", "prompt"}
)

# Set to "0" in the environment that launches Claude Code to keep session
# titles off; the first prompt line is then never read at all.
SESSION_TITLES_ENV = "PROMPT_ENHANCER_CLAUDE_SESSION_TITLES"

MAX_RAW_ID_LENGTH = 256


class ReceiverStatus(StrEnum):
    APPENDED = "appended"
    SKIPPED_NOTIFICATION = "skipped_notification"
    CONSENT_INACTIVE = "consent_inactive"
    STORE_UNAVAILABLE = "store_unavailable"
    KEY_UNAVAILABLE = "key_unavailable"
    INVALID_PAYLOAD = "invalid_payload"
    ERROR = "error"


class ReceiverOutcome(StrictModel):
    """Test-visible result; the command-line entrypoint discards it."""

    status: ReceiverStatus
    hook_event_name: HookEventName | None = None
    sequence: int | None = None


def _raw_identifier(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if not value or len(value) > MAX_RAW_ID_LENGTH:
        return None
    if any(character in value for character in "\x00\r\n"):
        return None
    return value


def session_titles_enabled(environment: Mapping[str, str] | None = None) -> bool:
    value = (environment if environment is not None else os.environ).get(SESSION_TITLES_ENV, "1")
    return value.strip().lower() not in {"0", "false", "no", "off"}


def minimize_payload(
    payload: Mapping[str, object],
    *,
    pseudonymizer: Pseudonymizer,
    received_at: datetime,
    titles: bool = True,
) -> MinimizedHookEvent | None:
    """Reduce one hook payload to its content-free record.

    Returns ``None`` for a ``Notification`` hook, whose only distinguishing
    field is free text that this receiver does not read.  Raises
    ``ValueError`` when the payload lacks a usable session identifier.
    """

    session_id = _raw_identifier(payload.get("session_id"))
    if session_id is None:
        raise ValueError("hook payload lacks a usable session identifier")
    name = parse_hook_event_name(payload.get("hook_event_name"))
    if name is HookEventName.NOTIFICATION:
        return None

    cwd = payload.get("cwd")
    hook_session_id = pseudonymizer.pseudonymize(PSEUDONYM_NAMESPACE_SESSION, session_id)
    hook_project_id = pseudonymizer.pseudonymize(
        PSEUDONYM_NAMESPACE_PROJECT, project_identity_material(cwd, session_id)
    )

    tool_category = None
    tool_use_ref = None
    success = None
    start_source = None
    end_reason = None
    compact_trigger = None
    session_title = None
    if name is HookEventName.USER_PROMPT_SUBMIT and titles:
        session_title = session_title_from_prompt(payload.get("prompt"))
    if name in (HookEventName.PRE_TOOL_USE, HookEventName.POST_TOOL_USE):
        tool_category = categorize_tool_name(payload.get("tool_name"))
        tool_use_id = _raw_identifier(payload.get("tool_use_id"))
        if tool_use_id is not None:
            tool_use_ref = pseudonymizer.pseudonymize(
                f"{PSEUDONYM_NAMESPACE_TOOL_USE}:{hook_session_id}", tool_use_id
            )
        if name is HookEventName.POST_TOOL_USE:
            # Claude Code documents PostToolUse as firing after a tool
            # completes successfully; a PreToolUse without a matching
            # PostToolUse stays unknown, never failed.
            success = True
    elif name is HookEventName.SESSION_START:
        start_source = parse_session_start_source(payload.get("source"))
    elif name is HookEventName.SESSION_END:
        end_reason = parse_session_end_reason(payload.get("reason"))
    elif name is HookEventName.PRE_COMPACT:
        compact_trigger = parse_compact_trigger(payload.get("trigger"))

    return MinimizedHookEvent(
        hook_session_id=hook_session_id,
        hook_project_id=hook_project_id,
        project_display_label=project_display_label(cwd),
        session_display_label=session_title,
        hook_event_name=name,
        event_kind=hook_event_kind(name),
        received_at=received_at.astimezone(UTC),
        tool_category=tool_category,
        tool_use_ref=tool_use_ref,
        session_start_source=start_source,
        session_end_reason=end_reason,
        compact_trigger=compact_trigger,
        success=success,
    )


def _read_bounded(stream: BinaryIO) -> bytes | None:
    data = stream.read(MAX_HOOK_PAYLOAD_BYTES + 1)
    if data is None or len(data) > MAX_HOOK_PAYLOAD_BYTES:
        return None
    return data


def receive(
    stdin: BinaryIO,
    *,
    settings: AppSettings,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    key_loader: Callable[[AppSettings], Pseudonymizer] = (
        lambda settings: load_pseudonymizer(settings.pseudonym_key_path)
    ),
) -> ReceiverOutcome:
    """Process one hook invocation.  Never raises; never writes to a stream."""

    try:
        raw = _read_bounded(stdin)
        if raw is None:
            return ReceiverOutcome(status=ReceiverStatus.INVALID_PAYLOAD)
        try:
            payload = json.loads(raw)
        except (UnicodeDecodeError, ValueError):
            return ReceiverOutcome(status=ReceiverStatus.INVALID_PAYLOAD)
        if not isinstance(payload, dict):
            return ReceiverOutcome(status=ReceiverStatus.INVALID_PAYLOAD)

        try:
            pseudonymizer = key_loader(settings)
        except (PrivacyBoundaryError, OSError, ValueError):
            return ReceiverOutcome(status=ReceiverStatus.KEY_UNAVAILABLE)

        try:
            event = minimize_payload(
                payload,
                pseudonymizer=pseudonymizer,
                received_at=now(),
                titles=session_titles_enabled(),
            )
        except ValueError:
            return ReceiverOutcome(status=ReceiverStatus.INVALID_PAYLOAD)
        if event is None:
            return ReceiverOutcome(
                status=ReceiverStatus.SKIPPED_NOTIFICATION,
                hook_event_name=HookEventName.NOTIFICATION,
            )

        try:
            outcome = receiver_append(settings.database_path, pseudonymizer, event)
        except HookLedgerConsentInactive:
            return ReceiverOutcome(
                status=ReceiverStatus.CONSENT_INACTIVE, hook_event_name=event.hook_event_name
            )
        except HookLedgerUnavailable:
            return ReceiverOutcome(
                status=ReceiverStatus.STORE_UNAVAILABLE, hook_event_name=event.hook_event_name
            )
        return ReceiverOutcome(
            status=ReceiverStatus.APPENDED,
            hook_event_name=event.hook_event_name,
            sequence=outcome.sequence,
        )
    except Exception:  # noqa: BLE001 - a hook must never fail the user's session
        return ReceiverOutcome(status=ReceiverStatus.ERROR)


def main(settings: AppSettings | None = None) -> int:
    """Command-line entrypoint: silent, side-effect-bounded, always exit 0."""

    try:
        resolved = settings if settings is not None else AppSettings.from_env()
        receive(sys.stdin.buffer, settings=resolved)
    except Exception:  # noqa: BLE001
        pass
    return 0


__all__ = (
    "ALLOWED_PAYLOAD_KEYS",
    "SESSION_TITLES_ENV",
    "session_titles_enabled",
    "ReceiverOutcome",
    "ReceiverStatus",
    "main",
    "minimize_payload",
    "receive",
)
