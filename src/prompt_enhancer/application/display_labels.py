"""Privacy-bounded use cases for provider labels and local manual overrides."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import Field, SecretStr, field_validator, model_validator

from ..adapters.base import AdapterHealth, AdapterProbe
from ..display_labels import (
    PROJECT_DISPLAY_NAME_MAX_LENGTH,
    SESSION_DISPLAY_NAME_MAX_LENGTH,
    minimize_private_display_name,
    require_private_display_name,
)
from ..domain import (
    PSEUDONYM_PATTERN,
    SAFE_VERSION_PATTERN,
    DataTier,
    Provider,
    SourceSession,
    SourceSessionPage,
    StrictModel,
)
from ..ingestion import ConsentRequiredError
from .ingestion import SourceIdentifierProtector


MAX_LABEL_ENRICHMENT_SELECTORS = 25
MAX_LABEL_ENRICHMENT_SESSIONS = 25
MAX_LABEL_SCAN_PAGES = 50
MAX_LABEL_SCAN_SESSIONS = 2_000


class LabelEntityKind(StrEnum):
    PROJECT = "project"
    SESSION = "session"


class ProviderLabelSource(StrEnum):
    PATH_BASENAME = "provider_path_basename"
    EXPLICIT_TITLE = "provider_explicit_title"
    #: A title the app derived from the session's first prompt (Claude Code transcripts).
    FIRST_PROMPT = "provider_first_prompt"


class LabelObservationMethod(StrEnum):
    THREAD_LIST_STATE_DB = "thread_list_state_db"
    THREAD_READ_SUMMARY = "thread_read_summary"
    LEGACY_V4_IMPORT = "legacy_v4_import"
    #: Read from the head of a Claude Code transcript file (cwd, first prompt).
    TRANSCRIPT_HEAD = "transcript_head"
    #: Carried by Claude Code hook event fields (cwd, explicit title).
    HOOK_EVENT = "hook_event"


#: Provenance each indexing provider stamps on the labels it observes. Providers
#: absent here keep the plain display-name columns (the synthetic demo adapter).
INDEXED_LABEL_PROVENANCE: dict[Provider, dict[str, str]] = {
    Provider.CODEX: {
        "extractor_version": "codex-display-labels-v1",
        "observation_method": LabelObservationMethod.THREAD_LIST_STATE_DB.value,
        "project_source": ProviderLabelSource.PATH_BASENAME.value,
        "session_source": ProviderLabelSource.EXPLICIT_TITLE.value,
    },
    Provider.CLAUDE_CODE: {
        "extractor_version": "claude-code-display-labels-v1",
        "observation_method": LabelObservationMethod.TRANSCRIPT_HEAD.value,
        "project_source": ProviderLabelSource.PATH_BASENAME.value,
        "session_source": ProviderLabelSource.FIRST_PROMPT.value,
    },
}
#: Claude Code's hook adapter carries labels in hook event fields rather than a transcript head.
HOOK_ADAPTER_VERSION_PREFIX = "claude-code-hooks-adapter-"


class ProviderDisplayLabelPolicy(StrictModel):
    """Provider-specific provenance selected only by the composition root."""

    provider: Provider
    consent_tier: DataTier
    observation_method: LabelObservationMethod
    extractor_version: str = Field(pattern=SAFE_VERSION_PATTERN.pattern)
    project_label_source: ProviderLabelSource
    session_label_source: ProviderLabelSource


class LabelTarget(StrictModel):
    session_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    project_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    project_label_missing: bool
    session_label_missing: bool


class LabelTargetBatch(StrictModel):
    targets: tuple[LabelTarget, ...]
    truncated: bool = False


class ProviderDisplayLabelObservation(StrictModel):
    """One minimized label with field-specific source and method provenance."""

    provider: Provider
    session_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    project_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    entity_kind: LabelEntityKind
    value: str = Field(min_length=1, max_length=SESSION_DISPLAY_NAME_MAX_LENGTH, repr=False)
    source: ProviderLabelSource
    observation_method: LabelObservationMethod
    extractor_version: str = Field(pattern=SAFE_VERSION_PATTERN.pattern)
    provider_version: str = Field(pattern=SAFE_VERSION_PATTERN.pattern)
    adapter_version: str = Field(pattern=SAFE_VERSION_PATTERN.pattern)
    source_schema_version: str = Field(pattern=SAFE_VERSION_PATTERN.pattern)
    observed_at: datetime

    @model_validator(mode="after")
    def validate_label(self) -> ProviderDisplayLabelObservation:
        max_length = (
            PROJECT_DISPLAY_NAME_MAX_LENGTH
            if self.entity_kind is LabelEntityKind.PROJECT
            else SESSION_DISPLAY_NAME_MAX_LENGTH
        )
        require_private_display_name(self.value, max_length=max_length)
        return self

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("label observation time must include a timezone")
        return value.astimezone(UTC)


class LabelWriteResult(StrictModel):
    project_labels_filled: int = 0
    session_labels_filled: int = 0


class LabelEnrichmentReport(StrictModel):
    provider: Provider
    requested_sessions: int = 0
    matched_sessions: int = 0
    summary_reads: int = 0
    project_labels_filled: int = 0
    session_labels_filled: int = 0
    labels_unavailable: int = 0
    sessions_not_found: int = 0
    truncated: bool = False


class ManualDisplayLabelResult(StrictModel):
    entity_kind: LabelEntityKind
    entity_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    revision: int = Field(ge=0)
    changed: bool


class ProviderDisplayLabelRepository(Protocol):
    def initialize(self) -> None: ...

    def has_active_consent(self, provider: Provider, tier: DataTier) -> bool: ...

    def selection_is_indexed(
        self,
        provider: Provider,
        *,
        project_ids: frozenset[str],
        session_ids: frozenset[str],
    ) -> bool: ...

    def resolve_provider_label_targets(
        self,
        provider: Provider,
        *,
        project_ids: frozenset[str],
        session_ids: frozenset[str],
        limit: int,
    ) -> LabelTargetBatch: ...

    def apply_provider_display_labels(
        self,
        observations: tuple[ProviderDisplayLabelObservation, ...],
    ) -> LabelWriteResult: ...


class ManualDisplayLabelRepository(Protocol):
    def initialize(self) -> None: ...

    def set_manual_display_label(
        self,
        *,
        entity_kind: LabelEntityKind,
        entity_id: str,
        value: str,
        expected_revision: int,
    ) -> ManualDisplayLabelResult: ...

    def clear_manual_display_label(
        self,
        *,
        entity_kind: LabelEntityKind,
        entity_id: str,
        expected_revision: int,
    ) -> ManualDisplayLabelResult: ...


class ProviderDisplayLabelSource(Protocol):
    """Least-capability port for summary labels; it cannot return events."""

    @property
    def provider(self) -> Provider: ...

    @property
    def required_consent_tier(self) -> DataTier: ...

    @property
    def requires_explicit_selection(self) -> bool: ...

    def probe(self) -> AdapterProbe: ...

    def list_sessions(
        self, *, cursor: str | None = None, limit: int = 100
    ) -> SourceSessionPage: ...

    def read_display_labels(self, session: SourceSession) -> SourceSession: ...

    def close(self) -> None: ...


class DisplayLabelError(RuntimeError):
    """A sanitized display-label operation failure."""


class DisplayLabelSelectionError(DisplayLabelError):
    """The requested safe selectors are missing, excessive, or not indexed."""


class DisplayLabelConflictError(DisplayLabelError):
    """A local manual-label revision changed before this command."""


class DisplayLabelNotFoundError(DisplayLabelError):
    """The selected local catalog entity no longer exists."""


class InvalidDisplayLabelError(DisplayLabelError):
    """A user-supplied label did not pass local minimization."""


LabelSourceFactory = Callable[[], ProviderDisplayLabelSource]


class ProviderDisplayLabelEnrichmentService:
    """Find missing labels through explicit, bounded, summary-only provider reads."""

    def __init__(
        self,
        repository: ProviderDisplayLabelRepository,
        pseudonymizer: SourceIdentifierProtector,
        source_factory: LabelSourceFactory,
        policy: ProviderDisplayLabelPolicy,
    ) -> None:
        self._repository = repository
        self._pseudonymizer = pseudonymizer
        self._source_factory = source_factory
        self._policy = policy

    def enrich(
        self,
        *,
        project_ids: frozenset[str],
        session_ids: frozenset[str],
        max_sessions: int,
    ) -> LabelEnrichmentReport:
        self._repository.initialize()
        if not self._repository.has_active_consent(
            self._policy.provider, self._policy.consent_tier
        ):
            raise ConsentRequiredError(
                "explicit source consent is required before provider access"
            )
        if not project_ids and not session_ids:
            raise DisplayLabelSelectionError(
                "label enrichment requires an explicit safe selection"
            )
        if (
            len(project_ids) + len(session_ids)
            > MAX_LABEL_ENRICHMENT_SELECTORS
            or max_sessions < 1
            or max_sessions > MAX_LABEL_ENRICHMENT_SESSIONS
        ):
            raise DisplayLabelSelectionError("label enrichment exceeds the safe bound")
        if not self._repository.selection_is_indexed(
            self._policy.provider,
            project_ids=project_ids,
            session_ids=session_ids,
        ):
            raise DisplayLabelSelectionError(
                "label enrichment selection is not present in the safe index"
            )

        batch = self._repository.resolve_provider_label_targets(
            self._policy.provider,
            project_ids=project_ids,
            session_ids=session_ids,
            limit=max_sessions,
        )
        if not batch.targets:
            return LabelEnrichmentReport(
                provider=self._policy.provider,
                truncated=batch.truncated,
            )

        targets = {target.session_id: target for target in batch.targets}
        matched: set[str] = set()
        observations: list[ProviderDisplayLabelObservation] = []
        observed_projects: set[str] = set()
        summary_reads = 0
        labels_unavailable = 0
        source: ProviderDisplayLabelSource | None = None
        try:
            source = self._source_factory()
            if (
                source.provider is not self._policy.provider
                or source.required_consent_tier is not self._policy.consent_tier
                or not source.requires_explicit_selection
            ):
                raise DisplayLabelError("provider label source is unavailable")

            probe = source.probe()
            if (
                probe.provider is not self._policy.provider
                or probe.health is not AdapterHealth.READY
                or not probe.supports_metadata
                or probe.supports_content
            ):
                raise DisplayLabelError("provider label source is unavailable")

            cursor: str | None = None
            seen_cursors: set[str] = set()
            pages_scanned = 0
            sessions_scanned = 0
            while True:
                if pages_scanned >= MAX_LABEL_SCAN_PAGES:
                    raise DisplayLabelError("provider label scan exceeded its page bound")
                page = source.list_sessions(cursor=cursor, limit=100)
                pages_scanned += 1
                if (
                    len(page.sessions) > 100
                    or sessions_scanned + len(page.sessions)
                    > MAX_LABEL_SCAN_SESSIONS
                ):
                    raise DisplayLabelError(
                        "provider label scan exceeded its session bound"
                    )
                sessions_scanned += len(page.sessions)
                for listed in page.sessions:
                    self._require_provenance(listed, probe)
                    safe_project_id, safe_session_id = self._safe_identity(listed)
                    target = targets.get(safe_session_id)
                    if target is None or safe_session_id in matched:
                        continue
                    if safe_project_id != target.project_id:
                        raise DisplayLabelError(
                            "provider label project identity changed"
                        )
                    matched.add(safe_session_id)
                    need_project = (
                        target.project_label_missing
                        and target.project_id not in observed_projects
                    )
                    need_session = target.session_label_missing
                    if not need_project and not need_session:
                        continue

                    enriched = source.read_display_labels(listed)
                    self._require_same_identity(listed, enriched)
                    self._require_provenance(enriched, probe)
                    summary_reads += 1
                    project_label = (
                        self._private_label(
                            enriched.source_project_display_name,
                            max_length=PROJECT_DISPLAY_NAME_MAX_LENGTH,
                        )
                        if need_project
                        else None
                    )
                    session_label = (
                        self._private_label(
                            enriched.source_session_display_name,
                            max_length=SESSION_DISPLAY_NAME_MAX_LENGTH,
                        )
                        if need_session
                        else None
                    )
                    observed_at = datetime.now(UTC)
                    common = {
                        "provider": self._policy.provider,
                        "session_id": target.session_id,
                        "project_id": target.project_id,
                        "observation_method": self._policy.observation_method,
                        "extractor_version": self._policy.extractor_version,
                        "provider_version": probe.provider_version,
                        "adapter_version": probe.adapter_version,
                        "source_schema_version": probe.source_schema_version,
                        "observed_at": observed_at,
                    }
                    if project_label is not None:
                        observed_projects.add(target.project_id)
                        observations.append(
                            ProviderDisplayLabelObservation(
                                **common,
                                entity_kind=LabelEntityKind.PROJECT,
                                value=project_label,
                                source=self._policy.project_label_source,
                            )
                        )
                    if session_label is not None:
                        observations.append(
                            ProviderDisplayLabelObservation(
                                **common,
                                entity_kind=LabelEntityKind.SESSION,
                                value=session_label,
                                source=self._policy.session_label_source,
                            )
                        )
                    if project_label is None and session_label is None:
                        labels_unavailable += 1

                if len(matched) == len(targets):
                    break
                next_cursor = page.next_cursor
                if next_cursor is None:
                    break
                if next_cursor == cursor or next_cursor in seen_cursors:
                    raise DisplayLabelError("provider label pagination repeated")
                seen_cursors.add(next_cursor)
                cursor = next_cursor

            written = self._repository.apply_provider_display_labels(
                tuple(observations)
            )
            return LabelEnrichmentReport(
                provider=self._policy.provider,
                requested_sessions=len(targets),
                matched_sessions=len(matched),
                summary_reads=summary_reads,
                project_labels_filled=written.project_labels_filled,
                session_labels_filled=written.session_labels_filled,
                labels_unavailable=labels_unavailable,
                sessions_not_found=len(targets) - len(matched),
                truncated=batch.truncated,
            )
        except (ConsentRequiredError, DisplayLabelError):
            raise
        except Exception:
            raise DisplayLabelError("provider label enrichment failed") from None
        finally:
            if source is not None:
                try:
                    source.close()
                except Exception:
                    pass

    def _safe_identity(self, source: SourceSession) -> tuple[str, str]:
        if source.provider is not self._policy.provider:
            raise DisplayLabelError("provider label provenance changed")
        namespace = source.provider.value
        installation_id = self._pseudonymizer.pseudonymize(
            f"{namespace}:installation",
            source.source_installation_id.get_secret_value(),
        )
        project_id = self._pseudonymizer.pseudonymize(
            f"{namespace}:project:{installation_id}",
            source.source_project_id.get_secret_value(),
        )
        session_id = self._pseudonymizer.pseudonymize(
            f"{namespace}:session:{installation_id}",
            source.source_session_id.get_secret_value(),
        )
        return project_id, session_id

    @staticmethod
    def _require_provenance(source: SourceSession, probe: AdapterProbe) -> None:
        if (
            source.provider is not probe.provider
            or source.provider_version != probe.provider_version
            or source.adapter_version != probe.adapter_version
            or source.source_schema_version != probe.source_schema_version
        ):
            raise DisplayLabelError("provider label provenance changed")

    @staticmethod
    def _require_same_identity(
        listed: SourceSession, enriched: SourceSession
    ) -> None:
        if (
            enriched.provider is not listed.provider
            or enriched.source_installation_id.get_secret_value()
            != listed.source_installation_id.get_secret_value()
            or enriched.source_project_id.get_secret_value()
            != listed.source_project_id.get_secret_value()
            or enriched.source_session_id.get_secret_value()
            != listed.source_session_id.get_secret_value()
            or enriched.started_at != listed.started_at
        ):
            raise DisplayLabelError("provider summary identity changed")

    @staticmethod
    def _private_label(value: SecretStr | None, *, max_length: int) -> str | None:
        if value is None:
            return None
        return minimize_private_display_name(
            value.get_secret_value(), max_length=max_length
        )


class ManualDisplayLabelService:
    """Manage local-only overrides without contacting or renaming the provider."""

    def __init__(self, repository: ManualDisplayLabelRepository) -> None:
        self._repository = repository

    def set(
        self,
        *,
        entity_kind: LabelEntityKind,
        entity_id: str,
        value: SecretStr,
        expected_revision: int,
    ) -> ManualDisplayLabelResult:
        max_length = (
            PROJECT_DISPLAY_NAME_MAX_LENGTH
            if entity_kind is LabelEntityKind.PROJECT
            else SESSION_DISPLAY_NAME_MAX_LENGTH
        )
        minimized = minimize_private_display_name(
            value.get_secret_value(), max_length=max_length
        )
        if minimized is None:
            raise InvalidDisplayLabelError("local display label is invalid")
        self._repository.initialize()
        return self._repository.set_manual_display_label(
            entity_kind=entity_kind,
            entity_id=entity_id,
            value=minimized,
            expected_revision=expected_revision,
        )

    def clear(
        self,
        *,
        entity_kind: LabelEntityKind,
        entity_id: str,
        expected_revision: int,
    ) -> ManualDisplayLabelResult:
        self._repository.initialize()
        return self._repository.clear_manual_display_label(
            entity_kind=entity_kind,
            entity_id=entity_id,
            expected_revision=expected_revision,
        )
