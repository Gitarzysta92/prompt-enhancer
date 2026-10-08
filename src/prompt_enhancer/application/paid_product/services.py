"""Application services for the paid-product development foundation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from pydantic import SecretStr

from .contracts import (
    Account,
    AccountIdentityBinding,
    ApprovalState,
    DeepAnalysisJob,
    DeepAnalysisRequest,
    DeepJobState,
    EntitlementDeltaKind,
    EntitlementFeature,
    EntitlementLedgerEntry,
    EntitlementProjection,
    OrganizationSpendPolicy,
    PaidAuditAction,
    PaidAuditEvent,
    PaidPrincipal,
    PaidReasonCode,
    PaidScope,
    ProductDeploymentProfile,
    ProviderResult,
    RemoteAnalysisApproval,
    SignedBillingWebhook,
    SpendHold,
    SpendHoldState,
    SpendPolicy,
    TenantAccountBinding,
    TenantJobDestination,
    VerifiedOidcAssertion,
    WebhookDisposition,
)
from .errors import (
    ApprovalError,
    BillingWebhookError,
    PaidAuthorizationError,
    ProviderInvocationError,
    SpendLimitError,
)
from .ports import (
    ApprovalStore,
    AuditStore,
    BillingStore,
    HostedAnalysisProvider,
    IdentityStore,
    InitialTenantBindingResolver,
    JobStore,
    PrincipalAuthorizer,
    PseudonymFactory,
    PayloadPseudonymizer,
    SubjectPseudonymizer,
    TransactionBoundary,
    WebhookVerifier,
)


WEBHOOK_MAX_AGE = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class SignedInIdentity:
    account: Account
    identity: AccountIdentityBinding
    tenant: TenantAccountBinding


class ProductIdentityService:
    def __init__(
        self,
        *,
        store: IdentityStore,
        transaction: TransactionBoundary,
        pseudonymizer: SubjectPseudonymizer,
        tenant_bindings: InitialTenantBindingResolver,
        identifiers: PseudonymFactory,
        allowed_issuer: str,
        allowed_audience: str,
    ) -> None:
        self._store = store
        self._transaction = transaction
        self._pseudonymizer = pseudonymizer
        self._tenant_bindings = tenant_bindings
        self._identifiers = identifiers
        self._allowed_issuer = allowed_issuer
        self._allowed_audience = allowed_audience

    def sign_in(
        self,
        assertion: VerifiedOidcAssertion,
        *,
        now: datetime,
    ) -> SignedInIdentity:
        # Deliberately collapse every assertion failure to one reason.
        if (
            assertion.issuer_id != self._allowed_issuer
            or assertion.audience != self._allowed_audience
            or assertion.issued_at > now
            or assertion.expires_at <= now
        ):
            raise PaidAuthorizationError(PaidReasonCode.OIDC_ASSERTION_INVALID)
        # A verified nonce is consumed even if directory binding later denies the
        # sign-in.  Retrying after an authorization failure must not replay the
        # identity-provider assertion.
        with self._transaction:
            if self._store.nonce_consumed(assertion.issuer_id, assertion.nonce_id):
                raise PaidAuthorizationError(PaidReasonCode.OIDC_NONCE_REPLAYED)
            self._store.consume_nonce(assertion.issuer_id, assertion.nonce_id, at=now)
        with self._transaction:
            subject = self._pseudonymizer.pseudonymize(
                assertion.issuer_id, assertion.raw_subject
            )
            tenant_identity = self._tenant_bindings.resolve(
                assertion.issuer_id, subject
            )
            if tenant_identity is None:
                raise PaidAuthorizationError(PaidReasonCode.DEFAULT_DENY)
            organization_id, user_id = tenant_identity
            identity = self._store.binding_by_subject(assertion.issuer_id, subject)
            if identity is None:
                account = Account(
                    account_id=self._identifiers.new("account"), created_at=now
                )
                identity = AccountIdentityBinding(
                    account_id=account.account_id,
                    issuer_id=assertion.issuer_id,
                    subject_pseudonym=subject,
                    created_at=now,
                )
                tenant = TenantAccountBinding(
                    organization_id=organization_id,
                    account_id=account.account_id,
                    user_id=user_id,
                    created_at=now,
                )
                try:
                    self._store.save_identity(account, identity, tenant)
                except ValueError:
                    raise PaidAuthorizationError(PaidReasonCode.DEFAULT_DENY) from None
            else:
                account = self._store.account(identity.account_id)
                tenant = self._store.tenant_binding(organization_id, identity.account_id)
                if account is None or tenant is None or tenant.user_id != user_id:
                    raise PaidAuthorizationError(PaidReasonCode.DEFAULT_DENY)
                if account.disabled_at is not None:
                    raise PaidAuthorizationError(PaidReasonCode.PRINCIPAL_INACTIVE)
            return SignedInIdentity(account=account, identity=identity, tenant=tenant)


class BillingService:
    def __init__(
        self,
        *,
        store: BillingStore,
        transaction: TransactionBoundary,
        verifier: WebhookVerifier,
    ) -> None:
        self._store = store
        self._transaction = transaction
        self._verifier = verifier

    def process_webhook(
        self, webhook: SignedBillingWebhook, *, now: datetime
    ) -> WebhookDisposition:
        if not self._verifier.verify(webhook):
            raise BillingWebhookError(PaidReasonCode.WEBHOOK_SIGNATURE_INVALID)
        if abs(now - webhook.delivered_at) > WEBHOOK_MAX_AGE:
            raise BillingWebhookError(PaidReasonCode.WEBHOOK_STALE)
        with self._transaction:
            known = self._store.webhook_digest(webhook.provider_event_id)
            if known is not None:
                if known != webhook.provider_event_digest:
                    raise BillingWebhookError(PaidReasonCode.WEBHOOK_CONFLICT)
                return WebhookDisposition.IDEMPOTENT_REPLAY
            entry = EntitlementLedgerEntry(
                entry_id=webhook.entry_id,
                organization_id=webhook.organization_id,
                provider_event_id=webhook.provider_event_id,
                provider_event_digest=webhook.provider_event_digest,
                ledger_sequence=self._store.next_entitlement_sequence(
                    webhook.organization_id
                ),
                feature=webhook.feature,
                kind=webhook.kind,
                effective_at=webhook.effective_at,
                expires_at=webhook.expires_at,
                recorded_at=now,
            )
            # The replay fence and ledger append share the adapter transaction.
            self._store.fence_webhook(
                webhook.provider_event_id, webhook.provider_event_digest
            )
            self._store.append_entitlement(entry)
            return WebhookDisposition.APPLIED

    def entitlement(
        self,
        organization_id: str,
        feature: EntitlementFeature,
        *,
        now: datetime,
    ) -> EntitlementProjection:
        applicable = tuple(
            entry
            for entry in self._store.entitlement_entries(organization_id, feature)
            if entry.effective_at <= now
        )
        if not applicable:
            return EntitlementProjection(
                organization_id=organization_id,
                feature=feature,
                enabled=False,
                effective_at=None,
                expires_at=None,
                projected_at=now,
            )
        latest = max(
            applicable,
            key=lambda item: (
                item.effective_at,
                item.recorded_at,
                item.ledger_sequence,
            ),
        )
        enabled = latest.kind in {
            EntitlementDeltaKind.GRANT,
            EntitlementDeltaKind.ADJUSTMENT,
        }
        if latest.expires_at is not None and latest.expires_at <= now:
            enabled = False
        return EntitlementProjection(
            organization_id=organization_id,
            feature=feature,
            enabled=enabled,
            effective_at=latest.effective_at,
            expires_at=latest.expires_at,
            projected_at=now,
        )

    def reserve_spend(
        self,
        *,
        hold_id: str,
        organization_id: str,
        user_id: str,
        job_id: str,
        amount_micro: int,
        now: datetime,
    ) -> SpendHold:
        with self._transaction:
            return self._reserve_spend_locked(
                hold_id=hold_id,
                organization_id=organization_id,
                user_id=user_id,
                job_id=job_id,
                amount_micro=amount_micro,
                now=now,
            )

    def _reserve_spend_locked(
        self,
        *,
        hold_id: str,
        organization_id: str,
        user_id: str,
        job_id: str,
        amount_micro: int,
        now: datetime,
    ) -> SpendHold:
        existing = self._store.spend_hold(organization_id, hold_id)
        if existing is not None:
            if (
                existing.state is SpendHoldState.HELD
                and existing.user_id == user_id
                and existing.job_id == job_id
                and existing.amount_micro == amount_micro
            ):
                return existing
            raise SpendLimitError(PaidReasonCode.DEFAULT_DENY)
        policy = self._store.spend_policy(organization_id, user_id)
        organization_policy = self._store.organization_spend_policy(
            organization_id
        )
        if policy is None or organization_policy is None:
            raise SpendLimitError(PaidReasonCode.SPEND_LIMIT_EXCEEDED)
        if policy.currency != organization_policy.currency:
            raise SpendLimitError(PaidReasonCode.DEFAULT_DENY)
        counted = {
            SpendHoldState.HELD,
            SpendHoldState.SETTLED,
            SpendHoldState.COST_UNKNOWN,
        }
        rows = tuple(
            row for row in self._store.spend_holds(organization_id) if row.state in counted
        )
        org_used = sum(
            row.settled_amount_micro
            if row.state is SpendHoldState.SETTLED
            else row.amount_micro
            for row in rows
        )
        user_used = sum(
            row.settled_amount_micro
            if row.state is SpendHoldState.SETTLED
            else row.amount_micro
            for row in rows
            if row.user_id == user_id
        )
        if (
            org_used + amount_micro
            > organization_policy.organization_limit_micro
            or user_used + amount_micro > policy.user_limit_micro
        ):
            raise SpendLimitError(PaidReasonCode.SPEND_LIMIT_EXCEEDED)
        hold = SpendHold(
            hold_id=hold_id,
            organization_id=organization_id,
            user_id=user_id,
            job_id=job_id,
            amount_micro=amount_micro,
            state=SpendHoldState.HELD,
            created_at=now,
        )
        self._store.save_spend_hold(hold)
        return hold

    def settle_spend(
        self,
        organization_id: str,
        hold_id: str,
        *,
        actual_cost_micro: int | None,
        now: datetime,
    ) -> SpendHold:
        with self._transaction:
            return self._settle_spend_locked(
                organization_id,
                hold_id,
                actual_cost_micro=actual_cost_micro,
                now=now,
            )

    def _settle_spend_locked(
        self,
        organization_id: str,
        hold_id: str,
        *,
        actual_cost_micro: int | None,
        now: datetime,
    ) -> SpendHold:
        hold = self._store.spend_hold(organization_id, hold_id)
        if hold is None or hold.state not in {
            SpendHoldState.HELD,
            SpendHoldState.COST_UNKNOWN,
        }:
            raise SpendLimitError(PaidReasonCode.DEFAULT_DENY)
        if actual_cost_micro is None:
            updated = SpendHold.model_validate(
                {**hold.model_dump(), "state": SpendHoldState.COST_UNKNOWN}
            )
        else:
            if actual_cost_micro > hold.amount_micro:
                updated = SpendHold.model_validate(
                    {**hold.model_dump(), "state": SpendHoldState.COST_UNKNOWN}
                )
            else:
                updated = SpendHold.model_validate(
                    {
                        **hold.model_dump(),
                        "state": SpendHoldState.SETTLED,
                        "settled_amount_micro": actual_cost_micro,
                        "settled_at": now,
                    }
                )
        self._store.save_spend_hold(updated)
        return updated

    def release_spend(
        self, organization_id: str, hold_id: str, *, now: datetime
    ) -> SpendHold:
        with self._transaction:
            hold = self._store.spend_hold(organization_id, hold_id)
            if hold is None or hold.state is not SpendHoldState.HELD:
                raise SpendLimitError(PaidReasonCode.DEFAULT_DENY)
            updated = SpendHold.model_validate(
                {
                    **hold.model_dump(),
                    "state": SpendHoldState.RELEASED,
                    "settled_at": now,
                }
            )
            self._store.save_spend_hold(updated)
            return updated


class ApprovalService:
    def __init__(
        self, *, store: ApprovalStore, transaction: TransactionBoundary
    ) -> None:
        self._store = store
        self._transaction = transaction

    def register(self, approval: RemoteAnalysisApproval) -> None:
        if approval.state is not ApprovalState.AVAILABLE:
            raise ApprovalError(PaidReasonCode.APPROVAL_MISMATCH)
        with self._transaction:
            if self._store.approval(approval.organization_id, approval.approval_id) is not None:
                raise ApprovalError(PaidReasonCode.DEFAULT_DENY)
            self._store.save_approval(approval)

    def consume(
        self,
        request: DeepAnalysisRequest,
        *,
        now: datetime,
    ) -> RemoteAnalysisApproval:
        with self._transaction:
            return self._consume_locked(request, now=now)

    def _consume_locked(
        self, request: DeepAnalysisRequest, *, now: datetime
    ) -> RemoteAnalysisApproval:
        approval = self._store.approval(request.organization_id, request.approval_id)
        if approval is None:
            raise ApprovalError(PaidReasonCode.APPROVAL_MISSING)
        if approval.state is ApprovalState.CONSUMED:
            raise ApprovalError(PaidReasonCode.APPROVAL_REPLAYED)
        if approval.state is ApprovalState.REVOKED:
            raise ApprovalError(PaidReasonCode.APPROVAL_MISSING)
        if approval.expires_at <= now:
            raise ApprovalError(PaidReasonCode.APPROVAL_EXPIRED)
        exact = (
            approval.organization_id == request.organization_id
            and approval.user_id == request.user_id
            and approval.provider is request.destination
            and approval.model_id == request.model_id
            and approval.window_fingerprint == request.window_fingerprint
            and approval.payload_pseudonym == request.payload_pseudonym
            and approval.metric_keys == request.metric_keys
            and approval.redactor_version == request.redactor_version
            and approval.retention_class is request.retention_class
            and approval.approved_payload_bytes == request.payload_bytes
            and request.estimated_cost_micro == approval.max_cost_micro
        )
        if not exact:
            raise ApprovalError(PaidReasonCode.APPROVAL_MISMATCH)
        consumed = RemoteAnalysisApproval.model_validate(
            {
                **approval.model_dump(),
                "state": ApprovalState.CONSUMED,
                "consumed_at": now,
            }
        )
        self._store.save_approval(consumed)
        return consumed


class DeepAnalysisService:
    def __init__(
        self,
        *,
        profile: ProductDeploymentProfile,
        authorizer: PrincipalAuthorizer,
        billing: BillingService,
        approvals: ApprovalService,
        jobs: JobStore,
        audit: AuditStore,
        identifiers: PseudonymFactory,
        provider: HostedAnalysisProvider,
        transaction: TransactionBoundary,
        payload_pseudonymizer: PayloadPseudonymizer,
    ) -> None:
        self._profile = profile
        self._authorizer = authorizer
        self._billing = billing
        self._approvals = approvals
        self._jobs = jobs
        self._audit = audit
        self._identifiers = identifiers
        self._provider = provider
        self._transaction = transaction
        self._payload_pseudonymizer = payload_pseudonymizer
        if billing._transaction is not transaction or approvals._transaction is not transaction:
            raise ValueError("paid_product_transaction_boundary_mismatch")
        if profile is ProductDeploymentProfile.DEVELOPMENT:
            if (
                provider.destination is not TenantJobDestination.SYNTHETIC_TEST
                or provider.production_ready
            ):
                raise ValueError("development_provider_composition_invalid")
        elif not provider.production_ready or provider.destination not in {
            TenantJobDestination.OFFICIAL_OPENAI_API,
            TenantJobDestination.OFFICIAL_ANTHROPIC_API,
        }:
            raise ValueError("production_provider_composition_unavailable")

    def _audit_event(
        self,
        principal: PaidPrincipal,
        action: PaidAuditAction,
        *,
        allowed: bool,
        now: datetime,
        reason: PaidReasonCode | None = None,
    ) -> None:
        self._audit.append_audit(
            PaidAuditEvent(
                event_id=self._identifiers.new("paid-audit"),
                organization_id=principal.organization_id,
                actor_user_id=principal.user_id,
                action=action,
                allowed=allowed,
                reason=reason,
                occurred_at=now,
            )
        )

    def submit(
        self,
        principal: PaidPrincipal,
        request: DeepAnalysisRequest,
        approved_payload: SecretStr,
        *,
        now: datetime,
    ) -> DeepAnalysisJob:
        if (
            principal.organization_id != request.organization_id
            or principal.user_id != request.user_id
        ):
            with self._transaction:
                self._audit_event(
                    principal,
                    PaidAuditAction.ACCESS_DENIED,
                    allowed=False,
                    now=now,
                    reason=PaidReasonCode.CROSS_TENANT,
                )
            raise PaidAuthorizationError(PaidReasonCode.DEFAULT_DENY)
        if not self._authorizer.allows(
            principal, PaidScope.JOBS_SUBMIT, now=now
        ):
            raise PaidAuthorizationError(PaidReasonCode.DEFAULT_DENY)
        if request.destination is not self._provider.destination:
            raise PaidAuthorizationError(PaidReasonCode.DESTINATION_UNAVAILABLE)
        if request.destination is TenantJobDestination.SYNTHETIC_TEST:
            if self._profile is not ProductDeploymentProfile.DEVELOPMENT:
                raise PaidAuthorizationError(PaidReasonCode.DESTINATION_UNAVAILABLE)
        elif self._profile is ProductDeploymentProfile.DEVELOPMENT:
            # Development never contacts commercial APIs.
            raise PaidAuthorizationError(PaidReasonCode.DESTINATION_UNAVAILABLE)
        entitlement = self._billing.entitlement(
            request.organization_id,
            EntitlementFeature.HOSTED_DEEP_ANALYSIS,
            now=now,
        )
        if not entitlement.enabled:
            raise PaidAuthorizationError(PaidReasonCode.ENTITLEMENT_MISSING)
        if len(approved_payload.get_secret_value().encode("utf-8")) != request.payload_bytes:
            raise ApprovalError(PaidReasonCode.APPROVAL_MISMATCH)
        if (
            self._payload_pseudonymizer.pseudonymize(approved_payload)
            != request.payload_pseudonym
        ):
            raise ApprovalError(PaidReasonCode.APPROVAL_MISMATCH)
        with self._transaction:
            existing = self._jobs.job(request.organization_id, request.job_id)
            if existing is not None:
                if (
                    existing.user_id == request.user_id
                    and existing.destination is request.destination
                    and existing.model_id == request.model_id
                    and existing.metric_keys == request.metric_keys
                ):
                    return existing
                raise PaidAuthorizationError(PaidReasonCode.DEFAULT_DENY)
            # Entitlement may be revoked after the early, inexpensive reject
            # check.  Re-project it while holding the same write transaction
            # that creates the spend hold and queued job so a revocation that
            # won the ledger race cannot authorize new work.
            current_entitlement = self._billing.entitlement(
                request.organization_id,
                EntitlementFeature.HOSTED_DEEP_ANALYSIS,
                now=now,
            )
            if not current_entitlement.enabled:
                raise PaidAuthorizationError(PaidReasonCode.ENTITLEMENT_MISSING)
            hold = self._billing._reserve_spend_locked(
                hold_id=request.hold_id,
                organization_id=request.organization_id,
                user_id=request.user_id,
                job_id=request.job_id,
                amount_micro=request.estimated_cost_micro,
                now=now,
            )
            self._approvals._consume_locked(request, now=now)
            queued = DeepAnalysisJob(
                job_id=request.job_id,
                organization_id=request.organization_id,
                user_id=request.user_id,
                destination=request.destination,
                model_id=request.model_id,
                metric_keys=request.metric_keys,
                state=DeepJobState.QUEUED,
                requested_at=request.requested_at,
            )
            self._jobs.save_job(queued)
        try:
            result = self._provider.analyze(request, approved_payload)
            self._validate_result(request, result)
        except ProviderInvocationError as exc:
            failure_reason = exc.reason
            with self._transaction:
                self._billing._settle_spend_locked(
                    request.organization_id,
                    hold.hold_id,
                    actual_cost_micro=None,
                    now=now,
                )
                failed = DeepAnalysisJob.model_validate(
                    {
                        **queued.model_dump(),
                        "state": DeepJobState.COST_UNKNOWN,
                        "completed_at": now,
                        "reason": failure_reason,
                    }
                )
                self._jobs.save_job(failed)
                self._audit_event(
                    principal,
                    PaidAuditAction.JOB_FAILED,
                    allowed=False,
                    now=now,
                    reason=failure_reason,
                )
            raise
        except Exception:
            with self._transaction:
                self._billing._settle_spend_locked(
                    request.organization_id,
                    hold.hold_id,
                    actual_cost_micro=None,
                    now=now,
                )
                failed = DeepAnalysisJob.model_validate(
                    {
                        **queued.model_dump(),
                        "state": DeepJobState.COST_UNKNOWN,
                        "completed_at": now,
                        "reason": PaidReasonCode.PROVIDER_FAILED,
                    }
                )
                self._jobs.save_job(failed)
                self._audit_event(
                    principal,
                    PaidAuditAction.JOB_FAILED,
                    allowed=False,
                    now=now,
                    reason=PaidReasonCode.PROVIDER_FAILED,
                )
            raise ProviderInvocationError(PaidReasonCode.PROVIDER_FAILED) from None
        with self._transaction:
            settled = self._billing._settle_spend_locked(
                request.organization_id,
                hold.hold_id,
                actual_cost_micro=result.actual_cost_micro,
                now=now,
            )
            state = (
                DeepJobState.COST_UNKNOWN
                if settled.state is SpendHoldState.COST_UNKNOWN
                else DeepJobState.COMPLETED
            )
            completed = DeepAnalysisJob.model_validate(
                {
                    **queued.model_dump(),
                    "state": state,
                    "completed_at": result.completed_at,
                    "provider_receipt_id": result.provider_receipt_id,
                    "judgments": result.judgments,
                    "reason": (
                        PaidReasonCode.COST_UNKNOWN
                        if state is DeepJobState.COST_UNKNOWN
                        else None
                    ),
                }
            )
            self._jobs.save_job(completed)
            self._audit_event(
                principal,
                PaidAuditAction.JOB_COMPLETED,
                allowed=True,
                now=now,
                reason=completed.reason,
            )
            return completed

    def reconcile_after_restart(self, *, now: datetime) -> tuple[DeepAnalysisJob, ...]:
        """Fail closed any durable job stranded before a provider receipt.

        Provider calls are never replayed automatically: the original one-shot
        approval was consumed before the call.  A queued receipt discovered at
        startup therefore becomes ``cost_unknown`` and keeps the full hold
        counted until an audited operator reconciliation supplies real usage.
        """

        recovered: list[DeepAnalysisJob] = []
        for queued in self._jobs.queued_jobs():
            with self._transaction:
                current = self._jobs.job(queued.organization_id, queued.job_id)
                if current is None or current.state is not DeepJobState.QUEUED:
                    continue
                matching_holds = tuple(
                    hold
                    for hold in self._billing._store.spend_holds(
                        queued.organization_id
                    )
                    if hold.job_id == queued.job_id
                )
                if len(matching_holds) != 1 or matching_holds[0].state not in {
                    SpendHoldState.HELD,
                    SpendHoldState.COST_UNKNOWN,
                }:
                    raise RuntimeError("paid_product_queued_job_graph_invalid")
                self._billing._settle_spend_locked(
                    queued.organization_id,
                    matching_holds[0].hold_id,
                    actual_cost_micro=None,
                    now=now,
                )
                failed = DeepAnalysisJob.model_validate(
                    {
                        **queued.model_dump(),
                        "state": DeepJobState.COST_UNKNOWN,
                        "completed_at": now,
                        "reason": PaidReasonCode.PROVIDER_FAILED,
                    }
                )
                self._jobs.save_job(failed)
                self._audit.append_audit(
                    PaidAuditEvent(
                        event_id=self._identifiers.new("paid-audit"),
                        organization_id=queued.organization_id,
                        actor_user_id=queued.user_id,
                        action=PaidAuditAction.JOB_FAILED,
                        allowed=False,
                        reason=PaidReasonCode.PROVIDER_FAILED,
                        occurred_at=now,
                    )
                )
                recovered.append(failed)
        return tuple(recovered)

    @staticmethod
    def _validate_result(
        request: DeepAnalysisRequest, result: ProviderResult
    ) -> None:
        keys = tuple(item.metric_key for item in result.judgments)
        if (
            result.destination is not request.destination
            or result.model_id != request.model_id
            or keys != request.metric_keys
            or result.completed_at < request.requested_at
            or (
                result.actual_cost_micro is not None
                and result.actual_cost_micro > request.estimated_cost_micro
            )
        ):
            raise ProviderInvocationError(PaidReasonCode.RESULT_INVALID)


__all__ = [
    "ApprovalService",
    "BillingService",
    "DeepAnalysisService",
    "ProductIdentityService",
    "SignedInIdentity",
]
