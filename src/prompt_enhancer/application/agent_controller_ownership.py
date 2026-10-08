"""Durable, content-free ownership for project-scoped external controllers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from pydantic import Field, model_validator

from ..domain import StrictModel


AGENT_CONTROLLER_OWNERSHIP_CONTRACT_VERSION = "agent-controller-ownership.v1"
AGENT_CONTROLLER_OWNERSHIP_LIST_CONTRACT_VERSION = (
    "agent-controller-ownership-list.v1"
)
AGENT_CONTROLLER_RESTART_RECONCILIATION_CONTRACT_VERSION = (
    "agent-controller-restart-reconciliation.v1"
)
AGENT_CONTROLLER_HANDOFF_SECONDS = 600
MAX_AGENT_CONTROLLER_OWNERSHIPS = 128
_ID_PATTERN = r"^[0-9a-f]{32}$"

AgentControllerOwnershipState = Literal[
    "claimed",
    "running",
    "waiting_native_approval",
    "reconnecting",
    "submission_uncertain",
    "stopping",
    "stop_uncertain",
    "cleanup_unconfirmed",
    "revoked",
]
AgentControllerOperation = Literal[
    "turn",
    "write_proposal",
    "transaction_proposal",
    "lifecycle_proposal",
]
AgentControllerClientKind = Literal["codex", "claude", "other"]


class AgentControllerOwnershipError(RuntimeError):
    """A content-free ownership failure safe for local contracts."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AgentControllerHandoff(StrictModel):
    target_connection_id: str = Field(pattern=_ID_PATTERN)
    target_label: str = Field(min_length=1, max_length=80)
    target_client_kind: AgentControllerClientKind
    offered_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def coherent_window(self) -> "AgentControllerHandoff":
        if self.expires_at <= self.offered_at:
            raise ValueError("controller handoff expiry must follow its offer")
        return self


class AgentControllerOwnership(StrictModel):
    """Exact current owner of one live Agent chat operation."""

    contract_version: Literal["agent-controller-ownership.v1"] = (
        AGENT_CONTROLLER_OWNERSHIP_CONTRACT_VERSION
    )
    project_id: str = Field(pattern=_ID_PATTERN)
    project_name: str = Field(min_length=1, max_length=120)
    session_id: str = Field(pattern=_ID_PATTERN)
    session_title: str = Field(min_length=1, max_length=120)
    owner_connection_id: str = Field(pattern=_ID_PATTERN)
    owner_label: str = Field(min_length=1, max_length=80)
    owner_client_kind: AgentControllerClientKind
    operation: AgentControllerOperation
    state: AgentControllerOwnershipState
    cursor: int = Field(strict=True, ge=0)
    last_seq: int = Field(strict=True, ge=0)
    approval_pending: bool
    ownership_started_at: datetime
    owner_since: datetime
    updated_at: datetime
    revision: int = Field(strict=True, ge=1)
    handoff: AgentControllerHandoff | None = None
    native_approval_inherited: Literal[False] = False

    @model_validator(mode="after")
    def coherent_ownership(self) -> "AgentControllerOwnership":
        if self.cursor > self.last_seq:
            raise ValueError("controller cursor cannot exceed its observed sequence")
        if not (
            self.ownership_started_at <= self.owner_since <= self.updated_at
        ):
            raise ValueError("controller ownership timestamps are incoherent")
        if self.state == "waiting_native_approval" and not self.approval_pending:
            raise ValueError("waiting controller ownership needs pending approval truth")
        if self.state in {"claimed", "running"} and self.approval_pending:
            raise ValueError("active controller phase cannot hide pending approval")
        if self.state == "revoked" and self.handoff is not None:
            raise ValueError("revoked ownership cannot retain a handoff")
        if self.handoff is not None:
            if self.handoff.target_connection_id == self.owner_connection_id:
                raise ValueError("controller handoff cannot target its owner")
            if self.handoff.offered_at < self.owner_since:
                raise ValueError("controller handoff predates the current owner")
        return self


class AgentControllerOwnershipList(StrictModel):
    contract_version: Literal["agent-controller-ownership-list.v1"] = (
        AGENT_CONTROLLER_OWNERSHIP_LIST_CONTRACT_VERSION
    )
    ownerships: tuple[AgentControllerOwnership, ...]
    active_count: int = Field(strict=True, ge=0, le=MAX_AGENT_CONTROLLER_OWNERSHIPS)

    @model_validator(mode="after")
    def exact_count(self) -> "AgentControllerOwnershipList":
        if self.active_count != len(self.ownerships):
            raise ValueError("controller ownership count is incoherent")
        return self


class OfferAgentControllerHandoff(StrictModel):
    session_id: str = Field(pattern=_ID_PATTERN)
    target_connection_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)


class AcceptAgentControllerHandoff(StrictModel):
    session_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)


