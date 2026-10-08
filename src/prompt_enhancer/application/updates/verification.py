"""Offline signed-manifest verification with security-sensitive ordering."""

from __future__ import annotations

from datetime import UTC, datetime
import json

from pydantic import ValidationError

from .contracts import (
    MAX_UPDATE_MANIFEST_BYTES,
    MAX_UPDATE_SIGNATURE_BYTES,
    UpdateChannel,
    UpdateManifest,
    UpdateRejection,
    UpdateVerification,
    UpdateVerificationState,
)
from .ports import ManifestSignatureVerifier, SignatureState


def _rejected(reason: UpdateRejection) -> UpdateVerification:
    return UpdateVerification(state=UpdateVerificationState.REJECTED, rejection=reason)


def _version_tuple(value: str) -> tuple[int, int, int]:
    if len(value) > 32:
        raise ValueError("version exceeded bound")
    major, minor, patch = value.split(".")
    return int(major), int(minor), int(patch)


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate update manifest key")
        result[key] = value
    return result


def authenticate_signed_update_manifest(
    raw_manifest: bytes,
    *,
    signature: bytes,
    key_id: str,
    verifier: ManifestSignatureVerifier,
) -> UpdateVerification:
    """Authenticate bounded signed manifest bytes without time/version policy.

    This is deliberately narrower than :func:`verify_update_manifest`: replay
    evidence needs a historically authentic release identity even when it is
    no longer eligible to download or stage today.  Callers must separately
    apply the full current-policy verification before exposing a release.
    """

    if len(raw_manifest) > MAX_UPDATE_MANIFEST_BYTES:
        return _rejected(UpdateRejection.MANIFEST_TOO_LARGE)
    if len(signature) > MAX_UPDATE_SIGNATURE_BYTES:
        return _rejected(UpdateRejection.SIGNATURE_TOO_LARGE)
    try:
        decoded = raw_manifest.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return _rejected(UpdateRejection.INVALID_ENCODING)
    try:
        parsed = json.loads(decoded, object_pairs_hook=_object_without_duplicate_keys)
        manifest = UpdateManifest.model_validate(parsed)
    except (json.JSONDecodeError, RecursionError, TypeError, ValueError, ValidationError):
        return _rejected(UpdateRejection.INVALID_SCHEMA)
    try:
        signature_state = verifier.verify(
            payload=raw_manifest,
            signature=signature,
            key_id=key_id,
        )
    except Exception:
        signature_state = SignatureState.INVALID
    if signature_state is SignatureState.UNKNOWN_KEY:
        return _rejected(UpdateRejection.UNKNOWN_KEY)
    if signature_state is not SignatureState.VALID:
        return _rejected(UpdateRejection.BAD_SIGNATURE)
    return UpdateVerification(
        state=UpdateVerificationState.ACCEPTED,
        manifest=manifest,
    )


def verify_update_manifest(
    raw_manifest: bytes,
    *,
    signature: bytes,
    key_id: str,
    verifier: ManifestSignatureVerifier,
    now: datetime,
    installed_version: str,
    channel: UpdateChannel,
) -> UpdateVerification:
    """Verify in fixed order: size, decode, schema, signature, semantics."""

    authenticated = authenticate_signed_update_manifest(
        raw_manifest,
        signature=signature,
        key_id=key_id,
        verifier=verifier,
    )
    if authenticated.state is UpdateVerificationState.REJECTED:
        return authenticated
    manifest = authenticated.manifest
    if manifest is None:
        return _rejected(UpdateRejection.INVALID_SCHEMA)
    try:
        installed = _version_tuple(installed_version)
    except (TypeError, ValueError):
        return _rejected(UpdateRejection.INVALID_SCHEMA)
    if now.tzinfo is None or now.utcoffset() is None:
        return _rejected(UpdateRejection.INVALID_SCHEMA)
    current_time = now.astimezone(UTC)
    published_at = manifest.published_at.astimezone(UTC)
    expires_at = manifest.expires_at.astimezone(UTC)
    if published_at > current_time:
        return _rejected(UpdateRejection.NOT_YET_PUBLISHED)
    if expires_at <= current_time or expires_at <= published_at:
        return _rejected(UpdateRejection.EXPIRED)
    if manifest.channel is not channel:
        return _rejected(UpdateRejection.CHANNEL_MISMATCH)
    release = _version_tuple(manifest.release_version)
    minimum = _version_tuple(manifest.minimum_supported_version)
    if installed < minimum:
        return _rejected(UpdateRejection.MINIMUM_VERSION_UNSUPPORTED)
    if release < installed:
        return _rejected(UpdateRejection.DOWNGRADE)
    if release == installed:
        return _rejected(UpdateRejection.CURRENT_VERSION)
    return UpdateVerification(
        state=UpdateVerificationState.ACCEPTED,
        manifest=manifest,
    )
