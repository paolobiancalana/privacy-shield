"use client";

import { useState, useTransition } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  BarChart3Icon,
  KeyRoundIcon,
  SettingsIcon,
  CreditCardIcon,
  ExternalLinkIcon,
  ChevronDownIcon,
  CheckIcon,
  LogOutIcon,
  BuildingIcon,
} from "lucide-react";

import { createClient } from "@/lib/supabase/client";
import { cn } from "@/lib/utils";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Org {
  id: string;
  name: string;
  slug: string;
  role: string;
}

export interface DashboardUser {
  id: string;
  email: string;
}

interface DashboardShellProps {
  children: React.ReactNode;
  user: DashboardUser;
  orgs: Org[];
  initialOrgId: string;
}

// ---------------------------------------------------------------------------
// Nav links
// ---------------------------------------------------------------------------

const navLinks = [
  {
    href: "/dashboard/usage",
    label: "Usage",
    icon: BarChart3Icon,
    external: false,
  },
  {
    href: "/dashboard/keys",
    label: "API Keys",
    icon: KeyRoundIcon,
    external: false,
  },
  {
    href: "/dashboard/settings",
    label: "Settings",
    icon: SettingsIcon,
    external: false,
  },
  {
    href: "/dashboard/billing",
    label: "Billing",
    icon: CreditCardIcon,
    external: false,
  },
  {
    href: "https://docs.privacyshield.pro",
    label: "Docs",
    icon: ExternalLinkIcon,
    external: true,
  },
];

const PAGE_TITLES: Record<string, string> = {
  "/dashboard/usage": "Usage",
  "/dashboard/keys": "API Keys",
  "/dashboard/settings": "Settings",
  "/dashboard/billing": "Billing",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getInitials(email: string): string {
  const parts = email.split("@")[0].split(/[._-]/);
  return parts
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function DashboardShell({
  children,
  user,
  orgs,
  initialOrgId,
}: DashboardShellProps) {
  const pathname = usePathname();
  const router = useRouter();
  const [selectedOrgId, setSelectedOrgId] = useState(initialOrgId);
  const [isPending, startTransition] = useTransition();

  const selectedOrg = orgs.find((o) => o.id === selectedOrgId) ?? orgs[0];
  const pageTitle = PAGE_TITLES[pathname] ?? "Dashboard";

  function handleSelectOrg(orgId: string) {
    setSelectedOrgId(orgId);
    // Persist selection in a cookie so server components can read it on next request.
    // eslint-disable-next-line react-hooks/immutability
    document.cookie = `ps_selected_org=${orgId}; path=/; max-age=31536000; SameSite=Lax`;
    router.refresh();
  }

  function handleSignOut() {
    startTransition(async () => {
      const supabase = createClient();
      await supabase.auth.signOut();
      router.push("/");
    });
  }

  return (
    <div className="flex min-h-screen bg-background">
      {/* ------------------------------------------------------------------ */}
      {/* Sidebar                                                              */}
      {/* ------------------------------------------------------------------ */}
      <aside className="flex w-60 flex-col border-r border-border bg-sidebar">
        {/* Logo */}
        <div className="flex h-14 items-center border-b border-border px-5">
          <Link
            href="/dashboard/usage"
            className="flex items-center gap-2 text-sm font-semibold tracking-tight text-foreground"
          >
            <span className="flex size-6 items-center justify-center rounded-md bg-primary text-xs font-bold text-primary-foreground">
              PS
            </span>
            Privacy Shield
          </Link>
        </div>

        {/* Org switcher */}
        <div className="border-b border-border px-3 py-3">
          {orgs.length > 1 ? (
            <DropdownMenu>
              <DropdownMenuTrigger
                render={
                  <Button
                    variant="ghost"
                    size="sm"
                    className="w-full justify-between px-2 text-sm font-normal"
                  />
                }
              >
                <span className="flex items-center gap-2 truncate">
                  <BuildingIcon className="size-3.5 shrink-0 text-muted-foreground" />
                  <span className="truncate">{selectedOrg?.name ?? "Select org"}</span>
                </span>
                <ChevronDownIcon className="size-3.5 shrink-0 text-muted-foreground" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-52">
                <DropdownMenuLabel>Organizations</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {orgs.map((org) => (
                  <DropdownMenuItem
                    key={org.id}
                    onClick={() => handleSelectOrg(org.id)}
                    className="flex items-center justify-between"
                  >
                    <span className="truncate">{org.name}</span>
                    {org.id === selectedOrgId && (
                      <CheckIcon className="size-3.5 text-primary" />
                    )}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <div className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm">
              <BuildingIcon className="size-3.5 shrink-0 text-muted-foreground" />
              <span className="truncate text-foreground">
                {selectedOrg?.name ?? "No org"}
              </span>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className="flex flex-1 flex-col gap-0.5 px-3 py-3" aria-label="Main navigation">
          {navLinks.map((link) => {
            const isActive =
              !link.external && pathname.startsWith(link.href);
            const Icon = link.icon;

            return (
              <Link
                key={link.href}
                href={link.href}
                target={link.external ? "_blank" : undefined}
                rel={link.external ? "noopener noreferrer" : undefined}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors",
                  isActive
                    ? "bg-sidebar-accent text-foreground font-medium"
                    : "text-muted-foreground hover:bg-sidebar-accent hover:text-foreground"
                )}
              >
                <Icon className="size-4 shrink-0" />
                {link.label}
                {link.external && (
                  <ExternalLinkIcon className="ml-auto size-3 text-muted-foreground" />
                )}
              </Link>
            );
          })}
        </nav>

        {/* User menu */}
        <div className="border-t border-border px-3 py-3">
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button
                  variant="ghost"
                  size="sm"
                  className="w-full justify-start gap-2 px-2 text-sm font-normal"
                />
              }
            >
              <Avatar size="sm">
                <AvatarFallback className="bg-primary/20 text-primary text-xs">
                  {getInitials(user.email)}
                </AvatarFallback>
              </Avatar>
              <span className="truncate text-muted-foreground">
                {user.email}
              </span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="w-52" side="top">
              <DropdownMenuLabel className="font-normal">
                <div className="flex flex-col gap-0.5">
                  <span className="text-xs text-muted-foreground truncate">
                    Signed in as
                  </span>
                  <span className="text-sm truncate">{user.email}</span>
                </div>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant="destructive"
                onClick={handleSignOut}
                disabled={isPending}
              >
                <LogOutIcon className="size-4" />
                {isPending ? "Signing out…" : "Sign out"}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </aside>

      {/* ------------------------------------------------------------------ */}
      {/* Main content                                                         */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex flex-1 flex-col min-w-0">
        <header className="flex h-14 items-center border-b border-border px-8">
          <h1 className="text-base font-semibold">{pageTitle}</h1>
        </header>
        <main className="flex-1 overflow-y-auto px-8 py-6">{children}</main>
      </div>
    </div>
  );
}
