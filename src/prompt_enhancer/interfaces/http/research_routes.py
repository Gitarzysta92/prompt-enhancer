"""Read-only, content-free research catalog for the dashboard Model Lab."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import Field

from ...application.analysis.method_research import (
    CATALOG_KEY,
    CATALOG_REVIEWED_ON,
    CATALOG_VERSION,
    METHODS,
    METRIC_ROADMAP,
    MODEL_CANDIDATES,
    SOURCES,
    AnalysisMethod,
    MetricRoadmapItem,
    ModelBenchmark,
    ModelCandidate,
    ResearchSource,
)
from .dto import HttpDto
from ...infrastructure.text_models.jobs import (
    CandidateEvaluationSummary,
    LocalTextModelEvaluationService,
    ModelEvaluationBusyError,
    ModelEvaluationUnavailableError,
    ModelEvaluationJob,
    ModelEvaluationNotFoundError,
    ModelEvaluationRequest,
    ModelRuntimeInventory,
)
from ...infrastructure.text_models.compatibility import (
    ModelCompatibilityCatalog,
    ModelCompatibilityEntry,
)


class ResearchSourceDto(HttpDto):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    title: str = Field(min_length=1, max_length=160)
    url: str = Field(pattern=r"^https://[^\s]+$", max_length=256)
    kind: Literal["paper", "model_card"]


class AnalysisMethodDto(HttpDto):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=96)
    family: Literal[
        "extraction", "conversation", "linking", "semantic_inference", "workflow", "evaluation"
    ]
    approach: Literal[
        "rules",
        "classifier",
        "hybrid",
        "statistical",
        "embedding",
        "reranker",
        "nli",
        "graph_rules",
        "graph",
        "process_mining",
        "generative_model",
        "calibration",
    ]
    maturity: Literal[
        "product_baseline", "evaluated_exploratory", "research_candidate", "failed_gate"
    ]
    privacy_tier: Literal["metadata", "redacted_content"]
    purpose: str = Field(min_length=1, max_length=320)
    produces: tuple[str, ...] = Field(min_length=1, max_length=8)
    candidate_model_keys: tuple[str, ...] = Field(max_length=8)
    source_keys: tuple[str, ...] = Field(max_length=8)
    limitations: tuple[str, ...] = Field(min_length=1, max_length=8)


class ModelBenchmarkDto(HttpDto):
    benchmark_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    case_count: int = Field(ge=1, le=100_000)
    primary_metric: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    primary_value: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    secondary_metric: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$"
    )
    secondary_value: float | None = Field(
        default=None, ge=0.0, le=1.0, allow_inf_nan=False
    )
    critical_metric: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$"
    )
    critical_value: float | None = Field(
        default=None, ge=0.0, le=1.0, allow_inf_nan=False
    )


class ModelCandidateDto(HttpDto):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    display_name: str = Field(min_length=1, max_length=96)
    repository_id: str = Field(pattern=r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
    task: str = Field(min_length=1, max_length=80)
    license_spdx: Literal["MIT", "Apache-2.0"]
    revision: str | None = Field(default=None, pattern=r"^[a-f0-9]{40}$")
    parameter_scale: str = Field(pattern=r"^[0-9]+(?:\.[0-9]+)?[MB]$", max_length=16)
    language_scope: str = Field(min_length=1, max_length=96)
    status: Literal[
        "evaluated_exploratory", "research_shortlist", "rejected_screen"
    ]
    product_enabled: Literal[False]
    trust_remote_code: Literal[False]
    decision: str = Field(min_length=1, max_length=360)
    benchmark: ModelBenchmarkDto | None
    source_keys: tuple[str, ...] = Field(min_length=1, max_length=8)


class MetricRoadmapItemDto(HttpDto):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=96)
    profile: Literal["prompt", "collaboration", "logic", "agent_answer", "outcome"]
    question: str = Field(min_length=1, max_length=240)
    direction: Literal["higher_is_better", "lower_is_better", "contextual"]
    state: Literal["baseline_available", "research", "needs_objective_evidence"]
    evidence: str = Field(min_length=1, max_length=280)
    method_keys: tuple[str, ...] = Field(min_length=1, max_length=8)
    caution: str = Field(min_length=1, max_length=240)


class TextAnalysisResearchCatalogDto(HttpDto):
    catalog_key: Literal["text-analysis-methods"]
    catalog_version: int = Field(ge=1)
    reviewed_on: date
    privacy_mode: Literal["local_only_redacted_content"]
    summary_policy: Literal["multidimensional_profile_no_universal_score"]
    catalog_read_starts_session_access: Literal[False]
    catalog_read_downloads_models: Literal[False]
    methods: tuple[AnalysisMethodDto, ...] = Field(min_length=1, max_length=64)
    model_candidates: tuple[ModelCandidateDto, ...] = Field(
        min_length=1, max_length=32
    )
    metric_roadmap: tuple[MetricRoadmapItemDto, ...] = Field(
        min_length=10, max_length=64
    )
    sources: tuple[ResearchSourceDto, ...] = Field(min_length=1, max_length=64)


class ModelRuntimeInventoryDto(HttpDto):
    preferred_device: Literal["cpu", "cuda", "mps"]
    cuda_state: Literal["available", "unavailable", "unknown"]
    cuda_available: bool | None
    mps_available: bool
    cpu_available: Literal[True]
    cpu_architecture_bucket: Literal["x86_64", "arm64", "x86", "arm32"] | None
    logical_core_bucket: Literal[
        "1_to_4", "5_to_8", "9_to_16", "17_to_32", "33_to_64", "65_plus"
    ] | None
    system_ram_bucket: Literal[
        "below_16_gib_class",
        "16_gib_class",
        "32_gib_class",
        "64_gib_plus_class",
    ] | None
    cuda_vram_bucket: Literal[
        "below_8_gib_class",
        "8_gib_class",
        "12_gib_class",
        "16_gib_class",
        "24_gib_plus_class",
    ] | None
    cuda_capability_bucket: Literal["pre_7", "7_x", "8_x", "9_plus"] | None
    model_cache_free_disk_bucket: Literal[
        "under_10240_mib",
        "10240_to_51199_mib",
        "51200_to_102399_mib",
        "102400_plus_mib",
    ] | None
    discovery_reason_codes: tuple[
        Literal[
            "cpu_architecture_unknown",
            "logical_core_bucket_unknown",
            "system_ram_bucket_unknown",
            "cuda_inventory_unknown",
            "model_cache_free_disk_bucket_unknown",
        ],
        ...,
    ] = Field(max_length=5)
    inventory_version: Literal["bucketed-sensitive-hardware-inventory-v3"]
    one_model_at_a_time: Literal[True]
    subprocess_isolation: Literal[True]
    raw_session_data_accepted: Literal[False]
    model_child_gpu_allocation_ceiling_mib: Literal[6144]
    model_child_rss_ceiling_mib: Literal[8192]
    model_downloads_started: Literal[False]
    model_activation_allowed: Literal[False]
    sensitivity: Literal["sensitive_derived"]
    local_only: Literal[True]
    persisted: Literal[False]
    synced: Literal[False]


class ModelCompatibilityEntryDto(HttpDto):
    configuration_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,95}$")
    model_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    repository_id: str = Field(pattern=r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
    revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    task: Literal[
        "requirement_action_retrieval",
        "scoped_nli",
        "binary_nli",
        "pair_reranking",
        "structured_rubric",
    ]
    role: Literal[
        "retrieval",
        "reranking",
        "scoped_nli",
        "binary_nli",
        "structured_rubric",
    ]
    language_scope: Literal["english_polish"]
    license_spdx: Literal["MIT", "Apache-2.0"]
    status: Literal["research_only", "unavailable"]
    reason_codes: tuple[
        Literal[
            "exploratory_resource_fit",
            "resource_measurement_missing",
            "hardware_inventory_unknown",
            "insufficient_system_ram",
            "cuda_unavailable",
            "cuda_inventory_unknown",
            "insufficient_cuda_vram",
            "child_gpu_allocation_ceiling_exceeded",
            "child_rss_ceiling_exceeded",
            "unsafe_pickle_only",
        ],
        ...,
    ] = Field(min_length=1, max_length=2)
    quantization: Literal["none", "bitsandbytes_nf4"]
    dtype: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    runtime: str = Field(pattern=r"^[a-z][a-z0-9_]{0,95}$")
    measurement_method: Literal[
        "torch_cuda_max_memory_allocated",
        "documented_approximate_gpu_peak_only",
        "not_measured",
    ]
    measurement_precision: Literal[
        "observed_to_0_001_mib",
        "documented_approximate_0_01_gib",
        "not_measured",
    ]
    measurement_source: str = Field(pattern=r"^[a-z][a-z0-9_]{0,95}$")
    resource_measurement_state: Literal["complete", "partial", "missing"]
    observed_peak_gpu_allocation_mib: float | None = Field(
        default=None, ge=0, le=1_048_576, allow_inf_nan=False
    )
    observed_peak_child_rss_mib: float | None = Field(
        default=None, ge=0, le=1_048_576, allow_inf_nan=False
    )
    benchmark_key: str | None = Field(
        default=None, pattern=r"^[a-z][a-z0-9_-]{0,63}$"
    )
    synthetic_case_count: int | None = Field(default=None, ge=1, le=100_000)
    trust_remote_code: Literal[False]
    product_enabled: Literal[False]
    activation_allowed: Literal[False]
    download_allowed: Literal[False]


class ModelCompatibilityCatalogDto(HttpDto):
    catalog_version: Literal["reviewed-model-resource-fit-v3"]
    measurement_version: Literal["reviewed-runtime-configurations-2026-08-v3"]
    catalog_policy: Literal["exploratory_resource_fit_only"]
    content_free: Literal[True]
    session_data_read: Literal[False]
    cache_contents_read: Literal[False]
    downloads_started: Literal[False]
    activation_allowed: Literal[False]
    local_only: Literal[True]
    persisted: Literal[False]
    synced: Literal[False]
    inventory: ModelRuntimeInventoryDto
    models: tuple[ModelCompatibilityEntryDto, ...] = Field(
        min_length=1, max_length=32
    )


class ModelCompatibilityUnavailableDetailDto(HttpDto):
    code: Literal["model_compatibility_catalog_unavailable"]


class ModelCompatibilityUnavailableResponseDto(HttpDto):
    detail: ModelCompatibilityUnavailableDetailDto


class ModelEvaluationRequestDto(HttpDto):
    candidate: Literal[
        "all",
        "session-link",
        "e5",
        "e5-base",
        "nli",
        "bge-m3",
        "bge-reranker",
        "qwen-embedding",
        "qwen-reranker",
        "qwen-rubric",
    ] = "all"
    device: Literal["auto", "cpu", "cuda", "mps"] = "auto"
    mode: Literal["smoke", "full"] = "smoke"
    allow_download: bool = False


class CandidateEvaluationSummaryDto(HttpDto):
    key: Literal[
        "multilingual_e5_small",
        "multilingual_e5_base",
        "mdeberta_xnli",
        "bge_m3",
        "bge_reranker_v2_m3",
        "qwen3_embedding_06b",
        "qwen3_reranker_06b",
        "qwen3_4b_rubric",
    ]
    status: Literal["evaluated", "not_completed", "blocked_before_download"]
    error_code: Literal[
        "unsafe_pickle_only",
        "model_cache_missing_or_invalid",
        "batch_size_outside_manifest_bound",
        "cuda_unavailable",
        "mps_unavailable",
        "resource_exhausted",
        "evaluation_failed",
    ] | None = None
    primary_metric: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    primary_value: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    secondary_metric: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    secondary_value: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    critical_metric: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,63}$")
    critical_value: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    inference_latency_ms: float | None = Field(
        default=None, ge=0, le=86_400_000, allow_inf_nan=False
    )
    peak_accelerator_memory_mb: float | None = Field(
        default=None, ge=0, le=1_048_576, allow_inf_nan=False
    )


class ModelEvaluationJobDto(HttpDto):
    job_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    candidate: ModelEvaluationRequestDto
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    resolved_device: Literal["cpu", "cuda", "mps"] | None
    error_code: Literal[
        "candidate_evaluation_incomplete", "model_evaluation_failed",
        "application_shutdown", "model_evaluation_cleanup_unconfirmed"
    ] | None
    outcomes: tuple[CandidateEvaluationSummaryDto, ...] = Field(max_length=8)


def _source(value: ResearchSource) -> ResearchSourceDto:
    return ResearchSourceDto(
        key=value.key,
        title=value.title,
        url=value.url,
        kind=value.kind,
    )


def _method(value: AnalysisMethod) -> AnalysisMethodDto:
    return AnalysisMethodDto(
        key=value.key,
        name=value.name,
        family=value.family,
        approach=value.approach,
        maturity=value.maturity.value,
        privacy_tier=value.privacy_tier,
        purpose=value.purpose,
        produces=value.produces,
        candidate_model_keys=value.candidate_model_keys,
        source_keys=value.source_keys,
        limitations=value.limitations,
    )


def _benchmark(value: ModelBenchmark | None) -> ModelBenchmarkDto | None:
    if value is None:
        return None
    return ModelBenchmarkDto(
        benchmark_key=value.benchmark_key,
        case_count=value.case_count,
        primary_metric=value.primary_metric,
        primary_value=value.primary_value,
        secondary_metric=value.secondary_metric,
        secondary_value=value.secondary_value,
        critical_metric=value.critical_metric,
        critical_value=value.critical_value,
    )


def _candidate(value: ModelCandidate) -> ModelCandidateDto:
    return ModelCandidateDto(
        key=value.key,
        display_name=value.display_name,
        repository_id=value.repository_id,
        task=value.task,
        license_spdx=value.license_spdx,
        revision=value.revision,
        parameter_scale=value.parameter_scale,
        language_scope=value.language_scope,
        status=value.status.value,
        product_enabled=False,
        trust_remote_code=False,
        decision=value.decision,
        benchmark=_benchmark(value.benchmark),
        source_keys=value.source_keys,
    )


def _metric(value: MetricRoadmapItem) -> MetricRoadmapItemDto:
    return MetricRoadmapItemDto(
        key=value.key,
        name=value.name,
        profile=value.profile,
        question=value.question,
        direction=value.direction.value,
        state=value.state.value,
        evidence=value.evidence,
        method_keys=value.method_keys,
        caution=value.caution,
    )


def text_analysis_research_catalog() -> TextAnalysisResearchCatalogDto:
    return TextAnalysisResearchCatalogDto(
        catalog_key=CATALOG_KEY,
        catalog_version=CATALOG_VERSION,
        reviewed_on=date.fromisoformat(CATALOG_REVIEWED_ON),
        privacy_mode="local_only_redacted_content",
        summary_policy="multidimensional_profile_no_universal_score",
        catalog_read_starts_session_access=False,
        catalog_read_downloads_models=False,
        methods=tuple(_method(value) for value in METHODS),
        model_candidates=tuple(_candidate(value) for value in MODEL_CANDIDATES),
        metric_roadmap=tuple(_metric(value) for value in METRIC_ROADMAP),
        sources=tuple(_source(value) for value in SOURCES),
    )


def _runtime_dto(value: ModelRuntimeInventory) -> ModelRuntimeInventoryDto:
    return ModelRuntimeInventoryDto(
        preferred_device=value.preferred_device,
        cuda_state=value.cuda_state.value,
        cuda_available=value.cuda_available,
        mps_available=value.mps_available,
        cpu_available=value.cpu_available,
        cpu_architecture_bucket=value.cpu_architecture_bucket,
        logical_core_bucket=value.logical_core_bucket,
        system_ram_bucket=value.system_ram_bucket,
        cuda_vram_bucket=value.cuda_vram_bucket,
        cuda_capability_bucket=value.cuda_capability_bucket,
        model_cache_free_disk_bucket=value.model_cache_free_disk_bucket,
        discovery_reason_codes=tuple(
            reason.value for reason in value.discovery_reason_codes
        ),
        inventory_version=value.inventory_version,
        one_model_at_a_time=value.one_model_at_a_time,
        subprocess_isolation=value.subprocess_isolation,
        raw_session_data_accepted=value.raw_session_data_accepted,
        model_child_gpu_allocation_ceiling_mib=(
            value.model_child_gpu_allocation_ceiling_mib
        ),
        model_child_rss_ceiling_mib=value.model_child_rss_ceiling_mib,
        model_downloads_started=value.model_downloads_started,
        model_activation_allowed=value.model_activation_allowed,
        sensitivity=value.sensitivity,
        local_only=value.local_only,
        persisted=value.persisted,
        synced=value.synced,
    )


def _compatibility_entry_dto(
    value: ModelCompatibilityEntry,
) -> ModelCompatibilityEntryDto:
    return ModelCompatibilityEntryDto(
        configuration_key=value.configuration_key,
        model_key=value.model_key,
        repository_id=value.repository_id,
        revision=value.revision,
        task=value.task,
        role=value.role,
        language_scope=value.language_scope,
        license_spdx=value.license_spdx,
        status=value.status.value,
        reason_codes=tuple(reason.value for reason in value.reason_codes),
        quantization=value.quantization,
        dtype=value.dtype,
        runtime=value.runtime,
        measurement_method=value.measurement_method,
        measurement_precision=value.measurement_precision,
        measurement_source=value.measurement_source,
        resource_measurement_state=value.resource_measurement_state.value,
        observed_peak_gpu_allocation_mib=value.observed_peak_gpu_allocation_mib,
        observed_peak_child_rss_mib=value.observed_peak_child_rss_mib,
        benchmark_key=value.benchmark_key,
        synthetic_case_count=value.synthetic_case_count,
        trust_remote_code=value.trust_remote_code,
        product_enabled=value.product_enabled,
        activation_allowed=value.activation_allowed,
        download_allowed=value.download_allowed,
    )


def _compatibility_catalog_dto(
    value: ModelCompatibilityCatalog,
) -> ModelCompatibilityCatalogDto:
    return ModelCompatibilityCatalogDto(
        catalog_version=value.catalog_version,
        measurement_version=value.measurement_version,
        catalog_policy=value.catalog_policy,
        content_free=value.content_free,
        session_data_read=value.session_data_read,
        cache_contents_read=value.cache_contents_read,
        downloads_started=value.downloads_started,
        activation_allowed=value.activation_allowed,
        local_only=value.local_only,
        persisted=value.persisted,
        synced=value.synced,
        inventory=_runtime_dto(value.inventory),
        models=tuple(_compatibility_entry_dto(item) for item in value.models),
    )


def _outcome_dto(value: CandidateEvaluationSummary) -> CandidateEvaluationSummaryDto:
    return CandidateEvaluationSummaryDto(
        key=value.key,
        status=value.status,
        error_code=value.error_code,
        primary_metric=value.primary_metric,
        primary_value=value.primary_value,
        secondary_metric=value.secondary_metric,
        secondary_value=value.secondary_value,
        critical_metric=value.critical_metric,
        critical_value=value.critical_value,
        inference_latency_ms=value.inference_latency_ms,
        peak_accelerator_memory_mb=value.peak_accelerator_memory_mb,
    )


def _job_dto(value: ModelEvaluationJob) -> ModelEvaluationJobDto:
    request = value.request
    return ModelEvaluationJobDto(
        job_id=value.job_id,
        status=value.status,
        candidate=ModelEvaluationRequestDto(
            candidate=request.candidate,
            device=request.device,
            mode=request.mode,
            allow_download=request.allow_download,
        ),
        created_at=value.created_at,
        started_at=value.started_at,
        completed_at=value.completed_at,
        resolved_device=value.resolved_device,
        error_code=value.error_code,
        outcomes=tuple(_outcome_dto(item) for item in value.outcomes),
    )


def create_research_router(
    require_local_auth: Callable[..., None],
    model_evaluation_service: LocalTextModelEvaluationService | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix="/v1/research",
        tags=["research"],
        dependencies=[Depends(require_local_auth)],
    )

    @router.get(
        "/text-analysis-methods",
        response_model=TextAnalysisResearchCatalogDto,
    )
    def get_text_analysis_methods() -> TextAnalysisResearchCatalogDto:
        return text_analysis_research_catalog()

    if model_evaluation_service is not None:

        @router.get(
            "/text-model-runtime",
            response_model=ModelRuntimeInventoryDto,
        )
        def get_text_model_runtime() -> ModelRuntimeInventoryDto:
            return _runtime_dto(model_evaluation_service.inventory())

        @router.get(
            "/text-model-compatibility",
            response_model=ModelCompatibilityCatalogDto,
            responses={
                503: {"model": ModelCompatibilityUnavailableResponseDto}
            },
        )
        def get_text_model_compatibility(
            response: Response,
        ) -> ModelCompatibilityCatalogDto:
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["Pragma"] = "no-cache"
            try:
                return _compatibility_catalog_dto(
                    model_evaluation_service.compatibility_catalog()
                )
            except Exception:
                raise HTTPException(
                    status_code=503,
                    detail={
                        "code": "model_compatibility_catalog_unavailable"
                    },
                    headers={
                        "Cache-Control": "no-store, private",
                        "Pragma": "no-cache",
                    },
                ) from None

        @router.post(
            "/text-model-evaluations",
            response_model=ModelEvaluationJobDto,
            status_code=202,
        )
        def start_text_model_evaluation(
            body: ModelEvaluationRequestDto,
        ) -> ModelEvaluationJobDto:
            try:
                job = model_evaluation_service.start(
                    ModelEvaluationRequest(
                        candidate=body.candidate,
                        device=body.device,
                        mode=body.mode,
                        allow_download=body.allow_download,
                    )
                )
            except ModelEvaluationBusyError:
                raise HTTPException(
                    status_code=409,
                    detail="a local model evaluation is already running",
                ) from None
            except ModelEvaluationUnavailableError:
                raise HTTPException(
                    status_code=503,
                    detail={"code": "model_evaluation_unavailable"},
                ) from None
            return _job_dto(job)

        @router.get(
            "/text-model-evaluations/{job_id}",
            response_model=ModelEvaluationJobDto,
        )
        def get_text_model_evaluation(
            job_id: Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")],
        ) -> ModelEvaluationJobDto:
            try:
                return _job_dto(model_evaluation_service.get(job_id))
            except ModelEvaluationNotFoundError:
                raise HTTPException(
                    status_code=404,
                    detail="model evaluation not found",
                ) from None

    return router
