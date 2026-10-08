from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import hashlib
import sqlite3

import pytest

from prompt_enhancer.application.estimators.contracts import (
    ArtifactAvailability,
    EstimatorPlan,
    EstimatorReasoningEffort,
    EstimatorRoute,
    EstimatorStage,
    EstimatorStageKind,
    MetricDirection,
    MetricQuestionSpec,
    MetricValueKind,
    ModelArtifactIdentity,
    ModelExecutionMode,
    ModelSource,
    ProviderSchemaIdentity,
    StageCondition,
    TokenizerIdentity,
)
from prompt_enhancer.application.estimators.gate_contracts import (
    CalibrationLanguage,
    CalibrationSplit,
    CalibrationTaskStratum,
    CaseOrigin,
    EvidenceTier,
    GatePolicy,
    GatePreregistration,
    MetricGateSpec,
    MetricRiskTier,
)
from prompt_enhancer.application.estimators.gate_v2_contracts import (
    CaseAssignmentManifestV2,
    CaseAssignmentV2,
    ConstellationIdentityReceipt,
    GatePreregistrationV2,
)
from prompt_enhancer.application.estimators.persistence import (
    PrivacyDeleteOutcome,
    PreregisteredEstimatorCampaign,
)
from prompt_enhancer.database import (
    Database,
    DatabaseInvariantError,
    SCHEMA_VERSION,
    _MIGRATION_1,
)
from prompt_enhancer.domain import Provider
from prompt_enhancer.infrastructure.sqlite import migrations


BASE = datetime(2026, 1, 1, tzinfo=UTC)
METRIC_KEY = "verification_quality"


def _id(label: str) -> str:
    return hashlib.sha256(f"reserved-example:{label}".encode()).hexdigest()


def _artifact(index: int) -> ModelArtifactIdentity:
    return ModelArtifactIdentity(
        source=ModelSource.OPENAI_API,
        requested_model_id=f"reserved-model-{index}-v1",
        served_model_id=f"reserved-model-{index}-v1",
        requested_revision="reserved-revision-v1",
        served_revision="reserved-revision-v1",
        requested_execution_mode=ModelExecutionMode.STANDARD,
        served_execution_mode=ModelExecutionMode.STANDARD,
        weight_availability=ArtifactAvailability.PROVIDER_MANAGED,
        tokenizer=TokenizerIdentity(
            tokenizer_id=f"reserved-tokenizer-{index}-v1",
            revision="reserved-revision-v1",
            availability=ArtifactAvailability.PROVIDER_MANAGED,
        ),
        license_id="reserved-provider-license-v1",
    )


def _plan(*, plan_version: str = "reserved-plan-v1") -> EstimatorPlan:
    question = MetricQuestionSpec(
        metric_key=METRIC_KEY,
        metric_definition_version="metric-v1",
        question_id="verification-quality-question",
        question_version="question-v1",
        question_sha256=_id("question"),
        prompt_template_id="verification-quality-template",
        prompt_template_version="template-v1",
        prompt_template_sha256=_id("template"),
        rubric_id="verification-quality-rubric",
        rubric_version="rubric-v1",
        rubric_sha256=_id("rubric"),
        output_schema_version="metric-output-v1",
        value_kind=MetricValueKind.CATEGORICAL,
        unit_code="label",
        direction=MetricDirection.DESCRIPTIVE,
    )
    model_kinds = {
        EstimatorStageKind.EMBEDDING_RETRIEVAL,
        EstimatorStageKind.RERANKER,
        EstimatorStageKind.SPECIALIST,
        EstimatorStageKind.SECOND_OPINION,
    }
    stages = tuple(
        EstimatorStage(
            ordinal=index,
            kind=kind,
            condition=(
                StageCondition.DISAGREEMENT_LOW_CONFIDENCE_DRIFT_AUDIT_OR_HIGH_VALUE
                if kind is EstimatorStageKind.SECOND_OPINION
                else StageCondition.UNRESOLVED_DISAGREEMENT
                if kind is EstimatorStageKind.HUMAN_ADJUDICATION
                else StageCondition.ALWAYS
            ),
            component_version=f"reserved-stage-{index}-v1",
            configuration_sha256=_id(f"stage:{index}"),
            output_schema_version=f"reserved-output-{index}-v1",
            model_artifact=_artifact(index) if kind in model_kinds else None,
        )
        for index, kind in enumerate(tuple(EstimatorStageKind), start=1)
    )
    return EstimatorPlan(
        plan_key=f"reserved-campaign-{_id(plan_version)[:8]}",
        plan_version=plan_version,
        route=EstimatorRoute.BALANCED,
        question_specs=(question,),
        evidence_packet_schema_version="reserved-packet-v1",
        provider_schemas=(
            ProviderSchemaIdentity(
                provider=Provider.CODEX,
                adapter_version="reserved-adapter-v1",
                provider_schema_version="reserved-provider-schema-v1",
            ),
        ),
        preprocessing_version="reserved-preprocessing-v1",
        preprocessing_sha256=_id("preprocessing"),
        reasoning_effort=EstimatorReasoningEffort.MEDIUM,
        calibration_version="reserved-calibration-v1",
        calibration_sha256=_id("calibration"),
        router_version="reserved-router-v1",
        router_sha256=_id("router"),
        redactor_version="reserved-redactor-v1",
        redactor_sha256=_id("redactor"),
        stages=stages,
    )


