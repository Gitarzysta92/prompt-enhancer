"""Offline subprocess adapter for the selected-session neural-link experiment."""

from __future__ import annotations

import gc
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Mapping

from ...application.analysis.model_link_experiments import (
    ModelExperimentDevice,
    ModelLinkModelIdentity,
    ModelLinkPairScore,
    ModelLinkRunnerRequest,
    ModelLinkRunnerResult,
)
from ...application.owned_process import OwnedProcessRunError, run_owned_process
from .benchmark import RetrievalCandidate, RetrievalCase
from .loader import (
    isolated_hugging_face_environment,
    prepare_model_snapshot,
    transformers_network_closed,
)
from .manifests import BGE_RERANKER_V2_M3, QWEN3_EMBEDDING_06B, ModelManifest
from .transformers_backends import (
    TransformersLastTokenEmbeddingScorer,
    TransformersSequenceReranker,
    resolve_device,
)


SESSION_LINK_RUNNER_SCHEMA_VERSION = 1
MAX_SESSION_LINK_STDIN_BYTES = 512 * 1024
MAX_SESSION_LINK_STDOUT_BYTES = 1024 * 1024
MAX_SESSION_LINK_PROCESSES = 32


class SessionLinkRunnerError(RuntimeError):
    """Fixed local failure; never carries private subprocess output."""


def _model_identity(manifest: ModelManifest, backend_key: str) -> dict[str, str]:
    return {
        "key": manifest.key,
        "repository_id": manifest.repository_id,
        "revision": manifest.revision,
        "license_spdx": manifest.license_spdx,
        "tokenizer_id": f"{manifest.tokenizer_repository_id}:{manifest.tokenizer_revision}",
        "backend_key": backend_key,
    }


def _strict_payload(
    payload: object,
) -> tuple[str, tuple[str, ...], tuple[RetrievalCase, ...]]:
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "device",
        "cases",
    }:
        raise SessionLinkRunnerError("invalid_session_link_payload")
    if payload["schema_version"] != SESSION_LINK_RUNNER_SCHEMA_VERSION:
        raise SessionLinkRunnerError("invalid_session_link_payload")
    device = payload["device"]
    if device not in {"auto", "cpu", "cuda", "mps"}:
        raise SessionLinkRunnerError("invalid_session_link_payload")
    raw_cases = payload["cases"]
    if not isinstance(raw_cases, list) or not 1 <= len(raw_cases) <= 8:
        raise SessionLinkRunnerError("invalid_session_link_payload")
    cases: list[RetrievalCase] = []
    query_ids: list[str] = []
    seen_queries: set[str] = set()
    for raw_case in raw_cases:
        if not isinstance(raw_case, dict) or set(raw_case) != {
            "query_id",
            "query_text",
            "candidates",
        }:
            raise SessionLinkRunnerError("invalid_session_link_payload")
        query_id = raw_case["query_id"]
        query_text = raw_case["query_text"]
        candidates = raw_case["candidates"]
        if (
            not isinstance(query_id, str)
            or len(query_id) != 64
            or any(char not in "0123456789abcdef" for char in query_id)
            or query_id in seen_queries
            or not isinstance(query_text, str)
            or not 1 <= len(query_text) <= 4_000
            or not isinstance(candidates, list)
            or not 1 <= len(candidates) <= 8
        ):
            raise SessionLinkRunnerError("invalid_session_link_payload")
        seen_queries.add(query_id)
        query_ids.append(query_id)
        parsed_candidates: list[RetrievalCandidate] = []
        seen_candidates: set[str] = set()
        for raw_candidate in candidates:
            if not isinstance(raw_candidate, dict) or set(raw_candidate) != {
                "candidate_id",
                "text",
            }:
                raise SessionLinkRunnerError("invalid_session_link_payload")
            candidate_id = raw_candidate["candidate_id"]
            text = raw_candidate["text"]
            if (
                not isinstance(candidate_id, str)
                or len(candidate_id) != 64
                or any(char not in "0123456789abcdef" for char in candidate_id)
                or candidate_id in seen_candidates
                or not isinstance(text, str)
                or not 1 <= len(text) <= 4_000
            ):
                raise SessionLinkRunnerError("invalid_session_link_payload")
            seen_candidates.add(candidate_id)
            parsed_candidates.append(
                RetrievalCandidate(candidate_id=candidate_id, text=text)
            )
        cases.append(
            RetrievalCase(
                language="unknown",
                query=query_text,
                positive_candidate_id=parsed_candidates[0].candidate_id,
                candidates=tuple(parsed_candidates),
            )
        )
    return device, tuple(query_ids), tuple(cases)


