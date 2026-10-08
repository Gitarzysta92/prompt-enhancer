"""Development adapters for the control-plane ports.

Everything here is in memory and single process. A production deployment
replaces this package with a PostgreSQL adapter that enforces the same tenant
scoping through row-level security; see
``docs/control-plane-postgres-rls.md``.
"""

from .development import (
    DEFAULT_DEVICE_SCOPES,
    DEVICE_KEY_FINGERPRINT_DOMAIN,
    DevelopmentControlPlane,
    ProvisionedSeat,
    create_development_control_plane,
    development_device_key,
)
from .development_store import (
    CREDENTIAL_DIGEST_DOMAIN,
    DevelopmentApiClientStore,
    DevelopmentAggregateReleaseStore,
    DevelopmentAuditStore,
    DevelopmentCredentialStore,
    DevelopmentCursorStore,
    DevelopmentDeviceStore,
    DevelopmentDirectoryStore,
    DevelopmentEntitlementStore,
    DevelopmentManagerGrantStore,
    DevelopmentRecipientDeliveryStore,
    DevelopmentSnapshotStore,
    DevelopmentTransaction,
    RandomIdentifierFactory,
    credential_digest,
)
from .resolver import StoredCredentialPrincipalResolver
from .signatures import (
    DevelopmentHmacSignatureVerifier,
    ExplicitSignatureVerifierRegistry,
    development_signature,
    development_signature_bytes,
    development_verifier_registry,
    sign_development_envelope,
)

__all__ = [
    "CREDENTIAL_DIGEST_DOMAIN",
    "DEFAULT_DEVICE_SCOPES",
    "DEVICE_KEY_FINGERPRINT_DOMAIN",
    "DevelopmentApiClientStore",
    "DevelopmentAggregateReleaseStore",
    "DevelopmentAuditStore",
    "DevelopmentControlPlane",
    "DevelopmentCredentialStore",
    "DevelopmentCursorStore",
    "DevelopmentDeviceStore",
    "DevelopmentDirectoryStore",
    "DevelopmentEntitlementStore",
    "DevelopmentHmacSignatureVerifier",
    "DevelopmentManagerGrantStore",
    "DevelopmentRecipientDeliveryStore",
    "DevelopmentSnapshotStore",
    "DevelopmentTransaction",
    "ExplicitSignatureVerifierRegistry",
    "ProvisionedSeat",
    "RandomIdentifierFactory",
    "StoredCredentialPrincipalResolver",
    "create_development_control_plane",
    "credential_digest",
    "development_device_key",
    "development_signature",
    "development_signature_bytes",
    "development_verifier_registry",
    "sign_development_envelope",
]
