from __future__ import annotations

from datetime import timedelta
import hashlib
import sqlite3

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.estimators import (
    CompletedSyntheticEstimatorBundle,
    EstimateUncertainty,
    EstimatorExecution,
    EstimatorExecutionState,
    EstimatorStageReceipt,
    EstimatorStageReceiptState,
    EvidencePacketReceipt,
    MetricEstimate,
    MetricEstimateSource,
    MetricEstimateState,
    ModelRunState,
    ModelVote,
    PrivacyDeleteOutcome,
    SyntheticEstimatorCase,
    UncertaintyKind,
)
from prompt_enhancer.application.estimators.contracts import STAGE_ORDER
from prompt_enhancer.database import (
    SCHEMA_VERSION,
    Database,
    DatabaseInvariantError,
    _apply_migration_atomically,
    _migration_body,
    _MIGRATION_1,
)
from prompt_enhancer.domain import Provider
from prompt_enhancer.infrastructure.sqlite import migrations
from prompt_enhancer.infrastructure.sqlite.estimators import SqliteEstimatorRepository

from test_estimator_contracts import NOW, digest, model_run, synthetic_plan


def _bundle(*, sensitive_canary: str = "synthetic private phrase"):
    plan = synthetic_plan()
    question = plan.question_specs[0]
    plan_fingerprint = plan.canonical_fingerprint
    references = tuple(sorted((digest("evidence-a"), digest("evidence-b"))))
    packet = EvidencePacketReceipt(
        packet_schema_version=plan.evidence_packet_schema_version,
        packet_sha256=digest(sensitive_canary),
        requirements_sha256=digest("requirements"),
        chronology_sha256=digest("chronology"),
        retrieval_index_sha256=digest("retrieval-index"),
        provider=Provider.SYNTHETIC,
        adapter_version=plan.provider_schemas[0].adapter_version,
        provider_schema_version=plan.provider_schemas[0].provider_schema_version,
        preprocessing_version=plan.preprocessing_version,
        preprocessing_sha256=plan.preprocessing_sha256,
        redactor_version=plan.redactor_version,
        redactor_sha256=plan.redactor_sha256,
        source_record_count=8,
        requirement_count=2,
        action_count=2,
        decision_count=1,
        feedback_count=1,
        verification_count=2,
        opaque_evidence_refs=references,
        created_at=NOW,
    )
    packet_fingerprint = packet.canonical_fingerprint
    execution_id = digest("persistence-execution")
    test_case = SyntheticEstimatorCase(
        case_id=digest("persistence-case"),
        case_schema_version="synthetic-case-1",
        plan_fingerprint=plan_fingerprint,
        evidence_packet_fingerprint=packet_fingerprint,
        created_at=NOW,
    )
    receipt_start = NOW + timedelta(seconds=1)
    receipts = tuple(
        EstimatorStageReceipt(
            ordinal=ordinal,
            kind=kind,
            state=(
                EstimatorStageReceiptState.SKIPPED
                if ordinal == 7
                else EstimatorStageReceiptState.COMPLETED
            ),
            outcome_code=("not_needed" if ordinal == 7 else "stage_complete"),
            started_at=(
                None
                if ordinal == 7
                else receipt_start + timedelta(milliseconds=20 * ordinal)
            ),
            finished_at=(
                None
                if ordinal == 7
                else receipt_start + timedelta(milliseconds=20 * ordinal + 10)
            ),
        )
        for ordinal, kind in enumerate(STAGE_ORDER, start=1)
    )
    execution = EstimatorExecution(
        execution_id=execution_id,
        plan_fingerprint=plan_fingerprint,
        evidence_packet_fingerprint=packet_fingerprint,
        route=plan.route,
        state=EstimatorExecutionState.COMPLETED,
        created_at=NOW,
        started_at=NOW + timedelta(milliseconds=500),
        finished_at=receipt_start + timedelta(milliseconds=150),
        stage_receipts=receipts,
        cascade_stop_stage_ordinal=7,
        cascade_stop_stage_kind=STAGE_ORDER[-1],
        cascade_stop_reason_code="cascade_complete",
    )
    runs = tuple(
        model_run(
            model=stage.model_artifact,
            run_id=digest(f"persistence-run-{stage.ordinal}"),
            execution_id=execution_id,
            plan_fingerprint=plan_fingerprint,
            evidence_packet_fingerprint=packet_fingerprint,
            route=plan.route,
            stage_ordinal=stage.ordinal,
            stage_kind=stage.kind,
            started_at=receipt_start
            + timedelta(milliseconds=20 * stage.ordinal + 1),
            finished_at=receipt_start
            + timedelta(milliseconds=20 * stage.ordinal + 9),
            latency_ms=8,
            response_schema_version=stage.output_schema_version,
        )
        for stage in plan.stages
        if stage.model_artifact is not None
    )
    votes = tuple(
        sorted(
            (
                ModelVote(
                    vote_id=digest(f"persistence-vote-{index}"),
                    execution_id=execution_id,
                    model_run_id=run.run_id,
                    plan_fingerprint=plan_fingerprint,
                    evidence_packet_fingerprint=packet_fingerprint,
                    metric_question_fingerprint=question.canonical_fingerprint,
                    metric_key=question.metric_key,
                    state=MetricEstimateState.KNOWN,
                    value_kind=question.value_kind,
                    numeric_value=0.5,
                    confidence=0.8,
                    opaque_evidence_refs=references,
                )
                for index, run in enumerate(runs[-2:], start=1)
            ),
            key=lambda vote: vote.vote_id,
        )
    )
    estimate = MetricEstimate(
        estimate_id=digest("persistence-estimate"),
        execution_id=execution_id,
        plan_fingerprint=plan_fingerprint,
        evidence_packet_fingerprint=packet_fingerprint,
        metric_question_fingerprint=question.canonical_fingerprint,
        metric_key=question.metric_key,
        source=MetricEstimateSource.MODEL_CASCADE,
        state=MetricEstimateState.KNOWN,
        value_kind=question.value_kind,
        unit_code=question.unit_code,
        numeric_value=0.5,
        numerator=1,
        denominator=2,
        uncertainty=EstimateUncertainty(
            kind=UncertaintyKind.CONFIDENCE,
            confidence=0.8,
        ),
        evidence_coverage=0.75,
        vote_ids=tuple(vote.vote_id for vote in votes),
        created_at=receipt_start + timedelta(milliseconds=150),
    )
    return CompletedSyntheticEstimatorBundle(
        test_case=test_case,
        plan=plan,
        evidence_packet=packet,
        execution=execution,
        model_runs=runs,
        model_votes=votes,
        metric_estimates=(estimate,),
    )


