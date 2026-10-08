"""Generate the public, synthetic local-model compatibility matrix."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_ROOT = _REPOSITORY_ROOT / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from prompt_enhancer.application.local_models import (  # noqa: E402
    LOCAL_MODEL_COMPATIBILITY_CONTRACT_VERSION,
    LOCAL_MODEL_RUNTIME_ADAPTER_VERSION,
    LocalModelCompatibility,
    LocalModelCompatibilityReason,
    LocalModelCompatibilityState,
)


def _case(
    state: LocalModelCompatibilityState,
    reason: LocalModelCompatibilityReason,
    execution: str,
) -> LocalModelCompatibility:
    return LocalModelCompatibility(
        alias="synthetic-model",
        state=state,
        reason_code=reason,
        architecture="synthetic-architecture",
        tokenizer_model="synthetic-tokenizer",
        training_context_size=32768,
        metadata_reader_version="gguf-metadata.v1",
        artifact_identity_state="unverified",
        execution_state=execution,
        context_counter_state="not_run",
    )


CASES = (
    ("Registered GGUF; no execution yet", _case(
        LocalModelCompatibilityState.UNKNOWN,
        LocalModelCompatibilityReason.MODEL_NOT_EXECUTED,
        "not_run",
    ), "Activate and pass the exact live text probe."),
    ("llama.cpp binary unavailable", _case(
        LocalModelCompatibilityState.UNKNOWN,
        LocalModelCompatibilityReason.RUNTIME_UNAVAILABLE,
        "not_run",
    ), "Install or select a documented llama-server binary."),
    ("Exact artifact passed live text probe", _case(
        LocalModelCompatibilityState.SUPPORTED,
        LocalModelCompatibilityReason.LIVE_TEXT_PROBE_VERIFIED,
        "verified",
    ), "Usable for the capabilities separately verified by the live probe."),
    ("Exact artifact failed live text probe", _case(
        LocalModelCompatibilityState.UNSUPPORTED,
        LocalModelCompatibilityReason.LIVE_TEXT_PROBE_FAILED,
        "failed",
    ), "Do not advertise it as usable with this adapter/runtime."),
    ("Registered artifact is missing", _case(
        LocalModelCompatibilityState.UNSUPPORTED,
        LocalModelCompatibilityReason.ARTIFACT_MISSING,
        "failed",
    ), "Restore the exact artifact or remove the stale registry row."),
)


def build_matrix() -> str:
    rows = "\n".join(
        f"| {scenario} | `{receipt.state}` | `{receipt.reason_code}` | {next_step} |"
        for scenario, receipt, next_step in CASES
    )
    return f"""# Local model compatibility matrix

Generated from `{LOCAL_MODEL_COMPATIBILITY_CONTRACT_VERSION}` using adapter
`{LOCAL_MODEL_RUNTIME_ADAPTER_VERSION}`. Every row uses synthetic identity data;
this document contains no installed model, path, account, prompt, or transcript data.

| Contract scenario | State | Closed reason | Meaning / next step |
|---|---|---|---|
{rows}

## Admission rules

- Catalog discovery and GGUF metadata are identity evidence, not executable compatibility.
- `supported` requires a successful live text request for the exact currently served alias.
- Architecture, tokenizer, training context, runtime version, model digest, runtime-binary digest, licence, and source revision remain `unknown` when unavailable; names never fill them in.
- Vision, audio, tools, structured output, and recording are admitted separately by live capability probes.
- Exact context admission uses llama.cpp's chat-template-aware [`POST /v1/chat/completions/input_tokens`](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md). If that interface is absent or malformed, input use remains unknown; the app does not substitute a character estimate or another tokenizer.
- On a measured overflow, Agent removes only whole older conversation units and recounts. System instructions, tool definitions, and the current request are protected; if those cannot fit, inference is refused.

The runtime adapter follows the official [llama.cpp server interface](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md). Additional formats or runtime families must receive a new versioned adapter and contract row before they can be advertised.
"""


def export_matrix(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_matrix(), encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/local-model-compatibility-matrix.md"),
    )
    export_matrix(parser.parse_args().output)


if __name__ == "__main__":
    main()
