"""Versioned, content-free guidance contract for the Metric Contract V2 seam.

Both the dashboard and the desktop overlay need to tell a user what a metric
state means and what to try next.  Until now that decision logic lived only in
the client, which meant two surfaces could disagree and neither could be tested
against the metric contract that produced the state.

This module publishes the decision *identity* rather than its wording:

* ``role``, ``audience`` and ``basis`` are closed enums;
* ``reason_code`` is the projection's own content-free explanation code;
* the contract's complete factor list is catalog metadata; session advice may
  name at most two focus factors, and only when per-factor sufficient statistics
  were measured;
* diagnosis, action and verification advice is referenced by deterministic
  template identity, so the rendered sentence stays in the presentation layer
  and no session prose is ever produced, transported, or persisted here.

Measurement authority and calibration status are separate axes.  A deterministic
local rule and a typed objective receipt are both *measured* observations and
differ in ``evidence_authority``; only an uncalibrated neural estimate may claim
the ``experimental`` basis.  A known value whose factor attribution is unproven is
``method-only``.  Only a ``known`` state carries a fraction, and missing
capability, a right-censored opportunity, and an empty opportunity set each keep
their own state rather than being rendered as a zero.
"""

from __future__ import annotations

from enum import StrEnum
import re
from types import MappingProxyType
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ...domain import StrictModel
from .coaching_baselines import COACHING_METRIC_DEFINITIONS
from .metric_contract_v2 import (
    DenominatorBasis,
    EvidenceAuthority,
    METRIC_CONTRACT_REGISTRY_VERSION_V2,
    METRIC_CONTRACTS_V2,
    MetricContractV2,
    MetricValueStateV2,
    metric_contract_v2,
)
from .metric_projection_v2 import MetricStateV2
from .text_contracts import MetricDirection


METRIC_GUIDANCE_CONTRACT_VERSION = "metric-guidance-contract-v1"
METRIC_GUIDANCE_SCHEMA_VERSION = 1
#: Template identities are catalog data, not session data.  A presentation
#: surface resolves an identity to reviewed wording; the identity is the API.
METRIC_GUIDANCE_TEMPLATE_CATALOG_VERSION = "metric-guidance-templates-v1"
METRIC_GUIDANCE_TEMPLATE_VERSION = 1
#: Oriented value at or above which a known state is advice to *retain* the
#: observed practice rather than to change it.  Deliberately equal to the
#: reviewed coaching strength floor so the two surfaces cannot drift apart.
METRIC_GUIDANCE_RETAIN_FLOOR = 0.75
#: A contract's complete factor list is catalog metadata.  Session advice may
#: name at most two focus factors, and only when per-factor sufficient
#: statistics were actually measured for that opportunity.
MAX_GUIDANCE_FOCUS_FACTOR_KEYS = 2
MAX_GUIDANCE_FACTOR_KEYS = 8

_SAFE_CODE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
_PSEUDONYM_SHAPE = re.compile(r"^[a-f0-9]{64}$")


def _safe_code(value: str) -> str:
    """Reject prose, identifiers, and anything digest-shaped.

    The pseudonym check is the privacy canary: a keyed digest is content-free
    but still a per-installation identifier, so it must never reach a guidance
    field that a client may log or display.
    """

    if _SAFE_CODE.fullmatch(value) is None or _PSEUDONYM_SHAPE.fullmatch(value):
        raise ValueError("metric guidance values must be content-free codes")
    return value


class GuidanceRole(StrEnum):
    """What kind of signal the metric is; never a judgement about a person."""

    SPECIFICATION_SIGNAL = "specification_signal"
    COLLABORATION_SIGNAL = "collaboration_signal"
    TRACEABILITY_SIGNAL = "traceability_signal"
    OUTCOME_EVIDENCE = "outcome_evidence"
    FRICTION_SIGNAL = "friction_signal"


class GuidanceAudience(StrEnum):
    """Who can act on the guidance without inventing evidence."""

    USER = "user"
    AGENT = "agent"
    WORKFLOW = "workflow"
    TOOLING = "tooling"


