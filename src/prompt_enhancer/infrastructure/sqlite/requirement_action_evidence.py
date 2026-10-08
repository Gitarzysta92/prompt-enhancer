"""SQLite adapter for reviewed, content-free requirement-action evidence."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import hmac
import sqlite3

from ...application.analysis.evidence_contracts import (
    ActionFamily,
    ActionState,
    TypedEvidenceProvenance,
)
from ...application.analysis.requirement_action_evidence import (
    ConfirmedRequirementActionLink,
    RequirementActionCandidate,
    RequirementActionCandidateManifest,
    RequirementActionConflictError,
    RequirementActionDecisionKind,
    RequirementActionDecisionRecord,
    RequirementActionEvidenceSnapshot,
    RequirementActionProposalPageSnapshot,
    RequirementActionProposalRecord,
    RequirementActionProposalStatus,
    RequirementActionProposalView,
    RequirementActionRepository,
    RequirementActionRequirement,
    requirement_action_candidate_manifest_fingerprint,
    requirement_action_decision_authority_fingerprint,
    requirement_action_evidence_snapshot_fingerprint,
    requirement_action_graph_fingerprint,
)
from ...application.analysis.requirement_plan_evidence import (
    RequirementCoordinate,
    RequirementPlanProducerReceipt,
)
from ...database import DatabaseInvariantError
from ...domain import EventKind, Provider, ToolCategory
from ..identifiers import LocalArtifactIdFactory
from ._common import ConnectionScope, from_iso, require_safe_id, to_iso


def _page_snapshot_id(
    identifiers: LocalArtifactIdFactory,
    session_id: str,
    snapshot: RequirementActionProposalPageSnapshot,
) -> str:
    return identifiers.fingerprint(
        "requirement-action-proposal-page-snapshot-v1",
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


def _derived_requirement_id(confirmation_id: str, ordinal: int) -> str:
    """Reproduce the frozen M55 confirmed-requirement identifier."""

    return hashlib.sha256(
        (
            "requirement-plan-confirmed-requirement-v1"
            f"\x1f{confirmation_id}\x1f{ordinal}"
        ).encode("ascii")
    ).hexdigest()


class SqliteRequirementActionEvidenceRepository(RequirementActionRepository):
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
        self, proposal: RequirementActionProposalRecord
    ) -> tuple[RequirementActionProposalView, bool]:
        self._ensure_initialized()
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    """SELECT proposal_id,command_fingerprint,payload_sha256
                       FROM requirement_action_evidence_proposals
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
                        raise RequirementActionConflictError(
                            "proposal idempotency key conflicts"
                        )
                    view = self._get_view(connection, proposal.proposal_id)
                    if view is None:
                        raise DatabaseInvariantError(
                            "requirement-action proposal replay is incomplete"
                        )
                    connection.commit()
                    return view, False

                graph_fingerprint = requirement_action_graph_fingerprint(proposal)
                link_count = sum(len(item.action_ids) for item in proposal.links)
                provenance = proposal.candidate_provenance
                connection.execute(
                    """INSERT INTO requirement_action_evidence_proposals(
                           proposal_id,session_id,source_run_id,
                           source_window_fingerprint,
                           requirement_plan_confirmation_id,
                           requirement_plan_evidence_fingerprint,
                           candidate_manifest_fingerprint,
                           expected_predecessor_confirmation_id,payload_sha256,
                           idempotency_key_digest,command_fingerprint,
                           producer_kind,producer_claim_fingerprint,
                           producer_authority,producer_raw_claim_persisted,
                           candidate_provider,candidate_provider_version,
                           candidate_adapter_version,candidate_decoder_key,
                           candidate_decoder_version,
                           candidate_source_schema_version,
                           candidate_evidence_schema_version,
                           candidate_provenance_extraction_complete,
                           candidate_extraction_complete,
                           candidate_enumeration_complete,
                           requirement_count,candidate_count,link_count,
                           graph_fingerprint,created_at,schema_version,
                           policy_version,review_rubric_version,
                           local_only,content_persisted
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,0)""",
                    (
                        proposal.proposal_id,
                        proposal.session_id,
                        proposal.source_run_id,
                        proposal.source_window_fingerprint,
                        proposal.requirement_plan_confirmation_id,
                        proposal.requirement_plan_evidence_fingerprint,
                        proposal.candidate_manifest_fingerprint,
                        proposal.expected_predecessor_confirmation_id,
                        proposal.payload_sha256,
                        proposal.idempotency_key_digest,
                        proposal.command_fingerprint,
                        proposal.producer_receipt.kind,
                        proposal.producer_receipt.claim_fingerprint,
                        proposal.producer_receipt.authority,
                        int(proposal.producer_receipt.raw_claim_persisted),
                        provenance.provider.value,
                        provenance.provider_version,
                        provenance.adapter_version,
                        provenance.decoder_key,
                        provenance.decoder_version,
                        provenance.source_schema_version,
                        provenance.evidence_schema_version,
                        int(provenance.extraction_complete),
                        int(proposal.candidate_extraction_complete),
                        int(proposal.candidate_enumeration_complete),
                        len(proposal.requirements),
                        len(proposal.candidates),
                        link_count,
                        graph_fingerprint,
                        to_iso(proposal.created_at),
                        proposal.schema_version,
                        proposal.policy_version,
                        proposal.review_rubric_version,
                    ),
                )
                connection.executemany(
                    """INSERT INTO requirement_action_evidence_requirements(
                           proposal_id,requirement_index,requirement_id,
                           message_sequence,clause_index
                       ) VALUES(?,?,?,?,?)""",
                    (
                        (
                            proposal.proposal_id,
                            item.requirement_index,
                            item.requirement_id,
                            item.coordinate.message_sequence,
                            item.coordinate.clause_index,
                        )
                        for item in proposal.requirements
                    ),
                )
                connection.executemany(
                    """INSERT INTO requirement_action_evidence_candidates(
                           proposal_id,candidate_index,action_id,
                           source_reference_id,sequence,event_kind,
                           tool_category,occurred_at,duration_ms,family,state
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        (
                            proposal.proposal_id,
                            item.candidate_index,
                            item.action_id,
                            item.source_reference_id,
                            item.sequence,
                            item.event_kind.value,
                            (
                                None
                                if item.tool_category is None
                                else item.tool_category.value
                            ),
                            to_iso(item.occurred_at),
                            item.duration_ms,
                            item.family.value,
                            item.state.value,
                        )
                        for item in proposal.candidates
                    ),
                )
                requirement_index = {
                    item.requirement_id: item.requirement_index
                    for item in proposal.requirements
                }
                candidate_index = {
                    item.action_id: item.candidate_index
                    for item in proposal.candidates
                }
                connection.executemany(
                    """INSERT INTO requirement_action_evidence_links(
                           proposal_id,requirement_index,candidate_index
                       ) VALUES(?,?,?)""",
                    (
                        (
                            proposal.proposal_id,
                            requirement_index[item.requirement_id],
                            candidate_index[action_id],
                        )
                        for item in proposal.links
                        for action_id in item.action_ids
                    ),
                )
                connection.execute(
                    """INSERT INTO requirement_action_evidence_proposal_seals(
                           proposal_id,requirement_count,candidate_count,
                           link_count,payload_sha256,
                           requirement_plan_confirmation_id,
                           requirement_plan_evidence_fingerprint,
                           candidate_manifest_fingerprint,producer_kind,
                           producer_claim_fingerprint,producer_authority,
                           producer_raw_claim_persisted,candidate_provider,
                           candidate_provider_version,candidate_adapter_version,
                           candidate_decoder_key,candidate_decoder_version,
                           candidate_source_schema_version,
                           candidate_evidence_schema_version,
                           candidate_provenance_extraction_complete,
                           candidate_extraction_complete,
                           candidate_enumeration_complete,schema_version,
                           policy_version,review_rubric_version,
                           graph_fingerprint,sealed_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        proposal.proposal_id,
                        len(proposal.requirements),
                        len(proposal.candidates),
                        link_count,
                        proposal.payload_sha256,
                        proposal.requirement_plan_confirmation_id,
                        proposal.requirement_plan_evidence_fingerprint,
                        proposal.candidate_manifest_fingerprint,
                        proposal.producer_receipt.kind,
                        proposal.producer_receipt.claim_fingerprint,
                        proposal.producer_receipt.authority,
                        int(proposal.producer_receipt.raw_claim_persisted),
                        provenance.provider.value,
                        provenance.provider_version,
                        provenance.adapter_version,
                        provenance.decoder_key,
                        provenance.decoder_version,
                        provenance.source_schema_version,
                        provenance.evidence_schema_version,
                        int(provenance.extraction_complete),
                        int(proposal.candidate_extraction_complete),
                        int(proposal.candidate_enumeration_complete),
                        proposal.schema_version,
                        proposal.policy_version,
                        proposal.review_rubric_version,
                        graph_fingerprint,
                        to_iso(proposal.created_at),
                    ),
                )
                view = self._get_view(connection, proposal.proposal_id)
                if view is None or view.proposal != proposal:
                    raise DatabaseInvariantError(
                        "requirement-action proposal failed exact rehydration"
                    )
                connection.commit()
                return view, True
            except RequirementActionConflictError:
                connection.rollback()
                raise
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise RequirementActionConflictError(
                    "requirement-action proposal conflicts with authority"
                ) from error
            except Exception:
                connection.rollback()
                raise

    def decide(
        self, decision: RequirementActionDecisionRecord
    ) -> tuple[RequirementActionProposalView, bool]:
        self._ensure_initialized()
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                # Replay is intentionally resolved before current-head checks:
                # a committed decision remains idempotent after its source ages.
                existing = connection.execute(
                    """SELECT * FROM requirement_action_evidence_decisions
                       WHERE proposal_id=?""",
                    (decision.proposal_id,),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["decision_id"] != decision.decision_id
                        or existing["session_id"] != decision.session_id
                        or existing["decision"] != decision.decision.value
                        or existing["idempotency_key_digest"]
                        != decision.idempotency_key_digest
                        or existing["command_fingerprint"]
                        != decision.command_fingerprint
                        or existing["reviewed_descriptor_set_fingerprint"]
                        != decision.reviewed_descriptor_set_fingerprint
                        or existing["decision_authority_fingerprint"]
                        != decision.decision_authority_fingerprint
                    ):
                        raise RequirementActionConflictError(
                            "proposal already has another decision"
                        )
                    view = self._get_view(connection, decision.proposal_id)
                    if view is None:
                        raise DatabaseInvariantError(
                            "requirement-action decision replay is incomplete"
                        )
                    connection.commit()
                    return view, False
                proposal = connection.execute(
                    """SELECT session_id FROM requirement_action_evidence_proposals
                       WHERE proposal_id=?""",
                    (decision.proposal_id,),
                ).fetchone()
                if proposal is None or proposal["session_id"] != decision.session_id:
                    raise RequirementActionConflictError(
                        "requirement-action proposal authority changed"
                    )
                connection.execute(
                    """INSERT INTO requirement_action_evidence_decisions(
                           decision_id,proposal_id,session_id,decision,
                           idempotency_key_digest,command_fingerprint,
                           reviewed_descriptor_set_fingerprint,
                           decision_authority_fingerprint,
                           decided_at,confirmation_authority,schema_version,
                           local_only,content_persisted
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,1,0)""",
                    (
                        decision.decision_id,
                        decision.proposal_id,
                        decision.session_id,
                        decision.decision.value,
                        decision.idempotency_key_digest,
                        decision.command_fingerprint,
                        decision.reviewed_descriptor_set_fingerprint,
                        decision.decision_authority_fingerprint,
                        to_iso(decision.decided_at),
                        decision.confirmation_authority,
                        decision.schema_version,
                    ),
                )
                view = self._get_view(connection, decision.proposal_id)
                if view is None or view.decision != decision:
                    raise DatabaseInvariantError(
                        "requirement-action decision failed exact rehydration"
                    )
                connection.commit()
                return view, True
            except RequirementActionConflictError:
                connection.rollback()
                raise
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise RequirementActionConflictError(
                    "requirement-action decision conflicts with authority"
                ) from error
            except Exception:
                connection.rollback()
                raise

    def get_proposal(self, proposal_id: str) -> RequirementActionProposalView | None:
        self._ensure_initialized()
        require_safe_id(proposal_id)
        with self._connection_scope(readonly=True) as connection:
            connection.execute("BEGIN")
            return self._get_view(connection, proposal_id)

    def list_proposals_page(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
        snapshot: RequirementActionProposalPageSnapshot | None = None,
    ) -> tuple[
        tuple[RequirementActionProposalView, ...],
        RequirementActionProposalPageSnapshot,
    ]:
        self._ensure_initialized()
        require_safe_id(session_id)
        if not 1 <= limit <= 200 or not 0 <= offset <= 1_000_000:
            raise ValueError("requirement-action page is outside its bound")
        if snapshot is not None and not hmac.compare_digest(
            snapshot.snapshot_id,
            _page_snapshot_id(self._identifiers, session_id, snapshot),
        ):
            raise RequirementActionConflictError(
                "requirement-action page snapshot is invalid"
            )
        with self._connection_scope(readonly=True) as connection:
            try:
                connection.execute("BEGIN")
                if snapshot is None:
                    boundary = connection.execute(
                        """SELECT created_at,proposal_id
                           FROM requirement_action_evidence_proposals
                           WHERE session_id=?
                           ORDER BY created_at DESC,proposal_id DESC LIMIT 1""",
                        (session_id,),
                    ).fetchone()
                    if boundary is None:
                        page_snapshot = RequirementActionProposalPageSnapshot(
                            snapshot_id="0" * 64,
                            total=0,
                            decision_count=0,
                        )
                    else:
                        page_snapshot = self._page_snapshot(
                            connection,
                            session_id,
                            boundary["created_at"],
                            boundary["proposal_id"],
                        )
                else:
                    page_snapshot = snapshot
                    if snapshot.total > 0:
                        assert snapshot.high_water_created_at is not None
                        assert snapshot.high_water_proposal_id is not None
                        boundary_text = to_iso(snapshot.high_water_created_at)
                        current = self._page_snapshot(
                            connection,
                            session_id,
                            boundary_text,
                            snapshot.high_water_proposal_id,
                        )
                        boundary = connection.execute(
                            """SELECT 1 FROM requirement_action_evidence_proposals
                               WHERE session_id=? AND proposal_id=? AND created_at=?""",
                            (
                                session_id,
                                snapshot.high_water_proposal_id,
                                boundary_text,
                            ),
                        ).fetchone()
                        if (
                            boundary is None
                            or current.total != snapshot.total
                            or current.decision_count != snapshot.decision_count
                        ):
                            raise RequirementActionConflictError(
                                "requirement-action page snapshot changed"
                            )
                if snapshot is None:
                    page_snapshot = page_snapshot.model_copy(
                        update={
                            "snapshot_id": _page_snapshot_id(
                                self._identifiers,
                                session_id,
                                page_snapshot,
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
                        """SELECT proposal_id
                           FROM requirement_action_evidence_proposals
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
                    self._get_view(connection, row["proposal_id"]) for row in rows
                )
                if any(view is None for view in views):
                    raise DatabaseInvariantError(
                        "requirement-action page is incomplete"
                    )
                result = tuple(view for view in views if view is not None)
                if page_snapshot.total < offset + len(result):
                    raise DatabaseInvariantError(
                        "requirement-action page count is incoherent"
                    )
                connection.commit()
                return result, page_snapshot
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _page_snapshot(
        connection: sqlite3.Connection,
        session_id: str,
        boundary_text: str,
        boundary_proposal_id: str,
    ) -> RequirementActionProposalPageSnapshot:
        count = connection.execute(
            """SELECT COUNT(*) AS total
               FROM requirement_action_evidence_proposals
               WHERE session_id=? AND (
                 created_at < ? OR (created_at=? AND proposal_id<=?)
               )""",
            (
                session_id,
                boundary_text,
                boundary_text,
                boundary_proposal_id,
            ),
        ).fetchone()
        decisions = connection.execute(
            """SELECT COUNT(*) AS total
               FROM requirement_action_evidence_decisions decision
               JOIN requirement_action_evidence_proposals proposal
                 ON proposal.proposal_id=decision.proposal_id
               WHERE proposal.session_id=? AND (
                 proposal.created_at < ? OR
                 (proposal.created_at=? AND proposal.proposal_id<=?)
               )""",
            (
                session_id,
                boundary_text,
                boundary_text,
                boundary_proposal_id,
            ),
        ).fetchone()
        if count is None or decisions is None:
            raise DatabaseInvariantError("requirement-action page count is missing")
        created_at = from_iso(boundary_text)
        if created_at is None:
            raise DatabaseInvariantError("requirement-action page time is missing")
        return RequirementActionProposalPageSnapshot(
            snapshot_id="0" * 64,
            total=int(count["total"]),
            decision_count=int(decisions["total"]),
            high_water_created_at=created_at,
            high_water_proposal_id=boundary_proposal_id,
        )

    def snapshot(
        self, session_id: str, source_window_fingerprint: str
    ) -> RequirementActionEvidenceSnapshot:
        self._ensure_initialized()
        require_safe_id(session_id)
        require_safe_id(source_window_fingerprint)
        with self._connection_scope(readonly=True) as connection:
            # One read transaction prevents a concurrently appended decision
            # from producing a torn head/view/snapshot combination.
            connection.execute("BEGIN")
            heads = connection.execute(
                """SELECT decision.decision_id,proposal.proposal_id
                   FROM requirement_action_evidence_decisions decision
                   JOIN requirement_action_evidence_proposals proposal
                     ON proposal.proposal_id=decision.proposal_id
                   WHERE decision.decision='confirm'
                     AND proposal.session_id=?
                     AND proposal.source_window_fingerprint=?
                     AND NOT EXISTS(
                       SELECT 1 FROM requirement_action_evidence_decisions child_decision
                       JOIN requirement_action_evidence_proposals child
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
                return RequirementActionEvidenceSnapshot(
                    session_id=session_id,
                    source_window_fingerprint=source_window_fingerprint,
                )
            if len(heads) != 1:
                raise DatabaseInvariantError(
                    "requirement-action confirmation graph has multiple heads"
                )
            confirmation_id = str(heads[0]["decision_id"])
            view = self._get_view(connection, str(heads[0]["proposal_id"]))
            if (
                view is None
                or view.decision is None
                or view.decision.decision_id != confirmation_id
                or view.decision.decision is not RequirementActionDecisionKind.CONFIRM
            ):
                raise DatabaseInvariantError(
                    "requirement-action confirmed graph is incomplete"
                )
            proposal = view.proposal
            manifest = self._manifest(proposal)
            placeholder = RequirementActionEvidenceSnapshot(
                session_id=session_id,
                source_run_id=proposal.source_run_id,
                source_window_fingerprint=source_window_fingerprint,
                requirement_plan_confirmation_id=(
                    proposal.requirement_plan_confirmation_id
                ),
                requirement_plan_evidence_fingerprint=(
                    proposal.requirement_plan_evidence_fingerprint
                ),
                confirmation_id=confirmation_id,
                proposal_id=proposal.proposal_id,
                reviewed_descriptor_set_fingerprint=(
                    view.decision.reviewed_descriptor_set_fingerprint
                ),
                producer_receipt=proposal.producer_receipt,
                candidate_manifest=manifest,
                requirements=proposal.requirements,
                links=proposal.links,
                complete_requirement_enumeration=True,
                complete_action_candidate_enumeration=True,
                complete_requirement_link_classification=True,
                evidence_fingerprint="0" * 64,
            )
            fingerprint = requirement_action_evidence_snapshot_fingerprint(
                placeholder,
                self._identifiers,
            )
            return RequirementActionEvidenceSnapshot.model_validate(
                {
                    **placeholder.model_dump(),
                    "evidence_fingerprint": fingerprint,
                }
            )

    def latest_snapshot(self, session_id: str) -> RequirementActionEvidenceSnapshot:
        self._ensure_initialized()
        require_safe_id(session_id)
        with self._connection_scope(readonly=True) as connection:
            connection.execute("BEGIN")
            row = connection.execute(
                """SELECT proposal.source_window_fingerprint,
                          decision.decision_id
                   FROM requirement_action_evidence_decisions decision
                   JOIN requirement_action_evidence_proposals proposal
                     ON proposal.proposal_id=decision.proposal_id
                   WHERE decision.decision='confirm'
                     AND proposal.session_id=?
                     AND NOT EXISTS(
                       SELECT 1 FROM requirement_action_evidence_decisions child_decision
                       JOIN requirement_action_evidence_proposals child
                         ON child.proposal_id=child_decision.proposal_id
                       WHERE child_decision.decision='confirm'
                         AND child.expected_predecessor_confirmation_id=
                             decision.decision_id
                     )
                   ORDER BY decision.decided_at DESC,decision.decision_id DESC
                   LIMIT 1""",
                (session_id,),
            ).fetchone()
        if row is None:
            return RequirementActionEvidenceSnapshot(
                session_id=session_id,
                source_window_fingerprint="0" * 64,
            )
        snapshot = self.snapshot(session_id, row["source_window_fingerprint"])
        with self._connection_scope(readonly=True) as connection:
            current = connection.execute(
                """SELECT proposal.source_window_fingerprint,
                          decision.decision_id
                   FROM requirement_action_evidence_decisions decision
                   JOIN requirement_action_evidence_proposals proposal
                     ON proposal.proposal_id=decision.proposal_id
                   WHERE decision.decision='confirm'
                     AND proposal.session_id=?
                     AND NOT EXISTS(
                       SELECT 1 FROM requirement_action_evidence_decisions child_decision
                       JOIN requirement_action_evidence_proposals child
                         ON child.proposal_id=child_decision.proposal_id
                       WHERE child_decision.decision='confirm'
                         AND child.expected_predecessor_confirmation_id=
                             decision.decision_id
                     )
                   ORDER BY decision.decided_at DESC,decision.decision_id DESC
                   LIMIT 1""",
                (session_id,),
            ).fetchone()
        if (
            current is None
            or current["source_window_fingerprint"]
            != snapshot.source_window_fingerprint
            or current["decision_id"] != snapshot.confirmation_id
        ):
            raise DatabaseInvariantError(
                "requirement-action latest authority changed during read"
            )
        return snapshot

    @staticmethod
    def _manifest(
        proposal: RequirementActionProposalRecord,
    ) -> RequirementActionCandidateManifest:
        manifest = RequirementActionCandidateManifest(
            session_id=proposal.session_id,
            source_run_id=proposal.source_run_id,
            source_window_fingerprint=proposal.source_window_fingerprint,
            provenance=proposal.candidate_provenance,
            extraction_complete=proposal.candidate_extraction_complete,
            enumeration_complete=proposal.candidate_enumeration_complete,
            actions=proposal.candidates,
            manifest_fingerprint=proposal.candidate_manifest_fingerprint,
        )
        if (
            requirement_action_candidate_manifest_fingerprint(manifest)
            != manifest.manifest_fingerprint
        ):
            raise DatabaseInvariantError(
                "requirement-action candidate manifest seal is invalid"
            )
        return manifest

    def _get_view(
        self,
        connection: sqlite3.Connection,
        proposal_id: str,
    ) -> RequirementActionProposalView | None:
        row = connection.execute(
            """SELECT proposal.*,
                      seal.requirement_count AS sealed_requirement_count,
                      seal.candidate_count AS sealed_candidate_count,
                      seal.link_count AS sealed_link_count,
                      seal.payload_sha256 AS sealed_payload_sha256,
                      seal.requirement_plan_confirmation_id
                        AS sealed_requirement_plan_confirmation_id,
                      seal.requirement_plan_evidence_fingerprint
                        AS sealed_requirement_plan_evidence_fingerprint,
                      seal.candidate_manifest_fingerprint
                        AS sealed_candidate_manifest_fingerprint,
                      seal.producer_kind AS sealed_producer_kind,
                      seal.producer_claim_fingerprint
                        AS sealed_producer_claim_fingerprint,
                      seal.producer_authority AS sealed_producer_authority,
                      seal.producer_raw_claim_persisted
                        AS sealed_producer_raw_claim_persisted,
                      seal.candidate_provider AS sealed_candidate_provider,
                      seal.candidate_provider_version
                        AS sealed_candidate_provider_version,
                      seal.candidate_adapter_version
                        AS sealed_candidate_adapter_version,
                      seal.candidate_decoder_key AS sealed_candidate_decoder_key,
                      seal.candidate_decoder_version
                        AS sealed_candidate_decoder_version,
                      seal.candidate_source_schema_version
                        AS sealed_candidate_source_schema_version,
                      seal.candidate_evidence_schema_version
                        AS sealed_candidate_evidence_schema_version,
                      seal.candidate_provenance_extraction_complete
                        AS sealed_candidate_provenance_extraction_complete,
                      seal.candidate_extraction_complete
                        AS sealed_candidate_extraction_complete,
                      seal.candidate_enumeration_complete
                        AS sealed_candidate_enumeration_complete,
                      seal.schema_version AS sealed_schema_version,
                      seal.policy_version AS sealed_policy_version,
                      seal.review_rubric_version AS sealed_review_rubric_version,
                      seal.graph_fingerprint AS sealed_graph_fingerprint,
                      seal.sealed_at AS sealed_at
               FROM requirement_action_evidence_proposals proposal
               JOIN requirement_action_evidence_proposal_seals seal
                 ON seal.proposal_id=proposal.proposal_id
               WHERE proposal.proposal_id=?""",
            (proposal_id,),
        ).fetchone()
        if row is None:
            return None
        requirements = tuple(
            RequirementActionRequirement(
                requirement_index=int(item["requirement_index"]),
                requirement_id=item["requirement_id"],
                coordinate=RequirementCoordinate(
                    message_sequence=int(item["message_sequence"]),
                    clause_index=int(item["clause_index"]),
                ),
            )
            for item in connection.execute(
                """SELECT * FROM requirement_action_evidence_requirements
                   WHERE proposal_id=? ORDER BY requirement_index""",
                (proposal_id,),
            ).fetchall()
        )
        candidates = tuple(
            RequirementActionCandidate(
                candidate_index=int(item["candidate_index"]),
                action_id=item["action_id"],
                source_reference_id=item["source_reference_id"],
                sequence=int(item["sequence"]),
                event_kind=EventKind(item["event_kind"]),
                tool_category=(
                    None
                    if item["tool_category"] is None
                    else ToolCategory(item["tool_category"])
                ),
                occurred_at=from_iso(item["occurred_at"]),
                duration_ms=item["duration_ms"],
                family=ActionFamily(item["family"]),
                state=ActionState(item["state"]),
            )
            for item in connection.execute(
                """SELECT * FROM requirement_action_evidence_candidates
                   WHERE proposal_id=? ORDER BY candidate_index""",
                (proposal_id,),
            ).fetchall()
        )
        action_id_by_index = {
            item.candidate_index: item.action_id for item in candidates
        }
        links = tuple(
            ConfirmedRequirementActionLink(
                requirement_id=requirement.requirement_id,
                action_ids=tuple(
                    sorted(
                        action_id_by_index[int(link["candidate_index"])]
                        for link in connection.execute(
                            """SELECT candidate_index
                               FROM requirement_action_evidence_links
                               WHERE proposal_id=? AND requirement_index=?
                               ORDER BY candidate_index""",
                            (proposal_id, requirement.requirement_index),
                        ).fetchall()
                    )
                ),
            )
            for requirement in requirements
        )
        link_count = sum(len(item.action_ids) for item in links)
        sealed_pairs = (
            ("requirement_count", "sealed_requirement_count"),
            ("candidate_count", "sealed_candidate_count"),
            ("link_count", "sealed_link_count"),
            ("payload_sha256", "sealed_payload_sha256"),
            (
                "requirement_plan_confirmation_id",
                "sealed_requirement_plan_confirmation_id",
            ),
            (
                "requirement_plan_evidence_fingerprint",
                "sealed_requirement_plan_evidence_fingerprint",
            ),
            (
                "candidate_manifest_fingerprint",
                "sealed_candidate_manifest_fingerprint",
            ),
            ("producer_kind", "sealed_producer_kind"),
            ("producer_claim_fingerprint", "sealed_producer_claim_fingerprint"),
            ("producer_authority", "sealed_producer_authority"),
            ("producer_raw_claim_persisted", "sealed_producer_raw_claim_persisted"),
            ("candidate_provider", "sealed_candidate_provider"),
            ("candidate_provider_version", "sealed_candidate_provider_version"),
            ("candidate_adapter_version", "sealed_candidate_adapter_version"),
            ("candidate_decoder_key", "sealed_candidate_decoder_key"),
            ("candidate_decoder_version", "sealed_candidate_decoder_version"),
            (
                "candidate_source_schema_version",
                "sealed_candidate_source_schema_version",
            ),
            (
                "candidate_evidence_schema_version",
                "sealed_candidate_evidence_schema_version",
            ),
            (
                "candidate_provenance_extraction_complete",
                "sealed_candidate_provenance_extraction_complete",
            ),
            (
                "candidate_extraction_complete",
                "sealed_candidate_extraction_complete",
            ),
            (
                "candidate_enumeration_complete",
                "sealed_candidate_enumeration_complete",
            ),
            ("schema_version", "sealed_schema_version"),
            ("policy_version", "sealed_policy_version"),
            ("review_rubric_version", "sealed_review_rubric_version"),
            ("graph_fingerprint", "sealed_graph_fingerprint"),
            ("created_at", "sealed_at"),
        )
        if (
            any(row[left] != row[right] for left, right in sealed_pairs)
            or int(row["requirement_count"]) != len(requirements)
            or int(row["candidate_count"]) != len(candidates)
            or int(row["link_count"]) != link_count
            or int(row["producer_raw_claim_persisted"]) != 0
            or int(row["sealed_producer_raw_claim_persisted"]) != 0
        ):
            raise DatabaseInvariantError(
                "requirement-action proposal graph is incomplete"
            )
        source_rows = connection.execute(
            """SELECT requirement.ordinal,requirement.message_sequence,
                      requirement.clause_index
               FROM requirement_plan_evidence_decisions decision
               JOIN requirement_plan_evidence_requirements requirement
                 ON requirement.proposal_id=decision.proposal_id
               WHERE decision.decision_id=? AND decision.decision='confirm'
               ORDER BY requirement.ordinal""",
            (row["requirement_plan_confirmation_id"],),
        ).fetchall()
        expected_requirements = tuple(
            sorted(
                (
                    RequirementActionRequirement(
                        requirement_index=0,
                        requirement_id=_derived_requirement_id(
                            row["requirement_plan_confirmation_id"],
                            int(source["ordinal"]),
                        ),
                        coordinate=RequirementCoordinate(
                            message_sequence=int(source["message_sequence"]),
                            clause_index=int(source["clause_index"]),
                        ),
                    )
                    for source in source_rows
                ),
                key=lambda item: item.requirement_id,
            )
        )
        expected_requirements = tuple(
            item.model_copy(update={"requirement_index": index})
            for index, item in enumerate(expected_requirements)
        )
        if requirements != expected_requirements:
            raise DatabaseInvariantError(
                "requirement-action requirements do not match confirmed authority"
            )
        created_at = from_iso(row["created_at"])
        if created_at is None:
            raise DatabaseInvariantError(
                "requirement-action proposal time is missing"
            )
        proposal = RequirementActionProposalRecord(
            proposal_id=row["proposal_id"],
            session_id=row["session_id"],
            source_run_id=row["source_run_id"],
            source_window_fingerprint=row["source_window_fingerprint"],
            requirement_plan_confirmation_id=(
                row["requirement_plan_confirmation_id"]
            ),
            requirement_plan_evidence_fingerprint=(
                row["requirement_plan_evidence_fingerprint"]
            ),
            candidate_manifest_fingerprint=row["candidate_manifest_fingerprint"],
            candidate_provenance=TypedEvidenceProvenance(
                provider=Provider(row["candidate_provider"]),
                provider_version=row["candidate_provider_version"],
                adapter_version=row["candidate_adapter_version"],
                decoder_key=row["candidate_decoder_key"],
                decoder_version=row["candidate_decoder_version"],
                source_schema_version=row["candidate_source_schema_version"],
                evidence_schema_version=int(row["candidate_evidence_schema_version"]),
                extraction_complete=bool(
                    row["candidate_provenance_extraction_complete"]
                ),
            ),
            candidate_extraction_complete=bool(
                row["candidate_extraction_complete"]
            ),
            candidate_enumeration_complete=bool(
                row["candidate_enumeration_complete"]
            ),
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
            requirements=requirements,
            candidates=candidates,
            links=links,
            created_at=created_at,
            schema_version=row["schema_version"],
            policy_version=row["policy_version"],
            review_rubric_version=row["review_rubric_version"],
            local_only=bool(row["local_only"]),
            content_persisted=bool(row["content_persisted"]),
        )
        if requirement_action_graph_fingerprint(proposal) != row["graph_fingerprint"]:
            raise DatabaseInvariantError(
                "requirement-action proposal graph fingerprint is invalid"
            )
        SqliteRequirementActionEvidenceRepository._manifest(proposal)
        decision_row = connection.execute(
            """SELECT * FROM requirement_action_evidence_decisions
               WHERE proposal_id=?""",
            (proposal_id,),
        ).fetchone()
        decision = None
        if decision_row is not None:
            decided_at = from_iso(decision_row["decided_at"])
            if decided_at is None:
                raise DatabaseInvariantError(
                    "requirement-action decision time is missing"
                )
            decision = RequirementActionDecisionRecord(
                decision_id=decision_row["decision_id"],
                proposal_id=decision_row["proposal_id"],
                session_id=decision_row["session_id"],
                decision=RequirementActionDecisionKind(decision_row["decision"]),
                idempotency_key_digest=decision_row["idempotency_key_digest"],
                command_fingerprint=decision_row["command_fingerprint"],
                reviewed_descriptor_set_fingerprint=(
                    decision_row["reviewed_descriptor_set_fingerprint"]
                ),
                decision_authority_fingerprint=(
                    decision_row["decision_authority_fingerprint"]
                ),
                decided_at=decided_at,
                confirmation_authority=decision_row["confirmation_authority"],
                schema_version=decision_row["schema_version"],
                local_only=bool(decision_row["local_only"]),
                content_persisted=bool(decision_row["content_persisted"]),
            )
            if (
                decision.proposal_id != proposal.proposal_id
                or decision.session_id != proposal.session_id
            ):
                raise DatabaseInvariantError(
                    "requirement-action decision authority is cross-bound"
                )
            expected_decision_authority = (
                requirement_action_decision_authority_fingerprint(
                    self._identifiers,
                    proposal=proposal,
                    decision_id=decision.decision_id,
                    decision=decision.decision,
                    idempotency_key_digest=decision.idempotency_key_digest,
                    command_fingerprint=decision.command_fingerprint,
                    reviewed_descriptor_set_fingerprint=(
                        decision.reviewed_descriptor_set_fingerprint
                    ),
                )
            )
            if not hmac.compare_digest(
                decision.decision_authority_fingerprint,
                expected_decision_authority,
            ):
                raise DatabaseInvariantError(
                    "requirement-action decision authority is invalid"
                )
        status = (
            RequirementActionProposalStatus.PROPOSED
            if decision is None
            else RequirementActionProposalStatus.CONFIRMED
            if decision.decision is RequirementActionDecisionKind.CONFIRM
            else RequirementActionProposalStatus.REJECTED
        )
        return RequirementActionProposalView(
            proposal=proposal,
            decision=decision,
            status=status,
        )


__all__ = ("SqliteRequirementActionEvidenceRepository",)
