"""Filesystem-backed resolution of immutable package resources.

The production resolver never falls back to a repository parent.  Zip-imported
resources are declined because a temporary extraction path would not live long
enough for the HTTP application or a subprocess.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
import os
from pathlib import Path

from ...application.paths import PathInspectionState
from ...application.resources import (
    ResourceAvailability,
    ResourceKind,
    ResourceShape,
    ResolvedResource,
)
from ..paths import inspect_path_components


@dataclass(frozen=True, slots=True)
class ResourceLayoutEntry:
    relative_parts: tuple[str, ...]
    shape: ResourceShape


PACKAGED_RESOURCE_LAYOUT: dict[ResourceKind, ResourceLayoutEntry] = {
    ResourceKind.DASHBOARD_STATIC: ResourceLayoutEntry(
        ("_resources", "dashboard"), ResourceShape.DIRECTORY
    ),
    ResourceKind.ACCELERATOR_PROBE: ResourceLayoutEntry(
        ("_resources", "probes", "probe_local_accelerator.py"), ResourceShape.FILE
    ),
    ResourceKind.THIRD_PARTY_NOTICES: ResourceLayoutEntry(
        ("_resources", "public", "THIRD_PARTY_NOTICES.txt"), ResourceShape.FILE
    ),
    ResourceKind.SOFTWARE_BILL_OF_MATERIALS: ResourceLayoutEntry(
        ("_resources", "public", "sbom.json"), ResourceShape.FILE
    ),
    ResourceKind.APPLICATION_UPDATE_TRUST: ResourceLayoutEntry(
        ("_resources", "public", "application-update-trust-v1.json"),
        ResourceShape.FILE,
    ),
}


class _FilesystemResolver:
    def __init__(self, root: Path) -> None:
        self._root = Path(os.path.abspath(os.fspath(root)))

    def resolve(self, kind: ResourceKind) -> ResolvedResource:
        entry = PACKAGED_RESOURCE_LAYOUT.get(kind)
        if entry is None:
            return ResolvedResource(
                kind=kind,
                availability=ResourceAvailability.UNSUPPORTED_LAYOUT,
                reason_code="resource_layout_unregistered",
            )
        root_inspection, _ = inspect_path_components(self._root)
        if root_inspection.state is not PathInspectionState.SAFE:
            return ResolvedResource(
                kind=kind,
                availability=ResourceAvailability.REJECTED,
                reason_code="resource_root_untrusted",
            )
        candidate = self._root.joinpath(*entry.relative_parts)
        try:
            candidate.relative_to(self._root)
        except ValueError:
            return ResolvedResource(
                kind=kind,
                availability=ResourceAvailability.REJECTED,
                reason_code="resource_outside_package",
            )
        inspection, _ = inspect_path_components(candidate)
        if inspection.state is not PathInspectionState.SAFE:
            return ResolvedResource(
                kind=kind,
                availability=ResourceAvailability.REJECTED,
                reason_code="resource_path_untrusted",
            )
        exists = candidate.is_file() if entry.shape is ResourceShape.FILE else candidate.is_dir()
        if not exists:
            return ResolvedResource(
                kind=kind,
                availability=ResourceAvailability.MISSING,
                reason_code="resource_missing",
            )
        try:
            resolved_root = self._root.resolve(strict=True)
            resolved_candidate = candidate.resolve(strict=True)
            resolved_candidate.relative_to(resolved_root)
        except (OSError, ValueError):
            return ResolvedResource(
                kind=kind,
                availability=ResourceAvailability.REJECTED,
                reason_code="resource_boundary_unverified",
            )
        return ResolvedResource(
            kind=kind,
            availability=ResourceAvailability.AVAILABLE,
            path=resolved_candidate,
        )


class StagedResourceResolver(_FilesystemResolver):
    """Development/test fake for a synthetic staged package tree."""


class PackageResourceResolver:
    def __init__(self, package: str = "prompt_enhancer") -> None:
        self._package = package

    def resolve(self, kind: ResourceKind) -> ResolvedResource:
        try:
            root = resources.files(self._package)
            filesystem_root = Path(os.fspath(root))
        except (AttributeError, ModuleNotFoundError, OSError, TypeError, ValueError):
            return ResolvedResource(
                kind=kind,
                availability=ResourceAvailability.UNSUPPORTED_LAYOUT,
                reason_code="package_is_not_filesystem_backed",
            )
        return _FilesystemResolver(filesystem_root).resolve(kind)


def default_packaged_resource_resolver() -> PackageResourceResolver:
    return PackageResourceResolver()
