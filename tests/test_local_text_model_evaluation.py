from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path

import pytest

from prompt_enhancer.infrastructure.text_models.benchmark import (
    LexicalBm25Scorer,
    RubricPrediction,
    SyntheticCorpusError,
    corpus_public_summary,
    evaluate_nli,
    evaluate_retrieval,
    evaluate_rubric,
    load_synthetic_corpus,
    load_synthetic_rubric_corpus,
    rubric_corpus_public_summary,
)
from prompt_enhancer.infrastructure.text_models.loader import (
    ModelCacheBoundaryError,
    ModelIntegrityError,
    isolated_hugging_face_environment,
    prepare_model_snapshot,
    transformers_network_closed,
    validate_model_cache_root,
)
from prompt_enhancer.infrastructure.text_models.manifests import (
    BGE_M3,
    BGE_M3_BLOCKED,
    BGE_M3_LEGACY_BLOCKED,
    BGE_RERANKER_V2_M3,
    DEBERTA_SMALL_LONG_NLI,
    E5_MULTILINGUAL_BASE,
    E5_MULTILINGUAL_SMALL,
    MDEBERTA_XNLI,
    MODERNBERT_BASE_ZEROSHOT,
    QWEN3_4B_RUBRIC,
    QWEN3_EMBEDDING_06B,
    QWEN3_RERANKER_06B,
    BLOCKED_TEXT_MODEL_MANIFESTS,
    TEXT_MODEL_MANIFESTS,
    ModelManifest,
    TextModelTask,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "synthetic"
    / "text_models"
    / "bilingual_model_screen_v1.json"
)
RUBRIC_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "synthetic"
    / "text_models"
    / "bilingual_rubric_screen_v1.json"
)


def _test_manifest(weight: bytes, *, sha256: str | None = None) -> ModelManifest:
    return ModelManifest(
        key="example_embedding",
        task=TextModelTask.REQUIREMENT_ACTION_RETRIEVAL,
        repository_id="example-org/example-model",
        revision="a" * 40,
        tokenizer_repository_id="example-org/example-model",
        tokenizer_revision="a" * 40,
        license_spdx="MIT",
        weight_filename="model.safetensors",
        weight_sha256=sha256 or hashlib.sha256(weight).hexdigest(),
        max_sequence_length=64,
        max_batch_size=4,
    )


def _fake_snapshot(
    root: Path,
    weight: bytes,
    *,
    include_config: bool = True,
) -> Path:
    snapshot = root / "snapshots" / ("a" * 40)
    snapshot.mkdir(parents=True)
    if include_config:
        (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "tokenizer.json").write_text("{}", encoding="utf-8")
    (snapshot / "model.safetensors").write_bytes(weight)
    return snapshot


