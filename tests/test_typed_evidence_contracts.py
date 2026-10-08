from __future__ import annotations

from pydantic import SecretStr, ValidationError
import pytest

from prompt_enhancer.application.analysis import (
    ActionEvidence,
    ActionFamily,
    ActionState,
    DecisionEvidence,
    DecisionState,
    EphemeralTypedEvidenceProjection,
    FeedbackEvidence,
    RationaleState,
    TypedEvidenceKind,
    TypedEvidenceProvenance,
    VerificationEvidence,
    VerificationMethod,
    VerificationOutcome,
    validate_projection_descriptor,
)
from prompt_enhancer.application.analysis.text_contracts import TextLanguage
from prompt_enhancer.application.providers import (
    CapabilityKey,
    DecoderDescriptor,
    ProviderIdentity,
    ProviderSurface,
    SchemaArtifactKind,
    SchemaArtifactProvenance,
)
from prompt_enhancer.domain import Provider


ONE = "1" * 64
TWO = "2" * 64
THREE = "3" * 64
FOUR = "4" * 64


def _provenance() -> TypedEvidenceProvenance:
    return TypedEvidenceProvenance(
        provider=Provider.SYNTHETIC,
        provider_version="1.0.0",
        adapter_version="typed-adapter-1",
        decoder_key="typed-evidence",
        decoder_version="1",
        source_schema_version="typed-schema-1",
        extraction_complete=True,
    )


def _descriptor(*capabilities: CapabilityKey) -> DecoderDescriptor:
    return DecoderDescriptor(
        provider=ProviderIdentity(key="synthetic"),
        surface=ProviderSurface.TEXT_WINDOW,
        adapter_version="typed-adapter-1",
        decoder_key="typed-evidence",
        decoder_version="1",
        wire_schema_family="synthetic-typed-evidence",
        canonical_schema_version="typed-schema-1",
        schema_artifact=SchemaArtifactProvenance(
            artifact_key="synthetic-typed-evidence",
            artifact_version="1",
            kind=SchemaArtifactKind.SYNTHETIC,
        ),
        capabilities=capabilities,
    )


def test_projection_accepts_all_four_documented_evidence_kinds() -> None:
    records = (
        ActionEvidence(
            evidence_id=ONE,
            source_reference_id=ONE,
            sequence=0,
            family=ActionFamily.TOOL,
            state=ActionState.COMPLETED,
        ),
        DecisionEvidence(
            evidence_id=TWO,
            source_reference_id=TWO,
            sequence=1,
            state=DecisionState.ACCEPTED,
            rationale_state=RationaleState.PRESENT,
            rationale_reference_id=THREE,
        ),
        FeedbackEvidence(
            evidence_id=THREE,
            source_reference_id=THREE,
            sequence=2,
            language=TextLanguage.ENGLISH,
            text=SecretStr("Synthetic feedback only."),
        ),
        VerificationEvidence(
            evidence_id=FOUR,
            source_reference_id=FOUR,
            sequence=3,
            method=VerificationMethod.TEST,
            outcome=VerificationOutcome.PASSED,
            receipt_reference_ids=(ONE,),
        ),
    )
    projection = EphemeralTypedEvidenceProjection(
        session_id=FOUR,
        provenance=_provenance(),
        declared_kinds=frozenset(TypedEvidenceKind),
        records=records,
    )

    validate_projection_descriptor(
        projection,
        _descriptor(
            CapabilityKey.TOOL_EVENTS,
            CapabilityKey.DECISION_EVENTS,
            CapabilityKey.FEEDBACK_MESSAGES,
            CapabilityKey.VERIFICATION_EVENTS,
        ),
    )
    assert "Synthetic feedback only" not in repr(projection)
    assert "Synthetic feedback only" not in projection.model_dump_json()


def test_projection_rejects_undeclared_or_mismatched_provider_evidence() -> None:
    projection = EphemeralTypedEvidenceProjection(
        session_id=FOUR,
        provenance=_provenance(),
        declared_kinds=frozenset({TypedEvidenceKind.ACTION}),
        records=(
            ActionEvidence(
                evidence_id=ONE,
                source_reference_id=ONE,
                sequence=0,
                family=ActionFamily.TOOL,
                state=ActionState.COMPLETED,
            ),
        ),
    )

    with pytest.raises(ValueError, match="not declared"):
        validate_projection_descriptor(
            projection,
            _descriptor(CapabilityKey.USER_MESSAGES),
        )

    mismatch = projection.model_copy(
        update={
            "provenance": _provenance().model_copy(
                update={"decoder_version": "2"}
            )
        }
    )
    with pytest.raises(ValueError, match="does not match"):
        validate_projection_descriptor(
            mismatch,
            _descriptor(CapabilityKey.TOOL_EVENTS),
        )


def test_verification_requires_receipt_and_feedback_stays_secret() -> None:
    with pytest.raises(ValidationError):
        VerificationEvidence(
            evidence_id=ONE,
            source_reference_id=ONE,
            sequence=0,
            method=VerificationMethod.TEST,
            outcome=VerificationOutcome.PASSED,
            receipt_reference_ids=(),
        )

    feedback = FeedbackEvidence(
        evidence_id=ONE,
        source_reference_id=ONE,
        sequence=0,
        language=TextLanguage.ENGLISH,
        text=SecretStr("Synthetic feedback only."),
    )
    assert feedback.text.get_secret_value() == "Synthetic feedback only."
    assert "Synthetic feedback only" not in repr(feedback)


def test_decision_rationale_state_cannot_be_fabricated() -> None:
    with pytest.raises(ValidationError):
        DecisionEvidence(
            evidence_id=ONE,
            source_reference_id=ONE,
            sequence=0,
            state=DecisionState.ACCEPTED,
            rationale_state=RationaleState.PRESENT,
        )


def test_links_cannot_define_or_escape_their_own_denominator() -> None:
    linked_action = ActionEvidence(
        evidence_id=ONE,
        source_reference_id=TWO,
        sequence=0,
        family=ActionFamily.TOOL,
        state=ActionState.COMPLETED,
        requirement_reference_ids=(THREE,),
    )

    with pytest.raises(ValidationError, match="opportunity declaration"):
        EphemeralTypedEvidenceProjection(
            session_id=FOUR,
            provenance=_provenance(),
            declared_kinds=frozenset({TypedEvidenceKind.ACTION}),
            records=(linked_action,),
        )
