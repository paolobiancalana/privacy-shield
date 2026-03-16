"use client";

import { ArrowUpCircleIcon } from "lucide-react";
import Link from "next/link";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  CardFooter,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PlanBadge } from "@/components/dashboard/plan-badge";
import type { BillingData } from "./page";

interface BillingViewProps {
  billing: BillingData;
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

const UPGRADEABLE_PLANS = ["free", "developer"];

export function BillingView({ billing }: BillingViewProps) {
  const tokensPercent =
    billing.monthlyTokenLimit > 0
      ? Math.min(
          100,
          Math.round(
            (billing.tokensUsed / billing.monthlyTokenLimit) * 100
          )
        )
      : 0;

  const showUpgrade = UPGRADEABLE_PLANS.includes(billing.planId);

  return (
    <div className="flex flex-col gap-6 max-w-3xl">
      <div>
        <h1 className="text-xl font-semibold">Fatturazione</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Gestisci il tuo abbonamento e visualizza l&apos;utilizzo.
        </p>
      </div>

      {/* Current plan card */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-4">
            <div className="flex flex-col gap-1">
              <CardTitle>Piano attuale</CardTitle>
              <CardDescription>Abbonamento mensile</CardDescription>
            </div>
            <PlanBadge plan={billing.planId} />
          </div>
        </CardHeader>

        <CardContent className="flex flex-col gap-5">
          {/* API Calls */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium">Chiamate API (questo mese)</span>
              <span className="tabular-nums text-muted-foreground">
                {formatNumber(billing.callsUsed)}
              </span>
            </div>
          </div>

          {/* Tokens */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium">Token creati</span>
              <span className="tabular-nums text-muted-foreground">
                {formatNumber(billing.tokensUsed)} /{" "}
                {formatNumber(billing.monthlyTokenLimit)}
              </span>
            </div>
            <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className={`h-full transition-all ${
                  tokensPercent >= 80 ? "bg-amber-500" : "bg-primary"
                }`}
                style={{ width: `${tokensPercent}%` }}
              />
            </div>
            {tokensPercent >= 80 && (
              <p className="text-xs text-amber-400">
                Stai usando il {tokensPercent}% della tua quota mensile di token.
              </p>
            )}
          </div>
        </CardContent>

        {showUpgrade && (
          <CardFooter className="flex items-center justify-between gap-4">
            <p className="text-xs text-muted-foreground">
              Passa a un piano superiore per limiti più alti e supporto prioritario.
            </p>
            <Link href="/pricing">
              <Button size="sm">
                <ArrowUpCircleIcon className="size-4" />
                Aggiorna piano
              </Button>
            </Link>
          </CardFooter>
        )}
      </Card>

      {/* Invoice history placeholder */}
      <Card>
        <CardHeader>
          <CardTitle>Storico fatture</CardTitle>
          <CardDescription>
            Fatture precedenti per il tuo abbonamento.
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-0">
          <div className="flex flex-col items-center justify-center py-10 text-center">
            <p className="text-sm text-muted-foreground">Nessuna fattura.</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Le fatture appariranno qui quando passerai a un piano a pagamento.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
