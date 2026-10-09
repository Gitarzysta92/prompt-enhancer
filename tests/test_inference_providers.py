"""Synthetic inference boundaries; no provider sessions or external model calls."""
from __future__ import annotations
import json
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from prompt_enhancer.api import create_app, API_TOKEN_HEADER
from prompt_enhancer.application.inference import InferenceError, InferenceModel, InferenceRegistry, InferenceStream
from prompt_enhancer.application.inference_review import ReviewedInference, InferenceReviewRequired, InferenceSelection, inference_selection
from prompt_enhancer.application.runtime_cancellation import RuntimeCooperativeStop, runtime_request_scope
from prompt_enhancer.bootstrap import bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.infrastructure.local_inference import LocalInferenceProvider
from prompt_enhancer.infrastructure.redaction.deterministic import DeterministicLocalRedactor


class Provider:
    provider_id = "litellm"
    def __init__(self, remote=True):
        self.remote = remote
        self.calls = []
        self.reply = "Synthetic answer."
    def models(self):
        return (InferenceModel(id="example-model", name="example-model", provider="litellm" if self.remote else "local",
            remote=self.remote, available=True, availability="configured" if self.remote else "running", adapter_version="synthetic.v1"),)
    def complete(self, alias, body):
        self.calls.append((alias, json.loads(body)))
        return 200, json.dumps({"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": self.reply}}]}).encode(), "application/json"
    def open_chat(self, alias, body):
        self.calls.append((alias, json.loads(body)))
        chunks = [b'data: {"choices":[{"delta":{"content":"Synthetic answer."},"finish_reason":null}]}\n\n',
                  b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n', b'data: [DONE]\n\n']
        return InferenceStream(200, "text/event-stream", lines=iter(chunks))


def setup(remote=True, clock=None):
    provider = Provider(remote)
    redactor = DeterministicLocalRedactor()
    kwargs = {} if clock is None else {"clock": clock}
    service = ReviewedInference(InferenceRegistry((provider,)),
        redact=lambda value: redactor.redact(SecretStr(value)).text.get_secret_value(), redactor_version=redactor.version, **kwargs)
    return provider, service


def body(text="Synthetic calculator question."):
    return json.dumps({"messages": [{"role": "user", "content": text}], "max_tokens": 100}).encode()


def test_remote_does_not_depend_on_owned_local_runtime():
    class UnavailableRuntime:
        def overview(self): raise RuntimeError("synthetic local registry unavailable")
        def chat(self, *args): pytest.fail("local inference must not run")
    remote = Provider()
    registry = InferenceRegistry((LocalInferenceProvider(UnavailableRuntime()), remote))
    assert registry.catalog().unavailable_providers == ("local",)
    assert registry.resolve("example-model")[0] is remote
    assert not registry.available("missing-model")
    assert not hasattr(registry, "activate") and not hasattr(registry, "stop")


def test_local_provider_delegates_without_external_review():
    provider, service = setup(remote=False)
    assert service.complete("example-model", body(), "chat")[0] == 200
    assert len(provider.calls) == 1


def test_preview_redacts_without_egress_then_sends_exact_reviewed_body_once():
    provider, service = setup()
    raw = body("Email alex@example.test. password=example-invalid-canary")
    preview = service.preview("example-model", raw, "chat")
    assert provider.calls == []
    rendered = json.dumps(preview.request)
    assert "alex@example.test" not in rendered and "example-invalid-canary" not in rendered
    service.complete("example-model", raw, "chat", approval=preview.approval)
    assert provider.calls[0][1] == preview.request
    with pytest.raises(InferenceError, match="inference_preview_required"):
        service.complete("example-model", raw, "chat", approval=preview.approval)
    assert len(provider.calls) == 1


@pytest.mark.parametrize("change", ["text", "parameters", "purpose", "expired", "missing"])
def test_review_cannot_authorize_changed_or_unreviewed_requests(change):
    clock = [1000.0]; provider, service = setup(clock=lambda: clock[0])
    raw = body(); preview = service.preview("example-model", raw, "chat")
    purpose = "chat"; approval = preview.approval
    if change == "text": raw = body("Changed synthetic request")
    if change == "parameters": raw = raw.replace(b'100', b'101')
    if change == "purpose": purpose = "judge"
    if change == "expired": clock[0] += 601
    if change == "missing": approval = None
    with pytest.raises(InferenceError, match="inference_preview_required"):
        service.complete("example-model", raw, purpose, approval=approval)
    assert provider.calls == []


def test_preview_response_repr_never_contains_text_or_approval():
    _, service = setup()
    value = service.preview("example-model", body("Fictional review content."), "chat")
    assert "Fictional review content." not in repr(value)
    assert value.approval not in repr(value)


def wait_pending(service, scope):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        rows = service.pending(scope)
        if rows: return rows[0]
        time.sleep(.01)
    pytest.fail("Synthetic review did not arrive")


@pytest.mark.parametrize("decision", ["accept", "decline", "stop"])
def test_agent_review_is_scoped_cancelable_and_ephemeral(decision):
    provider, service = setup(); cancelled = threading.Event(); outcomes = []
    def run():
        try:
            with runtime_request_scope(cancelled):
                outcomes.append(service.wait_for_agent_review("example-session", "example-model", body()))
        except (InferenceError, RuntimeCooperativeStop) as error:
            outcomes.append(error)
    thread = threading.Thread(target=run); thread.start()
    try:
        pending = wait_pending(service, "example-session")
        assert service.pending("different-session") == ()
        with pytest.raises(InferenceError): service.decide("different-session", pending.id, accepted=True)
        assert provider.calls == []
        if decision == "stop": cancelled.set()
        else: service.decide("example-session", pending.id, accepted=decision == "accept")
        thread.join(2); assert not thread.is_alive()
        assert isinstance(outcomes[0], bytes if decision == "accept" else Exception)
        assert service.pending("example-session") == ()
        with pytest.raises(InferenceError): service.decide("example-session", pending.id, accepted=True)
    finally:
        cancelled.set(); thread.join(3)


def test_authenticated_http_preview_stream_and_manual_analysis(tmp_path):
    provider, service = setup()
    app = create_app(settings=AppSettings(home=tmp_path, session_reader_enabled=False),
        api_token="example-invalid-application-token-for-tests", inference_service=service)
    headers = {API_TOKEN_HEADER: "example-invalid-application-token-for-tests"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/v1/inference/models").status_code == 401
        assert client.get("/v1/inference/models", headers=headers).json()["models"][0]["availability"] == "configured"
        request = {"model_id": "example-model", "messages": [{"role": "user", "content": "Synthetic calculator question."}]}
        assert client.post("/v1/inference/chat", headers=headers, json=request).status_code == 428
        preview = client.post("/v1/inference/chat/preview", headers=headers, json=request)
        assert preview.status_code == 200 and provider.calls == []
        response = client.post("/v1/inference/chat", headers=headers, json={**request, "approval": preview.json()["approval"]})
        assert response.status_code == 200 and "Synthetic answer." in response.text
        assert response.headers["cache-control"] == "no-store"
        provider.reply = json.dumps({"summary": "A fictional calculator test.", "strengths": [], "improvements": [], "reframed_prompt": None})
        manual = {"model_id": "example-model", "kind": "interpret", "text": "Write a fictional calculator unit test."}
        review = client.post("/v1/inference/analysis/preview", headers=headers, json=manual)
        assert review.status_code == 200
        result = client.post("/v1/inference/analysis", headers=headers, json={**manual, "approval": review.json()["approval"]})
        assert result.status_code == 200, result.text
        assert result.json()["persisted"] is False
        assert result.json()["result"]["summary"] == "A fictional calculator test."


def test_model_judge_uses_selected_provider_and_preview_does_not_write(tmp_path):
    from prompt_enhancer.application.analysis.text_contracts import EphemeralRedactedMessage, TextLanguage, TextMessageKind, TextRole
    provider, inference = setup()
    provider.reply = json.dumps({"prompt.task_definition_coverage": "high", "prompt.context_sufficiency": "medium", "outcome.verification_strategy_adequacy": "cannot_judge"})
    application = bootstrap_local_application(AppSettings(home=tmp_path, session_reader_enabled=False))
    runtime = SimpleNamespace(overview=lambda: SimpleNamespace(models=()), chat=lambda *args: pytest.fail("local model called"))
    judge, _ = application.create_model_judge_service(runtime, inference=inference)
    judge._session_lookup = lambda value: SimpleNamespace(provider="codex")
    judge._window = lambda *args: SimpleNamespace(analysis_window_fingerprint="b" * 64, messages=(
        EphemeralRedactedMessage(message_id="a" * 64, sequence=0, role=TextRole.USER,
            kind=TextMessageKind.REQUEST, language=TextLanguage.ENGLISH, text=SecretStr("Check the example calculator.")),))
    saved = []; judge._repository = SimpleNamespace(upsert=saved.append)
    with inference_selection(InferenceSelection("example-model", "judge", preview=True)):
        with pytest.raises(InferenceReviewRequired) as required:
            judge.judge("c" * 64)
    assert provider.calls == [] and saved == []
    with inference_selection(InferenceSelection("example-model", "judge", required.value.preview.approval)):
        outcome = judge.judge("c" * 64)
    assert outcome.raw_valid and len(saved) == 3
    provenance = json.loads(saved[0].model_identity)
    assert provenance["provider"] == "litellm" and provenance["redactor"] == inference.redactor_version


@pytest.mark.parametrize("accept", [True, False])
def test_agent_turn_waits_for_review_without_changing_workspace_authority(tmp_path, accept):
    from prompt_enhancer.application.local_agent import AgentSettings, LocalAgentService, SendMessage
    provider, inference = setup()
    workspace = tmp_path / "example-project"; workspace.mkdir()
    agent = LocalAgentService(chat=provider.complete, open_chat=provider.open_chat,
        active_model=lambda: "example-model", model_ready=lambda alias: alias == "example-model",
        inference_review=inference.wait_for_agent_review)
    session = agent.create(AgentSettings(workspace=str(workspace), model_alias="example-model", allow_writes=False, allow_commands=False))
    try:
        agent.send(session.session_id, SendMessage(text="Explain a fictional calculator."))
        pending = wait_pending(inference, session.session_id)
        assert provider.calls == []
        assert agent.get(session.session_id).settings.allow_writes is False
        inference.decide(session.session_id, pending.id, accepted=accept)
        worker = agent._session(session.session_id).thread
        worker.join(3); assert not worker.is_alive()
        assert len(provider.calls) == (1 if accept else 0)
        assert not agent.get(session.session_id).running
        assert list(workspace.iterdir()) == []
    finally:
        agent.shutdown()


def test_agent_reviews_new_tool_results_and_stop_releases_pending_review(tmp_path):
    from prompt_enhancer.application.local_agent import AgentSettings, LocalAgentService, SendMessage
    provider, inference = setup()
    workspace = tmp_path / "example-project"; workspace.mkdir()
    (workspace / "example.txt").write_text("Synthetic contact: alex@example.test.", encoding="utf-8")
    calls = []
    def chat(alias, request):
        calls.append(json.loads(request))
        message = {"role": "assistant", "content": "", "tool_calls": [{"id": "example-call", "type": "function",
            "function": {"name": "read_file", "arguments": json.dumps({"path": "example.txt"})}}]}
        return 200, json.dumps({"choices": [{"finish_reason": "tool_calls", "message": message}]}).encode(), "application/json"
    agent = LocalAgentService(chat=chat, active_model=lambda: "example-model",
        model_ready=lambda alias: True, inference_review=inference.wait_for_agent_review)
    session = agent.create(AgentSettings(workspace=str(workspace), model_alias="example-model", allow_writes=False, allow_commands=False))
    try:
        agent.send(session.session_id, SendMessage(text="Explain example.txt."))
        first = wait_pending(inference, session.session_id)
        inference.decide(session.session_id, first.id, accepted=True)
        second = wait_pending(inference, session.session_id)
        assert second.id != first.id and len(calls) == 1
        messages = second.preview.request["messages"]
        assert messages[-1]["role"] == "tool"
        assert "alex@example.test" not in json.dumps(messages[-1])
        assert "Synthetic contact" in json.dumps(messages[-1])
        worker = agent._session(session.session_id).thread
        agent.stop(session.session_id)
        worker.join(3)
        assert not worker.is_alive() and inference.pending(session.session_id) == ()
        assert len(calls) == 1
        assert (workspace / "example.txt").read_text() == "Synthetic contact: alex@example.test."
    finally:
        agent.shutdown()


def test_review_fails_closed_when_redaction_fails():
    provider = Provider()
    def unavailable(text): raise ValueError("synthetic redactor unavailable")
    service = ReviewedInference(InferenceRegistry((provider,)), redact=unavailable, redactor_version="synthetic.v1")
    with pytest.raises(InferenceError, match="inference_request_invalid"):
        service.preview("example-model", body(), "chat")
    assert provider.calls == []


def test_concurrent_replay_sends_only_once():
    from concurrent.futures import ThreadPoolExecutor
    provider, service = setup()
    request = body(); preview = service.preview("example-model", request, "chat")
    def attempt():
        try:
            return service.complete("example-model", request, "chat", approval=preview.approval)[0]
        except InferenceError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: attempt(), range(2)), key=lambda value: value or 0) == [None, 200]
    assert len(provider.calls) == 1


