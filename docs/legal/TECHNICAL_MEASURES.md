# Privacy Shield -- Technical and Organisational Measures (GDPR Art. 32)

> Last Updated: [DATE]
>
> This document provides evidence of the "appropriate technical and organisational measures" implemented by Privacy Shield to ensure a level of security appropriate to the risk, as required by GDPR Article 32.

---

## 1. Encryption

### 1.1 Encryption at Rest

| Property | Value |
|----------|-------|
| Algorithm | AES-256-GCM (Galois/Counter Mode) |
| Library | `cryptography` (PyCA) -- `AESGCM` class |
| Key size | 256 bits (32 bytes) |
| Nonce | 12 bytes, cryptographically random (`os.urandom`) per encryption |
| Authentication tag | 16 bytes (GCM provides authenticated encryption) |
| Wire format | `nonce (12B) \|\| tag_and_ciphertext (variable)` |

**Per-Organization Data Encryption Key (DEK)**:

- Each organization receives a unique 32-byte random DEK, generated via `os.urandom(32)`.
- The DEK encrypts all PII vault entries for that organization.
- DEKs are stored in Redis at key `ps:dek:{org_id}` with no TTL (lifecycle managed separately).

**Key Encryption Key (KEK) -- Envelope Encryption**:

```
KEK (32 bytes, from env var PRIVACY_SHIELD_KEK_BASE64)
  |
  +-- AES-256-GCM(KEK, raw_dek) --> encrypted_dek stored in Redis
  |
  +-- Startup validation: encrypt/decrypt round-trip on probe value
```

- The KEK wraps (encrypts) each per-org DEK before it is stored in Redis.
- The KEK is loaded from the `PRIVACY_SHIELD_KEK_BASE64` environment variable at process startup.
- Validated as exactly 32 bytes of decoded base64 by a Pydantic field validator. Startup fails immediately if the KEK is missing, malformed, or the wrong length.
- The KEK is never written to disk, logs, metrics, or API responses.

**Additional Authenticated Data (AAD)**:

- PII encryption calls pass `associated_data=org_id.encode()` to `AES-256-GCM.encrypt()`.
- This cryptographically binds the ciphertext to the originating organization.
- Decryption with a mismatched `org_id` (or without AAD) causes an `InvalidTag` exception, preventing cross-tenant decryption even if vault keys could be guessed.

**DEK Concurrency Safety**:

```python
# app/infrastructure/adapters/aes_crypto.py — get_or_create_dek()
#
# Uses VaultPort.set_dek_if_absent() which executes a Redis Lua script
# with SET-NX semantics. Two concurrent first requests for the same org
# both generate a candidate DEK, but only one wins the atomic write.
# Both callers decrypt and return the *winning* DEK.
```

### 1.2 DEK Rotation

- Endpoint: `POST /api/v1/rotate-dek` (requires `X-Admin-Key`)
- Generates a new 32-byte DEK for the specified organization.
- Scans all active vault entries via `scan_active_token_hashes()` (cursor-based `SCAN`, non-blocking).
- Re-encrypts each entry: decrypt with old DEK, encrypt with new DEK, store with preserved TTL.
- Stores the new encrypted DEK at `ps:dek:{org_id}`.
- Safe to retry: partial rotations re-encrypt remaining entries on the next call.

### 1.3 Encryption in Transit

| Property | Value |
|----------|-------|
| Protocol | TLS 1.3 |
| Certificate | Let's Encrypt (auto-renewed) |
| Client auth | mTLS -- client certificate required for production API access |
| HSTS | Enabled |
| Reverse proxy | Nginx (terminates TLS) |
| Backend binding | Uvicorn on `localhost:8000` only -- not network-accessible |

## 2. Access Control

### 2.1 API Key Authentication

```
Client                          Privacy Shield
  |                                  |
  |-- X-Api-Key: <raw_key> -------->|
  |                                  |-- SHA-256(raw_key) --> key_hash
  |                                  |-- validate_key(key_hash)
  |                                  |     |
  |                                  |     +--> Redis: ps:key:{key_hash}
  |                                  |     +--> Returns ApiKeyMetadata or None
  |                                  |
  |                                  |-- check_rate_limit(key_hash, limit)
  |                                  |     |
  |                                  |     +--> Redis: INCR ps:rate:{key_hash}:{minute}
  |                                  |     +--> Returns (allowed: bool, count: int)
  |                                  |
  |<-- 200 / 401 / 429 -------------|
```

| Property | Implementation |
|----------|---------------|
| Header | `X-Api-Key` |
| Storage | SHA-256 hash only -- raw key never stored |
| Lookup | `ApiKeyPort.validate_key(key_hash)` returns `ApiKeyMetadata` or `None` |
| Revocation | `active` field set to `False`; revoked keys remain for audit but are rejected |
| Rate limit | Per-key sliding window with configurable per-minute limit |
| Input sanitisation | Null bytes (`\x00`) and control characters (`ord(c) < 32`) rejected immediately |

