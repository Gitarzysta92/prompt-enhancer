"""Private transport seam used to test the adapter without launching Codex."""

from __future__ import annotations

from typing import Protocol


JsonObject = dict[str, object]


class InternalJsonRpcTransport(Protocol):
    """Generic JSON-RPC primitives kept behind the allowlisted client facade."""

    def _start(self) -> None: ...

    def _request(self, method: str, params: JsonObject) -> object: ...

    def _notify(self, method: str, params: JsonObject | None = None) -> None: ...

    def close(self) -> None: ...
