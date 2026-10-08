"""Explicit, content-free task lifecycle commands and query contracts.

Lifecycle is intentionally separate from discovery, immutable task revisions,
and analysis execution.  The only writer is this explicit local-user command
service; model output and analysis completion have no lifecycle mutation port.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import Field, field_validator, model_validator

from ..domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, StrictModel


TASK_LIFECYCLE_COMMAND_SCHEMA_VERSION = "task-lifecycle-command-v1"
TASK_LIFECYCLE_SOURCE = "explicit_local_user"
TASK_LIFECYCLE_ACTOR_SCOPE = "local_user"


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("lifecycle identifiers must be safe pseudonyms")
    return value


def _optional_pseudonym(value: str | None) -> str | None:
    return None if value is None else _pseudonym(value)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("lifecycle timestamps must include a timezone")
    return value.astimezone(UTC)


class TaskLifecycleState(StrEnum):
    """Authoritative states justified by the current local workflow."""

    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class TaskLifecycleEventKind(StrEnum):
    TRANSITION = "transition"
    CORRECTION = "correction"


class TaskLifecycleEventRecord(StrictModel):
    """One immutable explicit-user lifecycle receipt."""

    event_id: str
    task_id: str
    task_revision: int = Field(ge=1)
    sequence: int = Field(ge=1)
    event_kind: TaskLifecycleEventKind
    prior_state: TaskLifecycleState | None
    resulting_state: TaskLifecycleState | None
    previous_event_id: str | None
    supersedes_event_id: str | None
    task_input_fingerprint: str
    command_schema_version: str
    source: str
    actor_scope: str
    request_fingerprint: str
    idempotency_key_hash: str
    created_at: datetime

    _validate_ids = field_validator(
        "event_id",
        "task_id",
        "task_input_fingerprint",
        "request_fingerprint",
        "idempotency_key_hash",
    )(_pseudonym)
    _validate_optional_ids = field_validator(
        "previous_event_id", "supersedes_event_id"
    )(_optional_pseudonym)
    _validate_created_at = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def validate_receipt_shape(self) -> TaskLifecycleEventRecord:
        if self.command_schema_version != TASK_LIFECYCLE_COMMAND_SCHEMA_VERSION:
            raise ValueError("lifecycle command schema is unsupported")
        if self.source != TASK_LIFECYCLE_SOURCE:
            raise ValueError("lifecycle source must be an explicit local user")
        if self.actor_scope != TASK_LIFECYCLE_ACTOR_SCOPE:
            raise ValueError("lifecycle actor scope is unsupported")
        if self.sequence == 1 and self.previous_event_id is not None:
            raise ValueError("the first lifecycle receipt cannot have a predecessor")
        if self.sequence > 1 and self.previous_event_id is None:
            raise ValueError("later lifecycle receipts require a predecessor")
        if self.event_kind is TaskLifecycleEventKind.TRANSITION:
            if self.supersedes_event_id is not None or self.resulting_state is None:
                raise ValueError("transition receipts cannot supersede and require a state")
        elif (
            self.supersedes_event_id is None
            or self.supersedes_event_id != self.previous_event_id
        ):
            raise ValueError("correction receipts must supersede the current predecessor")
        return self


class TaskLifecycleSnapshot(StrictModel):
    """Exact derived head plus a bounded immutable event page."""

    task_id: str
    task_revision: int = Field(ge=1)
    current_task_revision: int = Field(ge=1)
    is_current_revision: bool
    current_state: TaskLifecycleState | None
    head_event_id: str | None
    event_count: int = Field(ge=0)
    prior_revision_event_count: int = Field(ge=0)
    events: tuple[TaskLifecycleEventRecord, ...]
    events_limit: int = Field(ge=1, le=100)
    events_offset: int = Field(ge=0)

    _validate_task_id = field_validator("task_id")(_pseudonym)
    _validate_head = field_validator("head_event_id")(_optional_pseudonym)

    @model_validator(mode="after")
    def validate_snapshot(self) -> TaskLifecycleSnapshot:
        if self.is_current_revision != (
            self.task_revision == self.current_task_revision
        ):
            raise ValueError("lifecycle current-revision flag is inconsistent")
        if self.event_count == 0:
            if self.current_state is not None or self.head_event_id is not None:
                raise ValueError("an empty lifecycle must remain unknown")
        elif self.head_event_id is None:
            raise ValueError("a non-empty lifecycle requires a head receipt")
        if len(self.events) > self.events_limit:
            raise ValueError("lifecycle event page exceeds its declared limit")
        if any(
            event.task_id != self.task_id
            or event.task_revision != self.task_revision
            for event in self.events
        ):
            raise ValueError("lifecycle event page crosses revision identity")
        if tuple(event.sequence for event in self.events) != tuple(
            sorted(event.sequence for event in self.events)
        ):
            raise ValueError("lifecycle event page must be ordered")
        return self


class TaskLifecycleTransitionCommand(StrictModel):
    task_id: str
    task_revision: int = Field(ge=1)
    expected_head_event_id: str | None
    state: TaskLifecycleState

    _validate_task_id = field_validator("task_id")(_pseudonym)
    _validate_head = field_validator("expected_head_event_id")(_optional_pseudonym)


class TaskLifecycleCorrectionCommand(StrictModel):
    task_id: str
    task_revision: int = Field(ge=1)
    expected_head_event_id: str
    supersedes_event_id: str

    _validate_ids = field_validator(
        "task_id", "expected_head_event_id", "supersedes_event_id"
    )(_pseudonym)

    @model_validator(mode="after")
    def require_current_target(self) -> TaskLifecycleCorrectionCommand:
        if self.expected_head_event_id != self.supersedes_event_id:
            raise ValueError("a correction must target the expected current head")
        return self


class TaskLifecycleEventDraft(StrictModel):
    event_id: str
    task_id: str
    task_revision: int = Field(ge=1)
    event_kind: TaskLifecycleEventKind
    requested_state: TaskLifecycleState | None
    expected_head_event_id: str | None
    supersedes_event_id: str | None
    command_schema_version: str
    source: str
    actor_scope: str
    request_fingerprint: str
    idempotency_key_hash: str
    created_at: datetime

    _validate_ids = field_validator(
        "event_id", "task_id", "request_fingerprint", "idempotency_key_hash"
    )(_pseudonym)
    _validate_optional_ids = field_validator(
        "expected_head_event_id", "supersedes_event_id"
    )(_optional_pseudonym)
    _validate_created_at = field_validator("created_at")(_utc)

    @model_validator(mode="after")
    def validate_draft(self) -> TaskLifecycleEventDraft:
        if self.command_schema_version != TASK_LIFECYCLE_COMMAND_SCHEMA_VERSION:
            raise ValueError("lifecycle command schema is unsupported")
        if self.source != TASK_LIFECYCLE_SOURCE or self.actor_scope != TASK_LIFECYCLE_ACTOR_SCOPE:
            raise ValueError("lifecycle authority is unsupported")
        if self.event_kind is TaskLifecycleEventKind.TRANSITION:
            if self.requested_state is None or self.supersedes_event_id is not None:
                raise ValueError("transition draft shape is invalid")
        elif (
            self.requested_state is not None
            or self.supersedes_event_id is None
            or self.supersedes_event_id != self.expected_head_event_id
        ):
            raise ValueError("correction draft shape is invalid")
        return self


class TaskLifecycleRepositoryError(RuntimeError):
    """Sanitized base for atomic lifecycle persistence rejections."""


class TaskLifecycleParentNotFound(TaskLifecycleRepositoryError):
    pass


class TaskLifecycleStaleRevision(TaskLifecycleRepositoryError):
    pass


class TaskLifecycleStaleHead(TaskLifecycleRepositoryError):
    pass


class TaskLifecycleIllegalTransition(TaskLifecycleRepositoryError):
    pass


class TaskLifecycleIdempotencyConflict(TaskLifecycleRepositoryError):
    pass


class TaskLifecycleRepository(Protocol):
    def append_event(
        self, draft: TaskLifecycleEventDraft
    ) -> tuple[TaskLifecycleEventRecord, bool]: ...

    def get_snapshot(
        self,
        task_id: str,
        task_revision: int,
        *,
        events_limit: int = 100,
        events_offset: int = 0,
    ) -> TaskLifecycleSnapshot | None: ...

    def list_current_snapshots(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        events_limit: int = 100,
    ) -> tuple[TaskLifecycleSnapshot, ...]: ...


class TaskLifecycleArtifactIds(Protocol):
    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str: ...


class TaskLifecycleError(RuntimeError):
    """Sanitized application-facing lifecycle command error."""


class TaskLifecycleNotFoundError(TaskLifecycleError):
    pass


class TaskLifecycleStaleRevisionError(TaskLifecycleError):
    pass


class TaskLifecycleStaleHeadError(TaskLifecycleError):
    pass


class InvalidTaskLifecycleTransitionError(TaskLifecycleError):
    pass


class TaskLifecycleIdempotencyError(TaskLifecycleError):
    pass


@dataclass(frozen=True, slots=True)
class TaskLifecycleWriteResult:
    event: TaskLifecycleEventRecord
    applied: bool


class TaskLifecycleService:
    """Issue one explicit local-user event and delegate the atomic truth checks."""

    def __init__(
        self,
        repository: TaskLifecycleRepository,
        identifiers: TaskLifecycleArtifactIds,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._identifiers = identifiers
        self._clock = clock

    def transition(
        self,
        command: TaskLifecycleTransitionCommand,
        *,
        idempotency_key: str,
    ) -> TaskLifecycleWriteResult:
        return self._apply(
            task_id=command.task_id,
            task_revision=command.task_revision,
            expected_head_event_id=command.expected_head_event_id,
            event_kind=TaskLifecycleEventKind.TRANSITION,
            requested_state=command.state,
            supersedes_event_id=None,
            idempotency_key=idempotency_key,
        )

    def correct(
        self,
        command: TaskLifecycleCorrectionCommand,
        *,
        idempotency_key: str,
    ) -> TaskLifecycleWriteResult:
        return self._apply(
            task_id=command.task_id,
            task_revision=command.task_revision,
            expected_head_event_id=command.expected_head_event_id,
            event_kind=TaskLifecycleEventKind.CORRECTION,
            requested_state=None,
            supersedes_event_id=command.supersedes_event_id,
            idempotency_key=idempotency_key,
        )

    def _apply(
        self,
        *,
        task_id: str,
        task_revision: int,
        expected_head_event_id: str | None,
        event_kind: TaskLifecycleEventKind,
        requested_state: TaskLifecycleState | None,
        supersedes_event_id: str | None,
        idempotency_key: str,
    ) -> TaskLifecycleWriteResult:
        if SAFE_VERSION_PATTERN.fullmatch(idempotency_key) is None:
            raise InvalidTaskLifecycleTransitionError(
                "idempotency key must be a short content-free identifier"
            )
        idempotency_hash = self._identifiers.fingerprint(
            "task-lifecycle-idempotency-v1", (idempotency_key,)
        )
        values = (
            TASK_LIFECYCLE_COMMAND_SCHEMA_VERSION,
            event_kind.value,
            task_id,
            str(task_revision),
            expected_head_event_id or "none",
            requested_state.value if requested_state is not None else "none",
            supersedes_event_id or "none",
            TASK_LIFECYCLE_SOURCE,
            TASK_LIFECYCLE_ACTOR_SCOPE,
        )
        draft = TaskLifecycleEventDraft(
            event_id=self._identifiers.fingerprint(
                "task-lifecycle-event-v1", (idempotency_hash,)
            ),
            task_id=task_id,
            task_revision=task_revision,
            event_kind=event_kind,
            requested_state=requested_state,
            expected_head_event_id=expected_head_event_id,
            supersedes_event_id=supersedes_event_id,
            command_schema_version=TASK_LIFECYCLE_COMMAND_SCHEMA_VERSION,
            source=TASK_LIFECYCLE_SOURCE,
            actor_scope=TASK_LIFECYCLE_ACTOR_SCOPE,
            request_fingerprint=self._identifiers.fingerprint(
                "task-lifecycle-request-v1", values
            ),
            idempotency_key_hash=idempotency_hash,
            created_at=self._clock(),
        )
        try:
            event, applied = self._repository.append_event(draft)
        except TaskLifecycleParentNotFound as exc:
            raise TaskLifecycleNotFoundError("task revision does not exist") from exc
        except TaskLifecycleStaleRevision as exc:
            raise TaskLifecycleStaleRevisionError("task revision is not current") from exc
        except TaskLifecycleStaleHead as exc:
            raise TaskLifecycleStaleHeadError("task lifecycle head changed") from exc
        except TaskLifecycleIllegalTransition as exc:
            raise InvalidTaskLifecycleTransitionError(
                "task lifecycle transition is invalid"
            ) from exc
        except TaskLifecycleIdempotencyConflict as exc:
            raise TaskLifecycleIdempotencyError(
                "task lifecycle idempotency key conflicts"
            ) from exc
        return TaskLifecycleWriteResult(event=event, applied=applied)
