# Privacy Shield -- Data Protection Impact Assessment (DPIA)

> Last Updated: [DATE]
>
> Next Review: [REVIEW_DATE]
>
> DPIA Owner: [DPO_NAME], [DPO_EMAIL]

---

## 1. Processing Description

### 1.1 Overview

Privacy Shield is an automated PII detection and ephemeral tokenization service for Italian business documents. It processes text submitted via a REST API, identifies personal data using a combination of a fine-tuned NER model (XLM-RoBERTa-base, ONNX INT8 quantized) and compiled regex patterns, and replaces each detected PII span with an opaque cryptographic token. The encrypted original values are stored in an ephemeral Redis vault with a configurable TTL (default 60 seconds), after which they are permanently and automatically deleted.

### 1.2 Processing Operations

```
Controller submits text via API
        |
        v
+------------------+    +-------------------+    +--------------------+
| PII Detection    | -> | Tokenization      | -> | Vault Storage      |
| (NER + Regex)    |    | (AES-256-GCM)     |    | (Redis, TTL 60s)   |
+------------------+    +-------------------+    +--------------------+
        |                       |                         |
        v                       v                         v
  Spans identified      Token: [#tipo:hash]       Encrypted PII stored
  in memory only        returned to caller        (auto-expires)
```

| Operation | Purpose | Data Flow |
|-----------|---------|-----------|
| **Tokenize** | Replace PII with opaque tokens | Text in -> tokenized text + token metadata out; encrypted PII to vault |
| **Rehydrate** | Reverse-map tokens to originals | Tokenized text in -> original text out; reads from vault |
| **Flush** | Immediate deletion of vault entries | request_id in -> all associated vault keys deleted |
| **DEK Rotation** | Rotate per-org encryption key | New DEK generated; all active entries re-encrypted |

### 1.3 Data Subjects

Individuals whose personal data appears in texts submitted by data controllers (customers) to the Privacy Shield API:

- Employees, customers, partners, and contacts of the data controller
- Any natural person referenced in processed documents

### 1.4 Categories of Personal Data

14 PII categories detected (see Section 3 of [PRIVACY_POLICY.md](./PRIVACY_POLICY.md) for the full table). Includes standard personal data (names, addresses, email, phone) and potentially special category data (medical terms via the `med` type).

### 1.5 Technology Stack

| Component | Technology | Location |
|-----------|-----------|----------|
| API Server | Python 3.11 + FastAPI + Uvicorn | Hetzner VPS, Falkenstein, DE |
| NER Model | XLM-RoBERTa-base, ONNX Runtime INT8 (265MB) | Local, same server |
| Regex Engine | 7 compiled Python regex patterns | Local, same server |
| Span Fusion | Deterministic trim + merge + overlap resolution | Local, same server |
| Crypto | AES-256-GCM via `cryptography` (PyCA) | Local, same server |
| Vault | Redis 7.x, zero persistence, localhost only | Local, same server |
| Reverse Proxy | Nginx, TLS 1.3, mTLS | Local, same server |

## 2. Necessity and Proportionality

### 2.1 Necessity

Processing is necessary to fulfill the contractual obligation of providing PII protection services to data controllers. Without processing the text to detect PII, the service cannot produce the tokenized output that controllers require.

### 2.2 Proportionality Assessment

| Principle | Assessment |
|-----------|-----------|
| **Data minimisation** | Only detected PII spans are extracted and stored -- never the full submitted text. The text is processed in memory and discarded after the API response is returned. |
| **Storage limitation** | Vault entries auto-expire via TTL (default 60 seconds). No persistent database is used. Redis is configured with zero persistence (`save ""`, `appendonly no`). |
| **Purpose limitation** | Processing is limited to three explicit operations (tokenize, rehydrate, flush) requested by the controller via authenticated API calls. No secondary use (analytics, training, profiling). |
| **Accuracy** | PII detection achieves 88.5% exact F1 / 93.2% partial F1. Regex patterns for structured identifiers (CF, IBAN, email, phone) have near-perfect precision. |
| **Integrity and confidentiality** | AES-256-GCM encryption with per-org DEK, envelope encryption, and AAD binding to org_id. TLS 1.3 + mTLS in transit. |

### 2.3 Alternatives Considered

| Alternative | Reason Not Selected |
|-------------|-------------------|
| Cloud NLP API (Google, AWS) | PII would leave EU / be processed by third-party -- increases transfer risk |
| Persistent database for vault | Increases data retention risk; ephemeral Redis eliminates entire category of breach scenarios |
| Shared encryption key across orgs | Cross-tenant risk; per-org DEK ensures cryptographic isolation |
| Client-side detection only | Lower accuracy; no server-side crypto guarantee; client cannot be trusted |

## 3. Risk Assessment

### 3.1 Risk Matrix

