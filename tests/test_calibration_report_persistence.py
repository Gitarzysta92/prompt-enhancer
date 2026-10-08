from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import hashlib
import inspect
import math
import sqlite3
from threading import Event

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.estimators.calibration_report_contracts import (
    CALIBRATION_MEASUREMENT_SPECS,
    FIXED_CALIBRATION_REPORT_DEFINITION,
    CalibrationMeasurementShape,
    CalibrationMeasurementState,
    CalibrationScopeDimension,
)
from prompt_enhancer.application.estimators.calibration_report_persistence import (
    RepositorySealedCalibrationReportV1,
    revalidate_repository_sealed_calibration_report_v1,
)
from prompt_enhancer.database import (
    Database,
    DatabaseError,
    DatabaseInvariantError,
    SCHEMA_VERSION,
    _MIGRATION_1,
)
from prompt_enhancer.infrastructure.sqlite import migrations
from prompt_enhancer.infrastructure.sqlite.calibration_reports import (
    SqliteCalibrationReportRepository,
)
from prompt_enhancer.infrastructure.sqlite.estimators import SqliteEstimatorRepository

from test_calibration_reporting import _numeric_projection
from test_estimator_campaign_persistence import BASE, _id
from test_estimator_evidence_persistence import (
    _SyntheticStructuredVerifier,
    _registered,
)


DERIVED_AT = datetime(2026, 4, 1, 12, 0, 0, 123456, tzinfo=UTC)


def _report_repository(
    database: Database,
    *,
    clock=lambda: DERIVED_AT,
    fault_hook=None,
) -> SqliteCalibrationReportRepository:
    return SqliteCalibrationReportRepository(
        database._connection,
        database._ensure_initialized,
        begin_write_authorization=(
            database._begin_estimator_calibration_report_authorization
        ),
        end_write_authorization=(
            database._end_estimator_calibration_report_authorization
        ),
        clock=clock,
        fault_hook=fault_hook,
    )


def _sealed(tmp_path):
    database, evidence_repository, campaign, submission, _ = _registered(tmp_path)
    evidence_repository.append_calibration_evidence_submission(submission)
    report_repository = _report_repository(database)
    receipt = report_repository.derive_calibration_report(submission.submission_id)
    return (
        database,
        evidence_repository,
        report_repository,
        campaign,
        submission,
        receipt,
    )


def _create_v18_database(path) -> None:
    scripts = (_MIGRATION_1,) + tuple(
        getattr(migrations, f"MIGRATION_{version}") for version in range(2, 19)
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
                "INSERT INTO schema_migrations VALUES (?,?,?)",
                (
                    version,
                    hashlib.sha256(script.encode()).hexdigest(),
                    BASE.isoformat(timespec="microseconds"),
                ),
            )
            connection.execute(f"PRAGMA user_version={version}")
            connection.commit()


def test_v18_to_v19_migration_is_checksum_tracked_and_does_not_backfill(tmp_path) -> None:
    path = tmp_path / "reserved-private.sqlite"
    _create_v18_database(path)
    database = Database(path)
    database.initialize()
    assert SCHEMA_VERSION == 61
    with database._connection(readonly=True) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        row = connection.execute(
            "SELECT checksum FROM schema_migrations WHERE version=19"
        ).fetchone()
        assert row["checksum"] == hashlib.sha256(
            migrations.MIGRATION_19.encode()
        ).hexdigest()
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_calibration_report_roots"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_calibration_report_measurement_specs"
        ).fetchone()[0] == len(CALIBRATION_MEASUREMENT_SPECS) == 60
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_full_report_round_trip_restart_replay_and_repository_timestamp(tmp_path) -> None:
    database, _, repository, _, submission, receipt = _sealed(tmp_path)
    assert receipt.derived_at == DERIVED_AT
    assert receipt.report.source_observed_at == DERIVED_AT
    assert receipt.report.derived_at is None
    assert receipt.report.repository_owned is False
    assert receipt.repository_owned is receipt.repository_sealed is True
    assert (
        receipt.comparison_allowed
        is receipt.activation_allowed
        is receipt.private_export_allowed
        is receipt.team_share_allowed
        is False
    )
    assert tuple(item.fingerprint for item in receipt.report.metric_reports) == (
        receipt.metric_report_fingerprints
    )

    def clock_must_not_run():
        raise AssertionError("exact replay must preserve the repository timestamp")

    restarted = _report_repository(database, clock=clock_must_not_run)
    assert restarted.derive_calibration_report(submission.submission_id) == receipt
    assert restarted.get_calibration_report_for_submission(submission.submission_id) == receipt
    assert repository.derive_calibration_report(submission.submission_id) == receipt
    with database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_calibration_report_roots"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_calibration_report_append_authorizations"
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_public_derivation_signature_accepts_only_submission_id(tmp_path) -> None:
    database = Database(tmp_path / "reserved-private.sqlite")
    repository = database.calibration_report_repository()
    signature = inspect.signature(repository.derive_calibration_report)
    assert tuple(signature.parameters) == ("submission_id",)
    forbidden = {
        "report",
        "projection",
        "clock",
        "outcome",
        "metrics",
        "campaign",
        "derived_at",
    }
    assert forbidden.isdisjoint(signature.parameters)


