"use client";

import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Menu, X, Shield } from "lucide-react";

export default function MarketingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="flex min-h-screen flex-col" style={{ background: "#0a0a0a" }}>
      <header
        className="sticky top-0 z-50 border-b border-border backdrop-blur-md"
        style={{ background: "rgba(10,10,10,0.85)" }}
      >
        <nav className="mx-auto flex h-16 max-w-7xl items-center justify-between px-6">
          {/* Brand */}
          <Link href="/" className="flex items-center gap-2 text-foreground">
            <div
              className="flex h-8 w-8 items-center justify-center rounded-lg"
              style={{ background: "#3b82f6" }}
              aria-hidden="true"
            >
              <Shield className="h-4 w-4 text-white" />
            </div>
            <span className="text-lg font-bold tracking-tight">
              Privacy Shield
            </span>
          </Link>

          {/* Desktop nav */}
          <div className="hidden items-center gap-1 md:flex">
            <Link
              href="/pricing"
              className="rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              Piani
            </Link>
            <Link
              href="/docs"
              className="rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              Documentazione
            </Link>
          </div>

          <div className="hidden items-center gap-2 md:flex">
            <Link href="/login">
              <Button variant="ghost" size="sm">
                Accedi
              </Button>
            </Link>
            <Link href="/signup">
              <Button size="sm">Inizia Gratis</Button>
            </Link>
          </div>

          {/* Mobile menu toggle */}
          <button
            className="flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground md:hidden"
            onClick={() => setMobileOpen((prev) => !prev)}
            aria-label={mobileOpen ? "Chiudi menu" : "Apri menu"}
            aria-expanded={mobileOpen}
          >
            {mobileOpen ? (
              <X className="h-5 w-5" />
            ) : (
              <Menu className="h-5 w-5" />
            )}
          </button>
        </nav>

        {/* Mobile drawer */}
        {mobileOpen && (
          <div
            className="border-t border-border px-6 py-4 md:hidden"
            style={{ background: "#0f0f1a" }}
          >
            <nav className="flex flex-col gap-1" aria-label="Navigazione mobile">
              <Link
                href="/pricing"
                className="rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                onClick={() => setMobileOpen(false)}
              >
                Piani
              </Link>
              <Link
                href="/docs"
                className="rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                onClick={() => setMobileOpen(false)}
              >
                Documentazione
              </Link>
              <div className="mt-3 flex flex-col gap-2 border-t border-border pt-3">
                <Link href="/login" onClick={() => setMobileOpen(false)}>
                  <Button variant="ghost" size="sm" className="w-full">
                    Accedi
                  </Button>
                </Link>
                <Link href="/signup" onClick={() => setMobileOpen(false)}>
                  <Button size="sm" className="w-full">
                    Inizia Gratis
                  </Button>
                </Link>
              </div>
            </nav>
          </div>
        )}
      </header>

      <main className="flex-1">{children}</main>

      <footer className="border-t border-border py-10">
        <div className="mx-auto max-w-7xl px-6">
          <div className="flex flex-col items-center justify-between gap-6 sm:flex-row">
            <div className="flex items-center gap-2">
              <div
                className="flex h-6 w-6 items-center justify-center rounded"
                style={{ background: "#3b82f6" }}
                aria-hidden="true"
              >
                <Shield className="h-3 w-3 text-white" />
              </div>
              <span className="text-sm font-semibold text-foreground">
                Privacy Shield
              </span>
            </div>
            <div className="flex items-center gap-6 text-sm text-muted-foreground">
              <Link href="/pricing" className="transition-colors hover:text-foreground">
                Piani
              </Link>
              <Link href="/docs" className="transition-colors hover:text-foreground">
                Documentazione
              </Link>
              <Link href="/login" className="transition-colors hover:text-foreground">
                Accedi
              </Link>
            </div>
            <p className="text-sm text-muted-foreground">
              &copy; {new Date().getFullYear()} Privacy Shield. Tutti i diritti riservati.
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}
