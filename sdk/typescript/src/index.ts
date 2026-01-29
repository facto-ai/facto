/**
 * Facto SDK - Forensic Accountability Infrastructure for AI Agents
 *
 * This SDK provides tools for capturing and signing facto events from AI agents,
 * creating tamper-proof audit trails for compliance and debugging.
 *
 * @example
 * ```typescript
 * import { FactoClient } from '@facto-ai/sdk';
 *
 * const client = new FactoClient({
 *   endpoint: 'http://localhost:8080',
 *   agentId: 'my-agent',
 * });
 *
 * // Using factod wrapper
 * const factodLLMCall = client.factod('llm_call', async (prompt: string) => {
 *   return await openai.chat.completions.create({ ... });
 * });
 * const result = await factodLLMCall("Hello");
 *
 * // Manual recording
 * await client.record({
 *   actionType: 'tool_use',
 *   inputData: { tool: 'search', query: 'AI news' },
 *   outputData: { results: [...] },
 * });
 *
 * await client.close();
 * ```
 *
 * @packageDocumentation
 */

// Client
export { FactoClient } from './client';

// Models
export {
  type FactoConfig,
  type FactoEvent,
  type FactoEventWire,
  type ExecutionMeta,
  type Proof,
  type RecordOptions,
  type FactoContext,
  type BatchIngestRequest,
  type BatchIngestResponse,
  generateFactoId,
  generateSessionId,
  currentTimeNs,
  toWireFormat,
} from './models';

// Crypto
export {
  CryptoProvider,
  generateKeypair,
  verifyEvent,
  toBase64,
  fromBase64,
} from './crypto';
