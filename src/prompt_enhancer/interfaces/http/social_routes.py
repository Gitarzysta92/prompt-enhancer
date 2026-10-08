"""Default-off loopback routes for the private social development foundation.

Two deliberately separate factories live here.  The readiness router is a
read-only ledger and needs only the local auth dependency plus an explicitly
composed ``SocialReadiness``.  The mutation router cannot be built without both
a ``SocialService`` and a ``SocialPrincipalResolver``: every mutation resolves
its caller from the ``X-Social-Credential`` header through that resolver, so a
browser session cookie, the local API token, a JSON body field or a URL segment
can never name who is acting.  Bodies carry only the target, request or
conversation being operated on.

The tranche is intentionally narrow.  Message-envelope mutation stays absent
because no reviewed cryptography adapter exists, and file-transfer routes stay
absent because signaling and direct byte transport are unavailable.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Response
from pydantic import Field

from ...application.social.contracts import (
    MAX_FRIEND_REQUEST_LIFETIME,
    BlockRecord,
    Conversation,
    FriendRequest,
    SOCIAL_ID_PATTERN,
    SocialDeletionReceipt,
    SocialReadiness,
    VerifiedSocialPrincipal,
)
from ...application.social.errors import (
    SocialAuthorizationError,
    SocialConflictError,
    SocialCryptoUnavailableError,
    SocialError,
)
from ...application.social.ports import SocialPrincipalResolver
from ...application.social.service import SocialService
from ...domain import StrictModel


SOCIAL_CREDENTIAL_HEADER = "X-Social-Credential"
MIN_SOCIAL_CREDENTIAL_CHARACTERS = 32
MAX_SOCIAL_CREDENTIAL_CHARACTERS = 256
DEFAULT_FRIEND_REQUEST_LIFETIME_SECONDS = 7 * 24 * 60 * 60

_PRIVATE_HEADERS = {"Cache-Control": "no-store, private", "Pragma": "no-cache"}

SocialIdentifier = Annotated[str, Field(pattern=SOCIAL_ID_PATTERN.pattern)]


class FriendRequestCreate(StrictModel):
    """The account being asked; the requester is the resolved credential."""

    target_account_id: SocialIdentifier
    expires_in_seconds: int = Field(
        default=DEFAULT_FRIEND_REQUEST_LIFETIME_SECONDS,
        ge=60,
        le=int(MAX_FRIEND_REQUEST_LIFETIME.total_seconds()),
    )


class FriendRequestDecision(StrictModel):
    request_id: SocialIdentifier
    accept: bool


class RelationshipTarget(StrictModel):
    """Used for friend removal, block and unblock; no caller identity field."""

    target_account_id: SocialIdentifier


class DirectConversationCreate(StrictModel):
    friend_account_id: SocialIdentifier


class RelationshipChangeReceipt(StrictModel):
    removed: bool


def _reject(error: SocialError) -> HTTPException:
    """Map a closed reason code to a status without exception text.

    Authorization, unknown targets and blocks share one 403 class so the API is
    not an enumeration oracle; conflicts answer 409 and the fail-closed crypto
    adapter answers 503.
    """

    if isinstance(error, SocialAuthorizationError):
        return HTTPException(status_code=403, detail={"code": error.reason.value})
    if isinstance(error, SocialConflictError):
        return HTTPException(status_code=409, detail={"code": error.reason.value})
    if isinstance(error, SocialCryptoUnavailableError):
        return HTTPException(status_code=503, detail={"code": error.reason.value})
    return HTTPException(status_code=403, detail={"code": "default_deny"})


def _prevent_private_caching(response: Response) -> None:
    for name, value in _PRIVATE_HEADERS.items():
        response.headers[name] = value


def create_social_readiness_router(
    require_local_auth: Callable[..., None],
    readiness: SocialReadiness,
) -> APIRouter:
    """Expose the honest capability ledger; it grants no social authority."""

    if not isinstance(readiness, SocialReadiness):
        raise TypeError("social readiness router requires a SocialReadiness receipt")
    router = APIRouter(
        prefix="/v1/social",
        tags=["social-readiness"],
        dependencies=[Depends(require_local_auth), Depends(_prevent_private_caching)],
    )

    @router.get("/readiness", response_model=SocialReadiness)
    def social_readiness() -> SocialReadiness:
        return readiness

    return router


def create_social_mutation_router(
    require_local_auth: Callable[..., None],
    service: SocialService,
    resolver: SocialPrincipalResolver,
) -> APIRouter:
    """Build the narrow relationship-mutation router.

    Both arguments are mandatory: without a resolver there is no way to know
    who is calling, so no route exists rather than one that trusts a body.
    """

    if service is None or not isinstance(service, SocialService):
        raise TypeError("social mutation router requires a SocialService")
    if resolver is None or not callable(getattr(resolver, "resolve", None)):
        raise TypeError("social mutation router requires a SocialPrincipalResolver")

    def verified_principal(
        credential: Annotated[
            str | None, Header(alias=SOCIAL_CREDENTIAL_HEADER)
        ] = None,
    ) -> VerifiedSocialPrincipal:
        rejected = HTTPException(status_code=401, detail={"code": "credential_rejected"})
        if credential is None or not (
            MIN_SOCIAL_CREDENTIAL_CHARACTERS
            <= len(credential)
            <= MAX_SOCIAL_CREDENTIAL_CHARACTERS
        ):
            raise rejected
        try:
            principal = resolver.resolve(credential)
        except Exception:  # noqa: BLE001 - a failing resolver must fail closed
            raise rejected from None
        if not isinstance(principal, VerifiedSocialPrincipal):
            raise rejected
        return principal

    router = APIRouter(
        prefix="/v1/social",
        tags=["social"],
        dependencies=[Depends(require_local_auth), Depends(_prevent_private_caching)],
    )
    caller = Depends(verified_principal)

    @router.post("/friend-requests", response_model=FriendRequest, status_code=201)
    def create_friend_request(
        payload: Annotated[FriendRequestCreate, Body()],
        principal: VerifiedSocialPrincipal = caller,
    ) -> FriendRequest:
        expires_at = service.clock() + timedelta(seconds=payload.expires_in_seconds)
        try:
            return service.request_friend(
                principal, payload.target_account_id, expires_at=expires_at
            )
        except SocialError as error:
            raise _reject(error) from None

    @router.post("/friend-requests/decisions", response_model=FriendRequest)
    def decide_friend_request(
        payload: Annotated[FriendRequestDecision, Body()],
        principal: VerifiedSocialPrincipal = caller,
    ) -> FriendRequest:
        try:
            return service.decide_friend_request(
                principal, payload.request_id, accept=payload.accept
            )
        except SocialError as error:
            raise _reject(error) from None

    @router.post("/friends/removals", response_model=RelationshipChangeReceipt)
    def remove_friend(
        payload: Annotated[RelationshipTarget, Body()],
        principal: VerifiedSocialPrincipal = caller,
    ) -> RelationshipChangeReceipt:
        try:
            removed = service.remove_friend(principal, payload.target_account_id)
        except SocialError as error:
            raise _reject(error) from None
        return RelationshipChangeReceipt(removed=removed)

    @router.post("/blocks", response_model=BlockRecord, status_code=201)
    def block_account(
        payload: Annotated[RelationshipTarget, Body()],
        principal: VerifiedSocialPrincipal = caller,
    ) -> BlockRecord:
        try:
            return service.block_account(principal, payload.target_account_id)
        except SocialError as error:
            raise _reject(error) from None

    @router.post("/blocks/removals", response_model=RelationshipChangeReceipt)
    def unblock_account(
        payload: Annotated[RelationshipTarget, Body()],
        principal: VerifiedSocialPrincipal = caller,
    ) -> RelationshipChangeReceipt:
        try:
            removed = service.unblock_account(principal, payload.target_account_id)
        except SocialError as error:
            raise _reject(error) from None
        return RelationshipChangeReceipt(removed=removed)

    @router.post("/direct-conversations", response_model=Conversation, status_code=201)
    def create_direct_conversation(
        payload: Annotated[DirectConversationCreate, Body()],
        principal: VerifiedSocialPrincipal = caller,
    ) -> Conversation:
        try:
            return service.create_direct_conversation(
                principal, payload.friend_account_id
            )
        except SocialError as error:
            raise _reject(error) from None

    @router.post("/account-metadata-deletions", response_model=SocialDeletionReceipt)
    def delete_own_account_metadata(
        principal: VerifiedSocialPrincipal = caller,
    ) -> SocialDeletionReceipt:
        """Erase the caller's own metadata; the subject is never a parameter."""

        try:
            return service.delete_account_metadata(principal)
        except SocialError as error:
            raise _reject(error) from None

    return router


__all__ = [
    "DEFAULT_FRIEND_REQUEST_LIFETIME_SECONDS",
    "MAX_SOCIAL_CREDENTIAL_CHARACTERS",
    "MIN_SOCIAL_CREDENTIAL_CHARACTERS",
    "SOCIAL_CREDENTIAL_HEADER",
    "DirectConversationCreate",
    "FriendRequestCreate",
    "FriendRequestDecision",
    "RelationshipChangeReceipt",
    "RelationshipTarget",
    "create_social_mutation_router",
    "create_social_readiness_router",
]
