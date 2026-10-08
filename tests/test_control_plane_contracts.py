"""Contract tests for the minimized control-plane surface."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.control_plane import (
    ALLOWED_SNAPSHOT_METRIC_KEYS,
    CONTROL_PLANE_CONTRACT_VERSION,
    DEVELOPMENT_READINESS_GAPS,
    UNIT_LIMITS,
    ApiClient,
    ApiClientState,
    ApiScope,
    ControlPlaneReadiness,
    DeploymentProfile,
    Device,
    DeviceState,
    Entitlement,
    EntitlementTier,
    ManagerAccessGrant,
    MeasurementDefinitionVersion,
    MeasurementUnit,
    Membership,
    MembershipState,
    OrganizationRole,
    ProducerAdapterVersion,
    ReportingBucket,
    ReportingBucketKind,
    SignatureAlgorithm,
    SnapshotEnvelope,
    SnapshotMeasurement,
    SnapshotMetricKey,
    VerifiedIdentity,
    VisibilityScope,
    canonical_envelope_bytes,
    envelope_digest,
)


PERIOD = ReportingBucket(kind=ReportingBucketKind.ISO_WEEK, key="2047-W10")
ISSUED = PERIOD.end + timedelta(hours=1)
ORGANIZATION = "a" * 64
TEAM = "b" * 64
USER = "c" * 64
DEVICE = "d" * 64
ENVELOPE = "e" * 64
FINGERPRINT = "f" * 64
CLIENT = "1" * 64
# Prose, not an identifier: spaces and punctuation are exactly what every
# control-plane string field must refuse.
CONTENT_CANARY = "SYNTHETIC private canary: def helper() # never store"


def measurement(**overrides: object) -> SnapshotMeasurement:
    fields: dict[str, object] = {
        "key": SnapshotMetricKey.SESSIONS_STARTED,
        "unit": MeasurementUnit.COUNT,
        "value": 4.0,
        "observed_count": 4,
        "eligible_count": 4,
    }
    fields.update(overrides)
    return SnapshotMeasurement(**fields)


def envelope(**overrides: object) -> SnapshotEnvelope:
    fields: dict[str, object] = {
        "envelope_id": ENVELOPE,
        "period": PERIOD,
        "issued_at": ISSUED,
        "measurement_definition_version": (
            MeasurementDefinitionVersion.COACHING_FREE_OPERATIONS_V1
        ),
        "producer_adapter_version": ProducerAdapterVersion.DEVELOPMENT_V1,
        "measurements": (measurement(),),
    }
    fields.update(overrides)
    return SnapshotEnvelope(**fields)


def test_allowlist_is_closed_and_no_field_accepts_prose() -> None:
    assert ALLOWED_SNAPSHOT_METRIC_KEYS == frozenset(SnapshotMetricKey)

    with pytest.raises(ValidationError):
        measurement(key="prompt.private_coaching_note")

    # No field of the envelope accepts prose. A future free-text field would
    # accept the canary and fail here, which is the point of the loop.
    for name in SnapshotEnvelope.model_fields:
        with pytest.raises(ValidationError):
            envelope(**{name: CONTENT_CANARY})
    for name in SnapshotMeasurement.model_fields:
        with pytest.raises(ValidationError):
            measurement(**{name: CONTENT_CANARY})

    with pytest.raises(ValidationError):
        envelope(note=CONTENT_CANARY)
    assert CONTENT_CANARY not in canonical_envelope_bytes(envelope()).decode("ascii")


def test_version_fields_are_server_registered_literals() -> None:
    """A version string is the obvious covert channel; it is an enum instead."""

    for field in ("measurement_definition_version", "producer_adapter_version"):
        for smuggled in (
            "control-plane-measurements-v1-CANARY",
            "development-producer-v1.7f3a",
            "v1",
        ):
            with pytest.raises(ValidationError):
                envelope(**{field: smuggled})

    accepted = envelope()
    assert accepted.measurement_definition_version in MeasurementDefinitionVersion
    assert accepted.producer_adapter_version in ProducerAdapterVersion


def test_envelope_has_no_caller_asserted_principal_fields() -> None:
    for field, value in (
        ("organization_id", ORGANIZATION),
        ("subject_user_id", USER),
        ("client_id", CLIENT),
        ("device_id", DEVICE),
    ):
        with pytest.raises(ValidationError):
            envelope(**{field: value})


def test_numeric_values_are_bounded_and_quantized() -> None:
    ceiling, _ = UNIT_LIMITS[MeasurementUnit.COUNT]

    with pytest.raises(ValidationError):
        measurement(value=ceiling + 1)
    with pytest.raises(ValidationError):
        measurement(value=4.0000001)
    with pytest.raises(ValidationError):
        measurement(value=float("inf"))
    with pytest.raises(ValidationError):
        measurement(value=-1.0)
    with pytest.raises(ValidationError):
        measurement(eligible_count=10_000_000)

    seconds = measurement(
        key=SnapshotMetricKey.ACTIVE_SECONDS,
        unit=MeasurementUnit.SECONDS,
        value=12.5,
    )
    assert seconds.value == 12.5
    with pytest.raises(ValidationError):
        measurement(
            key=SnapshotMetricKey.ACTIVE_SECONDS,
            unit=MeasurementUnit.SECONDS,
            value=12.55,
        )


def test_timestamps_are_whole_seconds_and_periods_are_canonical() -> None:
    with pytest.raises(ValidationError):
        envelope(issued_at=ISSUED.replace(microsecond=1))
    with pytest.raises(ValidationError):
        envelope(issued_at=ISSUED.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        envelope(issued_at=PERIOD.end - timedelta(seconds=1))
    with pytest.raises(ValidationError):
        envelope(issued_at=PERIOD.end + timedelta(days=40))

    with pytest.raises(ValidationError):
        ReportingBucket(kind=ReportingBucketKind.ISO_WEEK, key="2047-W99")
    with pytest.raises(ValidationError):
        ReportingBucket(kind=ReportingBucketKind.CALENDAR_MONTH, key="2047-13")
    with pytest.raises(ValidationError):
        ReportingBucket(kind=ReportingBucketKind.CALENDAR_MONTH, key="1999-01")

    month = ReportingBucket(kind=ReportingBucketKind.CALENDAR_MONTH, key="2047-12")
    assert month.start == datetime(2047, 12, 1, tzinfo=UTC)
    assert month.end == datetime(2048, 1, 1, tzinfo=UTC)


def test_unknown_measurements_never_become_zero() -> None:
    unknown = measurement(value=None, observed_count=0, eligible_count=6)
    assert unknown.value is None
    assert unknown.is_known is False
    assert unknown.coverage == 0.0

    with pytest.raises(ValidationError):
        measurement(value=None, observed_count=3, eligible_count=6)
    with pytest.raises(ValidationError):
        measurement(value=0.0, observed_count=0, eligible_count=6)


def test_envelope_requires_sorted_unique_measurements_and_a_named_team() -> None:
    with pytest.raises(ValidationError):
        envelope(measurements=(measurement(), measurement()))
    with pytest.raises(ValidationError):
        envelope(
            measurements=(
                measurement(key=SnapshotMetricKey.TOOL_INVOCATIONS),
                measurement(key=SnapshotMetricKey.SESSIONS_STARTED),
            )
        )
    with pytest.raises(ValidationError):
        envelope(visibility=VisibilityScope.TEAM)


def test_canonical_bytes_are_domain_separated_and_stable() -> None:
    first = canonical_envelope_bytes(envelope())
    second = canonical_envelope_bytes(envelope())
    assert first == second
    assert first.startswith(b"prompt-enhancer/control-plane-snapshot-v2\x00")

    changed = envelope(measurements=(measurement(value=5.0),))
    assert envelope_digest(changed) != envelope_digest(envelope())


def test_directory_records_bind_revocation_to_a_timestamp() -> None:
    membership = Membership(
        membership_id="2" * 64,
        organization_id=ORGANIZATION,
        user_id=USER,
        role=OrganizationRole.MEMBER,
        state=MembershipState.ACTIVE,
        team_ids=(TEAM,),
        created_at=ISSUED,
    )
    assert membership.is_active()
    assert membership.belongs_to_team(TEAM)

    with pytest.raises(ValidationError):
        Membership(**{**membership.model_dump(), "state": MembershipState.REVOKED})
    with pytest.raises(ValidationError):
        Device(
            device_id=DEVICE,
            organization_id=ORGANIZATION,
            user_id=USER,
            algorithm=SignatureAlgorithm.DEVELOPMENT_HMAC_SHA256,
            key_fingerprint=FINGERPRINT,
            state=DeviceState.REVOKED,
            registered_at=ISSUED,
        )


def test_a_client_is_bound_to_one_member_and_one_device() -> None:
    client = ApiClient(
        client_id=CLIENT,
        organization_id=ORGANIZATION,
        user_id=USER,
        device_id=DEVICE,
        scopes=(ApiScope.SNAPSHOTS_PULL, ApiScope.SNAPSHOTS_PUSH),
        state=ApiClientState.ACTIVE,
        created_at=ISSUED,
    )
    assert client.is_active()
    assert client.user_id == USER
    assert client.device_id == DEVICE

    for missing in ("user_id", "device_id"):
        fields = client.model_dump()
        fields.pop(missing)
        with pytest.raises(ValidationError):
            ApiClient(**fields)


def test_a_verified_identity_always_names_a_device() -> None:
    identity = VerifiedIdentity(
        organization_id=ORGANIZATION,
        user_id=USER,
        client_id=CLIENT,
        device_id=DEVICE,
        verified_at=ISSUED,
    )
    assert identity.device_id == DEVICE

    fields = identity.model_dump()
    fields.pop("device_id")
    with pytest.raises(ValidationError):
        VerifiedIdentity(**fields)


def test_manager_grants_name_exactly_one_target() -> None:
    for targets in ({}, {"subject_user_id": USER, "team_id": TEAM}):
        with pytest.raises(ValidationError):
            ManagerAccessGrant(
                grant_id="3" * 64,
                organization_id=ORGANIZATION,
                manager_user_id=USER,
                granted_at=ISSUED,
                expires_at=ISSUED + timedelta(hours=1),
                **targets,
            )

    grant = ManagerAccessGrant(
        grant_id="3" * 64,
        organization_id=ORGANIZATION,
        manager_user_id=USER,
        team_id=TEAM,
        granted_at=ISSUED,
        expires_at=ISSUED + timedelta(hours=1),
    )
    assert grant.is_active(ISSUED)
    assert not grant.is_active(ISSUED + timedelta(hours=1))
    assert grant.covers_team(TEAM)
    assert not grant.covers_subject("9" * 64)


def test_entitlement_gate_defaults_off_and_claims_nothing_extra() -> None:
    entitlement = Entitlement(organization_id=ORGANIZATION, evaluated_at=ISSUED)
    assert entitlement.tier is EntitlementTier.LOCAL_ONLY
    assert entitlement.remote_sync_enabled is False
    assert entitlement.billing_enabled is False
    assert entitlement.remote_transport_available is False
    assert entitlement.seat_limit is None

    for forbidden in ("billing_enabled", "remote_transport_available"):
        with pytest.raises(ValidationError):
            Entitlement(
                organization_id=ORGANIZATION,
                evaluated_at=ISSUED,
                **{forbidden: True},
            )

    enabled = Entitlement(
        organization_id=ORGANIZATION,
        evaluated_at=ISSUED,
        remote_sync_enabled=True,
    )
    assert enabled.remote_sync_enabled is True


def test_readiness_cannot_claim_a_finished_product() -> None:
    readiness = ControlPlaneReadiness(
        profile=DeploymentProfile.DEVELOPMENT,
        gaps=DEVELOPMENT_READINESS_GAPS,
    )
    assert readiness.contract_version == CONTROL_PLANE_CONTRACT_VERSION
    assert readiness.production_ready is False
    assert readiness.remote_listening_enabled is False
    assert readiness.delivery_guarantee == "at_least_once_with_monotonic_ack"
    assert len(readiness.gaps) >= 1

    with pytest.raises(ValidationError):
        ControlPlaneReadiness(
            profile=DeploymentProfile.PRODUCTION,
            production_ready=True,
            gaps=DEVELOPMENT_READINESS_GAPS,
        )
    with pytest.raises(ValidationError):
        ControlPlaneReadiness(profile=DeploymentProfile.DEVELOPMENT, gaps=())
