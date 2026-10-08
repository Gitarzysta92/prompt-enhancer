"""Content-free compatibility preflight for the installed Codex App Server.

The probe invokes only the documented JSON-schema generator. It uses an
isolated empty ``CODEX_HOME``, reads a small fixed schema slice, and returns a
closed status plus content-free structural tokens. It never starts App Server,
lists threads, reads sessions, hashes provider responses, downloads adapters,
or changes adapter selection.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from typing import Any, Protocol, runtime_checkable

from ....application.owned_process import (
    OwnedProcessResult,
    OwnedProcessRunError,
    run_owned_process,
)
from ....application.providers import (
    CapabilityKey,
    CapabilityObservation,
    CapabilityState,
    CompatibilityReason,
    CompatibilityReasonCode,
    CompatibilityState,
    DecoderDescriptor,
    ExtractionCompleteness,
    ExtractionCompletenessState,
    ProviderCompatibilityReport,
    ProviderIdentity,
    ProviderSurface,
    SchemaArtifactKind,
    SchemaArtifactProvenance,
)
from .content_contracts import (
    ADMITTED_THREAD_ITEM_TYPES,
    DISCARDED_THREAD_ITEM_TYPES,
    DISCARDED_USER_INPUT_TYPES,
    TEXT_CONTENT_ADAPTER_VERSION,
    TEXT_CONTENT_SCHEMA_VERSION,
)
from .transports.stdio_jsonl import CODEX_APP_SERVER_ARGV


CONSUMED_SCHEMA_MANIFEST_VERSION = "codex-consumed-schema-v1"
DEFAULT_SCHEMA_PROBE_TIMEOUT_SECONDS = 10.0
MAX_GENERATED_SCHEMA_FILES = 1_024
MAX_GENERATED_SCHEMA_DIRECTORIES = 64
MAX_GENERATED_SCHEMA_BYTES = 64 * 1024 * 1024
MAX_CONSUMED_SCHEMA_FILE_BYTES = 4 * 1024 * 1024
MAX_PROVIDER_VERSION_BYTES = 256
MAX_SCHEMA_PROBE_PROCESSES = 8

_SCHEMA_FILES = (
    "v1/InitializeParams.json",
    "v1/InitializeResponse.json",
    "v2/ThreadListParams.json",
    "v2/ThreadListResponse.json",
    "v2/ThreadReadParams.json",
    "v2/ThreadReadResponse.json",
)
_SAFE_STRUCTURAL_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{0,63}$")
_SAFE_PROVIDER_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+:/-]{0,127}$")
_SAFE_COMMAND_PATH = re.compile(r'^[^\x00\r\n&|<>^%!\"]+$')
_SUPPORTED_AGENT_PHASES = frozenset({"commentary", "final_answer"})
_TEXT_USER_INPUT_TYPE = "text"
_TESTED_0_144_5_THREAD_ITEM_TYPES = tuple(
    sorted(
        {
            "userMessage",
            "hookPrompt",
            "agentMessage",
            "plan",
            "reasoning",
            "commandExecution",
            "fileChange",
            "mcpToolCall",
            "dynamicToolCall",
            "collabAgentToolCall",
            "subAgentActivity",
            "webSearch",
            "imageView",
            "sleep",
            "imageGeneration",
            "enteredReviewMode",
            "exitedReviewMode",
            "contextCompaction",
        }
    )
)
_TESTED_0_144_5_USER_INPUT_TYPES = tuple(
    sorted({"text", "image", "localImage", "skill", "mention"})
)
_TESTED_0_144_5_AGENT_PHASES = tuple(sorted(_SUPPORTED_AGENT_PHASES))
_CODEX_VERSION = re.compile(
    rb"codex-cli (?P<version>[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?)\r?\n?"
)


CODEX_TEXT_WINDOW_DECODER_DESCRIPTOR = DecoderDescriptor(
    provider=ProviderIdentity(key="codex"),
    surface=ProviderSurface.TEXT_WINDOW,
    adapter_version=TEXT_CONTENT_ADAPTER_VERSION,
    decoder_key="codex.app-server.text-window",
    decoder_version="6",
    wire_schema_family="codex.app-server.v2",
    canonical_schema_version=TEXT_CONTENT_SCHEMA_VERSION,
    schema_artifact=SchemaArtifactProvenance(
        artifact_key="codex.app-server.generated.consumed",
        artifact_version=CONSUMED_SCHEMA_MANIFEST_VERSION,
        kind=SchemaArtifactKind.GENERATED,
        checksum_sha256=None,
    ),
    capabilities=(
        CapabilityKey.USER_MESSAGES,
        CapabilityKey.AGENT_MESSAGES,
        CapabilityKey.PLAN_MESSAGES,
    ),
    tested_provider_versions=("0.144.5",),
)


class CodexSchemaPreflightStatus(StrEnum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    RESOURCE_LIMIT = "resource_limit"


@dataclass(frozen=True, slots=True)
class CodexConsumedSchemaManifest:
    """Safe semantic projection of the generated schema slice."""

    manifest_version: str
    thread_item_types: tuple[str, ...]
    user_input_types: tuple[str, ...]
    agent_message_phases: tuple[str, ...]
    unclassified_thread_item_types: tuple[str, ...]
    unclassified_user_input_types: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.manifest_version != CONSUMED_SCHEMA_MANIFEST_VERSION:
            raise ValueError("consumed schema manifest version is unsupported")
        for values in (
            self.thread_item_types,
            self.user_input_types,
            self.agent_message_phases,
            self.unclassified_thread_item_types,
            self.unclassified_user_input_types,
        ):
            if (
                values != tuple(sorted(set(values)))
                or any(
                    _SAFE_STRUCTURAL_TOKEN.fullmatch(value) is None
                    for value in values
                )
            ):
                raise ValueError("schema manifest tokens must be safe and canonical")
        if not set(self.unclassified_thread_item_types).issubset(
            self.thread_item_types
        ) or not set(self.unclassified_user_input_types).issubset(
            self.user_input_types
        ):
            raise ValueError("unclassified schema tokens must belong to their union")


@dataclass(frozen=True, slots=True)
class CodexSchemaPreflightResult:
    """A bounded result suitable for local status reporting."""

    status: CodexSchemaPreflightStatus
    provider_version: str = "unknown"
    manifest_version: str = CONSUMED_SCHEMA_MANIFEST_VERSION
    manifest: CodexConsumedSchemaManifest | None = None

    def __post_init__(self) -> None:
        if _SAFE_PROVIDER_VERSION.fullmatch(self.provider_version) is None:
            raise ValueError("provider version must be a safe structural token")
        if self.manifest_version != CONSUMED_SCHEMA_MANIFEST_VERSION:
            raise ValueError("schema preflight manifest version is unsupported")
        if self.status is CodexSchemaPreflightStatus.COMPATIBLE:
            if (
                self.manifest is None
                or self.manifest.manifest_version != self.manifest_version
            ):
                raise ValueError("compatible schema preflight requires its manifest")
        elif self.manifest is not None:
            raise ValueError("failed schema preflight cannot expose a manifest")

    @property
    def compatible(self) -> bool:
        return self.status is CodexSchemaPreflightStatus.COMPATIBLE


@runtime_checkable
class CodexSchemaProbe(Protocol):
    """Content-free installed-schema probe port."""

    def probe(self) -> CodexSchemaPreflightResult: ...


class _SchemaInspectionError(RuntimeError):
    def __init__(self, status: CodexSchemaPreflightStatus) -> None:
        self.status = status
        super().__init__(status.value)


class ProcessResult(Protocol):
    returncode: int
    stdout: bytes


ProcessRunner = Callable[..., ProcessResult]
Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise _SchemaInspectionError(CodexSchemaPreflightStatus.INCOMPATIBLE)
    return value


def _sequence(value: object) -> tuple[Any, ...]:
    if not isinstance(value, list):
        raise _SchemaInspectionError(CodexSchemaPreflightStatus.INCOMPATIBLE)
    return tuple(value)


def _required(schema: Mapping[str, Any], *names: str) -> None:
    required = _sequence(schema.get("required", []))
    if not set(names).issubset(required):
        raise _SchemaInspectionError(CodexSchemaPreflightStatus.INCOMPATIBLE)


def _property(schema: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    properties = _mapping(schema.get("properties"))
    if name not in properties:
        raise _SchemaInspectionError(CodexSchemaPreflightStatus.INCOMPATIBLE)
    return _mapping(properties[name])


def _allows_type(schema: Mapping[str, Any], expected: str) -> bool:
    declared = schema.get("type")
    if isinstance(declared, str):
        return declared == expected
    if isinstance(declared, list):
        return expected in declared
    return False


def _require_type(schema: Mapping[str, Any], expected: str) -> None:
    if not _allows_type(schema, expected):
        raise _SchemaInspectionError(CodexSchemaPreflightStatus.INCOMPATIBLE)


def _definitions(schema: Mapping[str, Any]) -> Mapping[str, Any]:
    return _mapping(schema.get("definitions"))


def _definition(schema: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    definitions = _definitions(schema)
    if name not in definitions:
        raise _SchemaInspectionError(CodexSchemaPreflightStatus.INCOMPATIBLE)
    return _mapping(definitions[name])


def _contains_definition_ref(schema: Mapping[str, Any], name: str) -> bool:
    target = f"#/definitions/{name}"
    if schema.get("$ref") == target:
        return True
    for key in ("allOf", "anyOf", "oneOf"):
        raw_children = schema.get(key)
        if not isinstance(raw_children, list):
            continue
        for child in raw_children:
            if isinstance(child, dict) and _contains_definition_ref(child, name):
                return True
    return False


def _require_definition_ref(schema: Mapping[str, Any], name: str) -> None:
    if not _contains_definition_ref(schema, name):
        raise _SchemaInspectionError(CodexSchemaPreflightStatus.INCOMPATIBLE)


def _safe_token(value: object) -> str:
    if not isinstance(value, str) or _SAFE_STRUCTURAL_TOKEN.fullmatch(value) is None:
        raise _SchemaInspectionError(CodexSchemaPreflightStatus.INCOMPATIBLE)
    return value


def _variant_map(union: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    variants: dict[str, Mapping[str, Any]] = {}
    for raw_variant in _sequence(union.get("oneOf")):
        variant = _mapping(raw_variant)
        type_property = _property(variant, "type")
        enum_values = _sequence(type_property.get("enum"))
        if len(enum_values) != 1:
            raise _SchemaInspectionError(CodexSchemaPreflightStatus.INCOMPATIBLE)
        tag = _safe_token(enum_values[0])
        if tag in variants:
            raise _SchemaInspectionError(CodexSchemaPreflightStatus.INCOMPATIBLE)
        variants[tag] = variant
    return variants


def _enum_values(union: Mapping[str, Any]) -> frozenset[str]:
    values: set[str] = set()
    if "enum" in union:
        values.update(_safe_token(value) for value in _sequence(union["enum"]))
    for key in ("oneOf", "anyOf"):
        raw_variants = union.get(key)
        if raw_variants is None:
            continue
        for raw_variant in _sequence(raw_variants):
            variant = _mapping(raw_variant)
            if "enum" in variant:
                values.update(
                    _safe_token(value) for value in _sequence(variant["enum"])
                )
    return frozenset(values)


def _validate_bundle_limits(root: Path) -> None:
    files = 0
    directories = 0
    total_bytes = 0
    for directory, child_directories, child_files in os.walk(root, followlinks=False):
        directories += 1
        if directories > MAX_GENERATED_SCHEMA_DIRECTORIES:
            raise _SchemaInspectionError(CodexSchemaPreflightStatus.RESOURCE_LIMIT)
        directory_path = Path(directory)
        for child in child_directories:
            if (directory_path / child).is_symlink():
                raise _SchemaInspectionError(CodexSchemaPreflightStatus.INCOMPATIBLE)
        for child in child_files:
            path = directory_path / child
            if path.is_symlink():
                raise _SchemaInspectionError(CodexSchemaPreflightStatus.INCOMPATIBLE)
            files += 1
            if files > MAX_GENERATED_SCHEMA_FILES:
                raise _SchemaInspectionError(CodexSchemaPreflightStatus.RESOURCE_LIMIT)
            try:
                size = path.stat(follow_symlinks=False).st_size
            except OSError:
                raise _SchemaInspectionError(
                    CodexSchemaPreflightStatus.UNAVAILABLE
                ) from None
            total_bytes += size
            if total_bytes > MAX_GENERATED_SCHEMA_BYTES:
                raise _SchemaInspectionError(CodexSchemaPreflightStatus.RESOURCE_LIMIT)


def _load_schema(root: Path, relative_path: str) -> Mapping[str, Any]:
    path = root.joinpath(*relative_path.split("/"))
    if path.is_symlink() or not path.is_file():
        raise _SchemaInspectionError(CodexSchemaPreflightStatus.INCOMPATIBLE)
    try:
        size = path.stat(follow_symlinks=False).st_size
        if size < 2 or size > MAX_CONSUMED_SCHEMA_FILE_BYTES:
            raise _SchemaInspectionError(CodexSchemaPreflightStatus.RESOURCE_LIMIT)
        payload = path.read_bytes()
        parsed = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_strict_json_object,
        )
    except _SchemaInspectionError:
        raise
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        raise _SchemaInspectionError(CodexSchemaPreflightStatus.INCOMPATIBLE) from None
    return _mapping(parsed)


def _inspect_read_contract(schema: Mapping[str, Any]) -> tuple[
    tuple[str, ...], tuple[str, ...], tuple[str, ...]
]:
    _required(schema, "thread")
    _require_definition_ref(_property(schema, "thread"), "Thread")
    thread = _definition(schema, "Thread")
    _required(thread, "id", "turns")
    _require_type(_property(thread, "id"), "string")
    turns = _property(thread, "turns")
    _require_type(turns, "array")
    _require_definition_ref(_mapping(turns.get("items")), "Turn")

    turn = _definition(schema, "Turn")
    _required(turn, "id", "items")
    _require_type(_property(turn, "id"), "string")
    turn_items = _property(turn, "items")
    _require_type(turn_items, "array")
    _require_definition_ref(_mapping(turn_items.get("items")), "ThreadItem")

    item_variants = _variant_map(_definition(schema, "ThreadItem"))
    if not ADMITTED_THREAD_ITEM_TYPES.issubset(item_variants):
        raise _SchemaInspectionError(CodexSchemaPreflightStatus.INCOMPATIBLE)

    user_message = item_variants["userMessage"]
    _required(user_message, "content", "id", "type")
    user_content = _property(user_message, "content")
    _require_type(user_content, "array")
    _require_definition_ref(_mapping(user_content.get("items")), "UserInput")
    _require_type(_property(user_message, "id"), "string")

    agent_message = item_variants["agentMessage"]
    _required(agent_message, "id", "text", "type")
    _require_type(_property(agent_message, "id"), "string")
    _require_type(_property(agent_message, "text"), "string")

    plan = item_variants["plan"]
    _required(plan, "id", "text", "type")
    _require_type(_property(plan, "id"), "string")
    _require_type(_property(plan, "text"), "string")

    user_input_variants = _variant_map(_definition(schema, "UserInput"))
    if _TEXT_USER_INPUT_TYPE not in user_input_variants:
        raise _SchemaInspectionError(CodexSchemaPreflightStatus.INCOMPATIBLE)
    text_input = user_input_variants[_TEXT_USER_INPUT_TYPE]
    _required(text_input, "text", "type")
    _require_type(_property(text_input, "text"), "string")

    agent_properties = _mapping(agent_message.get("properties"))
    if "phase" in agent_properties:
        phase_property = _mapping(agent_properties["phase"])
        _require_definition_ref(phase_property, "MessagePhase")
        phases = _enum_values(_definition(schema, "MessagePhase"))
        if not phases or not phases.issubset(_SUPPORTED_AGENT_PHASES):
            raise _SchemaInspectionError(CodexSchemaPreflightStatus.INCOMPATIBLE)
    else:
        phases = frozenset()

    return (
        tuple(sorted(item_variants)),
        tuple(sorted(user_input_variants)),
        tuple(sorted(phases)),
    )


def _inspect_list_contract(
    params: Mapping[str, Any], response: Mapping[str, Any]
) -> None:
    _require_type(_property(params, "useStateDbOnly"), "boolean")
    source_kinds_property = _property(params, "sourceKinds")
    _require_type(source_kinds_property, "array")
    _require_definition_ref(
        _mapping(source_kinds_property.get("items")), "ThreadSourceKind"
    )
    source_kinds = _enum_values(_definition(params, "ThreadSourceKind"))
    if not {"cli", "vscode", "appServer"}.issubset(source_kinds):
        raise _SchemaInspectionError(CodexSchemaPreflightStatus.INCOMPATIBLE)
    _require_definition_ref(_property(params, "sortKey"), "ThreadSortKey")
    sort_keys = _enum_values(_definition(params, "ThreadSortKey"))
    if "created_at" not in sort_keys:
        raise _SchemaInspectionError(CodexSchemaPreflightStatus.INCOMPATIBLE)
    _required(response, "data")
    data = _property(response, "data")
    _require_type(data, "array")
    _require_definition_ref(_mapping(data.get("items")), "Thread")
    thread = _definition(response, "Thread")
    _required(thread, "id", "createdAt")
    _require_type(_property(thread, "id"), "string")


def _inspect_initialize_contract(params: Mapping[str, Any]) -> None:
    _required(params, "clientInfo")
    _require_definition_ref(_property(params, "clientInfo"), "ClientInfo")
    client_info = _definition(params, "ClientInfo")
    _required(client_info, "name", "version")
    _require_type(_property(client_info, "name"), "string")
    _require_type(_property(client_info, "version"), "string")
    _require_definition_ref(
        _property(params, "capabilities"), "InitializeCapabilities"
    )
    capabilities = _definition(params, "InitializeCapabilities")
    _require_type(capabilities, "object")


def _inspect_read_params(params: Mapping[str, Any]) -> None:
    _required(params, "threadId")
    _require_type(_property(params, "threadId"), "string")
    _require_type(_property(params, "includeTurns"), "boolean")


def inspect_generated_schema_bundle(root: Path) -> CodexConsumedSchemaManifest:
    """Validate only the fixed protocol slice consumed by this adapter."""

    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise _SchemaInspectionError(CodexSchemaPreflightStatus.INCOMPATIBLE)
    _validate_bundle_limits(root)
    schemas = {name: _load_schema(root, name) for name in _SCHEMA_FILES}
    _inspect_initialize_contract(schemas["v1/InitializeParams.json"])
    _mapping(schemas["v1/InitializeResponse.json"])
    _inspect_list_contract(
        schemas["v2/ThreadListParams.json"],
        schemas["v2/ThreadListResponse.json"],
    )
    _inspect_read_params(schemas["v2/ThreadReadParams.json"])
    item_types, input_types, phases = _inspect_read_contract(
        schemas["v2/ThreadReadResponse.json"]
    )
    known_items = ADMITTED_THREAD_ITEM_TYPES | DISCARDED_THREAD_ITEM_TYPES
    known_inputs = {_TEXT_USER_INPUT_TYPE} | DISCARDED_USER_INPUT_TYPES
    return CodexConsumedSchemaManifest(
        manifest_version=CONSUMED_SCHEMA_MANIFEST_VERSION,
        thread_item_types=item_types,
        user_input_types=input_types,
        agent_message_phases=phases,
        unclassified_thread_item_types=tuple(
            value for value in item_types if value not in known_items
        ),
        unclassified_user_input_types=tuple(
            value for value in input_types if value not in known_inputs
        ),
    )


def preflight_generated_schema_bundle(root: Path) -> CodexSchemaPreflightResult:
    """Return a sanitized result for a previously generated synthetic bundle."""

    try:
        manifest = inspect_generated_schema_bundle(root)
        return CodexSchemaPreflightResult(
            status=CodexSchemaPreflightStatus.COMPATIBLE,
            manifest=manifest,
        )
    except _SchemaInspectionError as error:
        return CodexSchemaPreflightResult(status=error.status)
    except (OSError, ValueError):
        return CodexSchemaPreflightResult(
            status=CodexSchemaPreflightStatus.UNAVAILABLE
        )


def _isolated_environment(codex_home: Path) -> dict[str, str]:
    allowed = {
        "COMSPEC",
        "LANG",
        "LC_ALL",
        "PATH",
        "PATHEXT",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "WINDIR",
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in allowed and "\x00" not in value
    }
    environment["CODEX_HOME"] = os.fspath(codex_home)
    return environment


def _generator_command(output_directory: Path) -> tuple[str, ...]:
    tail = ("app-server", "--listen", "stdio://")
    if len(CODEX_APP_SERVER_ARGV) <= len(tail) or CODEX_APP_SERVER_ARGV[-3:] != tail:
        raise _SchemaInspectionError(CodexSchemaPreflightStatus.UNAVAILABLE)
    prefix = CODEX_APP_SERVER_ARGV[:-3]
    command = (
        *prefix,
        "app-server",
        "generate-json-schema",
        "--out",
        os.fspath(output_directory),
    )
    if any(
        not isinstance(value, str)
        or not value
        or len(value) > 32_768
        or _SAFE_COMMAND_PATH.fullmatch(value) is None
        for value in command
    ):
        raise _SchemaInspectionError(CodexSchemaPreflightStatus.UNAVAILABLE)
    return command


def _version_command() -> tuple[str, ...]:
    tail = ("app-server", "--listen", "stdio://")
    if len(CODEX_APP_SERVER_ARGV) <= len(tail) or CODEX_APP_SERVER_ARGV[-3:] != tail:
        raise _SchemaInspectionError(CodexSchemaPreflightStatus.UNAVAILABLE)
    command = (*CODEX_APP_SERVER_ARGV[:-3], "--version")
    if any(
        not value
        or len(value) > 32_768
        or _SAFE_COMMAND_PATH.fullmatch(value) is None
        for value in command
    ):
        raise _SchemaInspectionError(CodexSchemaPreflightStatus.UNAVAILABLE)
    return command


def _run_owned_schema_process(
    command: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    stdout_limit: int,
) -> OwnedProcessResult:
    return run_owned_process(
        command,
        cwd=cwd,
        env=env,
        stdout_limit=stdout_limit,
        stderr_limit=0,
        timeout=timeout,
        maximum_active_processes=MAX_SCHEMA_PROBE_PROCESSES,
    )


@dataclass(slots=True)
class CodexInstalledSchemaProbe:
    """Run the fixed installed-schema generator under strict local bounds."""

    timeout_seconds: float = DEFAULT_SCHEMA_PROBE_TIMEOUT_SECONDS
    _runner: ProcessRunner = field(default=_run_owned_schema_process, repr=False)

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 0.1 <= float(self.timeout_seconds) <= 30.0
        ):
            raise ValueError("schema-probe timeout must be between 0.1 and 30 seconds")

    def probe(self) -> CodexSchemaPreflightResult:
        try:
            with tempfile.TemporaryDirectory(
                prefix="prompt-enhancer-codex-schema-"
            ) as temporary:
                root = Path(temporary)
                codex_home = root / "isolated-codex-home"
                output = root / "generated"
                codex_home.mkdir()
                output.mkdir()
                command = _generator_command(output)
                version_command = _version_command()
                deadline = time.monotonic() + float(self.timeout_seconds)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(version_command, 0)
                version_process = self._runner(
                    version_command,
                    cwd=root,
                    env=_isolated_environment(codex_home),
                    timeout=remaining,
                    stdout_limit=MAX_PROVIDER_VERSION_BYTES,
                )
                provider_version = "unknown"
                if version_process.returncode == 0:
                    version_match = _CODEX_VERSION.fullmatch(version_process.stdout)
                    if version_match is not None:
                        provider_version = version_match.group("version").decode("ascii")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, 0)
                completed = self._runner(
                    command,
                    cwd=root,
                    env=_isolated_environment(codex_home),
                    timeout=remaining,
                    stdout_limit=0,
                )
                if completed.returncode != 0:
                    return CodexSchemaPreflightResult(
                        status=CodexSchemaPreflightStatus.UNAVAILABLE
                    )
                manifest = inspect_generated_schema_bundle(output)
                return CodexSchemaPreflightResult(
                    status=CodexSchemaPreflightStatus.COMPATIBLE,
                    provider_version=provider_version,
                    manifest=manifest,
                )
        except subprocess.TimeoutExpired:
            return CodexSchemaPreflightResult(
                status=CodexSchemaPreflightStatus.TIMEOUT
            )
        except OwnedProcessRunError as error:
            status = {
                "owned_process_timeout": CodexSchemaPreflightStatus.TIMEOUT,
                "owned_process_stdout_limit": (
                    CodexSchemaPreflightStatus.RESOURCE_LIMIT
                ),
                "owned_process_stderr_limit": (
                    CodexSchemaPreflightStatus.RESOURCE_LIMIT
                ),
            }.get(error.code, CodexSchemaPreflightStatus.UNAVAILABLE)
            return CodexSchemaPreflightResult(status=status)
        except _SchemaInspectionError as error:
            return CodexSchemaPreflightResult(status=error.status)
        except (OSError, ValueError):
            return CodexSchemaPreflightResult(
                status=CodexSchemaPreflightStatus.UNAVAILABLE
            )


@dataclass(slots=True)
class CodexTextWindowCompatibilityProbe:
    """Provider-neutral compatibility adapter for the Codex text surface."""

    schema_probe: CodexSchemaProbe = field(
        default_factory=CodexInstalledSchemaProbe
    )
    _clock: Clock = field(default=_utc_now, repr=False)

    @property
    def descriptor(self) -> DecoderDescriptor:
        return CODEX_TEXT_WINDOW_DECODER_DESCRIPTOR

    def check(self) -> ProviderCompatibilityReport:
        result = self.schema_probe.probe()
        try:
            checked_at = self._clock()
            if (
                not isinstance(checked_at, datetime)
                or checked_at.tzinfo is None
                or checked_at.utcoffset() is None
            ):
                raise TypeError
            checked_at = checked_at.astimezone(UTC)
        except Exception:
            checked_at = datetime.now(UTC)

        capabilities = self.descriptor.capabilities
        if result.status is CodexSchemaPreflightStatus.COMPATIBLE:
            manifest = result.manifest
            has_unclassified = manifest is not None and bool(
                manifest.unclassified_thread_item_types
                or manifest.unclassified_user_input_types
            )
            reasons: tuple[CompatibilityReason, ...] = ()
            if has_unclassified:
                state = CompatibilityState.DEGRADED
                extraction = ExtractionCompleteness(
                    state=ExtractionCompletenessState.UNKNOWN,
                    observed_units=0,
                )
                reasons = (
                    CompatibilityReason(
                        code=CompatibilityReasonCode.UNKNOWN_UNION_VARIANT
                    ),
                )
            else:
                extraction = ExtractionCompleteness(
                    state=ExtractionCompletenessState.COMPLETE,
                    observed_units=len(capabilities),
                    eligible_units=len(capabilities),
                    coverage=1.0,
                )
                exact_manifest = manifest is not None and (
                    manifest.thread_item_types
                    == _TESTED_0_144_5_THREAD_ITEM_TYPES
                    and manifest.user_input_types
                    == _TESTED_0_144_5_USER_INPUT_TYPES
                    and manifest.agent_message_phases
                    == _TESTED_0_144_5_AGENT_PHASES
                )
                if (
                    result.provider_version in self.descriptor.tested_provider_versions
                    and exact_manifest
                ):
                    state = CompatibilityState.EXACT
                else:
                    state = CompatibilityState.COMPATIBLE
                    reasons = (
                        CompatibilityReason(
                            code=(
                                CompatibilityReasonCode.SCHEMA_ARTIFACT_UNKNOWN
                                if result.provider_version
                                in self.descriptor.tested_provider_versions
                                else (
                                    CompatibilityReasonCode.PROVIDER_VERSION_UNKNOWN
                                    if result.provider_version == "unknown"
                                    else CompatibilityReasonCode.PROVIDER_VERSION_UNTESTED
                                )
                            )
                        ),
                    )
            observations = tuple(
                CapabilityObservation(key=key, state=CapabilityState.SUPPORTED)
                for key in capabilities
            )
            return ProviderCompatibilityReport(
                descriptor=self.descriptor,
                provider_version=result.provider_version,
                state=state,
                capabilities=observations,
                extraction=extraction,
                reasons=reasons,
                checked_at=checked_at,
            )

        reason_code = {
            CodexSchemaPreflightStatus.INCOMPATIBLE: (
                CompatibilityReasonCode.SCHEMA_FAMILY_UNSUPPORTED
            ),
            CodexSchemaPreflightStatus.TIMEOUT: CompatibilityReasonCode.TIMEOUT,
            CodexSchemaPreflightStatus.RESOURCE_LIMIT: (
                CompatibilityReasonCode.RESOURCE_LIMIT
            ),
            CodexSchemaPreflightStatus.UNAVAILABLE: (
                CompatibilityReasonCode.PROVIDER_UNAVAILABLE
            ),
        }[result.status]
        compatibility_state = (
            CompatibilityState.INCOMPATIBLE
            if result.status is CodexSchemaPreflightStatus.INCOMPATIBLE
            else CompatibilityState.UNAVAILABLE
        )
        report_reasons = [CompatibilityReason(code=reason_code)]
        capability_reason = reason_code
        if compatibility_state is CompatibilityState.UNAVAILABLE and (
            reason_code is not CompatibilityReasonCode.PROVIDER_UNAVAILABLE
        ):
            report_reasons.append(
                CompatibilityReason(
                    code=CompatibilityReasonCode.PROVIDER_UNAVAILABLE
                )
            )
            capability_reason = CompatibilityReasonCode.PROVIDER_UNAVAILABLE
        return ProviderCompatibilityReport(
            descriptor=self.descriptor,
            provider_version=result.provider_version,
            state=compatibility_state,
            capabilities=tuple(
                CapabilityObservation(
                    key=key,
                    state=CapabilityState.UNKNOWN,
                    reason_code=capability_reason,
                )
                for key in capabilities
            ),
            extraction=ExtractionCompleteness(
                state=ExtractionCompletenessState.NONE,
                observed_units=0,
            ),
            reasons=tuple(report_reasons),
            checked_at=checked_at,
        )
