"""SQLite adapter for content-free, user-confirmed metric lifecycle evidence."""

from __future__ import annotations

from collections.abc import Callable
import sqlite3

from ...application.analysis.metric_lifecycle_evidence import (
    FAMILY_OPPORTUNITY_KIND,
    ConfirmedMetricLifecycleOpportunity,
    ConfirmedMetricLifecycleOutcome,
    MetricLifecycleConflictError,
    MetricLifecycleDecisionKind,
    MetricLifecycleDecisionRecord,
    MetricLifecycleEvidenceRepository,
    MetricLifecycleEvidenceSnapshot,
    MetricLifecycleFamily,
    MetricLifecycleFamilyEvidence,
    MetricLifecycleLinkKind,
    MetricLifecycleOpportunityKind,
    MetricLifecycleOutcomeKind,
    MetricLifecycleProposalKind,
    MetricLifecycleProposalRecord,
    MetricLifecycleProposalView,
)
from ...database import DatabaseInvariantError
from ._common import ConnectionScope, from_iso, require_safe_id, to_iso


MAX_LISTED_LIFECYCLE_PROPOSALS = 1_000


class SqliteMetricLifecycleEvidenceRepository(MetricLifecycleEvidenceRepository):
    """Atomic proposal/decision store whose metric read is confirm-only."""

    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized

    def issue_proposal(
        self, proposal: MetricLifecycleProposalRecord
    ) -> tuple[MetricLifecycleProposalView, bool]:
        self._ensure_initialized()
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    """SELECT proposal_id,command_fingerprint
                       FROM metric_lifecycle_evidence_proposals
                       WHERE session_id=? AND idempotency_key_digest=?""",
                    (proposal.session_id, proposal.idempotency_key_digest),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["proposal_id"] != proposal.proposal_id
                        or existing["command_fingerprint"]
                        != proposal.command_fingerprint
                    ):
                        raise MetricLifecycleConflictError(
                            "proposal idempotency key conflicts"
                        )
                    view = self._get_view(connection, proposal.proposal_id)
                    if view is None:
                        raise DatabaseInvariantError(
                            "lifecycle proposal replay is incomplete"
                        )
                    connection.commit()
                    return view, False
                latest = connection.execute(
                    """SELECT run.run_id,run.input_fingerprint
                       FROM session_model_ensemble_runs run
                       JOIN session_model_ensemble_seals seal
                         ON seal.run_id=run.run_id
                       WHERE run.session_id=?
                       ORDER BY run.completed_at DESC,run.run_id DESC
                       LIMIT 1""",
                    (proposal.session_id,),
                ).fetchone()
                if (
                    latest is None
                    or latest["run_id"] != proposal.source_run_id
                    or latest["input_fingerprint"]
                    != proposal.source_window_fingerprint
                ):
                    raise MetricLifecycleConflictError(
                        "lifecycle proposal source authority changed"
                    )
                connection.execute(
                    """INSERT OR IGNORE INTO metric_lifecycle_evidence_windows(
                           session_id,source_window_fingerprint,anchor_run_id
                       ) VALUES(?,?,?)""",
                    (
                        proposal.session_id,
                        proposal.source_window_fingerprint,
                        proposal.source_run_id,
                    ),
                )
                window = connection.execute(
                    """SELECT anchor_run_id
                       FROM metric_lifecycle_evidence_windows
                       WHERE session_id=? AND source_window_fingerprint=?""",
                    (proposal.session_id, proposal.source_window_fingerprint),
                ).fetchone()
                if window is None:
                    raise DatabaseInvariantError(
                        "lifecycle evidence window could not be sealed"
                    )
                stored_proposal = proposal.model_copy(
                    update={"source_run_id": str(window["anchor_run_id"])}
                )
                connection.execute(
                    """INSERT INTO metric_lifecycle_evidence_proposals(
                           proposal_id,session_id,source_run_id,
                           source_window_fingerprint,proposal_revision,
                           proposal_kind,family,opportunity_kind,opportunity_id,
                           link_kind,outcome_kind,idempotency_key_digest,
                           command_fingerprint,created_at,schema_version,
                           policy_version,local_only,content_persisted
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,0)""",
                    (
                        stored_proposal.proposal_id,
                        stored_proposal.session_id,
                        stored_proposal.source_run_id,
                        stored_proposal.source_window_fingerprint,
                        stored_proposal.proposal_revision,
                        stored_proposal.proposal_kind.value,
                        stored_proposal.family.value,
                        stored_proposal.opportunity_kind.value,
                        stored_proposal.opportunity_id,
                        None if stored_proposal.link_kind is None else stored_proposal.link_kind.value,
                        (
                            None
                            if stored_proposal.outcome_kind is None
                            else stored_proposal.outcome_kind.value
                        ),
                        stored_proposal.idempotency_key_digest,
                        stored_proposal.command_fingerprint,
                        to_iso(stored_proposal.created_at),
                        stored_proposal.schema_version,
                        stored_proposal.policy_version,
                    ),
                )
                connection.executemany(
                    """INSERT INTO metric_lifecycle_evidence_enumeration_members(
                           proposal_id,opportunity_id,ordinal
                       ) VALUES(?,?,?)""",
                    (
                        (stored_proposal.proposal_id, opportunity_id, ordinal)
                        for ordinal, opportunity_id in enumerate(
                            stored_proposal.enumerated_opportunity_ids
                        )
                    ),
                )
                view = self._get_view(connection, stored_proposal.proposal_id)
                if view is None:
                    raise DatabaseInvariantError("lifecycle proposal insert is incomplete")
                connection.commit()
                return view, True
            except MetricLifecycleConflictError:
                connection.rollback()
                raise
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise MetricLifecycleConflictError(
                    "lifecycle proposal conflicts with confirmed evidence"
                ) from error
            except Exception:
                connection.rollback()
                raise

    def decide(
        self, decision: MetricLifecycleDecisionRecord
    ) -> tuple[MetricLifecycleProposalView, bool]:
        self._ensure_initialized()
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                proposal = connection.execute(
                    """SELECT proposal_revision,session_id
                       FROM metric_lifecycle_evidence_proposals
                       WHERE proposal_id=?""",
                    (decision.proposal_id,),
                ).fetchone()
                if proposal is None:
                    raise MetricLifecycleConflictError(
                        "lifecycle proposal does not exist"
                    )
                if (
                    proposal["session_id"] != decision.session_id
                    or int(proposal["proposal_revision"])
                    != decision.expected_proposal_revision
                ):
                    raise MetricLifecycleConflictError(
                        "lifecycle proposal authority changed"
                    )
                existing = connection.execute(
                    """SELECT decision_id,idempotency_key_digest,
                              command_fingerprint,decision
                       FROM metric_lifecycle_evidence_decisions
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
                        raise MetricLifecycleConflictError(
                            "lifecycle proposal already has another decision"
                        )
                    view = self._get_view(connection, decision.proposal_id)
                    if view is None:
                        raise DatabaseInvariantError(
                            "lifecycle decision replay is incomplete"
                        )
                    connection.commit()
                    return view, False
                key_conflict = connection.execute(
                    """SELECT proposal_id,command_fingerprint
                       FROM metric_lifecycle_evidence_decisions
                       WHERE session_id=? AND idempotency_key_digest=?""",
                    (decision.session_id, decision.idempotency_key_digest),
                ).fetchone()
                if key_conflict is not None:
                    raise MetricLifecycleConflictError(
                        "decision idempotency key conflicts"
                    )
                connection.execute(
                    """INSERT INTO metric_lifecycle_evidence_decisions(
                           decision_id,proposal_id,session_id,
                           expected_proposal_revision,decision,
                           idempotency_key_digest,command_fingerprint,
                           decided_at,confirmation_authority,schema_version,
                           local_only,content_persisted
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,1,0)""",
                    (
                        decision.decision_id,
                        decision.proposal_id,
                        decision.session_id,
                        decision.expected_proposal_revision,
                        decision.decision.value,
                        decision.idempotency_key_digest,
                        decision.command_fingerprint,
                        to_iso(decision.decided_at),
                        decision.confirmation_authority,
                        decision.schema_version,
                    ),
                )
                view = self._get_view(connection, decision.proposal_id)
                if view is None:
                    raise DatabaseInvariantError("lifecycle decision insert is incomplete")
                connection.commit()
                return view, True
            except MetricLifecycleConflictError:
                connection.rollback()
                raise
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise MetricLifecycleConflictError(
                    "lifecycle decision conflicts with confirmed evidence"
                ) from error
            except Exception:
                connection.rollback()
                raise

    def get_proposal(
        self, proposal_id: str
    ) -> MetricLifecycleProposalView | None:
        self._ensure_initialized()
        require_safe_id(proposal_id)
        with self._connection_scope(readonly=True) as connection:
            return self._get_view(connection, proposal_id)

    def list_proposals(
        self, session_id: str
    ) -> tuple[MetricLifecycleProposalView, ...]:
        self._ensure_initialized()
        require_safe_id(session_id)
        with self._connection_scope(readonly=True) as connection:
            count_row = connection.execute(
                """SELECT COUNT(*) AS total
                   FROM metric_lifecycle_evidence_proposals
                   WHERE session_id=?""",
                (session_id,),
            ).fetchone()
            if (
                count_row is None
                or int(count_row["total"]) > MAX_LISTED_LIFECYCLE_PROPOSALS
            ):
                raise DatabaseInvariantError(
                    "lifecycle proposal list exceeds its proven complete boundary"
                )
            rows = connection.execute(
                """SELECT proposal_id
                   FROM metric_lifecycle_evidence_proposals
                   WHERE session_id=?
                   ORDER BY created_at DESC,proposal_id DESC
                   LIMIT ?""",
                (session_id, MAX_LISTED_LIFECYCLE_PROPOSALS),
            ).fetchall()
            views = tuple(
                self._get_view(connection, row["proposal_id"]) for row in rows
            )
            if any(view is None for view in views):
                raise DatabaseInvariantError("lifecycle proposal graph is incomplete")
            return tuple(view for view in reversed(views) if view is not None)

    def list_proposals_page(
        self, session_id: str, *, limit: int, offset: int
    ) -> tuple[tuple[MetricLifecycleProposalView, ...], int]:
        self._ensure_initialized()
        require_safe_id(session_id)
        if not 1 <= limit <= 200 or not 0 <= offset <= 1_000_000:
            raise ValueError("lifecycle proposal page is outside its bound")
        with self._connection_scope(readonly=True) as connection:
            count_row = connection.execute(
                """SELECT COUNT(*) AS total
                   FROM metric_lifecycle_evidence_proposals
                   WHERE session_id=?""",
                (session_id,),
            ).fetchone()
            if count_row is None:
                raise DatabaseInvariantError("lifecycle proposal count is missing")
            total = int(count_row["total"])
            rows = connection.execute(
                """SELECT proposal_id
                   FROM metric_lifecycle_evidence_proposals
                   WHERE session_id=?
                   ORDER BY created_at ASC,proposal_id ASC
                   LIMIT ? OFFSET ?""",
                (session_id, limit, offset),
            ).fetchall()
            views = tuple(
                self._get_view(connection, row["proposal_id"]) for row in rows
            )
            if any(view is None for view in views):
                raise DatabaseInvariantError("lifecycle proposal page is incomplete")
            return tuple(view for view in views if view is not None), total

    def snapshot(
        self, session_id: str, source_window_fingerprint: str
    ) -> MetricLifecycleEvidenceSnapshot:
        self._ensure_initialized()
        require_safe_id(session_id)
        require_safe_id(source_window_fingerprint)
        with self._connection_scope(readonly=True) as connection:
            opportunities = connection.execute(
                """SELECT proposal.opportunity_id,proposal.family,
                          proposal.opportunity_kind,decision.decision_id,
                          decision.decided_at
                   FROM metric_lifecycle_evidence_proposals proposal
                   JOIN metric_lifecycle_evidence_decisions decision
                     ON decision.proposal_id=proposal.proposal_id
                    AND decision.decision='confirm'
                   WHERE proposal.session_id=?
                     AND proposal.source_window_fingerprint=?
                     AND proposal.proposal_kind='opportunity'
                   ORDER BY proposal.family,proposal.opportunity_id""",
                (session_id, source_window_fingerprint),
            ).fetchall()
            outcomes = connection.execute(
                """SELECT proposal.opportunity_id,proposal.family,
                          proposal.link_kind,proposal.outcome_kind,
                          decision.decision_id,decision.decided_at
                   FROM metric_lifecycle_evidence_proposals proposal
                   JOIN metric_lifecycle_evidence_decisions decision
                     ON decision.proposal_id=proposal.proposal_id
                    AND decision.decision='confirm'
                   WHERE proposal.session_id=?
                     AND proposal.source_window_fingerprint=?
                     AND proposal.proposal_kind='outcome'
                   ORDER BY proposal.family,proposal.opportunity_id""",
                (session_id, source_window_fingerprint),
            ).fetchall()
            enumerations = connection.execute(
                """SELECT proposal.proposal_id,proposal.family,
                          decision.decision_id
                   FROM metric_lifecycle_evidence_proposals proposal
                   JOIN metric_lifecycle_evidence_decisions decision
                     ON decision.proposal_id=proposal.proposal_id
                    AND decision.decision='confirm'
                   WHERE proposal.session_id=?
                     AND proposal.source_window_fingerprint=?
                     AND proposal.proposal_kind='enumeration'
                   ORDER BY proposal.family""",
                (session_id, source_window_fingerprint),
            ).fetchall()
            outcome_by_opportunity: dict[str, ConfirmedMetricLifecycleOutcome] = {}
            for row in outcomes:
                opportunity_id = str(row["opportunity_id"])
                if opportunity_id in outcome_by_opportunity:
                    raise DatabaseInvariantError(
                        "an opportunity has multiple confirmed outcomes"
                    )
                decided_at = from_iso(row["decided_at"])
                if decided_at is None:
                    raise DatabaseInvariantError("lifecycle outcome time is missing")
                outcome_by_opportunity[opportunity_id] = (
                    ConfirmedMetricLifecycleOutcome(
                        decision_id=row["decision_id"],
                        link_kind=MetricLifecycleLinkKind(row["link_kind"]),
                        outcome_kind=MetricLifecycleOutcomeKind(row["outcome_kind"]),
                        decided_at=decided_at,
                    )
                )
            enumeration_by_family: dict[
                MetricLifecycleFamily, tuple[str, tuple[str, ...]]
            ] = {}
            for row in enumerations:
                family = MetricLifecycleFamily(row["family"])
                if family in enumeration_by_family:
                    raise DatabaseInvariantError(
                        "a lifecycle family has multiple enumerations"
                    )
                members = tuple(
                    member["opportunity_id"]
                    for member in connection.execute(
                        """SELECT opportunity_id
                           FROM metric_lifecycle_evidence_enumeration_members
                           WHERE proposal_id=? ORDER BY ordinal""",
                        (row["proposal_id"],),
                    ).fetchall()
                )
                enumeration_by_family[family] = (row["decision_id"], members)
            opportunity_rows: dict[
                MetricLifecycleFamily, list[ConfirmedMetricLifecycleOpportunity]
            ] = {family: [] for family in MetricLifecycleFamily}
            for row in opportunities:
                family = MetricLifecycleFamily(row["family"])
                confirmed_at = from_iso(row["decided_at"])
                if confirmed_at is None:
                    raise DatabaseInvariantError(
                        "lifecycle opportunity confirmation time is missing"
                    )
                opportunity_id = str(row["opportunity_id"])
                opportunity_rows[family].append(
                    ConfirmedMetricLifecycleOpportunity(
                        opportunity_id=opportunity_id,
                        opportunity_kind=MetricLifecycleOpportunityKind(
                            row["opportunity_kind"]
                        ),
                        confirmation_id=row["decision_id"],
                        confirmed_at=confirmed_at,
                        outcome=outcome_by_opportunity.get(opportunity_id),
                    )
                )
            families = []
            for family in MetricLifecycleFamily:
                enumeration = enumeration_by_family.get(family)
                families.append(
                    MetricLifecycleFamilyEvidence(
                        family=family,
                        opportunity_kind=FAMILY_OPPORTUNITY_KIND[family],
                        enumeration_confirmed=enumeration is not None,
                        enumeration_confirmation_id=(
                            None if enumeration is None else enumeration[0]
                        ),
                        enumerated_opportunity_ids=(
                            () if enumeration is None else enumeration[1]
                        ),
                        opportunities=tuple(opportunity_rows[family]),
                    )
                )
            return MetricLifecycleEvidenceSnapshot(
                session_id=session_id,
                source_window_fingerprint=source_window_fingerprint,
                families=tuple(families),
            )

    @staticmethod
    def _get_view(
        connection: sqlite3.Connection, proposal_id: str
    ) -> MetricLifecycleProposalView | None:
        row = connection.execute(
            """SELECT * FROM metric_lifecycle_evidence_proposals
               WHERE proposal_id=?""",
            (proposal_id,),
        ).fetchone()
        if row is None:
            return None
        members = tuple(
            item["opportunity_id"]
            for item in connection.execute(
                """SELECT opportunity_id
                   FROM metric_lifecycle_evidence_enumeration_members
                   WHERE proposal_id=? ORDER BY ordinal""",
                (proposal_id,),
            ).fetchall()
        )
        created_at = from_iso(row["created_at"])
        if created_at is None:
            raise DatabaseInvariantError("lifecycle proposal time is missing")
        proposal = MetricLifecycleProposalRecord(
            proposal_id=row["proposal_id"],
            session_id=row["session_id"],
            source_run_id=row["source_run_id"],
            source_window_fingerprint=row["source_window_fingerprint"],
            proposal_revision=int(row["proposal_revision"]),
            proposal_kind=MetricLifecycleProposalKind(row["proposal_kind"]),
            family=MetricLifecycleFamily(row["family"]),
            opportunity_kind=MetricLifecycleOpportunityKind(
                row["opportunity_kind"]
            ),
            opportunity_id=row["opportunity_id"],
            link_kind=(
                None
                if row["link_kind"] is None
                else MetricLifecycleLinkKind(row["link_kind"])
            ),
            outcome_kind=(
                None
                if row["outcome_kind"] is None
                else MetricLifecycleOutcomeKind(row["outcome_kind"])
            ),
            enumerated_opportunity_ids=members,
            idempotency_key_digest=row["idempotency_key_digest"],
            command_fingerprint=row["command_fingerprint"],
            created_at=created_at,
            schema_version=row["schema_version"],
            policy_version=row["policy_version"],
            local_only=bool(row["local_only"]),
            content_persisted=bool(row["content_persisted"]),
        )
        decision_row = connection.execute(
            """SELECT * FROM metric_lifecycle_evidence_decisions
               WHERE proposal_id=?""",
            (proposal_id,),
        ).fetchone()
        decision = None
        if decision_row is not None:
            decided_at = from_iso(decision_row["decided_at"])
            if decided_at is None:
                raise DatabaseInvariantError("lifecycle decision time is missing")
            decision = MetricLifecycleDecisionRecord(
                decision_id=decision_row["decision_id"],
                proposal_id=decision_row["proposal_id"],
                session_id=decision_row["session_id"],
                expected_proposal_revision=int(
                    decision_row["expected_proposal_revision"]
                ),
                decision=MetricLifecycleDecisionKind(decision_row["decision"]),
                idempotency_key_digest=decision_row["idempotency_key_digest"],
                command_fingerprint=decision_row["command_fingerprint"],
                decided_at=decided_at,
                confirmation_authority=decision_row["confirmation_authority"],
                schema_version=decision_row["schema_version"],
                local_only=bool(decision_row["local_only"]),
                content_persisted=bool(decision_row["content_persisted"]),
            )
        return MetricLifecycleProposalView(proposal=proposal, decision=decision)


__all__ = [
    "MAX_LISTED_LIFECYCLE_PROPOSALS",
    "SqliteMetricLifecycleEvidenceRepository",
]
