"""Disclosure controls for fixed-bucket team aggregation."""

from __future__ import annotations

from datetime import timedelta

from prompt_enhancer.application.control_plane import (
    MINIMUM_COHORT_SIZE,
    MeasurementDefinitionVersion,
    MeasurementUnit,
    ProducerAdapterVersion,
    ReportingBucket,
    ReportingBucketKind,
    SnapshotEnvelope,
    SnapshotMeasurement,
    SnapshotMetricKey,
    SnapshotRecord,
    SuppressionReason,
    VisibilityScope,
    aggregate_team_snapshots,
    envelope_digest,
)


PERIOD = ReportingBucket(kind=ReportingBucketKind.ISO_WEEK, key="2047-W10")
NOW = PERIOD.end + timedelta(hours=1)
ORGANIZATION = "a" * 64
TEAM = "b" * 64


def _subject(index: int) -> str:
    return f"{index:064d}"


def _record(
    sequence: int,
    subject_user_id: str,
    *,
    value: float | None = 3.0,
) -> SnapshotRecord:
    envelope = SnapshotEnvelope(
        envelope_id=f"{sequence:064d}",
        team_id=TEAM,
        visibility=VisibilityScope.TEAM,
        period=PERIOD,
        issued_at=NOW,
        measurement_definition_version=(
            MeasurementDefinitionVersion.COACHING_FREE_OPERATIONS_V1
        ),
        producer_adapter_version=ProducerAdapterVersion.DEVELOPMENT_V1,
        measurements=(
            SnapshotMeasurement(
                key=SnapshotMetricKey.SESSIONS_STARTED,
                unit=MeasurementUnit.COUNT,
                value=value,
                observed_count=0 if value is None else 1,
                eligible_count=1,
            ),
        ),
    )
    return SnapshotRecord(
        snapshot_id=f"{sequence + 1000:064d}",
        organization_id=ORGANIZATION,
        subject_user_id=subject_user_id,
        device_id="d" * 64,
        sequence=sequence,
        accepted_at=NOW,
        content_digest=envelope_digest(envelope),
        envelope=envelope,
    )


def _aggregate(records: tuple[SnapshotRecord, ...], eligible: int):
    return aggregate_team_snapshots(
        records,
        organization_id=ORGANIZATION,
        team_id=TEAM,
        period=PERIOD,
        eligible_subject_ids=frozenset(_subject(i) for i in range(1, eligible + 1)),
    )


def test_suppressed_cohorts_publish_no_sub_threshold_counts() -> None:
    aggregate = _aggregate(
        tuple(_record(i, _subject(i)) for i in range(1, MINIMUM_COHORT_SIZE)),
        eligible=MINIMUM_COHORT_SIZE + 3,
    )

    assert aggregate.suppressed is True
    assert aggregate.suppression_reason is SuppressionReason.COHORT_TOO_SMALL
    assert aggregate.cohort_size is None
    assert aggregate.eligible_subjects is None
    assert aggregate.measurements == ()

    empty = _aggregate((), eligible=9)
    assert empty.suppressed is True
    assert empty.suppression_reason is SuppressionReason.COHORT_TOO_SMALL
    assert empty.cohort_size is None
    assert empty.eligible_subjects is None


def test_sparse_measurements_withhold_value_and_every_count() -> None:
    records = tuple(
        _record(i, _subject(i), value=(3.0 if i == 1 else None))
        for i in range(1, MINIMUM_COHORT_SIZE + 1)
    )
    aggregate = _aggregate(records, eligible=MINIMUM_COHORT_SIZE)

    assert aggregate.suppressed is False
    measurement = aggregate.measurements[0]
    assert measurement.suppressed is True
    assert measurement.value is None
    assert measurement.contributing_subjects is None
    assert measurement.eligible_subjects is None
    assert measurement.missing_subjects is None
    assert measurement.coverage is None


def test_publishable_cohort_reports_missingness_only_at_or_above_k() -> None:
    records = tuple(
        _record(i, _subject(i)) for i in range(1, MINIMUM_COHORT_SIZE + 1)
    )
    aggregate = _aggregate(records, eligible=MINIMUM_COHORT_SIZE + 2)

    assert aggregate.suppressed is False
    assert aggregate.cohort_size == MINIMUM_COHORT_SIZE
    assert aggregate.eligible_subjects == MINIMUM_COHORT_SIZE + 2
    measurement = aggregate.measurements[0]
    assert measurement.value == 3.0 * MINIMUM_COHORT_SIZE
    assert measurement.contributing_subjects == MINIMUM_COHORT_SIZE
    assert measurement.missing_subjects == 2
