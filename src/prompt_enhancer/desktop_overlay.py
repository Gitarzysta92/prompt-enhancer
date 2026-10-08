"""Native Windows host for the content-free live-metrics overlay.

The host deliberately reuses the authenticated loopback application.  It does
not put API credentials, provider identifiers, or session identifiers in the
window URL, command line, logs, or Javascript bridge, and it never sends the
persistent API token to a listener whose identity has not been proven first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import ipaddress
import json
from pathlib import PureWindowsPath
import re
import socket
from threading import Event, RLock, Thread
import time
from types import ModuleType
from typing import Any, Callable
import urllib.request
import urllib.parse

from .config import AppSettings
from .application.runtime_lifecycle import RuntimeComponent, RuntimeLifecycleReport
from .interfaces.http.desktop_identity import (
    DESKTOP_CHALLENGE_HEADER,
    DESKTOP_IDENTITY_PATH,
    DESKTOP_IDENTITY_VERSION,
    canonical_loopback_origin,
    is_desktop_owned_instance_path,
    new_desktop_owned_instance_path,
    new_desktop_challenge,
    verify_desktop_identity_proof,
)
from .interfaces.http.user_presence import (
    USER_PRESENCE_HEADER,
    USER_PRESENCE_VERSION,
    UserPresenceApprovalManager,
)
from .infrastructure.native_lifecycle import (
    NATIVE_FAILURE_REASON_CODES,
    NativeLifecycleMarker,
    NativeLifecycleMarkerError,
    NativeWindowKind,
)
from .infrastructure.windows_single_instance import (
    WindowsSingleInstanceError,
    acquire_windows_instance,
    focus_existing_window,
)
from .privacy import load_or_create_api_token


_OVERLAY_PATH = "/overlay/model-ensemble"
_AGENT_PATH = "/agent"
_AGENT_WINDOW_PATH = "/agent/window"
_AGENT_WINDOW_TITLE = "Prompt Enhancer - Agent workspace"
_AGENT_CHAT_WINDOW_TITLE = "Prompt Enhancer - Agent chat"
_AGENT_INSTANCE_NAME = "Local\\PromptEnhancer.AgentWorkspace.v1"
_FOLDER_PICKER_VERSION = "native-folder-picker-v1"
_AGENT_WINDOW_VERSION = "native-agent-window-v1"
_AGENT_WINDOW_KEY = re.compile(r"^[a-f0-9]{32}$")
_PROBE_TIMEOUT_SECONDS = 1.0
_STARTUP_TIMEOUT_SECONDS = 20.0
_STARTUP_POLL_SECONDS = 0.1
_MAX_PROBE_BYTES = 64 * 1024
_SERVICE_STOP_TIMEOUT_SECONDS = 45.0
_SERVICE_FORCE_STOP_TIMEOUT_SECONDS = 5.0
_REQUEST_DRAIN_TIMEOUT_SECONDS = 3.0

# All native diagnostics are selected from this vocabulary. Never display the
# caught exception's message, repr, traceback, or arbitrary attributes.
_FAILURE_MESSAGES = {
    "desktop_failed": "The desktop window could not complete its operation.",
    "unsupported_platform": "The native desktop window requires Windows.",
    "configuration_invalid": "The local application configuration is not valid.",
    "local_state_unavailable": "The application could not access its local state.",
    "dependency_unavailable": "The desktop runtime is unavailable. Check the desktop installation and WebView2 runtime.",
    "window_start_failed": "The local service started, but the native window could not open.",
    "window_close_unconfirmed": "The native window loop ended without a confirmed close event. Cleanup is not assumed.",
    "port_in_use": "The configured local port is already in use. Close the other application instance before retrying.",
    "service_bind_failed": "The native launcher could not reserve a private loopback listener.",
    "service_untrusted": "The listener on the configured local port could not be verified. It was not given access.",
    "service_not_ready": "The owned local service did not become ready in time.",
    "service_exited": "The owned local service exited unexpectedly.",
    "runtime_start_failed": "An application component could not start. Check the component code below.",
    "service_stop_timeout": "The owned local service did not stop within the allowed time. Cleanup is not confirmed.",
    "service_stop_failed": "The owned local service could not be checked during shutdown. Cleanup is not confirmed.",
    "runtime_stop_failed": "The local listener stopped, but one or more application components did not confirm cleanup.",
    "runtime_stop_unconfirmed": "The local listener stopped without a confirmed application cleanup. Model unloading is not confirmed.",
    "lifecycle_marker_unavailable": "The native lifecycle status could not be recorded safely.",
}

if frozenset(_FAILURE_MESSAGES) != NATIVE_FAILURE_REASON_CODES:
    raise RuntimeError("native lifecycle failure vocabulary is inconsistent")


class DesktopOverlayError(RuntimeError):
    """Base class for safe, content-free desktop-host failures."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "desktop_failed",
        components: tuple[RuntimeComponent, ...] = (),
        cleanup_reason_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = (
            reason_code if reason_code in _FAILURE_MESSAGES else "desktop_failed"
        )
        self.components = tuple(
            component for component in components if isinstance(component, RuntimeComponent)
        )
        self.cleanup_reason_code = (
            cleanup_reason_code if cleanup_reason_code in _FAILURE_MESSAGES else None
        )


class DesktopOverlayDependencyError(DesktopOverlayError):
    """Raised when the optional native host dependency is unavailable."""


