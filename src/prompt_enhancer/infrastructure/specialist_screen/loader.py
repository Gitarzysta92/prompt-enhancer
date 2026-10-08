"""Fail-closed cache preparation for the bounded specialist candidates."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prompt_enhancer.infrastructure.text_models.loader import (
    isolated_hugging_face_environment,
    model_eval_cache_root,
    prepare_model_snapshot,
    validate_model_cache_root,
)
from prompt_enhancer.infrastructure.text_models.manifests import ModelManifest

from .manifests import SPECIALIST_MODEL_MANIFESTS


class SpecialistCandidateError(RuntimeError):
    """A fixed-code failure safe for aggregate local reporting."""


@dataclass(frozen=True, slots=True)
class PreparedSpecialistSnapshot:
    manifest: ModelManifest
    snapshot: Path


class _ExactSpecialistManifest:
    """Delegate manifest fields while narrowing the snapshot file allowlist."""

    __slots__ = ("_manifest",)

    def __init__(self, manifest: ModelManifest) -> None:
        self._manifest = manifest

    def __getattr__(self, name: str) -> Any:
        return getattr(self._manifest, name)

    @property
    def allowed_snapshot_patterns(self) -> tuple[str, ...]:
        return (
            *(filename for filename, _ in self._manifest.weight_files),
            *(
                filename
                for filename, _ in self._manifest.additional_artifact_files
            ),
        )


def specialist_cache_root() -> Path:
    return model_eval_cache_root() / "specialist-screen"


def require_registered_specialist_manifest(manifest: ModelManifest) -> None:
    registered = SPECIALIST_MODEL_MANIFESTS.get(manifest.key)
    if registered is None or registered != manifest:
        raise SpecialistCandidateError("unregistered_specialist_manifest")


def prepare_specialist_snapshot(
    manifest: ModelManifest,
    *,
    cache_root: Path | None = None,
    allow_public_download: bool = False,
    downloader: Callable[..., str] | None = None,
    file_downloader: Callable[..., str] | None = None,
    repo_root: Path | None = None,
) -> PreparedSpecialistSnapshot:
    """Preflight and resolve one exact public snapshot.

    The default is strictly offline.  The only online path is the explicit
    ``allow_public_download`` switch, which delegates to the existing reviewed
    public-model preparation boundary (immutable revision, allowlist,
    ``token=False``, safetensors hash verification).
    """

    require_registered_specialist_manifest(manifest)
    selected_cache = validate_model_cache_root(
        cache_root or specialist_cache_root(),
        repo_root=repo_root,
    )
    with isolated_hugging_face_environment(
        selected_cache,
        repo_root=repo_root,
    ):
        snapshot = prepare_model_snapshot(
            _ExactSpecialistManifest(manifest),
            cache_root=selected_cache,
            allow_download=allow_public_download,
            downloader=downloader,
            file_downloader=file_downloader,
            repo_root=repo_root,
        )
    return PreparedSpecialistSnapshot(manifest=manifest, snapshot=snapshot)
