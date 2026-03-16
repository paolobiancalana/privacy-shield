import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { getStripe } from "@/lib/stripe/client";

// Map plan_id to Stripe price IDs.
// These must match the price IDs in your Stripe dashboard and can be
// overridden via environment variables for easy staging/production switching.
const STRIPE_PRICE_IDS: Record<string, string | undefined> = {
  developer: process.env.STRIPE_PRICE_ID_DEVELOPER,
  business: process.env.STRIPE_PRICE_ID_BUSINESS,
  enterprise: process.env.STRIPE_PRICE_ID_ENTERPRISE,
};

export async function POST(request: Request) {
  const supabase = await createClient();

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return NextResponse.json(
      { error: "Not authenticated", code: "AUTH_REQUIRED" },
      { status: 401 }
    );
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error: "Invalid JSON body", code: "VALIDATION_ERROR" },
      { status: 422 }
    );
  }

  const { org_id, plan_id } = body as Record<string, unknown>;

  if (!org_id || typeof org_id !== "string") {
    return NextResponse.json(
      { error: "org_id is required", code: "VALIDATION_ERROR" },
      { status: 422 }
    );
  }

  if (!plan_id || typeof plan_id !== "string") {
    return NextResponse.json(
      { error: "plan_id is required", code: "VALIDATION_ERROR" },
      { status: 422 }
    );
  }

  const stripePriceId = STRIPE_PRICE_IDS[plan_id];

  if (!stripePriceId) {
    return NextResponse.json(
      {
        error: `plan_id "${plan_id}" is not available for purchase. Valid options: developer, business, enterprise`,
        code: "VALIDATION_ERROR",
      },
      { status: 422 }
    );
  }

  // Verify user is a member of the org (owner or admin can initiate billing)
  const { data: membership, error: membershipError } = await supabase
    .from("ps_org_members")
    .select("role")
    .eq("org_id", org_id)
    .eq("user_id", user.id)
    .maybeSingle();

  if (membershipError) {
    console.error("Failed to verify org membership for checkout", {
      userId: user.id,
      orgId: org_id,
      error: membershipError.message,
    });
    return NextResponse.json(
      { error: "Failed to initiate checkout", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  if (!membership) {
    return NextResponse.json(
      { error: "Organization not found", code: "NOT_FOUND" },
      { status: 404 }
    );
  }

  if (!["owner", "admin"].includes(membership.role)) {
    return NextResponse.json(
      {
        error: "Only owners and admins can manage billing",
        code: "FORBIDDEN",
      },
      { status: 403 }
    );
  }

  // Fetch org to get or create Stripe customer
  const { data: org, error: orgError } = await supabase
    .from("ps_organizations")
    .select("id, name, slug, stripe_customer_id")
    .eq("id", org_id)
    .single();

  if (orgError || !org) {
    console.error("Failed to fetch org for checkout", {
      userId: user.id,
      orgId: org_id,
      error: orgError?.message,
    });
    return NextResponse.json(
      { error: "Organization not found", code: "NOT_FOUND" },
      { status: 404 }
    );
  }

  let stripeCustomerId = org.stripe_customer_id as string | null;

  // Create a Stripe customer if one does not exist yet
  if (!stripeCustomerId) {
    try {
      const customer = await getStripe().customers.create({
        name: org.name,
        email: user.email,
        metadata: {
          org_id: org.id,
          org_slug: org.slug,
        },
      });

      stripeCustomerId = customer.id;

      // Persist the customer ID so future operations reuse it
      const { error: updateError } = await supabase
        .from("ps_organizations")
        .update({ stripe_customer_id: stripeCustomerId })
        .eq("id", org_id);

      if (updateError) {
        console.error("Failed to persist Stripe customer ID", {
          userId: user.id,
          orgId: org_id,
          stripeCustomerId,
          error: updateError.message,
        });
        // Non-fatal — proceed; the customer ID will be captured via webhook
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      console.error("Failed to create Stripe customer", {
        userId: user.id,
        orgId: org_id,
        error: message,
      });
      return NextResponse.json(
        { error: "Failed to initiate checkout", code: "INTERNAL_ERROR" },
        { status: 500 }
      );
    }
  }

  const appUrl = process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000";

  // Create the Stripe Checkout session
  try {
    const session = await getStripe().checkout.sessions.create({
      customer: stripeCustomerId,
      mode: "subscription",
      line_items: [
        {
          price: stripePriceId,
          quantity: 1,
        },
      ],
      metadata: {
        org_id: org.id,
        plan_id,
      },
      subscription_data: {
        metadata: {
          org_id: org.id,
          plan_id,
        },
      },
      success_url: `${appUrl}/dashboard/billing?checkout=success&session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${appUrl}/dashboard/billing?checkout=canceled`,
      allow_promotion_codes: true,
    });

    return NextResponse.json({ checkout_url: session.url }, { status: 200 });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error("Failed to create Stripe checkout session", {
      userId: user.id,
      orgId: org_id,
      planId: plan_id,
      error: message,
    });
    return NextResponse.json(
      { error: "Failed to initiate checkout", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }
}
