"""Release dependency policy for the optional local-model runtime."""

from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_model_extra_stays_on_the_reviewed_torch_minor() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    models = tuple(project["project"]["optional-dependencies"]["models"])
    assert "torch>=2.8,<2.9" in models
    assert "transformers>=4.57.6,<5" in models
    assert "bitsandbytes>=0.50.1,<1" in models


def test_universal_lock_never_promotes_the_cuda_13_stack() -> None:
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "torch"\nversion = "2.8.0"' in lock
    assert "-cu13" not in lock
    assert "cuda-toolkit" not in lock
    assert 'name = "stripe"' not in lock
