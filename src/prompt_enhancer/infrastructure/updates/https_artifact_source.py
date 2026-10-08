"""Pinned, bounded HTTPS artifact stream; it has no install capability."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from urllib.parse import urlsplit
import re

import httpx
from time import monotonic

from ...application.updates.contracts import UpdateChannel
from .https_manifest_source import UpdateManifestSourceError, _validate_manifest_url

_ACCEPT = "application/vnd.prompt-enhancer.application.v1"
_MAX_CHUNK_BYTES = 64 * 1024
_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class HttpsUpdateArtifactSource:
    """Uses only immutable package-owned URL templates for signed releases."""

    def __init__(self,
                 *,
                 artifact_url_templates: Mapping[UpdateChannel, str],
                 transport: httpx.BaseTransport | None = None) -> None:
        if not artifact_url_templates or len(artifact_url_templates) > len(
                UpdateChannel):
            raise ValueError("update artifact map is invalid")
        self._templates = {}
        for channel, template in artifact_url_templates.items():
            if not isinstance(channel, UpdateChannel) or template.count(
                    "{version}") != 1 or template.count(
                        "{sha256}") != 1 or template.count(
                            "{") != 2 or template.count("}") != 2:
                raise ValueError("update artifact template is invalid")
            sentinel = template.replace("{version}",
                                        "1.2.3").replace("{sha256}", "a" * 64)
            parsed_template = urlsplit(template)
            if ("{" in parsed_template.netloc or "}" in parsed_template.netloc
                    or "{version}" not in parsed_template.path
                    or "{sha256}" not in parsed_template.path):
                raise ValueError("update artifact template is invalid")
            _validate_manifest_url(sentinel)
            self._templates[channel] = template
        if UpdateChannel.STABLE not in self._templates:
            raise ValueError("update artifact map is invalid")
        self._transport = transport

    def iter_artifact(self, *, channel: UpdateChannel, release_version: str,
                      artifact_sha256: str,
                      artifact_size_bytes: int) -> Iterator[bytes]:
        if (not isinstance(release_version, str)
                or _VERSION.fullmatch(release_version) is None
                or not isinstance(artifact_sha256, str)
                or _SHA256.fullmatch(artifact_sha256) is None
                or not isinstance(artifact_size_bytes, int)
                or isinstance(artifact_size_bytes, bool)
                or artifact_size_bytes <= 0):
            raise UpdateManifestSourceError(
                "update_artifact_arguments_invalid")
        template = self._templates.get(channel)
        if template is None:
            raise UpdateManifestSourceError("update_artifact_unconfigured")
        url = template.replace("{version}", release_version).replace(
            "{sha256}", artifact_sha256)
        try:
            deadline = monotonic() + 30.0
            with httpx.Client(follow_redirects=False,
                              timeout=httpx.Timeout(30.0, connect=5.0),
                              transport=self._transport,
                              trust_env=False) as client:
                with client.stream("GET",
                                   url,
                                   headers={
                                       "Accept": _ACCEPT,
                                       "Accept-Encoding": "identity",
                                       "Cache-Control": "no-cache"
                                   }) as response:
                    if response.status_code != 200:
                        raise UpdateManifestSourceError(
                            "update_artifact_http_rejected")
                    if response.headers.get(
                            "Content-Encoding",
                            "identity").strip().lower() not in {
                                "", "identity"
                            }:
                        raise UpdateManifestSourceError(
                            "update_artifact_encoding_invalid")
                    length = response.headers.get("Content-Length")
                    if length is None:
                        raise UpdateManifestSourceError(
                            "update_artifact_length_missing")
                    try:
                        if int(length, 10) != artifact_size_bytes:
                            raise ValueError
                    except ValueError as error:
                        raise UpdateManifestSourceError(
                            "update_artifact_length_invalid") from error
                    received = 0
                    for chunk in response.iter_bytes(
                            chunk_size=_MAX_CHUNK_BYTES):
                        if monotonic() > deadline:
                            raise UpdateManifestSourceError(
                                "update_artifact_deadline_exceeded")
                        if chunk:
                            if len(chunk) > _MAX_CHUNK_BYTES:
                                raise UpdateManifestSourceError(
                                    "update_artifact_chunk_invalid")
                            received += len(chunk)
                            if received > artifact_size_bytes:
                                raise UpdateManifestSourceError(
                                    "update_artifact_oversize")
                            yield chunk
                    if received != artifact_size_bytes:
                        raise UpdateManifestSourceError(
                            "update_artifact_length_invalid")
        except UpdateManifestSourceError:
            raise
        except (httpx.HTTPError, OSError) as error:
            raise UpdateManifestSourceError(
                "update_artifact_fetch_failed") from error


__all__ = ("HttpsUpdateArtifactSource", )
