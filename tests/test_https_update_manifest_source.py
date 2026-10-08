from __future__ import annotations

import base64

import httpx
import pytest

from prompt_enhancer.application.updates.contracts import (
    MAX_UPDATE_MANIFEST_BYTES,
    UpdateChannel,
)
from prompt_enhancer.infrastructure.updates import (
    HttpsUpdateManifestSource,
    UpdateManifestSourceError,
)


URL = "https://updates.example.invalid/prompt-enhancer/stable/manifest-v1.json"
MEDIA_TYPE = "application/vnd.prompt-enhancer.update-manifest.v1+json"
SIGNATURE = b"s" * 64


def _response(
    body: bytes = b"{}",
    *,
    status_code: int = 200,
    extra_headers: dict[str, str] | None = None,
    streamed: bool = False,
) -> httpx.Response:
    headers = {
        "Content-Type": MEDIA_TYPE,
        "X-Prompt-Enhancer-Key-Id": "release-2040",
        "X-Prompt-Enhancer-Manifest-Signature": base64.b64encode(SIGNATURE).decode(),
        **(extra_headers or {}),
    }
    if streamed or "Content-Encoding" in headers:
        return httpx.Response(
            status_code,
            headers=headers,
            stream=httpx.ByteStream(body),
        )
    return httpx.Response(status_code, headers=headers, content=body)


def test_source_fetches_only_the_exact_channel_url_without_ambient_authority() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response()

    source = HttpsUpdateManifestSource(
        manifest_urls={UpdateChannel.STABLE: URL},
        transport=httpx.MockTransport(handler),
    )
    assert requests == []

    envelope = source.fetch_manifest(channel=UpdateChannel.STABLE)

    assert envelope.raw_manifest == b"{}"
    assert envelope.signature == SIGNATURE
    assert envelope.key_id == "release-2040"
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url) == URL
    assert request.headers["accept"] == MEDIA_TYPE
    assert request.headers["cache-control"] == "no-cache"
    for forbidden in ("authorization", "cookie", "referer", "x-api-key"):
        assert forbidden not in request.headers


@pytest.mark.parametrize(
    "url",
    [
        "http://updates.example.invalid/manifest.json",
        "https://updates.example.invalid:8443/manifest.json",
        "https://person:secret@updates.example.invalid/manifest.json",
        "https://updates.example.invalid/manifest.json?channel=stable",
        "https://updates.example.invalid/manifest.json#latest",
        "https://127.0.0.1/manifest.json",
        "https://localhost/manifest.json",
        "https://single-label/manifest.json",
        "https://updates.example.invalid",
    ],
)
def test_source_rejects_non_exact_or_non_public_https_urls(url: str) -> None:
    with pytest.raises(ValueError, match="update manifest URL is invalid"):
        HttpsUpdateManifestSource(
            manifest_urls={UpdateChannel.STABLE: url},
            transport=httpx.MockTransport(lambda _request: _response()),
        )


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (_response(status_code=302, extra_headers={"Location": "https://other.example.invalid/manifest.json"}), "update_manifest_http_rejected"),
        (_response(extra_headers={"Content-Type": "application/json"}), "update_manifest_media_type_invalid"),
        (_response(extra_headers={"Content-Encoding": "gzip"}), "update_manifest_encoding_invalid"),
        (_response(extra_headers={"Content-Length": "999"}), "update_manifest_length_invalid"),
        (_response(extra_headers={"X-Prompt-Enhancer-Key-Id": ""}), "update_manifest_headers_invalid"),
        (_response(extra_headers={"X-Prompt-Enhancer-Manifest-Signature": "%%%"}), "update_manifest_signature_invalid"),
    ],
)
def test_source_rejects_redirects_and_malformed_metadata(
    response: httpx.Response,
    reason: str,
) -> None:
    source = HttpsUpdateManifestSource(
        manifest_urls={UpdateChannel.STABLE: URL},
        transport=httpx.MockTransport(lambda _request: response),
    )

    with pytest.raises(UpdateManifestSourceError) as captured:
        source.fetch_manifest(channel=UpdateChannel.STABLE)

    assert captured.value.reason_code == reason
    assert str(captured.value) == reason
    assert URL not in str(captured.value)


def test_source_bounds_streamed_response_bytes_before_verification() -> None:
    source = HttpsUpdateManifestSource(
        manifest_urls={UpdateChannel.STABLE: URL},
        transport=httpx.MockTransport(
            lambda _request: _response(
                b"x" * (MAX_UPDATE_MANIFEST_BYTES + 1), streamed=True
            )
        ),
    )

    with pytest.raises(UpdateManifestSourceError) as captured:
        source.fetch_manifest(channel=UpdateChannel.STABLE)

    assert captured.value.reason_code == "update_manifest_too_large"


def test_unconfigured_channel_does_not_open_transport() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response()

    source = HttpsUpdateManifestSource(
        manifest_urls={UpdateChannel.STABLE: URL},
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(UpdateManifestSourceError) as captured:
        source.fetch_manifest(channel=UpdateChannel.BETA)

    assert captured.value.reason_code == "update_channel_unconfigured"
    assert calls == 0
