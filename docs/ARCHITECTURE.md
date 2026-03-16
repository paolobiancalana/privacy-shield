# Privacy Shield — Architecture Document

> Last updated: 2026-03-16

## Overview

Privacy Shield is a **standalone SaaS platform** for PII (Personally Identifiable Information) detection, tokenization, and rehydration. It serves multiple access channels and user types independently from any specific framework or application.

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Privacy Shield Platform                    │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Dashboard    │  │  API Gateway │  │  Browser Ext │      │
│  │  (Web App)    │  │  (REST)      │  │  (Chrome/FF) │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                  │                  │              │
│         └──────────┬───────┴──────────┬──────┘              │
│                    ▼                  ▼                      │
│  ┌─────────────────────────────────────────────────┐        │
│  │              Platform Layer                      │        │
│  │  - User auth (signup/login/OAuth)               │        │
│  │  - Org & team management                        │        │
│  │  - Self-service API key lifecycle               │        │
│  │  - Plan & subscription management               │        │
│  │  - Usage metering & billing (Stripe)            │        │
│  │  - Admin console                                │        │
│  │                                                 │        │
│  │  Storage: Supabase (users, orgs, plans, keys)   │        │
│  └──────────────────────┬──────────────────────────┘        │
│                         │                                    │
│                         ▼                                    │
│  ┌─────────────────────────────────────────────────┐        │
│  │              Runtime Engine                      │        │
│  │  - NER detection (XLM-RoBERTa, ONNX INT8)      │        │
│  │  - Regex detection (CF, IBAN, email, phone)     │        │
│  │  - Span fusion (post-processing)                │        │
│  │  - AES-256-GCM tokenization / rehydration       │        │
│  │  - Redis vault (ephemeral, zero persistence)    │        │
│  │  - Per-org isolation (vault, DEK, usage)        │        │
│  │                                                 │        │
│  │  Host: Hetzner VPS (api.privacyshield.pro)      │        │
│  └─────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────┘

External integrations:
  ├── SNAP Framework (native adapter, mTLS)
  ├── Any HTTP client (REST API + API key)
  ├── Browser extension (via REST API)
  └── SDKs: Python, JavaScript, Go (future)
```

## Access Channels

| Channel | Auth Method | Status |
|---------|------------|--------|
| **REST API** (api.privacyshield.pro) | mTLS + API key | Production |
| **SNAP Framework** | Native adapter (HttpPrivacyShieldAdapter) | Production |
| **Dashboard** (privacyshield.pro) | Email/password + OAuth | Planned |
| **Browser Extension** | API key (user generates from dashboard) | Planned |
| **Python SDK** | API key | Planned |
| **JavaScript SDK** | API key | Planned |

## User Types

| Type | Description | Example |
|------|-------------|---------|
| **Developer** | Individual using API directly | Freelance dev protecting client data |
| **Organization** | Company with multiple users/keys | Materic.ai, law firm, clinic |
| **SaaS Platform** | Company extending SNAP Framework | Materic.ai (first), 4 more planned |
| **Admin** | Platform operator | Internal team |

## Runtime Engine (Current — Production)

### Components

| Component | Technology | Status |
|-----------|-----------|--------|
| NER Model | XLM-RoBERTa-base, ONNX INT8 (265MB) | Production |
| Regex Engine | 7 compiled patterns (CF, IBAN, email, phone, P.IVA, PEC, SDI) | Production |
| Span Fusion | Deterministic trim + merge + overlap resolution | Production |
| Crypto | AES-256-GCM envelope encryption (KEK → DEK → PII) | Production |
| Vault | Redis (zero persistence, password auth, localhost only) | Production |
| API Auth | API key (SHA-256 hashed, per-key rate limiting) | Production |
| Admin Auth | Admin key (X-Admin-Key header, rate limited) | Production |
| Transport | Nginx + mTLS (TLS 1.3, client cert required) | Production |

### API Endpoints (Runtime)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /api/v1/tokenize | API key | Detect PII and replace with tokens |
| POST | /api/v1/rehydrate | API key | Restore original values from tokens |
| POST | /api/v1/flush | API key | Delete all vault entries for a request |
| POST | /api/v1/keys | Admin key | Create new API key |
| DELETE | /api/v1/keys/{hash} | Admin key | Revoke API key |
| GET | /api/v1/keys | Admin key | List keys |
| GET | /api/v1/usage/{org_id} | Admin key | Monthly usage stats |
| POST | /api/v1/rotate-dek | Admin key | Rotate org encryption key |
| GET | /health | Public | Service health check |
| GET | /metrics | Admin key | In-memory metrics |

### Performance (Hetzner VPS, 2vCPU/4GB)

| Metric | Value |
|--------|-------|
| Latency (warm) | 70-90ms |
| Throughput | ~12 req/s |
| Model RAM | ~680MB |
| Total RAM used | ~1.2GB / 3.7GB |
| Model size (disk) | 265MB |

### Security

| Layer | Protection |
|-------|-----------|
| Network | Nginx reverse proxy, UFW deny-all, port 8000 localhost only |
| Transport | TLS 1.3, mTLS (client cert required), HSTS |
| Auth | API key (SHA-256), admin rate limiting (10/min/IP) |
| Crypto | AES-256-GCM, envelope encryption, per-org DEK |
| Process | Non-root user (pii), systemd hardening, core dumps disabled |
| Data | Zero persistence Redis, TTL on vault entries, flush on request |

## Platform Layer (Next — Planned)

### User & Auth

- Email/password registration
- OAuth (Google, GitHub)
- Email verification
- Password reset
- Session management (JWT or session cookies)
- 2FA (TOTP) for enterprise plans

### Organization Management

- Create org on signup (personal org by default)
- Invite team members (admin/member roles)
- Org settings (name, billing email, plan)
- Transfer ownership

### API Key Self-Service

- Generate keys from dashboard (live + test environments)
- View active keys (masked, show last 4 chars)
- Revoke keys
- Set per-key labels/descriptions
- Key usage statistics

### Plans & Billing

| Plan | Rate Limit | Monthly Tokens | Price |
|------|-----------|---------------|-------|
| Free | 10/min | 1,000 | €0 |
| Developer | 60/min | 50,000 | €19/mo |
| Business | 200/min | 500,000 | €79/mo |
| Enterprise | Custom | Custom | Custom |

- Stripe integration for payments
- Usage-based billing (overage charges)
- Invoice generation
- Plan upgrade/downgrade

### Dashboard

- Usage graphs (daily/monthly)
- API key management
- Org settings
- Billing & invoices
- API documentation (interactive)
- Logs viewer (recent API calls, no PII shown)

## Data Model

```
users
  ├── id (UUID)
  ├── email
  ├── password_hash
  ├── name
  ├── verified (bool)
  ├── created_at
  └── last_login_at

