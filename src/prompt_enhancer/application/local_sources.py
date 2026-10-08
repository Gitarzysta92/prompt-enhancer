"""Consent and bounded ingestion use cases for local provider sources."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from ..adapters.base import ProviderAdapter
from ..domain import DataTier, Provider, StrictModel
from ..ingestion import (
    ConsentRequiredError,
    IngestionError,
    IngestionReport,
    IngestionSelection,
)
from .display_labels import LabelEnrichmentReport
from .verification import VerificationCapability

MAX_LOCAL_SOURCE_SELECTORS = 100


class LocalSourceRepository(Protocol):
    def has_active_consent(self, provider: Provider, tier: DataTier) -> bool: ...

    def grant_consent(self, provider: Provider, tier: DataTier) -> None: ...

    def revoke_consent(self, provider: Provider, tier: DataTier) -> None: ...

    def provider_catalog_summary(self, provider: Provider) -> dict[str, int]: ...

    def selection_is_indexed(
        self,
        provider: Provider,
        *,
        project_ids: frozenset[str],
        session_ids: frozenset[str],
    ) -> bool: ...


class IngestionRunner(Protocol):
    def ingest(
        self,
        adapter: ProviderAdapter,
        *,
        page_limit: int = 100,
        selection: IngestionSelection | None = None,
    ) -> IngestionReport: ...


class LabelEnrichmentRunner(Protocol):
    def enrich(
        self,
        *,
        project_ids: frozenset[str],
        session_ids: frozenset[str],
        max_sessions: int,
    ) -> LabelEnrichmentReport: ...


CodexAdapterFactory = Callable[[bool], ProviderAdapter]
AutomationRevoker = Callable[[Provider], int]


class LocalSourceSelectionError(RuntimeError):
    """A safe selector is missing, excessive, or absent from the local index."""


class CodexLocalSourceStatus(StrictModel):
    consent_active: bool
    indexed_sessions: int
    indexed_projects: int
    verification_capability: VerificationCapability


class CodexLocalSourceService:
    """Application boundary for explicit, user-triggered Codex source access."""

    _TIER = DataTier.REDACTED_CONTENT

    def __init__(
        self,
        repository: LocalSourceRepository,
        ingestion: IngestionRunner,
        adapter_factory: CodexAdapterFactory,
        verification_capability: VerificationCapability,
        label_enrichment: LabelEnrichmentRunner | None = None,
        automation_revoker: AutomationRevoker | None = None,
    ) -> None:
        self._repository = repository
        self._ingestion = ingestion
        self._adapter_factory = adapter_factory
        self._verification_capability = verification_capability
        self._label_enrichment = label_enrichment
        self._automation_revoker = automation_revoker

    def set_automation_revoker(self, revoker: AutomationRevoker) -> None:
        """Bind the local scheduler only at the trusted composition root."""

        self._automation_revoker = revoker

    def status(self) -> CodexLocalSourceStatus:
        counts = self._repository.provider_catalog_summary(Provider.CODEX)
        return CodexLocalSourceStatus(
            consent_active=self._repository.has_active_consent(
                Provider.CODEX, self._TIER
            ),
            indexed_sessions=counts["sessions"],
            indexed_projects=counts["projects"],
            verification_capability=self._verification_capability,
        )

    def grant_local_history(self) -> CodexLocalSourceStatus:
        self._repository.grant_consent(Provider.CODEX, self._TIER)
        return self.status()

    def revoke_local_history(self) -> CodexLocalSourceStatus:
        self._repository.revoke_consent(Provider.CODEX, self._TIER)
        if self._automation_revoker is not None:
            try:
                self._automation_revoker(Provider.CODEX)
            except Exception:
                # Consent is already authoritative. A worker rechecks it before
                # every read even if eager queue cancellation fails.
                pass
        return self.status()

    def index(self, *, max_sessions: int) -> IngestionReport:
        self._require_consent()
        return self._ingestion.ingest(
            self._adapter_factory(False),
            selection=IngestionSelection(max_sessions=max_sessions),
        )

    def analyze(
        self,
        *,
        project_ids: frozenset[str],
        session_ids: frozenset[str],
        max_sessions: int,
    ) -> IngestionReport:
        self._require_consent()
        if len(project_ids) + len(session_ids) > MAX_LOCAL_SOURCE_SELECTORS:
            raise LocalSourceSelectionError(
                "local-source selection exceeds the safe bound"
            )
        selection = IngestionSelection(
            project_ids=project_ids,
            session_ids=session_ids,
            max_sessions=max_sessions,
        )
        if not selection.has_selector:
            raise LocalSourceSelectionError(
                "operational history access requires an explicit safe selection"
            )
        if not self._repository.selection_is_indexed(
            Provider.CODEX,
            project_ids=selection.project_ids,
            session_ids=selection.session_ids,
        ):
            raise LocalSourceSelectionError(
                "local-source selection is not present in the safe index"
            )
        return self._ingestion.ingest(
            self._adapter_factory(True), selection=selection
        )

    def enrich_labels(
        self,
        *,
        project_ids: frozenset[str],
        session_ids: frozenset[str],
        max_sessions: int,
    ) -> LabelEnrichmentReport:
        if self._label_enrichment is None:
            raise IngestionError("local label enrichment is unavailable")
        return self._label_enrichment.enrich(
            project_ids=project_ids,
            session_ids=session_ids,
            max_sessions=max_sessions,
        )

    def _require_consent(self) -> None:
        if not self._repository.has_active_consent(Provider.CODEX, self._TIER):
            raise ConsentRequiredError(
                "explicit source consent is required before provider access"
            )


ClaudeHookAdapterFactory = Callable[[], ProviderAdapter]
HookLedgerSummary = Callable[[], dict[str, int]]
# Optional owner-authorized transcript adapter (ADR 0011). When present it is
# the primary Claude source: history, tokens, tool errors, titles.
ClaudeTranscriptAdapterFactory = Callable[[], ProviderAdapter]
TranscriptSupersede = Callable[[ProviderAdapter], int]


class ClaudeCodeLocalSourceStatus(StrictModel):
    """Content-free state of the hook-based Claude Code source.

    ``captured_*`` counts describe the local hook ledger - events the receiver
    has recorded under consent but that may not yet be indexed into the main
    session tables.  ``indexed_*`` counts describe what indexing has admitted.
    Neither is a claim that every provider event was captured.
    """

    consent_active: bool
    captured_sessions: int
    captured_events: int
    captured_requests: int = 0
    telemetry_sessions: int = 0
    indexed_sessions: int
    indexed_projects: int
    verification_capability: VerificationCapability
    capture_channel: str = "claude_code_hooks"
    telemetry_channel: str = "claude_code_otlp"
    reads_transcripts: bool = False
    persists_content: bool = False


class ClaudeCodeLocalSourceService:
    """Application boundary for the hook-captured Claude Code source.

    Hooks are content-free by construction, so there is one capture mode and
    one consent tier; there is no separate label or operational-history read.
    Revoking consent stops the receiver from recording anything further; it
    does not delete what was already recorded, and says so.
    """

    _TIER = DataTier.REDACTED_CONTENT

    def __init__(
        self,
        repository: LocalSourceRepository,
        ingestion: IngestionRunner,
        adapter_factory: ClaudeHookAdapterFactory,
        ledger_summary: HookLedgerSummary,
        verification_capability: VerificationCapability,
        automation_revoker: AutomationRevoker | None = None,
        transcript_adapter_factory: ClaudeTranscriptAdapterFactory | None = None,
        transcript_supersede: TranscriptSupersede | None = None,
    ) -> None:
        self._repository = repository
        self._ingestion = ingestion
        self._adapter_factory = adapter_factory
        self._ledger_summary = ledger_summary
        self._verification_capability = verification_capability
        self._automation_revoker = automation_revoker
        self._transcript_adapter_factory = transcript_adapter_factory
        self._transcript_supersede = transcript_supersede

    def set_automation_revoker(self, revoker: AutomationRevoker) -> None:
        self._automation_revoker = revoker

    def status(self) -> ClaudeCodeLocalSourceStatus:
        counts = self._repository.provider_catalog_summary(Provider.CLAUDE_CODE)
        try:
            captured = self._ledger_summary()
        except Exception:
            captured = {"sessions": 0, "events": 0}
        return ClaudeCodeLocalSourceStatus(
            consent_active=self._repository.has_active_consent(
                Provider.CLAUDE_CODE, self._TIER
            ),
            captured_sessions=int(captured.get("sessions", 0)),
            captured_events=int(captured.get("events", 0)),
            captured_requests=int(captured.get("requests", 0)),
            telemetry_sessions=int(captured.get("telemetry_sessions", 0)),
            indexed_sessions=counts["sessions"],
            indexed_projects=counts["projects"],
            verification_capability=self._verification_capability,
            # Owner-authorized transcript reading (ADR 0011) is the primary
            # Claude source when wired; the status says so rather than hiding it.
            reads_transcripts=self._transcript_adapter_factory is not None,
        )

    def grant_local_history(self) -> ClaudeCodeLocalSourceStatus:
        self._repository.grant_consent(Provider.CLAUDE_CODE, self._TIER)
        return self.status()

    def revoke_local_history(self) -> ClaudeCodeLocalSourceStatus:
        self._repository.revoke_consent(Provider.CLAUDE_CODE, self._TIER)
        if self._automation_revoker is not None:
            try:
                self._automation_revoker(Provider.CLAUDE_CODE)
            except Exception:
                pass
        return self.status()

    def index(self, *, max_sessions: int) -> IngestionReport:
        if not self._repository.has_active_consent(Provider.CLAUDE_CODE, self._TIER):
            raise ConsentRequiredError(
                "explicit source consent is required before provider access"
            )
        if self._transcript_adapter_factory is None:
            return self._ingestion.ingest(
                self._adapter_factory(),
                selection=IngestionSelection(max_sessions=max_sessions),
            )
        # Transcripts first: they are the provider's own record. Where one
        # exists it supersedes earlier hook-captured events for that session,
        # and the hook adapter then contributes only sessions without one.
        transcripts = self._transcript_adapter_factory()
        from ..adapters.base import AdapterHealth

        if transcripts.probe().health is not AdapterHealth.READY:
            # No transcript root on this machine: hooks are the only source.
            return self._ingestion.ingest(
                self._adapter_factory(),
                selection=IngestionSelection(max_sessions=max_sessions),
            )
        if self._transcript_supersede is not None:
            self._transcript_supersede(transcripts)
        first = self._ingestion.ingest(
            transcripts, selection=IngestionSelection(max_sessions=max_sessions)
        )
        second = self._ingestion.ingest(
            self._adapter_factory(),
            selection=IngestionSelection(max_sessions=max_sessions),
        )
        return first.model_copy(update={
            "sessions_seen": first.sessions_seen + second.sessions_seen,
            "sessions_selected": first.sessions_selected + second.sessions_selected,
            "sessions_inserted": first.sessions_inserted + second.sessions_inserted,
            "sessions_updated": first.sessions_updated + second.sessions_updated,
            "events_seen": first.events_seen + second.events_seen,
            "events_inserted": first.events_inserted + second.events_inserted,
            "events_updated": first.events_updated + second.events_updated,
            "metrics_written": first.metrics_written + second.metrics_written,
            "truncated": first.truncated or second.truncated,
        })