def test_missing_and_unsealed_submission_are_rejected(tmp_path) -> None:
    database, evidence_repository, _, submission, _ = _registered(tmp_path)
    repository = _report_repository(database)
    assert repository.get_calibration_report_for_submission(submission.submission_id) is None
    with pytest.raises(DatabaseInvariantError, match="sealed calibration evidence"):
        repository.derive_calibration_report(submission.submission_id)
    evidence_repository.append_calibration_evidence_submission(submission, seal=False)
    with pytest.raises(DatabaseInvariantError, match="sealed calibration evidence"):
        repository.derive_calibration_report(submission.submission_id)
    with pytest.raises(ValueError):
        repository.derive_calibration_report("reserved/submission")


@pytest.mark.parametrize("failure_stage", ("after_children", "after_root", "before_commit"))
def test_atomic_rollback_cleans_rows_database_capability_and_transient_auth(
    tmp_path, failure_stage
) -> None:
    database, evidence_repository, _, submission, _ = _registered(tmp_path)
    evidence_repository.append_calibration_evidence_submission(submission)

    def fail_at_selected_stage(stage: str) -> None:
        if stage == failure_stage:
            raise RuntimeError("reserved rollback injection")

    failing = _report_repository(database, fault_hook=fail_at_selected_stage)
    with pytest.raises(RuntimeError, match="reserved rollback injection"):
        failing.derive_calibration_report(submission.submission_id)
    assert database._estimator_calibration_report_authorizations == set()
    with database._connection(readonly=True) as connection:
        for table in (
            "estimator_calibration_report_drafts",
            "estimator_calibration_report_metric_drafts",
            "estimator_calibration_report_scopes",
            "estimator_calibration_report_measurements",
            "estimator_calibration_report_metric_roots",
            "estimator_calibration_report_roots",
            "estimator_calibration_report_append_authorizations",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert _report_repository(database).derive_calibration_report(
        submission.submission_id
    ).repository_sealed


def test_concurrent_same_submission_is_exactly_idempotent(tmp_path) -> None:
    database, evidence_repository, _, submission, _ = _registered(tmp_path)
    evidence_repository.append_calibration_evidence_submission(submission)
    repositories = (_report_repository(database), _report_repository(database))
    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = tuple(
            executor.map(
                lambda item: item.derive_calibration_report(submission.submission_id),
                repositories,
            )
        )
    assert receipts[0] == receipts[1]
    with database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_calibration_report_roots"
        ).fetchone()[0] == 1


def test_hmac_authority_is_exactly_scoped_and_stale_tags_cannot_be_reused(
    tmp_path,
) -> None:
    database, _, _, campaign, submission, receipt = _sealed(tmp_path)
    report_id = _id("second-report")
    operation_id, tag = database._begin_estimator_calibration_report_authorization(
        report_id, submission.submission_id, campaign.campaign_id
    )
    try:
        assert database._estimator_calibration_report_authorization_tag(
            operation_id, report_id, submission.submission_id, campaign.campaign_id
        ) == tag
        for values in (
            (_id("wrong-operation"), report_id, submission.submission_id, campaign.campaign_id),
            (operation_id, receipt.report.report_id, submission.submission_id, campaign.campaign_id),
            (operation_id, report_id, _id("wrong-submission"), campaign.campaign_id),
            (operation_id, report_id, submission.submission_id, _id("wrong-campaign")),
        ):
            assert database._estimator_calibration_report_authorization_tag(*values) == ""
    finally:
        database._end_estimator_calibration_report_authorization(
            operation_id,
            report_id,
            submission.submission_id,
            campaign.campaign_id,
            tag,
        )
    assert database._estimator_calibration_report_authorization_tag(
        operation_id, report_id, submission.submission_id, campaign.campaign_id
    ) == ""


