"""Content-free container readiness using the bundled Python runtime."""
from __future__ import annotations

import json
import os
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def main() -> int:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open("http://127.0.0.1:8080/health", timeout=3) as response:
            body = response.read(4097)
            revision = os.environ.get("PROMPT_ENHANCER_REVISION", "")
            ready = (
                response.status == 200 and len(body) <= 4096 and bool(revision)
                and response.headers.get("X-Prompt-Enhancer-Revision") == revision
                and json.loads(body).get("status") == "ok"
            )
        return 0 if ready else 1
    except (OSError, ValueError, TypeError, AttributeError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