def test_candidate_manifests_are_exact_pins_without_remote_code() -> None:
    assert E5_MULTILINGUAL_SMALL.revision == (
        "614241f622f53c4eeff9890bdc4f31cfecc418b3"
    )
    assert E5_MULTILINGUAL_SMALL.weight_sha256 == (
        "1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477"
    )
    assert E5_MULTILINGUAL_BASE.revision == (
        "d128750597153bb5987e10b1c3493a34e5a4502a"
    )
    assert E5_MULTILINGUAL_BASE.weight_sha256 == (
        "a18a44fad1d0b46ded15928144138cff1135d5cc8233bdd90be5f18822de09a7"
    )
    assert BGE_M3.revision == "142964af7e05de16511657561de8e8750fc153a0"
    assert BGE_M3.weight_sha256 == (
        "993b2248881724788dcab8c644a91dfd63584b6e5604ff2037cb5541e1e38e7e"
    )
    assert BGE_M3.architecture == "xlm_roberta_cls"
    assert len(BGE_M3.additional_artifact_files) == 9
    assert dict(BGE_M3.additional_artifact_files)["tokenizer.json"] == (
        "21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08"
    )
    assert MDEBERTA_XNLI.revision == (
        "b5113eb38ab63efdd7f280f8c144ea8b13f978ce"
    )
    assert MDEBERTA_XNLI.weight_sha256 == (
        "7c8e29f1115986d032e92b0fbaa0bdef1062a46f658b08705f237c05014a8541"
    )
    assert DEBERTA_SMALL_LONG_NLI.revision == (
        "9a77395d4d3751be9e2a69c4ae318491d9b3fffb"
    )
    assert DEBERTA_SMALL_LONG_NLI.weight_sha256 == (
        "9af30c7ad7235a2054300bc2df1d98149ad6008dd1ef06212be8b32b5d1b3458"
    )
    assert DEBERTA_SMALL_LONG_NLI.max_sequence_length == 1_680
    assert MODERNBERT_BASE_ZEROSHOT.revision == (
        "d421c4545a438fd006fb43f8b981c5d908faa1e1"
    )
    assert MODERNBERT_BASE_ZEROSHOT.weight_sha256 == (
        "5af4dac82bf3da16575d0c71c8c96ee7eb6621ae5f4f4726943d0a3583b44b46"
    )
    assert MODERNBERT_BASE_ZEROSHOT.task is TextModelTask.BINARY_NLI
    assert MODERNBERT_BASE_ZEROSHOT.max_sequence_length == 2_048
    assert BGE_RERANKER_V2_M3.revision == "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
    assert QWEN3_EMBEDDING_06B.revision == "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
    assert QWEN3_RERANKER_06B.revision == "e61197ed45024b0ed8a2d74b80b4d909f1255473"
    assert QWEN3_4B_RUBRIC.revision == "cdbee75f17c01a7cc42f958dc650907174af0554"
    assert len(TEXT_MODEL_MANIFESTS) == 10
    for manifest in TEXT_MODEL_MANIFESTS.values():
        assert manifest.trust_remote_code is False
        assert all(filename.endswith(".safetensors") for filename, _ in manifest.weight_files)
        assert manifest.revision == manifest.tokenizer_revision
        assert manifest.max_sequence_length <= 2_048
        assert manifest.max_batch_size <= 32

    assert BGE_M3_BLOCKED is BGE_M3_LEGACY_BLOCKED
    assert BLOCKED_TEXT_MODEL_MANIFESTS == {
        "bge_m3_legacy_pickle_pin": BGE_M3_LEGACY_BLOCKED
    }
    assert BGE_M3_LEGACY_BLOCKED.blocked_reason == "unsafe_pickle_only"
    assert BGE_M3_LEGACY_BLOCKED.reviewed_artifact == "pytorch_model.bin"

    public_pin = BGE_M3.public_pin()
    assert len(public_pin["additional_artifact_files"]) == 9
    assert "pytorch_model.bin" not in BGE_M3.allowed_snapshot_patterns


def test_manifest_rejects_remote_code_and_movable_revision() -> None:
    fields = E5_MULTILINGUAL_SMALL.__dict__ if hasattr(E5_MULTILINGUAL_SMALL, "__dict__") else None
    assert fields is None  # slots also reduce accidental mutation surface
    with pytest.raises(ValueError, match="40-character"):
        ModelManifest(
            key="invalid_model",
            task=TextModelTask.REQUIREMENT_ACTION_RETRIEVAL,
            repository_id="example-org/example-model",
            revision="main",
            tokenizer_repository_id="example-org/example-model",
            tokenizer_revision="a" * 40,
            license_spdx="MIT",
            weight_filename="model.safetensors",
            weight_sha256="b" * 64,
            max_sequence_length=64,
            max_batch_size=4,
        )
    with pytest.raises(ValueError, match="trust_remote_code"):
        ModelManifest(
            key="invalid_model",
            task=TextModelTask.REQUIREMENT_ACTION_RETRIEVAL,
            repository_id="example-org/example-model",
            revision="a" * 40,
            tokenizer_repository_id="example-org/example-model",
            tokenizer_revision="a" * 40,
            license_spdx="MIT",
            weight_filename="model.safetensors",
            weight_sha256="b" * 64,
            max_sequence_length=64,
            max_batch_size=4,
            trust_remote_code=True,
        )
    with pytest.raises(ValueError, match="tokenizer and model pin"):
        replace(E5_MULTILINGUAL_SMALL, tokenizer_revision="b" * 40)
    with pytest.raises(ValueError, match="auxiliary artifact filename"):
        replace(
            E5_MULTILINGUAL_SMALL,
            additional_artifact_files=(("custom_model.py", "b" * 64),),
        )
    with pytest.raises(ValueError, match="auxiliary artifact SHA-256"):
        replace(
            E5_MULTILINGUAL_SMALL,
            additional_artifact_files=(("config.json", "not-a-digest"),),
        )