class ValueOrigin(StrEnum):
    """What produced a value, kept separate from its calibration status.

    A deterministic local rule and a typed objective receipt are both *measured*
    observations; they differ in authority, not in whether they were measured.
    Only a neural estimate is uncalibrated, and it is the sole origin allowed to
    claim the experimental basis.
    """

    NONE = "none"
    DETERMINISTIC_LOCAL = "deterministic_local"
    TYPED_OBJECTIVE = "typed_objective"
    NEURAL_UNCALIBRATED = "neural_uncalibrated"


class GuidanceFactorEvidence(StrEnum):
    """Whether per-factor sufficient statistics exist for this opportunity.

    ``AGGREGATE_ONLY`` means a fraction is known but which factors were met is
    not: a rubric numerator proves a count, never an identity.  Advice must then
    stay method-level rather than naming a factor the evidence cannot support.
    """

    NOT_OBSERVED = "not_observed"
    AGGREGATE_ONLY = "aggregate_only"
    PER_FACTOR_MEASURED = "per_factor_measured"


class GuidanceBasis(StrEnum):
    """How far the guidance may go, given origin and factor evidence.

    ``MEASURED`` is a measured local observation, deterministic or objective.
    ``EXPERIMENTAL`` is reserved for an uncalibrated neural estimate.
    ``METHOD_ONLY`` covers a known value whose factor attribution is unproven
    and any failed stage.  ``READINESS`` covers every non-value state.
    """

    MEASURED = "measured"
    EXPERIMENTAL = "experimental"
    READINESS = "readiness"
    METHOD_ONLY = "method-only"


class GuidanceStateClass(StrEnum):
    """Deterministic bridge from a typed metric state to a template family."""

    KNOWN_RETAIN = "known_retain"
    KNOWN_IMPROVE = "known_improve"
    PENDING_CLOSURE = "pending_closure"
    OBJECTIVE_EVIDENCE_MISSING = "objective_evidence_missing"
    OBJECTIVE_EVIDENCE_UNRESOLVED = "objective_evidence_unresolved"
    EVIDENCE_UNRESOLVED = "evidence_unresolved"
    NO_OPPORTUNITY = "no_opportunity"
    EVIDENCE_COVERAGE_ABSTAINED = "evidence_coverage_abstained"
    ANALYSIS_FAILED = "analysis_failed"


_ROLE_BY_DIMENSION = {
    "prompt": GuidanceRole.SPECIFICATION_SIGNAL,
    "collaboration": GuidanceRole.COLLABORATION_SIGNAL,
    "logic": GuidanceRole.TRACEABILITY_SIGNAL,
    "outcome": GuidanceRole.OUTCOME_EVIDENCE,
}
#: A risk-direction metric is friction, not a collaboration achievement.
_FRICTION_METRIC_KEYS = frozenset({"collaboration.rework_candidate_rate"})

#: Generic action and verification families.  A readiness or failure state must
#: not borrow the metric-specific improvement template: there is no measured
#: value to improve, and implying one would read as a masked zero.
_GENERIC_TEMPLATES = MappingProxyType(
    {
        GuidanceStateClass.PENDING_CLOSURE: (
            "action.await_opportunity_closure",
            "verification.await_opportunity_closure",
        ),
        GuidanceStateClass.OBJECTIVE_EVIDENCE_MISSING: (
            "action.collect_objective_receipt",
            "verification.objective_receipt_scope",
        ),
        # A receipt already exists but does not resolve every opportunity, so
        # asking for one to be collected would be false advice.
        GuidanceStateClass.OBJECTIVE_EVIDENCE_UNRESOLVED: (
            "action.resolve_objective_evidence",
            "verification.objective_evidence_completeness",
        ),
        GuidanceStateClass.EVIDENCE_UNRESOLVED: (
            "action.hold_state_unknown",
            "verification.review_opportunity_evidence",
        ),
        GuidanceStateClass.NO_OPPORTUNITY: (
            "action.no_change_required",
            "verification.reassess_on_new_opportunity",
        ),
        GuidanceStateClass.EVIDENCE_COVERAGE_ABSTAINED: (
            "action.review_evidence_coverage",
            "verification.review_evidence_coverage",
        ),
        GuidanceStateClass.ANALYSIS_FAILED: (
            "action.repair_local_analysis_stage",
            "verification.fresh_sealed_receipt",
        ),
    }
)
_METRIC_ACTION_PREFIX = MappingProxyType(
    {
        GuidanceStateClass.KNOWN_RETAIN: "action.retain",
        GuidanceStateClass.KNOWN_IMPROVE: "action.improve",
    }
)

