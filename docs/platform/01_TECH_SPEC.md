# Platform Layer — Technical Specification

> This document is the single source of truth for implementing the Privacy Shield Platform Layer.
> An AI agent implementing this spec should follow it exactly without deviation.

## Stack Decision (Final)

| Component | Technology | Version | Rationale |
|-----------|-----------|---------|-----------|
| Frontend | Next.js (App Router) | 15+ | SSR, API routes, TypeScript native |
| Auth | Supabase Auth | Latest | Already in tech stack, RLS, OAuth |
| Database | Supabase PostgreSQL | Latest | Shared with SNAP ecosystem, RLS |
| Payments | Stripe | API v2024+ | Subscriptions + usage metering |
| Hosting (frontend) | Vercel | Free tier initially | Native Next.js, auto-deploy from git |
| Hosting (platform API) | Same Hetzner VPS | — | Co-located with runtime, no latency |
| CSS | Tailwind CSS | 4+ | Utility-first, dark mode |
| UI Components | shadcn/ui | Latest | Accessible, composable, no bundle bloat |

## Directory Structure (Final)

```
privacy-shield/
  platform/                         # NEW — all platform code here
    web/                            # Next.js frontend
      app/
        (auth)/
          login/page.tsx
          signup/page.tsx
          reset-password/page.tsx
        (dashboard)/
          layout.tsx                # Sidebar + header
          page.tsx                  # Overview (redirect to /usage)
          usage/page.tsx            # Usage graphs
          keys/page.tsx             # API key management
          settings/page.tsx         # Org settings
          billing/page.tsx          # Plan + invoices
        (marketing)/
          page.tsx                  # Landing page (replaces static HTML)
          pricing/page.tsx
          docs/page.tsx             # API documentation
        api/
          billing/webhook/route.ts  # Stripe webhook handler
        layout.tsx                  # Root layout
        globals.css
      lib/
        supabase/
          client.ts                # Browser Supabase client
          server.ts                # Server-side Supabase client
          middleware.ts            # Auth middleware
        stripe/
          client.ts                # Stripe SDK instance
          plans.ts                 # Plan definitions
        ps-admin/
          client.ts                # HTTP client to PS runtime admin endpoints
      components/
        ui/                        # shadcn/ui components
        dashboard/
          usage-chart.tsx
          key-card.tsx
          key-create-dialog.tsx
          plan-badge.tsx
      package.json
      next.config.ts
      tailwind.config.ts
      tsconfig.json

    api/                            # Platform API (FastAPI on VPS)
      main.py                      # FastAPI app
      routes/
        keys.py                    # Key provisioning (proxies to PS runtime)
        usage.py                   # Usage aggregation
        billing.py                 # Stripe webhook + checkout
      services/
        key_provisioning.py        # Creates key on PS runtime, stores hash in Supabase
        usage_sync.py              # Daily cron: PS runtime → Supabase usage_daily
        billing_sync.py            # Daily cron: usage → Stripe metering
      config.py                    # Settings
      requirements.txt
```

## Supabase Schema (Exact SQL)

Execute this migration in the Supabase SQL editor. This is the COMPLETE schema — no additional tables needed.

