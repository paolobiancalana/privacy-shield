import { cookies } from "next/headers";
import { createClient, createAdminClient } from "@/lib/supabase/server";
import { SettingsForm } from "./settings-form";

export default async function SettingsPage() {
  const supabase = await createClient();
  const adminClient = await createAdminClient();
  const cookieStore = await cookies();

  const orgId = cookieStore.get("ps_selected_org")?.value ?? null;

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-xl font-semibold">Impostazioni</h1>
        <p className="text-sm text-muted-foreground">Effettua il login per accedere alle impostazioni.</p>
      </div>
    );
  }

  let resolvedOrgId = orgId;
  let userRole = "member";

  if (!resolvedOrgId) {
    const { data: member } = await adminClient
      .from("ps_org_members")
      .select("org_id, role")
      .eq("user_id", user.id)
      .limit(1)
      .maybeSingle();
    resolvedOrgId = member?.org_id ?? null;
    userRole = member?.role ?? "member";
  } else {
    const { data: member } = await adminClient
      .from("ps_org_members")
      .select("role")
      .eq("org_id", resolvedOrgId)
      .eq("user_id", user.id)
      .maybeSingle();

    if (member) {
      userRole = member.role ?? "member";
    } else {
      const { data: fallbackMember } = await adminClient
        .from("ps_org_members")
        .select("org_id, role")
        .eq("user_id", user.id)
        .limit(1)
        .maybeSingle();
      resolvedOrgId = fallbackMember?.org_id ?? null;
      userRole = fallbackMember?.role ?? "member";
    }
  }

  let org: { id: string; name: string; slug: string } | null = null;

  if (resolvedOrgId) {
    const { data } = await adminClient
      .from("ps_organizations")
      .select("id, name, slug")
      .eq("id", resolvedOrgId)
      .maybeSingle();
    org = data;
  }

  return (
    <SettingsForm
      org={org}
      isOwner={userRole === "owner"}
    />
  );
}
