"""Validate a reviewed, content-free provider compatibility manifest offline.

This tool deliberately does not discover installed providers, invoke provider
commands, inspect sessions, access a network, hash runtime responses, or update
adapters.  It is suitable for a release gate after a compatibility manifest has
already been produced from reviewed public contracts and synthetic tests.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any


MANIFEST_VERSION = "provider-compatibility-manifest-v1"
MAX_MANIFEST_BYTES = 256 * 1024
MAX_ENTRIES = 256
MAX_LIST_ITEMS = 128

_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_RELEASE_STATES = frozenset({"blocked", "experimental", "verified"})
_CAPABILITY_STATES = frozenset({"partial", "supported", "unsupported"})
_SCHEMA_SOURCES = frozenset(
    {"official_export", "official_sdk", "synthetic_contract"}
)
_RELEASE_EVIDENCE = frozenset(
    {
        "local_smoke_attestation",
        "official_contract",
        "privacy_review",
        "synthetic_contract",
    }
)
_VERIFIED_EVIDENCE = _RELEASE_EVIDENCE

_ROOT_KEYS = frozenset({"entries", "manifest_version"})
_ENTRY_KEYS = frozenset(
    {
        "adapter_version",
        "canonical_schema_version",
        "capabilities",
        "decoder_version",
        "fixture_corpus_version",
        "provider",
        "release_evidence",
        "release_state",
        "schema_artifact_version",
        "schema_family",
        "schema_source",
        "surface",
        "tested_provider_versions",
    }
)


class ManifestError(ValueError):
    """A sanitized validation error whose code contains no manifest value."""

    def __init__(self, code: str = "manifest_invalid") -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CompatibilityEntry:
    provider: str
    surface: str
    schema_family: str
    adapter_version: str
    decoder_version: str
    canonical_schema_version: str
    schema_source: str
    schema_artifact_version: str
    fixture_corpus_version: str
    tested_provider_versions: tuple[str, ...]
    release_state: str
    release_evidence: tuple[str, ...]
    capabilities: tuple[tuple[str, str], ...]

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return (
            self.provider,
            self.surface,
            self.schema_family,
            self.decoder_version,
        )

    def capability_state(self, capability: str) -> str | None:
        return dict(self.capabilities).get(capability)


@dataclass(frozen=True, slots=True)
class CompatibilityManifest:
    entries: tuple[CompatibilityEntry, ...]


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ManifestError()
        result[key] = value
    return result


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ManifestError()
    return value


def _exact_keys(value: dict[str, Any], expected: frozenset[str]) -> None:
    if set(value) != expected:
        raise ManifestError()


def _identifier(value: object) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ManifestError()
    return value


def _version(value: object) -> str:
    if not isinstance(value, str) or _VERSION.fullmatch(value) is None:
        raise ManifestError()
    return value


def _closed_value(value: object, allowed: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ManifestError()
    return value


def _sorted_unique_versions(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > MAX_LIST_ITEMS:
        raise ManifestError()
    normalized = tuple(_version(item) for item in value)
    if normalized != tuple(sorted(set(normalized))):
        raise ManifestError()
    return normalized


def _sorted_unique_evidence(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > len(_RELEASE_EVIDENCE):
        raise ManifestError()
    normalized = tuple(_closed_value(item, _RELEASE_EVIDENCE) for item in value)
    if normalized != tuple(sorted(set(normalized))):
        raise ManifestError()
    return normalized


def _capabilities(value: object) -> tuple[tuple[str, str], ...]:
    candidate = _object(value)
    if not candidate or len(candidate) > MAX_LIST_ITEMS:
        raise ManifestError()
    normalized = tuple(
        sorted(
            (
                _identifier(key),
                _closed_value(state, _CAPABILITY_STATES),
            )
            for key, state in candidate.items()
        )
    )
    if len({key for key, _ in normalized}) != len(normalized):
        raise ManifestError()
    return normalized


def _entry(value: object) -> CompatibilityEntry:
    candidate = _object(value)
    _exact_keys(candidate, _ENTRY_KEYS)
    release_state = _closed_value(candidate["release_state"], _RELEASE_STATES)
    schema_source = _closed_value(candidate["schema_source"], _SCHEMA_SOURCES)
    tested_versions = _sorted_unique_versions(candidate["tested_provider_versions"])
    evidence = _sorted_unique_evidence(candidate["release_evidence"])
    capabilities = _capabilities(candidate["capabilities"])

    if release_state == "verified":
        if (
            schema_source == "synthetic_contract"
            or not tested_versions
            or set(evidence) != _VERIFIED_EVIDENCE
            or not any(state == "supported" for _, state in capabilities)
        ):
            raise ManifestError()
    if release_state == "blocked" and any(
        state != "unsupported" for _, state in capabilities
    ):
        raise ManifestError()

    return CompatibilityEntry(
        provider=_identifier(candidate["provider"]),
        surface=_identifier(candidate["surface"]),
        schema_family=_version(candidate["schema_family"]),
        adapter_version=_version(candidate["adapter_version"]),
        decoder_version=_version(candidate["decoder_version"]),
        canonical_schema_version=_version(candidate["canonical_schema_version"]),
        schema_source=schema_source,
        schema_artifact_version=_version(candidate["schema_artifact_version"]),
        fixture_corpus_version=_version(candidate["fixture_corpus_version"]),
        tested_provider_versions=tested_versions,
        release_state=release_state,
        release_evidence=evidence,
        capabilities=capabilities,
    )


def validate_manifest(value: object) -> CompatibilityManifest:
    """Return an immutable normalized manifest or a sanitized failure."""

    candidate = _object(value)
    _exact_keys(candidate, _ROOT_KEYS)
    if candidate["manifest_version"] != MANIFEST_VERSION:
        raise ManifestError()
    raw_entries = candidate["entries"]
    if (
        not isinstance(raw_entries, list)
        or not raw_entries
        or len(raw_entries) > MAX_ENTRIES
    ):
        raise ManifestError()
    entries = tuple(_entry(item) for item in raw_entries)
    identities = tuple(item.identity for item in entries)
    if identities != tuple(sorted(set(identities))):
        raise ManifestError()
    return CompatibilityManifest(entries=entries)


def load_manifest(path: Path) -> CompatibilityManifest:
    """Read exactly one bounded regular JSON file without discovery or hashing."""

    try:
        if path.is_symlink() or not path.is_file():
            raise ManifestError("manifest_unavailable")
        size = path.stat(follow_symlinks=False).st_size
        if size < 2 or size > MAX_MANIFEST_BYTES:
            raise ManifestError()
        payload = path.read_bytes()
        if len(payload) < 2 or len(payload) > MAX_MANIFEST_BYTES:
            raise ManifestError()
        parsed = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_strict_object,
        )
        return validate_manifest(parsed)
    except ManifestError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise ManifestError() from None


def evaluate_support(
    manifest: CompatibilityManifest,
    *,
    provider: str,
    surface: str,
    schema_family: str,
    provider_version: str,
    capability: str,
) -> str:
    """Evaluate one exact, public compatibility tuple without guessing ranges."""

    safe_provider = _identifier(provider)
    safe_surface = _identifier(surface)
    safe_schema_family = _version(schema_family)
    safe_provider_version = _version(provider_version)
    safe_capability = _identifier(capability)
    matches = tuple(
        entry
        for entry in manifest.entries
        if (
            entry.provider == safe_provider
            and entry.surface == safe_surface
            and entry.schema_family == safe_schema_family
        )
    )
    if not matches:
        return "schema_family_unregistered"
    if all(safe_provider_version not in entry.tested_provider_versions for entry in matches):
        return "provider_version_untested"
    matching_version = tuple(
        entry
        for entry in matches
        if safe_provider_version in entry.tested_provider_versions
    )
    if all(entry.release_state == "blocked" for entry in matching_version):
        return "decoder_blocked"
    if any(
        entry.release_state == "verified"
        and entry.capability_state(safe_capability) == "supported"
        for entry in matching_version
    ):
        return "compatibility_supported"
    if any(
        entry.release_state != "blocked"
        and entry.capability_state(safe_capability) == "partial"
        for entry in matching_version
    ):
        return "capability_partial"
    if any(
        entry.release_state == "experimental"
        and entry.capability_state(safe_capability) == "supported"
        for entry in matching_version
    ):
        return "decoder_experimental"
    return "capability_unsupported"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate one reviewed provider compatibility manifest offline."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--provider")
    parser.add_argument("--surface")
    parser.add_argument("--schema-family")
    parser.add_argument("--provider-version")
    parser.add_argument("--capability")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    query = (
        args.provider,
        args.surface,
        args.schema_family,
        args.provider_version,
        args.capability,
    )
    if any(item is not None for item in query) and not all(
        item is not None for item in query
    ):
        print("query_invalid", file=sys.stderr)
        return 2
    try:
        manifest = load_manifest(args.manifest)
        if all(item is not None for item in query):
            result = evaluate_support(
                manifest,
                provider=args.provider,
                surface=args.surface,
                schema_family=args.schema_family,
                provider_version=args.provider_version,
                capability=args.capability,
            )
            print(result)
            return 0 if result == "compatibility_supported" else 3
    except ManifestError as error:
        print(error.code, file=sys.stderr)
        return 2
    print("manifest_valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
