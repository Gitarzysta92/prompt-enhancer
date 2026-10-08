"""Claude Code OTLP capture: allowlisted parse, PII drop, ledger, adapter, HTTP.

Every value here is fictional.  The exports deliberately carry the account,
organization, user, prompt, tool-parameter, and error fields the real
provider can emit, so the canary sweep proves the drop-list, not just the
allowlist.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import io
import json
from pathlib import Path
import re
import sqlite3

from fastapi.testclient import TestClient
import pytest

from prompt_enhancer.api import API_TOKEN_HEADER
from prompt_enhancer.application.providers import CapabilityKey, CompatibilityReasonCode
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.domain import (
    DataTier,
    EventKind,
    EventTimeBasis,
    Provider,
    UsageCounterKind,
    UsageScope,
)
from prompt_enhancer.infrastructure.providers.claude_code_hooks import telemetry as telemetry_module
from prompt_enhancer.infrastructure.providers.claude_code_hooks.adapter import (
    CLAUDE_CODE_HOOKS_DECODER_DESCRIPTOR,
    ClaudeCodeHookAdapter,
    ClaudeCodeHooksCompatibilityProbe,
)
from prompt_enhancer.infrastructure.providers.claude_code_hooks.contracts import (
    PSEUDONYM_NAMESPACE_PROJECT,
    PSEUDONYM_NAMESPACE_SESSION,
)
from prompt_enhancer.infrastructure.providers.claude_code_hooks.receiver import (
    ReceiverStatus,
    receive,
)
from prompt_enhancer.infrastructure.providers.claude_code_hooks.telemetry import (
    ALLOWED_ATTRIBUTE_KEYS,
    TELEMETRY_CONTRACT_VERSION,
    TelemetryParseError,
    TelemetryUsageRecord,
    parse_logs_export,
    parse_metrics_export,
)
from prompt_enhancer.privacy import Pseudonymizer


KEY = Pseudonymizer(b"\x22" * 32)
T0 = datetime(2026, 8, 19, 8, 0, tzinfo=UTC)
NANO = 1_000_000_000

CANARY_SESSION = "CANARY-OTEL-SESSION-9f9f"
CANARY_EMAIL = "canary.person@example.invalid"
CANARY_ORG = "CANARY-ORG-00000000-0000-4000-8000-000000000000"
CANARY_USER = "CANARY-USER-account-uuid"
CANARY_PROMPT = "CANARY-PROMPT-please rotate the acme api key"
CANARY_TOOL_PARAMS = '{"command":"CANARY-cat /home/example-user/.ssh/id_rsa"}'
CANARY_ERROR = "CANARY-ERROR-rate limited for acme workspace"
CANARIES = (
    CANARY_SESSION, CANARY_EMAIL, CANARY_ORG, CANARY_USER, CANARY_PROMPT,
    CANARY_TOOL_PARAMS, CANARY_ERROR, "example-user", "acme", "id_rsa",
)


def _attr(key: str, value: object) -> dict[str, object]:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": str(value)}}


def _resource() -> dict[str, object]:
    return {"attributes": [
        _attr("service.name", "claude-code"),
        _attr("service.version", "2.1.0"),
        _attr("user.email", CANARY_EMAIL),
        _attr("organization.id", CANARY_ORG),
        _attr("user.account_uuid", CANARY_USER),
        _attr("terminal.type", "vscode"),
    ]}


def _log(name: str, at: datetime, **attrs: object) -> dict[str, object]:
    common = {
        "session.id": CANARY_SESSION, "app.version": "2.1.0", "event.name": name,
        "user.email": CANARY_EMAIL, "user.id": CANARY_USER, "organization.id": CANARY_ORG,
    }
    common.update(attrs)
    return {
        "timeUnixNano": str(int(at.timestamp() * NANO)),
        "severityNumber": 9,
        "body": {"stringValue": f"claude_code.{name}"},
        "attributes": [_attr(k, v) for k, v in common.items()],
    }


def logs_export(session: str = CANARY_SESSION) -> dict[str, object]:
    def rec(name: str, at: datetime, **attrs: object) -> dict[str, object]:
        record = _log(name, at, **attrs)
        record["attributes"] = [a if a["key"] != "session.id" else _attr("session.id", session) for a in record["attributes"]]
        return record

    return {"resourceLogs": [{"resource": _resource(), "scopeLogs": [{"scope": {"name": "com.anthropic.claude_code"}, "logRecords": [
        rec("user_prompt", T0, prompt_length=42, prompt=CANARY_PROMPT),
        rec("api_request", T0 + timedelta(seconds=2), model="claude-opus-5", cost_usd=0.0123, duration_ms=1840,
            input_tokens=1200, output_tokens=340, cache_read_tokens=800, cache_creation_tokens=0),
        rec("tool_result", T0 + timedelta(seconds=3), tool_name="Bash", success=True, duration_ms=120,
            tool_parameters=CANARY_TOOL_PARAMS),
        rec("api_request", T0 + timedelta(seconds=5), model="claude-opus-5", cost_usd=0.02, duration_ms=2210,
            input_tokens=1500, output_tokens=500, cache_read_tokens=1200, cache_creation_tokens=64),
        rec("api_error", T0 + timedelta(seconds=6), model="claude-opus-5", error=CANARY_ERROR, status_code=429,
            duration_ms=90),
        rec("tool_decision", T0 + timedelta(seconds=7), tool_name="Edit", decision="accept", source="user_permanent"),
    ]}]}]}


def metrics_export(session: str = CANARY_SESSION, at: datetime = T0 + timedelta(minutes=1)) -> dict[str, object]:
    def sum_metric(name: str, points: list[tuple[dict[str, object], object]]) -> dict[str, object]:
        return {"name": name, "sum": {"aggregationTemporality": 2, "isMonotonic": True, "dataPoints": [
            {"attributes": [_attr("session.id", session), _attr("app.version", "2.1.0"), _attr("user.email", CANARY_EMAIL),
                            _attr("organization.id", CANARY_ORG)] + [_attr(k, v) for k, v in attrs.items()],
             "timeUnixNano": str(int(at.timestamp() * NANO)),
             **({"asInt": str(value)} if isinstance(value, int) else {"asDouble": value})}
            for attrs, value in points]}}

    return {"resourceMetrics": [{"resource": _resource(), "scopeMetrics": [{"metrics": [
        sum_metric("claude_code.token.usage", [({"type": "input", "model": "claude-opus-5"}, 2700), ({"type": "output", "model": "claude-opus-5"}, 840),
                                               ({"type": "cacheRead", "model": "claude-opus-5"}, 2000), ({"type": "cacheCreation", "model": "claude-opus-5"}, 64)]),
        sum_metric("claude_code.cost.usage", [({"model": "claude-opus-5"}, 0.0323)]),
        sum_metric("claude_code.lines_of_code.count", [({"type": "added"}, 120), ({"type": "removed"}, 33)]),
        sum_metric("claude_code.commit.count", [({}, 2)]),
        sum_metric("claude_code.pull_request.count", [({}, 0)]),
        sum_metric("claude_code.active_time.total", [({"type": "user"}, 95.5), ({"type": "cli"}, 240.0)]),
        sum_metric("claude_code.session.count", [({}, 1)]),
        {"name": "claude_code.code_edit_tool.decision", "sum": {"dataPoints": [{"attributes": [_attr("session.id", session), _attr("tool_name", "Edit"), _attr("language", "python")], "asInt": "3"}]}},
    ]}]}]}


def _no_canary(text: str) -> None:
    for canary in CANARIES:
        assert canary not in text, canary


# --- contract ---------------------------------------------------------------------


def test_telemetry_source_reads_only_allowlisted_attribute_keys() -> None:
    source = Path(telemetry_module.__file__).read_text(encoding="utf-8")
    body = source.split('"""', 2)[2]
    # Every attribute read in the module names an allowlisted key.
    reads = re.findall(r'attributes\.get\("([A-Za-z_.]+)"\)', body)
    assert reads, "expected attribute reads"
    for key in reads:
        assert key in ALLOWED_ATTRIBUTE_KEYS, key
    # And the allowlist itself never admits an identity or content key.
    for forbidden in ("user.email", "user.id", "user.account_uuid", "organization.id",
                      "terminal.type", "prompt", "tool_parameters", "error", "tool_name",
                      "custom_instructions", "message"):
        assert forbidden not in ALLOWED_ATTRIBUTE_KEYS, forbidden


