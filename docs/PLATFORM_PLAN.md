# Privacy Shield — Platform Layer Plan

> Status: Planning
> Priority: High — required before second SaaS onboarding

## Problem Statement

Privacy Shield runtime is production-ready but operates as an internal service managed via admin CLI. To scale to multiple SaaS clients and direct users, we need a self-service platform layer with user accounts, API key management, billing, and a dashboard.

## Target Users

### 1. SaaS Platforms (via SNAP Framework)
- Materic.ai (construction/HVAC ERP) — **active**
- 4 more SaaS planned
- Each SaaS = one org on PS
- Each org's end-users are transparent to PS (SNAP handles user management)
- Need: API key, rate limits per plan, usage metering, billing

### 2. Direct API Users
- Developers integrating PII detection in their apps
- Small businesses processing documents
- Need: self-service signup, API key generation, documentation, pay-as-you-go

### 3. Browser Extension Users
- Individual users protecting PII in web forms, emails, documents
- Need: account, API key (auto-generated), simple UI, free tier

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  privacyshield.pro                        │
│                                                          │
│  ┌──────────────────────────────────────────────┐       │
│  │           Next.js Frontend                    │       │
│  │  /              → Landing page                │       │
│  │  /login         → Auth (Supabase Auth)        │       │
│  │  /signup        → Registration                │       │
│  │  /dashboard     → Usage, keys, settings       │       │
│  │  /docs          → API documentation           │       │
│  │  /pricing       → Plans                       │       │
│  └──────────────────┬───────────────────────────┘       │
│                     │                                    │
│  ┌──────────────────▼───────────────────────────┐       │
│  │         Platform API (Supabase Edge Functions │       │
│  │         or FastAPI on same VPS)               │       │
│  │                                               │       │
│  │  POST /auth/signup                            │       │
│  │  POST /auth/login                             │       │
│  │  GET  /orgs                                   │       │
│  │  POST /orgs/{id}/keys                         │       │
│  │  GET  /orgs/{id}/usage                        │       │
│  │  POST /billing/checkout                       │       │
│  │  POST /billing/webhook (Stripe)               │       │
│  └──────────────────┬───────────────────────────┘       │
│                     │                                    │
│  ┌──────────────────▼───────────────────────────┐       │
│  │         Supabase (PostgreSQL)                 │       │
│  │  - users (via Supabase Auth)                  │       │
│  │  - organizations                              │       │
│  │  - org_members                                │       │
│  │  - plans                                      │       │
│  │  - api_keys (metadata only, hash indexed)     │       │
│  │  - usage_daily                                │       │
│  │  - subscriptions                              │       │
│  │  - invoices                                   │       │
│  └──────────────────────────────────────────────┘       │
│                                                          │
│  ┌──────────────────────────────────────────────┐       │
│  │         api.privacyshield.pro                 │       │
│  │         (Runtime Engine — existing)            │       │
│  │         Unchanged — receives API key + org_id  │       │
│  └──────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. Auth: Supabase Auth
- Already in the tech stack (SNAP uses Supabase)
- Email/password + OAuth (Google, GitHub) out of the box
- JWT tokens for session management
- Row Level Security (RLS) for data isolation

### 2. API Key Flow
User creates key from dashboard → Platform API generates key → calls PS Runtime admin endpoint → stores metadata in Supabase → returns raw key once to user.

The raw key is shown ONCE. User must copy it. We store only the SHA-256 hash. This is the same pattern as Stripe, OpenAI, etc.

### 3. Billing: Stripe
- Checkout Sessions for subscription creation
- Webhooks for payment events
- Usage-based billing via Stripe Metering API
- Daily cron job: read PS `/api/v1/usage/{org_id}` → report to Stripe

### 4. Runtime Engine Unchanged
The PS runtime on Hetzner stays exactly as-is. The platform layer is a separate service that:
- Manages users, orgs, plans in Supabase
- Proxies key creation/revocation to PS runtime admin endpoint
- Reads usage data from PS runtime for billing
- Does NOT handle PII data (that stays in the runtime)

## Database Schema (Supabase)

