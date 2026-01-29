/**
 * Data models for the Facto SDK.
 */

/**
 * Configuration for the Facto client.
 */
export interface FactoConfig {
  /** The endpoint URL of the ingestion service */
  endpoint: string;
  /** Unique identifier for this agent */
  agentId: string;
  /** Optional session ID (auto-generated if not provided) */
  sessionId?: string;
  /** Ed25519 private key seed (32 bytes) */
  privateKey?: Uint8Array;
  /** Ed25519 public key (32 bytes) */
  publicKey?: Uint8Array;
  /** Number of events to batch before sending (default: 100) */
  batchSize?: number;
  /** Flush interval in milliseconds (default: 1000) */
  flushIntervalMs?: number;
  /** Request timeout in milliseconds (default: 30000) */
  timeoutMs?: number;
  /** Maximum retry attempts (default: 3) */
  maxRetries?: number;
  /** Default tags to include with all events */
  tags?: Record<string, string>;
}

/**
 * Execution metadata for a facto event.
 */
export interface ExecutionMeta {
  modelId?: string;
  modelHash?: string;
  temperature?: number;
  seed?: number;
  maxTokens?: number;
  toolCalls?: unknown[];
  sdkVersion: string;
  sdkLanguage: string;
  tags: Record<string, string>;
}

/**
 * Cryptographic proof for a facto event.
 */
export interface Proof {
  /** Base64-encoded Ed25519 signature */
  signature: string;
  /** Base64-encoded Ed25519 public key */
  publicKey: string;
  /** SHA3-256 hash of previous event (hex) */
  prevHash: string;
  /** SHA3-256 hash of this event (hex) */
  eventHash: string;
}

/**
 * A facto event representing an agent action.
 */
export interface FactoEvent {
  factoId: string;
  agentId: string;
  sessionId: string;
  parentFactoId?: string | null;
  actionType: string;
  status: string;
  inputData: Record<string, unknown>;
  outputData: Record<string, unknown>;
  executionMeta: ExecutionMeta;
  proof: Proof;
  startedAt: number;
  completedAt: number;
}

/**
 * Wire format for FactoEvent (snake_case for JSON serialization).
 */
export interface FactoEventWire {
  facto_id: string;
  agent_id: string;
  session_id: string;
  parent_facto_id: string | null;
  action_type: string;
  status: string;
  input_data: Record<string, unknown>;
  output_data: Record<string, unknown>;
  execution_meta: {
    model_id: string | null;
    model_hash: string | null;
    temperature: number | null;
    seed: number | null;
    max_tokens: number | null;
    tool_calls: unknown[];
    sdk_version: string;
    sdk_language: string;
    tags: Record<string, string>;
  };
  proof: {
    signature: string;
    public_key: string;
    prev_hash: string;
    event_hash: string;
  };
  started_at: number;
  completed_at: number;
}

/**
 * Options for recording a facto event.
 */
export interface RecordOptions {
  actionType: string;
  inputData: Record<string, unknown>;
  outputData: Record<string, unknown>;
  status?: string;
  parentFactoId?: string;
  executionMeta?: Partial<ExecutionMeta>;
  startedAt?: number;
  completedAt?: number;
}

/**
 * Context for tracing an action.
 */
export interface FactoContext {
  factoId: string;
  setOutput(output: unknown): void;
  setStatus(status: string): void;
  setError(error: Error): void;
}

/**
 * Batch ingest request.
 */
export interface BatchIngestRequest {
  events: FactoEventWire[];
  batch_id?: string;
}

/**
 * Batch ingest response.
 */
export interface BatchIngestResponse {
  accepted_count: number;
  rejected_count: number;
  rejected: Array<{
    facto_id: string;
    reason: string;
  }>;
}

/**
 * Generate a new facto ID.
 */
export function generateFactoId(): string {
  const uuid = crypto.randomUUID();
  return `ft-${uuid}`;
}

/**
 * Generate a session ID.
 */
export function generateSessionId(): string {
  const uuid = crypto.randomUUID().replace(/-/g, '').slice(0, 12);
  return `session-${uuid}`;
}

/**
 * Get current time in nanoseconds since epoch.
 */
export function currentTimeNs(): number {
  return Math.floor(Date.now() * 1_000_000);
}

/**
 * Convert a FactoEvent to wire format (snake_case).
 */
export function toWireFormat(event: FactoEvent): FactoEventWire {
  return {
    facto_id: event.factoId,
    agent_id: event.agentId,
    session_id: event.sessionId,
    parent_facto_id: event.parentFactoId ?? null,
    action_type: event.actionType,
    status: event.status,
    input_data: event.inputData,
    output_data: event.outputData,
    execution_meta: {
      model_id: event.executionMeta.modelId ?? null,
      model_hash: event.executionMeta.modelHash ?? null,
      temperature: event.executionMeta.temperature ?? null,
      seed: event.executionMeta.seed ?? null,
      max_tokens: event.executionMeta.maxTokens ?? null,
      tool_calls: event.executionMeta.toolCalls ?? [],
      sdk_version: event.executionMeta.sdkVersion,
      sdk_language: event.executionMeta.sdkLanguage,
      tags: event.executionMeta.tags,
    },
    proof: {
      signature: event.proof.signature,
      public_key: event.proof.publicKey,
      prev_hash: event.proof.prevHash,
      event_hash: event.proof.eventHash,
    },
    started_at: event.startedAt,
    completed_at: event.completedAt,
  };
}
