# Privacy Shield Plan System

> Last updated: 2026-03-17

## Overview

The Plan System governs per-organization resource limits, rate throttling, and billing readiness for the Privacy Shield microservice. It introduces four immutable tiers (free, starter, business, enterprise) and enforces three constraints at runtime:

1. **Monthly token quota** -- calendar-month cap on tokens created via `/api/v1/tokenize`.
2. **Max API keys** -- hard limit on active keys per organization.
3. **Per-key rate limit** -- requests per minute, derived from the org's plan (not from the caller).

All enforcement is organization-scoped. An organization without an explicit plan assignment defaults to `free`.


## Plan Tiers

| Field | Free | Starter | Business | Enterprise |
|---|---|---|---|---|
| `id` | `free` | `starter` | `business` | `enterprise` |
| `rate_limit_per_minute` | 10 | 60 | 200 | 1,000 |
| `monthly_token_limit` | 1,000 | 50,000 | 500,000 | -1 (unlimited) |
| `max_keys` | 2 | 5 | 20 | 100 |
| `price_cents` (EUR/month) | 0 | 1,900 | 7,900 | 0 (custom billing) |

- Plans are frozen dataclasses defined at module load time in `app/domain/plans.py`.
- The sentinel value `-1` for `monthly_token_limit` means unlimited. All enforcement code checks `plan.monthly_token_limit != -1` before comparing usage.
- `price_cents = 0` on enterprise indicates custom/sales-driven billing, not "free".


## Architecture

### Hexagonal Layer Map

```
Domain                          Application                       Infrastructure
------------------------------  --------------------------------  --------------------------------
Plan (frozen dataclass)         CreateApiKeyUseCase               RedisOrgPlanAdapter
  PLANS catalog                 TokenizeTextUseCase               billing_stub.py (501 stubs)
  get_plan() / list_plans()       _check_monthly_quota()          routes.py (plan endpoints)
                                                                  schemas.py (Pydantic models)
OrgPlanPort (ABC)                                                 PrivacyShieldMetrics
  get_org_plan_id()                                                 (3 plan-specific counters)
  set_org_plan()
  get_org_plan_info()

MonthlyQuotaExceededError
MaxKeysExceededError
PlanNotFoundError
```

### Dependency Flow

```
routes.py
  |
  +-> Container
  |     |
  |     +-> CreateApiKeyUseCase(api_key_port, org_plan_port)
  |     +-> TokenizeTextUseCase(detection, vault, crypto, api_key_port, org_plan_port)
  |     +-> org_plan_port  (direct access for GET/POST /org/{id}/plan)
  |
  +-> Plan catalog (get_plan, list_plans)  -- pure domain, no DI needed
```

Both `CreateApiKeyUseCase` and `TokenizeTextUseCase` receive `OrgPlanPort` as an optional dependency. When present, plan enforcement is active. When `None`, the use cases fall back to caller-supplied `plan`/`rate_limit` parameters (backward-compatible).


## API Reference

### Public Endpoints (no auth)

#### `GET /api/v1/plans`

List all available plans.

**Response** `200 OK`
```json
[
  {
    "id": "free",
    "name": "Free",
    "rate_limit_per_minute": 10,
    "monthly_token_limit": 1000,
    "max_keys": 2,
    "price_cents": 0
  }
]
```

#### `GET /api/v1/plans/{plan_id}`

Get a single plan by ID.

**Response** `200 OK` -- single `PlanResponse` object.
**Error** `404` -- plan_id does not exist in the catalog.


### Admin Endpoints (require `X-Admin-Key`)

#### `GET /api/v1/org/{org_id}/plan`

Return the org's current plan, monthly usage, and active key count.

**Response** `200 OK`
```json
{
  "plan": { "id": "starter", "name": "Starter", "rate_limit_per_minute": 60, "monthly_token_limit": 50000, "max_keys": 5, "price_cents": 1900 },
  "usage": {
    "month": "2026-03",
    "tokenize_calls": 42,
    "rehydrate_calls": 10,
    "flush_calls": 5,
    "total_tokens_created": 1234
  },
  "active_keys": 3,
  "max_keys": 5
}
```

#### `POST /api/v1/org/{org_id}/plan`

Assign a plan to the organization.

**Request body**
```json
{
  "plan_id": "business",
  "stripe_customer_id": "cus_abc123"
}
```

**Error** `404` -- plan_id not found.
**Error** `409 Conflict` -- org has more active keys than the target plan allows.

#### `GET /api/v1/usage/{org_id}`

Monthly usage stats enriched with plan context.

**Response** `200 OK`
```json
{
  "org_id": "...",
  "month": "2026-03",
  "tokenize_calls": 42,
  "total_tokens_created": 1234,
  "plan_id": "starter",
  "plan_name": "Starter",
  "monthly_token_limit": 50000,
  "remaining_tokens": 48766,
  "percent_used": 2.47
}
```

For enterprise plans: `remaining_tokens` is `null`, `percent_used` is `0.0`.


### Modified Endpoints

#### `POST /api/v1/keys` (plan-aware)

- `plan` and `rate_limit` fields in body are **ignored** (`extra = "ignore"`).
- The org's assigned plan determines rate limit and plan label.
- **New error** `409` -- org has reached `max_keys` for its plan.

#### `POST /api/v1/tokenize` (quota-enforced)

Monthly quota check runs **before** the concurrent vault quota check.
- **New error** `429` with headers: `X-Monthly-Limit`, `X-Monthly-Used`, `X-Plan`, `Retry-After: 86400`.

### Billing Stubs (501 Not Implemented)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/v1/billing/webhook` | None | Stripe webhook receiver |
| `POST` | `/api/v1/billing/checkout` | Admin key | Stripe Checkout session |


## Enforcement Rules

### Error-to-HTTP Mapping

| Domain Error | HTTP | Detail |
|---|---|---|
| `MonthlyQuotaExceededError` | 429 | Monthly token quota exceeded |
| `QuotaExceededError` | 503 | Organization token quota exceeded |
| `MaxKeysExceededError` | 409 | Plan-specific max keys message |
| `PlanNotFoundError` | 404 | Plan not found |


## Redis Key Patterns

| Pattern | Value | TTL |
|---|---|---|
| `ps:org_plan:{org_id}` | JSON (below) | None (permanent) |

```json
{
  "plan_id": "starter",
  "stripe_customer_id": "cus_abc123",
  "assigned_at": "2026-03-17T10:30:00+00:00"
}
```

When no key exists, `get_org_plan_id()` returns `None` → defaults to `"free"`.


## Billing Readiness

| Component | Status | Work Needed |
|---|---|---|
| Plan catalog with prices | Done | -- |
| `stripe_customer_id` storage | Done | Call `stripe.customers.create()` on first paid plan |
| Checkout endpoint | 501 stub | Implement Stripe Checkout Sessions |
| Webhook handler | 501 stub | Verify signature, handle subscription events |
| Usage metering | Counters exist | Report to Stripe Usage Records |
| Downgrade protection | Key-count guard exists | Add grace period |


## Backward Compatibility

- `CreateKeyRequest` silently ignores old `plan`/`rate_limit` fields via `extra = "ignore"`.
- Use cases accept `OrgPlanPort` as optional (`None` = no enforcement). Existing tests unchanged.
- Existing API keys retain their original rate limits; plan rate limits apply only to newly created keys.
