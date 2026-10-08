"""Explicitly development-only HMAC fake; never composed by production code."""

from __future__ import annotations

import hashlib
import hmac

from pydantic import SecretBytes

from ...application.updates.ports import SignatureState


class DevelopmentHmacManifestVerifier:
    def __init__(
        self,
        *,
        development_mode: bool,
        keys: dict[str, SecretBytes],
    ) -> None:
        if development_mode is not True:
            raise RuntimeError("development_update_verifier_disabled")
        if not keys or any(len(value.get_secret_value()) < 32 for value in keys.values()):
            raise ValueError("development verifier keys do not meet the test bound")
        self._keys = dict(keys)

    def verify(self, *, payload: bytes, signature: bytes, key_id: str) -> SignatureState:
        key = self._keys.get(key_id)
        if key is None:
            return SignatureState.UNKNOWN_KEY
        expected = hmac.new(
            key.get_secret_value(), payload, digestmod=hashlib.sha256
        ).digest()
        return (
            SignatureState.VALID
            if hmac.compare_digest(expected, signature)
            else SignatureState.INVALID
        )
