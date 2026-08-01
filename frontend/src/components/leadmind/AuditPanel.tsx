"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { AuditEntry } from "@/lib/leadmind-api";
import { formatRelativeTime } from "@/lib/leadmind-ui";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Activity, Zap, ShieldCheck, Database } from "lucide-react";

interface AuditPanelProps {
  audit: AuditEntry[];
  groqUsage: {
    in_memory_calls_this_session: number;
    total_logged_calls: number;
    logged_success: number;
    logged_rate_limited: number;
    logged_errors: number;
  } | null;
}

export function AuditPanel({ audit, groqUsage }: AuditPanelProps) {
  const total = audit.length;
  const groqCalls = audit.filter((a) => a.used_groq === 1).length;
  const fallbackCalls = audit.filter((a) => a.used_fallback === 1).length;
  const cacheHits = audit.filter((a) => a.used_cache === 1).length;
  const failures = audit.filter((a) => a.success === 0).length;

  return (
    <Card className="h-full">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <Activity className="h-4 w-4 text-violet-500" />
          Observability — Audit Log
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Usage summary */}
        <div className="grid grid-cols-3 gap-2">
          <UsageStat
            label="Groq"
            value={groqCalls}
            icon={<Zap className="h-3 w-3 text-amber-500" />}
          />
          <UsageStat
            label="Fallback"
            value={fallbackCalls}
            icon={<ShieldCheck className="h-3 w-3 text-emerald-500" />}
          />
          <UsageStat
            label="Cache"
            value={cacheHits}
            icon={<Database className="h-3 w-3 text-sky-500" />}
          />
        </div>

        {/* Free-tier monitoring */}
        {groqUsage && (
          <div className="rounded-lg border border-amber-200/60 bg-amber-50/40 p-3 dark:border-amber-900/60 dark:bg-amber-950/20">
            <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-amber-700 dark:text-amber-300">
              Free-tier monitoring
            </div>
            <div className="grid grid-cols-2 gap-2 text-[11px]">
              <Stat
                label="Session calls"
                value={groqUsage.in_memory_calls_this_session}
              />
              <Stat
                label="Total logged"
                value={groqUsage.total_logged_calls}
              />
              <Stat
                label="Rate-limited (429)"
                value={groqUsage.logged_rate_limited}
                warn={groqUsage.logged_rate_limited > 0}
              />
              <Stat
                label="Errors"
                value={groqUsage.logged_errors}
                warn={groqUsage.logged_errors > 0}
              />
            </div>
          </div>
        )}

        {/* Recent tool calls */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between text-[11px] text-muted-foreground">
            <span>Recent tool calls</span>
            <span>
              {total} shown · {failures} failed
            </span>
          </div>
          <ScrollArea className="h-[280px] rounded-lg border border-border/40 bg-muted/20">
            <div className="divide-y divide-border/40">
              {audit.length === 0 && (
                <div className="p-4 text-center text-xs text-muted-foreground">
                  No tool calls yet.
                </div>
              )}
              {audit.map((a) => {
                const flags: string[] = [];
                if (a.used_groq) flags.push("groq");
                if (a.used_fallback) flags.push("fallback");
                if (a.used_cache) flags.push("cache");
                const flagStr = flags.join(",") || "—";
                return (
                  <div
                    key={a.id}
                    className="flex items-center gap-2 px-3 py-2 text-[11px]"
                  >
                    <span className="font-mono text-muted-foreground">#{a.id}</span>
                    <span className="font-medium">{a.tool_name}</span>
                    <Badge
                      variant="outline"
                      className={`px-1 py-0 text-[9px] ${
                        a.success
                          ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300"
                          : "border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300"
                      }`}
                    >
                      {flagStr}
                    </Badge>
                    {a.duration_ms !== null && (
                      <span className="ml-auto tabular-nums text-muted-foreground">
                        {a.duration_ms}ms
                      </span>
                    )}
                    <span className="text-muted-foreground">
                      {formatRelativeTime(a.created_at)}
                    </span>
                  </div>
                );
              })}
            </div>
          </ScrollArea>
        </div>
      </CardContent>
    </Card>
  );
}

function UsageStat({
  label,
  value,
  icon,
}: {
  label: string;
  value: number;
  icon: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border/60 bg-card p-2.5">
      <div className="flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {icon}
        {label}
      </div>
      <div className="mt-0.5 text-lg font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function Stat({
  label,
  value,
  warn,
}: {
  label: string;
  value: number;
  warn?: boolean;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span
        className={`font-mono font-semibold tabular-nums ${
          warn ? "text-amber-700 dark:text-amber-400" : ""
        }`}
      >
        {value}
      </span>
    </div>
  );
}
