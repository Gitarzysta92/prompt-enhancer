"""Privacy-bounded contracts for local verification classification.

The candidate is intentionally ephemeral.  It may contain a selected command in
memory, but it is never a persistence or HTTP DTO.  Classifiers return only a
small, content-free decision whose identifiers are safe to persist later.
"""

from __future__ import annotations

from enum import StrEnum
import re
from typing import Protocol

from pydantic import Field, SecretStr, field_validator, model_validator

from ...domain import Provider, StrictModel


SAFE_RULE_ID = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
SAFE_COMPONENT_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
MAX_EPHEMERAL_COMMAND_LENGTH = 16_384


class VerificationKind(StrEnum):
    TEST = "test"
    BUILD = "build"
    LINT = "lint"
    TYPE_CHECK = "type_check"
    SECURITY = "security"
    ARTIFACT_VALIDATION = "artifact_validation"


class VerificationExecutionState(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"


class VerificationOutcome(StrEnum):
    PASSED = "passed"
    CHECK_FAILED = "check_failed"
    INTERRUPTED = "interrupted"
    EXECUTION_ERROR = "execution_error"
    NO_EVALUABLE_CHECKS = "no_evaluable_checks"
    UNKNOWN = "unknown"


class VerificationClassificationDecision(StrEnum):
    VERIFICATION = "verification"
    KNOWN_NON_VERIFICATION = "known_non_verification"
    ABSTAINED = "abstained"


class VerificationAbstentionReason(StrEnum):
    EMPTY = "empty"
    TOO_LARGE = "too_large"
    UNSAFE_SHAPE = "unsafe_shape"
    AMBIGUOUS_SHELL = "ambiguous_shell"
    INCOMPATIBLE_SCHEMA = "incompatible_schema"
    UNSUPPORTED_SIGNATURE = "unsupported_signature"


class VerificationCapabilityState(StrEnum):
    SUPPORTED = "supported"
    VALIDATION_ONLY = "validation_only"
    UNSUPPORTED = "unsupported"
    INCOMPATIBLE = "incompatible"
    NOT_AUTHORIZED = "not_authorized"


class EphemeralVerificationCandidate(StrictModel):
    """A selected local command that must not cross the classifier boundary."""

    provider: Provider
    source_item_id: SecretStr = Field(repr=False)
    command: SecretStr = Field(repr=False)
    candidate_schema_version: str
    execution_state: VerificationExecutionState = VerificationExecutionState.UNKNOWN
    exit_code: int | None = Field(default=None, ge=-2_147_483_648, le=2_147_483_647)

    @field_validator("source_item_id", mode="before")
    @classmethod
    def require_bounded_source_id(cls, value: object) -> object:
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(raw, str) or not raw:
            raise ValueError("ephemeral verification input is invalid")
        if len(raw) > 4_096:
            raise ValueError("ephemeral verification input exceeds its bound")
        return value

    @field_validator("command", mode="before")
    @classmethod
    def require_bounded_command(cls, value: object) -> object:
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(raw, str):
            raise ValueError("ephemeral verification command is invalid")
        if len(raw) > MAX_EPHEMERAL_COMMAND_LENGTH:
            raise ValueError("ephemeral verification command exceeds its bound")
        return value

    @field_validator("candidate_schema_version")
    @classmethod
    def require_safe_schema_version(cls, value: str) -> str:
        if not SAFE_COMPONENT_VERSION.fullmatch(value):
            raise ValueError("candidate schema version is invalid")
        return value


class VerificationClassification(StrictModel):
    """Content-free tri-state result from a local classifier."""

    decision: VerificationClassificationDecision
    kind: VerificationKind | None = None
    rule_id: str | None = None
    abstention_reason: VerificationAbstentionReason | None = None
    classifier_version: str
    normalizer_version: str

    @field_validator("classifier_version", "normalizer_version")
    @classmethod
    def require_safe_version(cls, value: str) -> str:
        if not SAFE_COMPONENT_VERSION.fullmatch(value):
            raise ValueError("verification component version is invalid")
        return value

    @field_validator("rule_id")
    @classmethod
    def require_safe_rule(cls, value: str | None) -> str | None:
        if value is not None and not SAFE_RULE_ID.fullmatch(value):
            raise ValueError("verification rule identifier is invalid")
        return value

    @model_validator(mode="after")
    def validate_decision_shape(self) -> VerificationClassification:
        if self.decision is VerificationClassificationDecision.VERIFICATION:
            if self.kind is None or self.rule_id is None or self.abstention_reason is not None:
                raise ValueError("verification decisions require one safe matched rule")
        elif self.decision is VerificationClassificationDecision.KNOWN_NON_VERIFICATION:
            if self.kind is not None or self.rule_id is None or self.abstention_reason is not None:
                raise ValueError("known non-verification decisions require one safe rule")
        elif (
            self.kind is not None
            or self.rule_id is not None
            or self.abstention_reason is None
        ):
            raise ValueError("abstentions require only a safe reason code")
        return self


class VerificationCapability(StrictModel):
    """Truthful provider capability shown before any verification claim."""

    state: VerificationCapabilityState
    live_classification_enabled: bool
    classifier_version: str | None = None
    normalizer_version: str | None = None
    candidate_schema_version: str | None = None
    supported_kinds: tuple[VerificationKind, ...] = ()
    reason_code: str

    @field_validator(
        "classifier_version", "normalizer_version", "candidate_schema_version"
    )
    @classmethod
    def require_optional_safe_version(cls, value: str | None) -> str | None:
        if value is not None and not SAFE_COMPONENT_VERSION.fullmatch(value):
            raise ValueError("verification capability version is invalid")
        return value

    @field_validator("reason_code")
    @classmethod
    def require_safe_reason(cls, value: str) -> str:
        if not SAFE_RULE_ID.fullmatch(value):
            raise ValueError("verification capability reason is invalid")
        return value

    @model_validator(mode="after")
    def live_requires_supported_state(self) -> VerificationCapability:
        if self.live_classification_enabled != (
            self.state is VerificationCapabilityState.SUPPORTED
        ):
            raise ValueError("supported verification and live enablement must agree")
        if self.state in {
            VerificationCapabilityState.SUPPORTED,
            VerificationCapabilityState.VALIDATION_ONLY,
        }:
            if not (
                self.classifier_version
                and self.normalizer_version
                and self.candidate_schema_version
                and self.supported_kinds
            ):
                raise ValueError("verification classifier provenance is incomplete")
        return self


class VerificationClassifier(Protocol):
    classifier_version: str
    normalizer_version: str

    def classify(
        self, candidate: EphemeralVerificationCandidate
    ) -> VerificationClassification:
        """Classify locally without retaining or exposing the transient command."""
