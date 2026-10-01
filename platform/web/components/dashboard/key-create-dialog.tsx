"use client";

import { cn } from "@/lib/utils";

import { useState } from "react";
import { PlusIcon } from "lucide-react";
import { toast } from "sonner";
import { Button, buttonVariants } from "@/components/ui/button";
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
import { Alert, AlertDescription } from "@/components/ui/alert";
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from "@/components/ui/select";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Calendar } from "@/components/ui/calendar";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { format, addDays } from "date-fns";
import type { ApiKey } from "./api-key-table";

interface KeyCreateDialogProps {
  orgId: string;
  onCreated: (key: ApiKey, rawValue: string) => void;
}

type Environment = "live" | "test";

const EXPIRATION_OPTIONS = [
  { label: "7 days", value: "7d", days: 7 },
  { label: "30 days", value: "30d", days: 30 },
  { label: "60 days", value: "60d", days: 60 },
  { label: "90 days", value: "90d", days: 90 },
  { label: "Custom", value: "custom", days: 0 },
  { label: "Never", value: "never", days: -1 },
] as const;

export function KeyCreateDialog({ orgId, onCreated }: KeyCreateDialogProps) {
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState("");
  const [environment, setEnvironment] = useState<Environment>("test");
  const [expiration, setExpiration] = useState<string>("30d");
  const [customDate, setCustomDate] = useState<Date | undefined>(undefined);
  const [loading, setLoading] = useState(false);

  function resetForm() {
    setLabel("");
    setEnvironment("test");
    setExpiration("30d");
    setCustomDate(undefined);
  }

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) resetForm();
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);

    let expiresAt: string | null = null;
    if (expiration === "custom" && customDate) {
      expiresAt = customDate.toISOString();
    } else if (expiration !== "never") {
      const option = EXPIRATION_OPTIONS.find((o) => o.value === expiration);
      if (option && option.days > 0) {
        expiresAt = addDays(new Date(), option.days).toISOString();
      }
    }

    try {
      const res = await fetch(`/api/orgs/${orgId}/keys`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          label: label.trim() || "Untitled key",
          environment,
          expires_at: expiresAt,
        }),
      });

      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { error?: string };
        throw new Error(body.error ?? "Failed to create key");
      }

      const data = (await res.json()) as {
        key: string;
        key_id: string;
        key_prefix: string;
        label: string;
        environment: string;
        created_at: string;
        expires_at: string | null;
      };

      // Notify parent with both the record and the raw value for the one-time view
      onCreated({
        id: data.key_id,
        prefix: data.key_prefix,
        label: data.label,
        environment: data.environment as Environment,
        active: true,
        created_at: data.created_at,
        revoked_at: null,
        expires_at: data.expires_at,
      }, data.key);

      toast.success("Chiave API creata correttamente");
      setOpen(false);
      resetForm();
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Something went wrong";
      toast.error(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger
        className={cn(
          buttonVariants({ size: "sm" }),
          "h-9 px-4 font-medium shadow-sm transition-all hover:scale-[1.02] active:scale-[0.98] cursor-pointer"
        )}
      >
        <PlusIcon className="mr-2 size-4" />
        Nuova chiave
      </DialogTrigger>

      <DialogContent className="sm:max-w-[440px] bg-[#0c0c11] border-border/40 shadow-2xl p-0 overflow-hidden">
        <form onSubmit={handleSubmit} className="flex flex-col">
          <div className="p-6 pb-4">
            <DialogHeader className="mb-4">
              <DialogTitle className="text-xl font-bold tracking-tight">Crezione Nuova Chiave</DialogTitle>
              <DialogDescription className="text-muted-foreground/60">
                Genera una nuova chiave di accesso per i tuoi progetti.
              </DialogDescription>
            </DialogHeader>

            <Alert variant="warning" className="mb-6 rounded-xl border-amber-500/10 bg-amber-500/[0.03] py-3">
              <AlertDescription className="text-[11px] leading-relaxed text-amber-500/80">
                Questa chiave deve essere conservata in un luogo sicuro. Non potrai più visualizzarla una volta chiusa questa finestra.
              </AlertDescription>
            </Alert>

            <div className="flex flex-col gap-5">
              {/* Name */}
              <div className="flex flex-col gap-2">
                <Label htmlFor="key-label" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/50 pl-0.5">Nome</Label>
                <Input
                  id="key-label"
                  placeholder="es. My API Key"
                  className="h-11 border-border/40 bg-white/[0.02] hover:bg-white/[0.04] transition-all focus:ring-1 focus:ring-primary/20 rounded-xl"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  maxLength={80}
                  required
                  autoFocus
                />
              </div>

              {/* Expires In */}
              <div className="flex flex-col gap-2">
                <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/50 pl-0.5">Scadenza</Label>
                <div className="flex gap-2">
                  <Select value={expiration} onValueChange={(val) => val && setExpiration(val)}>
                    <SelectTrigger className="flex-1 h-11 border-border/40 bg-white/[0.02] rounded-xl hover:bg-white/[0.04]">
                      <SelectValue placeholder="Seleziona scadenza" />
                    </SelectTrigger>
                    <SelectContent>
                      {EXPIRATION_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value}>
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  {expiration === "custom" && (
                    <Popover>
                      <PopoverTrigger
                        className={cn(
                          buttonVariants({ variant: "outline" }),
                          "h-11 border-border/40 bg-white/[0.02] rounded-xl px-3 hover:bg-white/[0.04] cursor-pointer"
                        )}
                      >
                        {customDate ? format(customDate, "dd/MM/yyyy") : "Scegli data"}
                      </PopoverTrigger>
                      <PopoverContent className="w-auto p-0 border-border/40 shadow-2xl" align="end">
                        <Calendar 
                          selected={customDate} 
                          onSelect={setCustomDate} 
                        />
                      </PopoverContent>
                    </Popover>
                  )}
                </div>
              </div>

              {/* Environment */}
              <div className="flex flex-col gap-2">
                <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/50 pl-0.5">Ambiente</Label>
                <div className="flex gap-2.5">
                  {(["test", "live"] as const).map((env) => (
                    <button
                      key={env}
                      type="button"
                      onClick={() => setEnvironment(env)}
                      className={[
                        "flex flex-1 items-center justify-center gap-2 rounded-xl border px-3 py-2.5 text-sm font-medium transition-all duration-200 cursor-pointer",
                        environment === env
                          ? "border-primary/40 bg-primary/5 text-primary shadow-[0_0_15px_rgba(var(--primary-rgb),0.05)] ring-1 ring-primary/20"
                          : "border-border/40 bg-transparent text-muted-foreground/60 hover:bg-white/[0.03] hover:border-border/60 hover:text-muted-foreground",
                      ].join(" ")}
                    >
                      <div className={cn(
                        "size-1.5 rounded-full",
                        environment === env ? "bg-primary" : "bg-muted-foreground/40"
                      )} />
                      {env === "live" ? "Live" : "Test"}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          <DialogFooter className="bg-white/[0.02] border-t border-border/40 p-5 mt-4 sm:flex-row gap-3">
            <DialogClose
              className={cn(
                buttonVariants({ variant: "ghost" }),
                "flex-1 sm:flex-none h-11 border-transparent hover:bg-white/5 font-medium cursor-pointer"
              )}
            >
              Annulla
            </DialogClose>
            <Button 
                type="submit" 
                className="flex-1 sm:flex-none h-11 px-8 font-bold bg-primary text-primary-foreground hover:opacity-90 transition-opacity rounded-xl" 
                disabled={loading}
            >
              {loading ? "Generazione..." : "Generate token"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
