"""
Agent identity and cryptographic authentication.

Agents authenticate via Ed25519 signed requests.
No human may ever obtain agent credentials.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Dict, Optional, Tuple

# Use nacl for Ed25519 if available, fallback to hmac-based scheme
try:
    from nacl.signing import VerifyKey
    from nacl.exceptions import BadSignatureError
    HAS_NACL = True
except ImportError:
    HAS_NACL = False


def generate_nonce() -> str:
    """Generate a cryptographic nonce for registration."""
    return secrets.token_hex(32)


def generate_claim_token() -> str:
    """Generate a single-use claim token."""
    return secrets.token_urlsafe(32)


def generate_agent_id(public_key: str) -> str:
    """Derive a deterministic agent ID from a public key."""
    digest = hashlib.sha256(public_key.encode()).hexdigest()
    return f"agent_{digest[:16]}"


def verify_signed_nonce(public_key: str, nonce: str, signature: str) -> bool:
    """
    Verify that the agent controls the private key corresponding to public_key.

    If nacl is available, uses Ed25519 verification.
    Otherwise, falls back to HMAC-SHA256 (the agent signs with their key as secret).
    """
    if HAS_NACL:
        try:
            verify_key = VerifyKey(bytes.fromhex(public_key))
            verify_key.verify(nonce.encode(), bytes.fromhex(signature))
            return True
        except (BadSignatureError, Exception):
            return False
    else:
        # Fallback: HMAC-SHA256 where the public_key is used as shared secret
        # This is a simplified scheme for environments without nacl
        expected = hmac.new(
            public_key.encode(),
            nonce.encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


def verify_agent_request(
    public_key: str,
    method: str,
    path: str,
    body: str,
    timestamp: str,
    signature: str,
) -> bool:
    """
    Verify a signed agent API request.

    The agent signs: METHOD + PATH + BODY + TIMESTAMP using their private key.
    """
    message = f"{method}:{path}:{body}:{timestamp}"

    if HAS_NACL:
        try:
            verify_key = VerifyKey(bytes.fromhex(public_key))
            verify_key.verify(message.encode(), bytes.fromhex(signature))
            return True
        except Exception:
            return False
    else:
        # HMAC fallback
        expected = hmac.new(
            public_key.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


def is_timestamp_valid(timestamp: str, max_age_seconds: int = 300) -> bool:
    """Check that the request timestamp is within acceptable skew."""
    try:
        ts = float(timestamp)
        now = time.time()
        return abs(now - ts) < max_age_seconds
    except (ValueError, TypeError):
        return False


class AntiSybil:
    """
    Anti-sybil protection via proof-of-work.

    Agents must find a nonce such that SHA256(challenge + nonce) has
    a specified number of leading zero bits.
    """

    DIFFICULTY = 16  # 16 leading zero bits (~65536 attempts)

    @classmethod
    def generate_challenge(cls) -> str:
        return secrets.token_hex(16)

    @classmethod
    def verify_pow(cls, challenge: str, pow_nonce: str) -> bool:
        digest = hashlib.sha256(f"{challenge}{pow_nonce}".encode()).hexdigest()
        # Check leading zeros in hex (each hex char = 4 bits)
        required_hex_zeros = cls.DIFFICULTY // 4
        return digest[:required_hex_zeros] == "0" * required_hex_zeros

    @classmethod
    def solve_pow(cls, challenge: str) -> str:
        """Solve a PoW puzzle (utility for testing)."""
        nonce = 0
        while True:
            candidate = str(nonce)
            if cls.verify_pow(challenge, candidate):
                return candidate
            nonce += 1
