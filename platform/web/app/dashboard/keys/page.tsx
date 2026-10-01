import { cookies } from "next/headers";
import { createClient, createAdminClient } from "@/lib/supabase/server";
import { KeysManager } from "./keys-manager";
import type { ApiKey } from "@/components/dashboard/api-key-table";

export default async function KeysPage() {
  const supabase = await createClient();
  const adminClient = await createAdminClient();
  const cookieStore = await cookies();

  // Resolve selected org from cookie
  const orgId = cookieStore.get("ps_selected_org")?.value ?? null;

  let resolvedOrgId = orgId;

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!resolvedOrgId && user) {
    const { data: member, error: memberError } = await adminClient
      .from("ps_org_members")
      .select("org_id")
      .eq("user_id", user.id)
      .limit(1)
      .maybeSingle();
    
    if (memberError) {
      console.error("[KeysPage] Membership Lookup Error:", memberError.message);
    }

    resolvedOrgId = member?.org_id ?? null;
  }

  // Fetch API keys for the selected org
  const keys: ApiKey[] = [];

  if (resolvedOrgId) {
    const { data, error: keysError } = await adminClient
      .from("ps_api_keys")
      .select(
        "id, key_prefix, label, environment, active, created_at, revoked_at, expires_at"
      )
      .eq("org_id", resolvedOrgId)
      .order("created_at", { ascending: false });

    if (keysError) {
       console.error("[KeysPage] Keys Fetch Error:", keysError.message);
    }

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
          expires_at: row.expires_at ?? null,
        });
      }
    }
  } else {
    console.warn("[KeysPage] No resolvedOrgId found. Creation button will be hidden.");
  }

  return (
    <KeysManager
      initialKeys={keys}
      orgId={resolvedOrgId ?? ""}
    />
  );
}
