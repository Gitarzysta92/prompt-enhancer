"""Domain-separated SHA-256 Merkle commitments for file chunk manifests."""

from __future__ import annotations

import hashlib
from typing import Protocol, Sequence


LEAF_DOMAIN = b"prompt-enhancer/direct-file-leaf/v1"
NODE_DOMAIN = b"prompt-enhancer/direct-file-node/v1"


class ChunkLike(Protocol):
    index: int
    offset: int
    size: int
    sha256: str


def _u64(value: int) -> bytes:
    if not 0 <= value < 2**64:
        raise ValueError("Merkle integer is outside unsigned 64-bit range")
    return value.to_bytes(8, "big")


def chunk_leaf(chunk: ChunkLike) -> bytes:
    """Commit to position, size and the SHA-256 digest of one chunk."""

    try:
        raw_digest = bytes.fromhex(chunk.sha256)
    except ValueError as exc:
        raise ValueError("chunk digest is not hexadecimal") from exc
    if len(raw_digest) != 32:
        raise ValueError("chunk digest is not SHA-256")
    return hashlib.sha256(
        LEAF_DOMAIN
        + b"\x00"
        + _u64(chunk.index)
        + _u64(chunk.offset)
        + _u64(chunk.size)
        + raw_digest
    ).digest()


def compute_merkle_root(chunks: Sequence[ChunkLike]) -> str:
    """Return a deterministic root, duplicating an odd node at each level."""

    if not chunks:
        raise ValueError("Merkle tree requires at least one chunk")
    level = [chunk_leaf(chunk) for chunk in chunks]
    while len(level) > 1:
        next_level: list[bytes] = []
        for index in range(0, len(level), 2):
            left = level[index]
            right = level[index + 1] if index + 1 < len(level) else left
            next_level.append(
                hashlib.sha256(NODE_DOMAIN + b"\x00" + left + right).digest()
            )
        level = next_level
    return level[0].hex()


__all__ = ["LEAF_DOMAIN", "NODE_DOMAIN", "chunk_leaf", "compute_merkle_root"]
