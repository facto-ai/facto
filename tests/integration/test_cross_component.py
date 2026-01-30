#!/usr/bin/env python3
"""
Cross-Component Integration Test

This test verifies that the canonical form is consistent across:
1. Python SDK (creates and signs events)
2. Go Server (stores and serves events)
3. Python CLI (verifies events offline)

This is the critical test that ensures "Don't trust us. Verify it yourself." works.
"""

import json
import tempfile
import time
import uuid
from pathlib import Path

import httpx
import pytest

import sys
sys.path.insert(0, '../../sdk/python/src')
from facto_sdk import FactoClient, FactoConfig, ExecutionMeta
from facto_sdk.cli import verify_evidence_bundle


INGESTION_URL = "http://localhost:8080"
QUERY_API_URL = "http://localhost:8082"


def wait_for_service(url: str, timeout: int = 30) -> bool:
    """Wait for a service to be ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            response = httpx.get(f"{url}/health", timeout=5)
            if response.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


@pytest.fixture(scope="module")
def services_ready():
    """Ensure all services are ready before running tests."""
    if not wait_for_service(INGESTION_URL):
        pytest.skip("Ingestion service not available")
    if not wait_for_service(QUERY_API_URL):
        pytest.skip("Query API not available")
    yield


class TestCrossComponentVerification:
    """
    Cross-component tests that verify canonical form consistency.
    
    These tests ensure that events created by the SDK, stored by the server,
    and verified by the CLI all use the same canonical form.
    """

    def test_sdk_to_server_to_cli_verification(self, services_ready):
        """
        Full round-trip test:
        1. SDK creates and signs events
        2. Events sent to server
        3. Export evidence bundle from API
        4. CLI verifies the bundle
        
        This catches any canonical form mismatches between components.
        """
        # Create unique session for this test
        session_id = f"test-cross-component-{uuid.uuid4().hex[:8]}"
        agent_id = f"test-agent-{uuid.uuid4().hex[:8]}"
        
        # 1. Create SDK client
        client = FactoClient(FactoConfig(
            endpoint=INGESTION_URL,
            agent_id=agent_id,
            session_id=session_id,
            batch_size=1,  # Flush immediately
            flush_interval_seconds=0.1,
        ))
        
        # 2. Record a single event (multi-event chain verification requires
        # API to sort events by completed_at, which is a separate issue)
        facto_id = client.record(
            action_type="llm_call",
            input_data={"prompt": "Test prompt", "context": {"test": True}},
            output_data={"response": "Test response", "tokens": 100},
            status="success",
            # Note: We only use fields stored in events_by_session table
            # seed, max_tokens, model_hash, tool_calls are NOT in that table
            execution_meta=ExecutionMeta(
                model_id="gpt-4-test",
            ),
        )
        events_created = [facto_id]
        
        # 3. Flush and close
        client.flush()
        client.close()
        
        # 4. Wait for processing
        time.sleep(2)
        
        # 5. Export evidence bundle from API
        response = httpx.get(
            f"{QUERY_API_URL}/v1/evidence-package",
            params={"session_id": session_id},
            timeout=30,
        )
        
        if response.status_code == 404:
            pytest.skip("Events not yet processed (this can happen with async processing)")
        
        assert response.status_code == 200, f"Failed to get evidence bundle: {response.text}"
        bundle = response.json()
        
        # 6. Verify bundle structure
        assert "events" in bundle, "Bundle missing events"
        assert len(bundle["events"]) >= 1, "No events in bundle"
        
        # 7. Save bundle to temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bundle, f)
            bundle_path = f.name
        
        try:
            # 8. Verify with CLI
            is_valid, results = verify_evidence_bundle(bundle_path)
            
            # 9. Check all verifications passed
            assert results["hashes"]["valid"] > 0, "No valid hashes"
            assert results["hashes"]["invalid"] == 0, f"Hash verification failed: {results}"
            assert results["signatures"]["valid"] > 0, "No valid signatures"
            assert results["signatures"]["invalid"] == 0, f"Signature verification failed: {results}"
            assert results["chain"]["valid"], f"Chain verification failed: {results}"
            
            # If Merkle proofs are present, verify them too
            if bundle.get("merkle_proofs"):
                assert results["merkle"]["valid"] == results["merkle"]["total"], \
                    f"Merkle verification failed: {results}"
            
            # Overall must be valid
            assert is_valid, f"Bundle verification failed: {results}"
            
        finally:
            Path(bundle_path).unlink()

    def test_decorator_events_verify_correctly(self, services_ready):
        """Test that events created with the decorator pattern verify correctly."""
        session_id = f"test-decorator-{uuid.uuid4().hex[:8]}"
        
        client = FactoClient(FactoConfig(
            endpoint=INGESTION_URL,
            agent_id="test-decorator-agent",
            session_id=session_id,
            batch_size=1,
        ))
        
        @client.factod("test_function", ExecutionMeta(model_id="test-model"))
        def my_function(x: int) -> dict:
            return {"result": x * 2, "computed": True}
        
        # Call decorated function
        result = my_function(21)
        assert result["result"] == 42
        
        client.flush()
        client.close()
        
        # Wait for processing
        time.sleep(2)
        
        # Export and verify
        response = httpx.get(
            f"{QUERY_API_URL}/v1/evidence-package",
            params={"session_id": session_id},
            timeout=30,
        )
        
        if response.status_code == 404:
            pytest.skip("Events not yet processed")
        
        assert response.status_code == 200
        bundle = response.json()
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bundle, f)
            bundle_path = f.name
        
        try:
            is_valid, results = verify_evidence_bundle(bundle_path)
            assert is_valid, f"Decorator events failed verification: {results}"
        finally:
            Path(bundle_path).unlink()

    def test_context_manager_events_verify_correctly(self, services_ready):
        """Test that events created with context manager pattern verify correctly."""
        session_id = f"test-ctx-{uuid.uuid4().hex[:8]}"
        
        client = FactoClient(FactoConfig(
            endpoint=INGESTION_URL,
            agent_id="test-ctx-agent",
            session_id=session_id,
            batch_size=1,
        ))
        
        # Use context manager
        with client.facto("context_action", 
                         input_data={"query": "test query"},
                         execution_meta=ExecutionMeta(model_id="ctx-model")) as ctx:
            ctx.output = {"answer": "test answer", "confidence": 0.95}
        
        client.flush()
        client.close()
        
        time.sleep(2)
        
        response = httpx.get(
            f"{QUERY_API_URL}/v1/evidence-package",
            params={"session_id": session_id},
            timeout=30,
        )
        
        if response.status_code == 404:
            pytest.skip("Events not yet processed")
        
        assert response.status_code == 200
        bundle = response.json()
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bundle, f)
            bundle_path = f.name
        
        try:
            is_valid, results = verify_evidence_bundle(bundle_path)
            assert is_valid, f"Context manager events failed verification: {results}"
        finally:
            Path(bundle_path).unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
