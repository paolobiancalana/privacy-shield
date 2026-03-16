"use client";

import { useState } from "react";
import { KeyRoundIcon } from "lucide-react";
import { toast } from "sonner";

import { KeyCard, type ApiKey } from "@/components/dashboard/key-card";
import { KeyCreateDialog } from "@/components/dashboard/key-create-dialog";

interface KeysManagerProps {
  initialKeys: ApiKey[];
  orgId: string;
}

export function KeysManager({ initialKeys, orgId }: KeysManagerProps) {
  const [keys, setKeys] = useState<ApiKey[]>(initialKeys);

  function handleCreated(newKey: ApiKey) {
    setKeys((prev) => [newKey, ...prev]);
  }

  async function handleRevoke(keyId: string) {
    try {
      const res = await fetch(`/api/orgs/${orgId}/keys/${keyId}`, {
        method: "DELETE",
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(
          (body as { error?: string })?.error ?? "Failed to revoke key"
        );
      }

      setKeys((prev) =>
        prev.map((k) =>
          k.id === keyId
            ? { ...k, active: false, revoked_at: new Date().toISOString() }
            : k
        )
      );
      toast.success("API key revoked");
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Something went wrong";
      toast.error(message);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Chiavi API</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Gestisci le chiavi API della tua organizzazione.
          </p>
        </div>
        {orgId && (
          <KeyCreateDialog orgId={orgId} onCreated={handleCreated} />
        )}
      </div>

      {/* Key list */}
      {keys.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card py-16 text-center">
          <KeyRoundIcon className="mb-3 size-8 text-muted-foreground/50" />
          <p className="text-sm font-medium text-foreground">Nessuna chiave API</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Creane una per iniziare a usare l&apos;API.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {keys.map((key) => (
            <KeyCard key={key.id} apiKey={key} onRevoke={handleRevoke} />
          ))}
        </div>
      )}
    </div>
  );
}