| Risk ID | Risk Description | Likelihood | Impact | Residual Risk | Justification |
|---------|-----------------|------------|--------|---------------|---------------|
| R-01 | Unauthorized access to vault entries | Low | High | **LOW** | AES-256-GCM encryption, per-org DEK, API key auth, TLS 1.3 + mTLS, rate limiting |
| R-02 | Data breach (vault exfiltration) | Low | High | **LOW** | Ephemeral storage (60s TTL), no persistence, Redis bound to localhost, UFW firewall |
| R-03 | Purpose deviation (secondary use of PII) | Very Low | Medium | **LOW** | Processing limited to 3 API operations; no analytics, no model training, no logging of PII values |
| R-04 | Cross-tenant data leakage | Very Low | Critical | **LOW** | Vault keys scoped to `org_id:request_id:hash`; AES-GCM AAD binds ciphertext to `org_id`; per-org DEK |
| R-05 | Model inference attack (PII type distribution) | Very Low | Low | **NEGLIGIBLE** | Prometheus metrics omit PII type distribution; audit logs access-controlled; token count only |
| R-06 | Key compromise (KEK) | Very Low | Critical | **LOW** | KEK loaded from env var (not stored on disk); per-org DEK limits blast radius; DEK rotation available |
| R-07 | Key compromise (single org DEK) | Low | High | **LOW** | Per-org isolation: compromise of one DEK does not affect other organizations |
| R-08 | Denial of service exhausting vault | Low | Medium | **LOW** | Per-org token quota (default 10,000); per-key rate limiting; admin rate limiting (10/min/IP) |
| R-09 | Processing of special category data (medical) | Medium | High | **MEDIUM** | Controller responsibility to ensure Art. 9(2) basis; documented in DPA Section 3 |
| R-10 | Orphaned vault entries on crash | Low | Low | **LOW** | Graceful shutdown flushes orphan `ps:req:*` keys; TTL ensures auto-expiry regardless |

### 3.2 Detailed Risk Analysis

#### R-01: Unauthorized Access

**Threat**: An attacker obtains a valid API key or bypasses authentication to access vault entries.

**Mitigations**:
- API keys are SHA-256 hashed before storage; raw keys are never persisted.
- Keys with null bytes or control characters are rejected at the authentication layer to prevent oracle attacks.
- Per-key sliding-window rate limiting prevents brute force.
- Admin endpoints have separate rate limiting (10 req/min per IP), checked before key comparison to prevent timing-based attacks.
- Admin key comparison uses `hmac.compare_digest()` (constant-time) to prevent timing side channels.
- Even if authentication is bypassed, vault entries are AES-256-GCM encrypted under a per-org DEK that is itself encrypted under the KEK.

#### R-04: Cross-Tenant Leakage

**Threat**: One organization's API key is used to access another organization's vault entries.

**Mitigations**:
- Vault keys are scoped: `ps:{org_id}:{request_id}:{token_hash}`. An attacker would need to guess all three components.
- AES-GCM AAD (`associated_data`) is set to `org_id.encode()` during encryption. Attempting to decrypt with a different org's DEK or without the correct AAD causes an `InvalidTag` exception.
- The `org_id` resolved from the API key takes precedence over the `org_id` in the request body. If they mismatch, the API key's `org_id` is used (logged as a warning).
- Per-org DEK: even if vault keys could be guessed, the encryption key is different per organization.

#### R-06: KEK Compromise

**Threat**: The master Key Encryption Key is compromised, enabling decryption of all org DEKs.

**Mitigations**:
- KEK is loaded from the `PRIVACY_SHIELD_KEK_BASE64` environment variable at startup. It is validated as exactly 32 bytes of base64-decoded data.
- KEK is never written to disk, logs, or API responses.
- KEK validation occurs via a dummy encrypt/decrypt round-trip at startup (`validate_kek()`).
- In the event of suspected compromise: generate a new KEK, rotate all org DEKs via `POST /api/v1/rotate-dek`, restart the service.

## 4. Mitigation Measures

### 4.1 Encryption at Rest

```
# app/infrastructure/adapters/aes_crypto.py

KEK (32 bytes, env var PRIVACY_SHIELD_KEK_BASE64)
  |
  +-- encrypt_dek(dek) --> AES-256-GCM(KEK, dek) --> stored at ps:dek:{org_id}
  |
  +-- Per-org DEK (32 bytes, os.urandom)
        |
        +-- encrypt(dek, pii, aad=org_id) --> nonce(12B) + tag+ciphertext
        |                                     stored at ps:{org}:{req}:{hash}
        |                                     TTL: 60s (configurable)
        |
        +-- hmac_token_hash(dek, pii) --> 8-char hex suffix for display token
```

- Algorithm: AES-256-GCM (authenticated encryption with associated data)
- Nonce: 12 bytes, cryptographically random (`os.urandom`), unique per encryption
- AAD: `org_id.encode()` -- binds ciphertext to the originating organization
- Wire format: `nonce (12B) + tag_and_ciphertext (variable)`

### 4.2 Encryption in Transit

- TLS 1.3 via Nginx reverse proxy with Let's Encrypt certificate
- mTLS: client certificate required for production API access
- HSTS enabled
- Uvicorn bound to `localhost:6379` only -- not directly accessible from the network

### 4.3 Access Control

