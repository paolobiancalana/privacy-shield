/**
 * Privacy Shield Admin SDK.
 *
 * Provides privileged operations for managing organizations, plans, and API
 * keys. All methods use the X-Admin-Key header and require an admin API key.
 *
 * Zero dependencies — uses native fetch (Node.js 18+) or browser fetch.
 * ESM only.
 *
 * @example
 * ```ts
 * import { PrivacyShieldAdmin } from '@privacyshield/sdk';
 *
 * const admin = new PrivacyShieldAdmin({ adminKey: 'my-admin-secret' });
 *
 * // First-time setup for a new tenant:
 * const { key, keyId, created } = await admin.provision('org-uuid', 'starter');
 * if (created) {
 *   console.log('New key (store securely):', key);
 * } else {
 *   console.log('Already provisioned, existing key ID:', keyId);
 * }
 * ```
 */

import type {
  KeyInfo,
  KeyResult,
  OrgPlanInfo,
  PlanInfo,
  PrivacyShieldAdminConfig,
  PrivacyShieldError,
  ProvisionResult,
} from './types.js';
import { PrivacyShieldApiError } from './client.js';
import {
  assertNotBrowser,
  safeParseJson,
  validateBaseUrl,
  validateTimeoutMs,
} from './validators.js';

const DEFAULT_BASE_URL = 'https://api.privacyshield.pro';
const DEFAULT_TIMEOUT_MS = 5_000;

/**
 * Privacy Shield Admin client.
 *
 * Privileged counterpart to `PrivacyShield`. Uses `X-Admin-Key` for all
 * requests. Never use this client in browser environments — the admin key
 * must remain server-side only.
 */
export class PrivacyShieldAdmin {
  private readonly adminKey: string;
  private readonly baseUrl: string;
  private readonly timeoutMs: number;

  constructor(config: PrivacyShieldAdminConfig) {
    assertNotBrowser('PrivacyShieldAdmin');
    if (!config.adminKey) {
      throw new Error('PrivacyShieldAdmin: adminKey is required');
    }
    this.adminKey = config.adminKey;
    this.baseUrl = validateBaseUrl(config.baseUrl, DEFAULT_BASE_URL);
    this.timeoutMs = validateTimeoutMs(config.timeoutMs, DEFAULT_TIMEOUT_MS);
  }

  // ── Public API ──────────────────────────────────────────────────────────

  /**
   * Provision an organization: assign a plan and create an API key.
   *
   * Idempotent: calling this method twice for the same (orgId, environment)
   * pair returns the existing key_id with created=false. The raw key is only
   * present in the response when created=true (first provision).
   *
   * @param orgId - UUID of the organization to provision.
   * @param planId - Plan to assign. Defaults to "free".
   * @param environment - Key environment: "live" or "test". Defaults to "live".
   */
  async provision(
    orgId: string,
    planId: string = 'free',
    environment: string = 'live',
  ): Promise<ProvisionResult> {
    const raw = await this.post('/api/v1/provision', {
      organization_id: orgId,
      plan_id: planId,
      environment,
    });
    return {
      plan: raw.plan as string,
      key: raw.key as string,
      keyId: raw.key_id as string,
      created: raw.created as boolean,
      organizationId: raw.organization_id as string,
      environment: raw.environment as string,
    };
  }

  /**
   * Change the plan for an organization.
   *
   * Returns the new plan details. Returns 409 if the org has more active keys
   * than the target plan allows — revoke excess keys first.
   *
   * @param orgId - UUID of the organization.
   * @param planId - Target plan ID (must exist in the plan catalog).
   */
  async setPlan(orgId: string, planId: string): Promise<PlanInfo> {
    const raw = await this.post(`/api/v1/org/${encodeURIComponent(orgId)}/plan`, {
      plan_id: planId,
    });
    const plan = raw.plan as Record<string, unknown>;
    return this.mapPlanInfo(plan);
  }

  /**
   * Create an additional API key for an organization.
   *
   * Returns 409 if the org has reached the plan's max_keys limit.
   *
   * @param orgId - UUID of the organization.
   * @param environment - Key environment: "live" or "test". Defaults to "live".
   */
  async createKey(orgId: string, environment: string = 'live'): Promise<KeyResult> {
    const raw = await this.post('/api/v1/keys', {
      organization_id: orgId,
      environment,
    });
    return {
      key: raw.key as string,
      keyId: raw.key_id as string,
      organizationId: raw.organization_id as string,
    };
  }

