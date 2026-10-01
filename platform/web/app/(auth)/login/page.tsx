"use client";

import { Suspense } from "react";
import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";



// ---------------------------------------------------------------------------
// Error message humanizer
// ---------------------------------------------------------------------------

function friendlyError(msg: string): string {
  const m = msg.toLowerCase();
  if (m.includes("invalid login credentials") || m.includes("invalid credentials"))
    return "Email o password non corrette.";
  if (m.includes("email not confirmed"))
    return "Email non ancora confermata. Controlla la tua casella e clicca il link di attivazione.";
  if (m.includes("user not found"))
    return "Nessun account trovato con questa email.";
  if (m.includes("rate limit") || m.includes("too many requests"))
    return "Troppi tentativi. Aspetta qualche minuto e riprova.";
  if (m.includes("network") || m.includes("fetch"))
    return "Errore di rete. Controlla la connessione e riprova.";
  return msg;
}

// ---------------------------------------------------------------------------
// Inner component that uses useSearchParams
// ---------------------------------------------------------------------------

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [customError, setErrorMessage] = useState<string | null>(null);
  const errorMessage =
    customError ??
    (searchParams.get("error") === "auth"
      ? "Autenticazione non riuscita. Riprova o usa un metodo diverso."
      : null);

  const supabase = createClient();

  async function handleEmailLogin(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setErrorMessage(null);
    setLoading(true);

    const { error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    if (error) {
      setErrorMessage(friendlyError(error.message));
      setLoading(false);
      return;
    }

    router.push("/dashboard");
  }

  return (
    <Card className="w-full max-w-md bg-[#1a1a2e]">
      <CardHeader className="space-y-1 pb-2">
        <CardTitle className="text-center text-2xl font-semibold text-white">
          Bentornato
        </CardTitle>
        <CardDescription className="text-center text-[#888888]">
          Accedi al tuo account Privacy Shield
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4 pt-2">


        {errorMessage && (
          <div
            role="alert"
            className="flex items-start gap-2.5 rounded-lg border border-red-800/50 bg-red-950/40 px-3 py-3 text-sm text-red-300"
          >
            <svg className="mt-0.5 size-4 shrink-0 text-red-400" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clipRule="evenodd" />
            </svg>
            <span>{errorMessage}</span>
          </div>
        )}

        {/* Email/password form */}
        <form onSubmit={handleEmailLogin} className="space-y-3" noValidate>
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              placeholder="you@example.com"
              autoComplete="email"
              required
              disabled={loading}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label htmlFor="password">Password</Label>
              <Link
                href="/reset-password"
                className="text-xs text-[#3b82f6] hover:underline"
                tabIndex={0}
              >
                Password dimenticata?
              </Link>
            </div>
            <Input
              id="password"
              type="password"
              placeholder="••••••••"
              autoComplete="current-password"
              required
              disabled={loading}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>

          <Button
            type="submit"
            className="w-full"
            size="lg"
            disabled={loading}
          >
            {loading ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                Accesso in corso…
              </>
            ) : (
              "Accedi"
            )}
          </Button>
        </form>

        {/* Sign up link */}
        <p className="text-center text-sm text-[#888888]">
          Non hai un account?{" "}
          <Link
            href="/signup"
            className="text-[#3b82f6] hover:underline"
          >
            Registrati
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page — wraps LoginForm in Suspense so useSearchParams is valid
// ---------------------------------------------------------------------------

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0a0a0a] px-4">
      <Suspense
        fallback={
          <div className="flex size-8 items-center justify-center">
            <Loader2 className="size-6 animate-spin text-muted-foreground" />
          </div>
        }
      >
        <LoginForm />
      </Suspense>
    </div>
  );
}
