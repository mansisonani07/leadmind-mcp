"use client";

import { useState, useEffect, useCallback } from "react";
import { api, type Lead, type Dashboard as DashboardData, type LeadWithHistory } from "@/lib/leadmind-api";
import { Header } from "./Header";
import { StatsGrid } from "./StatsGrid";
import { LeadsTable } from "./LeadsTable";
import { LeadDetailDrawer } from "./LeadDetailDrawer";
import { AuditPanel } from "./AuditPanel";
import { McpPrimitivesPanel } from "./McpPrimitivesPanel";
import { AddLeadDialog } from "./AddLeadDialog";

export default function DashboardPage() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [filter, setFilter] = useState<string | undefined>(undefined);
  const [selectedLeadId, setSelectedLeadId] = useState<number | null>(null);
  const [selectedLead, setSelectedLead] = useState<LeadWithHistory | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDashboard = useCallback(async () => {
    try {
      const data = await api.dashboard();
      setDashboard(data);
      setLeads(data.recent_leads || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch dashboard");
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchLeads = useCallback(async (status?: string) => {
    try {
      const data = await api.listLeads(status as any);
      setLeads(data.leads);
    } catch (err) {
      console.error("Failed to fetch leads:", err);
    }
  }, []);

  useEffect(() => {
    fetchDashboard();
  }, [fetchDashboard]);

  useEffect(() => {
    fetchLeads(filter);
  }, [filter, fetchLeads]);

  const handleSelectLead = useCallback(async (leadId: number) => {
    setSelectedLeadId(leadId);
    setDrawerOpen(true);
    try {
      const data = await api.getLead(leadId);
      setSelectedLead(data);
    } catch (err) {
      console.error("Failed to fetch lead:", err);
    }
  }, []);

  const handleLeadAdded = useCallback(() => {
    setAddDialogOpen(false);
    fetchDashboard();
    fetchLeads(filter);
  }, [fetchDashboard, fetchLeads, filter]);

  const handleFilterChange = useCallback((status: string | undefined) => {
    setFilter(status);
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-slate-400">Loading LeadMind dashboard...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center max-w-md">
          <div className="text-red-400 text-lg mb-2">Connection Error</div>
          <div className="text-slate-400 text-sm">{error}</div>
          <div className="text-slate-500 text-xs mt-2">
            Make sure the backend is running at the configured URL.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <Header />
      <main className="container mx-auto px-4 py-6 space-y-6">
        <StatsGrid stats={dashboard?.stats ?? null} />
        <LeadsTable
          leads={leads}
          onSelectLead={handleSelectLead}
          selectedLeadId={selectedLeadId}
          onAddLead={() => setAddDialogOpen(true)}
          onFilterChange={handleFilterChange}
          currentFilter={filter}
        />
        <McpPrimitivesPanel />
        <AuditPanel audit={dashboard?.audit ?? []} groqUsage={dashboard?.groq_usage} />
      </main>

      <LeadDetailDrawer
        lead={selectedLead}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
      />

      <AddLeadDialog
        open={addDialogOpen}
        onOpenChange={setAddDialogOpen}
        onLeadAdded={handleLeadAdded}
      />
    </div>
  );
}
