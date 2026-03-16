import { cookies } from "next/headers";
import { createClient } from "@/lib/supabase/server";
import { PLAN_LIMITS, type PlanId } from "@/lib/stripe/plans";
import { BillingView } from "./billing-view";

export interface BillingData {
  planId: string;
  planDisplayName: string;
  tokensUsed: number;
  monthlyTokenLimit: number;
  callsUsed: number;
}

export default async function BillingPage() {
  const supabase = await createClient();
  const cookieStore = await cookies();

  const orgId = cookieStore.get("ps_selected_org")?.value ?? null;

  const {
    data: { user },
  } = await supabase.auth.getUser();

  let resolvedOrgId = orgId;

  if (!resolvedOrgId && user) {
    const { data: member } = await supabase
      .from("ps_org_members")
      .select("org_id")
      .eq("user_id", user.id)
      .limit(1)
      .single();
    resolvedOrgId = member?.org_id ?? null;
  }

  let billingData: BillingData = {
    planId: "free",
    planDisplayName: "Free",
    tokensUsed: 0,
    monthlyTokenLimit: 1_000,
    callsUsed: 0,
  };

  if (resolvedOrgId) {
    // Fetch org with plan info via join
    const { data: org } = await supabase
      .from("ps_organizations")
      .select("plan_id, ps_plans(display_name, monthly_token_limit)")
      .eq("id", resolvedOrgId)
      .single();

    const planId = (org?.plan_id ?? "free") as PlanId;
    const plan = org?.ps_plans as unknown as {
      display_name: string;
      monthly_token_limit: number;
    } | null;
    const monthlyTokenLimit =
      plan?.monthly_token_limit ?? PLAN_LIMITS[planId]?.monthlyTokens ?? 1_000;

    // Fetch current month usage
    const monthStart = new Date();
    monthStart.setDate(1);
    const monthStartStr = monthStart.toISOString().split("T")[0];

    const { data: usageRows } = await supabase
      .from("ps_usage_daily")
      .select("tokenize_calls, rehydrate_calls, flush_calls, tokens_created")
      .eq("org_id", resolvedOrgId)
      .gte("date", monthStartStr);

    const callsUsed = (usageRows ?? []).reduce(
      (s, r) =>
        s +
        (r.tokenize_calls ?? 0) +
        (r.rehydrate_calls ?? 0) +
        (r.flush_calls ?? 0),
      0
    );
    const tokensUsed = (usageRows ?? []).reduce(
      (s, r) => s + (r.tokens_created ?? 0),
      0
    );

    billingData = {
      planId,
      planDisplayName: plan?.display_name ?? planId,
      monthlyTokenLimit,
      callsUsed,
      tokensUsed,
    };
  }

  return <BillingView billing={billingData} />;
}
