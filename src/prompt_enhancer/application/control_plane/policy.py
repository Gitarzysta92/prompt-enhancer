"""Default-deny authorization for every control-plane read and write.

:func:`authorize` is a pure function over facts the service resolved from the
directory after a credential was verified. Nothing a caller sends reaches this
function, so a caller cannot widen its own authority by claiming a role, a
team, a device, or a tenant.

The rules are written so that the only way to reach an allow is to match an
explicit clause. Every unmatched path falls through to
``ReasonCode.DEFAULT_DENY``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, StrictModel
from .contracts import (
    ADMINISTRATIVE_ROLES,
    MANAGERIAL_ROLES,
    ApiClientState,
    ApiScope,
    DeviceState,
    ManagerAccessGrant,
    MembershipState,
    OrganizationRole,
    ReasonCode,
    VisibilityScope,
)


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("policy identifiers must be HMAC pseudonyms")
    return value


def _optional_pseudonym(value: str | None) -> str | None:
    return None if value is None else _pseudonym(value)


class AccessAction(StrEnum):
    PUSH_SNAPSHOT = "push_snapshot"
    READ_SNAPSHOT = "read_snapshot"
    PULL_DELTA = "pull_delta"
    READ_TEAM_AGGREGATE = "read_team_aggregate"
    READ_AUDIT = "read_audit"
    DELETE_SUBJECT_DATA = "delete_subject_data"
    ADMINISTER_DIRECTORY = "administer_directory"
    MANAGE_OWN_DEVICE = "manage_own_device"


REQUIRED_SCOPES: dict[AccessAction, ApiScope] = {
    AccessAction.MANAGE_OWN_DEVICE: ApiScope.SNAPSHOTS_PUSH,
    AccessAction.PUSH_SNAPSHOT: ApiScope.SNAPSHOTS_PUSH,
    AccessAction.READ_SNAPSHOT: ApiScope.SNAPSHOTS_PULL,
    AccessAction.PULL_DELTA: ApiScope.SNAPSHOTS_PULL,
    AccessAction.READ_TEAM_AGGREGATE: ApiScope.AGGREGATES_READ,
    AccessAction.READ_AUDIT: ApiScope.AUDIT_READ,
    AccessAction.DELETE_SUBJECT_DATA: ApiScope.DELETION_REQUEST,
    AccessAction.ADMINISTER_DIRECTORY: ApiScope.DIRECTORY_ADMINISTER,
}


class AccessPrincipal(StrictModel):
    """Facts about the caller, all resolved by the service after verification.

    ``device_id`` is mandatory. Every credential is bound to one device, so
    there is no unattributed caller, and revoking a device ends everything that
    credential could do.
    """

    organization_id: str
    user_id: str
    role: OrganizationRole
    membership_state: MembershipState
    team_ids: tuple[str, ...] = ()
    device_id: str
    device_state: DeviceState
    client_id: str
    client_state: ApiClientState
    client_scopes: tuple[ApiScope, ...] = ()

    _identifiers = field_validator(
        "organization_id", "user_id", "device_id", "client_id"
    )(_pseudonym)

    @field_validator("team_ids")
    @classmethod
    def valid_team_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_pseudonym(value) for value in values)


class AccessResource(StrictModel):
    """The thing being reached for, described without any content."""

    organization_id: str
    subject_user_id: str | None = None
    team_id: str | None = None
    visibility: VisibilityScope = VisibilityScope.INDIVIDUAL

    _identifier = field_validator("organization_id")(_pseudonym)
    _optional_identifiers = field_validator("subject_user_id", "team_id")(
        _optional_pseudonym
    )


class AccessDecision(StrictModel):
    """The decision, its closed reason, and whether it must be audited."""

    allowed: bool
    reason: ReasonCode
    requires_audit: bool = False
    manager_grant_id: str | None = Field(default=None)

    _optional_identifiers = field_validator("manager_grant_id")(_optional_pseudonym)

    @model_validator(mode="after")
    def manager_grants_are_audited_allows(self) -> AccessDecision:
        if self.manager_grant_id is not None:
            if not self.allowed or not self.requires_audit:
                raise ValueError("a used manager grant must be an audited allow")
        return self


def _deny(reason: ReasonCode) -> AccessDecision:
    return AccessDecision(allowed=False, reason=reason, requires_audit=True)


def _usable_grants(
    principal: AccessPrincipal,
    grants: tuple[ManagerAccessGrant, ...],
    now: datetime,
) -> tuple[ManagerAccessGrant, ...]:
    if principal.role not in MANAGERIAL_ROLES:
        return ()
    return tuple(
        grant
        for grant in grants
        if grant.organization_id == principal.organization_id
        and grant.manager_user_id == principal.user_id
        and grant.is_active(now)
    )


def _active_subject_grant(
    principal: AccessPrincipal,
    resource: AccessResource,
    grants: tuple[ManagerAccessGrant, ...],
    now: datetime,
) -> ManagerAccessGrant | None:
    if resource.subject_user_id is None:
        return None
    for grant in _usable_grants(principal, grants, now):
        if grant.covers_subject(resource.subject_user_id):
            return grant
        if grant.covers_team(resource.team_id):
            return grant
    return None


def _active_team_grant(
    principal: AccessPrincipal,
    team_id: str,
    grants: tuple[ManagerAccessGrant, ...],
    now: datetime,
) -> ManagerAccessGrant | None:
    """Find a grant naming the whole team.

    A grant that names a single subject is deliberately not enough to read a
    cohort aggregate: the aggregate covers people the grant never mentioned.
    """

    for grant in _usable_grants(principal, grants, now):
        if grant.covers_team(team_id):
            return grant
    return None


def authorize(
    principal: AccessPrincipal,
    resource: AccessResource,
    action: AccessAction,
    *,
    now: datetime,
    grants: tuple[ManagerAccessGrant, ...] = (),
) -> AccessDecision:
    """Return the single authorization decision for one operation.

    Ordering matters. Tenant isolation is checked before anything else so that
    a cross-tenant probe cannot learn whether a subject, team, or envelope
    exists in the other tenant.
    """

    if principal.organization_id != resource.organization_id:
        return _deny(ReasonCode.CROSS_TENANT)
    if principal.membership_state is not MembershipState.ACTIVE:
        return _deny(ReasonCode.MEMBERSHIP_INACTIVE)
    if principal.client_state is not ApiClientState.ACTIVE:
        return _deny(ReasonCode.CLIENT_INACTIVE)
    if principal.device_state is not DeviceState.ACTIVE:
        return _deny(ReasonCode.DEVICE_INACTIVE)
    if REQUIRED_SCOPES[action] not in principal.client_scopes:
        return _deny(ReasonCode.SCOPE_MISSING)

    is_self = (
        resource.subject_user_id is not None
        and resource.subject_user_id == principal.user_id
    )

    if action is AccessAction.MANAGE_OWN_DEVICE:
        # Self-revocation only. Touching somebody else's device is directory
        # administration and takes the administrative path.
        if not is_self:
            return _deny(ReasonCode.SUBJECT_MISMATCH)
        return AccessDecision(
            allowed=True, reason=ReasonCode.SELF_ACCESS, requires_audit=True
        )

    if action is AccessAction.PUSH_SNAPSHOT:
        if not is_self:
            return _deny(ReasonCode.SUBJECT_MISMATCH)
        return AccessDecision(allowed=True, reason=ReasonCode.SELF_ACCESS)

    if action is AccessAction.PULL_DELTA:
        # Reaching the tenant log is not reading its rows. Each delivered item
        # is authorized separately with READ_SNAPSHOT.
        return AccessDecision(allowed=True, reason=ReasonCode.TENANT_MEMBERSHIP)

    if action is AccessAction.READ_SNAPSHOT:
        if is_self:
            return AccessDecision(allowed=True, reason=ReasonCode.SELF_ACCESS)
        if resource.visibility is VisibilityScope.ORGANIZATION:
            return AccessDecision(
                allowed=True, reason=ReasonCode.ORGANIZATION_VISIBILITY
            )
        if resource.visibility is VisibilityScope.TEAM:
            shares_team = (
                resource.team_id is not None
                and resource.team_id in principal.team_ids
            )
            if shares_team:
                return AccessDecision(
                    allowed=True, reason=ReasonCode.TEAM_VISIBILITY
                )
            grant = _active_subject_grant(principal, resource, grants, now)
            if grant is not None:
                return AccessDecision(
                    allowed=True,
                    reason=ReasonCode.MANAGER_GRANT,
                    requires_audit=True,
                    manager_grant_id=grant.grant_id,
                )
            return _deny(ReasonCode.TEAM_MEMBERSHIP_REQUIRED)
        grant = _active_subject_grant(principal, resource, grants, now)
        if grant is not None:
            return AccessDecision(
                allowed=True,
                reason=ReasonCode.MANAGER_GRANT,
                requires_audit=True,
                manager_grant_id=grant.grant_id,
            )
        return _deny(ReasonCode.INDIVIDUAL_VISIBILITY)

    if action is AccessAction.READ_TEAM_AGGREGATE:
        if resource.team_id is None:
            return _deny(ReasonCode.DEFAULT_DENY)
        if resource.team_id in principal.team_ids:
            return AccessDecision(allowed=True, reason=ReasonCode.TEAM_VISIBILITY)
        grant = _active_team_grant(principal, resource.team_id, grants, now)
        if grant is not None:
            return AccessDecision(
                allowed=True,
                reason=ReasonCode.MANAGER_GRANT,
                requires_audit=True,
                manager_grant_id=grant.grant_id,
            )
        return _deny(ReasonCode.MANAGER_GRANT_REQUIRED)

    if action is AccessAction.READ_AUDIT:
        if principal.role in ADMINISTRATIVE_ROLES:
            return AccessDecision(
                allowed=True,
                reason=ReasonCode.ADMINISTRATIVE_ROLE,
                requires_audit=True,
            )
        return _deny(ReasonCode.DEFAULT_DENY)

    if action is AccessAction.DELETE_SUBJECT_DATA:
        if is_self:
            return AccessDecision(
                allowed=True, reason=ReasonCode.SELF_ACCESS, requires_audit=True
            )
        if principal.role in ADMINISTRATIVE_ROLES:
            return AccessDecision(
                allowed=True,
                reason=ReasonCode.ADMINISTRATIVE_ROLE,
                requires_audit=True,
            )
        return _deny(ReasonCode.DEFAULT_DENY)

    if action is AccessAction.ADMINISTER_DIRECTORY:
        if principal.role in ADMINISTRATIVE_ROLES:
            return AccessDecision(
                allowed=True,
                reason=ReasonCode.ADMINISTRATIVE_ROLE,
                requires_audit=True,
            )
        return _deny(ReasonCode.DEFAULT_DENY)

    return _deny(ReasonCode.DEFAULT_DENY)


__all__ = [
    "REQUIRED_SCOPES",
    "AccessAction",
    "AccessDecision",
    "AccessPrincipal",
    "AccessResource",
    "authorize",
]
