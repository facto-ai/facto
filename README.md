<p align="center">
  <h1 align="center">Facto</h1>
  <p align="center">
    <strong>Forensic Accountability Infrastructure for AI Agents</strong>
  </p>
  <p align="center">
    Tamper-proof event logging for the agentic economy
  </p>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> •
  <a href="#why-facto">Why Facto</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#sdks">SDKs</a>
</p>

---

## The Problem

AI agents are making autonomous decisions—signing contracts, executing trades, making purchases. When something goes wrong, who's accountable?

**Starting August 2, 2026**, the EU AI Act requires high-risk AI systems to maintain detailed logs of their operations. Traditional logging isn't enough. You need:

- ✅ **Cryptographic proof** that logs haven't been tampered with
- ✅ **Third-party verification** independent of the AI operator
- ✅ **Legal admissibility** for audits and disputes

**Facto is the black box flight recorder for AI agents.**

## Why Facto

| Feature | Traditional Logs | Facto |
|---------|-----------------|-------|
| Tamper-proof | ❌ | ✅ Ed25519 signatures + SHA3-256 hashes |
| Chain integrity | ❌ | ✅ Hash chain linking (prev_hash) |
| Third-party verifiable | ❌ | ✅ Merkle tree anchoring |
| Legal evidence packages | ❌ | ✅ Export for audits |
| High throughput | Varies | ✅ 4,000+ events/sec |

## Quick Start

### 1. Start Infrastructure

```bash
git clone https://github.com/facto-ai/facto.git
cd facto
docker compose up -d
```

### 2. Start Services

```bash
# Terminal 1: Ingestion (Rust)
cd server/ingestion && cargo build --release
RUST_LOG=info ./target/release/facto-ingestion

# Terminal 2: Processor (Go)
cd server/processor && go build -o processor . && ./processor

# Terminal 3: API (Go)
cd server/api && go build -o api . && ./api
```

### 3. Install SDK

```bash
pip install facto-ai
```

### 4. Record Your First Event

```python
from facto import FactoClient, FactoConfig

client = FactoClient(FactoConfig(
    endpoint="http://localhost:8080",
    agent_id="my-agent-001",
))

# Record an AI action
facto_id = client.record(
    action_type="llm_call",
    input_data={"prompt": "Book a flight to Paris"},
    output_data={"response": "I've booked flight AF123 for €450"},
)

print(f"Recorded: {facto_id}")
# Output: Recorded: ft-a1b2c3d4-5678-90ab-cdef-1234567890ab

client.close()
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           YOUR AI AGENT                                 │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  Facto SDK (Python / TypeScript)                                  │  │
│  │  • Generate facto_id (UUIDv4)                                     │  │
│  │  • Compute SHA3-256 hash                                          │  │
│  │  • Sign with Ed25519                                              │  │
│  │  • Link to previous event (prev_hash)                             │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ HTTPS POST /v1/ingest/batch
┌─────────────────────────────────────────────────────────────────────────┐
│                         FACTO INFRASTRUCTURE                            │
│                                                                         │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────────┐  │
│  │  Ingestion      │    │  NATS JetStream │    │  Processor          │  │
│  │  (Rust + Axum)  │───▶│  (Message Queue)│───▶│  (Go)               │  │
│  │  :8080          │    │  :4222          │    │  :8081              │  │
│  │                 │    │                 │    │  • Merkle trees     │  │
│  │  • Verify sigs  │    │  • Durable      │    │  • Batch writes     │  │
│  │  • Rate limit   │    │  • At-least-once│    │                     │  │
│  └─────────────────┘    └─────────────────┘    └──────────┬──────────┘  │
│                                                           │             │
│                                                           ▼             │
│                            ┌─────────────────────────────────────────┐  │
│                            │  ScyllaDB                               │  │
│                            │  • events, events_by_facto_id           │  │
│                            │  • events_by_session, merkle_roots      │  │
│                            │  :9042                                  │  │
│                            └─────────────────────────────────────────┘  │
│                                                           │             │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  Query API (Go + Gin)                                    :8082    │  │
│  │  • GET  /v1/events?agent_id=X&start=T1&end=T2                     │  │
│  │  • GET  /v1/events/{facto_id}                                     │  │
│  │  • POST /v1/verify                                                │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## SDKs

### Python

```python
from facto import FactoClient, FactoConfig, ExecutionMeta

client = FactoClient(FactoConfig(
    endpoint="http://localhost:8080",
    agent_id="my-agent",
))

# Option 1: Simple record
client.record("tool_call", {"tool": "search"}, {"results": [...]})

# Option 2: Decorator
@client.factod("openai_call", ExecutionMeta(model_id="gpt-4"))
async def call_openai(prompt):
    return await openai.chat.completions.create(...)

# Option 3: Context manager
with client.facto("complex_operation", {"step": 1}) as ctx:
    result = do_something()
    ctx.output = {"result": result}
```

### TypeScript

```typescript
import { FactoClient } from 'facto-sdk';

const client = new FactoClient({
  endpoint: 'http://localhost:8080',
  agentId: 'my-agent',
});

// Record events
await client.record({
  actionType: 'api_call',
  inputData: { url: 'https://api.example.com' },
  outputData: { status: 200 },
});

await client.close();
```



## EU AI Act Compliance

**Article 12: Record-Keeping** (applicable from August 2, 2026) requires:

> *"High-risk AI systems shall technically allow for the automatic recording of events (logs) over the lifetime of the system."*
>
> *"Logging capabilities shall enable the recording of events relevant for identifying situations that may result in the high-risk AI system presenting a risk [...] facilitating post-market monitoring [...] and monitoring the operation of high-risk AI systems."*
>
> — Article 12, EU AI Act

Facto provides the technical infrastructure to meet these requirements with cryptographically verifiable, tamper-proof audit trails.

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License - see [LICENSE](LICENSE) for details.

---

<p align="center">
  <strong>Built for the agentic economy</strong>
</p>
