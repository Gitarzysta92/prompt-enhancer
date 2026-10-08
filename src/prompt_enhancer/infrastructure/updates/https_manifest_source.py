"""Bounded, no-proxy HTTPS source for an explicitly requested update check."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
import ipaddress
from urllib.parse import urlsplit

import httpx

from ...application.updates.contracts import (
    MAX_UPDATE_MANIFEST_BYTES,
    MAX_UPDATE_SIGNATURE_BYTES,
    UpdateChannel,
)
from ...application.updates.ports import SignedUpdateManifestEnvelope


_KEY_ID_HEADER = "X-Prompt-Enhancer-Key-Id"
_SIGNATURE_HEADER = "X-Prompt-Enhancer-Manifest-Signature"
_ACCEPT = "application/vnd.prompt-enhancer.update-manifest.v1+json"


class UpdateManifestSourceError(RuntimeError):
    """Content-free source failure consumed by the update coordinator."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _validate_manifest_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2_048:
        raise ValueError("update manifest URL is invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError("update manifest URL is invalid") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
        or "\\" in parsed.path
    ):
        raise ValueError("update manifest URL is invalid")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or not hostname or "." not in hostname:
        raise ValueError("update manifest URL is invalid")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise ValueError("update manifest URL is invalid")
    return value


class HttpsUpdateManifestSource:
    """Fetch one exact channel URL without credentials, redirects, or proxies."""

    def __init__(
        self,
        *,
        manifest_urls: Mapping[UpdateChannel, str],
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not manifest_urls or len(manifest_urls) > len(UpdateChannel):
            raise ValueError("update manifest channel map is invalid")
        self._manifest_urls = {
            channel: _validate_manifest_url(url)
            for channel, url in manifest_urls.items()
        }
        if any(not isinstance(channel, UpdateChannel) for channel in self._manifest_urls):
            raise ValueError("update manifest channel map is invalid")
        self._transport = transport

    def fetch_manifest(self, *, channel: UpdateChannel) -> SignedUpdateManifestEnvelope:
        url = self._manifest_urls.get(channel)
        if url is None:
            raise UpdateManifestSourceError("update_channel_unconfigured")
        try:
            with httpx.Client(
                follow_redirects=False,
                timeout=httpx.Timeout(8.0, connect=5.0),
                transport=self._transport,
                trust_env=False,
            ) as client:
                with client.stream(
                    "GET",
                    url,
                    headers={"Accept": _ACCEPT, "Cache-Control": "no-cache"},
                ) as response:
                    if response.status_code != 200:
                        raise UpdateManifestSourceError("update_manifest_http_rejected")
                    media_type = response.headers.get("Content-Type", "").split(
                        ";", 1
                    )[0].strip().lower()
                    if media_type != _ACCEPT:
                        raise UpdateManifestSourceError("update_manifest_media_type_invalid")
                    content_encoding = response.headers.get(
                        "Content-Encoding", "identity"
                    ).strip().lower()
                    if content_encoding not in {"", "identity"}:
                        raise UpdateManifestSourceError("update_manifest_encoding_invalid")
                    content_length = response.headers.get("Content-Length")
                    declared_length: int | None = None
                    if content_length is not None:
                        try:
                            declared_length = int(content_length, 10)
                        except ValueError as error:
                            raise UpdateManifestSourceError(
                                "update_manifest_length_invalid"
                            ) from error
                        if declared_length < 0 or declared_length > MAX_UPDATE_MANIFEST_BYTES:
                            raise UpdateManifestSourceError(
                                "update_manifest_length_invalid"
                            )
                    payload = bytearray()
                    for chunk in response.iter_bytes():
                        if len(payload) + len(chunk) > MAX_UPDATE_MANIFEST_BYTES:
                            raise UpdateManifestSourceError("update_manifest_too_large")
                        payload.extend(chunk)
                    if declared_length is not None and declared_length != len(payload):
                        raise UpdateManifestSourceError("update_manifest_length_invalid")
                    key_id = response.headers.get(_KEY_ID_HEADER, "")
                    encoded_signature = response.headers.get(_SIGNATURE_HEADER, "")
        except UpdateManifestSourceError:
            raise
        except (httpx.HTTPError, OSError) as error:
            raise UpdateManifestSourceError("update_manifest_fetch_failed") from error

        if not encoded_signature or len(encoded_signature) > 1_024:
            raise UpdateManifestSourceError("update_manifest_signature_invalid")
        try:
            signature = base64.b64decode(encoded_signature, validate=True)
        except (binascii.Error, ValueError) as error:
            raise UpdateManifestSourceError("update_manifest_signature_invalid") from error
        if not signature or len(signature) > MAX_UPDATE_SIGNATURE_BYTES:
            raise UpdateManifestSourceError("update_manifest_signature_invalid")
        try:
            return SignedUpdateManifestEnvelope(
                raw_manifest=bytes(payload),
                signature=signature,
                key_id=key_id,
            )
        except (TypeError, ValueError) as error:
            raise UpdateManifestSourceError("update_manifest_headers_invalid") from error


__all__ = ("HttpsUpdateManifestSource", "UpdateManifestSourceError")
