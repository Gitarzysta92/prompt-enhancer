"""Compatibility adapter from owned local runtimes to the inference port."""
from __future__ import annotations

from ..application.inference import InferenceError, InferenceModel, InferenceStream
from ..application.local_models import LocalModelError, LocalModelService, RuntimeState


class LocalInferenceProvider:
    provider_id = "local"
    def __init__(self, runtime: LocalModelService):
        self._runtime = runtime

    def models(self) -> tuple[InferenceModel, ...]:
        return tuple(InferenceModel(
            id=item.record.alias, name=item.record.display_name, provider="local", remote=False,
            available=item.runtime.state is RuntimeState.RUNNING,
            availability="running" if item.runtime.state is RuntimeState.RUNNING else "stopped",
            revision=item.record.source_revision if item.record.provenance_verified else None,
            license=item.record.source_license if item.record.provenance_verified else None,
            adapter_version="local-inference.v1", tools=item.runtime.tool_calling,
            context_tokens=item.runtime.context_size,
        ) for item in self._runtime.overview().models)

    def complete(self, model_id: str, body: bytes) -> tuple[int, bytes, str]:
        try:
            return self._runtime.chat(model_id, body)
        except LocalModelError:
            raise InferenceError("model_error") from None

    def open_chat(self, model_id: str, body: bytes) -> InferenceStream:
        try:
            reply = self._runtime.open_chat(model_id, body)
        except LocalModelError:
            raise InferenceError("model_error") from None
        return InferenceStream(reply.status_code, reply.content_type, reply.body,
            reply.lines, reply.cancel, reply.read_usage_tail)
