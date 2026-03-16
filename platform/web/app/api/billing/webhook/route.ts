import { NextResponse } from "next/server";
import { createClient as createSupabaseClient } from "@supabase/supabase-js";
import { getStripe } from "@/lib/stripe/client";
import type Stripe from "stripe";

// Stripe requires the raw body for signature verification — disable Next.js
// body parsing for this route.
export const dynamic = "force-dynamic";

function getServiceClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;

  if (!url || !serviceKey) {
    throw new Error(
      "Missing NEXT_PUBLIC_SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY"
    );
  }

  return createSupabaseClient(url, serviceKey, {
    auth: { persistSession: false },
  });
}

async function handleCheckoutSessionCompleted(
  session: Stripe.Checkout.Session,
  supabase: ReturnType<typeof getServiceClient>
) {
  const orgId = session.metadata?.org_id;
  const planId = session.metadata?.plan_id;

  if (!orgId || !planId) {
    console.warn("checkout.session.completed missing metadata", {
      sessionId: session.id,
      metadata: session.metadata,
    });
    return;
  }

  const customerId =
    typeof session.customer === "string"
      ? session.customer
      : session.customer?.id ?? null;

  const subscriptionId =
    typeof session.subscription === "string"
      ? session.subscription
      : session.subscription?.id ?? null;

  const { error } = await supabase
    .from("ps_organizations")
    .update({
      plan_id: planId,
      stripe_customer_id: customerId,
      stripe_subscription_id: subscriptionId,
      updated_at: new Date().toISOString(),
    })
    .eq("id", orgId);

  if (error) {
    console.error("Failed to update org after checkout.session.completed", {
      orgId,
      planId,
      error: error.message,
    });
    throw error;
  }

  console.info("Org plan updated after checkout", { orgId, planId });
}

async function handleSubscriptionUpdated(
  subscription: Stripe.Subscription,
  supabase: ReturnType<typeof getServiceClient>
) {
  const orgId = subscription.metadata?.org_id;
  if (!orgId) {
    console.warn(
      "customer.subscription.updated missing org_id in metadata",
      { subscriptionId: subscription.id }
    );
    return;
  }

  // Derive plan_id from the price metadata or lookup table.
  // The price metadata should carry plan_id set at price creation time.
  const planId =
    subscription.items.data[0]?.price?.metadata?.plan_id ?? null;

  const updates: Record<string, unknown> = {
    stripe_subscription_id: subscription.id,
    subscription_status: subscription.status,
    updated_at: new Date().toISOString(),
  };

  if (planId) {
    updates.plan_id = planId;
  }

  const { error } = await supabase
    .from("ps_organizations")
    .update(updates)
    .eq("id", orgId);

  if (error) {
    console.error(
      "Failed to update org after customer.subscription.updated",
      { orgId, error: error.message }
    );
    throw error;
  }

  console.info("Org subscription updated", {
    orgId,
    subscriptionId: subscription.id,
    status: subscription.status,
    planId,
  });
}

async function handleSubscriptionDeleted(
  subscription: Stripe.Subscription,
  supabase: ReturnType<typeof getServiceClient>
) {
  const orgId = subscription.metadata?.org_id;
  if (!orgId) {
    console.warn(
      "customer.subscription.deleted missing org_id in metadata",
      { subscriptionId: subscription.id }
    );
    return;
  }

  const { error } = await supabase
    .from("ps_organizations")
    .update({
      plan_id: "free",
      stripe_subscription_id: null,
      subscription_status: "canceled",
      updated_at: new Date().toISOString(),
    })
    .eq("id", orgId);

  if (error) {
    console.error(
      "Failed to downgrade org after customer.subscription.deleted",
      { orgId, error: error.message }
    );
    throw error;
  }

  console.info("Org downgraded to free after subscription deleted", {
    orgId,
    subscriptionId: subscription.id,
  });
}

async function handleInvoicePaymentFailed(
  invoice: Stripe.Invoice,
  supabase: ReturnType<typeof getServiceClient>
) {
  const customerId =
    typeof invoice.customer === "string"
      ? invoice.customer
      : invoice.customer?.id ?? null;

  if (!customerId) {
    console.warn("invoice.payment_failed missing customer", {
      invoiceId: invoice.id,
    });
    return;
  }

  // Look up org by stripe_customer_id
  const { data: org, error: fetchError } = await supabase
    .from("ps_organizations")
    .select("id")
    .eq("stripe_customer_id", customerId)
    .maybeSingle();

  if (fetchError) {
    console.error("Failed to look up org for failed invoice", {
      customerId,
      error: fetchError.message,
    });
    throw fetchError;
  }

  if (!org) {
    console.warn("No org found for Stripe customer", { customerId });
    return;
  }

  const { error: updateError } = await supabase
    .from("ps_organizations")
    .update({
      subscription_status: "past_due",
      updated_at: new Date().toISOString(),
    })
    .eq("id", org.id);

  if (updateError) {
    console.error("Failed to mark org past_due after payment failure", {
      orgId: org.id,
      error: updateError.message,
    });
    throw updateError;
  }

  console.info("Org marked past_due after invoice payment failed", {
    orgId: org.id,
    invoiceId: invoice.id,
  });
}

export async function POST(request: Request) {
  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET;

  if (!webhookSecret) {
    console.error("STRIPE_WEBHOOK_SECRET is not set");
    return NextResponse.json(
      { error: "Webhook not configured", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  const body = await request.text();
  const signature = request.headers.get("stripe-signature");

  if (!signature) {
    return NextResponse.json(
      { error: "Missing stripe-signature header", code: "VALIDATION_ERROR" },
      { status: 400 }
    );
  }

  let event: Stripe.Event;

  try {
    event = getStripe().webhooks.constructEvent(body, signature, webhookSecret);
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error("Stripe webhook signature verification failed", { message });
    return NextResponse.json(
      {
        error: `Webhook signature verification failed: ${message}`,
        code: "VALIDATION_ERROR",
      },
      { status: 400 }
    );
  }

  const supabase = getServiceClient();

  try {
    switch (event.type) {
      case "checkout.session.completed":
        await handleCheckoutSessionCompleted(
          event.data.object as Stripe.Checkout.Session,
          supabase
        );
        break;

      case "customer.subscription.updated":
        await handleSubscriptionUpdated(
          event.data.object as Stripe.Subscription,
          supabase
        );
        break;

      case "customer.subscription.deleted":
        await handleSubscriptionDeleted(
          event.data.object as Stripe.Subscription,
          supabase
        );
        break;

      case "invoice.payment_failed":
        await handleInvoicePaymentFailed(
          event.data.object as Stripe.Invoice,
          supabase
        );
        break;

      default:
        // Acknowledge unhandled events without error
        console.info("Unhandled Stripe event type", { type: event.type });
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error("Error handling Stripe webhook event", {
      type: event.type,
      eventId: event.id,
      message,
    });
    // Return 500 so Stripe retries the event
    return NextResponse.json(
      { error: "Webhook handler failed", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  return NextResponse.json({ received: true });
}
