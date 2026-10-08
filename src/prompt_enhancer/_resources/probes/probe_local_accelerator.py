"""Emit a bounded, content-free local accelerator inventory.

This packaged child reads no caches, credentials, sessions, or device names.
The parent converts the bounded numeric response into coarse capability classes.
"""

from __future__ import annotations

import json


SCHEMA_VERSION = 1


def _unknown() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "cuda_state": "unknown",
        "cuda_total_memory_mib": None,
        "cuda_capability_major": None,
        "cuda_capability_minor": None,
        "mps_available": False,
    }


def probe() -> dict[str, object]:
    try:
        import torch

        cuda_available = bool(torch.cuda.is_available())
        mps_backend = getattr(torch.backends, "mps", None)
        mps_available = bool(mps_backend) and bool(mps_backend.is_available())
        if not cuda_available:
            return {
                "schema_version": SCHEMA_VERSION,
                "cuda_state": "unavailable",
                "cuda_total_memory_mib": None,
                "cuda_capability_major": None,
                "cuda_capability_minor": None,
                "mps_available": mps_available,
            }
        properties = torch.cuda.get_device_properties(0)
        major, minor = torch.cuda.get_device_capability(0)
        return {
            "schema_version": SCHEMA_VERSION,
            "cuda_state": "available",
            "cuda_total_memory_mib": int(properties.total_memory // (1024 * 1024)),
            "cuda_capability_major": int(major),
            "cuda_capability_minor": int(minor),
            "mps_available": mps_available,
        }
    except Exception:
        return _unknown()


def main() -> int:
    print(json.dumps(probe(), separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
