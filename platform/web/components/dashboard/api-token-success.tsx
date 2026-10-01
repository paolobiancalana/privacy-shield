"use client";

import { useState } from "react";
import { CopyIcon, CheckIcon, AlertTriangleIcon, XIcon } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ApiTokenSuccessProps {
  token: string;
  onClose: () => void;
}

export function ApiTokenSuccess({ token, onClose }: ApiTokenSuccessProps) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    await navigator.clipboard.writeText(token);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  return (
    <div className="relative overflow-hidden rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-6 animate-in fade-in slide-in-from-top-4 duration-500">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-emerald-400">
            <CheckIcon className="size-4" />
            Nuova chiave creata con successo!
          </h3>
          <p className="mt-1 text-xs text-muted-foreground/80">
            Copia questa chiave ora e conservala in un posto sicuro. Per motivi di sicurezza, **non potrai più visualizzarla** una volta chiusa questa finestra.
          </p>
          
          <div className="mt-4 flex flex-col gap-3">
            <div className="flex items-center gap-2">
              <code className="flex-1 overflow-x-auto rounded-lg border border-emerald-500/20 bg-[#0a0a0f] px-4 py-2.5 font-mono text-[13px] text-emerald-50 px-3">
                {token}
              </code>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-10 border-emerald-500/20 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 hover:text-emerald-300 transition-all font-medium"
                onClick={handleCopy}
              >
                {copied ? (
                  <>
                    <CheckIcon className="mr-2 size-3.5" />
                    Copiato
                  </>
                ) : (
                  <>
                    <CopyIcon className="mr-2 size-3.5" />
                    Copia
                  </>
                )}
              </Button>
            </div>
            
            <div className="flex items-center gap-2 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-300">
              <AlertTriangleIcon className="size-3.5 shrink-0" />
              <span>
                Attenzione: Se perdi questa chiave, dovrai revocarla e generarne una nuova.
              </span>
            </div>
          </div>
        </div>
        
        <button
          onClick={onClose}
          className="rounded-lg p-1 text-muted-foreground/50 hover:bg-white/5 hover:text-white transition-colors"
          aria-label="Chiudi avviso"
        >
          <XIcon className="size-4" />
        </button>
      </div>
    </div>
  );
}
