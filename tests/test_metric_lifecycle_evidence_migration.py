"""Append-only M43 to M44 upgrade and rollback guarantees."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import sqlite3

import pytest

from prompt_enhancer import database as database_module
from prompt_enhancer.database import (
    SCHEMA_VERSION,
    Database,
    _MIGRATION_1,
    _apply_migration_atomically,
)
from prompt_enhancer.infrastructure.sqlite import migrations


NOW = datetime(2044, 5, 6, 7, 8, tzinfo=UTC)
MIGRATION_43_FROZEN_SHA256 = (
    "c9f21b888cd8e9faf6c11c933a2bca9360f0f8b0abdb213ec69e8b22132f92ec"
)


def _create_populated_v43(path) -> tuple[str, str]:
    scripts = (_MIGRATION_1,) + tuple(
        getattr(migrations, f"MIGRATION_{version}") for version in range(2, 44)
    )
    timestamp = NOW.isoformat(timespec="microseconds")
    installation_id = "1" * 64
    project_id = "2" * 64
    session_id = "3" * 64
    task_id = "4" * 64
    task_fingerprint = "5" * 64
    event_id = "6" * 64
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=ON")
        for script in scripts:
            connection.executescript(script)
        connection.execute(
            """CREATE TABLE schema_migrations(
                   version INTEGER PRIMARY KEY,
                   checksum TEXT NOT NULL,
                   applied_at TEXT NOT NULL
               )"""
        )
        connection.executemany(
            "INSERT INTO schema_migrations VALUES (?,?,?)",
            tuple(
                (
                    version,
                    hashlib.sha256(script.encode()).hexdigest(),
                    timestamp,
                )
                for version, script in enumerate(scripts, start=1)
            ),
        )
        connection.execute(
            "INSERT INTO installations VALUES (?,?,?)",
            (installation_id, "synthetic", timestamp),
        )
        connection.execute(
            """INSERT INTO projects(
                   project_id,installation_id,provider,created_at
               ) VALUES (?,?,?,?)""",
            (project_id, installation_id, "synthetic", timestamp),
        )
        connection.execute(
            """INSERT INTO sessions(
                   session_id,installation_id,project_id,provider,
                   provider_version,adapter_version,source_schema_version,
                   started_at,ended_at,terminal_state,events_complete,
                   created_at,updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                session_id,
                installation_id,
                project_id,
                "synthetic",
                "synthetic-provider-v1",
                "synthetic-adapter-v1",
                "synthetic-schema-v1",
                timestamp,
                timestamp,
                "completed",
                1,
                timestamp,
                timestamp,
            ),
        )
        connection.execute(
            "INSERT INTO tasks(task_id,project_id,created_at) VALUES (?,?,?)",
            (task_id, project_id, timestamp),
        )
        connection.execute(
            """INSERT INTO task_revisions(
                   task_id,revision,task_type,lifecycle_state,
                   input_fingerprint,created_at
               ) VALUES (?,1,'feature_implementation','confirmed',?,?)""",
            (task_id, task_fingerprint, timestamp),
        )
        connection.execute(
            """INSERT INTO task_lifecycle_events(
                   event_id,task_id,task_revision,sequence,event_kind,
                   prior_state,resulting_state,previous_event_id,
                   supersedes_event_id,task_input_fingerprint,
                   command_schema_version,source,actor_scope,
                   request_fingerprint,idempotency_key_hash,created_at
               ) VALUES (?,?,1,1,'transition',NULL,'backlog',NULL,NULL,?,
                         'task-lifecycle-command-v1','explicit_local_user',
                         'local_user',?,?,?)""",
            (event_id, task_id, task_fingerprint, "7" * 64, "8" * 64, timestamp),
        )
        connection.execute("PRAGMA user_version=43")
        connection.commit()
    return task_id, event_id


