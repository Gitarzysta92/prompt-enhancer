from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
import hashlib
import json
import re
import sqlite3

import pytest
from pydantic import SecretStr

from prompt_enhancer.application.analysis.metric_contract_v2 import (
    METRIC_CONTRACT_REGISTRY_VERSION_V2,
    metric_contract_v2,
    metric_contract_v2_set_fingerprint,
)
from prompt_enhancer.application.analysis.metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_6,
)
from prompt_enhancer.application.analysis.metric_projection_v6 import (
    project_metric_states_v6,
)
from prompt_enhancer.application.analysis.metric_publication_v2 import (
    publish_metric_states_v2,
)
from prompt_enhancer.application.analysis.requirement_plan_evidence import (
    REQUIREMENT_PLAN_DECISION_CONFIRMATION,
    REQUIREMENT_PLAN_EVIDENCE_FILE_VERSION,
    REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
    REQUIREMENT_PLAN_METRIC_KEY,
    REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
    InMemoryRequirementPlanReviewContextStore,
    RequirementDisposition,
    RequirementPlanConflictError,
    RequirementPlanDecisionCommand,
    RequirementPlanDecisionKind,
    RequirementPlanDecisionRecord,
    RequirementPlanEvidenceService,
    RequirementPlanProposalStatus,
    SealedRunRequirementPlanSource,
)
from prompt_enhancer.application.analysis.semantic_units import SemanticUnitReconciler
from prompt_enhancer.application.analysis.session_model_ensemble import (
    REQUIREMENT_PLAN_UNAVAILABLE_FINGERPRINT,
    REQUIREMENT_PLAN_UNAVAILABLE_POLICY_VERSION,
    REQUIREMENT_PLAN_UNAVAILABLE_SCHEMA_VERSION,
    RequirementPlanEvidenceSource,
    SessionRequirementPlanEvidenceBinding,
)
from prompt_enhancer.application.analysis.text_contracts import TextMessageKind
from prompt_enhancer.database import Database, DatabaseInvariantError
from prompt_enhancer.infrastructure.identifiers import LocalArtifactIdFactory
from prompt_enhancer.privacy import Pseudonymizer

from test_model_ensemble_persistence import _database_and_session
from test_model_ensemble_r5_profile_persistence import NOW, _preset_binding, _record
from test_probabilistic_metric_persistence import IDS, _context


ARTIFACT_IDS = LocalArtifactIdFactory(Pseudonymizer(bytes(range(32))))


def _restart_database(database: Database) -> Database:
    restarted = Database(database.path)
    restarted.configure_local_artifact_id_factory(ARTIFACT_IDS)
    return restarted


def _downgrade_synthetic_copy_to_v55(path) -> None:  # type: ignore[no-untyped-def]
    """Remove only post-M55 objects to exercise the explicit trusted upgrade."""

    from prompt_enhancer.infrastructure.sqlite import migrations

    created = tuple(
        (kind.casefold(), name)
        for script in (
            migrations.MIGRATION_56,
            migrations.MIGRATION_57,
            migrations.MIGRATION_58,
            migrations.MIGRATION_59,
        )
        for kind, name in re.findall(
            r"CREATE\s+(?:(?:UNIQUE)\s+)?(TABLE|INDEX|TRIGGER)\s+([a-z0-9_]+)",
            script,
            flags=re.IGNORECASE,
        )
    )
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        for kind in ("trigger", "index", "table"):
            for object_kind, name in reversed(created):
                if object_kind == kind:
                    connection.execute(
                        f"DROP {kind.upper()} IF EXISTS {name}"  # noqa: S608
                    )
        # The current synthetic seed has M61's added columns. Removing only
        # migration ledger rows would leave a falsely labelled v55 schema and
        # correctly fail when M61 tries to add those same columns again.
        for table, columns in (
            ("calibration_ratings", ("case_fingerprint", "case_version", "window_fingerprint")),
            ("model_judgments", ("case_fingerprint", "case_version")),
        ):
            for column in columns:
                connection.execute(f"ALTER TABLE {table} DROP COLUMN {column}")  # noqa: S608
            assert not set(columns) & {
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")  # noqa: S608
            }
        connection.execute("DELETE FROM schema_migrations WHERE version>=56")
        connection.execute("PRAGMA user_version=55")
        connection.commit()