```sql
-- Plans
CREATE TABLE ps_plans (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  display_name TEXT NOT NULL,
  rate_limit_per_minute INT NOT NULL,
  monthly_token_limit INT NOT NULL,
  price_cents INT NOT NULL,
  stripe_price_id TEXT,
  features JSONB DEFAULT '{}',
  active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO ps_plans VALUES
  ('free',       'Free',       'Free',       10,   1000,     0,    NULL, '{}', true, now()),
  ('developer',  'Developer',  'Developer',  60,   50000,    1900, NULL, '{}', true, now()),
  ('business',   'Business',   'Business',   200,  500000,   7900, NULL, '{}', true, now()),
  ('enterprise', 'Enterprise', 'Enterprise', 1000, 5000000,  0,    NULL, '{}', true, now());

-- Organizations (extends Supabase Auth users)
CREATE TABLE ps_organizations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  owner_id UUID NOT NULL REFERENCES auth.users(id),
  plan_id TEXT NOT NULL REFERENCES ps_plans(id) DEFAULT 'free',
  stripe_customer_id TEXT,
  stripe_subscription_id TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

-- Org members
CREATE TABLE ps_org_members (
  org_id UUID NOT NULL REFERENCES ps_organizations(id),
  user_id UUID NOT NULL REFERENCES auth.users(id),
  role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('admin', 'member')),
  joined_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (org_id, user_id)
);

-- API keys (metadata — raw key never stored)
CREATE TABLE ps_api_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES ps_organizations(id),
  key_hash TEXT NOT NULL UNIQUE,
  key_prefix TEXT NOT NULL,  -- "ps_live_...abc" (last 4 for display)
  label TEXT DEFAULT '',
  environment TEXT NOT NULL DEFAULT 'live' CHECK (environment IN ('live', 'test')),
  rate_limit_per_minute INT,  -- NULL = use plan default
  active BOOLEAN DEFAULT true,
  created_by UUID REFERENCES auth.users(id),
  created_at TIMESTAMPTZ DEFAULT now(),
  revoked_at TIMESTAMPTZ
);

-- Daily usage (aggregated from PS runtime)
CREATE TABLE ps_usage_daily (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES ps_organizations(id),
  date DATE NOT NULL,
  tokenize_calls INT DEFAULT 0,
  rehydrate_calls INT DEFAULT 0,
  flush_calls INT DEFAULT 0,
  tokens_created INT DEFAULT 0,
  detection_ms_total DOUBLE PRECISION DEFAULT 0,
  UNIQUE (org_id, date)
);
```

## API Endpoints (Platform Layer)

### Auth
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /auth/signup | None | Create account |
| POST | /auth/login | None | Login, get JWT |
| POST | /auth/logout | JWT | Invalidate session |
| POST | /auth/reset-password | None | Send reset email |
| GET | /auth/me | JWT | Current user info |

### Organizations
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /orgs | JWT | Create organization |
| GET | /orgs | JWT | List user's orgs |
| GET | /orgs/{id} | JWT + member | Org details |
| PATCH | /orgs/{id} | JWT + admin | Update org |
| POST | /orgs/{id}/members | JWT + admin | Invite member |

### API Keys
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /orgs/{id}/keys | JWT + admin | Create API key |
| GET | /orgs/{id}/keys | JWT + member | List keys (masked) |
| DELETE | /orgs/{id}/keys/{key_id} | JWT + admin | Revoke key |

### Usage & Billing
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /orgs/{id}/usage | JWT + member | Usage stats |
| GET | /orgs/{id}/usage/daily | JWT + member | Daily breakdown |
| POST | /billing/checkout | JWT + admin | Create Stripe checkout |
| POST | /billing/webhook | Stripe signature | Handle payment events |
| GET | /billing/invoices | JWT + admin | Invoice history |

## Implementation Sprints

### Sprint 1: Admin CLI (Immediate)
- CLI tool for org/key management (replaces manual curl)
- Automated provisioning script
- Usage export command
- **Output**: Materic.ai and future SaaS can be onboarded via script

### Sprint 2: Platform API + Auth (1 week)
- Supabase project setup (or reuse existing)
- User registration/login via Supabase Auth
- Org CRUD
- API key self-service (create/list/revoke)
- Key creation proxies to PS runtime admin endpoint

### Sprint 3: Dashboard MVP (1 week)
- Next.js app on privacyshield.pro
- Login/signup pages
- Dashboard: usage graph, active keys, org settings
- API key creation flow (show once, copy)
- Responsive (mobile-friendly for quick checks)

### Sprint 4: Billing (1 week)
- Stripe integration
- Plan selection during signup
- Checkout flow
- Webhook handler for payment events
- Daily usage → Stripe metering sync
- Invoice page

### Sprint 5: Browser Extension (2 weeks)
- Chrome extension
- Firefox extension
- Uses user's API key
- Right-click → "Detect PII" on selected text
- Auto-detect PII in form fields (optional)

### Sprint 6: SDKs (1 week)
- Python SDK (`pip install privacy-shield`)
- JavaScript SDK (`npm install @privacyshield/sdk`)
- Auto-generated from OpenAPI spec

## Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Dashboard latency | < 500ms page load |
| API key creation | < 2s end-to-end |
| Uptime | 99.9% (runtime engine) |
| Data retention | PII tokens: TTL 60s. Usage data: 2 years |
| GDPR compliance | PII never stored permanently. User data deletion on request |
| Audit trail | All admin actions logged |
