"""Projection identity r3: the corrections that could not be made in place.

``metric_projection_v2`` stays frozen.  Rows it wrote were produced by rules
that are no longer the ones current code applies, so relabelling them would
make a stored number mean something the producer never meant.  This module is
therefore a new persisted projection identity
(``metric-contract-v2-projection-3``, algorithm version ``3``) that reuses every
shared rule verbatim and changes exactly four decisions:

1. **Objective withholding causes stay distinct.**  r2 collapsed "this adapter
   has no authority over the family", "the family is declared but the source
   window was not fully extracted", and "the family is observable and complete
   but larger than the receipt bound" into one capability-missing unknown.  r3
   reads the closed :class:`ObjectiveWithholdingCause` the r3 objective
   producer declares and reports each as the readiness dimension it is.  A
   receipt-bound overflow in particular becomes *evidence unresolved* with the
   capability available and the source complete, never ``not_applicable``.
2. **An empty objective opportunity set is measurable only when proved.**  The
   r3 objective producer requires enumeration, negative-link, *and* every
   outcome kind before an empty set may become ``not_applicable``.
3. **A rubric with no reconciliation reports missing ownership.**  r2 treated an
   absent semantic-unit head set as a proved absence of request revisions and
   published ``not_applicable`` for two rubric contracts.  Nothing was proved:
   without heads there is no opportunity ownership to score against, so r3
   withholds with an ownership reason instead.
4. **``logic.open_loop_closure`` becomes structurally measurable.**  Its
   opportunities come from the ephemeral explicit-plan extractor in
   ``open_loop_lifecycle_v3``: one episode per documented ``AGENT`` ``PLAN``
   message, closed only by a later ``AGENT`` ``ACTION`` or ``VERIFICATION``
   that names that exact plan message in ``supersedes_message_ids``.  No
   persisted semantic-unit receipt changes meaning, no lexical rule is
   consulted, and an absent plan set stays a named actionable unknown.

Everything else — the rubric, profile-slot, and remaining episode contracts —
is the same code path r2 uses, stamped with the r3 identity.  The other
structural collaboration metrics keep their honest unknown; this tranche adds
one measurable metric, not a sweep.
"""

from __future__ import annotations

from collections.abc import Mapping

from .metric_contract_v2 import (
    DenominatorBasis,
    METRIC_CONTRACTS_V2,
    MetricContractV2,
    MetricValueStateV2,
    OpportunityState,
)
from .metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_3,
    LiveMetricStateProjectionV2,
    MetricStateV2,
    _canonical_revision,
    _focus_owned_revision,
    _issue_metric_state_projection,
    _objective_state,
    _Opportunity,
    _profile_slot_state,
    _rubric_state,
    _statistics,
    _unit_state,
    _Window,
    resolve_metric_state,
)
from .objective_metric_projection import (
    ObjectiveMetricOverride,
    ObjectiveWithholdingCause,
)
from .open_loop_lifecycle_v3 import (
    OpenLoopLifecycleProjection,
    project_open_loop_lifecycle_v3,
)
from .semantic_units import (
    SemanticUnitIdFactory,
    SemanticUnitReconciliation,
)
from .text_contracts import P1TextAnalysisInput, TextMetricResult


METRIC_PROJECTION_V3_VERSION = METRIC_PROJECTION_V2_VERSION_3
METRIC_PROJECTION_V3_ALGORITHM_ID = "rules.en-pl.contract-v2-opportunities"
METRIC_PROJECTION_V3_ALGORITHM_VERSION = "3"
#: A rubric fraction needs an exactly-owned request revision.  With no
#: reconciliation at all there is no ownership to check, which is a missing
#: capability and never a proved absence of opportunities.
REASON_RUBRIC_OWNERSHIP_UNAVAILABLE = "rubric_opportunity_ownership_unavailable"
#: The one metric whose r3 opportunities come from the ephemeral lifecycle
#: extractor rather than from persisted semantic-unit heads.
OPEN_LOOP_METRIC_KEY = "logic.open_loop_closure"
#: Causes whose state is fully described by the capability/completeness pair
#: below, with no opportunity to enumerate.
_WITHHELD_CAUSE_FLAGS: dict[ObjectiveWithholdingCause, tuple[bool, bool]] = {
    # (capability_available, source_complete)
    ObjectiveWithholdingCause.AUTHORITY_MISSING: (False, False),
    ObjectiveWithholdingCause.EXTRACTION_INCOMPLETE: (True, False),
    ObjectiveWithholdingCause.OPPORTUNITY_BOUND_EXCEEDED: (True, True),
}