def test_cache_is_confined_to_runtime_model_eval(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    allowed = validate_model_cache_root(
        repository / "runtime" / "model-eval" / "candidate",
        repo_root=repository,
    )
    assert allowed == (
        repository / "runtime" / "model-eval" / "candidate"
    ).resolve()
    with pytest.raises(ModelCacheBoundaryError, match="cache_outside"):
        validate_model_cache_root(repository / "models", repo_root=repository)


def test_transformers_inference_offline_flags_are_scoped_and_restored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HF_HUB_OFFLINE", "prior-value")
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)

    with transformers_network_closed():
        assert os.environ["HF_HUB_OFFLINE"] == "1"
        assert os.environ["TRANSFORMERS_OFFLINE"] == "1"

    assert os.environ["HF_HUB_OFFLINE"] == "prior-value"
    assert "TRANSFORMERS_OFFLINE" not in os.environ


def test_hugging_face_state_is_scoped_to_the_isolated_task_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "repository"
    cache = repository / "runtime" / "model-eval"
    monkeypatch.setenv("HF_HOME", "prior-value")
    monkeypatch.delenv("HF_TOKEN_PATH", raising=False)

    with isolated_hugging_face_environment(cache, repo_root=repository) as isolated:
        assert isolated == cache.resolve()
        for name in (
            "HF_HOME",
            "HF_HUB_CACHE",
            "HF_ASSETS_CACHE",
            "HF_TOKEN_PATH",
            "HF_STORED_TOKENS_PATH",
            "SENTENCE_TRANSFORMERS_HOME",
        ):
            configured = Path(os.environ[name]).resolve()
            assert configured == isolated or isolated in configured.parents

    assert os.environ["HF_HOME"] == "prior-value"
    assert "HF_TOKEN_PATH" not in os.environ


