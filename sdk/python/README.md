# Facto Python SDK

**Forensic Accountability Infrastructure for AI Agents**

`facto-ai` is the Python SDK for Facto, a system designed to create tamper-proof, verifiable audit trails for AI agent actions. It allows you to wrap LLM calls and agent steps, automatically generating cryptographically signed events that are stored in a verifiable log.

## Features

- **Cryptographic Signatures**: Every event is signed with Ed25519, ensuring authenticity.
- **Tamper-Proof Logging**: Events form a hash chain, making the history immutable.
- **Easy Integration**: Use decorators or context managers to wrap your existing code.
- **Verification CLI**: Included CLI tool to verify evidence bundles offline.

## Installation

```bash
pip install facto-ai
```

## Quick Start

### 1. Initialize the Client

```python
from facto import FactoClient, FactoConfig

client = FactoClient(
    FactoConfig(
        endpoint="http://localhost:8080",  # Your Facto ingestion endpoint
        agent_id="my-agent-001",
    )
)
```

### 2. Wrap LLM Calls

**Using the Decorator:**

```python
from facto import ExecutionMeta

@client.factod(
    action_type="llm_call",
    execution_meta=ExecutionMeta(model_id="gpt-4")
)
def chat_with_llm(prompt):
    # Your LLM logic here
    return {"response": "Hello world!"}

result = chat_with_llm("Hi there")
```

**Using the Context Manager:**

```python
with client.facto(
    "tool_execution",
    input_data={"tool": "search", "query": "weather in sf"}
) as ctx:
    # Perform action
    result = perform_search("weather in sf")
    
    # Record output
    ctx.output = result
    ctx.status = "success"
```

### 3. Verify Events

You can verify exported evidence bundles using the CLI:

```bash
facto verify path/to/evidence.json
```

## Documentation

For full documentation, visit [docs.facto.ai](https://docs.facto.ai) or the [GitHub Repository](https://github.com/facto-ai/facto).
