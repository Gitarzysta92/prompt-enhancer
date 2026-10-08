"""Produce external partial frontend evidence; no rendering or legal conclusion."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from prompt_enhancer.infrastructure.frontend_notice_inventory import prepare, FrontendNoticeError


ERROR_CODES = frozenset({
    "frontend_notice_cli_invalid",
    "frontend_notice_dependency_changed",
    "frontend_notice_evidence_oversize",
    "frontend_notice_input_changed",
    "frontend_notice_input_invalid",
    "frontend_notice_output_changed",
    "frontend_notice_output_failed",
    "frontend_notice_report_oversize",
})
FALLBACK_ERROR_CODE = "frontend_notice_failed"


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise FrontendNoticeError("frontend_notice_cli_invalid")


def main(argv=None):
    try:
        parser = Parser(allow_abbrev=False)
        for name in ("dependencies-root", "dashboard-root", "output"):
            parser.add_argument("--" + name, required=True, type=Path)
        for name in ("dependency-provenance-sha256", "dashboard-manifest-sha256", "graph-sha256"):
            parser.add_argument("--" + name, required=True)
        print(json.dumps(prepare(**vars(parser.parse_args(argv))), sort_keys=True))
        return 0
    except FrontendNoticeError as error:
        code = str(error)
        print(json.dumps({"passed": False, "error_code": code if code in ERROR_CODES else FALLBACK_ERROR_CODE}))
        return 1
    except Exception:
        print(json.dumps({"passed": False, "error_code": FALLBACK_ERROR_CODE}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
