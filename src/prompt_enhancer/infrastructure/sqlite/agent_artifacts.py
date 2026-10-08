"""SQLite persistence for immutable authored-Agent artifact lineage."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
import sqlite3
import threading

from ...application.agent_artifacts import (
    MAX_AGENT_ARTIFACT_PAGE_SIZE,
    MAX_AGENT_ARTIFACTS_PER_SESSION,
    MAX_AGENT_ARTIFACT_VERSIONS_PER_SESSION,
    AgentArtifact,
    AgentArtifactDetail,
    AgentArtifactError,
    AgentArtifactKind,
    AgentArtifactLifecycleCounts,
    AgentArtifactListView,
    AgentArtifactVersion,
    UpdateAgentArtifact,
)
from ...application.agent_catalog import AgentCatalogError, AgentRetentionPolicy
from .agent_catalog import AgentCatalogSqliteDatabase


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _artifact_page_snapshot(
    *,
    project_id: str,
    session_id: str,
    view: AgentArtifactListView,
    counts: AgentArtifactLifecycleCounts,
    artifacts: tuple[AgentArtifact, ...],
) -> str:
    payload = json.dumps(
        {
            "contract_version": "agent-artifact-page.v1",
            "project_id": project_id,
            "session_id": session_id,
            "view": view,
            "counts": counts.model_dump(mode="json"),
            "artifacts": [
                artifact.model_dump(mode="json") for artifact in artifacts
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


_HEAD_SELECT = """
SELECT artifact.artifact_id AS a_artifact_id,
       session.project_id AS a_project_id,
       artifact.session_id AS a_session_id,
       artifact.title AS a_title,
       artifact.artifact_kind AS a_kind,
       artifact.relative_path AS a_path,
       artifact.created_at AS a_created_at,
       artifact.updated_at AS a_updated_at,
       artifact.revision AS a_revision,
       artifact.latest_version_number AS a_version_count,
       artifact.archived_at AS a_archived_at,
       artifact.removed_at AS a_removed_at,
       version.version_id AS v_version_id,
       version.artifact_id AS v_artifact_id,
       version.version_number AS v_version_number,
       version.created_at AS v_created_at,
       version.relative_path AS v_path,
       version.media_type AS v_media_type,
       version.preview_kind AS v_preview_kind,
       version.provenance AS v_provenance,
       version.sha256 AS v_sha256,
       version.byte_size AS v_byte_size,
       version.source_turn_id AS v_source_turn_id,
       version.source_event_seq AS v_source_event_seq
FROM agent_artifacts artifact
JOIN agent_catalog_sessions session ON session.session_id=artifact.session_id
JOIN agent_artifact_versions version
  ON version.artifact_id=artifact.artifact_id
 AND version.version_number=artifact.latest_version_number
