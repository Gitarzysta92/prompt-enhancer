from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import logging
import pickle

import pytest
from pydantic import ValidationError

import prompt_enhancer.application.history.source_capture as source_capture
from prompt_enhancer.application.history.contracts import (
    ProjectMetricSelectionAuthorityKind,
    ProjectMetricSelectionRevisionV2,
    ProjectMetricSelectionSource,
    TemporalHistoryRootReceipt,
)
from prompt_enhancer.application.history.source_capture import (
    DraftMembershipAuthorityState,
    EnumeratedSelectionCoverageState,
    MAX_TEMPORAL_CAPTURE_TOTAL_UTF8_BYTES,
    MAX_TEMPORAL_SOURCE_CONTENT_CHARACTERS,
    MAX_TEMPORAL_SOURCE_ENTRIES,
    ProspectiveTemporalCaptureRequestV1,
    ProspectiveTemporalSourceDraftV1,
    SyntheticEnumerationCompletenessState,
    SyntheticLocalHmacKeyHandle,
    SyntheticTemporalSourceDraftBuilder,
    TemporalCaptureCapabilityDescriptor,
    TemporalCaptureCapabilityState,
    TemporalSourceAuthorityState,
    synthetic_temporal_source_entry_for_tests,
)
from prompt_enhancer.domain import Provider
from prompt_enhancer.infrastructure.providers.temporal_capture import (
    CODEX_TEMPORAL_CAPTURE_CAPABILITY,
    codex_temporal_capture_capability,
)


BASE = datetime(2044, 1, 2, 12, tzinfo=UTC)
LOCAL_KEY = b"reserved-private-key-canary-" + (b"x" * 5)


def _id(label: str) -> str:
    return hashlib.sha256(f"reserved-example-{label}".encode()).hexdigest()


def _root(*, label: str = "root") -> TemporalHistoryRootReceipt:
    issued_at = BASE - timedelta(hours=2)
    return TemporalHistoryRootReceipt(
        root_receipt_id=_id(label),
        project_id=_id("project"),
        epoch_ordinal=1,
        history_floor_at=issued_at,
        issued_at=issued_at,
    )


def _selection(
    root: TemporalHistoryRootReceipt | None = None,
) -> ProjectMetricSelectionRevisionV2:
    root = root or _root()
    return ProjectMetricSelectionRevisionV2(
        selection_revision_id=_id("selection"),
        root_receipt_id=root.root_receipt_id,
        root_receipt_fingerprint=root.fingerprint,
        project_id=root.project_id,
        selection_ordinal=1,
        selected_metric_keys=("efficiency", "quality"),
        source=ProjectMetricSelectionSource.EXPLICIT_PROJECT_CONFIGURATION,
        effective_at=BASE - timedelta(minutes=95),
        recorded_at=BASE - timedelta(minutes=90),
        metric_pack_key="coaching_pack",
        metric_pack_version=3,
        metric_pack_sha256=_id("metric-pack"),
        metric_catalog_version="catalog-v4",
        metric_catalog_sha256=_id("metric-catalog"),
        source_authority_kind=(
            ProjectMetricSelectionAuthorityKind.PROJECT_CONFIGURATION
        ),
        source_authority_id=_id("project-configuration"),
        source_authority_fingerprint=_id("project-configuration-fingerprint"),
        source_authority_version="project-config-v2",
    )


def _request(
    *,
    root: TemporalHistoryRootReceipt | None = None,
    selection: ProjectMetricSelectionRevisionV2 | None = None,
    requested_at: datetime = BASE,
    allowlisted_kind_codes: tuple[str, ...] = ("message", "tool"),
) -> ProspectiveTemporalCaptureRequestV1:
    root = root or _root()
    selection = selection or _selection(root)
    return ProspectiveTemporalCaptureRequestV1.for_synthetic_tests(
        history_root_receipt=root,
        selection_revision=selection,
        session_id=_id("session"),
        requested_at=requested_at,
        allowlisted_kind_codes=allowlisted_kind_codes,
        privacy_policy_version="privacy-v1",
        retention_policy_version="retention-v1",
        fingerprint_key_version="installation-key-v1",
    )