def _payload(session_id: str, run, *, predecessor: str | None = None) -> bytes:  # type: ignore[no-untyped-def]
    document = {
        "schema_version": REQUIREMENT_PLAN_EVIDENCE_FILE_VERSION,
        "session_id": session_id,
        "expected_source_run_id": run.run_id,
        "source_window_fingerprint": run.input_fingerprint,
        "expected_predecessor_confirmation_id": predecessor,
        "registry_version": METRIC_CONTRACT_REGISTRY_VERSION_V2,
        "contract_set_fingerprint": metric_contract_v2_set_fingerprint(),
        "metric_key": REQUIREMENT_PLAN_METRIC_KEY,
        "metric_contract_fingerprint": metric_contract_v2(
            REQUIREMENT_PLAN_METRIC_KEY
        ).fingerprint,
        "source_projection_version": METRIC_PROJECTION_V2_VERSION_6,
        "clause_algorithm": "message-clause-coordinates-en-pl-v1",
        "review_rubric_version": REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
        "nonce": "9" * 64,
        "expires_at": (NOW + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "producer": {
            "kind": "local_coding_agent",
            "producer_id": "example-agent",
            "producer_version": "1",
            "model_id": "example-local-model",
            "authority": "untrusted_provenance_claim",
        },
        "contains_prose": False,
        "contains_scores": False,
        "contains_authoritative_model_judgment_claims": False,
        "contains_untrusted_structured_proposals": True,
        "contains_objective_receipt_claims": False,
        "complete_user_clause_classification": True,
        "requirements": [
            {
                "coordinate": {"message_sequence": 0, "clause_index": 0},
                "disposition": "linked",
                "plan_indexes": [0],
            },
            {
                "coordinate": {"message_sequence": 0, "clause_index": 1},
                "disposition": "not_linked",
                "plan_indexes": [],
            },
            {
                "coordinate": {"message_sequence": 0, "clause_index": 2},
                "disposition": "pending",
                "plan_indexes": [],
            },
        ],
        "excluded_user_clauses": [
            {
                "coordinate": {"message_sequence": 0, "clause_index": 3},
                "reason": "not_requirement",
                "basis_coordinate": None,
            }
        ],
        "plan_items": [{"message_sequence": 1, "clause_index": 0}],
    }
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _payload_with_withdrawal_basis(
    session_id: str,
    run,
    *,
    predecessor: str | None = None,
) -> bytes:  # type: ignore[no-untyped-def]
    """Return a complete graph whose excluded clause cites a later user clause."""

    document = json.loads(_payload(session_id, run, predecessor=predecessor))
    document["requirements"] = [
        item
        for item in document["requirements"]
        if item["coordinate"]["clause_index"] != 2
    ]
    document["requirements"].append(
        {
            "coordinate": {"message_sequence": 0, "clause_index": 3},
            "disposition": "not_linked",
            "plan_indexes": [],
        }
    )
    document["excluded_user_clauses"] = [
        {
            "coordinate": {"message_sequence": 0, "clause_index": 2},
            "reason": "withdrawn",
            "basis_coordinate": {"message_sequence": 0, "clause_index": 3},
        }
    ]
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _setup(tmp_path):  # type: ignore[no-untyped-def]
    database, session_id = _database_and_session(tmp_path)
    database.configure_local_artifact_id_factory(ARTIFACT_IDS)
    legacy_shape = _record(
        session_id,
        run_character="a",
        request_character="b",
        binding=_preset_binding(session_id),
    )
    base_context = _context(session_id)
    context = base_context.model_copy(
        update={
            "available_message_kinds": frozenset(
                {TextMessageKind.REQUEST, TextMessageKind.PLAN}
            ),
            "messages": (
                base_context.messages[0].model_copy(
                    update={
                        "text": SecretStr(
                            "First synthetic requirement. Second synthetic requirement. Third synthetic requirement. Omitted synthetic clause."
                        )
                    }
                ),
                base_context.messages[1].model_copy(
                    update={
                        "kind": TextMessageKind.PLAN,
                        "text": SecretStr(
                            "Implement the first synthetic requirement. "
                            "Verify the synthetic result."
                        ),
                    }
                ),
            ),
        }
    )
    publication = publish_metric_states_v2(
        project_metric_states_v6(
            context=context,
            reconciliation=SemanticUnitReconciler(IDS).reconcile(
                context
            ).reconciliation,
            id_factory=IDS,
        )
    )
    run = legacy_shape.model_copy(
        update={
            "requirement_plan_evidence_binding": (
                SessionRequirementPlanEvidenceBinding(
                    evidence_source=RequirementPlanEvidenceSource.UNAVAILABLE,
                    session_id=session_id,
                    source_window_fingerprint=legacy_shape.input_fingerprint,
                    evidence_fingerprint=REQUIREMENT_PLAN_UNAVAILABLE_FINGERPRINT,
                    evidence_schema_version=REQUIREMENT_PLAN_UNAVAILABLE_SCHEMA_VERSION,
                    evidence_policy_version=REQUIREMENT_PLAN_UNAVAILABLE_POLICY_VERSION,
                    bound_at=NOW,
                )
            ),
            "receipt": legacy_shape.receipt.model_copy(
                update={"metric_publication_v2": publication}
            ),
        }
    )
    models = database.model_ensemble_repository()
    models.save_completed(run)
    repository = database.requirement_plan_evidence_repository()
    review_contexts = InMemoryRequirementPlanReviewContextStore(
        clock=lambda: NOW + timedelta(minutes=1),
        monotonic_clock=lambda: 100.0,
    )
    review_contexts.publish(run.run_id, context)
    service = RequirementPlanEvidenceService(
        repository,
        SealedRunRequirementPlanSource(models, review_contexts),
        ARTIFACT_IDS,
        review_contexts=review_contexts,
        clock=lambda: NOW + timedelta(minutes=1),
    )
    return database, session_id, run, repository, service


def _import(
    service,
    session_id: str,
    run,
    *,
    predecessor=None,
    suffix="0001",
    payload: bytes | None = None,
):  # type: ignore[no-untyped-def]
    payload = payload or _payload(session_id, run, predecessor=predecessor)
    preview = service.preview(session_id=session_id, payload=payload, now=NOW)
    return service.import_file(
        session_id=session_id,
        payload=payload,
        expected_payload_sha256=preview.payload_sha256,
        confirmation=REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
        idempotency_key=f"synthetic-requirement-plan-import-{suffix}",
        now=NOW,
    )[0]


def _confirm(service, session_id: str, run, proposal, *, suffix="0001"):  # type: ignore[no-untyped-def]
    review = service.review_proposal(
        session_id=session_id,
        proposal_id=proposal.proposal.proposal_id,
        expected_source_run_id=run.run_id,
    )
    return service.decide(
        session_id=session_id,
        proposal_id=proposal.proposal.proposal_id,
        command=RequirementPlanDecisionCommand(
            expected_source_run_id=run.run_id,
            decision=RequirementPlanDecisionKind.CONFIRM,
            confirmation=REQUIREMENT_PLAN_DECISION_CONFIRMATION,
            review_receipt_id=review.review_receipt_id,
            manifest_fingerprint=review.manifest_fingerprint,
            reviewed_graph_fingerprint=review.reviewed_graph_fingerprint,
            reviewed_candidate_set_fingerprint=(
                review.reviewed_candidate_set_fingerprint
            ),
            complete_review_acknowledged=True,
        ),
        idempotency_key=f"synthetic-requirement-plan-decision-{suffix}",
    )[0]


def _decision_record(
    session_id: str,
    proposal,
    *,
    decision: RequirementPlanDecisionKind,
    suffix: str,
) -> RequirementPlanDecisionRecord:  # type: ignore[no-untyped-def]
    """Build the same content-free decision identity as the service boundary."""

    identifiers = LocalArtifactIdFactory(Pseudonymizer(bytes(range(32))))
    idempotency_key = f"synthetic-requirement-plan-decision-{suffix}"
    idempotency_digest = identifiers.fingerprint(
        "requirement-plan-decision-idempotency-v1",
        (session_id, idempotency_key),
    )
    command_fingerprint = identifiers.fingerprint(
        "requirement-plan-decision-command-v1",
        (
            proposal.proposal.proposal_id,
            proposal.proposal.source_run_id,
            decision.value,
            REQUIREMENT_PLAN_DECISION_CONFIRMATION,
        ),
    )
    return RequirementPlanDecisionRecord(
        decision_id=identifiers.fingerprint(
            "requirement-plan-decision-v1",
            (proposal.proposal.proposal_id, idempotency_digest),
        ),
        proposal_id=proposal.proposal.proposal_id,
        session_id=session_id,
        decision=decision,
        idempotency_key_digest=idempotency_digest,
        command_fingerprint=command_fingerprint,
        decided_at=NOW + timedelta(minutes=1),
    )


def _insert_unsealed_proposal(
    connection: sqlite3.Connection,
    source,
    *,
    proposal_id: str,
    requirement_count: int,
    excluded_user_clause_count: int,
) -> tuple[str, str, str]:  # type: ignore[no-untyped-def]
    """Insert one synthetic open graph for direct M55 trigger attacks."""

    record = source.proposal
    payload_sha256 = hashlib.sha256(
        f"synthetic-payload:{proposal_id}".encode("ascii")
    ).hexdigest()
    idempotency_key_digest = hashlib.sha256(
        f"synthetic-idempotency:{proposal_id}".encode("ascii")
    ).hexdigest()
    command_fingerprint = hashlib.sha256(
        f"synthetic-command:{proposal_id}".encode("ascii")
    ).hexdigest()
    graph_fingerprint = hashlib.sha256(
        f"synthetic-graph:{proposal_id}".encode("ascii")
    ).hexdigest()
    created_at = record.created_at.isoformat(timespec="microseconds")
    connection.execute(
        """INSERT INTO requirement_plan_evidence_proposals(
               proposal_id,session_id,source_run_id,source_window_fingerprint,
               expected_predecessor_confirmation_id,payload_sha256,
               producer_kind,producer_claim_fingerprint,producer_authority,
               producer_raw_claim_persisted,review_rubric_version,
               complete_user_clause_classification,
               requirement_count,excluded_user_clause_count,
               plan_item_count,link_count,graph_fingerprint,idempotency_key_digest,
               command_fingerprint,created_at,schema_version,policy_version,
               local_only,content_persisted
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,?,?,?,?,?,?,1,0)""",
        (
            proposal_id,
            record.session_id,
            record.source_run_id,
            record.source_window_fingerprint,
            None,
            payload_sha256,
            record.producer_receipt.kind,
            record.producer_receipt.claim_fingerprint,
            record.producer_receipt.authority,
            int(record.producer_receipt.raw_claim_persisted),
            record.review_rubric_version,
            1,
            requirement_count,
            excluded_user_clause_count,
            graph_fingerprint,
            idempotency_key_digest,
            command_fingerprint,
            created_at,
            record.schema_version,
            record.policy_version,
        ),
    )
    return payload_sha256, graph_fingerprint, created_at


def test_sqlite_roundtrip_is_inert_until_confirmed_and_restart_safe(tmp_path) -> None:
    database, session_id, run, repository, service = _setup(tmp_path)
    proposal = _import(service, session_id, run)
    assert proposal.status is RequirementPlanProposalStatus.PROPOSED
    assert len(proposal.proposal.excluded_user_clauses) == 1
    assert proposal.proposal.producer_receipt.model_dump() == {
        "kind": "local_coding_agent",
        "claim_fingerprint": ARTIFACT_IDS.fingerprint(
            "requirement-plan-producer-claim-v1",
            (
                "local_coding_agent",
                "example-agent",
                "1",
                "example-local-model",
                "untrusted_provenance_claim",
            ),
        ),
        "authority": "untrusted_provenance_claim_commitment",
        "raw_claim_persisted": False,
    }
    assert proposal.proposal.review_rubric_version == (
        REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION
    )
    assert proposal.proposal.excluded_user_clauses[0].model_dump() == {
        "coordinate": {"message_sequence": 0, "clause_index": 3},
        "reason": "not_requirement",
        "basis_coordinate": None,
    }
    assert repository.snapshot(session_id, run.input_fingerprint).confirmation_id is None

    confirmed = _confirm(service, session_id, run, proposal)
    assert confirmed.status is RequirementPlanProposalStatus.CONFIRMED
    snapshot = repository.snapshot(session_id, run.input_fingerprint)
    assert snapshot.complete_user_clause_classification is True
    assert snapshot.review_rubric_version == REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION
    assert tuple(item.model_dump() for item in snapshot.excluded_user_clauses) == (
        {
            "coordinate": {"message_sequence": 0, "clause_index": 3},
            "reason": "not_requirement",
            "basis_coordinate": None,
        },
    )
    assert {item.disposition for item in snapshot.requirements} == {
        RequirementDisposition.LINKED,
        RequirementDisposition.NOT_LINKED,
        RequirementDisposition.PENDING,
    }
    assert all(len(value) == 64 for value in (
        snapshot.confirmation_id,
        snapshot.proposal_id,
        *(item.requirement_id for item in snapshot.requirements),
        *(item.plan_id for item in snapshot.plan_items),
    ) if value is not None)

    restarted = _restart_database(database)
    loaded = restarted.requirement_plan_evidence_repository().snapshot(
        session_id, run.input_fingerprint
    )
    assert loaded == snapshot
    rehydrated = restarted.requirement_plan_evidence_repository().get_proposal(
        proposal.proposal.proposal_id
    )
    assert rehydrated == confirmed
    assert rehydrated.decision is not None
    assert rehydrated.decision.confirmation_authority == (
        "owned_native_user_presence"
    )
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT confirmation_authority FROM requirement_plan_evidence_decisions"
        ).fetchone()[0] == "owned_native_user_presence"
        authority = connection.execute(
            """SELECT authority_source,authority_fingerprint,authority_version,
                      local_only,content_persisted
               FROM requirement_plan_evidence_decision_authority_m56"""
        ).fetchone()
        assert authority is not None
        assert authority[0] == "keyed_application_issuance"
        assert len(authority[1]) == 64
        assert authority[2:] == (
            "requirement-plan-decision-authority-v1",
            1,
            0,
        )


