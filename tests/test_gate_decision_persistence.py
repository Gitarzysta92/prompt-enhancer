from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import hashlib
import inspect
import sqlite3

import pytest

from prompt_enhancer.application.estimators.evidence_contracts import (
    CalibrationEvidenceSubmissionV1,
    PrivacyScanManifestV1,
    PrivacyScanReceiptV1,
)
from prompt_enhancer.application.estimators.gate_contracts import (
    CalibrationSplit,
    GatePolicy,
    GatePreregistration,
    HighRiskPrecisionRule,
    MetricGateSpec,
    MetricRiskTier,
)
from prompt_enhancer.application.estimators.gate_decision_contracts import (
    GateDecisionCheckOutcome,
    GateDecisionOutcome,
    GateDecisionValueShape,
)
from prompt_enhancer.application.estimators.gate_decision_evaluation import (
    repository_gate_check_vocabulary,
)
from prompt_enhancer.application.estimators.gate_v2_contracts import (
    CaseAssignmentManifestV2,
    CaseAssignmentV2,
    GatePreregistrationV2,
)
from prompt_enhancer.application.estimators.persistence import (
    PreregisteredEstimatorCampaign,
)
from prompt_enhancer.database import (
    Database,
    DatabaseError,
    DatabaseInvariantError,
    SCHEMA_VERSION,
    _MIGRATION_1,
)
from prompt_enhancer.infrastructure.sqlite import migrations
from prompt_enhancer.infrastructure.sqlite.estimators import (
    SqliteEstimatorRepository,
)
from prompt_enhancer.infrastructure.sqlite.gate_decisions import (
    SqliteGateDecisionRepository,
)

from test_calibration_report_persistence import _report_repository
from test_estimator_campaign_persistence import BASE, _campaign, _id
from test_estimator_evidence_persistence import (
    _SyntheticStructuredVerifier,
    _submission,
)


REPORT_AT = datetime(2026, 5, 1, 12, 0, 0, 123456, tzinfo=UTC)
DECISION_AT = datetime(2026, 5, 1, 12, 0, 1, 654321, tzinfo=UTC)


def _rebuilt_campaign(
    *, holdout_start: datetime | None = None
) -> PreregisteredEstimatorCampaign:
    """Rebuild every fingerprint after changing only synthetic observation time."""

    original = _campaign()
    holdout_ids = set(original.split.holdout_case_ids)
    nonholdout = tuple(
        item
        for item in original.assignment_manifest.assignments
        if item.case_id not in holdout_ids
    )
    nonholdout_end = max(item.observed_at for item in nonholdout)
    holdout_start = holdout_start or nonholdout_end + timedelta(microseconds=1)
    holdout_ordinals = {
        case_id: index
        for index, case_id in enumerate(original.split.holdout_case_ids)
    }
    assignments = tuple(
        CaseAssignmentV2.model_validate(
            {
                **item.model_dump(mode="python"),
                "observed_at": (
                    holdout_start
                    + timedelta(microseconds=holdout_ordinals[item.case_id])
                    if item.case_id in holdout_ids
                    else item.observed_at
                ),
            }
        )
        for item in original.assignment_manifest.assignments
    )
    manifest = CaseAssignmentManifestV2.model_validate(
        {
            **original.assignment_manifest.model_dump(mode="python"),
            "assignments": assignments,
        }
    )
    split = CalibrationSplit.model_validate(
        {
            **original.split.model_dump(mode="python"),
            "assignment_manifest_fingerprint": manifest.fingerprint,
        }
    )
    legacy = GatePreregistration.model_validate(
        {
            **original.legacy_preregistration.model_dump(mode="python"),
            "assignment_manifest_fingerprint": manifest.fingerprint,
            "split_fingerprint": split.fingerprint,
        }
    )
    preregistration_v2 = GatePreregistrationV2.model_validate(
        {
            **original.preregistration_v2.model_dump(mode="python"),
            "assignment_manifest_fingerprint": manifest.fingerprint,
            "split_fingerprint": split.fingerprint,
            "legacy_preregistration_fingerprint": legacy.fingerprint,
        }
    )
    return PreregisteredEstimatorCampaign.model_validate(
        {
            **original.model_dump(mode="python"),
            "assignment_manifest": manifest,
            "split": split,
            "legacy_preregistration": legacy,
            "preregistration_v2": preregistration_v2,
        }
    )


