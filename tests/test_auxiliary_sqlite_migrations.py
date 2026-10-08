"""Synthetic migration integrity tests for every auxiliary SQLite store."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from prompt_enhancer.application import annotation as annotation_module
from prompt_enhancer.application import shared_folders as shared_folder_module
from prompt_enhancer.application.annotation import (
    AnnotationError,
    CentralAnnotationStore,
)
from prompt_enhancer.application.maintenance.inventory import (
    APPLICATION_PATH_INVENTORY,
    AppPathKind,
    BackupDisposition,
    ExportDisposition,
    PathSensitivity,
)
from prompt_enhancer.application.shared_folders import (
    SharedFolderError,
    SharedFolderStore,
)
from prompt_enhancer.infrastructure.paid_product import sqlite as paid_module
from prompt_enhancer.infrastructure.paid_product.sqlite import PaidProductSqliteStore
from prompt_enhancer.infrastructure.social import sqlite as social_module
from prompt_enhancer.infrastructure.social.sqlite import SocialSqliteDatabase
from prompt_enhancer.sqlite_migration_integrity import (
    SqliteMigrationIntegrity,
    SqliteMigrationIntegrityError,
)


SYNTHETIC_TIME = "2047-03-08T12:00:00+00:00"
_FAMILIES = ("social", "paid_product", "shared_folder", "central_annotation")


def _database_path(root: Path, family: str) -> Path:
    names = {
        "social": social_module.SOCIAL_DATABASE_FILENAME,
        "paid_product": paid_module.PAID_PRODUCT_DATABASE_FILENAME,
        "shared_folder": shared_folder_module.SHARED_FOLDER_DATABASE_FILENAME,
        "central_annotation": annotation_module.CENTRAL_ANNOTATION_DATABASE_FILENAME,
    }
    return root / names[family]


def _integrity(family: str) -> SqliteMigrationIntegrity:
    contracts = {
        "social": social_module._MIGRATION_INTEGRITY,
        "paid_product": paid_module._MIGRATION_INTEGRITY,
        "shared_folder": shared_folder_module._SHARED_FOLDER_MIGRATION_INTEGRITY,
        "central_annotation": annotation_module._CENTRAL_ANNOTATION_MIGRATION_INTEGRITY,
    }
    return contracts[family]


def _open(family: str, path: Path) -> None:
    if family == "social":
        assert SocialSqliteDatabase(path).initialize() == _integrity(family).schema_version
    elif family == "paid_product":
        assert PaidProductSqliteStore(path).initialize() == _integrity(family).schema_version
    elif family == "shared_folder":
        SharedFolderStore(path)
    else:
        CentralAnnotationStore(path)


def _build_historical(path: Path, family: str, head: int) -> None:
    """Build an exact pre-checksum schema without invoking current code."""

    integrity = _integrity(family)
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        if family in {"social", "paid_product"}:
            integrity.create_ledger(connection)
        for version, statements in integrity.migrations:
            if version > head:
                break
            for statement in statements:
                connection.execute(statement)
            if family in {"social", "paid_product"}:
                connection.execute(
                    f"INSERT INTO {integrity.ledger_table}(version, applied_at) VALUES (?, ?)",
                    (version, SYNTHETIC_TIME),
                )
        connection.execute("COMMIT")
    finally:
        connection.close()


def _insert_representative_record(path: Path, family: str, head: int) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        if family == "social" and head == 2:
            connection.execute(
                """
                INSERT INTO social_accounts(
                    organization_id, account_id, state, created_at, deleted_at
                ) VALUES (?, ?, 'active', ?, NULL)
                """,
                ("soc_" + "1" * 64, "soc_" + "2" * 64, SYNTHETIC_TIME),
            )
        elif family == "paid_product":
            connection.execute(
                "INSERT INTO paid_accounts(account_id, body_json) VALUES (?, ?)",
                ("synthetic-account", json.dumps({"fixture": "synthetic"})),
            )
        elif family == "shared_folder":
            connection.execute(
                """
                INSERT INTO shared_folders(
                    share_id, name, path, token_hash, created_at, revoked_at
                ) VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (
                    "1" * 32,
                    "Synthetic workspace",
                    "X:/synthetic/workspace",
                    "2" * 64,
                    SYNTHETIC_TIME,
                ),
            )
        elif family == "central_annotation":
            window = '{"fixture":"synthetic-redacted-window"}'
            connection.execute(
                """
                INSERT INTO central_annotations(
                    user_label, session_id, project_id, provider, window_chars,
                    redacted_window, labels_json, model_identity,
                    prompt_version, submitted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "synthetic-owner",
                    "3" * 64,
                    "4" * 64,
                    "synthetic",
                    len(window),
                    window,
                    '{"interaction_quality":"high"}',
                    "synthetic-model",
                    "synthetic-prompt-v1",
                    SYNTHETIC_TIME,
                ),
            )
        connection.commit()
    finally:
        connection.close()


def _assert_representative_record(path: Path, family: str, head: int) -> None:
    connection = sqlite3.connect(path)
    try:
        if family == "social" and head == 2:
            row = connection.execute(
                "SELECT state FROM social_accounts WHERE account_id=?",
                ("soc_" + "2" * 64,),
            ).fetchone()
            assert row == ("active",)
        elif family == "paid_product":
            row = connection.execute(
                "SELECT body_json FROM paid_accounts WHERE account_id=?",
                ("synthetic-account",),
            ).fetchone()
            assert row == (json.dumps({"fixture": "synthetic"}),)
        elif family == "shared_folder":
            row = connection.execute(
                "SELECT name FROM shared_folders WHERE share_id=?", ("1" * 32,)
            ).fetchone()
            assert row == ("Synthetic workspace",)
        elif family == "central_annotation":
            row = connection.execute(
                "SELECT redacted_window FROM central_annotations WHERE session_id=?",
                ("3" * 64,),
            ).fetchone()
            assert row == ('{"fixture":"synthetic-redacted-window"}',)
    finally:
        connection.close()


def _snapshot(path: Path) -> tuple[object, ...]:
    connection = sqlite3.connect(path)
    try:
        schema = tuple(
            (str(row[0]), str(row[1]), str(row[2] or ""))
            for row in connection.execute(
                """
                SELECT type, name, sql FROM sqlite_master
                WHERE name NOT LIKE 'sqlite_%'
                ORDER BY type, name
                """
            ).fetchall()
        )
        counts = []
        for kind, name, _sql in schema:
            if kind != "table":
                continue
            quoted = name.replace('"', '""')
            counts.append(
                (name, int(connection.execute(f'SELECT COUNT(*) FROM "{quoted}"').fetchone()[0]))
            )
        return (
            int(connection.execute("PRAGMA user_version").fetchone()[0]),
            schema,
            tuple(counts),
        )
    finally:
        connection.close()


def _assert_current_provenance(path: Path, family: str) -> None:
    integrity = _integrity(family)
    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone() == (
            integrity.schema_version,
        )
        versions = tuple(
            int(row[0])
            for row in connection.execute(
                f"SELECT version FROM {integrity.ledger_table} ORDER BY version"
            ).fetchall()
        )
        assert versions == tuple(range(1, integrity.schema_version + 1))
        checksums = {
            int(row[0]): str(row[1])
            for row in connection.execute(
                f"SELECT version, checksum FROM {integrity.checksum_table} ORDER BY version"
            ).fetchall()
        }
        assert checksums == dict(integrity.checksums)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        connection.execute("PRAGMA foreign_keys=ON")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("family", "head"),
    (
        ("social", 1),
        ("social", 2),
        ("paid_product", 1),
        ("shared_folder", 1),
        ("central_annotation", 1),
        ("central_annotation", 2),
    ),
)
def test_every_supported_historical_head_upgrades_and_reopens_with_data(
    tmp_path: Path,
    family: str,
    head: int,
) -> None:
    path = _database_path(tmp_path, family)
    _build_historical(path, family, head)
    _insert_representative_record(path, family, head)

    _open(family, path)
    _assert_current_provenance(path, family)
    _assert_representative_record(path, family, head)

    _open(family, path)
    _assert_current_provenance(path, family)
    _assert_representative_record(path, family, head)


@pytest.mark.parametrize("family", _FAMILIES)
def test_unknown_unversioned_shape_fails_without_mutation(
    tmp_path: Path,
    family: str,
) -> None:
    path = _database_path(tmp_path, family)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE synthetic_unknown_table(value TEXT)")
        connection.execute("INSERT INTO synthetic_unknown_table VALUES ('fixture')")
    before = _snapshot(path)

    with pytest.raises(SqliteMigrationIntegrityError) as captured:
        _open(family, path)

    assert captured.value.code == f"{family}_migration_history_incomplete"
    assert _snapshot(path) == before


@pytest.mark.parametrize("family", ("shared_folder", "central_annotation"))
def test_legacy_shape_with_matching_columns_but_altered_types_is_not_adopted(
    tmp_path: Path,
    family: str,
) -> None:
    path = _database_path(tmp_path, family)
    statements = _integrity(family).migrations[0][1]
    with sqlite3.connect(path) as connection:
        for index, statement in enumerate(statements):
            if family == "shared_folder" and index == 0:
                statement = statement.replace(
                    "name TEXT NOT NULL", "name BLOB NOT NULL", 1
                )
            elif family == "central_annotation":
                statement = statement.replace(
                    "window_chars INTEGER NOT NULL",
                    "window_chars TEXT NOT NULL",
                    1,
                )
            connection.execute(statement)
    before = _snapshot(path)

    with pytest.raises(SqliteMigrationIntegrityError) as captured:
        _open(family, path)

    assert captured.value.code == f"{family}_migration_history_incomplete"
    assert _snapshot(path) == before


@pytest.mark.parametrize("family", _FAMILIES)
@pytest.mark.parametrize(
    ("defect", "suffix"),
    (
        ("gap", "migration_history_incomplete"),
        ("checksum", "migration_checksum_mismatch"),
        ("head", "schema_version_mismatch"),
    ),
)
def test_corrupt_provenance_fails_closed_without_repairing_it(
    tmp_path: Path,
    family: str,
    defect: str,
    suffix: str,
) -> None:
    path = _database_path(tmp_path, family)
    _open(family, path)
    integrity = _integrity(family)
    with sqlite3.connect(path) as connection:
        if defect == "gap":
            missing = max(1, integrity.schema_version - 1)
            connection.execute(
                f"DELETE FROM {integrity.checksum_table} WHERE version=?", (missing,)
            )
            connection.execute(
                f"DELETE FROM {integrity.ledger_table} WHERE version=?", (missing,)
            )
        elif defect == "checksum":
            connection.execute(
                f"UPDATE {integrity.checksum_table} SET checksum=? WHERE version=?",
                ("0" * 64, integrity.schema_version),
            )
        else:
            connection.execute(f"PRAGMA user_version={integrity.schema_version - 1}")
    before = _snapshot(path)

    with pytest.raises(SqliteMigrationIntegrityError) as captured:
        _open(family, path)

    assert captured.value.code == f"{family}_{suffix}"
    assert _snapshot(path) == before


@pytest.mark.parametrize(
    ("family", "error_type", "message"),
    (
        ("social", RuntimeError, "social_schema_integrity_invalid"),
        ("paid_product", RuntimeError, "paid_product_schema_integrity_invalid"),
        ("shared_folder", SharedFolderError, "shared_folder_schema_integrity_invalid"),
        (
            "central_annotation",
            AnnotationError,
            "central_annotation_schema_integrity_invalid",
        ),
    ),
)
def test_extra_current_table_is_refused_without_mutation(
    tmp_path: Path,
    family: str,
    error_type: type[Exception],
    message: str,
) -> None:
    path = _database_path(tmp_path, family)
    _open(family, path)
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE synthetic_unregistered_table(value TEXT)")
    before = _snapshot(path)

    with pytest.raises(error_type, match=f"^{message}$"):
        _open(family, path)

    assert _snapshot(path) == before


@pytest.mark.parametrize(
    ("family", "head"),
    (
        ("social", 2),
        ("paid_product", 1),
        ("shared_folder", 1),
        ("central_annotation", 2),
    ),
)
def test_late_migration_failure_rolls_back_schema_ledger_and_sqlite_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    family: str,
    head: int,
) -> None:
    path = _database_path(tmp_path, family)
    _build_historical(path, family, head)
    _insert_representative_record(path, family, head)
    before = _snapshot(path)
    original = SqliteMigrationIntegrity.apply_pending

    def fail_after_apply(
        self: SqliteMigrationIntegrity,
        connection: sqlite3.Connection,
        *,
        current: int,
        applied_at: str,
    ) -> None:
        original(
            self,
            connection,
            current=current,
            applied_at=applied_at,
        )
        raise RuntimeError("synthetic_late_migration_failure")

    monkeypatch.setattr(SqliteMigrationIntegrity, "apply_pending", fail_after_apply)
    with pytest.raises(RuntimeError, match="^synthetic_late_migration_failure$"):
        _open(family, path)

    assert _snapshot(path) == before
    _assert_representative_record(path, family, head)


def test_bootstrap_auxiliary_databases_are_secret_inventory_families() -> None:
    by_id = {entry.path_id: entry for entry in APPLICATION_PATH_INVENTORY}
    for path_id, filename in (
        ("shared_folder_database", shared_folder_module.SHARED_FOLDER_DATABASE_FILENAME),
        (
            "central_annotation_database",
            annotation_module.CENTRAL_ANNOTATION_DATABASE_FILENAME,
        ),
    ):
        database = by_id[path_id]
        assert database.relative_parts == (filename,)
        assert database.kind is AppPathKind.SQLITE_DATABASE
        assert database.sensitivity is PathSensitivity.SECRET
        assert database.export is ExportDisposition.EXCLUDED
        assert database.backup is BackupDisposition.SQLITE_ONLINE
        for suffix in ("wal", "shm"):
            sidecar = by_id[f"{path_id}_{suffix}"]
            assert sidecar.parent_path_id == path_id
            assert sidecar.relative_parts == (f"{filename}-{suffix}",)
            assert sidecar.kind is AppPathKind.SQLITE_SIDECAR
            assert sidecar.sensitivity is PathSensitivity.SECRET
            assert sidecar.export is ExportDisposition.EXCLUDED
            assert sidecar.backup is BackupDisposition.EXCLUDED
