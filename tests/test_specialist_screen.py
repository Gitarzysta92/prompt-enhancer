from __future__ import annotations

from dataclasses import replace
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from prompt_enhancer.infrastructure.specialist_screen import backends as specialist_backends
from prompt_enhancer.infrastructure.specialist_screen.backends import (
    MiniLmV2NliBackend,
    SpecialistBackendError,
)
from prompt_enhancer.infrastructure.specialist_screen import loader as specialist_loader
from prompt_enhancer.infrastructure.specialist_screen.contracts import (
    SPECIALIST_LABEL_ORDER,
    SpecialistAbstentionReason,
    SpecialistCompatibility,
    SpecialistLabel,
    SpecialistOutcome,
    SpecialistPrediction,
    SpecialistPredictionState,
)
from prompt_enhancer.infrastructure.specialist_screen.evaluator import (
    DeterministicAbstainingSpecialist,
    OracleGatedNliSpecialist,
    SpecialistCorpusError,
    SPECIALIST_CORPUS_SHA256,
    SPECIALIST_EVALUATOR_VERSION,
    SPECIALIST_METRIC_DEFINITION_VERSION,
    corpus_public_summary,
    evaluate_specialist_predictions,
    load_specialist_corpus,
    run_specialist_candidate,
    run_specialist_screen,
)
from prompt_enhancer.infrastructure.specialist_screen.loader import (
    SpecialistCandidateError,
    prepare_specialist_snapshot,
)
from prompt_enhancer.infrastructure.specialist_screen.manifests import (
    MDEBERTA_HISTORICAL_REJECTION,
    MINILMV2_L6_NLI,
    MINILMV2_L12_NLI,
    SPECIALIST_MODEL_MANIFESTS,
)
from prompt_enhancer.infrastructure.text_models.loader import (
    ModelIntegrityError,
    ModelSnapshotUnavailableError,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "synthetic"
    / "specialists"
    / "scoped_nli_screen_v1.json"
)


def _one_hot(label: SpecialistLabel) -> tuple[tuple[SpecialistLabel, float], ...]:
    return tuple(
        (candidate, 1.0 if candidate is label else 0.0)
        for candidate in SPECIALIST_LABEL_ORDER
    )


class _PerfectBackend:
    def __init__(self) -> None:
        self.received_compatibilities: list[SpecialistCompatibility] = []

    def predict_probabilities(self, cases):  # type: ignore[no-untyped-def]
        self.received_compatibilities.extend(case.compatibility for case in cases)
        return tuple(
            _one_hot(SpecialistLabel(case.expected_outcome.value)) for case in cases
        )


class _LowConfidenceBackend:
    def predict_probabilities(self, cases):  # type: ignore[no-untyped-def]
        return tuple(
            (
                (SpecialistLabel.ENTAILMENT, 0.34),
                (SpecialistLabel.NEUTRAL, 0.33),
                (SpecialistLabel.CONTRADICTION, 0.33),
            )
            for _ in cases
        )


def test_specialist_manifests_are_exact_safe_pins_and_only_reviewed_candidates() -> None:
    assert list(SPECIALIST_MODEL_MANIFESTS) == [
        "multilingual_minilmv2_l6_nli",
        "multilingual_minilmv2_l12_nli",
    ]
    assert MINILMV2_L6_NLI.revision == (
        "0a71e92a985b6e1ad1828cf67ce9c459639c1dca"
    )
    assert MINILMV2_L6_NLI.weight_sha256 == (
        "91b323ccf247ec1e3b5925d566230bae7c52de8147e6062b42e250089a3fc80b"
    )
    assert MINILMV2_L12_NLI.revision == (
        "0d55db361c5f291640208c51ff8c181146aa8eff"
    )
    assert MINILMV2_L12_NLI.weight_sha256 == (
        "47b82b3b1f18a0e4cc5cc80d470d75b3e2278603328b3dd67454b19148d7f85b"
    )
    for manifest in SPECIALIST_MODEL_MANIFESTS.values():
        assert manifest.license_spdx == "MIT"
        assert manifest.trust_remote_code is False
        assert manifest.weight_filename == "model.safetensors"
        assert manifest.tokenizer_revision == manifest.revision
        assert dict(manifest.output_label_by_index) == {
            0: "entailment",
            1: "neutral",
            2: "contradiction",
        }
        assert len(manifest.additional_artifact_files) == 5
        assert "pytorch_model.bin" not in manifest.allowed_snapshot_patterns