def _privacy_clean_submission(
    campaign: PreregisteredEstimatorCampaign,
) -> CalibrationEvidenceSubmissionV1:
    original = _submission(campaign)
    manifest = PrivacyScanManifestV1.model_validate(
        {
            **original.privacy_scan.manifest.model_dump(mode="python"),
            "findings": (),
        }
    )
    scan = PrivacyScanReceiptV1.model_validate(
        {
            **original.privacy_scan.model_dump(mode="python"),
            "manifest": manifest,
        }
    )
    return CalibrationEvidenceSubmissionV1.model_validate(
        {
            **original.model_dump(mode="python"),
            "privacy_scan": scan,
        }
    )


def _high_risk_campaign() -> PreregisteredEstimatorCampaign:
    original = _rebuilt_campaign()
    metric = original.legacy_preregistration.metric_specs[0]
    policy = GatePolicy.model_validate(
        {
            **original.policy.model_dump(mode="python"),
            "high_risk_precision_rules": (
                HighRiskPrecisionRule(
                    metric_key=metric.metric_key,
                    minimum_precision=0.9,
                    minimum_positive_predictions=2,
                ),
            ),
        }
    )
    legacy = GatePreregistration.model_validate(
        {
            **original.legacy_preregistration.model_dump(mode="python"),
            "policy_fingerprint": policy.fingerprint,
            "metric_specs": (
                MetricGateSpec(
                    metric_key=metric.metric_key,
                    label_vocabulary=metric.label_vocabulary,
                    risk_tier=MetricRiskTier.HIGH,
                    positive_label="positive",
                ),
            ),
        }
    )
    preregistration_v2 = GatePreregistrationV2.model_validate(
        {
            **original.preregistration_v2.model_dump(mode="python"),
            "policy_fingerprint": policy.fingerprint,
            "legacy_preregistration_fingerprint": legacy.fingerprint,
        }
    )
    return PreregisteredEstimatorCampaign.model_validate(
        {
            **original.model_dump(mode="python"),
            "policy": policy,
            "legacy_preregistration": legacy,
            "preregistration_v2": preregistration_v2,
        }
    )


def _latency_minimum_campaign(minimum: int) -> PreregisteredEstimatorCampaign:
    original = _rebuilt_campaign()
    policy = GatePolicy.model_validate(
        {
            **original.policy.model_dump(mode="python"),
            "minimum_operational_samples_per_latency_class": minimum,
        }
    )
    legacy = GatePreregistration.model_validate(
        {
            **original.legacy_preregistration.model_dump(mode="python"),
            "policy_fingerprint": policy.fingerprint,
        }
    )
    preregistration_v2 = GatePreregistrationV2.model_validate(
        {
            **original.preregistration_v2.model_dump(mode="python"),
            "policy_fingerprint": policy.fingerprint,
            "legacy_preregistration_fingerprint": legacy.fingerprint,
        }
    )
    return PreregisteredEstimatorCampaign.model_validate(
        {
            **original.model_dump(mode="python"),
            "policy": policy,
            "legacy_preregistration": legacy,
            "preregistration_v2": preregistration_v2,
        }
    )


def _gate_repository(
    database: Database,
    *,
    clock=lambda: DECISION_AT,
    fault_hook=None,
) -> SqliteGateDecisionRepository:
    return SqliteGateDecisionRepository(
        database._connection,
        database._ensure_initialized,
        begin_write_authorization=(
            database._begin_estimator_gate_decision_authorization
        ),
        end_write_authorization=(
            database._end_estimator_gate_decision_authorization
        ),
        clock=clock,
        fault_hook=fault_hook,
    )