### 2.2 Admin Key Authentication

| Property | Implementation |
|----------|---------------|
| Header | `X-Admin-Key` |
| Comparison | `hmac.compare_digest()` -- constant-time to prevent timing side channels |
| Rate limit | 10 requests/minute per client IP (Redis sliding window) |
| Rate limit ordering | Rate limit checked **before** key comparison to prevent brute-force timing attacks |
| Disabled state | If `ADMIN_API_KEY` env var is empty, admin endpoints return HTTP 403 |

### 2.3 Request Validation

| Validation | Implementation |
|------------|---------------|
| Schema | Pydantic `BaseModel` with `Field` constraints and `field_validator` |
| UUID enforcement | `organization_id` and `request_id` validated as UUID format |
| Text size | Max 10,000 characters per text, max 100 texts per request |
| Org mismatch | If body `organization_id` differs from API key's `org_id`, the key's `org_id` is authoritative (warning logged) |

## 3. Pseudonymisation

### 3.1 Token Format

```
[#tipo:XXXXXXXX]

  tipo     = PII type code (pe, org, loc, ind, med, leg, rel, fin, pro, dt, cf, ib, em, tel)
  XXXXXXXX = 8-character hex string derived from HMAC-SHA256(DEK, pii_value)
```

**Properties**:

| Property | Value |
|----------|-------|
| Derivation | `HMAC-SHA256(dek, pii_value.encode('utf-8')).hexdigest()[:8]` |
| Determinism | Same (DEK, PII value) always produces the same token within one org |
| Irreversibility | HMAC truncation -- cannot recover PII from the 8-char suffix |
| Collision handling | Hash collisions resolved with `_N` suffix (e.g., `a3f2_2`) |
| Reverse mapping | Requires vault access: correct `org_id` + `request_id` + vault not expired |

### 3.2 Audit Log Pseudonymisation

- `log_processing_activity()` hashes `org_id` via `SHA-256` and uses only the first 12 hex characters.
- GDPR Article 30 records contain: operation name, pseudonymised org hash, aggregated PII type counts, token count, and duration. No actual PII values.

## 4. Data Minimisation

| Measure | Implementation |
|---------|---------------|
| Span-only extraction | Only detected PII spans are encrypted and stored -- full text is never persisted |
| Ephemeral vault | Redis with zero persistence (`save ""`, `appendonly no`) |
| TTL expiry | Default 60 seconds, configurable via `TOKEN_TTL_SECONDS` (minimum 10s) |
| Explicit flush | `POST /api/v1/flush` atomically deletes all vault entries for a request |
| No secondary storage | No database, no file system, no object store for PII |
| Metrics isolation | Prometheus metrics omit PII type distribution to prevent inference of processing patterns |

## 5. Availability and Resilience

### 5.1 Service Continuity

| Measure | Implementation |
|---------|---------------|
| Process management | systemd service with `Restart=always` |
| Health monitoring | `GET /health` -- checks Redis connectivity (with latency), crypto subsystem (KEK probe), and NER model status |
| HTTP status | 200 for `healthy`, 503 for `degraded` (one or more components down) |

### 5.2 Graceful Shutdown

```
SIGTERM received
    |
    v
1. Set shutdown flag --> new requests receive HTTP 503
    |
    v
2. Drain in-flight requests (up to 10 seconds)
    |
    v
3. SCAN ps:req:* --> UNLINK orphaned request tracking sets
    |
    v
4. Close Redis connection pool
    |
    v
Process exits
```

- The `_SHUTDOWN_DRAIN_SECONDS = 10` constant controls the drain timeout.
- Orphan cleanup uses cursor-based `SCAN` (non-blocking) and `UNLINK` (background deletion).
- Health and metrics endpoints remain available during shutdown for monitoring.

### 5.3 Resource Protection

| Protection | Implementation |
|-----------|---------------|
| Per-org token quota | Default 10,000 active tokens (`MAX_TOKENS_PER_ORG`); enforced via `count_org_tokens()` |
| Quota exceeded | HTTP 503 with message "Organization token quota exceeded" (`QuotaExceededError`) |
| Per-text timeout | 5-second `asyncio.wait_for()` on each text in the tokenize endpoint |
| Per-key rate limit | Configurable sliding window (default 100 req/min) |
| Admin rate limit | 10 req/min per IP, prevents brute-force on `X-Admin-Key` |
| Text size limit | 10,000 characters per text, 100 texts per request |

## 6. Monitoring and Audit

### 6.1 Structured Logging

