"""Authenticated, loopback-only HTTP views over the local metadata store."""

from __future__ import annotations

from contextlib import asynccontextmanager
import hmac
import re
from html.parser import HTMLParser
from pathlib import Path
from threading import Lock
from typing import Annotated, Any, Callable, Literal, Mapping, Protocol, Sequence
from urllib.parse import urlsplit

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Path as PathParameter,
    Query,
    Request,
    Response,
)
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles

from .application.display_labels import ManualDisplayLabelService
from .application.local_sources import (
    ClaudeCodeLocalSourceService,
    CodexLocalSourceService,
)
from .application.analysis.session_text_service import SessionTextAnalysisService
from .application.jobs import AnalysisJobService, AnalysisJobWorker
from .application.automation import AutomationGrantService, AutomationGrantWorker
from .application.analysis.metric_readiness import MetricReadinessService
from .application.analysis.metric_coverage import MetricCoverageService
from .application.analysis.metric_lifecycle_evidence import (
    MetricLifecycleEvidenceService,
)
from .application.analysis.declared_task_profiles import DeclaredTaskProfileService
from .application.analysis.agent_metric_evidence import AgentMetricEvidenceService
from .application.analysis.requirement_plan_evidence import (
    RequirementPlanEvidenceService,
)
from .application.analysis.requirement_action_evidence import (
    RequirementActionEvidenceService,
)
from .application.analysis.requirement_verification_persistence import (
    RequirementVerificationEvidenceService,
)
from .application.estimators import EstimatorRepository
from .application.analysis.model_link_experiments import (
    SessionModelLinkExperimentService,
)
from .application.analysis.session_model_ensemble import (
    SessionModelEnsembleService,
)
from .application.analysis.model_ensemble_watch import (
    ModelEnsembleWatchService,
    ModelEnsembleWatchWorker,
)
from .application.analysis.project_quality_aggregation import (
    ProjectQualityAggregationService,
)
from .application.providers import ProviderCompatibilityCatalog
from .infrastructure.text_models.jobs import LocalTextModelEvaluationService
from .config import (
    AppSettings,
    is_loopback_host,
    lexical_absolute_path,
    path_has_symlink_component,
    prepare_app_home,
)
from .domain import PSEUDONYM_PATTERN, Provider, StrictModel
from .application.control_plane import ControlPlaneService, PrincipalResolver
from .application.paid_product.contracts import ProductReadiness
from .application.social.contracts import SocialReadiness
from .application.social.ports import SocialPrincipalResolver
from .application.social.service import SocialService
from .application.task_lifecycle import TaskLifecycleService
from .application.workspace_folder_picker import LocalWorkspaceFolderPicker
from .application.updates import (
    ApplicationUpdateSurface,
    UnconfiguredApplicationUpdateSurface,
)
from . import __version__
from .interfaces.http import (
    create_agent_metric_evidence_router,
    create_control_plane_router,
    create_session_analysis_command_router,
    create_session_analysis_query_router,
    create_session_quality_aggregation_router,
    create_project_quality_aggregation_router,
    create_provider_compatibility_router,
    create_metric_readiness_router,
    create_metric_lifecycle_evidence_router,
    create_metric_coverage_router,
    create_research_router,
    create_model_link_experiment_router,
    create_model_ensemble_router,
    create_model_ensemble_watch_router,
    create_analysis_job_router,
    create_automation_grant_router,
    create_application_update_router,
    create_estimator_router,
    create_task_query_router,
    create_task_lifecycle_router,
    create_paid_product_readiness_router,
    create_social_mutation_router,
    create_social_readiness_router,
)
from .interfaces.http.declared_task_profile_routes import (
    create_declared_task_profile_router,
)
from .interfaces.http.requirement_plan_evidence_routes import (
    create_requirement_plan_evidence_router,
)
from .interfaces.http.requirement_action_evidence_routes import (
    create_requirement_action_evidence_router,
)
from .interfaces.http.requirement_verification_evidence_routes import (
    create_requirement_verification_evidence_router,
)
from .interfaces.http.browser_session import (
    BROWSER_SESSION_COOKIE,
    CSRF_HEADER,
    BrowserSessionManager,
)
from .interfaces.http.user_presence import USER_PRESENCE_HEADER
from .interfaces.http.desktop_identity import (
    DESKTOP_CHALLENGE_HEADER,
    DESKTOP_IDENTITY_PATH,
    DESKTOP_IDENTITY_VERSION,
    desktop_identity_proof,
    exact_request_loopback_origin,
    is_desktop_owned_instance_path,
    parse_desktop_challenge,
)
from .interfaces.http.analysis_routes import (
    TaskAnalysisCommandService,
    create_task_analysis_router,
)
from .interfaces.http.review_routes import (
    ReviewCommandService,
    create_task_review_router,
)
from .interfaces.http.local_source_routes import create_local_source_router
from .interfaces.http.claude_local_source_routes import (
    create_claude_local_source_router,
)
from .interfaces.http.otlp_ingest_routes import create_otlp_ingest_router
from .interfaces.http.session_reader_routes import create_session_reader_router
from .interfaces.http.onboarding_routes import create_onboarding_router
from .interfaces.http.display_label_routes import create_display_label_router
from .interfaces.http.dto import (
    CapabilitiesDto,
    ProjectSessionCatalogResponse,
    SessionCatalogItemDto,
    SessionCatalogListResponse,
)
from .interfaces.http.session_provider_contracts import (
    SessionProviderFailureCode,
    session_provider_failure_detail,
)
from .interfaces.http.spa_routes import is_spa_navigation_path
from .privacy import load_or_create_api_token


API_TOKEN_HEADER = "X-Prompt-Enhancer-Token"
RUNTIME_LIVENESS_CONTRACT_VERSION = "runtime-liveness.v1"

RuntimeComponentName = Literal[
    "analysis_job_worker",
    "automation_grant_worker",
    "model_ensemble_watch_worker",
    "local_source_refresh_worker",
]


class RuntimeComponentLivenessDto(StrictModel):
    component: RuntimeComponentName
    configured: bool
    alive: bool | None


