"""Bounded MCP client-host contract.

The Store may discover an untrusted MCP server, but discovery is not tool
authority.  This module defines the narrow compatibility-probe boundary used
between reviewed management plans and transport adapters. Raw endpoints and
headers are transient inputs only. Exact bounded tool contracts may be retained
locally for owner review and project admission, while durable public receipts
contain only counts and deterministic contract digests.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import ipaddress
import json
import math
import re
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from jsonschema import FormatChecker
from jsonschema.exceptions import SchemaError as JsonSchemaSchemaError
from jsonschema.validators import validator_for
from pydantic import Field, SecretStr, field_validator, model_validator

from ..domain import StrictModel


MCP_GUARDED_HOST_CONTRACT_VERSION = "mcp-guarded-host.v1"
MAX_MCP_PROBE_SECONDS = 20.0
MAX_MCP_PROBE_TOOLS = 256
MAX_MCP_TOOL_PAGES = 16
MAX_MCP_TOOL_NAME_CHARS = 128
MAX_MCP_TOOL_TITLE_CHARS = 256
MAX_MCP_TOOL_DESCRIPTION_CHARS = 4_096
MAX_MCP_TOOL_METADATA_TOTAL_BYTES = 512 * 1024
MAX_MCP_SCHEMA_BYTES = 256 * 1024
MAX_MCP_SCHEMA_TOTAL_BYTES = 1024 * 1024
MAX_MCP_SCHEMA_DEPTH = 32
MAX_MCP_SCHEMA_NODES = 8_192
MAX_MCP_SCHEMA_COLLECTION_ITEMS = 1_024
MAX_MCP_SCHEMA_STRING_CHARS = 32_768
MAX_MCP_SCHEMA_BRANCHES = 64
MAX_MCP_SCHEMA_ENUM_ITEMS = 256
MAX_MCP_SCHEMA_PROPERTIES = 256
MAX_MCP_SCHEMA_PATTERN_CHARS = 256
MAX_MCP_REMOTE_HEADERS = 32
MAX_MCP_REMOTE_HEADER_VALUE_BYTES = 8 * 1024
MAX_MCP_ENDPOINT_CHARS = 2_048

_ID_PATTERN = r"^[0-9a-f]{32}$"
_DIGEST_PATTERN = r"^[0-9a-f]{64}$"
_PROTOCOL_PATTERN = r"^20[0-9]{2}-[0-9]{2}-[0-9]{2}$"
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_.:/-]{1,128}$")
_HEADER_NAME = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]{1,128}$")
_RESERVED_HEADERS = frozenset(
    {
        "accept-encoding",
        "connection",
        "content-encoding",
        "content-length",
        "content-type",
        "host",
        "mcp-method",
        "mcp-name",
        "mcp-protocol-version",
        "mcp-session-id",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_SUPPORTED_JSON_SCHEMA_DIALECTS = frozenset(
    {
        "http://json-schema.org/draft-07/schema#",
        "https://json-schema.org/draft-07/schema#",
        "https://json-schema.org/draft/2020-12/schema",
        "https://json-schema.org/draft/2020-12/schema#",
    }
)
_SCHEMA_MAPPING_KEYWORDS = frozenset(
    {"$defs", "definitions", "properties", "dependentSchemas"}
)
_SCHEMA_PATTERN_MAPPING_KEYWORDS = frozenset({"patternProperties"})
_SCHEMA_SINGLE_KEYWORDS = frozenset(
    {
        "additionalItems",
        "additionalProperties",
        "contains",
        "contentSchema",
        "else",
        "if",
        "items",
        "not",
        "propertyNames",
        "then",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
)
_SCHEMA_SEQUENCE_KEYWORDS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
_SCHEMA_SCALAR_KEYWORDS = frozenset(
    {
        "$comment",
        "$ref",
        "$schema",
        "const",
        "contentEncoding",
        "contentMediaType",
        "default",
        "deprecated",
        "dependentRequired",
        "description",
        "enum",
        "examples",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "format",
        "maxContains",
        "maxItems",
        "maxLength",
        "maxProperties",
        "maximum",
        "minContains",
        "minItems",
        "minLength",
        "minProperties",
        "minimum",
        "multipleOf",
        "pattern",
        "readOnly",
        "required",
        "title",
        "type",
        "uniqueItems",
        "writeOnly",
    }
)
_SCHEMA_ALLOWED_KEYWORDS = frozenset(
    _SCHEMA_MAPPING_KEYWORDS
    | _SCHEMA_PATTERN_MAPPING_KEYWORDS
    | _SCHEMA_SINGLE_KEYWORDS
    | _SCHEMA_SEQUENCE_KEYWORDS
    | _SCHEMA_SCALAR_KEYWORDS
)
_SUPPORTED_SCHEMA_FORMATS = frozenset(FormatChecker.checkers)
_RESERVED_TOOL_IDENTITIES = frozenset(
    {
        "initialize",
        "notifications_initialized",
        "ping",
        "prompts_get",
        "prompts_list",
        "resources_list",
        "resources_read",
        "tools_call",
        "tools_list",
    }
)


class McpGuardedHostError(RuntimeError):
    """A content-free failure safe to surface through local HTTP."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class McpRemoteHeader(StrictModel):
    """One transient header.  Its value must never be serialized publicly."""

    name: str = Field(min_length=1, max_length=128)
    value: SecretStr = Field(min_length=1, max_length=MAX_MCP_REMOTE_HEADER_VALUE_BYTES, repr=False)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if (
            normalized != value
            or _HEADER_NAME.fullmatch(value) is None
            or value.casefold() in _RESERVED_HEADERS
        ):
            raise ValueError("reserved or invalid MCP transport header")
        return value

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if (
            not raw
            or any(character in raw for character in ("\x00", "\r", "\n"))
            or len(raw.encode("utf-8")) > MAX_MCP_REMOTE_HEADER_VALUE_BYTES
        ):
            raise ValueError("invalid MCP transport header value")
        return value


