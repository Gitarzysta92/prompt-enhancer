"""Explicit, local application command for one selected-session text analysis.

The command is deliberately the only place where standing local-history consent
may be turned into a one-shot redacted-content capability.  Provider adapters
remain replaceable and receive neither a persistence port nor authority to read
another session.  Ephemeral text is consumed by the metric engine and is never
projected into the immutable result records.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Protocol

from ...domain import DataTier, PSEUDONYM_PATTERN, Provider, SAFE_VERSION_PATTERN
from ..persistence import (
    AnalysisRunStatus,
    SessionAnalysisCompletionAuthority,
    SessionAnalysisPublicationRejectedError,
    SessionAnalysisEvidenceRecord,
    SessionAnalysisSignalRecord,
    SessionAnalysisResultRecord,
    SessionAnalysisRunDraft,
    SessionAnalysisRunRecord,
    SessionAnalysisRunRepository,
    SessionEvidenceOrigin,
    SessionMetricAggregation,
    SessionMetricApplicability,
    SessionMetricDirection,
    SessionMetricScopeState,
    SessionMetricSignalStatus,
)
from .text_baselines import (
    DEFAULT_TEXT_METRIC_ENGINE,
    DEFAULT_TEXT_METRIC_PACK_KEY,
    DEFAULT_TEXT_METRIC_PACK_VERSION,
    TextMetricEngine,
)
from .coaching_baselines import DEFAULT_COACHING_METRIC_ENGINE
from .redaction_preview import (
    AnalysisApproval,
    AnalysisDestination,
    ApprovedRedactedAnalysis,
    CostEstimateState,
    InMemoryRedactionPreviewStore,
    RedactionPreviewBinding,
    RedactionPreviewInspection,
    RedactionPreviewMismatchError,
    RetentionClass,
)
from .text_contracts import (
    ApplicabilityBasis,
    MAX_ANALYSIS_CHARACTERS,
    MAX_ANALYSIS_MESSAGES,
    P1LocalAnalysisGrant,
    P1TextAnalysisInput,
    TextMetricResult,
    TextTaskProfile,
)
from .text_analysis_presets import (
    TextAnalysisPreset,
    TextAnalysisPresetId,
    resolve_text_analysis_preset,
)
from .text_source import (
    EphemeralTextAnalysisSource,
    TextAnalysisPurpose,
    TextAnalysisSelection,
    TextSourceFailureReason,
    TextSourceReadError,
    TextSourceAccessGrant,
)


SESSION_TEXT_ANALYSIS_CONFIRMATION = "analyze_selected_redacted_text"
SESSION_TEXT_ANALYSIS_CONSENT_POLICY_VERSION = "explicit-session-text-analysis-v1"
SESSION_TEXT_ANALYSIS_PLAN_VERSION = "deterministic-prompt-logic-plan-v2"
EXPLICIT_USER_ANALYSIS_PROFILE_KEY = "explicit.user-profile"
EXPLICIT_USER_ANALYSIS_PROFILE_VERSION = 1
LOCAL_ANALYSIS_MODEL_ID = "none"


class SessionTextAnalysisError(RuntimeError):
    """Sanitized base error; messages and codes never include provider data."""

    code = "session_text_analysis_error"


class SessionTextAnalysisInputError(SessionTextAnalysisError):
    code = "invalid_analysis_request"


class SessionTextAnalysisConfirmationError(SessionTextAnalysisError):
    code = "confirmation_required"


class SessionTextAnalysisConsentError(SessionTextAnalysisError):
    code = "redacted_content_consent_required"


class SessionTextAnalysisSelectionError(SessionTextAnalysisError):
    code = "session_not_in_safe_index"


class SessionTextAnalysisCompatibilityError(SessionTextAnalysisError):
    code = "provider_compatibility_blocked"


class SessionTextAnalysisConflictError(SessionTextAnalysisError):
    code = "analysis_idempotency_conflict"


class SessionTextAnalysisSourceError(SessionTextAnalysisError):
    """A bounded source failure; never constructed from provider text."""

    code = "local_text_source_unavailable"

    def __init__(self, reason: TextSourceFailureReason) -> None:
        if not isinstance(reason, TextSourceFailureReason):
            raise TypeError("analysis source reason must be a bounded enum value")
        self.reason = reason
        self.code = reason.value
        super().__init__(reason.value)


class SessionTextAnalysisPersistenceError(SessionTextAnalysisError):
    code = "analysis_persistence_failed"


class SessionTextAnalysisExecutionError(SessionTextAnalysisError):
    code = "metric_execution_failed"


class SessionTextAnalysisCooperativeStop(SessionTextAnalysisError):
    """A content-free stop already persisted by the automation queue."""

    code = "analysis_cooperative_stop"

    def __init__(self, reason_code: str) -> None:
        if SAFE_VERSION_PATTERN.fullmatch(reason_code) is None:
            raise ValueError("cooperative stop reason must be content-free")
        self.reason_code = reason_code
        super().__init__(reason_code)


class SessionTextAnalysisAccessPolicy(Protocol):
    """Read-only policy seam implemented by the local safe-index repository."""

    def has_active_consent(self, provider: Provider, tier: DataTier) -> bool: ...

    def selection_is_indexed(
        self,
        provider: Provider,
        *,
        project_ids: frozenset[str],
        session_ids: frozenset[str],
    ) -> bool: ...


class SessionTextAnalysisIdFactory(Protocol):
    """Keyed, installation-local identifiers over content-free values only."""

    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str: ...

    def session_analysis_run_id(
        self,
        idempotency_key: str,
        provider: Provider,
        session_id: str,
        metric_pack_key: str,
        metric_pack_version: int,
    ) -> str: ...


class SessionTextAnalysisSourceFactory(Protocol):
    """Create a provider source only after policy and idempotency gates pass."""

    def __call__(self, provider: Provider) -> EphemeralTextAnalysisSource: ...


class SessionTextAnalysisCompatibilityPolicy(Protocol):
    """Verify one provider surface without receiving any session content."""

    def require_compatible(self, provider: str) -> object: ...


@dataclass(frozen=True, slots=True)
class SessionTextAnalysisOutcome:
    run_id: str
    status: AnalysisRunStatus
    result_count: int
    applied: bool
    analysis_profile_key: str
    analysis_profile_version: int


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SessionTextAnalysisExecutionError("analysis clock is unavailable")
    return value.astimezone(UTC)


def _profile_fingerprint_values(profile: TextTaskProfile) -> tuple[str, ...]:
    """Canonicalize the reviewed profile without accepting free-form text."""

    values: list[str] = ["task-profile", "1"]
    decisions = sorted(
        profile.applicability,
        key=lambda item: (item.metric_key, item.applicability.value, item.basis.value),
    )
    values.extend(("applicability-count", str(len(decisions))))
    for item in decisions:
        values.extend(
            (
                "metric",
                item.metric_key,
                "applicability",
                item.applicability.value,
                "basis",
                item.basis.value,
            )
        )
    for label, items in (
        ("goal-slots", profile.expected_goal_slots),
        ("constraint-kinds", profile.expected_constraint_kinds),
        ("deliverable-slots", profile.expected_deliverable_slots),
    ):
        ordered = tuple(sorted(item.value for item in items))
        values.extend((label, str(len(ordered)), *ordered))
    values.extend(
        (
            "expected-outcomes",
            (
                "unknown"
                if profile.expected_outcome_count is None
                else str(profile.expected_outcome_count)
            ),
        )
    )
    return tuple(values)


def _plan_fingerprint_values(engine: TextMetricEngine) -> tuple[str, ...]:
    """Describe the local no-model plan independently of result ordering."""

    definitions = sorted(
        engine.registry.definitions,
        key=lambda definition: (definition.key, definition.version),
    )
    values: list[str] = [
        SESSION_TEXT_ANALYSIS_PLAN_VERSION,
        "metric-engine",
        engine.engine_version,
        "algorithm",
        engine.algorithm_id,
        engine.algorithm_version,
        "rubric",
        engine.rubric_version,
        *engine.model_plan_identity,
        "definition-count",
        str(len(definitions)),
    ]
    for definition in definitions:
        values.extend(
            (
                "definition",
                definition.key,
                str(definition.version),
                definition.unit,
                definition.direction.value,
                definition.aggregation_method.value,
                definition.required_tier.value,
            )
        )
    return tuple(values)


def _engine_pack_identity(engine: TextMetricEngine) -> tuple[str, int]:
    """Read the composed pack identity while retaining legacy test adapters."""

    key = getattr(engine, "pack_key", DEFAULT_TEXT_METRIC_PACK_KEY)
    version = getattr(engine, "pack_version", DEFAULT_TEXT_METRIC_PACK_VERSION)
    if (
        not isinstance(key, str)
        or SAFE_VERSION_PATTERN.fullmatch(key) is None
        or isinstance(version, bool)
        or not isinstance(version, int)
        or version < 1
    ):
        raise ValueError("text metric engine pack identity is invalid")
    return key, version


def _resolve_metric_selection(
    engine: TextMetricEngine,
    selected_metric_keys: tuple[str, ...] | None,
) -> tuple[str, ...]:
    available = tuple(
        definition.key for definition in engine.registry.definitions
    )
    if selected_metric_keys is None:
        return tuple(sorted(available))
    if (
        not isinstance(selected_metric_keys, tuple)
        or not selected_metric_keys
        or selected_metric_keys != tuple(sorted(selected_metric_keys))
        or len(set(selected_metric_keys)) != len(selected_metric_keys)
        or any(
            not isinstance(key, str)
            or SAFE_VERSION_PATTERN.fullmatch(key) is None
            for key in selected_metric_keys
        )
        or not set(selected_metric_keys).issubset(available)
    ):
        raise SessionTextAnalysisInputError(
            "selected metric scope is invalid for this analysis pack"
        )
    return selected_metric_keys


def _metric_scope_fingerprint_values(
    selected_metric_keys: tuple[str, ...] | None,
) -> tuple[str, ...]:
    if selected_metric_keys is None:
        # Preserve the existing full-profile identity for manual and approved
        # preview runs.  Automation always supplies an explicit immutable set.
        return ()
    return (
        "metric-scope",
        "explicit-selection-v1",
        "metric-count",
        str(len(selected_metric_keys)),
        *selected_metric_keys,
    )


def _pre_read_matches(
    stored: SessionAnalysisRunDraft,
    *,
    session_id: str,
    provider: Provider,
    analysis_profile_key: str,
    analysis_profile_version: int,
    request_fingerprint: str,
    model_plan_fingerprint: str,
    metric_engine_version: str,
    metric_pack_key: str,
    metric_pack_version: int,
    selected_metric_keys: tuple[str, ...],
    schema_version: int,
) -> bool:
    return (
        stored.session_id == session_id
        and stored.provider is provider
        and stored.analysis_profile_key == analysis_profile_key
        and stored.analysis_profile_version == analysis_profile_version
        and stored.request_fingerprint == request_fingerprint
        and stored.model_plan_fingerprint == model_plan_fingerprint
        and stored.metric_pack_key == metric_pack_key
        and stored.metric_pack_version == metric_pack_version
        and stored.metric_scope_state is SessionMetricScopeState.EXACT
        and stored.selected_metric_keys == selected_metric_keys
        and stored.data_tier is DataTier.REDACTED_CONTENT
        and stored.consent_purpose == TextAnalysisPurpose.TEXT_ANALYSIS.value
        and stored.consent_policy_version
        == SESSION_TEXT_ANALYSIS_CONSENT_POLICY_VERSION
        and stored.metric_engine_version == metric_engine_version
        and stored.schema_version == schema_version
        and stored.local_only
    )


def _draft_matches(
    stored: SessionAnalysisRunDraft, expected: SessionAnalysisRunDraft
) -> bool:
    return stored.model_dump(exclude={"started_at"}) == expected.model_dump(
        exclude={"started_at"}
    )


class SessionTextAnalysisService:
    """Append one immutable, versioned metric-pack snapshot after approval."""

    def __init__(
        self,
        access_policy: SessionTextAnalysisAccessPolicy,
        analyses: SessionAnalysisRunRepository,
        source_factory: SessionTextAnalysisSourceFactory,
        compatibility_policy: SessionTextAnalysisCompatibilityPolicy,
        identifiers: SessionTextAnalysisIdFactory,
        *,
        schema_version: int,
        metric_engine: TextMetricEngine = DEFAULT_TEXT_METRIC_ENGINE,
        additional_metric_engines: tuple[TextMetricEngine, ...] = (
            DEFAULT_COACHING_METRIC_ENGINE,
        ),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        preview_store: InMemoryRedactionPreviewStore | None = None,
    ) -> None:
        if isinstance(schema_version, bool) or schema_version < 1:
            raise ValueError("analysis schema version must be positive")
        if not callable(getattr(compatibility_policy, "require_compatible", None)):
            raise ValueError("analysis requires a provider compatibility policy")
        engines = (metric_engine, *additional_metric_engines)
        engine_by_pack: dict[tuple[str, int], TextMetricEngine] = {}
        for engine in engines:
            plan_values = _plan_fingerprint_values(engine)
            if (
                not engine.registry.definitions
                or len(engine.registry.definitions) > 100
                or any(
                    SAFE_VERSION_PATTERN.fullmatch(value) is None
                    for value in plan_values
                )
            ):
                raise ValueError("text metric engine plan identity is invalid")
            identity = _engine_pack_identity(engine)
            if identity in engine_by_pack:
                raise ValueError("text metric pack identities must be unique")
            engine_by_pack[identity] = engine
        self._access_policy = access_policy
        self._analyses = analyses
        self._source_factory = source_factory
        self._compatibility_policy = compatibility_policy
        self._identifiers = identifiers
        self._schema_version = schema_version
        self._metric_engine = metric_engine
        self._metric_engines = engine_by_pack
        self._clock = clock
        self._preview_store = preview_store or InMemoryRedactionPreviewStore(
            clock=clock
        )
        # One process-local command boundary avoids a duplicate provider read
        # when concurrent retries share an idempotency key. It is intentionally
        # bounded (one lock, no per-key map); cross-process serialization remains
        # the responsibility of a future reservation-capable repository.
        self._command_lock = Lock()

    def run(
        self,
        *,
        provider: Provider,
        session_id: str,
        task_profile: TextTaskProfile,
        confirmation: str,
        idempotency_key: str,
        max_messages: int = MAX_ANALYSIS_MESSAGES,
        max_characters: int = MAX_ANALYSIS_CHARACTERS,
    ) -> SessionTextAnalysisOutcome:
        """Run an internal/future explicitly reviewed custom profile."""

        metric_pack_key, metric_pack_version = _engine_pack_identity(
            self._metric_engine
        )
        return self._run_profile(
            provider=provider,
            session_id=session_id,
            task_profile=task_profile,
            required_basis=ApplicabilityBasis.USER_SELECTED,
            analysis_profile_key=EXPLICIT_USER_ANALYSIS_PROFILE_KEY,
            analysis_profile_version=EXPLICIT_USER_ANALYSIS_PROFILE_VERSION,
            confirmation=confirmation,
            idempotency_key=idempotency_key,
            max_messages=max_messages,
            max_characters=max_characters,
            metric_engine=self._metric_engine,
            metric_pack_key=metric_pack_key,
            metric_pack_version=metric_pack_version,
        )

    def run_preset(
        self,
        *,
        provider: Provider,
        session_id: str,
        preset_id: TextAnalysisPresetId,
        confirmation: str,
        idempotency_key: str,
        selected_metric_keys: tuple[str, ...] | None = None,
        completion_authority: SessionAnalysisCompletionAuthority | None = None,
        cooperative_check: Callable[[], None] | None = None,
        publication_committed_callback: Callable[[], None] | None = None,
    ) -> SessionTextAnalysisOutcome:
        """Resolve a versioned server-owned profile before any provider access.

        Manual callers omit ``selected_metric_keys`` and retain the immutable
        full-profile behavior.  The reviewed automation bridge supplies its
        immutable job scope so unselected calculators and observations are
        excluded from that run.
        """

        preset, metric_engine = self._resolve_preset_plan(preset_id)
        return self._run_profile(
            provider=provider,
            session_id=session_id,
            task_profile=preset.task_profile,
            required_basis=ApplicabilityBasis.TASK_PROFILE,
            analysis_profile_key=preset.analysis_profile_key,
            analysis_profile_version=preset.analysis_profile_version,
            confirmation=confirmation,
            idempotency_key=idempotency_key,
            max_messages=preset.max_messages,
            max_characters=preset.max_characters,
            metric_engine=metric_engine,
            metric_pack_key=preset.metric_pack_key,
            metric_pack_version=preset.metric_pack_version,
            selected_metric_keys=selected_metric_keys,
            completion_authority=completion_authority,
            cooperative_check=cooperative_check,
            publication_committed_callback=publication_committed_callback,
        )

    def prepare_preset_preview(
        self,
        *,
        provider: Provider,
        session_id: str,
        preset_id: TextAnalysisPresetId,
    ) -> RedactionPreviewInspection:
        """Read and retain one exact local redacted window for user inspection."""

        preset, metric_engine = self._resolve_preset_plan(preset_id)
        self._validate_preview_selection(provider, session_id)
        model_plan_fingerprint = self._identifiers.fingerprint(
            "session-analysis-plan-v1",
            _plan_fingerprint_values(metric_engine),
        )
        metric_keys = tuple(
            definition.key
            for definition in sorted(
                metric_engine.registry.definitions,
                key=lambda definition: (definition.key, definition.version),
            )
        )
        with self._command_lock:
            self._enforce_access_policy(provider, session_id)
            self._enforce_provider_compatibility(provider)
            context = self._read_context(
                provider=provider,
                session_id=session_id,
                task_profile=preset.task_profile,
                max_messages=preset.max_messages,
                max_characters=preset.max_characters,
            )
            binding = RedactionPreviewBinding(
                provider=provider,
                session_id=session_id,
                analysis_window_fingerprint=(
                    context.analysis_window_fingerprint
                ),
                metric_keys=metric_keys,
                destination=AnalysisDestination.LOCAL,
                exact_model=LOCAL_ANALYSIS_MODEL_ID,
                estimator_plan_version=model_plan_fingerprint,
                redactor_version=context.redactor_version,
                retention_class=RetentionClass.LOCAL_EPHEMERAL,
                message_count=context.observed_message_count,
                character_count=sum(
                    len(message.text.get_secret_value())
                    for message in context.messages
                ),
                cost_state=CostEstimateState.NOT_APPLICABLE,
            )
            receipt = self._preview_store.create(context, binding)
            return self._preview_store.inspect(receipt.preview_id)

    def approve_preview(
        self,
        approval: AnalysisApproval,
    ) -> SessionTextAnalysisOutcome:
        """Consume one exact preview and compute without another content read."""

        if not isinstance(approval, AnalysisApproval):
            raise SessionTextAnalysisInputError("preview approval is invalid")
        approved = self._preview_store.consume(approval)
        preset, metric_engine = self._resolve_approved_plan(approved)
        return self._run_profile(
            provider=approved.context.provider,
            session_id=approved.context.session_id,
            task_profile=preset.task_profile,
            required_basis=ApplicabilityBasis.TASK_PROFILE,
            analysis_profile_key=preset.analysis_profile_key,
            analysis_profile_version=preset.analysis_profile_version,
            confirmation=SESSION_TEXT_ANALYSIS_CONFIRMATION,
            idempotency_key=approved.idempotency_key,
            max_messages=preset.max_messages,
            max_characters=preset.max_characters,
            metric_engine=metric_engine,
            metric_pack_key=preset.metric_pack_key,
            metric_pack_version=preset.metric_pack_version,
            prepared_context=approved.context,
        )

    def _resolve_preset_plan(
        self,
        preset_id: TextAnalysisPresetId,
    ) -> tuple[TextAnalysisPreset, TextMetricEngine]:
        try:
            preset = resolve_text_analysis_preset(preset_id)
        except (KeyError, TypeError):
            raise SessionTextAnalysisInputError(
                "analysis preset identifier is invalid"
            ) from None
        metric_engine = self._metric_engines.get(
            (preset.metric_pack_key, preset.metric_pack_version)
        )
        if metric_engine is None:
            raise SessionTextAnalysisInputError(
                "analysis preset metric pack is unavailable"
            )
        return preset, metric_engine

    def _resolve_approved_plan(
        self,
        approved: ApprovedRedactedAnalysis,
    ) -> tuple[TextAnalysisPreset, TextMetricEngine]:
        binding = approved.receipt.binding
        if (
            binding.destination is not AnalysisDestination.LOCAL
            or binding.exact_model != LOCAL_ANALYSIS_MODEL_ID
            or binding.retention_class is not RetentionClass.LOCAL_EPHEMERAL
            or binding.cost_state is not CostEstimateState.NOT_APPLICABLE
        ):
            raise RedactionPreviewMismatchError()
        candidates = []
        for preset_id in TextAnalysisPresetId:
            preset, metric_engine = self._resolve_preset_plan(preset_id)
            metric_keys = tuple(
                definition.key
                for definition in sorted(
                    metric_engine.registry.definitions,
                    key=lambda definition: (
                        definition.key,
                        definition.version,
                    ),
                )
            )
            model_plan_fingerprint = self._identifiers.fingerprint(
                "session-analysis-plan-v1",
                _plan_fingerprint_values(metric_engine),
            )
            if (
                binding.metric_keys == metric_keys
                and binding.estimator_plan_version
                == model_plan_fingerprint
                and approved.context.task_profile == preset.task_profile
            ):
                candidates.append((preset, metric_engine))
        if len(candidates) != 1:
            raise RedactionPreviewMismatchError()
        return candidates[0]

    @staticmethod
    def _validate_preview_selection(
        provider: Provider,
        session_id: str,
    ) -> None:
        if not isinstance(provider, Provider):
            raise SessionTextAnalysisInputError("provider is invalid")
        if (
            not isinstance(session_id, str)
            or PSEUDONYM_PATTERN.fullmatch(session_id) is None
        ):
            raise SessionTextAnalysisInputError(
                "session identifier must be a safe pseudonym"
            )

    def _run_profile(
        self,
        *,
        provider: Provider,
        session_id: str,
        task_profile: TextTaskProfile,
        required_basis: ApplicabilityBasis,
        analysis_profile_key: str,
        analysis_profile_version: int,
        confirmation: str,
        idempotency_key: str,
        max_messages: int,
        max_characters: int,
        metric_engine: TextMetricEngine,
        metric_pack_key: str,
        metric_pack_version: int,
        selected_metric_keys: tuple[str, ...] | None = None,
        prepared_context: P1TextAnalysisInput | None = None,
        completion_authority: SessionAnalysisCompletionAuthority | None = None,
        cooperative_check: Callable[[], None] | None = None,
        publication_committed_callback: Callable[[], None] | None = None,
    ) -> SessionTextAnalysisOutcome:
        effective_metric_keys = _resolve_metric_selection(
            metric_engine,
            selected_metric_keys,
        )
        metric_scope_fingerprint_values = _metric_scope_fingerprint_values(
            selected_metric_keys
        )
        self._validate_request(
            provider=provider,
            session_id=session_id,
            task_profile=task_profile,
            required_basis=required_basis,
            analysis_profile_key=analysis_profile_key,
            analysis_profile_version=analysis_profile_version,
            confirmation=confirmation,
            idempotency_key=idempotency_key,
            max_messages=max_messages,
            max_characters=max_characters,
            metric_engine=metric_engine,
            metric_pack_key=metric_pack_key,
            metric_pack_version=metric_pack_version,
        )

        model_plan_fingerprint = self._identifiers.fingerprint(
            "session-analysis-plan-v1",
            (
                *_plan_fingerprint_values(metric_engine),
                *metric_scope_fingerprint_values,
            ),
        )
        request_fingerprint = self._identifiers.fingerprint(
            "session-analysis-request-v1",
            (
                "provider",
                provider.value,
                "session",
                session_id,
                "purpose",
                TextAnalysisPurpose.TEXT_ANALYSIS.value,
                "confirmation",
                SESSION_TEXT_ANALYSIS_CONFIRMATION,
                "consent-policy",
                SESSION_TEXT_ANALYSIS_CONSENT_POLICY_VERSION,
                "analysis-profile",
                analysis_profile_key,
                "analysis-profile-version",
                str(analysis_profile_version),
                "max-messages",
                str(max_messages),
                "max-characters",
                str(max_characters),
                "metric-pack",
                metric_pack_key,
                str(metric_pack_version),
                "model-plan",
                model_plan_fingerprint,
                *metric_scope_fingerprint_values,
                *_profile_fingerprint_values(task_profile),
            ),
        )
        run_id = self._identifiers.session_analysis_run_id(
            idempotency_key,
            provider,
            session_id,
            metric_pack_key,
            metric_pack_version,
        )

        with self._command_lock:
            return self._run_locked(
                provider=provider,
                session_id=session_id,
                task_profile=task_profile,
                analysis_profile_key=analysis_profile_key,
                analysis_profile_version=analysis_profile_version,
                max_messages=max_messages,
                max_characters=max_characters,
                request_fingerprint=request_fingerprint,
                model_plan_fingerprint=model_plan_fingerprint,
                metric_engine=metric_engine,
                metric_engine_version=metric_engine.engine_version,
                metric_pack_key=metric_pack_key,
                metric_pack_version=metric_pack_version,
                selected_metric_keys=effective_metric_keys,
                calculator_selected_metric_keys=(
                    effective_metric_keys
                    if selected_metric_keys is not None
                    else None
                ),
                run_id=run_id,
                prepared_context=prepared_context,
                completion_authority=completion_authority,
                cooperative_check=cooperative_check,
                publication_committed_callback=publication_committed_callback,
            )

    def _run_locked(
        self,
        *,
        provider: Provider,
        session_id: str,
        task_profile: TextTaskProfile,
        analysis_profile_key: str,
        analysis_profile_version: int,
        max_messages: int,
        max_characters: int,
        request_fingerprint: str,
        model_plan_fingerprint: str,
        metric_engine: TextMetricEngine,
        metric_engine_version: str,
        metric_pack_key: str,
        metric_pack_version: int,
        selected_metric_keys: tuple[str, ...],
        calculator_selected_metric_keys: tuple[str, ...] | None,
        run_id: str,
        prepared_context: P1TextAnalysisInput | None,
        completion_authority: SessionAnalysisCompletionAuthority | None,
        cooperative_check: Callable[[], None] | None,
        publication_committed_callback: Callable[[], None] | None,
    ) -> SessionTextAnalysisOutcome:

        existing = self._get_run(run_id)
        if existing is not None:
            if not _pre_read_matches(
                existing.draft,
                session_id=session_id,
                provider=provider,
                analysis_profile_key=analysis_profile_key,
                analysis_profile_version=analysis_profile_version,
                request_fingerprint=request_fingerprint,
                model_plan_fingerprint=model_plan_fingerprint,
                metric_engine_version=metric_engine_version,
                metric_pack_key=metric_pack_key,
                metric_pack_version=metric_pack_version,
                selected_metric_keys=selected_metric_keys,
                schema_version=self._schema_version,
            ):
                raise SessionTextAnalysisConflictError(
                    "analysis identifier conflicts with stored provenance"
                )
            if (
                existing.status is AnalysisRunStatus.COMPLETED
                and publication_committed_callback is not None
            ):
                publication_committed_callback()
            return self._existing_outcome(existing)

        if cooperative_check is not None:
            cooperative_check()
        # Authority is observed inside the serialized command boundary so a
        # queued request cannot mint a grant from stale consent/index state.
        self._enforce_access_policy(provider, session_id)
        self._enforce_provider_compatibility(provider)
        context = prepared_context
        if context is None:
            if cooperative_check is not None:
                cooperative_check()
            try:
                context = self._read_context(
                    provider=provider,
                    session_id=session_id,
                    task_profile=task_profile,
                    max_messages=max_messages,
                    max_characters=max_characters,
                )
            finally:
                if cooperative_check is not None:
                    cooperative_check()
        input_fingerprint = self._identifiers.fingerprint(
            "session-analysis-input-v1",
            (request_fingerprint, context.analysis_window_fingerprint),
        )
        draft = SessionAnalysisRunDraft(
            run_id=run_id,
            session_id=session_id,
            request_fingerprint=request_fingerprint,
            input_fingerprint=input_fingerprint,
            analysis_profile_key=analysis_profile_key,
            analysis_profile_version=analysis_profile_version,
            metric_pack_key=metric_pack_key,
            metric_pack_version=metric_pack_version,
            metric_scope_state=SessionMetricScopeState.EXACT,
            selected_metric_keys=selected_metric_keys,
            data_tier=DataTier.REDACTED_CONTENT,
            consent_purpose=TextAnalysisPurpose.TEXT_ANALYSIS.value,
            consent_policy_version=SESSION_TEXT_ANALYSIS_CONSENT_POLICY_VERSION,
            provider=provider,
            provider_version=context.provider_version,
            adapter_version=context.adapter_version,
            source_schema_version=context.source_schema_version,
            content_schema_version=context.content_schema_version,
            metric_engine_version=metric_engine_version,
            redactor_version=context.redactor_version,
            model_plan_fingerprint=model_plan_fingerprint,
            schema_version=self._schema_version,
            local_only=True,
            started_at=_require_utc(self._clock()),
        )
        try:
            if cooperative_check is not None:
                cooperative_check()
            if completion_authority is None:
                self._analyses.begin(draft)
            else:
                self._analyses.begin(
                    draft,
                    completion_authority=completion_authority,
                )
            if cooperative_check is not None:
                cooperative_check()
        except SessionAnalysisPublicationRejectedError as error:
            raise SessionTextAnalysisCooperativeStop(error.reason_code) from None
        except SessionTextAnalysisCooperativeStop:
            raise
        except Exception:
            if cooperative_check is not None:
                cooperative_check()
            race_winner = self._get_run(run_id)
            if race_winner is not None and _draft_matches(race_winner.draft, draft):
                if (
                    race_winner.status is AnalysisRunStatus.COMPLETED
                    and publication_committed_callback is not None
                ):
                    publication_committed_callback()
                return self._existing_outcome(race_winner)
            if race_winner is None:
                raise SessionTextAnalysisPersistenceError(
                    "analysis run could not be stored"
                ) from None
            raise SessionTextAnalysisConflictError(
                "analysis identifier conflicts with stored provenance"
            ) from None

        grant = P1LocalAnalysisGrant(
            provider=provider,
            session_id=session_id,
            analysis_window_fingerprint=context.analysis_window_fingerprint,
            data_tier=DataTier.REDACTED_CONTENT,
            consent_active=True,
            local_only=True,
            content_persistence_allowed=False,
        )
        try:
            if cooperative_check is not None:
                cooperative_check()
            try:
                if cooperative_check is None:
                    calculated = metric_engine.compute(
                        context,
                        grant,
                        pack_key=metric_pack_key,
                        pack_version=metric_pack_version,
                        selected_metric_keys=calculator_selected_metric_keys,
                    )
                else:
                    calculated = metric_engine.compute(
                        context,
                        grant,
                        pack_key=metric_pack_key,
                        pack_version=metric_pack_version,
                        selected_metric_keys=calculator_selected_metric_keys,
                        cooperative_check=cooperative_check,
                    )
            finally:
                if cooperative_check is not None:
                    cooperative_check()
            try:
                self._validate_result_set(
                    context,
                    calculated,
                    metric_engine,
                    selected_metric_keys=calculator_selected_metric_keys,
                )
            finally:
                if cooperative_check is not None:
                    cooperative_check()
        except SessionTextAnalysisCooperativeStop:
            raise
        except Exception:
            self._mark_failed(run_id, SessionTextAnalysisExecutionError.code)
            raise SessionTextAnalysisExecutionError(
                "local metric analysis failed"
            ) from None

        try:
            if cooperative_check is not None:
                cooperative_check()
            # The publication timestamp is read after the last cooperative
            # checkpoint: a checkpoint advances the job's publication
            # high-water mark to its own wall-clock reading, so a timestamp
            # taken before it would be rejected as a clock regression.
            try:
                finished_at = _require_utc(self._clock())
                if finished_at < draft.started_at:
                    raise ValueError("analysis clock moved backwards")
                records = tuple(
                    self._to_record(result, computed_at=finished_at)
                    for result in calculated
                )
            except Exception:
                self._mark_failed(run_id, SessionTextAnalysisExecutionError.code)
                raise SessionTextAnalysisExecutionError(
                    "local metric analysis failed"
                ) from None
            self._analyses.complete(
                run_id,
                records,
                finished_at=finished_at,
                completion_authority=completion_authority,
            )
        except SessionAnalysisPublicationRejectedError as error:
            raise SessionTextAnalysisCooperativeStop(error.reason_code) from None
        except (SessionTextAnalysisCooperativeStop, SessionTextAnalysisExecutionError):
            raise
        except Exception:
            if cooperative_check is not None:
                cooperative_check()
            self._mark_failed(run_id, SessionTextAnalysisPersistenceError.code)
            raise SessionTextAnalysisPersistenceError(
                "analysis results could not be stored"
            ) from None
        if publication_committed_callback is not None:
            publication_committed_callback()
        return SessionTextAnalysisOutcome(
            run_id=run_id,
            status=AnalysisRunStatus.COMPLETED,
            result_count=len(records),
            applied=True,
            analysis_profile_key=analysis_profile_key,
            analysis_profile_version=analysis_profile_version,
        )

    def _validate_request(
        self,
        *,
        provider: Provider,
        session_id: str,
        task_profile: TextTaskProfile,
        required_basis: ApplicabilityBasis,
        analysis_profile_key: str,
        analysis_profile_version: int,
        confirmation: str,
        idempotency_key: str,
        max_messages: int,
        max_characters: int,
        metric_engine: TextMetricEngine,
        metric_pack_key: str,
        metric_pack_version: int,
    ) -> None:
        if not isinstance(provider, Provider):
            raise SessionTextAnalysisInputError("provider is invalid")
        if not isinstance(session_id, str) or PSEUDONYM_PATTERN.fullmatch(session_id) is None:
            raise SessionTextAnalysisInputError(
                "session identifier must be a safe pseudonym"
            )
        if not isinstance(task_profile, TextTaskProfile):
            raise SessionTextAnalysisInputError("task profile is invalid")
        if (
            not isinstance(required_basis, ApplicabilityBasis)
            or not isinstance(analysis_profile_key, str)
            or SAFE_VERSION_PATTERN.fullmatch(analysis_profile_key) is None
            or isinstance(analysis_profile_version, bool)
            or not isinstance(analysis_profile_version, int)
            or analysis_profile_version < 1
        ):
            raise SessionTextAnalysisInputError("analysis profile identity is invalid")
        if _engine_pack_identity(metric_engine) != (
            metric_pack_key,
            metric_pack_version,
        ):
            raise SessionTextAnalysisInputError("analysis metric pack is invalid")
        expected_metric_keys = {
            definition.key for definition in metric_engine.registry.definitions
        }
        decisions = task_profile.applicability
        if (
            {decision.metric_key for decision in decisions} != expected_metric_keys
            or len(decisions) != len(expected_metric_keys)
            or any(
                decision.basis is not required_basis
                for decision in decisions
            )
        ):
            raise SessionTextAnalysisInputError(
                "task profile must contain one authorized decision for every metric"
            )
        if confirmation != SESSION_TEXT_ANALYSIS_CONFIRMATION:
            raise SessionTextAnalysisConfirmationError(
                "explicit per-run confirmation is required"
            )
        if (
            not isinstance(idempotency_key, str)
            or SAFE_VERSION_PATTERN.fullmatch(idempotency_key) is None
        ):
            raise SessionTextAnalysisInputError(
                "idempotency key must be a short content-free identifier"
            )
        if (
            isinstance(max_messages, bool)
            or not isinstance(max_messages, int)
            or not 1 <= max_messages <= MAX_ANALYSIS_MESSAGES
            or isinstance(max_characters, bool)
            or not isinstance(max_characters, int)
            or not 1 <= max_characters <= MAX_ANALYSIS_CHARACTERS
        ):
            raise SessionTextAnalysisInputError("analysis bounds are invalid")

    def _enforce_access_policy(self, provider: Provider, session_id: str) -> None:
        try:
            consent_active = self._access_policy.has_active_consent(
                provider, DataTier.REDACTED_CONTENT
            )
        except Exception:
            raise SessionTextAnalysisConsentError(
                "redacted-content consent status is unavailable"
            ) from None
        if not consent_active:
            raise SessionTextAnalysisConsentError(
                "redacted-content consent is required"
            )
        try:
            indexed = self._access_policy.selection_is_indexed(
                provider,
                project_ids=frozenset(),
                session_ids=frozenset((session_id,)),
            )
        except Exception:
            raise SessionTextAnalysisSelectionError(
                "safe session selection is unavailable"
            ) from None
        if not indexed:
            raise SessionTextAnalysisSelectionError(
                "selected session is not present in the safe index"
            )

    def _enforce_provider_compatibility(self, provider: Provider) -> None:
        try:
            self._compatibility_policy.require_compatible(provider.value)
        except Exception:
            raise SessionTextAnalysisCompatibilityError(
                "provider compatibility is not verified"
            ) from None

    def _get_run(self, run_id: str) -> SessionAnalysisRunRecord | None:
        try:
            return self._analyses.get(run_id)
        except Exception:
            raise SessionTextAnalysisPersistenceError(
                "analysis persistence is unavailable"
            ) from None

    def _existing_outcome(
        self, existing: SessionAnalysisRunRecord
    ) -> SessionTextAnalysisOutcome:
        try:
            result_count = len(self._analyses.get_results(existing.draft.run_id))
        except Exception:
            raise SessionTextAnalysisPersistenceError(
                "analysis results are unavailable"
            ) from None
        return SessionTextAnalysisOutcome(
            run_id=existing.draft.run_id,
            status=existing.status,
            result_count=result_count,
            applied=False,
            analysis_profile_key=existing.draft.analysis_profile_key,
            analysis_profile_version=existing.draft.analysis_profile_version,
        )

    def _read_context(
        self,
        *,
        provider: Provider,
        session_id: str,
        task_profile: TextTaskProfile,
        max_messages: int,
        max_characters: int,
    ) -> P1TextAnalysisInput:
        selection = TextAnalysisSelection(
            provider=provider,
            session_id=session_id,
            max_messages=max_messages,
            max_characters=max_characters,
        )
        source_grant = TextSourceAccessGrant(
            purpose=TextAnalysisPurpose.TEXT_ANALYSIS,
            provider=provider,
            session_id=session_id,
            data_tier=DataTier.REDACTED_CONTENT,
            per_run_confirmation_active=True,
            local_only=True,
            content_persistence_allowed=False,
        )
        try:
            source = self._source_factory(provider)
            if (
                source.provider is not provider
                or source.purpose is not TextAnalysisPurpose.TEXT_ANALYSIS
                or not source.read_only
                or not source.requires_explicit_selection
            ):
                raise ValueError("source capability mismatch")
            context = source.read(
                selection=selection,
                grant=source_grant,
                task_profile=task_profile,
            )
            if (
                context.provider is not provider
                or context.session_id != session_id
                or context.task_profile != task_profile
                or context.observed_message_count > max_messages
                or sum(
                    len(message.text.get_secret_value())
                    for message in context.messages
                )
                > max_characters
            ):
                raise ValueError("source result exceeds its capability")
            return context
        except TextSourceReadError as error:
            raise SessionTextAnalysisSourceError(error.reason) from None
        except Exception:
            raise SessionTextAnalysisSourceError(
                TextSourceFailureReason.PROVIDER_UNAVAILABLE
            ) from None

    def _validate_result_set(
        self,
        context: P1TextAnalysisInput,
        results: tuple[TextMetricResult, ...],
        metric_engine: TextMetricEngine,
        *,
        selected_metric_keys: tuple[str, ...] | None,
    ) -> None:
        selected = set(
            _resolve_metric_selection(metric_engine, selected_metric_keys)
        )
        expected = tuple(
            sorted(
                (definition.key, definition.version)
                for definition in metric_engine.registry.definitions
                if definition.key in selected
            )
        )
        actual = tuple(
            sorted(
                (result.observation.key, result.observation.version)
                for result in results
            )
        )
        if actual != expected or len(results) != len(expected):
            raise ValueError("metric pack result set is incomplete")
        for result in results:
            provenance = result.provenance
            if (
                provenance.provider is not context.provider
                or provenance.provider_version != context.provider_version
                or provenance.adapter_version != context.adapter_version
                or provenance.source_schema_version != context.source_schema_version
                or provenance.content_schema_version != context.content_schema_version
                or provenance.redactor_version != context.redactor_version
                or provenance.analysis_window_fingerprint
                != context.analysis_window_fingerprint
                or provenance.algorithm_id != metric_engine.algorithm_id
                or provenance.algorithm_version
                != metric_engine.algorithm_version
                or provenance.rubric_version != metric_engine.rubric_version
                or (
                    metric_engine.model_plan_identity[:2] == ("model", "none")
                    and provenance.model_id is not None
                )
                or not provenance.local_only
            ):
                raise ValueError("metric result provenance does not match its input")

    @staticmethod
    def _to_record(
        result: TextMetricResult, *, computed_at: datetime
    ) -> SessionAnalysisResultRecord:
        fraction = result.fraction
        provenance = result.provenance
        return SessionAnalysisResultRecord(
            observation=result.observation,
            value_state=result.value_state,
            direction=SessionMetricDirection(result.direction.value),
            applicability=SessionMetricApplicability(result.applicability.value),
            aggregation_method=SessionMetricAggregation(
                result.aggregation_method.value
            ),
            metric_schema_version=provenance.metric_schema_version,
            evidence_data_tier=result.evidence_data_tier,
            fraction_numerator=(None if fraction is None else fraction.numerator),
            fraction_denominator=(None if fraction is None else fraction.denominator),
            evidence=tuple(
                SessionAnalysisEvidenceRecord(
                    message_id=item.message_id,
                    origin=SessionEvidenceOrigin(item.origin.value),
                )
                for item in result.evidence
            ),
            signals=tuple(
                SessionAnalysisSignalRecord(
                    code=item.code,
                    status=SessionMetricSignalStatus(item.status.value),
                    count=item.count,
                )
                for item in result.signals
            ),
            explanation_code=result.explanation_code,
            error_code=result.error_code,
            algorithm_id=provenance.algorithm_id,
            algorithm_version=provenance.algorithm_version,
            model_id=provenance.model_id,
            model_revision=provenance.model_revision,
            model_license=provenance.model_license,
            tokenizer_id=provenance.tokenizer_id,
            prompt_version=provenance.prompt_version,
            rubric_version=provenance.rubric_version,
            computed_at=computed_at,
        )

    def _mark_failed(self, run_id: str, failure_code: str) -> None:
        try:
            self._analyses.fail(
                run_id,
                finished_at=_require_utc(self._clock()),
                failure_code=failure_code,
            )
        except Exception:
            # The original safe error remains authoritative. A racing terminal
            # transition is never retried with a fresh provider read.
            return
