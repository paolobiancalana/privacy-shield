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

/** Callback interface for client-side telemetry. */
export interface MetricsCallback {
  /** Called after each HTTP request completes (success or failure). */
  onRequest(metric: {
    /** Operation name: 'tokenize', 'rehydrate', 'flush', or 'health'. */
    operation: string;
    /** Request duration in milliseconds. */
    durationMs: number;
    /** HTTP status code (0 if network error). */
    statusCode: number;
    /** Error message if request failed. */
    error?: string;
  }): void;
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
  /** Optional metrics callback for client-side telemetry. */
  metrics?: MetricsCallback;
}

/** Error from the PS API. */
export interface PrivacyShieldError {
  error: string;
  code: string;
  detail: string | null;
}

// ── Admin SDK types ─────────────────────────────────────────────────────────

/** Admin SDK configuration. */
export interface PrivacyShieldAdminConfig {
  /** Admin API key (X-Admin-Key). */
  adminKey: string;
  /** Base URL of the PS runtime API. Default: "https://api.privacyshield.pro" */
  baseUrl?: string;
  /** Request timeout in ms. Default: 5000. */
  timeoutMs?: number;
}

/**
 * Result of a provision() call.
 *
 * When created=true, key contains the raw API key (shown once only).
 * When created=false, the org was already provisioned; key is an empty string.
 */
export interface ProvisionResult {
  /** Plan ID assigned to the organization. */
  plan: string;
  /**
   * Raw API key — present only when created=true.
   * Empty string on subsequent calls; the key cannot be recovered after first issuance.
   */
  key: string;
  /** Stable key identifier (use for revocation). */
  keyId: string;
  /** True if a new key was created; false if the org was already provisioned. */
  created: boolean;
  /** Organization ID that was provisioned. */
  organizationId: string;
  /** Key environment: "live" or "test". */
  environment: string;
}

/** Plan details returned by admin plan operations. */
export interface PlanInfo {
  /** Plan ID (e.g. "free", "starter", "pro"). */
  id: string;
  /** Human-readable plan name. */
  name: string;
  /** Maximum API calls per minute. */
  rateLimitPerMinute: number;
  /** Monthly token creation limit (-1 = unlimited). */
  monthlyTokenLimit: number;
  /** Maximum number of API keys per org. */
  maxKeys: number;
  /** Plan price in cents. */
  priceCents: number;
}

/** Result of a createKey() call. */
export interface KeyResult {
  /** Raw API key — shown once only; store it securely. */
  key: string;
  /** Stable key identifier (use for revocation). */
  keyId: string;
  /** Organization ID that owns this key. */
  organizationId: string;
}

/** Metadata for a single API key (no raw key material). */
export interface KeyInfo {
  /** Stable key identifier. */
  keyId: string;
  /** Organization ID that owns this key. */
  orgId: string;
  /** Plan ID at time of key creation. */
  plan: string;
  /** Maximum API calls per minute. */
  rateLimitPerMinute: number;
  /** Whether the key is currently active (not revoked). */
  active: boolean;
  /** Key environment: "live" or "test". */
  environment: string;
  /** ISO 8601 creation timestamp. */
  createdAt: string;
}

/** Combined plan, usage, and key summary for an organization. */
export interface OrgPlanInfo {
  /** Full plan details for the org's current plan. */
  plan: PlanInfo;
  /** Monthly usage counters for the current calendar month. */
  usage: {
    month: string;
    tokenizeCalls: number;
    rehydrateCalls: number;
    flushCalls: number;
    totalTokensCreated: number;
  };
  /** Number of currently active (non-revoked) keys. */
  activeKeys: number;
  /** Maximum keys allowed by the current plan. */
  maxKeys: number;
}
