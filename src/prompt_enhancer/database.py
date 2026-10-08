"""Private, local SQLite persistence for metadata-only analytics.

Only ``SafeSession`` and ``SafeEvent`` values can enter this module.  Provider
identifiers and conversation content have no persistence API here.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import secrets
import sqlite3
import threading
from typing import TYPE_CHECKING, Iterable, Iterator

if TYPE_CHECKING:
    from .infrastructure.identifiers import LocalArtifactIdFactory

from .application.persistence import PersistenceConflictError
from .application.display_labels import (
    HOOK_ADAPTER_VERSION_PREFIX,
    INDEXED_LABEL_PROVENANCE,
    DisplayLabelConflictError,
    DisplayLabelNotFoundError,
    LabelEntityKind,
    LabelObservationMethod,
    LabelTarget,
    LabelTargetBatch,
    LabelWriteResult,
    ManualDisplayLabelResult,
    ProviderDisplayLabelObservation,
    ProviderLabelSource,
)
from .application.analysis.project_quality_aggregation import (
    IndexedProjectQualitySnapshot,
    IndexedProjectSessions,
    ProjectQualitySelectionIncompleteError,
    ProjectQualitySelectionLimitError,
)
from .config import lexical_absolute_path, path_has_symlink_component
from .domain import (
    PSEUDONYM_PATTERN,
    SAFE_VERSION_PATTERN,
    DataTier,
    EventKind,
    EventTimeBasis,
    MetricObservation,
    MetricSource,
    Provider,
    SafeEvent,
    SafeSession,
    SessionState,
    ToolCategory,
    UsageCounterKind,
    UsageRecord,
    UsageScope,
)
from .metrics import (
    METRIC_DEFINITIONS,
    MetricDefinition,
    NOT_APPLICABLE_VERSION,
    metric_engine_version_for_definition,
)
from .infrastructure.sqlite.migrations import (
    MIGRATION_2,
    MIGRATION_3,
    MIGRATION_4,
    MIGRATION_5,
    MIGRATION_6,
    MIGRATION_7,
    MIGRATION_8,
    MIGRATION_9,
    MIGRATION_10,
    MIGRATION_11,
    MIGRATION_12,
    MIGRATION_13,
    MIGRATION_14,
    MIGRATION_15,
    MIGRATION_16,
    MIGRATION_17,
    MIGRATION_18,
    MIGRATION_19,
    MIGRATION_20,
    MIGRATION_21,
    MIGRATION_22,
    MIGRATION_23,
    MIGRATION_24,
    MIGRATION_25,
    MIGRATION_26,
    MIGRATION_27,
    MIGRATION_28,
    MIGRATION_29,
    MIGRATION_30,
    MIGRATION_31,
    MIGRATION_32,
    MIGRATION_33,
    MIGRATION_34,
    MIGRATION_35,
    MIGRATION_36,
    MIGRATION_37,
    MIGRATION_38,
    MIGRATION_39,
    MIGRATION_40,
    MIGRATION_41,
    MIGRATION_42,
    MIGRATION_43,
    MIGRATION_44,
    MIGRATION_45,
    MIGRATION_46,
    MIGRATION_47,
    MIGRATION_48,
    MIGRATION_49,
    MIGRATION_50,
    MIGRATION_51,
    MIGRATION_52,
    MIGRATION_53,
    MIGRATION_54,
    MIGRATION_55,
    MIGRATION_56,
    MIGRATION_57,
    MIGRATION_58,
    MIGRATION_59,
    MIGRATION_60,
    MIGRATION_61,
)


SCHEMA_VERSION = 61
LOCAL_SOURCE_CONSENT_TIERS = frozenset(
    {DataTier.METADATA, DataTier.REDACTED_CONTENT}
)




class DatabaseError(RuntimeError):
    """A sanitized local persistence failure."""


class DatabaseInvariantError(DatabaseError, PersistenceConflictError):
    """A safe persistent identifier conflicted with existing provenance."""


@dataclass(frozen=True, slots=True)
class PersistResult:
    session_inserted: int = 0
    session_updated: int = 0
    events_inserted: int = 0
    events_updated: int = 0


_MIGRATION_1 = r"""
CREATE TABLE IF NOT EXISTS installations (
    installation_id TEXT PRIMARY KEY
        CHECK(length(installation_id) = 64 AND installation_id NOT GLOB '*[^0-9a-f]*'),
    provider TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY
        CHECK(length(project_id) = 64 AND project_id NOT GLOB '*[^0-9a-f]*'),
    installation_id TEXT NOT NULL REFERENCES installations(installation_id),
    provider TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY
        CHECK(length(session_id) = 64 AND session_id NOT GLOB '*[^0-9a-f]*'),
    installation_id TEXT NOT NULL REFERENCES installations(installation_id),
    project_id TEXT NOT NULL REFERENCES projects(project_id),
    provider TEXT NOT NULL,
    provider_version TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    source_schema_version TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    terminal_state TEXT NOT NULL,
    events_complete INTEGER NOT NULL CHECK(events_complete IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_started_at_idx ON sessions(started_at DESC);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY
        CHECK(length(event_id) = 64 AND event_id NOT GLOB '*[^0-9a-f]*'),
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence >= 0),
    occurred_at TEXT NOT NULL,
    duration_ms INTEGER CHECK(duration_ms IS NULL OR duration_ms >= 0),
    success INTEGER CHECK(success IS NULL OR success IN (0, 1)),
    tool_category TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(session_id, sequence)
);
CREATE INDEX IF NOT EXISTS events_session_idx ON events(session_id, sequence);

CREATE TABLE IF NOT EXISTS usage_records (
    event_id TEXT PRIMARY KEY REFERENCES events(event_id) ON DELETE CASCADE,
    input_tokens INTEGER CHECK(input_tokens IS NULL OR input_tokens >= 0),
    cached_input_tokens INTEGER CHECK(cached_input_tokens IS NULL OR cached_input_tokens >= 0),
    cache_creation_tokens INTEGER CHECK(cache_creation_tokens IS NULL OR cache_creation_tokens >= 0),
    output_tokens INTEGER CHECK(output_tokens IS NULL OR output_tokens >= 0),
    reasoning_output_tokens INTEGER CHECK(reasoning_output_tokens IS NULL OR reasoning_output_tokens >= 0),
    total_tokens INTEGER CHECK(total_tokens IS NULL OR total_tokens >= 0),
    model_id TEXT,
    provider_reported INTEGER NOT NULL CHECK(provider_reported IN (0, 1))
);

CREATE TABLE IF NOT EXISTS metric_definitions (
    key TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version >= 1),
    dimension TEXT NOT NULL,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL,
    unit TEXT NOT NULL,
    source TEXT NOT NULL,
    algorithm_version TEXT NOT NULL,
    definition_checksum TEXT NOT NULL,
    PRIMARY KEY(key, version)
);

