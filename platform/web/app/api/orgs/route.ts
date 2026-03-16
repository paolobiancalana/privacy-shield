import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const SLUG_PATTERN = /^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$/;

export async function GET() {
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

  // Fetch org memberships for the user
  const { data: memberships, error: membershipsError } = await supabase
    .from("ps_org_members")
    .select("org_id, role")
    .eq("user_id", user.id);

  if (membershipsError) {
    console.error("Failed to fetch org memberships", {
      userId: user.id,
      error: membershipsError.message,
    });
    return NextResponse.json(
      { error: "Failed to fetch organizations", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  if (!memberships || memberships.length === 0) {
    return NextResponse.json({ organizations: [] });
  }

  const orgIds = memberships.map((m) => m.org_id);

  // Fetch orgs with plan info
  const { data: orgs, error: orgsError } = await supabase
    .from("ps_organizations")
    .select(
      "id, name, slug, plan_id, stripe_customer_id, created_at, updated_at"
    )
    .in("id", orgIds);

  if (orgsError) {
    console.error("Failed to fetch organizations", {
      userId: user.id,
      error: orgsError.message,
    });
    return NextResponse.json(
      { error: "Failed to fetch organizations", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  // Merge membership role into each org
  const roleByOrgId = Object.fromEntries(
    memberships.map((m) => [m.org_id, m.role])
  );

  const organizations = (orgs ?? []).map((org) => ({
    ...org,
    member_role: roleByOrgId[org.id] ?? null,
  }));

  return NextResponse.json({ organizations });
}

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

  const { name, slug } = body as Record<string, unknown>;

  if (!name || typeof name !== "string" || name.trim().length === 0) {
    return NextResponse.json(
      { error: "name is required", code: "VALIDATION_ERROR" },
      { status: 422 }
    );
  }

  if (!slug || typeof slug !== "string") {
    return NextResponse.json(
      { error: "slug is required", code: "VALIDATION_ERROR" },
      { status: 422 }
    );
  }

  const normalizedSlug = slug.toLowerCase();

  if (!SLUG_PATTERN.test(normalizedSlug)) {
    return NextResponse.json(
      {
        error:
          "slug must be 3–63 characters, lowercase alphanumeric and hyphens only, cannot start or end with a hyphen",
        code: "VALIDATION_ERROR",
      },
      { status: 422 }
    );
  }

  // Check slug uniqueness
  const { data: existing } = await supabase
    .from("ps_organizations")
    .select("id")
    .eq("slug", normalizedSlug)
    .maybeSingle();

  if (existing) {
    return NextResponse.json(
      { error: "Slug is already taken", code: "VALIDATION_ERROR" },
      { status: 422 }
    );
  }

  // Insert org and membership in a transaction-like sequence.
  // Supabase JS v2 does not expose a client-side transaction API;
  // we perform sequential inserts and clean up on failure.
  const { data: org, error: orgError } = await supabase
    .from("ps_organizations")
    .insert({
      name: name.trim(),
      slug: normalizedSlug,
      plan_id: "free",
    })
    .select()
    .single();

  if (orgError) {
    console.error("Failed to create organization", {
      userId: user.id,
      error: orgError.message,
      code: orgError.code,
    });

    if (orgError.code === "23505") {
      return NextResponse.json(
        { error: "Slug is already taken", code: "VALIDATION_ERROR" },
        { status: 422 }
      );
    }

    return NextResponse.json(
      { error: "Failed to create organization", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  const { error: memberError } = await supabase
    .from("ps_org_members")
    .insert({
      org_id: org.id,
      user_id: user.id,
      role: "owner",
    });

  if (memberError) {
    console.error("Failed to create org membership — rolling back org", {
      userId: user.id,
      orgId: org.id,
      error: memberError.message,
    });

    // Best-effort rollback
    await supabase.from("ps_organizations").delete().eq("id", org.id);

    return NextResponse.json(
      { error: "Failed to create organization", code: "INTERNAL_ERROR" },
      { status: 500 }
    );
  }

  return NextResponse.json({ organization: org }, { status: 201 });
}
