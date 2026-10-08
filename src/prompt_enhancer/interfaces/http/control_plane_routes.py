"""Loopback development routes for the team control plane.

These routes are disabled by default and are mounted only when the operator
opts in *and* a principal resolver is configured. They reuse the local API's
existing authentication, loopback host check, origin check, and no-store cache
policy; they add no listener, no CORS relaxation, and no remote destination.

No request body carries an identity. The tenant, member, client, and device all
come from the credential header through the resolver dependency, so there is no
field a caller could use to name somebody else. Bodies carry only what is being
published or asked for.

Reads are expressed as POST commands with a JSON body so that the little
identity that does travel — the team or subject being asked about — never
appears in a URL, where it would land in history, proxy logs, and referrers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Response
from pydantic import Field, SecretStr

from ...application.control_plane import (
    DEFAULT_DELTA_PAGE_ITEMS,
    MAX_AUDIT_PAGE_ITEMS,
    MAX_CREDENTIAL_CHARACTERS,
    MAX_DELTA_PAGE_ITEMS,
    MIN_CREDENTIAL_CHARACTERS,
    AuditEvent,
    AuthorizationDeniedError,
    ControlPlaneReadiness,
    ControlPlaneService,
    CursorError,
    DeletionReceipt,
    DeltaPage,
    DirectoryNotFoundError,
    EntitlementError,
    EnvelopeConflictError,
    EnvelopeIdentifier,
    EnvelopeRejectedError,
    EnvelopeReplayedError,
    ManagerAccessGrant,
    PrincipalResolver,
    PushReceipt,
    ReportingBucket,
    SignedSnapshotEnvelope,
    TeamAggregate,
    VerifiedIdentity,
)
from ...domain import PSEUDONYM_PATTERN, StrictModel


CONTROL_PLANE_CREDENTIAL_HEADER = "X-Control-Plane-Credential"

Pseudonym = Annotated[str, Field(pattern=PSEUDONYM_PATTERN.pattern)]


class SnapshotPushRequest(StrictModel):
    """One signed envelope with no principal identity fields."""

    signed_envelope: SignedSnapshotEnvelope


class DeltaPullRequest(StrictModel):
    """An acknowledgement of the last processed offer and a page size.

    Omitting ``acknowledge_through`` redelivers the current unacknowledged
    window. The number is accepted only if this credential's client/device was
    previously offered it; identity never comes from this body.
    """

    acknowledge_through: int | None = Field(default=None, ge=0)
    limit: int = Field(
        default=DEFAULT_DELTA_PAGE_ITEMS, ge=1, le=MAX_DELTA_PAGE_ITEMS
    )


class TeamAggregateRequest(StrictModel):
    """A team and one canonical reporting bucket. Arbitrary windows are absent."""

    team_id: Pseudonym
    period: ReportingBucket


class SubjectDeletionRequest(StrictModel):
    """Whose data to delete. Omitting the subject deletes the caller's own."""

    subject_user_id: Pseudonym | None = None


class AuditQueryRequest(StrictModel):
    limit: int = Field(default=50, ge=1, le=MAX_AUDIT_PAGE_ITEMS)


class ManagerGrantRevocationRequest(StrictModel):
    grant_id: Pseudonym


def _reject(error: Exception) -> HTTPException:
    """Map a control-plane error to a status and its closed reason code.

    A missing tenant, team, or device answers 403 rather than 404 so the API
    cannot be used to enumerate what exists in somebody else's tenant.
    """

    if isinstance(error, (AuthorizationDeniedError, DirectoryNotFoundError)):
        return HTTPException(status_code=403, detail={"code": error.reason.value})
    if isinstance(error, EntitlementError):
        return HTTPException(status_code=402, detail={"code": error.reason.value})
    if isinstance(error, (CursorError, EnvelopeConflictError, EnvelopeReplayedError)):
        return HTTPException(status_code=409, detail={"code": error.reason.value})
    if isinstance(error, EnvelopeRejectedError):
        return HTTPException(status_code=400, detail={"code": error.reason.value})
    raise error


_HANDLED = (
    AuthorizationDeniedError,
    DirectoryNotFoundError,
    EntitlementError,
    EnvelopeConflictError,
    EnvelopeRejectedError,
    EnvelopeReplayedError,
    CursorError,
)


