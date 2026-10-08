"""Current all-twenty measurement paths, derived from reviewed contracts.

This catalog answers a narrower question than a session readiness receipt:
*does the shipped application have a defensible path that could resolve this
metric when its required evidence exists?*  It never promises that a particular
session has that evidence and it never treats an experimental model estimate as
measurement authority.

The catalog is intentionally computed from the same frozen contracts, task
profile, lifecycle registry, semantic-unit capability set, and default typed
evidence descriptor that the live service composes.  It is therefore useful as
a product/release gate: a new adapter or configured denominator must change the
underlying authority first, not a dashboard label.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from ...domain import StrictModel
from .metric_contract_v2 import (
    METRIC_CONTRACT_REGISTRY_VERSION_V2,
    METRIC_CONTRACTS_V2,
    DenominatorBasis,
    EvidenceAuthority,
    MetricContractV2,
    metric_contract_v2_set_fingerprint,
)
from .metric_evidence_readiness_v2 import (
    METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION,
    METRIC_EVIDENCE_REQUIREMENTS_V2,
)
from .metric_lifecycle_evidence import MetricLifecycleFamily
from .metric_projection_v2 import METRIC_PROJECTION_V2_VERSION_8
from .metric_projection_v3 import OPEN_LOOP_METRIC_KEY
from .probabilistic_metrics import (
    EVIDENCE_LANE_METRIC_KEYS,
    PROBABILISTIC_METRIC_CONTRACTS,
)
from .provider_evidence import CURRENT_SAFE_EVENT_EVIDENCE_CAPABILITIES
from .semantic_units import EXTRACTABLE_SEMANTIC_UNIT_KINDS


METRIC_OPERABILITY_CATALOG_VERSION = "metric-operability-v4"


class MetricMeasuredPath(StrEnum):
    FOCUS_RUBRIC = "focus_rubric"
    DECLARED_TASK_PROFILE = "declared_task_profile"
    CONFIRMED_LIFECYCLE = "confirmed_lifecycle"
    DOCUMENTED_SEMANTIC_UNIT = "documented_semantic_unit"
    EXPLICIT_PLAN_LINK = "explicit_plan_link"
    TASK_SCOPED_VERIFICATION = "task_scoped_verification"
    TYPED_OBJECTIVE = "typed_objective"
    SEMANTIC_UNIT_EXTRACTOR = "semantic_unit_extractor"
    REVIEWED_REQUIREMENT_PLAN = "reviewed_requirement_plan"
    REVIEWED_REQUIREMENT_ACTION = "reviewed_requirement_action"


class MetricShippedPathState(StrEnum):
    AVAILABLE_WHEN_EVIDENCE_EXISTS = "available_when_evidence_exists"
    TASK_PROFILE_CONFIGURATION_REQUIRED = "task_profile_configuration_required"
    PROVIDER_ADAPTER_REQUIRED = "provider_adapter_required"


class MetricNextStepCode(StrEnum):
    ANALYZE_FOCUS_REQUEST = "analyze_focus_request"
    DECLARE_TASK_PROFILE = "declare_task_profile"
    CONFIRM_LIFECYCLE_EVIDENCE = "confirm_lifecycle_evidence"
    RECORD_DOCUMENTED_DECISION = "record_documented_decision"
    LINK_PLAN_SUPERSESSION = "link_plan_supersession"
    RECORD_TASK_SCOPED_VERIFICATION = "record_task_scoped_verification"
    ADD_OBJECTIVE_OPPORTUNITY_LINK_ADAPTER = (
        "add_objective_opportunity_link_adapter"
    )
    ADD_REQUIREMENT_PLAN_EXTRACTOR = "add_requirement_plan_extractor"
    CONFIRM_REQUIREMENT_PLAN_EVIDENCE = "confirm_requirement_plan_evidence"
    COMPOSE_REQUIREMENT_ACTION_EVIDENCE = (
        "compose_requirement_action_evidence"
    )


class MetricOperabilityEntry(StrictModel):
    metric_key: str
    contract_version: str
    contract_fingerprint: str
    evidence_authority: EvidenceAuthority
    denominator_basis: DenominatorBasis
    measured_path: MetricMeasuredPath
    shipped_path_state: MetricShippedPathState
    next_step_code: MetricNextStepCode
    experimental_model_path: bool
    measured_value_may_use_model_output: Literal[False] = False


class MetricOperabilityCatalog(StrictModel):
    catalog_version: Literal[METRIC_OPERABILITY_CATALOG_VERSION] = (
        METRIC_OPERABILITY_CATALOG_VERSION
    )
    registry_version: Literal[METRIC_CONTRACT_REGISTRY_VERSION_V2] = (
        METRIC_CONTRACT_REGISTRY_VERSION_V2
    )
    contract_set_fingerprint: str
    projection_version: Literal[METRIC_PROJECTION_V2_VERSION_8] = (
        METRIC_PROJECTION_V2_VERSION_8
    )
    readiness_catalog_version: Literal[
        METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION
    ] = METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION
    total_metric_count: Literal[20] = 20
    shipped_path_count: int = Field(ge=0, le=20)
    task_profile_configuration_gap_count: int = Field(ge=0, le=20)
    provider_adapter_gap_count: int = Field(ge=0, le=20)
    experimental_model_path_count: int = Field(ge=0, le=20)
    model_authoritative_metric_count: Literal[0] = 0
    entries: tuple[MetricOperabilityEntry, ...] = Field(min_length=20, max_length=20)
    local_only: Literal[True] = True
    content_persisted: Literal[False] = False

    @model_validator(mode="after")
    def exact_partition(self) -> "MetricOperabilityCatalog":
        expected = tuple(contract.metric_key for contract in METRIC_CONTRACTS_V2)
        if tuple(item.metric_key for item in self.entries) != expected:
            raise ValueError("metric operability must preserve the contract order")
        available = sum(
            item.shipped_path_state
            is MetricShippedPathState.AVAILABLE_WHEN_EVIDENCE_EXISTS
            for item in self.entries
        )
        profile_gaps = sum(
            item.shipped_path_state
            is MetricShippedPathState.TASK_PROFILE_CONFIGURATION_REQUIRED
            for item in self.entries
        )
        adapter_gaps = sum(
            item.shipped_path_state
            is MetricShippedPathState.PROVIDER_ADAPTER_REQUIRED
            for item in self.entries
        )
        model_paths = sum(item.experimental_model_path for item in self.entries)
        if (
            available != self.shipped_path_count
            or profile_gaps != self.task_profile_configuration_gap_count
            or adapter_gaps != self.provider_adapter_gap_count
            or model_paths != self.experimental_model_path_count
            or available + profile_gaps + adapter_gaps != self.total_metric_count
            or any(item.measured_value_may_use_model_output for item in self.entries)
        ):
            raise ValueError("metric operability counts do not preserve the catalog")
        return self


_LIFECYCLE_KEYS = frozenset(family.value for family in MetricLifecycleFamily)
_EXPERIMENTAL_MODEL_KEYS = frozenset(
    contract.metric_key
    for contract in PROBABILISTIC_METRIC_CONTRACTS
    if (
        contract.metric_key not in EVIDENCE_LANE_METRIC_KEYS
        and not contract.objective_evidence_required
        and contract.closure_horizon == "immediate"
    )
)


def _entry(contract: MetricContractV2) -> MetricOperabilityEntry:
    key = contract.metric_key
    if key in _LIFECYCLE_KEYS:
        measured_path = MetricMeasuredPath.CONFIRMED_LIFECYCLE
        state = MetricShippedPathState.AVAILABLE_WHEN_EVIDENCE_EXISTS
        next_step = MetricNextStepCode.CONFIRM_LIFECYCLE_EVIDENCE
    elif key == OPEN_LOOP_METRIC_KEY:
        measured_path = MetricMeasuredPath.EXPLICIT_PLAN_LINK
        state = MetricShippedPathState.AVAILABLE_WHEN_EVIDENCE_EXISTS
        next_step = MetricNextStepCode.LINK_PLAN_SUPERSESSION
    elif key == "logic.decomposition_coverage":
        measured_path = MetricMeasuredPath.REVIEWED_REQUIREMENT_PLAN
        state = MetricShippedPathState.AVAILABLE_WHEN_EVIDENCE_EXISTS
        next_step = MetricNextStepCode.CONFIRM_REQUIREMENT_PLAN_EVIDENCE
    elif key == "logic.requirement_action_traceability":
        # R8 is the current publication identity. Keep the path unavailable in
        # this catalog until a production provider proves a complete safe-event
        # and redacted-descriptor review surface; UI composition alone is not
        # operability.
        measured_path = MetricMeasuredPath.REVIEWED_REQUIREMENT_ACTION
        state = MetricShippedPathState.PROVIDER_ADAPTER_REQUIRED
        next_step = MetricNextStepCode.COMPOSE_REQUIREMENT_ACTION_EVIDENCE
    elif contract.denominator_basis is DenominatorBasis.RUBRIC_FACTORS:
        measured_path = MetricMeasuredPath.FOCUS_RUBRIC
        state = MetricShippedPathState.AVAILABLE_WHEN_EVIDENCE_EXISTS
        next_step = MetricNextStepCode.ANALYZE_FOCUS_REQUEST
    elif contract.denominator_basis is DenominatorBasis.DECLARED_PROFILE_SLOTS:
        measured_path = MetricMeasuredPath.DECLARED_TASK_PROFILE
        state = MetricShippedPathState.AVAILABLE_WHEN_EVIDENCE_EXISTS
        next_step = MetricNextStepCode.DECLARE_TASK_PROFILE
    elif contract.denominator_basis is DenominatorBasis.OBJECTIVE_OPPORTUNITIES:
        required = set(
            METRIC_EVIDENCE_REQUIREMENTS_V2[key].required_adapter_capabilities
        )
        available = required <= CURRENT_SAFE_EVENT_EVIDENCE_CAPABILITIES
        measured_path = (
            MetricMeasuredPath.TASK_SCOPED_VERIFICATION
            if key == "outcome.first_pass_verification"
            else MetricMeasuredPath.TYPED_OBJECTIVE
        )
        state = (
            MetricShippedPathState.AVAILABLE_WHEN_EVIDENCE_EXISTS
            if available
            else MetricShippedPathState.PROVIDER_ADAPTER_REQUIRED
        )
        next_step = (
            MetricNextStepCode.RECORD_TASK_SCOPED_VERIFICATION
            if available
            else MetricNextStepCode.ADD_OBJECTIVE_OPPORTUNITY_LINK_ADAPTER
        )
    elif contract.opportunity_unit_kind in EXTRACTABLE_SEMANTIC_UNIT_KINDS:
        measured_path = MetricMeasuredPath.DOCUMENTED_SEMANTIC_UNIT
        state = MetricShippedPathState.AVAILABLE_WHEN_EVIDENCE_EXISTS
        next_step = MetricNextStepCode.RECORD_DOCUMENTED_DECISION
    else:
        measured_path = MetricMeasuredPath.SEMANTIC_UNIT_EXTRACTOR
        state = MetricShippedPathState.PROVIDER_ADAPTER_REQUIRED
        next_step = MetricNextStepCode.ADD_REQUIREMENT_PLAN_EXTRACTOR
    return MetricOperabilityEntry(
        metric_key=key,
        contract_version=contract.contract_version,
        contract_fingerprint=contract.fingerprint,
        evidence_authority=contract.evidence_authority,
        denominator_basis=contract.denominator_basis,
        measured_path=measured_path,
        shipped_path_state=state,
        next_step_code=next_step,
        experimental_model_path=key in _EXPERIMENTAL_MODEL_KEYS,
    )


def metric_operability_catalog() -> MetricOperabilityCatalog:
    entries = tuple(_entry(contract) for contract in METRIC_CONTRACTS_V2)
    return MetricOperabilityCatalog(
        contract_set_fingerprint=metric_contract_v2_set_fingerprint(),
        shipped_path_count=sum(
            item.shipped_path_state
            is MetricShippedPathState.AVAILABLE_WHEN_EVIDENCE_EXISTS
            for item in entries
        ),
        task_profile_configuration_gap_count=sum(
            item.shipped_path_state
            is MetricShippedPathState.TASK_PROFILE_CONFIGURATION_REQUIRED
            for item in entries
        ),
        provider_adapter_gap_count=sum(
            item.shipped_path_state
            is MetricShippedPathState.PROVIDER_ADAPTER_REQUIRED
            for item in entries
        ),
        experimental_model_path_count=sum(
            item.experimental_model_path for item in entries
        ),
        entries=entries,
    )


__all__ = (
    "METRIC_OPERABILITY_CATALOG_VERSION",
    "MetricMeasuredPath",
    "MetricNextStepCode",
    "MetricOperabilityCatalog",
    "MetricOperabilityEntry",
    "MetricShippedPathState",
    "metric_operability_catalog",
)
