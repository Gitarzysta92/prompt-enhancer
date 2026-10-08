"""Dedicated SQLite boundary for authored Agent navigation and local history."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from typing import Iterator, Literal, Sequence, cast

from ...application.agent_catalog import (
    MAX_AGENT_CATALOG_PAGE_SIZE,
    MAX_AGENT_CATALOG_SESSIONS,
    MAX_AGENT_HISTORY_EVENT_CHARS,
    MAX_AGENT_HISTORY_EVENTS,
    MAX_AGENT_PROJECTS,
    AgentCatalogError,
    AgentCatalogSessionRecord,
    AgentMessageSearchHit,
    AgentMessageSearchRequest,
    AgentHistorySnapshot,
    AgentHistoryState,
    AgentRetentionPolicy,
    AgentProjectRecord,
    AgentSessionForkReceipt,
    AgentSessionLineage,
    ForkAgentSession,
    StoredAgentEvent,
    UpdateAgentCatalogSession,
    UpdateAgentProject,
)
from ...application.agent_mcp_connections import (
    AgentMcpClientKind,
    AgentMcpConnection,
    AgentMcpConnectionError,
    AgentMcpConnectionScope,
    AgentMcpToolOutcome,
    AgentMcpToolSource,
    _connection_state,
)
from ...application.agent_controller_ownership import (
    AgentControllerHandoff,
    AgentControllerOperation,
    AgentControllerOwnership,
    AgentControllerOwnershipError,
    AgentControllerOwnershipReleaseReceipt,
    AgentControllerRestartReconciliationReceipt,
    AgentControllerOwnershipState,
)
from ...config import lexical_absolute_path, path_has_symlink_component


AGENT_CATALOG_DATABASE_FILENAME = "agent-catalog.sqlite3"
AGENT_CATALOG_SCHEMA_VERSION = 31

_SCHEMA_V1 = r"""
CREATE TABLE IF NOT EXISTS agent_projects (
    project_id TEXT PRIMARY KEY
        CHECK(length(project_id)=32 AND project_id NOT GLOB '*[^0-9a-f]*'),
    name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 120),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision >= 1),
    pinned INTEGER NOT NULL CHECK(pinned IN (0, 1)),
    archived_at TEXT,
    is_default INTEGER NOT NULL CHECK(is_default IN (0, 1))
) STRICT;

CREATE UNIQUE INDEX IF NOT EXISTS agent_projects_one_default_idx
    ON agent_projects(is_default) WHERE is_default=1;
CREATE INDEX IF NOT EXISTS agent_projects_order_idx
    ON agent_projects(pinned DESC, updated_at DESC, project_id);

CREATE TABLE IF NOT EXISTS agent_catalog_sessions (
    session_id TEXT PRIMARY KEY
        CHECK(length(session_id)=32 AND session_id NOT GLOB '*[^0-9a-f]*'),
    project_id TEXT NOT NULL REFERENCES agent_projects(project_id) ON DELETE RESTRICT,
    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
    workspace TEXT NOT NULL CHECK(length(workspace) BETWEEN 1 AND 1024),
    model_alias TEXT CHECK(model_alias IS NULL OR length(model_alias) BETWEEN 1 AND 64),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_opened_at TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK(revision >= 1),
    pinned INTEGER NOT NULL CHECK(pinned IN (0, 1)),
    archived_at TEXT,
    history_state TEXT NOT NULL CHECK(
        history_state IN ('memory_only')
    )
) STRICT;

CREATE INDEX IF NOT EXISTS agent_catalog_sessions_project_idx
    ON agent_catalog_sessions(project_id, pinned DESC, last_opened_at DESC, session_id);
CREATE INDEX IF NOT EXISTS agent_catalog_sessions_order_idx
    ON agent_catalog_sessions(pinned DESC, last_opened_at DESC, session_id);
