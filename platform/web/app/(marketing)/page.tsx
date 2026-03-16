import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import {
  ArrowRight,
  Zap,
  Lock,
  Database,
  Send,
  ScanSearch,
  Replace,
  RefreshCw,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Static data
// ---------------------------------------------------------------------------

const stats = [
  {
    label: "PII Types Detected",
    value: "10",
    description: "Names, CF, IVA, IBAN, email, phone, address & more",
    icon: ScanSearch,
  },
  {
    label: "API Latency",
    value: "<80ms",
    description: "p99 end-to-end across Italian document workloads",
    icon: Zap,
  },
  {
    label: "Transport Security",
    value: "mTLS",
    description: "Mutual TLS on every request — no plain-text secrets",
    icon: Lock,
  },
];

const steps = [
  {
    number: "01",
    title: "Send your text",
    description:
      "POST any Italian business document — invoices, contracts, emails — to the tokenize endpoint using your API key.",
    icon: Send,
  },
  {
    number: "02",
    title: "PII is detected",
    description:
      "Our NER ONNX model identifies 10 entity types in milliseconds: names, tax codes (CF), VAT numbers, IBAN, emails, phones, and addresses.",
    icon: ScanSearch,
  },
  {
    number: "03",
    title: "Tokens replace PII",
    description:
      "Each detected entity is swapped for an opaque, reversible token like [PERSON_abc123]. The sanitised text is safe to store or send downstream.",
    icon: Replace,
  },
  {
    number: "04",
    title: "Rehydrate on demand",
    description:
      "When you need the original data back, call /rehydrate with the token. Access is gated by your API key and optional expiry rules.",
    icon: RefreshCw,
  },
];

const curlRequest = `curl -X POST https://api.privacyshield.pro/api/v1/tokenize \\
  -H "X-API-Key: ps_live_..." \\
  -H "Content-Type: application/json" \\
  -d '{"text": "Mario Rossi, CF RSSMRA85M10H501Z"}'`;

const curlResponse = `{
  "sanitized_text": "[PERSON_a1b2c3], CF [CF_d4e5f6]",
  "entities": [
    {
      "type": "PERSON",
      "original": "Mario Rossi",
      "token": "PERSON_a1b2c3",
      "start": 0,
      "end": 11
    },
    {
      "type": "CF",
      "original": "RSSMRA85M10H501Z",
      "token": "CF_d4e5f6",
      "start": 17,
      "end": 33
    }
  ],
  "token_count": 2,
  "latency_ms": 42
}`;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function LandingPage() {
  return (
    <>
      {/* ------------------------------------------------------------------ */}
      {/* Hero                                                                */}
      {/* ------------------------------------------------------------------ */}
      <section className="relative overflow-hidden px-6 pb-24 pt-20 text-center">
        {/* Ambient glow */}
        <div
          className="pointer-events-none absolute inset-0"
          aria-hidden="true"
          style={{
            background:
              "radial-gradient(ellipse 80% 50% at 50% -10%, rgba(59,130,246,0.12) 0%, transparent 70%)",
          }}
        />

        <div className="relative mx-auto max-w-4xl">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-xs text-muted-foreground">
            <span
              className="inline-block h-1.5 w-1.5 rounded-full"
              style={{ background: "#10b981" }}
              aria-hidden="true"
            />
            Production-ready API — free tier available
          </div>

          <h1 className="mt-4 text-4xl font-bold tracking-tight text-foreground sm:text-5xl lg:text-6xl">
            PII Detection API for{" "}
            <span style={{ color: "#3b82f6" }}>Italian Business</span>{" "}
            Documents
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground">
            Privacy Shield detects and tokenizes personally identifiable
            information in real time. Sub-80ms latency, mTLS transport security,
            and full GDPR compliance — purpose-built for Italian CF, IVA, IBAN,
            and more.
          </p>

          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <Link href="/signup">
              <Button size="lg" className="gap-2">
                Get Started Free
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Button>
            </Link>
            <Link href="/docs">
              <Button variant="outline" size="lg">
                View Docs
              </Button>
            </Link>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Stats row                                                           */}
      {/* ------------------------------------------------------------------ */}
      <section className="border-y border-border px-6 py-12" aria-label="Key metrics">
        <div className="mx-auto grid max-w-5xl grid-cols-1 gap-6 sm:grid-cols-3">
          {stats.map(({ label, value, description, icon: Icon }) => (
            <Card key={label} className="text-center">
              <CardContent className="pt-6">
                <div
                  className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-lg"
                  style={{ background: "rgba(59,130,246,0.12)" }}
                  aria-hidden="true"
                >
                  <Icon className="h-5 w-5" style={{ color: "#3b82f6" }} />
                </div>
                <p
                  className="text-3xl font-bold tabular-nums"
                  style={{ color: "#3b82f6" }}
                >
                  {value}
                </p>
                <p className="mt-1 text-sm font-medium text-foreground">
                  {label}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {description}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* How it works                                                        */}
      {/* ------------------------------------------------------------------ */}
      <section className="px-6 py-24" aria-labelledby="how-it-works-heading">
        <div className="mx-auto max-w-5xl">
          <div className="mb-14 text-center">
            <h2
              id="how-it-works-heading"
              className="text-3xl font-bold tracking-tight text-foreground"
            >
              How it works
            </h2>
            <p className="mt-3 text-muted-foreground">
              Four simple steps from raw document to safe, rehydratable output.
            </p>
          </div>

          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {steps.map(({ number, title, description, icon: Icon }) => (
              <Card key={number} className="relative overflow-visible">
                <CardHeader>
                  <div className="mb-2 flex items-center gap-3">
                    <div
                      className="flex h-9 w-9 items-center justify-center rounded-lg"
                      style={{ background: "rgba(59,130,246,0.12)" }}
                      aria-hidden="true"
                    >
                      <Icon
                        className="h-5 w-5"
                        style={{ color: "#3b82f6" }}
                      />
                    </div>
                    <span
                      className="font-mono text-xs font-bold"
                      style={{ color: "#3b82f6" }}
                    >
                      {number}
                    </span>
                  </div>
                  <CardTitle className="text-base">{title}</CardTitle>
                </CardHeader>
                <CardContent>
                  <CardDescription className="text-sm leading-relaxed">
                    {description}
                  </CardDescription>
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Code example                                                        */}
      {/* ------------------------------------------------------------------ */}
      <section
        className="border-t border-border px-6 py-24"
        aria-labelledby="code-example-heading"
      >
        <div className="mx-auto max-w-5xl">
          <div className="mb-14 text-center">
            <h2
              id="code-example-heading"
              className="text-3xl font-bold tracking-tight text-foreground"
            >
              One API call away
            </h2>
            <p className="mt-3 text-muted-foreground">
              Integrate in minutes with any language or HTTP client.
            </p>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {/* Request */}
            <div className="flex flex-col gap-3">
              <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                Request
              </p>
              <div
                className="overflow-x-auto rounded-xl border border-border p-5"
                style={{ background: "#0f0f1a" }}
              >
                <pre className="font-mono text-sm leading-relaxed text-foreground">
                  <code>{curlRequest}</code>
                </pre>
              </div>
            </div>

            {/* Response */}
            <div className="flex flex-col gap-3">
              <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                Response
              </p>
              <div
                className="overflow-x-auto rounded-xl border border-border p-5"
                style={{ background: "#0f0f1a" }}
              >
                <pre className="font-mono text-sm leading-relaxed">
                  <code>
                    {/* Syntax-highlight key parts with inline spans */}
                    {curlResponse.split("\n").map((line, i) => {
                      // Colour keys blue, strings green, numbers amber
                      const formatted = line
                        .replace(
                          /("[\w_]+")\s*:/g,
                          `<span style="color:#93c5fd">$1</span>:`
                        )
                        .replace(
                          /:\s*(".*?")/g,
                          `: <span style="color:#86efac">$1</span>`
                        )
                        .replace(
                          /:\s*(\d+)/g,
                          `: <span style="color:#fcd34d">$1</span>`
                        );
                      return (
                        <span
                          key={i}
                          dangerouslySetInnerHTML={{ __html: formatted + "\n" }}
                        />
                      );
                    })}
                  </code>
                </pre>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Pricing CTA                                                         */}
      {/* ------------------------------------------------------------------ */}
      <section className="border-t border-border px-6 py-24">
        <div
          className="mx-auto max-w-3xl rounded-2xl border border-border p-10 text-center"
          style={{
            background:
              "linear-gradient(135deg, #1a1a2e 0%, #0f0f1a 100%)",
          }}
        >
          <Database
            className="mx-auto mb-4 h-10 w-10"
            style={{ color: "#3b82f6" }}
            aria-hidden="true"
          />
          <h2 className="text-2xl font-bold text-foreground">
            Transparent, usage-based pricing
          </h2>
          <p className="mt-3 text-muted-foreground">
            Start free with 1 000 tokens per month. Scale to 5 M tokens on
            Enterprise. No hidden fees.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <Link href="/pricing">
              <Button size="lg" className="gap-2">
                View Pricing
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Button>
            </Link>
            <Link href="/signup">
              <Button variant="outline" size="lg">
                Start Free — no credit card
              </Button>
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
