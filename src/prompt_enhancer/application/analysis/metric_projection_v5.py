"""Projection r5: clause-owned acceptance-test opportunities.

Projection r4 remains frozen and readable.  Supplying a reviewed task profile
was already an input supported by r4, but its acceptance implementation
repeated one global yes/no cue across every declared expected outcome.  A
profile that declared three outcomes could therefore never score above 1/3.

R5 inherits every r4 decision and replaces exactly
``prompt.acceptance_testability``.  It counts distinct checkable requirement
clauses owned by the canonical active request revision, capped by the reviewed
expected-outcome count.  Clause text is used only ephemerally and is never
returned or persisted by this projection.
"""

from __future__ import annotations

from collections.abc import Mapping
import re

from .coaching_baselines import CoachingTextFeatureExtractor
from .metric_contract_v2 import METRIC_CONTRACTS_V2, OpportunityState
from .metric_lifecycle_evidence import MetricLifecycleEvidenceSnapshot
from .metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_5,
    LiveMetricStateProjectionV2,
    _canonical_revision,
    _issue_metric_state_projection,
    _Opportunity,
    _profile_slot_state,
    _statistics,
    _Window,
    resolve_metric_state,
)
from .metric_projection_v4 import project_metric_states_v4
from .objective_metric_projection import ObjectiveMetricOverride
from .semantic_units import SemanticUnitIdFactory, SemanticUnitReconciliation
from .text_contracts import P1TextAnalysisInput, TextLanguage, TextMetricResult


METRIC_PROJECTION_V5_VERSION = METRIC_PROJECTION_V2_VERSION_5
METRIC_PROJECTION_V5_ALGORITHM_ID = (
    "rules.en-pl.clause-owned-acceptance.contract-v2-opportunities"
)
METRIC_PROJECTION_V5_ALGORITHM_VERSION = "5"
ACCEPTANCE_METRIC_KEY = "prompt.acceptance_testability"
REASON_CLAUSE_OWNED_ACCEPTANCE = "declared_profile_checkable_clauses"
_SUPPORTED_LANGUAGES = frozenset(
    {TextLanguage.ENGLISH, TextLanguage.POLISH, TextLanguage.MIXED}
)
_WHITESPACE = re.compile(r"\s+")


def _acceptance_state_v5(
    *,
    context: P1TextAnalysisInput,
    reconciliation: SemanticUnitReconciliation | None,
    id_factory: SemanticUnitIdFactory,
):
    contract = next(
        item for item in METRIC_CONTRACTS_V2 if item.metric_key == ACCEPTANCE_METRIC_KEY
    )
    window = _Window(context, id_factory)
    revision = (
        None
        if reconciliation is None
        else _canonical_revision(context, reconciliation, window)
    )
    source_complete = context.requested_scope_complete or (
        context.analysis_scope is None
        and context.window_complete
        and context.text_extraction_complete
    )
    baseline = _profile_slot_state(
        contract,
        context,
        revision,
        window,
        source_complete=source_complete,
        projection_version=METRIC_PROJECTION_V5_VERSION,
    )
    expected = context.task_profile.expected_outcome_count
    if expected is None or revision is None:
        return baseline
    owner = window.message(revision.owner_source_digest)
    if owner is None or owner.language not in _SUPPORTED_LANGUAGES:
        return baseline

    features = CoachingTextFeatureExtractor().extract(context)
    distinct_clauses = {
        _WHITESPACE.sub(" ", clause.text).strip().casefold()
        for clause in features.checkable_requirements
        if clause.message_id == owner.message_id
    }
    met_count = min(expected, len(distinct_clauses))
    opportunities = tuple(
        _Opportunity(
            unit_id=f"slot-{index}",
            owner_source_digest=f"slot-{index}",
            state=(
                OpportunityState.MET
                if index < met_count
                else OpportunityState.NOT_MET
            ),
        )
        for index in range(expected)
    )
    return resolve_metric_state(
        contract,
        _statistics(
            contract,
            opportunities,
            capability_available=True,
            source_complete=source_complete,
        ),
        explanation_code=REASON_CLAUSE_OWNED_ACCEPTANCE,
        projection_version=METRIC_PROJECTION_V5_VERSION,
    )


def project_metric_states_v5(
    *,
    context: P1TextAnalysisInput,
    reconciliation: SemanticUnitReconciliation | None,
    id_factory: SemanticUnitIdFactory,
    conversational_results: Mapping[str, TextMetricResult] | None = None,
    objective_overrides: Mapping[str, ObjectiveMetricOverride] | None = None,
    lifecycle_evidence: MetricLifecycleEvidenceSnapshot | None = None,
) -> LiveMetricStateProjectionV2:
    """Project all twenty contracts under append-only identity r5."""

    inherited = project_metric_states_v4(
        context=context,
        reconciliation=reconciliation,
        id_factory=id_factory,
        conversational_results=conversational_results,
        objective_overrides=objective_overrides,
        lifecycle_evidence=lifecycle_evidence,
    )
    acceptance = _acceptance_state_v5(
        context=context,
        reconciliation=reconciliation,
        id_factory=id_factory,
    )
    states = tuple(
        acceptance
        if state.metric_key == ACCEPTANCE_METRIC_KEY
        else state.model_copy(
            update={"projection_version": METRIC_PROJECTION_V5_VERSION}
        )
        for state in inherited
    )
    if len(states) != len(METRIC_CONTRACTS_V2) or any(
        state.projection_version != METRIC_PROJECTION_V5_VERSION for state in states
    ):
        raise AssertionError("r5 projection produced an incomplete identity")
    projection = _issue_metric_state_projection(states, compatibility=False)
    if not isinstance(projection, LiveMetricStateProjectionV2):
        raise AssertionError("live projection issuer returned the wrong envelope")
    return projection


__all__ = [
    "ACCEPTANCE_METRIC_KEY",
    "METRIC_PROJECTION_V5_ALGORITHM_ID",
    "METRIC_PROJECTION_V5_ALGORITHM_VERSION",
    "METRIC_PROJECTION_V5_VERSION",
    "REASON_CLAUSE_OWNED_ACCEPTANCE",
    "project_metric_states_v5",
]
