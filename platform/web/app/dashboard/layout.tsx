import { redirect } from "next/navigation";
import { cookies } from "next/headers";

import { createClient, createAdminClient } from "@/lib/supabase/server";
import { DashboardShell, type Org } from "@/components/dashboard/dashboard-shell";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createClient();

  // -------------------------------------------------------------------------
  // Auth guard
  // -------------------------------------------------------------------------
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/login");
  }

  const adminClient = await createAdminClient();

  // -------------------------------------------------------------------------
  // Fetch orgs the user belongs to
  // -------------------------------------------------------------------------
  const { data: memberRows, error: orgsError } = await adminClient
    .from("ps_org_members")
    .select(
      `
        role,
        ps_organizations (
          id,
          name,
          slug
        )
      `
    )
    .eq("user_id", user.id);

  if (orgsError) {
    console.error("[DashboardLayout] failed to fetch org memberships", orgsError);
  }

  let orgs: Org[] = (memberRows ?? []).flatMap((row) => {
    // Supabase infers the join as an array type; cast via unknown to single record
    const org = (row.ps_organizations as unknown) as {
      id: string;
      name: string;
      slug: string;
    } | null;
    if (!org || Array.isArray(org)) return [];
    return [{ id: org.id, name: org.name, slug: org.slug, role: row.role }];
  });

  // Auto-provision if user has 0 organizations so they are never stranded
  if (orgs.length === 0) {
    try {
      const emailPrefix = (user.email ?? "user").split("@")[0].toLowerCase().replace(/[^a-z0-9]/g, "-") || "org";
      const orgName = (user.email ?? "Personal").split("@")[0] || "Personal Org";
      const suffix = user.id.replace(/-/g, "").slice(0, 6);
      const slug = `${emailPrefix.slice(0, 30)}-${suffix}`;

      const { data: newOrg, error: newOrgErr } = await adminClient
        .from("ps_organizations")
        .insert({
          name: orgName,
          slug: slug,
          owner_id: user.id,
          plan_id: "free",
        })
        .select("id, name, slug")
        .single();

      if (newOrg && !newOrgErr) {
        await adminClient.from("ps_org_members").insert({
          org_id: newOrg.id,
          user_id: user.id,
          role: "owner",
        });

        orgs = [{ id: newOrg.id, name: newOrg.name, slug: newOrg.slug, role: "owner" }];
      } else {
        console.error("[DashboardLayout] Failed to auto-provision org:", newOrgErr);
      }
    } catch (err) {
      console.error("[DashboardLayout] Auto-provision exception:", err);
    }
  }

  // -------------------------------------------------------------------------
  // Determine selected org (cookie → first org)
  // -------------------------------------------------------------------------
  const cookieStore = await cookies();
  const cookieOrgId = cookieStore.get("ps_selected_org")?.value ?? null;
  const validOrgId =
    cookieOrgId && orgs.some((o) => o.id === cookieOrgId)
      ? cookieOrgId
      : (orgs[0]?.id ?? "");

  return (
    <DashboardShell
      user={{ id: user.id, email: user.email ?? "" }}
      orgs={orgs}
      initialOrgId={validOrgId}
    >
      {children}
    </DashboardShell>
  );
}
