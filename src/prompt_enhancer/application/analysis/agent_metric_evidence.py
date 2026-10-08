"""Strict local-file boundary for agent-proposed metric lifecycle evidence.

The file is content-free and cannot carry a score, transcript, path, tool
output, or objective-evidence claim.  Parsing and preview are read-only.  An
import creates only an inert lifecycle proposal; the existing authenticated
local-user decision route remains the sole authority that can confirm it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
from typing import Any, Literal, Protocol, TypeAlias

from pydantic import field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, StrictModel
from .metric_contract_v2 import (
    METRIC_CONTRACT_REGISTRY_VERSION_V2,
    METRIC_CONTRACT_VERSION_V2,
    metric_contract_v2,
    metric_contract_v2_set_fingerprint,
)
from .metric_lifecycle_evidence import (
    FAMILY_LINK_KIND,
    FAMILY_OPPORTUNITY_KIND,
    FAMILY_OUTCOME_KINDS,
    MetricLifecycleFamily,
    MetricLifecycleLinkKind,
    MetricLifecycleOpportunityKind,
    MetricLifecycleOutcomeKind,
    MetricLifecycleNotFoundError,
    MetricLifecyclePersistenceError,
    MetricLifecycleProposalCommand,
    MetricLifecycleProposalView,
)
from .metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_4,
    METRIC_PROJECTION_V2_VERSION_5,
)


AGENT_METRIC_EVIDENCE_FILE_VERSION = "agent-metric-evidence-file-v1"
AGENT_METRIC_EVIDENCE_FILE_VERSION_2 = "agent-metric-evidence-file-v2"
SUPPORTED_AGENT_METRIC_EVIDENCE_FILE_VERSIONS = (
    AGENT_METRIC_EVIDENCE_FILE_VERSION,
    AGENT_METRIC_EVIDENCE_FILE_VERSION_2,
)
AGENT_METRIC_EVIDENCE_IMPORT_CONFIRMATION = (
    "import_agent_metric_evidence_as_unconfirmed_proposal"
)
MAX_AGENT_METRIC_EVIDENCE_BYTES = 64 * 1024
MAX_AGENT_METRIC_EVIDENCE_DEPTH = 8
MAX_AGENT_METRIC_EVIDENCE_ITEMS = 1_100
MAX_AGENT_METRIC_EVIDENCE_LIFETIME = timedelta(hours=24)


class AgentMetricEvidenceFileError(ValueError):
    code = "invalid_agent_metric_evidence_file"


class AgentMetricEvidenceDefinitionsOutOfDateError(AgentMetricEvidenceFileError):
    """The sealed producer identity is newer than this file definition."""

    code = "agent_metric_evidence_definitions_out_of_date"


def _safe_code(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("producer provenance must be a content-free identifier")
    return value


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("identifier must be a SHA-256-shaped local pseudonym")
    return value


class AgentMetricEvidenceProducer(StrictModel):
    kind: Literal["local_coding_agent"] = "local_coding_agent"
    producer_id: str
    producer_version: str
    model_id: str
    authority: Literal["untrusted_provenance_claim"] = "untrusted_provenance_claim"

    _safe = field_validator(
        "producer_id", "producer_version", "model_id"
    )(_safe_code)


class AgentMetricEvidenceFile(StrictModel):
    schema_version: Literal[AGENT_METRIC_EVIDENCE_FILE_VERSION] = (
        AGENT_METRIC_EVIDENCE_FILE_VERSION
    )
    session_id: str
    expected_source_run_id: str
    registry_version: Literal[METRIC_CONTRACT_REGISTRY_VERSION_V2] = (
        METRIC_CONTRACT_REGISTRY_VERSION_V2
    )
    contract_set_fingerprint: str
    projection_version: Literal[METRIC_PROJECTION_V2_VERSION_4] = (
        METRIC_PROJECTION_V2_VERSION_4
    )
    metric_key: MetricLifecycleFamily
    contract_version: Literal[METRIC_CONTRACT_VERSION_V2] = METRIC_CONTRACT_VERSION_V2
    metric_contract_fingerprint: str
    nonce: str
    expires_at: datetime
    producer: AgentMetricEvidenceProducer
    contains_scores: Literal[False] = False
    contains_objective_receipt_claims: Literal[False] = False
    command: MetricLifecycleProposalCommand

    _ids = field_validator("session_id", "expected_source_run_id", "nonce")(
        _pseudonym
    )
    _digests = field_validator(
        "contract_set_fingerprint", "metric_contract_fingerprint"
    )(_pseudonym)

    @field_validator("expires_at")
    @classmethod
    def utc_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("agent evidence expiry must be UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bind_contract_and_command(self) -> "AgentMetricEvidenceFile":
        contract = metric_contract_v2(self.metric_key.value)
        if self.contract_set_fingerprint != metric_contract_v2_set_fingerprint():
            raise ValueError("contract-set fingerprint does not match this application")
        if self.metric_contract_fingerprint != contract.fingerprint:
            raise ValueError("metric contract fingerprint does not match this metric")
        if self.command.family is not self.metric_key:
            raise ValueError("command family does not match the bound metric")
        if self.command.expected_source_run_id != self.expected_source_run_id:
            raise ValueError("command run does not match the bound source run")
        return self


class AgentMetricEvidenceFileV2(StrictModel):
    """Append-only r5 file bound to one exact sealed source authority.

    The source-window fingerprint is deliberately part of the canonical bytes
    covered by the preview digest.  Unlike v1, an r5 file can therefore never
    be replayed against a different profile-bound source window even when a
    caller supplies the same session and command family.
    """

    schema_version: Literal[AGENT_METRIC_EVIDENCE_FILE_VERSION_2] = (
        AGENT_METRIC_EVIDENCE_FILE_VERSION_2
    )
    session_id: str
    expected_source_run_id: str
    source_window_fingerprint: str
    registry_version: Literal[METRIC_CONTRACT_REGISTRY_VERSION_V2] = (
        METRIC_CONTRACT_REGISTRY_VERSION_V2
    )
    contract_set_fingerprint: str
    projection_version: Literal[METRIC_PROJECTION_V2_VERSION_5] = (
        METRIC_PROJECTION_V2_VERSION_5
    )
    metric_key: MetricLifecycleFamily
    contract_version: Literal[METRIC_CONTRACT_VERSION_V2] = METRIC_CONTRACT_VERSION_V2
    metric_contract_fingerprint: str
    nonce: str
    expires_at: datetime
    producer: AgentMetricEvidenceProducer
    contains_scores: Literal[False] = False
    contains_prose: Literal[False] = False
    contains_objective_receipt_claims: Literal[False] = False
    command: MetricLifecycleProposalCommand

    _ids = field_validator(
        "session_id",
        "expected_source_run_id",
        "source_window_fingerprint",
        "nonce",
    )(_pseudonym)
    _digests = field_validator(
        "contract_set_fingerprint", "metric_contract_fingerprint"
    )(_pseudonym)

    @field_validator("expires_at")
    @classmethod
    def utc_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("agent evidence expiry must be UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def bind_contract_and_command(self) -> "AgentMetricEvidenceFileV2":
        contract = metric_contract_v2(self.metric_key.value)
        if self.contract_set_fingerprint != metric_contract_v2_set_fingerprint():
            raise ValueError("contract-set fingerprint does not match this application")
        if self.metric_contract_fingerprint != contract.fingerprint:
            raise ValueError("metric contract fingerprint does not match this metric")
        if self.command.family is not self.metric_key:
            raise ValueError("command family does not match the bound metric")
        if self.command.expected_source_run_id != self.expected_source_run_id:
            raise ValueError("command run does not match the bound source run")
        return self


ParsedAgentMetricEvidenceFile: TypeAlias = (
    AgentMetricEvidenceFile | AgentMetricEvidenceFileV2
)


class AgentMetricEvidencePreview(StrictModel):
    schema_version: Literal[
        AGENT_METRIC_EVIDENCE_FILE_VERSION,
        AGENT_METRIC_EVIDENCE_FILE_VERSION_2,
    ]
    payload_sha256: str
    session_id: str
    expected_source_run_id: str
    source_window_fingerprint: str
    metric_key: MetricLifecycleFamily
    proposal_kind: str
    expires_at: datetime
    producer: AgentMetricEvidenceProducer
    creates_unconfirmed_proposal_only: Literal[True] = True
    requires_authenticated_local_user_confirmation: Literal[True] = True
    can_set_numeric_metric: Literal[False] = False
    objective_receipt_claims_accepted: Literal[False] = False
    raw_payload_persisted: Literal[False] = False

    _digests = field_validator(
        "payload_sha256", "session_id", "expected_source_run_id",
        "source_window_fingerprint",
    )(_pseudonym)


class AgentMetricEvidenceMetricContract(StrictModel):
    metric_key: MetricLifecycleFamily
    contract_fingerprint: str
    opportunity_kind: MetricLifecycleOpportunityKind
    link_kind: MetricLifecycleLinkKind
    outcome_kinds: tuple[MetricLifecycleOutcomeKind, ...]

    _fingerprint = field_validator("contract_fingerprint")(_pseudonym)


class AgentMetricEvidenceFileContract(StrictModel):
    schema_version: Literal[AGENT_METRIC_EVIDENCE_FILE_VERSION] = (
        AGENT_METRIC_EVIDENCE_FILE_VERSION
    )
    media_type: Literal[
        "application/vnd.prompt-enhancer.agent-metric-evidence+json"
    ] = "application/vnd.prompt-enhancer.agent-metric-evidence+json"
    max_payload_bytes: Literal[MAX_AGENT_METRIC_EVIDENCE_BYTES] = (
        MAX_AGENT_METRIC_EVIDENCE_BYTES
    )
    max_lifetime_seconds: Literal[86400] = 86400
    session_id: str
    expected_source_run_id: str
    source_window_fingerprint: str
    registry_version: Literal[METRIC_CONTRACT_REGISTRY_VERSION_V2] = (
        METRIC_CONTRACT_REGISTRY_VERSION_V2
    )
    contract_set_fingerprint: str
    projection_version: Literal[METRIC_PROJECTION_V2_VERSION_4] = (
        METRIC_PROJECTION_V2_VERSION_4
    )
    contract_version: Literal[METRIC_CONTRACT_VERSION_V2] = METRIC_CONTRACT_VERSION_V2
    metrics: tuple[AgentMetricEvidenceMetricContract, ...]
    canonical_json_required: Literal[True] = True
    explicit_local_confirmation_required: Literal[True] = True
    scores_allowed: Literal[False] = False
    prose_allowed: Literal[False] = False
    objective_receipt_claims_allowed: Literal[False] = False

    _ids = field_validator(
        "session_id", "expected_source_run_id", "source_window_fingerprint",
        "contract_set_fingerprint",
    )(_pseudonym)

    @model_validator(mode="after")
    def exact_metric_catalog(self) -> "AgentMetricEvidenceFileContract":
        if tuple(item.metric_key for item in self.metrics) != tuple(MetricLifecycleFamily):
            raise ValueError("agent evidence contract must list all lifecycle families")
        return self


class AgentMetricEvidenceFileContractV2(StrictModel):
    schema_version: Literal[AGENT_METRIC_EVIDENCE_FILE_VERSION_2] = (
        AGENT_METRIC_EVIDENCE_FILE_VERSION_2
    )
    media_type: Literal[
        "application/vnd.prompt-enhancer.agent-metric-evidence+json"
    ] = "application/vnd.prompt-enhancer.agent-metric-evidence+json"
    max_payload_bytes: Literal[MAX_AGENT_METRIC_EVIDENCE_BYTES] = (
        MAX_AGENT_METRIC_EVIDENCE_BYTES
    )
    max_lifetime_seconds: Literal[86400] = 86400
    session_id: str
    expected_source_run_id: str
    source_window_fingerprint: str
    registry_version: Literal[METRIC_CONTRACT_REGISTRY_VERSION_V2] = (
        METRIC_CONTRACT_REGISTRY_VERSION_V2
    )
    contract_set_fingerprint: str
    projection_version: Literal[METRIC_PROJECTION_V2_VERSION_5] = (
        METRIC_PROJECTION_V2_VERSION_5
    )
    contract_version: Literal[METRIC_CONTRACT_VERSION_V2] = METRIC_CONTRACT_VERSION_V2
    metrics: tuple[AgentMetricEvidenceMetricContract, ...]
    canonical_json_required: Literal[True] = True
    explicit_local_confirmation_required: Literal[True] = True
    scores_allowed: Literal[False] = False
    prose_allowed: Literal[False] = False
    objective_receipt_claims_allowed: Literal[False] = False

    _ids = field_validator(
        "session_id",
        "expected_source_run_id",
        "source_window_fingerprint",
        "contract_set_fingerprint",
    )(_pseudonym)

    @model_validator(mode="after")
    def exact_metric_catalog(self) -> "AgentMetricEvidenceFileContractV2":
        if tuple(item.metric_key for item in self.metrics) != tuple(MetricLifecycleFamily):
            raise ValueError("agent evidence contract must list all lifecycle families")
        return self


AgentMetricEvidenceAnyFileContract: TypeAlias = (
    AgentMetricEvidenceFileContract | AgentMetricEvidenceFileContractV2
)


class AgentMetricEvidenceImportResult(StrictModel):
    payload_sha256: str
    proposal: MetricLifecycleProposalView
    applied: bool
    producer_claim_persisted: Literal[False] = False
    raw_payload_persisted: Literal[False] = False
    requires_authenticated_local_user_confirmation: Literal[True] = True

    _digest = field_validator("payload_sha256")(_pseudonym)


class AgentMetricLifecycleCommand(Protocol):
    def current_source_window(self, session_id: str) -> tuple[str, str]: ...

    def validate_proposal_command(
        self, *, session_id: str, command: MetricLifecycleProposalCommand
    ) -> tuple[str, str]: ...

    def propose(
        self,
        *,
        session_id: str,
        command: MetricLifecycleProposalCommand,
        idempotency_key: str,
    ) -> tuple[MetricLifecycleProposalView, bool]: ...


class AgentMetricEvidenceSourceContract(StrictModel):
    """Exact content-free identity of the sealed metric source publication."""

    session_id: str
    expected_source_run_id: str
    source_window_fingerprint: str
    registry_version: str
    contract_set_fingerprint: str
    projection_version: str

    _ids = field_validator(
        "session_id",
        "expected_source_run_id",
        "source_window_fingerprint",
        "contract_set_fingerprint",
    )(_pseudonym)
    _versions = field_validator("registry_version", "projection_version")(_safe_code)


class AgentMetricEvidenceSourceAuthority(Protocol):
    def current_source_contract(
        self, session_id: str
    ) -> AgentMetricEvidenceSourceContract: ...


class AgentMetricEvidenceSealedRunRepository(Protocol):
    def get_latest(self, session_id: str): ...


class SealedRunAgentMetricEvidenceSource:
    """Adapt the verified model-ensemble repository to the file boundary."""

    def __init__(self, repository: AgentMetricEvidenceSealedRunRepository) -> None:
        self._repository = repository

    def current_source_contract(
        self, session_id: str
    ) -> AgentMetricEvidenceSourceContract:
        try:
            latest = self._repository.get_latest(session_id)
        except Exception:
            raise MetricLifecyclePersistenceError(
                "sealed source publication could not be read"
            ) from None
        if latest is None:
            raise MetricLifecycleNotFoundError(
                "a sealed source metric publication is required"
            )
        publication = latest.receipt.metric_publication_v2
        if publication is None:
            raise MetricLifecycleNotFoundError(
                "a sealed source metric publication is required"
            )
        return AgentMetricEvidenceSourceContract(
            session_id=latest.session_id,
            expected_source_run_id=latest.run_id,
            source_window_fingerprint=latest.input_fingerprint,
            registry_version=publication.registry_version,
            contract_set_fingerprint=publication.contract_set_fingerprint,
            projection_version=publication.projection_version,
        )


class _LegacyR4AgentMetricEvidenceSource:
    """Compatibility authority for applications not yet wired to sealed runs."""

    def __init__(self, lifecycle: AgentMetricLifecycleCommand) -> None:
        self._lifecycle = lifecycle

    def current_source_contract(
        self, session_id: str
    ) -> AgentMetricEvidenceSourceContract:
        run_id, window_fingerprint = self._lifecycle.current_source_window(session_id)
        return AgentMetricEvidenceSourceContract(
            session_id=session_id,
            expected_source_run_id=run_id,
            source_window_fingerprint=window_fingerprint,
            registry_version=METRIC_CONTRACT_REGISTRY_VERSION_V2,
            contract_set_fingerprint=metric_contract_v2_set_fingerprint(),
            projection_version=METRIC_PROJECTION_V2_VERSION_4,
        )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _validate_json_budget(value: object, *, depth: int = 0) -> int:
    if depth > MAX_AGENT_METRIC_EVIDENCE_DEPTH:
        raise ValueError("agent evidence nesting exceeds its bound")
    if isinstance(value, float):
        raise ValueError("agent evidence does not accept floating-point values")
    if isinstance(value, dict):
        return 1 + sum(
            _validate_json_budget(item, depth=depth + 1)
            for item in value.values()
        )
    if isinstance(value, list):
        return 1 + sum(
            _validate_json_budget(item, depth=depth + 1) for item in value
        )
    if value is None or isinstance(value, (str, int, bool)):
        return 1
    raise ValueError("agent evidence contains an unsupported JSON value")


def parse_agent_metric_evidence_file(
    payload: bytes,
    *,
    now: datetime | None = None,
) -> tuple[ParsedAgentMetricEvidenceFile, str]:
    if not payload or len(payload) > MAX_AGENT_METRIC_EVIDENCE_BYTES:
        raise AgentMetricEvidenceFileError("agent evidence file size is invalid")
    if payload.startswith(b"\xef\xbb\xbf") or b"\x00" in payload:
        raise AgentMetricEvidenceFileError("agent evidence encoding is invalid")
    try:
        text = payload.decode("utf-8", errors="strict")
        data = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
        if not isinstance(data, dict):
            raise ValueError("agent evidence root must be an object")
        if _validate_json_budget(data) > MAX_AGENT_METRIC_EVIDENCE_ITEMS:
            raise ValueError("agent evidence item count exceeds its bound")
        canonical = json.dumps(
            data, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")
        if not hmac.compare_digest(payload, canonical):
            raise ValueError("agent evidence JSON must use the canonical encoding")
        schema_version = data.get("schema_version")
        projection_version = data.get("projection_version")
        if (
            isinstance(projection_version, str)
            and SAFE_VERSION_PATTERN.fullmatch(projection_version) is not None
            and projection_version
            not in {
                METRIC_PROJECTION_V2_VERSION_4,
                METRIC_PROJECTION_V2_VERSION_5,
            }
        ):
            raise AgentMetricEvidenceDefinitionsOutOfDateError(
                "agent evidence projection definitions are out of date"
            )
        if schema_version == AGENT_METRIC_EVIDENCE_FILE_VERSION:
            parsed = AgentMetricEvidenceFile.model_validate(data)
        elif schema_version == AGENT_METRIC_EVIDENCE_FILE_VERSION_2:
            parsed = AgentMetricEvidenceFileV2.model_validate(data)
        else:
            raise ValueError("agent evidence schema is unsupported")
    except AgentMetricEvidenceDefinitionsOutOfDateError:
        raise
    except Exception as error:
        raise AgentMetricEvidenceFileError(
            "agent evidence file failed strict validation"
        ) from error
    checked_at = datetime.now(UTC) if now is None else now
    if checked_at.tzinfo is None or checked_at.utcoffset() != timedelta(0):
        raise AgentMetricEvidenceFileError("agent evidence clock must be UTC")
    remaining = parsed.expires_at - checked_at
    if remaining <= timedelta(0) or remaining > MAX_AGENT_METRIC_EVIDENCE_LIFETIME:
        raise AgentMetricEvidenceFileError("agent evidence expiry is outside policy")
    return parsed, hashlib.sha256(payload).hexdigest()


class AgentMetricEvidenceService:
    def __init__(
        self,
        lifecycle: AgentMetricLifecycleCommand,
        source_authority: AgentMetricEvidenceSourceAuthority | None = None,
    ) -> None:
        self._lifecycle = lifecycle
        self._source_authority = (
            _LegacyR4AgentMetricEvidenceSource(lifecycle)
            if source_authority is None
            else source_authority
        )

    def contract(self, session_id: str) -> AgentMetricEvidenceAnyFileContract:
        source = self._current_source_contract(session_id)
        contract_type = self._contract_type(source.projection_version)
        return contract_type(
            session_id=session_id,
            expected_source_run_id=source.expected_source_run_id,
            source_window_fingerprint=source.source_window_fingerprint,
            contract_set_fingerprint=metric_contract_v2_set_fingerprint(),
            metrics=tuple(
                AgentMetricEvidenceMetricContract(
                    metric_key=family,
                    contract_fingerprint=metric_contract_v2(family.value).fingerprint,
                    opportunity_kind=FAMILY_OPPORTUNITY_KIND[family],
                    link_kind=FAMILY_LINK_KIND[family],
                    outcome_kinds=tuple(
                        sorted(FAMILY_OUTCOME_KINDS[family], key=lambda item: item.value)
                    ),
                )
                for family in MetricLifecycleFamily
            ),
        )

    def preview(
        self, *, session_id: str, payload: bytes, now: datetime | None = None
    ) -> AgentMetricEvidencePreview:
        parsed, digest = parse_agent_metric_evidence_file(payload, now=now)
        if not hmac.compare_digest(parsed.session_id, session_id):
            raise AgentMetricEvidenceFileError("agent evidence session is mismatched")
        source = self._current_source_contract(session_id)
        run_id, window_fingerprint = self._lifecycle.validate_proposal_command(
            session_id=session_id, command=parsed.command
        )
        self._validate_file_binding(parsed, source)
        if (
            not hmac.compare_digest(run_id, source.expected_source_run_id)
            or not hmac.compare_digest(
                window_fingerprint, source.source_window_fingerprint
            )
        ):
            raise AgentMetricEvidenceFileError(
                "agent evidence authority sources disagree"
            )
        return AgentMetricEvidencePreview(
            schema_version=parsed.schema_version,
            payload_sha256=digest,
            session_id=session_id,
            expected_source_run_id=parsed.expected_source_run_id,
            source_window_fingerprint=window_fingerprint,
            metric_key=parsed.metric_key,
            proposal_kind=parsed.command.proposal_kind.value,
            expires_at=parsed.expires_at,
            producer=parsed.producer,
        )

    def import_file(
        self,
        *,
        session_id: str,
        payload: bytes,
        expected_payload_sha256: str,
        confirmation: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> AgentMetricEvidenceImportResult:
        if confirmation != AGENT_METRIC_EVIDENCE_IMPORT_CONFIRMATION:
            raise AgentMetricEvidenceFileError("agent evidence confirmation is invalid")
        parsed, digest = parse_agent_metric_evidence_file(payload, now=now)
        if (
            PSEUDONYM_PATTERN.fullmatch(expected_payload_sha256) is None
            or not hmac.compare_digest(digest, expected_payload_sha256)
            or not hmac.compare_digest(parsed.session_id, session_id)
        ):
            raise AgentMetricEvidenceFileError("agent evidence preview binding changed")
        source = self._current_source_contract(session_id)
        run_id, window_fingerprint = self._lifecycle.validate_proposal_command(
            session_id=session_id, command=parsed.command
        )
        self._validate_file_binding(parsed, source)
        if (
            not hmac.compare_digest(run_id, source.expected_source_run_id)
            or not hmac.compare_digest(
                window_fingerprint, source.source_window_fingerprint
            )
        ):
            raise AgentMetricEvidenceFileError(
                "agent evidence authority sources disagree"
            )
        proposal, applied = self._lifecycle.propose(
            session_id=session_id,
            command=parsed.command,
            idempotency_key=idempotency_key,
        )
        return AgentMetricEvidenceImportResult(
            payload_sha256=digest,
            proposal=proposal,
            applied=applied,
        )

    def _current_source_contract(
        self, session_id: str
    ) -> AgentMetricEvidenceSourceContract:
        source = self._source_authority.current_source_contract(session_id)
        if not hmac.compare_digest(source.session_id, session_id):
            raise AgentMetricEvidenceFileError(
                "sealed source publication belongs to another session"
            )
        if (
            source.registry_version != METRIC_CONTRACT_REGISTRY_VERSION_V2
            or not hmac.compare_digest(
                source.contract_set_fingerprint,
                metric_contract_v2_set_fingerprint(),
            )
        ):
            raise AgentMetricEvidenceDefinitionsOutOfDateError(
                "sealed metric contract definitions are out of date"
            )
        self._contract_type(source.projection_version)
        return source

    @staticmethod
    def _contract_type(projection_version: str):
        if projection_version == METRIC_PROJECTION_V2_VERSION_4:
            return AgentMetricEvidenceFileContract
        if projection_version == METRIC_PROJECTION_V2_VERSION_5:
            return AgentMetricEvidenceFileContractV2
        raise AgentMetricEvidenceDefinitionsOutOfDateError(
            "sealed metric projection definitions are out of date"
        )

    @staticmethod
    def _validate_file_binding(
        parsed: ParsedAgentMetricEvidenceFile,
        source: AgentMetricEvidenceSourceContract,
    ) -> None:
        expected_schema = (
            AGENT_METRIC_EVIDENCE_FILE_VERSION
            if source.projection_version == METRIC_PROJECTION_V2_VERSION_4
            else AGENT_METRIC_EVIDENCE_FILE_VERSION_2
        )
        file_window = (
            source.source_window_fingerprint
            if isinstance(parsed, AgentMetricEvidenceFile)
            else parsed.source_window_fingerprint
        )
        if (
            parsed.schema_version != expected_schema
            or parsed.projection_version != source.projection_version
            or parsed.registry_version != source.registry_version
            or not hmac.compare_digest(
                parsed.contract_set_fingerprint, source.contract_set_fingerprint
            )
            or not hmac.compare_digest(
                parsed.expected_source_run_id, source.expected_source_run_id
            )
            or not hmac.compare_digest(
                file_window, source.source_window_fingerprint
            )
        ):
            raise AgentMetricEvidenceFileError(
                "agent evidence file is bound to another sealed source"
            )


__all__ = (
    "AGENT_METRIC_EVIDENCE_FILE_VERSION",
    "AGENT_METRIC_EVIDENCE_FILE_VERSION_2",
    "AGENT_METRIC_EVIDENCE_IMPORT_CONFIRMATION",
    "MAX_AGENT_METRIC_EVIDENCE_BYTES",
    "SUPPORTED_AGENT_METRIC_EVIDENCE_FILE_VERSIONS",
    "AgentMetricEvidenceAnyFileContract",
    "AgentMetricEvidenceDefinitionsOutOfDateError",
    "AgentMetricEvidenceFile",
    "AgentMetricEvidenceFileV2",
    "AgentMetricEvidenceFileError",
    "AgentMetricEvidenceFileContract",
    "AgentMetricEvidenceFileContractV2",
    "AgentMetricEvidenceMetricContract",
    "AgentMetricEvidenceImportResult",
    "AgentMetricEvidencePreview",
    "AgentMetricEvidenceProducer",
    "AgentMetricEvidenceService",
    "AgentMetricEvidenceSourceAuthority",
    "AgentMetricEvidenceSourceContract",
    "ParsedAgentMetricEvidenceFile",
    "SealedRunAgentMetricEvidenceSource",
    "parse_agent_metric_evidence_file",
)
