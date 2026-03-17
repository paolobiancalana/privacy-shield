# Privacy Shield -- Privacy Policy

> Last Updated: [DATE]

## 1. Data Controller

This Privacy Policy describes how **[YOUR LEGAL ENTITY]** ("we", "us", "the Controller") processes personal data through the Privacy Shield platform, a PII detection and ephemeral tokenization service accessible at `api.privacyshield.pro`.

**Contact**:
- Data Protection Officer: [DPO_EMAIL]
- Registered address: [YOUR ADDRESS]

## 2. Purpose of Processing

Privacy Shield detects Personally Identifiable Information (PII) in Italian business documents and replaces it with opaque, cryptographically derived tokens. The purpose is to enable downstream systems to process documents without exposure to raw personal data.

Processing operations:
- **Tokenize**: Detect PII spans via NER model (XLM-RoBERTa) and regex engine, replace each span with an opaque token of the form `[#tipo:XXXXXXXX]`, and store the encrypted original in an ephemeral vault.
- **Rehydrate**: Reverse-map tokens back to original PII values using the ephemeral vault.
- **Flush**: Immediately and irrevocably delete all vault entries associated with a specific request.

## 3. Categories of Personal Data Processed

Privacy Shield detects and tokenizes the following PII categories:

| Code | Category | Detection Source | Description |
|------|----------|-----------------|-------------|
| `pe` | Persona | NER | Personal names |
| `org` | Organizzazione | NER | Organization names |
| `loc` | Localita | NER | Place names, cities |
| `ind` | Indirizzo | NER | Street addresses |
| `med` | Medico | NER | Medical terms, conditions |
| `leg` | Legale | NER | Legal references, case numbers |
| `rel` | Relazione | NER | Relationship descriptors |
| `fin` | Finanziario | NER | Financial information |
| `pro` | Professione | NER | Professional titles, roles |
| `dt` | Data nascita | NER | Dates of birth (discursive form) |
| `cf` | Codice Fiscale | Regex | Italian fiscal codes |
| `ib` | IBAN | Regex | International bank account numbers |
| `em` | Email | Regex | Email addresses |
| `tel` | Telefono | Regex | Phone numbers |

**Important**: The full text submitted by the caller is never stored. Only the individual PII spans detected within the text are encrypted and placed in the ephemeral vault. The text itself is processed in memory and discarded after the response is returned.

## 4. Legal Basis for Processing

Processing is carried out under the following legal bases pursuant to GDPR Article 6(1):

- **Article 6(1)(b) -- Contractual necessity**: Processing is necessary for the performance of the data processing agreement between the Controller and the customer (data controller) who submits texts via the API.
- **Article 6(1)(f) -- Legitimate interest**: The Controller has a legitimate interest in providing PII protection services that minimize the exposure of personal data in document workflows. This interest is balanced against the rights of data subjects by the ephemeral nature of processing (all data auto-expires within the configured TTL).

## 5. Data Retention

Privacy Shield operates on an **ephemeral-only** retention model:

| Data Category | Storage | Retention | Mechanism |
|---------------|---------|-----------|-----------|
| Encrypted PII vault entries | Redis (in-memory) | Configurable TTL (default: **60 seconds**) | Redis key expiry (`EXPIRE`) |
| Per-org Data Encryption Keys | Redis (in-memory) | Duration of service operation | No TTL; deleted on org offboarding |
| API key metadata | Redis (in-memory) | Duration of service operation | Explicit revocation or service termination |
| Audit logs (GDPR Art. 30) | Structured JSON log files | Per log rotation policy | Org ID is SHA-256 hashed (pseudonymised) |
| Prometheus/JSON metrics | In-memory only | Until process restart | No PII in metrics by design |

**No persistent database is used for PII storage.** Redis is configured with zero persistence (`save ""`, `appendonly no`). A process restart or Redis restart permanently destroys all vault entries.

Callers may also trigger immediate deletion at any time via the `POST /api/v1/flush` endpoint, which atomically removes all vault entries associated with a given `request_id`.

