"""Isolated, integrity-checked Hugging Face snapshot loading."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
from typing import Any

from .manifests import ModelManifest


class TextModelLoadError(RuntimeError):
    """Base class whose message is safe to expose as a fixed error code only."""


class ModelCacheBoundaryError(TextModelLoadError):
    pass


class ModelSnapshotUnavailableError(TextModelLoadError):
    pass


class ModelIntegrityError(TextModelLoadError):
    pass


_UNSAFE_MODEL_SUFFIXES = frozenset(
    {".bin", ".ckpt", ".joblib", ".pickle", ".pkl", ".pt", ".pth"}
)


@contextmanager
def transformers_network_closed():
    """Temporarily force Hub and Transformers offline during local inference."""

    names = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
    previous = {name: os.environ.get(name) for name in names}
    for name in names:
        os.environ[name] = "1"
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@contextmanager
def isolated_hugging_face_environment(
    cache_root: Path | None = None,
    *,
    repo_root: Path | None = None,
):
    """Point all Hugging Face state at this task's ignored cache only.

    This context must begin before importing Hub or Transformers modules.  It
    prevents their default cache/token paths from resolving into a home
    directory even though public downloads also pass ``token=False``.
    """

    cache = validate_model_cache_root(
        cache_root or model_eval_cache_root(),
        repo_root=repo_root,
    )
    values = {
        "HF_HOME": cache / "hf-home",
        "HF_HUB_CACHE": cache / "hub",
        "HF_ASSETS_CACHE": cache / "assets",
        "HF_TOKEN_PATH": cache / "credentials-disabled" / "token",
        "HF_STORED_TOKENS_PATH": cache / "credentials-disabled" / "stored-tokens",
        "SENTENCE_TRANSFORMERS_HOME": cache / "sentence-transformers",
    }
    previous = {name: os.environ.get(name) for name in values}
    for name, value in values.items():
        os.environ[name] = str(value)
    try:
        yield cache
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def model_eval_cache_root() -> Path:
    return repository_root() / "runtime" / "model-eval"


def _reject_existing_symlink_components(path: Path, stop: Path) -> None:
    try:
        relative = path.relative_to(stop)
    except ValueError as exc:
        raise ModelCacheBoundaryError("cache_outside_runtime_model_eval") from exc
    cursor = stop
    for part in relative.parts:
        cursor /= part
        if cursor.exists() and cursor.is_symlink():
            raise ModelCacheBoundaryError("cache_symlink_component_rejected")


def validate_model_cache_root(
    candidate: Path,
    *,
    repo_root: Path | None = None,
) -> Path:
    """Require an ordinary directory at or below ``runtime/model-eval``."""

    root = (repo_root or repository_root()).resolve()
    lexical_allowed = root / "runtime" / "model-eval"
    lexical_candidate = candidate if candidate.is_absolute() else root / candidate
    _reject_existing_symlink_components(lexical_allowed, root)
    _reject_existing_symlink_components(lexical_candidate, root)
    allowed = lexical_allowed.resolve()
    resolved = lexical_candidate.resolve()
    if resolved != allowed and allowed not in resolved.parents:
        raise ModelCacheBoundaryError("cache_outside_runtime_model_eval")
    resolved.mkdir(parents=True, exist_ok=True)
    if resolved.is_symlink() or not resolved.is_dir():
        raise ModelCacheBoundaryError("cache_must_be_an_ordinary_directory")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_snapshot_artifacts(
    snapshot: Path,
    *,
    cache: Path,
    manifest: ModelManifest,
) -> None:
    """Fail closed on poisoned local-cache entries before Transformers loads.

    Hub snapshots normally use file symlinks into a cache-local blob directory,
    so those links remain supported.  Every resolved target must nevertheless
    stay inside the isolated task cache and every lexical snapshot filename must
    be part of the reviewed manifest allowlist.
    """

    allowed = frozenset(manifest.allowed_snapshot_patterns)
    for artifact in snapshot.rglob("*"):
        relative = artifact.relative_to(snapshot).as_posix()
        if artifact.is_symlink():
            try:
                resolved = artifact.resolve(strict=True)
            except OSError:
                raise ModelIntegrityError("broken_snapshot_symlink_rejected") from None
            if resolved != cache and cache not in resolved.parents:
                raise ModelCacheBoundaryError("snapshot_artifact_outside_isolated_cache")
            if resolved.is_dir():
                raise ModelIntegrityError("snapshot_directory_symlink_rejected")
        if not artifact.is_file():
            continue
        if artifact.suffix.casefold() in _UNSAFE_MODEL_SUFFIXES:
            raise ModelIntegrityError("unsafe_model_artifact_rejected")
        if relative not in allowed:
            raise ModelIntegrityError("unexpected_snapshot_artifact_rejected")
        resolved = artifact.resolve()
        if resolved != cache and cache not in resolved.parents:
            raise ModelCacheBoundaryError("snapshot_artifact_outside_isolated_cache")


def _default_snapshot_download(**kwargs: Any) -> str:
    # Import only after the caller has chosen online/offline policy.  token=False
    # prevents use of any locally stored Hugging Face credential for these public
    # candidates.
    from huggingface_hub import snapshot_download

    return snapshot_download(**kwargs)


def _default_file_download(**kwargs: Any) -> str:
    from huggingface_hub import hf_hub_download

    return hf_hub_download(**kwargs)


def prepare_model_snapshot(
    manifest: ModelManifest,
    *,
    cache_root: Path | None = None,
    allow_download: bool = False,
    downloader: Callable[..., str] | None = None,
    file_downloader: Callable[..., str] | None = None,
    repo_root: Path | None = None,
) -> Path:
    """Resolve and verify one pinned snapshot inside the isolated cache.

    Network access is impossible through this function unless
    ``allow_download`` is explicitly true.  Even in online mode it never uses a
    credential and downloads only the allowlisted public artifacts.
    """

    cache = validate_model_cache_root(
        cache_root or model_eval_cache_root(),
        repo_root=repo_root,
    )
    fetch = downloader or _default_snapshot_download
    previous_offline = os.environ.get("HF_HUB_OFFLINE")
    if not allow_download:
        os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        try:
            snapshot_value = fetch(
                repo_id=manifest.repository_id,
                revision=manifest.revision,
                cache_dir=str(cache),
                allow_patterns=list(manifest.allowed_snapshot_patterns),
                local_files_only=not allow_download,
                token=False,
                max_workers=4,
            )
        except Exception as exc:
            raise ModelSnapshotUnavailableError("model_snapshot_unavailable") from None
    finally:
        if not allow_download:
            if previous_offline is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = previous_offline

    snapshot = Path(snapshot_value).resolve()
    if snapshot != cache and cache not in snapshot.parents:
        raise ModelCacheBoundaryError("snapshot_outside_isolated_cache")
    if not snapshot.is_dir():
        raise ModelSnapshotUnavailableError("model_snapshot_unavailable")
    if snapshot.name != manifest.revision or snapshot.parent.name != "snapshots":
        raise ModelIntegrityError("snapshot_revision_path_mismatch")

    # Some Hub cache versions can return an otherwise valid allowlisted
    # snapshot before a small non-LFS config artifact is materialized.  In the
    # explicitly online mode only, request that one reviewed filename directly.
    # Offline mode continues to fail without any network fallback.
    config = snapshot / "config.json"
    if not config.is_file() and allow_download:
        fetch_file = file_downloader or _default_file_download
        try:
            config_value = fetch_file(
                repo_id=manifest.repository_id,
                filename="config.json",
                revision=manifest.revision,
                cache_dir=str(cache),
                local_files_only=False,
                token=False,
            )
        except Exception:
            raise ModelSnapshotUnavailableError("model_config_unavailable") from None
        resolved_config = Path(config_value).resolve()
        if resolved_config != cache and cache not in resolved_config.parents:
            raise ModelCacheBoundaryError("config_outside_isolated_cache")

    _validate_snapshot_artifacts(snapshot, cache=cache, manifest=manifest)

    for filename, expected_digest in manifest.weight_files:
        weight = snapshot / filename
        if not weight.is_file():
            raise ModelIntegrityError("reviewed_safetensors_weight_missing")
        resolved_weight = weight.resolve()
        if resolved_weight != cache and cache not in resolved_weight.parents:
            raise ModelCacheBoundaryError("weight_outside_isolated_cache")
        if _sha256(weight) != expected_digest:
            raise ModelIntegrityError("reviewed_weight_sha256_mismatch")
    for filename, expected_digest in manifest.additional_artifact_files:
        artifact = snapshot / filename
        if not artifact.is_file():
            raise ModelIntegrityError("reviewed_auxiliary_artifact_missing")
        resolved_artifact = artifact.resolve()
        if resolved_artifact != cache and cache not in resolved_artifact.parents:
            raise ModelCacheBoundaryError(
                "auxiliary_artifact_outside_isolated_cache"
            )
        if _sha256(artifact) != expected_digest:
            raise ModelIntegrityError("reviewed_auxiliary_artifact_sha256_mismatch")
    if not config.is_file():
        raise ModelIntegrityError("model_config_missing")
    if not any(
        (snapshot / filename).is_file()
        for filename in (
            "tokenizer.json",
            "sentencepiece.bpe.model",
            "spm.model",
            "vocab.txt",
            "vocab.json",
        )
    ):
        raise ModelIntegrityError("reviewed_tokenizer_artifact_missing")
    return snapshot
