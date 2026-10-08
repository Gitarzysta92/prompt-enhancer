"""Bounded, fixed-name durable evidence for authenticated update identity."""

from __future__ import annotations

import base64
import binascii
import json
import os
from pathlib import Path
import stat

from ...application.paths import PathInspectionState
from ...application.updates.contracts import (
    MAX_UPDATE_MANIFEST_BYTES,
    MAX_UPDATE_SIGNATURE_BYTES,
    ApplicationUpdateReason,
)
from ...application.updates.ports import (
    ArtifactStagingError,
    SignedUpdateManifestEnvelope,
)
from ...infrastructure.paths.local import inspect_path_components


class ReplayLedgerError(ArtifactStagingError):
    """A content-free replay-evidence integrity or durability failure."""

    def __init__(self) -> None:
        super().__init__(ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED)


class AtomicReplayLedger:
    """Retain exactly one public signed envelope beneath a private root.

    This store never derives or records a release version, artifact hash, URL,
    or account data.  Its caller authenticates the envelope before persistence
    and must authenticate it again after loading under then-current trust.
    Atomic replace plus file fsync is a local best-effort consistency boundary,
    not a hardware anti-rollback or power-loss durability guarantee.
    """

    _LEDGER = "update-replay.ledger.json"
    _PARTIAL = "update-replay.ledger.partial"
    _GUARD = "update-replay.ledger.lock"
    _MAX_BYTES = 64 * 1024

    def __init__(self, *, root: Path) -> None:
        self._root = root
        self._ensure_root()

    def _ensure_root(self) -> None:
        inspection, _ = inspect_path_components(self._root)
        if (inspection.state is not PathInspectionState.SAFE
                or not self._root.is_dir()):
            raise ReplayLedgerError()

    def _path(self, name: str) -> Path:
        return self._root / name

    @staticmethod
    def _safe_leaf(path: Path, *, missing_ok: bool = True) -> bool:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return missing_ok
        except OSError:
            return False
        return (stat.S_ISREG(metadata.st_mode)
                and not stat.S_ISLNK(metadata.st_mode)
                and not bool(getattr(metadata, "st_file_attributes", 0) & 0x400)
                and metadata.st_nlink == 1)

    @staticmethod
    def _serialize(envelope: SignedUpdateManifestEnvelope) -> bytes:
        if (not envelope.raw_manifest
                or len(envelope.raw_manifest) > MAX_UPDATE_MANIFEST_BYTES
                or not envelope.signature
                or len(envelope.signature) > MAX_UPDATE_SIGNATURE_BYTES):
            raise ReplayLedgerError()
        # This is the exact publisher-signed public input, not parsed claims.
        encoded = json.dumps(
            {
                "key_id": envelope.key_id,
                "manifest_base64": base64.b64encode(
                    envelope.raw_manifest).decode("ascii"),
                "schema_version": 1,
                "signature_base64": base64.b64encode(
                    envelope.signature).decode("ascii"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > AtomicReplayLedger._MAX_BYTES:
            raise ReplayLedgerError()
        return encoded

    @staticmethod
    def _decode(raw: bytes) -> SignedUpdateManifestEnvelope:
        if not raw or len(raw) > AtomicReplayLedger._MAX_BYTES:
            raise ReplayLedgerError()
        try:
            data = json.loads(
                raw.decode("utf-8", errors="strict"),
                object_pairs_hook=_without_duplicates,
            )
            if (set(data) != {
                    "schema_version",
                    "key_id",
                    "manifest_base64",
                    "signature_base64",
            } or type(data["schema_version"]) is not int
                    or data["schema_version"] != 1
                    or not all(isinstance(data[name], str) for name in (
                        "key_id", "manifest_base64", "signature_base64"))):
                raise ValueError
            manifest = base64.b64decode(data["manifest_base64"], validate=True)
            signature = base64.b64decode(data["signature_base64"], validate=True)
            if (not manifest or len(manifest) > MAX_UPDATE_MANIFEST_BYTES
                    or not signature or len(signature) > MAX_UPDATE_SIGNATURE_BYTES):
                raise ValueError
            return SignedUpdateManifestEnvelope(
                raw_manifest=manifest,
                signature=signature,
                key_id=data["key_id"],
            )
        except (binascii.Error, json.JSONDecodeError, RecursionError, TypeError,
                ValueError) as error:
            raise ReplayLedgerError() from error

    def _load_unlocked(self) -> SignedUpdateManifestEnvelope | None:
        ledger, partial = self._path(self._LEDGER), self._path(self._PARTIAL)
        if not self._safe_leaf(ledger) or not self._safe_leaf(partial):
            raise ReplayLedgerError()
        if partial.exists():
            raise ReplayLedgerError()
        if not ledger.exists():
            return None
        try:
            with ledger.open("rb") as handle:
                metadata = os.fstat(handle.fileno())
                if (not stat.S_ISREG(metadata.st_mode)
                        or metadata.st_nlink != 1):
                    raise ValueError
                # Bound the actual read rather than trusting a prior stat:
                # another process can replace or grow the fixed-name leaf.
                raw = handle.read(self._MAX_BYTES + 1)
                if not raw or len(raw) > self._MAX_BYTES:
                    raise ValueError
        except (OSError, ValueError) as error:
            raise ReplayLedgerError() from error
        return self._decode(raw)

    def load(self) -> SignedUpdateManifestEnvelope | None:
        self._ensure_root()
        guard = self._path(self._GUARD)
        if not self._safe_leaf(guard) or guard.exists():
            raise ReplayLedgerError()
        return self._load_unlocked()

    def persist_authenticated(
            self,
            *,
            expected_envelope: SignedUpdateManifestEnvelope | None,
            envelope: SignedUpdateManifestEnvelope,
    ) -> None:
        """CAS-replace retained evidence only after caller authentication."""

        encoded = self._serialize(envelope)
        self._ensure_root()
        ledger, partial, guard = (self._path(self._LEDGER),
                                  self._path(self._PARTIAL),
                                  self._path(self._GUARD))
        if (not self._safe_leaf(ledger) or not self._safe_leaf(partial)
                or not self._safe_leaf(guard) or partial.exists()
                or guard.exists()):
            raise ReplayLedgerError()
        acquired = False
        try:
            with guard.open("xb") as handle:
                acquired = True
                handle.flush()
                os.fsync(handle.fileno())
            # The exact comparison happens while the fixed-name guard is held,
            # so another coordinator cannot silently replace a newer floor.
            if self._load_unlocked() != expected_envelope:
                raise ReplayLedgerError()
            with partial.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            if not self._safe_leaf(partial, missing_ok=False):
                raise ReplayLedgerError()
            os.replace(partial, ledger)
        except ReplayLedgerError:
            raise
        except OSError as error:
            raise ReplayLedgerError() from error
        finally:
            if acquired:
                try:
                    if not self._safe_leaf(guard, missing_ok=False):
                        raise ReplayLedgerError()
                    guard.unlink()
                except OSError as error:
                    raise ReplayLedgerError() from error


def _without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate replay ledger key")
        result[key] = value
    return result


__all__ = ("AtomicReplayLedger", "ReplayLedgerError")