class RuntimeLivenessDto(StrictModel):
    contract_version: Literal["runtime-liveness.v1"] = (
        RUNTIME_LIVENESS_CONTRACT_VERSION
    )
    status: Literal["ok", "degraded"]
    components: tuple[RuntimeComponentLivenessDto, ...]

_HASHED_STATIC_ASSET_PATTERN = re.compile(
    r"assets/[A-Za-z0-9][A-Za-z0-9._-]{0,95}-[A-Za-z0-9_-]{8,64}"
    r"\.[A-Za-z0-9]{1,8}"
)
_HASHED_MODULE_ASSET_PATTERN = re.compile(
    r"/?(assets/[A-Za-z0-9][A-Za-z0-9._-]{0,95}-[A-Za-z0-9_-]{8,64}\.js)"
)
_HTML_ACCEPT_QUALITY_PATTERN = re.compile(r"(?:0(?:\.\d{0,3})?|1(?:\.0{0,3})?)")


def _accepts_html_navigation(accept: str) -> bool:
    """Return whether an exact HTML media range has positive quality."""

    for media_range in accept.split(","):
        parts = [part.strip() for part in media_range.split(";")]
        if not parts or parts[0].casefold() != "text/html":
            continue
        quality = 1.0
        valid = True
        for parameter in parts[1:]:
            name, separator, value = parameter.partition("=")
            if name.strip().casefold() != "q":
                continue
            normalized = value.strip()
            if separator != "=" or _HTML_ACCEPT_QUALITY_PATTERN.fullmatch(
                normalized
            ) is None:
                valid = False
                break
            quality = float(normalized)
        if valid and quality > 0:
            return True
    return False


def _safe_static_request_path(path: str) -> bool:
    """Reject normalized aliases before Starlette resolves a static path."""

    if path == "":
        return True
    if "\\" in path or any(ord(character) < 32 for character in path):
        return False
    return all(segment not in {"", ".", ".."} for segment in path.split("/"))


