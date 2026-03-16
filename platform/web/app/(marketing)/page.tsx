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
    label: "Tipi di PII rilevati",
    value: "10",
    description: "Nomi, CF, P.IVA, IBAN, email, telefono, indirizzo e altro",
    icon: ScanSearch,
  },
  {
    label: "Latenza API",
    value: "<80ms",
    description: "p99 end-to-end su documenti aziendali italiani",
    icon: Zap,
  },
  {
    label: "Sicurezza trasporto",
    value: "mTLS",
    description: "Mutual TLS su ogni richiesta — zero segreti in chiaro",
    icon: Lock,
  },
];

const steps = [
  {
    number: "01",
    title: "Invia il testo",
    description:
      "Esegui una POST con qualsiasi documento aziendale italiano — fatture, contratti, email — all'endpoint /tokenize usando la tua chiave API.",
    icon: Send,
  },
  {
    number: "02",
    title: "PII rilevata",
    description:
      "Il nostro modello NER ONNX identifica 10 tipi di entità in millisecondi: nomi, codici fiscali (CF), partite IVA, IBAN, email, telefoni e indirizzi.",
    icon: ScanSearch,
  },
  {
    number: "03",
    title: "Token sostituiscono i dati",
    description:
      "Ogni entità rilevata viene sostituita da un token opaco e reversibile come [PERSON_abc123]. Il testo sanificato è sicuro da archiviare o trasmettere.",
    icon: Replace,
  },
  {
    number: "04",
    title: "Reidrata quando serve",
    description:
      "Quando hai bisogno dei dati originali, chiama /rehydrate con il token. L'accesso è controllato dalla tua chiave API e da regole di scadenza opzionali.",
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
            Beta aperta — accesso completo e gratuito
          </div>

          <h1 className="mt-4 text-4xl font-bold tracking-tight text-foreground sm:text-5xl lg:text-6xl">
            I tuoi dati personali sono a rischio.{" "}
            <span style={{ color: "#3b82f6" }}>Ogni giorno.</span>
          </h1>

          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground">
            Una violazione dei dati può costarti fino a <strong className="text-foreground">€20 milioni o il 4% del fatturato</strong> in sanzioni GDPR — oltre al danno reputazionale. Privacy Shield rileva e tokenizza automaticamente i dati personali in tempo reale: codice fiscale, partita IVA, IBAN, email e molto altro. Latenza inferiore a 80ms, sicurezza mTLS, pronto per la produzione.
          </p>

          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <Link href="/signup">
              <Button size="lg" className="gap-2">
                Proteggi i tuoi dati
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Button>
            </Link>
            <Link href="/docs">
              <Button variant="outline" size="lg">
                Documentazione API
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
              Come funziona
            </h2>
            <p className="mt-3 text-muted-foreground">
              Quattro semplici passaggi dal documento grezzo all'output sanificato e reidratabile.
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
              Una sola chiamata API
            </h2>
            <p className="mt-3 text-muted-foreground">
              Integra in pochi minuti con qualsiasi linguaggio o client HTTP.
            </p>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            {/* Request */}
            <div className="flex flex-col gap-3">
              <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
                Richiesta
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
                Risposta
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
            Gratis durante la Beta
          </h2>
          <p className="mt-3 text-muted-foreground">
            500K token/mese, 200 req/min, 20 chiavi API. Nessuna carta di credito. Nessun vincolo.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <Link href="/signup">
              <Button size="lg" className="gap-2">
                Inizia la Beta
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Button>
            </Link>
            <Link href="/docs">
              <Button variant="outline" size="lg">
                Leggi la Documentazione
              </Button>
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
