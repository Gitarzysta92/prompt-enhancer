"""The optional social schema never joins the analyzer database."""

from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

from prompt_enhancer.infrastructure.social import (
    SOCIAL_DATABASE_FILENAME,
    SOCIAL_SCHEMA_VERSION,
    SocialSqliteDatabase,
)


def test_social_database_uses_dedicated_file_and_migration_ledger(tmp_path: Path) -> None:
    database = SocialSqliteDatabase.under(tmp_path)
    assert database.path.name == SOCIAL_DATABASE_FILENAME
    assert database.initialize() == SOCIAL_SCHEMA_VERSION
    assert database.initialize() == SOCIAL_SCHEMA_VERSION

    connection = sqlite3.connect(database.path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "social_schema_migrations" in tables
        assert "schema_migrations" not in tables
        assert "sessions" not in tables
        assert "events" not in tables
        assert "metrics" not in tables
        version = connection.execute(
            "SELECT MAX(version) FROM social_schema_migrations"
        ).fetchone()[0]
        assert version == SOCIAL_SCHEMA_VERSION
    finally:
        connection.close()


def test_social_schema_has_no_plaintext_file_bytes_paths_or_analyzer_join_columns(
    tmp_path: Path,
) -> None:
    database = SocialSqliteDatabase.under(tmp_path)
    database.initialize()
    connection = sqlite3.connect(database.path)
    try:
        tables = tuple(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
            if row[0] != "social_schema_migrations"
        )
        columns = {
            row[1]
            for table in tables
            for row in connection.execute(f'PRAGMA table_info("{table}")')
        }
    finally:
        connection.close()
    forbidden = {
        "plaintext",
        "ciphertext",
        "message_body",
        "message_text",
        "file_bytes",
        "file_path",
        "absolute_path",
        "file_name",
        "session_id",
        "project_id",
        "prompt_id",
        "analytics_user_id",
    }
    assert columns.isdisjoint(forbidden)


def test_social_database_refuses_analyzer_or_arbitrary_filename(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        SocialSqliteDatabase(tmp_path / "metrics.sqlite3").initialize()
    with pytest.raises(ValueError):
        SocialSqliteDatabase(tmp_path / "other.sqlite3").initialize()


def test_social_schema_rejects_non_namespaced_join_identifiers(tmp_path: Path) -> None:
    database = SocialSqliteDatabase.under(tmp_path)
    database.initialize()
    connection = sqlite3.connect(database.path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO social_accounts(
                    organization_id, account_id, state, created_at
                ) VALUES (?, ?, 'active', '2047-03-08T12:00:00+00:00')
                """,
                ("a" * 64, "b" * 64),
            )
    finally:
        connection.close()


def test_social_database_refuses_symlink_target_when_supported(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    try:
        linked.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable on this platform")
    with pytest.raises(ValueError):
        SocialSqliteDatabase.under(linked).initialize()


def test_social_database_refuses_dangling_file_symlink_before_any_write(
    tmp_path: Path,
) -> None:
    target = tmp_path / "synthetic-target.sqlite3"
    app_home = tmp_path / "app-home"
    app_home.mkdir()
    linked_database = app_home / SOCIAL_DATABASE_FILENAME
    try:
        linked_database.symlink_to(target)
    except OSError:
        pytest.skip("file symlinks unavailable on this platform")
    assert linked_database.exists() is False
    with pytest.raises(ValueError):
        SocialSqliteDatabase.under(app_home).initialize()
    assert target.exists() is False
