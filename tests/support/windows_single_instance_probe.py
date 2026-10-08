"""Content-free child probe for the Windows named-mutex contract."""

from __future__ import annotations

import json
import sys

from prompt_enhancer.infrastructure.windows_single_instance import (
    acquire_windows_instance,
)


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    lease = acquire_windows_instance(sys.argv[1])
    primary = lease is not None
    if lease is not None:
        lease.close()
    print(json.dumps({"contract": "windows-single-instance-probe.v1", "primary": primary}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
