from __future__ import annotations

from datetime import timedelta
import inspect
from pathlib import Path

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.history import aggregation as aggregation_contracts
from prompt_enhancer.application.history import aggregation_persistence as contracts
from prompt_enhancer.application.history.aggregation import (
    MAX_SUPPLIED_STRATA,
    RawStratumDispositionV1,
    RepositoryBackedSyntheticRawAggregationDraftV2,
    draft_repository_sealed_synthetic_raw_aggregation,
)
from prompt_enhancer.application.history.aggregation_persistence import (
    SYNTHETIC_AGGREGATION_OVERFLOW_PROBE_LIMIT,
    SYNTHETIC_AGGREGATION_QUERY_VERIFIER_FINGERPRINT,
    SYNTHETIC_AGGREGATION_REPOSITORY_VERIFIER_FINGERPRINT,
    RepositorySealedSyntheticAggregationValidationV1,
    SyntheticAggregationCollectionEnumerationReceiptV1,
    SyntheticAggregationCollectionPredicateV1,
    TemporalSyntheticAggregationValidationRepositoryV1,
)
from tests import test_temporal_repository_aggregation as fixtures


def _id(label: str) -> str:
    return fixtures.base._id(f"aggregation-validation:{label}")


def _validation(
    *receipts,
    anchor=None,
    window=None,
    as_of=None,
    sealed_at=None,
    idempotency_key_sha256: str | None = None,
) -> RepositorySealedSyntheticAggregationValidationV1:
    exact_anchor = anchor or receipts[0]
    exact_window = window or fixtures._window()
    exact_as_of = as_of or fixtures.AS_OF
    key = idempotency_key_sha256 or _id("default-idempotency-key")
    predicate = SyntheticAggregationCollectionPredicateV1.from_repository_query(
        idempotency_key_sha256=key,
        anchor=exact_anchor,
        metric_key=fixtures.base.METRIC,
        window=exact_window,
        as_of=exact_as_of,
    )
    draft = draft_repository_sealed_synthetic_raw_aggregation(
        anchor=exact_anchor.prepared_receipt,
        metric_key=fixtures.base.METRIC,
        window=exact_window,
        as_of=exact_as_of,
        strata=tuple(receipts),
    )
    members = draft.ordered_supplied_stratum_manifest
    enumeration = SyntheticAggregationCollectionEnumerationReceiptV1(
        enumeration_id=(
            SyntheticAggregationCollectionEnumerationReceiptV1.enumeration_id_for(
                predicate=predicate,
                ordered_members=members,
            )
        ),
        predicate=predicate,
        predicate_fingerprint=predicate.fingerprint,
        ordered_members=members,
        member_count=len(members),
    )
    exact_sealed_at = sealed_at or exact_as_of + timedelta(microseconds=1)
    graph = RepositorySealedSyntheticAggregationValidationV1.ordered_graph_for(
        anchor=exact_anchor,
        predicate=predicate,
        enumeration=enumeration,
        aggregation_draft=draft,
    )
    return RepositorySealedSyntheticAggregationValidationV1(
        validation_receipt_id=(
            RepositorySealedSyntheticAggregationValidationV1.validation_receipt_id_for(
                anchor=exact_anchor,
                predicate=predicate,
                enumeration=enumeration,
                aggregation_draft=draft,
                sealed_at=exact_sealed_at,
            )
        ),
        anchor=exact_anchor,
        predicate=predicate,
        enumeration=enumeration,
        aggregation_draft=draft,
        aggregation_draft_fingerprint=draft.fingerprint,
        ordered_graph_fingerprints=graph,
        sealed_at=exact_sealed_at,
    )


def _enumeration(
    predicate: SyntheticAggregationCollectionPredicateV1,
    members,
) -> SyntheticAggregationCollectionEnumerationReceiptV1:
    exact_members = tuple(members)
    return SyntheticAggregationCollectionEnumerationReceiptV1(
        enumeration_id=(
            SyntheticAggregationCollectionEnumerationReceiptV1.enumeration_id_for(
                predicate=predicate,
                ordered_members=exact_members,
            )
        ),
        predicate=predicate,
        predicate_fingerprint=predicate.fingerprint,
        ordered_members=exact_members,
        member_count=len(exact_members),
    )