class McpRemoteConnectionSpec(StrictModel):
    """Transient, exact Registry connection material for one reviewed plan."""

    management_id: str = Field(pattern=_ID_PATTERN)
    catalog_id: str = Field(pattern=_ID_PATTERN)
    option_id: str = Field(pattern=_ID_PATTERN)
    plan_revision: str = Field(pattern=_DIGEST_PATTERN)
    transport: Literal["streamable-http", "sse"]
    endpoint_host: str = Field(min_length=1, max_length=255)
    endpoint: SecretStr = Field(min_length=1, max_length=MAX_MCP_ENDPOINT_CHARS, repr=False)
    headers: tuple[McpRemoteHeader, ...] = Field(max_length=MAX_MCP_REMOTE_HEADERS)

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint_shape(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if (
            len(raw) > MAX_MCP_ENDPOINT_CHARS
            or any(character in raw for character in ("\x00", "\r", "\n"))
            or "{" in raw
            or "}" in raw
        ):
            raise ValueError("invalid MCP endpoint")
        try:
            parsed = urlsplit(raw)
            port = parsed.port
        except ValueError as error:
            raise ValueError("invalid MCP endpoint") from error
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or bool(parsed.fragment)
            or (port is not None and not 1 <= port <= 65_535)
        ):
            raise ValueError("invalid MCP endpoint")
        return value

    @model_validator(mode="after")
    def coherent_origin_and_headers(self) -> "McpRemoteConnectionSpec":
        parsed = urlsplit(self.endpoint.get_secret_value())
        host = (parsed.hostname or "").casefold()
        try:
            if isinstance(ipaddress.ip_address(host), ipaddress.IPv6Address):
                host = f"[{host}]"
        except ValueError:
            pass
        if parsed.port is not None and parsed.port != 443:
            host = f"{host}:{parsed.port}"
        if host != self.endpoint_host.casefold():
            raise ValueError("MCP endpoint origin does not match reviewed host")
        names = [item.name.casefold() for item in self.headers]
        if len(names) != len(set(names)):
            raise ValueError("duplicate MCP transport headers")
        return self


@dataclass(frozen=True, slots=True, repr=False)
class McpStdioConnectionSpec:
    """Internal exact executable identity populated only after Store-05 install."""

    management_id: str
    executable: str
    arguments: tuple[str, ...]
    environment: Mapping[str, str]
    working_directory: str | None = None


@dataclass(frozen=True, slots=True, repr=False)
class McpDiscoveredTool:
    """Transient server data; normalized before any local retention."""

    name: str
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any] | None = None
    title: str | None = None
    description: str | None = None


class McpReviewedToolContract(StrictModel):
    """Bounded local-only contract captured by one closed compatibility probe."""

    tool_id: str = Field(pattern=_ID_PATTERN)
    name: str = Field(min_length=1, max_length=MAX_MCP_TOOL_NAME_CHARS)
    title: str | None = Field(default=None, min_length=1, max_length=MAX_MCP_TOOL_TITLE_CHARS)
    description: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_MCP_TOOL_DESCRIPTION_CHARS,
    )
    model_alias: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    input_schema: dict[str, Any]
    input_schema_digest: str = Field(pattern=_DIGEST_PATTERN)
    model_input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None
    output_schema_digest: str | None = Field(default=None, pattern=_DIGEST_PATTERN)
    contract_digest: str = Field(pattern=_DIGEST_PATTERN)

    @model_validator(mode="after")
    def coherent_contract(self) -> "McpReviewedToolContract":
        if (self.output_schema is None) != (self.output_schema_digest is None):
            raise ValueError("reviewed MCP output schema evidence is incoherent")
        return self