| Property | Implementation |
|----------|---------------|
| Format | JSON, one object per line |
| Library | Python stdlib `logging` with custom `_JsonFormatter` |
| Namespace | `privacy_shield.*` logger hierarchy |
| Extra fields | Prefixed with `_ps_` in `LogRecord`, stripped to clean keys in JSON output |

### 6.2 PII Prevention in Logs

```python
# app/infrastructure/telemetry.py

SAFE_LOG_FIELDS: frozenset[str] = frozenset({
    "token_count", "span_count", "source", "rehydrated_count",
    "flushed_count", "duration_ms", "org_id", "request_id",
    "operation", "detection_ms", "tokenization_ms", "status",
    "key_id", "plan", "count", "limit", "error_code",
    "re_encrypted_count", "component_status", "text_count",
    "environment", "key_hash", "audit", "pii_type_counts", "org_hash",
})
```

- `log_operation()` raises `ValueError` if any keyword argument is not in `SAFE_LOG_FIELDS`.
- Forbidden fields (e.g., `original_text`, `pii_value`, `decrypted_*`) are rejected at call time, not at output time.
- `log_error()` accepts only `operation`, `org_id`, `error_code`, and a generic `message` (which must not contain PII).

### 6.3 GDPR Article 30 -- Record of Processing Activities

```python
# app/infrastructure/telemetry.py — log_processing_activity()

{
    "timestamp": "2026-03-17T10:30:45",
    "level": "INFO",
    "logger": "privacy_shield.audit",
    "message": "processing_activity operation=tokenize",
    "audit": true,
    "operation": "tokenize",
    "org_hash": "a1b2c3d4e5f6",          // SHA-256 first 12 hex chars
    "pii_type_counts": {"pe": 3, "cf": 1}, // aggregate counts only
    "token_count": 4,
    "duration_ms": 87.234
}
```

- Emitted for every tokenize operation.
- `org_id` is pseudonymised to a 12-character SHA-256 hash.
- Contains only aggregate PII type counts -- never individual PII values.

### 6.4 Metrics

**Counters** (no PII in labels):

| Metric | Labels | Description |
|--------|--------|-------------|
| `ps_tokenizations_total` | `source` (regex/slm) | Total tokenize calls |
| `ps_tokens_created` | (none) | Total tokens created (type omitted intentionally) |
| `ps_failures_total` | `reason` | Operation failures |
| `ps_flush_total` | `status` | Flush outcomes |
| `ps_dek_rotations_total` | (none) | DEK rotation count |
| `ps_health_checks_total` | `status` | Health check results |
| `ps_auth_failures_total` | `reason` | Auth failure tracking |

**Histograms**:

| Metric | Labels | Description |
|--------|--------|-------------|
| `ps_latency_ms` | `operation` | Request latency (tokenize/rehydrate/flush) |

**GDPR safety**: The `ps_tokens_created` counter deliberately omits PII type labels. The docstring in `record_tokenization()` explains: "An attacker with metrics access could infer what kinds of PII an org processes."

**Exposition formats**:

| Endpoint | Format | Auth |
|----------|--------|------|
| `GET /metrics` | JSON snapshot | Admin key |
| `GET /metrics/prometheus` | Prometheus text 0.0.4 | Admin key |

## 7. Tenant Isolation

### 7.1 Vault Key Scoping

```
Vault entry key:     ps:{org_id}:{request_id}:{token_hash}
Request tracking:    ps:req:{org_id}:{request_id}  (Redis SET of token_hashes)
DEK storage:         ps:dek:{org_id}               (no TTL)
Rate limit:          ps:rate:{key_hash}:{minute}
Admin rate limit:    ps:admin_rate:{ip}:{minute}
```

- All vault keys include `org_id` as the first component after the prefix.
- `request_id` provides request-level isolation within an org: tokens from one request cannot be rehydrated using a different `request_id`.

### 7.2 Cryptographic Isolation

| Layer | Mechanism |
|-------|-----------|
| Per-org DEK | Each org has a unique 32-byte AES-256 key; compromise of one does not affect others |
| AES-GCM AAD | `org_id.encode()` bound to ciphertext; decryption with wrong org fails with `InvalidTag` |
| Org resolution | `org_id` resolved from API key (authoritative); body `org_id` is overridden if mismatched |

### 7.3 Org-ID Authority

```python
# app/infrastructure/api/routes.py — tokenize()

org_id = auth["org_id"]                    # from API key lookup
if body.organization_id != org_id:
    _logger.warning(
        "org_id mismatch: body=%s vs key=%s — using key org_id",
        body.organization_id, org_id,
    )
```

The API key's `org_id` is always authoritative. A caller cannot override the organization context by manipulating the request body.

## 8. Testing Evidence

### 8.1 Automated Test Suite

