"""Repository-owned v19 calibration report derivation and persistence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import json
from typing import NoReturn

from ...application.estimators.calibration_report_contracts import (
    CALIBRATION_MEASUREMENT_SPECS,
    FIXED_CALIBRATION_REPORT_DEFINITION,
    CalibrationAgreementReceiptV1,
    CalibrationClassReceiptV1,
    CalibrationComparisonIdentityV1,
    CalibrationConfusionCellV1,
    CalibrationMeasurementV1,
    CalibrationMeasurementSpecV1,
    CalibrationMetricReportV1,
    CalibrationMissingnessReceiptV1,
    CalibrationReliabilityBinV1,
    CalibrationReportDefinitionV1,
    CalibrationReportScopeV1,
    CalibrationResourceReceiptV1,
    CalibrationSelectivePointV1,
    CalibrationStabilityReceiptV1,
    UntrustedCalibrationReportV1,
)
from ...application.estimators.calibration_report_persistence import (
    CalibrationReportRepository,
    RepositorySealedCalibrationReportV1,
    repository_calibration_receipt_id,
    revalidate_repository_sealed_calibration_report_v1,
)
from ...application.estimators.calibration_reporting import (
    UntrustedCalibrationProjectionV1,
    derive_untrusted_calibration_report,
)
from ...database import DatabaseInvariantError
from ._common import ConnectionScope, require_safe_id
from .estimators import SqliteEstimatorRepository, _contract_fingerprint


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _to_epoch_us(value: datetime) -> int:
    delta = value - _EPOCH
    return (
        delta.days * 86_400_000_000
        + delta.seconds * 1_000_000
        + delta.microseconds
    )


def _from_epoch_us(value: int) -> datetime:
    return _EPOCH + timedelta(microseconds=int(value))


def _row_fingerprint(value) -> str:
    return _contract_fingerprint(value)


class SqliteCalibrationReportRepository(CalibrationReportRepository):
    """Derive, seal, and recursively verify normalized calibration reports."""

    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
        *,
        begin_write_authorization: (
            Callable[[str, str, str], tuple[str, str]] | None
        ) = None,
        end_write_authorization: (
            Callable[[str, str, str, str, str], None] | None
        ) = None,
        clock: Callable[[], datetime] | None = None,
        fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized
        self._begin_write_authorization = begin_write_authorization
        self._end_write_authorization = end_write_authorization
        self._clock = clock or (lambda: datetime.now(UTC))
        self._fault_hook = fault_hook
        # These connection-aware hydrators perform full v16/v17 reconstruction
        # and static lineage verification.  No separate connection is opened.
        self._estimator_hydrator = SqliteEstimatorRepository(
            connection_scope, ensure_initialized
        )

    @staticmethod
    def _conflict(message: str) -> NoReturn:
        raise DatabaseInvariantError(message)

    def _fault(self, stage: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(stage)

    def derive_calibration_report(
        self, submission_id: str
    ) -> RepositorySealedCalibrationReportV1:
        """Derive from one sealed v17 submission; no caller report or clock."""

        self._ensure_initialized()
        require_safe_id(submission_id)
        if (
            self._begin_write_authorization is None
            or self._end_write_authorization is None
        ):
            self._conflict("calibration report repository authority is unavailable")

        authorization: tuple[str, str] | None = None
        authority_lineage: tuple[str, str, str] | None = None
        try:
            with self._connection_scope() as connection:
                try:
                    connection.execute("PRAGMA trusted_schema = ON")
                    connection.execute("BEGIN IMMEDIATE")
                    existing = connection.execute(
                        """
                        SELECT d.report_id
                        FROM estimator_calibration_report_drafts d
                        JOIN estimator_calibration_report_roots r
                          ON r.report_id=d.report_id
                        WHERE d.submission_id=?
                        """,
                        (submission_id,),
                    ).fetchone()
                    if existing is not None:
                        receipt = self._hydrate_and_rederive(
                            connection, existing["report_id"]
                        )
                        connection.commit()
                        return receipt
                    dangling = connection.execute(
                        "SELECT 1 FROM estimator_calibration_report_drafts WHERE submission_id=?",
                        (submission_id,),
                    ).fetchone()
                    if dangling is not None:
                        self._conflict("calibration report storage is incompletely sealed")

                    evidence_row = connection.execute(
                        """
                        SELECT submission_id,campaign_id,submission_fingerprint
                        FROM estimator_evidence_submissions WHERE submission_id=?
                        """,
                        (submission_id,),
                    ).fetchone()
                    if evidence_row is None:
                        self._conflict(
                            "sealed calibration evidence submission is missing"
                        )
                    campaign = self._estimator_hydrator._hydrate_preregistered_campaign(
                        connection, evidence_row["campaign_id"]
                    )
                    submission = self._estimator_hydrator._hydrate_calibration_evidence_submission(
                        connection, submission_id
                    )
                    if submission.fingerprint != evidence_row["submission_fingerprint"]:
                        self._conflict("sealed submission fingerprint is inconsistent")

                    derived_at = self._clock()
                    if (
                        derived_at.tzinfo is None
                        or derived_at.utcoffset() != timedelta(0)
                    ):
                        raise ValueError("repository calibration clock must return UTC")
                    projection = UntrustedCalibrationProjectionV1(
                        campaign=campaign,
                        submission=submission,
                        source_observed_at=derived_at,
                    )
                    report = derive_untrusted_calibration_report(projection)
                    receipt = revalidate_repository_sealed_calibration_report_v1(
                        RepositorySealedCalibrationReportV1(
                            receipt_id=repository_calibration_receipt_id(
                                report.fingerprint, derived_at
                            ),
                            report=report,
                            report_fingerprint=report.fingerprint,
                            definition_fingerprint=report.definition.fingerprint,
                            metric_report_fingerprints=tuple(
                                item.fingerprint for item in report.metric_reports
                            ),
                            derived_at=derived_at,
                        )
                    )
                    authority_lineage = (
                        report.report_id,
                        submission_id,
                        campaign.campaign_id,
                    )
                    authorization = self._begin_write_authorization(
                        *authority_lineage
                    )
                    connection.execute(
                        "INSERT INTO estimator_calibration_report_append_authorizations VALUES (?,?,?,?,?)",
                        (
                            authorization[0],
                            report.report_id,
                            submission_id,
                            campaign.campaign_id,
                            authorization[1],
                        ),
                    )
                    self._insert_report(connection, receipt)
                    self._fault("after_children")
                    self._insert_roots(connection, receipt)
                    self._fault("after_root")
                    hydrated = self._hydrate_and_rederive(
                        connection, report.report_id
                    )
                    if hydrated != receipt:
                        self._conflict(
                            "calibration report differs after relational hydration"
                        )
                    connection.execute(
                        "DELETE FROM estimator_calibration_report_append_authorizations WHERE operation_id=?",
                        (authorization[0],),
                    )
                    self._fault("before_commit")
                    connection.commit()
                    return hydrated
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    connection.execute("PRAGMA trusted_schema = OFF")
        finally:
            if (
                authorization is not None
                and authority_lineage is not None
                and self._end_write_authorization is not None
            ):
                self._end_write_authorization(
                    authorization[0],
                    *authority_lineage,
                    authorization[1],
                )

    def get_calibration_report_for_submission(
        self, submission_id: str
    ) -> RepositorySealedCalibrationReportV1 | None:
        self._ensure_initialized()
        require_safe_id(submission_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """
                SELECT d.report_id FROM estimator_calibration_report_drafts d
                JOIN estimator_calibration_report_roots r ON r.report_id=d.report_id
                WHERE d.submission_id=?
                """,
                (submission_id,),
            ).fetchone()
            if row is None:
                dangling = connection.execute(
                    "SELECT 1 FROM estimator_calibration_report_drafts WHERE submission_id=?",
                    (submission_id,),
                ).fetchone()
                if dangling is not None:
                    self._conflict("calibration report storage is incompletely sealed")
                return None
            return self._hydrate_and_rederive(connection, row["report_id"])

    @staticmethod
    def _insert_report(connection, receipt: RepositorySealedCalibrationReportV1) -> None:
        report = receipt.report
        rid = report.report_id
        connection.execute(
            """
            INSERT INTO estimator_calibration_report_drafts VALUES (
              ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )
            """,
            (
                rid,
                report.contract_version,
                report.campaign_id,
                report.campaign_fingerprint,
                report.submission_id,
                report.submission_fingerprint,
                report.stored_plan_fingerprint,
                report.policy_fingerprint,
                report.assignment_manifest_fingerprint,
                report.split_fingerprint,
                report.preregistration_fingerprint,
                report.preregistration_v2_fingerprint,
                report.constellation_fingerprint,
                report.source_bundle_fingerprint,
                report.definition.fingerprint,
                report.state.value,
                _to_epoch_us(report.source_observed_at),
                None,
                report.fingerprint,
                len(report.metric_reports),
                0,
                "untrusted_projection",
                0,
                0,
                0,
                0,
            ),
        )
        for metric_ordinal, metric in enumerate(report.metric_reports):
            SqliteCalibrationReportRepository._insert_metric(
                connection, rid, metric_ordinal, metric
            )

    @staticmethod
    def _insert_metric(connection, rid: str, ordinal: int, metric) -> None:
        key = metric.metric_key
        connection.execute(
            """INSERT INTO estimator_calibration_report_metric_drafts
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rid,
                ordinal,
                key,
                metric.contract_version,
                metric.value_kind,
                metric.state.value,
                metric.fingerprint,
                len(metric.label_vocabulary),
                len(metric.scopes),
                len(metric.measurements),
                len(metric.confusion_cells),
                len(metric.class_receipts),
                len(metric.reliability_bins),
                len(metric.selective_points),
                len(metric.agreement_receipts),
                len(metric.stability_receipts),
                len(metric.resource_receipt.measurement_keys),
                len(metric.missingness),
                0,
                0,
            ),
        )
        identity = metric.comparison_identity
        connection.execute(
            """INSERT INTO estimator_calibration_report_comparison_identities
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                rid,
                key,
                identity.contract_version,
                identity.metric_semantics_fingerprint,
                identity.evidence_scope_fingerprint,
                identity.pipeline_fingerprint,
                identity.gate_policy_fingerprint,
                identity.threshold_policy_fingerprint,
                identity.split_fingerprint,
                identity.submission_fingerprint,
                identity.served_runtime_identity_fingerprint,
                identity.measurement_provenance_fingerprint,
                identity.report_definition_fingerprint,
                identity.estimator_configuration_fingerprint,
                identity.constellation_fingerprint,
                identity.comparison_family_fingerprint,
                identity.observation_identity_fingerprint,
                identity.observation_source_fingerprint,
                0,
            ),
        )
        connection.executemany(
            "INSERT INTO estimator_calibration_report_label_vocabulary VALUES (?,?,?,?)",
            ((rid, key, index, value) for index, value in enumerate(metric.label_vocabulary)),
        )
        connection.executemany(
            "INSERT INTO estimator_calibration_report_scopes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                (
                    rid,
                    key,
                    index,
                    item.scope_id,
                    item.contract_version,
                    item.dimension.value,
                    item.bucket_code,
                    item.case_count,
                    item.minimum_required_count,
                    item.state.value,
                    item.reason_code,
                    item.fingerprint,
                )
                for index, item in enumerate(metric.scopes)
            ),
        )
        connection.executemany(
            "INSERT INTO estimator_calibration_report_measurements VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                (
                    rid,
                    key,
                    index,
                    item.scope_id,
                    item.measurement_key,
                    item.contract_version,
                    item.family.value,
                    item.shape.value,
                    item.unit_code,
                    item.state.value,
                    item.scalar_value,
                    item.integer_value,
                    item.numerator,
                    item.denominator,
                    item.sample_count,
                    item.reason_code,
                    item.fingerprint,
                )
                for index, item in enumerate(metric.measurements)
            ),
        )
        connection.executemany(
            "INSERT INTO estimator_calibration_report_confusion_cells VALUES (?,?,?,?,?,?,?,?,?)",
            (
                (rid, key, index, item.scope_id, item.truth_label, item.predicted_label, item.contract_version, item.count, _row_fingerprint(item))
                for index, item in enumerate(metric.confusion_cells)
            ),
        )
        connection.executemany(
            "INSERT INTO estimator_calibration_report_class_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                (rid, key, index, item.scope_id, item.label_code, item.contract_version, item.support, item.predicted_count, item.true_positive, item.false_positive, item.false_negative, item.precision, item.recall, item.f1, _row_fingerprint(item))
                for index, item in enumerate(metric.class_receipts)
            ),
        )
        connection.executemany(
            "INSERT INTO estimator_calibration_report_reliability_bins VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                (rid, key, index, item.scope_id, item.bin_index, item.contract_version, item.lower_bound, item.upper_bound, item.count, item.mean_confidence, item.accuracy, item.absolute_gap, _row_fingerprint(item))
                for index, item in enumerate(metric.reliability_bins)
            ),
        )
        connection.executemany(
            "INSERT INTO estimator_calibration_report_selective_points VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                (rid, key, index, item.scope_id, item.threshold, item.contract_version, item.state.value, item.coverage_numerator, item.coverage_denominator, item.risk_numerator, item.risk_denominator, item.reason_code, _row_fingerprint(item))
                for index, item in enumerate(metric.selective_points)
            ),
        )
        connection.executemany(
            "INSERT INTO estimator_calibration_report_agreement_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                (rid, key, index, item.contract_version, item.kind.value, item.state.value, item.case_count, item.pair_count, item.match_count, item.observed_agreement, item.cohen_kappa, item.reason_code, _row_fingerprint(item))
                for index, item in enumerate(metric.agreement_receipts)
            ),
        )
        connection.executemany(
            "INSERT INTO estimator_calibration_report_stability_receipts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                (rid, key, index, item.contract_version, item.condition.value, item.state.value, item.case_count, item.pair_count, item.match_count, item.stability, item.reason_code, _row_fingerprint(item))
                for index, item in enumerate(metric.stability_receipts)
            ),
        )
        resource = metric.resource_receipt
        connection.execute(
            "INSERT INTO estimator_calibration_report_resource_receipts VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rid, key, resource.contract_version, resource.attempt_count, resource.observed_usage_count, resource.observed_resource_count, resource.observed_cost_count, resource.terminal_state_count, len(resource.measurement_keys), _row_fingerprint(resource)),
        )
        connection.executemany(
            "INSERT INTO estimator_calibration_report_resource_keys VALUES (?,?,?,?)",
            ((rid, key, index, value) for index, value in enumerate(resource.measurement_keys)),
        )
        connection.executemany(
            "INSERT INTO estimator_calibration_report_missingness VALUES (?,?,?,?,?,?,?,?,?)",
            (
                (rid, key, index, item.measurement_key, item.contract_version, item.state.value, item.affected_count, item.reason_code, _row_fingerprint(item))
                for index, item in enumerate(metric.missingness)
            ),
        )

    @staticmethod
    def _insert_roots(connection, receipt: RepositorySealedCalibrationReportV1) -> None:
        report = receipt.report
        for ordinal, metric in enumerate(report.metric_reports):
            connection.execute(
                "INSERT INTO estimator_calibration_report_metric_roots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    report.report_id,
                    metric.metric_key,
                    ordinal,
                    "repository-sealed-calibration-metric-root-v1",
                    metric.fingerprint,
                    metric.comparison_identity.observation_identity_fingerprint,
                    len(metric.label_vocabulary),
                    len(metric.scopes),
                    len(metric.measurements),
                    len(metric.confusion_cells),
                    len(metric.class_receipts),
                    len(metric.reliability_bins),
                    len(metric.selective_points),
                    len(metric.agreement_receipts),
                    len(metric.stability_receipts),
                    len(metric.resource_receipt.measurement_keys),
                    len(metric.missingness),
                ),
            )
        connection.execute(
            "INSERT INTO estimator_calibration_report_roots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                report.report_id,
                receipt.contract_version,
                receipt.receipt_id,
                report.fingerprint,
                report.definition.fingerprint,
                len(report.metric_reports),
                _to_epoch_us(receipt.derived_at),
                receipt.fingerprint,
                1,
                1,
                "repository_sealed",
                0,
                0,
                0,
                0,
            ),
        )

    @staticmethod
    def _assert_ordinals(rows, label: str) -> None:
        if tuple(row["ordinal"] for row in rows) != tuple(range(len(rows))):
            raise DatabaseInvariantError(f"{label} ordinals are not contiguous")

    @staticmethod
    def _assert_fingerprint(value, stored: str, label: str) -> None:
        if _row_fingerprint(value) != stored:
            raise DatabaseInvariantError(f"{label} fingerprint is not reproducible")

    def _hydrate_definition(self, connection) -> CalibrationReportDefinitionV1:
        fingerprint = FIXED_CALIBRATION_REPORT_DEFINITION.fingerprint
        row = connection.execute(
            "SELECT * FROM estimator_calibration_report_definitions WHERE definition_fingerprint=?",
            (fingerprint,),
        ).fetchone()
        if row is None:
            self._conflict("fixed calibration report definition is missing")
        thresholds = connection.execute(
            "SELECT * FROM estimator_calibration_report_selective_thresholds WHERE definition_fingerprint=? ORDER BY ordinal",
            (fingerprint,),
        ).fetchall()
        ks = connection.execute(
            "SELECT * FROM estimator_calibration_report_retrieval_ks WHERE definition_fingerprint=? ORDER BY ordinal",
            (fingerprint,),
        ).fetchall()
        specs = connection.execute(
            "SELECT * FROM estimator_calibration_report_measurement_specs WHERE definition_fingerprint=? ORDER BY ordinal",
            (fingerprint,),
        ).fetchall()
        self._assert_ordinals(thresholds, "calibration threshold")
        self._assert_ordinals(ks, "calibration retrieval k")
        self._assert_ordinals(specs, "calibration measurement vocabulary")
        definition = CalibrationReportDefinitionV1(
            contract_version=row["contract_version"],
            definition_version=row["definition_version"],
            classification_version=row["classification_version"],
            confidence_calibration_version=row["confidence_calibration_version"],
            truth_resolution_version=row["truth_resolution_version"],
            human_pairing_version=row["human_pairing_version"],
            slice_version=row["slice_version"],
            time_bucket_version=row["time_bucket_version"],
            quantile_version=row["quantile_version"],
            reliability_bin_count=row["reliability_bin_count"],
            selective_thresholds=tuple(item["threshold"] for item in thresholds),
            retrieval_ks=tuple(item["retrieval_k"] for item in ks),
            full_probability_vector_required=bool(row["full_probability_vector_required"]),
            false_confidence_threshold_source=row["false_confidence_threshold_source"],
            minimum_slice_size_source=row["minimum_slice_size_source"],
            activation_allowed=bool(row["activation_allowed"]),
        )
        actual_specs = tuple(
            CalibrationMeasurementSpecV1(
                contract_version=item["contract_version"],
                measurement_key=item["measurement_key"],
                family=item["family"],
                shape=item["shape"],
                unit_code=item["unit_code"],
            )
            for item in specs
        )
        if (
            definition != FIXED_CALIBRATION_REPORT_DEFINITION
            or actual_specs != CALIBRATION_MEASUREMENT_SPECS
            or any(
                value.fingerprint != item["spec_fingerprint"]
                for value, item in zip(actual_specs, specs, strict=True)
            )
            or row["selective_threshold_count"] != len(thresholds)
            or row["retrieval_k_count"] != len(ks)
        ):
            self._conflict("fixed calibration report definition is not reproducible")
        return definition

    def _hydrate_and_rederive(
        self, connection, report_id: str
    ) -> RepositorySealedCalibrationReportV1:
        draft = connection.execute(
            "SELECT * FROM estimator_calibration_report_drafts WHERE report_id=?",
            (report_id,),
        ).fetchone()
        root = connection.execute(
            "SELECT * FROM estimator_calibration_report_roots WHERE report_id=?",
            (report_id,),
        ).fetchone()
        if draft is None or root is None:
            self._conflict("sealed calibration report root is missing")
        definition = self._hydrate_definition(connection)
        metric_rows = connection.execute(
            "SELECT * FROM estimator_calibration_report_metric_drafts WHERE report_id=? ORDER BY metric_ordinal",
            (report_id,),
        ).fetchall()
        if tuple(item["metric_ordinal"] for item in metric_rows) != tuple(range(len(metric_rows))):
            self._conflict("calibration metric ordinals are not contiguous")
        metrics = tuple(
            self._hydrate_metric(connection, report_id, item) for item in metric_rows
        )
        report = UntrustedCalibrationReportV1(
            contract_version=draft["contract_version"],
            report_id=draft["report_id"],
            campaign_id=draft["campaign_id"],
            campaign_fingerprint=draft["campaign_fingerprint"],
            submission_id=draft["submission_id"],
            submission_fingerprint=draft["submission_fingerprint"],
            stored_plan_fingerprint=draft["stored_plan_fingerprint"],
            policy_fingerprint=draft["policy_fingerprint"],
            assignment_manifest_fingerprint=draft["assignment_manifest_fingerprint"],
            split_fingerprint=draft["split_fingerprint"],
            preregistration_fingerprint=draft["preregistration_fingerprint"],
            preregistration_v2_fingerprint=draft["preregistration_v2_fingerprint"],
            constellation_fingerprint=draft["constellation_fingerprint"],
            source_bundle_fingerprint=draft["source_bundle_fingerprint"],
            definition=definition,
            state=draft["state"],
            metric_reports=metrics,
            source_observed_at=_from_epoch_us(draft["source_observed_at_us"]),
        )
        if (
            report.fingerprint != draft["report_fingerprint"]
            or report.fingerprint != root["report_fingerprint"]
            or len(metrics) != draft["metric_count"]
            or len(metrics) != root["metric_count"]
            or definition.fingerprint != draft["definition_fingerprint"]
            or definition.fingerprint != root["definition_fingerprint"]
            or draft["derived_at_us"] is not None
            or draft["source_observed_at_us"] != root["derived_at_us"]
            or (
                draft["repository_owned"],
                draft["persistence_state"],
                draft["comparison_allowed"],
                draft["activation_allowed"],
                draft["private_export_allowed"],
                draft["team_share_allowed"],
            ) != (0, "untrusted_projection", 0, 0, 0, 0)
        ):
            self._conflict("calibration report root is not reproducible")
        metric_roots = connection.execute(
            "SELECT * FROM estimator_calibration_report_metric_roots WHERE report_id=? ORDER BY metric_ordinal",
            (report_id,),
        ).fetchall()
        if len(metric_roots) != len(metrics):
            self._conflict("calibration metric roots are incomplete")
        for ordinal, (metric, stored_metric, metric_draft) in enumerate(
            zip(metrics, metric_roots, metric_rows, strict=True)
        ):
            expected_counts = (
                len(metric.label_vocabulary), len(metric.scopes), len(metric.measurements),
                len(metric.confusion_cells), len(metric.class_receipts), len(metric.reliability_bins),
                len(metric.selective_points), len(metric.agreement_receipts), len(metric.stability_receipts),
                len(metric.resource_receipt.measurement_keys), len(metric.missingness),
            )
            stored_counts = tuple(
                stored_metric[column]
                for column in (
                    "vocabulary_count", "scope_count", "measurement_count", "confusion_count", "class_count",
                    "reliability_count", "selective_count", "agreement_count", "stability_count", "resource_key_count", "missingness_count",
                )
            )
            draft_counts = tuple(
                metric_draft[column]
                for column in (
                    "vocabulary_count", "scope_count", "measurement_count", "confusion_count", "class_count",
                    "reliability_count", "selective_count", "agreement_count", "stability_count", "resource_key_count", "missingness_count",
                )
            )
            if (
                stored_metric["metric_ordinal"] != ordinal
                or stored_metric["metric_key"] != metric.metric_key
                or stored_metric["metric_fingerprint"] != metric.fingerprint
                or metric_draft["metric_fingerprint"] != metric.fingerprint
                or stored_metric["comparison_identity_fingerprint"]
                != metric.comparison_identity.observation_identity_fingerprint
                or expected_counts != stored_counts
                or expected_counts != draft_counts
            ):
                self._conflict("calibration metric root is not reproducible")
        receipt = revalidate_repository_sealed_calibration_report_v1(
            RepositorySealedCalibrationReportV1(
                contract_version=root["contract_version"],
                receipt_id=root["receipt_id"],
                report=report,
                report_fingerprint=root["report_fingerprint"],
                definition_fingerprint=root["definition_fingerprint"],
                metric_report_fingerprints=tuple(item.fingerprint for item in metrics),
                derived_at=_from_epoch_us(root["derived_at_us"]),
                repository_owned=bool(root["repository_owned"]),
                repository_sealed=bool(root["repository_sealed"]),
                persistence_state=root["persistence_state"],
                comparison_allowed=bool(root["comparison_allowed"]),
                activation_allowed=bool(root["activation_allowed"]),
                private_export_allowed=bool(root["private_export_allowed"]),
                team_share_allowed=bool(root["team_share_allowed"]),
            )
        )
        if receipt.fingerprint != root["receipt_fingerprint"]:
            self._conflict("calibration report receipt fingerprint is not reproducible")
        campaign = self._estimator_hydrator._hydrate_preregistered_campaign(
            connection, report.campaign_id
        )
        submission = self._estimator_hydrator._hydrate_calibration_evidence_submission(
            connection, report.submission_id
        )
        expected = derive_untrusted_calibration_report(
            UntrustedCalibrationProjectionV1(
                campaign=campaign,
                submission=submission,
                source_observed_at=receipt.derived_at,
            )
        )
        if expected != report:
            self._conflict("persisted calibration report math is not reproducible")
        return receipt

    def _hydrate_metric(self, connection, report_id: str, root) -> CalibrationMetricReportV1:
        key = root["metric_key"]
        identity_row = connection.execute(
            "SELECT * FROM estimator_calibration_report_comparison_identities WHERE report_id=? AND metric_key=?",
            (report_id, key),
        ).fetchone()
        if identity_row is None:
            self._conflict("calibration comparison identity is missing")
        identity = CalibrationComparisonIdentityV1(
            **{
                field: identity_row[field]
                for field in CalibrationComparisonIdentityV1.model_fields
                if field != "comparison_allowed"
            },
            comparison_allowed=bool(identity_row["comparison_allowed"]),
        )
        for column, actual in (
            ("comparison_family_fingerprint", identity.comparison_family_fingerprint),
            ("observation_identity_fingerprint", identity.observation_identity_fingerprint),
            ("observation_source_fingerprint", identity.observation_source_fingerprint),
        ):
            if identity_row[column] != actual:
                self._conflict("calibration comparison identity is not reproducible")
        vocabulary = connection.execute(
            "SELECT * FROM estimator_calibration_report_label_vocabulary WHERE report_id=? AND metric_key=? ORDER BY ordinal",
            (report_id, key),
        ).fetchall()
        scopes = connection.execute(
            "SELECT * FROM estimator_calibration_report_scopes WHERE report_id=? AND metric_key=? ORDER BY ordinal",
            (report_id, key),
        ).fetchall()
        measurements = connection.execute(
            "SELECT * FROM estimator_calibration_report_measurements WHERE report_id=? AND metric_key=? ORDER BY ordinal",
            (report_id, key),
        ).fetchall()
        confusion = connection.execute(
            "SELECT * FROM estimator_calibration_report_confusion_cells WHERE report_id=? AND metric_key=? ORDER BY ordinal",
            (report_id, key),
        ).fetchall()
        classes = connection.execute(
            "SELECT * FROM estimator_calibration_report_class_receipts WHERE report_id=? AND metric_key=? ORDER BY ordinal",
            (report_id, key),
        ).fetchall()
        bins = connection.execute(
            "SELECT * FROM estimator_calibration_report_reliability_bins WHERE report_id=? AND metric_key=? ORDER BY ordinal",
            (report_id, key),
        ).fetchall()
        selective = connection.execute(
            "SELECT * FROM estimator_calibration_report_selective_points WHERE report_id=? AND metric_key=? ORDER BY ordinal",
            (report_id, key),
        ).fetchall()
        agreements = connection.execute(
            "SELECT * FROM estimator_calibration_report_agreement_receipts WHERE report_id=? AND metric_key=? ORDER BY ordinal",
            (report_id, key),
        ).fetchall()
        stability = connection.execute(
            "SELECT * FROM estimator_calibration_report_stability_receipts WHERE report_id=? AND metric_key=? ORDER BY ordinal",
            (report_id, key),
        ).fetchall()
        resource_row = connection.execute(
            "SELECT * FROM estimator_calibration_report_resource_receipts WHERE report_id=? AND metric_key=?",
            (report_id, key),
        ).fetchone()
        resource_keys = connection.execute(
            "SELECT * FROM estimator_calibration_report_resource_keys WHERE report_id=? AND metric_key=? ORDER BY ordinal",
            (report_id, key),
        ).fetchall()
        missing = connection.execute(
            "SELECT * FROM estimator_calibration_report_missingness WHERE report_id=? AND metric_key=? ORDER BY ordinal",
            (report_id, key),
        ).fetchall()
        for rows, label in (
            (vocabulary, "label vocabulary"), (scopes, "scope"), (measurements, "measurement"),
            (confusion, "confusion"), (classes, "class receipt"), (bins, "reliability bin"),
            (selective, "selective point"), (agreements, "agreement"), (stability, "stability"),
            (resource_keys, "resource key"), (missing, "missingness"),
        ):
            self._assert_ordinals(rows, label)
        if resource_row is None:
            self._conflict("calibration resource receipt is missing")

        scope_values = tuple(
            CalibrationReportScopeV1(
                contract_version=row["contract_version"], scope_id=row["scope_id"], metric_key=key,
                dimension=row["dimension"], bucket_code=row["bucket_code"], case_count=row["case_count"],
                minimum_required_count=row["minimum_required_count"], state=row["state"], reason_code=row["reason_code"],
            ) for row in scopes
        )
        for value, row in zip(scope_values, scopes, strict=True):
            self._assert_fingerprint(value, row["scope_fingerprint"], "calibration scope")
        measurement_values = tuple(
            CalibrationMeasurementV1(
                contract_version=row["contract_version"], scope_id=row["scope_id"], measurement_key=row["measurement_key"],
                family=row["family"], shape=row["shape"], unit_code=row["unit_code"], state=row["state"],
                scalar_value=row["scalar_value"], integer_value=row["integer_value"], numerator=row["numerator"],
                denominator=row["denominator"], sample_count=row["sample_count"], reason_code=row["reason_code"],
            ) for row in measurements
        )
        for value, row in zip(measurement_values, measurements, strict=True):
            self._assert_fingerprint(value, row["measurement_fingerprint"], "calibration measurement")
        confusion_values = tuple(
            CalibrationConfusionCellV1(contract_version=row["contract_version"], scope_id=row["scope_id"], truth_label=row["truth_label"], predicted_label=row["predicted_label"], count=row["count"])
            for row in confusion
        )
        class_values = tuple(
            CalibrationClassReceiptV1(contract_version=row["contract_version"], scope_id=row["scope_id"], label_code=row["label_code"], support=row["support"], predicted_count=row["predicted_count"], true_positive=row["true_positive"], false_positive=row["false_positive"], false_negative=row["false_negative"], precision=row["precision"], recall=row["recall"], f1=row["f1"])
            for row in classes
        )
        bin_values = tuple(
            CalibrationReliabilityBinV1(contract_version=row["contract_version"], scope_id=row["scope_id"], bin_index=row["bin_index"], lower_bound=row["lower_bound"], upper_bound=row["upper_bound"], count=row["count"], mean_confidence=row["mean_confidence"], accuracy=row["accuracy"], absolute_gap=row["absolute_gap"])
            for row in bins
        )
        selective_values = tuple(
            CalibrationSelectivePointV1(contract_version=row["contract_version"], scope_id=row["scope_id"], threshold=row["threshold"], state=row["state"], coverage_numerator=row["coverage_numerator"], coverage_denominator=row["coverage_denominator"], risk_numerator=row["risk_numerator"], risk_denominator=row["risk_denominator"], reason_code=row["reason_code"])
            for row in selective
        )
        agreement_values = tuple(
            CalibrationAgreementReceiptV1(contract_version=row["contract_version"], metric_key=key, kind=row["kind"], state=row["state"], case_count=row["case_count"], pair_count=row["pair_count"], match_count=row["match_count"], observed_agreement=row["observed_agreement"], cohen_kappa=row["cohen_kappa"], reason_code=row["reason_code"])
            for row in agreements
        )
        stability_values = tuple(
            CalibrationStabilityReceiptV1(contract_version=row["contract_version"], metric_key=key, condition=row["condition"], state=row["state"], case_count=row["case_count"], pair_count=row["pair_count"], match_count=row["match_count"], stability=row["stability"], reason_code=row["reason_code"])
            for row in stability
        )
        resource = CalibrationResourceReceiptV1(
            contract_version=resource_row["contract_version"], metric_key=key,
            attempt_count=resource_row["attempt_count"], observed_usage_count=resource_row["observed_usage_count"],
            observed_resource_count=resource_row["observed_resource_count"], observed_cost_count=resource_row["observed_cost_count"],
            terminal_state_count=resource_row["terminal_state_count"], measurement_keys=tuple(row["measurement_key"] for row in resource_keys),
        )
        missing_values = tuple(
            CalibrationMissingnessReceiptV1(contract_version=row["contract_version"], metric_key=key, measurement_key=row["measurement_key"], state=row["state"], affected_count=row["affected_count"], reason_code=row["reason_code"])
            for row in missing
        )
        for values, rows, label in (
            (confusion_values, confusion, "confusion cell"), (class_values, classes, "class receipt"),
            (bin_values, bins, "reliability bin"), (selective_values, selective, "selective point"),
            (agreement_values, agreements, "agreement receipt"), (stability_values, stability, "stability receipt"),
            (missing_values, missing, "missingness receipt"),
        ):
            for value, row in zip(values, rows, strict=True):
                self._assert_fingerprint(value, row["row_fingerprint"], label)
        self._assert_fingerprint(resource, resource_row["row_fingerprint"], "resource receipt")
        if len(resource.measurement_keys) != resource_row["measurement_key_count"]:
            self._conflict("resource receipt key count is inconsistent")

        metric = CalibrationMetricReportV1(
            contract_version=root["contract_version"], metric_key=key, value_kind=root["value_kind"],
            label_vocabulary=tuple(row["label_code"] for row in vocabulary), comparison_identity=identity,
            state=root["state"], scopes=scope_values, measurements=measurement_values,
            confusion_cells=confusion_values, class_receipts=class_values, reliability_bins=bin_values,
            selective_points=selective_values, agreement_receipts=agreement_values,
            stability_receipts=stability_values, resource_receipt=resource, missingness=missing_values,
            comparison_allowed=bool(root["comparison_allowed"]), activation_allowed=bool(root["activation_allowed"]),
        )
        if metric.fingerprint != root["metric_fingerprint"]:
            self._conflict("calibration metric report fingerprint is not reproducible")
        return metric


__all__ = ["SqliteCalibrationReportRepository"]
