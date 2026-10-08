"""Internal cohort arithmetic with suppression and fixed buckets.

This helper is not a public disclosure mechanism. The control-plane service
fails every aggregate request closed because these local rules do not prevent
cross-team or longitudinal differencing. An unsuppressed value from this module
must not be released until stable cohorts, overlap rules, and an atomic query
budget have a separately reviewed implementation.

Three rules do the work here.

1. **Fixed buckets only.** An aggregate is computed for one canonical reporting
   bucket, never for a caller-chosen interval. Arbitrary windows let an
   observer difference two overlapping requests to isolate one person, and no
   threshold defends against that.
2. **A suppressed result publishes no counts.** Not the value, number of
   contributors, number eligible, or cohort size: "one person reported" is
   itself the disclosure. Suppressed measurements report ``None`` for all.
3. **Missingness is reported, never filled.** A published measurement carries
   how many of the cohort contributed a known value, so silence is visible
   instead of averaged away.

The minimum cohort size is a blunt disclosure control, not an anonymity proof.
It does not defend against an observer who watches the same cohort across many
buckets as membership changes, and it is not a substitute for the governance
review that team sharing still requires.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, StrictModel
from .contracts import VisibilityScope
from .envelopes import MeasurementUnit, SNAPSHOT_METRIC_UNITS, SnapshotMetricKey
from .periods import ReportingBucket
from .sync import SnapshotRecord


MINIMUM_COHORT_SIZE = 5

AGGREGATE_VISIBILITY_SCOPES = frozenset(
    {VisibilityScope.TEAM, VisibilityScope.ORGANIZATION}
)


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("aggregate identifiers must be HMAC pseudonyms")
    return value


class SuppressionReason(StrEnum):
    COHORT_TOO_SMALL = "cohort_too_small"
    MEASUREMENT_COHORT_TOO_SMALL = "measurement_cohort_too_small"
    PRIVACY_DELETION = "privacy_deletion"
    DISCLOSURE_CONTROL_UNAVAILABLE = "disclosure_control_unavailable"


class AggregateMeasurement(StrictModel):
    """One cohort total, or an explicit refusal to publish one.

    When ``suppressed`` is set, ``value`` and ``contributing_subjects`` are both
    ``None``. Reporting an exact contributor count for a suppressed measurement
    would defeat the suppression it is paired with.
    """

    key: SnapshotMetricKey
    unit: MeasurementUnit
    value: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    contributing_subjects: int | None = Field(default=None, ge=0)
    eligible_subjects: int | None = Field(default=None, ge=0)
    suppressed: bool = False
    suppression_reason: SuppressionReason | None = None

    @model_validator(mode="after")
    def coherent_measurement(self) -> AggregateMeasurement:
        if self.unit is not SNAPSHOT_METRIC_UNITS[self.key]:
            raise ValueError("aggregate unit must match the allowlisted unit")
        if self.suppressed != (self.suppression_reason is not None):
            raise ValueError("suppression requires exactly one reason")
        if self.suppressed:
            if (
                self.value is not None
                or self.contributing_subjects is not None
                or self.eligible_subjects is not None
            ):
                raise ValueError("a suppressed measurement publishes no counts")
            return self
        if (
            self.contributing_subjects is None
            or self.eligible_subjects is None
            or self.value is None
        ):
            raise ValueError("a published measurement reports value and cohort")
        if self.contributing_subjects > self.eligible_subjects:
            raise ValueError("contributors cannot exceed eligible subjects")
        return self

    @property
    def missing_subjects(self) -> int | None:
        if self.contributing_subjects is None or self.eligible_subjects is None:
            return None
        return self.eligible_subjects - self.contributing_subjects

    @property
    def coverage(self) -> float | None:
        if (
            self.contributing_subjects is None
            or self.eligible_subjects is None
            or self.eligible_subjects == 0
        ):
            return None
        return self.contributing_subjects / self.eligible_subjects


class TeamAggregate(StrictModel):
    """A cohort result that is explicit about what it does not contain.

    ``cohort_size`` is ``None`` whenever the aggregate is suppressed. Publishing
    "this cohort had one contributor" tells an observer exactly what the
    threshold exists to hide.
    """

    organization_id: str
    team_id: str
    period: ReportingBucket
    minimum_cohort_size: int = Field(ge=1)
    cohort_size: int | None = Field(default=None, ge=0)
    eligible_subjects: int | None = Field(default=None, ge=0)
    suppressed: bool
    suppression_reason: SuppressionReason | None = None
    measurements: tuple[AggregateMeasurement, ...] = ()

    _identifiers = field_validator("organization_id", "team_id")(_pseudonym)

    @model_validator(mode="after")
    def coherent_aggregate(self) -> TeamAggregate:
        if self.suppressed != (self.suppression_reason is not None):
            raise ValueError("suppression requires exactly one reason")
        if self.suppressed:
            if (
                self.measurements
                or self.cohort_size is not None
                or self.eligible_subjects is not None
            ):
                raise ValueError("a suppressed aggregate publishes nothing")
            return self
        if self.cohort_size is None or self.eligible_subjects is None:
            raise ValueError("a published aggregate reports its cohort size")
        if self.cohort_size > self.eligible_subjects:
            raise ValueError("cohort size cannot exceed eligible subjects")
        return self


def _latest_per_subject(
    records: tuple[SnapshotRecord, ...],
) -> tuple[SnapshotRecord, ...]:
    """Keep one snapshot per subject so a resend cannot double-count them.

    Ties on ``issued_at`` resolve by envelope identifier purely so the result is
    deterministic; it is not a claim that either snapshot is more correct.
    """

    newest: dict[str, SnapshotRecord] = {}
    for record in records:
        current = newest.get(record.subject_user_id)
        if current is None:
            newest[record.subject_user_id] = record
            continue
        candidate_key = (record.envelope.issued_at, record.envelope.envelope_id)
        current_key = (current.envelope.issued_at, current.envelope.envelope_id)
        if candidate_key > current_key:
            newest[record.subject_user_id] = record
    return tuple(newest[key] for key in sorted(newest))


def _suppressed(
    *,
    organization_id: str,
    team_id: str,
    period: ReportingBucket,
    minimum_cohort_size: int,
    reason: SuppressionReason,
) -> TeamAggregate:
    return TeamAggregate(
        organization_id=organization_id,
        team_id=team_id,
        period=period,
        minimum_cohort_size=minimum_cohort_size,
        suppressed=True,
        suppression_reason=reason,
    )


def aggregate_team_snapshots(
    records: tuple[SnapshotRecord, ...],
    *,
    organization_id: str,
    team_id: str,
    period: ReportingBucket,
    eligible_subject_ids: frozenset[str],
    minimum_cohort_size: int = MINIMUM_COHORT_SIZE,
) -> TeamAggregate:
    """Compute a candidate aggregate for contract tests and future policy work.

    ``eligible_subject_ids`` is the current cohort that could have reported,
    supplied by the caller from the directory. Passing the whole membership
    rather than a count is what makes silence visible: without it, a team where
    two of nine people reported would be indistinguishable from a team of two.
    A snapshot from someone outside the cohort is ignored rather than counted.
    """

    eligible_subjects = len(eligible_subject_ids)
    eligible = [
        record
        for record in records
        if record.organization_id == organization_id
        and record.team_id == team_id
        and record.subject_user_id in eligible_subject_ids
        and record.visibility in AGGREGATE_VISIBILITY_SCOPES
        and record.period == period
    ]
    deduplicated = _latest_per_subject(tuple(eligible))
    cohort_size = len(deduplicated)

    if cohort_size == 0:
        return _suppressed(
            organization_id=organization_id,
            team_id=team_id,
            period=period,
            minimum_cohort_size=minimum_cohort_size,
            # Zero and one-through-(k-1) use the same public reason. A distinct
            # "empty" reason would itself disclose a sub-threshold count.
            reason=SuppressionReason.COHORT_TOO_SMALL,
        )
    if cohort_size < minimum_cohort_size:
        return _suppressed(
            organization_id=organization_id,
            team_id=team_id,
            period=period,
            minimum_cohort_size=minimum_cohort_size,
            reason=SuppressionReason.COHORT_TOO_SMALL,
        )

    totals: dict[SnapshotMetricKey, float] = {}
    contributors: dict[SnapshotMetricKey, int] = {}
    # Keys that everybody reported as unknown still belong in the result.
    # Dropping them would turn "nobody could measure this" into "nobody was
    # asked", which is the missingness confusion this plane exists to avoid.
    reported: set[SnapshotMetricKey] = set()
    for record in deduplicated:
        for measurement in record.envelope.measurements:
            reported.add(measurement.key)
            if measurement.value is None:
                continue
            totals[measurement.key] = (
                totals.get(measurement.key, 0.0) + measurement.value
            )
            contributors[measurement.key] = contributors.get(measurement.key, 0) + 1

    measurements: list[AggregateMeasurement] = []
    for key in sorted(reported, key=lambda entry: entry.value):
        contributing = contributors.get(key, 0)
        unit = SNAPSHOT_METRIC_UNITS[key]
        # A key reported by only a few people re-creates a small cohort inside
        # a large one, so it is suppressed independently of the cohort check,
        # and its contributor count is withheld along with its value.
        if contributing < minimum_cohort_size:
            measurements.append(
                AggregateMeasurement(
                    key=key,
                    unit=unit,
                    suppressed=True,
                    suppression_reason=(
                        SuppressionReason.MEASUREMENT_COHORT_TOO_SMALL
                    ),
                )
            )
            continue
        measurements.append(
            AggregateMeasurement(
                key=key,
                unit=unit,
                value=totals[key],
                contributing_subjects=contributing,
                eligible_subjects=eligible_subjects,
            )
        )

    return TeamAggregate(
        organization_id=organization_id,
        team_id=team_id,
        period=period,
        minimum_cohort_size=minimum_cohort_size,
        cohort_size=cohort_size,
        eligible_subjects=eligible_subjects,
        suppressed=False,
        measurements=tuple(measurements),
    )


__all__ = [
    "AGGREGATE_VISIBILITY_SCOPES",
    "MINIMUM_COHORT_SIZE",
    "AggregateMeasurement",
    "SuppressionReason",
    "TeamAggregate",
    "aggregate_team_snapshots",
]