class DesktopOverlayServiceError(DesktopOverlayError):
    """Raised when the configured loopback service cannot be trusted or started."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect away from the probed loopback origin."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        del request, file_pointer, code, message, headers, new_url
        return None


@dataclass
class _OwnedServer:
    server: Any
    thread: Thread
    user_presence: UserPresenceApprovalManager
    readiness_path: str
    lifecycle: RuntimeLifecycleReport = field(default_factory=RuntimeLifecycleReport)
    thread_failed: Event = field(default_factory=Event)
    cleanup_runtime: Callable[[], None] | None = None
    endpoints: tuple[tuple[str, str], ...] = ()
    listener: socket.socket | None = None

    def stop(self) -> None:
        """Stop only the Uvicorn instance created by this desktop host."""

        self.server.should_exit = True
        join_failed = False
        alive = True
        try:
            self.thread.join(timeout=_SERVICE_STOP_TIMEOUT_SECONDS)
            alive = self.thread.is_alive()
        except Exception:
            join_failed = True
        if alive:
            self.server.force_exit = True
            try:
                self.thread.join(timeout=_SERVICE_FORCE_STOP_TIMEOUT_SECONDS)
                alive = self.thread.is_alive()
            except Exception:
                join_failed = True
        listener_failed = False
        if self.listener is not None:
            try:
                self.listener.close()
                self.listener = None
            except Exception:
                listener_failed = True
        cleanup_failed = False
        if not alive and not self.lifecycle.cleanup_finished and self.cleanup_runtime is not None:
            try:
                self.cleanup_runtime()
            except Exception:
                cleanup_failed = True
        # Raise outside the except blocks: retaining an exception context could
        # retain private adapter state even when its text is not displayed.
        if join_failed or listener_failed:
            raise DesktopOverlayServiceError(
                "desktop service shutdown could not be verified",
                reason_code="service_stop_failed",
            )
        if alive:
            raise DesktopOverlayServiceError(
                "desktop service did not stop",
                reason_code="service_stop_timeout",
            )
        if cleanup_failed or self.lifecycle.shutdown_failures:
            raise DesktopOverlayServiceError(
                "desktop runtime cleanup was incomplete",
                reason_code="runtime_stop_failed",
                components=self.lifecycle.shutdown_failures,
            )
        if not self.lifecycle.cleanup_finished:
            raise DesktopOverlayServiceError(
                "desktop runtime cleanup was not confirmed",
                reason_code="runtime_stop_unconfirmed",
            )
        if self.thread_failed.is_set():
            raise DesktopOverlayServiceError(
                "desktop service exited unexpectedly",
                reason_code="service_exited",
            )


class _DesktopWindowApi:
    """Content-free bridge for window chrome and native user presence."""

    def __init__(
        self,
        user_presence: UserPresenceApprovalManager | None = None,
        expected_origin: str | None = None,
    ) -> None:
        self._window: Any | None = None
        self._maximized = False
        self._user_presence = user_presence
        self._expected_origin = expected_origin

    def _bind(self, window: Any) -> None:
        self._window = window

    def minimize_window(self) -> None:
        if self._window is not None:
            self._window.minimize()

    def toggle_maximize_window(self) -> bool:
        if self._window is None:
            return False
        if self._maximized:
            self._window.restore()
        else:
            self._window.maximize()
        self._maximized = not self._maximized
        return self._maximized

    def close_window(self) -> None:
        if self._window is not None:
            self._window.destroy()

    def confirm_user_presence(self, request: Any) -> dict[str, Any]:
        """Show a native dialog and return one exact, short-lived capability."""

        manager = self._user_presence
        window = self._window
        if manager is None or window is None:
            return {
                "approved": False,
                "reason": "native_confirmation_unavailable",
                "version": USER_PRESENCE_VERSION,
            }
        if not self._window_origin_is_expected(window):
            return {
                "approved": False,
                "reason": "native_confirmation_unavailable",
                "version": USER_PRESENCE_VERSION,
            }
        if not isinstance(request, dict) or set(request) != {
            "method",
            "path",
            "body_sha256",
        }:
            return {
                "approved": False,
                "reason": "invalid_confirmation_request",
                "version": USER_PRESENCE_VERSION,
            }
        method = request.get("method")
        path = request.get("path")
        body_sha256 = request.get("body_sha256")
        if not all(isinstance(value, str) for value in (method, path, body_sha256)):
            return {
                "approved": False,
                "reason": "invalid_confirmation_request",
                "version": USER_PRESENCE_VERSION,
            }
        label = manager.action_label(method, path)
        if label is None:
            return {
                "approved": False,
                "reason": "action_not_allowed",
                "version": USER_PRESENCE_VERSION,
            }
        approved = bool(
            window.create_confirmation_dialog(
                "Confirm local action",
                f"{label}.\n\nApprove only if you initiated and reviewed this action.",
            )
        )
        if not approved:
            return {
                "approved": False,
                "reason": "user_declined",
                "version": USER_PRESENCE_VERSION,
            }
        if not self._window_origin_is_expected(window):
            return {
                "approved": False,
                "reason": "native_confirmation_unavailable",
                "version": USER_PRESENCE_VERSION,
            }
        try:
            token = manager.issue(
                method=method,
                path=path,
                body_sha256=body_sha256,
            )
        except ValueError:
            return {
                "approved": False,
                "reason": "invalid_confirmation_request",
                "version": USER_PRESENCE_VERSION,
            }
        return {
            "approved": True,
            "approval_token": token,
            "version": USER_PRESENCE_VERSION,
        }

    def _window_origin_is_expected(self, window: Any) -> bool:
        expected = self._expected_origin
        if expected is None:
            return False
        try:
            current = window.get_current_url()
            current_url = urllib.parse.urlsplit(current)
            expected_url = urllib.parse.urlsplit(expected)
            if (
                not isinstance(current, str)
                or current_url.username is not None
                or current_url.password is not None
                or current_url.scheme.casefold() not in {"http", "https"}
            ):
                return False
            return (
                current_url.scheme.casefold(),
                (current_url.hostname or "").casefold(),
                current_url.port,
            ) == (
                expected_url.scheme.casefold(),
                (expected_url.hostname or "").casefold(),
                expected_url.port,
            )
        except (AttributeError, TypeError, ValueError):
            return False


class _DesktopAgentWindowApi(_DesktopWindowApi):
    """Owned Agent bridge with one explicit, user-driven folder chooser.

    Unlike the content-free confirmation bridge, a successful folder choice
    returns the path the person selected.  The value is never logged or kept
    by this bridge, and the local-agent service remains authoritative for all
    protected-root, drive-root, reparse-point, and workspace validation.
    """

    def __init__(
        self,
        user_presence: UserPresenceApprovalManager,
        expected_origin: str,
        folder_dialog_type: Any | None,
        window_coordinator: "_NativeAgentWindowCoordinator | None" = None,
    ) -> None:
        super().__init__(user_presence, expected_origin)
        self._folder_dialog_type = folder_dialog_type
        self._window_coordinator = window_coordinator

    @staticmethod
    def _folder_picker_response(
        status: str,
        path: str | None = None,
    ) -> dict[str, Any]:
        if status == "selected" and path is not None:
            return {
                "version": _FOLDER_PICKER_VERSION,
                "status": "selected",
                "path": path,
            }
        return {
            "version": _FOLDER_PICKER_VERSION,
            "status": status,
        }

    def _window_route_is_agent(self, window: Any) -> bool:
        if not self._window_origin_is_expected(window):
            return False
        try:
            current = urllib.parse.urlsplit(window.get_current_url())
        except (AttributeError, TypeError, ValueError):
            return False
        if current.fragment != "":
            return False
        if current.path == _AGENT_PATH:
            return current.query == ""
        if current.path != _AGENT_WINDOW_PATH:
            return False
        try:
            query = urllib.parse.parse_qs(
                current.query,
                keep_blank_values=True,
                strict_parsing=True,
            )
        except ValueError:
            return False
        return (
            set(query) == {"window"}
            and len(query["window"]) == 1
            and _AGENT_WINDOW_KEY.fullmatch(query["window"][0]) is not None
        )

    def open_agent_chat_window(self, request: Any) -> dict[str, Any]:
        """Open or focus the one in-process Agent chat window.

        The bridge receives only a fresh opaque rendezvous key. Session and
        project identifiers stay in same-origin browser memory and never cross
        this Python boundary or enter a native URL.
        """

        coordinator = self._window_coordinator
        window = self._window
        if (
            coordinator is None
            or window is None
            or not self._window_route_is_agent(window)
        ):
            return _native_agent_window_receipt("unavailable", None)
        if (
            not isinstance(request, dict)
            or set(request) != {"version", "window_key"}
            or request.get("version") != _AGENT_WINDOW_VERSION
            or not isinstance(request.get("window_key"), str)
            or _AGENT_WINDOW_KEY.fullmatch(request["window_key"]) is None
        ):
            return _native_agent_window_receipt("invalid_request", None)
        return coordinator.open_or_focus(request["window_key"])

    def choose_workspace_folder(self) -> dict[str, Any]:
        """Open the owned native folder dialog and return the exact v1 shape."""

        window = self._window
        if (
            window is None
            or self._folder_dialog_type is None
            or not self._window_route_is_agent(window)
        ):
            return self._folder_picker_response("unavailable")
        try:
            selected = window.create_file_dialog(
                self._folder_dialog_type,
                allow_multiple=False,
            )
        except Exception:
            return self._folder_picker_response("unavailable")
        if not self._window_route_is_agent(window):
            return self._folder_picker_response("unavailable")
        if selected is None or selected == () or selected == []:
            return self._folder_picker_response("cancelled")
        if (
            not isinstance(selected, (tuple, list))
            or len(selected) != 1
            or not isinstance(selected[0], str)
        ):
            return self._folder_picker_response("unavailable")
        path = selected[0]
        if (
            not path
            or len(path) > 1024
            or "\0" in path
            or not PureWindowsPath(path).is_absolute()
        ):
            return self._folder_picker_response("unavailable")
        return self._folder_picker_response("selected", path)


def _native_agent_window_receipt(
    status: str,
    window_key: str | None,
) -> dict[str, Any]:
    """Return the exact content-free child-window bridge contract."""

    return {
        "version": _AGENT_WINDOW_VERSION,
        "status": status,
        "window_key": window_key,
        "listener_started": False,
        "worker_started": False,
        "process_spawned": False,
        "runtime_owner_created": False,
    }


@dataclass(slots=True)
class _NativeAgentChildWindow:
    key: str
    window: Any


class _NativeAgentWindowCoordinator:
    """Own at most one child WebView inside the primary Agent process.

    It has no application settings, server factory, subprocess callable, or
    runtime service. The primary WebView remains the sole lifecycle owner.
    """

    def __init__(
        self,
        create_window: Callable[[str], Any | None],
        focus_window: Callable[[Any], bool],
    ) -> None:
        self._create_window = create_window
        self._focus_window = focus_window
        self._lock = RLock()
        self._child: _NativeAgentChildWindow | None = None
        self._owner_closing = False

    def open_or_focus(self, requested_key: str) -> dict[str, Any]:
        if _AGENT_WINDOW_KEY.fullmatch(requested_key) is None:
            return _native_agent_window_receipt("invalid_request", None)
        with self._lock:
            if self._owner_closing:
                return _native_agent_window_receipt("unavailable", None)
            existing = self._child
            if existing is not None:
                focused = False
                try:
                    focused = bool(self._focus_window(existing.window))
                except Exception:
                    focused = False
                return _native_agent_window_receipt(
                    "focused" if focused else "focus_unconfirmed",
                    existing.key,
                )

            try:
                window = self._create_window(requested_key)
            except Exception:
                window = None
            if window is None:
                return _native_agent_window_receipt("unavailable", None)
            child = _NativeAgentChildWindow(requested_key, window)
            self._child = child

            def child_closed() -> None:
                with self._lock:
                    if self._child is child:
                        self._child = None

            try:
                window.events.closed += child_closed
            except Exception:
                self._child = None
                try:
                    window.destroy()
                except Exception:
                    pass
                return _native_agent_window_receipt("unavailable", None)
            return _native_agent_window_receipt("opened", requested_key)

    def begin_owner_shutdown(self) -> None:
        """Close the subordinate window once; never start or relaunch anything.

        A child opened for ordinary use keeps pywebview's close confirmation so
        a person cannot discard its local draft accidentally.  The primary
        owner already obtained its own quit confirmation, however.  Leaving the
        child's confirmation enabled here lets that modal outlive the primary
        window and keeps the listener/runtime owner alive behind an apparent
        application exit.  Disable only the owned child's native confirmation
        immediately before the owner-initiated destroy.
        """

        with self._lock:
            if self._owner_closing:
                return
            self._owner_closing = True
            child = self._child
        if child is not None:
            try:
                child.window.confirm_close = False
                child.window.destroy()
            except Exception:
                return

    def children_closed(self) -> bool:
        with self._lock:
            return self._child is None


def _loopback_origin(host: str, port: int) -> str:
    try:
        return canonical_loopback_origin(host, port)
    except ValueError:
        raise DesktopOverlayServiceError(
            "desktop overlay requires a validated loopback service"
        ) from None


def _exact_loopback_endpoints(host: str, port: int) -> tuple[tuple[str, str], ...]:
    """Resolve a configured loopback host to exact numeric HTTP origins.

    The WebView and identity probe use the returned numeric origin, never the
    ``localhost`` alias.  That makes the authority in the HMAC proof identical
    to the transport endpoint and prevents IPv4/IPv6 relay ambiguity.
    """

    # Validate the configuration and port before asking the resolver anything.
    _loopback_origin(host, port)
    if host.casefold() != "localhost":
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            raise DesktopOverlayServiceError(
                "desktop overlay requires a validated loopback service"
            ) from None
        return (
            (
                address.compressed,
                canonical_loopback_origin(address.compressed, port),
            ),
        )

    try:
        addresses = socket.getaddrinfo(
            host,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except OSError:
        raise DesktopOverlayServiceError(
            "desktop loopback authority could not be resolved"
        ) from None
    endpoints: list[tuple[str, str]] = []
    seen: set[str] = set()
    for family, _socktype, _protocol, _canonical_name, sockaddr in addresses:
        if family not in {socket.AF_INET, socket.AF_INET6} or not sockaddr:
            continue
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if not address.is_loopback or address.compressed in seen:
            continue
        seen.add(address.compressed)
        endpoints.append(
            (
                address.compressed,
                canonical_loopback_origin(address.compressed, port),
            )
        )
    if not endpoints:
        raise DesktopOverlayServiceError(
            "desktop loopback authority could not be resolved"
        )
    return tuple(endpoints)


def _port_is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=_PROBE_TIMEOUT_SECONDS):
            return True
    except OSError:
        return False


def _try_reserve_listener(
    address: str,
    port: int,
) -> tuple[socket.socket, tuple[tuple[str, str], ...], int] | None:
    """Atomically bind one exact loopback address without making it inheritable."""

    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    listener = socket.socket(family, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.set_inheritable(False)
        listener.bind((address, port))
        selected_port = int(listener.getsockname()[1])
        origin = canonical_loopback_origin(address, selected_port)
        return listener, ((address, origin),), selected_port
    except Exception:
        listener.close()
        return None


def _reserve_owned_listener(
    settings: AppSettings,
    *,
    allow_ephemeral: bool,
) -> tuple[socket.socket, AppSettings, tuple[tuple[str, str], ...]]:
    """Reserve the native service socket before application startup.

    Protected Agent mode may select an OS-assigned loopback port when the
    configured one is unavailable. It still owns a new server and never attaches
    the native approval bridge to the listener that occupied the configured port.
    """

    endpoints = _exact_loopback_endpoints(settings.host, settings.port)
    for address, _origin in endpoints:
        reserved = _try_reserve_listener(address, settings.port)
        if reserved is None:
            continue
        listener, selected_endpoints, selected_port = reserved
        selected = settings.model_copy(
            update={"host": selected_endpoints[0][0], "port": selected_port}
        )
        return listener, selected, selected_endpoints
    if allow_ephemeral:
        for address, _origin in endpoints:
            reserved = _try_reserve_listener(address, 0)
            if reserved is None:
                continue
            listener, selected_endpoints, selected_port = reserved
            selected = settings.model_copy(
                update={"host": selected_endpoints[0][0], "port": selected_port}
            )
            return listener, selected, selected_endpoints
    reason_code = "port_in_use" if any(
        _port_is_open(address, settings.port) for address, _origin in endpoints
    ) else "service_bind_failed"
    raise DesktopOverlayServiceError(
        "desktop loopback listener could not be reserved",
        reason_code=reason_code,
    )


def _fetch_identity_payload(origin: str, challenge: str) -> Any:
    """Send exactly one unauthenticated challenge and return the parsed body.

    The request carries no token, no cookie, and no identifier.  Any transport,
    status, size, or encoding problem is reported as ``None`` so callers never
    render provider or exception details.
    """

    request = urllib.request.Request(
        f"{origin}{DESKTOP_IDENTITY_PATH}",
        method="GET",
        headers={
            "Accept": "application/json",
            DESKTOP_CHALLENGE_HEADER: challenge,
        },
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirect(),
    )
    try:
        with opener.open(request, timeout=_PROBE_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                return None
            content_type = response.headers.get_content_type().casefold()
            if content_type != "application/json":
                return None
            body = response.read(_MAX_PROBE_BYTES + 1)
            if not body or len(body) > _MAX_PROBE_BYTES:
                return None
        return json.loads(body.decode("utf-8"))
    except Exception:
        # Collapse every failure to one value so callers and CLI error handling
        # can never render an exception that embeds listener-controlled bytes.
        return None


def _verify_service_identity(origin: str, token: str) -> bool:
    """Prove that a listener is this application without disclosing the token.

    A fresh 256-bit challenge is sent in the clear; only a service that already
    holds the same local token can return the origin-bound keyed digest.  A port
    squatter therefore sees a random value and learns nothing reusable, and a
    squatter relaying to a real instance on another loopback origin fails the
    origin binding.  Malformed, oversized, or unexpected answers are untrusted.
    """

    challenge = new_desktop_challenge()
    payload = _fetch_identity_payload(origin, challenge)
    if not isinstance(payload, dict):
        return False
    if payload.get("identity_version") != DESKTOP_IDENTITY_VERSION:
        return False
    try:
        return verify_desktop_identity_proof(
            token, origin, bytes.fromhex(challenge), payload.get("proof")
        )
    except Exception:
        return False


def _verify_owned_service_instance(origin: str, readiness_path: str) -> bool:
    """Prove readiness belongs to this exact in-process server instance.

    Persistent desktop identity intentionally allows the metrics overlay to
    attach to another trusted Prompt Enhancer process.  Protected Agent mode
    needs a stronger property: the HTTP dependency and native bridge must share
    the same approval manager.  A per-launch, unguessable exact route closes the
    bind race without putting the persistent API token on the wire.
    """

    if not is_desktop_owned_instance_path(readiness_path):
        return False
    request = urllib.request.Request(
        f"{origin}{readiness_path}",
        method="GET",
        headers={"Accept": "application/json"},
    )
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirect(),
    )
    try:
        with opener.open(request, timeout=_PROBE_TIMEOUT_SECONDS) as response:
            if response.status != 204:
                return False
            return response.read(1) == b""
    except Exception:
        return False


def _start_owned_server(
    settings: AppSettings,
    *,
    allow_ephemeral: bool = False,
) -> _OwnedServer:
    import uvicorn
    from .bootstrap import bootstrap_local_application

    listener, selected_settings, endpoints = _reserve_owned_listener(
        settings,
        allow_ephemeral=allow_ephemeral,
    )
    try:
        application = bootstrap_local_application(selected_settings)
        user_presence = UserPresenceApprovalManager()

        def verify_user_presence(request: Any, body: bytes) -> None:
            if not user_presence.consume(
                token=request.headers.get(USER_PRESENCE_HEADER),
                method=request.method,
                path=request.url.path,
                body=body,
            ):
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=403,
                    detail="native user-presence confirmation required",
                )

        readiness_path = new_desktop_owned_instance_path()
        http_app = application.create_http_app(
            user_presence_confirmation=verify_user_presence,
            user_presence_confirmation_mode="native_bridge_bound_token",
            desktop_owned_readiness_path=readiness_path,
        )
        configuration = uvicorn.Config(
            http_app,
            host=selected_settings.host,
            port=selected_settings.port,
            access_log=False,
            log_level="warning",
            timeout_graceful_shutdown=_REQUEST_DRAIN_TIMEOUT_SECONDS,
            # Uvicorn's default exception tracebacks can carry private paths or
            # adapter values. The desktop reports only the closed lifecycle codes.
            log_config={
                "version": 1,
                "disable_existing_loggers": False,
                "handlers": {"desktop_null": {"class": "logging.NullHandler"}},
                "loggers": {
                    name: {"handlers": ["desktop_null"], "propagate": False}
                    for name in ("uvicorn", "uvicorn.error", "uvicorn.access")
                },
            },
        )
        server = uvicorn.Server(configuration)
        thread_failed = Event()

        def run_owned() -> None:
            try:
                server.run(sockets=[listener])
            except BaseException:
                # Includes Uvicorn's SystemExit on startup failure. Do not let
                # threading.excepthook render an unchecked private traceback.
                thread_failed.set()

        thread = Thread(
            target=run_owned,
            name="prompt-enhancer-desktop-loopback",
            daemon=True,
        )
        thread.start()
    except BaseException:
        listener.close()
        raise
    return _OwnedServer(
        server=server,
        thread=thread,
        user_presence=user_presence,
        readiness_path=readiness_path,
        lifecycle=http_app.state.runtime_lifecycle,
        thread_failed=thread_failed,
        cleanup_runtime=http_app.state.stop_runtime_components,
        endpoints=endpoints,
        listener=listener,
    )


def _wait_for_owned_service(
    endpoints: tuple[tuple[str, str], ...],
    token: str,
    owned: _OwnedServer,
) -> str:
    deadline = time.monotonic() + _STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if not owned.thread.is_alive():
            break
        for _address, origin in endpoints:
            if _verify_service_identity(
                origin, token
            ) and _verify_owned_service_instance(
                origin, owned.readiness_path
            ):
                if owned.thread.is_alive():
                    return origin
                break
        time.sleep(_STARTUP_POLL_SECONDS)
    lifecycle = getattr(owned, "lifecycle", None)
    if isinstance(lifecycle, RuntimeLifecycleReport) and lifecycle.startup_failure:
        raise DesktopOverlayServiceError(
            "desktop loopback component did not become ready",
            reason_code="runtime_start_failed",
            components=(lifecycle.startup_failure,),
        )
    raise DesktopOverlayServiceError(
        "desktop loopback service did not become ready",
        reason_code="service_not_ready" if owned.thread.is_alive() else "service_exited",
    )


def _load_webview() -> ModuleType:
    try:
        return importlib.import_module("webview")
    except ImportError:
        raise DesktopOverlayDependencyError(
            "desktop support is not installed; install the desktop extra",
            reason_code="dependency_unavailable",
        ) from None


def _native_folder_dialog_type(webview: ModuleType) -> Any | None:
    """Resolve pywebview 6's folder enum with a narrow legacy fallback."""

    file_dialog = getattr(webview, "FileDialog", None)
    current = None if file_dialog is None else getattr(file_dialog, "FOLDER", None)
    if current is not None:
        return current
    legacy = getattr(webview, "FOLDER_DIALOG", None)
    return legacy if legacy is not None else None


