"""Strict, URL-free signed update manifest contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal


from pydantic import ConfigDict, Field, field_validator, model_validator

from ...domain import StrictModel

MAX_UPDATE_MANIFEST_BYTES = 32 * 1024
MAX_UPDATE_SIGNATURE_BYTES = 512
APPLICATION_UPDATE_STATUS_CONTRACT_VERSION = "application-update-status.v3"


class UpdateChannel(StrEnum):
    STABLE = "stable"
    BETA = "beta"


class UpdateManifest(StrictModel):
    model_config = ConfigDict(extra="forbid",
                              frozen=True,
                              hide_input_in_errors=True)

    schema_version: Literal[1]
    release_version: str = Field(
        max_length=32,
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
    minimum_supported_version: str = Field(
        max_length=32,
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
    channel: UpdateChannel
    published_at: datetime
    expires_at: datetime
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_size_bytes: int = Field(gt=0, le=4 * 1024 * 1024 * 1024)

    @field_validator("published_at", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("update timestamps must be timezone-aware")
        return value

    @field_validator("schema_version", "artifact_size_bytes", mode="before")
    @classmethod
    def reject_boolean_integers(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("update integer fields require JSON integers")
        return value


class UpdateRejection(StrEnum):
    BAD_SIGNATURE = "bad_signature"
    CHANNEL_MISMATCH = "channel_mismatch"
    CURRENT_VERSION = "current_version"
    DOWNGRADE = "downgrade"
    EXPIRED = "expired"
    INVALID_ENCODING = "invalid_encoding"
    INVALID_SCHEMA = "invalid_schema"
    MANIFEST_TOO_LARGE = "manifest_too_large"
    MINIMUM_VERSION_UNSUPPORTED = "minimum_version_unsupported"
    NOT_YET_PUBLISHED = "not_yet_published"
    SIGNATURE_TOO_LARGE = "signature_too_large"
    UNKNOWN_KEY = "unknown_key"
    REPLAYED_RELEASE = "replayed_release"
    RELEASE_IDENTITY_CONFLICT = "release_identity_conflict"


class UpdateVerificationState(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class UpdateVerification(StrictModel):
    model_config = ConfigDict(extra="forbid",
                              frozen=True,
                              hide_input_in_errors=True)

    state: UpdateVerificationState
    rejection: UpdateRejection | None = None
    manifest: UpdateManifest | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def validate_result(self) -> UpdateVerification:
        if self.state is UpdateVerificationState.ACCEPTED:
            if self.manifest is None or self.rejection is not None:
                raise ValueError("accepted update requires only a manifest")
        elif self.rejection is None or self.manifest is not None:
            raise ValueError("rejected update requires only a rejection code")
        return self


class ApplicationUpdateState(StrEnum):
    """Owner-visible application update lifecycle without paths or URLs."""

    UNCONFIGURED = "unconfigured"
    READY_TO_CHECK = "ready_to_check"
    CHECKING = "checking"
    CURRENT = "current"
    AVAILABLE = "available"
    STAGING = "staging"
    STAGED = "staged"
    VERIFYING = "verifying"
    FAILED = "failed"


class ApplicationUpdateReason(StrEnum):
    RELEASE_FEED_UNCONFIGURED = "release_feed_unconfigured"
    RELEASE_FEED_UNAVAILABLE = "release_feed_unavailable"
    MANIFEST_REJECTED = "manifest_rejected"
    ARTIFACT_DOWNLOAD_FAILED = "artifact_download_failed"
    ARTIFACT_VERIFICATION_FAILED = "artifact_verification_failed"
    STAGING_INTERRUPTED = "staging_interrupted"
    STAGING_CLEANUP_UNCONFIRMED = "staging_cleanup_unconfirmed"


class PackageReviewState(StrEnum):
    NOT_CONFIGURED = "not_configured"
    NOT_STAGED = "not_staged"
    NOT_CHECKED = "not_checked"
    CHECKING = "checking"
    VERIFIED = "verified"
    REJECTED = "rejected"


class PackageReview(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    state: PackageReviewState
    reason_code: Literal[
        "unsupported_platform", "unsupported_package", "package_io_failed",
        "package_changed", "release_binding_mismatch", "archive_invalid",
        "manifest_invalid", "identity_mismatch", "signature_invalid",
        "signature_unverifiable", "signer_mismatch",
    ] | UpdateRejection | None = None
    checked_at: datetime | None = None

    @field_validator("checked_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("package review timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_review(self) -> "PackageReview":
        terminal = self.state in {PackageReviewState.VERIFIED, PackageReviewState.REJECTED}
        if terminal != (self.checked_at is not None):
            raise ValueError("terminal package review requires its check time")
        if self.state is PackageReviewState.REJECTED and self.reason_code is None:
            raise ValueError("rejected package review requires a reason")
        if self.state is not PackageReviewState.REJECTED and self.reason_code is not None:
            raise ValueError("only rejected package review carries a reason")
        return self


class ApplicationUpdateStatus(StrictModel):
    """Content-free snapshot rendered by the application shell."""

    model_config = ConfigDict(extra="forbid",
                              frozen=True,
                              hide_input_in_errors=True)

    contract_version: Literal["application-update-status.v3"] = (
        APPLICATION_UPDATE_STATUS_CONTRACT_VERSION)
    contains_private_data: Literal[False] = False
    installed_version: str = Field(
        max_length=32,
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
    channel: UpdateChannel
    state: ApplicationUpdateState
    instance_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    revision: int = Field(ge=0, le=9_007_199_254_740_991)
    available_version: str | None = Field(
        default=None,
        max_length=32,
        pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$",
    )
    artifact_size_bytes: int | None = Field(default=None, gt=0, le=4 * 1024**3)
    downloaded_bytes: int | None = Field(default=None, ge=0, le=4 * 1024**3)
    last_checked_at: datetime | None = None
    reason_code: ApplicationUpdateReason | None = None
    verification_code: UpdateRejection | None = None
    can_check: bool
    can_stage: bool
    can_cancel: bool
    can_retry: bool
    can_apply: bool
    can_verify: bool = False
    package_review: PackageReview = PackageReview(state=PackageReviewState.NOT_STAGED)

    @field_validator("artifact_size_bytes",
                     "downloaded_bytes",
                     "revision",
                     mode="before")
    @classmethod
    def reject_boolean_optional_integers(cls, value: object) -> object:
        if value is not None and (isinstance(value, bool)
                                  or not isinstance(value, int)):
            raise ValueError("update numeric fields require JSON integers")
        return value

    @field_validator("last_checked_at")
    @classmethod
    def require_checked_timezone(cls,
                                 value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None
                                  or value.utcoffset() is None):
            raise ValueError("update check timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_surface_state(self) -> ApplicationUpdateStatus:
        has_release = self.available_version is not None
        has_size = self.artifact_size_bytes is not None
        has_check = self.last_checked_at is not None
        actions = (
            self.can_check,
            self.can_stage,
            self.can_cancel,
            self.can_retry,
            self.can_apply,
        )

        if self.can_apply:
            raise ValueError(
                "application installation handoff is not connected")
        review = self.package_review
        if self.state is ApplicationUpdateState.UNCONFIGURED:
            if review.state is not PackageReviewState.NOT_CONFIGURED:
                raise ValueError("unconfigured package review is inconsistent")
        elif self.state is ApplicationUpdateState.STAGED:
            allowed = ({PackageReviewState.NOT_CHECKED, PackageReviewState.VERIFIED,
                        PackageReviewState.REJECTED} if self.can_verify
                       else {PackageReviewState.NOT_CONFIGURED})
            if review.state not in allowed:
                raise ValueError("staged package review is inconsistent")
        elif self.state is not ApplicationUpdateState.VERIFYING:
            if self.can_verify or review.state is not PackageReviewState.NOT_STAGED:
                raise ValueError("non-staged package review is inconsistent")
        if self.state is ApplicationUpdateState.VERIFYING:
            if (any(actions) or self.can_verify or review.state is not PackageReviewState.CHECKING
                    or not has_release or not has_size or not has_check
                    or self.downloaded_bytes != self.artifact_size_bytes
                    or self.reason_code is not None or self.verification_code is not None):
                raise ValueError("verifying update state is inconsistent")
            return self

        if self.state is ApplicationUpdateState.UNCONFIGURED:
            if (self.reason_code
                    is not ApplicationUpdateReason.RELEASE_FEED_UNCONFIGURED
                    or self.verification_code is not None or has_release
                    or has_size or has_check
                    or self.downloaded_bytes is not None or any(actions)):
                raise ValueError("unconfigured update state is inconsistent")
        elif self.state is ApplicationUpdateState.READY_TO_CHECK:
            if (self.reason_code is not None
                    or self.verification_code is not None or has_release
                    or has_size or has_check
                    or self.downloaded_bytes is not None):
                raise ValueError("ready update state is inconsistent")
            if actions != (True, False, False, False, False):
                raise ValueError("ready update actions are inconsistent")
        elif self.state is ApplicationUpdateState.CHECKING:
            if (self.reason_code is not None
                    or self.verification_code is not None or has_release
                    or has_size or has_check
                    or self.downloaded_bytes is not None or any(actions)):
                raise ValueError("checking update state is inconsistent")
        elif self.state is ApplicationUpdateState.CURRENT:
            if (self.reason_code is not None
                    or self.verification_code is not None or has_release
                    or has_size or not has_check
                    or self.downloaded_bytes is not None):
                raise ValueError("current update state is inconsistent")
            if actions != (True, False, False, False, False):
                raise ValueError("current update actions are inconsistent")
        elif self.state is ApplicationUpdateState.AVAILABLE:
            if (self.reason_code is not None
                    or self.verification_code is not None or not has_release
                    or not has_size or not has_check):
                raise ValueError("available update state is inconsistent")
            if self.downloaded_bytes not in {None, 0}:
                raise ValueError(
                    "unstaged update cannot report downloaded bytes")
            if (not self.can_check or self.can_cancel or self.can_retry
                    or self.can_apply):
                raise ValueError("available update actions are inconsistent")
        elif self.state is ApplicationUpdateState.STAGING:
            if (self.reason_code is not None
                    or self.verification_code is not None or not has_release
                    or not has_size or not has_check
                    or self.downloaded_bytes is None
                    or self.downloaded_bytes > self.artifact_size_bytes):
                raise ValueError("staging update state is inconsistent")
            if actions not in {
                (False, False, True, False, False),
                (False, False, False, False, False),
            }:
                raise ValueError("staging update actions are inconsistent")
        elif self.state is ApplicationUpdateState.STAGED:
            if (self.reason_code is not None
                    or self.verification_code is not None or not has_release
                    or not has_size or not has_check
                    or self.downloaded_bytes != self.artifact_size_bytes):
                raise ValueError("staged update state is inconsistent")
            if actions != (True, False, False, False, False):
                raise ValueError("staged update actions are inconsistent")
        elif (self.reason_code is None or self.can_stage or self.can_cancel
              or self.can_apply):
            raise ValueError("failed update state is inconsistent")
        else:
            if self.reason_code is ApplicationUpdateReason.STAGING_CLEANUP_UNCONFIRMED:
                if self.can_check or self.can_retry:
                    raise ValueError(
                        "cleanup-uncertain update state is quarantined")
            elif self.can_retry and self.reason_code not in {
                    ApplicationUpdateReason.RELEASE_FEED_UNAVAILABLE,
                    ApplicationUpdateReason.ARTIFACT_DOWNLOAD_FAILED,
                    ApplicationUpdateReason.STAGING_INTERRUPTED,
            }:
                raise ValueError(
                    "failed update retry capability is inconsistent")
            rejected_manifest = (self.reason_code
                                 is ApplicationUpdateReason.MANIFEST_REJECTED)
            has_verification = self.verification_code is not None
            if rejected_manifest != has_verification:
                raise ValueError(
                    "failed manifest verification state is inconsistent")
        return self