def test_populated_m55_decision_receives_one_explicit_keyed_upgrade(tmp_path) -> None:
    database, session_id, run, _repository, service = _setup(tmp_path)
    confirmed = _confirm(
        service,
        session_id,
        run,
        _import(service, session_id, run, suffix="trusted-upgrade"),
        suffix="trusted-upgrade",
    )
    assert confirmed.decision is not None
    _downgrade_synthetic_copy_to_v55(database.path)

    upgraded = Database(database.path)
    upgraded.configure_local_artifact_id_factory(ARTIFACT_IDS)
    upgraded.initialize()
    repository = upgraded.requirement_plan_evidence_repository()
    assert repository.get_proposal(confirmed.proposal.proposal_id) == confirmed
    with sqlite3.connect(database.path) as connection:
        authority = connection.execute(
            """SELECT authority_source,authority_fingerprint
               FROM requirement_plan_evidence_decision_authority_m56
               WHERE decision_id=?""",
            (confirmed.decision.decision_id,),
        ).fetchone()
        assert authority is not None
        assert authority[0] == "trusted_m55_upgrade"
        assert len(authority[1]) == 64

    restarted = _restart_database(upgraded)
    assert restarted.requirement_plan_evidence_repository().get_proposal(
        confirmed.proposal.proposal_id
    ) == confirmed


