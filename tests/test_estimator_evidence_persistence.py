from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import sqlite3

import pytest

from prompt_enhancer.application.estimators.contracts import (
    ExecutionDestination,
    MetricValueKind,
    RetentionClass,
)
from prompt_enhancer.application.estimators.evidence_contracts import (
    AttemptApprovalKind,
    AttemptLaunchReceiptV1,
    AttemptTerminalOutcomeV1,
    AttemptTerminalState,
    AuthoritativeCandidateProjectionV2,
    AuthoritativeDeterministicBaselineProjectionV1,
    BlindAdjudicationResolution,
    BlindHumanAdjudicationInputV1,
    BlindHumanJudgmentInputV1,
    CalibrationEvidenceSubmissionV1,
    CalibrationValueState,
    CostProvenanceV1,
    ExpectedAttemptManifestV2,
    HoldoutAccessAuditV1,
    HoldoutAccessEventV1,
    HoldoutAccessKind,
    HoldoutAccessManifestV1,
    HoldoutActorKind,
    HumanParticipantKind,
    MeasurementState,
    ObjectiveTruthKind,
    ObjectiveTruthProjectionV1,
    PrivacyFindingCategory,
    PrivacyFindingV1,
    PrivacyScanManifestV1,
    PrivacyScanReceiptV1,
    QueueProvenanceV1,
    ResourceUsageProvenanceV1,
    ServedIdentityState,
    ServedIdentityV1,
    StabilitySeriesManifestV1,
    StabilityTrialReceiptV1,
    StructuredEstimateReceiptV1,
    TokenUsageProvenanceV1,
)
from prompt_enhancer.application.estimators.gate_contracts import StabilityCondition
from prompt_enhancer.database import Database, DatabaseError, DatabaseInvariantError, SCHEMA_VERSION, _MIGRATION_1
from prompt_enhancer.infrastructure.sqlite import migrations

from test_estimator_campaign_persistence import BASE, _campaign, _id, _repository


class _SyntheticStructuredVerifier:
    def __init__(self, receipts: tuple[StructuredEstimateReceiptV1, ...]) -> None:
        self._by_attempt = {item.attempt_id: item for item in receipts}

    def verify_structured_estimate(self, *, launch, outcome):
        assert launch.attempt_id == outcome.attempt_id
        return self._by_attempt[launch.attempt_id]


