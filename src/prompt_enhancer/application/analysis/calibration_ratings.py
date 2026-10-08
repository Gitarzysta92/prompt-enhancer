"""Blind human ratings of the owner's own sessions, for calibration.

A person reviews the same bounded redacted case that a model judge sees and
rates a few rubric questions on a closed ordinal scale, or abstains. Model
labels are not shown alongside the person's choices. Receipt-bound ratings
can be compared only with judgments of that exact case; a receipt does not
verify the rater's identity, independence, or task success, and does not
promote a model score to an objective measurement. Historical unbound labels
remain readable but do not enter current agreement. Persistent rows contain
pseudonyms, labels, timestamps, versions and case fingerprints, not evidence
text. This derived metadata is sensitive, not anonymous.

Sampling is deterministic and provider-stratified. An underfilled sample may
be redrawn until the first stored rating, after which its membership is
frozen. The rater is known only by a pseudonym derived from a label the
person types; the label itself is not stored.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
from typing import Literal, Protocol

from pydantic import Field, field_validator

from ...domain import PSEUDONYM_PATTERN, Provider, StrictModel
from .calibration_cases import CalibrationCaseIdentity, CalibrationReview, CalibrationReviewError, CalibrationReviewService


CALIBRATION_CONTRACT_VERSION = "calibration-ratings.v1"
CALIBRATION_SAMPLE_VERSION = "calibration-sample-v1"
LEGACY_CALIBRATION_RATING_VERSION = "calibration-rating-v1"
CALIBRATION_RATING_VERSION = "calibration-rating-v2-reviewed-case"
DEFAULT_SAMPLE_SIZE = 96
MAX_SAMPLE_SIZE = 1000
MAX_CANDIDATE_SESSIONS = 5_000
RATER_NAMESPACE = "calibration:rater"

#: The three rubric metrics a person rates blind in the first wave.  They are
#: the ones the P1 profile emits for every session and whose wording a reader
#: can judge from the transcript alone.
CALIBRATION_METRIC_KEYS: tuple[str, ...] = (
    "prompt.task_definition_coverage",
    "prompt.context_sufficiency",
    "outcome.verification_strategy_adequacy",
)


class RatingLabel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CANNOT_JUDGE = "cannot_judge"


class CalibrationSampleMember(StrictModel):
    position: int = Field(ge=0)
    session_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    provider: Provider
    project_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    project_display_name: str | None = Field(default=None, max_length=120)
    session_display_name: str | None = Field(default=None, max_length=160)
    started_at: datetime | None = None
    rated_metric_keys: tuple[str, ...] = ()


class CalibrationSample(StrictModel):
    contract_version: Literal[CALIBRATION_CONTRACT_VERSION] = CALIBRATION_CONTRACT_VERSION
    sample_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    sample_version: str
    created_at: datetime
    target_size: int = Field(ge=1, le=MAX_SAMPLE_SIZE)
    metric_keys: tuple[str, ...] = CALIBRATION_METRIC_KEYS
    members: tuple[CalibrationSampleMember, ...]


class CalibrationRating(StrictModel):
    rater_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    session_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    metric_key: str = Field(min_length=1, max_length=120)
    label: RatingLabel
    rated_at: datetime
    revision: int = Field(ge=1)
    rating_version: str = Field(default=LEGACY_CALIBRATION_RATING_VERSION, min_length=1, max_length=64)
    case_fingerprint: str | None = Field(default=None, pattern=PSEUDONYM_PATTERN.pattern)
    case_version: str | None = Field(default=None, min_length=1, max_length=64)
    window_fingerprint: str | None = Field(default=None, pattern=PSEUDONYM_PATTERN.pattern)


class RatingSubmission(StrictModel):
    rater_label: str = Field(min_length=1, max_length=80)
    session_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    ratings: dict[str, RatingLabel] = Field(min_length=1, max_length=len(CALIBRATION_METRIC_KEYS))
    review_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")

    @field_validator("ratings")
    @classmethod
    def only_calibration_metrics(cls, value: dict[str, RatingLabel]) -> dict[str, RatingLabel]:
        unknown = set(value) - set(CALIBRATION_METRIC_KEYS)
        if unknown:
            raise ValueError("ratings name a metric outside the calibration set")
        return value

    @field_validator("rater_label")
    @classmethod
    def printable_label(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped or any(ord(ch) < 32 or ord(ch) == 127 for ch in stripped):
            raise ValueError("rater label must be printable")
        return stripped


class MetricRatingCount(StrictModel):
    metric_key: str
    rated_sessions: int = Field(ge=0)
    low: int = Field(ge=0)
    medium: int = Field(ge=0)
    high: int = Field(ge=0)
    cannot_judge: int = Field(ge=0)


class CalibrationProgress(StrictModel):
    contract_version: Literal[CALIBRATION_CONTRACT_VERSION] = CALIBRATION_CONTRACT_VERSION
    sample_id: str | None = None
    sample_size: int = Field(ge=0)
    rated_sessions: int = Field(ge=0)
    rater_count: int = Field(ge=0)
    metrics: tuple[MetricRatingCount, ...]


class CalibrationExportRow(StrictModel):
    rater_id: str
    session_id: str
    provider: Provider
    metric_key: str
    label: RatingLabel
    rated_at: datetime
    revision: int
    rating_version: str
    case_fingerprint: str | None = None
    case_version: str | None = None
    window_fingerprint: str | None = None


class CalibrationExport(StrictModel):
    """Sensitive derived metadata with case provenance; no evidence text."""

    contract_version: Literal[CALIBRATION_CONTRACT_VERSION] = CALIBRATION_CONTRACT_VERSION
    sample_id: str | None
    sample_version: str
    rating_version: str
    exported_at: datetime
    rows: tuple[CalibrationExportRow, ...]


class CalibrationRatingRepository(Protocol):
    def get_sample(self) -> CalibrationSample | None: ...

    def create_sample(self, sample: CalibrationSample) -> None: ...

    def replace_sample(self, sample: CalibrationSample) -> None: ...

    def upsert_rating(
        self,
        *,
        rater_id: str,
        session_id: str,
        metric_key: str,
        label: RatingLabel,
        rated_at: datetime,
    ) -> CalibrationRating: ...

    def upsert_ratings(
        self, *, rater_id: str, session_id: str, labels: dict[str, RatingLabel],
        rated_at: datetime, case: CalibrationCaseIdentity | None = None,
    ) -> tuple[CalibrationRating, ...]: ...

    def list_ratings(
        self, *, rater_id: str | None = None, session_id: str | None = None
    ) -> tuple[CalibrationRating, ...]: ...


class SessionCatalogReader(Protocol):
    def list_sessions(self, *, limit: int, offset: int) -> list[dict[str, object]]: ...


class Pseudonymizing(Protocol):
    def pseudonymize(self, namespace: str, value: str) -> str: ...


class CalibrationSampleEmptyError(RuntimeError):
    """No indexed session exists yet, so no sample can be frozen."""


class CalibrationSessionNotSampledError(ValueError):
    """The rated session is not a member of the frozen sample."""


def _stable_order_key(sample_version: str, session_id: str) -> str:
    return hashlib.sha256(f"{sample_version}|{session_id}".encode("utf-8")).hexdigest()


def stratified_selection(
    candidates: Iterable[dict[str, object]],
    *,
    size: int,
    sample_version: str = CALIBRATION_SAMPLE_VERSION,
) -> list[dict[str, object]]:
    """Deterministic, provider-stratified selection (round robin by provider).

    Within a provider the order is a stable hash of the session pseudonym, so
    the choice is pseudo-random but identical on every machine and run.
    """

    by_provider: dict[str, list[dict[str, object]]] = {}
    for row in candidates:
        provider = str(row.get("provider", ""))
        by_provider.setdefault(provider, []).append(row)
    for rows in by_provider.values():
        rows.sort(key=lambda row: _stable_order_key(sample_version, str(row["session_id"])))
    selected: list[dict[str, object]] = []
    providers = sorted(by_provider)
    cursors = {provider: 0 for provider in providers}
    while len(selected) < size:
        progressed = False
        for provider in providers:
            rows = by_provider[provider]
            cursor = cursors[provider]
            if cursor < len(rows):
                selected.append(rows[cursor])
                cursors[provider] = cursor + 1
                progressed = True
                if len(selected) >= size:
                    break
        if not progressed:
            break
    return selected


class CalibrationRatingService:
    def __init__(
        self,
        catalog: SessionCatalogReader,
        repository: CalibrationRatingRepository,
        pseudonymizer: Pseudonymizing,
        *,
        sample_size: int = DEFAULT_SAMPLE_SIZE,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        reviews: CalibrationReviewService | None = None,
    ) -> None:
        self._catalog = catalog
        self._repository = repository
        self._pseudonymizer = pseudonymizer
        self._sample_size = max(1, min(int(sample_size), MAX_SAMPLE_SIZE))
        self._clock = clock
        self._reviews = reviews

    def rater_id(self, rater_label: str) -> str:
        return self._pseudonymizer.pseudonymize(RATER_NAMESPACE, rater_label.strip())

    def _candidates(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        offset = 0
        while len(rows) < MAX_CANDIDATE_SESSIONS:
            page = self._catalog.list_sessions(limit=500, offset=offset)
            rows.extend(page)
            offset += len(page)
            if len(page) < 500:
                break
        return rows

    def sample(self, *, rater_label: str | None = None) -> CalibrationSample:
        """The frozen sample, created on first call.

        It is re-drawn only while it is under-filled *and* nothing has been
        rated yet - for example when it was first drawn before a second
        provider was loaded.  Once a rating exists the sample never changes,
        so ratings stay comparable across sittings.
        """

        existing = self._repository.get_sample()
        redraw = (
            existing is not None
            and len(existing.members) < existing.target_size
            and not self._repository.list_ratings()
        )
        if existing is None or redraw:
            candidates = self._candidates()
            if not candidates:
                raise CalibrationSampleEmptyError("no indexed session to sample")
            chosen = stratified_selection(candidates, size=self._sample_size)
            if redraw and existing is not None and [str(row["session_id"]) for row in chosen] == [m.session_id for m in existing.members]:
                chosen = []  # nothing new to draw; keep the existing sample
            created_at = self._clock()
            sample_id = hashlib.sha256(
                "|".join([CALIBRATION_SAMPLE_VERSION, *(str(row["session_id"]) for row in chosen)]).encode("utf-8")
            ).hexdigest()
            existing_members = tuple(
                CalibrationSampleMember(
                    position=position,
                    session_id=str(row["session_id"]),
                    provider=Provider(str(row["provider"])),
                    project_id=str(row["project_id"]),
                    project_display_name=_label(row.get("project_display_name")),
                    session_display_name=_label(row.get("session_display_name")),
                    started_at=_timestamp(row.get("started_at")),
                )
                for position, row in enumerate(chosen)
            )
            if chosen:
                existing = CalibrationSample(
                    sample_id=sample_id,
                    sample_version=CALIBRATION_SAMPLE_VERSION,
                    created_at=created_at,
                    target_size=self._sample_size,
                    members=existing_members,
                )
                if redraw:
                    self._repository.replace_sample(existing)
                else:
                    self._repository.create_sample(existing)
        assert existing is not None
        if rater_label is None:
            return existing
        rated = self._repository.list_ratings(rater_id=self.rater_id(rater_label))
        by_session: dict[str, set[str]] = {}
        for rating in rated:
            by_session.setdefault(rating.session_id, set()).add(rating.metric_key)
        return existing.model_copy(
            update={
                "members": tuple(
                    member.model_copy(update={"rated_metric_keys": tuple(sorted(by_session.get(member.session_id, ())))})
                    for member in existing.members
                )
            }
        )

    def review(self, session_id: str, window_characters: int = 15_000) -> CalibrationReview:
        if self._reviews is None:
            raise CalibrationReviewError("calibration_review_disabled")
        sample = self.sample()
        if session_id not in {member.session_id for member in sample.members}:
            raise CalibrationSessionNotSampledError("session is not part of the calibration sample")
        return self._reviews.issue(session_id, window_characters)

    def rate(self, submission: RatingSubmission) -> CalibrationProgress:
        sample = self.sample()
        if submission.session_id not in {member.session_id for member in sample.members}:
            raise CalibrationSessionNotSampledError("session is not part of the calibration sample")
        rater_id = self.rater_id(submission.rater_label)
        now = self._clock()
        case = None
        if submission.review_id is not None:
            if self._reviews is None:
                raise CalibrationReviewError("calibration_review_disabled")
            case = self._reviews.resolve(submission.review_id, submission.session_id)
        # Older callers may still submit labels, but absence of a review receipt
        # stays explicitly unbound and can never qualify for current agreement.
        self._repository.upsert_ratings(
            rater_id=rater_id, session_id=submission.session_id,
            labels=submission.ratings, rated_at=now, case=case,
        )
        return self.progress()

    def ratings_for(self, rater_label: str) -> tuple[CalibrationRating, ...]:
        return self._repository.list_ratings(rater_id=self.rater_id(rater_label))

    def progress(self) -> CalibrationProgress:
        sample = self._repository.get_sample()
        ratings = self._repository.list_ratings()
        metrics: list[MetricRatingCount] = []
        for metric_key in CALIBRATION_METRIC_KEYS:
            rows = [rating for rating in ratings if rating.metric_key == metric_key]
            metrics.append(
                MetricRatingCount(
                    metric_key=metric_key,
                    rated_sessions=len({rating.session_id for rating in rows}),
                    low=sum(1 for rating in rows if rating.label is RatingLabel.LOW),
                    medium=sum(1 for rating in rows if rating.label is RatingLabel.MEDIUM),
                    high=sum(1 for rating in rows if rating.label is RatingLabel.HIGH),
                    cannot_judge=sum(1 for rating in rows if rating.label is RatingLabel.CANNOT_JUDGE),
                )
            )
        return CalibrationProgress(
            sample_id=None if sample is None else sample.sample_id,
            sample_size=0 if sample is None else len(sample.members),
            rated_sessions=len({rating.session_id for rating in ratings}),
            rater_count=len({rating.rater_id for rating in ratings}),
            metrics=tuple(metrics),
        )

    def export(self) -> CalibrationExport:
        sample = self._repository.get_sample()
        providers = {} if sample is None else {member.session_id: member.provider for member in sample.members}
        rows = tuple(
            CalibrationExportRow(
                rater_id=rating.rater_id,
                session_id=rating.session_id,
                provider=providers.get(rating.session_id, Provider.SYNTHETIC),
                metric_key=rating.metric_key,
                label=rating.label,
                rated_at=rating.rated_at,
                revision=rating.revision,
                rating_version=rating.rating_version,
                case_fingerprint=rating.case_fingerprint,
                case_version=rating.case_version,
                window_fingerprint=rating.window_fingerprint,
            )
            for rating in self._repository.list_ratings()
        )
        return CalibrationExport(
            sample_id=None if sample is None else sample.sample_id,
            sample_version=CALIBRATION_SAMPLE_VERSION,
            rating_version=CALIBRATION_RATING_VERSION,
            exported_at=self._clock(),
            rows=rows,
        )


def _label(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()[:160]
    return None


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


__all__ = (
    "CALIBRATION_CONTRACT_VERSION",
    "CALIBRATION_METRIC_KEYS",
    "CALIBRATION_RATING_VERSION",
    "LEGACY_CALIBRATION_RATING_VERSION",
    "CALIBRATION_SAMPLE_VERSION",
    "CalibrationExport",
    "CalibrationExportRow",
    "CalibrationProgress",
    "CalibrationRating",
    "CalibrationRatingRepository",
    "CalibrationRatingService",
    "CalibrationSample",
    "CalibrationSampleEmptyError",
    "CalibrationSampleMember",
    "CalibrationSessionNotSampledError",
    "DEFAULT_SAMPLE_SIZE",
    "MetricRatingCount",
    "RatingLabel",
    "RatingSubmission",
    "stratified_selection",
)