def _draft_with_manifest(
    draft: RepositoryBackedSyntheticRawAggregationDraftV2,
    members,
) -> RepositoryBackedSyntheticRawAggregationDraftV2:
    exact_members = tuple(members)
    fields = draft.model_dump(mode="python", exclude={"aggregation_draft_id"})
    fields["ordered_supplied_stratum_manifest"] = tuple(
        item.model_dump(mode="python") for item in exact_members
    )
    fields["ordered_included_stratum_fingerprints"] = tuple(
        sorted(
            item.sealed_stratum_fingerprint
            for item in exact_members
            if item.disposition is RawStratumDispositionV1.INCLUDED
        )
    )
    draft_id = aggregation_contracts._repository_aggregation_draft_id(fields)
    return RepositoryBackedSyntheticRawAggregationDraftV2(
        aggregation_draft_id=draft_id,
        **fields,
    )


def _outer_from_parts(
    *,
    anchor,
    predicate: SyntheticAggregationCollectionPredicateV1,
    enumeration: SyntheticAggregationCollectionEnumerationReceiptV1,
    draft: RepositoryBackedSyntheticRawAggregationDraftV2,
    sealed_at,
) -> RepositorySealedSyntheticAggregationValidationV1:
    graph = RepositorySealedSyntheticAggregationValidationV1.ordered_graph_for(
        anchor=anchor,
        predicate=predicate,
        enumeration=enumeration,
        aggregation_draft=draft,
    )
    receipt_id = (
        RepositorySealedSyntheticAggregationValidationV1.validation_receipt_id_for(
            anchor=anchor,
            predicate=predicate,
            enumeration=enumeration,
            aggregation_draft=draft,
            sealed_at=sealed_at,
        )
    )
    return RepositorySealedSyntheticAggregationValidationV1(
        validation_receipt_id=receipt_id,
        anchor=anchor,
        predicate=predicate,
        enumeration=enumeration,
        aggregation_draft=draft,
        aggregation_draft_fingerprint=draft.fingerprint,
        ordered_graph_fingerprints=graph,
        sealed_at=sealed_at,
    )


def _canonical_reordinal(members):
    ordered = sorted(
        members,
        key=lambda item: (
            item.effective_at,
            item.session_id,
            item.revision_ordinal,
            item.revision_id,
            item.sealed_stratum_id,
        ),
    )
    return tuple(
        item.model_copy(update={"supplied_ordinal": ordinal})
        for ordinal, item in enumerate(ordered)
    )


def test_single_and_multi_member_validations_bind_the_exact_repository_graph() -> None:
    first = fixtures._receipt("validation-first")
    second = fixtures._receipt("validation-second")

    single = _validation(first)
    multi = _validation(second, first, anchor=first)

    assert single.enumeration.member_count == 1
    assert multi.enumeration.member_count == 2
    assert multi.enumeration.ordered_members == (
        multi.aggregation_draft.ordered_supplied_stratum_manifest
    )
    assert multi.aggregation_draft.supplied_strata_count == 2
    assert multi.aggregation_draft.excluded_late_seal_count == 0
    assert multi.predicate.anchor_sealed_stratum_id == first.sealed_stratum_id
    assert sum(
        item.sealed_stratum_id == first.sealed_stratum_id
        for item in multi.enumeration.ordered_members
    ) == 1
    assert multi.ordered_graph_fingerprints[-1] == (
        SYNTHETIC_AGGREGATION_REPOSITORY_VERIFIER_FINGERPRINT
    )
    assert RepositorySealedSyntheticAggregationValidationV1.revalidate_for_persistence(
        multi
    ) == multi