"""

_SCHEMA_V2 = (
    """
    ALTER TABLE agent_catalog_sessions
    ADD COLUMN retention_policy TEXT NOT NULL DEFAULT 'metadata_only'
        CHECK(retention_policy IN ('metadata_only', 'local_history'))
    """,
    """
    ALTER TABLE agent_catalog_sessions
    ADD COLUMN history_revision INTEGER NOT NULL DEFAULT 0 CHECK(history_revision >= 0)
    """,
    """
    ALTER TABLE agent_catalog_sessions
    ADD COLUMN last_event_seq INTEGER NOT NULL DEFAULT 0 CHECK(last_event_seq >= 0)
    """,
    """
    ALTER TABLE agent_catalog_sessions
    ADD COLUMN turn_count INTEGER NOT NULL DEFAULT 0 CHECK(turn_count >= 0)
    """,
    """
    ALTER TABLE agent_catalog_sessions
    ADD COLUMN history_profile_json TEXT
        CHECK(history_profile_json IS NULL OR length(history_profile_json) <= 16000)
    """,
    """
    CREATE TABLE agent_conversation_events (
        session_id TEXT NOT NULL
            REFERENCES agent_catalog_sessions(session_id) ON DELETE CASCADE,
        event_seq INTEGER NOT NULL CHECK(event_seq >= 1),
        event_at TEXT NOT NULL,
        event_kind TEXT NOT NULL CHECK(event_kind IN (
            'user', 'assistant', 'tool_call', 'tool_result', 'status', 'error', 'done'
        )),
        turn_id TEXT CHECK(
            turn_id IS NULL OR (length(turn_id)=32 AND turn_id NOT GLOB '*[^0-9a-f]*')
        ),
        event_contract_version TEXT NOT NULL CHECK(event_contract_version='agent-history.v1'),
        payload_json TEXT NOT NULL CHECK(length(payload_json) BETWEEN 2 AND 250000),
        PRIMARY KEY(session_id, event_seq)
    ) STRICT
    """,
    """
    CREATE UNIQUE INDEX agent_conversation_settled_turn_idx
        ON agent_conversation_events(session_id, turn_id)
        WHERE event_kind='done'
    """,
    """
    CREATE INDEX agent_conversation_events_order_idx
        ON agent_conversation_events(session_id, event_seq)
    """,
)

_SCHEMA_V3 = (
    """
    CREATE TABLE agent_artifacts (
        artifact_id TEXT PRIMARY KEY
            CHECK(length(artifact_id)=32 AND artifact_id NOT GLOB '*[^0-9a-f]*'),
        session_id TEXT NOT NULL
            REFERENCES agent_catalog_sessions(session_id) ON DELETE CASCADE,
        title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 120),
        artifact_kind TEXT NOT NULL CHECK(artifact_kind IN (
            'code','markdown','text','data','image','pdf','document','binary'
        )),
        relative_path TEXT NOT NULL CHECK(length(relative_path) BETWEEN 1 AND 1024),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision >= 1),
        latest_version_number INTEGER NOT NULL CHECK(latest_version_number >= 1),
        UNIQUE(session_id, relative_path)
    ) STRICT
    """,
    """
    CREATE TABLE agent_artifact_versions (
        version_id TEXT PRIMARY KEY
            CHECK(length(version_id)=32 AND version_id NOT GLOB '*[^0-9a-f]*'),
        artifact_id TEXT NOT NULL
            REFERENCES agent_artifacts(artifact_id) ON DELETE CASCADE,
        version_number INTEGER NOT NULL CHECK(version_number >= 1),
        created_at TEXT NOT NULL,
        relative_path TEXT NOT NULL CHECK(length(relative_path) BETWEEN 1 AND 1024),
        media_type TEXT NOT NULL CHECK(length(media_type) BETWEEN 1 AND 128),
        preview_kind TEXT NOT NULL CHECK(preview_kind IN (
            'text','image','pdf','download_only'
        )),
        provenance TEXT NOT NULL CHECK(provenance IN (
            'reviewed_write','verified_output','generated_unverified','external_effect_unknown'
        )),
        sha256 TEXT NOT NULL
            CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
        byte_size INTEGER NOT NULL CHECK(byte_size >= 0 AND byte_size <= 25165824),
        source_turn_id TEXT CHECK(
            source_turn_id IS NULL OR
            (length(source_turn_id)=32 AND source_turn_id NOT GLOB '*[^0-9a-f]*')
        ),
        source_event_seq INTEGER CHECK(source_event_seq IS NULL OR source_event_seq >= 1),
        UNIQUE(artifact_id, version_number)
    ) STRICT
    """,
    """
    CREATE UNIQUE INDEX agent_artifact_source_event_idx
        ON agent_artifact_versions(artifact_id, source_event_seq)
        WHERE source_event_seq IS NOT NULL
    """,
    """
    CREATE INDEX agent_artifacts_session_order_idx
        ON agent_artifacts(session_id, updated_at DESC, artifact_id)
    """,
    """
    CREATE INDEX agent_artifact_versions_order_idx
        ON agent_artifact_versions(artifact_id, version_number)
    """,
    """
    CREATE TRIGGER agent_artifact_versions_immutable
        BEFORE UPDATE ON agent_artifact_versions
        BEGIN SELECT RAISE(ABORT, 'agent artifact versions are immutable'); END
    """,
)

_SCHEMA_V4 = (
    """
    CREATE TABLE agent_attachments (
        attachment_id TEXT PRIMARY KEY
            CHECK(length(attachment_id)=32 AND attachment_id NOT GLOB '*[^0-9a-f]*'),
        session_id TEXT NOT NULL
            REFERENCES agent_catalog_sessions(session_id) ON DELETE CASCADE,
        model_alias TEXT NOT NULL
            CHECK(length(model_alias) BETWEEN 1 AND 64),
        capability_probe_version TEXT NOT NULL
            CHECK(length(capability_probe_version) BETWEEN 1 AND 64),
        attachment_kind TEXT NOT NULL CHECK(attachment_kind IN ('image','audio')),
        media_type TEXT NOT NULL CHECK(media_type IN ('image/png','image/jpeg','audio/wav')),
        display_name TEXT NOT NULL CHECK(length(display_name) BETWEEN 1 AND 120),
        source_kind TEXT NOT NULL CHECK(source_kind IN ('file','microphone')),
        attachment_state TEXT NOT NULL CHECK(attachment_state IN ('staged','attached')),
        retention_policy TEXT NOT NULL CHECK(retention_policy IN ('memory_only','local_history')),
        created_at TEXT NOT NULL,
        expires_at TEXT,
        attached_event_seq INTEGER CHECK(attached_event_seq IS NULL OR attached_event_seq >= 1),
        sha256 TEXT NOT NULL
            CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
        byte_size INTEGER NOT NULL CHECK(byte_size BETWEEN 1 AND 12582912),
        width INTEGER CHECK(width IS NULL OR width BETWEEN 1 AND 8192),
        height INTEGER CHECK(height IS NULL OR height BETWEEN 1 AND 8192),
        duration_ms INTEGER CHECK(duration_ms IS NULL OR duration_ms BETWEEN 1 AND 300000),
        sample_rate_hz INTEGER CHECK(sample_rate_hz IS NULL OR sample_rate_hz BETWEEN 8000 AND 48000),
        channels INTEGER CHECK(channels IS NULL OR channels BETWEEN 1 AND 2),
        payload BLOB NOT NULL CHECK(length(payload)=byte_size),
        CHECK(
            (attachment_state='staged' AND expires_at IS NOT NULL AND attached_event_seq IS NULL)
            OR
            (attachment_state='attached' AND attached_event_seq IS NOT NULL)
        ),
        CHECK(
            (attachment_kind='image' AND media_type IN ('image/png','image/jpeg')
                AND width IS NOT NULL AND height IS NOT NULL
                AND duration_ms IS NULL AND sample_rate_hz IS NULL AND channels IS NULL)
            OR
            (attachment_kind='audio' AND media_type='audio/wav'
                AND width IS NULL AND height IS NULL
                AND duration_ms IS NOT NULL AND sample_rate_hz IS NOT NULL AND channels IS NOT NULL)
        ),
        FOREIGN KEY(session_id, attached_event_seq)
            REFERENCES agent_conversation_events(session_id, event_seq) ON DELETE CASCADE
    ) STRICT
    """,
    """
    CREATE INDEX agent_attachments_session_state_idx
        ON agent_attachments(session_id, attachment_state, created_at, attachment_id)
    """,
    """
    CREATE INDEX agent_attachments_expiry_idx
        ON agent_attachments(expires_at)
        WHERE attachment_state='staged'
    """,
    """
    CREATE TRIGGER agent_attachment_payload_immutable
        BEFORE UPDATE ON agent_attachments
        WHEN NEW.payload != OLD.payload
          OR NEW.sha256 != OLD.sha256
          OR NEW.byte_size != OLD.byte_size
          OR NEW.media_type != OLD.media_type
          OR NEW.attachment_kind != OLD.attachment_kind
        BEGIN SELECT RAISE(ABORT, 'agent attachment payload is immutable'); END
    """,
)

_SCHEMA_V5 = (
    """
    CREATE TABLE agent_session_lineage (
        session_id TEXT PRIMARY KEY
            REFERENCES agent_catalog_sessions(session_id) ON DELETE CASCADE,
        fork_request_id TEXT NOT NULL UNIQUE
            CHECK(length(fork_request_id)=32 AND fork_request_id NOT GLOB '*[^0-9a-f]*'),
        source_project_id TEXT NOT NULL
            CHECK(length(source_project_id)=32 AND source_project_id NOT GLOB '*[^0-9a-f]*'),
        source_session_id TEXT NOT NULL
            CHECK(length(source_session_id)=32 AND source_session_id NOT GLOB '*[^0-9a-f]*'),
        source_catalog_revision INTEGER NOT NULL CHECK(source_catalog_revision >= 1),
        source_history_revision INTEGER NOT NULL CHECK(source_history_revision >= 0),
        requested_destination_project_id TEXT
            CHECK(requested_destination_project_id IS NULL OR
                  (length(requested_destination_project_id)=32 AND
                   requested_destination_project_id NOT GLOB '*[^0-9a-f]*')),
        requested_through_event_seq INTEGER CHECK(
            requested_through_event_seq IS NULL OR requested_through_event_seq >= 0
        ),
        requested_title TEXT CHECK(
            requested_title IS NULL OR length(requested_title) BETWEEN 1 AND 120
        ),
        branch_event_seq INTEGER NOT NULL CHECK(branch_event_seq >= 0),
        copied_event_count INTEGER NOT NULL CHECK(copied_event_count >= 0),
        copied_turn_count INTEGER NOT NULL CHECK(copied_turn_count >= 0),
        copied_attachment_count INTEGER NOT NULL CHECK(copied_attachment_count >= 0),
        source_tail_omitted INTEGER NOT NULL CHECK(source_tail_omitted IN (0, 1)),
        created_at TEXT NOT NULL,
        CHECK(copied_event_count = branch_event_seq),
        CHECK(branch_event_seq <= source_history_revision),
        CHECK(copied_turn_count <= copied_event_count)
    ) STRICT
    """,
    """
    CREATE INDEX agent_session_lineage_source_idx
        ON agent_session_lineage(source_session_id, created_at, session_id)
    """,
)

_SCHEMA_V6 = (
    """
    CREATE TABLE agent_mcp_connections (
        connection_id TEXT PRIMARY KEY
            CHECK(length(connection_id)=32 AND connection_id NOT GLOB '*[^0-9a-f]*'),
        request_id TEXT NOT NULL UNIQUE
            CHECK(length(request_id)=32 AND request_id NOT GLOB '*[^0-9a-f]*'),
        request_fingerprint TEXT NOT NULL
            CHECK(length(request_fingerprint)=64 AND request_fingerprint NOT GLOB '*[^0-9a-f]*'),
        label TEXT NOT NULL CHECK(length(label) BETWEEN 1 AND 80),
        client_kind TEXT NOT NULL CHECK(client_kind IN ('codex','claude','other')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        last_used_at TEXT,
        revoked_at TEXT,
        revision INTEGER NOT NULL CHECK(revision >= 1),
        credential_revision INTEGER NOT NULL CHECK(credential_revision >= 1),
        allow_model_lifecycle INTEGER NOT NULL
            CHECK(allow_model_lifecycle IN (0, 1))
    ) STRICT
    """,
    """
    CREATE INDEX agent_mcp_connections_status_idx
        ON agent_mcp_connections(revoked_at, expires_at, updated_at DESC, connection_id)
    """,
    """
    CREATE TABLE agent_mcp_connection_rotations (
        request_id TEXT PRIMARY KEY
            CHECK(length(request_id)=32 AND request_id NOT GLOB '*[^0-9a-f]*'),
        request_fingerprint TEXT NOT NULL
            CHECK(length(request_fingerprint)=64 AND request_fingerprint NOT GLOB '*[^0-9a-f]*'),
        connection_id TEXT NOT NULL
            REFERENCES agent_mcp_connections(connection_id) ON DELETE CASCADE,
        expected_revision INTEGER NOT NULL CHECK(expected_revision >= 1),
        resulting_revision INTEGER NOT NULL CHECK(resulting_revision >= 2),
        resulting_credential_revision INTEGER NOT NULL
            CHECK(resulting_credential_revision >= 2),
        created_at TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE INDEX agent_mcp_connection_rotations_connection_idx
        ON agent_mcp_connection_rotations(connection_id, created_at, request_id)
    """,
)

_SCHEMA_V7 = (
    "DROP TRIGGER agent_attachment_payload_immutable",
    "DROP INDEX agent_attachments_session_state_idx",
    "DROP INDEX agent_attachments_expiry_idx",
    "ALTER TABLE agent_attachments RENAME TO agent_attachments_v6",
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
        media_type TEXT NOT NULL CHECK(media_type IN ('image/png','image/jpeg','audio/wav')),
        display_name TEXT NOT NULL CHECK(length(display_name) BETWEEN 1 AND 120),
        source_kind TEXT NOT NULL
            CHECK(source_kind IN ('file','microphone','external_agent')),
        attachment_state TEXT NOT NULL CHECK(attachment_state IN ('staged','attached')),
        retention_policy TEXT NOT NULL CHECK(retention_policy IN ('memory_only','local_history')),
        created_at TEXT NOT NULL,
        expires_at TEXT,
        attached_event_seq INTEGER CHECK(attached_event_seq IS NULL OR attached_event_seq >= 1),
        sha256 TEXT NOT NULL
            CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
        byte_size INTEGER NOT NULL CHECK(byte_size BETWEEN 1 AND 12582912),
        width INTEGER CHECK(width IS NULL OR width BETWEEN 1 AND 8192),
        height INTEGER CHECK(height IS NULL OR height BETWEEN 1 AND 8192),
        duration_ms INTEGER CHECK(duration_ms IS NULL OR duration_ms BETWEEN 1 AND 300000),
        sample_rate_hz INTEGER CHECK(sample_rate_hz IS NULL OR sample_rate_hz BETWEEN 8000 AND 48000),
        channels INTEGER CHECK(channels IS NULL OR channels BETWEEN 1 AND 2),
        payload BLOB NOT NULL CHECK(length(payload)=byte_size),
        CHECK(
            (attachment_state='staged' AND expires_at IS NOT NULL AND attached_event_seq IS NULL)
            OR
            (attachment_state='attached' AND attached_event_seq IS NOT NULL)
        ),
        CHECK(
            (attachment_kind='image' AND media_type IN ('image/png','image/jpeg')
                AND width IS NOT NULL AND height IS NOT NULL
                AND duration_ms IS NULL AND sample_rate_hz IS NULL AND channels IS NULL)
            OR
            (attachment_kind='audio' AND media_type='audio/wav'
                AND width IS NULL AND height IS NULL
                AND duration_ms IS NOT NULL AND sample_rate_hz IS NOT NULL AND channels IS NOT NULL)
        ),
        FOREIGN KEY(session_id, attached_event_seq)
            REFERENCES agent_conversation_events(session_id, event_seq) ON DELETE CASCADE
    ) STRICT
    """,
    """
    INSERT INTO agent_attachments(
        attachment_id,session_id,model_alias,capability_probe_version,
        attachment_kind,media_type,display_name,source_kind,attachment_state,
        retention_policy,created_at,expires_at,attached_event_seq,sha256,byte_size,
        width,height,duration_ms,sample_rate_hz,channels,payload
    )
    SELECT
        attachment_id,session_id,model_alias,capability_probe_version,
        attachment_kind,media_type,display_name,source_kind,attachment_state,
        retention_policy,created_at,expires_at,attached_event_seq,sha256,byte_size,
        width,height,duration_ms,sample_rate_hz,channels,payload
    FROM agent_attachments_v6
    """,
    "DROP TABLE agent_attachments_v6",
    """
    CREATE INDEX agent_attachments_session_state_idx
        ON agent_attachments(session_id, attachment_state, created_at, attachment_id)
    """,
    """
    CREATE INDEX agent_attachments_expiry_idx
        ON agent_attachments(expires_at)
        WHERE attachment_state='staged'
    """,
    """
    CREATE TRIGGER agent_attachment_payload_immutable
        BEFORE UPDATE ON agent_attachments
        WHEN NEW.payload != OLD.payload
          OR NEW.sha256 != OLD.sha256
          OR NEW.byte_size != OLD.byte_size
          OR NEW.media_type != OLD.media_type
          OR NEW.attachment_kind != OLD.attachment_kind
        BEGIN SELECT RAISE(ABORT, 'agent attachment payload is immutable'); END
    """,
)

_SCHEMA_V8 = (
    "DROP TRIGGER agent_artifact_versions_immutable",
    "DROP INDEX agent_artifact_source_event_idx",
    "DROP INDEX agent_artifact_versions_order_idx",
    "ALTER TABLE agent_artifact_versions RENAME TO agent_artifact_versions_v7",
    """
    CREATE TABLE agent_artifact_versions (
        version_id TEXT PRIMARY KEY
            CHECK(length(version_id)=32 AND version_id NOT GLOB '*[^0-9a-f]*'),
        artifact_id TEXT NOT NULL
            REFERENCES agent_artifacts(artifact_id) ON DELETE CASCADE,
        version_number INTEGER NOT NULL CHECK(version_number >= 1),
        created_at TEXT NOT NULL,
        relative_path TEXT NOT NULL CHECK(length(relative_path) BETWEEN 1 AND 1024),
        media_type TEXT NOT NULL CHECK(length(media_type) BETWEEN 1 AND 128),
        preview_kind TEXT NOT NULL CHECK(preview_kind IN (
            'text','image','pdf','document','download_only'
        )),
        provenance TEXT NOT NULL CHECK(provenance IN (
            'reviewed_write','verified_output','generated_unverified','external_effect_unknown'
        )),
        sha256 TEXT NOT NULL
            CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
        byte_size INTEGER NOT NULL CHECK(byte_size >= 0 AND byte_size <= 25165824),
        source_turn_id TEXT CHECK(
            source_turn_id IS NULL OR
            (length(source_turn_id)=32 AND source_turn_id NOT GLOB '*[^0-9a-f]*')
        ),
        source_event_seq INTEGER CHECK(source_event_seq IS NULL OR source_event_seq >= 1),
        UNIQUE(artifact_id, version_number)
    ) STRICT
    """,
    """
    INSERT INTO agent_artifact_versions(
        version_id,artifact_id,version_number,created_at,relative_path,
        media_type,preview_kind,provenance,sha256,byte_size,
        source_turn_id,source_event_seq
    )
    SELECT
        version_id,artifact_id,version_number,created_at,relative_path,
        media_type,preview_kind,provenance,sha256,byte_size,
        source_turn_id,source_event_seq
    FROM agent_artifact_versions_v7
    """,
    "DROP TABLE agent_artifact_versions_v7",
    """
    CREATE UNIQUE INDEX agent_artifact_source_event_idx
        ON agent_artifact_versions(artifact_id, source_event_seq)
        WHERE source_event_seq IS NOT NULL
    """,
    """
    CREATE INDEX agent_artifact_versions_order_idx
        ON agent_artifact_versions(artifact_id, version_number)
    """,
    """
    CREATE TRIGGER agent_artifact_versions_immutable
        BEFORE UPDATE ON agent_artifact_versions
        BEGIN SELECT RAISE(ABORT, 'agent artifact versions are immutable'); END
    """,
)

_SCHEMA_V9 = (
    """
    ALTER TABLE agent_mcp_connections
    ADD COLUMN last_tool_at TEXT
    """,
    """
    ALTER TABLE agent_mcp_connections
    ADD COLUMN last_tool_name TEXT CHECK(
        last_tool_name IS NULL OR
        (length(last_tool_name) BETWEEN 7 AND 48 AND
         last_tool_name NOT GLOB '*[^a-z0-9_]*')
    )
    """,
    """
    ALTER TABLE agent_mcp_connections
    ADD COLUMN last_tool_outcome TEXT CHECK(
        last_tool_outcome IS NULL OR
        last_tool_outcome IN ('succeeded','failed')
    )
    """,
)

_SCHEMA_V10 = (
    """
    ALTER TABLE agent_mcp_connections
    ADD COLUMN last_tool_source TEXT CHECK(
        last_tool_source IS NULL OR
        last_tool_source IN ('external_client','native_self_test')
    )
    """,
    """
    ALTER TABLE agent_mcp_connections
    ADD COLUMN last_auth_rejected_at TEXT
    """,
)

_SCHEMA_V11 = (
    "DROP TRIGGER agent_artifact_versions_immutable",
    "DROP INDEX agent_artifact_source_event_idx",
    "DROP INDEX agent_artifact_versions_order_idx",
    "ALTER TABLE agent_artifact_versions RENAME TO agent_artifact_versions_v10",
    """
    CREATE TABLE agent_artifact_versions (
        version_id TEXT PRIMARY KEY
            CHECK(length(version_id)=32 AND version_id NOT GLOB '*[^0-9a-f]*'),
        artifact_id TEXT NOT NULL
            REFERENCES agent_artifacts(artifact_id) ON DELETE CASCADE,
        version_number INTEGER NOT NULL CHECK(version_number >= 1),
        created_at TEXT NOT NULL,
        relative_path TEXT NOT NULL CHECK(length(relative_path) BETWEEN 1 AND 1024),
        media_type TEXT NOT NULL CHECK(length(media_type) BETWEEN 1 AND 128),
        preview_kind TEXT NOT NULL CHECK(preview_kind IN (
            'text','image','pdf','document','download_only'
        )),
        provenance TEXT NOT NULL CHECK(provenance IN (
            'reviewed_write','reviewed_move','verified_output',
            'generated_unverified','external_effect_unknown'
        )),
        sha256 TEXT NOT NULL
            CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
        byte_size INTEGER NOT NULL CHECK(byte_size >= 0 AND byte_size <= 25165824),
        source_turn_id TEXT CHECK(
            source_turn_id IS NULL OR
            (length(source_turn_id)=32 AND source_turn_id NOT GLOB '*[^0-9a-f]*')
        ),
        source_event_seq INTEGER CHECK(source_event_seq IS NULL OR source_event_seq >= 1),
        UNIQUE(artifact_id, version_number)
    ) STRICT
    """,
    """
    INSERT INTO agent_artifact_versions(
        version_id,artifact_id,version_number,created_at,relative_path,
        media_type,preview_kind,provenance,sha256,byte_size,
        source_turn_id,source_event_seq
    )
    SELECT
        version_id,artifact_id,version_number,created_at,relative_path,
        media_type,preview_kind,provenance,sha256,byte_size,
        source_turn_id,source_event_seq
    FROM agent_artifact_versions_v10
    """,
    "DROP TABLE agent_artifact_versions_v10",
    """
    CREATE UNIQUE INDEX agent_artifact_source_event_idx
        ON agent_artifact_versions(artifact_id, source_event_seq)
        WHERE source_event_seq IS NOT NULL
    """,
    """
    CREATE INDEX agent_artifact_versions_order_idx
        ON agent_artifact_versions(artifact_id, version_number)
    """,
    """
    CREATE TRIGGER agent_artifact_versions_immutable
        BEFORE UPDATE ON agent_artifact_versions
        BEGIN SELECT RAISE(ABORT, 'agent artifact versions are immutable'); END
    """,
)

_SCHEMA_V12 = (
    """
    CREATE TABLE mcp_managed_servers (
        management_id TEXT PRIMARY KEY
            CHECK(length(management_id)=32 AND management_id NOT GLOB '*[^0-9a-f]*'),
        request_id TEXT NOT NULL UNIQUE
            CHECK(length(request_id)=32 AND request_id NOT GLOB '*[^0-9a-f]*'),
        request_fingerprint TEXT NOT NULL
            CHECK(length(request_fingerprint)=64 AND request_fingerprint NOT GLOB '*[^0-9a-f]*'),
        catalog_id TEXT NOT NULL
            CHECK(length(catalog_id)=32 AND catalog_id NOT GLOB '*[^0-9a-f]*'),
        server_name TEXT NOT NULL CHECK(length(server_name) BETWEEN 3 AND 241),
        server_title TEXT NOT NULL CHECK(length(server_title) BETWEEN 1 AND 100),
        server_version TEXT NOT NULL CHECK(length(server_version) BETWEEN 1 AND 255),
        server_status_at_review TEXT NOT NULL
            CHECK(server_status_at_review IN ('active','deprecated','deleted')),
        option_id TEXT NOT NULL
            CHECK(length(option_id)=32 AND option_id NOT GLOB '*[^0-9a-f]*'),
        plan_revision TEXT NOT NULL
            CHECK(length(plan_revision)=64 AND plan_revision NOT GLOB '*[^0-9a-f]*'),
        option_kind TEXT NOT NULL CHECK(option_kind IN ('local_package','remote_server')),
        option_label TEXT NOT NULL CHECK(length(option_label) BETWEEN 1 AND 120),
        registry_type TEXT CHECK(registry_type IS NULL OR length(registry_type) BETWEEN 1 AND 32),
        package_identifier TEXT CHECK(package_identifier IS NULL OR length(package_identifier) BETWEEN 1 AND 512),
        package_version TEXT CHECK(package_version IS NULL OR length(package_version) BETWEEN 1 AND 255),
        runtime_hint TEXT CHECK(runtime_hint IS NULL OR length(runtime_hint) BETWEEN 1 AND 32),
        transport TEXT NOT NULL CHECK(transport IN ('stdio','streamable-http','sse','unknown')),
        endpoint_host TEXT CHECK(endpoint_host IS NULL OR length(endpoint_host) BETWEEN 1 AND 255),
        endpoint_state TEXT NOT NULL CHECK(endpoint_state IN (
            'not_applicable','fixed_host','template_requires_configuration','invalid'
        )),
        secure_transport INTEGER CHECK(secure_transport IS NULL OR secure_transport IN (0,1)),
        required_permissions_json TEXT NOT NULL
            CHECK(length(required_permissions_json) BETWEEN 2 AND 256),
        risks_json TEXT NOT NULL CHECK(length(risks_json) BETWEEN 2 AND 1024),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision >= 1),
        lifecycle_state TEXT NOT NULL CHECK(lifecycle_state='planned'),
        installation_state TEXT NOT NULL CHECK(installation_state='not_installed'),
        host_state TEXT NOT NULL CHECK(host_state='not_started'),
        health_state TEXT NOT NULL CHECK(health_state='not_checked'),
        last_health_checked_at TEXT CHECK(last_health_checked_at IS NULL),
        update_state TEXT NOT NULL CHECK(update_state='not_checked'),
        latest_available_version TEXT CHECK(latest_available_version IS NULL),
        tool_routing_state TEXT NOT NULL CHECK(tool_routing_state='inactive'),
        UNIQUE(catalog_id, option_id),
        CHECK(
            (option_kind='local_package' AND registry_type IS NOT NULL
                AND package_identifier IS NOT NULL AND endpoint_state='not_applicable')
            OR
            (option_kind='remote_server' AND registry_type IS NULL
                AND package_identifier IS NULL AND package_version IS NULL
                AND runtime_hint IS NULL AND endpoint_state!='not_applicable')
        ),
        CHECK(
            (endpoint_state='fixed_host' AND endpoint_host IS NOT NULL
                AND secure_transport IS NOT NULL)
            OR
            (endpoint_state!='fixed_host' AND endpoint_host IS NULL
                AND (endpoint_state='not_applicable' OR secure_transport IS NULL))
        )
    ) STRICT
    """,
    """
    CREATE INDEX mcp_managed_servers_order_idx
        ON mcp_managed_servers(updated_at DESC, management_id)
    """,
    """
    CREATE TABLE mcp_managed_requirements (
        management_id TEXT NOT NULL
            REFERENCES mcp_managed_servers(management_id) ON DELETE CASCADE,
        requirement_id TEXT NOT NULL
            CHECK(length(requirement_id)=32 AND requirement_id NOT GLOB '*[^0-9a-f]*'),
        requirement_order INTEGER NOT NULL CHECK(requirement_order BETWEEN 0 AND 63),
        location TEXT NOT NULL CHECK(location IN (
            'runtime_argument','package_argument','environment_variable',
            'transport_header','remote_variable'
        )),
        name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 128),
        required INTEGER NOT NULL CHECK(required IN (0,1)),
        secret INTEGER NOT NULL CHECK(secret IN (0,1)),
        value_format TEXT NOT NULL CHECK(value_format IN (
            'string','number','boolean','filepath','unknown'
        )),
        user_value_needed INTEGER NOT NULL CHECK(user_value_needed IN (0,1)),
        fixed_value_declared INTEGER NOT NULL CHECK(fixed_value_declared IN (0,1)),
        default_declared INTEGER NOT NULL CHECK(default_declared IN (0,1)),
        PRIMARY KEY(management_id, requirement_id),
        UNIQUE(management_id, requirement_order)
    ) STRICT
    """,
    """
    CREATE TABLE mcp_managed_project_bindings (
        management_id TEXT NOT NULL
            REFERENCES mcp_managed_servers(management_id) ON DELETE CASCADE,
        project_id TEXT NOT NULL
            REFERENCES agent_projects(project_id) ON DELETE CASCADE,
        enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
        granted_permissions_json TEXT NOT NULL
            CHECK(length(granted_permissions_json) BETWEEN 2 AND 256),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision >= 1),
        PRIMARY KEY(management_id, project_id)
    ) STRICT
    """,
    """
    CREATE INDEX mcp_managed_project_bindings_project_idx
        ON mcp_managed_project_bindings(project_id, enabled, management_id)
    """,
    """
    CREATE TABLE mcp_managed_secret_references (
        management_id TEXT NOT NULL,
        requirement_id TEXT NOT NULL,
        reference_id TEXT NOT NULL UNIQUE
            CHECK(length(reference_id)=32 AND reference_id NOT GLOB '*[^0-9a-f]*'),
        vault_provider TEXT NOT NULL CHECK(vault_provider='windows_credential_manager'),
        reference_state TEXT NOT NULL CHECK(reference_state IN (
            'pending_store','active','store_failed','pending_removal','cleanup_required'
        )),
        request_id TEXT NOT NULL
            CHECK(length(request_id)=32 AND request_id NOT GLOB '*[^0-9a-f]*'),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision >= 1),
        PRIMARY KEY(management_id, requirement_id),
        FOREIGN KEY(management_id, requirement_id)
            REFERENCES mcp_managed_requirements(management_id, requirement_id)
            ON DELETE CASCADE
    ) STRICT
    """,
    """
    CREATE TABLE mcp_managed_mutations (
        request_id TEXT PRIMARY KEY
            CHECK(length(request_id)=32 AND request_id NOT GLOB '*[^0-9a-f]*'),
        request_fingerprint TEXT NOT NULL
            CHECK(length(request_fingerprint)=64 AND request_fingerprint NOT GLOB '*[^0-9a-f]*'),
        action TEXT NOT NULL CHECK(action IN (
            'set_project_binding','store_secret','remove_secret'
        )),
        management_id TEXT NOT NULL
            REFERENCES mcp_managed_servers(management_id) ON DELETE CASCADE,
        target_id TEXT NOT NULL
            CHECK(length(target_id)=32 AND target_id NOT GLOB '*[^0-9a-f]*'),
        resulting_revision INTEGER NOT NULL CHECK(resulting_revision >= 1),
        created_at TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE INDEX mcp_managed_mutations_server_idx
        ON mcp_managed_mutations(management_id, created_at DESC, request_id)
    """,
)


_SCHEMA_V13 = (
    """
    CREATE TABLE mcp_managed_probe_receipts (
        request_id TEXT PRIMARY KEY
            CHECK(length(request_id)=32 AND request_id NOT GLOB '*[^0-9a-f]*'),
        request_fingerprint TEXT NOT NULL
            CHECK(length(request_fingerprint)=64 AND request_fingerprint NOT GLOB '*[^0-9a-f]*'),
        management_id TEXT NOT NULL
            REFERENCES mcp_managed_servers(management_id) ON DELETE CASCADE,
        resulting_revision INTEGER NOT NULL CHECK(resulting_revision >= 2),
        checked_at TEXT NOT NULL,
        transport TEXT NOT NULL CHECK(transport IN ('stdio','streamable-http','sse')),
        protocol_version TEXT NOT NULL
            CHECK(length(protocol_version)=10 AND protocol_version GLOB '20??-??-??'),
        tool_count INTEGER NOT NULL CHECK(tool_count BETWEEN 0 AND 256),
        schema_digest TEXT NOT NULL
            CHECK(length(schema_digest)=64 AND schema_digest NOT GLOB '*[^0-9a-f]*'),
        elapsed_ms INTEGER NOT NULL CHECK(elapsed_ms BETWEEN 0 AND 120000),
        process_started INTEGER NOT NULL CHECK(process_started IN (0,1)),
        process_tree_cleanup TEXT NOT NULL
            CHECK(process_tree_cleanup IN ('verified','not_applicable')),
        CHECK(
            (process_started=1 AND process_tree_cleanup='verified') OR
            (process_started=0 AND process_tree_cleanup='not_applicable')
        )
    ) STRICT
    """,
    """
    CREATE INDEX mcp_managed_probe_receipts_server_idx
        ON mcp_managed_probe_receipts(
            management_id, checked_at DESC, request_id DESC
        )
    """,
)


_SCHEMA_V14 = (
    """
    CREATE TABLE mcp_managed_lifecycle_state (
        management_id TEXT PRIMARY KEY
            REFERENCES mcp_managed_servers(management_id) ON DELETE CASCADE,
        lifecycle_state TEXT NOT NULL CHECK(lifecycle_state IN (
            'planned','installed','cleanup_required'
        )),
        installation_state TEXT NOT NULL CHECK(installation_state IN (
            'not_installed','installed','cleanup_required'
        )),
        installation_kind TEXT NOT NULL CHECK(installation_kind IN (
            'none','remote_activation','local_package'
        )),
        operation_state TEXT NOT NULL CHECK(operation_state IN (
            'idle','installing','updating','uninstalling','rolling_back',
            'cleanup_required'
        )),
        installed_plan_revision TEXT CHECK(
            installed_plan_revision IS NULL OR
            (length(installed_plan_revision)=64 AND
             installed_plan_revision NOT GLOB '*[^0-9a-f]*')
        ),
        installed_at TEXT,
        process_tree_cleanup TEXT NOT NULL CHECK(process_tree_cleanup IN (
            'not_applicable','verified','unconfirmed'
        )),
        last_error_code TEXT CHECK(
            last_error_code IS NULL OR length(last_error_code) BETWEEN 1 AND 96
        ),
        updated_at TEXT NOT NULL,
        CHECK(
            (installation_state='not_installed' AND lifecycle_state='planned'
             AND installation_kind='none' AND installed_plan_revision IS NULL
             AND installed_at IS NULL AND operation_state='idle'
             AND process_tree_cleanup='not_applicable')
            OR
            (installation_state='installed' AND lifecycle_state='installed'
             AND installation_kind!='none' AND installed_plan_revision IS NOT NULL
             AND installed_at IS NOT NULL AND operation_state='idle')
            OR
            (installation_state='cleanup_required'
             AND lifecycle_state='cleanup_required'
             AND installation_kind!='none'
             AND operation_state='cleanup_required')
        )
    ) STRICT
    """,
    """
    INSERT INTO mcp_managed_lifecycle_state(
        management_id,lifecycle_state,installation_state,installation_kind,
        operation_state,installed_plan_revision,installed_at,
        process_tree_cleanup,last_error_code,updated_at
    )
    SELECT management_id,'planned','not_installed','none','idle',NULL,NULL,
           'not_applicable',NULL,updated_at
    FROM mcp_managed_servers
    """,
    """
    CREATE TABLE mcp_managed_lifecycle_receipts (
        request_id TEXT PRIMARY KEY
            CHECK(length(request_id)=32 AND request_id NOT GLOB '*[^0-9a-f]*'),
        request_fingerprint TEXT NOT NULL
            CHECK(length(request_fingerprint)=64 AND
                  request_fingerprint NOT GLOB '*[^0-9a-f]*'),
        management_id TEXT NOT NULL
            REFERENCES mcp_managed_servers(management_id) ON DELETE CASCADE,
        action TEXT NOT NULL CHECK(action IN ('install','uninstall')),
        preview_digest TEXT NOT NULL
            CHECK(length(preview_digest)=64 AND
                  preview_digest NOT GLOB '*[^0-9a-f]*'),
        resulting_revision INTEGER NOT NULL CHECK(resulting_revision >= 2),
        resulting_installation_state TEXT NOT NULL CHECK(
            resulting_installation_state IN ('not_installed','installed')
        ),
        created_at TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE INDEX mcp_managed_lifecycle_receipts_server_idx
        ON mcp_managed_lifecycle_receipts(
            management_id, resulting_revision DESC, request_id DESC
        )
    """,
)


_SCHEMA_V15 = (
    """
    CREATE TABLE mcp_managed_local_packages (
        management_id TEXT PRIMARY KEY
            REFERENCES mcp_managed_servers(management_id) ON DELETE CASCADE,
        request_id TEXT NOT NULL UNIQUE
            CHECK(length(request_id)=32 AND request_id NOT GLOB '*[^0-9a-f]*'),
        request_fingerprint TEXT NOT NULL
            CHECK(length(request_fingerprint)=64 AND
                  request_fingerprint NOT GLOB '*[^0-9a-f]*'),
        preview_digest TEXT NOT NULL
            CHECK(length(preview_digest)=64 AND
                  preview_digest NOT GLOB '*[^0-9a-f]*'),
        status TEXT NOT NULL CHECK(status IN (
            'installing','installed','cleanup_required'
        )),
        artifact_sha256 TEXT CHECK(
            artifact_sha256 IS NULL OR
            (length(artifact_sha256)=64 AND artifact_sha256 NOT GLOB '*[^0-9a-f]*')
        ),
        artifact_bytes INTEGER CHECK(
            artifact_bytes IS NULL OR artifact_bytes BETWEEN 1 AND 67108864
        ),
        tree_digest TEXT CHECK(
            tree_digest IS NULL OR
            (length(tree_digest)=64 AND tree_digest NOT GLOB '*[^0-9a-f]*')
        ),
        manifest_digest TEXT CHECK(
            manifest_digest IS NULL OR
            (length(manifest_digest)=64 AND manifest_digest NOT GLOB '*[^0-9a-f]*')
        ),
        manifest_version TEXT CHECK(
            manifest_version IS NULL OR manifest_version IN ('0.3','0.4')
        ),
        license_state TEXT CHECK(
            license_state IS NULL OR license_state='declared'
        ),
        runtime_kind TEXT CHECK(
            runtime_kind IS NULL OR runtime_kind IN ('node','python','binary')
        ),
        runtime_version TEXT CHECK(
            runtime_version IS NULL OR length(runtime_version) BETWEEN 1 AND 64
        ),
        checked_at TEXT,
        protocol_version TEXT CHECK(
            protocol_version IS NULL OR
            (length(protocol_version)=10 AND protocol_version GLOB '20??-??-??')
        ),
        tool_count INTEGER CHECK(tool_count IS NULL OR tool_count BETWEEN 0 AND 256),
        schema_digest TEXT CHECK(
            schema_digest IS NULL OR
            (length(schema_digest)=64 AND schema_digest NOT GLOB '*[^0-9a-f]*')
        ),
        elapsed_ms INTEGER CHECK(elapsed_ms IS NULL OR elapsed_ms BETWEEN 0 AND 120000),
        process_tree_cleanup TEXT NOT NULL CHECK(process_tree_cleanup IN (
            'not_applicable','verified','unconfirmed'
        )),
        error_code TEXT CHECK(
            error_code IS NULL OR length(error_code) BETWEEN 1 AND 96
        ),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK(
            (status='installing' AND artifact_sha256 IS NULL
             AND artifact_bytes IS NULL AND tree_digest IS NULL
             AND manifest_digest IS NULL AND manifest_version IS NULL
             AND license_state IS NULL AND runtime_kind IS NULL
             AND runtime_version IS NULL AND checked_at IS NULL
             AND protocol_version IS NULL AND tool_count IS NULL
             AND schema_digest IS NULL AND elapsed_ms IS NULL
             AND process_tree_cleanup='not_applicable' AND error_code IS NULL)
            OR
            (status='installed' AND artifact_sha256 IS NOT NULL
             AND artifact_bytes IS NOT NULL AND tree_digest IS NOT NULL
             AND manifest_digest IS NOT NULL AND manifest_version IS NOT NULL
             AND license_state='declared' AND runtime_kind IS NOT NULL
             AND checked_at IS NOT NULL AND protocol_version IS NOT NULL
             AND tool_count IS NOT NULL AND schema_digest IS NOT NULL
             AND elapsed_ms IS NOT NULL AND process_tree_cleanup='verified'
             AND error_code IS NULL)
            OR
            (status='cleanup_required' AND error_code IS NOT NULL)
        )
    ) STRICT
    """,
    """
    CREATE INDEX mcp_managed_local_packages_status_idx
        ON mcp_managed_local_packages(status, updated_at, management_id)
    """,
)


_SCHEMA_V16 = (
    """
    CREATE TABLE mcp_managed_local_operations (
        request_id TEXT PRIMARY KEY
            CHECK(length(request_id)=32 AND request_id NOT GLOB '*[^0-9a-f]*'),
        request_fingerprint TEXT NOT NULL
            CHECK(length(request_fingerprint)=64 AND
                  request_fingerprint NOT GLOB '*[^0-9a-f]*'),
        management_id TEXT NOT NULL UNIQUE
            REFERENCES mcp_managed_servers(management_id) ON DELETE CASCADE,
        action TEXT NOT NULL CHECK(action IN (
            'update','uninstall','rollback','cleanup'
        )),
        preview_digest TEXT NOT NULL
            CHECK(length(preview_digest)=64 AND
                  preview_digest NOT GLOB '*[^0-9a-f]*'),
        expected_revision INTEGER NOT NULL CHECK(expected_revision >= 1),
        expected_tree_digest TEXT NOT NULL
            CHECK(length(expected_tree_digest)=64 AND
                  expected_tree_digest NOT GLOB '*[^0-9a-f]*'),
        status TEXT NOT NULL CHECK(status IN (
            'reserved','prepared','cleanup_required'
        )),
        error_code TEXT CHECK(
            error_code IS NULL OR length(error_code) BETWEEN 1 AND 96
        ),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK(
            (status IN ('reserved','prepared') AND error_code IS NULL) OR
            (status='cleanup_required' AND error_code IS NOT NULL)
        )
    ) STRICT
    """,
    """
    CREATE INDEX mcp_managed_local_operations_state_idx
        ON mcp_managed_local_operations(status, updated_at, management_id)
    """,
)


_SCHEMA_V17 = (
    """
    CREATE TABLE mcp_managed_local_update_payloads (
        request_id TEXT PRIMARY KEY
            REFERENCES mcp_managed_local_operations(request_id) ON DELETE CASCADE,
        management_id TEXT NOT NULL UNIQUE
            REFERENCES mcp_managed_servers(management_id) ON DELETE CASCADE,
        target_plan_json TEXT NOT NULL
            CHECK(length(target_plan_json) BETWEEN 2 AND 32768),
        target_plan_digest TEXT NOT NULL
            CHECK(length(target_plan_digest)=64 AND
                  target_plan_digest NOT GLOB '*[^0-9a-f]*'),
        target_result_json TEXT CHECK(
            target_result_json IS NULL OR
            length(target_result_json) BETWEEN 2 AND 32768
        ),
        target_result_digest TEXT CHECK(
            target_result_digest IS NULL OR
            (length(target_result_digest)=64 AND
             target_result_digest NOT GLOB '*[^0-9a-f]*')
        ),
        target_tree_digest TEXT CHECK(
            target_tree_digest IS NULL OR
            (length(target_tree_digest)=64 AND
             target_tree_digest NOT GLOB '*[^0-9a-f]*')
        ),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK(
            (target_result_json IS NULL AND target_result_digest IS NULL
             AND target_tree_digest IS NULL) OR
            (target_result_json IS NOT NULL AND target_result_digest IS NOT NULL
             AND target_tree_digest IS NOT NULL)
        )
    ) STRICT
    """,
    """
    CREATE TABLE mcp_managed_local_rollback_generations (
        management_id TEXT PRIMARY KEY
            REFERENCES mcp_managed_servers(management_id) ON DELETE CASCADE,
        generation_id TEXT NOT NULL UNIQUE
            CHECK(length(generation_id)=32 AND generation_id NOT GLOB '*[^0-9a-f]*'),
        generation_json TEXT NOT NULL
            CHECK(length(generation_json) BETWEEN 2 AND 32768),
        generation_digest TEXT NOT NULL
            CHECK(length(generation_digest)=64 AND
                  generation_digest NOT GLOB '*[^0-9a-f]*'),
        plan_revision TEXT NOT NULL
            CHECK(length(plan_revision)=64 AND plan_revision NOT GLOB '*[^0-9a-f]*'),
        server_version TEXT NOT NULL CHECK(length(server_version) BETWEEN 1 AND 255),
        tree_digest TEXT NOT NULL
            CHECK(length(tree_digest)=64 AND tree_digest NOT GLOB '*[^0-9a-f]*'),
        retained_at TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE INDEX mcp_managed_local_rollback_generations_order_idx
        ON mcp_managed_local_rollback_generations(retained_at, management_id)
    """,
    """
    CREATE TABLE mcp_managed_local_recovery_attempts (
        request_id TEXT PRIMARY KEY
            CHECK(length(request_id)=32 AND request_id NOT GLOB '*[^0-9a-f]*'),
        request_fingerprint TEXT NOT NULL
            CHECK(length(request_fingerprint)=64 AND
                  request_fingerprint NOT GLOB '*[^0-9a-f]*'),
        management_id TEXT NOT NULL UNIQUE
            REFERENCES mcp_managed_servers(management_id) ON DELETE CASCADE,
        operation_id TEXT NOT NULL UNIQUE
            REFERENCES mcp_managed_local_operations(request_id)
            ON DELETE CASCADE,
        action TEXT NOT NULL CHECK(action IN ('update','rollback','cleanup')),
        preview_digest TEXT NOT NULL
            CHECK(length(preview_digest)=64 AND
                  preview_digest NOT GLOB '*[^0-9a-f]*'),
        expected_revision INTEGER NOT NULL CHECK(expected_revision >= 1),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE TABLE mcp_managed_local_swap_receipts (
        request_id TEXT PRIMARY KEY
            CHECK(length(request_id)=32 AND request_id NOT GLOB '*[^0-9a-f]*'),
        request_fingerprint TEXT NOT NULL
            CHECK(length(request_fingerprint)=64 AND
                  request_fingerprint NOT GLOB '*[^0-9a-f]*'),
        management_id TEXT NOT NULL
            REFERENCES mcp_managed_servers(management_id) ON DELETE CASCADE,
        action TEXT NOT NULL CHECK(action IN (
            'update','rollback','cleanup',
            'recover_update','recover_rollback','recover_cleanup'
        )),
        preview_digest TEXT NOT NULL
            CHECK(length(preview_digest)=64 AND
                  preview_digest NOT GLOB '*[^0-9a-f]*'),
        resulting_revision INTEGER NOT NULL CHECK(resulting_revision >= 2),
        created_at TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE INDEX mcp_managed_local_swap_receipts_server_idx
        ON mcp_managed_local_swap_receipts(
            management_id, resulting_revision DESC, request_id DESC
        )
    """,
)


_SCHEMA_V18 = (
    """
    CREATE TABLE mcp_managed_tool_snapshots (
        snapshot_id TEXT PRIMARY KEY
            CHECK(length(snapshot_id)=32 AND snapshot_id NOT GLOB '*[^0-9a-f]*'),
        management_id TEXT NOT NULL
            REFERENCES mcp_managed_servers(management_id) ON DELETE CASCADE,
        observation_id TEXT NOT NULL
            CHECK(length(observation_id)=32 AND observation_id NOT GLOB '*[^0-9a-f]*'),
        plan_revision TEXT NOT NULL
            CHECK(length(plan_revision)=64 AND plan_revision NOT GLOB '*[^0-9a-f]*'),
        source TEXT NOT NULL CHECK(source IN ('remote_probe','local_package_probe')),
        source_tree_digest TEXT CHECK(
            source_tree_digest IS NULL OR
            (length(source_tree_digest)=64 AND source_tree_digest NOT GLOB '*[^0-9a-f]*')
        ),
        protocol_version TEXT NOT NULL
            CHECK(length(protocol_version)=10 AND protocol_version GLOB '20??-??-??'),
        tool_count INTEGER NOT NULL CHECK(tool_count BETWEEN 0 AND 256),
        schema_digest TEXT NOT NULL
            CHECK(length(schema_digest)=64 AND schema_digest NOT GLOB '*[^0-9a-f]*'),
        reviewed_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(management_id, observation_id),
        UNIQUE(snapshot_id, management_id),
        CHECK(
            (source='remote_probe' AND source_tree_digest IS NULL) OR
            (source='local_package_probe' AND source_tree_digest IS NOT NULL)
        )
    ) STRICT
    """,
    """
    CREATE INDEX mcp_managed_tool_snapshots_server_idx
        ON mcp_managed_tool_snapshots(management_id, reviewed_at DESC, snapshot_id)
    """,
    """
    CREATE TABLE mcp_managed_tools (
        snapshot_id TEXT NOT NULL
            REFERENCES mcp_managed_tool_snapshots(snapshot_id) ON DELETE CASCADE,
        tool_id TEXT NOT NULL
            CHECK(length(tool_id)=32 AND tool_id NOT GLOB '*[^0-9a-f]*'),
        tool_order INTEGER NOT NULL CHECK(tool_order BETWEEN 0 AND 255),
        name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 128),
        title TEXT CHECK(title IS NULL OR length(title) BETWEEN 1 AND 256),
        description TEXT CHECK(
            description IS NULL OR length(description) BETWEEN 1 AND 4096
        ),
        model_alias TEXT NOT NULL CHECK(
            length(model_alias) BETWEEN 1 AND 64 AND
            model_alias GLOB '[A-Za-z0-9_-]*' AND
            model_alias NOT GLOB '*[^A-Za-z0-9_-]*'
        ),
        input_schema_json TEXT NOT NULL
            CHECK(length(input_schema_json) BETWEEN 2 AND 262144),
        input_schema_digest TEXT NOT NULL
            CHECK(length(input_schema_digest)=64 AND input_schema_digest NOT GLOB '*[^0-9a-f]*'),
        model_input_schema_json TEXT NOT NULL
            CHECK(length(model_input_schema_json) BETWEEN 2 AND 262144),
        output_schema_json TEXT CHECK(
            output_schema_json IS NULL OR length(output_schema_json) BETWEEN 2 AND 262144
        ),
        output_schema_digest TEXT CHECK(
            output_schema_digest IS NULL OR
            (length(output_schema_digest)=64 AND output_schema_digest NOT GLOB '*[^0-9a-f]*')
        ),
        contract_digest TEXT NOT NULL
            CHECK(length(contract_digest)=64 AND contract_digest NOT GLOB '*[^0-9a-f]*'),
        PRIMARY KEY(snapshot_id, tool_id),
        UNIQUE(snapshot_id, tool_order),
        UNIQUE(snapshot_id, name),
        UNIQUE(snapshot_id, model_alias),
        CHECK((output_schema_json IS NULL)=(output_schema_digest IS NULL))
    ) STRICT
    """,
    """
    CREATE TABLE mcp_managed_tool_snapshot_state (
        management_id TEXT PRIMARY KEY
            REFERENCES mcp_managed_servers(management_id) ON DELETE CASCADE,
        snapshot_id TEXT,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(snapshot_id, management_id)
            REFERENCES mcp_managed_tool_snapshots(snapshot_id, management_id)
            ON DELETE RESTRICT
    ) STRICT
    """,
    """
    INSERT INTO mcp_managed_tool_snapshot_state(management_id,snapshot_id,updated_at)
    SELECT management_id,NULL,updated_at FROM mcp_managed_servers
    """,
    """
    CREATE TABLE mcp_managed_project_tools (
        management_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        snapshot_id TEXT NOT NULL,
        tool_id TEXT NOT NULL,
        admitted_at TEXT NOT NULL,
        PRIMARY KEY(management_id, project_id, tool_id),
        FOREIGN KEY(management_id, project_id)
            REFERENCES mcp_managed_project_bindings(management_id, project_id)
            ON DELETE CASCADE,
        FOREIGN KEY(snapshot_id, management_id)
            REFERENCES mcp_managed_tool_snapshots(snapshot_id, management_id)
            ON DELETE CASCADE,
        FOREIGN KEY(snapshot_id, tool_id)
            REFERENCES mcp_managed_tools(snapshot_id, tool_id)
            ON DELETE CASCADE
    ) STRICT
    """,
    """
    CREATE INDEX mcp_managed_project_tools_project_idx
        ON mcp_managed_project_tools(project_id, management_id, snapshot_id)
    """,
)


_SCHEMA_V19 = (
    "ALTER TABLE mcp_managed_local_update_payloads "
    "RENAME TO mcp_managed_local_update_payloads_v18",
    """
    CREATE TABLE mcp_managed_local_update_payloads (
        request_id TEXT PRIMARY KEY
            REFERENCES mcp_managed_local_operations(request_id) ON DELETE CASCADE,
        management_id TEXT NOT NULL UNIQUE
            REFERENCES mcp_managed_servers(management_id) ON DELETE CASCADE,
        target_plan_json TEXT NOT NULL
            CHECK(length(target_plan_json) BETWEEN 2 AND 32768),
        target_plan_digest TEXT NOT NULL
            CHECK(length(target_plan_digest)=64 AND
                  target_plan_digest NOT GLOB '*[^0-9a-f]*'),
        target_result_json TEXT CHECK(
            target_result_json IS NULL OR
            length(target_result_json) BETWEEN 2 AND 4194304
        ),
        target_result_digest TEXT CHECK(
            target_result_digest IS NULL OR
            (length(target_result_digest)=64 AND
             target_result_digest NOT GLOB '*[^0-9a-f]*')
        ),
        target_tree_digest TEXT CHECK(
            target_tree_digest IS NULL OR
            (length(target_tree_digest)=64 AND
             target_tree_digest NOT GLOB '*[^0-9a-f]*')
        ),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK(
            (target_result_json IS NULL AND target_result_digest IS NULL
             AND target_tree_digest IS NULL) OR
            (target_result_json IS NOT NULL AND target_result_digest IS NOT NULL
             AND target_tree_digest IS NOT NULL)
        )
    ) STRICT
    """,
    """
    INSERT INTO mcp_managed_local_update_payloads(
        request_id,management_id,target_plan_json,target_plan_digest,
        target_result_json,target_result_digest,target_tree_digest,
        created_at,updated_at
    )
    SELECT request_id,management_id,target_plan_json,target_plan_digest,
           target_result_json,target_result_digest,target_tree_digest,
           created_at,updated_at
    FROM mcp_managed_local_update_payloads_v18
    """,
    "DROP TABLE mcp_managed_local_update_payloads_v18",
)


_SCHEMA_V20 = (
    """
    ALTER TABLE mcp_managed_tool_snapshots
    ADD COLUMN source_manifest_digest TEXT CHECK(
        source_manifest_digest IS NULL OR
        (length(source_manifest_digest)=64 AND
         source_manifest_digest NOT GLOB '*[^0-9a-f]*')
    )
    """,
    """
    UPDATE mcp_managed_tool_snapshots
    SET source_manifest_digest=(
        SELECT package.manifest_digest
        FROM mcp_managed_local_packages package
        WHERE package.management_id=mcp_managed_tool_snapshots.management_id
          AND package.status='installed'
          AND package.tree_digest=mcp_managed_tool_snapshots.source_tree_digest
          AND mcp_managed_tool_snapshots.plan_revision=(
              SELECT server.plan_revision FROM mcp_managed_servers server
              WHERE server.management_id=package.management_id
          )
    )
    WHERE source='local_package_probe'
      AND EXISTS (
        SELECT 1 FROM mcp_managed_local_packages package
        WHERE package.management_id=mcp_managed_tool_snapshots.management_id
          AND package.status='installed'
          AND package.tree_digest=mcp_managed_tool_snapshots.source_tree_digest
          AND mcp_managed_tool_snapshots.plan_revision=(
              SELECT server.plan_revision FROM mcp_managed_servers server
              WHERE server.management_id=package.management_id
          )
      )
    """,
    """
    UPDATE mcp_managed_tool_snapshots
    SET source_manifest_digest=(
        SELECT json_extract(
            generation.generation_json,
            '$.local_package_evidence.manifest_digest'
        )
        FROM mcp_managed_local_rollback_generations generation
        WHERE generation.management_id=mcp_managed_tool_snapshots.management_id
          AND generation.tree_digest=mcp_managed_tool_snapshots.source_tree_digest
          AND generation.plan_revision=mcp_managed_tool_snapshots.plan_revision
    )
    WHERE source='local_package_probe'
      AND source_manifest_digest IS NULL
      AND EXISTS (
        SELECT 1 FROM mcp_managed_local_rollback_generations generation
        WHERE generation.management_id=mcp_managed_tool_snapshots.management_id
          AND generation.tree_digest=mcp_managed_tool_snapshots.source_tree_digest
          AND generation.plan_revision=mcp_managed_tool_snapshots.plan_revision
      )
    """,
)


_SCHEMA_V21 = (
    """
    ALTER TABLE agent_artifacts
    ADD COLUMN archived_at TEXT CHECK(
        archived_at IS NULL OR length(archived_at) BETWEEN 20 AND 40
    )
    """,
    """
    ALTER TABLE agent_artifacts
    ADD COLUMN removed_at TEXT CHECK(
        removed_at IS NULL OR length(removed_at) BETWEEN 20 AND 40
    )
    """,
    """
    CREATE INDEX agent_artifacts_session_lifecycle_idx
        ON agent_artifacts(
            session_id, removed_at, archived_at, updated_at DESC, artifact_id
        )
    """,
    """
    CREATE TRIGGER agent_artifacts_lifecycle_coherent_insert
    BEFORE INSERT ON agent_artifacts
    WHEN (NEW.removed_at IS NOT NULL AND NEW.archived_at IS NULL)
      OR (NEW.archived_at IS NOT NULL AND NEW.archived_at < NEW.created_at)
      OR (NEW.removed_at IS NOT NULL AND NEW.removed_at < NEW.archived_at)
      OR (NEW.archived_at IS NOT NULL AND NEW.updated_at < NEW.archived_at)
      OR (NEW.removed_at IS NOT NULL AND NEW.updated_at < NEW.removed_at)
    BEGIN SELECT RAISE(ABORT, 'agent artifact lifecycle is incoherent'); END
    """,
    """
    CREATE TRIGGER agent_artifacts_lifecycle_coherent_update
    BEFORE UPDATE ON agent_artifacts
    WHEN (NEW.removed_at IS NOT NULL AND NEW.archived_at IS NULL)
      OR (NEW.archived_at IS NOT NULL AND NEW.archived_at < NEW.created_at)
      OR (NEW.removed_at IS NOT NULL AND NEW.removed_at < NEW.archived_at)
      OR (NEW.archived_at IS NOT NULL AND NEW.updated_at < NEW.archived_at)
      OR (NEW.removed_at IS NOT NULL AND NEW.updated_at < NEW.removed_at)
    BEGIN SELECT RAISE(ABORT, 'agent artifact lifecycle is incoherent'); END
    """,
)


_SCHEMA_V22 = (
    "DROP TRIGGER agent_attachment_payload_immutable",
    "DROP INDEX agent_attachments_session_state_idx",
    "DROP INDEX agent_attachments_expiry_idx",
    "ALTER TABLE agent_attachments RENAME TO agent_attachments_v21",
    """
    CREATE TABLE agent_attachments (
        attachment_id TEXT PRIMARY KEY
            CHECK(length(attachment_id)=32 AND attachment_id NOT GLOB '*[^0-9a-f]*'),
        session_id TEXT NOT NULL
            REFERENCES agent_catalog_sessions(session_id) ON DELETE CASCADE,
        model_alias TEXT NOT NULL CHECK(length(model_alias) BETWEEN 1 AND 64),
        capability_probe_version TEXT NOT NULL
            CHECK(length(capability_probe_version) BETWEEN 1 AND 64),
        attachment_kind TEXT NOT NULL
            CHECK(attachment_kind IN ('image','audio','document')),
        media_type TEXT NOT NULL CHECK(media_type IN (
            'image/png','image/jpeg','audio/wav','text/plain','text/markdown',
            'application/json','text/csv','text/tab-separated-values',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'application/vnd.oasis.opendocument.text'
        )),
        display_name TEXT NOT NULL CHECK(length(display_name) BETWEEN 1 AND 120),
        source_kind TEXT NOT NULL
            CHECK(source_kind IN ('file','microphone','external_agent')),
        attachment_state TEXT NOT NULL CHECK(attachment_state IN ('staged','attached')),
        retention_policy TEXT NOT NULL
            CHECK(retention_policy IN ('memory_only','local_history')),
        created_at TEXT NOT NULL,
        expires_at TEXT,
        attached_event_seq INTEGER CHECK(attached_event_seq IS NULL OR attached_event_seq >= 1),
        sha256 TEXT NOT NULL
            CHECK(length(sha256)=64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
        byte_size INTEGER NOT NULL CHECK(byte_size BETWEEN 1 AND 12582912),
        width INTEGER CHECK(width IS NULL OR width BETWEEN 1 AND 8192),
        height INTEGER CHECK(height IS NULL OR height BETWEEN 1 AND 8192),
        duration_ms INTEGER CHECK(duration_ms IS NULL OR duration_ms BETWEEN 1 AND 300000),
        sample_rate_hz INTEGER
            CHECK(sample_rate_hz IS NULL OR sample_rate_hz BETWEEN 8000 AND 48000),
        channels INTEGER CHECK(channels IS NULL OR channels BETWEEN 1 AND 2),
        routing TEXT NOT NULL
            CHECK(routing IN ('native_multimodal','local_text_projection')),
        document_format TEXT CHECK(document_format IS NULL OR document_format IN (
            'plain_text','markdown','json','csv','tsv','docx','pptx','xlsx','odt'
        )),
        projected_characters INTEGER CHECK(
            projected_characters IS NULL OR projected_characters BETWEEN 1 AND 100000
        ),
        projection_truncated INTEGER
            CHECK(projection_truncated IS NULL OR projection_truncated IN (0,1)),
        omitted_features_json TEXT NOT NULL
            CHECK(length(omitted_features_json) BETWEEN 2 AND 128),
        payload BLOB NOT NULL CHECK(length(payload)=byte_size),
        CHECK(
            (attachment_state='staged' AND expires_at IS NOT NULL AND attached_event_seq IS NULL)
            OR
            (attachment_state='attached' AND attached_event_seq IS NOT NULL)
        ),
        CHECK(
            (attachment_kind='image' AND media_type IN ('image/png','image/jpeg')
                AND width IS NOT NULL AND height IS NOT NULL
                AND duration_ms IS NULL AND sample_rate_hz IS NULL AND channels IS NULL
                AND routing='native_multimodal' AND document_format IS NULL
                AND projected_characters IS NULL AND projection_truncated IS NULL
                AND omitted_features_json='[]')
            OR
            (attachment_kind='audio' AND media_type='audio/wav'
                AND width IS NULL AND height IS NULL
                AND duration_ms IS NOT NULL AND sample_rate_hz IS NOT NULL AND channels IS NOT NULL
                AND routing='native_multimodal' AND document_format IS NULL
                AND projected_characters IS NULL AND projection_truncated IS NULL
                AND omitted_features_json='[]')
            OR
            (attachment_kind='document'
                AND width IS NULL AND height IS NULL AND duration_ms IS NULL
                AND sample_rate_hz IS NULL AND channels IS NULL
                AND routing='local_text_projection'
                AND projected_characters IS NOT NULL AND projection_truncated IS NOT NULL
                AND (
                    (document_format='plain_text' AND media_type='text/plain')
                    OR (document_format='markdown' AND media_type='text/markdown')
                    OR (document_format='json' AND media_type='application/json')
                    OR (document_format='csv' AND media_type='text/csv')
                    OR (document_format='tsv' AND media_type='text/tab-separated-values')
                    OR (document_format='docx' AND media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
                    OR (document_format='pptx' AND media_type='application/vnd.openxmlformats-officedocument.presentationml.presentation')
                    OR (document_format='xlsx' AND media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                    OR (document_format='odt' AND media_type='application/vnd.oasis.opendocument.text')
                ))
        ),
        FOREIGN KEY(session_id, attached_event_seq)
            REFERENCES agent_conversation_events(session_id, event_seq) ON DELETE CASCADE
    ) STRICT
    """,
    """
    INSERT INTO agent_attachments(
        attachment_id,session_id,model_alias,capability_probe_version,
        attachment_kind,media_type,display_name,source_kind,attachment_state,
        retention_policy,created_at,expires_at,attached_event_seq,sha256,byte_size,
        width,height,duration_ms,sample_rate_hz,channels,routing,document_format,
        projected_characters,projection_truncated,omitted_features_json,payload
    )
    SELECT
        attachment_id,session_id,model_alias,capability_probe_version,
        attachment_kind,media_type,display_name,source_kind,attachment_state,
        retention_policy,created_at,expires_at,attached_event_seq,sha256,byte_size,
        width,height,duration_ms,sample_rate_hz,channels,'native_multimodal',NULL,
        NULL,NULL,'[]',payload
    FROM agent_attachments_v21
    """,
    "DROP TABLE agent_attachments_v21",
    """
    CREATE INDEX agent_attachments_session_state_idx
        ON agent_attachments(session_id, attachment_state, created_at, attachment_id)
    """,
    """
    CREATE INDEX agent_attachments_expiry_idx
        ON agent_attachments(expires_at)
        WHERE attachment_state='staged'
    """,
    """
    CREATE TRIGGER agent_attachment_payload_immutable
        BEFORE UPDATE ON agent_attachments
        WHEN NEW.payload != OLD.payload
          OR NEW.sha256 != OLD.sha256
          OR NEW.byte_size != OLD.byte_size
          OR NEW.media_type != OLD.media_type
          OR NEW.attachment_kind != OLD.attachment_kind
          OR NEW.routing != OLD.routing
          OR NEW.document_format IS NOT OLD.document_format
          OR NEW.projected_characters IS NOT OLD.projected_characters
          OR NEW.projection_truncated IS NOT OLD.projection_truncated
          OR NEW.omitted_features_json != OLD.omitted_features_json
        BEGIN SELECT RAISE(ABORT, 'agent attachment payload is immutable'); END
    """,
)


_SCHEMA_V23 = (
    """
    ALTER TABLE agent_mcp_connections
    ADD COLUMN scope_project_id TEXT CHECK(
        scope_project_id IS NULL OR
        (length(scope_project_id)=32 AND scope_project_id NOT GLOB '*[^0-9a-f]*')
    )
    """,
    """
    CREATE INDEX agent_mcp_connections_scope_idx
        ON agent_mcp_connections(scope_project_id, revoked_at, expires_at)
    """,
)


_SCHEMA_V24 = (
    """
    CREATE TABLE agent_controller_ownerships (
        session_id TEXT PRIMARY KEY
            REFERENCES agent_catalog_sessions(session_id) ON DELETE CASCADE
            CHECK(length(session_id)=32 AND session_id NOT GLOB '*[^0-9a-f]*'),
        project_id TEXT NOT NULL
            REFERENCES agent_projects(project_id) ON DELETE RESTRICT
            CHECK(length(project_id)=32 AND project_id NOT GLOB '*[^0-9a-f]*'),
        owner_connection_id TEXT NOT NULL
            REFERENCES agent_mcp_connections(connection_id) ON DELETE CASCADE
            CHECK(length(owner_connection_id)=32 AND owner_connection_id NOT GLOB '*[^0-9a-f]*'),
        operation TEXT NOT NULL CHECK(operation IN (
            'turn','write_proposal','transaction_proposal','lifecycle_proposal'
        )),
        state TEXT NOT NULL CHECK(state IN (
            'claimed','running','waiting_native_approval','reconnecting',
            'submission_uncertain','stopping','stop_uncertain',
            'cleanup_unconfirmed','revoked'
        )),
        cursor INTEGER NOT NULL CHECK(cursor >= 0),
        last_seq INTEGER NOT NULL CHECK(last_seq >= 0),
        approval_pending INTEGER NOT NULL CHECK(approval_pending IN (0,1)),
        ownership_started_at TEXT NOT NULL,
        owner_since TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        revision INTEGER NOT NULL CHECK(revision >= 1),
        handoff_target_connection_id TEXT
            REFERENCES agent_mcp_connections(connection_id) ON DELETE RESTRICT
            CHECK(handoff_target_connection_id IS NULL OR
                  (length(handoff_target_connection_id)=32 AND
                   handoff_target_connection_id NOT GLOB '*[^0-9a-f]*')),
        handoff_offered_at TEXT,
        handoff_expires_at TEXT,
        CHECK(cursor <= last_seq),
        CHECK(
            (handoff_target_connection_id IS NULL AND handoff_offered_at IS NULL
             AND handoff_expires_at IS NULL)
            OR
            (handoff_target_connection_id IS NOT NULL AND handoff_offered_at IS NOT NULL
             AND handoff_expires_at IS NOT NULL
             AND handoff_target_connection_id != owner_connection_id)
        ),
        CHECK(state != 'revoked' OR handoff_target_connection_id IS NULL)
    ) STRICT
    """,
    """
    CREATE INDEX agent_controller_ownerships_owner_idx
        ON agent_controller_ownerships(owner_connection_id, updated_at DESC, session_id)
    """,
    """
    CREATE INDEX agent_controller_ownerships_target_idx
        ON agent_controller_ownerships(handoff_target_connection_id, handoff_expires_at)
        WHERE handoff_target_connection_id IS NOT NULL
    """,
)


_SCHEMA_V25 = (
    """
    CREATE TABLE mcp_managed_tool_call_receipts (
        call_id TEXT PRIMARY KEY
            CHECK(length(call_id)=32 AND call_id NOT GLOB '*[^0-9a-f]*'),
        management_id TEXT NOT NULL
            REFERENCES mcp_managed_servers(management_id) ON DELETE CASCADE,
        project_id TEXT NOT NULL
            REFERENCES agent_projects(project_id) ON DELETE CASCADE,
        session_id TEXT NOT NULL
            REFERENCES agent_catalog_sessions(session_id) ON DELETE CASCADE,
        turn_id TEXT NOT NULL
            CHECK(length(turn_id)=32 AND turn_id NOT GLOB '*[^0-9a-f]*'),
        host_instance_id TEXT NOT NULL
            CHECK(length(host_instance_id)=32 AND host_instance_id NOT GLOB '*[^0-9a-f]*'),
        tool_snapshot_id TEXT NOT NULL,
        tool_id TEXT NOT NULL,
        server_revision INTEGER NOT NULL CHECK(server_revision >= 1),
        project_binding_revision INTEGER NOT NULL CHECK(project_binding_revision >= 1),
        argument_digest TEXT NOT NULL
            CHECK(length(argument_digest)=64 AND argument_digest NOT GLOB '*[^0-9a-f]*'),
        argument_bytes INTEGER NOT NULL CHECK(argument_bytes BETWEEN 2 AND 65536),
        approval_state TEXT NOT NULL CHECK(approval_state IN (
            'not_requested','not_required','approved','denied','timed_out',
            'cancelled_before_decision'
        )),
        outcome TEXT NOT NULL CHECK(outcome IN (
            'denied','timed_out','cancelled','succeeded','tool_error','failed'
        )),
        error_code TEXT CHECK(
            error_code IS NULL OR
            (length(error_code) BETWEEN 1 AND 96 AND
             error_code NOT GLOB '*[^a-z0-9_]*')
        ),
        requested_at TEXT NOT NULL,
        completed_at TEXT NOT NULL,
        result_bytes INTEGER NOT NULL CHECK(result_bytes BETWEEN 0 AND 131072),
        result_digest TEXT CHECK(
            result_digest IS NULL OR
            (length(result_digest)=64 AND result_digest NOT GLOB '*[^0-9a-f]*')
        ),
        cleanup_verified INTEGER NOT NULL CHECK(cleanup_verified IN (0,1)),
        arguments_persisted INTEGER NOT NULL DEFAULT 0 CHECK(arguments_persisted=0),
        result_persisted INTEGER NOT NULL DEFAULT 0 CHECK(result_persisted=0),
        credentials_persisted INTEGER NOT NULL DEFAULT 0 CHECK(credentials_persisted=0),
        reusable_approval_persisted INTEGER NOT NULL DEFAULT 0
            CHECK(reusable_approval_persisted=0),
        FOREIGN KEY(tool_snapshot_id, management_id)
            REFERENCES mcp_managed_tool_snapshots(snapshot_id, management_id)
            ON DELETE CASCADE,
        FOREIGN KEY(tool_snapshot_id, tool_id)
            REFERENCES mcp_managed_tools(snapshot_id, tool_id)
            ON DELETE CASCADE,
        CHECK(completed_at >= requested_at),
        CHECK(
            (outcome IN ('succeeded','tool_error') AND approval_state='approved'
             AND result_digest IS NOT NULL AND error_code IS NULL)
            OR
            (outcome='failed' AND approval_state='approved'
             AND error_code IS NOT NULL)
            OR
            (outcome='denied' AND approval_state='denied'
             AND result_bytes=0 AND result_digest IS NULL AND error_code IS NULL)
            OR
            (outcome='timed_out' AND approval_state IN ('approved','timed_out')
             AND result_bytes=0 AND result_digest IS NULL AND error_code IS NULL)
            OR
            (outcome='cancelled' AND approval_state IN ('approved','cancelled_before_decision')
             AND result_bytes=0 AND result_digest IS NULL AND error_code IS NULL)
        )
    ) STRICT
    """,
    """
    CREATE INDEX mcp_managed_tool_call_receipts_session_idx
        ON mcp_managed_tool_call_receipts(
            session_id, completed_at DESC, call_id DESC
        )
    """,
    """
    CREATE INDEX mcp_managed_tool_call_receipts_project_server_idx
        ON mcp_managed_tool_call_receipts(
            project_id, management_id, completed_at DESC, call_id DESC
        )
    """,
)


_SCHEMA_V26 = (
    """
    CREATE TABLE mcp_managed_host_action_receipts (
        receipt_id TEXT PRIMARY KEY
            CHECK(length(receipt_id)=32 AND receipt_id NOT GLOB '*[^0-9a-f]*'),
        request_id TEXT NOT NULL UNIQUE
            CHECK(length(request_id)=32 AND request_id NOT GLOB '*[^0-9a-f]*'),
        management_id TEXT NOT NULL
            REFERENCES mcp_managed_servers(management_id) ON DELETE CASCADE,
        project_id TEXT NOT NULL
            REFERENCES agent_projects(project_id) ON DELETE CASCADE,
        instance_id TEXT CHECK(
            instance_id IS NULL OR
            (length(instance_id)=32 AND instance_id NOT GLOB '*[^0-9a-f]*')
        ),
        app_run_digest TEXT NOT NULL
            CHECK(length(app_run_digest)=64 AND app_run_digest NOT GLOB '*[^0-9a-f]*'),
        binding_digest TEXT NOT NULL
            CHECK(length(binding_digest)=64 AND binding_digest NOT GLOB '*[^0-9a-f]*'),
        execution_kind TEXT NOT NULL CHECK(execution_kind IN (
            'local_native_process','reviewed_remote_connection'
        )),
        action TEXT NOT NULL CHECK(action IN (
            'start','stop','revoke_project','revoke_server','health_revoke','shutdown'
        )),
        outcome TEXT NOT NULL CHECK(outcome IN (
            'ready','stopped','refused','failed','cleanup_required'
        )),
        reason TEXT NOT NULL CHECK(reason IN (
            'owner_start','owner_stop','project_revoked','server_revoked',
            'health_failed','app_shutdown','start_refused','start_failed',
            'cleanup_unconfirmed'
        )),
        requested_at TEXT NOT NULL,
        completed_at TEXT NOT NULL,
        process_started INTEGER NOT NULL CHECK(process_started IN (0,1)),
        cleanup_state TEXT NOT NULL CHECK(cleanup_state IN (
            'not_applicable','pending','verified','unconfirmed'
        )),
        host_ready INTEGER NOT NULL CHECK(host_ready IN (0,1)),
        error_code TEXT CHECK(
            error_code IS NULL OR
            (length(error_code) BETWEEN 1 AND 96 AND
             error_code NOT GLOB '*[^a-z0-9_]*')
        ),
        endpoint_persisted INTEGER NOT NULL DEFAULT 0 CHECK(endpoint_persisted=0),
        credential_persisted INTEGER NOT NULL DEFAULT 0 CHECK(credential_persisted=0),
        command_or_path_persisted INTEGER NOT NULL DEFAULT 0
            CHECK(command_or_path_persisted=0),
        tool_content_persisted INTEGER NOT NULL DEFAULT 0 CHECK(tool_content_persisted=0),
        prompt_or_result_persisted INTEGER NOT NULL DEFAULT 0
            CHECK(prompt_or_result_persisted=0),
        replay_grants_authority INTEGER NOT NULL DEFAULT 0
            CHECK(replay_grants_authority=0),
        CHECK(completed_at >= requested_at),
        CHECK(execution_kind='local_native_process' OR process_started=0),
        CHECK(
            (outcome='ready' AND action='start' AND reason='owner_start'
             AND instance_id IS NOT NULL AND host_ready=1 AND error_code IS NULL
             AND ((execution_kind='local_native_process' AND process_started=1
                   AND cleanup_state='pending')
                  OR
                  (execution_kind='reviewed_remote_connection' AND process_started=0
                   AND cleanup_state='not_applicable')))
            OR
            (outcome='refused' AND action='start' AND reason='start_refused'
             AND instance_id IS NULL AND process_started=0 AND host_ready=0
             AND cleanup_state='not_applicable' AND error_code IS NOT NULL)
            OR
            (outcome='failed' AND action='start' AND reason='start_failed'
             AND host_ready=0 AND error_code IS NOT NULL
             AND ((process_started=1 AND execution_kind='local_native_process'
                   AND cleanup_state='verified')
                  OR (process_started=0 AND cleanup_state='not_applicable')))
            OR
            (outcome='cleanup_required' AND reason='cleanup_unconfirmed'
             AND instance_id IS NOT NULL AND host_ready=0
             AND cleanup_state='unconfirmed' AND error_code IS NOT NULL
             AND ((execution_kind='local_native_process' AND process_started=1)
                  OR (execution_kind='reviewed_remote_connection' AND process_started=0)))
            OR
            (outcome='stopped' AND action IN (
                'stop','revoke_project','revoke_server','health_revoke','shutdown'
             ) AND reason=CASE action
                WHEN 'stop' THEN 'owner_stop'
                WHEN 'revoke_project' THEN 'project_revoked'
                WHEN 'revoke_server' THEN 'server_revoked'
                WHEN 'health_revoke' THEN 'health_failed'
                WHEN 'shutdown' THEN 'app_shutdown'
             END
             AND instance_id IS NOT NULL AND host_ready=0 AND error_code IS NULL
             AND ((process_started=1 AND execution_kind='local_native_process'
                   AND cleanup_state='verified')
                  OR (process_started=0 AND cleanup_state='not_applicable')))
        )
    ) STRICT
    """,
    """
    CREATE INDEX mcp_managed_host_action_receipts_project_idx
        ON mcp_managed_host_action_receipts(
            project_id, completed_at DESC, receipt_id DESC
        )
    """,
    """
    CREATE INDEX mcp_managed_host_action_receipts_server_idx
        ON mcp_managed_host_action_receipts(
            management_id, completed_at DESC, receipt_id DESC
        )
    """,
    """
    CREATE TABLE mcp_managed_host_cleanup_blocks (
        block_id TEXT PRIMARY KEY
            CHECK(length(block_id)=32 AND block_id NOT GLOB '*[^0-9a-f]*'),
        management_id TEXT NOT NULL
            REFERENCES mcp_managed_servers(management_id) ON DELETE CASCADE,
        project_id TEXT NOT NULL
            REFERENCES agent_projects(project_id) ON DELETE CASCADE,
        instance_id TEXT NOT NULL
            CHECK(length(instance_id)=32 AND instance_id NOT GLOB '*[^0-9a-f]*'),
        app_run_digest TEXT NOT NULL
            CHECK(length(app_run_digest)=64 AND app_run_digest NOT GLOB '*[^0-9a-f]*'),
        binding_digest TEXT NOT NULL
            CHECK(length(binding_digest)=64 AND binding_digest NOT GLOB '*[^0-9a-f]*'),
        binding_json TEXT NOT NULL CHECK(length(binding_json) BETWEEN 2 AND 65536),
        reason TEXT NOT NULL CHECK(reason IN (
            'local_process_cleanup_unconfirmed',
            'remote_connection_cleanup_unconfirmed'
        )),
        state TEXT NOT NULL CHECK(state IN ('active','resolved')),
        process_started INTEGER NOT NULL CHECK(process_started IN (0,1)),
        cleanup_verified INTEGER NOT NULL CHECK(cleanup_verified IN (0,1)),
        lifecycle_actions_blocked INTEGER NOT NULL
            CHECK(lifecycle_actions_blocked IN (0,1)),
        recovery_attempts INTEGER NOT NULL CHECK(recovery_attempts BETWEEN 0 AND 100),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        resolved_at TEXT,
        endpoint_persisted INTEGER NOT NULL DEFAULT 0 CHECK(endpoint_persisted=0),
        credential_persisted INTEGER NOT NULL DEFAULT 0 CHECK(credential_persisted=0),
        process_identity_persisted INTEGER NOT NULL DEFAULT 0
            CHECK(process_identity_persisted=0),
        command_or_path_persisted INTEGER NOT NULL DEFAULT 0
            CHECK(command_or_path_persisted=0),
        tool_content_persisted INTEGER NOT NULL DEFAULT 0 CHECK(tool_content_persisted=0),
        CHECK(updated_at >= created_at),
        CHECK(resolved_at IS NULL OR
              (resolved_at >= created_at AND resolved_at <= updated_at)),
        CHECK((reason='local_process_cleanup_unconfirmed')=process_started),
        CHECK(
            (state='active' AND cleanup_verified=0
             AND lifecycle_actions_blocked=1 AND resolved_at IS NULL)
            OR
            (state='resolved' AND cleanup_verified=1
             AND lifecycle_actions_blocked=0 AND resolved_at IS NOT NULL)
        )
    ) STRICT
    """,
    """
    CREATE UNIQUE INDEX mcp_managed_host_cleanup_blocks_active_idx
        ON mcp_managed_host_cleanup_blocks(management_id, project_id)
        WHERE state='active'
    """,
    """
    CREATE INDEX mcp_managed_host_cleanup_blocks_project_idx
        ON mcp_managed_host_cleanup_blocks(
            project_id, state, updated_at DESC, block_id DESC
        )
    """,
)


_SCHEMA_V27 = (
    """
    CREATE TABLE mcp_managed_local_configuration_inspections (
        request_id TEXT PRIMARY KEY
            CHECK(length(request_id)=32 AND request_id NOT GLOB '*[^0-9a-f]*'),
        management_id TEXT NOT NULL
            REFERENCES mcp_managed_servers(management_id) ON DELETE CASCADE,
        request_fingerprint TEXT NOT NULL
            CHECK(length(request_fingerprint)=64 AND
                  request_fingerprint NOT GLOB '*[^0-9a-f]*'),
        preview_digest TEXT NOT NULL
            CHECK(length(preview_digest)=64 AND
                  preview_digest NOT GLOB '*[^0-9a-f]*'),
        plan_revision TEXT NOT NULL
            CHECK(length(plan_revision)=64 AND plan_revision NOT GLOB '*[^0-9a-f]*'),
        artifact_sha256 TEXT NOT NULL
            CHECK(length(artifact_sha256)=64 AND artifact_sha256 NOT GLOB '*[^0-9a-f]*'),
        artifact_bytes INTEGER NOT NULL CHECK(artifact_bytes BETWEEN 1 AND 67108864),
        manifest_digest TEXT NOT NULL
            CHECK(length(manifest_digest)=64 AND manifest_digest NOT GLOB '*[^0-9a-f]*'),
        manifest_version TEXT NOT NULL CHECK(manifest_version IN ('0.3','0.4')),
        configuration_schema_digest TEXT NOT NULL
            CHECK(length(configuration_schema_digest)=64 AND
                  configuration_schema_digest NOT GLOB '*[^0-9a-f]*'),
        requirement_ids_json TEXT NOT NULL
            CHECK(length(requirement_ids_json) BETWEEN 2 AND 1153),
        resulting_revision INTEGER NOT NULL CHECK(resulting_revision >= 2),
        inspected_at TEXT NOT NULL,
        current_state INTEGER NOT NULL DEFAULT 1 CHECK(current_state IN (0,1)),
        archive_retained INTEGER NOT NULL DEFAULT 0 CHECK(archive_retained=0),
        process_started INTEGER NOT NULL DEFAULT 0 CHECK(process_started=0),
        configuration_values_persisted INTEGER NOT NULL DEFAULT 0
            CHECK(configuration_values_persisted=0),
        manifest_content_persisted INTEGER NOT NULL DEFAULT 0
            CHECK(manifest_content_persisted=0)
    ) STRICT
    """,
    """
    CREATE INDEX mcp_managed_local_configuration_inspections_request_idx
        ON mcp_managed_local_configuration_inspections(request_id)
    """,
    """
    CREATE UNIQUE INDEX mcp_managed_local_configuration_inspections_current_idx
        ON mcp_managed_local_configuration_inspections(management_id)
        WHERE current_state=1
    """,
)


_SCHEMA_V28 = (
    """
    CREATE TABLE mcp_managed_tool_call_claims (
        call_id TEXT PRIMARY KEY
            CHECK(length(call_id)=32 AND call_id NOT GLOB '*[^0-9a-f]*'),
        app_run_digest TEXT NOT NULL
            CHECK(length(app_run_digest)=64 AND app_run_digest NOT GLOB '*[^0-9a-f]*'),
        management_id TEXT NOT NULL
            REFERENCES mcp_managed_servers(management_id) ON DELETE CASCADE,
        project_id TEXT NOT NULL
            REFERENCES agent_projects(project_id) ON DELETE CASCADE,
        session_id TEXT NOT NULL
            REFERENCES agent_catalog_sessions(session_id) ON DELETE CASCADE,
        turn_id TEXT NOT NULL
            CHECK(length(turn_id)=32 AND turn_id NOT GLOB '*[^0-9a-f]*'),
        host_instance_id TEXT NOT NULL
            CHECK(length(host_instance_id)=32 AND host_instance_id NOT GLOB '*[^0-9a-f]*'),
        tool_snapshot_id TEXT NOT NULL,
        tool_id TEXT NOT NULL,
        server_revision INTEGER NOT NULL CHECK(server_revision >= 1),
        project_binding_revision INTEGER NOT NULL CHECK(project_binding_revision >= 1),
        argument_digest TEXT NOT NULL
            CHECK(length(argument_digest)=64 AND argument_digest NOT GLOB '*[^0-9a-f]*'),
        argument_bytes INTEGER NOT NULL CHECK(argument_bytes BETWEEN 2 AND 65536),
        approval_digest TEXT NOT NULL
            CHECK(length(approval_digest)=64 AND approval_digest NOT GLOB '*[^0-9a-f]*'),
        approval_state TEXT NOT NULL CHECK(approval_state IN (
            'approved','denied','timed_out','cancelled_before_decision'
        )),
        requested_at TEXT NOT NULL,
        approval_expires_at TEXT NOT NULL,
        claimed_at TEXT NOT NULL,
        arguments_persisted INTEGER NOT NULL DEFAULT 0 CHECK(arguments_persisted=0),
        result_persisted INTEGER NOT NULL DEFAULT 0 CHECK(result_persisted=0),
        approval_identifier_persisted INTEGER NOT NULL DEFAULT 0
            CHECK(approval_identifier_persisted=0),
        replay_grants_authority INTEGER NOT NULL DEFAULT 0
            CHECK(replay_grants_authority=0),
        FOREIGN KEY(tool_snapshot_id, management_id)
            REFERENCES mcp_managed_tool_snapshots(snapshot_id, management_id)
            ON DELETE CASCADE,
        FOREIGN KEY(tool_snapshot_id, tool_id)
            REFERENCES mcp_managed_tools(snapshot_id, tool_id)
            ON DELETE CASCADE,
        CHECK(approval_expires_at > requested_at),
        CHECK(claimed_at >= requested_at)
    ) STRICT
    """,
    """
    CREATE INDEX mcp_managed_tool_call_claims_session_idx
        ON mcp_managed_tool_call_claims(
            session_id, claimed_at DESC, call_id DESC
        )
    """,
    """
    CREATE INDEX mcp_managed_tool_call_claims_project_server_idx
        ON mcp_managed_tool_call_claims(
            project_id, management_id, claimed_at DESC, call_id DESC
        )
    """,
)


_SCHEMA_V29 = (
    """
    CREATE TRIGGER IF NOT EXISTS mcp_managed_tool_call_claims_scope_insert
    BEFORE INSERT ON mcp_managed_tool_call_claims
    FOR EACH ROW
    WHEN NOT EXISTS (
        SELECT 1
        FROM agent_catalog_sessions session
        WHERE session.session_id=NEW.session_id
          AND session.project_id=NEW.project_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'mcp_tool_call_scope_conflict');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS mcp_managed_tool_call_claims_immutable
    BEFORE UPDATE ON mcp_managed_tool_call_claims
    FOR EACH ROW
    BEGIN
        SELECT RAISE(ABORT, 'mcp_tool_call_claim_immutable');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS mcp_managed_tool_call_receipts_claim_insert
    BEFORE INSERT ON mcp_managed_tool_call_receipts
    FOR EACH ROW
    WHEN NOT EXISTS (
        SELECT 1
        FROM mcp_managed_tool_call_claims claim
        WHERE claim.call_id=NEW.call_id
          AND claim.management_id=NEW.management_id
          AND claim.project_id=NEW.project_id
          AND claim.session_id=NEW.session_id
          AND claim.turn_id=NEW.turn_id
          AND claim.host_instance_id=NEW.host_instance_id
          AND claim.tool_snapshot_id=NEW.tool_snapshot_id
          AND claim.tool_id=NEW.tool_id
          AND claim.server_revision=NEW.server_revision
          AND claim.project_binding_revision=NEW.project_binding_revision
          AND claim.argument_digest=NEW.argument_digest
          AND claim.argument_bytes=NEW.argument_bytes
          AND claim.approval_state=NEW.approval_state
          AND claim.requested_at=NEW.requested_at
    )
    BEGIN
        SELECT RAISE(ABORT, 'mcp_tool_call_claim_scope_conflict');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS mcp_managed_tool_call_receipts_immutable
    BEFORE UPDATE ON mcp_managed_tool_call_receipts
    FOR EACH ROW
    BEGIN
        SELECT RAISE(ABORT, 'mcp_tool_call_receipt_immutable');
    END
    """,
)


_SCHEMA_V30 = (
    """
    CREATE TABLE agent_catalog_migration_checksums (
        version INTEGER PRIMARY KEY
            REFERENCES agent_catalog_schema_migrations(version) ON DELETE RESTRICT
            CHECK(version > 0),
        checksum TEXT NOT NULL CHECK(
            length(checksum)=64 AND checksum NOT GLOB '*[^0-9a-f]*'
        )
    ) STRICT
    """,
)

# FTS5 is intentionally maintained by application transactions instead of SQL
# triggers.  Connections run with trusted_schema=OFF, and this keeps a message
# projection, its index row, and the append-only journal in one explicit
# rollback boundary.  The projection contains only owner-admitted visible text.
_SCHEMA_V31 = (
    """
    CREATE TABLE agent_message_search_messages (
        message_id INTEGER PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES agent_catalog_sessions(session_id) ON DELETE CASCADE,
        event_seq INTEGER NOT NULL CHECK(event_seq >= 1),
        role TEXT NOT NULL CHECK(role IN ('user','assistant')),
        text TEXT NOT NULL CHECK(length(text) BETWEEN 1 AND 120000),
        UNIQUE(session_id, event_seq)
    ) STRICT
    """,
    """
    CREATE INDEX agent_message_search_messages_session_idx
    ON agent_message_search_messages(session_id, event_seq)
    """,
    """
    CREATE VIRTUAL TABLE agent_message_search_fts USING fts5(
        text,
        content='agent_message_search_messages',
        content_rowid='message_id',
        tokenize='unicode61 remove_diacritics 0'
    )
    """,
    """
    INSERT INTO agent_message_search_messages(session_id,event_seq,role,text)
    SELECT event.session_id,event.event_seq,
           CASE event_kind WHEN 'user' THEN 'user' ELSE 'assistant' END,
           json_extract(event.payload_json, '$.text')
    FROM agent_conversation_events AS event
    JOIN agent_catalog_sessions AS session ON session.session_id=event.session_id
    WHERE session.retention_policy='local_history'
      AND event.event_kind IN ('user','assistant')
      AND json_type(event.payload_json, '$.text')='text'
      AND length(json_extract(event.payload_json, '$.text')) > 0
    """,
    "INSERT INTO agent_message_search_fts(agent_message_search_fts) VALUES('rebuild')",
)

_AGENT_CATALOG_MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        1,
        tuple(
            statement.strip()
            for statement in _SCHEMA_V1.split(";")
            if statement.strip()
        ),
    ),
    (2, _SCHEMA_V2),
    (3, _SCHEMA_V3),
    (4, _SCHEMA_V4),
    (5, _SCHEMA_V5),
    (6, _SCHEMA_V6),
    (7, _SCHEMA_V7),
    (8, _SCHEMA_V8),
    (9, _SCHEMA_V9),
    (10, _SCHEMA_V10),
    (11, _SCHEMA_V11),
    (12, _SCHEMA_V12),
    (13, _SCHEMA_V13),
    (14, _SCHEMA_V14),
    (15, _SCHEMA_V15),
    (16, _SCHEMA_V16),
    (17, _SCHEMA_V17),
    (18, _SCHEMA_V18),
    (19, _SCHEMA_V19),
    (20, _SCHEMA_V20),
    (21, _SCHEMA_V21),
    (22, _SCHEMA_V22),
    (23, _SCHEMA_V23),
    (24, _SCHEMA_V24),
    (25, _SCHEMA_V25),
    (26, _SCHEMA_V26),
    (27, _SCHEMA_V27),
    (28, _SCHEMA_V28),
    (29, _SCHEMA_V29),
    (30, _SCHEMA_V30),
    (31, _SCHEMA_V31),
)

