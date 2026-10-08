from __future__ import annotations

import pytest
from pydantic import SecretStr

from prompt_enhancer.application.discovery import CandidateIdentity
from prompt_enhancer.domain import Provider
from prompt_enhancer.infrastructure.identifiers import LocalArtifactIdFactory
from prompt_enhancer.privacy import Pseudonymizer


def _factory(key_byte: int = 7) -> LocalArtifactIdFactory:
    return LocalArtifactIdFactory(Pseudonymizer(bytes([key_byte]) * 32))


def _identity(version: str = "metadata-v1") -> CandidateIdentity:
    return CandidateIdentity(
        discovery_version=version,
        provider=Provider.SYNTHETIC,
        installation_id="0" * 64,
        project_id="1" * 64,
        session_ids=("a" * 64, "b" * 64),
    )


def test_artifact_identifiers_are_stable_domain_separated_pseudonyms() -> None:
    factory = _factory()

    candidate_id = factory.create(_identity())
    repeated_id = factory.create(_identity())
    decision_id = factory.decision_id("example-retry-0001")
    task_id = factory.task_id(decision_id, 0)
    run_id = factory.analysis_run_id(
        "example-analysis-0001",
        task_id,
        1,
        "core.metadata.task",
        1,
    )
    fingerprint = factory.fingerprint(
        "task-input-v1", ("unknown", "a" * 64, "b" * 64)
    )

    assert candidate_id == repeated_id
    assert len({candidate_id, decision_id, task_id, run_id, fingerprint}) == 5
    assert all(len(value) == 64 for value in (candidate_id, decision_id, task_id, fingerprint))
    assert factory.create(_identity("metadata-v2")) != candidate_id
    assert _factory(8).create(_identity()) != candidate_id


def test_artifact_factory_rejects_content_like_or_invalid_inputs() -> None:
    factory = _factory()
    decision_id = factory.decision_id("example-retry-0001")

    with pytest.raises(ValueError, match="content-free"):
        factory.decision_id("contains spaces and prompt-like text")
    with pytest.raises(ValueError, match="safe pseudonym"):
        factory.task_id("unsafe", 0)
    with pytest.raises(ValueError, match="negative"):
        factory.task_id(decision_id, -1)
    with pytest.raises(ValueError, match="namespace"):
        factory.fingerprint("unsafe namespace", ("a" * 64,))


def test_secret_fingerprint_is_keyed_stable_and_content_sensitive() -> None:
    factory = _factory()
    metadata = ("synthetic", "a" * 64)
    first = factory.fingerprint_secret(
        "semantic-source-version-v1",
        metadata,
        SecretStr("First synthetic redacted value."),
    )
    repeated = factory.fingerprint_secret(
        "semantic-source-version-v1",
        metadata,
        SecretStr("First synthetic redacted value."),
    )
    changed = factory.fingerprint_secret(
        "semantic-source-version-v1",
        metadata,
        SecretStr("Changed synthetic redacted value."),
    )

    assert first == repeated
    assert first != changed
    assert first != _factory(8).fingerprint_secret(
        "semantic-source-version-v1",
        metadata,
        SecretStr("First synthetic redacted value."),
    )
    assert len(first) == 64
    assert "First synthetic" not in first
    with pytest.raises(TypeError, match="SecretStr"):
        factory.fingerprint_secret(  # type: ignore[arg-type]
            "semantic-source-version-v1",
            metadata,
            "plain string",
        )