def test_offline_snapshot_resolution_passes_no_token_and_verifies_hash(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    cache = repository / "runtime" / "model-eval"
    weight = b"fictional-safetensors-placeholder"
    manifest = _test_manifest(weight)
    calls: list[dict[str, object]] = []

    def downloader(**kwargs: object) -> str:
        calls.append(kwargs)
        return str(_fake_snapshot(cache, weight))

    snapshot = prepare_model_snapshot(
        manifest,
        cache_root=cache,
        allow_download=False,
        downloader=downloader,
        repo_root=repository,
    )

    assert snapshot.is_dir()
    assert calls == [
        {
            "repo_id": manifest.repository_id,
            "revision": manifest.revision,
            "cache_dir": str(cache.resolve()),
            "allow_patterns": list(manifest.allowed_snapshot_patterns),
            "local_files_only": True,
            "token": False,
            "max_workers": 4,
        }
    ]


def test_explicit_download_can_materialize_only_the_missing_public_config(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    cache = repository / "runtime" / "model-eval"
    weight = b"fictional-safetensors-placeholder"
    manifest = _test_manifest(weight)
    snapshot = _fake_snapshot(cache, weight, include_config=False)
    file_calls: list[dict[str, object]] = []

    def snapshot_downloader(**_: object) -> str:
        return str(snapshot)

    def file_downloader(**kwargs: object) -> str:
        file_calls.append(kwargs)
        config = snapshot / "config.json"
        config.write_text("{}", encoding="utf-8")
        return str(config)

    prepared = prepare_model_snapshot(
        manifest,
        cache_root=cache,
        allow_download=True,
        downloader=snapshot_downloader,
        file_downloader=file_downloader,
        repo_root=repository,
    )

    assert prepared == snapshot.resolve()
    assert file_calls == [
        {
            "repo_id": manifest.repository_id,
            "filename": "config.json",
            "revision": manifest.revision,
            "cache_dir": str(cache.resolve()),
            "local_files_only": False,
            "token": False,
        }
    ]


def test_snapshot_rejects_hash_mismatch_and_pickle_weight(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    cache = repository / "runtime" / "model-eval"
    weight = b"fictional-safetensors-placeholder"
    manifest = _test_manifest(weight, sha256="f" * 64)

    def mismatched(**_: object) -> str:
        return str(_fake_snapshot(cache, weight))

    with pytest.raises(ModelIntegrityError, match="sha256_mismatch"):
        prepare_model_snapshot(
            manifest,
            cache_root=cache,
            downloader=mismatched,
            repo_root=repository,
        )

    repository_two = tmp_path / "repository-two"
    cache_two = repository_two / "runtime" / "model-eval"
    manifest_two = _test_manifest(weight)

    def unsafe(**_: object) -> str:
        snapshot = _fake_snapshot(cache_two, weight)
        (snapshot / "pytorch_model.bin").write_bytes(b"fictional-pickle-placeholder")
        return str(snapshot)

    with pytest.raises(ModelIntegrityError, match="unsafe_model_artifact"):
        prepare_model_snapshot(
            manifest_two,
            cache_root=cache_two,
            downloader=unsafe,
            repo_root=repository_two,
        )


def test_snapshot_verifies_declared_auxiliary_artifact_hashes(tmp_path: Path) -> None:
    weight = b"fictional-safetensors-placeholder"
    expected = b"fictional-reviewed-tokenizer-config"
    manifest = replace(
        _test_manifest(weight),
        additional_artifact_files=(
            ("tokenizer_config.json", hashlib.sha256(expected).hexdigest()),
        ),
    )

    missing_repository = tmp_path / "missing-repository"
    missing_cache = missing_repository / "runtime" / "model-eval"
    with pytest.raises(ModelIntegrityError, match="auxiliary_artifact_missing"):
        prepare_model_snapshot(
            manifest,
            cache_root=missing_cache,
            downloader=lambda **_: str(_fake_snapshot(missing_cache, weight)),
            repo_root=missing_repository,
        )

    mismatch_repository = tmp_path / "mismatch-repository"
    mismatch_cache = mismatch_repository / "runtime" / "model-eval"

    def mismatched_auxiliary(**_: object) -> str:
        snapshot = _fake_snapshot(mismatch_cache, weight)
        (snapshot / "tokenizer_config.json").write_bytes(b"fictional-mismatch")
        return str(snapshot)

    with pytest.raises(ModelIntegrityError, match="auxiliary_artifact_sha256_mismatch"):
        prepare_model_snapshot(
            manifest,
            cache_root=mismatch_cache,
            downloader=mismatched_auxiliary,
            repo_root=mismatch_repository,
        )


def test_snapshot_rejects_unreviewed_prepopulated_artifact(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    cache = repository / "runtime" / "model-eval"
    weight = b"fictional-safetensors-placeholder"
    manifest = _test_manifest(weight)

    def poisoned(**_: object) -> str:
        snapshot = _fake_snapshot(cache, weight)
        (snapshot / "custom_model.py").write_text(
            "raise RuntimeError('fictional custom code')",
            encoding="utf-8",
        )
        return str(snapshot)

    with pytest.raises(ModelIntegrityError, match="unexpected_snapshot_artifact"):
        prepare_model_snapshot(
            manifest,
            cache_root=cache,
            downloader=poisoned,
            repo_root=repository,
        )


def test_snapshot_path_must_identify_the_declared_revision(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    cache = repository / "runtime" / "model-eval"
    weight = b"fictional-safetensors-placeholder"
    manifest = _test_manifest(weight)
    snapshot = cache / manifest.revision
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    (snapshot / "tokenizer.json").write_text("{}", encoding="utf-8")
    (snapshot / "model.safetensors").write_bytes(weight)

    with pytest.raises(ModelIntegrityError, match="snapshot_revision_path_mismatch"):
        prepare_model_snapshot(
            manifest,
            cache_root=cache,
            downloader=lambda **_: str(snapshot),
            repo_root=repository,
        )


def test_snapshot_rejects_config_symlink_outside_isolated_cache(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    cache = repository / "runtime" / "model-eval"
    weight = b"fictional-safetensors-placeholder"
    manifest = _test_manifest(weight)
    snapshot = _fake_snapshot(cache, weight)
    config = snapshot / "config.json"
    config.unlink()
    outside = tmp_path / "fictional-outside-config.json"
    outside.write_text("{}", encoding="utf-8")
    try:
        config.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"file symlinks are unavailable: {type(exc).__name__}")

    with pytest.raises(ModelCacheBoundaryError, match="outside_isolated_cache"):
        prepare_model_snapshot(
            manifest,
            cache_root=cache,
            downloader=lambda **_: str(snapshot),
            repo_root=repository,
        )


def test_bilingual_fixture_is_balanced_typed_and_bounded() -> None:
    corpus = load_synthetic_corpus(FIXTURE)
    summary = corpus_public_summary(corpus)

    assert summary == {
        "schema_version": 1,
        "benchmark_id": "bilingual_model_screen_v1",
        "synthetic_only": True,
        "languages": ["en", "pl"],
        "retrieval_case_count": 12,
        "nli_case_count": 18,
        "nli_label_counts": {"contradiction": 6, "entailment": 6, "neutral": 6},
        "nli_scope_counts": {"different_scope": 4, "same_scope": 14},
    }
    smoke = corpus.smoke_subset()
    assert {case.language for case in smoke.retrieval_cases} == {"en", "pl"}
    assert {case.language for case in smoke.nli_cases} == {"en", "pl"}
    assert {case.expected_label for case in smoke.nli_cases} == {
        "entailment",
        "neutral",
        "contradiction",
    }


def test_bilingual_rubric_fixture_is_balanced_typed_and_bounded() -> None:
    corpus = load_synthetic_rubric_corpus(RUBRIC_FIXTURE)
    assert rubric_corpus_public_summary(corpus) == {
        "schema_version": 1,
        "benchmark_id": "bilingual_rubric_screen_v1",
        "synthetic_only": True,
        "languages": ["en", "pl"],
        "case_count": 24,
        "label_counts": {"absent": 8, "abstain": 8, "present": 8},
        "rubric_counts": {
            "acceptance_testability": 6,
            "constraint_precision": 6,
            "deliverable_contract": 6,
            "task_definition": 6,
        },
    }
    smoke = corpus.smoke_subset()
    assert len(smoke.cases) == 8
    assert {case.language for case in smoke.cases} == {"en", "pl"}
    assert {case.rubric_key for case in smoke.cases} == {
        "task_definition",
        "constraint_precision",
        "acceptance_testability",
        "deliverable_contract",
    }
    assert {case.expected_label for case in smoke.cases} == {
        "present",
        "absent",
        "abstain",
    }


def test_corpus_loader_rejects_unreviewed_extra_fields(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["source_path"] = "fictional-value"
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SyntheticCorpusError, match="invalid fields"):
        load_synthetic_corpus(candidate)


class _PerfectRetrievalScorer:
    def score(self, cases):  # type: ignore[no-untyped-def]
        return tuple(
            tuple(
                1.0 if candidate.candidate_id == case.positive_candidate_id else 0.0
                for candidate in case.candidates
            )
            for case in cases
        )


class _PerfectNliClassifier:
    def predict(self, cases):  # type: ignore[no-untyped-def]
        return tuple(case.expected_label for case in cases)


class _PerfectRubricJudge:
    def predict(self, cases):  # type: ignore[no-untyped-def]
        return tuple(
            RubricPrediction(label=case.expected_label, json_valid=True)
            for case in cases
        )


def test_reports_are_aggregate_only_and_do_not_carry_fixture_text_or_ids() -> None:
    corpus = load_synthetic_corpus(FIXTURE)
    retrieval = evaluate_retrieval(
        corpus.retrieval_cases,
        _PerfectRetrievalScorer(),
        backend_key="synthetic_test_backend",
    )
    nli = evaluate_nli(
        corpus.nli_cases,
        _PerfectNliClassifier(),
        backend_key="synthetic_test_backend",
    )
    rubric_corpus = load_synthetic_rubric_corpus(RUBRIC_FIXTURE)
    rubric = evaluate_rubric(
        rubric_corpus.cases,
        _PerfectRubricJudge(),
        backend_key="synthetic_test_backend",
    )

    assert retrieval["top1_accuracy"] == 1.0
    assert retrieval["mean_reciprocal_rank"] == 1.0
    assert nli["three_way_accuracy"] == 1.0
    assert nli["contradiction_detection_macro_f1"] == 1.0
    assert nli["different_scope_false_positive_rate"] == 0.0
    assert rubric["exact_label_accuracy"] == 1.0
    assert rubric["json_schema_compliance_rate"] == 1.0
    rendered = json.dumps({"retrieval": retrieval, "nli": nli, "rubric": rubric})
    for forbidden in (
        "Export the selected metric profile",
        "Wyeksportuj profil metryk",
        "en_export_png",
        "pl_export_png",
        "embedding",
        "Implement a loopback-only metrics export",
        "en_task_present",
    ):
        assert forbidden not in rendered


def test_lexical_baseline_is_nontrivial_against_hard_negatives() -> None:
    corpus = load_synthetic_corpus(FIXTURE)
    report = evaluate_retrieval(
        corpus.retrieval_cases,
        LexicalBm25Scorer(),
        backend_key=LexicalBm25Scorer.key,
    )
    assert 0.25 <= report["top1_accuracy"] < 1.0
    assert report["mean_reciprocal_rank"] >= report["top1_accuracy"]
