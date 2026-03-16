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
        <h1 className="text-xl font-semibold">Billing</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Manage your subscription and view usage.
        </p>
      </div>

      {/* Current plan card */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-4">
            <div className="flex flex-col gap-1">
              <CardTitle>Current plan</CardTitle>
              <CardDescription>Monthly subscription</CardDescription>
            </div>
            <PlanBadge plan={billing.planId} />
          </div>
        </CardHeader>

        <CardContent className="flex flex-col gap-5">
          {/* API Calls */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium">API Calls (this month)</span>
              <span className="tabular-nums text-muted-foreground">
                {formatNumber(billing.callsUsed)}
              </span>
            </div>
          </div>

          {/* Tokens */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium">Tokens Created</span>
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
                You are using {tokensPercent}% of your monthly token quota.
              </p>
            )}
          </div>
        </CardContent>

        {showUpgrade && (
          <CardFooter className="flex items-center justify-between gap-4">
            <p className="text-xs text-muted-foreground">
              Upgrade to get higher limits and priority support.
            </p>
            <Link href="/pricing">
              <Button size="sm">
                <ArrowUpCircleIcon className="size-4" />
                Upgrade
              </Button>
            </Link>
          </CardFooter>
        )}
      </Card>

      {/* Invoice history placeholder */}
      <Card>
        <CardHeader>
          <CardTitle>Invoice history</CardTitle>
          <CardDescription>
            Past invoices for your subscription.
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-0">
          <div className="flex flex-col items-center justify-center py-10 text-center">
            <p className="text-sm text-muted-foreground">No invoices yet.</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Your invoices will appear here once you upgrade to a paid plan.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