def _withheld_objective_state(
    contract: MetricContractV2,
    override: ObjectiveMetricOverride,
) -> MetricStateV2:
    """Report a withheld objective contract as the readiness dimension it is.

    The state is built directly rather than through ``resolve_metric_state``
    because that resolver reads an empty eligible set as "no opportunity", and
    for a receipt-bound overflow the opportunity set is demonstrably not empty:
    it is too large to represent.  Publishing ``not_applicable`` there would be
    the exact false zero this identity exists to remove.  The producer's own
    ``explanation_code`` is preserved verbatim.
    """

    capability_available, source_complete = _WITHHELD_CAUSE_FLAGS[
        override.withholding_cause
    ]
    return MetricStateV2(
        metric_key=contract.metric_key,
        contract_version=contract.contract_version,
        contract_fingerprint=contract.fingerprint,
        evidence_authority=contract.evidence_authority,
        value_state=MetricValueStateV2.UNKNOWN,
        explanation_code=override.explanation_code,
        statistics=_statistics(
            contract,
            (),
            capability_available=capability_available,
            source_complete=source_complete,
        ),
        projection_version=METRIC_PROJECTION_V3_VERSION,
    )


def objective_metric_state_v3(
    contract: MetricContractV2,
    override: ObjectiveMetricOverride | None,
) -> MetricStateV2:
    """Resolve one objective contract from an r3 objective override."""

    if contract.denominator_basis is not DenominatorBasis.OBJECTIVE_OPPORTUNITIES:
        raise ValueError("only objective contracts use the objective lane")
    if override is None:
        return _objective_state(
            contract,
            None,
            projection_version=METRIC_PROJECTION_V3_VERSION,
        )
    if override.withholding_cause is ObjectiveWithholdingCause.UNSPECIFIED:
        # The frozen r2 producer never declares a cause.  Accepting its output
        # here would silently republish r2 semantics under the r3 identity.
        raise ValueError(
            "r3 objective states require an r3 objective override"
        )
    if override.withholding_cause in _WITHHELD_CAUSE_FLAGS:
        return _withheld_objective_state(contract, override)
    return _objective_state(
        contract,
        override,
        projection_version=METRIC_PROJECTION_V3_VERSION,
    )


def open_loop_metric_state_v3(
    contract: MetricContractV2,
    lifecycle: OpenLoopLifecycleProjection,
    *,
    source_complete: bool,
) -> MetricStateV2:
    """Project explicit plan episodes onto the open-loop closure contract.

    One episode is one opportunity with exactly one owner.  A closed episode is
    ``met``; an episode with no explicit closing link is ``pending``, never
    ``not_met``: the window may simply have ended before the loop did.  There
    is no ``not_met`` outcome at all, which is why this metric can be measured
    only when every episode carries an explicit link and otherwise publishes
    honest censoring bounds.
    """

    if not lifecycle.capability_available:
        return resolve_metric_state(
            contract,
            _statistics(
                contract,
                (),
                capability_available=False,
                source_complete=source_complete,
            ),
            explanation_code=lifecycle.reason_code,
            unavailable_code=lifecycle.reason_code,
            projection_version=METRIC_PROJECTION_V3_VERSION,
        )
    opportunities = tuple(
        _Opportunity(
            episode.episode_id,
            episode.owner_source_digest,
            OpportunityState.MET if episode.closed else OpportunityState.PENDING,
        )
        for episode in lifecycle.episodes
    )
    return resolve_metric_state(
        contract,
        _statistics(
            contract,
            opportunities,
            capability_available=True,
            source_complete=source_complete,
        ),
        explanation_code=lifecycle.reason_code,
        projection_version=METRIC_PROJECTION_V3_VERSION,
    )