| Category | Description |
|----------|-------------|
| **Total tests** | 498+ |
| **Cross-tenant isolation** | Tests verify that org A's API key cannot access org B's vault entries |
| **Concurrent access** | Tests verify DEK creation under concurrent first-requests (TOCTOU) |
| **Input fuzzing** | Null bytes, control characters, oversized inputs, malformed UUIDs |
| **Crypto round-trip** | Encrypt/decrypt verification for all PII types |
| **AAD mismatch** | Tests verify `InvalidTag` when decrypting with wrong `org_id` |
| **Rate limiting** | Tests verify both per-key and admin rate limit enforcement |
| **Graceful shutdown** | Tests verify drain behavior and orphan cleanup |

### 8.2 Red Team Audit

11 attack vectors tested, all mitigated:

| # | Attack Vector | Result |
|---|--------------|--------|
| 1 | Cross-tenant vault access via body org_id manipulation | Mitigated (key org_id authoritative) |
| 2 | Timing attack on admin key comparison | Mitigated (`hmac.compare_digest`) |
| 3 | Brute-force admin key | Mitigated (10/min/IP rate limit) |
| 4 | PII leakage in error responses | Mitigated (generic error messages, no stack traces) |
| 5 | PII leakage in logs | Mitigated (`SAFE_LOG_FIELDS` allowlist) |
| 6 | PII leakage in metrics | Mitigated (type labels omitted from token counter) |
| 7 | Null byte injection in API key | Mitigated (rejected at auth layer) |
| 8 | Resource exhaustion via token flooding | Mitigated (per-org quota, rate limiting) |
| 9 | Vault entry access after key revocation | Mitigated (revoked keys rejected by `validate_key`) |
| 10 | Cross-request rehydration within same org | Mitigated (`request_id` in vault key) |
| 11 | DEK race condition on concurrent first requests | Mitigated (Lua SET-NX atomic script) |

### 8.3 Security Hardening Summary

10 specific security fixes applied and verified with regression tests:

1. Constant-time admin key comparison (`hmac.compare_digest`)
2. Admin rate limiting before key comparison
3. Null byte / control character rejection on API keys
4. PII type label removal from Prometheus token counter
5. `SAFE_LOG_FIELDS` allowlist with `ValueError` on violations
6. Generic error responses (no stack traces, no internal details)
7. Org-ID authority from API key (body org_id override)
8. Per-org token quota enforcement
9. Graceful shutdown with orphan vault cleanup
10. AES-GCM AAD binding to `org_id`

## 9. Organisational Measures

| Measure | Status |
|---------|--------|
| Data Protection Officer appointed | [PENDING -- DPO_EMAIL] |
| DPA template available for customers | See [DPA_TEMPLATE.md](./DPA_TEMPLATE.md) |
| DPIA completed | See [DPIA.md](./DPIA.md) |
| Processing records (Art. 30) | Automated via `log_processing_activity()` |
| Staff confidentiality obligations | [TO BE DOCUMENTED] |
| Incident response procedure | Breach notification within 72 hours (per DPA Section 8) |
| KEK rotation procedure | [TO BE DOCUMENTED -- recommend annual review] |
| Service monitoring | Health endpoint + Prometheus metrics (admin-protected) |

---

## Appendix A: Configuration Reference

| Environment Variable | Default | Description | GDPR Relevance |
|---------------------|---------|-------------|----------------|
| `PRIVACY_SHIELD_KEK_BASE64` | (required) | Base64-encoded 32-byte master key | Encryption at rest |
| `REDIS_URL` | `redis://localhost:6379` | Redis connection URL | Vault storage location |
| `TOKEN_TTL_SECONDS` | `60` | Vault entry TTL (min: 10) | Data retention period |
| `ADMIN_API_KEY` | (empty = disabled) | Admin key for management endpoints | Access control |
| `DEFAULT_RATE_LIMIT` | `100` | Default per-key rate limit (req/min) | Resource protection |
| `MAX_TOKENS_PER_ORG` | `10000` | Per-org active token quota | Resource protection |
| `LOG_LEVEL` | `INFO` | Logging verbosity | Audit completeness |
| `HOST` | `0.0.0.0` | Bind address | Network exposure |
| `PORT` | `8000` | Bind port | Network exposure |

## Appendix B: Redis Key Patterns

| Pattern | TTL | Purpose |
|---------|-----|---------|
| `ps:{org_id}:{request_id}:{token_hash}` | Configurable (default 60s) | Encrypted PII vault entry |
| `ps:req:{org_id}:{request_id}` | Configurable (reset on each token add) | Request token tracking set |
| `ps:dek:{org_id}` | None (permanent) | Encrypted per-org DEK |
| `ps:key:{key_hash}` | None (permanent) | API key metadata (JSON) |
| `ps:rate:{key_hash}:{minute}` | 120s | Per-key rate limit counter |
| `ps:admin_rate:{ip}:{minute}` | 120s | Admin rate limit counter |
