"""Strict public-shape tests for sealed r7 requirement-action authority."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.analysis.session_model_ensemble import (
    REQUIREMENT_ACTION_AWAITING_REVIEW_FINGERPRINT,
    REQUIREMENT_ACTION_BINDING_INVALID_FINGERPRINT,
    REQUIREMENT_ACTION_CANDIDATE_MANIFEST_OVERFLOW_FINGERPRINT,
    REQUIREMENT_ACTION_CANDIDATE_SOURCE_INCOMPLETE_FINGERPRINT,
    REQUIREMENT_ACTION_UNAVAILABLE_FINGERPRINT,
    RequirementActionEvidenceSource,
    SessionRequirementActionEvidenceBinding,
)
from prompt_enhancer.interfaces.http.model_ensemble_routes import (
    ModelRequirementActionEvidenceBindingDto,
)


IDENTIFIER = "a" * 64
SECOND_IDENTIFIER = "b" * 64
THIRD_IDENTIFIER = "c" * 64
FOURTH_IDENTIFIER = "d" * 64
FIFTH_IDENTIFIER = "e" * 64
SIXTH_IDENTIFIER = "f" * 64


def _marker(
    source: RequirementActionEvidenceSource,
) -> SessionRequirementActionEvidenceBinding:
    identities = {
        RequirementActionEvidenceSource.UNAVAILABLE: (
            REQUIREMENT_ACTION_UNAVAILABLE_FINGERPRINT,
            "requirement-action-unavailable-v1",
        ),
        RequirementActionEvidenceSource.AWAITING_REVIEW: (
            REQUIREMENT_ACTION_AWAITING_REVIEW_FINGERPRINT,
            "requirement-action-awaiting-review-v1",
        ),
        RequirementActionEvidenceSource.CANDIDATE_MANIFEST_OVERFLOW: (
            REQUIREMENT_ACTION_CANDIDATE_MANIFEST_OVERFLOW_FINGERPRINT,
            "requirement-action-candidate-manifest-overflow-v1",
        ),
        RequirementActionEvidenceSource.CANDIDATE_SOURCE_INCOMPLETE: (
            REQUIREMENT_ACTION_CANDIDATE_SOURCE_INCOMPLETE_FINGERPRINT,
            "requirement-action-candidate-source-incomplete-v1",
        ),
        RequirementActionEvidenceSource.BINDING_INVALID: (
            REQUIREMENT_ACTION_BINDING_INVALID_FINGERPRINT,
            "requirement-action-binding-invalid-v1",
        ),
    }
    fingerprint, schema = identities[source]
    return SessionRequirementActionEvidenceBinding(
        evidence_source=source,
        session_id=IDENTIFIER,
        source_window_fingerprint=SECOND_IDENTIFIER,
        evidence_fingerprint=fingerprint,
        evidence_schema_version=schema,
        evidence_policy_version="reviewed-requirement-action-v1",
        bound_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    "source",
    [
        RequirementActionEvidenceSource.UNAVAILABLE,
        RequirementActionEvidenceSource.AWAITING_REVIEW,
        RequirementActionEvidenceSource.CANDIDATE_MANIFEST_OVERFLOW,
        RequirementActionEvidenceSource.CANDIDATE_SOURCE_INCOMPLETE,
        RequirementActionEvidenceSource.BINDING_INVALID,
    ],
)
def test_public_marker_is_minimized_and_exact(
    source: RequirementActionEvidenceSource,
) -> None:
    dto = ModelRequirementActionEvidenceBindingDto.from_binding(_marker(source))
    payload = dto.model_dump(mode="json")

    assert "session_id" not in payload
    assert "source_window_fingerprint" not in payload
    assert "bound_at" not in payload
    assert payload["source_run_id"] is None
    assert payload["confirmation_id"] is None
    assert payload["proposal_id"] is None


def test_public_reviewed_binding_retains_only_content_free_authority() -> None:
    binding = SessionRequirementActionEvidenceBinding(
        evidence_source=(
            RequirementActionEvidenceSource.REVIEWED_REQUIREMENT_ACTION
        ),
        session_id=IDENTIFIER,
        source_window_fingerprint=SECOND_IDENTIFIER,
        source_run_id=THIRD_IDENTIFIER,
        requirement_plan_confirmation_id=FOURTH_IDENTIFIER,
        requirement_plan_evidence_fingerprint=FIFTH_IDENTIFIER,
        candidate_manifest_fingerprint=SIXTH_IDENTIFIER,
        confirmation_id="1" * 64,
        proposal_id="2" * 64,
        reviewed_descriptor_set_fingerprint="4" * 64,
        evidence_fingerprint="3" * 64,
        evidence_schema_version="requirement-action-evidence-v1",
        evidence_policy_version="reviewed-requirement-action-v1",
        bound_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    payload = ModelRequirementActionEvidenceBindingDto.from_binding(
        binding
    ).model_dump(mode="json")

    assert payload["source_run_id"] == THIRD_IDENTIFIER
    assert payload["candidate_manifest_fingerprint"] == SIXTH_IDENTIFIER
    assert payload["confirmation_id"] == "1" * 64
    assert payload["reviewed_descriptor_set_fingerprint"] == "4" * 64
    assert payload["content_persisted"] is False
    assert "session_id" not in payload
    assert "source_window_fingerprint" not in payload
    assert "bound_at" not in payload


def test_public_reviewed_binding_rejects_partial_or_marker_authority() -> None:
    payload = {
        "evidence_source": "reviewed_requirement_action",
        "source_run_id": THIRD_IDENTIFIER,
        "requirement_plan_confirmation_id": FOURTH_IDENTIFIER,
        "requirement_plan_evidence_fingerprint": FIFTH_IDENTIFIER,
        "candidate_manifest_fingerprint": SIXTH_IDENTIFIER,
        "confirmation_id": "1" * 64,
        "proposal_id": None,
        "evidence_fingerprint": REQUIREMENT_ACTION_AWAITING_REVIEW_FINGERPRINT,
        "evidence_schema_version": "requirement-action-evidence-v1",
        "evidence_policy_version": "reviewed-requirement-action-v1",
        "local_only": True,
        "content_persisted": False,
    }

    with pytest.raises(ValidationError):
        ModelRequirementActionEvidenceBindingDto.model_validate(payload)
