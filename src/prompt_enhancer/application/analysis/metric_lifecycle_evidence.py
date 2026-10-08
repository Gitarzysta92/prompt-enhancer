"""Explicit local-user evidence for five collaboration lifecycle metrics.

The proposal surface is deliberately content-free.  A caller may select only
closed opportunity, link, and outcome kinds and may refer only to identifiers
previously issued by this service.  Proposals are inert until an authenticated
local user confirms them; rejected and undecided proposals never enter a
metric denominator.

Completeness is a separate, explicit claim.  A confirmed enumeration receipt
names the exact confirmed opportunities for one family in one bounded source
window.  Without that receipt the family remains unknown even when individual
opportunities or outcomes have been confirmed.  A confirmed enumerated
opportunity without an outcome is right-censored, not failed.

No record stores transcript text, excerpts, paths, labels, or caller supplied
times.  Identifiers are installation-local keyed pseudonyms and every time is
issued by the server clock.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Protocol

from pydantic import Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, Provider, StrictModel


METRIC_LIFECYCLE_EVIDENCE_SCHEMA_VERSION = "metric-lifecycle-evidence-v1"
METRIC_LIFECYCLE_EVIDENCE_POLICY_VERSION = "explicit-local-confirmation-v1"
METRIC_LIFECYCLE_PROPOSAL_REVISION = 1
METRIC_LIFECYCLE_DECISION_CONFIRMATION = (
    "apply_local_user_metric_lifecycle_decision"
)
MAX_LIFECYCLE_ENUMERATION_SIZE = 1_000


class MetricLifecycleFamily(StrEnum):
    AMBIGUITY_RESOLUTION = "collaboration.ambiguity_resolution"
    CLARIFICATION_YIELD = "collaboration.clarification_yield"
    EXPLORATION_CONVERSION = "collaboration.exploration_conversion"
    SCOPE_CHANGE_DISCIPLINE = "collaboration.scope_change_discipline"
    REWORK_CANDIDATE_RATE = "collaboration.rework_candidate_rate"


class MetricLifecycleProposalKind(StrEnum):
    OPPORTUNITY = "opportunity"
    OUTCOME = "outcome"
    ENUMERATION = "enumeration"


class MetricLifecycleOpportunityKind(StrEnum):
    AMBIGUITY = "ambiguity"
    CLARIFICATION = "clarification"
    EXPLORATION = "exploration"
    SCOPE_CHANGE = "scope_change"
    REWORK = "rework"


class MetricLifecycleLinkKind(StrEnum):
    AMBIGUITY_RESOLUTION = "ambiguity_resolution"
    CLARIFICATION_ANSWER_INCORPORATION = "clarification_answer_incorporation"
    EXPLORATION_SUPPORT_DECISION = "exploration_support_decision"
    SCOPE_CHANGE_IMPACT_DISPOSITION = "scope_change_impact_disposition"
    REWORK_REQUIREMENT_ASSESSMENT = "rework_requirement_assessment"


class MetricLifecycleOutcomeKind(StrEnum):
    AMBIGUITY_RESOLVED = "ambiguity_resolved"
    AMBIGUITY_CLOSED_UNRESOLVED = "ambiguity_closed_unresolved"
    CLARIFICATION_INCORPORATED = "clarification_incorporated"
    CLARIFICATION_NOT_INCORPORATED = "clarification_not_incorporated"
    EXPLORATION_CONVERTED = "exploration_converted"
    EXPLORATION_NOT_CONVERTED = "exploration_not_converted"
    SCOPE_CHANGE_DISCIPLINED = "scope_change_disciplined"
    SCOPE_CHANGE_UNDISCIPLINED = "scope_change_undisciplined"
    REWORK_REQUIRED = "rework_required"
    REWORK_NOT_REQUIRED = "rework_not_required"


class MetricLifecycleDecisionKind(StrEnum):
    CONFIRM = "confirm"
    REJECT = "reject"


class MetricLifecycleProposalStatus(StrEnum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


FAMILY_OPPORTUNITY_KIND = MappingProxyType(
    {
        MetricLifecycleFamily.AMBIGUITY_RESOLUTION: (
            MetricLifecycleOpportunityKind.AMBIGUITY
        ),
        MetricLifecycleFamily.CLARIFICATION_YIELD: (
            MetricLifecycleOpportunityKind.CLARIFICATION
        ),
        MetricLifecycleFamily.EXPLORATION_CONVERSION: (
            MetricLifecycleOpportunityKind.EXPLORATION
        ),
        MetricLifecycleFamily.SCOPE_CHANGE_DISCIPLINE: (
            MetricLifecycleOpportunityKind.SCOPE_CHANGE
        ),
        MetricLifecycleFamily.REWORK_CANDIDATE_RATE: (
            MetricLifecycleOpportunityKind.REWORK
        ),
    }
)

FAMILY_LINK_KIND = MappingProxyType(
    {
        MetricLifecycleFamily.AMBIGUITY_RESOLUTION: (
            MetricLifecycleLinkKind.AMBIGUITY_RESOLUTION
        ),
        MetricLifecycleFamily.CLARIFICATION_YIELD: (
            MetricLifecycleLinkKind.CLARIFICATION_ANSWER_INCORPORATION
        ),
        MetricLifecycleFamily.EXPLORATION_CONVERSION: (
            MetricLifecycleLinkKind.EXPLORATION_SUPPORT_DECISION
        ),
        MetricLifecycleFamily.SCOPE_CHANGE_DISCIPLINE: (
            MetricLifecycleLinkKind.SCOPE_CHANGE_IMPACT_DISPOSITION
        ),
        MetricLifecycleFamily.REWORK_CANDIDATE_RATE: (
            MetricLifecycleLinkKind.REWORK_REQUIREMENT_ASSESSMENT
        ),
    }
)

FAMILY_OUTCOME_KINDS = MappingProxyType(
    {
        MetricLifecycleFamily.AMBIGUITY_RESOLUTION: frozenset(
            {
                MetricLifecycleOutcomeKind.AMBIGUITY_RESOLVED,
                MetricLifecycleOutcomeKind.AMBIGUITY_CLOSED_UNRESOLVED,
            }
        ),
        MetricLifecycleFamily.CLARIFICATION_YIELD: frozenset(
            {
                MetricLifecycleOutcomeKind.CLARIFICATION_INCORPORATED,
                MetricLifecycleOutcomeKind.CLARIFICATION_NOT_INCORPORATED,
            }
        ),
        MetricLifecycleFamily.EXPLORATION_CONVERSION: frozenset(
            {
                MetricLifecycleOutcomeKind.EXPLORATION_CONVERTED,
                MetricLifecycleOutcomeKind.EXPLORATION_NOT_CONVERTED,
            }
        ),
        MetricLifecycleFamily.SCOPE_CHANGE_DISCIPLINE: frozenset(
            {
                MetricLifecycleOutcomeKind.SCOPE_CHANGE_DISCIPLINED,
                MetricLifecycleOutcomeKind.SCOPE_CHANGE_UNDISCIPLINED,
            }
        ),
        MetricLifecycleFamily.REWORK_CANDIDATE_RATE: frozenset(
            {
                MetricLifecycleOutcomeKind.REWORK_REQUIRED,
                MetricLifecycleOutcomeKind.REWORK_NOT_REQUIRED,
            }
        ),
    }
)

MET_OUTCOME_KINDS = frozenset(
    {
        MetricLifecycleOutcomeKind.AMBIGUITY_RESOLVED,
        MetricLifecycleOutcomeKind.CLARIFICATION_INCORPORATED,
        MetricLifecycleOutcomeKind.EXPLORATION_CONVERTED,
        MetricLifecycleOutcomeKind.SCOPE_CHANGE_DISCIPLINED,
        # This metric is a lower-is-better candidate *rate*.  A confirmed
        # required-rework episode belongs in its numerator; it is not inverted
        # here to look like a quality score.
        MetricLifecycleOutcomeKind.REWORK_REQUIRED,
    }
)


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("identifier must be an installation-local pseudonym")
    return value


def _safe_code(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a short content-free identifier")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("server timestamps must be UTC")
    return value


class MetricLifecycleProposalCommand(StrictModel):
    """Closed proposal payload accepted by the authenticated local API."""

    expected_source_run_id: str
    proposal_kind: MetricLifecycleProposalKind
    family: MetricLifecycleFamily
    opportunity_kind: MetricLifecycleOpportunityKind
    opportunity_id: str | None = None
    link_kind: MetricLifecycleLinkKind | None = None
    outcome_kind: MetricLifecycleOutcomeKind | None = None
    enumerated_opportunity_ids: tuple[str, ...] = Field(
        default=(), max_length=MAX_LIFECYCLE_ENUMERATION_SIZE
    )

    _run = field_validator("expected_source_run_id")(_pseudonym)

    @field_validator("opportunity_id")
    @classmethod
    def validate_optional_opportunity_id(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @field_validator("enumerated_opportunity_ids")
    @classmethod
    def validate_enumeration_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(_pseudonym(item) for item in value)
        if len(set(checked)) != len(checked):
            raise ValueError("enumerated opportunity identifiers cannot repeat")
        if checked != tuple(sorted(checked)):
            raise ValueError("enumerated opportunity identifiers must be sorted")
        return checked

    @model_validator(mode="after")
    def validate_closed_shape(self) -> "MetricLifecycleProposalCommand":
        if self.opportunity_kind is not FAMILY_OPPORTUNITY_KIND[self.family]:
            raise ValueError("opportunity kind does not belong to the metric family")
        if self.proposal_kind is MetricLifecycleProposalKind.OPPORTUNITY:
            if (
                self.opportunity_id is not None
                or self.link_kind is not None
                or self.outcome_kind is not None
                or self.enumerated_opportunity_ids
            ):
                raise ValueError("an opportunity proposal cannot carry links or outcomes")
        elif self.proposal_kind is MetricLifecycleProposalKind.OUTCOME:
            if (
                self.opportunity_id is None
                or self.link_kind is not FAMILY_LINK_KIND[self.family]
                or self.outcome_kind not in FAMILY_OUTCOME_KINDS[self.family]
                or self.enumerated_opportunity_ids
            ):
                raise ValueError("outcome proposal fields do not match the metric family")
        elif (
            self.opportunity_id is not None
            or self.link_kind is not None
            or self.outcome_kind is not None
        ):
            raise ValueError("an enumeration proposal carries only opportunity identifiers")
        return self


class MetricLifecycleDecisionCommand(StrictModel):
    expected_source_run_id: str
    expected_proposal_revision: int = Field(
        default=METRIC_LIFECYCLE_PROPOSAL_REVISION,
        ge=METRIC_LIFECYCLE_PROPOSAL_REVISION,
        le=METRIC_LIFECYCLE_PROPOSAL_REVISION,
    )
    decision: MetricLifecycleDecisionKind
    confirmation: Literal[METRIC_LIFECYCLE_DECISION_CONFIRMATION]

    _run = field_validator("expected_source_run_id")(_pseudonym)


class MetricLifecycleProposalRecord(StrictModel):
    proposal_id: str
    session_id: str
    source_run_id: str
    source_window_fingerprint: str
    proposal_revision: int = Field(
        default=METRIC_LIFECYCLE_PROPOSAL_REVISION,
        ge=METRIC_LIFECYCLE_PROPOSAL_REVISION,
        le=METRIC_LIFECYCLE_PROPOSAL_REVISION,
    )
    proposal_kind: MetricLifecycleProposalKind
    family: MetricLifecycleFamily
    opportunity_kind: MetricLifecycleOpportunityKind
    opportunity_id: str | None = None
    link_kind: MetricLifecycleLinkKind | None = None
    outcome_kind: MetricLifecycleOutcomeKind | None = None
    enumerated_opportunity_ids: tuple[str, ...] = Field(
        default=(), max_length=MAX_LIFECYCLE_ENUMERATION_SIZE
    )
    idempotency_key_digest: str
    command_fingerprint: str
    created_at: datetime
    schema_version: str = METRIC_LIFECYCLE_EVIDENCE_SCHEMA_VERSION
    policy_version: str = METRIC_LIFECYCLE_EVIDENCE_POLICY_VERSION
    local_only: bool = True
    content_persisted: bool = False

    _ids = field_validator(
        "proposal_id",
        "session_id",
        "source_run_id",
        "source_window_fingerprint",
        "idempotency_key_digest",
        "command_fingerprint",
    )(_pseudonym)
    _codes = field_validator("schema_version", "policy_version")(_safe_code)
    _created = field_validator("created_at")(_utc)

    @field_validator("opportunity_id")
    @classmethod
    def validate_record_opportunity_id(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @model_validator(mode="after")
    def validate_record_shape(self) -> "MetricLifecycleProposalRecord":
        command = MetricLifecycleProposalCommand(
            expected_source_run_id=self.source_run_id,
            proposal_kind=self.proposal_kind,
            family=self.family,
            opportunity_kind=self.opportunity_kind,
            opportunity_id=(
                None
                if self.proposal_kind is MetricLifecycleProposalKind.OPPORTUNITY
                else self.opportunity_id
            ),
            link_kind=self.link_kind,
            outcome_kind=self.outcome_kind,
            enumerated_opportunity_ids=self.enumerated_opportunity_ids,
        )
        if self.proposal_kind is MetricLifecycleProposalKind.OPPORTUNITY:
            if self.opportunity_id is None:
                raise ValueError("the server must issue an opportunity identifier")
            if command.opportunity_id is not None:
                raise AssertionError("opportunity command normalization failed")
        if not self.local_only or self.content_persisted:
            raise ValueError("lifecycle evidence is local metadata only")
        return self


class MetricLifecycleDecisionRecord(StrictModel):
    decision_id: str
    proposal_id: str
    session_id: str
    expected_proposal_revision: int = Field(
        ge=METRIC_LIFECYCLE_PROPOSAL_REVISION,
        le=METRIC_LIFECYCLE_PROPOSAL_REVISION,
    )
    decision: MetricLifecycleDecisionKind
    idempotency_key_digest: str
    command_fingerprint: str
    decided_at: datetime
    confirmation_authority: str = "authenticated_local_user"
    schema_version: str = METRIC_LIFECYCLE_EVIDENCE_SCHEMA_VERSION
    local_only: bool = True
    content_persisted: bool = False

    _ids = field_validator(
        "decision_id",
        "proposal_id",
        "session_id",
        "idempotency_key_digest",
        "command_fingerprint",
    )(_pseudonym)
    _codes = field_validator("confirmation_authority", "schema_version")(_safe_code)
    _decided = field_validator("decided_at")(_utc)

    @model_validator(mode="after")
    def validate_privacy(self) -> "MetricLifecycleDecisionRecord":
        if not self.local_only or self.content_persisted:
            raise ValueError("lifecycle decisions are local metadata only")
        return self


class MetricLifecycleProposalView(StrictModel):
    proposal: MetricLifecycleProposalRecord
    decision: MetricLifecycleDecisionRecord | None = None

    @property
    def status(self) -> MetricLifecycleProposalStatus:
        if self.decision is None:
            return MetricLifecycleProposalStatus.PROPOSED
        if self.decision.decision is MetricLifecycleDecisionKind.CONFIRM:
            return MetricLifecycleProposalStatus.CONFIRMED
        return MetricLifecycleProposalStatus.REJECTED

    @model_validator(mode="after")
    def validate_binding(self) -> "MetricLifecycleProposalView":
        if self.decision is not None and (
            self.decision.proposal_id != self.proposal.proposal_id
            or self.decision.session_id != self.proposal.session_id
            or self.decision.expected_proposal_revision
            != self.proposal.proposal_revision
        ):
            raise ValueError("lifecycle decision describes another proposal")
        return self


class ConfirmedMetricLifecycleOutcome(StrictModel):
    decision_id: str
    link_kind: MetricLifecycleLinkKind
    outcome_kind: MetricLifecycleOutcomeKind
    decided_at: datetime

    _decision = field_validator("decision_id")(_pseudonym)
    _decided = field_validator("decided_at")(_utc)


class ConfirmedMetricLifecycleOpportunity(StrictModel):
    opportunity_id: str
    opportunity_kind: MetricLifecycleOpportunityKind
    confirmation_id: str
    confirmed_at: datetime
    outcome: ConfirmedMetricLifecycleOutcome | None = None

    _ids = field_validator("opportunity_id", "confirmation_id")(_pseudonym)
    _confirmed = field_validator("confirmed_at")(_utc)


class MetricLifecycleFamilyEvidence(StrictModel):
    family: MetricLifecycleFamily
    opportunity_kind: MetricLifecycleOpportunityKind
    enumeration_confirmed: bool
    enumeration_confirmation_id: str | None = None
    enumerated_opportunity_ids: tuple[str, ...] = ()
    opportunities: tuple[ConfirmedMetricLifecycleOpportunity, ...] = ()

    @field_validator("enumeration_confirmation_id")
    @classmethod
    def validate_optional_confirmation(cls, value: str | None) -> str | None:
        return None if value is None else _pseudonym(value)

    @model_validator(mode="after")
    def validate_evidence(self) -> "MetricLifecycleFamilyEvidence":
        if self.opportunity_kind is not FAMILY_OPPORTUNITY_KIND[self.family]:
            raise ValueError("family evidence has the wrong opportunity kind")
        ids = tuple(item.opportunity_id for item in self.opportunities)
        if len(set(ids)) != len(ids) or ids != tuple(sorted(ids)):
            raise ValueError("confirmed opportunities must be unique and sorted")
        enumerated = tuple(self.enumerated_opportunity_ids)
        if len(set(enumerated)) != len(enumerated) or enumerated != tuple(
            sorted(enumerated)
        ):
            raise ValueError("enumerated opportunity identifiers must be unique and sorted")
        if self.enumeration_confirmed != (
            self.enumeration_confirmation_id is not None
        ):
            raise ValueError("enumeration authority and identifier must agree")
        if self.enumeration_confirmed and enumerated != ids:
            raise ValueError("a confirmed enumeration must exactly cover opportunities")
        if not self.enumeration_confirmed and enumerated:
            raise ValueError("an unconfirmed enumeration has no authoritative members")
        for opportunity in self.opportunities:
            if opportunity.opportunity_kind is not self.opportunity_kind:
                raise ValueError("opportunity kind does not match family evidence")
            if opportunity.outcome is not None and (
                opportunity.outcome.link_kind is not FAMILY_LINK_KIND[self.family]
                or opportunity.outcome.outcome_kind
                not in FAMILY_OUTCOME_KINDS[self.family]
            ):
                raise ValueError("confirmed outcome does not match its family")
        return self


class MetricLifecycleEvidenceSnapshot(StrictModel):
    session_id: str
    source_window_fingerprint: str
    families: tuple[MetricLifecycleFamilyEvidence, ...] = Field(
        min_length=len(MetricLifecycleFamily),
        max_length=len(MetricLifecycleFamily),
    )
    schema_version: str = METRIC_LIFECYCLE_EVIDENCE_SCHEMA_VERSION
    local_only: bool = True
    content_persisted: bool = False

    _ids = field_validator("session_id", "source_window_fingerprint")(_pseudonym)
    _schema = field_validator("schema_version")(_safe_code)

    @model_validator(mode="after")
    def validate_snapshot(self) -> "MetricLifecycleEvidenceSnapshot":
        if tuple(item.family for item in self.families) != tuple(
            MetricLifecycleFamily
        ):
            raise ValueError("lifecycle snapshot must contain all families in order")
        if not self.local_only or self.content_persisted:
            raise ValueError("lifecycle snapshot is local metadata only")
        return self


class MetricLifecycleEvidenceRepository(Protocol):
    def issue_proposal(
        self, proposal: MetricLifecycleProposalRecord
    ) -> tuple[MetricLifecycleProposalView, bool]: ...

    def decide(
        self, decision: MetricLifecycleDecisionRecord
    ) -> tuple[MetricLifecycleProposalView, bool]: ...

    def get_proposal(
        self, proposal_id: str
    ) -> MetricLifecycleProposalView | None: ...

    def list_proposals(
        self, session_id: str
    ) -> tuple[MetricLifecycleProposalView, ...]: ...

    def list_proposals_page(
        self, session_id: str, *, limit: int, offset: int
    ) -> tuple[tuple[MetricLifecycleProposalView, ...], int]: ...

    def snapshot(
        self, session_id: str, source_window_fingerprint: str
    ) -> MetricLifecycleEvidenceSnapshot: ...


class MetricLifecycleWindowRepository(Protocol):
    def get_latest(self, session_id: str): ...


class MetricLifecycleAccessPolicy(Protocol):
    def selection_is_indexed(
        self,
        provider: Provider,
        *,
        project_ids: frozenset[str],
        session_ids: frozenset[str],
    ) -> bool: ...


class MetricLifecycleIdFactory(Protocol):
    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str: ...


class MetricLifecycleEvidenceError(RuntimeError):
    code = "metric_lifecycle_evidence_failed"


class MetricLifecycleInputError(MetricLifecycleEvidenceError):
    code = "invalid_metric_lifecycle_evidence"


class MetricLifecycleNotFoundError(MetricLifecycleEvidenceError):
    code = "metric_lifecycle_evidence_not_found"


class MetricLifecycleStaleWindowError(MetricLifecycleEvidenceError):
    code = "metric_lifecycle_source_window_stale"


class MetricLifecycleConflictError(MetricLifecycleEvidenceError):
    code = "metric_lifecycle_evidence_conflict"


class MetricLifecyclePersistenceError(MetricLifecycleEvidenceError):
    code = "metric_lifecycle_evidence_persistence_failed"


class MetricLifecycleEvidenceService:
    """Issue and decide typed lifecycle evidence against the latest local run."""

    def __init__(
        self,
        access_policy: MetricLifecycleAccessPolicy,
        window_repository: MetricLifecycleWindowRepository,
        repository: MetricLifecycleEvidenceRepository,
        identifiers: MetricLifecycleIdFactory,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._access_policy = access_policy
        self._window_repository = window_repository
        self._repository = repository
        self._identifiers = identifiers
        self._clock = clock

    def propose(
        self,
        *,
        session_id: str,
        command: MetricLifecycleProposalCommand,
        idempotency_key: str,
    ) -> tuple[MetricLifecycleProposalView, bool]:
        self._validate_request(session_id, idempotency_key)
        self._validate_session(session_id)
        idempotency_digest = self._identifiers.fingerprint(
            "metric-lifecycle-proposal-idempotency-v1",
            (session_id, idempotency_key),
        )
        proposal_id = self._identifiers.fingerprint(
            "metric-lifecycle-proposal-v1",
            (session_id, idempotency_digest),
        )
        try:
            existing = self._repository.get_proposal(proposal_id)
        except Exception:
            raise MetricLifecyclePersistenceError(
                "lifecycle proposal could not be read"
            ) from None
        if existing is not None:
            if self._proposal_matches_command(
                existing.proposal,
                command,
                idempotency_digest=idempotency_digest,
            ):
                return existing, False
            raise MetricLifecycleConflictError(
                "proposal idempotency key conflicts"
            )
        latest = self._latest_authority(session_id)
        if latest.run_id != command.expected_source_run_id:
            raise MetricLifecycleStaleWindowError("source run changed")
        values = self._command_values(command)
        command_fingerprint = self._identifiers.fingerprint(
            "metric-lifecycle-proposal-command-v1",
            (
                session_id,
                latest.run_id,
                latest.input_fingerprint,
                *values,
            ),
        )
        opportunity_id = command.opportunity_id
        if command.proposal_kind is MetricLifecycleProposalKind.OPPORTUNITY:
            opportunity_id = self._identifiers.fingerprint(
                "metric-lifecycle-opportunity-v1", (proposal_id,)
            )
        proposal = MetricLifecycleProposalRecord(
            proposal_id=proposal_id,
            session_id=session_id,
            source_run_id=latest.run_id,
            source_window_fingerprint=latest.input_fingerprint,
            proposal_kind=command.proposal_kind,
            family=command.family,
            opportunity_kind=command.opportunity_kind,
            opportunity_id=opportunity_id,
            link_kind=command.link_kind,
            outcome_kind=command.outcome_kind,
            enumerated_opportunity_ids=command.enumerated_opportunity_ids,
            idempotency_key_digest=idempotency_digest,
            command_fingerprint=command_fingerprint,
            created_at=self._clock(),
        )
        try:
            return self._repository.issue_proposal(proposal)
        except MetricLifecycleConflictError:
            raise
        except Exception:
            raise MetricLifecyclePersistenceError(
                "lifecycle proposal could not be stored"
            ) from None

    def validate_proposal_command(
        self,
        *,
        session_id: str,
        command: MetricLifecycleProposalCommand,
    ) -> tuple[str, str]:
        """Validate an inert proposal against the current source window.

        This read-only seam is used by the local agent-file preview.  It does
        not issue an identifier, persist a row, or grant evidence authority.
        """

        self._validate_session(session_id)
        latest = self._latest_authority(session_id)
        if latest.run_id != command.expected_source_run_id:
            raise MetricLifecycleStaleWindowError("source run changed")
        return latest.run_id, latest.input_fingerprint

    def current_source_window(self, session_id: str) -> tuple[str, str]:
        """Return the current content-free run/window binding for file authors."""

        latest = self._latest_authority(session_id)
        return latest.run_id, latest.input_fingerprint

    def decide(
        self,
        *,
        session_id: str,
        proposal_id: str,
        command: MetricLifecycleDecisionCommand,
        idempotency_key: str,
    ) -> tuple[MetricLifecycleProposalView, bool]:
        self._validate_request(session_id, idempotency_key)
        self._validate_session(session_id)
        try:
            _pseudonym(proposal_id)
        except ValueError:
            raise MetricLifecycleInputError(
                "proposal identifier is invalid"
            ) from None
        try:
            proposal = self._repository.get_proposal(proposal_id)
        except Exception:
            raise MetricLifecyclePersistenceError(
                "lifecycle proposal could not be read"
            ) from None
        if proposal is None or proposal.proposal.session_id != session_id:
            raise MetricLifecycleNotFoundError("lifecycle proposal does not exist")
        if (
            command.expected_proposal_revision
            != proposal.proposal.proposal_revision
            or command.expected_source_run_id != proposal.proposal.source_run_id
        ):
            raise MetricLifecycleConflictError("proposal authority changed")
        idempotency_digest = self._identifiers.fingerprint(
            "metric-lifecycle-decision-idempotency-v1",
            (session_id, idempotency_key),
        )
        command_fingerprint = self._identifiers.fingerprint(
            "metric-lifecycle-decision-command-v1",
            (
                proposal_id,
                str(command.expected_proposal_revision),
                command.decision.value,
                command.confirmation,
            ),
        )
        decision_id = self._identifiers.fingerprint(
            "metric-lifecycle-decision-v1", (proposal_id, idempotency_digest)
        )
        if proposal.decision is not None:
            if (
                proposal.decision.decision_id == decision_id
                and proposal.decision.idempotency_key_digest
                == idempotency_digest
                and proposal.decision.command_fingerprint
                == command_fingerprint
                and proposal.decision.decision is command.decision
            ):
                return proposal, False
            raise MetricLifecycleConflictError(
                "lifecycle proposal already has another decision"
            )
        latest = self._latest_authority(session_id)
        if latest.input_fingerprint != proposal.proposal.source_window_fingerprint:
            raise MetricLifecycleStaleWindowError("source window changed")
        decision = MetricLifecycleDecisionRecord(
            decision_id=decision_id,
            proposal_id=proposal_id,
            session_id=session_id,
            expected_proposal_revision=command.expected_proposal_revision,
            decision=command.decision,
            idempotency_key_digest=idempotency_digest,
            command_fingerprint=command_fingerprint,
            decided_at=self._clock(),
        )
        try:
            return self._repository.decide(decision)
        except MetricLifecycleConflictError:
            raise
        except Exception:
            raise MetricLifecyclePersistenceError(
                "lifecycle decision could not be stored"
            ) from None

    def list(self, session_id: str) -> tuple[MetricLifecycleProposalView, ...]:
        self._validate_session(session_id)
        try:
            return self._repository.list_proposals(session_id)
        except Exception:
            raise MetricLifecyclePersistenceError(
                "lifecycle proposals could not be read"
            ) from None

    def list_page(
        self, session_id: str, *, limit: int, offset: int
    ) -> tuple[tuple[MetricLifecycleProposalView, ...], int]:
        self._validate_session(session_id)
        if not 1 <= limit <= 200 or not 0 <= offset <= 1_000_000:
            raise MetricLifecycleInputError("lifecycle proposal page is invalid")
        try:
            return self._repository.list_proposals_page(
                session_id, limit=limit, offset=offset
            )
        except Exception:
            raise MetricLifecyclePersistenceError(
                "lifecycle proposal page could not be read"
            ) from None

    def snapshot_for_window(
        self, session_id: str, source_window_fingerprint: str
    ) -> MetricLifecycleEvidenceSnapshot:
        try:
            _pseudonym(session_id)
            _pseudonym(source_window_fingerprint)
        except ValueError:
            raise MetricLifecycleInputError(
                "lifecycle evidence window is invalid"
            ) from None
        try:
            return self._repository.snapshot(session_id, source_window_fingerprint)
        except Exception:
            raise MetricLifecyclePersistenceError(
                "lifecycle evidence could not be read"
            ) from None

    def _latest_authority(self, session_id: str):
        self._validate_session(session_id)
        try:
            latest = self._window_repository.get_latest(session_id)
        except Exception:
            raise MetricLifecyclePersistenceError(
                "source-window authority could not be read"
            ) from None
        if latest is None:
            raise MetricLifecycleNotFoundError("a source model run is required")
        return latest

    def _validate_session(self, session_id: str) -> None:
        try:
            _pseudonym(session_id)
            indexed = self._access_policy.selection_is_indexed(
                Provider.CODEX,
                project_ids=frozenset(),
                session_ids=frozenset((session_id,)),
            )
        except Exception:
            raise MetricLifecycleInputError("session selection is invalid") from None
        if not indexed:
            raise MetricLifecycleNotFoundError("session is not indexed")

    def _validate_request(self, session_id: str, idempotency_key: str) -> None:
        try:
            _pseudonym(session_id)
            key_is_valid = (
                SAFE_VERSION_PATTERN.fullmatch(idempotency_key) is not None
                and len(idempotency_key) >= 16
            )
        except (TypeError, ValueError):
            key_is_valid = False
        if not key_is_valid:
            raise MetricLifecycleInputError(
                "idempotency key must be a content-free identifier"
            )

    @staticmethod
    def _command_values(command: MetricLifecycleProposalCommand) -> tuple[str, ...]:
        return (
            command.proposal_kind.value,
            command.family.value,
            command.opportunity_kind.value,
            command.opportunity_id or "none",
            command.link_kind.value if command.link_kind is not None else "none",
            command.outcome_kind.value if command.outcome_kind is not None else "none",
            *command.enumerated_opportunity_ids,
        )

    def _proposal_matches_command(
        self,
        proposal: MetricLifecycleProposalRecord,
        command: MetricLifecycleProposalCommand,
        *,
        idempotency_digest: str,
    ) -> bool:
        expected_opportunity_id = (
            proposal.opportunity_id
            if command.proposal_kind is MetricLifecycleProposalKind.OPPORTUNITY
            else command.opportunity_id
        )
        expected_command_fingerprint = self._identifiers.fingerprint(
            "metric-lifecycle-proposal-command-v1",
            (
                proposal.session_id,
                command.expected_source_run_id,
                proposal.source_window_fingerprint,
                *self._command_values(command),
            ),
        )
        return (
            proposal.proposal_kind is command.proposal_kind
            and proposal.family is command.family
            and proposal.opportunity_kind is command.opportunity_kind
            and proposal.opportunity_id == expected_opportunity_id
            and proposal.link_kind is command.link_kind
            and proposal.outcome_kind is command.outcome_kind
            and proposal.enumerated_opportunity_ids
            == command.enumerated_opportunity_ids
            and proposal.idempotency_key_digest == idempotency_digest
            and proposal.command_fingerprint == expected_command_fingerprint
        )


__all__ = [
    "FAMILY_LINK_KIND",
    "FAMILY_OPPORTUNITY_KIND",
    "FAMILY_OUTCOME_KINDS",
    "MAX_LIFECYCLE_ENUMERATION_SIZE",
    "MET_OUTCOME_KINDS",
    "METRIC_LIFECYCLE_EVIDENCE_POLICY_VERSION",
    "METRIC_LIFECYCLE_EVIDENCE_SCHEMA_VERSION",
    "METRIC_LIFECYCLE_PROPOSAL_REVISION",
    "METRIC_LIFECYCLE_DECISION_CONFIRMATION",
    "ConfirmedMetricLifecycleOpportunity",
    "ConfirmedMetricLifecycleOutcome",
    "MetricLifecycleConflictError",
    "MetricLifecycleDecisionCommand",
    "MetricLifecycleDecisionKind",
    "MetricLifecycleDecisionRecord",
    "MetricLifecycleEvidenceError",
    "MetricLifecycleEvidenceRepository",
    "MetricLifecycleEvidenceService",
    "MetricLifecycleEvidenceSnapshot",
    "MetricLifecycleFamily",
    "MetricLifecycleFamilyEvidence",
    "MetricLifecycleInputError",
    "MetricLifecycleLinkKind",
    "MetricLifecycleNotFoundError",
    "MetricLifecycleOpportunityKind",
    "MetricLifecycleOutcomeKind",
    "MetricLifecyclePersistenceError",
    "MetricLifecycleProposalCommand",
    "MetricLifecycleProposalKind",
    "MetricLifecycleProposalRecord",
    "MetricLifecycleProposalStatus",
    "MetricLifecycleProposalView",
    "MetricLifecycleStaleWindowError",
]
