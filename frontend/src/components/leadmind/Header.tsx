"use client";

import {
  Brain,
  RefreshCw,
  Sparkles,
  Zap,
  Database,
  Activity,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

interface HeaderProps {
  demoMode: boolean;
  groqCallsThisSession: number;
  onRefresh: () => void;
  onResetDemo: () => void;
  refreshing: boolean;
}

export function Header({
  demoMode,
  groqCallsThisSession,
  onRefresh,
  onResetDemo,
  refreshing,
}: HeaderProps) {
  return (
    <header className="sticky top-0 z-40 w-full border-b border-border/60 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex h-16 max-w-[1400px] items-center gap-4 px-4 sm:px-6 lg:px-8">
        {/* Logo + title */}
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-fuchsia-500 text-white shadow-sm">
            <Brain className="h-5 w-5" />
          </div>
          <div className="flex flex-col">
            <div className="flex items-center gap-2">
              <span className="text-base font-semibold tracking-tight">
                LeadMind
              </span>
              <Badge
                variant="outline"
                className="hidden bg-violet-50 px-1.5 py-0 text-[10px] font-medium uppercase tracking-wider text-violet-700 dark:bg-violet-950/50 dark:text-violet-300 sm:inline-flex"
              >
                MCP
              </Badge>
            </div>
            <span className="text-[11px] text-muted-foreground">
              AI Lead Management CRM
            </span>
          </div>
        </div>

        {/* Center: stack badges */}
        <div className="ml-2 hidden items-center gap-2 md:flex">
          <Pill icon={<Sparkles className="h-3 w-3" />} label="Groq Llama-3.3-70b" />
          <Pill icon={<Database className="h-3 w-3" />} label="SQLite" />
          <Pill icon={<Zap className="h-3 w-3" />} label="MCP SDK" />
        </div>

        {/* Right: usage + actions */}
        <div className="ml-auto flex items-center gap-2">
          {demoMode && (
            <Badge
              variant="outline"
              className="hidden bg-emerald-50 px-2 py-1 text-[11px] font-medium text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300 sm:inline-flex"
            >
              <Activity className="mr-1 h-3 w-3" />
              Demo mode
            </Badge>
          )}
          <Badge
            variant="outline"
            className="hidden bg-amber-50 px-2 py-1 text-[11px] font-medium text-amber-700 dark:bg-amber-950/50 dark:text-amber-300 sm:inline-flex"
          >
            <Sparkles className="mr-1 h-3 w-3" />
            Groq calls: {groqCallsThisSession}
          </Badge>
          <Button
            variant="outline"
            size="sm"
            onClick={onRefresh}
            disabled={refreshing}
            className="gap-1.5"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
            <span className="hidden sm:inline">Refresh</span>
          </Button>
          {demoMode && (
            <Button
              variant="outline"
              size="sm"
              onClick={onResetDemo}
              disabled={refreshing}
              className="gap-1.5"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Reset demo</span>
            </Button>
          )}
        </div>
      </div>
    </header>
  );
}

function Pill({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-border/60 bg-muted/40 px-2 py-1 text-[11px] font-medium text-muted-foreground">
      {icon}
      {label}
    </span>
  );
}