def _submission(campaign=None) -> CalibrationEvidenceSubmissionV1:
    campaign = campaign or _campaign()
    plan = campaign.stored_plan
    stage = next(
        item
        for item in campaign.constellation_identity.stages
        if item.ordinal == 5
    )
    artifact = plan.stages[4].model_artifact
    assert artifact is not None
    question = plan.question_specs[0].canonical_fingerprint
    assignments = {
        item.case_id: item for item in campaign.assignment_manifest.assignments
    }
    started = BASE + timedelta(days=9)
    launches = []
    outcomes = []
    # Every sealed holdout case is executed; the first receives one additional
    # repeat trial with the exact same lineage.
    case_sequence = (*campaign.split.holdout_case_ids, campaign.split.holdout_case_ids[0])
    for index, case_id in enumerate(case_sequence):
        assignment = assignments[case_id]
        launched_at = started + timedelta(minutes=index)
        attempt_id = _id(f"evidence-attempt-{index}")
        execution_id = _id(f"evidence-execution-{index}")
        launch = AttemptLaunchReceiptV1(
            launch_id=_id(f"evidence-launch-{index}"),
            campaign_id=campaign.campaign_id,
            attempt_id=attempt_id,
            execution_id=execution_id,
            case_id=case_id,
            plan_fingerprint=plan.canonical_fingerprint,
            metric_question_fingerprint=question,
            evidence_packet_fingerprint=assignment.evidence_packet_fingerprint,
            constellation_stage_fingerprint=stage.stage_fingerprint,
            stage_ordinal=stage.ordinal,
            stage_kind=stage.kind,
            stage_configuration_sha256=stage.stage_configuration_sha256,
            model_artifact_fingerprint=stage.model_artifact_fingerprint,
            requested_source=artifact.source,
            requested_model_id=artifact.requested_model_id,
            requested_revision=artifact.requested_revision,
            requested_execution_mode=artifact.requested_execution_mode,
            runner_adapter_key="reserved-runner-v1",
            runner_adapter_version="reserved-runner-v1",
            runner_configuration_sha256=_id(f"runner-config-{index}"),
            response_schema_version=stage.output_schema_version,
            destination=ExecutionDestination.OPENAI_API,
            retention_class=RetentionClass.PROVIDER_ZERO_DAY,
            approval_kind=AttemptApprovalKind.FRESH_REDACTION_PREVIEW,
            approval_id=_id(f"approval-{index}"),
            redaction_preview_fingerprint=_id(f"preview-{index}"),
            approved_at=launched_at - timedelta(seconds=5),
            launched_at=launched_at,
        )
        launches.append(launch)
        outcome = AttemptTerminalOutcomeV1(
            outcome_id=_id(f"evidence-outcome-{index}"),
            campaign_id=campaign.campaign_id,
            attempt_id=attempt_id,
            execution_id=execution_id,
            case_id=case_id,
            plan_fingerprint=plan.canonical_fingerprint,
            metric_question_fingerprint=question,
            evidence_packet_fingerprint=assignment.evidence_packet_fingerprint,
            state=AttemptTerminalState.SUCCESS,
            served_identity=ServedIdentityV1(
                state=ServedIdentityState.OBSERVED,
                served_source=artifact.source,
                served_model_id=artifact.requested_model_id,
                served_revision=artifact.requested_revision,
                served_execution_mode=artifact.requested_execution_mode,
                fallback_used=False,
            ),
            structured_output_fingerprint=_id(f"structured-output-{index}"),
            usage=TokenUsageProvenanceV1(
                state=MeasurementState.OBSERVED,
                collector_version="reserved-usage-v1",
                input_tokens=10,
                cached_input_tokens=2,
                output_tokens=4,
                reasoning_output_tokens=1,
                total_tokens=14,
            ),
            resources=ResourceUsageProvenanceV1(
                state=MeasurementState.OBSERVED,
                collector_version="reserved-resource-v1",
                peak_ram_bytes=1024,
                peak_vram_bytes=2048,
                energy_millijoules=4.5,
            ),
            cost=CostProvenanceV1(
                state=MeasurementState.OBSERVED,
                collector_version="reserved-cost-v1",
                amount_microusd=25,
            ),
            queue=QueueProvenanceV1(
                queue_key="calibration",
                queue_version="reserved-queue-v1",
                worker_id=_id(f"worker-{index}"),
                enqueued_at=launched_at - timedelta(seconds=1),
                dequeued_at=launched_at,
                wait_ms=1000,
            ),
            started_at=launched_at,
            finished_at=launched_at + timedelta(seconds=2),
            latency_ms=2000,
        )
        outcomes.append(outcome)

    launches = tuple(sorted(launches, key=lambda item: item.attempt_id))
    outcomes = tuple(sorted(outcomes, key=lambda item: item.attempt_id))
    expected = ExpectedAttemptManifestV2.from_launches(
        manifest_id=_id("expected-attempt-manifest"),
        campaign_id=campaign.campaign_id,
        launches=launches,
        frozen_at=started - timedelta(minutes=1),
    )
    by_attempt = {item.attempt_id: item for item in outcomes}
    repeat_attempt_ids = tuple(
        item.attempt_id
        for item in expected.attempts
        if item.case_id == campaign.split.holdout_case_ids[0]
    )
    estimates = []
    for index, attempt_id in enumerate(repeat_attempt_ids):
        outcome = by_attempt[attempt_id]
        estimates.append(
            StructuredEstimateReceiptV1(
                receipt_id=_id(f"estimate-receipt-{index}"),
                campaign_id=campaign.campaign_id,
                case_id=outcome.case_id,
                plan_fingerprint=outcome.plan_fingerprint,
                metric_question_fingerprint=outcome.metric_question_fingerprint,
                evidence_packet_fingerprint=outcome.evidence_packet_fingerprint,
                attempt_id=outcome.attempt_id,
                outcome_id=outcome.outcome_id,
                outcome_fingerprint=outcome.fingerprint,
                structured_output_fingerprint=outcome.structured_output_fingerprint,
                value_kind=MetricValueKind.CATEGORICAL,
                state=CalibrationValueState.KNOWN,
                label_code="positive",
                confidence=0.8,
                recorded_at=outcome.finished_at + timedelta(seconds=1),
            )
        )
    estimates = tuple(sorted(estimates, key=lambda item: (item.recorded_at, item.receipt_id)))
    estimate_by_attempt = {item.attempt_id: item for item in estimates}
    first_attempt = repeat_attempt_ids[0]
    first_outcome = by_attempt[first_attempt]
    first_estimate = estimate_by_attempt[first_attempt]
    candidate = AuthoritativeCandidateProjectionV2(
        projection_id=_id("candidate-projection"),
        campaign_id=campaign.campaign_id,
        case_id=first_outcome.case_id,
        plan_fingerprint=first_outcome.plan_fingerprint,
        metric_question_fingerprint=first_outcome.metric_question_fingerprint,
        evidence_packet_fingerprint=first_outcome.evidence_packet_fingerprint,
        attempt_id=first_attempt,
        outcome_id=first_outcome.outcome_id,
        outcome_fingerprint=first_outcome.fingerprint,
        estimate_receipt_id=first_estimate.receipt_id,
        estimate_receipt_fingerprint=first_estimate.fingerprint,
        stage_ordinal=5,
        stage_kind=stage.kind,
        selected_at=first_estimate.recorded_at + timedelta(seconds=1),
    )
    trials = tuple(
        StabilityTrialReceiptV1(
            receipt_id=_id(f"stability-trial-{index}"),
            campaign_id=campaign.campaign_id,
            case_id=by_attempt[attempt_id].case_id,
            plan_fingerprint=by_attempt[attempt_id].plan_fingerprint,
            metric_question_fingerprint=by_attempt[attempt_id].metric_question_fingerprint,
            evidence_packet_fingerprint=by_attempt[attempt_id].evidence_packet_fingerprint,
            condition=StabilityCondition.REPEAT,
            trial_ordinal=index,
            attempt_id=attempt_id,
            outcome_id=by_attempt[attempt_id].outcome_id,
            outcome_fingerprint=by_attempt[attempt_id].fingerprint,
            estimate_receipt_id=estimate_by_attempt[attempt_id].receipt_id,
            estimate_receipt_fingerprint=estimate_by_attempt[attempt_id].fingerprint,
            recorded_at=estimate_by_attempt[attempt_id].recorded_at + timedelta(seconds=2),
        )
        for index, attempt_id in enumerate(repeat_attempt_ids, start=1)
    )
    series = StabilitySeriesManifestV1(
        series_id=_id("stability-series"),
        campaign_id=campaign.campaign_id,
        case_id=first_outcome.case_id,
        plan_fingerprint=first_outcome.plan_fingerprint,
        metric_question_fingerprint=first_outcome.metric_question_fingerprint,
        evidence_packet_fingerprint=first_outcome.evidence_packet_fingerprint,
        condition=StabilityCondition.REPEAT,
        trials=trials,
        frozen_at=max(item.recorded_at for item in trials) + timedelta(seconds=1),
    )

    baseline = AuthoritativeDeterministicBaselineProjectionV1(
        projection_id=_id("baseline-projection"),
        campaign_id=campaign.campaign_id,
        case_id=first_outcome.case_id,
        plan_fingerprint=first_outcome.plan_fingerprint,
        metric_question_fingerprint=first_outcome.metric_question_fingerprint,
        evidence_packet_fingerprint=first_outcome.evidence_packet_fingerprint,
        baseline_id="reserved-baseline-v1",
        baseline_version="reserved-baseline-v1",
        baseline_configuration_sha256=_id("baseline-config"),
        final_estimate_fingerprint=_id("baseline-final-estimate"),
        value_kind=MetricValueKind.CATEGORICAL,
        state=CalibrationValueState.KNOWN,
        label_code="positive",
        evaluated_at=started + timedelta(minutes=12),
    )
    objective = ObjectiveTruthProjectionV1(
        projection_id=_id("objective-projection"),
        campaign_id=campaign.campaign_id,
        case_id=first_outcome.case_id,
        plan_fingerprint=first_outcome.plan_fingerprint,
        metric_question_fingerprint=first_outcome.metric_question_fingerprint,
        evidence_packet_fingerprint=first_outcome.evidence_packet_fingerprint,
        truth_kind=ObjectiveTruthKind.TEST_RESULT,
        objective_evidence_fingerprint=_id("objective-evidence"),
        verification_adapter_version="reserved-verifier-v1",
        value_kind=MetricValueKind.CATEGORICAL,
        state=CalibrationValueState.KNOWN,
        label_code="positive",
        observed_at=started + timedelta(minutes=21),
    )
    judgments = tuple(
        sorted(
            (
                BlindHumanJudgmentInputV1(
                    judgment_id=_id(f"judgment-{index}"),
                    campaign_id=campaign.campaign_id,
                    case_id=first_outcome.case_id,
                    plan_fingerprint=first_outcome.plan_fingerprint,
                    metric_question_fingerprint=first_outcome.metric_question_fingerprint,
                    evidence_packet_fingerprint=first_outcome.evidence_packet_fingerprint,
                    participant_id=_id(f"participant-{index}"),
                    participant_kind=HumanParticipantKind.INDEPENDENT_ANNOTATOR,
                    annotation_protocol_version="reserved-annotation-v1",
                    value_kind=MetricValueKind.CATEGORICAL,
                    state=CalibrationValueState.KNOWN,
                    label_code="positive",
                    created_at=started + timedelta(minutes=22, seconds=index),
                )
                for index in range(2)
            ),
            key=lambda item: (item.created_at, item.judgment_id),
        )
    )
    adjudication = BlindHumanAdjudicationInputV1(
        adjudication_id=_id("adjudication"),
        campaign_id=campaign.campaign_id,
        case_id=first_outcome.case_id,
        plan_fingerprint=first_outcome.plan_fingerprint,
        metric_question_fingerprint=first_outcome.metric_question_fingerprint,
        evidence_packet_fingerprint=first_outcome.evidence_packet_fingerprint,
        adjudicator_id=_id("adjudicator"),
        adjudicator_kind=HumanParticipantKind.ADJUDICATOR,
        resolution=BlindAdjudicationResolution.RESOLVED,
        judgment_ids=tuple(sorted(item.judgment_id for item in judgments)),
        annotation_protocol_version="reserved-annotation-v1",
        value_kind=MetricValueKind.CATEGORICAL,
        state=CalibrationValueState.KNOWN,
        label_code="positive",
        completed_at=started + timedelta(minutes=23),
    )

    access_manifest = HoldoutAccessManifestV1(
        manifest_id=_id("access-manifest"),
        campaign_id=campaign.campaign_id,
        auditor_version="reserved-auditor-v1",
        coverage_started_at=started - timedelta(minutes=5),
        coverage_ended_at=started + timedelta(minutes=30),
        events=(
            HoldoutAccessEventV1(
                event_id=_id("access-event"),
                campaign_id=campaign.campaign_id,
                case_id=first_outcome.case_id,
                actor_id=_id("system-auditor"),
                actor_kind=HoldoutActorKind.SYSTEM_AUDITOR,
                access_kind=HoldoutAccessKind.CASE_INPUT_READ,
                occurred_at=started - timedelta(minutes=1),
            ),
        ),
        frozen_at=started + timedelta(minutes=31),
    )
    audit = HoldoutAccessAuditV1(
        audit_id=_id("access-audit"),
        campaign_id=campaign.campaign_id,
        manifest=access_manifest,
        holdout_case_ids=campaign.split.holdout_case_ids,
        holdout_unsealed_at=started + timedelta(minutes=20),
        completed_at=started + timedelta(minutes=32),
    )
    artifacts = tuple(
        sorted(
            {
                *(item.structured_output_fingerprint for item in outcomes),
                baseline.final_estimate_fingerprint,
                objective.objective_evidence_fingerprint,
            }
        )
    )
    finding = PrivacyFindingV1(
        finding_id=_id("privacy-finding"),
        campaign_id=campaign.campaign_id,
        artifact_fingerprint=artifacts[0],
        detector_key="reserved-detector",
        detector_version="reserved-detector-v1",
        category=PrivacyFindingCategory.MODEL_OUTPUT_TEXT,
        occurrence_count=2,
        detected_at=started + timedelta(minutes=24),
    )
    privacy_manifest = PrivacyScanManifestV1(
        manifest_id=_id("privacy-manifest"),
        campaign_id=campaign.campaign_id,
        expected_artifact_fingerprints=artifacts,
        scanned_artifact_fingerprints=artifacts,
        findings=(finding,),
        frozen_at=started + timedelta(minutes=25),
    )
    scan = PrivacyScanReceiptV1(
        scan_id=_id("privacy-scan"),
        campaign_id=campaign.campaign_id,
        scanner_version="reserved-scanner-v1",
        manifest=privacy_manifest,
        started_at=started + timedelta(minutes=24),
        completed_at=started + timedelta(minutes=26),
    )
    return CalibrationEvidenceSubmissionV1(
        submission_id=_id("evidence-submission"),
        campaign_id=campaign.campaign_id,
        campaign_holdout_case_ids=campaign.split.holdout_case_ids,
        expected_attempt_manifest=expected,
        attempt_launches=launches,
        attempt_outcomes=outcomes,
        structured_estimate_receipts=estimates,
        holdout_access_audit=audit,
        privacy_scan=scan,
        candidate_projections=(candidate,),
        deterministic_baseline_projections=(baseline,),
        objective_truth_projections=(objective,),
        blind_human_judgments=judgments,
        blind_human_adjudications=(adjudication,),
        stability_series=(series,),
        submitted_at=started + timedelta(minutes=33),
    )


