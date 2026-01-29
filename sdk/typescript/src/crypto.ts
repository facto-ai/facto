/**
 * Cryptographic utilities for the Facto SDK.
 */

import * as ed25519 from '@noble/ed25519';
import { sha3_256 } from '@noble/hashes/sha3';
import { bytesToHex, hexToBytes } from '@noble/hashes/utils';
import type { FactoEventWire } from './models';

// Enable synchronous methods for ed25519
// @ts-ignore - This is needed for synchronous signing
ed25519.etc.sha512Sync = (...m: Uint8Array[]) => {
  const h = sha3_256.create();
  m.forEach((b) => h.update(b));
  // Use SHA-512 from Web Crypto API synchronously via a workaround
  // For production, you'd want to use the async version
  return new Uint8Array(64); // Placeholder - see note below
};

/**
 * Convert Uint8Array to base64 string.
 */
export function toBase64(bytes: Uint8Array): string {
  if (typeof Buffer !== 'undefined') {
    return Buffer.from(bytes).toString('base64');
  }
  return btoa(String.fromCharCode(...bytes));
}

/**
 * Convert base64 string to Uint8Array.
 */
export function fromBase64(base64: string): Uint8Array {
  if (typeof Buffer !== 'undefined') {
    return new Uint8Array(Buffer.from(base64, 'base64'));
  }
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

/**
 * Handles cryptographic operations for event signing and verification.
 */
export class CryptoProvider {
  private privateKey: Uint8Array;
  private _publicKey: Uint8Array;
  private _prevHash: string = '0'.repeat(64);

  /**
   * Create a new CryptoProvider.
   *
   * @param privateKey - Ed25519 private key (32 bytes). If not provided, generates a new keypair.
   */
  constructor(privateKey?: Uint8Array) {
    if (privateKey) {
      if (privateKey.length !== 32) {
        throw new Error('Private key must be 32 bytes');
      }
      this.privateKey = privateKey;
      this._publicKey = ed25519.getPublicKey(privateKey);
    } else {
      this.privateKey = ed25519.utils.randomPrivateKey();
      this._publicKey = ed25519.getPublicKey(this.privateKey);
    }
  }

  /**
   * Get the public key as Uint8Array.
   */
  get publicKey(): Uint8Array {
    return this._publicKey;
  }

  /**
   * Get the public key as base64 string.
   */
  get publicKeyBase64(): string {
    return toBase64(this._publicKey);
  }

  /**
   * Get the current prev_hash for chain linking.
   */
  get prevHash(): string {
    return this._prevHash;
  }

  /**
   * Update the prev_hash after successfully sending an event.
   */
  updatePrevHash(eventHash: string): void {
    this._prevHash = eventHash;
  }

  /**
   * Build the canonical JSON form for hashing/signing.
   */
  buildCanonicalForm(event: FactoEventWire): string {
    // Build the canonical structure with sorted keys
    const canonical: Record<string, unknown> = {};

    canonical['action_type'] = event.action_type;
    canonical['agent_id'] = event.agent_id;
    canonical['completed_at'] = event.completed_at;

    // Build execution_meta in sorted order
    const execMeta: Record<string, unknown> = {};
    if (event.execution_meta.model_id !== null) {
      execMeta['model_id'] = event.execution_meta.model_id;
    }
    execMeta['seed'] = event.execution_meta.seed;
    execMeta['sdk_version'] = event.execution_meta.sdk_version;
    if (event.execution_meta.temperature !== null) {
      execMeta['temperature'] = event.execution_meta.temperature;
    }
    execMeta['tool_calls'] = event.execution_meta.tool_calls;
    canonical['execution_meta'] = execMeta;

    canonical['input_data'] = event.input_data;
    canonical['output_data'] = event.output_data;
    canonical['parent_facto_id'] = event.parent_facto_id;
    canonical['prev_hash'] = event.proof.prev_hash;
    canonical['session_id'] = event.session_id;
    canonical['started_at'] = event.started_at;
    canonical['status'] = event.status;
    canonical['facto_id'] = event.facto_id;

    return JSON.stringify(canonical, Object.keys(canonical).sort());
  }

  /**
   * Compute SHA3-256 hash of the canonical form.
   */
  computeHash(canonical: string): string {
    const hash = sha3_256(new TextEncoder().encode(canonical));
    return bytesToHex(hash);
  }

  /**
   * Sign a message with the private key.
   */
  async sign(message: Uint8Array): Promise<Uint8Array> {
    return await ed25519.signAsync(message, this.privateKey);
  }

  /**
   * Sign a message and return base64-encoded signature.
   */
  async signBase64(message: Uint8Array): Promise<string> {
    const signature = await this.sign(message);
    return toBase64(signature);
  }

  /**
   * Verify a signature.
   */
  async verify(
    message: Uint8Array,
    signature: Uint8Array,
    publicKey: Uint8Array
  ): Promise<boolean> {
    try {
      return await ed25519.verifyAsync(signature, message, publicKey);
    } catch {
      return false;
    }
  }

  /**
   * Sign an event and compute its hash.
   *
   * @param event - Event in wire format with proof.prev_hash set
   * @returns Tuple of [eventHash, signatureBase64]
   */
  async signEvent(event: FactoEventWire): Promise<[string, string]> {
    const canonical = this.buildCanonicalForm(event);
    const eventHash = this.computeHash(canonical);
    const signature = await this.signBase64(new TextEncoder().encode(canonical));
    return [eventHash, signature];
  }
}

/**
 * Generate a new Ed25519 keypair.
 *
 * @returns Tuple of [privateKey, publicKey], both 32 bytes
 */
export function generateKeypair(): [Uint8Array, Uint8Array] {
  const privateKey = ed25519.utils.randomPrivateKey();
  const publicKey = ed25519.getPublicKey(privateKey);
  return [privateKey, publicKey];
}

/**
 * Verify an event's hash and signature.
 *
 * @param event - The event in wire format with proof
 * @returns Tuple of [hashValid, signatureValid]
 */
export async function verifyEvent(
  event: FactoEventWire
): Promise<[boolean, boolean]> {
  const crypto = new CryptoProvider();

  // Build canonical form
  const canonical = crypto.buildCanonicalForm(event);

  // Verify hash
  const computedHash = crypto.computeHash(canonical);
  const hashValid = computedHash === event.proof.event_hash;

  // Verify signature
  let signatureValid = false;
  try {
    const publicKey = fromBase64(event.proof.public_key);
    const signature = fromBase64(event.proof.signature);
    signatureValid = await crypto.verify(
      new TextEncoder().encode(canonical),
      signature,
      publicKey
    );
  } catch {
    signatureValid = false;
  }

  return [hashValid, signatureValid];
}