@pytest.mark.parametrize("first_kind", ("requirement", "excluded"))
def test_clause_classification_overlap_is_rejected_in_both_insert_orders(
    tmp_path,
    first_kind: str,
) -> None:
    database, session_id, run, _repository, service = _setup(tmp_path)
    source = _import(service, session_id, run, suffix=f"overlap-{first_kind}")
    proposal_id = ("1" if first_kind == "requirement" else "2") * 64
    with database._connection() as connection:
        _insert_unsealed_proposal(
            connection,
            source,
            proposal_id=proposal_id,
            requirement_count=1,
            excluded_user_clause_count=1,
        )
        requirement_sql = (
            "INSERT INTO requirement_plan_evidence_requirements("
            "proposal_id,ordinal,message_sequence,clause_index,disposition) "
            "VALUES(?,0,0,0,'pending')"
        )
        excluded_sql = (
            "INSERT INTO requirement_plan_evidence_excluded_user_clauses("
            "proposal_id,ordinal,message_sequence,clause_index,exclusion_reason,"
            "basis_message_sequence,basis_clause_index) "
            "VALUES(?,0,0,0,'not_requirement',NULL,NULL)"
        )
        first_sql, second_sql = (
            (requirement_sql, excluded_sql)
            if first_kind == "requirement"
            else (excluded_sql, requirement_sql)
        )
        connection.execute(first_sql, (proposal_id,))
        with pytest.raises(sqlite3.IntegrityError, match="outside proposal"):
            connection.execute(second_sql, (proposal_id,))
        connection.rollback()


def test_proposal_seal_rejects_an_omitted_excluded_user_clause(tmp_path) -> None:
    database, session_id, run, _repository, service = _setup(tmp_path)
    source = _import(service, session_id, run, suffix="omitted-child")
    proposal_id = "3" * 64
    with database._connection() as connection:
        payload_sha256, graph_fingerprint, created_at = _insert_unsealed_proposal(
            connection,
            source,
            proposal_id=proposal_id,
            requirement_count=1,
            excluded_user_clause_count=1,
        )
        connection.execute(
            """INSERT INTO requirement_plan_evidence_requirements(
                   proposal_id,ordinal,message_sequence,clause_index,disposition
               ) VALUES(?,0,0,0,'pending')""",
            (proposal_id,),
        )
        with pytest.raises(sqlite3.IntegrityError, match="proposal is incomplete"):
            connection.execute(
                """INSERT INTO requirement_plan_evidence_proposal_seals(
                       proposal_id,requirement_count,
                       excluded_user_clause_count,plan_item_count,link_count,
                       payload_sha256,producer_kind,producer_claim_fingerprint,
                       producer_authority,producer_raw_claim_persisted,
                       review_rubric_version,
                       complete_user_clause_classification,graph_fingerprint,
                       sealed_at
                   ) VALUES(?,1,1,0,0,?,?,?,?,?,?,?,?,?)""",
                (
                    proposal_id,
                    payload_sha256,
                    source.proposal.producer_receipt.kind,
                    source.proposal.producer_receipt.claim_fingerprint,
                    source.proposal.producer_receipt.authority,
                    int(source.proposal.producer_receipt.raw_claim_persisted),
                    source.proposal.review_rubric_version,
                    1,
                    graph_fingerprint,
                    created_at,
                ),
            )
        connection.rollback()


def test_combined_reviewed_clause_count_is_bounded_at_sqlite_boundary(
    tmp_path,
) -> None:
    database, session_id, run, _repository, service = _setup(tmp_path)
    source = _import(service, session_id, run, suffix="combined-bound")
    with database._connection() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            _insert_unsealed_proposal(
                connection,
                source,
                proposal_id="4" * 64,
                requirement_count=1000,
                excluded_user_clause_count=1,
            )
        connection.rollback()


@pytest.mark.parametrize(
    ("reason", "basis_clause_index"),
    (
        ("superseded", 0),
        ("withdrawn", 0),
        ("duplicate", 2),
    ),
)
def test_seal_rejects_invalid_exclusion_basis_relationships(
    tmp_path,
    reason: str,
    basis_clause_index: int,
) -> None:
    database, session_id, run, _repository, service = _setup(tmp_path)
    source = _import(service, session_id, run, suffix=f"basis-{reason}")
    proposal_id = {
        "superseded": "5",
        "withdrawn": "6",
        "duplicate": "7",
    }[reason] * 64
    with database._connection() as connection:
        payload_sha256, graph_fingerprint, created_at = _insert_unsealed_proposal(
            connection,
            source,
            proposal_id=proposal_id,
            requirement_count=1,
            excluded_user_clause_count=1,
        )
        connection.execute(
            """INSERT INTO requirement_plan_evidence_requirements(
                   proposal_id,ordinal,message_sequence,clause_index,disposition
               ) VALUES(?,0,0,0,'pending')""",
            (proposal_id,),
        )
        connection.execute(
            """INSERT INTO requirement_plan_evidence_excluded_user_clauses(
                   proposal_id,ordinal,message_sequence,clause_index,
                   exclusion_reason,basis_message_sequence,basis_clause_index
               ) VALUES(?,0,0,1,?,0,?)""",
            (proposal_id, reason, basis_clause_index),
        )
        with pytest.raises(sqlite3.IntegrityError, match="proposal is incomplete"):
            connection.execute(
                """INSERT INTO requirement_plan_evidence_proposal_seals(
                       proposal_id,requirement_count,excluded_user_clause_count,
                       plan_item_count,link_count,payload_sha256,
                       producer_kind,producer_claim_fingerprint,
                       producer_authority,producer_raw_claim_persisted,
                       review_rubric_version,
                       complete_user_clause_classification,graph_fingerprint,
                       sealed_at
                   ) VALUES(?,1,1,0,0,?,?,?,?,?,?,?,?,?)""",
                (
                    proposal_id,
                    payload_sha256,
                    source.proposal.producer_receipt.kind,
                    source.proposal.producer_receipt.claim_fingerprint,
                    source.proposal.producer_receipt.authority,
                    int(source.proposal.producer_receipt.raw_claim_persisted),
                    source.proposal.review_rubric_version,
                    1,
                    graph_fingerprint,
                    created_at,
                ),
            )
        connection.rollback()


def test_exclusion_basis_shape_is_enforced_before_sealing(tmp_path) -> None:
    database, session_id, run, _repository, service = _setup(tmp_path)
    source = _import(service, session_id, run, suffix="basis-shape")
    proposal_id = "8" * 64
    with database._connection() as connection:
        _insert_unsealed_proposal(
            connection,
            source,
            proposal_id=proposal_id,
            requirement_count=0,
            excluded_user_clause_count=2,
        )
        for parameters in (
            (proposal_id, 0, "not_requirement", 0, 1),
            (proposal_id, 1, "withdrawn", None, None),
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    """INSERT INTO requirement_plan_evidence_excluded_user_clauses(
                           proposal_id,ordinal,message_sequence,clause_index,
                           exclusion_reason,basis_message_sequence,
                           basis_clause_index
                       ) VALUES(?,?,0,0,?,?,?)""",
                    parameters,
                )
        connection.rollback()


