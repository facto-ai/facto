"""
Facto SDK - Forensic Accountability Infrastructure for AI Agents

This SDK provides tools for capturing and signing facto events from AI agents,
creating tamper-proof audit trails for compliance and debugging.

Example usage:
    from facto import FactoClient, FactoConfig

    client = FactoClient(FactoConfig(
        endpoint="http://localhost:8080",
        agent_id="my-agent",
    ))

    # Using context manager
    with client.facto("llm_call", input_data={"prompt": "Hello"}) as ctx:
        response = call_llm()
        ctx.output = response

    # Using decorator
    @client.factod("process_document")
    def process(doc):
        return analyze(doc)

    # Manual recording
    client.record(
        action_type="decision",
        input_data={"options": [1, 2, 3]},
        output_data={"choice": 2},
        status="success"
    )

    client.close()
"""

from .client import AsyncFactoClient, FactoClient
from .crypto import CryptoProvider, generate_keypair, verify_event
from .cli import verify_evidence_bundle
from .models import (
    ExecutionMeta,
    Proof,
    FactoConfig,
    FactoContext,
    FactoEvent,
    current_time_ns,
    generate_facto_id,
)

__version__ = "0.1.1"
__all__ = [
    # Clients
    "FactoClient",
    "AsyncFactoClient",
    # Configuration
    "FactoConfig",
    # Models
    "FactoEvent",
    "FactoContext",
    "ExecutionMeta",
    "Proof",
    # Crypto
    "CryptoProvider",
    "generate_keypair",
    "verify_event",
    # CLI / Verification
    "verify_evidence_bundle",
    # Utilities
    "generate_facto_id",
    "current_time_ns",
]
