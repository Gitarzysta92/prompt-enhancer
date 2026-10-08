"""Evaluate deterministic text metrics against the checked-in synthetic corpus.

This command never reads provider state and accepts no external corpus path.  Its
report measures fixture agreement, not real English/Polish calibration.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_ROOT = _REPOSITORY_ROOT / "src"
_CORPUS = (
    _REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "synthetic"
    / "text_metrics"
    / "bilingual_cases.json"
)
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from prompt_enhancer.application.analysis.text_evaluation import (
    SyntheticTextEvaluationCase,
    evaluate_synthetic_text_cases,
)


def main() -> int:
    payload = json.loads(_CORPUS.read_text(encoding="utf-8"))
    cases = tuple(
        SyntheticTextEvaluationCase.model_validate(case)
        for case in payload["cases"]
    )
    report = evaluate_synthetic_text_cases(
        cases,
        corpus_schema_version=payload["corpus_schema_version"],
    )
    print(report.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
