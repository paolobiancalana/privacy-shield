"use client";

import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { BookOpen, Terminal, Code2, Zap } from "lucide-react";

// ---------------------------------------------------------------------------
// Code snippets
// ---------------------------------------------------------------------------

const quickstartSnippets = {
  curl: `# 1. Tokenize PII in a document
curl -X POST https://api.privacyshield.pro/api/v1/tokenize \\
  -H "X-API-Key: ps_live_YOUR_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "text": "Contatta Mario Rossi al 02-1234567 o mario.rossi@example.com"
  }'

# 2. Rehydrate tokens back to original PII
curl -X POST https://api.privacyshield.pro/api/v1/rehydrate \\
  -H "X-API-Key: ps_live_YOUR_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "text": "Contatta [PERSON_a1b2c3] al [PHONE_d4e5f6] o [EMAIL_g7h8i9]"
  }'`,

  python: `import httpx

API_KEY = "ps_live_YOUR_KEY"
BASE_URL = "https://api.privacyshield.pro/api/v1"

headers = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json",
}

# 1. Tokenize
response = httpx.post(
    f"{BASE_URL}/tokenize",
    headers=headers,
    json={"text": "Contatta Mario Rossi al 02-1234567 o mario.rossi@example.com"},
)
result = response.json()
sanitized = result["sanitized_text"]
print(sanitized)
# → "Contatta [PERSON_a1b2c3] al [PHONE_d4e5f6] o [EMAIL_g7h8i9]"

# 2. Rehydrate
response = httpx.post(
    f"{BASE_URL}/rehydrate",
    headers=headers,
    json={"text": sanitized},
)
print(response.json()["rehydrated_text"])
# → "Contatta Mario Rossi al 02-1234567 o mario.rossi@example.com"`,

  typescript: `const API_KEY = "ps_live_YOUR_KEY";
const BASE_URL = "https://api.privacyshield.pro/api/v1";

const headers = {
  "X-API-Key": API_KEY,
  "Content-Type": "application/json",
};

// 1. Tokenize
const tokenizeRes = await fetch(\`\${BASE_URL}/tokenize\`, {
  method: "POST",
  headers,
  body: JSON.stringify({
    text: "Contatta Mario Rossi al 02-1234567 o mario.rossi@example.com",
  }),
});
const { sanitized_text, entities } = await tokenizeRes.json();
console.log(sanitized_text);
// → "Contatta [PERSON_a1b2c3] al [PHONE_d4e5f6] o [EMAIL_g7h8i9]"

// 2. Rehydrate
const rehydrateRes = await fetch(\`\${BASE_URL}/rehydrate\`, {
  method: "POST",
  headers,
  body: JSON.stringify({ text: sanitized_text }),
});
const { rehydrated_text } = await rehydrateRes.json();
console.log(rehydrated_text);
// → "Contatta Mario Rossi al 02-1234567 o mario.rossi@example.com"`,
};

// ---------------------------------------------------------------------------
// Endpoint definitions
// ---------------------------------------------------------------------------

type Endpoint = {
  method: "POST" | "GET" | "DELETE";
  path: string;
  description: string;
  requestBody: string;
  responseBody: string;
  badge: string;
};

const endpoints: Endpoint[] = [
  {
    method: "POST",
    path: "/api/v1/tokenize",
    description:
      "Scan text for PII entities and replace them with reversible tokens. Supports Italian-specific entity types: CF, IVA, IBAN, and more.",
    badge: "Core",
    requestBody: `{
  "text": "string",          // required — document text (max 50 000 chars)
  "entity_types": ["string"] // optional — filter to specific types
}`,
    responseBody: `{
  "sanitized_text": "string",
  "entities": [
    {
      "type": "PERSON | CF | IVA | IBAN | EMAIL | PHONE | ADDRESS | DATE | ORG | OTHER",
      "original": "string",
      "token": "string",
      "start": 0,
      "end": 0
    }
  ],
  "token_count": 0,
  "latency_ms": 0
}`,
  },
  {
    method: "POST",
    path: "/api/v1/rehydrate",
    description:
      "Reverse tokenization: swap tokens back to their original PII values. Requires the same API key used during tokenization.",
    badge: "Core",
    requestBody: `{
  "text": "string" // required — text containing [TYPE_token] placeholders
}`,
    responseBody: `{
  "rehydrated_text": "string",
  "resolved_count": 0,
  "unresolved_tokens": ["string"]
}`,
  },
  {
    method: "POST",
    path: "/api/v1/flush",
    description:
      "Permanently delete all stored token mappings for a given scope. Use to honour GDPR erasure requests or rotate token namespaces.",
    badge: "Privacy",
    requestBody: `{
  "scope": "all | session",  // required
  "session_id": "string"     // required when scope is "session"
}`,
    responseBody: `{
  "deleted_count": 0,
  "ok": true
}`,
  },
];

