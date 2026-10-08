"""SQLite adapter for append-only requirement-verification evidence."""

from __future__ import annotations

from collections.abc import Callable
import hmac
import sqlite3

from ...application.analysis.metric_contract_v2 import (
    metric_contract_v2_set_fingerprint,
)
from ...application.analysis.metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_5,
    METRIC_PROJECTION_V2_VERSION_6,
    METRIC_PROJECTION_V2_VERSION_7,
    METRIC_PROJECTION_V2_VERSION_8,
)
from ...application.analysis.requirement_plan_evidence import (
    RequirementPlanDecisionKind,
)
from ...application.analysis.requirement_verification_evidence import (
    AppIssuedRequirementVerificationOpportunity,
    AppIssuedRequirementVerificationOpportunitySet,
    AppIssuedRequirementVerificationResult,
    ExplicitRequirementAcceptanceAuthority,
    RequirementAcceptanceOutcome,
    RequirementVerificationMethod,
    RequirementVerificationOutcome,
    issue_requirement_verification_evidence_set,
    validate_explicit_requirement_acceptance,
    validate_requirement_verification_opportunities,
    validate_requirement_verification_result,
)
from ...application.analysis.requirement_verification_persistence import (
    MAX_REQUIREMENT_VERIFICATION_HISTORY_PER_OPPORTUNITY,
    MAX_REQUIREMENT_VERIFICATION_REVISIONS,
    REQUIREMENT_ACCEPTANCE_APPEND_CONFIRMATION,
    RequirementVerificationAuthorityDraft,
    RequirementVerificationAuthorityHead,
    RequirementVerificationAuthorityRecord,
    RequirementVerificationAuthorityRecordKind,
    RequirementVerificationConflictError,
    RequirementVerificationDefinitionsOutOfDateError,
    RequirementVerificationEvidenceSnapshot,
    RequirementVerificationNotFoundError,
    RequirementVerificationOpportunitySetRecord,
)
from ...database import DatabaseInvariantError
from ..identifiers import LocalArtifactIdFactory
from ._common import ConnectionScope, from_iso, require_safe_id, to_iso
from .requirement_plan_evidence import (
    SqliteRequirementPlanEvidenceRepository,
    confirmed_requirement_plan_snapshot,
)


_SUPPORTED_PROJECTIONS = frozenset(
    {
        METRIC_PROJECTION_V2_VERSION_5,
        METRIC_PROJECTION_V2_VERSION_6,
        METRIC_PROJECTION_V2_VERSION_7,
        METRIC_PROJECTION_V2_VERSION_8,
    }
)


class SqliteCurrentRequirementPlanSourceWindowAuthority:
    """Resolve the latest sealed source window without ephemeral text state."""

    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized

    def current_source_window(self, session_id: str) -> str:
        self._ensure_initialized()
        require_safe_id(session_id)
        with self._connection_scope(readonly=True) as connection:
            connection.execute("BEGIN")
            try:
                rows = connection.execute(
                    """WITH latest AS (
                         SELECT run.run_id,run.input_fingerprint
                         FROM session_model_ensemble_runs run
                         JOIN session_model_ensemble_seals seal
                           ON seal.run_id=run.run_id
                         WHERE run.session_id=?
                         ORDER BY run.completed_at DESC,run.run_id DESC
                         LIMIT 1
                       )
                       SELECT latest.input_fingerprint,
                              publication.projection_version,
                              publication.contract_set_fingerprint
                       FROM latest
                       JOIN (
                         SELECT run_id,projection_version,contract_set_fingerprint
                         FROM session_model_ensemble_metric_publication_v2_seals_r5
                         UNION ALL
                         SELECT run_id,projection_version,contract_set_fingerprint
                         FROM session_model_ensemble_metric_publication_v2_seals_r6
                         UNION ALL
                         SELECT run_id,projection_version,contract_set_fingerprint
                         FROM session_model_ensemble_metric_publication_v2_seals_r7
                         UNION ALL
                         SELECT run_id,projection_version,contract_set_fingerprint
                         FROM session_model_ensemble_metric_publication_v2_seals_r8
                       ) publication ON publication.run_id=latest.run_id""",
                    (session_id,),
                ).fetchall()
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        if not rows:
            raise RequirementVerificationNotFoundError(
                "a sealed metric publication is required"
            )
        if len(rows) != 1:
            raise DatabaseInvariantError(
                "current sealed metric publication identity is ambiguous"
            )
        row = rows[0]
        if (
            row["projection_version"] not in _SUPPORTED_PROJECTIONS
            or not hmac.compare_digest(
                row["contract_set_fingerprint"],
                metric_contract_v2_set_fingerprint(),
            )
        ):
            raise RequirementVerificationDefinitionsOutOfDateError(
                "current metric publication definitions are not supported"
            )
        return require_safe_id(str(row["input_fingerprint"]))


