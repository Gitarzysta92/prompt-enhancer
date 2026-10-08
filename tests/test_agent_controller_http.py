"""The controller HTTP transport cannot redirect, proxy, or disclose its token."""

from __future__ import annotations

import json
from typing import Any

import pytest

from prompt_enhancer.application.agent_controller_client import AgentControllerError
from prompt_enhancer.infrastructure.agent_controller_http import (
    LoopbackAgentControllerTransport,
    _RejectRedirects,
)


TOKEN = "example_controller_transport_token_123456789"


class _Response:
    def __init__(
        self,
        payload: Any,
        *,
        url: str = "http://127.0.0.1:8765/v1/agent/orchestration",
        status: int = 200,
    ) -> None:
        self.status = status
        self.headers = {"Content-Type": "application/json"}
        self._body = json.dumps(payload).encode("utf-8")
        self._url = url

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self, _size: int) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url


class _Opener:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.requests = []
        self.timeouts: list[float] = []

    def open(self, request, *, timeout: float):  # noqa: ANN001
        self.requests.append(request)
        self.timeouts.append(timeout)
        return self.response


@pytest.mark.parametrize(
    "base_url",
    (
        "https://127.0.0.1:8765",
        "http://example.invalid:8765",
        "http://user:secret" + chr(64) + "127.0.0.1:8765",
        "http://127.0.0.1:8765/private",
        "http://127.0.0.1:8765?token=example",
    ),
)
def test_transport_rejects_every_non_exact_loopback_origin(base_url: str) -> None:
    with pytest.raises(AgentControllerError) as captured:
        LoopbackAgentControllerTransport(base_url, TOKEN)
    assert captured.value.code == "controller_base_url_invalid"
    assert TOKEN not in str(captured.value)


def test_transport_sends_secret_only_as_header_and_repr_is_redacted() -> None:
    opener = _Opener(_Response({"contract_version": "synthetic"}))
    transport = LoopbackAgentControllerTransport(
        "http://127.0.0.1:8765",
        TOKEN,
        timeout_seconds=3,
        opener=opener,  # type: ignore[arg-type]
    )
    response = transport.request(
        "GET",
        "/v1/agent/sessions/" + "a" * 32 + "/events",
        query={"after": 7, "include_archived": False},
    )

    assert response.status_code == 200
    assert len(opener.requests) == 1
    request = opener.requests[0]
    assert request.get_header("Authorization") == f"Bearer {TOKEN}"
    assert TOKEN not in request.full_url
    assert request.full_url.endswith("?after=7&include_archived=false")
    assert opener.timeouts == [3]
    assert TOKEN not in repr(transport)
    assert "<redacted>" in repr(transport)


def test_transport_refuses_traversal_and_cross_origin_final_response() -> None:
    opener = _Opener(
        _Response(
            {"status": "redirected"},
            url="http://127.0.0.2:8765/v1/agent/orchestration",
        )
    )
    transport = LoopbackAgentControllerTransport(
        "http://127.0.0.1:8765",
        TOKEN,
        opener=opener,  # type: ignore[arg-type]
    )
    with pytest.raises(AgentControllerError) as traversal:
        transport.request("GET", "/v1/agent/../private")
    assert traversal.value.code == "controller_path_invalid"
    assert opener.requests == []

    with pytest.raises(AgentControllerError) as redirected:
        transport.request("GET", "/v1/agent/orchestration")
    assert redirected.value.code == "controller_redirect_refused"
    assert TOKEN not in str(redirected.value)


def test_redirect_handler_never_constructs_a_follow_up_request() -> None:
    handler = _RejectRedirects()
    assert (
        handler.redirect_request(
            object(),
            object(),
            302,
            "Found",
            {"Location": "http://example.invalid"},
            "http://example.invalid",
        )
        is None
    )
