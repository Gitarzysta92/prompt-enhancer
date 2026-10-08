"""Print an offline Windows wheel inventory; it does not download wheels."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_SOURCE_ROOT) not in sys.path: sys.path.insert(0, str(_SOURCE_ROOT))

from prompt_enhancer.infrastructure.desktop_dependency_export import export_windows_desktop_requirements
from prompt_enhancer.infrastructure.windows_wheel_inventory import WindowsWheelTarget, plan_windows_wheels


class _SafeParser(argparse.ArgumentParser):
    def error(self, message: str) -> None: self.exit(2, "windows_wheel_inventory_failed\n")  # noqa: ARG002


def main(argv: list[str] | None = None) -> int:
    parser = _SafeParser()
    parser.add_argument("--python-full-version", required=True)
    parser.add_argument("--architecture", required=True, choices=("amd64", "arm64"))
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args(argv)
    try:
        export = export_windows_desktop_requirements(repository_root=arguments.repository_root)
        inventory = plan_windows_wheels(export=export, lockfile=arguments.repository_root / "uv.lock",
            target=WindowsWheelTarget(arguments.python_full_version, arguments.architecture))
        print(json.dumps({"target": asdict(inventory.target), "artifacts": [asdict(item) for item in inventory.artifacts], "export_fingerprint": inventory.export_fingerprint, "lockfile_sha256": inventory.lockfile_sha256, "pyproject_sha256": inventory.pyproject_sha256, "complete": True}, sort_keys=True, separators=(",", ":")))
        return 0
    except Exception:
        print("windows_wheel_inventory_failed", file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