def project_metric_states_v3(
    *,
    context: P1TextAnalysisInput,
    reconciliation: SemanticUnitReconciliation | None,
    id_factory: SemanticUnitIdFactory,
    conversational_results: Mapping[str, TextMetricResult] | None = None,
    objective_overrides: Mapping[str, ObjectiveMetricOverride] | None = None,
) -> LiveMetricStateProjectionV2:
    """Project all twenty contracts under projection identity r3.

    ``objective_overrides`` must come from ``project_objective_metric_overrides_v3``:
    an r2 override carries no withholding cause and is rejected rather than
    reinterpreted.
    """

    if reconciliation is not None and (
        reconciliation.provider is not context.provider
        or reconciliation.session_id != context.session_id
        or reconciliation.analysis_window_fingerprint
        != context.analysis_window_fingerprint
    ):
        raise ValueError("semantic-unit heads describe a different analysis window")
    conversational = dict(conversational_results or {})
    objective = dict(objective_overrides or {})
    window = _Window(context, id_factory)
    revision = (
        None
        if reconciliation is None
        else _canonical_revision(context, reconciliation, window)
    )
    focus_revision = (
        None
        if reconciliation is None
        else _focus_owned_revision(context, reconciliation, window)
    )
    focus_unowned = revision is not None and focus_revision is None
    # A fixed rubric or declared profile belongs to the canonical request in the
    # explicitly requested bounded scope; cross-turn episodes need the stricter
    # whole-window completeness.  Both are unchanged from r2.
    requested_scope_complete = context.requested_scope_complete or (
        context.analysis_scope is None
        and context.window_complete
        and context.text_extraction_complete
    )
    # The explicit-plan extractor reads the analysis window directly, so its
    # completeness is the window's own, not the reconciliation's.  It is the
    # same expression the reconciler uses, so the two never disagree.
    episode_source_complete = (
        context.window_complete and context.text_extraction_complete
    )
    open_loop = project_open_loop_lifecycle_v3(context, id_factory)
    states: list[MetricStateV2] = []
    for contract in METRIC_CONTRACTS_V2:
        if contract.denominator_basis is DenominatorBasis.OBJECTIVE_OPPORTUNITIES:
            states.append(
                objective_metric_state_v3(
                    contract, objective.get(contract.metric_key)
                )
            )
        elif contract.metric_key == OPEN_LOOP_METRIC_KEY:
            states.append(
                open_loop_metric_state_v3(
                    contract,
                    open_loop,
                    source_complete=episode_source_complete,
                )
            )
        elif contract.denominator_basis is DenominatorBasis.DECLARED_PROFILE_SLOTS:
            states.append(
                _profile_slot_state(
                    contract,
                    context,
                    revision,
                    window,
                    source_complete=requested_scope_complete,
                    projection_version=METRIC_PROJECTION_V3_VERSION,
                )
            )
        elif contract.denominator_basis is DenominatorBasis.RUBRIC_FACTORS:
            if reconciliation is None:
                # No head set was reconciled for this window, so no request
                # revision can be shown to own the scored focus message.  That
                # is missing ownership, not a proved empty opportunity set.
                states.append(
                    resolve_metric_state(
                        contract,
                        _statistics(
                            contract,
                            (),
                            capability_available=False,
                            source_complete=requested_scope_complete,
                        ),
                        explanation_code=REASON_RUBRIC_OWNERSHIP_UNAVAILABLE,
                        unavailable_code=REASON_RUBRIC_OWNERSHIP_UNAVAILABLE,
                        projection_version=METRIC_PROJECTION_V3_VERSION,
                    )
                )
            else:
                states.append(
                    _rubric_state(
                        contract,
                        conversational.get(contract.metric_key),
                        focus_revision,
                        focus_unowned=focus_unowned,
                        source_complete=requested_scope_complete,
                        projection_version=METRIC_PROJECTION_V3_VERSION,
                    )
                )
        elif reconciliation is None:
            states.append(
                resolve_metric_state(
                    contract,
                    _statistics(
                        contract,
                        (),
                        capability_available=True,
                        source_complete=False,
                    ),
                    explanation_code="semantic_units_unavailable",
                    projection_version=METRIC_PROJECTION_V3_VERSION,
                )
            )
        else:
            states.append(
                _unit_state(
                    contract,
                    context,
                    reconciliation,
                    window,
                    projection_version=METRIC_PROJECTION_V3_VERSION,
                )
            )
    if any(
        state.projection_version != METRIC_PROJECTION_V3_VERSION for state in states
    ):
        raise AssertionError("r3 projection produced a foreign projection identity")
    projection = _issue_metric_state_projection(states, compatibility=False)
    if not isinstance(projection, LiveMetricStateProjectionV2):
        raise AssertionError("live projection issuer returned the wrong envelope")
    return projection


__all__ = [
    "METRIC_PROJECTION_V3_ALGORITHM_ID",
    "METRIC_PROJECTION_V3_ALGORITHM_VERSION",
    "METRIC_PROJECTION_V3_VERSION",
    "OPEN_LOOP_METRIC_KEY",
    "REASON_RUBRIC_OWNERSHIP_UNAVAILABLE",
    "objective_metric_state_v3",
    "open_loop_metric_state_v3",
    "project_metric_states_v3",
]