def test_mdeberta_rejection_is_immutable_history_not_a_runnable_candidate() -> None:
    record = MDEBERTA_HISTORICAL_REJECTION.public_record()
    assert record == {
        "candidate_key": "mdeberta_xnli",
        "repository_id": (
            "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
        ),
        "revision": "b5113eb38ab63efdd7f280f8c144ea8b13f978ce",
        "decision": "rejected",
        "reason_code": "historical_unscoped_configuration_rejected",
        "benchmark_id": "bilingual_model_screen_v1",
        "synthetic_case_count": 18,
        "runnable_in_this_screen": False,
        "activation_allowed": False,
    }
    assert record["candidate_key"] not in SPECIALIST_MODEL_MANIFESTS


def test_specialist_fixture_is_balanced_bounded_and_scoped() -> None:
    corpus = load_specialist_corpus(FIXTURE)
    assert corpus_public_summary(corpus) == {
        "schema_version": 1,
        "benchmark_id": "specialist_scoped_nli_screen_v1",
        "synthetic_only": True,
        "source_fixture_sha256": SPECIALIST_CORPUS_SHA256,
        "case_count": 24,
        "languages": ["en", "pl"],
        "outcome_counts": {
            "abstain": 6,
            "contradiction": 6,
            "entailment": 6,
            "neutral": 6,
        },
        "compatibility_counts": {
            "compatible": 18,
            "different_scope": 2,
            "insufficient_evidence": 2,
            "superseded": 2,
        },
        "task_stratum_counts": {
            "bug_fix": 6,
            "code_review": 6,
            "feature": 6,
            "research_design": 6,
        },
        "critical_claim_count": 16,
    }
    smoke = corpus.smoke_subset()
    assert len(smoke.cases) == 8
    assert {case.language for case in smoke.cases} == {"en", "pl"}
    assert {case.expected_outcome for case in smoke.cases} == set(
        SpecialistOutcome
    )


def test_specialist_fixture_rejects_extension_fields_and_non_synthetic_data(
    tmp_path: Path,
) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["source_path"] = "fictional-value"
    extended = tmp_path / "extended.json"
    extended.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SpecialistCorpusError, match="invalid_fields"):
        load_specialist_corpus(extended)

    payload.pop("source_path")
    payload["synthetic_only"] = False
    non_synthetic = tmp_path / "non-synthetic.json"
    non_synthetic.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SpecialistCorpusError, match="contract_failed"):
        load_specialist_corpus(non_synthetic)


def test_canonical_specialist_fixture_requires_the_reviewed_digest(
    tmp_path: Path,
) -> None:
    corpus = load_specialist_corpus(
        FIXTURE,
        expected_sha256=SPECIALIST_CORPUS_SHA256,
    )
    assert corpus.source_fixture_sha256 == SPECIALIST_CORPUS_SHA256

    changed = tmp_path / "changed.json"
    changed.write_bytes(FIXTURE.read_bytes() + b"\n")
    with pytest.raises(SpecialistCorpusError, match="sha256_mismatch"):
        load_specialist_corpus(
            changed,
            expected_sha256=SPECIALIST_CORPUS_SHA256,
        )


def test_specialist_fixture_rejects_known_label_for_incompatible_scope(
    tmp_path: Path,
) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["cases"][9]["expected_outcome"] = "contradiction"
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SpecialistCorpusError, match="contract_failed"):
        load_specialist_corpus(invalid)


