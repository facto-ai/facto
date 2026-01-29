#!/usr/bin/env python3
"""
Basic usage example for the Facto SDK.

This example demonstrates:
1. Initializing the client
2. Recording events manually
3. Using the context manager
4. Using the decorator
5. Verifying events
"""

import time
from facto_sdk import (
    FactoClient,
    FactoConfig,
    ExecutionMeta,
    verify_event,
)


def simulate_llm_call(prompt: str) -> str:
    """Simulate an LLM call."""
    time.sleep(0.1)  # Simulate latency
    return f"Response to: {prompt}"


def simulate_tool_call(tool_name: str, args: dict) -> dict:
    """Simulate a tool call."""
    time.sleep(0.05)
    return {"result": f"Executed {tool_name}", "args": args}


def main():
    # Initialize the client
    print("Initializing Facto client...")
    config = FactoConfig(
        endpoint="http://127.0.0.1:8080",
        agent_id="example-agent-001",
        tags={"environment": "development", "version": "1.0.0"},
    )
    client = FactoClient(config)
    print(f"Session ID: {config.session_id}")

    # Method 1: Manual recording
    print("\n1. Recording events manually...")
    facto_id = client.record(
        action_type="initialization",
        input_data={"config": {"model": "gpt-4", "temperature": 0.7}},
        output_data={"status": "ready"},
        execution_meta=ExecutionMeta(
            model_id="gpt-4",
            temperature=0.7,
        ),
    )
    print(f"   Recorded initialization event: {facto_id}")

    # Method 2: Context manager
    print("\n2. Using context manager...")
    with client.facto(
        "llm_call",
        input_data={"prompt": "What is the capital of France?"},
        execution_meta=ExecutionMeta(model_id="gpt-4", temperature=0.7),
    ) as ctx:
        response = simulate_llm_call("What is the capital of France?")
        ctx.output = {"response": response, "tokens": 42}
    print(f"   Recorded LLM call event: {ctx.facto_id}")

    # Method 3: Decorator
    print("\n3. Using decorator...")

    @client.factod("tool_use")
    def search_web(query: str) -> dict:
        """Search the web for a query."""
        return simulate_tool_call("web_search", {"query": query})

    result = search_web("latest AI news")
    print(f"   Recorded tool use event for web search")

    # Multiple events with parent-child relationship
    print("\n4. Recording nested events...")
    with client.facto("agent_task", input_data={"task": "research"}) as parent_ctx:
        # Child event 1
        with client.facto(
            "llm_call",
            input_data={"prompt": "Analyze the research topic"},
            parent_facto_id=parent_ctx.facto_id,
        ) as child1:
            child1.output = {"analysis": "Topic is interesting"}

        # Child event 2
        with client.facto(
            "tool_use",
            input_data={"tool": "database_query"},
            parent_facto_id=parent_ctx.facto_id,
        ) as child2:
            child2.output = {"records": 10}

        parent_ctx.output = {"status": "completed", "children": 2}
    print(f"   Recorded parent event: {parent_ctx.facto_id}")

    # Demonstrate error handling
    print("\n5. Recording error events...")
    try:
        with client.facto("risky_operation", input_data={"action": "divide"}) as ctx:
            raise ValueError("Division by zero")
    except ValueError:
        pass  # Error is automatically recorded
    print(f"   Recorded error event: {ctx.facto_id}")

    # Verify an event
    print("\n6. Verifying event integrity...")
    # Get the last event from the batch
    if client._batch:
        last_event = client._batch[-1]
        event_dict = last_event.to_dict()
        hash_valid, sig_valid = verify_event(event_dict)
        print(f"   Hash valid: {hash_valid}")
        print(f"   Signature valid: {sig_valid}")

    # Flush and close
    print("\n7. Flushing events...")
    try:
        client.flush()
        print("   Events flushed successfully!")
    except Exception as e:
        print(f"   Note: Could not connect to server ({e})")
        print("   Events are still in the batch and would be sent when server is available")

    # Print batch summary
    print(f"\nTotal events recorded: {len(client._batch)}")
    for event in client._batch:
        print(f"  - {event.action_type}: {event.facto_id}")

    client.close()
    print("\nClient closed.")


if __name__ == "__main__":
    main()
