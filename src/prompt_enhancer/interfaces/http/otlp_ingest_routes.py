"""Loopback OTLP/HTTP JSON receiver for Claude Code telemetry.

Mounted outside the token-authenticated ``/v1`` tree because the provider's
exporter, not the dashboard, is the caller.  It requires a separate write-only
ingest token, accepts only ``application/json`` (the ``http/json`` OTLP
protocol), bounds the body, and never echoes anything from the payload.

Consent-inactive and store-unavailable exports are answered with HTTP 200 and
an OTLP ``partialSuccess`` naming the rejected count: the exporter treats that
as delivered, so it neither retries nor surfaces an error to the person using
Claude Code, and nothing is written.
"""

from __future__ import annotations

from collections.abc import Callable
import hmac
import json
from typing import Protocol

from fastapi import APIRouter, HTTPException, Request, Response

from ...infrastructure.providers.claude_code_hooks.ledger import (
    HookLedgerConsentInactive,
    HookLedgerUnavailable,
)
from ...infrastructure.providers.claude_code_hooks.telemetry import (
    MAX_TELEMETRY_PAYLOAD_BYTES,
    TelemetryIngestOutcome,
    TelemetryParseError,
)


OTLP_LOGS_PATH = "/otlp/v1/logs"
OTLP_METRICS_PATH = "/otlp/v1/metrics"
_PRIVATE_HEADERS = {"Cache-Control": "no-store, private", "Pragma": "no-cache"}


class TelemetryIngestCommand(Protocol):
    def ingest_logs(self, payload: object) -> TelemetryIngestOutcome: ...

    def ingest_metrics(self, payload: object) -> TelemetryIngestOutcome: ...


def _authorized(request: Request, ingest_token: str) -> bool:
    header = request.headers.get("authorization", "")
    scheme, _, candidate = header.partition(" ")
    if scheme.lower() != "bearer" or not candidate:
        return False
    return hmac.compare_digest(candidate.strip().encode("utf-8"), ingest_token.encode("utf-8"))


async def _bounded_json(request: Request) -> object:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(
            415,
            detail={
                "code": "otlp_json_required",
                "message": "set OTEL_EXPORTER_OTLP_PROTOCOL=http/json",
            },
        )
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_TELEMETRY_PAYLOAD_BYTES:
            raise HTTPException(
                413, detail={"code": "otlp_payload_too_large", "message": "export exceeds the local bound"}
            )
    try:
        return json.loads(bytes(body))
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(
            400, detail={"code": "otlp_payload_invalid", "message": "export is not valid JSON"}
        ) from None


def _partial(rejected_key: str, rejected: int, message: str) -> Response:
    payload = {"partialSuccess": {rejected_key: rejected, "errorMessage": message}}
    return Response(
        content=json.dumps(payload),
        media_type="application/json",
        headers=_PRIVATE_HEADERS,
    )


def _accepted(rejected_key: str, outcome: TelemetryIngestOutcome) -> Response:
    payload: dict[str, object] = {}
    if outcome.rejected:
        payload["partialSuccess"] = {
            rejected_key: outcome.rejected,
            "errorMessage": "records without a usable session identifier were not recorded",
        }
    return Response(
        content=json.dumps(payload),
        media_type="application/json",
        headers=_PRIVATE_HEADERS,
    )


def create_otlp_ingest_router(
    ingest_token: str,
    service: TelemetryIngestCommand,
) -> APIRouter:
    router = APIRouter(tags=["telemetry-ingest"], include_in_schema=False)

    def _guard(request: Request) -> None:
        if not _authorized(request, ingest_token):
            raise HTTPException(
                401,
                detail={"code": "otlp_ingest_token_required", "message": "ingest token required"},
                headers={"WWW-Authenticate": "Bearer"},
            )

    async def _handle(
        request: Request,
        *,
        rejected_key: str,
        ingest: Callable[[object], TelemetryIngestOutcome],
    ) -> Response:
        _guard(request)
        payload = await _bounded_json(request)
        try:
            outcome = ingest(payload)
        except TelemetryParseError:
            raise HTTPException(
                400, detail={"code": "otlp_payload_invalid", "message": "export shape is invalid"}
            ) from None
        except HookLedgerConsentInactive:
            return _partial(rejected_key, _count(payload, rejected_key), "claude_code capture is not permitted")
        except HookLedgerUnavailable:
            return _partial(rejected_key, _count(payload, rejected_key), "local store unavailable")
        return _accepted(rejected_key, outcome)

    @router.post(OTLP_LOGS_PATH)
    async def ingest_logs(request: Request) -> Response:
        return await _handle(request, rejected_key="rejectedLogRecords", ingest=service.ingest_logs)

    @router.post(OTLP_METRICS_PATH)
    async def ingest_metrics(request: Request) -> Response:
        return await _handle(request, rejected_key="rejectedDataPoints", ingest=service.ingest_metrics)

    return router


def _count(payload: object, rejected_key: str) -> int:
    """Best-effort record count for the partialSuccess body; never reads values."""

    total = 0
    if not isinstance(payload, dict):
        return 0
    if rejected_key == "rejectedLogRecords":
        for resource in payload.get("resourceLogs") or []:
            if not isinstance(resource, dict):
                continue
            for scope in resource.get("scopeLogs") or []:
                if isinstance(scope, dict):
                    records = scope.get("logRecords")
                    total += len(records) if isinstance(records, list) else 0
    else:
        for resource in payload.get("resourceMetrics") or []:
            if not isinstance(resource, dict):
                continue
            for scope in resource.get("scopeMetrics") or []:
                if not isinstance(scope, dict):
                    continue
                for metric in scope.get("metrics") or []:
                    if not isinstance(metric, dict):
                        continue
                    container = metric.get("sum") or metric.get("gauge") or {}
                    points = container.get("dataPoints") if isinstance(container, dict) else None
                    total += len(points) if isinstance(points, list) else 0
    return min(total, 10_000_000)


__all__ = ("OTLP_LOGS_PATH", "OTLP_METRICS_PATH", "create_otlp_ingest_router")