def test_protocol_is_narrow_and_caller_controls_only_request_identity() -> None:
    issue = inspect.signature(
        TemporalSyntheticAggregationValidationRepositoryV1.validate_synthetic_aggregation
    )
    assert tuple(issue.parameters) == (
        "self",
        "anchor_sealed_stratum_id",
        "metric_key",
        "window",
        "idempotency_key_sha256",
    )
    assert issue.parameters["idempotency_key_sha256"].kind is (
        inspect.Parameter.KEYWORD_ONLY
    )
    forbidden = {
        "as_of",
        "strata",
        "project_id",
        "installation_id",
        "provider",
        "verifier",
    }
    assert forbidden.isdisjoint(issue.parameters)

    exact_getter = inspect.signature(
        TemporalSyntheticAggregationValidationRepositoryV1.get_synthetic_aggregation_validation
    )
    replay_getter = inspect.signature(
        TemporalSyntheticAggregationValidationRepositoryV1.get_synthetic_aggregation_validation_for_idempotency
    )
    assert tuple(exact_getter.parameters) == ("self", "validation_receipt_id")
    assert tuple(replay_getter.parameters) == (
        "self",
        "idempotency_key_sha256",
    )


def test_code_owned_versions_and_verifier_fingerprints_are_frozen() -> None:
    assert contracts.SYNTHETIC_AGGREGATION_COLLECTION_PREDICATE_V1_VERSION == (
        "synthetic-aggregation-sealed-stratum-query-v1"
    )
    assert contracts.SYNTHETIC_AGGREGATION_COLLECTION_ENUMERATION_V1_VERSION == (
        "synthetic-aggregation-collection-enumeration-v1"
    )
    assert (
        contracts.REPOSITORY_SEALED_SYNTHETIC_AGGREGATION_VALIDATION_V1_VERSION
        == "repository-sealed-synthetic-aggregation-validation-v1"
    )
    assert contracts.SYNTHETIC_AGGREGATION_QUERY_PREDICATE_VERSION == (
        "same-root-source-sealed-at-inclusive-v1"
    )
    assert contracts.SYNTHETIC_AGGREGATION_QUERY_VERIFIER_VERSION == (
        "synthetic-aggregation-query-verifier-v1"
    )
    assert contracts.SYNTHETIC_AGGREGATION_REPOSITORY_VERIFIER_VERSION == (
        "synthetic-aggregation-repository-verifier-v1"
    )
    assert SYNTHETIC_AGGREGATION_QUERY_VERIFIER_FINGERPRINT == (
        "78cfe772de8614c767ea212095e6ce0c92bed039e431d9d758e8b78a6e296568"
    )
    assert SYNTHETIC_AGGREGATION_REPOSITORY_VERIFIER_FINGERPRINT == (
        "025747d6c4714c4111ba42c8bd8c331a7b686317e105f1037f1c91a350690822"
    )
    assert SYNTHETIC_AGGREGATION_QUERY_VERIFIER_FINGERPRINT != (
        SYNTHETIC_AGGREGATION_REPOSITORY_VERIFIER_FINGERPRINT
    )


