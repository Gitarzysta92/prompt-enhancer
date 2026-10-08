"""Normalized, content-free persistence for local measured/predictive analysis."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
import hashlib
import hmac
import json

from ...application.analysis.model_ensemble import (
    ChunkMetricCommitteeReceipt,
    ModelEnsembleChunkReceipt,
    ModelEvidenceSelectionReceipt,
    ModelExpertIdentity,
    ModelExpertReceipt,
    ModelExpertRole,
    ModelExpertStatus,
    ModelMetricVote,
    ModelVoteState,
    MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION,
    SessionModelEnsembleMetricReceipt,
    SessionModelEnsembleReceipt,
    SessionModelEnsembleTypedMetricReceipt,
    SourceCoverageState,
)
from ...application.analysis.metric_contract_v2 import (
    DenominatorBasis,
    EvidenceAuthority,
    METRIC_CONTRACTS_V2,
    MetricValueStateV2,
)
from ...application.analysis.metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_2,
    METRIC_PROJECTION_V2_VERSION_3,
    METRIC_PROJECTION_V2_VERSION_4,
    METRIC_PROJECTION_V2_VERSION_5,
    METRIC_PROJECTION_V2_VERSION_6,
    METRIC_PROJECTION_V2_VERSION_7,
    METRIC_PROJECTION_V2_VERSION_8,
    MetricStateV2,
    OpportunityStatistics,
    _issue_metric_state_projection,
    reviewed_requirement_plan_denominator_is_authoritative,
)
from ...application.analysis.metric_publication_v2 import (
    METRIC_PUBLICATION_V2_KEY,
    METRIC_PUBLICATION_V2_VERSION,
    MetricPublicationSource,
    MetricPublicationV2,
    metric_publication_v2_fingerprint,
    publish_metric_states_v2,
)
from ...application.analysis.requirement_action_evidence import (
    RequirementActionDecisionKind,
    RequirementActionEvidenceSnapshot,
    requirement_action_evidence_snapshot_fingerprint,
    requirement_plan_snapshot_fingerprint,
)
from ...application.analysis.requirement_plan_evidence import (
    RequirementPlanDecisionKind,
)
from ...application.analysis.requirement_verification_evidence import (
    RequirementAcceptanceOutcome,
    RequirementVerificationOutcome,
    issue_requirement_verification_opportunities,
)
from ...application.analysis.session_model_ensemble import (
    MetricProfileSource,
    RequirementActionEvidenceSource,
    RequirementPlanEvidenceSource,
    REQUIREMENT_VERIFICATION_BINDING_SCHEMA_VERSION,
    RequirementVerificationEvidenceSource,
    SessionModelEnsemblePersistenceAuthority,
    SessionModelEnsembleRepository,
    SessionModelEnsembleRunRecord,
    SessionMetricProfileBinding,
    SessionRequirementActionEvidenceBinding,
    SessionRequirementPlanEvidenceBinding,
    SessionRequirementVerificationEvidenceBinding,
    validate_requirement_action_binding_metric_state,
    validate_requirement_plan_binding_metric_state,
    validate_requirement_verification_binding_metric_state,
    validate_r8_typed_metric_projection,
    validate_reviewed_requirement_action_snapshot_metric_state,
    validate_reviewed_requirement_plan_outcomes_metric_state,
)
from ...application.analysis.semantic_units import (
    SEMANTIC_UNIT_CONTRACT_VERSION,
    SEMANTIC_UNIT_SCHEMA_VERSION,
    SemanticUnitReceipt,
    SemanticUnitReconciliation,
)
from ...application.analysis.probabilistic_metrics import (
    PROBABILISTIC_METRIC_PROJECTION_VERSION,
    PROBABILISTIC_METRIC_CONTRACTS,
    FactorScale,
    PredictiveFactorContribution,
    PredictiveMetricState,
    PredictiveMetricTarget,
    PredictiveModelStageReceipt,
    SessionPredictiveMetricProjection,
    SessionPredictiveMetricReceipt,
)
from ...application.persistence import MetricValueState
from ...database import DatabaseInvariantError
from ...domain import Provider
from ..identifiers import LocalArtifactIdFactory
from ._common import ConnectionScope, from_iso, require_safe_id, to_iso


def _graph_fingerprint(run: SessionModelEnsembleRunRecord) -> str:
    payload = run.model_dump(mode="json")
    # This append-only adjunct has its own seal and is not part of the frozen
    # base-run graph commitment.
    payload.pop("metric_profile_binding", None)
    payload.pop("requirement_plan_evidence_binding", None)
    payload.pop("requirement_action_evidence_binding", None)
    payload.pop("requirement_verification_evidence_binding", None)
    receipt = payload["receipt"]
    # The typed projection is an append-only adjunct with its own seal.  Keep
    # the original v26 graph commitment byte-compatible for legacy runs.
    receipt.pop("metric_projection_version", None)
    receipt.pop("metric_projection_completed_at", None)
    receipt.pop("typed_metrics", None)
    receipt.pop("metric_publication_v2", None)
    receipt.pop("predictive_projection", None)
    receipt["chunk_plan"] = sorted(
        receipt["chunk_plan"], key=lambda item: item["ordinal"]
    )
    receipt["chunks"] = sorted(
        receipt["chunks"],
        key=lambda item: (item["chunk_ordinal"], item["metric_key"]),
    )
    receipt["metrics"] = sorted(
        receipt["metrics"], key=lambda item: item["metric_key"]
    )
    receipt["experts"] = sorted(
        receipt["experts"], key=lambda item: item["identity"]["ordinal"]
    )
    receipt["evidence_selections"] = sorted(
        receipt["evidence_selections"],
        key=lambda item: (
            item["chunk_ordinal"],
            item["metric_key"],
            item["model_key"],
        ),
    )
    receipt["model_votes"] = sorted(
        receipt["model_votes"],
        key=lambda item: (
            item["chunk_ordinal"],
            item["metric_key"],
            item["model_key"],
        ),
    )
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _metric_state_v2_from_row(item: object) -> MetricStateV2:
    """Hydrate one content-free V2 row through the application validators."""

    return MetricStateV2(
        metric_key=item["metric_key"],  # type: ignore[index]
        registry_version=item["registry_version"],  # type: ignore[index]
        contract_version=item["contract_version"],  # type: ignore[index]
        contract_fingerprint=item["contract_fingerprint"],  # type: ignore[index]
        evidence_authority=EvidenceAuthority(item["evidence_authority"]),  # type: ignore[index]
        value_state=MetricValueStateV2(item["value_state"]),  # type: ignore[index]
        explanation_code=item["explanation_code"],  # type: ignore[index]
        numerator=item["numerator"],  # type: ignore[index]
        denominator=item["denominator"],  # type: ignore[index]
        numeric_value=item["numeric_value"],  # type: ignore[index]
        censoring_lower_bound=item["censoring_lower_bound"],  # type: ignore[index]
        censoring_upper_bound=item["censoring_upper_bound"],  # type: ignore[index]
        statistics=OpportunityStatistics(
            metric_key=item["metric_key"],  # type: ignore[index]
            denominator_basis=DenominatorBasis(item["denominator_basis"]),  # type: ignore[index]
            opportunity_unit_kind=item["opportunity_unit_kind"],  # type: ignore[index]
            capability_available=bool(item["capability_available"]),  # type: ignore[index]
            source_complete=bool(item["source_complete"]),  # type: ignore[index]
            eligible_count=item["eligible_count"],  # type: ignore[index]
            met_count=item["met_count"],  # type: ignore[index]
            not_met_count=item["not_met_count"],  # type: ignore[index]
            pending_count=item["pending_count"],  # type: ignore[index]
            unknown_count=item["unknown_count"],  # type: ignore[index]
            superseded_excluded_count=item[  # type: ignore[index]
                "superseded_excluded_count"
            ],
            distinct_owner_count=item["distinct_owner_count"],  # type: ignore[index]
        ),
        projection_version=item["projection_version"],  # type: ignore[index]
        product_metric_eligible=bool(item["product_metric_eligible"]),  # type: ignore[index]
    )


def _metric_projection_fingerprint(receipt: SessionModelEnsembleReceipt) -> str:
    payload = {
        "projection_version": receipt.metric_projection_version,
        "projected_at": (
            None
            if receipt.metric_projection_completed_at is None
            else receipt.metric_projection_completed_at.isoformat()
        ),
        "metrics": sorted(
            (item.model_dump(mode="json") for item in receipt.typed_metrics),
            key=lambda item: item["metric_key"],
        ),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _predictive_projection_fingerprint(
    projection: SessionPredictiveMetricProjection,
) -> str:
    payload = projection.model_dump(mode="json")
    payload["metrics"] = sorted(
        payload["metrics"], key=lambda item: item["metric_key"]
    )
    for metric in payload["metrics"]:
        metric["factors"] = sorted(
            metric["factors"], key=lambda item: item["factor_key"]
        )
    payload["model_stages"] = sorted(
        payload["model_stages"], key=lambda item: item["model_key"]
    )
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


#: Sidecar tables per projection identity, newest first.  The r1 pair (frozen
#: at MIGRATION_40), r2 (MIGRATION_41), and r3 (MIGRATION_42) never gain a row
#: from current code; r4 is frozen at MIGRATION_44 and the profile-bound r5
#: pair added by MIGRATION_54 receives every new publication.  All five stay
#: readable, and a run carries at most one pair.
METRIC_V2_SIDECARS = (
    (
        METRIC_PROJECTION_V2_VERSION_8,
        "session_model_ensemble_metric_states_v2_r8",
        "session_model_ensemble_metric_publication_v2_seals_r8",
    ),
    (
        METRIC_PROJECTION_V2_VERSION_7,
        "session_model_ensemble_metric_states_v2_r7",
        "session_model_ensemble_metric_publication_v2_seals_r7",
    ),
    (
        METRIC_PROJECTION_V2_VERSION_6,
        "session_model_ensemble_metric_states_v2_r6",
        "session_model_ensemble_metric_publication_v2_seals_r6",
    ),
    (
        METRIC_PROJECTION_V2_VERSION_5,
        "session_model_ensemble_metric_states_v2_r5",
        "session_model_ensemble_metric_publication_v2_seals_r5",
    ),
    (
        METRIC_PROJECTION_V2_VERSION_4,
        "session_model_ensemble_metric_states_v2_r4",
        "session_model_ensemble_metric_publication_v2_seals_r4",
    ),
    (
        METRIC_PROJECTION_V2_VERSION_3,
        "session_model_ensemble_metric_states_v2_r3",
        "session_model_ensemble_metric_publication_v2_seals_r3",
    ),
    (
        METRIC_PROJECTION_V2_VERSION_2,
        "session_model_ensemble_metric_states_v2_r2",
        "session_model_ensemble_metric_publication_v2_seals_r2",
    ),
    (
        "metric-contract-v2-projection-1",
        "session_model_ensemble_metric_states_v2",
        "session_model_ensemble_metric_publication_v2_seals",
    ),
)


def _metric_v2_tables(projection_version: str) -> tuple[str, str]:
    for version, states_table, seals_table in METRIC_V2_SIDECARS:
        if projection_version == version:
            return states_table, seals_table
    raise DatabaseInvariantError("metric V2 projection identity is unsupported")


def _metric_publication_v2_fingerprint(
    publication: MetricPublicationV2,
) -> str:
    """Delegate to the one canonical definition the API projection also reads."""

    return metric_publication_v2_fingerprint(publication)


def _metric_profile_binding_fingerprint(
    binding: SessionMetricProfileBinding,
) -> str:
    return hashlib.sha256(
        json.dumps(
            binding.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _metric_publication_profile_fingerprint(
    publication: MetricPublicationV2,
    binding: SessionMetricProfileBinding,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "profile_binding_fingerprint": (
                    _metric_profile_binding_fingerprint(binding)
                ),
                "projection_fingerprint": (
                    _metric_publication_v2_fingerprint(publication)
                ),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _requirement_plan_binding_fingerprint(
    binding: SessionRequirementPlanEvidenceBinding,
) -> str:
    return hashlib.sha256(
        json.dumps(
            binding.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _metric_publication_requirement_plan_fingerprint(
    publication: MetricPublicationV2,
    binding: SessionRequirementPlanEvidenceBinding,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "requirement_plan_binding_fingerprint": (
                    _requirement_plan_binding_fingerprint(binding)
                ),
                "projection_fingerprint": (
                    _metric_publication_v2_fingerprint(publication)
                ),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _requirement_action_binding_fingerprint(
    binding: SessionRequirementActionEvidenceBinding,
) -> str:
    return hashlib.sha256(
        json.dumps(
            binding.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _metric_publication_requirement_action_fingerprint(
    publication: MetricPublicationV2,
    binding: SessionRequirementActionEvidenceBinding,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "requirement_action_binding_fingerprint": (
                    _requirement_action_binding_fingerprint(binding)
                ),
                "projection_fingerprint": (
                    _metric_publication_v2_fingerprint(publication)
                ),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _requirement_verification_binding_fingerprint(
    binding: SessionRequirementVerificationEvidenceBinding,
    identifiers: LocalArtifactIdFactory,
) -> str:
    return identifiers.fingerprint(
        REQUIREMENT_VERIFICATION_BINDING_SCHEMA_VERSION,
        binding.authority_identity(),
    )


def _metric_publication_requirement_verification_fingerprint(
    publication: MetricPublicationV2,
    binding: SessionRequirementVerificationEvidenceBinding,
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "requirement_verification_binding_fingerprint": (
                    binding.binding_fingerprint
                ),
                "projection_fingerprint": (
                    _metric_publication_v2_fingerprint(publication)
                ),
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _semantic_unit_reconciliation_fingerprint(
    reconciliation: SemanticUnitReconciliation,
) -> str:
    """Seal an already content-free canonical semantic-unit projection."""

    return hashlib.sha256(
        json.dumps(
            reconciliation.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


class SqliteSessionModelEnsembleRepository(SessionModelEnsembleRepository):
    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
        *,
        identifiers: LocalArtifactIdFactory | None = None,
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized
        self._identifiers = identifiers

    def save_completed(
        self,
        run: SessionModelEnsembleRunRecord,
        *,
        authority: SessionModelEnsemblePersistenceAuthority | None = None,
        semantic_units: SemanticUnitReconciliation | None = None,
    ) -> None:
        self._ensure_initialized()
        receipt = run.receipt
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if authority is not None:
                    active = connection.execute(
                        """SELECT 1
                           FROM session_model_ensemble_watches
                           WHERE watch_id=? AND state='running'
                             AND generation=? AND lease_owner=? AND lease_token=?
                             AND lease_expires_at>? AND session_id=? AND provider=?
                             AND latest_run_id IS ?""",
                        (
                            authority.watch_id,
                            authority.generation,
                            authority.owner,
                            authority.token,
                            to_iso(authority.observed_at),
                            run.session_id,
                            run.provider.value,
                            authority.prior_run_id,
                        ),
                    ).fetchone()
                    if active is None:
                        raise DatabaseInvariantError(
                            "model ensemble watch persistence authority is no longer active"
                        )
                session = connection.execute(
                    "SELECT provider FROM sessions WHERE session_id=?",
                    (run.session_id,),
                ).fetchone()
                if session is None or session["provider"] != run.provider.value:
                    raise DatabaseInvariantError(
                        "model ensemble target does not match an indexed session"
                    )
                connection.execute(
                    """
                    INSERT INTO session_model_ensemble_runs(
                        run_id,session_id,request_fingerprint,input_fingerprint,
                        provider,provider_version,adapter_version,source_schema_version,
                        content_schema_version,redactor_version,consent_policy_version,
                        plan_version,plan_fingerprint,source_window_fingerprint,
                        source_coverage_state,chunk_count,model_count,metric_count,
                        created_at,completed_at,local_only,content_persisted,
                        calibration_state,product_metric_eligible
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,0,'not_assessed',0)
                    """,
                    (
                        run.run_id,
                        run.session_id,
                        run.request_fingerprint,
                        run.input_fingerprint,
                        run.provider.value,
                        run.provider_version,
                        run.adapter_version,
                        run.source_schema_version,
                        run.content_schema_version,
                        run.redactor_version,
                        run.consent_policy_version,
                        receipt.plan_version,
                        receipt.plan_fingerprint,
                        receipt.source_window_fingerprint,
                        receipt.source_coverage_state.value,
                        receipt.chunk_count,
                        receipt.model_count,
                        len(receipt.metrics),
                        to_iso(receipt.created_at),
                        to_iso(receipt.completed_at),
                    ),
                )
                connection.executemany(
                    """INSERT INTO session_model_ensemble_chunks
                       VALUES(?,?,?,?,?,?)""",
                    (
                        (
                            run.run_id,
                            chunk.ordinal,
                            chunk.chunk_fingerprint,
                            chunk.source_message_count,
                            chunk.fragment_count,
                            chunk.character_count,
                        )
                        for chunk in receipt.chunk_plan
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO session_model_ensemble_experts(
                        run_id,model_ordinal,model_key,role,repository_id,revision,
                        tokenizer_id,license_spdx,backend_key,contributes_to_decision,
                        status,error_code,device,inference_latency_ms,
                        peak_accelerator_memory_mb,process_rss_mb,
                        unloaded_after_stage,calibration_state
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,'not_assessed')
                    """,
                    (
                        (
                            run.run_id,
                            expert.identity.ordinal,
                            expert.identity.model_key,
                            expert.identity.role.value,
                            expert.identity.repository_id,
                            expert.identity.revision,
                            expert.identity.tokenizer_id,
                            expert.identity.license_spdx,
                            expert.identity.backend_key,
                            int(expert.identity.contributes_to_decision),
                            expert.status.value,
                            expert.error_code,
                            expert.device,
                            expert.inference_latency_ms,
                            expert.peak_accelerator_memory_mb,
                            expert.process_rss_mb,
                        )
                        for expert in receipt.experts
                    ),
                )
                for selection in receipt.evidence_selections:
                    connection.execute(
                        """INSERT INTO session_model_ensemble_evidence_selections
                           VALUES(?,?,?,?,?,?,?,?,?,'not_assessed')""",
                        (
                            run.run_id,
                            selection.chunk_ordinal,
                            selection.metric_key,
                            selection.model_key,
                            selection.role.value,
                            selection.candidate_count,
                            len(selection.selected_fragment_ids),
                            selection.ranking_fingerprint,
                            selection.top_raw_score,
                        ),
                    )
                    connection.executemany(
                        """INSERT INTO session_model_ensemble_selection_fragments
                           VALUES(?,?,?,?,?,?)""",
                        (
                            (
                                run.run_id,
                                selection.chunk_ordinal,
                                selection.metric_key,
                                selection.model_key,
                                ordinal,
                                fragment_id,
                            )
                            for ordinal, fragment_id in enumerate(
                                selection.selected_fragment_ids
                            )
                        ),
                    )
                for vote in receipt.model_votes:
                    connection.execute(
                        """INSERT INTO session_model_ensemble_votes
                           VALUES(?,?,?,?,?,?,?,?,?,'not_assessed')""",
                        (
                            run.run_id,
                            vote.chunk_ordinal,
                            vote.metric_key,
                            vote.model_key,
                            vote.role.value,
                            vote.state.value,
                            vote.raw_score,
                            len(vote.evidence_fragment_ids),
                            vote.reason_code,
                        ),
                    )
                    connection.executemany(
                        """INSERT INTO session_model_ensemble_vote_fragments
                           VALUES(?,?,?,?,?,?)""",
                        (
                            (
                                run.run_id,
                                vote.chunk_ordinal,
                                vote.metric_key,
                                vote.model_key,
                                ordinal,
                                fragment_id,
                            )
                            for ordinal, fragment_id in enumerate(
                                vote.evidence_fragment_ids
                            )
                        ),
                    )
                connection.executemany(
                    """INSERT INTO session_model_ensemble_chunk_metrics
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        (
                            run.run_id,
                            item.chunk_ordinal,
                            item.metric_key,
                            item.value_state.value,
                            item.numerator,
                            item.denominator,
                            item.rubric_vote.value,
                            item.contributing_nli_votes,
                            item.diagnostic_nli_votes,
                            item.reason_code,
                        )
                        for item in receipt.chunks
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO session_model_ensemble_metrics(
                        run_id,metric_key,value_state,numerator,denominator,
                        numeric_value,known_chunk_count,abstained_chunk_count,
                        unsupported_chunk_count,failed_chunk_count,total_chunk_count,
                        explanation_code,calibration_state,product_metric_eligible
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'not_assessed',0)
                    """,
                    (
                        (
                            run.run_id,
                            item.metric_key,
                            item.value_state.value,
                            item.numerator,
                            item.denominator,
                            item.numeric_value,
                            item.known_chunk_count,
                            item.abstained_chunk_count,
                            item.unsupported_chunk_count,
                            item.failed_chunk_count,
                            item.total_chunk_count,
                            item.explanation_code,
                        )
                        for item in receipt.metrics
                    ),
                )
                selection_fragment_count = sum(
                    len(item.selected_fragment_ids)
                    for item in receipt.evidence_selections
                )
                vote_fragment_count = sum(
                    len(item.evidence_fragment_ids) for item in receipt.model_votes
                )
                connection.execute(
                    """INSERT INTO session_model_ensemble_seals
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        run.run_id,
                        _graph_fingerprint(run),
                        receipt.chunk_count,
                        len(receipt.experts),
                        len(receipt.evidence_selections),
                        selection_fragment_count,
                        len(receipt.model_votes),
                        vote_fragment_count,
                        len(receipt.chunks),
                        len(receipt.metrics),
                        to_iso(receipt.completed_at),
                    ),
                )
                self._insert_metric_profile_binding(connection, run)
                self._insert_requirement_plan_binding(connection, run)
                self._insert_requirement_action_binding(connection, run)
                self._insert_requirement_verification_binding(
                    connection,
                    run,
                    require_current=True,
                )
                self._insert_metric_projection(connection, run)
                self._insert_metric_publication_v2(connection, run)
                self._insert_predictive_projection(connection, run)
                self._insert_semantic_unit_reconciliation(
                    connection,
                    run,
                    semantic_units,
                )
                hydrated = self._hydrate(connection, run.run_id)
                if (
                    hydrated is None
                    or _graph_fingerprint(hydrated) != _graph_fingerprint(run)
                    or hydrated.receipt.metric_publication_v2
                    != run.receipt.metric_publication_v2
                    or hydrated.metric_profile_binding
                    != run.metric_profile_binding
                    or hydrated.requirement_plan_evidence_binding
                    != run.requirement_plan_evidence_binding
                    or hydrated.requirement_action_evidence_binding
                    != run.requirement_action_evidence_binding
                    or hydrated.requirement_verification_evidence_binding
                    != run.requirement_verification_evidence_binding
                ):
                    raise DatabaseInvariantError(
                        "stored model ensemble graph failed exact rehydration"
                    )
                hydrated_semantic_units = self._hydrate_semantic_units(
                    connection,
                    run.run_id,
                )
                if hydrated_semantic_units != semantic_units:
                    raise DatabaseInvariantError(
                        "stored semantic-unit sidecar failed exact rehydration"
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def save_metric_projection(
        self,
        run: SessionModelEnsembleRunRecord,
        *,
        authority: SessionModelEnsemblePersistenceAuthority | None = None,
    ) -> None:
        """Append the current typed projection to an already sealed legacy run."""

        self._ensure_initialized()
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if (
                    run.receipt.metric_publication_v2 is not None
                    and run.receipt.metric_publication_v2.projection_version
                    == METRIC_PROJECTION_V2_VERSION_8
                ):
                    raise DatabaseInvariantError(
                        "r8 projection requires one atomic completed-run save"
                    )
                if authority is not None:
                    active = connection.execute(
                        """SELECT 1 FROM session_model_ensemble_watches
                           WHERE watch_id=? AND state='running'
                             AND generation=? AND lease_owner=? AND lease_token=?
                             AND lease_expires_at>? AND session_id=? AND provider=?
                             AND latest_run_id=?""",
                        (
                            authority.watch_id,
                            authority.generation,
                            authority.owner,
                            authority.token,
                            to_iso(authority.observed_at),
                            run.session_id,
                            run.provider.value,
                            run.run_id,
                        ),
                    ).fetchone()
                    if active is None or authority.prior_run_id != run.run_id:
                        raise DatabaseInvariantError(
                            "model ensemble watch projection authority is no longer active"
                        )
                stored = self._hydrate(connection, run.run_id)
                if stored is None or _graph_fingerprint(stored) != _graph_fingerprint(run):
                    raise DatabaseInvariantError(
                        "typed metric projection does not match the sealed ensemble run"
                    )
                if (
                    stored.metric_profile_binding is not None
                    and stored.metric_profile_binding != run.metric_profile_binding
                ):
                    raise DatabaseInvariantError(
                        "metric profile binding does not match the sealed ensemble run"
                    )
                if (
                    stored.requirement_plan_evidence_binding is not None
                    and stored.requirement_plan_evidence_binding
                    != run.requirement_plan_evidence_binding
                ):
                    raise DatabaseInvariantError(
                        "requirement-plan binding does not match the sealed run"
                    )
                if (
                    stored.requirement_action_evidence_binding is not None
                    and stored.requirement_action_evidence_binding
                    != run.requirement_action_evidence_binding
                ):
                    raise DatabaseInvariantError(
                        "requirement-action binding does not match the sealed run"
                    )
                self._insert_metric_profile_binding(connection, run)
                self._insert_requirement_plan_binding(connection, run)
                self._insert_requirement_action_binding(connection, run)
                self._insert_metric_projection(connection, run)
                self._insert_metric_publication_v2(connection, run)
                self._insert_predictive_projection(connection, run)
                hydrated = self._hydrate(connection, run.run_id)
                if (
                    hydrated is None
                    or hydrated.receipt.metric_projection_version
                    != run.receipt.metric_projection_version
                    or hydrated.receipt.metric_projection_completed_at
                    != run.receipt.metric_projection_completed_at
                    or hydrated.receipt.typed_metrics != run.receipt.typed_metrics
                    or hydrated.receipt.metric_publication_v2
                    != run.receipt.metric_publication_v2
                    or hydrated.metric_profile_binding
                    != run.metric_profile_binding
                    or hydrated.requirement_plan_evidence_binding
                    != run.requirement_plan_evidence_binding
                    or hydrated.requirement_action_evidence_binding
                    != run.requirement_action_evidence_binding
                    or hydrated.requirement_verification_evidence_binding
                    != run.requirement_verification_evidence_binding
                ):
                    raise DatabaseInvariantError(
                        "typed metric projection failed exact rehydration"
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _insert_metric_profile_binding(
        connection,
        run: SessionModelEnsembleRunRecord,
    ) -> None:
        binding = run.metric_profile_binding
        existing = SqliteSessionModelEnsembleRepository._hydrate_metric_profile_binding(
            connection,
            run.run_id,
        )
        if binding is None:
            if existing is not None:
                raise DatabaseInvariantError(
                    "stored metric profile binding is missing from the run"
                )
            return
        if existing is not None:
            if existing != binding:
                raise DatabaseInvariantError("metric profile binding is immutable")
            return
        connection.execute(
            """
            INSERT INTO session_model_ensemble_metric_profile_bindings(
                run_id,profile_source,provider,session_id,
                source_window_fingerprint,profile_id,profile_revision,
                profile_fingerprint,profile_schema_version,
                profile_policy_version,bound_at,binding_fingerprint,
                local_only,content_persisted
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,0)
            """,
            (
                run.run_id,
                binding.profile_source.value,
                binding.provider.value,
                binding.session_id,
                binding.source_window_fingerprint,
                binding.profile_id,
                binding.profile_revision,
                binding.profile_fingerprint,
                binding.profile_schema_version,
                binding.profile_policy_version,
                to_iso(binding.bound_at),
                _metric_profile_binding_fingerprint(binding),
            ),
        )
        stored = SqliteSessionModelEnsembleRepository._hydrate_metric_profile_binding(
            connection,
            run.run_id,
        )
        if stored != binding:
            raise DatabaseInvariantError(
                "metric profile binding failed exact rehydration"
            )

    @staticmethod
    def _hydrate_metric_profile_binding(
        connection,
        run_id: str,
    ) -> SessionMetricProfileBinding | None:
        # Repository upgrade fixtures deliberately hydrate pre-M54 schemas.
        present = connection.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table'
                 AND name='session_model_ensemble_metric_profile_bindings'"""
        ).fetchone()
        if present is None:
            return None
        row = connection.execute(
            """SELECT * FROM session_model_ensemble_metric_profile_bindings
               WHERE run_id=?""",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        binding = SessionMetricProfileBinding(
            profile_source=MetricProfileSource(row["profile_source"]),
            provider=Provider(row["provider"]),
            session_id=row["session_id"],
            source_window_fingerprint=row["source_window_fingerprint"],
            profile_id=row["profile_id"],
            profile_revision=row["profile_revision"],
            profile_fingerprint=row["profile_fingerprint"],
            profile_schema_version=row["profile_schema_version"],
            profile_policy_version=row["profile_policy_version"],
            bound_at=from_iso(row["bound_at"]),
            local_only=bool(row["local_only"]),
            content_persisted=bool(row["content_persisted"]),
        )
        if row["binding_fingerprint"] != _metric_profile_binding_fingerprint(
            binding
        ):
            raise DatabaseInvariantError("metric profile binding seal is invalid")
        return binding

    def _insert_requirement_plan_binding(
        self,
        connection,
        run: SessionModelEnsembleRunRecord,
    ) -> None:
        binding = run.requirement_plan_evidence_binding
        publication = run.receipt.metric_publication_v2
        if binding is not None and publication is not None:
            state = next(
                item.state
                for item in publication.metrics
                if item.state.metric_key == "logic.decomposition_coverage"
            )
            self._validate_requirement_plan_binding_authority(
                connection,
                binding,
                state,
            )
        existing = (
            SqliteSessionModelEnsembleRepository._hydrate_requirement_plan_binding(
                connection,
                run.run_id,
            )
        )
        if binding is None:
            if existing is not None:
                raise DatabaseInvariantError(
                    "stored requirement-plan binding is missing from the run"
                )
            return
        if existing is not None:
            if existing != binding:
                raise DatabaseInvariantError(
                    "requirement-plan binding is immutable"
                )
            return
        connection.execute(
            """INSERT INTO session_model_ensemble_requirement_plan_bindings(
                   run_id,evidence_source,session_id,source_window_fingerprint,
                   confirmation_id,proposal_id,evidence_fingerprint,
                   evidence_schema_version,evidence_policy_version,bound_at,
                   binding_fingerprint,local_only,content_persisted
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,1,0)""",
            (
                run.run_id,
                binding.evidence_source.value,
                binding.session_id,
                binding.source_window_fingerprint,
                binding.confirmation_id,
                binding.proposal_id,
                binding.evidence_fingerprint,
                binding.evidence_schema_version,
                binding.evidence_policy_version,
                to_iso(binding.bound_at),
                _requirement_plan_binding_fingerprint(binding),
            ),
        )
        stored = (
            SqliteSessionModelEnsembleRepository._hydrate_requirement_plan_binding(
                connection,
                run.run_id,
            )
        )
        if stored != binding:
            raise DatabaseInvariantError(
                "requirement-plan binding failed exact rehydration"
            )

    @staticmethod
    def _hydrate_requirement_plan_binding(
        connection,
        run_id: str,
    ) -> SessionRequirementPlanEvidenceBinding | None:
        present = connection.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table'
                 AND name='session_model_ensemble_requirement_plan_bindings'"""
        ).fetchone()
        if present is None:
            return None
        row = connection.execute(
            """SELECT * FROM session_model_ensemble_requirement_plan_bindings
               WHERE run_id=?""",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        bound_at = from_iso(row["bound_at"])
        if bound_at is None:
            raise DatabaseInvariantError(
                "requirement-plan binding time is missing"
            )
        binding = SessionRequirementPlanEvidenceBinding(
            evidence_source=RequirementPlanEvidenceSource(row["evidence_source"]),
            session_id=row["session_id"],
            source_window_fingerprint=row["source_window_fingerprint"],
            confirmation_id=row["confirmation_id"],
            proposal_id=row["proposal_id"],
            evidence_fingerprint=row["evidence_fingerprint"],
            evidence_schema_version=row["evidence_schema_version"],
            evidence_policy_version=row["evidence_policy_version"],
            bound_at=bound_at,
            local_only=bool(row["local_only"]),
            content_persisted=bool(row["content_persisted"]),
        )
        if row["binding_fingerprint"] != _requirement_plan_binding_fingerprint(
            binding
        ):
            raise DatabaseInvariantError(
                "requirement-plan binding seal is invalid"
            )
        return binding

    def _validate_requirement_plan_binding_authority(
        self,
        connection,
        binding: SessionRequirementPlanEvidenceBinding,
        state: MetricStateV2,
    ) -> None:
        if (
            binding.evidence_source
            is not RequirementPlanEvidenceSource.REVIEWED_REQUIREMENT_PLAN
        ):
            return
        identifiers = self._identifiers
        if identifiers is None:
            raise DatabaseInvariantError(
                "reviewed requirement-plan binding requires keyed identifiers"
            )
        assert binding.proposal_id is not None
        assert binding.confirmation_id is not None
        from .requirement_plan_evidence import (
            SqliteRequirementPlanEvidenceRepository,
            confirmed_requirement_plan_snapshot,
        )

        evidence = SqliteRequirementPlanEvidenceRepository(
            self._connection_scope,
            self._ensure_initialized,
            identifiers=identifiers,
        )
        view = evidence._get_view(connection, binding.proposal_id)
        if (
            view is None
            or view.decision is None
            or view.decision.decision is not RequirementPlanDecisionKind.CONFIRM
            or view.decision.decision_id != binding.confirmation_id
            or view.proposal.session_id != binding.session_id
            or view.proposal.source_window_fingerprint
            != binding.source_window_fingerprint
        ):
            raise DatabaseInvariantError(
                "requirement-plan binding lacks its confirmed graph"
            )
        snapshot = confirmed_requirement_plan_snapshot(view)
        expected_fingerprint = requirement_plan_snapshot_fingerprint(
            snapshot,
            identifiers,
        )
        if not hmac.compare_digest(
            binding.evidence_fingerprint,
            expected_fingerprint,
        ):
            raise DatabaseInvariantError(
                "requirement-plan binding evidence fingerprint is invalid"
            )
        if reviewed_requirement_plan_denominator_is_authoritative(state):
            try:
                validate_reviewed_requirement_plan_outcomes_metric_state(
                    tuple(item.disposition for item in view.proposal.requirements),
                    state,
                )
            except ValueError as exc:
                raise DatabaseInvariantError(
                    "reviewed requirement-plan graph disagrees with metric state"
                ) from exc

    def _insert_requirement_action_binding(
        self,
        connection,
        run: SessionModelEnsembleRunRecord,
    ) -> None:
        binding = run.requirement_action_evidence_binding
        snapshot = self._validate_requirement_action_binding_authority(
            connection,
            binding,
        )
        if snapshot is not None:
            publication = run.receipt.metric_publication_v2
            if publication is None:
                raise DatabaseInvariantError(
                    "reviewed requirement-action binding has no metric publication"
                )
            state = next(
                item.state
                for item in publication.metrics
                if item.state.metric_key
                == "logic.requirement_action_traceability"
            )
            try:
                validate_reviewed_requirement_action_snapshot_metric_state(
                    snapshot,
                    state,
                )
            except ValueError as exc:
                raise DatabaseInvariantError(
                    "reviewed requirement-action graph disagrees with metric state"
                ) from exc
        existing = (
            SqliteSessionModelEnsembleRepository
            ._hydrate_requirement_action_binding(connection, run.run_id)
        )
        if binding is None:
            if existing is not None:
                raise DatabaseInvariantError(
                    "stored requirement-action binding is missing from the run"
                )
            return
        if existing is not None:
            if existing != binding:
                raise DatabaseInvariantError(
                    "requirement-action binding is immutable"
                )
            return
        connection.execute(
            """INSERT INTO session_model_ensemble_requirement_action_bindings(
                   run_id,evidence_source,session_id,
                   source_window_fingerprint,source_run_id,
                   requirement_plan_confirmation_id,
                   requirement_plan_evidence_fingerprint,
                   candidate_manifest_fingerprint,
                   reviewed_descriptor_set_fingerprint,
                   confirmation_id,proposal_id,
                   evidence_fingerprint,evidence_schema_version,
                   evidence_policy_version,bound_at,binding_fingerprint,
                   local_only,content_persisted
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,0)""",
            (
                run.run_id,
                binding.evidence_source.value,
                binding.session_id,
                binding.source_window_fingerprint,
                binding.source_run_id,
                binding.requirement_plan_confirmation_id,
                binding.requirement_plan_evidence_fingerprint,
                binding.candidate_manifest_fingerprint,
                binding.reviewed_descriptor_set_fingerprint,
                binding.confirmation_id,
                binding.proposal_id,
                binding.evidence_fingerprint,
                binding.evidence_schema_version,
                binding.evidence_policy_version,
                to_iso(binding.bound_at),
                _requirement_action_binding_fingerprint(binding),
            ),
        )
        stored = (
            SqliteSessionModelEnsembleRepository
            ._hydrate_requirement_action_binding(connection, run.run_id)
        )
        if stored != binding:
            raise DatabaseInvariantError(
                "requirement-action binding failed exact rehydration"
            )

    def _validate_requirement_action_binding_authority(
        self,
        connection,
        binding: SessionRequirementActionEvidenceBinding | None,
    ) -> RequirementActionEvidenceSnapshot | None:
        if (
            binding is None
            or binding.evidence_source
            is not RequirementActionEvidenceSource.REVIEWED_REQUIREMENT_ACTION
        ):
            return None
        identifiers = self._identifiers
        if identifiers is None:
            raise DatabaseInvariantError(
                "reviewed requirement-action binding requires keyed identifiers"
            )
        assert binding.proposal_id is not None
        assert binding.confirmation_id is not None
        from .requirement_action_evidence import (
            SqliteRequirementActionEvidenceRepository,
        )

        evidence = SqliteRequirementActionEvidenceRepository(
            self._connection_scope,
            self._ensure_initialized,
            identifiers=identifiers,
        )
        view = evidence._get_view(connection, binding.proposal_id)
        if (
            view is None
            or view.decision is None
            or view.decision.decision
            is not RequirementActionDecisionKind.CONFIRM
        ):
            raise DatabaseInvariantError(
                "requirement-action binding lacks confirmed authority"
            )
        proposal = view.proposal
        decision = view.decision
        manifest = evidence._manifest(proposal)
        if (
            binding.session_id != proposal.session_id
            or binding.source_window_fingerprint
            != proposal.source_window_fingerprint
            or binding.source_run_id != proposal.source_run_id
            or binding.requirement_plan_confirmation_id
            != proposal.requirement_plan_confirmation_id
            or binding.requirement_plan_evidence_fingerprint
            != proposal.requirement_plan_evidence_fingerprint
            or binding.candidate_manifest_fingerprint
            != proposal.candidate_manifest_fingerprint
            or binding.confirmation_id != decision.decision_id
            or binding.reviewed_descriptor_set_fingerprint
            != decision.reviewed_descriptor_set_fingerprint
            or binding.evidence_schema_version != proposal.schema_version
            or binding.evidence_policy_version != proposal.policy_version
        ):
            raise DatabaseInvariantError(
                "requirement-action binding is cross-bound"
            )
        snapshot = RequirementActionEvidenceSnapshot(
            session_id=proposal.session_id,
            source_run_id=proposal.source_run_id,
            source_window_fingerprint=proposal.source_window_fingerprint,
            requirement_plan_confirmation_id=(
                proposal.requirement_plan_confirmation_id
            ),
            requirement_plan_evidence_fingerprint=(
                proposal.requirement_plan_evidence_fingerprint
            ),
            confirmation_id=decision.decision_id,
            proposal_id=proposal.proposal_id,
            reviewed_descriptor_set_fingerprint=(
                decision.reviewed_descriptor_set_fingerprint
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
        expected_fingerprint = requirement_action_evidence_snapshot_fingerprint(
            snapshot,
            identifiers,
        )
        if not hmac.compare_digest(
            binding.evidence_fingerprint,
            expected_fingerprint,
        ):
            raise DatabaseInvariantError(
                "requirement-action binding evidence fingerprint is invalid"
            )
        return snapshot.model_copy(
            update={"evidence_fingerprint": binding.evidence_fingerprint}
        )

    def validate_requirement_action_run_authority(
        self,
        connection,
        run_id: str,
    ) -> SessionRequirementActionEvidenceBinding | None:
        """Revalidate the exact keyed r7/r8 authority graph for a run.

        Trajectory reads intentionally avoid hydrating the complete ensemble
        graph, but they must not bypass the same installation-keyed decision
        and evidence checks used by :meth:`get`.  Keep this small authority
        reader shared so every SQLite projection of an r7/r8 run fails closed on
        forged native-review claims.
        """

        binding = self._hydrate_requirement_action_binding(connection, run_id)
        snapshot = self._validate_requirement_action_binding_authority(
            connection,
            binding,
        )
        if binding is not None:
            state = self._require_r6_or_r7_metric_state(
                connection,
                run_id,
                metric_key="logic.requirement_action_traceability",
                tables=(
                    "session_model_ensemble_metric_states_v2_r7",
                    "session_model_ensemble_metric_states_v2_r8",
                ),
            )
            try:
                validate_requirement_action_binding_metric_state(binding, state)
                if snapshot is not None:
                    validate_reviewed_requirement_action_snapshot_metric_state(
                        snapshot,
                        state,
                    )
            except ValueError as exc:
                raise DatabaseInvariantError(
                    "requirement-action binding disagrees with its metric row"
                ) from exc
        return binding

    def validate_requirement_plan_run_authority(
        self,
        connection,
        run_id: str,
    ) -> SessionRequirementPlanEvidenceBinding | None:
        """Revalidate plan marker semantics for r6-r8 run and watch reads."""

        binding = self._hydrate_requirement_plan_binding(connection, run_id)
        if binding is not None:
            state = self._require_r6_or_r7_metric_state(
                connection,
                run_id,
                metric_key="logic.decomposition_coverage",
                tables=(
                    "session_model_ensemble_metric_states_v2_r6",
                    "session_model_ensemble_metric_states_v2_r7",
                    "session_model_ensemble_metric_states_v2_r8",
                ),
            )
            try:
                validate_requirement_plan_binding_metric_state(binding, state)
            except ValueError as exc:
                raise DatabaseInvariantError(
                    "requirement-plan binding disagrees with its metric row"
                ) from exc
            self._validate_requirement_plan_binding_authority(
                connection,
                binding,
                state,
            )
        return binding

    @staticmethod
    def _require_r6_or_r7_metric_state(
        connection,
        run_id: str,
        *,
        metric_key: str,
        tables: tuple[str, ...],
    ) -> MetricStateV2:
        rows = []
        for table in tables:
            present = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if present is None:
                continue
            row = connection.execute(
                f"SELECT * FROM {table} WHERE run_id=? AND metric_key=?",
                (run_id, metric_key),
            ).fetchone()
            if row is not None:
                rows.append(row)
        if len(rows) != 1:
            raise DatabaseInvariantError(
                "evidence binding requires exactly one matching metric row"
            )
        try:
            return _metric_state_v2_from_row(rows[0])
        except (TypeError, ValueError) as exc:
            raise DatabaseInvariantError("bound metric row is invalid") from exc

    @staticmethod
    def _hydrate_requirement_action_binding(
        connection,
        run_id: str,
    ) -> SessionRequirementActionEvidenceBinding | None:
        present = connection.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table'
                 AND name='session_model_ensemble_requirement_action_bindings'"""
        ).fetchone()
        if present is None:
            return None
        row = connection.execute(
            """SELECT * FROM session_model_ensemble_requirement_action_bindings
               WHERE run_id=?""",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        bound_at = from_iso(row["bound_at"])
        if bound_at is None:
            raise DatabaseInvariantError(
                "requirement-action binding time is missing"
            )
        binding = SessionRequirementActionEvidenceBinding(
            evidence_source=RequirementActionEvidenceSource(
                row["evidence_source"]
            ),
            session_id=row["session_id"],
            source_window_fingerprint=row["source_window_fingerprint"],
            source_run_id=row["source_run_id"],
            requirement_plan_confirmation_id=(
                row["requirement_plan_confirmation_id"]
            ),
            requirement_plan_evidence_fingerprint=(
                row["requirement_plan_evidence_fingerprint"]
            ),
            candidate_manifest_fingerprint=(
                row["candidate_manifest_fingerprint"]
            ),
            reviewed_descriptor_set_fingerprint=(
                row["reviewed_descriptor_set_fingerprint"]
            ),
            confirmation_id=row["confirmation_id"],
            proposal_id=row["proposal_id"],
            evidence_fingerprint=row["evidence_fingerprint"],
            evidence_schema_version=row["evidence_schema_version"],
            evidence_policy_version=row["evidence_policy_version"],
            bound_at=bound_at,
            local_only=bool(row["local_only"]),
            content_persisted=bool(row["content_persisted"]),
        )
        if row["binding_fingerprint"] != (
            _requirement_action_binding_fingerprint(binding)
        ):
            raise DatabaseInvariantError(
                "requirement-action binding seal is invalid"
            )
        return binding

    def _insert_requirement_verification_binding(
        self,
        connection,
        run: SessionModelEnsembleRunRecord,
        *,
        require_current: bool,
    ) -> None:
        binding = run.requirement_verification_evidence_binding
        publication = run.receipt.metric_publication_v2
        if binding is not None:
            if publication is None:
                raise DatabaseInvariantError(
                    "requirement-verification binding has no publication"
                )
            state = next(
                item.state
                for item in publication.metrics
                if item.state.metric_key
                == "outcome.verified_requirement_coverage"
            )
            try:
                validate_requirement_verification_binding_metric_state(
                    binding,
                    state,
                )
            except ValueError as exc:
                raise DatabaseInvariantError(
                    "requirement-verification binding disagrees with its metric row"
                ) from exc
            self._validate_requirement_verification_binding_authority(
                connection,
                binding,
                run.requirement_plan_evidence_binding,
                require_current=require_current,
            )
        existing = self._hydrate_requirement_verification_binding(
            connection,
            run.run_id,
        )
        if binding is None:
            if existing is not None:
                raise DatabaseInvariantError(
                    "stored requirement-verification binding is missing from the run"
                )
            return
        if existing is not None:
            if existing != binding:
                raise DatabaseInvariantError(
                    "requirement-verification binding is immutable"
                )
            return
        connection.execute(
            """INSERT INTO
                 session_model_ensemble_requirement_verification_bindings(
                   run_id,evidence_source,session_id,source_window_fingerprint,
                   requirement_plan_confirmation_id,
                   requirement_plan_proposal_id,
                   requirement_plan_evidence_fingerprint,
                   requirement_plan_schema_version,
                   requirement_plan_policy_version,
                   requirement_plan_review_rubric_version,
                   opportunity_count,opportunity_set_fingerprint,
                   evidence_set_fingerprint,through_revision,
                   authority_head_count,objective_result_count,
                   native_acceptance_count,resolved_opportunity_count,
                   met_requirement_count,opportunity_issuer_version,
                   result_issuer_version,acceptance_issuer_version,
                   evidence_schema_version,evidence_policy_version,
                   persistence_schema_version,evidence_projection_version,
                   objective_projection_version,binding_schema_version,
                   bound_at,binding_fingerprint,local_only,content_persisted
                 ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,0)""",
            (
                run.run_id,
                binding.evidence_source.value,
                binding.session_id,
                binding.source_window_fingerprint,
                binding.requirement_plan_confirmation_id,
                binding.requirement_plan_proposal_id,
                binding.requirement_plan_evidence_fingerprint,
                binding.requirement_plan_schema_version,
                binding.requirement_plan_policy_version,
                binding.requirement_plan_review_rubric_version,
                binding.opportunity_count,
                binding.opportunity_set_fingerprint,
                binding.evidence_set_fingerprint,
                binding.through_revision,
                binding.authority_head_count,
                binding.objective_result_count,
                binding.native_acceptance_count,
                binding.resolved_opportunity_count,
                binding.met_requirement_count,
                binding.opportunity_issuer_version,
                binding.result_issuer_version,
                binding.acceptance_issuer_version,
                binding.evidence_schema_version,
                binding.evidence_policy_version,
                binding.persistence_schema_version,
                binding.evidence_projection_version,
                binding.objective_projection_version,
                binding.binding_schema_version,
                to_iso(binding.bound_at),
                binding.binding_fingerprint,
            ),
        )
        stored = self._hydrate_requirement_verification_binding(
            connection,
            run.run_id,
        )
        if stored != binding:
            raise DatabaseInvariantError(
                "requirement-verification binding failed exact rehydration"
            )

    def _hydrate_requirement_verification_binding(
        self,
        connection,
        run_id: str,
    ) -> SessionRequirementVerificationEvidenceBinding | None:
        present = connection.execute(
            """SELECT 1 FROM sqlite_master
               WHERE type='table' AND name=
                 'session_model_ensemble_requirement_verification_bindings'"""
        ).fetchone()
        if present is None:
            return None
        row = connection.execute(
            """SELECT * FROM
                 session_model_ensemble_requirement_verification_bindings
               WHERE run_id=?""",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        identifiers = self._identifiers
        if identifiers is None:
            raise DatabaseInvariantError(
                "requirement-verification binding requires keyed identifiers"
            )
        bound_at = from_iso(row["bound_at"])
        if bound_at is None:
            raise DatabaseInvariantError(
                "requirement-verification binding time is missing"
            )
        try:
            binding = SessionRequirementVerificationEvidenceBinding(
                evidence_source=RequirementVerificationEvidenceSource(
                    row["evidence_source"]
                ),
                session_id=row["session_id"],
                source_window_fingerprint=row["source_window_fingerprint"],
                requirement_plan_confirmation_id=(
                    row["requirement_plan_confirmation_id"]
                ),
                requirement_plan_proposal_id=(
                    row["requirement_plan_proposal_id"]
                ),
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
                opportunity_count=row["opportunity_count"],
                opportunity_set_fingerprint=row["opportunity_set_fingerprint"],
                evidence_set_fingerprint=row["evidence_set_fingerprint"],
                through_revision=row["through_revision"],
                authority_head_count=row["authority_head_count"],
                objective_result_count=row["objective_result_count"],
                native_acceptance_count=row["native_acceptance_count"],
                resolved_opportunity_count=row["resolved_opportunity_count"],
                met_requirement_count=row["met_requirement_count"],
                opportunity_issuer_version=row["opportunity_issuer_version"],
                result_issuer_version=row["result_issuer_version"],
                acceptance_issuer_version=row["acceptance_issuer_version"],
                evidence_schema_version=row["evidence_schema_version"],
                evidence_policy_version=row["evidence_policy_version"],
                persistence_schema_version=row["persistence_schema_version"],
                evidence_projection_version=row["evidence_projection_version"],
                objective_projection_version=row["objective_projection_version"],
                binding_schema_version=row["binding_schema_version"],
                binding_fingerprint=row["binding_fingerprint"],
                bound_at=bound_at,
                local_only=bool(row["local_only"]),
                content_persisted=bool(row["content_persisted"]),
            )
        except (TypeError, ValueError) as exc:
            raise DatabaseInvariantError(
                "requirement-verification binding is malformed"
            ) from exc
        expected_fingerprint = _requirement_verification_binding_fingerprint(
            binding,
            identifiers,
        )
        if not hmac.compare_digest(
            binding.binding_fingerprint,
            expected_fingerprint,
        ):
            raise DatabaseInvariantError(
                "requirement-verification binding seal is invalid"
            )
        return binding

    def _validate_requirement_verification_binding_authority(
        self,
        connection,
        binding: SessionRequirementVerificationEvidenceBinding,
        plan_binding: SessionRequirementPlanEvidenceBinding | None,
        *,
        require_current: bool,
    ) -> None:
        identifiers = self._identifiers
        if identifiers is None:
            raise DatabaseInvariantError(
                "requirement-verification binding requires keyed identifiers"
            )
        if not hmac.compare_digest(
            binding.binding_fingerprint,
            _requirement_verification_binding_fingerprint(
                binding,
                identifiers,
            ),
        ):
            raise DatabaseInvariantError(
                "requirement-verification binding fingerprint is invalid"
            )
        if binding.evidence_source is RequirementVerificationEvidenceSource.UNAVAILABLE:
            # A deliberately uncomposed verification reader may coexist with an
            # exact reviewed-r6 denominator. The unavailable binding carries no
            # r6 identity of its own; the enclosing run still cross-binds both
            # content-free authorities to the same session and source window.
            return
        if (
            plan_binding is None
            or plan_binding.evidence_source
            is not RequirementPlanEvidenceSource.REVIEWED_REQUIREMENT_PLAN
            or plan_binding.confirmation_id
            != binding.requirement_plan_confirmation_id
            or plan_binding.proposal_id
            != binding.requirement_plan_proposal_id
            or plan_binding.evidence_fingerprint
            != binding.requirement_plan_evidence_fingerprint
            or plan_binding.evidence_schema_version
            != binding.requirement_plan_schema_version
            or plan_binding.evidence_policy_version
            != binding.requirement_plan_policy_version
            or plan_binding.session_id != binding.session_id
            or plan_binding.source_window_fingerprint
            != binding.source_window_fingerprint
        ):
            raise DatabaseInvariantError(
                "requirement-verification binding is cross-bound"
            )
        assert binding.requirement_plan_proposal_id is not None
        from .requirement_plan_evidence import (
            SqliteRequirementPlanEvidenceRepository,
            confirmed_requirement_plan_snapshot,
        )

        plan_repository = SqliteRequirementPlanEvidenceRepository(
            self._connection_scope,
            self._ensure_initialized,
            identifiers=identifiers,
        )
        view = plan_repository._get_view(
            connection,
            binding.requirement_plan_proposal_id,
        )
        if (
            view is None
            or view.decision is None
            or view.decision.decision is not RequirementPlanDecisionKind.CONFIRM
            or view.decision.decision_id
            != binding.requirement_plan_confirmation_id
        ):
            raise DatabaseInvariantError(
                "requirement-verification r6 authority is incomplete"
            )
        plan_snapshot = confirmed_requirement_plan_snapshot(view)
        try:
            opportunities = issue_requirement_verification_opportunities(
                plan_snapshot,
                identifiers,
            )
        except (TypeError, ValueError) as exc:
            raise DatabaseInvariantError(
                "requirement-verification opportunities are invalid"
            ) from exc
        if (
            opportunities.session_id != binding.session_id
            or opportunities.source_window_fingerprint
            != binding.source_window_fingerprint
            or opportunities.requirement_plan_confirmation_id
            != binding.requirement_plan_confirmation_id
            or opportunities.requirement_plan_proposal_id
            != binding.requirement_plan_proposal_id
            or opportunities.requirement_plan_evidence_fingerprint
            != binding.requirement_plan_evidence_fingerprint
            or opportunities.requirement_plan_schema_version
            != binding.requirement_plan_schema_version
            or opportunities.requirement_plan_policy_version
            != binding.requirement_plan_policy_version
            or opportunities.requirement_plan_review_rubric_version
            != binding.requirement_plan_review_rubric_version
            or opportunities.issuer_version != binding.opportunity_issuer_version
            or opportunities.evidence_schema_version
            != binding.evidence_schema_version
            or opportunities.evidence_policy_version
            != binding.evidence_policy_version
            or len(opportunities.opportunities) != binding.opportunity_count
            or opportunities.opportunity_set_fingerprint
            != binding.opportunity_set_fingerprint
        ):
            raise DatabaseInvariantError(
                "requirement-verification opportunity binding is invalid"
            )
        from .requirement_verification_evidence import (
            SqliteRequirementVerificationEvidenceRepository,
        )

        evidence_repository = SqliteRequirementVerificationEvidenceRepository(
            self._connection_scope,
            self._ensure_initialized,
            identifiers=identifiers,
        )
        if binding.evidence_source in {
            RequirementVerificationEvidenceSource.OPPORTUNITY_BOUND_EXCEEDED,
            RequirementVerificationEvidenceSource.AWAITING_EVIDENCE,
        }:
            if (
                require_current
                and evidence_repository._snapshot_for_requirement_plan_tx(
                    connection,
                    binding.session_id,
                    binding.requirement_plan_confirmation_id,
                )
                is not None
            ):
                raise DatabaseInvariantError(
                    "verification marker conflicts with persisted evidence"
                )
            return
        assert binding.opportunity_set_fingerprint is not None
        assert binding.through_revision is not None
        snapshot = evidence_repository._snapshot_for_binding_tx(
            connection,
            binding.session_id,
            binding.opportunity_set_fingerprint,
            through_revision=binding.through_revision,
            require_current=require_current,
        )
        if snapshot is None:
            raise DatabaseInvariantError(
                "persisted verification binding lost its M58 authority"
            )
        evidence = snapshot.evidence
        results = evidence.verification_results
        acceptances = evidence.acceptance_authorities
        resolved_result_count = sum(
            item.outcome
            in {RequirementVerificationOutcome.PASSED,
                RequirementVerificationOutcome.FAILED}
            for item in results
        )
        resolved_acceptance_count = sum(
            item.outcome
            in {RequirementAcceptanceOutcome.ACCEPTED,
                RequirementAcceptanceOutcome.REJECTED}
            for item in acceptances
        )
        met_count = sum(
            item.outcome is RequirementVerificationOutcome.PASSED
            for item in results
        ) + sum(
            item.outcome is RequirementAcceptanceOutcome.ACCEPTED
            for item in acceptances
        )
        if (
            evidence.opportunities != opportunities
            or evidence.evidence_set_fingerprint
            != binding.evidence_set_fingerprint
            or evidence.projection_version
            != binding.evidence_projection_version
            or evidence.evidence_schema_version
            != binding.evidence_schema_version
            or evidence.evidence_policy_version
            != binding.evidence_policy_version
            or snapshot.persistence_schema_version
            != binding.persistence_schema_version
            or snapshot.revision != binding.through_revision
            or len(snapshot.authority_heads) != binding.authority_head_count
            or len(results) != binding.objective_result_count
            or len(acceptances) != binding.native_acceptance_count
            or resolved_result_count + resolved_acceptance_count
            != binding.resolved_opportunity_count
            or met_count != binding.met_requirement_count
        ):
            raise DatabaseInvariantError(
                "persisted verification binding is not exact"
            )

    def validate_requirement_verification_run_authority(
        self,
        connection,
        run_id: str,
    ) -> SessionRequirementVerificationEvidenceBinding | None:
        binding = self._hydrate_requirement_verification_binding(
            connection,
            run_id,
        )
        if binding is None:
            return None
        plan_binding = self._hydrate_requirement_plan_binding(
            connection,
            run_id,
        )
        self._validate_requirement_verification_binding_authority(
            connection,
            binding,
            plan_binding,
            require_current=False,
        )
        state = self._require_r6_or_r7_metric_state(
            connection,
            run_id,
            metric_key="outcome.verified_requirement_coverage",
            tables=("session_model_ensemble_metric_states_v2_r8",),
        )
        try:
            validate_requirement_verification_binding_metric_state(
                binding,
                state,
            )
        except ValueError as exc:
            raise DatabaseInvariantError(
                "requirement-verification binding disagrees with its metric row"
            ) from exc
        return binding

    @staticmethod
    def _insert_metric_projection(connection, run: SessionModelEnsembleRunRecord) -> None:
        receipt = run.receipt
        try:
            validate_r8_typed_metric_projection(receipt)
        except ValueError as exc:
            raise DatabaseInvariantError(
                "r8 typed metric projection is incomplete or stale"
            ) from exc
        if not receipt.typed_metrics:
            return
        if (
            receipt.metric_projection_version
            != MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION
            or receipt.metric_projection_completed_at is None
        ):
            raise DatabaseInvariantError("typed metric projection identity is incomplete")
        connection.executemany(
            """
            INSERT INTO session_model_ensemble_typed_metrics(
                run_id,projection_version,metric_key,metric_version,value_state,
                numerator,denominator,numeric_value,observed_message_count,
                eligible_message_count,coverage,explanation_code,error_code,
                projection_source,metric_schema_version,engine_version,
                algorithm_id,algorithm_version,rubric_version,
                calibration_state,product_metric_eligible
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'deterministic_typed_contract',
                     ?,?,?,?,?,'not_assessed',0)
            """,
            (
                (
                    run.run_id,
                    receipt.metric_projection_version,
                    item.metric_key,
                    item.metric_version,
                    item.value_state.value,
                    item.numerator,
                    item.denominator,
                    item.numeric_value,
                    item.observed_message_count,
                    item.eligible_message_count,
                    item.coverage,
                    item.explanation_code,
                    item.error_code,
                    item.metric_schema_version,
                    item.engine_version,
                    item.algorithm_id,
                    item.algorithm_version,
                    item.rubric_version,
                )
                for item in receipt.typed_metrics
            ),
        )
        connection.execute(
            """INSERT INTO session_model_ensemble_typed_metric_seals(
                   run_id,projection_version,metric_count,projection_fingerprint,
                   projected_at
               ) VALUES(?,?,?,?,?)""",
            (
                run.run_id,
                receipt.metric_projection_version,
                len(receipt.typed_metrics),
                _metric_projection_fingerprint(receipt),
                to_iso(receipt.metric_projection_completed_at),
            ),
        )

    @staticmethod
    def _insert_predictive_projection(
        connection, run: SessionModelEnsembleRunRecord
    ) -> None:
        projection = run.receipt.predictive_projection
        if projection is None:
            return
        connection.executemany(
            """
            INSERT INTO session_model_ensemble_predictive_metrics(
                run_id,projection_version,metric_key,target,state,
                mean,median,q05,q25,q75,q95,applicability_probability,
                pending_probability,model_disagreement,effective_observation_count,
                model_set_version,calibration_version,contract_version,
                contract_fingerprint,factor_count,density_bin_count,
                product_metric_eligible
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)
            """,
            (
                (
                    run.run_id,
                    projection.projection_version,
                    item.metric_key,
                    item.target.value,
                    item.state.value,
                    item.mean,
                    item.median,
                    item.q05,
                    item.q25,
                    item.q75,
                    item.q95,
                    item.applicability_probability,
                    item.pending_probability,
                    item.model_disagreement,
                    item.effective_observation_count,
                    item.model_set_version,
                    item.calibration_version,
                    item.contract_version,
                    item.contract_fingerprint,
                    len(item.factors),
                    len(item.density_bins),
                )
                for item in projection.metrics
            ),
        )
        connection.executemany(
            """
            INSERT INTO session_model_ensemble_predictive_factors(
                run_id,projection_version,metric_key,factor_ordinal,
                factor_key,scale,weight,applicability_probability,
                present_probability,neutral_probability,absent_probability,
                expert_count,critical
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                (
                    run.run_id,
                    projection.projection_version,
                    metric.metric_key,
                    ordinal,
                    factor.factor_key,
                    factor.scale.value,
                    factor.weight,
                    factor.applicability_probability,
                    factor.present_probability,
                    factor.neutral_probability,
                    factor.absent_probability,
                    factor.expert_count,
                    int(factor.critical),
                )
                for metric in projection.metrics
                for ordinal, factor in enumerate(metric.factors)
            ),
        )
        connection.executemany(
            """
            INSERT INTO session_model_ensemble_predictive_density_bins(
                run_id,projection_version,metric_key,bin_ordinal,probability_mass
            ) VALUES(?,?,?,?,?)
            """,
            (
                (
                    run.run_id,
                    projection.projection_version,
                    metric.metric_key,
                    ordinal,
                    probability,
                )
                for metric in projection.metrics
                for ordinal, probability in enumerate(metric.density_bins)
            ),
        )
        connection.executemany(
            """
            INSERT INTO session_model_ensemble_predictive_model_stages(
                run_id,projection_version,stage_ordinal,model_key,repository_id,
                revision,status,error_code,device,quantization,
                inference_latency_ms,peak_accelerator_memory_mb,process_rss_mb,
                unloaded_after_stage
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1)
            """,
            (
                (
                    run.run_id,
                    projection.projection_version,
                    ordinal,
                    item.model_key,
                    item.repository_id,
                    item.revision,
                    item.status,
                    item.error_code,
                    item.device,
                    item.quantization,
                    item.inference_latency_ms,
                    item.peak_accelerator_memory_mb,
                    item.process_rss_mb,
                )
                for ordinal, item in enumerate(projection.model_stages)
            ),
        )
        factor_count = sum(len(item.factors) for item in projection.metrics)
        density_count = sum(len(item.density_bins) for item in projection.metrics)
        connection.execute(
            """
            INSERT INTO session_model_ensemble_predictive_metric_seals(
                run_id,projection_version,registry_version,model_set_version,
                metric_count,factor_count,density_bin_count,stage_count,
                sample_count,projection_fingerprint,projected_at,local_only,
                content_persisted,calibrated_as_truth
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,1,0,0)
            """,
            (
                run.run_id,
                projection.projection_version,
                projection.contract_registry_version,
                projection.model_set_version,
                len(projection.metrics),
                factor_count,
                density_count,
                len(projection.model_stages),
                projection.sample_count,
                _predictive_projection_fingerprint(projection),
                to_iso(projection.projected_at),
            ),
        )

    @staticmethod
    def _insert_metric_publication_v2(
        connection,
        run: SessionModelEnsembleRunRecord,
    ) -> None:
        publication = run.receipt.metric_publication_v2
        if publication is None:
            return
        if (
            publication.source is not MetricPublicationSource.LIVE_PROJECTION
            or publication.compatibility_preview
            or not publication.canonical_live_snapshot
            or publication.model_stage_consumed
        ):
            raise DatabaseInvariantError(
                "metric V2 sidecar must be a canonical live measured publication"
            )
        # Historical r1-r5 rows are read-only.  R6 remains writable only as
        # the bootstrap source for the reviewed action workflow; r7 adds the
        # exact requirement-action authority without reinterpreting r6 rows.
        binding = run.metric_profile_binding
        evidence_binding = run.requirement_plan_evidence_binding
        action_binding = run.requirement_action_evidence_binding
        verification_binding = run.requirement_verification_evidence_binding
        if (
            publication.projection_version
            not in {
                METRIC_PROJECTION_V2_VERSION_6,
                METRIC_PROJECTION_V2_VERSION_7,
                METRIC_PROJECTION_V2_VERSION_8,
            }
            or binding is None
            or evidence_binding is None
            or (
                publication.projection_version
                in {
                    METRIC_PROJECTION_V2_VERSION_7,
                    METRIC_PROJECTION_V2_VERSION_8,
                }
            )
            != (action_binding is not None)
            or (
                publication.projection_version
                == METRIC_PROJECTION_V2_VERSION_8
            )
            != (verification_binding is not None)
        ):
            raise DatabaseInvariantError(
                "new metric V2 publications require the current projection identity"
            )
        states_table, seals_table = _metric_v2_tables(
            publication.projection_version
        )
        connection.executemany(
            f"""
            INSERT INTO {states_table}(
                run_id,metric_ordinal,registry_version,projection_version,
                metric_key,contract_version,contract_fingerprint,
                evidence_authority,value_state,explanation_code,numerator,
                denominator,numeric_value,censoring_lower_bound,
                censoring_upper_bound,denominator_basis,opportunity_unit_kind,
                capability_available,source_complete,eligible_count,met_count,
                not_met_count,pending_count,unknown_count,
                superseded_excluded_count,distinct_owner_count,
                product_metric_eligible
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)
            """,
            (
                (
                    run.run_id,
                    ordinal,
                    publication.registry_version,
                    publication.projection_version,
                    item.state.metric_key,
                    item.state.contract_version,
                    item.state.contract_fingerprint,
                    item.state.evidence_authority.value,
                    item.state.value_state.value,
                    item.state.explanation_code,
                    item.state.numerator,
                    item.state.denominator,
                    item.state.numeric_value,
                    item.state.censoring_lower_bound,
                    item.state.censoring_upper_bound,
                    item.state.statistics.denominator_basis.value,
                    (
                        None
                        if item.state.statistics.opportunity_unit_kind is None
                        else item.state.statistics.opportunity_unit_kind.value
                    ),
                    int(item.state.statistics.capability_available),
                    int(item.state.statistics.source_complete),
                    item.state.statistics.eligible_count,
                    item.state.statistics.met_count,
                    item.state.statistics.not_met_count,
                    item.state.statistics.pending_count,
                    item.state.statistics.unknown_count,
                    item.state.statistics.superseded_excluded_count,
                    item.state.statistics.distinct_owner_count,
                )
                for ordinal, item in enumerate(publication.metrics)
            ),
        )
        projected_at = (
            run.receipt.metric_projection_completed_at
            or run.receipt.completed_at
        )
        if action_binding is not None:
            seal_columns = (
                "run_id",
                "publication_key",
                "publication_version",
                "registry_version",
                "contract_set_fingerprint",
                "projection_version",
                "guidance_contract_version",
                "guidance_template_catalog_version",
                "source",
                "canonical_live_snapshot",
                "model_stage_consumed",
                "compatibility_preview",
                "metric_count",
                "known_count",
                "pending_count",
                "unknown_count",
                "not_applicable_count",
                "abstained_count",
                "execution_error_count",
                "objective_measured_count",
                "projection_fingerprint",
                "profile_source",
                "profile_id",
                "profile_revision",
                "profile_fingerprint",
                "profile_schema_version",
                "profile_policy_version",
                "profile_binding_fingerprint",
                "publication_profile_fingerprint",
                "requirement_plan_source",
                "requirement_plan_confirmation_id",
                "requirement_plan_proposal_id",
                "requirement_plan_evidence_fingerprint",
                "requirement_plan_schema_version",
                "requirement_plan_policy_version",
                "requirement_plan_binding_fingerprint",
                "publication_requirement_plan_fingerprint",
                "requirement_action_source",
                "requirement_action_source_run_id",
                "requirement_action_requirement_plan_confirmation_id",
                "requirement_action_requirement_plan_evidence_fingerprint",
                "requirement_action_candidate_manifest_fingerprint",
                "requirement_action_reviewed_descriptor_set_fingerprint",
                "requirement_action_confirmation_id",
                "requirement_action_proposal_id",
                "requirement_action_evidence_fingerprint",
                "requirement_action_schema_version",
                "requirement_action_policy_version",
                "requirement_action_binding_fingerprint",
                "publication_requirement_action_fingerprint",
                "projected_at",
                "local_only",
                "content_persisted",
                "product_metric_eligible",
            )
            seal_values = (
                run.run_id,
                publication.publication_key,
                publication.publication_version,
                publication.registry_version,
                publication.contract_set_fingerprint,
                publication.projection_version,
                publication.guidance_contract_version,
                publication.guidance_template_catalog_version,
                publication.source.value,
                1,
                0,
                0,
                len(publication.metrics),
                publication.known_count,
                publication.pending_count,
                publication.unknown_count,
                publication.not_applicable_count,
                publication.abstained_count,
                publication.execution_error_count,
                publication.objective_measured_count,
                _metric_publication_v2_fingerprint(publication),
                binding.profile_source.value,
                binding.profile_id,
                binding.profile_revision,
                binding.profile_fingerprint,
                binding.profile_schema_version,
                binding.profile_policy_version,
                _metric_profile_binding_fingerprint(binding),
                _metric_publication_profile_fingerprint(publication, binding),
                evidence_binding.evidence_source.value,
                evidence_binding.confirmation_id,
                evidence_binding.proposal_id,
                evidence_binding.evidence_fingerprint,
                evidence_binding.evidence_schema_version,
                evidence_binding.evidence_policy_version,
                _requirement_plan_binding_fingerprint(evidence_binding),
                _metric_publication_requirement_plan_fingerprint(
                    publication,
                    evidence_binding,
                ),
                action_binding.evidence_source.value,
                action_binding.source_run_id,
                action_binding.requirement_plan_confirmation_id,
                action_binding.requirement_plan_evidence_fingerprint,
                action_binding.candidate_manifest_fingerprint,
                action_binding.reviewed_descriptor_set_fingerprint,
                action_binding.confirmation_id,
                action_binding.proposal_id,
                action_binding.evidence_fingerprint,
                action_binding.evidence_schema_version,
                action_binding.evidence_policy_version,
                _requirement_action_binding_fingerprint(action_binding),
                _metric_publication_requirement_action_fingerprint(
                    publication,
                    action_binding,
                ),
                to_iso(projected_at),
                1,
                0,
                0,
            )
            if verification_binding is not None:
                seal_columns += (
                    "requirement_verification_source",
                    "requirement_verification_requirement_plan_confirmation_id",
                    "requirement_verification_requirement_plan_proposal_id",
                    "requirement_verification_requirement_plan_evidence_fingerprint",
                    "requirement_verification_requirement_plan_schema_version",
                    "requirement_verification_requirement_plan_policy_version",
                    "requirement_verification_requirement_plan_review_rubric_version",
                    "requirement_verification_opportunity_count",
                    "requirement_verification_opportunity_set_fingerprint",
                    "requirement_verification_evidence_set_fingerprint",
                    "requirement_verification_through_revision",
                    "requirement_verification_authority_head_count",
                    "requirement_verification_objective_result_count",
                    "requirement_verification_native_acceptance_count",
                    "requirement_verification_resolved_opportunity_count",
                    "requirement_verification_met_requirement_count",
                    "requirement_verification_opportunity_issuer_version",
                    "requirement_verification_result_issuer_version",
                    "requirement_verification_acceptance_issuer_version",
                    "requirement_verification_evidence_schema_version",
                    "requirement_verification_evidence_policy_version",
                    "requirement_verification_persistence_schema_version",
                    "requirement_verification_evidence_projection_version",
                    "requirement_verification_objective_projection_version",
                    "requirement_verification_binding_schema_version",
                    "requirement_verification_binding_fingerprint",
                    "publication_requirement_verification_fingerprint",
                )
                seal_values += (
                    verification_binding.evidence_source.value,
                    verification_binding.requirement_plan_confirmation_id,
                    verification_binding.requirement_plan_proposal_id,
                    verification_binding.requirement_plan_evidence_fingerprint,
                    verification_binding.requirement_plan_schema_version,
                    verification_binding.requirement_plan_policy_version,
                    verification_binding.requirement_plan_review_rubric_version,
                    verification_binding.opportunity_count,
                    verification_binding.opportunity_set_fingerprint,
                    verification_binding.evidence_set_fingerprint,
                    verification_binding.through_revision,
                    verification_binding.authority_head_count,
                    verification_binding.objective_result_count,
                    verification_binding.native_acceptance_count,
                    verification_binding.resolved_opportunity_count,
                    verification_binding.met_requirement_count,
                    verification_binding.opportunity_issuer_version,
                    verification_binding.result_issuer_version,
                    verification_binding.acceptance_issuer_version,
                    verification_binding.evidence_schema_version,
                    verification_binding.evidence_policy_version,
                    verification_binding.persistence_schema_version,
                    verification_binding.evidence_projection_version,
                    verification_binding.objective_projection_version,
                    verification_binding.binding_schema_version,
                    verification_binding.binding_fingerprint,
                    _metric_publication_requirement_verification_fingerprint(
                        publication,
                        verification_binding,
                    ),
                )
            placeholders = ",".join("?" for _ in seal_values)
            connection.execute(
                f"INSERT INTO {seals_table}({','.join(seal_columns)}) "
                f"VALUES({placeholders})",
                seal_values,
            )
            return
        connection.execute(
            f"""
            INSERT INTO {seals_table}(
                run_id,publication_key,publication_version,registry_version,
                contract_set_fingerprint,projection_version,
                guidance_contract_version,guidance_template_catalog_version,
                source,canonical_live_snapshot,model_stage_consumed,
                compatibility_preview,metric_count,known_count,pending_count,
                unknown_count,not_applicable_count,abstained_count,
                execution_error_count,objective_measured_count,
                projection_fingerprint,profile_source,profile_id,
                profile_revision,profile_fingerprint,profile_schema_version,
                profile_policy_version,profile_binding_fingerprint,
                publication_profile_fingerprint,requirement_plan_source,
                requirement_plan_confirmation_id,requirement_plan_proposal_id,
                requirement_plan_evidence_fingerprint,
                requirement_plan_schema_version,requirement_plan_policy_version,
                requirement_plan_binding_fingerprint,
                publication_requirement_plan_fingerprint,
                projected_at,local_only,
                content_persisted,product_metric_eligible
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run.run_id,
                publication.publication_key,
                publication.publication_version,
                publication.registry_version,
                publication.contract_set_fingerprint,
                publication.projection_version,
                publication.guidance_contract_version,
                publication.guidance_template_catalog_version,
                publication.source.value,
                1,
                0,
                0,
                len(publication.metrics),
                publication.known_count,
                publication.pending_count,
                publication.unknown_count,
                publication.not_applicable_count,
                publication.abstained_count,
                publication.execution_error_count,
                publication.objective_measured_count,
                _metric_publication_v2_fingerprint(publication),
                binding.profile_source.value,
                binding.profile_id,
                binding.profile_revision,
                binding.profile_fingerprint,
                binding.profile_schema_version,
                binding.profile_policy_version,
                _metric_profile_binding_fingerprint(binding),
                _metric_publication_profile_fingerprint(publication, binding),
                evidence_binding.evidence_source.value,
                evidence_binding.confirmation_id,
                evidence_binding.proposal_id,
                evidence_binding.evidence_fingerprint,
                evidence_binding.evidence_schema_version,
                evidence_binding.evidence_policy_version,
                _requirement_plan_binding_fingerprint(evidence_binding),
                _metric_publication_requirement_plan_fingerprint(
                    publication,
                    evidence_binding,
                ),
                to_iso(projected_at),
                1,
                0,
                0,
            ),
        )

    @staticmethod
    def _insert_semantic_unit_reconciliation(
        connection,
        run: SessionModelEnsembleRunRecord,
        reconciliation: SemanticUnitReconciliation | None,
    ) -> None:
        if reconciliation is None:
            return
        if (
            reconciliation.schema_version != SEMANTIC_UNIT_SCHEMA_VERSION
            or reconciliation.contract_version != SEMANTIC_UNIT_CONTRACT_VERSION
            or reconciliation.provider is not run.provider
            or reconciliation.session_id != run.session_id
            or reconciliation.analysis_window_fingerprint != run.input_fingerprint
        ):
            raise DatabaseInvariantError(
                "semantic-unit sidecar does not match the ensemble run"
            )
        appended_ids = {item.receipt_id for item in reconciliation.appended}
        connection.executemany(
            """
            INSERT INTO session_model_ensemble_semantic_unit_heads(
                run_id,unit_ordinal,schema_version,contract_version,
                unit_kind_version,receipt_id,unit_id,unit_digest,revision,
                previous_receipt_id,kind,lifecycle,extraction_basis,
                owner_source_digest,source_version_digest,source_count,
                first_sequence,closed_at_sequence,
                superseded_by_source_digest,superseded_by_unit_id,
                owner_role,owner_message_kind,rework_class,disposition
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                (
                    run.run_id,
                    ordinal,
                    item.schema_version,
                    item.contract_version,
                    item.unit_kind_version,
                    item.receipt_id,
                    item.unit_id,
                    item.unit_digest,
                    item.revision,
                    item.previous_receipt_id,
                    item.kind.value,
                    item.lifecycle.value,
                    item.extraction_basis.value,
                    item.owner_source_digest,
                    item.source_version_digest,
                    len(item.source_digests),
                    item.first_sequence,
                    item.closed_at_sequence,
                    item.superseded_by_source_digest,
                    item.superseded_by_unit_id,
                    None if item.owner_role is None else item.owner_role.value,
                    (
                        None
                        if item.owner_message_kind is None
                        else item.owner_message_kind.value
                    ),
                    None if item.rework_class is None else item.rework_class.value,
                    "appended" if item.receipt_id in appended_ids else "unchanged",
                )
                for ordinal, item in enumerate(reconciliation.heads)
            ),
        )
        connection.executemany(
            """
            INSERT INTO session_model_ensemble_semantic_unit_sources(
                run_id,unit_id,source_ordinal,source_digest
            ) VALUES(?,?,?,?)
            """,
            (
                (run.run_id, item.unit_id, ordinal, source_digest)
                for item in reconciliation.heads
                for ordinal, source_digest in enumerate(item.source_digests)
            ),
        )
        connection.execute(
            """
            INSERT INTO session_model_ensemble_semantic_unit_seals(
                run_id,schema_version,contract_version,reconciliation_id,
                analysis_window_fingerprint,source_complete,head_count,
                appended_count,unchanged_count,retained_unobserved_unit_count,
                reconciliation_fingerprint,sealed_at,local_only,content_persisted
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,0)
            """,
            (
                run.run_id,
                reconciliation.schema_version,
                reconciliation.contract_version,
                reconciliation.reconciliation_id,
                reconciliation.analysis_window_fingerprint,
                int(reconciliation.source_complete),
                len(reconciliation.heads),
                len(reconciliation.appended),
                len(reconciliation.unchanged_receipt_ids),
                reconciliation.retained_unobserved_unit_count,
                _semantic_unit_reconciliation_fingerprint(reconciliation),
                to_iso(run.receipt.completed_at),
            ),
        )

    def get(self, run_id: str) -> SessionModelEnsembleRunRecord | None:
        # Hydrating one run reads the seal, the metrics, the typed and
        # predictive sidecars, the semantic-unit sidecar, and whichever V2
        # projection sidecar the run carries.  Outside a transaction those are
        # separate read snapshots, so a privacy deletion committing between
        # them could return a head whose children were already erased.  A
        # deferred read transaction pins all of them to one snapshot;
        # ``query_only`` is on for this scope, so no writer lock is taken and a
        # concurrent writer is never blocked.
        self._ensure_initialized()
        require_safe_id(run_id)
        with self._connection_scope(readonly=True) as connection:
            try:
                connection.execute("BEGIN")
                record = self._hydrate(connection, run_id)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return record

    def get_latest(self, session_id: str) -> SessionModelEnsembleRunRecord | None:
        self._ensure_initialized()
        require_safe_id(session_id)
        with self._connection_scope(readonly=True) as connection:
            try:
                connection.execute("BEGIN")
                row = connection.execute(
                    """SELECT r.run_id FROM session_model_ensemble_runs r
                       JOIN session_model_ensemble_seals s ON s.run_id=r.run_id
                       WHERE r.session_id=?
                       ORDER BY r.completed_at DESC,r.run_id DESC LIMIT 1""",
                    (session_id,),
                ).fetchone()
                record = (
                    None if row is None else self._hydrate(connection, row["run_id"])
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return record

    def get_semantic_unit_reconciliation(
        self,
        run_id: str,
    ) -> SemanticUnitReconciliation | None:
        """Read the immutable semantic-unit sidecar for one run, if present."""

        self._ensure_initialized()
        require_safe_id(run_id)
        with self._connection_scope(readonly=True) as connection:
            try:
                connection.execute("BEGIN")
                reconciliation = self._hydrate_semantic_units(connection, run_id)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return reconciliation

    def delete_for_privacy(self, run_id: str) -> bool:
        self._ensure_initialized()
        require_safe_id(run_id)
        with self._connection_scope() as connection:
            try:
                connection.execute("PRAGMA secure_delete=ON")
                connection.execute("BEGIN IMMEDIATE")
                target = connection.execute(
                    "SELECT session_id FROM session_model_ensemble_runs WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                if target is None:
                    connection.rollback()
                    return False
                privacy_stamp = to_iso(datetime.now(UTC))
                # Privacy removal is session-wide for shadow-model derivatives.
                # Disable and revoke the standing watch before erasing the
                # graph.  A watch-owned save validates this lease in the same
                # BEGIN IMMEDIATE transaction, so an in-flight generation can
                # neither recreate nor publish decisions derived from the
                # erased receipt.  Erasing all ensemble runs for the selected
                # session also closes the opposite transaction ordering, where
                # an in-flight descendant committed immediately before this
                # privacy transaction acquired the writer lock.
                running_attempt_ids = tuple(
                    row["attempt_id"]
                    for row in connection.execute(
                        """SELECT attempt.attempt_id
                           FROM session_model_ensemble_analysis_attempts attempt
                           JOIN session_model_ensemble_watches watch
                             ON watch.watch_id=attempt.watch_id
                           WHERE watch.session_id=? AND attempt.state='running'""",
                        (target["session_id"],),
                    ).fetchall()
                )
                if running_attempt_ids:
                    placeholders = ",".join("?" for _ in running_attempt_ids)
                    connection.execute(
                        """UPDATE session_model_ensemble_analysis_attempts
                           SET state='cancelled',error_code='privacy_deleted',
                               completed_at=?
                           WHERE attempt_id IN ("""
                        + placeholders
                        + ") AND state='running'",
                        (privacy_stamp, *running_attempt_ids),
                    )
                    connection.execute(
                        """INSERT INTO session_model_ensemble_analysis_attempt_seals(
                               attempt_id,contract_version,stage_count,warning_count,
                               sealed_at,local_only,content_persisted
                           )
                           SELECT attempt_id,'model-ensemble-attempt-stage-seal-v1',
                                  stage_count,warning_count,completed_at,1,0
                           FROM session_model_ensemble_analysis_attempts
                           WHERE attempt_id IN ("""
                        + placeholders
                        + ")",
                        running_attempt_ids,
                    )
                connection.execute(
                    """UPDATE session_model_ensemble_watches
                       SET state='disabled',latest_run_id=NULL,
                           latest_input_fingerprint=NULL,
                           last_error_code='privacy_deleted',
                           lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                           updated_at=?
                       WHERE session_id=?""",
                    (privacy_stamp, target["session_id"]),
                )
                deleted = connection.execute(
                    "DELETE FROM session_model_ensemble_runs WHERE session_id=?",
                    (target["session_id"],),
                ).rowcount
                connection.commit()
                checkpoint = connection.execute(
                    "PRAGMA wal_checkpoint(TRUNCATE)"
                ).fetchone()
                if checkpoint is None or tuple(int(value) for value in checkpoint) != (
                    0,
                    0,
                    0,
                ):
                    raise DatabaseInvariantError(
                        "model ensemble privacy deletion committed; WAL purge pending"
                    )
                return bool(deleted)
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _hydrate_semantic_units(
        connection,
        run_id: str,
    ) -> SemanticUnitReconciliation | None:
        seal = connection.execute(
            """SELECT seal.*,run.session_id,run.provider
               FROM session_model_ensemble_semantic_unit_seals seal
               JOIN session_model_ensemble_runs run ON run.run_id=seal.run_id
               WHERE seal.run_id=?""",
            (run_id,),
        ).fetchone()
        if seal is None:
            return None
        rows = connection.execute(
            """SELECT * FROM session_model_ensemble_semantic_unit_heads
               WHERE run_id=? ORDER BY unit_ordinal""",
            (run_id,),
        ).fetchall()
        heads: list[SemanticUnitReceipt] = []
        dispositions: list[str] = []
        for row in rows:
            sources = tuple(
                item["source_digest"]
                for item in connection.execute(
                    """SELECT source_digest
                       FROM session_model_ensemble_semantic_unit_sources
                       WHERE run_id=? AND unit_id=? ORDER BY source_ordinal""",
                    (run_id, row["unit_id"]),
                ).fetchall()
            )
            if len(sources) != int(row["source_count"]):
                raise DatabaseInvariantError(
                    "semantic-unit source graph is incomplete"
                )
            heads.append(
                SemanticUnitReceipt(
                    schema_version=row["schema_version"],
                    contract_version=row["contract_version"],
                    unit_kind_version=row["unit_kind_version"],
                    provider=Provider(seal["provider"]),
                    session_id=seal["session_id"],
                    receipt_id=row["receipt_id"],
                    unit_id=row["unit_id"],
                    unit_digest=row["unit_digest"],
                    revision=row["revision"],
                    previous_receipt_id=row["previous_receipt_id"],
                    kind=row["kind"],
                    lifecycle=row["lifecycle"],
                    extraction_basis=row["extraction_basis"],
                    owner_source_digest=row["owner_source_digest"],
                    source_digests=sources,
                    source_version_digest=row["source_version_digest"],
                    first_sequence=row["first_sequence"],
                    closed_at_sequence=row["closed_at_sequence"],
                    superseded_by_source_digest=row[
                        "superseded_by_source_digest"
                    ],
                    superseded_by_unit_id=row["superseded_by_unit_id"],
                    owner_role=row["owner_role"],
                    owner_message_kind=row["owner_message_kind"],
                    rework_class=row["rework_class"],
                )
            )
            dispositions.append(row["disposition"])
        appended = tuple(
            item
            for item, disposition in zip(heads, dispositions, strict=True)
            if disposition == "appended"
        )
        unchanged_receipt_ids = tuple(
            sorted(
                item.receipt_id
                for item, disposition in zip(heads, dispositions, strict=True)
                if disposition == "unchanged"
            )
        )
        reconciliation = SemanticUnitReconciliation(
            schema_version=seal["schema_version"],
            contract_version=seal["contract_version"],
            provider=Provider(seal["provider"]),
            session_id=seal["session_id"],
            analysis_window_fingerprint=seal["analysis_window_fingerprint"],
            source_complete=bool(seal["source_complete"]),
            reconciliation_id=seal["reconciliation_id"],
            heads=tuple(heads),
            appended=appended,
            unchanged_receipt_ids=unchanged_receipt_ids,
            retained_unobserved_unit_count=seal[
                "retained_unobserved_unit_count"
            ],
        )
        if (
            int(seal["head_count"]) != len(reconciliation.heads)
            or int(seal["appended_count"]) != len(reconciliation.appended)
            or int(seal["unchanged_count"])
            != len(reconciliation.unchanged_receipt_ids)
            or not bool(seal["local_only"])
            or bool(seal["content_persisted"])
            or seal["reconciliation_fingerprint"]
            != _semantic_unit_reconciliation_fingerprint(reconciliation)
        ):
            raise DatabaseInvariantError("semantic-unit sidecar seal is invalid")
        return reconciliation

    def _hydrate(self, connection, run_id: str) -> SessionModelEnsembleRunRecord | None:
        row = connection.execute(
            """SELECT r.* FROM session_model_ensemble_runs r
               JOIN session_model_ensemble_seals s ON s.run_id=r.run_id
               WHERE r.run_id=?""",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        chunks = tuple(
            ModelEnsembleChunkReceipt(
                ordinal=item["chunk_ordinal"],
                chunk_fingerprint=item["chunk_fingerprint"],
                source_message_count=item["source_message_count"],
                fragment_count=item["fragment_count"],
                character_count=item["character_count"],
            )
            for item in connection.execute(
                """SELECT * FROM session_model_ensemble_chunks WHERE run_id=?
                   ORDER BY chunk_ordinal""",
                (run_id,),
            ).fetchall()
        )
        experts = tuple(
            ModelExpertReceipt(
                identity=ModelExpertIdentity(
                    ordinal=item["model_ordinal"],
                    model_key=item["model_key"],
                    role=ModelExpertRole(item["role"]),
                    repository_id=item["repository_id"],
                    revision=item["revision"],
                    tokenizer_id=item["tokenizer_id"],
                    license_spdx=item["license_spdx"],
                    backend_key=item["backend_key"],
                    contributes_to_decision=bool(item["contributes_to_decision"]),
                ),
                status=ModelExpertStatus(item["status"]),
                error_code=item["error_code"],
                device=item["device"],
                inference_latency_ms=item["inference_latency_ms"],
                peak_accelerator_memory_mb=item["peak_accelerator_memory_mb"],
                process_rss_mb=item["process_rss_mb"],
            )
            for item in connection.execute(
                """SELECT * FROM session_model_ensemble_experts WHERE run_id=?
                   ORDER BY model_ordinal""",
                (run_id,),
            ).fetchall()
        )
        selections = []
        for item in connection.execute(
            """SELECT * FROM session_model_ensemble_evidence_selections
               WHERE run_id=? ORDER BY chunk_ordinal,metric_key,model_key""",
            (run_id,),
        ).fetchall():
            refs = tuple(
                ref["fragment_id"]
                for ref in connection.execute(
                    """SELECT fragment_id FROM session_model_ensemble_selection_fragments
                       WHERE run_id=? AND chunk_ordinal=? AND metric_key=? AND model_key=?
                       ORDER BY fragment_ordinal""",
                    (run_id, item["chunk_ordinal"], item["metric_key"], item["model_key"]),
                ).fetchall()
            )
            if len(refs) != item["selected_count"]:
                raise DatabaseInvariantError("model ensemble selection graph is incomplete")
            selections.append(
                ModelEvidenceSelectionReceipt(
                    chunk_ordinal=item["chunk_ordinal"],
                    metric_key=item["metric_key"],
                    model_key=item["model_key"],
                    role=ModelExpertRole(item["role"]),
                    candidate_count=item["candidate_count"],
                    selected_fragment_ids=refs,
                    ranking_fingerprint=item["ranking_fingerprint"],
                    top_raw_score=item["top_raw_score"],
                )
            )
        votes = []
        for item in connection.execute(
            """SELECT * FROM session_model_ensemble_votes WHERE run_id=?
               ORDER BY chunk_ordinal,metric_key,model_key""",
            (run_id,),
        ).fetchall():
            refs = tuple(
                ref["fragment_id"]
                for ref in connection.execute(
                    """SELECT fragment_id FROM session_model_ensemble_vote_fragments
                       WHERE run_id=? AND chunk_ordinal=? AND metric_key=? AND model_key=?
                       ORDER BY fragment_ordinal""",
                    (run_id, item["chunk_ordinal"], item["metric_key"], item["model_key"]),
                ).fetchall()
            )
            if len(refs) != item["evidence_count"]:
                raise DatabaseInvariantError("model ensemble vote graph is incomplete")
            votes.append(
                ModelMetricVote(
                    chunk_ordinal=item["chunk_ordinal"],
                    metric_key=item["metric_key"],
                    model_key=item["model_key"],
                    role=ModelExpertRole(item["role"]),
                    state=ModelVoteState(item["state"]),
                    raw_score=item["raw_score"],
                    evidence_fragment_ids=refs,
                    reason_code=item["reason_code"],
                )
            )
        chunk_metrics = tuple(
            ChunkMetricCommitteeReceipt(
                chunk_ordinal=item["chunk_ordinal"],
                metric_key=item["metric_key"],
                value_state=MetricValueState(item["value_state"]),
                numerator=item["numerator"],
                denominator=item["denominator"],
                rubric_vote=ModelVoteState(item["rubric_vote"]),
                contributing_nli_votes=item["contributing_nli_votes"],
                diagnostic_nli_votes=item["diagnostic_nli_votes"],
                reason_code=item["reason_code"],
            )
            for item in connection.execute(
                """SELECT * FROM session_model_ensemble_chunk_metrics
                   WHERE run_id=? ORDER BY chunk_ordinal,metric_key""",
                (run_id,),
            ).fetchall()
        )
        metrics = tuple(
            SessionModelEnsembleMetricReceipt(
                metric_key=item["metric_key"],
                value_state=MetricValueState(item["value_state"]),
                numerator=item["numerator"],
                denominator=item["denominator"],
                numeric_value=item["numeric_value"],
                known_chunk_count=item["known_chunk_count"],
                abstained_chunk_count=item["abstained_chunk_count"],
                unsupported_chunk_count=item["unsupported_chunk_count"],
                failed_chunk_count=item["failed_chunk_count"],
                total_chunk_count=item["total_chunk_count"],
                explanation_code=item["explanation_code"],
            )
            for item in connection.execute(
                """SELECT * FROM session_model_ensemble_metrics
                   WHERE run_id=? ORDER BY metric_key""",
                (run_id,),
            ).fetchall()
        )
        projection_seal = connection.execute(
            """SELECT * FROM session_model_ensemble_typed_metric_seals
               WHERE run_id=? AND projection_version=?""",
            (run_id, MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION),
        ).fetchone()
        typed_metrics: tuple[SessionModelEnsembleTypedMetricReceipt, ...] = ()
        projection_completed_at = None
        if projection_seal is not None:
            typed_metrics = tuple(
                SessionModelEnsembleTypedMetricReceipt(
                    metric_key=item["metric_key"],
                    metric_version=item["metric_version"],
                    value_state=MetricValueState(item["value_state"]),
                    numerator=item["numerator"],
                    denominator=item["denominator"],
                    numeric_value=item["numeric_value"],
                    observed_message_count=item["observed_message_count"],
                    eligible_message_count=item["eligible_message_count"],
                    coverage=item["coverage"],
                    explanation_code=item["explanation_code"],
                    error_code=item["error_code"],
                    projection_source=item["projection_source"],
                    metric_schema_version=item["metric_schema_version"],
                    engine_version=item["engine_version"],
                    algorithm_id=item["algorithm_id"],
                    algorithm_version=item["algorithm_version"],
                    rubric_version=item["rubric_version"],
                    calibration_state=item["calibration_state"],
                    product_metric_eligible=bool(item["product_metric_eligible"]),
                )
                for item in connection.execute(
                    """SELECT * FROM session_model_ensemble_typed_metrics
                       WHERE run_id=? AND projection_version=? ORDER BY metric_key""",
                    (run_id, MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION),
                ).fetchall()
            )
            projection_completed_at = from_iso(projection_seal["projected_at"])
        # Current repository code is also used by the v38/v39 upgrade fixtures to
        # prove that historical graphs remain readable before MIGRATION_40 is
        # applied.  Missing sidecar tables in those exact legacy schemas mean
        # "no V2 publication", not database corruption.  The r2 sidecar is read
        # first and the r1 sidecar second: a run carries at most one of them,
        # and each keeps the projection identity it was sealed under.
        metric_publication_v2_seal = None
        metric_v2_states_table = None
        for _version, states_table, seals_table in METRIC_V2_SIDECARS:
            present = connection.execute(
                """SELECT COUNT(*) AS table_count FROM sqlite_master
                   WHERE type='table' AND name IN (?,?)""",
                (states_table, seals_table),
            ).fetchone()["table_count"] == 2
            if not present:
                continue
            seal = connection.execute(
                f"SELECT * FROM {seals_table} WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if seal is None:
                continue
            if metric_publication_v2_seal is not None:
                raise DatabaseInvariantError(
                    "a run cannot carry two metric V2 publication identities"
                )
            metric_publication_v2_seal = seal
            metric_v2_states_table = states_table
        metric_publication_v2 = None
        if metric_publication_v2_seal is not None:
            states = tuple(
                _metric_state_v2_from_row(item)
                for item in connection.execute(
                    f"""SELECT * FROM {metric_v2_states_table}
                        WHERE run_id=? ORDER BY metric_ordinal""",
                    (run_id,),
                ).fetchall()
            )
            live_projection = _issue_metric_state_projection(
                states,
                compatibility=False,
            )
            metric_publication_v2 = publish_metric_states_v2(live_projection)
        predictive_seal = connection.execute(
            """SELECT * FROM session_model_ensemble_predictive_metric_seals
               WHERE run_id=? AND projection_version=?""",
            (run_id, PROBABILISTIC_METRIC_PROJECTION_VERSION),
        ).fetchone()
        predictive_projection = None
        if predictive_seal is not None:
            predictive_metrics = []
            for item in connection.execute(
                """SELECT * FROM session_model_ensemble_predictive_metrics
                   WHERE run_id=? AND projection_version=? ORDER BY metric_key""",
                (run_id, PROBABILISTIC_METRIC_PROJECTION_VERSION),
            ).fetchall():
                factors = tuple(
                    PredictiveFactorContribution(
                        factor_key=factor["factor_key"],
                        scale=FactorScale(factor["scale"]),
                        weight=factor["weight"],
                        applicability_probability=factor[
                            "applicability_probability"
                        ],
                        present_probability=factor["present_probability"],
                        neutral_probability=factor["neutral_probability"],
                        absent_probability=factor["absent_probability"],
                        expert_count=factor["expert_count"],
                        critical=bool(factor["critical"]),
                    )
                    for factor in connection.execute(
                        """SELECT * FROM session_model_ensemble_predictive_factors
                           WHERE run_id=? AND projection_version=? AND metric_key=?
                           ORDER BY factor_ordinal""",
                        (
                            run_id,
                            PROBABILISTIC_METRIC_PROJECTION_VERSION,
                            item["metric_key"],
                        ),
                    ).fetchall()
                )
                density = tuple(
                    float(bin_row["probability_mass"])
                    for bin_row in connection.execute(
                        """SELECT probability_mass
                           FROM session_model_ensemble_predictive_density_bins
                           WHERE run_id=? AND projection_version=? AND metric_key=?
                           ORDER BY bin_ordinal""",
                        (
                            run_id,
                            PROBABILISTIC_METRIC_PROJECTION_VERSION,
                            item["metric_key"],
                        ),
                    ).fetchall()
                )
                predictive_metrics.append(
                    SessionPredictiveMetricReceipt(
                        metric_key=item["metric_key"],
                        target=PredictiveMetricTarget(item["target"]),
                        state=PredictiveMetricState(item["state"]),
                        mean=item["mean"],
                        median=item["median"],
                        q05=item["q05"],
                        q25=item["q25"],
                        q75=item["q75"],
                        q95=item["q95"],
                        applicability_probability=item[
                            "applicability_probability"
                        ],
                        pending_probability=item["pending_probability"],
                        model_disagreement=item["model_disagreement"],
                        effective_observation_count=item[
                            "effective_observation_count"
                        ],
                        model_set_version=item["model_set_version"],
                        calibration_version=item["calibration_version"],
                        contract_version=item["contract_version"],
                        contract_fingerprint=item["contract_fingerprint"],
                        density_bins=density,
                        factors=factors,
                        product_metric_eligible=bool(
                            item["product_metric_eligible"]
                        ),
                    )
                )
            predictive_stages = tuple(
                PredictiveModelStageReceipt(
                    model_key=item["model_key"],
                    repository_id=item["repository_id"],
                    revision=item["revision"],
                    status=item["status"],
                    error_code=item["error_code"],
                    device=item["device"],
                    quantization=item["quantization"],
                    inference_latency_ms=item["inference_latency_ms"],
                    peak_accelerator_memory_mb=item[
                        "peak_accelerator_memory_mb"
                    ],
                    process_rss_mb=item["process_rss_mb"],
                    unloaded_after_stage=bool(item["unloaded_after_stage"]),
                )
                for item in connection.execute(
                    """SELECT * FROM session_model_ensemble_predictive_model_stages
                       WHERE run_id=? AND projection_version=? ORDER BY stage_ordinal""",
                    (run_id, PROBABILISTIC_METRIC_PROJECTION_VERSION),
                ).fetchall()
            )
            metrics_by_key = {
                item.metric_key: item for item in predictive_metrics
            }
            predictive_projection = SessionPredictiveMetricProjection(
                projection_version=predictive_seal["projection_version"],
                contract_registry_version=predictive_seal["registry_version"],
                model_set_version=predictive_seal["model_set_version"],
                projected_at=from_iso(predictive_seal["projected_at"]),
                metrics=tuple(
                    metrics_by_key[item.metric_key]
                    for item in PROBABILISTIC_METRIC_CONTRACTS
                ),
                model_stages=predictive_stages,
                sample_count=predictive_seal["sample_count"],
                local_only=bool(predictive_seal["local_only"]),
                content_persisted=bool(predictive_seal["content_persisted"]),
                calibrated_as_truth=bool(predictive_seal["calibrated_as_truth"]),
            )
        if (
            metric_publication_v2 is not None
            and metric_publication_v2.projection_version
            == METRIC_PROJECTION_V2_VERSION_8
            and len(typed_metrics) != len(METRIC_CONTRACTS_V2)
        ):
            raise DatabaseInvariantError(
                "r8 typed metric projection does not contain all twenty rows"
            )
        receipt = SessionModelEnsembleReceipt(
            plan_version=row["plan_version"],
            plan_fingerprint=row["plan_fingerprint"],
            source_window_fingerprint=row["source_window_fingerprint"],
            source_coverage_state=SourceCoverageState(row["source_coverage_state"]),
            chunk_count=row["chunk_count"],
            model_count=row["model_count"],
            chunk_plan=chunks,
            chunks=chunk_metrics,
            metrics=metrics,
            metric_projection_version=(
                None
                if projection_seal is None
                else MODEL_ENSEMBLE_METRIC_PROJECTION_VERSION
            ),
            metric_projection_completed_at=projection_completed_at,
            typed_metrics=typed_metrics,
            metric_publication_v2=metric_publication_v2,
            predictive_projection=predictive_projection,
            experts=experts,
            evidence_selections=tuple(selections),
            model_votes=tuple(votes),
            created_at=from_iso(row["created_at"]),
            completed_at=from_iso(row["completed_at"]),
        )
        try:
            validate_r8_typed_metric_projection(receipt)
        except ValueError as exc:
            raise DatabaseInvariantError(
                "r8 verified typed metric receipt is stale"
            ) from exc
        metric_profile_binding = self._hydrate_metric_profile_binding(
            connection,
            run_id,
        )
        requirement_plan_evidence_binding = (
            self.validate_requirement_plan_run_authority(connection, run_id)
        )
        requirement_action_evidence_binding = (
            self.validate_requirement_action_run_authority(
                connection,
                run_id,
            )
        )
        requirement_verification_evidence_binding = (
            self.validate_requirement_verification_run_authority(
                connection,
                run_id,
            )
        )
        record = SessionModelEnsembleRunRecord(
            run_id=row["run_id"],
            session_id=row["session_id"],
            request_fingerprint=row["request_fingerprint"],
            input_fingerprint=row["input_fingerprint"],
            provider=Provider(row["provider"]),
            provider_version=row["provider_version"],
            adapter_version=row["adapter_version"],
            source_schema_version=row["source_schema_version"],
            content_schema_version=row["content_schema_version"],
            redactor_version=row["redactor_version"],
            consent_policy_version=row["consent_policy_version"],
            metric_profile_binding=metric_profile_binding,
            requirement_plan_evidence_binding=(
                requirement_plan_evidence_binding
            ),
            requirement_action_evidence_binding=(
                requirement_action_evidence_binding
            ),
            requirement_verification_evidence_binding=(
                requirement_verification_evidence_binding
            ),
            receipt=receipt,
        )
        seal = connection.execute(
            "SELECT graph_fingerprint FROM session_model_ensemble_seals WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if seal is None or seal["graph_fingerprint"] != _graph_fingerprint(record):
            raise DatabaseInvariantError("model ensemble graph seal is invalid")
        if projection_seal is not None and (
            int(projection_seal["metric_count"]) != len(typed_metrics)
            or projection_seal["projection_fingerprint"]
            != _metric_projection_fingerprint(record.receipt)
        ):
            raise DatabaseInvariantError("typed metric projection seal is invalid")
        if metric_publication_v2_seal is not None and (
            metric_publication_v2 is None
            or metric_publication_v2_seal["publication_key"]
            != METRIC_PUBLICATION_V2_KEY
            or int(metric_publication_v2_seal["publication_version"])
            != METRIC_PUBLICATION_V2_VERSION
            or metric_publication_v2_seal["registry_version"]
            != metric_publication_v2.registry_version
            or metric_publication_v2_seal["contract_set_fingerprint"]
            != metric_publication_v2.contract_set_fingerprint
            or metric_publication_v2_seal["projection_version"]
            != metric_publication_v2.projection_version
            or metric_publication_v2_seal["guidance_contract_version"]
            != metric_publication_v2.guidance_contract_version
            or metric_publication_v2_seal["guidance_template_catalog_version"]
            != metric_publication_v2.guidance_template_catalog_version
            or metric_publication_v2_seal["source"]
            != MetricPublicationSource.LIVE_PROJECTION.value
            or not bool(metric_publication_v2_seal["canonical_live_snapshot"])
            or bool(metric_publication_v2_seal["compatibility_preview"])
            or bool(metric_publication_v2_seal["model_stage_consumed"])
            or int(metric_publication_v2_seal["metric_count"])
            != len(metric_publication_v2.metrics)
            or int(metric_publication_v2_seal["known_count"])
            != metric_publication_v2.known_count
            or int(metric_publication_v2_seal["pending_count"])
            != metric_publication_v2.pending_count
            or int(metric_publication_v2_seal["unknown_count"])
            != metric_publication_v2.unknown_count
            or int(metric_publication_v2_seal["not_applicable_count"])
            != metric_publication_v2.not_applicable_count
            or int(metric_publication_v2_seal["abstained_count"])
            != metric_publication_v2.abstained_count
            or int(metric_publication_v2_seal["execution_error_count"])
            != metric_publication_v2.execution_error_count
            or int(metric_publication_v2_seal["objective_measured_count"])
            != metric_publication_v2.objective_measured_count
            or metric_publication_v2_seal["projection_fingerprint"]
            != _metric_publication_v2_fingerprint(metric_publication_v2)
            or (
                metric_publication_v2.projection_version
                in {
                    METRIC_PROJECTION_V2_VERSION_5,
                    METRIC_PROJECTION_V2_VERSION_6,
                    METRIC_PROJECTION_V2_VERSION_7,
                    METRIC_PROJECTION_V2_VERSION_8,
                }
                and (
                    metric_profile_binding is None
                    or metric_publication_v2_seal["profile_source"]
                    != metric_profile_binding.profile_source.value
                    or metric_publication_v2_seal["profile_id"]
                    != metric_profile_binding.profile_id
                    or metric_publication_v2_seal["profile_revision"]
                    != metric_profile_binding.profile_revision
                    or metric_publication_v2_seal["profile_fingerprint"]
                    != metric_profile_binding.profile_fingerprint
                    or metric_publication_v2_seal["profile_schema_version"]
                    != metric_profile_binding.profile_schema_version
                    or metric_publication_v2_seal["profile_policy_version"]
                    != metric_profile_binding.profile_policy_version
                    or metric_publication_v2_seal[
                        "profile_binding_fingerprint"
                    ]
                    != _metric_profile_binding_fingerprint(
                        metric_profile_binding
                    )
                    or metric_publication_v2_seal[
                        "publication_profile_fingerprint"
                    ]
                    != _metric_publication_profile_fingerprint(
                        metric_publication_v2,
                        metric_profile_binding,
                    )
                )
            )
            or (
                metric_publication_v2.projection_version
                in {
                    METRIC_PROJECTION_V2_VERSION_6,
                    METRIC_PROJECTION_V2_VERSION_7,
                    METRIC_PROJECTION_V2_VERSION_8,
                }
                and (
                    requirement_plan_evidence_binding is None
                    or metric_publication_v2_seal["requirement_plan_source"]
                    != requirement_plan_evidence_binding.evidence_source.value
                    or metric_publication_v2_seal[
                        "requirement_plan_confirmation_id"
                    ]
                    != requirement_plan_evidence_binding.confirmation_id
                    or metric_publication_v2_seal[
                        "requirement_plan_proposal_id"
                    ]
                    != requirement_plan_evidence_binding.proposal_id
                    or metric_publication_v2_seal[
                        "requirement_plan_evidence_fingerprint"
                    ]
                    != requirement_plan_evidence_binding.evidence_fingerprint
                    or metric_publication_v2_seal[
                        "requirement_plan_schema_version"
                    ]
                    != requirement_plan_evidence_binding.evidence_schema_version
                    or metric_publication_v2_seal[
                        "requirement_plan_policy_version"
                    ]
                    != requirement_plan_evidence_binding.evidence_policy_version
                    or metric_publication_v2_seal[
                        "requirement_plan_binding_fingerprint"
                    ]
                    != _requirement_plan_binding_fingerprint(
                        requirement_plan_evidence_binding
                    )
                    or metric_publication_v2_seal[
                        "publication_requirement_plan_fingerprint"
                    ]
                    != _metric_publication_requirement_plan_fingerprint(
                        metric_publication_v2,
                        requirement_plan_evidence_binding,
                    )
                )
            )
            or (
                metric_publication_v2.projection_version
                in {
                    METRIC_PROJECTION_V2_VERSION_7,
                    METRIC_PROJECTION_V2_VERSION_8,
                }
                and (
                    requirement_action_evidence_binding is None
                    or metric_publication_v2_seal["requirement_action_source"]
                    != requirement_action_evidence_binding.evidence_source.value
                    or metric_publication_v2_seal[
                        "requirement_action_source_run_id"
                    ]
                    != requirement_action_evidence_binding.source_run_id
                    or metric_publication_v2_seal[
                        "requirement_action_requirement_plan_confirmation_id"
                    ]
                    != requirement_action_evidence_binding.requirement_plan_confirmation_id
                    or metric_publication_v2_seal[
                        "requirement_action_requirement_plan_evidence_fingerprint"
                    ]
                    != requirement_action_evidence_binding.requirement_plan_evidence_fingerprint
                    or metric_publication_v2_seal[
                        "requirement_action_candidate_manifest_fingerprint"
                    ]
                    != requirement_action_evidence_binding.candidate_manifest_fingerprint
                    or metric_publication_v2_seal[
                        "requirement_action_reviewed_descriptor_set_fingerprint"
                    ]
                    != requirement_action_evidence_binding.reviewed_descriptor_set_fingerprint
                    or metric_publication_v2_seal[
                        "requirement_action_confirmation_id"
                    ]
                    != requirement_action_evidence_binding.confirmation_id
                    or metric_publication_v2_seal[
                        "requirement_action_proposal_id"
                    ]
                    != requirement_action_evidence_binding.proposal_id
                    or metric_publication_v2_seal[
                        "requirement_action_evidence_fingerprint"
                    ]
                    != requirement_action_evidence_binding.evidence_fingerprint
                    or metric_publication_v2_seal[
                        "requirement_action_schema_version"
                    ]
                    != requirement_action_evidence_binding.evidence_schema_version
                    or metric_publication_v2_seal[
                        "requirement_action_policy_version"
                    ]
                    != requirement_action_evidence_binding.evidence_policy_version
                    or metric_publication_v2_seal[
                        "requirement_action_binding_fingerprint"
                    ]
                    != _requirement_action_binding_fingerprint(
                        requirement_action_evidence_binding
                    )
                    or metric_publication_v2_seal[
                        "publication_requirement_action_fingerprint"
                    ]
                    != _metric_publication_requirement_action_fingerprint(
                        metric_publication_v2,
                        requirement_action_evidence_binding,
                    )
                )
            )
            or (
                metric_publication_v2.projection_version
                == METRIC_PROJECTION_V2_VERSION_8
                and (
                    requirement_verification_evidence_binding is None
                    or metric_publication_v2_seal[
                        "requirement_verification_source"
                    ]
                    != requirement_verification_evidence_binding.evidence_source.value
                    or metric_publication_v2_seal[
                        "requirement_verification_requirement_plan_confirmation_id"
                    ]
                    != requirement_verification_evidence_binding.requirement_plan_confirmation_id
                    or metric_publication_v2_seal[
                        "requirement_verification_requirement_plan_proposal_id"
                    ]
                    != requirement_verification_evidence_binding.requirement_plan_proposal_id
                    or metric_publication_v2_seal[
                        "requirement_verification_requirement_plan_evidence_fingerprint"
                    ]
                    != requirement_verification_evidence_binding.requirement_plan_evidence_fingerprint
                    or metric_publication_v2_seal[
                        "requirement_verification_requirement_plan_schema_version"
                    ]
                    != requirement_verification_evidence_binding.requirement_plan_schema_version
                    or metric_publication_v2_seal[
                        "requirement_verification_requirement_plan_policy_version"
                    ]
                    != requirement_verification_evidence_binding.requirement_plan_policy_version
                    or metric_publication_v2_seal[
                        "requirement_verification_requirement_plan_review_rubric_version"
                    ]
                    != requirement_verification_evidence_binding.requirement_plan_review_rubric_version
                    or metric_publication_v2_seal[
                        "requirement_verification_opportunity_count"
                    ]
                    != requirement_verification_evidence_binding.opportunity_count
                    or metric_publication_v2_seal[
                        "requirement_verification_opportunity_set_fingerprint"
                    ]
                    != requirement_verification_evidence_binding.opportunity_set_fingerprint
                    or metric_publication_v2_seal[
                        "requirement_verification_evidence_set_fingerprint"
                    ]
                    != requirement_verification_evidence_binding.evidence_set_fingerprint
                    or metric_publication_v2_seal[
                        "requirement_verification_through_revision"
                    ]
                    != requirement_verification_evidence_binding.through_revision
                    or metric_publication_v2_seal[
                        "requirement_verification_authority_head_count"
                    ]
                    != requirement_verification_evidence_binding.authority_head_count
                    or metric_publication_v2_seal[
                        "requirement_verification_objective_result_count"
                    ]
                    != requirement_verification_evidence_binding.objective_result_count
                    or metric_publication_v2_seal[
                        "requirement_verification_native_acceptance_count"
                    ]
                    != requirement_verification_evidence_binding.native_acceptance_count
                    or metric_publication_v2_seal[
                        "requirement_verification_resolved_opportunity_count"
                    ]
                    != requirement_verification_evidence_binding.resolved_opportunity_count
                    or metric_publication_v2_seal[
                        "requirement_verification_met_requirement_count"
                    ]
                    != requirement_verification_evidence_binding.met_requirement_count
                    or metric_publication_v2_seal[
                        "requirement_verification_opportunity_issuer_version"
                    ]
                    != requirement_verification_evidence_binding.opportunity_issuer_version
                    or metric_publication_v2_seal[
                        "requirement_verification_result_issuer_version"
                    ]
                    != requirement_verification_evidence_binding.result_issuer_version
                    or metric_publication_v2_seal[
                        "requirement_verification_acceptance_issuer_version"
                    ]
                    != requirement_verification_evidence_binding.acceptance_issuer_version
                    or metric_publication_v2_seal[
                        "requirement_verification_evidence_schema_version"
                    ]
                    != requirement_verification_evidence_binding.evidence_schema_version
                    or metric_publication_v2_seal[
                        "requirement_verification_evidence_policy_version"
                    ]
                    != requirement_verification_evidence_binding.evidence_policy_version
                    or metric_publication_v2_seal[
                        "requirement_verification_persistence_schema_version"
                    ]
                    != requirement_verification_evidence_binding.persistence_schema_version
                    or metric_publication_v2_seal[
                        "requirement_verification_evidence_projection_version"
                    ]
                    != requirement_verification_evidence_binding.evidence_projection_version
                    or metric_publication_v2_seal[
                        "requirement_verification_objective_projection_version"
                    ]
                    != requirement_verification_evidence_binding.objective_projection_version
                    or metric_publication_v2_seal[
                        "requirement_verification_binding_schema_version"
                    ]
                    != requirement_verification_evidence_binding.binding_schema_version
                    or metric_publication_v2_seal[
                        "requirement_verification_binding_fingerprint"
                    ]
                    != requirement_verification_evidence_binding.binding_fingerprint
                    or metric_publication_v2_seal[
                        "publication_requirement_verification_fingerprint"
                    ]
                    != _metric_publication_requirement_verification_fingerprint(
                        metric_publication_v2,
                        requirement_verification_evidence_binding,
                    )
                )
            )
        ):
            raise DatabaseInvariantError("metric V2 publication seal is invalid")
        if predictive_seal is not None and (
            predictive_projection is None
            or int(predictive_seal["metric_count"])
            != len(predictive_projection.metrics)
            or int(predictive_seal["factor_count"])
            != sum(len(item.factors) for item in predictive_projection.metrics)
            or int(predictive_seal["density_bin_count"])
            != sum(
                len(item.density_bins) for item in predictive_projection.metrics
            )
            or int(predictive_seal["stage_count"])
            != len(predictive_projection.model_stages)
            or predictive_seal["projection_fingerprint"]
            != _predictive_projection_fingerprint(predictive_projection)
        ):
            raise DatabaseInvariantError("predictive metric projection seal is invalid")
        return record


__all__ = ["SqliteSessionModelEnsembleRepository"]