| Control | Implementation |
|---------|---------------|
| API key authentication | `X-Api-Key` header, SHA-256 hashed lookup |
| Admin key authentication | `X-Admin-Key` header, `hmac.compare_digest()` |
| Per-key rate limiting | Redis sliding window, configurable per-minute limit |
| Admin rate limiting | 10 req/min per IP, checked before key comparison |
| Input sanitisation | Null byte and control character rejection on API keys |
| Request validation | Pydantic strict typing, UUID format validation on org_id and request_id |

### 4.4 Pseudonymisation

- Token format: `[#tipo:XXXXXXXX]` where `XXXXXXXX` is an 8-character hex string derived from `HMAC-SHA256(DEK, pii_value)`.
- Tokens are opaque -- no PII can be derived from the token itself without access to the vault.
- Reverse mapping requires: valid API key for the correct org + correct `request_id` + vault entry not expired.

### 4.5 Data Minimisation

- Only detected PII spans are extracted, encrypted, and stored.
- Full submitted text is processed in memory and discarded after the response.
- No persistent database is used for PII storage.
- Redis configured with zero persistence: `save ""`, `appendonly no`.

### 4.6 Availability and Resilience

| Measure | Implementation |
|---------|---------------|
| Auto-restart | systemd service (`Restart=always`) |
| Health monitoring | `GET /health` checks Redis, crypto, and NER model |
| Graceful shutdown | Request drain (10s), orphan vault entry cleanup via SCAN + UNLINK |
| Shutdown guard | New requests receive HTTP 503 during shutdown phase |
| Resource limits | Per-org token quota (default 10,000); per-key rate limiting |
| Processing timeout | 5-second timeout per text in tokenize endpoint (`asyncio.wait_for`) |

### 4.7 Audit and Logging

| Measure | Implementation |
|---------|---------------|
| Structured logging | JSON format via custom `_JsonFormatter`, Pino-compatible |
| PII prevention in logs | `SAFE_LOG_FIELDS` allowlist; forbidden fields raise `ValueError` |
| GDPR Art. 30 records | `log_processing_activity()` with pseudonymised org_id (SHA-256 first 12 hex chars) |
| Metrics | In-memory counters/histograms, no PII in labels; Prometheus exposition available |
| Auth failure tracking | `ps_auth_failures_total` counter with reason labels |

### 4.8 Testing

| Category | Count | Coverage |
|----------|-------|---------|
| Unit tests | Included in 498 total | Core domain logic, crypto, detection |
| Integration tests | Included in 498 total | Full API request/response cycles |
| Adversarial security tests | Included in 498 total | Cross-tenant, concurrent access, input fuzzing |
| Red team audit | 11 attack vectors | 11/11 mitigated |
| Security hardening | 10 specific fixes | All verified with regression tests |

## 5. Consultation

### 5.1 Internal Stakeholders

| Stakeholder | Consulted | Input |
|-------------|-----------|-------|
| Engineering | Yes | Technical architecture, crypto design, testing strategy |
| Product | Yes | PII categories, TTL defaults, quota limits |
| Legal | [PENDING] | DPA template review, legal basis confirmation |

### 5.2 Data Subjects

Direct consultation with data subjects is not feasible because:

- Privacy Shield processes data on behalf of data controllers (customers), not directly from data subjects.
- The data subjects are individuals referenced in documents submitted by the controller.
- The controller is responsible for informing data subjects about the use of Privacy Shield as a processor.

### 5.3 Supervisory Authority Consultation

Prior consultation with the supervisory authority (Art. 36) is **not required** because:

- The residual risks identified in Section 3 are all rated LOW or NEGLIGIBLE after mitigation.
- The ephemeral architecture eliminates the highest-impact persistence-related risks entirely.
- No high-risk processing (large-scale profiling, systematic monitoring of public areas) is performed.

## 6. Conclusion

### 6.1 Overall Assessment

The processing carried out by Privacy Shield is **proportionate** to the stated purpose of PII protection in business documents. The ephemeral-by-design architecture, combined with strong cryptographic controls (AES-256-GCM, per-org DEK, envelope encryption, AAD binding), ensures that risks to data subjects are adequately mitigated.

### 6.2 Residual Risk Summary

| Risk Level | Count | Risk IDs |
|------------|-------|----------|
| NEGLIGIBLE | 1 | R-05 |
| LOW | 8 | R-01, R-02, R-03, R-04, R-06, R-07, R-08, R-10 |
| MEDIUM | 1 | R-09 (special category data -- controller responsibility) |
| HIGH | 0 | -- |
| CRITICAL | 0 | -- |

### 6.3 Conditions for Approval

This DPIA is approved subject to:

1. Controllers processing special category data (`med` type) must confirm their Art. 9(2) legal basis in the DPA.
2. KEK rotation procedure must be documented and tested at least annually.
3. This DPIA must be reviewed on or before **[REVIEW_DATE]**, or earlier if:
   - The processing operations change materially.
   - A data breach occurs.
   - New PII categories are added to the detection engine.
   - The infrastructure hosting arrangement changes.

---

**Approved by**: [NAME], [TITLE]

**Date**: [DATE]
