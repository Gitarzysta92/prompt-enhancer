"""Prepare an offline, reviewed application wheel."""
from __future__ import annotations
import argparse, json, sys
from dataclasses import asdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from prompt_enhancer.infrastructure.application_wheel_preparation import ApplicationWheelPreparationError, prepare_application_wheel

class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse normally echoes user-supplied paths and values to stderr.
        raise ApplicationWheelPreparationError("application_wheel_cli_invalid")

def main(argv: list[str] | None = None) -> int:
    try:
        p=Parser()
        for name in ("project-root","source-manifest","dashboard-manifest","python-executable","setuptools-wheel","destination"):
            p.add_argument("--"+name,type=Path,required=True)
        p.add_argument("--prepared-dashboard-root",type=Path)
        p.add_argument("--python-sha256",required=True)
        p.add_argument("--python-size-bytes",type=int,required=True)
        p.add_argument("--python-version",required=True)
        source_state=p.add_mutually_exclusive_group(required=True)
        source_state.add_argument("--source-tree-dirty",dest="source_tree_dirty",action="store_true")
        source_state.add_argument("--source-tree-clean",dest="source_tree_dirty",action="store_false")
        p.add_argument("--setuptools-sha256",required=True)
        p.add_argument("--setuptools-size-bytes",type=int,required=True)
        p.add_argument("--setuptools-version",required=True)
        a=p.parse_args(argv)
        result=prepare_application_wheel(project_root=a.project_root,source_manifest=a.source_manifest,dashboard_manifest=a.dashboard_manifest,source_tree_dirty=a.source_tree_dirty,python_executable=a.python_executable,python_sha256=a.python_sha256,python_size_bytes=a.python_size_bytes,python_version=a.python_version,setuptools_wheel=a.setuptools_wheel,setuptools_sha256=a.setuptools_sha256,setuptools_size_bytes=a.setuptools_size_bytes,setuptools_version=a.setuptools_version,destination=a.destination,prepared_dashboard_root=a.prepared_dashboard_root)
    except ApplicationWheelPreparationError:
        print("application_wheel_preparation_failed",file=sys.stderr);return 2
    print(json.dumps(asdict(result),sort_keys=True,separators=(",",":")));return 0
if __name__=="__main__":raise SystemExit(main())