def _entry(
    ordinal: int,
    *,
    at: datetime | None = None,
    source_order: int | None = None,
    kind: str = "message",
    content: str | None = None,
    reference: str | None = None,
):
    return synthetic_temporal_source_entry_for_tests(
        source_entry_reference=reference or f"example-entry-{ordinal:04d}",
        occurred_at=at or BASE - timedelta(minutes=30 - ordinal),
        source_order=ordinal if source_order is None else source_order,
        kind_code=kind,
        normalized_redacted_content=(
            content or f"Reserved example redacted message {ordinal}."
        ),
    )


def _handle() -> SyntheticLocalHmacKeyHandle:
    return SyntheticLocalHmacKeyHandle.from_secret_for_tests(
        secret=LOCAL_KEY,
        key_version="installation-key-v1",
    )


def _build(
    *,
    request: ProspectiveTemporalCaptureRequestV1 | None = None,
    observed: tuple | None = None,
    selected: tuple | None = None,
) -> ProspectiveTemporalSourceDraftV1:
    request = request or _request()
    observed = observed if observed is not None else (_entry(1), _entry(2), _entry(3))
    selected = selected if selected is not None else observed[1:]
    return SyntheticTemporalSourceDraftBuilder(_handle()).build(
        request=request,
        observed_entries=observed,
        selected_entries=selected,
        captured_at=request.requested_at + timedelta(minutes=1),
        provider_version="fictional-provider-v1",
        provider_adapter_version="fictional-adapter-v1",
        provider_schema_version="fictional-provider-schema-v1",
        source_schema_version="fictional-source-schema-v1",
        content_schema_version="fictional-content-schema-v1",
        redactor_version="fictional-redactor-v1",
        redactor_sha256=_id("redactor"),
    )


def test_request_factory_binds_exact_root_selection_scope_and_authority() -> None:
    root = _root()
    selection = _selection(root)
    request = _request(root=root, selection=selection)

    assert request.history_root_receipt == root
    assert request.history_root_fingerprint == root.fingerprint
    assert request.history_root_receipt.epoch_ordinal == 1
    assert request.history_root_receipt.history_floor_at == root.history_floor_at
    assert request.selection_revision == selection
    assert request.selection_revision_fingerprint == selection.fingerprint
    assert request.selection_scope_fingerprint == selection.metric_set_fingerprint
    assert request.selection_revision.selected_metric_keys == ("efficiency", "quality")
    assert request.selection_revision.metric_pack_sha256 == _id("metric-pack")
    assert request.selection_revision.metric_catalog_sha256 == _id("metric-catalog")
    assert request.selection_revision.source_authority_id == _id(
        "project-configuration"
    )
    assert request.provider is Provider.SYNTHETIC
    assert request.repository_lineage_verified is False
    assert request.product_authority is False


def test_request_revalidates_model_copies_and_rejects_mismatched_lineage() -> None:
    root = _root()
    other_root = TemporalHistoryRootReceipt(
        root_receipt_id=_id("other-root"),
        project_id=root.project_id,
        epoch_ordinal=1,
        history_floor_at=root.history_floor_at,
        issued_at=root.issued_at,
    )
    with pytest.raises(ValidationError, match="exact history-root"):
        _request(root=other_root, selection=_selection(root))

    forged_root = root.model_copy(
        update={"history_floor_at": root.history_floor_at - timedelta(days=1)}
    )
    with pytest.raises(ValidationError, match="floor must equal"):
        _request(root=forged_root, selection=_selection(root))


