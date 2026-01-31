"""Tests for the Facto SDK client."""

import pytest

from facto import (
    AsyncFactoClient,
    CryptoProvider,
    ExecutionMeta,
    FactoClient,
    FactoConfig,
    generate_keypair,
    verify_event,
)


class TestCryptoProvider:
    """Tests for cryptographic operations."""

    def test_generate_keypair(self):
        """Test keypair generation."""
        private_key, public_key = generate_keypair()
        assert len(private_key) == 32
        assert len(public_key) == 32

    def test_crypto_provider_init(self):
        """Test CryptoProvider initialization."""
        crypto = CryptoProvider()
        assert len(crypto.public_key) == 32
        assert len(crypto.private_key) == 32
        assert len(crypto.public_key_base64) > 0

    def test_crypto_provider_with_existing_key(self):
        """Test CryptoProvider with existing keypair."""
        private_key, public_key = generate_keypair()
        crypto = CryptoProvider(private_key=private_key)
        assert crypto.public_key == public_key

    def test_prev_hash_initialization(self):
        """Test that prev_hash starts as 64 zeros."""
        crypto = CryptoProvider()
        assert crypto.prev_hash == "0" * 64

    def test_hash_computation(self):
        """Test SHA3-256 hash computation."""
        crypto = CryptoProvider()
        canonical = '{"test":"data"}'
        hash_result = crypto.compute_hash(canonical)
        assert len(hash_result) == 64  # SHA3-256 produces 64 hex chars

    def test_sign_and_verify(self):
        """Test signing and verification."""
        crypto = CryptoProvider()
        message = b"test message"
        signature = crypto.sign(message)
        assert len(signature) == 64  # Ed25519 signature is 64 bytes
        assert crypto.verify(message, signature, crypto.public_key)

    def test_canonical_form(self):
        """Test canonical form building."""
        crypto = CryptoProvider()
        event_dict = {
            "facto_id": "ft-test",
            "agent_id": "agent-test",
            "session_id": "session-test",
            "parent_facto_id": None,
            "action_type": "test",
            "status": "success",
            "input_data": {"key": "value"},
            "output_data": {"result": "ok"},
            "execution_meta": {
                "model_id": "gpt-4",
                "temperature": 0.7,
                "seed": None,
                "sdk_version": "0.1.0",
                "tool_calls": [],
            },
            "proof": {"prev_hash": "0" * 64},
            "started_at": 1000000000,
            "completed_at": 1000000001,
        }
        canonical = crypto.build_canonical_form(event_dict)
        # Check that it's valid JSON
        import json

        parsed = json.loads(canonical)
        assert "action_type" in parsed
        assert "agent_id" in parsed

    def test_sign_event(self):
        """Test event signing."""
        crypto = CryptoProvider()
        event_dict = {
            "facto_id": "ft-test",
            "agent_id": "agent-test",
            "session_id": "session-test",
            "parent_facto_id": None,
            "action_type": "test",
            "status": "success",
            "input_data": {},
            "output_data": {},
            "execution_meta": {
                "model_id": None,
                "temperature": None,
                "seed": None,
                "sdk_version": "0.1.0",
                "tool_calls": [],
            },
            "proof": {"prev_hash": "0" * 64},
            "started_at": 1000000000,
            "completed_at": 1000000001,
        }
        event_hash, signature = crypto.sign_event(event_dict)
        assert len(event_hash) == 64
        assert len(signature) > 0


class TestFactoConfig:
    """Tests for FactoConfig."""

    def test_default_config(self):
        """Test default configuration."""
        config = FactoConfig(endpoint="http://localhost:8080", agent_id="test-agent")
        assert config.endpoint == "http://localhost:8080"
        assert config.agent_id == "test-agent"
        assert config.session_id is not None
        assert config.batch_size == 100
        assert config.flush_interval_seconds == 1.0

    def test_custom_session_id(self):
        """Test custom session ID."""
        config = FactoConfig(
            endpoint="http://localhost:8080",
            agent_id="test-agent",
            session_id="custom-session",
        )
        assert config.session_id == "custom-session"


