"""Private-stdin local model runner; stdout contains scores and provenance only."""

from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prompt_enhancer.infrastructure.text_models.session_links import (  # noqa: E402
    MAX_SESSION_LINK_STDIN_BYTES,
    execute_session_link_payload,
)


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_SESSION_LINK_STDIN_BYTES + 1)
    if len(raw) > MAX_SESSION_LINK_STDIN_BYTES:
        return 2
    try:
        payload = json.loads(raw.decode("utf-8"))
        result = execute_session_link_payload(payload)
    except Exception:
        return 2
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
