"use client";

import { useEffect, useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Lead, LeadStatus, LeadWithHistory, NextAction, api } from "@/lib/leadmind-api";
import { STATUS_CONFIG, formatDateTime, formatRelativeTime } from "@/lib/leadmind-ui";
import { toast } from "sonner";
import {
  Sparkles,
  Loader2,
  Mail,
  Clock,
  MessageSquare,
  RefreshCw,
  ArrowRight,
  History,
} from "lucide-react";

interface LeadDetailDrawerProps {
  lead: Lead | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onLeadUpdated: () => void;
}

const STATUS_OPTIONS: LeadStatus[] = ["Hot", "Warm", "Cold", "Converted", "Lost"];

export function LeadDetailDrawer({
  lead,
  open,
  onOpenChange,
  onLeadUpdated,
}: LeadDetailDrawerProps) {
  const [detail, setDetail] = useState<LeadWithHistory | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [nextAction, setNextAction] = useState<NextAction | null>(null);
  const [loadingAction, setLoadingAction] = useState(false);
  const [updatingStatus, setUpdatingStatus] = useState<LeadStatus | null>(null);

  useEffect(() => {
    if (!lead || !open) {
      setDetail(null);
      setNextAction(null);
      return;
    }
    let cancelled = false;
    setLoadingDetail(true);
    api
      .getLead(lead.id)
      .then((d) => {
        if (!cancelled) setDetail(d);
      })
      .catch((e) => toast.error(`Failed to load lead: ${e.message}`))
      .finally(() => {
        if (!cancelled) setLoadingDetail(false);
      });
    return () => {
      cancelled = true;
    };
  }, [lead, open]);

  const fetchNextAction = async (id: number) => {
    setLoadingAction(true);
    try {
      const r = await api.nextAction(id);
      setNextAction(r);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed to fetch next action");
    } finally {
      setLoadingAction(false);
    }
  };

  const handleStatusChange = async (newStatus: LeadStatus) => {
    if (!lead) return;
    setUpdatingStatus(newStatus);
    try {
      await api.updateStatus(lead.id, newStatus);
      toast.success(`Marked ${lead.name} as ${newStatus}`);
      onLeadUpdated();
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed to update status");
    } finally {
      setUpdatingStatus(null);
    }
  };

  if (!lead) return null;
  const cfg = STATUS_CONFIG[lead.status];

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-[560px] overflow-y-auto">
        <SheetHeader>
          <div className="flex items-start justify-between gap-3 pr-6">
            <div className="min-w-0 flex-1">
              <SheetTitle className="text-lg">{lead.name}</SheetTitle>
              <SheetDescription className="flex flex-wrap items-center gap-2 pt-1 text-xs">
                <span className="inline-flex items-center gap-1">
                  <Mail className="h-3 w-3" />
                  {lead.contact_info || "—"}
                </span>
                <span className="opacity-50">·</span>
                <span>via {lead.source || "unknown"}</span>
              </SheetDescription>
            </div>
            <Badge
              variant="outline"
              className={`gap-1 px-2 py-1 text-xs font-medium ${cfg.badgeClass}`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${cfg.dotClass}`} />
              {cfg.label}
            </Badge>
          </div>
        </SheetHeader>

        <div className="mt-4 space-y-5 px-4 pb-6">
          {/* Status changer + Next action */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                Update status
              </label>
              <Select
                value={lead.status}
                onValueChange={(v) => handleStatusChange(v as LeadStatus)}
                disabled={updatingStatus !== null}
              >
                <SelectTrigger className="h-9 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STATUS_OPTIONS.map((s) => (
                    <SelectItem key={s} value={s} className="text-xs">
                      <span className="flex items-center gap-2">
                        <span className={`h-1.5 w-1.5 rounded-full ${STATUS_CONFIG[s].dotClass}`} />
                        {s}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {updatingStatus && (
                <p className="text-[11px] text-muted-foreground">
                  Updating to {updatingStatus}…
                </p>
              )}
            </div>
            <div className="space-y-1.5">
              <label className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                AI next action
              </label>
              <Button
                variant="outline"
                size="sm"
                className="h-9 w-full gap-1.5 text-xs"
                onClick={() => fetchNextAction(lead.id)}
                disabled={loadingAction}
              >
                {loadingAction ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Sparkles className="h-3.5 w-3.5" />
                )}
                Suggest next action
              </Button>
            </div>
          </div>

          {nextAction && (
            <div className="rounded-lg border border-violet-200 bg-violet-50/50 p-3 dark:border-violet-900 dark:bg-violet-950/30">
              <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-violet-700 dark:text-violet-300">
                <Sparkles className="h-3 w-3" />
                Recommended Next Action
                <Badge
                  variant="outline"
                  className="ml-1 px-1 py-0 text-[9px] font-normal"
                >
                  {nextAction.source}
                </Badge>
              </div>
              <p className="text-sm leading-relaxed">{nextAction.suggestion}</p>
            </div>
          )}

          {/* Original message */}
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              <MessageSquare className="h-3 w-3" />
              Original message
            </div>
            <div className="rounded-lg border border-border/60 bg-muted/30 p-3">
              <Textarea
                readOnly
                value={lead.message || ""}
                className="min-h-[80px] resize-none border-0 bg-transparent p-0 text-sm shadow-none focus-visible:ring-0"
              />
            </div>
          </div>

          {/* Metadata */}
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="rounded-lg border border-border/60 p-3">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Created</div>
              <div className="mt-1 font-medium">{formatDateTime(lead.created_at)}</div>
              <div className="text-[11px] text-muted-foreground">
                {formatRelativeTime(lead.created_at)}
              </div>
            </div>
            <div className="rounded-lg border border-border/60 p-3">
              <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Last contacted
              </div>
              <div className="mt-1 font-medium">{formatDateTime(lead.last_contacted_at)}</div>
              <div className="text-[11px] text-muted-foreground">
                {formatRelativeTime(lead.last_contacted_at)}
              </div>
            </div>
          </div>

          {/* History timeline */}
          <div className="space-y-2">
            <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              <History className="h-3 w-3" />
              Timeline
              {detail && (
                <span className="ml-1 text-[10px] opacity-60">
                  ({detail.history.length} events)
                </span>
              )}
            </div>
            {loadingDetail ? (
              <div className="flex items-center gap-2 p-4 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" />
                Loading timeline…
              </div>
            ) : detail && detail.history.length > 0 ? (
              <ol className="relative space-y-3 border-l border-border/60 pl-4">
                {detail.history.map((h) => (
                  <li key={h.id} className="relative">
                    <span
                      className={`absolute -left-[21px] top-1 h-2 w-2 rounded-full ring-2 ring-background ${
                        EVENT_DOT[h.event_type] ?? "bg-muted-foreground"
                      }`}
                    />
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge
                        variant="outline"
                        className="px-1.5 py-0 text-[10px] font-medium uppercase tracking-wide"
                      >
                        {h.event_type.replace("_", " ")}
                      </Badge>
                      <span className="text-[10px] text-muted-foreground">
                        {formatRelativeTime(h.created_at)}
                      </span>
                    </div>
                    {h.event_description && (
                      <p className="mt-1 text-xs leading-relaxed text-foreground/90">
                        {h.event_description}
                      </p>
                    )}
                    {h.old_value && h.new_value && (
                      <div className="mt-1 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                        <span className="rounded bg-muted px-1 py-0.5">{h.old_value}</span>
                        <ArrowRight className="h-3 w-3" />
                        <span className="rounded bg-muted px-1 py-0.5">{h.new_value}</span>
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-xs text-muted-foreground">No history yet.</p>
            )}
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

const EVENT_DOT: Record<string, string> = {
  created: "bg-violet-500",
  classified: "bg-amber-500",
  status_change: "bg-sky-500",
  contacted: "bg-emerald-500",
  note: "bg-zinc-400",
};
