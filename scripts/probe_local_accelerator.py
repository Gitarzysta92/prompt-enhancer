"""Development wrapper for the package-owned accelerator probe."""

from __future__ import annotations

from pathlib import Path
import sys


_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from prompt_enhancer._resources.probes.probe_local_accelerator import main


if __name__ == "__main__":
    raise SystemExit(main())
