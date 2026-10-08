"""Report offline Windows dependency preparation; it never fetches or builds."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from prompt_enhancer.infrastructure.desktop_dependency_export import export_windows_desktop_requirements  # noqa: E402
from prompt_enhancer.infrastructure.windows_dependency_preparation import (  # noqa: E402
    prepare_windows_dependencies,
    report_json,
)
from prompt_enhancer.infrastructure.windows_wheel_inventory import WindowsWheelTarget  # noqa: E402


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise ValueError("invalid command line")


def main(argv: list[str] | None = None) -> int:
    try:
        parser = _Parser(allow_abbrev=False)
        parser.add_argument("--python-full-version", required=True)
        parser.add_argument("--architecture", required=True, choices=("amd64", "arm64"))
        parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
        parser.add_argument("--proxy-tools-wheel", type=Path)
        parser.add_argument("--proxy-tools-provenance", type=Path)
        arguments = parser.parse_args(argv)
        export = export_windows_desktop_requirements(repository_root=arguments.repository_root)
        report = prepare_windows_dependencies(
            export=export, lockfile=arguments.repository_root / "uv.lock",
            target=WindowsWheelTarget(arguments.python_full_version, arguments.architecture),
            proxy_tools_wheel=arguments.proxy_tools_wheel,
            proxy_tools_provenance=arguments.proxy_tools_provenance,
        )
        output = report_json(report)
    except Exception:
        print("windows_dependency_preparation_failed", file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