def _registered(tmp_path):
    database, repository = _repository(tmp_path)
    campaign = _campaign()
    repository.register_plan(campaign.stored_plan)
    repository.register_preregistered_campaign(campaign)
    submission = _submission(campaign)
    verifier = _SyntheticStructuredVerifier(
        submission.structured_estimate_receipts
    )
    from prompt_enhancer.infrastructure.sqlite.estimators import SqliteEstimatorRepository

    trusted_repository = SqliteEstimatorRepository(
        database._connection,
        database._ensure_initialized,
        structured_estimate_verifier=verifier,
        begin_evidence_authorization=database._begin_estimator_evidence_authorization,
        end_evidence_authorization=database._end_estimator_evidence_authorization,
        begin_evidence_delete_authorization=database._begin_estimator_evidence_delete_authorization,
        end_evidence_delete_authorization=database._end_estimator_evidence_delete_authorization,
    )
    return database, trusted_repository, campaign, submission, verifier


def test_evidence_partial_restart_seal_round_trip_and_idempotency(tmp_path) -> None:
    database, repository, _, submission, verifier = _registered(tmp_path)
    assert repository.append_calibration_evidence_submission(
        submission, seal=False
    ) is None
    assert repository.get_calibration_evidence_submission(submission.submission_id) is None
    with database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_evidence_attempt_launches"
        ).fetchone()[0] == len(submission.attempt_launches)
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_evidence_submissions"
        ).fetchone()[0] == 0

    from prompt_enhancer.infrastructure.sqlite.estimators import SqliteEstimatorRepository

    restarted = SqliteEstimatorRepository(
        database._connection,
        database._ensure_initialized,
        structured_estimate_verifier=verifier,
        begin_evidence_authorization=database._begin_estimator_evidence_authorization,
        end_evidence_authorization=database._end_estimator_evidence_authorization,
        begin_evidence_delete_authorization=database._begin_estimator_evidence_delete_authorization,
        end_evidence_delete_authorization=database._end_estimator_evidence_delete_authorization,
    )
    assert restarted.append_calibration_evidence_submission(
        submission
    ) == submission.fingerprint
    assert restarted.get_calibration_evidence_submission(
        submission.submission_id
    ) == submission
    assert restarted.append_calibration_evidence_submission(
        submission
    ) == submission.fingerprint


