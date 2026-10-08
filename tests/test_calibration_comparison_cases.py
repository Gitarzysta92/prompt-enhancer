"""Agreement needs matching reviewed evidence, not just a matching session id."""

from types import SimpleNamespace

import pytest

from prompt_enhancer.application.analysis.calibration_ratings import RatingLabel
from prompt_enhancer.application.analysis.model_judge import JUDGE_PROMPT_VERSION, ModelJudgment
from tests.test_structured_model_replies import NOW, SESSION, _Repository, _judge


CASE = "d" * 64
WINDOW = "b" * 64
METRIC = "prompt.task_definition_coverage"
CASE_VERSION = "calibration-case.v1"
RATING_VERSION = "calibration-rating-v2-reviewed-case"


def _comparison(*, model_changes=None, rating_changes=None):
    row = ModelJudgment(**{
        "session_id": SESSION, "metric_key": METRIC, "label": RatingLabel.HIGH,
        "model_alias": "example-model", "model_identity": "example-model.gguf",
        "prompt_version": JUDGE_PROMPT_VERSION, "window_fingerprint": WINDOW, "judged_at": NOW,
        "case_fingerprint": CASE, "case_version": CASE_VERSION, **(model_changes or {}),
    })
    rating = SimpleNamespace(
        **{
            "rater_id": "e" * 64, "session_id": SESSION, "metric_key": METRIC,
            "label": RatingLabel.HIGH, "rated_at": NOW, "revision": 1,
            "case_fingerprint": CASE, "case_version": CASE_VERSION,
            "window_fingerprint": WINDOW, "rating_version": RATING_VERSION,
            **(rating_changes or {}),
        }
    )
    repository = _Repository()
    repository.rows = [row]
    service = _judge(repository, lambda *_args: pytest.fail("agreement must not invoke inference"), (rating,))
    return service, repository


@pytest.mark.parametrize("changes", (
    {"case_fingerprint": "f" * 64},
    {"case_fingerprint": None, "case_version": None},
    {"case_version": "example-unknown-case-version"},
    {"window_fingerprint": "f" * 64},
    {"rating_version": "calibration-rating-v1"},
), ids=("different-rendered-window", "unbound-legacy-rating", "different-case-protocol", "different-source-window", "unbound-rating-protocol"))
def test_ratings_for_different_or_unknown_evidence_do_not_become_pairs(changes):
    service, repository = _comparison(rating_changes=changes)
    original = tuple(repository.rows)
    report = service.agreement()
    assert report.metrics[0].pairs == 0
    assert report.metrics[0].agreement_rate is None
    assert report.metrics[0].cohen_kappa is None
    assert report.metrics[0].unmatched_ratings == 1
    assert tuple(repository.rows) == original


@pytest.mark.parametrize("changes", (
    {"case_fingerprint": None, "case_version": None},
    {"case_version": "example-unknown-case-version"},
    {"model_identity": "example-other-model.gguf"},
), ids=("unbound-model-case", "unknown-model-case", "replaced-model-identity"))
def test_unbound_or_different_model_evidence_is_not_a_current_pair(changes):
    service, repository = _comparison(model_changes=changes)
    report = service.agreement()
    assert report.metrics[0].pairs == 0
    assert len(service.judgments_for(SESSION).judgments) == len(repository.rows) == 1


@pytest.mark.parametrize("abstainer", ("human", "model", "both"))
def test_cannot_judge_is_an_abstention_not_agreement_or_disagreement(abstainer):
    service, _repository = _comparison(
        model_changes={"label": RatingLabel.CANNOT_JUDGE} if abstainer != "human" else {},
        rating_changes={"label": RatingLabel.CANNOT_JUDGE} if abstainer != "model" else {},
    )
    report = service.agreement()
    assert report.metrics[0].pairs == 0
    assert report.metrics[0].agreement_rate is None
    assert report.metrics[0].abstained_pairs == 1


def test_matching_known_case_still_forms_a_pair():
    service, _repository = _comparison()
    assert service.agreement().metrics[0].pairs == 1


def test_agreement_and_kappa_use_only_matching_nonabstaining_pairs():
    service, repository = _comparison()
    prototype = repository.rows[0]
    labels = ((RatingLabel.HIGH, RatingLabel.HIGH), (RatingLabel.MEDIUM, RatingLabel.HIGH),
              (RatingLabel.LOW, RatingLabel.LOW), (RatingLabel.MEDIUM, RatingLabel.MEDIUM))
    ratings = []
    repository.rows = []
    for index, (model_label, human_label) in enumerate(labels, 1):
        sid = f"{index:064x}"
        case = f"{index + 8:064x}"
        repository.rows.append(prototype.model_copy(update={"session_id": sid, "case_fingerprint": case, "label": model_label}))
        ratings.append(SimpleNamespace(session_id=sid, metric_key=METRIC, label=human_label, rating_version=RATING_VERSION,
                                       case_fingerprint=case, case_version=CASE_VERSION, window_fingerprint=WINDOW))
    ratings.extend((
        SimpleNamespace(**{**vars(ratings[0]), "label": RatingLabel.CANNOT_JUDGE}),
        SimpleNamespace(**{**vars(ratings[1]), "case_fingerprint": "e" * 64}),
    ))
    service = _judge(repository, lambda *_args: pytest.fail("must not invoke inference"), tuple(ratings))
    result = service.agreement().metrics[0]
    assert result.pairs == 4 and result.unmatched_ratings == 1 and result.abstained_pairs == 1
    assert result.agreement_rate == pytest.approx(3 / 4)
    assert result.cohen_kappa == pytest.approx(7 / 11)


def test_explicit_alias_never_pools_multiple_recorded_model_identities():
    service, repository = _comparison()
    repository.rows.append(repository.rows[0].model_copy(update={"session_id": "f" * 64, "model_identity": "example-other.gguf"}))
    current = service.agreement()
    assert current.model_identity == "example-model.gguf" and current.metrics[0].pairs == 1
    assert current.excluded_judgments == 1
    service._active_model = lambda: pytest.fail("an explicit alias report must work offline")
    ambiguous = service.agreement("example-model")
    assert ambiguous.model_identity is None and ambiguous.model_identity_ambiguous
    assert ambiguous.excluded_judgments == 2 and ambiguous.judged_sessions == 0
    assert ambiguous.metrics[0].agreement_rate is None
