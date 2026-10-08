"""Synthetic durability and attack tests for the paid-product SQLite adapter."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
import sqlite3
from threading import Event

import pytest
from pydantic import SecretStr

from prompt_enhancer.application.paid_product.contracts import (
    Account,
    AccountIdentityBinding,
    ApprovalState,
    DeepAnalysisJob,
    DeepAnalysisRequest,
    DeepJobState,
    DEVELOPMENT_PRODUCT_READINESS,
    EntitlementDeltaKind,
    EntitlementFeature,
    OrganizationSpendPolicy,
    PaidPrincipal,
    PaidReasonCode,
    PaidScope,
    ProductDeploymentProfile,
    RemoteAnalysisApproval,
    RetentionClass,
    SignedBillingWebhook,
    SpendHoldState,
    SpendPolicy,
    TenantAccountBinding,
    TenantJobDestination,
    WebhookDisposition,
)
from prompt_enhancer.application.paid_product.errors import (
    ApprovalError,
    PaidAuthorizationError,
)
from prompt_enhancer.application.paid_product.services import (
    ApprovalService,
    BillingService,
    DeepAnalysisService,
)
from prompt_enhancer.infrastructure.paid_product.development import (
    DevelopmentPayloadPseudonymizer,
    DevelopmentPrincipalAuthorizer,
    DevelopmentPseudonymFactory,
    DevelopmentWebhookVerifier,
    SyntheticHostedAnalysisProvider,
    canonical_webhook_digest,
    canonical_webhook_signature,
)
from prompt_enhancer.infrastructure.paid_product.sqlite import (
    PAID_PRODUCT_DATABASE_FILENAME,
    PAID_PRODUCT_SCHEMA_VERSION,
    PaidProductSqliteStore,
)


NOW = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)
KEY = b"fictional-paid-sqlite-key-00000001"
WEBHOOK_KEY = b"fictional-paid-webhook-key-00001"


def pid(label: str) -> str:
    return hashlib.sha256(f"fictional:{label}".encode("ascii")).hexdigest()


ORG = pid("organization")
USER = pid("user")
ACCOUNT = pid("account")
CLIENT = pid("client")
DEVICE = pid("device")
JOB = pid("job")
HOLD = pid("hold")
APPROVAL = pid("approval")
WINDOW = pid("window")


def store_under(root: Path) -> PaidProductSqliteStore:
    store = PaidProductSqliteStore.under(root)
    assert store.initialize() == PAID_PRODUCT_SCHEMA_VERSION
    return store


def signed_webhook(
    label: str,
    *,
    entry_label: str | None = None,
) -> SignedBillingWebhook:
    draft = SignedBillingWebhook(
        provider_event_id=pid(f"event-{label}"),
        provider_event_digest=pid("placeholder"),
        organization_id=ORG,
        entry_id=pid(entry_label or f"entry-{label}"),
        feature=EntitlementFeature.HOSTED_DEEP_ANALYSIS,
        kind=EntitlementDeltaKind.GRANT,
        effective_at=NOW,
        expires_at=NOW + timedelta(days=30),
        delivered_at=NOW,
        signature=SecretStr("0" * 64),
    )
    digested = draft.model_copy(
        update={"provider_event_digest": canonical_webhook_digest(draft)}
    )
    return digested.model_copy(
        update={
            "signature": SecretStr(
                canonical_webhook_signature(digested, WEBHOOK_KEY)
            )
        }
    )


def billing(store: PaidProductSqliteStore) -> BillingService:
    return BillingService(
        store=store,
        transaction=store,
        verifier=DevelopmentWebhookVerifier(WEBHOOK_KEY),
    )


def test_paid_sqlite_is_separate_atomic_and_rejects_newer_schema(tmp_path: Path) -> None:
    store = store_under(tmp_path)
    assert store.initialize() == PAID_PRODUCT_SCHEMA_VERSION
    assert store.path.name == PAID_PRODUCT_DATABASE_FILENAME
    assert store.structural_check()
    connection = sqlite3.connect(store.path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "sessions" not in tables
        assert "paid_deep_analysis_jobs" in tables
        connection.execute(
            "INSERT INTO paid_product_schema_migrations VALUES (?, ?)",
            (PAID_PRODUCT_SCHEMA_VERSION + 1, NOW.isoformat()),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(RuntimeError, match="schema is newer"):
        store.initialize()
    assert "local_receipt_tamper_seal_missing" in DEVELOPMENT_PRODUCT_READINESS.gaps
    assert "crash_reconciler_unmounted" in DEVELOPMENT_PRODUCT_READINESS.gaps


def test_uninitialized_store_never_creates_database_on_read_or_write(
    tmp_path: Path,
) -> None:
    store = PaidProductSqliteStore.under(tmp_path)
    with pytest.raises(RuntimeError, match="not_initialized"):
        store.account(ACCOUNT)
    with pytest.raises(RuntimeError, match="not_initialized"):
        with store:
            pass
    assert not store.path.exists()


def test_missing_required_trigger_fails_schema_verification(tmp_path: Path) -> None:
    store = store_under(tmp_path)
    connection = sqlite3.connect(store.path)
    try:
        connection.execute("DROP TRIGGER paid_webhook_fences_no_delete")
        connection.commit()
    finally:
        connection.close()
    assert store.structural_check() is False
    with pytest.raises(RuntimeError, match="schema_integrity_invalid"):
        store.initialize()


def test_identity_nonce_and_graph_survive_reopen(tmp_path: Path) -> None:
    store = store_under(tmp_path)
    account = Account(account_id=ACCOUNT, created_at=NOW)
    identity = AccountIdentityBinding(
        account_id=ACCOUNT,
        issuer_id="example-issuer-v1",
        subject_pseudonym=pid("subject"),
        created_at=NOW,
    )
    tenant = TenantAccountBinding(
        organization_id=ORG,
        account_id=ACCOUNT,
        user_id=USER,
        created_at=NOW,
    )
    with store:
        store.consume_nonce("example-issuer-v1", pid("nonce"), at=NOW)
        store.save_identity(account, identity, tenant)

    reopened = PaidProductSqliteStore(store.path)
    assert reopened.nonce_consumed("example-issuer-v1", pid("nonce"))
    assert reopened.binding_by_subject(
        "example-issuer-v1", pid("subject")
    ) == identity
    assert reopened.account(ACCOUNT) == account
    assert reopened.tenant_binding(ORG, ACCOUNT) == tenant
    with reopened:
        with pytest.raises(ValueError, match="already_consumed"):
            reopened.consume_nonce("example-issuer-v1", pid("nonce"), at=NOW)


def test_webhook_fence_and_append_rollback_together(tmp_path: Path) -> None:
    store = store_under(tmp_path)
    service = billing(store)
    first = signed_webhook("one", entry_label="same-entry")
    conflicting = signed_webhook("two", entry_label="same-entry")
    assert service.process_webhook(first, now=NOW) is WebhookDisposition.APPLIED
    with pytest.raises(ValueError, match="entitlement_conflict"):
        service.process_webhook(conflicting, now=NOW)
    assert store.webhook_digest(conflicting.provider_event_id) is None
    assert (
        service.process_webhook(first, now=NOW)
        is WebhookDisposition.IDEMPOTENT_REPLAY
    )
    assert [row.ledger_sequence for row in store.entitlement_entries(
        ORG, EntitlementFeature.HOSTED_DEEP_ANALYSIS
    )] == [1]


def test_concurrent_webhooks_receive_unique_monotonic_sequences(tmp_path: Path) -> None:
    path = store_under(tmp_path).path

    def apply(label: str) -> WebhookDisposition:
        local = PaidProductSqliteStore(path)
        return billing(local).process_webhook(signed_webhook(label), now=NOW)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(apply, ("parallel-a", "parallel-b")))
    assert results == (WebhookDisposition.APPLIED, WebhookDisposition.APPLIED)
    rows = PaidProductSqliteStore(path).entitlement_entries(
        ORG, EntitlementFeature.HOSTED_DEEP_ANALYSIS
    )
    assert tuple(row.ledger_sequence for row in rows) == (1, 2)


def test_reader_waits_for_same_store_writer_and_never_reads_torn_state(
    tmp_path: Path,
) -> None:
    store = store_under(tmp_path)
    writer_entered = Event()
    allow_writer_exit = Event()
    reader_finished = Event()

    def writer() -> None:
        with store:
            writer_entered.set()
            assert allow_writer_exit.wait(timeout=2.0)

    def reader() -> Account | None:
        assert writer_entered.wait(timeout=2.0)
        result = store.account(ACCOUNT)
        reader_finished.set()
        return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        writer_future = executor.submit(writer)
        reader_future = executor.submit(reader)
        assert not reader_finished.wait(timeout=0.05)
        allow_writer_exit.set()
        writer_future.result(timeout=2.0)
        assert reader_future.result(timeout=2.0) is None


def test_deep_analysis_receipts_survive_restart_without_payload(tmp_path: Path) -> None:
    store = store_under(tmp_path)
    bill = billing(store)
    assert bill.process_webhook(signed_webhook("enable"), now=NOW) is WebhookDisposition.APPLIED
    with store:
        store.save_spend_policy(
            SpendPolicy(organization_id=ORG, user_id=USER, user_limit_micro=50)
        )
        store.save_organization_spend_policy(
            OrganizationSpendPolicy(
                organization_id=ORG, organization_limit_micro=50
            )
        )

    payload = SecretStr("synthetic-input")
    payload_pseudonymizer = DevelopmentPayloadPseudonymizer(KEY)
    payload_pseudonym = payload_pseudonymizer.pseudonymize(payload)
    approved = RemoteAnalysisApproval(
        approval_id=APPROVAL,
        organization_id=ORG,
        user_id=USER,
        provider=TenantJobDestination.SYNTHETIC_TEST,
        model_id="synthetic-judge-v1",
        window_fingerprint=WINDOW,
        payload_pseudonym=payload_pseudonym,
        metric_keys=("prompt.constraint_precision",),
        redactor_version="redactor-v1",
        retention_class=RetentionClass.SYNTHETIC_EPHEMERAL,
        approved_payload_bytes=15,
        max_cost_micro=50,
        state=ApprovalState.AVAILABLE,
        approved_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=10),
    )
    approvals = ApprovalService(store=store, transaction=store)
    approvals.register(approved)
    request = DeepAnalysisRequest(
        job_id=JOB,
        organization_id=ORG,
        user_id=USER,
        approval_id=APPROVAL,
        hold_id=HOLD,
        destination=TenantJobDestination.SYNTHETIC_TEST,
        model_id="synthetic-judge-v1",
        window_fingerprint=WINDOW,
        payload_pseudonym=payload_pseudonym,
        metric_keys=("prompt.constraint_precision",),
        redactor_version="redactor-v1",
        retention_class=RetentionClass.SYNTHETIC_EPHEMERAL,
        payload_bytes=15,
        estimated_cost_micro=50,
        requested_at=NOW,
    )
    principal = PaidPrincipal(
        organization_id=ORG,
        user_id=USER,
        account_id=ACCOUNT,
        client_id=CLIENT,
        device_id=DEVICE,
        scopes=(PaidScope.JOBS_SUBMIT,),
        verified_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        active=True,
    )
    authorizer = DevelopmentPrincipalAuthorizer()
    authorizer.register(principal)
    identifiers = DevelopmentPseudonymFactory(KEY)
    service = DeepAnalysisService(
        profile=ProductDeploymentProfile.DEVELOPMENT,
        authorizer=authorizer,
        billing=bill,
        approvals=approvals,
        jobs=store,
        audit=store,
        identifiers=identifiers,
        provider=SyntheticHostedAnalysisProvider(
            completed_at=NOW + timedelta(seconds=1),
            identifiers=identifiers,
            actual_cost_micro=25,
        ),
        transaction=store,
        payload_pseudonymizer=payload_pseudonymizer,
    )
    completed = service.submit(principal, request, payload, now=NOW)
    assert completed.state is DeepJobState.COMPLETED

    reopened = PaidProductSqliteStore(store.path)
    assert reopened.job(ORG, JOB) == completed
    persisted_hold = reopened.spend_hold(ORG, HOLD)
    persisted_approval = reopened.approval(ORG, APPROVAL)
    assert persisted_hold is not None
    assert persisted_approval is not None
    assert persisted_hold.state is SpendHoldState.SETTLED
    assert persisted_approval.state is ApprovalState.CONSUMED
    assert len(reopened.audit_for_tenant(ORG)) == 1
    assert b"synthetic-input" not in store.path.read_bytes()
    assert reopened.structural_check()


def test_raw_receipt_mutation_and_terminal_rewrite_are_rejected(tmp_path: Path) -> None:
    store = store_under(tmp_path)
    service = billing(store)
    service.process_webhook(signed_webhook("immutable"), now=NOW)
    connection = sqlite3.connect(store.path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="entitlement_immutable"):
            connection.execute(
                "UPDATE paid_entitlement_ledger SET feature = 'team_sync'"
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="webhook_fence_immutable"):
            connection.execute("DELETE FROM paid_webhook_fences")
        connection.rollback()
    finally:
        connection.close()

    approvals = ApprovalService(store=store, transaction=store)
    payload_pseudonym = DevelopmentPayloadPseudonymizer(KEY).pseudonymize(
        SecretStr("synthetic-input")
    )
    available = RemoteAnalysisApproval(
        approval_id=APPROVAL,
        organization_id=ORG,
        user_id=USER,
        provider=TenantJobDestination.SYNTHETIC_TEST,
        model_id="synthetic-judge-v1",
        window_fingerprint=WINDOW,
        payload_pseudonym=payload_pseudonym,
        metric_keys=("prompt.constraint_precision",),
        redactor_version="redactor-v1",
        retention_class=RetentionClass.SYNTHETIC_EPHEMERAL,
        approved_payload_bytes=15,
        max_cost_micro=50,
        state=ApprovalState.AVAILABLE,
        approved_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    approvals.register(available)
    with store:
        consumed = available.model_copy(
            update={"state": ApprovalState.CONSUMED, "consumed_at": NOW}
        )
        store.save_approval(consumed)
    with store:
        with pytest.raises(ValueError, match="transition_invalid"):
            store.save_approval(available)
    persisted = store.approval(ORG, APPROVAL)
    assert persisted is not None
    assert persisted.state is ApprovalState.CONSUMED


def test_raw_allowed_transition_with_mismatched_terminal_body_fails_closed(
    tmp_path: Path,
) -> None:
    store = store_under(tmp_path)
    queued = DeepAnalysisJob(
        job_id=JOB,
        organization_id=ORG,
        user_id=USER,
        destination=TenantJobDestination.SYNTHETIC_TEST,
        model_id="synthetic-judge-v1",
        metric_keys=("prompt.constraint_precision",),
        state=DeepJobState.QUEUED,
        requested_at=NOW,
    )
    with store:
        store.save_job(queued)
    connection = sqlite3.connect(store.path)
    try:
        base_json = connection.execute(
            "SELECT base_json FROM paid_deep_analysis_jobs"
        ).fetchone()[0]
        connection.execute(
            """
            UPDATE paid_deep_analysis_jobs
            SET state = 'completed', terminal_json = ?
            """,
            (base_json,),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(ValueError, match="terminal_identity_mismatch"):
        store.job(ORG, JOB)


def test_writes_require_explicit_single_entry_transaction(tmp_path: Path) -> None:
    store = store_under(tmp_path)
    with pytest.raises(RuntimeError, match="write_requires_transaction"):
        store.save_spend_policy(
            SpendPolicy(organization_id=ORG, user_id=USER, user_limit_micro=50)
        )
    with store:
        with pytest.raises(RuntimeError, match="transaction_nested"):
            with store:
                pass


def test_lost_sqlite_transaction_never_degrades_to_autocommit(tmp_path: Path) -> None:
    store = store_under(tmp_path)
    event_id = pid("lost-transaction-event")
    with pytest.raises(RuntimeError, match="transaction_lost"):
        with store:
            store._writer().execute("ROLLBACK")
            store.fence_webhook(event_id, pid("lost-transaction-digest"))
    assert store.webhook_digest(event_id) is None

    original = ApprovalError(PaidReasonCode.APPROVAL_MISSING)
    with pytest.raises(ApprovalError) as raised:
        with store:
            store._writer().execute("ROLLBACK")
            raise original
    assert raised.value is original


def test_same_name_noop_trigger_fails_structural_check(tmp_path: Path) -> None:
    store = store_under(tmp_path)
    connection = sqlite3.connect(store.path)
    try:
        connection.execute("DROP TRIGGER paid_webhook_fences_no_delete")
        connection.execute(
            """
            CREATE TRIGGER paid_webhook_fences_no_delete
            BEFORE DELETE ON paid_webhook_fences
            BEGIN SELECT 1; END
            """
        )
        connection.commit()
    finally:
        connection.close()
    assert store.structural_check() is False
    with pytest.raises(RuntimeError, match="schema_integrity_invalid"):
        store.initialize()


def test_unexpected_trigger_with_unrelated_name_fails_structural_check(
    tmp_path: Path,
) -> None:
    store = store_under(tmp_path)
    connection = sqlite3.connect(store.path)
    try:
        connection.execute(
            """
            CREATE TRIGGER zz_suppress_paid_audit
            BEFORE INSERT ON paid_audit_events
            BEGIN SELECT RAISE(IGNORE); END
            """
        )
        connection.commit()
    finally:
        connection.close()
    assert store.structural_check() is False
    with pytest.raises(RuntimeError, match="schema_integrity_invalid"):
        store.initialize()


def test_unexpected_table_with_unrelated_name_fails_structural_check(
    tmp_path: Path,
) -> None:
    store = store_under(tmp_path)
    connection = sqlite3.connect(store.path)
    try:
        connection.execute("CREATE TABLE zz_hidden_payload(value BLOB)")
        connection.commit()
    finally:
        connection.close()
    assert store.structural_check() is False
    with pytest.raises(RuntimeError, match="schema_integrity_invalid"):
        store.initialize()


def test_cross_tenant_denial_is_transactionally_audited(tmp_path: Path) -> None:
    store = store_under(tmp_path)
    principal = PaidPrincipal(
        organization_id=ORG,
        user_id=USER,
        account_id=ACCOUNT,
        client_id=CLIENT,
        device_id=DEVICE,
        scopes=(PaidScope.JOBS_SUBMIT,),
        verified_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        active=True,
    )
    authority = DevelopmentPrincipalAuthorizer()
    authority.register(principal)
    identifiers = DevelopmentPseudonymFactory(KEY)
    payload = SecretStr("synthetic-input")
    pseudonymizer = DevelopmentPayloadPseudonymizer(KEY)
    request = DeepAnalysisRequest(
        job_id=JOB,
        organization_id=pid("other-organization"),
        user_id=USER,
        approval_id=APPROVAL,
        hold_id=HOLD,
        destination=TenantJobDestination.SYNTHETIC_TEST,
        model_id="synthetic-judge-v1",
        window_fingerprint=WINDOW,
        payload_pseudonym=pseudonymizer.pseudonymize(payload),
        metric_keys=("prompt.constraint_precision",),
        redactor_version="redactor-v1",
        retention_class=RetentionClass.SYNTHETIC_EPHEMERAL,
        payload_bytes=15,
        estimated_cost_micro=50,
        requested_at=NOW,
    )
    service = DeepAnalysisService(
        profile=ProductDeploymentProfile.DEVELOPMENT,
        authorizer=authority,
        billing=billing(store),
        approvals=ApprovalService(store=store, transaction=store),
        jobs=store,
        audit=store,
        identifiers=identifiers,
        provider=SyntheticHostedAnalysisProvider(
            completed_at=NOW,
            identifiers=identifiers,
            actual_cost_micro=25,
        ),
        transaction=store,
        payload_pseudonymizer=pseudonymizer,
    )
    with pytest.raises(PaidAuthorizationError):
        service.submit(principal, request, payload, now=NOW)
    audit = store.audit_for_tenant(ORG)
    assert len(audit) == 1
    assert audit[0].action.value == "access_denied"
    assert audit[0].reason is not None
    assert audit[0].reason.value == "cross_tenant"


def test_restart_reconciler_closes_queued_job_without_replaying_provider(
    tmp_path: Path,
) -> None:
    store = store_under(tmp_path)
    bill = billing(store)
    bill.process_webhook(signed_webhook("restart-enable"), now=NOW)
    with store:
        store.save_spend_policy(
            SpendPolicy(organization_id=ORG, user_id=USER, user_limit_micro=50)
        )
        store.save_organization_spend_policy(
            OrganizationSpendPolicy(
                organization_id=ORG, organization_limit_micro=50
            )
        )
    payload = SecretStr("synthetic-input")
    pseudonymizer = DevelopmentPayloadPseudonymizer(KEY)
    payload_pseudonym = pseudonymizer.pseudonymize(payload)
    approval = RemoteAnalysisApproval(
        approval_id=APPROVAL,
        organization_id=ORG,
        user_id=USER,
        provider=TenantJobDestination.SYNTHETIC_TEST,
        model_id="synthetic-judge-v1",
        window_fingerprint=WINDOW,
        payload_pseudonym=payload_pseudonym,
        metric_keys=("prompt.constraint_precision",),
        redactor_version="redactor-v1",
        retention_class=RetentionClass.SYNTHETIC_EPHEMERAL,
        approved_payload_bytes=15,
        max_cost_micro=50,
        state=ApprovalState.AVAILABLE,
        approved_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=10),
    )
    approvals = ApprovalService(store=store, transaction=store)
    approvals.register(approval)
    request = DeepAnalysisRequest(
        job_id=JOB,
        organization_id=ORG,
        user_id=USER,
        approval_id=APPROVAL,
        hold_id=HOLD,
        destination=TenantJobDestination.SYNTHETIC_TEST,
        model_id="synthetic-judge-v1",
        window_fingerprint=WINDOW,
        payload_pseudonym=payload_pseudonym,
        metric_keys=("prompt.constraint_precision",),
        redactor_version="redactor-v1",
        retention_class=RetentionClass.SYNTHETIC_EPHEMERAL,
        payload_bytes=15,
        estimated_cost_micro=50,
        requested_at=NOW,
    )
    queued = DeepAnalysisJob(
        job_id=JOB,
        organization_id=ORG,
        user_id=USER,
        destination=TenantJobDestination.SYNTHETIC_TEST,
        model_id="synthetic-judge-v1",
        metric_keys=request.metric_keys,
        state=DeepJobState.QUEUED,
        requested_at=NOW,
    )
    with store:
        bill._reserve_spend_locked(
            hold_id=HOLD,
            organization_id=ORG,
            user_id=USER,
            job_id=JOB,
            amount_micro=50,
            now=NOW,
        )
        approvals._consume_locked(request, now=NOW)
        store.save_job(queued)

    reopened = PaidProductSqliteStore(store.path)
    reopened_bill = billing(reopened)
    reopened_approvals = ApprovalService(store=reopened, transaction=reopened)
    principal = PaidPrincipal(
        organization_id=ORG,
        user_id=USER,
        account_id=ACCOUNT,
        client_id=CLIENT,
        device_id=DEVICE,
        scopes=(PaidScope.JOBS_SUBMIT,),
        verified_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        active=True,
    )
    authority = DevelopmentPrincipalAuthorizer()
    authority.register(principal)
    identifiers = DevelopmentPseudonymFactory(KEY)
    provider = SyntheticHostedAnalysisProvider(
        completed_at=NOW + timedelta(minutes=1),
        identifiers=identifiers,
        actual_cost_micro=25,
    )
    service = DeepAnalysisService(
        profile=ProductDeploymentProfile.DEVELOPMENT,
        authorizer=authority,
        billing=reopened_bill,
        approvals=reopened_approvals,
        jobs=reopened,
        audit=reopened,
        identifiers=identifiers,
        provider=provider,
        transaction=reopened,
        payload_pseudonymizer=pseudonymizer,
    )
    recovered = service.reconcile_after_restart(now=NOW + timedelta(minutes=2))
    assert len(recovered) == 1
    assert recovered[0].state is DeepJobState.COST_UNKNOWN
    assert provider.call_count == 0
    persisted_hold = reopened.spend_hold(ORG, HOLD)
    persisted_approval = reopened.approval(ORG, APPROVAL)
    assert persisted_hold is not None
    assert persisted_approval is not None
    assert persisted_hold.state is SpendHoldState.COST_UNKNOWN
    assert persisted_approval.state is ApprovalState.CONSUMED
    assert len(reopened.audit_for_tenant(ORG)) == 1
    assert service.reconcile_after_restart(now=NOW + timedelta(minutes=3)) == ()


def test_graph_mismatch_rolls_back_without_partial_identity(tmp_path: Path) -> None:
    store = store_under(tmp_path)
    with pytest.raises(ValueError, match="identity_graph_mismatch"):
        with store:
            store.save_identity(
                Account(account_id=ACCOUNT, created_at=NOW),
                AccountIdentityBinding(
                    account_id=pid("different-account"),
                    issuer_id="example-issuer-v1",
                    subject_pseudonym=pid("subject"),
                    created_at=NOW,
                ),
                TenantAccountBinding(
                    organization_id=ORG,
                    account_id=ACCOUNT,
                    user_id=USER,
                    created_at=NOW,
                ),
            )
    assert store.account(ACCOUNT) is None