def test_campaign_privacy_delete_serializes_with_inflight_report_derivation(
    tmp_path,
) -> None:
    database, evidence_repository, campaign, submission, _ = _registered(tmp_path)
    evidence_repository.append_calibration_evidence_submission(submission)
    children_inserted = Event()
    release_derivation = Event()

    def pause_after_children(stage: str) -> None:
        if stage == "after_children":
            children_inserted.set()
            assert release_derivation.wait(timeout=10)

    report_repository = _report_repository(
        database, fault_hook=pause_after_children
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        derive_future = executor.submit(
            report_repository.derive_calibration_report, submission.submission_id
        )
        assert children_inserted.wait(timeout=10)
        delete_future = executor.submit(
            evidence_repository.delete_preregistered_campaign_for_privacy,
            campaign.campaign_id,
        )
        release_derivation.set()
        receipt = derive_future.result(timeout=20)
        outcome = delete_future.result(timeout=20)
    assert receipt.repository_sealed
    assert outcome.value == "deleted_and_purged"
    assert report_repository.get_calibration_report_for_submission(
        submission.submission_id
    ) is None
    with database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_calibration_report_roots"
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_raw_sql_cannot_forge_authority_mutate_delete_or_append_after_seal(tmp_path) -> None:
    database, _, _, _, submission, receipt = _sealed(tmp_path)
    with pytest.raises(DatabaseError):
        with database._connection() as connection:
            connection.execute("PRAGMA trusted_schema=ON")
            connection.execute(
                "INSERT INTO estimator_calibration_report_append_authorizations VALUES (?,?,?,?,?)",
                (_id("forged-op"), receipt.report.report_id, submission.submission_id, submission.campaign_id, _id("forged-tag")),
            )
    with pytest.raises(DatabaseError):
        with database._connection() as connection:
            connection.execute(
                "UPDATE estimator_calibration_report_roots SET comparison_allowed=1 WHERE report_id=?",
                (receipt.report.report_id,),
            )
    with pytest.raises(DatabaseError):
        with database._connection() as connection:
            connection.execute(
                "DELETE FROM estimator_calibration_report_roots WHERE report_id=?",
                (receipt.report.report_id,),
            )
    with pytest.raises(DatabaseError):
        with database._connection() as connection:
            connection.execute("PRAGMA trusted_schema=ON")
            connection.execute(
                """
                INSERT INTO estimator_calibration_report_scopes
                SELECT report_id,metric_key,99999,?,contract_version,dimension,bucket_code,
                       case_count,minimum_required_count,state,reason_code,scope_fingerprint
                FROM estimator_calibration_report_scopes WHERE report_id=? LIMIT 1
                """,
                (_id("late-scope"), receipt.report.report_id),
            )


def test_hydration_rejects_corruption_and_rederives_complete_math(tmp_path) -> None:
    database, _, repository, _, submission, receipt = _sealed(tmp_path)
    metric = receipt.report.metric_reports[0]
    with database._connection() as connection:
        connection.execute(
            "DROP TRIGGER estimator_calibration_report_measurements_no_update"
        )
        connection.execute(
            """
            UPDATE estimator_calibration_report_measurements
            SET measurement_fingerprint=?
            WHERE report_id=? AND metric_key=? AND ordinal=0
            """,
            (_id("corrupt-measurement"), receipt.report.report_id, metric.metric_key),
        )
        connection.commit()
    with pytest.raises(DatabaseInvariantError, match="fingerprint"):
        repository.get_calibration_report_for_submission(submission.submission_id)


def test_complete_vocabulary_missingness_and_insufficient_detail_are_normalized(tmp_path) -> None:
    database, _, _, _, _, receipt = _sealed(tmp_path)
    expected = {item.measurement_key for item in CALIBRATION_MEASUREMENT_SPECS}
    with database._connection(readonly=True) as connection:
        for metric in receipt.report.metric_reports:
            overall = next(
                item
                for item in metric.scopes
                if item.dimension is CalibrationScopeDimension.OVERALL
            )
            rows = connection.execute(
                """
                SELECT measurement_key,state,scalar_value,integer_value,numerator,
                       denominator,reason_code
                FROM estimator_calibration_report_measurements
                WHERE report_id=? AND metric_key=? AND scope_id=?
                """,
                (receipt.report.report_id, metric.metric_key, overall.scope_id),
            ).fetchall()
            assert {row["measurement_key"] for row in rows} == expected
            assert all(
                row["scalar_value"] is None and row["integer_value"] is None
                for row in rows
                if row["state"] != CalibrationMeasurementState.KNOWN.value
            )
            missing = {
                row["measurement_key"]
                for row in rows
                if row["state"] != CalibrationMeasurementState.KNOWN.value
            }
            stored_missing = {
                row["measurement_key"]
                for row in connection.execute(
                    "SELECT measurement_key FROM estimator_calibration_report_missingness WHERE report_id=? AND metric_key=?",
                    (receipt.report.report_id, metric.metric_key),
                ).fetchall()
            }
            assert stored_missing == missing
            insufficient = {
                item.scope_id
                for item in metric.scopes
                if item.state is CalibrationMeasurementState.INSUFFICIENT_DATA
            }
            for table in (
                "estimator_calibration_report_confusion_cells",
                "estimator_calibration_report_class_receipts",
                "estimator_calibration_report_reliability_bins",
                "estimator_calibration_report_selective_points",
            ):
                assert not any(
                    row["scope_id"] in insufficient
                    for row in connection.execute(
                        f"SELECT scope_id FROM {table} WHERE report_id=? AND metric_key=?",
                        (receipt.report.report_id, metric.metric_key),
                    ).fetchall()
                )


def test_comparison_identity_truth_agreement_and_numeric_values_survive_roundtrip(tmp_path) -> None:
    projection = _numeric_projection()
    database = Database(tmp_path / "reserved-private.sqlite")
    base_repository = database.estimator_repository()
    base_repository.register_plan(projection.campaign.stored_plan)
    base_repository.register_preregistered_campaign(projection.campaign)
    verifier = _SyntheticStructuredVerifier(
        projection.submission.structured_estimate_receipts
    )
    evidence_repository = SqliteEstimatorRepository(
        database._connection,
        database._ensure_initialized,
        structured_estimate_verifier=verifier,
        begin_evidence_authorization=database._begin_estimator_evidence_authorization,
        end_evidence_authorization=database._end_estimator_evidence_authorization,
        begin_evidence_delete_authorization=database._begin_estimator_evidence_delete_authorization,
        end_evidence_delete_authorization=database._end_estimator_evidence_delete_authorization,
    )
    evidence_repository.append_calibration_evidence_submission(projection.submission)
    receipt = _report_repository(database).derive_calibration_report(
        projection.submission.submission_id
    )
    restarted = _report_repository(database).get_calibration_report_for_submission(
        projection.submission.submission_id
    )
    assert restarted == receipt
    metric = receipt.report.metric_reports[0]
    assert metric.comparison_identity.submission_fingerprint == (
        projection.submission.fingerprint
    )
    assert metric.comparison_identity.comparison_allowed is False
    assert metric.agreement_receipts == restarted.report.metric_reports[0].agreement_receipts
    numeric_keys = {
        "numeric.mean_absolute_error",
        "numeric.root_mean_squared_error",
        "numeric.within_tolerance_rate",
    }
    overall = next(
        item for item in metric.scopes if item.dimension is CalibrationScopeDimension.OVERALL
    )
    numeric = {
        item.measurement_key: item
        for item in metric.measurements
        if item.scope_id == overall.scope_id and item.measurement_key in numeric_keys
    }
    assert set(numeric) == numeric_keys
    assert all(item.state is CalibrationMeasurementState.UNSUPPORTED for item in numeric.values())
    assert all(item.scalar_value is None for item in numeric.values())
    assert any(
        item.numeric_value == 0.75
        for item in projection.submission.objective_truth_projections
    )


@pytest.mark.parametrize(
    "unsafe",
    (
        "reserved\x00submission",
        "C:/reserved/submission",
        "https://example.invalid/reserved",
        "../reserved",
    ),
)
def test_public_identifier_boundary_rejects_controls_paths_and_uris(tmp_path, unsafe) -> None:
    database = Database(tmp_path / "reserved-private.sqlite")
    repository = database.calibration_report_repository()
    with pytest.raises(ValueError):
        repository.derive_calibration_report(unsafe)


def test_recursive_receipt_revalidation_rejects_nonfinite_negative_zero_and_flag_forgery(tmp_path) -> None:
    _, _, _, _, _, receipt = _sealed(tmp_path)
    metric = receipt.report.metric_reports[0]
    index = next(
        index
        for index, item in enumerate(metric.measurements)
        if item.shape is CalibrationMeasurementShape.SCALAR
        and item.state is CalibrationMeasurementState.KNOWN
    )
    for unsafe in (-0.0, math.inf, math.nan):
        measurements = list(metric.measurements)
        measurements[index] = measurements[index].model_copy(
            update={"scalar_value": unsafe}
        )
        forged_metric = metric.model_copy(update={"measurements": tuple(measurements)})
        forged_report = receipt.report.model_copy(
            update={"metric_reports": (forged_metric, *receipt.report.metric_reports[1:])}
        )
        forged = receipt.model_copy(update={"report": forged_report})
        with pytest.raises((ValidationError, ValueError)):
            revalidate_repository_sealed_calibration_report_v1(forged)
    forged_flag = receipt.model_copy(update={"activation_allowed": True})
    with pytest.raises((ValidationError, ValueError)):
        revalidate_repository_sealed_calibration_report_v1(forged_flag)


def test_schema_is_normalized_scalar_only_and_has_no_decision_or_activation_surface(tmp_path) -> None:
    database = Database(tmp_path / "reserved-private.sqlite")
    database.initialize()
    forbidden = {
        "json",
        "blob",
        "prompt",
        "excerpt",
        "rationale",
        "commentary",
        "prose",
        "path",
        "uri",
        "evidence_body",
        "raw_output",
    }
    with database._connection(readonly=True) as connection:
        tables = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name GLOB 'estimator_calibration_report_*'
            ORDER BY name
            """
        ).fetchall()
        assert len(tables) >= 20
        for row in tables:
            assert "decision" not in row["name"] and "activation" not in row["name"]
            for column in connection.execute(
                f"PRAGMA table_info({row['name']})"
            ).fetchall():
                assert column["type"].upper() != "BLOB"
                assert not any(token in column["name"].lower() for token in forbidden)


def test_campaign_privacy_delete_cascades_reports_and_purges_identifiers(tmp_path) -> None:
    database, evidence_repository, repository, campaign, submission, receipt = _sealed(
        tmp_path
    )
    report_id = receipt.report.report_id
    assert evidence_repository.delete_preregistered_campaign_for_privacy(
        campaign.campaign_id
    ).value == "deleted_and_purged"
    assert repository.get_calibration_report_for_submission(submission.submission_id) is None
    with database._connection(readonly=True) as connection:
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'estimator_calibration_report_*'"
        ).fetchall():
            if row["name"] in {
                "estimator_calibration_report_definitions",
                "estimator_calibration_report_selective_thresholds",
                "estimator_calibration_report_retrieval_ks",
                "estimator_calibration_report_measurement_specs",
            }:
                continue
            assert connection.execute(
                f"SELECT COUNT(*) FROM {row['name']}"
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
            assert report_id.encode() not in payload
            assert submission.submission_id.encode() not in payload


def test_campaign_privacy_delete_wal_retry_includes_report_rows(tmp_path) -> None:
    database, evidence_repository, _, campaign, _, _ = _sealed(tmp_path)
    reader = sqlite3.connect(database.path)
    try:
        reader.execute("PRAGMA journal_mode=WAL")
        reader.execute("BEGIN")
        reader.execute(
            "SELECT COUNT(*) FROM estimator_calibration_report_roots"
        ).fetchone()
        with pytest.raises(DatabaseInvariantError, match="WAL purge is pending"):
            evidence_repository.delete_preregistered_campaign_for_privacy(
                campaign.campaign_id
            )
    finally:
        reader.rollback()
        reader.close()
    assert evidence_repository.delete_preregistered_campaign_for_privacy(
        campaign.campaign_id
    ).value == "already_absent_and_purged"
