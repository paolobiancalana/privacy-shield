import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
  CardFooter,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Check, Minus } from "lucide-react";

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

type Plan = {
  id: string;
  name: string;
  price: string;
  period: string;
  description: string;
  cta: string;
  ctaHref: string;
  ctaVariant: "default" | "outline";
  highlighted: boolean;
  badge?: string;
  features: {
    rateLimit: string;
    tokens: string;
    apiKeys: string;
    support: string;
    sla: string;
    customModels: boolean;
    dedicatedInfra: boolean;
  };
};

const plans: Plan[] = [
  {
    id: "free",
    name: "Free",
    price: "€0",
    period: "/month",
    description: "Perfect for evaluation and personal projects.",
    cta: "Start Free",
    ctaHref: "/signup",
    ctaVariant: "outline",
    highlighted: false,
    features: {
      rateLimit: "10 req / min",
      tokens: "1 000 tokens / mo",
      apiKeys: "2 API keys",
      support: "Community",
      sla: "None",
      customModels: false,
      dedicatedInfra: false,
    },
  },
  {
    id: "developer",
    name: "Developer",
    price: "€19",
    period: "/month",
    description: "For individual developers building production apps.",
    cta: "Get Started",
    ctaHref: "/signup",
    ctaVariant: "outline",
    highlighted: false,
    features: {
      rateLimit: "60 req / min",
      tokens: "50 000 tokens / mo",
      apiKeys: "5 API keys",
      support: "Email",
      sla: "99.5% uptime",
      customModels: false,
      dedicatedInfra: false,
    },
  },
  {
    id: "business",
    name: "Business",
    price: "€79",
    period: "/month",
    description: "For teams processing high document volumes.",
    cta: "Get Started",
    ctaHref: "/signup",
    ctaVariant: "default",
    highlighted: true,
    badge: "Most Popular",
    features: {
      rateLimit: "200 req / min",
      tokens: "500 000 tokens / mo",
      apiKeys: "20 API keys",
      support: "Priority email",
      sla: "99.9% uptime",
      customModels: false,
      dedicatedInfra: false,
    },
  },
  {
    id: "enterprise",
    name: "Enterprise",
    price: "Custom",
    period: "",
    description: "Dedicated infrastructure and custom SLAs for large teams.",
    cta: "Contact Us",
    ctaHref: "mailto:enterprise@privacyshield.pro",
    ctaVariant: "outline",
    highlighted: false,
    features: {
      rateLimit: "1 000 req / min",
      tokens: "5 000 000 tokens / mo",
      apiKeys: "100 API keys",
      support: "Dedicated manager",
      sla: "99.99% uptime",
      customModels: true,
      dedicatedInfra: true,
    },
  },
];

// Feature comparison rows (order matters)
type FeatureKey = keyof Plan["features"];

const comparisonRows: { key: FeatureKey; label: string }[] = [
  { key: "rateLimit", label: "Rate limit" },
  { key: "tokens", label: "Tokens per month" },
  { key: "apiKeys", label: "API keys" },
  { key: "support", label: "Support" },
  { key: "sla", label: "SLA" },
  { key: "customModels", label: "Custom NER models" },
  { key: "dedicatedInfra", label: "Dedicated infrastructure" },
];

// ---------------------------------------------------------------------------
// Helper components
// ---------------------------------------------------------------------------

