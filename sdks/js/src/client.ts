/**
 * Privacy Shield SDK — HTTP Client.
 *
 * Handles all communication with the PS runtime API, including
 * mTLS for Node.js environments and standard HTTPS for browsers.
 *
 * Zero dependencies — uses native fetch (Node.js 18+) or browser fetch.
 * For mTLS: falls back to node:https when client certificates are configured.
 */

import type {
  FlushRequest,
  FlushResponse,
  HealthResponse,
  MetricsCallback,
  PrivacyShieldConfig,
  PrivacyShieldError,
  RehydrateRequest,
  RehydrateResponse,
  TokenizeRequest,
  TokenizeResponse,
} from './types.js';

const DEFAULT_BASE_URL = 'https://api.privacyshield.pro';
const DEFAULT_TIMEOUT_MS = 5_000;

/** Error thrown by the SDK on API errors. */
export class PrivacyShieldApiError extends Error {
  readonly statusCode: number;
  readonly code: string;
  readonly detail: string | null;

  constructor(statusCode: number, body: PrivacyShieldError) {
    super(body.error);
    this.name = 'PrivacyShieldApiError';
    this.statusCode = statusCode;
    this.code = body.code;
    this.detail = body.detail;
  }
}

/**
 * Privacy Shield client.
 *
 * Usage:
 * ```ts
 * import { PrivacyShield } from '@privacyshield/sdk';
 *
 * const ps = new PrivacyShield({ apiKey: 'ps_live_xxx' });
 *
 * const result = await ps.tokenize({
 *   texts: ['Mario Rossi, CF RSSMRA85M01H501Z'],
 *   organizationId: 'uuid',
 *   requestId: 'uuid',
 * });
 * ```
 */
export class PrivacyShield {
  private readonly apiKey: string;
  private readonly baseUrl: string;
  private readonly timeoutMs: number;
  private readonly clientCert?: string | Buffer;
  private readonly clientKey?: string | Buffer;
  private readonly caCert?: string | Buffer;
  private readonly metrics?: MetricsCallback;
  private httpsAgent: unknown | null = null;

  constructor(config: PrivacyShieldConfig) {
    if (!config.apiKey) {
      throw new Error('PrivacyShield: apiKey is required');
    }

    this.apiKey = config.apiKey;
    this.baseUrl = (config.baseUrl ?? DEFAULT_BASE_URL).replace(/\/$/, '');
    this.timeoutMs = config.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.clientCert = config.clientCert;
    this.clientKey = config.clientKey;
    this.caCert = config.caCert;
    this.metrics = config.metrics;
  }

  // ── Public API ──────────────────────────────────────────────────

  /**
   * Detect PII in one or more texts and replace with opaque tokens.
   *
   * The returned tokens are stored encrypted in the PS vault with TTL.
   * Use `rehydrate()` to restore original values, and `flush()` to delete.
   */
  async tokenize(request: TokenizeRequest): Promise<TokenizeResponse> {
    const t0 = performance.now();
    try {
      const body = {
        texts: request.texts,
        organization_id: request.organizationId,
        request_id: request.requestId,
        existing_tokens: request.existingTokens ?? {},
      };

      const raw = await this.post('/api/v1/tokenize', body);

      const result: TokenizeResponse = {
        tokenizedTexts: raw.tokenized_texts as string[],
        tokens: (raw.tokens as Array<Record<string, unknown>>).map((t) => ({
          token: t.token as string,
          original: t.original as string,
          type: t.type as TokenizeResponse['tokens'][0]['type'],
          start: t.start as number,
          end: t.end as number,
          source: t.source as TokenizeResponse['tokens'][0]['source'],
        })),
        detectionMs: raw.detection_ms as number,
        tokenizationMs: raw.tokenization_ms as number,
      };
      this.emitMetric('tokenize', t0, 200);
      return result;
    } catch (err) {
      const statusCode = err instanceof PrivacyShieldApiError ? err.statusCode : 0;
      this.emitMetric('tokenize', t0, statusCode, err instanceof Error ? err.message : String(err));
      throw err;
    }
  }

  /**
   * Restore original PII values from opaque tokens.
   *
   * The request_id must match the one used in tokenize().
   * After flush(), rehydration returns tokens unchanged.
   */
  async rehydrate(request: RehydrateRequest): Promise<RehydrateResponse> {
    const t0 = performance.now();
    try {
      const body = {
        text: request.text,
        organization_id: request.organizationId,
        request_id: request.requestId,
      };

      const raw = await this.post('/api/v1/rehydrate', body);

      const result: RehydrateResponse = {
        text: raw.text as string,
        rehydratedCount: raw.rehydrated_count as number,
      };
      this.emitMetric('rehydrate', t0, 200);
      return result;
    } catch (err) {
      const statusCode = err instanceof PrivacyShieldApiError ? err.statusCode : 0;
      this.emitMetric('rehydrate', t0, statusCode, err instanceof Error ? err.message : String(err));
      throw err;
    }
  }

