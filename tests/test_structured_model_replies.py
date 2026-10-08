"""Synthetic completion receipts must precede commentary or judgment acceptance."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from types import SimpleNamespace

from pydantic import SecretStr
import pytest

from prompt_enhancer.application.analysis.calibration_ratings import CALIBRATION_METRIC_KEYS
from prompt_enhancer.application.analysis.model_judge import (
    CURRENT_JUDGE_PROMPT_VERSIONS,
    ModelJudgeError,
    ModelJudgeService,
    parse_judge_reply,
    render_window,
)
from prompt_enhancer.application.analysis.text_contracts import (
    EphemeralRedactedMessage,
    TextLanguage,
    TextMessageKind,
    TextRole,
)
from prompt_enhancer.application.annotation import (
    AnnotationService,
    CentralAnnotationServer,
    CentralBatch,
    CentralBatchItem,
    CentralBatchResult,
    RemoteAnnotationClient,
    RemoteSubmitRequest,
)
from prompt_enhancer.application.prompt_check import (
    PromptCheckRequest,
    PromptCheckService,
    parse_commentary_reply,
)
from prompt_enhancer.domain import Provider
from prompt_enhancer.privacy import Pseudonymizer
from tests.test_model_judge_availability import _client


SESSION = "a" * 64
NOW = datetime(2026, 8, 26, 10, tzinfo=UTC)
LANES = ("judge", "interpretation", "prompt_check", "central")
LABELS = {key: "high" for key in CALIBRATION_METRIC_KEYS}
COMMENTARY = {
    "findings": [{"aspect": "scope", "severity": "low", "why": "Scope is broad.", "suggestion": "Name the module."}],
    "reformulated_prompt": "Review the example module; report the checks performed.",
    "reformulated_elements": [],
    "notes": "Synthetic model suggestion.",
}
INTERPRETATION = {
    "summary": "The synthetic request names its target.",
    "strengths": ["Names the example module."],
    "improvements": ["State the expected result."],
    "reframed_prompt": "Review the example module and report the checks performed.",
}


class _Repository:
    def __init__(self) -> None:
        self.rows = []

    def upsert(self, row) -> None:
        self.rows = [old for old in self.rows if (old.session_id, old.metric_key, old.model_alias) != (row.session_id, row.metric_key, row.model_alias)]
        self.rows.append(row)

    def insert(self, row) -> None:
        self.rows.append(row)

    def list(self, *, session_id=None, model_alias=None):
        return tuple(row for row in self.rows if (session_id is None or row.session_id == session_id) and (model_alias is None or row.model_alias == model_alias))

    def store(self, *values) -> None:
        self.rows.append(values)


def _window():
    return SimpleNamespace(
        session_id=SESSION,
        provider=Provider.SYNTHETIC,
        analysis_window_fingerprint="b" * 64,
        messages=(EphemeralRedactedMessage(
            message_id="c" * 64, sequence=0, role=TextRole.USER,
            kind=TextMessageKind.REQUEST, language=TextLanguage.ENGLISH,
            text=SecretStr("Review the example module; report the checks performed."),
        ),),
    )


def _judge(repository, chat, ratings=()):
    return ModelJudgeService(
        repository=repository,
        ratings=SimpleNamespace(list_ratings=lambda: ratings),
        access=SimpleNamespace(has_active_consent=lambda *_args: True),
        source_factory=lambda _provider: SimpleNamespace(read=lambda **_kwargs: _window()),
        chat=chat,
        active_model=lambda: ("example-model", "example-model.gguf"),
        session_lookup=lambda _sid: SimpleNamespace(provider=Provider.SYNTHETIC),
        clock=lambda: NOW,
    )


def _content(lane):
    return json.dumps(COMMENTARY if lane == "prompt_check" else INTERPRETATION if lane == "interpretation" else LABELS)


def _envelope(content):
    return {"choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}]}


def _payload(lane, defect):
    value = _envelope(_content(lane))
    choice = value["choices"][0]
    if defect.startswith("finish:"):
        choice["finish_reason"] = defect.split(":", 1)[1]
    elif defect == "missing-receipt":
        del choice["finish_reason"]
    elif defect == "null-receipt":
        choice["finish_reason"] = None
    elif defect == "boolean-receipt":
        choice["finish_reason"] = True
    elif defect == "missing-role":
        del choice["message"]["role"]
    elif defect == "wrong-role":
        choice["message"]["role"] = "user"
    elif defect == "tool-call":
        choice["message"]["tool_calls"] = [{"type": "function", "function": {"name": "example", "arguments": "{}"}}]
    elif defect == "legacy-function":
        choice["message"]["function_call"] = {"name": "example", "arguments": "{}"}
    elif defect == "refusal":
        choice["message"]["refusal"] = "Synthetic refusal."
    elif defect == "multiple-choices":
        value["choices"].append(_envelope(_content(lane))["choices"][0])
    elif defect == "wrong-index":
        choice["index"] = 1
    elif defect == "boolean-index":
        choice["index"] = False
    elif defect == "nontext-content":
        choice["message"]["content"] = {"example": "synthetic"}
    elif defect == "duplicate-receipt":
        return json.dumps(value).replace('"finish_reason": "stop"', '"finish_reason": "length", "finish_reason": "stop"').encode()
    elif defect == "envelope-error":
        value["error"] = {"message": "Synthetic runtime failure."}
    else:
        raise AssertionError("unknown synthetic defect")
    return json.dumps(value).encode()


def _accepted(lane, payload, repository):
    chat = lambda _alias, _body: (200, payload, "application/json")
    if lane in {"judge", "interpretation"}:
        service = _judge(repository, chat)
        try:
            if lane == "judge":
                return service.judge(SESSION).raw_valid
            service.interpret(SESSION)
            return True
        except ModelJudgeError as error:
            assert error.code == "model_reply_invalid"
            assert str(error) == "model_reply_invalid"
            return False
    if lane == "central":
        service = CentralAnnotationServer(repository, chat=chat, active_model=lambda: "example-model", clock=lambda: NOW)
        result = service.annotate_batch(CentralBatch(user_label="example", items=(CentralBatchItem(session_id=SESSION, provider="synthetic", window=render_window(_window())),)))
        assert result.stored == len(result.annotations) == len(repository.rows)
        return result.stored > 0
    request = PromptCheckRequest(prompt="Add bounded retries to the example uploader; done when the unit tests pass.")
    service = PromptCheckService(repository, pseudonymize=Pseudonymizer(bytes(range(32))).pseudonymize, chat=chat, active_model=lambda: "example-model", clock=lambda: NOW)
    result = service.check(request)
    deterministic = PromptCheckService(_Repository(), pseudonymize=Pseudonymizer(bytes(range(32))).pseudonymize, clock=lambda: NOW).check(request.model_copy(update={"want_commentary": False}))
    assert result.metrics == deterministic.metrics
    assert result.context == deterministic.context
    assert len(repository.rows) == 1
    assert repository.rows[0].commentary_state == result.commentary.state
    assert COMMENTARY["notes"] not in repository.rows[0].model_dump_json()
    assert result.commentary.state in {"ok", "reply_invalid"}
    return result.commentary.state == "ok"


@pytest.mark.parametrize("lane", LANES)
@pytest.mark.parametrize("defect", (
    "finish:length", "finish:content_filter", "finish:tool_calls", "finish:unknown",
    "missing-receipt", "null-receipt", "boolean-receipt", "missing-role", "wrong-role",
    "tool-call", "legacy-function", "refusal", "multiple-choices", "wrong-index",
    "boolean-index", "nontext-content", "duplicate-receipt", "envelope-error",
))
def test_incomplete_or_ambiguous_model_result_is_never_accepted(lane, defect):
    repository = _Repository()
    assert not _accepted(lane, _payload(lane, defect), repository)
    if lane != "prompt_check":
        assert repository.rows == []


@pytest.mark.parametrize("lane", LANES)
@pytest.mark.parametrize("wrapper", ("plain", "fenced"))
def test_complete_synthetic_result_is_accepted(lane, wrapper):
    text = _content(lane)
    if wrapper == "fenced":
        text = "```json\n" + text + "\n```"
    assert _accepted(lane, json.dumps(_envelope(text)).encode(), _Repository())


@pytest.mark.parametrize("lane", LANES)
@pytest.mark.parametrize("defect", ("prose-prefix", "prose-suffix", "duplicate-key", "array-root", "nonfinite", "deep-json"))
def test_invalid_inner_json_is_not_salvaged_into_a_result(lane, defect):
    text = _content(lane)
    if defect == "prose-prefix":
        text = "Synthetic untrusted instructions. " + text
    elif defect == "prose-suffix":
        text += " Synthetic untrusted instructions."
    elif defect == "duplicate-key":
        first = next(iter(json.loads(text)))
        text = '{' + json.dumps(first) + ': null,' + text[1:]
    elif defect == "array-root":
        text = "[]"
    elif defect == "nonfinite":
        text = text[:-1] + ', "extra": NaN}'
    elif defect == "deep-json":
        text = '[' * 2_000 + '0' + ']' * 2_000
    assert not _accepted(lane, json.dumps(_envelope(text)).encode(), _Repository())


@pytest.mark.parametrize("invalid", (
    {"notes": {"unexpected": "synthetic"}},
    {"findings": "unexpected", "notes": "Synthetic note."},
    {"findings": [{"aspect": "weird", "severity": "urgent", "why": "x", "suggestion": "y"}]},
    {"findings": [{"aspect": "goal", "severity": "high", "why": 42, "suggestion": "y"}]},
    {"findings": [{"aspect": "goal", "severity": "high", "why": " ", "suggestion": "y"}]},
    {"findings": [{"aspect": "goal", "severity": "high", "why": "x", "suggestion": "y", "extra": True}]},
    {"reformulated_elements": ["unexpected"], "notes": "Synthetic note."},
    {"reformulated_prompt": "x" * 2_021},
    {"notes": "Synthetic note.", "extra": True},
), ids=("nontext-note", "nonlist-findings", "unknown-labels", "nontext-reason", "blank-reason", "extra-finding-key", "nonobject-element", "oversized-rewrite", "unknown-key"))
def test_commentary_schema_rejects_invalid_fields_instead_of_inventing_defaults(invalid):
    assert parse_commentary_reply(json.dumps(invalid), prompt_chars=10) is None


@pytest.mark.parametrize("invalid", (None, True, 3, {}, [], ["example"]))
def test_judge_parser_has_a_total_content_free_failure_boundary(invalid):
    assert parse_judge_reply(invalid) is None


@pytest.mark.parametrize("invalid", (
    {}, [], {"summary": 123}, {"summary": " "}, {"summary": "Synthetic note.", "extra": True},
    {"summary": "Synthetic note.", "strengths": [123]},
    {"summary": "Synthetic note.", "improvements": ["x"] * 4},
    {"summary": "x" * 601},
), ids=("empty", "array", "nontext", "blank", "extra-key", "coerced-item", "oversized-list", "oversized-summary"))
def test_interpretation_rejects_empty_or_malformed_content(invalid):
    assert not _accepted("interpretation", json.dumps(_envelope(json.dumps(invalid))).encode(), _Repository())


def test_failed_regeneration_preserves_the_last_valid_labels_and_can_recover():
    repository = _Repository()
    payloads = iter((
        json.dumps(_envelope(json.dumps(LABELS))).encode(),
        _payload("judge", "finish:length"),
        json.dumps(_envelope(json.dumps({key: "low" for key in LABELS}))).encode(),
    ))
    service = _judge(repository, lambda *_args: (200, next(payloads), "application/json"))
    assert service.judge(SESSION).raw_valid
    original = tuple(repository.rows)
    with pytest.raises(ModelJudgeError, match="^model_reply_invalid$"):
        service.judge(SESSION)
    assert tuple(repository.rows) == original
    assert service.judge(SESSION).raw_valid
    assert len(repository.rows) == len(LABELS)
    assert {row.label.value for row in repository.rows} == {"low"}


@pytest.mark.parametrize("legacy_version", ("judge-v3-untrusted-json-anchor-15k", "judge-v3-untrusted-json-anchor-6k", "example-unknown-version"))
def test_historical_unchecked_judgments_remain_readable_but_cannot_enter_current_agreement(legacy_version):
    repository = _Repository()
    service = _judge(repository, lambda *_args: (200, json.dumps(_envelope(json.dumps(LABELS))).encode(), "application/json"))
    service.judge(SESSION)
    repository.rows[1:] = [row.model_copy(update={"prompt_version": legacy_version}) for row in repository.rows[1:]]
    original = tuple(repository.rows)
    ratings = tuple(SimpleNamespace(
        session_id=SESSION, metric_key=row.metric_key, label=row.label,
        case_fingerprint=row.case_fingerprint, case_version=row.case_version,
        window_fingerprint=row.window_fingerprint, rating_version="calibration-rating-v2-reviewed-case",
    ) for row in repository.rows)
    service = _judge(repository, lambda *_args: pytest.fail("agreement must not invoke a model"), ratings)

    report = service.agreement()
    assert report.judged_sessions == 1
    assert [metric.pairs for metric in report.metrics] == [1, 0, 0]
    assert all(metric.agreement_rate is None for metric in report.metrics[1:])
    assert report.excluded_judgments == 2
    assert set(report.accepted_prompt_versions) == CURRENT_JUDGE_PROMPT_VERSIONS
    assert service.judgments_for(SESSION).judgments
    assert tuple(repository.rows) == original


def test_an_all_historical_report_remains_unknown_not_zero_agreement():
    repository = _Repository()
    service = _judge(repository, lambda *_args: (200, json.dumps(_envelope(json.dumps(LABELS))).encode(), "application/json"))
    service.judge(SESSION)
    repository.rows = [row.model_copy(update={"prompt_version": "judge-v3-untrusted-json-anchor-15k"}) for row in repository.rows]
    report = service.agreement()
    assert report.judged_sessions == 0
    assert report.excluded_judgments == 3
    assert all(metric.pairs == 0 and metric.agreement_rate is None and metric.cohen_kappa is None and metric.state == "insufficient_data" for metric in report.metrics)


@pytest.mark.parametrize("defect", ("finish:length", "nontext-content", "duplicate-receipt"))
def test_central_batch_skips_invalid_completion_and_continues_to_a_valid_item(defect):
    repository = _Repository()
    responses = iter((_payload("central", defect), json.dumps(_envelope(json.dumps(LABELS))).encode()))
    server = CentralAnnotationServer(repository, chat=lambda *_args: (200, next(responses), "application/json"), active_model=lambda: "example-model", clock=lambda: NOW)
    result = server.annotate_batch(CentralBatch(user_label="example", items=tuple(
        CentralBatchItem(session_id=sid, provider="synthetic", window=render_window(_window())) for sid in (SESSION, "d" * 64)
    )))
    assert result.stored == 1
    assert [row.session_id for row in result.annotations] == ["d" * 64]
    assert len(repository.rows) == 1
    assert repository.rows[0][1].session_id == "d" * 64


@pytest.mark.parametrize("path", ("agent", "central"))
@pytest.mark.parametrize("historical", (True, False))
def test_explicit_annotation_work_does_not_skip_historical_protocol_results(path, historical):
    repository = _Repository()
    judge = _judge(repository, lambda *_args: (200, json.dumps(_envelope(json.dumps(LABELS))).encode(), "application/json"))
    judge.judge(SESSION)
    repository.rows = [row.model_copy(update={
        "model_alias": f"{path}:example-model",
        "prompt_version": "judge-v3-untrusted-json-anchor-15k" if historical else row.prompt_version,
    }) for row in repository.rows]
    original = tuple(repository.rows)
    sessions = lambda *, limit, offset: [{"session_id": SESSION, "provider": "synthetic"}] if offset == 0 else []
    service = AnnotationService(judge, list_sessions=sessions)
    if path == "agent":
        service.set_allowance(True)
        work = service.work("example-model")
        assert work.remaining == int(historical)
    else:
        submissions = []

        def submit(batch):
            submissions.append(batch)
            return CentralBatchResult(stored=0, annotations=(), model_identity="example-model")

        remote = RemoteAnnotationClient(service, submit=submit, destination="embedded synthetic server", user_label="example", list_sessions=sessions)
        result = remote.submit_batch(RemoteSubmitRequest(limit=1))
        assert result.submitted == len(submissions) == int(historical)
    assert tuple(repository.rows) == original


@pytest.mark.parametrize("version", tuple(CURRENT_JUDGE_PROMPT_VERSIONS))
def test_reserved_legacy_window_identity_is_not_current_agreement(version):
    repository = _Repository()
    service = _judge(repository, lambda *_args: (200, json.dumps(_envelope(json.dumps(LABELS))).encode(), "application/json"))
    service.judge(SESSION)
    # Simulate a readable legacy row without inventing its missing fingerprint.
    repository.rows = [row.model_copy(update={"prompt_version": version, "window_fingerprint": "0" * 64}) for row in repository.rows]
    report = service.agreement()
    assert report.judged_sessions == 0 and report.excluded_judgments == 3
    assert len(service.judgments_for(SESSION).judgments) == 3


@pytest.mark.parametrize("lane", ("judge", "interpretation"))
def test_actual_judge_service_has_closed_http_failure_and_successful_retry(lane):
    repository = _Repository()
    responses = iter((_payload(lane, "finish:length"), json.dumps(_envelope(_content(lane))).encode()))
    service = _judge(repository, lambda *_args: (200, next(responses), "application/json"))
    # The same router harness as the availability suite: real service and JSON
    # serialization, synthetic dependency, no app settings or runtime process.
    with _client(service) as client:
        path = f"/v1/model-judge/sessions/{SESSION}" + ("/interpret" if lane == "interpretation" else "")
        failed = client.post(path)
        assert failed.status_code == 502
        assert failed.json() == {"detail": {"code": "model_reply_invalid"}}
        assert repository.rows == []
        retried = client.post(path)
        assert retried.status_code == 200
        assert retried.json()["session_id"] == SESSION
        if lane == "judge":
            assert retried.json()["raw_valid"] is True
            assert len(repository.rows) == 3
        else:
            assert retried.json()["summary"] == INTERPRETATION["summary"]
            assert retried.json()["prompt_version"] == "interpret-v2-complete-json"