def _start_webview_until_confirmed_close(webview: ModuleType, window: Any) -> None:
    """Require the native close event before treating a returned GUI loop as clean."""

    closed = Event()

    def confirm_closed() -> None:
        closed.set()

    try:
        window.events.closed += confirm_closed
    except Exception:
        raise DesktopOverlayDependencyError(
            "native close-event confirmation is unavailable",
            reason_code="window_close_unconfirmed",
        ) from None
    webview.start(gui="edgechromium", debug=False)
    if not closed.is_set():
        raise DesktopOverlayDependencyError(
            "native window loop returned without a close event",
            reason_code="window_close_unconfirmed",
        )


def _open_overlay_window(
    webview: ModuleType,
    url: str,
    user_presence: UserPresenceApprovalManager | None = None,
    on_created: Callable[[], None] | None = None,
) -> None:
    parsed_url = urllib.parse.urlsplit(url)
    expected_origin = f"{parsed_url.scheme}://{parsed_url.netloc}"
    window_api = _DesktopWindowApi(user_presence, expected_origin)
    window = webview.create_window(
        "Prompt Enhancer - Live metrics",
        url=url,
        js_api=window_api,
        width=420,
        height=620,
        min_size=(340, 420),
        resizable=True,
        frameless=True,
        easy_drag=False,
        shadow=True,
        on_top=True,
        confirm_close=False,
        background_color="#F4F8F7",
        text_select=True,
    )
    if window is None:
        raise DesktopOverlayDependencyError(
            "desktop window could not be created", reason_code="window_start_failed"
        )
    window_api._bind(window)
    if on_created is not None:
        on_created()
    _start_webview_until_confirmed_close(webview, window)


