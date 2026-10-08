"""Single-owner hosted gateway; provider homes and native authority stay absent."""

from __future__ import annotations

import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
from typing import Mapping


_HOST = re.compile(r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}\Z")
_USER = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_HASH = re.compile(r"\$2[aby]\$(?:1[0-6])\$[./A-Za-z0-9]{53}\Z")
_REVISION = re.compile(r"(?:[a-f0-9]{40}|development)\Z")


def gateway_environment(environment: Mapping[str, str]) -> dict[str, str]:
    values = {
        "PROMPT_ENHANCER_PUBLIC_HOST": environment.get("PROMPT_ENHANCER_PUBLIC_HOST", ""),
        "PROMPT_ENHANCER_WEB_USER": environment.get("PROMPT_ENHANCER_WEB_USER", ""),
        "PROMPT_ENHANCER_WEB_PASSWORD_HASH": environment.get("PROMPT_ENHANCER_WEB_PASSWORD_HASH", ""),
        "PROMPT_ENHANCER_REVISION": environment.get("PROMPT_ENHANCER_REVISION", "development"),
    }
    for name, pattern in zip(values, (_HOST, _USER, _HASH, _REVISION), strict=True):
        if pattern.fullmatch(values[name]) is None:
            # Never echo configuration or a credential on validation failure.
            raise ValueError("hosted_configuration_invalid")
    return {
        "PATH": os.defpath,
        "XDG_CONFIG_HOME": "/tmp/prompt-enhancer-gateway/config",
        "XDG_DATA_HOME": "/tmp/prompt-enhancer-gateway/data",
        **values,
    }


def backend_environment() -> dict[str, str]:
    return {
        "PATH": "/app/.venv/bin:/usr/local/bin:/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "PROMPT_ENHANCER_HOME": "/data/prompt-enhancer",
        "PROMPT_ENHANCER_HOST": "127.0.0.1",
        "PROMPT_ENHANCER_PORT": "8765",
        "PROMPT_ENHANCER_CLAUDE_HOME": "/tmp/disabled-provider",
        "PROMPT_ENHANCER_SESSION_READER": "disabled",
        "HF_HUB_OFFLINE": "1",
    }


def stop_children(children: list[subprocess.Popen]) -> None:
    for child in reversed(children):
        if child.poll() is None:
            child.terminate()
    deadline = time.monotonic() + 20
    for child in reversed(children):
        try:
            child.wait(timeout=max(0.1, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


def main() -> int:
    children: list[subprocess.Popen] = []
    stop = threading.Event()
    try:
        gateway_env = gateway_environment(os.environ)
        os.umask(0o077)
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda *_: stop.set())
        config = Path(__file__).with_name("Caddyfile")
        # A malformed gateway must never leave a running backend behind.
        subprocess.run(
            ["/usr/local/bin/caddy", "validate", "--config", str(config), "--adapter", "caddyfile"],
            env=gateway_env, check=True, timeout=15,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        for command, environment in (
            ([sys.executable, "-m", "prompt_enhancer", "serve"], backend_environment()),
            (["/usr/local/bin/caddy", "run", "--config", str(config), "--adapter", "caddyfile"], gateway_env),
        ):
            children.append(subprocess.Popen(
                command, env=environment,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ))
        print("Hosted services started; health check determines readiness.", flush=True)
        while not stop.wait(0.25):
            if any(child.poll() is not None for child in children):
                raise RuntimeError("hosted_child_exited")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        print("Hosted startup or runtime failed; inspect configuration and health.", file=sys.stderr)
        return 1
    finally:
        stop_children(children)


if __name__ == "__main__":
    raise SystemExit(main())
