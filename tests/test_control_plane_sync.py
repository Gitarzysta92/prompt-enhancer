"""End-to-end service tests for identity, synchronization, and erasure."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest

from prompt_enhancer.application.control_plane import (
    ENVELOPE_RESERVATION_TTL,
    ApiClientState,
    ApiScope,
    AuditAction,
    AuthorizationDeniedError,
    CursorError,
    DirectoryNotFoundError,
    EntitlementError,
    EnvelopeRejectedError,
    EnvelopeReplayedError,
    MeasurementDefinitionVersion,
    MeasurementUnit,
    OrganizationRole,
    ProducerAdapterVersion,
    ReasonCode,
    ReportingBucket,
    ReportingBucketKind,
    SnapshotEnvelope,
    SnapshotMeasurement,
    SnapshotMetricKey,
    SuppressionReason,
    VisibilityScope,
)
from prompt_enhancer.infrastructure.control_plane import (
    ProvisionedSeat,
    create_development_control_plane,
    credential_digest,
    sign_development_envelope,
)


PERIOD = ReportingBucket(kind=ReportingBucketKind.ISO_WEEK, key="2047-W10")
NOW = PERIOD.end + timedelta(hours=1)
ALL_SCOPES = tuple(sorted(ApiScope, key=lambda scope: scope.value))


def _plane():  # type: ignore[no-untyped-def]
    plane = create_development_control_plane(lambda: NOW)
    organization = plane.create_organization(now=NOW, sync_enabled=True)
    team = plane.create_team(organization.organization_id, now=NOW)
    return plane, organization, team


def _seat(plane, organization, team, *, role=OrganizationRole.MEMBER):  # type: ignore[no-untyped-def]
    return plane.provision_seat(
        organization.organization_id,
        now=NOW,
        role=role,
        team_ids=(team.team_id,),
        scopes=ALL_SCOPES,
    )


def _signed(
    plane,
    organization,
    seat: ProvisionedSeat,
    *,
    visibility: VisibilityScope = VisibilityScope.INDIVIDUAL,
    team_id: str | None = None,
    value: float = 4.0,
    envelope_id: str | None = None,
    issued_at: datetime | None = None,
):  # type: ignore[no-untyped-def]
    issued_id = envelope_id or plane.service.issue_envelope_identifier(
        seat.identity
    ).envelope_id
    envelope = SnapshotEnvelope(
        envelope_id=issued_id,
        team_id=team_id,
        visibility=visibility,
        period=PERIOD,
        issued_at=issued_at or NOW,
        measurement_definition_version=(
            MeasurementDefinitionVersion.COACHING_FREE_OPERATIONS_V1
        ),
        producer_adapter_version=ProducerAdapterVersion.DEVELOPMENT_V1,
        measurements=(
            SnapshotMeasurement(
                key=SnapshotMetricKey.SESSIONS_STARTED,
                unit=MeasurementUnit.COUNT,
                value=value,
                observed_count=1,
                eligible_count=1,
            ),
        ),
    )
    return sign_development_envelope(seat.device_key, envelope)


def test_server_issued_envelope_ids_are_bound_and_idempotent() -> None:
    plane, organization, team = _plane()
    first_seat = _seat(plane, organization, team)
    other_seat = _seat(plane, organization, team)
    signed = _signed(plane, organization, first_seat)

    first = plane.service.push(first_seat.identity, signed)
    duplicate = plane.service.push(first_seat.identity, signed)

    assert first.duplicate is False
    assert duplicate.duplicate is True
    assert duplicate.snapshot_id == first.snapshot_id
    stored = plane.snapshots.snapshot_by_envelope(
        organization.organization_id, signed.envelope.envelope_id
    )
    assert stored is not None
    assert stored.organization_id == organization.organization_id
    assert stored.subject_user_id == first_seat.membership.user_id
    assert stored.device_id == first_seat.device.device_id

    arbitrary = signed.envelope.model_copy(update={"envelope_id": "f" * 64})
    forged_id = sign_development_envelope(first_seat.device_key, arbitrary)
    with pytest.raises(EnvelopeRejectedError) as unregistered:
        plane.service.push(first_seat.identity, forged_id)
    assert unregistered.value.reason is ReasonCode.ENVELOPE_ID_UNREGISTERED
    rejected_events = plane.audit.events[organization.organization_id]
    assert "envelope_id" not in rejected_events[-1].model_dump(mode="json")
    assert "f" * 64 not in "".join(
        event.model_dump_json() for event in rejected_events
    )

    reserved_for_first = plane.service.issue_envelope_identifier(
        first_seat.identity
    ).envelope_id
    wrong_owner = _signed(
        plane, organization, other_seat, envelope_id=reserved_for_first
    )
    with pytest.raises(EnvelopeRejectedError) as rebound:
        plane.service.push(other_seat.identity, wrong_owner)
    assert rebound.value.reason is ReasonCode.ENVELOPE_ID_UNREGISTERED


def test_reserve_without_consumption_is_bounded_and_ids_never_enter_audit() -> None:
    current = [NOW]
    plane = create_development_control_plane(lambda: current[0])
    organization = plane.create_organization(now=NOW, sync_enabled=True)
    team = plane.create_team(organization.organization_id, now=NOW)
    seat = _seat(plane, organization, team)

    # Without consuming the reservation, thousands of issue calls expose only
    # one candidate. This deliberately says nothing about push-then-reissue.
    candidates = tuple(
        plane.service.issue_envelope_identifier(seat.identity).envelope_id
        for _ in range(2_048)
    )
    assert len(set(candidates)) == 1
    first = candidates[0]
    issued_events = [
        event
        for event in plane.audit.events[organization.organization_id]
        if event.action is AuditAction.ENVELOPE_IDENTIFIER_ISSUED
    ]
    assert len(issued_events) == 1

    current[0] = NOW + ENVELOPE_RESERVATION_TTL
    expired = _signed(
        plane,
        organization,
        seat,
        envelope_id=first,
        issued_at=current[0],
    )
    with pytest.raises(EnvelopeRejectedError) as rejected:
        plane.service.push(seat.identity, expired)
    assert rejected.value.reason is ReasonCode.ENVELOPE_RESERVATION_EXPIRED

    replacement = plane.service.issue_envelope_identifier(seat.identity).envelope_id
    assert replacement != first
    accepted = _signed(
        plane,
        organization,
        seat,
        envelope_id=replacement,
        issued_at=current[0],
    )
    plane.service.push(seat.identity, accepted)
    post_consumption = plane.service.issue_envelope_identifier(
        seat.identity
    ).envelope_id
    assert post_consumption != replacement

    # The development delta shape carries its accepted envelope ID. The hard
    # guarantee here is audit minimization, not removal of every signaling path.
    delivered = plane.service.pull(seat.identity)
    assert delivered.items[0].snapshot is not None
    assert delivered.items[0].snapshot.envelope.envelope_id == replacement

    # Both a server reservation selected by the caller and an attacker-chosen
    # canary stay out of every audit event, including allow and deny events.
    attacker_canary = "cafe" * 16
    forged = accepted.envelope.model_copy(update={"envelope_id": attacker_canary})
    with pytest.raises(EnvelopeRejectedError):
        plane.service.push(
            seat.identity,
            sign_development_envelope(seat.device_key, forged),
        )
    audit_json = "".join(
        event.model_dump_json()
        for event in plane.audit.events[organization.organization_id]
    )
    assert first not in audit_json
    assert replacement not in audit_json
    assert post_consumption not in audit_json
    assert attacker_canary not in audit_json
    assert all(
        "envelope_id" not in event.model_dump(mode="json")
        for event in plane.audit.events[organization.organization_id]
    )


def test_erasure_invalidates_all_prior_reservations_even_with_future_issue_time() -> None:
    current = [NOW]
    plane = create_development_control_plane(lambda: current[0])
    organization = plane.create_organization(now=NOW, sync_enabled=True)
    team = plane.create_team(organization.organization_id, now=NOW)
    seat = _seat(plane, organization, team)
    first = plane.service.issue_envelope_identifier(seat.identity).envelope_id
    second = plane.service.issue_envelope_identifier(seat.identity).envelope_id
    assert second == first

    deletion = plane.service.delete_subject_data(
        seat.identity, seat.membership.user_id
    )
    assert deletion.deleted_snapshot_count == 0
    assert plane.snapshots.envelope_reservation(
        organization.organization_id, first
    ) is None
    assert plane.snapshots.envelope_reservation(
        organization.organization_id, second
    ) is None

    current[0] = NOW + timedelta(hours=1)
    replay = _signed(
        plane,
        organization,
        seat,
        envelope_id=first,
        issued_at=current[0],
    )
    with pytest.raises(EnvelopeRejectedError) as rejected:
        plane.service.push(seat.identity, replay)
    assert rejected.value.reason is ReasonCode.ENVELOPE_ID_UNREGISTERED

    post_erasure = _signed(plane, organization, seat, issued_at=current[0])
    assert plane.service.push(seat.identity, post_erasure).duplicate is False


def test_denied_request_identifiers_are_not_persisted_in_audit() -> None:
    plane, organization, team = _plane()
    seat = _seat(plane, organization, team)
    attacker_chosen_subject = "a" * 64

    with pytest.raises(DirectoryNotFoundError):
        plane.service.delete_subject_data(seat.identity, attacker_chosen_subject)

    events = plane.audit.events[organization.organization_id]
    denial = events[-1]
    assert denial.reason is ReasonCode.DEFAULT_DENY
    assert denial.subject_user_id is None
    assert denial.team_id is None
    assert denial.manager_grant_id is None
    assert "envelope_id" not in denial.model_dump(mode="json")
    encoded = "".join(event.model_dump_json() for event in events)
    assert attacker_chosen_subject not in encoded


def test_deletion_keeps_replay_fence_and_emits_only_opaque_tombstone() -> None:
    plane, organization, team = _plane()
    seat = _seat(plane, organization, team)
    peer = _seat(plane, organization, team)
    signed = _signed(plane, organization, seat)
    pushed = plane.service.push(seat.identity, signed)
    delivered = plane.service.pull(seat.identity)
    assert len(delivered.items) == 1
    recipient_snapshot_id = delivered.items[0].snapshot.snapshot_id  # type: ignore[union-attr]
    assert recipient_snapshot_id != pushed.snapshot_id
    plane.service.pull(seat.identity, acknowledge_through=1)

    deletion = plane.service.delete_subject_data(
        seat.identity, seat.membership.user_id
    )
    assert deletion.deleted_snapshot_count == 1
    owner_page = plane.service.pull(seat.identity)
    assert len(owner_page.items) == 1
    marker = owner_page.items[0].tombstone
    assert marker is not None
    assert marker.target_snapshot_id == recipient_snapshot_id
    public = marker.model_dump(mode="json")
    assert set(public) == {
        "tombstone_id",
        "target_snapshot_id",
        "recorded_at",
    }
    for sensitive in (
        seat.membership.user_id,
        signed.envelope.envelope_id,
        organization.organization_id,
        team.team_id,
        "subject_request",
    ):
        assert sensitive not in marker.model_dump_json()

    assert [item.tombstone for item in owner_page.items] == [marker]
    assert "audience" not in owner_page.model_dump(mode="json")["items"][0]

    peer_page = plane.service.pull(peer.identity)
    assert peer_page.items == ()
    assert peer_page.next_cursor.sequence == 0

    with pytest.raises(EnvelopeReplayedError):
        plane.service.push(seat.identity, signed)
    consumed = plane.snapshots.consumed_envelope(
        organization.organization_id, signed.envelope.envelope_id
    )
    assert consumed is not None and consumed.deleted is True
    assert plane.snapshots.envelope_reservation(
        organization.organization_id, signed.envelope.envelope_id
    ) is None

    stolen = _signed(
        plane,
        organization,
        peer,
        envelope_id=signed.envelope.envelope_id,
    )
    with pytest.raises(EnvelopeRejectedError) as wrong_owner:
        plane.service.push(peer.identity, stolen)
    assert wrong_owner.value.reason is ReasonCode.ENVELOPE_ID_UNREGISTERED
    assert "envelope_id" not in plane.audit.events[
        organization.organization_id
    ][-1].model_dump(mode="json")


def test_recipient_cursor_has_no_gap_for_unauthorized_source_rows() -> None:
    plane, organization, team = _plane()
    hidden_subject = _seat(plane, organization, team)
    recipient = _seat(plane, organization, team)
    plane.service.push(
        hidden_subject.identity, _signed(plane, organization, hidden_subject)
    )

    hidden_only = plane.service.pull(recipient.identity)
    assert hidden_only.items == ()
    assert hidden_only.acknowledged_cursor.sequence == 0
    assert hidden_only.next_cursor.sequence == 0

    plane.service.push(recipient.identity, _signed(plane, organization, recipient))
    visible = plane.service.pull(recipient.identity)
    assert [item.sequence for item in visible.items] == [1]
    assert visible.next_cursor.sequence == 1
    assert "sequence" not in visible.model_dump(mode="json")["items"][0][
        "snapshot"
    ]


def test_erasure_scrubs_an_unacknowledged_snapshot_retry() -> None:
    plane, organization, team = _plane()
    subject = _seat(plane, organization, team)
    plane.service.push(subject.identity, _signed(plane, organization, subject))
    first = plane.service.pull(subject.identity)
    handle = first.items[0].snapshot.snapshot_id  # type: ignore[union-attr]

    plane.service.delete_subject_data(subject.identity, subject.membership.user_id)
    retry = plane.service.pull(subject.identity)

    assert [item.sequence for item in retry.items] == [1, 2]
    assert all(item.snapshot is None for item in retry.items)
    assert all(
        item.tombstone is not None
        and item.tombstone.target_snapshot_id == handle
        for item in retry.items
    )


def test_unacknowledged_manager_projection_retries_after_grant_ends() -> None:
    current = [NOW]
    plane = create_development_control_plane(lambda: current[0])
    organization = plane.create_organization(now=NOW, sync_enabled=True)
    team = plane.create_team(organization.organization_id, now=NOW)
    owner = _seat(plane, organization, team, role=OrganizationRole.OWNER)
    revoked_manager = _seat(
        plane, organization, team, role=OrganizationRole.MANAGER
    )
    expired_manager = _seat(
        plane, organization, team, role=OrganizationRole.MANAGER
    )
    subject = _seat(plane, organization, team)
    revoked_grant = plane.grant_manager_access(
        organization.organization_id,
        manager_user_id=revoked_manager.membership.user_id,
        subject_user_id=subject.membership.user_id,
        granted_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    plane.grant_manager_access(
        organization.organization_id,
        manager_user_id=expired_manager.membership.user_id,
        subject_user_id=subject.membership.user_id,
        granted_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    plane.service.push(subject.identity, _signed(plane, organization, subject))

    first_revoked = plane.service.pull(revoked_manager.identity)
    first_expired = plane.service.pull(expired_manager.identity)
    plane.service.revoke_manager_grant(owner.identity, revoked_grant.grant_id)
    current[0] = NOW + timedelta(hours=2)

    retry_revoked = plane.service.pull(revoked_manager.identity)
    retry_expired = plane.service.pull(expired_manager.identity)
    assert retry_revoked.items == first_revoked.items
    assert retry_expired.items == first_expired.items
    assert [item.sequence for item in retry_revoked.items] == [1]
    assert [item.sequence for item in retry_expired.items] == [1]


def test_revoked_and_expired_managers_receive_recipient_scoped_deletion() -> None:
    current = [NOW]
    plane = create_development_control_plane(lambda: current[0])
    organization = plane.create_organization(now=NOW, sync_enabled=True)
    team = plane.create_team(organization.organization_id, now=NOW)
    owner = _seat(plane, organization, team, role=OrganizationRole.OWNER)
    revoked_manager = _seat(
        plane, organization, team, role=OrganizationRole.MANAGER
    )
    expired_manager = _seat(
        plane, organization, team, role=OrganizationRole.MANAGER
    )
    subject = _seat(plane, organization, team)
    revoked_grant = plane.grant_manager_access(
        organization.organization_id,
        manager_user_id=revoked_manager.membership.user_id,
        subject_user_id=subject.membership.user_id,
        granted_at=NOW,
        expires_at=NOW + timedelta(days=1),
    )
    expired_grant = plane.grant_manager_access(
        organization.organization_id,
        manager_user_id=expired_manager.membership.user_id,
        subject_user_id=subject.membership.user_id,
        granted_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    plane.service.push(subject.identity, _signed(plane, organization, subject))

    revoked_snapshot = plane.service.pull(revoked_manager.identity)
    expired_snapshot = plane.service.pull(expired_manager.identity)
    subject_snapshot = plane.service.pull(subject.identity)
    revoked_handle = revoked_snapshot.items[0].snapshot.snapshot_id  # type: ignore[union-attr]
    expired_handle = expired_snapshot.items[0].snapshot.snapshot_id  # type: ignore[union-attr]
    subject_handle = subject_snapshot.items[0].snapshot.snapshot_id  # type: ignore[union-attr]
    assert len({revoked_handle, expired_handle, subject_handle}) == 3
    plane.service.pull(revoked_manager.identity, acknowledge_through=1)
    plane.service.pull(expired_manager.identity, acknowledge_through=1)
    plane.service.pull(subject.identity, acknowledge_through=1)

    revoked = plane.service.revoke_manager_grant(
        owner.identity, revoked_grant.grant_id
    )
    assert revoked.revoked_at == NOW
    current[0] = NOW + timedelta(hours=2)
    assert expired_grant.is_active(current[0]) is False
    plane.service.delete_subject_data(subject.identity, subject.membership.user_id)

    revoked_deletion = plane.service.pull(revoked_manager.identity)
    expired_deletion = plane.service.pull(expired_manager.identity)
    subject_deletion = plane.service.pull(subject.identity)
    revoked_marker = revoked_deletion.items[0].tombstone
    expired_marker = expired_deletion.items[0].tombstone
    subject_marker = subject_deletion.items[0].tombstone
    assert revoked_marker is not None
    assert expired_marker is not None
    assert subject_marker is not None
    assert revoked_deletion.items[0].sequence == 2
    assert expired_deletion.items[0].sequence == 2
    assert subject_deletion.items[0].sequence == 2
    assert revoked_marker.target_snapshot_id == revoked_handle
    assert expired_marker.target_snapshot_id == expired_handle
    assert subject_marker.target_snapshot_id == subject_handle
    assert len(
        {
            revoked_marker.tombstone_id,
            expired_marker.tombstone_id,
            subject_marker.tombstone_id,
        }
    ) == 3


def test_acknowledgements_are_monotonic_and_client_device_bound() -> None:
    plane, organization, team = _plane()
    seat = _seat(plane, organization, team)
    other = _seat(plane, organization, team)
    for _ in range(3):
        plane.service.push(seat.identity, _signed(plane, organization, seat))

    first = plane.service.pull(seat.identity, limit=2)
    assert [item.sequence for item in first.items] == [1, 2]
    assert first.acknowledged_cursor.sequence == 0
    assert first.next_cursor.sequence == 2

    repeated = plane.service.pull(seat.identity, limit=2)
    assert [item.sequence for item in repeated.items] == [1, 2]

    second = plane.service.pull(seat.identity, acknowledge_through=2, limit=2)
    assert [item.sequence for item in second.items] == [3]
    assert second.acknowledged_cursor.sequence == 2

    with pytest.raises(CursorError) as backwards:
        plane.service.pull(seat.identity, acknowledge_through=1)
    assert backwards.value.reason is ReasonCode.CURSOR_REGRESSION
    with pytest.raises(CursorError) as future:
        plane.service.pull(seat.identity, acknowledge_through=99)
    assert future.value.reason is ReasonCode.CURSOR_NOT_OFFERED
    with pytest.raises(CursorError) as other_client:
        plane.service.pull(other.identity, acknowledge_through=2)
    assert other_client.value.reason is ReasonCode.CURSOR_NOT_OFFERED


def test_device_revocation_atomically_ends_key_client_and_credential_access() -> None:
    plane, organization, team = _plane()
    owner = _seat(plane, organization, team, role=OrganizationRole.OWNER)
    member = _seat(plane, organization, team)
    assert plane.resolver.resolve(member.credential) == member.identity

    plane.service.revoke_device(owner.identity, member.device.device_id)

    assert plane.devices.verification_key(
        organization.organization_id, member.device.device_id
    ) is None
    client = plane.clients.client(
        organization.organization_id, member.client.client_id
    )
    assert client is not None and client.state is ApiClientState.REVOKED
    assert credential_digest(member.credential) in plane.credentials.revoked_digests
    assert plane.resolver.resolve(member.credential) is None
    with pytest.raises(AuthorizationDeniedError):
        plane.service.pull(member.identity)


def test_remote_sync_entitlement_is_enforced_without_blocking_erasure() -> None:
    plane, organization, team = _plane()
    seat = _seat(plane, organization, team)
    signed = _signed(plane, organization, seat)
    plane.service.push(seat.identity, signed)
    plane.set_sync_entitlement(organization.organization_id, enabled=False, now=NOW)

    with pytest.raises(EntitlementError):
        plane.service.issue_envelope_identifier(seat.identity)
    with pytest.raises(EntitlementError):
        plane.service.pull(seat.identity)

    deletion = plane.service.delete_subject_data(
        seat.identity, seat.membership.user_id
    )
    assert deletion.deleted_snapshot_count == 1


def test_in_memory_store_serializes_concurrent_sequence_allocation() -> None:
    plane, organization, team = _plane()
    # Each worker gets its own producer tuple. A producer may intentionally hold
    # only one outstanding reservation, so sharing one seat here would test
    # duplicate retry semantics instead of concurrent sequence allocation.
    seats = tuple(_seat(plane, organization, team) for _ in range(32))

    def publish(seat: ProvisionedSeat) -> str:
        receipt = plane.service.push(seat.identity, _signed(plane, organization, seat))
        return receipt.snapshot_id

    with ThreadPoolExecutor(max_workers=8) as workers:
        snapshot_ids = tuple(workers.map(publish, seats))

    sequences = tuple(
        item.sequence
        for item in plane.snapshots.read_since(
            organization.organization_id, sequence=0, limit=100
        )
        if item.snapshot is not None
    )
    assert sorted(sequences) == list(range(1, 33))
    assert len(set(snapshot_ids)) == 32


def test_team_aggregate_fails_closed_without_reviewed_differencing_controls() -> None:
    plane, organization, team = _plane()
    seats = tuple(_seat(plane, organization, team) for _ in range(5))
    for seat in seats:
        plane.service.push(
            seat.identity,
            _signed(
                plane,
                organization,
                seat,
                visibility=VisibilityScope.TEAM,
                team_id=team.team_id,
            ),
        )

    suppressed = plane.service.team_aggregate(
        seats[0].identity, team.team_id, period=PERIOD
    )
    late = _seat(plane, organization, team)
    plane.service.push(
        late.identity,
        _signed(
            plane,
            organization,
            late,
            visibility=VisibilityScope.TEAM,
            team_id=team.team_id,
            value=999.0,
        ),
    )
    repeated = plane.service.team_aggregate(
        seats[0].identity, team.team_id, period=PERIOD
    )
    assert repeated == suppressed
    assert suppressed.suppressed is True
    assert (
        suppressed.suppression_reason
        is SuppressionReason.DISCLOSURE_CONTROL_UNAVAILABLE
    )
    assert suppressed.cohort_size is None
    assert suppressed.eligible_subjects is None
    assert suppressed.measurements == ()

    plane.service.delete_subject_data(
        seats[0].identity, seats[0].membership.user_id
    )
    erased = plane.service.team_aggregate(
        seats[1].identity, team.team_id, period=PERIOD
    )
    assert erased.suppressed is True
    assert erased.cohort_size is None
    assert erased.eligible_subjects is None
    assert erased.measurements == ()


def test_overlapping_team_and_longitudinal_queries_expose_no_difference_operands() -> None:
    plane, organization, first_team = _plane()
    second_team = plane.create_team(organization.organization_id, now=NOW)
    seats = tuple(
        plane.provision_seat(
            organization.organization_id,
            now=NOW,
            team_ids=(first_team.team_id, second_team.team_id),
            scopes=ALL_SCOPES,
        )
        for _ in range(5)
    )
    for seat in seats:
        for team in (first_team, second_team):
            plane.service.push(
                seat.identity,
                _signed(
                    plane,
                    organization,
                    seat,
                    visibility=VisibilityScope.TEAM,
                    team_id=team.team_id,
                ),
            )

    following_period = ReportingBucket(
        kind=ReportingBucketKind.ISO_WEEK, key="2047-W11"
    )
    attempted_operands = (
        plane.service.team_aggregate(
            seats[0].identity, first_team.team_id, period=PERIOD
        ),
        plane.service.team_aggregate(
            seats[0].identity, second_team.team_id, period=PERIOD
        ),
        plane.service.team_aggregate(
            seats[0].identity, first_team.team_id, period=following_period
        ),
    )
    for result in attempted_operands:
        assert result.suppressed is True
        assert (
            result.suppression_reason
            is SuppressionReason.DISCLOSURE_CONTROL_UNAVAILABLE
        )
        assert result.cohort_size is None
        assert result.eligible_subjects is None
        assert result.measurements == ()
