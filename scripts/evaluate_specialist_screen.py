"""Screen two pinned specialists on the checked-in fictional EN/PL corpus.

No provider/session path or arbitrary corpus is accepted.  Public downloads are
disabled unless ``--download`` is passed, and the output is aggregate-only.
Synthetic results can never activate or promote a product estimator.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Sequence


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_ROOT = _REPOSITORY_ROOT / "src"
_CORPUS = (
    _REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "synthetic"
    / "specialists"
    / "scoped_nli_screen_v1.json"
)
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from prompt_enhancer.infrastructure.specialist_screen.evaluator import (
    SPECIALIST_CORPUS_SHA256,
    SPECIALIST_EVALUATOR_VERSION,
    SPECIALIST_METRIC_DEFINITION_VERSION,
    load_specialist_corpus,
    run_specialist_screen,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the synthetic-only scoped-NLI specialist pre-screen."
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda", "mps"),
        default="auto",
    )
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=0.7,
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Use the balanced eight-case fictional smoke subset.",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help=(
            "Explicitly prepare allowlisted public artifacts at immutable revisions; "
            "otherwise the run is network-closed."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    arguments = _parser().parse_args(argv)
    try:
        corpus = load_specialist_corpus(
            _CORPUS,
            expected_sha256=SPECIALIST_CORPUS_SHA256,
        )
        if arguments.smoke:
            corpus = corpus.smoke_subset()
        report = run_specialist_screen(
            corpus,
            allow_public_download=arguments.download,
            device=arguments.device,
            batch_size=arguments.batch_size,
            confidence_threshold=arguments.confidence_threshold,
        )
        completed = all(
            candidate["status"] == "completed"
            for candidate in report["candidates"]
        )
        report["status"] = "completed" if completed else "completed_with_unavailable"
        exit_code = 0 if completed else 2
    except Exception:
        report = {
            "contract": "synthetic-specialist-screen-v1",
            "synthetic_only": True,
            "screen_tier": "bounded_foundation_pre_screen",
            "evaluator_version": SPECIALIST_EVALUATOR_VERSION,
            "metric_definition_version": SPECIALIST_METRIC_DEFINITION_VERSION,
            "routing_mode": "oracle_fixture_compatibility_labels",
            "router_evaluated": False,
            "promotion_screen_minimum_case_count": 96,
            "promotion_screen_gate_met": False,
            "activation_allowed": False,
            "promotion_allowed": False,
            "status": "not_completed",
            "failure_code": "specialist_screen_failed",
        }
        exit_code = 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
