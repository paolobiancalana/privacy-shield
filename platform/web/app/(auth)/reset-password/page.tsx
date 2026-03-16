"use client";

import { useState } from "react";
import Link from "next/link";
import { Loader2, CircleCheck } from "lucide-react";
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

export default function ResetPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const supabase = createClient();

  async function handleReset(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setErrorMessage(null);
    setLoading(true);

    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: `${window.location.origin}/auth/callback?next=/update-password`,
    });

    if (error) {
      setErrorMessage(error.message);
      setLoading(false);
      return;
    }

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
              <h2 className="text-lg font-semibold text-white">
                Check your email
              </h2>
              <p className="text-sm text-[#888888]">
                We sent a password reset link to{" "}
                <span className="text-[#e0e0e0]">{email}</span>. The link
                expires in 1 hour.
              </p>
            </div>
            <Link
              href="/login"
              className="mt-2 text-sm text-[#3b82f6] hover:underline"
            >
              Back to sign in
            </Link>
          </CardContent>
        </Card>
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // Reset form
  // -------------------------------------------------------------------------
  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0a0a0a] px-4">
      <Card className="w-full max-w-md bg-[#1a1a2e]">
        <CardHeader className="space-y-1 pb-2">
          <CardTitle className="text-center text-2xl font-semibold text-white">
            Reset your password
          </CardTitle>
          <CardDescription className="text-center text-[#888888]">
            Enter your email and we&apos;ll send you a reset link
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-4 pt-2">
          {/* Error banner */}
          {errorMessage && (
            <div
              role="alert"
              className="rounded-lg border border-red-800/40 bg-red-950/30 px-3 py-2.5 text-sm text-red-400"
            >
              {errorMessage}
            </div>
          )}

          <form onSubmit={handleReset} className="space-y-3" noValidate>
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

            <Button
              type="submit"
              className="w-full"
              size="lg"
              disabled={loading}
            >
              {loading ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  Sending link…
                </>
              ) : (
                "Send reset link"
              )}
            </Button>
          </form>

          <p className="text-center text-sm text-[#888888]">
            Remembered your password?{" "}
            <Link href="/login" className="text-[#3b82f6] hover:underline">
              Sign in
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