def _sealed_lineage(
    tmp_path,
    *,
    campaign: PreregisteredEstimatorCampaign | None = None,
    clean_privacy: bool = True,
):
    database = Database(tmp_path / "reserved-private.sqlite")
    database.initialize()
    campaign = campaign or _rebuilt_campaign()
    repository = database.estimator_repository()
    repository.register_plan(campaign.stored_plan)
    repository.register_preregistered_campaign(campaign)
    submission = (
        _privacy_clean_submission(campaign)
        if clean_privacy
        else _submission(campaign)
    )
    verifier = _SyntheticStructuredVerifier(
        submission.structured_estimate_receipts
    )
    evidence_repository = SqliteEstimatorRepository(
        database._connection,
        database._ensure_initialized,
        structured_estimate_verifier=verifier,
        begin_evidence_authorization=(
            database._begin_estimator_evidence_authorization
        ),
        end_evidence_authorization=(
            database._end_estimator_evidence_authorization
        ),
        begin_evidence_delete_authorization=(
            database._begin_estimator_evidence_delete_authorization
        ),
        end_evidence_delete_authorization=(
            database._end_estimator_evidence_delete_authorization
        ),
    )
    evidence_repository.append_calibration_evidence_submission(submission)
    sealed_report = _report_repository(
        database, clock=lambda: REPORT_AT
    ).derive_calibration_report(submission.submission_id)
    return database, campaign, submission, sealed_report


def _by_key(decision):
    return {item.check_key: item for item in decision.checks}