def test_structured_estimates_fail_closed_and_reject_mismatched_decoder(tmp_path) -> None:
    database, _, _, submission, _ = _registered(tmp_path)
    repository = database.estimator_repository()
    with pytest.raises(DatabaseInvariantError, match="independent output verifier"):
        repository.append_calibration_evidence_submission(submission)

    changed = submission.structured_estimate_receipts[0].model_copy(
        update={"confidence": 0.7}
    )
    bad_verifier = _SyntheticStructuredVerifier(
        (changed, *submission.structured_estimate_receipts[1:])
    )
    from prompt_enhancer.infrastructure.sqlite.estimators import SqliteEstimatorRepository

    mismatched_repository = SqliteEstimatorRepository(
        database._connection,
        database._ensure_initialized,
        structured_estimate_verifier=bad_verifier,
        begin_evidence_authorization=database._begin_estimator_evidence_authorization,
        end_evidence_authorization=database._end_estimator_evidence_authorization,
        begin_evidence_delete_authorization=database._begin_estimator_evidence_delete_authorization,
        end_evidence_delete_authorization=database._end_estimator_evidence_delete_authorization,
    )
    with pytest.raises(DatabaseInvariantError, match="independent decoding"):
        mismatched_repository.append_calibration_evidence_submission(submission)