def create_control_plane_router(
    require_local_auth: Callable[..., None],
    service: ControlPlaneService,
    resolver: PrincipalResolver,
) -> APIRouter:
    """Build the development control-plane router.

    The resolver is a required argument: there is no configuration in which
    these routes accept a request without verifying a credential first. The
    caller is responsible for mounting this only when the explicit opt-in
    setting is enabled.
    """

    def prevent_private_caching(response: Response) -> None:
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"

    def verified_identity(
        credential: Annotated[
            str | None, Header(alias=CONTROL_PLANE_CREDENTIAL_HEADER)
        ] = None,
    ) -> VerifiedIdentity:
        """Resolve the caller from the credential header, or refuse."""

        if credential is None or not (
            MIN_CREDENTIAL_CHARACTERS <= len(credential) <= MAX_CREDENTIAL_CHARACTERS
        ):
            raise HTTPException(
                status_code=401, detail={"code": "credential_rejected"}
            )
        identity = resolver.resolve(SecretStr(credential))
        if identity is None:
            raise HTTPException(
                status_code=401, detail={"code": "credential_rejected"}
            )
        return identity

    router = APIRouter(
        prefix="/v1/control-plane",
        tags=["control-plane"],
        dependencies=[
            Depends(require_local_auth),
            Depends(prevent_private_caching),
        ],
    )
    # The identity dependency is attached as a default value rather than an
    # annotation alias: this module defers annotation evaluation, and a local
    # alias would not resolve when FastAPI reads the signature.
    caller = Depends(verified_identity)

    @router.get("/readiness", response_model=ControlPlaneReadiness)
    def readiness() -> ControlPlaneReadiness:
        """Report the deployment profile and every unfinished prerequisite."""

        return service.readiness()

    @router.post(
        "/envelope-identifiers",
        response_model=EnvelopeIdentifier,
        responses={
            401: {"description": "Credential rejected"},
            402: {"description": "Tenant not entitled to synchronize"},
            403: {"description": "Default-deny authorization"},
        },
    )
    def issue_envelope_identifier(
        identity: VerifiedIdentity = caller,
    ) -> EnvelopeIdentifier:
        """Reserve one server-issued identifier before signing an envelope."""

        try:
            return service.issue_envelope_identifier(identity)
        except _HANDLED as error:
            raise _reject(error) from None

    @router.post(
        "/snapshots",
        response_model=PushReceipt,
        responses={
            400: {"description": "Signature, binding, or freshness"},
            401: {"description": "Credential rejected"},
            402: {"description": "Tenant not entitled to synchronize"},
            403: {"description": "Default-deny authorization"},
            409: {"description": "Replayed or conflicting envelope identifier"},
        },
    )
    def push_snapshot(
        payload: Annotated[SnapshotPushRequest, Body()],
        identity: VerifiedIdentity = caller,
    ) -> PushReceipt:
        """Accept one signed, allowlisted snapshot at most once, ever."""

        try:
            return service.push(identity, payload.signed_envelope)
        except _HANDLED as error:
            raise _reject(error) from None

    @router.post(
        "/deltas",
        response_model=DeltaPage,
        responses={
            401: {"description": "Credential rejected"},
            402: {"description": "Tenant not entitled to synchronize"},
            403: {"description": "Default-deny authorization"},
        },
    )
    def pull_deltas(
        payload: Annotated[DeltaPullRequest, Body()],
        identity: VerifiedIdentity = caller,
    ) -> DeltaPage:
        """Return the next ordered page the caller is allowed to read."""

        try:
            return service.pull(
                identity,
                acknowledge_through=payload.acknowledge_through,
                limit=payload.limit,
            )
        except _HANDLED as error:
            raise _reject(error) from None

    @router.post(
        "/team-aggregates",
        response_model=TeamAggregate,
        responses={
            401: {"description": "Credential rejected"},
            402: {"description": "Tenant not entitled to synchronize"},
            403: {"description": "Default-deny authorization"},
        },
    )
    def read_team_aggregate(
        payload: Annotated[TeamAggregateRequest, Body()],
        identity: VerifiedIdentity = caller,
    ) -> TeamAggregate:
        """Return a cohort result for one canonical bucket, or a suppression."""

        try:
            return service.team_aggregate(
                identity, payload.team_id, period=payload.period
            )
        except _HANDLED as error:
            raise _reject(error) from None

    @router.post(
        "/deletions",
        response_model=DeletionReceipt,
        responses={
            401: {"description": "Credential rejected"},
            403: {"description": "Default-deny authorization"},
        },
    )
    def delete_subject_data(
        payload: Annotated[SubjectDeletionRequest, Body()],
        identity: VerifiedIdentity = caller,
    ) -> DeletionReceipt:
        """Delete one subject's snapshots and publish ordered tombstones."""

        subject = payload.subject_user_id or identity.user_id
        try:
            return service.delete_subject_data(identity, subject)
        except _HANDLED as error:
            raise _reject(error) from None

    @router.post(
        "/manager-grant-revocations",
        response_model=ManagerAccessGrant,
        responses={
            401: {"description": "Credential rejected"},
            403: {"description": "Administrative role required"},
        },
    )
    def revoke_manager_grant(
        payload: Annotated[ManagerGrantRevocationRequest, Body()],
        identity: VerifiedIdentity = caller,
    ) -> ManagerAccessGrant:
        try:
            return service.revoke_manager_grant(identity, payload.grant_id)
        except _HANDLED as error:
            raise _reject(error) from None

    @router.post(
        "/audit-queries",
        response_model=tuple[AuditEvent, ...],
        responses={
            401: {"description": "Credential rejected"},
            403: {"description": "Administrative role required"},
        },
    )
    def read_audit(
        payload: Annotated[AuditQueryRequest, Body()],
        identity: VerifiedIdentity = caller,
    ) -> tuple[AuditEvent, ...]:
        """Return recent tenant audit evidence for an administrator."""

        try:
            return service.read_audit(identity, limit=payload.limit)
        except _HANDLED as error:
            raise _reject(error) from None

    return router


__all__ = [
    "CONTROL_PLANE_CREDENTIAL_HEADER",
    "AuditQueryRequest",
    "DeltaPullRequest",
    "ManagerGrantRevocationRequest",
    "SnapshotPushRequest",
    "SubjectDeletionRequest",
    "TeamAggregateRequest",
    "create_control_plane_router",
]