  /**
   * Revoke an API key by its SHA-256 hash.
   *
   * The key is deactivated but not deleted — its metadata is retained for
   * audit purposes. Returns 404 if the hash is not found.
   *
   * SECURITY: NEVER pass the raw API key to this method — the value is sent
   * as a URL path segment and would be captured by HTTP access logs, CDN
   * caches, and browser history. Always hash first:
   *
   * ```ts
   * import { hashKey } from '@privacyshield/sdk';
   * await admin.revokeKey(await hashKey(rawKey));
   * ```
   *
   * @param keyHash - SHA-256 hex hash of the raw API key to revoke.
   */
  async revokeKey(keyHash: string): Promise<void> {
    if (!/^[a-f0-9]{64}$/.test(keyHash)) {
      throw new Error(
        'PrivacyShieldAdmin.revokeKey: keyHash must be a 64-char lowercase hex SHA-256 digest. ' +
        'Use `hashKey(rawKey)` from @privacyshield/sdk to derive it — never pass the raw key.',
      );
    }
    await this.delete(`/api/v1/keys/${encodeURIComponent(keyHash)}`);
  }

  /**
   * List all API keys for an organization.
   *
   * Includes both active and revoked keys.
   *
   * @param orgId - UUID of the organization.
   */
  async listKeys(orgId: string): Promise<KeyInfo[]> {
    const raw = await this.get(`/api/v1/keys?org_id=${encodeURIComponent(orgId)}`);
    return (raw as unknown as Array<Record<string, unknown>>).map((k) => ({
      keyId: k.key_id as string,
      orgId: k.org_id as string,
      plan: k.plan as string,
      rateLimitPerMinute: k.rate_limit_per_minute as number,
      active: k.active as boolean,
      environment: k.environment as string,
      createdAt: k.created_at as string,
    }));
  }

  /**
   * Get the current plan, usage, and key counts for an organization.
   *
   * Usage figures reflect the current calendar month (UTC).
   *
   * @param orgId - UUID of the organization.
   */
  async getOrgPlan(orgId: string): Promise<OrgPlanInfo> {
    const raw = (await this.get(
      `/api/v1/org/${encodeURIComponent(orgId)}/plan`,
    )) as Record<string, unknown>;
    const plan = raw.plan as Record<string, unknown>;
    const usage = raw.usage as Record<string, unknown>;
    return {
      plan: this.mapPlanInfo(plan),
      usage: {
        month: usage.month as string,
        tokenizeCalls: usage.tokenize_calls as number,
        rehydrateCalls: usage.rehydrate_calls as number,
        flushCalls: usage.flush_calls as number,
        totalTokensCreated: usage.total_tokens_created as number,
      },
      activeKeys: raw.active_keys as number,
      maxKeys: raw.max_keys as number,
    };
  }

  // ── Private helpers ─────────────────────────────────────────────────────

  private mapPlanInfo(raw: Record<string, unknown>): PlanInfo {
    return {
      id: raw.id as string,
      name: raw.name as string,
      rateLimitPerMinute: raw.rate_limit_per_minute as number,
      monthlyTokenLimit: raw.monthly_token_limit as number,
      maxKeys: raw.max_keys as number,
      priceCents: raw.price_cents as number,
    };
  }

  private async post(path: string, body: unknown): Promise<Record<string, unknown>> {
    const url = `${this.baseUrl}${path}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Key': this.adminKey,
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      if (!response.ok) {
        await this.handleError(response);
      }

      return (await safeParseJson(response)) as Record<string, unknown>;
    } finally {
      clearTimeout(timer);
    }
  }

  private async get(path: string): Promise<Record<string, unknown> | unknown[]> {
    const url = `${this.baseUrl}${path}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: {
          'X-Admin-Key': this.adminKey,
        },
        signal: controller.signal,
      });

      if (!response.ok) {
        await this.handleError(response);
      }

      return (await safeParseJson(response)) as Record<string, unknown> | unknown[];
    } finally {
      clearTimeout(timer);
    }
  }

  private async delete(path: string): Promise<void> {
    const url = `${this.baseUrl}${path}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    try {
      const response = await fetch(url, {
        method: 'DELETE',
        headers: {
          'X-Admin-Key': this.adminKey,
        },
        signal: controller.signal,
      });

      if (!response.ok) {
        await this.handleError(response);
      }
    } finally {
      clearTimeout(timer);
    }
  }

  private async handleError(response: Response): Promise<never> {
    let body: PrivacyShieldError;
    try {
      body = (await safeParseJson(response)) as PrivacyShieldError;
    } catch {
      body = {
        error: `HTTP ${response.status}: ${response.statusText}`,
        code: 'UNKNOWN',
        detail: null,
      };
    }
    throw new PrivacyShieldApiError(response.status, body);
  }
}
