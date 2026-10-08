"""Application composition root for the private local runtime.

Concrete infrastructure is selected here so CLI and HTTP entry points do not
independently assemble databases, privacy primitives, and use-case services.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from . import __version__
from .config import AppSettings, prepare_app_home
from .database import Database
from .ingestion import IngestionService
from .privacy import (
    Pseudonymizer,
    load_or_create_api_token,
    load_or_create_pseudonymizer,
)

if TYPE_CHECKING:
    from .application.analysis import (
        MetricCoverageService,
        MetricLifecycleEvidenceService,
        MetricReadinessService,
        ProjectQualityAggregationService,
        SessionModelLinkExperimentService,
        SessionModelEnsembleService,
        SessionTextAnalysisService,
        TaskAnalysisService,
    )
    from .application.providers import (
        ProviderCompatibilityCatalog,
        ProviderSurfaceCompatibilityPolicy,
    )
    from .application.discovery import (
        DiscoveryPersistenceService,
        TaskDiscoveryEngine,
        TaskReviewService,
    )
    from .application.local_sources import CodexLocalSourceService
    from .application.task_lifecycle import TaskLifecycleService
    from .application.jobs import AnalysisJobService, AnalysisJobWorker
    from .application.automation import (
        AutomationGrantService,
        AutomationGrantWorker,
    )
    from .infrastructure.control_plane import DevelopmentControlPlane
    from fastapi import FastAPI


@dataclass(frozen=True, slots=True)
class LocalApplication:
    """Concrete services for one local application installation.

    The API token is deliberately not retained on this object, exposed as a
    property, or included in its representation. It is loaded only when the HTTP
    adapter is constructed.
    """

    settings: AppSettings
    database: Database
    pseudonymizer: Pseudonymizer

    def create_ingestion_service(self) -> IngestionService:
        """Construct the ingestion use case from already validated dependencies."""
        return IngestionService(self.database, self.pseudonymizer)

    def create_codex_local_source_service(
        self,
    ) -> CodexLocalSourceService:
        """Construct explicit consent, index, and selected-analysis commands."""

        from .application.display_labels import (
            LabelObservationMethod,
            ProviderLabelSource,
            ProviderDisplayLabelEnrichmentService,
            ProviderDisplayLabelPolicy,
        )
        from .application.local_sources import CodexLocalSourceService
        from .domain import DataTier, Provider
        from .infrastructure.providers.codex_app_server import (
            LABEL_EXTRACTOR_VERSION,
        )
        from .infrastructure.verification import validation_only_capability

        return CodexLocalSourceService(
            self.database,
            self.create_ingestion_service(),
            lambda operational_history: self.create_codex_adapter(
                operational_history=operational_history
            ),
            validation_only_capability(),
            ProviderDisplayLabelEnrichmentService(
                self.database,
                self.pseudonymizer,
                lambda: self.create_codex_adapter(label_enrichment=True),
                ProviderDisplayLabelPolicy(
                    provider=Provider.CODEX,
                    consent_tier=DataTier.REDACTED_CONTENT,
                    observation_method=LabelObservationMethod.THREAD_READ_SUMMARY,
                    extractor_version=LABEL_EXTRACTOR_VERSION,
                    project_label_source=ProviderLabelSource.PATH_BASENAME,
                    session_label_source=ProviderLabelSource.EXPLICIT_TITLE,
                ),
            ),
        )

    @staticmethod
    def create_codex_adapter(
        *,
        operational_history: bool = False,
        label_enrichment: bool = False,
    ):
        """Select the documented, read-only Codex infrastructure adapter."""

        from .infrastructure.providers.codex_app_server import (
            CodexAppServerAdapter,
            CodexReadMode,
        )

        if operational_history and label_enrichment:
            raise ValueError("Codex adapter modes are mutually exclusive")
        if operational_history:
            mode = CodexReadMode.OPERATIONAL_HISTORY
        elif label_enrichment:
            mode = CodexReadMode.LABEL_ENRICHMENT
        else:
            mode = CodexReadMode.METADATA_INDEX
        return CodexAppServerAdapter(mode=mode)

    def claude_home(self):
        """Env var, then the owner-supplied override file, then ~/.claude."""

        from .infrastructure.providers.claude_code_hooks.transcript_reader import (
            default_claude_home,
        )

        return default_claude_home(override_file=self.settings.claude_home_override_path)

    def set_claude_home(self, path) -> None:
        """Persist an owner-supplied Claude home as a private one-line file."""

        from .privacy import write_private_text

        write_private_text(self.settings.claude_home_override_path, str(path))

    def create_claude_transcript_adapter(self):
        """Owner-authorized transcript adapter (ADR 0011): history, tokens, tool errors."""

        from .infrastructure.providers.claude_code_hooks.transcript_adapter import (
            ClaudeTranscriptAdapter,
        )

        return ClaudeTranscriptAdapter(self.pseudonymizer, claude_home=self.claude_home())

    def create_claude_hook_adapter(self):
        """Read-only adapter over the local Claude Code hook ledger.

        Sessions covered by a transcript file yield no hook events; the
        transcript adapter is their single source of record.
        """

        from .infrastructure.providers.claude_code_hooks.adapter import (
            ClaudeCodeHookAdapter,
        )

        covered = self.create_claude_transcript_adapter().covered_hook_session_ids()
        return ClaudeCodeHookAdapter(
            self.database.claude_hook_ledger(),
            transcript_coverage=lambda hook_session_id: hook_session_id in covered,
        )

    def _supersede_hook_events_covered_by_transcripts(self, transcripts) -> int:
        """Delete receiver-clock events for sessions a transcript now covers."""

        from .infrastructure.providers.claude_code_hooks.contracts import (
            SOURCE_SCHEMA_VERSION as HOOK_SOURCE_SCHEMA_VERSION,
        )
        from .infrastructure.providers.claude_code_hooks.transcript_reader import (
            catalog_session_id_for,
        )

        removed = 0
        for hook_session_id in transcripts.covered_hook_session_ids():
            # catalog id = HMAC(claude_code:session:<installation>, hook pseudonym)
            installation_id = self.pseudonymizer.pseudonymize(
                "claude_code:installation", "claude-code-hooks-local-v1"
            )
            catalog_id = self.pseudonymizer.pseudonymize(
                f"claude_code:session:{installation_id}", hook_session_id
            )
            removed += self.database.supersede_session_events(
                catalog_id, only_source_schema_version=HOOK_SOURCE_SCHEMA_VERSION
            )
        del catalog_session_id_for
        return removed

    def create_claude_local_source_service(self):
        """Consent, status, and index commands for the hook-captured source."""

        from .application.local_sources import ClaudeCodeLocalSourceService
        from .infrastructure.verification import validation_only_capability

        return ClaudeCodeLocalSourceService(
            self.database,
            self.create_ingestion_service(),
            self.create_claude_hook_adapter,
            lambda: self.database.claude_hook_ledger().summary(),
            validation_only_capability(),
            transcript_adapter_factory=self.create_claude_transcript_adapter,
            transcript_supersede=self._supersede_hook_events_covered_by_transcripts,
        )

    def create_onboarding_service(
        self, codex_source_service=None, claude_source_service=None, *, enable_automation=None, after_index=None
    ):
        """First-run detection, one consent, first index, periodic refresh."""

        from .application.onboarding import OnboardingService
        from .domain import Provider

        codex_service = codex_source_service or self.create_codex_local_source_service()
        claude_service = claude_source_service or self.create_claude_local_source_service()

        def discover_tasks(provider: Provider) -> None:
            # Propose task candidates from the freshly indexed sessions so the
            # Discovery inbox fills without the CLI. Candidate ids are
            # deterministic and persistence skips existing ones, so this is
            # idempotent; failures never fail the index.
            try:
                sessions = []
                offset = 0
                while len(sessions) < 5_000:
                    page = self.database.list_sessions(limit=500, offset=offset, provider=provider)
                    for item in page:
                        session = self.database.get_session(str(item["session_id"]))
                        if session is not None:
                            sessions.append(session)
                    offset += len(page)
                    if len(page) < 500:
                        break
                if sessions:
                    self.create_discovery_persistence_service().discover_and_persist(sessions)
                # Single-session candidates are accepted automatically with
                # decision_source="automation" (owner's direction, 2026-08-19);
                # multi-session groupings still wait for a person.
                self.create_singleton_auto_accepter().run(provider=provider)
            except Exception:
                pass
            if after_index is not None:
                # e.g. the model-judge sweep over newly indexed sessions; never fails the index.
                try:
                    after_index(provider)
                except Exception:
                    pass

        def index_codex() -> int:
            report = codex_service.index(max_sessions=500)
            discover_tasks(Provider.CODEX)
            # Fill missing Codex titles in bounded batches without a second click.
            try:
                missing: list[str] = []
                offset = 0
                while len(missing) < 25:
                    page = self.database.list_sessions(limit=100, offset=offset)
                    for row in page:
                        if row.get("provider") == "codex" and not row.get("session_display_name"):
                            missing.append(str(row["session_id"]))
                            if len(missing) >= 25:
                                break
                    offset += len(page)
                    if len(page) < 100:
                        break
                if missing:
                    codex_service.enrich_labels(
                        project_ids=frozenset(), session_ids=frozenset(missing), max_sessions=25
                    )
            except Exception:
                pass
            return int(report.sessions_seen)

        def index_claude() -> int:
            report = claude_service.index(max_sessions=1000)
            discover_tasks(Provider.CLAUDE_CODE)
            return int(report.sessions_seen)

        return OnboardingService(
            self.database,
            claude_home=self.claude_home,
            set_claude_home=self.set_claude_home,
            index_codex=index_codex,
            index_claude=index_claude,
            enable_automation=enable_automation,
        )

    def create_local_model_service(self):
        """Local model runtimes: registry under the app home, llama-server on loopback."""

        from .application.local_models import LocalModelService, detect_llama_server

        home = self.settings.home
        models_root = self.settings.local_models_dir
        return LocalModelService(
            models_root,
            llama_server=lambda: detect_llama_server(app_home=home, models_root=models_root),
        )

    def create_model_judge_service(self, local_model_service=None, calibration_service=None):
        """Model-judge lane over the active local model (ADR 0013 section 4)."""

        from pathlib import Path

        from .application.analysis.model_judge import ModelJudgeService
        from .application.local_models import RuntimeState

        models = local_model_service or self.create_local_model_service()
        calibration = calibration_service or self.create_calibration_rating_service()

        def active_model():
            overview = models.overview()
            for item in overview.models:
                if item.runtime.state is RuntimeState.RUNNING:
                    identity = item.record.source_file or Path(item.record.path).name
                    return item.record.alias, identity
            return None

        return ModelJudgeService(
            repository=self.database.model_judgment_repository(),
            ratings=self.database.calibration_rating_repository(),
            access=self.database,
            source_factory=self.create_text_analysis_source,
            chat=models.chat,
            active_model=active_model,
            session_lookup=self.database.get_session,
            metrics_lookup=self.database.get_session_metrics,
        ), calibration

    def create_prompt_check_service(self, local_model_service=None):
        """Prompt validation in context: deterministic cues + optional local-model commentary (ADR 0015)."""

        from pathlib import Path

        from .application.local_models import RuntimeState
        from .application.prompt_check import PromptCheckService

        models = local_model_service or self.create_local_model_service()

        def active_model() -> str | None:
            try:
                overview = models.overview()
            except Exception:
                return None
            for item in overview.models:
                if item.runtime.state is RuntimeState.RUNNING:
                    return item.record.alias
            return None

        def session_context(session_id: str):
            """The session's redacted tail as prior context (metrics-only storage still applies)."""

            from .application.analysis.text_contracts import TextRole, TextTaskProfile
            from .application.analysis.text_source import (
                TextAnalysisPurpose,
                TextAnalysisSelection,
                TextSourceAccessGrant,
            )
            from .application.prompt_check import MAX_CONTEXT_MESSAGE_CHARS, PromptCheckMessage
            from .domain import DataTier, Provider

            session = self.database.get_session(session_id)
            if session is None:
                return ()
            provider = Provider(getattr(session, "provider"))
            if not self.database.has_active_consent(provider, DataTier.REDACTED_CONTENT):
                return ()
            source = self.create_text_analysis_source(provider)
            grant = TextSourceAccessGrant(
                purpose=TextAnalysisPurpose.TEXT_ANALYSIS,
                provider=provider,
                session_id=session_id,
                data_tier=DataTier.REDACTED_CONTENT,
                per_run_confirmation_active=True,
                local_only=True,
                content_persistence_allowed=False,
            )
            window = source.read(
                selection=TextAnalysisSelection(provider=provider, session_id=session_id),
                grant=grant,
                task_profile=TextTaskProfile(applicability=()),
            )
            out = []
            for message in window.messages[-12:]:
                text = message.text.get_secret_value()[:MAX_CONTEXT_MESSAGE_CHARS]
                if not text.strip():
                    continue
                out.append(PromptCheckMessage(role="user" if message.role is TextRole.USER else "assistant", content=text))
            return tuple(out)

        return PromptCheckService(
            self.database.prompt_check_repository(),
            pseudonymize=self.pseudonymizer.pseudonymize,
            chat=models.chat,
            active_model=active_model,
            session_context=session_context,
        )

    def create_agent_catalog_service(self):
        """Private authored-Agent project/session navigation catalog."""

        from .application.agent_catalog import AgentCatalogService
        from .infrastructure.sqlite.agent_catalog import (
            AgentCatalogSqliteDatabase,
            SqliteAgentCatalogRepository,
        )

        database = AgentCatalogSqliteDatabase(self.settings.agent_catalog_path)
        return AgentCatalogService(SqliteAgentCatalogRepository(database))

    def create_agent_hardening_service(self, local_agent_service):
        """On-demand content-free integrity and restart-readiness status."""

        from .application.agent_hardening import AgentHardeningService
        from .infrastructure.sqlite.agent_catalog import AgentCatalogSqliteDatabase
        from .infrastructure.sqlite.agent_hardening import SqliteAgentHardeningProbe

        database = AgentCatalogSqliteDatabase(self.settings.agent_catalog_path)
        return AgentHardeningService(
            SqliteAgentHardeningProbe(database),
            local_agent_service,
        )

    def create_agent_mcp_connection_service(self, api_token: str):
        """Durable authority for direct, process-free Agent MCP clients."""

        from .application.agent_mcp_connections import AgentMcpConnectionService
        from .infrastructure.sqlite.agent_catalog import (
            AgentCatalogSqliteDatabase,
            SqliteAgentMcpConnectionRepository,
        )

        database = AgentCatalogSqliteDatabase(self.settings.agent_catalog_path)
        return AgentMcpConnectionService(
            SqliteAgentMcpConnectionRepository(database),
            token_pepper=api_token,
        )

    def create_mcp_registry_catalog_service(self):
        """Read-only official MCP Registry catalog with public local fallback."""

        from .application.mcp_registry_catalog import McpRegistryCatalogService
        from .infrastructure.mcp_registry import (
            JsonMcpRegistryCache,
            OfficialMcpRegistryHttpClient,
        )

        return McpRegistryCatalogService(
            OfficialMcpRegistryHttpClient(),
            JsonMcpRegistryCache(self.settings.mcp_registry_cache_path),
        )

    def create_mcp_server_management_service(
        self,
        catalog_service=None,
        *,
        connection_factory=None,
    ):
        """Reviewed plans plus bounded, non-tool compatibility probes."""

        from .application.mcp_guarded_host import McpGuardedHost
        from .application.mcp_server_management import McpManagedServerService
        from .infrastructure.mcp_guarded_host import (
            OfficialSdkMcpConnectionFactory,
            OfficialSdkMcpProbeClient,
        )
        from .infrastructure.mcp_package_installer import (
            McpbPackageInstaller,
            PinnedHttpsMcpArtifactDownloader,
        )
        from .infrastructure.mcp_secret_vault import platform_mcp_secret_vault
        from .infrastructure.sqlite.agent_catalog import AgentCatalogSqliteDatabase
        from .infrastructure.sqlite.mcp_server_management import (
            SqliteMcpManagedServerRepository,
        )

        database = AgentCatalogSqliteDatabase(self.settings.agent_catalog_path)
        connections = connection_factory or OfficialSdkMcpConnectionFactory()
        host = McpGuardedHost(
            OfficialSdkMcpProbeClient(connection_factory=connections)
        )
        return McpManagedServerService(
            SqliteMcpManagedServerRepository(database),
            catalog_service or self.create_mcp_registry_catalog_service(),
            platform_mcp_secret_vault(),
            host,
            McpbPackageInstaller(
                self.settings.mcp_packages_dir,
                PinnedHttpsMcpArtifactDownloader(),
                host,
            ),
        )

    def create_mcp_managed_runtime_service(
        self,
        management_service,
        *,
        connection_factory=None,
    ):
        """Inert-until-start MCP host ownership and content-free call receipts."""

        from .application.mcp_managed_runtime import McpManagedRuntimeService
        from .infrastructure.mcp_guarded_host import OfficialSdkMcpConnectionFactory
        from .infrastructure.mcp_managed_host_supervisor import (
            McpManagedHostSupervisor,
        )
        from .infrastructure.sqlite.agent_catalog import AgentCatalogSqliteDatabase
        from .infrastructure.sqlite.mcp_managed_runtime import (
            SqliteMcpManagedRuntimeReceiptRepository,
        )

        connections = connection_factory or OfficialSdkMcpConnectionFactory()
        database = AgentCatalogSqliteDatabase(self.settings.agent_catalog_path)
        return McpManagedRuntimeService(
            management_service,
            McpManagedHostSupervisor(connections),
            SqliteMcpManagedRuntimeReceiptRepository(database),
        )

    def create_local_agent_service(
        self,
        local_model_service=None,
        *,
        mcp_managed_runtime_service=None,
    ):
        """Local agent workspace (ADR 0016): one folder, tools with approval, the active local model."""

        import os
        from pathlib import Path

        from .application.agent_artifacts import AgentArtifactService
        from .application.agent_attachments import AgentAttachmentService
        from .application.local_agent import LocalAgentService
        from .application.local_models import RuntimeCapabilities
        from .infrastructure.sqlite.agent_attachments import (
            SqliteAgentAttachmentRepository,
        )
        from .infrastructure.sqlite.agent_artifacts import (
            SqliteAgentArtifactRepository,
        )
        from .infrastructure.sqlite.agent_catalog import AgentCatalogSqliteDatabase
        models = local_model_service or self.create_local_model_service()

        def active_model() -> str | None:
            try:
                aliases = models.running_aliases()
            except Exception:
                return None
            return aliases[0] if aliases else None

        def model_ready(alias: str) -> bool:
            try:
                return models.running_aliases() == (alias,)
            except Exception:
                return False

        def runtime_capabilities(alias: str) -> RuntimeCapabilities:
            try:
                status = models.coordinator_status()
            except Exception:
                return RuntimeCapabilities()
            if status.served is None or status.served.alias != alias:
                return RuntimeCapabilities()
            return status.capabilities

        def context_preflight(alias: str, body: bytes, compacted_messages: int):
            return models.preflight_chat(
                alias,
                body,
                compacted_messages=compacted_messages,
            )

        user_home = Path.home()
        codex_home = Path(os.environ.get("CODEX_HOME", user_home / ".codex")).expanduser()
        protected_roots = (
            self.settings.home,
            self.settings.local_models_dir,
            self.claude_home(),
            codex_home,
            user_home / ".claude.json",
            user_home / ".ssh",
            user_home / ".gnupg",
            user_home / ".aws",
            user_home / ".azure",
            user_home / ".kube",
            user_home / ".docker",
            user_home / ".npmrc",
            user_home / ".pypirc",
            user_home / ".git-credentials",
            user_home / ".netrc",
        )
        catalog = self.create_agent_catalog_service()
        artifacts = AgentArtifactService(
            SqliteAgentArtifactRepository(
                AgentCatalogSqliteDatabase(self.settings.agent_catalog_path)
            ),
            catalog,
        )
        attachments = AgentAttachmentService(
            SqliteAgentAttachmentRepository(
                AgentCatalogSqliteDatabase(self.settings.agent_catalog_path)
            ),
            catalog,
        )
        return LocalAgentService(
            chat=models.chat,
            open_chat=models.open_chat,
            active_model=active_model,
            model_ready=model_ready,
            forbidden_roots=protected_roots,
            catalog=catalog,
            artifacts=artifacts,
            attachments=attachments,
            runtime_capabilities=runtime_capabilities,
            context_preflight=context_preflight,
            mcp_managed_runtime=mcp_managed_runtime_service,
        )

    def create_shared_folder_services(self):
        """ADR 0018: the folder-share registry, owner service and peer client."""

        from .application.shared_folders import (
            PeerFolderClient,
            SHARED_FOLDER_DATABASE_FILENAME,
            SharedFolderService,
            SharedFolderStore,
        )

        store = SharedFolderStore(
            self.settings.home / SHARED_FOLDER_DATABASE_FILENAME
        )
        service = SharedFolderService(store, forbidden_roots=(self.settings.home,))
        client = PeerFolderClient(store)
        return service, client

    def create_annotation_services(self, local_model_service=None, model_judge_service=None):
        """ADR 0017: agent annotation surface + the embedded central annotation server + remote client."""

        from .application.annotation import (
            AnnotationService,
            CENTRAL_ANNOTATION_DATABASE_FILENAME,
            CentralAnnotationServer,
            CentralAnnotationStore,
            RemoteAnnotationClient,
        )
        from .application.local_models import RuntimeState

        models = local_model_service or self.create_local_model_service()
        judge = model_judge_service
        if judge is None:
            judge, _ = self.create_model_judge_service(models)

        def active_model() -> str | None:
            try:
                overview = models.overview()
            except Exception:
                return None
            for item in overview.models:
                if item.runtime.state is RuntimeState.RUNNING:
                    return item.record.alias
            return None

        service = AnnotationService(judge, list_sessions=self.database.list_sessions)
        store = CentralAnnotationStore(
            self.settings.home / CENTRAL_ANNOTATION_DATABASE_FILENAME
        )
        central = CentralAnnotationServer(store, chat=models.chat, active_model=active_model)
        remote_client = RemoteAnnotationClient(
            service,
            submit=central.annotate_batch,  # locally in-process; on the VPS this becomes an HTTPS call
            destination="embedded central server (this machine)",
            user_label="owner",
            list_sessions=self.database.list_sessions,
            active_model=active_model,
        )
        return service, central, remote_client

    def create_agent_read_surface(self, prompt_check_service=None):
        """Read-only allowlisted tools for connected coding agents (ADR 0014), plus the prompt check tool (ADR 0015)."""

        from .application.agent_surface import AgentReadSurface

        calibration = self.create_calibration_rating_service()
        judge, _ = self.create_model_judge_service(calibration_service=calibration)
        prompt_checks = prompt_check_service or self.create_prompt_check_service()

        def calibration_status() -> dict[str, object]:
            from .application.analysis.calibration_ratings import CalibrationSampleEmptyError

            try:
                sample = calibration.sample()
                members, metric_keys = sample.members, sample.metric_keys
            except CalibrationSampleEmptyError:
                members, metric_keys = (), ()
            metric_count = len(metric_keys)
            fully_rated = sum(1 for member in members if len(member.rated_metric_keys) >= metric_count) if metric_count else 0
            agreements = []
            for alias in judge.judged_model_aliases():
                report = judge.agreement(alias)
                agreements.append(
                    {
                        "model_alias": alias,
                        "judged_sessions": report.judged_sessions,
                        "metrics": [
                            {
                                "metric_key": m.metric_key,
                                "pairs": m.pairs,
                                "agreement_rate": m.agreement_rate,
                                "cohen_kappa": m.cohen_kappa,
                                "state": m.state,
                            }
                            for m in report.metrics
                        ],
                    }
                )
            return {
                "sample_sessions": len(members),
                "fully_rated_sessions": fully_rated,
                "metric_keys": list(metric_keys),
                "model_judge": agreements,
                "caveat": "model judgments are labels stored apart from metrics; they never become metric values",
            }

        def check_prompt(request):
            # The MCP process has no model runtime; when the dashboard server is running,
            # its prompt check (with the active model's commentary) answers instead.
            from .application.prompt_check import PromptCheckResult
            from .interfaces.hooks import post_prompt_check

            via_server = post_prompt_check(self.settings, request.model_dump(mode="json"))
            if via_server is not None:
                try:
                    return PromptCheckResult.model_validate(via_server)
                except Exception:
                    pass
            return prompt_checks.check(request)

        return AgentReadSurface(self.database, calibration_status=calibration_status, prompt_check=check_prompt)

    def create_calibration_rating_service(self):
        """Blind ratings of the owner's own sessions over a frozen sample."""

        from .application.analysis.calibration_ratings import CalibrationRatingService
        from .application.analysis.calibration_cases import CalibrationReviewService, prepare_calibration_case
        from .application.analysis.model_judge import read_judge_window, render_window
        from .domain import DataTier, Provider

        def provider_for(session_id):
            session = self.database.get_session(session_id)
            return Provider(session.provider) if session is not None else None

        def read_case(session_id, window_characters):
            provider = provider_for(session_id)
            context = read_judge_window(
                access=self.database, source_factory=self.create_text_analysis_source,
                provider=provider, session_id=session_id,
            )
            return prepare_calibration_case(
                session_id=session_id, provider=provider,
                window_fingerprint=context.analysis_window_fingerprint,
                rendered_window=render_window(context, max_characters=window_characters),
            )

        return CalibrationRatingService(
            self.database,
            self.database.calibration_rating_repository(),
            self.pseudonymizer,
            reviews=CalibrationReviewService(
                read_case=read_case, provider_for=provider_for,
                has_consent=lambda provider: self.database.has_active_consent(provider, DataTier.REDACTED_CONTENT),
                enabled=self.settings.session_reader_enabled,
            ),
        )

    def create_session_reader_service(self):
        """Owner-authorized on-demand session reading (ADR 0011); off by default."""

        from .application.analysis.session_reader import SessionReaderService
        from .domain import Provider
        from .infrastructure.providers.claude_code_hooks.transcript_reader import (
            ClaudeTranscriptReader,
        )
        from .infrastructure.providers.codex_app_server import CodexTextAnalysisSource
        from .infrastructure.providers.codex_app_server.session_reader import (
            CodexSessionReader,
        )

        return SessionReaderService(
            self.database,
            {
                Provider.CODEX: CodexSessionReader(CodexTextAnalysisSource(self.pseudonymizer)),
                Provider.CLAUDE_CODE: ClaudeTranscriptReader(self.pseudonymizer, claude_home=self.claude_home()),
            },
            enabled=self.settings.session_reader_enabled,
        )

    def create_manual_display_label_service(self):
        from .application.display_labels import ManualDisplayLabelService

        return ManualDisplayLabelService(self.database)

    def create_task_discovery_engine(self) -> TaskDiscoveryEngine:
        """Construct deterministic discovery with installation-local IDs."""

        from .application.discovery import TaskDiscoveryEngine
        from .infrastructure.identifiers import LocalArtifactIdFactory

        return TaskDiscoveryEngine(LocalArtifactIdFactory(self.pseudonymizer))

    def create_discovery_persistence_service(self) -> DiscoveryPersistenceService:
        """Construct discovery plus immutable candidate persistence."""

        from .application.discovery import (
            DiscoveryPersistenceService,
            TaskDiscoveryEngine,
        )
        from .infrastructure.identifiers import LocalArtifactIdFactory

        identifiers = LocalArtifactIdFactory(self.pseudonymizer)
        return DiscoveryPersistenceService(
            TaskDiscoveryEngine(identifiers),
            self.database.task_repository(),
            identifiers,
        )

    def create_singleton_auto_accepter(self):
        """Accept single-session candidates automatically, visibly as automation."""

        from .application.discovery.auto_accept import SingletonCandidateAutoAccepter

        return SingletonCandidateAutoAccepter(
            self.database.task_repository(),
            self.create_task_review_service(),
        )

    def create_task_review_service(self) -> TaskReviewService:
        """Construct explicit review commands over the narrow task repository."""

        from .application.discovery import TaskReviewService
        from .infrastructure.identifiers import LocalArtifactIdFactory

        return TaskReviewService(
            self.database.task_repository(),
            LocalArtifactIdFactory(self.pseudonymizer),
        )

    def create_task_lifecycle_service(self) -> TaskLifecycleService:
        """Construct explicit local-user work-state commands."""

        from .application.task_lifecycle import TaskLifecycleService
        from .infrastructure.identifiers import LocalArtifactIdFactory

        return TaskLifecycleService(
            self.database.task_lifecycle_repository(),
            LocalArtifactIdFactory(self.pseudonymizer),
        )

    def create_metric_lifecycle_evidence_service(
        self,
    ) -> MetricLifecycleEvidenceService:
        """Construct explicit confirmation over sealed model-run windows."""

        from .application.analysis.metric_lifecycle_evidence import (
            MetricLifecycleEvidenceService,
        )
        from .infrastructure.identifiers import LocalArtifactIdFactory

        return MetricLifecycleEvidenceService(
            self.database,
            self.database.model_ensemble_repository(),
            self.database.metric_lifecycle_evidence_repository(),
            LocalArtifactIdFactory(self.pseudonymizer),
        )

    def create_task_analysis_service(self) -> TaskAnalysisService:
        """Construct the immutable deterministic task-analysis use case."""

        from .application.analysis import TaskAnalysisService
        from .database import SCHEMA_VERSION
        from .infrastructure.identifiers import LocalArtifactIdFactory

        return TaskAnalysisService(
            self.database.task_repository(),
            self.database.analysis_run_repository(),
            self.database,
            LocalArtifactIdFactory(self.pseudonymizer),
            schema_version=SCHEMA_VERSION,
        )

    def create_provider_compatibility_catalog(self) -> ProviderCompatibilityCatalog:
        """Compose only built-in, release-reviewed compatibility probes."""

        from .application.providers import (
            ProviderCompatibilityCatalog,
            ProviderCompatibilityService,
            TrustedProviderRegistry,
        )
        from .infrastructure.providers.codex_app_server import (
            CODEX_TEXT_WINDOW_DECODER_DESCRIPTOR,
            CodexTextWindowCompatibilityProbe,
        )

        from .infrastructure.providers.claude_code_hooks.adapter import (
            CLAUDE_CODE_HOOKS_DECODER_DESCRIPTOR,
            ClaudeCodeHooksCompatibilityProbe,
        )
        from .infrastructure.providers.claude_code_hooks.text_source import (
            CLAUDE_CODE_TEXT_WINDOW_DECODER_DESCRIPTOR,
            ClaudeTranscriptTextWindowProbe,
        )

        descriptors = (
            CODEX_TEXT_WINDOW_DECODER_DESCRIPTOR,
            CLAUDE_CODE_TEXT_WINDOW_DECODER_DESCRIPTOR,
            CLAUDE_CODE_HOOKS_DECODER_DESCRIPTOR,
        )
        registry = TrustedProviderRegistry(descriptors)
        service = ProviderCompatibilityService(
            registry,
            (
                CodexTextWindowCompatibilityProbe(),
                ClaudeTranscriptTextWindowProbe(self.claude_home),
                ClaudeCodeHooksCompatibilityProbe(self.database.claude_hook_ledger()),
            ),
        )
        return ProviderCompatibilityCatalog(service, descriptors)

    def create_text_analysis_source(self, provider: Provider):
        """One local, read-only text source per provider for the P1 pipeline.

        Codex reads the app-server; Claude Code reads the owner's transcript
        file (ADR 0011).  Both redact locally before anything reaches a model.
        """

        from .domain import Provider
        from .infrastructure.providers.codex_app_server import CodexTextAnalysisSource

        if provider is Provider.CODEX:
            return CodexTextAnalysisSource(self.pseudonymizer)
        if provider is Provider.CLAUDE_CODE:
            from .infrastructure.providers.claude_code_hooks.text_source import (
                ClaudeTranscriptTextAnalysisSource,
            )
            from .infrastructure.providers.claude_code_hooks.transcript_reader import (
                ClaudeTranscriptReader,
            )

            reader = ClaudeTranscriptReader(self.pseudonymizer, claude_home=self.claude_home())
            return ClaudeTranscriptTextAnalysisSource(self.pseudonymizer, locate=reader.locate)
        raise ValueError("unsupported local text-analysis provider")

    def create_session_text_analysis_service(
        self,
        compatibility_policy: ProviderSurfaceCompatibilityPolicy,
    ) -> SessionTextAnalysisService:
        """Construct the explicit, one-session local P1 analysis command."""

        from .application.analysis import SessionTextAnalysisService
        from .application.persistence import SESSION_ANALYSIS_RUN_SCHEMA_VERSION
        from .infrastructure.identifiers import LocalArtifactIdFactory

        source_factory = self.create_text_analysis_source

        return SessionTextAnalysisService(
            self.database,
            self.database.session_analysis_run_repository(),
            source_factory,
            compatibility_policy,
            LocalArtifactIdFactory(self.pseudonymizer),
            schema_version=SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
        )

    def create_metric_readiness_service(
        self,
        compatibility_catalog: ProviderCompatibilityCatalog,
    ) -> MetricReadinessService:
        """Compose cached provider capability and persisted readiness queries."""

        from .application.analysis.metric_readiness import MetricReadinessService

        return MetricReadinessService(
            self.database,
            self.database.session_analysis_run_repository(),
            compatibility_catalog,
        )

    def create_metric_coverage_service(
        self,
        metric_readiness_service: MetricReadinessService,
    ) -> MetricCoverageService:
        """Compose exact local-index counts with cached capability truth."""

        from datetime import UTC, datetime

        from .application.analysis.metric_coverage import MetricCoverageService

        return MetricCoverageService(
            self.database.metric_coverage_repository(),
            metric_readiness_service,
            clock=lambda: datetime.now(UTC),
        )

    def create_session_model_link_experiment_service(
        self,
        compatibility_policy: ProviderSurfaceCompatibilityPolicy,
    ) -> SessionModelLinkExperimentService:
        """Compose the explicit offline neural comparison for one session."""

        from .application.analysis import SessionModelLinkExperimentService
        from .infrastructure.identifiers import LocalArtifactIdFactory
        from .infrastructure.text_models.session_links import (
            SubprocessSessionModelLinkRunner,
        )

        source_factory = self.create_text_analysis_source

        return SessionModelLinkExperimentService(
            self.database,
            self.database.model_link_experiment_repository(),
            source_factory,
            compatibility_policy,
            LocalArtifactIdFactory(self.pseudonymizer),
            SubprocessSessionModelLinkRunner(),
        )

    def create_objective_overrides_provider(self):
        """Objective (evidence-lane) overrides for one session, or None.

        Reads only already-indexed safe events and the reviewed task ledger;
        never the provider.  Any failure yields None so a run is still shown.
        """

        from .application.analysis.objective_metric_projection import (
            project_objective_metric_overrides_v3,
        )

        projector = self.create_typed_evidence_projector()

        def overrides(provider, session_id: str):
            try:
                projection = projector.project(provider=provider, session_id=session_id)
                if projection is None:
                    return None
                return project_objective_metric_overrides_v3(
                    projection, projector.descriptor_for_projection(projection)
                )
            except Exception:
                return None

        return overrides

    def create_typed_evidence_projector(self):
        """Safe-event typed evidence (decoder 4) for the measured metric lane.

        Tool events are actions; a test/build tool end with an exit status is
        a verification receipt; the verification *task* denominator is the one
        current accepted task revision that contains the session (ADR 0012) -
        never minted from an event.  One descriptor per provider so Claude
        transcript sessions project with their own adapter/schema identity.
        """

        from .application.analysis.provider_evidence import (
            CURRENT_SAFE_EVENT_EVIDENCE_CAPABILITIES,
            SAFE_EVENT_EVIDENCE_DECODER_CURRENT_VERSION,
            SAFE_EVENT_EVIDENCE_DECODER_KEY,
            SafeEventTypedEvidenceProjector,
        )

        from .application.providers import (
            CapabilityKey,
            DecoderDescriptor,
            ProviderIdentity,
            ProviderSurface,
            SchemaArtifactKind,
            SchemaArtifactProvenance,
        )
        from .domain import Provider
        from .infrastructure.identifiers import LocalArtifactIdFactory
        from .infrastructure.providers.codex_app_server.contracts import (
            ADAPTER_VERSION as CODEX_ADAPTER_VERSION,
            SOURCE_SCHEMA_VERSION as CODEX_SOURCE_SCHEMA_VERSION,
        )

        safe_event_capabilities = CURRENT_SAFE_EVENT_EVIDENCE_CAPABILITIES
        safe_event_descriptor = DecoderDescriptor(
            provider=ProviderIdentity(key="codex"),
            surface=ProviderSurface.OPERATIONAL_EVENTS,
            adapter_version=CODEX_ADAPTER_VERSION,
            decoder_key=SAFE_EVENT_EVIDENCE_DECODER_KEY,
            decoder_version=SAFE_EVENT_EVIDENCE_DECODER_CURRENT_VERSION,
            wire_schema_family="codex.app-server.v2.safe-events",
            canonical_schema_version=CODEX_SOURCE_SCHEMA_VERSION,
            schema_artifact=SchemaArtifactProvenance(
                artifact_key="codex.safe-event-index",
                artifact_version="1",
                kind=SchemaArtifactKind.MINIMIZED,
            ),
            capabilities=safe_event_capabilities,
        )
        from .infrastructure.providers.claude_code_hooks.transcript_adapter import (
            TRANSCRIPT_ADAPTER_VERSION,
            TRANSCRIPT_SOURCE_SCHEMA_VERSION,
        )

        claude_safe_event_descriptor = DecoderDescriptor(
            provider=ProviderIdentity(key="claude_code"),
            surface=ProviderSurface.OPERATIONAL_EVENTS,
            adapter_version=TRANSCRIPT_ADAPTER_VERSION,
            decoder_key=SAFE_EVENT_EVIDENCE_DECODER_KEY,
            decoder_version=SAFE_EVENT_EVIDENCE_DECODER_CURRENT_VERSION,
            wire_schema_family="claude-code.transcripts.v1.safe-events",
            canonical_schema_version=TRANSCRIPT_SOURCE_SCHEMA_VERSION,
            schema_artifact=SchemaArtifactProvenance(
                artifact_key="claude-code.safe-event-index",
                artifact_version="1",
                kind=SchemaArtifactKind.MINIMIZED,
            ),
            capabilities=safe_event_capabilities,
        )
        from .infrastructure.providers.claude_code_hooks.contracts import (
            ADAPTER_VERSION as CLAUDE_HOOK_ADAPTER_VERSION,
            SOURCE_SCHEMA_VERSION as CLAUDE_HOOK_SOURCE_SCHEMA_VERSION,
        )

        # The hook ledger authorizes action receipts only. It does not classify
        # shell invocations into test/build verification receipts and cannot
        # enumerate a complete provider stream, so no stronger evidence or
        # denominator capability is borrowed from the transcript descriptor.
        claude_hook_safe_event_descriptor = DecoderDescriptor(
            provider=ProviderIdentity(key="claude_code"),
            surface=ProviderSurface.OPERATIONAL_EVENTS,
            adapter_version=CLAUDE_HOOK_ADAPTER_VERSION,
            decoder_key=SAFE_EVENT_EVIDENCE_DECODER_KEY,
            decoder_version=SAFE_EVENT_EVIDENCE_DECODER_CURRENT_VERSION,
            wire_schema_family="claude-code.hooks.v1.safe-events",
            canonical_schema_version=CLAUDE_HOOK_SOURCE_SCHEMA_VERSION,
            schema_artifact=SchemaArtifactProvenance(
                artifact_key="claude-code.hook-safe-event-index",
                artifact_version="1",
                kind=SchemaArtifactKind.DOCUMENTED,
            ),
            capabilities=(CapabilityKey.TOOL_EVENTS,),
        )

        return SafeEventTypedEvidenceProjector(
            self.database,
            LocalArtifactIdFactory(self.pseudonymizer),
            safe_event_descriptor,
            tasks=self.database.task_repository(),
            descriptors={Provider.CLAUDE_CODE: claude_safe_event_descriptor},
            source_descriptors={
                (
                    Provider.CODEX,
                    CODEX_ADAPTER_VERSION,
                    CODEX_SOURCE_SCHEMA_VERSION,
                ): safe_event_descriptor,
                (
                    Provider.CLAUDE_CODE,
                    TRANSCRIPT_ADAPTER_VERSION,
                    TRANSCRIPT_SOURCE_SCHEMA_VERSION,
                ): claude_safe_event_descriptor,
                (
                    Provider.CLAUDE_CODE,
                    CLAUDE_HOOK_ADAPTER_VERSION,
                    CLAUDE_HOOK_SOURCE_SCHEMA_VERSION,
                ): claude_hook_safe_event_descriptor,
            },
        )

    def create_declared_task_profile_service(self):
        """Construct authenticated, content-free per-session profile revisions."""

        from .application.analysis.declared_task_profiles import (
            DeclaredTaskProfileService,
        )
        from .infrastructure.identifiers import LocalArtifactIdFactory

        return DeclaredTaskProfileService(
            self.database.declared_task_profile_repository(),
            LocalArtifactIdFactory(self.pseudonymizer),
        )

    def create_requirement_plan_evidence_service(self, review_contexts=None):
        """Construct inert import plus native-confirmed decomposition evidence."""

        from .application.analysis.requirement_plan_evidence import (
            InMemoryRequirementPlanReviewContextStore,
            RequirementPlanEvidenceService,
            SealedRunRequirementPlanSource,
        )
        from .infrastructure.identifiers import LocalArtifactIdFactory

        models = self.database.model_ensemble_repository()
        contexts = (
            InMemoryRequirementPlanReviewContextStore()
            if review_contexts is None
            else review_contexts
        )
        return RequirementPlanEvidenceService(
            self.database.requirement_plan_evidence_repository(),
            SealedRunRequirementPlanSource(models, contexts),
            LocalArtifactIdFactory(self.pseudonymizer),
            review_contexts=contexts,
        )

    def create_requirement_action_evidence_service(self, review_contexts=None):
        """Construct inert import plus native-reviewed action-link evidence."""

        from .application.analysis.requirement_action_evidence import (
            InMemoryRequirementActionReviewContextStore,
            RequirementActionEvidenceService,
            SealedRunRequirementActionSource,
        )
        from .infrastructure.identifiers import LocalArtifactIdFactory

        models = self.database.model_ensemble_repository()
        contexts = (
            InMemoryRequirementActionReviewContextStore()
            if review_contexts is None
            else review_contexts
        )
        return RequirementActionEvidenceService(
            self.database.requirement_action_evidence_repository(),
            SealedRunRequirementActionSource(models, contexts),
            LocalArtifactIdFactory(self.pseudonymizer),
            review_contexts=contexts,
        )

    def create_requirement_verification_evidence_service(self):
        """Construct restart-safe, content-free verification evidence authority."""

        from .application.analysis.requirement_verification_persistence import (
            RequirementVerificationEvidenceService,
        )
        from .infrastructure.identifiers import LocalArtifactIdFactory

        return RequirementVerificationEvidenceService(
            self.database.requirement_verification_evidence_repository(),
            self.database.requirement_verification_current_plan_authority(),
            LocalArtifactIdFactory(self.pseudonymizer),
        )

    def create_session_model_ensemble_service(
        self,
        compatibility_policy: ProviderSurfaceCompatibilityPolicy,
        requirement_plan_review_contexts=None,
        requirement_action_review_contexts=None,
    ) -> SessionModelEnsembleService:
        """Compose the serial, process-isolated all-metric live pipeline."""

        from .application.analysis import SessionModelEnsembleService
        from .application.analysis.semantic_units import SemanticUnitReconciler
        from .infrastructure.identifiers import LocalArtifactIdFactory
        from .infrastructure.text_models.probabilistic_metrics import (
            LocalProbabilisticMetricRunner,
        )

        source_factory = self.create_text_analysis_source

        return SessionModelEnsembleService(
            self.database,
            self.database.model_ensemble_repository(),
            source_factory,
            compatibility_policy,
            LocalArtifactIdFactory(self.pseudonymizer),
            LocalProbabilisticMetricRunner(),
            typed_evidence_projector=self.create_typed_evidence_projector(),
            semantic_unit_reconciler=SemanticUnitReconciler(
                LocalArtifactIdFactory(self.pseudonymizer),
            ),
            lifecycle_evidence_reader=(
                self.database.metric_lifecycle_evidence_repository()
            ),
            declared_task_profile_reader=(
                self.database.declared_task_profile_repository()
            ),
            requirement_plan_evidence_reader=(
                self.database.requirement_plan_evidence_repository()
            ),
            requirement_plan_review_contexts=requirement_plan_review_contexts,
            requirement_action_evidence_reader=(
                self.database.requirement_action_evidence_repository()
            ),
            requirement_action_review_contexts=(
                requirement_action_review_contexts
            ),
            requirement_verification_reader=(
                self.database.requirement_verification_evidence_repository()
            ),
        )

    def create_project_quality_aggregation_service(
        self,
    ) -> ProjectQualityAggregationService:
        """Compose indexed-project resolution with immutable session aggregation."""

        from .application.analysis import (
            FingerprintedSessionQualityAggregator,
            ProjectQualityAggregationService,
            SessionQualityAggregationService,
        )
        from .application.analysis.coaching_baselines import (
            COACHING_METRIC_DEFINITIONS,
            COACHING_METRIC_PACK_KEY,
            COACHING_METRIC_PACK_VERSION,
        )
        from .application.analysis.text_analysis_presets import COACHING_PROFILE_V1

        def session_quality_factory(repository):
            return FingerprintedSessionQualityAggregator(
                SessionQualityAggregationService(
                    repository,
                    definitions=COACHING_METRIC_DEFINITIONS,
                    analysis_profile_key=COACHING_PROFILE_V1.analysis_profile_key,
                    analysis_profile_version=(
                        COACHING_PROFILE_V1.analysis_profile_version
                    ),
                    metric_pack_key=COACHING_METRIC_PACK_KEY,
                    metric_pack_version=COACHING_METRIC_PACK_VERSION,
                )
            )

        return ProjectQualityAggregationService(
            self.database,
            session_quality_factory,
        )

    def create_analysis_job_service(self) -> AnalysisJobService:
        """Compose the durable content-free queue without enabling a runner."""

        from .application.jobs import AnalysisJobService

        return AnalysisJobService(self.database.analysis_job_repository())

    def create_automation_runtime(
        self,
        *,
        codex_source_service: CodexLocalSourceService,
        session_text_analysis_service: SessionTextAnalysisService,
        analysis_job_service: AnalysisJobService,
        claude_source_service=None,
    ) -> tuple[
        AutomationGrantService,
        AutomationGrantWorker,
        AnalysisJobWorker,
    ]:
        """Compose the local-only scheduler and its single reviewed worker."""

        from datetime import UTC, datetime, timedelta

        from .application.analysis.coaching_baselines import (
            COACHING_METRIC_ENGINE_VERSION,
            COACHING_METRIC_PACK_VERSION,
            COACHING_METRIC_RUBRIC_VERSION,
        )
        from .application.automation import (
            AutomationGrantService,
            AutomationGrantWorker,
            AutomationJobGuard,
            SessionQualityAutomationHandler,
        )
        from .application.jobs import (
            AnalysisJobKind,
            AnalysisJobWorker,
        )
        from .domain import Provider
        from .infrastructure.automation import (
            LocalAutomationAccessPolicy,
            LocalAutomationCatalogRefresher,
            LocalAutomationIdFactory,
            QueueAutomationJobSink,
        )
        from .infrastructure.power import LocalPowerSourceReader
        from .infrastructure.redaction.deterministic import (
            DETERMINISTIC_REDACTOR_VERSION,
        )

        estimator_plan_version = (
            f"coaching-v{COACHING_METRIC_PACK_VERSION}-"
            f"{COACHING_METRIC_ENGINE_VERSION}-"
            f"{COACHING_METRIC_RUBRIC_VERSION}"
        )
        clock = lambda: datetime.now(UTC)
        power_source = LocalPowerSourceReader()
        access = LocalAutomationAccessPolicy(self.database)
        candidates = self.database.automation_candidate_source(
            estimator_plan_version=estimator_plan_version,
            redactor_version=DETERMINISTIC_REDACTOR_VERSION,
        )
        grants = self.database.automation_grant_repository()
        grant_service = AutomationGrantService(
            grants,
            access,
            LocalAutomationCatalogRefresher(
                {
                    Provider.CODEX: codex_source_service,
                    **(
                        {Provider.CLAUDE_CODE: claude_source_service}
                        if claude_source_service is not None
                        else {}
                    ),
                }
            ),
            candidates,
            QueueAutomationJobSink(
                analysis_job_service,
                estimator_plan_version=estimator_plan_version,
                redactor_version=DETERMINISTIC_REDACTOR_VERSION,
            ),
            LocalAutomationIdFactory(),
            power_source,
            clock=clock,
        )
        guard = AutomationJobGuard(
            grants,
            access,
            candidates,
            clock=clock,
        )
        job_worker = AnalysisJobWorker(
            self.database.analysis_job_repository(),
            {
                (AnalysisJobKind.SESSION_QUALITY, provider): (
                    SessionQualityAutomationHandler(
                        session_text_analysis_service
                    )
                )
                for provider in (Provider.CODEX, Provider.CLAUDE_CODE)
            },
            authorization_check=guard.authorized,
            fingerprint_resolver=guard.fingerprints,
            power_source=power_source,
            clock=clock,
            lease_duration=timedelta(minutes=5),
        )
        return grant_service, AutomationGrantWorker(grant_service), job_worker

    def create_control_plane(self) -> DevelopmentControlPlane:
        """Compose the in-memory development control plane and its resolver.

        The composed plane starts with no organizations, no credentials, and no
        entitlement, so enabling the setting exposes routes that authenticate
        nobody and authorize nothing until a tenant is provisioned deliberately
        and in process. Nothing here reads the analyzer database, provider
        sessions, or local files, and nothing it holds survives a restart.
        """

        from datetime import UTC, datetime

        from .infrastructure.control_plane import create_development_control_plane

        return create_development_control_plane(lambda: datetime.now(UTC))

    def create_http_app(
        self,
        *,
        user_presence_confirmation=None,
        user_presence_confirmation_mode=None,
        desktop_owned_readiness_path=None,
        workspace_folder_picker=None,
    ) -> FastAPI:
        """Construct the authenticated HTTP adapter without exposing its token."""

        from .api import create_app
        from .application.providers import (
            CapabilityKey,
            ProviderSurface,
            ProviderSurfaceCompatibilityPolicy,
        )
        from .domain import Provider
        from .infrastructure.text_models.jobs import LocalTextModelEvaluationService
        from .application.resources import ResourceAvailability, ResourceKind
        from .infrastructure.resources import default_packaged_resource_resolver
        from .infrastructure.paths import LocalPrivatePathHardener
        from .infrastructure.updates import (
            compose_packaged_application_update_surface,
        )
        from .application.workspace_folder_picker import (
            create_default_workspace_folder_picker,
        )

        token = load_or_create_api_token(self.settings.api_token_path)
        dashboard_resource = default_packaged_resource_resolver().resolve(
            ResourceKind.DASHBOARD_STATIC
        )
        application_update_path_hardener = LocalPrivatePathHardener()
        application_update_service = compose_packaged_application_update_surface(
            resolver=default_packaged_resource_resolver(),
            installed_version=__version__,
            staging_root=self.settings.application_update_staging_dir,
            private_path_hardener=application_update_path_hardener,
            private_update_staging_root_preparer=application_update_path_hardener,
        )
        static_directory = (
            dashboard_resource.path
            if dashboard_resource.availability is ResourceAvailability.AVAILABLE
            else None
        )
        compatibility_catalog = self.create_provider_compatibility_catalog()
        # This invokes only the documented schema generator in an isolated
        # empty provider home. It never lists or reads provider sessions.
        compatibility_catalog.refresh("codex", ProviderSurface.TEXT_WINDOW)
        # Structure-only sample of the owner's transcript root (type keys, no
        # content); the text window is simply unavailable when it fails.
        try:
            compatibility_catalog.refresh("claude_code", ProviderSurface.TEXT_WINDOW)
        except Exception:
            pass
        compatibility_policy = ProviderSurfaceCompatibilityPolicy(
            compatibility_catalog,
            surface=ProviderSurface.TEXT_WINDOW,
            required_capabilities=(
                CapabilityKey.USER_MESSAGES,
                CapabilityKey.AGENT_MESSAGES,
                CapabilityKey.PLAN_MESSAGES,
            ),
        )
        codex_source_service = self.create_codex_local_source_service()
        session_text_analysis_service = self.create_session_text_analysis_service(
            compatibility_policy
        )
        metric_readiness_service = self.create_metric_readiness_service(
            compatibility_catalog
        )
        metric_coverage_service = self.create_metric_coverage_service(
            metric_readiness_service
        )
        from .application.analysis.requirement_plan_evidence import (
            InMemoryRequirementPlanReviewContextStore,
        )
        from .application.analysis.requirement_action_evidence import (
            InMemoryRequirementActionReviewContextStore,
        )

        requirement_plan_review_contexts = (
            InMemoryRequirementPlanReviewContextStore()
        )
        requirement_action_review_contexts = (
            InMemoryRequirementActionReviewContextStore()
        )
        session_model_ensemble_service = self.create_session_model_ensemble_service(
            compatibility_policy,
            requirement_plan_review_contexts,
            requirement_action_review_contexts,
        )
        metric_lifecycle_evidence_service = (
            self.create_metric_lifecycle_evidence_service()
        )
        from .application.analysis.agent_metric_evidence import (
            AgentMetricEvidenceService,
            SealedRunAgentMetricEvidenceSource,
        )

        agent_metric_evidence_service = AgentMetricEvidenceService(
            metric_lifecycle_evidence_service,
            SealedRunAgentMetricEvidenceSource(
                self.database.model_ensemble_repository()
            ),
        )
        declared_task_profile_service = self.create_declared_task_profile_service()
        requirement_plan_evidence_service = (
            self.create_requirement_plan_evidence_service(
                requirement_plan_review_contexts
            )
        )
        requirement_verification_evidence_service = (
            self.create_requirement_verification_evidence_service()
        )
        requirement_action_evidence_service = (
            self.create_requirement_action_evidence_service(
                requirement_action_review_contexts
            )
        )
        from .application.analysis.model_ensemble_watch import (
            ModelEnsembleWatchService,
            ModelEnsembleWatchWorker,
        )

        model_ensemble_watch_service = ModelEnsembleWatchService(
            self.database.model_ensemble_watch_repository(),
            session_model_ensemble_service,
        )
        model_ensemble_watch_worker = ModelEnsembleWatchWorker(
            model_ensemble_watch_service
        )
        analysis_job_service = self.create_analysis_job_service()
        claude_source_service = self.create_claude_local_source_service()
        (
            automation_grant_service,
            automation_grant_worker,
            analysis_job_worker,
        ) = self.create_automation_runtime(
            codex_source_service=codex_source_service,
            session_text_analysis_service=session_text_analysis_service,
            analysis_job_service=analysis_job_service,
            claude_source_service=claude_source_service,
        )
        def revoke_local_workers(provider: Provider) -> int:
            return (
                automation_grant_service.revoke_provider(provider)
                + model_ensemble_watch_service.quarantine_for_provider(provider)
            )

        codex_source_service.set_automation_revoker(revoke_local_workers)
        claude_source_service.set_automation_revoker(revoke_local_workers)
        otlp_ingest_token = load_or_create_api_token(self.settings.otlp_ingest_token_path)
        telemetry_ingest_service = self.database.claude_telemetry_ingest(self.pseudonymizer)
        def enable_automation(provider: Provider) -> int:
            return automation_grant_service.ensure_default_grants(
                provider, self.database.list_project_ids(provider)
            )

        local_model_service = self.create_local_model_service()
        calibration_rating_service = self.create_calibration_rating_service()
        model_judge_service, _ = self.create_model_judge_service(local_model_service, calibration_rating_service)
        prompt_check_service = self.create_prompt_check_service(local_model_service)
        agent_mcp_connection_service = (
            self.create_agent_mcp_connection_service(token)
        )
        mcp_registry_catalog_service = self.create_mcp_registry_catalog_service()
        from .infrastructure.mcp_guarded_host import OfficialSdkMcpConnectionFactory

        mcp_connection_factory = OfficialSdkMcpConnectionFactory()
        mcp_server_management_service = (
            self.create_mcp_server_management_service(
                mcp_registry_catalog_service,
                connection_factory=mcp_connection_factory,
            )
        )
        mcp_managed_runtime_service = self.create_mcp_managed_runtime_service(
            mcp_server_management_service,
            connection_factory=mcp_connection_factory,
        )
        # A consumed one-use approval from an earlier process may never be
        # replayed or shown as a live call.  Settle those content-free claims
        # before any Agent session can acquire this run's MCP runtime.
        mcp_managed_runtime_service.reconcile_after_restart()
        # Inject the boot-owned runtime during construction.  This guarantees
        # that no already-live session can acquire new MCP authority as a side
        # effect of rebuilding an HTTP adapter.
        local_agent_service = self.create_local_agent_service(
            local_model_service,
            mcp_managed_runtime_service=mcp_managed_runtime_service,
        )
        if workspace_folder_picker is None:
            workspace_folder_picker = create_default_workspace_folder_picker()
        # Catalog ownership describes a process-bound controller.  On a new
        # composition, only sessions actually present in the boot-owned local
        # service may retain live authority; all other rows become uncertainty
        # evidence with native approvals and handoffs cleared.
        agent_mcp_connection_service.ownership.reconcile_after_restart(
            live_session_ids=tuple(
                session.session_id for session in local_agent_service.list()
            ),
        )
        agent_hardening_service = self.create_agent_hardening_service(
            local_agent_service
        )
        annotation_service, central_annotation_server, remote_annotation_client = self.create_annotation_services(local_model_service, model_judge_service)
        shared_folder_service, peer_folder_client = self.create_shared_folder_services()

        def judge_new_sessions(provider: Provider) -> None:
            # Judge the newest indexed sessions with the active local model, one
            # at a time in the judge's own thread; already-judged sessions are
            # skipped, and with no active model nothing happens.
            rows = self.database.list_sessions(limit=200, offset=0, provider=provider)
            model_judge_service.start_sweep(tuple(str(row["session_id"]) for row in rows))

        def every_session_id() -> tuple[str, ...]:
            # Newest first, bounded: the sweep itself skips sessions the active model judged before.
            ids: list[str] = []
            offset = 0
            while len(ids) < 5000:
                rows = self.database.list_sessions(limit=500, offset=offset)
                if not rows:
                    break
                ids.extend(str(row["session_id"]) for row in rows)
                offset += len(rows)
                if len(rows) < 500:
                    break
            return tuple(ids)

        onboarding_service = self.create_onboarding_service(
            codex_source_service, claude_source_service, enable_automation=enable_automation, after_index=judge_new_sessions
        )
        from .application.onboarding import LocalSourceRefreshWorker

        local_source_refresh_worker = LocalSourceRefreshWorker(onboarding_service)
        control_plane = (
            self.create_control_plane()
            if self.settings.control_plane_development_api
            else None
        )
        return create_app(
            settings=self.settings,
            database=self.database,
            api_token=token,
            task_review_service=self.create_task_review_service(),
            task_lifecycle_service=self.create_task_lifecycle_service(),
            metric_lifecycle_evidence_service=(
                metric_lifecycle_evidence_service
            ),
            agent_metric_evidence_service=agent_metric_evidence_service,
            declared_task_profile_service=declared_task_profile_service,
            requirement_plan_evidence_service=requirement_plan_evidence_service,
            requirement_action_evidence_service=(
                requirement_action_evidence_service
            ),
            requirement_verification_evidence_service=(
                requirement_verification_evidence_service
            ),
            task_analysis_service=self.create_task_analysis_service(),
            session_text_analysis_service=session_text_analysis_service,
            session_model_link_experiment_service=(
                self.create_session_model_link_experiment_service(
                    compatibility_policy
                )
            ),
            session_model_ensemble_service=session_model_ensemble_service,
            model_ensemble_watch_service=model_ensemble_watch_service,
            model_ensemble_watch_worker=model_ensemble_watch_worker,
            project_quality_aggregation_service=(
                self.create_project_quality_aggregation_service()
            ),
            provider_compatibility_catalog=compatibility_catalog,
            metric_readiness_service=metric_readiness_service,
            metric_coverage_service=metric_coverage_service,
            codex_source_service=codex_source_service,
            claude_source_service=claude_source_service,
            otlp_ingest_token=otlp_ingest_token,
            telemetry_ingest_service=telemetry_ingest_service,
            session_reader_service=self.create_session_reader_service(),
            calibration_rating_service=calibration_rating_service,
            local_model_service=local_model_service,
            model_judge_service=model_judge_service,
            prompt_check_service=prompt_check_service,
            local_agent_service=local_agent_service,
            workspace_folder_picker=workspace_folder_picker,
            application_update_service=application_update_service,
            agent_hardening_service=agent_hardening_service,
            agent_mcp_connection_service=agent_mcp_connection_service,
            mcp_registry_catalog_service=mcp_registry_catalog_service,
            mcp_server_management_service=mcp_server_management_service,
            mcp_managed_runtime_service=mcp_managed_runtime_service,
            annotation_service=annotation_service,
            central_annotation_server=central_annotation_server,
            remote_annotation_client=remote_annotation_client,
            shared_folder_service=shared_folder_service,
            peer_folder_client=peer_folder_client,
            calibration_sample_session_ids=lambda: tuple(m.session_id for m in calibration_rating_service.sample().members),
            all_session_ids=every_session_id,
            objective_overrides_provider=self.create_objective_overrides_provider(),
            onboarding_service=onboarding_service,
            local_source_refresh_worker=local_source_refresh_worker,
            display_label_service=self.create_manual_display_label_service(),
            model_evaluation_service=LocalTextModelEvaluationService(),
            analysis_job_service=analysis_job_service,
            analysis_job_worker=analysis_job_worker,
            automation_grant_service=automation_grant_service,
            automation_grant_worker=automation_grant_worker,
            control_plane_service=(
                None if control_plane is None else control_plane.service
            ),
            control_plane_principal_resolver=(
                None if control_plane is None else control_plane.resolver
            ),
            estimator_repository=self.database.estimator_repository(),
            static_directory=static_directory,
            user_presence_confirmation=user_presence_confirmation,
            user_presence_confirmation_mode=user_presence_confirmation_mode,
            desktop_owned_readiness_path=desktop_owned_readiness_path,
        )


def bootstrap_local_application(settings: AppSettings) -> LocalApplication:
    """Build the local modular monolith and enforce private-state prerequisites."""

    prepare_app_home(settings)
    pseudonymizer = load_or_create_pseudonymizer(settings.pseudonym_key_path)
    from .infrastructure.identifiers import LocalArtifactIdFactory

    database = Database(settings.database_path)
    database.configure_local_artifact_id_factory(
        LocalArtifactIdFactory(pseudonymizer)
    )
    database.initialize()

    # Initialization promises that every CLI command leaves a complete local
    # installation. Discard the value so it cannot leak through the composition
    # root or an object's repr.
    load_or_create_api_token(settings.api_token_path)

    return LocalApplication(
        settings=settings,
        database=database,
        pseudonymizer=pseudonymizer,
    )