def _open_agent_window(
    webview: ModuleType,
    url: str,
    user_presence: UserPresenceApprovalManager,
    on_created: Callable[[], None] | None = None,
) -> None:
    """Open the full Agent surface with the owned native safety bridge."""

    parsed_url = urllib.parse.urlsplit(url)
    expected_origin = f"{parsed_url.scheme}://{parsed_url.netloc}"
    folder_dialog_type = _native_folder_dialog_type(webview)
    coordinator: _NativeAgentWindowCoordinator

    def create_chat_window(window_key: str) -> Any | None:
        child_api = _DesktopAgentWindowApi(
            user_presence,
            expected_origin,
            folder_dialog_type,
            coordinator,
        )
        child = webview.create_window(
            _AGENT_CHAT_WINDOW_TITLE,
            url=f"{expected_origin}{_AGENT_WINDOW_PATH}?window={window_key}",
            js_api=child_api,
            width=1100,
            height=860,
            min_size=(360, 500),
            resizable=True,
            frameless=False,
            shadow=True,
            on_top=False,
            confirm_close=True,
            background_color="#F4F8F7",
            text_select=True,
        )
        if child is not None:
            child_api._bind(child)
        return child

    def focus_chat_window(child: Any) -> bool:
        try:
            child.restore()
            child.show()
        except Exception:
            pass
        return focus_existing_window(
            _AGENT_CHAT_WINDOW_TITLE,
            timeout_seconds=0.25,
        )

    coordinator = _NativeAgentWindowCoordinator(
        create_chat_window,
        focus_chat_window,
    )
    window_api = _DesktopAgentWindowApi(
        user_presence,
        expected_origin,
        folder_dialog_type,
        coordinator,
    )
    window = webview.create_window(
        _AGENT_WINDOW_TITLE,
        url=url,
        js_api=window_api,
        width=1280,
        height=900,
        min_size=(840, 640),
        resizable=True,
        frameless=False,
        shadow=True,
        on_top=False,
        confirm_close=True,
        background_color="#F4F8F7",
        text_select=True,
    )
    if window is None:
        raise DesktopOverlayDependencyError(
            "desktop window could not be created", reason_code="window_start_failed"
        )
    window_api._bind(window)
    try:
        window.events.closed += coordinator.begin_owner_shutdown
    except Exception:
        try:
            window.destroy()
        except Exception:
            pass
        raise DesktopOverlayDependencyError(
            "native child-window cleanup confirmation is unavailable",
            reason_code="window_close_unconfirmed",
        ) from None
    if on_created is not None:
        on_created()
    _start_webview_until_confirmed_close(webview, window)
    coordinator.begin_owner_shutdown()
    if not coordinator.children_closed():
        raise DesktopOverlayDependencyError(
            "native child window did not confirm cleanup",
            reason_code="window_close_unconfirmed",
        )


