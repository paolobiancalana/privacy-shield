/**
 * Privacy Shield SDK — Input/runtime validators.
 *
 * Shared between PrivacyShield and PrivacyShieldAdmin. Zero deps.
 */

/** Hard cap on HTTP response body size to prevent OOM via a compromised
 *  or misconfigured upstream. 1 MB is generous for the JSON payloads
 *  this SDK ever expects (largest is a tokenize batch of 100 strings). */
export const MAX_RESPONSE_SIZE = 1_048_576;

/** Validate baseUrl: must be a parsable URL with https: protocol.
 *  Returns the normalized origin (no trailing slash, no path). */
export function validateBaseUrl(input: string | undefined, fallback: string): string {
  const raw = input ?? fallback;
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error(`PrivacyShield: baseUrl is not a valid URL (got "${raw}")`);
  }
  if (parsed.protocol !== 'https:') {
    throw new Error(
      `PrivacyShield: baseUrl must use https:// (got "${parsed.protocol}")`,
    );
  }
  return parsed.origin;
}

/** Validate timeoutMs: must be a positive finite number.
 *  Rejects 0 (immediate abort), negative values, Infinity, NaN. */
export function validateTimeoutMs(input: number | undefined, fallback: number): number {
  const value = input ?? fallback;
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(
      `PrivacyShield: timeoutMs must be a positive finite number (got ${String(value)})`,
    );
  }
  return value;
}

/** Block construction in browser environments. Used by PrivacyShieldAdmin
 *  whose admin key must never be shipped to client-side JavaScript. */
export function assertNotBrowser(className: string): void {
  if (typeof window !== 'undefined' && typeof (window as { document?: unknown }).document !== 'undefined') {
    throw new Error(
      `${className} must not be used in browser environments — ` +
      `the admin key must remain server-side only`,
    );
  }
}

/** Parse JSON from a Response object with a size cap.
 *  Reads body as text first, validates byte length, then parses. */
export async function safeParseJson(response: Response, maxSize: number = MAX_RESPONSE_SIZE): Promise<unknown> {
  const text = await response.text();
  if (text.length > maxSize) {
    throw new Error(
      `PrivacyShield: response body exceeds ${maxSize} bytes (got ${text.length})`,
    );
  }
  if (text.length === 0) return {};
  try {
    return JSON.parse(text);
  } catch (err) {
    throw new Error(
      `PrivacyShield: response body is not valid JSON: ${err instanceof Error ? err.message : String(err)}`,
    );
  }
}
