"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { 
  Loader2, 
  CircleCheck, 
  Eye, 
  EyeOff, 
  RefreshCw, 
  Check
} from "lucide-react";
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
  if (m.includes("user already registered") || m.includes("already been registered"))
    return "Esiste già un account con questa email. Prova ad accedere.";
  if (m.includes("invalid email"))
    return "Indirizzo email non valido.";
  if (m.includes("password should be at least"))
    return "La password deve essere di almeno 6 caratteri.";
  if (m.includes("rate limit") || m.includes("too many requests"))
    return "Troppi tentativi. Aspetta qualche minuto e riprova.";
  if (m.includes("database error") || m.includes("unexpected_failure") || m.includes("null value"))
    return "Si è verificato un errore durante la creazione dell'account. Riprova tra qualche istante.";
  if (m.includes("email not confirmed"))
    return "Email non ancora confermata. Controlla la tua casella e clicca il link di attivazione.";
  if (m.includes("invalid login credentials") || m.includes("invalid credentials"))
    return "Email o password non corrette.";
  if (m.includes("network") || m.includes("fetch"))
    return "Errore di rete. Controlla la connessione e riprova.";
  return msg;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const emailRegex = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
  const isEmailValid = email === "" || emailRegex.test(email);

  // Password strength calculation
  const getPasswordStrength = (pwd: string) => {
    let score = 0;
    if (pwd.length >= 10) score++;
    if (/[A-Z]/.test(pwd)) score++;
    if (/[0-9]/.test(pwd)) score++;
    if (/[^A-Za-z0-9]/.test(pwd)) score++;
    return score;
  };

  const strength = getPasswordStrength(password);
  const strengthPercentage = (strength / 4) * 100;
  
  const getStrengthColor = (s: number) => {
    if (s <= 1) return "bg-red-500";
    if (s <= 2) return "bg-orange-500";
    if (s <= 3) return "bg-yellow-500";
    return "bg-emerald-500";
  };

  const generateSecurePassword = () => {
    const charset = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*()_+~`|}{[]:;?><,./-=";
    let retVal = "";
    for (let i = 0, n = charset.length; i < 16; ++i) {
      retVal += charset.charAt(Math.floor(Math.random() * n));
    }
    setPassword(retVal);
    if (!showPassword) setShowPassword(true);
  };

  const supabase = createClient();

  async function handleSignup(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setErrorMessage(null);
    setLoading(true);

    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        emailRedirectTo: `${window.location.origin}/auth/confirm`,
      },
    });

    if (error) {
      setErrorMessage(friendlyError(error.message));
      setLoading(false);
      return;
    }

    // When mailer_autoconfirm is ON in Supabase, signUp returns a live session
    // immediately — no email confirmation step. Redirect straight to dashboard.
    // When autoconfirm is OFF, data.session is null and we show the email prompt.
    if (data.session) {
      router.push("/dashboard");
      return;
    }

    // No session yet — email confirmation is required.
    setSuccess(true);
    setLoading(false);
  }



  // -------------------------------------------------------------------------
  // Success state
  // -------------------------------------------------------------------------
  if (success) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#0a0a0a] px-4">
        <Card className="w-full max-w-md bg-[#1a1a2e]">
          <CardContent className="flex flex-col items-center gap-4 py-10 text-center">
            <div className="flex size-12 items-center justify-center rounded-full bg-emerald-950/50 ring-1 ring-emerald-800/40">
              <CircleCheck className="size-6 text-emerald-400" />
            </div>
            <div className="space-y-1">
              <h2 className="text-lg font-semibold text-white">Controlla la tua email</h2>
              <p className="text-sm text-[#888888]">
                Abbiamo inviato un link di conferma a{" "}
                <span className="text-[#e0e0e0]">{email}</span>. Clicca il link
                per attivare il tuo account.
              </p>
            </div>
            <Link
              href="/login"
              className="mt-2 text-sm text-[#3b82f6] hover:underline"
            >
              Torna al login
            </Link>
          </CardContent>
        </Card>
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // Sign up form
  // -------------------------------------------------------------------------
  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0a0a0a] px-4">
      <Card className="w-full max-w-md bg-[#1a1a2e]">
        <CardHeader className="space-y-1 pb-2">
          <CardTitle className="text-center text-2xl font-semibold text-white">
            Crea il tuo account
          </CardTitle>
          <CardDescription className="text-center text-[#888888]">
            Inizia a proteggere i tuoi dati con Privacy Shield
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
          <form onSubmit={handleSignup} className="space-y-4">
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label htmlFor="email">Email</Label>
                {!isEmailValid && (
                  <span className="text-[10px] text-red-400">Email non valida</span>
                )}
              </div>
              <Input
                id="email"
                type="email"
                placeholder="you@example.com"
                autoComplete="email"
                required
                disabled={loading}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={cn(
                  "bg-[#131325] border-[#2a2a4a] text-white placeholder:text-[#555555]",
                  !isEmailValid && "border-red-500/50 focus-visible:ring-red-500/20"
                )}
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="password">Password</Label>
                <button
                  type="button"
                  onClick={generateSecurePassword}
                  className="flex items-center gap-1 text-[10px] text-[#3b82f6] transition-colors hover:text-[#60a5fa] focus:outline-none"
                >
                  <RefreshCw className="size-2.5" />
                  Genera sicura
                </button>
              </div>
              
              <div className="relative">
                <Input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  placeholder="Min. 8 caratteri"
                  autoComplete="new-password"
                  required
                  disabled={loading}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="bg-[#131325] border-[#2a2a4a] text-white placeholder:text-[#555555] pr-10"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[#555555] hover:text-[#888888] focus:outline-none"
                  tabIndex={-1}
                >
                  {showPassword ? (
                    <EyeOff className="size-4" />
                  ) : (
                    <Eye className="size-4" />
                  )}
                </button>
              </div>

              {/* Password strength indicator */}
              {password.length > 0 && (
                <div className="space-y-3 pt-1 animate-in fade-in slide-in-from-top-1 duration-300">
                  <div className="h-1 w-full overflow-hidden rounded-full bg-[#131325]">
                    <div 
                      className={cn("h-full transition-all duration-500 ease-out", getStrengthColor(strength))} 
                      style={{ width: `${strengthPercentage}%` }}
                    />
                  </div>
                  
                  <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-[10px]">
                    <RequirementItem met={password.length >= 10} text="10+ caratteri" />
                    <RequirementItem met={/[A-Z]/.test(password)} text="Maiuscola" />
                    <RequirementItem met={/[0-9]/.test(password)} text="Numero" />
                    <RequirementItem met={/[^A-Za-z0-9]/.test(password)} text="Simbolo" />
                  </div>
                </div>
              )}
            </div>

            <Button
              type="submit"
              className="w-full"
              size="lg"
              disabled={loading || !isEmailValid || strength < 2}
            >
              {loading ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  Creazione in corso…
                </>
              ) : (
                "Crea account"
              )}
            </Button>
          </form>

          {/* Sign in link */}
          <p className="text-center text-sm text-[#888888]">
            Hai già un account?{" "}
            <Link href="/login" className="text-[#3b82f6] hover:underline">
              Accedi
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function RequirementItem({ met, text }: { met: boolean; text: string }) {
  return (
    <div className={cn("flex items-center gap-1.5 transition-colors", met ? "text-emerald-400 font-medium" : "text-[#666666]")}>
      {met ? <Check className="size-2.5" /> : <div className="size-2.5 rounded-full border border-current" />}
      {text}
    </div>
  );
}
