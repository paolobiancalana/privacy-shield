import { cookies } from "next/headers";
import { createClient } from "@/lib/supabase/server";
import { PLAN_LIMITS, type PlanId } from "@/lib/stripe/plans";
import { UsageDashboard } from "./usage-dashboard";

export interface DailyUsageRow {
  date: string;
  tokenize_calls: number;
  rehydrate_calls: number;
  flush_calls: number;
  tokens_created: number;
  detection_ms_p95: number | null;
}

export interface UsageSummary {
  totalCalls: number;
  tokensCreated: number;
  percentUsed: number;
  avgLatencyMs: number | null;
  monthlyLimit: number;
  dailyRows: DailyUsageRow[];
}

async function fetchUsage(
  orgId: string,
  days: number
): Promise<UsageSummary> {
  const supabase = await createClient();

  const since = new Date();
  since.setDate(since.getDate() - days);
  const sinceStr = since.toISOString().split("T")[0];

  // Fetch daily stats using actual schema columns
  const { data: rows } = await supabase
    .from("ps_usage_daily")
    .select(
      "date, tokenize_calls, rehydrate_calls, flush_calls, tokens_created, detection_ms_p95"
    )
    .eq("org_id", orgId)
    .gte("date", sinceStr)
    .order("date", { ascending: false });

  const dailyRows: DailyUsageRow[] = (rows ?? []).map((r) => ({
    date: r.date,
    tokenize_calls: r.tokenize_calls ?? 0,
    rehydrate_calls: r.rehydrate_calls ?? 0,
    flush_calls: r.flush_calls ?? 0,
    tokens_created: r.tokens_created ?? 0,
    detection_ms_p95: r.detection_ms_p95 ?? null,
  }));

  const totalCalls = dailyRows.reduce(
    (s, r) => s + r.tokenize_calls + r.rehydrate_calls + r.flush_calls,
    0
  );
  const tokensCreated = dailyRows.reduce((s, r) => s + r.tokens_created, 0);
  const latencies = dailyRows
    .map((r) => r.detection_ms_p95)
    .filter((v): v is number => v !== null);
  const avgLatencyMs =
    latencies.length > 0
      ? Math.round(latencies.reduce((a, b) => a + b, 0) / latencies.length)
      : null;

  // Fetch org plan to get monthly token limit
  const { data: org } = await supabase
    .from("ps_organizations")
    .select("plan_id")
    .eq("id", orgId)
    .single();

  const planId = (org?.plan_id ?? "free") as PlanId;
  const monthlyLimit = PLAN_LIMITS[planId]?.monthlyTokens ?? 1_000;

  // Current month token usage for percent calculation
  const monthStart = new Date();
  monthStart.setDate(1);
  const monthStartStr = monthStart.toISOString().split("T")[0];

  const { data: monthRows } = await supabase
    .from("ps_usage_daily")
    .select("tokens_created")
    .eq("org_id", orgId)
    .gte("date", monthStartStr);

  const monthTotal = (monthRows ?? []).reduce(
    (s, r) => s + (r.tokens_created ?? 0),
    0
  );
  const percentUsed =
    monthlyLimit > 0
      ? Math.min(100, Math.round((monthTotal / monthlyLimit) * 100))
      : 0;

  return {
    totalCalls,
    tokensCreated,
    percentUsed,
    avgLatencyMs,
    monthlyLimit,
    dailyRows,
  };
}

export default async function UsagePage({
  searchParams,
}: {
  searchParams: Promise<{ days?: string }>;
}) {
  const cookieStore = await cookies();
  const orgId = cookieStore.get("ps_selected_org")?.value ?? null;

  const supabase = await createClient();
  let resolvedOrgId = orgId;

  if (!resolvedOrgId) {
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (user) {
      const { data: member } = await supabase
        .from("ps_org_members")
        .select("org_id")
        .eq("user_id", user.id)
        .limit(1)
        .single();
      resolvedOrgId = member?.org_id ?? null;
    }
  }

  const params = await searchParams;
  const daysParam = parseInt(params.days ?? "30", 10);
  const days = [7, 30, 90].includes(daysParam) ? daysParam : 30;

  let summary: UsageSummary = {
    totalCalls: 0,
    tokensCreated: 0,
    percentUsed: 0,
    avgLatencyMs: null,
    monthlyLimit: 1_000,
    dailyRows: [],
  };

  if (resolvedOrgId) {
    summary = await fetchUsage(resolvedOrgId, days);
  }

  return <UsageDashboard summary={summary} activeDays={days} />;
}
