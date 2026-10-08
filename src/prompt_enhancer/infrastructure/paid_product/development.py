"""Locked, offline-only development adapters for the paid-product boundary."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import hashlib
import hmac
import json
from threading import RLock

from pydantic import SecretStr

from ...application.paid_product.contracts import (
    Account,
    AccountIdentityBinding,
    DeepAnalysisJob,
    DeepAnalysisRequest,
    DeepJobState,
    EntitlementFeature,
    EntitlementLedgerEntry,
    MetricJudgment,
    OrganizationSpendPolicy,
    PaidAuditEvent,
    PaidPrincipal,
    PaidScope,
    ProviderResult,
    RemoteAnalysisApproval,
    SignedBillingWebhook,
    SpendHold,
    SpendPolicy,
    TenantAccountBinding,
    TenantJobDestination,
)


def _digest(key: bytes, value: str) -> str:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


class DevelopmentPseudonymFactory:
    """Process-local deterministic IDs; never a production identifier source."""

    def __init__(self, key: bytes) -> None:
        if len(key) < 32:
            raise ValueError("development pseudonym key must have at least 32 bytes")
        self._key = key
        self._lock = RLock()
        self._counter = 0

    def new(self, namespace: str) -> str:
        with self._lock:
            self._counter += 1
            return _digest(self._key, f"{namespace}:{self._counter}")


class DevelopmentSubjectPseudonymizer:
    def __init__(self, key: bytes) -> None:
        if len(key) < 32:
            raise ValueError("development subject key must have at least 32 bytes")
        self._key = key

    def pseudonymize(self, issuer_id: str, raw_subject: SecretStr) -> str:
        return _digest(
            self._key, f"{issuer_id}\x00{raw_subject.get_secret_value()}"
        )


class DevelopmentPayloadPseudonymizer:
    def __init__(self, key: bytes) -> None:
        if len(key) < 32:
            raise ValueError("development payload key must have at least 32 bytes")
        self._key = key

    def pseudonymize(self, approved_payload: SecretStr) -> str:
        return _digest(self._key, approved_payload.get_secret_value())


class DevelopmentTenantBindingResolver:
    """Server-seeded invite/directory projection for synthetic tests."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._bindings: dict[tuple[str, str], tuple[str, str]] = {}

    def bind(
        self,
        issuer_id: str,
        subject_pseudonym: str,
        organization_id: str,
        user_id: str,
    ) -> None:
        with self._lock:
            self._bindings[(issuer_id, subject_pseudonym)] = (
                organization_id,
                user_id,
            )

    def resolve(
        self, issuer_id: str, subject_pseudonym: str
    ) -> tuple[str, str] | None:
        with self._lock:
            return self._bindings.get((issuer_id, subject_pseudonym))