def test_evidence_model_copy_bypass_is_recursively_revalidated_before_write(tmp_path) -> None:
    database, repository, _, submission, verifier = _registered(tmp_path)
    forged = submission.model_copy(update={"activation_allowed": True})
    with pytest.raises(ValueError):
        repository.append_calibration_evidence_submission(forged)
    nested = submission.model_copy(
        update={
            "attempt_launches": (
                submission.attempt_launches[0].model_copy(
                    update={"response_schema_version": "file:reserved"}
                ),
                *submission.attempt_launches[1:],
            )
        }
    )
    with pytest.raises(ValueError):
        repository.append_calibration_evidence_submission(nested)
    with database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_evidence_attempt_launches"
        ).fetchone()[0] == 0


def test_evidence_concurrent_exact_replay_and_conflict_are_atomic(tmp_path) -> None:
    database, _, _, submission, verifier = _registered(tmp_path)

    def append() -> str | None:
        from prompt_enhancer.infrastructure.sqlite.estimators import SqliteEstimatorRepository

        return SqliteEstimatorRepository(
            database._connection,
            database._ensure_initialized,
            structured_estimate_verifier=verifier,
            begin_evidence_authorization=database._begin_estimator_evidence_authorization,
            end_evidence_authorization=database._end_estimator_evidence_authorization,
            begin_evidence_delete_authorization=database._begin_estimator_evidence_delete_authorization,
            end_evidence_delete_authorization=database._end_estimator_evidence_delete_authorization,
        ).append_calibration_evidence_submission(submission)

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert tuple(executor.map(lambda _: append(), range(2))) == (
            submission.fingerprint,
            submission.fingerprint,
        )
    with database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_evidence_submissions"
        ).fetchone()[0] == 1


def test_evidence_rows_are_sealed_against_direct_mutation(tmp_path) -> None:
    database, repository, _, submission, verifier = _registered(tmp_path)
    repository.append_calibration_evidence_submission(submission)
    with database._connection() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE estimator_evidence_submissions SET activation_allowed=1 WHERE submission_id=?",
            (submission.submission_id,),
        )
    with database._connection() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "DELETE FROM estimator_evidence_attempt_outcomes WHERE submission_id=?",
            (submission.submission_id,),
        )
    with pytest.raises(DatabaseError):
        with database._connection() as connection:
            connection.execute(
                "INSERT INTO estimator_evidence_expected_attempts SELECT submission_id, manifest_id, 999, ?, execution_id, case_id, plan_fingerprint, metric_question_fingerprint, evidence_packet_fingerprint, constellation_stage_fingerprint, stage_configuration_sha256, stage_ordinal, stage_kind, ?, campaign_id FROM estimator_evidence_expected_attempts WHERE submission_id=? LIMIT 1",
                (_id("late-attempt"), _id("late-attempt-fingerprint"), submission.submission_id),
            )