_DEFINITION_BY_KEY = MappingProxyType(
    {item.key: item for item in COACHING_METRIC_DEFINITIONS}
)


def _template(*parts: str) -> str:
    return _safe_code(f"{'.'.join(parts)}.v{METRIC_GUIDANCE_TEMPLATE_VERSION}")


def metric_guidance_role(metric_key: str) -> GuidanceRole:
    definition = _DEFINITION_BY_KEY.get(metric_key)
    if definition is None:
        raise ValueError("metric is outside the guidance catalog")
    if metric_key in _FRICTION_METRIC_KEYS:
        return GuidanceRole.FRICTION_SIGNAL
    return _ROLE_BY_DIMENSION[definition.dimension]


def metric_guidance_audience(contract: MetricContractV2) -> GuidanceAudience:
    """Route by evidence authority first; prose cannot satisfy a receipt.

    An objective contract is addressed to tooling because no user or agent
    wording can resolve it.  The remaining contracts follow the metric family
    the workspace already groups them by.
    """

    if contract.evidence_authority is EvidenceAuthority.OBJECTIVE_RECEIPT:
        return GuidanceAudience.TOOLING
    if contract.metric_key.startswith("outcome."):
        return GuidanceAudience.TOOLING
    if contract.metric_key.startswith("prompt."):
        return GuidanceAudience.USER
    if contract.metric_key.startswith("collaboration."):
        return GuidanceAudience.WORKFLOW
    return GuidanceAudience.AGENT


class MetricGuidanceTemplateSet(StrictModel):
    """The three template identities a client renders for one state class."""

    state_class: GuidanceStateClass
    diagnosis_template_id: str
    action_template_id: str
    verification_template_id: str

    _validate_codes = field_validator(
        "diagnosis_template_id",
        "action_template_id",
        "verification_template_id",
    )(_safe_code)


