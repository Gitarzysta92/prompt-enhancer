"""Durable, metadata-only composition of the direct file-sharing service.

The file store shares the social SQLite connection, transaction, directory and
graph store, so authorization facts, file metadata and audit rows commit or
roll back together.  Signaling still fails closed: no ICE/STUN/TURN, no
listener, no relay and no byte transport is composed here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from ...application.file_sharing.contracts import FileShareQuota
from ...application.file_sharing.service import (
    DirectFileSharingService,
    FileSharingStores,
)
from ..social.sqlite_file_store import SqliteFileShareStore
from ..social.sqlite_store import SqliteSocialFoundation
from .development import FailClosedDirectSignaling, RandomFileShareIdentifierFactory


@dataclass(frozen=True, slots=True)
class SqliteFileSharingFoundation:
    social: SqliteSocialFoundation
    store: SqliteFileShareStore
    service: DirectFileSharingService


def create_sqlite_file_sharing_foundation(
    social: SqliteSocialFoundation,
    clock: Callable[[], datetime],
    *,
    quota: FileShareQuota | None = None,
) -> SqliteFileSharingFoundation:
    store = SqliteFileShareStore(db=social.db)
    service = DirectFileSharingService(
        stores=FileSharingStores(
            transaction=social.db,
            directory=social.store,
            graph=social.store,
            manifests=store,
            grants=store,
            availability=store,
            transfers=store,
            audit=store,
        ),
        identifiers=RandomFileShareIdentifierFactory(),
        signaling=FailClosedDirectSignaling(),
        quota=quota or FileShareQuota(),
        clock=clock,
    )
    return SqliteFileSharingFoundation(social=social, store=store, service=service)


__all__ = ["SqliteFileSharingFoundation", "create_sqlite_file_sharing_foundation"]
