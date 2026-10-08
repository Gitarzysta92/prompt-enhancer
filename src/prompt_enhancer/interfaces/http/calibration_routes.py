"""Blind calibration ratings over the owner's own sessions (local only)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ...application.analysis.calibration_cases import CalibrationReview, CalibrationReviewError, CalibrationReviewRequest

from ...application.analysis.calibration_ratings import (
    CalibrationExport,
    CalibrationProgress,
    CalibrationRating,
    CalibrationRatingService,
    CalibrationSample,
    CalibrationSampleEmptyError,
    CalibrationSessionNotSampledError,
    RatingSubmission,
)


def create_calibration_router(
    require_local_auth: Callable[..., None],
    service: CalibrationRatingService,
) -> APIRouter:
    router = APIRouter(
        prefix="/v1/calibration",
        tags=["calibration"],
        dependencies=[Depends(require_local_auth)],
    )

    def review_error(error: CalibrationReviewError) -> HTTPException:
        status = 403 if error.code in {"calibration_review_disabled", "calibration_review_consent_required"} else 409
        return HTTPException(status_code=status, detail={"code": error.code, "message": "The reviewed case could not be confirmed. Review the evidence again before saving."})

    @router.post("/review", response_model=CalibrationReview)
    def review(payload: CalibrationReviewRequest, response: Response) -> CalibrationReview:
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["Pragma"] = "no-cache"
        try:
            return service.review(payload.session_id, payload.window_characters)
        except CalibrationReviewError as error:
            raise review_error(error) from None
        except CalibrationSessionNotSampledError:
            raise HTTPException(status_code=422, detail={"code": "session_not_sampled", "message": "session is not part of the calibration sample"}) from None
        except CalibrationSampleEmptyError:
            raise HTTPException(status_code=409, detail={"code": "calibration_sample_empty", "message": "no indexed session to sample yet"}) from None

    @router.get("/sample", response_model=CalibrationSample)
    def sample(
        rater_label: Annotated[str | None, Query(min_length=1, max_length=80)] = None,
    ) -> CalibrationSample:
        try:
            return service.sample(rater_label=rater_label)
        except CalibrationSampleEmptyError:
            raise HTTPException(
                status_code=409,
                detail={"code": "calibration_sample_empty", "message": "no indexed session to sample yet"},
            ) from None

    @router.put("/ratings", response_model=CalibrationProgress)
    def rate(payload: RatingSubmission) -> CalibrationProgress:
        try:
            return service.rate(payload)
        except CalibrationReviewError as error:
            raise review_error(error) from None
        except CalibrationSessionNotSampledError:
            raise HTTPException(
                status_code=422,
                detail={"code": "session_not_sampled", "message": "session is not part of the calibration sample"},
            ) from None
        except CalibrationSampleEmptyError:
            raise HTTPException(
                status_code=409,
                detail={"code": "calibration_sample_empty", "message": "no indexed session to sample yet"},
            ) from None

    @router.get("/ratings", response_model=tuple[CalibrationRating, ...])
    def ratings(
        rater_label: Annotated[str, Query(min_length=1, max_length=80)],
    ) -> tuple[CalibrationRating, ...]:
        return service.ratings_for(rater_label)

    @router.get("/progress", response_model=CalibrationProgress)
    def progress() -> CalibrationProgress:
        return service.progress()

    @router.get("/export", response_model=CalibrationExport)
    def export() -> CalibrationExport:
        return service.export()

    return router


__all__ = ("create_calibration_router",)