class MetricGuidanceCatalogEntry(StrictModel):
    """Static, session-free guidance identity for one V2 metric contract."""

    metric_key: str
    metric_version: int = Field(ge=1)
    registry_version: Literal[METRIC_CONTRACT_REGISTRY_VERSION_V2] = (
        METRIC_CONTRACT_REGISTRY_VERSION_V2
    )
    contract_version: str
    contract_fingerprint: str
    denominator_basis: DenominatorBasis
    evidence_authority: EvidenceAuthority
    direction: MetricDirection
    role: GuidanceRole
    audience: GuidanceAudience
    contract_factor_keys: tuple[str, ...] = Field(
        min_length=1, max_length=MAX_GUIDANCE_FACTOR_KEYS
    )
    templates: tuple[MetricGuidanceTemplateSet, ...] = Field(
        min_length=len(GuidanceStateClass), max_length=len(GuidanceStateClass)
    )

    _validate_metric_key = field_validator("metric_key")(_safe_code)

    @field_validator("contract_version")
    @classmethod
    def validate_contract_version(cls, value: str) -> str:
        return _safe_code(value)

    @field_validator("contract_fingerprint")
    @classmethod
    def validate_fingerprint(cls, value: str) -> str:
        if _PSEUDONYM_SHAPE.fullmatch(value) is None:
            raise ValueError("contract fingerprint must be lowercase SHA-256")
        return value

    @field_validator("contract_factor_keys")
    @classmethod
    def validate_factor_keys(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("guidance factor keys cannot repeat")
        return tuple(_safe_code(value) for value in values)

    @model_validator(mode="after")
    def validate_template_coverage(self) -> MetricGuidanceCatalogEntry:
        classes = tuple(item.state_class for item in self.templates)
        if set(classes) != set(GuidanceStateClass):
            raise ValueError("guidance templates must cover every state class")
        return self


class MetricGuidanceReceipt(StrictModel):
    """One content-free guidance decision for one projected metric state.

    Every field is an enum, an integer, a bounded ratio, or a reviewed code.
    There is no field capable of carrying transcript text, a rendered sentence,
    a path, or a provider identifier.
    """

    schema_version: Literal[METRIC_GUIDANCE_SCHEMA_VERSION] = (
        METRIC_GUIDANCE_SCHEMA_VERSION
    )
    contract_version: Literal[METRIC_GUIDANCE_CONTRACT_VERSION] = (
        METRIC_GUIDANCE_CONTRACT_VERSION
    )
    template_catalog_version: Literal[METRIC_GUIDANCE_TEMPLATE_CATALOG_VERSION] = (
        METRIC_GUIDANCE_TEMPLATE_CATALOG_VERSION
    )
    template_version: int = Field(
        default=METRIC_GUIDANCE_TEMPLATE_VERSION, ge=1
    )
    metric_key: str
    metric_version: int = Field(ge=1)
    registry_version: Literal[METRIC_CONTRACT_REGISTRY_VERSION_V2] = (
        METRIC_CONTRACT_REGISTRY_VERSION_V2
    )
    metric_contract_version: str
    metric_contract_fingerprint: str
    value_state: MetricValueStateV2
    denominator_basis: DenominatorBasis
    evidence_authority: EvidenceAuthority
    role: GuidanceRole
    audience: GuidanceAudience
    basis: GuidanceBasis
    value_origin: ValueOrigin
    factor_evidence: GuidanceFactorEvidence
    state_class: GuidanceStateClass
    reason_code: str
    contract_factor_count: int = Field(ge=1, le=MAX_GUIDANCE_FACTOR_KEYS)
    focus_factor_keys: tuple[str, ...] = Field(
        default=(), max_length=MAX_GUIDANCE_FOCUS_FACTOR_KEYS
    )
    diagnosis_template_id: str
    action_template_id: str
    verification_template_id: str
    eligible_count: int = Field(ge=0, le=1_000_000)
    met_count: int = Field(ge=0, le=1_000_000)
    not_met_count: int = Field(ge=0, le=1_000_000)
    pending_count: int = Field(ge=0, le=1_000_000)
    unknown_count: int = Field(ge=0, le=1_000_000)
    numerator: int | None = Field(default=None, ge=0, le=1_000_000)
    denominator: int | None = Field(default=None, ge=1, le=1_000_000)
    censoring_lower_bound: float | None = Field(default=None, ge=0, le=1)
    censoring_upper_bound: float | None = Field(default=None, ge=0, le=1)
    product_metric_eligible: Literal[False] = False

    _validate_codes = field_validator(
        "metric_key",
        "metric_contract_version",
        "reason_code",
        "diagnosis_template_id",
        "action_template_id",
        "verification_template_id",
    )(_safe_code)

    @field_validator("metric_contract_fingerprint")
    @classmethod
    def validate_fingerprint(cls, value: str) -> str:
        if _PSEUDONYM_SHAPE.fullmatch(value) is None:
            raise ValueError("contract fingerprint must be lowercase SHA-256")
        return value

    @field_validator("focus_factor_keys")
    @classmethod
    def validate_focus_factor_keys(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("guidance focus factor keys cannot repeat")
        return tuple(_safe_code(value) for value in values)

    @model_validator(mode="after")
    def validate_guidance(self) -> MetricGuidanceReceipt:
        counts = (
            self.met_count
            + self.not_met_count
            + self.pending_count
            + self.unknown_count
        )
        if counts != self.eligible_count:
            raise ValueError("guidance counts must partition the eligible set")
        known = self.value_state is MetricValueStateV2.KNOWN
        if known != (self.numerator is not None and self.denominator is not None):
            raise ValueError("only a known guidance state carries a fraction")
        if known:
            assert self.numerator is not None and self.denominator is not None
            if self.numerator > self.denominator:
                raise ValueError("guidance numerator cannot exceed its denominator")
            if self.state_class not in {
                GuidanceStateClass.KNOWN_RETAIN,
                GuidanceStateClass.KNOWN_IMPROVE,
            }:
                raise ValueError("a known state requires a known state class")
            if self.value_origin is ValueOrigin.NONE:
                raise ValueError("a known state requires a value origin")
            if (
                self.value_origin is ValueOrigin.TYPED_OBJECTIVE
            ) != (
                self.evidence_authority is EvidenceAuthority.OBJECTIVE_RECEIPT
            ):
                raise ValueError("value origin must match the evidence authority")
        else:
            if self.basis in {GuidanceBasis.MEASURED, GuidanceBasis.EXPERIMENTAL}:
                raise ValueError("only a known state may claim a value-bearing basis")
            if self.value_origin is not ValueOrigin.NONE:
                raise ValueError("a non-known state cannot claim a value origin")
            if self.factor_evidence is not GuidanceFactorEvidence.NOT_OBSERVED:
                raise ValueError("factor evidence requires a known metric state")
        if self.basis is GuidanceBasis.EXPERIMENTAL and (
            self.value_origin is not ValueOrigin.NEURAL_UNCALIBRATED
        ):
            raise ValueError("only an uncalibrated neural estimate is experimental")
        if self.basis is GuidanceBasis.MEASURED and self.value_origin not in {
            ValueOrigin.DETERMINISTIC_LOCAL,
            ValueOrigin.TYPED_OBJECTIVE,
        }:
            raise ValueError("measured guidance requires a measured value origin")
        if (
            self.basis is GuidanceBasis.MEASURED
            and self.factor_evidence is GuidanceFactorEvidence.AGGREGATE_ONLY
        ):
            raise ValueError("aggregate-only factor evidence is method-level guidance")
        if self.focus_factor_keys and (
            self.factor_evidence is not GuidanceFactorEvidence.PER_FACTOR_MEASURED
        ):
            raise ValueError("focus factors require measured per-factor statistics")
        if len(self.focus_factor_keys) > self.contract_factor_count:
            raise ValueError("focus factors must belong to the contract factor list")
        if (
            self.value_state is MetricValueStateV2.NOT_APPLICABLE
            and self.eligible_count != 0
        ):
            raise ValueError("a not-applicable state requires an empty opportunity set")
        if (
            self.value_state is MetricValueStateV2.PENDING
            and self.pending_count == 0
        ):
            raise ValueError("a pending state requires a pending opportunity")
        if self.value_state is MetricValueStateV2.EXECUTION_ERROR and (
            self.state_class is not GuidanceStateClass.ANALYSIS_FAILED
            or self.audience is not GuidanceAudience.TOOLING
            or self.basis is not GuidanceBasis.METHOD_ONLY
        ):
            raise ValueError("a failed stage is tooling guidance with no value basis")
        bounded = (
            self.censoring_lower_bound is not None,
            self.censoring_upper_bound is not None,
        )
        if len(set(bounded)) != 1:
            raise ValueError("censoring bounds are published as a pair")
        if (
            self.censoring_lower_bound is not None
            and self.censoring_upper_bound is not None
            and self.censoring_lower_bound > self.censoring_upper_bound
        ):
            raise ValueError("censoring bounds must be ordered")
        return self


def _templates_for(metric_key: str, state_class: GuidanceStateClass) -> tuple[str, str, str]:
    diagnosis = _template("diagnosis", metric_key)
    generic = _GENERIC_TEMPLATES.get(state_class)
    if generic is None:
        prefix = _METRIC_ACTION_PREFIX[state_class]
        return (
            diagnosis,
            _template(prefix, metric_key),
            _template("verification", metric_key),
        )
    return (diagnosis, _template(generic[0]), _template(generic[1]))


def metric_guidance_template_set(
    metric_key: str,
    state_class: GuidanceStateClass,
) -> MetricGuidanceTemplateSet:
    diagnosis, action, verification = _templates_for(metric_key, state_class)
    return MetricGuidanceTemplateSet(
        state_class=state_class,
        diagnosis_template_id=diagnosis,
        action_template_id=action,
        verification_template_id=verification,
    )


def _state_class(
    state: MetricStateV2,
    contract: MetricContractV2,
    direction: MetricDirection,
) -> GuidanceStateClass:
    if state.value_state is MetricValueStateV2.EXECUTION_ERROR:
        return GuidanceStateClass.ANALYSIS_FAILED
    if state.value_state is MetricValueStateV2.ABSTAINED:
        return GuidanceStateClass.EVIDENCE_COVERAGE_ABSTAINED
    if state.value_state is MetricValueStateV2.NOT_APPLICABLE:
        return GuidanceStateClass.NO_OPPORTUNITY
    if state.value_state is MetricValueStateV2.PENDING:
        return GuidanceStateClass.PENDING_CLOSURE
    if state.value_state is MetricValueStateV2.UNKNOWN:
        # An objective contract cannot be advanced by any wording, so the only
        # honest action is to connect the receipt that could resolve it.
        if contract.evidence_authority is EvidenceAuthority.OBJECTIVE_RECEIPT:
            if (
                state.statistics.capability_available
                and state.statistics.eligible_count > 0
            ):
                # Authorized evidence exists; it just does not close the set.
                return GuidanceStateClass.OBJECTIVE_EVIDENCE_UNRESOLVED
            return GuidanceStateClass.OBJECTIVE_EVIDENCE_MISSING
        return GuidanceStateClass.EVIDENCE_UNRESOLVED
    assert state.numeric_value is not None
    oriented = (
        1.0 - state.numeric_value
        if direction is MetricDirection.LOWER_IS_BETTER
        else state.numeric_value
    )
    return (
        GuidanceStateClass.KNOWN_RETAIN
        if oriented >= METRIC_GUIDANCE_RETAIN_FLOOR
        else GuidanceStateClass.KNOWN_IMPROVE
    )


def default_value_origin(
    contract: MetricContractV2,
    state: MetricStateV2,
) -> ValueOrigin:
    """A projected value is deterministic or objective, never neural."""

    if state.value_state is not MetricValueStateV2.KNOWN:
        return ValueOrigin.NONE
    if contract.evidence_authority is EvidenceAuthority.OBJECTIVE_RECEIPT:
        return ValueOrigin.TYPED_OBJECTIVE
    return ValueOrigin.DETERMINISTIC_LOCAL


def _basis(
    state: MetricStateV2,
    origin: ValueOrigin,
    factor_evidence: GuidanceFactorEvidence,
) -> GuidanceBasis:
    if state.value_state is MetricValueStateV2.EXECUTION_ERROR:
        return GuidanceBasis.METHOD_ONLY
    if state.value_state is not MetricValueStateV2.KNOWN:
        return GuidanceBasis.READINESS
    if factor_evidence is GuidanceFactorEvidence.AGGREGATE_ONLY:
        # The fraction is measured; which factors were met is not.
        return GuidanceBasis.METHOD_ONLY
    if origin is ValueOrigin.NEURAL_UNCALIBRATED:
        return GuidanceBasis.EXPERIMENTAL
    return GuidanceBasis.MEASURED


def build_metric_guidance(
    state: MetricStateV2,
    *,
    factor_evidence: GuidanceFactorEvidence = GuidanceFactorEvidence.NOT_OBSERVED,
    focus_factor_keys: tuple[str, ...] = (),
    value_origin: ValueOrigin | None = None,
) -> MetricGuidanceReceipt:
    """Derive one guidance receipt from one projected V2 metric state.

    The function is total over the twenty V2 contracts and pure: the same state
    always yields the same identities, in any language, on any surface.  It
    reads no session text and produces no sentence.  ``factor_evidence`` and
    ``focus_factor_keys`` must come from the producer that actually held the
    per-factor statistics; the default publishes none.
    """

    contract = metric_contract_v2(state.metric_key)
    if state.contract_fingerprint != contract.fingerprint:
        raise ValueError("metric state does not match its V2 contract fingerprint")
    definition = _DEFINITION_BY_KEY.get(state.metric_key)
    if definition is None:
        raise ValueError("metric is outside the guidance catalog")
    origin = (
        default_value_origin(contract, state)
        if value_origin is None
        else value_origin
    )
    if state.value_state is not MetricValueStateV2.KNOWN:
        origin = ValueOrigin.NONE
        factor_evidence = GuidanceFactorEvidence.NOT_OBSERVED
        focus_factor_keys = ()
    contract_factor_keys = tuple(item.factor_key for item in contract.factors)
    if any(item not in contract_factor_keys for item in focus_factor_keys):
        raise ValueError("focus factors must belong to the contract factor list")
    state_class = _state_class(state, contract, definition.direction)
    diagnosis, action, verification = _templates_for(state.metric_key, state_class)
    audience = (
        GuidanceAudience.TOOLING
        if state.value_state is MetricValueStateV2.EXECUTION_ERROR
        else metric_guidance_audience(contract)
    )
    statistics = state.statistics
    return MetricGuidanceReceipt(
        metric_key=state.metric_key,
        metric_version=definition.version,
        metric_contract_version=contract.contract_version,
        metric_contract_fingerprint=contract.fingerprint,
        value_state=state.value_state,
        denominator_basis=contract.denominator_basis,
        evidence_authority=contract.evidence_authority,
        role=metric_guidance_role(state.metric_key),
        audience=audience,
        basis=_basis(state, origin, factor_evidence),
        value_origin=origin,
        factor_evidence=factor_evidence,
        state_class=state_class,
        reason_code=state.explanation_code,
        contract_factor_count=len(contract_factor_keys),
        focus_factor_keys=focus_factor_keys[:MAX_GUIDANCE_FOCUS_FACTOR_KEYS],
        diagnosis_template_id=diagnosis,
        action_template_id=action,
        verification_template_id=verification,
        eligible_count=statistics.eligible_count,
        met_count=statistics.met_count,
        not_met_count=statistics.not_met_count,
        pending_count=statistics.pending_count,
        unknown_count=statistics.unknown_count,
        numerator=state.numerator,
        denominator=state.denominator,
        censoring_lower_bound=state.censoring_lower_bound,
        censoring_upper_bound=state.censoring_upper_bound,
    )


def metric_guidance_catalog() -> tuple[MetricGuidanceCatalogEntry, ...]:
    """Static guidance identities for all twenty contracts, in registry order.

    A client fetches this once and can then render every state it may receive,
    including states it has not observed yet, without duplicating the mapping.
    """

    entries: list[MetricGuidanceCatalogEntry] = []
    for contract in METRIC_CONTRACTS_V2:
        definition = _DEFINITION_BY_KEY[contract.metric_key]
        entries.append(
            MetricGuidanceCatalogEntry(
                metric_key=contract.metric_key,
                metric_version=definition.version,
                contract_version=contract.contract_version,
                contract_fingerprint=contract.fingerprint,
                denominator_basis=contract.denominator_basis,
                evidence_authority=contract.evidence_authority,
                direction=definition.direction,
                role=metric_guidance_role(contract.metric_key),
                audience=metric_guidance_audience(contract),
                contract_factor_keys=tuple(
                    item.factor_key for item in contract.factors
                ),
                templates=tuple(
                    metric_guidance_template_set(contract.metric_key, state_class)
                    for state_class in GuidanceStateClass
                ),
            )
        )
    return tuple(entries)


if set(_DEFINITION_BY_KEY) != {item.metric_key for item in METRIC_CONTRACTS_V2}:
    raise RuntimeError("metric guidance catalog does not cover the V2 registry")


__all__ = [
    "MAX_GUIDANCE_FACTOR_KEYS",
    "MAX_GUIDANCE_FOCUS_FACTOR_KEYS",
    "METRIC_GUIDANCE_CONTRACT_VERSION",
    "METRIC_GUIDANCE_RETAIN_FLOOR",
    "METRIC_GUIDANCE_SCHEMA_VERSION",
    "METRIC_GUIDANCE_TEMPLATE_CATALOG_VERSION",
    "METRIC_GUIDANCE_TEMPLATE_VERSION",
    "GuidanceAudience",
    "GuidanceBasis",
    "GuidanceFactorEvidence",
    "GuidanceRole",
    "GuidanceStateClass",
    "MetricGuidanceCatalogEntry",
    "MetricGuidanceReceipt",
    "MetricGuidanceTemplateSet",
    "ValueOrigin",
    "build_metric_guidance",
    "default_value_origin",
    "metric_guidance_audience",
    "metric_guidance_catalog",
    "metric_guidance_role",
    "metric_guidance_template_set",
]
