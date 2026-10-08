"""Repository-sealed v20 gate decisions over sealed calibration lineage."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import secrets
from typing import NoReturn

from ...application.estimators.gate_decision_contracts import (
    FIXED_GATE_DECISION_DEFINITION,
    GateDecisionCheckV1,
    GateDecisionDefinitionV1,
    GateDecisionRepository,
    GateDecisionValueV1,
    RepositorySealedGateDecisionV1,
    canonical_payload_digest,
    revalidate_repository_sealed_gate_decision_v1,
)
from ...application.estimators.gate_decision_evaluation import (
    derive_repository_sealed_gate_decision_v1,
)
from ...database import DatabaseInvariantError
from ._common import ConnectionScope, require_safe_id
from .calibration_reports import SqliteCalibrationReportRepository
from .estimators import SqliteEstimatorRepository, _contract_fingerprint


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _to_epoch_us(value: datetime) -> int:
    delta = value - _EPOCH
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds


def _from_epoch_us(value: int) -> datetime:
    return _EPOCH + timedelta(microseconds=int(value))


class SqliteGateDecisionRepository(GateDecisionRepository):
    """Derive once, persist root last, and rederive before every return."""

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
        self._estimator_hydrator = SqliteEstimatorRepository(
            connection_scope, ensure_initialized
        )
        self._report_hydrator = SqliteCalibrationReportRepository(
            connection_scope, ensure_initialized
        )

    @staticmethod
    def _conflict(message: str) -> NoReturn:
        raise DatabaseInvariantError(message)

    def _fault(self, stage: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(stage)

    def derive_gate_decision(
        self, report_id: str
    ) -> RepositorySealedGateDecisionV1:
        """Accept only a sealed report identifier; every other fact is derived."""

        self._ensure_initialized()
        require_safe_id(report_id)
        if (
            self._begin_write_authorization is None
            or self._end_write_authorization is None
        ):
            self._conflict("gate decision repository authority is unavailable")
        authorization: tuple[str, str] | None = None
        authority_lineage: tuple[str, str, str] | None = None
        try:
            with self._connection_scope() as connection:
                trusted_schema = int(
                    connection.execute("PRAGMA trusted_schema").fetchone()[0]
                )
                try:
                    connection.execute("PRAGMA trusted_schema = ON")
                    connection.execute("BEGIN IMMEDIATE")
                    existing = connection.execute(
                        """
                        SELECT d.decision_id
                        FROM estimator_gate_decision_drafts d
                        JOIN estimator_gate_decision_roots r
                          ON r.decision_id=d.decision_id
                        WHERE d.report_id=?
                        """,
                        (report_id,),
                    ).fetchone()
                    if existing is not None:
                        decision = self._hydrate_and_rederive(
                            connection, existing["decision_id"]
                        )
                        connection.commit()
                        return decision
                    dangling = connection.execute(
                        "SELECT 1 FROM estimator_gate_decision_drafts WHERE report_id=?",
                        (report_id,),
                    ).fetchone()
                    if dangling is not None:
                        self._conflict("gate decision storage is incompletely sealed")

                    sealed_report = self._report_hydrator._hydrate_and_rederive(
                        connection, report_id
                    )
                    report = sealed_report.report
                    campaign = self._estimator_hydrator._hydrate_preregistered_campaign(
                        connection, report.campaign_id
                    )
                    submission = self._estimator_hydrator._hydrate_calibration_evidence_submission(
                        connection, report.submission_id
                    )
                    derived_at = self._clock()
                    if (
                        derived_at.tzinfo is None
                        or derived_at.utcoffset() != timedelta(0)
                    ):
                        raise ValueError("repository gate clock must return UTC")
                    decision = derive_repository_sealed_gate_decision_v1(
                        campaign,
                        submission,
                        sealed_report,
                        derived_at=derived_at,
                    )
                    job_id = secrets.token_hex(32)
                    authority_lineage = (report_id, decision.decision_id, job_id)
                    authorization = self._begin_write_authorization(*authority_lineage)
                    connection.execute(
                        "INSERT INTO estimator_gate_decision_append_authorizations VALUES (?,?,?,?,?)",
                        (
                            authorization[0],
                            report_id,
                            decision.decision_id,
                            job_id,
                            authorization[1],
                        ),
                    )
                    self._insert_draft(connection, decision)
                    self._insert_checks(connection, decision)
                    self._fault("after_checks")
                    self._insert_root(connection, decision)
                    self._fault("after_root")
                    hydrated = self._hydrate_and_rederive(
                        connection, decision.decision_id
                    )
                    if hydrated != decision:
                        self._conflict("gate decision differs after relational hydration")
                    connection.execute(
                        "DELETE FROM estimator_gate_decision_append_authorizations WHERE operation_id=?",
                        (authorization[0],),
                    )
                    self._fault("before_commit")
                    connection.commit()
                    return hydrated
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    connection.execute(
                        f"PRAGMA trusted_schema = {1 if trusted_schema else 0}"
                    )
        finally:
            if (
                authorization is not None
                and authority_lineage is not None
                and self._end_write_authorization is not None
            ):
                self._end_write_authorization(
                    authorization[0], *authority_lineage, authorization[1]
                )

    def get_gate_decision_for_report(
        self, report_id: str
    ) -> RepositorySealedGateDecisionV1 | None:
        self._ensure_initialized()
        require_safe_id(report_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """
                SELECT d.decision_id
                FROM estimator_gate_decision_drafts d
                JOIN estimator_gate_decision_roots r ON r.decision_id=d.decision_id
                WHERE d.report_id=?
                """,
                (report_id,),
            ).fetchone()
            if row is None:
                dangling = connection.execute(
                    "SELECT 1 FROM estimator_gate_decision_drafts WHERE report_id=?",
                    (report_id,),
                ).fetchone()
                if dangling is not None:
                    self._conflict("gate decision storage is incompletely sealed")
                return None
            return self._hydrate_and_rederive(connection, row["decision_id"])

    @staticmethod
    def _insert_draft(connection, decision: RepositorySealedGateDecisionV1) -> None:
        connection.execute(
            """
            INSERT INTO estimator_gate_decision_drafts VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )
            """,
            (
                decision.decision_id,
                decision.report_id,
                decision.campaign_id,
                decision.campaign_fingerprint,
                decision.stored_plan_fingerprint,
                decision.policy_fingerprint,
                decision.assignment_manifest_fingerprint,
                decision.split_fingerprint,
                decision.preregistration_fingerprint,
                decision.preregistration_v2_fingerprint,
                decision.constellation_fingerprint,
                decision.submission_id,
                decision.submission_fingerprint,
                decision.report_receipt_id,
                decision.report_fingerprint,
                decision.report_receipt_fingerprint,
                decision.report_definition_fingerprint,
                decision.report_source_bundle_fingerprint,
                decision.definition_fingerprint,
                decision.evaluator_version,
                decision.check_set_fingerprint,
                decision.outcome.value,
                len(decision.checks),
                _to_epoch_us(decision.campaign_registered_at),
                _to_epoch_us(decision.submission_submitted_at),
                _to_epoch_us(decision.report_derived_at),
                _to_epoch_us(decision.derived_at),
            ),
        )

    @staticmethod
    def _insert_checks(connection, decision: RepositorySealedGateDecisionV1) -> None:
        connection.executemany(
            """
            INSERT INTO estimator_gate_decision_checks VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )
            """,
            (
                (
                    decision.decision_id,
                    ordinal,
                    check.contract_version,
                    check.check_key,
                    check.category.value,
                    check.outcome.value,
                    check.operator.value,
                    check.actual.shape.value,
                    check.actual.unit_code,
                    check.actual.integer_value,
                    check.actual.scalar_value,
                    check.threshold.shape.value,
                    check.threshold.unit_code,
                    check.threshold.integer_value,
                    check.threshold.scalar_value,
                    check.reason_code,
                    check.fingerprint,
                )
                for ordinal, check in enumerate(decision.checks)
            ),
        )

    @staticmethod
    def _insert_root(connection, decision: RepositorySealedGateDecisionV1) -> None:
        connection.execute(
            """
            INSERT INTO estimator_gate_decision_roots VALUES (
                ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
            )
            """,
            (
                decision.decision_id,
                decision.contract_version,
                decision.fingerprint,
                decision.check_set_fingerprint,
                decision.definition_fingerprint,
                decision.evaluator_version,
                decision.outcome.value,
                len(decision.checks),
                _to_epoch_us(decision.derived_at),
                1,
                1,
                "repository_sealed",
                0,
                0,
                0,
                0,
                0,
            ),
        )

    def _hydrate_definition(self, connection) -> GateDecisionDefinitionV1:
        row = connection.execute(
            "SELECT * FROM estimator_gate_decision_definitions WHERE definition_fingerprint=?",
            (FIXED_GATE_DECISION_DEFINITION.fingerprint,),
        ).fetchone()
        if row is None:
            self._conflict("fixed gate decision definition is missing")
        definition = GateDecisionDefinitionV1(
            contract_version=row["contract_version"],
            definition_version=row["definition_version"],
            evaluator_version=row["evaluator_version"],
            lineage_version=row["lineage_version"],
            missingness_version=row["missingness_version"],
            outcome_version=row["outcome_version"],
            threshold_version=row["threshold_version"],
            vocabulary_version=row["vocabulary_version"],
            activation_allowed=bool(row["activation_allowed"]),
        )
        if definition != FIXED_GATE_DECISION_DEFINITION:
            self._conflict("fixed gate decision definition is not reproducible")
        return definition

    @staticmethod
    def _hydrate_value(row, prefix: str) -> GateDecisionValueV1:
        return GateDecisionValueV1(
            shape=row[f"{prefix}_shape"],
            unit_code=row[f"{prefix}_unit_code"],
            integer_value=row[f"{prefix}_integer_value"],
            scalar_value=row[f"{prefix}_scalar_value"],
        )

    def _hydrate_and_rederive(
        self, connection, decision_id: str
    ) -> RepositorySealedGateDecisionV1:
        draft = connection.execute(
            "SELECT * FROM estimator_gate_decision_drafts WHERE decision_id=?",
            (decision_id,),
        ).fetchone()
        root = connection.execute(
            "SELECT * FROM estimator_gate_decision_roots WHERE decision_id=?",
            (decision_id,),
        ).fetchone()
        if draft is None or root is None:
            self._conflict("sealed gate decision root is missing")
        definition = self._hydrate_definition(connection)
        rows = connection.execute(
            "SELECT * FROM estimator_gate_decision_checks WHERE decision_id=? ORDER BY ordinal",
            (decision_id,),
        ).fetchall()
        if tuple(row["ordinal"] for row in rows) != tuple(range(len(rows))):
            self._conflict("gate decision check ordinals are not contiguous")
        checks = tuple(
            GateDecisionCheckV1(
                contract_version=row["contract_version"],
                check_key=row["check_key"],
                category=row["category"],
                outcome=row["outcome"],
                operator=row["operator"],
                actual=self._hydrate_value(row, "actual"),
                threshold=self._hydrate_value(row, "threshold"),
                reason_code=row["reason_code"],
            )
            for row in rows
        )
        for check, row in zip(checks, rows, strict=True):
            if check.fingerprint != row["check_fingerprint"]:
                self._conflict("gate decision check fingerprint is not reproducible")
        check_set_fingerprint = canonical_payload_digest(
            [item.model_dump(mode="json") for item in checks]
        )
        decision = revalidate_repository_sealed_gate_decision_v1(
            RepositorySealedGateDecisionV1(
                contract_version=root["contract_version"],
                decision_id=draft["decision_id"],
                campaign_id=draft["campaign_id"],
                campaign_fingerprint=draft["campaign_fingerprint"],
                stored_plan_fingerprint=draft["stored_plan_fingerprint"],
                policy_fingerprint=draft["policy_fingerprint"],
                assignment_manifest_fingerprint=draft[
                    "assignment_manifest_fingerprint"
                ],
                split_fingerprint=draft["split_fingerprint"],
                preregistration_fingerprint=draft["preregistration_fingerprint"],
                preregistration_v2_fingerprint=draft[
                    "preregistration_v2_fingerprint"
                ],
                constellation_fingerprint=draft["constellation_fingerprint"],
                submission_id=draft["submission_id"],
                submission_fingerprint=draft["submission_fingerprint"],
                report_id=draft["report_id"],
                report_receipt_id=draft["report_receipt_id"],
                report_fingerprint=draft["report_fingerprint"],
                report_receipt_fingerprint=draft["report_receipt_fingerprint"],
                report_definition_fingerprint=draft[
                    "report_definition_fingerprint"
                ],
                report_source_bundle_fingerprint=draft[
                    "report_source_bundle_fingerprint"
                ],
                definition=definition,
                definition_fingerprint=draft["definition_fingerprint"],
                evaluator_version=draft["evaluator_version"],
                checks=checks,
                check_set_fingerprint=draft["check_set_fingerprint"],
                outcome=draft["outcome"],
                campaign_registered_at=_from_epoch_us(
                    draft["campaign_registered_at_us"]
                ),
                submission_submitted_at=_from_epoch_us(
                    draft["submission_submitted_at_us"]
                ),
                report_derived_at=_from_epoch_us(draft["report_derived_at_us"]),
                derived_at=_from_epoch_us(draft["derived_at_us"]),
                repository_owned=bool(root["repository_owned"]),
                repository_sealed=bool(root["repository_sealed"]),
                persistence_state=root["persistence_state"],
                activation_allowed=bool(root["activation_allowed"]),
                activation_slot_written=bool(root["activation_slot_written"]),
                comparison_allowed=bool(root["comparison_allowed"]),
                private_export_allowed=bool(root["private_export_allowed"]),
                team_share_allowed=bool(root["team_share_allowed"]),
            )
        )
        if (
            check_set_fingerprint != draft["check_set_fingerprint"]
            or check_set_fingerprint != root["check_set_fingerprint"]
            or len(checks) != draft["check_count"]
            or len(checks) != root["check_count"]
            or draft["definition_fingerprint"] != root["definition_fingerprint"]
            or draft["evaluator_version"] != root["evaluator_version"]
            or draft["outcome"] != root["outcome"]
            or draft["derived_at_us"] != root["derived_at_us"]
            or decision.fingerprint != root["decision_fingerprint"]
        ):
            self._conflict("gate decision root is not reproducible")

        sealed_report = self._report_hydrator._hydrate_and_rederive(
            connection, draft["report_id"]
        )
        campaign = self._estimator_hydrator._hydrate_preregistered_campaign(
            connection, draft["campaign_id"]
        )
        submission = self._estimator_hydrator._hydrate_calibration_evidence_submission(
            connection, draft["submission_id"]
        )
        expected = derive_repository_sealed_gate_decision_v1(
            campaign,
            submission,
            sealed_report,
            derived_at=decision.derived_at,
        )
        if expected != decision:
            self._conflict("persisted gate decision is not reproducible")
        return decision


__all__ = ["SqliteGateDecisionRepository"]