def test_prediction_contract_distinguishes_unknown_from_zero_confidence() -> None:
    abstained = SpecialistPrediction(
        state=SpecialistPredictionState.ABSTAINED,
        abstention_reason=(
            SpecialistAbstentionReason.BASELINE_REQUIRES_OBJECTIVE_EVIDENCE
        ),
    )
    assert abstained.confidence is None
    assert abstained.raw_label is None

    with pytest.raises(ValueError, match="require label probabilities"):
        SpecialistPrediction(
            state=SpecialistPredictionState.KNOWN,
            label=SpecialistLabel.ENTAILMENT,
        )
    with pytest.raises(ValueError, match="sum to one"):
        SpecialistPrediction(
            state=SpecialistPredictionState.KNOWN,
            label=SpecialistLabel.ENTAILMENT,
            probabilities=(
                (SpecialistLabel.ENTAILMENT, 0.0),
                (SpecialistLabel.NEUTRAL, 0.0),
                (SpecialistLabel.CONTRADICTION, 0.0),
            ),
        )


def test_deterministic_baseline_abstains_without_fabricating_evidence() -> None:
    corpus = load_specialist_corpus(FIXTURE)
    baseline = DeterministicAbstainingSpecialist()
    predictions = baseline.predict(corpus.cases)
    report = evaluate_specialist_predictions(
        corpus.cases,
        predictions,
        backend_key=baseline.key,
    )

    assert report["coverage"] == 0.0
    assert report["corpus_case_count"] == 24
    assert report["evaluated_nli_case_count"] == 18
    assert report["oracle_withheld_count"] == 6
    assert report["overall_typed_accuracy"] == 0.0
    assert report["selective_accuracy"] is None
    assert report["selective_risk"] is None
    assert report["three_way_macro_f1"] == 0.0
    assert report["abstention_precision"] == 0.0
    assert report["abstention_recall"] is None
    assert report["probability_case_count"] == 0
    assert report["multiclass_brier_score"] is None
    assert report["activation_allowed"] is False
    assert report["promotion_allowed"] is False


def test_oracle_compatibility_gate_never_sends_incompatible_cases_to_backend() -> None:
    corpus = load_specialist_corpus(FIXTURE)
    backend = _PerfectBackend()
    specialist = OracleGatedNliSpecialist(backend, confidence_threshold=0.7)
    predictions = specialist.predict(corpus.cases)
    report = evaluate_specialist_predictions(
        corpus.cases,
        predictions,
        backend_key="synthetic_perfect_scoped_nli",
    )

    assert len(backend.received_compatibilities) == 18
    assert set(backend.received_compatibilities) == {
        SpecialistCompatibility.COMPATIBLE
    }
    assert report["coverage"] == 1.0
    assert report["overall_typed_accuracy"] == 1.0
    assert report["selective_accuracy"] == 1.0
    assert report["three_way_macro_f1"] == 1.0
    assert report["multiclass_brier_score"] == 0.0
    assert report["log_loss"] == 0.0
    assert report["expected_calibration_error_10_bin"] == 0.0
    assert report["routing_mode"] == "oracle_fixture_compatibility_labels"
    assert report["router_evaluated"] is False
    assert report["oracle_withheld_count"] == 6
    assert report["router_metrics"] == {
        "state": "not_evaluated",
        "incompatible_known_rate": None,
        "different_scope_contradiction_false_positive_rate": None,
    }


