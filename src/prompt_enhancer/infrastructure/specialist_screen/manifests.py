"""Immutable supply-chain records for the first specialist pre-screen."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from prompt_enhancer.infrastructure.text_models.manifests import (
    MDEBERTA_XNLI,
    ModelManifest,
    TextModelTask,
)


_NLI_LABELS = (
    (0, "entailment"),
    (1, "neutral"),
    (2, "contradiction"),
)


MINILMV2_L6_NLI = ModelManifest(
    key="multilingual_minilmv2_l6_nli",
    task=TextModelTask.SCOPED_NLI,
    repository_id="MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli",
    revision="0a71e92a985b6e1ad1828cf67ce9c459639c1dca",
    tokenizer_repository_id="MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli",
    tokenizer_revision="0a71e92a985b6e1ad1828cf67ce9c459639c1dca",
    license_spdx="MIT",
    weight_filename="model.safetensors",
    weight_sha256="91b323ccf247ec1e3b5925d566230bae7c52de8147e6062b42e250089a3fc80b",
    additional_artifact_files=(
        (
            "config.json",
            "79862295be1538a947e0f56d495ef8d658c3eaebcfb42c7ad96229d195ca745d",
        ),
        (
            "tokenizer.json",
            "098c131bb4423163db239755e309facaa6850059f850f9f3d88a78344a4b631c",
        ),
        (
            "tokenizer_config.json",
            "86139ce1f39e814bcdb99a6fe30c0c4983911508aad07417e616d994fb74eb25",
        ),
        (
            "special_tokens_map.json",
            "06e405a36dfe4b9604f484f6a1e619af1a7f7d09e34a8555eb0b77b66318067f",
        ),
        (
            "sentencepiece.bpe.model",
            "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865",
        ),
    ),
    max_sequence_length=512,
    max_batch_size=16,
    output_label_by_index=_NLI_LABELS,
    architecture="sequence_classifier",
)


MINILMV2_L12_NLI = ModelManifest(
    key="multilingual_minilmv2_l12_nli",
    task=TextModelTask.SCOPED_NLI,
    repository_id="MoritzLaurer/multilingual-MiniLMv2-L12-mnli-xnli",
    revision="0d55db361c5f291640208c51ff8c181146aa8eff",
    tokenizer_repository_id="MoritzLaurer/multilingual-MiniLMv2-L12-mnli-xnli",
    tokenizer_revision="0d55db361c5f291640208c51ff8c181146aa8eff",
    license_spdx="MIT",
    weight_filename="model.safetensors",
    weight_sha256="47b82b3b1f18a0e4cc5cc80d470d75b3e2278603328b3dd67454b19148d7f85b",
    additional_artifact_files=(
        (
            "config.json",
            "15030844050f2df9cd2a8ab1e622cccfa0e42f15c87399aa1f8e8516a225783b",
        ),
        (
            "tokenizer.json",
            "098c131bb4423163db239755e309facaa6850059f850f9f3d88a78344a4b631c",
        ),
        (
            "tokenizer_config.json",
            "1e05e843ecf991ec0c148e0697f409f63032090d5f9729d052a8658c00786aff",
        ),
        (
            "special_tokens_map.json",
            "06e405a36dfe4b9604f484f6a1e619af1a7f7d09e34a8555eb0b77b66318067f",
        ),
        (
            "sentencepiece.bpe.model",
            "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865",
        ),
    ),
    max_sequence_length=512,
    max_batch_size=12,
    output_label_by_index=_NLI_LABELS,
    architecture="sequence_classifier",
)


SPECIALIST_MODEL_MANIFESTS: Mapping[str, ModelManifest] = MappingProxyType(
    {
        MINILMV2_L6_NLI.key: MINILMV2_L6_NLI,
        MINILMV2_L12_NLI.key: MINILMV2_L12_NLI,
    }
)


@dataclass(frozen=True, slots=True)
class HistoricalSpecialistDecision:
    candidate_key: str
    repository_id: str
    revision: str
    decision: str
    reason_code: str
    benchmark_id: str
    synthetic_case_count: int
    runnable_in_this_screen: bool = False
    activation_allowed: bool = False

    def public_record(self) -> dict[str, object]:
        return {
            "candidate_key": self.candidate_key,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "decision": self.decision,
            "reason_code": self.reason_code,
            "benchmark_id": self.benchmark_id,
            "synthetic_case_count": self.synthetic_case_count,
            "runnable_in_this_screen": self.runnable_in_this_screen,
            "activation_allowed": self.activation_allowed,
        }


MDEBERTA_HISTORICAL_REJECTION = HistoricalSpecialistDecision(
    candidate_key=MDEBERTA_XNLI.key,
    repository_id=MDEBERTA_XNLI.repository_id,
    revision=MDEBERTA_XNLI.revision,
    decision="rejected",
    reason_code="historical_unscoped_configuration_rejected",
    benchmark_id="bilingual_model_screen_v1",
    synthetic_case_count=18,
)
