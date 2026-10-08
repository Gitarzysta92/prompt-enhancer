"""V2 metric publication: a live projection wrapper and a V1 compatibility preview.

This module publishes the canonical live all-twenty measured projection as well
as a deliberately separate V1 compatibility preview.  The live projection is
safe to bind to a model-ensemble snapshot only after its semantic-unit and
objective-evidence inputs have been validated for that exact source window.

* ``publish_metric_states_v2`` wraps a genuine live V2 projection over persisted
  semantic-unit heads.  Newly sealed model-ensemble heads use this publication
  as their canonical measured layer.
* ``rehydrate_v1_compatibility_states`` reads an already persisted V1 analysis
  run and produces a read-only *compatibility preview*.  At most the reviewed
  compatible rubric rows carry a number; every other behavioural contract is
  withheld and every objective contract is unknown unless an authorized typed
  override is supplied.

Both paths produce all twenty contracts, in registry order, with a typed state, a
content-free guidance receipt, and an explicit implementation/readiness state so
a client can tell a live measurement from a compatibility projection from a
withheld one.  Nothing here consumes model-stage output, so an optional neural
stage that times out cannot change a single published value.

Fail-closed rules, all enforced by the contract at construction time:

* every published state and guidance receipt is re-checked field by field
  against ``metric_contract_v2`` — a forged authority, fingerprint, denominator
  basis, opportunity kind, or direction is rejected rather than published;
* a V1 row becomes a number only when every provenance field exactly matches the
  reviewed source-pack identity.  Any mismatch, any model/prompt/tokenizer
  provenance, and any orphan row yields ``unknown`` with one fixed reason;
* the five evidence-lane contracts are resolved only by the typed objective
  projection, so a stored conversational ratio can never ground a claim;
* guidance for an aggregate V1 row is method-level with no focus factor: a rubric
  numerator proves a count, never which factor was met.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum
import hashlib
import json
from types import MappingProxyType
from typing import Literal

from pydantic import Field, model_validator

from ...domain import DataTier, MetricSource, StrictModel
from ..persistence import (
    MetricValueState,
    SessionAnalysisResultRecord,
    SessionMetricAggregation,
    SessionMetricApplicability,
    SessionMetricDirection,
)
from .coaching_baselines import (
    COACHING_METRIC_ALGORITHM_ID,
    COACHING_METRIC_ALGORITHM_VERSION,
    COACHING_METRIC_DEFINITIONS,
    COACHING_METRIC_RUBRIC_VERSION,
)
from .metric_contract_v2 import (
    DenominatorBasis,
    EvidenceAuthority,
    METRIC_CONTRACTS_V2,
    METRIC_CONTRACT_REGISTRY_VERSION_V2,
    MetricContractV2,
    MetricValueStateV2,
    NoOpportunityOutcome,
    metric_contract_v2,
    metric_contract_v2_set_fingerprint,
)
from .metric_guidance import (
    METRIC_GUIDANCE_CONTRACT_VERSION,
    METRIC_GUIDANCE_TEMPLATE_CATALOG_VERSION,
    GuidanceBasis,
    GuidanceFactorEvidence,
    MetricGuidanceReceipt,
    ValueOrigin,
    build_metric_guidance,
)
from .metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION,
    METRIC_PROJECTION_V2_VERSION_7,
    METRIC_PROJECTION_V2_VERSION_8,
    LiveMetricStateProjectionV2,
    MetricProjectionV2Version,
    MetricStateProjectionV2,
    MetricStateV2,
    OpportunityStatistics,
    V1CompatibilityMetricStateProjectionV2,
    _issue_metric_state_projection,
    _metric_state_projection_is_compatibility,
    _metric_state_projection_is_issued,
    objective_metric_state,
    reviewed_requirement_plan_denominator_is_authoritative,
    resolve_metric_state,
)
from .objective_metric_projection import ObjectiveMetricOverride
from .text_contracts import TEXT_METRIC_SCHEMA_VERSION, MetricDirection


METRIC_PUBLICATION_V2_KEY = "metric.contract-v2.publication"
METRIC_PUBLICATION_V2_VERSION = 2
#: Identity of the one reviewed V1 source pack a compatibility row may come from.
V1_COMPATIBILITY_SOURCE_PACK = "coaching-observables-rubric-2"

#: Fixed, content-free reasons a stored V1 row cannot resolve a V2 contract.
REASON_RESULT_ABSENT = "metric_result_absent"
REASON_DENOMINATOR_NOT_OPPORTUNITY_OWNED = "v1_denominator_not_opportunity_owned"
REASON_PROVENANCE_INCOMPATIBLE = "v1_provenance_not_compatible"
REASON_RUBRIC_DENOMINATOR_MISMATCH = "rubric_denominator_mismatch"
REASON_RESULT_STATE_UNPUBLISHABLE = "stored_result_state_unpublishable"
#: Retained for readers of the previous version; provenance now covers this.
REASON_MODEL_ASSISTED_NOT_PUBLISHABLE = REASON_PROVENANCE_INCOMPATIBLE


class MetricPublicationSource(StrEnum):
    """Where the published states came from; never mixed within one bundle."""

    LIVE_PROJECTION = "live_projection"
    V1_COMPATIBILITY_PREVIEW = "v1_compatibility_preview"


class MetricImplementationState(StrEnum):
    """What a client may claim about one published metric today.

    This is the honesty dimension: it separates a live measurement from a
    read-only compatibility projection and from a value that was withheld.
    """

    LIVE_MEASURED = "live_measured"
    COMPATIBILITY_PROJECTED = "compatibility_projected"
    METHOD_ONLY_WITHHELD = "method_only_withheld"
    OBJECTIVE_CAPABILITY_MISSING = "objective_capability_missing"
    OBJECTIVE_EVIDENCE_UNRESOLVED = "objective_evidence_unresolved"
    PENDING = "pending"
    NO_OPPORTUNITY = "no_opportunity"
    ABSTAINED = "abstained"
    ERROR = "error"


class _CompatibilityProvenance(StrictModel):
    """The exact reviewed provenance identity a V1 row must match."""

    metric_version: int = Field(ge=1)
    metric_schema_version: int = Field(ge=1)
    unit: str
    source: MetricSource
    direction: SessionMetricDirection
    aggregation_method: SessionMetricAggregation
    evidence_data_tier: DataTier
    algorithm_id: str
    algorithm_version: str
    rubric_version: str


def _expected_provenance(metric_key: str) -> _CompatibilityProvenance | None:
    definition = next(
        (item for item in COACHING_METRIC_DEFINITIONS if item.key == metric_key),
        None,
    )
    if definition is None:
        return None
    return _CompatibilityProvenance(
        metric_version=definition.version,
        metric_schema_version=TEXT_METRIC_SCHEMA_VERSION,
        unit=definition.unit,
        source=MetricSource.DETERMINISTIC,
        direction=(
            SessionMetricDirection.HIGHER_IS_BETTER
            if definition.direction is MetricDirection.HIGHER_IS_BETTER
            else SessionMetricDirection.LOWER_IS_BETTER
        ),
        aggregation_method=SessionMetricAggregation.RATIO_OF_SUMS,
        evidence_data_tier=DataTier.REDACTED_CONTENT,
        algorithm_id=COACHING_METRIC_ALGORITHM_ID,
        algorithm_version=COACHING_METRIC_ALGORITHM_VERSION,
        rubric_version=COACHING_METRIC_RUBRIC_VERSION,
    )


_EXPECTED_PROVENANCE = MappingProxyType(
    {
        contract.metric_key: _expected_provenance(contract.metric_key)
        for contract in METRIC_CONTRACTS_V2
    }
)
if any(item is None for item in _EXPECTED_PROVENANCE.values()):
    raise RuntimeError("V1 compatibility provenance catalog is incomplete")


def v1_provenance_is_compatible(result: SessionAnalysisResultRecord) -> bool:
    """Exact-match gate over every provenance field a value depends on.

    A model, prompt, or tokenizer identity is disqualifying rather than merely
    noted: those rows are estimates from a different authority, and promoting one
    would relabel an uncalibrated inference as a deterministic observation.
    """

    expected = _EXPECTED_PROVENANCE.get(result.observation.key)
    if expected is None:
        return False
    if any(
        value is not None
        for value in (
            result.model_id,
            result.model_revision,
            result.model_license,
            result.tokenizer_id,
            result.prompt_version,
        )
    ):
        return False
    observation = result.observation
    return (
        observation.version == expected.metric_version
        and result.metric_schema_version == expected.metric_schema_version
        and observation.unit == expected.unit
        and observation.source is expected.source
        and result.direction is expected.direction
        and result.aggregation_method is expected.aggregation_method
        and result.evidence_data_tier is expected.evidence_data_tier
        and result.algorithm_id == expected.algorithm_id
        and result.algorithm_version == expected.algorithm_version
        and result.rubric_version == expected.rubric_version
        and result.rubric_version == V1_COMPATIBILITY_SOURCE_PACK
    )


def _validate_state_against_contract(state: MetricStateV2) -> MetricContractV2:
    """Re-derive the contract and reject any field a producer could have forged."""

    contract = metric_contract_v2(state.metric_key)
    if state.contract_version != contract.contract_version:
        raise ValueError("published state contract version does not match the registry")
    if state.contract_fingerprint != contract.fingerprint:
        raise ValueError("published state contract fingerprint is forged")
    if state.evidence_authority is not contract.evidence_authority:
        raise ValueError("published state evidence authority is forged")
    statistics = state.statistics
    if statistics.metric_key != state.metric_key:
        raise ValueError("published statistics belong to another metric")
    if statistics.denominator_basis is not contract.denominator_basis:
        raise ValueError("published state denominator basis is forged")
    if statistics.opportunity_unit_kind is not contract.opportunity_unit_kind:
        raise ValueError("published state opportunity unit kind is forged")
    if state.registry_version != METRIC_CONTRACT_REGISTRY_VERSION_V2:
        raise ValueError("published state registry version is forged")
    if (
        state.value_state is MetricValueStateV2.PENDING
        and contract.pending_policy.value == "immediate"
    ):
        raise ValueError("an immediate contract cannot publish a pending state")
    if (
        state.value_state is MetricValueStateV2.NOT_APPLICABLE
        and contract.no_opportunity_outcome is not NoOpportunityOutcome.NOT_APPLICABLE
    ):
        raise ValueError("this contract cannot publish a not-applicable state")
    return contract


def _validate_known_value_statistics(state: MetricStateV2) -> None:
    """A published number must be the sufficient statistics, not a claim.

    Without this a producer could publish a forged 3/3 beside an empty
    opportunity set, which is exactly the shape a masked zero takes.
    """

    statistics = state.statistics
    if state.value_state is not MetricValueStateV2.KNOWN:
        if state.numerator is not None or state.denominator is not None:
            raise ValueError("only a known state may publish a fraction")
        return
    if state.numerator is None or state.denominator is None:
        raise ValueError("a known state requires an exact fraction")
    if not statistics.capability_available:
        raise ValueError("a known value requires an available opportunity family")
    if not statistics.source_complete:
        raise ValueError("a known value requires a complete source view")
    if statistics.eligible_count == 0:
        raise ValueError("a known value requires at least one eligible opportunity")
    if state.denominator != statistics.eligible_count:
        raise ValueError("a known denominator must equal the eligible opportunities")
    if state.numerator != statistics.met_count:
        raise ValueError("a known numerator must equal the met opportunities")
    if statistics.pending_count or statistics.unknown_count:
        raise ValueError("a known value cannot leave an opportunity undetermined")
    if statistics.not_met_count != statistics.eligible_count - statistics.met_count:
        raise ValueError("known opportunity outcomes must partition the eligible set")
    ratio = statistics.met_count / statistics.eligible_count
    if (
        state.numeric_value is None
        or abs(state.numeric_value - ratio) > 1e-9
        or state.censoring_lower_bound != state.numeric_value
        or state.censoring_upper_bound != state.numeric_value
    ):
        raise ValueError("a known value must equal its exact resolved fraction")


def _validate_guidance_against_contract(
    guidance: MetricGuidanceReceipt,
    contract: MetricContractV2,
) -> None:
    definition = next(
        item
        for item in COACHING_METRIC_DEFINITIONS
        if item.key == contract.metric_key
    )
    if guidance.metric_contract_version != contract.contract_version:
        raise ValueError("published guidance contract version is forged")
    if guidance.metric_contract_fingerprint != contract.fingerprint:
        raise ValueError("published guidance contract fingerprint is forged")
    if guidance.evidence_authority is not contract.evidence_authority:
        raise ValueError("published guidance evidence authority is forged")
    if guidance.denominator_basis is not contract.denominator_basis:
        raise ValueError("published guidance denominator basis is forged")
    if guidance.metric_version != definition.version:
        raise ValueError("published guidance metric version is forged")
    if guidance.contract_factor_count != len(contract.factors):
        raise ValueError("published guidance factor count is forged")
    contract_factor_keys = {item.factor_key for item in contract.factors}
    if any(item not in contract_factor_keys for item in guidance.focus_factor_keys):
        raise ValueError("published guidance focus factor is outside the contract")
    if (
        guidance.value_origin is ValueOrigin.TYPED_OBJECTIVE
        and contract.evidence_authority is not EvidenceAuthority.OBJECTIVE_RECEIPT
    ):
        raise ValueError("only an objective contract may claim a typed origin")
    if guidance.registry_version != METRIC_CONTRACT_REGISTRY_VERSION_V2:
        raise ValueError("published guidance registry version is forged")


class PublishedMetricV2(StrictModel):
    """One projected state, its guidance, and what may be claimed about it."""

    state: MetricStateV2
    guidance: MetricGuidanceReceipt
    implementation_state: MetricImplementationState

    @model_validator(mode="after")
    def validate_pairing(self) -> PublishedMetricV2:
        if self.state.metric_key != self.guidance.metric_key:
            raise ValueError("published guidance belongs to another metric")
        if self.state.value_state is not self.guidance.value_state:
            raise ValueError("published guidance must restate the metric state")
        if self.state.numerator != self.guidance.numerator or (
            self.state.denominator != self.guidance.denominator
        ):
            raise ValueError("published guidance must restate the exact fraction")
        if (
            self.state.censoring_lower_bound != self.guidance.censoring_lower_bound
            or self.state.censoring_upper_bound != self.guidance.censoring_upper_bound
        ):
            raise ValueError("published guidance must restate the censoring bounds")
        contract = _validate_state_against_contract(self.state)
        _validate_guidance_against_contract(self.guidance, contract)
        _validate_known_value_statistics(self.state)
        known = self.state.value_state is MetricValueStateV2.KNOWN
        if known != (
            self.implementation_state
            in {
                MetricImplementationState.LIVE_MEASURED,
                MetricImplementationState.COMPATIBILITY_PROJECTED,
            }
        ):
            raise ValueError("only a known state may claim a measured implementation")
        if (
            self.implementation_state
            is MetricImplementationState.COMPATIBILITY_PROJECTED
            and self.state.evidence_authority is EvidenceAuthority.CONVERSATION
            and self.guidance.basis is not GuidanceBasis.METHOD_ONLY
        ):
            raise ValueError(
                "a behavioural compatibility projection is method-level guidance only"
            )
        expected_withheld = {
            MetricValueStateV2.PENDING: MetricImplementationState.PENDING,
            MetricValueStateV2.NOT_APPLICABLE: (
                MetricImplementationState.NO_OPPORTUNITY
            ),
            MetricValueStateV2.ABSTAINED: MetricImplementationState.ABSTAINED,
            MetricValueStateV2.EXECUTION_ERROR: MetricImplementationState.ERROR,
        }.get(self.state.value_state)
        if expected_withheld is not None and (
            self.implementation_state is not expected_withheld
        ):
            raise ValueError("implementation state must restate the metric state")
        if self.state.value_state is MetricValueStateV2.UNKNOWN and (
            self.implementation_state
            not in {
                MetricImplementationState.METHOD_ONLY_WITHHELD,
                MetricImplementationState.OBJECTIVE_CAPABILITY_MISSING,
                MetricImplementationState.OBJECTIVE_EVIDENCE_UNRESOLVED,
            }
        ):
            raise ValueError("an unknown state must name why it was withheld")
        return self


def _validate_r7_requirement_action_denominator(
    *,
    projection_version: MetricProjectionV2Version,
    metrics: Iterable[PublishedMetricV2],
) -> None:
    """Cross-bind the r7/r8 action denominator to reviewed r6-r8 requirements."""

    if projection_version not in {
        METRIC_PROJECTION_V2_VERSION_7,
        METRIC_PROJECTION_V2_VERSION_8,
    }:
        return
    states = {item.state.metric_key: item.state for item in metrics}
    decomposition = states.get("logic.decomposition_coverage")
    requirement_action = states.get("logic.requirement_action_traceability")
    if decomposition is None or requirement_action is None:
        return
    expected_eligible = (
        decomposition.statistics.eligible_count
        if reviewed_requirement_plan_denominator_is_authoritative(decomposition)
        else 0
    )
    if requirement_action.statistics.eligible_count != expected_eligible:
        raise ValueError(
            "r7/r8 requirement-action eligibility must equal authoritative reviewed requirements"
        )


class MetricPublicationV2(StrictModel):
    """A complete twenty-metric publication with no absent key and no zero fill."""

    publication_key: Literal[METRIC_PUBLICATION_V2_KEY] = METRIC_PUBLICATION_V2_KEY
    publication_version: int = Field(
        default=METRIC_PUBLICATION_V2_VERSION, ge=1
    )
    registry_version: Literal[METRIC_CONTRACT_REGISTRY_VERSION_V2] = (
        METRIC_CONTRACT_REGISTRY_VERSION_V2
    )
    contract_set_fingerprint: str
    #: Always the identity of the states themselves, never a caller argument:
    #: a rehydrated historical bundle must keep the producer identity it was
    #: sealed with instead of being relabelled as the current one.
    projection_version: MetricProjectionV2Version
    guidance_contract_version: Literal[METRIC_GUIDANCE_CONTRACT_VERSION] = (
        METRIC_GUIDANCE_CONTRACT_VERSION
    )
    guidance_template_catalog_version: Literal[
        METRIC_GUIDANCE_TEMPLATE_CATALOG_VERSION
    ] = METRIC_GUIDANCE_TEMPLATE_CATALOG_VERSION
    source: MetricPublicationSource
    #: A live producer is canonical for the measured layer of its exact bound
    #: snapshot.  The V1 compatibility adapter can never claim this flag.
    canonical_live_snapshot: bool
    model_stage_consumed: Literal[False] = False
    compatibility_preview: bool
    metrics: tuple[PublishedMetricV2, ...] = Field(
        min_length=len(METRIC_CONTRACTS_V2), max_length=len(METRIC_CONTRACTS_V2)
    )
    known_count: int = Field(ge=0)
    pending_count: int = Field(ge=0)
    unknown_count: int = Field(ge=0)
    not_applicable_count: int = Field(ge=0)
    abstained_count: int = Field(ge=0)
    execution_error_count: int = Field(ge=0)
    objective_measured_count: int = Field(ge=0)
    product_metric_eligible: Literal[False] = False

    @model_validator(mode="after")
    def validate_publication(self) -> MetricPublicationV2:
        expected = tuple(item.metric_key for item in METRIC_CONTRACTS_V2)
        if tuple(item.state.metric_key for item in self.metrics) != expected:
            raise ValueError("a publication must list every V2 metric in registry order")
        if self.contract_set_fingerprint != metric_contract_v2_set_fingerprint():
            raise ValueError("publication contract-set fingerprint is stale")
        if any(
            item.state.projection_version != self.projection_version
            for item in self.metrics
        ):
            raise ValueError(
                "a publication must restate the projection identity of its states"
            )
        _validate_r7_requirement_action_denominator(
            projection_version=self.projection_version,
            metrics=self.metrics,
        )
        if self.compatibility_preview != (
            self.source is MetricPublicationSource.V1_COMPATIBILITY_PREVIEW
        ):
            raise ValueError("compatibility preview flag must match the source")
        if self.canonical_live_snapshot != (
            self.source is MetricPublicationSource.LIVE_PROJECTION
        ):
            raise ValueError("canonical snapshot flag must match the live producer")
        counts = {
            MetricValueStateV2.KNOWN: self.known_count,
            MetricValueStateV2.PENDING: self.pending_count,
            MetricValueStateV2.UNKNOWN: self.unknown_count,
            MetricValueStateV2.NOT_APPLICABLE: self.not_applicable_count,
            MetricValueStateV2.ABSTAINED: self.abstained_count,
            MetricValueStateV2.EXECUTION_ERROR: self.execution_error_count,
        }
        for value_state, declared in counts.items():
            observed = sum(
                item.state.value_state is value_state for item in self.metrics
            )
            if observed != declared:
                raise ValueError("publication state counts are inconsistent")
        if sum(counts.values()) != len(METRIC_CONTRACTS_V2):
            raise ValueError("publication states must partition the twenty metrics")
        objective_known = sum(
            1
            for item in self.metrics
            if item.state.evidence_authority is EvidenceAuthority.OBJECTIVE_RECEIPT
            and item.state.value_state is MetricValueStateV2.KNOWN
        )
        if objective_known != self.objective_measured_count:
            raise ValueError("publication objective counts are inconsistent")
        # Objective precedence, restated at the publication boundary so a
        # future producer cannot resolve an evidence-lane metric from prose.
        if any(
            item.state.evidence_authority is EvidenceAuthority.OBJECTIVE_RECEIPT
            and item.state.value_state is MetricValueStateV2.KNOWN
            and item.state.statistics.denominator_basis
            is not DenominatorBasis.OBJECTIVE_OPPORTUNITIES
            for item in self.metrics
        ):
            raise ValueError(
                "objective contracts cannot be published from conversational material"
            )
        if self.compatibility_preview and any(
            item.implementation_state is MetricImplementationState.LIVE_MEASURED
            for item in self.metrics
        ):
            raise ValueError("a compatibility preview cannot claim a live measurement")
        for item in self.metrics:
            # Guidance is not user-constructible: rederive the whole receipt and
            # the implementation state from the validated state and the source.
            if item.guidance != _expected_guidance(item.state, source=self.source):
                raise ValueError("published guidance is not the derived receipt")
            if item.implementation_state is not _implementation_state(
                item.state, source=self.source
            ):
                raise ValueError("published implementation state is not derived")
            if self.compatibility_preview and (
                item.guidance.value_origin is ValueOrigin.NEURAL_UNCALIBRATED
                or item.guidance.basis is GuidanceBasis.EXPERIMENTAL
            ):
                raise ValueError(
                    "a compatibility preview consumes no model stage output"
                )
            if item.guidance.focus_factor_keys or (
                item.guidance.factor_evidence
                is GuidanceFactorEvidence.PER_FACTOR_MEASURED
            ):
                raise ValueError(
                    "no producer measures per-factor statistics for this publication"
                )
        return self

    def implementation_state_counts(self) -> dict[MetricImplementationState, int]:
        """Readiness partition over exactly the twenty published metrics."""

        return {
            state: sum(
                item.implementation_state is state for item in self.metrics
            )
            for state in MetricImplementationState
        }


def metric_publication_v2_fingerprint(publication: MetricPublicationV2) -> str:
    """Content commitment over one whole publication, in registry-free order.

    This is the exact value a persistence seal stores, so a reader can restate
    it without recomputing it differently.  Metrics are sorted by key rather
    than left in registry order so the commitment is over the content, not over
    an accidental iteration order.
    """

    payload = publication.model_dump(mode="json")
    payload["metrics"] = sorted(
        payload["metrics"], key=lambda item: item["state"]["metric_key"]
    )
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _derived_factor_evidence(
    state: MetricStateV2,
    *,
    source: MetricPublicationSource,
) -> GuidanceFactorEvidence:
    """Factor evidence is a property of the producer, not a caller argument.

    The aggregate compatibility publisher can never prove which factor was met,
    so it may only ever downgrade to ``AGGREGATE_ONLY``.  There is deliberately
    no path here that returns ``PER_FACTOR_MEASURED``: no producer in this tree
    measures per-factor statistics, and inventing one would be a fake API.
    """

    if (
        source is MetricPublicationSource.V1_COMPATIBILITY_PREVIEW
        and state.value_state is MetricValueStateV2.KNOWN
        and state.evidence_authority is EvidenceAuthority.CONVERSATION
    ):
        return GuidanceFactorEvidence.AGGREGATE_ONLY
    return GuidanceFactorEvidence.NOT_OBSERVED


def _expected_guidance(
    state: MetricStateV2,
    *,
    source: MetricPublicationSource,
) -> MetricGuidanceReceipt:
    """Rederive the one guidance receipt this state and source may carry."""

    return build_metric_guidance(
        state,
        factor_evidence=_derived_factor_evidence(state, source=source),
    )


def _implementation_state(
    state: MetricStateV2,
    *,
    source: MetricPublicationSource,
) -> MetricImplementationState:
    if state.value_state is MetricValueStateV2.KNOWN:
        return (
            MetricImplementationState.LIVE_MEASURED
            if source is MetricPublicationSource.LIVE_PROJECTION
            else MetricImplementationState.COMPATIBILITY_PROJECTED
        )
    if state.value_state is MetricValueStateV2.PENDING:
        return MetricImplementationState.PENDING
    if state.value_state is MetricValueStateV2.NOT_APPLICABLE:
        return MetricImplementationState.NO_OPPORTUNITY
    if state.value_state is MetricValueStateV2.ABSTAINED:
        return MetricImplementationState.ABSTAINED
    if state.value_state is MetricValueStateV2.EXECUTION_ERROR:
        return MetricImplementationState.ERROR
    if state.evidence_authority is EvidenceAuthority.OBJECTIVE_RECEIPT:
        if state.statistics.capability_available:
            # Authorized evidence exists but does not close the opportunity
            # set.  Projection r3 may deliberately withhold the cardinality
            # when the authoritative set exceeds the bounded receipt, so an
            # eligible count of zero is not itself a capability failure.
            return MetricImplementationState.OBJECTIVE_EVIDENCE_UNRESOLVED
        return MetricImplementationState.OBJECTIVE_CAPABILITY_MISSING
    return MetricImplementationState.METHOD_ONLY_WITHHELD


def publish_metric_states_v2(
    projection: MetricStateProjectionV2,
) -> MetricPublicationV2:
    """Pair every producer-issued projection state with its guidance receipt.

    Raw tuples and JSON-reconstructed states are deliberately insufficient:
    state data is not publication authority.  The live projector and reviewed
    compatibility adapter issue distinct opaque envelopes, and the source is
    derived from that envelope rather than supplied by the caller.
    """

    if not _metric_state_projection_is_issued(projection):
        raise TypeError("publication requires a producer-issued metric projection")
    compatibility = _metric_state_projection_is_compatibility(projection)
    if compatibility and type(projection) is V1CompatibilityMetricStateProjectionV2:
        source = MetricPublicationSource.V1_COMPATIBILITY_PREVIEW
    elif not compatibility and type(projection) is LiveMetricStateProjectionV2:
        source = MetricPublicationSource.LIVE_PROJECTION
    else:
        raise TypeError("metric projection class does not match its producer")
    published = tuple(
        PublishedMetricV2(
            state=state,
            guidance=_expected_guidance(state, source=source),
            implementation_state=_implementation_state(state, source=source),
        )
        for state in projection
    )

    def _count(value_state: MetricValueStateV2) -> int:
        return sum(item.state.value_state is value_state for item in published)

    projection_versions = {item.state.projection_version for item in published}
    if len(projection_versions) != 1:
        raise ValueError("a publication cannot mix producer projection identities")

    return MetricPublicationV2(
        contract_set_fingerprint=metric_contract_v2_set_fingerprint(),
        projection_version=projection_versions.pop(),
        source=source,
        canonical_live_snapshot=(
            source is MetricPublicationSource.LIVE_PROJECTION
        ),
        compatibility_preview=(
            source is MetricPublicationSource.V1_COMPATIBILITY_PREVIEW
        ),
        metrics=published,
        known_count=_count(MetricValueStateV2.KNOWN),
        pending_count=_count(MetricValueStateV2.PENDING),
        unknown_count=_count(MetricValueStateV2.UNKNOWN),
        not_applicable_count=_count(MetricValueStateV2.NOT_APPLICABLE),
        abstained_count=_count(MetricValueStateV2.ABSTAINED),
        execution_error_count=_count(MetricValueStateV2.EXECUTION_ERROR),
        objective_measured_count=sum(
            1
            for item in published
            if item.state.evidence_authority is EvidenceAuthority.OBJECTIVE_RECEIPT
            and item.state.value_state is MetricValueStateV2.KNOWN
        ),
    )


def publish_v1_compatibility_preview(
    results: Iterable[SessionAnalysisResultRecord],
    *,
    objective_overrides: Mapping[str, ObjectiveMetricOverride] | None = None,
) -> MetricPublicationV2:
    """Build the read-only compatibility preview for one stored V1 run."""

    states = rehydrate_v1_compatibility_states(
        results, objective_overrides=objective_overrides
    )
    # An aggregate rubric fraction proves a count, never a factor identity; the
    # downgrade to method-level guidance is derived, not requested.
    return publish_metric_states_v2(states)


def _empty_statistics(
    contract: MetricContractV2,
    *,
    capability_available: bool,
    source_complete: bool,
) -> OpportunityStatistics:
    return OpportunityStatistics(
        metric_key=contract.metric_key,
        denominator_basis=contract.denominator_basis,
        opportunity_unit_kind=contract.opportunity_unit_kind,
        capability_available=capability_available,
        source_complete=source_complete,
        eligible_count=0,
    )


def _withheld(contract: MetricContractV2, reason_code: str) -> MetricStateV2:
    """Publish an unknown whose reason names the missing capability, not zero."""

    return resolve_metric_state(
        contract,
        _empty_statistics(
            contract,
            capability_available=False,
            source_complete=False,
        ),
        explanation_code=reason_code,
        unavailable_code=reason_code,
    )


def _rubric_statistics(
    contract: MetricContractV2,
    *,
    met: int,
) -> OpportunityStatistics:
    factor_count = len(contract.factors)
    return OpportunityStatistics(
        metric_key=contract.metric_key,
        denominator_basis=contract.denominator_basis,
        opportunity_unit_kind=contract.opportunity_unit_kind,
        capability_available=True,
        source_complete=True,
        eligible_count=factor_count,
        met_count=met,
        not_met_count=factor_count - met,
    )


def _compatibility_rubric_state(
    contract: MetricContractV2,
    result: SessionAnalysisResultRecord,
) -> MetricStateV2:
    factor_count = len(contract.factors)
    numerator = result.fraction_numerator
    denominator = result.fraction_denominator
    if (
        numerator is None
        or denominator is None
        or denominator != factor_count
        or numerator > factor_count
    ):
        return _withheld(contract, REASON_RUBRIC_DENOMINATOR_MISMATCH)
    ratio = numerator / denominator
    return MetricStateV2(
        metric_key=contract.metric_key,
        contract_version=contract.contract_version,
        contract_fingerprint=contract.fingerprint,
        evidence_authority=contract.evidence_authority,
        value_state=MetricValueStateV2.KNOWN,
        explanation_code=result.explanation_code,
        numerator=numerator,
        denominator=denominator,
        numeric_value=ratio,
        censoring_lower_bound=ratio,
        censoring_upper_bound=ratio,
        statistics=_rubric_statistics(contract, met=numerator),
        projection_version=METRIC_PROJECTION_V2_VERSION,
    )


def _compatibility_state(
    contract: MetricContractV2,
    result: SessionAnalysisResultRecord | None,
) -> MetricStateV2:
    if result is None:
        return _withheld(contract, REASON_RESULT_ABSENT)
    # Provenance is checked before the value state so an incompatible row can
    # never be promoted, downgraded, or reinterpreted as a model-stage outcome.
    if not v1_provenance_is_compatible(result):
        return _withheld(contract, REASON_PROVENANCE_INCOMPATIBLE)
    if result.value_state is MetricValueState.EXECUTION_ERROR:
        return MetricStateV2(
            metric_key=contract.metric_key,
            contract_version=contract.contract_version,
            contract_fingerprint=contract.fingerprint,
            evidence_authority=contract.evidence_authority,
            value_state=MetricValueStateV2.EXECUTION_ERROR,
            explanation_code=result.error_code or result.explanation_code,
            statistics=_empty_statistics(
                contract,
                capability_available=False,
                source_complete=False,
            ),
            projection_version=METRIC_PROJECTION_V2_VERSION,
        )
    if contract.denominator_basis is not DenominatorBasis.RUBRIC_FACTORS:
        return _withheld(contract, REASON_DENOMINATOR_NOT_OPPORTUNITY_OWNED)
    if result.value_state is MetricValueState.KNOWN:
        return _compatibility_rubric_state(contract, result)
    if result.value_state is MetricValueState.ABSTAINED:
        return MetricStateV2(
            metric_key=contract.metric_key,
            contract_version=contract.contract_version,
            contract_fingerprint=contract.fingerprint,
            evidence_authority=contract.evidence_authority,
            value_state=MetricValueStateV2.ABSTAINED,
            explanation_code=result.explanation_code,
            statistics=_empty_statistics(
                contract,
                capability_available=True,
                source_complete=True,
            ),
            projection_version=METRIC_PROJECTION_V2_VERSION,
        )
    if (
        result.value_state is MetricValueState.NOT_APPLICABLE
        and result.applicability is SessionMetricApplicability.NOT_APPLICABLE
        and contract.no_opportunity_outcome is NoOpportunityOutcome.NOT_APPLICABLE
    ):
        return resolve_metric_state(
            contract,
            _empty_statistics(
                contract,
                capability_available=True,
                source_complete=True,
            ),
            explanation_code=result.explanation_code,
        )
    if result.value_state is MetricValueState.UNKNOWN:
        return _withheld(contract, result.explanation_code)
    return _withheld(contract, REASON_RESULT_STATE_UNPUBLISHABLE)


def rehydrate_v1_compatibility_states(
    results: Iterable[SessionAnalysisResultRecord],
    *,
    objective_overrides: Mapping[str, ObjectiveMetricOverride] | None = None,
) -> V1CompatibilityMetricStateProjectionV2:
    """Project one stored V1 run onto the V2 registry, fail-closed.

    ``objective_overrides`` is the only way an evidence-lane contract can become
    known.  Passing none keeps all five fail-closed, which is the correct state
    for a run whose typed evidence was never captured.
    """

    by_key: dict[str, SessionAnalysisResultRecord] = {}
    duplicated: set[str] = set()
    for result in results:
        key = result.observation.key
        if key in by_key:
            duplicated.add(key)
            continue
        by_key[key] = result
    overrides = dict(objective_overrides or {})
    states: list[MetricStateV2] = []
    for contract in METRIC_CONTRACTS_V2:
        if contract.denominator_basis is DenominatorBasis.OBJECTIVE_OPPORTUNITIES:
            states.append(
                objective_metric_state(
                    contract,
                    overrides.get(contract.metric_key),
                )
            )
            continue
        if contract.metric_key in duplicated:
            # Two rows for one metric make the exact fraction ambiguous.
            states.append(_withheld(contract, REASON_RESULT_STATE_UNPUBLISHABLE))
            continue
        states.append(_compatibility_state(contract, by_key.get(contract.metric_key)))
    projection = _issue_metric_state_projection(states, compatibility=True)
    if not isinstance(projection, V1CompatibilityMetricStateProjectionV2):
        raise AssertionError("compatibility issuer returned the wrong envelope")
    return projection


__all__ = [
    "METRIC_PUBLICATION_V2_KEY",
    "METRIC_PUBLICATION_V2_VERSION",
    "REASON_DENOMINATOR_NOT_OPPORTUNITY_OWNED",
    "REASON_MODEL_ASSISTED_NOT_PUBLISHABLE",
    "REASON_PROVENANCE_INCOMPATIBLE",
    "REASON_RESULT_ABSENT",
    "REASON_RESULT_STATE_UNPUBLISHABLE",
    "REASON_RUBRIC_DENOMINATOR_MISMATCH",
    "V1_COMPATIBILITY_SOURCE_PACK",
    "MetricImplementationState",
    "MetricPublicationSource",
    "MetricPublicationV2",
    "PublishedMetricV2",
    "metric_publication_v2_fingerprint",
    "publish_metric_states_v2",
    "publish_v1_compatibility_preview",
    "rehydrate_v1_compatibility_states",
    "v1_provenance_is_compatible",
]
