"""SQLite-backed private payload vault for local Agent attachments."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import sqlite3
import threading

from ...application.agent_attachment_contracts import (
    AgentAttachment,
    MAX_AGENT_ATTACHMENT_SESSION_BYTES,
    MAX_AGENT_STAGED_ATTACHMENTS,
)
from ...application.agent_attachments import (
    AgentAttachmentBlob,
    AgentAttachmentError,
)
from ...application.agent_catalog import AgentCatalogError
from .agent_catalog import AgentCatalogSqliteDatabase


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _attachment(row: sqlite3.Row) -> AgentAttachment:
    try:
        return AgentAttachment(
            attachment_id=str(row["attachment_id"]),
            session_id=str(row["session_id"]),
            model_alias=str(row["model_alias"]),
            capability_probe_version=str(row["capability_probe_version"]),
            kind=str(row["attachment_kind"]),
            media_type=str(row["media_type"]),
            display_name=str(row["display_name"]),
            source=str(row["source_kind"]),
            state=str(row["attachment_state"]),
            retention=str(row["retention_policy"]),
            created_at=_time(str(row["created_at"])),
            expires_at=(
                _time(str(row["expires_at"]))
                if row["expires_at"] is not None
                else None
            ),
            attached_event_seq=(
                int(row["attached_event_seq"])
                if row["attached_event_seq"] is not None
                else None
            ),
            sha256=str(row["sha256"]),
            byte_size=int(row["byte_size"]),
            width=int(row["width"]) if row["width"] is not None else None,
            height=int(row["height"]) if row["height"] is not None else None,
            duration_ms=(
                int(row["duration_ms"]) if row["duration_ms"] is not None else None
            ),
            sample_rate_hz=(
                int(row["sample_rate_hz"])
                if row["sample_rate_hz"] is not None
                else None
            ),
            channels=int(row["channels"]) if row["channels"] is not None else None,
            routing=str(row["routing"]),
            document_format=(
                str(row["document_format"])
                if row["document_format"] is not None
                else None
            ),
            projected_characters=(
                int(row["projected_characters"])
                if row["projected_characters"] is not None
                else None
            ),
            projection_truncated=(
                bool(row["projection_truncated"])
                if row["projection_truncated"] is not None
                else None
            ),
            omitted_features=tuple(json.loads(str(row["omitted_features_json"]))),
        )
    except (TypeError, ValueError):
        raise AgentAttachmentError("agent_attachment_corrupt") from None


_SELECT = """
SELECT attachment_id,session_id,model_alias,capability_probe_version,
       attachment_kind,media_type,display_name,source_kind,attachment_state,
       retention_policy,created_at,expires_at,attached_event_seq,sha256,
       byte_size,width,height,duration_ms,sample_rate_hz,channels,routing,
       document_format,projected_characters,projection_truncated,
       omitted_features_json,payload