class SqliteRequirementVerificationEvidenceRepository:
    """Persist exact r6 opportunities and dense immutable authority revisions."""

    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
        *,
        identifiers: LocalArtifactIdFactory,
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized
        self._identifiers = identifiers

    def issue_opportunity_set(
        self, record: RequirementVerificationOpportunitySetRecord
    ) -> tuple[RequirementVerificationEvidenceSnapshot, bool]:
        self._ensure_initialized()
        checked = RequirementVerificationOpportunitySetRecord.model_validate(
            record.model_dump(mode="python")
        )
        self._validate_stored_set(checked)
        opportunities = checked.opportunities
        with self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                collision = connection.execute(
                    """SELECT opportunity_set_fingerprint
                       FROM requirement_verification_opportunity_sets
                       WHERE opportunity_set_fingerprint=?
                          OR (session_id=? AND requirement_plan_confirmation_id=?)
                       ORDER BY opportunity_set_fingerprint LIMIT 2""",
                    (
                        opportunities.opportunity_set_fingerprint,
                        opportunities.session_id,
                        opportunities.requirement_plan_confirmation_id,
                    ),
                ).fetchall()
                if collision:
                    if len(collision) != 1:
                        raise DatabaseInvariantError(
                            "requirement-verification opportunity identity is ambiguous"
                        )
                    existing = self._set_record_tx(
                        connection, collision[0]["opportunity_set_fingerprint"]
                    )
                    if existing is None or existing.opportunities != opportunities:
                        raise RequirementVerificationConflictError(
                            "requirement-verification opportunity set conflicts"
                        )
                    snapshot = self._snapshot_tx(
                        connection,
                        opportunities.session_id,
                        opportunities.opportunity_set_fingerprint,
                        through_revision=None,
                    )
                    if snapshot is None:
                        raise DatabaseInvariantError(
                            "requirement-verification opportunity set is incomplete"
                        )
                    connection.commit()
                    return snapshot, False

                issued_at = to_iso(checked.issued_at)
                connection.execute(
                    """INSERT INTO requirement_verification_opportunity_sets(
                         opportunity_set_fingerprint,session_id,
                         source_window_fingerprint,
                         requirement_plan_confirmation_id,
                         requirement_plan_proposal_id,
                         requirement_plan_evidence_fingerprint,
                         requirement_plan_schema_version,
                         requirement_plan_policy_version,
                         requirement_plan_review_rubric_version,
                         opportunity_issuer_version,evidence_schema_version,
                         evidence_policy_version,
                         complete_active_requirement_enumeration,
                         opportunity_count,issued_at,persistence_schema_version,
                         local_only,content_persisted
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        opportunities.opportunity_set_fingerprint,
                        opportunities.session_id,
                        opportunities.source_window_fingerprint,
                        opportunities.requirement_plan_confirmation_id,
                        opportunities.requirement_plan_proposal_id,
                        opportunities.requirement_plan_evidence_fingerprint,
                        opportunities.requirement_plan_schema_version,
                        opportunities.requirement_plan_policy_version,
                        opportunities.requirement_plan_review_rubric_version,
                        opportunities.issuer_version,
                        opportunities.evidence_schema_version,
                        opportunities.evidence_policy_version,
                        int(opportunities.complete_active_requirement_enumeration),
                        len(opportunities.opportunities),
                        issued_at,
                        checked.persistence_schema_version,
                        int(checked.local_only),
                        int(checked.content_persisted),
                    ),
                )
                for item in opportunities.opportunities:
                    connection.execute(
                        """INSERT INTO requirement_verification_opportunities(
                             opportunity_set_fingerprint,requirement_index,
                             opportunity_id,requirement_id,message_sequence,
                             clause_index
                           ) VALUES(?,?,?,?,?,?)""",
                        (
                            opportunities.opportunity_set_fingerprint,
                            item.requirement_index,
                            item.opportunity_id,
                            item.requirement_id,
                            item.coordinate.message_sequence,
                            item.coordinate.clause_index,
                        ),
                    )
                connection.execute(
                    """INSERT INTO requirement_verification_opportunity_set_seals(
                         opportunity_set_fingerprint,session_id,
                         source_window_fingerprint,
                         requirement_plan_confirmation_id,
                         requirement_plan_proposal_id,
                         requirement_plan_evidence_fingerprint,
                         opportunity_count,opportunity_issuer_version,
                         evidence_schema_version,evidence_policy_version,
                         persistence_schema_version,sealed_at,local_only,
                         content_persisted
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        opportunities.opportunity_set_fingerprint,
                        opportunities.session_id,
                        opportunities.source_window_fingerprint,
                        opportunities.requirement_plan_confirmation_id,
                        opportunities.requirement_plan_proposal_id,
                        opportunities.requirement_plan_evidence_fingerprint,
                        len(opportunities.opportunities),
                        opportunities.issuer_version,
                        opportunities.evidence_schema_version,
                        opportunities.evidence_policy_version,
                        checked.persistence_schema_version,
                        issued_at,
                        int(checked.local_only),
                        int(checked.content_persisted),
                    ),
                )
                snapshot = self._snapshot_tx(
                    connection,
                    opportunities.session_id,
                    opportunities.opportunity_set_fingerprint,
                    through_revision=None,
                )
                if snapshot is None:
                    raise DatabaseInvariantError(
                        "requirement-verification opportunity set did not seal"
                    )
                connection.commit()
                return snapshot, True
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise RequirementVerificationConflictError(
                    "requirement-verification opportunity set changed"
                ) from error
            except Exception:
                connection.rollback()
                raise

    def get_opportunity_set(
        self, opportunity_set_fingerprint: str
    ) -> RequirementVerificationOpportunitySetRecord | None:
        self._ensure_initialized()
        require_safe_id(opportunity_set_fingerprint)
        with self._connection_scope(readonly=True) as connection:
            connection.execute("BEGIN")
            try:
                record = self._set_record_tx(
                    connection, opportunity_set_fingerprint
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        if record is not None:
            self._validate_stored_set(record)
        return record

    def find_replay(
        self, session_id: str, idempotency_key_digest: str
    ) -> RequirementVerificationAuthorityRecord | None:
        self._ensure_initialized()
        require_safe_id(session_id)
        require_safe_id(idempotency_key_digest)
        with self._connection_scope(readonly=True) as connection:
            connection.execute("BEGIN")
            try:
                row = connection.execute(
                    """SELECT authority_record_id
                       FROM requirement_verification_authority_records
                       WHERE session_id=? AND idempotency_key_digest=?""",
                    (session_id, idempotency_key_digest),
                ).fetchone()
                if row is None:
                    record = None
                    set_record = None
                else:
                    record, set_record = self._record_tx(
                        connection, row["authority_record_id"]
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        if set_record is not None:
            self._validate_stored_set(set_record)
        return record

    def append_authority(
        self, draft: RequirementVerificationAuthorityDraft
    ) -> tuple[RequirementVerificationEvidenceSnapshot, bool]:
        self._ensure_initialized()
        checked = RequirementVerificationAuthorityDraft.model_validate(
            draft.model_dump(mode="python")
        )
        set_record = self.get_opportunity_set(
            checked.opportunity_set_fingerprint
        )
        if (
            set_record is None
            or set_record.opportunities.session_id != checked.session_id
        ):
            raise RequirementVerificationNotFoundError(
                "requirement-verification opportunity set was not found"
            )
        self._validate_draft(checked, set_record.opportunities)
        with self._connection_scope() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                persisted_set = self._set_record_tx(
                    connection, checked.opportunity_set_fingerprint
                )
                if persisted_set != set_record:
                    raise DatabaseInvariantError(
                        "requirement-verification opportunity set changed"
                    )
                replay_row = connection.execute(
                    """SELECT authority_record_id
                       FROM requirement_verification_authority_records
                       WHERE session_id=? AND idempotency_key_digest=?""",
                    (checked.session_id, checked.idempotency_key_digest),
                ).fetchone()
                if replay_row is not None:
                    replay, _ = self._record_tx(
                        connection,
                        replay_row["authority_record_id"],
                        set_record=persisted_set,
                    )
                    if replay is None or not self._same_draft(replay, checked):
                        raise RequirementVerificationConflictError(
                            "requirement-verification idempotency key was reused"
                        )
                    snapshot = self._snapshot_tx(
                        connection,
                        checked.session_id,
                        checked.opportunity_set_fingerprint,
                        through_revision=replay.revision,
                    )
                    if snapshot is None:
                        raise DatabaseInvariantError(
                            "requirement-verification replay is incomplete"
                        )
                    connection.commit()
                    return snapshot, False

                revision_row = connection.execute(
                    """SELECT COALESCE(MAX(revision),0) AS current_revision
                       FROM requirement_verification_authority_records
                       WHERE opportunity_set_fingerprint=?""",
                    (checked.opportunity_set_fingerprint,),
                ).fetchone()
                if revision_row is None:
                    raise DatabaseInvariantError(
                        "requirement-verification revision is unavailable"
                    )
                revision = int(revision_row["current_revision"]) + 1
                if revision > MAX_REQUIREMENT_VERIFICATION_REVISIONS:
                    raise RequirementVerificationConflictError(
                        "requirement-verification revision bound was reached"
                    )
                record = RequirementVerificationAuthorityRecord(
                    **checked.model_dump(mode="python"), revision=revision
                )
                self._insert_authority_tx(connection, record)
                hydrated, _ = self._record_tx(
                    connection,
                    record.authority_record_id,
                    set_record=persisted_set,
                )
                if hydrated != record:
                    raise DatabaseInvariantError(
                        "requirement-verification authority did not seal"
                    )
                snapshot = self._snapshot_tx(
                    connection,
                    checked.session_id,
                    checked.opportunity_set_fingerprint,
                    through_revision=revision,
                )
                if snapshot is None:
                    raise DatabaseInvariantError(
                        "requirement-verification append is incomplete"
                    )
                connection.commit()
                return snapshot, True
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise RequirementVerificationConflictError(
                    "requirement-verification authority changed"
                ) from error
            except Exception:
                connection.rollback()
                raise

    def snapshot(
        self,
        session_id: str,
        opportunity_set_fingerprint: str,
        *,
        through_revision: int | None = None,
    ) -> RequirementVerificationEvidenceSnapshot | None:
        self._ensure_initialized()
        require_safe_id(session_id)
        require_safe_id(opportunity_set_fingerprint)
        if through_revision is not None and not (
            0 <= through_revision <= MAX_REQUIREMENT_VERIFICATION_REVISIONS
        ):
            raise ValueError("requirement-verification revision is outside its bound")
        with self._connection_scope(readonly=True) as connection:
            connection.execute("BEGIN")
            try:
                set_record = self._set_record_tx(
                    connection, opportunity_set_fingerprint
                )
                if (
                    set_record is None
                    or set_record.opportunities.session_id != session_id
                ):
                    result = None
                else:
                    result = self._snapshot_tx(
                        connection,
                        session_id,
                        opportunity_set_fingerprint,
                        through_revision=through_revision,
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        if set_record is not None:
            self._validate_stored_set(set_record)
        return result

    def snapshot_for_requirement_plan(
        self,
        session_id: str,
        requirement_plan_confirmation_id: str,
    ) -> RequirementVerificationEvidenceSnapshot | None:
        """Return the exact current M58 head for one reviewed r6 authority.

        The lookup, r6 revalidation, and M58 head hydration share one SQLite
        read snapshot.  Callers therefore cannot accidentally combine a set
        identity from one point in time with authority rows from another.
        """

        self._ensure_initialized()
        require_safe_id(session_id)
        require_safe_id(requirement_plan_confirmation_id)
        with self._connection_scope(readonly=True) as connection:
            connection.execute("BEGIN")
            try:
                result = self._snapshot_for_requirement_plan_tx(
                    connection,
                    session_id,
                    requirement_plan_confirmation_id,
                )
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise

    def _snapshot_for_requirement_plan_tx(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        requirement_plan_confirmation_id: str,
    ) -> RequirementVerificationEvidenceSnapshot | None:
        rows = connection.execute(
            """SELECT opportunity_set_fingerprint
               FROM requirement_verification_opportunity_sets
               WHERE session_id=? AND requirement_plan_confirmation_id=?
               ORDER BY opportunity_set_fingerprint LIMIT 2""",
            (session_id, requirement_plan_confirmation_id),
        ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise DatabaseInvariantError(
                "requirement-verification plan authority is ambiguous"
            )
        return self._snapshot_for_binding_tx(
            connection,
            session_id,
            str(rows[0]["opportunity_set_fingerprint"]),
            through_revision=None,
            require_current=True,
        )

    def _snapshot_for_binding_tx(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        opportunity_set_fingerprint: str,
        *,
        through_revision: int | None,
        require_current: bool,
    ) -> RequirementVerificationEvidenceSnapshot | None:
        """Hydrate and validate a binding without opening another connection.

        Saves use ``require_current`` while holding ``BEGIN IMMEDIATE``.
        Ordinary run hydration passes ``False`` so an immutable old run keeps
        describing its historical prefix after later evidence is appended.
        """

        set_record = self._set_record_tx(connection, opportunity_set_fingerprint)
        if (
            set_record is None
            or set_record.opportunities.session_id != session_id
        ):
            return None
        self._validate_stored_set_tx(connection, set_record)
        snapshot = self._snapshot_tx(
            connection,
            session_id,
            opportunity_set_fingerprint,
            through_revision=through_revision,
        )
        if snapshot is None:
            return None
        if require_current and through_revision is not None:
            current = self._snapshot_tx(
                connection,
                session_id,
                opportunity_set_fingerprint,
                through_revision=None,
            )
            if current is None or current.revision != through_revision:
                raise DatabaseInvariantError(
                    "requirement-verification run authority changed"
                )
        return snapshot

    def _validate_stored_set(
        self, record: RequirementVerificationOpportunitySetRecord
    ) -> None:
        with self._connection_scope(readonly=True) as connection:
            connection.execute("BEGIN")
            try:
                self._validate_stored_set_tx(connection, record)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def _validate_stored_set_tx(
        self,
        connection: sqlite3.Connection,
        record: RequirementVerificationOpportunitySetRecord,
    ) -> None:
        plan_repository = SqliteRequirementPlanEvidenceRepository(
            self._connection_scope,
            self._ensure_initialized,
            identifiers=self._identifiers,
        )
        view = plan_repository._get_view(
            connection, record.opportunities.requirement_plan_proposal_id
        )
        if (
            view is None
            or view.decision is None
            or view.decision.decision is not RequirementPlanDecisionKind.CONFIRM
            or view.decision.decision_id
            != record.opportunities.requirement_plan_confirmation_id
        ):
            raise DatabaseInvariantError(
                "requirement-verification r6 authority is incomplete"
            )
        snapshot = confirmed_requirement_plan_snapshot(view)
        try:
            validate_requirement_verification_opportunities(
                record.opportunities, snapshot, self._identifiers
            )
        except (TypeError, ValueError) as error:
            raise DatabaseInvariantError(
                "requirement-verification opportunity identity is invalid"
            ) from error

    def _validate_draft(
        self,
        draft: RequirementVerificationAuthorityDraft,
        opportunities: AppIssuedRequirementVerificationOpportunitySet,
    ) -> None:
        try:
            if draft.result is not None:
                validate_requirement_verification_result(
                    draft.result, opportunities, self._identifiers
                )
                expected_command = self._identifiers.fingerprint(
                    "requirement-verification-result-append-command-v1",
                    (
                        draft.session_id,
                        draft.result.result_fingerprint,
                        draft.expected_predecessor_authority_id or "none",
                    ),
                )
            else:
                assert draft.acceptance is not None
                validate_explicit_requirement_acceptance(
                    draft.acceptance, opportunities, self._identifiers
                )
                expected_confirmation = self._identifiers.fingerprint(
                    "requirement-acceptance-confirmation-v1",
                    (
                        draft.session_id,
                        draft.opportunity_set_fingerprint,
                        draft.opportunity_id,
                        draft.idempotency_key_digest,
                    ),
                )
                if not hmac.compare_digest(
                    draft.acceptance.confirmation_id, expected_confirmation
                ):
                    raise ValueError("native confirmation is not app-issued")
                expected_command = self._identifiers.fingerprint(
                    "requirement-acceptance-append-command-v1",
                    (
                        draft.session_id,
                        draft.opportunity_set_fingerprint,
                        draft.opportunity_id,
                        draft.acceptance.outcome.value,
                        REQUIREMENT_ACCEPTANCE_APPEND_CONFIRMATION,
                        draft.expected_predecessor_authority_id or "none",
                    ),
                )
            if not hmac.compare_digest(
                draft.command_fingerprint, expected_command
            ):
                raise ValueError("authority command fingerprint is invalid")
        except (AssertionError, TypeError, ValueError) as error:
            raise DatabaseInvariantError(
                "requirement-verification authority is invalid"
            ) from error

    @staticmethod
    def _same_draft(
        record: RequirementVerificationAuthorityRecord,
        draft: RequirementVerificationAuthorityDraft,
    ) -> bool:
        return record.model_dump(
            mode="python", exclude={"revision", "recorded_at"}
        ) == draft.model_dump(mode="python", exclude={"recorded_at"})

    def _set_record_tx(
        self, connection: sqlite3.Connection, opportunity_set_fingerprint: str
    ) -> RequirementVerificationOpportunitySetRecord | None:
        row = connection.execute(
            """SELECT evidence.*,
                      seal.session_id AS sealed_session_id,
                      seal.source_window_fingerprint AS sealed_source_window,
                      seal.requirement_plan_confirmation_id AS sealed_confirmation_id,
                      seal.requirement_plan_proposal_id AS sealed_proposal_id,
                      seal.requirement_plan_evidence_fingerprint AS sealed_plan_fingerprint,
                      seal.opportunity_count AS sealed_opportunity_count,
                      seal.opportunity_issuer_version AS sealed_issuer_version,
                      seal.evidence_schema_version AS sealed_evidence_schema_version,
                      seal.evidence_policy_version AS sealed_evidence_policy_version,
                      seal.persistence_schema_version AS sealed_persistence_schema_version,
                      seal.sealed_at,seal.local_only AS sealed_local_only,
                      seal.content_persisted AS sealed_content_persisted
               FROM requirement_verification_opportunity_sets evidence
               LEFT JOIN requirement_verification_opportunity_set_seals seal
                 ON seal.opportunity_set_fingerprint=
                    evidence.opportunity_set_fingerprint
               WHERE evidence.opportunity_set_fingerprint=?""",
            (opportunity_set_fingerprint,),
        ).fetchone()
        if row is None:
            return None
        if row["sealed_session_id"] is None:
            raise DatabaseInvariantError(
                "requirement-verification opportunity set is unsealed"
            )
        fields = (
            ("session_id", "sealed_session_id"),
            ("source_window_fingerprint", "sealed_source_window"),
            ("requirement_plan_confirmation_id", "sealed_confirmation_id"),
            ("requirement_plan_proposal_id", "sealed_proposal_id"),
            ("requirement_plan_evidence_fingerprint", "sealed_plan_fingerprint"),
            ("opportunity_count", "sealed_opportunity_count"),
            ("opportunity_issuer_version", "sealed_issuer_version"),
            ("evidence_schema_version", "sealed_evidence_schema_version"),
            ("evidence_policy_version", "sealed_evidence_policy_version"),
            ("persistence_schema_version", "sealed_persistence_schema_version"),
            ("issued_at", "sealed_at"),
            ("local_only", "sealed_local_only"),
            ("content_persisted", "sealed_content_persisted"),
        )
        if any(row[left] != row[right] for left, right in fields):
            raise DatabaseInvariantError(
                "requirement-verification opportunity seal disagrees"
            )
        children = connection.execute(
            """SELECT requirement_index,opportunity_id,requirement_id,
                      message_sequence,clause_index
               FROM requirement_verification_opportunities
               WHERE opportunity_set_fingerprint=?
               ORDER BY requirement_index""",
            (opportunity_set_fingerprint,),
        ).fetchall()
        if (
            len(children) != int(row["opportunity_count"])
            or tuple(int(item["requirement_index"]) for item in children)
            != tuple(range(len(children)))
        ):
            raise DatabaseInvariantError(
                "requirement-verification opportunity enumeration is incomplete"
            )
        issued_at = from_iso(row["issued_at"])
        if issued_at is None:
            raise DatabaseInvariantError(
                "requirement-verification opportunity time is missing"
            )
        try:
            opportunities = AppIssuedRequirementVerificationOpportunitySet(
                session_id=row["session_id"],
                source_window_fingerprint=row["source_window_fingerprint"],
                requirement_plan_confirmation_id=(
                    row["requirement_plan_confirmation_id"]
                ),
                requirement_plan_proposal_id=row["requirement_plan_proposal_id"],
                requirement_plan_evidence_fingerprint=(
                    row["requirement_plan_evidence_fingerprint"]
                ),
                requirement_plan_schema_version=(
                    row["requirement_plan_schema_version"]
                ),
                requirement_plan_policy_version=(
                    row["requirement_plan_policy_version"]
                ),
                requirement_plan_review_rubric_version=(
                    row["requirement_plan_review_rubric_version"]
                ),
                issuer_version=row["opportunity_issuer_version"],
                evidence_schema_version=row["evidence_schema_version"],
                evidence_policy_version=row["evidence_policy_version"],
                complete_active_requirement_enumeration=bool(
                    row["complete_active_requirement_enumeration"]
                ),
                opportunities=tuple(
                    AppIssuedRequirementVerificationOpportunity(
                        opportunity_id=item["opportunity_id"],
                        requirement_index=int(item["requirement_index"]),
                        requirement_id=item["requirement_id"],
                        coordinate={
                            "message_sequence": int(item["message_sequence"]),
                            "clause_index": int(item["clause_index"]),
                        },
                    )
                    for item in children
                ),
                opportunity_set_fingerprint=row["opportunity_set_fingerprint"],
                local_only=bool(row["local_only"]),
                content_persisted=bool(row["content_persisted"]),
            )
            return RequirementVerificationOpportunitySetRecord(
                opportunities=opportunities,
                issued_at=issued_at,
                persistence_schema_version=row["persistence_schema_version"],
                local_only=bool(row["local_only"]),
                content_persisted=bool(row["content_persisted"]),
            )
        except (TypeError, ValueError) as error:
            raise DatabaseInvariantError(
                "requirement-verification opportunity set is malformed"
            ) from error

    def _record_tx(
        self,
        connection: sqlite3.Connection,
        authority_record_id: str,
        *,
        set_record: RequirementVerificationOpportunitySetRecord | None = None,
    ) -> tuple[
        RequirementVerificationAuthorityRecord | None,
        RequirementVerificationOpportunitySetRecord | None,
    ]:
        row = connection.execute(
            """SELECT authority.*,
                      seal.session_id AS sealed_session_id,
                      seal.opportunity_set_fingerprint AS sealed_set_fingerprint,
                      seal.opportunity_id AS sealed_opportunity_id,
                      seal.requirement_id AS sealed_requirement_id,
                      seal.revision AS sealed_revision,
                      seal.expected_predecessor_authority_id AS sealed_predecessor,
                      seal.authority_kind AS sealed_authority_kind,
                      seal.authority_issuer_version AS sealed_issuer_version,
                      seal.evidence_schema_version AS sealed_evidence_schema_version,
                      seal.evidence_policy_version AS sealed_evidence_policy_version,
                      seal.issued_authority AS sealed_issued_authority,
                      seal.authority_fingerprint AS sealed_authority_fingerprint,
                      seal.receipt_reference_count AS sealed_receipt_count,
                      seal.idempotency_key_digest AS sealed_idempotency_digest,
                      seal.command_fingerprint AS sealed_command_fingerprint,
                      seal.recorded_at AS sealed_recorded_at,
                      seal.persistence_schema_version AS sealed_persistence_schema,
                      seal.sealed_at,seal.local_only AS sealed_local_only,
                      seal.content_persisted AS sealed_content_persisted
               FROM requirement_verification_authority_records authority
               LEFT JOIN requirement_verification_authority_record_seals seal
                 ON seal.authority_record_id=authority.authority_record_id
               WHERE authority.authority_record_id=?""",
            (authority_record_id,),
        ).fetchone()
        if row is None:
            return None, None
        if row["sealed_session_id"] is None:
            raise DatabaseInvariantError(
                "requirement-verification authority is unsealed"
            )
        authority_fingerprint = (
            row["result_fingerprint"]
            if row["authority_kind"] == "objective_result"
            else row["acceptance_fingerprint"]
        )
        exact = (
            row["session_id"] == row["sealed_session_id"]
            and row["opportunity_set_fingerprint"]
            == row["sealed_set_fingerprint"]
            and row["opportunity_id"] == row["sealed_opportunity_id"]
            and row["requirement_id"] == row["sealed_requirement_id"]
            and int(row["revision"]) == int(row["sealed_revision"])
            and row["expected_predecessor_authority_id"]
            == row["sealed_predecessor"]
            and row["authority_kind"] == row["sealed_authority_kind"]
            and row["authority_issuer_version"] == row["sealed_issuer_version"]
            and row["evidence_schema_version"]
            == row["sealed_evidence_schema_version"]
            and row["evidence_policy_version"]
            == row["sealed_evidence_policy_version"]
            and int(row["issued_authority"])
            == int(row["sealed_issued_authority"])
            and authority_fingerprint == row["sealed_authority_fingerprint"]
            and int(row["receipt_reference_count"] or 0)
            == int(row["sealed_receipt_count"])
            and row["idempotency_key_digest"]
            == row["sealed_idempotency_digest"]
            and row["command_fingerprint"] == row["sealed_command_fingerprint"]
            and row["recorded_at"] == row["sealed_recorded_at"]
            and row["recorded_at"] == row["sealed_at"]
            and row["persistence_schema_version"]
            == row["sealed_persistence_schema"]
            and int(row["local_only"]) == int(row["sealed_local_only"])
            and int(row["content_persisted"])
            == int(row["sealed_content_persisted"])
        )
        if not exact:
            raise DatabaseInvariantError(
                "requirement-verification authority seal disagrees"
            )
        receipt_rows = connection.execute(
            """SELECT ordinal,receipt_reference_id
               FROM requirement_verification_result_receipt_refs
               WHERE authority_record_id=? ORDER BY ordinal""",
            (authority_record_id,),
        ).fetchall()
        receipts = tuple(item["receipt_reference_id"] for item in receipt_rows)
        if (
            tuple(int(item["ordinal"]) for item in receipt_rows)
            != tuple(range(len(receipt_rows)))
            or len(receipts) != int(row["receipt_reference_count"] or 0)
        ):
            raise DatabaseInvariantError(
                "requirement-verification result receipts are incomplete"
            )
        if set_record is None:
            set_record = self._set_record_tx(
                connection, row["opportunity_set_fingerprint"]
            )
        if set_record is None:
            raise DatabaseInvariantError(
                "requirement-verification authority lost its opportunity set"
            )
        if (
            set_record.opportunities.opportunity_set_fingerprint
            != row["opportunity_set_fingerprint"]
        ):
            raise DatabaseInvariantError(
                "requirement-verification authority belongs to another set"
            )
        recorded_at = from_iso(row["recorded_at"])
        if recorded_at is None:
            raise DatabaseInvariantError(
                "requirement-verification authority time is missing"
            )
        try:
            result = None
            acceptance = None
            kind = RequirementVerificationAuthorityRecordKind(
                row["authority_kind"]
            )
            if kind is RequirementVerificationAuthorityRecordKind.OBJECTIVE_RESULT:
                result = AppIssuedRequirementVerificationResult(
                    result_id=row["authority_record_id"],
                    opportunity_set_fingerprint=row["opportunity_set_fingerprint"],
                    opportunity_id=row["opportunity_id"],
                    requirement_id=row["requirement_id"],
                    observed_sequence=int(row["observed_sequence"]),
                    method=RequirementVerificationMethod(row["verification_method"]),
                    outcome=RequirementVerificationOutcome(
                        row["verification_outcome"]
                    ),
                    receipt_reference_ids=receipts,
                    issuer_version=row["authority_issuer_version"],
                    evidence_schema_version=row["evidence_schema_version"],
                    evidence_policy_version=row["evidence_policy_version"],
                    result_fingerprint=row["result_fingerprint"],
                    app_issued=bool(row["issued_authority"]),
                    local_only=bool(row["local_only"]),
                    content_persisted=bool(row["content_persisted"]),
                )
            else:
                acceptance = ExplicitRequirementAcceptanceAuthority(
                    acceptance_id=row["authority_record_id"],
                    opportunity_set_fingerprint=row["opportunity_set_fingerprint"],
                    opportunity_id=row["opportunity_id"],
                    requirement_id=row["requirement_id"],
                    confirmation_id=row["acceptance_confirmation_id"],
                    outcome=RequirementAcceptanceOutcome(
                        row["acceptance_outcome"]
                    ),
                    issuer_version=row["authority_issuer_version"],
                    evidence_schema_version=row["evidence_schema_version"],
                    evidence_policy_version=row["evidence_policy_version"],
                    acceptance_fingerprint=row["acceptance_fingerprint"],
                    owned_native_action=bool(row["issued_authority"]),
                    local_only=bool(row["local_only"]),
                    content_persisted=bool(row["content_persisted"]),
                )
            record = RequirementVerificationAuthorityRecord(
                authority_record_id=row["authority_record_id"],
                session_id=row["session_id"],
                opportunity_set_fingerprint=row["opportunity_set_fingerprint"],
                opportunity_id=row["opportunity_id"],
                requirement_id=row["requirement_id"],
                expected_predecessor_authority_id=(
                    row["expected_predecessor_authority_id"]
                ),
                kind=kind,
                idempotency_key_digest=row["idempotency_key_digest"],
                command_fingerprint=row["command_fingerprint"],
                recorded_at=recorded_at,
                result=result,
                acceptance=acceptance,
                persistence_schema_version=row["persistence_schema_version"],
                local_only=bool(row["local_only"]),
                content_persisted=bool(row["content_persisted"]),
                revision=int(row["revision"]),
            )
            self._validate_draft(record, set_record.opportunities)
            return record, set_record
        except DatabaseInvariantError:
            raise
        except (TypeError, ValueError) as error:
            raise DatabaseInvariantError(
                "requirement-verification authority is malformed"
            ) from error

    def _all_records_tx(
        self,
        connection: sqlite3.Connection,
        opportunity_set_fingerprint: str,
        *,
        set_record: RequirementVerificationOpportunitySetRecord,
    ) -> tuple[RequirementVerificationAuthorityRecord, ...]:
        rows = connection.execute(
            """SELECT authority_record_id
               FROM requirement_verification_authority_records
               WHERE opportunity_set_fingerprint=? ORDER BY revision""",
            (opportunity_set_fingerprint,),
        ).fetchall()
        records = []
        for row in rows:
            record, _ = self._record_tx(
                connection,
                row["authority_record_id"],
                set_record=set_record,
            )
            if record is None:
                raise DatabaseInvariantError(
                    "requirement-verification authority history is incomplete"
                )
            records.append(record)
        if tuple(item.revision for item in records) != tuple(
            range(1, len(records) + 1)
        ):
            raise DatabaseInvariantError(
                "requirement-verification revisions are not dense"
            )
        per_opportunity: dict[str, list[RequirementVerificationAuthorityRecord]] = {}
        for item in records:
            per_opportunity.setdefault(item.opportunity_id, []).append(item)
        for history in per_opportunity.values():
            if len(history) > MAX_REQUIREMENT_VERIFICATION_HISTORY_PER_OPPORTUNITY:
                raise DatabaseInvariantError(
                    "requirement-verification history exceeds its bound"
                )
            if len({item.kind for item in history}) != 1:
                raise DatabaseInvariantError(
                    "requirement-verification authority kind changed"
                )
            objective_sequences = tuple(
                item.result.observed_sequence
                for item in history
                if item.result is not None
            )
            if any(
                current <= previous
                for previous, current in zip(
                    objective_sequences, objective_sequences[1:]
                )
            ):
                raise DatabaseInvariantError(
                    "requirement-verification observation did not advance"
                )
            for index, item in enumerate(history):
                predecessor = None if index == 0 else history[index - 1].authority_record_id
                if item.expected_predecessor_authority_id != predecessor:
                    raise DatabaseInvariantError(
                        "requirement-verification predecessor chain is invalid"
                    )
        return tuple(records)

    def _snapshot_tx(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        opportunity_set_fingerprint: str,
        *,
        through_revision: int | None,
    ) -> RequirementVerificationEvidenceSnapshot | None:
        set_record = self._set_record_tx(connection, opportunity_set_fingerprint)
        if set_record is None or set_record.opportunities.session_id != session_id:
            return None
        records = self._all_records_tx(
            connection,
            opportunity_set_fingerprint,
            set_record=set_record,
        )
        current_revision = len(records)
        target_revision = (
            current_revision if through_revision is None else through_revision
        )
        if target_revision > current_revision:
            raise RequirementVerificationNotFoundError(
                "requirement-verification revision was not found"
            )
        selected = [item for item in records if item.revision <= target_revision]
        heads_by_opportunity: dict[str, RequirementVerificationAuthorityRecord] = {}
        for item in selected:
            heads_by_opportunity[item.opportunity_id] = item
        head_records = tuple(
            heads_by_opportunity[key] for key in sorted(heads_by_opportunity)
        )
        evidence = issue_requirement_verification_evidence_set(
            set_record.opportunities,
            verification_results=tuple(
                item.result for item in head_records if item.result is not None
            ),
            acceptance_authorities=tuple(
                item.acceptance
                for item in head_records
                if item.acceptance is not None
            ),
            identifiers=self._identifiers,
        )
        return RequirementVerificationEvidenceSnapshot(
            evidence=evidence,
            revision=target_revision,
            authority_heads=tuple(
                RequirementVerificationAuthorityHead(
                    opportunity_id=item.opportunity_id,
                    authority_record_id=item.authority_record_id,
                    kind=item.kind,
                    revision=item.revision,
                )
                for item in head_records
            ),
        )

    def _insert_authority_tx(
        self,
        connection: sqlite3.Connection,
        record: RequirementVerificationAuthorityRecord,
    ) -> None:
        result = record.result
        acceptance = record.acceptance
        authority = result if result is not None else acceptance
        assert authority is not None
        authority_fingerprint = (
            result.result_fingerprint
            if result is not None
            else acceptance.acceptance_fingerprint
        )
        issuer_version = authority.issuer_version
        recorded_at = to_iso(record.recorded_at)
        receipts = () if result is None else result.receipt_reference_ids
        connection.execute(
            """INSERT INTO requirement_verification_authority_records(
                 authority_record_id,session_id,opportunity_set_fingerprint,
                 opportunity_id,requirement_id,revision,
                 expected_predecessor_authority_id,authority_kind,
                 authority_issuer_version,evidence_schema_version,
                 evidence_policy_version,issued_authority,observed_sequence,
                 verification_method,verification_outcome,
                 receipt_reference_count,result_fingerprint,
                 acceptance_confirmation_id,acceptance_outcome,
                 acceptance_fingerprint,idempotency_key_digest,
                 command_fingerprint,recorded_at,persistence_schema_version,
                 local_only,content_persisted
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                record.authority_record_id,
                record.session_id,
                record.opportunity_set_fingerprint,
                record.opportunity_id,
                record.requirement_id,
                record.revision,
                record.expected_predecessor_authority_id,
                record.kind.value,
                issuer_version,
                authority.evidence_schema_version,
                authority.evidence_policy_version,
                1,
                None if result is None else result.observed_sequence,
                None if result is None else result.method.value,
                None if result is None else result.outcome.value,
                None if result is None else len(receipts),
                None if result is None else result.result_fingerprint,
                None if acceptance is None else acceptance.confirmation_id,
                None if acceptance is None else acceptance.outcome.value,
                None if acceptance is None else acceptance.acceptance_fingerprint,
                record.idempotency_key_digest,
                record.command_fingerprint,
                recorded_at,
                record.persistence_schema_version,
                int(record.local_only),
                int(record.content_persisted),
            ),
        )
        for ordinal, receipt_reference_id in enumerate(receipts):
            connection.execute(
                """INSERT INTO requirement_verification_result_receipt_refs(
                     authority_record_id,ordinal,receipt_reference_id
                   ) VALUES(?,?,?)""",
                (record.authority_record_id, ordinal, receipt_reference_id),
            )
        connection.execute(
            """INSERT INTO requirement_verification_authority_record_seals(
                 authority_record_id,session_id,opportunity_set_fingerprint,
                 opportunity_id,requirement_id,revision,
                 expected_predecessor_authority_id,authority_kind,
                 authority_issuer_version,evidence_schema_version,
                 evidence_policy_version,issued_authority,
                 authority_fingerprint,receipt_reference_count,
                 idempotency_key_digest,command_fingerprint,recorded_at,
                 persistence_schema_version,sealed_at,local_only,
                 content_persisted
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                record.authority_record_id,
                record.session_id,
                record.opportunity_set_fingerprint,
                record.opportunity_id,
                record.requirement_id,
                record.revision,
                record.expected_predecessor_authority_id,
                record.kind.value,
                issuer_version,
                authority.evidence_schema_version,
                authority.evidence_policy_version,
                1,
                authority_fingerprint,
                len(receipts),
                record.idempotency_key_digest,
                record.command_fingerprint,
                recorded_at,
                record.persistence_schema_version,
                recorded_at,
                int(record.local_only),
                int(record.content_persisted),
            ),
        )


__all__ = (
    "SqliteCurrentRequirementPlanSourceWindowAuthority",
    "SqliteRequirementVerificationEvidenceRepository",
)
