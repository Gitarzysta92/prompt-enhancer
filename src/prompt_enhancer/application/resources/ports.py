"""Ports for packaged resources; no repository layout leaks into callers."""

from __future__ import annotations

from typing import Protocol

from .contracts import ResolvedResource, ResourceKind


class PackagedResourceResolver(Protocol):
    def resolve(self, kind: ResourceKind) -> ResolvedResource: ...
