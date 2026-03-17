# Privacy Shield -- Data Processing Agreement (Template)

> Last Updated: [DATE]
>
> This is a template. Replace all `[PLACEHOLDER]` values before execution.

---

## PARTIES

1. **[CUSTOMER LEGAL ENTITY]**, with registered office at [CUSTOMER ADDRESS], acting as **Data Controller** ("Controller")
2. **[YOUR LEGAL ENTITY]**, with registered office at [YOUR ADDRESS], acting as **Data Processor** ("Processor"), operating the Privacy Shield platform

Collectively referred to as the "Parties".

---

## 1. SUBJECT MATTER AND DURATION

### 1.1 Subject Matter

The Processor provides the Controller with a PII (Personally Identifiable Information) detection and ephemeral tokenization service ("Privacy Shield") via a REST API. The Processor detects PII in Italian-language texts submitted by the Controller, replaces detected PII with opaque cryptographic tokens, and stores the encrypted original values in an ephemeral vault for time-limited reverse mapping (rehydration).

### 1.2 Processing Operations

The Processor performs the following operations exclusively as instructed by the Controller via API calls:

| Operation | API Endpoint | Description |
|-----------|-------------|-------------|
| **Tokenize** | `POST /api/v1/tokenize` | Detect PII spans and replace with opaque tokens |
| **Rehydrate** | `POST /api/v1/rehydrate` | Reverse-map tokens to original PII values |
| **Flush** | `POST /api/v1/flush` | Immediately delete all vault entries for a request |
| **DEK Rotation** | `POST /api/v1/rotate-dek` | Rotate the per-organization encryption key |

No processing occurs outside of explicit API calls initiated by the Controller or the Controller's authorized systems.

### 1.3 Duration

This Agreement shall remain in effect for the duration of the service agreement between the Parties. Upon termination, the provisions of Section 10 (Data Return and Deletion) apply.

## 2. CATEGORIES OF DATA SUBJECTS

Individuals whose personal data may appear in texts submitted by the Controller to the Privacy Shield API, including but not limited to:

- Employees of the Controller
- Customers or clients of the Controller
- Business partners and contacts of the Controller
- Any natural person referenced in documents processed by the Controller

## 3. CATEGORIES OF PERSONAL DATA

The following categories of PII are detected and tokenized:

| Code | Category | Examples |
|------|----------|---------|
| `pe` | Personal names | First names, surnames, full names |
| `org` | Organizations | Company names, institution names |
| `loc` | Locations | City names, place names |
| `ind` | Addresses | Street addresses, postal codes |
| `med` | Medical | Medical conditions, treatments |
| `leg` | Legal | Case numbers, legal references |
| `rel` | Relationships | Family relationships, professional relationships |
| `fin` | Financial | Financial amounts, account references |
| `pro` | Professions | Job titles, professional roles |
| `dt` | Dates of birth | Discursive date expressions |
| `cf` | Codice Fiscale | Italian fiscal codes (16-char alphanumeric) |
| `ib` | IBAN | International bank account numbers |
| `em` | Email | Email addresses |
| `tel` | Phone | Phone numbers |

**Special categories (Art. 9)**: Medical (`med`) data may constitute special category data. The Controller is responsible for ensuring a lawful basis exists under Art. 9(2) before submitting texts containing health data.

## 4. PROCESSING INSTRUCTIONS

### 4.1 Scope of Instructions

The Processor shall process personal data only on documented instructions from the Controller, which are defined as:

1. API calls authenticated with a valid `X-Api-Key` issued to the Controller's organization.
2. The operations described in Section 1.2 above.
3. Any written instructions provided by the Controller and acknowledged by the Processor.

### 4.2 Instruction Boundaries

The Processor shall:

- Process personal data exclusively for the purposes of tokenization, rehydration, and flush as requested by the Controller via the API.
- Not process personal data for any other purpose, including but not limited to: analytics, model training, profiling, or marketing.
- Not transfer personal data to any third party except as specified in Section 7 (Sub-Processors).
- Inform the Controller if, in the Processor's opinion, an instruction infringes GDPR or other EU/member state data protection law (Art. 28(3)(a)).

### 4.3 Org-ID Enforcement

All API requests are authenticated via `X-Api-Key`, which resolves to the Controller's `org_id`. The Processor enforces tenant isolation at all layers:

- Vault keys are scoped to `org_id:request_id:hash`.
- AES-GCM Additional Authenticated Data (AAD) cryptographically binds ciphertext to the Controller's `org_id`.
- Cross-organization access is cryptographically impossible without the correct per-org Data Encryption Key (DEK).

## 5. SECURITY MEASURES (GDPR Art. 32)

The Processor implements the following technical and organisational measures:

### 5.1 Encryption

