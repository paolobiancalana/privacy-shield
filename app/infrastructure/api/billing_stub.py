# app/infrastructure/api/billing_stub.py
"""
Billing stub endpoints for the Privacy Shield plan system.

These endpoints are placeholders for future Stripe integration. All routes
return 501 Not Implemented to signal that billing is not yet configured,
while establishing the correct URL shape for clients to code against.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse

from app.infrastructure.api.auth import require_admin_key

billing_router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


@billing_router.post("/webhook")
async def billing_webhook(
    stripe_signature: str | None = Header(default=None, alias="stripe-signature"),
) -> JSONResponse:
    """
    Stripe webhook receiver placeholder.

    This endpoint will eventually handle Stripe event notifications
    (invoice.paid, customer.subscription.updated, etc.) to keep org plans
    in sync with Stripe subscription state.

    Not yet implemented — returns 501.
    Any future implementation MUST verify the stripe-signature header
    against the webhook signing secret.
    """
    if stripe_signature is None:
        raise HTTPException(status_code=400, detail="Missing stripe-signature header")
    return JSONResponse(
        status_code=501,
        content={"error": "Billing not yet configured", "code": "NOT_IMPLEMENTED"},
    )


@billing_router.post("/checkout", dependencies=[Depends(require_admin_key)])
async def billing_checkout() -> JSONResponse:
    """
    Stripe checkout session creation placeholder.

    This endpoint will eventually create a Stripe Checkout Session for
    upgrading or downgrading an org's plan.

    Not yet implemented — returns 501.
    Requires X-Admin-Key header.
    """
    return JSONResponse(
        status_code=501,
        content={"error": "Billing not yet configured", "code": "NOT_IMPLEMENTED"},
    )
