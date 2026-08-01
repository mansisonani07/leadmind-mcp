"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Stats } from "@/lib/leadmind-api";
import { STATUS_CONFIG } from "@/lib/leadmind-ui";
import { Users, Flame, TrendingUp, Clock, CheckCircle2, Sparkles } from "lucide-react";

interface StatsGridProps {
  stats: Stats | null;
}

export function StatsGrid({ stats }: StatsGridProps) {
  const total = stats?.total_leads ?? 0;
  const hot = stats?.by_status?.Hot ?? 0;
  const warm = stats?.by_status?.Warm ?? 0;
  const cold = stats?.by_status?.Cold ?? 0;
  const converted = stats?.by_status?.Converted ?? 0;
  const conversionRate = stats?.conversion_rate_percent ?? 0;
  const avgRespMin = stats?.average_response_time_minutes ?? 0;
  const groqCalls = stats?.groq_usage?.in_memory_calls_this_session ?? 0;

  const cards = [
    {
      label: "Total Leads",
      value: total,
      icon: <Users className="h-4 w-4" />,
      hint: `${Object.keys(stats?.by_source ?? {}).length} sources`,
      accent: "text-violet-600 dark:text-violet-400",
    },
    {
      label: "Hot Leads",
      value: hot,
      icon: <Flame className="h-4 w-4" />,
      hint: `${warm} warm · ${cold} cold`,
      accent: "text-red-600 dark:text-red-400",
    },
    {
      label: "Conversion Rate",
      value: `${conversionRate}%`,
      icon: <TrendingUp className="h-4 w-4" />,
      hint: `${converted} converted`,
      accent: "text-emerald-600 dark:text-emerald-400",
    },
    {
      label: "Avg Response",
      value: avgRespMin > 0 ? `${avgRespMin}m` : "—",
      icon: <Clock className="h-4 w-4" />,
      hint: "creation → first status change",
      accent: "text-sky-600 dark:text-sky-400",
    },
    {
      label: "Groq Calls",
      value: groqCalls,
      icon: <Sparkles className="h-4 w-4" />,
      hint: "free-tier usage this session",
      accent: "text-amber-600 dark:text-amber-400",
    },
    {
      label: "Sources Tracked",
      value: Object.keys(stats?.by_source ?? {}).length,
      icon: <CheckCircle2 className="h-4 w-4" />,
      hint: "acquisition channels",
      accent: "text-fuchsia-600 dark:text-fuchsia-400",
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {cards.map((c) => (
        <Card key={c.label} className="overflow-hidden">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2 pt-3">
            <CardTitle className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {c.label}
            </CardTitle>
            <span className={c.accent}>{c.icon}</span>
          </CardHeader>
          <CardContent className="pb-3">
            <div className="text-2xl font-semibold tracking-tight">{c.value}</div>
            <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
              {c.hint}
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

/** Status distribution bar (Hot / Warm / Cold / Converted / Lost) */
export function StatusDistribution({ stats }: { stats: Stats | null }) {
  const byStatus = stats?.by_status ?? {};
  const total = stats?.total_leads ?? 0;
  const order: (keyof typeof STATUS_CONFIG)[] = [
    "Hot",
    "Warm",
    "Cold",
    "Converted",
    "Lost",
  ];

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium">Pipeline Distribution</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {order.map((s) => {
          const count = byStatus[s] ?? 0;
          const pct = total > 0 ? (count / total) * 100 : 0;
          const cfg = STATUS_CONFIG[s];
          return (
            <div key={s} className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <div className="flex items-center gap-1.5">
                  <span className={`h-2 w-2 rounded-full ${cfg.dotClass}`} />
                  <span className="font-medium">{cfg.label}</span>
                </div>
                <span className="tabular-nums text-muted-foreground">
                  {count} <span className="opacity-50">({pct.toFixed(0)}%)</span>
                </span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className={`h-full ${cfg.dotClass} transition-all`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

/** Source breakdown — horizontal bar chart, top 6 sources by count */
export function SourceBreakdown({ stats }: { stats: Stats | null }) {
  const bySource = stats?.by_source ?? {};
  const entries = Object.entries(bySource).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, c]) => c));

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium">Leads by Source</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {entries.length === 0 && (
          <p className="text-xs text-muted-foreground">No sources yet.</p>
        )}
        {entries.map(([source, count]) => {
          const pct = (count / max) * 100;
          return (
            <div key={source} className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium">{source}</span>
                <span className="tabular-nums text-muted-foreground">{count}</span>
              </div>
              <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full bg-gradient-to-r from-violet-500 to-fuchsia-500 transition-all"
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
