"""SQLite-consistent backup primitive using ``Connection.backup`` only."""

from __future__ import annotations

import sqlite3


class SqliteOnlineBackupError(RuntimeError):
    """Sanitized failure with no database path or SQL content."""


def backup_open_database(
    source: sqlite3.Connection,
    destination: sqlite3.Connection,
    *,
    pages_per_step: int = 256,
) -> None:
    if isinstance(pages_per_step, bool) or not 1 <= pages_per_step <= 4_096:
        raise ValueError("SQLite backup step bound is invalid")
    try:
        source.backup(destination, pages=pages_per_step, sleep=0.0)
        row = destination.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.Error as error:
        raise SqliteOnlineBackupError("sqlite_online_backup_failed") from error
    if row is None or row[0] != "ok":
        raise SqliteOnlineBackupError("sqlite_backup_integrity_failed")
