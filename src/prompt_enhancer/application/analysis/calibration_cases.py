"""Exact, ephemeral review cases for human/model calibration comparisons.

Only the case identity is retained in a review receipt. Displayed evidence is
returned over the authorized local interface, never cached in this service.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import secrets
import threading
from typing import Literal

from pydantic import Field, field_validator

from ...domain import PSEUDONYM_PATTERN, Provider, StrictModel
from ..model_reply import model_json_object


CALIBRATION_CASE_VERSION = "calibration-case.v1"
JUDGE_WINDOW_SCHEMA_VERSION = "model-judge-window.v2"
REVIEW_LIFETIME = timedelta(minutes=15)
MAX_REVIEW_RECEIPTS = 128
MAX_REVIEW_CHARACTERS = 15_000


class CalibrationReviewError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CalibrationCaseIdentity(StrictModel):
    session_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    provider: Provider
    case_version: Literal[CALIBRATION_CASE_VERSION] = CALIBRATION_CASE_VERSION
    case_fingerprint: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    window_fingerprint: str = Field(pattern=PSEUDONYM_PATTERN.pattern)

    @field_validator("case_fingerprint", "window_fingerprint")
    @classmethod
    def _known_fingerprint(cls, value: str) -> str:
        if value == "0" * 64:
            raise ValueError("calibration_case_identity_missing")
        return value


class CalibrationCaseRecord(StrictModel):
    sequence: int = Field(ge=0)
    role: Literal["user", "agent", "plan"]
    content: str = Field(min_length=1, max_length=MAX_REVIEW_CHARACTERS, repr=False)

    @field_validator("content")
    @classmethod
    def _nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("calibration_case_empty")
        return value


class _RenderedWindow(StrictModel):
    schema_version: Literal[JUDGE_WINDOW_SCHEMA_VERSION] = Field(alias="schema")
    authority: Literal["untrusted_evidence"]
    available: Literal[True]
    task_anchor_retained: Literal[True]
    earlier_records_omitted: bool
    records: list[CalibrationCaseRecord] = Field(min_length=1, max_length=120, repr=False)


class PreparedCalibrationCase(CalibrationCaseIdentity):
    records: tuple[CalibrationCaseRecord, ...] = Field(min_length=1, max_length=120, repr=False)
    earlier_records_omitted: bool
    window_schema_version: Literal[JUDGE_WINDOW_SCHEMA_VERSION] = JUDGE_WINDOW_SCHEMA_VERSION


class CalibrationReview(PreparedCalibrationCase):
    contract_version: Literal[CALIBRATION_CASE_VERSION] = CALIBRATION_CASE_VERSION
    review_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    expires_at: datetime
    persisted: Literal[False] = False
    local_only: Literal[True] = True
    note: str = (
        "Rate only this bounded redacted evidence. It is the task anchor and recent tail used by the judge, "
        "not the whole transcript. Matching evidence is required for agreement; model opinions are never measurements."
    )


class CalibrationReviewRequest(StrictModel):
    session_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    window_characters: Literal[6_000, 15_000] = 15_000


def prepare_calibration_case(
    *, session_id: str, provider: Provider, window_fingerprint: str, rendered_window: str,
) -> PreparedCalibrationCase:
    """Seal exactly the rendered evidence, not a guess at the latest session."""

    if not isinstance(rendered_window, str) or not rendered_window.lstrip().startswith("{"):
        raise CalibrationReviewError("calibration_window_unavailable")
    data = model_json_object(rendered_window, max_characters=MAX_REVIEW_CHARACTERS)
    if data is None or data.get("available") is not True or data.get("task_anchor_retained") is not True:
        raise CalibrationReviewError("calibration_window_unavailable")
    try:
        window = _RenderedWindow.model_validate(data, strict=True)
        sequences = [record.sequence for record in window.records]
        if window.records[0].role != "user" or sequences != sorted(set(sequences)):
            raise ValueError("calibration_window_unavailable")
        canonical = json.dumps(
            {"case_version": CALIBRATION_CASE_VERSION, "session_id": session_id, "provider": provider.value,
             "window_fingerprint": window_fingerprint, "window": data},
            sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        )
        return PreparedCalibrationCase(
            session_id=session_id, provider=provider, window_fingerprint=window_fingerprint,
            case_fingerprint=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            records=tuple(window.records), earlier_records_omitted=window.earlier_records_omitted,
        )
    except (ValueError, TypeError, AttributeError):
        raise CalibrationReviewError("calibration_window_unavailable") from None


@dataclass(frozen=True)
class _ReviewReceipt:
    identity: CalibrationCaseIdentity
    expires_at: datetime


class CalibrationReviewService:
    """Bounded, memory-only receipts; existing reader opt-in and consent apply."""

    def __init__(
        self,
        *,
        read_case: Callable[[str, int], PreparedCalibrationCase],
        provider_for: Callable[[str], Provider | None],
        has_consent: Callable[[Provider], bool],
        enabled: bool,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._read_case = read_case
        self._provider_for = provider_for
        self._has_consent = has_consent
        self._enabled = enabled
        self._clock = clock
        self._lock = threading.Lock()
        self._receipts: OrderedDict[str, _ReviewReceipt] = OrderedDict()

    def _authorize(self, provider: Provider | None = None) -> None:
        if not self._enabled:
            raise CalibrationReviewError("calibration_review_disabled")
        if provider is not None:
            try:
                allowed = self._has_consent(provider)
            except Exception:
                raise CalibrationReviewError("calibration_review_unavailable") from None
            if allowed is not True:
                raise CalibrationReviewError("calibration_review_consent_required")

    def issue(self, session_id: str, window_characters: int = 15_000) -> CalibrationReview:
        self._authorize()
        if PSEUDONYM_PATTERN.fullmatch(session_id) is None or window_characters not in (6_000, 15_000):
            raise CalibrationReviewError("calibration_window_unavailable")
        try:
            provider = self._provider_for(session_id)
            if not isinstance(provider, Provider):
                raise CalibrationReviewError("calibration_window_unavailable")
            self._authorize(provider)
            case = self._read_case(session_id, window_characters)
        except CalibrationReviewError:
            raise
        except Exception:
            raise CalibrationReviewError("calibration_window_unavailable") from None
        if case.session_id != session_id or case.provider is not provider:
            raise CalibrationReviewError("calibration_window_unavailable")
        self._authorize(case.provider)
        identity = CalibrationCaseIdentity.model_validate(case.model_dump(include=set(CalibrationCaseIdentity.model_fields)))
        now = self._clock()
        receipt = _ReviewReceipt(identity=identity, expires_at=now + REVIEW_LIFETIME)
        with self._lock:
            for expired in [key for key, value in self._receipts.items() if value.expires_at <= now]:
                self._receipts.pop(expired)
            while len(self._receipts) >= MAX_REVIEW_RECEIPTS:
                self._receipts.popitem(last=False)
            review_id = secrets.token_hex(16)
            self._receipts[review_id] = receipt
        return CalibrationReview(**case.model_dump(), review_id=review_id, expires_at=receipt.expires_at)

    def resolve(self, review_id: str, session_id: str) -> CalibrationCaseIdentity:
        self._authorize()
        with self._lock:
            receipt = self._receipts.get(review_id)
        if receipt is None:
            raise CalibrationReviewError("calibration_review_missing")
        if receipt.identity.session_id != session_id:
            raise CalibrationReviewError("calibration_review_mismatch")
        if receipt.expires_at <= self._clock():
            raise CalibrationReviewError("calibration_review_expired")
        self._authorize(receipt.identity.provider)
        return receipt.identity


__all__ = (
    "CALIBRATION_CASE_VERSION", "JUDGE_WINDOW_SCHEMA_VERSION", "MAX_REVIEW_RECEIPTS",
    "REVIEW_LIFETIME", "CalibrationCaseIdentity", "CalibrationCaseRecord",
    "CalibrationReview", "CalibrationReviewError", "CalibrationReviewRequest", "CalibrationReviewService",
    "PreparedCalibrationCase", "prepare_calibration_case",
)
