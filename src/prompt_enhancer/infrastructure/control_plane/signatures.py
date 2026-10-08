"""Signature verification adapters for the control plane.

Only a development algorithm is implemented. ``dev-hmac-sha256`` uses symmetric
material that both the signer and the verifier hold, so it proves tamper
detection, key binding, and domain separation on one machine — and nothing
else. It is not a public-key identity: anybody able to verify is also able to
sign, which is exactly why it must never leave a development profile.

The production algorithm is Ed25519. It is named in the contract and is
deliberately left unregistered, so composing it fails closed with
``unsupported_algorithm`` instead of silently degrading to the symmetric
scheme. Adding it means a reviewed dependency, a key-distribution design, and
a superseding note in the ADR, not an edit to this file's default.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import hmac
from typing import Mapping

from ...application.control_plane import (
    DeviceVerificationKey,
    EnvelopeSignature,
    SignatureAlgorithm,
    SignatureVerifier,
    SignedSnapshotEnvelope,
    SnapshotEnvelope,
    canonical_envelope_bytes,
)


@dataclass(frozen=True, slots=True)
class DevelopmentHmacSignatureVerifier:
    """Verify a development HMAC-SHA256 tag over the canonical envelope bytes."""

    @property
    def algorithm(self) -> SignatureAlgorithm:
        return SignatureAlgorithm.DEVELOPMENT_HMAC_SHA256

    def verify(
        self,
        key: DeviceVerificationKey,
        payload: bytes,
        signature: str,
    ) -> bool:
        if key.algorithm is not self.algorithm:
            return False
        try:
            supplied = base64.b64decode(signature, validate=True)
        except (binascii.Error, ValueError):
            return False
        expected = development_signature_bytes(key, payload)
        return hmac.compare_digest(supplied, expected)


def development_signature_bytes(
    key: DeviceVerificationKey, payload: bytes
) -> bytes:
    """Compute the development tag. Signing and verifying share this helper."""

    if key.algorithm is not SignatureAlgorithm.DEVELOPMENT_HMAC_SHA256:
        raise ValueError("development signing requires the development algorithm")
    secret = key.material.get_secret_value().encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).digest()


def development_signature(key: DeviceVerificationKey, payload: bytes) -> str:
    """Produce the base64 tag a development device would send."""

    return base64.b64encode(development_signature_bytes(key, payload)).decode("ascii")


def sign_development_envelope(
    key: DeviceVerificationKey, envelope: SnapshotEnvelope
) -> SignedSnapshotEnvelope:
    """Produce what a development device would send for one envelope."""

    return SignedSnapshotEnvelope(
        envelope=envelope,
        signature=EnvelopeSignature(
            algorithm=key.algorithm,
            key_fingerprint=key.key_fingerprint,
            value=development_signature(key, canonical_envelope_bytes(envelope)),
        ),
    )


@dataclass(frozen=True, slots=True)
class ExplicitSignatureVerifierRegistry:
    """Resolve verifiers from an explicit table and refuse everything else."""

    verifiers: Mapping[SignatureAlgorithm, SignatureVerifier]

    def verifier(
        self, algorithm: SignatureAlgorithm
    ) -> SignatureVerifier | None:
        return self.verifiers.get(algorithm)


def development_verifier_registry() -> ExplicitSignatureVerifierRegistry:
    """The only registry composed today: development HMAC, nothing else."""

    return ExplicitSignatureVerifierRegistry(
        {
            SignatureAlgorithm.DEVELOPMENT_HMAC_SHA256: (
                DevelopmentHmacSignatureVerifier()
            )
        }
    )


__all__ = [
    "DevelopmentHmacSignatureVerifier",
    "ExplicitSignatureVerifierRegistry",
    "development_signature",
    "development_signature_bytes",
    "development_verifier_registry",
    "sign_development_envelope",
]
