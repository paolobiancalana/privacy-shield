# @privacyshield/sdk

Privacy Shield PII Detection SDK for Node.js and browsers.

## Install

```bash
npm install @privacyshield/sdk
```

## Quick Start

```typescript
import { PrivacyShield } from '@privacyshield/sdk';

const ps = new PrivacyShield({
  apiKey: 'ps_live_xxx',
});

// Detect and tokenize PII
const result = await ps.tokenize({
  texts: ['Mario Rossi, CF RSSMRA85M01H501Z, Via Roma 42, Milano'],
  organizationId: 'your-org-uuid',
  requestId: crypto.randomUUID(),
});

console.log(result.tokenizedTexts[0]);
// "[#pe:6542b3dc], CF [#cf:fb500f2e], [#ind:450bf5b9]"

// Restore original values
const restored = await ps.rehydrate({
  text: result.tokenizedTexts[0],
  organizationId: 'your-org-uuid',
  requestId: 'same-request-uuid',
});

// Cleanup
await ps.flush({
  organizationId: 'your-org-uuid',
  requestId: 'same-request-uuid',
});
```

## mTLS (Node.js only)

For production environments with mutual TLS:

```typescript
import fs from 'node:fs';

const ps = new PrivacyShield({
  apiKey: 'ps_live_xxx',
  baseUrl: 'https://api.privacyshield.pro',
  clientCert: fs.readFileSync('./client.crt'),
  clientKey: fs.readFileSync('./client.key'),
  caCert: fs.readFileSync('./ca.crt'),
});
```

## API

### `ps.tokenize(request)` → `TokenizeResponse`
Detect PII and replace with opaque tokens.

### `ps.rehydrate(request)` → `RehydrateResponse`
Restore original values from tokens.

### `ps.flush(request)` → `FlushResponse`
Delete all vault entries for a request.

### `ps.health()` → `HealthResponse`
Check service health.

## PII Types Detected

| Code | Type | Detection |
|------|------|-----------|
| pe | Person name | NER |
| org | Organization | NER |
| loc | Location | NER |
| ind | Address | NER |
| med | Medical | NER |
| leg | Legal | NER |
| rel | Relationship | NER |
| fin | Financial | NER |
| pro | Profession | NER |
| dt | Birth date | NER |
| cf | Codice Fiscale | Regex |
| ib | IBAN | Regex |
| em | Email | Regex |
| tel | Phone | Regex |

## License

MIT