def test_idempotency_key_is_strict_and_binds_query_enumeration_and_validation() -> None:
    receipt = fixtures._receipt("idempotency")
    left = _validation(receipt, idempotency_key_sha256=_id("key-a"))
    replay = _validation(receipt, idempotency_key_sha256=_id("key-a"))
    right = _validation(receipt, idempotency_key_sha256=_id("key-b"))

    assert replay == left
    assert right.aggregation_draft == left.aggregation_draft
    assert right.predicate.query_id != left.predicate.query_id
    assert right.predicate.fingerprint != left.predicate.fingerprint
    assert right.enumeration.enumeration_id != left.enumeration.enumeration_id
    assert right.validation_receipt_id != left.validation_receipt_id
    assert left.idempotent_issue_while_receipt_exists_guaranteed is True
    assert left.privacy_deletion_revokes_replay_history is True
    assert left.privacy_deletion_erases_idempotency_binding is True
    assert left.privacy_deletion_retains_idempotency_tombstone is False

    conflicting_request = (
        SyntheticAggregationCollectionPredicateV1.from_repository_query(
            idempotency_key_sha256=_id("key-a"),
            anchor=receipt,
            metric_key=fixtures.base.METRIC,
            window=fixtures._window(last_n=1),
            as_of=fixtures.AS_OF,
        )
    )
    assert conflicting_request.idempotency_key_sha256 == (
        left.predicate.idempotency_key_sha256
    )
    assert conflicting_request.query_id != left.predicate.query_id
    assert conflicting_request.fingerprint != left.predicate.fingerprint

    with pytest.raises(ValidationError):
        SyntheticAggregationCollectionPredicateV1.revalidate_for_persistence(
            left.predicate.model_copy(
                update={"idempotency_key_sha256": _id("conflicting-key")}
            )
        )
    with pytest.raises(ValueError):
        SyntheticAggregationCollectionPredicateV1.from_repository_query(
            idempotency_key_sha256="not-a-digest",
            anchor=receipt,
            metric_key=fixtures.base.METRIC,
            window=fixtures._window(),
            as_of=fixtures.AS_OF,
        )


def test_query_recursive_tampering_rejects() -> None:
    validation = _validation(fixtures._receipt("query-tamper"))
    predicate = validation.predicate
    attacks = (
        predicate.model_copy(update={"query_id": _id("forged-query")}),
        predicate.model_copy(update={"metric_key": "other.metric"}),
        predicate.model_copy(update={"caller_as_of_allowed": True}),
        predicate.model_copy(update={"remote_processing_allowed": True}),
    )
    for attack in attacks:
        with pytest.raises(ValidationError):
            SyntheticAggregationCollectionPredicateV1.revalidate_for_persistence(
                attack
            )


def test_enumeration_is_complete_canonical_bounded_and_recursively_revalidated() -> None:
    first = fixtures._receipt("enumeration-first")
    second = fixtures._receipt("enumeration-second")
    validation = _validation(second, first, anchor=first)
    enumeration = validation.enumeration

    assert tuple(item.supplied_ordinal for item in enumeration.ordered_members) == (
        0,
        1,
    )
    assert enumeration.member_count == len(enumeration.ordered_members)
    assert enumeration.overflow_detected is False
    assert enumeration.max_plus_one_probe_performed is True
    assert enumeration.bounded_sealed_stratum_collection_complete is True
    assert enumeration.repository_transaction_snapshot_used is True
    assert enumeration.predicate.maximum_member_count == MAX_SUPPLIED_STRATA
    assert enumeration.predicate.overflow_probe_limit == MAX_SUPPLIED_STRATA + 1
    assert SYNTHETIC_AGGREGATION_OVERFLOW_PROBE_LIMIT == MAX_SUPPLIED_STRATA + 1
    schema = SyntheticAggregationCollectionEnumerationReceiptV1.model_json_schema()
    assert schema["properties"]["ordered_members"]["maxItems"] == MAX_SUPPLIED_STRATA
    graph_schema = RepositorySealedSyntheticAggregationValidationV1.model_json_schema()
    assert graph_schema["properties"]["ordered_graph_fingerprints"]["minItems"] == 8
    assert graph_schema["properties"]["ordered_graph_fingerprints"]["maxItems"] == (
        MAX_SUPPLIED_STRATA + 7
    )

    with pytest.raises(ValidationError):
        _enumeration(enumeration.predicate, ())
    with pytest.raises(ValidationError):
        _enumeration(
            enumeration.predicate,
            tuple(reversed(enumeration.ordered_members)),
        )
    with pytest.raises(ValidationError):
        SyntheticAggregationCollectionEnumerationReceiptV1.revalidate_for_persistence(
            enumeration.model_copy(
                update={"predicate_fingerprint": _id("forged-predicate")}
            )
        )
    forged_member = enumeration.ordered_members[0].model_copy(
        update={"sealed_at": enumeration.predicate.as_of + timedelta(seconds=1)}
    )
    with pytest.raises(ValidationError):
        _enumeration(
            enumeration.predicate,
            (forged_member, *enumeration.ordered_members[1:]),
        )