```sql
-- ============================================================
-- Privacy Shield Platform — Database Schema
-- ============================================================

-- Plans (seeded, rarely changed)
CREATE TABLE ps_plans (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  display_name TEXT NOT NULL,
  rate_limit_per_minute INT NOT NULL DEFAULT 10,
  monthly_token_limit INT NOT NULL DEFAULT 1000,
  price_cents INT NOT NULL DEFAULT 0,
  stripe_price_id TEXT,
  features JSONB NOT NULL DEFAULT '{}',
  active BOOLEAN NOT NULL DEFAULT true,
  sort_order INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO ps_plans (id, name, display_name, rate_limit_per_minute, monthly_token_limit, price_cents, sort_order) VALUES
  ('free',       'free',       'Free',       10,   1000,     0,    0),
  ('developer',  'developer',  'Developer',  60,   50000,    1900, 1),
  ('business',   'business',   'Business',   200,  500000,   7900, 2),
  ('enterprise', 'enterprise', 'Enterprise', 1000, 5000000,  0,    3);

-- Organizations
CREATE TABLE ps_organizations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  owner_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  plan_id TEXT NOT NULL REFERENCES ps_plans(id) DEFAULT 'free',
  stripe_customer_id TEXT,
  stripe_subscription_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at TIMESTAMPTZ
);

CREATE INDEX idx_ps_organizations_owner ON ps_organizations(owner_id);
CREATE INDEX idx_ps_organizations_slug ON ps_organizations(slug);

-- Org members
CREATE TABLE ps_org_members (
  org_id UUID NOT NULL REFERENCES ps_organizations(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('owner', 'admin', 'member')),
  invited_by UUID REFERENCES auth.users(id),
  joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id, user_id)
);

-- API keys (only hash stored, never the raw key)
CREATE TABLE ps_api_keys (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES ps_organizations(id) ON DELETE CASCADE,
  key_hash TEXT NOT NULL UNIQUE,
  key_prefix TEXT NOT NULL,
  label TEXT NOT NULL DEFAULT '',
  environment TEXT NOT NULL DEFAULT 'live' CHECK (environment IN ('live', 'test')),
  runtime_key_id TEXT,  -- kid_xxx returned by PS runtime
  active BOOLEAN NOT NULL DEFAULT true,
  created_by UUID REFERENCES auth.users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  revoked_at TIMESTAMPTZ,
  last_used_at TIMESTAMPTZ
);

CREATE INDEX idx_ps_api_keys_org ON ps_api_keys(org_id);
CREATE INDEX idx_ps_api_keys_hash ON ps_api_keys(key_hash);

-- Daily usage (aggregated from PS runtime Redis counters)
CREATE TABLE ps_usage_daily (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id UUID NOT NULL REFERENCES ps_organizations(id) ON DELETE CASCADE,
  date DATE NOT NULL,
  tokenize_calls INT NOT NULL DEFAULT 0,
  rehydrate_calls INT NOT NULL DEFAULT 0,
  flush_calls INT NOT NULL DEFAULT 0,
  tokens_created INT NOT NULL DEFAULT 0,
  detection_ms_p50 DOUBLE PRECISION,
  detection_ms_p95 DOUBLE PRECISION,
  UNIQUE (org_id, date)
);

CREATE INDEX idx_ps_usage_daily_org_date ON ps_usage_daily(org_id, date);

-- Row Level Security
ALTER TABLE ps_organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE ps_org_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE ps_api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE ps_usage_daily ENABLE ROW LEVEL SECURITY;

-- Policies: users can only see orgs they belong to
CREATE POLICY "Users see own orgs" ON ps_organizations
  FOR SELECT USING (
    id IN (SELECT org_id FROM ps_org_members WHERE user_id = auth.uid())
  );

CREATE POLICY "Owners can update orgs" ON ps_organizations
  FOR UPDATE USING (owner_id = auth.uid());

CREATE POLICY "Members see org members" ON ps_org_members
  FOR SELECT USING (
    org_id IN (SELECT org_id FROM ps_org_members WHERE user_id = auth.uid())
  );

CREATE POLICY "Admins manage members" ON ps_org_members
  FOR ALL USING (
    org_id IN (
      SELECT org_id FROM ps_org_members
      WHERE user_id = auth.uid() AND role IN ('owner', 'admin')
    )
  );

CREATE POLICY "Members see keys" ON ps_api_keys
  FOR SELECT USING (
    org_id IN (SELECT org_id FROM ps_org_members WHERE user_id = auth.uid())
  );

CREATE POLICY "Admins manage keys" ON ps_api_keys
  FOR ALL USING (
    org_id IN (
      SELECT org_id FROM ps_org_members
      WHERE user_id = auth.uid() AND role IN ('owner', 'admin')
    )
  );

CREATE POLICY "Members see usage" ON ps_usage_daily
  FOR SELECT USING (
    org_id IN (SELECT org_id FROM ps_org_members WHERE user_id = auth.uid())
  );

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION ps_update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ps_organizations_updated
  BEFORE UPDATE ON ps_organizations
  FOR EACH ROW EXECUTE FUNCTION ps_update_timestamp();
```

## API Key Provisioning Flow (Exact)

This is the most critical flow. The agent implementing it MUST follow these exact steps:

```
1. User clicks "Create API Key" in dashboard
2. Frontend calls: POST /api/keys (Next.js API route)
   Body: { org_id, label, environment }
   Auth: Supabase JWT (user must be admin/owner of org)

3. Next.js API route:
   a. Verify JWT and org membership (admin/owner)
   b. Check org's plan allows more keys (free = max 2, dev = 5, biz = 20)
   c. Generate raw key: "ps_{environment}_{32 hex chars}"
      Example: "ps_live_a1b2c3d4e5f6789012345678abcdef01"
   d. Compute SHA-256 hash of raw key
   e. Call PS Runtime admin endpoint:
      POST https://api.privacyshield.pro/api/v1/keys
      Headers: X-Admin-Key: {ADMIN_KEY}, + mTLS client cert
      Body: {
        "organization_id": org_id (UUID),
        "plan": org.plan_id,
        "rate_limit_per_minute": plan.rate_limit_per_minute
      }
      Response: { "key": "ps_live_xxx", "key_id": "kid_xxx", "organization_id": "..." }

      IMPORTANT: We do NOT use the key returned by PS runtime.
      We use our OWN generated key (step c) and register it separately.
      The PS runtime key is stored as runtime_key_id for revocation.

      ACTUALLY — SIMPLER APPROACH: Use the key returned by PS runtime directly.
      PS runtime generates the key, we just store the hash.

   f. Store in Supabase ps_api_keys:
      - key_hash: SHA-256 of the raw key from PS runtime
      - key_prefix: first 8 + last 4 chars (for display: "ps_live_...cdef")
      - runtime_key_id: kid_xxx from PS runtime
      - org_id, label, environment, created_by

   g. Return to frontend: { raw_key: "ps_live_xxx" } (shown ONCE)

4. Frontend shows raw key in a modal with copy button and warning:
   "This key will not be shown again. Copy it now."
```

