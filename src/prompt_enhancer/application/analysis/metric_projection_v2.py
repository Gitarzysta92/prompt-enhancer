"""Project the V2 metric-science contracts over persisted semantic-unit heads.

Every denominator here is an exactly-owned opportunity set:

* semantic-unit contracts count one opportunity per active unit head, so an
  overlapping chunk, a duplicated read, or a re-run cannot inflate the
  denominator (``SemanticUnitReceipt`` already enforces exactly one owner);
* profile-slot contracts count what the caller explicitly declared;
* objective contracts count the adapter's authoritative opportunity set.

Right-censoring is represented per opportunity.  A single open episode no
longer forces the whole metric to ``unknown``: the resolved opportunities stay
measured and the metric publishes censoring bounds with a ``pending`` state.

Nothing in this module upgrades conversational text into objective evidence.
The five objective contracts are resolved only by the typed evidence lane.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Literal
from weakref import WeakKeyDictionary

from pydantic import Field, field_validator, model_validator

from ...domain import SAFE_VERSION_PATTERN, StrictModel
from ..persistence import MetricValueState
from .metric_contract_v2 import (
    DenominatorBasis,
    EvidenceAuthority,
    METRIC_CONTRACTS_V2,
    METRIC_CONTRACT_REGISTRY_VERSION_V2,
    MetricContractV2,
    MetricValueStateV2,
    NoOpportunityOutcome,
    OpportunitySelector,
    OpportunityState,
    PendingPolicy,
)
from .objective_metric_projection import ObjectiveMetricOverride
from .semantic_units import (
    EXTRACTABLE_SEMANTIC_UNIT_KINDS,
    FeedbackReworkClass,
    SemanticUnitIdFactory,
    SemanticUnitKind,
    SemanticUnitLifecycle,
    SemanticUnitReceipt,
    SemanticUnitReconciliation,
    semantic_source_digest,
)
from .text_contracts import (
    EphemeralRedactedMessage,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextMetricResult,
    TextRole,
)
from .text_baselines import CONSTRAINT_SLOT_PATTERNS, DELIVERABLE_SLOT_PATTERNS


#: Projection identity 1 mapped the fixed factor rubric onto whichever request
#: revision was latest when the focus message was not itself an owned request
#: revision.  That published a number computed from one message against an
#: opportunity owned by another, so a ``-1`` row is not reproducible under the
#: corrected rules.  Identity 2 is therefore a new persisted projection version
#: rather than an in-place fix: ``-1`` rows stay readable and keep meaning
#: exactly what the producer that wrote them meant.
METRIC_PROJECTION_V2_VERSION_1 = "metric-contract-v2-projection-1"
METRIC_PROJECTION_V2_VERSION_2 = "metric-contract-v2-projection-2"
#: Later identities live in their own producer modules.  They are named here
#: because this module owns the append-only readable-identity vocabulary that
#: persistence and the wire contract validate against.
METRIC_PROJECTION_V2_VERSION_3 = "metric-contract-v2-projection-3"
METRIC_PROJECTION_V2_VERSION_4 = "metric-contract-v2-projection-4"
METRIC_PROJECTION_V2_VERSION_5 = "metric-contract-v2-projection-5"
METRIC_PROJECTION_V2_VERSION_6 = "metric-contract-v2-projection-6"
METRIC_PROJECTION_V2_VERSION_7 = "metric-contract-v2-projection-7"
METRIC_PROJECTION_V2_VERSION_8 = "metric-contract-v2-projection-8"
#: The identity *this* producer stamps.  It stays at ``-2`` forever: rows it
#: wrote must keep meaning what the producer that wrote them meant.
METRIC_PROJECTION_V2_VERSION = METRIC_PROJECTION_V2_VERSION_2
#: Readable identities in append-only historical order. Persistence owns its
#: separate newest-first sidecar preference.
SUPPORTED_METRIC_PROJECTION_V2_VERSIONS = (
    METRIC_PROJECTION_V2_VERSION_1,
    METRIC_PROJECTION_V2_VERSION_2,
    METRIC_PROJECTION_V2_VERSION_3,
    METRIC_PROJECTION_V2_VERSION_4,
    METRIC_PROJECTION_V2_VERSION_5,
    METRIC_PROJECTION_V2_VERSION_6,
    METRIC_PROJECTION_V2_VERSION_7,
    METRIC_PROJECTION_V2_VERSION_8,
)
MetricProjectionV2Version = Literal[
    "metric-contract-v2-projection-1",
    "metric-contract-v2-projection-2",
    "metric-contract-v2-projection-3",
    "metric-contract-v2-projection-4",
    "metric-contract-v2-projection-5",
    "metric-contract-v2-projection-6",
    "metric-contract-v2-projection-7",
    "metric-contract-v2-projection-8",
]
METRIC_PROJECTION_V2_ALGORITHM_ID = "rules.en-pl.contract-v2-opportunities"
METRIC_PROJECTION_V2_ALGORITHM_VERSION = "2"
#: The rework classifier is a versioned local rule set, never a receipt field.
REWORK_CLASSIFIER_VERSION = "rework-class-en-pl-1"
#: A fixed factor rubric scores the focus message.  It may only be published
#: when the canonical active request revision owns exactly that message; any
#: other pairing is an unknown, never a zero.
REASON_RUBRIC_NOT_FOCUS_OWNED = "rubric_opportunity_not_focus_owned"

_SUPPORTED_LANGUAGES = frozenset(
    {TextLanguage.ENGLISH, TextLanguage.POLISH, TextLanguage.MIXED}
)

# Deterministic EN/PL cues.  They mirror the reviewed coaching vocabulary; the
# V2 change is where they are applied, not how permissive they are.
_TOKEN = re.compile(r"[^\W_]+(?:[-/.][^\W_]+)*", re.UNICODE)
_STRATEGY_CUE = re.compile(
    r"\b(?:acceptance|assert|check|coverage|equals?|exactly|regression|"
    r"reproduce|test(?:s|ed|ing)?|threshold|validate|verify|verified|"
    r"akceptacj|asercj|dokładnie|potwierdz|pokrycie|regresj|sprawdz|sprawdź|"
    r"test|próg|walidacj|weryfik|zweryfik)\w*\b|(?:<=|>=|==|<|>)\s*\d+",
    re.IGNORECASE,
)
_RATIONALE_CUE = re.compile(
    r"\b(?:because|due to|given that|so that|to preserve|trade-?off|alternative|"
    r"evidence|constraint|rationale|ponieważ|dlatego|ze względu|aby zachować|"
    r"kompromis|alternatyw|dowód|dowod|ograniczen|uzasadnien)\w*\b",
    re.IGNORECASE,
)
_CHECK_CUE = re.compile(
    r"\b(?:acceptance|assert|equals?|exactly|must pass|passes|returns?|"
    r"test(?:s|ed|ing)?|threshold|verify|verified|visible|"
    r"akceptacj|dokładnie|musi przejść|przechodzi|test|próg|zwraca|"
    r"zweryfik|widoczn)\w*\b|(?:<=|>=|==|<|>)\s*\d+|\b\d+(?:\.\d+)?%",
    re.IGNORECASE,
)
_ORACLE_CUE = re.compile(
    r"\b(?:acceptance|assert|expected|fails?|must pass|passes|returns?|"
    r"threshold|equals?|exactly|akceptacj|asercj|oczekiwan|nie przechodzi|"
    r"musi przejść|przechodzi|próg|zwraca|dokładnie)\w*\b|"
    r"(?:<=|>=|==|<|>)\s*\d+|\b\d+(?:\.\d+)?%",
    re.IGNORECASE,
)
# Rework classification.  Exclusions are evaluated before the correction cue so
# a genuine scope or preference change is never reported as avoidable rework.
_SCOPE_EVOLUTION_CUE = re.compile(
    r"\b(?:change (?:the )?scope|new requirement|additional requirement|"
    r"additionally|also add|no longer needed|out of scope|from now on|"
    r"zmień zakres|zmiana zakresu|nowe wymaganie|dodatkowo|dodaj jeszcze|"
    r"już nie potrzeb|poza zakresem|od teraz)\b",
    re.IGNORECASE,
)
_PREFERENCE_CUE = re.compile(
    r"\b(?:i(?:'d| would)? prefer|i like|rather|stylistic|nicer|cosmetic|"
    r"wolał|wolę|podoba mi się|raczej|estetycz|kosmetyczn)\w*\b",
    re.IGNORECASE,
)
_NEW_INFORMATION_CUE = re.compile(
    r"\b(?:forgot to mention|i did not say|for context|note that|"
    r"turns out|new information|just found|zapomniałem|nie powiedziałem|"
    r"dla kontekstu|okazuje się|nowa informacja|właśnie znalazł)\w*\b",
    re.IGNORECASE,
)
_CORRECTION_CUE = re.compile(
    r"\b(?:that is wrong|that's wrong|not what i asked|you misunderstood|"
    r"still fails?|still broken|redo|try again|incorrect|"
    r"to jest źle|nie o to|nie zrozumiał|nadal nie działa|nadal się psuje|"
    r"zrób ponownie|spróbuj ponownie|niepoprawn)\w*\b",
    re.IGNORECASE,
)


def _tokens(value: str) -> frozenset[str]:
    return frozenset(
        token.casefold() for token in _TOKEN.findall(value) if len(token) > 1
    )


def _related(left: str, right: str, *, threshold: float = 0.05) -> bool:
    left_tokens, right_tokens = _tokens(left), _tokens(right)
    if not left_tokens or not right_tokens:
        return False
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) >= threshold


class OpportunityStatistics(StrictModel):
    """Content-free sufficient statistics for one metric's opportunity set.

    These are the only numbers a downstream aggregate needs: no text, no
    identifiers, and no per-opportunity receipt beyond the counts.
    """

    metric_key: str
    denominator_basis: DenominatorBasis
    opportunity_unit_kind: SemanticUnitKind | None = None
    capability_available: bool
    source_complete: bool
    eligible_count: int = Field(ge=0, le=1_000_000)
    met_count: int = Field(default=0, ge=0, le=1_000_000)
    not_met_count: int = Field(default=0, ge=0, le=1_000_000)
    pending_count: int = Field(default=0, ge=0, le=1_000_000)
    unknown_count: int = Field(default=0, ge=0, le=1_000_000)
    superseded_excluded_count: int = Field(default=0, ge=0, le=1_000_000)
    distinct_owner_count: int = Field(default=0, ge=0, le=1_000_000)

    @field_validator("metric_key")
    @classmethod
    def validate_metric_key(cls, value: str) -> str:
        if SAFE_VERSION_PATTERN.fullmatch(value) is None:
            raise ValueError("metric key must be a content-free identifier")
        return value

    @model_validator(mode="after")
    def validate_partition(self) -> OpportunityStatistics:
        total = (
            self.met_count
            + self.not_met_count
            + self.pending_count
            + self.unknown_count
        )
        if total != self.eligible_count:
            raise ValueError("opportunity outcomes must partition the eligible set")
        if not self.capability_available and self.eligible_count:
            r7_requirement_action_candidate = (
                self.metric_key == "logic.requirement_action_traceability"
                and self.denominator_basis
                is DenominatorBasis.OBJECTIVE_OPPORTUNITIES
                and self.opportunity_unit_kind is None
                and self.source_complete
                and self.met_count == 0
                and self.not_met_count == 0
                and self.pending_count == 0
                and self.unknown_count == self.eligible_count
                and self.distinct_owner_count == self.eligible_count
            )
            if not r7_requirement_action_candidate:
                raise ValueError(
                    "an unavailable opportunity family cannot be eligible"
                )
        if (
            self.denominator_basis is DenominatorBasis.SEMANTIC_UNIT_OPPORTUNITIES
            and self.distinct_owner_count != self.eligible_count
        ):
            raise ValueError(
                "semantic-unit opportunities require exactly one owner each"
            )
        return self


class MetricStateV2(StrictModel):
    """One projected V2 metric result with censoring bounds."""

    metric_key: str
    registry_version: Literal[METRIC_CONTRACT_REGISTRY_VERSION_V2] = (
        METRIC_CONTRACT_REGISTRY_VERSION_V2
    )
    contract_version: str
    contract_fingerprint: str
    evidence_authority: EvidenceAuthority
    value_state: MetricValueStateV2
    explanation_code: str
    numerator: int | None = Field(default=None, ge=0, le=1_000_000)
    denominator: int | None = Field(default=None, ge=1, le=1_000_000)
    numeric_value: float | None = Field(default=None, ge=0, le=1)
    censoring_lower_bound: float | None = Field(default=None, ge=0, le=1)
    censoring_upper_bound: float | None = Field(default=None, ge=0, le=1)
    statistics: OpportunityStatistics
    #: Read every frozen identity, but require every producer and persistence
    #: reader to state which one it is using.  A historical row can therefore
    #: never acquire an identity through a model default whose rules did not
    #: produce it.
    projection_version: MetricProjectionV2Version
    product_metric_eligible: Literal[False] = False

    @field_validator("metric_key", "contract_version", "explanation_code")
    @classmethod
    def validate_safe_identifiers(cls, value: str) -> str:
        if SAFE_VERSION_PATTERN.fullmatch(value) is None:
            raise ValueError("metric state metadata must be content-free")
        return value

    @field_validator("contract_fingerprint")
    @classmethod
    def validate_contract_fingerprint(cls, value: str) -> str:
        if len(value) != 64 or any(
            character not in "0123456789abcdef" for character in value
        ):
            raise ValueError("contract fingerprint must be lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def validate_state(self) -> MetricStateV2:
        if self.statistics.metric_key != self.metric_key:
            raise ValueError("metric statistics belong to another metric")
        if not self.statistics.capability_available and self.statistics.eligible_count:
            r7_requirement_action_unavailable = (
                self.projection_version
                in {
                    "metric-contract-v2-projection-7",
                    "metric-contract-v2-projection-8",
                }
                and self.metric_key == "logic.requirement_action_traceability"
                and self.value_state is MetricValueStateV2.UNKNOWN
                and self.explanation_code == "requirement_action_evidence_unavailable"
                and self.statistics.source_complete
                and self.statistics.unknown_count
                == self.statistics.eligible_count
                and self.statistics.met_count == 0
                and self.statistics.not_met_count == 0
                and self.statistics.pending_count == 0
            )
            if not r7_requirement_action_unavailable:
                raise ValueError(
                    "an unavailable opportunity family cannot be eligible"
                )
        known = self.value_state is MetricValueStateV2.KNOWN
        if known != (self.numeric_value is not None):
            raise ValueError("only known metric states carry a point value")
        if known:
            if self.numerator is None or self.denominator is None:
                raise ValueError("known metric states require an exact fraction")
            if self.numerator > self.denominator:
                raise ValueError("metric numerator cannot exceed its denominator")
            if abs(self.numeric_value - self.numerator / self.denominator) > 1e-9:
                raise ValueError("known value must equal its exact fraction")
        elif self.numerator is not None or self.denominator is not None:
            raise ValueError("non-known metric states cannot carry a fraction")
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
        if known and (
            self.censoring_lower_bound != self.numeric_value
            or self.censoring_upper_bound != self.numeric_value
        ):
            raise ValueError("known values require exact equal censoring bounds")
        if (
            self.value_state is MetricValueStateV2.PENDING
            and self.statistics.pending_count == 0
        ):
            raise ValueError("pending metric states require a pending opportunity")
        if self.value_state is MetricValueStateV2.PENDING:
            statistics = self.statistics
            exact_pending_bounds = (
                statistics.capability_available
                and statistics.source_complete
                and statistics.eligible_count > 0
                and statistics.unknown_count == 0
                and self.censoring_lower_bound is not None
                and self.censoring_upper_bound is not None
                and abs(
                    self.censoring_lower_bound
                    - statistics.met_count / statistics.eligible_count
                )
                <= 1e-9
                and abs(
                    self.censoring_upper_bound
                    - (
                        statistics.met_count + statistics.pending_count
                    )
                    / statistics.eligible_count
                )
                <= 1e-9
            )
            if not exact_pending_bounds:
                raise ValueError(
                    "pending metric states require exact censoring bounds"
                )
        if (
            self.value_state is MetricValueStateV2.NOT_APPLICABLE
            and self.statistics.eligible_count != 0
        ):
            raise ValueError("not-applicable states require an empty opportunity set")
        if (
            self.evidence_authority is EvidenceAuthority.OBJECTIVE_RECEIPT
            and self.value_state is MetricValueStateV2.KNOWN
            and self.statistics.denominator_basis
            is not DenominatorBasis.OBJECTIVE_OPPORTUNITIES
        ):
            raise ValueError(
                "objective contracts cannot be resolved by conversational material"
            )
        return self


def reviewed_requirement_plan_denominator_is_authoritative(
    state: MetricStateV2,
) -> bool:
    """Whether an r6-r8 decomposition row proves its reviewed denominator."""

    contract = next(
        item
        for item in METRIC_CONTRACTS_V2
        if item.metric_key == "logic.decomposition_coverage"
    )
    statistics = state.statistics
    if (
        state.metric_key != "logic.decomposition_coverage"
        or state.contract_version != contract.contract_version
        or state.contract_fingerprint != contract.fingerprint
        or state.evidence_authority is not contract.evidence_authority
        or state.projection_version
        not in {
            METRIC_PROJECTION_V2_VERSION_6,
            METRIC_PROJECTION_V2_VERSION_7,
            METRIC_PROJECTION_V2_VERSION_8,
        }
        or statistics.metric_key != state.metric_key
        or statistics.denominator_basis is not contract.denominator_basis
        or statistics.opportunity_unit_kind is not contract.opportunity_unit_kind
        or not statistics.capability_available
        or not statistics.source_complete
        or statistics.unknown_count != 0
        or statistics.superseded_excluded_count != 0
        or statistics.distinct_owner_count != statistics.eligible_count
    ):
        return False
    eligible = statistics.eligible_count
    met = statistics.met_count
    pending = statistics.pending_count
    exact_partition = (
        met + statistics.not_met_count + pending == eligible
    )
    if not exact_partition:
        return False
    if state.value_state is MetricValueStateV2.KNOWN:
        return (
            state.explanation_code == "reviewed_requirement_plan_links"
            and eligible > 0
            and pending == 0
            and state.numerator == met
            and state.denominator == eligible
            and state.numeric_value is not None
            and state.censoring_lower_bound is not None
            and state.censoring_upper_bound is not None
            and abs(state.numeric_value - met / eligible) <= 1e-9
            and abs(state.censoring_lower_bound - met / eligible) <= 1e-9
            and abs(state.censoring_upper_bound - met / eligible) <= 1e-9
        )
    if state.value_state is MetricValueStateV2.PENDING:
        return (
            state.explanation_code == "opportunity_right_censored"
            and eligible > 0
            and pending > 0
            and state.numerator is None
            and state.denominator is None
            and state.numeric_value is None
            and state.censoring_lower_bound is not None
            and state.censoring_upper_bound is not None
            and abs(state.censoring_lower_bound - met / eligible) <= 1e-9
            and abs(
                state.censoring_upper_bound - (met + pending) / eligible
            )
            <= 1e-9
        )
    if state.value_state is MetricValueStateV2.NOT_APPLICABLE:
        return (
            state.explanation_code == "no_opportunity_observed"
            and eligible == 0
            and met == 0
            and statistics.not_met_count == 0
            and pending == 0
            and state.numerator is None
            and state.denominator is None
            and state.numeric_value is None
            and state.censoring_lower_bound is None
            and state.censoring_upper_bound is None
        )
    return False


class MetricStateProjectionV2(Sequence[MetricStateV2]):
    """Opaque, producer-issued projection consumed by the V2 publisher.

    Metric states are serializable data and therefore cannot carry authority by
    themselves.  The publisher accepts only one of these in-memory envelopes,
    issued by a reviewed producer.  Copying or rebuilding the contained models
    from JSON does not recreate the envelope authority.
    """

    __slots__ = ("__states", "__weakref__")

    def __init__(
        self,
        states: Sequence[MetricStateV2],
        *,
        _issuer: object,
    ) -> None:
        if _issuer is not _METRIC_STATE_PROJECTION_ISSUER:
            raise TypeError("metric-state projections are producer-issued")
        self.__states = tuple(states)

    def __len__(self) -> int:
        return len(self.__states)

    def __iter__(self) -> Iterator[MetricStateV2]:
        return iter(self.__states)

    def __getitem__(
        self,
        index: int | slice,
    ) -> MetricStateV2 | tuple[MetricStateV2, ...]:
        return self.__states[index]

    def _issued_state_tuple(self) -> tuple[MetricStateV2, ...]:
        """Return the exact sealed storage for the internal authority check."""

        return self.__states


class LiveMetricStateProjectionV2(MetricStateProjectionV2):
    """Projection issued only by the live V2 semantic-unit producer."""

    __slots__ = ()


class V1CompatibilityMetricStateProjectionV2(MetricStateProjectionV2):
    """Projection issued only by the reviewed V1 compatibility adapter."""

    __slots__ = ()


_METRIC_STATE_PROJECTION_ISSUER = object()


@dataclass(frozen=True, slots=True)
class _MetricStateProjectionAuthority:
    compatibility: bool
    states: tuple[MetricStateV2, ...]
    serialized_states: tuple[str, ...]


_ISSUED_METRIC_STATE_PROJECTIONS: WeakKeyDictionary[
    MetricStateProjectionV2,
    _MetricStateProjectionAuthority,
] = WeakKeyDictionary()


def _issue_metric_state_projection(
    states: Sequence[MetricStateV2],
    *,
    compatibility: bool,
) -> MetricStateProjectionV2:
    projection_type = (
        V1CompatibilityMetricStateProjectionV2
        if compatibility
        else LiveMetricStateProjectionV2
    )
    projection = projection_type(
        states,
        _issuer=_METRIC_STATE_PROJECTION_ISSUER,
    )
    states_tuple = projection._issued_state_tuple()
    _ISSUED_METRIC_STATE_PROJECTIONS[projection] = _MetricStateProjectionAuthority(
        compatibility=compatibility,
        states=states_tuple,
        serialized_states=tuple(state.model_dump_json() for state in states_tuple),
    )
    return projection


def _metric_state_projection_is_issued(
    projection: object,
) -> bool:
    if not isinstance(projection, MetricStateProjectionV2):
        return False
    try:
        authority = _ISSUED_METRIC_STATE_PROJECTIONS[projection]
    except (KeyError, TypeError):
        return False
    current = projection._issued_state_tuple()
    return (
        current is authority.states
        and tuple(state.model_dump_json() for state in current)
        == authority.serialized_states
    )


def _metric_state_projection_is_compatibility(
    projection: MetricStateProjectionV2,
) -> bool:
    try:
        authority = _ISSUED_METRIC_STATE_PROJECTIONS[projection]
    except (KeyError, TypeError) as exc:
        raise TypeError(
            "publication requires a producer-issued metric projection"
        ) from exc
    if not _metric_state_projection_is_issued(projection):
        raise TypeError("metric projection contents do not match their producer")
    return authority.compatibility


@dataclass(frozen=True, slots=True)
class _Opportunity:
    unit_id: str
    owner_source_digest: str
    state: OpportunityState


def _statistics(
    contract: MetricContractV2,
    opportunities: tuple[_Opportunity, ...],
    *,
    capability_available: bool,
    source_complete: bool,
    superseded_excluded: int = 0,
) -> OpportunityStatistics:
    owners = {item.owner_source_digest for item in opportunities}
    return OpportunityStatistics(
        metric_key=contract.metric_key,
        denominator_basis=contract.denominator_basis,
        opportunity_unit_kind=contract.opportunity_unit_kind,
        capability_available=capability_available,
        source_complete=source_complete,
        eligible_count=len(opportunities),
        met_count=sum(
            item.state is OpportunityState.MET for item in opportunities
        ),
        not_met_count=sum(
            item.state is OpportunityState.NOT_MET for item in opportunities
        ),
        pending_count=sum(
            item.state is OpportunityState.PENDING for item in opportunities
        ),
        unknown_count=sum(
            item.state is OpportunityState.UNKNOWN for item in opportunities
        ),
        superseded_excluded_count=superseded_excluded,
        distinct_owner_count=len(owners),
    )


def resolve_metric_state(
    contract: MetricContractV2,
    statistics: OpportunityStatistics,
    *,
    explanation_code: str,
    unavailable_code: str = "opportunity_family_unobservable",
    projection_version: str | None = None,
) -> MetricStateV2:
    """Turn sufficient statistics into one typed value state.

    Order matters.  Missing capability outranks an empty set, because an
    unobservable family proves nothing about whether an opportunity existed.
    Epistemic ``unknown`` outranks temporal ``pending`` for the same reason: an
    unclassifiable opportunity is not merely waiting.

    ``projection_version`` is how a later producer stamps its own identity onto
    a state resolved by these shared rules.  Left unset it keeps this module's
    identity, so the r2 producer is unaffected by the existence of r3.
    """

    stamped_projection_version = (
        METRIC_PROJECTION_V2_VERSION
        if projection_version is None
        else projection_version
    )

    def _state(
        value_state: MetricValueStateV2,
        code: str,
        *,
        numerator: int | None = None,
        denominator: int | None = None,
        bounds: tuple[float, float] | None = None,
    ) -> MetricStateV2:
        return MetricStateV2(
            metric_key=contract.metric_key,
            contract_version=contract.contract_version,
            contract_fingerprint=contract.fingerprint,
            evidence_authority=contract.evidence_authority,
            value_state=value_state,
            explanation_code=code,
            numerator=numerator,
            denominator=denominator,
            numeric_value=(
                None
                if numerator is None or denominator is None
                else numerator / denominator
            ),
            censoring_lower_bound=None if bounds is None else bounds[0],
            censoring_upper_bound=None if bounds is None else bounds[1],
            statistics=statistics,
            projection_version=stamped_projection_version,
        )

    if not statistics.capability_available:
        return _state(MetricValueStateV2.UNKNOWN, unavailable_code)
    if not statistics.source_complete:
        return _state(MetricValueStateV2.UNKNOWN, "source_reconciliation_incomplete")
    eligible = statistics.eligible_count
    if eligible == 0:
        if contract.no_opportunity_outcome is NoOpportunityOutcome.NOT_APPLICABLE:
            return _state(
                MetricValueStateV2.NOT_APPLICABLE, "no_opportunity_observed"
            )
        return _state(MetricValueStateV2.UNKNOWN, "opportunity_set_undetermined")

    met = statistics.met_count
    pending = statistics.pending_count
    unknown = statistics.unknown_count
    bounds = ((met) / eligible, (met + pending + unknown) / eligible)
    if unknown:
        return _state(
            MetricValueStateV2.UNKNOWN,
            "opportunity_classification_unknown",
            bounds=bounds,
        )
    if pending:
        if contract.pending_policy is not PendingPolicy.RIGHT_CENSORED_OPPORTUNITY:
            return _state(
                MetricValueStateV2.UNKNOWN,
                "opportunity_classification_unknown",
                bounds=bounds,
            )
        return _state(MetricValueStateV2.PENDING, "opportunity_right_censored", bounds=bounds)
    return _state(
        MetricValueStateV2.KNOWN,
        explanation_code,
        numerator=met,
        denominator=eligible,
        bounds=(met / eligible, met / eligible),
    )


def _active_heads(
    reconciliation: SemanticUnitReconciliation,
    kind: SemanticUnitKind,
) -> tuple[tuple[SemanticUnitReceipt, ...], int]:
    """Active heads of one kind plus the number excluded by supersession."""

    of_kind = tuple(item for item in reconciliation.heads if item.kind is kind)
    superseded = tuple(
        item
        for item in of_kind
        if item.lifecycle is SemanticUnitLifecycle.SUPERSEDED
    )
    return (
        tuple(
            item
            for item in of_kind
            if item.lifecycle is not SemanticUnitLifecycle.SUPERSEDED
        ),
        len(superseded),
    )


def classify_feedback_rework(text: str) -> FeedbackReworkClass:
    """Assign exactly one rework class, with exclusions evaluated first.

    A scope change, a preference change, or newly supplied information is never
    reported as avoidable rework.  Absent any cue the class stays unknown; the
    classifier does not guess so that the metric can report honest bounds.
    """

    if _SCOPE_EVOLUTION_CUE.search(text):
        return FeedbackReworkClass.SCOPE_EVOLUTION
    if _PREFERENCE_CUE.search(text):
        return FeedbackReworkClass.PREFERENCE_CHANGE
    if _NEW_INFORMATION_CUE.search(text):
        return FeedbackReworkClass.NEW_INFORMATION
    if _CORRECTION_CUE.search(text):
        return FeedbackReworkClass.AVOIDABLE_CORRECTION
    return FeedbackReworkClass.UNKNOWN


class _Window:
    """Join persisted heads back to the ephemeral messages they own."""

    def __init__(
        self,
        context: P1TextAnalysisInput,
        id_factory: SemanticUnitIdFactory,
    ) -> None:
        self._by_digest: dict[str, EphemeralRedactedMessage] = {
            semantic_source_digest(
                id_factory,
                provider=context.provider,
                session_id=context.session_id,
                message_id=message.message_id,
            ): message
            for message in context.messages
        }
        self._messages = context.messages

    def message(self, owner_source_digest: str) -> EphemeralRedactedMessage | None:
        return self._by_digest.get(owner_source_digest)

    def later_agent_messages(
        self,
        sequence: int,
        kinds: frozenset[TextMessageKind],
    ) -> tuple[EphemeralRedactedMessage, ...]:
        return tuple(
            message
            for message in self._messages
            if message.sequence > sequence
            and message.role is TextRole.AGENT
            and message.kind in kinds
        )


_STRATEGY_KINDS = frozenset(
    {
        TextMessageKind.PLAN,
        TextMessageKind.RESPONSE,
        TextMessageKind.VERIFICATION,
    }
)


def _verification_strategy_opportunities(
    heads: tuple[SemanticUnitReceipt, ...],
    window: _Window,
) -> tuple[_Opportunity, ...]:
    """Conversational D+S: D = active request revisions, S = stated strategy."""

    opportunities: list[_Opportunity] = []
    for head in heads:
        message = window.message(head.owner_source_digest)
        if message is None or message.language not in _SUPPORTED_LANGUAGES:
            state = OpportunityState.UNKNOWN
            opportunities.append(
                _Opportunity(head.unit_id, head.owner_source_digest, state)
            )
            continue
        text = message.text.get_secret_value()
        candidates = window.later_agent_messages(
            head.first_sequence, _STRATEGY_KINDS
        )
        related = tuple(
            candidate
            for candidate in candidates
            if _related(text, candidate.text.get_secret_value())
        )
        if not related:
            # Nothing that could state a strategy has been observed yet.
            state = OpportunityState.PENDING
        elif any(
            _STRATEGY_CUE.search(candidate.text.get_secret_value())
            and _ORACLE_CUE.search(candidate.text.get_secret_value())
            for candidate in related
        ):
            state = OpportunityState.MET
        elif any(
            candidate.kind in {TextMessageKind.RESPONSE, TextMessageKind.VERIFICATION}
            for candidate in related
        ):
            # A related terminal response closed this request turn without a
            # stated method-and-oracle pair.  A plan alone does not close the
            # horizon and therefore cannot manufacture a negative.
            state = OpportunityState.NOT_MET
        else:
            state = OpportunityState.PENDING
        opportunities.append(
            _Opportunity(head.unit_id, head.owner_source_digest, state)
        )
    return tuple(opportunities)


def _decision_rationale_opportunities(
    heads: tuple[SemanticUnitReceipt, ...],
    window: _Window,
) -> tuple[_Opportunity, ...]:
    opportunities: list[_Opportunity] = []
    for head in heads:
        message = window.message(head.owner_source_digest)
        if message is None or message.language not in _SUPPORTED_LANGUAGES:
            state = OpportunityState.UNKNOWN
        elif _RATIONALE_CUE.search(message.text.get_secret_value()):
            state = OpportunityState.MET
        else:
            state = OpportunityState.NOT_MET
        opportunities.append(
            _Opportunity(head.unit_id, head.owner_source_digest, state)
        )
    return tuple(opportunities)


def _rework_opportunities(
    heads: tuple[SemanticUnitReceipt, ...],
    window: _Window,
) -> tuple[_Opportunity, ...]:
    opportunities: list[_Opportunity] = []
    for head in heads:
        message = window.message(head.owner_source_digest)
        if message is None or message.language not in _SUPPORTED_LANGUAGES:
            state = OpportunityState.UNKNOWN
        else:
            rework_class = classify_feedback_rework(
                message.text.get_secret_value()
            )
            if rework_class is FeedbackReworkClass.UNKNOWN:
                state = OpportunityState.UNKNOWN
            elif rework_class is FeedbackReworkClass.AVOIDABLE_CORRECTION:
                state = OpportunityState.MET
            else:
                state = OpportunityState.NOT_MET
        opportunities.append(
            _Opportunity(head.unit_id, head.owner_source_digest, state)
        )
    return tuple(opportunities)


_UNIT_OPPORTUNITY_BUILDERS = {
    "outcome.verification_strategy_adequacy": _verification_strategy_opportunities,
    "logic.decision_rationale_coverage": _decision_rationale_opportunities,
    "collaboration.rework_candidate_rate": _rework_opportunities,
}
_UNIT_EXPLANATIONS = {
    "outcome.verification_strategy_adequacy": "stated_verification_strategy",
    "logic.decision_rationale_coverage": "decision_rationale_stated",
    "collaboration.rework_candidate_rate": "classified_rework_episodes",
}


def _canonical_revision(
    context: P1TextAnalysisInput,
    reconciliation: SemanticUnitReconciliation,
    window: _Window,
) -> SemanticUnitReceipt | None:
    """The one active request revision the focus message resolves to.

    When the focus message is not itself an active request revision the latest
    active revision is still the canonical *request* of the window.  That is
    the correct anchor for a contract that reads the request's own text, and
    the wrong anchor for a contract that scores the focus message; see
    ``_focus_owned_revision``.
    """

    active, _ = _active_heads(reconciliation, SemanticUnitKind.REQUEST_REVISION)
    if not active:
        return None
    focus = _focus_owned_revision(context, reconciliation, window)
    if focus is not None:
        return focus
    return max(active, key=lambda item: (item.first_sequence, item.unit_id))


def _focus_owned_revision(
    context: P1TextAnalysisInput,
    reconciliation: SemanticUnitReconciliation,
    window: _Window,
) -> SemanticUnitReceipt | None:
    """The active request revision that owns *exactly* the focus message.

    ``None`` means no active revision owns it: the focus is a feedback turn, a
    superseded request, or a message this reconciler never owned.  A rubric
    fraction computed from that message therefore has no exactly-owned
    opportunity to be published against.
    """

    active, _ = _active_heads(reconciliation, SemanticUnitKind.REQUEST_REVISION)
    for head in active:
        message = window.message(head.owner_source_digest)
        if message is not None and message.message_id == context.focus_message_id:
            return head
    return None


def _rubric_state(
    contract: MetricContractV2,
    conversational: TextMetricResult | None,
    revision: SemanticUnitReceipt | None,
    *,
    focus_unowned: bool,
    source_complete: bool,
    projection_version: str | None = None,
) -> MetricStateV2:
    """Score the fixed factor rubric against the focus-owned revision.

    The rubric numerator still comes from the reviewed V1 calculator, which
    scores ``context.focus_message_id``.  V2 anchors it to an exactly-owned
    opportunity, so the fraction may only be published when the canonical
    active request revision owns that same message.  ``focus_unowned`` marks
    the case where request revisions exist but none of them owns the scored
    message: borrowing the latest revision's ownership would publish a number
    about one turn as if it described another, and a zero would be worse still.
    """

    if focus_unowned:
        return resolve_metric_state(
            contract,
            _statistics(
                contract,
                (),
                capability_available=False,
                source_complete=source_complete,
            ),
            explanation_code=REASON_RUBRIC_NOT_FOCUS_OWNED,
            unavailable_code=REASON_RUBRIC_NOT_FOCUS_OWNED,
            projection_version=projection_version,
        )
    if revision is None:
        statistics = _statistics(
            contract,
            (),
            capability_available=True,
            source_complete=source_complete,
        )
        return resolve_metric_state(
            contract,
            statistics,
            explanation_code="rubric_factors",
            projection_version=projection_version,
        )
    known = (
        conversational is not None
        and conversational.value_state is MetricValueState.KNOWN
        and conversational.fraction is not None
    )
    factor_count = len(contract.factors)
    denominator_matches = (
        known
        and conversational is not None
        and conversational.fraction is not None
        and conversational.fraction.denominator == factor_count
    )
    met_count = (
        conversational.fraction.numerator
        if denominator_matches
        and conversational is not None
        and conversational.fraction is not None
        else 0
    )
    statistics = _statistics(
        contract,
        tuple(
            _Opportunity(
                f"{revision.unit_id}-factor-{index}",
                revision.owner_source_digest,
                (
                    OpportunityState.MET
                    if index < met_count
                    else OpportunityState.NOT_MET
                    if denominator_matches
                    else OpportunityState.UNKNOWN
                ),
            )
            for index in range(factor_count)
        ),
        capability_available=True,
        source_complete=source_complete,
    )
    if not denominator_matches:
        # Preserve the reviewed V1 abstention and its content-free reason.
        value_state = MetricValueStateV2.UNKNOWN
        code = "rubric_factors_unavailable"
        if conversational is not None:
            code = conversational.explanation_code
            if conversational.value_state is MetricValueState.ABSTAINED:
                value_state = MetricValueStateV2.ABSTAINED
            elif conversational.value_state is MetricValueState.EXECUTION_ERROR:
                value_state = MetricValueStateV2.EXECUTION_ERROR
            elif known:
                code = "rubric_denominator_mismatch"
        return MetricStateV2(
            metric_key=contract.metric_key,
            contract_version=contract.contract_version,
            contract_fingerprint=contract.fingerprint,
            evidence_authority=contract.evidence_authority,
            value_state=value_state,
            explanation_code=code,
            statistics=statistics,
            projection_version=(
                METRIC_PROJECTION_V2_VERSION
                if projection_version is None
                else projection_version
            ),
        )
    assert conversational is not None
    return resolve_metric_state(
        contract,
        statistics,
        explanation_code=conversational.explanation_code,
        projection_version=projection_version,
    )


def _profile_slot_state(
    contract: MetricContractV2,
    context: P1TextAnalysisInput,
    revision: SemanticUnitReceipt | None,
    window: _Window,
    *,
    source_complete: bool,
    projection_version: str | None = None,
) -> MetricStateV2:
    if revision is None:
        statistics = _statistics(
            contract,
            (),
            capability_available=True,
            source_complete=source_complete,
        )
        return resolve_metric_state(
            contract,
            statistics,
            explanation_code="declared_profile_slots",
            projection_version=projection_version,
        )
    owner = window.message(revision.owner_source_digest)
    if owner is None or owner.language not in _SUPPORTED_LANGUAGES:
        statistics = _statistics(
            contract,
            (),
            capability_available=False,
            source_complete=source_complete,
        )
        return resolve_metric_state(
            contract,
            statistics,
            explanation_code="canonical_request_unavailable",
            unavailable_code="canonical_request_unavailable",
            projection_version=projection_version,
        )
    profile = context.task_profile
    # Profile slots belong to the one active request revision.  Looking across
    # the full window would let a superseded request satisfy the current
    # denominator and would make incremental and from-scratch results diverge.
    request_text = owner.text.get_secret_value()
    declared: tuple[bool, ...]
    if contract.metric_key == "prompt.constraint_precision":
        declared = tuple(
            bool(CONSTRAINT_SLOT_PATTERNS[kind].search(request_text))
            for kind in profile.expected_constraint_kinds
        )
    elif contract.metric_key == "prompt.deliverable_contract":
        declared = tuple(
            bool(DELIVERABLE_SLOT_PATTERNS[slot].search(request_text))
            for slot in profile.expected_deliverable_slots
        )
    else:
        expected = profile.expected_outcome_count
        if expected is None:
            declared = ()
        else:
            checkable = int(bool(_CHECK_CUE.search(request_text)))
            declared = tuple(index < checkable for index in range(expected))
    opportunities = tuple(
        _Opportunity(
            unit_id=f"slot-{index}",
            owner_source_digest=f"slot-{index}",
            state=OpportunityState.MET if present else OpportunityState.NOT_MET,
        )
        for index, present in enumerate(declared)
    )
    statistics = _statistics(
        contract,
        opportunities,
        capability_available=True,
        source_complete=source_complete,
    )
    return resolve_metric_state(
        contract,
        statistics,
        explanation_code="declared_profile_slots",
        projection_version=projection_version,
    )


def _objective_state(
    contract: MetricContractV2,
    override: ObjectiveMetricOverride | None,
    *,
    projection_version: str | None = None,
) -> MetricStateV2:
    """Objective precedence: only the typed lane may resolve these contracts."""

    if override is None:
        statistics = _statistics(
            contract,
            (),
            capability_available=False,
            source_complete=False,
        )
        return resolve_metric_state(
            contract,
            statistics,
            explanation_code="typed_objective_absent",
            unavailable_code="typed_objective_absent",
            projection_version=projection_version,
        )
    eligible = override.eligible_opportunity_count
    resolved = override.resolved_opportunity_count
    met = override.met_opportunity_count
    if override.value_state is MetricValueState.KNOWN:
        states = (
            [OpportunityState.MET] * met
            + [OpportunityState.NOT_MET] * (eligible - met)
        )
    elif override.value_state is MetricValueState.NOT_APPLICABLE:
        states = []
    elif eligible == 0:
        statistics = _statistics(
            contract,
            (),
            capability_available=False,
            source_complete=False,
        )
        return resolve_metric_state(
            contract,
            statistics,
            explanation_code=override.explanation_code,
            unavailable_code=override.explanation_code,
            projection_version=projection_version,
        )
    else:
        censored = (
            OpportunityState.PENDING
            if contract.pending_policy
            is PendingPolicy.RIGHT_CENSORED_OPPORTUNITY
            else OpportunityState.UNKNOWN
        )
        states = (
            [OpportunityState.MET] * met
            + [OpportunityState.NOT_MET] * (resolved - met)
            + [censored] * (eligible - resolved)
        )
    opportunities = tuple(
        _Opportunity(
            unit_id=f"objective-{index}",
            owner_source_digest=f"objective-{index}",
            state=state,
        )
        for index, state in enumerate(states)
    )
    statistics = _statistics(
        contract,
        opportunities,
        capability_available=True,
        source_complete=True,
    )
    return resolve_metric_state(
        contract,
        statistics,
        explanation_code=override.explanation_code,
        projection_version=projection_version,
    )


def objective_metric_state(
    contract: MetricContractV2,
    override: ObjectiveMetricOverride | None,
) -> MetricStateV2:
    """Resolve one objective contract from the typed evidence lane only.

    Exposed so a publication seam that has no conversational window can still
    reach exactly the same fail-closed decision instead of reimplementing it.
    """

    if contract.denominator_basis is not DenominatorBasis.OBJECTIVE_OPPORTUNITIES:
        raise ValueError("only objective contracts use the objective lane")
    return _objective_state(contract, override)


def _unit_state(
    contract: MetricContractV2,
    context: P1TextAnalysisInput,
    reconciliation: SemanticUnitReconciliation,
    window: _Window,
    *,
    projection_version: str | None = None,
) -> MetricStateV2:
    kind = contract.opportunity_unit_kind
    assert kind is not None
    source_complete = reconciliation.source_complete
    if kind not in EXTRACTABLE_SEMANTIC_UNIT_KINDS:
        statistics = _statistics(
            contract,
            (),
            capability_available=False,
            source_complete=source_complete,
        )
        return resolve_metric_state(
            contract,
            statistics,
            explanation_code="opportunity_family_unobservable",
            projection_version=projection_version,
        )
    if contract.opportunity_selector is OpportunitySelector.CANONICAL_ACTIVE_REVISION:
        raise ValueError("canonical revision contracts use the rubric projection")
    heads, superseded = _active_heads(reconciliation, kind)
    builder = _UNIT_OPPORTUNITY_BUILDERS[contract.metric_key]
    opportunities = builder(heads, window)
    statistics = _statistics(
        contract,
        opportunities,
        capability_available=True,
        source_complete=source_complete,
        superseded_excluded=superseded,
    )
    return resolve_metric_state(
        contract,
        statistics,
        explanation_code=_UNIT_EXPLANATIONS[contract.metric_key],
        projection_version=projection_version,
    )


def project_metric_states_v2(
    *,
    context: P1TextAnalysisInput,
    reconciliation: SemanticUnitReconciliation | None,
    id_factory: SemanticUnitIdFactory,
    conversational_results: Mapping[str, TextMetricResult] | None = None,
    objective_overrides: Mapping[str, ObjectiveMetricOverride] | None = None,
) -> LiveMetricStateProjectionV2:
    """Project all twenty V2 contracts in registry order.

    ``reconciliation`` is the persisted semantic-unit head set for the same
    analysis window.  Without it no unit-based denominator exists and those
    contracts stay unknown rather than falling back to a lexical count.
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
    # Request revisions exist, but none of them owns the scored focus message.
    focus_unowned = revision is not None and focus_revision is None
    # A fixed rubric or declared profile belongs to the canonical request in
    # the explicitly requested bounded scope. It does not require proof that
    # the provider supplied the whole session. Cross-turn semantic episodes do:
    # they continue to use the reconciliation's stricter completeness flag.
    requested_scope_complete = context.requested_scope_complete or (
        context.analysis_scope is None
        and context.window_complete
        and context.text_extraction_complete
    )
    states: list[MetricStateV2] = []
    for contract in METRIC_CONTRACTS_V2:
        if contract.denominator_basis is DenominatorBasis.OBJECTIVE_OPPORTUNITIES:
            states.append(
                _objective_state(contract, objective.get(contract.metric_key))
            )
        elif contract.denominator_basis is DenominatorBasis.DECLARED_PROFILE_SLOTS:
            states.append(
                _profile_slot_state(
                    contract,
                    context,
                    revision,
                    window,
                    source_complete=requested_scope_complete,
                )
            )
        elif contract.denominator_basis is DenominatorBasis.RUBRIC_FACTORS:
            states.append(
                _rubric_state(
                    contract,
                    conversational.get(contract.metric_key),
                    focus_revision,
                    focus_unowned=focus_unowned,
                    source_complete=requested_scope_complete,
                )
            )
        elif reconciliation is None:
            statistics = _statistics(
                contract,
                (),
                capability_available=True,
                source_complete=False,
            )
            states.append(
                resolve_metric_state(
                    contract,
                    statistics,
                    explanation_code="semantic_units_unavailable",
                )
            )
        else:
            states.append(_unit_state(contract, context, reconciliation, window))
    projection = _issue_metric_state_projection(states, compatibility=False)
    if not isinstance(projection, LiveMetricStateProjectionV2):
        raise AssertionError("live projection issuer returned the wrong envelope")
    return projection


__all__ = [
    "METRIC_PROJECTION_V2_ALGORITHM_ID",
    "METRIC_PROJECTION_V2_ALGORITHM_VERSION",
    "METRIC_PROJECTION_V2_VERSION",
    "METRIC_PROJECTION_V2_VERSION_1",
    "METRIC_PROJECTION_V2_VERSION_2",
    "METRIC_PROJECTION_V2_VERSION_3",
    "METRIC_PROJECTION_V2_VERSION_4",
    "METRIC_PROJECTION_V2_VERSION_5",
    "METRIC_PROJECTION_V2_VERSION_6",
    "METRIC_PROJECTION_V2_VERSION_7",
    "METRIC_PROJECTION_V2_VERSION_8",
    "MetricProjectionV2Version",
    "MetricStateV2",
    "OpportunityStatistics",
    "REASON_RUBRIC_NOT_FOCUS_OWNED",
    "REWORK_CLASSIFIER_VERSION",
    "SUPPORTED_METRIC_PROJECTION_V2_VERSIONS",
    "classify_feedback_rework",
    "objective_metric_state",
    "project_metric_states_v2",
    "resolve_metric_state",
]
