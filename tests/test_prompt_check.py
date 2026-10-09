"""Prompt check (ADR 0015): deterministic cues, context inference, model commentary, history, HTTP, MCP tool."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import pytest
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER
from prompt_enhancer.application.agent_surface import AgentReadSurface
from prompt_enhancer.application.prompt_check import (
    MAX_PROMPT_CHARS,
    PROMPT_METRIC_KEYS,
    PromptCheckMessage,
    PromptCheckRequest,
    PromptCheckService,
    parse_commentary_reply,
)
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.privacy import Pseudonymizer


T0 = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)
CANARY = "CANARY-SECRET-PHRASE-7731"
WEAK = "fix it"
STRONG = (
    "Add retry with exponential backoff to the uploader in src/upload/client.py so that transient HTTP 503 responses "
    "are retried up to 3 times. Keep the public API unchanged and do not touch the auth module. Done when "
    "pytest tests/test_upload.py passes and a new test covers the retry path; deliver the change as a single commit."
)


class _Repo:
    def __init__(self) -> None:
        self.rows = []

    def insert(self, record) -> None:
        self.rows.append(record)

    def list(self, *, limit: int, offset: int):
        return tuple(reversed(self.rows))[offset : offset + limit]

    def get(self, check_id: str):
        return next((r for r in self.rows if r.check_id == check_id), None)


def _service(repo: _Repo | None = None, *, chat=None, active=None) -> PromptCheckService:
    return PromptCheckService(
        repo or _Repo(),
        pseudonymize=Pseudonymizer(bytes(range(32))).pseudonymize,
        chat=chat,
        active_model=active or (lambda: None),
        clock=lambda: T0,
    )


def test_deterministic_cues_and_context_inference_without_a_model() -> None:
    repo = _Repo()
    service = _service(repo)
    strong = service.check(PromptCheckRequest(prompt=STRONG, provider="codex", want_commentary=True))
    by_key = {m.key: m for m in strong.metrics}
    assert tuple(by_key) == PROMPT_METRIC_KEYS
    assert by_key["prompt.task_definition_coverage"].state == "known" and by_key["prompt.task_definition_coverage"].value == 1.0
    assert {c.code for c in by_key["prompt.task_definition_coverage"].cues} == {"task.action", "task.target", "task.outcome"}
    assert strong.context.task_type == "implement" and strong.context.language == "en"
    assert strong.context.file_references == 2 and strong.context.verification_requested is True
    assert strong.context.prior_context_supplied == 0
    assert strong.commentary.state == "no_active_model" and strong.commentary.findings == ()
    assert "Task definition coverage: 3/3" in strong.summary and "no local model active" in strong.summary
    assert strong.dashboard_path == f"/prompt-checks/{strong.check_id}"

    weak = service.check(PromptCheckRequest(prompt=WEAK, prior_messages=(PromptCheckMessage(role="user", content="The uploader fails under load."),)))
    assert all(m.state != "known" for m in weak.metrics)
    assert weak.context.depends_on_prior_context is True and weak.context.prior_context_supplied == 1
    assert "an acceptance criterion" in " ".join(weak.context.missing_elements)
    assert "too short or language not recognised" in weak.summary

    # History keeps metrics and counters only - never the prompt.
    assert [r.check_id for r in repo.list(limit=10, offset=0)] == [weak.check_id, strong.check_id]
    dumped = json.dumps([r.model_dump(mode="json") for r in repo.rows])
    assert "uploader" not in dumped and "fix it" not in dumped and "src/upload" not in dumped
    assert repo.get(strong.check_id).prompt_chars == len(STRONG)


def test_polish_prompt_is_analysed_and_task_type_prefers_the_earliest_verb() -> None:
    service = _service()
    result = service.check(
        PromptCheckRequest(
            prompt="Napraw błąd w module uploadera w pliku src/upload/client.py, bo przy HTTP 503 wysyłka się przerywa. "
            "Nie zmieniaj publicznego API. Uruchom testy pytest i dodaj test na ponowienie.",
            want_commentary=False,
        )
    )
    assert result.context.language == "pl" and result.context.task_type == "fix"
    assert result.context.verification_requested is True
    assert result.commentary.state == "skipped"

    # A prompt that names things only the earlier turns identify relies on them; an explicit file does not.
    shared = service.check(
        PromptCheckRequest(
            prompt="Add retry with exponential backoff to the uploader so transient 503s don't fail the batch.",
            prior_messages=(PromptCheckMessage(role="user", content="Yesterday the uploader in src/upload/client.py failed under load with transient 503 errors."),),
            want_commentary=False,
        )
    )
    assert shared.context.depends_on_prior_context is True
    explicit = service.check(
        PromptCheckRequest(
            prompt="Add retry with exponential backoff to the uploader in src/upload/client.py so transient 503s don't fail.",
            prior_messages=(PromptCheckMessage(role="user", content="Yesterday the uploader failed under load."),),
            want_commentary=False,
        )
    )
    assert explicit.context.depends_on_prior_context is False


def test_model_commentary_is_parsed_strictly_and_labelled_as_model_output() -> None:
    calls: list[dict] = []

    def chat(alias: str, body: bytes):
        payload = json.loads(body)
        calls.append(payload)
        reply = {
            "findings": [
                {"aspect": "acceptance", "severity": "high", "why": "No done-when.", "suggestion": "State the passing test."},
                {"aspect": "other", "severity": "medium", "why": "x", "suggestion": "y"},
            ],
            "reformulated_prompt": "Add retries to the uploader; done when tests pass.",
            "reformulated_elements": [{"element": "acceptance", "original": None, "suggested": "Done when pytest passes."}],
            "notes": "Mostly clear.",
        }
        text = "```json\n" + json.dumps(reply) + "\n```"
        return 200, json.dumps({"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": text}}]}).encode("utf-8"), "application/json"

    service = _service(chat=chat, active=lambda: "stub-model")
    result = service.check(PromptCheckRequest(prompt=STRONG, prior_messages=(PromptCheckMessage(role="assistant", content="Earlier reply " + CANARY),)))
    assert result.commentary.state == "ok" and result.commentary.model_alias == "stub-model"
    assert [f.aspect for f in result.commentary.findings] == ["acceptance", "other"]
    assert [f.severity for f in result.commentary.findings] == ["high", "medium"]
    assert result.commentary.reformulated_prompt.startswith("Add retries")
    assert result.commentary.reformulated_elements[0].element == "acceptance"
    assert "model suggestions" in result.summary and "reformulated prompt is included" in result.summary
    assert calls and calls[0]["chat_template_kwargs"] == {"enable_thinking": False}
    sent = calls[0]["messages"][1]["content"]
    assert CANARY in sent and "Prompt to review" in sent and "Deterministic findings" in sent

    # Invalid or overlong output is rejected, never repaired into valid advice.
    assert parse_commentary_reply("not json", prompt_chars=10) is None
    assert parse_commentary_reply("{}", prompt_chars=10) is None
    long = parse_commentary_reply(json.dumps({"reformulated_prompt": "x" * 90_000}), prompt_chars=10)
    assert long is None


def test_model_failures_fall_back_to_deterministic_results() -> None:
    def broken(alias: str, body: bytes):
        return 500, b"{}", "application/json"

    result = _service(chat=broken, active=lambda: "stub").check(PromptCheckRequest(prompt=STRONG))
    assert result.commentary.state == "model_error" and result.metrics

    def prose(alias: str, body: bytes):
        return 200, json.dumps({"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "I cannot help with that."}}]}).encode(), "application/json"

    result = _service(chat=prose, active=lambda: "stub").check(PromptCheckRequest(prompt=STRONG))
    assert result.commentary.state == "reply_invalid"


def test_request_bounds() -> None:
    import pytest

    with pytest.raises(ValueError):
        PromptCheckRequest(prompt="   ")
    with pytest.raises(ValueError):
        PromptCheckRequest(prompt="x" * (MAX_PROMPT_CHARS + 1))
    with pytest.raises(ValueError):
        PromptCheckRequest(prompt="ok", prior_messages=tuple(PromptCheckMessage(role="user", content="y" * 8_000) for _ in range(6)))
    with pytest.raises(ValueError):
        PromptCheckRequest(prompt="ok", agent_model="bad\nname")


def test_http_routes_persist_only_metrics_and_capability_is_advertised(tmp_path: Path) -> None:
    settings = AppSettings(home=tmp_path / "home")
    application = bootstrap_local_application(settings)
    application.database.initialize()
    client = TestClient(application.create_http_app(), base_url="http://127.0.0.1")
    headers = {API_TOKEN_HEADER: settings.api_token_path.read_text(encoding="utf-8").strip()}
    assert client.get("/v1/capabilities", headers=headers).json()["prompt_check"] is True
    assert client.post("/v1/prompt-checks", json={"prompt": STRONG}).status_code == 401
    created = client.post("/v1/prompt-checks", headers=headers, json={"prompt": STRONG, "provider": "claude_code", "agent_model": "claude-opus-5"})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["contract_version"] == "prompt-check.v1" and body["commentary"]["state"] == "no_active_model"
    assert {m["key"] for m in body["metrics"]} == set(PROMPT_METRIC_KEYS)
    listed = client.get("/v1/prompt-checks?limit=5", headers=headers).json()
    assert [c["check_id"] for c in listed["checks"]] == [body["check_id"]]
    stored = client.get(f"/v1/prompt-checks/{body['check_id']}", headers=headers).json()
    assert stored["provider"] == "claude_code" and stored["agent_model"] == "claude-opus-5" and stored["prompt_chars"] == len(STRONG)
    assert client.get(f"/v1/prompt-checks/{'0' * 64}", headers=headers).status_code == 404
    assert client.post("/v1/prompt-checks", headers=headers, json={"prompt": ""}).status_code == 422
    with sqlite3.connect(settings.database_path) as connection:
        rows = connection.execute("SELECT * FROM prompt_checks").fetchall()
        dump = repr(rows)
    assert len(rows) == 1 and "uploader" not in dump and "src/upload" not in dump


def test_mcp_check_prompt_tool_returns_the_scorecard(tmp_path: Path) -> None:
    database = Database(tmp_path / "m.sqlite3")
    database.initialize()
    service = _service(_Repo())
    surface = AgentReadSurface(database, prompt_check=service.check)
    assert [t.name for t in surface.tools()][-1] == "check_prompt"
    schema = next(t for t in surface.tools() if t.name == "check_prompt").input_schema()
    assert "prompt" in schema["properties"] and schema.get("additionalProperties") is False
    result = surface.call("check_prompt", {"prompt": STRONG, "prior_messages": [{"role": "user", "content": "context"}]})
    assert result["summary"].startswith("Prompt check") and result["context"]["prior_context_supplied"] == 1
    assert "contract_version" in result and result["metrics"]
    without = AgentReadSurface(database)
    assert all(t.name != "check_prompt" for t in without.tools())


def test_claude_prompt_check_hook_is_opt_in_silent_on_failure_and_hands_back_advice(tmp_path: Path) -> None:
    import io

    from prompt_enhancer.interfaces.hooks import additional_context_from_result, run_prompt_check_hook

    settings = AppSettings(home=tmp_path / "home")
    settings.home.mkdir(parents=True, exist_ok=True)
    settings.api_token_path.write_text("example-token-do-not-use", encoding="utf-8")
    payload = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "Please add retries to the uploader and keep the API stable"})

    # Disabled by env: nothing happens, nothing is called.
    calls: list[object] = []
    out = io.StringIO()
    assert run_prompt_check_hook(settings, stdin=io.StringIO(payload), stdout=out, env={"PROMPT_ENHANCER_PROMPT_CHECK_HOOK": "0"}, opener=lambda *a, **k: calls.append(a)) == 0
    assert out.getvalue() == "" and calls == []

    # Short prompts and slash commands are skipped.
    for short in ("ok", "yes please", "/compact"):
        out = io.StringIO()
        assert run_prompt_check_hook(settings, stdin=io.StringIO(json.dumps({"prompt": short})), stdout=out, env={}, opener=lambda *a, **k: calls.append(a)) == 0
        assert out.getvalue() == "" and calls == []

    class _Response:
        status = 200

        def __init__(self, body: dict) -> None:
            self._body = json.dumps(body).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self) -> bytes:
            return self._body

    seen: list[object] = []

    def opener(request, timeout):
        seen.append((request.full_url, json.loads(request.data), request.get_header("X-prompt-enhancer-token"), timeout))
        return _Response(
            {
                "summary": "Prompt check - Task definition coverage: 2/3 (missing: the intended result).",
                "commentary": {"state": "ok", "findings": [{"aspect": "acceptance", "severity": "high", "suggestion": "Say when it is done."}], "reformulated_prompt": "Add retries <specify: how many> to the uploader."},
                "context": {"depends_on_prior_context": True, "prior_context_supplied": 0},
            }
        )

    out = io.StringIO()
    assert run_prompt_check_hook(settings, stdin=io.StringIO(payload), stdout=out, env={"PROMPT_ENHANCER_PROMPT_CHECK_COMMENTARY": "1"}, opener=opener) == 0
    url, body, token, timeout = seen[0]
    assert url.endswith("/v1/prompt-checks") and url.startswith("http://127.0.0.1:") and token == "example-token-do-not-use"
    assert body["provider"] == "claude_code" and body["want_commentary"] is True and timeout == 45.0
    printed = json.loads(out.getvalue())
    advice = printed["hookSpecificOutput"]["additionalContext"]
    assert printed["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "Task definition coverage: 2/3" in advice and "[high] acceptance: Say when it is done." in advice
    assert "Add retries <specify: how many>" in advice and "rely on earlier conversation" in advice

    # Upstream failure: silent exit 0.
    def failing(request, timeout):
        raise OSError("down")

    out = io.StringIO()
    assert run_prompt_check_hook(settings, stdin=io.StringIO(payload), stdout=out, env={}, opener=failing) == 0
    assert out.getvalue() == ""
    assert len(additional_context_from_result({"summary": "x" * 5000})) <= 3_000


def test_remote_commentary_requires_matching_reviewed_redacted_preview():
    from prompt_enhancer.application.prompt_check import PromptCheckError
    calls = []
    repo = _Repo()

    def chat(alias, body):
        calls.append(json.loads(body))
        return 200, json.dumps({"choices": [{"finish_reason": "stop", "message": {
            "role": "assistant", "content": json.dumps({"reformulated_prompt": "Add a synthetic calculator test; verify that two plus two equals four."})
        }}]}).encode(), "application/json"

    service = PromptCheckService(repo, pseudonymize=Pseudonymizer(bytes(range(32))).pseudonymize, chat=chat,
        active_model=lambda: "example-qwen", remote_model="example-qwen")
    request = PromptCheckRequest(prompt="Add tests. Contact person@example.test; password=example-invalid-secret",
        prior_messages=(PromptCheckMessage(role="user", content="Use /example/private/file.py and 192.0.2.10"),))
    with pytest.raises(PromptCheckError, match="remote_preview_required"):
        service.check(request)
    preview = service.preview(request)
    assert not calls and not repo.rows
    preview_text = json.dumps(preview.messages)
    for canary in ("person@example.test", "example-invalid-secret", "/example/private/file.py", "192.0.2.10"):
        assert canary not in preview_text
    assert "[EMAIL]" in preview_text and "[SECRET]" in preview_text
    with pytest.raises(PromptCheckError, match="remote_preview_required"):
        service.check(request.model_copy(update={"prompt": "Delete the calculator instead.", "remote_approval": preview.approval}))
    result = service.check(request.model_copy(update={"remote_approval": preview.approval}))
    assert result.commentary.state == "ok"
    assert result.commentary.inference_provider == "litellm"
    assert calls[0]["messages"] == list(preview.messages)
    stored = json.dumps([row.model_dump(mode="json") for row in repo.rows])
    assert "example-invalid-secret" not in stored and "reformulated_prompt" not in stored


def test_remote_preview_expires_and_never_reads_provider_sessions():
    from datetime import timedelta
    from prompt_enhancer.application.prompt_check import PromptCheckError
    now = [datetime(2026, 1, 1, tzinfo=UTC)]
    reads, calls = [], []
    service = PromptCheckService(_Repo(), pseudonymize=Pseudonymizer(bytes(range(32))).pseudonymize,
        remote_model="example-qwen", active_model=lambda: "example-qwen",
        chat=lambda *args: calls.append(args), session_context=lambda *args: reads.append(args),
        clock=lambda: now[0])
    request = PromptCheckRequest(prompt=STRONG)
    preview = service.preview(request)
    now[0] += timedelta(seconds=601)
    with pytest.raises(PromptCheckError, match="remote_preview_required"):
        service.check(request.model_copy(update={"remote_approval": preview.approval}))
    for method in (service.preview, service.check):
        with pytest.raises(PromptCheckError, match="remote_session_context_forbidden"):
            method(request.model_copy(update={"session_id": "a" * 64}))
    result = service.check(request.model_copy(update={"want_commentary": False}))
    assert result.commentary.state == "skipped"
    assert not reads and not calls


def test_remote_http_routes_authenticate_preview_and_require_approval(tmp_path):
    from prompt_enhancer.config import LiteLLMSettings
    settings = AppSettings(home=tmp_path / "home", prompt_check_litellm=LiteLLMSettings(
        base_url="https://gateway.example.test/v1", credential="example-invalid-key", model="example-qwen"))
    application = bootstrap_local_application(settings)
    application.database.initialize()
    client = TestClient(application.create_http_app(), base_url="http://127.0.0.1")
    headers = {API_TOKEN_HEADER: settings.api_token_path.read_text().strip()}
    caps = client.get("/v1/capabilities", headers=headers).json()
    assert caps["network_inference"] and caps["prompt_check_network_inference"]
    assert caps["session_text_network_inference"] is True
    assert caps["automatic_session_text_network_inference"] is False
    assert caps["reviewed_inference"] is True
    assert client.get("/v1/prompt-checks/configuration", headers=headers).json()["model"] == "example-qwen"
    payload = {"prompt": "Add a synthetic calculator test. Contact person@example.test."}
    assert client.post("/v1/prompt-checks/preview", json=payload).status_code == 401
    assert client.post("/v1/prompt-checks", json=payload, headers=headers).status_code == 428
    preview = client.post("/v1/prompt-checks/preview", json=payload, headers=headers)
    assert preview.status_code == 200
    assert "no-store" in preview.headers["Cache-Control"]
    assert "person@example.test" not in preview.text
    assert client.get("/v1/prompt-checks", headers=headers).json()["checks"] == []
