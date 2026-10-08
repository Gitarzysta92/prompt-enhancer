"""Authenticated local-only commands for private display-label overrides."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import Field, SecretStr

from ...application.display_labels import (
    DisplayLabelConflictError,
    DisplayLabelNotFoundError,
    InvalidDisplayLabelError,
    LabelEntityKind,
    ManualDisplayLabelResult,
    ManualDisplayLabelService,
)
from ...domain import PSEUDONYM_PATTERN, StrictModel


class ManualDisplayLabelRequest(StrictModel):
    value: SecretStr
    expected_revision: int = Field(ge=0)


PseudonymPath = Annotated[
    str,
    Path(pattern=PSEUDONYM_PATTERN.pattern),
]


def create_display_label_router(
    require_local_auth: Callable[..., None],
    service: ManualDisplayLabelService,
) -> APIRouter:
    router = APIRouter(
        prefix="/v1/catalog",
        tags=["display-labels"],
        dependencies=[Depends(require_local_auth)],
    )

    def set_label(
        entity_kind: LabelEntityKind,
        entity_id: str,
        payload: ManualDisplayLabelRequest,
    ) -> ManualDisplayLabelResult:
        try:
            return service.set(
                entity_kind=entity_kind,
                entity_id=entity_id,
                value=payload.value,
                expected_revision=payload.expected_revision,
            )
        except InvalidDisplayLabelError:
            raise HTTPException(
                status_code=422, detail="local display label is invalid"
            ) from None
        except DisplayLabelConflictError:
            raise HTTPException(
                status_code=409, detail="local display label revision changed"
            ) from None
        except DisplayLabelNotFoundError:
            raise HTTPException(
                status_code=404, detail="local display label target was not found"
            ) from None

    def clear_label(
        entity_kind: LabelEntityKind,
        entity_id: str,
        expected_revision: int,
    ) -> ManualDisplayLabelResult:
        try:
            return service.clear(
                entity_kind=entity_kind,
                entity_id=entity_id,
                expected_revision=expected_revision,
            )
        except DisplayLabelConflictError:
            raise HTTPException(
                status_code=409, detail="local display label revision changed"
            ) from None
        except DisplayLabelNotFoundError:
            raise HTTPException(
                status_code=404, detail="local display label target was not found"
            ) from None

    @router.put("/projects/{project_id}/display-label")
    def set_project_label(
        project_id: PseudonymPath,
        payload: ManualDisplayLabelRequest,
    ) -> ManualDisplayLabelResult:
        return set_label(LabelEntityKind.PROJECT, project_id, payload)

    @router.delete("/projects/{project_id}/display-label")
    def clear_project_label(
        project_id: PseudonymPath,
        expected_revision: Annotated[int, Query(ge=0)],
    ) -> ManualDisplayLabelResult:
        return clear_label(
            LabelEntityKind.PROJECT, project_id, expected_revision
        )

    @router.put("/sessions/{session_id}/display-label")
    def set_session_label(
        session_id: PseudonymPath,
        payload: ManualDisplayLabelRequest,
    ) -> ManualDisplayLabelResult:
        return set_label(LabelEntityKind.SESSION, session_id, payload)

    @router.delete("/sessions/{session_id}/display-label")
    def clear_session_label(
        session_id: PseudonymPath,
        expected_revision: Annotated[int, Query(ge=0)],
    ) -> ManualDisplayLabelResult:
        return clear_label(
            LabelEntityKind.SESSION, session_id, expected_revision
        )

    return router