class TestVerifyEvent:
    """Tests for event verification."""

    def test_verify_valid_event(self):
        """Test verifying a valid event."""
        crypto = CryptoProvider()
        event_dict = {
            "facto_id": "ft-test",
            "agent_id": "agent-test",
            "session_id": "session-test",
            "parent_facto_id": None,
            "action_type": "test",
            "status": "success",
            "input_data": {},
            "output_data": {},
            "execution_meta": {
                "model_id": None,
                "temperature": None,
                "seed": None,
                "sdk_version": "0.1.0",
                "tool_calls": [],
            },
            "proof": {"prev_hash": "0" * 64},
            "started_at": 1000000000,
            "completed_at": 1000000001,
        }

        event_hash, signature = crypto.sign_event(event_dict)
        event_dict["proof"]["event_hash"] = event_hash
        event_dict["proof"]["signature"] = signature
        event_dict["proof"]["public_key"] = crypto.public_key_base64

        hash_valid, sig_valid = verify_event(event_dict)
        assert hash_valid
        assert sig_valid

    def test_verify_tampered_event(self):
        """Test verifying a tampered event."""
        crypto = CryptoProvider()
        event_dict = {
            "facto_id": "ft-test",
            "agent_id": "agent-test",
            "session_id": "session-test",
            "parent_facto_id": None,
            "action_type": "test",
            "status": "success",
            "input_data": {},
            "output_data": {},
            "execution_meta": {
                "model_id": None,
                "temperature": None,
                "seed": None,
                "sdk_version": "0.1.0",
                "tool_calls": [],
            },
            "proof": {"prev_hash": "0" * 64},
            "started_at": 1000000000,
            "completed_at": 1000000001,
        }

        event_hash, signature = crypto.sign_event(event_dict)
        event_dict["proof"]["event_hash"] = event_hash
        event_dict["proof"]["signature"] = signature
        event_dict["proof"]["public_key"] = crypto.public_key_base64

        # Tamper with the event
        event_dict["status"] = "error"

        hash_valid, sig_valid = verify_event(event_dict)
        assert not hash_valid
        assert not sig_valid


class TestFactoClient:
    """Tests for the FactoClient (mocked HTTP)."""

    def test_client_initialization(self):
        """Test client initialization."""
        config = FactoConfig(endpoint="http://localhost:8080", agent_id="test-agent")
        client = FactoClient(config)
        assert client.config == config
        client.close()

    def test_record_creates_event(self):
        """Test that record creates an event with correct structure."""
        config = FactoConfig(endpoint="http://localhost:8080", agent_id="test-agent")
        client = FactoClient(config)

        # Record an event (won't actually send due to batching)
        facto_id = client.record(
            action_type="test",
            input_data={"key": "value"},
            output_data={"result": "ok"},
        )

        assert facto_id.startswith("ft-")
        assert len(client._batch) == 1

        event = client._batch[0]
        assert event.action_type == "test"
        assert event.input_data == {"key": "value"}
        assert event.output_data == {"result": "ok"}
        assert event.status == "success"
        assert len(event.proof.event_hash) == 64
        assert len(event.proof.signature) > 0

        client.close()

    def test_chain_linking(self):
        """Test that prev_hash links events correctly."""
        config = FactoConfig(endpoint="http://localhost:8080", agent_id="test-agent")
        client = FactoClient(config)

        # Record first event
        client.record(
            action_type="first",
            input_data={},
            output_data={},
        )
        first_hash = client._batch[0].proof.event_hash

        # Record second event
        client.record(
            action_type="second",
            input_data={},
            output_data={},
        )
        second_prev_hash = client._batch[1].proof.prev_hash

        # Second event's prev_hash should be first event's hash
        assert second_prev_hash == first_hash

        client.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
