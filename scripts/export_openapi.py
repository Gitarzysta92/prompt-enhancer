"""Export the dashboard contract at build time; runtime docs stay disabled."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_ROOT = _REPOSITORY_ROOT / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from prompt_enhancer.api import create_app
from prompt_enhancer.application.analysis import (
    MetricCoverageReport,
    MetricCoverageSelection,
    ModelExperimentDevice,
    ModelLinkAnnotationLabel,
    SessionTextAnalysisOutcome,
    TaskAnalysisOutcome,
    TextAnalysisPresetId,
)
from prompt_enhancer.application.analysis.redaction_preview import (
    AnalysisApproval,
    RedactionPreviewInspection,
)
from prompt_enhancer.application.discovery import TaskDecisionCommand, TaskReviewResult
from prompt_enhancer.application.local_sources import (
    ClaudeCodeLocalSourceStatus,
    CodexLocalSourceStatus,
)
from prompt_enhancer.application.persistence import AnalysisRunStatus
from prompt_enhancer.config import AppSettings
from prompt_enhancer.domain import Provider
from prompt_enhancer.ingestion import IngestionReport
from prompt_enhancer.infrastructure.text_models.jobs import LocalTextModelEvaluationService


class _SchemaStore:
    """Content-free stand-in used only while FastAPI builds route schemas."""

    def initialize(self) -> None:
        return None

    def list_metric_definitions(self) -> list[dict[str, object]]:
        return []

    def list_sessions(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        provider: Provider | None = None,
    ) -> list[dict[str, object]]:
        return []

    def get_session_metrics(self, session_id: str) -> list[dict[str, object]]:
        return []


class _SchemaReviewService:
    def apply(
        self,
        command: TaskDecisionCommand,
        *,
        idempotency_key: str,
    ) -> TaskReviewResult:
        raise RuntimeError("schema-only service cannot execute commands")


class _SchemaTaskLifecycleService:
    """Non-executing stand-in that enables explicit lifecycle route schemas."""

    pass


class _SchemaAnalysisService:
    def run(
        self,
        task_id: str,
        task_revision: int,
        *,
        idempotency_key: str,
    ) -> TaskAnalysisOutcome:
        return TaskAnalysisOutcome(
            run_id="0" * 64,
            status=AnalysisRunStatus.COMPLETED,
            result_count=0,
            applied=False,
        )


class _SchemaSessionTextAnalysisService:
    def prepare_preset_preview(
        self,
        *,
        provider: Provider,
        session_id: str,
        preset_id: TextAnalysisPresetId,
    ) -> RedactionPreviewInspection:
        raise RuntimeError("schema-only service cannot access session text")

    def approve_preview(
        self,
        approval: AnalysisApproval,
    ) -> SessionTextAnalysisOutcome:
        raise RuntimeError("schema-only service cannot access session text")

    def run_preset(
        self,
        *,
        provider: Provider,
        session_id: str,
        preset_id: TextAnalysisPresetId,
        confirmation: str,
        idempotency_key: str,
    ) -> SessionTextAnalysisOutcome:
        raise RuntimeError("schema-only service cannot access session text")


class _SchemaModelLinkExperimentService:
    def run(
        self,
        *,
        provider: Provider,
        session_id: str,
        confirmation: str,
        device: ModelExperimentDevice,
        idempotency_key: str,
    ) -> object:
        raise RuntimeError("schema-only service cannot access session text")

    def latest(self, session_id: str) -> object:
        raise RuntimeError("schema-only service cannot access local experiments")

    def annotate(
        self,
        *,
        run_id: str,
        link_id: str,
        label: ModelLinkAnnotationLabel,
        expected_revision: int,
    ) -> object:
        raise RuntimeError("schema-only service cannot change annotations")


class _SchemaModelEnsembleService:
    def run(
        self,
        *,
        provider: Provider,
        session_id: str,
        confirmation: str,
        idempotency_key: str,
    ) -> object:
        raise RuntimeError("schema-only service cannot access session text")

    def latest(self, session_id: str) -> object:
        raise RuntimeError("schema-only service cannot access model ensembles")


class _SchemaModelEnsembleWatchService:
    def enable(self, **_kwargs: object) -> object:
        raise RuntimeError("schema-only service cannot enable model watches")

    def disable(self, _watch_id: str) -> object:
        raise RuntimeError("schema-only service cannot disable model watches")

    def get_active(self) -> object:
        raise RuntimeError("schema-only service cannot inspect model watches")


class _SchemaProjectQualityAggregationService:
    """Non-executing stand-in that only enables the project aggregate schema."""

    def aggregate(self, selection: object) -> object:
        raise RuntimeError("schema-only service cannot resolve indexed projects")


class _SchemaProviderCompatibilityCatalog:
    """Non-executing stand-in that exposes compatibility route signatures."""

    def descriptor(self, provider: str, surface: object) -> object:
        raise RuntimeError("schema-only service cannot inspect providers")

    def get_cached(self, provider: str, surface: object) -> object:
        raise RuntimeError("schema-only service cannot inspect providers")

    def refresh(self, provider: str, surface: object) -> object:
        raise RuntimeError("schema-only service cannot inspect providers")


class _SchemaMetricReadinessService:
    """Non-executing stand-in that exposes readiness response schemas."""

    def provider_capabilities(self, provider: Provider) -> object:
        raise RuntimeError("schema-only service cannot inspect providers")

    def session_readiness(
        self,
        session_id: str,
        *,
        preset_id: TextAnalysisPresetId,
    ) -> object:
        raise RuntimeError("schema-only service cannot inspect sessions")


class _SchemaMetricLifecycleEvidenceService:
    """Non-executing stand-in exposing typed lifecycle evidence routes."""

    pass


class _SchemaAnalysisJobService:
    """Non-executing stand-in that exposes durable job route signatures."""

    pass


class _SchemaAutomationGrantService:
    """Non-executing stand-in that exposes automation route signatures."""

    pass


class _SchemaEstimatorRepository:
    """Non-executing stand-in exposing the read-only Model Lab route."""

    pass


class _SchemaControlPlaneService:
    """Non-executing stand-in for the optional development control plane."""

    pass


class _SchemaControlPlanePrincipalResolver:
    """Non-executing stand-in that only enables dependency schema generation."""

    pass


class _SchemaClaudeSourceService:
    """Non-executing stand-in exposing the hook-captured source route signatures."""

    def status(self) -> ClaudeCodeLocalSourceStatus:
        raise RuntimeError("schema-only service cannot access local sources")

    def grant_local_history(self) -> ClaudeCodeLocalSourceStatus:
        raise RuntimeError("schema-only service cannot change consent")

    def revoke_local_history(self) -> ClaudeCodeLocalSourceStatus:
        raise RuntimeError("schema-only service cannot change consent")

    def index(self, *, max_sessions: int) -> IngestionReport:
        raise RuntimeError("schema-only service cannot access local sources")


class _SchemaOnboardingService:
    """Non-executing stand-in so the first-run routes are typed."""

    def status(self):
        raise RuntimeError("schema-only service cannot detect providers")

    def accept(self, payload):
        raise RuntimeError("schema-only service cannot grant consent")

    def refresh(self):
        raise RuntimeError("schema-only service cannot index")


class _SchemaCalibrationRatingService:
    """Non-executing stand-in so the blind calibration routes are typed."""

    def sample(self, *, rater_label=None):
        raise RuntimeError("schema-only service cannot sample sessions")

    def rate(self, submission):
        raise RuntimeError("schema-only service cannot store ratings")

    def ratings_for(self, rater_label):
        raise RuntimeError("schema-only service cannot list ratings")

    def progress(self):
        raise RuntimeError("schema-only service cannot report progress")

    def export(self):
        raise RuntimeError("schema-only service cannot export")


class _SchemaModelJudgeService:
    """Non-executing stand-in so the model-judge routes are typed."""

    def judge(self, session_id):
        raise RuntimeError("schema-only service cannot judge")

    def start_sweep(self, session_ids):
        raise RuntimeError("schema-only service cannot sweep")

    def sweep_status(self):
        raise RuntimeError("schema-only service has no sweep")

    def agreement(self):
        raise RuntimeError("schema-only service has no agreement")


class _SchemaPromptCheckService:
    """Non-executing stand-in so the prompt-check routes are typed."""

    def check(self, request):
        raise RuntimeError("schema-only service cannot check prompts")

    def history(self, *, limit=50, offset=0):
        raise RuntimeError("schema-only service has no history")

    def get(self, check_id):
        raise RuntimeError("schema-only service has no history")


class _SchemaAnnotationSurface:
    """Non-executing stand-in so the annotation + central routes are typed (ADR 0017)."""

    def __getattr__(self, name):
        def _fail(*args, **kwargs):
            raise RuntimeError("schema-only service")

        return _fail


class _SchemaLocalAgentService:
    """Non-executing stand-in so the local-agent routes are typed."""

    def list(self):
        raise RuntimeError("schema-only service")

    def create(self, settings):
        raise RuntimeError("schema-only service")

    def get(self, session_id):
        raise RuntimeError("schema-only service")

    def delete(self, session_id):
        raise RuntimeError("schema-only service")

    def send(self, session_id, message):
        raise RuntimeError("schema-only service")

    def events(self, session_id, after=0):
        raise RuntimeError("schema-only service")

    def approve(self, session_id, approval_id, decision):
        raise RuntimeError("schema-only service")

    def stop(self, session_id):
        raise RuntimeError("schema-only service")


class _SchemaLocalModelService:
    """Non-executing stand-in so the local model routes are typed."""

    def overview(self):
        raise RuntimeError("schema-only service cannot list models")

    def add(self, payload):
        raise RuntimeError("schema-only service cannot add models")

    def remote_files(self, repo_id):
        raise RuntimeError("schema-only service cannot query the hub")

    def start_download(self, payload):
        raise RuntimeError("schema-only service cannot download")

    def status(self, alias):
        raise RuntimeError("schema-only service has no runtimes")

    def remove(self, alias, *, delete_weights=False):
        raise RuntimeError("schema-only service cannot remove models")

    def activate(self, alias, payload=None):
        raise RuntimeError("schema-only service cannot activate models")

    def deactivate(self, alias):
        raise RuntimeError("schema-only service cannot deactivate models")

    def chat(self, alias, body):
        raise RuntimeError("schema-only service cannot chat")

    def shutdown(self):
        return None


class _SchemaSessionReaderService:
    """Non-executing stand-in so the owner-authorized reader route is typed."""

    enabled = True

    def read(self, session_id: str):
        raise RuntimeError("schema-only service cannot read sessions")


class _SchemaCodexSourceService:
    """Non-executing stand-in that exposes only local-source route signatures."""

    def status(self) -> CodexLocalSourceStatus:
        raise RuntimeError("schema-only service cannot access local sources")

    def grant_local_history(self) -> CodexLocalSourceStatus:
        raise RuntimeError("schema-only service cannot change consent")

    def revoke_local_history(self) -> CodexLocalSourceStatus:
        raise RuntimeError("schema-only service cannot change consent")

    def index(self, *, max_sessions: int) -> IngestionReport:
        raise RuntimeError("schema-only service cannot access local sources")

    def analyze(
        self,
        *,
        project_ids: frozenset[str],
        session_ids: frozenset[str],
        max_sessions: int,
    ) -> IngestionReport:
        raise RuntimeError("schema-only service cannot access local sources")


class _SchemaManualDisplayLabelService:
    """Non-executing stand-in for local override route signatures."""

    pass


class _SchemaMetricCoverageService:
    """Non-executing stand-in for the content-free coverage routes."""

    def report(self, selection: MetricCoverageSelection) -> MetricCoverageReport:
        del selection
        raise RuntimeError("schema-only service cannot query metric coverage")


class _SchemaDeclaredTaskProfileService:
    """Non-executing stand-in for reviewed task-profile route signatures."""

    pass


class _SchemaAgentHardeningService:
    """Non-executing stand-in for content-free Agent diagnostic signatures."""

    pass


class _SchemaAgentMcpConnectionService:
    """Non-executing stand-in for scoped Agent MCP connection signatures."""

    pass


class _SchemaMcpRegistryCatalogService:
    """Non-executing stand-in for read-only public MCP Store signatures."""

    pass


class _SchemaMcpServerManagementService:
    """Non-executing stand-in for durable MCP plan-management signatures."""

    pass


class _SchemaRequirementPlanEvidenceService:
    """Non-executing stand-in for reviewed requirement-plan routes."""

    pass


class _SchemaRequirementActionEvidenceService:
    """Non-executing stand-in for reviewed requirement-action routes."""

    pass


class _SchemaRequirementVerificationEvidenceService:
    """Non-executing stand-in for content-free verification evidence routes."""

    pass


_BROWSER_CONTROL_PLANE_PATH = "/v1/control-plane/readiness"
_COMPONENT_SCHEMA_PREFIX = "#/components/schemas/"


def _collect_schema_references(value: object, references: set[str]) -> None:
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith(
            _COMPONENT_SCHEMA_PREFIX
        ):
            references.add(reference.removeprefix(_COMPONENT_SCHEMA_PREFIX))
        for child in value.values():
            _collect_schema_references(child, references)
    elif isinstance(value, list):
        for child in value:
            _collect_schema_references(child, references)


def _add_browser_safe_control_plane_surface(
    schema: dict[str, Any],
    composed_schema: dict[str, Any],
) -> dict[str, Any]:
    """Export readiness without generating privileged browser clients."""

    paths = schema.get("paths")
    composed_paths = composed_schema.get("paths")
    if not isinstance(paths, dict) or not isinstance(composed_paths, dict):
        raise RuntimeError("OpenAPI paths are unavailable")
    readiness_path = composed_paths.get(_BROWSER_CONTROL_PLANE_PATH)
    if readiness_path is None:
        raise RuntimeError("composed control-plane readiness route is unavailable")
    paths[_BROWSER_CONTROL_PLANE_PATH] = readiness_path

    components = schema.get("components")
    composed_components = composed_schema.get("components")
    if not isinstance(components, dict) or not isinstance(composed_components, dict):
        raise RuntimeError("OpenAPI components are unavailable")
    definitions = components.get("schemas")
    composed_definitions = composed_components.get("schemas")
    if not isinstance(definitions, dict) or not isinstance(composed_definitions, dict):
        raise RuntimeError("OpenAPI schema definitions are unavailable")

    references: set[str] = set()
    _collect_schema_references(readiness_path, references)
    pending = list(references)
    while pending:
        name = pending.pop()
        definition = definitions.get(name, composed_definitions.get(name))
        if definition is None:
            raise RuntimeError(f"OpenAPI schema reference is unavailable: {name}")
        if name not in definitions:
            definitions[name] = definition
        before = set(references)
        _collect_schema_references(definition, references)
        pending.extend(references - before)
    return schema


def _build_schema_app(*, include_control_plane: bool):
    return create_app(
        settings=AppSettings(
            home=Path("example-state"),
            control_plane_development_api=include_control_plane,
        ),
        database=_SchemaStore(),
        api_token="example_schema_token_do_not_use_123456789",
        task_review_service=_SchemaReviewService(),
        task_lifecycle_service=_SchemaTaskLifecycleService(),  # type: ignore[arg-type]
        task_analysis_service=_SchemaAnalysisService(),
        session_text_analysis_service=_SchemaSessionTextAnalysisService(),
        session_model_link_experiment_service=_SchemaModelLinkExperimentService(),  # type: ignore[arg-type]
        session_model_ensemble_service=_SchemaModelEnsembleService(),  # type: ignore[arg-type]
        model_ensemble_watch_service=_SchemaModelEnsembleWatchService(),  # type: ignore[arg-type]
        project_quality_aggregation_service=_SchemaProjectQualityAggregationService(),  # type: ignore[arg-type]
        provider_compatibility_catalog=_SchemaProviderCompatibilityCatalog(),  # type: ignore[arg-type]
        metric_readiness_service=_SchemaMetricReadinessService(),  # type: ignore[arg-type]
        metric_lifecycle_evidence_service=_SchemaMetricLifecycleEvidenceService(),  # type: ignore[arg-type]
        metric_coverage_service=_SchemaMetricCoverageService(),  # type: ignore[arg-type]
        analysis_job_service=_SchemaAnalysisJobService(),  # type: ignore[arg-type]
        automation_grant_service=_SchemaAutomationGrantService(),  # type: ignore[arg-type]
        estimator_repository=_SchemaEstimatorRepository(),  # type: ignore[arg-type]
        control_plane_service=(
            _SchemaControlPlaneService() if include_control_plane else None
        ),  # type: ignore[arg-type]
        control_plane_principal_resolver=(
            _SchemaControlPlanePrincipalResolver()
            if include_control_plane
            else None
        ),  # type: ignore[arg-type]
        codex_source_service=_SchemaCodexSourceService(),
        claude_source_service=_SchemaClaudeSourceService(),  # type: ignore[arg-type]
        session_reader_service=_SchemaSessionReaderService(),  # type: ignore[arg-type]
        onboarding_service=_SchemaOnboardingService(),  # type: ignore[arg-type]
        calibration_rating_service=_SchemaCalibrationRatingService(),  # type: ignore[arg-type]
        local_model_service=_SchemaLocalModelService(),  # type: ignore[arg-type]
        model_judge_service=_SchemaModelJudgeService(),  # type: ignore[arg-type]
        prompt_check_service=_SchemaPromptCheckService(),  # type: ignore[arg-type]
        local_agent_service=_SchemaLocalAgentService(),  # type: ignore[arg-type]
        agent_hardening_service=_SchemaAgentHardeningService(),  # type: ignore[arg-type]
        agent_mcp_connection_service=_SchemaAgentMcpConnectionService(),  # type: ignore[arg-type]
        mcp_registry_catalog_service=_SchemaMcpRegistryCatalogService(),  # type: ignore[arg-type]
        mcp_server_management_service=_SchemaMcpServerManagementService(),  # type: ignore[arg-type]
        declared_task_profile_service=_SchemaDeclaredTaskProfileService(),  # type: ignore[arg-type]
        requirement_plan_evidence_service=_SchemaRequirementPlanEvidenceService(),  # type: ignore[arg-type]
        requirement_action_evidence_service=_SchemaRequirementActionEvidenceService(),  # type: ignore[arg-type]
        requirement_verification_evidence_service=_SchemaRequirementVerificationEvidenceService(),  # type: ignore[arg-type]
        annotation_service=_SchemaAnnotationSurface(),  # type: ignore[arg-type]
        shared_folder_service=_SchemaAnnotationSurface(),  # type: ignore[arg-type]
        peer_folder_client=_SchemaAnnotationSurface(),  # type: ignore[arg-type]
        central_annotation_server=_SchemaAnnotationSurface(),  # type: ignore[arg-type]
        remote_annotation_client=_SchemaAnnotationSurface(),  # type: ignore[arg-type]
        calibration_sample_session_ids=lambda: (),
        display_label_service=_SchemaManualDisplayLabelService(),
        model_evaluation_service=LocalTextModelEvaluationService(),
    )


def build_openapi_schema() -> dict[str, Any]:
    """Build the complete UI contract without creating local state or secrets."""

    base_schema = _build_schema_app(include_control_plane=False).openapi()
    # Compose the real default-off router to prove readiness exists under the
    # opt-in. Stand-ins never provision a tenant, issue a credential, or run.
    composed_schema = _build_schema_app(include_control_plane=True).openapi()
    return _add_browser_safe_control_plane_surface(base_schema, composed_schema)


def export_openapi(output: Path) -> None:
    """Write one deterministic UTF-8 JSON artifact for frontend code generation."""

    output = output.absolute()
    if output.suffix.casefold() != ".json":
        raise ValueError("OpenAPI output must be a JSON file")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_bytes(
        (json.dumps(build_openapi_schema(), indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
    )
    temporary.replace(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/openapi.json"),
        help="JSON artifact destination (default: docs/openapi.json)",
    )
    arguments = parser.parse_args()
    export_openapi(arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