def _create_v14_database(path) -> None:
    scripts = (_MIGRATION_1,) + tuple(
        getattr(migrations, f"MIGRATION_{version}") for version in range(2, 15)
    )
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        for version, script in enumerate(scripts, start=1):
            connection.executescript(script)
            connection.execute(
                """
                INSERT INTO schema_migrations(version, checksum, applied_at)
                VALUES (?, ?, ?)
                """,
                (
                    version,
                    hashlib.sha256(script.encode("utf-8")).hexdigest(),
                    NOW.isoformat(),
                ),
            )
            connection.execute(f"PRAGMA user_version = {version}")
            connection.commit()


def test_migration_1_to_15_and_database_factory_are_content_free(tmp_path) -> None:
    database = Database(tmp_path / "from-empty.sqlite3")
    repository = database.estimator_repository()

    assert repository.model_lab_summary(digest("unregistered-plan")).registered is False
    assert database.summary()["schema_version"] == SCHEMA_VERSION == 61

    with sqlite3.connect(database.path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name LIKE 'estimator_%'
                """
            )
        }
    assert "estimator_plans" in tables
    assert "estimator_executions" in tables
    assert "estimator_metric_estimates" in tables


def test_migration_14_to_15_adds_empty_tables_without_inference(tmp_path) -> None:
    path = tmp_path / "legacy-v14.sqlite3"
    assert hashlib.sha256(migrations.MIGRATION_14.encode("utf-8")).hexdigest() == (
        "74a984df1356e4f7397de268a1cf8cf4b7adba64b730fb5feb64406116aefdf4"
    )
    _create_v14_database(path)

    Database(path).initialize()

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_plans"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_executions"
        ).fetchone()[0] == 0


def test_migration_schema_ledger_and_user_version_roll_back_together(tmp_path) -> None:
    path = tmp_path / "atomic-migration.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        connection.commit()
        script = "CREATE TABLE crash_window_canary(value INTEGER); SELECT missing_function();"
        with pytest.raises(sqlite3.OperationalError):
            _apply_migration_atomically(
                connection,
                version=15,
                script=script,
                checksum=hashlib.sha256(script.encode("utf-8")).hexdigest(),
                applied_at=NOW.isoformat(timespec="microseconds"),
            )

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()[0] == 0
        assert connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'crash_window_canary'
            """
        ).fetchone() is None


def test_migration_runner_rejects_nested_transactions_and_commits_ledger(tmp_path) -> None:
    with pytest.raises(DatabaseInvariantError, match="nested transaction"):
        _migration_body(
            "BEGIN IMMEDIATE;\nCREATE TABLE one(value INTEGER);\nBEGIN;\nCOMMIT;\nCOMMIT;"
        )

    path = tmp_path / "atomic-success.sqlite3"
    script = "BEGIN IMMEDIATE;\nCREATE TABLE atomic_success(value INTEGER);\nCOMMIT;"
    checksum = hashlib.sha256(script.encode("utf-8")).hexdigest()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        connection.commit()
        _apply_migration_atomically(
            connection,
            version=15,
            script=script,
            checksum=checksum,
            applied_at=NOW.isoformat(timespec="microseconds"),
        )
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 15
        assert connection.execute(
            "SELECT checksum FROM schema_migrations WHERE version = 15"
        ).fetchone()[0] == checksum