def _create_v19_database(path) -> None:
    scripts = (_MIGRATION_1,) + tuple(
        getattr(migrations, f"MIGRATION_{version}")
        for version in range(2, 20)
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


def test_expanded_vocabulary_is_exact_and_clean_lineage_is_insufficient(
    tmp_path,
) -> None:
    database, campaign, _, sealed_report = _sealed_lineage(tmp_path)
    decision = _gate_repository(database).derive_gate_decision(
        sealed_report.report.report_id
    )
    expected = repository_gate_check_vocabulary(campaign, sealed_report)
    assert tuple(item.check_key for item in decision.checks) == expected
    assert len(expected) == 85
    assert decision.outcome is GateDecisionOutcome.INSUFFICIENT_DATA
    assert not any(
        item.outcome is GateDecisionCheckOutcome.FAIL
        for item in decision.checks
    )
    assert any(
        item.outcome is GateDecisionCheckOutcome.UNSUPPORTED
        for item in decision.checks
    )
    assert all(
        item.actual.shape is GateDecisionValueShape.NONE
        for item in decision.checks
        if item.outcome
        in {
            GateDecisionCheckOutcome.INSUFFICIENT_DATA,
            GateDecisionCheckOutcome.UNSUPPORTED,
        }
    )

    keys = set(expected)
    for stratum in campaign.policy.required_strata:
        assert f"policy.active_learning.stratum.{stratum.value}" in keys
        assert f"policy.holdout.stratum.{stratum.value}" in keys
    for language in campaign.policy.required_languages:
        assert f"policy.active_learning.language.{language.value}" in keys
        assert f"policy.holdout.language.{language.value}" in keys
    metric_key = sealed_report.report.metric_reports[0].metric_key
    for dimension in campaign.policy.subgroup_dimensions:
        assert f"policy.subgroup.minimum.{dimension.value}.{metric_key}" in keys
        assert f"policy.subgroup.regression.{dimension.value}.{metric_key}" in keys
    assert f"policy.cold_latency_samples.{metric_key}" in keys
    assert f"policy.warm_latency_samples.{metric_key}" in keys


def test_operational_latency_minimum_is_bound_before_p95_evaluation(tmp_path) -> None:
    decisions = []
    for minimum, folder in ((1, "minimum-one"), (999, "minimum-many")):
        target = tmp_path / folder
        target.mkdir()
        database, campaign, _, sealed_report = _sealed_lineage(
            target,
            campaign=_latency_minimum_campaign(minimum),
        )
        decision = _gate_repository(database).derive_gate_decision(
            sealed_report.report.report_id
        )
        checks = _by_key(decision)
        metric_key = campaign.stored_plan.question_specs[0].metric_key
        for latency_class in ("cold", "warm"):
            sample = checks[
                f"policy.{latency_class}_latency_samples.{metric_key}"
            ]
            percentile = checks[
                f"policy.{latency_class}_latency_p95.{metric_key}"
            ]
            assert sample.threshold.integer_value == minimum
            assert sample.actual.shape is GateDecisionValueShape.NONE
            assert percentile.actual.shape is GateDecisionValueShape.NONE
            assert sample.outcome is GateDecisionCheckOutcome.UNSUPPORTED
            assert percentile.outcome is GateDecisionCheckOutcome.UNSUPPORTED
        decisions.append(decision)
    assert decisions[0].check_set_fingerprint != decisions[1].check_set_fingerprint


def test_privacy_occurrences_are_rejected_separately_from_scan_coverage(
    tmp_path,
) -> None:
    database, _, _, sealed_report = _sealed_lineage(
        tmp_path, clean_privacy=False
    )
    decision = _gate_repository(database).derive_gate_decision(
        sealed_report.report.report_id
    )
    checks = _by_key(decision)
    finding = checks["policy.privacy.findings"]
    assert decision.outcome is GateDecisionOutcome.REJECTED
    assert finding.outcome is GateDecisionCheckOutcome.FAIL
    assert finding.actual.integer_value == 2
    assert finding.threshold.integer_value == 0
    assert checks["policy.privacy.unscanned"].outcome is GateDecisionCheckOutcome.PASS
    assert checks["policy.privacy.scan_coverage"].outcome is GateDecisionCheckOutcome.PASS


def test_time_separation_is_strict_at_the_exact_boundary(tmp_path) -> None:
    baseline = _campaign()
    holdout = set(baseline.split.holdout_case_ids)
    nonholdout_end = max(
        item.observed_at
        for item in baseline.assignment_manifest.assignments
        if item.case_id not in holdout
    )
    campaign = _rebuilt_campaign(holdout_start=nonholdout_end)
    database, _, _, sealed_report = _sealed_lineage(
        tmp_path, campaign=campaign
    )
    decision = _gate_repository(database).derive_gate_decision(
        sealed_report.report.report_id
    )
    check = _by_key(decision)["integrity.time_separation"]
    assert check.outcome is GateDecisionCheckOutcome.FAIL
    assert check.actual.integer_value == 1
    assert check.threshold.integer_value == 0
    assert decision.outcome is GateDecisionOutcome.REJECTED


def test_public_repository_signature_accepts_only_report_id(tmp_path) -> None:
    repository = Database(
        tmp_path / "reserved-private.sqlite"
    ).gate_decision_repository()
    assert tuple(inspect.signature(repository.derive_gate_decision).parameters) == (
        "report_id",
    )
    assert tuple(
        inspect.signature(repository.get_gate_decision_for_report).parameters
    ) == ("report_id",)


def test_round_trip_restart_replay_and_repository_clock(tmp_path) -> None:
    database, _, _, sealed_report = _sealed_lineage(tmp_path)
    report_id = sealed_report.report.report_id
    repository = _gate_repository(database)
    decision = repository.derive_gate_decision(report_id)
    assert decision.derived_at == DECISION_AT

    def clock_must_not_run():
        raise AssertionError("exact replay must preserve repository time")

    restarted = _gate_repository(database, clock=clock_must_not_run)
    assert restarted.derive_gate_decision(report_id) == decision
    assert restarted.get_gate_decision_for_report(report_id) == decision
    assert database.gate_decision_repository().get_gate_decision_for_report(
        report_id
    ) == decision
    with database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_gate_decision_roots"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_gate_decision_append_authorizations"
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_concurrent_exact_replay_has_one_root(tmp_path) -> None:
    database, _, _, sealed_report = _sealed_lineage(tmp_path)
    report_id = sealed_report.report.report_id

    def derive(_):
        return _gate_repository(database).derive_gate_decision(report_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        decisions = tuple(executor.map(derive, range(2)))
    assert decisions[0] == decisions[1]
    with database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_gate_decision_roots"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_gate_decision_checks"
        ).fetchone()[0] == len(decisions[0].checks)


def test_fault_rolls_back_children_root_and_transient_authorization(tmp_path) -> None:
    database, _, _, sealed_report = _sealed_lineage(tmp_path)

    def fail_after_checks(stage: str) -> None:
        if stage == "after_checks":
            raise RuntimeError("reserved synthetic fault")

    with pytest.raises(RuntimeError, match="synthetic fault"):
        _gate_repository(
            database, fault_hook=fail_after_checks
        ).derive_gate_decision(sealed_report.report.report_id)
    with database._connection(readonly=True) as connection:
        for table in (
            "estimator_gate_decision_append_authorizations",
            "estimator_gate_decision_drafts",
            "estimator_gate_decision_checks",
            "estimator_gate_decision_roots",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0] == 0


def test_missing_or_unsealed_report_cannot_derive(tmp_path) -> None:
    database = Database(tmp_path / "reserved-private.sqlite")
    database.initialize()
    with pytest.raises(DatabaseInvariantError, match="report"):
        _gate_repository(database).derive_gate_decision(_id("missing-report"))


def test_registered_high_risk_vocabulary_is_added_and_missingness_is_retained(
    tmp_path,
) -> None:
    campaign = _high_risk_campaign()
    database, campaign, _, sealed_report = _sealed_lineage(
        tmp_path, campaign=campaign
    )
    decision = _gate_repository(database).derive_gate_decision(
        sealed_report.report.report_id
    )
    metric_key = campaign.legacy_preregistration.metric_specs[0].metric_key
    ordinary_keys = set(
        repository_gate_check_vocabulary(_rebuilt_campaign(), sealed_report)
    )
    expected = repository_gate_check_vocabulary(campaign, sealed_report)
    assert len(expected) == 87
    assert set(expected) - ordinary_keys == {
        f"policy.high_risk_positive_predictions.{metric_key}",
        f"policy.high_risk_precision.{metric_key}",
    }
    checks = _by_key(decision)
    for key in set(expected) - ordinary_keys:
        assert checks[key].outcome is GateDecisionCheckOutcome.INSUFFICIENT_DATA
        assert checks[key].actual.shape is GateDecisionValueShape.NONE
        assert checks[key].reason_code == "class_receipt_unavailable"
    assert checks["policy.high_risk.registration"].outcome is GateDecisionCheckOutcome.PASS


def test_raw_hmac_authorization_is_job_and_decision_scoped_and_stale(tmp_path) -> None:
    database, _, _, sealed_report = _sealed_lineage(tmp_path)
    decision = _gate_repository(database).derive_gate_decision(
        sealed_report.report.report_id
    )
    report_id = decision.report_id
    decision_id = decision.decision_id
    job_id = _id("auth-job")
    operation_id, tag = database._begin_estimator_gate_decision_authorization(
        report_id, decision_id, job_id
    )
    try:
        for changed_decision, changed_job in (
            (_id("cross-decision"), job_id),
            (decision_id, _id("cross-job")),
        ):
            with pytest.raises(DatabaseError):
                with database._connection() as connection:
                    connection.execute("PRAGMA trusted_schema=ON")
                    connection.execute(
                        "INSERT INTO estimator_gate_decision_append_authorizations VALUES (?,?,?,?,?)",
                        (
                            operation_id,
                            report_id,
                            changed_decision,
                            changed_job,
                            tag,
                        ),
                    )

        with database._connection() as connection:
            connection.execute("PRAGMA trusted_schema=ON")
            connection.execute(
                "INSERT INTO estimator_gate_decision_append_authorizations VALUES (?,?,?,?,?)",
                (operation_id, report_id, decision_id, job_id, tag),
            )
            database._end_estimator_gate_decision_authorization(
                operation_id, report_id, decision_id, job_id, tag
            )
            with pytest.raises(sqlite3.IntegrityError, match="invalid"):
                connection.execute(
                    "DELETE FROM estimator_gate_decision_append_authorizations WHERE operation_id=?",
                    (operation_id,),
                )
            with pytest.raises(sqlite3.IntegrityError, match="invalid"):
                connection.execute(
                    "INSERT INTO estimator_gate_decision_append_authorizations VALUES (?,?,?,?,?)",
                    (operation_id, report_id, decision_id, job_id, tag),
                )
            connection.rollback()
    finally:
        database._end_estimator_gate_decision_authorization(
            operation_id, report_id, decision_id, job_id, tag
        )
    with database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_gate_decision_append_authorizations"
        ).fetchone()[0] == 0