@dataclass(frozen=True, slots=True, repr=False)
class McpHostProbeObservation:
    transport: Literal["stdio", "streamable-http", "sse"]
    protocol_version: str
    tools: tuple[McpDiscoveredTool, ...]
    elapsed_ms: int
    process_started: bool
    process_tree_cleanup_verified: bool


class McpHostProbeResult(StrictModel):
    """Compatibility result plus local-only contracts for the management store."""

    contract_version: Literal["mcp-guarded-host.v1"] = MCP_GUARDED_HOST_CONTRACT_VERSION
    outcome: Literal["compatible"] = "compatible"
    transport: Literal["stdio", "streamable-http", "sse"]
    protocol_version: str = Field(pattern=_PROTOCOL_PATTERN)
    tool_count: int = Field(strict=True, ge=0, le=MAX_MCP_PROBE_TOOLS)
    schema_digest: str = Field(pattern=_DIGEST_PATTERN)
    elapsed_ms: int = Field(strict=True, ge=0, le=120_000)
    connection_state: Literal["closed_after_probe"] = "closed_after_probe"
    process_started: bool
    process_tree_cleanup: Literal["verified", "not_applicable"]
    tool_names_persisted: bool = False
    tool_schemas_persisted: bool = False
    tool_results_requested: Literal[False] = False
    tool_authority_granted: Literal[False] = False
    reviewed_tools: tuple[McpReviewedToolContract, ...] = Field(
        default=(),
        max_length=MAX_MCP_PROBE_TOOLS,
        repr=False,
        exclude=True,
    )

    @model_validator(mode="after")
    def coherent_cleanup(self) -> "McpHostProbeResult":
        expected = "verified" if self.process_started else "not_applicable"
        if self.process_tree_cleanup != expected:
            raise ValueError("MCP process cleanup truth is incoherent")
        if self.tool_names_persisted != self.tool_schemas_persisted:
            raise ValueError("MCP tool-retention truth is incoherent")
        if self.tool_names_persisted:
            if len(self.reviewed_tools) != self.tool_count:
                raise ValueError("MCP reviewed-tool count is incoherent")
        elif self.reviewed_tools:
            raise ValueError("MCP reviewed tools cannot exist without retention truth")
        return self


class McpHostProbeClient(Protocol):
    def probe(
        self,
        connection: McpRemoteConnectionSpec | McpStdioConnectionSpec,
        *,
        deadline_seconds: float,
    ) -> McpHostProbeObservation: ...


def _character_is_escaped(value: str, index: int) -> bool:
    slashes = 0
    cursor = index - 1
    while cursor >= 0 and value[cursor] == "\\":
        slashes += 1
        cursor -= 1
    return bool(slashes % 2)


def _validate_schema_pattern(value: Any) -> None:
    """Admit a deliberately small, bounded, non-nested regex subset."""

    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_MCP_SCHEMA_PATTERN_CHARS
        or "\x00" in value
        or re.search(r"\\(?:[1-9]|g|k)", value)
    ):
        raise McpGuardedHostError("mcp_host_tool_schema_pattern_unsafe")
    try:
        re.compile(value)
    except re.error:
        raise McpGuardedHostError("mcp_host_tool_schema_pattern_unsafe") from None

    in_class = False
    quantifiers = 0
    unbounded = 0
    expansion = 1
    index = 0
    while index < len(value):
        character = value[index]
        if character == "\\":
            index += 2
            continue
        if character == "[" and not in_class:
            in_class = True
            index += 1
            continue
        if character == "]" and in_class:
            in_class = False
            index += 1
            continue
        if in_class:
            index += 1
            continue
        if character in {"(", ")", "|"}:
            raise McpGuardedHostError("mcp_host_tool_schema_pattern_unsafe")
        if character in {"*", "+", "?"}:
            quantifiers += 1
            if character in {"*", "+"}:
                unbounded += 1
            else:
                expansion *= 2
        elif character == "{":
            match = re.match(r"\{([0-9]{1,3})(?:,([0-9]{0,3}))?\}", value[index:])
            if match is None:
                raise McpGuardedHostError("mcp_host_tool_schema_pattern_unsafe")
            minimum = int(match.group(1))
            upper_text = match.group(2)
            if upper_text is None:
                upper = minimum
            elif upper_text == "":
                upper = minimum
                unbounded += 1
            else:
                upper = int(upper_text)
            if minimum > upper or upper > 256:
                raise McpGuardedHostError("mcp_host_tool_schema_pattern_unsafe")
            quantifiers += 1
            expansion *= max(1, upper - minimum + 1)
            index += len(match.group(0)) - 1
        if quantifiers > 8 or unbounded > 1 or expansion > 4_096:
            raise McpGuardedHostError("mcp_host_tool_schema_pattern_unsafe")
        index += 1
    if in_class:
        raise McpGuardedHostError("mcp_host_tool_schema_pattern_unsafe")
    if unbounded and not (
        value.startswith("^")
        and value.endswith("$")
        and not _character_is_escaped(value, len(value) - 1)
    ):
        raise McpGuardedHostError("mcp_host_tool_schema_pattern_unsafe")