def test_usage_record_type_cannot_hold_text_or_account_identity() -> None:
    fields = set(TelemetryUsageRecord.model_fields)
    for name in ("prompt", "error", "tool_parameters", "user_email", "organization_id", "account_uuid", "session_id"):
        assert name not in fields
    # An unsafe model identifier is dropped to unknown, never stored and never fatal.
    record = TelemetryUsageRecord(hook_session_id="a" * 64, hook_project_id="b" * 64, reported_at=T0, model_id="claude opus 5!")
    assert record.model_id is None
    with pytest.raises(ValueError):
        TelemetryUsageRecord(hook_session_id="not-a-pseudonym", hook_project_id="b" * 64, reported_at=T0)


# --- parse ------------------------------------------------------------------------


def test_logs_export_yields_only_api_requests_and_drops_everything_else() -> None:
    batch = parse_logs_export(logs_export(), pseudonymizer=KEY, received_at=T0)
    assert batch.rejected == 0
    assert [u.outcome for u in batch.usage] == ["completed", "completed", "error"]
    first = batch.usage[0]
    assert first.model_id == "claude-opus-5" and first.provider_version == "2.1.0"
    assert first.input_tokens == 1200 and first.output_tokens == 340
    assert first.cache_read_tokens == 800 and first.cache_creation_tokens == 0
    assert first.duration_ms == 1840 and first.cost_micro_usd == 12_300
    assert first.reported_at == T0 + timedelta(seconds=2)
    assert re.fullmatch(r"[a-f0-9]{64}", first.hook_session_id)
    _no_canary(batch.model_dump_json())
    # The error record carries no error text - only the outcome and what numbers it had.
    error = batch.usage[2]
    assert error.outcome == "error" and error.input_tokens is None and error.duration_ms == 90