CREATE TABLE IF NOT EXISTS metric_results (
    session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    version INTEGER NOT NULL,
    numeric_value REAL,
    text_value TEXT,
    unit TEXT NOT NULL,
    source TEXT NOT NULL,
    observed_count INTEGER NOT NULL CHECK(observed_count >= 0),
    eligible_count INTEGER NOT NULL CHECK(eligible_count >= 0),
    coverage REAL NOT NULL CHECK(coverage >= 0 AND coverage <= 1),
    confidence REAL CHECK(confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    metric_engine_version TEXT NOT NULL,
    redactor_version TEXT NOT NULL,
    model_id TEXT,
    model_revision TEXT,
    tokenizer_id TEXT,
    prompt_version TEXT,
    rubric_version TEXT,
    computed_at TEXT NOT NULL,
    CHECK(NOT (numeric_value IS NOT NULL AND text_value IS NOT NULL)),
    CHECK(observed_count <= eligible_count),
    PRIMARY KEY(session_id, key, version),
    FOREIGN KEY(key, version) REFERENCES metric_definitions(key, version)
);
CREATE INDEX IF NOT EXISTS metric_results_session_idx ON metric_results(session_id);

CREATE TABLE IF NOT EXISTS consent_grants (
    provider TEXT NOT NULL,
    data_tier TEXT NOT NULL,
    consent_schema_version TEXT NOT NULL,
    granted_at TEXT NOT NULL,
    revoked_at TEXT,
    PRIMARY KEY(provider, data_tier)
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    provider_version TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    source_schema_version TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    data_tier TEXT NOT NULL,
    redactor_version TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed')),
    sessions_seen INTEGER NOT NULL DEFAULT 0,
    events_seen INTEGER NOT NULL DEFAULT 0,
    metrics_written INTEGER NOT NULL DEFAULT 0,
    error_code TEXT
);
"""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _parse_time(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value).astimezone(UTC)


def _definition_checksum(definition: MetricDefinition) -> str:
    payload = json.dumps(
        definition.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _migration_body(script: str) -> str:
    """Remove only a migration's outer transaction without changing its checksum."""

    stripped = script.strip()
    for prefix in ("BEGIN IMMEDIATE;", "BEGIN;"):
        if stripped.startswith(prefix):
            if not stripped.endswith("COMMIT;"):
                raise DatabaseInvariantError(
                    "database migration transaction boundary is incomplete"
                )
            body = stripped[len(prefix) : -len("COMMIT;")].strip()
            if re.search(
                r"(?im)^\s*(?:BEGIN(?:\s+(?:DEFERRED|IMMEDIATE|EXCLUSIVE))?|"
                r"COMMIT|END\s+TRANSACTION|ROLLBACK|SAVEPOINT|RELEASE)\s*;",
                body,
            ):
                raise DatabaseInvariantError(
                    "database migration contains a nested transaction boundary"
                )
            return body
    if stripped.endswith("COMMIT;"):
        raise DatabaseInvariantError("database migration transaction is malformed")
    return stripped


def _temporal_safe_code(value: object) -> int:
    return int(
        isinstance(value, str)
        and re.fullmatch(r"[a-z][a-z0-9._-]{0,127}", value) is not None
    )


def _temporal_safe_version(value: object) -> int:
    return int(
        isinstance(value, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", value) is not None
        and ".." not in value
    )


def _temporal_real_is_canonical(value: object) -> int:
    return int(
        isinstance(value, float)
        and math.isfinite(value)
        and not (value == 0.0 and math.copysign(1.0, value) < 0.0)
    )


def _temporal_iso_to_epoch_us(value: object) -> int | None:
    """Parse the repository's canonical UTC ISO format for SQL parity checks."""

    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        return None
    canonical = parsed.astimezone(UTC).isoformat(timespec="microseconds")
    if canonical != value:
        return None
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = parsed - epoch
    return (
        delta.days * 86_400_000_000
        + delta.seconds * 1_000_000
        + delta.microseconds
    )


def _apply_migration_atomically(
    connection: sqlite3.Connection,
    *,
    version: int,
    script: str,
    checksum: str,
    applied_at: str,
) -> None:
    """Commit schema, checksum ledger, and user_version as one SQLite unit."""

    if not (1 <= version <= SCHEMA_VERSION):
        raise DatabaseInvariantError("database migration version is invalid")
    if len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum):
        raise DatabaseInvariantError("database migration checksum is invalid")
    if "'" in applied_at:
        raise DatabaseInvariantError("database migration timestamp is invalid")
    body = _migration_body(script)
    transaction = f"""
BEGIN IMMEDIATE;
{body}
INSERT INTO schema_migrations(version, checksum, applied_at)
VALUES ({version}, '{checksum}', '{applied_at}');
PRAGMA user_version = {version};
COMMIT;
"""
    try:
        connection.executescript(transaction)
    except sqlite3.Error:
        connection.rollback()
        raise


class Database:
    """Small, parameterized persistence API with no arbitrary-SQL surface."""

    def __init__(self, path: Path):
        self.path = lexical_absolute_path(Path(path))
        self._initialized = False
        self._estimator_evidence_authorization_secret = secrets.token_bytes(32)
        self._estimator_evidence_authorizations: set[
            tuple[str, str, str, str]
        ] = set()
        self._estimator_evidence_delete_authorizations: set[
            tuple[str, str, str]
        ] = set()
        self._estimator_evidence_authorization_lock = threading.Lock()
        self._estimator_runtime_authorization_secret = secrets.token_bytes(32)
        self._estimator_runtime_authorizations: set[
            tuple[str, str, str, str, str]
        ] = set()
        self._estimator_runtime_authorization_lock = threading.Lock()
        self._automation_publication_authorization_secret = secrets.token_bytes(32)
        self._automation_publication_authorizations: set[
            tuple[str, str, str, str]
        ] = set()
        self._automation_publication_authorization_lock = threading.Lock()
        self._estimator_calibration_report_authorization_secret = (
            secrets.token_bytes(32)
        )
        self._estimator_calibration_report_authorizations: set[
            tuple[str, str, str, str, str]
        ] = set()
        self._estimator_calibration_report_authorization_lock = threading.Lock()
        self._estimator_gate_decision_authorization_secret = secrets.token_bytes(32)
        self._estimator_gate_decision_authorizations: set[
            tuple[str, str, str, str, str]
        ] = set()
        self._estimator_gate_decision_authorization_lock = threading.Lock()
        self._temporal_scope_authorization_secret = secrets.token_bytes(32)
        self._temporal_scope_authorizations: set[
            tuple[object, ...]
        ] = set()
        self._temporal_scope_authorization_lock = threading.Lock()
        self._temporal_history_authorization_secret = secrets.token_bytes(32)
        self._temporal_history_authorizations: set[
            tuple[object, ...]
        ] = set()
        self._temporal_history_authorization_lock = threading.Lock()
        self._temporal_run_delete_authorization_secret = secrets.token_bytes(32)
        self._temporal_run_delete_authorizations: set[
            tuple[str, str, str]
        ] = set()
        self._temporal_run_delete_authorization_lock = threading.Lock()
        self._comparison_prepare_authorization_secret = secrets.token_bytes(32)
        self._comparison_prepare_authorizations: set[tuple[object, ...]] = set()
        self._comparison_prepare_authorization_lock = threading.Lock()
        self._comparison_seal_authorization_secret = secrets.token_bytes(32)
        self._comparison_seal_authorizations: set[tuple[object, ...]] = set()
        self._comparison_seal_authorization_lock = threading.Lock()
        self._comparison_task_delete_authorization_secret = secrets.token_bytes(32)
        self._comparison_task_delete_authorizations: set[tuple[object, ...]] = set()
        self._comparison_task_delete_authorization_lock = threading.Lock()
        self._synthetic_aggregation_append_authorization_secret = (
            secrets.token_bytes(32)
        )
        self._synthetic_aggregation_append_authorizations: set[
            tuple[object, ...]
        ] = set()
        self._synthetic_aggregation_append_authorization_lock = threading.Lock()
        self._synthetic_aggregation_delete_authorization_secret = (
            secrets.token_bytes(32)
        )
        self._synthetic_aggregation_delete_authorizations: set[
            tuple[object, ...]
        ] = set()
        self._synthetic_aggregation_delete_authorization_lock = threading.Lock()
        self._local_artifact_id_factory: LocalArtifactIdFactory | None = None
        self._initialization_lock = threading.Lock()

    def configure_local_artifact_id_factory(
        self,
        factory: LocalArtifactIdFactory,
    ) -> None:
        """Install the process-local keyed artifact issuer exactly once."""

        from .infrastructure.identifiers import LocalArtifactIdFactory

        if not isinstance(factory, LocalArtifactIdFactory):
            raise TypeError("local artifact ID factory is invalid")
        if self._local_artifact_id_factory is not None:
            if self._local_artifact_id_factory is factory:
                return
            raise DatabaseInvariantError(
                "local artifact ID factory is already configured"
            )
        self._local_artifact_id_factory = factory

    @staticmethod
    def _authorization_lookup(
        values: tuple[object, ...],
        *,
        active: set[tuple[object, ...]],
        lock: threading.Lock,
        exact_length: int,
    ) -> str:
        with lock:
            if len(values) == exact_length:
                match = next(
                    (item for item in active if item[:-1] == values),
                    None,
                )
            elif len(values) == 2:
                operation_id, authorization_fingerprint = values
                match = next(
                    (
                        item
                        for item in active
                        if item[0] == operation_id
                        and item[-2] == authorization_fingerprint
                    ),
                    None,
                )
            else:
                match = None
        return "" if match is None else str(match[-1])

    def _comparison_prepare_authorization_tag(self, *values: object) -> str:
        return self._authorization_lookup(
            values,
            active=self._comparison_prepare_authorizations,
            lock=self._comparison_prepare_authorization_lock,
            exact_length=9,
        )

    def _begin_comparison_prepare_authorization(
        self,
        job_id: str,
        grant_id: str,
        prepared_scope_id: str,
        prepared_stratum_id: str,
        expected_run_id: str,
        bridge_fingerprint: str,
        prepared_fingerprint: str,
        authorization_fingerprint: str,
    ) -> tuple[str, str]:
        operation_id = secrets.token_hex(32)
        lineage: tuple[object, ...] = (
            operation_id,
            job_id,
            grant_id,
            prepared_scope_id,
            prepared_stratum_id,
            expected_run_id,
            bridge_fingerprint,
            prepared_fingerprint,
            authorization_fingerprint,
        )
        tag = hmac.new(
            self._comparison_prepare_authorization_secret,
            json.dumps(
                ("comparison-prepare-write-v1", *lineage),
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("ascii", errors="strict"),
            hashlib.sha256,
        ).hexdigest()
        with self._comparison_prepare_authorization_lock:
            self._comparison_prepare_authorizations.add((*lineage, tag))
        return operation_id, tag

    def _end_comparison_prepare_authorization(
        self,
        operation_id: str,
        authorization_fingerprint: str,
        tag: str,
    ) -> None:
        with self._comparison_prepare_authorization_lock:
            matches = {
                item
                for item in self._comparison_prepare_authorizations
                if item[0] == operation_id
                and item[-2] == authorization_fingerprint
                and item[-1] == tag
            }
            self._comparison_prepare_authorizations.difference_update(matches)

    def _comparison_seal_authorization_tag(self, *values: object) -> str:
        return self._authorization_lookup(
            values,
            active=self._comparison_seal_authorizations,
            lock=self._comparison_seal_authorization_lock,
            exact_length=11,
        )

    def _begin_comparison_seal_authorization(
        self,
        prepared_stratum_id: str,
        analysis_run_id: str,
        sealed_batch_id: str,
        sealed_stratum_id: str,
        prepared_fingerprint: str,
        run_authority_fingerprint: str,
        sealed_batch_fingerprint: str,
        revalidation_fingerprint: str,
        sealed_fingerprint: str,
        authorization_fingerprint: str,
    ) -> tuple[str, str]:
        operation_id = secrets.token_hex(32)
        lineage: tuple[object, ...] = (
            operation_id,
            prepared_stratum_id,
            analysis_run_id,
            sealed_batch_id,
            sealed_stratum_id,
            prepared_fingerprint,
            run_authority_fingerprint,
            sealed_batch_fingerprint,
            revalidation_fingerprint,
            sealed_fingerprint,
            authorization_fingerprint,
        )
        tag = hmac.new(
            self._comparison_seal_authorization_secret,
            json.dumps(
                ("comparison-seal-write-v1", *lineage),
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("ascii", errors="strict"),
            hashlib.sha256,
        ).hexdigest()
        with self._comparison_seal_authorization_lock:
            self._comparison_seal_authorizations.add((*lineage, tag))
        return operation_id, tag

    def _end_comparison_seal_authorization(
        self,
        operation_id: str,
        authorization_fingerprint: str,
        tag: str,
    ) -> None:
        with self._comparison_seal_authorization_lock:
            matches = {
                item
                for item in self._comparison_seal_authorizations
                if item[0] == operation_id
                and item[-2] == authorization_fingerprint
                and item[-1] == tag
            }
            self._comparison_seal_authorizations.difference_update(matches)

    def _comparison_task_delete_authorization_tag(self, *values: object) -> str:
        return self._authorization_lookup(
            values,
            active=self._comparison_task_delete_authorizations,
            lock=self._comparison_task_delete_authorization_lock,
            exact_length=6,
        )

    def _begin_comparison_task_delete_authorization(
        self,
        task_id: str,
        prepared_stratum_id: str,
        expected_run_id: str,
        sealed_stratum_id: str | None,
        authorization_fingerprint: str,
    ) -> tuple[str, str]:
        operation_id = secrets.token_hex(32)
        lineage: tuple[object, ...] = (
            operation_id,
            task_id,
            prepared_stratum_id,
            expected_run_id,
            sealed_stratum_id,
            authorization_fingerprint,
        )
        tag = hmac.new(
            self._comparison_task_delete_authorization_secret,
            json.dumps(
                ("comparison-task-delete-v1", *lineage),
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("ascii", errors="strict"),
            hashlib.sha256,
        ).hexdigest()
        with self._comparison_task_delete_authorization_lock:
            self._comparison_task_delete_authorizations.add((*lineage, tag))
        return operation_id, tag

    def _end_comparison_task_delete_authorization(
        self,
        operation_id: str,
        authorization_fingerprint: str,
        tag: str,
    ) -> None:
        with self._comparison_task_delete_authorization_lock:
            matches = {
                item
                for item in self._comparison_task_delete_authorizations
                if item[0] == operation_id
                and item[-2] == authorization_fingerprint
                and item[-1] == tag
            }
            self._comparison_task_delete_authorizations.difference_update(matches)

    def _synthetic_aggregation_append_authorization_tag(
        self,
        *values: object,
    ) -> str:
        return self._authorization_lookup(
            values,
            active=self._synthetic_aggregation_append_authorizations,
            lock=self._synthetic_aggregation_append_authorization_lock,
            exact_length=17,
        )

    def _begin_synthetic_aggregation_append_authorization(
        self,
        validation_receipt_id: str,
        idempotency_key_sha256: str,
        request_fingerprint: str,
        anchor_sealed_stratum_id: str,
        query_id: str,
        predicate_fingerprint: str,
        enumeration_id: str,
        enumeration_fingerprint: str,
        aggregation_draft_id: str,
        aggregation_draft_fingerprint: str,
        validation_fingerprint: str,
        member_count: int,
        graph_fingerprint_count: int,
        as_of_us: int,
        sealed_at_us: int,
        authorization_fingerprint: str,
    ) -> tuple[str, str]:
        operation_id = secrets.token_hex(32)
        lineage: tuple[object, ...] = (
            operation_id,
            validation_receipt_id,
            idempotency_key_sha256,
            request_fingerprint,
            anchor_sealed_stratum_id,
            query_id,
            predicate_fingerprint,
            enumeration_id,
            enumeration_fingerprint,
            aggregation_draft_id,
            aggregation_draft_fingerprint,
            validation_fingerprint,
            member_count,
            graph_fingerprint_count,
            as_of_us,
            sealed_at_us,
            authorization_fingerprint,
        )
        tag = hmac.new(
            self._synthetic_aggregation_append_authorization_secret,
            json.dumps(
                ("synthetic-aggregation-append-v1", *lineage),
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("ascii", errors="strict"),
            hashlib.sha256,
        ).hexdigest()
        with self._synthetic_aggregation_append_authorization_lock:
            self._synthetic_aggregation_append_authorizations.add((*lineage, tag))
        return operation_id, tag

    def _end_synthetic_aggregation_append_authorization(
        self,
        operation_id: str,
        authorization_fingerprint: str,
        tag: str,
    ) -> None:
        with self._synthetic_aggregation_append_authorization_lock:
            matches = {
                item
                for item in self._synthetic_aggregation_append_authorizations
                if item[0] == operation_id
                and item[-2] == authorization_fingerprint
                and item[-1] == tag
            }
            self._synthetic_aggregation_append_authorizations.difference_update(
                matches
            )

    def _synthetic_aggregation_delete_authorization_tag(
        self,
        *values: object,
    ) -> str:
        return self._authorization_lookup(
            values,
            active=self._synthetic_aggregation_delete_authorizations,
            lock=self._synthetic_aggregation_delete_authorization_lock,
            exact_length=6,
        )

    def _begin_synthetic_aggregation_delete_authorization(
        self,
        operation_id: str,
        validation_receipt_id: str,
        cause_kind: str,
        cause_id: str,
        validation_fingerprint: str,
        authorization_fingerprint: str,
    ) -> str:
        if cause_kind == "run":
            with self._temporal_run_delete_authorization_lock:
                upstream_active = any(
                    item[0] == operation_id and item[1] == cause_id
                    for item in self._temporal_run_delete_authorizations
                )
        elif cause_kind == "task":
            with self._comparison_task_delete_authorization_lock:
                upstream_active = any(
                    item[0] == operation_id and item[1] == cause_id
                    for item in self._comparison_task_delete_authorizations
                )
        else:
            raise ValueError("synthetic aggregation deletion cause is invalid")
        if not upstream_active:
            raise DatabaseInvariantError(
                "synthetic aggregation deletion requires upstream privacy authority"
            )
        lineage: tuple[object, ...] = (
            operation_id,
            validation_receipt_id,
            cause_kind,
            cause_id,
            validation_fingerprint,
            authorization_fingerprint,
        )
        tag = hmac.new(
            self._synthetic_aggregation_delete_authorization_secret,
            json.dumps(
                ("synthetic-aggregation-delete-v1", *lineage),
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("ascii", errors="strict"),
            hashlib.sha256,
        ).hexdigest()
        with self._synthetic_aggregation_delete_authorization_lock:
            self._synthetic_aggregation_delete_authorizations.add((*lineage, tag))
        return tag

    def _end_synthetic_aggregation_delete_authorization(
        self,
        operation_id: str,
        authorization_fingerprint: str,
        tag: str,
    ) -> None:
        with self._synthetic_aggregation_delete_authorization_lock:
            matches = {
                item
                for item in self._synthetic_aggregation_delete_authorizations
                if item[0] == operation_id
                and item[-2] == authorization_fingerprint
                and item[-1] == tag
            }
            self._synthetic_aggregation_delete_authorizations.difference_update(
                matches
            )

    def _temporal_scope_authorization_tag(
        self,
        *values: object,
    ) -> str:
        with self._temporal_scope_authorization_lock:
            if len(values) == 12:
                match = next(
                    (
                        item
                        for item in self._temporal_scope_authorizations
                        if item[:-1] == values
                    ),
                    None,
                )
            elif len(values) == 2:
                operation_id, authorization_fingerprint = values
                match = next(
                    (
                        item
                        for item in self._temporal_scope_authorizations
                        if item[0] == operation_id
                        and item[-2] == authorization_fingerprint
                    ),
                    None,
                )
            else:
                match = None
        return "" if match is None else str(match[-1])

    def _begin_temporal_scope_authorization(
        self,
        automation_grant_id: str,
        automation_grant_revision: int,
        automation_grant_fingerprint: str,
        project_id: str,
        prepared_scope_id: str,
        prepared_scope_fingerprint: str,
        root_receipt_id: str,
        root_receipt_fingerprint: str,
        selection_revision_id: str,
        selection_revision_fingerprint: str,
        authorization_fingerprint: str,
    ) -> tuple[str, str]:
        operation_id = secrets.token_hex(32)
        lineage = (
            operation_id,
            automation_grant_id,
            automation_grant_revision,
            automation_grant_fingerprint,
            project_id,
            prepared_scope_id,
            prepared_scope_fingerprint,
            root_receipt_id,
            root_receipt_fingerprint,
            selection_revision_id,
            selection_revision_fingerprint,
            authorization_fingerprint,
        )
        tag = hmac.new(
            self._temporal_scope_authorization_secret,
            json.dumps(
                ("temporal-scope-write-v1", *lineage),
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("ascii", errors="strict"),
            hashlib.sha256,
        ).hexdigest()
        with self._temporal_scope_authorization_lock:
            self._temporal_scope_authorizations.add((*lineage, tag))
        return operation_id, tag

    def _end_temporal_scope_authorization(
        self,
        operation_id: str,
        authorization_fingerprint: str,
        tag: str,
    ) -> None:
        with self._temporal_scope_authorization_lock:
            matches = {
                item
                for item in self._temporal_scope_authorizations
                if item[0] == operation_id
                and item[-2] == authorization_fingerprint
                and item[-1] == tag
            }
            self._temporal_scope_authorizations.difference_update(matches)

    def _temporal_history_authorization_tag(
        self,
        *values: object,
    ) -> str:
        with self._temporal_history_authorization_lock:
            if len(values) == 20:
                match = next(
                    (
                        item
                        for item in self._temporal_history_authorizations
                        if item[:-1] == values
                    ),
                    None,
                )
            elif len(values) == 2:
                operation_id, authorization_fingerprint = values
                match = next(
                    (
                        item
                        for item in self._temporal_history_authorizations
                        if item[0] == operation_id
                        and item[-2] == authorization_fingerprint
                    ),
                    None,
                )
            else:
                match = None
        return "" if match is None else str(match[-1])

    def _begin_temporal_history_authorization(
        self,
        job_id: str,
        automation_grant_id: str,
        automation_grant_revision: int,
        automation_grant_fingerprint: str,
        analysis_run_id: str,
        analysis_run_fingerprint: str,
        root_receipt_id: str,
        root_receipt_fingerprint: str,
        selection_revision_id: str,
        selection_revision_fingerprint: str,
        prepared_scope_id: str,
        prepared_scope_fingerprint: str,
        completion_request_id: str,
        completion_request_fingerprint: str,
        seal_draft_id: str,
        seal_draft_fingerprint: str,
        sealed_batch_id: str,
        sealed_batch_fingerprint: str,
        authorization_fingerprint: str,
    ) -> tuple[str, str]:
        operation_id = secrets.token_hex(32)
        lineage = (
            operation_id,
            job_id,
            automation_grant_id,
            automation_grant_revision,
            automation_grant_fingerprint,
            analysis_run_id,
            analysis_run_fingerprint,
            root_receipt_id,
            root_receipt_fingerprint,
            selection_revision_id,
            selection_revision_fingerprint,
            prepared_scope_id,
            prepared_scope_fingerprint,
            completion_request_id,
            completion_request_fingerprint,
            seal_draft_id,
            seal_draft_fingerprint,
            sealed_batch_id,
            sealed_batch_fingerprint,
            authorization_fingerprint,
        )
        tag = hmac.new(
            self._temporal_history_authorization_secret,
            json.dumps(
                ("temporal-history-write-v1", *lineage),
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("ascii", errors="strict"),
            hashlib.sha256,
        ).hexdigest()
        with self._temporal_history_authorization_lock:
            self._temporal_history_authorizations.add((*lineage, tag))
        return operation_id, tag

    def _end_temporal_history_authorization(
        self,
        operation_id: str,
        authorization_fingerprint: str,
        tag: str,
    ) -> None:
        with self._temporal_history_authorization_lock:
            matches = {
                item
                for item in self._temporal_history_authorizations
                if item[0] == operation_id
                and item[-2] == authorization_fingerprint
                and item[-1] == tag
            }
            self._temporal_history_authorizations.difference_update(matches)

    def _temporal_run_delete_authorization_tag(
        self,
        operation_id: str,
        run_id: str,
    ) -> str:
        candidate = hmac.new(
            self._temporal_run_delete_authorization_secret,
            f"temporal-run-delete-v1:{operation_id}:{run_id}".encode(
                "ascii", errors="strict"
            ),
            hashlib.sha256,
        ).hexdigest()
        with self._temporal_run_delete_authorization_lock:
            active = (
                operation_id,
                run_id,
                candidate,
            ) in self._temporal_run_delete_authorizations
        return candidate if active else ""

    def _begin_temporal_run_delete_authorization(
        self,
        run_id: str,
    ) -> tuple[str, str]:
        operation_id = secrets.token_hex(32)
        tag = hmac.new(
            self._temporal_run_delete_authorization_secret,
            f"temporal-run-delete-v1:{operation_id}:{run_id}".encode(
                "ascii", errors="strict"
            ),
            hashlib.sha256,
        ).hexdigest()
        with self._temporal_run_delete_authorization_lock:
            self._temporal_run_delete_authorizations.add(
                (operation_id, run_id, tag)
            )
        return operation_id, tag

    def _end_temporal_run_delete_authorization(
        self,
        operation_id: str,
        run_id: str,
        tag: str,
    ) -> None:
        with self._temporal_run_delete_authorization_lock:
            self._temporal_run_delete_authorizations.discard(
                (operation_id, run_id, tag)
            )

    def _estimator_gate_decision_authorization_tag(
        self,
        operation_id: str,
        report_id: str,
        decision_id: str,
        job_id: str,
    ) -> str:
        candidate = hmac.new(
            self._estimator_gate_decision_authorization_secret,
            (
                "estimator-gate-decision-write-v1:"
                f"{operation_id}:{report_id}:{decision_id}:{job_id}"
            ).encode("ascii", errors="strict"),
            hashlib.sha256,
        ).hexdigest()
        with self._estimator_gate_decision_authorization_lock:
            active = (
                operation_id,
                report_id,
                decision_id,
                job_id,
                candidate,
            ) in self._estimator_gate_decision_authorizations
        return candidate if active else ""

    def _begin_estimator_gate_decision_authorization(
        self, report_id: str, decision_id: str, job_id: str
    ) -> tuple[str, str]:
        operation_id = secrets.token_hex(32)
        tag = hmac.new(
            self._estimator_gate_decision_authorization_secret,
            (
                "estimator-gate-decision-write-v1:"
                f"{operation_id}:{report_id}:{decision_id}:{job_id}"
            ).encode("ascii", errors="strict"),
            hashlib.sha256,
        ).hexdigest()
        with self._estimator_gate_decision_authorization_lock:
            self._estimator_gate_decision_authorizations.add(
                (operation_id, report_id, decision_id, job_id, tag)
            )
        return operation_id, tag

    def _end_estimator_gate_decision_authorization(
        self,
        operation_id: str,
        report_id: str,
        decision_id: str,
        job_id: str,
        tag: str,
    ) -> None:
        with self._estimator_gate_decision_authorization_lock:
            self._estimator_gate_decision_authorizations.discard(
                (operation_id, report_id, decision_id, job_id, tag)
            )

    def _estimator_calibration_report_authorization_tag(
        self,
        operation_id: str,
        report_id: str,
        submission_id: str,
        campaign_id: str,
    ) -> str:
        candidate = hmac.new(
            self._estimator_calibration_report_authorization_secret,
            (
                "estimator-calibration-report-write-v1:"
                f"{operation_id}:{report_id}:{submission_id}:{campaign_id}"
            ).encode("ascii", errors="strict"),
            hashlib.sha256,
        ).hexdigest()
        with self._estimator_calibration_report_authorization_lock:
            active = (
                operation_id,
                report_id,
                submission_id,
                campaign_id,
                candidate,
            ) in self._estimator_calibration_report_authorizations
        return candidate if active else ""

    def _begin_estimator_calibration_report_authorization(
        self, report_id: str, submission_id: str, campaign_id: str
    ) -> tuple[str, str]:
        operation_id = secrets.token_hex(32)
        tag = hmac.new(
            self._estimator_calibration_report_authorization_secret,
            (
                "estimator-calibration-report-write-v1:"
                f"{operation_id}:{report_id}:{submission_id}:{campaign_id}"
            ).encode("ascii", errors="strict"),
            hashlib.sha256,
        ).hexdigest()
        with self._estimator_calibration_report_authorization_lock:
            self._estimator_calibration_report_authorizations.add(
                (operation_id, report_id, submission_id, campaign_id, tag)
            )
        return operation_id, tag

    def _end_estimator_calibration_report_authorization(
        self,
        operation_id: str,
        report_id: str,
        submission_id: str,
        campaign_id: str,
        tag: str,
    ) -> None:
        with self._estimator_calibration_report_authorization_lock:
            self._estimator_calibration_report_authorizations.discard(
                (operation_id, report_id, submission_id, campaign_id, tag)
            )

    def _estimator_runtime_authorization_tag(
        self,
        operation_id: str,
        authorization_id: str,
        execution_id: str,
        job_id: str,
    ) -> str:
        candidate = hmac.new(
            self._estimator_runtime_authorization_secret,
            (
                "estimator-runtime-write-v2:"
                f"{operation_id}:{authorization_id}:{execution_id}:{job_id}"
            ).encode("ascii", errors="strict"),
            hashlib.sha256,
        ).hexdigest()
        with self._estimator_runtime_authorization_lock:
            active = (
                operation_id,
                authorization_id,
                execution_id,
                job_id,
                candidate,
            ) in self._estimator_runtime_authorizations
        return candidate if active else ""

    def _begin_estimator_runtime_authorization(
        self, authorization_id: str, execution_id: str, job_id: str
    ) -> tuple[str, str]:
        operation_id = secrets.token_hex(32)
        tag = hmac.new(
            self._estimator_runtime_authorization_secret,
            (
                "estimator-runtime-write-v2:"
                f"{operation_id}:{authorization_id}:{execution_id}:{job_id}"
            ).encode("ascii", errors="strict"),
            hashlib.sha256,
        ).hexdigest()
        with self._estimator_runtime_authorization_lock:
            self._estimator_runtime_authorizations.add(
                (operation_id, authorization_id, execution_id, job_id, tag)
            )
        return operation_id, tag

    def _end_estimator_runtime_authorization(
        self,
        operation_id: str,
        authorization_id: str,
        execution_id: str,
        job_id: str,
        tag: str,
    ) -> None:
        with self._estimator_runtime_authorization_lock:
            self._estimator_runtime_authorizations.discard(
                (operation_id, authorization_id, execution_id, job_id, tag)
            )

    def _automation_publication_authorization_tag(
        self, operation_id: str, job_id: str, action: str
    ) -> str:
        candidate = hmac.new(
            self._automation_publication_authorization_secret,
            (
                "automation-publication-write-v1:"
                f"{operation_id}:{job_id}:{action}"
            ).encode("ascii", errors="strict"),
            hashlib.sha256,
        ).hexdigest()
        with self._automation_publication_authorization_lock:
            active = (operation_id, job_id, action, candidate) in (
                self._automation_publication_authorizations
            )
        return candidate if active else ""

    def _begin_automation_publication_authorization(
        self, job_id: str, action: str
    ) -> tuple[str, str]:
        operation_id = secrets.token_hex(32)
        tag = hmac.new(
            self._automation_publication_authorization_secret,
            (
                "automation-publication-write-v1:"
                f"{operation_id}:{job_id}:{action}"
            ).encode("ascii", errors="strict"),
            hashlib.sha256,
        ).hexdigest()
        with self._automation_publication_authorization_lock:
            self._automation_publication_authorizations.add(
                (operation_id, job_id, action, tag)
            )
        return operation_id, tag

    def _end_automation_publication_authorization(
        self, operation_id: str, job_id: str, action: str, tag: str
    ) -> None:
        with self._automation_publication_authorization_lock:
            self._automation_publication_authorizations.discard(
                (operation_id, job_id, action, tag)
            )

    def _prepare_private_path(self) -> None:
        try:
            if path_has_symlink_component(self.path):
                raise DatabaseError(
                    "database path cannot contain a symlink or reparse point"
                )
            if self.path.exists() and not self.path.is_file():
                raise DatabaseError("database path must be a regular file")
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if path_has_symlink_component(self.path):
                raise DatabaseError(
                    "database path cannot contain a symlink or reparse point"
                )
            self.path.parent.chmod(0o700)
            if self.path.exists():
                self.path.chmod(0o600)
        except DatabaseError:
            raise
        except OSError:
            raise DatabaseError("could not securely prepare database path") from None

    def _estimator_evidence_authorization_tag(
        self, authorization_id: str, submission_id: str, campaign_id: str
    ) -> str:
        candidate = hmac.new(
            self._estimator_evidence_authorization_secret,
            (
                "estimator-evidence-append-v1:"
                f"{authorization_id}:{submission_id}:{campaign_id}"
            ).encode("ascii", errors="strict"),
            hashlib.sha256,
        ).hexdigest()
        with self._estimator_evidence_authorization_lock:
            active = (
                authorization_id,
                submission_id,
                campaign_id,
                candidate,
            ) in self._estimator_evidence_authorizations
        return candidate if active else ""

    def _begin_estimator_evidence_authorization(
        self, submission_id: str, campaign_id: str
    ) -> tuple[str, str]:
        authorization_id = secrets.token_hex(32)
        tag = hmac.new(
            self._estimator_evidence_authorization_secret,
            (
                "estimator-evidence-append-v1:"
                f"{authorization_id}:{submission_id}:{campaign_id}"
            ).encode("ascii", errors="strict"),
            hashlib.sha256,
        ).hexdigest()
        with self._estimator_evidence_authorization_lock:
            self._estimator_evidence_authorizations.add(
                (authorization_id, submission_id, campaign_id, tag)
            )
        return authorization_id, tag

    def _end_estimator_evidence_authorization(
        self,
        authorization_id: str,
        submission_id: str,
        campaign_id: str,
        tag: str,
    ) -> None:
        with self._estimator_evidence_authorization_lock:
            self._estimator_evidence_authorizations.discard(
                (authorization_id, submission_id, campaign_id, tag)
            )

    def _estimator_evidence_delete_authorization_tag(
        self, authorization_id: str, campaign_id: str
    ) -> str:
        candidate = hmac.new(
            self._estimator_evidence_authorization_secret,
            (
                "estimator-evidence-delete-v1:"
                f"{authorization_id}:{campaign_id}"
            ).encode("ascii", errors="strict"),
            hashlib.sha256,
        ).hexdigest()
        with self._estimator_evidence_authorization_lock:
            active = (
                authorization_id,
                campaign_id,
                candidate,
            ) in self._estimator_evidence_delete_authorizations
        return candidate if active else ""

    def _begin_estimator_evidence_delete_authorization(
        self, campaign_id: str
    ) -> tuple[str, str]:
        authorization_id = secrets.token_hex(32)
        tag = hmac.new(
            self._estimator_evidence_authorization_secret,
            (
                "estimator-evidence-delete-v1:"
                f"{authorization_id}:{campaign_id}"
            ).encode("ascii", errors="strict"),
            hashlib.sha256,
        ).hexdigest()
        with self._estimator_evidence_authorization_lock:
            self._estimator_evidence_delete_authorizations.add(
                (authorization_id, campaign_id, tag)
            )
        return authorization_id, tag

    def _end_estimator_evidence_delete_authorization(
        self, authorization_id: str, campaign_id: str, tag: str
    ) -> None:
        with self._estimator_evidence_authorization_lock:
            self._estimator_evidence_delete_authorizations.discard(
                (authorization_id, campaign_id, tag)
            )

    @contextmanager
    def _connection(self, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
        try:
            connection = sqlite3.connect(self.path, timeout=5.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.execute("PRAGMA secure_delete = ON")
            connection.create_function(
                "estimator_evidence_authorization_tag",
                3,
                self._estimator_evidence_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "estimator_evidence_delete_authorization_tag",
                2,
                self._estimator_evidence_delete_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "estimator_runtime_authorization_tag",
                4,
                self._estimator_runtime_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "automation_publication_authorization_tag",
                3,
                self._automation_publication_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "estimator_calibration_report_authorization_tag",
                4,
                self._estimator_calibration_report_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "estimator_gate_decision_authorization_tag",
                4,
                self._estimator_gate_decision_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "temporal_scope_authorization_tag",
                2,
                self._temporal_scope_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "temporal_scope_authorization_tag",
                12,
                self._temporal_scope_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "temporal_history_authorization_tag",
                2,
                self._temporal_history_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "temporal_history_authorization_tag",
                20,
                self._temporal_history_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "temporal_run_delete_authorization_tag",
                2,
                self._temporal_run_delete_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "comparison_prepare_authorization_tag",
                2,
                self._comparison_prepare_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "comparison_prepare_authorization_tag",
                9,
                self._comparison_prepare_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "comparison_seal_authorization_tag",
                2,
                self._comparison_seal_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "comparison_task_delete_authorization_tag",
                2,
                self._comparison_task_delete_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "comparison_task_delete_authorization_tag",
                6,
                self._comparison_task_delete_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "comparison_seal_authorization_tag",
                11,
                self._comparison_seal_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "synthetic_aggregation_append_authorization_tag",
                2,
                self._synthetic_aggregation_append_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "synthetic_aggregation_append_authorization_tag",
                17,
                self._synthetic_aggregation_append_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "synthetic_aggregation_delete_authorization_tag",
                2,
                self._synthetic_aggregation_delete_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "synthetic_aggregation_delete_authorization_tag",
                6,
                self._synthetic_aggregation_delete_authorization_tag,
                deterministic=False,
            )
            connection.create_function(
                "temporal_safe_code",
                1,
                _temporal_safe_code,
                deterministic=True,
            )
            connection.create_function(
                "temporal_safe_version",
                1,
                _temporal_safe_version,
                deterministic=True,
            )
            connection.create_function(
                "temporal_real_is_canonical",
                1,
                _temporal_real_is_canonical,
                deterministic=True,
            )
            connection.create_function(
                "temporal_iso_to_epoch_us",
                1,
                _temporal_iso_to_epoch_us,
                deterministic=True,
            )
            if readonly:
                connection.execute("PRAGMA query_only = ON")
            yield connection
        except sqlite3.Error:
            raise DatabaseError("local database operation failed") from None
        finally:
            local_connection = locals().get("connection")
            if local_connection is not None:
                local_connection.close()

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._initialization_lock:
            if self._initialized:
                return
            self._prepare_private_path()
            migrations = (
                (1, _MIGRATION_1),
                (2, MIGRATION_2),
                (3, MIGRATION_3),
                (4, MIGRATION_4),
                (5, MIGRATION_5),
                (6, MIGRATION_6),
                (7, MIGRATION_7),
                (8, MIGRATION_8),
                (9, MIGRATION_9),
                (10, MIGRATION_10),
                (11, MIGRATION_11),
                (12, MIGRATION_12),
                (13, MIGRATION_13),
                (14, MIGRATION_14),
                (15, MIGRATION_15),
                (16, MIGRATION_16),
                (17, MIGRATION_17),
                (18, MIGRATION_18),
                (19, MIGRATION_19),
                (20, MIGRATION_20),
                (21, MIGRATION_21),
                (22, MIGRATION_22),
                (23, MIGRATION_23),
                (24, MIGRATION_24),
                (25, MIGRATION_25),
                (26, MIGRATION_26),
                (27, MIGRATION_27),
                (28, MIGRATION_28),
                (29, MIGRATION_29),
                (30, MIGRATION_30),
                (31, MIGRATION_31),
                (32, MIGRATION_32),
                (33, MIGRATION_33),
                (34, MIGRATION_34),
                (35, MIGRATION_35),
                (36, MIGRATION_36),
                (37, MIGRATION_37),
                (38, MIGRATION_38),
                (39, MIGRATION_39),
                (40, MIGRATION_40),
                (41, MIGRATION_41),
                (42, MIGRATION_42),
                (43, MIGRATION_43),
                (44, MIGRATION_44),
                (45, MIGRATION_45),
                (46, MIGRATION_46),
                (47, MIGRATION_47),
                (48, MIGRATION_48),
                (49, MIGRATION_49),
                (50, MIGRATION_50),
                (51, MIGRATION_51),
                (52, MIGRATION_52),
                (53, MIGRATION_53),
                (54, MIGRATION_54),
                (55, MIGRATION_55),
                (56, MIGRATION_56),
                (57, MIGRATION_57),
                (58, MIGRATION_58),
                (59, MIGRATION_59),
                (60, MIGRATION_60),
                (61, MIGRATION_61),
            )
            with self._connection() as connection:
                database_version = int(
                    connection.execute("PRAGMA user_version").fetchone()[0]
                )
                if database_version > SCHEMA_VERSION:
                    raise DatabaseInvariantError(
                        "database schema is newer than this application"
                    )
                migration_table_exists = connection.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table' AND name = 'schema_migrations'
                    """
                ).fetchone()
                if migration_table_exists is not None:
                    newest_migration = connection.execute(
                        "SELECT MAX(version) FROM schema_migrations"
                    ).fetchone()[0]
                    if newest_migration is not None and newest_migration > SCHEMA_VERSION:
                        raise DatabaseInvariantError(
                            "database migration is newer than this application"
                        )
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("PRAGMA journal_size_limit = 8388608")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        checksum TEXT NOT NULL,
                        applied_at TEXT NOT NULL
                    )
                    """
                )
                applied = {
                    int(row["version"]): row["checksum"]
                    for row in connection.execute(
                        "SELECT version, checksum FROM schema_migrations ORDER BY version"
                    ).fetchall()
                }
                if set(applied) != set(range(1, database_version + 1)):
                    raise DatabaseInvariantError("database migration history is incomplete")
                for version, script in migrations:
                    checksum = hashlib.sha256(script.encode("utf-8")).hexdigest()
                    if version in applied and applied[version] != checksum:
                        raise DatabaseInvariantError("database migration checksum mismatch")
                    if version <= database_version:
                        continue
                    _apply_migration_atomically(
                        connection,
                        version=version,
                        script=script,
                        checksum=checksum,
                        applied_at=_iso(_utc_now()),
                    )
                pending_plan_decision_authority = int(
                    connection.execute(
                        """SELECT COUNT(*)
                           FROM requirement_plan_evidence_decision_authority_m56
                           WHERE authority_source='trusted_m55_upgrade_pending'
                              OR authority_fingerprint IS NULL"""
                    ).fetchone()[0]
                )
                if pending_plan_decision_authority:
                    if database_version >= 56:
                        raise DatabaseInvariantError(
                            "requirement-plan decision authority is incomplete"
                        )
                    identifiers = self._local_artifact_id_factory
                    if identifiers is None:
                        raise DatabaseInvariantError(
                            "M55 requirement-plan decisions require a keyed trusted upgrade"
                        )
                    from .infrastructure.sqlite.requirement_plan_evidence import (
                        upgrade_trusted_m55_decision_authority,
                    )

                    upgrade_trusted_m55_decision_authority(connection, identifiers)
                incomplete_plan_decision_authority = int(
                    connection.execute(
                        """SELECT COUNT(*)
                           FROM requirement_plan_evidence_decisions decision
                           LEFT JOIN requirement_plan_evidence_decision_authority_m56 authority
                             ON authority.decision_id=decision.decision_id
                           WHERE authority.decision_id IS NULL
                              OR authority.authority_source=
                                 'trusted_m55_upgrade_pending'
                              OR authority.authority_fingerprint IS NULL"""
                    ).fetchone()[0]
                )
                if incomplete_plan_decision_authority:
                    raise DatabaseInvariantError(
                        "requirement-plan decision authority is incomplete"
                    )
                self._seed_metric_definitions(connection)
                connection.commit()
            try:
                self.path.chmod(0o600)
            except OSError:
                raise DatabaseError("could not restrict database file permissions") from None
            self._initialized = True

    def _seed_metric_definitions(self, connection: sqlite3.Connection) -> None:
        for definition in METRIC_DEFINITIONS:
            values = (
                definition.dimension,
                definition.display_name,
                definition.description,
                definition.unit,
                definition.source.value,
                metric_engine_version_for_definition(definition),
                _definition_checksum(definition),
            )
            row = connection.execute(
                """
                SELECT dimension, display_name, description, unit, source,
                       algorithm_version, definition_checksum
                FROM metric_definitions WHERE key = ? AND version = ?
                """,
                (definition.key, definition.version),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO metric_definitions(
                        key, version, dimension, display_name, description, unit,
                        source, algorithm_version, definition_checksum
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (definition.key, definition.version, *values),
                )
                continue
            existing = tuple(row[key] for key in row.keys())
            if existing != values:
                raise DatabaseInvariantError(
                    "metric definition changed without a version bump"
                )

    def _ensure_initialized(self) -> None:
        self.initialize()

    def task_repository(self):
        """Return the narrow task/discovery persistence adapter."""

        from .infrastructure.sqlite.tasks import SqliteTaskRepository

        self._ensure_initialized()
        return SqliteTaskRepository(
            self._connection,
            self._ensure_initialized,
            begin_comparison_task_delete_authorization=(
                self._begin_comparison_task_delete_authorization
            ),
            end_comparison_task_delete_authorization=(
                self._end_comparison_task_delete_authorization
            ),
            begin_synthetic_aggregation_delete_authorization=(
                self._begin_synthetic_aggregation_delete_authorization
            ),
            end_synthetic_aggregation_delete_authorization=(
                self._end_synthetic_aggregation_delete_authorization
            ),
        )

    def task_lifecycle_repository(self):
        """Return the append-only explicit task lifecycle adapter."""

        from .infrastructure.sqlite.task_lifecycle import (
            SqliteTaskLifecycleRepository,
        )

        self._ensure_initialized()
        return SqliteTaskLifecycleRepository(
            self._connection,
            self._ensure_initialized,
        )

    def supersede_session_events(
        self, session_id: str, *, only_source_schema_version: str
    ) -> int:
        """Remove one session's events so a richer source can replace them.

        Guarded: only when the stored session still carries the named source
        schema (a receiver-clock approximation such as the hook ledger), so a
        provider's own record can supersede it without double counting and
        without touching any other session, analysis run, or task.
        """

        self._ensure_initialized()
        from .infrastructure.sqlite._common import require_safe_id

        require_safe_id(session_id)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT source_schema_version FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None or row["source_schema_version"] != only_source_schema_version:
                return 0
            cursor = connection.execute(
                "DELETE FROM events WHERE session_id = ?", (session_id,)
            )
            connection.commit()
            return int(cursor.rowcount)

    def claude_telemetry_ingest(self, pseudonymizer):
        """Return the write side used by the loopback OTLP receiver."""

        from .infrastructure.providers.claude_code_hooks.telemetry import (
            TelemetryIngestService,
        )

        self._ensure_initialized()
        return TelemetryIngestService(
            self._connection, self._ensure_initialized, pseudonymizer
        )

    def prompt_check_repository(self):
        """Prompt-check history (metrics and counters only; never text)."""

        from .infrastructure.sqlite.prompt_checks import SqlitePromptCheckRepository

        self._ensure_initialized()
        return SqlitePromptCheckRepository(self._connection, self._ensure_initialized)

    def model_judgment_repository(self):
        """Model-judge lane judgments (labels only, separate from metrics)."""

        from .infrastructure.sqlite.model_judgments import SqliteModelJudgmentRepository

        self._ensure_initialized()
        return SqliteModelJudgmentRepository(self._connection, self._ensure_initialized)

    def calibration_rating_repository(self):
        """Frozen calibration sample and blind ratings (content-free)."""

        from .infrastructure.sqlite.calibration_ratings import (
            SqliteCalibrationRatingRepository,
        )

        self._ensure_initialized()
        return SqliteCalibrationRatingRepository(self._connection, self._ensure_initialized)

    def claude_hook_ledger(self):
        """Return the read side of the Claude Code hook ledger."""

        from .infrastructure.providers.claude_code_hooks.ledger import (
            SqliteClaudeHookLedger,
        )

        self._ensure_initialized()
        return SqliteClaudeHookLedger(self._connection, self._ensure_initialized)

    def metric_lifecycle_evidence_repository(self):
        """Return explicit, content-free collaboration evidence persistence."""

        from .infrastructure.sqlite.metric_lifecycle_evidence import (
            SqliteMetricLifecycleEvidenceRepository,
        )

        self._ensure_initialized()
        return SqliteMetricLifecycleEvidenceRepository(
            self._connection,
            self._ensure_initialized,
        )

    def declared_task_profile_repository(self):
        """Return immutable reviewed task-profile denominator persistence."""

        from .infrastructure.sqlite.declared_task_profiles import (
            SqliteDeclaredTaskProfileRepository,
        )

        self._ensure_initialized()
        return SqliteDeclaredTaskProfileRepository(
            self._connection,
            self._ensure_initialized,
        )

    def requirement_plan_evidence_repository(self):
        """Return reviewed, content-free requirement-plan evidence storage."""

        from .infrastructure.sqlite.requirement_plan_evidence import (
            SqliteRequirementPlanEvidenceRepository,
        )

        self._ensure_initialized()
        identifiers = self._local_artifact_id_factory
        if identifiers is None:
            raise DatabaseInvariantError(
                "requirement-plan persistence requires local keyed ID issuance"
            )
        return SqliteRequirementPlanEvidenceRepository(
            self._connection,
            self._ensure_initialized,
            identifiers=identifiers,
        )

    def requirement_action_evidence_repository(self):
        """Return reviewed, content-free requirement-action evidence storage."""

        from .infrastructure.sqlite.requirement_action_evidence import (
            SqliteRequirementActionEvidenceRepository,
        )

        self._ensure_initialized()
        identifiers = self._local_artifact_id_factory
        if identifiers is None:
            raise DatabaseInvariantError(
                "requirement-action persistence requires local keyed ID issuance"
            )
        return SqliteRequirementActionEvidenceRepository(
            self._connection,
            self._ensure_initialized,
            identifiers=identifiers,
        )

    def requirement_verification_evidence_repository(self):
        """Return append-only, content-free requirement-verification storage."""

        from .infrastructure.sqlite.requirement_verification_evidence import (
            SqliteRequirementVerificationEvidenceRepository,
        )

        self._ensure_initialized()
        identifiers = self._local_artifact_id_factory
        if identifiers is None:
            raise DatabaseInvariantError(
                "requirement-verification persistence requires local keyed ID issuance"
            )
        return SqliteRequirementVerificationEvidenceRepository(
            self._connection,
            self._ensure_initialized,
            identifiers=identifiers,
        )

    def requirement_verification_current_plan_authority(self):
        """Return the restart-safe durable r6 current-window authority."""

        from .application.analysis.requirement_verification_persistence import (
            CurrentRequirementPlanSnapshotAuthority,
        )
        from .infrastructure.sqlite.requirement_verification_evidence import (
            SqliteCurrentRequirementPlanSourceWindowAuthority,
        )

        self._ensure_initialized()
        return CurrentRequirementPlanSnapshotAuthority(
            self.requirement_plan_evidence_repository(),
            SqliteCurrentRequirementPlanSourceWindowAuthority(
                self._connection,
                self._ensure_initialized,
            ),
        )

    def analysis_run_repository(self):
        """Return the immutable task-analysis persistence adapter."""

        from .infrastructure.sqlite.analysis_runs import SqliteAnalysisRunRepository

        self._ensure_initialized()
        return SqliteAnalysisRunRepository(self._connection, self._ensure_initialized)

    def session_analysis_run_repository(self):
        """Return the immutable selected-session analysis persistence adapter."""

        from .infrastructure.sqlite.session_analysis_runs import (
            SqliteSessionAnalysisRunRepository,
        )

        self._ensure_initialized()
        return SqliteSessionAnalysisRunRepository(
            self._connection,
            self._ensure_initialized,
            temporal_history_repository=self.temporal_history_repository(),
            temporal_comparison_repository=(
                None
                if self._local_artifact_id_factory is None
                else self.temporal_comparison_stratum_repository()
            ),
            begin_temporal_delete_authorization=(
                self._begin_temporal_run_delete_authorization
            ),
            end_temporal_delete_authorization=(
                self._end_temporal_run_delete_authorization
            ),
            begin_synthetic_aggregation_delete_authorization=(
                self._begin_synthetic_aggregation_delete_authorization
            ),
            end_synthetic_aggregation_delete_authorization=(
                self._end_synthetic_aggregation_delete_authorization
            ),
            begin_publication_authorization=(
                self._begin_automation_publication_authorization
            ),
            end_publication_authorization=(
                self._end_automation_publication_authorization
            ),
        )

    def metric_coverage_repository(self):
        """Return the read-only, identifier-free coverage projection."""

        from .infrastructure.sqlite.metric_coverage import (
            SqliteMetricCoverageRepository,
        )

        self._ensure_initialized()
        return SqliteMetricCoverageRepository(
            self._connection,
            self._ensure_initialized,
        )

    def temporal_history_repository(self):
        """Return repository-owned prospective synthetic temporal persistence."""

        from .infrastructure.sqlite.temporal_history import (
            SqliteTemporalHistoryRepository,
        )

        self._ensure_initialized()
        return SqliteTemporalHistoryRepository(
            self._connection,
            self._ensure_initialized,
            begin_scope_authorization=self._begin_temporal_scope_authorization,
            end_scope_authorization=self._end_temporal_scope_authorization,
            begin_history_authorization=self._begin_temporal_history_authorization,
            end_history_authorization=self._end_temporal_history_authorization,
        )

    def temporal_comparison_stratum_repository(self):
        """Return repository-issued synthetic comparison-stratum persistence."""

        from .infrastructure.sqlite.temporal_comparison_strata import (
            SqliteTemporalComparisonStratumRepository,
        )

        self._ensure_initialized()
        identifiers = self._local_artifact_id_factory
        if identifiers is None:
            raise DatabaseInvariantError(
                "comparison persistence requires local keyed ID issuance"
            )
        return SqliteTemporalComparisonStratumRepository(
            self._connection,
            self._ensure_initialized,
            temporal_history_repository=self.temporal_history_repository(),
            identifiers=identifiers,
            begin_prepare_authorization=(
                self._begin_comparison_prepare_authorization
            ),
            end_prepare_authorization=self._end_comparison_prepare_authorization,
            begin_seal_authorization=self._begin_comparison_seal_authorization,
            end_seal_authorization=self._end_comparison_seal_authorization,
        )

    def temporal_synthetic_aggregation_validation_repository(self):
        """Return bounded repository-sealed synthetic aggregation validation."""

        from .infrastructure.sqlite.temporal_aggregation_validation import (
            SqliteTemporalSyntheticAggregationValidationRepository,
        )

        self._ensure_initialized()
        return SqliteTemporalSyntheticAggregationValidationRepository(
            self._connection,
            self._ensure_initialized,
            comparison_repository=self.temporal_comparison_stratum_repository(),
            begin_append_authorization=(
                self._begin_synthetic_aggregation_append_authorization
            ),
            end_append_authorization=(
                self._end_synthetic_aggregation_append_authorization
            ),
            begin_delete_authorization=(
                self._begin_synthetic_aggregation_delete_authorization
            ),
            end_delete_authorization=(
                self._end_synthetic_aggregation_delete_authorization
            ),
        )

    def model_link_experiment_repository(self):
        """Return the content-free local neural-comparison persistence adapter."""

        from .infrastructure.sqlite.model_link_experiments import (
            SqliteModelLinkExperimentRepository,
        )

        self._ensure_initialized()
        return SqliteModelLinkExperimentRepository(
            self._connection, self._ensure_initialized
        )

    def model_ensemble_repository(self):
        """Return normalized content-free measured and predictive persistence."""

        from .infrastructure.sqlite.model_ensemble import (
            SqliteSessionModelEnsembleRepository,
        )

        self._ensure_initialized()
        return SqliteSessionModelEnsembleRepository(
            self._connection,
            self._ensure_initialized,
            identifiers=self._local_artifact_id_factory,
        )

    def model_ensemble_watch_repository(self):
        """Return the durable content-free continuous-watch adapter."""

        from .infrastructure.sqlite.model_ensemble_watch import (
            SqliteModelEnsembleWatchRepository,
        )

        self._ensure_initialized()
        return SqliteModelEnsembleWatchRepository(
            self._connection,
            self._ensure_initialized,
            identifiers=self._local_artifact_id_factory,
        )

    def estimator_repository(self):
        """Return immutable, content-free P1 estimator persistence."""

        from .infrastructure.sqlite.estimators import SqliteEstimatorRepository

        self._ensure_initialized()
        return SqliteEstimatorRepository(
            self._connection,
            self._ensure_initialized,
            begin_evidence_authorization=(
                self._begin_estimator_evidence_authorization
            ),
            end_evidence_authorization=(
                self._end_estimator_evidence_authorization
            ),
            begin_evidence_delete_authorization=(
                self._begin_estimator_evidence_delete_authorization
            ),
            end_evidence_delete_authorization=(
                self._end_estimator_evidence_delete_authorization
            ),
        )

    def analysis_job_repository(self):
        """Return the mutable, content-free durable job queue adapter."""

        from .infrastructure.sqlite.analysis_jobs import SqliteAnalysisJobRepository

        self._ensure_initialized()
        return SqliteAnalysisJobRepository(
            self._connection,
            self._ensure_initialized,
            begin_publication_authorization=(
                self._begin_automation_publication_authorization
            ),
            end_publication_authorization=(
                self._end_automation_publication_authorization
            ),
        )

    def estimator_runtime_repository(self):
        """Return the execution-only, content-free estimator runtime adapter."""

        from .infrastructure.sqlite.estimator_runtime import (
            SqliteEstimatorRuntimeRepository,
        )

        self._ensure_initialized()
        return SqliteEstimatorRuntimeRepository(
            self._connection,
            self._ensure_initialized,
            begin_write_authorization=self._begin_estimator_runtime_authorization,
            end_write_authorization=self._end_estimator_runtime_authorization,
        )

    def calibration_report_repository(self):
        """Return repository-owned, non-activating calibration reporting."""

        from .infrastructure.sqlite.calibration_reports import (
            SqliteCalibrationReportRepository,
        )

        self._ensure_initialized()
        return SqliteCalibrationReportRepository(
            self._connection,
            self._ensure_initialized,
            begin_write_authorization=(
                self._begin_estimator_calibration_report_authorization
            ),
            end_write_authorization=(
                self._end_estimator_calibration_report_authorization
            ),
        )

    def gate_decision_repository(self):
        """Return repository-sealed, non-activating gate decisions."""

        from .infrastructure.sqlite.gate_decisions import (
            SqliteGateDecisionRepository,
        )

        self._ensure_initialized()
        return SqliteGateDecisionRepository(
            self._connection,
            self._ensure_initialized,
            begin_write_authorization=(
                self._begin_estimator_gate_decision_authorization
            ),
            end_write_authorization=(
                self._end_estimator_gate_decision_authorization
            ),
        )

    def automation_grant_repository(self):
        """Return renewable, content-free local automation grant storage."""

        from .infrastructure.sqlite.automation_grants import (
            SqliteAutomationGrantRepository,
        )

        self._ensure_initialized()
        return SqliteAutomationGrantRepository(
            self._connection, self._ensure_initialized
        )

    def automation_candidate_source(
        self,
        *,
        estimator_plan_version: str,
        redactor_version: str,
    ):
        """Return a metadata-only newest-session fingerprint projection."""

        from .infrastructure.automation import SqliteAutomationCandidateSource

        self._ensure_initialized()
        return SqliteAutomationCandidateSource(
            self._connection,
            self._ensure_initialized,
            estimator_plan_version=estimator_plan_version,
            redactor_version=redactor_version,
        )

    def has_active_consent(
        self,
        provider: Provider,
        tier: DataTier = DataTier.METADATA,
    ) -> bool:
        self._ensure_initialized()
        if tier not in LOCAL_SOURCE_CONSENT_TIERS:
            return False
        with self._connection(readonly=True) as connection:
            row = connection.execute(
                """
                SELECT 1 FROM consent_grants
                WHERE provider = ? AND data_tier = ? AND revoked_at IS NULL
                """,
                (provider.value, tier.value),
            ).fetchone()
        return row is not None

    def grant_consent(
        self,
        provider: Provider,
        tier: DataTier = DataTier.METADATA,
    ) -> None:
        self._ensure_initialized()
        if provider is Provider.SYNTHETIC:
            return
        if tier not in LOCAL_SOURCE_CONSENT_TIERS:
            raise DatabaseInvariantError("unsupported local source consent tier")
        now = _iso(_utc_now())
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO consent_grants(
                    provider, data_tier, consent_schema_version, granted_at, revoked_at
                ) VALUES (?, ?, ?, ?, NULL)
                ON CONFLICT(provider, data_tier) DO UPDATE SET
                    consent_schema_version=excluded.consent_schema_version,
                    granted_at=excluded.granted_at,
                    revoked_at=NULL
                """,
                (provider.value, tier.value, f"{tier.value}-source-consent-1", now),
            )
            connection.commit()

    def revoke_consent(
        self,
        provider: Provider,
        tier: DataTier = DataTier.METADATA,
    ) -> None:
        self._ensure_initialized()
        if tier not in LOCAL_SOURCE_CONSENT_TIERS:
            raise DatabaseInvariantError("unsupported local source consent tier")
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE consent_grants SET revoked_at = ?
                WHERE provider = ? AND data_tier = ? AND revoked_at IS NULL
                """,
                (_iso(_utc_now()), provider.value, tier.value),
            )
            connection.commit()

    @staticmethod
    def _merge_optional_observation(
        existing: object | None,
        incoming: object | None,
        field: str,
    ) -> object | None:
        if existing is None:
            return incoming
        if incoming is None or incoming == existing:
            return existing
        raise DatabaseInvariantError(f"{field} observation conflict")

    @staticmethod
    def _merge_terminal_state(existing: str, incoming: str) -> str:
        if existing == incoming:
            return existing
        if existing == SessionState.UNKNOWN.value:
            return incoming
        if incoming == SessionState.UNKNOWN.value:
            return existing
        raise DatabaseInvariantError("session terminal state conflict")

    @staticmethod
    def _session_values(session: SafeSession) -> tuple[object, ...]:
        return (
            session.installation_id,
            session.project_id,
            session.provider.value,
            session.provider_version,
            session.adapter_version,
            session.source_schema_version,
            _iso(session.started_at),
            _iso(session.ended_at) if session.ended_at is not None else None,
            session.terminal_state.value,
            int(session.events_complete),
            (
                session.session_display_name
                if session.provider not in INDEXED_LABEL_PROVENANCE
                else None
            ),
        )

    def _upsert_session(
        self, connection: sqlite3.Connection, session: SafeSession, now: str
    ) -> tuple[int, int]:
        installation = connection.execute(
            "SELECT provider FROM installations WHERE installation_id = ?",
            (session.installation_id,),
        ).fetchone()
        if installation is None:
            connection.execute(
                "INSERT INTO installations(installation_id, provider, created_at) VALUES (?, ?, ?)",
                (session.installation_id, session.provider.value, now),
            )
        elif installation["provider"] != session.provider.value:
            raise DatabaseInvariantError("installation pseudonym provenance conflict")

        project = connection.execute(
            "SELECT installation_id, provider, display_name FROM projects WHERE project_id = ?",
            (session.project_id,),
        ).fetchone()
        if project is None:
            connection.execute(
                """
                INSERT INTO projects(
                    project_id, installation_id, provider, display_name, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session.project_id,
                    session.installation_id,
                    session.provider.value,
                    (
                        session.project_display_name
                        if session.provider not in INDEXED_LABEL_PROVENANCE
                        else None
                    ),
                    now,
                ),
            )
        elif (
            project["installation_id"] != session.installation_id
            or project["provider"] != session.provider.value
        ):
            raise DatabaseInvariantError("project pseudonym provenance conflict")
        elif (
            session.provider not in INDEXED_LABEL_PROVENANCE
            and session.project_display_name is not None
            and project["display_name"] != session.project_display_name
        ):
            connection.execute(
                "UPDATE projects SET display_name = ? WHERE project_id = ?",
                (session.project_display_name, session.project_id),
            )

        row = connection.execute(
            """
            SELECT installation_id, project_id, provider, provider_version,
                   adapter_version, source_schema_version, started_at, ended_at,
                   terminal_state, events_complete, display_name,
                   provider_activity_revision
            FROM sessions WHERE session_id = ?
            """,
            (session.session_id,),
        ).fetchone()
        values = self._session_values(session)
        if row is None:
            connection.execute(
                """
                INSERT INTO sessions(
                    session_id, installation_id, project_id, provider,
                    provider_version, adapter_version, source_schema_version,
                    started_at, ended_at, terminal_state, events_complete,
                    display_name, provider_activity_revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    *values,
                    session.provider_activity_revision,
                    now,
                    now,
                ),
            )
            return 1, 0

        identity_keys = (
            "installation_id",
            "project_id",
            "provider",
            "started_at",
        )
        identity_values = (
            values[0],
            values[1],
            values[2],
            values[6],
        )
        if tuple(row[key] for key in identity_keys) != identity_values:
            raise DatabaseInvariantError("session identity conflict")
        merged = (
            values[0],
            values[1],
            values[2],
            values[3],
            values[4],
            values[5],
            values[6],
            self._merge_optional_observation(
                row["ended_at"], values[7], "session ended_at"
            ),
            self._merge_terminal_state(row["terminal_state"], values[8]),
            int(bool(row["events_complete"]) or bool(values[9])),
            values[10] if values[10] is not None else row["display_name"],
            (
                session.provider_activity_revision
                if session.provider_activity_revision is not None
                else row["provider_activity_revision"]
            ),
        )
        existing = tuple(row[key] for key in row.keys())
        if existing == merged:
            return 0, 0
        connection.execute(
            """
            UPDATE sessions SET
                provider_version=?, adapter_version=?, source_schema_version=?,
                ended_at=?, terminal_state=?, events_complete=?, display_name=?,
                provider_activity_revision=?, updated_at=?
            WHERE session_id=?
            """,
            (*merged[3:6], *merged[7:], now, session.session_id),
        )
        return 0, 1

    def _observe_indexed_display_labels(
        self,
        connection: sqlite3.Connection,
        session: SafeSession,
        now: str,
    ) -> bool:
        """Record provider labels with provenance outside identity columns."""

        provenance = INDEXED_LABEL_PROVENANCE.get(session.provider)
        if provenance is None:
            return False
        observation_method = provenance["observation_method"]
        session_source = provenance["session_source"]
        if session.provider is Provider.CLAUDE_CODE and session.adapter_version.startswith(HOOK_ADAPTER_VERSION_PREFIX):
            observation_method = LabelObservationMethod.HOOK_EVENT.value
            session_source = ProviderLabelSource.EXPLICIT_TITLE.value
        changed = False
        candidates = (
            (
                "project_display_labels",
                "project_id",
                session.project_id,
                session.project_display_name,
                provenance["project_source"],
            ),
            (
                "session_display_labels",
                "session_id",
                session.session_id,
                session.session_display_name,
                session_source,
            ),
        )
        for table, identity_column, identity, value, source in candidates:
            if value is None:
                continue
            row = connection.execute(
                f"""
                SELECT provider_value, provider_source, observation_method,
                       extractor_version, provider_version, adapter_version,
                       source_schema_version
                FROM {table} WHERE {identity_column} = ?
                """,
                (identity,),
            ).fetchone()
            provider_values = (
                value,
                source,
                observation_method,
                provenance["extractor_version"],
                session.provider_version,
                session.adapter_version,
                session.source_schema_version,
            )
            if row is None:
                connection.execute(
                    f"""
                    INSERT INTO {table}(
                        {identity_column}, provider_value, provider_source,
                        observation_method, extractor_version, provider_version,
                        adapter_version, source_schema_version,
                        provider_observed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (identity, *provider_values, now),
                )
                changed = True
                continue
            existing = tuple(row[key] for key in row.keys())
            if existing == provider_values:
                continue
            connection.execute(
                f"""
                UPDATE {table}
                SET provider_value=?, provider_source=?, observation_method=?,
                    extractor_version=?, provider_version=?, adapter_version=?,
                    source_schema_version=?, provider_observed_at=?
                WHERE {identity_column}=?
                """,
                (*provider_values, now, identity),
            )
            changed = True
        return changed

    @staticmethod
    def _event_values(event: SafeEvent) -> tuple[object, ...]:
        return (
            event.session_id,
            event.kind.value,
            event.sequence,
            _iso(event.occurred_at),
            event.time_basis.value,
            event.duration_ms,
            None if event.success is None else int(event.success),
            event.tool_category.value if event.tool_category is not None else None,
        )

    @staticmethod
    def _usage_values(usage: UsageRecord) -> tuple[object, ...]:
        return (
            usage.input_tokens,
            usage.cached_input_tokens,
            usage.cache_creation_tokens,
            usage.output_tokens,
            usage.reasoning_output_tokens,
            usage.total_tokens,
            usage.model_id,
            int(usage.provider_reported),
            usage.counter_kind.value,
            usage.scope.value,
        )

    def _upsert_event(
        self, connection: sqlite3.Connection, event: SafeEvent, now: str
    ) -> tuple[int, int]:
        row = connection.execute(
            """
            SELECT session_id, kind, sequence, occurred_at, time_basis,
                   duration_ms, success, tool_category
            FROM events WHERE event_id = ?
            """,
            (event.event_id,),
        ).fetchone()
        values = self._event_values(event)
        sequence_owner = connection.execute(
            "SELECT event_id FROM events WHERE session_id = ? AND sequence = ?",
            (event.session_id, event.sequence),
        ).fetchone()
        if (
            sequence_owner is not None
            and sequence_owner["event_id"] != event.event_id
        ):
            raise DatabaseInvariantError("event sequence identity conflict")

        inserted = 0
        changed = False
        if row is None:
            connection.execute(
                """
                INSERT INTO events(
                    event_id, session_id, kind, sequence, occurred_at, time_basis,
                    duration_ms, success, tool_category, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (event.event_id, *values, now, now),
            )
            inserted = 1
        else:
            identity_keys = ("session_id", "kind", "sequence", "occurred_at", "time_basis")
            identity_values = values[: len(identity_keys)]
            if tuple(row[key] for key in identity_keys) != identity_values:
                raise DatabaseInvariantError("event identity conflict")
            merged = (
                *identity_values,
                self._merge_optional_observation(
                    row["duration_ms"], values[5], "event duration"
                ),
                self._merge_optional_observation(
                    row["success"], values[6], "event success"
                ),
                self._merge_optional_observation(
                    row["tool_category"], values[7], "event tool category"
                ),
            )
            if tuple(row[key] for key in row.keys()) != merged:
                connection.execute(
                    """
                    UPDATE events SET duration_ms=?, success=?, tool_category=?,
                        updated_at=? WHERE event_id=?
                    """,
                    (*merged[5:], now, event.event_id),
                )
                changed = True

        usage_row = connection.execute(
            """
            SELECT input_tokens, cached_input_tokens, cache_creation_tokens,
                   output_tokens, reasoning_output_tokens, total_tokens, model_id,
                   provider_reported, counter_kind, scope
            FROM usage_records WHERE event_id = ?
            """,
            (event.event_id,),
        ).fetchone()
        if event.usage is not None:
            usage_values = self._usage_values(event.usage)
            if usage_row is None:
                connection.execute(
                    """
                    INSERT INTO usage_records(
                        event_id, input_tokens, cached_input_tokens,
                        cache_creation_tokens, output_tokens, reasoning_output_tokens,
                        total_tokens, model_id, provider_reported, counter_kind, scope
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (event.event_id, *usage_values),
                )
                changed = changed or not inserted
            else:
                if usage_row["provider_reported"] != usage_values[7]:
                    raise DatabaseInvariantError(
                        "usage reporting provenance conflict"
                    )
                if (
                    usage_row["counter_kind"] != usage_values[8]
                    or usage_row["scope"] != usage_values[9]
                ):
                    raise DatabaseInvariantError(
                        "usage counter provenance conflict"
                    )

                merged_usage = (
                    self._merge_optional_observation(
                        usage_row["input_tokens"], usage_values[0], "usage input tokens"
                    ),
                    self._merge_optional_observation(
                        usage_row["cached_input_tokens"],
                        usage_values[1],
                        "usage cached input tokens",
                    ),
                    self._merge_optional_observation(
                        usage_row["cache_creation_tokens"],
                        usage_values[2],
                        "usage cache creation tokens",
                    ),
                    self._merge_optional_observation(
                        usage_row["output_tokens"], usage_values[3], "usage output tokens"
                    ),
                    self._merge_optional_observation(
                        usage_row["reasoning_output_tokens"],
                        usage_values[4],
                        "usage reasoning output tokens",
                    ),
                    self._merge_optional_observation(
                        usage_row["total_tokens"], usage_values[5], "usage total tokens"
                    ),
                    self._merge_optional_observation(
                        usage_row["model_id"], usage_values[6], "usage model identifier"
                    ),
                    usage_row["provider_reported"],
                    usage_row["counter_kind"],
                    usage_row["scope"],
                )
                if tuple(usage_row[key] for key in usage_row.keys()) != merged_usage:
                    connection.execute(
                        """
                        UPDATE usage_records SET input_tokens=?,
                            cached_input_tokens=?, cache_creation_tokens=?,
                            output_tokens=?, reasoning_output_tokens=?,
                            total_tokens=?, model_id=?, provider_reported=?,
                            counter_kind=?, scope=?
                        WHERE event_id=?
                        """,
                        (*merged_usage, event.event_id),
                    )
                    changed = True
        return inserted, int(changed and not inserted)

    def persist_session(
        self,
        session: SafeSession,
        events: Iterable[SafeEvent],
    ) -> PersistResult:
        self._ensure_initialized()
        event_list = tuple(events)
        if any(event.session_id != session.session_id for event in event_list):
            raise DatabaseInvariantError("event belongs to a different safe session")
        now = _iso(_utc_now())
        with self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                session_inserted, session_updated = self._upsert_session(
                    connection, session, now
                )
                labels_changed = self._observe_indexed_display_labels(
                    connection, session, now
                )
                if labels_changed and not session_inserted:
                    session_updated = 1
                events_inserted = 0
                events_updated = 0
                for event in event_list:
                    inserted, updated = self._upsert_event(connection, event, now)
                    events_inserted += inserted
                    events_updated += updated
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return PersistResult(
            session_inserted=session_inserted,
            session_updated=session_updated,
            events_inserted=events_inserted,
            events_updated=events_updated,
        )

    def get_session(self, session_id: str) -> SafeSession | None:
        self._ensure_initialized()
        with self._connection(readonly=True) as connection:
            row = connection.execute(
                """
                SELECT s.*,
                       COALESCE(pdl.manual_value, pdl.provider_value, p.display_name)
                           AS project_display_name,
                       COALESCE(sdl.manual_value, sdl.provider_value, s.display_name)
                           AS session_display_name
                FROM sessions s JOIN projects p ON p.project_id = s.project_id
                LEFT JOIN project_display_labels pdl ON pdl.project_id = p.project_id
                LEFT JOIN session_display_labels sdl ON sdl.session_id = s.session_id
                WHERE s.session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return SafeSession(
            provider=Provider(row["provider"]),
            installation_id=row["installation_id"],
            project_id=row["project_id"],
            session_id=row["session_id"],
            provider_version=row["provider_version"],
            adapter_version=row["adapter_version"],
            source_schema_version=row["source_schema_version"],
            started_at=_parse_time(row["started_at"]),
            provider_activity_revision=row["provider_activity_revision"],
            ended_at=_parse_time(row["ended_at"]),
            terminal_state=SessionState(row["terminal_state"]),
            events_complete=bool(row["events_complete"]),
            project_display_name=row["project_display_name"],
            session_display_name=row["session_display_name"],
        )

    def get_session_events(self, session_id: str) -> tuple[SafeEvent, ...]:
        self._ensure_initialized()
        with self._connection(readonly=True) as connection:
            rows = connection.execute(
                """
                SELECT e.*, u.event_id AS usage_event_id, u.input_tokens,
                       u.cached_input_tokens, u.cache_creation_tokens,
                       u.output_tokens, u.reasoning_output_tokens, u.total_tokens,
                       u.model_id, u.provider_reported, u.counter_kind, u.scope
                FROM events e
                LEFT JOIN usage_records u ON u.event_id = e.event_id
                WHERE e.session_id = ? ORDER BY e.sequence, e.event_id
                """,
                (session_id,),
            ).fetchall()
        result: list[SafeEvent] = []
        for row in rows:
            usage = None
            if row["usage_event_id"] is not None:
                usage = UsageRecord(
                    input_tokens=row["input_tokens"],
                    cached_input_tokens=row["cached_input_tokens"],
                    cache_creation_tokens=row["cache_creation_tokens"],
                    output_tokens=row["output_tokens"],
                    reasoning_output_tokens=row["reasoning_output_tokens"],
                    total_tokens=row["total_tokens"],
                    model_id=row["model_id"],
                    provider_reported=bool(row["provider_reported"]),
                    counter_kind=UsageCounterKind(row["counter_kind"]),
                    scope=UsageScope(row["scope"]),
                )
            result.append(
                SafeEvent(
                    session_id=row["session_id"],
                    event_id=row["event_id"],
                    kind=EventKind(row["kind"]),
                    sequence=row["sequence"],
                    occurred_at=_parse_time(row["occurred_at"]),
                    duration_ms=row["duration_ms"],
                    time_basis=EventTimeBasis(row["time_basis"]),
                    success=None if row["success"] is None else bool(row["success"]),
                    tool_category=(
                        ToolCategory(row["tool_category"])
                        if row["tool_category"] is not None
                        else None
                    ),
                    usage=usage,
                )
            )
        return tuple(result)

    def replace_session_metrics(
        self,
        session_id: str,
        observations: Iterable[MetricObservation],
        *,
        metric_pack_key: str,
        metric_pack_version: int,
        metric_engine_version: str,
    ) -> int:
        self._ensure_initialized()
        if (
            not isinstance(metric_pack_key, str)
            or SAFE_VERSION_PATTERN.fullmatch(metric_pack_key) is None
        ):
            raise DatabaseInvariantError("metric pack key is invalid")
        if (
            isinstance(metric_pack_version, bool)
            or not isinstance(metric_pack_version, int)
            or metric_pack_version < 1
        ):
            raise DatabaseInvariantError("metric pack version is invalid")
        if (
            not isinstance(metric_engine_version, str)
            or SAFE_VERSION_PATTERN.fullmatch(metric_engine_version) is None
        ):
            raise DatabaseInvariantError("metric engine version is invalid")
        items = tuple(observations)
        identities = {(item.key, item.version) for item in items}
        if len(identities) != len(items):
            raise DatabaseInvariantError("duplicate metric observation")
        now = _iso(_utc_now())
        changed = 0
        with self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute(
                    "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
                ).fetchone() is None:
                    raise DatabaseInvariantError("safe session does not exist")
                existing_rows = connection.execute(
                    "SELECT * FROM metric_results WHERE session_id = ?", (session_id,)
                ).fetchall()
                existing = {(row["key"], row["version"]): row for row in existing_rows}
                stale = set(existing) - identities
                for key, version in stale:
                    connection.execute(
                        "DELETE FROM metric_results WHERE session_id=? AND key=? AND version=?",
                        (session_id, key, version),
                    )
                    changed += 1
                for item in items:
                    values = (
                        item.numeric_value,
                        item.text_value,
                        item.unit,
                        item.source.value,
                        item.observed_count,
                        item.eligible_count,
                        item.coverage,
                        item.confidence,
                        metric_pack_key,
                        metric_pack_version,
                        metric_engine_version,
                        NOT_APPLICABLE_VERSION,
                        None,
                        None,
                        None,
                        None,
                        None,
                    )
                    row = existing.get((item.key, item.version))
                    comparison_keys = (
                        "numeric_value", "text_value", "unit", "source",
                        "observed_count", "eligible_count", "coverage", "confidence",
                        "metric_pack_key", "metric_pack_version",
                        "metric_engine_version", "redactor_version", "model_id",
                        "model_revision", "tokenizer_id", "prompt_version", "rubric_version",
                    )
                    if row is None:
                        connection.execute(
                            """
                            INSERT INTO metric_results(
                                session_id, key, version, numeric_value, text_value,
                                unit, source, observed_count, eligible_count, coverage,
                                confidence, metric_pack_key, metric_pack_version,
                                metric_engine_version, redactor_version,
                                model_id, model_revision, tokenizer_id, prompt_version,
                                rubric_version, computed_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (session_id, item.key, item.version, *values, now),
                        )
                        changed += 1
                    elif tuple(row[key] for key in comparison_keys) != values:
                        connection.execute(
                            """
                            UPDATE metric_results SET numeric_value=?, text_value=?,
                                unit=?, source=?, observed_count=?, eligible_count=?,
                                coverage=?, confidence=?, metric_pack_key=?,
                                metric_pack_version=?, metric_engine_version=?,
                                redactor_version=?, model_id=?, model_revision=?,
                                tokenizer_id=?, prompt_version=?, rubric_version=?,
                                computed_at=?
                            WHERE session_id=? AND key=? AND version=?
                            """,
                            (*values, now, session_id, item.key, item.version),
                        )
                        changed += 1
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return changed

    def list_metric_definitions(self) -> list[dict[str, object]]:
        self._ensure_initialized()
        with self._connection(readonly=True) as connection:
            rows = connection.execute(
                """
                SELECT key, version, dimension, display_name, description, unit,
                       source, algorithm_version, definition_checksum
                FROM metric_definitions ORDER BY dimension, key, version
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_sessions(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        provider: Provider | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, object]]:
        self._ensure_initialized()
        if limit < 1 or limit > 500:
            raise ValueError("limit must be between 1 and 500")
        if offset < 0:
            raise ValueError("offset cannot be negative")
        filters: list[str] = []
        parameters: list[object] = []
        if provider is not None:
            filters.append("s.provider = ?")
            parameters.append(provider.value)
        if project_id is not None:
            filters.append("s.project_id = ?")
            parameters.append(project_id)
        where_clause = " WHERE " + " AND ".join(filters) if filters else ""
        parameters.extend((limit, offset))
        with self._connection(readonly=True) as connection:
            rows = connection.execute(
                f"""
                SELECT s.session_id, s.installation_id, s.project_id, s.provider,
                       s.provider_version, s.adapter_version, s.source_schema_version,
                       s.started_at, s.ended_at, s.terminal_state, s.events_complete,
                       COALESCE(pdl.manual_value, pdl.provider_value, p.display_name)
                           AS project_display_name,
                       COALESCE(sdl.manual_value, sdl.provider_value, s.display_name)
                           AS session_display_name,
                       CASE
                           WHEN pdl.manual_value IS NOT NULL THEN 'manual'
                           WHEN pdl.provider_value IS NOT NULL
                                OR p.display_name IS NOT NULL THEN 'provider'
                           ELSE 'unknown'
                       END AS project_display_name_origin,
                       CASE
                           WHEN sdl.manual_value IS NOT NULL THEN 'manual'
                           WHEN sdl.provider_value IS NOT NULL
                                OR s.display_name IS NOT NULL THEN 'provider'
                           ELSE 'unknown'
                       END AS session_display_name_origin,
                       COALESCE(pdl.manual_revision, 0)
                           AS project_manual_label_revision,
                       COALESCE(sdl.manual_revision, 0)
                           AS session_manual_label_revision
                FROM sessions s JOIN projects p ON p.project_id = s.project_id
                LEFT JOIN project_display_labels pdl
                    ON pdl.project_id = p.project_id
                LEFT JOIN session_display_labels sdl
                    ON sdl.session_id = s.session_id
                {where_clause}
                ORDER BY s.started_at DESC, s.session_id LIMIT ? OFFSET ?
                """,
                tuple(parameters),
            ).fetchall()
        return [
            {
                **dict(row),
                "events_complete": bool(row["events_complete"]),
            }
            for row in rows
        ]

    def count_sessions(
        self,
        *,
        provider: Provider | None = None,
        project_id: str | None = None,
    ) -> int:
        """Count indexed sessions inside an optional provider/project boundary."""

        self._ensure_initialized()
        filters: list[str] = []
        parameters: list[object] = []
        if provider is not None:
            filters.append("provider = ?")
            parameters.append(provider.value)
        if project_id is not None:
            filters.append("project_id = ?")
            parameters.append(project_id)
        where_clause = " WHERE " + " AND ".join(filters) if filters else ""
        with self._connection(readonly=True) as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS count FROM sessions{where_clause}",
                tuple(parameters),
            ).fetchone()
        return int(row["count"])

    def resolve_indexed_project_sessions(
        self,
        project_ids: tuple[str, ...],
        *,
        max_sessions: int,
    ) -> IndexedProjectSessions:
        """Resolve one complete project scope with one bounded catalog query.

        The query takes at most ``max_sessions + 1`` candidate sessions and
        returns at most that sentinel plus one row per selected project. This
        detects an oversized, missing, or empty selection without a full-scope
        count and fails rather than becoming silent pagination. Only safe local
        identifiers are read; provider adapters are not part of this path.
        """

        self._ensure_initialized()
        with self._connection(readonly=True) as connection:
            return self._resolve_indexed_project_sessions_on_connection(
                connection,
                project_ids,
                max_sessions=max_sessions,
            )

    @staticmethod
    def _resolve_indexed_project_sessions_on_connection(
        connection: sqlite3.Connection,
        project_ids: tuple[str, ...],
        *,
        max_sessions: int,
    ) -> IndexedProjectSessions:
        if not 1 <= len(project_ids) <= 25:
            raise ProjectQualitySelectionIncompleteError(
                ProjectQualitySelectionIncompleteError.code
            )
        if len(set(project_ids)) != len(project_ids):
            raise ProjectQualitySelectionIncompleteError(
                ProjectQualitySelectionIncompleteError.code
            )
        if any(PSEUDONYM_PATTERN.fullmatch(value) is None for value in project_ids):
            raise ProjectQualitySelectionIncompleteError(
                ProjectQualitySelectionIncompleteError.code
            )
        if max_sessions < 1 or max_sessions > 100:
            raise ProjectQualitySelectionLimitError(
                ProjectQualitySelectionLimitError.code
            )

        selected_values = ", ".join("(?, ?)" for _ in project_ids)
        parameters = tuple(
            value
            for ordinal, project_id in enumerate(project_ids)
            for value in (project_id, ordinal)
        ) + (
            max_sessions + 1,
            max_sessions + 1 + len(project_ids),
        )
        query = f"""
            WITH selected_projects(project_id, selection_order) AS (
                VALUES {selected_values}
            ),
            resolved_projects AS (
                SELECT
                    selected_projects.project_id,
                    selected_projects.selection_order,
                    CASE WHEN projects.project_id IS NULL THEN 0 ELSE 1 END
                        AS project_found
                FROM selected_projects
                LEFT JOIN projects
                  ON projects.project_id = selected_projects.project_id
            ),
            candidate_sessions AS (
                SELECT
                    resolved_projects.project_id,
                    resolved_projects.selection_order,
                    sessions.session_id,
                    sessions.started_at
                FROM resolved_projects
                JOIN sessions
                  ON sessions.project_id = resolved_projects.project_id
                WHERE resolved_projects.project_found = 1
                LIMIT ?
            ),
            scope_stats AS (
                SELECT
                    (
                        SELECT COUNT(*) FROM resolved_projects
                        WHERE project_found = 1
                    ) AS matched_project_count,
                    (
                        SELECT COUNT(*) FROM resolved_projects
                        WHERE project_found = 1
                          AND NOT EXISTS (
                              SELECT 1 FROM candidate_sessions
                              WHERE candidate_sessions.project_id =
                                  resolved_projects.project_id
                          )
                    ) AS empty_project_count,
                    (SELECT COUNT(*) FROM candidate_sessions)
                        AS candidate_session_count
            )
            SELECT
                resolved_projects.selection_order,
                resolved_projects.project_found,
                candidate_sessions.session_id,
                scope_stats.matched_project_count,
                scope_stats.empty_project_count,
                scope_stats.candidate_session_count
            FROM resolved_projects
            LEFT JOIN candidate_sessions
              ON candidate_sessions.project_id = resolved_projects.project_id
            CROSS JOIN scope_stats
            ORDER BY
                resolved_projects.selection_order,
                candidate_sessions.started_at DESC,
                candidate_sessions.session_id
            LIMIT ?
        """
        rows = connection.execute(query, parameters).fetchall()

        if not rows:
            raise ProjectQualitySelectionIncompleteError(
                ProjectQualitySelectionIncompleteError.code
            )
        matched_project_count = int(rows[0]["matched_project_count"])
        empty_project_count = int(rows[0]["empty_project_count"])
        session_count = int(rows[0]["candidate_session_count"])
        if matched_project_count != len(project_ids):
            raise ProjectQualitySelectionIncompleteError(
                ProjectQualitySelectionIncompleteError.code
            )
        if session_count > max_sessions:
            raise ProjectQualitySelectionLimitError(
                ProjectQualitySelectionLimitError.code
            )
        if session_count < 1 or empty_project_count:
            raise ProjectQualitySelectionIncompleteError(
                ProjectQualitySelectionIncompleteError.code
            )

        session_ids = tuple(
            str(row["session_id"])
            for row in rows
            if row["session_id"] is not None
        )
        if len(session_ids) != session_count or len(set(session_ids)) != session_count:
            raise ProjectQualitySelectionIncompleteError(
                ProjectQualitySelectionIncompleteError.code
            )
        return IndexedProjectSessions(
            selected_project_count=matched_project_count,
            session_ids=session_ids,
        )

    @contextmanager
    def open_indexed_project_quality_snapshot(
        self,
        project_ids: tuple[str, ...],
        *,
        max_sessions: int,
    ) -> Iterator[IndexedProjectQualitySnapshot]:
        """Keep catalog resolution and immutable-run aggregation in one snapshot."""

        from .infrastructure.sqlite.session_analysis_runs import (
            SqliteSessionAnalysisRunRepository,
        )

        self._ensure_initialized()
        with self._connection(readonly=True) as connection:
            connection.execute("BEGIN")
            resolution = self._resolve_indexed_project_sessions_on_connection(
                connection,
                project_ids,
                max_sessions=max_sessions,
            )

            @contextmanager
            def borrowed_connection(
                *,
                readonly: bool = False,
            ) -> Iterator[sqlite3.Connection]:
                if not readonly:
                    raise DatabaseError("project quality snapshot is read-only")
                yield connection

            repository = SqliteSessionAnalysisRunRepository(
                borrowed_connection,
                self._ensure_initialized,
            )
            try:
                yield IndexedProjectQualitySnapshot(
                    resolution=resolution,
                    repository=repository,
                )
            finally:
                connection.rollback()

    def resolve_provider_label_targets(
        self,
        provider: Provider,
        *,
        project_ids: frozenset[str],
        session_ids: frozenset[str],
        limit: int,
    ) -> LabelTargetBatch:
        """Expand safe project selectors to a fixed, already-indexed session set."""

        self._ensure_initialized()
        if limit < 1 or limit > 25:
            raise ValueError("label target limit must be between 1 and 25")
        if not project_ids and not session_ids:
            return LabelTargetBatch(targets=())

        conditions: list[str] = []
        parameters: list[object] = [provider.value]
        if project_ids:
            values = tuple(sorted(project_ids))
            conditions.append(
                "s.project_id IN (" + ",".join("?" for _ in values) + ")"
            )
            parameters.extend(values)
        if session_ids:
            values = tuple(sorted(session_ids))
            conditions.append(
                "s.session_id IN (" + ",".join("?" for _ in values) + ")"
            )
            parameters.extend(values)
        parameters.append(limit + 1)
        where_selection = " OR ".join(conditions)

        with self._connection(readonly=True) as connection:
            rows = connection.execute(
                f"""
                SELECT s.session_id, s.project_id,
                       COALESCE(pdl.manual_value, pdl.provider_value, p.display_name)
                           IS NULL AS project_label_missing,
                       COALESCE(sdl.manual_value, sdl.provider_value, s.display_name)
                           IS NULL AS session_label_missing
                FROM sessions s
                JOIN projects p ON p.project_id = s.project_id
                LEFT JOIN project_display_labels pdl
                    ON pdl.project_id = p.project_id
                LEFT JOIN session_display_labels sdl
                    ON sdl.session_id = s.session_id
                WHERE s.provider = ?
                  AND ({where_selection})
                  AND (
                    COALESCE(pdl.manual_value, pdl.provider_value, p.display_name)
                        IS NULL
                    OR COALESCE(
                        sdl.manual_value, sdl.provider_value, s.display_name
                    ) IS NULL
                  )
                ORDER BY s.started_at DESC, s.session_id
                LIMIT ?
                """,
                tuple(parameters),
            ).fetchall()
        truncated = len(rows) > limit
        return LabelTargetBatch(
            targets=tuple(
                LabelTarget(
                    session_id=row["session_id"],
                    project_id=row["project_id"],
                    project_label_missing=bool(row["project_label_missing"]),
                    session_label_missing=bool(row["session_label_missing"]),
                )
                for row in rows[:limit]
            ),
            truncated=truncated,
        )

    @staticmethod
    def _fill_provider_display_label(
        connection: sqlite3.Connection,
        *,
        table: str,
        identity_column: str,
        identity: str,
        observation: ProviderDisplayLabelObservation,
    ) -> int:
        row = connection.execute(
            f"SELECT provider_value FROM {table} WHERE {identity_column} = ?",
            (identity,),
        ).fetchone()
        values = (
            observation.value,
            observation.source.value,
            observation.observation_method.value,
            observation.extractor_version,
            observation.provider_version,
            observation.adapter_version,
            observation.source_schema_version,
            _iso(observation.observed_at),
        )
        if row is None:
            connection.execute(
                f"""
                INSERT INTO {table}(
                    {identity_column}, provider_value, provider_source,
                    observation_method, extractor_version, provider_version,
                    adapter_version, source_schema_version, provider_observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (identity, *values),
            )
            return 1
        if row["provider_value"] is not None:
            return 0
        cursor = connection.execute(
            f"""
            UPDATE {table}
            SET provider_value=?, provider_source=?, observation_method=?,
                extractor_version=?, provider_version=?, adapter_version=?,
                source_schema_version=?, provider_observed_at=?
            WHERE {identity_column}=? AND provider_value IS NULL
            """,
            (*values, identity),
        )
        return int(cursor.rowcount == 1)

    def apply_provider_display_labels(
        self,
        observations: tuple[ProviderDisplayLabelObservation, ...],
    ) -> LabelWriteResult:
        """Atomically fill missing provider labels without changing identity."""

        self._ensure_initialized()
        if not observations:
            return LabelWriteResult()
        project_labels_filled = 0
        session_labels_filled = 0
        with self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                for observation in observations:
                    row = connection.execute(
                        """
                        SELECT provider, project_id
                        FROM sessions WHERE session_id = ?
                        """,
                        (observation.session_id,),
                    ).fetchone()
                    if (
                        row is None
                        or row["provider"] != observation.provider.value
                        or row["project_id"] != observation.project_id
                    ):
                        raise DatabaseInvariantError(
                            "display label target identity conflict"
                        )
                    if observation.entity_kind is LabelEntityKind.PROJECT:
                        project_labels_filled += self._fill_provider_display_label(
                            connection,
                            table="project_display_labels",
                            identity_column="project_id",
                            identity=observation.project_id,
                            observation=observation,
                        )
                    else:
                        session_labels_filled += self._fill_provider_display_label(
                            connection,
                            table="session_display_labels",
                            identity_column="session_id",
                            identity=observation.session_id,
                            observation=observation,
                        )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return LabelWriteResult(
            project_labels_filled=project_labels_filled,
            session_labels_filled=session_labels_filled,
        )

    @staticmethod
    def _manual_label_storage(
        entity_kind: LabelEntityKind,
    ) -> tuple[str, str, str]:
        if entity_kind is LabelEntityKind.PROJECT:
            return "projects", "project_display_labels", "project_id"
        return "sessions", "session_display_labels", "session_id"

    def set_manual_display_label(
        self,
        *,
        entity_kind: LabelEntityKind,
        entity_id: str,
        value: str,
        expected_revision: int,
    ) -> ManualDisplayLabelResult:
        """Set one local override with optimistic concurrency."""

        self._ensure_initialized()
        entity_table, label_table, identity_column = self._manual_label_storage(
            entity_kind
        )
        now = _iso(_utc_now())
        with self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                exists = connection.execute(
                    f"SELECT 1 FROM {entity_table} WHERE {identity_column} = ?",
                    (entity_id,),
                ).fetchone()
                if exists is None:
                    raise DisplayLabelNotFoundError(
                        "local display label target was not found"
                    )
                row = connection.execute(
                    f"""
                    SELECT manual_value, manual_revision
                    FROM {label_table} WHERE {identity_column} = ?
                    """,
                    (entity_id,),
                ).fetchone()
                current_revision = 0 if row is None else int(row["manual_revision"])
                if current_revision != expected_revision:
                    raise DisplayLabelConflictError(
                        "local display label revision changed"
                    )
                if row is not None and row["manual_value"] == value:
                    connection.commit()
                    return ManualDisplayLabelResult(
                        entity_kind=entity_kind,
                        entity_id=entity_id,
                        revision=current_revision,
                        changed=False,
                    )
                next_revision = current_revision + 1
                if row is None:
                    connection.execute(
                        f"""
                        INSERT INTO {label_table}(
                            {identity_column}, manual_value, manual_revision,
                            manual_updated_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (entity_id, value, next_revision, now),
                    )
                else:
                    connection.execute(
                        f"""
                        UPDATE {label_table}
                        SET manual_value=?, manual_revision=?, manual_updated_at=?
                        WHERE {identity_column}=?
                        """,
                        (value, next_revision, now, entity_id),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return ManualDisplayLabelResult(
            entity_kind=entity_kind,
            entity_id=entity_id,
            revision=next_revision,
            changed=True,
        )

    def clear_manual_display_label(
        self,
        *,
        entity_kind: LabelEntityKind,
        entity_id: str,
        expected_revision: int,
    ) -> ManualDisplayLabelResult:
        """Clear only the local override and reveal any provider observation."""

        self._ensure_initialized()
        entity_table, label_table, identity_column = self._manual_label_storage(
            entity_kind
        )
        now = _iso(_utc_now())
        with self._connection() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                exists = connection.execute(
                    f"SELECT 1 FROM {entity_table} WHERE {identity_column} = ?",
                    (entity_id,),
                ).fetchone()
                if exists is None:
                    raise DisplayLabelNotFoundError(
                        "local display label target was not found"
                    )
                row = connection.execute(
                    f"""
                    SELECT manual_value, manual_revision
                    FROM {label_table} WHERE {identity_column} = ?
                    """,
                    (entity_id,),
                ).fetchone()
                current_revision = 0 if row is None else int(row["manual_revision"])
                if current_revision != expected_revision:
                    raise DisplayLabelConflictError(
                        "local display label revision changed"
                    )
                if row is None or row["manual_value"] is None:
                    connection.commit()
                    return ManualDisplayLabelResult(
                        entity_kind=entity_kind,
                        entity_id=entity_id,
                        revision=current_revision,
                        changed=False,
                    )
                next_revision = current_revision + 1
                connection.execute(
                    f"""
                    UPDATE {label_table}
                    SET manual_value=NULL, manual_revision=?, manual_updated_at=?
                    WHERE {identity_column}=?
                    """,
                    (next_revision, now, entity_id),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return ManualDisplayLabelResult(
            entity_kind=entity_kind,
            entity_id=entity_id,
            revision=next_revision,
            changed=True,
        )

    def list_project_ids(self, provider: Provider, *, limit: int = 500) -> tuple[str, ...]:
        """Pseudonymous project ids indexed for one provider, most recent first."""

        self._ensure_initialized()
        bounded = max(1, min(int(limit), 5_000))
        with self._connection(readonly=True) as connection:
            rows = connection.execute(
                """
                SELECT project_id
                FROM sessions
                WHERE provider = ?
                GROUP BY project_id
                ORDER BY MAX(COALESCE(ended_at, started_at)) DESC, project_id
                LIMIT ?
                """,
                (provider.value, bounded),
            ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def provider_catalog_summary(self, provider: Provider) -> dict[str, int]:
        """Return aggregate counts without exposing source or safe identifiers."""

        self._ensure_initialized()
        with self._connection(readonly=True) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS sessions,
                       COUNT(DISTINCT project_id) AS projects
                FROM sessions WHERE provider = ?
                """,
                (provider.value,),
            ).fetchone()
        return {"sessions": int(row["sessions"]), "projects": int(row["projects"])}

    def selection_is_indexed(
        self,
        provider: Provider,
        *,
        project_ids: frozenset[str],
        session_ids: frozenset[str],
    ) -> bool:
        """Require every safe selector to exist for the requested provider."""

        self._ensure_initialized()
        if not project_ids and not session_ids:
            return False
        project_values = tuple(sorted(project_ids))
        session_values = tuple(sorted(session_ids))
        with self._connection(readonly=True) as connection:
            if project_values:
                placeholders = ",".join("?" for _ in project_values)
                project_count = connection.execute(
                    f"""
                    SELECT COUNT(*) FROM projects
                    WHERE provider = ? AND project_id IN ({placeholders})
                    """,
                    (provider.value, *project_values),
                ).fetchone()[0]
                if int(project_count) != len(project_values):
                    return False
            if session_values:
                placeholders = ",".join("?" for _ in session_values)
                session_count = connection.execute(
                    f"""
                    SELECT COUNT(*) FROM sessions
                    WHERE provider = ? AND session_id IN ({placeholders})
                    """,
                    (provider.value, *session_values),
                ).fetchone()[0]
                if int(session_count) != len(session_values):
                    return False
        return True

    def get_session_metrics(self, session_id: str) -> list[dict[str, object]]:
        self._ensure_initialized()
        with self._connection(readonly=True) as connection:
            rows = connection.execute(
                """
                SELECT r.key, r.version, d.dimension, d.display_name,
                       r.metric_pack_key, r.metric_pack_version,
                       r.numeric_value, r.text_value, r.unit, r.source,
                       r.observed_count, r.eligible_count, r.coverage, r.confidence,
                       r.metric_engine_version, r.redactor_version, r.model_id,
                       r.model_revision, r.tokenizer_id, r.prompt_version,
                       r.rubric_version, r.computed_at
                FROM metric_results r
                JOIN metric_definitions d ON d.key = r.key AND d.version = r.version
                WHERE r.session_id = ? ORDER BY d.dimension, r.key, r.version
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def summary(self) -> dict[str, int]:
        self._ensure_initialized()
        queries = {
            "sessions": "SELECT COUNT(*) FROM sessions",
            "events": "SELECT COUNT(*) FROM events",
            "metric_results": "SELECT COUNT(*) FROM metric_results",
            "active_consents": "SELECT COUNT(*) FROM consent_grants WHERE revoked_at IS NULL",
        }
        with self._connection(readonly=True) as connection:
            result = {
                key: int(connection.execute(sql).fetchone()[0])
                for key, sql in queries.items()
            }
        result["schema_version"] = SCHEMA_VERSION
        return result

    def begin_ingestion_run(
        self,
        *,
        provider: Provider,
        provider_version: str,
        adapter_version: str,
        source_schema_version: str,
        data_tier: DataTier = DataTier.METADATA,
    ) -> str:
        self._ensure_initialized()
        run_id = secrets.token_hex(16)
        if data_tier not in LOCAL_SOURCE_CONSENT_TIERS:
            raise DatabaseInvariantError("unsupported ingestion data tier")
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO ingestion_runs(
                    run_id, provider, provider_version, adapter_version,
                    source_schema_version, schema_version, data_tier,
                    redactor_version, started_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'running')
                """,
                (
                    run_id,
                    provider.value,
                    provider_version,
                    adapter_version,
                    source_schema_version,
                    SCHEMA_VERSION,
                    data_tier.value,
                    NOT_APPLICABLE_VERSION,
                    _iso(_utc_now()),
                ),
            )
            connection.commit()
        return run_id

    def finish_ingestion_run(
        self,
        run_id: str,
        *,
        status: str,
        sessions_seen: int,
        events_seen: int,
        metrics_written: int,
        error_code: str | None = None,
    ) -> None:
        self._ensure_initialized()
        if status not in {"completed", "failed"}:
            raise ValueError("terminal ingestion status must be completed or failed")
        if any(value < 0 for value in (sessions_seen, events_seen, metrics_written)):
            raise ValueError("ingestion counts cannot be negative")
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE ingestion_runs SET finished_at=?, status=?, sessions_seen=?,
                    events_seen=?, metrics_written=?, error_code=?
                WHERE run_id=? AND status='running'
                """,
                (
                    _iso(_utc_now()),
                    status,
                    sessions_seen,
                    events_seen,
                    metrics_written,
                    error_code,
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise DatabaseInvariantError("ingestion run is missing or already finished")
            connection.commit()