def _local_json_pointer_target(schema: Mapping[str, Any], reference: str) -> Any:
    if reference == "#":
        return schema
    if not reference.startswith("#/") or "%" in reference:
        raise McpGuardedHostError("mcp_host_tool_schema_external_ref")
    current: Any = schema
    for raw_token in reference[2:].split("/"):
        if re.search(r"~(?![01])", raw_token):
            raise McpGuardedHostError("mcp_host_tool_schema_ref_invalid")
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                raise McpGuardedHostError("mcp_host_tool_schema_ref_invalid")
            current = current[token]
        elif isinstance(current, Sequence) and not isinstance(
            current, (str, bytes, bytearray)
        ):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                raise McpGuardedHostError("mcp_host_tool_schema_ref_invalid")
            position = int(token)
            if position >= len(current):
                raise McpGuardedHostError("mcp_host_tool_schema_ref_invalid")
            current = current[position]
        else:
            raise McpGuardedHostError("mcp_host_tool_schema_ref_invalid")
    if not isinstance(current, (Mapping, bool)):
        raise McpGuardedHostError("mcp_host_tool_schema_ref_invalid")
    return current


def _assert_acyclic_schema_graph(adjacency: Mapping[int, set[int]]) -> None:
    colors: dict[int, int] = {}
    for start in adjacency:
        if colors.get(start, 0):
            continue
        colors[start] = 1
        stack: list[tuple[int, Any]] = [(start, iter(adjacency.get(start, ())))]
        while stack:
            node, edges = stack[-1]
            try:
                child = next(edges)
            except StopIteration:
                colors[node] = 2
                stack.pop()
                continue
            state = colors.get(child, 0)
            if state == 1:
                raise McpGuardedHostError("mcp_host_tool_schema_recursive")
            if state == 0:
                colors[child] = 1
                stack.append((child, iter(adjacency.get(child, ()))))