def test_exact_plan_registration_bundle_restart_and_fail_closed_summary(tmp_path) -> None:
    path = tmp_path / "estimator.sqlite3"
    bundle = _bundle()
    database = Database(path)
    repository = database.estimator_repository()

    fingerprint = repository.register_plan(bundle.plan)
    assert fingerprint == bundle.plan.canonical_fingerprint
    assert repository.register_plan(bundle.plan) == fingerprint
    assert repository.get_plan(fingerprint) == bundle.plan
    repository.save_completed_synthetic_bundle(bundle)

    restarted = Database(path).estimator_repository()
    assert restarted.get_plan(fingerprint) == bundle.plan
    assert restarted.get_completed_bundle(bundle.execution.execution_id) == bundle
    summary = restarted.attempt_activation(fingerprint)
    assert summary.synthetic_execution_count == 1
    assert summary.metric_estimate_count == 1
    assert summary.activation_outcome == "synthetic_or_insufficient"
    assert summary.activation_allowed is False


def test_truthful_early_stop_persists_and_hydrates_exactly(tmp_path) -> None:
    original = _bundle()
    early_execution = original.execution.model_copy(
        update={
            "stage_receipts": original.execution.stage_receipts[:2],
            "cascade_stop_stage_ordinal": 2,
            "cascade_stop_stage_kind": STAGE_ORDER[1],
            "cascade_stop_reason_code": "deterministic_evidence_sufficient",
            "finished_at": original.execution.stage_receipts[1].finished_at,
        }
    )
    early_estimate = original.metric_estimates[0].model_copy(
        update={
            "source": MetricEstimateSource.DETERMINISTIC,
            "vote_ids": (),
            "created_at": original.execution.stage_receipts[1].finished_at,
        }
    )
    early = CompletedSyntheticEstimatorBundle(
        test_case=original.test_case,
        plan=original.plan,
        evidence_packet=original.evidence_packet,
        execution=early_execution,
        model_runs=(),
        model_votes=(),
        metric_estimates=(early_estimate,),
    )
    path = tmp_path / "early-stop.sqlite3"
    repository = Database(path).estimator_repository()
    repository.register_plan(early.plan)
    repository.save_completed_synthetic_bundle(early)

    assert Database(path).estimator_repository().get_completed_bundle(
        early.execution.execution_id
    ) == early


def test_non_prefix_receipts_and_run_beyond_stop_are_rejected() -> None:
    bundle = _bundle()
    with pytest.raises(ValidationError, match="ordered contiguous cascade prefix"):
        EstimatorExecution(
            **{
                **bundle.execution.model_dump(),
                "stage_receipts": (
                    bundle.execution.stage_receipts[0],
                    bundle.execution.stage_receipts[2],
                ),
            }
        )

    early_execution = bundle.execution.model_copy(
        update={
            "stage_receipts": bundle.execution.stage_receipts[:2],
            "cascade_stop_stage_ordinal": 2,
            "cascade_stop_stage_kind": STAGE_ORDER[1],
            "cascade_stop_reason_code": "deterministic_evidence_sufficient",
            "finished_at": bundle.execution.stage_receipts[1].finished_at,
        }
    )
    early_estimate = bundle.metric_estimates[0].model_copy(
        update={
            "source": MetricEstimateSource.DETERMINISTIC,
            "vote_ids": (),
            "created_at": bundle.execution.stage_receipts[1].finished_at,
        }
    )
    with pytest.raises(ValidationError, match="reached stage"):
        CompletedSyntheticEstimatorBundle(
            test_case=bundle.test_case,
            plan=bundle.plan,
            evidence_packet=bundle.evidence_packet,
            execution=early_execution,
            model_runs=(bundle.model_runs[-1],),
            model_votes=(),
            metric_estimates=(early_estimate,),
        )


