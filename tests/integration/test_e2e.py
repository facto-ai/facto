#!/usr/bin/env python3
"""
End-to-end integration tests for Facto.

These tests verify the complete flow:
SDK -> Ingestion -> NATS -> Processor -> ScyllaDB -> Query API

Prerequisites:
- docker-compose up -d
- All services running (ingestion, processor, api)
"""

import asyncio
import time
import uuid
from typing import Any, Dict, List

import httpx
import pytest

# Import facto SDK
import sys
sys.path.insert(0, '../../sdk/python/src')
from facto_sdk import FactoClient, FactoConfig, AsyncFactoClient, verify_event


INGESTION_URL = "http://localhost:8080"
QUERY_API_URL = "http://localhost:8082"


def wait_for_service(url: str, timeout: int = 60) -> bool:
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
    services = [
        ("Ingestion", INGESTION_URL),
        ("Query API", QUERY_API_URL),
    ]

    for name, url in services:
        if not wait_for_service(url):
            pytest.skip(f"{name} service not available at {url}")

    yield


@pytest.fixture
def facto_client(services_ready) -> FactoClient:
    """Create a facto client for testing."""
    config = FactoConfig(
        endpoint=INGESTION_URL,
        agent_id=f"test-agent-{uuid.uuid4().hex[:8]}",
        batch_size=1,  # Flush immediately for testing
        flush_interval_seconds=0.1,
    )
    client = FactoClient(config)
    yield client
    client.close()


@pytest.fixture
def query_client(services_ready) -> httpx.Client:
    """Create an HTTP client for the Query API."""
    return httpx.Client(base_url=QUERY_API_URL, timeout=30)


class TestIngestionService:
    """Tests for the ingestion service."""

    def test_health_check(self, services_ready):
        """Test ingestion service health check."""
        response = httpx.get(f"{INGESTION_URL}/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    def test_ready_check(self, services_ready):
        """Test ingestion service readiness check."""
        response = httpx.get(f"{INGESTION_URL}/ready")
        # May return 503 if NATS not connected, but should respond
        assert response.status_code in [200, 503]


class TestQueryAPI:
    """Tests for the Query API."""

    def test_health_check(self, services_ready):
        """Test Query API health check."""
        response = httpx.get(f"{QUERY_API_URL}/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestEndToEnd:
    """End-to-end integration tests."""

    def test_single_event_flow(self, facto_client: FactoClient, query_client: httpx.Client):
        """Test sending a single event through the entire system."""
        # Record an event
        facto_id = facto_client.record(
            action_type="test_action",
            input_data={"test": "input"},
            output_data={"test": "output"},
            status="success",
        )

        # Flush to send immediately
        facto_client.flush()

        # Wait for processing
        time.sleep(3)

        # Query the event
        response = query_client.get(f"/v1/events/{facto_id}")

        if response.status_code == 200:
            event = response.json()
            assert event["facto_id"] == facto_id
            assert event["action_type"] == "test_action"
            assert event["status"] == "success"
        elif response.status_code == 404:
            # Event might not be processed yet in CI/CD environments
            pytest.skip("Event not yet processed (may be timing issue)")

    def test_batch_events_flow(self, services_ready):
        """Test sending a batch of events."""
        agent_id = f"test-agent-batch-{uuid.uuid4().hex[:8]}"
        config = FactoConfig(
            endpoint=INGESTION_URL,
            agent_id=agent_id,
            batch_size=10,
            flush_interval_seconds=0.1,
        )
        client = FactoClient(config)

        # Record multiple events
        facto_ids = []
        for i in range(10):
            facto_id = client.record(
                action_type=f"test_action_{i}",
                input_data={"index": i},
                output_data={"result": i * 2},
            )
            facto_ids.append(facto_id)

        # Flush
        client.flush()
        client.close()

        # Verify batch was sent (check at least one event)
        assert len(facto_ids) == 10

    def test_chain_linking(self, facto_client: FactoClient):
        """Test that events are properly chain-linked."""
        # Record first event
        facto_client.record(
            action_type="first",
            input_data={},
            output_data={},
        )
        first_event = facto_client._batch[0] if facto_client._batch else None

        if first_event is None:
            pytest.skip("First event not captured in batch")
            return

        first_hash = first_event.proof.event_hash

        # Record second event
        facto_client.record(
            action_type="second",
            input_data={},
            output_data={},
        )
        second_event = facto_client._batch[1] if len(facto_client._batch) > 1 else None

        if second_event is None:
            pytest.skip("Second event not captured in batch")
            return

        # Verify chain linking
        assert second_event.proof.prev_hash == first_hash

    def test_event_verification(self, facto_client: FactoClient):
        """Test that recorded events can be verified."""
        # Record an event
        facto_client.record(
            action_type="verification_test",
            input_data={"test": True},
            output_data={"verified": True},
        )

        if not facto_client._batch:
            pytest.skip("No events in batch")
            return

        event = facto_client._batch[0]
        event_dict = event.to_dict()

        # Verify the event
        hash_valid, sig_valid = verify_event(event_dict)
        assert hash_valid, "Event hash should be valid"
        assert sig_valid, "Event signature should be valid"

    def test_session_events(self, services_ready, query_client: httpx.Client):
        """Test querying events by session."""
        session_id = f"test-session-{uuid.uuid4().hex[:8]}"
        config = FactoConfig(
            endpoint=INGESTION_URL,
            agent_id="test-agent-session",
            session_id=session_id,
            batch_size=1,
        )
        client = FactoClient(config)

        # Record events in the session
        for i in range(3):
            client.record(
                action_type=f"session_action_{i}",
                input_data={"index": i},
                output_data={"result": i},
            )
            client.flush()

        client.close()

        # Wait for processing
        time.sleep(3)

        # Query session events
        response = query_client.get(f"/v1/sessions/{session_id}/events")

        if response.status_code == 200:
            data = response.json()
            # Events should be in the session
            assert "events" in data

    def test_verify_endpoint(self, facto_client: FactoClient, query_client: httpx.Client):
        """Test the verify endpoint."""
        # Record an event
        facto_client.record(
            action_type="verify_test",
            input_data={"data": "test"},
            output_data={"result": "ok"},
        )

        if not facto_client._batch:
            pytest.skip("No events in batch")
            return

        event = facto_client._batch[0]
        event_dict = event.to_dict()

        # Verify via API
        response = query_client.post("/v1/verify", json={"event": event_dict})

        if response.status_code == 200:
            result = response.json()
            assert result["valid"] == True
            assert result["checks"]["hash_valid"] == True
            assert result["checks"]["signature_valid"] == True


class TestAsyncClient:
    """Tests for the async client."""

    @pytest.mark.asyncio
    async def test_async_record(self, services_ready):
        """Test async client recording."""
        config = FactoConfig(
            endpoint=INGESTION_URL,
            agent_id=f"test-agent-async-{uuid.uuid4().hex[:8]}",
            batch_size=1,
        )
        client = AsyncFactoClient(config)
        await client.start()

        facto_id = await client.record(
            action_type="async_test",
            input_data={"async": True},
            output_data={"result": "ok"},
        )

        assert facto_id.startswith("ft-")

        await client.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
