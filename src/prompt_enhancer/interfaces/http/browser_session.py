"""Ephemeral same-origin browser sessions for the integrated local dashboard."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import secrets
from threading import Lock
import time


BROWSER_SESSION_COOKIE = "prompt_enhancer_session"
CSRF_HEADER = "X-Prompt-Enhancer-CSRF"
_MIN_SECRET_LENGTH = 16
_MAX_SECRET_LENGTH = 256


@dataclass(frozen=True, slots=True)
class BrowserSessionGrant:
    cookie_value: str
    csrf_token: str
    expires_in_seconds: int


@dataclass(frozen=True, slots=True)
class _SessionRecord:
    csrf_digests: tuple[bytes, ...]
    expires_at: float


class BrowserSessionManager:
    """Keep random browser and CSRF credentials only in process memory."""

    def __init__(
        self,
        *,
        lifetime_seconds: int = 1_800,
        max_sessions: int = 128,
        max_csrf_tokens_per_session: int = 8,
    ) -> None:
        if lifetime_seconds < 60 or lifetime_seconds > 86_400:
            raise ValueError("browser session lifetime is outside the safe bound")
        if max_sessions < 1 or max_sessions > 1_024:
            raise ValueError("browser session count is outside the safe bound")
        if max_csrf_tokens_per_session < 1 or max_csrf_tokens_per_session > 32:
            raise ValueError("CSRF token count is outside the safe bound")
        self._lifetime_seconds = lifetime_seconds
        self._max_sessions = max_sessions
        self._max_csrf_tokens_per_session = max_csrf_tokens_per_session
        self._records: dict[bytes, _SessionRecord] = {}
        self._lock = Lock()

    @staticmethod
    def _digest(value: str) -> bytes:
        return hashlib.sha256(value.encode("utf-8")).digest()

    @staticmethod
    def _plausible_secret(value: str | None) -> bool:
        return (
            value is not None
            and _MIN_SECRET_LENGTH <= len(value) <= _MAX_SECRET_LENGTH
        )

    def issue(self, existing_cookie: str | None = None) -> BrowserSessionGrant:
        """Issue a tab CSRF token while preserving a valid shared browser cookie."""

        csrf_token = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            cookie_value = existing_cookie or ""
            cookie_digest = (
                self._digest(cookie_value)
                if self._plausible_secret(cookie_value)
                else b""
            )
            record = self._records.get(cookie_digest)
            csrf_digest = self._digest(csrf_token)
            if record is not None and record.expires_at > now:
                csrf_digests = (*record.csrf_digests, csrf_digest)[
                    -self._max_csrf_tokens_per_session :
                ]
            else:
                cookie_value = secrets.token_urlsafe(32)
                cookie_digest = self._digest(cookie_value)
                if len(self._records) >= self._max_sessions:
                    oldest = min(
                        self._records,
                        key=lambda key: self._records[key].expires_at,
                    )
                    del self._records[oldest]
                csrf_digests = (csrf_digest,)
            self._records[cookie_digest] = _SessionRecord(
                csrf_digests=csrf_digests,
                expires_at=now + self._lifetime_seconds,
            )
        return BrowserSessionGrant(
            cookie_value=cookie_value,
            csrf_token=csrf_token,
            expires_in_seconds=self._lifetime_seconds,
        )

    def authenticate(self, cookie_value: str | None) -> bool:
        if not self._plausible_secret(cookie_value):
            return False
        now = time.monotonic()
        with self._lock:
            record = self._records.get(self._digest(cookie_value))
            if record is None or record.expires_at <= now:
                return False
            return True

    def verify_csrf(self, cookie_value: str | None, candidate: str | None) -> bool:
        if not (
            self._plausible_secret(cookie_value)
            and self._plausible_secret(candidate)
        ):
            return False
        now = time.monotonic()
        with self._lock:
            record = self._records.get(self._digest(cookie_value))
            if record is None or record.expires_at <= now:
                return False
            candidate_digest = self._digest(candidate)
            return any(
                hmac.compare_digest(expected, candidate_digest)
                for expected in record.csrf_digests
            )

    def _prune(self, now: float) -> None:
        expired = [
            key
            for key, value in self._records.items()
            if value.expires_at <= now
        ]
        for key in expired:
            del self._records[key]