def test_bundle_rejects_unproven_model_and_human_claims() -> None:
    bundle = _bundle()
    failed_run = bundle.model_runs[-1].model_copy(
        update={
            "state": "failed",
            "structured_output_valid": False,
            "failure_code": "execution_failed",
        }
    )
    failed_run_vote = bundle.model_votes[-1].model_copy(
        update={"model_run_id": failed_run.run_id}
    )
    with pytest.raises(ValidationError, match="completed model stages require"):
        CompletedSyntheticEstimatorBundle(
            test_case=bundle.test_case,
            plan=bundle.plan,
            evidence_packet=bundle.evidence_packet,
            execution=bundle.execution,
            model_runs=(*bundle.model_runs[:-1], failed_run),
            model_votes=(*bundle.model_votes[:-1], failed_run_vote),
            metric_estimates=bundle.metric_estimates,
        )

    unknown_vote = bundle.model_votes[0].model_copy(
        update={
            "state": MetricEstimateState.UNKNOWN,
            "numeric_value": None,
            "confidence": None,
            "unknown_reason_code": "insufficient_evidence",
            "opaque_evidence_refs": (),
        }
    )
    unsupported_estimate = bundle.metric_estimates[0].model_copy(
        update={
            "state": MetricEstimateState.ABSTAINED,
            "numeric_value": None,
            "numerator": None,
            "denominator": None,
            "uncertainty": None,
            "abstention_reason_code": "unsupported_router_result",
        }
    )
    with pytest.raises(ValidationError, match="supporting its final state"):
        CompletedSyntheticEstimatorBundle(
            test_case=bundle.test_case,
            plan=bundle.plan,
            evidence_packet=bundle.evidence_packet,
            execution=bundle.execution,
            model_runs=bundle.model_runs,
            model_votes=tuple(
                unknown_vote if vote.vote_id == unknown_vote.vote_id else vote
                for vote in bundle.model_votes
            ),
            metric_estimates=(unsupported_estimate,),
        )

    human_estimate = MetricEstimate(
        **{
            **bundle.metric_estimates[0].model_dump(),
            "source": MetricEstimateSource.HUMAN_ADJUDICATED,
            "vote_ids": (),
            "adjudication_id": digest("unpersisted-adjudication"),
            "created_at": bundle.execution.stage_receipts[1].finished_at,
        }
    )
    early_execution = bundle.execution.model_copy(
        update={
            "stage_receipts": bundle.execution.stage_receipts[:2],
            "cascade_stop_stage_ordinal": 2,
            "cascade_stop_stage_kind": STAGE_ORDER[1],
            "cascade_stop_reason_code": "deterministic_evidence_sufficient",
            "finished_at": bundle.execution.stage_receipts[1].finished_at,
        }
    )
    with pytest.raises(ValidationError, match="outside this repository slice"):
        CompletedSyntheticEstimatorBundle(
            test_case=bundle.test_case,
            plan=bundle.plan,
            evidence_packet=bundle.evidence_packet,
            execution=early_execution,
            model_runs=(),
            model_votes=(),
            metric_estimates=(human_estimate,),
        )


def test_bundle_rejects_schema_latency_time_and_skipped_always_stage() -> None:
    bundle = _bundle()
    with pytest.raises(ValidationError, match="model run lineage"):
        CompletedSyntheticEstimatorBundle(
            **{
                **bundle.model_dump(),
                "model_runs": (
                    bundle.model_runs[0].model_copy(
                        update={"response_schema_version": "forged-v999"}
                    ),
                    *bundle.model_runs[1:],
                ),
            }
        )
    with pytest.raises(ValidationError, match="model run lineage"):
        CompletedSyntheticEstimatorBundle(
            **{
                **bundle.model_dump(),
                "model_runs": (
                    bundle.model_runs[0].model_copy(update={"latency_ms": 0}),
                    *bundle.model_runs[1:],
                ),
            }
        )
    with pytest.raises(ValidationError, match="predates a selected model run"):
        CompletedSyntheticEstimatorBundle(
            **{
                **bundle.model_dump(),
                "metric_estimates": (
                    bundle.metric_estimates[0].model_copy(
                        update={"created_at": bundle.execution.started_at}
                    ),
                ),
            }
        )

    skipped = bundle.execution.stage_receipts[2].model_copy(
        update={
            "state": EstimatorStageReceiptState.SKIPPED,
            "outcome_code": "not_needed",
            "started_at": None,
            "finished_at": None,
        }
    )
    execution = bundle.execution.model_copy(
        update={
            "stage_receipts": (
                *bundle.execution.stage_receipts[:2],
                skipped,
                *bundle.execution.stage_receipts[3:],
            )
        }
    )
    with pytest.raises(ValidationError, match="always-run"):
        CompletedSyntheticEstimatorBundle(
            **{
                **bundle.model_dump(),
                "execution": execution,
                "model_runs": bundle.model_runs[1:],
            }
        )


