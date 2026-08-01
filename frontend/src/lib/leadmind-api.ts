/**
 * LeadMind API client.
 *
 * All requests go through the Next.js API routes in src/app/api/leadmind/[...path]/route.ts
 * which proxy to the Python FastAPI backend on port 8000 via XTransformPort.
 *
 * The Python backend (leadmind-mcp/api_server.py) is the source of truth —
 * it reads/writes the same SQLite DB that the MCP server uses.
 */

export type LeadStatus = "Hot" | "Warm" | "Cold" | "Converted" | "Lost";

export interface Lead {
  id: number;
  name: string;
  contact_info: string | null;
  message: string | null;
  status: LeadStatus;
  source: string | null;
  created_at: string;
  last_contacted_at: string | null;
  converted_at: string | null;
}

export interface HistoryEntry {
  id: number;
  lead_id: number;
  event_type: "created" | "status_change" | "classified" | "contacted" | "note" | string;
  event_description: string | null;
  old_value: string | null;
  new_value: string | null;
  created_at: string;
}

export interface LeadWithHistory {
  lead: Lead;
  history: HistoryEntry[];
}

export interface Classification {
  status: LeadStatus;
  confidence: number;
  reasoning: string;
  source: "groq" | "fallback" | "cache";
  keywords?: string[];
}

export interface AddLeadResponse {
  id: number;
  name: string;
  status: LeadStatus;
  classification: Classification;
}

export interface Stats {
  total_leads: number;
  by_status: Record<string, number>;
  by_source: Record<string, number>;
  average_response_time_minutes: number;
  conversion_rate_percent: number;
  groq_usage: {
    in_memory_calls_this_session: number;
    total_logged_calls: number;
    logged_success: number;
    logged_rate_limited: number;
    logged_errors: number;
  };
}

export interface AuditEntry {
  id: number;
  tool_name: string;
  params: string | null;
  used_groq: number;
  used_fallback: number;
  used_cache: number;
  success: number;
  error_message: string | null;
  duration_ms: number | null;
  created_at: string;
}

export interface Dashboard {
  stats: Stats;
  recent_leads: Lead[];
  groq_usage: Stats["groq_usage"];
  audit: AuditEntry[];
}

export interface NextAction {
  lead_id: number;
  lead_name: string;
  current_status: LeadStatus;
  suggestion: string;
  source: "groq" | "fallback";
}

const API_BASE = process.env.NEXT_PUBLIC_LEADMIND_BACKEND_URL
  ? process.env.NEXT_PUBLIC_LEADMIND_BACKEND_URL.replace(/\/+$/, "")
  : "/api/leadmind";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  health: () => apiFetch<{ status: string; demo_mode: boolean }>("/health"),
  dashboard: () => apiFetch<Dashboard>("/dashboard"),
  stats: () => apiFetch<Stats>("/stats"),
  listLeads: (status?: LeadStatus) =>
    apiFetch<{ count: number; filter: string; leads: Lead[] }>(
      `/leads${status ? `?status=${status}` : ""}`
    ),
  getLead: (id: number) => apiFetch<LeadWithHistory>(`/leads/${id}`),
  addLead: (payload: { name: string; contact_info: string; message: string; source: string }) =>
    apiFetch<AddLeadResponse>("/leads", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateStatus: (id: number, status: LeadStatus) =>
    apiFetch<{ id: number; old_status: string; new_status: string; updated_at: string }>(
      `/leads/${id}/status`,
      { method: "PATCH", body: JSON.stringify({ status }) }
    ),
  nextAction: (id: number) => apiFetch<NextAction>(`/leads/${id}/next-action`),
  audit: (limit = 50) => apiFetch<{ count: number; entries: AuditEntry[] }>(`/audit?limit=${limit}`),
  resetDemo: () => apiFetch<{ reset: boolean; message: string }>(`/demo/reset`, { method: "POST" }),
};