if tuple(version for version, _statements in _AGENT_CATALOG_MIGRATIONS) != tuple(
    range(1, AGENT_CATALOG_SCHEMA_VERSION + 1)
):
    raise RuntimeError("agent_catalog_migration_registry_invalid")


def _agent_catalog_migration_checksum(statements: tuple[str, ...]) -> str:
    """Hash the canonical statement list without depending on host newlines."""

    canonical = json.dumps(
        tuple(statement.strip() for statement in statements),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


_AGENT_CATALOG_MIGRATION_CHECKSUMS = {
    version: _agent_catalog_migration_checksum(statements)
    for version, statements in _AGENT_CATALOG_MIGRATIONS
}


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _like(value: str) -> str:
    escaped = value.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _catalog_page_snapshot(
    *,
    collection: Literal["projects", "sessions"],
    scope: dict[str, object],
    records: list[dict[str, object]],
) -> str:
    """Bind one bounded ordered metadata result to its exact query scope."""

    payload = json.dumps(
        {
            "contract_version": "agent-catalog-page.v1",
            "collection": collection,
            "scope": scope,
            "records": records,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class AgentCatalogSqliteDatabase:
    """Fixed-name, symlink-refusing Agent catalog database."""

    def __init__(self, path: Path) -> None:
        self.path = lexical_absolute_path(path)
        self._initialize_lock = threading.Lock()
        self._initialized = False

    @classmethod
    def under(cls, app_home: Path) -> "AgentCatalogSqliteDatabase":
        return cls(lexical_absolute_path(app_home) / AGENT_CATALOG_DATABASE_FILENAME)

    def _validated_path(self) -> Path:
        candidate = lexical_absolute_path(self.path)
        if candidate.name != AGENT_CATALOG_DATABASE_FILENAME:
            raise AgentCatalogError("agent_catalog_path_invalid")
        if path_has_symlink_component(candidate.parent) or path_has_symlink_component(candidate):
            raise AgentCatalogError("agent_catalog_path_unsafe")
        return candidate

    @staticmethod
    def _migration_table_exists(
        connection: sqlite3.Connection,
        table: str,
    ) -> bool:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone() is not None

    @classmethod
    def _validate_migration_state(
        cls,
        connection: sqlite3.Connection,
        *,
        database_version: int,
    ) -> int:
        rows = connection.execute(
            "SELECT version FROM agent_catalog_schema_migrations ORDER BY version"
        ).fetchall()
        versions = tuple(int(row[0]) for row in rows)
        current = versions[-1] if versions else 0
        if current > AGENT_CATALOG_SCHEMA_VERSION:
            raise AgentCatalogError("agent_catalog_schema_newer")
        if versions != tuple(range(1, current + 1)):
            raise AgentCatalogError("agent_catalog_migration_history_incomplete")
        if database_version != current:
            raise AgentCatalogError("agent_catalog_schema_version_mismatch")

        checksum_table_exists = cls._migration_table_exists(
            connection,
            "agent_catalog_migration_checksums",
        )
        if current == 0:
            application_table = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type='table'
                  AND name != 'agent_catalog_schema_migrations'
                  AND (name LIKE 'agent_%' OR name LIKE 'mcp_managed_%')
                LIMIT 1
                """
            ).fetchone()
            if checksum_table_exists or application_table is not None:
                raise AgentCatalogError("agent_catalog_migration_history_incomplete")
            return current

        if current < 30:
            if checksum_table_exists:
                raise AgentCatalogError("agent_catalog_migration_history_incomplete")
            return current
        if not checksum_table_exists:
            raise AgentCatalogError("agent_catalog_migration_checksum_mismatch")

        checksum_rows = connection.execute(
            """
            SELECT version, checksum
            FROM agent_catalog_migration_checksums
            ORDER BY version
            """
        ).fetchall()
        observed = {int(row[0]): str(row[1]) for row in checksum_rows}
        expected = {
            version: _AGENT_CATALOG_MIGRATION_CHECKSUMS[version]
            for version in range(1, current + 1)
        }
        if observed != expected:
            raise AgentCatalogError("agent_catalog_migration_checksum_mismatch")
        return current

    def initialize(self) -> int:
        path = self._validated_path()
        with self._initialize_lock:
            if self._initialized:
                return AGENT_CATALOG_SCHEMA_VERSION
            try:
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            except OSError:
                raise AgentCatalogError("agent_catalog_storage_unavailable") from None
            if path_has_symlink_component(path.parent) or path_has_symlink_component(path):
                raise AgentCatalogError("agent_catalog_path_unsafe")
            try:
                connection = sqlite3.connect(path, isolation_level=None, timeout=5.0)
                try:
                    connection.execute("PRAGMA busy_timeout = 5000")
                    connection.execute("PRAGMA foreign_keys = ON")
                    connection.execute("PRAGMA trusted_schema = OFF")
                    connection.execute("PRAGMA journal_mode = WAL")
                    connection.execute("PRAGMA synchronous = FULL")
                    connection.execute("BEGIN IMMEDIATE")
                    database_version = int(
                        connection.execute("PRAGMA user_version").fetchone()[0]
                    )
                    if database_version > AGENT_CATALOG_SCHEMA_VERSION:
                        raise AgentCatalogError("agent_catalog_schema_newer")
                    migration_table_exists = self._migration_table_exists(
                        connection,
                        "agent_catalog_schema_migrations",
                    )
                    if not migration_table_exists and database_version != 0:
                        raise AgentCatalogError("agent_catalog_schema_version_mismatch")
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS agent_catalog_schema_migrations (
                            version INTEGER PRIMARY KEY CHECK(version > 0),
                            applied_at TEXT NOT NULL
                        ) STRICT
                        """
                    )
                    current = self._validate_migration_state(
                        connection,
                        database_version=database_version,
                    )
                    for version, statements in _AGENT_CATALOG_MIGRATIONS:
                        if version <= current:
                            continue
                        for statement in statements:
                            connection.execute(statement)
                        connection.execute(
                            """
                            INSERT INTO agent_catalog_schema_migrations(
                                version, applied_at
                            ) VALUES (?, ?)
                            """,
                            (version, _iso(datetime.now(UTC))),
                        )
                        if version == 30:
                            connection.executemany(
                                """
                                INSERT INTO agent_catalog_migration_checksums(
                                    version, checksum
                                ) VALUES (?, ?)
                                """,
                                tuple(
                                    (
                                        migration_version,
                                        _AGENT_CATALOG_MIGRATION_CHECKSUMS[
                                            migration_version
                                        ],
                                    )
                                    for migration_version in range(1, version + 1)
                                ),
                            )
                        elif version > 30:
                            connection.execute(
                                """
                                INSERT INTO agent_catalog_migration_checksums(
                                    version, checksum
                                ) VALUES (?, ?)
                                """,
                                (
                                    version,
                                    _AGENT_CATALOG_MIGRATION_CHECKSUMS[version],
                                ),
                            )
                        current = version
                    connection.execute(
                        f"PRAGMA user_version = {AGENT_CATALOG_SCHEMA_VERSION}"
                    )
                    self._validate_migration_state(
                        connection,
                        database_version=AGENT_CATALOG_SCHEMA_VERSION,
                    )
                    connection.execute("COMMIT")
                except Exception:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                    raise
                finally:
                    connection.close()
            except AgentCatalogError:
                raise
            except (OSError, sqlite3.Error):
                raise AgentCatalogError("agent_catalog_storage_unavailable") from None
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            if path_has_symlink_component(path):
                raise AgentCatalogError("agent_catalog_path_unsafe")
            self._initialized = True
            return AGENT_CATALOG_SCHEMA_VERSION

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.initialize()
        path = self._validated_path()
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                path,
                isolation_level=None,
                check_same_thread=False,
                timeout=5.0,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.execute("PRAGMA synchronous = FULL")
            yield connection
        except AgentCatalogError:
            raise
        except sqlite3.Error:
            raise AgentCatalogError("agent_catalog_storage_unavailable") from None
        finally:
            if connection is not None:
                connection.close()


class SqliteAgentCatalogRepository:
    def __init__(self, database: AgentCatalogSqliteDatabase) -> None:
        self._database = database
        self._write_lock = threading.RLock()
        self._database.initialize()

    @staticmethod
    def _index_visible_message(
        connection: sqlite3.Connection,
        *,
        session_id: str,
        event: StoredAgentEvent,
    ) -> None:
        """Project only admitted user/assistant visible text into FTS5."""
        if event.kind not in {"user", "assistant"} or not event.text:
            return
        role = "user" if event.kind == "user" else "assistant"
        cursor = connection.execute(
            """INSERT INTO agent_message_search_messages(session_id,event_seq,role,text)
               VALUES(?,?,?,?)""",
            (session_id, event.seq, role, event.text),
        )
        message_id = int(cursor.lastrowid)
        connection.execute(
            "INSERT INTO agent_message_search_fts(rowid,text) VALUES(?,?)",
            (message_id, event.text),
        )

    @staticmethod
    def _delete_visible_messages(
        connection: sqlite3.Connection, *, session_id: str
    ) -> None:
        rows = connection.execute(
            "SELECT message_id,text FROM agent_message_search_messages WHERE session_id=?",
            (session_id,),
        )
        for row in rows:
            connection.execute(
                """INSERT INTO agent_message_search_fts(agent_message_search_fts,rowid,text)
                   VALUES('delete',?,?)""",
                (int(row["message_id"]), str(row["text"])),
            )
        connection.execute(
            "DELETE FROM agent_message_search_messages WHERE session_id=?", (session_id,)
        )

    @staticmethod
    def _message_search_phrase(query: str) -> str:
        # A quoted single phrase prevents FTS operators/column selectors from
        # becoming grammar. SQLite binds it separately from the SQL statement.
        return '"' + query.replace('"', '""') + '"'

    @staticmethod
    def _message_excerpt(value: str, open_marker: str, close_marker: str) -> str:
        start = value.find(open_marker)
        end = value.find(close_marker, start + len(open_marker))
        if start < 0 or end < 0:
            raise AgentCatalogError("agent_message_search_corrupt")
        plain = value.replace(open_marker, "").replace(close_marker, "")
        match_start = start
        match_end = end - len(open_marker)
        left = max(0, match_start - 96)
        right = min(len(plain), max(match_end + 120, left + 1))
        if right - left > 240:
            right = left + 240
        excerpt = plain[left:right]
        if left:
            excerpt = "…" + excerpt[1:]
        if right < len(plain) and len(excerpt) >= 2:
            excerpt = excerpt[:-1] + "…"
        if not excerpt:
            raise AgentCatalogError("agent_message_search_corrupt")
        return excerpt

    @staticmethod
    def _project(connection: sqlite3.Connection, project_id: str) -> AgentProjectRecord | None:
        row = connection.execute(
            """
            SELECT project.project_id, project.name, project.created_at,
                   project.updated_at, project.revision, project.pinned,
                   project.archived_at, project.is_default,
                   COUNT(session.session_id) AS session_count
            FROM agent_projects project
            LEFT JOIN agent_catalog_sessions session
              ON session.project_id=project.project_id
            WHERE project.project_id=?
            GROUP BY project.project_id
            """,
            (project_id,),
        ).fetchone()
        return None if row is None else SqliteAgentCatalogRepository._project_record(row)

    @staticmethod
    def _project_record(row: sqlite3.Row) -> AgentProjectRecord:
        return AgentProjectRecord(
            project_id=str(row["project_id"]),
            name=str(row["name"]),
            created_at=_time(str(row["created_at"])),
            updated_at=_time(str(row["updated_at"])),
            revision=int(row["revision"]),
            pinned=bool(row["pinned"]),
            archived_at=None if row["archived_at"] is None else _time(str(row["archived_at"])),
            session_count=int(row["session_count"]),
            is_default=bool(row["is_default"]),
        )

    @staticmethod
    def _session_record(row: sqlite3.Row) -> AgentCatalogSessionRecord:
        retention_policy = AgentRetentionPolicy(str(row["retention_policy"]))
        lineage = (
            None
            if row["lineage_session_id"] is None
            else AgentSessionLineage(
                source_project_id=str(row["lineage_source_project_id"]),
                source_session_id=str(row["lineage_source_session_id"]),
                source_catalog_revision=int(row["lineage_source_catalog_revision"]),
                source_history_revision=int(row["lineage_source_history_revision"]),
                branch_event_seq=int(row["lineage_branch_event_seq"]),
                copied_event_count=int(row["lineage_copied_event_count"]),
                copied_turn_count=int(row["lineage_copied_turn_count"]),
                copied_attachment_count=int(row["lineage_copied_attachment_count"]),
                created_at=_time(str(row["lineage_created_at"])),
            )
        )
        return AgentCatalogSessionRecord(
            session_id=str(row["session_id"]),
            project_id=str(row["project_id"]),
            title=str(row["title"]),
            workspace=str(row["workspace"]),
            model_alias=None if row["model_alias"] is None else str(row["model_alias"]),
            created_at=_time(str(row["created_at"])),
            updated_at=_time(str(row["updated_at"])),
            last_opened_at=_time(str(row["last_opened_at"])),
            revision=int(row["revision"]),
            pinned=bool(row["pinned"]),
            archived_at=None if row["archived_at"] is None else _time(str(row["archived_at"])),
            history_state=(
                AgentHistoryState.DURABLE_LOCAL
                if retention_policy is AgentRetentionPolicy.LOCAL_HISTORY
                else AgentHistoryState.MEMORY_ONLY
            ),
            retention_policy=retention_policy,
            history_revision=int(row["history_revision"]),
            last_event_seq=int(row["last_event_seq"]),
            turn_count=int(row["turn_count"]),
            lineage=lineage,
        )

    @staticmethod
    def _session_select() -> str:
        return """
            SELECT session.*,
                   lineage.session_id AS lineage_session_id,
                   lineage.source_project_id AS lineage_source_project_id,
                   lineage.source_session_id AS lineage_source_session_id,
                   lineage.source_catalog_revision AS lineage_source_catalog_revision,
                   lineage.source_history_revision AS lineage_source_history_revision,
                   lineage.branch_event_seq AS lineage_branch_event_seq,
                   lineage.copied_event_count AS lineage_copied_event_count,
                   lineage.copied_turn_count AS lineage_copied_turn_count,
                   lineage.copied_attachment_count AS lineage_copied_attachment_count,
                   lineage.created_at AS lineage_created_at
            FROM agent_catalog_sessions session
            LEFT JOIN agent_session_lineage lineage ON lineage.session_id=session.session_id
        """

    @staticmethod
    def _touch_projects(
        connection: sqlite3.Connection,
        project_ids: set[str],
        changed_at: datetime,
    ) -> None:
        timestamp = _iso(changed_at)
        for project_id in sorted(project_ids):
            connection.execute(
                "UPDATE agent_projects SET updated_at=?, revision=revision+1 WHERE project_id=?",
                (timestamp, project_id),
            )

    def create_project(
        self,
        *,
        project_id: str,
        name: str,
        created_at: datetime,
        is_default: bool = False,
    ) -> AgentProjectRecord:
        with self._write_lock, self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            count = int(connection.execute("SELECT COUNT(*) FROM agent_projects").fetchone()[0])
            if count >= MAX_AGENT_PROJECTS:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("too_many_agent_projects")
            try:
                connection.execute(
                    """
                    INSERT INTO agent_projects(
                        project_id,name,created_at,updated_at,revision,pinned,archived_at,is_default
                    ) VALUES(?,?,?,?,1,0,NULL,?)
                    """,
                    (project_id, name, _iso(created_at), _iso(created_at), int(is_default)),
                )
                connection.execute("COMMIT")
            except sqlite3.IntegrityError:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_project_conflict") from None
            project = self._project(connection, project_id)
            assert project is not None
            return project

    def get_or_create_default_project(
        self,
        *,
        project_id: str,
        name: str,
        created_at: datetime,
    ) -> AgentProjectRecord:
        with self._write_lock, self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT project_id FROM agent_projects WHERE is_default=1"
            ).fetchone()
            if row is None:
                count = int(connection.execute("SELECT COUNT(*) FROM agent_projects").fetchone()[0])
                if count >= MAX_AGENT_PROJECTS:
                    connection.execute("ROLLBACK")
                    raise AgentCatalogError("too_many_agent_projects")
                connection.execute(
                    """
                    INSERT INTO agent_projects(
                        project_id,name,created_at,updated_at,revision,pinned,archived_at,is_default
                    ) VALUES(?,?,?,?,1,0,NULL,1)
                    """,
                    (project_id, name, _iso(created_at), _iso(created_at)),
                )
                selected = project_id
            else:
                selected = str(row["project_id"])
            connection.execute("COMMIT")
            project = self._project(connection, selected)
            assert project is not None
            return project

    def get_project(self, project_id: str) -> AgentProjectRecord | None:
        with self._database.connect() as connection:
            return self._project(connection, project_id)

    def list_projects(
        self,
        *,
        search: str | None,
        include_archived: bool,
        limit: int,
    ) -> tuple[AgentProjectRecord, ...]:
        clauses: list[str] = []
        values: list[object] = []
        if not include_archived:
            clauses.append("project.archived_at IS NULL")
        if search:
            session_archive_filter = (
                "" if include_archived else "AND matched.archived_at IS NULL"
            )
            clauses.append(
                "("
                "lower(project.name) LIKE ? ESCAPE '\\' "
                "OR EXISTS ("
                "SELECT 1 FROM agent_catalog_sessions matched "
                "WHERE matched.project_id=project.project_id "
                f"{session_archive_filter} "
                "AND lower(matched.title) LIKE ? ESCAPE '\\'"
                ")"
                ")"
            )
            escaped = _like(search)
            values.extend((escaped, escaped))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(limit)
        with self._database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT project.project_id, project.name, project.created_at,
                       project.updated_at, project.revision, project.pinned,
                       project.archived_at, project.is_default,
                       COUNT(session.session_id) AS session_count
                FROM agent_projects project
                LEFT JOIN agent_catalog_sessions session
                  ON session.project_id=project.project_id
                {where}
                GROUP BY project.project_id
                ORDER BY project.pinned DESC,
                         CASE WHEN project.archived_at IS NULL THEN 0 ELSE 1 END,
                         project.updated_at DESC, project.project_id
                LIMIT ?
                """,
                tuple(values),
            ).fetchall()
            return tuple(self._project_record(row) for row in rows)

    def page_projects(
        self,
        *,
        search: str | None,
        include_archived: bool,
        limit: int,
        offset: int,
        snapshot: str | None,
    ) -> tuple[tuple[AgentProjectRecord, ...], int, str]:
        if limit < 1 or limit > MAX_AGENT_CATALOG_PAGE_SIZE:
            raise AgentCatalogError("agent_catalog_page_invalid")
        if offset < 0 or offset > MAX_AGENT_PROJECTS:
            raise AgentCatalogError("agent_catalog_page_out_of_range")
        if offset > 0 and snapshot is None:
            raise AgentCatalogError("agent_catalog_page_snapshot_required")
        clauses: list[str] = []
        values: list[object] = []
        if not include_archived:
            clauses.append("project.archived_at IS NULL")
        if search:
            session_archive_filter = (
                "" if include_archived else "AND matched.archived_at IS NULL"
            )
            clauses.append(
                "("
                "lower(project.name) LIKE ? ESCAPE '\\' "
                "OR EXISTS ("
                "SELECT 1 FROM agent_catalog_sessions matched "
                "WHERE matched.project_id=project.project_id "
                f"{session_archive_filter} "
                "AND lower(matched.title) LIKE ? ESCAPE '\\'"
                ")"
                ")"
            )
            escaped = _like(search)
            values.extend((escaped, escaped))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._database.connect() as connection:
            connection.execute("BEGIN")
            try:
                rows = connection.execute(
                    f"""
                    SELECT project.project_id, project.name, project.created_at,
                           project.updated_at, project.revision, project.pinned,
                           project.archived_at, project.is_default,
                           COUNT(session.session_id) AS session_count
                    FROM agent_projects project
                    LEFT JOIN agent_catalog_sessions session
                      ON session.project_id=project.project_id
                    {where}
                    GROUP BY project.project_id
                    ORDER BY project.pinned DESC,
                             CASE WHEN project.archived_at IS NULL THEN 0 ELSE 1 END,
                             project.updated_at DESC, project.project_id
                    """,
                    tuple(values),
                ).fetchall()
                records = tuple(self._project_record(row) for row in rows)
                current_snapshot = _catalog_page_snapshot(
                    collection="projects",
                    scope={
                        "include_archived": include_archived,
                        "search": search,
                    },
                    records=[
                        record.model_dump(mode="json") for record in records
                    ],
                )
                if snapshot is not None and snapshot != current_snapshot:
                    raise AgentCatalogError("agent_catalog_page_snapshot_conflict")
                if offset > len(records):
                    raise AgentCatalogError("agent_catalog_page_out_of_range")
                page = records[offset : offset + limit]
                connection.execute("COMMIT")
                return page, len(records), current_snapshot
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def update_project(
        self,
        project_id: str,
        command: UpdateAgentProject,
        changed_at: datetime,
    ) -> AgentProjectRecord:
        assignments = ["updated_at=?", "revision=revision+1"]
        values: list[object] = [_iso(changed_at)]
        if command.name is not None:
            assignments.append("name=?")
            values.append(command.name)
        if command.pinned is not None:
            assignments.append("pinned=?")
            values.append(int(command.pinned))
        if command.archived is not None:
            assignments.append("archived_at=?")
            values.append(_iso(changed_at) if command.archived else None)
        values.extend((project_id, command.expected_revision))
        with self._write_lock, self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT revision,is_default FROM agent_projects WHERE project_id=?",
                (project_id,),
            ).fetchone()
            if current is None:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_project_not_found")
            if int(current["revision"]) != command.expected_revision:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_project_revision_conflict")
            if command.archived is True and bool(current["is_default"]):
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_default_project_protected")
            cursor = connection.execute(
                f"UPDATE agent_projects SET {', '.join(assignments)} WHERE project_id=? AND revision=?",
                tuple(values),
            )
            if cursor.rowcount != 1:
                exists = connection.execute(
                    "SELECT 1 FROM agent_projects WHERE project_id=?", (project_id,)
                ).fetchone()
                connection.execute("ROLLBACK")
                raise AgentCatalogError(
                    "agent_project_revision_conflict" if exists else "agent_project_not_found"
                )
            connection.execute("COMMIT")
            project = self._project(connection, project_id)
            assert project is not None
            return project

    def delete_project(self, project_id: str, expected_revision: int) -> None:
        with self._write_lock, self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            project = connection.execute(
                "SELECT is_default, revision FROM agent_projects WHERE project_id=?",
                (project_id,),
            ).fetchone()
            if project is None:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_project_not_found")
            if int(project["revision"]) != expected_revision:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_project_revision_conflict")
            if bool(project["is_default"]):
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_default_project_protected")
            count = int(connection.execute(
                "SELECT COUNT(*) FROM agent_catalog_sessions WHERE project_id=?", (project_id,)
            ).fetchone()[0])
            if count:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_project_not_empty")
            cursor = connection.execute(
                "DELETE FROM agent_projects WHERE project_id=? AND revision=?",
                (project_id, expected_revision),
            )
            if cursor.rowcount != 1:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_project_revision_conflict")
            connection.execute("COMMIT")

    def create_session(
        self,
        *,
        session_id: str,
        project_id: str,
        title: str,
        workspace: str,
        model_alias: str | None,
        retention_policy: AgentRetentionPolicy,
        profile_json: str | None,
        created_at: datetime,
    ) -> AgentCatalogSessionRecord:
        with self._write_lock, self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            project = connection.execute(
                "SELECT archived_at FROM agent_projects WHERE project_id=?", (project_id,)
            ).fetchone()
            if project is None:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_project_not_found")
            if project["archived_at"] is not None:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_project_archived")
            count = int(connection.execute("SELECT COUNT(*) FROM agent_catalog_sessions").fetchone()[0])
            if count >= MAX_AGENT_CATALOG_SESSIONS:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("too_many_agent_catalog_sessions")
            try:
                timestamp = _iso(created_at)
                connection.execute(
                    """
                    INSERT INTO agent_catalog_sessions(
                        session_id,project_id,title,workspace,model_alias,
                        created_at,updated_at,last_opened_at,revision,pinned,
                        archived_at,history_state,retention_policy,history_revision,
                        last_event_seq,turn_count,history_profile_json
                    ) VALUES(?,?,?,?,?,?,?,?,1,0,NULL,'memory_only',?,0,0,0,?)
                    """,
                    (
                        session_id,
                        project_id,
                        title,
                        workspace,
                        model_alias,
                        timestamp,
                        timestamp,
                        timestamp,
                        retention_policy.value,
                        profile_json,
                    ),
                )
                self._touch_projects(connection, {project_id}, created_at)
                connection.execute("COMMIT")
            except sqlite3.IntegrityError:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_catalog_session_conflict") from None
            session = self._get_session(connection, session_id)
            assert session is not None
            return session

    @staticmethod
    def _get_session(connection: sqlite3.Connection, session_id: str) -> AgentCatalogSessionRecord | None:
        row = connection.execute(
            SqliteAgentCatalogRepository._session_select()
            + " WHERE session.session_id=?",
            (session_id,),
        ).fetchone()
        return None if row is None else SqliteAgentCatalogRepository._session_record(row)

    def get_session(self, session_id: str) -> AgentCatalogSessionRecord | None:
        with self._database.connect() as connection:
            return self._get_session(connection, session_id)

    @staticmethod
    def _fork_title(source_title: str, requested_title: str | None) -> str:
        if requested_title is not None:
            return requested_title
        suffix = " (branch)"
        return source_title[: 120 - len(suffix)].rstrip() + suffix

    @staticmethod
    def _fork_attachment_id(new_session_id: str, source_attachment_id: str) -> str:
        return hashlib.sha256(
            f"agent-fork:{new_session_id}:{source_attachment_id}".encode("ascii")
        ).hexdigest()[:32]

    @staticmethod
    def _fork_receipt(
        connection: sqlite3.Connection,
        request_id: str,
        *,
        idempotent_replay: bool,
    ) -> AgentSessionForkReceipt:
        row = connection.execute(
            "SELECT * FROM agent_session_lineage WHERE fork_request_id=?",
            (request_id,),
        ).fetchone()
        if row is None:
            raise AgentCatalogError("agent_history_corrupt")
        session = SqliteAgentCatalogRepository._get_session(
            connection,
            str(row["session_id"]),
        )
        if session is None:
            raise AgentCatalogError("agent_history_corrupt")
        return AgentSessionForkReceipt(
            request_id=request_id,
            idempotent_replay=idempotent_replay,
            session=session,
            source_tail_omitted=bool(row["source_tail_omitted"]),
        )

    @staticmethod
    def _fork_request_matches(
        row: sqlite3.Row,
        *,
        source_project_id: str,
        source_session_id: str,
        command: ForkAgentSession,
    ) -> bool:
        return (
            str(row["source_project_id"]) == source_project_id
            and str(row["source_session_id"]) == source_session_id
            and int(row["source_catalog_revision"])
            == command.expected_catalog_revision
            and int(row["source_history_revision"])
            == command.expected_history_revision
            and (
                None
                if row["requested_destination_project_id"] is None
                else str(row["requested_destination_project_id"])
            )
            == command.destination_project_id
            and (
                None
                if row["requested_through_event_seq"] is None
                else int(row["requested_through_event_seq"])
            )
            == command.through_event_seq
            and (
                None
                if row["requested_title"] is None
                else str(row["requested_title"])
            )
            == command.title
        )

    def fork_session(
        self,
        *,
        source_project_id: str,
        source_session_id: str,
        new_session_id: str,
        command: ForkAgentSession,
        created_at: datetime,
    ) -> AgentSessionForkReceipt:
        """Atomically copy one settled retained prefix into a new inert chat."""

        with self._write_lock, self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM agent_session_lineage WHERE fork_request_id=?",
                (command.request_id,),
            ).fetchone()
            if existing is not None:
                if not self._fork_request_matches(
                    existing,
                    source_project_id=source_project_id,
                    source_session_id=source_session_id,
                    command=command,
                ):
                    connection.execute("ROLLBACK")
                    raise AgentCatalogError("agent_session_fork_request_conflict")
                receipt = self._fork_receipt(
                    connection,
                    command.request_id,
                    idempotent_replay=True,
                )
                connection.execute("COMMIT")
                return receipt

            source = connection.execute(
                "SELECT * FROM agent_catalog_sessions WHERE session_id=?",
                (source_session_id,),
            ).fetchone()
            if source is None or str(source["project_id"]) != source_project_id:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_catalog_session_not_found")
            if int(source["revision"]) != command.expected_catalog_revision:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_catalog_session_revision_conflict")
            if str(source["retention_policy"]) != AgentRetentionPolicy.LOCAL_HISTORY.value:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_history_not_retained")
            if int(source["history_revision"]) != command.expected_history_revision:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_history_revision_conflict")

            destination_project_id = command.destination_project_id or source_project_id
            destination = connection.execute(
                "SELECT archived_at FROM agent_projects WHERE project_id=?",
                (destination_project_id,),
            ).fetchone()
            if destination is None:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_project_not_found")
            if destination["archived_at"] is not None:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_project_archived")
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM agent_catalog_sessions"
                ).fetchone()[0]
            )
            if count >= MAX_AGENT_CATALOG_SESSIONS:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("too_many_agent_catalog_sessions")

            if command.through_event_seq is None:
                settled = connection.execute(
                    """
                    SELECT MAX(event_seq) FROM agent_conversation_events
                    WHERE session_id=? AND event_kind='done'
                    """,
                    (source_session_id,),
                ).fetchone()[0]
                branch_event_seq = 0 if settled is None else int(settled)
            else:
                branch_event_seq = command.through_event_seq
                if branch_event_seq > 0:
                    point = connection.execute(
                        """
                        SELECT event_kind FROM agent_conversation_events
                        WHERE session_id=? AND event_seq=?
                        """,
                        (source_session_id, branch_event_seq),
                    ).fetchone()
                    if point is None or str(point["event_kind"]) != "done":
                        connection.execute("ROLLBACK")
                        raise AgentCatalogError("agent_session_fork_point_invalid")

            source_rows = connection.execute(
                """
                SELECT event_seq,event_at,event_kind,turn_id,payload_json
                FROM agent_conversation_events
                WHERE session_id=? AND event_seq<=?
                ORDER BY event_seq ASC
                """,
                (source_session_id, branch_event_seq),
            ).fetchall()
            try:
                events = tuple(
                    StoredAgentEvent.model_validate_json(str(row["payload_json"]))
                    for row in source_rows
                )
            except (TypeError, ValueError):
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_history_corrupt") from None
            for event, row in zip(events, source_rows, strict=True):
                if (
                    event.seq != int(row["event_seq"])
                    or event.kind != str(row["event_kind"])
                    or event.turn_id
                    != (None if row["turn_id"] is None else str(row["turn_id"]))
                    or _iso(event.at) != str(row["event_at"])
                ):
                    connection.execute("ROLLBACK")
                    raise AgentCatalogError("agent_history_corrupt")

            message_attachment_sequence = tuple(
                (event.seq, attachment)
                for event in events
                for attachment in event.attachments
            )
            if len(message_attachment_sequence) != len(
                {
                    attachment.attachment_id
                    for _, attachment in message_attachment_sequence
                }
            ):
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_history_corrupt")
            message_attachments = {
                attachment.attachment_id: attachment
                for _, attachment in message_attachment_sequence
            }
            attachment_event_sequences = {
                attachment.attachment_id: event_seq
                for event_seq, attachment in message_attachment_sequence
            }
            attachment_rows = connection.execute(
                """
                SELECT * FROM agent_attachments
                WHERE session_id=? AND attachment_state='attached'
                  AND attached_event_seq<=?
                ORDER BY attachment_id
                """,
                (source_session_id, branch_event_seq),
            ).fetchall()
            if {str(row["attachment_id"]) for row in attachment_rows} != set(
                message_attachments
            ):
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_history_corrupt")
            for row in attachment_rows:
                metadata = message_attachments[str(row["attachment_id"])]
                payload = bytes(row["payload"])
                if (
                    str(row["retention_policy"]) != "local_history"
                    or row["expires_at"] is not None
                    or row["attached_event_seq"] is None
                    or int(row["attached_event_seq"])
                    != attachment_event_sequences[metadata.attachment_id]
                    or str(row["attachment_kind"]) != metadata.kind
                    or str(row["media_type"]) != metadata.media_type
                    or str(row["display_name"]) != metadata.display_name
                    or str(row["sha256"]) != metadata.sha256
                    or int(row["byte_size"]) != metadata.byte_size
                    or (None if row["width"] is None else int(row["width"]))
                    != metadata.width
                    or (None if row["height"] is None else int(row["height"]))
                    != metadata.height
                    or (None if row["duration_ms"] is None else int(row["duration_ms"]))
                    != metadata.duration_ms
                    or (
                        None
                        if row["sample_rate_hz"] is None
                        else int(row["sample_rate_hz"])
                    )
                    != metadata.sample_rate_hz
                    or (None if row["channels"] is None else int(row["channels"]))
                    != metadata.channels
                    or str(row["routing"]) != metadata.routing
                    or (
                        None
                        if row["document_format"] is None
                        else str(row["document_format"])
                    )
                    != metadata.document_format
                    or (
                        None
                        if row["projected_characters"] is None
                        else int(row["projected_characters"])
                    )
                    != metadata.projected_characters
                    or (
                        None
                        if row["projection_truncated"] is None
                        else bool(row["projection_truncated"])
                    )
                    != metadata.projection_truncated
                    or str(row["omitted_features_json"])
                    != json.dumps(
                        list(metadata.omitted_features),
                        ensure_ascii=True,
                        separators=(",", ":"),
                    )
                    or len(payload) != metadata.byte_size
                    or hashlib.sha256(payload).hexdigest() != metadata.sha256
                ):
                    connection.execute("ROLLBACK")
                    raise AgentCatalogError("agent_history_corrupt")

            attachment_ids = {
                source_id: self._fork_attachment_id(new_session_id, source_id)
                for source_id in message_attachments
            }
            rewritten_events = tuple(
                event.model_copy(
                    update={
                        "attachments": tuple(
                            attachment.model_copy(
                                update={
                                    "attachment_id": attachment_ids[
                                        attachment.attachment_id
                                    ]
                                }
                            )
                            for attachment in event.attachments
                        )
                    }
                )
                for event in events
            )
            copied_turn_count = sum(event.kind == "done" for event in events)
            source_tail_omitted = int(source["last_event_seq"]) > branch_event_seq
            timestamp = _iso(created_at)
            title = self._fork_title(str(source["title"]), command.title)
            try:
                connection.execute(
                    """
                    INSERT INTO agent_catalog_sessions(
                        session_id,project_id,title,workspace,model_alias,
                        created_at,updated_at,last_opened_at,revision,pinned,
                        archived_at,history_state,retention_policy,history_revision,
                        last_event_seq,turn_count,history_profile_json
                    ) VALUES(?,?,?,?,?,?,?,?,1,0,NULL,'memory_only','local_history',?,?,?,?)
                    """,
                    (
                        new_session_id,
                        destination_project_id,
                        title,
                        str(source["workspace"]),
                        None if source["model_alias"] is None else str(source["model_alias"]),
                        timestamp,
                        timestamp,
                        timestamp,
                        len(rewritten_events),
                        branch_event_seq,
                        copied_turn_count,
                        source["history_profile_json"],
                    ),
                )
                for event in rewritten_events:
                    payload = event.model_dump_json(exclude_none=True)
                    if len(payload) > MAX_AGENT_HISTORY_EVENT_CHARS:
                        raise AgentCatalogError("agent_history_event_too_large")
                    connection.execute(
                        """
                        INSERT INTO agent_conversation_events(
                            session_id,event_seq,event_at,event_kind,turn_id,
                            event_contract_version,payload_json
                        ) VALUES(?,?,?,?,?,'agent-history.v1',?)
                        """,
                        (
                            new_session_id,
                            event.seq,
                            _iso(event.at),
                            event.kind,
                            event.turn_id,
                            payload,
                        ),
                    )
                    self._index_visible_message(
                        connection, session_id=new_session_id, event=event
                    )
                for row in attachment_rows:
                    source_attachment_id = str(row["attachment_id"])
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
                            attachment_ids[source_attachment_id],
                            new_session_id,
                            row["model_alias"],
                            row["capability_probe_version"],
                            row["attachment_kind"],
                            row["media_type"],
                            row["display_name"],
                            row["source_kind"],
                            "attached",
                            "local_history",
                            row["created_at"],
                            None,
                            row["attached_event_seq"],
                            row["sha256"],
                            row["byte_size"],
                            row["width"],
                            row["height"],
                            row["duration_ms"],
                            row["sample_rate_hz"],
                            row["channels"],
                            row["routing"],
                            row["document_format"],
                            row["projected_characters"],
                            row["projection_truncated"],
                            row["omitted_features_json"],
                            row["payload"],
                        ),
                    )
                connection.execute(
                    """
                    INSERT INTO agent_session_lineage(
                        session_id,fork_request_id,source_project_id,source_session_id,
                        source_catalog_revision,source_history_revision,
                        requested_destination_project_id,requested_through_event_seq,
                        requested_title,branch_event_seq,copied_event_count,
                        copied_turn_count,copied_attachment_count,source_tail_omitted,
                        created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        new_session_id,
                        command.request_id,
                        source_project_id,
                        source_session_id,
                        command.expected_catalog_revision,
                        command.expected_history_revision,
                        command.destination_project_id,
                        command.through_event_seq,
                        command.title,
                        branch_event_seq,
                        len(rewritten_events),
                        copied_turn_count,
                        len(attachment_rows),
                        int(source_tail_omitted),
                        timestamp,
                    ),
                )
                self._touch_projects(connection, {destination_project_id}, created_at)
                receipt = self._fork_receipt(
                    connection,
                    command.request_id,
                    idempotent_replay=False,
                )
                connection.execute("COMMIT")
                return receipt
            except AgentCatalogError:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
            except sqlite3.IntegrityError:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_session_fork_conflict") from None

    def list_sessions(
        self,
        *,
        project_id: str | None,
        search: str | None,
        include_archived: bool,
        limit: int,
    ) -> tuple[AgentCatalogSessionRecord, ...]:
        clauses: list[str] = []
        values: list[object] = []
        if project_id is not None:
            clauses.append("session.project_id=?")
            values.append(project_id)
        if not include_archived:
            clauses.append("session.archived_at IS NULL")
        if search:
            clauses.append("lower(session.title) LIKE ? ESCAPE '\\'")
            values.append(_like(search))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(limit)
        with self._database.connect() as connection:
            rows = connection.execute(
                f"""
                {self._session_select()}
                {where}
                ORDER BY session.pinned DESC,
                         CASE WHEN session.archived_at IS NULL THEN 0 ELSE 1 END,
                         session.last_opened_at DESC, session.session_id
                LIMIT ?
                """,
                tuple(values),
            ).fetchall()
            return tuple(self._session_record(row) for row in rows)

    def page_sessions(
        self,
        *,
        project_id: str | None,
        search: str | None,
        include_archived: bool,
        limit: int,
        offset: int,
        snapshot: str | None,
    ) -> tuple[tuple[AgentCatalogSessionRecord, ...], int, str]:
        if limit < 1 or limit > MAX_AGENT_CATALOG_PAGE_SIZE:
            raise AgentCatalogError("agent_catalog_page_invalid")
        if offset < 0 or offset > MAX_AGENT_CATALOG_SESSIONS:
            raise AgentCatalogError("agent_catalog_page_out_of_range")
        if offset > 0 and snapshot is None:
            raise AgentCatalogError("agent_catalog_page_snapshot_required")
        clauses: list[str] = []
        values: list[object] = []
        if project_id is not None:
            clauses.append("session.project_id=?")
            values.append(project_id)
        if not include_archived:
            clauses.append("session.archived_at IS NULL")
        if search:
            clauses.append("lower(session.title) LIKE ? ESCAPE '\\'")
            values.append(_like(search))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._database.connect() as connection:
            connection.execute("BEGIN")
            try:
                rows = connection.execute(
                    f"""
                    {self._session_select()}
                    {where}
                    ORDER BY session.pinned DESC,
                             CASE WHEN session.archived_at IS NULL THEN 0 ELSE 1 END,
                             session.last_opened_at DESC, session.session_id
                    """,
                    tuple(values),
                ).fetchall()
                records = tuple(self._session_record(row) for row in rows)
                current_snapshot = _catalog_page_snapshot(
                    collection="sessions",
                    scope={
                        "include_archived": include_archived,
                        "project_id": project_id,
                        "search": search,
                    },
                    records=[
                        record.model_dump(mode="json") for record in records
                    ],
                )
                if snapshot is not None and snapshot != current_snapshot:
                    raise AgentCatalogError("agent_catalog_page_snapshot_conflict")
                if offset > len(records):
                    raise AgentCatalogError("agent_catalog_page_out_of_range")
                page = records[offset : offset + limit]
                connection.execute("COMMIT")
                return page, len(records), current_snapshot
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise

    def search_messages(
        self,
        *,
        request: AgentMessageSearchRequest,
    ) -> tuple[tuple[AgentMessageSearchHit, ...], int, str]:
        """Search the explicit visible-text projection, never journal JSON.

        `unicode61 remove_diacritics 0` makes matching case-insensitive while
        preserving diacritic distinctions. The bound phrase is literal input,
        so `OR`, quotes, punctuation, and SQL syntax have no operator effect.
        """
        clauses = [
            "session.retention_policy='local_history'",
            "session.archived_at IS NULL" if not request.include_archived else "1=1",
            "project.archived_at IS NULL" if not request.include_archived else "1=1",
        ]
        values: list[object] = [self._message_search_phrase(request.query)]
        if request.project_id is not None:
            clauses.append("session.project_id=?")
            values.append(request.project_id)
        where = " AND ".join(clauses)
        # First result per chat is deterministic by event sequence. Keep only
        # IDs/revisions while snapshotting: no matching plaintext is copied
        # into an in-memory result set beyond the requested page.
        base = f"""
            WITH fts_matches AS (
                SELECT message_id, session_id, event_seq, role
                FROM agent_message_search_fts
                JOIN agent_message_search_messages
                  ON agent_message_search_messages.message_id=agent_message_search_fts.rowid
                WHERE agent_message_search_fts MATCH ?
            ), ranked AS (
                SELECT fts_matches.message_id, fts_matches.session_id,
                       fts_matches.event_seq, fts_matches.role,
                       session.project_id, session.history_revision,
                       session.revision AS catalog_revision, project.revision AS project_revision,
                       session.pinned, session.last_opened_at,
                       project.name AS project_name, session.title,
                       ROW_NUMBER() OVER (
                         PARTITION BY fts_matches.session_id
                         ORDER BY fts_matches.event_seq ASC
                       ) AS row_number
                FROM fts_matches
                JOIN agent_catalog_sessions AS session ON session.session_id=fts_matches.session_id
                JOIN agent_projects AS project ON project.project_id=session.project_id
                WHERE {where}
            )
        """
        ordering = "ORDER BY pinned DESC,last_opened_at DESC,session_id"
        with self._database.connect() as connection:
            deadline = time.monotonic() + 2.0
            connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 10_000)
            connection.execute("BEGIN")
            try:
                # FTS5 verifies the external-content index before it answers.
                # A damaged index is unavailable, never an empty result set.
                connection.execute(
                    "INSERT INTO agent_message_search_fts(agent_message_search_fts,rank) VALUES('integrity-check',1)"
                )
                metadata = connection.execute(
                    base + f"""
                    SELECT message_id,session_id,project_id,project_name,title,event_seq,history_revision,
                           catalog_revision,project_revision,role,
                           pinned,last_opened_at
                    FROM ranked WHERE row_number=1 {ordering} LIMIT ?
                    """,
                    (*values, MAX_AGENT_CATALOG_SESSIONS + 1),
                ).fetchall()
            except sqlite3.DatabaseError as error:
                # A missing/corrupt FTS virtual table must never look like no hits.
                connection.set_progress_handler(None, 0)
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                code = (
                    "agent_message_search_timed_out"
                    if time.monotonic() >= deadline
                    else "agent_message_search_unavailable"
                )
                raise AgentCatalogError(code) from error
            total = len(metadata)
            if total > MAX_AGENT_CATALOG_SESSIONS:
                connection.set_progress_handler(None, 0)
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_message_search_corrupt")
            snapshot = _catalog_page_snapshot(
                collection="message-search",
                scope={
                    "query": request.query,
                    "project_id": request.project_id,
                    "include_archived": request.include_archived,
                },
                records=[dict(row) for row in metadata],
            )
            if request.snapshot is not None and request.snapshot != snapshot:
                connection.set_progress_handler(None, 0)
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_message_search_snapshot_conflict")
            if request.offset > total:
                connection.set_progress_handler(None, 0)
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_message_search_page_out_of_range")
            selected = metadata[request.offset : request.offset + request.limit]
            selected_ids = tuple(int(row["message_id"]) for row in selected)
            for _ in range(3):
                marker = uuid.uuid4().hex
                open_marker = f"__agent_search_open_{marker}__"
                close_marker = f"__agent_search_close_{marker}__"
                collision = None if not selected_ids else connection.execute(
                    """SELECT 1 FROM agent_message_search_messages
                       WHERE message_id IN ({}) AND (instr(text,?) > 0 OR instr(text,?) > 0)
                       LIMIT 1""".format(",".join("?" for _ in selected_ids)),
                    (*selected_ids, open_marker, close_marker),
                ).fetchone()
                if collision is None:
                    break
            else:
                connection.set_progress_handler(None, 0)
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_message_search_corrupt")
            rows: list[tuple[sqlite3.Row, str]] = []
            try:
                for row in selected:
                    # Highlight is evaluated only for the <=50 requested rows, not
                    # for every matching message in the catalog.
                    decorated = connection.execute(
                    """SELECT highlight(agent_message_search_fts,0,?,?)
                       FROM agent_message_search_fts
                       WHERE rowid=? AND agent_message_search_fts MATCH ?""",
                    (open_marker, close_marker, int(row["message_id"]), values[0]),
                    ).fetchone()
                    if decorated is None:
                        raise AgentCatalogError("agent_message_search_corrupt")
                    rows.append((row, str(decorated[0])))
            except sqlite3.DatabaseError as error:
                code = "agent_message_search_timed_out" if time.monotonic() >= deadline else "agent_message_search_unavailable"
                raise AgentCatalogError(code) from error
            finally:
                connection.set_progress_handler(None, 0)
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
        matches = tuple(
            AgentMessageSearchHit(
                session_id=str(row["session_id"]), project_id=str(row["project_id"]),
                project_name=str(row["project_name"]), title=str(row["title"]),
                match_event_seq=int(row["event_seq"]), history_revision=int(row["history_revision"]),
                role=cast(Literal["user", "assistant"], str(row["role"])),
                excerpt=self._message_excerpt(decorated, open_marker, close_marker),
            )
            for row, decorated in rows
        )
        return matches, total, snapshot

    def update_session(
        self,
        session_id: str,
        command: UpdateAgentCatalogSession,
        changed_at: datetime,
    ) -> AgentCatalogSessionRecord:
        assignments = ["updated_at=?", "revision=revision+1"]
        timestamp = _iso(changed_at)
        values: list[object] = [timestamp]
        if command.title is not None:
            assignments.append("title=?")
            values.append(command.title)
        if command.project_id is not None:
            assignments.append("project_id=?")
            values.append(command.project_id)
        if command.model_alias is not None:
            assignments.append("model_alias=?")
            values.append(command.model_alias)
        if command.pinned is not None:
            assignments.append("pinned=?")
            values.append(int(command.pinned))
        if command.archived is not None:
            assignments.append("archived_at=?")
            values.append(timestamp if command.archived else None)
        values.extend((session_id, command.expected_revision))
        with self._write_lock, self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT project_id FROM agent_catalog_sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            if current is None:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_catalog_session_not_found")
            source_project_id = str(current["project_id"])
            if command.project_id is not None:
                destination = connection.execute(
                    "SELECT archived_at FROM agent_projects WHERE project_id=?",
                    (command.project_id,),
                ).fetchone()
                if destination is None:
                    connection.execute("ROLLBACK")
                    raise AgentCatalogError("agent_project_not_found")
                if destination["archived_at"] is not None:
                    connection.execute("ROLLBACK")
                    raise AgentCatalogError("agent_project_archived")
            cursor = connection.execute(
                f"UPDATE agent_catalog_sessions SET {', '.join(assignments)} WHERE session_id=? AND revision=?",
                tuple(values),
            )
            if cursor.rowcount != 1:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_catalog_session_revision_conflict")
            self._touch_projects(
                connection,
                {source_project_id, command.project_id or source_project_id},
                changed_at,
            )
            connection.execute("COMMIT")
            session = self._get_session(connection, session_id)
            assert session is not None
            return session

    def delete_session(
        self,
        session_id: str,
        expected_catalog_revision: int,
        expected_history_revision: int,
        changed_at: datetime,
    ) -> None:
        with self._write_lock, self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT project_id, revision, history_revision
                   FROM agent_catalog_sessions WHERE session_id=?""",
                (session_id,),
            ).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_catalog_session_not_found")
            if int(row["revision"]) != expected_catalog_revision:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_catalog_session_revision_conflict")
            if int(row["history_revision"]) != expected_history_revision:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_history_revision_conflict")
            self._delete_visible_messages(connection, session_id=session_id)
            cursor = connection.execute(
                """DELETE FROM agent_catalog_sessions
                   WHERE session_id=? AND revision=? AND history_revision=?""",
                (session_id, expected_catalog_revision, expected_history_revision),
            )
            if cursor.rowcount != 1:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_catalog_session_revision_conflict")
            self._touch_projects(connection, {str(row["project_id"])}, changed_at)
            connection.execute("COMMIT")

    def append_history_event(
        self,
        *,
        project_id: str,
        session_id: str,
        expected_history_revision: int,
        event: StoredAgentEvent,
    ) -> int:
        """Append one exact event and advance the independent history head."""

        payload = event.model_dump_json(exclude_none=True)
        if len(payload) > MAX_AGENT_HISTORY_EVENT_CHARS:
            raise AgentCatalogError("agent_history_event_too_large")
        with self._write_lock, self._database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                """
                SELECT project_id,retention_policy,history_revision,last_event_seq
                FROM agent_catalog_sessions WHERE session_id=?
                """,
                (session_id,),
            ).fetchone()
            if current is None or str(current["project_id"]) != project_id:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_catalog_session_not_found")
            if str(current["retention_policy"]) != AgentRetentionPolicy.LOCAL_HISTORY.value:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_history_not_retained")
            if int(current["history_revision"]) != expected_history_revision:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_history_revision_conflict")
            if event.seq <= int(current["last_event_seq"]):
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_history_sequence_conflict")
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM agent_conversation_events WHERE session_id=?",
                    (session_id,),
                ).fetchone()[0]
            )
            if count >= MAX_AGENT_HISTORY_EVENTS:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_history_limit_reached")
            try:
                connection.execute(
                    """
                    INSERT INTO agent_conversation_events(
                        session_id,event_seq,event_at,event_kind,turn_id,
                        event_contract_version,payload_json
                    ) VALUES(?,?,?,?,?,'agent-history.v1',?)
                    """,
                    (
                        session_id,
                        event.seq,
                        _iso(event.at),
                        event.kind,
                        event.turn_id,
                        payload,
                    ),
                )
                self._index_visible_message(connection, session_id=session_id, event=event)
                connection.execute(
                    """
                    UPDATE agent_catalog_sessions
                    SET history_revision=history_revision+1,
                        last_event_seq=?,
                        turn_count=turn_count+?,
                        updated_at=?,
                        last_opened_at=?
                    WHERE session_id=? AND history_revision=?
                    """,
                    (
                        event.seq,
                        int(event.kind == "done"),
                        _iso(event.at),
                        _iso(event.at),
                        session_id,
                        expected_history_revision,
                    ),
                )
                connection.execute("COMMIT")
            except sqlite3.IntegrityError:
                connection.execute("ROLLBACK")
                raise AgentCatalogError("agent_history_sequence_conflict") from None
        return expected_history_revision + 1

    def read_history(
        self,
        *,
        project_id: str,
        session_id: str,
        after: int,
        limit: int,
    ) -> AgentHistorySnapshot:
        with self._database.connect() as connection:
            current = connection.execute(
                """
                SELECT project_id,retention_policy,history_revision,last_event_seq,
                       turn_count,history_profile_json
                FROM agent_catalog_sessions WHERE session_id=?
                """,
                (session_id,),
            ).fetchone()
            if current is None or str(current["project_id"]) != project_id:
                raise AgentCatalogError("agent_catalog_session_not_found")
            if str(current["retention_policy"]) != AgentRetentionPolicy.LOCAL_HISTORY.value:
                raise AgentCatalogError("agent_history_not_retained")
            rows = connection.execute(
                """
                SELECT event_seq,payload_json
                FROM agent_conversation_events
                WHERE session_id=? AND event_seq>?
                ORDER BY event_seq ASC LIMIT ?
                """,
                (session_id, after, limit),
            ).fetchall()
            first = connection.execute(
                "SELECT MIN(event_seq) FROM agent_conversation_events WHERE session_id=?",
                (session_id,),
            ).fetchone()[0]
            turn_head = connection.execute(
                """
                SELECT
                    MAX(CASE WHEN event_kind='user' THEN event_seq END) AS last_user_seq,
                    MAX(CASE WHEN event_kind='done' THEN event_seq END) AS last_done_seq
                FROM agent_conversation_events WHERE session_id=?
                """,
                (session_id,),
            ).fetchone()
        try:
            events = tuple(
                StoredAgentEvent.model_validate_json(str(row["payload_json"]))
                for row in rows
            )
        except (ValueError, TypeError):
            raise AgentCatalogError("agent_history_corrupt") from None
        if any(event.seq != int(row["event_seq"]) for event, row in zip(events, rows, strict=True)):
            raise AgentCatalogError("agent_history_corrupt")
        last_seq = int(current["last_event_seq"])
        return AgentHistorySnapshot(
            project_id=project_id,
            session_id=session_id,
            history_revision=int(current["history_revision"]),
            first_seq=0 if first is None else int(first),
            last_seq=last_seq,
            turn_count=int(current["turn_count"]),
            interrupted=(
                turn_head is not None
                and turn_head["last_user_seq"] is not None
                and (
                    turn_head["last_done_seq"] is None
                    or int(turn_head["last_user_seq"]) > int(turn_head["last_done_seq"])
                )
            ),
            profile_json=(
                None
                if current["history_profile_json"] is None
                else str(current["history_profile_json"])
            ),
            events=events,
        )


_AGENT_MCP_CONNECTION_SELECT = """
    SELECT connection_record.*, scoped_project.name AS scope_project_name
    FROM agent_mcp_connections AS connection_record
    LEFT JOIN agent_projects AS scoped_project
      ON scoped_project.project_id = connection_record.scope_project_id