def test_excluded_user_clause_rows_are_immutable_and_tamper_evident(tmp_path) -> None:
    database, session_id, run, repository, service = _setup(tmp_path)
    confirmed = _confirm(
        service,
        session_id,
        run,
        _import(service, session_id, run, suffix="excluded-clause-tamper"),
        suffix="excluded-clause-tamper",
    )
    proposal_id = confirmed.proposal.proposal_id
    with database._connection() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="are immutable"):
            connection.execute(
                """UPDATE requirement_plan_evidence_excluded_user_clauses
                   SET clause_index=2 WHERE proposal_id=?""",
                (proposal_id,),
            )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="requires parent privacy deletion",
        ):
            connection.execute(
                """DELETE FROM requirement_plan_evidence_excluded_user_clauses
                   WHERE proposal_id=?""",
                (proposal_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="outside proposal"):
            connection.execute(
                """INSERT INTO requirement_plan_evidence_excluded_user_clauses(
                       proposal_id,ordinal,message_sequence,clause_index,
                       exclusion_reason,basis_message_sequence,basis_clause_index
                   ) VALUES(?,1,0,4,'not_requirement',NULL,NULL)""",
                (proposal_id,),
            )
        connection.rollback()

    # Simulate offline corruption after disabling only the child delete guard.
    # Both proposal and confirmed-snapshot hydration must detect the broken seal.
    with database._connection() as connection:
        connection.execute(
            "DROP TRIGGER "
            "requirement_plan_evidence_excluded_user_clauses_privacy_delete_only"
        )
        connection.execute(
            """DELETE FROM requirement_plan_evidence_excluded_user_clauses
               WHERE proposal_id=?""",
            (proposal_id,),
        )
        connection.commit()
    with pytest.raises(DatabaseInvariantError, match="graph is incomplete"):
        repository.get_proposal(proposal_id)
    with pytest.raises(DatabaseInvariantError, match="graph is incomplete"):
        repository.snapshot(session_id, run.input_fingerprint)


def test_exclusion_reason_and_basis_roundtrip_and_graph_tamper_fails_closed(
    tmp_path,
) -> None:
    database, session_id, run, repository, service = _setup(tmp_path)
    payload = _payload_with_withdrawal_basis(session_id, run)
    preview = service.preview(session_id=session_id, payload=payload, now=NOW)
    proposed = service.import_file(
        session_id=session_id,
        payload=payload,
        expected_payload_sha256=preview.payload_sha256,
        confirmation=REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
        idempotency_key="synthetic-withdrawal-basis-import",
        now=NOW,
    )[0]
    confirmed = _confirm(
        service,
        session_id,
        run,
        proposed,
        suffix="withdrawal-basis",
    )
    excluded = confirmed.proposal.excluded_user_clauses
    assert tuple(item.model_dump() for item in excluded) == (
        {
            "coordinate": {"message_sequence": 0, "clause_index": 2},
            "reason": "withdrawn",
            "basis_coordinate": {"message_sequence": 0, "clause_index": 3},
        },
    )
    snapshot = repository.snapshot(session_id, run.input_fingerprint)
    assert snapshot.excluded_user_clauses == excluded
    restarted = _restart_database(
        database
    ).requirement_plan_evidence_repository()
    assert restarted.get_proposal(proposed.proposal.proposal_id) == confirmed
    assert (
        restarted.snapshot(session_id, run.input_fingerprint)
        .excluded_user_clauses
        == excluded
    )

    proposal_id = proposed.proposal.proposal_id
    with database._connection() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="are immutable"):
            connection.execute(
                """UPDATE requirement_plan_evidence_excluded_user_clauses
                   SET exclusion_reason='duplicate' WHERE proposal_id=?""",
                (proposal_id,),
            )
        connection.rollback()
    with database._connection() as connection:
        connection.execute(
            "DROP TRIGGER requirement_plan_evidence_excluded_user_clauses_no_update"
        )
        connection.execute(
            """UPDATE requirement_plan_evidence_excluded_user_clauses
               SET exclusion_reason='duplicate' WHERE proposal_id=?""",
            (proposal_id,),
        )
        connection.commit()
    with pytest.raises(DatabaseInvariantError, match="graph fingerprint is invalid"):
        repository.get_proposal(proposal_id)
    with pytest.raises(DatabaseInvariantError, match="graph fingerprint is invalid"):
        repository.snapshot(session_id, run.input_fingerprint)


def test_producer_claim_receipt_roundtrips_without_raw_claim_and_is_sealed(
    tmp_path,
) -> None:
    database, session_id, run, repository, service = _setup(tmp_path)
    confirmed = _confirm(
        service,
        session_id,
        run,
        _import(service, session_id, run, suffix="producer-seal"),
        suffix="producer-seal",
    )
    proposal_id = confirmed.proposal.proposal_id
    expected = confirmed.proposal.producer_receipt
    assert expected.raw_claim_persisted is False
    assert repository.snapshot(
        session_id, run.input_fingerprint
    ).producer_receipt == expected
    restarted = _restart_database(database).requirement_plan_evidence_repository()
    restarted_view = restarted.get_proposal(proposal_id)
    assert restarted_view is not None
    assert restarted_view.proposal.producer_receipt == expected

    with sqlite3.connect(database.path) as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(requirement_plan_evidence_proposals)"
            )
        }
        assert {
            "producer_id",
            "producer_version",
            "producer_model_id",
        }.isdisjoint(columns)
        stored = connection.execute(
            """SELECT producer_claim_fingerprint,producer_authority,
                      producer_raw_claim_persisted
               FROM requirement_plan_evidence_proposals WHERE proposal_id=?""",
            (proposal_id,),
        ).fetchone()
        assert stored == (
            expected.claim_fingerprint,
            "untrusted_provenance_claim_commitment",
            0,
        )

    with database._connection() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="proposals are immutable"):
            connection.execute(
                """UPDATE requirement_plan_evidence_proposals
                   SET producer_claim_fingerprint=? WHERE proposal_id=?""",
                ("e" * 64, proposal_id),
            )
        with pytest.raises(sqlite3.IntegrityError, match="seals are immutable"):
            connection.execute(
                """UPDATE requirement_plan_evidence_proposal_seals
                   SET producer_claim_fingerprint=? WHERE proposal_id=?""",
                ("e" * 64, proposal_id),
            )
        connection.rollback()

    # Forced offline mutation cannot be mistaken for reviewed provenance.
    with database._connection() as connection:
        connection.execute(
            "DROP TRIGGER requirement_plan_evidence_proposals_no_update"
        )
        connection.execute(
            """UPDATE requirement_plan_evidence_proposals
               SET producer_claim_fingerprint=? WHERE proposal_id=?""",
            ("e" * 64, proposal_id),
        )
        connection.commit()
    with pytest.raises(DatabaseInvariantError, match="provenance is not sealed"):
        repository.get_proposal(proposal_id)
    with pytest.raises(DatabaseInvariantError, match="provenance is not sealed"):
        repository.snapshot(session_id, run.input_fingerprint)


