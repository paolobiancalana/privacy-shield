import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

interface RouteContext {
  params: Promise<{ orgId: string }>;
}

export async function GET(_request: Request, { params }: RouteContext) {
  const { orgId } = await params;

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

  // Verify membership
  const { data: membership, error: membershipError } = await supabase
    .from("ps_org_members")
    .select("role")
    .eq("org_id", orgId)
    .eq("user_id", user.id)
    .maybeSingle();

  if (membershipError) {
    console.error("Failed to verify org membership", {
      userId: user.id,
      orgId,
      error: membershipError.message,
    });
    return NextResponse.json(
      { error: "Failed to fetch organization", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  if (!membership) {
    return NextResponse.json(
      { error: "Organization not found", code: "NOT_FOUND" },
      { status: 404 }
    );
  }

  // Fetch org details with plan info
  const { data: org, error: orgError } = await supabase
    .from("ps_organizations")
    .select(
      "id, name, slug, plan_id, stripe_customer_id, created_at, updated_at"
    )
    .eq("id", orgId)
    .single();

  if (orgError || !org) {
    console.error("Failed to fetch organization", {
      userId: user.id,
      orgId,
      error: orgError?.message,
    });
    return NextResponse.json(
      { error: "Organization not found", code: "NOT_FOUND" },
      { status: 404 }
    );
  }

  // Fetch members with email via rpc or direct join.
  // ps_org_members joined with auth.users is typically exposed
  // via a view or RPC in Supabase. We fetch members and rely on
  // the service role being able to reach auth.users via the
  // admin API, but here we use the anon client so we select only
  // the columns available through the table itself.
  const { data: members, error: membersError } = await supabase
    .from("ps_org_members")
    .select("user_id, role, created_at")
    .eq("org_id", orgId);

  if (membersError) {
    console.error("Failed to fetch org members", {
      userId: user.id,
      orgId,
      error: membersError.message,
    });
    return NextResponse.json(
      { error: "Failed to fetch organization details", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  // Build usage summary for the current calendar month
  const now = new Date();
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1)
    .toISOString()
    .slice(0, 10);
  const monthEnd = new Date(now.getFullYear(), now.getMonth() + 1, 0)
    .toISOString()
    .slice(0, 10);

  const { data: usageRows, error: usageError } = await supabase
    .from("ps_usage_daily")
    .select("tokens_used, requests_total, pii_detected")
    .eq("org_id", orgId)
    .gte("date", monthStart)
    .lte("date", monthEnd);

  if (usageError) {
    console.error("Failed to fetch usage summary", {
      userId: user.id,
      orgId,
      error: usageError.message,
    });
    return NextResponse.json(
      { error: "Failed to fetch organization details", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  const usageSummary = (usageRows ?? []).reduce(
    (acc, row) => ({
      tokens_used: acc.tokens_used + (row.tokens_used ?? 0),
      requests_total: acc.requests_total + (row.requests_total ?? 0),
      pii_detected: acc.pii_detected + (row.pii_detected ?? 0),
    }),
    { tokens_used: 0, requests_total: 0, pii_detected: 0 }
  );

  return NextResponse.json({
    organization: {
      ...org,
      member_role: membership.role,
    },
    members: members ?? [],
    usage_this_month: usageSummary,
  });
}
