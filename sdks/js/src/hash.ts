/**
 * Privacy Shield SDK — Hash helpers.
 *
 * Provides SHA-256 helpers for safely deriving stable identifiers from
 * sensitive material (e.g. raw API keys) without ever transmitting the
 * raw value over network paths that can land in access logs.
 *
 * Uses Web Crypto API (`crypto.subtle.digest`), available in both
 * Node.js 18+ (global `crypto`) and all modern browsers.
 */

/**
 * Compute the SHA-256 hex hash of an input string.
 *
 * Use this BEFORE passing a raw API key to `PrivacyShieldAdmin.revokeKey()`.
 * Passing the raw key directly would leak it into HTTP access logs (the key
 * appears as a URL path segment), Cloudflare/proxy logs, and browser history.
 *
 * @example
 * ```ts
 * import { PrivacyShieldAdmin, hashKey } from '@privacyshield/sdk';
 *
 * const admin = new PrivacyShieldAdmin({ adminKey: '...' });
 * const rawKey = 'ps_live_abc123...'; // from secrets manager
 * const keyHash = await hashKey(rawKey);
 * await admin.revokeKey(keyHash);  // safe: hash is opaque
 * ```
 *
 * @param input - The raw string to hash (e.g. a raw API key).
 * @returns Lowercase hex-encoded SHA-256 digest.
 */
export async function hashKey(input: string): Promise<string> {
  if (typeof input !== 'string' || input.length === 0) {
    throw new Error('hashKey: input must be a non-empty string');
  }
  const cryptoApi = (globalThis as { crypto?: Crypto }).crypto;
  if (!cryptoApi?.subtle) {
    throw new Error('hashKey: Web Crypto API not available in this runtime');
  }
  const buf = await cryptoApi.subtle.digest('SHA-256', new TextEncoder().encode(input));
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}