class ReleaseAgentControllerOwnership(StrictModel):
    session_id: str = Field(pattern=_ID_PATTERN)
    expected_revision: int = Field(strict=True, ge=1)


class AgentControllerOwnershipReleaseReceipt(StrictModel):
    contract_version: Literal["agent-controller-ownership.v1"] = (
        AGENT_CONTROLLER_OWNERSHIP_CONTRACT_VERSION
    )
    project_id: str = Field(pattern=_ID_PATTERN)
    session_id: str = Field(pattern=_ID_PATTERN)
    released_connection_id: str = Field(pattern=_ID_PATTERN)
    released_revision: int = Field(strict=True, ge=1)
    released_at: datetime
    released_by: Literal["owner", "native"]
    session_settled: Literal[True] = True
    native_approval_inherited: Literal[False] = False


class AgentControllerRestartReconciliationReceipt(StrictModel):
    """Content-free evidence that stale process authority was removed."""

    contract_version: Literal["agent-controller-restart-reconciliation.v1"] = (
        AGENT_CONTROLLER_RESTART_RECONCILIATION_CONTRACT_VERSION
    )
    reconciled_at: datetime
    observed_ownerships: int = Field(
        strict=True,
        ge=0,
        le=MAX_AGENT_CONTROLLER_OWNERSHIPS,
    )
    live_ownerships_preserved: int = Field(
        strict=True,
        ge=0,
        le=MAX_AGENT_CONTROLLER_OWNERSHIPS,
    )
    non_live_submission_uncertain: int = Field(
        strict=True,
        ge=0,
        le=MAX_AGENT_CONTROLLER_OWNERSHIPS,
    )
    non_live_cleanup_unconfirmed: int = Field(
        strict=True,
        ge=0,
        le=MAX_AGENT_CONTROLLER_OWNERSHIPS,
    )
    non_live_revoked: int = Field(
        strict=True,
        ge=0,
        le=MAX_AGENT_CONTROLLER_OWNERSHIPS,
    )
    changed_ownerships: int = Field(
        strict=True,
        ge=0,
        le=MAX_AGENT_CONTROLLER_OWNERSHIPS,
    )
    native_approvals_cleared: int = Field(
        strict=True,
        ge=0,
        le=MAX_AGENT_CONTROLLER_OWNERSHIPS,
    )
    handoffs_cleared: int = Field(
        strict=True,
        ge=0,
        le=MAX_AGENT_CONTROLLER_OWNERSHIPS,
    )
    stale_native_approval_retained: Literal[False] = False
    stale_handoff_retained: Literal[False] = False

    @model_validator(mode="after")
    def coherent_counts(self) -> "AgentControllerRestartReconciliationReceipt":
        if (
            self.reconciled_at.tzinfo is None
            or self.reconciled_at.utcoffset() is None
        ):
            raise ValueError("controller restart reconciliation time is naive")
        non_live = (
            self.non_live_submission_uncertain
            + self.non_live_cleanup_unconfirmed
            + self.non_live_revoked
        )
        if self.observed_ownerships != self.live_ownerships_preserved + non_live:
            raise ValueError("controller restart reconciliation counts are incoherent")
        if any(
            value > non_live
            for value in (
                self.changed_ownerships,
                self.native_approvals_cleared,
                self.handoffs_cleared,
            )
        ):
            raise ValueError("controller restart reconciliation exceeds stale scope")
        return self