def test_campaign_privacy_delete_cascades_partial_and_final_evidence(tmp_path) -> None:
    database, repository, campaign, submission, verifier = _registered(tmp_path)
    repository.append_calibration_evidence_submission(submission)
    assert repository.delete_preregistered_campaign_for_privacy(campaign.campaign_id).value == "deleted_and_purged"
    assert repository.get_calibration_evidence_submission(submission.submission_id) is None
    with database._connection(readonly=True) as connection:
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'estimator_evidence_*'"
        ).fetchall():
            assert connection.execute(f"SELECT COUNT(*) FROM {row['name']}").fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='estimator_evidence_privacy_delete_context'"
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    for path in (
        database.path,
        database.path.with_name(f"{database.path.name}-wal"),
        database.path.with_name(f"{database.path.name}-shm"),
    ):
        if path.exists():
            payload = path.read_bytes()
            assert submission.submission_id.encode() not in payload
            assert submission.attempt_outcomes[0].structured_output_fingerprint.encode() not in payload


def test_schema_17_is_normalized_content_free_and_non_activating(tmp_path) -> None:
    database, _, _, _, _ = _registered(tmp_path)
    assert SCHEMA_VERSION == 61
    forbidden = {"json", "blob", "prompt", "excerpt", "rationale", "commentary", "prose", "path", "uri"}
    with database._connection(readonly=True) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'estimator_evidence_*' ORDER BY name"
        ).fetchall()
        assert len(tables) >= 20
        for item in tables:
            for column in connection.execute(
                f"PRAGMA table_info({item['name']})"
            ).fetchall():
                assert column["type"].upper() != "BLOB"
                assert not any(token in column["name"].lower() for token in forbidden)
        names = {row["name"] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert not any(
            token in name
            for name in names
            for token in ("activation_decision", "gate_report", "estimator_activation")
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert hashlib.sha256(migrations.MIGRATION_17.encode()).hexdigest()


def test_v16_to_v17_preserves_campaign_and_seals_migration_ledger(tmp_path) -> None:
    path = tmp_path / "legacy-v16.sqlite"
    scripts = (_MIGRATION_1,) + tuple(
        getattr(migrations, f"MIGRATION_{version}") for version in range(2, 17)
    )
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
                    hashlib.sha256(script.encode()).hexdigest(),
                    BASE.isoformat(timespec="microseconds"),
                ),
            )
            connection.execute(f"PRAGMA user_version={version}")
            connection.commit()
        connection.execute(
            "INSERT INTO installations VALUES (?, 'synthetic', ?)",
            (_id("migration-preserved-installation"), BASE.isoformat(timespec="microseconds")),
        )
        connection.commit()

    database = Database(path)
    database.initialize()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        rows = connection.execute(
            "SELECT version, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert [row[0] for row in rows] == list(range(1, 62))
        assert rows[15][1] == hashlib.sha256(migrations.MIGRATION_16.encode()).hexdigest()
        assert rows[16][1] == hashlib.sha256(migrations.MIGRATION_17.encode()).hexdigest()
        assert rows[17][1] == hashlib.sha256(migrations.MIGRATION_18.encode()).hexdigest()
        assert connection.execute("SELECT COUNT(*) FROM installations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM estimator_evidence_submissions").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_partial_evidence_privacy_delete_reports_pinned_wal_then_retry_purges(tmp_path) -> None:
    database, repository, campaign, submission, verifier = _registered(tmp_path)
    repository.append_calibration_evidence_submission(
        submission, seal=False
    )
    reader = sqlite3.connect(database.path)
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM estimator_evidence_attempt_launches").fetchall()
        with pytest.raises(DatabaseInvariantError, match="WAL purge is pending"):
            repository.delete_preregistered_campaign_for_privacy(campaign.campaign_id)
    finally:
        reader.rollback()
        reader.close()
    assert repository.get_preregistered_campaign(campaign.campaign_id) is None
    assert repository.delete_preregistered_campaign_for_privacy(
        campaign.campaign_id
    ).value == "already_absent_and_purged"
    needles = (
        submission.submission_id.encode(),
        submission.attempt_outcomes[0].structured_output_fingerprint.encode(),
    )
    for path in (
        database.path,
        database.path.with_name(f"{database.path.name}-wal"),
        database.path.with_name(f"{database.path.name}-shm"),
    ):
        if path.exists():
            payload = path.read_bytes()
            assert all(needle not in payload for needle in needles)


def test_raw_sql_rejects_controls_paths_nonfinite_and_early_final_root(tmp_path) -> None:
    database, repository, _, submission, verifier = _registered(tmp_path)
    repository.append_calibration_evidence_submission(
        submission, seal=False
    )
    with pytest.raises(DatabaseError):
        with database._connection() as connection:
            connection.execute(
                "INSERT INTO estimator_evidence_attempt_launches SELECT submission_id, launch_id, campaign_id, attempt_id||char(0), execution_id, case_id, plan_fingerprint, metric_question_fingerprint, evidence_packet_fingerprint, constellation_stage_fingerprint, stage_ordinal, stage_kind, stage_configuration_sha256, model_artifact_fingerprint, requested_source, requested_model_id, requested_revision, requested_execution_mode, runner_adapter_key, runner_adapter_version, runner_configuration_sha256, response_schema_version, destination, retention_class, approval_kind, approval_id, redaction_preview_fingerprint, approved_at_us, launched_at_us, launch_fingerprint FROM estimator_evidence_attempt_launches LIMIT 1"
            )


def test_raw_sql_cannot_hijack_authorization_or_delete_campaign(tmp_path) -> None:
    database, repository, campaign, submission, verifier = _registered(tmp_path)
    repository.append_calibration_evidence_submission(submission)
    with pytest.raises(DatabaseError):
        with database._connection() as connection:
            connection.execute("PRAGMA trusted_schema=ON")
            connection.execute(
                "INSERT INTO estimator_evidence_append_authorizations VALUES (?,?,?,?)",
                (
                    _id("forged-auth"),
                    submission.submission_id,
                    campaign.campaign_id,
                    _id("forged-auth-tag"),
                ),
            )
    with pytest.raises(DatabaseError):
        with database._connection() as connection:
            connection.execute("PRAGMA trusted_schema=ON")
            connection.execute(
                "DELETE FROM estimator_gate_campaigns WHERE campaign_id=?",
                (campaign.campaign_id,),
            )
    assert repository.get_calibration_evidence_submission(
        submission.submission_id
    ) == submission
    with database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_evidence_append_authorizations"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_evidence_delete_authorizations"
        ).fetchone()[0] == 0