def _safe_desktop_failure(
    error: Exception, *, default_code: str = "desktop_failed"
) -> DesktopOverlayError:
    from pydantic import ValidationError

    from .config import ConfigurationError

    components: tuple[RuntimeComponent, ...] = ()
    cleanup_code = None
    if isinstance(error, DesktopOverlayError):
        code = error.reason_code
        components = error.components
        cleanup_code = error.cleanup_reason_code
    elif isinstance(error, (ConfigurationError, ValidationError)):
        code = "configuration_invalid"
    elif isinstance(error, NativeLifecycleMarkerError):
        code = "lifecycle_marker_unavailable"
    elif isinstance(error, ImportError):
        code = "dependency_unavailable"
    elif isinstance(error, OSError) and default_code == "desktop_failed":
        code = "local_state_unavailable"
    else:
        code = default_code
    code = code if code in _FAILURE_MESSAGES else "desktop_failed"
    failure_type = (
        DesktopOverlayServiceError
        if isinstance(error, DesktopOverlayServiceError)
        else DesktopOverlayDependencyError
        if isinstance(error, DesktopOverlayDependencyError)
        else DesktopOverlayError
    )
    return failure_type(
        _FAILURE_MESSAGES[code],
        reason_code=code,
        components=components,
        cleanup_reason_code=cleanup_code,
    )


