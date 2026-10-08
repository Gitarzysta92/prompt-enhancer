"""Private, fixed-name update staging files (never an installer)."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import stat
from collections.abc import Callable, Iterable

from ...application.updates.contracts import UpdateManifest
from ...application.updates.ports import (
    ArtifactStagingCancelled,
    ArtifactStagingError,
    SignedUpdateManifestEnvelope,
)
from ...application.updates.contracts import ApplicationUpdateReason
from ...infrastructure.paths.local import inspect_path_components
from ...application.paths import PathInspectionState

UpdateStagingError = ArtifactStagingError
UpdateStagingCancelled = ArtifactStagingCancelled


class FileUpdateStagingStore:
    """Stores one signed artifact below an already-hardened private root.

    The caller must establish the root's platform privacy guarantee before
    composition.  This class still rejects links, reparse points, and
    hard-linked leaves on every destructive operation.
    """

    _PARTIAL = "artifact.partial"
    _FINAL = "artifact.staged"
    _LEDGER = "staged-update.ledger.json"

    def __init__(self, *, root: Path) -> None:
        self._root = root
        self._ensure_root()

    def _ensure_root(self) -> None:
        inspection, _ = inspect_path_components(self._root)
        if inspection.state is not PathInspectionState.SAFE:
            raise UpdateStagingError(
                ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED)
        if not self._root.is_dir():
            raise UpdateStagingError(
                ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED)

    def _path(self, name: str) -> Path:
        # Fixed names prevent caller-controlled cleanup targets.
        return self._root / name

    def _safe_leaf(self, path: Path, *, missing_ok: bool = True) -> bool:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return missing_ok
        except OSError:
            return False
        return (stat.S_ISREG(metadata.st_mode)
                and not stat.S_ISLNK(metadata.st_mode) and
                not bool(getattr(metadata, "st_file_attributes", 0) & 0x400)
                and metadata.st_nlink == 1)

    def _remove_owned(self, name: str) -> None:
        self._ensure_root()
        path = self._path(name)
        if not self._safe_leaf(path):
            raise UpdateStagingError(
                ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED)
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            raise UpdateStagingError(
                ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED) from error

    @staticmethod
    def _ledger(manifest: UpdateManifest,
                envelope: SignedUpdateManifestEnvelope) -> bytes:
        # The signed public envelope is retained for restart authentication;
        # no owner data, paths, URLs, or downloaded content enter this ledger.
        data = {
            "schema_version":
            1,
            "state":
            "staged",
            "key_id":
            envelope.key_id,
            "manifest_base64":
            base64.b64encode(envelope.raw_manifest).decode("ascii"),
            "signature_base64":
            base64.b64encode(envelope.signature).decode("ascii"),
        }
        return json.dumps(data, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")

    def stage(
        self,
        *,
        manifest: UpdateManifest,
        envelope: SignedUpdateManifestEnvelope,
        chunks: Iterable[bytes],
        cancelled: Callable[[], bool],
        on_progress: Callable[[int], None],
    ) -> None:
        self._ensure_root()
        partial = self._path(self._PARTIAL)
        final = self._path(self._FINAL)
        ledger = self._path(self._LEDGER)
        ledger_tmp = self._path("staged-update.ledger.partial")
        if not all(
                self._safe_leaf(path)
                for path in (partial, final, ledger, ledger_tmp)):
            raise UpdateStagingError(
                ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED)
        # Never overwrite unaccounted-for stage evidence.
        if final.exists() or ledger.exists():
            raise UpdateStagingError(
                ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED)
        if partial.exists() or ledger_tmp.exists():
            raise UpdateStagingError(
                ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED)
        digest = hashlib.sha256()
        count = 0
        created_partial = False
        promoted = False
        try:
            with partial.open("xb") as handle:
                created_partial = True
                for chunk in chunks:
                    if cancelled():
                        raise UpdateStagingCancelled()
                    if not isinstance(chunk, bytes) or not chunk:
                        if not isinstance(chunk, bytes):
                            raise UpdateStagingError(ApplicationUpdateReason.
                                                     ARTIFACT_DOWNLOAD_FAILED)
                        continue
                    if count + len(chunk) > manifest.artifact_size_bytes:
                        raise UpdateStagingError(ApplicationUpdateReason.
                                                 ARTIFACT_VERIFICATION_FAILED)
                    handle.write(chunk)
                    digest.update(chunk)
                    count += len(chunk)
                    on_progress(count)
                handle.flush()
                os.fsync(handle.fileno())
            if cancelled():
                raise UpdateStagingCancelled()
            if count != manifest.artifact_size_bytes or digest.hexdigest(
            ) != manifest.artifact_sha256:
                raise UpdateStagingError(
                    ApplicationUpdateReason.ARTIFACT_VERIFICATION_FAILED)
            if not self._safe_leaf(partial, missing_ok=False):
                raise UpdateStagingError(
                    ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED)
            os.replace(partial, final)
            promoted = True
            if not self._safe_leaf(ledger_tmp):
                raise UpdateStagingError(
                    ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED)
            if ledger_tmp.exists():
                raise UpdateStagingError(
                    ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED)
            with ledger_tmp.open("xb") as handle:
                handle.write(self._ledger(manifest, envelope))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(ledger_tmp, ledger)
        except Exception as error:
            # A known regular, owned partial can be cleaned; uncertainty is a
            # failure and intentionally leaves evidence untouched.
            if created_partial:
                try:
                    self._remove_owned(self._PARTIAL)
                except UpdateStagingError:
                    raise
            if promoted:
                raise UpdateStagingError(
                    ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED
                ) from error
            raise

    def discard_partial(self) -> None:
        self._remove_owned(self._PARTIAL)

    def staged_package_path(self) -> Path:
        """Return the one owned staged artifact after a non-mutating safety check.

        This deliberately has no caller-selected filename.  Consumers that need
        a filesystem path for an OS verifier can inspect only ``artifact.staged``
        below this already-private root; they must still call
        :meth:`recover_envelope` to bind its bytes to authenticated evidence.
        """

        self._ensure_root()
        final = self._path(self._FINAL)
        if not self._safe_leaf(final, missing_ok=False):
            raise UpdateStagingError(
                ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED)
        return final

    def supersede_staged(
            self, *, expected_envelope: SignedUpdateManifestEnvelope) -> None:
        """Remove only the exact authenticated prior stage after an owner stage action."""

        recovered = self.recover_envelope()
        if recovered is None or recovered != expected_envelope:
            raise UpdateStagingError(
                ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED)
        self._remove_owned(self._FINAL)
        self._remove_owned(self._LEDGER)

    def recover_envelope(self) -> SignedUpdateManifestEnvelope | None:
        """Return only a fully accounted signed envelope after restart.

        Any orphan, partial, link, malformed ledger, or byte mismatch is left
        untouched and fails closed.  A caller must still verify the envelope
        against its current key/time/version policy before presenting STAGED.
        """

        self._ensure_root()
        partial = self._path(self._PARTIAL)
        final = self._path(self._FINAL)
        ledger = self._path(self._LEDGER)
        ledger_partial = self._path("staged-update.ledger.partial")
        if not all(
                self._safe_leaf(path)
                for path in (partial, final, ledger, ledger_partial)):
            raise UpdateStagingError(
                ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED)
        if partial.exists() or ledger_partial.exists():
            raise UpdateStagingError(
                ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED)
        if not final.exists() and not ledger.exists():
            return None
        if not final.exists() or not ledger.exists():
            raise UpdateStagingError(
                ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED)
        if not self._safe_leaf(final, missing_ok=False) or not self._safe_leaf(
                ledger, missing_ok=False):
            raise UpdateStagingError(
                ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED)
        try:
            ledger_size = ledger.stat().st_size
            if ledger_size <= 0 or ledger_size > 64 * 1024:
                raise ValueError
            raw_ledger = ledger.read_bytes()
            if len(raw_ledger) != ledger_size or len(raw_ledger) > 64 * 1024:
                raise ValueError
            data = json.loads(
                raw_ledger.decode("utf-8"),
                object_pairs_hook=_without_duplicates,
            )
            if set(data) != {
                    "schema_version",
                    "state",
                    "key_id",
                    "manifest_base64",
                    "signature_base64",
            } or type(data["schema_version"]
                      ) is not int or data["schema_version"] != 1 or data[
                          "state"] != "staged" or not all(
                              isinstance(data[name], str)
                              for name in ("key_id", "manifest_base64",
                                           "signature_base64")):
                raise ValueError
            raw_manifest = base64.b64decode(data["manifest_base64"],
                                            validate=True)
            manifest = UpdateManifest.model_validate_json(raw_manifest)
            if final.stat().st_size != manifest.artifact_size_bytes:
                raise ValueError
            digest = hashlib.sha256()
            size = 0
            with final.open("rb") as handle:
                for chunk in iter(lambda: handle.read(64 * 1024), b""):
                    if size + len(chunk) > manifest.artifact_size_bytes:
                        raise ValueError
                    digest.update(chunk)
                    size += len(chunk)
            if size != manifest.artifact_size_bytes or digest.hexdigest(
            ) != manifest.artifact_sha256:
                raise ValueError
            return SignedUpdateManifestEnvelope(
                raw_manifest=raw_manifest,
                signature=base64.b64decode(data["signature_base64"],
                                           validate=True),
                key_id=data["key_id"],
            )
        except (OSError, TypeError, ValueError, RecursionError, binascii.Error,
                json.JSONDecodeError) as error:
            raise UpdateStagingError(ApplicationUpdateReason.
                                     ARTIFACT_VERIFICATION_FAILED) from error


def _without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate update ledger key")
        result[key] = value
    return result


__all__ = ("FileUpdateStagingStore", "UpdateStagingCancelled",
           "UpdateStagingError")