def test_populated_v43_upgrades_to_v44_without_backfill_or_frozen_drift(
    tmp_path,
) -> None:
    path = tmp_path / "populated-v43.sqlite3"
    task_id, event_id = _create_populated_v43(path)
    frozen = hashlib.sha256(migrations.MIGRATION_43.encode()).hexdigest()
    assert frozen == MIGRATION_43_FROZEN_SHA256

    Database(path).initialize()

    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT version,checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert SCHEMA_VERSION == 61
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert tuple(row[0] for row in rows) == tuple(range(1, 62))
        assert rows[42][1] == frozen
        assert rows[43][1] == hashlib.sha256(
            migrations.MIGRATION_44.encode()
        ).hexdigest()
        assert connection.execute(
            """SELECT event_id FROM task_lifecycle_events
               WHERE task_id=?""",
            (task_id,),
        ).fetchone()[0] == event_id
        for table in (
            "metric_lifecycle_evidence_windows",
            "metric_lifecycle_evidence_proposals",
            "metric_lifecycle_evidence_enumeration_members",
            "metric_lifecycle_evidence_decisions",
            "session_model_ensemble_metric_states_v2_r4",
            "session_model_ensemble_metric_publication_v2_seals_r4",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0] == 0
        foreign_keys = connection.execute(
            "PRAGMA foreign_key_list(metric_lifecycle_evidence_proposals)"
        ).fetchall()
        assert any(
            row[2] == "session_model_ensemble_runs"
            and row[3] == "source_run_id"
            and row[6] == "CASCADE"
            for row in foreign_keys
        )
        assert {
            (row[2], row[3], row[4], row[6]) for row in foreign_keys
        }.issuperset(
            {
                (
                    "metric_lifecycle_evidence_windows",
                    "session_id",
                    "session_id",
                    "CASCADE",
                ),
                (
                    "metric_lifecycle_evidence_windows",
                    "source_window_fingerprint",
                    "source_window_fingerprint",
                    "CASCADE",
                ),
            }
        )
        window_foreign_keys = connection.execute(
            "PRAGMA foreign_key_list(metric_lifecycle_evidence_windows)"
        ).fetchall()
        assert any(
            row[2] == "session_model_ensemble_runs"
            and row[3] == "anchor_run_id"
            and row[6] == "CASCADE"
            for row in window_foreign_keys
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_failed_v44_rolls_back_schema_ledger_and_user_version_together(
    tmp_path,
) -> None:
    path = tmp_path / "failed-v44.sqlite3"
    task_id, event_id = _create_populated_v43(path)
    broken = migrations.MIGRATION_44.replace(
        "\nCOMMIT;\n",
        "\nSELECT missing_metric_lifecycle_function();\nCOMMIT;\n",
    )
    assert broken != migrations.MIGRATION_44

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.OperationalError):
            _apply_migration_atomically(
                connection,
                version=44,
                script=broken,
                checksum=hashlib.sha256(broken.encode()).hexdigest(),
                applied_at=NOW.isoformat(timespec="microseconds"),
            )

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 43
        assert connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 43
        assert connection.execute(
            """SELECT event_id FROM task_lifecycle_events
               WHERE task_id=?""",
            (task_id,),
        ).fetchone()[0] == event_id
        assert connection.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table'
                 AND name='metric_lifecycle_evidence_proposals'"""
        ).fetchone() is None
        assert connection.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table'
                 AND name='metric_lifecycle_evidence_windows'"""
        ).fetchone() is None
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_database_registry_places_m44_after_byte_frozen_m43() -> None:
    assert database_module.MIGRATION_43 is migrations.MIGRATION_43
    assert database_module.MIGRATION_44 is migrations.MIGRATION_44
    assert SCHEMA_VERSION == 61
    assert hashlib.sha256(migrations.MIGRATION_43.encode()).hexdigest() == (
        MIGRATION_43_FROZEN_SHA256
    )
    assert "metric_lifecycle_evidence_proposals" not in migrations.MIGRATION_43
    assert "metric_lifecycle_evidence_proposals" in migrations.MIGRATION_44
