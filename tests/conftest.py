"""Repository-wide guard against accidental non-loopback test egress."""

from __future__ import annotations

import ipaddress
import sqlite3
import socket
from collections.abc import Callable

import pytest


def _loopback_address(address: object) -> bool:
    if not isinstance(address, tuple) or not address:
        # Local-domain and platform-specific non-IP transports are not remote
        # network egress and remain governed by their own adapters.
        return True
    host = address[0]
    if isinstance(host, bytes):
        try:
            host = host.decode("ascii", errors="strict")
        except UnicodeDecodeError:
            return False
    if not isinstance(host, str):
        return False
    if host.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        # Reject names before they can trigger external DNS resolution.
        return False


@pytest.fixture(autouse=True)
def deny_non_loopback_tcp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail, rather than skip, any IPv4/IPv6 non-loopback test connection."""

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo
    original_sendto = socket.socket.sendto

    def guarded_connect(instance: socket.socket, address: object) -> None:
        if instance.family in {socket.AF_INET, socket.AF_INET6} and not _loopback_address(address):
            raise AssertionError("non_loopback_socket_forbidden")
        original_connect(instance, address)

    def guarded_connect_ex(instance: socket.socket, address: object) -> int:
        if instance.family in {socket.AF_INET, socket.AF_INET6} and not _loopback_address(address):
            raise AssertionError("non_loopback_socket_forbidden")
        return original_connect_ex(instance, address)

    def guarded_getaddrinfo(host: object, *args: object, **kwargs: object):
        if host is not None and not _loopback_address((host, 0)):
            raise AssertionError("non_loopback_socket_forbidden")
        return original_getaddrinfo(host, *args, **kwargs)

    def guarded_sendto(instance: socket.socket, data: bytes, *args: object) -> int:
        address = args[-1] if args else None
        if instance.family in {socket.AF_INET, socket.AF_INET6} and not _loopback_address(address):
            raise AssertionError("non_loopback_socket_forbidden")
        return original_sendto(instance, data, *args)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
    monkeypatch.setattr(socket.socket, "sendto", guarded_sendto)


@pytest.fixture(autouse=True)
def _isolated_provider_homes(tmp_path_factory, monkeypatch):
    """Never let a test touch the real Claude Code home.

    The owner-authorized transcript reader and adapter (ADR 0011) default to
    ``~/.claude``; under test that directory must be an empty temporary one so
    no real session is ever scanned, even into a temporary store.  Tests that
    need transcripts create them under this path.
    """

    home = tmp_path_factory.mktemp("claude-home-isolated")
    monkeypatch.setenv("PROMPT_ENHANCER_CLAUDE_HOME", str(home))
    yield


@pytest.fixture
def downgrade_agent_catalog_post_v20() -> Callable[[sqlite3.Connection], None]:
    """Reverse post-v20 additive schemas for exact historical fixtures.

    Migration tests start with the current database so they can preserve real
    rows, then reconstruct one older supported schema. Newer migrations must be
    removed from both the ledger *and* the schema or the fixture would claim a
    version it never represented. This helper deliberately contains test-only
    reverse DDL; production migrations remain forward-only and fail closed on
    inconsistent schemas.
    """

    def columns(connection: sqlite3.Connection, table: str) -> set[str]:
        return {
            str(row[1])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }

    def downgrade(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA foreign_keys = OFF")

        # Schema 30. Historical fixtures have no checksum provenance sidecar.
        connection.execute(
            "DROP TABLE IF EXISTS agent_catalog_migration_checksums"
        )

        # Schema 29. Historical fixtures have neither the cross-project claim
        # guards nor immutable call evidence triggers.
        connection.execute(
            "DROP TRIGGER IF EXISTS mcp_managed_tool_call_receipts_immutable"
        )
        connection.execute(
            "DROP TRIGGER IF EXISTS mcp_managed_tool_call_receipts_claim_insert"
        )
        connection.execute(
            "DROP TRIGGER IF EXISTS mcp_managed_tool_call_claims_immutable"
        )
        connection.execute(
            "DROP TRIGGER IF EXISTS mcp_managed_tool_call_claims_scope_insert"
        )

        # Schema 28. A real pre-28 database has no durable one-use call claims;
        # remove the dependent table before older fixtures reconstruct their
        # managed-tool snapshot and receipt schemas.
        connection.execute("DROP TABLE IF EXISTS mcp_managed_tool_call_claims")

        # Schema 27.
        connection.execute(
            "DROP TABLE IF EXISTS mcp_managed_local_configuration_inspections"
        )

        # Schema 26. These content-free runtime tables depend on managed server
        # and project rows that older migration fixtures remove below.
        connection.execute("DROP TABLE IF EXISTS mcp_managed_host_cleanup_blocks")
        connection.execute("DROP TABLE IF EXISTS mcp_managed_host_action_receipts")

        # Schema 24.
        connection.execute("DROP TABLE IF EXISTS agent_controller_ownerships")

        # Schema 23.
        if "scope_project_id" in columns(connection, "agent_mcp_connections"):
            connection.execute("DROP INDEX IF EXISTS agent_mcp_connections_scope_idx")
            connection.execute(
                "ALTER TABLE agent_mcp_connections DROP COLUMN scope_project_id"
            )

        # Schema 22 rebuilt the attachment table to add bounded document
        # projections. Historical <=21 fixtures can contain only image/audio.
        if "routing" in columns(connection, "agent_attachments"):
            document_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM agent_attachments "
                    "WHERE attachment_kind='document'"
                ).fetchone()[0]
            )
            assert document_count == 0, "historical attachment fixture contains future rows"
            connection.execute("DROP TRIGGER IF EXISTS agent_attachment_payload_immutable")
            connection.execute("DROP INDEX IF EXISTS agent_attachments_session_state_idx")
            connection.execute("DROP INDEX IF EXISTS agent_attachments_expiry_idx")
            connection.execute(
                "ALTER TABLE agent_attachments RENAME TO agent_attachments_v22_current"
            )
            connection.execute(
                """
                CREATE TABLE agent_attachments (
                    attachment_id TEXT PRIMARY KEY
                        CHECK(length(attachment_id)=32 AND attachment_id NOT GLOB '*[^0-9a-f]*'),
                    session_id TEXT NOT NULL
                        REFERENCES agent_catalog_sessions(session_id) ON DELETE CASCADE,
                    model_alias TEXT NOT NULL CHECK(length(model_alias) BETWEEN 1 AND 64),
                    capability_probe_version TEXT NOT NULL
                        CHECK(length(capability_probe_version) BETWEEN 1 AND 64),
                    attachment_kind TEXT NOT NULL CHECK(attachment_kind IN ('image','audio')),
                    media_type TEXT NOT NULL
                        CHECK(media_type IN ('image/png','image/jpeg','audio/wav')),
                    display_name TEXT NOT NULL CHECK(length(display_name) BETWEEN 1 AND 120),
                    source_kind TEXT NOT NULL
                        CHECK(source_kind IN ('file','microphone','external_agent')),
                    attachment_state TEXT NOT NULL CHECK(attachment_state IN ('staged','attached')),
                    retention_policy TEXT NOT NULL
                        CHECK(retention_policy IN ('memory_only','local_history')),
                    created_at TEXT NOT NULL,
                    expires_at TEXT,
                    attached_event_seq INTEGER
                        CHECK(attached_event_seq IS NULL OR attached_event_seq >= 1),
                    sha256 TEXT NOT NULL
                        CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
                    byte_size INTEGER NOT NULL CHECK(byte_size BETWEEN 1 AND 12582912),
                    width INTEGER CHECK(width IS NULL OR width BETWEEN 1 AND 8192),
                    height INTEGER CHECK(height IS NULL OR height BETWEEN 1 AND 8192),
                    duration_ms INTEGER
                        CHECK(duration_ms IS NULL OR duration_ms BETWEEN 1 AND 300000),
                    sample_rate_hz INTEGER
                        CHECK(sample_rate_hz IS NULL OR sample_rate_hz BETWEEN 8000 AND 48000),
                    channels INTEGER CHECK(channels IS NULL OR channels BETWEEN 1 AND 2),
                    payload BLOB NOT NULL CHECK(length(payload)=byte_size),
                    CHECK(
                        (attachment_state='staged' AND expires_at IS NOT NULL
                            AND attached_event_seq IS NULL)
                        OR
                        (attachment_state='attached' AND attached_event_seq IS NOT NULL)
                    ),
                    CHECK(
                        (attachment_kind='image'
                            AND media_type IN ('image/png','image/jpeg')
                            AND width IS NOT NULL AND height IS NOT NULL
                            AND duration_ms IS NULL AND sample_rate_hz IS NULL
                            AND channels IS NULL)
                        OR
                        (attachment_kind='audio' AND media_type='audio/wav'
                            AND width IS NULL AND height IS NULL
                            AND duration_ms IS NOT NULL AND sample_rate_hz IS NOT NULL
                            AND channels IS NOT NULL)
                    ),
                    FOREIGN KEY(session_id, attached_event_seq)
                        REFERENCES agent_conversation_events(session_id, event_seq)
                        ON DELETE CASCADE
                ) STRICT
                """
            )
            connection.execute(
                """
                INSERT INTO agent_attachments(
                    attachment_id,session_id,model_alias,capability_probe_version,
                    attachment_kind,media_type,display_name,source_kind,
                    attachment_state,retention_policy,created_at,expires_at,
                    attached_event_seq,sha256,byte_size,width,height,duration_ms,
                    sample_rate_hz,channels,payload
                )
                SELECT
                    attachment_id,session_id,model_alias,capability_probe_version,
                    attachment_kind,media_type,display_name,source_kind,
                    attachment_state,retention_policy,created_at,expires_at,
                    attached_event_seq,sha256,byte_size,width,height,duration_ms,
                    sample_rate_hz,channels,payload
                FROM agent_attachments_v22_current
                """
            )
            connection.execute("DROP TABLE agent_attachments_v22_current")
            connection.execute(
                "CREATE INDEX agent_attachments_session_state_idx "
                "ON agent_attachments(session_id, attachment_state, created_at, attachment_id)"
            )
            connection.execute(
                "CREATE INDEX agent_attachments_expiry_idx ON agent_attachments(expires_at) "
                "WHERE attachment_state='staged'"
            )
            connection.execute(
                """
                CREATE TRIGGER agent_attachment_payload_immutable
                BEFORE UPDATE ON agent_attachments
                WHEN NEW.payload != OLD.payload
                  OR NEW.sha256 != OLD.sha256
                  OR NEW.byte_size != OLD.byte_size
                  OR NEW.media_type != OLD.media_type
                  OR NEW.attachment_kind != OLD.attachment_kind
                BEGIN SELECT RAISE(ABORT, 'agent attachment payload is immutable'); END
                """
            )

        # Schema 21.
        artifact_columns = columns(connection, "agent_artifacts")
        if "archived_at" in artifact_columns or "removed_at" in artifact_columns:
            future_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM agent_artifacts "
                    "WHERE archived_at IS NOT NULL OR removed_at IS NOT NULL"
                ).fetchone()[0]
            )
            assert future_count == 0, "historical artifact fixture contains future lifecycle rows"
            connection.execute("DROP TRIGGER IF EXISTS agent_artifacts_lifecycle_coherent_insert")
            connection.execute("DROP TRIGGER IF EXISTS agent_artifacts_lifecycle_coherent_update")
            connection.execute("DROP INDEX IF EXISTS agent_artifacts_session_lifecycle_idx")
            if "removed_at" in artifact_columns:
                connection.execute("ALTER TABLE agent_artifacts DROP COLUMN removed_at")
            if "archived_at" in artifact_columns:
                connection.execute("ALTER TABLE agent_artifacts DROP COLUMN archived_at")

    return downgrade
