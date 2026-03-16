export async function psAdminFetch(
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  const PS_RUNTIME_URL = process.env.PS_RUNTIME_URL || "https://api.privacyshield.pro";
  const PS_ADMIN_KEY = process.env.PS_ADMIN_KEY || "";

  const { headers, ...rest } = options;

  return fetch(`${PS_RUNTIME_URL}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      "X-Admin-Key": PS_ADMIN_KEY,
      ...headers,
    },
  });
}