def test_mixed_committee_and_failed_or_refused_attempts_round_trip(tmp_path) -> None:
    original = _bundle()
    abstained_vote = original.model_votes[-1].model_copy(
        update={
            "state": MetricEstimateState.ABSTAINED,
            "numeric_value": None,
            "confidence": None,
            "opaque_evidence_refs": (),
            "abstention_reason_code": "low_confidence",
        }
    )
    abstained_estimate = original.metric_estimates[0].model_copy(
        update={
            "state": MetricEstimateState.ABSTAINED,
            "numeric_value": None,
            "numerator": None,
            "denominator": None,
            "uncertainty": None,
            "abstention_reason_code": "committee_abstained",
        }
    )
    mixed = CompletedSyntheticEstimatorBundle(
        **{
            **original.model_dump(),
            "model_votes": (*original.model_votes[:-1], abstained_vote),
            "metric_estimates": (abstained_estimate,),
        }
    )
    repository = Database(tmp_path / "mixed-state.sqlite3").estimator_repository()
    repository.register_plan(mixed.plan)
    repository.save_completed_synthetic_bundle(mixed)
    assert repository.get_completed_bundle(mixed.execution.execution_id) == mixed

    failed_run = original.model_runs[-1].model_copy(
        update={
            "state": ModelRunState.OUT_OF_MEMORY,
            "structured_output_valid": False,
            "failure_code": "out_of_memory",
        }
    )
    target_vote = next(
        vote for vote in original.model_votes if vote.model_run_id == failed_run.run_id
    )
    failed_vote = target_vote.model_copy(
        update={
            "model_run_id": failed_run.run_id,
            "state": MetricEstimateState.FAILED,
            "numeric_value": None,
            "confidence": None,
            "opaque_evidence_refs": (),
            "failure_code": "out_of_memory",
        }
    )
    failed_receipt = original.execution.stage_receipts[5].model_copy(
        update={"state": EstimatorStageReceiptState.FAILED, "outcome_code": "out_of_memory"}
    )
    failed_execution = original.execution.model_copy(
        update={
            "stage_receipts": (
                *original.execution.stage_receipts[:5],
                failed_receipt,
                original.execution.stage_receipts[6],
            )
        }
    )
    failed_estimate = original.metric_estimates[0].model_copy(
        update={
            "state": MetricEstimateState.FAILED,
            "numeric_value": None,
            "numerator": None,
            "denominator": None,
            "uncertainty": None,
            "failure_code": "out_of_memory",
        }
    )
    failed = CompletedSyntheticEstimatorBundle(
        **{
            **original.model_dump(),
            "execution": failed_execution,
            "model_runs": (*original.model_runs[:-1], failed_run),
            "model_votes": tuple(
                sorted(
                    (
                        failed_vote if vote.vote_id == target_vote.vote_id else vote
                        for vote in original.model_votes
                    ),
                    key=lambda vote: (vote.metric_key, vote.vote_id),
                )
            ),
            "metric_estimates": (failed_estimate,),
        }
    )
    failed_repository = Database(tmp_path / "failed-state.sqlite3").estimator_repository()
    failed_repository.register_plan(failed.plan)
    failed_repository.save_completed_synthetic_bundle(failed)
    assert failed_repository.get_completed_bundle(failed.execution.execution_id) == failed

    refused_run = original.model_runs[-1].model_copy(
        update={
            "state": ModelRunState.REFUSED,
            "structured_output_valid": False,
            "refusal_code": "provider_refusal",
        }
    )
    refused_vote = target_vote.model_copy(
        update={
            "model_run_id": refused_run.run_id,
            "state": MetricEstimateState.ABSTAINED,
            "numeric_value": None,
            "confidence": None,
            "opaque_evidence_refs": (),
            "abstention_reason_code": "provider_refusal",
        }
    )
    refused_estimate = abstained_estimate.model_copy(
        update={"abstention_reason_code": "provider_refusal"}
    )
    refused_execution = failed_execution.model_copy(
        update={
            "stage_receipts": (
                *failed_execution.stage_receipts[:5],
                failed_receipt.model_copy(update={"outcome_code": "provider_refusal"}),
                failed_execution.stage_receipts[6],
            )
        }
    )
    refused = CompletedSyntheticEstimatorBundle(
        **{
            **original.model_dump(),
            "execution": refused_execution,
            "model_runs": (*original.model_runs[:-1], refused_run),
            "model_votes": tuple(
                sorted(
                    (
                        refused_vote if vote.vote_id == target_vote.vote_id else vote
                        for vote in original.model_votes
                    ),
                    key=lambda vote: (vote.metric_key, vote.vote_id),
                )
            ),
            "metric_estimates": (refused_estimate,),
        }
    )
    refused_repository = Database(tmp_path / "refused-state.sqlite3").estimator_repository()
    refused_repository.register_plan(refused.plan)
    refused_repository.save_completed_synthetic_bundle(refused)
    assert refused_repository.get_completed_bundle(refused.execution.execution_id) == refused

def test_zero_measured_units_round_trip_without_becoming_unknown(tmp_path) -> None:
    original = _bundle()
    zero_run = original.model_runs[0].model_copy(
        update={
            "throughput_unit_code": "records",
            "measured_unit_count": 0,
            "throughput_window_ms": 8,
            "throughput_provenance_version": "throughput-1",
        }
    )
    bundle = CompletedSyntheticEstimatorBundle(
        test_case=original.test_case,
        plan=original.plan,
        evidence_packet=original.evidence_packet,
        execution=original.execution,
        model_runs=(zero_run, *original.model_runs[1:]),
        model_votes=original.model_votes,
        metric_estimates=original.metric_estimates,
    )
    repository = Database(tmp_path / "zero-throughput.sqlite3").estimator_repository()
    repository.register_plan(bundle.plan)
    repository.save_completed_synthetic_bundle(bundle)

    hydrated = repository.get_completed_bundle(bundle.execution.execution_id)
    assert hydrated == bundle
    assert hydrated.model_runs[0].measured_unit_count == 0


def test_same_plan_key_and_version_cannot_drift(tmp_path) -> None:
    repository = Database(tmp_path / "conflict.sqlite3").estimator_repository()
    original = synthetic_plan()
    drifted = synthetic_plan(calibration_sha256=digest("drifted-calibration"))
    assert drifted.canonical_fingerprint != original.canonical_fingerprint
    assert (drifted.plan_key, drifted.plan_version) == (
        original.plan_key,
        original.plan_version,
    )
    repository.register_plan(original)

    with pytest.raises(DatabaseInvariantError, match="key and version"):
        repository.register_plan(drifted)


