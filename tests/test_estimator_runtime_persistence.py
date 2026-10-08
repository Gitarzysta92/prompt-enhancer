from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.automation import (
    AUTOMATION_GRANT_LIFETIME,
    AutomationGrantDraft,
    AutomationGrantScope,
    AutomationResourcePolicy,
    AutomationRoute,
)
from prompt_enhancer.application.estimators.contracts import (
    EstimatorPlan,
    EstimatorRoute,
    ExecutionDestination,
    MetricEstimateState,
    MetricValueKind,
    ProviderSchemaIdentity,
    RetentionClass,
)
from prompt_enhancer.application.estimators.evidence_packets import (
    build_runtime_evidence_packet_receipt,
)
from prompt_enhancer.application.estimators.runtime_persistence import (
    DurableRuntimeAuthorizationKind,
    DurableRuntimeAuthorizationReceipt,
    DurableRuntimePacketBinding,
    EstimatorRuntimeCheckpointReceipt,
    EstimatorRuntimeLaunch,
    EstimatorRuntimeMetricObservation,
    EstimatorRuntimeStageAttemptReceipt,
    EstimatorRuntimeStageOutcomeReceipt,
    EstimatorRuntimeStageOutcomeState,
    EstimatorRuntimeState,
    EstimatorRuntimeStateReceipt,
)
from prompt_enhancer.application.estimators.runtime_service import (
    EstimatorRuntimeHandler,
    EstimatorRuntimeService,
    EstimatorRuntimeSourceIdentity,
    ObjectiveRuntimeEvidence,
    ProductionRuntimeBm25,
)
from prompt_enhancer.application.estimators.runtime_catalog import (
    RuntimeEstimatorCatalog,
    RuntimePlanRegistration,
)
from prompt_enhancer.application.jobs import (
    AnalysisJobConflictError,
    AnalysisJobDraft,
    AnalysisJobIdentity,
    AnalysisJobKind,
    AnalysisJobLease,
    AnalysisJobService,
    AnalysisJobState,
    AnalysisJobWorker,
    PowerSourceState,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import DatabaseInvariantError, SCHEMA_VERSION
from prompt_enhancer.database import Database, _MIGRATION_1
from prompt_enhancer.domain import Provider
from prompt_enhancer.infrastructure.sqlite import migrations

from test_analysis_job_queue import MutableClock, TOKEN, _database, _http_payload
from test_estimator_runtime_foundation import (
    PRIVATE_MARKER,
    evidence_packet,
    plan_registration,
    runtime_catalog,
    synthetic_plan,
)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


class SyntheticPacketSource:
    def __init__(self, packet, identity: EstimatorRuntimeSourceIdentity) -> None:  # type: ignore[no-untyped-def]
        self.packet = packet
        self.current_identity = identity
        self.identity_reads = 0
        self.packet_reads = 0
        self.objective_reads = 0

    def identity(
        self, _binding: DurableRuntimePacketBinding
    ) -> EstimatorRuntimeSourceIdentity:
        self.identity_reads += 1
        return self.current_identity

    def load_packet(self, _binding: DurableRuntimePacketBinding):  # type: ignore[no-untyped-def]
        self.packet_reads += 1
        return self.packet

    def objective_evidence(self, packet):  # type: ignore[no-untyped-def]
        self.objective_reads += 1
        receipt = build_runtime_evidence_packet_receipt(packet)
        return ObjectiveRuntimeEvidence(
            state=MetricEstimateState.KNOWN,
            value_kind=MetricValueKind.FRACTION,
            numeric_value=1.0,
            numerator=1,
            denominator=1,
            opaque_evidence_refs=(receipt.opaque_evidence_refs[0],),
        )


class FailOnceBm25:
    def __init__(self) -> None:
        self.failed = False
        self.delegate = ProductionRuntimeBm25()

    def retrieve(self, packet):  # type: ignore[no-untyped-def]
        if not self.failed:
            self.failed = True
            raise RuntimeError("synthetic interruption without packet logging")
        return self.delegate.retrieve(packet)


class FailAlwaysBm25:
    def retrieve(self, _packet):  # type: ignore[no-untyped-def]
        raise RuntimeError("synthetic bounded terminal interruption")


class FailOnceObjectiveSource(SyntheticPacketSource):
    def __init__(self, packet, identity: EstimatorRuntimeSourceIdentity) -> None:  # type: ignore[no-untyped-def]
        super().__init__(packet, identity)
        self.failed = False

    def objective_evidence(self, packet):  # type: ignore[no-untyped-def]
        if not self.failed:
            self.failed = True
            raise RuntimeError("synthetic objective interruption")
        return super().objective_evidence(packet)


def _setup(tmp_path, *, label: str = "default"):  # type: ignore[no-untyped-def]
    database, session = _database(tmp_path)
    clock = MutableClock()
    catalog = runtime_catalog()
    registration = catalog.plan_for_route(EstimatorRoute.BALANCED)
    database.estimator_repository().register_plan(registration.plan)
    packet = evidence_packet()
    packet_receipt = build_runtime_evidence_packet_receipt(packet)
    binding = DurableRuntimePacketBinding(
        metric_key=packet_receipt.metric_key,
        metric_question_fingerprint=packet_receipt.metric_question_fingerprint,
        evidence_packet_fingerprint=packet_receipt.packet_fingerprint,
    )
    identity = EstimatorRuntimeSourceIdentity(
        input_fingerprint=digest(f"{label}-input"),
        provenance_fingerprint=digest(f"{label}-provenance"),
        session_revision_id=digest(f"{label}-revision"),
        window_fingerprint=digest(f"{label}-window"),
    )
    authorization = DurableRuntimeAuthorizationReceipt(
        authorization_id=digest(f"{label}-authorization"),
        job_id=digest(f"{label}-job"),
        execution_id=digest(f"{label}-execution"),
        kind=DurableRuntimeAuthorizationKind.SYNTHETIC_TEST,
        provider=Provider.SYNTHETIC,
        destination=ExecutionDestination.SYNTHETIC_TEST,
        retention_class=RetentionClass.SYNTHETIC,
        project_id=str(session["project_id"]),
        session_id=str(session["session_id"]),
        session_revision_id=identity.session_revision_id,
        window_fingerprint=identity.window_fingerprint,
        input_fingerprint=identity.input_fingerprint,
        provenance_fingerprint=identity.provenance_fingerprint,
        plan_fingerprint=registration.plan_fingerprint,
        route=EstimatorRoute.BALANCED,
        provider_schema_version="synthetic-schema-1",
        redactor_version=registration.plan.redactor_version,
        redactor_sha256=registration.plan.redactor_sha256,
        packet_bindings=(binding,),
        issued_at=clock(),
        expires_at=clock() + timedelta(minutes=10),
    )
    launch = EstimatorRuntimeLaunch(
        authorization=authorization,
        packet_receipts=(packet_receipt,),
        consumed_at=clock(),
    )
    repository = database.estimator_runtime_repository()
    source = SyntheticPacketSource(packet, identity)
    return (
        database,
        clock,
        catalog,
        repository,
        source,
        launch,
        registration,
    )


def _worker(database, clock, handler):  # type: ignore[no-untyped-def]
    return AnalysisJobWorker(
        database.analysis_job_repository(),
        {
            (AnalysisJobKind.ESTIMATOR_EXECUTION, Provider.SYNTHETIC): handler,
        },
        authorization_check=handler.authorization_check,
        fingerprint_resolver=handler.fingerprint_resolver,
        execution_stop_callback=handler.execution_stop_callback,
        execution_recovery_callback=handler.execution_recovery_callback,
        clock=clock,
        worker_id=digest("synthetic-runtime-worker"),
    )


def _generic_identity(launch: EstimatorRuntimeLaunch) -> AnalysisJobIdentity:
    authorization = launch.authorization
    return AnalysisJobIdentity(
        kind=AnalysisJobKind.ESTIMATOR_EXECUTION,
        provider=authorization.provider,
        project_id=authorization.project_id,
        session_id=authorization.session_id,
        input_fingerprint=authorization.input_fingerprint,
        provenance_fingerprint=authorization.provenance_fingerprint,
        metric_keys=tuple(
            item.metric_key for item in authorization.packet_bindings
        ),
        estimator_plan_version=authorization.plan_fingerprint,
        redactor_version=authorization.redactor_version,
        provider_schema_version=authorization.provider_schema_version,
    )


def test_generic_service_repository_and_http_cannot_create_or_cancel_runtime_jobs(
    tmp_path,
) -> None:
    database, clock, catalog, repository, _source, launch, _ = _setup(
        tmp_path, label="generic-boundary"
    )
    generic_repository = database.analysis_job_repository()
    service = AnalysisJobService(generic_repository, clock=clock)
    identity = _generic_identity(launch)
    with pytest.raises(AnalysisJobConflictError):
        service.enqueue(identity)
    with pytest.raises(DatabaseInvariantError, match="atomic runtime launch"):
        generic_repository.enqueue(
            AnalysisJobDraft(
                job_id=digest("generic-job"),
                dedupe_key=digest("generic-dedupe"),
                identity=identity,
                max_attempts=3,
                created_at=clock(),
            )
        )

    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        analysis_job_service=service,
    )
    payload = _http_payload(
        {
            "project_id": launch.authorization.project_id,
            "session_id": launch.authorization.session_id,
        }
    )
    payload["kind"] = AnalysisJobKind.ESTIMATOR_EXECUTION.value
    with TestClient(app, base_url="http://127.0.0.1") as client:
        rejected = client.post(
            "/v1/analysis-jobs",
            json=payload,
            headers={API_TOKEN_HEADER: TOKEN},
        )
    assert rejected.status_code == 422
    assert rejected.json() == {"detail": "request validation failed"}

    launched = EstimatorRuntimeService(repository, catalog, clock=clock).launch(
        launch
    )
    with pytest.raises(AnalysisJobConflictError):
        service.cancel(launched.job.job_id)
    with pytest.raises(DatabaseInvariantError, match="runtime boundary"):
        generic_repository.request_cancel(launched.job.job_id, now=clock())
    with TestClient(app, base_url="http://127.0.0.1") as client:
        cancelled = client.post(
            f"/v1/analysis-jobs/{launched.job.job_id}/cancellation",
            headers={API_TOKEN_HEADER: TOKEN},
        )
    assert cancelled.status_code == 409
    untouched = repository.get_by_job(launched.job.job_id)
    assert untouched is not None
    assert untouched.job.state is AnalysisJobState.QUEUED
    assert untouched.states[-1].state is EstimatorRuntimeState.CREATED


