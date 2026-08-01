"use client";

import { useState, useMemo } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Lead, LeadStatus } from "@/lib/leadmind-api";
import { STATUS_CONFIG, formatRelativeTime } from "@/lib/leadmind-ui";
import { Search, ChevronRight } from "lucide-react";

interface LeadsTableProps {
  leads: Lead[];
  onSelectLead: (lead: Lead) => void;
  selectedLeadId?: number;
}

type FilterStatus = "all" | LeadStatus;

export function LeadsTable({ leads, onSelectLead, selectedLeadId }: LeadsTableProps) {
  const [filter, setFilter] = useState<FilterStatus>("all");
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    let result = leads;
    if (filter !== "all") {
      result = result.filter((l) => l.status === filter);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (l) =>
          l.name.toLowerCase().includes(q) ||
          (l.contact_info ?? "").toLowerCase().includes(q) ||
          (l.message ?? "").toLowerCase().includes(q) ||
          (l.source ?? "").toLowerCase().includes(q)
      );
    }
    return result;
  }, [leads, filter, search]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { all: leads.length };
    for (const l of leads) {
      c[l.status] = (c[l.status] ?? 0) + 1;
    }
    return c;
  }, [leads]);

  return (
    <div className="space-y-3">
      {/* Filter tabs + search */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <Tabs value={filter} onValueChange={(v) => setFilter(v as FilterStatus)}>
          <TabsList className="bg-muted/40">
            <TabsTrigger value="all" className="text-xs">
              All <span className="ml-1 opacity-50">{counts.all}</span>
            </TabsTrigger>
            {(["Hot", "Warm", "Cold", "Converted", "Lost"] as LeadStatus[]).map((s) => (
              <TabsTrigger key={s} value={s} className="text-xs">
                {s}
                <span className="ml-1 opacity-50">{counts[s] ?? 0}</span>
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <div className="relative w-full sm:w-72">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search name, email, message, source…"
            className="h-8 pl-8 text-xs"
          />
        </div>
      </div>

      {/* Table */}
      <div className="rounded-lg border border-border/60 bg-card">
        <div className="max-h-[460px] overflow-auto">
          <Table>
            <TableHeader className="sticky top-0 z-10 bg-card">
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-[60px] text-xs">#</TableHead>
                <TableHead className="text-xs">Lead</TableHead>
                <TableHead className="hidden text-xs md:table-cell">Source</TableHead>
                <TableHead className="text-xs">Status</TableHead>
                <TableHead className="hidden text-xs sm:table-cell">Created</TableHead>
                <TableHead className="w-[40px]"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="py-8 text-center text-xs text-muted-foreground">
                    No leads match this filter.
                  </TableCell>
                </TableRow>
              )}
              {filtered.map((lead) => {
                const cfg = STATUS_CONFIG[lead.status];
                return (
                  <TableRow
                    key={lead.id}
                    onClick={() => onSelectLead(lead)}
                    className={`cursor-pointer transition-colors ${
                      selectedLeadId === lead.id ? "bg-violet-50 dark:bg-violet-950/30" : ""
                    }`}
                  >
                    <TableCell className="font-mono text-[11px] text-muted-foreground">
                      {lead.id}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col">
                        <span className="text-sm font-medium">{lead.name}</span>
                        <span className="text-[11px] text-muted-foreground">
                          {lead.contact_info || "—"}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="hidden text-xs md:table-cell text-muted-foreground">
                      {lead.source || "—"}
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="outline"
                        className={`gap-1 px-2 py-0.5 text-[11px] font-medium ${cfg.badgeClass}`}
                      >
                        <span className={`h-1.5 w-1.5 rounded-full ${cfg.dotClass}`} />
                        {cfg.label}
                      </Badge>
                    </TableCell>
                    <TableCell className="hidden text-xs text-muted-foreground sm:table-cell">
                      {formatRelativeTime(lead.created_at)}
                    </TableCell>
                    <TableCell>
                      <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      </div>
    </div>
  );
}
