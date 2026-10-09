"""Inference contracts: no process, filesystem, HTTP, or provider credentials.

Model lifecycle belongs to the local runtime manager. Features depend only on
this port; an external provider never impersonates an owned local process.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import Field

from ..domain import StrictModel


class InferenceModel(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    name: str = Field(min_length=1, max_length=120)
    provider: Literal["local", "litellm"]
    remote: bool
    available: bool
    availability: Literal["running", "stopped", "configured"]
    revision: str | None = None
    license: str | None = None
    adapter_version: str
    # Null means not measured/qualified, not unsupported.
    tools: bool | None = None
    context_tokens: int | None = None
    streaming: bool = True


class InferenceCatalog(StrictModel):
    contract_version: Literal["inference.v1"] = "inference.v1"
    models: tuple[InferenceModel, ...]
    unavailable_providers: tuple[str, ...] = ()


@dataclass(slots=True)
class InferenceStream:
    status_code: int
    content_type: str
    body: bytes | None = None
    lines: Iterator[bytes] | None = None
    cancel: Callable[[], None] | None = None
    read_usage_tail: Callable[[], object | None] | None = None


class InferenceProvider(Protocol):
    provider_id: str
    def models(self) -> tuple[InferenceModel, ...]: ...
    def complete(self, model_id: str, body: bytes) -> tuple[int, bytes, str]: ...
    def open_chat(self, model_id: str, body: bytes) -> InferenceStream: ...


class InferenceError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class InferenceRegistry:
    """Request routing only. This object cannot start or stop a model."""

    def __init__(self, providers: tuple[InferenceProvider, ...]):
        self._providers = providers

    def catalog(self) -> InferenceCatalog:
        found = []
        unavailable = []
        for provider in self._providers:
            try:
                found.extend(provider.models())
            except Exception:
                unavailable.append(provider.provider_id)
        models = tuple(found)
        if len({model.id for model in models}) != len(models):
            raise InferenceError("inference_model_id_conflict")
        return InferenceCatalog(models=models, unavailable_providers=tuple(unavailable))

    def resolve(self, model_id: str) -> tuple[InferenceProvider, InferenceModel]:
        # Validate the entire catalog so collisions never silently pick a provider.
        self.catalog()
        for provider in self._providers:
            try:
                models = provider.models()
            except Exception:
                continue
            for model in models:
                if model.id == model_id:
                    if not model.available:
                        raise InferenceError("model_not_active")
                    return provider, model
        raise InferenceError("inference_model_not_found")

    def available(self, model_id: str) -> bool:
        try:
            self.resolve(model_id)
            return True
        except InferenceError:
            return False
