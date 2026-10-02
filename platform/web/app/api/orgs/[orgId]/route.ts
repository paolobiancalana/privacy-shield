import { NextResponse } from "next/server";
import { createClient, createAdminClient } from "@/lib/supabase/server";

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

  const adminClient = await createAdminClient();

  // Verify membership
  const { data: membership, error: membershipError } = await adminClient
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
  const { data: org, error: orgError } = await adminClient
    .from("ps_organizations")
    .select(
      "id, name, slug, plan_id, stripe_customer_id, created_at, updated_at"
    )
    .eq("id", orgId)
    .maybeSingle();

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

  const { data: members } = await adminClient
    .from("ps_org_members")
    .select("user_id, role, created_at")
    .eq("org_id", orgId);

  return NextResponse.json({
    organization: {
      ...org,
      member_role: membership.role,
    },
    members: members ?? [],
  });
}

export async function PATCH(request: Request, { params }: RouteContext) {
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

  const adminClient = await createAdminClient();

  // Verify membership and permission
  const { data: membership, error: membershipError } = await adminClient
    .from("ps_org_members")
    .select("role")
    .eq("org_id", orgId)
    .eq("user_id", user.id)
    .maybeSingle();

  if (membershipError || !membership) {
    return NextResponse.json(
      { error: "Organization not found", code: "NOT_FOUND" },
      { status: 404 }
    );
  }

  if (!ADMIN_ROLES.has(membership.role)) {
    return NextResponse.json(
      { error: "Only owners and admins can update organization settings", code: "FORBIDDEN" },
      { status: 403 }
    );
  }

  let body: { name?: string; slug?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error: "Invalid JSON body", code: "VALIDATION_ERROR" },
      { status: 422 }
    );
  }

  const updates: Record<string, string> = {};
  if (body.name && typeof body.name === "string" && body.name.trim().length > 0) {
    updates.name = body.name.trim();
  }
  if (body.slug && typeof body.slug === "string" && body.slug.trim().length > 0) {
    updates.slug = body.slug.trim().toLowerCase().replace(/[^a-z0-9-]/g, "-");
  }

  if (Object.keys(updates).length === 0) {
    return NextResponse.json(
      { error: "No fields to update", code: "VALIDATION_ERROR" },
      { status: 422 }
    );
  }

  const { data: updatedOrg, error: updateError } = await adminClient
    .from("ps_organizations")
    .update(updates)
    .eq("id", orgId)
    .select("id, name, slug")
    .maybeSingle();

  if (updateError) {
    console.error("Failed to update organization", {
      orgId,
      error: updateError.message,
    });
    return NextResponse.json(
      { error: updateError.message || "Failed to update organization", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  return NextResponse.json({ organization: updatedOrg });
}

export async function DELETE(_request: Request, { params }: RouteContext) {
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

  const adminClient = await createAdminClient();

  // Verify only OWNER can delete
  const { data: membership } = await adminClient
    .from("ps_org_members")
    .select("role")
    .eq("org_id", orgId)
    .eq("user_id", user.id)
    .maybeSingle();

  if (!membership || membership.role !== "owner") {
    return NextResponse.json(
      { error: "Only the organization owner can delete the organization", code: "FORBIDDEN" },
      { status: 403 }
    );
  }

  // Cascading deletes handled by FK constraints (or explicit)
  await adminClient.from("ps_api_keys").delete().eq("org_id", orgId);
  await adminClient.from("ps_usage_daily").delete().eq("org_id", orgId);
  await adminClient.from("ps_org_members").delete().eq("org_id", orgId);
  const { error: deleteError } = await adminClient
    .from("ps_organizations")
    .delete()
    .eq("id", orgId);

  if (deleteError) {
    console.error("Failed to delete organization", {
      orgId,
      error: deleteError.message,
    });
    return NextResponse.json(
      { error: "Failed to delete organization", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  return NextResponse.json({ success: true });
}