def _run_with_owned_cleanup(
    owned: _OwnedServer | None, operation: Callable[[], None]
) -> None:
    """Keep primary and cleanup evidence without retaining private failures."""

    failure: DesktopOverlayError | None = None
    cleanup: DesktopOverlayError | None = None
    try:
        operation()
    except Exception as error:
        failure = _safe_desktop_failure(error, default_code="window_start_failed")
    finally:
        if owned is not None:
            try:
                owned.stop()
            except Exception as error:
                cleanup = _safe_desktop_failure(error, default_code="service_stop_failed")
    if failure is not None:
        if cleanup is not None:
            failure.cleanup_reason_code = cleanup.reason_code
            failure.components = tuple(dict.fromkeys((*failure.components, *cleanup.components)))
        raise failure
    if cleanup is not None:
        raise cleanup


def _run_with_lifecycle_marker(
    marker: NativeLifecycleMarker,
    operation: Callable[[], None],
) -> None:
    """Publish one fixed lifecycle outcome without replacing primary failure evidence."""

    try:
        marker.start()
    except Exception:
        raise DesktopOverlayError(
            _FAILURE_MESSAGES["lifecycle_marker_unavailable"],
            reason_code="lifecycle_marker_unavailable",
        ) from None
    failure: DesktopOverlayError | None = None
    try:
        operation()
    except Exception as error:
        failure = _safe_desktop_failure(error)
    if failure is not None:
        try:
            marker.failed(
                failure.reason_code,
                components=failure.components,
                cleanup_reason_code=failure.cleanup_reason_code,
            )
        except Exception:
            # Preserve the primary closed failure. The retained non-terminal
            # marker itself remains evidence that final publication failed.
            pass
        raise failure
    try:
        marker.stopped()
    except Exception:
        raise DesktopOverlayError(
            _FAILURE_MESSAGES["lifecycle_marker_unavailable"],
            reason_code="lifecycle_marker_unavailable",
        ) from None