def test_plan_registration_clock_is_injected_and_idempotence_preserves_it(
    tmp_path,
) -> None:
    database = Database(tmp_path / "registration-clock.sqlite3")
    database.initialize()
    plan = synthetic_plan()
    repository = SqliteEstimatorRepository(
        database._connection,
        database._ensure_initialized,
        clock=lambda: NOW,
    )
    repository.register_plan(plan)
    later_repository = SqliteEstimatorRepository(
        database._connection,
        database._ensure_initialized,
        clock=lambda: NOW + timedelta(days=1),
    )
    later_repository.register_plan(plan)

    with sqlite3.connect(database.path) as connection:
        registered_at = connection.execute(
            """
            SELECT registered_at FROM estimator_plans
            WHERE plan_fingerprint = ?
            """,
            (plan.canonical_fingerprint,),
        ).fetchone()[0]
    assert registered_at == NOW.isoformat(timespec="microseconds")


def test_schema_privacy_allowlist_has_no_payload_or_account_columns(tmp_path) -> None:
    database = Database(tmp_path / "privacy.sqlite3")
    database.initialize()
    permitted_provenance = {
        "prompt_template_id",
        "prompt_template_version",
        "prompt_template_sha256",
        "response_schema_version",
    }
    forbidden_fragments = {
        "prompt",
        "response",
        "body",
        "content",
        "rationale",
        "commentary",
        "excerpt",
        "path",
        "username",
        "adjudicator",
        "account",
    }

    with sqlite3.connect(database.path) as connection:
        table_names = tuple(
            row[0]
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type = 'table' AND name LIKE 'estimator_%'
                ORDER BY name
                """
            )
        )
        columns = tuple(
            (table, row[1], row[2].upper())
            for table in table_names
            for row in connection.execute(f"PRAGMA table_info({table})")
        )
    assert table_names
    assert all(column_type in {"TEXT", "INTEGER", "REAL"} for _, _, column_type in columns)
    assert not any(
        fragment in column
        for _, column, _ in columns
        if column not in permitted_provenance
        for fragment in forbidden_fragments
    )


def test_direct_sql_rejects_canaries_in_version_code_and_timestamp_fields(
    tmp_path,
) -> None:
    bundle = _bundle()
    database = Database(tmp_path / "metadata-canaries.sqlite3")
    repository = database.estimator_repository()
    repository.register_plan(bundle.plan)
    repository.save_completed_synthetic_bundle(bundle)

    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError, match="content-free"):
            connection.execute(
                """
                INSERT INTO estimator_metric_questions
                SELECT ?, contract_version, metric_key, metric_definition_version,
                       question_id, question_version, question_sha256,
                       prompt_template_id, prompt_template_version,
                       prompt_template_sha256, rubric_id, rubric_version,
                       rubric_sha256, ?, value_kind, unit_code, direction,
                       lower_bound, upper_bound
                FROM estimator_metric_questions WHERE question_fingerprint = ?
                """,
                (
                    digest("unsafe-question-copy"),
                    "SYNTHETIC PRIVATE VERSION CANARY",
                    bundle.plan.question_specs[0].canonical_fingerprint,
                ),
            )
        source_artifact = bundle.plan.stages[2].model_artifact
        with pytest.raises(sqlite3.IntegrityError, match="children are inconsistent"):
            connection.execute(
                """
                INSERT INTO estimator_model_artifacts
                SELECT ?, contract_version, source, ?, served_model_id,
                       requested_revision, served_revision,
                       requested_execution_mode, served_execution_mode,
                       weight_availability, weight_file_count, tokenizer_id,
                       tokenizer_revision, tokenizer_availability,
                       tokenizer_file_count, license_id, trust_remote_code
                FROM estimator_model_artifacts WHERE artifact_fingerprint = ?
                """,
                (
                    digest("unsafe-path-artifact-copy"),
                    "C:/Users/Example/private-model",
                    source_artifact.canonical_fingerprint,
                ),
            )
        with pytest.raises(sqlite3.IntegrityError, match="children are inconsistent"):
            connection.execute(
                """
                INSERT INTO estimator_model_artifacts
                SELECT ?, ?, source, requested_model_id, served_model_id,
                       requested_revision, served_revision,
                       requested_execution_mode, served_execution_mode,
                       weight_availability, weight_file_count, tokenizer_id,
                       tokenizer_revision, tokenizer_availability,
                       tokenizer_file_count, license_id, trust_remote_code
                FROM estimator_model_artifacts WHERE artifact_fingerprint = ?
                """,
                (
                    digest("unsafe-contract-artifact-copy"),
                    "C:/Users/Example/private",
                    source_artifact.canonical_fingerprint,
                ),
            )
        with pytest.raises(sqlite3.IntegrityError, match="content-free"):
            connection.execute(
                """
                INSERT INTO estimator_stage_receipts(
                    execution_id, ordinal, kind, state, outcome_code,
                    started_at, finished_at
                ) VALUES (?, 1, 'objective_evidence', 'completed',
                          'stage_complete', ?, ?)
                """,
                (
                    digest("future-impossible-timestamp-execution"),
                    "2099-99-99T99:99:99.999999+00:00",
                    "2099-99-99T99:99:99.999999+00:00",
                ),
            )


def test_direct_sql_rejects_model_run_shape_and_response_schema(tmp_path) -> None:
    bundle = _bundle()
    database = Database(tmp_path / "run-shape.sqlite3")
    repository = database.estimator_repository()
    repository.register_plan(bundle.plan)
    repository.save_completed_synthetic_bundle(bundle)

    with sqlite3.connect(database.path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        row = dict(
            connection.execute(
                "SELECT * FROM estimator_model_runs WHERE run_id = ?",
                (bundle.model_runs[0].run_id,),
            ).fetchone()
        )
        columns = tuple(row)
        placeholders = ", ".join("?" for _ in columns)
        insert = (
            f"INSERT INTO estimator_model_runs({', '.join(columns)}) "
            f"VALUES ({placeholders})"
        )
        for label, changes in (
            (
                "unsafe-retention",
                {
                    "retention_class": "provider_30_day",
                    "retention_days": 30,
                },
            ),
            ("unsafe-response-schema", {"response_schema_version": "forged-v999"}),
        ):
            forged = {
                **row,
                "run_id": digest(label),
                "execution_id": digest(f"future-{label}"),
                **changes,
            }
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(insert, tuple(forged[column] for column in columns))
            connection.rollback()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO estimator_stage_receipts(
                    execution_id, ordinal, kind, state, outcome_code,
                    started_at, finished_at
                ) VALUES (?, 1, 'objective_evidence', 'skipped', ?, NULL, NULL)
                """,
                (
                    digest("future-invalid-outcome-execution"),
                    "SYNTHETIC PRIVATE OUTCOME CANARY",
                ),
            )
        with pytest.raises(sqlite3.IntegrityError, match="content-free"):
            connection.execute(
                """
                INSERT INTO estimator_stage_receipts(
                    execution_id, ordinal, kind, state, outcome_code,
                    started_at, finished_at
                ) VALUES (?, 1, 'objective_evidence', 'completed',
                          'stage_complete', ?, ?)
                """,
                (
                    digest("future-invalid-timestamp-execution"),
                    "SYNTHETIC PRIVATE TIMESTAMP CANARY",
                    NOW.isoformat(timespec="microseconds"),
                ),
            )


