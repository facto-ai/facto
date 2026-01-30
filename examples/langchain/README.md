# LangChain + Facto Integration

Cryptographically signed, tamper-proof audit trails for your LangChain agents.

## Installation

```bash
pip install facto-sdk langchain langchain-openai
```

## Quick Start

### Option 1: Decorator (Simplest)

```python
import os
from langchain_openai import ChatOpenAI
from facto_sdk import FactoClient, FactoConfig

# Initialize Facto
facto = FactoClient(FactoConfig(
    endpoint="http://localhost:8080",
    agent_id="my-langchain-agent",
))

# Create your LLM
llm = ChatOpenAI(model="gpt-4")

@facto.factod("llm_call")
def traced_llm_call(prompt: str) -> str:
    """Every call is cryptographically logged."""
    response = llm.invoke(prompt)
    return response.content

# Use it
result = traced_llm_call("What is the capital of France?")
print(result)

facto.close()
```

### Option 2: Context Manager (More Control)

```python
from langchain_openai import ChatOpenAI
from facto_sdk import FactoClient, FactoConfig, ExecutionMeta

facto = FactoClient(FactoConfig(
    endpoint="http://localhost:8080",
    agent_id="my-langchain-agent",
))

llm = ChatOpenAI(model="gpt-4")

with facto.facto("llm_call", input_data={"prompt": "Hello"}) as ctx:
    response = llm.invoke("Hello, world!")
    ctx.output = {"response": response.content}
    ctx.meta = ExecutionMeta(
        model_id="gpt-4",
        temperature=0.7,
    )

facto.close()
```

### Option 3: Manual Recording

```python
import time
from langchain_openai import ChatOpenAI
from facto_sdk import FactoClient, FactoConfig

facto = FactoClient(FactoConfig(
    endpoint="http://localhost:8080",
    agent_id="my-langchain-agent",
))

llm = ChatOpenAI(model="gpt-4")

# Record start
start_time = time.time_ns()
prompt = "Explain quantum computing in one sentence."

# Call LLM
response = llm.invoke(prompt)

# Record end
facto.record(
    action_type="llm_call",
    input_data={"prompt": prompt},
    output_data={"response": response.content},
    status="success",
)

print(f"Response: {response.content}")

facto.close()
```

## Verification

Every event is:
- **Hashed** with SHA3-256
- **Signed** with Ed25519
- **Chain-linked** via `prev_hash`

Verify your audit trail:

```bash
# Export evidence bundle
curl "http://localhost:8082/v1/evidence-package?session_id=YOUR_SESSION_ID" > evidence.json

# Verify offline (no network required)
facto verify evidence.json
```

## Environment Variables

```bash
export OPENAI_API_KEY=sk-...
export FACTO_ENDPOINT=http://localhost:8080
```

## Full Example

See [basic_usage.py](./basic_usage.py) for a complete working example.