def test_request_cannot_be_backdated_or_detached_from_derived_bindings() -> None:
    root = _root()
    selection = _selection(root)
    with pytest.raises(ValidationError, match="predate the recorded selection"):
        _request(
            root=root,
            selection=selection,
            requested_at=selection.recorded_at - timedelta(seconds=1),
        )

    backdated_selection = ProjectMetricSelectionRevisionV2(
        **{
            **selection.model_dump(),
            "effective_at": root.issued_at - timedelta(seconds=2),
            "recorded_at": root.issued_at - timedelta(seconds=1),
        }
    )
    with pytest.raises(ValidationError, match="before its history root"):
        _request(root=root, selection=backdated_selection)

    request = _request(root=root, selection=selection)
    for update in (
        {"history_root_fingerprint": _id("unrelated-root")},
        {"selection_revision_fingerprint": _id("unrelated-selection")},
        {"selection_scope_fingerprint": _id("unrelated-scope")},
        {"provider": Provider.CODEX},
    ):
        with pytest.raises(ValidationError):
            ProspectiveTemporalCaptureRequestV1.revalidate(
                request.model_copy(update=update)
            )


def test_request_allowlist_is_exact_sorted_unique_and_path_free() -> None:
    for values in (("tool", "message"), ("message", "message")):
        with pytest.raises(ValidationError, match="unique and sorted"):
            _request(allowlisted_kind_codes=values)
    for value in ("file:///reserved/private", "C:\\reserved\\private", "bad\nkind"):
        with pytest.raises(ValidationError) as raised:
            _request(allowlisted_kind_codes=(value,))
        assert value not in str(raised.value)


def test_builder_is_deterministic_role_separated_and_explicitly_untrusted() -> None:
    first = _build()
    second = _build()
    assert first == second
    assert first.fingerprint == second.fingerprint
    assert len(
        {
            first.selected_window_draft_commitment,
            first.eligible_window_draft_commitment,
            first.selected_membership_draft_commitment,
            first.analysis_window_draft_commitment,
        }
    ) == 4
    assert first.capture_request_fingerprint == first.capture_request.fingerprint
    assert first.synthetic_test_only is True
    assert first.source_authority_state is TemporalSourceAuthorityState.SYNTHETIC_TEST_ONLY
    assert first.enumeration_completeness_state is (
        SyntheticEnumerationCompletenessState.UNTRUSTED_SYNTHETIC_ENUMERATION
    )
    assert first.authoritative_enumeration_complete is False
    assert first.membership_authority_state is (
        DraftMembershipAuthorityState.UNTRUSTED_COMMITMENT_NOT_A_PROOF
    )
    assert first.product_authority is False
    assert first.repository_verified is False
    assert first.repository_issued is False
    assert first.sealed is False
    assert first.comparison_allowed is False
    assert first.snapshot_materialization_allowed is False
    assert first.activation_allowed is False


@pytest.mark.parametrize("mutation", ["content", "time", "kind", "request"])
def test_content_time_kind_and_request_changes_alter_commitments(mutation: str) -> None:
    entries = (
        _entry(1, at=BASE - timedelta(minutes=10)),
        _entry(2, at=BASE - timedelta(minutes=10)),
    )
    base = _build(observed=entries, selected=entries)
    request = _request()
    changed = entries
    if mutation == "content":
        changed = (
            _entry(
                1,
                at=entries[0].occurred_at,
                content="Different reserved example.",
            ),
            entries[1],
        )
    elif mutation == "time":
        changed = (
            _entry(1, at=entries[0].occurred_at - timedelta(seconds=1)),
            entries[1],
        )
    elif mutation == "kind":
        changed = (
            _entry(1, at=entries[0].occurred_at, kind="tool"),
            entries[1],
        )
    else:
        request = _request(requested_at=BASE + timedelta(seconds=1))
    result = _build(request=request, observed=changed, selected=changed)
    assert result.selected_window_draft_commitment != base.selected_window_draft_commitment
    assert result.eligible_window_draft_commitment != base.eligible_window_draft_commitment