function FeatureValue({ value }: { value: string | boolean }) {
  if (typeof value === "boolean") {
    return value ? (
      <Check
        className="mx-auto h-4 w-4"
        style={{ color: "#10b981" }}
        aria-label="Included"
      />
    ) : (
      <Minus
        className="mx-auto h-4 w-4 text-muted-foreground"
        aria-label="Not included"
      />
    );
  }
  return <span className="text-sm text-foreground">{value}</span>;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function PricingPage() {
  return (
    <div className="px-6 py-24">
      {/* Header */}
      <div className="mx-auto max-w-3xl text-center">
        <h1 className="text-4xl font-bold tracking-tight text-foreground">
          Choose your plan
        </h1>
        <p className="mt-4 text-lg text-muted-foreground">
          Start for free. Upgrade as you scale. Cancel any time.
        </p>
      </div>

      {/* Plan cards */}
      <div className="mx-auto mt-12 grid max-w-6xl grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {plans.map((plan) => (
          <Card
            key={plan.id}
            className="relative flex flex-col"
            style={
              plan.highlighted
                ? {
                    borderColor: "#3b82f6",
                    boxShadow: "0 0 0 1px #3b82f6, 0 8px 32px rgba(59,130,246,0.15)",
                  }
                : undefined
            }
          >
            {plan.badge && (
              <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                <Badge>{plan.badge}</Badge>
              </div>
            )}

            <CardHeader className="pb-2">
              <CardTitle className="text-lg">{plan.name}</CardTitle>
              <CardDescription>{plan.description}</CardDescription>
            </CardHeader>

            <CardContent className="flex flex-1 flex-col gap-6">
              {/* Price */}
              <div className="flex items-end gap-1">
                <span
                  className="text-4xl font-bold tracking-tight"
                  style={{ color: plan.highlighted ? "#3b82f6" : undefined }}
                >
                  {plan.price}
                </span>
                {plan.period && (
                  <span className="mb-1 text-sm text-muted-foreground">
                    {plan.period}
                  </span>
                )}
              </div>

              {/* Key features */}
              <ul className="flex flex-1 flex-col gap-2">
                {[
                  plan.features.rateLimit,
                  plan.features.tokens,
                  plan.features.apiKeys,
                ].map((feat) => (
                  <li key={feat} className="flex items-center gap-2 text-sm text-foreground">
                    <Check
                      className="h-3.5 w-3.5 shrink-0"
                      style={{ color: "#10b981" }}
                      aria-hidden="true"
                    />
                    {feat}
                  </li>
                ))}
              </ul>
            </CardContent>

            <CardFooter>
              <Link href={plan.ctaHref} className="w-full">
                <Button variant={plan.ctaVariant} className="w-full">
                  {plan.cta}
                </Button>
              </Link>
            </CardFooter>
          </Card>
        ))}
      </div>

      {/* Feature comparison table */}
      <div className="mx-auto mt-20 max-w-6xl">
        <h2 className="mb-6 text-center text-2xl font-bold tracking-tight text-foreground">
          Full feature comparison
        </h2>

        <div className="overflow-x-auto rounded-xl border border-border">
          <table className="w-full text-left text-sm" aria-label="Plan feature comparison">
            <thead>
              <tr className="border-b border-border" style={{ background: "#0f0f1a" }}>
                <th
                  scope="col"
                  className="px-4 py-3 font-medium text-muted-foreground"
                >
                  Feature
                </th>
                {plans.map((p) => (
                  <th
                    key={p.id}
                    scope="col"
                    className="px-4 py-3 text-center font-medium"
                    style={
                      p.highlighted
                        ? { color: "#3b82f6" }
                        : { color: "#e0e0e0" }
                    }
                  >
                    {p.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {comparisonRows.map(({ key, label }, rowIdx) => (
                <tr
                  key={key}
                  className="border-b border-border last:border-0"
                  style={
                    rowIdx % 2 === 1
                      ? { background: "rgba(255,255,255,0.02)" }
                      : undefined
                  }
                >
                  <td className="px-4 py-3 text-muted-foreground">{label}</td>
                  {plans.map((p) => (
                    <td key={p.id} className="px-4 py-3 text-center">
                      <FeatureValue value={p.features[key]} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="mt-6 text-center text-sm text-muted-foreground">
          All plans include GDPR-compliant data handling, AES-256 token
          encryption, and automatic PII expiry.{" "}
          <Link
            href="mailto:enterprise@privacyshield.pro"
            className="underline underline-offset-4 transition-colors hover:text-foreground"
          >
            Contact us
          </Link>{" "}
          for volume discounts.
        </p>
      </div>
    </div>
  );
}