const methodColors: Record<string, string> = {
  POST: "#3b82f6",
  GET: "#10b981",
  DELETE: "#ef4444",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function CodeBlock({ code }: { code: string }) {
  return (
    <div
      className="overflow-x-auto rounded-xl border border-border p-5"
      style={{ background: "#0f0f1a" }}
    >
      <pre className="font-mono text-sm leading-relaxed text-foreground">
        <code>{code}</code>
      </pre>
    </div>
  );
}

function MethodBadge({ method }: { method: string }) {
  return (
    <span
      className="inline-flex items-center rounded px-2 py-0.5 font-mono text-xs font-bold text-white"
      style={{ background: methodColors[method] ?? "#888" }}
    >
      {method}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DocsPage() {
  return (
    <div className="px-6 py-16">
      <div className="mx-auto max-w-4xl">
        {/* Header */}
        <div className="mb-12">
          <div className="mb-3 flex items-center gap-2 text-sm text-muted-foreground">
            <BookOpen className="h-4 w-4" aria-hidden="true" />
            <span>API Reference</span>
          </div>
          <h1 className="text-4xl font-bold tracking-tight text-foreground">
            Privacy Shield API Docs
          </h1>
          <p className="mt-4 text-lg text-muted-foreground">
            Everything you need to integrate PII detection and tokenization into
            your application.
          </p>

          {/* Meta info */}
          <div className="mt-6 flex flex-wrap gap-3">
            <span
              className="inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1 text-xs text-muted-foreground"
              style={{ background: "#0f0f1a" }}
            >
              <Zap className="h-3 w-3" aria-hidden="true" />
              Base URL: api.privacyshield.pro
            </span>
            <span
              className="inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1 text-xs text-muted-foreground"
              style={{ background: "#0f0f1a" }}
            >
              <Terminal className="h-3 w-3" aria-hidden="true" />
              Auth: X-API-Key header
            </span>
            <span
              className="inline-flex items-center gap-1.5 rounded-full border border-border px-3 py-1 text-xs text-muted-foreground"
              style={{ background: "#0f0f1a" }}
            >
              <Code2 className="h-3 w-3" aria-hidden="true" />
              Format: JSON
            </span>
          </div>
        </div>

        <Separator className="mb-12" />

        {/* ---------------------------------------------------------------- */}
        {/* Quick start                                                       */}
        {/* ---------------------------------------------------------------- */}
        <section aria-labelledby="quickstart-heading" className="mb-16">
          <h2
            id="quickstart-heading"
            className="mb-2 text-2xl font-bold text-foreground"
          >
            Quick start
          </h2>
          <p className="mb-6 text-muted-foreground">
            Get your API key from the{" "}
            <a
              href="/dashboard"
              className="underline underline-offset-4 transition-colors hover:text-foreground"
            >
              dashboard
            </a>{" "}
            and make your first request in under two minutes.
          </p>

          <Tabs defaultValue="curl">
            <TabsList className="mb-4">
              <TabsTrigger value="curl">curl</TabsTrigger>
              <TabsTrigger value="python">Python</TabsTrigger>
              <TabsTrigger value="typescript">TypeScript</TabsTrigger>
            </TabsList>

            <TabsContent value="curl">
              <CodeBlock code={quickstartSnippets.curl} />
            </TabsContent>
            <TabsContent value="python">
              <CodeBlock code={quickstartSnippets.python} />
            </TabsContent>
            <TabsContent value="typescript">
              <CodeBlock code={quickstartSnippets.typescript} />
            </TabsContent>
          </Tabs>
        </section>

        <Separator className="mb-12" />

        {/* ---------------------------------------------------------------- */}
        {/* Authentication                                                    */}
        {/* ---------------------------------------------------------------- */}
        <section aria-labelledby="auth-heading" className="mb-16">
          <h2
            id="auth-heading"
            className="mb-2 text-2xl font-bold text-foreground"
          >
            Authentication
          </h2>
          <p className="mb-4 text-muted-foreground">
            Every request must include your API key in the{" "}
            <code
              className="rounded px-1.5 py-0.5 font-mono text-sm"
              style={{ background: "#1a1a2e", color: "#93c5fd" }}
            >
              X-API-Key
            </code>{" "}
            header. Keys are prefixed with{" "}
            <code
              className="rounded px-1.5 py-0.5 font-mono text-sm"
              style={{ background: "#1a1a2e", color: "#86efac" }}
            >
              ps_live_
            </code>{" "}
            for production and{" "}
            <code
              className="rounded px-1.5 py-0.5 font-mono text-sm"
              style={{ background: "#1a1a2e", color: "#fcd34d" }}
            >
              ps_test_
            </code>{" "}
            for sandbox.
          </p>
          <CodeBlock
            code={`# All requests must include this header
X-API-Key: ps_live_YOUR_API_KEY`}
          />
        </section>

        <Separator className="mb-12" />

        {/* ---------------------------------------------------------------- */}
        {/* Endpoints                                                         */}
        {/* ---------------------------------------------------------------- */}
        <section aria-labelledby="endpoints-heading">
          <h2
            id="endpoints-heading"
            className="mb-8 text-2xl font-bold text-foreground"
          >
            Endpoints
          </h2>

          <div className="flex flex-col gap-10">
            {endpoints.map((ep) => (
              <article
                key={ep.path}
                aria-labelledby={`ep-${ep.path.replace(/\//g, "-")}`}
              >
                <Card>
                  <CardHeader>
                    <div className="flex flex-wrap items-center gap-3">
                      <MethodBadge method={ep.method} />
                      <code
                        className="font-mono text-sm font-semibold text-foreground"
                        id={`ep-${ep.path.replace(/\//g, "-")}`}
                      >
                        {ep.path}
                      </code>
                      <Badge variant="secondary">{ep.badge}</Badge>
                    </div>
                    <CardDescription className="mt-2 text-sm leading-relaxed">
                      {ep.description}
                    </CardDescription>
                  </CardHeader>

                  <CardContent className="flex flex-col gap-5">
                    <div>
                      <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                        Request body
                      </p>
                      <CodeBlock code={ep.requestBody} />
                    </div>
                    <div>
                      <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                        Response
                      </p>
                      <CodeBlock code={ep.responseBody} />
                    </div>
                  </CardContent>
                </Card>
              </article>
            ))}
          </div>
        </section>

        <Separator className="my-12" />

        {/* ---------------------------------------------------------------- */}
        {/* Error codes                                                       */}
        {/* ---------------------------------------------------------------- */}
        <section aria-labelledby="errors-heading" className="mb-16">
          <h2
            id="errors-heading"
            className="mb-6 text-2xl font-bold text-foreground"
          >
            Error codes
          </h2>

          <div className="overflow-x-auto rounded-xl border border-border">
            <table
              className="w-full text-left text-sm"
              aria-label="API error codes"
            >
              <thead>
                <tr
                  className="border-b border-border"
                  style={{ background: "#0f0f1a" }}
                >
                  <th scope="col" className="px-4 py-3 font-medium text-muted-foreground">
                    HTTP Status
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium text-muted-foreground">
                    Code
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium text-muted-foreground">
                    Meaning
                  </th>
                </tr>
              </thead>
              <tbody>
                {[
                  { status: "400", code: "invalid_request", meaning: "Malformed JSON or missing required field." },
                  { status: "401", code: "unauthorized", meaning: "Missing or invalid API key." },
                  { status: "422", code: "text_too_long", meaning: "Input text exceeds 50 000 characters." },
                  { status: "429", code: "rate_limited", meaning: "Request rate exceeded for your plan." },
                  { status: "500", code: "internal_error", meaning: "Unexpected server error. Retry with backoff." },
                ].map(({ status, code, meaning }, i) => (
                  <tr
                    key={code}
                    className="border-b border-border last:border-0"
                    style={
                      i % 2 === 1
                        ? { background: "rgba(255,255,255,0.02)" }
                        : undefined
                    }
                  >
                    <td className="px-4 py-3">
                      <code
                        className="rounded px-1.5 py-0.5 font-mono text-xs"
                        style={{
                          background:
                            status.startsWith("4") || status.startsWith("5")
                              ? "rgba(239,68,68,0.1)"
                              : "rgba(59,130,246,0.1)",
                          color:
                            status.startsWith("4") || status.startsWith("5")
                              ? "#fca5a5"
                              : "#93c5fd",
                        }}
                      >
                        {status}
                      </code>
                    </td>
                    <td className="px-4 py-3">
                      <code className="font-mono text-xs text-muted-foreground">
                        {code}
                      </code>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">{meaning}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* ---------------------------------------------------------------- */}
        {/* PII entity types                                                  */}
        {/* ---------------------------------------------------------------- */}
        <section aria-labelledby="entity-types-heading">
          <h2
            id="entity-types-heading"
            className="mb-6 text-2xl font-bold text-foreground"
          >
            Supported PII entity types
          </h2>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {[
              { type: "PERSON", example: "Mario Rossi", note: "Full names" },
              { type: "CF", example: "RSSMRA85M10H501Z", note: "Codice Fiscale" },
              { type: "IVA", example: "IT12345678901", note: "Partita IVA" },
              { type: "IBAN", example: "IT60X0542811101000000123456", note: "Bank account" },
              { type: "EMAIL", example: "mario@example.com", note: "Email addresses" },
              { type: "PHONE", example: "+39 02 1234567", note: "Phone numbers" },
              { type: "ADDRESS", example: "Via Roma 1, Milano", note: "Street addresses" },
              { type: "DATE", example: "15/03/1985", note: "Dates of birth" },
              { type: "ORG", example: "Rossi S.r.l.", note: "Company names" },
              { type: "OTHER", example: "—", note: "Residual PII" },
            ].map(({ type, example, note }) => (
              <div
                key={type}
                className="flex items-start gap-3 rounded-xl border border-border p-4"
                style={{ background: "#0f0f1a" }}
              >
                <code
                  className="mt-0.5 shrink-0 rounded px-2 py-0.5 font-mono text-xs font-bold"
                  style={{
                    background: "rgba(59,130,246,0.12)",
                    color: "#93c5fd",
                  }}
                >
                  {type}
                </code>
                <div>
                  <p className="text-sm font-medium text-foreground">{note}</p>
                  <p className="mt-0.5 font-mono text-xs text-muted-foreground">
                    e.g. {example}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