FROM agent_attachments
"""


class SqliteAgentAttachmentRepository:
    def __init__(self, database: AgentCatalogSqliteDatabase) -> None:
        self._database = database
        self._write_lock = threading.Lock()

    @staticmethod
    def _translate(error: AgentCatalogError) -> AgentAttachmentError:
        return AgentAttachmentError(error.code)

    def purge_expired(self, now: datetime) -> None:
        try:
            with self._write_lock, self._database.connect() as connection:
                connection.execute(
                    "DELETE FROM agent_attachments WHERE attachment_state='staged' AND expires_at<=?",
                    (_iso(now),),
                )
        except AgentCatalogError as error:
            raise self._translate(error) from None

    def create(self, blob: AgentAttachmentBlob) -> AgentAttachment:
        attachment = blob.attachment
        try:
            with self._write_lock, self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                session = connection.execute(
                    "SELECT retention_policy FROM agent_catalog_sessions WHERE session_id=?",
                    (attachment.session_id,),
                ).fetchone()
                if session is None:
                    connection.execute("ROLLBACK")
                    raise AgentAttachmentError("agent_catalog_session_not_found")
                expected_retention = (
                    "local_history"
                    if str(session["retention_policy"]) == "local_history"
                    else "memory_only"
                )
                if attachment.retention != expected_retention:
                    connection.execute("ROLLBACK")
                    raise AgentAttachmentError("agent_attachment_retention_changed")
                staged = int(connection.execute(
                    "SELECT COUNT(*) FROM agent_attachments WHERE session_id=? AND attachment_state='staged'",
                    (attachment.session_id,),
                ).fetchone()[0])
                if staged >= MAX_AGENT_STAGED_ATTACHMENTS:
                    connection.execute("ROLLBACK")
                    raise AgentAttachmentError("agent_attachment_stage_limit")
                stored_bytes = int(connection.execute(
                    "SELECT COALESCE(SUM(byte_size),0) FROM agent_attachments WHERE session_id=?",
                    (attachment.session_id,),
                ).fetchone()[0])
                if stored_bytes + attachment.byte_size > MAX_AGENT_ATTACHMENT_SESSION_BYTES:
                    connection.execute("ROLLBACK")
                    raise AgentAttachmentError("agent_attachment_session_too_large")
                connection.execute(
                    """
                    INSERT INTO agent_attachments(
                        attachment_id,session_id,model_alias,capability_probe_version,
                        attachment_kind,media_type,display_name,source_kind,
                        attachment_state,retention_policy,created_at,expires_at,
                        attached_event_seq,sha256,byte_size,width,height,duration_ms,
                        sample_rate_hz,channels,routing,document_format,
                        projected_characters,projection_truncated,
                        omitted_features_json,payload
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        attachment.attachment_id,
                        attachment.session_id,
                        attachment.model_alias,
                        attachment.capability_probe_version,
                        attachment.kind,
                        attachment.media_type,
                        attachment.display_name,
                        attachment.source,
                        attachment.state,
                        attachment.retention,
                        _iso(attachment.created_at),
                        _iso(attachment.expires_at) if attachment.expires_at else None,
                        attachment.attached_event_seq,
                        attachment.sha256,
                        attachment.byte_size,
                        attachment.width,
                        attachment.height,
                        attachment.duration_ms,
                        attachment.sample_rate_hz,
                        attachment.channels,
                        attachment.routing,
                        attachment.document_format,
                        attachment.projected_characters,
                        (
                            int(attachment.projection_truncated)
                            if attachment.projection_truncated is not None
                            else None
                        ),
                        json.dumps(
                            list(attachment.omitted_features),
                            ensure_ascii=True,
                            separators=(",", ":"),
                        ),
                        sqlite3.Binary(blob.payload),
                    ),
                )
                connection.execute("COMMIT")
                return attachment
        except AgentAttachmentError:
            raise
        except AgentCatalogError as error:
            raise self._translate(error) from None
        except sqlite3.IntegrityError:
            raise AgentAttachmentError("agent_attachment_conflict") from None

    def list_staged(self, session_id: str) -> tuple[AgentAttachment, ...]:
        try:
            with self._database.connect() as connection:
                rows = connection.execute(
                    _SELECT
                    + " WHERE session_id=? AND attachment_state='staged'"
                    + " ORDER BY created_at,attachment_id",
                    (session_id,),
                ).fetchall()
                return tuple(_attachment(row) for row in rows)
        except AgentCatalogError as error:
            raise self._translate(error) from None

    def get(self, session_id: str, attachment_id: str) -> AgentAttachmentBlob | None:
        try:
            with self._database.connect() as connection:
                row = connection.execute(
                    _SELECT + " WHERE session_id=? AND attachment_id=?",
                    (session_id, attachment_id),
                ).fetchone()
                if row is None:
                    return None
                payload = row["payload"]
                if not isinstance(payload, bytes):
                    raise AgentAttachmentError("agent_attachment_corrupt")
                return AgentAttachmentBlob(_attachment(row), payload)
        except AgentAttachmentError:
            raise
        except AgentCatalogError as error:
            raise self._translate(error) from None

    def mark_attached(
        self,
        session_id: str,
        attachment_ids: tuple[str, ...],
        event_seq: int,
    ) -> None:
        if not attachment_ids:
            return
        try:
            with self._write_lock, self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                session = connection.execute(
                    "SELECT retention_policy FROM agent_catalog_sessions WHERE session_id=?",
                    (session_id,),
                ).fetchone()
                if session is None:
                    connection.execute("ROLLBACK")
                    raise AgentAttachmentError("agent_catalog_session_not_found")
                if str(session["retention_policy"]) != "local_history":
                    connection.execute("ROLLBACK")
                    raise AgentAttachmentError("agent_attachment_retention_changed")
                for attachment_id in attachment_ids:
                    cursor = connection.execute(
                        """
                        UPDATE agent_attachments
                        SET attachment_state='attached',expires_at=NULL,attached_event_seq=?
                        WHERE session_id=? AND attachment_id=? AND attachment_state='staged'
                        """,
                        (event_seq, session_id, attachment_id),
                    )
                    if cursor.rowcount != 1:
                        connection.execute("ROLLBACK")
                        raise AgentAttachmentError("agent_attachment_state_changed")
                connection.execute("COMMIT")
        except AgentAttachmentError:
            raise
        except AgentCatalogError as error:
            raise self._translate(error) from None
        except sqlite3.IntegrityError:
            raise AgentAttachmentError("agent_attachment_storage_unavailable") from None

    def delete(self, session_id: str, attachment_id: str, *, staged_only: bool) -> bool:
        where = "session_id=? AND attachment_id=?"
        if staged_only:
            where += " AND attachment_state='staged'"
        try:
            with self._write_lock, self._database.connect() as connection:
                cursor = connection.execute(
                    f"DELETE FROM agent_attachments WHERE {where}",
                    (session_id, attachment_id),
                )
                return cursor.rowcount == 1
        except AgentCatalogError as error:
            raise self._translate(error) from None


__all__ = ["SqliteAgentAttachmentRepository"]
