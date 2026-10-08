"""Content-free provider capability and coaching-metric readiness projections.

Readiness is deliberately separate from metric calculation.  It combines a
versioned, reviewed evidence-requirement catalog with cached provider
compatibility and already-persisted result states.  It never refreshes a
provider, reads a transcript, or substitutes a missing value with zero.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import Field, field_validator, model_validator

from ...domain import DataTier, Provider, SafeSession, StrictModel
from ..persistence import (
    AnalysisRunStatus,
    MetricValueState,
    SessionAnalysisResultRecord,
    SessionAnalysisRunRecord,
    SessionAnalysisRunRepository,
    SessionMetricScopeState,
)
from ..providers import (
    CapabilityKey,
    CapabilityState,
    CompatibilityState,
    DecoderDescriptor,
    ProviderCompatibilityReport,
    ProviderSurface,
)
from .coaching_baselines import (
    COACHING_EVIDENCE_CAPABILITY_CATALOG_VERSION,
    COACHING_METRIC_DEFINITIONS,
)
from .text_analysis_presets import COACHING_PROFILE_V1, TextAnalysisPresetId
from .text_contracts import MetricDirection, TextMetricDefinition


METRIC_READINESS_CATALOG_VERSION = (
    COACHING_EVIDENCE_CAPABILITY_CATALOG_VERSION
)


class MetricEvidenceCapability(StrEnum):
    """Provider evidence families used by the reviewed coaching pack."""

    REQUEST_TEXT = "request_text"
    RESPONSE_TEXT = "response_text"
    PLAN_TEXT = "plan_text"
    ACTION_EVIDENCE = "action_evidence"
    DECISION_EVIDENCE = "decision_evidence"
    FEEDBACK_TEXT = "feedback_text"
    OBJECTIVE_VERIFICATION = "objective_verification"


class ProviderMetricCapabilityState(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class ProviderMetricCapabilityReason(StrEnum):
    VERIFIED_BY_COMPATIBLE_DECODER = "verified_by_compatible_decoder"
    NOT_DECLARED_BY_DECODER = "not_declared_by_decoder"
    PROVIDER_ADAPTER_UNAVAILABLE = "provider_adapter_unavailable"
    COMPATIBILITY_NOT_CHECKED = "compatibility_not_checked"
    PROVIDER_INCOMPATIBLE = "provider_incompatible"
    CAPABILITY_NOT_OBSERVED = "capability_not_observed"
    CAPABILITY_UNVERIFIED = "capability_unverified"


class MetricReadinessState(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"
    ABSTAINED = "abstained"
    INCOMPATIBLE = "incompatible"
    NOT_APPLICABLE = "not_applicable"
    FAILED = "failed"


class MetricReadinessReason(StrEnum):
    MEASURED = "measured"
    ANALYSIS_NOT_RUN = "analysis_not_run"
    ANALYSIS_IN_PROGRESS = "analysis_in_progress"
    RESULT_UNKNOWN = "result_unknown"
    RESULT_ABSTAINED = "result_abstained"
    EXPLICITLY_NOT_APPLICABLE = "explicitly_not_applicable"
    PROVIDER_CAPABILITY_MISSING = "provider_capability_missing"
    PROVIDER_ADAPTER_UNAVAILABLE = "provider_adapter_unavailable"
    PROVIDER_COMPATIBILITY_UNVERIFIED = "provider_compatibility_unverified"
    PROVIDER_INCOMPATIBLE = "provider_incompatible"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    ANALYSIS_FAILED = "analysis_failed"
    RESULT_FAILED = "result_failed"
    RESULT_MISSING = "result_missing"
    METRIC_NOT_SELECTED = "metric_not_selected"
    METRIC_SCOPE_UNKNOWN = "metric_scope_unknown"


class MetricReadinessAction(StrEnum):
    NONE = "none"
    RUN_LOCAL_ANALYSIS = "run_local_analysis"
    CHECK_PROVIDER_COMPATIBILITY = "check_provider_compatibility"
    UPDATE_PROVIDER_ADAPTER = "update_provider_adapter"
    COLLECT_ACTION_EVIDENCE = "collect_action_evidence"
    COLLECT_DECISION_EVIDENCE = "collect_decision_evidence"
    COLLECT_FEEDBACK_EVIDENCE = "collect_feedback_evidence"
    COLLECT_OBJECTIVE_VERIFICATION = "collect_objective_verification"
    REVIEW_APPLICABILITY = "review_applicability"
    REVIEW_EVIDENCE_COVERAGE = "review_evidence_coverage"
    RETRY_ANALYSIS = "retry_analysis"
    SELECT_METRIC_FOR_ANALYSIS = "select_metric_for_analysis"


class MetricRadarPolicy(StrEnum):
    """Server-owned plotting policy; clients never infer or invert direction."""

    DIRECT_BOUNDED_RATIO = "direct_bounded_ratio"
    EXACT_VALUE_ONLY_UNNORMALIZED_LOWER_IS_BETTER = (
        "exact_value_only_unnormalized_lower_is_better"
    )


class MetricEvidenceRequirement(StrictModel):
    """AND-of-OR capability groups for one exact metric definition."""

    metric_key: str
    metric_version: int = Field(ge=1)
    catalog_version: str = METRIC_READINESS_CATALOG_VERSION
    capability_groups: tuple[tuple[MetricEvidenceCapability, ...], ...] = Field(
        min_length=1
    )

    @field_validator("capability_groups")
    @classmethod
    def validate_groups(
        cls,
        groups: tuple[tuple[MetricEvidenceCapability, ...], ...],
    ) -> tuple[tuple[MetricEvidenceCapability, ...], ...]:
        normalized: list[tuple[MetricEvidenceCapability, ...]] = []
        for group in groups:
            if not group or len(set(group)) != len(group):
                raise ValueError("metric capability alternatives must be unique")
            normalized.append(tuple(sorted(group, key=lambda item: item.value)))
        if len(set(normalized)) != len(normalized):
            raise ValueError("metric capability groups must be unique")
        return tuple(normalized)


class ProviderMetricCapability(StrictModel):
    capability: MetricEvidenceCapability
    state: ProviderMetricCapabilityState
    reason_code: ProviderMetricCapabilityReason


class ProviderCapabilityReport(StrictModel):
    """Content-free capability projection for the coaching metric catalog."""

    provider: Provider
    surface: ProviderSurface = ProviderSurface.TEXT_WINDOW
    catalog_version: str = METRIC_READINESS_CATALOG_VERSION
    compatibility_state: CompatibilityState
    provider_version: str | None = None
    decoder_key: str | None = None
    decoder_version: str | None = None
    checked_at: datetime | None = None
    capabilities: tuple[ProviderMetricCapability, ...]
    structurally_attemptable_metric_count: int = Field(ge=0)
    structurally_unsupported_metric_count: int = Field(ge=0)
    structurally_unknown_metric_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> ProviderCapabilityReport:
        capability_keys = tuple(item.capability for item in self.capabilities)
        if len(set(capability_keys)) != len(capability_keys):
            raise ValueError("provider metric capabilities cannot contain duplicates")
        if set(capability_keys) != set(MetricEvidenceCapability):
            raise ValueError("provider metric capability projection is incomplete")
        if (
            self.structurally_attemptable_metric_count
            + self.structurally_unsupported_metric_count
            + self.structurally_unknown_metric_count
            != len(COACHING_METRIC_REQUIREMENTS)
        ):
            raise ValueError("provider metric capability counts are inconsistent")
        return self


class MetricReadiness(StrictModel):
    metric_key: str
    metric_version: int = Field(ge=1)
    dimension: str
    display_name: str
    unit: str
    direction: MetricDirection
    radar_policy: MetricRadarPolicy
    evidence_tier: DataTier
    state: MetricReadinessState
    reason_code: MetricReadinessReason
    next_actions: tuple[MetricReadinessAction, ...]
    capability_groups: tuple[tuple[MetricEvidenceCapability, ...], ...]
    available_capabilities: tuple[MetricEvidenceCapability, ...] = ()
    missing_capabilities: tuple[MetricEvidenceCapability, ...] = ()
    latest_run_id: str | None = None

    @field_validator("next_actions")
    @classmethod
    def unique_actions(
        cls, values: tuple[MetricReadinessAction, ...]
    ) -> tuple[MetricReadinessAction, ...]:
        if not values or len(set(values)) != len(values):
            raise ValueError("metric readiness actions must be nonempty and unique")
        return values

    @field_validator("available_capabilities", "missing_capabilities")
    @classmethod
    def unique_capabilities(
        cls, values: tuple[MetricEvidenceCapability, ...]
    ) -> tuple[MetricEvidenceCapability, ...]:
        if len(set(values)) != len(values):
            raise ValueError("metric readiness capabilities must be unique")
        return values


class SessionMetricReadinessReport(StrictModel):
    session_id: str
    provider: Provider
    preset_id: TextAnalysisPresetId
    analysis_profile_key: str
    analysis_profile_version: int = Field(ge=1)
    metric_pack_key: str
    metric_pack_version: int = Field(ge=1)
    capability_report: ProviderCapabilityReport
    metrics: tuple[MetricReadiness, ...]


class MetricReadinessStore(Protocol):
    def get_session(self, session_id: str) -> SafeSession | None: ...


class ProviderReadinessCatalog(Protocol):
    def descriptor(
        self, provider: str, surface: ProviderSurface
    ) -> DecoderDescriptor: ...

    def get_cached(
        self, provider: str, surface: ProviderSurface
    ) -> ProviderCompatibilityReport | None: ...


class MetricReadinessSessionNotFoundError(LookupError):
    pass


class MetricReadinessPresetUnsupportedError(ValueError):
    pass


_PROVIDER_CAPABILITY_MAP: dict[MetricEvidenceCapability, CapabilityKey | None] = {
    MetricEvidenceCapability.REQUEST_TEXT: CapabilityKey.USER_MESSAGES,
    MetricEvidenceCapability.RESPONSE_TEXT: CapabilityKey.AGENT_MESSAGES,
    MetricEvidenceCapability.PLAN_TEXT: CapabilityKey.PLAN_MESSAGES,
    MetricEvidenceCapability.ACTION_EVIDENCE: CapabilityKey.TOOL_EVENTS,
    MetricEvidenceCapability.DECISION_EVIDENCE: CapabilityKey.DECISION_EVENTS,
    MetricEvidenceCapability.FEEDBACK_TEXT: CapabilityKey.FEEDBACK_MESSAGES,
    MetricEvidenceCapability.OBJECTIVE_VERIFICATION: (
        CapabilityKey.VERIFICATION_EVENTS
    ),
}


def _groups(
    *groups: tuple[MetricEvidenceCapability, ...],
) -> tuple[tuple[MetricEvidenceCapability, ...], ...]:
    return groups


_REQUEST_OR_FEEDBACK = (
    MetricEvidenceCapability.REQUEST_TEXT,
    MetricEvidenceCapability.FEEDBACK_TEXT,
)


_REQUIREMENT_GROUPS: dict[
    str, tuple[tuple[MetricEvidenceCapability, ...], ...]
] = {
    "prompt.task_definition_coverage": _groups(_REQUEST_OR_FEEDBACK),
    "prompt.problem_evidence_quality": _groups(_REQUEST_OR_FEEDBACK),
    "prompt.context_sufficiency": _groups(_REQUEST_OR_FEEDBACK),
    "prompt.constraint_precision": _groups(_REQUEST_OR_FEEDBACK),
    "prompt.acceptance_testability": _groups(_REQUEST_OR_FEEDBACK),
    "prompt.deliverable_contract": _groups(_REQUEST_OR_FEEDBACK),
    "collaboration.ambiguity_resolution": _groups(_REQUEST_OR_FEEDBACK),
    "collaboration.clarification_yield": _groups(
        (MetricEvidenceCapability.RESPONSE_TEXT,),
        _REQUEST_OR_FEEDBACK,
    ),
    "collaboration.exploration_conversion": _groups(
        (
            MetricEvidenceCapability.REQUEST_TEXT,
            MetricEvidenceCapability.RESPONSE_TEXT,
            MetricEvidenceCapability.PLAN_TEXT,
        ),
    ),
    "collaboration.scope_change_discipline": _groups(_REQUEST_OR_FEEDBACK),
    "collaboration.rework_candidate_rate": _groups(
        (MetricEvidenceCapability.RESPONSE_TEXT,),
        (MetricEvidenceCapability.FEEDBACK_TEXT,),
    ),
    "logic.decomposition_coverage": _groups(
        _REQUEST_OR_FEEDBACK,
        (MetricEvidenceCapability.PLAN_TEXT,),
    ),
    "logic.hypothesis_test_linkage": _groups(
        (MetricEvidenceCapability.OBJECTIVE_VERIFICATION,),
    ),
    "logic.decision_rationale_coverage": _groups(
        (MetricEvidenceCapability.DECISION_EVIDENCE,),
    ),
    "logic.requirement_action_traceability": _groups(
        _REQUEST_OR_FEEDBACK,
        (MetricEvidenceCapability.ACTION_EVIDENCE,),
    ),
    "logic.open_loop_closure": _groups(
        (
            MetricEvidenceCapability.REQUEST_TEXT,
            MetricEvidenceCapability.FEEDBACK_TEXT,
            MetricEvidenceCapability.RESPONSE_TEXT,
        ),
    ),
    "outcome.agent_claim_grounding": _groups(
        (MetricEvidenceCapability.RESPONSE_TEXT,),
        (MetricEvidenceCapability.OBJECTIVE_VERIFICATION,),
    ),
    "outcome.verification_strategy_adequacy": _groups(
        _REQUEST_OR_FEEDBACK,
        (
            MetricEvidenceCapability.PLAN_TEXT,
            MetricEvidenceCapability.RESPONSE_TEXT,
            MetricEvidenceCapability.OBJECTIVE_VERIFICATION,
        ),
    ),
    "outcome.first_pass_verification": _groups(
        (MetricEvidenceCapability.OBJECTIVE_VERIFICATION,),
    ),
    "outcome.verified_requirement_coverage": _groups(
        _REQUEST_OR_FEEDBACK,
        (MetricEvidenceCapability.OBJECTIVE_VERIFICATION,),
    ),
}


COACHING_METRIC_REQUIREMENTS = tuple(
    MetricEvidenceRequirement(
        metric_key=definition.key,
        metric_version=definition.version,
        capability_groups=_REQUIREMENT_GROUPS[definition.key],
    )
    for definition in COACHING_METRIC_DEFINITIONS
)

if set(_REQUIREMENT_GROUPS) != {
    definition.key for definition in COACHING_METRIC_DEFINITIONS
}:
    raise RuntimeError("coaching metric capability catalog is incomplete")


_ACTION_FOR_CAPABILITY = {
    MetricEvidenceCapability.ACTION_EVIDENCE: (
        MetricReadinessAction.COLLECT_ACTION_EVIDENCE
    ),
    MetricEvidenceCapability.DECISION_EVIDENCE: (
        MetricReadinessAction.COLLECT_DECISION_EVIDENCE
    ),
    MetricEvidenceCapability.FEEDBACK_TEXT: (
        MetricReadinessAction.COLLECT_FEEDBACK_EVIDENCE
    ),
    MetricEvidenceCapability.OBJECTIVE_VERIFICATION: (
        MetricReadinessAction.COLLECT_OBJECTIVE_VERIFICATION
    ),
}


class MetricReadinessService:
    """Project cached capability and persisted state without provider access."""

    def __init__(
        self,
        store: MetricReadinessStore,
        runs: SessionAnalysisRunRepository,
        providers: ProviderReadinessCatalog,
    ) -> None:
        self._store = store
        self._runs = runs
        self._providers = providers
        self._requirements = {
            (item.metric_key, item.metric_version): item
            for item in COACHING_METRIC_REQUIREMENTS
        }

    def provider_capabilities(self, provider: Provider) -> ProviderCapabilityReport:
        descriptor, report = self._cached_provider_state(provider)
        declared = set() if descriptor is None else set(descriptor.capabilities)
        observations = (
            {}
            if report is None
            else {item.key: item.state for item in report.capabilities}
        )
        capabilities = tuple(
            self._project_capability(
                capability,
                descriptor=descriptor,
                report=report,
                declared=declared,
                observations=observations,
            )
            for capability in MetricEvidenceCapability
        )
        structurally_available = {
            item.capability
            for item in capabilities
            if item.reason_code
            is not ProviderMetricCapabilityReason.NOT_DECLARED_BY_DECODER
            and item.reason_code
            is not ProviderMetricCapabilityReason.PROVIDER_ADAPTER_UNAVAILABLE
        }
        attemptable = sum(
            self._requirements_satisfied(item, structurally_available)
            for item in COACHING_METRIC_REQUIREMENTS
        )
        unknown = (
            len(COACHING_METRIC_REQUIREMENTS) if descriptor is None else 0
        )
        unsupported = (
            0
            if descriptor is None
            else len(COACHING_METRIC_REQUIREMENTS) - attemptable
        )
        return ProviderCapabilityReport(
            provider=provider,
            compatibility_state=(
                CompatibilityState.UNTESTED if report is None else report.state
            ),
            provider_version=None if report is None else report.provider_version,
            decoder_key=None if descriptor is None else descriptor.decoder_key,
            decoder_version=None if descriptor is None else descriptor.decoder_version,
            checked_at=None if report is None else report.checked_at,
            capabilities=capabilities,
            structurally_attemptable_metric_count=attemptable,
            structurally_unsupported_metric_count=unsupported,
            structurally_unknown_metric_count=unknown,
        )

    def session_readiness(
        self,
        session_id: str,
        *,
        preset_id: TextAnalysisPresetId = TextAnalysisPresetId.COACHING_PROFILE_V1,
    ) -> SessionMetricReadinessReport:
        if preset_id is not TextAnalysisPresetId.COACHING_PROFILE_V1:
            raise MetricReadinessPresetUnsupportedError(
                "metric readiness preset is unsupported"
            )
        session = self._store.get_session(session_id)
        if session is None:
            raise MetricReadinessSessionNotFoundError(
                "metric readiness session is unavailable"
            )
        capability_report = self.provider_capabilities(session.provider)
        latest = self._runs.get_latest_for_profile(
            session_id,
            analysis_profile_key=COACHING_PROFILE_V1.analysis_profile_key,
            analysis_profile_version=COACHING_PROFILE_V1.analysis_profile_version,
            metric_pack_key=COACHING_PROFILE_V1.metric_pack_key,
            metric_pack_version=COACHING_PROFILE_V1.metric_pack_version,
        )
        results = (
            ()
            if latest is None or latest.status is not AnalysisRunStatus.COMPLETED
            else self._runs.get_results(latest.draft.run_id)
        )
        result_index = {
            (item.observation.key, item.observation.version): item for item in results
        }
        capability_index = {
            item.capability: item for item in capability_report.capabilities
        }
        metrics = tuple(
            self._metric_readiness(
                definition=definition,
                requirement=self._requirements[(definition.key, definition.version)],
                capability_report=capability_report,
                capability_index=capability_index,
                latest=latest,
                result=result_index.get((definition.key, definition.version)),
            )
            for definition in COACHING_METRIC_DEFINITIONS
        )
        return SessionMetricReadinessReport(
            session_id=session_id,
            provider=session.provider,
            preset_id=preset_id,
            analysis_profile_key=COACHING_PROFILE_V1.analysis_profile_key,
            analysis_profile_version=COACHING_PROFILE_V1.analysis_profile_version,
            metric_pack_key=COACHING_PROFILE_V1.metric_pack_key,
            metric_pack_version=COACHING_PROFILE_V1.metric_pack_version,
            capability_report=capability_report,
            metrics=metrics,
        )

    def _cached_provider_state(
        self, provider: Provider
    ) -> tuple[DecoderDescriptor | None, ProviderCompatibilityReport | None]:
        try:
            descriptor = self._providers.descriptor(
                provider.value, ProviderSurface.TEXT_WINDOW
            )
        except Exception:
            return None, None
        try:
            report = self._providers.get_cached(
                provider.value, ProviderSurface.TEXT_WINDOW
            )
        except Exception:
            report = None
        return descriptor, report

    @staticmethod
    def _project_capability(
        capability: MetricEvidenceCapability,
        *,
        descriptor: DecoderDescriptor | None,
        report: ProviderCompatibilityReport | None,
        declared: set[CapabilityKey],
        observations: dict[CapabilityKey, CapabilityState],
    ) -> ProviderMetricCapability:
        provider_capability = _PROVIDER_CAPABILITY_MAP[capability]
        if descriptor is None:
            return ProviderMetricCapability(
                capability=capability,
                state=ProviderMetricCapabilityState.UNKNOWN,
                reason_code=(
                    ProviderMetricCapabilityReason.PROVIDER_ADAPTER_UNAVAILABLE
                ),
            )
        if provider_capability is None or provider_capability not in declared:
            return ProviderMetricCapability(
                capability=capability,
                state=ProviderMetricCapabilityState.UNSUPPORTED,
                reason_code=ProviderMetricCapabilityReason.NOT_DECLARED_BY_DECODER,
            )
        if report is None:
            return ProviderMetricCapability(
                capability=capability,
                state=ProviderMetricCapabilityState.UNKNOWN,
                reason_code=ProviderMetricCapabilityReason.COMPATIBILITY_NOT_CHECKED,
            )
        if report.state not in {
            CompatibilityState.EXACT,
            CompatibilityState.COMPATIBLE,
        }:
            return ProviderMetricCapability(
                capability=capability,
                state=ProviderMetricCapabilityState.UNKNOWN,
                reason_code=ProviderMetricCapabilityReason.PROVIDER_INCOMPATIBLE,
            )
        observation = observations.get(provider_capability)
        if observation is CapabilityState.SUPPORTED:
            return ProviderMetricCapability(
                capability=capability,
                state=ProviderMetricCapabilityState.SUPPORTED,
                reason_code=(
                    ProviderMetricCapabilityReason.VERIFIED_BY_COMPATIBLE_DECODER
                ),
            )
        if observation is CapabilityState.UNSUPPORTED:
            return ProviderMetricCapability(
                capability=capability,
                state=ProviderMetricCapabilityState.UNSUPPORTED,
                reason_code=ProviderMetricCapabilityReason.CAPABILITY_NOT_OBSERVED,
            )
        return ProviderMetricCapability(
            capability=capability,
            state=ProviderMetricCapabilityState.UNKNOWN,
            reason_code=ProviderMetricCapabilityReason.CAPABILITY_UNVERIFIED,
        )

    @staticmethod
    def _requirements_satisfied(
        requirement: MetricEvidenceRequirement,
        available: set[MetricEvidenceCapability],
    ) -> bool:
        return all(
            any(item in available for item in group)
            for group in requirement.capability_groups
        )

    @staticmethod
    def _missing_capabilities(
        requirement: MetricEvidenceRequirement,
        capability_index: dict[
            MetricEvidenceCapability, ProviderMetricCapability
        ],
    ) -> tuple[MetricEvidenceCapability, ...]:
        missing: list[MetricEvidenceCapability] = []
        for group in requirement.capability_groups:
            if any(
                capability_index[item].state
                is ProviderMetricCapabilityState.SUPPORTED
                for item in group
            ):
                continue
            missing.extend(group)
        return tuple(sorted(set(missing), key=lambda item: item.value))

    def _metric_readiness(
        self,
        *,
        definition: TextMetricDefinition,
        requirement: MetricEvidenceRequirement,
        capability_report: ProviderCapabilityReport,
        capability_index: dict[
            MetricEvidenceCapability, ProviderMetricCapability
        ],
        latest: SessionAnalysisRunRecord | None,
        result: SessionAnalysisResultRecord | None,
    ) -> MetricReadiness:
        required_capabilities = {
            item for group in requirement.capability_groups for item in group
        }
        available_capabilities = tuple(
            sorted(
                (
                    item
                    for item in required_capabilities
                    if capability_index[item].state
                    is ProviderMetricCapabilityState.SUPPORTED
                ),
                key=lambda item: item.value,
            )
        )
        common = dict(
            metric_key=definition.key,
            metric_version=definition.version,
            dimension=definition.dimension,
            display_name=definition.display_name,
            unit=definition.unit,
            direction=definition.direction,
            radar_policy=(
                MetricRadarPolicy.DIRECT_BOUNDED_RATIO
                if definition.direction is MetricDirection.HIGHER_IS_BETTER
                else MetricRadarPolicy.EXACT_VALUE_ONLY_UNNORMALIZED_LOWER_IS_BETTER
            ),
            evidence_tier=definition.required_tier,
            capability_groups=requirement.capability_groups,
            available_capabilities=available_capabilities,
            latest_run_id=None if latest is None else latest.draft.run_id,
        )
        if capability_report.decoder_key is None:
            return MetricReadiness(
                **common,
                state=MetricReadinessState.UNSUPPORTED,
                reason_code=MetricReadinessReason.PROVIDER_ADAPTER_UNAVAILABLE,
                next_actions=(MetricReadinessAction.UPDATE_PROVIDER_ADAPTER,),
                missing_capabilities=tuple(
                    sorted(required_capabilities, key=lambda item: item.value)
                ),
            )
        if capability_report.compatibility_state is CompatibilityState.UNTESTED:
            return MetricReadiness(
                **common,
                state=MetricReadinessState.UNKNOWN,
                reason_code=(
                    MetricReadinessReason.PROVIDER_COMPATIBILITY_UNVERIFIED
                ),
                next_actions=(
                    MetricReadinessAction.CHECK_PROVIDER_COMPATIBILITY,
                ),
                missing_capabilities=(),
            )
        if capability_report.compatibility_state is CompatibilityState.UNAVAILABLE:
            return MetricReadiness(
                **common,
                state=MetricReadinessState.FAILED,
                reason_code=MetricReadinessReason.PROVIDER_UNAVAILABLE,
                next_actions=(
                    MetricReadinessAction.CHECK_PROVIDER_COMPATIBILITY,
                ),
                missing_capabilities=(),
            )
        if capability_report.compatibility_state not in {
            CompatibilityState.EXACT,
            CompatibilityState.COMPATIBLE,
        }:
            return MetricReadiness(
                **common,
                state=MetricReadinessState.INCOMPATIBLE,
                reason_code=MetricReadinessReason.PROVIDER_INCOMPATIBLE,
                next_actions=(
                    MetricReadinessAction.UPDATE_PROVIDER_ADAPTER,
                ),
                missing_capabilities=(),
            )
        if result is not None:
            return self._from_result(common, result)

        missing = self._missing_capabilities(requirement, capability_index)
        if missing:
            actions = tuple(
                dict.fromkeys(
                    _ACTION_FOR_CAPABILITY.get(
                        item,
                        MetricReadinessAction.UPDATE_PROVIDER_ADAPTER,
                    )
                    for item in missing
                )
            )
            return MetricReadiness(
                **common,
                state=MetricReadinessState.UNSUPPORTED,
                reason_code=MetricReadinessReason.PROVIDER_CAPABILITY_MISSING,
                next_actions=actions,
                missing_capabilities=missing,
            )
        if (
            latest is not None
            and latest.draft.metric_scope_state
            is SessionMetricScopeState.EXACT
            and definition.key not in latest.draft.selected_metric_keys
        ):
            return MetricReadiness(
                **common,
                state=MetricReadinessState.UNKNOWN,
                reason_code=MetricReadinessReason.METRIC_NOT_SELECTED,
                next_actions=(
                    MetricReadinessAction.SELECT_METRIC_FOR_ANALYSIS,
                ),
                missing_capabilities=(),
            )
        if (
            latest is not None
            and latest.draft.metric_scope_state
            is SessionMetricScopeState.LEGACY_UNKNOWN
        ):
            return MetricReadiness(
                **common,
                state=MetricReadinessState.UNKNOWN,
                reason_code=MetricReadinessReason.METRIC_SCOPE_UNKNOWN,
                next_actions=(
                    MetricReadinessAction.SELECT_METRIC_FOR_ANALYSIS,
                ),
                missing_capabilities=(),
            )
        if latest is not None and latest.status is AnalysisRunStatus.FAILED:
            return MetricReadiness(
                **common,
                state=MetricReadinessState.FAILED,
                reason_code=MetricReadinessReason.ANALYSIS_FAILED,
                next_actions=(MetricReadinessAction.RETRY_ANALYSIS,),
                missing_capabilities=(),
            )
        if latest is not None and latest.status is AnalysisRunStatus.RUNNING:
            return MetricReadiness(
                **common,
                state=MetricReadinessState.UNKNOWN,
                reason_code=MetricReadinessReason.ANALYSIS_IN_PROGRESS,
                next_actions=(MetricReadinessAction.NONE,),
                missing_capabilities=(),
            )
        if latest is not None:
            return MetricReadiness(
                **common,
                state=MetricReadinessState.FAILED,
                reason_code=MetricReadinessReason.RESULT_MISSING,
                next_actions=(MetricReadinessAction.RETRY_ANALYSIS,),
                missing_capabilities=(),
            )
        return MetricReadiness(
            **common,
            state=MetricReadinessState.UNKNOWN,
            reason_code=MetricReadinessReason.ANALYSIS_NOT_RUN,
            next_actions=(MetricReadinessAction.RUN_LOCAL_ANALYSIS,),
            missing_capabilities=(),
        )

    @staticmethod
    def _from_result(
        common: dict[str, object],
        result: SessionAnalysisResultRecord,
    ) -> MetricReadiness:
        state, reason, actions = {
            MetricValueState.KNOWN: (
                MetricReadinessState.KNOWN,
                MetricReadinessReason.MEASURED,
                (MetricReadinessAction.NONE,),
            ),
            MetricValueState.UNKNOWN: (
                MetricReadinessState.UNKNOWN,
                MetricReadinessReason.RESULT_UNKNOWN,
                (MetricReadinessAction.REVIEW_APPLICABILITY,),
            ),
            MetricValueState.NOT_APPLICABLE: (
                MetricReadinessState.NOT_APPLICABLE,
                MetricReadinessReason.EXPLICITLY_NOT_APPLICABLE,
                (MetricReadinessAction.NONE,),
            ),
            MetricValueState.ABSTAINED: (
                MetricReadinessState.ABSTAINED,
                MetricReadinessReason.RESULT_ABSTAINED,
                (MetricReadinessAction.REVIEW_EVIDENCE_COVERAGE,),
            ),
            MetricValueState.EXECUTION_ERROR: (
                MetricReadinessState.FAILED,
                MetricReadinessReason.RESULT_FAILED,
                (MetricReadinessAction.RETRY_ANALYSIS,),
            ),
        }[result.value_state]
        return MetricReadiness(
            **common,
            state=state,
            reason_code=reason,
            next_actions=actions,
            missing_capabilities=(),
        )


__all__ = [
    "COACHING_METRIC_REQUIREMENTS",
    "METRIC_READINESS_CATALOG_VERSION",
    "MetricEvidenceCapability",
    "MetricEvidenceRequirement",
    "MetricReadiness",
    "MetricReadinessAction",
    "MetricReadinessPresetUnsupportedError",
    "MetricReadinessReason",
    "MetricRadarPolicy",
    "MetricReadinessService",
    "MetricReadinessSessionNotFoundError",
    "MetricReadinessState",
    "ProviderCapabilityReport",
    "ProviderMetricCapability",
    "ProviderMetricCapabilityReason",
    "ProviderMetricCapabilityState",
    "SessionMetricReadinessReport",
]
