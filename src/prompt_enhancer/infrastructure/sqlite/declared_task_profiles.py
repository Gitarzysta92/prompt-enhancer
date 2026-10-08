"""SQLite adapter for immutable, content-free reviewed task profiles."""

from __future__ import annotations

from collections.abc import Callable
import sqlite3

from ...application.analysis.declared_task_profiles import (
    DeclaredTaskProfileConflictError,
    DeclaredTaskProfileNotFoundError,
    DeclaredTaskProfileRecord,
    DeclaredTaskProfileRepository,
    DeclaredTaskProfileStaleRevisionError,
)
from ...application.analysis.text_contracts import ConstraintKind, DeliverableSlot
from ...database import DatabaseInvariantError
from ...domain import Provider
from ._common import ConnectionScope, from_iso, require_safe_id, to_iso


class SqliteDeclaredTaskProfileRepository(DeclaredTaskProfileRepository):
    """Append and seal exact profile revisions under one immediate lock."""

    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized

    def save(
        self, profile: DeclaredTaskProfileRecord
    ) -> tuple[DeclaredTaskProfileRecord, bool]:
        self._ensure_initialized()
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                # Replays are resolved before testing the expected head.  A
                # successful retry therefore remains stable after its own
                # revision has become the current head.
                replay = connection.execute(
                    """SELECT profile_id,command_fingerprint
                       FROM session_declared_task_profiles
                       WHERE session_id=? AND idempotency_key_digest=?""",
                    (profile.session_id, profile.idempotency_key_digest),
                ).fetchone()
                if replay is not None:
                    if (
                        replay["profile_id"] != profile.profile_id
                        or replay["command_fingerprint"]
                        != profile.command_fingerprint
                    ):
                        raise DeclaredTaskProfileConflictError(
                            "task profile idempotency key conflicts"
                        )
                    stored = self._get_by_id(connection, profile.profile_id)
                    if stored is None:
                        raise DatabaseInvariantError(
                            "task profile replay is not sealed"
                        )
                    connection.commit()
                    return stored, False

                parent = connection.execute(
                    "SELECT provider FROM sessions WHERE session_id=?",
                    (profile.session_id,),
                ).fetchone()
                if parent is None or parent["provider"] != profile.provider.value:
                    raise DeclaredTaskProfileNotFoundError(
                        "task profile session/provider does not exist"
                    )

                latest = connection.execute(
                    """SELECT profile.profile_id,profile.revision
                       FROM session_declared_task_profiles profile
                       JOIN session_declared_task_profile_seals seal
                         ON seal.profile_id=profile.profile_id
                       WHERE profile.session_id=?
                       ORDER BY profile.revision DESC,profile.profile_id DESC
                       LIMIT 1""",
                    (profile.session_id,),
                ).fetchone()
                expected_revision = 1 if latest is None else int(latest["revision"]) + 1
                expected_previous = (
                    None if latest is None else str(latest["profile_id"])
                )
                if (
                    profile.revision != expected_revision
                    or profile.previous_profile_id != expected_previous
                ):
                    raise DeclaredTaskProfileStaleRevisionError(
                        "task profile expected revision is stale"
                    )

                constraint_count = (
                    None
                    if profile.constraint_kinds is None
                    else len(profile.constraint_kinds)
                )
                deliverable_count = (
                    None
                    if profile.deliverable_slots is None
                    else len(profile.deliverable_slots)
                )
                confirmed_at = to_iso(profile.confirmed_at)
                connection.execute(
                    """INSERT INTO session_declared_task_profiles(
                           profile_id,session_id,provider,revision,
                           previous_profile_id,constraint_kind_count,
                           expected_outcome_count,deliverable_slot_count,
                           profile_fingerprint,idempotency_key_digest,
                           command_fingerprint,confirmed_at,
                           confirmation_authority,schema_version,policy_version,
                           local_only,content_persisted
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        profile.profile_id,
                        profile.session_id,
                        profile.provider.value,
                        profile.revision,
                        profile.previous_profile_id,
                        constraint_count,
                        profile.expected_outcome_count,
                        deliverable_count,
                        profile.profile_fingerprint,
                        profile.idempotency_key_digest,
                        profile.command_fingerprint,
                        confirmed_at,
                        profile.confirmation_authority,
                        profile.schema_version,
                        profile.policy_version,
                        1,
                        0,
                    ),
                )
                connection.executemany(
                    """INSERT INTO session_declared_task_profile_constraint_kinds(
                           profile_id,ordinal,constraint_kind
                       ) VALUES(?,?,?)""",
                    (
                        (profile.profile_id, ordinal, kind.value)
                        for ordinal, kind in enumerate(profile.constraint_kinds or ())
                    ),
                )
                connection.executemany(
                    """INSERT INTO session_declared_task_profile_deliverable_slots(
                           profile_id,ordinal,deliverable_slot
                       ) VALUES(?,?,?)""",
                    (
                        (profile.profile_id, ordinal, slot.value)
                        for ordinal, slot in enumerate(profile.deliverable_slots or ())
                    ),
                )
                connection.execute(
                    """INSERT INTO session_declared_task_profile_seals(
                           profile_id,constraint_kind_count,
                           expected_outcome_count,deliverable_slot_count,sealed_at
                       ) VALUES(?,?,?,?,?)""",
                    (
                        profile.profile_id,
                        constraint_count,
                        profile.expected_outcome_count,
                        deliverable_count,
                        confirmed_at,
                    ),
                )
                stored = self._get_by_id(connection, profile.profile_id)
                if stored is None:
                    raise DatabaseInvariantError("task profile insert is not sealed")
                connection.commit()
                return stored, True
            except (
                DeclaredTaskProfileConflictError,
                DeclaredTaskProfileNotFoundError,
                DeclaredTaskProfileStaleRevisionError,
            ):
                connection.rollback()
                raise
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise DeclaredTaskProfileConflictError(
                    "task profile conflicts with stored authority"
                ) from error
            except Exception:
                connection.rollback()
                raise

    def get_by_id(self, profile_id: str) -> DeclaredTaskProfileRecord | None:
        self._ensure_initialized()
        require_safe_id(profile_id)
        with self._connection_scope(readonly=True) as connection:
            return self._get_by_id(connection, profile_id)

    def get_revision(
        self, provider: Provider, session_id: str, revision: int
    ) -> DeclaredTaskProfileRecord | None:
        self._ensure_initialized()
        require_safe_id(session_id)
        if not isinstance(provider, Provider):
            raise ValueError("provider must be known")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise ValueError("revision must be positive")
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """SELECT profile.profile_id
                   FROM session_declared_task_profiles profile
                   JOIN session_declared_task_profile_seals seal
                     ON seal.profile_id=profile.profile_id
                   WHERE profile.provider=? AND profile.session_id=?
                     AND profile.revision=?""",
                (provider.value, session_id, revision),
            ).fetchone()
            return (
                None
                if row is None
                else self._get_by_id(connection, str(row["profile_id"]))
            )

    def get_latest(
        self, provider: Provider, session_id: str
    ) -> DeclaredTaskProfileRecord | None:
        self._ensure_initialized()
        require_safe_id(session_id)
        if not isinstance(provider, Provider):
            raise ValueError("provider must be known")
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """SELECT profile.profile_id
                   FROM session_declared_task_profiles profile
                   JOIN session_declared_task_profile_seals seal
                     ON seal.profile_id=profile.profile_id
                   WHERE profile.provider=? AND profile.session_id=?
                   ORDER BY profile.revision DESC,profile.profile_id DESC
                   LIMIT 1""",
                (provider.value, session_id),
            ).fetchone()
            return (
                None
                if row is None
                else self._get_by_id(connection, str(row["profile_id"]))
            )

    @staticmethod
    def _get_by_id(
        connection: sqlite3.Connection, profile_id: str
    ) -> DeclaredTaskProfileRecord | None:
        row = connection.execute(
            """SELECT profile.*
               FROM session_declared_task_profiles profile
               JOIN session_declared_task_profile_seals seal
                 ON seal.profile_id=profile.profile_id
                AND seal.constraint_kind_count IS profile.constraint_kind_count
                AND seal.expected_outcome_count IS profile.expected_outcome_count
                AND seal.deliverable_slot_count IS profile.deliverable_slot_count
                AND seal.sealed_at=profile.confirmed_at
               WHERE profile.profile_id=?""",
            (profile_id,),
        ).fetchone()
        if row is None:
            return None
        constraints = tuple(
            item["constraint_kind"]
            for item in connection.execute(
                """SELECT constraint_kind
                   FROM session_declared_task_profile_constraint_kinds
                   WHERE profile_id=? ORDER BY ordinal""",
                (profile_id,),
            ).fetchall()
        )
        deliverables = tuple(
            item["deliverable_slot"]
            for item in connection.execute(
                """SELECT deliverable_slot
                   FROM session_declared_task_profile_deliverable_slots
                   WHERE profile_id=? ORDER BY ordinal""",
                (profile_id,),
            ).fetchall()
        )
        constraint_count = row["constraint_kind_count"]
        deliverable_count = row["deliverable_slot_count"]
        expected_constraints = (
            0 if constraint_count is None else int(constraint_count)
        )
        expected_deliverables = (
            0 if deliverable_count is None else int(deliverable_count)
        )
        if len(constraints) != expected_constraints:
            raise DatabaseInvariantError("task profile constraint count is invalid")
        if len(deliverables) != expected_deliverables:
            raise DatabaseInvariantError("task profile deliverable count is invalid")
        confirmed_at = from_iso(row["confirmed_at"])
        if confirmed_at is None:
            raise DatabaseInvariantError("task profile confirmation time is missing")
        try:
            return DeclaredTaskProfileRecord(
                profile_id=row["profile_id"],
                provider=Provider(row["provider"]),
                session_id=row["session_id"],
                revision=int(row["revision"]),
                previous_profile_id=row["previous_profile_id"],
                constraint_kinds=(
                    None
                    if constraint_count is None
                    else tuple(ConstraintKind(value) for value in constraints)
                ),
                expected_outcome_count=row["expected_outcome_count"],
                deliverable_slots=(
                    None
                    if deliverable_count is None
                    else tuple(DeliverableSlot(value) for value in deliverables)
                ),
                profile_fingerprint=row["profile_fingerprint"],
                idempotency_key_digest=row["idempotency_key_digest"],
                command_fingerprint=row["command_fingerprint"],
                confirmed_at=confirmed_at,
                confirmation_authority=row["confirmation_authority"],
                schema_version=row["schema_version"],
                policy_version=row["policy_version"],
                local_only=bool(row["local_only"]),
                content_persisted=bool(row["content_persisted"]),
            )
        except (TypeError, ValueError):
            raise DatabaseInvariantError("stored task profile is invalid") from None


__all__ = ["SqliteDeclaredTaskProfileRepository"]
