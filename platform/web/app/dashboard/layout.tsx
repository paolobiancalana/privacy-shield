import { redirect } from "next/navigation";
import { cookies } from "next/headers";

import { createClient } from "@/lib/supabase/server";
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

  // -------------------------------------------------------------------------
  // Fetch orgs the user belongs to
  // -------------------------------------------------------------------------
  const { data: memberRows } = await supabase
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

  const orgs: Org[] = (memberRows ?? []).flatMap((row) => {
    // Supabase infers the join as an array type; cast via unknown to single record
    const org = (row.ps_organizations as unknown) as {
      id: string;
      name: string;
      slug: string;
    } | null;
    if (!org || Array.isArray(org)) return [];
    return [{ id: org.id, name: org.name, slug: org.slug, role: row.role }];
  });

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
