"use client";

import { useState, useEffect } from "react";
import { KeyRoundIcon, BookOpenIcon, TerminalIcon, ExternalLinkIcon } from "lucide-react";
import { toast } from "sonner";

import { ApiKeyTable, type ApiKey } from "@/components/dashboard/api-key-table";
import { KeyCreateDialog } from "@/components/dashboard/key-create-dialog";
import { ApiTokenSuccess } from "@/components/dashboard/api-token-success";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";

interface KeysManagerProps {
  initialKeys: ApiKey[];
  orgId: string;
}

export function KeysManager({ initialKeys, orgId }: KeysManagerProps) {
  const [keys, setKeys] = useState<ApiKey[]>(initialKeys);
  const [searchQuery, setSearchQuery] = useState("");
  const [newlyCreatedToken, setNewlyCreatedToken] = useState<string | null>(null);
  const [keyToRevoke, setKeyToRevoke] = useState<string | null>(null);
  const [isRevoking, setIsRevoking] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  function handleCreated(key: ApiKey, rawValue: string) {
    setKeys((prev) => [key, ...prev]);
    setNewlyCreatedToken(rawValue);
    // Scroll to top to ensure the banner is visible
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function handleRevokeConfirm() {
    if (!keyToRevoke) return;
    
    setIsRevoking(true);
    try {
      const res = await fetch(`/api/orgs/${orgId}/keys/${keyToRevoke}`, {
        method: "DELETE",
      });

      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { error?: string };
        throw new Error(body.error ?? "Failed to revoke key");
      }

      setKeys((prev) => prev.filter((k) => k.id !== keyToRevoke));
      toast.success("Chiave API revocata con successo");
      setKeyToRevoke(null);
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Something went wrong";
      toast.error(message);
    } finally {
      setIsRevoking(false);
    }
  }

  function handleRevokeRequest(keyId: string) {
    setKeyToRevoke(keyId);
  }

  if (!mounted) {
    return <div className="min-h-screen" />; // Placeholder to avoid layout shift
  }

  return (
    <div className="flex flex-col gap-8 max-w-6xl mx-auto pb-20 animate-in fade-in duration-700">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-6 border-b border-border/40 pb-8">
        <div className="space-y-1">
          <h1 className="text-3xl font-bold tracking-tight text-foreground">Chiavi di Accesso</h1>
          <p className="text-muted-foreground text-sm max-w-md leading-relaxed">
            Gestisci i token di accesso per interagire con l&apos;API di Privacy Shield. 
            Queste chiavi hanno i permessi completi per la tua organizzazione.
          </p>
        </div>
        
        <div className="flex items-center gap-3">
          <div className="hidden sm:flex items-center gap-4 mr-2">
            <a 
              href="https://docs.privacyshield.pro/api" 
              target="_blank" 
              className="group flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-primary transition-colors"
            >
              <BookOpenIcon className="size-3.5 opacity-50 group-hover:opacity-100" />
              API Docs
              <ExternalLinkIcon className="size-3 opacity-0 group-hover:opacity-40 -ml-0.5" />
            </a>
            <a 
              href="https://docs.privacyshield.pro/cli" 
              target="_blank" 
              className="group flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-primary transition-colors"
            >
              <TerminalIcon className="size-3.5 opacity-50 group-hover:opacity-100" />
              CLI Docs
              <ExternalLinkIcon className="size-3 opacity-0 group-hover:opacity-40 -ml-0.5" />
            </a>
          </div>
          {orgId && (
            <KeyCreateDialog orgId={orgId} onCreated={handleCreated} />
          )}
        </div>
      </div>

      {/* One-time Success Banner */}
      {newlyCreatedToken && (
        <ApiTokenSuccess 
          token={newlyCreatedToken} 
          onClose={() => setNewlyCreatedToken(null)} 
        />
      )}

      {/* Key Table Section */}
      <div className="space-y-4">
        <ApiKeyTable 
          keys={keys} 
          onRevoke={handleRevokeRequest}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
        />
        
        <AlertDialog 
          open={!!keyToRevoke} 
          onOpenChange={(open) => !open && setKeyToRevoke(null)}
        >
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Revoca Chiave API</AlertDialogTitle>
              <AlertDialogDescription>
                Sei sicuro di voler revocare questa chiave? Questa azione non può essere annullata 
                e tutte le applicazioni che utilizzano questo token perderanno l&apos;accesso.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel disabled={isRevoking}>Annulla</AlertDialogCancel>
              <AlertDialogAction 
                onClick={(e) => {
                  e.preventDefault();
                  handleRevokeConfirm();
                }}
                disabled={isRevoking}
                variant="destructive"
              >
                {isRevoking ? "Revoca in corso..." : "Revoca Chiave"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
        
        {keys.length === 0 && !searchQuery && (
          <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border/60 bg-white/[0.01] py-20 text-center">
            <div className="rounded-full bg-primary/5 p-4 mb-4">
              <KeyRoundIcon className="size-8 text-primary/40" />
            </div>
            <h3 className="text-base font-semibold text-foreground">Nessuna chiave configurata</h3>
            <p className="mt-2 text-sm text-muted-foreground max-w-xs mx-auto">
              Per iniziare a proteggere i tuoi progetti, genera la tua prima chiave API.
            </p>
            <div className="mt-6">
              {orgId && (
                <KeyCreateDialog orgId={orgId} onCreated={handleCreated} />
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
