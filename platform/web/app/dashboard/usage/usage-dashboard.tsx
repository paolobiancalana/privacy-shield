"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState, useEffect, useCallback, Suspense, useTransition } from "react";
import {
  ActivityIcon,
  KeyRoundIcon,
  ZapIcon,
  PercentIcon,
  RefreshCwIcon,
} from "lucide-react";

import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { UsageSummary } from "./page";

interface UsageDashboardProps {
  summary: UsageSummary;
  activeDays: number;
  orgId?: string;
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("it-IT", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

const DAY_OPTIONS = [
  { value: "7", label: "7 giorni" },
  { value: "30", label: "30 giorni" },
  { value: "90", label: "90 giorni" },
] as const;

function UsageDashboardInner({ summary, activeDays, orgId }: UsageDashboardProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();

  const [liveSummary, setLiveSummary] = useState<UsageSummary>(summary);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Sync state if server prop changes
  useEffect(() => {
    setLiveSummary(summary);
  }, [summary]);

  // Real-time polling function
  const fetchLive = useCallback(async (showSpin = false) => {
    if (!orgId) return;
    if (showSpin) setIsRefreshing(true);
    try {
      const res = await fetch(`/api/orgs/${orgId}/usage?period=${activeDays}d`, {
        cache: "no-store",
      });
      if (res.ok) {
        const json = await res.json();
        if (json.summary) {
          setLiveSummary(json.summary);
        }
      }
    } catch (e) {
      console.warn("[UsageDashboard] Polling error:", e);
    } finally {
      if (showSpin) {
        setTimeout(() => setIsRefreshing(false), 500);
      }
    }
  }, [orgId, activeDays]);

  // Live auto-refresh: poll every 5s and on window focus
  useEffect(() => {
    if (!orgId) return;

    // Fetch immediately on mount in case server had stale cache
    fetchLive(false);

    const interval = setInterval(() => {
      fetchLive(false);
    }, 5000);

    const handleFocus = () => {
      fetchLive(false);
    };

    window.addEventListener("focus", handleFocus);

    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", handleFocus);
    };
  }, [orgId, fetchLive]);

  function handleTabChange(value: string) {
    startTransition(() => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("days", value);
      router.push(`/dashboard/usage?${params.toString()}`);
    });
  }

  const summaryCards = [
    {
      title: "Chiamate totali",
      value: formatNumber(liveSummary.totalCalls),
      description: `Ultimi ${activeDays} giorni`,
      icon: ActivityIcon,
      color: "text-blue-400",
    },
    {
      title: "Token creati",
      value: formatNumber(liveSummary.tokensCreated),
      description: `Ultimi ${activeDays} giorni`,
      icon: KeyRoundIcon,
      color: "text-violet-400",
    },
    {
      title: "Utilizzo mensile",
      value: `${liveSummary.percentUsed}%`,
      description: `del limite di ${formatNumber(liveSummary.monthlyLimit)} token`,
      icon: PercentIcon,
      color:
        liveSummary.percentUsed >= 90
          ? "text-red-400"
          : liveSummary.percentUsed >= 70
            ? "text-amber-400"
            : "text-emerald-400",
    },
    {
      title: "Latenza media (p95)",
      value:
        liveSummary.avgLatencyMs !== null
          ? `${liveSummary.avgLatencyMs} ms`
          : "—",
      description: `Ultimi ${activeDays} giorni`,
      icon: ZapIcon,
      color: "text-amber-400",
    },
  ];

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Utilizzo</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Monitora il consumo e le prestazioni delle tue API in tempo reale.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-400 font-medium">
            <span className="relative flex size-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex size-2 rounded-full bg-emerald-500"></span>
            </span>
            Live (5s)
          </div>

          <Button
            variant="ghost"
            size="icon"
            onClick={() => fetchLive(true)}
            disabled={isRefreshing}
            className="size-8 text-muted-foreground hover:text-foreground cursor-pointer"
            title="Aggiorna ora"
          >
            <RefreshCwIcon className={cn("size-3.5", isRefreshing && "animate-spin")} />
          </Button>
        </div>
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
          <CardTitle>Quota mensile</CardTitle>
          <CardDescription>Si resetta il 1° di ogni mese.</CardDescription>
        </CardHeader>
        <CardContent className="pt-0">
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium">
                {formatNumber(
                  Math.round(
                    (liveSummary.percentUsed / 100) * liveSummary.monthlyLimit
                  )
                )}{" "}
                / {formatNumber(liveSummary.monthlyLimit)} tokens
              </span>
              <span className="text-muted-foreground tabular-nums">
                {liveSummary.percentUsed}%
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                className={cn(
                  "h-full transition-all duration-500 ease-out",
                  liveSummary.percentUsed >= 90
                    ? "bg-red-500"
                    : liveSummary.percentUsed >= 70
                      ? "bg-amber-500"
                      : "bg-primary"
                )}
                style={{ width: `${Math.min(100, liveSummary.percentUsed)}%` }}
              />
            </div>
            {liveSummary.percentUsed >= 90 && (
              <p className="text-xs text-red-400">
                Attenzione: hai quasi esaurito la quota mensile del tuo piano.
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Daily activity table */}
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <CardTitle>Dettaglio giornaliero</CardTitle>
              <CardDescription>Attività API giornaliera.</CardDescription>
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
          {liveSummary.dailyRows.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <ActivityIcon className="mb-2 size-8 text-muted-foreground/40" />
              <p className="text-sm text-muted-foreground">
                Nessun dato di utilizzo per questo periodo.
              </p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Data</TableHead>
                  <TableHead className="text-right">Tokenizza</TableHead>
                  <TableHead className="text-right">Reidrata</TableHead>
                  <TableHead className="text-right">Flush</TableHead>
                  <TableHead className="text-right">Token</TableHead>
                  <TableHead className="text-right">Latenza p95</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {liveSummary.dailyRows.map((row) => (
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
                      {row.flush_calls.toLocaleString()}
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