def test_raw_sql_cannot_delete_campaign_before_any_v17_evidence(tmp_path) -> None:
    database, repository = _repository(tmp_path)
    campaign = _campaign()
    repository.register_plan(campaign.stored_plan)
    repository.register_preregistered_campaign(campaign)

    with pytest.raises(DatabaseError):
        with database._connection() as connection:
            connection.execute("PRAGMA trusted_schema=ON")
            connection.execute(
                "DELETE FROM estimator_gate_campaigns WHERE campaign_id=?",
                (campaign.campaign_id,),
            )

    assert repository.get_preregistered_campaign(campaign.campaign_id) == campaign
    with database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_case_manifests_v2 WHERE manifest_fingerprint=?",
            (campaign.assignment_manifest.fingerprint,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_calibration_splits WHERE split_fingerprint=?",
            (campaign.split.fingerprint,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_preregistrations_v2 WHERE preregistration_fingerprint=?",
            (campaign.preregistration_v2.fingerprint,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_constellations WHERE constellation_fingerprint=?",
            (campaign.constellation_identity.fingerprint,),
        ).fetchone()[0] == 1

    assert (
        repository.delete_preregistered_campaign_for_privacy(campaign.campaign_id).value
        == "deleted_and_purged"
    )
    assert repository.get_preregistered_campaign(campaign.campaign_id) is None


@pytest.mark.parametrize(
    ("trigger", "table", "column"),
    (
        (
            "estimator_evidence_expected_manifest_no_update",
            "estimator_evidence_expected_manifests",
            "attempt_count",
        ),
        (
            "estimator_evidence_access_manifest_no_update",
            "estimator_evidence_access_manifests",
            "event_count",
        ),
        (
            "estimator_evidence_access_manifest_no_update",
            "estimator_evidence_access_manifests",
            "gap_count",
        ),
        (
            "estimator_evidence_access_audit_no_update",
            "estimator_evidence_access_audits",
            "holdout_count",
        ),
        (
            "estimator_evidence_privacy_manifest_no_update",
            "estimator_evidence_privacy_manifests",
            "expected_count",
        ),
        (
            "estimator_evidence_privacy_manifest_no_update",
            "estimator_evidence_privacy_manifests",
            "scanned_count",
        ),
        (
            "estimator_evidence_privacy_manifest_no_update",
            "estimator_evidence_privacy_manifests",
            "finding_row_count",
        ),
        (
            "estimator_evidence_privacy_manifest_no_update",
            "estimator_evidence_privacy_manifests",
            "finding_occurrence_count",
        ),
        (
            "estimator_evidence_adjudication_no_update",
            "estimator_evidence_blind_adjudications",
            "judgment_count",
        ),
        (
            "estimator_evidence_series_no_update",
            "estimator_evidence_stability_series",
            "trial_count",
        ),
        *(
            (
                "estimator_evidence_submission_no_update",
                "estimator_evidence_submissions",
                column,
            )
            for column in (
                "holdout_count",
                "launch_count",
                "outcome_count",
                "structured_estimate_count",
                "candidate_projection_count",
                "baseline_projection_count",
                "objective_projection_count",
                "judgment_count",
                "adjudication_count",
                "stability_series_count",
            )
        ),
    ),
)
def test_hydration_rejects_every_corrupted_stored_aggregate_count(
    tmp_path, trigger: str, table: str, column: str
) -> None:
    database, repository, _, submission, _ = _registered(tmp_path)
    repository.append_calibration_evidence_submission(submission)
    with database._connection() as connection:
        connection.execute(f"DROP TRIGGER {trigger}")
        connection.execute(
            f"UPDATE {table} SET {column}={column}+1 WHERE submission_id=?",
            (submission.submission_id,),
        )
        connection.commit()

    with pytest.raises(DatabaseInvariantError, match="count is not reproducible"):
        repository.get_calibration_evidence_submission(submission.submission_id)


def test_hydration_reloads_and_revalidates_v16_campaign_lineage(tmp_path) -> None:
    database, repository, campaign, submission, _ = _registered(tmp_path)
    repository.append_calibration_evidence_submission(submission)
    forged_plan_fingerprint = _id("forged-stored-plan")
    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("DROP TRIGGER estimator_gate_campaigns_no_update")
        connection.execute(
            "UPDATE estimator_gate_campaigns SET stored_plan_fingerprint=? WHERE campaign_id=?",
            (forged_plan_fingerprint, campaign.campaign_id),
        )
        connection.commit()

    with pytest.raises(DatabaseInvariantError):
        repository.get_calibration_evidence_submission(submission.submission_id)


def test_sealed_root_rejects_late_append_on_every_evidence_table(tmp_path) -> None:
    database, repository, _, submission, _ = _registered(tmp_path)
    repository.append_calibration_evidence_submission(submission)
    with database._connection(readonly=True) as connection:
        triggers = {
            row["tbl_name"]
            for row in connection.execute(
                "SELECT tbl_name FROM sqlite_master WHERE type='trigger' AND name GLOB 'estimator_evidence_*_final_sealed'"
            )
        }
        evidence_tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'estimator_evidence_*'"
            )
            if row["name"]
            not in {
                "estimator_evidence_submissions",
                "estimator_evidence_append_authorizations",
                "estimator_evidence_delete_authorizations",
                # V15 synthetic-only tables are outside the V17 campaign ledger.
                "estimator_evidence_packets",
                "estimator_evidence_refs",
            }
        }
        assert evidence_tables <= triggers


