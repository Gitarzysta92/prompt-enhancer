"""Strict minimized HTTP shape for sealed r8 verification authority."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.analysis.session_model_ensemble import (
    RequirementVerificationEvidenceSource,
    SessionRequirementVerificationEvidenceBinding,
)
from prompt_enhancer.interfaces.http.model_ensemble_routes import (
    ModelRequirementVerificationEvidenceBindingDto,
)


SESSION_ID = "a" * 64
WINDOW_ID = "b" * 64
BINDING_ID = "c" * 64
PLAN_FIELDS = {
    "requirement_plan_confirmation_id": "1" * 64,
    "requirement_plan_proposal_id": "2" * 64,
    "requirement_plan_evidence_fingerprint": "3" * 64,
    "requirement_plan_schema_version": "requirement-plan-evidence-v1",
    "requirement_plan_policy_version": "reviewed-requirement-plan-v1",
    "requirement_plan_review_rubric_version": (
        "active-requirement-plan-review-rubric-v1"
    ),
}
VERSIONS = {
    "opportunity_issuer_version": (
        "reviewed-r6-requirement-opportunity-issuer-v1"
    ),
    "result_issuer_version": "local-objective-verification-result-issuer-v1",
    "acceptance_issuer_version": (
        "native-explicit-requirement-acceptance-issuer-v1"
    ),
    "evidence_schema_version": "requirement-verification-evidence-v1",
    "evidence_policy_version": (
        "app-issued-reviewed-requirement-verification-v1"
    ),
    "persistence_schema_version": "requirement-verification-persistence-v1",
    "evidence_projection_version": (
        "reviewed-requirement-verification-objective-projection-v1"
    ),
    "objective_projection_version": (
        "reviewed-requirement-verification-objective-projection-v1"
    ),
    "binding_schema_version": (
        "session-requirement-verification-evidence-binding-v1"
    ),
}
REQUIRED_NULLABLE_FIELDS = (
    "requirement_plan_confirmation_id",
    "requirement_plan_proposal_id",
    "requirement_plan_evidence_fingerprint",
    "requirement_plan_schema_version",
    "requirement_plan_policy_version",
    "requirement_plan_review_rubric_version",
    "opportunity_count",
    "opportunity_set_fingerprint",
    "evidence_set_fingerprint",
    "through_revision",
    "authority_head_count",
    "objective_result_count",
    "native_acceptance_count",
    "resolved_opportunity_count",
    "met_requirement_count",
)


def _binding(
    source: RequirementVerificationEvidenceSource,
) -> SessionRequirementVerificationEvidenceBinding:
    fields: dict[str, object] = {}
    if source is not RequirementVerificationEvidenceSource.UNAVAILABLE:
        fields.update(PLAN_FIELDS)
        fields.update(
            opportunity_count=(
                101
                if source
                is RequirementVerificationEvidenceSource.OPPORTUNITY_BOUND_EXCEEDED
                else 2
            ),
            opportunity_set_fingerprint="4" * 64,
        )
    if source is RequirementVerificationEvidenceSource.AWAITING_EVIDENCE:
        fields.update(
            authority_head_count=0,
            objective_result_count=0,
            native_acceptance_count=0,
            resolved_opportunity_count=0,
            met_requirement_count=0,
        )
    if source is RequirementVerificationEvidenceSource.PERSISTED_EVIDENCE:
        fields.update(
            evidence_set_fingerprint="5" * 64,
            through_revision=3,
            authority_head_count=2,
            objective_result_count=1,
            native_acceptance_count=1,
            resolved_opportunity_count=1,
            met_requirement_count=1,
        )
    return SessionRequirementVerificationEvidenceBinding(
        evidence_source=source,
        session_id=SESSION_ID,
        source_window_fingerprint=WINDOW_ID,
        binding_fingerprint=BINDING_ID,
        bound_at=datetime(2026, 1, 1, tzinfo=UTC),
        **VERSIONS,
        **fields,
    )


@pytest.mark.parametrize("source", list(RequirementVerificationEvidenceSource))
def test_public_r8_binding_is_exact_minimized_and_content_free(
    source: RequirementVerificationEvidenceSource,
) -> None:
    payload = ModelRequirementVerificationEvidenceBindingDto.from_binding(
        _binding(source)
    ).model_dump(mode="json")

    assert payload["evidence_source"] == source.value
    assert payload["binding_fingerprint"] == BINDING_ID
    assert payload["local_only"] is True
    assert payload["content_persisted"] is False
    assert "session_id" not in payload
    assert "source_window_fingerprint" not in payload
    assert "bound_at" not in payload
    serialized_keys = " ".join(payload).casefold()
    for forbidden in (
        "prompt",
        "transcript",
        "excerpt",
        "prose",
        "payload",
        "model_id",
        "raw_content",
        "file_path",
    ):
        assert forbidden not in serialized_keys


def test_public_r8_binding_rejects_partial_counts_versions_and_private_fields() -> None:
    payload = ModelRequirementVerificationEvidenceBindingDto.from_binding(
        _binding(RequirementVerificationEvidenceSource.PERSISTED_EVIDENCE)
    ).model_dump(mode="json")

    for update in (
        {"requirement_plan_proposal_id": None},
        {"authority_head_count": 1},
        {"resolved_opportunity_count": 3},
        {"binding_fingerprint": "not-a-pseudonym"},
        {"evidence_policy_version": "future-policy-v2"},
        {"session_id": SESSION_ID},
        {"bound_at": "2026-01-01T00:00:00Z"},
    ):
        with pytest.raises(ValidationError):
            ModelRequirementVerificationEvidenceBindingDto.model_validate(
                payload | update
            )


def test_public_r8_binding_preserves_unknown_authorities_as_unresolved() -> None:
    payload = ModelRequirementVerificationEvidenceBindingDto.from_binding(
        _binding(RequirementVerificationEvidenceSource.PERSISTED_EVIDENCE)
    ).model_dump(mode="json")

    assert payload["authority_head_count"] == 2
    assert payload["resolved_opportunity_count"] == 1
    assert ModelRequirementVerificationEvidenceBindingDto.model_validate(
        payload
    ).resolved_opportunity_count == 1


def test_public_r8_binding_requires_every_nullable_wire_key() -> None:
    payload = ModelRequirementVerificationEvidenceBindingDto.from_binding(
        _binding(RequirementVerificationEvidenceSource.UNAVAILABLE)
    ).model_dump(mode="json")

    assert all(field in payload and payload[field] is None for field in REQUIRED_NULLABLE_FIELDS)
    for field in REQUIRED_NULLABLE_FIELDS:
        missing = dict(payload)
        del missing[field]
        with pytest.raises(ValidationError):
            ModelRequirementVerificationEvidenceBindingDto.model_validate(missing)


def test_public_r8_openapi_marks_nullable_keys_as_required() -> None:
    schema = ModelRequirementVerificationEvidenceBindingDto.model_json_schema()

    assert set(REQUIRED_NULLABLE_FIELDS) <= set(schema["required"])
    for field in REQUIRED_NULLABLE_FIELDS:
        property_schema = schema["properties"][field]
        assert "default" not in property_schema
        assert any(option.get("type") == "null" for option in property_schema["anyOf"])