def _policy() -> GatePolicy:
    return GatePolicy(
        policy_id=_id("policy"),
        minimum_holdout_count=8,
        minimum_holdout_per_metric=8,
        minimum_holdout_per_stratum=2,
        minimum_holdout_per_language=4,
        minimum_operational_samples_per_latency_class=4,
        minimum_subgroup_size=2,
        minimum_baseline_margin=0.0,
        minimum_selective_coverage=0.95,
        maximum_selective_risk=0.05,
        false_confidence_threshold=0.90,
        maximum_false_confident_error_rate=0.0,
        maximum_cold_p95_latency_ms=1_000.0,
        maximum_warm_p95_latency_ms=500.0,
        maximum_oom_rate=0.01,
        maximum_error_rate=0.01,
        maximum_refusal_rate=0.01,
        maximum_material_subgroup_regression=0.02,
    )


def _campaign(
    plan: EstimatorPlan | None = None, *, policy: GatePolicy | None = None
) -> PreregisteredEstimatorCampaign:
    plan = plan or _plan()
    question_fingerprint = plan.question_specs[0].canonical_fingerprint
    roles = (("development", 8), ("active", 100), ("holdout", 8))
    role_ids: dict[str, list[str]] = {role: [] for role, _ in roles}
    assignments = []
    for role, count in roles:
        for index in range(count):
            case_id = _id(f"{plan.plan_version}:{role}:case:{index}")
            role_ids[role].append(case_id)
            assignments.append(
                CaseAssignmentV2(
                    case_id=case_id,
                    project_id=_id(f"{plan.plan_version}:{role}:project:{index % 2}"),
                    session_revision_id=_id(
                        f"{plan.plan_version}:{role}:revision:{index}"
                    ),
                    metric_key=METRIC_KEY,
                    provider=Provider.CODEX,
                    origin=CaseOrigin.PRIVATE_REPRESENTATIVE,
                    task_stratum=tuple(CalibrationTaskStratum)[index % 4],
                    language=tuple(CalibrationLanguage)[index % 2],
                    evidence_tier=EvidenceTier.OBJECTIVE,
                    observed_at=BASE + timedelta(days=1, minutes=index),
                    plan_fingerprint=plan.canonical_fingerprint,
                    metric_question_fingerprint=question_fingerprint,
                    evidence_packet_fingerprint=_id(
                        f"{plan.plan_version}:{role}:packet:{index}"
                    ),
                )
            )
    manifest = CaseAssignmentManifestV2(
        manifest_id=_id(f"{plan.plan_version}:manifest"),
        plan_fingerprint=plan.canonical_fingerprint,
        frozen_at=BASE + timedelta(days=3),
        assignments=tuple(sorted(assignments, key=lambda item: item.case_id)),
    )
    split = CalibrationSplit(
        split_id=_id(f"{plan.plan_version}:split"),
        assignment_manifest_fingerprint=manifest.fingerprint,
        frozen_at=BASE + timedelta(days=4),
        development_case_ids=tuple(sorted(role_ids["development"])),
        active_learning_case_ids=tuple(sorted(role_ids["active"])),
        holdout_case_ids=tuple(sorted(role_ids["holdout"])),
    )
    policy = policy or _policy()
    legacy = GatePreregistration(
        preregistration_id=_id(f"{plan.plan_version}:legacy-preregistration"),
        policy_fingerprint=policy.fingerprint,
        assignment_manifest_fingerprint=manifest.fingerprint,
        split_fingerprint=split.fingerprint,
        estimator_identity_fingerprint=_id(
            f"{plan.plan_version}:legacy-nonauthoritative-identity"
        ),
        registered_at=BASE + timedelta(days=6),
        metric_specs=(
            MetricGateSpec(
                metric_key=METRIC_KEY,
                label_vocabulary=("negative", "positive"),
                risk_tier=MetricRiskTier.STANDARD,
            ),
        ),
    )
    constellation = ConstellationIdentityReceipt.from_plan(
        plan,
        constellation_id=_id(f"{plan.plan_version}:constellation"),
        frozen_at=BASE + timedelta(days=5),
    )
    preregistration_v2 = GatePreregistrationV2(
        preregistration_id=_id(f"{plan.plan_version}:preregistration-v2"),
        policy_fingerprint=policy.fingerprint,
        assignment_manifest_fingerprint=manifest.fingerprint,
        split_fingerprint=split.fingerprint,
        stored_plan_fingerprint=plan.canonical_fingerprint,
        constellation_fingerprint=constellation.fingerprint,
        legacy_preregistration_fingerprint=legacy.fingerprint,
        registered_at=BASE + timedelta(days=7),
    )
    return PreregisteredEstimatorCampaign(
        campaign_id=_id(f"{plan.plan_version}:campaign"),
        stored_plan=plan,
        policy=policy,
        assignment_manifest=manifest,
        split=split,
        legacy_preregistration=legacy,
        preregistration_v2=preregistration_v2,
        constellation_identity=constellation,
        registered_at=BASE + timedelta(days=8),
    )