def test_order_is_strict_timestamp_source_order_stable_identity_canonical() -> None:
    at = BASE - timedelta(minutes=10)
    entries = (
        _entry(1, at=at, source_order=7, reference="example-entry-a"),
        _entry(2, at=at, source_order=7, reference="example-entry-b"),
    )
    _build(observed=entries, selected=entries)
    with pytest.raises(ValueError, match="strict canonical"):
        _build(observed=tuple(reversed(entries)), selected=entries)
    with pytest.raises(ValueError, match="strict canonical"):
        _build(observed=entries, selected=tuple(reversed(entries)))


def test_duplicate_or_changed_selected_identity_fails_closed() -> None:
    entries = (_entry(1), _entry(2), _entry(3))
    with pytest.raises(ValueError, match="strict canonical|duplicate"):
        _build(observed=(entries[0], entries[0]), selected=())

    changed = _entry(
        2,
        at=entries[1].occurred_at,
        content="Changed reserved selected content.",
    )
    with pytest.raises(ValueError, match="exactly match"):
        _build(observed=entries, selected=(changed,))


def test_counts_and_coverage_are_derived_from_exact_enumerated_entries() -> None:
    request = _request()
    before = _entry(1, at=request.history_root_receipt.history_floor_at - timedelta(seconds=1))
    inside_one = _entry(2, at=BASE - timedelta(minutes=20))
    inside_two = _entry(3, at=BASE - timedelta(minutes=10))
    nonallowlisted = _entry(4, at=BASE - timedelta(minutes=5), kind="unknown_kind")
    after = _entry(5, at=request.requested_at + timedelta(seconds=1))
    observed = (before, inside_one, inside_two, nonallowlisted, after)

    complete = _build(
        request=request,
        observed=observed,
        selected=(inside_one, inside_two),
    )
    assert complete.enumerated_source_entry_count == 5
    assert complete.bounded_eligible_entry_count == 2
    assert complete.selected_entry_count == 2
    assert complete.enumerated_selection_coverage is (
        EnumeratedSelectionCoverageState.COMPLETE_ENUMERATED_SET
    )

    omitted = _build(
        request=request,
        observed=observed,
        selected=(inside_one,),
    )
    assert omitted.bounded_eligible_entry_count == 2
    assert omitted.selected_entry_count == 1
    assert omitted.enumerated_selection_coverage is (
        EnumeratedSelectionCoverageState.PARTIAL_ENUMERATED_SET
    )
    assert omitted.authoritative_enumeration_complete is False


def test_empty_enumeration_has_derived_not_applicable_coverage() -> None:
    draft = _build(observed=(), selected=())
    assert draft.enumerated_source_entry_count == 0
    assert draft.bounded_eligible_entry_count == 0
    assert draft.selected_entry_count == 0
    assert draft.enumerated_selection_coverage is (
        EnumeratedSelectionCoverageState.NOT_APPLICABLE_EMPTY_ENUMERATED_SET
    )
    assert draft.selected_window_started_at is None
    assert draft.selected_window_ended_at is None


def test_selected_noneligible_entry_is_rejected() -> None:
    request = _request()
    inside = _entry(1)
    before = _entry(
        2,
        at=request.history_root_receipt.history_floor_at - timedelta(seconds=1),
    )
    with pytest.raises(ValueError, match="exactly match"):
        _build(request=request, observed=(before, inside), selected=(before,))


def test_private_entry_is_frozen_non_pydantic_and_secret_safe(
    caplog: pytest.LogCaptureFixture,
) -> None:
    canary_reference = "reserved-secret-reference"
    canary_content = "RESERVED SECRET REDACTED CONTENT CANARY"
    entry = _entry(
        1,
        reference=canary_reference,
        content=canary_content,
    )
    assert canary_reference not in repr(entry)
    assert canary_content not in repr(entry)
    assert not hasattr(entry, "model_dump")
    assert not hasattr(entry, "model_json_schema")
    with pytest.raises(TypeError) as pickled:
        pickle.dumps(entry)
    assert canary_reference not in str(pickled.value)
    assert canary_content not in str(pickled.value)

    caplog.set_level(logging.INFO)
    logging.getLogger("synthetic.temporal").info("entry=%r", entry)
    assert canary_reference not in caplog.text
    assert canary_content not in caplog.text

    with pytest.raises(ValueError) as invalid:
        synthetic_temporal_source_entry_for_tests(
            source_entry_reference="file:///reserved/private/path",
            occurred_at=BASE,
            source_order=1,
            kind_code="message",
            normalized_redacted_content=canary_content,
        )
    assert canary_reference not in str(invalid.value)
    assert canary_content not in str(invalid.value)


