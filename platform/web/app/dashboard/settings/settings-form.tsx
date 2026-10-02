"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { SaveIcon, Trash2Icon, AlertTriangleIcon } from "lucide-react";
import { toast } from "sonner";

import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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
import { Separator } from "@/components/ui/separator";

interface SettingsFormProps {
  org: { id: string; name: string; slug: string } | null;
  isOwner: boolean;
}

export function SettingsForm({ org, isOwner }: SettingsFormProps) {
  const router = useRouter();

  const [name, setName] = useState(org?.name ?? "");
  const [slug, setSlug] = useState(org?.slug ?? "");
  const [isSaving, startSave] = useTransition();
  const [isDeleting, startDelete] = useTransition();

  function handleSave(e: React.FormEvent) {
    e.preventDefault();

    startSave(async () => {
      if (!org) return;

      try {
        const res = await fetch(`/api/orgs/${org.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: name.trim(), slug: slug.trim() }),
        });

        const data = await res.json();
        if (!res.ok) {
          toast.error(data.error || "Failed to save settings");
        } else {
          toast.success("Settings saved");
          router.refresh();
        }
      } catch (err) {
        toast.error("An error occurred while saving settings");
      }
    });
  }

  function handleDelete() {
    startDelete(async () => {
      if (!org) return;

      try {
        const res = await fetch(`/api/orgs/${org.id}`, {
          method: "DELETE",
        });

        const data = await res.json();
        if (!res.ok) {
          toast.error(data.error || "Failed to delete organization");
        } else {
          toast.success("Organization deleted");
          document.cookie =
            "ps_selected_org=; path=/; max-age=0; SameSite=Lax";
          router.push("/");
          router.refresh();
        }
      } catch (err) {
        toast.error("An error occurred while deleting organization");
      }
    });
  }

  if (!org) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-xl font-semibold">Impostazioni</h1>
        <p className="text-sm text-muted-foreground">Nessuna organizzazione trovata.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 max-w-2xl">
      <div>
        <h1 className="text-xl font-semibold">Impostazioni</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Gestisci le impostazioni della tua organizzazione.
        </p>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* General                                                              */}
      {/* ------------------------------------------------------------------ */}
      <Card>
        <CardHeader>
          <CardTitle>Generale</CardTitle>
          <CardDescription>
            Aggiorna il nome e lo slug della tua organizzazione.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSave} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="org-name">Nome organizzazione</Label>
              <Input
                id="org-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Acme Inc."
                disabled={!isOwner}
                required
                maxLength={80}
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="org-slug">Slug</Label>
              <div className="flex items-center gap-0">
                <span className="flex h-8 items-center rounded-l-lg border border-r-0 border-input bg-muted px-2.5 text-sm text-muted-foreground">
                  app/
                </span>
                <Input
                  id="org-slug"
                  value={slug}
                  onChange={(e) =>
                    setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-"))
                  }
                  placeholder="acme-inc"
                  disabled={!isOwner}
                  required
                  maxLength={40}
                  pattern="[a-z0-9-]+"
                  className="rounded-l-none"
                />
              </div>
              <p className="text-xs text-muted-foreground">
                Lowercase letters, numbers, and hyphens only.
              </p>
            </div>

            {isOwner && (
              <div className="flex justify-end">
                <Button type="submit" size="sm" disabled={isSaving}>
                  <SaveIcon className="size-4" />
                  {isSaving ? "Salvataggio…" : "Salva modifiche"}
                </Button>
              </div>
            )}

            {!isOwner && (
              <p className="text-xs text-muted-foreground">
                Solo i proprietari possono modificare queste impostazioni.
              </p>
            )}
          </form>
        </CardContent>
      </Card>

      {/* ------------------------------------------------------------------ */}
      {/* Danger zone                                                          */}
      {/* ------------------------------------------------------------------ */}
      {isOwner && (
        <Card className="border-destructive/40">
          <CardHeader>
            <CardTitle className="text-destructive">Zona pericolosa</CardTitle>
            <CardDescription>
              Azioni irreversibili. Procedi con cautela.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Separator className="mb-4" />
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-sm font-medium">Elimina organizzazione</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Elimina definitivamente la tua organizzazione e tutti i dati associati.
                  Questa azione non può essere annullata.
                </p>
              </div>

              <AlertDialog>
                <AlertDialogTrigger
                  render={
                    <Button
                      variant="destructive"
                      size="sm"
                      className="shrink-0"
                    />
                  }
                >
                  <Trash2Icon className="size-4" />
                  Elimina org
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle className="flex items-center gap-2">
                      <AlertTriangleIcon className="size-4 text-destructive" />
                      Eliminare &ldquo;{org.name}&rdquo;?
                    </AlertDialogTitle>
                    <AlertDialogDescription>
                      Questa operazione eliminerà definitivamente l&apos;organizzazione,
                      tutte le chiavi API, i dati di utilizzo e i record dei membri.
                      Questa azione non può essere annullata.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Annulla</AlertDialogCancel>
                    <AlertDialogAction
                      variant="destructive"
                      onClick={handleDelete}
                      disabled={isDeleting}
                    >
                      {isDeleting ? "Eliminazione…" : "Sì, elimina organizzazione"}
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
