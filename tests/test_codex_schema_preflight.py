from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess

import pytest

from prompt_enhancer.application.owned_process import OwnedProcessResult
from prompt_enhancer.application.providers import (
    CapabilityKey,
    CapabilityState,
    CompatibilityReasonCode,
    CompatibilityState,
    ExtractionCompletenessState,
    ProviderCompatibilityProbe,
    ProviderSurface,
)
from prompt_enhancer.infrastructure.providers.codex_app_server import schema_preflight
from prompt_enhancer.infrastructure.providers.codex_app_server.schema_preflight import (
    CODEX_TEXT_WINDOW_DECODER_DESCRIPTOR,
    CONSUMED_SCHEMA_MANIFEST_VERSION,
    CodexInstalledSchemaProbe,
    CodexSchemaPreflightStatus,
    CodexTextWindowCompatibilityProbe,
    MAX_PROVIDER_VERSION_BYTES,
    MAX_SCHEMA_PROBE_PROCESSES,
    _run_owned_schema_process,
    preflight_generated_schema_bundle,
)


_DISCARDED_ITEM_TYPES = (
    "reasoning",
    "commandExecution",
    "fileChange",
    "mcpToolCall",
    "dynamicToolCall",
    "collabAgentToolCall",
    "hookPrompt",
    "subAgentActivity",
    "webSearch",
    "imageView",
    "sleep",
    "imageGeneration",
    "enteredReviewMode",
    "exitedReviewMode",
    "contextCompaction",
)


def _tagged_variant(tag: str, **properties: object) -> dict[str, object]:
    return {
        "type": "object",
        "required": ["type", *properties],
        "properties": {
            "type": {"type": "string", "enum": [tag]},
            **properties,
        },
    }


def _write_json(root: Path, relative: str, value: object) -> None:
    path = root.joinpath(*relative.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_synthetic_bundle(
    root: Path,
    *,
    future_item: bool = False,
    future_input: bool = False,
    extra_phase: str | None = None,
) -> None:
    initialize_params = {
        "type": "object",
        "required": ["clientInfo"],
        "properties": {
            "clientInfo": {"$ref": "#/definitions/ClientInfo"},
            "capabilities": {
                "$ref": "#/definitions/InitializeCapabilities"
            },
        },
        "definitions": {
            "ClientInfo": {
                "type": "object",
                "required": ["name", "version"],
                "properties": {
                    "name": {"type": "string"},
                    "version": {"type": "string"},
                },
            },
            "InitializeCapabilities": {"type": "object", "properties": {}},
        },
    }
    list_params = {
        "type": "object",
        "properties": {
            "useStateDbOnly": {"type": "boolean"},
            "sourceKinds": {
                "type": "array",
                "items": {"$ref": "#/definitions/ThreadSourceKind"},
            },
            "sortKey": {"$ref": "#/definitions/ThreadSortKey"},
        },
        "definitions": {
            "ThreadSourceKind": {
                "type": "string",
                "enum": ["cli", "vscode", "appServer"],
            },
            "ThreadSortKey": {"type": "string", "enum": ["created_at"]},
        },
    }
    list_response = {
        "type": "object",
        "required": ["data"],
        "properties": {
            "data": {
                "type": "array",
                "items": {"$ref": "#/definitions/Thread"},
            }
        },
        "definitions": {
            "Thread": {
                "type": "object",
                "required": ["id", "createdAt", "turns"],
                "properties": {
                    "id": {"type": "string"},
                    "createdAt": {"type": "integer"},
                    "turns": {"type": "array"},
                },
            }
        },
    }
    read_params = {
        "type": "object",
        "required": ["threadId"],
        "properties": {
            "threadId": {"type": "string"},
            "includeTurns": {"type": "boolean"},
        },
    }
    item_variants = [
        _tagged_variant(
            "userMessage",
            content={
                "type": "array",
                "items": {"$ref": "#/definitions/UserInput"},
            },
            id={"type": "string"},
        ),
        _tagged_variant(
            "agentMessage",
            id={"type": "string"},
            text={"type": "string"},
            phase={"$ref": "#/definitions/MessagePhase"},
        ),
        _tagged_variant(
            "plan",
            id={"type": "string"},
            text={"type": "string"},
        ),
        *(_tagged_variant(tag) for tag in _DISCARDED_ITEM_TYPES),
    ]
    if future_item:
        item_variants.append(
            _tagged_variant("futureMessage", text={"type": "string"})
        )
    input_variants = [
        _tagged_variant("text", text={"type": "string"}),
        _tagged_variant("image"),
        _tagged_variant("localImage"),
        _tagged_variant("skill"),
        _tagged_variant("mention"),
    ]
    if future_input:
        input_variants.append(
            _tagged_variant("futureInput", text={"type": "string"})
        )
    phases = ["commentary", "final_answer"]
    if extra_phase is not None:
        phases.append(extra_phase)
    read_response = {
        "type": "object",
        "required": ["thread"],
        "properties": {"thread": {"$ref": "#/definitions/Thread"}},
        "definitions": {
            "Thread": {
                "type": "object",
                "required": ["id", "turns"],
                "properties": {
                    "id": {"type": "string"},
                    "turns": {
                        "type": "array",
                        "items": {"$ref": "#/definitions/Turn"},
                    },
                },
            },
            "Turn": {
                "type": "object",
                "required": ["id", "items"],
                "properties": {
                    "id": {"type": "string"},
                    "items": {
                        "type": "array",
                        "items": {"$ref": "#/definitions/ThreadItem"},
                    },
                },
            },
            "ThreadItem": {"oneOf": item_variants},
            "UserInput": {"oneOf": input_variants},
            "MessagePhase": {
                "oneOf": [
                    {"type": "string", "enum": [phase]} for phase in phases
                ]
            },
        },
    }

    _write_json(root, "v1/InitializeParams.json", initialize_params)
    _write_json(root, "v1/InitializeResponse.json", {"type": "object"})
    _write_json(root, "v2/ThreadListParams.json", list_params)
    _write_json(root, "v2/ThreadListResponse.json", list_response)
    _write_json(root, "v2/ThreadReadParams.json", read_params)
    _write_json(root, "v2/ThreadReadResponse.json", read_response)


def test_synthetic_consumed_schema_slice_is_compatible_and_content_free(
    tmp_path: Path,
) -> None:
    _write_synthetic_bundle(tmp_path)

    result = preflight_generated_schema_bundle(tmp_path)

    assert result.status is CodexSchemaPreflightStatus.COMPATIBLE
    assert result.manifest is not None
    assert result.manifest.manifest_version == CONSUMED_SCHEMA_MANIFEST_VERSION
    assert result.manifest.unclassified_thread_item_types == ()
    assert result.manifest.unclassified_user_input_types == ()
    assert set(result.manifest.agent_message_phases) == {
        "commentary",
        "final_answer",
    }


def test_disconnected_definition_graph_is_structurally_incompatible(
    tmp_path: Path,
) -> None:
    _write_synthetic_bundle(tmp_path)
    path = tmp_path / "v2" / "ThreadReadResponse.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    schema["definitions"]["Thread"]["properties"]["turns"]["items"] = {
        "$ref": "#/definitions/ThreadItem"
    }
    _write_json(tmp_path, "v2/ThreadReadResponse.json", schema)

    result = preflight_generated_schema_bundle(tmp_path)

    assert result.status is CodexSchemaPreflightStatus.INCOMPATIBLE
    assert result.manifest is None