def test_raw_sql_cannot_append_update_or_standalone_delete_after_seal(
    tmp_path,
) -> None:
    database, _, _, sealed_report = _sealed_lineage(tmp_path)
    decision = _gate_repository(database).derive_gate_decision(
        sealed_report.report.report_id
    )
    job_id = _id("late-append-job")
    operation_id, tag = database._begin_estimator_gate_decision_authorization(
        decision.report_id, decision.decision_id, job_id
    )
    try:
        with database._connection() as connection:
            connection.execute("PRAGMA trusted_schema=ON")
            connection.execute(
                "INSERT INTO estimator_gate_decision_append_authorizations VALUES (?,?,?,?,?)",
                (
                    operation_id,
                    decision.report_id,
                    decision.decision_id,
                    job_id,
                    tag,
                ),
            )
            with pytest.raises(sqlite3.IntegrityError, match="sealed"):
                connection.execute(
                    """
                    INSERT INTO estimator_gate_decision_checks
                    SELECT decision_id,999,contract_version,'policy.late_append',category,
                           outcome,operator,actual_shape,actual_unit_code,
                           actual_integer_value,actual_scalar_value,threshold_shape,
                           threshold_unit_code,threshold_integer_value,
                           threshold_scalar_value,reason_code,?
                    FROM estimator_gate_decision_checks
                    WHERE decision_id=? AND ordinal=0
                    """,
                    (_id("late-check-fingerprint"), decision.decision_id),
                )
            connection.rollback()
    finally:
        database._end_estimator_gate_decision_authorization(
            operation_id,
            decision.report_id,
            decision.decision_id,
            job_id,
            tag,
        )

    for statement in (
        "UPDATE estimator_gate_decision_checks SET reason_code='corrupt' WHERE decision_id=? AND ordinal=0",
        "UPDATE estimator_gate_decision_roots SET outcome='rejected' WHERE decision_id=?",
        "DELETE FROM estimator_gate_decision_checks WHERE decision_id=? AND ordinal=0",
        "DELETE FROM estimator_gate_decision_roots WHERE decision_id=?",
        "DELETE FROM estimator_gate_decision_drafts WHERE decision_id=?",
    ):
        with database._connection() as connection:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(statement, (decision.decision_id,))
            connection.rollback()
    assert _gate_repository(database).get_gate_decision_for_report(
        decision.report_id
    ) == decision