def _repository(tmp_path):
    database = Database(tmp_path / "private.sqlite")
    database.initialize()
    return database, database.estimator_repository()


def _create_v15_database(path) -> None:
    scripts = (_MIGRATION_1,) + tuple(
        getattr(migrations, f"MIGRATION_{version}") for version in range(2, 16)
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
                "INSERT INTO schema_migrations VALUES (?, ?, ?)",
                (
                    version,
                    hashlib.sha256(script.encode()).hexdigest(),
                    BASE.isoformat(timespec="microseconds"),
                ),
            )
            connection.execute(f"PRAGMA user_version = {version}")
            connection.commit()


def test_campaign_round_trip_is_root_last_immutable_and_idempotent(tmp_path) -> None:
    database, repository = _repository(tmp_path)
    campaign = _campaign()
    repository.register_plan(campaign.stored_plan)

    assert repository.register_preregistered_campaign(campaign) == campaign.fingerprint
    assert repository.register_preregistered_campaign(campaign) == campaign.fingerprint
    assert repository.get_preregistered_campaign(campaign.campaign_id) == campaign
    assert campaign.activation_allowed is False

    with database._connection() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE estimator_gate_campaigns SET activation_allowed = 1 WHERE campaign_id = ?",
            (campaign.campaign_id,),
        )


def test_concurrent_same_campaign_registration_has_one_sealed_root(tmp_path) -> None:
    database, repository = _repository(tmp_path)
    campaign = _campaign()
    repository.register_plan(campaign.stored_plan)

    def register() -> str:
        return database.estimator_repository().register_preregistered_campaign(
            campaign
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: register(), range(2)))
    assert results == (campaign.fingerprint, campaign.fingerprint)
    with database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_gate_campaigns"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_case_manifests_v2"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_case_assignments_v2"
        ).fetchone()[0] == len(campaign.assignment_manifest.assignments)