def test_enumeration_rejects_duplicate_repository_roles_and_coordinates() -> None:
    validation = _validation(fixtures._receipt("duplicate-member"))
    member = validation.enumeration.ordered_members[0]
    duplicate = member.model_copy(update={"supplied_ordinal": 1})

    with pytest.raises(ValidationError):
        _enumeration(validation.predicate, (member, duplicate))


def test_enumeration_rejects_mutable_member_collections_before_coercion() -> None:
    validation = _validation(fixtures._receipt("mutable-members"))
    fields = validation.enumeration.model_dump(mode="python")
    fields["ordered_members"] = list(validation.enumeration.ordered_members)

    with pytest.raises(ValidationError):
        SyntheticAggregationCollectionEnumerationReceiptV1(**fields)
    with pytest.raises(ValidationError):
        SyntheticAggregationCollectionEnumerationReceiptV1.revalidate_for_persistence(
            fields
        )


def test_enumeration_overflow_fails_before_any_nested_member_access() -> None:
    class Poison:
        def __getattribute__(self, name: str):
            raise AssertionError("overflow preflight accessed a nested member")

    validation = _validation(fixtures._receipt("overflow-preflight"))
    fields = validation.enumeration.model_dump(mode="python")
    fields["ordered_members"] = tuple(
        Poison() for _ in range(MAX_SUPPLIED_STRATA + 1)
    )
    fields["member_count"] = MAX_SUPPLIED_STRATA

    with pytest.raises(ValidationError):
        SyntheticAggregationCollectionEnumerationReceiptV1(**fields)
    with pytest.raises(ValidationError):
        SyntheticAggregationCollectionEnumerationReceiptV1.revalidate_for_persistence(
            fields
        )


def test_enumeration_rejects_each_duplicate_member_identity_and_fingerprint_role() -> None:
    first = fixtures._receipt("role-first")
    second = fixtures._receipt("role-second")
    validation = _validation(first, second, anchor=first)
    members = validation.enumeration.ordered_members
    left, right = members
    duplicate_fields = (
        "prepared_stratum_id",
        "prepared_stratum_fingerprint",
        "sealed_stratum_id",
        "sealed_stratum_fingerprint",
        "analysis_run_id",
        "analysis_run_authority_sha256",
        "sealed_batch_id",
        "sealed_batch_sha256",
        "revision_id",
        "revision_fingerprint",
    )
    for field_name in duplicate_fields:
        attacked = right.model_copy(
            update={field_name: getattr(left, field_name)}
        )
        with pytest.raises(ValidationError):
            _enumeration(
                validation.predicate,
                _canonical_reordinal((left, attacked)),
            )

    coordinate_collision = right.model_copy(
        update={
            "session_id": left.session_id,
            "revision_ordinal": left.revision_ordinal,
        }
    )
    with pytest.raises(ValidationError):
        _enumeration(
            validation.predicate,
            _canonical_reordinal((left, coordinate_collision)),
        )


def test_anchor_member_must_equal_the_full_exact_anchor_manifest_not_only_its_id() -> None:
    validation = _validation(fixtures._receipt("anchor-manifest"))
    member = validation.enumeration.ordered_members[0]
    forged_member = member.model_copy(
        update={"sealed_stratum_fingerprint": _id("forged-anchor-fingerprint")}
    )
    forged_draft = _draft_with_manifest(
        validation.aggregation_draft,
        (forged_member,),
    )
    forged_enumeration = _enumeration(validation.predicate, (forged_member,))

    with pytest.raises(ValidationError):
        _outer_from_parts(
            anchor=validation.anchor,
            predicate=validation.predicate,
            enumeration=forged_enumeration,
            draft=forged_draft,
            sealed_at=validation.sealed_at,
        )


