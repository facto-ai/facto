"""Cryptographic utilities for the Facto SDK."""

import base64
import hashlib
import json
from typing import Any, Dict, Optional, Tuple

from nacl.signing import SigningKey, VerifyKey
from nacl.exceptions import BadSignatureError


class CryptoProvider:
    """Handles cryptographic operations for event signing and verification."""

    def __init__(
        self,
        private_key: Optional[bytes] = None,
        public_key: Optional[bytes] = None,
    ):
        """
        Initialize the crypto provider.

        Args:
            private_key: Ed25519 private key seed (32 bytes). If None, generates new keypair.
            public_key: Ed25519 public key (32 bytes). Only needed if private_key is provided.
        """
        if private_key is not None:
            if len(private_key) != 32:
                raise ValueError("Private key must be 32 bytes")
            self._signing_key = SigningKey(private_key)
            self._verify_key = self._signing_key.verify_key
        else:
            # Generate new keypair
            self._signing_key = SigningKey.generate()
            self._verify_key = self._signing_key.verify_key

        self._prev_hash: str = "0" * 64  # Initial prev_hash is 64 zeros

    @property
    def public_key(self) -> bytes:
        """Get the public key bytes."""
        return bytes(self._verify_key)

    @property
    def public_key_base64(self) -> str:
        """Get the public key as base64 string."""
        return base64.b64encode(self.public_key).decode("ascii")

    @property
    def private_key(self) -> bytes:
        """Get the private key seed bytes."""
        return bytes(self._signing_key)

    @property
    def prev_hash(self) -> str:
        """Get the current prev_hash for chain linking."""
        return self._prev_hash

    def update_prev_hash(self, event_hash: str) -> None:
        """Update the prev_hash after successfully sending an event."""
        self._prev_hash = event_hash

    def build_canonical_form(self, event_dict: Dict[str, Any]) -> str:
        """
        Build the canonical JSON form for hashing/signing.

        The canonical form has sorted keys and no extra whitespace.
        """
        # Build the canonical structure with specific fields in sorted order
        canonical: Dict[str, Any] = {}

        canonical["action_type"] = event_dict["action_type"]
        canonical["agent_id"] = event_dict["agent_id"]
        canonical["completed_at"] = event_dict["completed_at"]

        # Build execution_meta in sorted order
        exec_meta: Dict[str, Any] = {}
        em = event_dict.get("execution_meta", {})
        if em.get("model_id") is not None:
            exec_meta["model_id"] = em["model_id"]
        exec_meta["seed"] = em.get("seed")
        exec_meta["sdk_version"] = em.get("sdk_version", "0.1.0")
        if em.get("temperature") is not None:
            exec_meta["temperature"] = em["temperature"]
        exec_meta["tool_calls"] = em.get("tool_calls", [])
        canonical["execution_meta"] = exec_meta

        canonical["input_data"] = event_dict["input_data"]
        canonical["output_data"] = event_dict["output_data"]
        canonical["parent_facto_id"] = event_dict.get("parent_facto_id")
        canonical["prev_hash"] = event_dict["proof"]["prev_hash"]
        canonical["session_id"] = event_dict["session_id"]
        canonical["started_at"] = event_dict["started_at"]
        canonical["status"] = event_dict["status"]
        canonical["facto_id"] = event_dict["facto_id"]

        return json.dumps(canonical, sort_keys=True, separators=(",", ":"))

    def compute_hash(self, canonical: str) -> str:
        """Compute SHA3-256 hash of the canonical form."""
        hasher = hashlib.sha3_256()
        hasher.update(canonical.encode("utf-8"))
        return hasher.hexdigest()

    def sign(self, message: bytes) -> bytes:
        """Sign a message with the private key."""
        signed = self._signing_key.sign(message)
        return signed.signature

    def sign_base64(self, message: bytes) -> str:
        """Sign a message and return base64-encoded signature."""
        signature = self.sign(message)
        return base64.b64encode(signature).decode("ascii")

    def verify(self, message: bytes, signature: bytes, public_key: bytes) -> bool:
        """Verify a signature."""
        try:
            verify_key = VerifyKey(public_key)
            verify_key.verify(message, signature)
            return True
        except BadSignatureError:
            return False

    def sign_event(self, event_dict: Dict[str, Any]) -> Tuple[str, str]:
        """
        Sign an event and compute its hash.

        Args:
            event_dict: Event dictionary with proof.prev_hash set

        Returns:
            Tuple of (event_hash, signature_base64)
        """
        # Build canonical form
        canonical = self.build_canonical_form(event_dict)

        # Compute hash
        event_hash = self.compute_hash(canonical)

        # Sign the canonical form
        signature = self.sign_base64(canonical.encode("utf-8"))

        return event_hash, signature


def generate_keypair() -> Tuple[bytes, bytes]:
    """
    Generate a new Ed25519 keypair.

    Returns:
        Tuple of (private_key_seed, public_key), both 32 bytes
    """
    signing_key = SigningKey.generate()
    return bytes(signing_key), bytes(signing_key.verify_key)


def verify_event(event_dict: Dict[str, Any]) -> Tuple[bool, bool]:
    """
    Verify an event's hash and signature.

    Args:
        event_dict: The event dictionary with proof

    Returns:
        Tuple of (hash_valid, signature_valid)
    """
    crypto = CryptoProvider()

    # Build canonical form
    canonical = crypto.build_canonical_form(event_dict)

    # Verify hash
    computed_hash = crypto.compute_hash(canonical)
    hash_valid = computed_hash == event_dict["proof"]["event_hash"]

    # Verify signature
    try:
        public_key = base64.b64decode(event_dict["proof"]["public_key"])
        signature = base64.b64decode(event_dict["proof"]["signature"])
        signature_valid = crypto.verify(canonical.encode("utf-8"), signature, public_key)
    except Exception:
        signature_valid = False

    return hash_valid, signature_valid
