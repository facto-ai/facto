#!/usr/bin/env python3
"""
Load test for the Facto ingestion service.

This script simulates multiple agents sending events at high rates to
verify the system can handle the target throughput of 100M events/day
(~1,200 events/sec sustained).

Usage:
    python load_test.py --duration 60 --target-rps 1500 --agents 10

Prerequisites:
    pip install httpx pynacl
"""

import argparse
import asyncio
import base64
import hashlib
import json
import statistics
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx
from nacl.signing import SigningKey


@dataclass
class LoadTestConfig:
    """Configuration for load test."""
    endpoint: str = "http://localhost:8080"
    duration_seconds: int = 60
    target_rps: int = 1200
    num_agents: int = 10
    batch_size: int = 100
    connection_pool_size: int = 100
    timeout_seconds: float = 30.0


@dataclass
class LoadTestStats:
    """Statistics collected during load test."""
    total_events_sent: int = 0
    total_events_accepted: int = 0
    total_events_rejected: int = 0
    total_requests: int = 0
    failed_requests: int = 0
    latencies: List[float] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    errors: List[str] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    @property
    def events_per_second(self) -> float:
        if self.duration <= 0:
            return 0.0
        return self.total_events_accepted / self.duration

    @property
    def projected_daily_events(self) -> float:
        return self.events_per_second * 86400

    @property
    def p50_latency(self) -> float:
        if not self.latencies:
            return 0.0
        return statistics.median(self.latencies) * 1000  # ms

    @property
    def p95_latency(self) -> float:
        if not self.latencies:
            return 0.0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.95)
        return sorted_latencies[idx] * 1000  # ms

    @property
    def p99_latency(self) -> float:
        if not self.latencies:
            return 0.0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.99)
        return sorted_latencies[idx] * 1000  # ms

    @property
    def error_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.failed_requests / self.total_requests * 100


class SimulatedAgent:
    """Simulates an AI agent sending facto events."""

    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        self.session_id = f"session-{uuid.uuid4().hex[:12]}"
        self.signing_key = SigningKey.generate()
        self.public_key = self.signing_key.verify_key
        self.prev_hash = "0" * 64
        self.event_count = 0

    def generate_event(self) -> Dict[str, Any]:
        """Generate a facto event."""
        facto_id = f"ft-{uuid.uuid4()}"
        now = int(time.time() * 1_000_000_000)

        event = {
            "facto_id": facto_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "parent_facto_id": None,
            "action_type": "llm_call",
            "status": "success",
            "input_data": {"prompt": f"Test prompt {self.event_count}"},
            "output_data": {"response": f"Test response {self.event_count}"},
            "execution_meta": {
                "model_id": "gpt-4",
                "model_hash": None,
                "temperature": 0.7,
                "seed": None,
                "max_tokens": 1000,
                "tool_calls": [],
                "sdk_version": "0.1.0",
                "sdk_language": "python",
                "tags": {"test": "load_test"},
            },
            "proof": {
                "prev_hash": self.prev_hash,
            },
            "started_at": now,
            "completed_at": now,
        }

        # Build canonical form and compute hash/signature
        canonical = self._build_canonical(event)
        event_hash = hashlib.sha3_256(canonical.encode()).hexdigest()
        signature = self.signing_key.sign(canonical.encode()).signature

        event["proof"]["event_hash"] = event_hash
        event["proof"]["signature"] = base64.b64encode(signature).decode()
        event["proof"]["public_key"] = base64.b64encode(bytes(self.public_key)).decode()

        self.prev_hash = event_hash
        self.event_count += 1

        return event

    def _build_canonical(self, event: Dict[str, Any]) -> str:
        """Build canonical form for hashing."""
        canonical = {
            "action_type": event["action_type"],
            "agent_id": event["agent_id"],
            "completed_at": event["completed_at"],
            "execution_meta": {
                "model_id": event["execution_meta"]["model_id"],
                "seed": event["execution_meta"]["seed"],
                "sdk_version": event["execution_meta"]["sdk_version"],
                "temperature": event["execution_meta"]["temperature"],
                "tool_calls": event["execution_meta"]["tool_calls"],
            },
            "input_data": event["input_data"],
            "output_data": event["output_data"],
            "parent_facto_id": event["parent_facto_id"],
            "prev_hash": event["proof"]["prev_hash"],
            "session_id": event["session_id"],
            "started_at": event["started_at"],
            "status": event["status"],
            "facto_id": event["facto_id"],
        }
        return json.dumps(canonical, sort_keys=True, separators=(",", ":"))