def test_global_role_separation_rejects_nested_member_collisions() -> None:
    receipt = fixtures._receipt("nested-key-collision")
    with pytest.raises(ValidationError):
        _validation(
            receipt,
            idempotency_key_sha256=receipt.analysis_run.draft.run_id,
        )

    anchor = fixtures._receipt("nested-anchor")
    other = fixtures._receipt("nested-other")
    validation = _validation(anchor, other, anchor=anchor)
    members = validation.enumeration.ordered_members
    anchor_member = next(
        item
        for item in members
        if item.sealed_stratum_id == anchor.sealed_stratum_id
    )
    other_member = next(item for item in members if item is not anchor_member)
    collided = other_member.model_copy(
        update={
            "analysis_run_authority_sha256": other_member.sealed_batch_sha256
        }
    )
    forged_members = _canonical_reordinal((anchor_member, collided))
    forged_draft = _draft_with_manifest(
        validation.aggregation_draft,
        forged_members,
    )
    forged_enumeration = _enumeration(validation.predicate, forged_members)

    with pytest.raises(ValidationError):
        _outer_from_parts(
            anchor=anchor,
            predicate=validation.predicate,
            enumeration=forged_enumeration,
            draft=forged_draft,
            sealed_at=validation.sealed_at,
        )


def test_as_of_is_inclusive_and_validation_seal_chronology_is_exact() -> None:
    receipt = fixtures._receipt("inclusive-seal")
    exact_as_of = receipt.sealed_at
    validation = _validation(
        receipt,
        window=fixtures._window(last_n=1),
        as_of=exact_as_of,
        sealed_at=exact_as_of,
    )

    assert validation.predicate.sealed_at_inclusive is True
    assert validation.enumeration.ordered_members[0].sealed_at == exact_as_of
    assert validation.aggregation_draft.excluded_late_seal_count == 0
    assert validation.sealed_at == exact_as_of

    earlier = validation.predicate.as_of - timedelta(microseconds=1)
    forged_id = RepositorySealedSyntheticAggregationValidationV1.validation_receipt_id_for(
        anchor=validation.anchor,
        predicate=validation.predicate,
        enumeration=validation.enumeration,
        aggregation_draft=validation.aggregation_draft,
        sealed_at=earlier,
    )
    with pytest.raises(ValidationError):
        RepositorySealedSyntheticAggregationValidationV1(
            **validation.model_dump(
                mode="python",
                exclude={"validation_receipt_id", "sealed_at"},
            ),
            validation_receipt_id=forged_id,
            sealed_at=earlier,
        )


def test_outer_receipt_rejects_graph_nested_draft_and_capability_tampering() -> None:
    validation = _validation(fixtures._receipt("outer-tamper"))
    forged_draft = validation.aggregation_draft.model_copy(
        update={"repository_owned": True}
    )
    attacks = (
        validation.model_copy(
            update={"validation_receipt_id": _id("forged-validation")}
        ),
        validation.model_copy(
            update={
                "ordered_graph_fingerprints": tuple(
                    reversed(validation.ordered_graph_fingerprints)
                )
            }
        ),
        validation.model_copy(update={"aggregation_draft": forged_draft}),
        validation.model_copy(update={"aggregate_materialization_allowed": True}),
        validation.model_copy(update={"sealed": False}),
        validation.model_copy(
            update={"idempotent_issue_while_receipt_exists_guaranteed": False}
        ),
        validation.model_copy(
            update={"privacy_deletion_revokes_replay_history": False}
        ),
        validation.model_copy(
            update={"privacy_deletion_erases_idempotency_binding": False}
        ),
        validation.model_copy(
            update={"privacy_deletion_retains_idempotency_tombstone": True}
        ),
    )
    for attack in attacks:
        with pytest.raises(ValidationError):
            RepositorySealedSyntheticAggregationValidationV1.revalidate_for_persistence(
                attack
            )