"""


class SqliteAgentArtifactRepository:
    def __init__(
        self,
        database: AgentCatalogSqliteDatabase,
        *,
        fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        self._database = database
        self._write_lock = threading.RLock()
        self._fault_hook = fault_hook
        try:
            self._database.initialize()
        except AgentCatalogError:
            raise AgentArtifactError("agent_artifact_storage_unavailable") from None

    def _fault(self, stage: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(stage)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            with self._database.connect() as connection:
                yield connection
        except AgentCatalogError:
            raise AgentArtifactError("agent_artifact_storage_unavailable") from None

    @staticmethod
    def _version(row: sqlite3.Row, prefix: str = "v_") -> AgentArtifactVersion:
        value = lambda name: row[f"{prefix}{name}"]
        return AgentArtifactVersion(
            version_id=str(value("version_id")),
            artifact_id=str(value("artifact_id")),
            version_number=int(value("version_number")),
            created_at=_time(str(value("created_at"))),
            path=str(value("path")),
            media_type=str(value("media_type")),
            preview_kind=str(value("preview_kind")),
            provenance=str(value("provenance")),
            sha256=str(value("sha256")),
            byte_size=int(value("byte_size")),
            source_turn_id=(
                None if value("source_turn_id") is None else str(value("source_turn_id"))
            ),
            source_event_seq=(
                None if value("source_event_seq") is None else int(value("source_event_seq"))
            ),
        )

    @classmethod
    def _artifact(cls, row: sqlite3.Row) -> AgentArtifact:
        return AgentArtifact(
            artifact_id=str(row["a_artifact_id"]),
            project_id=str(row["a_project_id"]),
            session_id=str(row["a_session_id"]),
            title=str(row["a_title"]),
            kind=str(row["a_kind"]),
            path=str(row["a_path"]),
            created_at=_time(str(row["a_created_at"])),
            updated_at=_time(str(row["a_updated_at"])),
            revision=int(row["a_revision"]),
            version_count=int(row["a_version_count"]),
            lifecycle_state=(
                "removed"
                if row["a_removed_at"] is not None
                else "archived"
                if row["a_archived_at"] is not None
                else "active"
            ),
            archived_at=(
                None
                if row["a_archived_at"] is None
                else _time(str(row["a_archived_at"]))
            ),
            removed_at=(
                None
                if row["a_removed_at"] is None
                else _time(str(row["a_removed_at"]))
            ),
            latest_version=cls._version(row),
        )

    @staticmethod
    def _session(
        connection: sqlite3.Connection,
        project_id: str,
        session_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT project_id,retention_policy FROM agent_catalog_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if row is None or str(row["project_id"]) != project_id:
            raise AgentArtifactError("agent_catalog_session_not_found")
        if str(row["retention_policy"]) != AgentRetentionPolicy.LOCAL_HISTORY.value:
            raise AgentArtifactError("agent_artifact_retention_required")
        return row

    def _head(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
    ) -> AgentArtifact | None:
        row = connection.execute(
            _HEAD_SELECT
            + " WHERE artifact.artifact_id=? AND artifact.session_id=? AND session.project_id=?",
            (artifact_id, session_id, project_id),
        ).fetchone()
        return None if row is None else self._artifact(row)

    def upsert_version(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
        version_id: str,
        title: str,
        kind: AgentArtifactKind,
        version: AgentArtifactVersion,
    ) -> AgentArtifact:
        with self._write_lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._session(connection, project_id, session_id)
                if version.source_event_seq is not None:
                    prior = connection.execute(
                        """
                        SELECT artifact.artifact_id
                        FROM agent_artifact_versions version
                        JOIN agent_artifacts artifact ON artifact.artifact_id=version.artifact_id
                        WHERE artifact.session_id=? AND version.source_event_seq=?
                        """,
                        (session_id, version.source_event_seq),
                    ).fetchone()
                    if prior is not None:
                        connection.execute("COMMIT")
                        existing = self._head(
                            connection,
                            project_id=project_id,
                            session_id=session_id,
                            artifact_id=str(prior["artifact_id"]),
                        )
                        if existing is None:
                            raise AgentArtifactError("agent_artifact_storage_unavailable")
                        return existing

                artifact = connection.execute(
                    """
                    SELECT artifact_id,created_at,updated_at,latest_version_number,
                           title,removed_at
                    FROM agent_artifacts WHERE session_id=? AND relative_path=?
                    """,
                    (session_id, version.path),
                ).fetchone()
                if artifact is None:
                    count = int(connection.execute(
                        "SELECT COUNT(*) FROM agent_artifacts WHERE session_id=?",
                        (session_id,),
                    ).fetchone()[0])
                    if count >= MAX_AGENT_ARTIFACTS_PER_SESSION:
                        raise AgentArtifactError("agent_artifact_limit_reached")
                    actual_artifact_id = artifact_id
                    version_number = 1
                    connection.execute(
                        """
                        INSERT INTO agent_artifacts(
                            artifact_id,session_id,title,artifact_kind,relative_path,
                            created_at,updated_at,revision,latest_version_number
                        ) VALUES(?,?,?,?,?,?,?,1,1)
                        """,
                        (
                            actual_artifact_id,
                            session_id,
                            title,
                            kind,
                            version.path,
                            _iso(version.created_at),
                            _iso(version.created_at),
                        ),
                    )
                    self._fault("after_head_insert")
                else:
                    actual_artifact_id = str(artifact["artifact_id"])
                    if artifact["removed_at"] is not None:
                        raise AgentArtifactError("agent_artifact_removed")
                    latest_number = int(artifact["latest_version_number"])
                    latest = connection.execute(
                        """
                        SELECT sha256,byte_size,source_event_seq
                        FROM agent_artifact_versions
                        WHERE artifact_id=? AND version_number=?
                        """,
                        (actual_artifact_id, latest_number),
                    ).fetchone()
                    if (
                        version.source_event_seq is None
                        and latest is not None
                        and str(latest["sha256"]) == version.sha256
                        and int(latest["byte_size"]) == version.byte_size
                    ):
                        connection.execute("COMMIT")
                        existing = self._head(
                            connection,
                            project_id=project_id,
                            session_id=session_id,
                            artifact_id=actual_artifact_id,
                        )
                        if existing is None:
                            raise AgentArtifactError("agent_artifact_storage_unavailable")
                        return existing
                    version_number = latest_number + 1

                versions = int(connection.execute(
                    """
                    SELECT COUNT(*) FROM agent_artifact_versions version
                    JOIN agent_artifacts artifact ON artifact.artifact_id=version.artifact_id
                    WHERE artifact.session_id=?
                    """,
                    (session_id,),
                ).fetchone()[0])
                if versions >= MAX_AGENT_ARTIFACT_VERSIONS_PER_SESSION:
                    raise AgentArtifactError("agent_artifact_version_limit_reached")

                stored = version.model_copy(update={
                    "artifact_id": actual_artifact_id,
                    "version_id": version_id,
                    "version_number": version_number,
                })
                connection.execute(
                    """
                    INSERT INTO agent_artifact_versions(
                        version_id,artifact_id,version_number,created_at,relative_path,
                        media_type,preview_kind,provenance,sha256,byte_size,
                        source_turn_id,source_event_seq
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        stored.version_id,
                        stored.artifact_id,
                        stored.version_number,
                        _iso(stored.created_at),
                        stored.path,
                        stored.media_type,
                        stored.preview_kind,
                        stored.provenance,
                        stored.sha256,
                        stored.byte_size,
                        stored.source_turn_id,
                        stored.source_event_seq,
                    ),
                )
                self._fault("after_version_insert")
                if artifact is not None:
                    connection.execute(
                        """
                        UPDATE agent_artifacts
                        SET title=?,artifact_kind=?,updated_at=?,revision=revision+1,
                            latest_version_number=?
                        WHERE artifact_id=?
                        """,
                        (
                            str(artifact["title"]),
                            kind,
                            _iso(max(_time(str(artifact["updated_at"])), stored.created_at)),
                            version_number,
                            actual_artifact_id,
                        ),
                    )
                    self._fault("after_head_update")
                self._fault("before_commit")
                connection.execute("COMMIT")
                self._fault("after_commit")
            except AgentArtifactError:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            except sqlite3.IntegrityError:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise AgentArtifactError("agent_artifact_conflict") from None
            except sqlite3.Error:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise AgentArtifactError("agent_artifact_storage_unavailable") from None
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

            head = self._head(
                connection,
                project_id=project_id,
                session_id=session_id,
                artifact_id=actual_artifact_id,
            )
            if head is None:
                raise AgentArtifactError("agent_artifact_storage_unavailable")
            return head

    def list_artifacts(
        self,
        *,
        project_id: str,
        session_id: str,
        view: AgentArtifactListView,
        limit: int,
    ) -> tuple[tuple[AgentArtifact, ...], AgentArtifactLifecycleCounts]:
        predicates = {
            "active": "artifact.archived_at IS NULL AND artifact.removed_at IS NULL",
            "archived": "artifact.archived_at IS NOT NULL AND artifact.removed_at IS NULL",
            "removed": "artifact.removed_at IS NOT NULL",
            "all": "1=1",
        }
        with self._connection() as connection:
            self._session(connection, project_id, session_id)
            count_row = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN archived_at IS NULL AND removed_at IS NULL THEN 1 ELSE 0 END),
                    SUM(CASE WHEN archived_at IS NOT NULL AND removed_at IS NULL THEN 1 ELSE 0 END),
                    SUM(CASE WHEN removed_at IS NOT NULL THEN 1 ELSE 0 END),
                    COUNT(*)
                FROM agent_artifacts WHERE session_id=?
                """,
                (session_id,),
            ).fetchone()
            rows = connection.execute(
                _HEAD_SELECT
                + f"""
                  WHERE artifact.session_id=? AND session.project_id=?
                    AND {predicates[view]}
                  ORDER BY artifact.updated_at DESC, artifact.artifact_id ASC
                  LIMIT ?
                """,
                (session_id, project_id, limit),
            ).fetchall()
        counts = AgentArtifactLifecycleCounts(
            active=int(count_row[0] or 0),
            archived=int(count_row[1] or 0),
            removed=int(count_row[2] or 0),
            total=int(count_row[3] or 0),
        )
        return tuple(self._artifact(row) for row in rows), counts

    def page_artifacts(
        self,
        *,
        project_id: str,
        session_id: str,
        view: AgentArtifactListView,
        limit: int,
        offset: int,
        snapshot: str | None,
    ) -> tuple[
        tuple[AgentArtifact, ...],
        AgentArtifactLifecycleCounts,
        int,
        str,
    ]:
        if limit < 1 or limit > MAX_AGENT_ARTIFACT_PAGE_SIZE:
            raise AgentArtifactError("agent_artifact_page_invalid")
        if offset < 0 or offset > MAX_AGENT_ARTIFACTS_PER_SESSION:
            raise AgentArtifactError("agent_artifact_page_out_of_range")
        if offset > 0 and snapshot is None:
            raise AgentArtifactError("agent_artifact_page_snapshot_required")
        predicates = {
            "active": "artifact.archived_at IS NULL AND artifact.removed_at IS NULL",
            "archived": "artifact.archived_at IS NOT NULL AND artifact.removed_at IS NULL",
            "removed": "artifact.removed_at IS NOT NULL",
            "all": "1=1",
        }
        with self._connection() as connection:
            connection.execute("BEGIN")
            try:
                self._session(connection, project_id, session_id)
                count_row = connection.execute(
                    """
                    SELECT
                        SUM(CASE WHEN archived_at IS NULL AND removed_at IS NULL THEN 1 ELSE 0 END),
                        SUM(CASE WHEN archived_at IS NOT NULL AND removed_at IS NULL THEN 1 ELSE 0 END),
                        SUM(CASE WHEN removed_at IS NOT NULL THEN 1 ELSE 0 END),
                        COUNT(*)
                    FROM agent_artifacts WHERE session_id=?
                    """,
                    (session_id,),
                ).fetchone()
                counts = AgentArtifactLifecycleCounts(
                    active=int(count_row[0] or 0),
                    archived=int(count_row[1] or 0),
                    removed=int(count_row[2] or 0),
                    total=int(count_row[3] or 0),
                )
                rows = connection.execute(
                    _HEAD_SELECT
                    + f"""
                      WHERE artifact.session_id=? AND session.project_id=?
                        AND {predicates[view]}
                      ORDER BY artifact.updated_at DESC, artifact.artifact_id ASC
                    """,
                    (session_id, project_id),
                ).fetchall()
                all_artifacts = tuple(self._artifact(row) for row in rows)
                total = counts.total if view == "all" else getattr(counts, view)
                if total != len(all_artifacts):
                    raise AgentArtifactError("agent_artifact_storage_unavailable")
                current_snapshot = _artifact_page_snapshot(
                    project_id=project_id,
                    session_id=session_id,
                    view=view,
                    counts=counts,
                    artifacts=all_artifacts,
                )
                if snapshot is not None and snapshot != current_snapshot:
                    raise AgentArtifactError("agent_artifact_page_snapshot_conflict")
                if offset > total:
                    raise AgentArtifactError("agent_artifact_page_out_of_range")
                page = all_artifacts[offset : offset + limit]
                connection.execute("COMMIT")
                return page, counts, total, current_snapshot
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def get_artifact_by_path(
        self,
        *,
        project_id: str,
        session_id: str,
        path: str,
    ) -> AgentArtifact | None:
        with self._connection() as connection:
            self._session(connection, project_id, session_id)
            row = connection.execute(
                _HEAD_SELECT
                + " WHERE artifact.session_id=? AND session.project_id=? "
                "AND artifact.relative_path=?",
                (session_id, project_id, path),
            ).fetchone()
        return None if row is None else self._artifact(row)

    def relocate_version(
        self,
        *,
        project_id: str,
        session_id: str,
        source_path: str,
        target_path: str,
        expected_artifact_id: str,
        expected_artifact_revision: int,
        title: str,
        kind: AgentArtifactKind,
        version: AgentArtifactVersion,
    ) -> AgentArtifact:
        """Atomically append a move version and advance the artifact head."""

        with self._write_lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._session(connection, project_id, session_id)
                row = connection.execute(
                    _HEAD_SELECT
                    + " WHERE artifact.session_id=? AND session.project_id=? "
                    "AND artifact.relative_path=?",
                    (session_id, project_id, source_path),
                ).fetchone()
                if row is None:
                    raise AgentArtifactError("agent_artifact_relocation_conflict")
                source = self._artifact(row)
                if (
                    source.lifecycle_state == "removed"
                    or source.artifact_id != expected_artifact_id
                    or source.revision != expected_artifact_revision
                    or version.artifact_id != source.artifact_id
                    or version.version_number != source.version_count + 1
                    or version.path != target_path
                    or version.provenance != "reviewed_move"
                    or version.sha256 != source.latest_version.sha256
                    or version.byte_size != source.latest_version.byte_size
                ):
                    raise AgentArtifactError("agent_artifact_relocation_conflict")
                target = connection.execute(
                    "SELECT artifact_id FROM agent_artifacts "
                    "WHERE session_id=? AND relative_path=?",
                    (session_id, target_path),
                ).fetchone()
                if target is not None:
                    raise AgentArtifactError("agent_artifact_relocation_target_conflict")
                versions = int(connection.execute(
                    """
                    SELECT COUNT(*) FROM agent_artifact_versions version
                    JOIN agent_artifacts artifact ON artifact.artifact_id=version.artifact_id
                    WHERE artifact.session_id=?
                    """,
                    (session_id,),
                ).fetchone()[0])
                if versions >= MAX_AGENT_ARTIFACT_VERSIONS_PER_SESSION:
                    raise AgentArtifactError("agent_artifact_version_limit_reached")
                connection.execute(
                    """
                    INSERT INTO agent_artifact_versions(
                        version_id,artifact_id,version_number,created_at,relative_path,
                        media_type,preview_kind,provenance,sha256,byte_size,
                        source_turn_id,source_event_seq
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        version.version_id,
                        version.artifact_id,
                        version.version_number,
                        _iso(max(source.updated_at, version.created_at)),
                        version.path,
                        version.media_type,
                        version.preview_kind,
                        version.provenance,
                        version.sha256,
                        version.byte_size,
                        version.source_turn_id,
                        version.source_event_seq,
                    ),
                )
                updated = connection.execute(
                    """
                    UPDATE agent_artifacts
                    SET title=?,artifact_kind=?,relative_path=?,updated_at=?,
                        revision=revision+1,latest_version_number=?
                    WHERE artifact_id=? AND session_id=? AND revision=?
                      AND relative_path=?
                    """,
                    (
                        title,
                        kind,
                        target_path,
                        _iso(version.created_at),
                        version.version_number,
                        expected_artifact_id,
                        session_id,
                        expected_artifact_revision,
                        source_path,
                    ),
                )
                if updated.rowcount != 1:
                    raise AgentArtifactError("agent_artifact_relocation_conflict")
                connection.execute("COMMIT")
            except AgentArtifactError:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            except sqlite3.IntegrityError:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise AgentArtifactError("agent_artifact_relocation_conflict") from None
            except sqlite3.Error:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise AgentArtifactError("agent_artifact_storage_unavailable") from None

            head = self._head(
                connection,
                project_id=project_id,
                session_id=session_id,
                artifact_id=expected_artifact_id,
            )
            if head is None:
                raise AgentArtifactError("agent_artifact_storage_unavailable")
            return head

    def get_artifact(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
    ) -> AgentArtifactDetail | None:
        with self._connection() as connection:
            self._session(connection, project_id, session_id)
            head = self._head(
                connection,
                project_id=project_id,
                session_id=session_id,
                artifact_id=artifact_id,
            )
            if head is None:
                return None
            rows = connection.execute(
                """
                SELECT version_id,artifact_id,version_number,created_at,
                       relative_path AS path,media_type,preview_kind,provenance,
                       sha256,byte_size,source_turn_id,source_event_seq
                FROM agent_artifact_versions
                WHERE artifact_id=? ORDER BY version_number ASC
                """,
                (artifact_id,),
            ).fetchall()
        versions = tuple(self._version(row, prefix="") for row in rows)
        return AgentArtifactDetail(**head.model_dump(), versions=versions)

    def get_version(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
        version_id: str,
    ) -> AgentArtifactVersion | None:
        with self._connection() as connection:
            self._session(connection, project_id, session_id)
            row = connection.execute(
                """
                SELECT version.version_id,version.artifact_id,version.version_number,
                       version.created_at,version.relative_path AS path,
                       version.media_type,version.preview_kind,version.provenance,
                       version.sha256,version.byte_size,version.source_turn_id,
                       version.source_event_seq
                FROM agent_artifact_versions version
                JOIN agent_artifacts artifact ON artifact.artifact_id=version.artifact_id
                JOIN agent_catalog_sessions session ON session.session_id=artifact.session_id
                WHERE version.version_id=? AND artifact.artifact_id=?
                  AND artifact.session_id=? AND session.project_id=?
                """,
                (version_id, artifact_id, session_id, project_id),
            ).fetchone()
        return None if row is None else self._version(row, prefix="")

    def update_artifact(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
        command: UpdateAgentArtifact,
        changed_at: datetime,
    ) -> AgentArtifact:
        with self._write_lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._session(connection, project_id, session_id)
                current = self._head(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    artifact_id=artifact_id,
                )
                if current is None:
                    raise AgentArtifactError("agent_artifact_not_found")
                if current.revision != command.expected_revision:
                    raise AgentArtifactError("agent_artifact_revision_conflict")
                effective_changed_at = max(changed_at, current.updated_at)

                title = current.title
                archived_at = current.archived_at
                removed_at = current.removed_at
                if command.operation == "rename":
                    if current.lifecycle_state == "removed":
                        raise AgentArtifactError("agent_artifact_removed")
                    assert command.title is not None
                    if command.title == current.title:
                        raise AgentArtifactError("agent_artifact_no_change")
                    title = command.title
                elif command.operation == "archive":
                    if current.lifecycle_state != "active":
                        raise AgentArtifactError("agent_artifact_state_conflict")
                    archived_at = effective_changed_at
                elif command.operation == "restore":
                    if current.lifecycle_state != "archived":
                        raise AgentArtifactError("agent_artifact_state_conflict")
                    archived_at = None
                else:
                    if current.lifecycle_state != "removed":
                        raise AgentArtifactError("agent_artifact_state_conflict")
                    removed_at = None

                updated = connection.execute(
                    """
                    UPDATE agent_artifacts
                    SET title=?,archived_at=?,removed_at=?,updated_at=?,revision=revision+1
                    WHERE artifact_id=? AND session_id=? AND revision=?
                    """,
                    (
                        title,
                        None if archived_at is None else _iso(archived_at),
                        None if removed_at is None else _iso(removed_at),
                        _iso(effective_changed_at),
                        artifact_id,
                        session_id,
                        command.expected_revision,
                    ),
                )
                if updated.rowcount != 1:
                    raise AgentArtifactError("agent_artifact_revision_conflict")
                connection.execute("COMMIT")
            except AgentArtifactError:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            except sqlite3.IntegrityError:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise AgentArtifactError("agent_artifact_conflict") from None
            except sqlite3.Error:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise AgentArtifactError("agent_artifact_storage_unavailable") from None

            result = self._head(
                connection,
                project_id=project_id,
                session_id=session_id,
                artifact_id=artifact_id,
            )
            if result is None:
                raise AgentArtifactError("agent_artifact_storage_unavailable")
            return result

    def remove_artifact(
        self,
        *,
        project_id: str,
        session_id: str,
        artifact_id: str,
        expected_revision: int,
        removed_at: datetime,
    ) -> AgentArtifact:
        with self._write_lock, self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._session(connection, project_id, session_id)
                current = self._head(
                    connection,
                    project_id=project_id,
                    session_id=session_id,
                    artifact_id=artifact_id,
                )
                if current is None:
                    raise AgentArtifactError("agent_artifact_not_found")
                if current.revision != expected_revision:
                    raise AgentArtifactError("agent_artifact_revision_conflict")
                if current.lifecycle_state == "removed":
                    raise AgentArtifactError("agent_artifact_state_conflict")
                if current.lifecycle_state != "archived":
                    raise AgentArtifactError("agent_artifact_archive_required")
                effective_removed_at = max(removed_at, current.updated_at)
                updated = connection.execute(
                    """
                    UPDATE agent_artifacts
                    SET removed_at=?,updated_at=?,revision=revision+1
                    WHERE artifact_id=? AND session_id=? AND revision=?
                      AND archived_at IS NOT NULL AND removed_at IS NULL
                    """,
                    (
                        _iso(effective_removed_at),
                        _iso(effective_removed_at),
                        artifact_id,
                        session_id,
                        expected_revision,
                    ),
                )
                if updated.rowcount != 1:
                    raise AgentArtifactError("agent_artifact_revision_conflict")
                connection.execute("COMMIT")
            except AgentArtifactError:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            except sqlite3.IntegrityError:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise AgentArtifactError("agent_artifact_conflict") from None
            except sqlite3.Error:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise AgentArtifactError("agent_artifact_storage_unavailable") from None

            result = self._head(
                connection,
                project_id=project_id,
                session_id=session_id,
                artifact_id=artifact_id,
            )
            if result is None:
                raise AgentArtifactError("agent_artifact_storage_unavailable")
            return result


__all__ = ("SqliteAgentArtifactRepository",)