def test_canary_never_reaches_database_bytes_and_invalid_scope_is_rejected(
    tmp_path,
) -> None:
    canary = "SYNTHETIC-PRIVATE-PAYLOAD-CANARY-DO-NOT-STORE"
    bundle = _bundle(sensitive_canary=canary)
    path = tmp_path / "canary.sqlite3"
    repository = Database(path).estimator_repository()
    repository.register_plan(bundle.plan)
    repository.save_completed_synthetic_bundle(bundle)

    assert canary.encode("utf-8") not in path.read_bytes()

    bad_vote = bundle.model_votes[0].model_copy(
        update={"opaque_evidence_refs": (digest("outside-packet"),)}
    )
    with pytest.raises(ValidationError, match="outside its packet"):
        CompletedSyntheticEstimatorBundle(
            **{
                **bundle.model_dump(),
                "model_votes": (bad_vote, *bundle.model_votes[1:]),
            }
        )


def test_raw_probability_validation_and_snapshot_sealing(tmp_path) -> None:
    bundle = _bundle()
    database = Database(tmp_path / "sealed.sqlite3")
    repository = database.estimator_repository()
    repository.register_plan(bundle.plan)
    repository.save_completed_synthetic_bundle(bundle)

    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE estimator_plans SET route = 'fast' WHERE plan_fingerprint = ?",
                (bundle.plan.canonical_fingerprint,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="parent privacy deletion"):
            connection.execute(
                "DELETE FROM estimator_model_votes WHERE vote_id = ?",
                (bundle.model_votes[0].vote_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="already sealed"):
            connection.execute(
                """
                INSERT INTO estimator_stage_receipts(
                    execution_id, ordinal, kind, state, outcome_code,
                    started_at, finished_at
                ) VALUES (?, 7, 'human_adjudication', 'skipped', 'late_append', NULL, NULL)
                """,
                (bundle.execution.execution_id,),
            )

        invalid_vote_id = digest("invalid-probability-vote")
        connection.rollback()
        connection.execute("BEGIN")
        connection.executemany(
            """
            INSERT INTO estimator_vote_probabilities(
                vote_id, ordinal, label_code, probability
            ) VALUES (?, ?, ?, ?)
            """,
            (
                (invalid_vote_id, 0, "absent", 0.2),
                (invalid_vote_id, 1, "present", 0.2),
            ),
        )
        with pytest.raises(sqlite3.IntegrityError, match="children are inconsistent"):
            connection.execute(
                """
                INSERT INTO estimator_model_votes(
                    vote_id, execution_id, model_run_id, contract_version,
                    plan_fingerprint, evidence_packet_fingerprint,
                    metric_question_fingerprint, metric_key, state, value_kind,
                    numeric_value, label_code, confidence, unknown_reason_code,
                    abstention_reason_code, not_applicable_reason_code, failure_code,
                    probability_count, evidence_ref_count
                ) VALUES (?, ?, ?, 'model-vote-v1', ?, ?, ?, ?, 'known',
                          'categorical', NULL, 'present', 0.8, NULL, NULL, NULL,
                          NULL, 2, 0)
                """,
                (
                    invalid_vote_id,
                    digest("future-execution"),
                    digest("future-run"),
                    bundle.plan.canonical_fingerprint,
                    bundle.evidence_packet.canonical_fingerprint,
                    bundle.plan.question_specs[0].canonical_fingerprint,
                    bundle.plan.question_specs[0].metric_key,
                ),
            )
        connection.rollback()


def test_parent_privacy_delete_removes_bundle_and_updates_summary(tmp_path) -> None:
    bundle = _bundle()
    path = tmp_path / "privacy-delete.sqlite3"
    repository = Database(path).estimator_repository()
    plan_fingerprint = repository.register_plan(bundle.plan)
    repository.save_completed_synthetic_bundle(bundle)

    assert (
        repository.delete_synthetic_case_for_privacy(bundle.test_case.case_id)
        is PrivacyDeleteOutcome.DELETED_AND_PURGED
    )
    assert repository.get_completed_bundle(bundle.execution.execution_id) is None
    summary = repository.model_lab_summary(plan_fingerprint)
    assert summary.registered is True
    assert summary.synthetic_execution_count == 0
    assert summary.metric_estimate_count == 0

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_evidence_packets"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_model_runs"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_model_votes"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_metric_estimates"
        ).fetchone()[0] == 0


