"""Provider-independent ASGI ownership of a cancelable inference stream."""
from __future__ import annotations
from collections.abc import Callable
import threading
import anyio
from fastapi import HTTPException, Response
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from starlette.types import Receive, Scope, Send
from ...application.inference import InferenceStream
from ...application.runtime_cancellation import runtime_request_scope

def _close_chat(upstream: InferenceStream) -> None:
    try:
        if upstream.cancel is not None:
            upstream.cancel()
    finally:
        close = getattr(upstream.lines, "close", None)
        if callable(close):
            close()


class InferenceRelayResponse(Response):
    """Own connect, headers and streaming until delivery or client disconnect.

    There is exactly one ASGI receive consumer, including before headers. The
    standard streaming sender still handles framing and the iterator thread
    pool; calling stream_response avoids starting a second disconnect watcher.
    """

    def __init__(self, open_chat: Callable[[], InferenceStream], *, errors: tuple[type[Exception], ...], error_response: Callable[[Exception], HTTPException]):
        super().__init__(content=b"")
        self._open_chat = open_chat
        self._errors = errors
        self._error_response = error_response

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        cancelled = threading.Event()
        upstream = None
        failure = None
        disconnected = False
        delivery_finished = False

        async with anyio.create_task_group() as tasks:
            async def watch_disconnect() -> None:
                nonlocal disconnected
                try:
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            disconnected = True
                            tasks.cancel_scope.cancel()
                            return
                finally:
                    # Also release the worker when the ASGI request itself is
                    # cancelled during application shutdown.
                    if not delivery_finished:
                        disconnected = True
                    cancelled.set()

            tasks.start_soon(watch_disconnect)
            try:
                with runtime_request_scope(cancelled):
                    try:
                        # Never wait for a runtime socket on the API event loop.
                        # The worker is joined, not abandoned on cancellation.
                        upstream = await run_in_threadpool(self._open_chat)
                    except self._errors as error:
                        failure = error
                    if upstream is not None and not cancelled.is_set():
                        if upstream.lines is not None:
                            response = StreamingResponse(
                                upstream.lines, status_code=upstream.status_code,
                                media_type="text/event-stream",
                                headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
                            )
                            await response.stream_response(send)
                        else:
                            response = Response(
                                content=upstream.body or b"", status_code=upstream.status_code,
                                media_type=upstream.content_type, headers={"Cache-Control": "no-store"},
                            )
                            await response(scope, receive, send)
            except OSError:
                # ASGI 2.4+ may report a closed client through send as well.
                disconnected = True
            finally:
                delivery_finished = True
                cancelled.set()
                try:
                    with anyio.CancelScope(shield=True):
                        if upstream is not None:
                            await run_in_threadpool(_close_chat, upstream)
                finally:
                    tasks.cancel_scope.cancel()
        # Raise outside the task group so exception handlers receive the normal
        # sanitized HTTP error rather than an ExceptionGroup or a false 200.
        if failure is not None and not disconnected:
            raise self._error_response(failure) from None