class AgentControllerOwnershipRepository(Protocol):
    def claim_controller_ownership(
        self,
        *,
        connection_id: str,
        project_id: str,
        session_id: str,
        operation: AgentControllerOperation,
        claimed_at: datetime,
    ) -> AgentControllerOwnership: ...

    def get_controller_ownership(
        self,
        session_id: str,
        *,
        now: datetime,
    ) -> AgentControllerOwnership | None: ...

    def list_controller_ownerships(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> Sequence[AgentControllerOwnership]: ...

    def update_controller_ownership(
        self,
        session_id: str,
        *,
        owner_connection_id: str,
        state: AgentControllerOwnershipState,
        cursor: int,
        last_seq: int,
        approval_pending: bool,
        updated_at: datetime,
    ) -> AgentControllerOwnership: ...

    def offer_controller_handoff(
        self,
        session_id: str,
        *,
        owner_connection_id: str,
        target_connection_id: str,
        expected_revision: int,
        offered_at: datetime,
        expires_at: datetime,
    ) -> AgentControllerOwnership: ...

    def accept_controller_handoff(
        self,
        session_id: str,
        *,
        target_connection_id: str,
        expected_revision: int,
        accepted_at: datetime,
    ) -> AgentControllerOwnership: ...

    def release_controller_ownership(
        self,
        session_id: str,
        *,
        owner_connection_id: str | None,
        expected_revision: int | None,
        released_at: datetime,
        released_by: Literal["owner", "native"],
    ) -> AgentControllerOwnershipReleaseReceipt: ...

    def reconcile_controller_ownerships_after_restart(
        self,
        *,
        live_session_ids: Sequence[str],
        reconciled_at: datetime,
    ) -> AgentControllerRestartReconciliationReceipt: ...


class AgentControllerOwnershipService:
    """Coordinate one exact owner without storing conversation content."""

    def __init__(
        self,
        repository: AgentControllerOwnershipRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("controller ownership clock must be timezone-aware")
        return value.astimezone(UTC)

    def claim(
        self,
        *,
        connection_id: str,
        project_id: str,
        session_id: str,
        operation: AgentControllerOperation,
    ) -> AgentControllerOwnership:
        return self._repository.claim_controller_ownership(
            connection_id=connection_id,
            project_id=project_id,
            session_id=session_id,
            operation=operation,
            claimed_at=self._now(),
        )

    def get(self, session_id: str) -> AgentControllerOwnership | None:
        return self._repository.get_controller_ownership(
            session_id,
            now=self._now(),
        )

    def list(self) -> AgentControllerOwnershipList:
        ownerships = tuple(
            self._repository.list_controller_ownerships(
                now=self._now(),
                limit=MAX_AGENT_CONTROLLER_OWNERSHIPS,
            )
        )
        return AgentControllerOwnershipList(
            ownerships=ownerships,
            active_count=len(ownerships),
        )

    def update(
        self,
        session_id: str,
        *,
        owner_connection_id: str,
        state: AgentControllerOwnershipState,
        cursor: int,
        last_seq: int,
        approval_pending: bool,
    ) -> AgentControllerOwnership:
        return self._repository.update_controller_ownership(
            session_id,
            owner_connection_id=owner_connection_id,
            state=state,
            cursor=cursor,
            last_seq=last_seq,
            approval_pending=approval_pending,
            updated_at=self._now(),
        )

    def reconcile_after_restart(
        self,
        *,
        live_session_ids: Sequence[str],
    ) -> AgentControllerRestartReconciliationReceipt:
        return self._repository.reconcile_controller_ownerships_after_restart(
            live_session_ids=live_session_ids,
            reconciled_at=self._now(),
        )

    def offer(
        self,
        *,
        owner_connection_id: str,
        command: OfferAgentControllerHandoff,
    ) -> AgentControllerOwnership:
        now = self._now()
        return self._repository.offer_controller_handoff(
            command.session_id,
            owner_connection_id=owner_connection_id,
            target_connection_id=command.target_connection_id,
            expected_revision=command.expected_revision,
            offered_at=now,
            expires_at=now + timedelta(seconds=AGENT_CONTROLLER_HANDOFF_SECONDS),
        )

    def accept(
        self,
        *,
        target_connection_id: str,
        command: AcceptAgentControllerHandoff,
    ) -> AgentControllerOwnership:
        return self._repository.accept_controller_handoff(
            command.session_id,
            target_connection_id=target_connection_id,
            expected_revision=command.expected_revision,
            accepted_at=self._now(),
        )

    def release_owner(
        self,
        *,
        owner_connection_id: str,
        session_id: str,
        expected_revision: int | None = None,
    ) -> AgentControllerOwnershipReleaseReceipt:
        return self._repository.release_controller_ownership(
            session_id,
            owner_connection_id=owner_connection_id,
            expected_revision=expected_revision,
            released_at=self._now(),
            released_by="owner",
        )

    def release_native(
        self,
        command: ReleaseAgentControllerOwnership,
        *,
        session_settled: bool,
    ) -> AgentControllerOwnershipReleaseReceipt:
        if not session_settled:
            raise AgentControllerOwnershipError(
                "agent_controller_session_not_settled"
            )
        return self._repository.release_controller_ownership(
            command.session_id,
            owner_connection_id=None,
            expected_revision=command.expected_revision,
            released_at=self._now(),
            released_by="native",
        )


__all__ = (
    "AGENT_CONTROLLER_HANDOFF_SECONDS",
    "AGENT_CONTROLLER_OWNERSHIP_CONTRACT_VERSION",
    "AGENT_CONTROLLER_OWNERSHIP_LIST_CONTRACT_VERSION",
    "AGENT_CONTROLLER_RESTART_RECONCILIATION_CONTRACT_VERSION",
    "MAX_AGENT_CONTROLLER_OWNERSHIPS",
    "AcceptAgentControllerHandoff",
    "AgentControllerClientKind",
    "AgentControllerHandoff",
    "AgentControllerOperation",
    "AgentControllerOwnership",
    "AgentControllerOwnershipError",
    "AgentControllerOwnershipList",
    "AgentControllerOwnershipReleaseReceipt",
    "AgentControllerRestartReconciliationReceipt",
    "AgentControllerOwnershipRepository",
    "AgentControllerOwnershipService",
    "AgentControllerOwnershipState",
    "OfferAgentControllerHandoff",
    "ReleaseAgentControllerOwnership",
)