def _schema_stats(schema: Mapping[str, Any]) -> tuple[int, int]:
    """Validate one finite, acyclic JSON Schema subset without recursion."""

    nodes = 0
    branches = 0
    enum_items = 0
    properties = 0
    adjacency: dict[int, set[int]] = {}
    references: list[tuple[int, str]] = []
    visited: set[tuple[int, str]] = set()
    stack: list[tuple[Any, int, str]] = [(schema, 1, "schema")]
    while stack:
        value, depth, context = stack.pop()
        is_container = isinstance(value, Mapping) or (
            isinstance(value, Sequence)
            and not isinstance(value, (str, bytes, bytearray))
        )
        if is_container:
            marker = (id(value), context)
            if marker in visited:
                continue
            visited.add(marker)
            adjacency.setdefault(id(value), set())
            children = value.values() if isinstance(value, Mapping) else value
            for child in children:
                if isinstance(child, Mapping) or (
                    isinstance(child, Sequence)
                    and not isinstance(child, (str, bytes, bytearray))
                ):
                    adjacency[id(value)].add(id(child))

        nodes += 1
        if nodes > MAX_MCP_SCHEMA_NODES or depth > MAX_MCP_SCHEMA_DEPTH:
            raise McpGuardedHostError("mcp_host_tool_schema_too_complex")

        if context == "schema":
            if isinstance(value, bool):
                continue
            if not isinstance(value, Mapping):
                raise McpGuardedHostError("mcp_host_tool_schema_invalid")
            if len(value) > MAX_MCP_SCHEMA_COLLECTION_ITEMS:
                raise McpGuardedHostError("mcp_host_tool_schema_too_complex")
            for key, child in value.items():
                if (
                    not isinstance(key, str)
                    or len(key) > 256
                    or "\x00" in key
                ):
                    raise McpGuardedHostError("mcp_host_tool_schema_invalid")
                if key not in _SCHEMA_ALLOWED_KEYWORDS and not key.startswith("x-"):
                    raise McpGuardedHostError(
                        "mcp_host_tool_schema_keyword_unsupported"
                    )
                if key == "$schema" and child not in _SUPPORTED_JSON_SCHEMA_DIALECTS:
                    raise McpGuardedHostError(
                        "mcp_host_tool_schema_dialect_unsupported"
                    )
                if key == "$ref":
                    if (
                        not isinstance(child, str)
                        or len(child) > 1_024
                        or not (child == "#" or child.startswith("#/"))
                    ):
                        raise McpGuardedHostError(
                            "mcp_host_tool_schema_external_ref"
                        )
                    references.append((id(value), child))
                if key == "pattern":
                    _validate_schema_pattern(child)
                if key == "format" and (
                    not isinstance(child, str)
                    or child not in _SUPPORTED_SCHEMA_FORMATS
                ):
                    raise McpGuardedHostError(
                        "mcp_host_tool_schema_format_unsupported"
                    )
                if key == "enum":
                    if not isinstance(child, Sequence) or isinstance(
                        child, (str, bytes, bytearray)
                    ):
                        raise McpGuardedHostError("mcp_host_tool_schema_invalid")
                    enum_items += len(child)
                    if enum_items > MAX_MCP_SCHEMA_ENUM_ITEMS:
                        raise McpGuardedHostError(
                            "mcp_host_tool_schema_too_complex"
                        )

                child_context = "json"
                if key in _SCHEMA_MAPPING_KEYWORDS:
                    child_context = "schema_map"
                elif key in _SCHEMA_PATTERN_MAPPING_KEYWORDS:
                    child_context = "pattern_schema_map"
                elif key in _SCHEMA_SINGLE_KEYWORDS:
                    child_context = "schema"
                elif key in _SCHEMA_SEQUENCE_KEYWORDS:
                    child_context = "schema_sequence"
                    if not isinstance(child, Sequence) or isinstance(
                        child, (str, bytes, bytearray)
                    ):
                        raise McpGuardedHostError("mcp_host_tool_schema_invalid")
                    branches += len(child)
                    if branches > MAX_MCP_SCHEMA_BRANCHES:
                        raise McpGuardedHostError(
                            "mcp_host_tool_schema_too_complex"
                        )
                stack.append((child, depth + 1, child_context))
        elif context in {"schema_map", "pattern_schema_map"}:
            if not isinstance(value, Mapping):
                raise McpGuardedHostError("mcp_host_tool_schema_invalid")
            properties += len(value)
            if (
                len(value) > MAX_MCP_SCHEMA_PROPERTIES
                or properties > MAX_MCP_SCHEMA_PROPERTIES
            ):
                raise McpGuardedHostError("mcp_host_tool_schema_too_complex")
            for key, child in value.items():
                if (
                    not isinstance(key, str)
                    or len(key) > 256
                    or "\x00" in key
                    or not isinstance(child, (Mapping, bool))
                ):
                    raise McpGuardedHostError("mcp_host_tool_schema_invalid")
                if context == "pattern_schema_map":
                    _validate_schema_pattern(key)
                stack.append((child, depth + 1, "schema"))
        elif context == "schema_sequence":
            if not isinstance(value, Sequence) or isinstance(
                value, (str, bytes, bytearray)
            ):
                raise McpGuardedHostError("mcp_host_tool_schema_invalid")
            if len(value) > MAX_MCP_SCHEMA_BRANCHES:
                raise McpGuardedHostError("mcp_host_tool_schema_too_complex")
            for child in value:
                if not isinstance(child, (Mapping, bool)):
                    raise McpGuardedHostError("mcp_host_tool_schema_invalid")
                stack.append((child, depth + 1, "schema"))
        elif isinstance(value, Mapping):
            if len(value) > MAX_MCP_SCHEMA_COLLECTION_ITEMS:
                raise McpGuardedHostError("mcp_host_tool_schema_too_complex")
            for key, child in value.items():
                if (
                    not isinstance(key, str)
                    or len(key) > 256
                    or "\x00" in key
                ):
                    raise McpGuardedHostError("mcp_host_tool_schema_invalid")
                stack.append((child, depth + 1, "json"))
        elif isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            if len(value) > MAX_MCP_SCHEMA_COLLECTION_ITEMS:
                raise McpGuardedHostError("mcp_host_tool_schema_too_complex")
            stack.extend((child, depth + 1, "json") for child in value)
        elif isinstance(value, str):
            if len(value) > MAX_MCP_SCHEMA_STRING_CHARS or "\x00" in value:
                raise McpGuardedHostError("mcp_host_tool_schema_too_large")
        elif isinstance(value, float) and not math.isfinite(value):
            raise McpGuardedHostError("mcp_host_tool_schema_invalid")
        elif value is not None and not isinstance(value, (str, int, float, bool)):
            raise McpGuardedHostError("mcp_host_tool_schema_invalid")

    for source, reference in references:
        target = _local_json_pointer_target(schema, reference)
        if isinstance(target, Mapping):
            adjacency.setdefault(source, set()).add(id(target))
    _assert_acyclic_schema_graph(adjacency)

    try:
        encoded = json.dumps(
            schema,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise McpGuardedHostError("mcp_host_tool_schema_invalid") from None
    if len(encoded) > MAX_MCP_SCHEMA_BYTES:
        raise McpGuardedHostError("mcp_host_tool_schema_too_large")
    return len(encoded), nodes


def mcp_json_schema_validator(schema: Mapping[str, Any]) -> Any:
    """Return a checked local-only validator for the accepted bounded subset."""

    _schema_stats(schema)
    try:
        detached = json.loads(_schema_bytes(schema))
        validator_type = validator_for(detached)
        validator_type.check_schema(detached)
        return validator_type(detached, format_checker=FormatChecker())
    except (JsonSchemaSchemaError, TypeError, ValueError, RecursionError):
        raise McpGuardedHostError("mcp_host_tool_schema_invalid") from None


def _normalized_tool_text(
    value: str | None,
    *,
    maximum: int,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise McpGuardedHostError("mcp_host_tool_metadata_invalid")
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return None
    if len(normalized) > maximum or any(
        (ord(character) < 32 and character not in {"\n", "\t"})
        or ord(character) == 127
        for character in normalized
    ):
        raise McpGuardedHostError("mcp_host_tool_metadata_invalid")
    return normalized


def _schema_bytes(schema: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            schema,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, OverflowError):
        raise McpGuardedHostError("mcp_host_tool_schema_invalid") from None


def project_mcp_tool_schema_for_model(
    schema: Mapping[str, Any],
) -> dict[str, Any]:
    """Strip prompt-like annotations while preserving structural guidance."""

    scalar_keys = {
        "$ref",
        "$schema",
        "type",
        "enum",
        "const",
        "required",
        "dependentRequired",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minItems",
        "maxItems",
        "minContains",
        "maxContains",
        "uniqueItems",
        "minProperties",
        "maxProperties",
    }
    mapping_keys = {
        "properties",
        "patternProperties",
        "$defs",
        "definitions",
        "dependentSchemas",
    }
    schema_keys = {
        "items",
        "additionalItems",
        "additionalProperties",
        "unevaluatedProperties",
        "unevaluatedItems",
        "contains",
        "contentSchema",
        "propertyNames",
        "not",
        "if",
        "then",
        "else",
    }
    sequence_keys = {"allOf", "anyOf", "oneOf", "prefixItems"}

    def project(value: Mapping[str, Any], depth: int = 0) -> dict[str, Any]:
        if depth > MAX_MCP_SCHEMA_DEPTH:
            raise McpGuardedHostError("mcp_host_tool_schema_too_complex")
        result: dict[str, Any] = {}
        for key, child in value.items():
            if key in scalar_keys:
                result[key] = child
            elif key in mapping_keys and isinstance(child, Mapping):
                projected_mapping: dict[str, Any] = {}
                for name, item in child.items():
                    if isinstance(item, Mapping):
                        projected_mapping[str(name)] = project(item, depth + 1)
                    elif isinstance(item, bool):
                        projected_mapping[str(name)] = item
                result[key] = projected_mapping
            elif key in schema_keys:
                if isinstance(child, Mapping):
                    result[key] = project(child, depth + 1)
                elif isinstance(child, bool):
                    result[key] = child
            elif key in sequence_keys and isinstance(child, Sequence) and not isinstance(
                child, (str, bytes, bytearray)
            ):
                projected_items: list[Any] = []
                for item in child:
                    if isinstance(item, Mapping):
                        projected_items.append(project(item, depth + 1))
                    elif isinstance(item, bool):
                        projected_items.append(item)
                result[key] = projected_items
        return result

    projected = project(schema)
    if not projected:
        projected = {"type": "object"}
    _schema_stats(projected)
    return projected


def _model_alias(management_id: str, name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "tool"
    slug = slug[:16]
    name_digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return f"mcp_{management_id}_{slug}_{name_digest}"


def _canonical_tool_identity(name: str) -> str:
    return re.sub(r"[_.:/-]+", "_", name.casefold()).strip("_")


def review_mcp_tool_contracts(
    management_id: str,
    tools: Sequence[McpDiscoveredTool],
) -> tuple[tuple[McpReviewedToolContract, ...], str]:
    """Normalize one complete listing into exact review and drift evidence.

    This is the single public application-layer reviewer used by closed probes
    and persistent health checks. It performs no transport operation and grants
    no tool authority.
    """

    if re.fullmatch(_ID_PATTERN, management_id) is None:
        raise McpGuardedHostError("mcp_host_management_identity_invalid")
    if len(tools) > MAX_MCP_PROBE_TOOLS:
        raise McpGuardedHostError("mcp_host_tool_count_exceeded")
    seen: set[str] = set()
    seen_canonical: set[str] = set()
    canonical: list[dict[str, Any]] = []
    total_bytes = 0
    metadata_bytes = 0
    for tool in tools:
        if _TOOL_NAME.fullmatch(tool.name) is None or tool.name in seen:
            raise McpGuardedHostError("mcp_host_tool_identity_invalid")
        seen.add(tool.name)
        identity = _canonical_tool_identity(tool.name)
        if not identity or identity in _RESERVED_TOOL_IDENTITIES:
            raise McpGuardedHostError("mcp_host_tool_identity_invalid")
        if identity in seen_canonical:
            raise McpGuardedHostError("mcp_host_tool_identity_conflict")
        seen_canonical.add(identity)
        if not isinstance(tool.input_schema, Mapping):
            raise McpGuardedHostError("mcp_host_tool_schema_invalid")
        root_type = tool.input_schema.get("type")
        if root_type not in (None, "object"):
            raise McpGuardedHostError("mcp_host_tool_schema_invalid")
        input_bytes, _ = _schema_stats(tool.input_schema)
        mcp_json_schema_validator(tool.input_schema)
        total_bytes += input_bytes
        if tool.output_schema is not None:
            if not isinstance(tool.output_schema, Mapping):
                raise McpGuardedHostError("mcp_host_tool_schema_invalid")
            output_bytes, _ = _schema_stats(tool.output_schema)
            mcp_json_schema_validator(tool.output_schema)
            total_bytes += output_bytes
        if total_bytes > MAX_MCP_SCHEMA_TOTAL_BYTES:
            raise McpGuardedHostError("mcp_host_tool_schema_total_exceeded")
        title = _normalized_tool_text(
            tool.title,
            maximum=MAX_MCP_TOOL_TITLE_CHARS,
        )
        description = _normalized_tool_text(
            tool.description,
            maximum=MAX_MCP_TOOL_DESCRIPTION_CHARS,
        )
        metadata_bytes += len(
            json.dumps(
                {
                    "name": tool.name,
                    "title": title,
                    "description": description,
                },
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        )
        if metadata_bytes > MAX_MCP_TOOL_METADATA_TOTAL_BYTES:
            raise McpGuardedHostError("mcp_host_tool_metadata_total_exceeded")
        canonical.append({
            "name": tool.name,
            "title": title,
            "description": description,
            "input": dict(tool.input_schema),
            "output": None if tool.output_schema is None else dict(tool.output_schema),
        })
    canonical.sort(key=lambda item: item["name"])
    try:
        material = json.dumps(
            canonical,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, OverflowError):
        raise McpGuardedHostError("mcp_host_tool_schema_invalid") from None
    reviewed: list[McpReviewedToolContract] = []
    for item in canonical:
        input_schema = item["input"]
        output_schema = item["output"]
        input_digest = hashlib.sha256(_schema_bytes(input_schema)).hexdigest()
        output_digest = (
            None
            if output_schema is None
            else hashlib.sha256(_schema_bytes(output_schema)).hexdigest()
        )
        contract_material = json.dumps(
            item,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
        contract_digest = hashlib.sha256(contract_material).hexdigest()
        reviewed.append(
            McpReviewedToolContract(
                tool_id=contract_digest[:32],
                name=item["name"],
                title=item["title"],
                description=item["description"],
                model_alias=_model_alias(management_id, item["name"]),
                input_schema=input_schema,
                input_schema_digest=input_digest,
                model_input_schema=project_mcp_tool_schema_for_model(input_schema),
                output_schema=output_schema,
                output_schema_digest=output_digest,
                contract_digest=contract_digest,
            )
        )
    aliases = [item.model_alias for item in reviewed]
    if len(aliases) != len(set(aliases)):
        raise McpGuardedHostError("mcp_host_tool_alias_collision")
    return tuple(reviewed), hashlib.sha256(material).hexdigest()


def _tool_contract_digest(tools: Sequence[McpDiscoveredTool]) -> str:
    """Compatibility helper retained for tests and older internal callers."""

    return review_mcp_tool_contracts("0" * 32, tools)[1]


class McpGuardedHost:
    """Validate one observation and return bounded, local-reviewable contracts."""

    def __init__(self, client: McpHostProbeClient) -> None:
        self._client = client

    def probe(
        self,
        connection: McpRemoteConnectionSpec | McpStdioConnectionSpec,
        *,
        deadline_seconds: float = 12.0,
    ) -> McpHostProbeResult:
        if (
            isinstance(deadline_seconds, bool)
            or not isinstance(deadline_seconds, (int, float))
            or not math.isfinite(deadline_seconds)
            or not 0.1 <= deadline_seconds <= MAX_MCP_PROBE_SECONDS
        ):
            raise McpGuardedHostError("mcp_host_deadline_invalid")
        try:
            observed = self._client.probe(
                connection,
                deadline_seconds=float(deadline_seconds),
            )
        except McpGuardedHostError:
            raise
        except Exception:
            raise McpGuardedHostError("mcp_host_probe_failed") from None
        expected_transport = (
            connection.transport
            if isinstance(connection, McpRemoteConnectionSpec)
            else "stdio"
        )
        if observed.transport != expected_transport:
            raise McpGuardedHostError("mcp_host_transport_mismatch")
        if re.fullmatch(_PROTOCOL_PATTERN, observed.protocol_version) is None:
            raise McpGuardedHostError("mcp_host_protocol_unsupported")
        if (
            isinstance(observed.elapsed_ms, bool)
            or not 0 <= observed.elapsed_ms <= 120_000
        ):
            raise McpGuardedHostError("mcp_host_probe_receipt_invalid")
        if observed.process_started != isinstance(connection, McpStdioConnectionSpec):
            raise McpGuardedHostError("mcp_host_process_truth_invalid")
        if observed.process_started and not observed.process_tree_cleanup_verified:
            raise McpGuardedHostError("mcp_host_cleanup_unconfirmed")
        reviewed_tools, schema_digest = review_mcp_tool_contracts(
            connection.management_id,
            observed.tools,
        )
        return McpHostProbeResult(
            transport=observed.transport,
            protocol_version=observed.protocol_version,
            tool_count=len(observed.tools),
            schema_digest=schema_digest,
            elapsed_ms=observed.elapsed_ms,
            process_started=observed.process_started,
            process_tree_cleanup=(
                "verified" if observed.process_started else "not_applicable"
            ),
            tool_names_persisted=True,
            tool_schemas_persisted=True,
            reviewed_tools=reviewed_tools,
        )


__all__ = (
    "MAX_MCP_ENDPOINT_CHARS",
    "MAX_MCP_PROBE_SECONDS",
    "MAX_MCP_PROBE_TOOLS",
    "MAX_MCP_REMOTE_HEADERS",
    "MAX_MCP_REMOTE_HEADER_VALUE_BYTES",
    "MAX_MCP_SCHEMA_BYTES",
    "MAX_MCP_SCHEMA_BRANCHES",
    "MAX_MCP_SCHEMA_COLLECTION_ITEMS",
    "MAX_MCP_SCHEMA_DEPTH",
    "MAX_MCP_SCHEMA_ENUM_ITEMS",
    "MAX_MCP_SCHEMA_NODES",
    "MAX_MCP_SCHEMA_PATTERN_CHARS",
    "MAX_MCP_SCHEMA_PROPERTIES",
    "MAX_MCP_SCHEMA_STRING_CHARS",
    "MAX_MCP_SCHEMA_TOTAL_BYTES",
    "MAX_MCP_TOOL_NAME_CHARS",
    "MAX_MCP_TOOL_TITLE_CHARS",
    "MAX_MCP_TOOL_DESCRIPTION_CHARS",
    "MAX_MCP_TOOL_METADATA_TOTAL_BYTES",
    "MAX_MCP_TOOL_PAGES",
    "MCP_GUARDED_HOST_CONTRACT_VERSION",
    "McpDiscoveredTool",
    "McpGuardedHost",
    "McpGuardedHostError",
    "McpHostProbeClient",
    "McpHostProbeObservation",
    "McpHostProbeResult",
    "McpRemoteConnectionSpec",
    "McpRemoteHeader",
    "McpReviewedToolContract",
    "McpStdioConnectionSpec",
    "mcp_json_schema_validator",
    "project_mcp_tool_schema_for_model",
    "review_mcp_tool_contracts",
)
