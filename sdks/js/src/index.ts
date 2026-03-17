/**
 * @privacyshield/sdk — PII Detection SDK for Node.js and browsers.
 *
 * @example
 * ```ts
 * import { PrivacyShield } from '@privacyshield/sdk';
 *
 * const ps = new PrivacyShield({
 *   apiKey: 'ps_live_xxx',
 *   // For mTLS (Node.js only):
 *   clientCert: fs.readFileSync('./client.crt'),
 *   clientKey: fs.readFileSync('./client.key'),
 *   caCert: fs.readFileSync('./ca.crt'),
 * });
 *
 * // Tokenize
 * const { tokenizedTexts, tokens } = await ps.tokenize({
 *   texts: ['Mario Rossi, CF RSSMRA85M01H501Z'],
 *   organizationId: 'org-uuid',
 *   requestId: 'req-uuid',
 * });
 *
 * // Rehydrate
 * const { text } = await ps.rehydrate({
 *   text: 'Risposta con [#pe:6542b3dc]',
 *   organizationId: 'org-uuid',
 *   requestId: 'req-uuid',
 * });
 *
 * // Flush (cleanup)
 * await ps.flush({ organizationId: 'org-uuid', requestId: 'req-uuid' });
 * ```
 */

export { PrivacyShield, PrivacyShieldApiError } from './client.js';
export type {
  FlushRequest,
  FlushResponse,
  HealthResponse,
  MetricsCallback,
  PiiType,
  PrivacyShieldConfig,
  PrivacyShieldError,
  RehydrateRequest,
  RehydrateResponse,
  TokenEntry,
  TokenizeRequest,
  TokenizeResponse,
} from './types.js';
