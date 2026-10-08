"""Checksum-pinned MCPB staging, validation, guarded probe and publication."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import stat
import sys
import tempfile
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit
import zipfile

import anyio
import httpx2
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import SecretStr

from ..application.local_command_process import minimal_environment, run_with_tree_kill
from ..application.mcp_guarded_host import (
    McpGuardedHost,
    McpGuardedHostError,
    McpRemoteConnectionSpec,
    McpStdioConnectionSpec,
)
from ..application.mcp_local_packages import (
    McpLocalPackageCleanupResult,
    McpLocalPackageConfigurationInspectionResult,
    McpLocalPackageInstallResult,
    McpLocalPackageInstallerError,
    McpLocalPackageLaunchExpectation,
    McpLocalPackageStagedUpdateResult,
    McpLocalPackageUninstallResult,
    McpLocalPackageUpdatePublicationResult,
    McpLocalPackageUserConfigurationRequirement,
)
from ..application.mcp_registry_catalog import McpRegistryResolvedLocalPackage
from ..application.runtime_cancellation import RuntimeCleanupUnconfirmed
from ..config import lexical_absolute_path, path_has_symlink_component
from .mcp_guarded_host import (
    McpDnsResolver,
    SystemMcpDnsResolver,
    _PinnedOriginTransport,
    resolve_public_mcp_origin,
)


MAX_MCPB_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_MCPB_EXPANDED_BYTES = 256 * 1024 * 1024
MAX_MCPB_FILE_BYTES = 32 * 1024 * 1024
MAX_MCPB_FILES = 10_000
MAX_MCPB_ENTRIES = 12_000
MAX_MCPB_MANIFEST_BYTES = 256 * 1024
MAX_MCPB_REDIRECTS = 4
MAX_MCPB_COMPRESSION_RATIO = 200

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[0-9a-f]{32}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_USER_CONFIGURATION_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_USER_CONFIGURATION_REFERENCE = re.compile(
    r"\$\{user_config\.([A-Za-z_][A-Za-z0-9_]{0,63})\}"
)
_NODE_VERSION = re.compile(r"^v?([0-9]+\.[0-9]+\.[0-9]+)(?:[-+][0-9A-Za-z.-]+)?$")
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
)
_DENIED_ENVIRONMENT = frozenset(
    {
        "APPDATA",
        "COMSPEC",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "LOCALAPPDATA",
        "NO_PROXY",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "USERPROFILE",
        "WINDIR",
    }
)


class McpArtifactDownloader(Protocol):
    def fetch(self, url: SecretStr, *, maximum_bytes: int) -> bytes: ...


def _endpoint_host(raw: str) -> str:
    try:
        parsed = urlsplit(raw)
        host = (parsed.hostname or "").encode("idna").decode("ascii").casefold()
        port = parsed.port or 443
    except (UnicodeError, ValueError):
        raise McpLocalPackageInstallerError("mcp_package_download_url_invalid") from None
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.fragment)
        or port != 443
    ):
        raise McpLocalPackageInstallerError("mcp_package_download_url_invalid")
    return host


def _redirect_host_allowed(initial_host: str, candidate_host: str) -> bool:
    if initial_host == "github.com":
        return candidate_host == "github.com" or candidate_host.endswith(
            ".githubusercontent.com"
        )
    if initial_host == "gitlab.com":
        return candidate_host in {"gitlab.com", "storage.googleapis.com"} or candidate_host.endswith(
            ".gitlab-static.net"
        )
    return False


class PinnedHttpsMcpArtifactDownloader:
    """Fetch one bounded release asset with per-hop public DNS pinning."""

    def __init__(self, resolver: McpDnsResolver | None = None) -> None:
        self._resolver = resolver or SystemMcpDnsResolver()

    async def _fetch(self, raw_url: str, *, maximum_bytes: int) -> bytes:
        initial_host = _endpoint_host(raw_url)
        if initial_host not in {"github.com", "gitlab.com"}:
            raise McpLocalPackageInstallerError("mcp_package_download_url_invalid")
        current = raw_url
        visited: set[str] = set()
        for _hop in range(MAX_MCPB_REDIRECTS + 1):
            if current in visited:
                raise McpLocalPackageInstallerError("mcp_package_download_redirect_invalid")
            visited.add(current)
            host = _endpoint_host(current)
            if not _redirect_host_allowed(initial_host, host):
                raise McpLocalPackageInstallerError("mcp_package_download_redirect_invalid")
            connection = McpRemoteConnectionSpec(
                management_id="0" * 32,
                catalog_id="0" * 32,
                option_id="0" * 32,
                plan_revision="0" * 64,
                transport="streamable-http",
                endpoint_host=host,
                endpoint=SecretStr(current),
                headers=(),
            )
            try:
                origin = resolve_public_mcp_origin(connection, self._resolver)
                transport = _PinnedOriginTransport(
                    origin,
                    maximum_response_bytes=maximum_bytes,
                )
                async with httpx2.AsyncClient(
                    transport=transport,
                    follow_redirects=False,
                    trust_env=False,
                    timeout=httpx2.Timeout(8.0, connect=5.0),
                    headers={"Accept": "application/octet-stream"},
                ) as client:
                    response = await client.get(current)
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        await response.aclose()
                        if not location or len(location) > 2_048:
                            raise McpLocalPackageInstallerError(
                                "mcp_package_download_redirect_invalid"
                            )
                        current = urljoin(current, location)
                        continue
                    if response.status_code != 200:
                        await response.aclose()
                        raise McpLocalPackageInstallerError(
                            "mcp_package_download_failed"
                        )
                    declared = response.headers.get("content-length")
                    if declared is not None:
                        try:
                            declared_size = int(declared)
                        except ValueError:
                            raise McpLocalPackageInstallerError(
                                "mcp_package_download_invalid"
                            ) from None
                        if not 0 < declared_size <= maximum_bytes:
                            raise McpLocalPackageInstallerError(
                                "mcp_package_download_too_large"
                            )
                    payload = await response.aread()
                    await response.aclose()
                    if not payload or len(payload) > maximum_bytes:
                        raise McpLocalPackageInstallerError(
                            "mcp_package_download_too_large"
                        )
                    return payload
            except McpLocalPackageInstallerError:
                raise
            except McpGuardedHostError as error:
                code = (
                    "mcp_package_download_too_large"
                    if error.code == "mcp_host_response_too_large"
                    else "mcp_package_download_failed"
                )
                raise McpLocalPackageInstallerError(code) from None
            except Exception:
                raise McpLocalPackageInstallerError("mcp_package_download_failed") from None
        raise McpLocalPackageInstallerError("mcp_package_download_redirect_invalid")

    def fetch(self, url: SecretStr, *, maximum_bytes: int) -> bytes:
        if maximum_bytes != MAX_MCPB_ARTIFACT_BYTES:
            raise McpLocalPackageInstallerError("mcp_package_download_bound_invalid")
        return anyio.run(
            lambda: self._fetch(url.get_secret_value(), maximum_bytes=maximum_bytes)
        )


def _ordinary_relative_path(value: str) -> PurePosixPath:
    if (
        not value
        or len(value) > 512
        or "\\" in value
        or "\x00" in value
        or ":" in value
    ):
        raise McpLocalPackageInstallerError("mcp_package_archive_path_invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise McpLocalPackageInstallerError("mcp_package_archive_path_invalid")
    for part in path.parts:
        if part.endswith((" ", ".")) or part.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
            raise McpLocalPackageInstallerError("mcp_package_archive_path_invalid")
    return path


def _safe_file(path: Path) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError:
        raise McpLocalPackageInstallerError("mcp_package_tree_invalid") from None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or bool(getattr(metadata, "st_file_attributes", 0) & 0x400)
    ):
        raise McpLocalPackageInstallerError("mcp_package_tree_invalid")
    return metadata


def _tree_digest(root: Path) -> str:
    pending = [(root, PurePosixPath())]
    files: list[tuple[str, int, str]] = []
    entries = 0
    total = 0
    while pending:
        directory, relative_directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                children = sorted(iterator, key=lambda item: item.name, reverse=True)
        except OSError:
            raise McpLocalPackageInstallerError("mcp_package_tree_invalid") from None
        for child in children:
            entries += 1
            if entries > MAX_MCPB_ENTRIES:
                raise McpLocalPackageInstallerError("mcp_package_archive_too_many_entries")
            try:
                metadata = child.stat(follow_symlinks=False)
            except OSError:
                raise McpLocalPackageInstallerError("mcp_package_tree_invalid") from None
            if stat.S_ISLNK(metadata.st_mode) or bool(
                getattr(metadata, "st_file_attributes", 0) & 0x400
            ):
                raise McpLocalPackageInstallerError("mcp_package_tree_invalid")
            relative = relative_directory / child.name
            candidate = Path(child.path)
            if stat.S_ISDIR(metadata.st_mode):
                pending.append((candidate, relative))
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise McpLocalPackageInstallerError("mcp_package_tree_invalid")
            if len(files) >= MAX_MCPB_FILES or metadata.st_size > MAX_MCPB_FILE_BYTES:
                raise McpLocalPackageInstallerError("mcp_package_archive_too_large")
            digest = hashlib.sha256()
            size = 0
            try:
                with candidate.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        size += len(chunk)
                        total += len(chunk)
                        if size > MAX_MCPB_FILE_BYTES or total > MAX_MCPB_EXPANDED_BYTES:
                            raise McpLocalPackageInstallerError(
                                "mcp_package_archive_too_large"
                            )
                        digest.update(chunk)
                after = candidate.stat()
            except McpLocalPackageInstallerError:
                raise
            except OSError:
                raise McpLocalPackageInstallerError("mcp_package_tree_invalid") from None
            if (
                after.st_size != metadata.st_size
                or after.st_mtime_ns != metadata.st_mtime_ns
                or after.st_ctime_ns != metadata.st_ctime_ns
            ):
                raise McpLocalPackageInstallerError("mcp_package_tree_changed")
            files.append((relative.as_posix(), size, digest.hexdigest()))
    material = json.dumps(
        sorted(files),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(b"prompt-enhancer/mcpb-tree/v1\x00" + material).hexdigest()


def _extract_mcpb(payload: bytes, staging: Path) -> None:
    names: dict[str, str] = {}
    total = 0
    file_count = 0
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except (OSError, zipfile.BadZipFile):
        raise McpLocalPackageInstallerError("mcp_package_archive_invalid") from None
    with archive:
        entries = archive.infolist()
        if not entries or len(entries) > MAX_MCPB_ENTRIES:
            raise McpLocalPackageInstallerError("mcp_package_archive_too_many_entries")
        for info in entries:
            relative = _ordinary_relative_path(info.filename.rstrip("/"))
            mode = (info.external_attr >> 16) & 0xFFFF
            if (
                info.flag_bits & 0x1
                or stat.S_ISLNK(mode)
                or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
                or info.file_size < 0
                or info.compress_size < 0
                or info.file_size > MAX_MCPB_FILE_BYTES
                or (
                    info.file_size > 0
                    and (
                        info.compress_size == 0
                        or info.file_size > info.compress_size * MAX_MCPB_COMPRESSION_RATIO
                    )
                )
            ):
                raise McpLocalPackageInstallerError("mcp_package_archive_invalid")
            for depth in range(1, len(relative.parts) + 1):
                logical = PurePosixPath(*relative.parts[:depth]).as_posix()
                folded = logical.casefold()
                previous = names.setdefault(folded, logical)
                if previous != logical:
                    raise McpLocalPackageInstallerError(
                        "mcp_package_archive_path_collision"
                    )
            target = staging.joinpath(*relative.parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            file_count += 1
            total += info.file_size
            if file_count > MAX_MCPB_FILES or total > MAX_MCPB_EXPANDED_BYTES:
                raise McpLocalPackageInstallerError("mcp_package_archive_too_large")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise McpLocalPackageInstallerError("mcp_package_archive_path_collision")
            written = 0
            try:
                with archive.open(info, "r") as source, target.open("xb") as destination:
                    while chunk := source.read(1024 * 1024):
                        written += len(chunk)
                        if written > info.file_size or written > MAX_MCPB_FILE_BYTES:
                            raise McpLocalPackageInstallerError(
                                "mcp_package_archive_too_large"
                            )
                        destination.write(chunk)
            except McpLocalPackageInstallerError:
                raise
            except (OSError, zipfile.BadZipFile, RuntimeError):
                raise McpLocalPackageInstallerError("mcp_package_archive_invalid") from None
            if written != info.file_size:
                raise McpLocalPackageInstallerError("mcp_package_archive_invalid")
            if os.name != "nt" and mode & 0o111:
                target.chmod(0o700)


def _confined(root: Path, candidate: Path) -> Path:
    absolute = lexical_absolute_path(candidate)
    try:
        absolute.relative_to(root)
    except ValueError:
        raise McpLocalPackageInstallerError("mcp_package_manifest_path_invalid") from None
    if path_has_symlink_component(absolute):
        raise McpLocalPackageInstallerError("mcp_package_manifest_path_invalid")
    return absolute


def _runtime_constraint(value: Any, version: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise McpLocalPackageInstallerError("mcp_package_runtime_constraint_invalid")
    if any(character in value for character in ("^", "~", "|", "*")):
        raise McpLocalPackageInstallerError("mcp_package_runtime_constraint_unsupported")
    normalized = re.sub(r"\s+(?=[<>=!])", ",", value.strip())
    try:
        allowed = SpecifierSet(normalized)
        parsed = Version(version)
    except (InvalidSpecifier, InvalidVersion):
        raise McpLocalPackageInstallerError(
            "mcp_package_runtime_constraint_unsupported"
        ) from None
    if parsed not in allowed:
        raise McpLocalPackageInstallerError("mcp_package_runtime_incompatible")


def _expanded_value(value: str, root: Path) -> str:
    expanded = (
        value.replace("${__dirname}", str(root))
        .replace("${pathSeparator}", os.sep)
        .replace("${/}", os.sep)
    )
    if (
        "${" in expanded
        or any(character in expanded for character in ("\x00", "\r", "\n"))
        or len(expanded) > 4_096
    ):
        raise McpLocalPackageInstallerError("mcp_package_manifest_value_unsupported")
    return expanded


def _canonical_user_configuration_value(
    specification: Mapping[str, Any],
    value: Any,
) -> str:
    kind = specification.get("type")
    if kind == "boolean":
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, str) and value in {"true", "false"}:
            rendered = value
        else:
            raise McpLocalPackageInstallerError(
                "mcp_package_user_configuration_invalid"
            )
    elif kind == "number":
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise McpLocalPackageInstallerError(
                "mcp_package_user_configuration_invalid"
            )
        rendered = str(value)
        try:
            number = Decimal(rendered)
        except InvalidOperation:
            raise McpLocalPackageInstallerError(
                "mcp_package_user_configuration_invalid"
            ) from None
        if not number.is_finite():
            raise McpLocalPackageInstallerError(
                "mcp_package_user_configuration_invalid"
            )
        for bound_name, predicate in (
            ("min", lambda bound: number < bound),
            ("max", lambda bound: number > bound),
        ):
            raw_bound = specification.get(bound_name)
            if raw_bound is None:
                continue
            if isinstance(raw_bound, bool) or not isinstance(raw_bound, (int, float)):
                raise McpLocalPackageInstallerError(
                    "mcp_package_user_configuration_invalid"
                )
            bound = Decimal(str(raw_bound))
            if not bound.is_finite() or predicate(bound):
                raise McpLocalPackageInstallerError(
                    "mcp_package_user_configuration_invalid"
                )
    elif kind in {"string", "directory", "file"}:
        if not isinstance(value, str):
            raise McpLocalPackageInstallerError(
                "mcp_package_user_configuration_invalid"
            )
        rendered = value
        if kind in {"directory", "file"} and not (
            PureWindowsPath(rendered).is_absolute()
            or PurePosixPath(rendered).is_absolute()
        ):
            raise McpLocalPackageInstallerError(
                "mcp_package_user_configuration_invalid"
            )
    else:
        raise McpLocalPackageInstallerError(
            "mcp_package_user_configuration_unsupported"
        )
    if (
        not rendered
        or any(character in rendered for character in ("\x00", "\r", "\n"))
        or len(rendered.encode("utf-8")) > 2_048
        or (
            kind in {"directory", "file"}
            and any(character in rendered for character in "*?[]")
        )
    ):
        raise McpLocalPackageInstallerError(
            "mcp_package_user_configuration_invalid"
        )
    return rendered


def _user_configuration_contract(
    manifest: Mapping[str, Any],
    *,
    manifest_digest: str,
) -> tuple[
    tuple[McpLocalPackageUserConfigurationRequirement, ...],
    dict[str, Mapping[str, Any]],
    dict[str, str],
    str,
]:
    raw_configuration = manifest.get("user_config")
    if raw_configuration is None:
        configuration: Mapping[str, Any] = {}
    elif not isinstance(raw_configuration, Mapping) or len(raw_configuration) > 32:
        raise McpLocalPackageInstallerError(
            "mcp_package_user_configuration_unsupported"
        )
    else:
        configuration = raw_configuration
    server = manifest.get("server")
    if not isinstance(server, Mapping):
        raise McpLocalPackageInstallerError("mcp_package_manifest_invalid")
    raw_execution = server.get("mcp_config")
    if raw_execution is None:
        execution: Mapping[str, Any] = {}
    elif not isinstance(raw_execution, Mapping):
        raise McpLocalPackageInstallerError("mcp_package_manifest_invalid")
    else:
        execution = raw_execution
    raw_arguments = execution.get("args")
    if raw_arguments is None:
        arguments: Sequence[Any] = ()
    elif (
        not isinstance(raw_arguments, Sequence)
        or isinstance(raw_arguments, (str, bytes, bytearray))
        or len(raw_arguments) > 64
        or any(not isinstance(item, str) for item in raw_arguments)
    ):
        raise McpLocalPackageInstallerError("mcp_package_manifest_invalid")
    else:
        arguments = raw_arguments
    raw_environment = execution.get("env")
    if raw_environment is None:
        environment: Mapping[str, Any] = {}
    elif (
        not isinstance(raw_environment, Mapping)
        or len(raw_environment) > 32
        or any(
            not isinstance(name, str)
            or _ENV_NAME.fullmatch(name) is None
            or name.upper() in _DENIED_ENVIRONMENT
            or not isinstance(item, str)
            for name, item in raw_environment.items()
        )
    ):
        raise McpLocalPackageInstallerError("mcp_package_manifest_invalid")
    else:
        environment = raw_environment

    argument_keys: set[str] = set()
    environment_keys: set[str] = set()
    for target, values in (
        (argument_keys, arguments),
        (environment_keys, environment.values()),
    ):
        for raw in values:
            assert isinstance(raw, str)
            matches = tuple(_USER_CONFIGURATION_REFERENCE.finditer(raw))
            if "${user_config." in _USER_CONFIGURATION_REFERENCE.sub("", raw):
                raise McpLocalPackageInstallerError(
                    "mcp_package_user_configuration_invalid"
                )
            target.update(match.group(1) for match in matches)
    referenced = argument_keys | environment_keys
    if any(key not in configuration for key in referenced):
        raise McpLocalPackageInstallerError(
            "mcp_package_user_configuration_invalid"
        )
    if any(key not in referenced for key in configuration):
        raise McpLocalPackageInstallerError(
            "mcp_package_user_configuration_invalid"
        )
    if argument_keys & environment_keys:
        raise McpLocalPackageInstallerError(
            "mcp_package_user_configuration_unsupported"
        )

    requirements: list[McpLocalPackageUserConfigurationRequirement] = []
    specifications: dict[str, Mapping[str, Any]] = {}
    defaults: dict[str, str] = {}
    normalized_schema: list[dict[str, Any]] = []
    for key, raw_specification in configuration.items():
        if key not in referenced:
            continue
        if (
            not isinstance(key, str)
            or _USER_CONFIGURATION_KEY.fullmatch(key) is None
            or not isinstance(raw_specification, Mapping)
            or raw_specification.get("type")
            not in {"string", "number", "boolean", "directory", "file"}
            or any(
                field in raw_specification
                and not isinstance(raw_specification.get(field), bool)
                for field in ("required", "sensitive", "multiple")
            )
        ):
            raise McpLocalPackageInstallerError(
                "mcp_package_user_configuration_unsupported"
            )
        if raw_specification.get("multiple") is True:
            raise McpLocalPackageInstallerError(
                "mcp_package_user_configuration_unsupported"
            )
        sensitive = raw_specification.get("sensitive") is True
        required = raw_specification.get("required") is True
        if sensitive and (key in argument_keys or not required):
            raise McpLocalPackageInstallerError(
                "mcp_package_sensitive_configuration_unsupported"
            )
        default_declared = "default" in raw_specification
        if default_declared:
            if sensitive:
                raise McpLocalPackageInstallerError(
                    "mcp_package_sensitive_configuration_unsupported"
                )
            defaults[key] = _canonical_user_configuration_value(
                raw_specification,
                raw_specification.get("default"),
            )
        kind = str(raw_specification["type"])
        value_format = (
            "filepath" if kind in {"directory", "file"} else kind
        )
        requirement = McpLocalPackageUserConfigurationRequirement(
            requirement_id=hashlib.sha256(
                (
                    "prompt-enhancer/mcpb-user-configuration/v1\x00"
                    + manifest_digest
                    + "\x00"
                    + key
                ).encode("utf-8")
            ).hexdigest()[:32],
            key=key,
            location=(
                "package_argument"
                if key in argument_keys
                else "environment_variable"
            ),
            required=required,
            secret=sensitive,
            format=value_format,
            user_value_needed=required and not default_declared,
            default_declared=default_declared,
        )
        requirements.append(requirement)
        specifications[key] = raw_specification
        normalized_schema.append(requirement.model_dump(mode="json"))
    schema_digest = hashlib.sha256(
        json.dumps(
            normalized_schema,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).hexdigest()
    return tuple(requirements), specifications, defaults, schema_digest


def _resolved_user_configuration(
    manifest: Mapping[str, Any],
    *,
    manifest_digest: str,
    supplied: Mapping[str, SecretStr] | None,
) -> dict[str, str | None]:
    requirements, specifications, defaults, _schema_digest = (
        _user_configuration_contract(manifest, manifest_digest=manifest_digest)
    )
    provided = supplied or {}
    expected = {
        item.key for item in requirements if item.secret or item.user_value_needed
    }
    if (
        set(provided) != expected
        or any(not isinstance(value, SecretStr) for value in provided.values())
    ):
        raise McpLocalPackageInstallerError(
            "mcp_package_user_configuration_required"
        )
    resolved: dict[str, str | None] = {}
    for requirement in requirements:
        if requirement.key in provided:
            value: Any = provided[requirement.key].get_secret_value()
            resolved[requirement.key] = _canonical_user_configuration_value(
                specifications[requirement.key],
                value,
            )
        elif requirement.key in defaults:
            resolved[requirement.key] = defaults[requirement.key]
        else:
            resolved[requirement.key] = None
    return resolved


def _substitute_user_configuration(
    value: str,
    resolved: Mapping[str, str | None],
) -> str | None:
    exact = _USER_CONFIGURATION_REFERENCE.fullmatch(value)
    if exact is not None and resolved.get(exact.group(1)) is None:
        return None

    def replacement(match: re.Match[str]) -> str:
        configured = resolved.get(match.group(1))
        return "" if configured is None else configured

    substituted = _USER_CONFIGURATION_REFERENCE.sub(replacement, value)
    if "${user_config." in substituted:
        raise McpLocalPackageInstallerError(
            "mcp_package_user_configuration_invalid"
        )
    return substituted


def _manifest_execution(
    manifest: Mapping[str, Any],
    root: Path,
    *,
    manifest_digest: str,
    user_configuration: Mapping[str, SecretStr] | None = None,
) -> tuple[str, tuple[str, ...], dict[str, str], str, str | None]:
    resolved_user_configuration = _resolved_user_configuration(
        manifest,
        manifest_digest=manifest_digest,
        supplied=user_configuration,
    )
    server = manifest.get("server")
    if not isinstance(server, Mapping):
        raise McpLocalPackageInstallerError("mcp_package_manifest_invalid")
    runtime_kind = server.get("type")
    if runtime_kind not in {"node", "python", "binary"}:
        raise McpLocalPackageInstallerError("mcp_package_runtime_unsupported")
    entry_value = server.get("entry_point")
    if not isinstance(entry_value, str):
        raise McpLocalPackageInstallerError("mcp_package_manifest_invalid")
    entry_relative = _ordinary_relative_path(entry_value)
    entry = _confined(root, root.joinpath(*entry_relative.parts))
    if os.name == "nt" and runtime_kind == "binary" and not entry.is_file():
        executable_candidate = entry.with_suffix(entry.suffix + ".exe")
        if executable_candidate.is_file():
            entry = _confined(root, executable_candidate)
    _safe_file(entry)

    compatibility = manifest.get("compatibility")
    if compatibility is not None and not isinstance(compatibility, Mapping):
        raise McpLocalPackageInstallerError("mcp_package_manifest_invalid")
    compatibility = compatibility or {}
    platforms = compatibility.get("platforms")
    if platforms is not None:
        if (
            not isinstance(platforms, Sequence)
            or isinstance(platforms, (str, bytes, bytearray))
            or not platforms
            or any(item not in {"darwin", "win32", "linux"} for item in platforms)
            or sys.platform not in platforms
        ):
            raise McpLocalPackageInstallerError("mcp_package_platform_incompatible")
    runtimes = compatibility.get("runtimes")
    if runtimes is not None and not isinstance(runtimes, Mapping):
        raise McpLocalPackageInstallerError("mcp_package_manifest_invalid")
    runtimes = runtimes or {}

    if runtime_kind == "node":
        resolved = shutil.which("node")
        if resolved is None:
            raise McpLocalPackageInstallerError("mcp_package_runtime_unavailable")
        executable = _confined(lexical_absolute_path(Path(resolved).parent), Path(resolved))
        _safe_file(executable)
        try:
            version_check = run_with_tree_kill(
                [str(executable), "--version"],
                timeout=3.0,
                env=minimal_environment(),
            )
        except RuntimeCleanupUnconfirmed:
            raise McpLocalPackageInstallerError(
                "mcp_package_runtime_cleanup_unconfirmed",
                cleanup_required=True,
                process_tree_cleanup="unconfirmed",
            ) from None
        except Exception:
            raise McpLocalPackageInstallerError("mcp_package_runtime_unavailable") from None
        match = _NODE_VERSION.fullmatch(version_check.stdout.strip())
        if version_check.returncode != 0 or match is None:
            raise McpLocalPackageInstallerError("mcp_package_runtime_unavailable")
        runtime_version = match.group(1)
        _runtime_constraint(runtimes.get("node"), runtime_version)
        default_arguments = (str(entry),)
    elif runtime_kind == "python":
        executable = lexical_absolute_path(Path(sys.executable))
        _safe_file(executable)
        runtime_version = ".".join(str(item) for item in sys.version_info[:3])
        _runtime_constraint(runtimes.get("python"), runtime_version)
        default_arguments = ("-I", str(entry))
    else:
        executable = entry
        runtime_version = None
        default_arguments = ()

    configuration = server.get("mcp_config")
    if configuration is not None and not isinstance(configuration, Mapping):
        raise McpLocalPackageInstallerError("mcp_package_manifest_invalid")
    configuration = configuration or {}
    if configuration.get("platform_overrides"):
        raise McpLocalPackageInstallerError("mcp_package_platform_override_unsupported")
    command = configuration.get("command")
    if command is not None:
        if not isinstance(command, str) or not command or len(command) > 512:
            raise McpLocalPackageInstallerError("mcp_package_manifest_invalid")
        command_name = Path(command).name.casefold()
        allowed_commands = {
            "node": {"node", "node.exe"},
            "python": {"python", "python.exe", "python3", "python3.exe"},
            "binary": {entry.name.casefold()},
        }[runtime_kind]
        if command_name not in allowed_commands:
            raise McpLocalPackageInstallerError("mcp_package_command_unsupported")

    raw_arguments = configuration.get("args")
    if raw_arguments is None:
        arguments = list(default_arguments)
    else:
        if (
            not isinstance(raw_arguments, Sequence)
            or isinstance(raw_arguments, (str, bytes, bytearray))
            or len(raw_arguments) > 64
            or any(not isinstance(item, str) for item in raw_arguments)
        ):
            raise McpLocalPackageInstallerError("mcp_package_manifest_invalid")
        arguments = []
        for raw in raw_arguments:
            configured = _substitute_user_configuration(
                raw,
                resolved_user_configuration,
            )
            if configured is None:
                continue
            expanded = _expanded_value(configured, root)
            path_candidate: Path | None = None
            if (
                _USER_CONFIGURATION_REFERENCE.fullmatch(raw) is None
                and Path(expanded).is_absolute()
            ):
                path_candidate = Path(expanded)
            elif (
                _USER_CONFIGURATION_REFERENCE.fullmatch(raw) is None
                and ("/" in expanded or "\\" in expanded)
                and not expanded.startswith("-")
            ):
                path_candidate = root / expanded
            if path_candidate is not None:
                expanded = str(_confined(root, path_candidate))
            arguments.append(expanded)
        if runtime_kind in {"node", "python"} and str(entry) not in arguments:
            arguments = (["-I"] if runtime_kind == "python" else []) + [
                str(entry),
                *arguments,
            ]

    raw_environment = configuration.get("env")
    if raw_environment is None:
        environment: dict[str, str] = {}
    else:
        if not isinstance(raw_environment, Mapping) or len(raw_environment) > 32:
            raise McpLocalPackageInstallerError("mcp_package_manifest_invalid")
        environment = {}
        for name, raw in raw_environment.items():
            if (
                not isinstance(name, str)
                or _ENV_NAME.fullmatch(name) is None
                or name.upper() in _DENIED_ENVIRONMENT
                or not isinstance(raw, str)
            ):
                raise McpLocalPackageInstallerError(
                    "mcp_package_environment_unsupported"
                )
            configured = _substitute_user_configuration(
                raw,
                resolved_user_configuration,
            )
            if configured is None:
                continue
            expanded = _expanded_value(configured, root)
            if name.upper() in {"PYTHONPATH", "NODE_PATH"}:
                for part in expanded.split(os.pathsep):
                    if part:
                        _confined(root, Path(part) if Path(part).is_absolute() else root / part)
            environment[name] = expanded
    return str(executable), tuple(arguments), environment, runtime_kind, runtime_version


def _apply_registry_execution_configuration(
    package: McpRegistryResolvedLocalPackage | None,
    arguments: tuple[str, ...],
    environment: Mapping[str, str],
) -> tuple[tuple[str, ...], dict[str, str]]:
    if package is None:
        return arguments, dict(environment)
    if package.execution_configuration_state != "resolved":
        raise McpLocalPackageInstallerError("mcp_package_configuration_invalid")
    try:
        runtime_arguments = tuple(
            item.get_secret_value() for item in package.runtime_arguments
        )
        package_arguments = tuple(
            item.get_secret_value() for item in package.package_arguments
        )
    except Exception:
        raise McpLocalPackageInstallerError(
            "mcp_package_configuration_invalid"
        ) from None
    combined = (*runtime_arguments, *arguments, *package_arguments)
    if (
        len(combined) > 128
        or any(
            not item
            or any(character in item for character in ("\x00", "\r", "\n"))
            or len(item.encode("utf-8")) > 2_048
            for item in combined
        )
    ):
        raise McpLocalPackageInstallerError("mcp_package_configuration_invalid")
    merged = dict(environment)
    seen = {name.casefold() for name in merged}
    for declaration in package.environment:
        name = declaration.name
        value = declaration.value.get_secret_value()
        if (
            _ENV_NAME.fullmatch(name) is None
            or name.upper() in _DENIED_ENVIRONMENT
            or name.casefold() in seen
            or not value
            or any(character in value for character in ("\x00", "\r", "\n"))
            or len(value.encode("utf-8")) > 2_048
        ):
            raise McpLocalPackageInstallerError(
                "mcp_package_environment_unsupported"
            )
        seen.add(name.casefold())
        merged[name] = value
    return tuple(combined), merged


def _parse_manifest(staging: Path) -> tuple[Mapping[str, Any], str, str]:
    manifest_path = staging / "manifest.json"
    metadata = _safe_file(manifest_path)
    if not 0 < metadata.st_size <= MAX_MCPB_MANIFEST_BYTES:
        raise McpLocalPackageInstallerError("mcp_package_manifest_too_large")
    try:
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise McpLocalPackageInstallerError("mcp_package_manifest_invalid") from None
    if not isinstance(manifest, Mapping):
        raise McpLocalPackageInstallerError("mcp_package_manifest_invalid")
    version = manifest.get("manifest_version")
    author = manifest.get("author")
    required_text = (manifest.get("name"), manifest.get("version"), manifest.get("description"))
    if (
        version not in {"0.3", "0.4"}
        or any(not isinstance(item, str) or not item or len(item) > 1_024 for item in required_text)
        or not isinstance(author, Mapping)
        or not isinstance(author.get("name"), str)
        or not author.get("name")
    ):
        raise McpLocalPackageInstallerError("mcp_package_manifest_invalid")
    license_value = manifest.get("license")
    if (
        not isinstance(license_value, str)
        or not license_value.strip()
        or len(license_value) > 128
        or any(ord(character) < 32 for character in license_value)
    ):
        raise McpLocalPackageInstallerError("mcp_package_license_not_declared")
    manifest_digest = hashlib.sha256(raw).hexdigest()
    _user_configuration_contract(manifest, manifest_digest=manifest_digest)
    return manifest, str(version), manifest_digest


def _remove_verified_tree(root: Path, candidate: Path) -> bool:
    if candidate.parent != root or not candidate.exists():
        return not candidate.exists()
    try:
        _tree_digest(candidate)
        shutil.rmtree(candidate)
    except Exception:
        return False
    return not candidate.exists()


class McpbPackageInstaller:
    """Install one exact MCPB without shells, terminals or retained hosts."""

    def __init__(
        self,
        packages_root: Path,
        downloader: McpArtifactDownloader,
        host: McpGuardedHost,
    ) -> None:
        self._root = lexical_absolute_path(packages_root)
        self._downloader = downloader
        self._host = host

    def supports(self, registry_type: str) -> bool:
        return registry_type == "mcpb"

    def _installed_package_root(self, management_id: str) -> Path:
        """Resolve one existing installed tree without creating directories."""

        if _ID.fullmatch(management_id) is None:
            raise McpLocalPackageInstallerError("mcp_package_identity_invalid")
        root = self._root
        if not root.exists():
            raise McpLocalPackageInstallerError("mcp_package_install_required")
        if (
            path_has_symlink_component(root.parent)
            or path_has_symlink_component(root)
            or not root.is_dir()
        ):
            raise McpLocalPackageInstallerError("mcp_package_root_unsafe")
        installed = root / "installed"
        if not installed.exists():
            raise McpLocalPackageInstallerError("mcp_package_install_required")
        if path_has_symlink_component(installed) or not installed.is_dir():
            raise McpLocalPackageInstallerError("mcp_package_root_unsafe")
        package = installed / management_id
        if not package.exists():
            raise McpLocalPackageInstallerError("mcp_package_install_required")
        if path_has_symlink_component(package) or not package.is_dir():
            raise McpLocalPackageInstallerError("mcp_package_root_unsafe")
        return package

    def resolve_installed_connection(
        self,
        *,
        management_id: str,
        expected: McpLocalPackageLaunchExpectation,
        configuration: McpRegistryResolvedLocalPackage | None = None,
        user_configuration: Mapping[str, SecretStr] | None = None,
    ) -> McpStdioConnectionSpec:
        """Re-derive one exact launch without retaining or starting a host."""

        package = self._installed_package_root(management_id)
        before = _tree_digest(package)
        if before != expected.tree_digest:
            raise McpLocalPackageInstallerError(
                "mcp_package_installed_tree_changed",
                cleanup_required=True,
            )
        try:
            manifest, manifest_version, manifest_digest = _parse_manifest(package)
            executable, arguments, environment, runtime_kind, runtime_version = (
                _manifest_execution(
                    manifest,
                    package,
                    manifest_digest=manifest_digest,
                    user_configuration=user_configuration,
                )
            )
            arguments, environment = _apply_registry_execution_configuration(
                configuration,
                arguments,
                environment,
            )
        except McpLocalPackageInstallerError as error:
            try:
                changed = _tree_digest(package) != before
            except McpLocalPackageInstallerError:
                changed = True
            if changed:
                raise McpLocalPackageInstallerError(
                    "mcp_package_installed_tree_changed",
                    cleanup_required=True,
                ) from None
            raise
        after = _tree_digest(package)
        if after != before:
            raise McpLocalPackageInstallerError(
                "mcp_package_installed_tree_changed",
                cleanup_required=True,
            )
        if (
            manifest_digest != expected.manifest_digest
            or manifest_version != expected.manifest_version
        ):
            raise McpLocalPackageInstallerError(
                "mcp_package_manifest_evidence_mismatch",
                cleanup_required=True,
            )
        if (
            runtime_kind != expected.runtime_kind
            or runtime_version != expected.runtime_version
        ):
            raise McpLocalPackageInstallerError("mcp_package_runtime_changed")
        return McpStdioConnectionSpec(
            management_id=management_id,
            executable=executable,
            arguments=arguments,
            environment=environment,
            working_directory=str(package),
        )

    def _prepare_roots(self) -> tuple[Path, Path, Path, Path]:
        if path_has_symlink_component(self._root.parent) or path_has_symlink_component(
            self._root
        ):
            raise McpLocalPackageInstallerError("mcp_package_root_unsafe")
        try:
            self._root.mkdir(mode=0o700, parents=True, exist_ok=True)
            staging = self._root / ".staging"
            installed = self._root / "installed"
            quarantine = self._root / ".quarantine"
            rollback = self._root / ".rollback"
            staging.mkdir(mode=0o700, exist_ok=True)
            installed.mkdir(mode=0o700, exist_ok=True)
            quarantine.mkdir(mode=0o700, exist_ok=True)
            rollback.mkdir(mode=0o700, exist_ok=True)
            if os.name != "nt":
                for directory in (
                    self._root,
                    staging,
                    installed,
                    quarantine,
                    rollback,
                ):
                    directory.chmod(0o700)
        except OSError:
            raise McpLocalPackageInstallerError("mcp_package_root_unavailable") from None
        if any(
            path_has_symlink_component(directory) or not directory.is_dir()
            for directory in (self._root, staging, installed, quarantine, rollback)
        ):
            raise McpLocalPackageInstallerError("mcp_package_root_unsafe")
        return staging, installed, quarantine, rollback

    def inspect_configuration(
        self,
        package: McpRegistryResolvedLocalPackage,
        *,
        management_id: str,
    ) -> McpLocalPackageConfigurationInspectionResult:
        """Inspect one checksum-pinned archive without retaining or executing it."""

        if (
            _ID.fullmatch(management_id) is None
            or package.registry_type != "mcpb"
            or package.execution_configuration_state != "inspection_only"
            or _DIGEST.fullmatch(package.file_sha256) is None
        ):
            raise McpLocalPackageInstallerError("mcp_package_identity_invalid")
        staging_root, _installed, _quarantine, _rollback = self._prepare_roots()
        try:
            staging = Path(
                tempfile.mkdtemp(prefix=f"{management_id}-inspect-", dir=staging_root)
            )
        except OSError:
            raise McpLocalPackageInstallerError(
                "mcp_package_staging_unavailable"
            ) from None

        result: McpLocalPackageConfigurationInspectionResult | None = None
        problem: McpLocalPackageInstallerError | None = None
        try:
            payload = self._downloader.fetch(
                package.package_identifier,
                maximum_bytes=MAX_MCPB_ARTIFACT_BYTES,
            )
            artifact_digest = hashlib.sha256(payload).hexdigest()
            if artifact_digest != package.file_sha256:
                raise McpLocalPackageInstallerError(
                    "mcp_package_integrity_mismatch"
                )
            _extract_mcpb(payload, staging)
            manifest, manifest_version, manifest_digest = _parse_manifest(staging)
            requirements, _specifications, _defaults, schema_digest = (
                _user_configuration_contract(
                    manifest,
                    manifest_digest=manifest_digest,
                )
            )
            result = McpLocalPackageConfigurationInspectionResult(
                artifact_sha256=artifact_digest,
                artifact_bytes=len(payload),
                manifest_digest=manifest_digest,
                manifest_version=manifest_version,
                configuration_schema_digest=schema_digest,
                requirements=requirements,
            )
        except McpLocalPackageInstallerError as error:
            problem = error
        except Exception:
            problem = McpLocalPackageInstallerError(
                "mcp_package_configuration_inspection_failed"
            )
        finally:
            if staging.exists() and not _remove_verified_tree(staging_root, staging):
                problem = McpLocalPackageInstallerError(
                    "mcp_package_cleanup_unconfirmed",
                    cleanup_required=True,
                )
        if problem is not None:
            raise problem
        assert result is not None
        return result

    def install_and_probe(
        self,
        package: McpRegistryResolvedLocalPackage,
        *,
        management_id: str,
        user_configuration: Mapping[str, SecretStr] | None = None,
    ) -> McpLocalPackageInstallResult:
        if (
            _ID.fullmatch(management_id) is None
            or package.registry_type != "mcpb"
            or package.execution_configuration_state != "resolved"
        ):
            raise McpLocalPackageInstallerError("mcp_package_identity_invalid")
        if _DIGEST.fullmatch(package.file_sha256) is None:
            raise McpLocalPackageInstallerError("mcp_package_integrity_required")
        staging_root, installed_root, _quarantine_root, _rollback_root = (
            self._prepare_roots()
        )
        final = installed_root / management_id
        if final.exists():
            raise McpLocalPackageInstallerError(
                "mcp_package_existing_tree_requires_cleanup",
                cleanup_required=True,
            )
        try:
            staging = Path(
                tempfile.mkdtemp(prefix=f"{management_id}-", dir=staging_root)
            )
        except OSError:
            raise McpLocalPackageInstallerError("mcp_package_staging_unavailable") from None
        published = False
        process_cleanup = "not_applicable"
        problem: McpLocalPackageInstallerError | None = None
        result: McpLocalPackageInstallResult | None = None
        try:
            payload = self._downloader.fetch(
                package.package_identifier,
                maximum_bytes=MAX_MCPB_ARTIFACT_BYTES,
            )
            artifact_digest = hashlib.sha256(payload).hexdigest()
            if artifact_digest != package.file_sha256:
                raise McpLocalPackageInstallerError("mcp_package_integrity_mismatch")
            _extract_mcpb(payload, staging)
            manifest, manifest_version, manifest_digest = _parse_manifest(staging)
            executable, arguments, environment, runtime_kind, runtime_version = (
                _manifest_execution(
                    manifest,
                    staging,
                    manifest_digest=manifest_digest,
                    user_configuration=user_configuration,
                )
            )
            arguments, environment = _apply_registry_execution_configuration(
                package,
                arguments,
                environment,
            )
            tree_digest = _tree_digest(staging)
            try:
                probe = self._host.probe(
                    McpStdioConnectionSpec(
                        management_id=management_id,
                        executable=executable,
                        arguments=arguments,
                        environment=environment,
                        working_directory=str(staging),
                    )
                )
                process_cleanup = probe.process_tree_cleanup
            except McpGuardedHostError as error:
                cleanup_unconfirmed = error.code == "mcp_host_cleanup_unconfirmed"
                raise McpLocalPackageInstallerError(
                    error.code,
                    cleanup_required=cleanup_unconfirmed,
                    process_tree_cleanup=(
                        "unconfirmed" if cleanup_unconfirmed else "verified"
                    ),
                ) from None
            if _tree_digest(staging) != tree_digest:
                raise McpLocalPackageInstallerError(
                    "mcp_package_probe_modified_tree"
                )
            result = McpLocalPackageInstallResult(
                artifact_sha256=artifact_digest,
                artifact_bytes=len(payload),
                tree_digest=tree_digest,
                manifest_digest=manifest_digest,
                manifest_version=manifest_version,
                runtime_kind=runtime_kind,
                runtime_version=runtime_version,
                probe=probe,
            )
            try:
                os.replace(staging, final)
            except OSError:
                raise McpLocalPackageInstallerError(
                    "mcp_package_publication_failed"
                ) from None
            published = True
            return result
        except McpLocalPackageInstallerError as error:
            problem = error
        except Exception:
            problem = McpLocalPackageInstallerError("mcp_package_install_failed")
        finally:
            if not published and staging.exists():
                cleaned = _remove_verified_tree(staging_root, staging)
                if not cleaned:
                    problem = McpLocalPackageInstallerError(
                        "mcp_package_cleanup_unconfirmed",
                        cleanup_required=True,
                        process_tree_cleanup=(
                            "unconfirmed"
                            if process_cleanup == "unconfirmed"
                            else process_cleanup
                        ),
                    )
        assert problem is not None
        raise problem

    def rollback_publication(
        self,
        *,
        management_id: str,
        expected_tree_digest: str,
    ) -> bool:
        if _ID.fullmatch(management_id) is None or _DIGEST.fullmatch(
            expected_tree_digest
        ) is None:
            return False
        try:
            _staging, installed, _quarantine, _rollback = self._prepare_roots()
            final = installed / management_id
            if not final.exists():
                return True
            if _tree_digest(final) != expected_tree_digest:
                return False
            return _remove_verified_tree(installed, final)
        except Exception:
            return False

    @staticmethod
    def _valid_uninstall_identity(
        management_id: str,
        operation_id: str,
        expected_tree_digest: str,
    ) -> bool:
        return (
            _ID.fullmatch(management_id) is not None
            and _ID.fullmatch(operation_id) is not None
            and _DIGEST.fullmatch(expected_tree_digest) is not None
        )

    def prepare_uninstall(
        self,
        *,
        management_id: str,
        operation_id: str,
        expected_tree_digest: str,
    ) -> McpLocalPackageUninstallResult:
        """Atomically quarantine one exact installed tree before DB commit."""

        if not self._valid_uninstall_identity(
            management_id, operation_id, expected_tree_digest
        ):
            raise McpLocalPackageInstallerError("mcp_package_identity_invalid")
        try:
            _staging, installed, quarantine, _rollback = self._prepare_roots()
            final = installed / management_id
            held = quarantine / operation_id
            if final.exists() and held.exists():
                raise McpLocalPackageInstallerError(
                    "mcp_package_uninstall_state_conflict",
                    cleanup_required=True,
                )
            if held.exists():
                if _tree_digest(held) != expected_tree_digest:
                    raise McpLocalPackageInstallerError(
                        "mcp_package_quarantine_tree_changed",
                        cleanup_required=True,
                    )
                return McpLocalPackageUninstallResult(
                    tree_digest=expected_tree_digest
                )
            if not final.exists():
                raise McpLocalPackageInstallerError(
                    "mcp_package_installed_tree_missing",
                    cleanup_required=True,
                )
            if _tree_digest(final) != expected_tree_digest:
                raise McpLocalPackageInstallerError(
                    "mcp_package_installed_tree_changed",
                    cleanup_required=True,
                )
            try:
                os.replace(final, held)
            except OSError:
                raise McpLocalPackageInstallerError(
                    "mcp_package_uninstall_quarantine_failed"
                ) from None
            if _tree_digest(held) != expected_tree_digest:
                restored = False
                try:
                    if not final.exists():
                        os.replace(held, final)
                        restored = _tree_digest(final) == expected_tree_digest
                except Exception:
                    restored = False
                raise McpLocalPackageInstallerError(
                    "mcp_package_uninstall_tree_changed",
                    cleanup_required=not restored,
                )
            return McpLocalPackageUninstallResult(
                tree_digest=expected_tree_digest
            )
        except McpLocalPackageInstallerError:
            raise
        except Exception:
            raise McpLocalPackageInstallerError(
                "mcp_package_uninstall_failed",
                cleanup_required=True,
            ) from None

    def commit_uninstall(
        self,
        *,
        management_id: str,
        operation_id: str,
        expected_tree_digest: str,
    ) -> bool:
        """Delete only the exact quarantined tree; safe to retry."""

        if not self._valid_uninstall_identity(
            management_id, operation_id, expected_tree_digest
        ):
            return False
        try:
            _staging, installed, quarantine, _rollback = self._prepare_roots()
            final = installed / management_id
            held = quarantine / operation_id
            if final.exists():
                return False
            if not held.exists():
                return True
            if _tree_digest(held) != expected_tree_digest:
                return False
            return _remove_verified_tree(quarantine, held)
        except Exception:
            return False

    def rollback_uninstall(
        self,
        *,
        management_id: str,
        operation_id: str,
        expected_tree_digest: str,
    ) -> bool:
        """Restore a verified quarantined tree when preparation cannot commit."""

        if not self._valid_uninstall_identity(
            management_id, operation_id, expected_tree_digest
        ):
            return False
        try:
            _staging, installed, quarantine, _rollback = self._prepare_roots()
            final = installed / management_id
            held = quarantine / operation_id
            if final.exists():
                return not held.exists() and _tree_digest(final) == expected_tree_digest
            if not held.exists() or _tree_digest(held) != expected_tree_digest:
                return False
            os.replace(held, final)
            return _tree_digest(final) == expected_tree_digest
        except Exception:
            return False

    def complete_interrupted_uninstall(
        self,
        *,
        management_id: str,
        operation_id: str,
        expected_tree_digest: str,
    ) -> McpLocalPackageCleanupResult:
        """Finish a journaled uninstall from installed, quarantined, or absent state."""

        if not self._valid_uninstall_identity(
            management_id, operation_id, expected_tree_digest
        ):
            raise McpLocalPackageInstallerError("mcp_package_identity_invalid")
        try:
            _staging, installed, quarantine, _rollback = self._prepare_roots()
            final = installed / management_id
            held = quarantine / operation_id
            if final.exists() or held.exists():
                self.prepare_uninstall(
                    management_id=management_id,
                    operation_id=operation_id,
                    expected_tree_digest=expected_tree_digest,
                )
                if not self.commit_uninstall(
                    management_id=management_id,
                    operation_id=operation_id,
                    expected_tree_digest=expected_tree_digest,
                ):
                    raise McpLocalPackageInstallerError(
                        "mcp_package_uninstall_cleanup_unconfirmed",
                        cleanup_required=True,
                    )
                changed = True
            else:
                changed = False
            if final.exists() or held.exists():
                raise McpLocalPackageInstallerError(
                    "mcp_package_uninstall_cleanup_unconfirmed",
                    cleanup_required=True,
                )
            return McpLocalPackageCleanupResult(
                tree_digest=expected_tree_digest,
                filesystem_changed=changed,
            )
        except McpLocalPackageInstallerError:
            raise
        except Exception:
            raise McpLocalPackageInstallerError(
                "mcp_package_uninstall_recovery_failed",
                cleanup_required=True,
            ) from None

    @staticmethod
    def _valid_update_identity(
        management_id: str,
        operation_id: str,
        expected_current_tree_digest: str,
        expected_target_tree_digest: str | None = None,
    ) -> bool:
        return (
            _ID.fullmatch(management_id) is not None
            and _ID.fullmatch(operation_id) is not None
            and _DIGEST.fullmatch(expected_current_tree_digest) is not None
            and (
                expected_target_tree_digest is None
                or _DIGEST.fullmatch(expected_target_tree_digest) is not None
            )
        )

    def stage_update(
        self,
        package: McpRegistryResolvedLocalPackage,
        *,
        management_id: str,
        operation_id: str,
        expected_current_tree_digest: str,
        user_configuration: Mapping[str, SecretStr] | None = None,
    ) -> McpLocalPackageStagedUpdateResult:
        """Download and probe one target in a deterministic unpublished slot."""

        if (
            not self._valid_update_identity(
                management_id,
                operation_id,
                expected_current_tree_digest,
            )
            or package.registry_type != "mcpb"
            or package.execution_configuration_state != "resolved"
            or _DIGEST.fullmatch(package.file_sha256) is None
        ):
            raise McpLocalPackageInstallerError("mcp_package_identity_invalid")
        staging_root, installed_root, _quarantine, rollback_root = (
            self._prepare_roots()
        )
        final = installed_root / management_id
        staging = staging_root / operation_id
        held = rollback_root / management_id
        try:
            if (
                not final.is_dir()
                or _tree_digest(final) != expected_current_tree_digest
            ):
                raise McpLocalPackageInstallerError(
                    "mcp_package_installed_tree_changed",
                    cleanup_required=True,
                )
            if held.exists():
                raise McpLocalPackageInstallerError(
                    "mcp_package_rollback_generation_exists"
                )
            if staging.exists():
                raise McpLocalPackageInstallerError(
                    "mcp_package_update_staging_conflict",
                    cleanup_required=True,
                )
            staging.mkdir(mode=0o700)
            if os.name != "nt":
                staging.chmod(0o700)
        except McpLocalPackageInstallerError:
            raise
        except Exception:
            raise McpLocalPackageInstallerError(
                "mcp_package_update_staging_unavailable"
            ) from None

        process_cleanup = "not_applicable"
        problem: McpLocalPackageInstallerError | None = None
        try:
            payload = self._downloader.fetch(
                package.package_identifier,
                maximum_bytes=MAX_MCPB_ARTIFACT_BYTES,
            )
            artifact_digest = hashlib.sha256(payload).hexdigest()
            if artifact_digest != package.file_sha256:
                raise McpLocalPackageInstallerError("mcp_package_integrity_mismatch")
            _extract_mcpb(payload, staging)
            manifest, manifest_version, manifest_digest = _parse_manifest(staging)
            executable, arguments, environment, runtime_kind, runtime_version = (
                _manifest_execution(
                    manifest,
                    staging,
                    manifest_digest=manifest_digest,
                    user_configuration=user_configuration,
                )
            )
            arguments, environment = _apply_registry_execution_configuration(
                package,
                arguments,
                environment,
            )
            tree_digest = _tree_digest(staging)
            try:
                probe = self._host.probe(
                    McpStdioConnectionSpec(
                        management_id=management_id,
                        executable=executable,
                        arguments=arguments,
                        environment=environment,
                        working_directory=str(staging),
                    )
                )
                process_cleanup = probe.process_tree_cleanup
            except McpGuardedHostError as error:
                cleanup_unconfirmed = error.code == "mcp_host_cleanup_unconfirmed"
                raise McpLocalPackageInstallerError(
                    error.code,
                    cleanup_required=cleanup_unconfirmed,
                    process_tree_cleanup=(
                        "unconfirmed" if cleanup_unconfirmed else "verified"
                    ),
                ) from None
            if _tree_digest(staging) != tree_digest:
                raise McpLocalPackageInstallerError(
                    "mcp_package_probe_modified_tree"
                )
            return McpLocalPackageStagedUpdateResult(
                artifact_sha256=artifact_digest,
                artifact_bytes=len(payload),
                tree_digest=tree_digest,
                manifest_digest=manifest_digest,
                manifest_version=manifest_version,
                runtime_kind=runtime_kind,
                runtime_version=runtime_version,
                probe=probe,
            )
        except McpLocalPackageInstallerError as error:
            problem = error
        except Exception:
            problem = McpLocalPackageInstallerError("mcp_package_update_stage_failed")
        if staging.exists() and not _remove_verified_tree(staging_root, staging):
            problem = McpLocalPackageInstallerError(
                "mcp_package_cleanup_unconfirmed",
                cleanup_required=True,
                process_tree_cleanup=(
                    "unconfirmed"
                    if process_cleanup == "unconfirmed"
                    else process_cleanup
                ),
            )
        assert problem is not None
        raise problem

    def publish_update(
        self,
        *,
        management_id: str,
        operation_id: str,
        expected_current_tree_digest: str,
        expected_target_tree_digest: str,
    ) -> McpLocalPackageUpdatePublicationResult:
        """Publish a staged target while retaining the exact current tree."""

        if not self._valid_update_identity(
            management_id,
            operation_id,
            expected_current_tree_digest,
            expected_target_tree_digest,
        ):
            raise McpLocalPackageInstallerError("mcp_package_identity_invalid")
        staging_root, installed_root, _quarantine, rollback_root = (
            self._prepare_roots()
        )
        final = installed_root / management_id
        staging = staging_root / operation_id
        held = rollback_root / management_id
        try:
            if held.exists():
                if (
                    final.is_dir()
                    and _tree_digest(final) == expected_target_tree_digest
                    and _tree_digest(held) == expected_current_tree_digest
                    and not staging.exists()
                ):
                    return McpLocalPackageUpdatePublicationResult(
                        target_tree_digest=expected_target_tree_digest,
                        rollback_tree_digest=expected_current_tree_digest,
                    )
                raise McpLocalPackageInstallerError(
                    "mcp_package_update_state_conflict",
                    cleanup_required=True,
                )
            if (
                not final.is_dir()
                or _tree_digest(final) != expected_current_tree_digest
            ):
                raise McpLocalPackageInstallerError(
                    "mcp_package_installed_tree_changed",
                    cleanup_required=True,
                )
            if (
                not staging.is_dir()
                or _tree_digest(staging) != expected_target_tree_digest
            ):
                raise McpLocalPackageInstallerError(
                    "mcp_package_update_target_changed",
                    cleanup_required=True,
                )
            os.replace(final, held)
            if _tree_digest(held) != expected_current_tree_digest:
                raise McpLocalPackageInstallerError(
                    "mcp_package_update_rollback_generation_changed",
                    cleanup_required=True,
                )
            os.replace(staging, final)
            if (
                _tree_digest(final) != expected_target_tree_digest
                or _tree_digest(held) != expected_current_tree_digest
            ):
                raise McpLocalPackageInstallerError(
                    "mcp_package_update_publication_changed",
                    cleanup_required=True,
                )
            return McpLocalPackageUpdatePublicationResult(
                target_tree_digest=expected_target_tree_digest,
                rollback_tree_digest=expected_current_tree_digest,
            )
        except McpLocalPackageInstallerError as error:
            restored = self.rollback_update_publication(
                management_id=management_id,
                operation_id=operation_id,
                expected_current_tree_digest=expected_current_tree_digest,
                expected_target_tree_digest=expected_target_tree_digest,
            )
            raise McpLocalPackageInstallerError(
                error.code,
                cleanup_required=error.cleanup_required or not restored,
                process_tree_cleanup=error.process_tree_cleanup,
            ) from None
        except Exception:
            restored = self.rollback_update_publication(
                management_id=management_id,
                operation_id=operation_id,
                expected_current_tree_digest=expected_current_tree_digest,
                expected_target_tree_digest=expected_target_tree_digest,
            )
            raise McpLocalPackageInstallerError(
                "mcp_package_update_publication_failed",
                cleanup_required=not restored,
            ) from None

    def rollback_update_publication(
        self,
        *,
        management_id: str,
        operation_id: str,
        expected_current_tree_digest: str,
        expected_target_tree_digest: str,
    ) -> bool:
        """Restore the old exact tree and discard only the verified target."""

        if not self._valid_update_identity(
            management_id,
            operation_id,
            expected_current_tree_digest,
            expected_target_tree_digest,
        ):
            return False
        try:
            staging_root, installed_root, _quarantine, rollback_root = (
                self._prepare_roots()
            )
            final = installed_root / management_id
            staging = staging_root / operation_id
            held = rollback_root / management_id
            if final.exists() and _tree_digest(final) == expected_target_tree_digest:
                if staging.exists() or not held.is_dir():
                    return False
                os.replace(final, staging)
            if not final.exists() and held.is_dir():
                if _tree_digest(held) != expected_current_tree_digest:
                    return False
                os.replace(held, final)
            if (
                not final.is_dir()
                or _tree_digest(final) != expected_current_tree_digest
                or held.exists()
            ):
                return False
            if staging.exists():
                if _tree_digest(staging) != expected_target_tree_digest:
                    return False
                if not _remove_verified_tree(staging_root, staging):
                    return False
            return not staging.exists()
        except Exception:
            return False

    def swap_rollback_generation(
        self,
        *,
        management_id: str,
        operation_id: str,
        expected_current_tree_digest: str,
        expected_rollback_tree_digest: str,
    ) -> bool:
        """Swap two exact trees, retaining the superseded current generation."""

        if not self._valid_update_identity(
            management_id,
            operation_id,
            expected_current_tree_digest,
            expected_rollback_tree_digest,
        ):
            return False
        try:
            _staging, installed_root, quarantine_root, rollback_root = (
                self._prepare_roots()
            )
            final = installed_root / management_id
            held = rollback_root / management_id
            transition = quarantine_root / operation_id
            if transition.exists():
                if not transition.is_dir():
                    return False
                transition_digest = _tree_digest(transition)
                final_digest = _tree_digest(final) if final.is_dir() else None
                held_digest = _tree_digest(held) if held.is_dir() else None
                # Complete toward the requested orientation: final must become
                # expected_rollback and held must become expected_current.
                if (
                    final_digest is None
                    and held_digest == expected_current_tree_digest
                    and transition_digest == expected_rollback_tree_digest
                ):
                    os.replace(transition, final)
                elif (
                    final_digest == expected_rollback_tree_digest
                    and held_digest is None
                    and transition_digest == expected_current_tree_digest
                ):
                    os.replace(transition, held)
                elif (
                    final_digest is None
                    and held_digest == expected_rollback_tree_digest
                    and transition_digest == expected_current_tree_digest
                ):
                    os.replace(held, final)
                    os.replace(transition, held)
                elif (
                    final_digest == expected_current_tree_digest
                    and held_digest is None
                    and transition_digest == expected_rollback_tree_digest
                ):
                    os.replace(final, held)
                    os.replace(transition, final)
                else:
                    return False
                return (
                    final.is_dir()
                    and held.is_dir()
                    and _tree_digest(final) == expected_rollback_tree_digest
                    and _tree_digest(held) == expected_current_tree_digest
                    and not transition.exists()
                )
            if not final.is_dir() or not held.is_dir():
                return False
            final_digest = _tree_digest(final)
            held_digest = _tree_digest(held)
            if (
                final_digest == expected_rollback_tree_digest
                and held_digest == expected_current_tree_digest
            ):
                return True
            if (
                final_digest != expected_current_tree_digest
                or held_digest != expected_rollback_tree_digest
            ):
                return False
            if expected_current_tree_digest == expected_rollback_tree_digest:
                return True
            os.replace(final, transition)
            os.replace(held, final)
            os.replace(transition, held)
            return (
                _tree_digest(final) == expected_rollback_tree_digest
                and _tree_digest(held) == expected_current_tree_digest
                and not transition.exists()
            )
        except Exception:
            return False

    def cleanup_rollback_generation(
        self,
        *,
        management_id: str,
        operation_id: str,
        expected_tree_digest: str,
    ) -> McpLocalPackageCleanupResult:
        """Remove only one exact retained rollback generation without execution."""

        if not self._valid_uninstall_identity(
            management_id,
            operation_id,
            expected_tree_digest,
        ):
            raise McpLocalPackageInstallerError("mcp_package_identity_invalid")
        try:
            _staging, _installed, quarantine, rollback = self._prepare_roots()
            held = rollback / management_id
            removing = quarantine / operation_id
            if held.exists() and removing.exists():
                raise McpLocalPackageInstallerError(
                    "mcp_package_rollback_cleanup_state_conflict",
                    cleanup_required=True,
                )
            changed = False
            if held.exists():
                if _tree_digest(held) != expected_tree_digest:
                    raise McpLocalPackageInstallerError(
                        "mcp_package_rollback_generation_changed",
                        cleanup_required=True,
                    )
                os.replace(held, removing)
                changed = True
            if removing.exists():
                if _tree_digest(removing) != expected_tree_digest:
                    raise McpLocalPackageInstallerError(
                        "mcp_package_rollback_quarantine_changed",
                        cleanup_required=True,
                    )
                if not _remove_verified_tree(quarantine, removing):
                    raise McpLocalPackageInstallerError(
                        "mcp_package_rollback_cleanup_unconfirmed",
                        cleanup_required=True,
                    )
                changed = True
            if held.exists() or removing.exists():
                raise McpLocalPackageInstallerError(
                    "mcp_package_rollback_cleanup_unconfirmed",
                    cleanup_required=True,
                )
            return McpLocalPackageCleanupResult(
                tree_digest=expected_tree_digest,
                filesystem_changed=changed,
            )
        except McpLocalPackageInstallerError:
            raise
        except Exception:
            raise McpLocalPackageInstallerError(
                "mcp_package_rollback_cleanup_failed",
                cleanup_required=True,
            ) from None


__all__ = (
    "MAX_MCPB_ARTIFACT_BYTES",
    "McpArtifactDownloader",
    "McpbPackageInstaller",
    "PinnedHttpsMcpArtifactDownloader",
)
