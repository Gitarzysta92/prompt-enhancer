"""Build the one reviewed proxy-tools source input without a resolver."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from prompt_enhancer.infrastructure.proxy_tools_wheel_preparation import (  # noqa: E402
    prepare_proxy_tools_wheel,
)


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        del message
        raise ValueError("invalid command line")


def main(argv: list[str] | None = None) -> int:
    try:
        parser = _Parser(
            description="Prepare the reviewed proxy-tools wheel from local inputs.",
            allow_abbrev=False,
        )
        parser.add_argument("--source-archive", required=True, type=Path)
        parser.add_argument("--python-executable", required=True, type=Path)
        parser.add_argument("--python-sha256", required=True)
        parser.add_argument("--python-size-bytes", required=True, type=int)
        parser.add_argument("--python-version", required=True)
        parser.add_argument("--setuptools-wheel", required=True, type=Path)
        parser.add_argument("--destination", required=True, type=Path)
        arguments = parser.parse_args(argv)
        result = prepare_proxy_tools_wheel(
            source_archive=arguments.source_archive,
            python_executable=arguments.python_executable,
            python_sha256=arguments.python_sha256,
            python_size_bytes=arguments.python_size_bytes,
            python_version=arguments.python_version,
            setuptools_wheel=arguments.setuptools_wheel,
            destination=arguments.destination,
        )
        output = json.dumps({
            "filename": result.filename,
            "license_discrepancy_review_required": result.license_discrepancy_review_required,
            "network_isolation_not_proven": result.network_isolation_not_proven,
            "python_sha256": result.python_sha256,
            "python_size_bytes": result.python_size_bytes,
            "python_version": result.python_version,
            "python_runtime_dependencies_not_pinned": result.python_runtime_dependencies_not_pinned,
            "setuptools_sha256": result.setuptools_sha256,
            "setuptools_size_bytes": result.setuptools_size_bytes,
            "setuptools_version": result.setuptools_version,
            "sha256": result.sha256,
            "size_bytes": result.size_bytes,
            "source_date_epoch": result.source_date_epoch,
            "source_sha256": result.source_sha256,
            "source_size_bytes": result.source_size_bytes,
        }, sort_keys=True, separators=(",", ":"))
    except Exception:
        print("proxy_tools_wheel_preparation_failed", file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
