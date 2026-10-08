"""Print lock-bound desktop requirements; no wheel build, install, or download."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_SOURCE_ROOT) not in sys.path: sys.path.insert(0, str(_SOURCE_ROOT))

from prompt_enhancer.infrastructure.desktop_dependency_export import export_windows_desktop_requirements


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # noqa: ARG002
        self.exit(2, "windows_desktop_export_failed\n")


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser(description="Export offline hashed desktop requirements.")
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args(argv)
    try:
        result = export_windows_desktop_requirements(repository_root=arguments.repository_root)
        sys.stdout.write(result.requirements)
        return 0
    except Exception:
        print("windows_desktop_export_failed", file=sys.stderr)
        return 2


if __name__ == "__main__": raise SystemExit(main())
