"""Authenticated, read-only routes for immutable session quality snapshots."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Protocol, cast

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
)

from ...application.analysis.metric_contract_v2 import (
    METRIC_CONTRACT_REGISTRY_VERSION_V2,
    metric_contract_v2_set_fingerprint,
)
from ...application.analysis.metric_guidance import (
    METRIC_GUIDANCE_CONTRACT_VERSION,
    METRIC_GUIDANCE_TEMPLATE_CATALOG_VERSION,
    METRIC_GUIDANCE_TEMPLATE_VERSION,
    MetricGuidanceCatalogEntry,
    metric_guidance_catalog,
)
from ...application.analysis.metric_operability import (
    MetricOperabilityCatalog,
    metric_operability_catalog,
)
from ...application.analysis.session_coaching_service import (
    SessionCoachingProjection,
    SessionCoachingProjectionError,
    SessionCoachingProjectionService,
)
from ...application.analysis.session_metric_publication_service import (
    SessionMetricPublication,
    SessionMetricPublicationError,
    SessionMetricPublicationService,
)
from ...application.persistence import SessionAnalysisRunRepository, TaskRepository
from ...domain import PSEUDONYM_PATTERN
from .dto import (
    HttpDto,
    SessionAnalysisResultDto,
    SessionAnalysisRunDto,
    SessionAnalysisRunListResponse,
    SessionAnalysisRunResponse,
)


_PRIVATE_HEADERS = {"Cache-Control": "no-store, private", "Pragma": "no-cache"}


class MetricGuidanceCatalogResponse(HttpDto):
    """Static guidance identities; no session, run, or provider data.

    The canonical contract identity travels with the catalog so a presentation
    surface that must keep prose locally can bind that prose to one exact
    registry fingerprint instead of drifting away from it silently.
    """

    catalog_version: str
    contract_version: str
    template_version: int
    registry_version: str
    contract_set_fingerprint: str
    entries: tuple[MetricGuidanceCatalogEntry, ...]


class SessionAnalysisQueryStore(Protocol):
    """Narrow factories needed by the qualitative read adapter."""

    def list_metric_definitions(self) -> list[dict[str, object]]: ...

    def session_analysis_run_repository(self) -> SessionAnalysisRunRepository: ...

    def task_repository(self) -> TaskRepository: ...


def _query_store(request: Request) -> SessionAnalysisQueryStore:
    return cast(SessionAnalysisQueryStore, request.app.state.database)


def _definition_index(
    store: SessionAnalysisQueryStore,
) -> dict[tuple[str, int], dict[str, object]]:
    definitions: dict[tuple[str, int], dict[str, object]] = {}
    for definition in store.list_metric_definitions():
        key = definition.get("key")
        version = definition.get("version")
        if isinstance(key, str) and isinstance(version, int) and not isinstance(version, bool):
            definitions[(key, version)] = definition
    return definitions


OBJECTIVE_EVIDENCE_ALGORITHM_ID = "typed-objective-evidence"
OBJECTIVE_EVIDENCE_ALGORITHM_VERSION = "typed-objective-evidence-v2"


def _overlay_objective_results(results, overrides):
    """Replace evidence-lane rows with their objective (decoder 4) values.

    Objective evidence outranks a rubric estimate for an objective contract;
    the row keeps its identity but carries the typed-evidence provenance so a
    reader can tell a measured fraction from a model judgment.
    """

    if not overrides:
        return results
    overlaid = []
    for result in results:
        override = overrides.get(result.observation.key)
        if override is None:
            overlaid.append(result)
            continue
        eligible = int(override.eligible_opportunity_count)
        observed = int(override.resolved_opportunity_count)
        known = override.numerator is not None and override.denominator is not None and override.denominator > 0
        observation = result.observation.model_copy(
            update={
                "numeric_value": (override.numerator / override.denominator) if known else None,
                "observed_count": observed,
                "eligible_count": eligible,
                "coverage": 0.0 if eligible == 0 else min(1.0, observed / eligible),
            }
        )
        overlaid.append(
            result.model_copy(
                update={
                    "observation": observation,
                    "value_state": override.value_state,
                    "fraction_numerator": override.numerator if known else None,
                    "fraction_denominator": override.denominator if known else None,
                    "explanation_code": override.explanation_code,
                    "error_code": None,
                    "evidence": (),
                    "signals": (),
                    "algorithm_id": OBJECTIVE_EVIDENCE_ALGORITHM_ID,
                    "algorithm_version": OBJECTIVE_EVIDENCE_ALGORITHM_VERSION,
                    "model_id": None,
                    "model_revision": None,
                    "model_license": None,
                    "tokenizer_id": None,
                    "prompt_version": None,
                }
            )
        )
    return tuple(overlaid)


def _detail_response(
    store: SessionAnalysisQueryStore,
    run_id: str,
    objective_overrides=None,
) -> SessionAnalysisRunResponse:
    repository = store.session_analysis_run_repository()
    run = repository.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="quality analysis run not found")
    definitions = _definition_index(store)
    results = repository.get_results(run_id)
    if objective_overrides is not None:
        try:
            overrides = objective_overrides(run.draft.provider, run.draft.session_id)
        except Exception:
            overrides = None
        results = _overlay_objective_results(results, overrides)
    return SessionAnalysisRunResponse(
        run=SessionAnalysisRunDto.from_record(run),
        results=tuple(
            SessionAnalysisResultDto.from_record(
                result,
                definition=definitions.get(
                    (result.observation.key, result.observation.version)
                ),
            )
            for result in results
        ),
    )


def create_session_analysis_query_router(
    require_local_token: Callable[..., None],
    objective_overrides: Callable[..., object] | None = None,
) -> APIRouter:
    """Expose list/latest/detail without initiating a provider read or analysis."""

    router = APIRouter(
        prefix="/v1",
        tags=["session-quality-analysis"],
        dependencies=[Depends(require_local_token)],
    )

    @router.get(
        "/sessions/{session_id}/quality-analysis-runs",
        response_model=SessionAnalysisRunListResponse,
    )
    def session_analysis_run_list(
        request: Request,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> SessionAnalysisRunListResponse:
        records = _query_store(request).session_analysis_run_repository().list_for_session(
            session_id,
            limit=limit,
            offset=offset,
        )
        return SessionAnalysisRunListResponse(
            session_id=session_id,
            runs=tuple(SessionAnalysisRunDto.from_record(item) for item in records),
            limit=limit,
            offset=offset,
        )

    @router.get(
        "/sessions/{session_id}/quality-analysis-runs/latest",
        response_model=SessionAnalysisRunResponse,
    )
    def latest_session_analysis_run(
        request: Request,
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> SessionAnalysisRunResponse:
        store = _query_store(request)
        run = store.session_analysis_run_repository().get_latest_completed(session_id)
        if run is None:
            raise HTTPException(
                status_code=404, detail="completed quality analysis run not found"
            )
        return _detail_response(store, run.draft.run_id, objective_overrides)

    @router.get(
        "/quality-analysis/runs/{run_id}",
        response_model=SessionAnalysisRunResponse,
    )
    def session_analysis_run_detail(
        request: Request,
        run_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> SessionAnalysisRunResponse:
        return _detail_response(_query_store(request), run_id, objective_overrides)

    @router.get(
        "/quality-analysis/runs/{run_id}/coaching-summary",
        response_model=SessionCoachingProjection,
    )
    def session_coaching_summary(
        request: Request,
        run_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> SessionCoachingProjection:
        """Project stored results only; never initiate a provider content read."""

        store = _query_store(request)
        service = SessionCoachingProjectionService(
            store.session_analysis_run_repository(),
            store.task_repository(),
        )
        try:
            projection = service.get(run_id)
        except SessionCoachingProjectionError as exc:
            messages = {
                "coaching_run_not_completed": "completed coaching analysis required",
                "coaching_pack_unsupported": "compatible coaching analysis required",
            }
            raise HTTPException(
                status_code=409,
                detail=messages.get(exc.code, "coaching summary unavailable"),
            ) from None
        if projection is None:
            raise HTTPException(status_code=404, detail="quality analysis run not found")
        return projection

    @router.get(
        "/metric-contracts/v2/guidance-catalog",
        response_model=MetricGuidanceCatalogResponse,
    )
    def metric_guidance_catalog_route(
        response: Response,
    ) -> MetricGuidanceCatalogResponse:
        """Serve the static guidance identities the dashboard and overlay share."""

        response.headers.update(_PRIVATE_HEADERS)
        return MetricGuidanceCatalogResponse(
            catalog_version=METRIC_GUIDANCE_TEMPLATE_CATALOG_VERSION,
            contract_version=METRIC_GUIDANCE_CONTRACT_VERSION,
            template_version=METRIC_GUIDANCE_TEMPLATE_VERSION,
            registry_version=METRIC_CONTRACT_REGISTRY_VERSION_V2,
            contract_set_fingerprint=metric_contract_v2_set_fingerprint(),
            entries=metric_guidance_catalog(),
        )

    @router.get(
        "/metric-contracts/v2/operability-catalog",
        response_model=MetricOperabilityCatalog,
    )
    def metric_operability_catalog_route(
        response: Response,
    ) -> MetricOperabilityCatalog:
        """Expose the current all-twenty measurement-path release gate.

        This static response never describes whether a particular session has
        evidence.  It only identifies which reviewed local authority could
        resolve each metric, the still-missing adapter/configuration seam, and
        whether an experimental model path exists without measurement power.
        """

        response.headers.update(_PRIVATE_HEADERS)
        return metric_operability_catalog()

    @router.get(
        "/quality-analysis/runs/{run_id}/metric-v2-compatibility-preview",
        response_model=SessionMetricPublication,
    )
    def session_metric_publication(
        request: Request,
        response: Response,
        run_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> SessionMetricPublication:
        """Read-only V1 compatibility preview; not the canonical live snapshot."""

        response.headers.update(_PRIVATE_HEADERS)
        store = _query_store(request)
        service = SessionMetricPublicationService(
            store.session_analysis_run_repository(),
            objective_overrides=objective_overrides,  # type: ignore[arg-type]
        )
        try:
            projection = service.get(run_id)
        except SessionMetricPublicationError as exc:
            messages = {
                "publication_run_not_completed": (
                    "completed quality analysis required"
                ),
                "publication_pack_unsupported": (
                    "compatible coaching analysis required"
                ),
            }
            raise HTTPException(
                status_code=409,
                detail=messages.get(exc.code, "metric publication unavailable"),
            ) from None
        if projection is None:
            raise HTTPException(status_code=404, detail="quality analysis run not found")
        return projection

    return router
