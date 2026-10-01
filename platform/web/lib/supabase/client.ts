import { createBrowserClient } from "@supabase/ssr";

const memoryStorage = new Map<string, string>();

export function createClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!url || !anonKey) {
    console.error(
      "[SupabaseClient] NEXT_PUBLIC_SUPABASE_URL or NEXT_PUBLIC_SUPABASE_ANON_KEY is not defined"
    );
  }

  return createBrowserClient(url || "", anonKey || "", {
    cookies: {
      getAll() {
        try {
          if (typeof document === "undefined") {
            return Array.from(memoryStorage.entries()).map(([name, value]) => ({
              name,
              value,
            }));
          }
          const cookieStr = document.cookie;
          if (!cookieStr) {
            return Array.from(memoryStorage.entries()).map(([name, value]) => ({
              name,
              value,
            }));
          }
          const parsed = cookieStr
            .split(";")
            .map((v) => v.trim())
            .filter(Boolean)
            .map((cookie) => {
              const eqIdx = cookie.indexOf("=");
              if (eqIdx === -1) return { name: cookie, value: "" };
              return {
                name: decodeURIComponent(cookie.slice(0, eqIdx).trim()),
                value: decodeURIComponent(cookie.slice(eqIdx + 1).trim()),
              };
            });

          // Include any memory-stored cookies if not found in document.cookie
          const names = new Set(parsed.map((p) => p.name));
          for (const [name, value] of memoryStorage.entries()) {
            if (!names.has(name)) {
              parsed.push({ name, value });
            }
          }
          return parsed;
        } catch {
          // If browser restricts storage access (e.g. Safari sandbox or private window)
          return Array.from(memoryStorage.entries()).map(([name, value]) => ({
            name,
            value,
          }));
        }
      },
      setAll(cookiesToSet) {
        try {
          cookiesToSet.forEach(({ name, value, options }) => {
            memoryStorage.set(name, value);
            if (typeof document !== "undefined") {
              let cookie = `${encodeURIComponent(name)}=${encodeURIComponent(value)}; path=${options?.path ?? "/"}`;
              if (options?.maxAge) cookie += `; max-age=${options.maxAge}`;
              if (options?.domain) cookie += `; domain=${options.domain}`;
              if (options?.sameSite) cookie += `; samesite=${options.sameSite}`;
              if (
                options?.secure ||
                (typeof window !== "undefined" && window.location.protocol === "https:")
              ) {
                cookie += "; secure";
              }
              document.cookie = cookie;
            }
          });
        } catch {
          // Storage blocked, already stored in memoryStorage
        }
      },
    },
  });
}