def test_low_confidence_model_abstains_but_retains_aggregate_calibration_inputs() -> None:
    corpus = load_specialist_corpus(FIXTURE)
    specialist = OracleGatedNliSpecialist(
        _LowConfidenceBackend(),
        confidence_threshold=0.7,
    )
    predictions = specialist.predict(corpus.cases)
    report = evaluate_specialist_predictions(
        corpus.cases,
        predictions,
        backend_key="synthetic_low_confidence_nli",
    )

    assert report["coverage"] == 0.0
    assert report["selective_accuracy"] is None
    assert report["probability_case_count"] == 18
    assert report["multiclass_brier_score"] is not None
    assert report["expected_calibration_error_10_bin"] is not None
    for case, prediction in zip(corpus.cases, predictions, strict=True):
        if case.compatibility is SpecialistCompatibility.COMPATIBLE:
            assert prediction.abstention_reason is SpecialistAbstentionReason.LOW_CONFIDENCE
            assert prediction.probabilities
        else:
            assert not prediction.probabilities


def test_aggregate_report_never_contains_fixture_text_or_paths() -> None:
    corpus = load_specialist_corpus(FIXTURE)
    predictions = OracleGatedNliSpecialist(
        _PerfectBackend(), confidence_threshold=0.7
    ).predict(corpus.cases)
    report = evaluate_specialist_predictions(
        corpus.cases,
        predictions,
        backend_key="synthetic_aggregate_only",
    )
    rendered = json.dumps(report, ensure_ascii=False)
    for forbidden in (
        "The metric export requires",
        "Eksport metryk wymaga",
        str(FIXTURE),
        "premise",
        "hypothesis",
    ):
        assert forbidden not in rendered


def test_specialist_loader_is_offline_by_default_and_uses_existing_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    cache = repository / "runtime" / "model-eval" / "specialist-screen"
    snapshot = cache / "models--fictional" / "snapshots" / MINILMV2_L6_NLI.revision
    snapshot.mkdir(parents=True)
    calls: list[dict[str, object]] = []

    def fake_prepare(manifest, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"manifest": manifest, **kwargs})
        return snapshot

    monkeypatch.setattr(specialist_loader, "prepare_model_snapshot", fake_prepare)
    prepared = prepare_specialist_snapshot(
        MINILMV2_L6_NLI,
        cache_root=cache,
        repo_root=repository,
    )

    assert prepared.snapshot == snapshot
    assert len(calls) == 1
    call = calls[0]
    delegated_manifest = call.pop("manifest")
    assert delegated_manifest.key == MINILMV2_L6_NLI.key
    assert delegated_manifest.allowed_snapshot_patterns == tuple(
        filename
        for filename, _ in (
            *MINILMV2_L6_NLI.weight_files,
            *MINILMV2_L6_NLI.additional_artifact_files,
        )
    )
    assert call == {
        "cache_root": cache.resolve(),
        "allow_download": False,
        "downloader": None,
        "file_downloader": None,
        "repo_root": repository,
    }


def test_specialist_loader_rejects_manifest_drift_before_cache_or_network(
    tmp_path: Path,
) -> None:
    drifted = replace(MINILMV2_L6_NLI, weight_sha256="f" * 64)
    with pytest.raises(SpecialistCandidateError, match="unregistered"):
        prepare_specialist_snapshot(
            drifted,
            cache_root=tmp_path / "runtime" / "model-eval" / "specialist-screen",
            repo_root=tmp_path,
        )


def test_specialist_snapshot_rejects_safe_but_undeclared_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    cache = repository / "runtime" / "model-eval" / "specialist-screen"
    weight = b"fictional-reviewed-safetensors"
    config = b"{}"
    tokenizer = b"{}"
    manifest = replace(
        MINILMV2_L6_NLI,
        key="fictional_minilm_nli",
        repository_id="example-org/fictional-minilm",
        revision="a" * 40,
        tokenizer_repository_id="example-org/fictional-minilm",
        tokenizer_revision="a" * 40,
        weight_sha256=hashlib.sha256(weight).hexdigest(),
        additional_artifact_files=(
            ("config.json", hashlib.sha256(config).hexdigest()),
            ("tokenizer.json", hashlib.sha256(tokenizer).hexdigest()),
        ),
    )
    snapshot = cache / "snapshots" / manifest.revision
    snapshot.mkdir(parents=True)
    (snapshot / "model.safetensors").write_bytes(weight)
    (snapshot / "config.json").write_bytes(config)
    (snapshot / "tokenizer.json").write_bytes(tokenizer)
    # Globally supported by the shared loader, but absent from this specialist
    # manifest's exact hash-declared list.
    (snapshot / "generation_config.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        specialist_loader,
        "require_registered_specialist_manifest",
        lambda _: None,
    )
    with pytest.raises(
        ModelIntegrityError,
        match="unexpected_snapshot_artifact_rejected",
    ):
        prepare_specialist_snapshot(
            manifest,
            cache_root=cache,
            downloader=lambda **_: str(snapshot),
            repo_root=repository,
        )


