import { NextResponse } from "next/server";
import { createHash, randomBytes } from "crypto";
import { createClient } from "@/lib/supabase/server";
import { PLAN_LIMITS, type PlanId } from "@/lib/stripe/plans";

interface RouteContext {
  params: Promise<{ orgId: string }>;
}

const ADMIN_ROLES = new Set(["owner", "admin"]);

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
      { error: "Failed to fetch keys", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  if (!membership) {
    return NextResponse.json(
      { error: "Organization not found", code: "NOT_FOUND" },
      { status: 404 }
    );
  }

  // Return active keys and revoked keys (exclude key_hash for security)
  const { data: keys, error: keysError } = await supabase
    .from("ps_api_keys")
    .select(
      "id, key_prefix, label, environment, active, created_by, created_at, revoked_at"
    )
    .eq("org_id", orgId)
    .order("created_at", { ascending: false });

  if (keysError) {
    console.error("Failed to fetch API keys", {
      userId: user.id,
      orgId,
      error: keysError.message,
    });
    return NextResponse.json(
      { error: "Failed to fetch keys", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  return NextResponse.json({ keys: keys ?? [] });
}

export async function POST(request: Request, { params }: RouteContext) {
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

  // Verify membership and role
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
      { error: "Failed to create key", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  if (!membership) {
    return NextResponse.json(
      { error: "Organization not found", code: "NOT_FOUND" },
      { status: 404 }
    );
  }

  if (!ADMIN_ROLES.has(membership.role)) {
    return NextResponse.json(
      {
        error: "Only owners and admins can create API keys",
        code: "FORBIDDEN",
      },
      { status: 403 }
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

  const { label, environment } = body as Record<string, unknown>;

  if (!label || typeof label !== "string" || label.trim().length === 0) {
    return NextResponse.json(
      { error: "label is required", code: "VALIDATION_ERROR" },
      { status: 422 }
    );
  }

  if (!environment || typeof environment !== "string") {
    return NextResponse.json(
      { error: "environment is required", code: "VALIDATION_ERROR" },
      { status: 422 }
    );
  }

  const validEnvironments = ["production", "staging", "development", "test"];
  if (!validEnvironments.includes(environment)) {
    return NextResponse.json(
      {
        error: `environment must be one of: ${validEnvironments.join(", ")}`,
        code: "VALIDATION_ERROR",
      },
      { status: 422 }
    );
  }

  // Fetch org plan
  const { data: org, error: orgError } = await supabase
    .from("ps_organizations")
    .select("plan_id")
    .eq("id", orgId)
    .single();

  if (orgError || !org) {
    console.error("Failed to fetch org plan", {
      userId: user.id,
      orgId,
      error: orgError?.message,
    });
    return NextResponse.json(
      { error: "Organization not found", code: "NOT_FOUND" },
      { status: 404 }
    );
  }

  // Check active key count against plan limit
  const { count: activeKeyCount, error: countError } = await supabase
    .from("ps_api_keys")
    .select("id", { count: "exact", head: true })
    .eq("org_id", orgId)
    .eq("active", true);

  if (countError) {
    console.error("Failed to count active keys", {
      userId: user.id,
      orgId,
      error: countError.message,
    });
    return NextResponse.json(
      { error: "Failed to create key", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  const planId = (org.plan_id ?? "free") as PlanId;
  const planLimits = PLAN_LIMITS[planId] ?? PLAN_LIMITS.free;
  const currentCount = activeKeyCount ?? 0;

  if (currentCount >= planLimits.maxKeys) {
    return NextResponse.json(
      {
        error: `Your ${planId} plan allows a maximum of ${planLimits.maxKeys} active API keys. Revoke an existing key or upgrade your plan.`,
        code: "PLAN_LIMIT_REACHED",
      },
      { status: 400 }
    );
  }

  // Generate the raw key: ps_{environment}_{32 random hex chars}
  const rawKey = `ps_${environment}_${randomBytes(16).toString("hex")}`;

  // SHA-256 hash for storage
  const keyHash = createHash("sha256").update(rawKey).digest("hex");

  // Key prefix: first 8 chars + "..." + last 4 chars of the raw key
  const keyPrefix = `${rawKey.slice(0, 8)}...${rawKey.slice(-4)}`;

  const { data: keyRecord, error: insertError } = await supabase
    .from("ps_api_keys")
    .insert({
      org_id: orgId,
      label: label.trim(),
      environment,
      key_hash: keyHash,
      key_prefix: keyPrefix,
      active: true,
      created_by: user.id,
    })
    .select("id, key_prefix, label, environment, created_at")
    .single();

  if (insertError) {
    console.error("Failed to insert API key", {
      userId: user.id,
      orgId,
      error: insertError.message,
    });
    return NextResponse.json(
      { error: "Failed to create key", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  // Return the raw key only once — it cannot be recovered later
  return NextResponse.json(
    {
      key: rawKey,
      key_id: keyRecord.id,
      key_prefix: keyRecord.key_prefix,
      label: keyRecord.label,
      environment: keyRecord.environment,
      created_at: keyRecord.created_at,
    },
    { status: 201 }
  );
}