def test_raw_sql_rejects_out_of_range_epoch_and_forged_expected_fingerprint(
    tmp_path,
) -> None:
    database, repository, _, submission, _ = _registered(tmp_path)
    repository.append_calibration_evidence_submission(submission, seal=False)
    # Updates are immutable; prove the range trigger itself using a fresh,
    # unauthorized insert attempt with trusted schema enabled. Authorization
    # rejects first, which is the stronger boundary; introspection proves the
    # time-bound trigger is installed on every timestamp-bearing table.
    with database._connection(readonly=True) as connection:
        timestamp_tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'estimator_evidence_*'"
            )
            if any(
                column["name"].endswith("_at_us")
                for column in connection.execute(
                    f"PRAGMA table_info({row['name']})"
                )
            )
        }
        bounded_tables = {
            row["tbl_name"]
            for row in connection.execute(
                "SELECT tbl_name FROM sqlite_master WHERE type='trigger' AND name GLOB 'estimator_evidence_*_time_bounds'"
            )
        }
        assert timestamp_tables <= bounded_tables
    with database._connection() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE estimator_evidence_expected_attempts SET attempt_fingerprint=? WHERE submission_id=?",
            (_id("forged-expected-fingerprint"), submission.submission_id),
        )
    with pytest.raises(DatabaseError):
        with database._connection() as connection:
            connection.execute(
                "INSERT INTO estimator_evidence_attempt_launches SELECT ?, launch_id, campaign_id, ?, execution_id, case_id, plan_fingerprint, metric_question_fingerprint, evidence_packet_fingerprint, constellation_stage_fingerprint, stage_ordinal, stage_kind, stage_configuration_sha256, model_artifact_fingerprint, requested_source, requested_model_id, requested_revision, requested_execution_mode, 'file:reserved', runner_adapter_version, runner_configuration_sha256, response_schema_version, destination, retention_class, approval_kind, approval_id, redaction_preview_fingerprint, approved_at_us, launched_at_us, ? FROM estimator_evidence_attempt_launches LIMIT 1",
                (_id("raw-path-submission"), _id("raw-path-attempt"), _id("raw-path-launch-fingerprint")),
            )
    with database._connection() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE estimator_evidence_attempt_outcomes SET energy_millijoules=? WHERE submission_id=?",
            (float("inf"), submission.submission_id),
        )
    with pytest.raises(DatabaseError):
        with database._connection() as connection:
            connection.execute(
                "INSERT INTO estimator_evidence_submissions VALUES (?,?,?,?,?,?,?,8,9,9,2,1,1,1,2,1,1,0,0,0)",
                (
                    _id("wrong-final-root"),
                    _id("wrong-final-fingerprint"),
                    submission.campaign_id,
                    submission.expected_attempt_manifest.manifest_id,
                    submission.holdout_access_audit.audit_id,
                    submission.privacy_scan.scan_id,
                    0,
                ),
            )