| Layer | Measure |
|-------|---------|
| At rest | AES-256-GCM with per-organization DEK (32-byte random key) |
| Key management | KEK envelope encryption (32-byte master key wraps per-org DEKs) |
| In transit | TLS 1.3 (Let's Encrypt), mTLS with client certificate verification |
| DEK rotation | Available via `POST /api/v1/rotate-dek` (re-encrypts all active entries) |

### 5.2 Access Control

| Measure | Implementation |
|---------|---------------|
| API authentication | Per-organization API key, SHA-256 hashed storage |
| Admin authentication | Separate admin key (`X-Admin-Key`), constant-time comparison (`hmac.compare_digest`) |
| Rate limiting | Per-key sliding window (configurable per-minute limit) |
| Admin rate limiting | 10 requests/minute per client IP (checked before key comparison to prevent timing attacks) |
| Input validation | Null byte and control character rejection on API keys |

### 5.3 Data Minimisation

- Only detected PII spans are encrypted and stored -- full text is never persisted.
- Vault entries auto-expire via configurable TTL (default 60 seconds).
- Explicit flush API for immediate deletion.
- Token format `[#tipo:XXXXXXXX]` is opaque -- no PII derivable from token.

### 5.4 Availability and Resilience

- systemd service with automatic restart.
- Health endpoint (`GET /health`) monitors Redis, crypto subsystem, and NER model.
- Graceful shutdown: request drain (10s), orphan vault entry cleanup.
- Per-organization token quota (default 10,000) prevents resource exhaustion.

### 5.5 Monitoring and Audit

- Structured JSON logging with PII allowlist (`SAFE_LOG_FIELDS`) -- forbidden fields raise `ValueError` immediately.
- GDPR Article 30 audit logging via `log_processing_activity()` with pseudonymised `org_id` (SHA-256 hash).
- Prometheus-compatible metrics endpoint (admin-protected, no PII in metric labels or values).

For the full technical evidence, see [TECHNICAL_MEASURES.md](./TECHNICAL_MEASURES.md).

## 6. CONFIDENTIALITY

The Processor ensures that all personnel authorized to process personal data:

- Have committed themselves to confidentiality or are under an appropriate statutory obligation of confidentiality.
- Process personal data only on instructions from the Controller, unless required to do so by EU or member state law.

## 7. SUB-PROCESSORS

### 7.1 Authorized Sub-Processors

The Controller provides general written authorization for the following sub-processors:

| Sub-Processor | Service | Location | Data Access |
|---------------|---------|----------|-------------|
| **Hetzner Online GmbH** | Infrastructure hosting (VPS) | Falkenstein, Germany (EU) | Physical host of encrypted vault data |

**Note**: Redis runs as a self-hosted, co-located service on the Hetzner VPS, bound to `localhost:6379`. It is not a separate sub-processor. The NER model (XLM-RoBERTa ONNX INT8) runs locally on the same server -- no external ML API calls are made.

### 7.2 Sub-Processor Changes

The Processor shall:

- Inform the Controller in writing of any intended addition or replacement of sub-processors, giving the Controller the opportunity to object (Art. 28(2)).
- Impose the same data protection obligations on any sub-processor by way of a contract (Art. 28(4)).
- Remain fully liable to the Controller for the performance of the sub-processor's obligations.

## 8. DATA BREACH NOTIFICATION

### 8.1 Notification Timeline

The Processor shall notify the Controller without undue delay, and in any event within **72 hours** of becoming aware of a personal data breach, in accordance with GDPR Article 33.

### 8.2 Notification Content

The notification shall include:

- Nature of the breach (categories and approximate number of data subjects and records affected).
- Name and contact details of the DPO or other contact point.
- Likely consequences of the breach.
- Measures taken or proposed to address the breach and mitigate its effects.

### 8.3 Cooperation

The Processor shall cooperate with the Controller to:

- Investigate the breach and determine its scope.
- Fulfill the Controller's notification obligations to supervisory authorities and data subjects.
- Implement corrective measures.

## 9. AUDIT RIGHTS

### 9.1 Information and Evidence

The Processor shall:

- Make available to the Controller all information necessary to demonstrate compliance with GDPR Article 28 obligations.
- Provide audit logs, security test results, and infrastructure configuration evidence upon written request.

### 9.2 Inspections

The Controller (or an independent auditor mandated by the Controller) may conduct audits and inspections. The Processor shall:

- Allow and contribute to audits with reasonable notice (minimum 30 days).
- Provide remote access to relevant logs and monitoring dashboards where feasible.
- Limit physical on-site audits to once per calendar year unless a data breach has occurred.

### 9.3 Automated Evidence

The following evidence is available programmatically:

| Evidence | Access |
|----------|--------|
| Service health | `GET /health` (public) |
| Processing metrics (no PII) | `GET /metrics` (admin key required) |
| Prometheus metrics | `GET /metrics/prometheus` (admin key required) |
| Monthly usage statistics | `GET /api/v1/usage/{org_id}` (admin key required) |

## 10. DATA RETURN AND DELETION

### 10.1 During Contract Term

- All vault entries auto-expire via TTL (default 60 seconds).
- The Controller may explicitly delete vault entries at any time via `POST /api/v1/flush`.
- The Controller may request DEK rotation at any time via `POST /api/v1/rotate-dek`.

### 10.2 Upon Contract Termination

Upon termination of the service agreement:

1. The Processor shall revoke all API keys belonging to the Controller's organization.
2. The Processor shall delete the Controller's per-org DEK from Redis (`ps:dek:{org_id}`).
3. Any remaining vault entries will auto-expire within the TTL window (maximum 60 seconds by default).
4. The Processor shall confirm deletion in writing within 10 business days.

**Note**: Due to the ephemeral architecture (no persistent database, Redis with zero persistence), termination results in complete and irrecoverable data deletion. No backup copies exist.

## 11. LIABILITY

Liability for damages arising from a breach of this Agreement shall be governed by the main service agreement between the Parties and applicable law, including GDPR Article 82.

## 12. STANDARD CONTRACTUAL CLAUSES

If the Controller is established outside the EU/EEA, or if data transfers to third countries become necessary in the future, the Parties shall execute the Standard Contractual Clauses (EU Commission Implementing Decision 2021/914) as an addendum to this Agreement.

**Current status**: No international data transfers occur. All processing takes place within the EU (Hetzner, Falkenstein, Germany).

## 13. GOVERNING LAW

This Agreement shall be governed by the laws of [JURISDICTION], without regard to its conflict of laws provisions. The courts of [JURISDICTION] shall have exclusive jurisdiction over any disputes arising from this Agreement.

---

## SIGNATURES

| | Controller | Processor |
|---|-----------|-----------|
| **Name** | | |
| **Title** | | |
| **Date** | | |
| **Signature** | | |
