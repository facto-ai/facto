/**
 * Facto client for sending events to the ingestion service.
 */

import { CryptoProvider } from './crypto';
import {
  type BatchIngestRequest,
  type BatchIngestResponse,
  type ExecutionMeta,
  type Proof,
  type RecordOptions,
  type FactoConfig,
  type FactoContext,
  type FactoEvent,
  type FactoEventWire,
  currentTimeNs,
  generateSessionId,
  generateFactoId,
  toWireFormat,
} from './models';

const SDK_VERSION = '0.1.0';
const SDK_LANGUAGE = 'typescript';

/**
 * Facto client for sending events to the ingestion service.
 */
export class FactoClient {
  private config: Required<
    Omit<FactoConfig, 'privateKey' | 'publicKey'> & {
      privateKey?: Uint8Array;
      publicKey?: Uint8Array;
    }
  >;
  private crypto: CryptoProvider;
  private batch: FactoEvent[] = [];
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private closed = false;

  /**
   * Create a new FactoClient.
   *
   * @param config - Configuration for the client
   */
  constructor(config: FactoConfig) {
    this.config = {
      endpoint: config.endpoint,
      agentId: config.agentId,
      sessionId: config.sessionId ?? generateSessionId(),
      privateKey: config.privateKey,
      publicKey: config.publicKey,
      batchSize: config.batchSize ?? 100,
      flushIntervalMs: config.flushIntervalMs ?? 1000,
      timeoutMs: config.timeoutMs ?? 30000,
      maxRetries: config.maxRetries ?? 3,
      tags: config.tags ?? {},
    };

    this.crypto = new CryptoProvider(config.privateKey);

    // Start periodic flush
    this.flushTimer = setInterval(() => {
      if (!this.closed) {
        this.flush().catch(console.error);
      }
    }, this.config.flushIntervalMs);
  }

  /**
   * Get the session ID.
   */
  get sessionId(): string {
    return this.config.sessionId;
  }

  /**
   * Get the public key as base64.
   */
  get publicKey(): string {
    return this.crypto.publicKeyBase64;
  }

  /**
   * Record a facto event.
   *
   * @param options - Options for the event
   * @returns The facto_id of the recorded event
   */
  async record(options: RecordOptions): Promise<string> {
    const factoId = generateFactoId();
    const now = currentTimeNs();

    // Merge tags
    const tags = { ...this.config.tags, ...options.executionMeta?.tags };

    const executionMeta: ExecutionMeta = {
      modelId: options.executionMeta?.modelId,
      modelHash: options.executionMeta?.modelHash,
      temperature: options.executionMeta?.temperature,
      seed: options.executionMeta?.seed,
      maxTokens: options.executionMeta?.maxTokens,
      toolCalls: options.executionMeta?.toolCalls ?? [],
      sdkVersion: SDK_VERSION,
      sdkLanguage: SDK_LANGUAGE,
      tags,
    };

    // Build event for signing (wire format)
    const eventWire: FactoEventWire = {
      facto_id: factoId,
      agent_id: this.config.agentId,
      session_id: this.config.sessionId,
      parent_facto_id: options.parentFactoId ?? null,
      action_type: options.actionType,
      status: options.status ?? 'success',
      input_data: options.inputData,
      output_data: options.outputData,
      execution_meta: {
        model_id: executionMeta.modelId ?? null,
        model_hash: executionMeta.modelHash ?? null,
        temperature: executionMeta.temperature ?? null,
        seed: executionMeta.seed ?? null,
        max_tokens: executionMeta.maxTokens ?? null,
        tool_calls: executionMeta.toolCalls ?? [],
        sdk_version: executionMeta.sdkVersion,
        sdk_language: executionMeta.sdkLanguage,
        tags: executionMeta.tags,
      },
      proof: {
        signature: '',
        public_key: this.crypto.publicKeyBase64,
        prev_hash: this.crypto.prevHash,
        event_hash: '',
      },
      started_at: options.startedAt ?? now,
      completed_at: options.completedAt ?? now,
    };

    // Sign the event
    const [eventHash, signature] = await this.crypto.signEvent(eventWire);

    // Create the complete event
    const event: FactoEvent = {
      factoId,
      agentId: this.config.agentId,
      sessionId: this.config.sessionId,
      parentFactoId: options.parentFactoId,
      actionType: options.actionType,
      status: options.status ?? 'success',
      inputData: options.inputData,
      outputData: options.outputData,
      executionMeta,
      proof: {
        signature,
        publicKey: this.crypto.publicKeyBase64,
        prevHash: this.crypto.prevHash,
        eventHash,
      },
      startedAt: options.startedAt ?? now,
      completedAt: options.completedAt ?? now,
    };

    // Update prev_hash for chain linking
    this.crypto.updatePrevHash(eventHash);

    // Add to batch
    this.batch.push(event);
    if (this.batch.length >= this.config.batchSize) {
      await this.flush();
    }

    return factoId;
  }

