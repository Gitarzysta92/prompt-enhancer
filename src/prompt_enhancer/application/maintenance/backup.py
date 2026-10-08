"""Portable backup planning and all-before-mutation restore verification."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import hmac
import json
from typing import Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from ...domain import StrictModel
from ..build_evidence.manifest import canonical_json
from .inventory import (
    APPLICATION_PATH_INVENTORY,
    AppPathKind,
    AppPathSpec,
    BackupDisposition,
    PathSensitivity,
)


BACKUP_MANIFEST_SCHEMA_VERSION = 1
MAX_BACKUP_MANIFEST_BYTES = 1_048_576
MAX_BACKUP_ENTRIES = 1_024
MAX_BACKUP_ENTRY_BYTES = 4 * 1024 * 1024 * 1024


class BackupPlanState(StrEnum):
    READY = "ready"
    NOTHING_ELIGIBLE = "nothing_eligible"
    UNSUPPORTED_ENCRYPTED_BACKUP = "unsupported_encrypted_backup"


class BackupPlan(StrictModel):
    state: BackupPlanState
    path_ids: tuple[str, ...] = ()


class BackupEntry(StrictModel):
    path_id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    kind: AppPathKind
    size_bytes: int = Field(ge=0, le=MAX_BACKUP_ENTRY_BYTES)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_schema_version: int | None = Field(default=None, ge=1, le=1_000_000)

    @field_validator("size_bytes", mode="before")
    @classmethod
    def reject_boolean_size(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("backup size requires a JSON integer")
        return value

    @field_validator("source_schema_version", mode="before")
    @classmethod
    def reject_boolean_schema_version(cls, value: object) -> object:
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise ValueError("source schema requires a JSON integer")
        return value

    @model_validator(mode="after")
    def require_database_schema(self) -> BackupEntry:
        if (
            self.kind is AppPathKind.SQLITE_DATABASE
            and self.source_schema_version is None
        ):
            raise ValueError("SQLite backup entry requires its source schema")
        if (
            self.kind is not AppPathKind.SQLITE_DATABASE
            and self.source_schema_version is not None
        ):
            raise ValueError("non-database backup entry cannot declare a schema")
        return self


class BackupManifest(StrictModel):
    schema_version: Literal[1] = BACKUP_MANIFEST_SCHEMA_VERSION
    application_version: str = Field(
        max_length=96, pattern=r"^[A-Za-z0-9_.+\-]{1,96}$"
    )
    created_at: datetime
    entries: tuple[BackupEntry, ...] = Field(min_length=1, max_length=MAX_BACKUP_ENTRIES)
    encrypted: Literal[False] = False

    @field_validator("schema_version", mode="before")
    @classmethod
    def reject_boolean_schema(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("backup schema requires a JSON integer")
        return value

    @field_validator("created_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("backup timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def reject_duplicates(self) -> BackupManifest:
        identifiers = [entry.path_id for entry in self.entries]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("backup manifest contains duplicate paths")
        return self


class RestoreRejection(StrEnum):
    ENTRY_HASH_MISMATCH = "entry_hash_mismatch"
    ENTRY_MISSING = "entry_missing"
    ENTRY_SIZE_MISMATCH = "entry_size_mismatch"
    INVALID_MANIFEST = "invalid_manifest"
    MANIFEST_TOO_LARGE = "manifest_too_large"
    NEWER_SCHEMA_UNSUPPORTED = "newer_schema_unsupported"
    PATH_NOT_RESTORABLE = "path_not_restorable"
    UNKNOWN_PATH = "unknown_path"


class RestoreVerificationState(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class RestoreVerification(StrictModel):
    state: RestoreVerificationState
    approved_path_ids: tuple[str, ...] = ()
    rejection: RestoreRejection | None = None

    @model_validator(mode="after")
    def validate_state(self) -> RestoreVerification:
        if self.state is RestoreVerificationState.APPROVED:
            if self.rejection is not None:
                raise ValueError("approved restore cannot include a rejection")
        elif self.rejection is None or self.approved_path_ids:
            raise ValueError("rejected restore includes only a reason")
        return self


def plan_backup(
    *,
    encrypted: bool,
    inventory: tuple[AppPathSpec, ...] = APPLICATION_PATH_INVENTORY,
) -> BackupPlan:
    if encrypted:
        return BackupPlan(state=BackupPlanState.UNSUPPORTED_ENCRYPTED_BACKUP)
    eligible = tuple(
        sorted(
            entry.path_id
            for entry in inventory
            if entry.backup is not BackupDisposition.EXCLUDED
            and entry.sensitivity is not PathSensitivity.SECRET
        )
    )
    return BackupPlan(
        state=BackupPlanState.READY if eligible else BackupPlanState.NOTHING_ELIGIBLE,
        path_ids=eligible,
    )


def create_backup_manifest(
    payloads: Mapping[str, bytes],
    *,
    application_version: str,
    created_at: datetime,
    sqlite_schema_versions: Mapping[str, int],
    inventory: tuple[AppPathSpec, ...] = APPLICATION_PATH_INVENTORY,
) -> BackupManifest:
    by_id = {entry.path_id: entry for entry in inventory}
    entries: list[BackupEntry] = []
    for path_id, payload in sorted(payloads.items()):
        spec = by_id.get(path_id)
        if (
            spec is None
            or spec.backup is BackupDisposition.EXCLUDED
            or spec.sensitivity is PathSensitivity.SECRET
        ):
            raise ValueError("backup payload is not eligible")
        entries.append(
            BackupEntry(
                path_id=path_id,
                kind=spec.kind,
                size_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                source_schema_version=(
                    sqlite_schema_versions.get(path_id)
                    if spec.kind is AppPathKind.SQLITE_DATABASE
                    else None
                ),
            )
        )
    expected_schema_ids = {
        entry.path_id
        for entry in entries
        if entry.kind is AppPathKind.SQLITE_DATABASE
    }
    if set(sqlite_schema_versions) != expected_schema_ids:
        raise ValueError("backup schema provenance is incomplete")
    manifest = BackupManifest(
        application_version=application_version,
        created_at=created_at,
        entries=tuple(entries),
    )
    if len(canonical_json(manifest)) > MAX_BACKUP_MANIFEST_BYTES:
        raise ValueError("backup manifest exceeded its size bound")
    return manifest


def _restore_rejected(reason: RestoreRejection) -> RestoreVerification:
    return RestoreVerification(state=RestoreVerificationState.REJECTED, rejection=reason)


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate backup manifest key")
        result[key] = value
    return result


def verify_restore_manifest(
    raw_manifest: bytes,
    *,
    payloads: Mapping[str, bytes],
    supported_sqlite_schema_versions: Mapping[str, int],
    inventory: tuple[AppPathSpec, ...] = APPLICATION_PATH_INVENTORY,
) -> RestoreVerification:
    """Validate the entire restore set without writing or opening any target."""

    if len(raw_manifest) > MAX_BACKUP_MANIFEST_BYTES:
        return _restore_rejected(RestoreRejection.MANIFEST_TOO_LARGE)
    try:
        decoded = raw_manifest.decode("utf-8", errors="strict")
        untrusted = json.loads(
            decoded, object_pairs_hook=_object_without_duplicate_keys
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        return _restore_rejected(RestoreRejection.INVALID_MANIFEST)
    if not isinstance(untrusted, dict):
        return _restore_rejected(RestoreRejection.INVALID_MANIFEST)
    schema_version = untrusted.get("schema_version")
    if isinstance(schema_version, int) and schema_version > BACKUP_MANIFEST_SCHEMA_VERSION:
        return _restore_rejected(RestoreRejection.NEWER_SCHEMA_UNSUPPORTED)
    try:
        manifest = BackupManifest.model_validate(untrusted)
    except (TypeError, ValueError, ValidationError):
        return _restore_rejected(RestoreRejection.INVALID_MANIFEST)
    by_id = {entry.path_id: entry for entry in inventory}
    approved: list[str] = []
    for entry in manifest.entries:
        spec = by_id.get(entry.path_id)
        if spec is None:
            return _restore_rejected(RestoreRejection.UNKNOWN_PATH)
        if (
            spec.backup is BackupDisposition.EXCLUDED
            or spec.sensitivity is PathSensitivity.SECRET
            or entry.kind is not spec.kind
        ):
            return _restore_rejected(RestoreRejection.PATH_NOT_RESTORABLE)
        if entry.kind is AppPathKind.SQLITE_DATABASE:
            supported_schema = supported_sqlite_schema_versions.get(entry.path_id)
            if supported_schema is None:
                return _restore_rejected(RestoreRejection.PATH_NOT_RESTORABLE)
            if entry.source_schema_version is None or entry.source_schema_version > supported_schema:
                return _restore_rejected(RestoreRejection.NEWER_SCHEMA_UNSUPPORTED)
        payload = payloads.get(entry.path_id)
        if payload is None:
            return _restore_rejected(RestoreRejection.ENTRY_MISSING)
        if len(payload) != entry.size_bytes:
            return _restore_rejected(RestoreRejection.ENTRY_SIZE_MISMATCH)
        if not hmac.compare_digest(
            hashlib.sha256(payload).hexdigest(), entry.sha256
        ):
            return _restore_rejected(RestoreRejection.ENTRY_HASH_MISMATCH)
        approved.append(entry.path_id)
    if set(payloads) != set(approved):
        return _restore_rejected(RestoreRejection.UNKNOWN_PATH)
    if set(supported_sqlite_schema_versions) != {
        entry.path_id
        for entry in manifest.entries
        if entry.kind is AppPathKind.SQLITE_DATABASE
    }:
        return _restore_rejected(RestoreRejection.UNKNOWN_PATH)
    return RestoreVerification(
        state=RestoreVerificationState.APPROVED,
        approved_path_ids=tuple(approved),
    )
