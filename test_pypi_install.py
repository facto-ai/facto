
import sys
import uuid
import asyncio
from typing import Dict, Any

# Ensure we are not importing from local source
for path in sys.path:
    if "sdk/python/src" in path:
        print(f"WARNING: Local source path found in sys.path: {path}")

try:
    import facto
    from facto import FactoClient, FactoConfig, CryptoProvider, FactoEvent
    from facto import generate_keypair, current_time_ns
    print(f"✅ Successfully imported facto-ai (version {facto.__version__})")
except ImportError as e:
    print(f"❌ Failed to import facto-ai: {e}")
    sys.exit(1)

async def test_basic_usage():
    print("\n--- Testing Basic Usage ---")
    
    # 1. Crypto Provider
    try:
        kp = generate_keypair()
        # kp is likely (signing_key, verify_key) objects or bytes
        # Let's inspect what it returns. Based on previous error, key[0] is bytes.
        private_key_bytes = kp[0]
        crypto = CryptoProvider(private_key_bytes)
        print("✅ CryptoProvider initialized and keypair generated")
    except Exception as e:
        print(f"❌ CryptoProvider failed: {e}")
        return

    # 2. Client Initialization (Mock endpoint)
    try:
        client = FactoClient(FactoConfig(
            endpoint="http://localhost:8080",
            agent_id="test-agent-pypi"
        ))
        print("✅ FactoClient initialized")
    except Exception as e:
        print(f"❌ FactoClient init failed: {e}")
        return

    # 3. Create Event Object (Mock)
    try:
        event = FactoEvent(
            facto_id=f"ft-{uuid.uuid4()}",
            agent_id="test-agent",
            session_id="test-session",
            action_type="test_action",
            status="success",
            input_data={"foo": "bar"},
            output_data={"baz": "qux"},
            execution_meta={"model_id": "test-model"},
            proof={"event_hash": "test-hash", "signature": "test-sig"},
            started_at=current_time_ns(),
            completed_at=current_time_ns()
        )
        print("✅ FactoEvent model created")
    except Exception as e:
        print(f"❌ FactoEvent model failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_basic_usage())