def test_semantic_digest_roles_cannot_collide() -> None:
    receipt = fixtures._receipt("role-collision")
    with pytest.raises(ValidationError):
        _validation(
            receipt,
            idempotency_key_sha256=(
                SYNTHETIC_AGGREGATION_QUERY_VERIFIER_FINGERPRINT
            ),
        )


def test_authority_only_changes_move_every_repository_validation_identity() -> None:
    varied = frozenset(
        {
            "analysis-job",
            "analysis-job-dedupe",
            "lease-owner-base",
            "lease-token-base",
            "expected-run-receipt",
            "automation-revalidation-receipt",
            "repository-revalidation-authority",
        }
    )
    first = fixtures._receipt("authority-left", varied_labels=varied)
    second = fixtures._receipt("authority-right", varied_labels=varied)
    left = _validation(first, idempotency_key_sha256=_id("authority-key"))
    right = _validation(second, idempotency_key_sha256=_id("authority-key"))

    assert fixtures._aggregate(left.aggregation_draft).ratio == 1.0
    assert fixtures._aggregate(right.aggregation_draft).ratio == 1.0
    assert left.aggregation_draft.included_revision_count == 1
    assert right.aggregation_draft.included_revision_count == 1
    assert left.predicate.query_id != right.predicate.query_id
    assert left.enumeration.enumeration_id != right.enumeration.enumeration_id
    assert left.aggregation_draft.aggregation_draft_id != (
        right.aggregation_draft.aggregation_draft_id
    )
    assert left.validation_receipt_id != right.validation_receipt_id


def test_capability_ceiling_preserves_embedded_draft_as_unsealed_and_unowned() -> None:
    validation = _validation(fixtures._receipt("capability-ceiling"))
    allowed_true = {
        "repository_return_required",
        "structurally_constructible_not_capability",
        "synthetic_test_only",
        "repository_owned",
        "repository_graph_verified",
        "repository_enumeration_performed",
        "bounded_sealed_stratum_collection_complete",
        "sealed",
        "idempotent_issue_while_receipt_exists_guaranteed",
        "privacy_deletion_revokes_replay_history",
        "privacy_deletion_erases_idempotency_binding",
    }
    for name in type(validation).model_fields:
        value = getattr(validation, name)
        if isinstance(value, bool):
            assert value is (name in allowed_true), name

    draft = validation.aggregation_draft
    assert isinstance(draft, RepositoryBackedSyntheticRawAggregationDraftV2)
    assert draft.repository_owned is False
    assert draft.repository_verified is False
    assert draft.repository_enumeration_performed is False
    assert draft.collection_completeness_verified is False
    assert draft.comparison_stratum_complete is False
    assert draft.sealed is False
    for name in (
        "population_completeness_verified",
        "product_history_completeness_verified",
        "source_authority_verified",
        "product_capture_allowed",
        "product_history_eligible",
        "comparison_allowed",
        "pair_matching_allowed",
        "aggregate_materialization_allowed",
        "snapshot_materialization_allowed",
        "recommendation_allowed",
        "recommendation_outcome_evaluation_allowed",
        "causal_claim_allowed",
        "activation_allowed",
        "legacy_inference_allowed",
        "backfill_allowed",
        "remote_processing_allowed",
        "private_export_allowed",
        "team_share_allowed",
    ):
        assert getattr(validation, name) is False, name


def test_serialization_is_content_free_and_temporal_snapshot_is_absent() -> None:
    validation = _validation(fixtures._receipt("serialization"))
    serialized = validation.model_dump_json()
    for forbidden in (
        "prompt_text",
        "source_text",
        "transcript",
        "messages",
        "file://",
        "https://",
        "@example",
    ):
        assert forbidden not in serialized
    assert validation.contains_local_content is False
    assert validation.predicate.contains_local_content is False
    assert validation.enumeration.contains_local_content is False
    assert validation.aggregation_draft.contains_local_content is False

    source = Path(contracts.__file__).read_text(encoding="utf-8")
    assert "TemporalSnapshot" not in source
    assert not any(name.startswith("TemporalSnapshot") for name in contracts.__all__)
