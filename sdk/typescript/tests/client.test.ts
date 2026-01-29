/**
 * Tests for the Facto SDK client.
 */

import { describe, it, expect } from 'vitest';
import {
  FactoClient,
  CryptoProvider,
  generateKeypair,
  verifyEvent,
  generateFactoId,
  generateSessionId,
  toWireFormat,
  type FactoEventWire,
} from '../src';

describe('CryptoProvider', () => {
  it('should generate a keypair', () => {
    const [privateKey, publicKey] = generateKeypair();
    expect(privateKey.length).toBe(32);
    expect(publicKey.length).toBe(32);
  });

  it('should initialize with generated key', () => {
    const crypto = new CryptoProvider();
    expect(crypto.publicKey.length).toBe(32);
    expect(crypto.publicKeyBase64.length).toBeGreaterThan(0);
  });

  it('should initialize with existing key', () => {
    const [privateKey, publicKey] = generateKeypair();
    const crypto = new CryptoProvider(privateKey);
    expect(crypto.publicKey).toEqual(publicKey);
  });

  it('should start with prev_hash of 64 zeros', () => {
    const crypto = new CryptoProvider();
    expect(crypto.prevHash).toBe('0'.repeat(64));
  });

  it('should compute SHA3-256 hash', () => {
    const crypto = new CryptoProvider();
    const hash = crypto.computeHash('{"test":"data"}');
    expect(hash.length).toBe(64);
  });

  it('should sign and verify', async () => {
    const crypto = new CryptoProvider();
    const message = new TextEncoder().encode('test message');
    const signature = await crypto.sign(message);
    expect(signature.length).toBe(64);

    const isValid = await crypto.verify(message, signature, crypto.publicKey);
    expect(isValid).toBe(true);
  });

  it('should build canonical form', () => {
    const crypto = new CryptoProvider();
    const event: FactoEventWire = {
      facto_id: 'ft-test',
      agent_id: 'agent-test',
      session_id: 'session-test',
      parent_facto_id: null,
      action_type: 'test',
      status: 'success',
      input_data: { key: 'value' },
      output_data: { result: 'ok' },
      execution_meta: {
        model_id: 'gpt-4',
        model_hash: null,
        temperature: 0.7,
        seed: null,
        max_tokens: null,
        tool_calls: [],
        sdk_version: '0.1.0',
        sdk_language: 'typescript',
        tags: {},
      },
      proof: {
        signature: '',
        public_key: '',
        prev_hash: '0'.repeat(64),
        event_hash: '',
      },
      started_at: 1000000000,
      completed_at: 1000000001,
    };

    const canonical = crypto.buildCanonicalForm(event);
    expect(canonical).toContain('action_type');
    expect(canonical).toContain('agent_id');
  });

  it('should sign event', async () => {
    const crypto = new CryptoProvider();
    const event: FactoEventWire = {
      facto_id: 'ft-test',
      agent_id: 'agent-test',
      session_id: 'session-test',
      parent_facto_id: null,
      action_type: 'test',
      status: 'success',
      input_data: {},
      output_data: {},
      execution_meta: {
        model_id: null,
        model_hash: null,
        temperature: null,
        seed: null,
        max_tokens: null,
        tool_calls: [],
        sdk_version: '0.1.0',
        sdk_language: 'typescript',
        tags: {},
      },
      proof: {
        signature: '',
        public_key: '',
        prev_hash: '0'.repeat(64),
        event_hash: '',
      },
      started_at: 1000000000,
      completed_at: 1000000001,
    };

    const [eventHash, signature] = await crypto.signEvent(event);
    expect(eventHash.length).toBe(64);
    expect(signature.length).toBeGreaterThan(0);
  });
});

describe('Utility functions', () => {
  it('should generate facto IDs', () => {
    const factoId = generateFactoId();
    expect(factoId).toMatch(/^ft-[a-f0-9-]+$/);
  });

  it('should generate session IDs', () => {
    const sessionId = generateSessionId();
    expect(sessionId).toMatch(/^session-[a-f0-9]+$/);
  });
});

describe('verifyEvent', () => {
  it('should verify valid event', async () => {
    const crypto = new CryptoProvider();
    const event: FactoEventWire = {
      facto_id: 'ft-test',
      agent_id: 'agent-test',
      session_id: 'session-test',
      parent_facto_id: null,
      action_type: 'test',
      status: 'success',
      input_data: {},
      output_data: {},
      execution_meta: {
        model_id: null,
        model_hash: null,
        temperature: null,
        seed: null,
        max_tokens: null,
        tool_calls: [],
        sdk_version: '0.1.0',
        sdk_language: 'typescript',
        tags: {},
      },
      proof: {
        signature: '',
        public_key: crypto.publicKeyBase64,
        prev_hash: '0'.repeat(64),
        event_hash: '',
      },
      started_at: 1000000000,
      completed_at: 1000000001,
    };

    const [eventHash, signature] = await crypto.signEvent(event);
    event.proof.event_hash = eventHash;
    event.proof.signature = signature;

    const [hashValid, sigValid] = await verifyEvent(event);
    expect(hashValid).toBe(true);
    expect(sigValid).toBe(true);
  });

  it('should detect tampered event', async () => {
    const crypto = new CryptoProvider();
    const event: FactoEventWire = {
      facto_id: 'ft-test',
      agent_id: 'agent-test',
      session_id: 'session-test',
      parent_facto_id: null,
      action_type: 'test',
      status: 'success',
      input_data: {},
      output_data: {},
      execution_meta: {
        model_id: null,
        model_hash: null,
        temperature: null,
        seed: null,
        max_tokens: null,
        tool_calls: [],
        sdk_version: '0.1.0',
        sdk_language: 'typescript',
        tags: {},
      },
      proof: {
        signature: '',
        public_key: crypto.publicKeyBase64,
        prev_hash: '0'.repeat(64),
        event_hash: '',
      },
      started_at: 1000000000,
      completed_at: 1000000001,
    };

    const [eventHash, signature] = await crypto.signEvent(event);
    event.proof.event_hash = eventHash;
    event.proof.signature = signature;

    // Tamper with the event
    event.status = 'error';

    const [hashValid, sigValid] = await verifyEvent(event);
    expect(hashValid).toBe(false);
    expect(sigValid).toBe(false);
  });
});

describe('FactoClient', () => {
  it('should initialize with config', () => {
    const client = new FactoClient({
      endpoint: 'http://localhost:8080',
      agentId: 'test-agent',
    });

    expect(client.sessionId).toBeDefined();
    expect(client.publicKey).toBeDefined();

    // Clean up
    client.close();
  });

  it('should record events', async () => {
    const client = new FactoClient({
      endpoint: 'http://localhost:8080',
      agentId: 'test-agent',
    });

    const factoId = await client.record({
      actionType: 'test',
      inputData: { key: 'value' },
      outputData: { result: 'ok' },
    });

    expect(factoId).toMatch(/^ft-/);

    await client.close();
  });

  it('should create factod wrapper', async () => {
    const client = new FactoClient({
      endpoint: 'http://localhost:8080',
      agentId: 'test-agent',
    });

    const factodFn = client.factod('test', async (x: number) => x * 2);
    const result = await factodFn(5);

    expect(result).toBe(10);

    await client.close();
  });

  it('should handle startFacto context', async () => {
    const client = new FactoClient({
      endpoint: 'http://localhost:8080',
      agentId: 'test-agent',
    });

    const ctx = client.startFacto('test', { input: 'data' });
    expect(ctx.factoId).toMatch(/^ft-/);

    ctx.setOutput({ result: 'ok' });
    await ctx.end();

    await client.close();
  });
});
