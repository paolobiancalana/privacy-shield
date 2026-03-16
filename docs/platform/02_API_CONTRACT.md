# Platform Layer — API Contract

> Every endpoint, request, response, error code defined. No ambiguity.

## Base URLs

| Service | URL | Auth |
|---------|-----|------|
| Platform API (Next.js) | https://privacyshield.pro/api/ | Supabase JWT |
| Runtime API | https://api.privacyshield.pro/api/v1/ | mTLS + API key |

## Platform API Endpoints

All platform endpoints require a Supabase JWT in the `Authorization: Bearer {token}` header unless marked as "Public".

### Auth

Auth is handled entirely by Supabase Auth SDK on the frontend. No custom auth endpoints needed. The Next.js middleware validates the JWT and injects the user context.

### POST /api/orgs

Create a new organization.

```
Request:
{
  "name": "Materic.ai",
  "slug": "materic"    // lowercase, alphanumeric + hyphens, unique
}

Response 201:
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Materic.ai",
  "slug": "materic",
  "plan_id": "free",
  "created_at": "2026-03-16T12:00:00Z"
}

Errors:
  400 — slug already taken
  401 — not authenticated
```

Side effects:
- Creates org in ps_organizations
- Adds current user as owner in ps_org_members

### GET /api/orgs

List organizations the current user belongs to.

```
Response 200:
{
  "organizations": [
    {
      "id": "...",
      "name": "Materic.ai",
      "slug": "materic",
      "plan_id": "business",
      "role": "owner",
      "created_at": "..."
    }
  ]
}
```

### GET /api/orgs/{org_id}

Get organization details. User must be a member.

```
Response 200:
{
  "id": "...",
  "name": "Materic.ai",
  "slug": "materic",
  "plan": {
    "id": "business",
    "display_name": "Business",
    "rate_limit_per_minute": 200,
    "monthly_token_limit": 500000,
    "price_cents": 7900
  },
  "members": [
    { "user_id": "...", "email": "paolo@materic.ai", "role": "owner" }
  ],
  "usage_this_month": {
    "tokenize_calls": 1234,
    "tokens_created": 5678,
    "limit": 500000,
    "percent_used": 1.1
  },
  "created_at": "..."
}

Errors:
  403 — not a member of this org
  404 — org not found
```

### POST /api/orgs/{org_id}/keys

Create a new API key. User must be admin or owner.

```
Request:
{
  "label": "production-server",
  "environment": "live"         // "live" | "test"
}

Response 201:
{
  "key": "ps_live_a1b2c3d4e5f6789012345678abcdef01",  // SHOWN ONCE
  "key_id": "550e8400-...",
  "key_prefix": "ps_live_...ef01",
  "label": "production-server",
  "environment": "live",
  "created_at": "2026-03-16T12:00:00Z"
}

Errors:
  400 — key limit reached for plan (free=2, dev=5, biz=20, ent=100)
  403 — not admin/owner
```

Implementation:
1. Validate membership + role
2. Check key count vs plan limit
3. Call PS Runtime: POST /api/v1/keys (admin)
4. Store hash + metadata in ps_api_keys
5. Return raw key ONCE

### GET /api/orgs/{org_id}/keys

List API keys (masked). User must be a member.

```
Response 200:
{
  "keys": [
    {
      "id": "...",
      "key_prefix": "ps_live_...ef01",
      "label": "production-server",
      "environment": "live",
      "active": true,
      "created_at": "2026-03-16T12:00:00Z",
      "last_used_at": "2026-03-16T14:30:00Z"
    }
  ]
}
```

### DELETE /api/orgs/{org_id}/keys/{key_id}

Revoke an API key. User must be admin or owner.

```
Response 200:
{
  "revoked": true,
  "key_id": "..."
}

Errors:
  403 — not admin/owner
  404 — key not found or already revoked
```

Implementation:
1. Load key from Supabase
2. Call PS Runtime: DELETE /api/v1/keys/{runtime_key_id} (admin)
3. Mark key as revoked in Supabase

### GET /api/orgs/{org_id}/usage

Usage statistics. User must be a member.

```
Query params:
  period: "7d" | "30d" | "90d" (default: "30d")

Response 200:
{
  "org_id": "...",
  "period": "30d",
  "summary": {
    "tokenize_calls": 12345,
    "rehydrate_calls": 11000,
    "tokens_created": 45678,
    "monthly_limit": 500000,
    "percent_used": 9.1
  },
  "daily": [
    {
      "date": "2026-03-15",
      "tokenize_calls": 456,
      "tokens_created": 1234
    },
    ...
  ]
}
```

### POST /api/billing/checkout

Create a Stripe Checkout Session. User must be admin/owner.

```
Request:
{
  "org_id": "...",
  "plan_id": "business"
}

Response 200:
{
  "checkout_url": "https://checkout.stripe.com/c/pay/..."
}
```

### POST /api/billing/webhook

Stripe webhook handler. Auth: Stripe signature verification.

```
Headers:
  Stripe-Signature: t=...,v1=...

Events handled:
  checkout.session.completed → update org plan + stripe IDs
  customer.subscription.updated → sync plan changes
  customer.subscription.deleted → downgrade to free
  invoice.payment_failed → log warning (email notification future)
```

### GET /api/billing/invoices/{org_id}

Invoice history. User must be admin/owner.

```
Response 200:
{
  "invoices": [
    {
      "id": "in_xxx",
      "date": "2026-03-01",
      "amount_cents": 7900,
      "status": "paid",
      "pdf_url": "https://pay.stripe.com/..."
    }
  ]
}
```

## Error Response Format (All Endpoints)

```json
{
  "error": "Human-readable message",
  "code": "MACHINE_READABLE_CODE",
  "detail": null | "additional context"
}
```

Standard codes:
- `AUTH_REQUIRED` (401)
- `FORBIDDEN` (403)
- `NOT_FOUND` (404)
- `VALIDATION_ERROR` (422)
- `RATE_LIMITED` (429)
- `INTERNAL_ERROR` (500)
- `PLAN_LIMIT_REACHED` (400)
- `KEY_ALREADY_REVOKED` (400)