def test_unavailable_candidate_is_typed_and_does_not_claim_a_measurement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = load_specialist_corpus(FIXTURE).smoke_subset()

    def unavailable(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise ModelSnapshotUnavailableError("model_snapshot_unavailable")

    monkeypatch.setattr(
        "prompt_enhancer.infrastructure.specialist_screen.evaluator.prepare_specialist_snapshot",
        unavailable,
    )
    result = run_specialist_candidate(corpus, MINILMV2_L6_NLI)

    assert result["status"] == "unavailable"
    assert result["failure_code"] == "model_cache_missing_or_invalid"
    assert result["metrics"] is None
    assert result["runtime"] is None
    assert result["activation_allowed"] is False
    assert result["promotion_allowed"] is False


def test_candidate_backend_is_closed_after_a_completed_bounded_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = load_specialist_corpus(FIXTURE).smoke_subset()

    class LifecycleBackend(_PerfectBackend):
        closed = False

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *args):  # type: ignore[no-untyped-def]
            self.closed = True

        def runtime_observation(self):  # type: ignore[no-untyped-def]
            return {"device": "synthetic", "inference_latency_ms": 0.0}

    backend = LifecycleBackend()
    monkeypatch.setattr(
        "prompt_enhancer.infrastructure.specialist_screen.evaluator.prepare_specialist_snapshot",
        lambda *args, **kwargs: SimpleNamespace(snapshot=tmp_path),
    )
    monkeypatch.setattr(
        "prompt_enhancer.infrastructure.specialist_screen.evaluator.isolated_hugging_face_environment",
        lambda *args, **kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        "prompt_enhancer.infrastructure.specialist_screen.evaluator.MiniLmV2NliBackend",
        lambda *args, **kwargs: backend,
    )

    result = run_specialist_candidate(corpus, MINILMV2_L6_NLI)
    assert result["status"] == "completed"
    assert backend.closed is True


