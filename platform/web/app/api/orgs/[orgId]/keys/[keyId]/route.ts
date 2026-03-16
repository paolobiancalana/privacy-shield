import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

interface RouteContext {
  params: Promise<{ orgId: string; keyId: string }>;
}

const ADMIN_ROLES = new Set(["owner", "admin"]);

export async function DELETE(_request: Request, { params }: RouteContext) {
  const { orgId, keyId } = await params;

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
      { error: "Failed to revoke key", code: "INTERNAL_ERROR" },
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
        error: "Only owners and admins can revoke API keys",
        code: "FORBIDDEN",
      },
      { status: 403 }
    );
  }

  // Verify the key belongs to this org and is currently active
  const { data: key, error: keyFetchError } = await supabase
    .from("ps_api_keys")
    .select("id, active")
    .eq("id", keyId)
    .eq("org_id", orgId)
    .maybeSingle();

  if (keyFetchError) {
    console.error("Failed to fetch API key", {
      userId: user.id,
      orgId,
      keyId,
      error: keyFetchError.message,
    });
    return NextResponse.json(
      { error: "Failed to revoke key", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  if (!key) {
    return NextResponse.json(
      { error: "API key not found", code: "NOT_FOUND" },
      { status: 404 }
    );
  }

  if (!key.active) {
    // Already revoked — treat as idempotent success
    return NextResponse.json({ revoked: true, key_id: keyId });
  }

  const { error: updateError } = await supabase
    .from("ps_api_keys")
    .update({
      active: false,
      revoked_at: new Date().toISOString(),
    })
    .eq("id", keyId)
    .eq("org_id", orgId);

  if (updateError) {
    console.error("Failed to revoke API key", {
      userId: user.id,
      orgId,
      keyId,
      error: updateError.message,
    });
    return NextResponse.json(
      { error: "Failed to revoke key", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  return NextResponse.json({ revoked: true, key_id: keyId });
}
