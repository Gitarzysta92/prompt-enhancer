"""Ephemeral redaction preview and one-shot approval boundary.

The store in this module is deliberately process-local.  It has no persistence
port, and its secret-bearing objects hide redacted text from normal
representations.  A caller must explicitly request inspection or atomically
consume an exact approval before it can access the prepared analysis input.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from secrets import token_hex
from threading import Lock
from time import monotonic

from pydantic import Field, SecretStr, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, Provider, SAFE_VERSION_PATTERN, StrictModel
from .text_contracts import P1TextAnalysisInput, TextLanguage, TextMessageKind, TextRole


REDACTION_PREVIEW_TTL = timedelta(minutes=10)
REDACTION_PREVIEW_CONFIRMATION = "approve_exact_redacted_preview"
MAX_ACTIVE_REDACTION_PREVIEWS = 128
MAX_PREVIEW_TOMBSTONES = 512


class AnalysisDestination(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"


class RetentionClass(StrEnum):
    LOCAL_EPHEMERAL = "local_ephemeral"
    REMOTE_ZERO_RETENTION = "remote_zero_retention"
    REMOTE_30_DAY = "remote_30_day"
    REMOTE_PROVIDER_STANDARD = "remote_provider_standard"


class CostEstimateState(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class RedactionPreviewError(RuntimeError):
    """Content-free preview failure safe for an HTTP error mapper."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RedactionPreviewNotFoundError(RedactionPreviewError):
    def __init__(self) -> None:
        super().__init__("redaction_preview_not_found")


class RedactionPreviewExpiredError(RedactionPreviewError):
    def __init__(self) -> None:
        super().__init__("redaction_preview_expired")


class RedactionPreviewConsumedError(RedactionPreviewError):
    def __init__(self) -> None:
        super().__init__("redaction_preview_consumed")


class RedactionPreviewMismatchError(RedactionPreviewError):
    def __init__(self) -> None:
        super().__init__("redaction_preview_binding_mismatch")


class RedactionPreviewCapacityError(RedactionPreviewError):
    def __init__(self) -> None:
        super().__init__("redaction_preview_capacity_reached")