  /**
   * Delete all vault entries for a request.
   *
   * After flush, tokens become permanently unresolvable.
   * This is the normal cleanup step after a conversation turn.
   */
  async flush(request: FlushRequest): Promise<FlushResponse> {
    const t0 = performance.now();
    try {
      const body = {
        organization_id: request.organizationId,
        request_id: request.requestId,
      };

      const raw = await this.post('/api/v1/flush', body);

      const result: FlushResponse = {
        flushedCount: raw.flushed_count as number,
      };
      this.emitMetric('flush', t0, 200);
      return result;
    } catch (err) {
      const statusCode = err instanceof PrivacyShieldApiError ? err.statusCode : 0;
      this.emitMetric('flush', t0, statusCode, err instanceof Error ? err.message : String(err));
      throw err;
    }
  }

  /** Check service health. Does not require API key. */
  async health(): Promise<HealthResponse> {
    const t0 = performance.now();
    try {
      const raw = await this.get('/health');
      const result = raw as unknown as HealthResponse;
      this.emitMetric('health', t0, 200);
      return result;
    } catch (err) {
      const statusCode = err instanceof PrivacyShieldApiError ? err.statusCode : 0;
      this.emitMetric('health', t0, statusCode, err instanceof Error ? err.message : String(err));
      throw err;
    }
  }

  // ── Telemetry helper ────────────────────────────────────────────

  private emitMetric(operation: string, t0: number, statusCode: number, error?: string): void {
    try {
      this.metrics?.onRequest({
        operation,
        durationMs: performance.now() - t0,
        statusCode,
        error,
      });
    } catch {
      // Telemetry must never break the caller
    }
  }

  // ── HTTP internals ──────────────────────────────────────────────

  private async post(
    path: string,
    body: unknown,
  ): Promise<Record<string, unknown>> {
    const url = `${this.baseUrl}${path}`;
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-Api-Key': this.apiKey,
    };

    // mTLS: use node:https when certificates are configured
    if (this.clientCert && this.clientKey && url.startsWith('https://')) {
      return this.postWithMtls(url, body, headers);
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers,
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      if (!response.ok) {
        await this.handleError(response);
      }

      return (await response.json()) as Record<string, unknown>;
    } finally {
      clearTimeout(timer);
    }
  }

  private async get(path: string): Promise<Record<string, unknown>> {
    const url = `${this.baseUrl}${path}`;
    const headers: Record<string, string> = {};
    if (this.apiKey) {
      headers['X-Api-Key'] = this.apiKey;
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const response = await fetch(url, {
        method: 'GET',
        headers,
        signal: controller.signal,
      });

      if (!response.ok) {
        await this.handleError(response);
      }

      return (await response.json()) as Record<string, unknown>;
    } finally {
      clearTimeout(timer);
    }
  }

  private async handleError(response: Response): Promise<never> {
    let body: PrivacyShieldError;
    try {
      body = (await response.json()) as PrivacyShieldError;
    } catch {
      body = {
        error: `HTTP ${response.status}: ${response.statusText}`,
        code: 'UNKNOWN',
        detail: null,
      };
    }
    throw new PrivacyShieldApiError(response.status, body);
  }

  /**
   * HTTPS POST with mTLS client certificates (Node.js only).
   * Uses node:https.Agent for TLS client authentication.
   */
  private async postWithMtls(
    url: string,
    body: unknown,
    headers: Record<string, string>,
  ): Promise<Record<string, unknown>> {
    // Dynamic import for ESM compatibility (no require in ESM)
    const https = await import('node:https');
    const { URL } = await import('node:url');

    if (!this.httpsAgent) {
      const agentOptions: Record<string, unknown> = {
        cert: this.clientCert,
        key: this.clientKey,
        rejectUnauthorized: true,
        keepAlive: true,
      };
      // Only set ca if provided — otherwise use system CAs (e.g. Let's Encrypt)
      if (this.caCert) {
        agentOptions.ca = this.caCert;
      }
      this.httpsAgent = new https.Agent(agentOptions);
    }

    return new Promise((resolve, reject) => {
      const parsed = new URL(url);
      const jsonBody = JSON.stringify(body);
      const timer = setTimeout(() => {
        req.destroy(new Error('Timeout'));
      }, this.timeoutMs);

      const req = https.request(
        {
          hostname: parsed.hostname,
          port: parsed.port || 443,
          path: parsed.pathname + parsed.search,
          method: 'POST',
          headers: {
            ...headers,
            'Content-Length': Buffer.byteLength(jsonBody).toString(),
          },
          agent: this.httpsAgent as import('node:https').Agent,
        },
        (res) => {
          let data = '';
          res.on('data', (chunk: string) => (data += chunk));
          res.on('end', () => {
            clearTimeout(timer);
            if (res.statusCode && res.statusCode >= 400) {
              try {
                const errorBody = JSON.parse(data) as PrivacyShieldError;
                reject(
                  new PrivacyShieldApiError(res.statusCode, errorBody),
                );
              } catch {
                reject(
                  new PrivacyShieldApiError(res.statusCode, {
                    error: `HTTP ${res.statusCode}`,
                    code: 'UNKNOWN',
                    detail: data,
                  }),
                );
              }
              return;
            }
            try {
              resolve(JSON.parse(data) as Record<string, unknown>);
            } catch {
              reject(new Error('Invalid JSON from Privacy Shield'));
            }
          });
        },
      );

      req.on('error', (err) => {
        clearTimeout(timer);
        reject(err);
      });

      req.write(jsonBody);
      req.end();
    });
  }
}
