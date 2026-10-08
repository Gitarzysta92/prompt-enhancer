"""Production manifest verification against a packaged Ed25519 trust store."""

from __future__ import annotations

import re
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from ...application.updates.ports import SignatureState


_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MAX_TRUSTED_KEYS = 8


class Ed25519ManifestVerifier:
    def __init__(self, *, public_keys: Mapping[str, bytes]) -> None:
        if not public_keys or len(public_keys) > _MAX_TRUSTED_KEYS:
            raise ValueError("update trust store size is invalid")
        parsed: dict[str, Ed25519PublicKey] = {}
        for key_id, raw_key in public_keys.items():
            if _KEY_ID.fullmatch(key_id) is None or not isinstance(raw_key, bytes):
                raise ValueError("update trust store entry is invalid")
            try:
                parsed[key_id] = Ed25519PublicKey.from_public_bytes(raw_key)
            except ValueError as error:
                raise ValueError("update trust store entry is invalid") from error
        self._keys = parsed

    def verify(self, *, payload: bytes, signature: bytes, key_id: str) -> SignatureState:
        key = self._keys.get(key_id)
        if key is None:
            return SignatureState.UNKNOWN_KEY
        if not isinstance(payload, bytes) or not isinstance(signature, bytes) or len(signature) != 64:
            return SignatureState.INVALID
        try:
            key.verify(signature, payload)
        except (InvalidSignature, ValueError, TypeError):
            return SignatureState.INVALID
        return SignatureState.VALID
