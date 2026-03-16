import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { PLAN_LIMITS, type PlanId } from "@/lib/stripe/plans";

interface RouteContext {
  params: Promise<{ orgId: string }>;
}

type Period = "7d" | "30d" | "90d";

function getPeriodStart(period: Period): string {
  const now = new Date();
  const days = period === "7d" ? 7 : period === "30d" ? 30 : 90;
  const start = new Date(now);
  start.setDate(start.getDate() - (days - 1));
  return start.toISOString().slice(0, 10);
}

function getTodayString(): string {
  return new Date().toISOString().slice(0, 10);
}

function getCurrentMonthStart(): string {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), 1)
    .toISOString()
    .slice(0, 10);
}

export async function GET(request: Request, { params }: RouteContext) {
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
    return NextResponse.json(
      { error: "Failed to fetch usage", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  if (!membership) {
    return NextResponse.json(
      { error: "Organization not found", code: "NOT_FOUND" },
      { status: 404 }
    );
  }

  // Parse period query param
  const url = new URL(request.url);
  const rawPeriod = url.searchParams.get("period") ?? "30d";
  const validPeriods: Period[] = ["7d", "30d", "90d"];

  if (!validPeriods.includes(rawPeriod as Period)) {
    return NextResponse.json(
      {
        error: `period must be one of: ${validPeriods.join(", ")}`,
        code: "VALIDATION_ERROR",
      },
      { status: 422 }
    );
  }

  const period = rawPeriod as Period;
  const periodStart = getPeriodStart(period);
  const today = getTodayString();

  // Fetch daily breakdown — actual schema columns
  const { data: dailyRows, error: dailyError } = await supabase
    .from("ps_usage_daily")
    .select(
      "date, tokenize_calls, rehydrate_calls, flush_calls, tokens_created, detection_ms_p50, detection_ms_p95"
    )
    .eq("org_id", orgId)
    .gte("date", periodStart)
    .lte("date", today)
    .order("date", { ascending: true });

  if (dailyError) {
    return NextResponse.json(
      { error: "Failed to fetch usage", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  // Compute totals
  const periodTotals = (dailyRows ?? []).reduce(
    (acc, row) => ({
      tokenize_calls: acc.tokenize_calls + (row.tokenize_calls ?? 0),
      rehydrate_calls: acc.rehydrate_calls + (row.rehydrate_calls ?? 0),
      flush_calls: acc.flush_calls + (row.flush_calls ?? 0),
      tokens_created: acc.tokens_created + (row.tokens_created ?? 0),
    }),
    { tokenize_calls: 0, rehydrate_calls: 0, flush_calls: 0, tokens_created: 0 }
  );

  // Fetch org plan for limit calculation
  const { data: org } = await supabase
    .from("ps_organizations")
    .select("plan_id")
    .eq("id", orgId)
    .single();

  const planId = (org?.plan_id ?? "free") as PlanId;
  const planLimits = PLAN_LIMITS[planId] ?? PLAN_LIMITS.free;

  // Current month token usage
  const monthStart = getCurrentMonthStart();

  const { data: monthRows } = await supabase
    .from("ps_usage_daily")
    .select("tokens_created")
    .eq("org_id", orgId)
    .gte("date", monthStart);

  const monthlyTokensUsed = (monthRows ?? []).reduce(
    (sum, row) => sum + (row.tokens_created ?? 0),
    0
  );

  const monthlyTokenLimit = planLimits.monthlyTokens;
  const monthlyUsagePercent =
    monthlyTokenLimit > 0
      ? Math.min(100, (monthlyTokensUsed / monthlyTokenLimit) * 100)
      : 0;

  return NextResponse.json({
    period,
    period_start: periodStart,
    period_end: today,
    summary: periodTotals,
    monthly_quota: {
      tokens_used: monthlyTokensUsed,
      tokens_limit: monthlyTokenLimit,
      usage_percent: Math.round(monthlyUsagePercent * 100) / 100,
      plan_id: planId,
    },
    daily: dailyRows ?? [],
  });
}