def execute_session_link_payload(payload: object) -> dict[str, object]:
    """Execute verified cached models; return scores and content-free provenance only."""

    requested_device, query_ids, cases = _strict_payload(payload)
    resolved_device = resolve_device(requested_device)
    with isolated_hugging_face_environment(), transformers_network_closed():
        qwen_snapshot = prepare_model_snapshot(
            QWEN3_EMBEDDING_06B, allow_download=False
        )
        bge_snapshot = prepare_model_snapshot(
            BGE_RERANKER_V2_M3, allow_download=False
        )
        qwen = TransformersLastTokenEmbeddingScorer(
            QWEN3_EMBEDDING_06B,
            qwen_snapshot,
            device=resolved_device,
            batch_size=min(8, QWEN3_EMBEDDING_06B.max_batch_size),
        )
        try:
            qwen_rows = qwen.score(cases)
        finally:
            qwen.close()
            del qwen
            gc.collect()
        bge = TransformersSequenceReranker(
            BGE_RERANKER_V2_M3,
            bge_snapshot,
            device=resolved_device,
            batch_size=min(8, BGE_RERANKER_V2_M3.max_batch_size),
        )
        try:
            bge_rows = bge.score(cases)
        finally:
            bge.close()
            del bge
            gc.collect()

    scores: list[dict[str, object]] = []
    for case_index, case in enumerate(cases):
        if len(qwen_rows[case_index]) != len(case.candidates) or len(
            bge_rows[case_index]
        ) != len(case.candidates):
            raise SessionLinkRunnerError("invalid_model_score_shape")
        for candidate_index, candidate in enumerate(case.candidates):
            qwen_score = float(qwen_rows[case_index][candidate_index])
            bge_score = float(bge_rows[case_index][candidate_index])
            if not math.isfinite(qwen_score) or not math.isfinite(bge_score):
                raise SessionLinkRunnerError("non_finite_model_score")
            scores.append(
                {
                    "query_message_id": query_ids[case_index],
                    "candidate_message_id": candidate.candidate_id,
                    "qwen_score": round(qwen_score, 8),
                    "bge_score": round(bge_score, 8),
                }
            )
    return {
        "schema_version": SESSION_LINK_RUNNER_SCHEMA_VERSION,
        "resolved_device": resolved_device,
        "qwen_model": _model_identity(
            QWEN3_EMBEDDING_06B, TransformersLastTokenEmbeddingScorer.key
        ),
        "bge_model": _model_identity(
            BGE_RERANKER_V2_M3, TransformersSequenceReranker.key
        ),
        "scores": scores,
    }


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _child_environment(root: Path) -> dict[str, str]:
    allowed: dict[str, str] = {}
    for name in (
        "PATH",
        "SystemRoot",
        "WINDIR",
        "TEMP",
        "TMP",
        "COMSPEC",
        "PATHEXT",
        "CUDA_VISIBLE_DEVICES",
    ):
        value = os.environ.get(name)
        if value:
            allowed[name] = value
    allowed.update(
        {
            "PYTHONPATH": str(root / "src"),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "HF_HUB_DISABLE_PROGRESS_BARS": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "TRANSFORMERS_VERBOSITY": "error",
        }
    )
    return allowed


def _request_payload(request: ModelLinkRunnerRequest) -> dict[str, object]:
    return {
        "schema_version": SESSION_LINK_RUNNER_SCHEMA_VERSION,
        "device": request.device.value,
        "cases": [
            {
                "query_id": case.query_message_id,
                "query_text": case.query_text.get_secret_value(),
                "candidates": [
                    {
                        "candidate_id": candidate.message_id,
                        "text": candidate.text.get_secret_value(),
                    }
                    for candidate in case.candidates
                ],
            }
            for case in request.cases
        ],
    }


def _parse_result(payload: object, request: ModelLinkRunnerRequest) -> ModelLinkRunnerResult:
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "resolved_device",
        "qwen_model",
        "bge_model",
        "scores",
    }:
        raise SessionLinkRunnerError("invalid_session_link_result")
    if payload["schema_version"] != SESSION_LINK_RUNNER_SCHEMA_VERSION:
        raise SessionLinkRunnerError("invalid_session_link_result")
    if payload["qwen_model"] != _model_identity(
        QWEN3_EMBEDDING_06B,
        TransformersLastTokenEmbeddingScorer.key,
    ) or payload["bge_model"] != _model_identity(
        BGE_RERANKER_V2_M3,
        TransformersSequenceReranker.key,
    ):
        raise SessionLinkRunnerError("invalid_session_link_result")
    try:
        result = ModelLinkRunnerResult(
            resolved_device=ModelExperimentDevice(payload["resolved_device"]),
            qwen_model=ModelLinkModelIdentity.model_validate(payload["qwen_model"]),
            bge_model=ModelLinkModelIdentity.model_validate(payload["bge_model"]),
            scores=tuple(
                ModelLinkPairScore.model_validate(item)
                for item in payload["scores"]
            ),
        )
    except Exception:
        raise SessionLinkRunnerError("invalid_session_link_result") from None
    expected = {
        (case.query_message_id, candidate.message_id)
        for case in request.cases
        for candidate in case.candidates
    }
    observed = {
        (item.query_message_id, item.candidate_message_id) for item in result.scores
    }
    if observed != expected or len(observed) != len(result.scores):
        raise SessionLinkRunnerError("invalid_session_link_result")
    return result


class SubprocessSessionModelLinkRunner:
    """Send redacted text through stdin only; receive content-free scores on stdout."""

    def run(self, request: ModelLinkRunnerRequest) -> ModelLinkRunnerResult:
        root = _repository_root()
        script = root / "scripts" / "run_session_model_links.py"
        if not script.is_file():
            raise SessionLinkRunnerError("session_link_runner_unavailable")
        encoded = json.dumps(
            _request_payload(request),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > MAX_SESSION_LINK_STDIN_BYTES:
            raise SessionLinkRunnerError("session_link_input_exceeded_bound")
        try:
            completed = run_owned_process(
                [sys.executable, str(script)],
                cwd=root,
                env=_child_environment(root),
                stdin_payload=encoded,
                stdout_limit=MAX_SESSION_LINK_STDOUT_BYTES,
                stderr_limit=0,
                timeout=300,
                maximum_active_processes=MAX_SESSION_LINK_PROCESSES,
            )
        except (OSError, OwnedProcessRunError):
            raise SessionLinkRunnerError("session_link_runner_failed") from None
        if completed.returncode != 0:
            raise SessionLinkRunnerError("session_link_runner_failed")
        try:
            payload = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SessionLinkRunnerError("invalid_session_link_result") from None
        return _parse_result(payload, request)