def _run_desktop_overlay(
    settings: AppSettings,
    marker: NativeLifecycleMarker,
) -> None:
    endpoints = _exact_loopback_endpoints(settings.host, settings.port)
    token = load_or_create_api_token(settings.api_token_path)
    owned: _OwnedServer | None = None

    origin: str | None = None
    occupied_untrusted = False
    for address, candidate_origin in endpoints:
        if not _port_is_open(address, settings.port):
            continue
        if _verify_service_identity(candidate_origin, token):
            origin = candidate_origin
            break
        occupied_untrusted = True
    if origin is None and occupied_untrusted:
        raise DesktopOverlayServiceError(
            "configured loopback port is occupied by an untrusted service",
            reason_code="service_untrusted",
        )
    if origin is None:
        owned = _start_owned_server(settings)
        endpoints = owned.endpoints

    def open_window() -> None:
        nonlocal origin
        if owned is not None:
            origin = _wait_for_owned_service(endpoints, token, owned)
        assert origin is not None
        marker.service_ready()
        _open_overlay_window(
            _load_webview(),
            f"{origin}{_OVERLAY_PATH}",
            None if owned is None else owned.user_presence,
            marker.window_created,
        )
        marker.window_closed()

    _run_with_owned_cleanup(owned, open_window)


def run_desktop_overlay(settings: AppSettings) -> None:
    """Attach to the trusted local service or own one for the window lifetime."""

    if not sys_platform_is_windows():
        raise DesktopOverlayError(
            "desktop overlay is currently available only on Windows",
            reason_code="unsupported_platform",
        )
    marker = NativeLifecycleMarker(
        settings.native_overlay_lifecycle_path,
        NativeWindowKind.OVERLAY,
    )
    _run_with_lifecycle_marker(marker, lambda: _run_desktop_overlay(settings, marker))


