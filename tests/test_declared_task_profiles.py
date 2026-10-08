"""Reviewed task-profile validation and SQLite authority tests.

Every fixture and identifier in this module is synthetic.  The persisted
surface is deliberately restricted to closed enums, counts, pseudonyms, and
server-issued timestamps.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import sqlite3

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.analysis.declared_task_profiles import (
    DECLARED_TASK_PROFILE_CONFIRMATION,
    DeclaredTaskProfileCommand,
    DeclaredTaskProfileConflictError,
    DeclaredTaskProfileNotFoundError,
    DeclaredTaskProfileService,
    DeclaredTaskProfileStaleRevisionError,
    apply_declared_task_profile,
)
from prompt_enhancer.application.analysis.text_contracts import (
    ConstraintKind,
    DeliverableSlot,
)
from prompt_enhancer.database import Database
from prompt_enhancer.domain import Provider
from prompt_enhancer.infrastructure.identifiers import LocalArtifactIdFactory
from prompt_enhancer.privacy import Pseudonymizer
from prompt_enhancer.application.analysis.text_analysis_presets import COACHING_PROFILE_V1

from test_model_ensemble_persistence import _database_and_session


NOW = datetime(2048, 9, 10, 11, 12, 13, tzinfo=UTC)


def _command(
    *,
    expected_revision: int | None = None,
    constraint_kinds: tuple[ConstraintKind, ...] | None = (
        ConstraintKind.COST,
        ConstraintKind.PRIVACY,
    ),
    expected_outcome_count: int | None = 2,
    deliverable_slots: tuple[DeliverableSlot, ...] | None = (
        DeliverableSlot.ARTIFACT,
        DeliverableSlot.FORMAT,
    ),
) -> DeclaredTaskProfileCommand:
    return DeclaredTaskProfileCommand(
        expected_revision=expected_revision,
        constraint_kinds=constraint_kinds,
        expected_outcome_count=expected_outcome_count,
        deliverable_slots=deliverable_slots,
        confirmation=DECLARED_TASK_PROFILE_CONFIRMATION,
    )


def _service(tmp_path):
    database, session_id = _database_and_session(tmp_path, Provider.CODEX)
    repository = database.declared_task_profile_repository()
    service = DeclaredTaskProfileService(
        repository,
        LocalArtifactIdFactory(Pseudonymizer(bytes(range(32)))),
        clock=lambda: NOW,
    )
    return database, session_id, repository, service


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("constraint_kinds", ()),
        (
            "constraint_kinds",
            (ConstraintKind.PRIVACY, ConstraintKind.COST),
        ),
        (
            "constraint_kinds",
            (ConstraintKind.COST, ConstraintKind.COST),
        ),
        ("deliverable_slots", ()),
        (
            "deliverable_slots",
            (DeliverableSlot.FORMAT, DeliverableSlot.ARTIFACT),
        ),
        (
            "deliverable_slots",
            (DeliverableSlot.ARTIFACT, DeliverableSlot.ARTIFACT),
        ),
        ("expected_outcome_count", 0),
        ("expected_outcome_count", 101),
    ),
)
def test_command_rejects_empty_unsorted_duplicate_or_out_of_range_configuration(
    field, value
) -> None:
    values = _command().model_dump()
    values[field] = value
    with pytest.raises(ValidationError):
        DeclaredTaskProfileCommand.model_validate(values)


def test_command_allows_partial_unknowns_but_cannot_carry_content() -> None:
    command = _command(
        constraint_kinds=None,
        expected_outcome_count=None,
        deliverable_slots=None,
    )
    assert command.constraint_kinds is None
    assert command.expected_outcome_count is None
    assert command.deliverable_slots is None
    with pytest.raises(ValidationError):
        DeclaredTaskProfileCommand.model_validate(
            {
                **command.model_dump(),
                "prompt_text": "synthetic content must not cross this boundary",
                "workspace_path": "example/project",
            }
        )


def test_reviewed_values_overlay_only_profile_denominators(tmp_path) -> None:
    _database, session_id, _repository, service = _service(tmp_path)
    declaration, _created = service.save(
        provider=Provider.CODEX,
        session_id=session_id,
        command=_command(),
        idempotency_key="synthetic-profile-overlay-0001",
    )

    resolved = apply_declared_task_profile(
        COACHING_PROFILE_V1.task_profile,
        declaration,
    )

    assert resolved.applicability == COACHING_PROFILE_V1.task_profile.applicability
    assert (
        resolved.expected_goal_slots
        == COACHING_PROFILE_V1.task_profile.expected_goal_slots
    )
    assert resolved.expected_constraint_kinds == declaration.constraint_kinds
    assert resolved.expected_outcome_count == declaration.expected_outcome_count
    assert resolved.expected_deliverable_slots == declaration.deliverable_slots


def test_save_replay_conflict_revision_restart_and_private_metadata(tmp_path) -> None:
    database, session_id, _repository, service = _service(tmp_path)
    key = "synthetic-profile-retry-0001"
    first, created = service.save(
        provider=Provider.CODEX,
        session_id=session_id,
        command=_command(),
        idempotency_key=key,
    )
    assert created is True
    assert first.revision == 1
    assert first.previous_profile_id is None
    assert first.confirmed_at == NOW
    assert first.confirmation_authority == "authenticated_local_user"
    assert first.local_only is True
    assert first.content_persisted is False
    assert first.idempotency_key_digest != key
    assert first.constraint_kinds == (ConstraintKind.COST, ConstraintKind.PRIVACY)

    replay, created = service.save(
        provider=Provider.CODEX,
        session_id=session_id,
        command=_command(),
        idempotency_key=key,
    )
    assert created is False
    assert replay == first

    with pytest.raises(DeclaredTaskProfileConflictError):
        service.save(
            provider=Provider.CODEX,
            session_id=session_id,
            command=_command(expected_outcome_count=3),
            idempotency_key=key,
        )

    second, created = service.save(
        provider=Provider.CODEX,
        session_id=session_id,
        command=_command(
            expected_revision=1,
            constraint_kinds=None,
            expected_outcome_count=1,
        ),
        idempotency_key="synthetic-profile-retry-0002",
    )
    assert created is True
    assert second.revision == 2
    assert second.previous_profile_id == first.profile_id
    assert second.constraint_kinds is None
    assert second.profile_fingerprint != first.profile_fingerprint

    with pytest.raises(DeclaredTaskProfileStaleRevisionError):
        service.save(
            provider=Provider.CODEX,
            session_id=session_id,
            command=_command(expected_revision=1),
            idempotency_key="synthetic-profile-retry-stale-0003",
        )

    restarted = Database(database.path).declared_task_profile_repository()
    assert restarted.get_latest(Provider.CODEX, session_id) == second
    assert restarted.get_revision(Provider.CODEX, session_id, 1) == first

    with sqlite3.connect(database.path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM session_declared_task_profiles WHERE profile_id=?",
            (first.profile_id,),
        ).fetchone()
        assert row is not None
        assert key not in tuple(str(value) for value in row)
        forbidden_fragments = ("prompt", "text", "path", "rationale", "excerpt")
        assert not any(
            fragment in column.lower()
            for column in row.keys()
            for fragment in forbidden_fragments
        )


def test_session_provider_binding_and_missing_parent_fail_closed(tmp_path) -> None:
    _database, session_id, _repository, service = _service(tmp_path)
    with pytest.raises(DeclaredTaskProfileNotFoundError):
        service.save(
            provider=Provider.CLAUDE_CODE,
            session_id=session_id,
            command=_command(),
            idempotency_key="synthetic-wrong-provider-0001",
        )
    with pytest.raises(DeclaredTaskProfileNotFoundError):
        service.save(
            provider=Provider.CODEX,
            session_id=hashlib.sha256(b"synthetic-missing-session").hexdigest(),
            command=_command(),
            idempotency_key="synthetic-missing-session-0001",
        )


def test_seal_counts_revision_chain_and_enum_guards_reject_tampering(tmp_path) -> None:
    database, session_id, _repository, service = _service(tmp_path)
    first, _ = service.save(
        provider=Provider.CODEX,
        session_id=session_id,
        command=_command(),
        idempotency_key="synthetic-profile-tamper-0001",
    )
    profile_id = "a" * 64
    timestamp = NOW.isoformat(timespec="microseconds")
    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        values = (
            profile_id,
            session_id,
            "codex",
            2,
            first.profile_id,
            2,
            None,
            None,
            "b" * 64,
            "c" * 64,
            "d" * 64,
            timestamp,
            "authenticated_local_user",
            "declared-task-profile-v1",
            "authenticated-local-user-v1",
            1,
            0,
        )
        connection.execute(
            """INSERT INTO session_declared_task_profiles(
                   profile_id,session_id,provider,revision,previous_profile_id,
                   constraint_kind_count,expected_outcome_count,
                   deliverable_slot_count,profile_fingerprint,
                   idempotency_key_digest,command_fingerprint,confirmed_at,
                   confirmation_authority,schema_version,policy_version,
                   local_only,content_persisted
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            values,
        )
        connection.execute(
            """INSERT INTO session_declared_task_profile_constraint_kinds
               VALUES(?,0,'cost')""",
            (profile_id,),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO session_declared_task_profile_seals
                   VALUES(?,2,NULL,NULL,?)""",
                (profile_id, timestamp),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO session_declared_task_profile_constraint_kinds
                   VALUES(?,2,'privacy')""",
                (profile_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """INSERT INTO session_declared_task_profiles(
                       profile_id,session_id,provider,revision,previous_profile_id,
                       constraint_kind_count,expected_outcome_count,
                       deliverable_slot_count,profile_fingerprint,
                       idempotency_key_digest,command_fingerprint,confirmed_at,
                       confirmation_authority,schema_version,policy_version,
                       local_only,content_persisted
                   ) VALUES(?,?,?,3,?,NULL,NULL,NULL,?,?,?,?,?,?,?,?,0)""",
                (
                    "e" * 64,
                    session_id,
                    "codex",
                    first.profile_id,
                    "f" * 64,
                    "1" * 64,
                    "2" * 64,
                    timestamp,
                    "authenticated_local_user",
                    "declared-task-profile-v1",
                    "authenticated-local-user-v1",
                    1,
                ),
            )


def test_rows_are_immutable_and_only_parent_session_privacy_delete_cascades(
    tmp_path,
) -> None:
    database, session_id, _repository, service = _service(tmp_path)
    profile, _ = service.save(
        provider=Provider.CODEX,
        session_id=session_id,
        command=_command(),
        idempotency_key="synthetic-profile-delete-0001",
    )
    tables = (
        "session_declared_task_profile_constraint_kinds",
        "session_declared_task_profile_deliverable_slots",
        "session_declared_task_profile_seals",
        "session_declared_task_profiles",
    )
    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """UPDATE session_declared_task_profiles
                   SET expected_outcome_count=3 WHERE profile_id=?""",
                (profile.profile_id,),
            )
        for table in tables:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    f"DELETE FROM {table} WHERE profile_id=?", (profile.profile_id,)
                )
    # The main database connection registers the content-free authorization
    # functions required by older child-table privacy triggers too.
    with database._connection() as connection:
        connection.execute("PRAGMA trusted_schema=ON")
        connection.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        connection.commit()
        for table in tables:
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE profile_id=?",
                (profile.profile_id,),
            ).fetchone()[0] == 0