@pytest.mark.parametrize("construction", ["raw_internal", "object_setattr"])
@pytest.mark.parametrize(
    ("field_name", "invalid_value", "expected_error", "secret_fragment"),
    (
        (
            "source_entry_reference",
            "file:///reserved/private/reference-canary",
            "opaque, path-free, URI-free, and email-free",
            "reference-canary",
        ),
        (
            "source_entry_reference",
            "C:\\reserved\\private\\reference-canary",
            "opaque, path-free, URI-free, and email-free",
            "reference-canary",
        ),
        (
            "source_entry_reference",
            "bad\nreference-control-canary",
            "opaque, path-free, URI-free, and email-free",
            "control-canary",
        ),
        (
            "source_entry_reference",
            "mailto:reserved@example.com",
            "opaque, path-free, URI-free, and email-free",
            "reserved@example.com",
        ),
        (
            "source_entry_reference",
            "urn:reserved:private",
            "opaque, path-free, URI-free, and email-free",
            "reserved:private",
        ),
        (
            "source_entry_reference",
            "https:example.com",
            "opaque, path-free, URI-free, and email-free",
            "example.com",
        ),
        (
            "source_entry_reference",
            "C:relative-private",
            "opaque, path-free, URI-free, and email-free",
            "relative-private",
        ),
        (
            "source_entry_reference",
            "reserved@example.com",
            "opaque, path-free, URI-free, and email-free",
            "reserved@example.com",
        ),
        (
            "occurred_at",
            datetime(2044, 1, 2, 11, 30),
            "canonical UTC",
            "2044-01-02",
        ),
        (
            "source_order",
            -1,
            "bounded non-negative integer",
            "-1",
        ),
        (
            "source_order",
            True,
            "bounded non-negative integer",
            "True",
        ),
        (
            "source_order",
            2_147_483_648,
            "bounded non-negative integer",
            "2147483648",
        ),
        (
            "kind_code",
            "file:///reserved/private/kind-canary",
            "path-free and URI-free content code",
            "kind-canary",
        ),
        (
            "kind_code",
            "bad\nkind-control-canary",
            "path-free and URI-free content code",
            "control-canary",
        ),
        (
            "normalized_redacted_content",
            "R" * (MAX_TEMPORAL_SOURCE_CONTENT_CHARACTERS + 1),
            "non-empty and bounded",
            "R" * 64,
        ),
        (
            "normalized_redacted_content",
            "private-content-control-canary\x00",
            "non-empty and bounded",
            "control-canary",
        ),
    ),
)
def test_raw_or_mutated_private_entries_are_fully_revalidated_with_value_free_errors(
    construction: str,
    field_name: str,
    invalid_value: object,
    expected_error: str,
    secret_fragment: str,
) -> None:
    values = {
        "source_entry_reference": "example-entry-0001",
        "occurred_at": BASE - timedelta(minutes=5),
        "source_order": 1,
        "kind_code": "message",
        "normalized_redacted_content": "Reserved redacted content.",
    }
    if construction == "raw_internal":
        values[field_name] = invalid_value
        entry = source_capture._TemporalSourceEntry(**values)
    else:
        entry = _entry(1)
        object.__setattr__(entry, field_name, invalid_value)

    with pytest.raises((TypeError, ValueError), match=expected_error) as raised:
        _build(observed=(entry,), selected=())
    assert secret_fragment not in str(raised.value)


