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
MIGRATION_42_FROZEN_SHA256 = (
    "a17445627b435d04b84cad5bdcfcbfac963ea8069b481baf50eba652a8e78345"
)


def _create_populated_v42(path) -> tuple[str, str, str]:
    scripts = (_MIGRATION_1,) + tuple(
        getattr(migrations, f"MIGRATION_{version}") for version in range(2, 43)
    )
    timestamp = NOW.isoformat(timespec="microseconds")
    installation_id = "1" * 64
    project_id = "2" * 64
    session_id = "3" * 64
    task_id = "4" * 64
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=ON")
        for script in scripts:
            connection.executescript(script)
        connection.execute(
            """
            CREATE TABLE schema_migrations(
                version INTEGER PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            "INSERT INTO schema_migrations VALUES (?,?,?)",
            tuple(
                (
                    version,
                    hashlib.sha256(script.encode("utf-8")).hexdigest(),
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
            "INSERT INTO projects(project_id,installation_id,provider,created_at) VALUES (?,?,?,?)",
            (project_id, installation_id, "synthetic", timestamp),
        )
        connection.execute(
            """
            INSERT INTO sessions(
                session_id,installation_id,project_id,provider,
                provider_version,adapter_version,source_schema_version,
                started_at,ended_at,terminal_state,events_complete,
                created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
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
            """
            INSERT INTO task_revisions(
                task_id,revision,task_type,lifecycle_state,
                input_fingerprint,created_at
            ) VALUES (?,1,'feature_implementation','confirmed',?,?)
            """,
            (task_id, "5" * 64, timestamp),
        )
        connection.execute(
            """INSERT INTO task_revision_sessions(
                   task_id,revision,session_id,ordinal
               ) VALUES (?,1,?,0)""",
            (task_id, session_id),
        )
        connection.execute("PRAGMA user_version=42")
        connection.commit()
    return task_id, project_id, session_id


def test_populated_v42_upgrades_to_v43_without_backfill_or_m42_drift(tmp_path) -> None:
    path = tmp_path / "populated-v42.sqlite3"
    task_id, _project_id, session_id = _create_populated_v42(path)
    frozen_checksum = hashlib.sha256(migrations.MIGRATION_42.encode("utf-8")).hexdigest()
    assert frozen_checksum == MIGRATION_42_FROZEN_SHA256

    Database(path).initialize()

    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT version,checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert SCHEMA_VERSION == 61
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert tuple(row[0] for row in rows) == tuple(range(1, 62))
        assert rows[41][1] == frozen_checksum
        assert rows[42][1] == hashlib.sha256(
            migrations.MIGRATION_43.encode("utf-8")
        ).hexdigest()
        assert connection.execute(
            "SELECT COUNT(*) FROM task_lifecycle_events"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT input_fingerprint FROM task_revisions WHERE task_id=? AND revision=1",
            (task_id,),
        ).fetchone()[0] == "5" * 64
        assert connection.execute(
            "SELECT session_id FROM task_revision_sessions WHERE task_id=?",
            (task_id,),
        ).fetchone()[0] == session_id
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='session_model_ensemble_metric_states_v2_r3'"
        ).fetchone() is not None
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_failed_v43_rolls_back_schema_ledger_and_user_version_together(tmp_path) -> None:
    path = tmp_path / "failed-v43.sqlite3"
    task_id, _project_id, _session_id = _create_populated_v42(path)
    broken = migrations.MIGRATION_43.replace(
        "\nCOMMIT;\n",
        "\nSELECT missing_lifecycle_migration_function();\nCOMMIT;\n",
    )
    assert broken != migrations.MIGRATION_43

    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.OperationalError):
            _apply_migration_atomically(
                connection,
                version=43,
                script=broken,
                checksum=hashlib.sha256(broken.encode("utf-8")).hexdigest(),
                applied_at=NOW.isoformat(timespec="microseconds"),
            )

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 42
        assert connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == 42
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_lifecycle_events'"
        ).fetchone() is None
        assert connection.execute(
            "SELECT 1 FROM task_revisions WHERE task_id=? AND revision=1",
            (task_id,),
        ).fetchone() is not None
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='session_model_ensemble_metric_states_v2_r3'"
        ).fetchone() is not None
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_database_registry_places_frozen_m42_before_lifecycle_m43() -> None:
    assert database_module.MIGRATION_42 is migrations.MIGRATION_42
    assert database_module.MIGRATION_43 is migrations.MIGRATION_43
    assert SCHEMA_VERSION == 61
    assert "task_lifecycle_events" not in migrations.MIGRATION_42
    assert "task_lifecycle_events" in migrations.MIGRATION_43
