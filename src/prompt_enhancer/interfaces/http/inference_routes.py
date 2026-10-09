"""Authenticated inference surfaces, separate from local runtime management."""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from ...domain import StrictModel
from ...application.inference import InferenceCatalog, InferenceError, InferenceStream
from ...application.inference_review import InferencePreview, PendingInferenceReview, ReviewedInference
from ...application.manual_analysis import ManualAnalysisRequest, ManualAnalysisResult, manual_body, analyze_manual
from .inference_stream import InferenceRelayResponse


class ChatMessage(StrictModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=28_000, repr=False)


class InferenceChatRequest(StrictModel):
    model_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    messages: tuple[ChatMessage, ...] = Field(min_length=1, max_length=80, repr=False)
    max_tokens: int = Field(default=1100, ge=1, le=4096)
    temperature: float = Field(default=.2, ge=0, le=2)
    approval: str | None = Field(default=None, max_length=100, repr=False)

    def body(self) -> bytes:
        return json.dumps({"messages": [item.model_dump() for item in self.messages],
            "max_tokens": self.max_tokens, "temperature": self.temperature,
            "stream": True, "stream_options": {"include_usage": True}}).encode()


class InferenceReviewDecision(StrictModel):
    accepted: bool


def failure(error: InferenceError) -> HTTPException:
    status = {"inference_preview_required": 428, "inference_model_not_found": 404,
        "inference_review_not_found": 404, "model_not_active": 409, "model_error": 502, "model_reply_invalid": 502}.get(error.code, 422)
    return HTTPException(status, detail={"code": error.code})


def create_inference_router(require_auth: Callable, service: ReviewedInference) -> APIRouter:
    router = APIRouter(prefix="/v1/inference", tags=["inference"], dependencies=[Depends(require_auth)])

    @router.get("/models", response_model=InferenceCatalog)
    def models():
        try:
            return service.registry.catalog()
        except InferenceError as error:
            raise failure(error) from None

    @router.post("/chat/preview", response_model=InferencePreview)
    def preview(request: InferenceChatRequest):
        try:
            return service.preview(request.model_id, request.body(), "chat")
        except InferenceError as error:
            raise failure(error) from None

    @router.post("/chat")
    def chat(request: InferenceChatRequest):
        try:
            body = service.approved_body(request.model_id, request.body(), "chat", request.approval)
            provider, _ = service.registry.resolve(request.model_id)
        except InferenceError as error:
            raise failure(error) from None
        return InferenceRelayResponse(lambda: provider.open_chat(request.model_id, body),
            errors=(InferenceError,), error_response=failure)

    @router.post("/analysis/preview", response_model=InferencePreview)
    def preview_analysis(request: ManualAnalysisRequest):
        try:
            return service.preview(request.model_id, manual_body(request), "manual-" + request.kind)
        except InferenceError as error:
            raise failure(error) from None

    @router.post("/analysis", response_model=ManualAnalysisResult)
    def analyze(request: ManualAnalysisRequest):
        def complete():
            result = analyze_manual(service, request)
            return InferenceStream(200, "application/json", result.model_dump_json().encode())
        # The same request owner cancels a complete response on disconnect,
        # including while the remote provider is still preparing its headers.
        return InferenceRelayResponse(complete, errors=(InferenceError,), error_response=failure)

    @router.get("/agent/{session_id}/reviews", response_model=tuple[PendingInferenceReview, ...])
    def pending(session_id: str):
        return service.pending(session_id)

    @router.post("/agent/{session_id}/reviews/{review_id}", status_code=204)
    def decide(session_id: str, review_id: str, request: InferenceReviewDecision):
        try:
            service.decide(session_id, review_id, accepted=request.accepted)
        except InferenceError as error:
            raise failure(error) from None

    return router