def test_validation_returns_new_snapshots_isolated_from_original_mutation() -> None:
    original = _entry(1)
    snapshots = SyntheticTemporalSourceDraftBuilder._validate_entries(
        (original,), role="observed"
    )
    snapshot = snapshots[0]
    assert snapshot is not original
    expected = (
        snapshot.source_entry_reference,
        snapshot.occurred_at,
        snapshot.source_order,
        snapshot.kind_code,
        snapshot.normalized_redacted_content,
    )

    object.__setattr__(original, "source_entry_reference", "mutated-reference")
    object.__setattr__(original, "occurred_at", BASE + timedelta(days=1))
    object.__setattr__(original, "source_order", 999)
    object.__setattr__(original, "kind_code", "mutated")
    object.__setattr__(original, "normalized_redacted_content", "Mutated content.")

    assert (
        snapshot.source_entry_reference,
        snapshot.occurred_at,
        snapshot.source_order,
        snapshot.kind_code,
        snapshot.normalized_redacted_content,
    ) == expected


def test_mutating_original_during_hmac_cannot_change_validated_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline_entry = _entry(1)
    baseline = _build(
        observed=(baseline_entry,),
        selected=(baseline_entry,),
    )
    original = _entry(1)
    real_hmac_new = source_capture.hmac.new
    mutated = False

    def mutate_original_then_hash(*args, **kwargs):
        nonlocal mutated
        if not mutated:
            mutated = True
            object.__setattr__(
                original,
                "normalized_redacted_content",
                "Concurrent mutation canary.",
            )
            object.__setattr__(original, "source_entry_reference", "changed-entry")
        return real_hmac_new(*args, **kwargs)

    monkeypatch.setattr(source_capture.hmac, "new", mutate_original_then_hash)
    concurrent = _build(observed=(original,), selected=(original,))

    assert mutated is True
    assert concurrent == baseline


def test_public_draft_and_schema_have_no_secret_entries_or_proof_claim() -> None:
    draft = _build()
    serialized = draft.model_dump_json()
    schema = ProspectiveTemporalSourceDraftV1.model_json_schema()
    schema_text = str(schema)
    for forbidden in (
        "Reserved example redacted message",
        "example-entry",
        "normalized_redacted_content",
        "source_entry_reference",
        "subset_proof",
        "provider_raw_id",
        "raw_payload",
    ):
        assert forbidden not in serialized
        assert forbidden not in schema_text
    assert "_TemporalSourceEntry" not in source_capture.__all__


def test_hmac_handle_is_concrete_local_nondelegating_and_secret_safe() -> None:
    handle = _handle()
    secret_text = LOCAL_KEY.decode("ascii")
    assert secret_text not in repr(handle)
    assert secret_text not in repr(SyntheticTemporalSourceDraftBuilder(handle))
    with pytest.raises(TypeError):
        SyntheticTemporalSourceDraftBuilder(lambda payload: _id("forged"))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        class ForgedHandle(SyntheticLocalHmacKeyHandle):
            pass
    with pytest.raises(TypeError) as pickled:
        pickle.dumps(handle)
    assert secret_text not in str(pickled.value)
    assert not hasattr(source_capture, "InstallationLocalFingerprint")


