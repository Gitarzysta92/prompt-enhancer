from __future__ import annotations

import hashlib

import httpx
import pytest

from prompt_enhancer.application.updates import UpdateChannel
from prompt_enhancer.infrastructure.updates.https_artifact_source import (
    HttpsUpdateArtifactSource, )
from prompt_enhancer.infrastructure.updates.https_manifest_source import (
    UpdateManifestSourceError, )

VERSION = "9.8.7"
PAYLOAD = b"synthetic-artifact-bytes"
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
TEMPLATE = "https://updates.example.invalid/releases/{version}/{sha256}.bin"


def _source(handler) -> HttpsUpdateArtifactSource:
    return HttpsUpdateArtifactSource(
        artifact_url_templates={UpdateChannel.STABLE: TEMPLATE},
        transport=httpx.MockTransport(handler),
    )


def _read(source: HttpsUpdateArtifactSource) -> bytes:
    return b"".join(
        source.iter_artifact(
            channel=UpdateChannel.STABLE,
            release_version=VERSION,
            artifact_sha256=DIGEST,
            artifact_size_bytes=len(PAYLOAD),
        ))


def test_streams_only_the_template_path_for_a_future_signed_release() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200,
                              headers={"Content-Length": str(len(PAYLOAD))},
                              content=PAYLOAD)

    assert _read(_source(handler)) == PAYLOAD
    assert str(
        requests[0].url
    ) == f"https://updates.example.invalid/releases/{VERSION}/{DIGEST}.bin"
    assert requests[0].headers["accept-encoding"] == "identity"


@pytest.mark.parametrize(
    "response",
    [
        lambda: httpx.Response(
            302, headers={"Location": "https://example.invalid"}),
        lambda: httpx.Response(200,
                               headers={
                                   "Content-Encoding": "gzip",
                                   "Content-Length": str(len(PAYLOAD))
                               },
                               content=PAYLOAD),
        lambda: httpx.Response(200, stream=httpx.ByteStream(PAYLOAD)),
        lambda: httpx.Response(200,
                               headers=
                               {"Content-Length": str(len(PAYLOAD) + 1)},
                               content=PAYLOAD),
        lambda: httpx.Response(200,
                               headers={"Content-Length": str(len(PAYLOAD))},
                               content=PAYLOAD[:-1]),
    ],
)
def test_rejects_redirect_encoding_missing_or_mismatched_length(
        response) -> None:
    with pytest.raises(UpdateManifestSourceError):
        _read(_source(lambda _request: response()))


@pytest.mark.parametrize(
    "template",
    [
        "https://{version}.example.invalid/releases/{sha256}.bin",
        "https://updates.example.invalid/releases/{version}/artifact.bin",
        "https://updates.example.invalid/releases/{version}/{sha256}.bin?x=1",
        "https://user:pass@updates.example.invalid/releases/{version}/{sha256}.bin",
        "https://updates.example.invalid/releases/{version}/{sha256}/{unknown}.bin",
    ],
)
def test_rejects_unsafe_or_unknown_template_fields(template: str) -> None:
    with pytest.raises(ValueError):
        HttpsUpdateArtifactSource(
            artifact_url_templates={UpdateChannel.STABLE: template})


class _ClosingStream(httpx.SyncByteStream):

    def __init__(self) -> None:
        self.closed = False

    def __iter__(self):
        yield PAYLOAD[:5]
        yield PAYLOAD[5:]

    def close(self) -> None:
        self.closed = True


def test_closing_the_source_iterator_closes_the_http_stream() -> None:
    stream = _ClosingStream()
    source = _source(lambda _request: httpx.Response(
        200,
        headers={"Content-Length": str(len(PAYLOAD))},
        stream=stream,
    ))
    iterator = source.iter_artifact(
        channel=UpdateChannel.STABLE,
        release_version=VERSION,
        artifact_sha256=DIGEST,
        artifact_size_bytes=len(PAYLOAD),
    )
    next(iterator)
    iterator.close()
    assert stream.closed is True


def test_rejects_a_stream_that_exceeds_the_signed_size() -> None:
    source = _source(lambda _request: httpx.Response(
        200,
        headers={"Content-Length": str(len(PAYLOAD))},
        stream=httpx.ByteStream(PAYLOAD + b"x"),
    ))
    with pytest.raises(UpdateManifestSourceError):
        _read(source)


def test_rejects_a_stream_that_exceeds_the_total_deadline(monkeypatch) -> None:
    moments = iter((0.0, 31.0))
    monkeypatch.setattr(
        "prompt_enhancer.infrastructure.updates.https_artifact_source.monotonic",
        lambda: next(moments),
    )
    with pytest.raises(UpdateManifestSourceError):
        _read(
            _source(lambda _request: httpx.Response(
                200,
                headers={"Content-Length": str(len(PAYLOAD))},
                stream=httpx.ByteStream(PAYLOAD),
            )))


@pytest.mark.parametrize(
    ("version", "digest"),
    [
        ("9.8", DIGEST),
        ("09.8.7", DIGEST),
        (VERSION, "A" * 64),
        (VERSION, "g" * 64),
    ],
)
def test_rejects_bad_signed_release_arguments_before_transport(
    version: str,
    digest: str,
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    source = _source(handler)
    with pytest.raises(UpdateManifestSourceError):
        list(
            source.iter_artifact(
                channel=UpdateChannel.STABLE,
                release_version=version,
                artifact_sha256=digest,
                artifact_size_bytes=len(PAYLOAD),
            ))
    assert calls == 0
