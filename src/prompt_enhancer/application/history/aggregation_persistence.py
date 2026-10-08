"""Repository-return contracts for bounded synthetic aggregation validation.

These contracts seal only a content-free repository collection graph.  They do
not turn the embedded supplied-set aggregation draft into a repository-owned
aggregate, a product comparison, or a temporal snapshot.  Structural model
construction is never repository authorship; trusted callers must obtain the
outer receipt from an implementation of the narrow repository protocol.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
import re
from typing import Any, Literal, Protocol

from pydantic import Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, Provider, StrictModel
from .aggregation import (
    LAST_N_ORDER_VERSION,
    MAX_SUPPLIED_STRATA,
    RepositoryBackedStratumManifestEntryV2,
    RepositoryBackedSyntheticRawAggregationDraftV2,
)
from .comparison_strata_persistence import (
    RepositorySealedComparisonStratumV1,
    _sealed_alias_groups,
    _sealed_distinct_roles,
)
from .contracts import PersistenceRevalidatedModel, TemporalWindowSpec


SYNTHETIC_AGGREGATION_COLLECTION_PREDICATE_V1_VERSION = (
    "synthetic-aggregation-sealed-stratum-query-v1"
)
SYNTHETIC_AGGREGATION_COLLECTION_ENUMERATION_V1_VERSION = (
    "synthetic-aggregation-collection-enumeration-v1"
)
REPOSITORY_SEALED_SYNTHETIC_AGGREGATION_VALIDATION_V1_VERSION = (
    "repository-sealed-synthetic-aggregation-validation-v1"
)
SYNTHETIC_AGGREGATION_QUERY_PREDICATE_VERSION = (
    "same-root-source-sealed-at-inclusive-v1"
)
SYNTHETIC_AGGREGATION_QUERY_ORDER_VERSION = LAST_N_ORDER_VERSION
SYNTHETIC_AGGREGATION_QUERY_VERIFIER_VERSION = (
    "synthetic-aggregation-query-verifier-v1"
)
SYNTHETIC_AGGREGATION_REPOSITORY_VERIFIER_VERSION = (
    "synthetic-aggregation-repository-verifier-v1"
)
SYNTHETIC_AGGREGATION_OVERFLOW_PROBE_LIMIT = MAX_SUPPLIED_STRATA + 1

_SAFE_CODE = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")
_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")


def _digest(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase SHA-256 identifier")
    return value


def _safe_code(value: str) -> str:
    if _SAFE_CODE.fullmatch(value) is None or ".." in value:
        raise ValueError("value must be a lowercase path-free content code")
    return value


def _safe_version(value: str) -> str:
    if _SAFE_VERSION.fullmatch(value) is None or ".." in value:
        raise ValueError("value must be a path-free version")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be canonical UTC")
    return value.astimezone(UTC)


def _jsonable(value: Any) -> Any:
    if isinstance(value, StrictModel):
        return {
            field_name: _jsonable(getattr(value, field_name))
            for field_name in type(value).model_fields
        }
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, dict):
        return {key: _jsonable(nested) for key, nested in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(nested) for nested in value]
    if hasattr(value, "value"):
        return value.value
    return value


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _jsonable(value),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _domain_digest(role: str, value: Any) -> str:
    return _canonical_digest({"role": role, "payload": value})


SYNTHETIC_AGGREGATION_QUERY_VERIFIER_FINGERPRINT = _domain_digest(
    "synthetic-aggregation-query-verifier-v1",
    {
        "maximum_member_count": MAX_SUPPLIED_STRATA,
        "order_version": SYNTHETIC_AGGREGATION_QUERY_ORDER_VERSION,
        "overflow_probe_limit": SYNTHETIC_AGGREGATION_OVERFLOW_PROBE_LIMIT,
        "predicate_version": SYNTHETIC_AGGREGATION_QUERY_PREDICATE_VERSION,
        "sealed_at_inclusive": True,
    },
)
SYNTHETIC_AGGREGATION_REPOSITORY_VERIFIER_FINGERPRINT = _domain_digest(
    "synthetic-aggregation-repository-verifier-v1",
    {
        "query_verifier_fingerprint": (
            SYNTHETIC_AGGREGATION_QUERY_VERIFIER_FINGERPRINT
        ),
        "root_written_last": True,
        "validation_contract_version": (
            REPOSITORY_SEALED_SYNTHETIC_AGGREGATION_VALIDATION_V1_VERSION
        ),
    },
)


class SyntheticAggregationCollectionPredicateV1(PersistenceRevalidatedModel):
    """Exact repository query boundary for one atomic issuance attempt."""

    contract_version: Literal[
        SYNTHETIC_AGGREGATION_COLLECTION_PREDICATE_V1_VERSION
    ] = SYNTHETIC_AGGREGATION_COLLECTION_PREDICATE_V1_VERSION
    query_id: str
    idempotency_key_sha256: str
    anchor_sealed_stratum_id: str
    anchor_sealed_stratum_fingerprint: str
    anchor_prepared_stratum_id: str
    anchor_prepared_stratum_fingerprint: str
    root_receipt_id: str
    root_receipt_fingerprint: str
    history_floor_at: datetime
    installation_id: str
    project_id: str
    provider: Literal[Provider.SYNTHETIC] = Provider.SYNTHETIC
    metric_key: str
    window: TemporalWindowSpec
    as_of: datetime
    query_predicate_version: Literal[
        SYNTHETIC_AGGREGATION_QUERY_PREDICATE_VERSION
    ] = SYNTHETIC_AGGREGATION_QUERY_PREDICATE_VERSION
    query_order_version: Literal[SYNTHETIC_AGGREGATION_QUERY_ORDER_VERSION] = (
        SYNTHETIC_AGGREGATION_QUERY_ORDER_VERSION
    )
    maximum_member_count: Literal[MAX_SUPPLIED_STRATA] = MAX_SUPPLIED_STRATA
    overflow_probe_limit: Literal[SYNTHETIC_AGGREGATION_OVERFLOW_PROBE_LIMIT] = (
        SYNTHETIC_AGGREGATION_OVERFLOW_PROBE_LIMIT
    )
    sealed_at_inclusive: Literal[True] = True
    caller_as_of_allowed: Literal[False] = False
    caller_supplied_strata_allowed: Literal[False] = False
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False

    _digests = field_validator(
        "query_id",
        "idempotency_key_sha256",
        "anchor_sealed_stratum_id",
        "anchor_sealed_stratum_fingerprint",
        "anchor_prepared_stratum_id",
        "anchor_prepared_stratum_fingerprint",
        "root_receipt_id",
        "root_receipt_fingerprint",
        "installation_id",
        "project_id",
    )(_digest)
    _metric = field_validator("metric_key")(_safe_code)
    _times = field_validator("history_floor_at", "as_of")(_utc)
    _versions = field_validator(
        "query_predicate_version", "query_order_version"
    )(_safe_version)

    @classmethod
    def query_id_for(
        cls,
        *,
        idempotency_key_sha256: str,
        anchor: RepositorySealedComparisonStratumV1,
        metric_key: str,
        window: TemporalWindowSpec,
        as_of: datetime,
    ) -> str:
        prepared = anchor.prepared_receipt
        root = prepared.prepared_scope.history_root
        dimensions = prepared.dimensions
        return _domain_digest(
            "synthetic-aggregation-collection-query-v1",
            {
                "anchor_prepared_stratum_fingerprint": prepared.fingerprint,
                "anchor_prepared_stratum_id": prepared.prepared_stratum_id,
                "anchor_sealed_stratum_fingerprint": anchor.fingerprint,
                "anchor_sealed_stratum_id": anchor.sealed_stratum_id,
                "as_of": as_of,
                "caller_as_of_allowed": False,
                "caller_supplied_strata_allowed": False,
                "contract_version": (
                    SYNTHETIC_AGGREGATION_COLLECTION_PREDICATE_V1_VERSION
                ),
                "contains_local_content": False,
                "history_floor_at": root.history_floor_at,
                "idempotency_key_sha256": idempotency_key_sha256,
                "installation_id": dimensions.installation_id,
                "maximum_member_count": MAX_SUPPLIED_STRATA,
                "metric_key": metric_key,
                "overflow_probe_limit": (
                    SYNTHETIC_AGGREGATION_OVERFLOW_PROBE_LIMIT
                ),
                "project_id": dimensions.project_id,
                "provider": dimensions.provider,
                "query_order_version": SYNTHETIC_AGGREGATION_QUERY_ORDER_VERSION,
                "query_predicate_version": (
                    SYNTHETIC_AGGREGATION_QUERY_PREDICATE_VERSION
                ),
                "root_receipt_fingerprint": root.fingerprint,
                "root_receipt_id": root.root_receipt_id,
                "remote_processing_allowed": False,
                "sealed_at_inclusive": True,
                "window": window,
            },
        )

    @classmethod
    def from_repository_query(
        cls,
        *,
        idempotency_key_sha256: str,
        anchor: RepositorySealedComparisonStratumV1,
        metric_key: str,
        window: TemporalWindowSpec,
        as_of: datetime,
    ) -> SyntheticAggregationCollectionPredicateV1:
        checked_anchor = RepositorySealedComparisonStratumV1.revalidate_for_persistence(
            anchor
        )
        checked_window = TemporalWindowSpec.model_validate(
            window.model_dump(mode="python")
        )
        checked_key = _digest(idempotency_key_sha256)
        checked_metric = _safe_code(metric_key)
        checked_as_of = _utc(as_of)
        prepared = checked_anchor.prepared_receipt
        root = prepared.prepared_scope.history_root
        dimensions = prepared.dimensions
        return cls(
            query_id=cls.query_id_for(
                idempotency_key_sha256=checked_key,
                anchor=checked_anchor,
                metric_key=checked_metric,
                window=checked_window,
                as_of=checked_as_of,
            ),
            idempotency_key_sha256=checked_key,
            anchor_sealed_stratum_id=checked_anchor.sealed_stratum_id,
            anchor_sealed_stratum_fingerprint=checked_anchor.fingerprint,
            anchor_prepared_stratum_id=prepared.prepared_stratum_id,
            anchor_prepared_stratum_fingerprint=prepared.fingerprint,
            root_receipt_id=root.root_receipt_id,
            root_receipt_fingerprint=root.fingerprint,
            history_floor_at=root.history_floor_at,
            installation_id=dimensions.installation_id,
            project_id=dimensions.project_id,
            provider=dimensions.provider,
            metric_key=checked_metric,
            window=checked_window,
            as_of=checked_as_of,
        )

    @model_validator(mode="after")
    def exact_query(self) -> SyntheticAggregationCollectionPredicateV1:
        if self.as_of < self.history_floor_at:
            raise ValueError("query as-of cannot predate the prospective floor")
        expected_id = _domain_digest(
            "synthetic-aggregation-collection-query-v1",
            self.model_dump(mode="python", exclude={"query_id"}),
        )
        if self.query_id != expected_id:
            raise ValueError("query ID must bind the exact repository predicate")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class SyntheticAggregationCollectionEnumerationReceiptV1(
    PersistenceRevalidatedModel
):
    """Repository-return-only attestation of one bounded query result."""

    contract_version: Literal[
        SYNTHETIC_AGGREGATION_COLLECTION_ENUMERATION_V1_VERSION
    ] = SYNTHETIC_AGGREGATION_COLLECTION_ENUMERATION_V1_VERSION
    enumeration_id: str
    predicate: SyntheticAggregationCollectionPredicateV1
    predicate_fingerprint: str
    ordered_members: tuple[RepositoryBackedStratumManifestEntryV2, ...] = Field(
        min_length=1,
        max_length=MAX_SUPPLIED_STRATA,
    )
    member_count: int = Field(strict=True, ge=1, le=MAX_SUPPLIED_STRATA)
    overflow_detected: Literal[False] = False
    max_plus_one_probe_performed: Literal[True] = True
    query_verifier_version: Literal[
        SYNTHETIC_AGGREGATION_QUERY_VERIFIER_VERSION
    ] = SYNTHETIC_AGGREGATION_QUERY_VERIFIER_VERSION
    query_verifier_fingerprint: Literal[
        SYNTHETIC_AGGREGATION_QUERY_VERIFIER_FINGERPRINT
    ] = SYNTHETIC_AGGREGATION_QUERY_VERIFIER_FINGERPRINT
    repository_return_required: Literal[True] = True
    structurally_constructible_not_capability: Literal[True] = True
    repository_transaction_snapshot_used: Literal[True] = True
    bounded_sealed_stratum_collection_complete: Literal[True] = True
    population_completeness_verified: Literal[False] = False
    product_history_completeness_verified: Literal[False] = False
    source_authority_verified: Literal[False] = False
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False

    _digests = field_validator(
        "enumeration_id",
        "predicate_fingerprint",
        "query_verifier_fingerprint",
    )(_digest)
    _version = field_validator("query_verifier_version")(_safe_version)

    @model_validator(mode="before")
    @classmethod
    def bounded_immutable_members(cls, value: Any) -> Any:
        if isinstance(value, cls):
            members = value.ordered_members
        elif isinstance(value, dict):
            members = value.get("ordered_members")
        else:
            return value
        if not isinstance(members, tuple):
            raise ValueError("enumeration members must be an immutable tuple")
        if not 1 <= len(members) <= MAX_SUPPLIED_STRATA:
            raise ValueError("enumeration member count exceeds the bounded query")
        return value

    @classmethod
    def revalidate_for_persistence(
        cls,
        value: Any,
    ) -> SyntheticAggregationCollectionEnumerationReceiptV1:
        """Preserve the raw tuple boundary before recursive revalidation."""

        return cls.model_validate(value)

    @classmethod
    def enumeration_id_for(
        cls,
        *,
        predicate: SyntheticAggregationCollectionPredicateV1,
        ordered_members: tuple[RepositoryBackedStratumManifestEntryV2, ...],
    ) -> str:
        return _domain_digest(
            "synthetic-aggregation-collection-enumeration-v1",
            {
                "contract_version": (
                    SYNTHETIC_AGGREGATION_COLLECTION_ENUMERATION_V1_VERSION
                ),
                "ordered_members": ordered_members,
                "predicate": predicate,
                "query_verifier_fingerprint": (
                    SYNTHETIC_AGGREGATION_QUERY_VERIFIER_FINGERPRINT
                ),
            },
        )

    @model_validator(mode="after")
    def exact_enumeration(
        self,
    ) -> SyntheticAggregationCollectionEnumerationReceiptV1:
        predicate = SyntheticAggregationCollectionPredicateV1.revalidate_for_persistence(
            self.predicate
        )
        members = tuple(
            RepositoryBackedStratumManifestEntryV2.revalidate_for_persistence(item)
            for item in self.ordered_members
        )
        if self.predicate_fingerprint != predicate.fingerprint:
            raise ValueError("enumeration must bind the exact query predicate")
        if self.member_count != len(members):
            raise ValueError("enumeration count must equal the ordered member set")
        if tuple(item.supplied_ordinal for item in members) != tuple(
            range(len(members))
        ):
            raise ValueError("enumeration member ordinals must be contiguous")
        canonical = tuple(
            sorted(
                members,
                key=lambda item: (
                    item.effective_at,
                    item.session_id,
                    item.revision_ordinal,
                    item.revision_id,
                    item.sealed_stratum_id,
                ),
            )
        )
        if members != canonical:
            raise ValueError("enumeration must retain the canonical query order")
        if any(item.sealed_at > predicate.as_of for item in members):
            raise ValueError("enumeration cannot include post-as-of seals")
        unique_roles = {
            "prepared ID": tuple(item.prepared_stratum_id for item in members),
            "prepared fingerprint": tuple(
                item.prepared_stratum_fingerprint for item in members
            ),
            "sealed ID": tuple(item.sealed_stratum_id for item in members),
            "sealed fingerprint": tuple(
                item.sealed_stratum_fingerprint for item in members
            ),
            "run ID": tuple(item.analysis_run_id for item in members),
            "run authority": tuple(
                item.analysis_run_authority_sha256 for item in members
            ),
            "batch ID": tuple(item.sealed_batch_id for item in members),
            "batch fingerprint": tuple(item.sealed_batch_sha256 for item in members),
            "revision ID": tuple(item.revision_id for item in members),
            "revision fingerprint": tuple(
                item.revision_fingerprint for item in members
            ),
            "member fingerprint": tuple(item.fingerprint for item in members),
        }
        for role, values in unique_roles.items():
            if len(values) != len(set(values)):
                raise ValueError(f"enumeration has a duplicate {role}")
        coordinates = tuple(
            (item.session_id, item.revision_ordinal) for item in members
        )
        if len(coordinates) != len(set(coordinates)):
            raise ValueError("enumeration has a duplicate revision coordinate")
        expected_id = self.enumeration_id_for(
            predicate=predicate,
            ordered_members=members,
        )
        if self.enumeration_id != expected_id:
            raise ValueError("enumeration ID must bind the complete ordered result")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


def _require_distinct_validation_roles(
    *,
    validation_receipt_id: str,
    anchor: RepositorySealedComparisonStratumV1,
    predicate: SyntheticAggregationCollectionPredicateV1,
    enumeration: SyntheticAggregationCollectionEnumerationReceiptV1,
    aggregation: RepositoryBackedSyntheticRawAggregationDraftV2,
    anchor_member_index: int,
) -> None:
    anchor_roles = _sealed_distinct_roles(
        sealed_stratum_id=anchor.sealed_stratum_id,
        prepared=anchor.prepared_receipt,
        run=anchor.analysis_run,
        run_authority_fingerprint=anchor.analysis_run_authority_sha256,
        batch=anchor.sealed_batch,
        revalidation=anchor.automation_revalidation_request,
    )
    roles: dict[str, str | None] = {
        **{f"anchor_{name}": value for name, value in anchor_roles.items()},
        "validation_receipt_id": validation_receipt_id,
        "idempotency_key": predicate.idempotency_key_sha256,
        "query_id": predicate.query_id,
        "query_fingerprint": predicate.fingerprint,
        "enumeration_id": enumeration.enumeration_id,
        "enumeration_fingerprint": enumeration.fingerprint,
        "enumeration_predicate_fingerprint": enumeration.predicate_fingerprint,
        "query_verifier": SYNTHETIC_AGGREGATION_QUERY_VERIFIER_FINGERPRINT,
        "repository_verifier": (
            SYNTHETIC_AGGREGATION_REPOSITORY_VERIFIER_FINGERPRINT
        ),
        "aggregation_id": aggregation.aggregation_draft_id,
        "aggregation_fingerprint": aggregation.fingerprint,
        "outer_aggregation_fingerprint": aggregation.fingerprint,
        "aggregation_policy": aggregation.policy_identity_fingerprint,
        "embedded_anchor_fingerprint": anchor.fingerprint,
        "predicate_anchor_sealed_id": predicate.anchor_sealed_stratum_id,
        "predicate_anchor_sealed_fingerprint": (
            predicate.anchor_sealed_stratum_fingerprint
        ),
        "predicate_anchor_prepared_id": predicate.anchor_prepared_stratum_id,
        "predicate_anchor_prepared_fingerprint": (
            predicate.anchor_prepared_stratum_fingerprint
        ),
        "predicate_root_id": predicate.root_receipt_id,
        "predicate_root_fingerprint": predicate.root_receipt_fingerprint,
        "predicate_installation_id": predicate.installation_id,
        "predicate_project_id": predicate.project_id,
        "aggregation_anchor_prepared_id": aggregation.anchor_prepared_stratum_id,
        "aggregation_anchor_prepared_fingerprint": (
            aggregation.anchor_prepared_stratum_fingerprint
        ),
        "aggregation_root_id": aggregation.root_receipt_id,
        "aggregation_root_fingerprint": aggregation.root_receipt_fingerprint,
        "aggregation_installation_id": aggregation.installation_id,
        "aggregation_project_id": aggregation.project_id,
    }
    for index, item in enumerate(enumeration.ordered_members):
        prefix = f"member_{index}"
        roles.update(
            {
                f"{prefix}_fingerprint": item.fingerprint,
                f"{prefix}_prepared_id": item.prepared_stratum_id,
                f"{prefix}_prepared_fingerprint": (
                    item.prepared_stratum_fingerprint
                ),
                f"{prefix}_sealed_id": item.sealed_stratum_id,
                f"{prefix}_sealed_fingerprint": item.sealed_stratum_fingerprint,
                f"{prefix}_run_id": item.analysis_run_id,
                f"{prefix}_run_authority": item.analysis_run_authority_sha256,
                f"{prefix}_batch_id": item.sealed_batch_id,
                f"{prefix}_batch_fingerprint": item.sealed_batch_sha256,
                f"{prefix}_revision_id": item.revision_id,
                f"{prefix}_revision_fingerprint": item.revision_fingerprint,
                f"{prefix}_session_id": item.session_id,
            }
        )

    prefixed_anchor_aliases = tuple(
        frozenset(f"anchor_{name}" for name in group)
        for group in _sealed_alias_groups(anchor.sealed_batch)
    )
    member = f"member_{anchor_member_index}"
    allowed_aliases = (
        *prefixed_anchor_aliases,
        frozenset(
            {
                "query_fingerprint",
                "enumeration_predicate_fingerprint",
            }
        ),
        frozenset(
            {
                "aggregation_fingerprint",
                "outer_aggregation_fingerprint",
            }
        ),
        frozenset(
            {
                "anchor_prepared_stratum_id",
                "predicate_anchor_prepared_id",
                "aggregation_anchor_prepared_id",
                f"{member}_prepared_id",
            }
        ),
        frozenset(
            {
                "anchor_prepared_receipt_fingerprint",
                "predicate_anchor_prepared_fingerprint",
                "aggregation_anchor_prepared_fingerprint",
                f"{member}_prepared_fingerprint",
            }
        ),
        frozenset(
            {
                "anchor_sealed_stratum_id",
                "predicate_anchor_sealed_id",
                f"{member}_sealed_id",
            }
        ),
        frozenset(
            {
                "embedded_anchor_fingerprint",
                "predicate_anchor_sealed_fingerprint",
                f"{member}_sealed_fingerprint",
            }
        ),
        frozenset(
            {
                "anchor_history_root_id",
                "predicate_root_id",
                "aggregation_root_id",
            }
        ),
        frozenset(
            {
                "anchor_history_root_fingerprint",
                "predicate_root_fingerprint",
                "aggregation_root_fingerprint",
            }
        ),
        frozenset(
            {
                "anchor_installation_id",
                "predicate_installation_id",
                "aggregation_installation_id",
            }
        ),
        frozenset(
            {
                "anchor_project_id",
                "predicate_project_id",
                "aggregation_project_id",
            }
        ),
        frozenset(
            {
                "anchor_expected_analysis_run_id",
                f"{member}_run_id",
            }
        ),
        frozenset(
            {
                "anchor_analysis_run_authority_fingerprint",
                f"{member}_run_authority",
            }
        ),
        frozenset({"anchor_sealed_batch_id", f"{member}_batch_id"}),
        frozenset(
            {
                "anchor_sealed_batch_fingerprint",
                f"{member}_batch_fingerprint",
            }
        ),
        frozenset(
            {
                "anchor_session_revision_id",
                f"{member}_revision_id",
            }
        ),
        frozenset(
            {
                "anchor_session_revision_fingerprint",
                f"{member}_revision_fingerprint",
            }
        ),
        frozenset(
            {
                "anchor_session_id",
                *(f"member_{index}_session_id" for index in range(len(enumeration.ordered_members))),
            }
        ),
    )
    inverse: dict[str, list[str]] = {}
    for name, value in roles.items():
        if value is None:
            continue
        inverse.setdefault(_digest(value), []).append(name)
    for names in inverse.values():
        if len(names) <= 1:
            continue
        colliding = frozenset(names)
        if any(colliding.issubset(group) for group in allowed_aliases):
            continue
        raise ValueError("validation identities must be globally role-separated")


def _exact_anchor_manifest_entry(
    anchor: RepositorySealedComparisonStratumV1,
    member: RepositoryBackedStratumManifestEntryV2,
) -> RepositoryBackedStratumManifestEntryV2:
    revision = anchor.sealed_batch.seal_draft.session_revision
    return RepositoryBackedStratumManifestEntryV2(
        supplied_ordinal=member.supplied_ordinal,
        prepared_stratum_id=anchor.prepared_receipt.prepared_stratum_id,
        prepared_stratum_fingerprint=anchor.prepared_receipt.fingerprint,
        sealed_stratum_id=anchor.sealed_stratum_id,
        sealed_stratum_fingerprint=anchor.fingerprint,
        analysis_run_id=anchor.analysis_run.draft.run_id,
        analysis_run_authority_sha256=anchor.analysis_run_authority_sha256,
        sealed_batch_id=anchor.sealed_batch.sealed_batch_id,
        sealed_batch_sha256=anchor.sealed_batch_sha256,
        revision_id=revision.revision_id,
        revision_fingerprint=revision.fingerprint,
        session_id=revision.session_id,
        revision_ordinal=revision.revision_ordinal,
        effective_at=revision.effective_at,
        sealed_at=anchor.sealed_at,
        disposition=member.disposition,
    )


class RepositorySealedSyntheticAggregationValidationV1(
    PersistenceRevalidatedModel
):
    """Repository-returned seal of a bounded synthetic aggregation graph."""

    contract_version: Literal[
        REPOSITORY_SEALED_SYNTHETIC_AGGREGATION_VALIDATION_V1_VERSION
    ] = REPOSITORY_SEALED_SYNTHETIC_AGGREGATION_VALIDATION_V1_VERSION
    validation_receipt_id: str
    anchor: RepositorySealedComparisonStratumV1
    predicate: SyntheticAggregationCollectionPredicateV1
    enumeration: SyntheticAggregationCollectionEnumerationReceiptV1
    aggregation_draft: RepositoryBackedSyntheticRawAggregationDraftV2
    aggregation_draft_fingerprint: str
    ordered_graph_fingerprints: tuple[str, ...] = Field(
        min_length=8,
        max_length=7 + MAX_SUPPLIED_STRATA,
    )
    repository_verifier_version: Literal[
        SYNTHETIC_AGGREGATION_REPOSITORY_VERIFIER_VERSION
    ] = SYNTHETIC_AGGREGATION_REPOSITORY_VERIFIER_VERSION
    repository_verifier_fingerprint: Literal[
        SYNTHETIC_AGGREGATION_REPOSITORY_VERIFIER_FINGERPRINT
    ] = SYNTHETIC_AGGREGATION_REPOSITORY_VERIFIER_FINGERPRINT
    sealed_at: datetime

    repository_return_required: Literal[True] = True
    structurally_constructible_not_capability: Literal[True] = True
    synthetic_test_only: Literal[True] = True
    repository_owned: Literal[True] = True
    repository_graph_verified: Literal[True] = True
    repository_enumeration_performed: Literal[True] = True
    bounded_sealed_stratum_collection_complete: Literal[True] = True
    sealed: Literal[True] = True
    idempotent_issue_while_receipt_exists_guaranteed: Literal[True] = True
    privacy_deletion_revokes_replay_history: Literal[True] = True
    privacy_deletion_erases_idempotency_binding: Literal[True] = True
    privacy_deletion_retains_idempotency_tombstone: Literal[False] = False
    embedded_aggregation_repository_owned: Literal[False] = False
    comparison_stratum_complete: Literal[False] = False
    population_completeness_verified: Literal[False] = False
    product_history_completeness_verified: Literal[False] = False
    source_authority_verified: Literal[False] = False
    product_capture_allowed: Literal[False] = False
    product_history_eligible: Literal[False] = False
    comparison_allowed: Literal[False] = False
    pair_matching_allowed: Literal[False] = False
    aggregate_materialization_allowed: Literal[False] = False
    snapshot_materialization_allowed: Literal[False] = False
    recommendation_allowed: Literal[False] = False
    recommendation_outcome_evaluation_allowed: Literal[False] = False
    causal_claim_allowed: Literal[False] = False
    activation_allowed: Literal[False] = False
    legacy_inference_allowed: Literal[False] = False
    backfill_allowed: Literal[False] = False
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _digests = field_validator(
        "validation_receipt_id",
        "aggregation_draft_fingerprint",
        "repository_verifier_fingerprint",
    )(_digest)
    _version = field_validator("repository_verifier_version")(_safe_version)
    _sealed = field_validator("sealed_at")(_utc)

    @field_validator("ordered_graph_fingerprints")
    @classmethod
    def exact_graph_digests(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(_digest(value) for value in values)
        if len(checked) != len(set(checked)):
            raise ValueError("validation graph fingerprints must be unique")
        return checked

    @classmethod
    def ordered_graph_for(
        cls,
        *,
        anchor: RepositorySealedComparisonStratumV1,
        predicate: SyntheticAggregationCollectionPredicateV1,
        enumeration: SyntheticAggregationCollectionEnumerationReceiptV1,
        aggregation_draft: RepositoryBackedSyntheticRawAggregationDraftV2,
    ) -> tuple[str, ...]:
        return (
            anchor.fingerprint,
            predicate.fingerprint,
            enumeration.fingerprint,
            aggregation_draft.aggregation_draft_id,
            aggregation_draft.fingerprint,
            aggregation_draft.policy_identity_fingerprint,
            *(item.fingerprint for item in enumeration.ordered_members),
            SYNTHETIC_AGGREGATION_REPOSITORY_VERIFIER_FINGERPRINT,
        )

    @classmethod
    def validation_receipt_id_for(
        cls,
        *,
        anchor: RepositorySealedComparisonStratumV1,
        predicate: SyntheticAggregationCollectionPredicateV1,
        enumeration: SyntheticAggregationCollectionEnumerationReceiptV1,
        aggregation_draft: RepositoryBackedSyntheticRawAggregationDraftV2,
        sealed_at: datetime,
    ) -> str:
        return _domain_digest(
            "repository-sealed-synthetic-aggregation-validation-v1",
            {
                "aggregation_draft": aggregation_draft,
                "anchor": anchor,
                "contract_version": (
                    REPOSITORY_SEALED_SYNTHETIC_AGGREGATION_VALIDATION_V1_VERSION
                ),
                "enumeration": enumeration,
                "ordered_graph_fingerprints": cls.ordered_graph_for(
                    anchor=anchor,
                    predicate=predicate,
                    enumeration=enumeration,
                    aggregation_draft=aggregation_draft,
                ),
                "predicate": predicate,
                "repository_verifier_fingerprint": (
                    SYNTHETIC_AGGREGATION_REPOSITORY_VERIFIER_FINGERPRINT
                ),
                "sealed_at": sealed_at,
            },
        )

    @model_validator(mode="after")
    def exact_repository_validation(
        self,
    ) -> RepositorySealedSyntheticAggregationValidationV1:
        anchor = RepositorySealedComparisonStratumV1.revalidate_for_persistence(
            self.anchor
        )
        predicate = SyntheticAggregationCollectionPredicateV1.revalidate_for_persistence(
            self.predicate
        )
        enumeration = (
            SyntheticAggregationCollectionEnumerationReceiptV1.revalidate_for_persistence(
                self.enumeration
            )
        )
        aggregation = (
            RepositoryBackedSyntheticRawAggregationDraftV2.revalidate_for_persistence(
                self.aggregation_draft
            )
        )
        prepared = anchor.prepared_receipt
        root = prepared.prepared_scope.history_root
        dimensions = prepared.dimensions
        if (
            predicate.anchor_sealed_stratum_id != anchor.sealed_stratum_id
            or predicate.anchor_sealed_stratum_fingerprint != anchor.fingerprint
            or predicate.anchor_prepared_stratum_id != prepared.prepared_stratum_id
            or predicate.anchor_prepared_stratum_fingerprint != prepared.fingerprint
            or predicate.root_receipt_id != root.root_receipt_id
            or predicate.root_receipt_fingerprint != root.fingerprint
            or predicate.history_floor_at != root.history_floor_at
            or predicate.installation_id != dimensions.installation_id
            or predicate.project_id != dimensions.project_id
            or predicate.provider is not dimensions.provider
            or predicate.metric_key not in prepared.prepared_scope.selection_revision.selected_metric_keys
        ):
            raise ValueError("validation query must bind the exact anchor graph")
        if predicate.as_of < anchor.sealed_at or self.sealed_at < predicate.as_of:
            raise ValueError("validation chronology must follow the anchor and query")
        if enumeration.predicate != predicate:
            raise ValueError("enumeration must descend from the exact query")
        if (
            aggregation.anchor != prepared
            or aggregation.anchor_prepared_stratum_id != prepared.prepared_stratum_id
            or aggregation.anchor_prepared_stratum_fingerprint != prepared.fingerprint
            or aggregation.root_receipt_id != root.root_receipt_id
            or aggregation.root_receipt_fingerprint != root.fingerprint
            or aggregation.installation_id != dimensions.installation_id
            or aggregation.project_id != dimensions.project_id
            or aggregation.provider is not dimensions.provider
            or aggregation.metric_key != predicate.metric_key
            or aggregation.window != predicate.window
            or aggregation.as_of != predicate.as_of
        ):
            raise ValueError("aggregation draft must derive from the exact query anchor")
        if aggregation.ordered_supplied_stratum_manifest != enumeration.ordered_members:
            raise ValueError("enumeration must equal the aggregation input manifest")
        if aggregation.supplied_strata_count != enumeration.member_count:
            raise ValueError("aggregation count must equal the complete collection")
        if aggregation.excluded_late_seal_count != 0:
            raise ValueError("repository as-of queries cannot emit late collection members")
        if self.aggregation_draft_fingerprint != aggregation.fingerprint:
            raise ValueError("validation must bind the exact aggregation draft")
        expected_graph = self.ordered_graph_for(
            anchor=anchor,
            predicate=predicate,
            enumeration=enumeration,
            aggregation_draft=aggregation,
        )
        if self.ordered_graph_fingerprints != expected_graph:
            raise ValueError("validation must commit the exact ordered graph")
        expected_id = self.validation_receipt_id_for(
            anchor=anchor,
            predicate=predicate,
            enumeration=enumeration,
            aggregation_draft=aggregation,
            sealed_at=self.sealed_at,
        )
        if self.validation_receipt_id != expected_id:
            raise ValueError("validation ID must bind the exact repository graph")
        anchor_members = tuple(
            (index, item)
            for index, item in enumerate(enumeration.ordered_members)
            if item.sealed_stratum_id == anchor.sealed_stratum_id
        )
        if len(anchor_members) != 1:
            raise ValueError("the exact anchor must appear once in the collection")
        anchor_member_index, anchor_member = anchor_members[0]
        if anchor_member != _exact_anchor_manifest_entry(anchor, anchor_member):
            raise ValueError("the anchor member must bind the complete anchor graph")
        _require_distinct_validation_roles(
            validation_receipt_id=self.validation_receipt_id,
            anchor=anchor,
            predicate=predicate,
            enumeration=enumeration,
            aggregation=aggregation,
            anchor_member_index=anchor_member_index,
        )
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class TemporalSyntheticAggregationValidationRepositoryV1(Protocol):
    """Narrow issue/replay/read boundary; no caller-authored graph writes.

    An implementation must bind the idempotency key to the exact anchor,
    metric, and window before it captures its one repository UTC ``as_of``.
    While its receipt exists, exact-key retries return the original immutable
    receipt without recapturing the clock or re-enumerating; reuse against a
    changed request fails closed before clock capture or enumeration. Privacy
    deletion atomically erases the receipt, key binding, members, and graph
    commitments without a tombstone. Later key reuse is therefore a fresh
    issuance—even for changed inputs—not a replay or remembered conflict.
    """

    def validate_synthetic_aggregation(
        self,
        anchor_sealed_stratum_id: str,
        metric_key: str,
        window: TemporalWindowSpec,
        *,
        idempotency_key_sha256: str,
    ) -> RepositorySealedSyntheticAggregationValidationV1: ...

    def get_synthetic_aggregation_validation(
        self,
        validation_receipt_id: str,
    ) -> RepositorySealedSyntheticAggregationValidationV1 | None: ...

    def get_synthetic_aggregation_validation_for_idempotency(
        self,
        idempotency_key_sha256: str,
    ) -> RepositorySealedSyntheticAggregationValidationV1 | None: ...


__all__ = [
    "REPOSITORY_SEALED_SYNTHETIC_AGGREGATION_VALIDATION_V1_VERSION",
    "SYNTHETIC_AGGREGATION_COLLECTION_ENUMERATION_V1_VERSION",
    "SYNTHETIC_AGGREGATION_COLLECTION_PREDICATE_V1_VERSION",
    "SYNTHETIC_AGGREGATION_OVERFLOW_PROBE_LIMIT",
    "SYNTHETIC_AGGREGATION_QUERY_ORDER_VERSION",
    "SYNTHETIC_AGGREGATION_QUERY_PREDICATE_VERSION",
    "SYNTHETIC_AGGREGATION_QUERY_VERIFIER_FINGERPRINT",
    "SYNTHETIC_AGGREGATION_QUERY_VERIFIER_VERSION",
    "SYNTHETIC_AGGREGATION_REPOSITORY_VERIFIER_FINGERPRINT",
    "SYNTHETIC_AGGREGATION_REPOSITORY_VERIFIER_VERSION",
    "RepositorySealedSyntheticAggregationValidationV1",
    "SyntheticAggregationCollectionEnumerationReceiptV1",
    "SyntheticAggregationCollectionPredicateV1",
    "TemporalSyntheticAggregationValidationRepositoryV1",
]