def test_metrics_export_yields_latest_cumulative_counters() -> None:
    batch = parse_metrics_export(metrics_export(), pseudonymizer=KEY, received_at=T0)
    assert batch.rejected == 0 and len(batch.counters) == 1
    c = batch.counters[0]
    assert (c.input_tokens_total, c.output_tokens_total, c.cache_read_tokens_total, c.cache_creation_tokens_total) == (2700, 840, 2000, 64)
    assert c.cost_micro_usd_total == 32_300
    assert (c.lines_added_total, c.lines_removed_total) == (120, 33)
    assert (c.commit_count_total, c.pull_request_count_total) == (2, 0)
    assert (c.active_user_ms_total, c.active_cli_ms_total) == (95_500, 240_000)
    assert c.provider_version == "2.1.0"
    _no_canary(batch.model_dump_json())


def test_parse_rejects_records_without_session_and_refuses_bad_shapes() -> None:
    export = logs_export()
    export["resourceLogs"][0]["scopeLogs"][0]["logRecords"].append(
        {"timeUnixNano": "1", "attributes": [_attr("event.name", "api_request"), _attr("model", "x")]}
    )
    batch = parse_logs_export(export, pseudonymizer=KEY, received_at=T0)
    assert batch.rejected == 1 and len(batch.usage) == 3
    with pytest.raises(TelemetryParseError):
        parse_logs_export([1, 2], pseudonymizer=KEY, received_at=T0)
    deep: dict[str, object] = {}
    node = deep
    for _ in range(40):
        node["x"] = {}
        node = node["x"]  # type: ignore[assignment]
    with pytest.raises(TelemetryParseError):
        parse_metrics_export(deep, pseudonymizer=KEY, received_at=T0)


