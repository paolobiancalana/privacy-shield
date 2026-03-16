import { cookies } from "next/headers";
import { createClient } from "@/lib/supabase/server";
import { KeysManager } from "./keys-manager";
import type { ApiKey } from "@/components/dashboard/key-card";

export default async function KeysPage() {
  const supabase = await createClient();
  const cookieStore = await cookies();

  // Resolve selected org from cookie
  const orgId = cookieStore.get("ps_selected_org")?.value ?? null;

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

  // Fetch API keys for the selected org
  const keys: ApiKey[] = [];

  if (resolvedOrgId) {
    // Column names match the existing API route schema:
    // id, key_prefix, label, environment, active, created_at, revoked_at
    const { data } = await supabase
      .from("ps_api_keys")
      .select(
        "id, key_prefix, label, environment, active, created_at, revoked_at"
      )
      .eq("org_id", resolvedOrgId)
      .order("created_at", { ascending: false });

    if (data) {
      for (const row of data) {
        keys.push({
          id: row.id,
          prefix: row.key_prefix,
          label: row.label ?? null,
          environment: row.environment,
          active: row.active,
          created_at: row.created_at,
          revoked_at: row.revoked_at ?? null,
        });
      }
    }
  }

  return (
    <KeysManager
      initialKeys={keys}
      orgId={resolvedOrgId ?? ""}
    />
  );
}
