"use client";

import { format } from "date-fns";
import { 
  MoreVerticalIcon, 
  Trash2Icon, 
  CalendarIcon, 
  SearchIcon,
  ShieldCheckIcon
} from "lucide-react";
import { 
  Table, 
  TableBody, 
  TableCell, 
  TableHead, 
  TableHeader, 
  TableRow 
} from "@/components/ui/table";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export interface ApiKey {
  id: string;
  prefix: string;
  label: string;
  environment: "live" | "test" | string;
  active: boolean;
  created_at: string;
  revoked_at: string | null;
  expires_at: string | null;
}

interface ApiKeyTableProps {
  keys: ApiKey[];
  onRevoke: (id: string) => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
}

export function ApiKeyTable({ keys, onRevoke, searchQuery, onSearchChange }: ApiKeyTableProps) {
  const filteredKeys = keys.filter((k) =>
    k.label.toLowerCase().includes(searchQuery.toLowerCase()) ||
    k.prefix.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="flex flex-col gap-4">
      {/* Search and Filters Row */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1 max-w-sm">
          <SearchIcon className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground/50" />
          <Input 
            placeholder="Cerca chiavi..." 
            className="pl-10 h-10 border-border/50 bg-background/50 hover:bg-background transition-colors focus:ring-1 focus:ring-primary/20"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
          />
        </div>
      </div>

      <div className="rounded-xl border border-border/60 bg-[#0c0c11] overflow-hidden shadow-sm">
        <Table>
          <TableHeader className="bg-white/[0.02]">
            <TableRow className="hover:bg-transparent border-border/60">
              <TableHead className="w-[40%] text-xs font-medium uppercase tracking-wider text-muted-foreground/60">Token</TableHead>
              <TableHead className="text-xs font-medium uppercase tracking-wider text-muted-foreground/60">Ambiente</TableHead>
              <TableHead className="text-xs font-medium uppercase tracking-wider text-muted-foreground/60">Data Creazione</TableHead>
              <TableHead className="w-[10%] text-right"></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredKeys.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="h-32 text-center text-muted-foreground/60">
                  {searchQuery ? "Nessun risultato trovato" : "Nessuna chiave API configurata"}
                </TableCell>
              </TableRow>
            ) : (
              filteredKeys.map((key) => (
                <TableRow key={key.id} className="group border-border/40 hover:bg-white/[0.02] transition-colors">
                  <TableCell className="py-4">
                    <div className="flex flex-col gap-1">
                      <span className="text-sm font-semibold text-foreground group-hover:text-primary transition-colors">
                        {key.label}
                      </span>
                      <code className="text-[11px] text-muted-foreground/70 font-mono tracking-tight bg-muted/30 w-fit px-1.5 py-0.5 rounded border border-border/20">
                        {key.prefix}
                      </code>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <span className={[
                        "flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wider border",
                        key.environment === "live" 
                          ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" 
                          : "bg-amber-500/10 text-amber-400 border-amber-500/20"
                      ].join(" ")}>
                        <span className={[
                          "size-1.5 rounded-full",
                          key.environment === "live" ? "bg-emerald-400 shadow-[0_0_8px_rgba(34,197,94,0.6)]" : "bg-amber-400"
                        ].join(" ")} />
                        {key.environment}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2 text-xs text-muted-foreground/80">
                      <CalendarIcon className="size-3.5 opacity-40" />
                      {format(new Date(key.created_at), "dd MMM yyyy")}
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    <DropdownMenu>
                      <DropdownMenuTrigger
                        className={cn(
                          buttonVariants({ variant: "ghost", size: "icon" }),
                          "size-8 opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
                        )}
                      >
                        <MoreVerticalIcon className="size-4" />
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-[180px] bg-[#0c0c11] border-border/60">
                        <DropdownMenuItem className="text-xs py-2.5">
                          <ShieldCheckIcon className="mr-2 size-4 text-muted-foreground" />
                          Modifica permessi
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem 
                          variant="destructive"
                          className="text-xs py-2.5"
                          onClick={() => onRevoke(key.id)}
                        >
                          <Trash2Icon className="mr-2 size-4" />
                          Revoca chiave
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
