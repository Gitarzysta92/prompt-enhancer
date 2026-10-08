"""Ports for identity, billing, approval, and hosted-analysis boundaries."""

from __future__ import annotations

from datetime import datetime
from types import TracebackType
from typing import Protocol

from pydantic import SecretStr

from .contracts import (
    Account,
    AccountIdentityBinding,
    DeepAnalysisJob,
    DeepAnalysisRequest,
    EntitlementFeature,
    EntitlementLedgerEntry,
    PaidAuditEvent,
    PaidPrincipal,
    PaidScope,
    ProviderResult,
    OrganizationSpendPolicy,
    RemoteAnalysisApproval,
    SignedBillingWebhook,
    SpendHold,
    SpendPolicy,
    TenantAccountBinding,
)


class TransactionBoundary(Protocol):
    """Single-entry atomic boundary; nesting is a composition error."""

    def __enter__(self) -> None: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class PseudonymFactory(Protocol):
    def new(self, namespace: str) -> str: ...


class SubjectPseudonymizer(Protocol):
    def pseudonymize(self, issuer_id: str, raw_subject: SecretStr) -> str: ...


class PayloadPseudonymizer(Protocol):
    """Installation-keyed payload binding; never a plain content hash."""

    def pseudonymize(self, approved_payload: SecretStr) -> str: ...


class InitialTenantBindingResolver(Protocol):
    """Server-owned invite/directory binding; never request-body identity."""

    def resolve(
        self, issuer_id: str, subject_pseudonym: str
    ) -> tuple[str, str] | None: ...


class IdentityStore(Protocol):
    def nonce_consumed(self, issuer_id: str, nonce_id: str) -> bool: ...

    def consume_nonce(self, issuer_id: str, nonce_id: str, *, at: datetime) -> None: ...

    def binding_by_subject(
        self, issuer_id: str, subject_pseudonym: str
    ) -> AccountIdentityBinding | None: ...

    def account(self, account_id: str) -> Account | None: ...

    def tenant_binding(
        self, organization_id: str, account_id: str
    ) -> TenantAccountBinding | None: ...

    def save_identity(
        self,
        account: Account,
        identity: AccountIdentityBinding,
        tenant: TenantAccountBinding,
    ) -> None: ...


class WebhookVerifier(Protocol):
    def verify(self, webhook: SignedBillingWebhook) -> bool: ...


class BillingStore(Protocol):
    def next_entitlement_sequence(self, organization_id: str) -> int: ...

    def webhook_digest(self, provider_event_id: str) -> str | None: ...

    def fence_webhook(self, provider_event_id: str, digest: str) -> None: ...

    def append_entitlement(self, entry: EntitlementLedgerEntry) -> None: ...

    def entitlement_entries(
        self, organization_id: str, feature: EntitlementFeature
    ) -> tuple[EntitlementLedgerEntry, ...]: ...

    def spend_policy(self, organization_id: str, user_id: str) -> SpendPolicy | None: ...

    def organization_spend_policy(
        self, organization_id: str
    ) -> OrganizationSpendPolicy | None: ...

    def save_spend_policy(self, policy: SpendPolicy) -> None: ...

    def save_organization_spend_policy(
        self, policy: OrganizationSpendPolicy
    ) -> None: ...

    def spend_holds(self, organization_id: str) -> tuple[SpendHold, ...]: ...

    def spend_hold(self, organization_id: str, hold_id: str) -> SpendHold | None: ...

    def save_spend_hold(self, hold: SpendHold) -> None: ...


class ApprovalStore(Protocol):
    def approval(
        self, organization_id: str, approval_id: str
    ) -> RemoteAnalysisApproval | None: ...

    def save_approval(self, approval: RemoteAnalysisApproval) -> None: ...


class JobStore(Protocol):
    def job(self, organization_id: str, job_id: str) -> DeepAnalysisJob | None: ...

    def save_job(self, job: DeepAnalysisJob) -> None: ...

    def queued_jobs(self) -> tuple[DeepAnalysisJob, ...]: ...


class AuditStore(Protocol):
    def append_audit(self, event: PaidAuditEvent) -> None: ...

    def audit_for_tenant(self, organization_id: str) -> tuple[PaidAuditEvent, ...]: ...


class PrincipalAuthorizer(Protocol):
    """Server-side current membership/device/client/scope resolver."""

    def allows(
        self,
        principal: PaidPrincipal,
        required_scope: PaidScope,
        *,
        now: datetime,
    ) -> bool: ...


class HostedAnalysisProvider(Protocol):
    @property
    def destination(self): ...

    @property
    def production_ready(self) -> bool: ...

    def analyze(
        self, request: DeepAnalysisRequest, approved_payload: SecretStr
    ) -> ProviderResult: ...


__all__ = [
    "ApprovalStore",
    "AuditStore",
    "BillingStore",
    "HostedAnalysisProvider",
    "InitialTenantBindingResolver",
    "IdentityStore",
    "JobStore",
    "PrincipalAuthorizer",
    "PseudonymFactory",
    "PayloadPseudonymizer",
    "SubjectPseudonymizer",
    "TransactionBoundary",
    "WebhookVerifier",
]