  /**
   * Create a factod wrapper for a function.
   *
   * @param actionType - Type of action
   * @param fn - Function to wrap
   * @returns Wrapped function that records facto events
   */
  factod<T extends (...args: unknown[]) => unknown>(
    actionType: string,
    fn: T
  ): (...args: Parameters<T>) => Promise<ReturnType<T>> {
    return async (...args: Parameters<T>): Promise<ReturnType<T>> => {
      const startedAt = currentTimeNs();
      const inputData = { args };

      try {
        const result = await fn(...args);
        await this.record({
          actionType,
          inputData,
          outputData: { result },
          status: 'success',
          startedAt,
        });
        return result as ReturnType<T>;
      } catch (error) {
        await this.record({
          actionType,
          inputData,
          outputData: {
            error_type: error instanceof Error ? error.constructor.name : 'Error',
            error_message: error instanceof Error ? error.message : String(error),
          },
          status: 'error',
          startedAt,
        });
        throw error;
      }
    };
  }

  /**
   * Start a facto context for manual tracing.
   *
   * @param actionType - Type of action
   * @param inputData - Input data
   * @param parentFactoId - Optional parent facto ID
   * @returns FactoContext for setting output and status
   */
  startFacto(
    actionType: string,
    inputData: Record<string, unknown> = {},
    parentFactoId?: string
  ): FactoContext & { end: () => Promise<void> } {
    const factoId = generateFactoId();
    const startedAt = currentTimeNs();
    let output: unknown = {};
    let status = 'success';

    const context: FactoContext & { end: () => Promise<void> } = {
      factoId,
      setOutput(value: unknown): void {
        output = value;
      },
      setStatus(value: string): void {
        status = value;
      },
      setError(error: Error): void {
        status = 'error';
        output = {
          error_type: error.constructor.name,
          error_message: error.message,
        };
      },
      end: async (): Promise<void> => {
        const outputData =
          typeof output === 'object' && output !== null
            ? (output as Record<string, unknown>)
            : { result: output };

        await this.record({
          actionType,
          inputData,
          outputData,
          status,
          parentFactoId,
          startedAt,
        });
      },
    };

    return context;
  }

  /**
   * Flush the current batch of events.
   */
  async flush(): Promise<void> {
    if (this.batch.length === 0) {
      return;
    }

    const batch = this.batch;
    this.batch = [];

    try {
      await this.sendBatch(batch);
    } catch (error) {
      // On failure, add events back to batch
      this.batch = [...batch, ...this.batch];
      throw error;
    }
  }

  /**
   * Send a batch of events to the ingestion service.
   */
  private async sendBatch(events: FactoEvent[]): Promise<void> {
    if (events.length === 0) {
      return;
    }

    const payload: BatchIngestRequest = {
      events: events.map(toWireFormat),
    };

    for (let attempt = 0; attempt < this.config.maxRetries; attempt++) {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(
          () => controller.abort(),
          this.config.timeoutMs
        );

        const response = await fetch(`${this.config.endpoint}/v1/ingest/batch`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });

        clearTimeout(timeoutId);

        if (!response.ok) {
          if (response.status < 500) {
            // Don't retry client errors
            const errorText = await response.text();
            throw new Error(`Client error ${response.status}: ${errorText}`);
          }
          throw new Error(`Server error ${response.status}`);
        }

        const result: BatchIngestResponse = await response.json();
        if (result.rejected_count > 0) {
          console.warn(
            `${result.rejected_count} events rejected:`,
            result.rejected
          );
        }

        return;
      } catch (error) {
        if (attempt === this.config.maxRetries - 1) {
          throw error;
        }
        // Exponential backoff
        await new Promise((resolve) =>
          setTimeout(resolve, Math.pow(2, attempt) * 1000)
        );
      }
    }
  }

  /**
   * Close the client and flush remaining events.
   */
  async close(): Promise<void> {
    if (this.closed) {
      return;
    }

    this.closed = true;

    if (this.flushTimer) {
      clearInterval(this.flushTimer);
      this.flushTimer = null;
    }

    await this.flush();
  }
}