def test_runtime_scope_seal_blocks_raw_metric_insert_delete(tmp_path) -> None:
    database, _clock, _catalog, repository, _source, launch, _ = _setup(
        tmp_path, label="metric-seal"
    )
    repository.launch(launch)
    with database._connection() as connection:
        columns = tuple(
            row[1] for row in connection.execute("PRAGMA table_info(analysis_jobs)")
        )
        projection = ",".join(
            "?" if column in {"job_id", "dedupe_key"} else column
            for column in columns
        )
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(
                f"""
                INSERT INTO analysis_jobs({','.join(columns)})
                SELECT {projection} FROM analysis_jobs WHERE job_id=?
                """,
                (
                    digest("raw-orphan-runtime-job"),
                    digest("raw-orphan-runtime-dedupe"),
                    launch.authorization.job_id,
                ),
            )
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(
                "DELETE FROM analysis_job_metrics WHERE job_id=?",
                (launch.authorization.job_id,),
            )
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(
                "INSERT INTO analysis_job_metrics VALUES (?,?,1)",
                (launch.authorization.job_id, "forged.metric"),
            )
    snapshot = repository.get_by_job(launch.authorization.job_id)
    assert snapshot is not None
    assert snapshot.job.identity.metric_keys == tuple(
        item.metric_key for item in launch.authorization.packet_bindings
    )


def test_runtime_capability_is_exact_job_scoped_and_always_cleaned_up(
    tmp_path,
) -> None:
    database, _clock, _catalog, repository, _source, launch, _ = _setup(
        tmp_path, label="job-scoped-capability"
    )
    repository.launch(launch)
    authorization = launch.authorization
    cloned_job_id = digest("job-scoped-capability-clone")
    with database._connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        columns = tuple(
            row[1] for row in connection.execute("PRAGMA table_info(analysis_jobs)")
        )
        projection = ",".join(
            "?" if column in {"job_id", "dedupe_key"} else column
            for column in columns
        )
        with repository._authorized(
            connection,
            authorization.authorization_id,
            authorization.execution_id,
            authorization.job_id,
        ):
            with pytest.raises(sqlite3.DatabaseError, match="atomic runtime launch"):
                connection.execute(
                    f"""
                    INSERT INTO analysis_jobs({','.join(columns)})
                    SELECT {projection} FROM analysis_jobs WHERE job_id=?
                    """,
                    (
                        cloned_job_id,
                        digest("job-scoped-capability-clone-dedupe"),
                        authorization.job_id,
                    ),
                )
        connection.commit()
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_runtime_write_authorizations"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT 1 FROM analysis_jobs WHERE job_id=?", (cloned_job_id,)
        ).fetchone() is None

        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(RuntimeError, match="synthetic capability interruption"):
            with repository._authorized(
                connection,
                authorization.authorization_id,
                authorization.execution_id,
                authorization.job_id,
            ):
                raise RuntimeError("synthetic capability interruption")
        connection.commit()
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_runtime_write_authorizations"
        ).fetchone()[0] == 0

        connection.execute("BEGIN IMMEDIATE")
        with repository._authorized(
            connection,
            authorization.authorization_id,
            authorization.execution_id,
            authorization.job_id,
        ):
            assert connection.execute(
                "SELECT job_id FROM estimator_runtime_write_authorizations"
            ).fetchone()[0] == authorization.job_id
        connection.commit()
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_runtime_write_authorizations"
        ).fetchone()[0] == 0


def test_runtime_terminal_reconciliation_covers_both_failure_interleavings(
    tmp_path,
    monkeypatch,
) -> None:
    # Ledger callback failure happens before queue finish, so the queue requeues
    # and a later exact callback converges without a false terminal row.
    database, clock, catalog, repository, source, launch, _ = _setup(
        tmp_path / "callback-first", label="callback-first"
    )
    repository.launch(launch)
    source.current_identity = EstimatorRuntimeSourceIdentity(
        **{
            **source.current_identity.model_dump(mode="python"),
            "input_fingerprint": digest("callback-first-changed"),
        }
    )
    handler = EstimatorRuntimeHandler(repository, catalog, source, clock=clock)
    callback_calls = 0

    def fail_callback_once(job, state, reason):  # type: ignore[no-untyped-def]
        nonlocal callback_calls
        callback_calls += 1
        if callback_calls == 1:
            raise DatabaseInvariantError("synthetic ledger interruption")
        handler.execution_stop_callback(job, state, reason)

    worker = AnalysisJobWorker(
        database.analysis_job_repository(),
        {(AnalysisJobKind.ESTIMATOR_EXECUTION, Provider.SYNTHETIC): handler},
        authorization_check=handler.authorization_check,
        fingerprint_resolver=handler.fingerprint_resolver,
        execution_stop_callback=fail_callback_once,
        execution_recovery_callback=handler.execution_recovery_callback,
        clock=clock,
        worker_id=digest("callback-first-worker"),
    )
    assert worker.run_once()
    pending = repository.get_by_job(launch.authorization.job_id)
    assert pending is not None
    assert pending.job.state is AnalysisJobState.QUEUED
    assert [item.state for item in pending.states] == [EstimatorRuntimeState.CREATED]
    clock.advance(seconds=5)
    assert worker.run_once()
    converged = repository.get_by_job(launch.authorization.job_id)
    assert converged is not None
    assert converged.job.state is AnalysisJobState.SUPERSEDED
    assert [item.state for item in converged.states] == [
        EstimatorRuntimeState.CREATED,
        EstimatorRuntimeState.SUPERSEDED,
    ]

    # Runtime terminal append succeeds, queue finish fails, and the retry sees
    # the existing terminal receipt rather than appending a conflicting state.
    database, clock, catalog, repository, source, launch, _ = _setup(
        tmp_path / "queue-second", label="queue-second"
    )
    repository.launch(launch)
    handler = EstimatorRuntimeHandler(repository, catalog, source, clock=clock)
    queue_repository = database.analysis_job_repository()
    original_finish = queue_repository.finish
    finish_calls = 0

    def fail_finish_once(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal finish_calls
        finish_calls += 1
        if finish_calls == 1:
            raise DatabaseInvariantError("synthetic queue interruption")
        return original_finish(*args, **kwargs)

    monkeypatch.setattr(queue_repository, "finish", fail_finish_once)
    worker = AnalysisJobWorker(
        queue_repository,
        {(AnalysisJobKind.ESTIMATOR_EXECUTION, Provider.SYNTHETIC): handler},
        authorization_check=handler.authorization_check,
        fingerprint_resolver=handler.fingerprint_resolver,
        execution_stop_callback=handler.execution_stop_callback,
        execution_recovery_callback=handler.execution_recovery_callback,
        clock=clock,
        worker_id=digest("queue-second-worker"),
    )
    assert worker.run_once()
    pending = repository.get_by_job(launch.authorization.job_id)
    assert pending is not None
    assert pending.job.state is AnalysisJobState.QUEUED
    assert pending.states[-1].state is EstimatorRuntimeState.PARTIAL
    clock.advance(seconds=5)
    assert worker.run_once()
    converged = repository.get_by_job(launch.authorization.job_id)
    assert converged is not None
    assert converged.job.state is AnalysisJobState.PARTIAL
    assert [item.state for item in converged.states] == [
        EstimatorRuntimeState.CREATED,
        EstimatorRuntimeState.RUNNING,
        EstimatorRuntimeState.PARTIAL,
    ]


def _start_runtime(database, clock, repository, launch):  # type: ignore[no-untyped-def]
    snapshot = repository.launch(launch)
    claimed = database.analysis_job_repository().claim_next(
        owner=digest("manual-runtime-owner"),
        token=digest("manual-runtime-token"),
        now=clock(),
        lease_duration=timedelta(minutes=1),
    )
    assert claimed is not None and claimed.job_id == launch.authorization.job_id
    previous = snapshot.states[-1]
    repository.append_state(
        EstimatorRuntimeStateReceipt(
            state_receipt_id=digest(f"manual-running-{launch.authorization.job_id}"),
            execution_id=launch.authorization.execution_id,
            sequence=1,
            previous_state_receipt_fingerprint=previous.canonical_fingerprint,
            state=EstimatorRuntimeState.RUNNING,
            reason_code="runtime_worker_started",
            recorded_at=clock(),
        )
    )
    return claimed


def test_stage_fingerprint_order_and_terminal_append_guards(tmp_path) -> None:
    database, clock, catalog, repository, source, launch, registration = _setup(
        tmp_path / "order", label="order"
    )
    _start_runtime(database, clock, repository, launch)
    binding = launch.authorization.packet_bindings[0]

    def attempt(stage_ordinal: int, fingerprint: str, attempt_ordinal: int = 1):
        return EstimatorRuntimeStageAttemptReceipt(
            attempt_id=digest(
                f"order-attempt-{stage_ordinal}-{attempt_ordinal}-{fingerprint}"
            ),
            execution_id=launch.authorization.execution_id,
            metric_key=binding.metric_key,
            metric_question_fingerprint=binding.metric_question_fingerprint,
            evidence_packet_fingerprint=binding.evidence_packet_fingerprint,
            stage_ordinal=stage_ordinal,
            stage_kind=registration.stage_registration(stage_ordinal).stage_kind,
            stage_fingerprint=fingerprint,
            attempt_ordinal=attempt_ordinal,
            started_at=clock(),
        )

    with pytest.raises(DatabaseInvariantError, match="stage lineage"):
        repository.append_stage_attempt(attempt(1, digest("wrong-stage")))
    with pytest.raises(DatabaseInvariantError, match="checkpoint order"):
        repository.append_stage_attempt(
            attempt(2, registration.stage_registration(2).stage_fingerprint)
        )

    objective_attempt = attempt(
        1, registration.stage_registration(1).stage_fingerprint
    )
    repository.append_stage_attempt(objective_attempt)
    with pytest.raises(DatabaseInvariantError, match="completed stage outcome"):
        repository.append_checkpoint(
            EstimatorRuntimeCheckpointReceipt(
                checkpoint_id=digest("forged-checkpoint-before-outcome"),
                execution_id=launch.authorization.execution_id,
                metric_key=binding.metric_key,
                sequence=0,
                last_completed_stage_ordinal=1,
                next_stage_ordinal=2,
                restart_generation=0,
                state=EstimatorRuntimeState.RUNNING,
                reason_code="objective_stage_completed",
                recorded_at=clock(),
            )
        )

    # A separate complete run proves every append boundary rejects terminal jobs.
    database, clock, catalog, repository, source, launch, registration = _setup(
        tmp_path / "terminal", label="terminal"
    )
    repository.launch(launch)
    handler = EstimatorRuntimeHandler(repository, catalog, source, clock=clock)
    assert _worker(database, clock, handler).run_once()
    binding = launch.authorization.packet_bindings[0]
    with pytest.raises(DatabaseInvariantError, match="active queue lease"):
        repository.append_stage_attempt(
            EstimatorRuntimeStageAttemptReceipt(
                attempt_id=digest("after-terminal-attempt"),
                execution_id=launch.authorization.execution_id,
                metric_key=binding.metric_key,
                metric_question_fingerprint=binding.metric_question_fingerprint,
                evidence_packet_fingerprint=binding.evidence_packet_fingerprint,
                stage_ordinal=3,
                stage_kind=registration.stage_registration(3).stage_kind,
                stage_fingerprint=registration.stage_registration(3).stage_fingerprint,
                attempt_ordinal=1,
                started_at=clock(),
            )
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("packet_schema_version", "unreviewed-packet-2"),
        ("adapter_version", "unreviewed-adapter-2"),
        ("preprocessing_version", "unreviewed-preprocessor-2"),
        ("preprocessing_sha256", digest("unreviewed-preprocessor")),
        ("router_version", "unreviewed-router-2"),
        ("router_sha256", digest("unreviewed-router")),
    ),
)
def test_packet_provenance_mismatch_fails_at_application_and_sql_boundaries(
    tmp_path,
    field: str,
    replacement: str,
) -> None:
    _database_, clock, catalog, repository, _source, launch, _ = _setup(
        tmp_path, label=f"packet-{field}"
    )
    values = launch.packet_receipts[0].model_dump(mode="python")
    values[field] = replacement
    receipt = type(launch.packet_receipts[0])(**values)
    mismatched = EstimatorRuntimeLaunch(
        authorization=launch.authorization,
        packet_receipts=(receipt,),
        consumed_at=clock(),
    )
    with pytest.raises(ValueError, match="reviewed plan"):
        EstimatorRuntimeService(repository, catalog, clock=clock).launch(mismatched)
    with pytest.raises(DatabaseInvariantError, match="registered plan"):
        repository.launch(mismatched)