## 6. Sub-Processors

| Sub-Processor | Role | Location | Data Accessed |
|---------------|------|----------|---------------|
| **Hetzner Online GmbH** | Infrastructure hosting (VPS) | Falkenstein, Germany (EU) | Encrypted vault entries in transit within the server |
| **Redis** (self-hosted) | Ephemeral in-memory cache | Co-located on Hetzner VPS, Falkenstein, Germany (EU) | Encrypted PII values (AES-256-GCM ciphertext only) |

No third-party SaaS services receive or process PII. The NER model (XLM-RoBERTa ONNX INT8) runs locally on the same server -- no external ML API calls are made.

## 7. Data Subject Rights (GDPR Articles 15--22)

Data subjects whose personal data may appear in texts submitted to Privacy Shield have the following rights:

| Right | Article | How to Exercise |
|-------|---------|-----------------|
| **Access** | Art. 15 | Contact the DPO. Note: due to ephemeral storage, data may no longer exist at the time of request. |
| **Rectification** | Art. 16 | Contact the DPO. Vault entries are immutable; rectification is achieved by flushing and re-tokenizing. |
| **Erasure** | Art. 17 | Automatic via TTL expiry. Immediate erasure via `POST /api/v1/flush`. Contact DPO for org-level erasure. |
| **Restriction of Processing** | Art. 18 | Contact the DPO. API key can be revoked to halt all processing for an organization. |
| **Data Portability** | Art. 20 | Contact the DPO. Token-to-PII mappings can be exported before vault expiry via the rehydrate endpoint. |
| **Objection** | Art. 21 | Contact the DPO at [DPO_EMAIL]. |

**Practical note**: Because vault entries expire within seconds (default 60s), in most cases the personal data will have been permanently deleted before a data subject request can be received and processed. This ephemeral architecture is itself a strong privacy-by-design measure.

## 8. International Data Transfers

**No international data transfers occur.** All processing, storage, and transmission take place within the European Union:

- Server: Hetzner Online GmbH, Falkenstein, Germany
- Redis: localhost on the same server
- NER model: runs locally on the same server
- No external API calls are made during PII processing

## 9. Cookies and Tracking

Privacy Shield is an **API-only service**. It does not serve web pages to end users, does not set cookies, and does not use any tracking technologies (analytics, pixels, fingerprinting, or similar).

## 10. Security Measures

A summary of technical and organisational measures is provided here. For the full evidence document, see [TECHNICAL_MEASURES.md](./TECHNICAL_MEASURES.md).

- **Encryption at rest**: AES-256-GCM with per-organization Data Encryption Keys (DEK), wrapped under a master Key Encryption Key (KEK) using envelope encryption.
- **Encryption in transit**: TLS 1.3 via Nginx reverse proxy with Let's Encrypt certificate. mTLS (mutual TLS with client certificate) required for production API access.
- **Access control**: Per-organization API keys (SHA-256 hashed storage), admin key for management endpoints, per-key sliding-window rate limiting.
- **Tenant isolation**: Vault keys scoped to `org_id:request_id:hash`. AES-GCM Additional Authenticated Data (AAD) cryptographically binds ciphertext to the originating `org_id`.
- **Data minimisation**: Only detected PII spans are processed; full text is never stored.
- **Pseudonymisation**: Token format `[#tipo:XXXXXXXX]` is opaque; no PII can be derived from the token itself.

## 11. Changes to This Policy

We may update this Privacy Policy to reflect changes in our processing activities or applicable law. Material changes will be communicated to customers via email or API notification. The "Last Updated" date at the top of this document indicates the most recent revision.

## 12. Contact

For questions, concerns, or to exercise your data subject rights:

- **Data Protection Officer**: [DPO_EMAIL]
- **Postal address**: [YOUR ADDRESS]
- **Supervisory authority**: You have the right to lodge a complaint with the competent data protection supervisory authority in your EU member state.
