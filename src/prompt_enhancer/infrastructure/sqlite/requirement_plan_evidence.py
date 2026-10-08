"""SQLite adapter for reviewed, content-free requirement-plan evidence."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import hmac
import sqlite3

from ...application.analysis.requirement_plan_evidence import (
    ConfirmedPlanEvidence,
    ConfirmedRequirementEvidence,
    ExcludedRequirementClause,
    PlanCoordinate,
    RequirementCoordinate,
    RequirementDisposition,
    RequirementEvidenceEntry,
    RequirementPlanConflictError,
    RequirementPlanDecisionKind,
    RequirementPlanDecisionRecord,
    RequirementPlanEvidenceSnapshot,
    RequirementPlanExclusionReason,
    RequirementPlanProducerReceipt,
    RequirementPlanProposalRecord,
    RequirementPlanProposalPageSnapshot,
    RequirementPlanProposalStatus,
    RequirementPlanProposalView,
    RequirementPlanRepository,
    requirement_plan_graph_fingerprint,
)
from ...database import DatabaseInvariantError
from ..identifiers import LocalArtifactIdFactory
from ._common import ConnectionScope, from_iso, require_safe_id, to_iso


def _page_snapshot_id(
    identifiers: LocalArtifactIdFactory,
    session_id: str,
    snapshot: RequirementPlanProposalPageSnapshot,
) -> str:
    """Use the same installation-keyed boundary commitment as the service."""

    return identifiers.fingerprint(
        "requirement-plan-proposal-page-snapshot-v1",
        (
            session_id,
            str(snapshot.total),
            str(snapshot.decision_count),
            (
                "none"
                if snapshot.high_water_created_at is None
                else snapshot.high_water_created_at.isoformat()
            ),
            snapshot.high_water_proposal_id or "none",
        ),
    )


def _derived_id(namespace: str, authority_id: str, ordinal: int) -> str:
    """Derive a public-safe unit ID from an installation-keyed decision ID."""

    return hashlib.sha256(
        f"{namespace}\x1f{authority_id}\x1f{ordinal}".encode("ascii")
    ).hexdigest()


_PLAN_DECISION_AUTHORITY_VERSION = "requirement-plan-decision-authority-v1"
_PLAN_DECISION_AUTHORITY_KEYED = "keyed_application_issuance"
_PLAN_DECISION_AUTHORITY_UPGRADE = "trusted_m55_upgrade"
_PLAN_DECISION_AUTHORITY_UPGRADE_PENDING = "trusted_m55_upgrade_pending"


def _decision_authority_fingerprint(
    identifiers: LocalArtifactIdFactory,
    *,
    authority_source: str,
    decision_id: str,
    proposal_id: str,
    session_id: str,
    decision: str,
    idempotency_key_digest: str,
    command_fingerprint: str,
    decided_at: str,
    confirmation_authority: str,
    decision_schema_version: str,
    decision_local_only: int,
    decision_content_persisted: int,
    source_run_id: str,
    source_window_fingerprint: str,
    expected_predecessor_confirmation_id: str | None,
    payload_sha256: str,
    graph_fingerprint: str,
    proposal_schema_version: str,
    proposal_policy_version: str,
    review_rubric_version: str,
) -> str:
    """Bind one durable plan decision to its complete sealed authority."""

    return identifiers.fingerprint(
        _PLAN_DECISION_AUTHORITY_VERSION,
        (
            authority_source,
            decision_id,
            proposal_id,
            session_id,
            decision,
            idempotency_key_digest,
            command_fingerprint,
            decided_at,
            confirmation_authority,
            decision_schema_version,
            str(decision_local_only),
            str(decision_content_persisted),
            source_run_id,
            source_window_fingerprint,
            expected_predecessor_confirmation_id or "none",
            payload_sha256,
            graph_fingerprint,
            proposal_schema_version,
            proposal_policy_version,
            review_rubric_version,
        ),
    )


def upgrade_trusted_m55_decision_authority(
    connection: sqlite3.Connection,
    identifiers: LocalArtifactIdFactory,
) -> None:
    """Key only rows explicitly queued by the M55-to-M56 migration.

    The migration-created pending row is the durable proof that a decision
    existed before the keyed authority sidecar was introduced.  Missing
    sidecars discovered during ordinary reads are never manufactured here.
    """

    pending = connection.execute(
        """SELECT authority.decision_id,
                  decision.proposal_id,decision.session_id,decision.decision,
                  decision.idempotency_key_digest,decision.command_fingerprint,
                  decision.decided_at,decision.confirmation_authority,
                  decision.schema_version AS decision_schema_version,
                  decision.local_only AS decision_local_only,
                  decision.content_persisted AS decision_content_persisted,
                  proposal.source_run_id,proposal.source_window_fingerprint,
                  proposal.expected_predecessor_confirmation_id,
                  proposal.payload_sha256,proposal.graph_fingerprint,
                  proposal.schema_version AS proposal_schema_version,
                  proposal.policy_version AS proposal_policy_version,
                  proposal.review_rubric_version
           FROM requirement_plan_evidence_decision_authority_m56 authority
           JOIN requirement_plan_evidence_decisions decision
             ON decision.decision_id=authority.decision_id
           JOIN requirement_plan_evidence_proposals proposal
             ON proposal.proposal_id=decision.proposal_id
           WHERE authority.authority_source=?
             AND authority.authority_fingerprint IS NULL
           ORDER BY authority.decision_id""",
        (_PLAN_DECISION_AUTHORITY_UPGRADE_PENDING,),
    ).fetchall()
    for row in pending:
        fingerprint = _decision_authority_fingerprint(
            identifiers,
            authority_source=_PLAN_DECISION_AUTHORITY_UPGRADE,
            decision_id=row["decision_id"],
            proposal_id=row["proposal_id"],
            session_id=row["session_id"],
            decision=row["decision"],
            idempotency_key_digest=row["idempotency_key_digest"],
            command_fingerprint=row["command_fingerprint"],
            decided_at=row["decided_at"],
            confirmation_authority=row["confirmation_authority"],
            decision_schema_version=row["decision_schema_version"],
            decision_local_only=int(row["decision_local_only"]),
            decision_content_persisted=int(row["decision_content_persisted"]),
            source_run_id=row["source_run_id"],
            source_window_fingerprint=row["source_window_fingerprint"],
            expected_predecessor_confirmation_id=(
                row["expected_predecessor_confirmation_id"]
            ),
            payload_sha256=row["payload_sha256"],
            graph_fingerprint=row["graph_fingerprint"],
            proposal_schema_version=row["proposal_schema_version"],
            proposal_policy_version=row["proposal_policy_version"],
            review_rubric_version=row["review_rubric_version"],
        )
        changed = connection.execute(
            """UPDATE requirement_plan_evidence_decision_authority_m56
               SET authority_source=?,authority_fingerprint=?
               WHERE decision_id=? AND authority_source=?
                 AND authority_fingerprint IS NULL""",
            (
                _PLAN_DECISION_AUTHORITY_UPGRADE,
                fingerprint,
                row["decision_id"],
                _PLAN_DECISION_AUTHORITY_UPGRADE_PENDING,
            ),
        ).rowcount
        if changed != 1:
            raise DatabaseInvariantError(
                "requirement-plan decision upgrade authority changed"
            )


def _decision_authority_for_record(
    identifiers: LocalArtifactIdFactory,
    *,
    authority_source: str,
    proposal: RequirementPlanProposalRecord,
    decision: RequirementPlanDecisionRecord,
) -> str:
    return _decision_authority_fingerprint(
        identifiers,
        authority_source=authority_source,
        decision_id=decision.decision_id,
        proposal_id=decision.proposal_id,
        session_id=decision.session_id,
        decision=decision.decision.value,
        idempotency_key_digest=decision.idempotency_key_digest,
        command_fingerprint=decision.command_fingerprint,
        decided_at=to_iso(decision.decided_at),
        confirmation_authority=decision.confirmation_authority,
        decision_schema_version=decision.schema_version,
        decision_local_only=int(decision.local_only),
        decision_content_persisted=int(decision.content_persisted),
        source_run_id=proposal.source_run_id,
        source_window_fingerprint=proposal.source_window_fingerprint,
        expected_predecessor_confirmation_id=(
            proposal.expected_predecessor_confirmation_id
        ),
        payload_sha256=proposal.payload_sha256,
        graph_fingerprint=requirement_plan_graph_fingerprint(proposal),
        proposal_schema_version=proposal.schema_version,
        proposal_policy_version=proposal.policy_version,
        review_rubric_version=proposal.review_rubric_version,
    )


def confirmed_requirement_plan_snapshot(
    view: RequirementPlanProposalView,
) -> RequirementPlanEvidenceSnapshot:
    """Reconstruct one exact historical confirmed graph from its sealed view."""

    decision = view.decision
    if (
        decision is None
        or decision.decision is not RequirementPlanDecisionKind.CONFIRM
    ):
        raise DatabaseInvariantError(
            "requirement-plan confirmed graph is incomplete"
        )
    confirmation_id = decision.decision_id
    plan_id_by_ordinal = {
        ordinal: _derived_id(
            "requirement-plan-confirmed-plan-v1",
            confirmation_id,
            ordinal,
        )
        for ordinal in range(len(view.proposal.plan_items))
    }
    plan_items = tuple(
        sorted(
            (
                ConfirmedPlanEvidence(
                    plan_id=plan_id_by_ordinal[ordinal],
                    coordinate=coordinate,
                )
                for ordinal, coordinate in enumerate(view.proposal.plan_items)
            ),
            key=lambda item: item.plan_id,
        )
    )
    requirements = tuple(
        sorted(
            (
                ConfirmedRequirementEvidence(
                    requirement_id=_derived_id(
                        "requirement-plan-confirmed-requirement-v1",
                        confirmation_id,
                        ordinal,
                    ),
                    coordinate=item.coordinate,
                    disposition=item.disposition,
                    linked_plan_ids=tuple(
                        sorted(
                            plan_id_by_ordinal[index]
                            for index in item.plan_indexes
                        )
                    ),
                )
                for ordinal, item in enumerate(view.proposal.requirements)
            ),
            key=lambda item: item.requirement_id,
        )
    )
    return RequirementPlanEvidenceSnapshot(
        session_id=view.proposal.session_id,
        source_window_fingerprint=view.proposal.source_window_fingerprint,
        confirmation_id=confirmation_id,
        proposal_id=view.proposal.proposal_id,
        producer_receipt=view.proposal.producer_receipt,
        review_rubric_version=view.proposal.review_rubric_version,
        requirements=requirements,
        excluded_user_clauses=view.proposal.excluded_user_clauses,
        plan_items=plan_items,
        complete_user_clause_classification=True,
    )


class SqliteRequirementPlanEvidenceRepository(RequirementPlanRepository):
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

    def issue_proposal(
        self, proposal: RequirementPlanProposalRecord
    ) -> tuple[RequirementPlanProposalView, bool]:
        self._ensure_initialized()
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    """SELECT proposal_id,command_fingerprint,payload_sha256
                       FROM requirement_plan_evidence_proposals
                       WHERE session_id=? AND idempotency_key_digest=?""",
                    (proposal.session_id, proposal.idempotency_key_digest),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["proposal_id"] != proposal.proposal_id
                        or existing["command_fingerprint"]
                        != proposal.command_fingerprint
                        or existing["payload_sha256"] != proposal.payload_sha256
                    ):
                        raise RequirementPlanConflictError(
                            "proposal idempotency key conflicts"
                        )
                    view = self._get_view(connection, proposal.proposal_id)
                    if view is None:
                        raise DatabaseInvariantError(
                            "requirement-plan proposal replay is incomplete"
                        )
                    connection.commit()
                    return view, False
                link_count = sum(
                    len(item.plan_indexes) for item in proposal.requirements
                )
                graph_fingerprint = requirement_plan_graph_fingerprint(proposal)
                connection.execute(
                    """INSERT INTO requirement_plan_evidence_proposals(
                           proposal_id,session_id,source_run_id,
                           source_window_fingerprint,
                           expected_predecessor_confirmation_id,payload_sha256,
                           producer_kind,producer_claim_fingerprint,
                           producer_authority,producer_raw_claim_persisted,
                           review_rubric_version,
                           complete_user_clause_classification,
                           requirement_count,excluded_user_clause_count,
                           plan_item_count,link_count,
                           graph_fingerprint,
                           idempotency_key_digest,command_fingerprint,created_at,
                           schema_version,policy_version,local_only,content_persisted
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,0)""",
                    (
                        proposal.proposal_id,
                        proposal.session_id,
                        proposal.source_run_id,
                        proposal.source_window_fingerprint,
                        proposal.expected_predecessor_confirmation_id,
                        proposal.payload_sha256,
                        proposal.producer_receipt.kind,
                        proposal.producer_receipt.claim_fingerprint,
                        proposal.producer_receipt.authority,
                        int(proposal.producer_receipt.raw_claim_persisted),
                        proposal.review_rubric_version,
                        1,
                        len(proposal.requirements),
                        len(proposal.excluded_user_clauses),
                        len(proposal.plan_items),
                        link_count,
                        graph_fingerprint,
                        proposal.idempotency_key_digest,
                        proposal.command_fingerprint,
                        to_iso(proposal.created_at),
                        proposal.schema_version,
                        proposal.policy_version,
                    ),
                )
                connection.executemany(
                    """INSERT INTO requirement_plan_evidence_excluded_user_clauses(
                           proposal_id,ordinal,message_sequence,clause_index,
                           exclusion_reason,basis_message_sequence,
                           basis_clause_index
                       ) VALUES(?,?,?,?,?,?,?)""",
                    (
                        (
                            proposal.proposal_id,
                            ordinal,
                            item.coordinate.message_sequence,
                            item.coordinate.clause_index,
                            item.reason.value,
                            (
                                None
                                if item.basis_coordinate is None
                                else item.basis_coordinate.message_sequence
                            ),
                            (
                                None
                                if item.basis_coordinate is None
                                else item.basis_coordinate.clause_index
                            ),
                        )
                        for ordinal, item in enumerate(
                            proposal.excluded_user_clauses
                        )
                    ),
                )
                connection.executemany(
                    """INSERT INTO requirement_plan_evidence_requirements(
                           proposal_id,ordinal,message_sequence,clause_index,disposition
                       ) VALUES(?,?,?,?,?)""",
                    (
                        (
                            proposal.proposal_id,
                            ordinal,
                            item.coordinate.message_sequence,
                            item.coordinate.clause_index,
                            item.disposition.value,
                        )
                        for ordinal, item in enumerate(proposal.requirements)
                    ),
                )
                connection.executemany(
                    """INSERT INTO requirement_plan_evidence_plans(
                           proposal_id,ordinal,message_sequence,clause_index
                       ) VALUES(?,?,?,?)""",
                    (
                        (
                            proposal.proposal_id,
                            ordinal,
                            item.message_sequence,
                            item.clause_index,
                        )
                        for ordinal, item in enumerate(proposal.plan_items)
                    ),
                )
                connection.executemany(
                    """INSERT INTO requirement_plan_evidence_links(
                           proposal_id,requirement_ordinal,plan_ordinal
                       ) VALUES(?,?,?)""",
                    (
                        (proposal.proposal_id, requirement_ordinal, plan_ordinal)
                        for requirement_ordinal, item in enumerate(
                            proposal.requirements
                        )
                        for plan_ordinal in item.plan_indexes
                    ),
                )
                connection.execute(
                    """INSERT INTO requirement_plan_evidence_proposal_seals(
                           proposal_id,requirement_count,
                           excluded_user_clause_count,plan_item_count,link_count,
                           payload_sha256,producer_kind,
                           producer_claim_fingerprint,producer_authority,
                           producer_raw_claim_persisted,
                           review_rubric_version,
                           complete_user_clause_classification,
                           graph_fingerprint,
                           sealed_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        proposal.proposal_id,
                        len(proposal.requirements),
                        len(proposal.excluded_user_clauses),
                        len(proposal.plan_items),
                        link_count,
                        proposal.payload_sha256,
                        proposal.producer_receipt.kind,
                        proposal.producer_receipt.claim_fingerprint,
                        proposal.producer_receipt.authority,
                        int(proposal.producer_receipt.raw_claim_persisted),
                        proposal.review_rubric_version,
                        1,
                        graph_fingerprint,
                        to_iso(proposal.created_at),
                    ),
                )
                view = self._get_view(connection, proposal.proposal_id)
                if view is None:
                    raise DatabaseInvariantError(
                        "requirement-plan proposal insert is incomplete"
                    )
                connection.commit()
                return view, True
            except RequirementPlanConflictError:
                connection.rollback()
                raise
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise RequirementPlanConflictError(
                    "requirement-plan proposal conflicts with authority"
                ) from error
            except Exception:
                connection.rollback()
                raise

    def decide(
        self, decision: RequirementPlanDecisionRecord
    ) -> tuple[RequirementPlanProposalView, bool]:
        self._ensure_initialized()
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                proposal = connection.execute(
                    """SELECT session_id FROM requirement_plan_evidence_proposals
                       WHERE proposal_id=?""",
                    (decision.proposal_id,),
                ).fetchone()
                if proposal is None or proposal["session_id"] != decision.session_id:
                    raise RequirementPlanConflictError(
                        "requirement-plan proposal authority changed"
                    )
                existing = connection.execute(
                    """SELECT decision_id,idempotency_key_digest,
                              command_fingerprint,decision
                       FROM requirement_plan_evidence_decisions
                       WHERE proposal_id=?""",
                    (decision.proposal_id,),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["decision_id"] != decision.decision_id
                        or existing["idempotency_key_digest"]
                        != decision.idempotency_key_digest
                        or existing["command_fingerprint"]
                        != decision.command_fingerprint
                        or existing["decision"] != decision.decision.value
                    ):
                        raise RequirementPlanConflictError(
                            "proposal already has another decision"
                        )
                    view = self._get_view(connection, decision.proposal_id)
                    if view is None:
                        raise DatabaseInvariantError(
                            "requirement-plan decision replay is incomplete"
                        )
                    connection.commit()
                    return view, False
                proposal_view = self._get_view(connection, decision.proposal_id)
                if proposal_view is None or proposal_view.decision is not None:
                    raise DatabaseInvariantError(
                        "requirement-plan proposal authority is incomplete"
                    )
                connection.execute(
                    """INSERT INTO requirement_plan_evidence_decisions(
                           decision_id,proposal_id,session_id,decision,
                           idempotency_key_digest,command_fingerprint,decided_at,
                           confirmation_authority,schema_version,
                           local_only,content_persisted
                       ) VALUES(?,?,?,?,?,?,?,?,?,1,0)""",
                    (
                        decision.decision_id,
                        decision.proposal_id,
                        decision.session_id,
                        decision.decision.value,
                        decision.idempotency_key_digest,
                        decision.command_fingerprint,
                        to_iso(decision.decided_at),
                        decision.confirmation_authority,
                        decision.schema_version,
                    ),
                )
                authority_fingerprint = _decision_authority_for_record(
                    self._identifiers,
                    authority_source=_PLAN_DECISION_AUTHORITY_KEYED,
                    proposal=proposal_view.proposal,
                    decision=decision,
                )
                connection.execute(
                    """INSERT INTO requirement_plan_evidence_decision_authority_m56(
                           decision_id,proposal_id,session_id,authority_source,
                           authority_fingerprint,authority_version,
                           local_only,content_persisted
                       ) VALUES(?,?,?,?,?,?,1,0)""",
                    (
                        decision.decision_id,
                        decision.proposal_id,
                        decision.session_id,
                        _PLAN_DECISION_AUTHORITY_KEYED,
                        authority_fingerprint,
                        _PLAN_DECISION_AUTHORITY_VERSION,
                    ),
                )
                view = self._get_view(connection, decision.proposal_id)
                if view is None or view.decision != decision:
                    raise DatabaseInvariantError(
                        "requirement-plan decision failed exact rehydration"
                    )
                connection.commit()
                return view, True
            except RequirementPlanConflictError:
                connection.rollback()
                raise
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise RequirementPlanConflictError(
                    "requirement-plan decision conflicts with authority"
                ) from error
            except Exception:
                connection.rollback()
                raise

    def get_proposal(self, proposal_id: str) -> RequirementPlanProposalView | None:
        self._ensure_initialized()
        require_safe_id(proposal_id)
        with self._connection_scope(readonly=True) as connection:
            return self._get_view(connection, proposal_id)

    def list_proposals_page(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
        snapshot: RequirementPlanProposalPageSnapshot | None = None,
    ) -> tuple[
        tuple[RequirementPlanProposalView, ...],
        RequirementPlanProposalPageSnapshot,
    ]:
        self._ensure_initialized()
        require_safe_id(session_id)
        if not 1 <= limit <= 200 or not 0 <= offset <= 1_000_000:
            raise ValueError("requirement-plan page is outside its bound")
        if snapshot is not None and not hmac.compare_digest(
            snapshot.snapshot_id,
            _page_snapshot_id(self._identifiers, session_id, snapshot),
        ):
            raise RequirementPlanConflictError(
                "requirement-plan page snapshot is invalid"
            )
        with self._connection_scope(readonly=True) as connection:
            try:
                # COUNT, IDs, and hydrated children must describe one exact
                # read snapshot; otherwise a concurrent inert import can make
                # the route falsely claim a page is complete.
                connection.execute("BEGIN")
                if snapshot is None:
                    boundary = connection.execute(
                        """SELECT created_at,proposal_id
                           FROM requirement_plan_evidence_proposals
                           WHERE session_id=?
                           ORDER BY created_at DESC,proposal_id DESC LIMIT 1""",
                        (session_id,),
                    ).fetchone()
                    if boundary is None:
                        page_snapshot = RequirementPlanProposalPageSnapshot(
                            snapshot_id="0" * 64, total=0, decision_count=0
                        )
                    else:
                        boundary_created_at = from_iso(boundary["created_at"])
                        count = connection.execute(
                            """SELECT COUNT(*) AS total
                               FROM requirement_plan_evidence_proposals
                               WHERE session_id=? AND (
                                 created_at < ? OR
                                 (created_at=? AND proposal_id<=?)
                               )""",
                            (
                                session_id,
                                boundary["created_at"],
                                boundary["created_at"],
                                boundary["proposal_id"],
                            ),
                        ).fetchone()
                        if count is None:
                            raise DatabaseInvariantError(
                                "requirement-plan count is missing"
                            )
                        decision_count = connection.execute(
                            """SELECT COUNT(*) AS total
                               FROM requirement_plan_evidence_decisions decision
                               JOIN requirement_plan_evidence_proposals proposal
                                 ON proposal.proposal_id=decision.proposal_id
                               WHERE proposal.session_id=? AND (
                                 proposal.created_at < ? OR
                                 (proposal.created_at=? AND proposal.proposal_id<=?)
                               )""",
                            (
                                session_id,
                                boundary["created_at"],
                                boundary["created_at"],
                                boundary["proposal_id"],
                            ),
                        ).fetchone()
                        if decision_count is None:
                            raise DatabaseInvariantError(
                                "requirement-plan decision count is missing"
                            )
                        page_snapshot = RequirementPlanProposalPageSnapshot(
                            snapshot_id="0" * 64,
                            total=int(count["total"]),
                            decision_count=int(decision_count["total"]),
                            high_water_created_at=boundary_created_at,
                            high_water_proposal_id=boundary["proposal_id"],
                        )
                else:
                    page_snapshot = snapshot
                    if snapshot.total > 0:
                        assert snapshot.high_water_created_at is not None
                        assert snapshot.high_water_proposal_id is not None
                        boundary_text = to_iso(snapshot.high_water_created_at)
                        boundary = connection.execute(
                            """SELECT 1 FROM requirement_plan_evidence_proposals
                               WHERE session_id=? AND proposal_id=? AND created_at=?""",
                            (
                                session_id,
                                snapshot.high_water_proposal_id,
                                boundary_text,
                            ),
                        ).fetchone()
                        count = connection.execute(
                            """SELECT COUNT(*) AS total
                               FROM requirement_plan_evidence_proposals
                               WHERE session_id=? AND (
                                 created_at < ? OR
                                 (created_at=? AND proposal_id<=?)
                               )""",
                            (
                                session_id,
                                boundary_text,
                                boundary_text,
                                snapshot.high_water_proposal_id,
                            ),
                        ).fetchone()
                        decision_count = connection.execute(
                            """SELECT COUNT(*) AS total
                               FROM requirement_plan_evidence_decisions decision
                               JOIN requirement_plan_evidence_proposals proposal
                                 ON proposal.proposal_id=decision.proposal_id
                               WHERE proposal.session_id=? AND (
                                 proposal.created_at < ? OR
                                 (proposal.created_at=? AND proposal.proposal_id<=?)
                               )""",
                            (
                                session_id,
                                boundary_text,
                                boundary_text,
                                snapshot.high_water_proposal_id,
                            ),
                        ).fetchone()
                        if (
                            boundary is None
                            or count is None
                            or int(count["total"]) != snapshot.total
                            or decision_count is None
                            or int(decision_count["total"])
                            != snapshot.decision_count
                        ):
                            raise RequirementPlanConflictError(
                                "requirement-plan page snapshot changed"
                            )
                if snapshot is None:
                    page_snapshot = page_snapshot.model_copy(
                        update={
                            "snapshot_id": _page_snapshot_id(
                                self._identifiers, session_id, page_snapshot
                            )
                        }
                    )
                if page_snapshot.total == 0:
                    rows = ()
                else:
                    assert page_snapshot.high_water_created_at is not None
                    assert page_snapshot.high_water_proposal_id is not None
                    boundary_text = to_iso(page_snapshot.high_water_created_at)
                    rows = connection.execute(
                        """SELECT proposal_id FROM requirement_plan_evidence_proposals
                           WHERE session_id=? AND (
                             created_at < ? OR
                             (created_at=? AND proposal_id<=?)
                           )
                           ORDER BY created_at,proposal_id LIMIT ? OFFSET ?""",
                        (
                            session_id,
                            boundary_text,
                            boundary_text,
                            page_snapshot.high_water_proposal_id,
                            limit,
                            offset,
                        ),
                    ).fetchall()
                views = tuple(
                    self._get_view(connection, row["proposal_id"])
                    for row in rows
                )
                if any(view is None for view in views):
                    raise DatabaseInvariantError(
                        "requirement-plan page is incomplete"
                    )
                result = tuple(view for view in views if view is not None)
                total = page_snapshot.total
                if total < offset + len(result):
                    raise DatabaseInvariantError(
                        "requirement-plan page count is incoherent"
                    )
                connection.commit()
                return result, page_snapshot
            except Exception:
                connection.rollback()
                raise

    def snapshot(
        self, session_id: str, source_window_fingerprint: str
    ) -> RequirementPlanEvidenceSnapshot:
        self._ensure_initialized()
        require_safe_id(session_id)
        require_safe_id(source_window_fingerprint)
        with self._connection_scope(readonly=True) as connection:
            heads = connection.execute(
                """SELECT decision.decision_id,proposal.proposal_id
                   FROM requirement_plan_evidence_decisions decision
                   JOIN requirement_plan_evidence_proposals proposal
                     ON proposal.proposal_id=decision.proposal_id
                   WHERE decision.decision='confirm'
                     AND proposal.session_id=?
                     AND proposal.source_window_fingerprint=?
                     AND NOT EXISTS(
                       SELECT 1 FROM requirement_plan_evidence_decisions child_decision
                       JOIN requirement_plan_evidence_proposals child
                         ON child.proposal_id=child_decision.proposal_id
                       WHERE child_decision.decision='confirm'
                         AND child.expected_predecessor_confirmation_id=
                             decision.decision_id
                     )
                   ORDER BY decision.decided_at DESC,decision.decision_id DESC
                   LIMIT 2""",
                (session_id, source_window_fingerprint),
            ).fetchall()
            if not heads:
                return RequirementPlanEvidenceSnapshot(
                    session_id=session_id,
                    source_window_fingerprint=source_window_fingerprint,
                )
            if len(heads) != 1:
                raise DatabaseInvariantError(
                    "requirement-plan confirmation graph has multiple heads"
                )
            confirmation_id = str(heads[0]["decision_id"])
            proposal_id = str(heads[0]["proposal_id"])
            view = self._get_view(connection, proposal_id)
            if (
                view is None
                or view.decision is None
                or view.decision.decision_id != confirmation_id
                or view.decision.decision is not RequirementPlanDecisionKind.CONFIRM
            ):
                raise DatabaseInvariantError(
                    "requirement-plan confirmed graph is incomplete"
                )
            return confirmed_requirement_plan_snapshot(view)

    def latest_snapshot(self, session_id: str) -> RequirementPlanEvidenceSnapshot:
        self._ensure_initialized()
        require_safe_id(session_id)
        with self._connection_scope(readonly=True) as connection:
            rows = connection.execute(
                """SELECT proposal.source_window_fingerprint,
                          decision.decided_at,decision.decision_id
                   FROM requirement_plan_evidence_decisions decision
                   JOIN requirement_plan_evidence_proposals proposal
                     ON proposal.proposal_id=decision.proposal_id
                   WHERE decision.decision='confirm'
                     AND proposal.session_id=?
                     AND NOT EXISTS(
                       SELECT 1 FROM requirement_plan_evidence_decisions child_decision
                       JOIN requirement_plan_evidence_proposals child
                         ON child.proposal_id=child_decision.proposal_id
                       WHERE child_decision.decision='confirm'
                         AND child.expected_predecessor_confirmation_id=
                             decision.decision_id
                     )
                   ORDER BY decision.decided_at DESC,decision.decision_id DESC
                   LIMIT 1""",
                (session_id,),
            ).fetchall()
        if not rows:
            return RequirementPlanEvidenceSnapshot(
                session_id=session_id,
                source_window_fingerprint="0" * 64,
            )
        return self.snapshot(session_id, rows[0]["source_window_fingerprint"])

    def _get_view(
        self, connection: sqlite3.Connection, proposal_id: str
    ) -> RequirementPlanProposalView | None:
        row = connection.execute(
            """SELECT proposal.*,
                      seal.requirement_count AS sealed_requirement_count,
                      seal.excluded_user_clause_count
                        AS sealed_excluded_user_clause_count,
                      seal.plan_item_count AS sealed_plan_item_count,
                      seal.link_count AS sealed_link_count,
                      seal.payload_sha256 AS sealed_payload_sha256,
                      seal.producer_kind AS sealed_producer_kind,
                      seal.producer_claim_fingerprint
                        AS sealed_producer_claim_fingerprint,
                      seal.producer_authority AS sealed_producer_authority,
                      seal.producer_raw_claim_persisted
                        AS sealed_producer_raw_claim_persisted,
                      seal.review_rubric_version AS sealed_review_rubric_version,
                      seal.complete_user_clause_classification
                        AS sealed_complete_user_clause_classification,
                      seal.graph_fingerprint AS sealed_graph_fingerprint,
                      seal.sealed_at AS sealed_at
               FROM requirement_plan_evidence_proposals proposal
               JOIN requirement_plan_evidence_proposal_seals seal
                 ON seal.proposal_id=proposal.proposal_id
               WHERE proposal.proposal_id=?""",
            (proposal_id,),
        ).fetchone()
        if row is None:
            return None
        plans = tuple(
            PlanCoordinate(
                message_sequence=int(item["message_sequence"]),
                clause_index=int(item["clause_index"]),
            )
            for item in connection.execute(
                """SELECT message_sequence,clause_index
                   FROM requirement_plan_evidence_plans
                   WHERE proposal_id=? ORDER BY ordinal""",
                (proposal_id,),
            ).fetchall()
        )
        excluded_user_clauses = tuple(
            ExcludedRequirementClause(
                coordinate=RequirementCoordinate(
                    message_sequence=int(item["message_sequence"]),
                    clause_index=int(item["clause_index"]),
                ),
                reason=RequirementPlanExclusionReason(item["exclusion_reason"]),
                basis_coordinate=(
                    None
                    if item["basis_message_sequence"] is None
                    else RequirementCoordinate(
                        message_sequence=int(item["basis_message_sequence"]),
                        clause_index=int(item["basis_clause_index"]),
                    )
                ),
            )
            for item in connection.execute(
                """SELECT message_sequence,clause_index,exclusion_reason,
                          basis_message_sequence,basis_clause_index
                   FROM requirement_plan_evidence_excluded_user_clauses
                   WHERE proposal_id=? ORDER BY ordinal""",
                (proposal_id,),
            ).fetchall()
        )
        requirement_coordinates = {
            (int(item["message_sequence"]), int(item["clause_index"]))
            for item in connection.execute(
                """SELECT message_sequence,clause_index
                   FROM requirement_plan_evidence_requirements
                   WHERE proposal_id=?""",
                (proposal_id,),
            ).fetchall()
        }
        excluded_user_coordinates = {
            (item.coordinate.message_sequence, item.coordinate.clause_index)
            for item in excluded_user_clauses
        }
        if requirement_coordinates & excluded_user_coordinates:
            raise DatabaseInvariantError(
                "requirement-plan clause classification overlaps"
            )
        requirements = []
        actual_link_count = 0
        for item in connection.execute(
            """SELECT ordinal,message_sequence,clause_index,disposition
               FROM requirement_plan_evidence_requirements
               WHERE proposal_id=? ORDER BY ordinal""",
            (proposal_id,),
        ).fetchall():
            plan_indexes = tuple(
                int(link["plan_ordinal"])
                for link in connection.execute(
                    """SELECT plan_ordinal
                       FROM requirement_plan_evidence_links
                       WHERE proposal_id=? AND requirement_ordinal=?
                       ORDER BY plan_ordinal""",
                    (proposal_id, int(item["ordinal"])),
                ).fetchall()
            )
            actual_link_count += len(plan_indexes)
            requirements.append(
                RequirementEvidenceEntry(
                    coordinate=RequirementCoordinate(
                        message_sequence=int(item["message_sequence"]),
                        clause_index=int(item["clause_index"]),
                    ),
                    disposition=RequirementDisposition(item["disposition"]),
                    plan_indexes=plan_indexes,
                )
            )
        counts_are_exact = (
            int(row["requirement_count"])
            == int(row["sealed_requirement_count"])
            == len(requirements)
            and int(row["excluded_user_clause_count"])
            == int(row["sealed_excluded_user_clause_count"])
            == len(excluded_user_clauses)
            and int(row["plan_item_count"])
            == int(row["sealed_plan_item_count"])
            == len(plans)
            and int(row["link_count"])
            == int(row["sealed_link_count"])
            == actual_link_count
        )
        if (
            not counts_are_exact
            or row["payload_sha256"] != row["sealed_payload_sha256"]
            or row["created_at"] != row["sealed_at"]
        ):
            raise DatabaseInvariantError(
                "requirement-plan proposal graph is incomplete"
            )
        if (
            row["producer_kind"] != row["sealed_producer_kind"]
            or row["producer_claim_fingerprint"]
            != row["sealed_producer_claim_fingerprint"]
            or row["producer_authority"] != row["sealed_producer_authority"]
            or int(row["producer_raw_claim_persisted"]) != 0
            or int(row["sealed_producer_raw_claim_persisted"]) != 0
            or row["review_rubric_version"]
            != row["sealed_review_rubric_version"]
            or int(row["complete_user_clause_classification"]) != 1
            or int(row["sealed_complete_user_clause_classification"]) != 1
            or row["graph_fingerprint"] != row["sealed_graph_fingerprint"]
        ):
            raise DatabaseInvariantError(
                "requirement-plan producer provenance is not sealed"
            )
        created_at = from_iso(row["created_at"])
        if created_at is None:
            raise DatabaseInvariantError("requirement-plan proposal time is missing")
        proposal = RequirementPlanProposalRecord(
            proposal_id=row["proposal_id"],
            session_id=row["session_id"],
            source_run_id=row["source_run_id"],
            source_window_fingerprint=row["source_window_fingerprint"],
            expected_predecessor_confirmation_id=(
                row["expected_predecessor_confirmation_id"]
            ),
            payload_sha256=row["payload_sha256"],
            idempotency_key_digest=row["idempotency_key_digest"],
            command_fingerprint=row["command_fingerprint"],
            producer_receipt=RequirementPlanProducerReceipt(
                kind=row["producer_kind"],
                claim_fingerprint=row["producer_claim_fingerprint"],
                authority=row["producer_authority"],
                raw_claim_persisted=bool(row["producer_raw_claim_persisted"]),
            ),
            review_rubric_version=row["review_rubric_version"],
            requirements=tuple(requirements),
            excluded_user_clauses=excluded_user_clauses,
            plan_items=plans,
            created_at=created_at,
            schema_version=row["schema_version"],
            policy_version=row["policy_version"],
            local_only=bool(row["local_only"]),
            content_persisted=bool(row["content_persisted"]),
        )
        if requirement_plan_graph_fingerprint(proposal) != row["graph_fingerprint"]:
            raise DatabaseInvariantError(
                "requirement-plan proposal graph fingerprint is invalid"
            )
        decision_row = connection.execute(
            """SELECT decision.*,
                      authority.proposal_id AS authority_proposal_id,
                      authority.session_id AS authority_session_id,
                      authority.authority_source,
                      authority.authority_fingerprint,
                      authority.authority_version,
                      authority.local_only AS authority_local_only,
                      authority.content_persisted AS authority_content_persisted
               FROM requirement_plan_evidence_decisions decision
               LEFT JOIN requirement_plan_evidence_decision_authority_m56 authority
                 ON authority.decision_id=decision.decision_id
               WHERE decision.proposal_id=?""",
            (proposal_id,),
        ).fetchone()
        decision = None
        if decision_row is not None:
            decided_at = from_iso(decision_row["decided_at"])
            if decided_at is None:
                raise DatabaseInvariantError(
                    "requirement-plan decision time is missing"
                )
            decision = RequirementPlanDecisionRecord(
                decision_id=decision_row["decision_id"],
                proposal_id=decision_row["proposal_id"],
                session_id=decision_row["session_id"],
                decision=RequirementPlanDecisionKind(decision_row["decision"]),
                idempotency_key_digest=decision_row["idempotency_key_digest"],
                command_fingerprint=decision_row["command_fingerprint"],
                decided_at=decided_at,
                confirmation_authority=decision_row["confirmation_authority"],
                schema_version=decision_row["schema_version"],
                local_only=bool(decision_row["local_only"]),
                content_persisted=bool(decision_row["content_persisted"]),
            )
            if (
                decision.proposal_id != proposal.proposal_id
                or decision.session_id != proposal.session_id
                or decision_row["authority_proposal_id"] != proposal.proposal_id
                or decision_row["authority_session_id"] != proposal.session_id
                or decision_row["authority_version"]
                != _PLAN_DECISION_AUTHORITY_VERSION
                or decision_row["authority_source"]
                not in (
                    _PLAN_DECISION_AUTHORITY_KEYED,
                    _PLAN_DECISION_AUTHORITY_UPGRADE,
                )
                or decision_row["authority_local_only"] != 1
                or decision_row["authority_content_persisted"] != 0
                or decision_row["authority_fingerprint"] is None
            ):
                raise DatabaseInvariantError(
                    "requirement-plan decision authority is incomplete"
                )
            expected_decision_authority = _decision_authority_for_record(
                self._identifiers,
                authority_source=decision_row["authority_source"],
                proposal=proposal,
                decision=decision,
            )
            if not hmac.compare_digest(
                decision_row["authority_fingerprint"],
                expected_decision_authority,
            ):
                raise DatabaseInvariantError(
                    "requirement-plan decision authority is invalid"
                )
        status = (
            RequirementPlanProposalStatus.PROPOSED
            if decision is None
            else RequirementPlanProposalStatus.CONFIRMED
            if decision.decision is RequirementPlanDecisionKind.CONFIRM
            else RequirementPlanProposalStatus.REJECTED
        )
        return RequirementPlanProposalView(
            proposal=proposal,
            decision=decision,
            status=status,
        )


__all__ = ("SqliteRequirementPlanEvidenceRepository",)
