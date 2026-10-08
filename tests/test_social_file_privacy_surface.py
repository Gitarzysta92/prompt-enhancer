"""Canaries proving that shared metadata schemas cannot accept content fields."""

from __future__ import annotations

import inspect

from pydantic import BaseModel

from prompt_enhancer.application import file_sharing, social
from prompt_enhancer.application.file_sharing import FileManifest
from prompt_enhancer.application.social import E2eeEnvelopeMetadata


FORBIDDEN_PERSISTENT_FIELDS = {
    "absolute_path",
    "account_email",
    "body",
    "content",
    "credential",
    "file_bytes",
    "file_name",
    "file_path",
    "hostname",
    "message_text",
    "plaintext",
    "prompt",
    "raw_text",
    "source_code",
    "transcript",
}


def models_in(module: object) -> tuple[type[BaseModel], ...]:
    return tuple(
        candidate
        for _, candidate in inspect.getmembers(module, inspect.isclass)
        if issubclass(candidate, BaseModel)
        and candidate.__module__.startswith("prompt_enhancer.application")
    )


def test_persistent_social_and_manifest_contracts_have_no_content_fields() -> None:
    models = models_in(social.contracts) + models_in(file_sharing.contracts)
    # LocalFileDescriptor intentionally carries a validated owner-local basename
    # and is never a persistent control-plane record; its field is not one of
    # the forbidden path/name spellings above.
    for model in models:
        assert set(model.model_fields).isdisjoint(FORBIDDEN_PERSISTENT_FIELDS), model

    assert "ciphertext" not in E2eeEnvelopeMetadata.model_fields
    assert "ciphertext_size" in E2eeEnvelopeMetadata.model_fields
    assert "ciphertext_sha256" in E2eeEnvelopeMetadata.model_fields
    assert "file_name" not in FileManifest.model_fields
    assert "path" not in FileManifest.model_fields


def test_contract_source_does_not_import_analyzer_database_or_metrics() -> None:
    for module in (social.contracts, file_sharing.contracts):
        source = inspect.getsource(module)
        assert "prompt_enhancer.database" not in source
        assert "application.analysis" not in source
        assert "application.control_plane" not in source
        assert "metrics.sqlite3" not in source
