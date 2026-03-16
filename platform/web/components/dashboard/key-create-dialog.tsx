"use client";

import { useState } from "react";
import { PlusIcon, CopyIcon, CheckIcon, AlertTriangleIcon } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogClose,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ApiKey } from "./key-card";

interface KeyCreateDialogProps {
  orgId: string;
  onCreated: (key: ApiKey) => void;
}

type Environment = "live" | "test";

// Maps UI environment names to what the API/DB accepts.
// The DB check constraint allows: "live" | "test"
const ENV_TO_API: Record<Environment, string> = {
  live: "live",
  test: "test",
};

export function KeyCreateDialog({ orgId, onCreated }: KeyCreateDialogProps) {
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [environment, setEnvironment] = useState<Environment>("test");
  const [loading, setLoading] = useState(false);

  // Shown only after successful creation — full key value displayed once
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  function resetForm() {
    setLabel("");
    setEnvironment("test");
    setCreatedKey(null);
    setCopied(false);
  }

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) resetForm();
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);

    try {
      const res = await fetch(`/api/orgs/${orgId}/keys`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          label: label.trim() || "Untitled key",
          environment: ENV_TO_API[environment],
        }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          (body as { error?: string })?.error ?? "Failed to create key"
        );
      }

      // API returns: { key, key_id, key_prefix, label, environment, created_at }
      const data = (await res.json()) as {
        key: string;
        key_id: string;
        key_prefix: string;
        label: string;
        environment: string;
        created_at: string;
      };

      // Show the raw key once
      setCreatedKey(data.key);

      // Notify parent with a normalized ApiKey record
      onCreated({
        id: data.key_id,
        prefix: data.key_prefix,
        label: data.label,
        environment: data.environment,
        active: true,
        created_at: data.created_at,
        revoked_at: null,
      });

      toast.success("API key created");
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Something went wrong";
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }

  async function handleCopy() {
    if (!createdKey) return;
    await navigator.clipboard.writeText(createdKey);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger render={<Button size="sm" />}>
        <PlusIcon className="size-4" />
        Crea chiave
      </DialogTrigger>

      <DialogContent className="sm:max-w-md">
        {createdKey ? (
          /* ---------------------------------------------------------------- */
          /* Success state — show full key once                                */
          /* ---------------------------------------------------------------- */
          <>
            <DialogHeader>
              <DialogTitle>Chiave creata</DialogTitle>
              <DialogDescription>
                Copia la chiave API ora. Non verrà più mostrata.
              </DialogDescription>
            </DialogHeader>

            <div className="flex flex-col gap-3 py-2">
              {/* Warning banner */}
              <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-xs text-amber-400">
                <AlertTriangleIcon className="mt-0.5 size-3.5 shrink-0" />
                <span>
                  Questa chiave viene mostrata una sola volta. Salvala in un
                  luogo sicuro come un gestore di segreti o una variabile d&apos;ambiente.
                </span>
              </div>

              {/* Key display + copy */}
              <div className="flex items-center gap-2">
                <code className="flex-1 overflow-x-auto rounded-lg border border-border bg-muted px-3 py-2 font-mono text-xs text-foreground">
                  {createdKey}
                </code>
                <Button
                  type="button"
                  variant="outline"
                  size="icon-sm"
                  onClick={handleCopy}
                  aria-label="Copy API key"
                >
                  {copied ? (
                    <CheckIcon className="size-4 text-emerald-400" />
                  ) : (
                    <CopyIcon className="size-4" />
                  )}
                </Button>
              </div>
            </div>

            <DialogFooter showCloseButton={false}>
              <DialogClose render={<Button variant="outline" size="sm" />}>
                Fatto
              </DialogClose>
            </DialogFooter>
          </>
        ) : (
          /* ---------------------------------------------------------------- */
          /* Creation form                                                      */
          /* ---------------------------------------------------------------- */
          <form onSubmit={handleSubmit}>
            <DialogHeader>
              <DialogTitle>Crea chiave API</DialogTitle>
              <DialogDescription>
                Dai un nome alla chiave e scegli l&apos;ambiente.
              </DialogDescription>
            </DialogHeader>

            <div className="flex flex-col gap-4 py-4">
              {/* Label */}
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="key-label">Nome</Label>
                <Input
                  id="key-label"
                  placeholder="es. Server di produzione"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  maxLength={80}
                  required
                />
              </div>

              {/* Environment */}
              <div className="flex flex-col gap-1.5">
                <Label>Ambiente</Label>
                <div className="flex gap-2">
                  {(["test", "live"] as const).map((env) => (
                    <button
                      key={env}
                      type="button"
                      onClick={() => setEnvironment(env)}
                      className={[
                        "flex flex-1 items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium transition-colors",
                        environment === env
                          ? env === "live"
                            ? "border-emerald-500/60 bg-emerald-500/10 text-emerald-400"
                            : "border-amber-500/60 bg-amber-500/10 text-amber-400"
                          : "border-border text-muted-foreground hover:bg-muted",
                      ].join(" ")}
                    >
                      <span
                        className="size-1.5 rounded-full inline-block shrink-0"
                        style={{
                          backgroundColor:
                            environment === env
                              ? env === "live"
                                ? "#22c55e"
                                : "#f59e0b"
                              : "#555",
                        }}
                      />
                      {env === "live" ? "Live" : "Test"}
                    </button>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">
                  {environment === "live"
                    ? "Le chiavi Live elaborano dati reali. Usa solo in produzione."
                    : "Le chiavi Test sono sicure per sviluppo e CI."}
                </p>
              </div>
            </div>

            <DialogFooter showCloseButton={false}>
              <DialogClose render={<Button type="button" variant="outline" size="sm" />}>
                Annulla
              </DialogClose>
              <Button type="submit" size="sm" disabled={loading}>
                {loading ? "Creazione…" : "Crea chiave"}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
