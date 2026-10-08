"""Export and score the fixed fictional cross-model challenge.

This helper has no provider client and no credential handling.  Export reads
only checked-in synthetic fixtures.  Score accepts response files only from the
dedicated runtime directory and writes content-free aggregate reports there.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_ROOT = _REPOSITORY_ROOT / "src"
_RUNTIME_ROOT = _REPOSITORY_ROOT / "runtime" / "model-eval" / "cross-model-v1"
_MODEL_FIXTURE = (
    _REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "synthetic"
    / "text_models"
    / "bilingual_model_screen_v1.json"
)
_RUBRIC_FIXTURE = (
    _REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "synthetic"
    / "text_models"
    / "bilingual_rubric_screen_v1.json"
)
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from prompt_enhancer.application.analysis.cross_model_challenge import (
    CROSS_MODEL_CHALLENGE_ID,
    CROSS_MODEL_VARIANTS,
    CrossModelChallengeError,
    build_cross_model_challenge,
    compare_cross_model_response_stability,
    cross_model_response_schema,
    render_cross_model_prompt,
    score_cross_model_response,
)
from prompt_enhancer.infrastructure.text_models.loader import (
    ModelCacheBoundaryError,
    validate_model_cache_root,
)


_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _load_json(path: Path, *, maximum_bytes: int) -> dict[str, Any]:
    try:
        if path.stat().st_size > maximum_bytes:
            raise CrossModelChallengeError("json_file_too_large")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CrossModelChallengeError("json_file_unreadable") from exc
    if not isinstance(payload, dict):
        raise CrossModelChallengeError("json_root_must_be_an_object")
    return payload


def _runtime_file(name: str) -> Path:
    if not _SAFE_NAME.fullmatch(name):
        raise CrossModelChallengeError("unsafe_runtime_filename")
    try:
        root = validate_model_cache_root(
            _RUNTIME_ROOT, repo_root=_REPOSITORY_ROOT
        )
    except ModelCacheBoundaryError as exc:
        raise CrossModelChallengeError(
            "runtime_directory_boundary_rejected"
        ) from exc
    lexical_candidate = root / name
    if lexical_candidate.exists() and lexical_candidate.is_symlink():
        raise CrossModelChallengeError("runtime_file_symlink_rejected")
    candidate = lexical_candidate.resolve()
    if candidate.parent != root:
        raise CrossModelChallengeError("runtime_file_outside_boundary")
    return candidate


def _write_text(path: Path, value: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=".cross-model-",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    _write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _fixtures() -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        _load_json(_MODEL_FIXTURE, maximum_bytes=100_000),
        _load_json(_RUBRIC_FIXTURE, maximum_bytes=100_000),
    )


def _export(variants: tuple[str, ...]) -> dict[str, Any]:
    model_fixture, rubric_fixture = _fixtures()
    written: list[str] = []
    for variant in variants:
        challenge = build_cross_model_challenge(
            model_fixture, rubric_fixture, variant=variant
        )
        challenge_name = f"{variant}.challenge.json"
        schema_name = f"{variant}.response.schema.json"
        prompt_name = f"{variant}.prompt.txt"
        _write_json(_runtime_file(challenge_name), challenge)
        _write_json(
            _runtime_file(schema_name), cross_model_response_schema(challenge)
        )
        _write_text(
            _runtime_file(prompt_name), render_cross_model_prompt(challenge)
        )
        written.extend((challenge_name, schema_name, prompt_name))
    return {
        "challenge_id": CROSS_MODEL_CHALLENGE_ID,
        "synthetic_only": True,
        "runtime_directory": "runtime/model-eval/cross-model-v1",
        "files": written,
    }


def _score(model_id: str, variant: str, response_name: str) -> dict[str, Any]:
    model_fixture, rubric_fixture = _fixtures()
    challenge = _load_json(
        _runtime_file(f"{variant}.challenge.json"), maximum_bytes=200_000
    )
    response = _load_json(_runtime_file(response_name), maximum_bytes=500_000)
    report = score_cross_model_response(
        model_fixture,
        rubric_fixture,
        challenge,
        response,
        model_id=model_id,
    )
    safe_model = re.sub(r"[^A-Za-z0-9._-]+", "-", model_id).strip("-")
    report_name = f"{safe_model}.{variant}.report.json"
    _write_json(_runtime_file(report_name), report)
    return {**report, "report_file": report_name}


def _stability(
    model_id: str, response_a_name: str, response_b_name: str
) -> dict[str, Any]:
    challenge_a = _load_json(
        _runtime_file("order-a.challenge.json"), maximum_bytes=200_000
    )
    challenge_b = _load_json(
        _runtime_file("order-b.challenge.json"), maximum_bytes=200_000
    )
    response_a = _load_json(_runtime_file(response_a_name), maximum_bytes=500_000)
    response_b = _load_json(_runtime_file(response_b_name), maximum_bytes=500_000)
    report = compare_cross_model_response_stability(
        challenge_a,
        response_a,
        challenge_b,
        response_b,
        model_id=model_id,
    )
    safe_model = re.sub(r"[^A-Za-z0-9._-]+", "-", model_id).strip("-")
    report_name = f"{safe_model}.stability.report.json"
    _write_json(_runtime_file(report_name), report)
    return {**report, "report_file": report_name}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export or score the fixed fictional cross-model challenge."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export = subparsers.add_parser("export")
    export.add_argument(
        "--variant", choices=("all", *CROSS_MODEL_VARIANTS), default="all"
    )

    score = subparsers.add_parser("score")
    score.add_argument("--model-id", required=True)
    score.add_argument("--variant", choices=CROSS_MODEL_VARIANTS, required=True)
    score.add_argument("--response", required=True, help="Runtime filename only")

    stability = subparsers.add_parser("stability")
    stability.add_argument("--model-id", required=True)
    stability.add_argument("--response-a", required=True, help="Runtime filename")
    stability.add_argument("--response-b", required=True, help="Runtime filename")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "export":
            variants = (
                CROSS_MODEL_VARIANTS
                if args.variant == "all"
                else (args.variant,)
            )
            result = _export(variants)
        elif args.command == "score":
            result = _score(args.model_id, args.variant, args.response)
        else:
            result = _stability(
                args.model_id, args.response_a, args.response_b
            )
    except CrossModelChallengeError as exc:
        print(json.dumps({"status": "rejected", "reason": str(exc)}))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
