"""Synthetic Hugging Face Hub stubs for the local-model download tests.

Nothing here touches the network, a real repository, or a real model: the
"Hub" is a hand-built object graph with the same attribute names the
documented ``HfApi.model_info`` result exposes. Every identifier is a reserved
example value.
"""

from __future__ import annotations

from typing import Any
import time

from prompt_enhancer.application.local_models import DownloadStatus, LocalModelService


#: A fictional 40-hex commit oid; the tests never contact a real repository.
REVISION = "0123456789abcdef0123456789abcdef01234567"
#: A second fictional commit, used when a repository moves under the caller.
OTHER_REVISION = "89abcdef0123456789abcdef0123456789abcdef"
REPO_ID = "example-org/Example-GGUF"


class _Sibling:
    def __init__(self, filename: str, size: object, digest: object) -> None:
        self.rfilename = filename
        self.size = size
        self.lfs = None if digest is None else {"sha256": digest, "size": size, "pointer_size": 134}


class _Info:
    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


def stub_model_info(
    *,
    repo_id: str = REPO_ID,
    files: dict[str, tuple[object, object]] | None = None,
    license_id: str | None = "apache-2.0",
    tags: list[str] | None = None,
    head_revision: object = REVISION,
    pinned_revision: object | None = None,
    gated: object = False,
):
    """Build a ``model_info`` stand-in.

    ``files`` maps a file name to ``(size, sha256)``; either may be ``None`` or a
    malformed value to exercise the refusal paths. ``head_revision`` is what the
    unpinned lookup reports, ``pinned_revision`` what the commit-addressed lookup
    reports back (defaults to the same commit).
    """

    siblings = [_Sibling(name, size, digest) for name, (size, digest) in (files or {}).items()]
    card = None if license_id is None else {"license": license_id}
    declared_tags = tags if tags is not None else ([] if license_id is None else [f"license:{license_id}"])

    def model_info(requested_repo: str, *, revision: str | None = None, files_metadata: bool = False) -> _Info:
        assert files_metadata is True, "the app must always ask for file metadata"
        return _Info(
            id=requested_repo,
            sha=(head_revision if revision is None else (pinned_revision if pinned_revision is not None else head_revision)),
            tags=declared_tags,
            card_data=card,
            gated=gated,
            siblings=siblings,
        )

    model_info.repo_id = repo_id  # type: ignore[attr-defined]
    return model_info


def wait_for_download(service: LocalModelService, download_id: str, *, timeout: float = 15.0) -> DownloadStatus:
    """Block until one download reaches a terminal state."""

    deadline = time.monotonic() + timeout
    current = next(d for d in service.overview().downloads if d.download_id == download_id)
    while time.monotonic() < deadline:
        current = next(d for d in service.overview().downloads if d.download_id == download_id)
        if current.state in {"completed", "failed"}:
            return current
        time.sleep(0.02)
    return current