def test_hmac_failures_suppress_secret_content_and_original_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_canary = "RAW-CONTENT-FAILURE-CANARY"
    entry = _entry(1, content=secret_canary)

    def fail_hmac(*args, **kwargs):
        raise RuntimeError(f"provider leaked {secret_canary}")

    monkeypatch.setattr(source_capture.hmac, "new", fail_hmac)
    with pytest.raises(RuntimeError, match="local synthetic commitment failed") as raised:
        _build(observed=(entry,), selected=(entry,))
    assert secret_canary not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_entry_count_bound_is_enforced_before_any_hashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = tuple(
        _entry(
            ordinal,
            at=BASE - timedelta(minutes=10),
            source_order=ordinal,
        )
        for ordinal in range(MAX_TEMPORAL_SOURCE_ENTRIES + 1)
    )
    called = False

    def should_not_hash(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("hashing occurred before the count gate")

    monkeypatch.setattr(source_capture.hmac, "new", should_not_hash)
    with pytest.raises(ValueError, match="entry count exceeds"):
        _build(observed=entries, selected=())
    assert called is False


def test_aggregate_byte_bound_is_enforced_before_any_hashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry_count = (
        MAX_TEMPORAL_CAPTURE_TOTAL_UTF8_BYTES
        // MAX_TEMPORAL_SOURCE_CONTENT_CHARACTERS
    ) + 1
    content = "R" * MAX_TEMPORAL_SOURCE_CONTENT_CHARACTERS
    entries = tuple(
        _entry(
            ordinal,
            at=BASE - timedelta(minutes=10),
            source_order=ordinal,
            content=content,
        )
        for ordinal in range(entry_count)
    )
    called = False

    def should_not_hash(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("hashing occurred before the byte gate")

    monkeypatch.setattr(source_capture.hmac, "new", should_not_hash)
    with pytest.raises(ValueError, match="aggregate local byte bound"):
        _build(observed=entries, selected=())
    assert called is False


def test_per_entry_limits_and_private_identifiers_are_fail_closed() -> None:
    with pytest.raises(ValueError, match="non-empty and bounded"):
        _entry(1, content="R" * (MAX_TEMPORAL_SOURCE_CONTENT_CHARACTERS + 1))
    with pytest.raises(ValueError, match="bounded non-negative"):
        _entry(1, source_order=-1)
    for reference in (
        "file:///reserved/private",
        "C:\\reserved\\private",
        "reserved/private",
        "bad\nreference",
        "mailto:reserved@example.com",
        "urn:reserved:private",
        "https:example.com",
        "C:relative-private",
        "reserved@example.com",
    ):
        with pytest.raises(ValueError) as raised:
            _entry(1, reference=reference)
        assert reference not in str(raised.value)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("provider_version", "file:///reserved/private"),
        ("source_schema_version", "C:\\reserved\\private"),
        ("content_schema_version", "schema-v1\nprivate"),
    ),
)
def test_public_versions_reject_uri_path_and_control_text(
    field: str, value: str
) -> None:
    request = _request()
    kwargs = {
        "request": request,
        "observed_entries": (_entry(1),),
        "selected_entries": (_entry(1),),
        "captured_at": request.requested_at + timedelta(seconds=1),
        "provider_version": "fictional-provider-v1",
        "provider_adapter_version": "fictional-adapter-v1",
        "provider_schema_version": "fictional-provider-schema-v1",
        "source_schema_version": "fictional-source-schema-v1",
        "content_schema_version": "fictional-content-schema-v1",
        "redactor_version": "fictional-redactor-v1",
        "redactor_sha256": _id("redactor"),
    }
    kwargs[field] = value
    with pytest.raises(ValidationError) as raised:
        SyntheticTemporalSourceDraftBuilder(_handle()).build(**kwargs)
    assert value not in str(raised.value)


def test_recursive_copy_revalidation_blocks_every_trust_promotion() -> None:
    draft = _build()
    forged_request = draft.capture_request.model_copy(
        update={"repository_lineage_verified": True}
    )
    for update in (
        {"capture_request": forged_request},
        {"product_authority": True},
        {"repository_verified": True},
        {"repository_issued": True},
        {"sealed": True},
        {"comparison_allowed": True},
        {"snapshot_materialization_allowed": True},
        {"activation_allowed": True},
        {"authoritative_enumeration_complete": True},
        {
            "bounded_eligible_entry_count": 3,
            "selected_entry_count": 1,
            "enumerated_selection_coverage": (
                EnumeratedSelectionCoverageState.COMPLETE_ENUMERATED_SET
            ),
        },
    ):
        with pytest.raises(ValidationError):
            ProspectiveTemporalSourceDraftV1.revalidate(
                draft.model_copy(update=update)
            )


