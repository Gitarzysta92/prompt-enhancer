"""Ephemeral analysis of explicitly supplied text; no session ingestion or storage."""
from __future__ import annotations
import json
from typing import Literal
from pydantic import Field
from ..domain import StrictModel
from .inference import InferenceError, InferenceModel
from .inference_review import ReviewedInference
from .model_reply import completed_chat_content, model_json_object
from .analysis.model_judge import _InterpretationReply, _INTERPRET_SYSTEM_PROMPT, _SYSTEM_PROMPT, parse_judge_reply

class ManualAnalysisRequest(StrictModel):
    model_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    kind: Literal["interpret", "judge"]
    text: str = Field(min_length=1, max_length=28_000, repr=False)
    approval: str | None = Field(default=None, max_length=100, repr=False)


class ManualAnalysisResult(StrictModel):
    model: InferenceModel
    kind: Literal["interpret", "judge"]
    result: dict = Field(repr=False)
    prompt_version: Literal["manual-analysis.v1"] = "manual-analysis.v1"
    redactor_version: str
    persisted: Literal[False] = False


def manual_body(request: ManualAnalysisRequest) -> bytes:
    # Explicitly supplied text is ephemeral: no ingestion, session reads, or
    # database writes. Generated judgments never become objective metrics.
    window = json.dumps({"authority": "untrusted_evidence", "records": [
        {"role": "user", "content": request.text}]})
    body = {"messages": [
        {"role": "system", "content": _INTERPRET_SYSTEM_PROMPT if request.kind == "interpret" else _SYSTEM_PROMPT},
        {"role": "user", "content": "No objective metrics supplied; metric values are unknown.\nUNTRUSTED_TRANSCRIPT_JSON=" + window},
    ], "temperature": .2, "max_tokens": 1100}
    if request.kind == "interpret":
        body["response_format"] = {"type": "json_schema", "json_schema": {
            "name": "session_interpretation", "schema": _InterpretationReply.model_json_schema()}}
    else:
        body["response_format"] = {"type": "json_object"}
    return json.dumps(body).encode()


def analyze_manual(service: ReviewedInference, request: ManualAnalysisRequest) -> ManualAnalysisResult:
    status, payload, _ = service.complete(request.model_id, manual_body(request),
        "manual-" + request.kind, approval=request.approval)
    _, model = service.registry.resolve(request.model_id)
    if status != 200:
        raise InferenceError("model_error")
    text = completed_chat_content(payload)
    if request.kind == "judge":
        data = parse_judge_reply(text or "")
    else:
        value = model_json_object(text, max_characters=12_000)
        try:
            reading = _InterpretationReply.model_validate(value, strict=True)
            data = reading.model_dump() if any((reading.summary, reading.strengths,
                reading.improvements, reading.reframed_prompt)) else None
        except ValueError:
            data = None
    if not data:
        raise InferenceError("model_reply_invalid")
    return ManualAnalysisResult(model=model, kind=request.kind, result=data,
        redactor_version=service.redactor_version)