def test_get_rejects_relational_corruption(tmp_path) -> None:
    database, _, _, sealed_report = _sealed_lineage(tmp_path)
    repository = _gate_repository(database)
    decision = repository.derive_gate_decision(sealed_report.report.report_id)
    with database._connection() as connection:
        connection.execute(
            "DROP TRIGGER estimator_gate_decision_check_no_update"
        )
        connection.execute(
            "UPDATE estimator_gate_decision_checks SET check_fingerprint=? WHERE decision_id=? AND ordinal=0",
            (_id("corrupt-check-fingerprint"), decision.decision_id),
        )
        connection.commit()
    with pytest.raises(DatabaseInvariantError, match="fingerprint"):
        repository.get_gate_decision_for_report(decision.report_id)


def test_v19_to_v20_migration_is_checksum_tracked_and_has_no_backfill(
    tmp_path,
) -> None:
    path = tmp_path / "reserved-v19.sqlite"
    _create_v19_database(path)
    database = Database(path)
    database.initialize()
    assert SCHEMA_VERSION == 61
    with database._connection(readonly=True) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        assert connection.execute(
            "SELECT checksum FROM schema_migrations WHERE version=20"
        ).fetchone()[0] == hashlib.sha256(migrations.MIGRATION_20.encode()).hexdigest()
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_gate_decision_definitions"
        ).fetchone()[0] == 1
        for table in (
            "estimator_gate_decision_append_authorizations",
            "estimator_gate_decision_drafts",
            "estimator_gate_decision_checks",
            "estimator_gate_decision_roots",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_v20_schema_is_normalized_scalar_only_and_has_no_activation_slot(
    tmp_path,
) -> None:
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
        "private_identifier",
    }
    with database._connection(readonly=True) as connection:
        tables = tuple(
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'estimator_gate_decision_*' ORDER BY name"
            )
        )
        assert tables == (
            "estimator_gate_decision_append_authorizations",
            "estimator_gate_decision_checks",
            "estimator_gate_decision_definitions",
            "estimator_gate_decision_drafts",
            "estimator_gate_decision_roots",
        )
        assert not any("activation" in table for table in tables)
        for table in tables:
            columns = connection.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()
            assert all(column["type"].upper() != "BLOB" for column in columns)
            assert all(
                not any(token in column["name"].lower() for token in forbidden)
                for column in columns
            )
        check_columns = {
            row["name"]: row["type"].upper()
            for row in connection.execute(
                "PRAGMA table_info(estimator_gate_decision_checks)"
            )
        }
        assert check_columns["actual_integer_value"] == "INTEGER"
        assert check_columns["actual_scalar_value"] == "REAL"
        assert check_columns["threshold_integer_value"] == "INTEGER"
        assert check_columns["threshold_scalar_value"] == "REAL"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_campaign_privacy_delete_cascades_decision_and_purges_wal_bytes(
    tmp_path,
) -> None:
    database, campaign, submission, sealed_report = _sealed_lineage(tmp_path)
    decision = _gate_repository(database).derive_gate_decision(
        sealed_report.report.report_id
    )
    reader = sqlite3.connect(database.path)
    try:
        reader.execute("BEGIN")
        reader.execute(
            "SELECT * FROM estimator_gate_decision_checks"
        ).fetchall()
        with pytest.raises(DatabaseInvariantError, match="WAL purge is pending"):
            database.estimator_repository().delete_preregistered_campaign_for_privacy(
                campaign.campaign_id
            )
    finally:
        reader.rollback()
        reader.close()
    assert (
        database.estimator_repository().delete_preregistered_campaign_for_privacy(
            campaign.campaign_id
        ).value
        == "already_absent_and_purged"
    )
    assert _gate_repository(database).get_gate_decision_for_report(
        decision.report_id
    ) is None
    with database._connection(readonly=True) as connection:
        for table in (
            "estimator_gate_decision_append_authorizations",
            "estimator_gate_decision_drafts",
            "estimator_gate_decision_checks",
            "estimator_gate_decision_roots",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    needles = (
        campaign.campaign_id.encode(),
        submission.submission_id.encode(),
        decision.decision_id.encode(),
        decision.checks[0].fingerprint.encode(),
    )
    for path in (
        database.path,
        database.path.with_name(f"{database.path.name}-wal"),
        database.path.with_name(f"{database.path.name}-shm"),
    ):
        if path.exists():
            payload = path.read_bytes()
            assert all(needle not in payload for needle in needles)
