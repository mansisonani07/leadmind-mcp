"use client";

import { useEffect, useState, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Header } from "./Header";
import { StatsGrid, StatusDistribution, SourceBreakdown } from "./StatsGrid";
import { LeadsTable } from "./LeadsTable";
import { LeadDetailDrawer } from "./LeadDetailDrawer";
import { AuditPanel } from "./AuditPanel";
import { McpPrimitivesPanel } from "./McpPrimitivesPanel";
import { AddLeadDialog } from "./AddLeadDialog";
import {
  Lead,
  Stats,
  AuditEntry,
  Dashboard as DashboardType,
  api,
} from "@/lib/leadmind-api";
import { toast } from "sonner";
import { Loader2, Plus, AlertTriangle } from "lucide-react";

type LoadState = "loading" | "loaded" | "error";

export function DashboardPage() {
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [dashboard, setDashboard] = useState<DashboardType | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  const fetchAll = useCallback(async () => {
    try {
      const [dashRes, statsRes, leadsRes, auditRes] = await Promise.all([
        api.dashboard(),
        api.stats(),
        api.listLeads(),
        api.audit(50),
      ]);
      setDashboard(dashRes);
      setStats(statsRes);
      setLeads(leadsRes.leads);
      setAudit(auditRes.entries);
      setLoadState("loaded");
      setErrorMsg(null);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMsg(msg);
      setLoadState("error");
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    await fetchAll();
    setRefreshing(false);
    toast.success("Dashboard refreshed");
  }, [fetchAll]);

  const handleLeadUpdated = useCallback(() => {
    fetchAll();
  }, [fetchAll]);

  const handleLeadAdded = useCallback(() => {
    fetchAll();
  }, [fetchAll]);

  const handleSelectLead = useCallback((lead: Lead) => {
    setSelectedLead(lead);
    setDrawerOpen(true);
  }, []);

  if (loadState === "error") {
    return (
      <div className="flex min-h-screen items-center justify-center p-4">
        <div className="w-full max-w-md space-y-4 rounded-xl border border-destructive/30 bg-destructive/5 p-6 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
            <AlertTriangle className="h-6 w-6 text-destructive" />
          </div>
          <h2 className="text-lg font-semibold">Connection Error</h2>
          <p className="text-sm text-muted-foreground">{errorMsg}</p>
          <p className="text-xs text-muted-foreground">
            Make sure the backend is running at the configured URL.
          </p>
          <Button onClick={handleRefresh} variant="outline" className="gap-2">
            <Loader2 className="h-4 w-4" />
            Retry
          </Button>
        </div>
      </div>
    );
  }

  if (loadState === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="h-8 w-8 animate-spin text-violet-500" />
          <p className="text-sm text-muted-foreground">Loading dashboard…</p>
        </div>
      </div>
    );
  }

  const groqCalls = dashboard?.groq_usage?.in_memory_calls_this_session ?? 0;

  return (
    <div className="min-h-screen bg-background">
      <Header
        demoMode={dashboard?.stats ? true : false}
        groqCallsThisSession={groqCalls}
        onRefresh={handleRefresh}
        onResetDemo={async () => {
          try {
            await api.resetDemo();
            toast.success("Demo data reset");
            await fetchAll();
          } catch (e) {
            toast.error(e instanceof Error ? e.message : "Reset failed");
          }
        }}
        refreshing={refreshing}
      />
      <main className="mx-auto max-w-[1400px] space-y-4 px-4 py-4 sm:px-6 lg:px-8">
        <StatsGrid stats={stats} />
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="space-y-4 lg:col-span-2">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-medium">Leads</h2>
              <Button size="sm" className="gap-1.5" onClick={() => setAddDialogOpen(true)}>
                <Plus className="h-3.5 w-3.5" />
                Add Lead
              </Button>
            </div>
            <LeadsTable leads={leads} onSelectLead={handleSelectLead} selectedLeadId={selectedLead?.id} />
          </div>
          <div className="space-y-4">
            <StatusDistribution stats={stats} />
            <SourceBreakdown stats={stats} />
            <McpPrimitivesPanel />
          </div>
        </div>
        <AuditPanel audit={audit} groqUsage={stats?.groq_usage ?? null} />
      </main>
      <LeadDetailDrawer lead={selectedLead} open={drawerOpen} onOpenChange={setDrawerOpen} onLeadUpdated={handleLeadUpdated} />
      <AddLeadDialog open={addDialogOpen} onOpenChange={setAddDialogOpen} onLeadAdded={handleLeadAdded} />
    </div>
  );
}