def test_atomic_confirmation_chain_rejects_two_children_of_one_head(tmp_path) -> None:
    _database, session_id, run, _repository, service = _setup(tmp_path)
    first = _confirm(service, session_id, run, _import(service, session_id, run))
    assert first.decision is not None
    predecessor = first.decision.decision_id
    left = _import(
        service, session_id, run, predecessor=predecessor, suffix="left"
    )
    right = _import(
        service, session_id, run, predecessor=predecessor, suffix="right"
    )
    _confirm(service, session_id, run, left, suffix="left")
    with pytest.raises(RequirementPlanConflictError):
        _confirm(service, session_id, run, right, suffix="right")


def test_direct_repository_confirm_rejects_latest_run_roll_and_replay_survives(
    tmp_path,
) -> None:
    database, session_id, source, repository, service = _setup(tmp_path)
    stale = _import(service, session_id, source, suffix="stale")
    decided = _import(service, session_id, source, suffix="replay")
    replay_decision = _decision_record(
        session_id,
        decided,
        decision=RequirementPlanDecisionKind.REJECT,
        suffix="replay",
    )
    rejected, applied = repository.decide(replay_decision)
    assert applied is True
    assert rejected.status is RequirementPlanProposalStatus.REJECTED

    # The exact source window is unchanged, but a newly sealed run is now the
    # only authority allowed to receive a new confirmation.
    successor = source.model_copy(
        update={
            "run_id": "f" * 64,
            "request_fingerprint": "e" * 64,
            "receipt": source.receipt.model_copy(
                update={
                    "completed_at": NOW + timedelta(seconds=1),
                    "predictive_projection": None,
                }
            ),
        }
    )
    runs = database.model_ensemble_repository()
    runs.save_completed(successor)
    latest = runs.get_latest(session_id)
    assert latest is not None
    assert latest.run_id == successor.run_id
    assert latest.input_fingerprint == source.input_fingerprint

    stale_decision = _decision_record(
        session_id,
        stale,
        decision=RequirementPlanDecisionKind.CONFIRM,
        suffix="stale",
    )
    with pytest.raises(
        RequirementPlanConflictError,
        match="decision conflicts with authority",
    ):
        repository.decide(stale_decision)
    still_pending = repository.get_proposal(stale.proposal.proposal_id)
    assert still_pending is not None
    assert still_pending.status is RequirementPlanProposalStatus.PROPOSED

    replayed, applied = repository.decide(replay_decision)
    assert applied is False
    assert replayed == rejected


def test_list_page_count_and_rows_share_one_snapshot_during_concurrent_import(
    tmp_path,
) -> None:
    _database, session_id, run, repository, service = _setup(tmp_path)
    first = _import(service, session_id, run, suffix="page-first")
    original_scope = repository._connection_scope
    inserted = False

    class _InsertBeforeRows:
        def __init__(self, connection):  # type: ignore[no-untyped-def]
            self._connection = connection

        def execute(self, sql, parameters=()):  # type: ignore[no-untyped-def]
            nonlocal inserted
            normalized = " ".join(sql.split())
            if (
                not inserted
                and normalized.startswith(
                    "SELECT proposal_id FROM requirement_plan_evidence_proposals"
                )
            ):
                inserted = True
                _import(service, session_id, run, suffix="page-concurrent")
            return self._connection.execute(sql, parameters)

        def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
            return getattr(self._connection, name)

    @contextmanager
    def injected_scope(*, readonly: bool = False):  # type: ignore[no-untyped-def]
        with original_scope(readonly=readonly) as connection:
            yield _InsertBeforeRows(connection) if readonly else connection

    repository._connection_scope = injected_scope
    try:
        rows, page_snapshot = repository.list_proposals_page(
            session_id,
            limit=20,
            offset=0,
        )
    finally:
        repository._connection_scope = original_scope

    assert inserted is True
    assert page_snapshot.total >= len(rows)
    assert page_snapshot.total == 1
    assert page_snapshot.decision_count == 0
    assert tuple(view.proposal.proposal_id for view in rows) == (
        first.proposal.proposal_id,
    )
    fresh_rows, fresh_snapshot = repository.list_proposals_page(
        session_id,
        limit=20,
        offset=0,
    )
    assert fresh_snapshot.total == 2
    assert fresh_snapshot.decision_count == 0
    assert len(fresh_rows) == 2


def test_repository_page_snapshot_mac_rejects_every_boundary_forgery_before_query(
    tmp_path,
) -> None:
    database, session_id, run, repository, service = _setup(tmp_path)
    proposals = tuple(
        _import(service, session_id, run, suffix=f"repository-mac-{index}")
        for index in range(2)
    )
    rows, snapshot = repository.list_proposals_page(
        session_id,
        limit=1,
        offset=0,
    )
    assert len(rows) == 1
    assert snapshot.total == 2
    assert snapshot.decision_count == 0
    assert snapshot.snapshot_id != "0" * 64
    assert snapshot.high_water_proposal_id is not None
    lower_id = min(item.proposal.proposal_id for item in proposals)
    assert lower_id != snapshot.high_water_proposal_id

    attacks = (
        (
            session_id,
            snapshot.model_copy(update={"total": snapshot.total + 1}),
        ),
        (
            session_id,
            snapshot.model_copy(update={"decision_count": 1}),
        ),
        (
            session_id,
            snapshot.model_copy(update={"high_water_proposal_id": lower_id}),
        ),
        (
            session_id,
            snapshot.model_copy(
                update={
                    "total": 0,
                    "decision_count": 0,
                    "high_water_created_at": None,
                    "high_water_proposal_id": None,
                }
            ),
        ),
        ("f" * 64, snapshot),
    )
    original_scope = repository._connection_scope

    @contextmanager
    def query_must_not_open(*, readonly: bool = False):  # type: ignore[no-untyped-def]
        del readonly
        raise AssertionError("forged page snapshot reached SQLite")
        yield  # pragma: no cover - makes this a context manager

    repository._connection_scope = query_must_not_open
    try:
        for attacked_session_id, forged in attacks:
            with pytest.raises(
                RequirementPlanConflictError,
                match="page snapshot is invalid",
            ):
                repository.list_proposals_page(
                    attacked_session_id,
                    limit=1,
                    offset=0,
                    snapshot=forged,
                )
    finally:
        repository._connection_scope = original_scope

    second_page, repeated = repository.list_proposals_page(
        session_id,
        limit=1,
        offset=1,
        snapshot=snapshot,
    )
    assert len(second_page) == 1
    assert repeated == snapshot
    restarted_repository = _restart_database(
        database
    ).requirement_plan_evidence_repository()
    restarted_page, restarted_snapshot = restarted_repository.list_proposals_page(
        session_id,
        limit=1,
        offset=1,
        snapshot=snapshot,
    )
    assert restarted_page == second_page
    assert restarted_snapshot == snapshot