organizations
  ├── id (UUID)
  ├── name
  ├── slug
  ├── owner_id → users
  ├── plan_id → plans
  ├── stripe_customer_id
  ├── created_at
  └── deleted_at

org_members
  ├── org_id → organizations
  ├── user_id → users
  ├── role (admin | member)
  └── joined_at

plans
  ├── id
  ├── name (free | developer | business | enterprise)
  ├── rate_limit_per_minute
  ├── monthly_token_limit
  ├── price_cents
  └── features (JSONB)

api_keys
  ├── id (UUID)
  ├── org_id → organizations
  ├── key_hash (SHA-256, indexed)
  ├── key_prefix (ps_live_ / ps_test_, last 4 chars for display)
  ├── label
  ├── environment (live | test)
  ├── active (bool)
  ├── created_by → users
  ├── created_at
  └── revoked_at

usage_daily
  ├── org_id → organizations
  ├── date
  ├── tokenize_calls
  ├── rehydrate_calls
  ├── flush_calls
  ├── tokens_created
  └── detection_ms_total
```

## Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Runtime API | Python + FastAPI | Already in production, async, fast |
| NER Model | ONNX Runtime | No PyTorch dependency, INT8 quantized |
| Vault | Redis | Ephemeral by design, fast, TTL native |
| Platform API | Python + FastAPI or Node.js | TBD — depends on dashboard stack |
| Dashboard | Next.js or SvelteKit | TBD |
| Database | Supabase (PostgreSQL) | Already used by SNAP, auth built-in |
| Payments | Stripe | Industry standard |
| Hosting (Runtime) | Hetzner VPS | Current, 2vCPU/4GB, €3.65/mo |
| Hosting (Platform) | Vercel or same VPS | TBD |
| Domain | privacyshield.pro | Active, DNS configured |

## Repository Structure

```
privacy-shield/
  app/                    # Runtime engine (production)
    domain/               #   Entities, ports, services
    application/          #   Use cases (tokenize, rehydrate, flush)
    infrastructure/       #   Adapters (Redis, crypto, regex, NER, API)
    main.py               #   FastAPI entry point
  platform/               # Platform layer (planned)
    auth/                 #   User auth, session management
    billing/              #   Stripe integration, metering
    dashboard/            #   Web frontend
    api/                  #   Platform API routes
  training/               # ML pipeline (development)
    dataset/              #   Data pipeline
    training/             #   Training scripts
    inference/            #   Inference engine (Python, for eval)
    eval/                 #   Evaluation & benchmarks
    export/               #   ONNX export & quantization
  tests/                  # Span fusion tests
  tests_app/              # Runtime engine tests (498 tests)
  docs/                   # This directory
```

## Milestones

| # | Milestone | Status | Target |
|---|-----------|--------|--------|
| 1 | Runtime engine (NER + Regex + Vault) | ✅ Done | — |
| 2 | Production deployment (Hetzner + mTLS) | ✅ Done | — |
| 3 | Security hardening (red team passed) | ✅ Done | — |
| 4 | SNAP Framework integration (mTLS adapter) | ✅ Done | — |
| 5 | Admin CLI for org/key management | Next | Sprint 1 |
| 6 | Platform API (user auth, self-service keys) | Planned | Sprint 2 |
| 7 | Dashboard MVP (usage, keys, settings) | Planned | Sprint 3 |
| 8 | Stripe billing integration | Planned | Sprint 4 |
| 9 | Browser extension | Planned | Sprint 5 |
| 10 | SDKs (Python, JS) | Planned | Sprint 6 |
