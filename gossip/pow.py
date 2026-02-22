"""Proof-of-Work for Sybil resistance.

A node must find a nonce such that SHA-256(node_id || nonce) starts
with `k` leading hex zeros.  This makes joining the network expensive.
"""

import hashlib
import time


def compute_pow(node_id: str, k: int) -> dict:
    """Brute-force search for a valid nonce.

    Returns dict with: hash_alg, difficulty_k, nonce, digest_hex, elapsed_ms
    """
    prefix = "0" * k
    start = time.time()
    nonce = 0

    while True:
        data = f"{node_id}{nonce}".encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        if digest.startswith(prefix):
            elapsed_ms = (time.time() - start) * 1000
            return {
                "hash_alg": "sha256",
                "difficulty_k": k,
                "nonce": nonce,
                "digest_hex": digest,
                "elapsed_ms": round(elapsed_ms, 1),
            }
        nonce += 1


def validate_pow(node_id: str, pow_data: dict, required_k: int) -> bool:
    """Verify a PoW proof.

    Checks:
    1. H(node_id || nonce) actually produces the claimed digest
    2. The digest starts with required_k hex zeros
    3. The claimed difficulty_k >= required_k
    """
    if not pow_data:
        return False

    nonce = pow_data.get("nonce")
    claimed_digest = pow_data.get("digest_hex", "")
    claimed_k = pow_data.get("difficulty_k", 0)

    if nonce is None or claimed_k < required_k:
        return False

    data = f"{node_id}{nonce}".encode("utf-8")
    actual_digest = hashlib.sha256(data).hexdigest()

    if actual_digest != claimed_digest:
        return False

    prefix = "0" * required_k
    return actual_digest.startswith(prefix)
