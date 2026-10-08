"""Fictional MCP stdio peers for guarded-host integration tests only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time


def _write_message(value: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _spawn_children(
    pid_file: str | None,
    child_count: int,
    child_pids_file: str | None,
) -> None:
    if pid_file is None and child_count <= 0:
        return
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    requested = max(1 if pid_file is not None else 0, min(max(child_count, 0), 64))
    process_ids: list[int] = []
    for _ in range(requested):
        try:
            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
            )
        except OSError:
            break
        process_ids.append(child.pid)
    if pid_file is not None and process_ids:
        Path(pid_file).write_text(str(process_ids[0]), encoding="ascii")
    if child_pids_file is not None:
        Path(child_pids_file).write_text(
            "\n".join(str(item) for item in process_ids),
            encoding="ascii",
        )


def _run_legacy(call_marker: str | None) -> None:
    for line in sys.stdin:
        request = json.loads(line)
        method = request.get("method")
        identifier = request.get("id")
        if method == "notifications/initialized":
            continue
        if method == "server/discover":
            _write_message({
                "jsonrpc": "2.0",
                "id": identifier,
                "error": {"code": -32601, "message": "Method not found"},
            })
        elif method == "initialize":
            _write_message({
                "jsonrpc": "2.0",
                "id": identifier,
                "result": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "synthetic-legacy", "version": "1"},
                },
            })
        elif method == "tools/list":
            _write_message({
                "jsonrpc": "2.0",
                "id": identifier,
                "result": {
                    "tools": [{
                        "name": "synthetic_lookup",
                        "description": "Fictional lookup for transport validation.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                        },
                    }],
                },
            })
        elif method == "tools/call":
            if call_marker is not None:
                Path(call_marker).write_text("called", encoding="ascii")
            _write_message({
                "jsonrpc": "2.0",
                "id": identifier,
                "error": {"code": -32601, "message": "Tool calls are disabled"},
            })


def _run_modern(call_marker: str | None) -> None:
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("synthetic-modern")

    @server.tool(name="synthetic_lookup")
    def lookup(query: str) -> str:
        if call_marker is not None:
            Path(call_marker).write_text("called", encoding="ascii")
        return f"fictional result for {query}"

    server.run()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=("modern", "legacy", "hang", "malformed", "oversized", "crash"),
    )
    parser.add_argument("--call-marker")
    parser.add_argument("--child-pid-file")
    parser.add_argument("--child-count", type=int, default=0)
    parser.add_argument("--child-pids-file")
    parser.add_argument("--stderr-bytes", type=int, default=0)
    options = parser.parse_args()

    _spawn_children(
        options.child_pid_file,
        options.child_count,
        options.child_pids_file,
    )
    if options.stderr_bytes:
        sys.stderr.write("x" * min(max(options.stderr_bytes, 0), 4 * 1024 * 1024))
        sys.stderr.flush()
    if options.mode == "hang":
        time.sleep(60)
    elif options.mode == "malformed":
        sys.stdout.write("not-json\n")
        sys.stdout.flush()
        time.sleep(60)
    elif options.mode == "oversized":
        sys.stdout.write("x" * (2 * 1024 * 1024 + 1))
        sys.stdout.flush()
        time.sleep(60)
    elif options.mode == "crash":
        raise SystemExit(7)
    elif options.mode == "legacy":
        _run_legacy(options.call_marker)
    else:
        _run_modern(options.call_marker)


if __name__ == "__main__":
    main()