def _safe_version(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a content-free version identifier")
    return value


def _safe_pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a pseudonymous identifier")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("preview timestamps must be UTC")
    return value


class RedactionPreviewBinding(StrictModel):
    """Everything whose change invalidates a user's approval."""

    provider: Provider
    session_id: str
    analysis_window_fingerprint: str
    metric_keys: tuple[str, ...] = Field(min_length=1, max_length=100)
    destination: AnalysisDestination
    exact_model: str
    estimator_plan_version: str
    redactor_version: str
    retention_class: RetentionClass
    message_count: int = Field(ge=1, le=500)
    character_count: int = Field(ge=1, le=500_000)
    cost_state: CostEstimateState
    estimated_cost_microunits: int | None = Field(default=None, ge=0)
    cost_currency: str | None = None

    _safe_ids = field_validator(
        "session_id", "analysis_window_fingerprint"
    )(_safe_pseudonym)
    _safe_versions = field_validator(
        "exact_model", "estimator_plan_version", "redactor_version"
    )(_safe_version)

    @field_validator("metric_keys")
    @classmethod
    def validate_metric_keys(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("metric set cannot contain duplicates")
        return tuple(_safe_version(value) for value in values)

    @field_validator("cost_currency")
    @classmethod
    def validate_currency(cls, value: str | None) -> str | None:
        if value is not None and (len(value) != 3 or not value.isupper()):
            raise ValueError("cost currency must be an uppercase ISO code")
        return value

    @model_validator(mode="after")
    def validate_boundary(self) -> RedactionPreviewBinding:
        if self.destination is AnalysisDestination.LOCAL:
            if self.retention_class is not RetentionClass.LOCAL_EPHEMERAL:
                raise ValueError("local previews require local-ephemeral retention")
            if self.cost_state is not CostEstimateState.NOT_APPLICABLE:
                raise ValueError("local previews have no API-cost estimate")
        elif self.retention_class is RetentionClass.LOCAL_EPHEMERAL:
            raise ValueError("remote previews require a disclosed remote retention class")
        has_cost = self.estimated_cost_microunits is not None
        if self.cost_state is CostEstimateState.KNOWN:
            if not has_cost or self.cost_currency is None:
                raise ValueError("known cost requires an amount and currency")
        elif has_cost or self.cost_currency is not None:
            raise ValueError("unknown or inapplicable cost cannot claim an amount")
        return self


class RedactionPreviewReceipt(StrictModel):
    preview_id: str
    created_at: datetime
    expires_at: datetime
    binding: RedactionPreviewBinding

    _safe_preview_id = field_validator("preview_id")(_safe_pseudonym)
    _utc_timestamps = field_validator("created_at", "expires_at")(_utc)

    @model_validator(mode="after")
    def exact_ttl(self) -> RedactionPreviewReceipt:
        if self.expires_at - self.created_at != REDACTION_PREVIEW_TTL:
            raise ValueError("redaction preview TTL must be exactly ten minutes")
        return self


class RedactionPreviewMessage(StrictModel):
    role: TextRole
    kind: TextMessageKind
    language: TextLanguage
    text: SecretStr = Field(repr=False)


@dataclass(frozen=True, slots=True)
class RedactionPreviewInspection:
    receipt: RedactionPreviewReceipt
    messages: tuple[RedactionPreviewMessage, ...] = field(repr=False)


class AnalysisApproval(StrictModel):
    preview_id: str
    confirmation: str
    idempotency_key: str
    expected_binding: RedactionPreviewBinding

    _safe_preview_id = field_validator("preview_id")(_safe_pseudonym)
    _safe_idempotency_key = field_validator("idempotency_key")(_safe_version)

    @field_validator("confirmation")
    @classmethod
    def exact_confirmation(cls, value: str) -> str:
        if value != REDACTION_PREVIEW_CONFIRMATION:
            raise ValueError("exact redaction-preview confirmation is required")
        return value


@dataclass(frozen=True, slots=True)
class ApprovedRedactedAnalysis:
    receipt: RedactionPreviewReceipt
    idempotency_key: str
    context: P1TextAnalysisInput = field(repr=False)


@dataclass(slots=True)
class _PreviewEntry:
    receipt: RedactionPreviewReceipt
    context: P1TextAnalysisInput = field(repr=False)
    expires_monotonic: float


class InMemoryRedactionPreviewStore:
    """Bounded TTL store with atomic, exact, one-shot consumption."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic_clock: Callable[[], float] = monotonic,
        token_factory: Callable[[], str] = lambda: token_hex(32),
        max_active: int = MAX_ACTIVE_REDACTION_PREVIEWS,
    ) -> None:
        if not 1 <= max_active <= MAX_ACTIVE_REDACTION_PREVIEWS:
            raise ValueError("preview capacity is outside the reviewed bound")
        self._clock = clock
        self._monotonic_clock = monotonic_clock
        self._token_factory = token_factory
        self._max_active = max_active
        self._entries: dict[str, _PreviewEntry] = {}
        self._tombstones: OrderedDict[str, str] = OrderedDict()
        self._lock = Lock()

    def create(
        self,
        context: P1TextAnalysisInput,
        binding: RedactionPreviewBinding,
    ) -> RedactionPreviewReceipt:
        self._validate_context_binding(context, binding)
        with self._lock:
            now = _utc(self._clock())
            monotonic_now = self._monotonic_clock()
            self._expire_locked(now, monotonic_now)
            if len(self._entries) >= self._max_active:
                raise RedactionPreviewCapacityError()
            preview_id = self._token_factory()
            if (
                PSEUDONYM_PATTERN.fullmatch(preview_id) is None
                or preview_id in self._entries
                or preview_id in self._tombstones
            ):
                raise RedactionPreviewError("redaction_preview_token_invalid")
            receipt = RedactionPreviewReceipt(
                preview_id=preview_id,
                created_at=now,
                expires_at=now + REDACTION_PREVIEW_TTL,
                binding=binding,
            )
            self._entries[preview_id] = _PreviewEntry(
                receipt=receipt,
                context=context,
                expires_monotonic=(
                    monotonic_now + REDACTION_PREVIEW_TTL.total_seconds()
                ),
            )
            return receipt

    def inspect(self, preview_id: str) -> RedactionPreviewInspection:
        _safe_pseudonym(preview_id)
        with self._lock:
            entry = self._require_active_locked(
                preview_id,
                _utc(self._clock()),
                self._monotonic_clock(),
            )
            messages = tuple(
                RedactionPreviewMessage(
                    role=message.role,
                    kind=message.kind,
                    language=message.language,
                    text=message.text,
                )
                for message in entry.context.messages
            )
            return RedactionPreviewInspection(entry.receipt, messages)

    def consume(self, approval: AnalysisApproval) -> ApprovedRedactedAnalysis:
        with self._lock:
            entry = self._require_active_locked(
                approval.preview_id,
                _utc(self._clock()),
                self._monotonic_clock(),
            )
            if approval.expected_binding != entry.receipt.binding:
                raise RedactionPreviewMismatchError()
            del self._entries[approval.preview_id]
            self._add_tombstone_locked(approval.preview_id, "consumed")
            return ApprovedRedactedAnalysis(
                receipt=entry.receipt,
                idempotency_key=approval.idempotency_key,
                context=entry.context,
            )

    def discard(self, preview_id: str) -> bool:
        _safe_pseudonym(preview_id)
        with self._lock:
            removed = self._entries.pop(preview_id, None)
            if removed is None:
                return False
            self._add_tombstone_locked(preview_id, "consumed")
            return True

    def purge_expired(self) -> int:
        with self._lock:
            before = len(self._entries)
            self._expire_locked(
                _utc(self._clock()),
                self._monotonic_clock(),
            )
            return before - len(self._entries)

    @staticmethod
    def _validate_context_binding(
        context: P1TextAnalysisInput,
        binding: RedactionPreviewBinding,
    ) -> None:
        character_count = sum(
            len(message.text.get_secret_value()) for message in context.messages
        )
        if (
            binding.provider is not context.provider
            or binding.session_id != context.session_id
            or binding.analysis_window_fingerprint
            != context.analysis_window_fingerprint
            or binding.redactor_version != context.redactor_version
            or binding.message_count != context.observed_message_count
            or binding.character_count != character_count
        ):
            raise RedactionPreviewMismatchError()

    def _require_active_locked(
        self,
        preview_id: str,
        now: datetime,
        monotonic_now: float,
    ) -> _PreviewEntry:
        entry = self._entries.get(preview_id)
        if entry is not None and (
            now >= entry.receipt.expires_at
            or monotonic_now >= entry.expires_monotonic
        ):
            del self._entries[preview_id]
            self._add_tombstone_locked(preview_id, "expired")
            raise RedactionPreviewExpiredError()
        if entry is not None:
            return entry
        tombstone = self._tombstones.get(preview_id)
        if tombstone == "expired":
            raise RedactionPreviewExpiredError()
        if tombstone == "consumed":
            raise RedactionPreviewConsumedError()
        raise RedactionPreviewNotFoundError()

    def _expire_locked(self, now: datetime, monotonic_now: float) -> None:
        expired = tuple(
            preview_id
            for preview_id, entry in self._entries.items()
            if (
                now >= entry.receipt.expires_at
                or monotonic_now >= entry.expires_monotonic
            )
        )
        for preview_id in expired:
            del self._entries[preview_id]
            self._add_tombstone_locked(preview_id, "expired")

    def _add_tombstone_locked(self, preview_id: str, state: str) -> None:
        self._tombstones[preview_id] = state
        self._tombstones.move_to_end(preview_id)
        while len(self._tombstones) > MAX_PREVIEW_TOMBSTONES:
            self._tombstones.popitem(last=False)
