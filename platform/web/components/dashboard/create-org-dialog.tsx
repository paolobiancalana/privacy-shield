"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { PlusIcon, Building2Icon, Loader2Icon } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface CreateOrgDialogProps {
  trigger?: React.ReactNode;
  onCreated?: (org: { id: string; name: string; slug: string }) => void;
  className?: string;
}

export function CreateOrgDialog({ trigger, onCreated, className }: CreateOrgDialogProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugManuallyEdited, setSlugManuallyEdited] = useState(false);
  const [loading, setLoading] = useState(false);

  function slugify(text: string) {
    return text
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }

  function handleNameChange(val: string) {
    setName(val);
    if (!slugManuallyEdited) {
      setSlug(slugify(val));
    }
  }

  function handleSlugChange(val: string) {
    setSlugManuallyEdited(true);
    setSlug(slugify(val));
  }

  function resetForm() {
    setName("");
    setSlug("");
    setSlugManuallyEdited(false);
  }

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (!next) resetForm();
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      toast.error("Inserisci il nome dell'organizzazione");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch("/api/orgs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          slug: slug.trim() || slugify(name),
        }),
      });

      const body = await res.json();
      if (!res.ok) {
        throw new Error(body.error ?? "Impossibile creare l'organizzazione");
      }

      const org = body.organization;
      // Select new organization via cookie
      document.cookie = `ps_selected_org=${org.id}; path=/; max-age=31536000; SameSite=Lax`;

      toast.success(`Organizzazione "${org.name}" creata con successo!`);
      setOpen(false);
      resetForm();

      if (onCreated) {
        onCreated(org);
      }

      router.refresh();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Errore durante la creazione";
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger
        className={cn(
          !trigger &&
            cn(
              buttonVariants({ size: "sm" }),
              "h-9 px-3 font-medium transition-all cursor-pointer"
            ),
          className
        )}
      >
        {trigger ? (
          trigger
        ) : (
          <span className="flex items-center gap-1.5">
            <PlusIcon className="size-4" />
            Nuova organizzazione
          </span>
        )}
      </DialogTrigger>

      <DialogContent className="sm:max-w-[420px] bg-[#0c0c11] border-border/40 shadow-2xl p-0 overflow-hidden">
        <form onSubmit={handleSubmit} className="flex flex-col">
          <div className="p-6 pb-4">
            <DialogHeader className="mb-4">
              <div className="flex items-center gap-2 mb-1">
                <div className="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Building2Icon className="size-4" />
                </div>
                <DialogTitle className="text-xl font-bold tracking-tight">Nuova Organizzazione</DialogTitle>
              </div>
              <DialogDescription className="text-muted-foreground/60 text-xs">
                Crea un nuovo spazio per isolare chiavi API, log e impostazioni del tuo team o cliente.
              </DialogDescription>
            </DialogHeader>

            <div className="flex flex-col gap-4 mt-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="org-name" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/50">
                  Nome Organizzazione
                </Label>
                <Input
                  id="org-name"
                  placeholder="es. Acme Corp o Studio Legale"
                  className="h-10 border-border/40 bg-white/[0.02] focus:ring-1 focus:ring-primary/20 rounded-xl"
                  value={name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  maxLength={60}
                  required
                  autoFocus
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="org-slug" className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/50">
                  Identificativo (Slug)
                </Label>
                <div className="relative">
                  <Input
                    id="org-slug"
                    placeholder="es. acme-corp"
                    className="h-10 border-border/40 bg-white/[0.02] focus:ring-1 focus:ring-primary/20 rounded-xl font-mono text-xs"
                    value={slug}
                    onChange={(e) => handleSlugChange(e.target.value)}
                    maxLength={60}
                    required
                  />
                </div>
                <p className="text-[10px] text-muted-foreground/40 pl-0.5">
                  Usato nei percorsi e nelle chiamate API per identificare univocamente l&apos;organizzazione.
                </p>
              </div>
            </div>
          </div>

          <DialogFooter className="border-t border-border/40 bg-white/[0.01] px-6 py-4 flex items-center justify-between sm:justify-end gap-2">
            <DialogClose
              type="button"
              className={cn(
                buttonVariants({ variant: "ghost", size: "sm" }),
                "rounded-xl h-10 px-4 text-xs font-medium cursor-pointer"
              )}
              disabled={loading}
            >
              Annulla
            </DialogClose>
            <Button
              type="submit"
              size="sm"
              disabled={loading || !name.trim()}
              className="rounded-xl h-10 px-5 text-xs font-medium cursor-pointer"
            >
              {loading ? (
                <>
                  <Loader2Icon className="mr-2 size-3.5 animate-spin" />
                  Creazione...
                </>
              ) : (
                "Crea Organizzazione"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
