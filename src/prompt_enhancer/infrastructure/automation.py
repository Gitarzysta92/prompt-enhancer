"""Content-free adapters connecting automation grants to the local queue."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import hashlib
import json
import secrets
import sqlite3
from typing import Mapping, Protocol

from ..application.automation import (
    AutomationGrantRecord,
    AutomationGrantScope,
    AutomationScheduleResult,
    AutomationSessionCandidate,
)
from ..application.jobs import (
    AnalysisJobIdentity,
    AnalysisJobKind,
    AnalysisJobService,
    AnalysisJobState,
)
from ..domain import DataTier, Provider, SAFE_VERSION_PATTERN
from .sqlite._common import ConnectionScope, from_iso


def _fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class AutomationIndexService(Protocol):
    def index(self, *, max_sessions: int): ...


class AutomationConsentIndex(Protocol):
    def has_active_consent(self, provider: Provider, tier: DataTier) -> bool: ...

    def selection_is_indexed(
        self,
        provider: Provider,
        *,
        project_ids: frozenset[str],
        session_ids: frozenset[str],
    ) -> bool: ...


class LocalAutomationIdFactory:
    def new_id(self) -> str:
        return secrets.token_hex(32)


class LocalAutomationAccessPolicy:
    def __init__(self, index: AutomationConsentIndex) -> None:
        self._index = index

    def has_active_consent(self, provider: Provider, tier: DataTier) -> bool:
        return self._index.has_active_consent(provider, tier)

    def project_is_indexed(self, provider: Provider, project_id: str) -> bool:
        return self._index.selection_is_indexed(
            provider,
            project_ids=frozenset({project_id}),
            session_ids=frozenset(),
        )


class LocalAutomationCatalogRefresher:
    def __init__(self, services: Mapping[Provider, AutomationIndexService]) -> None:
        self._services = dict(services)

    def refresh(self, provider: Provider, *, max_sessions: int) -> None:
        service = self._services.get(provider)
        if service is None:
            raise RuntimeError("automation_provider_index_unavailable")
        service.index(max_sessions=max_sessions)


class SqliteAutomationCandidateSource:
    """Read newest safe index rows; never read transcript or event content."""

    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
        *,
        estimator_plan_version: str,
        redactor_version: str,
    ) -> None:
        for value in (estimator_plan_version, redactor_version):
            if SAFE_VERSION_PATTERN.fullmatch(value) is None:
                raise ValueError("automation provenance versions must be safe")
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized
        self._estimator_plan_version = estimator_plan_version
        self._redactor_version = redactor_version

    def newest_changed(
        self,
        scope: AutomationGrantScope,
        *,
        limit: int,
    ) -> tuple[AutomationSessionCandidate, ...]:
        self._ensure_initialized()
        if limit != scope.newest_session_limit:
            raise ValueError("automation candidate limit must match the grant")
        with self._connection_scope(readonly=True) as connection:
            rows = connection.execute(
                """
                SELECT session_id, project_id, provider, provider_version,
                       adapter_version, source_schema_version, started_at,
                       ended_at, terminal_state, events_complete, updated_at,
                       provider_activity_revision
                FROM sessions
                WHERE project_id = ? AND provider = ?
                ORDER BY COALESCE(ended_at, started_at) DESC, session_id
                LIMIT ?
                """,
                (scope.project_id, scope.provider.value, limit),
            ).fetchall()
        return tuple(self._candidate(scope, row) for row in rows)

    def _candidate(
        self,
        scope: AutomationGrantScope,
        row: sqlite3.Row,
    ) -> AutomationSessionCandidate:
        input_payload = {
            "session_id": row["session_id"],
            "provider_version": row["provider_version"],
            "adapter_version": row["adapter_version"],
            "source_schema_version": row["source_schema_version"],
            "started_at": row["started_at"],
            "ended_at": row["ended_at"],
            "terminal_state": row["terminal_state"],
            "events_complete": row["events_complete"],
            "updated_at": row["updated_at"],
        }
        # Preserve historical candidate fingerprints for zero-backfilled rows.
        # New Codex observations add only an HMAC revision, never the provider
        # activity timestamp itself.
        if row["provider_activity_revision"] is not None:
            input_payload["provider_activity_revision"] = row[
                "provider_activity_revision"
            ]
        input_fingerprint = _fingerprint(input_payload)
        provenance_fingerprint = _fingerprint(
            {
                "estimator_plan_version": self._estimator_plan_version,
                "redactor_version": self._redactor_version,
                "provider_schema_version": row["source_schema_version"],
                "metric_keys": scope.metric_keys,
            }
        )
        updated_at = from_iso(row["updated_at"])
        if updated_at is None:
            raise ValueError("automation candidate requires an update timestamp")
        return AutomationSessionCandidate(
            provider=Provider(row["provider"]),
            project_id=row["project_id"],
            session_id=row["session_id"],
            input_fingerprint=input_fingerprint,
            provenance_fingerprint=provenance_fingerprint,
            provider_schema_version=row["source_schema_version"],
            updated_at=updated_at,
        )


class QueueAutomationJobSink:
    """Deduplicate current fingerprints and supersede stale active work."""

    def __init__(
        self,
        jobs: AnalysisJobService,
        *,
        estimator_plan_version: str,
        redactor_version: str,
    ) -> None:
        for value in (estimator_plan_version, redactor_version):
            if SAFE_VERSION_PATTERN.fullmatch(value) is None:
                raise ValueError("automation job versions must be safe")
        self._jobs = jobs
        self._estimator_plan_version = estimator_plan_version
        self._redactor_version = redactor_version

    def schedule(
        self,
        grant: AutomationGrantRecord,
        candidate: AutomationSessionCandidate,
    ) -> AutomationScheduleResult:
        superseded = 0
        latest = self._jobs.latest_for_session(candidate.session_id)
        if latest is not None and latest.state not in {
            AnalysisJobState.COMPLETED,
            AnalysisJobState.PARTIAL,
            AnalysisJobState.FAILED,
            AnalysisJobState.CANCELLED,
            AnalysisJobState.SUPERSEDED,
        }:
            updated = self._jobs.supersede_if_changed(
                latest.job_id,
                input_fingerprint=candidate.input_fingerprint,
                provenance_fingerprint=candidate.provenance_fingerprint,
            )
            superseded = int(updated.state is AnalysisJobState.SUPERSEDED)
        outcome = self._jobs.enqueue(
            AnalysisJobIdentity(
                kind=AnalysisJobKind.SESSION_QUALITY,
                provider=candidate.provider,
                project_id=candidate.project_id,
                session_id=candidate.session_id,
                input_fingerprint=candidate.input_fingerprint,
                provenance_fingerprint=candidate.provenance_fingerprint,
                metric_keys=grant.scope.metric_keys,
                estimator_plan_version=self._estimator_plan_version,
                redactor_version=self._redactor_version,
                provider_schema_version=candidate.provider_schema_version,
                automation_grant_id=grant.grant_id,
            )
        )
        return AutomationScheduleResult(
            created=outcome.created,
            superseded=superseded,
        )

    def cancel_for_grant(
        self,
        grant_id: str,
        *,
        now: datetime,
    ) -> int:
        del now  # The queue owns its injected clock and records the exact time.
        result = self._jobs.revoke_automation_grant(grant_id)
        return result.cancelled + result.cancellation_requested


__all__ = [
    "LocalAutomationAccessPolicy",
    "LocalAutomationCatalogRefresher",
    "LocalAutomationIdFactory",
    "QueueAutomationJobSink",
    "SqliteAutomationCandidateSource",
]