class LoadTester:
    """Runs load tests against the ingestion service."""

    def __init__(self, config: LoadTestConfig):
        self.config = config
        self.stats = LoadTestStats()
        self.agents: List[SimulatedAgent] = []
        self._stop_event = asyncio.Event()

    async def run(self) -> LoadTestStats:
        """Run the load test."""
        print(f"\n{'='*60}")
        print("FACTO LOAD TEST")
        print(f"{'='*60}")
        print(f"Endpoint: {self.config.endpoint}")
        print(f"Duration: {self.config.duration_seconds} seconds")
        print(f"Target RPS: {self.config.target_rps}")
        print(f"Agents: {self.config.num_agents}")
        print(f"Batch size: {self.config.batch_size}")
        print(f"{'='*60}\n")

        # Create agents
        self.agents = [
            SimulatedAgent(f"load-test-agent-{i:04d}")
            for i in range(self.config.num_agents)
        ]

        # Calculate events per agent per second
        events_per_agent_per_second = self.config.target_rps / self.config.num_agents

        # Create HTTP client with connection pooling
        limits = httpx.Limits(
            max_connections=self.config.connection_pool_size,
            max_keepalive_connections=self.config.connection_pool_size,
        )
        async with httpx.AsyncClient(
            base_url=self.config.endpoint,
            limits=limits,
            timeout=self.config.timeout_seconds,
        ) as client:
            # Start time
            self.stats.start_time = time.time()

            # Create tasks for each agent
            tasks = []
            for agent in self.agents:
                task = asyncio.create_task(
                    self._agent_loop(client, agent, events_per_agent_per_second)
                )
                tasks.append(task)

            # Run for duration
            await asyncio.sleep(self.config.duration_seconds)
            self._stop_event.set()

            # Wait for all tasks to complete
            await asyncio.gather(*tasks, return_exceptions=True)

            self.stats.end_time = time.time()

        return self.stats

    async def _agent_loop(
        self,
        client: httpx.AsyncClient,
        agent: SimulatedAgent,
        target_eps: float,
    ):
        """Run event generation loop for an agent."""
        interval = 1.0 / target_eps if target_eps > 0 else 1.0
        batch: List[Dict[str, Any]] = []

        while not self._stop_event.is_set():
            # Generate events for batch
            batch.append(agent.generate_event())

            if len(batch) >= self.config.batch_size:
                await self._send_batch(client, batch)
                batch = []

            # Rate limiting
            await asyncio.sleep(interval)

        # Send remaining events
        if batch:
            await self._send_batch(client, batch)

    async def _send_batch(
        self,
        client: httpx.AsyncClient,
        events: List[Dict[str, Any]],
    ):
        """Send a batch of events."""
        payload = {"events": events}
        start = time.time()

        try:
            response = await client.post("/v1/ingest/batch", json=payload)
            latency = time.time() - start

            self.stats.total_requests += 1
            self.stats.latencies.append(latency)
            self.stats.total_events_sent += len(events)

            if response.status_code == 202:
                data = response.json()
                self.stats.total_events_accepted += data.get("accepted_count", 0)
                self.stats.total_events_rejected += data.get("rejected_count", 0)
            else:
                self.stats.failed_requests += 1
                self.stats.errors.append(f"HTTP {response.status_code}")

        except Exception as e:
            self.stats.failed_requests += 1
            self.stats.total_requests += 1
            self.stats.errors.append(str(e))

    def print_results(self):
        """Print test results."""
        print(f"\n{'='*60}")
        print("LOAD TEST RESULTS")
        print(f"{'='*60}")
        print(f"Duration: {self.stats.duration:.2f} seconds")
        print(f"Total events sent: {self.stats.total_events_sent:,}")
        print(f"Total events accepted: {self.stats.total_events_accepted:,}")
        print(f"Total events rejected: {self.stats.total_events_rejected:,}")
        print(f"Total requests: {self.stats.total_requests:,}")
        print(f"Failed requests: {self.stats.failed_requests:,}")
        print(f"{'='*60}")
        print(f"Events/second: {self.stats.events_per_second:,.0f}")
        print(f"Projected daily: {self.stats.projected_daily_events:,.0f} events")
        print(f"Target (100M/day): {100_000_000:,} events")
        print(f"{'='*60}")
        print(f"Latency p50: {self.stats.p50_latency:.2f} ms")
        print(f"Latency p95: {self.stats.p95_latency:.2f} ms")
        print(f"Latency p99: {self.stats.p99_latency:.2f} ms")
        print(f"Error rate: {self.stats.error_rate:.2f}%")
        print(f"{'='*60}")

        # Check if targets were met
        target_eps = 1200  # 100M / 86400
        target_p99 = 100  # ms

        eps_met = self.stats.events_per_second >= target_eps
        p99_met = self.stats.p99_latency <= target_p99
        zero_loss = self.stats.total_events_rejected == 0

        print("\nTARGETS:")
        print(f"  [{'✓' if eps_met else '✗'}] Throughput >= {target_eps} events/sec")
        print(f"  [{'✓' if p99_met else '✗'}] p99 latency <= {target_p99} ms")
        print(f"  [{'✓' if zero_loss else '✗'}] Zero data loss")

        if self.stats.errors:
            print(f"\nSample errors (first 5):")
            for error in self.stats.errors[:5]:
                print(f"  - {error}")

        print(f"{'='*60}\n")


async def main():
    parser = argparse.ArgumentParser(description="Facto Load Test")
    parser.add_argument(
        "--endpoint",
        default="http://localhost:8080",
        help="Ingestion service endpoint",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Test duration in seconds",
    )
    parser.add_argument(
        "--target-rps",
        type=int,
        default=1500,
        help="Target requests per second",
    )
    parser.add_argument(
        "--agents",
        type=int,
        default=10,
        help="Number of simulated agents",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Events per batch",
    )
    args = parser.parse_args()

    config = LoadTestConfig(
        endpoint=args.endpoint,
        duration_seconds=args.duration,
        target_rps=args.target_rps,
        num_agents=args.agents,
        batch_size=args.batch_size,
    )

    tester = LoadTester(config)

    try:
        await tester.run()
        tester.print_results()
    except KeyboardInterrupt:
        print("\nTest interrupted")
        tester.stats.end_time = time.time()
        tester.print_results()


if __name__ == "__main__":
    asyncio.run(main())