def test_campaign_children_are_sealed_against_direct_insert_update_delete(tmp_path) -> None:
    database, repository = _repository(tmp_path)
    campaign = _campaign()
    repository.register_plan(campaign.stored_plan)
    repository.register_preregistered_campaign(campaign)
    assignment = campaign.assignment_manifest.assignments[0]

    with database._connection() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO estimator_case_assignments_v2
            SELECT manifest_fingerprint, 999999, contract_version, ?, project_id,
                   session_revision_id, metric_key, provider, origin,
                   task_stratum, language, evidence_tier, observed_at,
                   plan_fingerprint, metric_question_fingerprint,
                   evidence_packet_fingerprint
            FROM estimator_case_assignments_v2
            WHERE manifest_fingerprint = ? AND case_id = ?
            """,
            (
                _id("sealed-extra-case"),
                campaign.assignment_manifest.fingerprint,
                assignment.case_id,
            ),
        )
    with database._connection() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "UPDATE estimator_case_assignments_v2 SET evidence_tier = 'human' WHERE manifest_fingerprint = ? AND case_id = ?",
            (campaign.assignment_manifest.fingerprint, assignment.case_id),
        )
    with database._connection() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "DELETE FROM estimator_case_assignments_v2 WHERE manifest_fingerprint = ? AND case_id = ?",
            (campaign.assignment_manifest.fingerprint, assignment.case_id),
        )


def test_campaign_requires_a_previously_stored_safe_non_synthetic_plan(tmp_path) -> None:
    database, repository = _repository(tmp_path)
    campaign = _campaign()
    with pytest.raises(DatabaseInvariantError, match="previously stored"):
        repository.register_preregistered_campaign(campaign)

    unsafe_plan = _plan(plan_version="file:reserved-secret")
    repository.register_plan(unsafe_plan)
    with pytest.raises(ValueError, match="unsafe v16 identifiers"):
        _campaign(unsafe_plan)
    with database._connection() as connection, pytest.raises(
        sqlite3.IntegrityError, match="unsafe for a v16 campaign"
    ):
        connection.execute(
            "INSERT INTO estimator_gate_safe_plan_audits VALUES (?)",
            (unsafe_plan.canonical_fingerprint,),
        )


def test_campaign_requires_one_represented_question_per_metric(tmp_path) -> None:
    database, repository = _repository(tmp_path)
    plan = _plan()
    first = plan.question_specs[0]
    second = first.model_copy(
        update={
            "metric_definition_version": "metric-v2",
            "question_version": "question-v2",
            "question_sha256": _id("question-v2"),
            "prompt_template_version": "template-v2",
            "prompt_template_sha256": _id("template-v2"),
            "rubric_version": "rubric-v2",
            "rubric_sha256": _id("rubric-v2"),
        }
    )
    duplicate_metric_plan = EstimatorPlan.model_validate(
        {
            **plan.model_dump(mode="python"),
            "plan_key": "reserved-duplicate-question-campaign",
            "plan_version": "reserved-duplicate-question-v1",
            "question_specs": (first, second),
        }
    )
    repository.register_plan(duplicate_metric_plan)
    with pytest.raises(ValueError, match="exactly one metric question"):
        _campaign(duplicate_metric_plan)
    with database._connection() as connection, pytest.raises(
        sqlite3.IntegrityError, match="unsafe for a v16 campaign"
    ):
        connection.execute(
            "INSERT INTO estimator_gate_safe_plan_audits VALUES (?)",
            (duplicate_metric_plan.canonical_fingerprint,),
        )


def test_campaign_assignment_provider_must_match_single_plan_schema() -> None:
    campaign = _campaign()
    changed = campaign.assignment_manifest.assignments[0].model_copy(
        update={"provider": Provider.CLAUDE_CODE}
    )
    manifest = CaseAssignmentManifestV2(
        manifest_id=campaign.assignment_manifest.manifest_id,
        plan_fingerprint=campaign.assignment_manifest.plan_fingerprint,
        frozen_at=campaign.assignment_manifest.frozen_at,
        assignments=tuple(
            sorted(
                (changed, *campaign.assignment_manifest.assignments[1:]),
                key=lambda item: item.case_id,
            )
        ),
    )
    with pytest.raises(ValueError, match="assignment provider"):
        PreregisteredEstimatorCampaign.model_validate(
            {
                **campaign.model_dump(mode="python"),
                "assignment_manifest": manifest,
            }
        )


def test_repository_revalidates_model_copy_bypasses_before_any_write(tmp_path) -> None:
    database, repository = _repository(tmp_path)
    campaign = _campaign()
    repository.register_plan(campaign.stored_plan)

    forged_flag = campaign.model_copy(update={"activation_allowed": True})
    with pytest.raises(ValueError):
        repository.register_preregistered_campaign(forged_flag)

    forged_nested = campaign.model_copy(
        update={
            "preregistration_v2": campaign.preregistration_v2.model_copy(
                update={"stored_plan_fingerprint": _id("forged-nested-plan")}
            )
        }
    )
    with pytest.raises(ValueError, match="v2 preregistration lineage"):
        repository.register_preregistered_campaign(forged_nested)

    with database._connection(readonly=True) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_gate_campaigns"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM estimator_case_manifests_v2"
        ).fetchone()[0] == 0


def test_campaign_rejects_negative_zero_policy_fingerprint(tmp_path) -> None:
    _, repository = _repository(tmp_path)
    policy = _policy().model_copy(update={"minimum_baseline_margin": -0.0})
    with pytest.raises(ValueError, match="negative zero"):
        _campaign(policy=policy)


def test_campaign_contract_rejects_incomplete_partition_and_wrong_lineage() -> None:
    campaign = _campaign()
    incomplete_split = campaign.split.model_copy(
        update={
            "holdout_case_ids": campaign.split.holdout_case_ids[:-1],
        }
    )
    with pytest.raises(ValueError, match="partition every manifest case"):
        PreregisteredEstimatorCampaign(
            **{
                **campaign.model_dump(),
                "split": incomplete_split,
            }
        )

    wrong_preregistration = campaign.preregistration_v2.model_copy(
        update={"stored_plan_fingerprint": _id("wrong-plan")}
    )
    with pytest.raises(ValueError, match="v2 preregistration lineage"):
        PreregisteredEstimatorCampaign(
            **{
                **campaign.model_dump(),
                "preregistration_v2": wrong_preregistration,
            }
        )

    high_risk_legacy = campaign.legacy_preregistration.model_copy(
        update={
            "metric_specs": (
                MetricGateSpec(
                    metric_key=METRIC_KEY,
                    label_vocabulary=("negative", "positive"),
                    risk_tier=MetricRiskTier.HIGH,
                    positive_label="positive",
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="high-risk policy rules"):
        PreregisteredEstimatorCampaign(
            **{
                **campaign.model_dump(),
                "legacy_preregistration": high_risk_legacy,
            }
        )


def test_migration_16_rejects_raw_sql_noncanonical_time_code_and_uri(tmp_path) -> None:
    database, repository = _repository(tmp_path)
    campaign = _campaign()
    repository.register_plan(campaign.stored_plan)
    repository.register_preregistered_campaign(campaign)

    with database._connection() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO estimator_case_assignments_v2 VALUES (
                ?, 0, 'case-assignment-v2', ?, ?, ?, ?, 'codex',
                'private_representative', 'bug_fix', 'en', 'objective',
                '2026-01-01T00:00:00Z', ?, ?, ?
            )
            """,
            (
                _id("raw-manifest"),
                _id("raw-case"),
                _id("raw-project"),
                _id("raw-revision"),
                METRIC_KEY,
                campaign.stored_plan.canonical_fingerprint,
                campaign.stored_plan.question_specs[0].canonical_fingerprint,
                _id("raw-packet"),
            ),
        )

    with database._connection() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO estimator_case_assignments_v2 VALUES (
                ?, 0, 'case-assignment-v2', ?, ?, ?, ?, 'codex',
                'private_representative', 'bug_fix', 'en', 'objective',
                '2026-02-31T00:00:00.000000+00:00', ?, ?, ?
            )
            """,
            (
                _id("invalid-calendar-manifest"),
                _id("invalid-calendar-case"),
                _id("invalid-calendar-project"),
                _id("invalid-calendar-revision"),
                METRIC_KEY,
                campaign.stored_plan.canonical_fingerprint,
                campaign.stored_plan.question_specs[0].canonical_fingerprint,
                _id("invalid-calendar-packet"),
            ),
        )


def test_migration_16_rejects_nul_and_ascii_controls_in_all_text_shapes(tmp_path) -> None:
    database, repository = _repository(tmp_path)
    campaign = _campaign()
    repository.register_plan(campaign.stored_plan)
    repository.register_preregistered_campaign(campaign)

    with database._connection() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO estimator_gate_policy_strata VALUES (?, 0, 'bug_fix')",
            (_id("nul-digest") + "\x00hidden",),
        )
    with database._connection() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO estimator_legacy_metric_labels VALUES (?, ?, 0, ?)",
            (_id("nul-label-parent"), METRIC_KEY, "valid\x00hidden"),
        )
    artifact = campaign.stored_plan.stages[2].model_artifact
    assert artifact is not None
    with database._connection() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO estimator_constellation_stages VALUES (
                ?, 3, 'constellation-stage-identity-v1',
                'embedding_retrieval', 'openai_api', ?, ?, ?, ?, ?
            )
            """,
            (
                _id("control-constellation"),
                _id("control-stage"),
                artifact.canonical_fingerprint,
                _id("control-configuration"),
                "valid\x01hidden",
                "reserved-output-v1",
            ),
        )
    with database._connection() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO estimator_case_manifests_v2 VALUES (
                ?, 'case-assignment-manifest-v2', ?, ?, ?, 1
            )
            """,
            (
                _id("control-time-manifest"),
                _id("control-time-manifest-id"),
                campaign.stored_plan.canonical_fingerprint,
                "2026-01-01T00:00:00.000000+00:00\x7f",
            ),
        )


def test_migration_16_rejects_cross_linked_question_constellation_and_policy(tmp_path) -> None:
    database, repository = _repository(tmp_path)
    first = _campaign()
    repository.register_plan(first.stored_plan)
    repository.register_preregistered_campaign(first)

    with database._connection() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute("BEGIN IMMEDIATE")
        assignment = first.assignment_manifest.assignments[0]
        fake_manifest = _id("cross-question-manifest")
        connection.execute(
            """
            INSERT INTO estimator_case_assignments_v2 VALUES (
                ?, 0, 'case-assignment-v2', ?, ?, ?, 'other_metric',
                'codex', 'private_representative', 'bug_fix', 'en',
                'objective', ?, ?, ?, ?
            )
            """,
            (
                fake_manifest,
                _id("cross-question-case"),
                assignment.project_id,
                assignment.session_revision_id,
                BASE.isoformat(timespec="microseconds"),
                first.stored_plan.canonical_fingerprint,
                first.stored_plan.question_specs[0].canonical_fingerprint,
                _id("cross-question-packet"),
            ),
        )
        connection.execute(
            "INSERT INTO estimator_case_manifests_v2 VALUES (?, 'case-assignment-manifest-v2', ?, ?, ?, 1)",
            (
                fake_manifest,
                _id("cross-question-manifest-id"),
                first.stored_plan.canonical_fingerprint,
                (BASE + timedelta(days=1)).isoformat(timespec="microseconds"),
            ),
        )

    with database._connection() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute("BEGIN IMMEDIATE")
        constellation_fingerprint = _id("cross-constellation")
        wrong_artifact = first.constellation_identity.stages[1]
        for index, expected in enumerate(first.constellation_identity.stages):
            artifact_fingerprint = (
                wrong_artifact.model_artifact_fingerprint
                if index == 0
                else expected.model_artifact_fingerprint
            )
            source = wrong_artifact.source if index == 0 else expected.source
            connection.execute(
                "INSERT INTO estimator_constellation_stages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    constellation_fingerprint,
                    expected.ordinal,
                    expected.contract_version,
                    expected.kind.value,
                    source.value,
                    _id(f"cross-constellation-stage:{index}"),
                    artifact_fingerprint,
                    expected.stage_configuration_sha256,
                    expected.component_version,
                    expected.output_schema_version,
                ),
            )
        connection.execute(
            "INSERT INTO estimator_constellations VALUES (?, 'constellation-identity-receipt-v1', ?, ?, ?, 4)",
            (
                constellation_fingerprint,
                _id("cross-constellation-id"),
                first.stored_plan.canonical_fingerprint,
                first.constellation_identity.frozen_at.isoformat(
                    timespec="microseconds"
                ),
            ),
        )

    second_policy = _policy().model_copy(
        update={
            "policy_id": _id("second-policy"),
            "maximum_cold_p95_latency_ms": 900.0,
        }
    )
    second = _campaign(_plan(plan_version="reserved-plan-v2"), policy=second_policy)
    repository.register_plan(second.stored_plan)
    repository.register_preregistered_campaign(second)
    with database._connection() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO estimator_preregistrations_v2 VALUES (
                ?, 'gate-preregistration-v2', ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                _id("cross-policy-preregistration-fingerprint"),
                _id("cross-policy-preregistration-id"),
                second.policy.fingerprint,
                first.assignment_manifest.fingerprint,
                first.split.fingerprint,
                first.stored_plan.canonical_fingerprint,
                first.constellation_identity.fingerprint,
                first.legacy_preregistration.fingerprint,
                first.preregistration_v2.registered_at.isoformat(
                    timespec="microseconds"
                ),
            ),
        )

    artifact = first.stored_plan.stages[2].model_artifact
    assert artifact is not None
    with database._connection() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO estimator_constellation_stages VALUES (
                ?, 3, 'constellation-stage-identity-v1',
                'embedding_retrieval', 'openai_api', ?, ?, ?,
                'file:reserved-path', 'reserved-output-v1'
            )
            """,
            (
                _id("raw-constellation"),
                _id("raw-stage"),
                artifact.canonical_fingerprint,
                _id("raw-stage-config"),
            ),
        )

    with database._connection() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO estimator_legacy_metric_labels VALUES (?, ?, 0, ?)
            """,
            (_id("raw-preregistration"), METRIC_KEY, "bad/control"),
        )

    policy_fingerprint = first.policy.fingerprint
    poisoned_fingerprint = _id("infinite-policy")
    with database._connection() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO estimator_gate_policy_strata SELECT ?, ordinal, task_stratum FROM estimator_gate_policy_strata WHERE policy_fingerprint = ?",
            (poisoned_fingerprint, policy_fingerprint),
        )
        connection.execute(
            "INSERT INTO estimator_gate_policy_languages SELECT ?, ordinal, language FROM estimator_gate_policy_languages WHERE policy_fingerprint = ?",
            (poisoned_fingerprint, policy_fingerprint),
        )
        connection.execute(
            "INSERT INTO estimator_gate_policy_subgroups SELECT ?, ordinal, dimension FROM estimator_gate_policy_subgroups WHERE policy_fingerprint = ?",
            (poisoned_fingerprint, policy_fingerprint),
        )
        connection.execute(
            """
            INSERT INTO estimator_gate_policies
            SELECT ?, contract_version, ?, minimum_active_learning_count,
                   maximum_active_learning_count, minimum_holdout_count,
                   minimum_holdout_per_metric, minimum_holdout_per_stratum,
                   minimum_holdout_per_language,
                   minimum_operational_samples_per_latency_class,
                   minimum_subgroup_size, minimum_baseline_margin,
                   maximum_human_gap, maximum_ece, minimum_repeat_stability,
                   minimum_selective_coverage, maximum_selective_risk,
                   false_confidence_threshold,
                   maximum_false_confident_error_rate, ?,
                   maximum_warm_p95_latency_ms, maximum_oom_rate,
                   maximum_error_rate, maximum_refusal_rate,
                   maximum_material_subgroup_regression,
                   required_strata_count, required_language_count,
                   subgroup_dimension_count, high_risk_rule_count
            FROM estimator_gate_policies WHERE policy_fingerprint = ?
            """,
            (
                poisoned_fingerprint,
                _id("infinite-policy-id"),
                float("inf"),
                policy_fingerprint,
            ),
        )


def test_campaign_privacy_delete_purges_owned_rows_and_retains_plan_policy(tmp_path) -> None:
    database, repository = _repository(tmp_path)
    campaign = _campaign()
    repository.register_plan(campaign.stored_plan)
    repository.register_preregistered_campaign(campaign)

    assert (
        repository.delete_preregistered_campaign_for_privacy(campaign.campaign_id)
        is PrivacyDeleteOutcome.DELETED_AND_PURGED
    )
    assert repository.get_preregistered_campaign(campaign.campaign_id) is None
    assert repository.get_plan(campaign.stored_plan.canonical_fingerprint) == campaign.stored_plan
    with database._connection(readonly=True) as connection:
        assert connection.execute("SELECT COUNT(*) FROM estimator_gate_policies").fetchone()[0] == 1
        for table in (
            "estimator_gate_campaigns",
            "estimator_case_manifests_v2",
            "estimator_case_assignments_v2",
            "estimator_calibration_splits",
            "estimator_calibration_split_cases",
            "estimator_legacy_preregistrations",
            "estimator_legacy_metric_specs",
            "estimator_legacy_metric_labels",
            "estimator_constellations",
            "estimator_constellation_stages",
            "estimator_preregistrations_v2",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert (
        repository.delete_preregistered_campaign_for_privacy(campaign.campaign_id)
        is PrivacyDeleteOutcome.ALREADY_ABSENT_AND_PURGED
    )


def test_campaign_delete_reports_pending_wal_purge_until_reader_closes(tmp_path) -> None:
    database, repository = _repository(tmp_path)
    campaign = _campaign()
    repository.register_plan(campaign.stored_plan)
    repository.register_preregistered_campaign(campaign)

    reader = sqlite3.connect(database.path)
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM estimator_gate_campaigns").fetchall()
        with pytest.raises(DatabaseInvariantError, match="WAL purge is pending"):
            repository.delete_preregistered_campaign_for_privacy(campaign.campaign_id)
        with pytest.raises(DatabaseInvariantError, match="revoked"):
            repository.register_preregistered_campaign(campaign)
    finally:
        reader.rollback()
        reader.close()

    assert repository.get_preregistered_campaign(campaign.campaign_id) is None
    assert (
        repository.delete_preregistered_campaign_for_privacy(campaign.campaign_id)
        is PrivacyDeleteOutcome.ALREADY_ABSENT_AND_PURGED
    )
    needles = (
        campaign.campaign_id.encode(),
        campaign.assignment_manifest.assignments[0].evidence_packet_fingerprint.encode(),
    )
    for candidate in (
        database.path,
        database.path.with_name(f"{database.path.name}-wal"),
        database.path.with_name(f"{database.path.name}-shm"),
    ):
        if candidate.exists():
            payload = candidate.read_bytes()
            assert all(needle not in payload for needle in needles)
    with pytest.raises(DatabaseInvariantError, match="revoked"):
        repository.register_preregistered_campaign(campaign)
    with database._connection(readonly=True) as connection:
        tombstone = connection.execute(
            "SELECT * FROM estimator_gate_campaign_tombstones"
        ).fetchone()
        assert set(tombstone.keys()) == {"revocation_key", "deleted_at"}
        assert tombstone["revocation_key"] != campaign.campaign_id


def test_v15_to_v16_preserves_rows_and_seals_migration_ledger(tmp_path) -> None:
    path = tmp_path / "legacy-v15.sqlite"
    expected_v15_checksum = (
        "66abea391b12fc082abfb550a2b83fb0768fb21da41b30d85ba6a1e48d444521"
    )
    assert hashlib.sha256(migrations.MIGRATION_15.encode()).hexdigest() == (
        expected_v15_checksum
    )
    _create_v15_database(path)
    installation_id = _id("preserved-installation")
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO installations VALUES (?, 'synthetic', ?)",
            (installation_id, BASE.isoformat(timespec="microseconds")),
        )
        connection.commit()

    Database(path).initialize()
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        rows = connection.execute(
            "SELECT version, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        assert [row[0] for row in rows] == list(range(1, 62))
        assert rows[14][1] == expected_v15_checksum
        assert rows[15][1] == hashlib.sha256(
            migrations.MIGRATION_16.encode()
        ).hexdigest()
        assert rows[16][1] == hashlib.sha256(
            migrations.MIGRATION_17.encode()
        ).hexdigest()
        assert rows[17][1] == hashlib.sha256(
            migrations.MIGRATION_18.encode()
        ).hexdigest()
        assert connection.execute(
            "SELECT installation_id FROM installations"
        ).fetchone()[0] == installation_id
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_schema_16_is_normalized_and_has_no_content_columns(tmp_path) -> None:
    database, _ = _repository(tmp_path)
    assert SCHEMA_VERSION == 61
    forbidden = {"json", "blob", "prompt", "excerpt", "response", "rationale", "commentary", "prose"}
    with database._connection(readonly=True) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 61
        tables = (
            "estimator_gate_policies",
            "estimator_gate_policy_strata",
            "estimator_gate_policy_languages",
            "estimator_gate_policy_subgroups",
            "estimator_gate_policy_high_risk_rules",
            "estimator_case_manifests_v2",
            "estimator_case_assignments_v2",
            "estimator_calibration_splits",
            "estimator_calibration_split_cases",
            "estimator_legacy_preregistrations",
            "estimator_legacy_metric_specs",
            "estimator_legacy_metric_labels",
            "estimator_constellations",
            "estimator_constellation_stages",
            "estimator_preregistrations_v2",
            "estimator_gate_campaigns",
            "estimator_gate_campaign_tombstones",
        )
        for table in tables:
            columns = connection.execute(f"PRAGMA table_info({table})").fetchall()
            for column in columns:
                assert column["type"].upper() != "BLOB"
                assert not any(token in column["name"].lower() for token in forbidden)