def test_hook_and_telemetry_agree_on_the_session_pseudonym() -> None:
    from prompt_enhancer.infrastructure.providers.claude_code_hooks.receiver import minimize_payload

    hook = minimize_payload({"session_id": CANARY_SESSION, "hook_event_name": "Stop"}, pseudonymizer=KEY, received_at=T0)
    assert hook is not None
    usage = parse_logs_export(logs_export(), pseudonymizer=KEY, received_at=T0).usage[0]
    assert usage.hook_session_id == hook.hook_session_id


# --- HTTP + ledger + adapter --------------------------------------------------------


@pytest.fixture
def composed(tmp_path: Path):
    settings = AppSettings(home=tmp_path)
    application = bootstrap_local_application(settings)
    client = TestClient(application.create_http_app(), base_url="http://127.0.0.1")
    api = {API_TOKEN_HEADER: settings.api_token_path.read_text(encoding="utf-8").strip()}
    ingest_token = settings.otlp_ingest_token_path.read_text(encoding="utf-8").strip()
    otlp = {"Authorization": f"Bearer {ingest_token}", "Content-Type": "application/json"}
    return client, api, otlp, settings, application


def test_otlp_receiver_requires_ingest_token_json_and_bounds(composed) -> None:
    client, api, otlp, settings, _ = composed
    body = json.dumps(logs_export())
    assert client.post("/otlp/v1/logs", content=body, headers={"Content-Type": "application/json"}).status_code == 401
    # The dashboard API token is not the ingest token.
    assert client.post("/otlp/v1/logs", content=body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {api[API_TOKEN_HEADER]}"}).status_code == 401
    assert client.post("/otlp/v1/logs", content=body, headers={"Authorization": otlp["Authorization"], "Content-Type": "application/x-protobuf"}).status_code == 415
    assert client.post("/otlp/v1/logs", content=b"{not json", headers=otlp).status_code == 400
    assert client.post("/otlp/v1/logs", content=b"[]", headers=otlp).status_code == 400
    # The ingest token opens nothing on the authenticated API.
    assert client.get("/v1/sessions", headers={API_TOKEN_HEADER: otlp["Authorization"].split()[1]}).status_code == 401
    assert "/otlp/v1/logs" not in client.get("/openapi.json").text if client.get("/openapi.json").status_code == 200 else True


def test_otlp_receiver_answers_inactive_consent_with_partial_success_and_writes_nothing(composed) -> None:
    client, _, otlp, settings, _ = composed
    response = client.post("/otlp/v1/logs", content=json.dumps(logs_export()), headers=otlp)
    assert response.status_code == 200
    assert response.json()["partialSuccess"]["rejectedLogRecords"] == 6
    assert "not permitted" in response.json()["partialSuccess"]["errorMessage"]
    response = client.post("/otlp/v1/metrics", content=json.dumps(metrics_export()), headers=otlp)
    assert response.status_code == 200 and response.json()["partialSuccess"]["rejectedDataPoints"] > 0
    connection = sqlite3.connect(settings.database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM claude_code_telemetry_sessions").fetchone()[0] == 0
    finally:
        connection.close()


def test_end_to_end_usage_reaches_token_metrics_without_canary(composed) -> None:
    client, api, otlp, settings, application = composed
    Database(settings.database_path).grant_consent(Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT)
    # A hook session first, so telemetry joins it rather than creating a telemetry-only one.
    clock = iter(T0 + timedelta(seconds=i) for i in range(30))
    for name in ("SessionStart", "Stop"):
        payload = {"session_id": CANARY_SESSION, "cwd": "/srv/example/CANARY-OTEL-PROJECT", "hook_event_name": name, "source": "startup"}
        receive(io.BytesIO(json.dumps(payload).encode()), settings=settings, now=lambda: next(clock))

    logs = client.post("/otlp/v1/logs", content=json.dumps(logs_export()), headers=otlp)
    assert logs.status_code == 200 and logs.json() == {}
    metrics = client.post("/otlp/v1/metrics", content=json.dumps(metrics_export()), headers=otlp)
    assert metrics.status_code == 200 and metrics.json() == {}

    status = client.get("/v1/local-sources/claude-code", headers=api).json()
    assert status["captured_sessions"] == 1

    indexed = client.post("/v1/local-sources/claude-code/index", headers=api, json={"max_sessions": 10}).json()
    assert indexed["sessions_seen"] == 1 and indexed["events_seen"] == 5  # 2 hook + 3 usage
    row = next(r for r in client.get("/v1/sessions?limit=50&offset=0", headers=api).json()["sessions"] if r["provider"] == "claude_code")
    assert row["provider_version"] == "2.1.0"
    session_id = row["session_id"]
    events = application.database.get_session_events(session_id)
    hook_events = [e for e in events if e.kind is not EventKind.USAGE]
    usage_events = [e for e in events if e.kind is EventKind.USAGE]
    assert hook_events and all(
        event.time_basis is EventTimeBasis.RECEIVER_OBSERVED
        for event in hook_events
    )
    assert len(usage_events) == 3
    assert all(
        event.time_basis is EventTimeBasis.PROVIDER_REPORTED
        for event in usage_events
    )
    assert usage_events[0].usage is not None
    assert usage_events[0].usage.input_tokens == 1200 and usage_events[0].usage.output_tokens == 340
    assert usage_events[0].usage.cached_input_tokens == 800 and usage_events[0].usage.model_id == "claude-opus-5"
    assert usage_events[0].usage.counter_kind is UsageCounterKind.DELTA and usage_events[0].usage.scope is UsageScope.REQUEST
    assert usage_events[2].success is False  # api_error
    assert all(e.sequence >= 1_000_000 for e in usage_events)

    # Deterministic token metrics now have numbers for this Claude session.
    metrics_rows = application.database.get_session_metrics(session_id)
    timestamp_rate = next(
        metric
        for metric in metrics_rows
        if metric["key"] == "data_quality.direct_event_timestamp_rate"
    )
    assert timestamp_rate["version"] == 2
    assert timestamp_rate["numeric_value"] == pytest.approx(3 / 5)
    token_metrics = {m["key"]: m for m in metrics_rows if "token" in str(m["key"])}
    assert token_metrics, [m["key"] for m in metrics_rows]
    assert any(m.get("numeric_value") not in (None, 0) for m in token_metrics.values())

    # Compatibility now knows the provider version but still cannot claim coverage.
    checked = client.post("/v1/providers/claude_code/compatibility/check", headers=api).json()
    assert checked["provider_version"] == "2.1.0" and checked["state"] == "degraded"
    ledger = application.database.claude_hook_ledger()
    report = ClaudeCodeHooksCompatibilityProbe(ledger).check()
    assert [r.code for r in report.reasons] == [
        CompatibilityReasonCode.PROVIDER_VERSION_UNTESTED,
        CompatibilityReasonCode.COMPLETE_DELIVERY_UNPROVEN,
        CompatibilityReasonCode.EPHEMERAL_DESCRIPTORS_UNAVAILABLE,
    ]
    assert CapabilityKey.TOKEN_USAGE in CLAUDE_CODE_HOOKS_DECODER_DESCRIPTOR.capabilities

    # Whole-database canary sweep, including the token stored on disk.
    connection = sqlite3.connect(settings.database_path)
    try:
        dump = "\n".join(repr(r) for t in [x[0] for x in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")] for r in connection.execute(f'SELECT * FROM "{t}"'))
    finally:
        connection.close()
    _no_canary(dump)
    assert otlp["Authorization"].split()[1] not in dump


@pytest.mark.parametrize("write_order", ("hook_first", "telemetry_first"))
def test_missing_cwd_project_reconciles_in_both_write_orders_and_survives_restart(
    composed,
    write_order: str,
) -> None:
    client, _, otlp, settings, application = composed
    Database(settings.database_path).grant_consent(
        Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT
    )
    raw_cwd = "/srv/example/CANARY-RECONCILE-PROJECT"

    def append_hook() -> None:
        outcome = receive(
            io.BytesIO(
                json.dumps(
                    {
                        "session_id": CANARY_SESSION,
                        "cwd": raw_cwd,
                        "hook_event_name": "SessionStart",
                        "source": "startup",
                    }
                ).encode()
            ),
            settings=settings,
            now=lambda: T0,
        )
        assert outcome.status is ReceiverStatus.APPENDED

    def append_telemetry() -> None:
        assert client.post(
            "/otlp/v1/logs", content=json.dumps(logs_export()), headers=otlp
        ).status_code == 200
        assert client.post(
            "/otlp/v1/metrics",
            content=json.dumps(metrics_export()),
            headers=otlp,
        ).status_code == 200

    first = append_hook if write_order == "hook_first" else append_telemetry
    second = append_telemetry if write_order == "hook_first" else append_hook
    first()
    ledger = application.database.claude_hook_ledger()
    before_session = ledger.list_sessions(limit=2)[0]
    before = ledger.read_session_snapshot(before_session.hook_session_id)
    assert before is not None
    second()

    # A new database/ledger instance models a process restart.  The reconciled
    # boundary remains exact without retaining either raw source identifier.
    reopened = Database(settings.database_path).claude_hook_ledger()
    session = reopened.list_sessions(limit=2)[0]
    after = reopened.read_session_snapshot(session.hook_session_id)
    assert after is not None and after.telemetry is not None
    assert after.boundary.boundary_fingerprint != before.boundary.boundary_fingerprint
    assert after.telemetry.hook_session_id == after.session.hook_session_id
    assert after.telemetry.hook_project_id == after.session.hook_project_id
    assert after.telemetry.counters is not None
    assert after.telemetry.counters.hook_session_id == after.session.hook_session_id
    assert after.telemetry.counters.hook_project_id == after.session.hook_project_id

    connection = sqlite3.connect(settings.database_path)
    try:
        provider_dump = "\n".join(
            repr(row)
            for table in (
                "claude_code_hook_sessions",
                "claude_code_hook_events",
                "claude_code_telemetry_sessions",
                "claude_code_telemetry_requests",
            )
            for row in connection.execute(f'SELECT * FROM "{table}"').fetchall()
        )
    finally:
        connection.close()
    assert CANARY_SESSION not in provider_dump
    assert raw_cwd not in provider_dump


def test_project_reconciliation_never_crosses_an_unrelated_session(composed) -> None:
    client, _, otlp, settings, application = composed
    Database(settings.database_path).grant_consent(
        Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT
    )
    assert client.post(
        "/otlp/v1/logs", content=json.dumps(logs_export()), headers=otlp
    ).status_code == 200
    ledger = application.database.claude_hook_ledger()
    telemetry_only = ledger.list_sessions(limit=2)[0]
    before = ledger.read_session_snapshot(telemetry_only.hook_session_id)
    assert before is not None

    unrelated_raw_session = "synthetic-unrelated-provider-session"
    outcome = receive(
        io.BytesIO(
            json.dumps(
                {
                    "session_id": unrelated_raw_session,
                    "cwd": "/srv/example/synthetic-unrelated-project",
                    "hook_event_name": "SessionStart",
                    "source": "startup",
                }
            ).encode()
        ),
        settings=settings,
        now=lambda: T0,
    )
    assert outcome.status is ReceiverStatus.APPENDED

    reopened = Database(settings.database_path).claude_hook_ledger()
    after = reopened.read_session_snapshot(telemetry_only.hook_session_id)
    assert after is not None
    assert after.boundary == before.boundary
    assert len(reopened.list_sessions(limit=3)) == 2


def test_two_nonplaceholder_projects_for_one_session_fail_closed(composed) -> None:
    _, _, _, settings, application = composed
    Database(settings.database_path).grant_consent(
        Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT
    )
    raw_session = "synthetic-conflicting-provider-session"
    raw_cwd = "/srv/example/synthetic-conflicting-hook-project"
    hook_session_id = application.pseudonymizer.pseudonymize(
        PSEUDONYM_NAMESPACE_SESSION, raw_session
    )
    foreign_project_id = application.pseudonymizer.pseudonymize(
        PSEUDONYM_NAMESPACE_PROJECT,
        "synthetic-nonplaceholder-telemetry-project",
    )
    connection = sqlite3.connect(settings.database_path)
    try:
        connection.execute(
            """INSERT INTO claude_code_telemetry_sessions(
                   hook_session_id, hook_project_id, contract_version,
                   provider_version, first_received_at, last_received_at,
                   request_count)
               VALUES (?,?,?,?,?,?,0)""",
            (
                hook_session_id,
                foreign_project_id,
                TELEMETRY_CONTRACT_VERSION,
                "synthetic-provider-v1",
                T0.isoformat(),
                T0.isoformat(),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    outcome = receive(
        io.BytesIO(
            json.dumps(
                {
                    "session_id": raw_session,
                    "cwd": raw_cwd,
                    "hook_event_name": "SessionStart",
                    "source": "startup",
                }
            ).encode()
        ),
        settings=settings,
        now=lambda: T0,
    )
    assert outcome.status is ReceiverStatus.STORE_UNAVAILABLE

    connection = sqlite3.connect(settings.database_path)
    try:
        stored_project_id = connection.execute(
            """SELECT hook_project_id FROM claude_code_telemetry_sessions
               WHERE hook_session_id=?""",
            (hook_session_id,),
        ).fetchone()[0]
        hook_count = connection.execute(
            """SELECT COUNT(*) FROM claude_code_hook_sessions
               WHERE hook_session_id=?""",
            (hook_session_id,),
        ).fetchone()[0]
        provider_dump = "\n".join(
            repr(row)
            for table in (
                "claude_code_hook_sessions",
                "claude_code_telemetry_sessions",
            )
            for row in connection.execute(f'SELECT * FROM "{table}"').fetchall()
        )
    finally:
        connection.close()
    assert stored_project_id == foreign_project_id
    assert hook_count == 0
    assert raw_session not in provider_dump and raw_cwd not in provider_dump


def test_telemetry_only_session_is_listed_with_cumulative_usage(composed) -> None:
    client, api, otlp, settings, application = composed
    Database(settings.database_path).grant_consent(Provider.CLAUDE_CODE, DataTier.REDACTED_CONTENT)
    assert client.post("/otlp/v1/metrics", content=json.dumps(metrics_export(session="only-otel-session")), headers=otlp).status_code == 200
    adapter = ClaudeCodeHookAdapter(application.database.claude_hook_ledger())
    probe = adapter.probe()
    assert probe.provider_version == "2.1.0"
    page = adapter.list_sessions(limit=10)
    assert len(page.sessions) == 1
    session = page.sessions[0]
    assert session.source_project_display_name is None
    snapshot = adapter.read_session(session)
    assert len(snapshot.events) == 1
    usage = snapshot.events[0]
    assert usage.kind is EventKind.USAGE and usage.usage is not None
    assert usage.time_basis is EventTimeBasis.PROVIDER_REPORTED
    assert usage.usage.counter_kind is UsageCounterKind.CUMULATIVE and usage.usage.scope is UsageScope.THREAD
    assert usage.usage.input_tokens == 2700 and usage.usage.output_tokens == 840


def test_cli_otel_config_prints_env_without_writing_config(tmp_path: Path, monkeypatch, capsys) -> None:
    from prompt_enhancer.cli import main

    monkeypatch.setenv("PROMPT_ENHANCER_HOME", str(tmp_path))
    assert main(["claude-otel-config"]) == 0
    out = capsys.readouterr().out
    assert "CLAUDE_CODE_ENABLE_TELEMETRY=1" in out
    assert "OTEL_EXPORTER_OTLP_PROTOCOL=http/json" in out
    assert "/otlp/v1/logs" in out and "/otlp/v1/metrics" in out
    assert "OTEL_LOG_USER_PROMPTS=0" in out
    token = (tmp_path / "otlp-ingest.token").read_text(encoding="utf-8").strip()
    assert f"Authorization=Bearer {token}" in out
    assert token != (tmp_path / "api.token").read_text(encoding="utf-8").strip() if (tmp_path / "api.token").exists() else True
