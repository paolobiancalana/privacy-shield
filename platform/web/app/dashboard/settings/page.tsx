import { cookies } from "next/headers";
import { createClient } from "@/lib/supabase/server";
import { SettingsForm } from "./settings-form";

export default async function SettingsPage() {
  const supabase = await createClient();
  const cookieStore = await cookies();

  const orgId = cookieStore.get("ps_selected_org")?.value ?? null;

  const {
    data: { user },
  } = await supabase.auth.getUser();

  let resolvedOrgId = orgId;
  let userRole = "member";

  if (!resolvedOrgId && user) {
    const { data: member } = await supabase
      .from("ps_org_members")
      .select("org_id, role")
      .eq("user_id", user.id)
      .limit(1)
      .single();
    resolvedOrgId = member?.org_id ?? null;
    userRole = member?.role ?? "member";
  } else if (resolvedOrgId && user) {
    const { data: member } = await supabase
      .from("ps_org_members")
      .select("role")
      .eq("org_id", resolvedOrgId)
      .eq("user_id", user.id)
      .single();
    userRole = member?.role ?? "member";
  }

  let org: { id: string; name: string; slug: string } | null = null;

  if (resolvedOrgId) {
    const { data } = await supabase
      .from("ps_organizations")
      .select("id, name, slug")
      .eq("id", resolvedOrgId)
      .single();
    org = data;
  }

  return (
    <SettingsForm
      org={org}
      isOwner={userRole === "owner"}
    />
  );
}