def canonical_webhook_digest(webhook: SignedBillingWebhook) -> str:
    material = {
        "delivered_at": webhook.delivered_at.isoformat(),
        "effective_at": webhook.effective_at.isoformat(),
        "entry_id": webhook.entry_id,
        "expires_at": (
            webhook.expires_at.isoformat() if webhook.expires_at is not None else None
        ),
        "feature": webhook.feature.value,
        "kind": webhook.kind.value,
        "organization_id": webhook.organization_id,
        "provider_event_id": webhook.provider_event_id,
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode(
        "ascii"
    )
    return hashlib.sha256(encoded).hexdigest()


def canonical_webhook_signature(webhook: SignedBillingWebhook, key: bytes) -> str:
    return hmac.new(
        key, canonical_webhook_digest(webhook).encode("ascii"), hashlib.sha256
    ).hexdigest()


class DevelopmentWebhookVerifier:
    def __init__(self, key: bytes) -> None:
        if len(key) < 32:
            raise ValueError("development webhook key must have at least 32 bytes")
        self._key = key

    def verify(self, webhook: SignedBillingWebhook) -> bool:
        expected_digest = canonical_webhook_digest(webhook)
        expected_signature = hmac.new(
            self._key, expected_digest.encode("ascii"), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(webhook.provider_event_digest, expected_digest) and hmac.compare_digest(
            webhook.signature.get_secret_value(), expected_signature
        )


class DevelopmentPaidProductStore:
    """One lock-backed adapter set for deterministic synthetic tests."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._transaction_snapshots: list[tuple[object, ...]] = []
        self._nonces: set[tuple[str, str]] = set()
        self._accounts: dict[str, Account] = {}
        self._identity_by_subject: dict[tuple[str, str], AccountIdentityBinding] = {}
        self._tenant_bindings: dict[tuple[str, str], TenantAccountBinding] = {}
        self._account_by_tenant_user: dict[tuple[str, str], str] = {}
        self._webhook_fences: dict[str, str] = {}
        self._entitlements: list[EntitlementLedgerEntry] = []
        self._spend_policies: dict[tuple[str, str], SpendPolicy] = {}
        self._organization_spend_policies: dict[str, OrganizationSpendPolicy] = {}
        self._spend_holds: dict[tuple[str, str], SpendHold] = {}
        self._approvals: dict[tuple[str, str], RemoteAnalysisApproval] = {}
        self._jobs: dict[tuple[str, str], DeepAnalysisJob] = {}
        self._audits: list[PaidAuditEvent] = []

    def __enter__(self) -> None:
        self._lock.acquire()
        self._transaction_snapshots.append(self._snapshot())

    def __exit__(self, exc_type, exc, traceback) -> None:
        snapshot = self._transaction_snapshots.pop()
        if exc_type is not None:
            self._restore(snapshot)
        self._lock.release()

    def _snapshot(self) -> tuple[object, ...]:
        return (
            set(self._nonces),
            dict(self._accounts),
            dict(self._identity_by_subject),
            dict(self._tenant_bindings),
            dict(self._account_by_tenant_user),
            dict(self._webhook_fences),
            list(self._entitlements),
            dict(self._spend_policies),
            dict(self._organization_spend_policies),
            dict(self._spend_holds),
            dict(self._approvals),
            dict(self._jobs),
            list(self._audits),
        )

    def _restore(self, snapshot: tuple[object, ...]) -> None:
        (
            self._nonces,
            self._accounts,
            self._identity_by_subject,
            self._tenant_bindings,
            self._account_by_tenant_user,
            self._webhook_fences,
            self._entitlements,
            self._spend_policies,
            self._organization_spend_policies,
            self._spend_holds,
            self._approvals,
            self._jobs,
            self._audits,
        ) = snapshot

    def nonce_consumed(self, issuer_id: str, nonce_id: str) -> bool:
        with self._lock:
            return (issuer_id, nonce_id) in self._nonces

    def consume_nonce(self, issuer_id: str, nonce_id: str, *, at: datetime) -> None:
        del at
        with self._lock:
            key = (issuer_id, nonce_id)
            if key in self._nonces:
                raise ValueError("nonce_already_consumed")
            self._nonces.add(key)

    def binding_by_subject(
        self, issuer_id: str, subject_pseudonym: str
    ) -> AccountIdentityBinding | None:
        with self._lock:
            return self._identity_by_subject.get((issuer_id, subject_pseudonym))

    def account(self, account_id: str) -> Account | None:
        with self._lock:
            return self._accounts.get(account_id)

    def tenant_binding(
        self, organization_id: str, account_id: str
    ) -> TenantAccountBinding | None:
        with self._lock:
            return self._tenant_bindings.get((organization_id, account_id))

    def save_identity(
        self,
        account: Account,
        identity: AccountIdentityBinding,
        tenant: TenantAccountBinding,
    ) -> None:
        with self._lock:
            subject_key = (identity.issuer_id, identity.subject_pseudonym)
            if identity.account_id != account.account_id or tenant.account_id != account.account_id:
                raise ValueError("identity_binding_mismatch")
            if subject_key in self._identity_by_subject:
                raise ValueError("identity_already_exists")
            tenant_user_key = (tenant.organization_id, tenant.user_id)
            existing_account = self._account_by_tenant_user.get(tenant_user_key)
            if existing_account is not None and existing_account != account.account_id:
                raise ValueError("tenant_user_already_bound")
            self._accounts[account.account_id] = account
            self._identity_by_subject[subject_key] = identity
            self._tenant_bindings[(tenant.organization_id, tenant.account_id)] = tenant
            self._account_by_tenant_user[tenant_user_key] = account.account_id

    def webhook_digest(self, provider_event_id: str) -> str | None:
        with self._lock:
            return self._webhook_fences.get(provider_event_id)

    def next_entitlement_sequence(self, organization_id: str) -> int:
        with self._lock:
            return 1 + max(
                (
                    row.ledger_sequence
                    for row in self._entitlements
                    if row.organization_id == organization_id
                ),
                default=0,
            )

    def fence_webhook(self, provider_event_id: str, digest: str) -> None:
        with self._lock:
            existing = self._webhook_fences.get(provider_event_id)
            if existing is not None and existing != digest:
                raise ValueError("webhook_conflict")
            self._webhook_fences[provider_event_id] = digest

    def append_entitlement(self, entry: EntitlementLedgerEntry) -> None:
        with self._lock:
            if any(row.entry_id == entry.entry_id for row in self._entitlements):
                raise ValueError("entitlement_entry_exists")
            self._entitlements.append(entry)

    def entitlement_entries(
        self, organization_id: str, feature: EntitlementFeature
    ) -> tuple[EntitlementLedgerEntry, ...]:
        with self._lock:
            return tuple(
                row
                for row in self._entitlements
                if row.organization_id == organization_id and row.feature is feature
            )

    def delete_entitlement_rows(self, organization_id: str) -> None:
        """Development erasure helper; consumed webhook fences intentionally remain."""

        with self._lock:
            self._entitlements = [
                row for row in self._entitlements if row.organization_id != organization_id
            ]

    def spend_policy(self, organization_id: str, user_id: str) -> SpendPolicy | None:
        with self._lock:
            return self._spend_policies.get((organization_id, user_id))

    def save_spend_policy(self, policy: SpendPolicy) -> None:
        with self._lock:
            self._spend_policies[(policy.organization_id, policy.user_id)] = policy

    def organization_spend_policy(
        self, organization_id: str
    ) -> OrganizationSpendPolicy | None:
        with self._lock:
            return self._organization_spend_policies.get(organization_id)

    def save_organization_spend_policy(
        self, policy: OrganizationSpendPolicy
    ) -> None:
        with self._lock:
            self._organization_spend_policies[policy.organization_id] = policy

    def spend_holds(self, organization_id: str) -> tuple[SpendHold, ...]:
        with self._lock:
            return tuple(
                row
                for (tenant, _), row in self._spend_holds.items()
                if tenant == organization_id
            )

    def spend_hold(self, organization_id: str, hold_id: str) -> SpendHold | None:
        with self._lock:
            return self._spend_holds.get((organization_id, hold_id))

    def save_spend_hold(self, hold: SpendHold) -> None:
        with self._lock:
            self._spend_holds[(hold.organization_id, hold.hold_id)] = hold

    def approval(
        self, organization_id: str, approval_id: str
    ) -> RemoteAnalysisApproval | None:
        with self._lock:
            return self._approvals.get((organization_id, approval_id))

    def save_approval(self, approval: RemoteAnalysisApproval) -> None:
        with self._lock:
            self._approvals[(approval.organization_id, approval.approval_id)] = approval

    def job(self, organization_id: str, job_id: str) -> DeepAnalysisJob | None:
        with self._lock:
            return self._jobs.get((organization_id, job_id))

    def save_job(self, job: DeepAnalysisJob) -> None:
        with self._lock:
            self._jobs[(job.organization_id, job.job_id)] = job

    def queued_jobs(self) -> tuple[DeepAnalysisJob, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        job
                        for job in self._jobs.values()
                        if job.state is DeepJobState.QUEUED
                    ),
                    key=lambda job: (job.organization_id, job.job_id),
                )
            )

    def append_audit(self, event: PaidAuditEvent) -> None:
        with self._lock:
            self._audits.append(event)

    def audit_for_tenant(self, organization_id: str) -> tuple[PaidAuditEvent, ...]:
        with self._lock:
            return tuple(
                row for row in self._audits if row.organization_id == organization_id
            )


class DevelopmentPrincipalAuthorizer:
    """Synthetic current-state resolver with explicit revocation hooks."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._revoked_users: set[tuple[str, str]] = set()
        self._revoked_clients: set[tuple[str, str]] = set()
        self._revoked_devices: set[tuple[str, str]] = set()
        self._principals: dict[tuple[str, str, str, str], PaidPrincipal] = {}

    def register(self, principal: PaidPrincipal) -> None:
        with self._lock:
            key = (
                principal.organization_id,
                principal.user_id,
                principal.client_id,
                principal.device_id,
            )
            self._principals[key] = principal

    def revoke_user(self, organization_id: str, user_id: str) -> None:
        with self._lock:
            self._revoked_users.add((organization_id, user_id))

    def revoke_client(self, organization_id: str, client_id: str) -> None:
        with self._lock:
            self._revoked_clients.add((organization_id, client_id))

    def revoke_device(self, organization_id: str, device_id: str) -> None:
        with self._lock:
            self._revoked_devices.add((organization_id, device_id))

    def allows(
        self,
        principal: PaidPrincipal,
        required_scope: PaidScope,
        *,
        now: datetime,
    ) -> bool:
        with self._lock:
            key = (
                principal.organization_id,
                principal.user_id,
                principal.client_id,
                principal.device_id,
            )
            return (
                self._principals.get(key) == principal
                and principal.active
                and principal.verified_at <= now < principal.expires_at
                and required_scope in principal.scopes
                and (principal.organization_id, principal.user_id)
                not in self._revoked_users
                and (principal.organization_id, principal.client_id)
                not in self._revoked_clients
                and (principal.organization_id, principal.device_id)
                not in self._revoked_devices
            )


class SyntheticHostedAnalysisProvider:
    """Content-independent provider used only in the development profile."""

    def __init__(
        self,
        *,
        completed_at: datetime,
        identifiers: DevelopmentPseudonymFactory,
        actual_cost_micro: int | None,
        fail: bool = False,
    ) -> None:
        self._completed_at = completed_at
        self._identifiers = identifiers
        self._actual_cost_micro = actual_cost_micro
        self._fail = fail
        self.call_count = 0

    @property
    def destination(self) -> TenantJobDestination:
        return TenantJobDestination.SYNTHETIC_TEST

    @property
    def production_ready(self) -> bool:
        return False

    def analyze(
        self, request: DeepAnalysisRequest, approved_payload: SecretStr
    ) -> ProviderResult:
        del approved_payload
        self.call_count += 1
        if self._fail:
            raise RuntimeError("synthetic_provider_failed")
        return ProviderResult(
            provider_receipt_id=self._identifiers.new("provider-receipt"),
            destination=TenantJobDestination.SYNTHETIC_TEST,
            model_id=request.model_id,
            judgments=tuple(
                MetricJudgment(metric_key=key, value=0.5, confidence=0.5)
                for key in request.metric_keys
            ),
            actual_cost_micro=self._actual_cost_micro,
            completed_at=self._completed_at,
        )


__all__ = [
    "DevelopmentPaidProductStore",
    "DevelopmentPrincipalAuthorizer",
    "DevelopmentPseudonymFactory",
    "DevelopmentPayloadPseudonymizer",
    "DevelopmentSubjectPseudonymizer",
    "DevelopmentTenantBindingResolver",
    "DevelopmentWebhookVerifier",
    "SyntheticHostedAnalysisProvider",
    "canonical_webhook_digest",
    "canonical_webhook_signature",
]
