"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Wrench,
  FileText,
  MessageSquare,
  ShieldCheck,
  Database,
  Zap,
  RotateCcw,
  Search,
} from "lucide-react";

const MCP_TOOLS = [
  { name: "get_leads", desc: "List leads, filter by status" },
  { name: "classify_lead", desc: "Hot/Warm/Cold + reasoning" },
  { name: "add_lead", desc: "Add + auto-classify on insert" },
  { name: "update_lead_status", desc: "Manual override + history log" },
  { name: "get_lead_stats", desc: "Pipeline aggregate stats" },
  { name: "get_lead_history", desc: "Full timeline per lead" },
  { name: "suggest_next_action", desc: "AI-recommended next step" },
  { name: "bulk_import_leads", desc: "CSV parse + batch classify" },
];

const MCP_RESOURCES = [
  { uri: "leads://dashboard", desc: "Live pipeline snapshot" },
  { uri: "audit://recent", desc: "Recent tool-call audit log" },
];

const MCP_PROMPTS = [
  { name: "weekly_lead_review", desc: "Structured weekly summary" },
];

export function McpPrimitivesPanel() {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <Wrench className="h-4 w-4 text-violet-500" />
          MCP Primitives Exposed
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Tools */}
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            <Wrench className="h-3 w-3" />
            Tools ({MCP_TOOLS.length})
          </div>
          <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
            {MCP_TOOLS.map((t) => (
              <div
                key={t.name}
                className="flex items-center gap-2 rounded-md border border-border/40 bg-muted/20 px-2 py-1.5"
              >
                <code className="font-mono text-[11px] font-medium text-violet-700 dark:text-violet-300">
                  {t.name}
                </code>
                <span className="text-[10px] text-muted-foreground">{t.desc}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Resources */}
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            <FileText className="h-3 w-3" />
            Resources ({MCP_RESOURCES.length})
          </div>
          <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
            {MCP_RESOURCES.map((r) => (
              <div
                key={r.uri}
                className="flex items-center gap-2 rounded-md border border-border/40 bg-muted/20 px-2 py-1.5"
              >
                <code className="font-mono text-[11px] font-medium text-fuchsia-700 dark:text-fuchsia-300">
                  {r.uri}
                </code>
                <span className="text-[10px] text-muted-foreground">{r.desc}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Prompts */}
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            <MessageSquare className="h-3 w-3" />
            Prompt Templates ({MCP_PROMPTS.length})
          </div>
          <div className="grid grid-cols-1 gap-1.5">
            {MCP_PROMPTS.map((p) => (
              <div
                key={p.name}
                className="flex items-center gap-2 rounded-md border border-border/40 bg-muted/20 px-2 py-1.5"
              >
                <code className="font-mono text-[11px] font-medium text-emerald-700 dark:text-emerald-300">
                  {p.name}
                </code>
                <span className="text-[10px] text-muted-foreground">{p.desc}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Reliability features */}
        <div className="space-y-1.5 border-t border-border/40 pt-3">
          <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            Reliability Engineering
          </div>
          <div className="flex flex-wrap gap-1.5">
            <Feature icon={<Search className="h-3 w-3" />} label="TTL cache (5 min)" />
            <Feature icon={<ShieldCheck className="h-3 w-3" />} label="Rule-based fallback" />
            <Feature icon={<Zap className="h-3 w-3" />} label="Rate-limit handler" />
            <Feature icon={<RotateCcw className="h-3 w-3" />} label="Demo auto-reset" />
            <Feature icon={<Database className="h-3 w-3" />} label="SQLite + WAL mode" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function Feature({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <Badge
      variant="outline"
      className="gap-1 px-1.5 py-0.5 text-[10px] font-normal text-muted-foreground"
    >
      {icon}
      {label}
    </Badge>
  );
}
