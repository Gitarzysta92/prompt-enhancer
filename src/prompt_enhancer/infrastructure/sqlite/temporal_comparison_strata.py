"""Repository-issued synthetic comparison-stratum persistence.

This adapter is deliberately narrower than a general graph store.  It derives
one prospective comparison preparation from live SQLite rows, freezes only
content-free projections, and seals that preparation only inside the owning
session-analysis completion transaction.  Public models are data, never write
capabilities; raw lease credentials remain ephemeral and are never persisted.

The v22 boundary verifies graph identity only.  Every downstream product,
matching, comparison, aggregation, snapshot, recommendation, activation,
export, and sharing capability remains false in the returned contracts.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import sqlite3
from typing import Protocol

from ...application.analysis.text_analysis_presets import COACHING_PROFILE_V1
from ...application.automation import (
    AutomationGrantRecord,
    AutomationGrantScope,
    AutomationGrantState,
    AutomationResourcePolicy,
    AutomationRoute,
)
from ...application.history.comparison_strata import (
    COMPARISON_CURRENT_TASK_QUERY_LIMIT,
    AutomationRevalidationRequestV1,
    ComparisonAnalysisJobAuthorityV1,
    ComparisonAutomationGrantAuthorityV1,
    ComparisonSessionAuthorityV1,
    ComparisonStratumDimensionsV1,
    ExpectedAnalysisRunVerificationRequestV1,
    ReviewedTaskManifestV1,
    ReviewedTaskSelectionVerificationRequestV1,
    ReviewedTaskTargetProjectionV1,
    _AutomationComparisonLeaseAuthorityV1,
    _domain_sha256,
    automation_grant_scope_fingerprint,
    comparison_policy_set_v1,
    select_current_reviewed_tasks_as_of,
    session_analysis_run_authority_fingerprint,
)
from ...application.history.comparison_strata_persistence import (
    AutomationGrantIdentityBridgeV1,
    COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_FINGERPRINT,
    COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_VERSION,
    EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_FINGERPRINT,
    EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_VERSION,
    RepositoryPreparedComparisonStratumV1,
    RepositorySealedComparisonStratumV1,
)
from ...application.jobs import (
    AnalysisJobIdentity,
    AnalysisJobKind,
    AnalysisJobRecord,
    AnalysisJobState,
)
from ...application.persistence import (
    AnalysisRunStatus,
    SessionAnalysisCompletionAuthority,
    SessionAnalysisRunDraft,
    SessionAnalysisRunRecord,
    SessionMetricScopeState,
    TaskRevisionRecord,
)
from ...application.history.persistence import RepositorySealedTemporalBatchV1
from ...database import DatabaseInvariantError
from ...domain import DataTier, Provider, SafeSession, SessionState
from ..identifiers import LocalArtifactIdFactory
from ._common import ConnectionScope, from_iso, require_safe_id, to_iso
from .temporal_history import (
    SqliteTemporalHistoryRepository,
    _from_us,
    _to_us,
)


class BeginAuthorization(Protocol):
    def __call__(self, *values: object) -> tuple[str, str]: ...


class EndAuthorization(Protocol):
    def __call__(
        self,
        operation_id: str,
        authorization_fingerprint: str,
        tag: str,
    ) -> None: ...


def _required_time(value: object) -> datetime:
    try:
        if not isinstance(value, str):
            raise ValueError
        parsed = from_iso(value)
        if parsed is None or parsed.utcoffset() != UTC.utcoffset(parsed):
            raise ValueError
        if to_iso(parsed) != value:
            raise ValueError
        return parsed
    except Exception:
        raise DatabaseInvariantError(
            "stored comparison timestamp is invalid"
        ) from None


def _optional_time(value: object) -> datetime | None:
    return None if value is None else _required_time(value)


class SqliteTemporalComparisonStratumRepository:
    """Issue and rehydrate exact, content-free synthetic comparison graphs."""

    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
        *,
        temporal_history_repository: SqliteTemporalHistoryRepository,
        identifiers: LocalArtifactIdFactory,
        begin_prepare_authorization: BeginAuthorization,
        end_prepare_authorization: EndAuthorization,
        begin_seal_authorization: BeginAuthorization,
        end_seal_authorization: EndAuthorization,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized
        self._temporal = temporal_history_repository
        self._identifiers = identifiers
        self._begin_prepare_authorization = begin_prepare_authorization
        self._end_prepare_authorization = end_prepare_authorization
        self._begin_seal_authorization = begin_seal_authorization
        self._end_seal_authorization = end_seal_authorization
        self._clock = clock or (lambda: datetime.now(UTC))

    @staticmethod
    def _raw_authority(
        authority: _AutomationComparisonLeaseAuthorityV1,
    ) -> tuple[str, str, str, str]:
        if type(authority) is not _AutomationComparisonLeaseAuthorityV1:
            raise DatabaseInvariantError("comparison lease authority is invalid")
        return (
            authority.job_id,
            authority.automation_grant_id,
            authority._lease_owner,
            authority._lease_token,
        )

    @staticmethod
    def _job_metrics(
        connection: sqlite3.Connection,
        job_id: str,
    ) -> tuple[str, ...]:
        rows = connection.execute(
            """SELECT ordinal,metric_key FROM analysis_job_metrics
               WHERE job_id=? ORDER BY ordinal""",
            (job_id,),
        ).fetchall()
        if tuple(row["ordinal"] for row in rows) != tuple(range(len(rows))):
            raise DatabaseInvariantError("stored comparison job metric order is invalid")
        return tuple(str(row["metric_key"]) for row in rows)

    @classmethod
    def _job_record(
        cls,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> AnalysisJobRecord:
        try:
            return AnalysisJobRecord(
                job_id=row["job_id"],
                dedupe_key=row["dedupe_key"],
                identity=AnalysisJobIdentity(
                    kind=AnalysisJobKind(row["kind"]),
                    provider=Provider(row["provider"]),
                    project_id=row["project_id"],
                    session_id=row["session_id"],
                    input_fingerprint=row["input_fingerprint"],
                    provenance_fingerprint=row["provenance_fingerprint"],
                    metric_keys=cls._job_metrics(connection, row["job_id"]),
                    estimator_plan_version=row["estimator_plan_version"],
                    redactor_version=row["redactor_version"],
                    provider_schema_version=row["provider_schema_version"],
                    automation_grant_id=row["automation_grant_id"],
                    local_only=bool(row["local_only"]),
                ),
                state=AnalysisJobState(row["state"]),
                stage_number=row["stage_number"],
                progress_completed=row["progress_completed"],
                progress_total=row["progress_total"],
                attempt_count=row["attempt_count"],
                max_attempts=row["max_attempts"],
                available_at=_required_time(row["available_at"]),
                cancel_requested=bool(row["cancel_requested"]),
                lease_owner=row["lease_owner"],
                lease_token=row["lease_token"],
                lease_expires_at=_optional_time(row["lease_expires_at"]),
                last_error_code=row["last_error_code"],
                terminal_reason_code=row["terminal_reason_code"],
                created_at=_required_time(row["created_at"]),
                updated_at=_required_time(row["updated_at"]),
                terminal_at=_optional_time(row["terminal_at"]),
            )
        except DatabaseInvariantError:
            raise
        except Exception:
            raise DatabaseInvariantError(
                "stored comparison job failed validation"
            ) from None

    @staticmethod
    def _grant_metrics(
        connection: sqlite3.Connection,
        grant_id: str,
    ) -> tuple[str, ...]:
        rows = connection.execute(
            """SELECT ordinal,metric_key FROM automation_grant_metrics
               WHERE grant_id=? ORDER BY ordinal""",
            (grant_id,),
        ).fetchall()
        if tuple(row["ordinal"] for row in rows) != tuple(range(len(rows))):
            raise DatabaseInvariantError(
                "stored comparison grant metric order is invalid"
            )
        return tuple(str(row["metric_key"]) for row in rows)

    @classmethod
    def _grant_record(
        cls,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> AutomationGrantRecord:
        try:
            return AutomationGrantRecord(
                grant_id=row["grant_id"],
                revision=row["revision"],
                scope=AutomationGrantScope(
                    provider=Provider(row["provider"]),
                    project_id=row["project_id"],
                    metric_keys=cls._grant_metrics(connection, row["grant_id"]),
                    newest_session_limit=row["newest_session_limit"],
                    check_interval_seconds=row["check_interval_seconds"],
                    resource_policy=AutomationResourcePolicy(
                        route=AutomationRoute(row["route"]),
                        max_gpu_workers=row["max_gpu_workers"],
                        max_cpu_workers=row["max_cpu_workers"],
                        pause_on_battery=bool(row["pause_on_battery"]),
                        maximum_session_seconds=row["maximum_session_seconds"],
                    ),
                    local_only=bool(row["local_only"]),
                    remote_requires_fresh_approval=bool(
                        row["remote_requires_fresh_approval"]
                    ),
                ),
                state=AutomationGrantState(row["state"]),
                created_at=_required_time(row["created_at"]),
                renewed_at=_required_time(row["renewed_at"]),
                expires_at=_required_time(row["expires_at"]),
                next_check_at=_required_time(row["next_check_at"]),
                last_checked_at=_optional_time(row["last_checked_at"]),
                revoked_at=_optional_time(row["revoked_at"]),
                last_error_code=row["last_error_code"],
            )
        except DatabaseInvariantError:
            raise
        except Exception:
            raise DatabaseInvariantError(
                "stored comparison grant failed validation"
            ) from None

    @staticmethod
    def _session_from_row(row: sqlite3.Row) -> SafeSession:
        try:
            return SafeSession(
                provider=Provider(row["provider"]),
                installation_id=row["installation_id"],
                project_id=row["project_id"],
                session_id=row["session_id"],
                provider_version=row["provider_version"],
                adapter_version=row["adapter_version"],
                source_schema_version=row["source_schema_version"],
                started_at=_required_time(row["started_at"]),
                ended_at=_optional_time(row["ended_at"]),
                terminal_state=SessionState(row["terminal_state"]),
                events_complete=bool(row["events_complete"]),
                project_display_name=None,
                session_display_name=None,
            )
        except DatabaseInvariantError:
            raise
        except Exception:
            raise DatabaseInvariantError(
                "stored comparison session failed validation"
            ) from None

    @staticmethod
    def _lease_fingerprint(
        *,
        job_id: str,
        lease_owner: str,
        lease_token: str,
        lease_expires_at: datetime,
    ) -> str:
        return _domain_sha256(
            "comparison.ephemeral-job-lease-binding.v1",
            {
                "job_id": job_id,
                "lease_expires_at": lease_expires_at.isoformat(),
                "lease_owner": lease_owner,
                "lease_token": lease_token,
            },
        )

    def _verify_replay_authority(
        self,
        prepared: RepositoryPreparedComparisonStratumV1,
        authority: _AutomationComparisonLeaseAuthorityV1,
    ) -> None:
        job_id, grant_id, owner, token = self._raw_authority(authority)
        job = prepared.analysis_job
        if (
            job_id != job.job_id
            or grant_id != prepared.automation_grant.grant_id
            or self._lease_fingerprint(
                job_id=job.job_id,
                lease_owner=owner,
                lease_token=token,
                lease_expires_at=job.lease_expires_at,
            )
            != job.lease_authority_fingerprint
        ):
            raise DatabaseInvariantError("comparison replay authority does not match")

    def _task_revisions_as_of(
        self,
        connection: sqlite3.Connection,
        *,
        session_id: str,
        cutoff_at: datetime,
    ) -> tuple[TaskRevisionRecord, ...]:
        rows = connection.execute(
            """
            WITH latest_before_cutoff AS (
                SELECT task_id,MAX(revision) AS revision
                FROM task_revisions
                WHERE created_at<=?
                GROUP BY task_id
            )
            SELECT latest.task_id,latest.revision,t.project_id,
                   revision.task_type,revision.lifecycle_state,
                   revision.input_fingerprint,revision.created_at
            FROM latest_before_cutoff AS latest
            JOIN task_revisions AS revision
              ON revision.task_id=latest.task_id
             AND revision.revision=latest.revision
            JOIN tasks AS t ON t.task_id=latest.task_id
            JOIN task_revision_sessions AS member
              ON member.task_id=latest.task_id
             AND member.revision=latest.revision
             AND member.session_id=?
            ORDER BY latest.task_id,latest.revision
            LIMIT ?
            """,
            (to_iso(cutoff_at), session_id, COMPARISON_CURRENT_TASK_QUERY_LIMIT),
        ).fetchall()
        if len(rows) == COMPARISON_CURRENT_TASK_QUERY_LIMIT:
            raise DatabaseInvariantError(
                "comparison MAX+1 task query exceeded its reviewed bound"
            )
        try:
            records = tuple(
                TaskRevisionRecord(
                    task_id=row["task_id"],
                    revision=row["revision"],
                    project_id=row["project_id"],
                    task_type=row["task_type"],
                    lifecycle_state=row["lifecycle_state"],
                    session_ids=(session_id,),
                    input_fingerprint=row["input_fingerprint"],
                    created_at=_required_time(row["created_at"]),
                )
                for row in rows
            )
            return select_current_reviewed_tasks_as_of(
                revisions=records,
                session_id=session_id,
                cutoff_at=cutoff_at,
            )
        except DatabaseInvariantError:
            raise
        except Exception:
            raise DatabaseInvariantError(
                "stored comparison task selection failed validation"
            ) from None

    def _selection_request(
        self,
        *,
        job_id: str,
        prepared_scope_id: str,
        session_id: str,
        cutoff_at: datetime,
        revisions: tuple[TaskRevisionRecord, ...],
    ) -> ReviewedTaskSelectionVerificationRequestV1:
        projections = tuple(
            ReviewedTaskTargetProjectionV1.from_source_revision(
                revision,
                target_session_id=session_id,
            )
            for revision in revisions
        )
        cutoff_code = to_iso(cutoff_at)
        selection_id = self._identifiers.fingerprint(
            "comparison-task-selection-id-v1",
            (job_id, prepared_scope_id, session_id, cutoff_code),
        )
        evidence = self._identifiers.fingerprint(
            "comparison-task-query-evidence-v1",
            (
                selection_id,
                str(COMPARISON_CURRENT_TASK_QUERY_LIMIT),
                str(len(projections)),
                *(item.fingerprint for item in projections),
            ),
        )
        fingerprint = ReviewedTaskSelectionVerificationRequestV1.selection_for(
            selection_request_id=selection_id,
            session_id=session_id,
            cutoff_at=cutoff_at,
            scanned_current_candidate_count=len(projections),
            ordered_projection_fingerprints=tuple(
                item.fingerprint for item in projections
            ),
            claimed_query_evidence_fingerprint=evidence,
        )
        return ReviewedTaskSelectionVerificationRequestV1(
            selection_request_id=selection_id,
            session_id=session_id,
            cutoff_at=cutoff_at,
            scanned_current_candidate_count=len(projections),
            current_revisions=projections,
            claimed_query_evidence_fingerprint=evidence,
            selection_sha256=fingerprint,
        )

    def _expected_run_request(
        self,
        *,
        job: ComparisonAnalysisJobAuthorityV1,
        issued_at: datetime,
    ) -> ExpectedAnalysisRunVerificationRequestV1:
        identity = job.identity
        idempotency_key = f"automation-{job.job_id}"
        run_id = self._identifiers.session_analysis_run_id(
            idempotency_key,
            identity.provider,
            identity.session_id,
            COACHING_PROFILE_V1.metric_pack_key,
            COACHING_PROFILE_V1.metric_pack_version,
        )
        receipt_id = self._identifiers.fingerprint(
            "comparison-expected-run-receipt-v1",
            (job.job_id, job.fingerprint, run_id, to_iso(issued_at)),
        )
        derivation = ExpectedAnalysisRunVerificationRequestV1.derivation_for(
            analysis_job_id=job.job_id,
            provider=identity.provider,
            session_id=identity.session_id,
            metric_pack_key=COACHING_PROFILE_V1.metric_pack_key,
            metric_pack_version=COACHING_PROFILE_V1.metric_pack_version,
        )
        request = ExpectedAnalysisRunVerificationRequestV1.request_for(
            authority_receipt_id=receipt_id,
            analysis_job_id=job.job_id,
            analysis_job_authority_fingerprint=job.fingerprint,
            provider=identity.provider,
            session_id=identity.session_id,
            idempotency_key=idempotency_key,
            metric_pack_key=COACHING_PROFILE_V1.metric_pack_key,
            metric_pack_version=COACHING_PROFILE_V1.metric_pack_version,
            expected_analysis_run_id=run_id,
            derivation_inputs_sha256=derivation,
            issued_at=issued_at,
        )
        return ExpectedAnalysisRunVerificationRequestV1(
            authority_receipt_id=receipt_id,
            analysis_job_id=job.job_id,
            analysis_job_authority_fingerprint=job.fingerprint,
            provider=identity.provider,
            session_id=identity.session_id,
            idempotency_key=idempotency_key,
            metric_pack_key=COACHING_PROFILE_V1.metric_pack_key,
            metric_pack_version=COACHING_PROFILE_V1.metric_pack_version,
            expected_analysis_run_id=run_id,
            derivation_inputs_sha256=derivation,
            request_sha256=request,
            issued_at=issued_at,
        )

    @staticmethod
    def _verify_temporal_grant_snapshot_locked(
        connection: sqlite3.Connection,
        *,
        selection_revision_id: str,
        expected_fingerprint: str,
        grant: ComparisonAutomationGrantAuthorityV1,
    ) -> None:
        row = connection.execute(
            """SELECT * FROM temporal_automation_grant_snapshots
               WHERE selection_revision_id=?""",
            (selection_revision_id,),
        ).fetchone()
        metric_rows = connection.execute(
            """SELECT ordinal,metric_key
               FROM temporal_automation_grant_snapshot_metrics
               WHERE selection_revision_id=? ORDER BY ordinal""",
            (selection_revision_id,),
        ).fetchall()
        resource = grant.scope.resource_policy
        if row is None or tuple(item["ordinal"] for item in metric_rows) != tuple(
            range(len(metric_rows))
        ):
            raise DatabaseInvariantError(
                "temporal comparison grant snapshot is incomplete"
            )
        exact = {
            "grant_id": grant.grant_id,
            "revision": grant.revision,
            "provider": grant.scope.provider.value,
            "project_id": grant.scope.project_id,
            "newest_session_limit": grant.scope.newest_session_limit,
            "check_interval_seconds": grant.scope.check_interval_seconds,
            "route": resource.route.value,
            "max_gpu_workers": resource.max_gpu_workers,
            "max_cpu_workers": resource.max_cpu_workers,
            "pause_on_battery": int(resource.pause_on_battery),
            "maximum_session_seconds": resource.maximum_session_seconds,
            "local_only": int(grant.scope.local_only),
            "remote_requires_fresh_approval": int(
                grant.scope.remote_requires_fresh_approval
            ),
            "state": AutomationGrantState.ACTIVE.value,
            "created_at_us": _to_us(grant.created_at),
            "renewed_at_us": _to_us(grant.renewed_at),
            "expires_at_us": _to_us(grant.expires_at),
            "metric_count": len(grant.scope.metric_keys),
            "grant_fingerprint": expected_fingerprint,
        }
        if (
            any(row[name] != value for name, value in exact.items())
            or tuple(str(item["metric_key"]) for item in metric_rows)
            != grant.scope.metric_keys
        ):
            raise DatabaseInvariantError(
                "temporal and comparison grant projections differ"
            )

    def _build_prepared_locked(
        self,
        connection: sqlite3.Connection,
        *,
        prepared_scope_id: str,
        authority: _AutomationComparisonLeaseAuthorityV1,
        prepared_at: datetime,
    ) -> RepositoryPreparedComparisonStratumV1:
        job_id, grant_id, owner, token = self._raw_authority(authority)
        job_row = connection.execute(
            "SELECT * FROM analysis_jobs WHERE job_id=?", (job_id,)
        ).fetchone()
        grant_row = connection.execute(
            "SELECT * FROM automation_grants WHERE grant_id=?", (grant_id,)
        ).fetchone()
        if job_row is None or grant_row is None:
            raise DatabaseInvariantError("comparison automation authority is missing")
        if job_row["lease_owner"] != owner or job_row["lease_token"] != token:
            raise DatabaseInvariantError("comparison automation lease is invalid")
        job_record = self._job_record(connection, job_row)
        grant_record = self._grant_record(connection, grant_row)
        try:
            job = ComparisonAnalysisJobAuthorityV1.from_active_record(
                job_record,
                observed_at=prepared_at,
            )
            grant = ComparisonAutomationGrantAuthorityV1.from_active_record(
                grant_record,
                observed_at=prepared_at,
            )
        except Exception:
            raise DatabaseInvariantError(
                "comparison automation authority is not live"
            ) from None
        if (
            job.identity.automation_grant_id != grant.grant_id
            or job.identity.provider is not Provider.SYNTHETIC
            or grant.scope.provider is not Provider.SYNTHETIC
        ):
            raise DatabaseInvariantError("comparison automation scope is invalid")

        scope = self._temporal._hydrate_scope_locked(
            connection,
            prepared_scope_id,
        )
        # The temporal grant snapshot and comparison live-grant authority use
        # intentionally separate fingerprint domains.  The repository proves
        # their exact row equivalence before the structural draft is issued.
        if (
            scope.automation_grant_id != grant.grant_id
            or scope.automation_grant_revision != grant.revision
            or scope.history_root.project_id != grant.scope.project_id
            or scope.selection_revision.selected_metric_keys
            != grant.scope.metric_keys
        ):
            raise DatabaseInvariantError(
                "comparison scope does not match the live grant revision"
            )
        self._verify_temporal_grant_snapshot_locked(
            connection,
            selection_revision_id=scope.selection_revision.selection_revision_id,
            expected_fingerprint=scope.automation_grant_fingerprint,
            grant=grant,
        )
        session_row = connection.execute(
            "SELECT * FROM sessions WHERE session_id=?",
            (job.identity.session_id,),
        ).fetchone()
        if session_row is None:
            raise DatabaseInvariantError("comparison session is missing")
        session = ComparisonSessionAuthorityV1.from_stored_session(
            self._session_from_row(session_row)
        )
        if (
            session.provider is not Provider.SYNTHETIC
            or session.source_schema_version
            != job.identity.provider_schema_version
            or session.terminal_state is not SessionState.COMPLETED
            or not session.events_complete
            or session.ended_at is None
            or session.ended_at > prepared_at
        ):
            raise DatabaseInvariantError(
                "comparison session is not a complete prepared snapshot"
            )
        revisions = self._task_revisions_as_of(
            connection,
            session_id=session.session_id,
            cutoff_at=prepared_at,
        )
        selection = self._selection_request(
            job_id=job.job_id,
            prepared_scope_id=prepared_scope_id,
            session_id=session.session_id,
            cutoff_at=prepared_at,
            revisions=revisions,
        )
        manifest = ReviewedTaskManifestV1.from_selection_verification_request(
            selection_request=selection
        )
        dimensions = ComparisonStratumDimensionsV1.from_authority(
            session=session,
            task_manifest=manifest,
        )
        expected_run = self._expected_run_request(job=job, issued_at=prepared_at)
        try:
            bridge = AutomationGrantIdentityBridgeV1(
                grant_id=grant.grant_id,
                revision=grant.revision,
                temporal_snapshot_fingerprint=(
                    scope.automation_grant_fingerprint
                ),
                comparison_authority_fingerprint=grant.fingerprint,
                bridge_fingerprint=AutomationGrantIdentityBridgeV1.fingerprint_for(
                    grant_id=grant.grant_id,
                    revision=grant.revision,
                    temporal_snapshot_fingerprint=(
                        scope.automation_grant_fingerprint
                    ),
                    comparison_authority_fingerprint=grant.fingerprint,
                ),
            )
            components = {
                "prepared_scope": scope,
                "analysis_job": job,
                "expected_run_request": expected_run,
                "session_authority": session,
                "automation_grant": grant,
                "automation_grant_scope_sha256": (
                    automation_grant_scope_fingerprint(grant.scope)
                ),
                "grant_identity_bridge": bridge,
                "dimensions": dimensions,
                "policies": comparison_policy_set_v1(),
                "prepared_at": prepared_at,
            }
            prepared_id = (
                RepositoryPreparedComparisonStratumV1.prepared_stratum_id_for(
                    **components
                )
            )
            ordered = (
                RepositoryPreparedComparisonStratumV1.ordered_graph_for(
                    prepared_scope=scope,
                    analysis_job=job,
                    expected_run_request=expected_run,
                    session_authority=session,
                    automation_grant=grant,
                    grant_identity_bridge=bridge,
                    dimensions=dimensions,
                    policies=components["policies"],
                )
            )
            return RepositoryPreparedComparisonStratumV1(
                prepared_stratum_id=prepared_id,
                ordered_graph_fingerprints=ordered,
                **components,
            )
        except Exception:
            raise DatabaseInvariantError(
                "comparison prepared graph failed exact derivation"
            ) from None

    def prepare_automation_stratum(
        self,
        prepared_scope_id: str,
        *,
        authority: _AutomationComparisonLeaseAuthorityV1,
    ) -> RepositoryPreparedComparisonStratumV1:
        self._ensure_initialized()
        require_safe_id(prepared_scope_id)
        job_id, _, _, _ = self._raw_authority(authority)
        with self._connection_scope() as connection:
            connection.execute("PRAGMA trusted_schema=ON")
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    """SELECT prepared_stratum_id
                       FROM comparison_prepared_stratum_roots
                       WHERE analysis_job_id=?""",
                    (job_id,),
                ).fetchone()
                if existing is not None:
                    prepared = self._hydrate_prepared_locked(
                        connection,
                        str(existing["prepared_stratum_id"]),
                    )
                    if prepared.prepared_scope.prepared_scope_id != prepared_scope_id:
                        raise DatabaseInvariantError(
                            "comparison preparation conflicts with stored scope"
                        )
                    self._verify_replay_authority(prepared, authority)
                    connection.commit()
                    return prepared
                now = self._clock()
                _to_us(now)
                prepared = self._build_prepared_locked(
                    connection,
                    prepared_scope_id=prepared_scope_id,
                    authority=authority,
                    prepared_at=now,
                )
                if connection.execute(
                    "SELECT 1 FROM session_analysis_runs WHERE run_id=?",
                    (prepared.expected_analysis_run_id,),
                ).fetchone() is not None:
                    raise DatabaseInvariantError(
                        "comparison preparation must precede analysis-run creation"
                    )
                self._insert_prepared_locked(connection, prepared)
                verified = self._hydrate_prepared_locked(
                    connection,
                    prepared.prepared_stratum_id,
                )
                if verified != prepared:
                    raise DatabaseInvariantError(
                        "stored comparison preparation did not rederive exactly"
                    )
                connection.commit()
                return verified
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.execute("PRAGMA trusted_schema=OFF")

    # The normalized insert/hydration methods are defined after the public read
    # API to keep the authority flow visible before storage mechanics.

    def get_prepared_stratum(
        self,
        prepared_stratum_id: str,
    ) -> RepositoryPreparedComparisonStratumV1 | None:
        self._ensure_initialized()
        require_safe_id(prepared_stratum_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """SELECT 1 FROM comparison_prepared_stratum_roots
                   WHERE prepared_stratum_id=?""",
                (prepared_stratum_id,),
            ).fetchone()
            return (
                None
                if row is None
                else self._hydrate_prepared_locked(connection, prepared_stratum_id)
            )

    def get_prepared_stratum_for_job(
        self,
        job_id: str,
    ) -> RepositoryPreparedComparisonStratumV1 | None:
        self._ensure_initialized()
        require_safe_id(job_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """SELECT prepared_stratum_id
                   FROM comparison_prepared_stratum_roots
                   WHERE analysis_job_id=?""",
                (job_id,),
            ).fetchone()
            return (
                None
                if row is None
                else self._hydrate_prepared_locked(
                    connection, str(row["prepared_stratum_id"])
                )
            )

    def get_sealed_stratum(
        self,
        sealed_stratum_id: str,
    ) -> RepositorySealedComparisonStratumV1 | None:
        self._ensure_initialized()
        require_safe_id(sealed_stratum_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """SELECT 1 FROM comparison_sealed_stratum_roots
                   WHERE sealed_stratum_id=?""",
                (sealed_stratum_id,),
            ).fetchone()
            return (
                None
                if row is None
                else self._hydrate_sealed_locked(connection, sealed_stratum_id)
            )

    def get_sealed_stratum_for_run(
        self,
        analysis_run_id: str,
    ) -> RepositorySealedComparisonStratumV1 | None:
        self._ensure_initialized()
        require_safe_id(analysis_run_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """SELECT sealed_stratum_id
                   FROM comparison_sealed_stratum_roots
                   WHERE analysis_run_id=?""",
                (analysis_run_id,),
            ).fetchone()
            return (
                None
                if row is None
                else self._hydrate_sealed_locked(
                    connection, str(row["sealed_stratum_id"])
                )
            )

    def get_sealed_stratum_for_batch(
        self,
        sealed_batch_id: str,
    ) -> RepositorySealedComparisonStratumV1 | None:
        self._ensure_initialized()
        require_safe_id(sealed_batch_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """SELECT sealed_stratum_id
                   FROM comparison_sealed_stratum_roots
                   WHERE sealed_batch_id=?""",
                (sealed_batch_id,),
            ).fetchone()
            return (
                None
                if row is None
                else self._hydrate_sealed_locked(
                    connection, str(row["sealed_stratum_id"])
                )
            )

    def seal_automation_stratum(
        self,
        prepared_stratum_id: str,
        sealed_batch_id: str,
        *,
        authority: _AutomationComparisonLeaseAuthorityV1,
    ) -> RepositorySealedComparisonStratumV1:
        """Replay an already atomic seal; never create an after-commit root."""

        self._ensure_initialized()
        require_safe_id(prepared_stratum_id)
        require_safe_id(sealed_batch_id)
        with self._connection_scope(readonly=True) as connection:
            prepared = self._hydrate_prepared_locked(connection, prepared_stratum_id)
            self._verify_replay_authority(prepared, authority)
            row = connection.execute(
                """SELECT sealed_stratum_id FROM comparison_sealed_stratum_roots
                   WHERE prepared_stratum_id=? AND sealed_batch_id=?""",
                (prepared_stratum_id, sealed_batch_id),
            ).fetchone()
            if row is None:
                raise DatabaseInvariantError(
                    "initial comparison sealing must be atomic with run completion"
                )
            return self._hydrate_sealed_locked(
                connection,
                str(row["sealed_stratum_id"]),
            )

    def _insert_prepared_locked(
        self,
        connection: sqlite3.Connection,
        prepared: RepositoryPreparedComparisonStratumV1,
    ) -> None:
        prepared = RepositoryPreparedComparisonStratumV1.revalidate_for_persistence(
            prepared
        )
        scope = prepared.prepared_scope
        job = prepared.analysis_job
        identity = job.identity
        expected = prepared.expected_run_request
        session = prepared.session_authority
        grant = prepared.automation_grant
        grant_scope = grant.scope
        resource = grant_scope.resource_policy
        bridge = prepared.grant_identity_bridge
        dimensions = prepared.dimensions
        manifest = dimensions.task_manifest
        selection = manifest.selection_request
        policies = prepared.policies
        authorization_fingerprint = _domain_sha256(
            "comparison.prepare-append-authorization.v1",
            (
                prepared.prepared_stratum_id,
                scope.prepared_scope_id,
                job.job_id,
                grant.grant_id,
                expected.expected_analysis_run_id,
                bridge.fingerprint,
                prepared.fingerprint,
            ),
        )
        operation_id, tag = self._begin_prepare_authorization(
            job.job_id,
            grant.grant_id,
            scope.prepared_scope_id,
            prepared.prepared_stratum_id,
            expected.expected_analysis_run_id,
            bridge.fingerprint,
            prepared.fingerprint,
            authorization_fingerprint,
        )
        try:
            connection.execute(
                """INSERT INTO comparison_prepare_append_authorizations(
                       operation_id,analysis_job_id,automation_grant_id,
                       prepared_scope_id,prepared_stratum_id,
                       expected_analysis_run_id,bridge_fingerprint,
                       prepared_fingerprint,authorization_fingerprint,
                       authorization_tag)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    operation_id,
                    job.job_id,
                    grant.grant_id,
                    scope.prepared_scope_id,
                    prepared.prepared_stratum_id,
                    expected.expected_analysis_run_id,
                    bridge.fingerprint,
                    prepared.fingerprint,
                    authorization_fingerprint,
                    tag,
                ),
            )
            for ordinal, item in enumerate(manifest.current_revisions):
                connection.execute(
                    """INSERT INTO comparison_prepared_task_projections(
                           prepared_stratum_id,operation_id,
                           expected_analysis_run_id,ordinal,task_id,
                           revision,project_id,target_session_id,task_type,
                           lifecycle_state,created_at_us,projection_fingerprint)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        prepared.prepared_stratum_id,
                        operation_id,
                        expected.expected_analysis_run_id,
                        ordinal,
                        item.task_id,
                        item.revision,
                        item.project_id,
                        item.target_session_id,
                        item.task_type,
                        item.lifecycle_state,
                        _to_us(item.created_at),
                        item.fingerprint,
                    ),
                )
            for ordinal, fingerprint in enumerate(
                prepared.ordered_graph_fingerprints
            ):
                connection.execute(
                    """INSERT INTO comparison_prepared_graph_commitments(
                           prepared_stratum_id,operation_id,
                           expected_analysis_run_id,ordinal,fingerprint)
                       VALUES(?,?,?,?,?)""",
                    (
                        prepared.prepared_stratum_id,
                        operation_id,
                        expected.expected_analysis_run_id,
                        ordinal,
                        fingerprint,
                    ),
                )
            root = {
                "prepared_stratum_id": prepared.prepared_stratum_id,
                "operation_id": operation_id,
                "contract_version": prepared.contract_version,
                "prepared_scope_id": scope.prepared_scope_id,
                "prepared_scope_fingerprint": scope.fingerprint,
                "analysis_job_id": job.job_id,
                "analysis_job_fingerprint": job.fingerprint,
                "job_dedupe_key": job.dedupe_key,
                "job_stored_authority_fingerprint": job.stored_job_fingerprint,
                "job_kind": identity.kind.value,
                "job_provider": identity.provider.value,
                "job_project_id": identity.project_id,
                "job_session_id": identity.session_id,
                "job_input_fingerprint": identity.input_fingerprint,
                "job_provenance_fingerprint": identity.provenance_fingerprint,
                "job_metric_count": len(identity.metric_keys),
                "job_estimator_plan_version": identity.estimator_plan_version,
                "job_redactor_version": identity.redactor_version,
                "job_provider_schema_version": identity.provider_schema_version,
                "job_automation_grant_id": identity.automation_grant_id,
                "job_local_only": int(identity.local_only),
                "job_max_attempts": job.max_attempts,
                "job_created_at_us": _to_us(job.created_at),
                "job_state_at_preparation": job.state_at_preparation.value,
                "job_lease_verified_at_us": _to_us(job.lease_verified_at),
                "job_lease_expires_at_us": _to_us(job.lease_expires_at),
                "job_lease_authority_fingerprint": job.lease_authority_fingerprint,
                "expected_run_authority_receipt_id": expected.authority_receipt_id,
                "expected_run_request_fingerprint": expected.fingerprint,
                "expected_run_derivation_fingerprint": expected.derivation_inputs_sha256,
                "expected_analysis_run_id": expected.expected_analysis_run_id,
                "expected_run_idempotency_key": expected.idempotency_key,
                "expected_run_metric_pack_key": expected.metric_pack_key,
                "expected_run_metric_pack_version": expected.metric_pack_version,
                "expected_run_issued_at_us": _to_us(expected.issued_at),
                "expected_run_verifier_version": prepared.expected_run_verifier_version,
                "expected_run_verifier_fingerprint": prepared.expected_run_verifier_fingerprint,
                "session_authority_fingerprint": session.fingerprint,
                "installation_id": session.installation_id,
                "project_id": session.project_id,
                "session_id": session.session_id,
                "session_provider": session.provider.value,
                "session_provider_version": session.provider_version,
                "session_adapter_version": session.adapter_version,
                "session_source_schema_version": session.source_schema_version,
                "session_started_at_us": _to_us(session.started_at),
                "session_ended_at_us": None if session.ended_at is None else _to_us(session.ended_at),
                "session_terminal_state": session.terminal_state.value,
                "session_events_complete": int(session.events_complete),
                "automation_grant_id": grant.grant_id,
                "automation_grant_revision": grant.revision,
                "automation_grant_authority_fingerprint": grant.fingerprint,
                "automation_grant_scope_fingerprint": prepared.automation_grant_scope_sha256,
                "grant_provider": grant_scope.provider.value,
                "grant_project_id": grant_scope.project_id,
                "grant_metric_count": len(grant_scope.metric_keys),
                "grant_newest_session_limit": grant_scope.newest_session_limit,
                "grant_check_interval_seconds": grant_scope.check_interval_seconds,
                "grant_route": resource.route.value,
                "grant_max_gpu_workers": resource.max_gpu_workers,
                "grant_max_cpu_workers": resource.max_cpu_workers,
                "grant_pause_on_battery": int(resource.pause_on_battery),
                "grant_maximum_session_seconds": resource.maximum_session_seconds,
                "grant_local_only": int(grant_scope.local_only),
                "grant_remote_requires_fresh_approval": int(grant_scope.remote_requires_fresh_approval),
                "grant_created_at_us": _to_us(grant.created_at),
                "grant_renewed_at_us": _to_us(grant.renewed_at),
                "grant_expires_at_us": _to_us(grant.expires_at),
                "grant_observed_active_at_us": _to_us(grant.observed_active_at),
                "grant_state_at_preparation": grant.state_at_preparation.value,
                "bridge_contract_version": bridge.contract_version,
                "temporal_snapshot_fingerprint": bridge.temporal_snapshot_fingerprint,
                "bridge_verifier_version": bridge.bridge_verifier_version,
                "bridge_verifier_fingerprint": bridge.bridge_verifier_fingerprint,
                "bridge_fingerprint": bridge.fingerprint,
                "task_selection_request_id": selection.selection_request_id,
                "task_selection_request_fingerprint": selection.fingerprint,
                "task_query_evidence_fingerprint": selection.claimed_query_evidence_fingerprint,
                "task_query_limit": selection.query_limit,
                "task_count": manifest.current_task_count,
                "task_manifest_fingerprint": manifest.fingerprint,
                "dimensions_fingerprint": dimensions.fingerprint,
                "task_type_state": dimensions.task_type_state.value,
                "task_type": None if dimensions.task_type is None else dimensions.task_type.value,
                "task_mix_bucket": dimensions.task_mix_bucket.value,
                "task_type_policy_fingerprint": policies.task_type.sha256,
                "automation_run_binding_policy_fingerprint": policies.automation_run_binding.sha256,
                "matching_policy_fingerprint": policies.matching.sha256,
                "censoring_policy_fingerprint": policies.censoring.sha256,
                "task_mix_policy_fingerprint": policies.task_mix.sha256,
                "policy_set_fingerprint": policies.fingerprint,
                "repository_verifier_version": prepared.repository_verifier_version,
                "repository_verifier_fingerprint": prepared.repository_verifier_fingerprint,
                "prepared_at_us": _to_us(prepared.prepared_at),
                "graph_commitment_count": len(prepared.ordered_graph_fingerprints),
                "prepared_fingerprint": prepared.fingerprint,
            }
            columns = tuple(root)
            connection.execute(
                f"INSERT INTO comparison_prepared_stratum_roots({','.join(columns)}) "
                f"VALUES({','.join('?' for _ in columns)})",
                tuple(root[column] for column in columns),
            )
            connection.execute(
                "DELETE FROM comparison_prepare_append_authorizations WHERE operation_id=?",
                (operation_id,),
            )
        finally:
            self._end_prepare_authorization(
                operation_id,
                authorization_fingerprint,
                tag,
            )

    def _hydrate_prepared_locked(
        self,
        connection: sqlite3.Connection,
        prepared_stratum_id: str,
    ) -> RepositoryPreparedComparisonStratumV1:
        row = connection.execute(
            "SELECT * FROM comparison_prepared_stratum_roots WHERE prepared_stratum_id=?",
            (prepared_stratum_id,),
        ).fetchone()
        if row is None:
            raise DatabaseInvariantError("stored comparison preparation is missing")
        try:
            scope = self._temporal._hydrate_scope_locked(
                connection, str(row["prepared_scope_id"])
            )
            metric_keys = scope.selection_revision.selected_metric_keys
            identity = AnalysisJobIdentity(
                kind=AnalysisJobKind(row["job_kind"]),
                provider=Provider(row["job_provider"]),
                project_id=row["job_project_id"],
                session_id=row["job_session_id"],
                input_fingerprint=row["job_input_fingerprint"],
                provenance_fingerprint=row["job_provenance_fingerprint"],
                metric_keys=metric_keys,
                estimator_plan_version=row["job_estimator_plan_version"],
                redactor_version=row["job_redactor_version"],
                provider_schema_version=row["job_provider_schema_version"],
                automation_grant_id=row["job_automation_grant_id"],
                local_only=bool(row["job_local_only"]),
            )
            job = ComparisonAnalysisJobAuthorityV1(
                job_id=row["analysis_job_id"],
                dedupe_key=row["job_dedupe_key"],
                identity=identity,
                max_attempts=row["job_max_attempts"],
                created_at=_from_us(row["job_created_at_us"]),
                state_at_preparation=AnalysisJobState(row["job_state_at_preparation"]),
                lease_verified_at=_from_us(row["job_lease_verified_at_us"]),
                lease_expires_at=_from_us(row["job_lease_expires_at_us"]),
                lease_authority_fingerprint=row["job_lease_authority_fingerprint"],
                authority_sha256=row["job_stored_authority_fingerprint"],
            )
            session = ComparisonSessionAuthorityV1(
                provider=Provider(row["session_provider"]),
                installation_id=row["installation_id"],
                project_id=row["project_id"],
                session_id=row["session_id"],
                provider_version=row["session_provider_version"],
                adapter_version=row["session_adapter_version"],
                source_schema_version=row["session_source_schema_version"],
                started_at=_from_us(row["session_started_at_us"]),
                ended_at=None if row["session_ended_at_us"] is None else _from_us(row["session_ended_at_us"]),
                terminal_state=SessionState(row["session_terminal_state"]),
                events_complete=bool(row["session_events_complete"]),
            )
            resource = AutomationResourcePolicy(
                route=AutomationRoute(row["grant_route"]),
                max_gpu_workers=row["grant_max_gpu_workers"],
                max_cpu_workers=row["grant_max_cpu_workers"],
                pause_on_battery=bool(row["grant_pause_on_battery"]),
                maximum_session_seconds=row["grant_maximum_session_seconds"],
            )
            grant_scope = AutomationGrantScope(
                provider=Provider(row["grant_provider"]),
                project_id=row["grant_project_id"],
                metric_keys=metric_keys,
                newest_session_limit=row["grant_newest_session_limit"],
                check_interval_seconds=row["grant_check_interval_seconds"],
                resource_policy=resource,
                local_only=bool(row["grant_local_only"]),
                remote_requires_fresh_approval=bool(row["grant_remote_requires_fresh_approval"]),
            )
            grant = ComparisonAutomationGrantAuthorityV1(
                grant_id=row["automation_grant_id"],
                revision=row["automation_grant_revision"],
                scope=grant_scope,
                created_at=_from_us(row["grant_created_at_us"]),
                renewed_at=_from_us(row["grant_renewed_at_us"]),
                expires_at=_from_us(row["grant_expires_at_us"]),
                observed_active_at=_from_us(row["grant_observed_active_at_us"]),
                authority_sha256=row["automation_grant_authority_fingerprint"],
                state_at_preparation=AutomationGrantState(row["grant_state_at_preparation"]),
            )
            self._verify_temporal_grant_snapshot_locked(
                connection,
                selection_revision_id=scope.selection_revision.selection_revision_id,
                expected_fingerprint=scope.automation_grant_fingerprint,
                grant=grant,
            )
            if (
                session.source_schema_version != identity.provider_schema_version
                or session.terminal_state is not SessionState.COMPLETED
                or not session.events_complete
                or session.ended_at is None
                or session.ended_at > _from_us(row["prepared_at_us"])
            ):
                raise ValueError("stored comparison session is not complete")
            bridge = AutomationGrantIdentityBridgeV1(
                contract_version=row["bridge_contract_version"],
                grant_id=grant.grant_id,
                revision=grant.revision,
                temporal_snapshot_fingerprint=row["temporal_snapshot_fingerprint"],
                comparison_authority_fingerprint=grant.fingerprint,
                bridge_verifier_version=row["bridge_verifier_version"],
                bridge_verifier_fingerprint=row["bridge_verifier_fingerprint"],
                bridge_fingerprint=row["bridge_fingerprint"],
            )
            task_rows = connection.execute(
                """SELECT * FROM comparison_prepared_task_projections
                   WHERE prepared_stratum_id=? ORDER BY ordinal""",
                (prepared_stratum_id,),
            ).fetchall()
            if tuple(item["ordinal"] for item in task_rows) != tuple(range(len(task_rows))):
                raise ValueError("stored task projection order is invalid")
            if any(
                item["expected_analysis_run_id"]
                != row["expected_analysis_run_id"]
                for item in task_rows
            ):
                raise ValueError("stored task projection run lineage is invalid")
            projections = tuple(
                ReviewedTaskTargetProjectionV1(
                    task_id=item["task_id"],
                    revision=item["revision"],
                    project_id=item["project_id"],
                    target_session_id=item["target_session_id"],
                    task_type=item["task_type"],
                    lifecycle_state=item["lifecycle_state"],
                    created_at=_from_us(item["created_at_us"]),
                    projection_sha256=item["projection_fingerprint"],
                )
                for item in task_rows
            )
            selection = ReviewedTaskSelectionVerificationRequestV1(
                selection_request_id=row["task_selection_request_id"],
                session_id=session.session_id,
                cutoff_at=_from_us(row["prepared_at_us"]),
                query_limit=row["task_query_limit"],
                scanned_current_candidate_count=row["task_count"],
                current_revisions=projections,
                claimed_query_evidence_fingerprint=row["task_query_evidence_fingerprint"],
                selection_sha256=row["task_selection_request_fingerprint"],
            )
            manifest = ReviewedTaskManifestV1.from_selection_verification_request(
                selection_request=selection
            )
            dimensions = ComparisonStratumDimensionsV1.from_authority(
                session=session,
                task_manifest=manifest,
            )
            expected = ExpectedAnalysisRunVerificationRequestV1(
                authority_receipt_id=row["expected_run_authority_receipt_id"],
                analysis_job_id=job.job_id,
                analysis_job_authority_fingerprint=job.fingerprint,
                provider=identity.provider,
                session_id=identity.session_id,
                idempotency_key=row["expected_run_idempotency_key"],
                metric_pack_key=row["expected_run_metric_pack_key"],
                metric_pack_version=row["expected_run_metric_pack_version"],
                expected_analysis_run_id=row["expected_analysis_run_id"],
                derivation_inputs_sha256=row["expected_run_derivation_fingerprint"],
                request_sha256=row["expected_run_request_fingerprint"],
                issued_at=_from_us(row["expected_run_issued_at_us"]),
            )
            commitments = connection.execute(
                """SELECT ordinal,expected_analysis_run_id,fingerprint
                   FROM comparison_prepared_graph_commitments
                   WHERE prepared_stratum_id=? ORDER BY ordinal""",
                (prepared_stratum_id,),
            ).fetchall()
            ordered = tuple(str(item["fingerprint"]) for item in commitments)
            if tuple(item["ordinal"] for item in commitments) != tuple(range(len(ordered))):
                raise ValueError("stored graph commitment order is invalid")
            if any(
                item["expected_analysis_run_id"]
                != row["expected_analysis_run_id"]
                for item in commitments
            ):
                raise ValueError("stored graph commitment run lineage is invalid")
            policies = comparison_policy_set_v1()
            prepared = RepositoryPreparedComparisonStratumV1(
                contract_version=row["contract_version"],
                prepared_stratum_id=row["prepared_stratum_id"],
                prepared_scope=scope,
                analysis_job=job,
                expected_run_request=expected,
                session_authority=session,
                automation_grant=grant,
                automation_grant_scope_sha256=row["automation_grant_scope_fingerprint"],
                grant_identity_bridge=bridge,
                dimensions=dimensions,
                policies=policies,
                expected_run_verifier_version=row["expected_run_verifier_version"],
                expected_run_verifier_fingerprint=row["expected_run_verifier_fingerprint"],
                repository_verifier_version=row["repository_verifier_version"],
                repository_verifier_fingerprint=row["repository_verifier_fingerprint"],
                ordered_graph_fingerprints=ordered,
                prepared_at=_from_us(row["prepared_at_us"]),
            )
            exact = {
                "prepared_scope_fingerprint": scope.fingerprint,
                "analysis_job_fingerprint": job.fingerprint,
                "session_authority_fingerprint": session.fingerprint,
                "automation_grant_authority_fingerprint": grant.fingerprint,
                "automation_grant_scope_fingerprint": automation_grant_scope_fingerprint(grant_scope),
                "task_manifest_fingerprint": manifest.fingerprint,
                "dimensions_fingerprint": dimensions.fingerprint,
                "task_type_state": dimensions.task_type_state.value,
                "task_type": None if dimensions.task_type is None else dimensions.task_type.value,
                "task_mix_bucket": dimensions.task_mix_bucket.value,
                "task_type_policy_fingerprint": policies.task_type.sha256,
                "automation_run_binding_policy_fingerprint": policies.automation_run_binding.sha256,
                "matching_policy_fingerprint": policies.matching.sha256,
                "censoring_policy_fingerprint": policies.censoring.sha256,
                "task_mix_policy_fingerprint": policies.task_mix.sha256,
                "policy_set_fingerprint": policies.fingerprint,
                "prepared_fingerprint": prepared.fingerprint,
                "job_metric_count": len(metric_keys),
                "grant_metric_count": len(metric_keys),
                "task_count": len(projections),
                "graph_commitment_count": len(ordered),
            }
            if any(row[name] != value for name, value in exact.items()):
                raise ValueError("stored comparison component fingerprint conflicts")
            return RepositoryPreparedComparisonStratumV1.revalidate_for_persistence(
                prepared
            )
        except DatabaseInvariantError:
            raise
        except Exception:
            raise DatabaseInvariantError(
                "stored comparison preparation failed exact rehydration"
            ) from None

    def _hydrate_sealed_locked(
        self,
        connection: sqlite3.Connection,
        sealed_stratum_id: str,
    ) -> RepositorySealedComparisonStratumV1:
        row = connection.execute(
            "SELECT * FROM comparison_sealed_stratum_roots WHERE sealed_stratum_id=?",
            (sealed_stratum_id,),
        ).fetchone()
        if row is None:
            raise DatabaseInvariantError("stored comparison seal is missing")
        try:
            prepared = self._hydrate_prepared_locked(
                connection, str(row["prepared_stratum_id"])
            )
            run = self._analysis_run_locked(
                connection, str(row["analysis_run_id"])
            )
            batch = self._temporal._hydrate_sealed_locked(
                connection, str(row["sealed_batch_id"])
            )
            revalidation_row = connection.execute(
                """SELECT * FROM comparison_automation_revalidations
                   WHERE sealed_stratum_id=?""",
                (sealed_stratum_id,),
            ).fetchone()
            if revalidation_row is None:
                raise ValueError("stored comparison revalidation is missing")
            if revalidation_row["analysis_run_id"] != row["analysis_run_id"]:
                raise ValueError("stored revalidation run lineage is invalid")
            revalidation = AutomationRevalidationRequestV1(
                contract_version=revalidation_row["contract_version"],
                authority_receipt_id=revalidation_row["authority_receipt_id"],
                prepared_stratum_id=revalidation_row["prepared_stratum_id"],
                prepared_stratum_fingerprint=revalidation_row["prepared_fingerprint"],
                analysis_job_id=revalidation_row["analysis_job_id"],
                analysis_job_record_authority_fingerprint=(
                    revalidation_row["job_record_authority_fingerprint"]
                ),
                current_job_state=AnalysisJobState(
                    revalidation_row["current_job_state"]
                ),
                current_job_lease_authority_fingerprint=(
                    revalidation_row["current_job_lease_authority_fingerprint"]
                ),
                current_job_lease_expires_at=_from_us(
                    revalidation_row["current_job_lease_expires_at_us"]
                ),
                automation_grant_id=revalidation_row["automation_grant_id"],
                current_grant_revision=revalidation_row["current_grant_revision"],
                current_grant_authority_fingerprint=(
                    revalidation_row["current_grant_authority_fingerprint"]
                ),
                current_grant_expires_at=_from_us(
                    revalidation_row["current_grant_expires_at_us"]
                ),
                reverified_at=_from_us(revalidation_row["reverified_at_us"]),
                repository_revalidation_authority_fingerprint=(
                    revalidation_row[
                        "repository_revalidation_authority_fingerprint"
                    ]
                ),
                authority_sha256=revalidation_row["revalidation_fingerprint"],
            )
            commitment_rows = connection.execute(
                """SELECT ordinal,analysis_run_id,fingerprint
                   FROM comparison_seal_authority_commitments
                   WHERE sealed_stratum_id=? ORDER BY ordinal""",
                (sealed_stratum_id,),
            ).fetchall()
            ordered = tuple(str(item["fingerprint"]) for item in commitment_rows)
            if tuple(item["ordinal"] for item in commitment_rows) != tuple(
                range(len(ordered))
            ):
                raise ValueError("stored seal commitment order is invalid")
            if any(
                item["analysis_run_id"] != row["analysis_run_id"]
                for item in commitment_rows
            ):
                raise ValueError("stored seal commitment run lineage is invalid")
            sealed = RepositorySealedComparisonStratumV1(
                contract_version=row["contract_version"],
                sealed_stratum_id=row["sealed_stratum_id"],
                prepared_receipt=prepared,
                analysis_run=run,
                analysis_run_authority_sha256=row["run_authority_fingerprint"],
                sealed_batch=batch,
                sealed_batch_sha256=row["sealed_batch_fingerprint"],
                automation_revalidation_request=revalidation,
                ordered_authority_fingerprints=ordered,
                repository_verifier_version=row["repository_verifier_version"],
                repository_verifier_fingerprint=row[
                    "repository_verifier_fingerprint"
                ],
                sealed_at=_from_us(row["sealed_at_us"]),
            )
            exact = {
                "prepared_fingerprint": prepared.fingerprint,
                "run_authority_fingerprint": (
                    session_analysis_run_authority_fingerprint(run)
                ),
                "sealed_batch_fingerprint": batch.fingerprint,
                "revalidation_fingerprint": revalidation.fingerprint,
                "authority_commitment_count": len(ordered),
                "sealed_fingerprint": sealed.fingerprint,
            }
            if any(row[name] != value for name, value in exact.items()):
                raise ValueError("stored comparison seal fingerprint conflicts")
            return RepositorySealedComparisonStratumV1.revalidate_for_persistence(
                sealed
            )
        except DatabaseInvariantError:
            raise
        except Exception:
            raise DatabaseInvariantError(
                "stored comparison seal failed exact rehydration"
            ) from None

    @staticmethod
    def _analysis_run_locked(
        connection: sqlite3.Connection,
        analysis_run_id: str,
    ) -> SessionAnalysisRunRecord:
        row = connection.execute(
            "SELECT * FROM session_analysis_runs WHERE run_id=?",
            (analysis_run_id,),
        ).fetchone()
        if row is None:
            raise DatabaseInvariantError("comparison analysis run is missing")
        metric_rows = connection.execute(
            """SELECT ordinal,metric_key FROM session_analysis_run_metrics
               WHERE run_id=? ORDER BY ordinal""",
            (analysis_run_id,),
        ).fetchall()
        if tuple(item["ordinal"] for item in metric_rows) != tuple(
            range(len(metric_rows))
        ):
            raise DatabaseInvariantError("comparison run metric order is invalid")
        try:
            draft = SessionAnalysisRunDraft(
                run_id=row["run_id"],
                session_id=row["session_id"],
                request_fingerprint=row["request_fingerprint"],
                input_fingerprint=row["input_fingerprint"],
                analysis_profile_key=row["analysis_profile_key"],
                analysis_profile_version=row["analysis_profile_version"],
                metric_pack_key=row["metric_pack_key"],
                metric_pack_version=row["metric_pack_version"],
                metric_scope_state=SessionMetricScopeState(
                    row["metric_scope_state"]
                ),
                selected_metric_keys=tuple(
                    str(item["metric_key"]) for item in metric_rows
                ),
                data_tier=DataTier(row["data_tier"]),
                consent_purpose=row["consent_purpose"],
                consent_policy_version=row["consent_policy_version"],
                provider=Provider(row["provider"]),
                provider_version=row["provider_version"],
                adapter_version=row["adapter_version"],
                source_schema_version=row["source_schema_version"],
                content_schema_version=row["content_schema_version"],
                metric_engine_version=row["metric_engine_version"],
                redactor_version=row["redactor_version"],
                model_plan_fingerprint=row["model_plan_fingerprint"],
                schema_version=row["schema_version"],
                local_only=bool(row["local_only"]),
                started_at=_required_time(row["started_at"]),
            )
            record = SessionAnalysisRunRecord(
                draft=draft,
                status=AnalysisRunStatus(row["status"]),
                finished_at=_optional_time(row["finished_at"]),
                failure_code=row["failure_code"],
            )
            if (
                record.finished_at is not None
                and record.finished_at < record.draft.started_at
            ):
                raise ValueError("stored comparison run ends before it starts")
            return record
        except DatabaseInvariantError:
            raise
        except Exception:
            raise DatabaseInvariantError(
                "stored comparison analysis run failed validation"
            ) from None

    def _build_sealed_locked(
        self,
        connection: sqlite3.Connection,
        *,
        prepared: RepositoryPreparedComparisonStratumV1,
        sealed_batch: RepositorySealedTemporalBatchV1,
        completion_authority: SessionAnalysisCompletionAuthority,
        analysis_run: SessionAnalysisRunRecord | None = None,
    ) -> RepositorySealedComparisonStratumV1:
        run = (
            self._analysis_run_locked(
                connection, prepared.expected_analysis_run_id
            )
            if analysis_run is None
            else SessionAnalysisRunRecord.model_validate(
                analysis_run.model_dump(mode="python")
            )
        )
        if run.status is not AnalysisRunStatus.COMPLETED or run.finished_at is None:
            raise DatabaseInvariantError(
                "comparison sealing requires a completed analysis run"
            )
        sealed_at = max(self._clock(), run.finished_at, sealed_batch.sealed_at)
        _to_us(sealed_at)
        job_row = connection.execute(
            "SELECT * FROM analysis_jobs WHERE job_id=?",
            (completion_authority.job_id,),
        ).fetchone()
        grant_row = connection.execute(
            "SELECT * FROM automation_grants WHERE grant_id=?",
            (completion_authority.automation_grant_id,),
        ).fetchone()
        if job_row is None or grant_row is None:
            raise DatabaseInvariantError(
                "comparison seal automation authority is missing"
            )
        if (
            job_row["lease_owner"] != completion_authority.lease_owner
            or job_row["lease_token"] != completion_authority.lease_token
        ):
            raise DatabaseInvariantError(
                "comparison seal automation lease is invalid"
            )
        try:
            current_job = ComparisonAnalysisJobAuthorityV1.from_active_record(
                self._job_record(connection, job_row), observed_at=sealed_at
            )
            current_grant = (
                ComparisonAutomationGrantAuthorityV1.from_active_record(
                    self._grant_record(connection, grant_row),
                    observed_at=sealed_at,
                )
            )
        except Exception:
            raise DatabaseInvariantError(
                "comparison seal automation authority is not live"
            ) from None
        prepared_job = prepared.analysis_job
        prepared_grant = prepared.automation_grant
        if (
            current_job.job_id != prepared_job.job_id
            or current_job.stored_job_fingerprint
            != prepared_job.stored_job_fingerprint
            or current_job.lease_authority_fingerprint
            != prepared_job.lease_authority_fingerprint
            or current_job.lease_expires_at != prepared_job.lease_expires_at
            or current_grant.grant_id != prepared_grant.grant_id
            or current_grant.revision != prepared_grant.revision
            or current_grant.fingerprint != prepared_grant.fingerprint
            or current_grant.expires_at != prepared_grant.expires_at
        ):
            raise DatabaseInvariantError(
                "comparison seal authority differs from preparation"
            )
        receipt_id = self._identifiers.fingerprint(
            "comparison-automation-revalidation-receipt-v1",
            (
                prepared.prepared_stratum_id,
                run.draft.run_id,
                sealed_batch.sealed_batch_id,
                to_iso(sealed_at),
            ),
        )
        repository_authority = self._identifiers.fingerprint(
            "comparison-repository-revalidation-authority-v1",
            (
                receipt_id,
                prepared.fingerprint,
                current_job.stored_job_fingerprint,
                current_job.lease_authority_fingerprint,
                current_grant.fingerprint,
            ),
        )
        revalidation_values = {
            "authority_receipt_id": receipt_id,
            "prepared_stratum_id": prepared.prepared_stratum_id,
            "prepared_stratum_fingerprint": prepared.fingerprint,
            "analysis_job_id": current_job.job_id,
            "analysis_job_record_authority_fingerprint": (
                current_job.stored_job_fingerprint
            ),
            "current_job_state": current_job.state_at_preparation,
            "current_job_lease_authority_fingerprint": (
                current_job.lease_authority_fingerprint
            ),
            "current_job_lease_expires_at": current_job.lease_expires_at,
            "automation_grant_id": current_grant.grant_id,
            "current_grant_revision": current_grant.revision,
            "current_grant_authority_fingerprint": current_grant.fingerprint,
            "current_grant_expires_at": current_grant.expires_at,
            "reverified_at": sealed_at,
            "repository_revalidation_authority_fingerprint": (
                repository_authority
            ),
        }
        revalidation = AutomationRevalidationRequestV1(
            **revalidation_values,
            authority_sha256=AutomationRevalidationRequestV1.authority_for(
                **revalidation_values
            ),
        )
        ordered = RepositorySealedComparisonStratumV1.ordered_authority_for(
            prepared_receipt=prepared,
            analysis_run=run,
            sealed_batch=sealed_batch,
            automation_revalidation_request=revalidation,
        )
        sealed_id = RepositorySealedComparisonStratumV1.sealed_stratum_id_for(
            prepared_receipt=prepared,
            analysis_run=run,
            sealed_batch=sealed_batch,
            automation_revalidation_request=revalidation,
            sealed_at=sealed_at,
        )
        return RepositorySealedComparisonStratumV1(
            sealed_stratum_id=sealed_id,
            prepared_receipt=prepared,
            analysis_run=run,
            analysis_run_authority_sha256=(
                session_analysis_run_authority_fingerprint(run)
            ),
            sealed_batch=sealed_batch,
            sealed_batch_sha256=sealed_batch.fingerprint,
            automation_revalidation_request=revalidation,
            ordered_authority_fingerprints=ordered,
            repository_verifier_version=(
                COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_VERSION
            ),
            repository_verifier_fingerprint=(
                COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_FINGERPRINT
            ),
            sealed_at=sealed_at,
        )

    def _begin_sealed_append_locked(
        self,
        connection: sqlite3.Connection,
        sealed: RepositorySealedComparisonStratumV1,
    ) -> tuple[str, str, str]:
        sealed = RepositorySealedComparisonStratumV1.revalidate_for_persistence(
            sealed
        )
        prepared = sealed.prepared_receipt
        run = sealed.analysis_run
        batch = sealed.sealed_batch
        revalidation = sealed.automation_revalidation_request
        authorization_fingerprint = _domain_sha256(
            "comparison.seal-append-authorization.v1",
            (
                sealed.sealed_stratum_id,
                prepared.prepared_stratum_id,
                run.draft.run_id,
                batch.sealed_batch_id,
                sealed.analysis_run_authority_sha256,
                batch.fingerprint,
                revalidation.fingerprint,
                sealed.fingerprint,
            ),
        )
        operation_id, tag = self._begin_seal_authorization(
            prepared.prepared_stratum_id,
            run.draft.run_id,
            batch.sealed_batch_id,
            sealed.sealed_stratum_id,
            prepared.fingerprint,
            sealed.analysis_run_authority_sha256,
            batch.fingerprint,
            revalidation.fingerprint,
            sealed.fingerprint,
            authorization_fingerprint,
        )
        try:
            connection.execute(
                """INSERT INTO comparison_seal_append_authorizations(
                       operation_id,prepared_stratum_id,analysis_run_id,
                       sealed_batch_id,sealed_stratum_id,prepared_fingerprint,
                       run_authority_fingerprint,sealed_batch_fingerprint,
                       revalidation_fingerprint,sealed_fingerprint,
                       authorization_fingerprint,authorization_tag)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    operation_id,
                    prepared.prepared_stratum_id,
                    run.draft.run_id,
                    batch.sealed_batch_id,
                    sealed.sealed_stratum_id,
                    prepared.fingerprint,
                    sealed.analysis_run_authority_sha256,
                    batch.fingerprint,
                    revalidation.fingerprint,
                    sealed.fingerprint,
                    authorization_fingerprint,
                    tag,
                ),
            )
            return operation_id, authorization_fingerprint, tag
        except Exception:
            self._end_seal_authorization(
                operation_id,
                authorization_fingerprint,
                tag,
            )
            raise

    def _insert_sealed_authorized_locked(
        self,
        connection: sqlite3.Connection,
        sealed: RepositorySealedComparisonStratumV1,
        authorization: tuple[str, str, str],
    ) -> None:
        sealed = RepositorySealedComparisonStratumV1.revalidate_for_persistence(
            sealed
        )
        prepared = sealed.prepared_receipt
        run = sealed.analysis_run
        batch = sealed.sealed_batch
        revalidation = sealed.automation_revalidation_request
        operation_id, authorization_fingerprint, tag = authorization
        try:
            connection.execute(
                """INSERT INTO comparison_automation_revalidations(
                       sealed_stratum_id,operation_id,analysis_run_id,
                       contract_version,
                       authority_receipt_id,prepared_stratum_id,
                       prepared_fingerprint,analysis_job_id,
                       job_record_authority_fingerprint,current_job_state,
                       current_job_lease_authority_fingerprint,
                       current_job_lease_expires_at_us,automation_grant_id,
                       current_grant_revision,current_grant_authority_fingerprint,
                       current_grant_expires_at_us,reverified_at_us,
                       repository_revalidation_authority_fingerprint,
                       revalidation_fingerprint)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    sealed.sealed_stratum_id,
                    operation_id,
                    run.draft.run_id,
                    revalidation.contract_version,
                    revalidation.authority_receipt_id,
                    prepared.prepared_stratum_id,
                    prepared.fingerprint,
                    revalidation.analysis_job_id,
                    revalidation.analysis_job_record_authority_fingerprint,
                    revalidation.current_job_state.value,
                    revalidation.current_job_lease_authority_fingerprint,
                    _to_us(revalidation.current_job_lease_expires_at),
                    revalidation.automation_grant_id,
                    revalidation.current_grant_revision,
                    revalidation.current_grant_authority_fingerprint,
                    _to_us(revalidation.current_grant_expires_at),
                    _to_us(revalidation.reverified_at),
                    revalidation.repository_revalidation_authority_fingerprint,
                    revalidation.fingerprint,
                ),
            )
            for ordinal, fingerprint in enumerate(
                sealed.ordered_authority_fingerprints
            ):
                connection.execute(
                    """INSERT INTO comparison_seal_authority_commitments(
                           sealed_stratum_id,operation_id,analysis_run_id,
                           ordinal,fingerprint)
                       VALUES(?,?,?,?,?)""",
                    (
                        sealed.sealed_stratum_id,
                        operation_id,
                        run.draft.run_id,
                        ordinal,
                        fingerprint,
                    ),
                )
            connection.execute(
                """INSERT INTO comparison_sealed_stratum_roots(
                       sealed_stratum_id,operation_id,contract_version,
                       prepared_stratum_id,prepared_fingerprint,analysis_run_id,
                       run_authority_fingerprint,sealed_batch_id,
                       sealed_batch_fingerprint,revalidation_fingerprint,
                       repository_verifier_version,
                       repository_verifier_fingerprint,sealed_at_us,
                       authority_commitment_count,sealed_fingerprint)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    sealed.sealed_stratum_id,
                    operation_id,
                    sealed.contract_version,
                    prepared.prepared_stratum_id,
                    prepared.fingerprint,
                    run.draft.run_id,
                    sealed.analysis_run_authority_sha256,
                    batch.sealed_batch_id,
                    batch.fingerprint,
                    revalidation.fingerprint,
                    sealed.repository_verifier_version,
                    sealed.repository_verifier_fingerprint,
                    _to_us(sealed.sealed_at),
                    len(sealed.ordered_authority_fingerprints),
                    sealed.fingerprint,
                ),
            )
            connection.execute(
                "DELETE FROM comparison_seal_append_authorizations WHERE operation_id=?",
                (operation_id,),
            )
        finally:
            self._end_seal_authorization(
                operation_id,
                authorization_fingerprint,
                tag,
            )

    def _authorize_completion_seal_locked(
        self,
        connection: sqlite3.Connection,
        *,
        sealed_batch: RepositorySealedTemporalBatchV1,
        completion_authority: SessionAnalysisCompletionAuthority,
        finished_at: datetime,
    ) -> tuple[
        RepositorySealedComparisonStratumV1,
        tuple[str, str, str],
    ] | None:
        """Build and authorize the root-last seal before terminal UPDATE."""

        row = connection.execute(
            """SELECT prepared_stratum_id FROM comparison_prepared_stratum_roots
               WHERE expected_analysis_run_id=?""",
            (sealed_batch.completion_request.analysis_run_id,),
        ).fetchone()
        if row is None:
            return None
        prepared = self._hydrate_prepared_locked(
            connection, str(row["prepared_stratum_id"])
        )
        running = self._analysis_run_locked(
            connection, prepared.expected_analysis_run_id
        )
        if running.status is not AnalysisRunStatus.RUNNING:
            raise DatabaseInvariantError(
                "comparison seal authorization requires a running analysis"
            )
        completed = SessionAnalysisRunRecord(
            draft=running.draft,
            status=AnalysisRunStatus.COMPLETED,
            finished_at=finished_at,
        )
        sealed = self._build_sealed_locked(
            connection,
            prepared=prepared,
            sealed_batch=sealed_batch,
            completion_authority=completion_authority,
            analysis_run=completed,
        )
        authorization = self._begin_sealed_append_locked(connection, sealed)
        return sealed, authorization

    def _commit_completion_seal_locked(
        self,
        connection: sqlite3.Connection,
        pending: tuple[
            RepositorySealedComparisonStratumV1,
            tuple[str, str, str],
        ],
    ) -> RepositorySealedComparisonStratumV1:
        sealed, authorization = pending
        self._insert_sealed_authorized_locked(
            connection,
            sealed,
            authorization,
        )
        verified = self._hydrate_sealed_locked(
            connection, sealed.sealed_stratum_id
        )
        if verified != sealed:
            raise DatabaseInvariantError(
                "stored comparison seal did not rederive exactly"
            )
        return verified

    def _cancel_completion_seal_authorization(
        self,
        pending: tuple[
            RepositorySealedComparisonStratumV1,
            tuple[str, str, str],
        ],
    ) -> None:
        _, (operation_id, authorization_fingerprint, tag) = pending
        self._end_seal_authorization(
            operation_id,
            authorization_fingerprint,
            tag,
        )

    def _replay_completed_locked(
        self,
        connection: sqlite3.Connection,
        *,
        sealed_batch: RepositorySealedTemporalBatchV1,
    ) -> RepositorySealedComparisonStratumV1 | None:
        row = connection.execute(
            """SELECT sealed_stratum_id FROM comparison_sealed_stratum_roots
               WHERE analysis_run_id=?""",
            (sealed_batch.completion_request.analysis_run_id,),
        ).fetchone()
        prepared = connection.execute(
            """SELECT 1 FROM comparison_prepared_stratum_roots
               WHERE expected_analysis_run_id=?""",
            (sealed_batch.completion_request.analysis_run_id,),
        ).fetchone()
        if row is None:
            if prepared is not None:
                raise DatabaseInvariantError(
                    "completed comparison run is missing its atomic seal"
                )
            return None
        sealed = self._hydrate_sealed_locked(
            connection, str(row["sealed_stratum_id"])
        )
        if sealed.sealed_batch != sealed_batch:
            raise DatabaseInvariantError(
                "completed comparison replay differs from stored graph"
            )
        return sealed


__all__ = ["SqliteTemporalComparisonStratumRepository"]
