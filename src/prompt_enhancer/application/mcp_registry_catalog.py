"""Bounded, read-only catalog of public MCP server metadata.

This module deliberately stops before installation.  Registry membership is
provenance, not a safety verdict, and no package, remote server, credential,
client configuration, subprocess, or shell command is activated here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import PurePosixPath, PureWindowsPath
import re
import threading
from typing import Any, Literal, Protocol
import unicodedata
from urllib.parse import urlsplit
import zlib

from pydantic import Field, SecretStr, field_validator, model_validator

from ..domain import StrictModel


MCP_REGISTRY_CATALOG_CONTRACT_VERSION = "mcp-registry-catalog.v1"
MCP_REGISTRY_SERVER_REVIEW_CONTRACT_VERSION = "mcp-registry-server-review.v1"
MCP_REGISTRY_SOURCE = "official_mcp_registry"
MCP_REGISTRY_BASE_URL = "https://registry.modelcontextprotocol.io"
MCP_STORE_CATALOG_PATH = "/v1/integrations/mcp-store/catalog"
MCP_STORE_ICON_PATH_PREFIX = "/v1/integrations/mcp-store/icons"
MCP_STORE_SERVER_PATH_PREFIX = "/v1/integrations/mcp-store/servers"
MCP_REGISTRY_DEFAULT_LIMIT = 24
MCP_REGISTRY_MAX_LIMIT = 48
MCP_REGISTRY_MAX_SEARCH_CHARS = 100
MCP_REGISTRY_MAX_CURSOR_CHARS = 512
MCP_REGISTRY_MAX_SERVERS = 48
MCP_REGISTRY_MAX_PACKAGES = 8
MCP_REGISTRY_MAX_REMOTES = 8
MCP_REGISTRY_MAX_ICON_SOURCES = 1_024
MCP_REGISTRY_MAX_ICON_CACHE_ITEMS = 64
MCP_REGISTRY_MAX_ICON_BYTES = 256 * 1024
MCP_REGISTRY_MAX_ICON_DIMENSION = 1_024
MCP_REGISTRY_MAX_ICON_PIXELS = 1_048_576

_ENDPOINT_VARIABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
_ENDPOINT_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_.-]{0,63})\}")
_LOCAL_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_LOCAL_NAMED_ARGUMENT = re.compile(r"^-{1,2}[A-Za-z0-9][A-Za-z0-9._-]{0,126}$")
MCP_REGISTRY_MAX_VERSIONS = 20
MCP_REGISTRY_MAX_INSTALL_OPTIONS = 16
MCP_REGISTRY_MAX_REQUIREMENTS = 32

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9.-]{1,160}/[A-Za-z0-9._-]{1,80}$")
_ICON_KEY_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_PACKAGE_TYPE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
_TRUSTED_ICON_HOSTS = frozenset(
    {
        "static.modelcontextprotocol.io",
        "modelcontextprotocol.io",
        "avatars.githubusercontent.com",
        "raw.githubusercontent.com",
        "user-images.githubusercontent.com",
        "cdn.jsdelivr.net",
    }
)
_TRUSTED_ICON_SUFFIXES = (".githubusercontent.com",)
_RASTER_MIME_TYPES = frozenset({"image/png", "image/jpeg", "image/jpg", "image/webp"})
_RASTER_SUFFIXES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

RegistryStatus = Literal["active", "deprecated", "deleted", "unknown"]
RegistryTransport = Literal["stdio", "streamable-http", "sse", "unknown"]
RegistryDelivery = Literal["live", "cached"]
ReviewOptionKind = Literal["local_package", "remote_server"]
ReviewCompatibilityStatus = Literal[
    "reviewable",
    "requires_configuration",
    "unsupported",
]
ReviewCompatibilityReason = Literal[
    "known_package_registry",
    "unknown_package_registry",
    "supported_transport",
    "unknown_transport",
    "runtime_hint_missing",
    "configuration_required",
    "endpoint_template_requires_configuration",
    "endpoint_invalid",
    "machine_runtime_not_probed",
    "platform_not_declared",
    "mcp_handshake_not_performed",
]
ReviewRisk = Literal[
    "downloads_package",
    "executes_local_code",
    "package_integrity_not_declared",
    "command_arguments_declared",
    "filesystem_input_declared",
    "credential_input_declared",
    "remote_network_egress",
    "insecure_remote_transport",
]
RequirementLocation = Literal[
    "runtime_argument",
    "package_argument",
    "environment_variable",
    "transport_header",
    "remote_variable",
]
RequirementFormat = Literal["string", "number", "boolean", "filepath", "unknown"]


class McpRegistryCatalogError(RuntimeError):
    """A closed, content-free registry/catalog failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class McpRegistryClientError(RuntimeError):
    """Content-free failure raised by an official-registry transport."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


def _unicode_text_safe(value: str) -> bool:
    combining_run = 0
    for character in value:
        category = unicodedata.category(character)
        if category.startswith("C"):
            return False
        if category.startswith("M"):
            combining_run += 1
            if combining_run > 4:
                return False
        else:
            combining_run = 0
    return True


def _bounded_text(value: Any, *, maximum: int, fallback: str | None = None) -> str | None:
    if not isinstance(value, str):
        return fallback
    if not _unicode_text_safe(value):
        return fallback
    normalized = unicodedata.normalize("NFC", " ".join(value.strip().split()))
    if not normalized or len(normalized) > maximum or not _unicode_text_safe(normalized):
        return fallback
    return normalized


def _safe_exact_text(value: Any, *, minimum: int = 1, maximum: int) -> str | None:
    if (
        not isinstance(value, str)
        or not minimum <= len(value) <= maximum
        or value != value.strip()
        or value != unicodedata.normalize("NFC", value)
        or not _unicode_text_safe(value)
    ):
        return None
    return value


def _safe_https_url(value: Any, *, maximum: int = 1_024) -> str | None:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or value != unicodedata.normalize("NFC", value)
        or not _unicode_text_safe(value)
    ):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.isascii()
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or any(character in value for character in ("\r", "\n", "\x00"))
    ):
        return None
    if port is not None and not 1 <= port <= 65_535:
        return None
    return value


def _registry_transport(value: Any) -> RegistryTransport:
    return value if value in {"stdio", "streamable-http", "sse"} else "unknown"


def _registry_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return _utc(parsed)
    except (TypeError, ValueError):
        return None


def _icon_host_trusted(host: str) -> bool:
    normalized = host.casefold().rstrip(".")
    return normalized in _TRUSTED_ICON_HOSTS or any(
        normalized.endswith(suffix) for suffix in _TRUSTED_ICON_SUFFIXES
    )


class McpRegistryPackage(StrictModel):
    registry_type: str = Field(min_length=1, max_length=32)
    identifier: str = Field(min_length=1, max_length=512)
    version: str | None = Field(default=None, min_length=1, max_length=255)
    transport: RegistryTransport
    runtime_hint: str | None = Field(default=None, min_length=1, max_length=32)
    checksum_available: bool

    @field_validator("registry_type")
    @classmethod
    def validate_registry_type(cls, value: str) -> str:
        if not _PACKAGE_TYPE_PATTERN.fullmatch(value):
            raise ValueError("invalid registry type")
        return value


class McpRegistryRemote(StrictModel):
    transport: RegistryTransport
    endpoint_host: str | None = Field(default=None, min_length=1, max_length=255)
    endpoint_state: Literal["fixed_host", "template_requires_configuration"]
    secure: bool | None

    @model_validator(mode="after")
    def coherent_endpoint(self) -> "McpRegistryRemote":
        if self.endpoint_state == "fixed_host":
            if self.endpoint_host is None or self.secure is None:
                raise ValueError("fixed endpoint is incomplete")
        elif self.endpoint_host is not None or self.secure is not None:
            raise ValueError("template endpoint exposes a resolved host")
        return self


class McpRegistryIcon(StrictModel):
    path: str = Field(pattern=rf"^{re.escape(MCP_STORE_ICON_PATH_PREFIX)}/[0-9a-f]{{32}}$")
    mime_type: Literal["image/png", "image/jpeg", "image/webp"]


def _presentation_revision(
    *,
    name: str,
    version: str,
    title: str,
    description: str,
    status: RegistryStatus,
    updated_at: datetime | None,
    repository_url: str | None,
    website_url: str | None,
    icon: McpRegistryIcon | None,
) -> str:
    material = {
        "name": name,
        "version": version,
        "title": title,
        "description": description,
        "status": status,
        "updated_at": (
            updated_at.isoformat().replace("+00:00", "Z")
            if updated_at is not None
            else None
        ),
        "repository_url": repository_url,
        "website_url": website_url,
        "icon": None if icon is None else icon.model_dump(mode="json"),
    }
    return hashlib.sha256(
        b"prompt-enhancer/mcp-registry-presentation/v1\x00"
        + json.dumps(
            material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class McpRegistryServer(StrictModel):
    catalog_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    presentation_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    name: str = Field(min_length=3, max_length=241)
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    publisher: str = Field(min_length=1, max_length=160)
    version: str = Field(min_length=1, max_length=255)
    status: RegistryStatus
    updated_at: datetime | None
    repository_url: str | None = Field(default=None, max_length=1_024)
    website_url: str | None = Field(default=None, max_length=1_024)
    icon: McpRegistryIcon | None
    packages: tuple[McpRegistryPackage, ...] = Field(max_length=MCP_REGISTRY_MAX_PACKAGES)
    remotes: tuple[McpRegistryRemote, ...] = Field(max_length=MCP_REGISTRY_MAX_REMOTES)
    supports_local: bool
    supports_remote: bool
    management_state: Literal["not_managed"] = "not_managed"
    install_action: Literal["unavailable"] = "unavailable"
    install_reason: Literal["guarded_install_host_not_implemented"] = (
        "guarded_install_host_not_implemented"
    )

    @field_validator("updated_at")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def coherent_distribution(self) -> "McpRegistryServer":
        if self.supports_local != bool(self.packages):
            raise ValueError("local support does not match packages")
        if self.supports_remote != bool(self.remotes):
            raise ValueError("remote support does not match remotes")
        if not _NAME_PATTERN.fullmatch(self.name):
            raise ValueError("invalid server name")
        if self.publisher != self.name.split("/", 1)[0]:
            raise ValueError("publisher does not match server name")
        expected_revision = _presentation_revision(
            name=self.name,
            version=self.version,
            title=self.title,
            description=self.description,
            status=self.status,
            updated_at=self.updated_at,
            repository_url=self.repository_url,
            website_url=self.website_url,
            icon=self.icon,
        )
        if self.presentation_revision != expected_revision:
            raise ValueError("server presentation revision does not match")
        return self


class McpRegistrySourceStatus(StrictModel):
    registry: Literal["official_mcp_registry"] = MCP_REGISTRY_SOURCE
    base_url: Literal["https://registry.modelcontextprotocol.io"] = MCP_REGISTRY_BASE_URL
    fetched_at: datetime
    delivery: RegistryDelivery
    cache_age_seconds: int = Field(strict=True, ge=0)

    @field_validator("fetched_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)


class McpRegistryCatalog(StrictModel):
    contract_version: Literal["mcp-registry-catalog.v1"] = (
        MCP_REGISTRY_CATALOG_CONTRACT_VERSION
    )
    source: McpRegistrySourceStatus
    search: str
    servers: tuple[McpRegistryServer, ...] = Field(max_length=MCP_REGISTRY_MAX_SERVERS)
    next_cursor: str | None = Field(default=None, max_length=MCP_REGISTRY_MAX_CURSOR_CHARS)
    partial: bool
    management_truth: Literal["registry_only_no_install_authority"] = (
        "registry_only_no_install_authority"
    )

    @model_validator(mode="after")
    def coherent_page(self) -> "McpRegistryCatalog":
        if len({server.catalog_id for server in self.servers}) != len(self.servers):
            raise ValueError("catalog identities are not unique")
        return self


class McpRegistryInputRequirement(StrictModel):
    requirement_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    location: RequirementLocation
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, min_length=1, max_length=240)
    required: bool
    secret: bool
    format: RequirementFormat
    repeated: bool
    fixed_value_declared: bool
    default_declared: bool
    choices_count: int = Field(strict=True, ge=0, le=64)
    user_value_needed: bool

    @model_validator(mode="after")
    def coherent_user_value(self) -> "McpRegistryInputRequirement":
        if self.user_value_needed != (
            self.required
            and not self.fixed_value_declared
            and not self.default_declared
        ):
            raise ValueError("user-value truth is incoherent")
        return self


class McpRegistryOptionCompatibility(StrictModel):
    status: ReviewCompatibilityStatus
    reasons: tuple[ReviewCompatibilityReason, ...] = Field(min_length=3, max_length=10)
    platform_compatibility: Literal["unverified"] = "unverified"
    runtime_availability: Literal["unverified"] = "unverified"
    mcp_handshake: Literal["not_performed"] = "not_performed"

    @model_validator(mode="after")
    def coherent_status(self) -> "McpRegistryOptionCompatibility":
        reasons = set(self.reasons)
        if len(reasons) != len(self.reasons):
            raise ValueError("compatibility reasons must be unique")
        if (
            "unknown_package_registry" in reasons
            or "unknown_transport" in reasons
            or "endpoint_invalid" in reasons
        ):
            expected = "unsupported"
        elif (
            "runtime_hint_missing" in reasons
            or "configuration_required" in reasons
            or "endpoint_template_requires_configuration" in reasons
        ):
            expected = "requires_configuration"
        else:
            expected = "reviewable"
        if self.status != expected:
            raise ValueError("compatibility status does not match reasons")
        return self


class McpRegistryInstallOption(StrictModel):
    option_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    kind: ReviewOptionKind
    label: str = Field(min_length=1, max_length=120)
    registry_type: str | None = Field(default=None, min_length=1, max_length=32)
    package_identifier: str | None = Field(default=None, min_length=1, max_length=512)
    package_version: str | None = Field(default=None, min_length=1, max_length=255)
    runtime_hint: str | None = Field(default=None, min_length=1, max_length=32)
    transport: RegistryTransport
    endpoint_host: str | None = Field(default=None, min_length=1, max_length=255)
    endpoint_state: Literal[
        "not_applicable",
        "fixed_host",
        "template_requires_configuration",
        "invalid",
    ]
    secure_transport: bool | None
    checksum_state: Literal["declared", "not_declared", "not_applicable"]
    requirements: tuple[McpRegistryInputRequirement, ...] = Field(
        max_length=MCP_REGISTRY_MAX_REQUIREMENTS
    )
    risks: tuple[ReviewRisk, ...] = Field(max_length=8)
    compatibility: McpRegistryOptionCompatibility
    execution_state: Literal["preview_only"] = "preview_only"
    execution_material_digest: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        exclude=True,
        repr=False,
    )

    @model_validator(mode="after")
    def coherent_option(self) -> "McpRegistryInstallOption":
        if self.kind == "local_package":
            if self.registry_type is None or self.package_identifier is None:
                raise ValueError("local package identity is incomplete")
            if self.checksum_state == "not_applicable":
                raise ValueError("local package truth is incoherent")
        else:
            if any(
                value is not None
                for value in (
                    self.registry_type,
                    self.package_identifier,
                    self.package_version,
                    self.runtime_hint,
                )
            ):
                raise ValueError("remote option contains package identity")
            if self.checksum_state != "not_applicable" or self.endpoint_state == "not_applicable":
                raise ValueError("remote option truth is incoherent")
        if self.endpoint_state == "fixed_host" and self.endpoint_host is None:
            raise ValueError("fixed endpoint host is missing")
        if self.endpoint_state != "fixed_host" and self.endpoint_host is not None:
            raise ValueError("non-fixed endpoint exposes a host")
        return self


class McpRegistryProvenance(StrictModel):
    registry: Literal["official_mcp_registry"] = MCP_REGISTRY_SOURCE
    registry_membership_security_review: Literal["not_claimed"] = "not_claimed"
    publisher_namespace: str = Field(min_length=1, max_length=160)
    repository_url: str | None = Field(default=None, max_length=1_024)
    repository_source: str | None = Field(default=None, min_length=1, max_length=32)
    repository_identity_declared: bool
    repository_subfolder_declared: bool
    website_url: str | None = Field(default=None, max_length=1_024)
    schema_url: str | None = Field(default=None, max_length=1_024)
    license_state: Literal["not_declared_by_registry_contract"] = (
        "not_declared_by_registry_contract"
    )

    @model_validator(mode="after")
    def coherent_namespace(self) -> "McpRegistryProvenance":
        if _safe_exact_text(self.publisher_namespace, maximum=160) is None:
            raise ValueError("invalid publisher namespace")
        return self


class McpRegistryVersionSummary(StrictModel):
    version: str = Field(min_length=1, max_length=255)
    status: RegistryStatus
    updated_at: datetime | None
    selected: bool

    @field_validator("updated_at")
    @classmethod
    def normalize_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)


class McpRegistryServerReview(StrictModel):
    contract_version: Literal["mcp-registry-server-review.v1"] = (
        MCP_REGISTRY_SERVER_REVIEW_CONTRACT_VERSION
    )
    source: McpRegistrySourceStatus
    server: McpRegistryServer
    provenance: McpRegistryProvenance
    versions: tuple[McpRegistryVersionSummary, ...] = Field(
        max_length=MCP_REGISTRY_MAX_VERSIONS
    )
    version_history_state: Literal["live", "partial", "unavailable"]
    options: tuple[McpRegistryInstallOption, ...] = Field(
        max_length=MCP_REGISTRY_MAX_INSTALL_OPTIONS
    )
    plan_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    partial: bool
    management_state: Literal["not_managed"] = "not_managed"
    install_action: Literal["unavailable"] = "unavailable"
    uninstall_action: Literal["not_applicable"] = "not_applicable"
    review_truth: Literal["preview_only_no_install_or_connection_authority"] = (
        "preview_only_no_install_or_connection_authority"
    )

    @model_validator(mode="after")
    def coherent_review(self) -> "McpRegistryServerReview":
        if self.provenance.publisher_namespace != self.server.publisher:
            raise ValueError("provenance publisher does not match server")
        if self.version_history_state != "live" and not self.partial:
            raise ValueError("partial history must be disclosed")
        return self


class McpRegistryResolvedRemoteHeader(StrictModel):
    """Transient Registry declaration used only to prepare a guarded client."""

    requirement_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    name: str = Field(min_length=1, max_length=128)
    required: bool
    secret: bool
    declared_value: SecretStr | None = Field(default=None, repr=False)


class McpRegistryResolvedRemoteConnection(StrictModel):
    """Exact, revalidated remote material that is never an HTTP response model."""

    catalog_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    option_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    plan_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    transport: Literal["streamable-http", "sse"]
    endpoint_host: str = Field(min_length=1, max_length=255)
    endpoint: SecretStr = Field(min_length=1, max_length=2_048, repr=False)
    headers: tuple[McpRegistryResolvedRemoteHeader, ...] = Field(max_length=32)


class McpRegistryResolvedLocalEnvironment(StrictModel):
    """One transient local environment value; never an HTTP response model."""

    name: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$",
    )
    value: SecretStr = Field(min_length=1, max_length=2_048, repr=False)


class McpRegistryResolvedLocalPackage(StrictModel):
    """Exact, transient MCPB artifact material; never an HTTP response model."""

    catalog_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    option_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    plan_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    registry_type: Literal["mcpb"] = "mcpb"
    package_identifier: SecretStr = Field(min_length=1, max_length=512, repr=False)
    package_version: str | None = Field(default=None, min_length=1, max_length=255)
    file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transport: Literal["stdio"] = "stdio"
    execution_configuration_state: Literal["resolved", "inspection_only"] = (
        "resolved"
    )
    runtime_arguments: tuple[SecretStr, ...] = Field(
        default=(), max_length=64, repr=False
    )
    package_arguments: tuple[SecretStr, ...] = Field(
        default=(), max_length=64, repr=False
    )
    environment: tuple[McpRegistryResolvedLocalEnvironment, ...] = Field(
        default=(),
        max_length=32,
        repr=False,
    )


def _review_plan_revision(
    server: McpRegistryServer,
    provenance: McpRegistryProvenance,
    options: Sequence[McpRegistryInstallOption],
) -> str:
    revision_payload = {
        "contract_version": MCP_REGISTRY_SERVER_REVIEW_CONTRACT_VERSION,
        "server": server.model_dump(mode="json"),
        "provenance": provenance.model_dump(mode="json"),
        "options": [
            {
                "public": item.model_dump(mode="json"),
                # Bind exact endpoint paths, queries, checksums, and declared
                # execution values without returning those values (or this
                # internal digest) through the review API.
                "execution_material_digest": item.execution_material_digest,
            }
            for item in options
        ],
    }
    return hashlib.sha256(
        json.dumps(
            revision_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _execution_material_digest(
    value: Mapping[str, Any],
    *,
    fields: Sequence[str],
) -> str:
    """Bind exact Registry execution material without exposing it."""

    selected = {field: value.get(field) for field in fields if field in value}
    try:
        encoded = json.dumps(
            selected,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        encoded = b'{"invalid_execution_material":true}'
    return hashlib.sha256(
        b"prompt-enhancer/mcp-registry-execution-material/v1\x00" + encoded
    ).hexdigest()


class McpRegistryCacheRecord(StrictModel):
    fetched_at: datetime
    search: str = Field(max_length=MCP_REGISTRY_MAX_SEARCH_CHARS)
    cursor: str | None = Field(default=None, max_length=MCP_REGISTRY_MAX_CURSOR_CHARS)
    limit: int = Field(strict=True, ge=1, le=MCP_REGISTRY_MAX_LIMIT)
    servers: tuple[McpRegistryServer, ...] = Field(max_length=MCP_REGISTRY_MAX_SERVERS)
    next_cursor: str | None = Field(default=None, max_length=MCP_REGISTRY_MAX_CURSOR_CHARS)
    partial: bool
    icon_sources: dict[str, str]

    @field_validator("fetched_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def validate_icon_sources(self) -> "McpRegistryCacheRecord":
        if len({server.catalog_id for server in self.servers}) != len(self.servers):
            raise ValueError("cached catalog identities are not unique")
        if self.search != " ".join(self.search.strip().split()) or (
            self.search and _safe_exact_text(self.search, maximum=MCP_REGISTRY_MAX_SEARCH_CHARS) is None
        ):
            raise ValueError("cached catalog search is unsafe")
        if self.cursor is not None and _safe_exact_text(
            self.cursor,
            maximum=MCP_REGISTRY_MAX_CURSOR_CHARS,
        ) is None:
            raise ValueError("cached catalog cursor is unsafe")
        if self.next_cursor is not None and _safe_exact_text(
            self.next_cursor,
            maximum=MCP_REGISTRY_MAX_CURSOR_CHARS,
        ) is None:
            raise ValueError("cached next cursor is unsafe")
        if self.cursor is not None and self.next_cursor == self.cursor:
            raise ValueError("cached catalog cursor cycles")
        if len(self.icon_sources) > MCP_REGISTRY_MAX_SERVERS:
            raise ValueError("too many icon sources")
        for key, source in self.icon_sources.items():
            trusted_source = _trusted_icon_source(source)
            expected_key = (
                hashlib.sha256(trusted_source.encode("utf-8")).hexdigest()[:32]
                if trusted_source is not None
                else None
            )
            if not _ICON_KEY_PATTERN.fullmatch(key) or key != expected_key:
                raise ValueError("invalid icon source")
        expected_icon_keys = {
            server.icon.path.rsplit("/", 1)[1]
            for server in self.servers
            if server.icon is not None
        }
        if set(self.icon_sources) != expected_icon_keys:
            raise ValueError("cached icon sources do not match the catalog")
        return self


@dataclass(frozen=True, slots=True)
class McpRegistryIconContent:
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    body: bytes


def _png_dimensions(body: bytes) -> tuple[int, int] | None:
    if not body.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    offset = 8
    dimensions: tuple[int, int] | None = None
    saw_image_data = False
    chunks = 0
    while offset + 12 <= len(body) and chunks < 256:
        chunks += 1
        length = int.from_bytes(body[offset:offset + 4], "big")
        chunk_type = body[offset + 4:offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if length > MCP_REGISTRY_MAX_ICON_BYTES or crc_end > len(body):
            return None
        expected_crc = int.from_bytes(body[data_end:crc_end], "big")
        if zlib.crc32(chunk_type + body[data_start:data_end]) & 0xFFFFFFFF != expected_crc:
            return None
        if chunks == 1:
            if chunk_type != b"IHDR" or length != 13:
                return None
            dimensions = (
                int.from_bytes(body[data_start:data_start + 4], "big"),
                int.from_bytes(body[data_start + 4:data_start + 8], "big"),
            )
        elif chunk_type == b"acTL":
            return None
        elif chunk_type == b"IDAT":
            saw_image_data = True
        elif chunk_type == b"IEND":
            if length != 0 or crc_end != len(body):
                return None
            return dimensions if saw_image_data else None
        offset = crc_end
    return None


def _jpeg_dimensions(body: bytes) -> tuple[int, int] | None:
    if len(body) < 12 or not body.startswith(b"\xff\xd8") or not body.endswith(b"\xff\xd9"):
        return None
    offset = 2
    sof_markers = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    while offset + 1 < len(body):
        if body[offset] != 0xFF:
            return None
        while offset < len(body) and body[offset] == 0xFF:
            offset += 1
        if offset >= len(body):
            return None
        marker = body[offset]
        offset += 1
        if marker == 0xD9:
            return None
        if marker == 0xDA:
            return None
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            continue
        if offset + 2 > len(body):
            return None
        length = int.from_bytes(body[offset:offset + 2], "big")
        if length < 2 or offset + length > len(body):
            return None
        if marker in sof_markers:
            if length < 8:
                return None
            height = int.from_bytes(body[offset + 3:offset + 5], "big")
            width = int.from_bytes(body[offset + 5:offset + 7], "big")
            return width, height
        offset += length
    return None


def _webp_dimensions(body: bytes) -> tuple[int, int] | None:
    if (
        len(body) < 20
        or body[:4] != b"RIFF"
        or body[8:12] != b"WEBP"
        or int.from_bytes(body[4:8], "little") != len(body) - 8
    ):
        return None
    offset = 12
    dimensions: tuple[int, int] | None = None
    while offset + 8 <= len(body):
        chunk_type = body[offset:offset + 4]
        length = int.from_bytes(body[offset + 4:offset + 8], "little")
        data_start = offset + 8
        data_end = data_start + length
        padded_end = data_end + (length % 2)
        if data_end > len(body) or padded_end > len(body):
            return None
        data = body[data_start:data_end]
        if chunk_type in {b"ANIM", b"ANMF"}:
            return None
        if chunk_type == b"VP8X":
            if len(data) < 10 or data[0] & 0x02:
                return None
            dimensions = (
                1 + int.from_bytes(data[4:7], "little"),
                1 + int.from_bytes(data[7:10], "little"),
            )
        elif chunk_type == b"VP8 " and dimensions is None:
            if len(data) < 10 or data[3:6] != b"\x9d\x01\x2a":
                return None
            dimensions = (
                int.from_bytes(data[6:8], "little") & 0x3FFF,
                int.from_bytes(data[8:10], "little") & 0x3FFF,
            )
        elif chunk_type == b"VP8L" and dimensions is None:
            if len(data) < 5 or data[0] != 0x2F:
                return None
            dimensions = (
                1 + (((data[2] & 0x3F) << 8) | data[1]),
                1 + (((data[4] & 0x0F) << 10) | (data[3] << 2) | (data[2] >> 6)),
            )
        offset = padded_end
    return dimensions if offset == len(body) else None


def _valid_icon_content(content: McpRegistryIconContent) -> bool:
    body = content.body
    if (
        not isinstance(body, bytes)
        or not 0 < len(body) <= MCP_REGISTRY_MAX_ICON_BYTES
    ):
        return False
    dimensions = {
        "image/png": _png_dimensions,
        "image/jpeg": _jpeg_dimensions,
        "image/webp": _webp_dimensions,
    }[content.media_type](body)
    if dimensions is None:
        return False
    width, height = dimensions
    return (
        0 < width <= MCP_REGISTRY_MAX_ICON_DIMENSION
        and 0 < height <= MCP_REGISTRY_MAX_ICON_DIMENSION
        and width * height <= MCP_REGISTRY_MAX_ICON_PIXELS
    )


class McpRegistryClient(Protocol):
    def list_servers(
        self,
        *,
        search: str,
        cursor: str | None,
        limit: int,
    ) -> Mapping[str, Any]: ...

    def get_server_version(self, *, name: str, version: str) -> Mapping[str, Any]: ...

    def list_server_versions(self, *, name: str) -> Mapping[str, Any]: ...

    def fetch_icon(self, source: str) -> McpRegistryIconContent: ...


class McpRegistryCache(Protocol):
    def get(self, key: str) -> McpRegistryCacheRecord | None: ...

    def put(self, key: str, record: McpRegistryCacheRecord) -> None: ...


def _trusted_icon_source(source: Any) -> str | None:
    url = _safe_https_url(source, maximum=1_024)
    if url is None:
        return None
    host = urlsplit(url).hostname or ""
    if not _icon_host_trusted(host) or bool(urlsplit(url).query):
        return None
    return url


def _trusted_raster_icon(source: Any, declared_mime: Any) -> tuple[str, str] | None:
    url = _trusted_icon_source(source)
    if url is None:
        return None
    mime = str(declared_mime or "").casefold().split(";", 1)[0].strip()
    if mime == "image/jpg":
        mime = "image/jpeg"
    if mime not in _RASTER_MIME_TYPES:
        path = urlsplit(url).path.casefold()
        mime = next(
            (candidate for suffix, candidate in _RASTER_SUFFIXES.items() if path.endswith(suffix)),
            "",
        )
    if mime not in {"image/png", "image/jpeg", "image/webp"}:
        return None
    return url, mime


def _parse_package(value: Any) -> McpRegistryPackage | None:
    if not isinstance(value, Mapping):
        return None
    registry_type = _bounded_text(value.get("registryType"), maximum=32)
    identifier = _bounded_text(value.get("identifier"), maximum=512)
    if registry_type is None or identifier is None:
        return None
    registry_type = registry_type.casefold()
    if not _PACKAGE_TYPE_PATTERN.fullmatch(registry_type):
        return None
    version = _bounded_text(value.get("version"), maximum=255)
    runtime_hint = _bounded_text(value.get("runtimeHint"), maximum=32)
    transport_value = value.get("transport")
    transport = _registry_transport(
        transport_value.get("type") if isinstance(transport_value, Mapping) else None
    )
    checksum = value.get("fileSha256")
    return McpRegistryPackage(
        registry_type=registry_type,
        identifier=identifier,
        version=version,
        transport=transport,
        runtime_hint=runtime_hint,
        checksum_available=isinstance(checksum, str)
        and bool(re.fullmatch(r"[a-f0-9]{64}", checksum)),
    )


def _parse_remote(value: Any) -> McpRegistryRemote | None:
    if not isinstance(value, Mapping):
        return None
    endpoint_state, endpoint_host, secure = _endpoint_summary(value.get("url"))
    if endpoint_state == "invalid":
        return None
    return McpRegistryRemote(
        transport=_registry_transport(value.get("type")),
        endpoint_host=endpoint_host,
        endpoint_state=endpoint_state,
        secure=secure,
    )


def _parse_server(value: Any) -> tuple[McpRegistryServer, tuple[str, str] | None] | None:
    if not isinstance(value, Mapping):
        return None
    raw = value.get("server")
    if not isinstance(raw, Mapping):
        return None
    name = _bounded_text(raw.get("name"), maximum=241)
    version = _bounded_text(raw.get("version"), maximum=255)
    description = _bounded_text(raw.get("description"), maximum=500)
    if (
        name is None
        or version is None
        or description is None
        or not _NAME_PATTERN.fullmatch(name)
    ):
        return None
    raw_title = raw.get("title")
    title = (
        name.split("/", 1)[1]
        if raw_title is None
        else _bounded_text(raw_title, maximum=100)
    )
    if title is None:
        return None

    official_meta: Mapping[str, Any] = {}
    metadata = value.get("_meta")
    if isinstance(metadata, Mapping):
        candidate = metadata.get("io.modelcontextprotocol.registry/official")
        if isinstance(candidate, Mapping):
            official_meta = candidate
    raw_status = official_meta.get("status")
    status: RegistryStatus = (
        raw_status if raw_status in {"active", "deprecated", "deleted"} else "unknown"
    )

    repository_url = None
    repository = raw.get("repository")
    if isinstance(repository, Mapping):
        repository_url = _safe_https_url(repository.get("url"))
    website_url = _safe_https_url(raw.get("websiteUrl"))

    packages = tuple(
        item
        for item in (
            _parse_package(candidate)
            for candidate in (
                raw.get("packages")[:MCP_REGISTRY_MAX_PACKAGES]
                if isinstance(raw.get("packages"), Sequence)
                and not isinstance(raw.get("packages"), (str, bytes, bytearray))
                else ()
            )
        )
        if item is not None
    )
    remotes = tuple(
        item
        for item in (
            _parse_remote(candidate)
            for candidate in (
                raw.get("remotes")[:MCP_REGISTRY_MAX_REMOTES]
                if isinstance(raw.get("remotes"), Sequence)
                and not isinstance(raw.get("remotes"), (str, bytes, bytearray))
                else ()
            )
        )
        if item is not None
    )

    icon: McpRegistryIcon | None = None
    icon_source: tuple[str, str] | None = None
    raw_icons = raw.get("icons")
    if isinstance(raw_icons, Sequence) and not isinstance(raw_icons, (str, bytes, bytearray)):
        for candidate in raw_icons[:8]:
            if not isinstance(candidate, Mapping):
                continue
            trusted = _trusted_raster_icon(candidate.get("src"), candidate.get("mimeType"))
            if trusted is None:
                continue
            source, mime_type = trusted
            key = hashlib.sha256(source.encode("utf-8")).hexdigest()[:32]
            icon = McpRegistryIcon(
                path=f"{MCP_STORE_ICON_PATH_PREFIX}/{key}",
                mime_type=mime_type,
            )
            icon_source = (key, source)
            break

    updated_at = _registry_time(official_meta.get("updatedAt"))
    catalog_id = hashlib.sha256(f"{name}\x00{version}".encode("utf-8")).hexdigest()[:32]
    server = McpRegistryServer(
        catalog_id=catalog_id,
        presentation_revision=_presentation_revision(
            name=name,
            version=version,
            title=title,
            description=description,
            status=status,
            updated_at=updated_at,
            repository_url=repository_url,
            website_url=website_url,
            icon=icon,
        ),
        name=name,
        title=title,
        description=description,
        publisher=name.split("/", 1)[0],
        version=version,
        status=status,
        updated_at=updated_at,
        repository_url=repository_url,
        website_url=website_url,
        icon=icon,
        packages=packages,
        remotes=remotes,
        supports_local=bool(packages),
        supports_remote=bool(remotes),
    )
    return server, icon_source


_KNOWN_PACKAGE_REGISTRIES = frozenset(
    {"npm", "pypi", "cargo", "oci", "nuget", "mcpb"}
)


def _catalog_id(name: str, version: str) -> str:
    return hashlib.sha256(f"{name}\x00{version}".encode("utf-8")).hexdigest()[:32]


def _official_metadata(value: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = value.get("_meta")
    if not isinstance(metadata, Mapping):
        return {}
    official = metadata.get("io.modelcontextprotocol.registry/official")
    return official if isinstance(official, Mapping) else {}


def _bounded_sequence(value: Any) -> Sequence[Any] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return None
    return value


def _input_requirement(
    value: Any,
    *,
    location: RequirementLocation,
    fallback_name: str,
    identity_material: str,
) -> McpRegistryInputRequirement | None:
    if not isinstance(value, Mapping):
        return None
    name = _bounded_text(value.get("name"), maximum=128)
    if name is None:
        name = _bounded_text(value.get("valueHint"), maximum=128)
    if name is None:
        name = fallback_name
    description = _bounded_text(value.get("description"), maximum=240)
    raw_format = value.get("format")
    input_format: RequirementFormat = (
        raw_format
        if raw_format in {"string", "number", "boolean", "filepath"}
        else "unknown"
    )
    choices = _bounded_sequence(value.get("choices"))
    choices_count = min(len(choices), 64) if choices is not None else 0
    fixed_value_declared = "value" in value and value.get("value") is not None
    default_declared = "default" in value and value.get("default") is not None
    required = value.get("isRequired") is True
    requirement_id = hashlib.sha256(
        f"{identity_material}\x00{location}\x00{name}".encode("utf-8")
    ).hexdigest()[:32]
    return McpRegistryInputRequirement(
        requirement_id=requirement_id,
        location=location,
        name=name,
        description=description,
        required=required,
        secret=value.get("isSecret") is True,
        format=input_format,
        repeated=value.get("isRepeated") is True,
        fixed_value_declared=fixed_value_declared,
        default_declared=default_declared,
        choices_count=choices_count,
        user_value_needed=required
        and not fixed_value_declared
        and not default_declared,
    )


def _requirements_from_sequence(
    value: Any,
    *,
    location: RequirementLocation,
    label: str,
    identity_material: str,
) -> tuple[list[McpRegistryInputRequirement], bool]:
    if value is None:
        return [], False
    sequence = _bounded_sequence(value)
    if sequence is None:
        return [], True
    partial = len(sequence) > MCP_REGISTRY_MAX_REQUIREMENTS
    requirements: list[McpRegistryInputRequirement] = []
    for index, candidate in enumerate(sequence[:MCP_REGISTRY_MAX_REQUIREMENTS]):
        requirement = _input_requirement(
            candidate,
            location=location,
            fallback_name=f"{label} {index + 1}",
            identity_material=f"{identity_material}\x00{index}",
        )
        if requirement is None:
            partial = True
            continue
        requirements.append(requirement)
        choices = _bounded_sequence(candidate.get("choices"))
        if choices is not None and len(choices) > 64:
            partial = True
        variables = candidate.get("variables")
        if variables is None:
            continue
        if not isinstance(variables, Mapping):
            partial = True
            continue
        if len(variables) > MCP_REGISTRY_MAX_REQUIREMENTS:
            partial = True
        for variable_index, (variable_name, variable) in enumerate(
            list(variables.items())[:MCP_REGISTRY_MAX_REQUIREMENTS]
        ):
            safe_name = _bounded_text(variable_name, maximum=128)
            if safe_name is None:
                partial = True
                continue
            nested = _input_requirement(
                variable,
                location=location,
                fallback_name=safe_name,
                identity_material=(
                    f"{identity_material}\x00{index}\x00variable\x00{variable_index}"
                ),
            )
            if nested is None:
                partial = True
                continue
            requirements.append(nested)
    return requirements, partial


def _requirements_from_mapping(
    value: Any,
    *,
    location: RequirementLocation,
    identity_material: str,
) -> tuple[list[McpRegistryInputRequirement], bool]:
    if value is None:
        return [], False
    if not isinstance(value, Mapping):
        return [], True
    partial = len(value) > MCP_REGISTRY_MAX_REQUIREMENTS
    requirements: list[McpRegistryInputRequirement] = []
    for index, (name, candidate) in enumerate(
        list(value.items())[:MCP_REGISTRY_MAX_REQUIREMENTS]
    ):
        safe_name = _bounded_text(name, maximum=128)
        if safe_name is None:
            partial = True
            continue
        normalized_candidate: Any = candidate
        if isinstance(candidate, Mapping):
            normalized_candidate = dict(candidate)
            # In the Registry mapping form the key is the executable variable
            # identity. A nested display name must not redirect substitution.
            normalized_candidate["name"] = safe_name
        requirement = _input_requirement(
            normalized_candidate,
            location=location,
            fallback_name=safe_name,
            identity_material=f"{identity_material}\x00{index}",
        )
        if requirement is None:
            partial = True
            continue
        requirements.append(requirement)
        if isinstance(candidate, Mapping):
            choices = _bounded_sequence(candidate.get("choices"))
            if choices is not None and len(choices) > 64:
                partial = True
    return requirements, partial


def _local_value_valid_for_requirement(
    requirement: McpRegistryInputRequirement,
    candidate: Mapping[str, Any],
    value: str,
) -> bool:
    if (
        not value
        or any(character in value for character in ("\x00", "\r", "\n"))
        or len(value.encode("utf-8")) > 2_048
    ):
        return False
    if requirement.format == "boolean" and value not in {"true", "false"}:
        return False
    if requirement.format == "number":
        try:
            if not Decimal(value).is_finite():
                return False
        except InvalidOperation:
            return False
    if requirement.format == "filepath":
        if any(character in value for character in "*?[]"):
            return False
        if not (
            PureWindowsPath(value).is_absolute()
            or PurePosixPath(value).is_absolute()
        ):
            return False
    choices = _bounded_sequence(candidate.get("choices"))
    if choices is not None:
        if (
            len(choices) > 64
            or any(not isinstance(item, str) for item in choices)
            or value not in choices
        ):
            return False
    return True


def _local_requirement_value(
    requirement: McpRegistryInputRequirement,
    candidate: Mapping[str, Any],
    configured_values: Mapping[str, SecretStr],
) -> str | None:
    if requirement.secret or requirement.user_value_needed:
        configured = configured_values.get(requirement.requirement_id)
        if not isinstance(configured, SecretStr):
            raise McpRegistryCatalogError(
                "mcp_registry_package_configuration_required"
            )
        value = configured.get_secret_value()
    elif requirement.fixed_value_declared:
        value = candidate.get("value")
    elif requirement.default_declared:
        value = candidate.get("default")
    else:
        return None
    if not isinstance(value, str) or not _local_value_valid_for_requirement(
        requirement,
        candidate,
        value,
    ):
        raise McpRegistryCatalogError("mcp_registry_package_configuration_invalid")
    return value


def _resolved_local_input(
    candidate: Any,
    *,
    location: RequirementLocation,
    fallback_name: str,
    identity_material: str,
    configured_values: Mapping[str, SecretStr],
) -> tuple[McpRegistryInputRequirement, str | None, tuple[str, ...]]:
    requirement = _input_requirement(
        candidate,
        location=location,
        fallback_name=fallback_name,
        identity_material=identity_material,
    )
    if requirement is None or not isinstance(candidate, Mapping):
        raise McpRegistryCatalogError("mcp_registry_package_option_changed")
    value = _local_requirement_value(requirement, candidate, configured_values)
    nested_ids: list[str] = []
    variables = candidate.get("variables")
    if variables is not None:
        if not isinstance(variables, Mapping) or len(variables) > MCP_REGISTRY_MAX_REQUIREMENTS:
            raise McpRegistryCatalogError("mcp_registry_package_option_changed")
        if value is None:
            raise McpRegistryCatalogError("mcp_registry_package_configuration_invalid")
        for variable_index, (variable_name, variable) in enumerate(variables.items()):
            safe_name = _bounded_text(variable_name, maximum=128)
            nested = _input_requirement(
                variable,
                location=location,
                fallback_name=safe_name or "",
                identity_material=(
                    f"{identity_material}\x00variable\x00{variable_index}"
                ),
            )
            if (
                safe_name is None
                or nested is None
                or not isinstance(variable, Mapping)
            ):
                raise McpRegistryCatalogError("mcp_registry_package_option_changed")
            replacement = _local_requirement_value(
                nested,
                variable,
                configured_values,
            )
            if replacement is None:
                raise McpRegistryCatalogError(
                    "mcp_registry_package_configuration_required"
                )
            value = value.replace(f"{{{safe_name}}}", replacement)
            nested_ids.append(nested.requirement_id)
    if value is not None and ("{" in value or "}" in value):
        raise McpRegistryCatalogError("mcp_registry_package_configuration_invalid")
    return requirement, value, tuple(nested_ids)


def _resolve_local_argument_sequence(
    value: Any,
    *,
    location: Literal["runtime_argument", "package_argument"],
    label: str,
    identity_material: str,
    configured_values: Mapping[str, SecretStr],
) -> tuple[tuple[SecretStr, ...], tuple[str, ...]]:
    if value is None:
        return (), ()
    sequence = _bounded_sequence(value)
    if sequence is None or len(sequence) > MCP_REGISTRY_MAX_REQUIREMENTS:
        raise McpRegistryCatalogError("mcp_registry_package_option_changed")
    arguments: list[SecretStr] = []
    requirement_ids: list[str] = []
    for index, candidate in enumerate(sequence):
        requirement, resolved, nested_ids = _resolved_local_input(
            candidate,
            location=location,
            fallback_name=f"{label} {index + 1}",
            identity_material=f"{identity_material}\x00{index}",
            configured_values=configured_values,
        )
        requirement_ids.extend((requirement.requirement_id, *nested_ids))
        if resolved is None:
            if requirement.required:
                raise McpRegistryCatalogError(
                    "mcp_registry_package_configuration_required"
                )
            continue
        argument_type = candidate.get("type") if isinstance(candidate, Mapping) else None
        if argument_type == "named":
            name = candidate.get("name")
            if not isinstance(name, str) or _LOCAL_NAMED_ARGUMENT.fullmatch(name) is None:
                raise McpRegistryCatalogError(
                    "mcp_registry_package_argument_invalid"
                )
            rendered = f"{name}={resolved}"
        elif argument_type == "positional":
            rendered = resolved
        else:
            raise McpRegistryCatalogError("mcp_registry_package_argument_invalid")
        if len(rendered.encode("utf-8")) > 2_048:
            raise McpRegistryCatalogError("mcp_registry_package_argument_invalid")
        arguments.append(SecretStr(rendered))
    return tuple(arguments), tuple(requirement_ids)


def _resolve_local_environment(
    value: Any,
    *,
    identity_material: str,
    configured_values: Mapping[str, SecretStr],
) -> tuple[tuple[McpRegistryResolvedLocalEnvironment, ...], tuple[str, ...]]:
    if value is None:
        return (), ()
    sequence = _bounded_sequence(value)
    if sequence is None or len(sequence) > MCP_REGISTRY_MAX_REQUIREMENTS:
        raise McpRegistryCatalogError("mcp_registry_package_option_changed")
    environment: list[McpRegistryResolvedLocalEnvironment] = []
    requirement_ids: list[str] = []
    seen: set[str] = set()
    for index, candidate in enumerate(sequence):
        requirement, resolved, nested_ids = _resolved_local_input(
            candidate,
            location="environment_variable",
            fallback_name=f"Environment variable {index + 1}",
            identity_material=f"{identity_material}\x00{index}",
            configured_values=configured_values,
        )
        requirement_ids.extend((requirement.requirement_id, *nested_ids))
        name = candidate.get("name") if isinstance(candidate, Mapping) else None
        if (
            not isinstance(name, str)
            or _LOCAL_ENVIRONMENT_NAME.fullmatch(name) is None
            or name.casefold() in seen
        ):
            raise McpRegistryCatalogError(
                "mcp_registry_package_environment_invalid"
            )
        seen.add(name.casefold())
        if resolved is None:
            if requirement.required:
                raise McpRegistryCatalogError(
                    "mcp_registry_package_configuration_required"
                )
            continue
        environment.append(
            McpRegistryResolvedLocalEnvironment(
                name=name,
                value=SecretStr(resolved),
            )
        )
    return tuple(environment), tuple(requirement_ids)


def _endpoint_template_names(value: str) -> tuple[str, ...] | None:
    matches = tuple(match.group(1) for match in _ENDPOINT_PLACEHOLDER.finditer(value))
    if not matches:
        return None
    remainder = _ENDPOINT_PLACEHOLDER.sub("", value)
    if "{" in remainder or "}" in remainder:
        return None
    return tuple(dict.fromkeys(matches))


def _endpoint_summary(
    value: Any,
) -> tuple[
    Literal["fixed_host", "template_requires_configuration", "invalid"],
    str | None,
    bool | None,
]:
    if not isinstance(value, str) or not value or len(value) > 1_024:
        return "invalid", None, None
    if "{" in value or "}" in value:
        return (
            ("template_requires_configuration", None, None)
            if _endpoint_template_names(value) is not None
            else ("invalid", None, None)
        )
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return "invalid", None, None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.fragment)
        or any(character in value for character in ("\r", "\n", "\x00"))
        or (port is not None and not 1 <= port <= 65_535)
    ):
        return "invalid", None, None
    host = parsed.hostname.casefold()
    if port is not None and port not in {80, 443}:
        host = f"{host}:{port}"
    return "fixed_host", host, parsed.scheme == "https"


def _compatibility(
    reasons: Sequence[ReviewCompatibilityReason],
) -> McpRegistryOptionCompatibility:
    unique = tuple(dict.fromkeys(reasons))
    reason_set = set(unique)
    if {
        "unknown_package_registry",
        "unknown_transport",
        "endpoint_invalid",
    } & reason_set:
        status: ReviewCompatibilityStatus = "unsupported"
    elif {
        "runtime_hint_missing",
        "configuration_required",
        "endpoint_template_requires_configuration",
    } & reason_set:
        status = "requires_configuration"
    else:
        status = "reviewable"
    return McpRegistryOptionCompatibility(status=status, reasons=unique)


def _bounded_requirements(
    groups: Sequence[tuple[list[McpRegistryInputRequirement], bool]],
) -> tuple[tuple[McpRegistryInputRequirement, ...], bool]:
    flattened: list[McpRegistryInputRequirement] = []
    partial = False
    for items, group_partial in groups:
        partial = partial or group_partial
        flattened.extend(items)
    if len(flattened) > MCP_REGISTRY_MAX_REQUIREMENTS:
        partial = True
        flattened = flattened[:MCP_REGISTRY_MAX_REQUIREMENTS]
    return tuple(flattened), partial


def _local_install_option(
    value: Any,
    *,
    server: McpRegistryServer,
    index: int,
) -> tuple[McpRegistryInstallOption | None, bool]:
    normalized = _parse_package(value)
    if normalized is None or not isinstance(value, Mapping):
        return None, True
    identity = f"{server.catalog_id}\x00local_package\x00{index}"
    transport_value = value.get("transport")
    transport_mapping = transport_value if isinstance(transport_value, Mapping) else {}
    if normalized.transport == "stdio":
        endpoint_state: Literal[
            "not_applicable",
            "fixed_host",
            "template_requires_configuration",
            "invalid",
        ] = "not_applicable"
        endpoint_host = None
        secure_transport = None
    else:
        endpoint_state, endpoint_host, secure_transport = _endpoint_summary(
            transport_mapping.get("url")
        )

    requirements, partial = _bounded_requirements(
        (
            _requirements_from_sequence(
                value.get("runtimeArguments"),
                location="runtime_argument",
                label="Runtime argument",
                identity_material=f"{identity}\x00runtime",
            ),
            _requirements_from_sequence(
                value.get("packageArguments"),
                location="package_argument",
                label="Package argument",
                identity_material=f"{identity}\x00package",
            ),
            _requirements_from_sequence(
                value.get("environmentVariables"),
                location="environment_variable",
                label="Environment variable",
                identity_material=f"{identity}\x00environment",
            ),
            _requirements_from_sequence(
                transport_mapping.get("headers"),
                location="transport_header",
                label="Transport header",
                identity_material=f"{identity}\x00header",
            ),
        )
    )
    has_runtime_arguments = bool(_bounded_sequence(value.get("runtimeArguments")))
    reasons: list[ReviewCompatibilityReason] = [
        (
            "known_package_registry"
            if normalized.registry_type in _KNOWN_PACKAGE_REGISTRIES
            else "unknown_package_registry"
        ),
        (
            "supported_transport"
            if normalized.transport in {"stdio", "streamable-http", "sse"}
            else "unknown_transport"
        ),
    ]
    if has_runtime_arguments and normalized.runtime_hint is None:
        reasons.append("runtime_hint_missing")
    if any(item.user_value_needed for item in requirements):
        reasons.append("configuration_required")
    if endpoint_state == "template_requires_configuration":
        reasons.append("endpoint_template_requires_configuration")
    elif endpoint_state == "invalid" and normalized.transport != "stdio":
        reasons.append("endpoint_invalid")
    reasons.extend(
        (
            "machine_runtime_not_probed",
            "platform_not_declared",
            "mcp_handshake_not_performed",
        )
    )

    risks: list[ReviewRisk] = ["downloads_package", "executes_local_code"]
    if not normalized.checksum_available:
        risks.append("package_integrity_not_declared")
    if bool(_bounded_sequence(value.get("runtimeArguments"))) or bool(
        _bounded_sequence(value.get("packageArguments"))
    ):
        risks.append("command_arguments_declared")
    if any(item.format == "filepath" for item in requirements):
        risks.append("filesystem_input_declared")
    if any(item.secret for item in requirements):
        risks.append("credential_input_declared")
    if normalized.transport in {"streamable-http", "sse"}:
        risks.append("remote_network_egress")
    if secure_transport is False:
        risks.append("insecure_remote_transport")

    option_id = hashlib.sha256(
        f"{identity}\x00{normalized.registry_type}\x00{normalized.identifier}".encode(
            "utf-8"
        )
    ).hexdigest()[:32]
    return (
        McpRegistryInstallOption(
            option_id=option_id,
            kind="local_package",
            label=f"{normalized.registry_type.upper()} package",
            registry_type=normalized.registry_type,
            package_identifier=normalized.identifier,
            package_version=normalized.version,
            runtime_hint=normalized.runtime_hint,
            transport=normalized.transport,
            endpoint_host=endpoint_host,
            endpoint_state=endpoint_state,
            secure_transport=secure_transport,
            checksum_state=(
                "declared" if normalized.checksum_available else "not_declared"
            ),
            requirements=requirements,
            risks=tuple(dict.fromkeys(risks)),
            compatibility=_compatibility(reasons),
            execution_material_digest=_execution_material_digest(
                value,
                fields=(
                    "registryType",
                    "identifier",
                    "version",
                    "runtimeHint",
                    "fileSha256",
                    "transport",
                    "runtimeArguments",
                    "packageArguments",
                    "environmentVariables",
                ),
            ),
        ),
        partial,
    )


def _remote_install_option(
    value: Any,
    *,
    server: McpRegistryServer,
    index: int,
) -> tuple[McpRegistryInstallOption | None, bool]:
    if not isinstance(value, Mapping):
        return None, True
    transport = _registry_transport(value.get("type"))
    endpoint_state, endpoint_host, secure_transport = _endpoint_summary(value.get("url"))
    identity = f"{server.catalog_id}\x00remote_server\x00{index}"
    requirements, partial = _bounded_requirements(
        (
            _requirements_from_sequence(
                value.get("headers"),
                location="transport_header",
                label="Transport header",
                identity_material=f"{identity}\x00header",
            ),
            _requirements_from_mapping(
                value.get("variables"),
                location="remote_variable",
                identity_material=f"{identity}\x00variable",
            ),
        )
    )
    reasons: list[ReviewCompatibilityReason] = [
        (
            "supported_transport"
            if transport in {"streamable-http", "sse"}
            else "unknown_transport"
        )
    ]
    if any(item.user_value_needed for item in requirements):
        reasons.append("configuration_required")
    if endpoint_state == "template_requires_configuration":
        reasons.append("endpoint_template_requires_configuration")
    elif endpoint_state == "invalid":
        reasons.append("endpoint_invalid")
    reasons.extend(
        (
            "machine_runtime_not_probed",
            "platform_not_declared",
            "mcp_handshake_not_performed",
        )
    )
    risks: list[ReviewRisk] = ["remote_network_egress"]
    if any(item.secret for item in requirements):
        risks.append("credential_input_declared")
    if secure_transport is False:
        risks.append("insecure_remote_transport")
    option_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return (
        McpRegistryInstallOption(
            option_id=option_id,
            kind="remote_server",
            label=(
                f"Remote · {endpoint_host}"
                if endpoint_host is not None
                else "Remote endpoint"
            ),
            transport=transport,
            endpoint_host=endpoint_host,
            endpoint_state=endpoint_state,
            secure_transport=secure_transport,
            checksum_state="not_applicable",
            requirements=requirements,
            risks=tuple(dict.fromkeys(risks)),
            compatibility=_compatibility(reasons),
            execution_material_digest=_execution_material_digest(
                value,
                fields=("type", "url", "headers", "variables"),
            ),
        ),
        partial,
    )


def _install_options(
    raw_server: Mapping[str, Any],
    server: McpRegistryServer,
) -> tuple[tuple[McpRegistryInstallOption, ...], bool]:
    options: list[McpRegistryInstallOption] = []
    partial = False
    raw_packages = raw_server.get("packages")
    if raw_packages is not None:
        packages = _bounded_sequence(raw_packages)
        if packages is None:
            partial = True
        else:
            partial = partial or len(packages) > MCP_REGISTRY_MAX_PACKAGES
            for index, value in enumerate(packages[:MCP_REGISTRY_MAX_PACKAGES]):
                option, option_partial = _local_install_option(
                    value, server=server, index=index
                )
                partial = partial or option_partial
                if option is not None:
                    options.append(option)
    raw_remotes = raw_server.get("remotes")
    if raw_remotes is not None:
        remotes = _bounded_sequence(raw_remotes)
        if remotes is None:
            partial = True
        else:
            partial = partial or len(remotes) > MCP_REGISTRY_MAX_REMOTES
            for index, value in enumerate(remotes[:MCP_REGISTRY_MAX_REMOTES]):
                option, option_partial = _remote_install_option(
                    value, server=server, index=index
                )
                partial = partial or option_partial
                if option is not None:
                    options.append(option)
    return tuple(options[:MCP_REGISTRY_MAX_INSTALL_OPTIONS]), partial


def _provenance(
    raw_server: Mapping[str, Any], server: McpRegistryServer
) -> McpRegistryProvenance:
    repository = raw_server.get("repository")
    repository_mapping = repository if isinstance(repository, Mapping) else {}
    source = _bounded_text(repository_mapping.get("source"), maximum=32)
    return McpRegistryProvenance(
        publisher_namespace=server.publisher,
        repository_url=server.repository_url,
        repository_source=source,
        repository_identity_declared=(
            _bounded_text(repository_mapping.get("id"), maximum=256) is not None
        ),
        repository_subfolder_declared=(
            _bounded_text(repository_mapping.get("subfolder"), maximum=512) is not None
        ),
        website_url=server.website_url,
        schema_url=_safe_https_url(raw_server.get("$schema")),
    )


def _version_history(
    payload: Mapping[str, Any],
    *,
    selected: McpRegistryServer,
) -> tuple[tuple[McpRegistryVersionSummary, ...], Literal["live", "partial"]]:
    raw_versions = payload.get("servers")
    if not isinstance(raw_versions, Sequence) or isinstance(
        raw_versions, (str, bytes, bytearray)
    ):
        return (
            (
                McpRegistryVersionSummary(
                    version=selected.version,
                    status=selected.status,
                    updated_at=selected.updated_at,
                    selected=True,
                ),
            ),
            "partial",
        )
    partial = len(raw_versions) > MCP_REGISTRY_MAX_VERSIONS
    versions: list[McpRegistryVersionSummary] = []
    seen: set[str] = set()
    for candidate in raw_versions[:MCP_REGISTRY_MAX_VERSIONS]:
        parsed = _parse_server(candidate)
        if parsed is None:
            partial = True
            continue
        server, _icon = parsed
        if server.name != selected.name or server.version in seen:
            partial = True
            continue
        seen.add(server.version)
        versions.append(
            McpRegistryVersionSummary(
                version=server.version,
                status=server.status,
                updated_at=server.updated_at,
                selected=server.version == selected.version,
            )
        )
    if selected.version not in seen:
        partial = True
        if len(versions) == MCP_REGISTRY_MAX_VERSIONS:
            versions.pop()
        versions.insert(
            0,
            McpRegistryVersionSummary(
                version=selected.version,
                status=selected.status,
                updated_at=selected.updated_at,
                selected=True,
            ),
        )
    return tuple(versions), "partial" if partial else "live"


class McpRegistryCatalogService:
    """Fetch, normalize and cache public official-registry metadata."""

    def __init__(
        self,
        client: McpRegistryClient,
        cache: McpRegistryCache,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._cache = cache
        self._clock = clock or (lambda: datetime.now(UTC))
        self._icon_sources: dict[str, str] = {}
        self._icon_cache: dict[str, McpRegistryIconContent] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _normalize_search(value: str | None) -> str:
        raw = value or ""
        if not isinstance(raw, str) or not _unicode_text_safe(raw):
            raise McpRegistryCatalogError("mcp_registry_query_invalid")
        normalized = unicodedata.normalize("NFC", " ".join(raw.strip().split()))
        if len(normalized) > MCP_REGISTRY_MAX_SEARCH_CHARS or not _unicode_text_safe(normalized):
            raise McpRegistryCatalogError("mcp_registry_query_invalid")
        return normalized

    @staticmethod
    def _normalize_cursor(value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if _safe_exact_text(value, maximum=MCP_REGISTRY_MAX_CURSOR_CHARS) is None:
            raise McpRegistryCatalogError("mcp_registry_cursor_invalid")
        return value

    @staticmethod
    def _cache_key(search: str, cursor: str | None, limit: int) -> str:
        material = f"v1\x00{search}\x00{cursor or ''}\x00{limit}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    def _register_icons(self, sources: Mapping[str, str]) -> None:
        with self._lock:
            for key, source in sources.items():
                if len(self._icon_sources) >= MCP_REGISTRY_MAX_ICON_SOURCES:
                    break
                trusted_source = _trusted_icon_source(source)
                expected_key = (
                    hashlib.sha256(trusted_source.encode("utf-8")).hexdigest()[:32]
                    if trusted_source is not None
                    else None
                )
                if _ICON_KEY_PATTERN.fullmatch(key) and key == expected_key:
                    self._icon_sources[key] = trusted_source

    def _catalog(self, record: McpRegistryCacheRecord, *, delivery: RegistryDelivery) -> McpRegistryCatalog:
        now = _utc(self._clock())
        age = max(0, int((now - record.fetched_at).total_seconds()))
        self._register_icons(record.icon_sources)
        return McpRegistryCatalog(
            source=McpRegistrySourceStatus(
                fetched_at=record.fetched_at,
                delivery=delivery,
                cache_age_seconds=age,
            ),
            search=record.search,
            servers=record.servers,
            next_cursor=record.next_cursor,
            partial=record.partial,
        )

    def list_servers(
        self,
        *,
        search: str | None = None,
        cursor: str | None = None,
        limit: int = MCP_REGISTRY_DEFAULT_LIMIT,
    ) -> McpRegistryCatalog:
        normalized_search = self._normalize_search(search)
        normalized_cursor = self._normalize_cursor(cursor)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MCP_REGISTRY_MAX_LIMIT:
            raise McpRegistryCatalogError("mcp_registry_limit_invalid")
        cache_key = self._cache_key(normalized_search, normalized_cursor, limit)
        failure_code = "mcp_registry_unavailable"
        try:
            payload = self._client.list_servers(
                search=normalized_search,
                cursor=normalized_cursor,
                limit=limit,
            )
            raw_servers = payload.get("servers")
            metadata = payload.get("metadata")
            if (
                not isinstance(raw_servers, Sequence)
                or isinstance(raw_servers, (str, bytes, bytearray))
                or not isinstance(metadata, Mapping)
            ):
                raise McpRegistryCatalogError("mcp_registry_response_invalid")
            partial = len(raw_servers) > MCP_REGISTRY_MAX_SERVERS
            parsed_servers: list[McpRegistryServer] = []
            parsed_by_id: dict[str, McpRegistryServer] = {}
            icon_sources: dict[str, str] = {}
            for raw in raw_servers[:MCP_REGISTRY_MAX_SERVERS]:
                parsed = _parse_server(raw)
                if parsed is None:
                    partial = True
                    continue
                server, icon_source = parsed
                existing = parsed_by_id.get(server.catalog_id)
                if existing is not None:
                    if existing != server:
                        raise McpRegistryCatalogError(
                            "mcp_registry_identity_conflict"
                        )
                    continue
                parsed_by_id[server.catalog_id] = server
                parsed_servers.append(server)
                if icon_source is not None:
                    icon_sources[icon_source[0]] = icon_source[1]
            next_cursor = metadata.get("nextCursor")
            if next_cursor is not None:
                next_cursor = self._normalize_cursor(next_cursor)
            if normalized_cursor is not None and next_cursor == normalized_cursor:
                raise McpRegistryCatalogError("mcp_registry_pagination_cycle")
            record = McpRegistryCacheRecord(
                fetched_at=_utc(self._clock()),
                search=normalized_search,
                cursor=normalized_cursor,
                limit=limit,
                servers=tuple(parsed_servers),
                next_cursor=next_cursor,
                partial=partial,
                icon_sources=icon_sources,
            )
            try:
                self._cache.put(cache_key, record)
            except Exception:
                # A public metadata cache failure must not disable a valid live response.
                pass
            return self._catalog(record, delivery="live")
        except McpRegistryCatalogError as error:
            if error.code in {
                "mcp_registry_query_invalid",
                "mcp_registry_cursor_invalid",
                "mcp_registry_limit_invalid",
            }:
                raise
            failure_code = error.code
        except McpRegistryClientError as error:
            failure_code = (
                "mcp_registry_response_invalid"
                if error.code in {
                    "registry_response_invalid",
                    "registry_response_too_large",
                }
                else "mcp_registry_unavailable"
            )
        except Exception:
            failure_code = "mcp_registry_unavailable"
        try:
            cached = self._cache.get(cache_key)
        except Exception:
            cached = None
        if cached is None:
            raise McpRegistryCatalogError(failure_code)
        return self._catalog(cached, delivery="cached")

    @staticmethod
    def _validate_server_identity(
        *,
        catalog_id: str,
        name: str,
        version: str,
    ) -> None:
        if not _ICON_KEY_PATTERN.fullmatch(catalog_id):
            raise McpRegistryCatalogError("mcp_registry_server_identity_invalid")
        if not _NAME_PATTERN.fullmatch(name):
            raise McpRegistryCatalogError("mcp_registry_server_identity_invalid")
        if (
            not version
            or len(version) > 255
            or version != version.strip()
            or _safe_exact_text(version, maximum=255) is None
            or _catalog_id(name, version) != catalog_id
        ):
            raise McpRegistryCatalogError("mcp_registry_server_identity_invalid")

    def _exact_review_components(
        self,
        *,
        catalog_id: str,
        name: str,
        version: str,
        presentation_revision: str | None = None,
    ) -> tuple[
        Mapping[str, Any],
        McpRegistryServer,
        McpRegistryProvenance,
        tuple[McpRegistryInstallOption, ...],
        str,
        bool,
    ]:
        self._validate_server_identity(
            catalog_id=catalog_id,
            name=name,
            version=version,
        )
        if presentation_revision is not None and re.fullmatch(
            r"^[0-9a-f]{64}$",
            presentation_revision,
        ) is None:
            raise McpRegistryCatalogError("mcp_registry_server_identity_invalid")
        try:
            payload = self._client.get_server_version(name=name, version=version)
        except McpRegistryClientError as error:
            if error.code == "registry_server_not_found":
                raise McpRegistryCatalogError("mcp_registry_server_not_found") from None
            raise McpRegistryCatalogError("mcp_registry_unavailable") from None
        except Exception:
            raise McpRegistryCatalogError("mcp_registry_unavailable") from None
        parsed = _parse_server(payload)
        raw_server = payload.get("server")
        if parsed is None or not isinstance(raw_server, Mapping):
            raise McpRegistryCatalogError("mcp_registry_response_invalid")
        server, icon_source = parsed
        if (
            server.catalog_id != catalog_id
            or server.name != name
            or server.version != version
        ):
            raise McpRegistryCatalogError("mcp_registry_response_invalid")
        if (
            presentation_revision is not None
            and server.presentation_revision != presentation_revision
        ):
            raise McpRegistryCatalogError("mcp_registry_source_disagreement")
        if icon_source is not None:
            self._register_icons({icon_source[0]: icon_source[1]})
        options, options_partial = _install_options(raw_server, server)
        provenance = _provenance(raw_server, server)
        return (
            raw_server,
            server,
            provenance,
            options,
            _review_plan_revision(server, provenance, options),
            options_partial,
        )

    def review_server(
        self,
        *,
        catalog_id: str,
        name: str,
        version: str,
        presentation_revision: str | None = None,
    ) -> McpRegistryServerReview:
        (
            _raw_server,
            server,
            provenance,
            options,
            plan_revision,
            options_partial,
        ) = self._exact_review_components(
            catalog_id=catalog_id,
            name=name,
            version=version,
            presentation_revision=presentation_revision,
        )
        try:
            history_payload = self._client.list_server_versions(name=name)
            versions, history_state = _version_history(
                history_payload,
                selected=server,
            )
        except Exception:
            versions = (
                McpRegistryVersionSummary(
                    version=server.version,
                    status=server.status,
                    updated_at=server.updated_at,
                    selected=True,
                ),
            )
            history_state = "unavailable"

        now = _utc(self._clock())
        return McpRegistryServerReview(
            source=McpRegistrySourceStatus(
                fetched_at=now,
                delivery="live",
                cache_age_seconds=0,
            ),
            server=server,
            provenance=provenance,
            versions=versions,
            version_history_state=history_state,
            options=options,
            plan_revision=plan_revision,
            partial=options_partial or history_state != "live",
        )

    def review_latest_server(self, *, name: str) -> McpRegistryServerReview:
        """Resolve the official ``latest`` alias, then re-fetch that exact version."""

        if not _NAME_PATTERN.fullmatch(name):
            raise McpRegistryCatalogError("mcp_registry_server_identity_invalid")
        try:
            payload = self._client.get_server_version(
                name=name,
                version="latest",
            )
        except McpRegistryClientError as error:
            if error.code == "registry_server_not_found":
                raise McpRegistryCatalogError(
                    "mcp_registry_server_not_found"
                ) from None
            raise McpRegistryCatalogError("mcp_registry_unavailable") from None
        except Exception:
            raise McpRegistryCatalogError("mcp_registry_unavailable") from None
        parsed = _parse_server(payload)
        if parsed is None:
            raise McpRegistryCatalogError("mcp_registry_response_invalid")
        latest, _icon_source = parsed
        if latest.name != name:
            raise McpRegistryCatalogError("mcp_registry_response_invalid")
        return self.review_server(
            catalog_id=latest.catalog_id,
            name=latest.name,
            version=latest.version,
        )

    def resolve_remote_connection(
        self,
        *,
        catalog_id: str,
        name: str,
        version: str,
        option_id: str,
        plan_revision: str,
        variable_values: Mapping[str, SecretStr] | None = None,
    ) -> McpRegistryResolvedRemoteConnection:
        """Re-fetch one exact plan and return transient remote material.

        This method is intentionally not exposed by the Registry HTTP router.
        The caller supplies reviewed endpoint-variable values only from its OS
        vault. The guarded transport independently rechecks the fully resolved
        HTTPS origin and egress policy.
        """

        if (
            _ICON_KEY_PATTERN.fullmatch(option_id) is None
            or re.fullmatch(r"^[0-9a-f]{64}$", plan_revision) is None
        ):
            raise McpRegistryCatalogError("mcp_registry_connection_identity_invalid")
        (
            raw_server,
            server,
            _provenance_value,
            options,
            current_revision,
            options_partial,
        ) = self._exact_review_components(
            catalog_id=catalog_id,
            name=name,
            version=version,
        )
        if current_revision != plan_revision:
            raise McpRegistryCatalogError("mcp_registry_connection_plan_changed")
        selected = next((item for item in options if item.option_id == option_id), None)
        if selected is None:
            raise McpRegistryCatalogError("mcp_registry_connection_option_changed")
        if (
            selected.kind != "remote_server"
            or selected.transport not in {"streamable-http", "sse"}
            or selected.endpoint_state not in {
                "fixed_host",
                "template_requires_configuration",
            }
            or (
                selected.endpoint_state == "fixed_host"
                and (
                    selected.secure_transport is not True
                    or selected.endpoint_host is None
                )
            )
            or (
                selected.endpoint_state == "template_requires_configuration"
                and (
                    selected.secure_transport is not None
                    or selected.endpoint_host is not None
                )
            )
            or selected.compatibility.status == "unsupported"
            or options_partial
        ):
            raise McpRegistryCatalogError("mcp_registry_connection_not_probeable")

        remotes = _bounded_sequence(raw_server.get("remotes"))
        if remotes is None:
            raise McpRegistryCatalogError("mcp_registry_connection_option_changed")
        raw_remote: Mapping[str, Any] | None = None
        remote_index = -1
        for index, candidate in enumerate(remotes[:MCP_REGISTRY_MAX_REMOTES]):
            normalized, partial = _remote_install_option(
                candidate,
                server=server,
                index=index,
            )
            if (
                normalized is not None
                and normalized.option_id == option_id
                and not partial
                and isinstance(candidate, Mapping)
            ):
                raw_remote = candidate
                remote_index = index
                if normalized != selected:
                    raise McpRegistryCatalogError(
                        "mcp_registry_connection_option_changed"
                    )
                break
        if raw_remote is None:
            raise McpRegistryCatalogError("mcp_registry_connection_option_changed")
        endpoint = raw_remote.get("url")
        endpoint_state, endpoint_host, secure = _endpoint_summary(endpoint)
        if (
            not isinstance(endpoint, str)
            or len(endpoint) > 2_048
            or endpoint_state != selected.endpoint_state
            or (
                endpoint_state == "fixed_host"
                and (
                    endpoint_host != selected.endpoint_host
                    or secure is not True
                )
            )
        ):
            raise McpRegistryCatalogError("mcp_registry_connection_option_changed")

        variables = raw_remote.get("variables")
        if variables is None:
            variable_items: list[tuple[Any, Any]] = []
        elif isinstance(variables, Mapping):
            if len(variables) > MCP_REGISTRY_MAX_REQUIREMENTS:
                raise McpRegistryCatalogError(
                    "mcp_registry_connection_not_probeable"
                )
            variable_items = list(variables.items())
        else:
            raise McpRegistryCatalogError("mcp_registry_connection_option_changed")

        identity = f"{server.catalog_id}\x00remote_server\x00{remote_index}"
        resolved_variables: list[
            tuple[str, McpRegistryInputRequirement, str | None]
        ] = []
        seen_variables: set[str] = set()
        for index, (raw_name, candidate) in enumerate(variable_items):
            safe_name = _bounded_text(raw_name, maximum=128)
            if (
                safe_name is None
                or _ENDPOINT_VARIABLE_NAME.fullmatch(safe_name) is None
                or safe_name in seen_variables
                or not isinstance(candidate, Mapping)
            ):
                raise McpRegistryCatalogError(
                    "mcp_registry_connection_option_changed"
                )
            seen_variables.add(safe_name)
            normalized_candidate = dict(candidate)
            normalized_candidate["name"] = safe_name
            requirement = _input_requirement(
                normalized_candidate,
                location="remote_variable",
                fallback_name=safe_name,
                identity_material=f"{identity}\x00variable\x00{index}",
            )
            if requirement is None:
                raise McpRegistryCatalogError(
                    "mcp_registry_connection_option_changed"
                )
            declared = (
                candidate.get("value")
                if requirement.fixed_value_declared
                else candidate.get("default")
                if requirement.default_declared
                else None
            )
            if declared is not None and not isinstance(declared, str):
                raise McpRegistryCatalogError(
                    "mcp_registry_connection_configuration_required"
                )
            if declared is not None and (
                any(character in declared for character in ("\x00", "\r", "\n"))
                or len(declared.encode("utf-8")) > 2_048
            ):
                raise McpRegistryCatalogError(
                    "mcp_registry_connection_configuration_required"
                )
            resolved_variables.append((safe_name, requirement, declared))
        if {item.requirement_id for _, item, _ in resolved_variables} != {
            item.requirement_id
            for item in selected.requirements
            if item.location == "remote_variable"
        }:
            raise McpRegistryCatalogError("mcp_registry_connection_option_changed")

        supplied = dict(variable_values or {})
        if any(not isinstance(value, SecretStr) for value in supplied.values()):
            raise McpRegistryCatalogError(
                "mcp_registry_connection_configuration_required"
            )
        expected_supplied = {
            item.requirement_id
            for _, item, _ in resolved_variables
            if item.secret or item.user_value_needed
        }
        if not set(supplied).issubset(expected_supplied):
            raise McpRegistryCatalogError(
                "mcp_registry_connection_configuration_required"
            )
        if endpoint_state == "fixed_host":
            if resolved_variables or supplied:
                raise McpRegistryCatalogError(
                    "mcp_registry_connection_option_changed"
                )
            resolved_endpoint = endpoint
            resolved_endpoint_host = endpoint_host
        else:
            template_names = _endpoint_template_names(endpoint)
            if (
                template_names is None
                or set(template_names) != {
                    name for name, _, _ in resolved_variables
                }
            ):
                raise McpRegistryCatalogError(
                    "mcp_registry_connection_option_changed"
                )
            substitutions: dict[str, str] = {}
            for variable_name, requirement, declared in resolved_variables:
                if requirement.secret or requirement.user_value_needed:
                    supplied_value = supplied.get(requirement.requirement_id)
                    raw_value = (
                        None
                        if supplied_value is None
                        else supplied_value.get_secret_value()
                    )
                else:
                    raw_value = declared
                if (
                    raw_value is None
                    or not raw_value
                    or any(
                        character in raw_value
                        for character in ("\x00", "\r", "\n", "{", "}")
                    )
                    or len(raw_value.encode("utf-8")) > 2_048
                ):
                    raise McpRegistryCatalogError(
                        "mcp_registry_connection_configuration_required"
                    )
                substitutions[variable_name] = raw_value
            resolved_endpoint = _ENDPOINT_PLACEHOLDER.sub(
                lambda match: substitutions[match.group(1)],
                endpoint,
            )
            (
                resolved_state,
                resolved_endpoint_host,
                resolved_secure,
            ) = _endpoint_summary(resolved_endpoint)
            if resolved_state != "fixed_host" or resolved_secure is not True:
                raise McpRegistryCatalogError(
                    "mcp_registry_connection_configuration_required"
                )
        if resolved_endpoint_host is None:
            raise McpRegistryCatalogError(
                "mcp_registry_connection_configuration_required"
            )

        raw_headers = raw_remote.get("headers")
        if raw_headers is None:
            header_items: Sequence[Any] = ()
        else:
            header_items = _bounded_sequence(raw_headers) or ()
            if not isinstance(raw_headers, Sequence) or isinstance(
                raw_headers, (str, bytes, bytearray)
            ):
                raise McpRegistryCatalogError("mcp_registry_connection_option_changed")
            if len(header_items) > MCP_REGISTRY_MAX_REQUIREMENTS:
                raise McpRegistryCatalogError("mcp_registry_connection_not_probeable")
        headers: list[McpRegistryResolvedRemoteHeader] = []
        seen_names: set[str] = set()
        for index, candidate in enumerate(header_items):
            if not isinstance(candidate, Mapping) or candidate.get("variables"):
                raise McpRegistryCatalogError(
                    "mcp_registry_connection_configuration_required"
                )
            requirement = _input_requirement(
                candidate,
                location="transport_header",
                fallback_name=f"Remote header {index + 1}",
                identity_material=f"{identity}\x00header\x00{index}",
            )
            if requirement is None:
                raise McpRegistryCatalogError("mcp_registry_connection_option_changed")
            declared = (
                candidate.get("value")
                if requirement.fixed_value_declared
                else candidate.get("default")
                if requirement.default_declared
                else None
            )
            if declared is not None and not isinstance(declared, str):
                raise McpRegistryCatalogError(
                    "mcp_registry_connection_configuration_required"
                )
            if (
                not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}", requirement.name)
                or requirement.name.casefold() in seen_names
            ):
                raise McpRegistryCatalogError("mcp_registry_connection_header_invalid")
            seen_names.add(requirement.name.casefold())
            if declared is not None and (
                any(character in declared for character in ("\x00", "\r", "\n"))
                or len(declared.encode("utf-8")) > 8 * 1024
            ):
                raise McpRegistryCatalogError("mcp_registry_connection_header_invalid")
            headers.append(
                McpRegistryResolvedRemoteHeader(
                    requirement_id=requirement.requirement_id,
                    name=requirement.name,
                    required=requirement.required,
                    secret=requirement.secret,
                    declared_value=(
                        None
                        if requirement.secret or declared is None
                        else SecretStr(declared)
                    ),
                )
            )
        if {item.requirement_id for item in headers} != {
            item.requirement_id
            for item in selected.requirements
            if item.location == "transport_header"
        }:
            raise McpRegistryCatalogError("mcp_registry_connection_option_changed")
        return McpRegistryResolvedRemoteConnection(
            catalog_id=catalog_id,
            option_id=option_id,
            plan_revision=plan_revision,
            transport=selected.transport,
            endpoint_host=resolved_endpoint_host,
            endpoint=SecretStr(resolved_endpoint),
            headers=tuple(headers),
        )

    def resolve_local_package(
        self,
        *,
        catalog_id: str,
        name: str,
        version: str,
        option_id: str,
        plan_revision: str,
        configuration_values: Mapping[str, SecretStr] | None = None,
        inspection_only: bool = False,
    ) -> McpRegistryResolvedLocalPackage:
        """Re-fetch one exact reviewed MCPB artifact and expose it transiently.

        Store-05b intentionally supports only checksum-pinned MCPB release
        archives. Other package registries need registry-specific resolution,
        lockfile and integrity adapters before they can become executable.
        """

        if (
            _ICON_KEY_PATTERN.fullmatch(option_id) is None
            or re.fullmatch(r"^[0-9a-f]{64}$", plan_revision) is None
        ):
            raise McpRegistryCatalogError("mcp_registry_package_identity_invalid")
        (
            raw_server,
            server,
            _provenance_value,
            options,
            current_revision,
            options_partial,
        ) = self._exact_review_components(
            catalog_id=catalog_id,
            name=name,
            version=version,
        )
        if current_revision != plan_revision:
            raise McpRegistryCatalogError("mcp_registry_package_plan_changed")
        selected = next((item for item in options if item.option_id == option_id), None)
        if selected is None:
            raise McpRegistryCatalogError("mcp_registry_package_option_changed")
        if (
            selected.kind != "local_package"
            or selected.registry_type != "mcpb"
            or selected.transport != "stdio"
            or selected.checksum_state != "declared"
            or selected.compatibility.status == "unsupported"
            or options_partial
        ):
            raise McpRegistryCatalogError("mcp_registry_package_not_installable")
        provided = configuration_values or {}
        expected_configured_ids = {
            item.requirement_id
            for item in selected.requirements
            if item.secret or item.user_value_needed
        }
        if not inspection_only and (
            any(not isinstance(key, str) or not isinstance(value, SecretStr) for key, value in provided.items())
            or set(provided) != expected_configured_ids
        ):
            raise McpRegistryCatalogError(
                "mcp_registry_package_configuration_required"
            )

        packages = _bounded_sequence(raw_server.get("packages"))
        if packages is None:
            raise McpRegistryCatalogError("mcp_registry_package_option_changed")
        raw_package: Mapping[str, Any] | None = None
        raw_package_index: int | None = None
        for index, candidate in enumerate(packages[:MCP_REGISTRY_MAX_PACKAGES]):
            normalized, partial = _local_install_option(
                candidate,
                server=server,
                index=index,
            )
            if (
                normalized is not None
                and normalized.option_id == option_id
                and not partial
                and isinstance(candidate, Mapping)
                ):
                if normalized != selected:
                    raise McpRegistryCatalogError(
                        "mcp_registry_package_option_changed"
                    )
                raw_package = candidate
                raw_package_index = index
                break
        if raw_package is None or raw_package_index is None:
            raise McpRegistryCatalogError("mcp_registry_package_option_changed")

        if inspection_only:
            if configuration_values:
                raise McpRegistryCatalogError(
                    "mcp_registry_package_configuration_invalid"
                )
            runtime_arguments: tuple[SecretStr, ...] = ()
            package_arguments: tuple[SecretStr, ...] = ()
            environment: tuple[McpRegistryResolvedLocalEnvironment, ...] = ()
        else:
            identity = f"{server.catalog_id}\x00local_package\x00{raw_package_index}"
            runtime_arguments, runtime_requirement_ids = (
                _resolve_local_argument_sequence(
                    raw_package.get("runtimeArguments"),
                    location="runtime_argument",
                    label="Runtime argument",
                    identity_material=f"{identity}\x00runtime",
                    configured_values=provided,
                )
            )
            package_arguments, package_requirement_ids = (
                _resolve_local_argument_sequence(
                    raw_package.get("packageArguments"),
                    location="package_argument",
                    label="Package argument",
                    identity_material=f"{identity}\x00package",
                    configured_values=provided,
                )
            )
            environment, environment_requirement_ids = _resolve_local_environment(
                raw_package.get("environmentVariables"),
                identity_material=f"{identity}\x00environment",
                configured_values=provided,
            )
            if set(
                (
                    *runtime_requirement_ids,
                    *package_requirement_ids,
                    *environment_requirement_ids,
                )
            ) != {item.requirement_id for item in selected.requirements}:
                raise McpRegistryCatalogError("mcp_registry_package_option_changed")
        identifier = raw_package.get("identifier")
        checksum = raw_package.get("fileSha256")
        try:
            parsed = urlsplit(identifier if isinstance(identifier, str) else "")
            host = (parsed.hostname or "").encode("idna").decode("ascii").casefold()
            port = parsed.port
        except (UnicodeError, ValueError):
            raise McpRegistryCatalogError("mcp_registry_package_url_invalid") from None
        release_path = parsed.path.casefold()
        github_release = host == "github.com" and "/releases/download/" in release_path
        gitlab_release = host == "gitlab.com" and "/-/releases/" in release_path
        if (
            not isinstance(identifier, str)
            or len(identifier) > 512
            or parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
            or bool(parsed.query)
            or bool(parsed.fragment)
            or not release_path.endswith(".mcpb")
            or not (github_release or gitlab_release)
            or not isinstance(checksum, str)
            or re.fullmatch(r"[0-9a-f]{64}", checksum) is None
        ):
            raise McpRegistryCatalogError("mcp_registry_package_url_invalid")
        return McpRegistryResolvedLocalPackage(
            catalog_id=catalog_id,
            option_id=option_id,
            plan_revision=plan_revision,
            package_identifier=SecretStr(identifier),
            package_version=selected.package_version,
            file_sha256=checksum,
            execution_configuration_state=(
                "inspection_only" if inspection_only else "resolved"
            ),
            runtime_arguments=runtime_arguments,
            package_arguments=package_arguments,
            environment=environment,
        )

    def get_icon(self, key: str) -> McpRegistryIconContent:
        if not _ICON_KEY_PATTERN.fullmatch(key):
            raise McpRegistryCatalogError("mcp_registry_icon_not_found")
        with self._lock:
            cached = self._icon_cache.get(key)
            source = self._icon_sources.get(key)
        if cached is not None:
            return cached
        if source is None:
            raise McpRegistryCatalogError("mcp_registry_icon_not_found")
        try:
            content = self._client.fetch_icon(source)
        except Exception:
            raise McpRegistryCatalogError("mcp_registry_icon_unavailable") from None
        if (
            content.media_type not in {"image/png", "image/jpeg", "image/webp"}
            or not _valid_icon_content(content)
        ):
            raise McpRegistryCatalogError("mcp_registry_icon_unavailable")
        with self._lock:
            if len(self._icon_cache) >= MCP_REGISTRY_MAX_ICON_CACHE_ITEMS:
                self._icon_cache.pop(next(iter(self._icon_cache)))
            self._icon_cache[key] = content
        return content


__all__ = (
    "MCP_REGISTRY_BASE_URL",
    "MCP_REGISTRY_CATALOG_CONTRACT_VERSION",
    "MCP_REGISTRY_SERVER_REVIEW_CONTRACT_VERSION",
    "MCP_STORE_CATALOG_PATH",
    "MCP_STORE_ICON_PATH_PREFIX",
    "MCP_STORE_SERVER_PATH_PREFIX",
    "McpRegistryCache",
    "McpRegistryCacheRecord",
    "McpRegistryCatalog",
    "McpRegistryCatalogError",
    "McpRegistryCatalogService",
    "McpRegistryClient",
    "McpRegistryClientError",
    "McpRegistryIconContent",
    "McpRegistryResolvedLocalEnvironment",
    "McpRegistryResolvedLocalPackage",
    "McpRegistryResolvedRemoteConnection",
    "McpRegistryResolvedRemoteHeader",
    "McpRegistryServerReview",
)
