"""Content-free, one-shot native user-presence approvals.

The same-origin browser session is only a CSRF boundary.  This module adds a
separate in-process capability that the desktop host may issue after a native
confirmation dialog.  Records retain only a keyed request fingerprint and a
monotonic expiry; request bodies, paths, identifiers, and tokens are never
persisted or logged.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import re
import secrets
from threading import Lock
import time


USER_PRESENCE_HEADER = "X-Prompt-Enhancer-User-Presence"
USER_PRESENCE_VERSION = "native-user-presence-v1"
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_TOKEN_MIN = 32
_TOKEN_MAX = 128
_SAFE_ACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"^/v1/sessions/[a-f0-9]{64}/declared-task-profile$"),
        "Save declared metric denominators for future analysis",
    ),
    (
        re.compile(
            r"^/v1/sessions/[a-f0-9]{64}/metric-lifecycle-evidence/"
            r"proposals/[a-f0-9]{64}/decision$"
        ),
        "Confirm or reject one metric-evidence proposal",
    ),
    (
        re.compile(
            r"^/v1/sessions/[a-f0-9]{64}/requirement-plan-evidence/"
            r"proposals/[a-f0-9]{64}/review$"
        ),
        "Open exact local clauses for one requirement-plan review",
    ),
    (
        re.compile(
            r"^/v1/sessions/[a-f0-9]{64}/requirement-plan-evidence/"
            r"proposals/[a-f0-9]{64}/decision$"
        ),
        (
            "Confirm or reject one reviewed active-requirement "
            "classification and plan-link proposal"
        ),
    ),
    (
        re.compile(
            r"^/v1/sessions/[a-f0-9]{64}/requirement-action-evidence/"
            r"proposals/[a-f0-9]{64}/review$"
        ),
        (
            "Open exact local requirements plus redacted action invocation "
            "and effect details for one review"
        ),
    ),
    (
        re.compile(
            r"^/v1/sessions/[a-f0-9]{64}/requirement-action-evidence/"
            r"proposals/[a-f0-9]{64}/decision$"
        ),
        "Confirm or reject one reviewed requirement-to-action link proposal",
    ),
    (
        re.compile(
            r"^/v1/sessions/[a-f0-9]{64}/"
            r"requirement-verification-evidence/acceptances$"
        ),
        "Record one explicit native requirement acceptance outcome",
    ),
    (
        re.compile(
            r"^/v1/agent/sessions/[a-f0-9]{32,64}/approvals/"
            r"[a-f0-9]{32,64}$"
        ),
        "Decide one pending local-agent tool action",
    ),
    (
        re.compile(
            r"^/v1/agent/sessions/[a-f0-9]{32}/changes/restores/"
            r"[a-f0-9]{32}/apply$"
        ),
        "Restore one reviewed workspace path to its retained session baseline",
    ),
    (
        re.compile(
            r"^/v1/agent/sessions/[a-f0-9]{32,64}/workspace/previews/"
            r"[a-f0-9]{32,64}/apply$"
        ),
        "Apply one previously reviewed workspace edit",
    ),
    (
        re.compile(r"^/v1/agent/sessions/[a-f0-9]{32}/authority$"),
        "Revalidate protected capabilities for one recovered Agent chat",
    ),
    (
        re.compile(
            r"^/v1/agent/sessions/[a-f0-9]{32}/workspace/creates/"
            r"[a-f0-9]{32}/apply$"
        ),
        "Create one previously reviewed workspace file",
    ),
    (
        re.compile(
            r"^/v1/agent/sessions/[a-f0-9]{32}/workspace/directories/"
            r"[a-f0-9]{32}/apply$"
        ),
        "Create one previously reviewed workspace folder",
    ),
    (
        re.compile(
            r"^/v1/agent/sessions/[a-f0-9]{32}/workspace/directory-moves/"
            r"[a-f0-9]{32}/apply$"
        ),
        "Apply one previously reviewed workspace folder move",
    ),
    (
        re.compile(
            r"^/v1/agent/sessions/[a-f0-9]{32}/workspace/file-trash/"
            r"[a-f0-9]{32}/apply$"
        ),
        "Move one previously reviewed workspace file to the Recycle Bin",
    ),
    (
        re.compile(
            r"^/v1/agent/sessions/[a-f0-9]{32}/workspace/moves/"
            r"[a-f0-9]{32}/apply$"
        ),
        "Apply one previously reviewed workspace file move",
    ),
    (
        re.compile(
            r"^/v1/agent/sessions/[a-f0-9]{32}/workspace/transactions/"
            r"[a-f0-9]{32}/apply$"
        ),
        "Apply one previously reviewed multi-file workspace transaction",
    ),
    (
        re.compile(
            r"^/v1/agent/projects/[a-f0-9]{32}/sessions/"
            r"[a-f0-9]{32}/artifacts$"
        ),
        "Capture one exact reviewed workspace file as a chat artifact",
    ),
    (
        re.compile(
            r"^/v1/agent/projects/[a-f0-9]{32}/sessions/"
            r"[a-f0-9]{32}/artifacts/[a-f0-9]{32}/remove$"
        ),
        "Move one archived artifact record to the recoverable Removed view without deleting its workspace file",
    ),
    (
        re.compile(r"^/v1/integrations/agent-mcp/connections$"),
        "Create one scoped external Agent connection and reveal its credential once",
    ),
    (
        re.compile(
            r"^/v1/integrations/agent-mcp/connections/[a-f0-9]{32}/rotate$"
        ),
        "Rotate one external Agent connection and reveal its replacement credential once",
    ),
    (
        re.compile(
            r"^/v1/integrations/agent-mcp/connections/[a-f0-9]{32}/revoke$"
        ),
        "Revoke one external Agent connection",
    ),
    (
        re.compile(r"^/v1/integrations/mcp-store/managed$"),
        "Save one reviewed MCP setup plan without installing or starting it",
    ),
    (
        re.compile(
            r"^/v1/integrations/mcp-store/managed/[a-f0-9]{32}/probe$"
        ),
        "Briefly connect one exact reviewed MCP endpoint, inspect bounded tool schemas, then close it without calling tools",
    ),
    (
        re.compile(
            r"^/v1/integrations/mcp-store/managed/[a-f0-9]{32}/install$"
        ),
        "Activate one exact reviewed remote MCP plan without starting a persistent host or granting tool authority",
    ),
    (
        re.compile(
            r"^/v1/integrations/mcp-store/managed/[a-f0-9]{32}/uninstall$"
        ),
        "Remove one remote MCP activation without deleting its reviewed plan or compatibility receipt",
    ),
    (
        re.compile(
            r"^/v1/integrations/mcp-store/managed/[a-f0-9]{32}/"
            r"projects/[a-f0-9]{32}$"
        ),
        "Change one project's future MCP permission plan; no tool becomes active",
    ),
    (
        re.compile(
            r"^/v1/integrations/mcp-store/managed/[a-f0-9]{32}/"
            r"secrets/[a-f0-9]{32}$"
        ),
        "Store one MCP credential in the operating-system vault",
    ),
    (
        re.compile(
            r"^/v1/integrations/mcp-store/managed/[a-f0-9]{32}/"
            r"secrets/[a-f0-9]{32}/remove$"
        ),
        "Remove one MCP credential from the operating-system vault",
    ),
)


@dataclass(frozen=True, slots=True)
class _Approval:
    request_fingerprint: bytes
    expires_at: float


class UserPresenceApprovalManager:
    """Bounded one-shot approvals shared only by an owned server and window."""

    def __init__(
        self,
        *,
        lifetime_seconds: int = 90,
        max_approvals: int = 64,
    ) -> None:
        if not 10 <= lifetime_seconds <= 300:
            raise ValueError("user-presence lifetime is outside the safe bound")
        if not 1 <= max_approvals <= 256:
            raise ValueError("user-presence approval count is outside the safe bound")
        self._lifetime_seconds = lifetime_seconds
        self._max_approvals = max_approvals
        self._approvals: dict[bytes, _Approval] = {}
        self._lock = Lock()

    @staticmethod
    def _token_digest(token: str) -> bytes:
        return hashlib.sha256(token.encode("utf-8")).digest()

    @staticmethod
    def _request_fingerprint(method: str, path: str, body_sha256: str) -> bytes:
        return hashlib.sha256(
            b"prompt-enhancer/native-user-presence/v1\0"
            + method.encode("ascii")
            + b"\0"
            + path.encode("ascii")
            + b"\0"
            + body_sha256.encode("ascii")
        ).digest()

    @staticmethod
    def action_label(method: str, path: str) -> str | None:
        if method != "POST" or not path.isascii() or len(path) > 256:
            return None
        for pattern, label in _SAFE_ACTIONS:
            if pattern.fullmatch(path) is not None:
                return label
        return None

    def issue(self, *, method: str, path: str, body_sha256: str) -> str:
        """Issue a capability only for one reviewed closed action shape."""

        if self.action_label(method, path) is None or _DIGEST.fullmatch(body_sha256) is None:
            raise ValueError("user-presence request is outside the reviewed contract")
        token = secrets.token_urlsafe(32)
        token_digest = self._token_digest(token)
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            if len(self._approvals) >= self._max_approvals:
                oldest = min(
                    self._approvals,
                    key=lambda key: self._approvals[key].expires_at,
                )
                del self._approvals[oldest]
            self._approvals[token_digest] = _Approval(
                request_fingerprint=self._request_fingerprint(
                    method, path, body_sha256
                ),
                expires_at=now + self._lifetime_seconds,
            )
        return token

    def consume(
        self,
        *,
        token: str | None,
        method: str,
        path: str,
        body: bytes,
    ) -> bool:
        """Consume exactly once; mismatches also burn a presented live token."""

        if (
            token is None
            or not _TOKEN_MIN <= len(token) <= _TOKEN_MAX
            or not token.isascii()
            or self.action_label(method, path) is None
        ):
            return False
        body_sha256 = hashlib.sha256(body).hexdigest()
        expected_request = self._request_fingerprint(method, path, body_sha256)
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            approval = self._approvals.pop(self._token_digest(token), None)
        return (
            approval is not None
            and approval.expires_at > now
            and hmac.compare_digest(
                approval.request_fingerprint,
                expected_request,
            )
        )

    def _prune(self, now: float) -> None:
        for key in tuple(self._approvals):
            if self._approvals[key].expires_at <= now:
                del self._approvals[key]


__all__ = [
    "USER_PRESENCE_HEADER",
    "USER_PRESENCE_VERSION",
    "UserPresenceApprovalManager",
]