def _automation_runtime_setup(
    tmp_path,
    *,
    label: str,
    create_grant: bool = True,
    route: AutomationRoute = AutomationRoute.BALANCED,
    metric_keys: tuple[str, ...] | None = None,
    grant_project_id: str | None = None,
    grant_created_offset_days: int = 0,
    resource_policy: AutomationResourcePolicy | None = None,
):  # type: ignore[no-untyped-def]
    database, seed_session = _database(tmp_path)
    clock = MutableClock()
    project_id = digest(f"{label}-codex-project")
    session_id = digest(f"{label}-codex-session")
    with database._connection() as connection:
        installation_id = connection.execute(
            "SELECT installation_id FROM sessions WHERE session_id=?",
            (seed_session["session_id"],),
        ).fetchone()[0]
        timestamp = clock().isoformat(timespec="microseconds")
        connection.execute(
            "INSERT INTO projects(project_id,installation_id,provider,created_at) VALUES (?,?,?,?)",
            (project_id, installation_id, Provider.CODEX.value, timestamp),
        )
        connection.execute(
            """
            INSERT INTO sessions(
                session_id,installation_id,project_id,provider,provider_version,
                adapter_version,source_schema_version,started_at,ended_at,
                terminal_state,events_complete,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                session_id,
                installation_id,
                project_id,
                Provider.CODEX.value,
                "codex-example-provider-v1",
                "codex-example-adapter-v1",
                "codex-example-schema-v1",
                timestamp,
                timestamp,
                "completed",
                1,
                timestamp,
                timestamp,
            ),
        )
        connection.commit()

    base_plan = synthetic_plan(EstimatorRoute.BALANCED)
    plan_values = base_plan.model_dump(mode="python")
    plan_values.update(
        plan_key=f"{label}.codex.runtime",
        provider_schemas=(
            ProviderSchemaIdentity(
                provider=Provider.CODEX,
                adapter_version="codex-example-adapter-v1",
                provider_schema_version="codex-example-schema-v1",
            ),
        ),
    )
    plan = EstimatorPlan(**plan_values)
    database.estimator_repository().register_plan(plan)
    base_registration = plan_registration(EstimatorRoute.BALANCED)
    registration = RuntimePlanRegistration(
        plan=plan,
        plan_fingerprint=plan.canonical_fingerprint,
        question_bindings=base_registration.question_bindings,
        stage_registrations=base_registration.stage_registrations,
    )
    base_catalog = runtime_catalog()
    catalog = RuntimeEstimatorCatalog(
        registrations=(
            base_catalog.registrations[0],
            registration,
            base_catalog.registrations[2],
        )
    )

    packet = evidence_packet()
    packet_values = build_runtime_evidence_packet_receipt(packet).model_dump(
        mode="python"
    )
    packet_values.update(
        plan_fingerprint=plan.canonical_fingerprint,
        provider=Provider.CODEX,
        adapter_version="codex-example-adapter-v1",
        provider_schema_version="codex-example-schema-v1",
    )
    receipt = type(build_runtime_evidence_packet_receipt(packet))(**packet_values)
    binding = DurableRuntimePacketBinding(
        metric_key=receipt.metric_key,
        metric_question_fingerprint=receipt.metric_question_fingerprint,
        evidence_packet_fingerprint=receipt.packet_fingerprint,
    )
    grant_id = digest(f"{label}-automation-grant")
    if create_grant:
        selected_project = grant_project_id or project_id
        if grant_project_id is not None:
            with database._connection() as connection:
                installation_id = connection.execute(
                    "SELECT installation_id FROM projects WHERE project_id=?",
                    (project_id,),
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO projects(project_id,installation_id,provider,created_at) VALUES (?,?,?,?)",
                    (
                        grant_project_id,
                        installation_id,
                        Provider.CODEX.value,
                        clock().isoformat(timespec="microseconds"),
                    ),
                )
                connection.commit()
        grant_created = clock() + timedelta(days=grant_created_offset_days)
        database.automation_grant_repository().create(
            AutomationGrantDraft(
                grant_id=grant_id,
                scope=AutomationGrantScope(
                    provider=Provider.CODEX,
                    project_id=selected_project,
                    metric_keys=metric_keys or (binding.metric_key,),
                    resource_policy=(
                        resource_policy or AutomationResourcePolicy(route=route)
                    ),
                ),
                created_at=grant_created,
                expires_at=grant_created + AUTOMATION_GRANT_LIFETIME,
            )
        )
    authorization = DurableRuntimeAuthorizationReceipt(
        authorization_id=digest(f"{label}-authorization"),
        job_id=digest(f"{label}-job"),
        execution_id=digest(f"{label}-execution"),
        kind=DurableRuntimeAuthorizationKind.AUTOMATION_ONCE,
        provider=Provider.CODEX,
        destination=ExecutionDestination.LOCAL_DEVICE,
        retention_class=RetentionClass.LOCAL_EPHEMERAL,
        project_id=project_id,
        session_id=session_id,
        session_revision_id=digest(f"{label}-revision"),
        window_fingerprint=digest(f"{label}-window"),
        input_fingerprint=digest(f"{label}-input"),
        provenance_fingerprint=digest(f"{label}-provenance"),
        plan_fingerprint=plan.canonical_fingerprint,
        route=EstimatorRoute.BALANCED,
        provider_schema_version="codex-example-schema-v1",
        redactor_version=plan.redactor_version,
        redactor_sha256=plan.redactor_sha256,
        packet_bindings=(binding,),
        automation_grant_id=grant_id,
        issued_at=clock(),
        expires_at=clock() + timedelta(minutes=10),
    )
    launch = EstimatorRuntimeLaunch(
        authorization=authorization,
        packet_receipts=(receipt,),
        consumed_at=clock(),
    )
    source = SyntheticPacketSource(
        packet,
        EstimatorRuntimeSourceIdentity(
            input_fingerprint=authorization.input_fingerprint,
            provenance_fingerprint=authorization.provenance_fingerprint,
            session_revision_id=authorization.session_revision_id,
            window_fingerprint=authorization.window_fingerprint,
        ),
    )
    return database, clock, catalog, database.estimator_runtime_repository(), source, launch


def _replace_grant_resource_policy(
    database: Database,
    grant_id: str,
    *,
    max_cpu_workers: int,
) -> None:
    """Reproduce a historical broad persisted profile with synthetic data."""

    with database._connection() as connection:
        row = connection.execute(
            "SELECT * FROM automation_grants WHERE grant_id=?", (grant_id,)
        ).fetchone()
        metrics = connection.execute(
            """
            SELECT metric_key,ordinal FROM automation_grant_metrics
            WHERE grant_id=? ORDER BY ordinal
            """,
            (grant_id,),
        ).fetchall()
        assert row is not None
        columns = tuple(row.keys())
        values = dict(row)
        values["max_cpu_workers"] = max_cpu_workers
        connection.execute("DELETE FROM automation_grants WHERE grant_id=?", (grant_id,))
        connection.execute(
            f"INSERT INTO automation_grants({','.join(columns)}) "
            f"VALUES ({','.join('?' for _ in columns)})",
            tuple(values[column] for column in columns),
        )
        connection.executemany(
            "INSERT INTO automation_grant_metrics VALUES (?,?,?)",
            ((grant_id, item["metric_key"], item["ordinal"]) for item in metrics),
        )
        connection.commit()


def _invalidate_automation_runtime_grant(
    database: Database,
    clock: MutableClock,
    launch: EstimatorRuntimeLaunch,
    variant: str,
) -> None:
    grant_id = launch.authorization.automation_grant_id
    assert grant_id is not None
    if variant == "missing":
        with database._connection() as connection:
            connection.execute("DELETE FROM automation_grants WHERE grant_id=?", (grant_id,))
            connection.commit()
    elif variant == "revoked":
        database.automation_grant_repository().revoke(grant_id, now=clock())
    elif variant == "expired":
        clock.advance(days=31)
        assert database.automation_grant_repository().expire_due(now=clock()) == 1
    elif variant == "past_expiry":
        clock.advance(days=31)
    elif variant == "unsupported":
        _replace_grant_resource_policy(database, grant_id, max_cpu_workers=2)
    elif variant == "scope":
        with database._connection() as connection:
            connection.execute(
                "DELETE FROM automation_grant_metrics WHERE grant_id=?", (grant_id,)
            )
            connection.execute(
                "INSERT INTO automation_grant_metrics VALUES (?,?,0)",
                (grant_id, "different.metric"),
            )
            connection.commit()
    else:  # pragma: no cover - test helper exhaustiveness
        raise AssertionError(f"unexpected invalidation variant: {variant}")


@pytest.mark.parametrize(
    ("variant", "options"),
    (
        ("missing", {"create_grant": False}),
        ("expired", {"grant_created_offset_days": -31}),
        ("route", {"route": AutomationRoute.FAST}),
        ("cpu", {"resource_policy": AutomationResourcePolicy(max_cpu_workers=2)}),
        (
            "battery",
            {"resource_policy": AutomationResourcePolicy(pause_on_battery=False)},
        ),
        (
            "runtime",
            {
                "resource_policy": AutomationResourcePolicy(
                    maximum_session_seconds=3_600
                )
            },
        ),
        ("metrics", {"metric_keys": ("different.metric",)}),
        ("project", {"grant_project_id": digest("different-grant-project")}),
    ),
)
def test_automation_grant_must_exist_and_match_exact_local_scope(
    tmp_path,
    variant: str,
    options: dict[str, object],
) -> None:
    _database_, _clock, _catalog, repository, _source, launch = (
        _automation_runtime_setup(tmp_path, label=f"grant-{variant}", **options)
    )
    with pytest.raises(DatabaseInvariantError, match="automation grant"):
        repository.launch(launch)


@pytest.mark.parametrize(
    ("variant", "expected_reason"),
    (
        ("missing", "automation_grant_not_found"),
        ("revoked", "automation_grant_inactive"),
        ("expired", "automation_grant_expired"),
        ("unsupported", "automation_resource_policy_unsupported"),
        ("scope", "automation_grant_scope_mismatch"),
    ),
)
def test_invalid_automation_runtime_reconciles_fixed_reason_without_source_access(
    tmp_path,
    variant: str,
    expected_reason: str,
) -> None:
    database, clock, _catalog, repository, source, launch = _automation_runtime_setup(
        tmp_path, label=f"cleanup-{variant}"
    )
    repository.launch(launch)
    _invalidate_automation_runtime_grant(database, clock, launch, variant)

    repository.reconcile_invalid_automation_grants(now=clock())
    snapshot = repository.get_by_job(launch.authorization.job_id)
    assert snapshot is not None
    assert snapshot.job.state is AnalysisJobState.CANCELLED
    assert snapshot.job.cancel_requested is True
    assert snapshot.job.attempt_count == 0
    assert snapshot.job.lease_owner is None
    assert snapshot.job.lease_token is None
    assert snapshot.job.terminal_reason_code == expected_reason
    assert snapshot.job.last_error_code == expected_reason
    assert [item.state for item in snapshot.states] == [
        EstimatorRuntimeState.CREATED,
        EstimatorRuntimeState.CANCELLED,
    ]
    assert snapshot.states[-1].reason_code == expected_reason
    assert snapshot.attempts == snapshot.checkpoints == ()
    assert source.identity_reads == source.packet_reads == source.objective_reads == 0

    # Reconciliation is idempotent after the exact terminal pair is sealed.
    repository.reconcile_invalid_automation_grants(now=clock())
    repeated = repository.get_by_job(launch.authorization.job_id)
    assert repeated == snapshot


@pytest.mark.parametrize(
    ("variants", "expected_reason"),
    (
        (("revoked", "past_expiry"), "automation_grant_inactive"),
        (("unsupported", "expired"), "automation_grant_expired"),
        (
            ("scope", "unsupported"),
            "automation_resource_policy_unsupported",
        ),
        (("scope", "missing"), "automation_grant_not_found"),
    ),
)
def test_invalid_automation_runtime_uses_fixed_reason_precedence(
    tmp_path,
    variants: tuple[str, ...],
    expected_reason: str,
) -> None:
    database, clock, _catalog, repository, _source, launch = (
        _automation_runtime_setup(
            tmp_path,
            label=f"cleanup-precedence-{'-'.join(variants)}",
        )
    )
    repository.launch(launch)
    for variant in variants:
        _invalidate_automation_runtime_grant(database, clock, launch, variant)

    repository.reconcile_invalid_automation_grants(now=clock())
    snapshot = repository.get_by_job(launch.authorization.job_id)
    assert snapshot is not None
    assert snapshot.job.state is AnalysisJobState.CANCELLED
    assert snapshot.job.terminal_reason_code == expected_reason
    assert snapshot.states[-1].reason_code == expected_reason


def test_reconciled_invalid_estimator_does_not_starve_manual(
    tmp_path,
) -> None:
    database, clock, catalog, repository, source, launch = _automation_runtime_setup(
        tmp_path, label="grant-revoked"
    )
    repository.launch(launch)
    _invalidate_automation_runtime_grant(database, clock, launch, "revoked")
    assert repository.authorization_is_valid(
        launch.authorization.job_id, now=clock()
    ) is False
    repository.reconcile_invalid_automation_grants(now=clock())
    manual = AnalysisJobService(database.analysis_job_repository(), clock=clock).enqueue(
        AnalysisJobIdentity(
            kind=AnalysisJobKind.SESSION_QUALITY,
            provider=launch.authorization.provider,
            project_id=launch.authorization.project_id,
            session_id=launch.authorization.session_id,
            input_fingerprint=digest("deferred-invalid-manual-input"),
            provenance_fingerprint=digest("deferred-invalid-manual-provenance"),
            metric_keys=tuple(
                binding.metric_key
                for binding in launch.authorization.packet_bindings
            ),
            estimator_plan_version="synthetic-manual-plan-v1",
            redactor_version=launch.authorization.redactor_version,
            provider_schema_version=launch.authorization.provider_schema_version,
        )
    ).job
    claimed = database.analysis_job_repository().claim_next(
        owner=digest("grant-revoked-worker"),
        token=digest("grant-revoked-token"),
        now=clock(),
        lease_duration=timedelta(seconds=30),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )
    assert claimed is not None and claimed.job_id == manual.job_id
    snapshot = repository.get_by_job(launch.authorization.job_id)
    assert snapshot is not None
    assert snapshot.job.state is AnalysisJobState.CANCELLED
    assert snapshot.job.attempt_count == 0
    assert snapshot.job.lease_owner is None
    assert snapshot.job.lease_token is None
    assert snapshot.job.lease_expires_at is None
    assert snapshot.states[-1].state is EstimatorRuntimeState.CANCELLED
    assert snapshot.states[-1].reason_code == "automation_grant_inactive"
    completed_manual = database.analysis_job_repository().get(manual.job_id)
    assert completed_manual is not None
    assert completed_manual.state is AnalysisJobState.PREPROCESSING
    assert source.identity_reads == source.packet_reads == 0


def test_invalid_running_runtime_closes_checkpoint_state_and_queue_atomically(
    tmp_path,
) -> None:
    database, clock, _catalog, repository, source, launch = _automation_runtime_setup(
        tmp_path, label="cleanup-running"
    )
    repository.launch(launch)
    claimed = database.analysis_job_repository().claim_next(
        owner=digest("cleanup-running-owner"),
        token=digest("cleanup-running-token"),
        now=clock(),
        lease_duration=timedelta(minutes=1),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )
    assert claimed is not None and claimed.job_id == launch.authorization.job_id
    created = repository.get_by_job(launch.authorization.job_id)
    assert created is not None
    repository.append_state(
        EstimatorRuntimeStateReceipt(
            state_receipt_id=digest("cleanup-running-state"),
            execution_id=launch.authorization.execution_id,
            sequence=1,
            previous_state_receipt_fingerprint=created.states[-1].canonical_fingerprint,
            state=EstimatorRuntimeState.RUNNING,
            reason_code="runtime_worker_started",
            recorded_at=clock(),
        )
    )
    binding = launch.authorization.packet_bindings[0]
    with database._connection() as connection:
        with repository._authorized(
            connection,
            launch.authorization.authorization_id,
            launch.authorization.execution_id,
            launch.authorization.job_id,
        ):
            repository._insert_checkpoint_locked(
                connection,
                launch.authorization.authorization_id,
                EstimatorRuntimeCheckpointReceipt(
                    checkpoint_id=digest("cleanup-running-checkpoint"),
                    execution_id=launch.authorization.execution_id,
                    metric_key=binding.metric_key,
                    sequence=0,
                    last_completed_stage_ordinal=0,
                    next_stage_ordinal=1,
                    restart_generation=0,
                    state=EstimatorRuntimeState.RUNNING,
                    reason_code="runtime_worker_started",
                    recorded_at=clock(),
                ),
            )
        connection.commit()
    database.analysis_job_repository().retry_or_fail(
        AnalysisJobLease(
            job_id=claimed.job_id,
            owner=claimed.lease_owner,
            token=claimed.lease_token,
            expires_at=claimed.lease_expires_at,
        ),
        now=clock(),
        error_code="synthetic_retry",
        retryable=True,
    )
    _invalidate_automation_runtime_grant(database, clock, launch, "revoked")

    repository.reconcile_invalid_automation_grants(now=clock())
    snapshot = repository.get_by_job(launch.authorization.job_id)
    assert snapshot is not None
    assert snapshot.job.state is AnalysisJobState.CANCELLED
    assert snapshot.job.attempt_count == 1
    assert snapshot.job.terminal_reason_code == "automation_grant_inactive"
    assert [item.state for item in snapshot.states] == [
        EstimatorRuntimeState.CREATED,
        EstimatorRuntimeState.RUNNING,
        EstimatorRuntimeState.CANCELLED,
    ]
    assert [item.state for item in snapshot.checkpoints] == [
        EstimatorRuntimeState.RUNNING,
        EstimatorRuntimeState.CANCELLED,
    ]
    terminal_checkpoint = snapshot.checkpoints[-1]
    assert terminal_checkpoint.sequence == 1
    assert terminal_checkpoint.previous_checkpoint_fingerprint == (
        snapshot.checkpoints[0].canonical_fingerprint
    )
    assert terminal_checkpoint.last_completed_stage_ordinal == 0
    assert terminal_checkpoint.next_stage_ordinal is None
    assert terminal_checkpoint.restart_generation == 0
    assert terminal_checkpoint.reason_code == "automation_grant_inactive"
    assert source.identity_reads == source.packet_reads == source.objective_reads == 0


def test_invalid_running_runtime_recovers_output_ahead_of_checkpoint(
    tmp_path,
) -> None:
    (
        database,
        clock,
        catalog,
        repository,
        source,
        launch,
    ) = _automation_runtime_setup(tmp_path, label="cleanup-output-ahead")
    repository.launch(launch)
    claimed = database.analysis_job_repository().claim_next(
        owner=digest("cleanup-output-ahead-owner"),
        token=digest("cleanup-output-ahead-token"),
        now=clock(),
        lease_duration=timedelta(minutes=1),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )
    assert claimed is not None
    created = repository.get_by_job(launch.authorization.job_id)
    assert created is not None
    repository.append_state(
        EstimatorRuntimeStateReceipt(
            state_receipt_id=digest("cleanup-output-ahead-running"),
            execution_id=launch.authorization.execution_id,
            sequence=1,
            previous_state_receipt_fingerprint=created.states[-1].canonical_fingerprint,
            state=EstimatorRuntimeState.RUNNING,
            reason_code="runtime_worker_started",
            recorded_at=clock(),
        )
    )
    binding = launch.authorization.packet_bindings[0]
    registration = catalog.plan_for_route(launch.authorization.route)
    attempt = EstimatorRuntimeStageAttemptReceipt(
        attempt_id=digest("cleanup-output-ahead-attempt"),
        execution_id=launch.authorization.execution_id,
        metric_key=binding.metric_key,
        metric_question_fingerprint=binding.metric_question_fingerprint,
        evidence_packet_fingerprint=binding.evidence_packet_fingerprint,
        stage_ordinal=1,
        stage_kind=registration.stage_registration(1).stage_kind,
        stage_fingerprint=registration.stage_registration(1).stage_fingerprint,
        attempt_ordinal=1,
        started_at=clock(),
    )
    repository.append_stage_attempt(attempt)
    objective = source.objective_evidence(source.packet)
    observation = EstimatorRuntimeMetricObservation(
        observation_id=digest("cleanup-output-ahead-observation"),
        execution_id=launch.authorization.execution_id,
        attempt_id=attempt.attempt_id,
        metric_key=binding.metric_key,
        metric_question_fingerprint=binding.metric_question_fingerprint,
        evidence_packet_fingerprint=binding.evidence_packet_fingerprint,
        state=objective.state,
        value_kind=objective.value_kind,
        numeric_value=objective.numeric_value,
        numerator=objective.numerator,
        denominator=objective.denominator,
        opaque_evidence_refs=objective.opaque_evidence_refs,
        observed_at=clock(),
    )
    repository.append_metric_observation(observation)
    repository.append_stage_outcome(
        EstimatorRuntimeStageOutcomeReceipt(
            outcome_id=digest("cleanup-output-ahead-outcome"),
            attempt_id=attempt.attempt_id,
            execution_id=launch.authorization.execution_id,
            state=EstimatorRuntimeStageOutcomeState.COMPLETED,
            reason_code="objective_observation_recorded",
            output_fingerprint=observation.canonical_fingerprint,
            finished_at=clock(),
        )
    )
    database.analysis_job_repository().retry_or_fail(
        AnalysisJobLease(
            job_id=claimed.job_id,
            owner=claimed.lease_owner,
            token=claimed.lease_token,
            expires_at=claimed.lease_expires_at,
        ),
        now=clock(),
        error_code="synthetic_retry",
        retryable=True,
    )
    _invalidate_automation_runtime_grant(database, clock, launch, "revoked")

    repository.reconcile_invalid_automation_grants(now=clock())
    snapshot = repository.get_by_job(launch.authorization.job_id)
    assert snapshot is not None
    assert snapshot.job.state is AnalysisJobState.CANCELLED
    assert snapshot.states[-1].state is EstimatorRuntimeState.CANCELLED
    assert len(snapshot.checkpoints) == 1
    assert snapshot.checkpoints[0].last_completed_stage_ordinal == 1
    assert snapshot.checkpoints[0].next_stage_ordinal is None
    assert snapshot.checkpoints[0].state is EstimatorRuntimeState.CANCELLED
    # The test's only source call prepared the synthetic durable output. Cleanup
    # itself must not revisit identity, packet, or objective material.
    assert source.identity_reads == source.packet_reads == 0
    assert source.objective_reads == 1


def test_invalid_running_runtime_rejects_future_interrupted_outcome(
    tmp_path,
) -> None:
    database, clock, catalog, repository, source, launch = _automation_runtime_setup(
        tmp_path, label="cleanup-future-interrupted"
    )
    repository.launch(launch)
    claimed = database.analysis_job_repository().claim_next(
        owner=digest("cleanup-future-interrupted-owner"),
        token=digest("cleanup-future-interrupted-token"),
        now=clock(),
        lease_duration=timedelta(minutes=10),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )
    assert claimed is not None
    created = repository.get_by_job(launch.authorization.job_id)
    assert created is not None
    cleanup_now = clock()
    repository.append_state(
        EstimatorRuntimeStateReceipt(
            state_receipt_id=digest("cleanup-future-interrupted-running"),
            execution_id=launch.authorization.execution_id,
            sequence=1,
            previous_state_receipt_fingerprint=created.states[-1].canonical_fingerprint,
            state=EstimatorRuntimeState.RUNNING,
            reason_code="runtime_worker_started",
            recorded_at=cleanup_now,
        )
    )
    clock.advance(minutes=5)
    binding = launch.authorization.packet_bindings[0]
    registration = catalog.plan_for_route(launch.authorization.route)
    attempt = EstimatorRuntimeStageAttemptReceipt(
        attempt_id=digest("cleanup-future-interrupted-attempt"),
        execution_id=launch.authorization.execution_id,
        metric_key=binding.metric_key,
        metric_question_fingerprint=binding.metric_question_fingerprint,
        evidence_packet_fingerprint=binding.evidence_packet_fingerprint,
        stage_ordinal=1,
        stage_kind=registration.stage_registration(1).stage_kind,
        stage_fingerprint=registration.stage_registration(1).stage_fingerprint,
        attempt_ordinal=1,
        started_at=clock(),
    )
    repository.append_stage_attempt(attempt)
    clock.advance(minutes=1)
    repository.append_stage_outcome(
        EstimatorRuntimeStageOutcomeReceipt(
            outcome_id=digest("cleanup-future-interrupted-outcome"),
            attempt_id=attempt.attempt_id,
            execution_id=launch.authorization.execution_id,
            state=EstimatorRuntimeStageOutcomeState.INTERRUPTED,
            reason_code="synthetic_interruption",
            finished_at=clock(),
        )
    )
    database.analysis_job_repository().retry_or_fail(
        AnalysisJobLease(
            job_id=claimed.job_id,
            owner=claimed.lease_owner,
            token=claimed.lease_token,
            expires_at=claimed.lease_expires_at,
        ),
        now=clock(),
        error_code="synthetic_retry",
        retryable=True,
    )
    clock.value = cleanup_now
    _invalidate_automation_runtime_grant(database, clock, launch, "revoked")
    before = repository.get_by_job(launch.authorization.job_id)

    repository.reconcile_invalid_automation_grants(now=clock())

    assert repository.get_by_job(launch.authorization.job_id) == before
    assert before is not None and before.job.state is AnalysisJobState.QUEUED
    assert before.states[-1].state is EstimatorRuntimeState.RUNNING
    assert before.outcomes[-1].state is EstimatorRuntimeStageOutcomeState.INTERRUPTED
    assert before.outcomes[-1].finished_at > cleanup_now
    assert source.identity_reads == source.packet_reads == source.objective_reads == 0
    with database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_runtime_write_authorizations"
        ).fetchone()[0] == 0
    assert database._estimator_runtime_authorizations == set()


def test_invalid_runtime_reconciliation_rolls_back_receipt_and_queue_together(
    tmp_path,
    monkeypatch,
) -> None:
    database, clock, _catalog, repository, source, launch = _automation_runtime_setup(
        tmp_path, label="cleanup-rollback"
    )
    repository.launch(launch)
    _invalidate_automation_runtime_grant(database, clock, launch, "revoked")
    original = repository._insert_terminal_state_locked

    def fail_after_state(*args, **kwargs):  # type: ignore[no-untyped-def]
        original(*args, **kwargs)
        raise DatabaseInvariantError("synthetic cleanup interruption")

    monkeypatch.setattr(repository, "_insert_terminal_state_locked", fail_after_state)
    with pytest.raises(DatabaseInvariantError, match="synthetic cleanup interruption"):
        repository.reconcile_invalid_automation_grants(now=clock())
    pending = repository.get_by_job(launch.authorization.job_id)
    assert pending is not None
    assert pending.job.state is AnalysisJobState.QUEUED
    assert [item.state for item in pending.states] == [EstimatorRuntimeState.CREATED]
    assert source.identity_reads == source.packet_reads == source.objective_reads == 0
    with database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_runtime_write_authorizations"
        ).fetchone()[0] == 0
    assert database._estimator_runtime_authorizations == set()

    monkeypatch.setattr(repository, "_insert_terminal_state_locked", original)
    repository.reconcile_invalid_automation_grants(now=clock())
    closed = repository.get_by_job(launch.authorization.job_id)
    assert closed is not None and closed.job.state is AnalysisJobState.CANCELLED
    with database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_runtime_write_authorizations"
        ).fetchone()[0] == 0
    assert database._estimator_runtime_authorizations == set()


def test_invalid_running_reconciliation_rolls_back_checkpoint_state_and_queue(
    tmp_path,
    monkeypatch,
) -> None:
    database, clock, _catalog, repository, _source, launch = (
        _automation_runtime_setup(tmp_path, label="cleanup-running-rollback")
    )
    repository.launch(launch)
    claimed = database.analysis_job_repository().claim_next(
        owner=digest("cleanup-running-rollback-owner"),
        token=digest("cleanup-running-rollback-token"),
        now=clock(),
        lease_duration=timedelta(minutes=1),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )
    assert claimed is not None
    created = repository.get_by_job(launch.authorization.job_id)
    assert created is not None
    repository.append_state(
        EstimatorRuntimeStateReceipt(
            state_receipt_id=digest("cleanup-running-rollback-state"),
            execution_id=launch.authorization.execution_id,
            sequence=1,
            previous_state_receipt_fingerprint=created.states[-1].canonical_fingerprint,
            state=EstimatorRuntimeState.RUNNING,
            reason_code="runtime_worker_started",
            recorded_at=clock(),
        )
    )
    database.analysis_job_repository().retry_or_fail(
        AnalysisJobLease(
            job_id=claimed.job_id,
            owner=claimed.lease_owner,
            token=claimed.lease_token,
            expires_at=claimed.lease_expires_at,
        ),
        now=clock(),
        error_code="synthetic_retry",
        retryable=True,
    )
    _invalidate_automation_runtime_grant(database, clock, launch, "revoked")
    before = repository.get_by_job(launch.authorization.job_id)

    def fail_after_checkpoints(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise DatabaseInvariantError("synthetic running cleanup interruption")

    monkeypatch.setattr(
        repository, "_insert_terminal_state_locked", fail_after_checkpoints
    )
    with pytest.raises(
        DatabaseInvariantError, match="synthetic running cleanup interruption"
    ):
        repository.reconcile_invalid_automation_grants(now=clock())
    assert repository.get_by_job(launch.authorization.job_id) == before
    with database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_runtime_write_authorizations"
        ).fetchone()[0] == 0
    assert database._estimator_runtime_authorizations == set()

def test_concurrent_invalid_runtime_reconciliation_appends_one_terminal_receipt(
    tmp_path,
) -> None:
    database, clock, _catalog, repository, source, launch = _automation_runtime_setup(
        tmp_path, label="cleanup-concurrent"
    )
    repository.launch(launch)
    _invalidate_automation_runtime_grant(database, clock, launch, "revoked")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = tuple(
            pool.submit(
                database.estimator_runtime_repository().reconcile_invalid_automation_grants,
                now=clock(),
            )
            for _ in range(2)
        )
        for future in futures:
            future.result()
    snapshot = repository.get_by_job(launch.authorization.job_id)
    assert snapshot is not None
    assert snapshot.job.state is AnalysisJobState.CANCELLED
    assert [item.state for item in snapshot.states] == [
        EstimatorRuntimeState.CREATED,
        EstimatorRuntimeState.CANCELLED,
    ]
    assert source.identity_reads == source.packet_reads == source.objective_reads == 0


def test_invalid_runtime_cleanup_leaves_terminal_checkpoint_anomaly_unchanged(
    tmp_path,
) -> None:
    database, clock, _catalog, repository, _source, launch = (
        _automation_runtime_setup(tmp_path, label="cleanup-terminal-checkpoint")
    )
    repository.launch(launch)
    claimed = database.analysis_job_repository().claim_next(
        owner=digest("cleanup-terminal-checkpoint-owner"),
        token=digest("cleanup-terminal-checkpoint-token"),
        now=clock(),
        lease_duration=timedelta(minutes=1),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )
    assert claimed is not None
    created = repository.get_by_job(launch.authorization.job_id)
    assert created is not None
    repository.append_state(
        EstimatorRuntimeStateReceipt(
            state_receipt_id=digest("cleanup-terminal-checkpoint-running"),
            execution_id=launch.authorization.execution_id,
            sequence=1,
            previous_state_receipt_fingerprint=created.states[-1].canonical_fingerprint,
            state=EstimatorRuntimeState.RUNNING,
            reason_code="runtime_worker_started",
            recorded_at=clock(),
        )
    )
    binding = launch.authorization.packet_bindings[0]
    with database._connection() as connection:
        with repository._authorized(
            connection,
            launch.authorization.authorization_id,
            launch.authorization.execution_id,
            launch.authorization.job_id,
        ):
            repository._insert_checkpoint_locked(
                connection,
                launch.authorization.authorization_id,
                EstimatorRuntimeCheckpointReceipt(
                    checkpoint_id=digest("cleanup-terminal-checkpoint-anomaly"),
                    execution_id=launch.authorization.execution_id,
                    metric_key=binding.metric_key,
                    sequence=0,
                    last_completed_stage_ordinal=0,
                    next_stage_ordinal=None,
                    restart_generation=0,
                    state=EstimatorRuntimeState.CANCELLED,
                    reason_code="synthetic_checkpoint_anomaly",
                    recorded_at=clock(),
                ),
            )
        connection.commit()
    database.analysis_job_repository().retry_or_fail(
        AnalysisJobLease(
            job_id=claimed.job_id,
            owner=claimed.lease_owner,
            token=claimed.lease_token,
            expires_at=claimed.lease_expires_at,
        ),
        now=clock(),
        error_code="synthetic_retry",
        retryable=True,
    )
    _invalidate_automation_runtime_grant(database, clock, launch, "revoked")
    before = repository.get_by_job(launch.authorization.job_id)

    repository.reconcile_invalid_automation_grants(now=clock())
    assert repository.get_by_job(launch.authorization.job_id) == before
    assert before is not None and before.job.state is AnalysisJobState.QUEUED
    assert before.states[-1].state is EstimatorRuntimeState.RUNNING
    assert before.checkpoints[-1].state is EstimatorRuntimeState.CANCELLED


def test_invalid_runtime_cleanup_leaves_created_history_anomaly_unchanged(
    tmp_path,
) -> None:
    database, clock, _catalog, repository, _source, launch = (
        _automation_runtime_setup(tmp_path, label="cleanup-created-history")
    )
    repository.launch(launch)
    binding = launch.authorization.packet_bindings[0]
    with database._connection() as connection:
        with repository._authorized(
            connection,
            launch.authorization.authorization_id,
            launch.authorization.execution_id,
            launch.authorization.job_id,
        ):
            repository._insert_checkpoint_locked(
                connection,
                launch.authorization.authorization_id,
                EstimatorRuntimeCheckpointReceipt(
                    checkpoint_id=digest("cleanup-created-history-checkpoint"),
                    execution_id=launch.authorization.execution_id,
                    metric_key=binding.metric_key,
                    sequence=0,
                    last_completed_stage_ordinal=0,
                    next_stage_ordinal=1,
                    restart_generation=0,
                    state=EstimatorRuntimeState.CREATED,
                    reason_code="synthetic_created_history",
                    recorded_at=clock(),
                ),
            )
        connection.commit()
    _invalidate_automation_runtime_grant(database, clock, launch, "revoked")
    before = repository.get_by_job(launch.authorization.job_id)

    repository.reconcile_invalid_automation_grants(now=clock())
    assert repository.get_by_job(launch.authorization.job_id) == before
    assert before is not None and before.job.state is AnalysisJobState.QUEUED
    assert before.states[-1].state is EstimatorRuntimeState.CREATED


def test_invalid_runtime_cleanup_leaves_open_attempt_for_recovery(
    tmp_path,
) -> None:
    database, clock, catalog, repository, _source, launch = (
        _automation_runtime_setup(tmp_path, label="cleanup-open-attempt")
    )
    repository.launch(launch)
    claimed = database.analysis_job_repository().claim_next(
        owner=digest("cleanup-open-attempt-owner"),
        token=digest("cleanup-open-attempt-token"),
        now=clock(),
        lease_duration=timedelta(minutes=1),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )
    assert claimed is not None
    created = repository.get_by_job(launch.authorization.job_id)
    assert created is not None
    repository.append_state(
        EstimatorRuntimeStateReceipt(
            state_receipt_id=digest("cleanup-open-attempt-running"),
            execution_id=launch.authorization.execution_id,
            sequence=1,
            previous_state_receipt_fingerprint=created.states[-1].canonical_fingerprint,
            state=EstimatorRuntimeState.RUNNING,
            reason_code="runtime_worker_started",
            recorded_at=clock(),
        )
    )
    binding = launch.authorization.packet_bindings[0]
    registration = catalog.plan_for_route(launch.authorization.route)
    repository.append_stage_attempt(
        EstimatorRuntimeStageAttemptReceipt(
            attempt_id=digest("cleanup-open-attempt-stage"),
            execution_id=launch.authorization.execution_id,
            metric_key=binding.metric_key,
            metric_question_fingerprint=binding.metric_question_fingerprint,
            evidence_packet_fingerprint=binding.evidence_packet_fingerprint,
            stage_ordinal=1,
            stage_kind=registration.stage_registration(1).stage_kind,
            stage_fingerprint=registration.stage_registration(1).stage_fingerprint,
            attempt_ordinal=1,
            started_at=clock(),
        )
    )
    database.analysis_job_repository().retry_or_fail(
        AnalysisJobLease(
            job_id=claimed.job_id,
            owner=claimed.lease_owner,
            token=claimed.lease_token,
            expires_at=claimed.lease_expires_at,
        ),
        now=clock(),
        error_code="synthetic_retry",
        retryable=True,
    )
    _invalidate_automation_runtime_grant(database, clock, launch, "revoked")
    before = repository.get_by_job(launch.authorization.job_id)

    repository.reconcile_invalid_automation_grants(now=clock())
    assert repository.get_by_job(launch.authorization.job_id) == before
    assert before is not None and before.job.state is AnalysisJobState.QUEUED
    assert len(before.attempts) == 1 and before.outcomes == ()


@pytest.mark.parametrize(
    ("runtime_state", "reason_code"),
    (
        (EstimatorRuntimeState.PARTIAL, "local_model_runtime_not_enabled"),
        (EstimatorRuntimeState.FAILED, "execution_handler_failed"),
    ),
)
def test_invalid_grant_mirrors_existing_terminal_runtime_without_relabeling(
    tmp_path,
    runtime_state: EstimatorRuntimeState,
    reason_code: str,
) -> None:
    database, clock, _catalog, repository, source, launch = _automation_runtime_setup(
        tmp_path, label=f"cleanup-terminal-{runtime_state.value}"
    )
    repository.launch(launch)
    claimed = database.analysis_job_repository().claim_next(
        owner=digest(f"cleanup-terminal-{runtime_state.value}-owner"),
        token=digest(f"cleanup-terminal-{runtime_state.value}-token"),
        now=clock(),
        lease_duration=timedelta(minutes=1),
        power_source=PowerSourceState.EXTERNAL_POWER,
    )
    assert claimed is not None
    created = repository.get_by_job(launch.authorization.job_id)
    assert created is not None
    running = EstimatorRuntimeStateReceipt(
        state_receipt_id=digest(f"cleanup-terminal-{runtime_state.value}-running"),
        execution_id=launch.authorization.execution_id,
        sequence=1,
        previous_state_receipt_fingerprint=created.states[-1].canonical_fingerprint,
        state=EstimatorRuntimeState.RUNNING,
        reason_code="runtime_worker_started",
        recorded_at=clock(),
    )
    repository.append_state(running)
    repository.append_state(
        EstimatorRuntimeStateReceipt(
            state_receipt_id=digest(
                f"cleanup-terminal-{runtime_state.value}-terminal"
            ),
            execution_id=launch.authorization.execution_id,
            sequence=2,
            previous_state_receipt_fingerprint=running.canonical_fingerprint,
            state=runtime_state,
            reason_code=reason_code,
            recorded_at=clock(),
        )
    )
    with database._connection() as connection:
        connection.execute(
            """
            UPDATE analysis_jobs SET state='queued',stage_number=NULL,
                available_at=?,lease_owner=NULL,lease_token=NULL,
                lease_expires_at=NULL,last_error_code='synthetic_retry',
                terminal_reason_code=NULL,terminal_at=NULL,updated_at=?
            WHERE job_id=? AND state IN ('preprocessing','stage_n')
            """,
            (
                clock().isoformat(timespec="microseconds"),
                clock().isoformat(timespec="microseconds"),
                launch.authorization.job_id,
            ),
        )
        connection.commit()
    _invalidate_automation_runtime_grant(database, clock, launch, "revoked")

    repository.reconcile_invalid_automation_grants(now=clock())
    snapshot = repository.get_by_job(launch.authorization.job_id)
    assert snapshot is not None
    assert snapshot.job.state is AnalysisJobState(runtime_state.value)
    assert snapshot.job.terminal_reason_code == reason_code
    assert snapshot.job.cancel_requested is False
    assert snapshot.job.last_error_code == "synthetic_retry"
    assert len(snapshot.states) == 3
    assert snapshot.states[-1].state is runtime_state
    assert snapshot.states[-1].reason_code == reason_code
    assert snapshot.checkpoints == ()
    assert source.identity_reads == source.packet_reads == source.objective_reads == 0

    repository.reconcile_invalid_automation_grants(now=clock())
    assert repository.get_by_job(launch.authorization.job_id) == snapshot


def test_v18_atomic_launch_and_real_worker_stop_truthfully_partial(tmp_path) -> None:
    database, clock, catalog, repository, source, launch, _ = _setup(tmp_path)
    with database._connection(readonly=True) as connection:
        metric_result_count = connection.execute(
            "SELECT COUNT(*) FROM metric_results"
        ).fetchone()[0]

    launched = EstimatorRuntimeService(repository, catalog, clock=clock).launch(launch)
    assert SCHEMA_VERSION == 61
    assert launched.job.identity.kind is AnalysisJobKind.ESTIMATOR_EXECUTION
    assert launched.authorization_consumed is True
    assert launched.authorization.activation_allowed is False
    assert launched.authorization.product_metric_write_allowed is False

    handler = EstimatorRuntimeHandler(repository, catalog, source, clock=clock)
    assert _worker(database, clock, handler).run_once() is True
    snapshot = repository.get_by_job(launch.authorization.job_id)
    assert snapshot is not None
    assert snapshot.job.state is AnalysisJobState.PARTIAL
    assert snapshot.job.terminal_reason_code == "local_model_runtime_not_enabled"
    assert snapshot.job.progress_completed == 3
    assert snapshot.job.progress_total == 8
    assert [item.state for item in snapshot.states] == [
        EstimatorRuntimeState.CREATED,
        EstimatorRuntimeState.RUNNING,
        EstimatorRuntimeState.PARTIAL,
    ]
    assert [item.stage_ordinal for item in snapshot.attempts] == [1, 2]
    assert len(snapshot.outcomes) == 2
    assert len(snapshot.observations) == 1
    assert snapshot.observations[0].calibration_state == "not_assessed"
    assert snapshot.observations[0].product_metric_write_allowed is False
    assert len(snapshot.retrievals) == 1
    assert snapshot.retrievals[0].calibration_state == "not_assessed"
    assert snapshot.retrievals[0].hits
    assert [item.sequence for item in snapshot.checkpoints] == [0, 1, 2]
    assert source.packet_reads == 1

    with database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM metric_results"
        ).fetchone()[0] == metric_result_count
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        runtime_columns = {
            row[1].lower()
            for table in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'estimator_runtime_%'"
            )
            for row in connection.execute(f"PRAGMA table_info({table[0]})")
        }
    forbidden = {
        "text",
        "prompt",
        "excerpt",
        "response",
        "commentary",
        "embedding",
        "json",
        "blob",
        "path",
        "uri",
    }
    assert not runtime_columns.intersection(forbidden)
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{database.path}{suffix}")
        if path.exists():
            assert PRIVATE_MARKER.encode("utf-8") not in path.read_bytes()


def test_one_shot_replay_and_remote_automation_fail_closed(tmp_path) -> None:
    _, clock, _, repository, _, launch, _ = _setup(tmp_path)
    repository.launch(launch)
    with pytest.raises(DatabaseInvariantError, match="one-shot"):
        repository.launch(launch)

    values = launch.authorization.model_dump(mode="python")
    values.update(
        kind=DurableRuntimeAuthorizationKind.AUTOMATION_ONCE,
        provider=Provider.CODEX,
        destination=ExecutionDestination.CODEX_CLI,
        retention_class=RetentionClass.PROVIDER_30_DAY,
        automation_grant_id=digest("automation-grant"),
        issued_at=clock(),
        expires_at=clock() + timedelta(minutes=10),
    )
    with pytest.raises(ValidationError, match="automation cannot authorize remote"):
        DurableRuntimeAuthorizationReceipt(**values)


def test_expiry_revocation_change_and_cancel_stop_before_packet_read(tmp_path) -> None:
    # Expiry is checked before the source identity or packet is read.
    database, clock, catalog, repository, source, launch, _ = _setup(
        tmp_path / "expiry", label="expiry"
    )
    repository.launch(launch)
    clock.advance(minutes=11)
    handler = EstimatorRuntimeHandler(repository, catalog, source, clock=clock)
    assert _worker(database, clock, handler).run_once()
    expired = repository.get_by_job(launch.authorization.job_id)
    assert expired is not None
    assert expired.job.state is AnalysisJobState.CANCELLED
    assert expired.states[-1].state is EstimatorRuntimeState.CANCELLED
    assert source.identity_reads == source.packet_reads == 0

    # A durable revocation has the same before-read behavior.
    database, clock, catalog, repository, source, launch, _ = _setup(
        tmp_path / "revoked", label="revoked"
    )
    repository.launch(launch)
    repository.revoke_authorization(
        launch.authorization.authorization_id, revoked_at=clock()
    )
    handler = EstimatorRuntimeHandler(repository, catalog, source, clock=clock)
    assert _worker(database, clock, handler).run_once()
    revoked = repository.get_by_job(launch.authorization.job_id)
    assert revoked is not None
    assert revoked.job.state is AnalysisJobState.CANCELLED
    assert revoked.authorization_revoked is True
    assert source.identity_reads == source.packet_reads == 0

    # Input drift is detected from metadata before packet material is opened.
    database, clock, catalog, repository, source, launch, _ = _setup(
        tmp_path / "changed", label="changed"
    )
    repository.launch(launch)
    source.current_identity = EstimatorRuntimeSourceIdentity(
        **{
            **source.current_identity.model_dump(mode="python"),
            "input_fingerprint": digest("changed-after-approval"),
        }
    )
    handler = EstimatorRuntimeHandler(repository, catalog, source, clock=clock)
    assert _worker(database, clock, handler).run_once()
    changed = repository.get_by_job(launch.authorization.job_id)
    assert changed is not None
    assert changed.job.state is AnalysisJobState.SUPERSEDED
    assert changed.states[-1].state is EstimatorRuntimeState.SUPERSEDED
    assert source.packet_reads == 0

    # A queue cancellation mirrors into the append-only runtime state journal.
    database, clock, catalog, repository, source, launch, _ = _setup(
        tmp_path / "cancelled", label="cancelled"
    )
    repository.launch(launch)
    EstimatorRuntimeService(repository, catalog, clock=clock).cancel(
        launch.authorization.job_id
    )
    cancelled = repository.get_by_job(launch.authorization.job_id)
    assert cancelled is not None
    assert cancelled.job.state is AnalysisJobState.CANCELLED
    assert cancelled.states[-1].state is EstimatorRuntimeState.CANCELLED
    assert source.packet_reads == 0


def test_interrupted_stage_restarts_without_duplicate_attempts_or_refs(tmp_path) -> None:
    database, clock, catalog, repository, source, launch, _ = _setup(
        tmp_path, label="restart"
    )
    repository.launch(launch)
    bm25 = FailOnceBm25()
    handler = EstimatorRuntimeHandler(
        repository, catalog, source, bm25=bm25, clock=clock
    )
    worker = _worker(database, clock, handler)
    assert worker.run_once()
    interrupted = repository.get_by_job(launch.authorization.job_id)
    assert interrupted is not None
    assert interrupted.job.state is AnalysisJobState.QUEUED
    assert interrupted.job.last_error_code == "execution_handler_failed"
    assert len(interrupted.observations) == 1
    assert len(interrupted.attempts) == 2
    assert len(interrupted.retrievals) == 0

    clock.advance(seconds=5)
    assert worker.run_once()
    completed = repository.get_by_job(launch.authorization.job_id)
    assert completed is not None
    assert completed.job.state is AnalysisJobState.PARTIAL
    assert len(completed.attempts) == 3
    bm25_attempts = [
        item for item in completed.attempts if item.stage_ordinal == 2
    ]
    assert [item.attempt_ordinal for item in bm25_attempts] == [1, 2]
    assert [
        item.state
        for item in completed.outcomes
        if item.attempt_id in {attempt.attempt_id for attempt in bm25_attempts}
    ] == [
        EstimatorRuntimeStageOutcomeState.INTERRUPTED,
        EstimatorRuntimeStageOutcomeState.COMPLETED,
    ]
    assert len(completed.observations) == 1
    assert len(completed.retrievals) == 1
    assert len(completed.retrievals[0].candidate_reference_ids) == len(
        set(completed.retrievals[0].candidate_reference_ids)
    )
    assert len(completed.retrievals[0].hits) == len(
        {item.evidence_reference_id for item in completed.retrievals[0].hits}
    )


def test_interrupted_objective_stage_records_truthful_new_attempt(tmp_path) -> None:
    database, clock, catalog, repository, source, launch, _ = _setup(
        tmp_path, label="objective-restart"
    )
    source = FailOnceObjectiveSource(source.packet, source.current_identity)
    repository.launch(launch)
    handler = EstimatorRuntimeHandler(repository, catalog, source, clock=clock)
    worker = _worker(database, clock, handler)
    assert worker.run_once()
    interrupted = repository.get_by_job(launch.authorization.job_id)
    assert interrupted is not None
    assert interrupted.job.state is AnalysisJobState.QUEUED
    assert [item.attempt_ordinal for item in interrupted.attempts] == [1]
    assert [item.state for item in interrupted.outcomes] == [
        EstimatorRuntimeStageOutcomeState.INTERRUPTED
    ]
    clock.advance(seconds=5)
    assert worker.run_once()
    completed = repository.get_by_job(launch.authorization.job_id)
    assert completed is not None
    objective_attempts = [
        item for item in completed.attempts if item.stage_ordinal == 1
    ]
    assert [item.attempt_ordinal for item in objective_attempts] == [1, 2]
    assert len(completed.observations) == 1
    assert completed.job.state is AnalysisJobState.PARTIAL


@pytest.mark.parametrize(
    "failed_reason",
    ("objective_observation_recorded", "bm25_retrieval_recorded"),
)
def test_persisted_stage_output_recovers_exact_outcome_and_checkpoint(
    tmp_path,
    monkeypatch,
    failed_reason: str,
) -> None:
    database, clock, catalog, repository, source, launch, _ = _setup(
        tmp_path, label=f"persisted-output-{failed_reason}"
    )
    repository.launch(launch)
    original_append = repository.append_stage_outcome
    failed = False

    def fail_once_after_output(receipt):  # type: ignore[no-untyped-def]
        nonlocal failed
        if not failed and receipt.reason_code == failed_reason:
            failed = True
            raise RuntimeError("synthetic post-output interruption")
        return original_append(receipt)

    monkeypatch.setattr(repository, "append_stage_outcome", fail_once_after_output)
    handler = EstimatorRuntimeHandler(repository, catalog, source, clock=clock)
    worker = _worker(database, clock, handler)
    assert worker.run_once()
    interrupted = repository.get_by_job(launch.authorization.job_id)
    assert interrupted is not None
    assert interrupted.job.state is AnalysisJobState.QUEUED
    if failed_reason == "objective_observation_recorded":
        assert len(interrupted.observations) == 1
        assert len(interrupted.outcomes) == 0
        assert len(interrupted.checkpoints) == 0
    else:
        assert len(interrupted.retrievals) == 1
        assert len(interrupted.outcomes) == 1
        assert [item.last_completed_stage_ordinal for item in interrupted.checkpoints] == [
            1
        ]

    clock.advance(seconds=5)
    assert worker.run_once()
    recovered = repository.get_by_job(launch.authorization.job_id)
    assert recovered is not None
    assert recovered.job.state is AnalysisJobState.PARTIAL
    assert len(recovered.observations) == 1
    assert len(recovered.retrievals) == 1
    assert len(recovered.attempts) == 2
    assert len(recovered.outcomes) == 2
    assert all(
        item.state is EstimatorRuntimeStageOutcomeState.COMPLETED
        for item in recovered.outcomes
    )
    assert [item.last_completed_stage_ordinal for item in recovered.checkpoints] == [
        1,
        2,
        2,
    ]
    stage_two = next(item for item in recovered.attempts if item.stage_ordinal == 2)
    retrieval = recovered.retrievals[0]
    stage_two_outcome = next(
        item for item in recovered.outcomes if item.attempt_id == stage_two.attempt_id
    )
    assert retrieval.attempt_id == stage_two.attempt_id
    assert stage_two_outcome.output_fingerprint == retrieval.canonical_fingerprint


def test_expired_lease_recovery_requeues_and_records_open_attempt_interrupted(
    tmp_path,
) -> None:
    database, clock, _catalog, repository, _source, launch, registration = _setup(
        tmp_path, label="expired-requeue"
    )
    claimed = _start_runtime(database, clock, repository, launch)
    binding = launch.authorization.packet_bindings[0]
    repository.append_stage_attempt(
        EstimatorRuntimeStageAttemptReceipt(
            attempt_id=digest("expired-open-attempt"),
            execution_id=launch.authorization.execution_id,
            metric_key=binding.metric_key,
            metric_question_fingerprint=binding.metric_question_fingerprint,
            evidence_packet_fingerprint=binding.evidence_packet_fingerprint,
            stage_ordinal=1,
            stage_kind=registration.stage_registration(1).stage_kind,
            stage_fingerprint=registration.stage_registration(1).stage_fingerprint,
            attempt_ordinal=1,
            started_at=clock(),
        )
    )
    clock.advance(minutes=2)
    repository.reconcile_expired(now=clock())
    recovered = repository.get_by_job(launch.authorization.job_id)
    assert recovered is not None
    assert recovered.job.state is AnalysisJobState.QUEUED
    assert recovered.job.last_error_code == "lease_expired"
    assert [item.state for item in recovered.outcomes] == [
        EstimatorRuntimeStageOutcomeState.INTERRUPTED
    ]
    assert recovered.outcomes[0].reason_code == "lease_expired_interrupted"


@pytest.mark.parametrize(
    ("requested_state", "reason", "runtime_state"),
    (
        (AnalysisJobState.CANCELLED, "cancellation_requested", EstimatorRuntimeState.CANCELLED),
        (AnalysisJobState.SUPERSEDED, "input_changed", EstimatorRuntimeState.SUPERSEDED),
    ),
)
def test_expired_lease_cancel_or_supersede_converges_both_ledgers(
    tmp_path,
    requested_state: AnalysisJobState,
    reason: str,
    runtime_state: EstimatorRuntimeState,
) -> None:
    database, clock, _catalog, repository, _source, launch, _ = _setup(
        tmp_path, label=f"expired-{requested_state.value}"
    )
    _start_runtime(database, clock, repository, launch)
    with database._connection() as connection:
        connection.execute(
            """
            UPDATE analysis_jobs SET cancel_requested=1,last_error_code=?
            WHERE job_id=?
            """,
            (reason, launch.authorization.job_id),
        )
        connection.commit()
    clock.advance(minutes=2)
    repository.reconcile_expired(now=clock())
    recovered = repository.get_by_job(launch.authorization.job_id)
    assert recovered is not None
    assert recovered.job.state is requested_state
    assert recovered.job.terminal_reason_code == reason
    assert recovered.states[-1].state is runtime_state
    assert recovered.states[-1].reason_code == reason


def test_expired_final_lease_fails_both_ledgers(tmp_path) -> None:
    database, clock, _catalog, repository, _source, launch, _ = _setup(
        tmp_path, label="expired-failed"
    )
    launch = EstimatorRuntimeLaunch(
        authorization=launch.authorization,
        packet_receipts=launch.packet_receipts,
        consumed_at=launch.consumed_at,
        max_attempts=1,
    )
    _start_runtime(database, clock, repository, launch)
    clock.advance(minutes=2)
    repository.reconcile_expired(now=clock())
    recovered = repository.get_by_job(launch.authorization.job_id)
    assert recovered is not None
    assert recovered.job.state is AnalysisJobState.FAILED
    assert recovered.job.terminal_reason_code == "lease_expired"
    assert recovered.states[-1].state is EstimatorRuntimeState.FAILED


def test_final_handler_failure_closes_queue_and_runtime_exactly(tmp_path) -> None:
    database, clock, catalog, repository, source, launch, _ = _setup(
        tmp_path, label="final-handler-failure"
    )
    launch = EstimatorRuntimeLaunch(
        authorization=launch.authorization,
        packet_receipts=launch.packet_receipts,
        consumed_at=launch.consumed_at,
        max_attempts=1,
    )
    repository.launch(launch)
    handler = EstimatorRuntimeHandler(
        repository, catalog, source, bm25=FailAlwaysBm25(), clock=clock
    )
    assert _worker(database, clock, handler).run_once()
    failed = repository.get_by_job(launch.authorization.job_id)
    assert failed is not None
    assert failed.job.state is AnalysisJobState.FAILED
    assert failed.job.terminal_reason_code == "execution_handler_failed"
    assert failed.states[-1].state is EstimatorRuntimeState.FAILED
    assert failed.states[-1].reason_code == "execution_handler_failed"
    bm25_attempt_id = next(
        item.attempt_id for item in failed.attempts if item.stage_ordinal == 2
    )
    assert next(
        item.state for item in failed.outcomes if item.attempt_id == bm25_attempt_id
    ) is EstimatorRuntimeStageOutcomeState.INTERRUPTED


def test_raw_sql_is_sealed_and_privacy_delete_purges_runtime_not_plan(tmp_path) -> None:
    database, clock, catalog, repository, source, launch, registration = _setup(
        tmp_path, label="privacy"
    )
    repository.launch(launch)
    handler = EstimatorRuntimeHandler(repository, catalog, source, clock=clock)
    assert _worker(database, clock, handler).run_once()

    with database._connection() as connection:
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(
                "UPDATE estimator_runtime_executions SET activation_allowed=1 WHERE execution_id=?",
                (launch.authorization.execution_id,),
            )
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(
                "DELETE FROM estimator_runtime_stage_attempts WHERE execution_id=?",
                (launch.authorization.execution_id,),
            )
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute(
                "INSERT INTO estimator_runtime_deletion_tombstones VALUES (?,?,?)",
                (
                    digest("forged-runtime-tombstone"),
                    registration.plan_fingerprint,
                    0,
                ),
            )

    reader = sqlite3.connect(database.path)
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM estimator_runtime_packet_refs").fetchall()
        with pytest.raises(DatabaseInvariantError, match="WAL privacy purge is pending"):
            repository.delete_execution_for_privacy(
                launch.authorization.execution_id
            )
        with database._connection(readonly=True) as connection:
            tombstone = connection.execute(
                """
                SELECT retained_plan_fingerprint
                FROM estimator_runtime_deletion_tombstones
                """
            ).fetchone()
            assert tombstone["retained_plan_fingerprint"] == registration.plan_fingerprint
            assert connection.execute("PRAGMA secure_delete").fetchone()[0] == 1
            assert connection.execute(
                "SELECT 1 FROM estimator_runtime_executions WHERE execution_id=?",
                (launch.authorization.execution_id,),
            ).fetchone() is None
    finally:
        reader.rollback()
        reader.close()
    outcome = repository.delete_execution_for_privacy(
        launch.authorization.execution_id
    )
    assert outcome.execution_deleted is True
    assert outcome.plan_retained is True
    assert outcome.durable_revocation_retained is True
    assert repository.get_by_execution(launch.authorization.execution_id) is None
    assert (
        database.estimator_repository().get_plan(registration.plan_fingerprint)
        == registration.plan
    )

    forbidden_bytes = (
        launch.authorization.execution_id.encode("ascii"),
        launch.packet_receipts[0].packet_fingerprint.encode("ascii"),
        launch.packet_receipts[0].opaque_evidence_refs[0].encode("ascii"),
    )
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{database.path}{suffix}")
        if path.exists():
            payload = path.read_bytes()
            assert all(item not in payload for item in forbidden_bytes)


def test_schema_has_no_runtime_payload_surface_and_queue_kind_is_closed(tmp_path) -> None:
    database, *_ = _setup(tmp_path)
    with database._connection(readonly=True) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        queue_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='analysis_jobs'"
        ).fetchone()[0]
        assert "estimator_execution" in queue_sql
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'estimator_runtime_%'"
            )
        }
        assert "estimator_runtime_authorizations" in tables
        assert "estimator_runtime_retrievals" in tables
        assert "estimator_runtime_metric_observations" in tables
        assert not any(
            forbidden == row[1].lower()
            for table in tables
            for row in connection.execute(f"PRAGMA table_info({table})")
            for forbidden in (
                "prompt",
                "excerpt",
                "response_text",
                "commentary",
                "embedding",
                "payload",
                "json",
                "blob",
                "filesystem_path",
                "uri",
            )
        )


def test_v17_to_v18_preserves_existing_queue_and_seals_migration_ledger(
    tmp_path,
) -> None:
    path = tmp_path / "legacy-v17.sqlite3"
    applied_at = MutableClock().value.isoformat(timespec="microseconds")
    scripts = (_MIGRATION_1,) + tuple(
        getattr(migrations, f"MIGRATION_{version}") for version in range(2, 18)
    )
    installation_id = digest("migration-installation")
    project_id = digest("migration-project")
    session_id = digest("migration-session")
    job_id = digest("migration-job")
    dedupe_key = digest("migration-dedupe")
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        for version, script in enumerate(scripts, start=1):
            connection.executescript(script)
            connection.execute(
                "INSERT INTO schema_migrations VALUES (?,?,?)",
                (
                    version,
                    hashlib.sha256(script.encode("utf-8")).hexdigest(),
                    applied_at,
                ),
            )
            connection.execute(f"PRAGMA user_version={version}")
            connection.commit()
        connection.execute(
            "INSERT INTO installations VALUES (?,?,?)",
            (installation_id, "synthetic", applied_at),
        )
        connection.execute(
            "INSERT INTO projects(project_id,installation_id,provider,created_at) VALUES (?,?,?,?)",
            (project_id, installation_id, "synthetic", applied_at),
        )
        connection.execute(
            """
            INSERT INTO sessions(
                session_id,installation_id,project_id,provider,provider_version,
                adapter_version,source_schema_version,started_at,ended_at,
                terminal_state,events_complete,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                session_id,
                installation_id,
                project_id,
                "synthetic",
                "synthetic-provider-v1",
                "synthetic-adapter-v1",
                "synthetic-schema-v1",
                applied_at,
                applied_at,
                "completed",
                1,
                applied_at,
                applied_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO analysis_jobs VALUES (
                ?,?,'session_quality','synthetic',?,?,?,?,'synthetic-plan-v1',
                'synthetic-redactor-v1','synthetic-schema-v1',NULL,1,'queued',
                NULL,0,1,0,3,?,0,NULL,NULL,NULL,NULL,NULL,?,?,NULL
            )
            """,
            (
                job_id,
                dedupe_key,
                project_id,
                session_id,
                digest("migration-input"),
                digest("migration-provenance"),
                applied_at,
                applied_at,
                applied_at,
            ),
        )
        connection.execute(
            "INSERT INTO analysis_job_metrics VALUES (?,?,0)",
            (job_id, "prompt.goal_cue_coverage"),
        )
        connection.commit()

    Database(path).initialize()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        rows = connection.execute(
            "SELECT version,checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert [row[0] for row in rows] == list(range(1, 62))
        assert rows[17][1] == hashlib.sha256(
            migrations.MIGRATION_18.encode("utf-8")
        ).hexdigest()
        assert connection.execute(
            "SELECT kind,state FROM analysis_jobs WHERE job_id=?", (job_id,)
        ).fetchone() == ("session_quality", "queued")
        assert connection.execute(
            "SELECT metric_key FROM analysis_job_metrics WHERE job_id=?", (job_id,)
        ).fetchone()[0] == "prompt.goal_cue_coverage"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