## Key Revocation Flow (Exact)

```
1. User clicks "Revoke" on a key in dashboard
2. Frontend calls: DELETE /api/keys/{key_id}
3. API route:
   a. Verify JWT + admin/owner
   b. Load key from Supabase (get runtime_key_id)
   c. Call PS Runtime: DELETE /api/v1/keys/{runtime_key_id}
      Headers: X-Admin-Key + mTLS
   d. Update Supabase: active = false, revoked_at = now()
   e. Return 200
```

## Usage Sync (Exact)

A cron job runs daily at 02:00 UTC:

```
1. For each active org in ps_organizations:
   a. Call PS Runtime: GET /api/v1/usage/{org_id}
      Headers: X-Admin-Key + mTLS
      Response: { org_id, month, tokenize_calls, rehydrate_calls, ... }

   b. UPSERT into ps_usage_daily:
      - org_id, date = today
      - values from PS runtime response

   c. If Stripe billing enabled:
      - Report usage to Stripe Metering API
      - stripe.billing.meter_events.create({
          event_name: 'ps_tokens',
          payload: { value: tokens_created, stripe_customer_id: org.stripe_customer_id }
        })
```

## Stripe Integration (Exact)

### Checkout Flow
```
1. User selects plan on /pricing
2. Frontend calls: POST /api/billing/checkout
   Body: { plan_id, org_id }
3. API creates Stripe Checkout Session:
   - line_items: [{ price: plan.stripe_price_id, quantity: 1 }]
   - customer: org.stripe_customer_id (create if null)
   - success_url: /dashboard/billing?success=true
   - cancel_url: /pricing
4. Return: { checkout_url } → frontend redirects

### Webhook Handler
POST /api/billing/webhook
- Verify Stripe signature (STRIPE_WEBHOOK_SECRET)
- Handle events:
  - checkout.session.completed → update org.plan_id, stripe_subscription_id
  - customer.subscription.updated → update plan_id if changed
  - customer.subscription.deleted → downgrade to 'free'
  - invoice.payment_failed → send email notification (future)
```

## Environment Variables (Platform)

```bash
# Supabase
NEXT_PUBLIC_SUPABASE_URL=https://xxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbG...
SUPABASE_SERVICE_ROLE_KEY=eyJhbG...  # Server-side only

# Stripe
STRIPE_SECRET_KEY=sk_live_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_live_xxx

# PS Runtime Admin
PS_RUNTIME_URL=https://api.privacyshield.pro
PS_ADMIN_KEY=<admin key from /opt/pii/.env>
PS_CLIENT_CERT_PATH=/path/to/snap-client.crt
PS_CLIENT_KEY_PATH=/path/to/snap-client.key
PS_CA_CERT_PATH=/path/to/ca.crt
```

## Pages Specification

### Landing Page (/)
- Hero: "PII Detection API for developers"
- Stats: 10 PII types, <80ms latency, 99.9% uptime
- Features grid (3 columns)
- Pricing section (link to /pricing)
- CTA: "Get Started Free" → /signup

### Signup (/signup)
- Email + password form
- OR OAuth (Google, GitHub)
- On success: create personal org (name = user name, slug = username)
- Redirect to /dashboard

### Login (/login)
- Email + password
- OR OAuth
- "Forgot password?" link

### Dashboard Layout
- Left sidebar: Usage, API Keys, Settings, Billing, Docs
- Top: org switcher (if user has multiple orgs), user avatar/menu
- Main content area

### Usage (/dashboard/usage)
- Date range selector (7d, 30d, 90d)
- Line chart: daily tokenize calls
- Bar chart: tokens created per day
- Summary cards: total calls this month, total tokens, avg latency
- Table: daily breakdown

### API Keys (/dashboard/keys)
- "Create Key" button → dialog
- Table of keys: prefix, label, environment, created, status, actions
- Revoke button (with confirmation)
- Empty state: "No keys yet. Create one to start using the API."

### Settings (/dashboard/settings)
- Org name, slug (editable by owner)
- Team members list (invite, remove, change role)
- Danger zone: delete org

### Billing (/dashboard/billing)
- Current plan badge
- Usage vs limit bar
- "Upgrade" button → Stripe checkout
- Invoice history table

### Pricing (/pricing)
- 4 plan cards (Free, Developer, Business, Enterprise)
- Feature comparison table
- "Get Started" buttons → /signup or Stripe checkout

### API Docs (/docs)
- OpenAPI-generated interactive documentation
- Or: static MDX pages with code examples in Python, JavaScript, curl
```

## Implementation Order (Non-Negotiable)

1. Supabase migration (run SQL above)
2. Next.js project scaffolding (`npx create-next-app@latest platform/web`)
3. Supabase Auth integration (signup, login, session)
4. Org creation on signup
5. Dashboard layout + usage page (read from Supabase)
6. API key management (create, list, revoke)
7. PS Runtime proxy (key creation calls PS admin endpoint)
8. Stripe integration (checkout, webhook, plan change)
9. Usage sync cron job
10. Landing page + pricing page
11. API docs page
