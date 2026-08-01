import { LeadStatus } from "@/lib/leadmind-api";

/**
 * Visual config for each lead status — color, badge class, icon, etc.
 * Kept in one place so the dashboard, table, and detail drawer stay consistent.
 */
export const STATUS_CONFIG: Record<
  LeadStatus,
  {
    label: string;
    badgeClass: string;
    dotClass: string;
    accent: string; // hex for charts
    description: string;
  }
> = {
  Hot: {
    label: "Hot",
    badgeClass:
      "bg-red-100 text-red-700 dark:bg-red-950/60 dark:text-red-300 border-red-200 dark:border-red-900",
    dotClass: "bg-red-500",
    accent: "#ef4444",
    description: "Urgent, budget approved, decision-ready",
  },
  Warm: {
    label: "Warm",
    badgeClass:
      "bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 border-amber-200 dark:border-amber-900",
    dotClass: "bg-amber-500",
    accent: "#f59e0b",
    description: "Evaluating, no urgency yet",
  },
  Cold: {
    label: "Cold",
    badgeClass:
      "bg-sky-100 text-sky-700 dark:bg-sky-950/60 dark:text-sky-300 border-sky-200 dark:border-sky-900",
    dotClass: "bg-sky-500",
    accent: "#0ea5e9",
    description: "Passive, future-only, nurturing",
  },
  Converted: {
    label: "Converted",
    badgeClass:
      "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300 border-emerald-200 dark:border-emerald-900",
    dotClass: "bg-emerald-500",
    accent: "#10b981",
    description: "Closed-won, onboarded customer",
  },
  Lost: {
    label: "Lost",
    badgeClass:
      "bg-zinc-200 text-zinc-600 dark:bg-zinc-800/60 dark:text-zinc-400 border-zinc-300 dark:border-zinc-700",
    dotClass: "bg-zinc-400",
    accent: "#71717a",
    description: "Closed-lost, re-engage later",
  },
};

export const SOURCE_CONFIG: Record<string, { accent: string }> = {
  "Website Form": { accent: "#8b5cf6" },
  Webinar: { accent: "#ec4899" },
  "Email Campaign": { accent: "#06b6d4" },
  Referral: { accent: "#10b981" },
  LinkedIn: { accent: "#0ea5e9" },
  "Cold Outreach": { accent: "#f59e0b" },
  "Demo Request": { accent: "#ef4444" },
  Newsletter: { accent: "#6366f1" },
  "Web Form": { accent: "#8b5cf6" },
  manual: { accent: "#71717a" },
  "csv_import": { accent: "#a3a3a3" },
  "CSV Import": { accent: "#a3a3a3" },
};

export function sourceAccent(source: string | null | undefined): string {
  if (!source) return "#71717a";
  return SOURCE_CONFIG[source]?.accent ?? "#71717a";
}

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  const d = new Date(iso.includes("T") ? iso : iso.replace(" ", "T") + "Z");
  if (isNaN(d.getTime())) return iso;
  const now = Date.now();
  const diff = now - d.getTime();
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day}d ago`;
  return d.toLocaleDateString();
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.includes("T") ? iso : iso.replace(" ", "T") + "Z");
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