def test_no_public_v2_mapping_or_documented_authority_path_exists() -> None:
    draft = _build()
    assert not hasattr(draft, "to_analysis_input_receipt_v2_fields")
    assert not hasattr(source_capture, "AnalysisInputReceiptV2DraftProvenance")
    assert list(TemporalSourceAuthorityState) == [
        TemporalSourceAuthorityState.SYNTHETIC_TEST_ONLY
    ]
    with pytest.raises(ValidationError):
        ProspectiveTemporalCaptureRequestV1(
            **{
                **_request().model_dump(),
                "provider": Provider.CODEX,
            }
        )


def test_codex_capability_is_unavailable_and_cannot_be_promoted() -> None:
    descriptor = codex_temporal_capture_capability()
    assert descriptor == CODEX_TEMPORAL_CAPTURE_CAPABILITY
    assert descriptor.provider is Provider.CODEX
    assert descriptor.capability_state is (
        TemporalCaptureCapabilityState.UNAVAILABLE_MISSING_AUTHORITATIVE_ITEM_TIMESTAMPS
    )
    assert descriptor.authoritative_item_timestamps_available is False
    assert descriptor.provider_snapshot_boundary_available is False
    assert descriptor.provider_cursor_boundary_available is False
    assert descriptor.trusted_adapter_issuance_implemented is False
    assert descriptor.trusted_repository_issuance_implemented is False
    assert descriptor.product_capture_allowed is False
    assert descriptor.product_authority is False
    assert list(TemporalCaptureCapabilityState) == [
        TemporalCaptureCapabilityState.UNAVAILABLE_MISSING_AUTHORITATIVE_ITEM_TIMESTAMPS
    ]
    assert set(descriptor.prohibited_timestamp_substitutions) == {
        "capture_timestamp",
        "list_timestamp",
        "read_clock",
        "session_created_at",
        "session_timestamp",
        "session_updated_at",
        "turn_order",
        "turn_timestamp",
    }
    for update in (
        {"authoritative_item_timestamps_available": True},
        {"provider_snapshot_boundary_available": True},
        {"trusted_adapter_issuance_implemented": True},
        {"product_capture_allowed": True},
        {"product_authority": True},
    ):
        with pytest.raises(ValidationError):
            TemporalCaptureCapabilityDescriptor.revalidate(
                descriptor.model_copy(update=update)
            )


def test_capture_time_and_key_version_fail_before_source_commitment() -> None:
    request = _request()
    entry = _entry(1)
    with pytest.raises(ValueError, match="cannot predate"):
        SyntheticTemporalSourceDraftBuilder(_handle()).build(
            request=request,
            observed_entries=(entry,),
            selected_entries=(entry,),
            captured_at=request.requested_at - timedelta(seconds=1),
            provider_version="provider-v1",
            provider_adapter_version="adapter-v1",
            provider_schema_version="provider-schema-v1",
            source_schema_version="source-schema-v1",
            content_schema_version="content-schema-v1",
            redactor_version="redactor-v1",
            redactor_sha256=_id("redactor"),
        )
    wrong_key = SyntheticLocalHmacKeyHandle.from_secret_for_tests(
        secret=LOCAL_KEY,
        key_version="different-key-v1",
    )
    with pytest.raises(ValueError, match="key version must match"):
        SyntheticTemporalSourceDraftBuilder(wrong_key).build(
            request=request,
            observed_entries=(entry,),
            selected_entries=(entry,),
            captured_at=request.requested_at,
            provider_version="provider-v1",
            provider_adapter_version="adapter-v1",
            provider_schema_version="provider-schema-v1",
            source_schema_version="source-schema-v1",
            content_schema_version="content-schema-v1",
            redactor_version="redactor-v1",
            redactor_sha256=_id("redactor"),
        )