def test_additive_unknown_unions_are_reported_without_admitting_them(
    tmp_path: Path,
) -> None:
    _write_synthetic_bundle(tmp_path, future_item=True, future_input=True)

    result = preflight_generated_schema_bundle(tmp_path)

    assert result.status is CodexSchemaPreflightStatus.COMPATIBLE
    assert result.manifest is not None
    assert result.manifest.unclassified_thread_item_types == ("futureMessage",)
    assert result.manifest.unclassified_user_input_types == ("futureInput",)


def test_new_agent_phase_is_a_genuine_structural_incompatibility(
    tmp_path: Path,
) -> None:
    private_canary = "PRIVATE-PHASE-CANARY"
    _write_synthetic_bundle(tmp_path, extra_phase=private_canary)

    result = preflight_generated_schema_bundle(tmp_path)

    assert result.status is CodexSchemaPreflightStatus.INCOMPATIBLE
    assert result.manifest is None
    assert private_canary not in repr(result)


def test_installed_probe_uses_fixed_bounded_isolated_processes(
    tmp_path: Path,
) -> None:
    observed: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def runner(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        observed.append((command, kwargs))
        if command[-1] == "--version":
            stdout = b"codex-cli 0.144.5\n"
        else:
            _write_synthetic_bundle(Path(command[-1]))
            stdout = b""
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    result = CodexInstalledSchemaProbe(_runner=runner).probe()

    assert result.status is CodexSchemaPreflightStatus.COMPATIBLE
    assert result.provider_version == "0.144.5"
    assert len(observed) == 2
    version_command, version_options = observed[0]
    schema_command, schema_options = observed[1]
    assert version_command[-1] == "--version"
    assert schema_command[-4:-1] == (
        "app-server",
        "generate-json-schema",
        "--out",
    )
    assert "--experimental" not in schema_command
    for options in (version_options, schema_options):
        assert 0 < options["timeout"] <= 10
        assert isinstance(options["cwd"], Path)
        environment = options["env"]
        assert isinstance(environment, dict)
        assert "CODEX_HOME" in environment
        assert not {
            "HOME",
            "USERPROFILE",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
        }.intersection(key.upper() for key in environment)
    assert version_options["stdout_limit"] == MAX_PROVIDER_VERSION_BYTES
    assert schema_options["stdout_limit"] == 0


def test_schema_runner_uses_shared_owned_process_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_run(command: tuple[str, ...], **kwargs: object) -> OwnedProcessResult:
        observed["command"] = command
        observed.update(kwargs)
        return OwnedProcessResult(returncode=0, stdout=b"synthetic")

    monkeypatch.setattr(schema_preflight, "run_owned_process", fake_run)
    result = _run_owned_schema_process(
        ("synthetic-codex", "--version"),
        cwd=tmp_path,
        env={"PATH": "synthetic"},
        timeout=1.0,
        stdout_limit=MAX_PROVIDER_VERSION_BYTES,
    )

    assert result.stdout == b"synthetic"
    assert observed["command"] == ("synthetic-codex", "--version")
    assert observed["cwd"] == tmp_path
    assert observed["stderr_limit"] == 0
    assert observed["maximum_active_processes"] == MAX_SCHEMA_PROBE_PROCESSES


def test_installed_probe_discards_timeout_details() -> None:
    private_canary = "PRIVATE-TIMEOUT-CANARY"

    def runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(command, 0.1, output=private_canary)

    result = CodexInstalledSchemaProbe(_runner=runner).probe()

    assert result.status is CodexSchemaPreflightStatus.TIMEOUT
    assert private_canary not in repr(result)


def test_generated_bundle_file_bound_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_synthetic_bundle(tmp_path)
    monkeypatch.setattr(
        "prompt_enhancer.infrastructure.providers.codex_app_server.schema_preflight.MAX_GENERATED_SCHEMA_FILES",
        1,
    )

    result = preflight_generated_schema_bundle(tmp_path)

    assert result.status is CodexSchemaPreflightStatus.RESOURCE_LIMIT


class _SyntheticSchemaProbe:
    def __init__(self, result) -> None:
        self._result = result

    def probe(self):
        return self._result


def test_provider_probe_reports_current_synthetic_schema_as_exact(
    tmp_path: Path,
) -> None:
    _write_synthetic_bundle(tmp_path)
    schema_result = preflight_generated_schema_bundle(tmp_path)
    schema_result = schema_result.__class__(
        status=schema_result.status,
        provider_version="0.144.5",
        manifest=schema_result.manifest,
    )
    checked_at = datetime(2030, 1, 2, tzinfo=UTC)
    probe = CodexTextWindowCompatibilityProbe(
        schema_probe=_SyntheticSchemaProbe(schema_result),
        _clock=lambda: checked_at,
    )

    report = probe.check()

    assert isinstance(probe, ProviderCompatibilityProbe)
    assert probe.descriptor == CODEX_TEXT_WINDOW_DECODER_DESCRIPTOR
    assert report.state is CompatibilityState.EXACT
    assert report.checked_at == checked_at
    assert report.provider_version == "0.144.5"
    assert report.extraction.state is ExtractionCompletenessState.COMPLETE
    assert report.reasons == ()
    assert report.descriptor.provider.key == "codex"
    assert report.descriptor.surface is ProviderSurface.TEXT_WINDOW
    assert report.descriptor.capabilities == (
        CapabilityKey.USER_MESSAGES,
        CapabilityKey.AGENT_MESSAGES,
        CapabilityKey.PLAN_MESSAGES,
    )
    assert all(
        capability.state is CapabilityState.SUPPORTED
        for capability in report.capabilities
    )


def test_provider_probe_degrades_on_additive_unclassified_variants(
    tmp_path: Path,
) -> None:
    _write_synthetic_bundle(tmp_path, future_item=True)
    schema_result = preflight_generated_schema_bundle(tmp_path)
    schema_result = schema_result.__class__(
        status=schema_result.status,
        provider_version="0.144.5",
        manifest=schema_result.manifest,
    )
    probe = CodexTextWindowCompatibilityProbe(
        schema_probe=_SyntheticSchemaProbe(schema_result),
    )

    report = probe.check()

    assert report.state is CompatibilityState.DEGRADED
    assert report.extraction.state is ExtractionCompletenessState.UNKNOWN
    assert tuple(reason.code for reason in report.reasons) == (
        CompatibilityReasonCode.UNKNOWN_UNION_VARIANT,
    )
