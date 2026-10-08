"""Shared team folders (ADR 0018): one folder, several people, agents on every side.

A person explicitly shares one folder; the share token (returned once, stored
only as a hash) lets peers list, read and write files through ``/p2p/v1/*``.
The receiving side registers a peer link and pulls the folder into a local
target, which is then an ordinary agent workspace. Writes carry the hash of
the version they were based on; a mismatch lands as a conflict copy beside the
original so nothing is silently lost. The central/login server is never in the
data path.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field

from ..config import lexical_absolute_path, path_has_symlink_component
from ..domain import StrictModel
from ..sqlite_migration_integrity import SqliteMigrationIntegrity

SHARED_FOLDERS_CONTRACT_VERSION = "shared-folders.v1"
SHARED_FOLDER_DATABASE_FILENAME = "shared-folders.sqlite3"
SHARED_FOLDER_SCHEMA_VERSION = 2
MAX_SHARES = 16
MAX_PEER_LINKS = 16
MAX_MANIFEST_FILES = 2_000
MAX_FILE_BYTES = 4_000_000
MAX_PULL_FILES = 500
SKIP_DIRS = frozenset({".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache", "dist", "build", ".next", ".cache"})
_SHARE_ID = re.compile(r"^[0-9a-f]{32}$")
_PEER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")


class SharedFolderError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SharedFolder(StrictModel):
    contract_version: Literal[SHARED_FOLDERS_CONTRACT_VERSION] = SHARED_FOLDERS_CONTRACT_VERSION
    share_id: str
    name: str
    path: str
    created_at: datetime
    revoked_at: datetime | None = None
    #: Present only in the response to the share action; never stored or listed.
    share_token: str | None = None


class SharedFolderList(StrictModel):
    contract_version: Literal[SHARED_FOLDERS_CONTRACT_VERSION] = SHARED_FOLDERS_CONTRACT_VERSION
    shares: tuple[SharedFolder, ...]


class ManifestEntry(StrictModel):
    path: str
    size: int = Field(ge=0)
    sha256: str
    modified_at: datetime


class FolderManifest(StrictModel):
    contract_version: Literal[SHARED_FOLDERS_CONTRACT_VERSION] = SHARED_FOLDERS_CONTRACT_VERSION
    share_id: str
    name: str
    files: tuple[ManifestEntry, ...]
    truncated: bool = False


class FileContent(StrictModel):
    contract_version: Literal[SHARED_FOLDERS_CONTRACT_VERSION] = SHARED_FOLDERS_CONTRACT_VERSION
    path: str
    content_b64: str
    sha256: str
    size: int = Field(ge=0)


class WriteFileRequest(StrictModel):
    content_b64: str = Field(max_length=(MAX_FILE_BYTES * 4) // 3 + 16)
    #: Hash of the version this edit was based on; None means "new file".
    base_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    peer_name: str = Field(default="peer", pattern=_PEER_NAME.pattern)


class WriteFileResult(StrictModel):
    contract_version: Literal[SHARED_FOLDERS_CONTRACT_VERSION] = SHARED_FOLDERS_CONTRACT_VERSION
    path: str
    stored_as: str
    conflict: bool = False
    sha256: str


class PeerLink(StrictModel):
    contract_version: Literal[SHARED_FOLDERS_CONTRACT_VERSION] = SHARED_FOLDERS_CONTRACT_VERSION
    link_id: str
    url: str
    share_id: str
    target: str
    name: str | None = None
    joined_at: datetime


class PeerLinkList(StrictModel):
    contract_version: Literal[SHARED_FOLDERS_CONTRACT_VERSION] = SHARED_FOLDERS_CONTRACT_VERSION
    links: tuple[PeerLink, ...]


class JoinRequest(StrictModel):
    url: str = Field(min_length=1, max_length=300)
    share_id: str = Field(pattern=_SHARE_ID.pattern)
    share_token: str = Field(min_length=16, max_length=128)
    target: str = Field(min_length=1, max_length=1024)


class SyncReport(StrictModel):
    contract_version: Literal[SHARED_FOLDERS_CONTRACT_VERSION] = SHARED_FOLDERS_CONTRACT_VERSION
    link_id: str
    pulled: int = Field(default=0, ge=0)
    pushed: int = Field(default=0, ge=0)
    conflicts: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative.replace("\\", "/"))
    if pure.is_absolute() or any(part in ("..", "") for part in pure.parts) or len(pure.parts) == 0:
        raise SharedFolderError("path_invalid")
    resolved = (root / Path(*pure.parts)).resolve()
    if root != resolved and root not in resolved.parents:
        raise SharedFolderError("path_invalid")
    return resolved


_SHARED_FOLDER_SCHEMA_V1 = (
    """
    CREATE TABLE shared_folders (
        share_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        path TEXT NOT NULL,
        token_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        revoked_at TEXT
    )
    """,
    """
    CREATE TABLE link_file_state (
        link_id TEXT NOT NULL,
        path TEXT NOT NULL,
        synced_sha256 TEXT NOT NULL,
        PRIMARY KEY (link_id, path)
    )
    """,
    """
    CREATE TABLE peer_links (
        link_id TEXT PRIMARY KEY,
        url TEXT NOT NULL,
        share_id TEXT NOT NULL,
        token TEXT NOT NULL,
        target TEXT NOT NULL,
        name TEXT,
        joined_at TEXT NOT NULL
    )
    """,
)

_SHARED_FOLDER_SCHEMA_V2 = (
    """
    CREATE TABLE shared_folder_migration_checksums (
        version INTEGER PRIMARY KEY
            REFERENCES shared_folder_schema_migrations(version) ON DELETE RESTRICT
            CHECK(version > 0),
        checksum TEXT NOT NULL CHECK(
            length(checksum)=64 AND checksum NOT GLOB '*[^0-9a-f]*'
        )
    ) STRICT
    """,
)

_SHARED_FOLDER_MIGRATIONS = (
    (1, _SHARED_FOLDER_SCHEMA_V1),
    (2, _SHARED_FOLDER_SCHEMA_V2),
)

_SHARED_FOLDER_TABLE_COLUMNS = {
    "shared_folders": (
        "share_id",
        "name",
        "path",
        "token_hash",
        "created_at",
        "revoked_at",
    ),
    "link_file_state": ("link_id", "path", "synced_sha256"),
    "peer_links": (
        "link_id",
        "url",
        "share_id",
        "token",
        "target",
        "name",
        "joined_at",
    ),
}


def _normalized_schema_sql(value: str) -> str:
    return " ".join(value.casefold().split()).replace(
        "create table if not exists ", "create table ", 1
    )


_SHARED_FOLDER_APPLICATION_SQL = {
    match.group(1): _normalized_schema_sql(statement)
    for statement in _SHARED_FOLDER_SCHEMA_V1
    if (
        match := re.search(
            r"\bCREATE TABLE(?: IF NOT EXISTS)?\s+([a-z][a-z0-9_]*)",
            statement,
            re.IGNORECASE,
        )
    )
}

_SHARED_FOLDER_MIGRATION_INTEGRITY = SqliteMigrationIntegrity(
    scope="shared_folder",
    ledger_table="shared_folder_schema_migrations",
    checksum_table="shared_folder_migration_checksums",
    schema_version=SHARED_FOLDER_SCHEMA_VERSION,
    checksum_introduced_version=2,
    migrations=_SHARED_FOLDER_MIGRATIONS,
    application_tables=frozenset(_SHARED_FOLDER_TABLE_COLUMNS),
)


class SharedFolderStore:
    """Shares and peer links in one isolated, versioned SQLite file."""

    def __init__(self, path: Path) -> None:
        self._path = lexical_absolute_path(path)
        self._lock = threading.Lock()
        self._initialize()

    def _validated_path(self) -> Path:
        path = lexical_absolute_path(self._path)
        if path_has_symlink_component(path.parent) or path_has_symlink_component(path):
            raise SharedFolderError("shared_folder_database_path_unsafe")
        return path

    @staticmethod
    def _configure(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA secure_delete=ON")
        connection.execute("PRAGMA synchronous=FULL")

    @staticmethod
    def _application_shape(connection: sqlite3.Connection) -> bool:
        tables = {
            str(row[0]): _normalized_schema_sql(str(row[1]))
            for row in connection.execute(
                """
                SELECT name, sql FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        }
        if tables != _SHARED_FOLDER_APPLICATION_SQL:
            return False
        return all(
            tuple(
                str(row[1])
                for row in connection.execute(
                    f'PRAGMA table_info("{table}")'
                ).fetchall()
            )
            == columns
            for table, columns in _SHARED_FOLDER_TABLE_COLUMNS.items()
        )

    @classmethod
    def _verify_current_structure(cls, connection: sqlite3.Connection) -> None:
        tables = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        }
        expected = set(_SHARED_FOLDER_TABLE_COLUMNS) | {
            "shared_folder_schema_migrations",
            "shared_folder_migration_checksums",
        }
        if tables != expected:
            raise SharedFolderError("shared_folder_schema_integrity_invalid")
        application_sql = {
            str(row[0]): _normalized_schema_sql(str(row[1]))
            for row in connection.execute(
                """
                SELECT name, sql FROM sqlite_master
                WHERE type='table' AND name IN (
                    'shared_folders', 'link_file_state', 'peer_links'
                )
                """
            ).fetchall()
        }
        if application_sql != _SHARED_FOLDER_APPLICATION_SQL:
            raise SharedFolderError("shared_folder_schema_integrity_invalid")
        for table, columns in _SHARED_FOLDER_TABLE_COLUMNS.items():
            observed = tuple(
                str(row[1])
                for row in connection.execute(
                    f'PRAGMA table_info("{table}")'
                ).fetchall()
            )
            if observed != columns:
                raise SharedFolderError("shared_folder_schema_integrity_invalid")
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise SharedFolderError("shared_folder_schema_integrity_invalid")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise SharedFolderError("shared_folder_schema_integrity_invalid")

    def _initialize(self) -> None:
        path = self._validated_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path_has_symlink_component(path.parent) or path_has_symlink_component(path):
            raise SharedFolderError("shared_folder_database_path_unsafe")
        connection = sqlite3.connect(path, isolation_level=None, timeout=5.0)
        try:
            self._configure(connection)
            connection.execute("BEGIN IMMEDIATE")
            database_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            ledger_exists = _SHARED_FOLDER_MIGRATION_INTEGRITY.table_exists(
                connection,
                "shared_folder_schema_migrations",
            )
            if not ledger_exists:
                if database_version != 0:
                    raise _SHARED_FOLDER_MIGRATION_INTEGRITY.error(
                        "schema_version_mismatch"
                    )
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        """
                        SELECT name FROM sqlite_master
                        WHERE type='table' AND name NOT LIKE 'sqlite_%'
                        """
                    ).fetchall()
                }
                if not tables:
                    _SHARED_FOLDER_MIGRATION_INTEGRITY.create_ledger(connection)
                elif self._application_shape(connection):
                    _SHARED_FOLDER_MIGRATION_INTEGRITY.adopt_legacy(
                        connection,
                        through_version=1,
                        applied_at=datetime.now(UTC)
                        .replace(microsecond=0)
                        .isoformat(),
                    )
                else:
                    raise _SHARED_FOLDER_MIGRATION_INTEGRITY.error(
                        "migration_history_incomplete"
                    )
            current = _SHARED_FOLDER_MIGRATION_INTEGRITY.validate(
                connection,
                database_version=database_version,
                allow_legacy_zero_head=True,
            )
            _SHARED_FOLDER_MIGRATION_INTEGRITY.apply_pending(
                connection,
                current=current,
                applied_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
            )
            self._verify_current_structure(connection)
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        if path_has_symlink_component(path):
            raise SharedFolderError("shared_folder_database_path_unsafe")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._validated_path(), timeout=5.0)
        try:
            connection.row_factory = sqlite3.Row
            self._configure(connection)
            # sqlite3's context manager commits/rolls back but does not close.
            # Every operation owns and releases its connection, including reads.
            with connection:
                yield connection
        finally:
            connection.close()

    # -- shares --

    def add_share(self, share_id: str, name: str, path: str, token_hash: str, created_at: datetime) -> None:
        with self._lock, self._connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM shared_folders WHERE revoked_at IS NULL").fetchone()[0]
            if int(count) >= MAX_SHARES:
                raise SharedFolderError("too_many_shares")
            connection.execute(
                "INSERT INTO shared_folders(share_id, name, path, token_hash, created_at, revoked_at) VALUES (?, ?, ?, ?, ?, NULL)",
                (share_id, name, path, token_hash, created_at.isoformat()),
            )
            connection.commit()

    def list_shares(self) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return list(connection.execute("SELECT * FROM shared_folders ORDER BY created_at DESC").fetchall())

    def get_share(self, share_id: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute("SELECT * FROM shared_folders WHERE share_id = ?", (share_id,)).fetchone()

    def revoke_share(self, share_id: str, revoked_at: datetime) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE shared_folders SET revoked_at = ? WHERE share_id = ? AND revoked_at IS NULL",
                (revoked_at.isoformat(), share_id),
            )
            connection.commit()
            return cursor.rowcount > 0

    # -- peer links --

    def add_link(self, link_id: str, url: str, share_id: str, token: str, target: str, name: str | None, joined_at: datetime) -> None:
        with self._lock, self._connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM peer_links").fetchone()[0]
            if int(count) >= MAX_PEER_LINKS:
                raise SharedFolderError("too_many_links")
            connection.execute(
                "INSERT INTO peer_links(link_id, url, share_id, token, target, name, joined_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (link_id, url, share_id, token, target, name, joined_at.isoformat()),
            )
            connection.commit()

    def list_links(self) -> list[sqlite3.Row]:
        with self._connect() as connection:
            return list(connection.execute("SELECT * FROM peer_links ORDER BY joined_at DESC").fetchall())

    def get_link(self, link_id: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute("SELECT * FROM peer_links WHERE link_id = ?", (link_id,)).fetchone()

    def remove_link(self, link_id: str) -> bool:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM link_file_state WHERE link_id = ?", (link_id,))
            cursor = connection.execute("DELETE FROM peer_links WHERE link_id = ?", (link_id,))
            connection.commit()
            return cursor.rowcount > 0

    def file_state(self, link_id: str) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT path, synced_sha256 FROM link_file_state WHERE link_id = ?", (link_id,)).fetchall()
            return {row["path"]: row["synced_sha256"] for row in rows}

    def record_synced(self, link_id: str, path: str, sha256: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO link_file_state(link_id, path, synced_sha256) VALUES (?, ?, ?)",
                (link_id, path, sha256),
            )
            connection.commit()


class SharedFolderService:
    """The owner side: share, list, revoke, and serve the p2p file surface."""

    def __init__(
        self,
        store: SharedFolderStore,
        *,
        forbidden_roots: tuple[Path, ...] = (),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._forbidden = tuple(root.resolve() for root in forbidden_roots if root.exists())
        self._clock = clock or (lambda: datetime.now(UTC))

    # -- owner surface --

    def share(self, path: str, name: str) -> SharedFolder:
        root = Path(path).expanduser()
        if not root.is_absolute() or not root.is_dir():
            raise SharedFolderError("folder_not_found")
        root = root.resolve()
        if root.anchor == str(root):
            raise SharedFolderError("folder_is_a_drive_root")
        for forbidden in self._forbidden:
            if root == forbidden or forbidden in root.parents or root in forbidden.parents:
                raise SharedFolderError("folder_not_allowed")
        if _PEER_NAME.fullmatch(name or "") is None:
            raise SharedFolderError("name_invalid")
        share_id = secrets.token_hex(16)
        token = secrets.token_urlsafe(32)
        now = self._clock()
        self._store.add_share(share_id, name, str(root), _hash_token(token), now)
        return SharedFolder(share_id=share_id, name=name, path=str(root), created_at=now, share_token=token)

    def list(self) -> SharedFolderList:
        shares = tuple(
            SharedFolder(
                share_id=row["share_id"], name=row["name"], path=row["path"],
                created_at=datetime.fromisoformat(row["created_at"]),
                revoked_at=datetime.fromisoformat(row["revoked_at"]) if row["revoked_at"] else None,
            )
            for row in self._store.list_shares()
        )
        return SharedFolderList(shares=shares)

    def revoke(self, share_id: str) -> None:
        if not self._store.revoke_share(share_id, self._clock()):
            raise SharedFolderError("share_not_found")

    # -- peer surface (token-authenticated) --

    def _authorized_root(self, share_id: str, token: str) -> tuple[Path, str]:
        if _SHARE_ID.fullmatch(share_id or "") is None:
            raise SharedFolderError("share_not_found")
        row = self._store.get_share(share_id)
        if row is None or row["revoked_at"] is not None:
            raise SharedFolderError("share_token_invalid")
        if not secrets.compare_digest(row["token_hash"], _hash_token(token or "")):
            raise SharedFolderError("share_token_invalid")
        root = Path(row["path"])
        if not root.is_dir():
            raise SharedFolderError("folder_not_found")
        return root, str(row["name"])

    def manifest(self, share_id: str, token: str) -> FolderManifest:
        root, name = self._authorized_root(share_id, token)
        files: list[ManifestEntry] = []
        truncated = False
        for candidate in sorted(root.rglob("*")):
            if len(files) >= MAX_MANIFEST_FILES:
                truncated = True
                break
            if not candidate.is_file():
                continue
            relative = candidate.relative_to(root)
            if any(part in SKIP_DIRS for part in relative.parts):
                continue
            stat = candidate.stat()
            if stat.st_size > MAX_FILE_BYTES:
                continue
            files.append(ManifestEntry(
                path=str(PurePosixPath(*relative.parts)), size=stat.st_size, sha256=_file_sha256(candidate),
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            ))
        return FolderManifest(share_id=share_id, name=name, files=tuple(files), truncated=truncated)

    def read_file(self, share_id: str, token: str, relative: str) -> FileContent:
        root, _ = self._authorized_root(share_id, token)
        target = _safe_relative(root, relative)
        if not target.is_file():
            raise SharedFolderError("file_not_found")
        raw = target.read_bytes()
        if len(raw) > MAX_FILE_BYTES:
            raise SharedFolderError("file_too_large")
        return FileContent(
            path=relative, content_b64=base64.b64encode(raw).decode("ascii"),
            sha256=hashlib.sha256(raw).hexdigest(), size=len(raw),
        )

    def write_file(self, share_id: str, token: str, relative: str, request: WriteFileRequest) -> WriteFileResult:
        root, _ = self._authorized_root(share_id, token)
        target = _safe_relative(root, relative)
        try:
            raw = base64.b64decode(request.content_b64.encode("ascii"), validate=True)
        except Exception:
            raise SharedFolderError("content_invalid") from None
        if len(raw) > MAX_FILE_BYTES:
            raise SharedFolderError("file_too_large")
        current = _file_sha256(target) if target.is_file() else None
        conflict = False
        stored_target = target
        if current is not None and request.base_sha256 != current:
            # The edit was based on an older (or no) version: keep both.
            stamp = self._clock().strftime("%Y%m%d-%H%M%S")
            peer = re.sub(r"[^A-Za-z0-9._-]", "-", request.peer_name)[:32] or "peer"
            stored_target = target.with_name(f"{target.stem}.conflict-{peer}-{stamp}{target.suffix}")
            conflict = True
        stored_target.parent.mkdir(parents=True, exist_ok=True)
        stored_target.write_bytes(raw)
        stored_relative = str(PurePosixPath(*stored_target.relative_to(root).parts))
        return WriteFileResult(path=relative, stored_as=stored_relative, conflict=conflict, sha256=hashlib.sha256(raw).hexdigest())


PeerFetch = Callable[[str, str, str | None, bytes | None], tuple[int, bytes]]
"""(method, url, share_token, body) -> (status, payload). Injected so tests run in-process."""


def urllib_peer_fetch(method: str, url: str, token: str | None, body: bytes | None) -> tuple[int, bytes]:
    """Default transport for real peers; the destination is always the URL the person typed when joining."""

    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, data=body, method=method)
    if token:
        request.add_header("X-Share-Token", token)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - peer URL chosen explicitly by the person
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


class PeerFolderClient:
    """The joining side: register a link, pull the folder down, push edits back."""

    def __init__(
        self,
        store: SharedFolderStore,
        *,
        fetch: PeerFetch = urllib_peer_fetch,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._fetch = fetch
        self._clock = clock or (lambda: datetime.now(UTC))

    def join(self, request: JoinRequest) -> PeerLink:
        target = Path(request.target).expanduser()
        if not target.is_absolute():
            raise SharedFolderError("target_invalid")
        target.mkdir(parents=True, exist_ok=True)
        url = request.url.rstrip("/")
        if not url.startswith(("http://", "https://")):
            raise SharedFolderError("url_invalid")
        # Prove the link before storing it.
        manifest = self._manifest(url, request.share_id, request.share_token)
        link_id = secrets.token_hex(16)
        now = self._clock()
        self._store.add_link(link_id, url, request.share_id, request.share_token, str(target.resolve()), manifest.name, now)
        return PeerLink(link_id=link_id, url=url, share_id=request.share_id, target=str(target.resolve()), name=manifest.name, joined_at=now)

    def list(self) -> PeerLinkList:
        links = tuple(
            PeerLink(
                link_id=row["link_id"], url=row["url"], share_id=row["share_id"], target=row["target"],
                name=row["name"], joined_at=datetime.fromisoformat(row["joined_at"]),
            )
            for row in self._store.list_links()
        )
        return PeerLinkList(links=links)

    def leave(self, link_id: str) -> None:
        if not self._store.remove_link(link_id):
            raise SharedFolderError("link_not_found")

    def _manifest(self, url: str, share_id: str, token: str) -> FolderManifest:
        status, payload = self._fetch("GET", f"{url}/p2p/v1/{share_id}/manifest", token, None)
        if status != 200:
            raise SharedFolderError("peer_unreachable" if status >= 500 else "share_token_invalid")
        try:
            return FolderManifest.model_validate_json(payload)
        except Exception:
            raise SharedFolderError("peer_reply_invalid") from None

    def pull(self, link_id: str) -> SyncReport:
        row = self._store.get_link(link_id)
        if row is None:
            raise SharedFolderError("link_not_found")
        url, share_id, token = row["url"], row["share_id"], row["token"]
        target_root = Path(row["target"])
        target_root.mkdir(parents=True, exist_ok=True)
        manifest = self._manifest(url, share_id, token)
        pulled = skipped = 0
        for entry in manifest.files[:MAX_PULL_FILES]:
            local = _safe_relative(target_root, entry.path)
            if local.is_file() and _file_sha256(local) == entry.sha256:
                self._store.record_synced(link_id, entry.path, entry.sha256)
                skipped += 1
                continue
            status, payload = self._fetch("GET", f"{url}/p2p/v1/{share_id}/files/{entry.path}", token, None)
            if status != 200:
                skipped += 1
                continue
            content = FileContent.model_validate_json(payload)
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(base64.b64decode(content.content_b64.encode("ascii")))
            self._store.record_synced(link_id, entry.path, content.sha256)
            pulled += 1
        return SyncReport(link_id=link_id, pulled=pulled, skipped=skipped)

    def push(self, link_id: str, *, peer_name: str = "peer") -> SyncReport:
        row = self._store.get_link(link_id)
        if row is None:
            raise SharedFolderError("link_not_found")
        url, share_id, token = row["url"], row["share_id"], row["token"]
        target_root = Path(row["target"])
        if not target_root.is_dir():
            raise SharedFolderError("target_invalid")
        manifest = self._manifest(url, share_id, token)
        remote = {entry.path: entry.sha256 for entry in manifest.files}
        synced = self._store.file_state(link_id)
        pushed = conflicts = skipped = 0
        count = 0
        for candidate in sorted(target_root.rglob("*")):
            if count >= MAX_PULL_FILES:
                break
            if not candidate.is_file():
                continue
            relative_parts = candidate.relative_to(target_root).parts
            if any(part in SKIP_DIRS for part in relative_parts):
                continue
            relative = str(PurePosixPath(*relative_parts))
            count += 1
            local_hash = _file_sha256(candidate)
            if remote.get(relative) == local_hash:
                self._store.record_synced(link_id, relative, local_hash)
                skipped += 1
                continue
            raw = candidate.read_bytes()
            if len(raw) > MAX_FILE_BYTES:
                skipped += 1
                continue
            body = json.dumps({
                "content_b64": base64.b64encode(raw).decode("ascii"),
                # The base is the version we last synced, not the remote's current
                # one: if both sides moved since then, the owner keeps a conflict
                # copy instead of a silent overwrite.
                "base_sha256": synced.get(relative),
                "peer_name": peer_name,
            }).encode("utf-8")
            status, payload = self._fetch("PUT", f"{url}/p2p/v1/{share_id}/files/{relative}", token, body)
            if status != 200:
                skipped += 1
                continue
            result = WriteFileResult.model_validate_json(payload)
            pushed += 1
            if result.conflict:
                conflicts += 1
            else:
                self._store.record_synced(link_id, relative, result.sha256)
        return SyncReport(link_id=link_id, pushed=pushed, conflicts=conflicts, skipped=skipped)


__all__ = (
    "SHARED_FOLDERS_CONTRACT_VERSION",
    "SHARED_FOLDER_DATABASE_FILENAME",
    "SHARED_FOLDER_SCHEMA_VERSION",
    "FileContent",
    "FolderManifest",
    "JoinRequest",
    "ManifestEntry",
    "PeerFolderClient",
    "PeerLink",
    "PeerLinkList",
    "SharedFolder",
    "SharedFolderError",
    "SharedFolderList",
    "SharedFolderService",
    "SharedFolderStore",
    "SyncReport",
    "WriteFileRequest",
    "WriteFileResult",
    "urllib_peer_fetch",
)
