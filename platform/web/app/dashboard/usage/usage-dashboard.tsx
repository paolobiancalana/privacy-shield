"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useTransition } from "react";
import {
  ActivityIcon,
  KeyRoundIcon,
  ZapIcon,
  PercentIcon,
} from "lucide-react";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import type { UsageSummary } from "./page";

interface UsageDashboardProps {
  summary: UsageSummary;
  activeDays: number;
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

const DAY_OPTIONS = [
  { value: "7", label: "7 days" },
  { value: "30", label: "30 days" },
  { value: "90", label: "90 days" },
] as const;

function UsageDashboardInner({ summary, activeDays }: UsageDashboardProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();

  function handleTabChange(value: string) {
    startTransition(() => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("days", value);
      router.push(`/dashboard/usage?${params.toString()}`);
    });
  }

  const summaryCards = [
    {
      title: "Total Calls",
      value: formatNumber(summary.totalCalls),
      description: `Last ${activeDays} days`,
      icon: ActivityIcon,
      color: "text-blue-400",
    },
    {
      title: "Tokens Created",
      value: formatNumber(summary.tokensCreated),
      description: `Last ${activeDays} days`,
      icon: KeyRoundIcon,
      color: "text-violet-400",
    },
    {
      title: "Monthly Usage",
      value: `${summary.percentUsed}%`,
      description: `of ${formatNumber(summary.monthlyLimit)} token limit`,
      icon: PercentIcon,
      color:
        summary.percentUsed >= 90
          ? "text-red-400"
          : summary.percentUsed >= 70
            ? "text-amber-400"
            : "text-emerald-400",
    },
    {
      title: "Avg Latency (p95)",
      value:
        summary.avgLatencyMs !== null
          ? `${summary.avgLatencyMs} ms`
          : "—",
      description: `Last ${activeDays} days`,
      icon: ZapIcon,
      color: "text-amber-400",
    },
  ];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">Usage</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Monitor your API consumption and performance.
        </p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {summaryCards.map((card) => {
          const Icon = card.icon;
          return (
            <Card key={card.title}>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardDescription>{card.title}</CardDescription>
                  <Icon className={`size-4 shrink-0 ${card.color}`} />
                </div>
                <CardTitle className="text-2xl font-semibold tabular-nums">
                  {card.value}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground">
                  {card.description}
                </p>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Monthly usage progress */}
      <Card>
        <CardHeader>
          <CardTitle>Monthly Quota</CardTitle>
          <CardDescription>Resets on the 1st of each month.</CardDescription>
        </CardHeader>
        <CardContent className="pt-0">
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium">
                {formatNumber(
                  Math.round(
                    (summary.percentUsed / 100) * summary.monthlyLimit
                  )
                )}{" "}
                / {formatNumber(summary.monthlyLimit)} tokens
              </span>
              <span className="text-muted-foreground tabular-nums">
                {summary.percentUsed}%
              </span>
            </div>
            <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className={`h-full transition-all ${
                  summary.percentUsed >= 90
                    ? "bg-red-500"
                    : summary.percentUsed >= 70
                      ? "bg-amber-500"
                      : "bg-primary"
                }`}
                style={{ width: `${summary.percentUsed}%` }}
              />
            </div>
          </div>
          {summary.percentUsed >= 80 && (
            <div className="mt-3 flex items-center gap-2">
              <Badge
                variant="outline"
                className="border-amber-500/40 bg-amber-500/10 text-amber-400 text-xs"
              >
                {summary.percentUsed >= 95 ? "Critical" : "Warning"}
              </Badge>
              <span className="text-xs text-muted-foreground">
                {summary.percentUsed >= 95
                  ? "Approaching your monthly limit. Upgrade to avoid disruptions."
                  : "You are using more than 80% of your monthly quota."}
              </span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Daily breakdown */}
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <CardTitle>Daily Breakdown</CardTitle>
              <CardDescription>Per-day API activity.</CardDescription>
            </div>

            <Tabs
              value={String(activeDays)}
              onValueChange={handleTabChange}
            >
              <TabsList>
                {DAY_OPTIONS.map((opt) => (
                  <TabsTrigger key={opt.value} value={opt.value}>
                    {opt.label}
                  </TabsTrigger>
                ))}
              </TabsList>
              {DAY_OPTIONS.map((opt) => (
                <TabsContent key={opt.value} value={opt.value} />
              ))}
            </Tabs>
          </div>
        </CardHeader>

        <CardContent className="pt-0">
          {summary.dailyRows.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <ActivityIcon className="mb-2 size-8 text-muted-foreground/40" />
              <p className="text-sm text-muted-foreground">
                No usage data for this period.
              </p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Date</TableHead>
                  <TableHead className="text-right">Tokenize</TableHead>
                  <TableHead className="text-right">Rehydrate</TableHead>
                  <TableHead className="text-right">Tokens</TableHead>
                  <TableHead className="text-right">p95 Latency</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {summary.dailyRows.map((row) => (
                  <TableRow key={row.date}>
                    <TableCell className="text-muted-foreground">
                      {formatDate(row.date)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.tokenize_calls.toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.rehydrate_calls.toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">
                      {row.tokens_created.toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-muted-foreground">
                      {row.detection_ms_p95 !== null
                        ? `${row.detection_ms_p95} ms`
                        : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export function UsageDashboard(props: UsageDashboardProps) {
  return (
    <Suspense fallback={null}>
      <UsageDashboardInner {...props} />
    </Suspense>
  );
}