"""


_AGENT_CONTROLLER_OWNERSHIP_SELECT = """
    SELECT
        ownership.*,
        project.name AS project_name,
        catalog_session.title AS session_title,
        owner.label AS owner_label,
        owner.client_kind AS owner_client_kind,
        target.label AS target_label,
        target.client_kind AS target_client_kind
    FROM agent_controller_ownerships AS ownership
    JOIN agent_projects AS project
      ON project.project_id=ownership.project_id
    JOIN agent_catalog_sessions AS catalog_session
      ON catalog_session.session_id=ownership.session_id
     AND catalog_session.project_id=ownership.project_id
    JOIN agent_mcp_connections AS owner
      ON owner.connection_id=ownership.owner_connection_id
    LEFT JOIN agent_mcp_connections AS target
      ON target.connection_id=ownership.handoff_target_connection_id
"""


class SqliteAgentMcpConnectionRepository:
    """Bounded credential metadata stored beside the durable Agent catalog."""

    def __init__(self, database: AgentCatalogSqliteDatabase) -> None:
        self._database = database
        self._write_lock = threading.RLock()
        self._database.initialize()

    @staticmethod
    def _record(row: sqlite3.Row, *, now: datetime) -> AgentMcpConnection:
        revoked_at = (
            None if row["revoked_at"] is None else _time(str(row["revoked_at"]))
        )
        expires_at = _time(str(row["expires_at"]))
        scope_project_id = (
            None
            if row["scope_project_id"] is None
            else str(row["scope_project_id"])
        )
        scope_project_name = (
            None
            if row["scope_project_name"] is None
            else str(row["scope_project_name"])
        )
        scope_bound = scope_project_id is not None and scope_project_name is not None
        return AgentMcpConnection(
            connection_id=str(row["connection_id"]),
            label=str(row["label"]),
            client_kind=cast(AgentMcpClientKind, str(row["client_kind"])),
            created_at=_time(str(row["created_at"])),
            updated_at=_time(str(row["updated_at"])),
            expires_at=expires_at,
            last_used_at=(
                None
                if row["last_used_at"] is None
                else _time(str(row["last_used_at"]))
            ),
            last_tool_at=(
                None
                if row["last_tool_at"] is None
                else _time(str(row["last_tool_at"]))
            ),
            last_tool_name=(
                None
                if row["last_tool_name"] is None
                else str(row["last_tool_name"])
            ),
            last_tool_outcome=(
                None
                if row["last_tool_outcome"] is None
                else cast(AgentMcpToolOutcome, str(row["last_tool_outcome"]))
            ),
            last_tool_source=(
                None
                if row["last_tool_source"] is None
                else cast(AgentMcpToolSource, str(row["last_tool_source"]))
            ),
            last_auth_rejected_at=(
                None
                if row["last_auth_rejected_at"] is None
                else _time(str(row["last_auth_rejected_at"]))
            ),
            revoked_at=revoked_at,
            revision=int(row["revision"]),
            credential_revision=int(row["credential_revision"]),
            allow_model_lifecycle=bool(row["allow_model_lifecycle"]),
            scope=AgentMcpConnectionScope(
                state="bound" if scope_bound else "missing",
                project_id=scope_project_id if scope_bound else None,
                project_name=scope_project_name if scope_bound else None,
                catalog_access="project_only" if scope_bound else "none",
                chat_access="project_only" if scope_bound else "none",
                workspace_access="project_only" if scope_bound else "none",
            ),
            state=_connection_state(
                expires_at=expires_at,
                revoked_at=revoked_at,
                scope_project_id=scope_project_id,
                scope_project_name=scope_project_name,
                now=now,
            ),
        )

    @staticmethod
    def _ownership_record(
        row: sqlite3.Row,
        *,
        now: datetime,
    ) -> AgentControllerOwnership:
        handoff = None
        if (
            row["handoff_target_connection_id"] is not None
            and row["handoff_offered_at"] is not None
            and row["handoff_expires_at"] is not None
            and row["target_label"] is not None
            and row["target_client_kind"] is not None
            and _time(str(row["handoff_expires_at"])) > now
        ):
            handoff = AgentControllerHandoff(
                target_connection_id=str(row["handoff_target_connection_id"]),
                target_label=str(row["target_label"]),
                target_client_kind=cast(
                    AgentMcpClientKind,
                    str(row["target_client_kind"]),
                ),
                offered_at=_time(str(row["handoff_offered_at"])),
                expires_at=_time(str(row["handoff_expires_at"])),
            )
        return AgentControllerOwnership(
            project_id=str(row["project_id"]),
            project_name=str(row["project_name"]),
            session_id=str(row["session_id"]),
            session_title=str(row["session_title"]),
            owner_connection_id=str(row["owner_connection_id"]),
            owner_label=str(row["owner_label"]),
            owner_client_kind=cast(
                AgentMcpClientKind,
                str(row["owner_client_kind"]),
            ),
            operation=cast(AgentControllerOperation, str(row["operation"])),
            state=cast(AgentControllerOwnershipState, str(row["state"])),
            cursor=int(row["cursor"]),
            last_seq=int(row["last_seq"]),
            approval_pending=bool(row["approval_pending"]),
            ownership_started_at=_time(str(row["ownership_started_at"])),
            owner_since=_time(str(row["owner_since"])),
            updated_at=_time(str(row["updated_at"])),
            revision=int(row["revision"]),
            handoff=handoff,
        )

    def create_connection(
        self,
        *,
        connection_id: str,
        request_id: str,
        request_fingerprint: str,
        label: str,
        client_kind: AgentMcpClientKind,
        scope_project_id: str,
        allow_model_lifecycle: bool,
        created_at: datetime,
        expires_at: datetime,
        active_limit: int,
    ) -> tuple[AgentMcpConnection, bool]:
        try:
            with self._write_lock, self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    _AGENT_MCP_CONNECTION_SELECT
                    + " WHERE connection_record.request_id=?",
                    (request_id,),
                ).fetchone()
                if existing is not None:
                    if str(existing["request_fingerprint"]) != request_fingerprint:
                        connection.execute("ROLLBACK")
                        raise AgentMcpConnectionError(
                            "agent_mcp_connection_request_conflict"
                        )
                    result = self._record(existing, now=created_at)
                    connection.execute("COMMIT")
                    return result, True
                scoped_project = connection.execute(
                    """
                    SELECT project_id FROM agent_projects
                    WHERE project_id=? AND archived_at IS NULL
                    """,
                    (scope_project_id,),
                ).fetchone()
                if scoped_project is None:
                    connection.execute("ROLLBACK")
                    raise AgentMcpConnectionError("agent_mcp_scope_project_unavailable")
                active_count = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM agent_mcp_connections AS candidate
                        WHERE candidate.revoked_at IS NULL
                          AND candidate.expires_at>?
                          AND candidate.scope_project_id IS NOT NULL
                          AND EXISTS(
                              SELECT 1 FROM agent_projects AS scoped_project
                              WHERE scoped_project.project_id=candidate.scope_project_id
                          )
                        """,
                        (_iso(created_at),),
                    ).fetchone()[0]
                )
                if active_count >= active_limit:
                    connection.execute("ROLLBACK")
                    raise AgentMcpConnectionError(
                        "too_many_agent_mcp_connections"
                    )
                try:
                    connection.execute(
                        """
                        INSERT INTO agent_mcp_connections(
                            connection_id,request_id,request_fingerprint,label,
                            client_kind,created_at,updated_at,expires_at,last_used_at,
                            revoked_at,revision,credential_revision,
                            allow_model_lifecycle,scope_project_id
                        ) VALUES(?,?,?,?,?,?,?,?,NULL,NULL,1,1,?,?)
                        """,
                        (
                            connection_id,
                            request_id,
                            request_fingerprint,
                            label,
                            client_kind,
                            _iso(created_at),
                            _iso(created_at),
                            _iso(expires_at),
                            int(allow_model_lifecycle),
                            scope_project_id,
                        ),
                    )
                except sqlite3.IntegrityError:
                    connection.execute("ROLLBACK")
                    raise AgentMcpConnectionError(
                        "agent_mcp_connection_identity_conflict"
                    ) from None
                stored = connection.execute(
                    _AGENT_MCP_CONNECTION_SELECT
                    + " WHERE connection_record.connection_id=?",
                    (connection_id,),
                ).fetchone()
                if stored is None:
                    connection.execute("ROLLBACK")
                    raise AgentMcpConnectionError(
                        "agent_mcp_connection_storage_unavailable"
                    )
                result = self._record(stored, now=created_at)
                connection.execute("COMMIT")
                return result, False
        except AgentMcpConnectionError:
            raise
        except AgentCatalogError:
            raise AgentMcpConnectionError(
                "agent_mcp_connection_storage_unavailable"
            ) from None

    def list_connections(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[AgentMcpConnection, ...]:
        try:
            with self._database.connect() as connection:
                rows = connection.execute(
                    _AGENT_MCP_CONNECTION_SELECT
                    + """
                    ORDER BY
                        CASE
                            WHEN connection_record.revoked_at IS NULL
                              AND connection_record.scope_project_id IS NOT NULL
                              AND scoped_project.project_id IS NOT NULL
                              AND connection_record.expires_at>? THEN 0
                            WHEN connection_record.revoked_at IS NULL
                              AND (connection_record.scope_project_id IS NULL
                                   OR scoped_project.project_id IS NULL) THEN 1
                            WHEN connection_record.revoked_at IS NULL THEN 2
                            ELSE 3
                        END,
                        connection_record.updated_at DESC,
                        connection_record.connection_id
                    LIMIT ?
                    """,
                    (_iso(now), limit),
                ).fetchall()
            return tuple(self._record(row, now=now) for row in rows)
        except AgentCatalogError:
            raise AgentMcpConnectionError(
                "agent_mcp_connection_storage_unavailable"
            ) from None

    def get_connection(
        self,
        connection_id: str,
        *,
        now: datetime,
    ) -> AgentMcpConnection | None:
        try:
            with self._database.connect() as connection:
                row = connection.execute(
                    _AGENT_MCP_CONNECTION_SELECT
                    + " WHERE connection_record.connection_id=?",
                    (connection_id,),
                ).fetchone()
            return None if row is None else self._record(row, now=now)
        except AgentCatalogError:
            raise AgentMcpConnectionError(
                "agent_mcp_connection_storage_unavailable"
            ) from None

    def rotate_connection(
        self,
        connection_id: str,
        *,
        request_id: str,
        request_fingerprint: str,
        expected_revision: int,
        updated_at: datetime,
        expires_at: datetime,
    ) -> tuple[AgentMcpConnection, bool]:
        try:
            with self._write_lock, self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                replay = connection.execute(
                    """
                    SELECT * FROM agent_mcp_connection_rotations
                    WHERE request_id=?
                    """,
                    (request_id,),
                ).fetchone()
                if replay is not None:
                    if (
                        str(replay["connection_id"]) != connection_id
                        or str(replay["request_fingerprint"])
                        != request_fingerprint
                        or int(replay["expected_revision"]) != expected_revision
                    ):
                        connection.execute("ROLLBACK")
                        raise AgentMcpConnectionError(
                            "agent_mcp_rotation_request_conflict"
                        )
                    current = connection.execute(
                        _AGENT_MCP_CONNECTION_SELECT
                        + " WHERE connection_record.connection_id=?",
                        (connection_id,),
                    ).fetchone()
                    if (
                        current is None
                        or int(current["revision"])
                        != int(replay["resulting_revision"])
                        or int(current["credential_revision"])
                        != int(replay["resulting_credential_revision"])
                    ):
                        connection.execute("ROLLBACK")
                        raise AgentMcpConnectionError(
                            "agent_mcp_rotation_replay_stale"
                        )
                    result = self._record(current, now=updated_at)
                    connection.execute("COMMIT")
                    return result, True
                current = connection.execute(
                    _AGENT_MCP_CONNECTION_SELECT
                    + " WHERE connection_record.connection_id=?",
                    (connection_id,),
                ).fetchone()
                if current is None:
                    connection.execute("ROLLBACK")
                    raise AgentMcpConnectionError(
                        "agent_mcp_connection_not_found"
                    )
                current_record = self._record(current, now=updated_at)
                if current_record.state != "active":
                    connection.execute("ROLLBACK")
                    raise AgentMcpConnectionError(
                        "agent_mcp_connection_inactive"
                    )
                if current_record.revision != expected_revision:
                    connection.execute("ROLLBACK")
                    raise AgentMcpConnectionError(
                        "agent_mcp_connection_revision_conflict"
                    )
                next_revision = current_record.revision + 1
                next_credential_revision = current_record.credential_revision + 1
                connection.execute(
                    """
                    UPDATE agent_mcp_connections
                    SET updated_at=?,expires_at=?,revision=?,credential_revision=?
                    WHERE connection_id=?
                    """,
                    (
                        _iso(updated_at),
                        _iso(expires_at),
                        next_revision,
                        next_credential_revision,
                        connection_id,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO agent_mcp_connection_rotations(
                        request_id,request_fingerprint,connection_id,
                        expected_revision,resulting_revision,
                        resulting_credential_revision,created_at
                    ) VALUES(?,?,?,?,?,?,?)
                    """,
                    (
                        request_id,
                        request_fingerprint,
                        connection_id,
                        expected_revision,
                        next_revision,
                        next_credential_revision,
                        _iso(updated_at),
                    ),
                )
                stored = connection.execute(
                    _AGENT_MCP_CONNECTION_SELECT
                    + " WHERE connection_record.connection_id=?",
                    (connection_id,),
                ).fetchone()
                if stored is None:
                    connection.execute("ROLLBACK")
                    raise AgentMcpConnectionError(
                        "agent_mcp_connection_storage_unavailable"
                    )
                result = self._record(stored, now=updated_at)
                connection.execute("COMMIT")
                return result, False
        except AgentMcpConnectionError:
            raise
        except AgentCatalogError:
            raise AgentMcpConnectionError(
                "agent_mcp_connection_storage_unavailable"
            ) from None

    def revoke_connection(
        self,
        connection_id: str,
        *,
        expected_revision: int,
        revoked_at: datetime,
    ) -> tuple[AgentMcpConnection, bool]:
        try:
            with self._write_lock, self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    _AGENT_MCP_CONNECTION_SELECT
                    + " WHERE connection_record.connection_id=?",
                    (connection_id,),
                ).fetchone()
                if current is None:
                    connection.execute("ROLLBACK")
                    raise AgentMcpConnectionError(
                        "agent_mcp_connection_not_found"
                    )
                current_record = self._record(current, now=revoked_at)
                if current_record.state == "revoked":
                    connection.execute("COMMIT")
                    return current_record, True
                if current_record.revision != expected_revision:
                    connection.execute("ROLLBACK")
                    raise AgentMcpConnectionError(
                        "agent_mcp_connection_revision_conflict"
                    )
                connection.execute(
                    """
                    UPDATE agent_mcp_connections
                    SET updated_at=?,revoked_at=?,revision=revision+1
                    WHERE connection_id=?
                    """,
                    (_iso(revoked_at), _iso(revoked_at), connection_id),
                )
                connection.execute(
                    """
                    UPDATE agent_controller_ownerships
                    SET state='revoked',updated_at=?,revision=revision+1,
                        handoff_target_connection_id=NULL,
                        handoff_offered_at=NULL,handoff_expires_at=NULL
                    WHERE owner_connection_id=?
                    """,
                    (_iso(revoked_at), connection_id),
                )
                connection.execute(
                    """
                    UPDATE agent_controller_ownerships
                    SET updated_at=?,revision=revision+1,
                        handoff_target_connection_id=NULL,
                        handoff_offered_at=NULL,handoff_expires_at=NULL
                    WHERE handoff_target_connection_id=?
                    """,
                    (_iso(revoked_at), connection_id),
                )
                stored = connection.execute(
                    _AGENT_MCP_CONNECTION_SELECT
                    + " WHERE connection_record.connection_id=?",
                    (connection_id,),
                ).fetchone()
                if stored is None:
                    connection.execute("ROLLBACK")
                    raise AgentMcpConnectionError(
                        "agent_mcp_connection_storage_unavailable"
                    )
                result = self._record(stored, now=revoked_at)
                connection.execute("COMMIT")
                return result, False
        except AgentMcpConnectionError:
            raise
        except AgentCatalogError:
            raise AgentMcpConnectionError(
                "agent_mcp_connection_storage_unavailable"
            ) from None

    def touch_connection(self, connection_id: str, *, used_at: datetime) -> None:
        try:
            with self._write_lock, self._database.connect() as connection:
                connection.execute(
                    """
                    UPDATE agent_mcp_connections
                    SET last_used_at=?
                    WHERE connection_id=? AND revoked_at IS NULL AND expires_at>?
                      AND (last_used_at IS NULL OR last_used_at<?)
                    """,
                    (
                        _iso(used_at),
                        connection_id,
                        _iso(used_at),
                        _iso(used_at),
                    ),
                )
        except AgentCatalogError:
            raise AgentMcpConnectionError(
                "agent_mcp_connection_storage_unavailable"
            ) from None

    def record_tool_call(
        self,
        connection_id: str,
        *,
        tool_name: str,
        outcome: AgentMcpToolOutcome,
        source: AgentMcpToolSource,
        observed_at: datetime,
    ) -> None:
        try:
            with self._write_lock, self._database.connect() as connection:
                connection.execute(
                    """
                    UPDATE agent_mcp_connections
                    SET last_tool_at=?,last_tool_name=?,last_tool_outcome=?,
                        last_tool_source=?
                    WHERE connection_id=? AND revoked_at IS NULL AND expires_at>?
                      AND (last_tool_at IS NULL OR last_tool_at<=?)
                    """,
                    (
                        _iso(observed_at),
                        tool_name,
                        outcome,
                        source,
                        connection_id,
                        _iso(observed_at),
                        _iso(observed_at),
                    ),
                )
        except (AgentCatalogError, sqlite3.Error):
            raise AgentMcpConnectionError(
                "agent_mcp_connection_storage_unavailable"
            ) from None

    def record_auth_rejection(
        self,
        connection_id: str,
        *,
        rejected_at: datetime,
    ) -> None:
        try:
            with self._write_lock, self._database.connect() as connection:
                connection.execute(
                    """
                    UPDATE agent_mcp_connections
                    SET last_auth_rejected_at=?
                    WHERE connection_id=?
                      AND (last_auth_rejected_at IS NULL OR last_auth_rejected_at<?)
                    """,
                    (
                        _iso(rejected_at),
                        connection_id,
                        _iso(rejected_at),
                    ),
                )
        except (AgentCatalogError, sqlite3.Error):
            raise AgentMcpConnectionError(
                "agent_mcp_connection_storage_unavailable"
            ) from None

    def claim_controller_ownership(
        self,
        *,
        connection_id: str,
        project_id: str,
        session_id: str,
        operation: AgentControllerOperation,
        claimed_at: datetime,
    ) -> AgentControllerOwnership:
        try:
            with self._write_lock, self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    _AGENT_CONTROLLER_OWNERSHIP_SELECT
                    + " WHERE ownership.session_id=?",
                    (session_id,),
                ).fetchone()
                if existing is not None:
                    connection.execute("ROLLBACK")
                    raise AgentControllerOwnershipError(
                        "agent_controller_session_owned"
                    )
                controller = connection.execute(
                    """
                    SELECT connection_id,scope_project_id,revoked_at,expires_at
                    FROM agent_mcp_connections WHERE connection_id=?
                    """,
                    (connection_id,),
                ).fetchone()
                if (
                    controller is None
                    or controller["revoked_at"] is not None
                    or _time(str(controller["expires_at"])) <= claimed_at
                ):
                    connection.execute("ROLLBACK")
                    raise AgentControllerOwnershipError(
                        "agent_controller_connection_inactive"
                    )
                if str(controller["scope_project_id"] or "") != project_id:
                    connection.execute("ROLLBACK")
                    raise AgentControllerOwnershipError(
                        "agent_controller_scope_mismatch"
                    )
                catalog_session = connection.execute(
                    """
                    SELECT project_id,archived_at FROM agent_catalog_sessions
                    WHERE session_id=?
                    """,
                    (session_id,),
                ).fetchone()
                if (
                    catalog_session is None
                    or str(catalog_session["project_id"]) != project_id
                    or catalog_session["archived_at"] is not None
                ):
                    connection.execute("ROLLBACK")
                    raise AgentControllerOwnershipError(
                        "agent_controller_scope_mismatch"
                    )
                stamp = _iso(claimed_at)
                connection.execute(
                    """
                    INSERT INTO agent_controller_ownerships(
                        session_id,project_id,owner_connection_id,operation,state,
                        cursor,last_seq,approval_pending,ownership_started_at,
                        owner_since,updated_at,revision,handoff_target_connection_id,
                        handoff_offered_at,handoff_expires_at
                    ) VALUES(?,?,?,?,'claimed',0,0,0,?,?,?,1,NULL,NULL,NULL)
                    """,
                    (
                        session_id,
                        project_id,
                        connection_id,
                        operation,
                        stamp,
                        stamp,
                        stamp,
                    ),
                )
                stored = connection.execute(
                    _AGENT_CONTROLLER_OWNERSHIP_SELECT
                    + " WHERE ownership.session_id=?",
                    (session_id,),
                ).fetchone()
                if stored is None:
                    connection.execute("ROLLBACK")
                    raise AgentControllerOwnershipError(
                        "agent_controller_ownership_storage_unavailable"
                    )
                result = self._ownership_record(stored, now=claimed_at)
                connection.execute("COMMIT")
                return result
        except AgentControllerOwnershipError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise AgentControllerOwnershipError(
                "agent_controller_ownership_storage_unavailable"
            ) from None

    def get_controller_ownership(
        self,
        session_id: str,
        *,
        now: datetime,
    ) -> AgentControllerOwnership | None:
        try:
            with self._database.connect() as connection:
                row = connection.execute(
                    _AGENT_CONTROLLER_OWNERSHIP_SELECT
                    + " WHERE ownership.session_id=?",
                    (session_id,),
                ).fetchone()
            return None if row is None else self._ownership_record(row, now=now)
        except (AgentCatalogError, sqlite3.Error):
            raise AgentControllerOwnershipError(
                "agent_controller_ownership_storage_unavailable"
            ) from None

    def list_controller_ownerships(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> tuple[AgentControllerOwnership, ...]:
        try:
            with self._database.connect() as connection:
                rows = connection.execute(
                    _AGENT_CONTROLLER_OWNERSHIP_SELECT
                    + " ORDER BY ownership.updated_at DESC, ownership.session_id LIMIT ?",
                    (limit,),
                ).fetchall()
            return tuple(self._ownership_record(row, now=now) for row in rows)
        except (AgentCatalogError, sqlite3.Error):
            raise AgentControllerOwnershipError(
                "agent_controller_ownership_storage_unavailable"
            ) from None

    def update_controller_ownership(
        self,
        session_id: str,
        *,
        owner_connection_id: str,
        state: AgentControllerOwnershipState,
        cursor: int,
        last_seq: int,
        approval_pending: bool,
        updated_at: datetime,
    ) -> AgentControllerOwnership:
        if cursor > last_seq:
            raise AgentControllerOwnershipError(
                "agent_controller_ownership_evidence_invalid"
            )
        try:
            with self._write_lock, self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                changed = connection.execute(
                    """
                    UPDATE agent_controller_ownerships
                    SET state=?,cursor=?,last_seq=?,approval_pending=?,
                        updated_at=?,revision=revision+1
                    WHERE session_id=? AND owner_connection_id=? AND state!='revoked'
                    """,
                    (
                        state,
                        cursor,
                        last_seq,
                        int(approval_pending),
                        _iso(updated_at),
                        session_id,
                        owner_connection_id,
                    ),
                ).rowcount
                if changed != 1:
                    current = connection.execute(
                        "SELECT owner_connection_id,state FROM agent_controller_ownerships WHERE session_id=?",
                        (session_id,),
                    ).fetchone()
                    connection.execute("ROLLBACK")
                    if current is None:
                        raise AgentControllerOwnershipError(
                            "agent_controller_ownership_not_found"
                        )
                    if str(current["owner_connection_id"]) != owner_connection_id:
                        raise AgentControllerOwnershipError(
                            "agent_controller_session_owned"
                        )
                    raise AgentControllerOwnershipError(
                        "agent_controller_connection_inactive"
                    )
                stored = connection.execute(
                    _AGENT_CONTROLLER_OWNERSHIP_SELECT
                    + " WHERE ownership.session_id=?",
                    (session_id,),
                ).fetchone()
                assert stored is not None
                result = self._ownership_record(stored, now=updated_at)
                connection.execute("COMMIT")
                return result
        except AgentControllerOwnershipError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise AgentControllerOwnershipError(
                "agent_controller_ownership_storage_unavailable"
            ) from None

    def reconcile_controller_ownerships_after_restart(
        self,
        *,
        live_session_ids: Sequence[str],
        reconciled_at: datetime,
    ) -> AgentControllerRestartReconciliationReceipt:
        live = frozenset(live_session_ids)
        if (
            len(live) != len(live_session_ids)
            or len(live) > 128
            or any(
                len(session_id) != 32
                or any(character not in "0123456789abcdef" for character in session_id)
                for session_id in live
            )
            or reconciled_at.tzinfo is None
            or reconciled_at.utcoffset() is None
        ):
            raise AgentControllerOwnershipError(
                "agent_controller_restart_reconciliation_invalid"
            )
        submission_states = {
            "claimed",
            "running",
            "waiting_native_approval",
            "reconnecting",
            "submission_uncertain",
        }
        cleanup_states = {
            "stopping",
            "stop_uncertain",
            "cleanup_unconfirmed",
        }
        try:
            with self._write_lock, self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                rows = connection.execute(
                    """
                    SELECT session_id,state,approval_pending,revision,
                           handoff_target_connection_id,handoff_offered_at,
                           handoff_expires_at
                    FROM agent_controller_ownerships
                    ORDER BY session_id
                    """
                ).fetchall()
                preserved = submission_uncertain = cleanup_unconfirmed = revoked = 0
                changed = approvals_cleared = handoffs_cleared = 0
                for row in rows:
                    session_id = str(row["session_id"])
                    if session_id in live:
                        preserved += 1
                        continue
                    state = str(row["state"])
                    if state in submission_states:
                        target_state = "submission_uncertain"
                        submission_uncertain += 1
                    elif state in cleanup_states:
                        target_state = "cleanup_unconfirmed"
                        cleanup_unconfirmed += 1
                    elif state == "revoked":
                        target_state = "revoked"
                        revoked += 1
                    else:
                        connection.execute("ROLLBACK")
                        raise AgentControllerOwnershipError(
                            "agent_controller_ownership_storage_corrupt"
                        )
                    approval_pending = bool(row["approval_pending"])
                    handoff_present = any(
                        row[column] is not None
                        for column in (
                            "handoff_target_connection_id",
                            "handoff_offered_at",
                            "handoff_expires_at",
                        )
                    )
                    approvals_cleared += int(approval_pending)
                    handoffs_cleared += int(handoff_present)
                    if (
                        state == target_state
                        and not approval_pending
                        and not handoff_present
                    ):
                        continue
                    updated = connection.execute(
                        """
                        UPDATE agent_controller_ownerships
                        SET state=?,approval_pending=0,updated_at=?,revision=revision+1,
                            handoff_target_connection_id=NULL,
                            handoff_offered_at=NULL,handoff_expires_at=NULL
                        WHERE session_id=? AND revision=?
                        """,
                        (
                            target_state,
                            _iso(reconciled_at),
                            session_id,
                            int(row["revision"]),
                        ),
                    ).rowcount
                    if updated != 1:
                        connection.execute("ROLLBACK")
                        raise AgentControllerOwnershipError(
                            "agent_controller_restart_reconciliation_conflict"
                        )
                    changed += 1
                receipt = AgentControllerRestartReconciliationReceipt(
                    reconciled_at=reconciled_at,
                    observed_ownerships=len(rows),
                    live_ownerships_preserved=preserved,
                    non_live_submission_uncertain=submission_uncertain,
                    non_live_cleanup_unconfirmed=cleanup_unconfirmed,
                    non_live_revoked=revoked,
                    changed_ownerships=changed,
                    native_approvals_cleared=approvals_cleared,
                    handoffs_cleared=handoffs_cleared,
                )
                connection.execute("COMMIT")
                return receipt
        except AgentControllerOwnershipError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise AgentControllerOwnershipError(
                "agent_controller_restart_reconciliation_unavailable"
            ) from None

    def offer_controller_handoff(
        self,
        session_id: str,
        *,
        owner_connection_id: str,
        target_connection_id: str,
        expected_revision: int,
        offered_at: datetime,
        expires_at: datetime,
    ) -> AgentControllerOwnership:
        if owner_connection_id == target_connection_id:
            raise AgentControllerOwnershipError(
                "agent_controller_handoff_target_invalid"
            )
        try:
            with self._write_lock, self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    "SELECT * FROM agent_controller_ownerships WHERE session_id=?",
                    (session_id,),
                ).fetchone()
                if current is None:
                    connection.execute("ROLLBACK")
                    raise AgentControllerOwnershipError(
                        "agent_controller_ownership_not_found"
                    )
                if str(current["owner_connection_id"]) != owner_connection_id:
                    connection.execute("ROLLBACK")
                    raise AgentControllerOwnershipError(
                        "agent_controller_session_owned"
                    )
                if int(current["revision"]) != expected_revision:
                    connection.execute("ROLLBACK")
                    raise AgentControllerOwnershipError(
                        "agent_controller_ownership_revision_conflict"
                    )
                if str(current["state"]) == "revoked":
                    connection.execute("ROLLBACK")
                    raise AgentControllerOwnershipError(
                        "agent_controller_connection_inactive"
                    )
                target = connection.execute(
                    """
                    SELECT scope_project_id,revoked_at,expires_at
                    FROM agent_mcp_connections WHERE connection_id=?
                    """,
                    (target_connection_id,),
                ).fetchone()
                if (
                    target is None
                    or target["revoked_at"] is not None
                    or _time(str(target["expires_at"])) <= offered_at
                    or str(target["scope_project_id"] or "")
                    != str(current["project_id"])
                ):
                    connection.execute("ROLLBACK")
                    raise AgentControllerOwnershipError(
                        "agent_controller_handoff_target_invalid"
                    )
                connection.execute(
                    """
                    UPDATE agent_controller_ownerships
                    SET handoff_target_connection_id=?,handoff_offered_at=?,
                        handoff_expires_at=?,updated_at=?,revision=revision+1
                    WHERE session_id=?
                    """,
                    (
                        target_connection_id,
                        _iso(offered_at),
                        _iso(expires_at),
                        _iso(offered_at),
                        session_id,
                    ),
                )
                stored = connection.execute(
                    _AGENT_CONTROLLER_OWNERSHIP_SELECT
                    + " WHERE ownership.session_id=?",
                    (session_id,),
                ).fetchone()
                assert stored is not None
                result = self._ownership_record(stored, now=offered_at)
                connection.execute("COMMIT")
                return result
        except AgentControllerOwnershipError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise AgentControllerOwnershipError(
                "agent_controller_ownership_storage_unavailable"
            ) from None

    def accept_controller_handoff(
        self,
        session_id: str,
        *,
        target_connection_id: str,
        expected_revision: int,
        accepted_at: datetime,
    ) -> AgentControllerOwnership:
        try:
            with self._write_lock, self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    "SELECT * FROM agent_controller_ownerships WHERE session_id=?",
                    (session_id,),
                ).fetchone()
                if current is None:
                    connection.execute("ROLLBACK")
                    raise AgentControllerOwnershipError(
                        "agent_controller_ownership_not_found"
                    )
                if int(current["revision"]) != expected_revision:
                    connection.execute("ROLLBACK")
                    raise AgentControllerOwnershipError(
                        "agent_controller_ownership_revision_conflict"
                    )
                if (
                    str(current["handoff_target_connection_id"] or "")
                    != target_connection_id
                ):
                    connection.execute("ROLLBACK")
                    raise AgentControllerOwnershipError(
                        "agent_controller_handoff_not_target"
                    )
                if (
                    current["handoff_expires_at"] is None
                    or _time(str(current["handoff_expires_at"])) <= accepted_at
                ):
                    connection.execute("ROLLBACK")
                    raise AgentControllerOwnershipError(
                        "agent_controller_handoff_expired"
                    )
                participants = connection.execute(
                    """
                    SELECT connection_id,scope_project_id,revoked_at,expires_at
                    FROM agent_mcp_connections
                    WHERE connection_id IN (?,?)
                    """,
                    (
                        str(current["owner_connection_id"]),
                        target_connection_id,
                    ),
                ).fetchall()
                if len(participants) != 2 or any(
                    row["revoked_at"] is not None
                    or _time(str(row["expires_at"])) <= accepted_at
                    or str(row["scope_project_id"] or "")
                    != str(current["project_id"])
                    for row in participants
                ):
                    connection.execute("ROLLBACK")
                    raise AgentControllerOwnershipError(
                        "agent_controller_handoff_unavailable"
                    )
                connection.execute(
                    """
                    UPDATE agent_controller_ownerships
                    SET owner_connection_id=?,owner_since=?,updated_at=?,
                        revision=revision+1,handoff_target_connection_id=NULL,
                        handoff_offered_at=NULL,handoff_expires_at=NULL
                    WHERE session_id=?
                    """,
                    (
                        target_connection_id,
                        _iso(accepted_at),
                        _iso(accepted_at),
                        session_id,
                    ),
                )
                stored = connection.execute(
                    _AGENT_CONTROLLER_OWNERSHIP_SELECT
                    + " WHERE ownership.session_id=?",
                    (session_id,),
                ).fetchone()
                assert stored is not None
                result = self._ownership_record(stored, now=accepted_at)
                connection.execute("COMMIT")
                return result
        except AgentControllerOwnershipError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise AgentControllerOwnershipError(
                "agent_controller_ownership_storage_unavailable"
            ) from None

    def release_controller_ownership(
        self,
        session_id: str,
        *,
        owner_connection_id: str | None,
        expected_revision: int | None,
        released_at: datetime,
        released_by: Literal["owner", "native"],
    ) -> AgentControllerOwnershipReleaseReceipt:
        try:
            with self._write_lock, self._database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    "SELECT * FROM agent_controller_ownerships WHERE session_id=?",
                    (session_id,),
                ).fetchone()
                if current is None:
                    connection.execute("ROLLBACK")
                    raise AgentControllerOwnershipError(
                        "agent_controller_ownership_not_found"
                    )
                if (
                    owner_connection_id is not None
                    and str(current["owner_connection_id"]) != owner_connection_id
                ):
                    connection.execute("ROLLBACK")
                    raise AgentControllerOwnershipError(
                        "agent_controller_session_owned"
                    )
                if (
                    expected_revision is not None
                    and int(current["revision"]) != expected_revision
                ):
                    connection.execute("ROLLBACK")
                    raise AgentControllerOwnershipError(
                        "agent_controller_ownership_revision_conflict"
                    )
                receipt = AgentControllerOwnershipReleaseReceipt(
                    project_id=str(current["project_id"]),
                    session_id=str(current["session_id"]),
                    released_connection_id=str(current["owner_connection_id"]),
                    released_revision=int(current["revision"]),
                    released_at=released_at,
                    released_by=released_by,
                )
                connection.execute(
                    "DELETE FROM agent_controller_ownerships WHERE session_id=?",
                    (session_id,),
                )
                connection.execute("COMMIT")
                return receipt
        except AgentControllerOwnershipError:
            raise
        except (AgentCatalogError, sqlite3.Error):
            raise AgentControllerOwnershipError(
                "agent_controller_ownership_storage_unavailable"
            ) from None


__all__ = (
    "AGENT_CATALOG_DATABASE_FILENAME",
    "AGENT_CATALOG_SCHEMA_VERSION",
    "AgentCatalogSqliteDatabase",
    "SqliteAgentCatalogRepository",
    "SqliteAgentMcpConnectionRepository",
)