def test_empty_manual_interpretation_is_not_reported_as_success():
    from prompt_enhancer.application.manual_analysis import ManualAnalysisRequest, analyze_manual, manual_body
    provider, service = setup()
    provider.reply = json.dumps({"summary": None, "strengths": [], "improvements": [], "reframed_prompt": None})
    request = ManualAnalysisRequest(model_id="example-model", kind="interpret", text="Synthetic request.")
    preview = service.preview(request.model_id, manual_body(request), "manual-interpret")
    with pytest.raises(InferenceError, match="model_reply_invalid"):
        analyze_manual(service, request.model_copy(update={"approval": preview.approval}))


def test_browser_review_requires_same_origin_csrf(tmp_path):
    from prompt_enhancer.api import CSRF_HEADER
    provider, service = setup()
    app = create_app(settings=AppSettings(home=tmp_path, session_reader_enabled=False),
        api_token="example-invalid-application-token-for-tests", inference_service=service)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        session = client.get("/auth/session", headers={"Sec-Fetch-Site": "same-origin"})
        assert session.status_code == 200
        request = {"model_id": "example-model", "messages": [{"role": "user", "content": "Synthetic request."}]}
        assert client.post("/v1/inference/chat/preview", json=request).status_code == 403
        headers = {"Origin": "http://127.0.0.1", CSRF_HEADER: session.json()["csrf_token"]}
        assert client.post("/v1/inference/chat/preview", headers={**headers, "Origin": "https://example.test"}, json=request).status_code == 403
        assert client.post("/v1/inference/chat/preview", headers=headers, json=request).status_code == 200
        assert provider.calls == []


def test_local_adapter_projects_only_verified_provenance_and_translates_errors():
    from prompt_enhancer.application.local_models import LocalModelError, RuntimeState, RuntimeStatus
    record = SimpleNamespace(alias="example-local", display_name="Example local", provenance_verified=True,
        source_revision="a" * 40, source_license="apache-2.0")
    def fail(*args): raise LocalModelError("runtime_unreachable")
    runtime = SimpleNamespace(overview=lambda: SimpleNamespace(models=(SimpleNamespace(record=record,
        runtime=RuntimeStatus(state=RuntimeState.RUNNING)),)), chat=fail, open_chat=fail)
    provider = LocalInferenceProvider(runtime)
    model = provider.models()[0]
    assert model.available and not model.remote
    assert model.revision == "a" * 40 and model.license == "apache-2.0"
    assert model.tools is None and model.context_tokens is None
    record.provenance_verified = False
    assert provider.models()[0].revision is None
    for call in (provider.complete, provider.open_chat):
        with pytest.raises(InferenceError, match="model_error"):
            call(model.id, body())