def test_signed_high_water_snapshot_excludes_later_insert_and_rejects_forgery(
    tmp_path,
) -> None:
    _database, session_id, run, repository, service = _setup(tmp_path)
    initial = tuple(
        _import(service, session_id, run, suffix=f"high-water-{index}")
        for index in range(3)
    )
    first_page, page_snapshot = service.list_page(
        session_id,
        limit=2,
        offset=0,
    )
    assert len(first_page) == 2
    assert page_snapshot.total == 3
    assert page_snapshot.decision_count == 0
    assert page_snapshot.snapshot_id != "0" * 64
    assert page_snapshot.high_water_created_at is not None
    assert page_snapshot.high_water_proposal_id is not None

    later_record = initial[0].proposal.model_copy(
        update={
            "proposal_id": "5" * 64,
            "idempotency_key_digest": "6" * 64,
            "command_fingerprint": "7" * 64,
            "created_at": NOW + timedelta(minutes=2),
        }
    )
    later, applied = repository.issue_proposal(later_record)
    assert applied is True

    second_page, repeated_snapshot = service.list_page(
        session_id,
        limit=2,
        offset=2,
        snapshot=page_snapshot,
    )
    assert repeated_snapshot == page_snapshot
    assert len(second_page) == 1
    frozen_ids = {
        item.proposal.proposal_id for item in (*first_page, *second_page)
    }
    assert frozen_ids == {
        item.proposal.proposal_id for item in initial
    }
    assert later.proposal.proposal_id not in frozen_ids

    fresh_rows, fresh_snapshot = service.list_page(
        session_id,
        limit=10,
        offset=0,
    )
    assert fresh_snapshot.total == 4
    assert fresh_snapshot.decision_count == 0
    assert len(fresh_rows) == 4
    assert later.proposal.proposal_id in {
        item.proposal.proposal_id for item in fresh_rows
    }

    for forged in (
        page_snapshot.model_copy(update={"total": 4}),
        page_snapshot.model_copy(
            update={"high_water_proposal_id": "8" * 64}
        ),
    ):
        with pytest.raises(
            RequirementPlanConflictError,
            match="page snapshot is invalid",
        ):
            service.list_page(
                session_id,
                limit=2,
                offset=2,
                snapshot=forged,
            )


def test_signed_page_snapshot_fails_closed_after_privacy_deletion(tmp_path) -> None:
    database, session_id, run, _repository, service = _setup(tmp_path)
    _import(service, session_id, run, suffix="snapshot-delete")
    _rows, page_snapshot = service.list_page(
        session_id,
        limit=1,
        offset=0,
    )

    assert database.model_ensemble_repository().delete_for_privacy(run.run_id) is True
    with pytest.raises(
        RequirementPlanConflictError,
        match="page snapshot changed",
    ):
        service.list_page(
            session_id,
            limit=1,
            offset=0,
            snapshot=page_snapshot,
        )


