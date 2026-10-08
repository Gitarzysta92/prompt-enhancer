from __future__ import annotations

import pytest

from prompt_enhancer.database import Database, DatabaseError


def test_database_rejects_symlinked_state_directory_before_resolution(tmp_path) -> None:
    target = tmp_path / "database-target"
    target.mkdir()
    link = tmp_path / "database-link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc.__class__.__name__}")

    database = Database(link / "metrics.sqlite3")
    with pytest.raises(DatabaseError, match="symlink"):
        database.initialize()
