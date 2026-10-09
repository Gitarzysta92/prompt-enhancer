"""Bounded HTTPS chat adapter; credentials and text are never logged here."""
from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import ssl
import socket
import threading
from urllib.parse import urlsplit

from ..config import LiteLLMSettings
from ..application.inference import InferenceModel, InferenceStream
from ..application.runtime_cancellation import (
    current_runtime_cancellation, raise_if_runtime_cancelled,
)

LITELLM_ADAPTER_VERSION = "litellm-chat-v1"
MAX_RESPONSE_BYTES = 256_000
MAX_STREAM_BYTES = 16 * 1024 * 1024
MAX_STREAM_LINE_BYTES = 256_000


class _PrivateHTTPSConnection(http.client.HTTPSConnection):
    """Dial a configured cluster address while verifying the URL's TLS name."""

    def __init__(self, host, port, *, address, context, timeout):
        super().__init__(host, port, context=context, timeout=timeout)
        self._address = address
        self._verified_context = context

    def connect(self):
        raw = socket.create_connection((self._address, self.port), self.timeout)
        try:
            self.sock = self._verified_context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class LiteLLMChat:
    def __init__(self, settings: LiteLLMSettings) -> None:
        self._settings = settings

    def __call__(self, alias: str, body: bytes) -> tuple[int, bytes, str]:
        reply = self._request(alias, body, stream=False)
        return reply.status_code, reply.body or b"{}", reply.content_type

    def open_chat(self, alias: str, body: bytes) -> InferenceStream:
        return self._request(alias, body, stream=True)

    def _request(self, alias: str, body: bytes, *, stream: bool) -> InferenceStream:
        config = self._settings
        failure = InferenceStream(502, "application/json", b"{}")
        if alias != config.model:
            return failure
        raise_if_runtime_cancelled()
        try:
            if len(body) > MAX_STREAM_BYTES:
                return failure
            payload = json.loads(body)
            if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
                return failure
        except (ValueError, TypeError):
            return failure
        url = urlsplit(config.base_url)
        context = ssl.create_default_context()
        pin = None
        if config.tls_cert_pem is not None:
            pem = config.tls_cert_pem.get_secret_value()
            context = ssl.create_default_context(cadata=pem)
            # Validate the chain, expiry, hostname AND exact leaf before auth.
            pin = hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).digest()
        if config.connect_address is not None:
            connection = _PrivateHTTPSConnection(
                url.hostname, url.port or 443, address=config.connect_address,
                context=context, timeout=5,
            )
        else:
            connection = http.client.HTTPSConnection(
                url.hostname, url.port or 443, context=context, timeout=5,
            )
        finished = threading.Event()
        cancellation = current_runtime_cancellation()
        retained = False
        active_socket = None

        def cancel():
            finished.set()
            # HTTPConnection can release its socket reference after headers
            # (Connection: close), while HTTPResponse still owns a blocking
            # file reader. Retain the socket so Stop can interrupt that reader.
            sock = connection.sock or active_socket
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except (OSError, AttributeError):
                    pass
            connection.close()

        def watch():
            while not finished.wait(.05):
                if cancellation is not None and cancellation.is_set():
                    cancel()
                    return

        watcher = threading.Thread(target=watch, name="inference-cancellation", daemon=True) if cancellation is not None else None
        if watcher is not None:
            watcher.start()

        def finish():
            cancel()
            if watcher is not None and watcher is not threading.current_thread():
                watcher.join(timeout=1)

        try:
            connection.connect()
            active_socket = connection.sock
            raise_if_runtime_cancelled()
            if hasattr(connection.sock, "settimeout"):
                connection.sock.settimeout(90)
            assert connection.sock is not None
            if pin is not None:
                actual = hashlib.sha256(connection.sock.getpeercert(binary_form=True)).digest()
                if not hmac.compare_digest(pin, actual):
                    return failure
            payload.pop("chat_template_kwargs", None)
            if config.reasoning_effort is not None:
                payload["reasoning_effort"] = config.reasoning_effort
            payload.update({"model": config.model, "stream": stream, "no-log": True})
            if not stream:
                payload.pop("stream_options", None)
            connection.request("POST", "/v1/chat/completions", json.dumps(payload).encode(), {
                "Host": url.netloc,
                "Authorization": "Bearer " + config.credential.get_secret_value(),
                "Content-Type": "application/json",
                "Accept": "text/event-stream" if stream else "application/json",
                "x-litellm-enable-message-redaction": "true",
            })
            response = connection.getresponse()
            # Never follow redirects or propagate gateway errors/headers.
            if response.status != 200:
                return failure
            content_type = response.getheader("Content-Type", "application/json") if hasattr(response, "getheader") else "application/json"
            if stream and "text/event-stream" in content_type:
                def lines():
                    size = 0
                    try:
                        while True:
                            raise_if_runtime_cancelled()
                            line = response.readline(MAX_STREAM_LINE_BYTES + 1)
                            if not line:
                                break
                            size += len(line)
                            if len(line) > MAX_STREAM_LINE_BYTES or size > MAX_STREAM_BYTES:
                                raise OSError("inference_response_too_large")
                            yield line
                    except (OSError, ValueError, http.client.HTTPException):
                        raise_if_runtime_cancelled()
                        raise OSError("inference_stream_failed") from None
                    finally:
                        finish()
                retained = True
                return InferenceStream(200, "text/event-stream", lines=lines(), cancel=finish)
            data = response.read(MAX_RESPONSE_BYTES + 1)
            if len(data) > MAX_RESPONSE_BYTES:
                return failure
            raise_if_runtime_cancelled()
            return InferenceStream(200, "application/json", data)
        except (OSError, ValueError, http.client.HTTPException):
            raise_if_runtime_cancelled()
            return failure
        finally:
            if not retained:
                finish()


class LiteLLMProvider:
    """External model adapter; no registry files, process handles or GPU claims."""
    provider_id = "litellm"
    def __init__(self, settings: LiteLLMSettings, transport: LiteLLMChat | None = None):
        self._settings = settings
        self._transport = transport or LiteLLMChat(settings)
        self.model_id = "gateway-" + hashlib.sha256(settings.model.encode()).hexdigest()[:16]

    def models(self) -> tuple[InferenceModel, ...]:
        return (InferenceModel(id=self.model_id, name=self._settings.model,
            provider="litellm", remote=True, available=True, availability="configured",
            revision=self._settings.model_revision, license=self._settings.model_license,
            adapter_version="litellm-inference.v1"),)

    def complete(self, model_id: str, body: bytes) -> tuple[int, bytes, str]:
        if model_id != self.model_id:
            return 502, b"{}", "application/json"
        return self._transport(self._settings.model, body)

    def open_chat(self, model_id: str, body: bytes) -> InferenceStream:
        if model_id != self.model_id:
            return InferenceStream(502, "application/json", b"{}")
        return self._transport.open_chat(self._settings.model, body)
