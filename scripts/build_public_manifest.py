"""Generate or compare deterministic public manifests for staged artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

_SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(_SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SOURCE_ROOT))

from prompt_enhancer.application.build_evidence.manifest import (
    build_manifest,
    canonical_json,
    compare_manifests,
)


def _named_values(values: list[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        name, separator, item = value.partition("=")
        if not separator or not name or not item or name in parsed:
            raise ValueError("invalid named public build value")
        parsed[name] = item
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate content-only evidence for a public staging tree."
    )
    parser.add_argument("staging_root", type=Path)
    parser.add_argument("--compare-root", type=Path)
    parser.add_argument("--git-revision", required=True)
    parser.add_argument("--tool-version", action="append", default=[])
    parser.add_argument("--lockfile-hash", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        tool_versions = _named_values(arguments.tool_version)
        lockfile_hashes = _named_values(arguments.lockfile_hash)
        first = build_manifest(
            arguments.staging_root,
            git_revision=arguments.git_revision,
            tool_versions=tool_versions,
            lockfile_hashes=lockfile_hashes,
        )
        if arguments.compare_root is None:
            payload = canonical_json(first)
        else:
            second = build_manifest(
                arguments.compare_root,
                git_revision=arguments.git_revision,
                tool_versions=tool_versions,
                lockfile_hashes=lockfile_hashes,
            )
            payload = canonical_json(compare_manifests(first, second))
    except Exception:
        print("build_manifest_failed", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
