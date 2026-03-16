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
  }

  // ── Public API ──────────────────────────────────────────────────

  /**
   * Detect PII in one or more texts and replace with opaque tokens.
   *
   * The returned tokens are stored encrypted in the PS vault with TTL.
   * Use `rehydrate()` to restore original values, and `flush()` to delete.
   */
  async tokenize(request: TokenizeRequest): Promise<TokenizeResponse> {
    const body = {
      texts: request.texts,
      organization_id: request.organizationId,
      request_id: request.requestId,
      existing_tokens: request.existingTokens ?? {},
    };

    const raw = await this.post('/api/v1/tokenize', body);

    return {
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
  }

  /**
   * Restore original PII values from opaque tokens.
   *
   * The request_id must match the one used in tokenize().
   * After flush(), rehydration returns tokens unchanged.
   */
  async rehydrate(request: RehydrateRequest): Promise<RehydrateResponse> {
    const body = {
      text: request.text,
      organization_id: request.organizationId,
      request_id: request.requestId,
    };

    const raw = await this.post('/api/v1/rehydrate', body);

    return {
      text: raw.text as string,
      rehydratedCount: raw.rehydrated_count as number,
    };
  }

  /**
   * Delete all vault entries for a request.
   *
   * After flush, tokens become permanently unresolvable.
   * This is the normal cleanup step after a conversation turn.
   */
  async flush(request: FlushRequest): Promise<FlushResponse> {
    const body = {
      organization_id: request.organizationId,
      request_id: request.requestId,
    };

    const raw = await this.post('/api/v1/flush', body);

    return {
      flushedCount: raw.flushed_count as number,
    };
  }

  /** Check service health. Does not require API key. */
  async health(): Promise<HealthResponse> {
    const raw = await this.get('/health');
    return raw as unknown as HealthResponse;
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
  private postWithMtls(
    url: string,
    body: unknown,
    headers: Record<string, string>,
  ): Promise<Record<string, unknown>> {
    // Dynamic import to keep browser compatibility
    const https = require('node:https') as typeof import('node:https');
    const { URL } = require('node:url') as typeof import('node:url');

    if (!this.httpsAgent) {
      this.httpsAgent = new https.Agent({
        cert: this.clientCert,
        key: this.clientKey,
        ca: this.caCert,
        rejectUnauthorized: true,
        keepAlive: true,
      });
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