def test_partial_backend_init_failure_releases_resources_before_next_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    model_number = 0
    tokenizer_number = 0

    class FakeTokenizer:
        def __init__(self, number: int) -> None:
            self.number = number

        def close(self) -> None:
            events.append(f"tokenizer_{self.number}_closed")

    class FakeModel:
        def __init__(self, number: int) -> None:
            self.number = number
            self.config = SimpleNamespace(
                id2label=(
                    {0: "contradiction", 1: "neutral", 2: "entailment"}
                    if number == 1
                    else {0: "entailment", 1: "neutral", 2: "contradiction"}
                )
            )

        def to(self, device: str):  # type: ignore[no-untyped-def]
            events.append(f"model_{self.number}_to_{device}")
            return self

        def eval(self) -> None:
            events.append(f"model_{self.number}_eval")

        def close(self) -> None:
            events.append(f"model_{self.number}_closed")

    class FakeAutoTokenizer:
        @staticmethod
        def from_pretrained(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal tokenizer_number
            tokenizer_number += 1
            events.append(f"tokenizer_{tokenizer_number}_loaded")
            return FakeTokenizer(tokenizer_number)

    class FakeAutoModel:
        @staticmethod
        def from_pretrained(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal model_number
            model_number += 1
            events.append(f"model_{model_number}_loaded")
            return FakeModel(model_number)

    fake_torch = ModuleType("torch")
    fake_torch.manual_seed = lambda _: events.append("torch_seeded")  # type: ignore[attr-defined]
    fake_torch.cuda = SimpleNamespace(  # type: ignore[attr-defined]
        manual_seed_all=lambda _: events.append("cuda_seeded"),
        empty_cache=lambda: events.append("cuda_cache_emptied"),
        reset_peak_memory_stats=lambda: events.append("cuda_peak_reset"),
    )
    fake_transformers = ModuleType("transformers")
    fake_transformers.AutoTokenizer = FakeAutoTokenizer  # type: ignore[attr-defined]
    fake_transformers.AutoModelForSequenceClassification = FakeAutoModel  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setattr(specialist_backends, "resolve_device", lambda _: "cuda")
    monkeypatch.setattr(specialist_backends, "_process_rss_mb", lambda: 0.0)
    monkeypatch.setattr(
        specialist_backends.gc,
        "collect",
        lambda: events.append("gc_collected") or 0,
    )

    with pytest.raises(SpecialistBackendError, match="label_order_mismatch"):
        MiniLmV2NliBackend(MINILMV2_L6_NLI, tmp_path, device="cuda")

    assert events.index("model_1_to_cpu") < events.index("model_1_closed")
    assert events.index("model_1_closed") < events.index("tokenizer_1_closed")
    assert events.index("tokenizer_1_closed") < events.index("gc_collected")
    cache_empty_positions = [
        index
        for index, event in enumerate(events)
        if event == "cuda_cache_emptied"
    ]
    assert len(cache_empty_positions) == 2
    first_cleanup = cache_empty_positions[1]
    assert events.index("gc_collected") < first_cleanup

    second = MiniLmV2NliBackend(MINILMV2_L12_NLI, tmp_path, device="cuda")
    assert first_cleanup < events.index("tokenizer_2_loaded")
    second.close()
    second.close()
    assert events.count("model_2_closed") == 1
    assert events.count("tokenizer_2_closed") == 1


def test_screen_serializes_only_two_candidates_and_keeps_history_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    corpus = load_specialist_corpus(FIXTURE).smoke_subset()
    observed: list[str] = []

    def fake_run(corpus, manifest, **kwargs):  # type: ignore[no-untyped-def]
        observed.append(manifest.key)
        return {
            "candidate": manifest.public_pin(),
            "status": "unavailable",
            "metrics": None,
            "runtime": None,
            "activation_allowed": False,
            "promotion_allowed": False,
        }

    monkeypatch.setattr(
        "prompt_enhancer.infrastructure.specialist_screen.evaluator.run_specialist_candidate",
        fake_run,
    )
    result = run_specialist_screen(corpus)

    assert observed == list(SPECIALIST_MODEL_MANIFESTS)
    assert result["serialized_execution"] is True
    assert result["screen_tier"] == "bounded_foundation_pre_screen"
    assert result["evaluator_version"] == SPECIALIST_EVALUATOR_VERSION
    assert result["metric_definition_version"] == (
        SPECIALIST_METRIC_DEFINITION_VERSION
    )
    assert result["routing_mode"] == "oracle_fixture_compatibility_labels"
    assert result["router_evaluated"] is False
    assert result["promotion_screen_minimum_case_count"] == 96
    assert result["promotion_screen_gate_met"] is False
    assert set(result["runtime_dependencies"]) == {
        "python",
        "huggingface_hub",
        "safetensors",
        "sentencepiece",
        "torch",
        "transformers",
    }
    assert result["activation_allowed"] is False
    assert result["promotion_allowed"] is False
    assert len(result["candidates"]) == 2
    assert result["historical_rejections"] == [
        MDEBERTA_HISTORICAL_REJECTION.public_record()
    ]
    assert result["omitted_candidate_families"] == [
        "bge_zero_shot",
        "qwen_structured_rubric",
    ]