def _run_desktop_agent(
    settings: AppSettings,
    marker: NativeLifecycleMarker,
) -> None:
    """Own the loopback server and open Agent with protected actions enabled.

    Unlike the read-only-compatible metrics overlay, the Agent window never
    attaches to an existing listener.  The native window and HTTP dependency
    share the same in-process one-shot approval manager. If another process owns
    the configured port, Agent reserves an OS-assigned loopback port instead of
    attaching its native bridge to that process.
    """

    token = load_or_create_api_token(settings.api_token_path)
    owned = _start_owned_server(settings, allow_ephemeral=True)

    def open_window() -> None:
        origin = _wait_for_owned_service(owned.endpoints, token, owned)
        marker.service_ready()
        _open_agent_window(
            _load_webview(),
            f"{origin}{_AGENT_PATH}",
            owned.user_presence,
            marker.window_created,
        )
        marker.window_closed()

    _run_with_owned_cleanup(owned, open_window)


def run_desktop_agent(settings: AppSettings) -> None:
    """Run the protected Agent with a content-free crash-observable marker."""

    if not sys_platform_is_windows():
        raise DesktopOverlayError(
            "desktop Agent is currently available only on Windows",
            reason_code="unsupported_platform",
        )
    marker = NativeLifecycleMarker(
        settings.native_agent_lifecycle_path,
        NativeWindowKind.AGENT,
    )
    _run_with_lifecycle_marker(marker, lambda: _run_desktop_agent(settings, marker))


def launch_desktop_agent(settings: AppSettings) -> None:
    """Run one protected Agent instance or focus the already-owned window.

    Both supported launch paths use this boundary. A duplicate launch never
    starts another listener, runtime worker, WebView, or lifecycle marker. The
    focus attempt is deliberately best-effort and bounded; failure to focus can
    never become authority to create a fallback instance.
    """

    if not sys_platform_is_windows():
        raise DesktopOverlayError(
            "desktop Agent is currently available only on Windows",
            reason_code="unsupported_platform",
        )
    lease = None
    acquire_failed = False
    try:
        lease = acquire_windows_instance(_AGENT_INSTANCE_NAME)
    except WindowsSingleInstanceError:
        acquire_failed = True
    if acquire_failed:
        raise DesktopOverlayError(
            _FAILURE_MESSAGES["local_state_unavailable"],
            reason_code="local_state_unavailable",
        ) from None
    if lease is None:
        focus_existing_window(_AGENT_WINDOW_TITLE)
        return

    failure: DesktopOverlayError | None = None
    try:
        run_desktop_agent(settings)
    except Exception as error:
        failure = _safe_desktop_failure(error)
    try:
        lease.close()
    except WindowsSingleInstanceError:
        if failure is None:
            failure = DesktopOverlayError(
                _FAILURE_MESSAGES["local_state_unavailable"],
                reason_code="local_state_unavailable",
            )
    if failure is not None:
        raise failure


def _failure_notice(
    reason_code: str,
    components: tuple[RuntimeComponent, ...] = (),
    cleanup_reason_code: str | None = None,
) -> str:
    code = reason_code if reason_code in _FAILURE_MESSAGES else "desktop_failed"
    notice = f"{_FAILURE_MESSAGES[code]}\n\nDiagnostic code: {code}"
    safe_components = tuple(
        component.value for component in components if isinstance(component, RuntimeComponent)
    )
    if safe_components:
        notice += "\nComponents: " + ", ".join(safe_components)
    if cleanup_reason_code in _FAILURE_MESSAGES:
        notice += f"\nCleanup: {cleanup_reason_code}\n{_FAILURE_MESSAGES[cleanup_reason_code]}"
    return notice


def _show_safe_desktop_error(
    reason_code: str = "desktop_failed",
    components: tuple[RuntimeComponent, ...] = (),
    cleanup_reason_code: str | None = None,
) -> None:
    """Show content-free native diagnostics; no exception or settings text."""

    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            _failure_notice(reason_code, components, cleanup_reason_code),
            "Prompt Enhancer",
            0x10,
        )
    except Exception:
        # The GUI entry point intentionally has no console.  If even the native
        # message box is unavailable, fail without rendering exception details.
        return


def _show_safe_agent_error(
    reason_code: str = "desktop_failed",
    components: tuple[RuntimeComponent, ...] = (),
    cleanup_reason_code: str | None = None,
) -> None:
    """Show one content-free native error for the protected Agent launcher."""

    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            _failure_notice(reason_code, components, cleanup_reason_code),
            "Prompt Enhancer",
            0x10,
        )
    except Exception:
        return


def desktop_main() -> int:
    """Console-free Windows entry point for the React/WebView overlay."""

    try:
        run_desktop_overlay(AppSettings.from_env())
    except Exception as error:
        failure = _safe_desktop_failure(error)
        _show_safe_desktop_error(
            failure.reason_code, failure.components, failure.cleanup_reason_code
        )
        return 1
    return 0


def agent_desktop_main() -> int:
    """Console-free Windows entry point for the protected Agent window."""

    try:
        launch_desktop_agent(AppSettings.from_env())
    except Exception as error:
        failure = _safe_desktop_failure(error)
        _show_safe_agent_error(
            failure.reason_code, failure.components, failure.cleanup_reason_code
        )
        return 1
    return 0


def sys_platform_is_windows() -> bool:
    """Small test seam that avoids importing GUI dependencies on other systems."""

    import sys

    return sys.platform == "win32"


__all__ = [
    "DesktopOverlayDependencyError",
    "DesktopOverlayError",
    "DesktopOverlayServiceError",
    "agent_desktop_main",
    "desktop_main",
    "launch_desktop_agent",
    "run_desktop_agent",
    "run_desktop_overlay",
]
