/**
 * Privacy Shield SDK — Type definitions.
 *
 * All types match the runtime API contract exactly.
 * See docs/platform/02_API_CONTRACT.md for the full spec.
 */

/** PII entity type codes. */
export type PiiType =
  | 'pe'   // persona
  | 'org'  // organizzazione
  | 'loc'  // località
  | 'ind'  // indirizzo
  | 'med'  // medico
  | 'leg'  // legale
  | 'rel'  // relazione
  | 'fin'  // finanziario
  | 'pro'  // professione
  | 'dt'   // data nascita discorsiva
  | 'cf'   // codice fiscale (regex)
  | 'ib'   // IBAN (regex)
  | 'em'   // email (regex)
  | 'tel'; // telefono (regex)

/** Detection source. */
export type DetectionSource = 'regex' | 'slm' | 'composite';

/** A single detected/tokenized PII entity. */
export interface TokenEntry {
  /** Opaque token string, e.g. "[#pe:6542b3dc]" */
  token: string;
  /** Original plaintext PII value. */
  original: string;
  /** PII type code. */
  type: PiiType;
  /** Inclusive start offset in original text. */
  start: number;
  /** Exclusive end offset in original text. */
  end: number;
  /** Detection source. */
  source: DetectionSource;
}

/** Tokenize request body. */
export interface TokenizeRequest {
  /** One or more texts to tokenize (max 100). */
  texts: string[];
  /** UUID of the processing organization. */
  organizationId: string;
  /** UUID identifying this request (for flush). */
  requestId: string;
  /** Carry-over map: pii_value → token from previous turns. */
  existingTokens?: Record<string, string>;
}

/** Tokenize response. */
export interface TokenizeResponse {
  /** Tokenized texts with PII replaced by opaque tokens. */
  tokenizedTexts: string[];
  /** All token entries created. */
  tokens: TokenEntry[];
  /** Detection time in ms. */
  detectionMs: number;
  /** Total tokenization time in ms. */
  tokenizationMs: number;
}

/** Rehydrate request body. */
export interface RehydrateRequest {
  /** Text containing opaque tokens to restore. */
  text: string;
  /** UUID of the processing organization. */
  organizationId: string;
  /** UUID of the original request (must match tokenize request). */
  requestId: string;
}

/** Rehydrate response. */
export interface RehydrateResponse {
  /** Text with tokens replaced by original PII values. */
  text: string;
  /** Number of tokens successfully rehydrated. */
  rehydratedCount: number;
}

/** Flush request body. */
export interface FlushRequest {
  /** UUID of the processing organization. */
  organizationId: string;
  /** UUID of the request to flush. */
  requestId: string;
}

/** Flush response. */
export interface FlushResponse {
  /** Number of vault entries deleted. */
  flushedCount: number;
}

/** Health check response. */
export interface HealthResponse {
  status: 'healthy' | 'degraded' | 'unhealthy';
  components: Record<string, { status: string; latency_ms?: number }>;
  version: string;
}

/** SDK configuration. */
export interface PrivacyShieldConfig {
  /** API key (e.g. "ps_live_xxx"). */
  apiKey: string;
  /** Base URL of the PS runtime API. Default: "https://api.privacyshield.pro" */
  baseUrl?: string;
  /** Request timeout in ms. Default: 5000. */
  timeoutMs?: number;
  /**
   * mTLS client certificate (PEM string or Buffer).
   * Required when connecting to mTLS-protected endpoints.
   * Node.js only — not available in browsers.
   */
  clientCert?: string | Buffer;
  /** mTLS client private key (PEM string or Buffer). Node.js only. */
  clientKey?: string | Buffer;
  /** CA certificate for server verification (PEM string or Buffer). Node.js only. */
  caCert?: string | Buffer;
}

/** Error from the PS API. */
export interface PrivacyShieldError {
  error: string;
  code: string;
  detail: string | null;
}
