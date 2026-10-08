"""Default-deny, visibility, manager-grant, and tenant-isolation policy tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.control_plane import (
    AccessAction,
    AccessPrincipal,
    AccessResource,
    ApiClientState,
    ApiScope,
    DeviceState,
    ManagerAccessGrant,
    MembershipState,
    OrganizationRole,
    ReasonCode,
    VisibilityScope,
    authorize,
)


NOW = datetime(2047, 5, 6, 7, 8, tzinfo=UTC)
ORGANIZATION = "a" * 64
OTHER_ORGANIZATION = "b" * 64
TEAM = "c" * 64
OTHER_TEAM = "d" * 64
ACTOR = "e" * 64
SUBJECT = "f" * 64
DEVICE = "1" * 64
CLIENT = "2" * 64
GRANT = "3" * 64

ALL_SCOPES = tuple(sorted(ApiScope, key=lambda scope: scope.value))


def principal(**overrides: object) -> AccessPrincipal:
    fields: dict[str, object] = {
        "organization_id": ORGANIZATION,
        "user_id": ACTOR,
        "role": OrganizationRole.MEMBER,
        "membership_state": MembershipState.ACTIVE,
        "team_ids": (TEAM,),
        "device_id": DEVICE,
        "device_state": DeviceState.ACTIVE,
        "client_id": CLIENT,
        "client_state": ApiClientState.ACTIVE,
        "client_scopes": ALL_SCOPES,
    }
    fields.update(overrides)
    return AccessPrincipal(**fields)


def resource(**overrides: object) -> AccessResource:
    fields: dict[str, object] = {
        "organization_id": ORGANIZATION,
        "subject_user_id": SUBJECT,
        "team_id": TEAM,
        "visibility": VisibilityScope.INDIVIDUAL,
    }
    fields.update(overrides)
    return AccessResource(**fields)


def team_grant(**overrides: object) -> ManagerAccessGrant:
    fields: dict[str, object] = {
        "grant_id": GRANT,
        "organization_id": ORGANIZATION,
        "manager_user_id": ACTOR,
        "team_id": TEAM,
        "granted_at": NOW - timedelta(hours=1),
        "expires_at": NOW + timedelta(hours=1),
    }
    fields.update(overrides)
    return ManagerAccessGrant(**fields)


@pytest.mark.parametrize("action", list(AccessAction))
def test_every_action_denies_without_a_scope(action: AccessAction) -> None:
    decision = authorize(
        principal(client_scopes=()), resource(), action, now=NOW
    )
    assert decision.allowed is False
    assert decision.reason is ReasonCode.SCOPE_MISSING
    assert decision.requires_audit is True


@pytest.mark.parametrize("action", list(AccessAction))
def test_every_action_denies_across_tenants(action: AccessAction) -> None:
    decision = authorize(
        principal(),
        resource(organization_id=OTHER_ORGANIZATION),
        action,
        now=NOW,
        grants=(team_grant(),),
    )
    assert decision.allowed is False
    assert decision.reason is ReasonCode.CROSS_TENANT


@pytest.mark.parametrize(
    "state", [MembershipState.REVOKED, MembershipState.SUSPENDED]
)
def test_inactive_membership_loses_every_permission(
    state: MembershipState,
) -> None:
    decision = authorize(
        principal(membership_state=state),
        resource(subject_user_id=ACTOR),
        AccessAction.READ_SNAPSHOT,
        now=NOW,
    )
    assert decision.allowed is False
    assert decision.reason is ReasonCode.MEMBERSHIP_INACTIVE


def test_revoked_device_cannot_push_or_read() -> None:
    revoked = principal(device_state=DeviceState.REVOKED)
    for action in (AccessAction.PUSH_SNAPSHOT, AccessAction.READ_SNAPSHOT):
        decision = authorize(
            revoked, resource(subject_user_id=ACTOR), action, now=NOW
        )
        assert decision.allowed is False
        assert decision.reason is ReasonCode.DEVICE_INACTIVE


def test_individual_visibility_is_readable_only_by_its_subject() -> None:
    own = authorize(
        principal(),
        resource(subject_user_id=ACTOR),
        AccessAction.READ_SNAPSHOT,
        now=NOW,
    )
    assert own.allowed is True
    assert own.reason is ReasonCode.SELF_ACCESS

    other = authorize(
        principal(), resource(), AccessAction.READ_SNAPSHOT, now=NOW
    )
    assert other.allowed is False
    assert other.reason is ReasonCode.INDIVIDUAL_VISIBILITY


def test_team_visibility_requires_membership_of_that_team() -> None:
    inside = authorize(
        principal(),
        resource(visibility=VisibilityScope.TEAM),
        AccessAction.READ_SNAPSHOT,
        now=NOW,
    )
    assert inside.allowed is True
    assert inside.reason is ReasonCode.TEAM_VISIBILITY

    outside = authorize(
        principal(team_ids=(OTHER_TEAM,)),
        resource(visibility=VisibilityScope.TEAM),
        AccessAction.READ_SNAPSHOT,
        now=NOW,
    )
    assert outside.allowed is False
    assert outside.reason is ReasonCode.TEAM_MEMBERSHIP_REQUIRED


def test_organization_visibility_is_readable_by_any_active_member() -> None:
    decision = authorize(
        principal(team_ids=()),
        resource(visibility=VisibilityScope.ORGANIZATION, team_id=None),
        AccessAction.READ_SNAPSHOT,
        now=NOW,
    )
    assert decision.allowed is True
    assert decision.reason is ReasonCode.ORGANIZATION_VISIBILITY


def test_manager_access_needs_an_explicit_unexpired_grant_and_is_audited() -> None:
    manager = principal(role=OrganizationRole.MANAGER, team_ids=())

    without_grant = authorize(
        manager, resource(), AccessAction.READ_SNAPSHOT, now=NOW
    )
    assert without_grant.allowed is False
    assert without_grant.reason is ReasonCode.INDIVIDUAL_VISIBILITY

    granted = authorize(
        manager,
        resource(),
        AccessAction.READ_SNAPSHOT,
        now=NOW,
        grants=(team_grant(),),
    )
    assert granted.allowed is True
    assert granted.reason is ReasonCode.MANAGER_GRANT
    assert granted.requires_audit is True
    assert granted.manager_grant_id == GRANT

    expired = authorize(
        manager,
        resource(),
        AccessAction.READ_SNAPSHOT,
        now=NOW + timedelta(hours=2),
        grants=(team_grant(),),
    )
    assert expired.allowed is False

    other_tenant_grant = authorize(
        manager,
        resource(),
        AccessAction.READ_SNAPSHOT,
        now=NOW,
        grants=(team_grant(organization_id=OTHER_ORGANIZATION),),
    )
    assert other_tenant_grant.allowed is False

    someone_elses_grant = authorize(
        manager,
        resource(),
        AccessAction.READ_SNAPSHOT,
        now=NOW,
        grants=(team_grant(manager_user_id=SUBJECT),),
    )
    assert someone_elses_grant.allowed is False


def test_a_plain_member_cannot_use_a_grant_meant_for_a_manager() -> None:
    decision = authorize(
        principal(team_ids=()),
        resource(),
        AccessAction.READ_SNAPSHOT,
        now=NOW,
        grants=(team_grant(),),
    )
    assert decision.allowed is False
    assert decision.reason is ReasonCode.INDIVIDUAL_VISIBILITY


def test_a_subject_grant_does_not_unlock_a_whole_cohort() -> None:
    manager = principal(role=OrganizationRole.MANAGER, team_ids=())
    subject_only = team_grant(team_id=None, subject_user_id=SUBJECT)

    one_person = authorize(
        manager,
        resource(),
        AccessAction.READ_SNAPSHOT,
        now=NOW,
        grants=(subject_only,),
    )
    assert one_person.allowed is True

    cohort = authorize(
        manager,
        resource(subject_user_id=None),
        AccessAction.READ_TEAM_AGGREGATE,
        now=NOW,
        grants=(subject_only,),
    )
    assert cohort.allowed is False
    assert cohort.reason is ReasonCode.MANAGER_GRANT_REQUIRED


def test_pushing_is_restricted_to_the_caller_with_a_bound_device() -> None:
    mismatched = authorize(
        principal(), resource(), AccessAction.PUSH_SNAPSHOT, now=NOW
    )
    assert mismatched.allowed is False
    assert mismatched.reason is ReasonCode.SUBJECT_MISMATCH

    with pytest.raises(ValidationError):
        principal(device_id=None, device_state=None)

    allowed = authorize(
        principal(),
        resource(subject_user_id=ACTOR),
        AccessAction.PUSH_SNAPSHOT,
        now=NOW,
    )
    assert allowed.allowed is True


def test_audit_and_directory_administration_require_an_administrative_role() -> None:
    for action in (AccessAction.READ_AUDIT, AccessAction.ADMINISTER_DIRECTORY):
        member = authorize(principal(), resource(), action, now=NOW)
        assert member.allowed is False
        assert member.reason is ReasonCode.DEFAULT_DENY

        manager = authorize(
            principal(role=OrganizationRole.MANAGER), resource(), action, now=NOW
        )
        assert manager.allowed is False

        admin = authorize(
            principal(role=OrganizationRole.ADMIN), resource(), action, now=NOW
        )
        assert admin.allowed is True
        assert admin.reason is ReasonCode.ADMINISTRATIVE_ROLE
        assert admin.requires_audit is True


def test_deletion_is_self_service_or_administrative() -> None:
    own = authorize(
        principal(),
        resource(subject_user_id=ACTOR),
        AccessAction.DELETE_SUBJECT_DATA,
        now=NOW,
    )
    assert own.allowed is True
    assert own.requires_audit is True

    other = authorize(
        principal(), resource(), AccessAction.DELETE_SUBJECT_DATA, now=NOW
    )
    assert other.allowed is False

    admin = authorize(
        principal(role=OrganizationRole.OWNER),
        resource(),
        AccessAction.DELETE_SUBJECT_DATA,
        now=NOW,
    )
    assert admin.allowed is True
