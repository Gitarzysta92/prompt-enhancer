"""Bounded HTTPS chat adapter; credentials and text are never logged here."""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import ssl
from urllib.parse import urlsplit

from ..config import LiteLLMSettings

LITELLM_ADAPTER_VERSION = "litellm-chat-v1"
MAX_RESPONSE_BYTES = 256_000


class LiteLLMChat:
    def __init__(self, settings: LiteLLMSettings) -> None:
        self._settings = settings

    def __call__(self, alias: str, body: bytes) -> tuple[int, bytes, str]:
        config = self._settings
        if alias != config.model:
            return 502, b"{}", "application/json"
        url = urlsplit(config.base_url)
        context = ssl.create_default_context()
        pin = None
        if config.tls_cert_pem is not None:
            pem = config.tls_cert_pem.get_secret_value()
            context = ssl.create_default_context(cadata=pem)
            # Validate the chain, expiry, hostname AND exact leaf before auth.
            pin = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).digest()
        connection = http.client.HTTPSConnection(
            url.hostname, url.port or 443,
            context=context, timeout=90,
        )
        try:
            connection.connect()
            assert connection.sock is not None
            if pin is not None:
                actual = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).digest()
                if not hmac.compare_digest(pin, actual):
                    return 502, b"{}", "application/json"
            payload = json.loads(body)
            payload.pop("chat_template_kwargs", None)
            if config.reasoning_effort is not None:
                payload["reasoning_effort"] = config.reasoning_effort
            payload.update({"model": config.model, "stream": False, "no-log": True})
            connection.request("POST", "/v1/chat/completions", json.dumps(payload).encode(), {
                "Host": url.netloc,
                "Authorization": "Bearer " + config.credential.get_secret_value(),
                "Content-Type": "application/json",
                "Accept": "application/json",
                "x-litellm-enable-message-redaction": "true",
            })
            response = connection.getresponse()
            # Never follow redirects or propagate gateway errors/headers.
            if response.status != 200:
                return 502, b"{}", "application/json"
            data = response.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                return 502, b"{}", "application/json"
            return 200, data, "application/json"
        except (OSError, ValueError, http.client.HTTPException):
            return 502, b"{}", "application/json"
        finally:
            connection.close()