def test_privacy_delete_fails_closed_until_wal_is_durably_purged(tmp_path) -> None:
    bundle = _bundle(sensitive_canary="synthetic-wal-purge-canary")
    path = tmp_path / "privacy-wal.sqlite3"
    repository = Database(path).estimator_repository()
    repository.register_plan(bundle.plan)
    repository.save_completed_synthetic_bundle(bundle)
    unique_bytes = bundle.evidence_packet.packet_sha256.encode("ascii")

    reader = sqlite3.connect(path)
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT COUNT(*) FROM estimator_evidence_packets").fetchone()
        with pytest.raises(DatabaseInvariantError, match="WAL purge is pending"):
            repository.delete_synthetic_case_for_privacy(bundle.test_case.case_id)
    finally:
        reader.rollback()
        reader.close()

    assert (
        repository.delete_synthetic_case_for_privacy(bundle.test_case.case_id)
        is PrivacyDeleteOutcome.ALREADY_ABSENT_AND_PURGED
    )
    for candidate in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if candidate.exists():
            assert unique_bytes not in candidate.read_bytes()


def test_repeated_execution_of_identical_case_is_preserved_for_stability(tmp_path) -> None:
    first = _bundle()
    second_execution_id = digest("persistence-execution-repeat")
    run_id_map = {
        run.run_id: digest(f"repeat-run-{run.stage_ordinal}")
        for run in first.model_runs
    }
    second_execution = first.execution.model_copy(
        update={"execution_id": second_execution_id}
    )
    second_runs = tuple(
        run.model_copy(
            update={"run_id": run_id_map[run.run_id], "execution_id": second_execution_id}
        )
        for run in first.model_runs
    )
    second_votes = tuple(
        vote.model_copy(
            update={
                "vote_id": digest(f"repeat-vote-{index}"),
                "execution_id": second_execution_id,
                "model_run_id": run_id_map[vote.model_run_id],
            }
        )
        for index, vote in enumerate(first.model_votes, start=1)
    )
    second_estimate = first.metric_estimates[0].model_copy(
        update={
            "estimate_id": digest("repeat-estimate"),
            "execution_id": second_execution_id,
            "vote_ids": tuple(vote.vote_id for vote in second_votes),
        }
    )
    second = CompletedSyntheticEstimatorBundle(
        test_case=first.test_case,
        plan=first.plan,
        evidence_packet=first.evidence_packet,
        execution=second_execution,
        model_runs=second_runs,
        model_votes=second_votes,
        metric_estimates=(second_estimate,),
    )
    repository = Database(tmp_path / "repeated.sqlite3").estimator_repository()
    repository.register_plan(first.plan)
    repository.save_completed_synthetic_bundle(first)
    repository.save_completed_synthetic_bundle(first)
    repository.save_completed_synthetic_bundle(second)

    assert repository.get_completed_bundle(second_execution_id) == second
    assert repository.model_lab_summary(first.plan.canonical_fingerprint).synthetic_execution_count == 2
