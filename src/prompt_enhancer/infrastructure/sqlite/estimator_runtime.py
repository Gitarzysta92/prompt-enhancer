"""SQLite persistence for the execution-only estimator runtime vertical."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import hashlib
import sqlite3

from ...application.estimators.contracts import (
    EstimatorRoute,
    EstimatorStageKind,
    ExecutionDestination,
    MetricEstimateState,
    MetricValueKind,
    RetentionClass,
)
from ...application.estimators.runtime_contracts import (
    RuntimeEvidencePacketReceipt,
    RuntimeRetrievalScoreKind,
    estimator_stage_fingerprint,
)
from ...application.estimators.runtime_persistence import (
    DurableRuntimeAuthorizationKind,
    DurableRuntimeAuthorizationReceipt,
    DurableRuntimePacketBinding,
    EstimatorRuntimeCheckpointReceipt,
    EstimatorRuntimeJobBinding,
    EstimatorRuntimeLaunch,
    EstimatorRuntimeMetricObservation,
    EstimatorRuntimePrivacyDeleteOutcome,
    EstimatorRuntimeRetrievalHit,
    EstimatorRuntimeRetrievalReceipt,
    EstimatorRuntimeSnapshot,
    EstimatorRuntimeStageAttemptReceipt,
    EstimatorRuntimeStageOutcomeReceipt,
    EstimatorRuntimeStageOutcomeState,
    EstimatorRuntimeState,
    EstimatorRuntimeStateReceipt,
    TERMINAL_ESTIMATOR_RUNTIME_STATES,
)
from ...application.jobs import AnalysisJobKind, AnalysisJobState
from ...database import DatabaseInvariantError
from ...domain import Provider
from ._common import ConnectionScope, require_safe_id, require_utc, to_iso
from .analysis_jobs import SqliteAnalysisJobRepository
from .estimators import SqliteEstimatorRepository


_MIN_TIMESTAMP_US = -62_135_596_800_000_000
_MAX_TIMESTAMP_US = 253_402_300_799_999_999
_STATE_TRANSITIONS = {
    EstimatorRuntimeState.CREATED: {
        EstimatorRuntimeState.RUNNING,
        EstimatorRuntimeState.CANCELLED,
        EstimatorRuntimeState.SUPERSEDED,
        EstimatorRuntimeState.FAILED,
    },
    EstimatorRuntimeState.RUNNING: {
        EstimatorRuntimeState.PARTIAL,
        EstimatorRuntimeState.CANCELLED,
        EstimatorRuntimeState.SUPERSEDED,
        EstimatorRuntimeState.FAILED,
    },
}

BeginAuthorization = Callable[[str, str, str], tuple[str, str]]
EndAuthorization = Callable[[str, str, str, str, str], None]


def _to_us(value: datetime) -> int:
    value = require_utc(value)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = value - epoch
    result = (
        delta.days * 86_400_000_000
        + delta.seconds * 1_000_000
        + delta.microseconds
    )
    if not _MIN_TIMESTAMP_US <= result <= _MAX_TIMESTAMP_US:
        raise ValueError("timestamp is outside the supported range")
    return result


def _from_us(value: int) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DatabaseInvariantError("runtime timestamp is invalid")
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=value)


def _domain_digest(domain: str, value: str) -> str:
    return hashlib.sha256(f"{domain}:{value}".encode("ascii")).hexdigest()


class SqliteEstimatorRuntimeRepository:
    """Append-only runtime receipts guarded by an application-held HMAC seam."""

    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
        *,
        begin_write_authorization: BeginAuthorization,
        end_write_authorization: EndAuthorization,
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized
        self._begin_write_authorization = begin_write_authorization
        self._end_write_authorization = end_write_authorization

    @contextmanager
    def _authorized(
        self,
        connection: sqlite3.Connection,
        authorization_id: str,
        execution_id: str,
        job_id: str,
    ) -> Iterator[None]:
        operation_id, tag = self._begin_write_authorization(
            authorization_id, execution_id, job_id
        )
        try:
            # Python cannot mark registered SQLite functions SQLITE_INNOCUOUS.
            # Trust the private schema only while the in-memory HMAC capability
            # is live on this one connection, then fail closed again.
            connection.execute("PRAGMA trusted_schema=ON")
            inserted = False
            try:
                connection.execute(
                    """
                    INSERT INTO estimator_runtime_write_authorizations(
                        operation_id, authorization_id, execution_id, job_id,
                        authorization_tag
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (operation_id, authorization_id, execution_id, job_id, tag),
                )
                inserted = True
                try:
                    yield
                finally:
                    deleted = connection.execute(
                        """
                        DELETE FROM estimator_runtime_write_authorizations
                        WHERE operation_id=? AND authorization_id=?
                          AND execution_id=? AND job_id=? AND authorization_tag=?
                        """,
                        (operation_id, authorization_id, execution_id, job_id, tag),
                    )
                    if deleted.rowcount != 1:
                        raise DatabaseInvariantError(
                            "runtime write authorization cleanup failed"
                        )
                    inserted = False
            finally:
                if inserted:
                    connection.rollback()
                connection.execute("PRAGMA trusted_schema=OFF")
        finally:
            self._end_write_authorization(
                operation_id, authorization_id, execution_id, job_id, tag
            )

    @staticmethod
    def _automation_grant_is_valid_locked(
        connection: sqlite3.Connection,
        authorization: DurableRuntimeAuthorizationReceipt,
        *,
        now: datetime,
    ) -> bool:
        if authorization.kind is not DurableRuntimeAuthorizationKind.AUTOMATION_ONCE:
            return authorization.automation_grant_id is None
        if (
            authorization.automation_grant_id is None
            or authorization.destination is not ExecutionDestination.LOCAL_DEVICE
        ):
            return False
        grant = connection.execute(
            """
            SELECT provider,project_id,route,max_gpu_workers,max_cpu_workers,
                   pause_on_battery,maximum_session_seconds,local_only,
                   remote_requires_fresh_approval,state,expires_at
            FROM automation_grants WHERE grant_id=?
            """,
            (authorization.automation_grant_id,),
        ).fetchone()
        if grant is None:
            return False
        grant_metrics = tuple(
            row["metric_key"]
            for row in connection.execute(
                """
                SELECT metric_key FROM automation_grant_metrics
                WHERE grant_id=? ORDER BY ordinal
                """,
                (authorization.automation_grant_id,),
            )
        )
        return (
            grant["provider"] == authorization.provider.value
            and grant["project_id"] == authorization.project_id
            and grant["route"] == authorization.route.value
            and grant["route"] == "balanced"
            and grant["max_gpu_workers"] == 1
            and grant["max_cpu_workers"] == 1
            and grant["pause_on_battery"] == 1
            and grant["maximum_session_seconds"] == 1800
            and bool(grant["local_only"])
            and bool(grant["remote_requires_fresh_approval"])
            and grant["state"] == "active"
            and to_iso(now) < grant["expires_at"]
            and grant_metrics
            == tuple(item.metric_key for item in authorization.packet_bindings)
        )

    def _validate_launch_sql(
        self, connection: sqlite3.Connection, launch: EstimatorRuntimeLaunch
    ) -> None:
        authorization = launch.authorization
        target = connection.execute(
            "SELECT project_id,provider FROM sessions WHERE session_id=?",
            (authorization.session_id,),
        ).fetchone()
        if target is None:
            raise DatabaseInvariantError("runtime session does not exist")
        if (
            target["project_id"] != authorization.project_id
            or target["provider"] != authorization.provider.value
        ):
            raise DatabaseInvariantError("runtime target provenance disagrees")
        if connection.execute(
            "SELECT 1 FROM estimator_plans WHERE plan_fingerprint=?",
            (authorization.plan_fingerprint,),
        ).fetchone() is None:
            raise DatabaseInvariantError("runtime plan is not registered")
        registered_plan = SqliteEstimatorRepository(
            self._connection_scope, self._ensure_initialized
        )._hydrate_plan(connection, authorization.plan_fingerprint)
        if (
            registered_plan.route is not authorization.route
            or registered_plan.redactor_version != authorization.redactor_version
            or registered_plan.redactor_sha256 != authorization.redactor_sha256
        ):
            raise DatabaseInvariantError("runtime plan provenance disagrees")
        provider_identities = {
            (
                identity.provider,
                identity.adapter_version,
                identity.provider_schema_version,
            )
            for identity in registered_plan.provider_schemas
        }
        if not any(
            provider is authorization.provider
            and schema == authorization.provider_schema_version
            for provider, _adapter, schema in provider_identities
        ):
            raise DatabaseInvariantError("runtime provider schema is not registered")
        questions = {
            (question.metric_key, question.canonical_fingerprint)
            for question in registered_plan.question_specs
        }
        receipts = {receipt.metric_key: receipt for receipt in launch.packet_receipts}
        for binding in authorization.packet_bindings:
            if (binding.metric_key, binding.metric_question_fingerprint) not in questions:
                raise DatabaseInvariantError("runtime metric question is not in the plan")
            receipt = receipts[binding.metric_key]
            packet_provider = (
                receipt.provider,
                receipt.adapter_version,
                receipt.provider_schema_version,
            )
            if (
                receipt.packet_schema_version
                != registered_plan.evidence_packet_schema_version
                or packet_provider not in provider_identities
                or receipt.preprocessing_version
                != registered_plan.preprocessing_version
                or receipt.preprocessing_sha256 != registered_plan.preprocessing_sha256
                or receipt.router_version != registered_plan.router_version
                or receipt.router_sha256 != registered_plan.router_sha256
                or receipt.redactor_version != registered_plan.redactor_version
                or receipt.redactor_sha256 != registered_plan.redactor_sha256
            ):
                raise DatabaseInvariantError(
                    "runtime packet provenance disagrees with its registered plan"
                )
        if not self._automation_grant_is_valid_locked(
            connection, authorization, now=launch.consumed_at
        ):
            raise DatabaseInvariantError(
                "runtime automation grant is absent, expired, revoked, or out of scope"
            )
        revocation_key = _domain_digest(
            "estimator-runtime-revocation-v1", authorization.execution_id
        )
        if connection.execute(
            "SELECT 1 FROM estimator_runtime_deletion_tombstones WHERE revocation_key=?",
            (revocation_key,),
        ).fetchone():
            raise DatabaseInvariantError("runtime execution was privacy revoked")

    def launch(self, launch: EstimatorRuntimeLaunch) -> EstimatorRuntimeSnapshot:
        self._ensure_initialized()
        launch = EstimatorRuntimeLaunch.model_validate(
            launch.model_dump(mode="python")
        )
        authorization = launch.authorization
        dedupe_key = _domain_digest(
            "estimator-runtime-job-v1", authorization.canonical_fingerprint
        )
        timestamp = to_iso(launch.consumed_at)
        consumed_at_us = _to_us(launch.consumed_at)
        with self._connection_scope() as connection:
            try:
                connection.execute("PRAGMA secure_delete=ON")
                if int(connection.execute("PRAGMA secure_delete").fetchone()[0]) != 1:
                    raise DatabaseInvariantError(
                        "runtime privacy deletion requires SQLite secure_delete"
                    )
                connection.execute("BEGIN IMMEDIATE")
                self._validate_launch_sql(connection, launch)
                if connection.execute(
                    "SELECT 1 FROM estimator_runtime_authorizations WHERE authorization_id=? OR job_id=? OR execution_id=?",
                    (
                        authorization.authorization_id,
                        authorization.job_id,
                        authorization.execution_id,
                    ),
                ).fetchone():
                    raise DatabaseInvariantError(
                        "runtime authorization is one-shot and already consumed"
                    )
                with self._authorized(
                    connection,
                    authorization.authorization_id,
                    authorization.execution_id,
                    authorization.job_id,
                ):
                    connection.execute(
                        """
                        INSERT INTO analysis_jobs(
                            job_id,dedupe_key,kind,provider,project_id,session_id,
                            input_fingerprint,provenance_fingerprint,
                            estimator_plan_version,redactor_version,
                            provider_schema_version,automation_grant_id,local_only,
                            state,stage_number,progress_completed,progress_total,
                            attempt_count,max_attempts,available_at,cancel_requested,
                            lease_owner,lease_token,lease_expires_at,last_error_code,
                            terminal_reason_code,created_at,updated_at,terminal_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,'queued',NULL,0,8,0,?,?,0,
                                  NULL,NULL,NULL,NULL,NULL,?,?,NULL)
                        """,
                        (
                            authorization.job_id,
                            dedupe_key,
                            AnalysisJobKind.ESTIMATOR_EXECUTION.value,
                            authorization.provider.value,
                            authorization.project_id,
                            authorization.session_id,
                            authorization.input_fingerprint,
                            authorization.provenance_fingerprint,
                            authorization.plan_fingerprint,
                            authorization.redactor_version,
                            authorization.provider_schema_version,
                            authorization.automation_grant_id,
                            launch.max_attempts,
                            timestamp,
                            timestamp,
                            timestamp,
                        ),
                    )
                    self._insert_authorization(connection, launch)
                    connection.executemany(
                        "INSERT INTO analysis_job_metrics(job_id,metric_key,ordinal) VALUES (?,?,?)",
                        (
                            (authorization.job_id, item.metric_key, ordinal)
                            for ordinal, item in enumerate(
                                authorization.packet_bindings
                            )
                        ),
                    )
                    self._insert_runtime_root(connection, launch)
                    self._insert_packets(connection, launch)
                    self._insert_binding(connection, launch)
                    initial = EstimatorRuntimeStateReceipt(
                        state_receipt_id=_domain_digest(
                            "estimator-runtime-state-v1",
                            f"{authorization.execution_id}:0",
                        ),
                        execution_id=authorization.execution_id,
                        sequence=0,
                        state=EstimatorRuntimeState.CREATED,
                        reason_code="authorization_consumed",
                        recorded_at=launch.consumed_at,
                    )
                    self._insert_state(connection, authorization.authorization_id, initial)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        snapshot = self.get_by_job(authorization.job_id)
        if snapshot is None:
            raise DatabaseInvariantError("runtime launch was not persisted")
        return snapshot

    @staticmethod
    def _insert_authorization(
        connection: sqlite3.Connection, launch: EstimatorRuntimeLaunch
    ) -> None:
        item = launch.authorization
        connection.execute(
            """
            INSERT INTO estimator_runtime_authorizations(
                authorization_id,authorization_fingerprint,contract_version,
                job_id,execution_id,kind,provider,destination,retention_class,
                project_id,session_id,session_revision_id,window_fingerprint,
                input_fingerprint,provenance_fingerprint,plan_fingerprint,route,
                provider_schema_version,redactor_version,redactor_sha256,
                automation_grant_id,issued_at_us,expires_at_us,packet_count,
                one_shot,preview_text_retained,execution_only,activation_allowed,
                product_metric_write_allowed,private_export_allowed,team_share_allowed
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,0,1,0,0,0,0)
            """,
            (
                item.authorization_id,
                item.canonical_fingerprint,
                item.contract_version,
                item.job_id,
                item.execution_id,
                item.kind.value,
                item.provider.value,
                item.destination.value,
                item.retention_class.value,
                item.project_id,
                item.session_id,
                item.session_revision_id,
                item.window_fingerprint,
                item.input_fingerprint,
                item.provenance_fingerprint,
                item.plan_fingerprint,
                item.route.value,
                item.provider_schema_version,
                item.redactor_version,
                item.redactor_sha256,
                item.automation_grant_id,
                _to_us(item.issued_at),
                _to_us(item.expires_at),
                len(item.packet_bindings),
            ),
        )
        connection.executemany(
            """
            INSERT INTO estimator_runtime_authorization_packets(
                authorization_id,execution_id,ordinal,metric_key,
                metric_question_fingerprint,evidence_packet_fingerprint
            ) VALUES (?,?,?,?,?,?)
            """,
            (
                (
                    item.authorization_id,
                    item.execution_id,
                    ordinal,
                    binding.metric_key,
                    binding.metric_question_fingerprint,
                    binding.evidence_packet_fingerprint,
                )
                for ordinal, binding in enumerate(item.packet_bindings)
            ),
        )
        connection.execute(
            """
            INSERT INTO estimator_runtime_authorization_consumptions(
                authorization_id,execution_id,job_id,consumed_at_us
            ) VALUES (?,?,?,?)
            """,
            (
                item.authorization_id,
                item.execution_id,
                item.job_id,
                _to_us(launch.consumed_at),
            ),
        )

    @staticmethod
    def _insert_runtime_root(
        connection: sqlite3.Connection, launch: EstimatorRuntimeLaunch
    ) -> None:
        item = launch.authorization
        values = (
            item.execution_id,
            item.authorization_id,
            item.job_id,
            item.plan_fingerprint,
            item.route.value,
            item.provider.value,
            item.project_id,
            item.session_id,
            item.session_revision_id,
            item.window_fingerprint,
            item.input_fingerprint,
            item.provenance_fingerprint,
            _to_us(launch.consumed_at),
        )
        connection.execute(
            """
            INSERT INTO estimator_runtime_executions(
                execution_id,authorization_id,job_id,plan_fingerprint,route,
                provider,project_id,session_id,session_revision_id,
                window_fingerprint,input_fingerprint,provenance_fingerprint,
                created_at_us,execution_only,activation_allowed,
                product_metric_write_allowed,private_export_allowed,
                team_share_allowed
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,0,0,0,0)
            """,
            values,
        )

    @staticmethod
    def _insert_binding(
        connection: sqlite3.Connection, launch: EstimatorRuntimeLaunch
    ) -> None:
        item = launch.authorization
        connection.execute(
            """
            INSERT INTO estimator_runtime_job_bindings(
                job_id,execution_id,authorization_id,authorization_fingerprint,
                plan_fingerprint,route,provider,project_id,session_id,
                session_revision_id,window_fingerprint,input_fingerprint,
                provenance_fingerprint,created_at_us
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                item.job_id,
                item.execution_id,
                item.authorization_id,
                item.canonical_fingerprint,
                item.plan_fingerprint,
                item.route.value,
                item.provider.value,
                item.project_id,
                item.session_id,
                item.session_revision_id,
                item.window_fingerprint,
                item.input_fingerprint,
                item.provenance_fingerprint,
                _to_us(launch.consumed_at),
            ),
        )

    @staticmethod
    def _insert_packets(
        connection: sqlite3.Connection, launch: EstimatorRuntimeLaunch
    ) -> None:
        authorization = launch.authorization
        for ordinal, item in enumerate(launch.packet_receipts):
            connection.execute(
                """
                INSERT INTO estimator_runtime_packet_receipts(
                    execution_id,authorization_id,ordinal,packet_fingerprint,
                    packet_schema_version,plan_fingerprint,metric_key,
                    metric_question_fingerprint,route,scope_projection_fingerprint,
                    scope_router_output_fingerprint,retrieval_query_fingerprint,
                    requirements_sha256,chronology_sha256,retrieval_index_sha256,
                    provider,adapter_version,provider_schema_version,
                    preprocessing_version,preprocessing_sha256,router_version,
                    router_sha256,redactor_version,redactor_sha256,
                    source_record_count,requirement_count,chronology_count,
                    action_count,decision_count,feedback_count,verification_count,
                    evidence_ref_count,created_at_us,ephemeral_payload_retained,
                    execution_only,activation_allowed,
                    private_export_allowed,team_share_allowed
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,1,0,0,0)
                """,
                (
                    authorization.execution_id,
                    authorization.authorization_id,
                    ordinal,
                    item.packet_fingerprint,
                    item.packet_schema_version,
                    item.plan_fingerprint,
                    item.metric_key,
                    item.metric_question_fingerprint,
                    item.route.value,
                    item.scope_projection_fingerprint,
                    item.scope_router_output_fingerprint,
                    item.retrieval_query_fingerprint,
                    item.requirements_sha256,
                    item.chronology_sha256,
                    item.retrieval_index_sha256,
                    item.provider.value,
                    item.adapter_version,
                    item.provider_schema_version,
                    item.preprocessing_version,
                    item.preprocessing_sha256,
                    item.router_version,
                    item.router_sha256,
                    item.redactor_version,
                    item.redactor_sha256,
                    item.source_record_count,
                    item.requirement_count,
                    item.chronology_count,
                    item.action_count,
                    item.decision_count,
                    item.feedback_count,
                    item.verification_count,
                    len(item.opaque_evidence_refs),
                    _to_us(item.created_at),
                ),
            )
            connection.executemany(
                """
                INSERT INTO estimator_runtime_packet_refs(
                    execution_id,packet_fingerprint,authorization_id,ordinal,
                    evidence_reference_id
                ) VALUES (?,?,?,?,?)
                """,
                (
                    (
                        authorization.execution_id,
                        item.packet_fingerprint,
                        authorization.authorization_id,
                        ref_ordinal,
                        reference,
                    )
                    for ref_ordinal, reference in enumerate(item.opaque_evidence_refs)
                ),
            )

    @staticmethod
    def _insert_state(
        connection: sqlite3.Connection,
        authorization_id: str,
        receipt: EstimatorRuntimeStateReceipt,
    ) -> None:
        connection.execute(
            """
            INSERT INTO estimator_runtime_state_receipts(
                state_receipt_id,execution_id,authorization_id,sequence,
                previous_state_receipt_fingerprint,state,reason_code,
                recorded_at_us,receipt_fingerprint
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                receipt.state_receipt_id,
                receipt.execution_id,
                authorization_id,
                receipt.sequence,
                receipt.previous_state_receipt_fingerprint,
                receipt.state.value,
                receipt.reason_code,
                _to_us(receipt.recorded_at),
                receipt.canonical_fingerprint,
            ),
        )

    @staticmethod
    def _authorization(
        connection: sqlite3.Connection, row: sqlite3.Row
    ) -> DurableRuntimeAuthorizationReceipt:
        bindings = tuple(
            DurableRuntimePacketBinding(
                metric_key=item["metric_key"],
                metric_question_fingerprint=item["metric_question_fingerprint"],
                evidence_packet_fingerprint=item["evidence_packet_fingerprint"],
            )
            for item in connection.execute(
                "SELECT * FROM estimator_runtime_authorization_packets WHERE authorization_id=? ORDER BY ordinal",
                (row["authorization_id"],),
            )
        )
        result = DurableRuntimeAuthorizationReceipt(
            authorization_id=row["authorization_id"],
            job_id=row["job_id"],
            execution_id=row["execution_id"],
            kind=DurableRuntimeAuthorizationKind(row["kind"]),
            provider=Provider(row["provider"]),
            destination=ExecutionDestination(row["destination"]),
            retention_class=RetentionClass(row["retention_class"]),
            project_id=row["project_id"],
            session_id=row["session_id"],
            session_revision_id=row["session_revision_id"],
            window_fingerprint=row["window_fingerprint"],
            input_fingerprint=row["input_fingerprint"],
            provenance_fingerprint=row["provenance_fingerprint"],
            plan_fingerprint=row["plan_fingerprint"],
            route=EstimatorRoute(row["route"]),
            provider_schema_version=row["provider_schema_version"],
            redactor_version=row["redactor_version"],
            redactor_sha256=row["redactor_sha256"],
            packet_bindings=bindings,
            automation_grant_id=row["automation_grant_id"],
            issued_at=_from_us(row["issued_at_us"]),
            expires_at=_from_us(row["expires_at_us"]),
        )
        if result.canonical_fingerprint != row["authorization_fingerprint"]:
            raise DatabaseInvariantError("runtime authorization fingerprint disagrees")
        return result

    @staticmethod
    def _binding(row: sqlite3.Row) -> EstimatorRuntimeJobBinding:
        return EstimatorRuntimeJobBinding(
            job_id=row["job_id"],
            execution_id=row["execution_id"],
            authorization_id=row["authorization_id"],
            authorization_fingerprint=row["authorization_fingerprint"],
            plan_fingerprint=row["plan_fingerprint"],
            route=EstimatorRoute(row["route"]),
            provider=Provider(row["provider"]),
            project_id=row["project_id"],
            session_id=row["session_id"],
            session_revision_id=row["session_revision_id"],
            window_fingerprint=row["window_fingerprint"],
            input_fingerprint=row["input_fingerprint"],
            provenance_fingerprint=row["provenance_fingerprint"],
            created_at=_from_us(row["created_at_us"]),
        )

    @staticmethod
    def _states(
        connection: sqlite3.Connection, execution_id: str
    ) -> tuple[EstimatorRuntimeStateReceipt, ...]:
        return tuple(
            EstimatorRuntimeStateReceipt(
                state_receipt_id=row["state_receipt_id"],
                execution_id=row["execution_id"],
                sequence=row["sequence"],
                previous_state_receipt_fingerprint=row[
                    "previous_state_receipt_fingerprint"
                ],
                state=EstimatorRuntimeState(row["state"]),
                reason_code=row["reason_code"],
                recorded_at=_from_us(row["recorded_at_us"]),
            )
            for row in connection.execute(
                "SELECT * FROM estimator_runtime_state_receipts WHERE execution_id=? ORDER BY sequence",
                (execution_id,),
            )
        )

    @staticmethod
    def _attempts(
        connection: sqlite3.Connection, execution_id: str
    ) -> tuple[EstimatorRuntimeStageAttemptReceipt, ...]:
        return tuple(
            EstimatorRuntimeStageAttemptReceipt(
                attempt_id=row["attempt_id"],
                execution_id=row["execution_id"],
                metric_key=row["metric_key"],
                metric_question_fingerprint=row["metric_question_fingerprint"],
                evidence_packet_fingerprint=row["evidence_packet_fingerprint"],
                stage_ordinal=row["stage_ordinal"],
                stage_kind=EstimatorStageKind(row["stage_kind"]),
                stage_fingerprint=row["stage_fingerprint"],
                attempt_ordinal=row["attempt_ordinal"],
                started_at=_from_us(row["started_at_us"]),
            )
            for row in connection.execute(
                "SELECT * FROM estimator_runtime_stage_attempts WHERE execution_id=? ORDER BY metric_key,stage_ordinal,attempt_ordinal",
                (execution_id,),
            )
        )

    @staticmethod
    def _outcomes(
        connection: sqlite3.Connection, execution_id: str
    ) -> tuple[EstimatorRuntimeStageOutcomeReceipt, ...]:
        return tuple(
            EstimatorRuntimeStageOutcomeReceipt(
                outcome_id=row["outcome_id"],
                attempt_id=row["attempt_id"],
                execution_id=row["execution_id"],
                state=EstimatorRuntimeStageOutcomeState(row["state"]),
                reason_code=row["reason_code"],
                output_fingerprint=row["output_fingerprint"],
                finished_at=_from_us(row["finished_at_us"]),
            )
            for row in connection.execute(
                "SELECT * FROM estimator_runtime_stage_outcomes WHERE execution_id=? ORDER BY finished_at_us,outcome_id",
                (execution_id,),
            )
        )

    @staticmethod
    def _checkpoints(
        connection: sqlite3.Connection, execution_id: str
    ) -> tuple[EstimatorRuntimeCheckpointReceipt, ...]:
        return tuple(
            EstimatorRuntimeCheckpointReceipt(
                checkpoint_id=row["checkpoint_id"],
                execution_id=row["execution_id"],
                metric_key=row["metric_key"],
                sequence=row["sequence"],
                previous_checkpoint_fingerprint=row[
                    "previous_checkpoint_fingerprint"
                ],
                last_completed_stage_ordinal=row["last_completed_stage_ordinal"],
                next_stage_ordinal=row["next_stage_ordinal"],
                restart_generation=row["restart_generation"],
                state=EstimatorRuntimeState(row["state"]),
                reason_code=row["reason_code"],
                recorded_at=_from_us(row["recorded_at_us"]),
            )
            for row in connection.execute(
                "SELECT * FROM estimator_runtime_checkpoints WHERE execution_id=? ORDER BY metric_key,sequence",
                (execution_id,),
            )
        )

    @staticmethod
    def _retrievals(
        connection: sqlite3.Connection, execution_id: str
    ) -> tuple[EstimatorRuntimeRetrievalReceipt, ...]:
        values = []
        for row in connection.execute(
            "SELECT * FROM estimator_runtime_retrievals WHERE execution_id=? ORDER BY metric_key",
            (execution_id,),
        ):
            candidates = tuple(
                item["evidence_reference_id"]
                for item in connection.execute(
                    "SELECT evidence_reference_id FROM estimator_runtime_retrieval_candidates WHERE retrieval_id=? ORDER BY ordinal",
                    (row["retrieval_id"],),
                )
            )
            hits = tuple(
                EstimatorRuntimeRetrievalHit(
                    evidence_reference_id=item["evidence_reference_id"],
                    rank=item["rank"],
                    raw_score=item["raw_score"],
                )
                for item in connection.execute(
                    "SELECT * FROM estimator_runtime_retrieval_hits WHERE retrieval_id=? ORDER BY rank",
                    (row["retrieval_id"],),
                )
            )
            receipt = EstimatorRuntimeRetrievalReceipt(
                retrieval_id=row["retrieval_id"],
                execution_id=row["execution_id"],
                attempt_id=row["attempt_id"],
                metric_key=row["metric_key"],
                metric_question_fingerprint=row["metric_question_fingerprint"],
                evidence_packet_fingerprint=row["evidence_packet_fingerprint"],
                query_fingerprint=row["query_fingerprint"],
                candidate_index_fingerprint=row["candidate_index_fingerprint"],
                candidate_reference_ids=candidates,
                hits=hits,
                created_at=_from_us(row["created_at_us"]),
            )
            if receipt.canonical_fingerprint != row["retrieval_fingerprint"]:
                raise DatabaseInvariantError("runtime retrieval fingerprint disagrees")
            values.append(receipt)
        return tuple(values)

    @staticmethod
    def _observations(
        connection: sqlite3.Connection, execution_id: str
    ) -> tuple[EstimatorRuntimeMetricObservation, ...]:
        values = []
        for row in connection.execute(
            "SELECT * FROM estimator_runtime_metric_observations WHERE execution_id=? ORDER BY metric_key",
            (execution_id,),
        ):
            refs = tuple(
                item["evidence_reference_id"]
                for item in connection.execute(
                    "SELECT evidence_reference_id FROM estimator_runtime_observation_refs WHERE observation_id=? ORDER BY ordinal",
                    (row["observation_id"],),
                )
            )
            receipt = EstimatorRuntimeMetricObservation(
                observation_id=row["observation_id"],
                execution_id=row["execution_id"],
                attempt_id=row["attempt_id"],
                metric_key=row["metric_key"],
                metric_question_fingerprint=row["metric_question_fingerprint"],
                evidence_packet_fingerprint=row["evidence_packet_fingerprint"],
                state=MetricEstimateState(row["state"]),
                value_kind=MetricValueKind(row["value_kind"]),
                numeric_value=row["numeric_value"],
                label_code=row["label_code"],
                numerator=row["numerator"],
                denominator=row["denominator"],
                reason_code=row["reason_code"],
                opaque_evidence_refs=refs,
                observed_at=_from_us(row["observed_at_us"]),
            )
            if receipt.canonical_fingerprint != row["observation_fingerprint"]:
                raise DatabaseInvariantError("runtime observation fingerprint disagrees")
            values.append(receipt)
        return tuple(values)

    @classmethod
    def _snapshot_locked(
        cls, connection: sqlite3.Connection, *, where: str, value: str
    ) -> EstimatorRuntimeSnapshot | None:
        binding_row = connection.execute(
            f"SELECT * FROM estimator_runtime_job_bindings WHERE {where}=?", (value,)
        ).fetchone()
        if binding_row is None:
            return None
        authorization_row = connection.execute(
            "SELECT * FROM estimator_runtime_authorizations WHERE authorization_id=?",
            (binding_row["authorization_id"],),
        ).fetchone()
        job_row = connection.execute(
            "SELECT * FROM analysis_jobs WHERE job_id=?", (binding_row["job_id"],)
        ).fetchone()
        if authorization_row is None or job_row is None:
            raise DatabaseInvariantError("runtime root lineage is incomplete")
        execution_id = binding_row["execution_id"]
        expected_metrics = tuple(
            (row["metric_key"], row["ordinal"])
            for row in connection.execute(
                """
                SELECT metric_key,ordinal FROM estimator_runtime_authorization_packets
                WHERE authorization_id=? ORDER BY ordinal
                """,
                (binding_row["authorization_id"],),
            )
        )
        queue_metrics = tuple(
            (row["metric_key"], row["ordinal"])
            for row in connection.execute(
                """
                SELECT metric_key,ordinal FROM analysis_job_metrics
                WHERE job_id=? ORDER BY ordinal
                """,
                (binding_row["job_id"],),
            )
        )
        packet_metrics = tuple(
            (row["metric_key"], row["ordinal"])
            for row in connection.execute(
                """
                SELECT metric_key,ordinal FROM estimator_runtime_packet_receipts
                WHERE execution_id=? ORDER BY ordinal
                """,
                (execution_id,),
            )
        )
        if not expected_metrics or not (
            expected_metrics == queue_metrics == packet_metrics
        ):
            raise DatabaseInvariantError("runtime metric scope seal disagrees")
        return EstimatorRuntimeSnapshot(
            binding=cls._binding(binding_row),
            authorization=cls._authorization(connection, authorization_row),
            job=SqliteAnalysisJobRepository._record(connection, job_row),
            states=cls._states(connection, execution_id),
            attempts=cls._attempts(connection, execution_id),
            outcomes=cls._outcomes(connection, execution_id),
            checkpoints=cls._checkpoints(connection, execution_id),
            retrievals=cls._retrievals(connection, execution_id),
            observations=cls._observations(connection, execution_id),
            authorization_revoked=connection.execute(
                "SELECT 1 FROM estimator_runtime_authorization_revocations WHERE authorization_id=?",
                (binding_row["authorization_id"],),
            ).fetchone()
            is not None,
        )

    def get_by_job(self, job_id: str) -> EstimatorRuntimeSnapshot | None:
        self._ensure_initialized()
        require_safe_id(job_id)
        with self._connection_scope(readonly=True) as connection:
            return self._snapshot_locked(connection, where="job_id", value=job_id)

    def get_by_execution(self, execution_id: str) -> EstimatorRuntimeSnapshot | None:
        self._ensure_initialized()
        require_safe_id(execution_id)
        with self._connection_scope(readonly=True) as connection:
            return self._snapshot_locked(
                connection, where="execution_id", value=execution_id
            )

    def authorization_is_valid(self, job_id: str, *, now: datetime) -> bool:
        self._ensure_initialized()
        require_safe_id(job_id)
        now_us = _to_us(now)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """
                SELECT a.*,r.authorization_id AS revoked
                FROM estimator_runtime_authorizations a
                JOIN estimator_runtime_authorization_consumptions c
                  ON c.authorization_id=a.authorization_id
                LEFT JOIN estimator_runtime_authorization_revocations r
                  ON r.authorization_id=a.authorization_id
                WHERE a.job_id=? AND c.job_id=a.job_id
                """,
                (job_id,),
            ).fetchone()
            if (
                row is None
                or row["revoked"] is not None
                or not row["issued_at_us"] <= now_us < row["expires_at_us"]
            ):
                return False
            authorization = self._authorization(connection, row)
            return self._automation_grant_is_valid_locked(
                connection, authorization, now=now
            )

    def reconcile_expired(self, *, now: datetime) -> None:
        """Mirror recoverable expired attempts before the generic queue requeues.

        Generic recovery intentionally skips estimator jobs.  This method first
        appends an INTERRUPTED receipt for every open attempt, then atomically
        closes/requeues the exact queue row.  A prior terminal runtime append is
        also converged into the queue without adding another runtime state.
        """

        self._ensure_initialized()
        now = require_utc(now)
        now_us = _to_us(now)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                rows = connection.execute(
                    """
                    SELECT b.execution_id,b.authorization_id,b.job_id,j.*
                    FROM estimator_runtime_job_bindings b
                    JOIN analysis_jobs j ON j.job_id=b.job_id
                    WHERE j.kind='estimator_execution'
                      AND j.state IN ('preprocessing','stage_n')
                      AND j.lease_expires_at<=?
                    ORDER BY j.lease_expires_at,j.job_id
                    """,
                    (to_iso(now),),
                ).fetchall()
                for row in rows:
                    states = self._states(connection, row["execution_id"])
                    if not states:
                        raise DatabaseInvariantError(
                            "runtime recovery state journal is absent"
                        )
                    latest = states[-1]
                    with self._authorized(
                        connection,
                        row["authorization_id"],
                        row["execution_id"],
                        row["job_id"],
                    ):
                        open_attempts = connection.execute(
                            """
                            SELECT a.* FROM estimator_runtime_stage_attempts a
                            LEFT JOIN estimator_runtime_stage_outcomes o
                              ON o.attempt_id=a.attempt_id
                            WHERE a.execution_id=? AND o.attempt_id IS NULL
                            ORDER BY a.metric_key,a.stage_ordinal,a.attempt_ordinal
                            """,
                            (row["execution_id"],),
                        ).fetchall()
                        for attempt in open_attempts:
                            output = connection.execute(
                                """
                                SELECT observation_fingerprint AS output_fingerprint,
                                       observed_at_us AS persisted_at_us
                                FROM estimator_runtime_metric_observations
                                WHERE attempt_id=?
                                UNION ALL
                                SELECT retrieval_fingerprint AS output_fingerprint,
                                       created_at_us AS persisted_at_us
                                FROM estimator_runtime_retrievals
                                WHERE attempt_id=?
                                """,
                                (attempt["attempt_id"], attempt["attempt_id"]),
                            ).fetchone()
                            recovered_output = output is not None
                            connection.execute(
                                """
                                INSERT INTO estimator_runtime_stage_outcomes
                                VALUES (?,?,?,?,?,?,?,?)
                                """,
                                (
                                    _domain_digest(
                                        "estimator-runtime-outcome-v1",
                                        attempt["attempt_id"],
                                    ),
                                    attempt["attempt_id"],
                                    row["execution_id"],
                                    row["authorization_id"],
                                    (
                                        EstimatorRuntimeStageOutcomeState.COMPLETED.value
                                        if recovered_output
                                        else EstimatorRuntimeStageOutcomeState.INTERRUPTED.value
                                    ),
                                    (
                                        "persisted_output_recovered"
                                        if recovered_output
                                        else "lease_expired_interrupted"
                                    ),
                                    (
                                        output["output_fingerprint"]
                                        if recovered_output
                                        else None
                                    ),
                                    max(
                                        now_us,
                                        attempt["started_at_us"],
                                        output["persisted_at_us"]
                                        if recovered_output
                                        else attempt["started_at_us"],
                                    ),
                                ),
                            )
                        if latest.state in TERMINAL_ESTIMATOR_RUNTIME_STATES:
                            queue_state = AnalysisJobState(latest.state.value)
                            reason = latest.reason_code
                            terminal_at = to_iso(now)
                            available_at = terminal_at
                        elif bool(row["cancel_requested"]):
                            reason = row["last_error_code"] or "cancellation_requested"
                            queue_state = (
                                AnalysisJobState.SUPERSEDED
                                if reason in {"input_changed", "provenance_changed"}
                                else AnalysisJobState.CANCELLED
                            )
                            terminal_at = to_iso(now)
                            available_at = terminal_at
                            if latest.state in {
                                EstimatorRuntimeState.CREATED,
                                EstimatorRuntimeState.RUNNING,
                            }:
                                runtime_state = EstimatorRuntimeState(
                                    queue_state.value
                                )
                                self._insert_terminal_state_locked(
                                    connection,
                                    row["authorization_id"],
                                    row["execution_id"],
                                    latest,
                                    state=runtime_state,
                                    reason_code=reason,
                                    recorded_at=now,
                                )
                        elif row["attempt_count"] >= row["max_attempts"]:
                            queue_state = AnalysisJobState.FAILED
                            reason = "lease_expired"
                            terminal_at = to_iso(now)
                            available_at = terminal_at
                            if latest.state in {
                                EstimatorRuntimeState.CREATED,
                                EstimatorRuntimeState.RUNNING,
                            }:
                                self._insert_terminal_state_locked(
                                    connection,
                                    row["authorization_id"],
                                    row["execution_id"],
                                    latest,
                                    state=EstimatorRuntimeState.FAILED,
                                    reason_code=reason,
                                    recorded_at=now,
                                )
                        else:
                            queue_state = AnalysisJobState.QUEUED
                            reason = None
                            terminal_at = None
                            delay_seconds = min(
                                300,
                                5 * (2 ** max(0, int(row["attempt_count"]) - 1)),
                            )
                            available_at = to_iso(now + timedelta(seconds=delay_seconds))
                        connection.execute(
                            """
                            UPDATE analysis_jobs SET state=?,stage_number=NULL,
                                available_at=?,lease_owner=NULL,lease_token=NULL,
                                lease_expires_at=NULL,last_error_code='lease_expired',
                                terminal_reason_code=?,terminal_at=?,updated_at=?
                            WHERE job_id=? AND state IN ('preprocessing','stage_n')
                            """,
                            (
                                queue_state.value,
                                available_at,
                                reason,
                                terminal_at,
                                to_iso(now),
                                row["job_id"],
                            ),
                        )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _invalid_automation_grant_reason_locked(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        now: datetime,
    ) -> str | None:
        grant = connection.execute(
            """
            SELECT provider,project_id,route,max_gpu_workers,max_cpu_workers,
                   pause_on_battery,maximum_session_seconds,local_only,
                   remote_requires_fresh_approval,state,expires_at
            FROM automation_grants WHERE grant_id=?
            """,
            (row["automation_grant_id"],),
        ).fetchone()
        if grant is None:
            return "automation_grant_not_found"
        if grant["state"] == "revoked":
            return "automation_grant_inactive"
        if grant["state"] == "expired" or grant["expires_at"] <= to_iso(now):
            return "automation_grant_expired"
        if (
            grant["route"] != "balanced"
            or grant["max_gpu_workers"] != 1
            or grant["max_cpu_workers"] != 1
            or grant["pause_on_battery"] != 1
            or grant["maximum_session_seconds"] != 1800
        ):
            return "automation_resource_policy_unsupported"

        grant_metrics = tuple(
            (item["metric_key"], item["ordinal"])
            for item in connection.execute(
                """
                SELECT metric_key,ordinal FROM automation_grant_metrics
                WHERE grant_id=? ORDER BY ordinal
                """,
                (row["automation_grant_id"],),
            )
        )
        authorization_metrics = tuple(
            (item["metric_key"], item["ordinal"])
            for item in connection.execute(
                """
                SELECT metric_key,ordinal
                FROM estimator_runtime_authorization_packets
                WHERE authorization_id=? ORDER BY ordinal
                """,
                (row["authorization_id"],),
            )
        )
        queue_metrics = tuple(
            (item["metric_key"], item["ordinal"])
            for item in connection.execute(
                """
                SELECT metric_key,ordinal FROM analysis_job_metrics
                WHERE job_id=? ORDER BY ordinal
                """,
                (row["job_id"],),
            )
        )
        if (
            grant["provider"] != row["authorization_provider"]
            or grant["provider"] != row["job_provider"]
            or grant["project_id"] != row["authorization_project_id"]
            or grant["project_id"] != row["job_project_id"]
            or grant["route"] != row["authorization_route"]
            or row["authorization_destination"] != "local_device"
            or row["job_automation_grant_id"] != row["automation_grant_id"]
            or grant["local_only"] != 1
            or grant["remote_requires_fresh_approval"] != 1
            or not grant_metrics
            or grant_metrics != authorization_metrics
            or grant_metrics != queue_metrics
        ):
            return "automation_grant_scope_mismatch"
        return None

    def reconcile_invalid_automation_grants(self, *, now: datetime) -> None:
        """Atomically close invalid queued automation runtimes in both ledgers.

        This metadata-only maintenance never opens an evidence packet.  The
        runtime state append goes through the exact job-scoped HMAC capability,
        and the queue terminal update shares its transaction.
        """

        self._ensure_initialized()
        now = require_utc(now)
        timestamp = to_iso(now)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                rows = connection.execute(
                    """
                    SELECT b.execution_id,b.authorization_id,b.job_id,
                           a.automation_grant_id,
                           a.provider AS authorization_provider,
                           a.project_id AS authorization_project_id,
                           a.route AS authorization_route,
                           a.destination AS authorization_destination,
                           j.provider AS job_provider,
                           j.project_id AS job_project_id,
                           j.automation_grant_id AS job_automation_grant_id,
                           j.attempt_count
                    FROM estimator_runtime_job_bindings b
                    JOIN estimator_runtime_authorizations a
                      ON a.authorization_id=b.authorization_id
                     AND a.execution_id=b.execution_id
                     AND a.job_id=b.job_id
                    JOIN analysis_jobs j ON j.job_id=b.job_id
                    WHERE a.kind='automation_once'
                      AND j.kind='estimator_execution'
                      AND j.state='queued'
                    ORDER BY j.available_at,j.created_at,j.job_id
                    """
                ).fetchall()
                for row in rows:
                    reason = self._invalid_automation_grant_reason_locked(
                        connection, row, now=now
                    )
                    if reason is None:
                        continue
                    states = self._states(connection, row["execution_id"])
                    if not states:
                        raise DatabaseInvariantError(
                            "runtime reconciliation state journal is absent"
                        )
                    latest = states[-1]
                    if now < latest.recorded_at:
                        continue
                    if latest.state in TERMINAL_ESTIMATOR_RUNTIME_STATES:
                        # A prior runtime append may commit before queue finish.
                        # Mirror that exact receipt; never replace its outcome
                        # with the later invalid-grant classification.
                        queue_state = AnalysisJobState(latest.state.value)
                        terminal_reason = latest.reason_code
                        updated = connection.execute(
                            """
                            UPDATE analysis_jobs SET state=?,stage_number=NULL,
                                terminal_reason_code=?,terminal_at=?,updated_at=?
                            WHERE job_id=? AND state='queued'
                            """,
                            (
                                queue_state.value,
                                terminal_reason,
                                timestamp,
                                timestamp,
                                row["job_id"],
                            ),
                        )
                        if updated.rowcount != 1:
                            raise DatabaseInvariantError(
                                "runtime automation reconciliation conflicted"
                            )
                        continue
                    attempts = self._attempts(connection, row["execution_id"])
                    checkpoints = self._checkpoints(connection, row["execution_id"])
                    if latest.state is EstimatorRuntimeState.CREATED and (
                        attempts or checkpoints
                    ):
                        # CREATED with stage history is internally inconsistent;
                        # do not manufacture a terminal chain around it.
                        continue
                    terminal_checkpoints: tuple[
                        tuple[
                            str,
                            EstimatorRuntimeCheckpointReceipt | None,
                            int,
                        ],
                        ...,
                    ] = ()
                    if latest.state is EstimatorRuntimeState.RUNNING:
                        if int(row["attempt_count"]) < 1:
                            continue
                        if connection.execute(
                            """
                            SELECT 1 FROM estimator_runtime_stage_attempts a
                            LEFT JOIN estimator_runtime_stage_outcomes o
                              ON o.attempt_id=a.attempt_id
                            WHERE a.execution_id=? AND o.attempt_id IS NULL
                            LIMIT 1
                            """,
                            (row["execution_id"],),
                        ).fetchone() is not None:
                            continue
                        if connection.execute(
                            """
                            SELECT 1 FROM estimator_runtime_stage_outcomes
                            WHERE execution_id=? AND finished_at_us>?
                            LIMIT 1
                            """,
                            (row["execution_id"], _to_us(now)),
                        ).fetchone() is not None:
                            # Every attempt is closed above, and outcome append
                            # enforces finished_at >= started_at.  Checking all
                            # outcome kinds therefore prevents a clock rollback
                            # from backdating this terminal append.
                            continue
                        metric_keys = tuple(
                            item["metric_key"]
                            for item in connection.execute(
                                """
                                SELECT metric_key
                                FROM estimator_runtime_authorization_packets
                                WHERE authorization_id=? ORDER BY ordinal
                                """,
                                (row["authorization_id"],),
                            )
                        )
                        if not metric_keys:
                            raise DatabaseInvariantError(
                                "runtime reconciliation metric seal is absent"
                            )
                        latest_by_metric = {
                            item.metric_key: item for item in checkpoints
                        }
                        prepared: list[
                            tuple[
                                str,
                                EstimatorRuntimeCheckpointReceipt | None,
                                int,
                            ]
                        ] = []
                        coherent = True
                        for metric_key in metric_keys:
                            previous = latest_by_metric.get(metric_key)
                            if (
                                previous is not None
                                and (
                                    previous.state
                                    in TERMINAL_ESTIMATOR_RUNTIME_STATES
                                    or now < previous.recorded_at
                                )
                            ):
                                coherent = False
                                break
                            completed_rows = connection.execute(
                                    """
                                    SELECT a.stage_ordinal,
                                           MAX(o.finished_at_us) AS finished_at_us
                                    FROM estimator_runtime_stage_attempts a
                                    JOIN estimator_runtime_stage_outcomes o
                                      ON o.attempt_id=a.attempt_id
                                    WHERE a.execution_id=? AND a.metric_key=?
                                      AND o.state='completed'
                                    GROUP BY a.stage_ordinal
                                    ORDER BY a.stage_ordinal
                                    """,
                                    (row["execution_id"], metric_key),
                                ).fetchall()
                            completed_ordinals = tuple(
                                int(item["stage_ordinal"])
                                for item in completed_rows
                            )
                            if completed_ordinals != tuple(
                                range(1, len(completed_ordinals) + 1)
                            ) or any(
                                int(item["finished_at_us"]) > _to_us(now)
                                for item in completed_rows
                            ):
                                coherent = False
                                break
                            completed_ordinal = len(completed_ordinals)
                            if (
                                previous is not None
                                and previous.last_completed_stage_ordinal
                                > completed_ordinal
                            ):
                                coherent = False
                                break
                            if (
                                previous is not None
                                and previous.restart_generation
                                > int(row["attempt_count"]) - 1
                            ):
                                coherent = False
                                break
                            prepared.append(
                                (metric_key, previous, completed_ordinal)
                            )
                        if not coherent:
                            continue
                        terminal_checkpoints = tuple(prepared)
                    if latest.state not in {
                        EstimatorRuntimeState.CREATED,
                        EstimatorRuntimeState.RUNNING,
                    }:
                        raise DatabaseInvariantError(
                            "runtime reconciliation state is invalid"
                        )
                    with self._authorized(
                            connection,
                            row["authorization_id"],
                            row["execution_id"],
                            row["job_id"],
                        ):
                            if latest.state is EstimatorRuntimeState.RUNNING:
                                for (
                                    metric_key,
                                    previous,
                                    completed_ordinal,
                                ) in terminal_checkpoints:
                                    sequence = (
                                        0 if previous is None else previous.sequence + 1
                                    )
                                    checkpoint = EstimatorRuntimeCheckpointReceipt(
                                        checkpoint_id=_domain_digest(
                                            "runtime-checkpoint",
                                            f"{row['execution_id']}:{metric_key}:{sequence}",
                                        ),
                                        execution_id=row["execution_id"],
                                        metric_key=metric_key,
                                        sequence=sequence,
                                        previous_checkpoint_fingerprint=(
                                            None
                                            if previous is None
                                            else previous.canonical_fingerprint
                                        ),
                                        last_completed_stage_ordinal=(
                                            completed_ordinal
                                        ),
                                        next_stage_ordinal=None,
                                        restart_generation=(
                                            int(row["attempt_count"]) - 1
                                        ),
                                        state=EstimatorRuntimeState.CANCELLED,
                                        reason_code=reason,
                                        recorded_at=now,
                                    )
                                    self._insert_checkpoint_locked(
                                        connection,
                                        row["authorization_id"],
                                        checkpoint,
                                    )
                            self._insert_terminal_state_locked(
                                connection,
                                row["authorization_id"],
                                row["execution_id"],
                                latest,
                                state=EstimatorRuntimeState.CANCELLED,
                                reason_code=reason,
                                recorded_at=now,
                            )
                    queue_state = AnalysisJobState.CANCELLED
                    terminal_reason = reason
                    updated = connection.execute(
                        """
                        UPDATE analysis_jobs SET state=?,stage_number=NULL,
                            cancel_requested=1,last_error_code=?,
                            terminal_reason_code=?,terminal_at=?,updated_at=?
                        WHERE job_id=? AND state='queued'
                        """,
                        (
                            queue_state.value,
                            terminal_reason,
                            terminal_reason,
                            timestamp,
                            timestamp,
                            row["job_id"],
                        ),
                    )
                    if updated.rowcount != 1:
                        raise DatabaseInvariantError(
                            "runtime automation reconciliation conflicted"
                        )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _insert_terminal_state_locked(
        connection: sqlite3.Connection,
        authorization_id: str,
        execution_id: str,
        latest: EstimatorRuntimeStateReceipt,
        *,
        state: EstimatorRuntimeState,
        reason_code: str,
        recorded_at: datetime,
    ) -> None:
        receipt = EstimatorRuntimeStateReceipt(
            state_receipt_id=_domain_digest(
                "estimator-runtime-state-v1", f"{execution_id}:{latest.sequence + 1}"
            ),
            execution_id=execution_id,
            sequence=latest.sequence + 1,
            previous_state_receipt_fingerprint=latest.canonical_fingerprint,
            state=state,
            reason_code=reason_code,
            recorded_at=recorded_at,
        )
        SqliteEstimatorRuntimeRepository._insert_state(
            connection, authorization_id, receipt
        )

    @staticmethod
    def _insert_checkpoint_locked(
        connection: sqlite3.Connection,
        authorization_id: str,
        receipt: EstimatorRuntimeCheckpointReceipt,
    ) -> None:
        connection.execute(
            """
            INSERT INTO estimator_runtime_checkpoints(
                checkpoint_id,execution_id,authorization_id,metric_key,
                sequence,previous_checkpoint_fingerprint,
                last_completed_stage_ordinal,next_stage_ordinal,
                restart_generation,state,reason_code,recorded_at_us,
                checkpoint_fingerprint
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                receipt.checkpoint_id,
                receipt.execution_id,
                authorization_id,
                receipt.metric_key,
                receipt.sequence,
                receipt.previous_checkpoint_fingerprint,
                receipt.last_completed_stage_ordinal,
                receipt.next_stage_ordinal,
                receipt.restart_generation,
                receipt.state.value,
                receipt.reason_code,
                _to_us(receipt.recorded_at),
                receipt.canonical_fingerprint,
            ),
        )

    def _root_for_authorization(
        self, connection: sqlite3.Connection, authorization_id: str
    ) -> tuple[str, str, str]:
        row = connection.execute(
            "SELECT authorization_id,execution_id,job_id FROM estimator_runtime_authorizations WHERE authorization_id=?",
            (authorization_id,),
        ).fetchone()
        if row is None:
            raise DatabaseInvariantError("runtime authorization does not exist")
        return row["authorization_id"], row["execution_id"], row["job_id"]

    def revoke_authorization(
        self, authorization_id: str, *, revoked_at: datetime
    ) -> None:
        self._ensure_initialized()
        require_safe_id(authorization_id)
        revoked_at_us = _to_us(revoked_at)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                auth_id, execution_id, job_id = self._root_for_authorization(
                    connection, authorization_id
                )
                with self._authorized(connection, auth_id, execution_id, job_id):
                    existing = connection.execute(
                        "SELECT revoked_at_us FROM estimator_runtime_authorization_revocations WHERE authorization_id=?",
                        (auth_id,),
                    ).fetchone()
                    if existing is None:
                        connection.execute(
                            "INSERT INTO estimator_runtime_authorization_revocations VALUES (?,?,?)",
                            (auth_id, execution_id, revoked_at_us),
                        )
                    elif existing["revoked_at_us"] != revoked_at_us:
                        raise DatabaseInvariantError(
                            "runtime authorization revocation is immutable"
                        )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def cancel(
        self, job_id: str, *, cancelled_at: datetime
    ) -> EstimatorRuntimeSnapshot:
        """Atomically cancel a queued runtime and mirror its terminal receipt."""

        self._ensure_initialized()
        require_safe_id(job_id)
        cancelled_at = require_utc(cancelled_at)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                snapshot = self._snapshot_locked(
                    connection, where="job_id", value=job_id
                )
                if snapshot is None:
                    raise DatabaseInvariantError("runtime execution does not exist")
                if snapshot.job.state in {
                    AnalysisJobState.COMPLETED,
                    AnalysisJobState.PARTIAL,
                    AnalysisJobState.FAILED,
                    AnalysisJobState.CANCELLED,
                    AnalysisJobState.SUPERSEDED,
                }:
                    connection.commit()
                    return snapshot
                if snapshot.job.state in {
                    AnalysisJobState.QUEUED,
                    AnalysisJobState.AWAITING_APPROVAL,
                }:
                    previous = snapshot.states[-1]
                    receipt = EstimatorRuntimeStateReceipt(
                        state_receipt_id=_domain_digest(
                            "estimator-runtime-state-v1",
                            f"{snapshot.binding.execution_id}:{previous.sequence + 1}",
                        ),
                        execution_id=snapshot.binding.execution_id,
                        sequence=previous.sequence + 1,
                        previous_state_receipt_fingerprint=(
                            previous.canonical_fingerprint
                        ),
                        state=EstimatorRuntimeState.CANCELLED,
                        reason_code="cancellation_requested",
                        recorded_at=cancelled_at,
                    )
                    with self._authorized(
                        connection,
                        snapshot.binding.authorization_id,
                        snapshot.binding.execution_id,
                        snapshot.binding.job_id,
                    ):
                        self._insert_state(
                            connection,
                            snapshot.binding.authorization_id,
                            receipt,
                        )
                    timestamp = to_iso(cancelled_at)
                    connection.execute(
                        """
                        UPDATE analysis_jobs SET state='cancelled',stage_number=NULL,
                            cancel_requested=1,
                            terminal_reason_code='cancellation_requested',
                            terminal_at=?,updated_at=? WHERE job_id=?
                        """,
                        (timestamp, timestamp, job_id),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE analysis_jobs SET cancel_requested=1,
                            last_error_code='cancellation_requested',updated_at=?
                        WHERE job_id=?
                        """,
                        (to_iso(cancelled_at), job_id),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        result = self.get_by_job(job_id)
        if result is None:
            raise DatabaseInvariantError("runtime cancellation was not persisted")
        return result

    def _execution_root(
        self, connection: sqlite3.Connection, execution_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM estimator_runtime_executions WHERE execution_id=?",
            (execution_id,),
        ).fetchone()
        if row is None:
            raise DatabaseInvariantError("runtime execution does not exist")
        return row

    @staticmethod
    def _packet_binding(
        connection: sqlite3.Connection,
        execution_id: str,
        metric_key: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM estimator_runtime_packet_receipts WHERE execution_id=? AND metric_key=?",
            (execution_id, metric_key),
        ).fetchone()
        if row is None:
            raise DatabaseInvariantError("runtime metric packet is not bound")
        return row

    def _require_active_execution(
        self,
        connection: sqlite3.Connection,
        execution_id: str,
        *,
        at: datetime,
        require_authorization: bool = True,
    ) -> tuple[sqlite3.Row, sqlite3.Row, EstimatorRuntimeStateReceipt]:
        root = self._execution_root(connection, execution_id)
        job = connection.execute(
            """
            SELECT * FROM analysis_jobs
            WHERE job_id=? AND kind='estimator_execution'
              AND state IN ('preprocessing','stage_n')
              AND lease_owner IS NOT NULL AND lease_token IS NOT NULL
              AND lease_expires_at>?
            """,
            (root["job_id"], to_iso(at)),
        ).fetchone()
        if job is None:
            raise DatabaseInvariantError(
                "runtime append requires the exact active queue lease"
            )
        states = self._states(connection, execution_id)
        if not states or states[-1].state not in {
            EstimatorRuntimeState.CREATED,
            EstimatorRuntimeState.RUNNING,
        }:
            raise DatabaseInvariantError("runtime execution is not appendable")
        if require_authorization:
            authorization_row = connection.execute(
                """
                SELECT a.* FROM estimator_runtime_authorizations a
                LEFT JOIN estimator_runtime_authorization_revocations r
                  ON r.authorization_id=a.authorization_id
                WHERE a.authorization_id=? AND r.authorization_id IS NULL
                  AND a.issued_at_us<=? AND a.expires_at_us>?
                """,
                (root["authorization_id"], _to_us(at), _to_us(at)),
            ).fetchone()
            if authorization_row is None:
                raise DatabaseInvariantError("runtime authorization is not active")
            authorization = self._authorization(connection, authorization_row)
            if not self._automation_grant_is_valid_locked(
                connection, authorization, now=at
            ):
                raise DatabaseInvariantError("runtime automation grant is not active")
        return root, job, states[-1]

    @staticmethod
    def _latest_checkpoint_locked(
        connection: sqlite3.Connection, execution_id: str, metric_key: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT * FROM estimator_runtime_checkpoints
            WHERE execution_id=? AND metric_key=?
            ORDER BY sequence DESC LIMIT 1
            """,
            (execution_id, metric_key),
        ).fetchone()

    def append_state(self, receipt: EstimatorRuntimeStateReceipt) -> None:
        self._ensure_initialized()
        receipt = EstimatorRuntimeStateReceipt.model_validate(
            receipt.model_dump(mode="python")
        )
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                root, _job, active_state = self._require_active_execution(
                    connection,
                    receipt.execution_id,
                    at=receipt.recorded_at,
                    require_authorization=(
                        receipt.state is EstimatorRuntimeState.RUNNING
                    ),
                )
                latest_row = connection.execute(
                    "SELECT * FROM estimator_runtime_state_receipts WHERE execution_id=? ORDER BY sequence DESC LIMIT 1",
                    (receipt.execution_id,),
                ).fetchone()
                if latest_row is None:
                    raise DatabaseInvariantError("runtime initial state is missing")
                latest = self._states(connection, receipt.execution_id)[-1]
                if latest != active_state:
                    raise DatabaseInvariantError("runtime state changed concurrently")
                if receipt.sequence != latest.sequence + 1:
                    raise DatabaseInvariantError("runtime state sequence is not contiguous")
                if receipt.previous_state_receipt_fingerprint != latest.canonical_fingerprint:
                    raise DatabaseInvariantError("runtime state chain disagrees")
                if receipt.state not in _STATE_TRANSITIONS.get(latest.state, set()):
                    raise DatabaseInvariantError("runtime state transition is invalid")
                with self._authorized(
                    connection,
                    root["authorization_id"],
                    receipt.execution_id,
                    root["job_id"],
                ):
                    self._insert_state(connection, root["authorization_id"], receipt)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def append_stage_attempt(
        self, receipt: EstimatorRuntimeStageAttemptReceipt
    ) -> None:
        self._ensure_initialized()
        receipt = EstimatorRuntimeStageAttemptReceipt.model_validate(
            receipt.model_dump(mode="python")
        )
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                root, _job, latest_state = self._require_active_execution(
                    connection, receipt.execution_id, at=receipt.started_at
                )
                if latest_state.state is not EstimatorRuntimeState.RUNNING:
                    raise DatabaseInvariantError(
                        "runtime stage attempt requires running state"
                    )
                packet = self._packet_binding(
                    connection, receipt.execution_id, receipt.metric_key
                )
                if (
                    packet["metric_question_fingerprint"]
                    != receipt.metric_question_fingerprint
                    or packet["packet_fingerprint"]
                    != receipt.evidence_packet_fingerprint
                ):
                    raise DatabaseInvariantError("runtime stage packet lineage disagrees")
                plan = SqliteEstimatorRepository(
                    self._connection_scope, self._ensure_initialized
                )._hydrate_plan(connection, root["plan_fingerprint"])
                stage = plan.stages[receipt.stage_ordinal - 1]
                if (
                    stage.kind is not receipt.stage_kind
                    or estimator_stage_fingerprint(stage) != receipt.stage_fingerprint
                ):
                    raise DatabaseInvariantError("runtime plan stage lineage disagrees")
                prior_attempts = connection.execute(
                    """
                    SELECT a.attempt_ordinal,o.state AS outcome_state
                    FROM estimator_runtime_stage_attempts a
                    LEFT JOIN estimator_runtime_stage_outcomes o
                      ON o.attempt_id=a.attempt_id
                    WHERE a.execution_id=? AND a.metric_key=? AND a.stage_ordinal=?
                    ORDER BY a.attempt_ordinal
                    """,
                    (
                        receipt.execution_id,
                        receipt.metric_key,
                        receipt.stage_ordinal,
                    ),
                ).fetchall()
                if receipt.attempt_ordinal != len(prior_attempts) + 1 or any(
                    row["outcome_state"] is None for row in prior_attempts
                ):
                    raise DatabaseInvariantError(
                        "runtime stage attempt order is not contiguous"
                    )
                if any(row["outcome_state"] == "completed" for row in prior_attempts):
                    raise DatabaseInvariantError(
                        "runtime completed stage cannot be attempted again"
                    )
                checkpoint = self._latest_checkpoint_locked(
                    connection, receipt.execution_id, receipt.metric_key
                )
                expected_stage = 1 if checkpoint is None else checkpoint["next_stage_ordinal"]
                if expected_stage != receipt.stage_ordinal:
                    raise DatabaseInvariantError(
                        "runtime stage attempt is out of checkpoint order"
                    )
                with self._authorized(
                    connection,
                    root["authorization_id"],
                    receipt.execution_id,
                    root["job_id"],
                ):
                    connection.execute(
                        """
                        INSERT INTO estimator_runtime_stage_attempts(
                            attempt_id,execution_id,authorization_id,metric_key,
                            metric_question_fingerprint,evidence_packet_fingerprint,
                            stage_ordinal,stage_kind,stage_fingerprint,
                            attempt_ordinal,started_at_us
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            receipt.attempt_id,
                            receipt.execution_id,
                            root["authorization_id"],
                            receipt.metric_key,
                            receipt.metric_question_fingerprint,
                            receipt.evidence_packet_fingerprint,
                            receipt.stage_ordinal,
                            receipt.stage_kind.value,
                            receipt.stage_fingerprint,
                            receipt.attempt_ordinal,
                            _to_us(receipt.started_at),
                        ),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def append_metric_observation(
        self, receipt: EstimatorRuntimeMetricObservation
    ) -> None:
        self._ensure_initialized()
        receipt = EstimatorRuntimeMetricObservation.model_validate(
            receipt.model_dump(mode="python")
        )
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                root, _job, latest_state = self._require_active_execution(
                    connection, receipt.execution_id, at=receipt.observed_at
                )
                if latest_state.state is not EstimatorRuntimeState.RUNNING:
                    raise DatabaseInvariantError(
                        "runtime observation requires running state"
                    )
                attempt = connection.execute(
                    "SELECT * FROM estimator_runtime_stage_attempts WHERE attempt_id=?",
                    (receipt.attempt_id,),
                ).fetchone()
                if attempt is None or any(
                    (
                        attempt[key] != expected
                        for key, expected in (
                            ("execution_id", receipt.execution_id),
                            ("metric_key", receipt.metric_key),
                            (
                                "metric_question_fingerprint",
                                receipt.metric_question_fingerprint,
                            ),
                            (
                                "evidence_packet_fingerprint",
                                receipt.evidence_packet_fingerprint,
                            ),
                            ("stage_ordinal", 1),
                        )
                    )
                ):
                    raise DatabaseInvariantError("runtime observation attempt disagrees")
                if connection.execute(
                    "SELECT 1 FROM estimator_runtime_stage_outcomes WHERE attempt_id=?",
                    (receipt.attempt_id,),
                ).fetchone() is not None:
                    raise DatabaseInvariantError(
                        "runtime observation attempt is already closed"
                    )
                allowed = {
                    item["evidence_reference_id"]
                    for item in connection.execute(
                        "SELECT evidence_reference_id FROM estimator_runtime_packet_refs WHERE execution_id=? AND packet_fingerprint=?",
                        (receipt.execution_id, receipt.evidence_packet_fingerprint),
                    )
                }
                if not set(receipt.opaque_evidence_refs).issubset(allowed):
                    raise DatabaseInvariantError(
                        "runtime observation references are outside its packet"
                    )
                with self._authorized(
                    connection,
                    root["authorization_id"],
                    receipt.execution_id,
                    root["job_id"],
                ):
                    connection.execute(
                        """
                        INSERT INTO estimator_runtime_metric_observations(
                            observation_id,execution_id,authorization_id,attempt_id,
                            metric_key,metric_question_fingerprint,
                            evidence_packet_fingerprint,stage_ordinal,state,value_kind,
                            numeric_value,label_code,numerator,denominator,reason_code,
                            ref_count,observed_at_us,observation_fingerprint,
                            calibration_state,execution_only,activation_allowed,
                            product_metric_write_allowed
                        ) VALUES (?,?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?,?,'not_assessed',1,0,0)
                        """,
                        (
                            receipt.observation_id,
                            receipt.execution_id,
                            root["authorization_id"],
                            receipt.attempt_id,
                            receipt.metric_key,
                            receipt.metric_question_fingerprint,
                            receipt.evidence_packet_fingerprint,
                            receipt.state.value,
                            receipt.value_kind.value,
                            receipt.numeric_value,
                            receipt.label_code,
                            receipt.numerator,
                            receipt.denominator,
                            receipt.reason_code,
                            len(receipt.opaque_evidence_refs),
                            _to_us(receipt.observed_at),
                            receipt.canonical_fingerprint,
                        ),
                    )
                    connection.executemany(
                        "INSERT INTO estimator_runtime_observation_refs VALUES (?,?,?,?,?)",
                        (
                            (
                                receipt.observation_id,
                                receipt.execution_id,
                                root["authorization_id"],
                                ordinal,
                                reference,
                            )
                            for ordinal, reference in enumerate(
                                receipt.opaque_evidence_refs
                            )
                        ),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def append_retrieval(self, receipt: EstimatorRuntimeRetrievalReceipt) -> None:
        self._ensure_initialized()
        receipt = EstimatorRuntimeRetrievalReceipt.model_validate(
            receipt.model_dump(mode="python")
        )
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                root, _job, latest_state = self._require_active_execution(
                    connection, receipt.execution_id, at=receipt.created_at
                )
                if latest_state.state is not EstimatorRuntimeState.RUNNING:
                    raise DatabaseInvariantError(
                        "runtime retrieval requires running state"
                    )
                attempt = connection.execute(
                    "SELECT * FROM estimator_runtime_stage_attempts WHERE attempt_id=?",
                    (receipt.attempt_id,),
                ).fetchone()
                packet = self._packet_binding(
                    connection, receipt.execution_id, receipt.metric_key
                )
                if (
                    attempt is None
                    or attempt["stage_ordinal"] != 2
                    or attempt["execution_id"] != receipt.execution_id
                    or attempt["metric_key"] != receipt.metric_key
                    or attempt["metric_question_fingerprint"]
                    != receipt.metric_question_fingerprint
                    or attempt["evidence_packet_fingerprint"]
                    != receipt.evidence_packet_fingerprint
                    or packet["retrieval_query_fingerprint"]
                    != receipt.query_fingerprint
                    or packet["retrieval_index_sha256"]
                    != receipt.candidate_index_fingerprint
                ):
                    raise DatabaseInvariantError("runtime retrieval lineage disagrees")
                if connection.execute(
                    "SELECT 1 FROM estimator_runtime_stage_outcomes WHERE attempt_id=?",
                    (receipt.attempt_id,),
                ).fetchone() is not None:
                    raise DatabaseInvariantError(
                        "runtime retrieval attempt is already closed"
                    )
                allowed = {
                    item["evidence_reference_id"]
                    for item in connection.execute(
                        "SELECT evidence_reference_id FROM estimator_runtime_packet_refs WHERE execution_id=? AND packet_fingerprint=?",
                        (receipt.execution_id, receipt.evidence_packet_fingerprint),
                    )
                }
                if not set(receipt.candidate_reference_ids).issubset(allowed):
                    raise DatabaseInvariantError(
                        "runtime retrieval candidates are outside the packet"
                    )
                with self._authorized(
                    connection,
                    root["authorization_id"],
                    receipt.execution_id,
                    root["job_id"],
                ):
                    connection.execute(
                        """
                        INSERT INTO estimator_runtime_retrievals(
                            retrieval_id,execution_id,authorization_id,attempt_id,
                            metric_key,metric_question_fingerprint,
                            evidence_packet_fingerprint,stage_ordinal,stage_kind,
                            score_kind,query_fingerprint,candidate_index_fingerprint,
                            candidate_count,hit_count,created_at_us,
                            retrieval_fingerprint,calibration_state,execution_only,
                            activation_allowed
                        ) VALUES (?,?,?,?,?,?,?,2,'bm25_retrieval','bm25_raw',?,?,?,?,?,?,'not_assessed',1,0)
                        """,
                        (
                            receipt.retrieval_id,
                            receipt.execution_id,
                            root["authorization_id"],
                            receipt.attempt_id,
                            receipt.metric_key,
                            receipt.metric_question_fingerprint,
                            receipt.evidence_packet_fingerprint,
                            receipt.query_fingerprint,
                            receipt.candidate_index_fingerprint,
                            len(receipt.candidate_reference_ids),
                            len(receipt.hits),
                            _to_us(receipt.created_at),
                            receipt.canonical_fingerprint,
                        ),
                    )
                    connection.executemany(
                        "INSERT INTO estimator_runtime_retrieval_candidates VALUES (?,?,?,?,?)",
                        (
                            (
                                receipt.retrieval_id,
                                receipt.execution_id,
                                root["authorization_id"],
                                ordinal,
                                reference,
                            )
                            for ordinal, reference in enumerate(
                                receipt.candidate_reference_ids
                            )
                        ),
                    )
                    connection.executemany(
                        "INSERT INTO estimator_runtime_retrieval_hits VALUES (?,?,?,?,?,?)",
                        (
                            (
                                receipt.retrieval_id,
                                receipt.execution_id,
                                root["authorization_id"],
                                hit.rank,
                                hit.evidence_reference_id,
                                hit.raw_score,
                            )
                            for hit in receipt.hits
                        ),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def append_stage_outcome(
        self, receipt: EstimatorRuntimeStageOutcomeReceipt
    ) -> None:
        self._ensure_initialized()
        receipt = EstimatorRuntimeStageOutcomeReceipt.model_validate(
            receipt.model_dump(mode="python")
        )
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                root, _job, latest_state = self._require_active_execution(
                    connection,
                    receipt.execution_id,
                    at=receipt.finished_at,
                    require_authorization=(
                        receipt.state
                        is EstimatorRuntimeStageOutcomeState.COMPLETED
                    ),
                )
                if latest_state.state is not EstimatorRuntimeState.RUNNING:
                    raise DatabaseInvariantError("runtime outcome requires running state")
                attempt = connection.execute(
                    "SELECT started_at_us FROM estimator_runtime_stage_attempts WHERE attempt_id=? AND execution_id=?",
                    (receipt.attempt_id, receipt.execution_id),
                ).fetchone()
                if attempt is None or _to_us(receipt.finished_at) < attempt["started_at_us"]:
                    raise DatabaseInvariantError("runtime outcome attempt disagrees")
                if receipt.output_fingerprint is not None:
                    output_exists = connection.execute(
                        """
                        SELECT 1 FROM estimator_runtime_metric_observations
                        WHERE attempt_id=? AND observation_fingerprint=?
                        UNION ALL
                        SELECT 1 FROM estimator_runtime_retrievals
                        WHERE attempt_id=? AND retrieval_fingerprint=?
                        """,
                        (
                            receipt.attempt_id,
                            receipt.output_fingerprint,
                            receipt.attempt_id,
                            receipt.output_fingerprint,
                        ),
                    ).fetchone()
                    if output_exists is None:
                        raise DatabaseInvariantError(
                            "runtime outcome output receipt does not exist"
                        )
                with self._authorized(
                    connection,
                    root["authorization_id"],
                    receipt.execution_id,
                    root["job_id"],
                ):
                    connection.execute(
                        "INSERT INTO estimator_runtime_stage_outcomes VALUES (?,?,?,?,?,?,?,?)",
                        (
                            receipt.outcome_id,
                            receipt.attempt_id,
                            receipt.execution_id,
                            root["authorization_id"],
                            receipt.state.value,
                            receipt.reason_code,
                            receipt.output_fingerprint,
                            _to_us(receipt.finished_at),
                        ),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def append_checkpoint(
        self, receipt: EstimatorRuntimeCheckpointReceipt
    ) -> None:
        self._ensure_initialized()
        receipt = EstimatorRuntimeCheckpointReceipt.model_validate(
            receipt.model_dump(mode="python")
        )
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                root, _job, latest_state = self._require_active_execution(
                    connection,
                    receipt.execution_id,
                    at=receipt.recorded_at,
                    require_authorization=(
                        receipt.state is EstimatorRuntimeState.RUNNING
                    ),
                )
                if latest_state.state is not EstimatorRuntimeState.RUNNING:
                    raise DatabaseInvariantError(
                        "runtime checkpoint requires running execution"
                    )
                self._packet_binding(connection, receipt.execution_id, receipt.metric_key)
                previous = connection.execute(
                    "SELECT checkpoint_fingerprint,sequence FROM estimator_runtime_checkpoints WHERE execution_id=? AND metric_key=? ORDER BY sequence DESC LIMIT 1",
                    (receipt.execution_id, receipt.metric_key),
                ).fetchone()
                if previous is None:
                    if receipt.sequence != 0 or receipt.previous_checkpoint_fingerprint is not None:
                        raise DatabaseInvariantError("runtime checkpoint must start at zero")
                elif (
                    receipt.sequence != previous["sequence"] + 1
                    or receipt.previous_checkpoint_fingerprint
                    != previous["checkpoint_fingerprint"]
                ):
                    raise DatabaseInvariantError("runtime checkpoint chain disagrees")
                if receipt.state is EstimatorRuntimeState.RUNNING:
                    completed = connection.execute(
                        """
                        SELECT o.finished_at_us FROM estimator_runtime_stage_attempts a
                        JOIN estimator_runtime_stage_outcomes o ON o.attempt_id=a.attempt_id
                        WHERE a.execution_id=? AND a.metric_key=?
                          AND a.stage_ordinal=? AND o.state='completed'
                        """,
                        (
                            receipt.execution_id,
                            receipt.metric_key,
                            receipt.last_completed_stage_ordinal,
                        ),
                    ).fetchone()
                    if (
                        completed is None
                        or completed["finished_at_us"] > _to_us(receipt.recorded_at)
                    ):
                        raise DatabaseInvariantError(
                            "runtime checkpoint lacks its completed stage outcome"
                        )
                elif receipt.last_completed_stage_ordinal:
                    completed = connection.execute(
                        """
                        SELECT 1 FROM estimator_runtime_stage_attempts a
                        JOIN estimator_runtime_stage_outcomes o ON o.attempt_id=a.attempt_id
                        WHERE a.execution_id=? AND a.metric_key=?
                          AND a.stage_ordinal=? AND o.state='completed'
                        """,
                        (
                            receipt.execution_id,
                            receipt.metric_key,
                            receipt.last_completed_stage_ordinal,
                        ),
                    ).fetchone()
                    if completed is None:
                        raise DatabaseInvariantError(
                            "runtime terminal checkpoint lacks last completed outcome"
                        )
                with self._authorized(
                    connection,
                    root["authorization_id"],
                    receipt.execution_id,
                    root["job_id"],
                ):
                    self._insert_checkpoint_locked(
                        connection,
                        root["authorization_id"],
                        receipt,
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def delete_execution_for_privacy(
        self, execution_id: str
    ) -> EstimatorRuntimePrivacyDeleteOutcome:
        self._ensure_initialized()
        require_safe_id(execution_id)
        revocation_key = _domain_digest(
            "estimator-runtime-revocation-v1", execution_id
        )
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                root = connection.execute(
                    "SELECT authorization_id,job_id,plan_fingerprint FROM estimator_runtime_executions WHERE execution_id=?",
                    (execution_id,),
                ).fetchone()
                if root is not None:
                    deleted_at_us = _to_us(datetime.now(UTC))
                    with self._authorized(
                        connection,
                        root["authorization_id"],
                        execution_id,
                        root["job_id"],
                    ):
                        connection.execute(
                            """
                            INSERT OR IGNORE INTO estimator_runtime_deletion_tombstones
                            VALUES (?,?,?)
                            """,
                            (revocation_key, root["plan_fingerprint"], deleted_at_us),
                        )
                        connection.execute(
                            "DELETE FROM analysis_jobs WHERE job_id=?",
                            (root["job_id"],),
                        )
                    plan_retained = connection.execute(
                        "SELECT 1 FROM estimator_plans WHERE plan_fingerprint=?",
                        (root["plan_fingerprint"],),
                    ).fetchone() is not None
                else:
                    tombstone = connection.execute(
                        """
                        SELECT retained_plan_fingerprint
                        FROM estimator_runtime_deletion_tombstones
                        WHERE revocation_key=?
                        """,
                        (revocation_key,),
                    ).fetchone()
                    if tombstone is None:
                        return EstimatorRuntimePrivacyDeleteOutcome(
                            execution_deleted=False,
                            plan_retained=False,
                            durable_revocation_retained=False,
                        )
                    plan_retained = connection.execute(
                        "SELECT 1 FROM estimator_plans WHERE plan_fingerprint=?",
                        (tombstone["retained_plan_fingerprint"],),
                    ).fetchone() is not None
                    if not plan_retained:
                        raise DatabaseInvariantError(
                            "runtime privacy tombstone retained plan is absent"
                        )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint is None or checkpoint[0] != 0:
                raise DatabaseInvariantError("runtime WAL privacy purge is pending")
        return EstimatorRuntimePrivacyDeleteOutcome(
            execution_deleted=True,
            plan_retained=plan_retained,
            durable_revocation_retained=True,
        )


__all__ = ["SqliteEstimatorRuntimeRepository"]