class _ModuleScriptCollector(HTMLParser):
    """Collect module-script sources without executing or resolving HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[str | None] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag.casefold() != "script":
            return
        type_values = [value for name, value in attrs if name == "type"]
        if (
            len(type_values) != 1
            or (type_values[0] or "").strip().casefold() != "module"
        ):
            return
        src_values = [value for name, value in attrs if name == "src"]
        self.sources.append(src_values[0] if len(src_values) == 1 else None)


def _static_app_revision(static_root: Path) -> str:
    """Return the one safe, content-free module asset named by ``index.html``."""

    index_path = static_root / "index.html"
    try:
        if index_path.is_symlink():
            raise ValueError("integrated dashboard build is unavailable or unsafe")
        markup = index_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError(
            "integrated dashboard build is unavailable or unsafe"
        ) from error

    collector = _ModuleScriptCollector()
    try:
        collector.feed(markup)
        collector.close()
    except Exception as error:
        raise ValueError(
            "integrated dashboard build is unavailable or unsafe"
        ) from error
    if len(collector.sources) != 1 or collector.sources[0] is None:
        raise ValueError("integrated dashboard build is unavailable or unsafe")

    match = _HASHED_MODULE_ASSET_PATTERN.fullmatch(collector.sources[0])
    if match is None:
        raise ValueError("integrated dashboard build is unavailable or unsafe")
    revision = match.group(1)
    if ".." in revision:
        raise ValueError("integrated dashboard build is unavailable or unsafe")
    module_path = static_root.joinpath(*revision.split("/"))
    try:
        module_is_unsafe = (
            path_has_symlink_component(module_path)
            or module_path.is_symlink()
            or not module_path.is_file()
        )
    except OSError as error:
        raise ValueError(
            "integrated dashboard build is unavailable or unsafe"
        ) from error
    if module_is_unsafe:
        raise ValueError("integrated dashboard build is unavailable or unsafe")
    return revision


class ReadStore(Protocol):
    """The intentionally narrow database surface exposed by the API."""

    def initialize(self) -> None: ...

    def list_metric_definitions(self) -> list[dict[str, Any]]: ...

    def list_sessions(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        provider: Provider | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def count_sessions(
        self,
        *,
        provider: Provider | None = None,
        project_id: str | None = None,
    ) -> int: ...

    def get_session_metrics(self, session_id: str) -> list[dict[str, Any]]: ...


def _default_port(scheme: str) -> int | None:
    if scheme == "http":
        return 80
    if scheme == "https":
        return 443
    return None


def _host_header_is_loopback(host_header: str | None) -> bool:
    """Parse Host without ambiguous colon splitting or user information."""

    if host_header is None or not host_header:
        return False
    if any(character.isspace() for character in host_header):
        return False
    try:
        parsed = urlsplit(f"//{host_header}")
        _ = parsed.port
    except ValueError:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if parsed.path or parsed.query or parsed.fragment:
        return False
    if parsed.hostname is None:
        return False
    return is_loopback_host(parsed.hostname)


def _origin_matches_request(origin: str, request: Request) -> bool:
    """Accept only a syntactically valid same-origin loopback Origin header."""

    try:
        parsed = urlsplit(origin)
        origin_port = parsed.port
    except ValueError:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return False
    if parsed.hostname is None or not is_loopback_host(parsed.hostname):
        return False

    request_host = request.url.hostname
    if request_host is None or not is_loopback_host(request_host):
        return False
    if parsed.scheme != request.url.scheme:
        return False
    if parsed.hostname.casefold() != request_host.casefold():
        return False

    effective_origin_port = origin_port or _default_port(parsed.scheme)
    effective_request_port = request.url.port or _default_port(request.url.scheme)
    return effective_origin_port == effective_request_port


def _json_records(records: Sequence[Mapping[str, Any] | Any]) -> list[Any]:
    """Encode public database records without inspecting arbitrary object attributes."""

    encoded: list[Any] = []
    for record in records:
        if isinstance(record, Mapping):
            encoded.append(jsonable_encoder(dict(record)))
            continue
        model_dump = getattr(record, "model_dump", None)
        if callable(model_dump):
            encoded.append(jsonable_encoder(model_dump(mode="json")))
            continue
        raise TypeError("database returned an unsupported public record type")
    return encoded


_SESSION_PROVIDER_HEADERS = {
    "Cache-Control": "no-store, private",
    "Pragma": "no-cache",
}


def _session_provider_failure(
    code: SessionProviderFailureCode,
) -> HTTPException:
    status_code = {
        SessionProviderFailureCode.SESSION_NOT_FOUND: 404,
        SessionProviderFailureCode.SESSION_CATALOG_UNAVAILABLE: 503,
    }[code]
    return HTTPException(
        status_code=status_code,
        detail=session_provider_failure_detail(code),
        headers=_SESSION_PROVIDER_HEADERS,
    )


def _resolve_session_provider(database: Any, session_id: str) -> Provider:
    """Resolve one exact safe-catalog provider without inventing a fallback."""

    catalog_failed = False
    try:
        record = database.get_session(session_id)
    except Exception:
        catalog_failed = True
        record = None
    if catalog_failed:
        raise _session_provider_failure(
            SessionProviderFailureCode.SESSION_CATALOG_UNAVAILABLE,
        )
    if record is None:
        raise _session_provider_failure(
            SessionProviderFailureCode.SESSION_NOT_FOUND,
        )
    provider: Provider | None = None
    provider_read_failed = False
    try:
        provider_value = (
            record.get("provider")
            if isinstance(record, Mapping)
            else getattr(record, "provider", None)
        )
        provider = Provider(provider_value)
    except Exception:
        provider_read_failed = True
    if provider_read_failed or provider is None:
        raise _session_provider_failure(
            SessionProviderFailureCode.SESSION_CATALOG_UNAVAILABLE,
        )
    return provider


def create_app(
    settings: AppSettings | None = None,
    database: ReadStore | None = None,
    api_token: str | None = None,
    task_review_service: ReviewCommandService | None = None,
    task_lifecycle_service: TaskLifecycleService | None = None,
    metric_lifecycle_evidence_service: MetricLifecycleEvidenceService | None = None,
    agent_metric_evidence_service: AgentMetricEvidenceService | None = None,
    declared_task_profile_service: DeclaredTaskProfileService | None = None,
    requirement_plan_evidence_service: RequirementPlanEvidenceService | None = None,
    requirement_action_evidence_service: (
        RequirementActionEvidenceService | None
    ) = None,
    requirement_verification_evidence_service: (
        RequirementVerificationEvidenceService | None
    ) = None,
    task_analysis_service: TaskAnalysisCommandService | None = None,
    session_text_analysis_service: SessionTextAnalysisService | None = None,
    session_model_link_experiment_service: SessionModelLinkExperimentService | None = None,
    session_model_ensemble_service: SessionModelEnsembleService | None = None,
    model_ensemble_watch_service: ModelEnsembleWatchService | None = None,
    model_ensemble_watch_worker: ModelEnsembleWatchWorker | None = None,
    project_quality_aggregation_service: ProjectQualityAggregationService | None = None,
    provider_compatibility_catalog: ProviderCompatibilityCatalog | None = None,
    metric_readiness_service: MetricReadinessService | None = None,
    metric_coverage_service: MetricCoverageService | None = None,
    codex_source_service: CodexLocalSourceService | None = None,
    claude_source_service: ClaudeCodeLocalSourceService | None = None,
    otlp_ingest_token: str | None = None,
    telemetry_ingest_service=None,
    session_reader_service=None,
    onboarding_service=None,
    calibration_rating_service=None,
    objective_overrides_provider=None,
    local_model_service=None,
    model_judge_service=None,
    calibration_sample_session_ids=None,
    all_session_ids=None,
    prompt_check_service=None,
    local_agent_service=None,
    workspace_folder_picker: LocalWorkspaceFolderPicker | None = None,
    application_update_service: ApplicationUpdateSurface | None = None,
    agent_hardening_service=None,
    agent_mcp_connection_service=None,
    mcp_registry_catalog_service=None,
    mcp_server_management_service=None,
    mcp_managed_runtime_service=None,
    annotation_service=None,
    shared_folder_service=None,
    peer_folder_client=None,
    central_annotation_server=None,
    remote_annotation_client=None,
    local_source_refresh_worker=None,
    display_label_service: ManualDisplayLabelService | None = None,
    model_evaluation_service: LocalTextModelEvaluationService | None = None,
    analysis_job_service: AnalysisJobService | None = None,
    analysis_job_worker: AnalysisJobWorker | None = None,
    automation_grant_service: AutomationGrantService | None = None,
    automation_grant_worker: AutomationGrantWorker | None = None,
    control_plane_service: ControlPlaneService | None = None,
    control_plane_principal_resolver: PrincipalResolver | None = None,
    paid_product_readiness: ProductReadiness | None = None,
    social_readiness: SocialReadiness | None = None,
    social_service: SocialService | None = None,
    social_principal_resolver: SocialPrincipalResolver | None = None,
    estimator_repository: EstimatorRepository | None = None,
    static_directory: Path | None = None,
    browser_session_manager: BrowserSessionManager | None = None,
    user_presence_confirmation: Callable[[Request, bytes], None] | None = None,
    user_presence_confirmation_mode: Literal["native_bridge_bound_token"] | None = None,
    desktop_owned_readiness_path: str | None = None,
) -> FastAPI:
    """Build the local API without enabling CORS or any remote integrations."""

    resolved_settings = settings or AppSettings.from_env()
    resolved_application_update_service = (
        application_update_service
        if application_update_service is not None
        else UnconfiguredApplicationUpdateSurface(installed_version=__version__)
    )
    if user_presence_confirmation_mode not in {None, "native_bridge_bound_token"}:
        raise ValueError("unsupported user-presence confirmation mode")
    if desktop_owned_readiness_path is not None and not is_desktop_owned_instance_path(
        desktop_owned_readiness_path
    ):
        raise ValueError("invalid desktop-owned readiness path")
    if user_presence_confirmation is None:
        if user_presence_confirmation_mode is not None:
            raise ValueError("user-presence mode requires an adapter")
        resolved_user_presence_mode = "unavailable"
    else:
        resolved_user_presence_mode = (
            user_presence_confirmation_mode or "native_bridge_bound_token"
        )
    if database is None or api_token is None:
        prepare_app_home(resolved_settings)

    if database is None:
        from .database import Database

        database = Database(Path(resolved_settings.database_path))
    database.initialize()

    resolved_token = api_token
    if resolved_token is None:
        resolved_token = load_or_create_api_token(resolved_settings.api_token_path)
    if len(resolved_token) < 32:
        raise ValueError("local API token is unexpectedly short")

    runtime_workers: tuple[tuple[RuntimeComponentName, Any | None], ...] = (
        ("analysis_job_worker", analysis_job_worker),
        ("automation_grant_worker", automation_grant_worker),
        ("model_ensemble_watch_worker", model_ensemble_watch_worker),
        ("local_source_refresh_worker", local_source_refresh_worker),
    )

    from .application.runtime_lifecycle import RuntimeComponent, RuntimeLifecycleReport

    runtime_lifecycle = RuntimeLifecycleReport()
    started: list[tuple[RuntimeComponentName, Any]] = []
    cleanup_lock = Lock()

    def stop_runtime_components() -> None:
        # Both ASGI lifespan and the owning desktop's emergency exit use this
        # exact cleanup. A forced server exit must not bypass model unloading.
        with cleanup_lock:
            if runtime_lifecycle.cleanup_finished:
                return
            cleanup_failures: list[RuntimeComponent] = []
            for name, worker in reversed(started):
                try:
                    worker.stop()
                except Exception:
                    cleanup_failures.append(RuntimeComponent(name))
            # Release model sockets before waiting for Agent turns that may be
            # blocked reading them. Evaluation jobs own a separate model tree.
            for component, service in (
                (RuntimeComponent.LOCAL_MODEL_SERVICE, local_model_service),
                (RuntimeComponent.LOCAL_AGENT_SERVICE, local_agent_service),
                (
                    RuntimeComponent.MCP_MANAGED_RUNTIME_SERVICE,
                    mcp_managed_runtime_service,
                ),
                (RuntimeComponent.MODEL_EVALUATION_SERVICE, model_evaluation_service),
            ):
                if service is None:
                    continue
                try:
                    service.shutdown()
                except Exception:
                    cleanup_failures.append(component)
            try:
                resolved_application_update_service.shutdown()
            except Exception:
                cleanup_failures.append(RuntimeComponent.APPLICATION_UPDATE_SERVICE)
            runtime_lifecycle.shutdown_failures = tuple(cleanup_failures)
            runtime_lifecycle.cleanup_finished = True

    @asynccontextmanager
    async def local_lifespan(_app: FastAPI):
        runtime_lifecycle.startup_failure = None
        runtime_lifecycle.shutdown_failures = ()
        runtime_lifecycle.cleanup_finished = False
        started.clear()
        primary_failed = False
        try:
            for _name, worker in runtime_workers:
                if worker is None:
                    continue
                # Stop is required to be idempotent, so registering before
                # start also covers a start method that launches and then fails.
                started.append((_name, worker))
                start_failed = False
                try:
                    worker.start()
                except Exception:
                    start_failed = True
                if start_failed:
                    runtime_lifecycle.startup_failure = RuntimeComponent(_name)
                    raise RuntimeError("runtime_component_start_failed")
            yield
        except BaseException:
            primary_failed = True
            raise
        finally:
            stop_runtime_components()
            if runtime_lifecycle.shutdown_failures and not primary_failed:
                raise RuntimeError("runtime_component_shutdown_failed")

    app = FastAPI(
        title="Prompt Enhancer Local API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=local_lifespan,
    )
    from fastapi.middleware.gzip import GZipMiddleware

    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.state.database = database
    app.state.runtime_workers = runtime_workers
    app.state.runtime_lifecycle = runtime_lifecycle
    app.state.stop_runtime_components = stop_runtime_components

    def _session_provider(session_id: str) -> Provider:
        return _resolve_session_provider(database, session_id)
    app.state.api_token = resolved_token
    app.state.settings = resolved_settings
    app.state.browser_sessions = browser_session_manager or BrowserSessionManager()

    @app.exception_handler(RequestValidationError)
    async def sanitize_request_validation(
        _request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422, content={"detail": "request validation failed"}
        )

    @app.middleware("http")
    async def enforce_local_request_boundary(request: Request, call_next: Any) -> Any:
        if not _host_header_is_loopback(request.headers.get("host")):
            response = JSONResponse(
                status_code=400, content={"detail": "invalid host"}
            )
        else:
            origin = request.headers.get("origin")
            if origin is not None and not _origin_matches_request(origin, request):
                response = JSONResponse(
                    status_code=403, content={"detail": "origin not allowed"}
                )
            else:
                response = await call_next(request)
        static_asset = request.url.path.removeprefix("/")
        route_declared_private = (
            response.headers.get("Cache-Control") == "no-store, private"
        )
        if route_declared_private or any(
            marker in request.url.path
            for marker in (
                "quality-analysis-previews",
                "model-ensemble-runs",
                "model-ensemble-watch",
                "model-ensemble-watches",
                "model-ensemble-attempts",
                "model-ensemble-head",
                "model-ensemble-snapshots",
                "/metric-lifecycle-evidence",
                "/metric-contracts/",
                "metric-coverage",
                "/analysis-jobs",
                "/automation-grants",
                "/control-plane",
                "/paid-product",
                "/social",
                "/estimators",
                "/text-model-compatibility",
                "/text-model-runtime",
                "/task-lifecycles",
                "/lifecycle",
                "/agent-metric-evidence",
                "/requirement-plan-evidence",
                "/requirement-action-evidence",
                "/requirement-verification-evidence",
                "/declared-task-profile",
                "/agent/",
                "/local-ui/workspace-folder-picker",
                "/application-updates",
                "/integrations/agent-mcp/",
                "/integrations/mcp-store/",
                "/diagnostics/agent-hardening",
                "/v1/calibration/",
            )
        ):
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["Pragma"] = "no-cache"
        elif (
            200 <= response.status_code < 300
            and _HASHED_STATIC_ASSET_PATTERN.fullmatch(static_asset) is not None
            and ".." not in static_asset
        ):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'; object-src 'none'; connect-src 'self'; "
            "img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        return response

    def require_local_token(
        request: Request,
        supplied_token: Annotated[str | None, Header(alias=API_TOKEN_HEADER)] = None,
        supplied_csrf: Annotated[str | None, Header(alias=CSRF_HEADER)] = None,
    ) -> None:
        candidate = supplied_token or ""
        supplied_authorization = request.headers.get("authorization")
        if not candidate and supplied_authorization:
            # OpenAI-style clients send the app token as a bearer credential.
            scheme, _, bearer = supplied_authorization.partition(" ")
            if scheme.casefold() == "bearer":
                candidate = bearer.strip()
        expected = request.app.state.api_token
        token_authenticated = hmac.compare_digest(
            candidate.encode("utf-8"), expected.encode("utf-8")
        )
        if token_authenticated:
            return
        cookie_value = request.cookies.get(BROWSER_SESSION_COOKIE)
        sessions = request.app.state.browser_sessions
        if not sessions.authenticate(cookie_value):
            raise HTTPException(status_code=401, detail="authentication required")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin is None or not _origin_matches_request(origin, request):
                raise HTTPException(
                    status_code=403, detail="same-origin mutation required"
                )
            if not sessions.verify_csrf(cookie_value, supplied_csrf):
                raise HTTPException(status_code=403, detail="CSRF validation failed")

    def require_browser_interaction(
        request: Request,
        supplied_csrf: Annotated[str | None, Header(alias=CSRF_HEADER)] = None,
    ) -> None:
        """Admit an explicit browser gesture without granting native authority."""

        if request.headers.get(API_TOKEN_HEADER) is not None or request.headers.get(
            "authorization"
        ) is not None:
            raise HTTPException(status_code=403, detail="browser interaction required")
        cookie_value = request.cookies.get(BROWSER_SESSION_COOKIE)
        sessions = request.app.state.browser_sessions
        if not sessions.authenticate(cookie_value):
            raise HTTPException(status_code=401, detail="browser session required")
        origin = request.headers.get("origin")
        if origin is None or not _origin_matches_request(origin, request):
            raise HTTPException(
                status_code=403, detail="same-origin interaction required"
            )
        if not sessions.verify_csrf(cookie_value, supplied_csrf):
            raise HTTPException(status_code=403, detail="CSRF validation failed")

    async def require_browser_user_confirmation(
        request: Request,
        supplied_csrf: Annotated[str | None, Header(alias=CSRF_HEADER)] = None,
        _supplied_user_presence: Annotated[
            str | None, Header(alias=USER_PRESENCE_HEADER)
        ] = None,
    ) -> None:
        """Reserve measurement-authority decisions for an owned native UI.

        API-token clients may submit inert proposals, but the token is not a
        human-decision credential.  A decision therefore requires the
        ephemeral browser session, same-origin mutation proof, its CSRF token,
        and an independently injected, non-self-issuable user-presence
        adapter. The default local server has no such adapter and fails closed.
        """

        if request.headers.get(API_TOKEN_HEADER) is not None or request.headers.get(
            "authorization"
        ) is not None:
            raise HTTPException(
                status_code=403, detail="owned native confirmation required"
            )
        cookie_value = request.cookies.get(BROWSER_SESSION_COOKIE)
        sessions = request.app.state.browser_sessions
        if not sessions.authenticate(cookie_value):
            raise HTTPException(status_code=401, detail="browser session required")
        origin = request.headers.get("origin")
        if origin is None or not _origin_matches_request(origin, request):
            raise HTTPException(
                status_code=403, detail="same-origin confirmation required"
            )
        if not sessions.verify_csrf(cookie_value, supplied_csrf):
            raise HTTPException(status_code=403, detail="CSRF validation failed")
        if user_presence_confirmation is None:
            raise HTTPException(
                status_code=503,
                detail="user-presence confirmation is unavailable",
            )
        user_presence_confirmation(request, await request.body())

    async def require_requirement_acceptance_confirmation(
        request: Request,
    ) -> None:
        """Apply native confirmation without advertising token authentication.

        The route publishes its four required browser/native proofs explicitly.
        Values are still validated by the same runtime dependency used by the
        other owned-native authority routes.
        """

        await require_browser_user_confirmation(
            request,
            supplied_csrf=request.headers.get(CSRF_HEADER),
            _supplied_user_presence=request.headers.get(USER_PRESENCE_HEADER),
        )

    authenticated = Depends(require_local_token)

    @app.get("/health", include_in_schema=False)
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "cost_mode": resolved_settings.cost_mode.value,
            "data_tier": resolved_settings.data_tier.value,
        }

    @app.get("/auth/session", include_in_schema=False)
    def browser_session(request: Request, response: Response) -> dict[str, Any]:
        fetch_site = request.headers.get("sec-fetch-site")
        if fetch_site not in {None, "same-origin", "none"}:
            raise HTTPException(status_code=403, detail="same-origin bootstrap required")
        grant = request.app.state.browser_sessions.issue(
            request.cookies.get(BROWSER_SESSION_COOKIE)
        )
        response.set_cookie(
            key=BROWSER_SESSION_COOKIE,
            value=grant.cookie_value,
            max_age=grant.expires_in_seconds,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
            path="/",
        )
        return {
            "csrf_token": grant.csrf_token,
            "expires_in_seconds": grant.expires_in_seconds,
            "user_presence_confirmation_available": (
                user_presence_confirmation is not None
            ),
            "user_presence_confirmation_mode": resolved_user_presence_mode,
        }

    @app.get(
        "/v1/runtime-liveness",
        response_model=RuntimeLivenessDto,
        responses={503: {"model": RuntimeLivenessDto}},
        dependencies=[authenticated],
    )
    def runtime_liveness(response: Response) -> RuntimeLivenessDto:
        components: list[RuntimeComponentLivenessDto] = []
        degraded = False
        for name, worker in runtime_workers:
            if worker is None:
                components.append(
                    RuntimeComponentLivenessDto(
                        component=name,
                        configured=False,
                        alive=None,
                    )
                )
                continue
            try:
                alive = bool(worker.is_alive())
            except Exception:
                alive = False
            degraded = degraded or not alive
            components.append(
                RuntimeComponentLivenessDto(
                    component=name,
                    configured=True,
                    alive=alive,
                )
            )
        if degraded:
            response.status_code = 503
        return RuntimeLivenessDto(
            status="degraded" if degraded else "ok",
            components=tuple(components),
        )

    @app.get(DESKTOP_IDENTITY_PATH, include_in_schema=False)
    def desktop_identity(
        request: Request,
        challenge: Annotated[
            str | None, Header(alias=DESKTOP_CHALLENGE_HEADER)
        ] = None,
    ) -> dict[str, Any]:
        """Prove knowledge of the local token to the native launcher.

        The launcher never sends the token here.  It sends a fresh random
        challenge and checks the keyed, origin-bound answer locally, so a port
        squatter learns nothing it can reuse and a relay to another loopback
        instance fails the origin binding.  This endpoint grants no access.
        """

        fetch_site = request.headers.get("sec-fetch-site")
        if fetch_site not in {None, "same-origin", "none"}:
            raise HTTPException(status_code=403, detail="native launcher only")
        parsed_challenge = parse_desktop_challenge(challenge)
        if parsed_challenge is None:
            raise HTTPException(status_code=400, detail="invalid desktop challenge")
        origin = exact_request_loopback_origin(
            request.headers.get("host"), request.scope.get("server")
        )
        if origin is None:
            raise HTTPException(
                status_code=403,
                detail="exact loopback authority required",
            )
        return {
            "identity_version": DESKTOP_IDENTITY_VERSION,
            "proof": desktop_identity_proof(
                request.app.state.api_token, origin, parsed_challenge
            ),
        }

    if desktop_owned_readiness_path is not None:

        @app.get(desktop_owned_readiness_path, include_in_schema=False)
        def desktop_owned_instance_ready() -> Response:
            """Prove this exact launcher-owned composition reached readiness."""

            return Response(
                status_code=204,
                headers={"Cache-Control": "no-store"},
            )

    @app.get(
        "/v1/capabilities",
        dependencies=[authenticated],
        response_model=CapabilitiesDto,
    )
    def capabilities() -> CapabilitiesDto:
        write_api = (
            task_review_service is not None
            or task_lifecycle_service is not None
            or task_analysis_service is not None
            or session_text_analysis_service is not None
            or session_model_link_experiment_service is not None
            or provider_compatibility_catalog is not None
            or codex_source_service is not None
            or claude_source_service is not None
            or display_label_service is not None
            or model_evaluation_service is not None
        )
        session_text_analysis = session_text_analysis_service is not None
        return CapabilitiesDto(
            cost_mode="offline_only",
            data_tier="metadata",
            network_inference=False,
            raw_transcripts=(
                session_reader_service is not None and session_reader_service.enabled
            ),
            arbitrary_sql=False,
            write_api=write_api,
            task_review=task_review_service is not None,
            task_lifecycle=task_lifecycle_service is not None,
            task_analysis=task_analysis_service is not None,
            session_text_analysis=session_text_analysis,
            session_model_link_experiment=(
                session_model_link_experiment_service is not None
            ),
            session_text_analysis_data_tier=(
                "redacted_content" if session_text_analysis else None
            ),
            session_text_content_persistence=False,
            codex_local_source=codex_source_service is not None,
            claude_code_local_source=claude_source_service is not None,
            local_models=local_model_service is not None,
            prompt_check=prompt_check_service is not None,
            local_agent=local_agent_service is not None,
            annotation=annotation_service is not None,
            shared_folders=shared_folder_service is not None,
            manual_display_labels=display_label_service is not None,
            browser_session=True,
            demo_provider="synthetic",
        )

    @app.get("/v1/metrics/definitions", dependencies=[authenticated])
    def metric_definitions(request: Request) -> dict[str, list[Any]]:
        records = request.app.state.database.list_metric_definitions()
        return {"definitions": _json_records(records)}

    @app.get(
        "/v1/sessions",
        dependencies=[authenticated],
        response_model=SessionCatalogListResponse,
    )
    def sessions(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
        provider: Provider | None = None,
    ) -> SessionCatalogListResponse:
        if provider is None:
            records = request.app.state.database.list_sessions(limit=limit, offset=offset)
        else:
            records = request.app.state.database.list_sessions(
                limit=limit, offset=offset, provider=provider
            )
        return SessionCatalogListResponse(
            sessions=tuple(SessionCatalogItemDto.from_record(item) for item in records),
            limit=limit,
            offset=offset,
        )

    @app.get(
        "/v1/projects/{project_id}/sessions",
        dependencies=[authenticated],
        response_model=ProjectSessionCatalogResponse,
    )
    def project_sessions(
        request: Request,
        project_id: Annotated[
            str,
            PathParameter(pattern=PSEUDONYM_PATTERN.pattern),
        ],
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
        provider: Provider | None = None,
    ) -> ProjectSessionCatalogResponse:
        records = request.app.state.database.list_sessions(
            limit=limit,
            offset=offset,
            provider=provider,
            project_id=project_id,
        )
        total = request.app.state.database.count_sessions(
            provider=provider,
            project_id=project_id,
        )
        return ProjectSessionCatalogResponse(
            sessions=tuple(SessionCatalogItemDto.from_record(item) for item in records),
            limit=limit,
            offset=offset,
            total=total,
            has_more=offset + len(records) < total,
        )

    @app.get("/v1/sessions/{session_id}/metrics", dependencies=[authenticated])
    def session_metrics(
        request: Request,
        session_id: Annotated[
            str,
            PathParameter(pattern=PSEUDONYM_PATTERN.pattern),
        ],
    ) -> dict[str, Any]:
        records = request.app.state.database.get_session_metrics(session_id)
        return {"session_id": session_id, "metrics": _json_records(records)}

    app.include_router(create_task_query_router(require_local_token))
    app.include_router(
        create_task_lifecycle_router(require_local_token, task_lifecycle_service)
    )
    if metric_lifecycle_evidence_service is not None:
        app.include_router(
            create_metric_lifecycle_evidence_router(
                require_local_token,
                require_browser_user_confirmation,
                metric_lifecycle_evidence_service,
            )
        )
        app.include_router(
            create_agent_metric_evidence_router(
                require_local_token,
                (
                    agent_metric_evidence_service
                    or AgentMetricEvidenceService(metric_lifecycle_evidence_service)
                ),
            )
        )
    app.include_router(
        create_session_analysis_query_router(
            require_local_token, objective_overrides=objective_overrides_provider
        )
    )
    from .interfaces.http.session_timeline_routes import create_session_timeline_router

    app.include_router(create_session_timeline_router(require_local_token))
    from .interfaces.http.project_timeline_routes import create_project_timeline_router

    app.include_router(create_project_timeline_router(require_local_token))
    app.include_router(create_session_quality_aggregation_router(require_local_token))
    if project_quality_aggregation_service is not None:
        app.include_router(
            create_project_quality_aggregation_router(
                require_local_token,
                project_quality_aggregation_service,
            )
        )
    app.include_router(
        create_research_router(require_local_token, model_evaluation_service)
    )
    if estimator_repository is not None:
        app.include_router(
            create_estimator_router(require_local_token, estimator_repository)
        )
    if provider_compatibility_catalog is not None:
        app.include_router(
            create_provider_compatibility_router(
                require_local_token,
                provider_compatibility_catalog,
            )
        )
    if metric_readiness_service is not None:
        app.include_router(
            create_metric_readiness_router(
                require_local_token,
                metric_readiness_service,
            )
        )
    if metric_coverage_service is not None:
        app.include_router(
            create_metric_coverage_router(
                require_local_token,
                metric_coverage_service,
            )
        )
    if session_text_analysis_service is not None:
        app.include_router(
            create_session_analysis_command_router(
                require_local_token,
                session_text_analysis_service,
                provider_resolver=_session_provider,
            )
        )
    if analysis_job_service is not None:
        app.include_router(
            create_analysis_job_router(require_local_token, analysis_job_service)
        )
    if automation_grant_service is not None:
        app.include_router(
            create_automation_grant_router(
                require_local_token,
                automation_grant_service,
            )
        )
    # Three independent gates: an operator must opt in through settings, the
    # composition root must have built a service, and a principal resolver must
    # exist. Without a resolver there is no way to verify who is calling, so no
    # route is mounted at all rather than mounting one that trusts a body.
    if (
        control_plane_service is not None
        and control_plane_principal_resolver is not None
        and resolved_settings.control_plane_development_api
    ):
        app.include_router(
            create_control_plane_router(
                require_local_token,
                control_plane_service,
                control_plane_principal_resolver,
            )
        )
    # Readiness is intentionally the only paid-product browser surface. Both
    # an exact operator opt-in and an explicitly composed receipt are required;
    # identity, billing, approval, and hosted-analysis commands stay unmounted.
    if (
        paid_product_readiness is not None
        and resolved_settings.paid_product_development_api
    ):
        app.include_router(
            create_paid_product_readiness_router(
                require_local_token,
                paid_product_readiness,
            )
        )
    # Social routes are default-off and never self-compose. Readiness needs the
    # exact operator opt-in plus an explicitly supplied receipt; mutations need
    # the opt-in plus both a service and a principal resolver. Nothing here
    # opens social.sqlite3, and a browser session or local token alone can
    # never act as a social principal.
    if social_readiness is not None and resolved_settings.social_development_api:
        app.include_router(
            create_social_readiness_router(require_local_token, social_readiness)
        )
    if (
        social_service is not None
        and social_principal_resolver is not None
        and resolved_settings.social_development_api
    ):
        app.include_router(
            create_social_mutation_router(
                require_local_token,
                social_service,
                social_principal_resolver,
            )
        )
    if session_model_link_experiment_service is not None:
        app.include_router(
            create_model_link_experiment_router(
                require_local_token,
                session_model_link_experiment_service,
                provider_resolver=_session_provider,
            )
        )
    if session_model_ensemble_service is not None:
        app.include_router(
            create_model_ensemble_router(
                require_local_token,
                session_model_ensemble_service,
                provider_resolver=_session_provider,
            )
        )
    if (
        model_ensemble_watch_service is not None
        and session_model_ensemble_service is not None
    ):
        app.include_router(
            create_model_ensemble_watch_router(
                require_local_token,
                model_ensemble_watch_service,
                session_model_ensemble_service,
                provider_resolver=_session_provider,
            )
        )
    if task_review_service is not None:
        app.include_router(create_task_review_router(require_local_token, task_review_service))
    if task_analysis_service is not None:
        app.include_router(
            create_task_analysis_router(require_local_token, task_analysis_service)
        )
    if codex_source_service is not None:
        app.include_router(
            create_local_source_router(require_local_token, codex_source_service)
        )
    if claude_source_service is not None:
        app.include_router(
            create_claude_local_source_router(
                require_local_token, claude_source_service
            )
        )
    if otlp_ingest_token is not None and telemetry_ingest_service is not None:
        app.include_router(
            create_otlp_ingest_router(otlp_ingest_token, telemetry_ingest_service)
        )
    if local_model_service is not None:
        from .interfaces.http.local_model_routes import create_local_model_router

        app.include_router(create_local_model_router(require_local_token, local_model_service))
    if prompt_check_service is not None:
        from .interfaces.http.prompt_check_routes import create_prompt_check_router

        app.include_router(create_prompt_check_router(require_local_token, prompt_check_service))
    from .interfaces.http.workspace_folder_picker_routes import (
        create_workspace_folder_picker_router,
    )

    app.include_router(
        create_workspace_folder_picker_router(
            require_local_token,
            require_browser_interaction,
            workspace_folder_picker,
        )
    )
    # Status is local and content-free. A check is separately restricted to an
    # explicit same-origin browser gesture; the default surface has no fetcher.
    app.include_router(
        create_application_update_router(
            require_local_token,
            require_browser_interaction,
            resolved_application_update_service,
        )
    )
    if local_agent_service is not None:
        from .interfaces.http.local_agent_routes import create_local_agent_router

        app.include_router(
            create_local_agent_router(
                require_local_token,
                require_browser_user_confirmation,
                local_agent_service,
            )
        )
    if agent_hardening_service is not None:
        from .interfaces.http.agent_hardening_routes import (
            create_agent_hardening_router,
        )

        app.include_router(
            create_agent_hardening_router(
                require_local_token,
                require_browser_user_confirmation,
                agent_hardening_service,
            )
        )
    if agent_mcp_connection_service is not None:
        from .application.agent_controller_client import AgentControllerClient
        from .application.agent_mcp_connections import AgentMcpPrincipal
        from .application.agent_mcp_surface import AgentMcpSurface
        from .application.local_agent_limits import LocalAgentError
        from .infrastructure.agent_controller_http import (
            LoopbackAgentControllerTransport,
        )
        from .interfaces.http.agent_mcp_routes import create_agent_mcp_router

        def create_http_agent_mcp_surface(
            base_url: str,
            principal: AgentMcpPrincipal,
        ) -> AgentMcpSurface:
            return AgentMcpSurface(
                AgentControllerClient(
                    LoopbackAgentControllerTransport(base_url, resolved_token)
                ),
                allow_model_lifecycle=principal.allow_model_lifecycle,
                scope_project_id=principal.project_id,
                controller_connection_id=principal.connection_id,
                controller_ownership=agent_mcp_connection_service.ownership,
            )

        def agent_controller_session_settled(session_id: str) -> bool:
            if local_agent_service is None:
                return False
            try:
                session = local_agent_service.get(session_id)
            except LocalAgentError as error:
                return error.code == "session_not_found"
            return not (
                session.running
                or session.closing
                or session.stopping
                or session.cleanup_unconfirmed
                or session.pending_approval_id is not None
            )

        app.include_router(
            create_agent_mcp_router(
                require_local_token,
                require_browser_user_confirmation,
                agent_mcp_connection_service,
                create_http_agent_mcp_surface,
                agent_controller_session_settled,
            )
        )
    if mcp_registry_catalog_service is not None:
        from .interfaces.http.mcp_registry_routes import create_mcp_registry_router

        app.include_router(
            create_mcp_registry_router(
                require_local_token,
                mcp_registry_catalog_service,
            )
        )
    if mcp_server_management_service is not None:
        from .interfaces.http.mcp_server_management_routes import (
            create_mcp_server_management_router,
        )

        app.include_router(
            create_mcp_server_management_router(
                require_local_token,
                require_browser_user_confirmation,
                mcp_server_management_service,
                mcp_managed_runtime_service,
            )
        )
    if requirement_plan_evidence_service is not None:
        app.include_router(
            create_requirement_plan_evidence_router(
                require_local_token,
                require_browser_user_confirmation,
                requirement_plan_evidence_service,
            )
        )
    if requirement_action_evidence_service is not None:
        app.include_router(
            create_requirement_action_evidence_router(
                require_local_token,
                require_browser_user_confirmation,
                requirement_action_evidence_service,
            )
        )
    if requirement_verification_evidence_service is not None:
        app.include_router(
            create_requirement_verification_evidence_router(
                require_local_token,
                require_requirement_acceptance_confirmation,
                requirement_verification_evidence_service,
            )
        )
    if declared_task_profile_service is not None:
        app.include_router(
            create_declared_task_profile_router(
                require_local_token,
                require_browser_user_confirmation,
                declared_task_profile_service,
                provider_resolver=_session_provider,
                confirmation_available=(user_presence_confirmation is not None),
            )
        )
    if annotation_service is not None:
        from .interfaces.http.annotation_routes import create_annotation_router, create_central_router

        app.include_router(create_annotation_router(require_local_token, annotation_service, remote_annotation_client))
        if central_annotation_server is not None:
            app.include_router(create_central_router(require_local_token, central_annotation_server))
    if shared_folder_service is not None and peer_folder_client is not None:
        from .interfaces.http.shared_folder_routes import create_p2p_router, create_shared_folder_router

        app.include_router(create_shared_folder_router(require_local_token, shared_folder_service, peer_folder_client))
        app.include_router(create_p2p_router(shared_folder_service))
    if model_judge_service is not None:
        from .interfaces.http.model_judge_routes import create_model_judge_router

        def _sample_ids():
            if calibration_sample_session_ids is None:
                raise RuntimeError("model judge sample catalog unavailable")
            return tuple(calibration_sample_session_ids())

        def _all_ids():
            if all_session_ids is None:
                raise RuntimeError("model judge session catalog unavailable")
            return tuple(all_session_ids())

        app.include_router(create_model_judge_router(require_local_token, model_judge_service, _sample_ids, _all_ids))
    if calibration_rating_service is not None:
        from .interfaces.http.calibration_routes import create_calibration_router

        app.include_router(create_calibration_router(require_local_token, calibration_rating_service))
    if session_reader_service is not None and session_reader_service.enabled:
        app.include_router(
            create_session_reader_router(require_local_token, session_reader_service)
        )
    if onboarding_service is not None:
        app.include_router(create_onboarding_router(require_local_token, onboarding_service))

    if display_label_service is not None:
        app.include_router(
            create_display_label_router(require_local_token, display_label_service)
        )
    if static_directory is not None:
        static_root = lexical_absolute_path(static_directory)
        if (
            path_has_symlink_component(static_root)
            or not static_root.is_dir()
            or not (static_root / "index.html").is_file()
        ):
            raise ValueError("integrated dashboard build is unavailable or unsafe")
        _static_app_revision(static_root)
        static_files = StaticFiles(directory=static_root, html=True)

        @app.api_route(
            "/app-revision.json", methods=["GET", "HEAD"], include_in_schema=False
        )
        def integrated_dashboard_revision() -> JSONResponse:
            try:
                revision = _static_app_revision(static_root)
            except ValueError:
                return JSONResponse(
                    status_code=503,
                    content={"detail": "dashboard revision temporarily unavailable"},
                )
            return JSONResponse(content={"revision": revision})

        @app.api_route(
            "/{asset_path:path}", methods=["GET", "HEAD"], include_in_schema=False
        )
        async def integrated_dashboard(request: Request, asset_path: str):
            first_segment = asset_path.partition("/")[0]
            if first_segment in {"v1", "auth", "health"}:
                raise HTTPException(status_code=404, detail="not found")
            requested = asset_path or "index.html"
            response = None
            if _safe_static_request_path(asset_path):
                try:
                    response = await static_files.get_response(
                        requested, request.scope
                    )
                except StarletteHTTPException as error:
                    if error.status_code != 404:
                        raise
            if response is not None and response.status_code != 404:
                return response
            if not _accepts_html_navigation(request.headers.get("accept", "")):
                raise HTTPException(status_code=404, detail="not found")
            if not is_spa_navigation_path(asset_path):
                raise HTTPException(status_code=404, detail="not found")
            return await static_files.get_response("index.html", request.scope)

    return app
