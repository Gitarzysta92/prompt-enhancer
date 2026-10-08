"""Immutable manifests for exploratory WP-11 model candidates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
import re
from typing import Mapping


_LOWER_HEX_40 = re.compile(r"[0-9a-f]{40}\Z")
_LOWER_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_REPOSITORY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_SAFE_LABELS = frozenset({"entailment", "neutral", "contradiction"})
_SAFE_BINARY_LABELS = frozenset({"entailment", "not_entailment"})
_SAFE_AUXILIARY_ARTIFACTS = (
    "config.json",
    "model.safetensors.index.json",
    "generation_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "added_tokens.json",
    "sentencepiece.bpe.model",
    "spm.model",
    "vocab.json",
    "vocab.txt",
    "merges.txt",
    "chat_template.jinja",
    "modules.json",
    "config_sentence_transformers.json",
    "sentence_bert_config.json",
    "1_Pooling/config.json",
)


class TextModelTask(str, Enum):
    REQUIREMENT_ACTION_RETRIEVAL = "requirement_action_retrieval"
    SCOPED_NLI = "scoped_nli"
    BINARY_NLI = "binary_nli"
    PAIR_RERANKING = "pair_reranking"
    STRUCTURED_RUBRIC = "structured_rubric"


@dataclass(frozen=True, slots=True)
class ModelManifest:
    """A fail-closed model and tokenizer provenance record.

    The manifest deliberately does not support branches, tags, pickle weights,
    custom code, or unbounded tokenizer inputs.
    """

    key: str
    task: TextModelTask
    repository_id: str
    revision: str
    tokenizer_repository_id: str
    tokenizer_revision: str
    license_spdx: str
    weight_filename: str
    weight_sha256: str
    max_sequence_length: int
    max_batch_size: int
    trust_remote_code: bool = False
    output_label_by_index: tuple[tuple[int, str], ...] = ()
    additional_weight_files: tuple[tuple[str, str], ...] = ()
    additional_artifact_files: tuple[tuple[str, str], ...] = ()
    architecture: str = "auto"

    def __post_init__(self) -> None:
        if not self.key or not self.key.replace("_", "").isalnum():
            raise ValueError("model manifest key must be a stable identifier")
        for repository_id in (
            self.repository_id,
            self.tokenizer_repository_id,
        ):
            if _REPOSITORY_ID.fullmatch(repository_id) is None:
                raise ValueError("model repository must be an explicit Hub repository ID")
        if _LOWER_HEX_40.fullmatch(self.revision) is None:
            raise ValueError("model revision must be a 40-character commit hash")
        if _LOWER_HEX_40.fullmatch(self.tokenizer_revision) is None:
            raise ValueError("tokenizer revision must be a 40-character commit hash")
        if (
            self.tokenizer_repository_id != self.repository_id
            or self.tokenizer_revision != self.revision
        ):
            raise ValueError(
                "single-snapshot evaluation requires the tokenizer and model pin to match"
            )
        if self.license_spdx not in {"MIT", "Apache-2.0"}:
            raise ValueError("candidate license must be an explicitly reviewed permissive SPDX identifier")
        if not self.weight_filename.endswith(".safetensors"):
            raise ValueError("only reviewed safetensors weight files are accepted")
        if _LOWER_HEX_64.fullmatch(self.weight_sha256) is None:
            raise ValueError("weight SHA-256 must be a lowercase 64-character digest")
        all_weights = ((self.weight_filename, self.weight_sha256), *self.additional_weight_files)
        filenames = tuple(filename for filename, _ in all_weights)
        if len(set(filenames)) != len(filenames):
            raise ValueError("reviewed weight filenames must be unique")
        for filename, digest in all_weights:
            if (
                not filename.endswith(".safetensors")
                or filename.startswith("/")
                or "\\" in filename
                or ".." in filename.split("/")
            ):
                raise ValueError("reviewed weights must be relative safetensors files")
            if _LOWER_HEX_64.fullmatch(digest) is None:
                raise ValueError("weight SHA-256 must be a lowercase 64-character digest")
        artifact_filenames = tuple(
            filename for filename, _ in self.additional_artifact_files
        )
        if len(set(artifact_filenames)) != len(artifact_filenames):
            raise ValueError("reviewed auxiliary artifact filenames must be unique")
        if set(filenames) & set(artifact_filenames):
            raise ValueError("weight and auxiliary artifact filenames must be distinct")
        for filename, digest in self.additional_artifact_files:
            if filename not in _SAFE_AUXILIARY_ARTIFACTS:
                raise ValueError("reviewed auxiliary artifact filename is unsupported")
            if _LOWER_HEX_64.fullmatch(digest) is None:
                raise ValueError(
                    "auxiliary artifact SHA-256 must be a lowercase 64-character digest"
                )
        if self.trust_remote_code:
            raise ValueError("trust_remote_code must remain disabled")
        if not 8 <= self.max_sequence_length <= 2_048:
            raise ValueError("model sequence length must be explicitly bounded at 2048 or less")
        if not 1 <= self.max_batch_size <= 32:
            raise ValueError("model batch size must be explicitly bounded at 32 or less")

        labels = dict(self.output_label_by_index)
        if len(labels) != len(self.output_label_by_index):
            raise ValueError("NLI output label indexes must be unique")
        if self.task is TextModelTask.SCOPED_NLI:
            if set(labels.values()) != _SAFE_LABELS or set(labels) != {0, 1, 2}:
                raise ValueError("NLI manifest must map indexes 0..2 to all three typed labels")
        elif self.task is TextModelTask.BINARY_NLI:
            if set(labels.values()) != _SAFE_BINARY_LABELS or set(labels) != {0, 1}:
                raise ValueError(
                    "binary NLI manifest must map indexes 0..1 to entailment and not_entailment"
                )
        elif labels:
            raise ValueError("retrieval manifests cannot declare classification labels")
        if not self.architecture or not self.architecture.replace("_", "").isalnum():
            raise ValueError("model architecture must be a stable identifier")

    @property
    def weight_files(self) -> tuple[tuple[str, str], ...]:
        return ((self.weight_filename, self.weight_sha256), *self.additional_weight_files)

    @property
    def allowed_snapshot_patterns(self) -> tuple[str, ...]:
        """Public model artifacts allowed into the isolated task cache."""

        return (
            *(filename for filename, _ in self.weight_files),
            *_SAFE_AUXILIARY_ARTIFACTS,
        )

    def public_pin(self) -> dict[str, object]:
        """Return provenance that is safe for aggregate benchmark output."""

        return {
            "key": self.key,
            "task": self.task.value,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "tokenizer_repository_id": self.tokenizer_repository_id,
            "tokenizer_revision": self.tokenizer_revision,
            "license_spdx": self.license_spdx,
            "weight_filename": self.weight_filename,
            "weight_sha256": self.weight_sha256,
            "weight_files": [
                {"filename": filename, "sha256": digest}
                for filename, digest in self.weight_files
            ],
            "additional_artifact_files": [
                {"filename": filename, "sha256": digest}
                for filename, digest in self.additional_artifact_files
            ],
            "max_sequence_length": self.max_sequence_length,
            "max_batch_size": self.max_batch_size,
            "trust_remote_code": self.trust_remote_code,
            "architecture": self.architecture,
        }


@dataclass(frozen=True, slots=True)
class BlockedModelManifest:
    """A candidate rejected before download by an immutable artifact gate."""

    key: str
    repository_id: str
    revision: str
    license_spdx: str
    blocked_reason: str
    reviewed_artifact: str
    reviewed_sha256: str

    def __post_init__(self) -> None:
        if _REPOSITORY_ID.fullmatch(self.repository_id) is None:
            raise ValueError("blocked model repository must be explicit")
        if _LOWER_HEX_40.fullmatch(self.revision) is None:
            raise ValueError("blocked model revision must be immutable")
        if _LOWER_HEX_64.fullmatch(self.reviewed_sha256) is None:
            raise ValueError("blocked artifact digest must be immutable")
        if self.blocked_reason != "unsafe_pickle_only":
            raise ValueError("blocked model reason must be a closed safe code")

    def public_pin(self) -> dict[str, object]:
        return {
            "key": self.key,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "license_spdx": self.license_spdx,
            "status": "blocked",
            "blocked_reason": self.blocked_reason,
            "reviewed_artifact": self.reviewed_artifact,
            "reviewed_sha256": self.reviewed_sha256,
            "trust_remote_code": False,
        }


E5_MULTILINGUAL_SMALL = ModelManifest(
    key="multilingual_e5_small",
    task=TextModelTask.REQUIREMENT_ACTION_RETRIEVAL,
    repository_id="intfloat/multilingual-e5-small",
    revision="614241f622f53c4eeff9890bdc4f31cfecc418b3",
    tokenizer_repository_id="intfloat/multilingual-e5-small",
    tokenizer_revision="614241f622f53c4eeff9890bdc4f31cfecc418b3",
    license_spdx="MIT",
    weight_filename="model.safetensors",
    weight_sha256="1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477",
    max_sequence_length=512,
    max_batch_size=32,
)

E5_MULTILINGUAL_BASE = ModelManifest(
    key="multilingual_e5_base",
    task=TextModelTask.REQUIREMENT_ACTION_RETRIEVAL,
    repository_id="intfloat/multilingual-e5-base",
    revision="d128750597153bb5987e10b1c3493a34e5a4502a",
    tokenizer_repository_id="intfloat/multilingual-e5-base",
    tokenizer_revision="d128750597153bb5987e10b1c3493a34e5a4502a",
    license_spdx="MIT",
    weight_filename="model.safetensors",
    weight_sha256="a18a44fad1d0b46ded15928144138cff1135d5cc8233bdd90be5f18822de09a7",
    max_sequence_length=512,
    max_batch_size=16,
)

MDEBERTA_XNLI = ModelManifest(
    key="mdeberta_xnli",
    task=TextModelTask.SCOPED_NLI,
    repository_id="MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7",
    revision="b5113eb38ab63efdd7f280f8c144ea8b13f978ce",
    tokenizer_repository_id=(
        "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
    ),
    tokenizer_revision="b5113eb38ab63efdd7f280f8c144ea8b13f978ce",
    license_spdx="MIT",
    weight_filename="model.safetensors",
    weight_sha256="7c8e29f1115986d032e92b0fbaa0bdef1062a46f658b08705f237c05014a8541",
    max_sequence_length=512,
    max_batch_size=16,
    # This repository's pinned config uses this explicit order.  Runtime loading
    # also validates semantic config labels when the config exposes them.
    output_label_by_index=(
        (0, "entailment"),
        (1, "neutral"),
        (2, "contradiction"),
    ),
)

DEBERTA_SMALL_LONG_NLI = ModelManifest(
    key="deberta_small_long_nli",
    task=TextModelTask.SCOPED_NLI,
    repository_id="tasksource/deberta-small-long-nli",
    revision="9a77395d4d3751be9e2a69c4ae318491d9b3fffb",
    tokenizer_repository_id="tasksource/deberta-small-long-nli",
    tokenizer_revision="9a77395d4d3751be9e2a69c4ae318491d9b3fffb",
    license_spdx="Apache-2.0",
    weight_filename="model.safetensors",
    weight_sha256="9af30c7ad7235a2054300bc2df1d98149ad6008dd1ef06212be8b32b5d1b3458",
    max_sequence_length=1_680,
    max_batch_size=8,
    output_label_by_index=(
        (0, "entailment"),
        (1, "neutral"),
        (2, "contradiction"),
    ),
    architecture="deberta_v2_sequence_classifier",
)

MODERNBERT_BASE_ZEROSHOT = ModelManifest(
    key="modernbert_base_zeroshot",
    task=TextModelTask.BINARY_NLI,
    repository_id="MoritzLaurer/ModernBERT-base-zeroshot-v2.0",
    revision="d421c4545a438fd006fb43f8b981c5d908faa1e1",
    tokenizer_repository_id="MoritzLaurer/ModernBERT-base-zeroshot-v2.0",
    tokenizer_revision="d421c4545a438fd006fb43f8b981c5d908faa1e1",
    license_spdx="Apache-2.0",
    weight_filename="model.safetensors",
    weight_sha256="5af4dac82bf3da16575d0c71c8c96ee7eb6621ae5f4f4726943d0a3583b44b46",
    # The upstream encoder supports a wider context, but the product contract
    # deliberately caps every live semantic episode at 2,048 tokens.
    max_sequence_length=2_048,
    max_batch_size=8,
    output_label_by_index=(
        (0, "entailment"),
        (1, "not_entailment"),
    ),
    architecture="modernbert_sequence_classifier",
)

BGE_M3_LEGACY_BLOCKED = BlockedModelManifest(
    key="bge_m3_legacy_pickle_pin",
    repository_id="BAAI/bge-m3",
    revision="5617a9f61b028005a4858fdac845db406aefb181",
    license_spdx="MIT",
    blocked_reason="unsafe_pickle_only",
    reviewed_artifact="pytorch_model.bin",
    reviewed_sha256="b5e0a70128ad4f26da749a34c4a202c9ba503069e0f40a27d3c35619a358ad38",
)

# Backwards-compatible public name for the superseded historical decision.
BGE_M3_BLOCKED = BGE_M3_LEGACY_BLOCKED

BGE_M3 = ModelManifest(
    key="bge_m3",
    task=TextModelTask.REQUIREMENT_ACTION_RETRIEVAL,
    repository_id="BAAI/bge-m3",
    revision="142964af7e05de16511657561de8e8750fc153a0",
    tokenizer_repository_id="BAAI/bge-m3",
    tokenizer_revision="142964af7e05de16511657561de8e8750fc153a0",
    license_spdx="MIT",
    weight_filename="model.safetensors",
    weight_sha256="993b2248881724788dcab8c644a91dfd63584b6e5604ff2037cb5541e1e38e7e",
    additional_artifact_files=(
        (
            "config.json",
            "26159e7ad065073448460117eb24b7a4572f6f4e78eadff65dc0a11c052449fa",
        ),
        (
            "tokenizer.json",
            "21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08",
        ),
        (
            "tokenizer_config.json",
            "a62b2b6784f990259fddef5f16388693a8043be4f69179e6a5257eeb3f9abac4",
        ),
        (
            "special_tokens_map.json",
            "8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835",
        ),
        (
            "sentencepiece.bpe.model",
            "cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865",
        ),
        (
            "modules.json",
            "84e40c8e006c9b1d6c122e02cba9b02458120b5fb0c87b746c41e0207cf642cf",
        ),
        (
            "config_sentence_transformers.json",
            "1eef72430e7194a1e59680e635aed81ffa083f05668dbc5bb1c56c04c0999c38",
        ),
        (
            "sentence_bert_config.json",
            "eb9b44b13c0f52a3b3685c3b1cbdea1ba8b04bea123b98f61610048940776eb1",
        ),
        (
            "1_Pooling/config.json",
            "e54c164a07274f2eb45bb724f54a79d1efcc90c41573887cd9a29aeee0597352",
        ),
    ),
    max_sequence_length=512,
    max_batch_size=4,
    architecture="xlm_roberta_cls",
)

BGE_RERANKER_V2_M3 = ModelManifest(
    key="bge_reranker_v2_m3",
    task=TextModelTask.PAIR_RERANKING,
    repository_id="BAAI/bge-reranker-v2-m3",
    revision="953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
    tokenizer_repository_id="BAAI/bge-reranker-v2-m3",
    tokenizer_revision="953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
    license_spdx="Apache-2.0",
    weight_filename="model.safetensors",
    weight_sha256="d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286",
    max_sequence_length=512,
    max_batch_size=8,
    architecture="sequence_classifier",
)

QWEN3_EMBEDDING_06B = ModelManifest(
    key="qwen3_embedding_06b",
    task=TextModelTask.REQUIREMENT_ACTION_RETRIEVAL,
    repository_id="Qwen/Qwen3-Embedding-0.6B",
    revision="97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
    tokenizer_repository_id="Qwen/Qwen3-Embedding-0.6B",
    tokenizer_revision="97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
    license_spdx="Apache-2.0",
    weight_filename="model.safetensors",
    weight_sha256="0437e45c94563b09e13cb7a64478fc406947a93cb34a7e05870fc8dcd48e23fd",
    max_sequence_length=512,
    max_batch_size=16,
    architecture="qwen3_embedding",
)

QWEN3_RERANKER_06B = ModelManifest(
    key="qwen3_reranker_06b",
    task=TextModelTask.PAIR_RERANKING,
    repository_id="Qwen/Qwen3-Reranker-0.6B",
    revision="e61197ed45024b0ed8a2d74b80b4d909f1255473",
    tokenizer_repository_id="Qwen/Qwen3-Reranker-0.6B",
    tokenizer_revision="e61197ed45024b0ed8a2d74b80b4d909f1255473",
    license_spdx="Apache-2.0",
    weight_filename="model.safetensors",
    weight_sha256="27cd75a405b9c1b46b59abfd88aaa209e6fed2a1972cde9b70e7659537c5e65b",
    max_sequence_length=512,
    max_batch_size=8,
    architecture="qwen3_reranker",
)

QWEN3_4B_RUBRIC = ModelManifest(
    key="qwen3_4b_rubric",
    task=TextModelTask.STRUCTURED_RUBRIC,
    repository_id="Qwen/Qwen3-4B-Instruct-2507",
    revision="cdbee75f17c01a7cc42f958dc650907174af0554",
    tokenizer_repository_id="Qwen/Qwen3-4B-Instruct-2507",
    tokenizer_revision="cdbee75f17c01a7cc42f958dc650907174af0554",
    license_spdx="Apache-2.0",
    weight_filename="model-00001-of-00003.safetensors",
    weight_sha256="75311d91bb08cf0b882913da464a1e722a31fb44db35208663487efb7a3d8ed6",
    additional_weight_files=(
        (
            "model-00002-of-00003.safetensors",
            "0b48adbb1f60e901153d91907ba11ce63bd4b8b584482e730f48808d055dfba1",
        ),
        (
            "model-00003-of-00003.safetensors",
            "7dd39ccca5e4de123c74c14af44c9bf2eb75df33b4614382af0134528e060d5d",
        ),
    ),
    max_sequence_length=512,
    max_batch_size=1,
    architecture="qwen3_instruct",
)

TEXT_MODEL_MANIFESTS: Mapping[str, ModelManifest] = MappingProxyType(
    {
        E5_MULTILINGUAL_SMALL.key: E5_MULTILINGUAL_SMALL,
        E5_MULTILINGUAL_BASE.key: E5_MULTILINGUAL_BASE,
        BGE_M3.key: BGE_M3,
        MDEBERTA_XNLI.key: MDEBERTA_XNLI,
        DEBERTA_SMALL_LONG_NLI.key: DEBERTA_SMALL_LONG_NLI,
        MODERNBERT_BASE_ZEROSHOT.key: MODERNBERT_BASE_ZEROSHOT,
        BGE_RERANKER_V2_M3.key: BGE_RERANKER_V2_M3,
        QWEN3_EMBEDDING_06B.key: QWEN3_EMBEDDING_06B,
        QWEN3_RERANKER_06B.key: QWEN3_RERANKER_06B,
        QWEN3_4B_RUBRIC.key: QWEN3_4B_RUBRIC,
    }
)

BLOCKED_TEXT_MODEL_MANIFESTS: Mapping[str, BlockedModelManifest] = MappingProxyType(
    {BGE_M3_LEGACY_BLOCKED.key: BGE_M3_LEGACY_BLOCKED}
)
