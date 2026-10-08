"""Synthetic attack tests for the default-off paid-product foundation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import hashlib

import pytest
from pydantic import SecretStr, ValidationError

from prompt_enhancer.application.paid_product.contracts import (
    ApprovalState,
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
    TenantJobDestination,
    VerifiedOidcAssertion,
    WebhookDisposition,
)
from prompt_enhancer.application.paid_product.errors import (
    ApprovalError,
    BillingWebhookError,
    PaidAuthorizationError,
    ProviderInvocationError,
    SpendLimitError,
)
from prompt_enhancer.application.paid_product.services import (
    ApprovalService,
    BillingService,
    DeepAnalysisService,
    ProductIdentityService,
)
from prompt_enhancer.infrastructure.paid_product.development import (
    DevelopmentPaidProductStore,
    DevelopmentPayloadPseudonymizer,
    DevelopmentPrincipalAuthorizer,
    DevelopmentPseudonymFactory,
    DevelopmentSubjectPseudonymizer,
    DevelopmentTenantBindingResolver,
    DevelopmentWebhookVerifier,
    SyntheticHostedAnalysisProvider,
    canonical_webhook_digest,
    canonical_webhook_signature,
)


NOW = datetime(2026, 8, 18, 4, 0, tzinfo=UTC)
KEY = b"synthetic-paid-product-test-key-0001"
WEBHOOK_KEY = b"synthetic-webhook-test-key-0000001"
PAYLOAD_PSEUDONYM = DevelopmentPayloadPseudonymizer(KEY).pseudonymize(
    SecretStr("synthetic-input")
)


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
EVENT = pid("provider-event")
ENTRY = pid("ledger-entry")


def signed_webhook(
    *,
    kind: EntitlementDeltaKind = EntitlementDeltaKind.GRANT,
    event_id: str = EVENT,
    organization_id: str = ORG,
    delivered_at: datetime = NOW,
    effective_at: datetime = NOW,
) -> SignedBillingWebhook:
    draft = SignedBillingWebhook(
        provider_event_id=event_id,
        provider_event_digest=pid("placeholder-digest"),
        organization_id=organization_id,
        entry_id=ENTRY,
        feature=EntitlementFeature.HOSTED_DEEP_ANALYSIS,
        kind=kind,
        effective_at=effective_at,
        expires_at=NOW + timedelta(days=30),
        delivered_at=delivered_at,
        signature=SecretStr("0" * 64),
    )
    with_digest = draft.model_copy(
        update={"provider_event_digest": canonical_webhook_digest(draft)}
    )
    return with_digest.model_copy(
        update={
            "signature": SecretStr(
                canonical_webhook_signature(with_digest, WEBHOOK_KEY)
            )
        }
    )


def resign(webhook: SignedBillingWebhook) -> SignedBillingWebhook:
    with_digest = webhook.model_copy(
        update={"provider_event_digest": canonical_webhook_digest(webhook)}
    )
    return with_digest.model_copy(
        update={
            "signature": SecretStr(
                canonical_webhook_signature(with_digest, WEBHOOK_KEY)
            )
        }
    )


def principal(*, organization_id: str = ORG) -> PaidPrincipal:
    return PaidPrincipal(
        organization_id=organization_id,
        user_id=USER,
        account_id=ACCOUNT,
        client_id=CLIENT,
        device_id=DEVICE,
        scopes=(PaidScope.JOBS_SUBMIT,),
        verified_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        active=True,
    )


def registered_authorizer(
    value: PaidPrincipal | None = None,
) -> DevelopmentPrincipalAuthorizer:
    authority = DevelopmentPrincipalAuthorizer()
    authority.register(value or principal())
    return authority


def approval(*, organization_id: str = ORG) -> RemoteAnalysisApproval:
    return RemoteAnalysisApproval(
        approval_id=APPROVAL,
        organization_id=organization_id,
        user_id=USER,
        provider=TenantJobDestination.SYNTHETIC_TEST,
        model_id="synthetic-judge-v1",
        window_fingerprint=WINDOW,
        payload_pseudonym=PAYLOAD_PSEUDONYM,
        metric_keys=("prompt.constraint_precision",),
        redactor_version="redactor-v1",
        retention_class=RetentionClass.SYNTHETIC_EPHEMERAL,
        approved_payload_bytes=15,
        max_cost_micro=50,
        state=ApprovalState.AVAILABLE,
        approved_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=10),
    )


def request(*, organization_id: str = ORG) -> DeepAnalysisRequest:
    return DeepAnalysisRequest(
        job_id=JOB,
        organization_id=organization_id,
        user_id=USER,
        approval_id=APPROVAL,
        hold_id=HOLD,
        destination=TenantJobDestination.SYNTHETIC_TEST,
        model_id="synthetic-judge-v1",
        window_fingerprint=WINDOW,
        payload_pseudonym=PAYLOAD_PSEUDONYM,
        metric_keys=("prompt.constraint_precision",),
        redactor_version="redactor-v1",
        retention_class=RetentionClass.SYNTHETIC_EPHEMERAL,
        payload_bytes=15,
        estimated_cost_micro=50,
        requested_at=NOW,
    )


def billing(store: DevelopmentPaidProductStore) -> BillingService:
    return BillingService(
        store=store,
        transaction=store,
        verifier=DevelopmentWebhookVerifier(WEBHOOK_KEY),
    )


def enable_and_budget(store: DevelopmentPaidProductStore) -> BillingService:
    service = billing(store)
    assert service.process_webhook(signed_webhook(), now=NOW) is WebhookDisposition.APPLIED
    store.save_spend_policy(
        SpendPolicy(
            organization_id=ORG,
            user_id=USER,
            user_limit_micro=50,
        )
    )
    store.save_organization_spend_policy(
        OrganizationSpendPolicy(
            organization_id=ORG,
            organization_limit_micro=50,
        )
    )
    return service


class RejectNestedTransaction:
    """Database-like boundary that fails if application services nest BEGIN."""

    def __init__(self, store: DevelopmentPaidProductStore) -> None:
        self._store = store
        self._active = False

    def __enter__(self) -> None:
        if self._active:
            raise RuntimeError("nested_transaction")
        self._active = True
        self._store.__enter__()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._store.__exit__(exc_type, exc, traceback)
        self._active = False


def test_destination_type_cannot_name_personal_or_local_execution() -> None:
    values = {item.value for item in TenantJobDestination}
    assert values == {
        "official_openai_api",
        "official_anthropic_api",
        "synthetic_test",
    }
    forbidden = ("codex", "claude_code", "cli", "manual", "local_device")
    assert not any(token in value for token in forbidden for value in values)


def test_contracts_reject_profile_fields_and_keep_readiness_false() -> None:
    assert DEVELOPMENT_PRODUCT_READINESS.production_ready is False
    assert DEVELOPMENT_PRODUCT_READINESS.remote_transport_enabled is False
    with pytest.raises(ValidationError):
        SpendPolicy.model_validate(
            {
                "organization_id": ORG,
                "user_id": USER,
                "organization_limit_micro": 50,
                "user_limit_micro": 50,
                "email": "fictional@example.invalid",
            }
        )


def test_identity_discards_subject_and_fences_nonce() -> None:
    store = DevelopmentPaidProductStore()
    pseudonymizer = DevelopmentSubjectPseudonymizer(KEY)
    tenant_bindings = DevelopmentTenantBindingResolver()
    tenant_bindings.bind(
        "synthetic-issuer-v1",
        pseudonymizer.pseudonymize(
            "synthetic-issuer-v1", SecretStr("fictional-subject")
        ),
        ORG,
        USER,
    )
    service = ProductIdentityService(
        store=store,
        transaction=store,
        pseudonymizer=pseudonymizer,
        tenant_bindings=tenant_bindings,
        identifiers=DevelopmentPseudonymFactory(KEY),
        allowed_issuer="synthetic-issuer-v1",
        allowed_audience="prompt-enhancer-v1",
    )
    assertion = VerifiedOidcAssertion(
        issuer_id="synthetic-issuer-v1",
        audience="prompt-enhancer-v1",
        raw_subject=SecretStr("fictional-subject"),
        nonce_id=pid("nonce"),
        issued_at=NOW - timedelta(seconds=5),
        expires_at=NOW + timedelta(minutes=5),
    )
    signed_in = service.sign_in(assertion, now=NOW)
    assert signed_in.identity.subject_pseudonym != "fictional-subject"
    assert "fictional-subject" not in repr(store.__dict__)
    with pytest.raises(PaidAuthorizationError) as caught:
        service.sign_in(assertion, now=NOW)
    assert caught.value.reason is PaidReasonCode.OIDC_NONCE_REPLAYED


def test_identity_requires_server_owned_tenant_binding_and_consumes_denied_nonce() -> None:
    store = DevelopmentPaidProductStore()
    service = ProductIdentityService(
        store=store,
        transaction=store,
        pseudonymizer=DevelopmentSubjectPseudonymizer(KEY),
        tenant_bindings=DevelopmentTenantBindingResolver(),
        identifiers=DevelopmentPseudonymFactory(KEY),
        allowed_issuer="synthetic-issuer-v1",
        allowed_audience="prompt-enhancer-v1",
    )
    assertion = VerifiedOidcAssertion(
        issuer_id="synthetic-issuer-v1",
        audience="prompt-enhancer-v1",
        raw_subject=SecretStr("uninvited-fictional-subject"),
        nonce_id=pid("uninvited-nonce"),
        issued_at=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=1),
    )
    with pytest.raises(PaidAuthorizationError) as denied:
        service.sign_in(assertion, now=NOW)
    assert denied.value.reason is PaidReasonCode.DEFAULT_DENY
    with pytest.raises(PaidAuthorizationError) as replay:
        service.sign_in(assertion, now=NOW)
    assert replay.value.reason is PaidReasonCode.OIDC_NONCE_REPLAYED


def test_two_identity_subjects_cannot_claim_the_same_tenant_user() -> None:
    store = DevelopmentPaidProductStore()
    pseudonymizer = DevelopmentSubjectPseudonymizer(KEY)
    tenant_bindings = DevelopmentTenantBindingResolver()
    for subject in ("fictional-subject-a", "fictional-subject-b"):
        tenant_bindings.bind(
            "synthetic-issuer-v1",
            pseudonymizer.pseudonymize(
                "synthetic-issuer-v1", SecretStr(subject)
            ),
            ORG,
            USER,
        )
    service = ProductIdentityService(
        store=store,
        transaction=store,
        pseudonymizer=pseudonymizer,
        tenant_bindings=tenant_bindings,
        identifiers=DevelopmentPseudonymFactory(KEY),
        allowed_issuer="synthetic-issuer-v1",
        allowed_audience="prompt-enhancer-v1",
    )

    def assertion(subject: str, nonce: str) -> VerifiedOidcAssertion:
        return VerifiedOidcAssertion(
            issuer_id="synthetic-issuer-v1",
            audience="prompt-enhancer-v1",
            raw_subject=SecretStr(subject),
            nonce_id=pid(nonce),
            issued_at=NOW - timedelta(seconds=1),
            expires_at=NOW + timedelta(minutes=1),
        )

    service.sign_in(assertion("fictional-subject-a", "nonce-a"), now=NOW)
    with pytest.raises(PaidAuthorizationError) as caught:
        service.sign_in(assertion("fictional-subject-b", "nonce-b"), now=NOW)
    assert caught.value.reason is PaidReasonCode.DEFAULT_DENY
    assert "fictional-subject-b" not in repr(store.__dict__)


@pytest.mark.parametrize(
    ("issuer", "audience", "issued_at", "expires_at"),
    (
        ("wrong-issuer-v1", "prompt-enhancer-v1", NOW, NOW + timedelta(minutes=1)),
        ("synthetic-issuer-v1", "wrong-audience-v1", NOW, NOW + timedelta(minutes=1)),
        (
            "synthetic-issuer-v1",
            "prompt-enhancer-v1",
            NOW + timedelta(seconds=1),
            NOW + timedelta(minutes=1),
        ),
        (
            "synthetic-issuer-v1",
            "prompt-enhancer-v1",
            NOW - timedelta(minutes=2),
            NOW - timedelta(minutes=1),
        ),
    ),
)
def test_oidc_failures_share_one_non_enumerating_reason(
    issuer: str, audience: str, issued_at: datetime, expires_at: datetime
) -> None:
    store = DevelopmentPaidProductStore()
    tenant_bindings = DevelopmentTenantBindingResolver()
    service = ProductIdentityService(
        store=store,
        transaction=store,
        pseudonymizer=DevelopmentSubjectPseudonymizer(KEY),
        tenant_bindings=tenant_bindings,
        identifiers=DevelopmentPseudonymFactory(KEY),
        allowed_issuer="synthetic-issuer-v1",
        allowed_audience="prompt-enhancer-v1",
    )
    assertion = VerifiedOidcAssertion(
        issuer_id=issuer,
        audience=audience,
        raw_subject=SecretStr("fictional-subject"),
        nonce_id=pid(f"nonce-{issuer}-{audience}"),
        issued_at=issued_at,
        expires_at=expires_at,
    )
    with pytest.raises(PaidAuthorizationError) as caught:
        service.sign_in(assertion, now=NOW)
    assert caught.value.reason is PaidReasonCode.OIDC_ASSERTION_INVALID


def test_webhook_is_idempotent_conflict_safe_and_fence_survives_erasure() -> None:
    store = DevelopmentPaidProductStore()
    service = billing(store)
    webhook = signed_webhook()
    assert service.process_webhook(webhook, now=NOW) is WebhookDisposition.APPLIED
    assert (
        service.process_webhook(webhook, now=NOW)
        is WebhookDisposition.IDEMPOTENT_REPLAY
    )
    store.delete_entitlement_rows(ORG)
    assert (
        service.process_webhook(webhook, now=NOW)
        is WebhookDisposition.IDEMPOTENT_REPLAY
    )
    conflict = webhook.model_copy(update={"provider_event_digest": pid("different")})
    with pytest.raises(BillingWebhookError) as caught:
        service.process_webhook(conflict, now=NOW)
    # Signature is checked before the conflict oracle.
    assert caught.value.reason is PaidReasonCode.WEBHOOK_SIGNATURE_INVALID

    signed_conflict = resign(
        webhook.model_copy(
            update={
                "entry_id": pid("conflicting-entry"),
                "kind": EntitlementDeltaKind.REVOKE,
            }
        )
    )
    with pytest.raises(BillingWebhookError) as signed_conflict_error:
        service.process_webhook(signed_conflict, now=NOW)
    assert signed_conflict_error.value.reason is PaidReasonCode.WEBHOOK_CONFLICT


def test_webhook_fence_rolls_back_if_ledger_append_fails() -> None:
    store = DevelopmentPaidProductStore()
    service = billing(store)
    service.process_webhook(signed_webhook(), now=NOW)
    second_event_id = pid("second-provider-event")
    duplicate_entry = resign(
        signed_webhook(event_id=second_event_id).model_copy(
            update={"entry_id": ENTRY}
        )
    )
    with pytest.raises(ValueError, match="entitlement_entry_exists"):
        service.process_webhook(duplicate_entry, now=NOW)
    assert store.webhook_digest(second_event_id) is None


def test_webhook_rejects_stale_and_bad_signature() -> None:
    store = DevelopmentPaidProductStore()
    service = billing(store)
    with pytest.raises(BillingWebhookError) as bad:
        service.process_webhook(
            signed_webhook().model_copy(
                update={"signature": SecretStr("f" * 64)}
            ),
            now=NOW,
        )
    assert bad.value.reason is PaidReasonCode.WEBHOOK_SIGNATURE_INVALID
    with pytest.raises(BillingWebhookError) as stale:
        service.process_webhook(
            signed_webhook(delivered_at=NOW - timedelta(minutes=6)), now=NOW
        )
    assert stale.value.reason is PaidReasonCode.WEBHOOK_STALE


def test_latest_entitlement_revocation_wins_and_expiry_disables() -> None:
    store = DevelopmentPaidProductStore()
    service = billing(store)
    service.process_webhook(signed_webhook(), now=NOW)
    assert service.entitlement(
        ORG, EntitlementFeature.HOSTED_DEEP_ANALYSIS, now=NOW
    ).enabled
    revoke = signed_webhook(
        kind=EntitlementDeltaKind.REVOKE,
        event_id=pid("revoke-event"),
        effective_at=NOW,
        delivered_at=NOW,
    ).model_copy(update={"entry_id": pid("revoke-entry")})
    # Changing a signed field requires recomputing both digest and signature.
    revoke = revoke.model_copy(
        update={"provider_event_digest": canonical_webhook_digest(revoke)}
    )
    revoke = revoke.model_copy(
        update={"signature": SecretStr(canonical_webhook_signature(revoke, WEBHOOK_KEY))}
    )
    service.process_webhook(revoke, now=NOW)
    assert not service.entitlement(
        ORG,
        EntitlementFeature.HOSTED_DEEP_ANALYSIS,
        now=NOW,
    ).enabled


def test_concurrent_last_allowance_creates_exactly_one_hold() -> None:
    store = DevelopmentPaidProductStore()
    service = enable_and_budget(store)

    def attempt(index: int) -> str:
        try:
            return service.reserve_spend(
                hold_id=pid(f"hold-{index}"),
                organization_id=ORG,
                user_id=USER,
                job_id=pid(f"job-{index}"),
                amount_micro=50,
                now=NOW,
            ).hold_id
        except SpendLimitError:
            return "denied"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(attempt, (1, 2)))
    assert sum(value != "denied" for value in results) == 1
    assert len(store.spend_holds(ORG)) == 1


def test_org_spend_cap_is_one_authoritative_row_not_a_user_value() -> None:
    store = DevelopmentPaidProductStore()
    service = billing(store)
    store.save_organization_spend_policy(
        OrganizationSpendPolicy(
            organization_id=ORG,
            organization_limit_micro=50,
        )
    )
    store.save_spend_policy(
        SpendPolicy(
            organization_id=ORG,
            user_id=USER,
            user_limit_micro=100,
        )
    )
    with pytest.raises(SpendLimitError) as caught:
        service.reserve_spend(
            hold_id=HOLD,
            organization_id=ORG,
            user_id=USER,
            job_id=JOB,
            amount_micro=51,
            now=NOW,
        )
    assert caught.value.reason is PaidReasonCode.SPEND_LIMIT_EXCEEDED


def test_terminal_spend_hold_cannot_be_reused_for_provider_retry() -> None:
    store = DevelopmentPaidProductStore()
    service = enable_and_budget(store)
    service.reserve_spend(
        hold_id=HOLD,
        organization_id=ORG,
        user_id=USER,
        job_id=JOB,
        amount_micro=50,
        now=NOW,
    )
    service.release_spend(ORG, HOLD, now=NOW)
    with pytest.raises(SpendLimitError) as caught:
        service.reserve_spend(
            hold_id=HOLD,
            organization_id=ORG,
            user_id=USER,
            job_id=JOB,
            amount_micro=50,
            now=NOW,
        )
    assert caught.value.reason is PaidReasonCode.DEFAULT_DENY


def test_actual_cost_above_hold_becomes_unknown_instead_of_remaining_held() -> None:
    store = DevelopmentPaidProductStore()
    service = enable_and_budget(store)
    service.reserve_spend(
        hold_id=HOLD,
        organization_id=ORG,
        user_id=USER,
        job_id=JOB,
        amount_micro=50,
        now=NOW,
    )
    updated = service.settle_spend(
        ORG, HOLD, actual_cost_micro=51, now=NOW
    )
    assert updated.state is SpendHoldState.COST_UNKNOWN
    assert updated.settled_amount_micro is None


def test_principal_authority_rejects_forged_scope_or_account() -> None:
    original = principal()
    authority = registered_authorizer(original)
    forged_scope = original.model_copy(
        update={"scopes": (PaidScope.JOBS_READ, PaidScope.JOBS_SUBMIT)}
    )
    forged_account = original.model_copy(update={"account_id": pid("forged-account")})
    assert not authority.allows(forged_scope, PaidScope.JOBS_SUBMIT, now=NOW)
    assert not authority.allows(forged_account, PaidScope.JOBS_SUBMIT, now=NOW)


def test_deep_analysis_consumes_exact_approval_and_settles() -> None:
    store = DevelopmentPaidProductStore()
    bill = enable_and_budget(store)
    approvals = ApprovalService(store=store, transaction=store)
    approvals.register(approval())
    ids = DevelopmentPseudonymFactory(KEY)
    provider = SyntheticHostedAnalysisProvider(
        completed_at=NOW + timedelta(seconds=1),
        identifiers=ids,
        actual_cost_micro=40,
    )
    service = DeepAnalysisService(
        profile=ProductDeploymentProfile.DEVELOPMENT,
        authorizer=registered_authorizer(),
        billing=bill,
        approvals=approvals,
        jobs=store,
        audit=store,
        identifiers=ids,
        provider=provider,
        transaction=store,
        payload_pseudonymizer=DevelopmentPayloadPseudonymizer(KEY),
    )
    result = service.submit(
        principal(), request(), SecretStr("synthetic-input"), now=NOW
    )
    assert result.state is DeepJobState.COMPLETED
    assert tuple(value.metric_key for value in result.judgments) == (
        "prompt.constraint_precision",
    )
    assert provider.call_count == 1
    assert store.approval(ORG, APPROVAL).state is ApprovalState.CONSUMED
    assert store.spend_hold(ORG, HOLD).state is SpendHoldState.SETTLED
    assert service.submit(
        principal(), request(), SecretStr("synthetic-input"), now=NOW
    ) == result
    assert provider.call_count == 1
    with pytest.raises(ApprovalError) as replay:
        approvals.consume(
            request().model_copy(
                update={
                    "job_id": pid("second-job"),
                    "hold_id": pid("second-hold"),
                }
            ),
            now=NOW,
        )
    assert replay.value.reason is PaidReasonCode.APPROVAL_REPLAYED


def test_entitlement_is_rechecked_inside_job_transaction() -> None:
    store = DevelopmentPaidProductStore()
    bill = enable_and_budget(store)
    approvals = ApprovalService(store=store, transaction=store)
    approvals.register(approval())
    ids = DevelopmentPseudonymFactory(KEY)
    provider = SyntheticHostedAnalysisProvider(
        completed_at=NOW + timedelta(seconds=1),
        identifiers=ids,
        actual_cost_micro=40,
    )
    service = DeepAnalysisService(
        profile=ProductDeploymentProfile.DEVELOPMENT,
        authorizer=registered_authorizer(),
        billing=bill,
        approvals=approvals,
        jobs=store,
        audit=store,
        identifiers=ids,
        provider=provider,
        transaction=store,
        payload_pseudonymizer=DevelopmentPayloadPseudonymizer(KEY),
    )
    original_entitlement = bill.entitlement
    calls = 0

    def revoke_after_first_projection(
        organization_id: str,
        feature: EntitlementFeature,
        *,
        now: datetime,
    ):
        nonlocal calls
        projection = original_entitlement(
            organization_id,
            feature,
            now=now,
        )
        calls += 1
        if calls == 1:
            revoke = signed_webhook(
                kind=EntitlementDeltaKind.REVOKE,
                event_id=pid("revocation-race-event"),
            ).model_copy(update={"entry_id": pid("revocation-race-entry")})
            bill.process_webhook(resign(revoke), now=now)
        return projection

    bill.entitlement = revoke_after_first_projection  # type: ignore[method-assign]
    with pytest.raises(PaidAuthorizationError) as caught:
        service.submit(
            principal(), request(), SecretStr("synthetic-input"), now=NOW
        )
    assert caught.value.reason is PaidReasonCode.ENTITLEMENT_MISSING
    assert calls == 2
    assert provider.call_count == 0
    assert store.spend_holds(ORG) == ()
    assert store.approval(ORG, APPROVAL).state is ApprovalState.AVAILABLE


def test_approval_mismatch_rolls_back_hold_and_never_calls_provider() -> None:
    store = DevelopmentPaidProductStore()
    bill = enable_and_budget(store)
    approvals = ApprovalService(store=store, transaction=store)
    approvals.register(approval())
    ids = DevelopmentPseudonymFactory(KEY)
    provider = SyntheticHostedAnalysisProvider(
        completed_at=NOW + timedelta(seconds=1),
        identifiers=ids,
        actual_cost_micro=40,
    )
    service = DeepAnalysisService(
        profile=ProductDeploymentProfile.DEVELOPMENT,
        authorizer=registered_authorizer(),
        billing=bill,
        approvals=approvals,
        jobs=store,
        audit=store,
        identifiers=ids,
        provider=provider,
        transaction=store,
        payload_pseudonymizer=DevelopmentPayloadPseudonymizer(KEY),
    )
    bad = request().model_copy(update={"window_fingerprint": pid("wrong-window")})
    with pytest.raises(ApprovalError) as caught:
        service.submit(principal(), bad, SecretStr("synthetic-input"), now=NOW)
    assert caught.value.reason is PaidReasonCode.APPROVAL_MISMATCH
    assert provider.call_count == 0
    assert store.spend_hold(ORG, HOLD) is None


@pytest.mark.parametrize(
    "bad_request",
    (
        request().model_copy(update={"estimated_cost_micro": 1}),
        request().model_copy(update={"payload_pseudonym": pid("wrong-payload")}),
    ),
)
def test_approval_requires_exact_cost_and_payload_binding(
    bad_request: DeepAnalysisRequest,
) -> None:
    store = DevelopmentPaidProductStore()
    bill = enable_and_budget(store)
    approvals = ApprovalService(store=store, transaction=store)
    approvals.register(approval())
    ids = DevelopmentPseudonymFactory(KEY)
    provider = SyntheticHostedAnalysisProvider(
        completed_at=NOW + timedelta(seconds=1),
        identifiers=ids,
        actual_cost_micro=1,
    )
    service = DeepAnalysisService(
        profile=ProductDeploymentProfile.DEVELOPMENT,
        authorizer=registered_authorizer(),
        billing=bill,
        approvals=approvals,
        jobs=store,
        audit=store,
        identifiers=ids,
        provider=provider,
        transaction=store,
        payload_pseudonymizer=DevelopmentPayloadPseudonymizer(KEY),
    )
    with pytest.raises(ApprovalError):
        service.submit(
            principal(), bad_request, SecretStr("synthetic-input"), now=NOW
        )
    assert provider.call_count == 0
    assert store.spend_holds(ORG) == ()


def test_same_length_payload_substitution_is_rejected_before_spend() -> None:
    store = DevelopmentPaidProductStore()
    bill = enable_and_budget(store)
    approvals = ApprovalService(store=store, transaction=store)
    approvals.register(approval())
    ids = DevelopmentPseudonymFactory(KEY)
    provider = SyntheticHostedAnalysisProvider(
        completed_at=NOW + timedelta(seconds=1),
        identifiers=ids,
        actual_cost_micro=40,
    )
    service = DeepAnalysisService(
        profile=ProductDeploymentProfile.DEVELOPMENT,
        authorizer=registered_authorizer(),
        billing=bill,
        approvals=approvals,
        jobs=store,
        audit=store,
        identifiers=ids,
        provider=provider,
        transaction=store,
        payload_pseudonymizer=DevelopmentPayloadPseudonymizer(KEY),
    )
    substituted = "synthetic-inpux"
    assert len(substituted.encode("utf-8")) == request().payload_bytes
    with pytest.raises(ApprovalError) as caught:
        service.submit(principal(), request(), SecretStr(substituted), now=NOW)
    assert caught.value.reason is PaidReasonCode.APPROVAL_MISMATCH
    assert provider.call_count == 0
    assert store.spend_holds(ORG) == ()


def test_deep_submit_never_nests_transaction_boundary() -> None:
    store = DevelopmentPaidProductStore()
    transaction = RejectNestedTransaction(store)
    bill = BillingService(
        store=store,
        transaction=transaction,
        verifier=DevelopmentWebhookVerifier(WEBHOOK_KEY),
    )
    bill.process_webhook(signed_webhook(), now=NOW)
    store.save_organization_spend_policy(
        OrganizationSpendPolicy(
            organization_id=ORG,
            organization_limit_micro=50,
        )
    )
    store.save_spend_policy(
        SpendPolicy(
            organization_id=ORG,
            user_id=USER,
            user_limit_micro=50,
        )
    )
    approvals = ApprovalService(store=store, transaction=transaction)
    approvals.register(approval())
    ids = DevelopmentPseudonymFactory(KEY)
    service = DeepAnalysisService(
        profile=ProductDeploymentProfile.DEVELOPMENT,
        authorizer=registered_authorizer(),
        billing=bill,
        approvals=approvals,
        jobs=store,
        audit=store,
        identifiers=ids,
        provider=SyntheticHostedAnalysisProvider(
            completed_at=NOW + timedelta(seconds=1),
            identifiers=ids,
            actual_cost_micro=40,
        ),
        transaction=transaction,
        payload_pseudonymizer=DevelopmentPayloadPseudonymizer(KEY),
    )
    assert service.submit(
        principal(), request(), SecretStr("synthetic-input"), now=NOW
    ).state is DeepJobState.COMPLETED


def test_missing_provider_usage_remains_unknown_and_hold_is_not_released() -> None:
    store = DevelopmentPaidProductStore()
    bill = enable_and_budget(store)
    approvals = ApprovalService(store=store, transaction=store)
    approvals.register(approval())
    ids = DevelopmentPseudonymFactory(KEY)
    service = DeepAnalysisService(
        profile=ProductDeploymentProfile.DEVELOPMENT,
        authorizer=registered_authorizer(),
        billing=bill,
        approvals=approvals,
        jobs=store,
        audit=store,
        identifiers=ids,
        provider=SyntheticHostedAnalysisProvider(
            completed_at=NOW + timedelta(seconds=1),
            identifiers=ids,
            actual_cost_micro=None,
        ),
        transaction=store,
        payload_pseudonymizer=DevelopmentPayloadPseudonymizer(KEY),
    )
    job = service.submit(
        principal(), request(), SecretStr("synthetic-input"), now=NOW
    )
    assert job.state is DeepJobState.COST_UNKNOWN
    hold = store.spend_hold(ORG, HOLD)
    assert hold.state is SpendHoldState.COST_UNKNOWN
    assert hold.settled_amount_micro is None


def test_provider_failure_is_content_free_and_retains_unknown_hold() -> None:
    store = DevelopmentPaidProductStore()
    bill = enable_and_budget(store)
    approvals = ApprovalService(store=store, transaction=store)
    approvals.register(approval())
    ids = DevelopmentPseudonymFactory(KEY)
    service = DeepAnalysisService(
        profile=ProductDeploymentProfile.DEVELOPMENT,
        authorizer=registered_authorizer(),
        billing=bill,
        approvals=approvals,
        jobs=store,
        audit=store,
        identifiers=ids,
        provider=SyntheticHostedAnalysisProvider(
            completed_at=NOW + timedelta(seconds=1),
            identifiers=ids,
            actual_cost_micro=None,
            fail=True,
        ),
        transaction=store,
        payload_pseudonymizer=DevelopmentPayloadPseudonymizer(KEY),
    )
    canary = "synthetic-input"
    with pytest.raises(ProviderInvocationError) as caught:
        service.submit(principal(), request(), SecretStr(canary), now=NOW)
    assert str(caught.value) == PaidReasonCode.PROVIDER_FAILED.value
    assert canary not in repr(store.__dict__)
    assert store.spend_hold(ORG, HOLD).state is SpendHoldState.COST_UNKNOWN


def test_provider_over_approval_cost_is_invalid_and_keeps_unknown_hold() -> None:
    store = DevelopmentPaidProductStore()
    bill = enable_and_budget(store)
    approvals = ApprovalService(store=store, transaction=store)
    approvals.register(approval())
    ids = DevelopmentPseudonymFactory(KEY)
    service = DeepAnalysisService(
        profile=ProductDeploymentProfile.DEVELOPMENT,
        authorizer=registered_authorizer(),
        billing=bill,
        approvals=approvals,
        jobs=store,
        audit=store,
        identifiers=ids,
        provider=SyntheticHostedAnalysisProvider(
            completed_at=NOW + timedelta(seconds=1),
            identifiers=ids,
            actual_cost_micro=51,
        ),
        transaction=store,
        payload_pseudonymizer=DevelopmentPayloadPseudonymizer(KEY),
    )
    with pytest.raises(ProviderInvocationError) as caught:
        service.submit(
            principal(), request(), SecretStr("synthetic-input"), now=NOW
        )
    assert caught.value.reason is PaidReasonCode.RESULT_INVALID
    assert store.spend_hold(ORG, HOLD).state is SpendHoldState.COST_UNKNOWN


def test_cross_tenant_and_revoked_device_fail_before_provider() -> None:
    store = DevelopmentPaidProductStore()
    bill = enable_and_budget(store)
    approvals = ApprovalService(store=store, transaction=store)
    approvals.register(approval())
    authorizer = DevelopmentPrincipalAuthorizer()
    authorizer.register(principal())
    authorizer.revoke_device(ORG, DEVICE)
    ids = DevelopmentPseudonymFactory(KEY)
    provider = SyntheticHostedAnalysisProvider(
        completed_at=NOW + timedelta(seconds=1),
        identifiers=ids,
        actual_cost_micro=40,
    )
    service = DeepAnalysisService(
        profile=ProductDeploymentProfile.DEVELOPMENT,
        authorizer=authorizer,
        billing=bill,
        approvals=approvals,
        jobs=store,
        audit=store,
        identifiers=ids,
        provider=provider,
        transaction=store,
        payload_pseudonymizer=DevelopmentPayloadPseudonymizer(KEY),
    )
    with pytest.raises(PaidAuthorizationError):
        service.submit(principal(), request(), SecretStr("synthetic-input"), now=NOW)
    with pytest.raises(PaidAuthorizationError) as cross:
        service.submit(
            principal(organization_id=pid("other-org")),
            request(),
            SecretStr("synthetic-input"),
            now=NOW,
        )
    assert cross.value.reason is PaidReasonCode.DEFAULT_DENY
    assert provider.call_count == 0


def test_development_never_contacts_official_destinations() -> None:
    store = DevelopmentPaidProductStore()
    bill = enable_and_budget(store)
    approvals = ApprovalService(store=store, transaction=store)
    ids = DevelopmentPseudonymFactory(KEY)
    provider = SyntheticHostedAnalysisProvider(
        completed_at=NOW + timedelta(seconds=1),
        identifiers=ids,
        actual_cost_micro=40,
    )
    service = DeepAnalysisService(
        profile=ProductDeploymentProfile.DEVELOPMENT,
        authorizer=registered_authorizer(),
        billing=bill,
        approvals=approvals,
        jobs=store,
        audit=store,
        identifiers=ids,
        provider=provider,
        transaction=store,
        payload_pseudonymizer=DevelopmentPayloadPseudonymizer(KEY),
    )
    official = request().model_copy(
        update={"destination": TenantJobDestination.OFFICIAL_OPENAI_API}
    )
    with pytest.raises(PaidAuthorizationError) as caught:
        service.submit(
            principal(), official, SecretStr("synthetic-input"), now=NOW
        )
    assert caught.value.reason is PaidReasonCode.DESTINATION_UNAVAILABLE
    assert provider.call_count == 0


def test_production_service_cannot_compose_synthetic_provider() -> None:
    store = DevelopmentPaidProductStore()
    ids = DevelopmentPseudonymFactory(KEY)
    with pytest.raises(ValueError, match="production_provider_composition_unavailable"):
        DeepAnalysisService(
            profile=ProductDeploymentProfile.PRODUCTION,
            authorizer=registered_authorizer(),
            billing=billing(store),
            approvals=ApprovalService(store=store, transaction=store),
            jobs=store,
            audit=store,
            identifiers=ids,
            provider=SyntheticHostedAnalysisProvider(
                completed_at=NOW,
                identifiers=ids,
                actual_cost_micro=1,
            ),
            transaction=store,
            payload_pseudonymizer=DevelopmentPayloadPseudonymizer(KEY),
        )


def test_deep_service_rejects_split_transaction_boundaries() -> None:
    store = DevelopmentPaidProductStore()
    billing_transaction = RejectNestedTransaction(store)
    approval_transaction = RejectNestedTransaction(store)
    ids = DevelopmentPseudonymFactory(KEY)
    with pytest.raises(ValueError, match="paid_product_transaction_boundary_mismatch"):
        DeepAnalysisService(
            profile=ProductDeploymentProfile.DEVELOPMENT,
            authorizer=registered_authorizer(),
            billing=BillingService(
                store=store,
                transaction=billing_transaction,
                verifier=DevelopmentWebhookVerifier(WEBHOOK_KEY),
            ),
            approvals=ApprovalService(
                store=store, transaction=approval_transaction
            ),
            jobs=store,
            audit=store,
            identifiers=ids,
            provider=SyntheticHostedAnalysisProvider(
                completed_at=NOW,
                identifiers=ids,
                actual_cost_micro=1,
            ),
            transaction=RejectNestedTransaction(store),
            payload_pseudonymizer=DevelopmentPayloadPseudonymizer(KEY),
        )
