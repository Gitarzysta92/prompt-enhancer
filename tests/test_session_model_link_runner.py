from __future__ import annotations

import json
from pathlib import Path

from pydantic import SecretStr
import pytest

from prompt_enhancer.application.analysis.model_link_experiments import (
    ModelExperimentDevice,
    ModelLinkCandidate,
    ModelLinkCandidateKind,
    ModelLinkCase,
    ModelLinkRunnerRequest,
)
from prompt_enhancer.application.owned_process import (
    OwnedProcessResult,
    OwnedProcessRunError,
)
from prompt_enhancer.infrastructure.text_models import session_links
from prompt_enhancer.infrastructure.text_models.session_links import (
    MAX_SESSION_LINK_PROCESSES,
    MAX_SESSION_LINK_STDOUT_BYTES,
    SESSION_LINK_RUNNER_SCHEMA_VERSION,
    SessionLinkRunnerError,
    SubprocessSessionModelLinkRunner,
    _child_environment,
    _model_identity,
    _parse_result,
    _strict_payload,
)
from prompt_enhancer.infrastructure.text_models.manifests import (
    BGE_RERANKER_V2_M3,
    QWEN3_EMBEDDING_06B,
)


QUERY_ID = "1" * 64
CANDIDATE_ID = "2" * 64
SYNTHETIC_CANARY = "SYNTHETIC_REDACTED_EXPERIMENT_CANARY"


def _request() -> ModelLinkRunnerRequest:
    return ModelLinkRunnerRequest(
        device=ModelExperimentDevice.CUDA,
        cases=(
            ModelLinkCase(
                query_message_id=QUERY_ID,
                query_sequence=0,
                query_text=SecretStr(f"Fictional request {SYNTHETIC_CANARY}"),
                candidates=(
                    ModelLinkCandidate(
                        message_id=CANDIDATE_ID,
                        sequence=1,
                        kind=ModelLinkCandidateKind.RESPONSE,
                        text=SecretStr("Fictional response for the local experiment."),
                    ),
                ),
            ),
        ),
    )


def _safe_response() -> dict[str, object]:
    return {
        "schema_version": SESSION_LINK_RUNNER_SCHEMA_VERSION,
        "resolved_device": "cuda",
        "qwen_model": _model_identity(
            QWEN3_EMBEDDING_06B, "qwen3_embedding_last_token_v1"
        ),
        "bge_model": _model_identity(
            BGE_RERANKER_V2_M3, "bge_reranker_sequence_classifier_v1"
        ),
        "scores": [
            {
                "query_message_id": QUERY_ID,
                "candidate_message_id": CANDIDATE_ID,
                "qwen_score": 0.75,
                "bge_score": 3.5,
            }
        ],
    }


def test_subprocess_runner_uses_stdin_only_and_accepts_content_free_stdout(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        captured["env"] = kwargs["env"]
        captured["input"] = kwargs["stdin_payload"]
        assert kwargs["stderr_limit"] == 0
        assert kwargs["stdout_limit"] == MAX_SESSION_LINK_STDOUT_BYTES
        assert kwargs["maximum_active_processes"] == MAX_SESSION_LINK_PROCESSES
        return OwnedProcessResult(
            returncode=0,
            stdout=json.dumps(_safe_response()).encode("utf-8"),
        )

    monkeypatch.setattr(session_links, "run_owned_process", fake_run)
    result = SubprocessSessionModelLinkRunner().run(_request())

    serialized_command = json.dumps(captured["command"])
    serialized_environment = json.dumps(captured["env"], sort_keys=True)
    assert SYNTHETIC_CANARY not in serialized_command
    assert SYNTHETIC_CANARY not in serialized_environment
    assert SYNTHETIC_CANARY in captured["input"].decode("utf-8")
    assert SYNTHETIC_CANARY not in result.model_dump_json()
    assert result.scores[0].qwen_score == 0.75


def test_subprocess_runner_maps_owned_cleanup_failure_to_closed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_run(*_args: object, **_kwargs: object) -> OwnedProcessResult:
        raise OwnedProcessRunError("owned_process_cleanup_unconfirmed")

    monkeypatch.setattr(session_links, "run_owned_process", fail_run)

    with pytest.raises(SessionLinkRunnerError, match="^session_link_runner_failed$"):
        SubprocessSessionModelLinkRunner().run(_request())


def test_child_environment_is_offline_and_excludes_home_and_tokens(monkeypatch) -> None:
    monkeypatch.setenv("HOME", "example-home-canary")
    monkeypatch.setenv("USERPROFILE", "example-profile-canary")
    monkeypatch.setenv("HF_TOKEN", "example-token-canary")
    environment = _child_environment(Path("D:/example-repository"))

    assert environment["HF_HUB_OFFLINE"] == "1"
    assert environment["TRANSFORMERS_OFFLINE"] == "1"
    assert environment["HF_HUB_DISABLE_TELEMETRY"] == "1"
    assert "HOME" not in environment
    assert "USERPROFILE" not in environment
    assert "HF_TOKEN" not in environment
    assert "example-token-canary" not in json.dumps(environment)


def test_result_contract_rejects_transcript_fields_and_incomplete_scores() -> None:
    response = _safe_response()
    response["query_excerpt"] = "must-not-cross-process-output"
    with pytest.raises(SessionLinkRunnerError, match="invalid_session_link_result"):
        _parse_result(response, _request())

    response = _safe_response()
    response["qwen_model"]["revision"] = "0" * 40
    with pytest.raises(SessionLinkRunnerError, match="invalid_session_link_result"):
        _parse_result(response, _request())

    response = _safe_response()
    response["scores"] = []
    with pytest.raises(SessionLinkRunnerError, match="invalid_session_link_result"):
        _parse_result(response, _request())


def test_child_payload_rejects_extra_content_and_malformed_identifiers() -> None:
    payload = {
        "schema_version": SESSION_LINK_RUNNER_SCHEMA_VERSION,
        "device": "cpu",
        "cases": [
            {
                "query_id": QUERY_ID,
                "query_text": "Fictional query",
                "candidates": [
                    {"candidate_id": CANDIDATE_ID, "text": "Fictional candidate"}
                ],
            }
        ],
    }
    device, query_ids, cases = _strict_payload(payload)
    assert device == "cpu" and query_ids == (QUERY_ID,) and len(cases) == 1

    payload["source_path"] = "must-not-be-accepted"
    with pytest.raises(SessionLinkRunnerError, match="invalid_session_link_payload"):
        _strict_payload(payload)
