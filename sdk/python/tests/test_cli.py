#!/usr/bin/env python3
"""
Unit tests for the Facto CLI verification tool.
"""

import json
import tempfile
from pathlib import Path

import pytest

from facto.cli import (
    build_canonical_form,
    compute_sha3_256,
    hash_pair,
    verify_chain_integrity,
    verify_event_hash,
    verify_event_signature,
    verify_evidence_bundle,
    verify_merkle_proof,
)


def make_test_event(
    facto_id: str = "ft-test-001",
    agent_id: str = "test-agent",
    session_id: str = "test-session",
    action_type: str = "test_action",
    prev_hash: str = "0" * 64,
    event_hash: str = None,
    signature: str = None,
    public_key: str = None,
) -> dict:
    """Create a test event dict."""
    from facto import CryptoProvider
    
    crypto = CryptoProvider()
    
    event = {
        "facto_id": facto_id,
        "agent_id": agent_id,
        "session_id": session_id,
        "action_type": action_type,
        "status": "success",
        "input_data": {"test": "input"},
        "output_data": {"test": "output"},
        "started_at": 1700000000000000000,
        "completed_at": 1700000001000000000,
        "parent_facto_id": None,
        "execution_meta": {
            "sdk_version": "0.1.0",
            "sdk_language": "python",
            "tool_calls": [],
        },
        "proof": {
            "prev_hash": prev_hash,
            "event_hash": "",
            "signature": "",
            "public_key": crypto.public_key_base64,
        },
    }
    
    # Compute hash and signature
    computed_hash, sig = crypto.sign_event(event)
    event["proof"]["event_hash"] = computed_hash
    event["proof"]["signature"] = sig
    
    return event


class TestBuildCanonicalForm:
    """Tests for canonical form building."""
    
    def test_canonical_form_is_deterministic(self):
        """Same event should produce same canonical form."""
        event = make_test_event()
        form1 = build_canonical_form(event)
        form2 = build_canonical_form(event)
        assert form1 == form2
    
    def test_canonical_form_has_sorted_keys(self):
        """Canonical form should have sorted keys."""
        event = make_test_event()
        form = build_canonical_form(event)
        data = json.loads(form)
        keys = list(data.keys())
        assert keys == sorted(keys)


class TestHashVerification:
    """Tests for SHA3-256 hash verification."""
    
    def test_valid_hash_passes(self):
        """Valid event hash should pass verification."""
        event = make_test_event()
        is_valid, computed, stored = verify_event_hash(event)
        assert is_valid
        assert computed == stored
    
    def test_tampered_hash_fails(self):
        """Tampered event hash should fail verification."""
        event = make_test_event()
        event["proof"]["event_hash"] = "a" * 64  # Tamper with hash
        is_valid, computed, stored = verify_event_hash(event)
        assert not is_valid
        assert computed != stored


class TestSignatureVerification:
    """Tests for Ed25519 signature verification."""
    
    def test_valid_signature_passes(self):
        """Valid signature should pass verification."""
        event = make_test_event()
        is_valid, error = verify_event_signature(event)
        assert is_valid
        assert error == ""
    
    def test_tampered_data_fails_signature(self):
        """Tampered data should fail signature verification."""
        event = make_test_event()
        event["input_data"]["test"] = "tampered"  # Modify data
        is_valid, error = verify_event_signature(event)
        assert not is_valid


class TestChainIntegrity:
    """Tests for prev_hash chain verification."""
    
    def test_empty_chain_is_valid(self):
        """Empty event list should be valid."""
        is_valid, errors = verify_chain_integrity([])
        assert is_valid
        assert errors == []
    
    def test_single_event_with_zero_prev_hash(self):
        """First event should have zero prev_hash."""
        event = make_test_event(prev_hash="0" * 64)
        is_valid, errors = verify_chain_integrity([event])
        assert is_valid
        assert errors == []
    
    def test_broken_chain_detected(self):
        """Broken chain should be detected."""
        event1 = make_test_event(facto_id="ft-1", prev_hash="0" * 64)
        event2 = make_test_event(
            facto_id="ft-2",
            prev_hash="wrong" + "0" * 59,  # Wrong prev_hash
        )
        event2["completed_at"] = event1["completed_at"] + 1000000000
        
        is_valid, errors = verify_chain_integrity([event1, event2])
        assert not is_valid
        assert len(errors) > 0


class TestMerkleProof:
    """Tests for Merkle proof verification."""
    
    def test_single_element_proof(self):
        """Single element Merkle tree should verify."""
        event_hash = "a" * 64
        # Single element has itself as root
        assert verify_merkle_proof(event_hash, [], event_hash)
    
    def test_two_element_proof(self):
        """Two element Merkle proof should verify."""
        left = "a" * 64
        right = "b" * 64
        root = hash_pair(left, right)
        
        # Left element proof
        proof = [{"hash": right, "position": "right"}]
        assert verify_merkle_proof(left, proof, root)
        
        # Right element proof
        proof = [{"hash": left, "position": "left"}]
        assert verify_merkle_proof(right, proof, root)


class TestEvidenceBundle:
    """Tests for full evidence bundle verification."""
    
    def test_valid_bundle(self):
        """Valid bundle should pass verification."""
        event = make_test_event()
        event_hash = event["proof"]["event_hash"]
        
        # For a single-element tree, the event hash is the root
        merkle_proof = {
            "facto_id": event["facto_id"],
            "root": event_hash,
            "proof": [],  # No siblings for single element
        }
        
        bundle = {
            "package_id": "ev-test",
            "session_id": "test-session",
            "events": [event],
            "merkle_proofs": [merkle_proof],
            "exported_at": "2024-01-01T00:00:00Z",
        }
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bundle, f)
            filepath = f.name
        
        try:
            is_valid, results = verify_evidence_bundle(filepath)
            assert is_valid
            assert results["hashes"]["valid"] == 1
            assert results["signatures"]["valid"] == 1
        finally:
            Path(filepath).unlink()
    
    def test_file_not_found(self):
        """Missing file should return error."""
        is_valid, results = verify_evidence_bundle("/nonexistent/file.json")
        assert not is_valid
        assert "error" in results


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
