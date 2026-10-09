"""Model-judge lane: judge one session, sweep the calibration sample, agreement."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from ...application.analysis.calibration_ratings import CalibrationSampleEmptyError
from ...application.analysis.model_judge import (
    JudgeAgreementReport,
    JudgeOutcome,
    JudgeSweepStatus,
    MODEL_JUDGE_CATALOG_UNAVAILABLE,
    ModelJudgeError,
    ModelJudgeService,
    SessionInterpretation,
    SessionJudgments,
)
from ...domain import PSEUDONYM_PATTERN, StrictModel
from pydantic import Field
from ...application.inference import InferenceError
from ...application.inference_review import (
    InferencePreview, InferenceReviewRequired, InferenceSelection, inference_selection,
)
from .inference_routes import failure as inference_failure


class SelectedJudgeModel(StrictModel):
    model_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    approval: str | None = Field(default=None, max_length=100, repr=False)


class JudgePreviewRequest(SelectedJudgeModel):
    kind: Literal["judge", "interpret"]


class ModelJudgeFailureCode(StrEnum):
    NO_ACTIVE_MODEL = "no_active_model"
    SESSION_NOT_FOUND = "session_not_found"
    CONSENT_REQUIRED = "consent_required"
    WINDOW_UNAVAILABLE = "window_unavailable"
    MODEL_UNREACHABLE = "model_unreachable"
    MODEL_NOT_ACTIVE = "model_not_active"
    MODEL_ERROR = "model_error"
    MODEL_REPLY_INVALID = "model_reply_invalid"
    CATALOG_UNAVAILABLE = MODEL_JUDGE_CATALOG_UNAVAILABLE


class ModelJudgeFailureDetail(StrictModel):
    code: ModelJudgeFailureCode


class ModelJudgeFailureResponse(StrictModel):
    detail: ModelJudgeFailureDetail


_STATUS: dict[ModelJudgeFailureCode, int] = {
    ModelJudgeFailureCode.NO_ACTIVE_MODEL: 409,
    ModelJudgeFailureCode.SESSION_NOT_FOUND: 404,
    ModelJudgeFailureCode.CONSENT_REQUIRED: 403,
    ModelJudgeFailureCode.WINDOW_UNAVAILABLE: 409,
    ModelJudgeFailureCode.MODEL_UNREACHABLE: 502,
    ModelJudgeFailureCode.MODEL_NOT_ACTIVE: 409,
    ModelJudgeFailureCode.MODEL_ERROR: 502,
    ModelJudgeFailureCode.MODEL_REPLY_INVALID: 502,
    ModelJudgeFailureCode.CATALOG_UNAVAILABLE: 503,
}

_PUBLIC_CODE_ALIASES = {
    "runtime_unreachable": ModelJudgeFailureCode.MODEL_UNREACHABLE,
}


def _failure(error_code: object) -> HTTPException:
    code = ModelJudgeFailureCode.MODEL_ERROR
    if isinstance(error_code, str):
        code = _PUBLIC_CODE_ALIASES.get(error_code, code)
        try:
            code = ModelJudgeFailureCode(error_code)
        except ValueError:
            pass
    detail = ModelJudgeFailureDetail(code=code)
    return HTTPException(
        status_code=_STATUS[code],
        detail=detail.model_dump(mode="json"),
    )


def create_model_judge_router(
    require_local_auth: Callable[..., None],
    service: ModelJudgeService,
    sample_session_ids: Callable[[], tuple[str, ...]],
    all_session_ids: Callable[[], tuple[str, ...]] | None = None,
    *, inference=None,
) -> APIRouter:
    router = APIRouter(
        prefix="/v1/model-judge",
        tags=["model-judge"],
        dependencies=[Depends(require_local_auth)],
    )

    def selected_call(session_id, kind, payload, *, preview=False):
        operation = service.interpret if kind == "interpret" else service.judge
        if payload is None:
            return operation(session_id)
        if inference is None:
            raise HTTPException(409, detail={"code": "inference_unavailable"})
        with inference_selection(InferenceSelection(payload.model_id,
                f"session-{kind}:{session_id}", payload.approval, preview)):
            try:
                return operation(session_id)
            except InferenceError as error:
                raise inference_failure(error) from None

    @router.post("/sessions/{session_id}/preview", response_model=InferencePreview)
    def preview_selected_model(
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        payload: JudgePreviewRequest,
    ):
        try:
            selected_call(session_id, payload.kind, payload, preview=True)
        except InferenceReviewRequired as review:
            return review.preview
        except ModelJudgeError as error:
            raise _failure(error.code) from None
        raise HTTPException(409, detail={"code": "inference_preview_unavailable"})

    def session_ids(scope: Literal["sample", "all"]) -> tuple[str, ...]:
        if scope == "all":
            if all_session_ids is None:
                raise ModelJudgeError(MODEL_JUDGE_CATALOG_UNAVAILABLE)
            supplier = all_session_ids
        else:
            supplier = sample_session_ids
        sample_empty = False
        supplier_failed = False
        try:
            values = tuple(supplier())
        except CalibrationSampleEmptyError:
            sample_empty = True
            values = ()
        except Exception:
            supplier_failed = True
            values = ()
        if supplier_failed or (sample_empty and scope == "all"):
            raise ModelJudgeError(MODEL_JUDGE_CATALOG_UNAVAILABLE)
        if sample_empty:
            return ()
        if any(
            not isinstance(session_id, str)
            or PSEUDONYM_PATTERN.fullmatch(session_id) is None
            for session_id in values
        ) or len(set(values)) != len(values):
            raise ModelJudgeError(MODEL_JUDGE_CATALOG_UNAVAILABLE)
        return values

    @router.get(
        "/sessions/{session_id}",
        response_model=SessionJudgments,
        responses={503: {"model": ModelJudgeFailureResponse}},
    )
    def session_judgments(
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
    ) -> SessionJudgments:
        try:
            return service.judgments_for(session_id)
        except ModelJudgeError as error:
            failure_code = error.code
        raise _failure(failure_code)

    @router.post(
        "/sessions/{session_id}/interpret",
        response_model=SessionInterpretation,
        responses={
            status: {"model": ModelJudgeFailureResponse}
            for status in (403, 404, 409, 502, 503)
        },
    )
    def interpret_session(
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        payload: SelectedJudgeModel | None = None,
    ) -> SessionInterpretation:
        try:
            result = selected_call(session_id, "interpret", payload)
            if payload is not None and inference is not None:
                _, model = inference.registry.resolve(payload.model_id)
                if model.remote:
                    result = result.model_copy(update={"caveat": "Interpretation from the reviewed text and metrics via " + model.provider + "; not a measurement.",
                        "inference_provider": model.provider, "model_revision": model.revision,
                        "adapter_version": model.adapter_version, "redactor_version": inference.redactor_version})
            return result
        except ModelJudgeError as error:
            failure_code = error.code
        raise _failure(failure_code)

    @router.post(
        "/sessions/{session_id}",
        response_model=JudgeOutcome,
        responses={
            status: {"model": ModelJudgeFailureResponse}
            for status in (403, 404, 409, 502, 503)
        },
    )
    def judge_session(
        session_id: Annotated[str, Path(pattern=PSEUDONYM_PATTERN.pattern)],
        payload: SelectedJudgeModel | None = None,
    ) -> JudgeOutcome:
        try:
            return selected_call(session_id, "judge", payload)
        except ModelJudgeError as error:
            failure_code = error.code
        raise _failure(failure_code)

    @router.post(
        "/sweep",
        response_model=JudgeSweepStatus,
        responses={
            status: {"model": ModelJudgeFailureResponse}
            for status in (409, 503)
        },
    )
    def sweep(
        scope: Annotated[Literal["sample", "all"], Query()] = "sample",
    ) -> JudgeSweepStatus:
        """Judge the sample or every indexed session with the active model."""

        try:
            return service.start_sweep(session_ids(scope))
        except ModelJudgeError as error:
            failure_code = error.code
        raise _failure(failure_code)

    @router.get("/sweep", response_model=JudgeSweepStatus)
    def sweep_status() -> JudgeSweepStatus:
        return service.sweep_status()

    @router.get(
        "/agreement",
        response_model=JudgeAgreementReport,
        responses={503: {"model": ModelJudgeFailureResponse}},
    )
    def agreement() -> JudgeAgreementReport:
        try:
            return service.agreement()
        except ModelJudgeError as error:
            failure_code = error.code
        raise _failure(failure_code)

    return router


__all__ = (
    "ModelJudgeFailureCode",
    "ModelJudgeFailureDetail",
    "ModelJudgeFailureResponse",
    "create_model_judge_router",
)
