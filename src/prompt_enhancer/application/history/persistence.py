"""Application contracts for prospective temporal-history persistence.

These models describe repository return values and one deliberately synthetic
test request.  They do not implement storage and they do not make public model
construction a repository capability.  In particular, a
``RepositoryPreparedTemporalScopeV1`` is authoritative only when returned by a
``TemporalHistoryPersistenceRepositoryV1`` implementation after it has checked
the stored automation grant and the complete root/selection graph.

The first persistence slice is intentionally narrower than the general history
contracts: only an automation-owned selection can be prepared, only synthetic
provider input can exercise completion, and even a repository-sealed graph is
not source-authoritative or eligible for product history, comparison,
snapshots, activation, export, or sharing.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
import hashlib
import json
import re
from typing import Annotated, Any, Literal, Protocol

from pydantic import Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, Provider
from ..automation.contracts import AUTOMATION_GRANT_CONTRACT_VERSION
from .contracts import (
    AnalysisInputReceiptV2,
    MAX_OBSERVATIONS,
    PersistenceRevalidatedModel,
    ProjectMetricSelectionAuthorityKind,
    ProjectMetricSelectionRevisionV2,
    ProjectMetricSelectionSource,
    RepositoryTemporalBatchSealDraft,
    TemporalHistoryRootReceipt,
)


REPOSITORY_PREPARED_TEMPORAL_SCOPE_V1_VERSION = (
    "repository-prepared-temporal-scope-v1"
)
SYNTHETIC_TEMPORAL_COMPLETION_REQUEST_V1_VERSION = (
    "synthetic-temporal-completion-request-v1"
)
REPOSITORY_SEALED_TEMPORAL_BATCH_V1_VERSION = (
    "repository-sealed-temporal-batch-v1"
)
REPOSITORY_TEMPORAL_AUTHORITY_SCOPE_V1 = "graph-selection-only-v1"
REPOSITORY_TEMPORAL_TIME_BASIS_V1 = "repository-utc-clock-v1"
MAX_REPOSITORY_GRAPH_FINGERPRINTS = 7 + MAX_OBSERVATIONS

_SAFE_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_MAX_ORDINAL = 9_007_199_254_740_991
PositiveStrictInt = Annotated[int, Field(strict=True, ge=1, le=_MAX_ORDINAL)]


def _digest(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase SHA-256 identifier")
    return value


def _safe_version(value: str) -> str:
    if (
        _SAFE_VERSION_PATTERN.fullmatch(value) is None
        or ".." in value
        or any(character in value for character in ("/", "\\", ":"))
    ):
        raise ValueError("version must be a path-free, URI-free content code")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("repository timestamps must be canonical UTC")
    return value


def _canonical_digest(value: PersistenceRevalidatedModel) -> str:
    payload = json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _require_unique_roles(**roles: str | None) -> None:
    """Reject cross-role identity aliasing while allowing explicit graph bindings.

    Callers pass each semantic role exactly once. Repeated references such as an
    input's root id, a batch's run id, or an observation's revision id are
    intentional equality bindings and therefore are not separate entries here.
    """

    populated = {name: value for name, value in roles.items() if value is not None}
    inverse: dict[str, list[str]] = {}
    for name, value in populated.items():
        assert value is not None
        inverse.setdefault(value, []).append(name)
    collisions = tuple(names for names in inverse.values() if len(names) > 1)
    if collisions:
        raise ValueError("graph identities and fingerprints must be role-separated")


def _request_role_identities(
    request: SyntheticTemporalCompletionRequestV1,
) -> dict[str, str | None]:
    scope = request.prepared_scope
    root = scope.history_root
    selection = scope.selection_revision
    analysis_input = request.analysis_input
    return {
        "prepared_scope_id": scope.prepared_scope_id,
        "prepared_scope_fingerprint": scope.fingerprint,
        "automation_grant_id": scope.automation_grant_id,
        "automation_grant_fingerprint": scope.automation_grant_fingerprint,
        "history_root_id": root.root_receipt_id,
        "history_root_fingerprint": root.fingerprint,
        "project_id": root.project_id,
        "predecessor_history_root_id": root.predecessor_root_id,
        "predecessor_history_root_fingerprint": root.predecessor_root_fingerprint,
        "selection_revision_id": selection.selection_revision_id,
        "selection_revision_fingerprint": selection.fingerprint,
        "selection_scope_fingerprint": selection.metric_set_fingerprint,
        "selection_predecessor_id": selection.compare_and_swap_predecessor_id,
        "selection_predecessor_fingerprint": (
            selection.compare_and_swap_predecessor_fingerprint
        ),
        "metric_pack_fingerprint": selection.metric_pack_sha256,
        "metric_catalog_fingerprint": selection.metric_catalog_sha256,
        "completion_request_id": request.completion_request_id,
        "completion_request_fingerprint": request.fingerprint,
        "analysis_input_receipt_id": analysis_input.input_receipt_id,
        "analysis_input_receipt_fingerprint": analysis_input.fingerprint,
        "input_provenance_fingerprint": analysis_input.provenance_fingerprint,
        "analysis_run_id": analysis_input.analysis_run_id,
        "analysis_run_fingerprint": analysis_input.analysis_run_fingerprint,
        "analysis_run_request_fingerprint": (
            analysis_input.analysis_run_request_fingerprint
        ),
        "session_id": analysis_input.session_id,
        "analysis_window_fingerprint": analysis_input.analysis_window_fingerprint,
        "selected_manifest_root": analysis_input.selected_window_manifest_root,
        "selected_manifest_identity": (
            analysis_input.selected_window_manifest_identity_fingerprint
        ),
        "observed_manifest_root": (
            analysis_input.post_floor_observed_allowlisted_source_manifest_root
        ),
        "observed_manifest_identity": (
            analysis_input.post_floor_observed_allowlisted_source_manifest_identity_fingerprint
        ),
        "analysis_profile_fingerprint": analysis_input.analysis_profile_sha256,
        "metric_engine_fingerprint": analysis_input.metric_engine_sha256,
        "consent_receipt_id": analysis_input.consent_receipt_id,
        "consent_receipt_fingerprint": analysis_input.consent_receipt_fingerprint,
        "redactor_fingerprint": analysis_input.redactor_sha256,
        "preprocessing_fingerprint": analysis_input.preprocessing_sha256,
        "router_fingerprint": analysis_input.router_sha256,
        "run_plan_fingerprint": analysis_input.model_plan_fingerprint,
    }


def automation_grant_authority_version(revision: int) -> str:
    """Return the one exact selection-authority version for a stored revision."""

    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 1
        or revision > _MAX_ORDINAL
    ):
        raise ValueError("automation grant revisions must be positive integers")
    return f"{AUTOMATION_GRANT_CONTRACT_VERSION}.revision-{revision}"


class TemporalSourceAuthorityStateV1(StrEnum):
    """Closed source-authority state for the first persistence slice."""

    SYNTHETIC_TEST_ONLY = "synthetic_test_only"


class RepositoryPreparedTemporalScopeV1(PersistenceRevalidatedModel):
    """Repository-returned root/selection authority for one stored grant.

    The type is structurally constructible so repository adapters can hydrate
    it, but construction is not proof of repository authorship.  Only an object
    returned by ``prepare_automation_scope`` or a repository read is an
    authoritative repository result.  Its authority stops at the prospective
    root and exact metric selection; it grants no source-capture or product
    capability.
    """

    contract_version: Literal[REPOSITORY_PREPARED_TEMPORAL_SCOPE_V1_VERSION] = (
        REPOSITORY_PREPARED_TEMPORAL_SCOPE_V1_VERSION
    )
    prepared_scope_id: str
    history_root: TemporalHistoryRootReceipt
    selection_revision: ProjectMetricSelectionRevisionV2
    automation_grant_id: str
    automation_grant_fingerprint: str
    automation_grant_revision: PositiveStrictInt
    prepared_at: datetime
    repository_time_basis: Literal[REPOSITORY_TEMPORAL_TIME_BASIS_V1] = (
        REPOSITORY_TEMPORAL_TIME_BASIS_V1
    )
    repository_authority_scope: Literal[REPOSITORY_TEMPORAL_AUTHORITY_SCOPE_V1] = (
        REPOSITORY_TEMPORAL_AUTHORITY_SCOPE_V1
    )
    repository_return_required: Literal[True] = True
    structurally_constructible_not_capability: Literal[True] = True
    repository_owned: Literal[True] = True
    repository_graph_verified: Literal[True] = True
    selection_authority_verified: Literal[True] = True
    sealed: Literal[True] = True
    capture_authority_verified: Literal[False] = False
    product_capture_allowed: Literal[False] = False
    product_history_eligible: Literal[False] = False
    comparison_allowed: Literal[False] = False
    snapshot_materialization_allowed: Literal[False] = False
    activation_allowed: Literal[False] = False
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "prepared_scope_id",
        "automation_grant_id",
        "automation_grant_fingerprint",
    )(_digest)
    _prepared_at = field_validator("prepared_at")(_utc)

    @model_validator(mode="after")
    def exact_repository_scope(self) -> RepositoryPreparedTemporalScopeV1:
        root = self.history_root
        selection = self.selection_revision
        expected_authority_version = automation_grant_authority_version(
            self.automation_grant_revision
        )
        if (
            selection.root_receipt_id != root.root_receipt_id
            or selection.root_receipt_fingerprint != root.fingerprint
            or selection.project_id != root.project_id
        ):
            raise ValueError("prepared selection must bind the exact history root")
        if (
            selection.source is not ProjectMetricSelectionSource.AUTOMATION_GRANT
            or selection.source_authority_kind
            is not ProjectMetricSelectionAuthorityKind.AUTOMATION_GRANT
            or selection.source_authority_id != self.automation_grant_id
            or selection.source_authority_fingerprint
            != self.automation_grant_fingerprint
            or selection.source_authority_version != expected_authority_version
        ):
            raise ValueError("prepared selection must bind the exact stored grant revision")
        if (
            selection.effective_at < root.history_floor_at
            or selection.recorded_at < root.history_floor_at
            or self.prepared_at < selection.recorded_at
        ):
            raise ValueError("prepared temporal scope must remain prospective and ordered")
        _require_unique_roles(
            prepared_scope_id=self.prepared_scope_id,
            automation_grant_id=self.automation_grant_id,
            automation_grant_fingerprint=self.automation_grant_fingerprint,
            history_root_id=root.root_receipt_id,
            history_root_fingerprint=root.fingerprint,
            project_id=root.project_id,
            predecessor_history_root_id=root.predecessor_root_id,
            predecessor_history_root_fingerprint=root.predecessor_root_fingerprint,
            selection_revision_id=selection.selection_revision_id,
            selection_revision_fingerprint=selection.fingerprint,
            selection_scope_fingerprint=selection.metric_set_fingerprint,
            selection_predecessor_id=selection.compare_and_swap_predecessor_id,
            selection_predecessor_fingerprint=(
                selection.compare_and_swap_predecessor_fingerprint
            ),
            metric_pack_fingerprint=selection.metric_pack_sha256,
            metric_catalog_fingerprint=selection.metric_catalog_sha256,
        )
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class SyntheticTemporalCompletionRequestV1(PersistenceRevalidatedModel):
    """Test-only request that binds one synthetic input to a prepared scope.

    This public request contains no session revision, observation, batch, seal,
    or caller-supplied root/selection override.  It is not source authority and
    cannot authorize product history.  A repository may use it only in a
    synthetic test path while independently rehydrating the prepared scope.
    """

    contract_version: Literal[SYNTHETIC_TEMPORAL_COMPLETION_REQUEST_V1_VERSION] = (
        SYNTHETIC_TEMPORAL_COMPLETION_REQUEST_V1_VERSION
    )
    completion_request_id: str
    prepared_scope: RepositoryPreparedTemporalScopeV1
    analysis_input: AnalysisInputReceiptV2
    analysis_run_id: str
    synthetic_test_only: Literal[True] = True
    repository_rehydration_required: Literal[True] = True
    source_authority_verified: Literal[False] = False
    product_authority: Literal[False] = False
    product_history_eligible: Literal[False] = False
    sealed: Literal[False] = False
    comparison_allowed: Literal[False] = False
    snapshot_materialization_allowed: Literal[False] = False
    activation_allowed: Literal[False] = False
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator("completion_request_id", "analysis_run_id")(_digest)

    @model_validator(mode="after")
    def exact_synthetic_input(self) -> SyntheticTemporalCompletionRequestV1:
        scope = self.prepared_scope
        root = scope.history_root
        selection = scope.selection_revision
        analysis_input = self.analysis_input
        if analysis_input.provider is not Provider.SYNTHETIC:
            raise ValueError("the completion request is synthetic-provider test-only")
        if self.analysis_run_id != analysis_input.analysis_run_id:
            raise ValueError("completion request must bind the exact analysis run")
        if (
            analysis_input.root_receipt_id != root.root_receipt_id
            or analysis_input.root_receipt_fingerprint != root.fingerprint
            or analysis_input.project_id != root.project_id
        ):
            raise ValueError("synthetic input must bind the prepared history root")
        if (
            analysis_input.selection_revision_id
            != selection.selection_revision_id
            or analysis_input.selection_revision_fingerprint != selection.fingerprint
            or analysis_input.selection_scope_fingerprint
            != selection.metric_set_fingerprint
            or analysis_input.selected_metric_keys != selection.selected_metric_keys
            or analysis_input.metric_pack_key != selection.metric_pack_key
            or analysis_input.metric_pack_version != selection.metric_pack_version
            or analysis_input.metric_pack_sha256 != selection.metric_pack_sha256
            or analysis_input.metric_catalog_version
            != selection.metric_catalog_version
            or analysis_input.metric_catalog_sha256
            != selection.metric_catalog_sha256
        ):
            raise ValueError("synthetic input must bind the exact prepared selection")
        if analysis_input.analysis_window_started_at < root.history_floor_at:
            raise ValueError("synthetic completion cannot introduce pre-floor history")
        if analysis_input.captured_at < scope.prepared_at:
            raise ValueError("synthetic input cannot predate scope preparation")
        _require_unique_roles(**_request_role_identities(self))
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


def _draft_role_identities(
    request: SyntheticTemporalCompletionRequestV1,
    draft: RepositoryTemporalBatchSealDraft,
) -> dict[str, str | None]:
    """Collect each semantic graph identity once, excluding bound aliases."""

    roles = _request_role_identities(request)
    revision = draft.session_revision
    batch = draft.observation_batch
    roles.update(
        {
            "session_revision_id": revision.revision_id,
            "session_revision_fingerprint": revision.fingerprint,
            "session_revision_predecessor_id": revision.predecessor_revision_id,
            "session_revision_predecessor_fingerprint": (
                revision.predecessor_revision_fingerprint
            ),
            "session_revision_predecessor_link_fingerprint": (
                revision.predecessor_link_fingerprint
            ),
            "observation_batch_id": batch.batch_id,
            "observation_batch_fingerprint": batch.fingerprint,
            "seal_draft_id": draft.seal_draft_id,
            "seal_draft_fingerprint": draft.fingerprint,
            "repository_verifier_fingerprint": (
                draft.requested_repository_verifier_fingerprint
            ),
        }
    )
    for index, observation in enumerate(batch.observations):
        roles[f"observation_{index}_id"] = observation.observation_id
        roles[f"observation_{index}_fingerprint"] = observation.fingerprint
        roles[f"comparison_identity_{index}_fingerprint"] = (
            observation.comparison_identity.fingerprint
        )
    return roles


class RepositorySealedTemporalBatchV1(PersistenceRevalidatedModel):
    """Repository-verified graph seal with deliberately absent source authority.

    The repository can attest that the exact draft graph and ordered child
    fingerprints were persisted together.  For this first slice the underlying
    provider is necessarily synthetic, so the seal remains test-only and grants
    no product-history or downstream materialization capability.
    """

    contract_version: Literal[REPOSITORY_SEALED_TEMPORAL_BATCH_V1_VERSION] = (
        REPOSITORY_SEALED_TEMPORAL_BATCH_V1_VERSION
    )
    sealed_batch_id: str
    completion_request: SyntheticTemporalCompletionRequestV1
    prepared_scope_fingerprint: str
    completion_request_fingerprint: str
    seal_draft: RepositoryTemporalBatchSealDraft
    seal_draft_fingerprint: str
    ordered_graph_fingerprints: tuple[str, ...] = Field(
        min_length=8,
        max_length=MAX_REPOSITORY_GRAPH_FINGERPRINTS,
    )
    repository_verifier_version: str
    repository_verifier_fingerprint: str
    sealed_at: datetime
    source_authority_state: Literal[
        TemporalSourceAuthorityStateV1.SYNTHETIC_TEST_ONLY
    ] = TemporalSourceAuthorityStateV1.SYNTHETIC_TEST_ONLY
    repository_return_required: Literal[True] = True
    structurally_constructible_not_capability: Literal[True] = True
    repository_owned: Literal[True] = True
    repository_graph_verified: Literal[True] = True
    sealed: Literal[True] = True
    source_authority_verified: Literal[False] = False
    capture_authority_verified: Literal[False] = False
    product_history_eligible: Literal[False] = False
    comparison_allowed: Literal[False] = False
    snapshot_materialization_allowed: Literal[False] = False
    activation_allowed: Literal[False] = False
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _digests = field_validator(
        "sealed_batch_id",
        "prepared_scope_fingerprint",
        "completion_request_fingerprint",
        "seal_draft_fingerprint",
        "repository_verifier_fingerprint",
    )(_digest)
    _verifier_version = field_validator("repository_verifier_version")(
        _safe_version
    )
    _sealed_at = field_validator("sealed_at")(_utc)

    @field_validator("ordered_graph_fingerprints")
    @classmethod
    def exact_digest_sequence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(_digest(value) for value in values)
        if len(checked) != len(set(checked)):
            raise ValueError("ordered graph fingerprints must be unique")
        return checked

    @model_validator(mode="after")
    def exact_repository_seal(self) -> RepositorySealedTemporalBatchV1:
        draft = self.seal_draft
        request = self.completion_request
        scope = request.prepared_scope
        if draft.analysis_input.provider is not Provider.SYNTHETIC:
            raise ValueError("the first repository seal is synthetic-test-only")
        if (
            self.prepared_scope_fingerprint != scope.fingerprint
            or self.completion_request_fingerprint != request.fingerprint
        ):
            raise ValueError("repository seal must bind the exact prepared request")
        if (
            draft.history_root != scope.history_root
            or draft.selection_revision != scope.selection_revision
            or draft.analysis_input != request.analysis_input
            or draft.analysis_run_id != request.analysis_run_id
            or draft.analysis_run_fingerprint
            != request.analysis_input.analysis_run_fingerprint
        ):
            raise ValueError("seal draft must descend from the exact prepared request")
        if self.seal_draft_fingerprint != draft.fingerprint:
            raise ValueError("repository seal must bind the exact draft fingerprint")
        expected_graph = (
            scope.fingerprint,
            request.fingerprint,
            draft.history_root.fingerprint,
            draft.selection_revision.fingerprint,
            draft.analysis_input.fingerprint,
            draft.session_revision.fingerprint,
            draft.observation_batch.fingerprint,
            *(item.fingerprint for item in draft.observation_batch.observations),
        )
        if self.ordered_graph_fingerprints != expected_graph:
            raise ValueError("repository seal must commit the exact ordered graph")
        if (
            self.repository_verifier_version
            != draft.requested_repository_verifier_version
            or self.repository_verifier_fingerprint
            != draft.requested_repository_verifier_fingerprint
        ):
            raise ValueError("repository seal must use the requested verifier identity")
        if self.sealed_at < draft.drafted_at:
            raise ValueError("repository seal cannot predate its draft")
        _require_unique_roles(
            **_draft_role_identities(request, draft),
            sealed_batch_id=self.sealed_batch_id,
            repository_seal_fingerprint=_canonical_digest(self),
        )
        return self

    @classmethod
    def ordered_graph_for(
        cls,
        completion_request: SyntheticTemporalCompletionRequestV1,
        draft: RepositoryTemporalBatchSealDraft,
    ) -> tuple[str, ...]:
        """Derive, but never trust, the canonical graph commitment sequence."""

        checked_request = SyntheticTemporalCompletionRequestV1.revalidate_for_persistence(
            completion_request
        )
        checked = RepositoryTemporalBatchSealDraft.revalidate_for_persistence(draft)
        if (
            checked.history_root != checked_request.prepared_scope.history_root
            or checked.selection_revision
            != checked_request.prepared_scope.selection_revision
            or checked.analysis_input != checked_request.analysis_input
            or checked.analysis_run_id != checked_request.analysis_run_id
            or checked.analysis_run_fingerprint
            != checked_request.analysis_input.analysis_run_fingerprint
        ):
            raise ValueError("seal draft must descend from the exact prepared request")
        _require_unique_roles(**_draft_role_identities(checked_request, checked))
        return (
            checked_request.prepared_scope.fingerprint,
            checked_request.fingerprint,
            checked.history_root.fingerprint,
            checked.selection_revision.fingerprint,
            checked.analysis_input.fingerprint,
            checked.session_revision.fingerprint,
            checked.observation_batch.fingerprint,
            *(item.fingerprint for item in checked.observation_batch.observations),
        )

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class TemporalHistoryPersistenceRepositoryV1(Protocol):
    """Read-oriented repository boundary; no public full-graph write exists."""

    def prepare_automation_scope(
        self, grant_id: str
    ) -> RepositoryPreparedTemporalScopeV1: ...

    def get_prepared_scope(
        self, prepared_scope_id: str
    ) -> RepositoryPreparedTemporalScopeV1 | None: ...

    def get_prepared_scope_for_grant(
        self, grant_id: str
    ) -> RepositoryPreparedTemporalScopeV1 | None: ...

    def get_sealed_batch(
        self, sealed_batch_id: str
    ) -> RepositorySealedTemporalBatchV1 | None: ...

    def get_sealed_batch_for_run(
        self, analysis_run_id: str
    ) -> RepositorySealedTemporalBatchV1 | None: ...


__all__ = [
    "MAX_REPOSITORY_GRAPH_FINGERPRINTS",
    "REPOSITORY_PREPARED_TEMPORAL_SCOPE_V1_VERSION",
    "REPOSITORY_SEALED_TEMPORAL_BATCH_V1_VERSION",
    "REPOSITORY_TEMPORAL_AUTHORITY_SCOPE_V1",
    "REPOSITORY_TEMPORAL_TIME_BASIS_V1",
    "SYNTHETIC_TEMPORAL_COMPLETION_REQUEST_V1_VERSION",
    "RepositoryPreparedTemporalScopeV1",
    "RepositorySealedTemporalBatchV1",
    "SyntheticTemporalCompletionRequestV1",
    "TemporalHistoryPersistenceRepositoryV1",
    "TemporalSourceAuthorityStateV1",
    "automation_grant_authority_version",
]
