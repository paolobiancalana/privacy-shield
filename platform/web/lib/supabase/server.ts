import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options)
            );
          } catch {
            // The `setAll` method was called from a Server Component.
            // This can be ignored if you have middleware refreshing sessions.
          }
        },
      },
    }
  );
}

/**
 * Creates a server-side Supabase client with the service role key.
 * This client bypasses all RLS policies and should only be used for
 * administrative tasks after manual authorization checks.
 */
export async function createAdminClient() {
  const serviceKey =
    process.env.SUPABASE_SERVICE_ROLE_KEY ||
    process.env.SUPABASE_SERVICE_KEY;

  if (!serviceKey) {
    console.warn(
      "[SupabaseAdmin] SUPABASE_SERVICE_ROLE_KEY or SUPABASE_SERVICE_KEY is not defined. Admin operations will fallback to anon key."
    );
  }

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    serviceKey || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return [];
        },
        setAll() {
          // No-op for admin client
        },
      },
    }
  );
}
