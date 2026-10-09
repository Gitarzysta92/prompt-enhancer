"""Reviewed egress for inference, independent of workspace execution authority."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, JsonValue

from ..domain import StrictModel
from .inference import InferenceError, InferenceModel, InferenceRegistry, InferenceStream
from .runtime_cancellation import raise_if_runtime_cancelled

MAX_REQUEST_BYTES = 256_000
REVIEW_SECONDS = 600


class InferencePreview(StrictModel):
    model: InferenceModel
    purpose: str = Field(max_length=120)
    request: dict[str, JsonValue] = Field(repr=False)
    approval: str = Field(repr=False)
    redactor_version: str
    expires_in_seconds: int = REVIEW_SECONDS


class PendingInferenceReview(StrictModel):
    id: str
    preview: InferencePreview = Field(repr=False)


class InferenceReviewRequired(Exception):
    def __init__(self, preview: InferencePreview):
        super().__init__("inference_preview_required")
        self.preview = preview


@dataclass(frozen=True)
class InferenceSelection:
    model_id: str
    purpose: str
    approval: str | None = None
    preview: bool = False


_selection: ContextVar[InferenceSelection | None] = ContextVar("inference_selection", default=None)


def current_inference_selection() -> InferenceSelection | None:
    return _selection.get()


@contextmanager
def inference_selection(selection: InferenceSelection) -> Iterator[None]:
    token = _selection.set(selection)
    try:
        yield
    finally:
        _selection.reset(token)


@dataclass
class _Pending:
    scope: str
    review: PendingInferenceReview
    done: threading.Event
    accepted: bool = False


class ReviewedInference:
    def __init__(self, registry: InferenceRegistry, *, redact: Callable[[str], str],
                 redactor_version: str, clock: Callable[[], float] = time.time):
        self.registry = registry
        self._redact = redact
        self.redactor_version = redactor_version
        self._clock = clock
        self._key = secrets.token_bytes(32)
        self._lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}
        self._used: dict[str, float] = {}

    def _prepare(self, model_id: str, body: bytes) -> tuple[InferenceModel, bytes]:
        _, model = self.registry.resolve(model_id)
        if len(body) > MAX_REQUEST_BYTES:
            raise InferenceError("inference_request_too_large")
        try:
            value = json.loads(body)
            if not isinstance(value, dict) or not isinstance(value.get("messages"), list):
                raise ValueError
            def clean(item):
                if isinstance(item, str):
                    return self._redact(item) if model.remote and item else item
                if isinstance(item, list):
                    return [clean(child) for child in item]
                if isinstance(item, dict):
                    return {key: clean(child) for key, child in item.items()}
                return item
            # Protocol identifiers stay stable. All content-bearing message and
            # tool-definition strings are redacted and displayed in the preview.
            if model.remote:
                for message in value["messages"]:
                    if not isinstance(message, dict):
                        raise ValueError
                    for key in ("content", "tool_calls", "function_call"):
                        if key in message:
                            message[key] = clean(message[key])
                if "tools" in value:
                    value["tools"] = clean(value["tools"])
                value.pop("chat_template_kwargs", None)
            value.pop("model", None)
            return model, json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        except Exception:
            raise InferenceError("inference_request_invalid") from None

    def _approval(self, model: InferenceModel, purpose: str, body: bytes, issued: int, nonce: str) -> str:
        bound = json.dumps([model.model_dump(), purpose, self.redactor_version, issued, nonce], sort_keys=True).encode()
        return str(issued) + "." + nonce + "." + hmac.new(self._key, bound + b"\0" + body, hashlib.sha256).hexdigest()

    def preview(self, model_id: str, body: bytes, purpose: str) -> InferencePreview:
        model, prepared = self._prepare(model_id, body)
        issued = int(self._clock())
        return InferencePreview(model=model, purpose=purpose, request=json.loads(prepared),
            approval=self._approval(model, purpose, prepared, issued, secrets.token_hex(8)), redactor_version=self.redactor_version)

    def approved_body(self, model_id: str, body: bytes, purpose: str, approval: str | None) -> bytes:
        model, prepared = self._prepare(model_id, body)
        if not model.remote:
            return prepared
        try:
            timestamp, nonce, _ = (approval or "").split(".")
            issued = int(timestamp)
            valid = 0 <= self._clock() - issued <= REVIEW_SECONDS and hmac.compare_digest(
                approval or "", self._approval(model, purpose, prepared, issued, nonce))
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise InferenceError("inference_preview_required")
        with self._lock:
            now = self._clock()
            self._used = {key: value for key, value in self._used.items() if now - value <= REVIEW_SECONDS}
            if approval in self._used or len(self._used) >= 4096:
                raise InferenceError("inference_preview_required")
            self._used[approval] = now
        return prepared

    def complete(self, model_id: str, body: bytes, purpose: str, *, approval: str | None = None,
                 preview: bool = False) -> tuple[int, bytes, str]:
        if preview:
            raise InferenceReviewRequired(self.preview(model_id, body, purpose))
        prepared = self.approved_body(model_id, body, purpose, approval)
        provider, _ = self.registry.resolve(model_id)
        return provider.complete(model_id, prepared)

    def open_chat(self, model_id: str, body: bytes, purpose: str, approval: str | None = None) -> InferenceStream:
        prepared = self.approved_body(model_id, body, purpose, approval)
        provider, _ = self.registry.resolve(model_id)
        return provider.open_chat(model_id, prepared)

    def wait_for_agent_review(self, scope: str, model_id: str, body: bytes) -> bytes:
        _, model = self.registry.resolve(model_id)
        if not model.remote:
            return body
        preview = self.preview(model_id, body, "agent:" + scope)
        review = PendingInferenceReview(id=secrets.token_hex(24), preview=preview)
        pending = _Pending(scope, review, threading.Event())
        with self._lock:
            if len(self._pending) >= 16:
                raise InferenceError("inference_review_capacity")
            self._pending[review.id] = pending
        deadline = time.monotonic() + REVIEW_SECONDS
        try:
            while not pending.done.wait(.05):
                raise_if_runtime_cancelled()
                if time.monotonic() > deadline:
                    raise InferenceError("inference_review_expired")
            raise_if_runtime_cancelled()
            if not pending.accepted:
                raise InferenceError("inference_review_declined")
            return self.approved_body(model_id, body, preview.purpose, preview.approval)
        finally:
            with self._lock:
                self._pending.pop(review.id, None)

    def pending(self, scope: str) -> tuple[PendingInferenceReview, ...]:
        with self._lock:
            return tuple(item.review for item in self._pending.values() if item.scope == scope and not item.done.is_set())

    def decide(self, scope: str, review_id: str, *, accepted: bool):
        with self._lock:
            pending = self._pending.get(review_id)
            if pending is None or pending.scope != scope or pending.done.is_set():
                raise InferenceError("inference_review_not_found")
            pending.accepted = accepted
            pending.done.set()
