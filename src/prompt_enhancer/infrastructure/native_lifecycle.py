"""Content-free, crash-observable lifecycle evidence for native launchers.

The marker deliberately contains no timestamps, process identifiers, ports,
paths, prompts, sessions, model identifiers or exception text. A non-terminal
phase left on disk is evidence that the previous process did not publish a
clean terminal outcome; it is not proof of why that process ended.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
from pathlib import Path
from typing import Any

from ..application.runtime_lifecycle import RuntimeComponent
from ..privacy import write_private_text_atomic


NATIVE_LIFECYCLE_CONTRACT = "native-lifecycle.v1"
MAX_NATIVE_LIFECYCLE_BYTES = 4096

NATIVE_FAILURE_REASON_CODES = frozenset(
    {
        "desktop_failed",
        "unsupported_platform",
        "configuration_invalid",
        "local_state_unavailable",
        "dependency_unavailable",
        "window_start_failed",
        "window_close_unconfirmed",
        "port_in_use",
        "service_bind_failed",
        "service_untrusted",
        "service_not_ready",
        "service_exited",
        "runtime_start_failed",
        "service_stop_timeout",
        "service_stop_failed",
        "runtime_stop_failed",
        "runtime_stop_unconfirmed",
        "lifecycle_marker_unavailable",
    }
)


class NativeLifecycleMarkerError(RuntimeError):
    """Raised without retaining filesystem or serialization details."""


class NativeWindowKind(StrEnum):
    AGENT = "agent"
    OVERLAY = "overlay"


class NativeLifecyclePhase(StrEnum):
    STARTING = "starting"
    SERVICE_READY = "service_ready"
    WINDOW_CREATED = "window_created"
    WINDOW_CLOSED = "window_closed"
    STOPPED = "stopped"
    FAILED = "failed"


class PreviousNativeOutcome(StrEnum):
    ABSENT = "absent"
    STOPPED = "stopped"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"


_TERMINAL_PHASES = {NativeLifecyclePhase.STOPPED, NativeLifecyclePhase.FAILED}
_TRANSITIONS = {
    NativeLifecyclePhase.STARTING: NativeLifecyclePhase.SERVICE_READY,
    NativeLifecyclePhase.SERVICE_READY: NativeLifecyclePhase.WINDOW_CREATED,
    NativeLifecyclePhase.WINDOW_CREATED: NativeLifecyclePhase.WINDOW_CLOSED,
    NativeLifecyclePhase.WINDOW_CLOSED: NativeLifecyclePhase.STOPPED,
}
_PAYLOAD_KEYS = {
    "contract",
    "window",
    "phase",
    "terminal",
    "reason_code",
    "cleanup_reason_code",
    "components",
    "previous",
}


def _valid_previous_payload(payload: Any, window: NativeWindowKind) -> NativeLifecyclePhase | None:
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_KEYS:
        return None
    if payload.get("contract") != NATIVE_LIFECYCLE_CONTRACT or payload.get("window") != window.value:
        return None
    try:
        phase = NativeLifecyclePhase(payload.get("phase"))
    except (TypeError, ValueError):
        return None
    if payload.get("terminal") is not (phase in _TERMINAL_PHASES):
        return None
    reason = payload.get("reason_code")
    cleanup = payload.get("cleanup_reason_code")
    components = payload.get("components")
    previous = payload.get("previous")
    if phase is NativeLifecyclePhase.FAILED:
        if reason not in NATIVE_FAILURE_REASON_CODES:
            return None
    elif reason is not None or cleanup is not None or components:
        return None
    if cleanup is not None and cleanup not in NATIVE_FAILURE_REASON_CODES:
        return None
    if not isinstance(components, list) or any(
        value not in {component.value for component in RuntimeComponent}
        for value in components
    ):
        return None
    if not isinstance(previous, dict) or set(previous) != {"outcome", "phase"}:
        return None
    try:
        previous_outcome = PreviousNativeOutcome(previous.get("outcome"))
    except (TypeError, ValueError):
        return None
    previous_phase = previous.get("phase")
    if previous_phase is not None:
        try:
            NativeLifecyclePhase(previous_phase)
        except (TypeError, ValueError):
            return None
    if previous_outcome in {PreviousNativeOutcome.ABSENT, PreviousNativeOutcome.UNKNOWN}:
        if previous_phase is not None:
            return None
    elif previous_outcome is PreviousNativeOutcome.STOPPED:
        if previous_phase != NativeLifecyclePhase.STOPPED.value:
            return None
    elif previous_outcome is PreviousNativeOutcome.FAILED:
        if previous_phase != NativeLifecyclePhase.FAILED.value:
            return None
    elif previous_phase not in {
        NativeLifecyclePhase.STARTING.value,
        NativeLifecyclePhase.SERVICE_READY.value,
        NativeLifecyclePhase.WINDOW_CREATED.value,
        NativeLifecyclePhase.WINDOW_CLOSED.value,
    }:
        return None
    return phase


def _previous_state(path: Path, window: NativeWindowKind) -> dict[str, str | None]:
    if not path.exists():
        return {"outcome": PreviousNativeOutcome.ABSENT.value, "phase": None}
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError
        with path.open("rb") as source:
            encoded = source.read(MAX_NATIVE_LIFECYCLE_BYTES + 1)
        if not encoded or len(encoded) > MAX_NATIVE_LIFECYCLE_BYTES:
            raise ValueError
        phase = _valid_previous_payload(json.loads(encoded.decode("utf-8")), window)
        if phase is None:
            raise ValueError
    except Exception:
        return {"outcome": PreviousNativeOutcome.UNKNOWN.value, "phase": None}
    if phase is NativeLifecyclePhase.STOPPED:
        outcome = PreviousNativeOutcome.STOPPED
    elif phase is NativeLifecyclePhase.FAILED:
        outcome = PreviousNativeOutcome.FAILED
    else:
        outcome = PreviousNativeOutcome.INTERRUPTED
    return {"outcome": outcome.value, "phase": phase.value}


@dataclass
class NativeLifecycleMarker:
    path: Path
    window: NativeWindowKind
    _phase: NativeLifecyclePhase | None = field(default=None, init=False)
    _previous: dict[str, str | None] | None = field(default=None, init=False)

    def _write(
        self,
        phase: NativeLifecyclePhase,
        *,
        reason_code: str | None = None,
        cleanup_reason_code: str | None = None,
        components: tuple[RuntimeComponent, ...] = (),
    ) -> None:
        if self._previous is None:
            raise NativeLifecycleMarkerError("native lifecycle marker was not started")
        payload = {
            "contract": NATIVE_LIFECYCLE_CONTRACT,
            "window": self.window.value,
            "phase": phase.value,
            "terminal": phase in _TERMINAL_PHASES,
            "reason_code": reason_code,
            "cleanup_reason_code": cleanup_reason_code,
            "components": [component.value for component in components],
            "previous": self._previous,
        }
        try:
            write_private_text_atomic(
                self.path,
                json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
            )
        except Exception:
            raise NativeLifecycleMarkerError("native lifecycle marker is unavailable") from None
        self._phase = phase

    def start(self) -> None:
        if self._phase is not None:
            raise NativeLifecycleMarkerError("native lifecycle marker already started")
        self._previous = _previous_state(self.path, self.window)
        self._write(NativeLifecyclePhase.STARTING)

    def _advance(self, phase: NativeLifecyclePhase) -> None:
        if self._phase is None or _TRANSITIONS.get(self._phase) is not phase:
            raise NativeLifecycleMarkerError("invalid native lifecycle transition")
        self._write(phase)

    def service_ready(self) -> None:
        self._advance(NativeLifecyclePhase.SERVICE_READY)

    def window_created(self) -> None:
        self._advance(NativeLifecyclePhase.WINDOW_CREATED)

    def window_closed(self) -> None:
        self._advance(NativeLifecyclePhase.WINDOW_CLOSED)

    def stopped(self) -> None:
        self._advance(NativeLifecyclePhase.STOPPED)

    def failed(
        self,
        reason_code: str,
        *,
        components: tuple[RuntimeComponent, ...] = (),
        cleanup_reason_code: str | None = None,
    ) -> None:
        if self._phase is None or self._phase in _TERMINAL_PHASES:
            raise NativeLifecycleMarkerError("invalid native lifecycle failure transition")
        safe_reason = (
            reason_code if reason_code in NATIVE_FAILURE_REASON_CODES else "desktop_failed"
        )
        safe_cleanup = (
            cleanup_reason_code
            if cleanup_reason_code in NATIVE_FAILURE_REASON_CODES
            else None
        )
        safe_components = tuple(
            dict.fromkeys(
                component
                for component in components
                if isinstance(component, RuntimeComponent)
            )
        )
        self._write(
            NativeLifecyclePhase.FAILED,
            reason_code=safe_reason,
            cleanup_reason_code=safe_cleanup,
            components=safe_components,
        )


__all__ = [
    "MAX_NATIVE_LIFECYCLE_BYTES",
    "NATIVE_FAILURE_REASON_CODES",
    "NATIVE_LIFECYCLE_CONTRACT",
    "NativeLifecycleMarker",
    "NativeLifecycleMarkerError",
    "NativeLifecyclePhase",
    "NativeWindowKind",
    "PreviousNativeOutcome",
]
