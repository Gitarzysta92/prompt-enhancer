from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import sqlite3

from fastapi.testclient import TestClient
import pytest

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.analysis.deterministic import (
    DEFAULT_METRIC_PACK,
    EVENT_COUNT_DEFINITION,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import (
    SCHEMA_VERSION,
    Database,
    _MIGRATION_1,
    _definition_checksum,
)
from prompt_enhancer.infrastructure.sqlite.migrations import (
    MIGRATION_2,
    MIGRATION_3,
    MIGRATION_4,
    MIGRATION_5,
    MIGRATION_6,
)
from prompt_enhancer.metrics import (
    METRIC_ENGINE_VERSION,
    NOT_APPLICABLE_VERSION,
    compute_session_metrics,
)


EXAMPLE_TIME = datetime(2026, 2, 1, 10, 0, tzinfo=UTC)
EXAMPLE_TOKEN = "example_local_api_token_do_not_use_123456789"
INSTALLATION_ID = "1" * 64
PROJECT_ID = "2" * 64
SESSION_ID = "3" * 64
LEGACY_PACK_IDENTITY = ("legacy.unknown.session", 1)


def _create_v5_database(path) -> None:
    migrations = (
        (1, _MIGRATION_1),
        (2, MIGRATION_2),
        (3, MIGRATION_3),
        (4, MIGRATION_4),
        (5, MIGRATION_5),
    )
    timestamp = EXAMPLE_TIME.isoformat()
    definition = EVENT_COUNT_DEFINITION
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for _, script in migrations:
            connection.executescript(script)
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO schema_migrations(version, checksum, applied_at)
            VALUES (?, ?, ?)
            """,
            tuple(
                (
                    version,
                    hashlib.sha256(script.encode("utf-8")).hexdigest(),
                    timestamp,
                )
                for version, script in migrations
            ),
        )
        connection.execute(
            "INSERT INTO installations(installation_id, provider, created_at) VALUES (?, ?, ?)",
            (INSTALLATION_ID, "synthetic", timestamp),
        )
        connection.execute(
            """
            INSERT INTO projects(project_id, installation_id, provider, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (PROJECT_ID, INSTALLATION_ID, "synthetic", timestamp),
        )
        connection.execute(
            """
            INSERT INTO sessions(
                session_id, installation_id, project_id, provider,
                provider_version, adapter_version, source_schema_version,
                started_at, ended_at, terminal_state, events_complete,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                SESSION_ID,
                INSTALLATION_ID,
                PROJECT_ID,
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
            """
            INSERT INTO metric_definitions(
                key, version, dimension, display_name, description, unit,
                source, algorithm_version, definition_checksum
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                definition.key,
                definition.version,
                definition.dimension,
                definition.display_name,
                definition.description,
                definition.unit,
                definition.source.value,
                METRIC_ENGINE_VERSION,
                _definition_checksum(definition),
            ),
        )
        connection.execute(
            """
            INSERT INTO metric_results(
                session_id, key, version, numeric_value, text_value, unit,
                source, observed_count, eligible_count, coverage, confidence,
                metric_engine_version, redactor_version, model_id,
                model_revision, tokenizer_id, prompt_version, rubric_version,
                computed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                SESSION_ID,
                definition.key,
                definition.version,
                0,
                None,
                definition.unit,
                definition.source.value,
                1,
                1,
                1.0,
                1.0,
                METRIC_ENGINE_VERSION,
                NOT_APPLICABLE_VERSION,
                None,
                None,
                None,
                None,
                None,
                timestamp,
            ),
        )
        connection.execute("PRAGMA user_version = 5")
        connection.commit()


def _api_metric_identity(database: Database, tmp_path) -> set[tuple[str, int]]:
    app = create_app(
        settings=AppSettings(home=tmp_path / "synthetic-app-home"),
        database=database,
        api_token=EXAMPLE_TOKEN,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get(
            f"/v1/sessions/{SESSION_ID}/metrics",
            headers={API_TOKEN_HEADER: EXAMPLE_TOKEN},
        )
    assert response.status_code == 200
    return {
        (item["metric_pack_key"], item["metric_pack_version"])
        for item in response.json()["metrics"]
    }


def test_v5_session_projection_upgrades_with_truthful_unknown_pack(tmp_path) -> None:
    path = tmp_path / "metrics.sqlite3"
    _create_v5_database(path)

    database = Database(path)
    database.initialize()

    metrics = database.get_session_metrics(SESSION_ID)
    assert database.summary()["schema_version"] == SCHEMA_VERSION == 61
    [legacy_metric] = metrics
    assert legacy_metric["key"] == EVENT_COUNT_DEFINITION.key
    assert legacy_metric["version"] == EVENT_COUNT_DEFINITION.version
    assert legacy_metric["numeric_value"] == 0
    assert legacy_metric["text_value"] is None
    assert legacy_metric["unit"] == EVENT_COUNT_DEFINITION.unit
    assert legacy_metric["source"] == EVENT_COUNT_DEFINITION.source.value
    assert legacy_metric["observed_count"] == 1
    assert legacy_metric["eligible_count"] == 1
    assert legacy_metric["coverage"] == 1.0
    assert legacy_metric["confidence"] == 1.0
    assert legacy_metric["metric_engine_version"] == METRIC_ENGINE_VERSION
    assert legacy_metric["redactor_version"] == NOT_APPLICABLE_VERSION
    assert legacy_metric["computed_at"] == EXAMPLE_TIME.isoformat()
    assert {
        (item["metric_pack_key"], item["metric_pack_version"])
        for item in metrics
    } == {LEGACY_PACK_IDENTITY}

    with sqlite3.connect(path) as connection:
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info(metric_results)")
        }
        foreign_key_violations = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE metric_results SET metric_pack_key = ? WHERE session_id = ?",
                ("unsafe pack key", SESSION_ID),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE metric_results SET metric_pack_version = 0 WHERE session_id = ?",
                (SESSION_ID,),
            )

    assert user_version == SCHEMA_VERSION
    assert [row[0] for row in versions] == list(range(1, SCHEMA_VERSION + 1))
    assert columns["metric_pack_key"][3] == 1
    assert columns["metric_pack_key"][4] is None
    assert columns["metric_pack_version"][3] == 1
    assert columns["metric_pack_version"][4] is None
    assert foreign_key_violations == []


def test_reanalysis_atomically_replaces_legacy_pack_and_api_exposes_it(
    tmp_path,
) -> None:
    path = tmp_path / "metrics.sqlite3"
    _create_v5_database(path)
    database = Database(path)
    database.initialize()

    assert _api_metric_identity(database, tmp_path) == {LEGACY_PACK_IDENTITY}

    session = database.get_session(SESSION_ID)
    assert session is not None
    observations = compute_session_metrics(
        session, database.get_session_events(SESSION_ID)
    )
    changed = database.replace_session_metrics(
        SESSION_ID,
        observations,
        metric_pack_key=DEFAULT_METRIC_PACK.key,
        metric_pack_version=DEFAULT_METRIC_PACK.version,
        metric_engine_version=METRIC_ENGINE_VERSION,
    )

    assert changed == len(observations)
    assert _api_metric_identity(database, tmp_path) == {
        (DEFAULT_METRIC_PACK.key, DEFAULT_METRIC_PACK.version)
    }
    assert database.replace_session_metrics(
        SESSION_ID,
        observations,
        metric_pack_key=DEFAULT_METRIC_PACK.key,
        metric_pack_version=DEFAULT_METRIC_PACK.version,
        metric_engine_version=METRIC_ENGINE_VERSION,
    ) == 0
