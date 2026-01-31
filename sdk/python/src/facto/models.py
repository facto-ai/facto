"""Data models for the Facto SDK."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time
import uuid


@dataclass
class FactoConfig:
    """Configuration for the Facto client."""

    endpoint: str
    agent_id: str
    session_id: Optional[str] = None
    private_key: Optional[bytes] = None  # Ed25519 private key (32 bytes seed)
    public_key: Optional[bytes] = None  # Ed25519 public key (32 bytes)
    batch_size: int = 100
    flush_interval_seconds: float = 1.0
    timeout_seconds: float = 30.0
    max_retries: int = 3
    tags: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.session_id:
            self.session_id = f"session-{uuid.uuid4().hex[:12]}"


@dataclass
class ExecutionMeta:
    """Execution metadata for a facto event."""

    model_id: Optional[str] = None
    model_hash: Optional[str] = None
    temperature: Optional[float] = None
    seed: Optional[int] = None
    max_tokens: Optional[int] = None
    tool_calls: List[Any] = field(default_factory=list)
    sdk_version: str = "0.1.0"
    sdk_language: str = "python"
    tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class Proof:
    """Cryptographic proof for a facto event."""

    signature: str  # Base64-encoded Ed25519 signature
    public_key: str  # Base64-encoded Ed25519 public key
    prev_hash: str  # SHA3-256 hash of previous event (hex)
    event_hash: str  # SHA3-256 hash of this event (hex)


@dataclass
class FactoEvent:
    """A facto event representing an agent action."""

    facto_id: str
    agent_id: str
    session_id: str
    action_type: str
    status: str
    input_data: Dict[str, Any]
    output_data: Dict[str, Any]
    execution_meta: ExecutionMeta
    proof: Proof
    started_at: int  # Nanoseconds since epoch
    completed_at: int  # Nanoseconds since epoch
    parent_facto_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "facto_id": self.facto_id,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "parent_facto_id": self.parent_facto_id,
            "action_type": self.action_type,
            "status": self.status,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "execution_meta": {
                "model_id": self.execution_meta.model_id,
                "model_hash": self.execution_meta.model_hash,
                "temperature": self.execution_meta.temperature,
                "seed": self.execution_meta.seed,
                "max_tokens": self.execution_meta.max_tokens,
                "tool_calls": self.execution_meta.tool_calls,
                "sdk_version": self.execution_meta.sdk_version,
                "sdk_language": self.execution_meta.sdk_language,
                "tags": self.execution_meta.tags,
            },
            "proof": {
                "signature": self.proof.signature,
                "public_key": self.proof.public_key,
                "prev_hash": self.proof.prev_hash,
                "event_hash": self.proof.event_hash,
            },
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass
class FactoContext:
    """Context manager for tracing an action."""

    client: Any  # FactoClient
    action_type: str
    input_data: Dict[str, Any]
    started_at: int
    parent_facto_id: Optional[str] = None
    execution_meta: Optional[ExecutionMeta] = None
    output: Any = None
    status: str = "success"
    _facto_id: Optional[str] = None

    @property
    def facto_id(self) -> str:
        if self._facto_id is None:
            self._facto_id = generate_facto_id()
        return self._facto_id

    def set_output(self, output: Any) -> None:
        """Set the output data."""
        self.output = output

    def set_status(self, status: str) -> None:
        """Set the status."""
        self.status = status

    def set_error(self, error: Exception) -> None:
        """Set error status and output."""
        self.status = "error"
        self.output = {
            "error_type": type(error).__name__,
            "error_message": str(error),
        }


def generate_facto_id() -> str:
    """Generate a new facto ID using UUIDv4."""
    return f"ft-{uuid.uuid4()}"


def current_time_ns() -> int:
    """
    Get current time in nanoseconds since epoch.
    Truncated to millisecond precision to match ScyllaDB timestamp limitation.
    """
    return int(time.time() * 1_000) * 1_000_000
