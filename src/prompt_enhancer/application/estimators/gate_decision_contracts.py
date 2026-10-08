"""Repository-sealed, deliberately non-activating gate-decision contracts.

The public models below are data structures, not authority tokens.  A trusted
decision is one returned by the SQLite repository after it has rehydrated and
rederived the complete v16/v17/v19 lineage in one transaction.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
import hashlib
import json
import math
import re
from typing import Literal, Protocol

from pydantic import Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, StrictModel


GATE_DECISION_DEFINITION_V1 = "gate-decision-definition-v1"
GATE_DECISION_VALUE_V1 = "gate-decision-value-v1"
GATE_DECISION_CHECK_V1 = "gate-decision-check-v1"
REPOSITORY_SEALED_GATE_DECISION_V1 = "repository-sealed-gate-decision-v1"
GATE_DECISION_EVALUATOR_V1 = "repository-gate-evaluator-v1"

_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_.-]{0,191}$")
_MAX_SAFE_INTEGER = 9_007_199_254_740_991


def canonical_payload_digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()


def _canonical_digest(value: StrictModel) -> str:
    return canonical_payload_digest(value.model_dump(mode="json"))


def _digest(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase SHA-256 identifier")
    return value


def _safe_code(value: str) -> str:
    if _SAFE_CODE.fullmatch(value) is None:
        raise ValueError("value must be a lowercase content-free code")
    return value


def _optional_code(value: str | None) -> str | None:
    return None if value is None else _safe_code(value)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return value


def _finite(value: float) -> float:
    number = float(value)
    if isinstance(value, bool) or not math.isfinite(number):
        raise ValueError("gate values must be finite numbers")
    if number == 0.0 and math.copysign(1.0, number) < 0:
        raise ValueError("negative zero is not a canonical gate value")
    return number


class GateDecisionOutcome(StrEnum):
    REJECTED = "rejected"
    INSUFFICIENT_DATA = "insufficient_data"


class GateDecisionCheckOutcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INSUFFICIENT_DATA = "insufficient_data"
    UNSUPPORTED = "unsupported"


class GateDecisionCheckCategory(StrEnum):
    INTEGRITY = "integrity"
    POLICY = "policy"


class GateDecisionValueShape(StrEnum):
    NONE = "none"
    COUNT = "count"
    SCALAR = "scalar"
    RATE = "rate"


class GateDecisionOperator(StrEnum):
    EQ = "eq"
    GTE = "gte"
    GT = "gt"
    LTE = "lte"
    LT = "lt"


class GateDecisionDefinitionV1(StrictModel):
    """Code-owned evaluator and missingness semantics."""

    contract_version: Literal[GATE_DECISION_DEFINITION_V1] = (
        GATE_DECISION_DEFINITION_V1
    )
    definition_version: Literal["repository-gate-policy-v1"] = (
        "repository-gate-policy-v1"
    )
    evaluator_version: Literal[GATE_DECISION_EVALUATOR_V1] = (
        GATE_DECISION_EVALUATOR_V1
    )
    lineage_version: Literal["sealed-v16-v17-v19-lineage-v1"] = (
        "sealed-v16-v17-v19-lineage-v1"
    )
    missingness_version: Literal["unknown-never-zero-or-fail-v1"] = (
        "unknown-never-zero-or-fail-v1"
    )
    outcome_version: Literal["reject-or-insufficient-only-v1"] = (
        "reject-or-insufficient-only-v1"
    )
    threshold_version: Literal["preregistered-boundaries-v1"] = (
        "preregistered-boundaries-v1"
    )
    vocabulary_version: Literal["registered-policy-expanded-v1"] = (
        "registered-policy-expanded-v1"
    )
    activation_allowed: Literal[False] = False

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


FIXED_GATE_DECISION_DEFINITION = GateDecisionDefinitionV1()


class GateDecisionValueV1(StrictModel):
    contract_version: Literal[GATE_DECISION_VALUE_V1] = GATE_DECISION_VALUE_V1
    shape: GateDecisionValueShape
    unit_code: str
    integer_value: int | None = Field(
        default=None, ge=-_MAX_SAFE_INTEGER, le=_MAX_SAFE_INTEGER
    )
    scalar_value: float | None = Field(default=None, allow_inf_nan=False)

    _unit = field_validator("unit_code")(_safe_code)
    _scalar = field_validator("scalar_value")(
        lambda value: None if value is None else _finite(value)
    )

    @model_validator(mode="after")
    def validate_shape(self) -> GateDecisionValueV1:
        if self.shape is GateDecisionValueShape.NONE:
            if (
                self.unit_code != "none"
                or self.integer_value is not None
                or self.scalar_value is not None
            ):
                raise ValueError("none values cannot carry a unit or number")
        elif self.shape is GateDecisionValueShape.COUNT:
            if (
                self.unit_code == "none"
                or self.integer_value is None
                or self.integer_value < 0
                or self.scalar_value is not None
            ):
                raise ValueError("count values require one nonnegative integer")
        elif self.shape is GateDecisionValueShape.SCALAR:
            if (
                self.unit_code == "none"
                or self.scalar_value is None
                or self.integer_value is not None
            ):
                raise ValueError("scalar values require one finite scalar")
        elif (
            self.unit_code != "ratio"
            or self.scalar_value is None
            or self.integer_value is not None
            or not 0.0 <= self.scalar_value <= 1.0
        ):
            raise ValueError("rate values require one finite ratio")
        return self

    @property
    def numeric_value(self) -> int | float | None:
        return self.integer_value if self.shape is GateDecisionValueShape.COUNT else self.scalar_value

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


NONE_GATE_VALUE = GateDecisionValueV1(
    shape=GateDecisionValueShape.NONE, unit_code="none"
)


class GateDecisionCheckV1(StrictModel):
    contract_version: Literal[GATE_DECISION_CHECK_V1] = GATE_DECISION_CHECK_V1
    check_key: str
    category: GateDecisionCheckCategory
    outcome: GateDecisionCheckOutcome
    operator: GateDecisionOperator
    actual: GateDecisionValueV1
    threshold: GateDecisionValueV1
    reason_code: str | None = None

    _key = field_validator("check_key")(_safe_code)
    _reason = field_validator("reason_code")(_optional_code)

    @model_validator(mode="after")
    def validate_result(self) -> GateDecisionCheckV1:
        actual = GateDecisionValueV1.model_validate(
            self.actual.model_dump(mode="python")
        )
        threshold = GateDecisionValueV1.model_validate(
            self.threshold.model_dump(mode="python")
        )
        known = self.outcome in {
            GateDecisionCheckOutcome.PASS,
            GateDecisionCheckOutcome.FAIL,
        }
        if known:
            if (
                actual.shape is GateDecisionValueShape.NONE
                or threshold.shape is GateDecisionValueShape.NONE
                or actual.shape is not threshold.shape
                or actual.unit_code != threshold.unit_code
            ):
                raise ValueError("known checks require comparable typed values")
            left = actual.numeric_value
            right = threshold.numeric_value
            assert left is not None and right is not None
            passed = {
                GateDecisionOperator.EQ: left == right,
                GateDecisionOperator.GTE: left >= right,
                GateDecisionOperator.GT: left > right,
                GateDecisionOperator.LTE: left <= right,
                GateDecisionOperator.LT: left < right,
            }.get(self.operator)
            if passed is None or (
                passed != (self.outcome is GateDecisionCheckOutcome.PASS)
            ):
                raise ValueError("check outcome does not match its exact operator")
            if (self.outcome is GateDecisionCheckOutcome.PASS) != (
                self.reason_code is None
            ):
                raise ValueError("only passing checks omit a reason")
        else:
            if (
                actual.shape is not GateDecisionValueShape.NONE
                or self.reason_code is None
            ):
                raise ValueError(
                    "missing or unsupported checks require no actual and a reason"
                )
            if threshold.shape is GateDecisionValueShape.NONE:
                if self.operator is not GateDecisionOperator.EQ:
                    raise ValueError("unthresholded checks use the exact none operator")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


def repository_gate_decision_id(
    report_id: str,
    report_receipt_fingerprint: str,
    definition_fingerprint: str,
    derived_at: datetime,
) -> str:
    for value in (report_id, report_receipt_fingerprint, definition_fingerprint):
        _digest(value)
    _utc(derived_at)
    return canonical_payload_digest(
        {
            "domain": REPOSITORY_SEALED_GATE_DECISION_V1,
            "report_id": report_id,
            "report_receipt_fingerprint": report_receipt_fingerprint,
            "definition_fingerprint": definition_fingerprint,
            "derived_at": derived_at.isoformat(timespec="microseconds"),
        }
    )


class RepositorySealedGateDecisionV1(StrictModel):
    """Exact root over a complete, canonical set of repository-derived checks."""

    contract_version: Literal[REPOSITORY_SEALED_GATE_DECISION_V1] = (
        REPOSITORY_SEALED_GATE_DECISION_V1
    )
    decision_id: str
    campaign_id: str
    campaign_fingerprint: str
    stored_plan_fingerprint: str
    policy_fingerprint: str
    assignment_manifest_fingerprint: str
    split_fingerprint: str
    preregistration_fingerprint: str
    preregistration_v2_fingerprint: str
    constellation_fingerprint: str
    submission_id: str
    submission_fingerprint: str
    report_id: str
    report_receipt_id: str
    report_fingerprint: str
    report_receipt_fingerprint: str
    report_definition_fingerprint: str
    report_source_bundle_fingerprint: str
    definition: GateDecisionDefinitionV1
    definition_fingerprint: str
    evaluator_version: Literal[GATE_DECISION_EVALUATOR_V1] = GATE_DECISION_EVALUATOR_V1
    checks: tuple[GateDecisionCheckV1, ...]
    check_set_fingerprint: str
    outcome: GateDecisionOutcome
    campaign_registered_at: datetime
    submission_submitted_at: datetime
    report_derived_at: datetime
    derived_at: datetime
    repository_owned: Literal[True] = True
    repository_sealed: Literal[True] = True
    persistence_state: Literal["repository_sealed"] = "repository_sealed"
    activation_allowed: Literal[False] = False
    activation_slot_written: Literal[False] = False
    comparison_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _digests = field_validator(
        "decision_id",
        "campaign_id",
        "campaign_fingerprint",
        "stored_plan_fingerprint",
        "policy_fingerprint",
        "assignment_manifest_fingerprint",
        "split_fingerprint",
        "preregistration_fingerprint",
        "preregistration_v2_fingerprint",
        "constellation_fingerprint",
        "submission_id",
        "submission_fingerprint",
        "report_id",
        "report_receipt_id",
        "report_fingerprint",
        "report_receipt_fingerprint",
        "report_definition_fingerprint",
        "report_source_bundle_fingerprint",
        "definition_fingerprint",
        "check_set_fingerprint",
    )(_digest)
    _times = field_validator(
        "campaign_registered_at",
        "submission_submitted_at",
        "report_derived_at",
        "derived_at",
    )(_utc)

    @model_validator(mode="after")
    def validate_seal(self) -> RepositorySealedGateDecisionV1:
        definition = GateDecisionDefinitionV1.model_validate(
            self.definition.model_dump(mode="python")
        )
        checks = tuple(
            GateDecisionCheckV1.model_validate(item.model_dump(mode="python"))
            for item in self.checks
        )
        if definition != FIXED_GATE_DECISION_DEFINITION:
            raise ValueError("gate decision definition is not code-owned")
        if self.definition_fingerprint != definition.fingerprint:
            raise ValueError("decision does not bind the fixed definition")
        keys = tuple(item.check_key for item in checks)
        if not keys or keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("gate checks must be unique and canonically sorted")
        expected_set = canonical_payload_digest(
            [item.model_dump(mode="json") for item in checks]
        )
        if self.check_set_fingerprint != expected_set:
            raise ValueError("decision does not bind its complete check set")
        outcomes = {item.outcome for item in checks}
        expected_outcome = (
            GateDecisionOutcome.REJECTED
            if GateDecisionCheckOutcome.FAIL in outcomes
            else GateDecisionOutcome.INSUFFICIENT_DATA
            if outcomes
            & {
                GateDecisionCheckOutcome.INSUFFICIENT_DATA,
                GateDecisionCheckOutcome.UNSUPPORTED,
            }
            else None
        )
        if expected_outcome is None:
            raise ValueError("v20 cannot represent an all-pass eligible decision")
        if self.outcome is not expected_outcome:
            raise ValueError("decision outcome must be derived from every check")
        if not (
            self.campaign_registered_at
            <= self.submission_submitted_at
            <= self.report_derived_at
            <= self.derived_at
        ):
            raise ValueError("decision lineage timestamps are not chronological")
        if self.decision_id != repository_gate_decision_id(
            self.report_id,
            self.report_receipt_fingerprint,
            self.definition_fingerprint,
            self.derived_at,
        ):
            raise ValueError("repository decision identifier is not reproducible")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


def revalidate_repository_sealed_gate_decision_v1(
    decision: RepositorySealedGateDecisionV1,
) -> RepositorySealedGateDecisionV1:
    return RepositorySealedGateDecisionV1.model_validate(
        decision.model_dump(mode="python")
    )


class GateDecisionRepository(Protocol):
    def derive_gate_decision(
        self, report_id: str
    ) -> RepositorySealedGateDecisionV1: ...

    def get_gate_decision_for_report(
        self, report_id: str
    ) -> RepositorySealedGateDecisionV1 | None: ...


__all__ = [
    "FIXED_GATE_DECISION_DEFINITION",
    "GATE_DECISION_EVALUATOR_V1",
    "GateDecisionCheckCategory",
    "GateDecisionCheckOutcome",
    "GateDecisionCheckV1",
    "GateDecisionDefinitionV1",
    "GateDecisionOperator",
    "GateDecisionOutcome",
    "GateDecisionRepository",
    "GateDecisionValueShape",
    "GateDecisionValueV1",
    "NONE_GATE_VALUE",
    "REPOSITORY_SEALED_GATE_DECISION_V1",
    "RepositorySealedGateDecisionV1",
    "canonical_payload_digest",
    "repository_gate_decision_id",
    "revalidate_repository_sealed_gate_decision_v1",
]
