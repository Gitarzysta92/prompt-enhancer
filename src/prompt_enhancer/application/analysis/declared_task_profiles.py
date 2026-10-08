"""Reviewed, content-free task-profile declarations for one local session.

Only the denominator configuration needed by three deterministic prompt
metrics crosses this boundary.  ``None`` means the person has not configured
that family, never zero and never not-applicable.  No prompt text, label,
path, rationale, model claim, or caller supplied time can be represented.

Each accepted command appends an immutable revision confirmed by an
authenticated local user.  Retry keys are converted to installation-local
keyed digests before persistence and all identifiers and times are issued by
the server-side service.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, TypeVar

from pydantic import Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, Provider, StrictModel
from .text_contracts import ConstraintKind, DeliverableSlot, TextTaskProfile


DECLARED_TASK_PROFILE_SCHEMA_VERSION = "declared-task-profile-v1"
DECLARED_TASK_PROFILE_POLICY_VERSION = "authenticated-local-user-v1"
DECLARED_TASK_PROFILE_CONFIRMATION = "save_reviewed_declared_task_profile"
DECLARED_TASK_PROFILE_CONFIRMATION_AUTHORITY = "authenticated_local_user"
MAX_DECLARED_TASK_PROFILE_REVISION = 1_000_000
_ProfileEnum = TypeVar("_ProfileEnum", ConstraintKind, DeliverableSlot)


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("identifier must be an installation-local pseudonym")
    return value


def _safe_code(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a short content-free identifier")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("server timestamps must be UTC")
    return value


def _configured_enum_values(
    values: tuple[_ProfileEnum, ...] | None,
    *,
    family: str,
) -> tuple[_ProfileEnum, ...] | None:
    if values is None:
        return None
    if not values:
        raise ValueError(f"configured {family} cannot be empty")
    if len(set(values)) != len(values):
        raise ValueError(f"configured {family} cannot contain duplicates")
    if values != tuple(sorted(values, key=lambda item: item.value)):
        raise ValueError(f"configured {family} must be sorted")
    return values


class DeclaredTaskProfileCommand(StrictModel):
    """Exact reviewed declaration supplied by a local authenticated UI."""

    expected_revision: int | None = Field(
        default=None,
        ge=1,
        le=MAX_DECLARED_TASK_PROFILE_REVISION - 1,
    )
    constraint_kinds: tuple[ConstraintKind, ...] | None = None
    expected_outcome_count: int | None = Field(default=None, ge=1, le=100)
    deliverable_slots: tuple[DeliverableSlot, ...] | None = None
    confirmation: Literal[DECLARED_TASK_PROFILE_CONFIRMATION]

    @field_validator("constraint_kinds")
    @classmethod
    def validate_constraint_kinds(
        cls, values: tuple[ConstraintKind, ...] | None
    ) -> tuple[ConstraintKind, ...] | None:
        return _configured_enum_values(values, family="constraint kinds")

    @field_validator("deliverable_slots")
    @classmethod
    def validate_deliverable_slots(
        cls, values: tuple[DeliverableSlot, ...] | None
    ) -> tuple[DeliverableSlot, ...] | None:
        return _configured_enum_values(values, family="deliverable slots")


class DeclaredTaskProfileRecord(StrictModel):
    """One sealed revision; all fields are safe metadata or closed values."""

    profile_id: str
    provider: Provider
    session_id: str
    revision: int = Field(ge=1, le=MAX_DECLARED_TASK_PROFILE_REVISION)
    previous_profile_id: str | None = None
    constraint_kinds: tuple[ConstraintKind, ...] | None = None
    expected_outcome_count: int | None = Field(default=None, ge=1, le=100)
    deliverable_slots: tuple[DeliverableSlot, ...] | None = None
    profile_fingerprint: str
    idempotency_key_digest: str
    command_fingerprint: str
    confirmed_at: datetime
    confirmation_authority: Literal[
        DECLARED_TASK_PROFILE_CONFIRMATION_AUTHORITY
    ] = DECLARED_TASK_PROFILE_CONFIRMATION_AUTHORITY
    schema_version: Literal[
        DECLARED_TASK_PROFILE_SCHEMA_VERSION
    ] = DECLARED_TASK_PROFILE_SCHEMA_VERSION
    policy_version: Literal[
        DECLARED_TASK_PROFILE_POLICY_VERSION
    ] = DECLARED_TASK_PROFILE_POLICY_VERSION
    local_only: Literal[True] = True
    content_persisted: Literal[False] = False

    _ids = field_validator(
        "profile_id",
        "session_id",
        "profile_fingerprint",
        "idempotency_key_digest",
        "command_fingerprint",
    )(_pseudonym)
    _confirmed = field_validator("confirmed_at")(_utc)
    _codes = field_validator(
        "confirmation_authority", "schema_version", "policy_version"
    )(_safe_code)

    @field_validator("previous_profile_id")
    @classmethod
    def validate_previous_profile_id(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @field_validator("constraint_kinds")
    @classmethod
    def validate_record_constraint_kinds(
        cls, values: tuple[ConstraintKind, ...] | None
    ) -> tuple[ConstraintKind, ...] | None:
        return _configured_enum_values(values, family="constraint kinds")

    @field_validator("deliverable_slots")
    @classmethod
    def validate_record_deliverable_slots(
        cls, values: tuple[DeliverableSlot, ...] | None
    ) -> tuple[DeliverableSlot, ...] | None:
        return _configured_enum_values(values, family="deliverable slots")

    @model_validator(mode="after")
    def validate_revision_chain_shape(self) -> "DeclaredTaskProfileRecord":
        if (self.revision == 1) != (self.previous_profile_id is None):
            raise ValueError("only the first task-profile revision has no predecessor")
        return self


class DeclaredTaskProfileRepository(Protocol):
    def save(
        self, profile: DeclaredTaskProfileRecord
    ) -> tuple[DeclaredTaskProfileRecord, bool]: ...

    def get_by_id(self, profile_id: str) -> DeclaredTaskProfileRecord | None: ...

    def get_revision(
        self, provider: Provider, session_id: str, revision: int
    ) -> DeclaredTaskProfileRecord | None: ...

    def get_latest(
        self, provider: Provider, session_id: str
    ) -> DeclaredTaskProfileRecord | None: ...


class DeclaredTaskProfileIdFactory(Protocol):
    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str: ...


class DeclaredTaskProfileError(RuntimeError):
    code = "declared_task_profile_failed"


class DeclaredTaskProfileInputError(DeclaredTaskProfileError):
    code = "invalid_declared_task_profile"


class DeclaredTaskProfileNotFoundError(DeclaredTaskProfileError):
    code = "declared_task_profile_session_not_found"


class DeclaredTaskProfileStaleRevisionError(DeclaredTaskProfileError):
    code = "declared_task_profile_revision_stale"


class DeclaredTaskProfileConflictError(DeclaredTaskProfileError):
    code = "declared_task_profile_conflict"


class DeclaredTaskProfilePersistenceError(DeclaredTaskProfileError):
    code = "declared_task_profile_persistence_failed"


class DeclaredTaskProfileService:
    """Issue immutable reviewed profile revisions using server authority."""

    def __init__(
        self,
        repository: DeclaredTaskProfileRepository,
        identifiers: DeclaredTaskProfileIdFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._identifiers = identifiers
        self._clock = clock

    def save(
        self,
        *,
        provider: Provider,
        session_id: str,
        command: DeclaredTaskProfileCommand,
        idempotency_key: str,
    ) -> tuple[DeclaredTaskProfileRecord, bool]:
        self._validate_request(provider, session_id, idempotency_key)
        idempotency_digest = self._identifiers.fingerprint(
            "declared-task-profile-idempotency-v1",
            (provider.value, session_id, idempotency_key),
        )
        profile_id = self._identifiers.fingerprint(
            "declared-task-profile-record-v1",
            (provider.value, session_id, idempotency_digest),
        )
        values = self._profile_values(command)
        command_fingerprint = self._identifiers.fingerprint(
            "declared-task-profile-command-v1",
            (
                provider.value,
                session_id,
                (
                    "none"
                    if command.expected_revision is None
                    else str(command.expected_revision)
                ),
                *values,
                command.confirmation,
            ),
        )
        profile_fingerprint = self._identifiers.fingerprint(
            "declared-task-profile-values-v1",
            (provider.value, session_id, *values),
        )
        revision = (
            1
            if command.expected_revision is None
            else command.expected_revision + 1
        )
        previous_profile_id: str | None = None
        if command.expected_revision is not None:
            try:
                previous = self._repository.get_revision(
                    provider, session_id, command.expected_revision
                )
            except Exception:
                raise DeclaredTaskProfilePersistenceError(
                    "task profile predecessor could not be read"
                ) from None
            if previous is None:
                raise DeclaredTaskProfileStaleRevisionError(
                    "task profile predecessor changed"
                )
            previous_profile_id = previous.profile_id
        try:
            profile = DeclaredTaskProfileRecord(
                profile_id=profile_id,
                provider=provider,
                session_id=session_id,
                revision=revision,
                previous_profile_id=previous_profile_id,
                constraint_kinds=command.constraint_kinds,
                expected_outcome_count=command.expected_outcome_count,
                deliverable_slots=command.deliverable_slots,
                profile_fingerprint=profile_fingerprint,
                idempotency_key_digest=idempotency_digest,
                command_fingerprint=command_fingerprint,
                confirmed_at=self._clock(),
            )
        except (TypeError, ValueError):
            raise DeclaredTaskProfileInputError(
                "server task-profile authority is invalid"
            ) from None
        try:
            return self._repository.save(profile)
        except (
            DeclaredTaskProfileConflictError,
            DeclaredTaskProfileNotFoundError,
            DeclaredTaskProfileStaleRevisionError,
        ):
            raise
        except Exception:
            raise DeclaredTaskProfilePersistenceError(
                "task profile could not be stored"
            ) from None

    def get_latest(
        self, *, provider: Provider, session_id: str
    ) -> DeclaredTaskProfileRecord | None:
        self._validate_selection(provider, session_id)
        try:
            return self._repository.get_latest(provider, session_id)
        except Exception:
            raise DeclaredTaskProfilePersistenceError(
                "task profile could not be read"
            ) from None

    @staticmethod
    def _profile_values(command: DeclaredTaskProfileCommand) -> tuple[str, ...]:
        constraints = (
            ("constraints-unconfigured",)
            if command.constraint_kinds is None
            else (
                "constraints-configured",
                *(item.value for item in command.constraint_kinds),
            )
        )
        outcomes = (
            "outcomes-unconfigured"
            if command.expected_outcome_count is None
            else f"outcomes-{command.expected_outcome_count}"
        )
        deliverables = (
            ("deliverables-unconfigured",)
            if command.deliverable_slots is None
            else (
                "deliverables-configured",
                *(item.value for item in command.deliverable_slots),
            )
        )
        return (*constraints, outcomes, *deliverables)

    @staticmethod
    def _validate_selection(provider: Provider, session_id: str) -> None:
        if not isinstance(provider, Provider):
            raise DeclaredTaskProfileInputError("task profile provider is invalid")
        try:
            _pseudonym(session_id)
        except (TypeError, ValueError):
            raise DeclaredTaskProfileInputError(
                "task profile session is invalid"
            ) from None

    @classmethod
    def _validate_request(
        cls, provider: Provider, session_id: str, idempotency_key: str
    ) -> None:
        cls._validate_selection(provider, session_id)
        try:
            valid_key = (
                isinstance(idempotency_key, str)
                and len(idempotency_key) >= 16
                and SAFE_VERSION_PATTERN.fullmatch(idempotency_key) is not None
            )
        except TypeError:
            valid_key = False
        if not valid_key:
            raise DeclaredTaskProfileInputError(
                "idempotency key must be a content-free identifier"
            )


def apply_declared_task_profile(
    base: TextTaskProfile,
    declaration: DeclaredTaskProfileRecord,
) -> TextTaskProfile:
    """Overlay only the three reviewed denominator families on a fixed preset.

    ``None`` deliberately maps back to the preset's unconfigured value.  The
    declaration cannot alter metric applicability or goal-slot semantics.
    """

    if not isinstance(base, TextTaskProfile) or not isinstance(
        declaration, DeclaredTaskProfileRecord
    ):
        raise TypeError("declared task profile inputs are invalid")
    return base.model_copy(
        update={
            "expected_constraint_kinds": declaration.constraint_kinds or (),
            "expected_outcome_count": declaration.expected_outcome_count,
            "expected_deliverable_slots": declaration.deliverable_slots or (),
        }
    )


__all__ = [
    "DECLARED_TASK_PROFILE_CONFIRMATION",
    "DECLARED_TASK_PROFILE_CONFIRMATION_AUTHORITY",
    "DECLARED_TASK_PROFILE_POLICY_VERSION",
    "DECLARED_TASK_PROFILE_SCHEMA_VERSION",
    "MAX_DECLARED_TASK_PROFILE_REVISION",
    "DeclaredTaskProfileCommand",
    "DeclaredTaskProfileConflictError",
    "DeclaredTaskProfileError",
    "DeclaredTaskProfileIdFactory",
    "DeclaredTaskProfileInputError",
    "DeclaredTaskProfileNotFoundError",
    "DeclaredTaskProfilePersistenceError",
    "DeclaredTaskProfileRecord",
    "DeclaredTaskProfileRepository",
    "DeclaredTaskProfileService",
    "DeclaredTaskProfileStaleRevisionError",
    "apply_declared_task_profile",
]
