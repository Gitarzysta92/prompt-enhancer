"""Authenticated, query-only task and analysis HTTP routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Protocol, cast

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from ...application.persistence import (
    AnalysisRunRepository,
    CandidateDecisionStatus,
    TaskRepository,
)
from ...domain import PSEUDONYM_PATTERN
from .dto import (
    AnalysisResultDto,
    AnalysisRunDto,
    AnalysisRunListResponse,
    AnalysisRunResponse,
    CandidateDecisionsResponse,
    CandidateListItemDto,
    CandidateListResponse,
    CandidateResponse,
    TaskCandidateDto,
    TaskDecisionDto,
    TaskRevisionDto,
    TaskRevisionListResponse,
    TaskRevisionResponse,
)


class QueryStore(Protocol):
    """Only repository factories needed by this HTTP query adapter."""

    def list_metric_definitions(self) -> list[dict[str, object]]: ...

    def task_repository(self) -> TaskRepository: ...

    def analysis_run_repository(self) -> AnalysisRunRepository: ...


def _query_store(request: Request) -> QueryStore:
    # The composition root owns the concrete store. This cast adds no dynamic
    # lookup and keeps SQL/storage types out of the HTTP interface.
    return cast(QueryStore, request.app.state.database)


def _metric_definition_index(
    store: QueryStore,
) -> dict[tuple[str, int], dict[str, object]]:
    definitions: dict[tuple[str, int], dict[str, object]] = {}
    for definition in store.list_metric_definitions():
        key = definition.get("key")
        version = definition.get("version")
        if (
            isinstance(key, str)
            and isinstance(version, int)
            and not isinstance(version, bool)
        ):
            definitions[(key, version)] = definition
    return definitions


def _with_names(store, candidate: TaskCandidateDto) -> TaskCandidateDto:
    """Attach catalog display labels (first session) when the store has them."""

    getter = getattr(store, "get_session", None)
    if not callable(getter) or not candidate.session_ids:
        return candidate
    try:
        session = getter(candidate.session_ids[0])
    except Exception:
        return candidate
    if session is None:
        return candidate
    return candidate.model_copy(
        update={
            "project_display_name": getattr(session, "project_display_name", None),
            "session_display_name": getattr(session, "session_display_name", None),
        }
    )


def create_task_query_router(
    require_local_token: Callable[..., None],
) -> APIRouter:
    """Create a router with the API's existing local-auth dependency."""

    router = APIRouter(
        prefix="/v1",
        tags=["task-discovery"],
        dependencies=[Depends(require_local_token)],
    )

    @router.get(
        "/discovery/candidates",
        response_model=CandidateListResponse,
    )
    def candidate_inbox(
        request: Request,
        status: Annotated[CandidateDecisionStatus | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> CandidateListResponse:
        store = _query_store(request)
        records = store.task_repository().list_candidates(
            status=status,
            limit=limit,
            offset=offset,
        )
        items = []
        for item in records:
            dto = CandidateListItemDto.from_record(item)
            items.append(dto.model_copy(update={"candidate": _with_names(store, dto.candidate)}))
        return CandidateListResponse(
            candidates=tuple(items),
            limit=limit,
            offset=offset,
        )

    @router.get(
        "/discovery/candidates/{candidate_id}",
        response_model=CandidateResponse,
    )
    def candidate_detail(
        request: Request,
        candidate_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> CandidateResponse:
        record = _query_store(request).task_repository().get_candidate(candidate_id)
        if record is None:
            raise HTTPException(status_code=404, detail="candidate not found")
        return CandidateResponse(candidate=_with_names(_query_store(request), TaskCandidateDto.from_record(record)))

    @router.get(
        "/discovery/candidates/{candidate_id}/decisions",
        response_model=CandidateDecisionsResponse,
    )
    def candidate_decisions(
        request: Request,
        candidate_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> CandidateDecisionsResponse:
        repository = _query_store(request).task_repository()
        if repository.get_candidate(candidate_id) is None:
            raise HTTPException(status_code=404, detail="candidate not found")
        decisions = repository.list_decisions(candidate_id)
        return CandidateDecisionsResponse(
            candidate_id=candidate_id,
            decisions=tuple(TaskDecisionDto.from_record(item) for item in decisions),
        )

    @router.get(
        "/task-revisions",
        response_model=TaskRevisionListResponse,
    )
    def task_revision_list(
        request: Request,
        task_id: Annotated[
            str | None,
            Query(pattern=PSEUDONYM_PATTERN.pattern),
        ] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> TaskRevisionListResponse:
        records = _query_store(request).task_repository().list_task_revisions(
            task_id=task_id,
            limit=limit,
            offset=offset,
        )
        return TaskRevisionListResponse(
            tasks=tuple(TaskRevisionDto.from_record(item) for item in records),
            limit=limit,
            offset=offset,
        )

    @router.get(
        "/tasks/{task_id}/revisions/{revision}",
        response_model=TaskRevisionResponse,
    )
    def task_revision_detail(
        request: Request,
        task_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        revision: Annotated[int, Path(ge=1)],
    ) -> TaskRevisionResponse:
        record = _query_store(request).task_repository().get_revision(task_id, revision)
        if record is None:
            raise HTTPException(status_code=404, detail="task revision not found")
        return TaskRevisionResponse(task=TaskRevisionDto.from_record(record))

    @router.get(
        "/analysis/runs",
        response_model=AnalysisRunListResponse,
    )
    def analysis_run_list(
        request: Request,
        task_id: Annotated[
            str | None,
            Query(pattern=PSEUDONYM_PATTERN.pattern),
        ] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> AnalysisRunListResponse:
        records = _query_store(request).analysis_run_repository().list_analysis_runs(
            task_id=task_id,
            limit=limit,
            offset=offset,
        )
        return AnalysisRunListResponse(
            runs=tuple(AnalysisRunDto.from_record(item) for item in records),
            limit=limit,
            offset=offset,
        )

    @router.get(
        "/analysis/runs/{run_id}",
        response_model=AnalysisRunResponse,
    )
    def analysis_run_detail(
        request: Request,
        run_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> AnalysisRunResponse:
        repository = _query_store(request).analysis_run_repository()
        run = repository.get(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="analysis run not found")
        results = repository.get_results(run_id)
        definitions = _metric_definition_index(_query_store(request))
        return AnalysisRunResponse(
            run=AnalysisRunDto.from_record(run),
            results=tuple(
                AnalysisResultDto.from_record(
                    item,
                    definition=definitions.get(
                        (item.observation.key, item.observation.version)
                    ),
                )
                for item in results
            ),
        )

    return router