def test_direct_mutation_and_delete_are_rejected(tmp_path) -> None:
    database, session_id, run, _repository, service = _setup(tmp_path)
    proposal = _confirm(service, session_id, run, _import(service, session_id, run))
    assert proposal.decision is not None
    with sqlite3.connect(database.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """UPDATE requirement_plan_evidence_proposals
                   SET link_count=0 WHERE proposal_id=?""",
                (proposal.proposal.proposal_id,),
            )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="decision requires parent privacy deletion",
        ):
            connection.execute(
                """DELETE FROM requirement_plan_evidence_decisions
                   WHERE decision_id=?""",
                (proposal.decision.decision_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """DELETE FROM requirement_plan_evidence_proposals
                   WHERE proposal_id=?""",
                (proposal.proposal.proposal_id,),
            )
        connection.rollback()


@pytest.mark.parametrize(
    "decision_kind",
    (RequirementPlanDecisionKind.CONFIRM, RequirementPlanDecisionKind.REJECT),
)
def test_unissued_native_decision_without_keyed_sidecar_fails_every_read(
    tmp_path,
    decision_kind: RequirementPlanDecisionKind,
) -> None:
    database, session_id, run, repository, service = _setup(tmp_path)
    proposal = _import(
        service,
        session_id,
        run,
        suffix=f"unissued-{decision_kind.value}",
    )
    decision = _decision_record(
        session_id,
        proposal,
        decision=decision_kind,
        suffix=f"unissued-{decision_kind.value}",
    )
    with database._connection() as connection:
        connection.execute(
            """INSERT INTO requirement_plan_evidence_decisions(
                   decision_id,proposal_id,session_id,decision,
                   idempotency_key_digest,command_fingerprint,decided_at,
                   confirmation_authority,schema_version,local_only,
                   content_persisted
               ) VALUES(?,?,?,?,?,?,?,?,?,1,0)""",
            (
                decision.decision_id,
                decision.proposal_id,
                decision.session_id,
                decision.decision.value,
                decision.idempotency_key_digest,
                decision.command_fingerprint,
                decision.decided_at.isoformat(timespec="microseconds"),
                decision.confirmation_authority,
                decision.schema_version,
            ),
        )
        connection.commit()

    with pytest.raises(DatabaseInvariantError, match="authority is incomplete"):
        repository.get_proposal(proposal.proposal.proposal_id)
    with pytest.raises(DatabaseInvariantError, match="authority is incomplete"):
        repository.list_proposals_page(session_id, limit=10, offset=0)
    restarted = Database(database.path)
    restarted.configure_local_artifact_id_factory(ARTIFACT_IDS)
    with pytest.raises(DatabaseInvariantError, match="authority is incomplete"):
        restarted.initialize()


def test_issued_decision_rejects_authority_fingerprint_and_kind_tampering(
    tmp_path,
) -> None:
    database, session_id, run, repository, service = _setup(tmp_path)
    confirmed = _confirm(
        service,
        session_id,
        run,
        _import(service, session_id, run, suffix="authority-tamper"),
        suffix="authority-tamper",
    )
    assert confirmed.decision is not None
    with database._connection() as connection:
        connection.execute(
            "DROP TRIGGER requirement_plan_decision_authority_update_exact_m56"
        )
        connection.execute(
            """UPDATE requirement_plan_evidence_decision_authority_m56
               SET authority_fingerprint=? WHERE decision_id=?""",
            ("f" * 64, confirmed.decision.decision_id),
        )
        connection.commit()
    with pytest.raises(DatabaseInvariantError, match="authority is invalid"):
        repository.get_proposal(confirmed.proposal.proposal_id)


def test_keyed_authority_fingerprints_cannot_be_swapped_between_decisions(
    tmp_path,
) -> None:
    database, session_id, run, repository, service = _setup(tmp_path)
    first_proposal = _import(service, session_id, run, suffix="swap-first")
    second_proposal = _import(service, session_id, run, suffix="swap-second")
    confirmed = _confirm(
        service,
        session_id,
        run,
        first_proposal,
        suffix="swap-first",
    )
    rejected, applied = service.decide(
        session_id=session_id,
        proposal_id=second_proposal.proposal.proposal_id,
        command=RequirementPlanDecisionCommand(
            expected_source_run_id=run.run_id,
            decision=RequirementPlanDecisionKind.REJECT,
            confirmation=REQUIREMENT_PLAN_DECISION_CONFIRMATION,
        ),
        idempotency_key="synthetic-requirement-plan-decision-swap-second",
    )
    assert applied is True
    assert confirmed.decision is not None
    assert rejected.decision is not None

    with database._connection() as connection:
        connection.execute(
            "DROP TRIGGER requirement_plan_decision_authority_update_exact_m56"
        )
        rows = connection.execute(
            """SELECT decision_id,authority_fingerprint
               FROM requirement_plan_evidence_decision_authority_m56
               WHERE decision_id IN (?,?) ORDER BY decision_id""",
            (confirmed.decision.decision_id, rejected.decision.decision_id),
        ).fetchall()
        assert len(rows) == 2
        connection.execute(
            """UPDATE requirement_plan_evidence_decision_authority_m56
               SET authority_fingerprint=CASE decision_id
                 WHEN ? THEN ? WHEN ? THEN ? ELSE authority_fingerprint END
               WHERE decision_id IN (?,?)""",
            (
                rows[0]["decision_id"],
                rows[1]["authority_fingerprint"],
                rows[1]["decision_id"],
                rows[0]["authority_fingerprint"],
                rows[0]["decision_id"],
                rows[1]["decision_id"],
            ),
        )
        connection.commit()

    for proposal_id in (
        confirmed.proposal.proposal_id,
        rejected.proposal.proposal_id,
    ):
        with pytest.raises(DatabaseInvariantError, match="authority is invalid"):
            repository.get_proposal(proposal_id)
    with pytest.raises(DatabaseInvariantError, match="authority is invalid"):
        repository.snapshot(session_id, run.input_fingerprint)

    with database._connection() as connection:
        connection.execute(
            "DROP TRIGGER requirement_plan_evidence_decisions_no_update"
        )
        connection.execute(
            """UPDATE requirement_plan_evidence_decisions SET decision='reject'
               WHERE decision_id=?""",
            (confirmed.decision.decision_id,),
        )
        connection.commit()
    with pytest.raises(DatabaseInvariantError, match="authority is invalid"):
        repository.get_proposal(confirmed.proposal.proposal_id)


def test_direct_session_delete_cascades_confirmed_proposal_and_authority(
    tmp_path,
) -> None:
    database, session_id, run, repository, service = _setup(tmp_path)
    proposal = _confirm(
        service,
        session_id,
        run,
        _import(service, session_id, run, suffix="session-delete"),
        suffix="session-delete",
    )
    assert proposal.status is RequirementPlanProposalStatus.CONFIRMED

    with database._connection() as connection:
        connection.execute("PRAGMA trusted_schema=ON")
        connection.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        connection.commit()
        for table in (
            "session_model_ensemble_runs",
            "requirement_plan_evidence_proposals",
            "requirement_plan_evidence_requirements",
            "requirement_plan_evidence_excluded_user_clauses",
            "requirement_plan_evidence_plans",
            "requirement_plan_evidence_links",
            "requirement_plan_evidence_proposal_seals",
            "requirement_plan_evidence_decisions",
            "requirement_plan_evidence_decision_authority_m56",
        ):
            assert connection.execute(
                f"SELECT COUNT(*) FROM {table}"  # noqa: S608 - closed constants
            ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    assert repository.get_proposal(proposal.proposal.proposal_id) is None


def test_confirmed_decision_sidecar_cascades_on_run_and_session_privacy_delete(
    tmp_path,
) -> None:
    database, session_id, run, repository, service = _setup(tmp_path)
    confirmed = _confirm(
        service,
        session_id,
        run,
        _import(service, session_id, run, suffix="confirmed-cascade"),
        suffix="confirmed-cascade",
    )
    assert confirmed.decision is not None

    assert database.model_ensemble_repository().delete_for_privacy(run.run_id) is True
    with sqlite3.connect(database.path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM requirement_plan_evidence_decisions"
        ).fetchone()[0] == 0
        assert connection.execute(
            """SELECT COUNT(*)
               FROM requirement_plan_evidence_decision_authority_m56"""
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert repository.get_proposal(confirmed.proposal.proposal_id) is None


def test_schema_55_is_content_free_and_migration_54_is_unchanged(tmp_path) -> None:
    database, _session_id, _run, _repository, _service = _setup(tmp_path)
    from prompt_enhancer.infrastructure.sqlite import migrations

    assert database.summary()["schema_version"] == 61
    assert hashlib.sha256(migrations.MIGRATION_54.encode()).hexdigest() == (
        "aafd1c1cc0c121db267d02f7cf14c1a05e6a796af5affda2988fa700216576ac"
    )
    forbidden = ("transcript", "message_text", "file_path", "score", "rationale")
    lowered = migrations.MIGRATION_55.casefold()
    # SQL comments mention excluded concepts; inspect column declarations only.
    with sqlite3.connect(database.path) as connection:
        for table in (
            "requirement_plan_evidence_proposals",
            "requirement_plan_evidence_requirements",
            "requirement_plan_evidence_excluded_user_clauses",
            "requirement_plan_evidence_plans",
            "requirement_plan_evidence_links",
            "requirement_plan_evidence_decisions",
        ):
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            assert not any(term in column.casefold() for term in forbidden for column in columns)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert "requirement_plan_evidence_proposals" in lowered
