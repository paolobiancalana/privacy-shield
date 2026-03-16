"use client";

import { useState } from "react";
import { KeyRoundIcon, TrashIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

export interface ApiKey {
  id: string;
  /** Displayed prefix, e.g. "ps_live_ab..." */
  prefix: string;
  label: string | null;
  environment: string;
  /** true = active, false = revoked */
  active: boolean;
  created_at: string;
  revoked_at: string | null;
  last_used_at?: string | null;
}

interface KeyCardProps {
  apiKey: ApiKey;
  onRevoke: (keyId: string) => Promise<void>;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function isLiveEnv(env: string): boolean {
  return env === "live" || env === "production";
}

export function KeyCard({ apiKey, onRevoke }: KeyCardProps) {
  const [loading, setLoading] = useState(false);

  async function handleRevoke() {
    setLoading(true);
    try {
      await onRevoke(apiKey.id);
    } finally {
      setLoading(false);
    }
  }

  const isRevoked = !apiKey.active;
  const live = isLiveEnv(apiKey.environment);

  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-border bg-card px-4 py-3">
      {/* Left: icon + info */}
      <div className="flex min-w-0 items-center gap-3">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted">
          <KeyRoundIcon className="size-4 text-muted-foreground" />
        </div>

        <div className="flex min-w-0 flex-col gap-0.5">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-sm text-foreground">
              {apiKey.prefix}
            </span>
            {/* Environment badge */}
            {live ? (
              <Badge
                variant="outline"
                className="border-emerald-500/40 bg-emerald-500/10 text-emerald-400 text-xs"
              >
                Live
              </Badge>
            ) : (
              <Badge
                variant="outline"
                className="border-amber-500/40 bg-amber-500/10 text-amber-400 text-xs"
              >
                Test
              </Badge>
            )}
            {/* Status badge */}
            {isRevoked && (
              <Badge variant="destructive" className="text-xs">
                Revoked
              </Badge>
            )}
          </div>

          <div className="flex items-center gap-3 text-xs text-muted-foreground flex-wrap">
            {apiKey.label && (
              <span className="truncate">{apiKey.label}</span>
            )}
            <span>Creata il {formatDate(apiKey.created_at)}</span>
            {apiKey.revoked_at && (
              <span>Revocata il {formatDate(apiKey.revoked_at)}</span>
            )}
            {apiKey.last_used_at && !isRevoked && (
              <span>Ultimo utilizzo {formatDate(apiKey.last_used_at)}</span>
            )}
          </div>
        </div>
      </div>

      {/* Right: revoke button */}
      {!isRevoked && (
        <AlertDialog>
          <AlertDialogTrigger
            render={
              <Button
                variant="ghost"
                size="icon-sm"
                className="shrink-0 text-muted-foreground hover:text-destructive"
                aria-label="Revoca chiave"
              />
            }
          >
            <TrashIcon className="size-4" />
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Revocare la chiave API?</AlertDialogTitle>
              <AlertDialogDescription>
                Tutte le richieste che usano{" "}
                <code className="rounded bg-muted px-1 font-mono text-xs text-foreground">
                  {apiKey.prefix}
                </code>{" "}
                smetteranno di funzionare immediatamente. Questa azione non può essere annullata.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Annulla</AlertDialogCancel>
              <AlertDialogAction
                variant="destructive"
                onClick={handleRevoke}
                disabled={loading}
              >
                {loading ? "Revoca in corso…" : "Revoca chiave"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
    </div>
  );
}
