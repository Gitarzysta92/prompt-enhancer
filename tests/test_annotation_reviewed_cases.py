"""Synthetic annotation receipts never upgrade unknown evidence to reviewed cases."""
from contextlib import closing
import json
import sqlite3

import pytest

from prompt_enhancer.application.analysis.calibration_ratings import CALIBRATION_METRIC_KEYS, RatingLabel
from prompt_enhancer.application.analysis.model_judge import eligible_model_judgment
from prompt_enhancer.application.annotation import (
    AnnotationError, AnnotationService, CentralAnnotation, CentralAnnotationServer,
    CentralAnnotationStore, CentralBatch, CentralBatchItem, CentralBatchResult,
    RemoteAnnotationClient, RemoteSubmitRequest, SubmitAnnotation,
)
from tests.test_structured_model_replies import NOW, SESSION, _Repository, _envelope, _judge


LABELS = {key: RatingLabel.HIGH for key in CALIBRATION_METRIC_KEYS}


def _services():
    repository = _Repository()
    rows = [{"session_id": SESSION, "provider": "synthetic", "project_id": "e" * 64}]
    listing = lambda *, limit, offset: rows[offset:offset + limit]
    service = AnnotationService(_judge(repository, lambda *_args: pytest.fail("no inference in an agent annotation")), list_sessions=listing, clock=lambda: NOW)
    service.set_allowance(True)
    return service, repository, listing


@pytest.mark.parametrize("protocol", ("bound", "legacy", "partial-labels"))
def test_work_completion_requires_all_labels_for_a_known_case(protocol):
    service, repository, _listing = _services()
    window = service.window(SESSION)
    case = {} if protocol == "legacy" else {"case_fingerprint": window.case_fingerprint, "case_version": window.case_version}
    labels = {CALIBRATION_METRIC_KEYS[0]: RatingLabel.HIGH} if protocol == "partial-labels" else LABELS
    result = service.submit(SubmitAnnotation(session_id=SESSION, model_name="example-agent", window_fingerprint=window.window_fingerprint, labels=labels, **case))
    assert result.stored == len(labels)
    assert service.work("example-agent").remaining == (0 if protocol == "bound" else 1)
    assert all(eligible_model_judgment(row) for row in repository.rows) == (protocol != "legacy")
    assert "example module" not in json.dumps([row.model_dump(mode="json") for row in repository.rows])


@pytest.mark.parametrize("changes", ({"case_fingerprint": "f" * 64}, {"case_version": "example-unknown"}, {"case_version": None}))
def test_agent_cannot_repoint_a_submitted_case(changes):
    service, repository, _listing = _services()
    window = service.window(SESSION)
    request = SubmitAnnotation(**{"session_id": SESSION, "model_name": "example-agent", "window_fingerprint": window.window_fingerprint,
                                  "case_fingerprint": window.case_fingerprint, "case_version": window.case_version, "labels": LABELS, **changes})
    with pytest.raises(AnnotationError, match="^case_fingerprint_mismatch$"):
        service.submit(request)
    assert repository.rows == []


@pytest.mark.parametrize("defect", ("none", "wrong-case", "wrong-source", "wrong-protocol", "partial-labels", "missing-model", "legacy", "duplicate"))
def test_remote_response_is_counted_from_verified_local_receipts_not_server_claims(defect):
    service, repository, listing = _services()
    sent = []
    def submit(batch):
        sent.extend(batch.items)
        item = batch.items[0]
        changes = {
            "wrong-case": {"case_fingerprint": "f" * 64}, "wrong-source": {"window_fingerprint": "f" * 64},
            "wrong-protocol": {"case_version": "example-unknown"}, "partial-labels": {"labels": {CALIBRATION_METRIC_KEYS[0]: RatingLabel.HIGH}},
            "legacy": {"case_fingerprint": None, "case_version": None, "window_fingerprint": None},
        }.get(defect, {})
        annotation = CentralAnnotation(**{"session_id": SESSION, "labels": LABELS, "case_fingerprint": item.case_fingerprint,
                                          "case_version": item.case_version, "window_fingerprint": item.window_fingerprint, **changes})
        return CentralBatchResult(stored=99, model_identity=None if defect == "missing-model" else "example-central",
                                  annotations=(annotation, annotation) if defect == "duplicate" else (annotation,))
    client = RemoteAnnotationClient(service, submit=submit, destination="embedded synthetic test server", user_label="example", list_sessions=listing, clock=lambda: NOW)
    result = client.submit_batch(RemoteSubmitRequest(limit=1))
    expected = 1 if defect in {"none", "missing-model", "legacy", "duplicate"} else 0
    assert result.submitted == 1 and result.annotated == expected and len(repository.rows) == expected * 3
    assert sent[0].case_fingerprint is not None and sent[0].window_fingerprint is not None
    if expected:
        assert all(eligible_model_judgment(row) for row in repository.rows) == (defect in {"none", "duplicate"})


def test_central_seals_the_actual_window_and_closes_its_sqlite_connections(tmp_path, monkeypatch):
    service, _repository, _listing = _services()
    window = service.window(SESSION)
    connections = []
    connect = sqlite3.connect
    def tracked(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection
    monkeypatch.setattr(sqlite3, "connect", tracked)
    path = tmp_path / "example-central.sqlite3"
    store = CentralAnnotationStore(path)
    server = CentralAnnotationServer(store, chat=lambda *_args: (200, json.dumps(_envelope(json.dumps({key: value.value for key, value in LABELS.items()}))).encode(), "application/json"), active_model=lambda: "example-central", clock=lambda: NOW)
    item = CentralBatchItem(session_id=SESSION, provider="synthetic", window=window.window, case_fingerprint=window.case_fingerprint, case_version=window.case_version, window_fingerprint=window.window_fingerprint)
    result = server.annotate_batch(CentralBatch(user_label="example", items=(item,)))
    assert store.count() == result.stored == 1
    assert result.annotations[0].case_fingerprint == window.case_fingerprint
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    with closing(connect(path)) as connection:
        stored = connection.execute("SELECT case_fingerprint, case_version, window_fingerprint FROM central_annotations").fetchone()
        assert stored == (window.case_fingerprint, window.case_version, window.window_fingerprint)
    invalid = item.model_copy(update={"case_fingerprint": "f" * 64})
    assert server.annotate_batch(CentralBatch(user_label="example", items=(invalid,))).stored == 0
