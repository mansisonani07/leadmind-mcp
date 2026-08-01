"""
LeadMind MCP — Self-contained FastAPI web dashboard + REST API.

This single file serves:
  - The dashboard UI at /                  (HTML, server-rendered)
  - The JSON API at /api/*                 (used by the dashboard JS)
  - Health + meta endpoints at /health, /stats, /dashboard

Run:
    python web_dashboard.py                # listens on :8000
    GROQ_API_KEY=gsk_... python web_dashboard.py    # with Groq enabled
    DEMO_RESET_INTERVAL_SEC=14400 python web_dashboard.py   # 4h reset

Environment variables (all optional, see config.py for full list):
    GROQ_API_KEY                 — free Groq key (https://console.groq.com/keys)
    DEMO_MODE=true               — auto-reset DB to seed data every N seconds
    DEMO_RESET_INTERVAL_SEC=14400 — 4 hours (good for public demo)
    PORT=8000                    — override listen port

The dashboard talks to /api/* on the same origin, so it works behind any
reverse proxy (Caddy, nginx, Cloudflare) without CORS configuration.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict, Optional

# Allow `python web_dashboard.py` from the project dir
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Header, HTTPException, Query, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import (  # noqa: E402
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
)

from config import (  # noqa: E402
    LEADMIND_AUTH_ENABLED,
    LEADMIND_API_KEY,
    DEMO_MODE,
)
from db import (  # noqa: E402
    fetch_audit_summary,
    fetch_lead,
    fetch_lead_history,
    fetch_leads,
    fetch_recent_leads,
    fetch_stats,
    init_db,
)
from groq_classifier import get_usage_snapshot  # noqa: E402
from seed_data import seed_database  # noqa: E402
from tools import (  # noqa: E402
    add_lead,
    bulk_import_leads,
    classify_lead,
    get_lead_stats,
    suggest_next_action,
    update_lead_status,
)

# Override demo reset to 4 hours for the public deployment (unless overridden)
os.environ.setdefault("DEMO_RESET_INTERVAL_SEC", "14400")  # 4 hours
os.environ.setdefault("DEMO_MODE", "true")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("leadmind.dashboard")

# Re-import config AFTER env overrides so DEMO_RESET_INTERVAL_SEC takes effect
from importlib import reload  # noqa: E402
import config as _config  # noqa: E402
reload(_config)
from config import DEMO_RESET_INTERVAL_SEC  # noqa: E402

# Initialize DB on startup
init_db()
seed_database(force=False)
logger.info(
    "LeadMind dashboard starting. demo_mode=%s, reset_interval=%ss",
    DEMO_MODE,
    DEMO_RESET_INTERVAL_SEC,
)

app = FastAPI(
    title="LeadMind MCP — Web Dashboard",
    version="1.0.0",
    description="Self-contained FastAPI dashboard + REST API for the LeadMind CRM.",
)

# Permissive CORS (the dashboard is same-origin, but this helps if anyone
# hits the API from elsewhere during the demo)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _check_auth(x_api_key: Optional[str]) -> None:
    if LEADMIND_AUTH_ENABLED:
        if not x_api_key or x_api_key != LEADMIND_API_KEY:
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")


# ===========================================================================
# DASHBOARD HTML (single-page app, vanilla JS, Tailwind via CDN)
# Defined here so the route below can reference it at module load time.
# ===========================================================================

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en" class="h-full">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>LeadMind MCP — AI Lead Management CRM</title>
  <meta name="description" content="Conversational AI lead management powered by MCP. Free-tier only: Groq LLM + SQLite. Built with caching, fallback, and demo-safe reliability engineering." />
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      theme: {
        extend: {
          fontFamily: {
            sans: ['ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
            mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
          },
        },
      },
      darkMode: 'class',
    }
  </script>
  <!-- Lightweight chart library: Chart.js v4 (~70KB gzip, no dependencies) -->
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    body { font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
    .tabular-nums { font-variant-numeric: tabular-nums; }
    ::-webkit-scrollbar { width: 8px; height: 8px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: rgba(0,0,0,0.15); border-radius: 4px; }
    ::-webkit-scrollbar-thumb:hover { background: rgba(0,0,0,0.25); }
    .dark ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.15); }
    .card { transition: transform 0.15s ease, box-shadow 0.15s ease, background-color 0.2s ease, border-color 0.2s ease; }
    .card:hover { transform: translateY(-1px); }
    .drawer { transition: transform 0.25s ease; }
    .modal-backdrop { animation: fadeIn 0.15s ease; }
    .modal-content { animation: slideUp 0.2s ease; }
    @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
    @keyframes slideUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
    /* Theme transition */
    body, header, main, footer { transition: background-color 0.2s ease, border-color 0.2s ease, color 0.2s ease; }
    /* Collapsible section */
    .collapse-content { max-height: 0; overflow: hidden; transition: max-height 0.4s ease, opacity 0.2s ease; opacity: 0; }
    .collapse-content.open { max-height: 1800px; opacity: 1; }
    .collapse-arrow { transition: transform 0.2s ease; }
    .collapse-arrow.open { transform: rotate(180deg); }
    /* Architecture diagram */
    .arch-node { transition: transform 0.15s ease, box-shadow 0.15s ease; }
    .arch-node:hover { transform: translateY(-2px); box-shadow: 0 8px 16px -8px rgba(139,92,246,0.30); }
    .arch-arrow { stroke-dasharray: 4 4; animation: dash 1s linear infinite; }
    @keyframes dash { to { stroke-dashoffset: -8; } }
    /* Toast stack — sits BELOW the header (header is ~64px tall) so it never overlaps pills */
    #toasts { top: 5rem !important; right: 1rem !important; max-width: calc(100vw - 2rem); z-index: 60; }
    /* Sample chips wrap and ellipsize at word boundary */
    .sample-chip { max-width: 100%; white-space: normal; overflow-wrap: anywhere; }
    /* Timeline detail toggle */
    .timeline-details { overflow: hidden; max-height: 0; transition: max-height 0.2s ease; }
    .timeline-details.open { max-height: 400px; }
    /* Drawer message box — taller line-height for readability */
    .drawer-message p { line-height: 1.6; }
  </style>
  <script>
    // Theme bootstrap — runs before body renders to avoid flash.
    // Per spec: persisted in-memory ONLY for the session (no localStorage).
    window.__leadmindTheme = window.__leadmindTheme || 'light';
    if (window.__leadmindTheme === 'dark') {
      document.documentElement.classList.add('dark');
    }
  </script>
</head>
<body class="h-full bg-gradient-to-b from-white to-slate-50 text-slate-900 dark:from-slate-950 dark:to-slate-900 dark:text-slate-100">
  <div id="app" class="min-h-full"></div>

  <!-- Toast container (positioned below header — see #toasts CSS rule) -->
  <div id="toasts" class="fixed flex flex-col gap-2 pointer-events-none"></div>

  <script>
    // =========================================================================
    // LeadMind Dashboard — vanilla JS single-page app (upgraded)
    // =========================================================================

    // ---- Lucide-style inline SVG icons (P1-8: replace all emoji with one icon set) ----
    // Each entry is just the inner <path> markup; the wrapping <svg> is added by icon().
    const ICONS = {
      sparkles: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z"/>',
      bolt:     '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/>',
      database: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7c0 1.657 3.582 3 8 3s8-1.343 8-3-3.582-3-8-3-8 1.343-8 3zm0 0v10c0 1.657 3.582 3 8 3s8-1.343 8-3V7M4 12c0 1.657 3.582 3 8 3s8-1.343 8-3"/>',
      cube:     '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"/>',
      users:    '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z"/>',
      flame:    '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.24 17 6.657c.5.786 1 1.343 1 2.343a4 4 0 01-4 4v2a6 6 0 01-3-5.244M9 18a3 3 0 104 0"/>',
      chart:    '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>',
      clock:    '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>',
      check:    '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>',
      flask:    '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.214M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.169.659 1.591L19.8 15.553c.595.595.921 1.402.921 2.243v2.454a2.25 2.25 0 01-2.25 2.25h-13.5A2.25 2.25 0 013 20.25v-2.454c0-.841.326-1.648.921-2.243l2.39-2.39M14.25 3.104c.251.023.501.05.75.082M19.5 6.75l.75-.75M3 6.75l-.75.75m15-3.5h.01m-12 0h.01"/>',
      mail:     '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>',
      chat:     '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>',
      list:     '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/>',
      inbox:    '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-3.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 007.586 13H4"/>',
      activity: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"/>',
      webhook:  '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H9m2 0h2m-3-7a4 4 0 01-4-4V7a4 4 0 014-4h1a4 4 0 014 4v3a4 4 0 01-4 4z"/>',
      plus:     '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>',
      download: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/>',
      arrow_right: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"/>',
      chevron_down: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>',
      chevron_right: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/>',
      search:   '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>',
      inbox_empty: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-3.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 007.586 13H4"/>',
      shield:   '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/>',
      refresh:  '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>',
    };
    function icon(name, cls = 'h-4 w-4') {
      const inner = ICONS[name] || '';
      return `<svg class="${cls}" fill="none" stroke="currentColor" viewBox="0 0 24 24">${inner}</svg>`;
    }

    const STATUS_CONFIG = {
      Hot:       { badge: 'bg-red-100 text-red-700 border-red-200 dark:bg-red-950/60 dark:text-red-300 dark:border-red-900', dot: 'bg-red-500', chart: '#ef4444', desc: 'Urgent, budget approved, decision-ready' },
      Warm:      { badge: 'bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-950/60 dark:text-amber-300 dark:border-amber-900', dot: 'bg-amber-500', chart: '#f59e0b', desc: 'Evaluating, no urgency yet' },
      Cold:      { badge: 'bg-sky-100 text-sky-700 border-sky-200 dark:bg-sky-950/60 dark:text-sky-300 dark:border-sky-900', dot: 'bg-sky-500', chart: '#0ea5e9', desc: 'Passive, future-only, nurturing' },
      Converted: { badge: 'bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-950/60 dark:text-emerald-300 dark:border-emerald-900', dot: 'bg-emerald-500', chart: '#10b981', desc: 'Closed-won, onboarded customer' },
      Lost:      { badge: 'bg-zinc-200 text-zinc-600 border-zinc-300 dark:bg-zinc-800/60 dark:text-zinc-400 dark:border-zinc-700', dot: 'bg-zinc-400', chart: '#71717a', desc: 'Closed-lost, re-engage later' },
    };

    const STATE = {
      leads: [],
      stats: null,
      audit: [],
      groqUsage: null,
      demoMode: false,
      groqKeyConfigured: false,
      filter: 'all',
      search: '',
      selectedLead: null,
      leadDetail: null,
      nextAction: null,
      loadingDetail: false,
      loadingAction: false,
      addModalOpen: false,
      refreshing: false,
      // New UI state
      theme: window.__leadmindTheme || 'light',
      classifyInput: '',
      classifyResult: null,
      classifying: false,
      howItWorksOpen: false,
      // Polish-pass additions
      auditOpen: false,
      webhookOpen: true,
      webhooks: [],
      selectedLeadIds: new Set(),
      bulkClassifying: false,
      lastClassifyLatencyMs: null,
    };

    // Chart instances — destroyed & recreated on each render to avoid leaks.
    let __charts = {};
    function destroyCharts() {
      Object.values(__charts).forEach(c => { try { c.destroy(); } catch {} });
      __charts = {};
    }

    // -------------------------------------------------------------------------
    // API helpers (unchanged — same endpoints as before)
    // -------------------------------------------------------------------------
    const XTP = new URLSearchParams(window.location.search).get('XTransformPort');
    function withXtp(path) {
      if (!XTP) return path;
      const sep = path.includes('?') ? '&' : '?';
      return `${path}${sep}XTransformPort=${XTP}`;
    }

    async function api(path, opts = {}) {
      const res = await fetch(withXtp(path), {
        ...opts,
        headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
      });
      if (!res.ok) {
        let detail = `${res.status} ${res.statusText}`;
        try { const b = await res.json(); if (b?.detail) detail = b.detail; } catch {}
        throw new Error(detail);
      }
      if (res.status === 204) return undefined;
      return res.json();
    }

    const apiHealth     = () => api('/api/health');
    const apiStats      = () => api('/api/stats');
    const apiListLeads  = (status) => api('/api/leads' + (status ? `?status=${status}` : ''));
    const apiGetLead    = (id) => api(`/api/leads/${id}`);
    const apiAddLead    = (p) => api('/api/leads', { method: 'POST', body: JSON.stringify(p) });
    const apiUpdateStat = (id, status) => api(`/api/leads/${id}/status`, { method: 'PATCH', body: JSON.stringify({ status }) });
    const apiNextAction = (id) => api(`/api/leads/${id}/next-action`);
    const apiClassify   = (text) => api('/api/classify', { method: 'POST', body: JSON.stringify({ text }) });
    const apiAudit      = (limit = 50) => api(`/api/audit?limit=${limit}`);
    const apiResetDemo  = () => api('/api/demo/reset', { method: 'POST' });
    // Polish-pass: webhook receiver + recent payloads
    const apiWebhookSend    = (p) => api('/api/webhook/lead', { method: 'POST', body: JSON.stringify(p) });
    const apiWebhooksRecent = () => api('/api/webhooks/recent');

    // -------------------------------------------------------------------------
    // Toast
    // -------------------------------------------------------------------------
    function toast(msg, type = 'info') {
      const colors = {
        info:    'bg-slate-800 text-white',
        success: 'bg-emerald-600 text-white',
        error:   'bg-red-600 text-white',
      };
      const el = document.createElement('div');
      el.className = `pointer-events-auto rounded-lg px-4 py-2 text-sm shadow-lg ${colors[type]} modal-content`;
      el.textContent = msg;
      document.getElementById('toasts').appendChild(el);
      setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity 0.3s'; }, 3000);
      setTimeout(() => el.remove(), 3400);
    }

    // -------------------------------------------------------------------------
    // Formatting
    // -------------------------------------------------------------------------
    function fmtRelative(iso) {
      if (!iso) return 'never';
      const d = new Date(iso.includes('T') ? iso : iso.replace(' ', 'T') + 'Z');
      if (isNaN(d.getTime())) return iso;
      const diff = Date.now() - d.getTime();
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

    function fmtDateTime(iso) {
      if (!iso) return '—';
      const d = new Date(iso.includes('T') ? iso : iso.replace(' ', 'T') + 'Z');
      if (isNaN(d.getTime())) return iso;
      return d.toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    }

    function escapeHtml(s) {
      if (s == null) return '';
      return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }

    // -------------------------------------------------------------------------
    // Confidence color coding — red <60%, amber 60-80%, green >80%
    // Used in Try it live + lead detail slide-over.
    // -------------------------------------------------------------------------
    function confidenceColor(conf) {
      const pct = (conf ?? 0) * 100;
      if (pct < 60) return 'text-red-600 dark:text-red-400';
      if (pct <= 80) return 'text-amber-600 dark:text-amber-400';
      return 'text-emerald-600 dark:text-emerald-400';
    }
    function confidenceBg(conf) {
      const pct = (conf ?? 0) * 100;
      if (pct < 60) return 'bg-red-50 dark:bg-red-950/40';
      if (pct <= 80) return 'bg-amber-50 dark:bg-amber-950/40';
      return 'bg-emerald-50 dark:bg-emerald-950/40';
    }
    function confidenceLabel(conf) {
      const pct = (conf ?? 0) * 100;
      if (pct < 60) return 'low';
      if (pct <= 80) return 'medium';
      return 'high';
    }

    // -------------------------------------------------------------------------
    // Theme toggle (in-memory only — no localStorage per spec)
    // -------------------------------------------------------------------------
    function toggleTheme() {
      STATE.theme = STATE.theme === 'light' ? 'dark' : 'light';
      window.__leadmindTheme = STATE.theme;
      if (STATE.theme === 'dark') {
        document.documentElement.classList.add('dark');
      } else {
        document.documentElement.classList.remove('dark');
      }
      render();
    }

    // -------------------------------------------------------------------------
    // Data loading
    // -------------------------------------------------------------------------
    async function loadAll(silent = false) {
      if (!silent) STATE.refreshing = true;
      render();
      try {
        const [leadsRes, statsRes, auditRes, healthRes, webhooksRes] = await Promise.all([
          apiListLeads(),
          apiStats(),
          apiAudit(50),
          apiHealth(),
          apiWebhooksRecent().catch(() => ({ payloads: [] })),  // best-effort
        ]);
        STATE.leads = leadsRes.leads;
        STATE.stats = statsRes;
        STATE.audit = auditRes.entries;
        STATE.groqUsage = statsRes.groq_usage;
        STATE.demoMode = healthRes.demo_mode;
        STATE.groqKeyConfigured = healthRes.groq_key_configured;
        STATE.webhooks = webhooksRes.payloads || [];
      } catch (e) {
        toast(e.message, 'error');
      } finally {
        STATE.refreshing = false;
        render();
      }
    }

    // -------------------------------------------------------------------------
    // Render
    // -------------------------------------------------------------------------
    function render() {
      try {
        destroyCharts();
        document.getElementById('app').innerHTML = `
          ${renderHeader()}
          <main class="mx-auto max-w-[1400px] space-y-6 px-4 py-6 sm:px-6 lg:px-8">
            ${renderHero()}
            ${renderTryItLive()}
            ${renderStatsGrid()}
            ${renderMainGrid()}
            ${renderHowItWorks()}
            ${renderWebhookPanel()}
            ${renderAuditPanel()}
            ${renderFooter()}
          </main>
          ${STATE.selectedLead ? renderDrawer() : ''}
          ${STATE.addModalOpen ? renderAddModal() : ''}
        `;
        attachHandlers();
        // Defer chart init to next frame so the canvas elements are fully
        // laid out in the DOM before Chart.js measures them. This prevents
        // a race condition where Chart.js reads 0 width/height right after
        // innerHTML is set, which previously caused a blank screen on
        // theme toggle (chart.js would throw, leaving render() incomplete).
        requestAnimationFrame(() => {
          try { initCharts(); } catch (e) { console.error('initCharts failed:', e); }
        });
      } catch (err) {
        console.error('render() failed:', err);
        // Last-resort: surface the error so the user doesn't see a blank screen
        const app = document.getElementById('app');
        if (app && (!app.innerHTML || app.innerHTML.trim() === '')) {
          app.innerHTML = `<div class="p-8 text-center text-red-600 dark:text-red-400">
            <p class="font-semibold">Render error</p>
            <pre class="mt-2 text-xs text-left whitespace-pre-wrap">${escapeHtml(String(err))}</pre>
            <button data-action="refresh" class="mt-4 rounded-md bg-violet-600 px-3 py-1.5 text-sm text-white">Reload</button>
          </div>`;
          const btn = app.querySelector('[data-action="refresh"]');
          if (btn) btn.addEventListener('click', () => loadAll());
        }
      }
    }

    function renderHeader() {
      const groqCalls = STATE.groqUsage?.in_memory_calls_this_session ?? 0;
      const isDark = STATE.theme === 'dark';
      return `
        <header class="sticky top-0 z-40 w-full border-b border-slate-200/60 bg-white/80 backdrop-blur dark:bg-slate-950/80 dark:border-slate-800/60">
          <div class="mx-auto flex h-16 max-w-[1400px] items-center gap-3 px-4 sm:gap-4 sm:px-6 lg:px-8">
            <div class="flex items-center gap-3">
              <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-fuchsia-500 text-white shadow-sm">
                <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/></svg>
              </div>
              <div class="flex flex-col">
                <div class="flex items-center gap-2">
                  <span class="text-base font-semibold tracking-tight">LeadMind</span>
                  <span class="hidden sm:inline-flex items-center rounded bg-violet-50 px-1.5 py-0 text-[10px] font-medium uppercase tracking-wider text-violet-700 dark:bg-violet-950/50 dark:text-violet-300">MCP</span>
                </div>
                <span class="text-[11px] text-slate-500 dark:text-slate-400">AI Lead Management CRM</span>
              </div>
            </div>
            <div class="ml-2 hidden items-center gap-2 lg:flex">
              ${pill('sparkles', 'Groq Llama-3.3-70b')}
              ${pill('database', 'SQLite')}
              ${pill('cube', 'MCP SDK')}
            </div>
            <div class="ml-auto flex items-center gap-1.5 sm:gap-2">
              ${STATE.groqKeyConfigured
                ? `<span class="hidden md:inline-flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-[11px] font-medium text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-300"><span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>Groq</span>`
                : `<span class="hidden md:inline-flex items-center gap-1 rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] font-medium text-amber-700 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-300">Fallback</span>`
              }
              ${STATE.demoMode
                ? `<span class="hidden md:inline-flex items-center gap-1 rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-[11px] font-medium text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-300">Demo</span>`
                : ''
              }
              <span class="hidden sm:inline-flex items-center gap-1 whitespace-nowrap rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] font-medium text-amber-700 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-300">Calls: ${groqCalls}</span>
              <button data-action="toggle-theme" title="Toggle dark / light theme" class="inline-flex h-8 w-8 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800">
                ${isDark
                  ? `<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"/></svg>`
                  : `<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"/></svg>`
                }
              </button>
              <button data-action="refresh" class="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:hover:bg-slate-800 ${STATE.refreshing ? 'opacity-50' : ''}">
                <svg class="h-3.5 w-3.5 ${STATE.refreshing ? 'animate-spin' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
                <span class="hidden sm:inline">Refresh</span>
              </button>
              ${STATE.demoMode ? `
                <button data-action="reset-demo" class="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:hover:bg-slate-800 ${STATE.refreshing ? 'opacity-50' : ''}">
                  <svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
                  <span class="hidden sm:inline">Reset</span>
                </button>
              ` : ''}
            </div>
          </div>
        </header>
      `;
    }

    function pill(iconName, label) {
      return `<span class="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-medium text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400">${icon(iconName, 'h-3 w-3')} ${label}</span>`;
    }

    function renderHero() {
      return `
        <section class="flex flex-col gap-3 rounded-xl border border-violet-200/40 bg-gradient-to-br from-violet-50/80 via-fuchsia-50/40 to-white p-5 dark:border-violet-900/40 dark:from-violet-950/30 dark:via-fuchsia-950/20">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 class="text-xl font-semibold tracking-tight sm:text-2xl">Lead Pipeline Dashboard</h1>
              <p class="mt-1 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
                Live view of the LeadMind CRM. Data is read directly from the SQLite database that the MCP server manages — every change here is visible to any MCP client (Claude Desktop, Cursor) connected to the same backend.
              </p>
            </div>
            <button data-action="open-add" class="inline-flex items-center gap-1.5 rounded-md bg-violet-600 px-3 py-1.5 text-sm font-medium text-white shadow-sm hover:bg-violet-700">
              <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
              Add lead
            </button>
          </div>
        </section>
      `;
    }

    // -------------------------------------------------------------------------
    // NEW: "Try it live" classify panel — calls real /api/classify endpoint
    // -------------------------------------------------------------------------
    function renderTryItLive() {
      const r = STATE.classifyResult;
      const cfg = r ? (STATUS_CONFIG[r.status] || STATUS_CONFIG.Warm) : null;
      const isCacheHit = r && r.source === 'cache';
      const samples = [
        'We urgently need a CRM, budget approved, ready to sign this week.',
        'Just researching options for next year, not ready to buy.',
        'Interested but need to compare with two other vendors first.',
        'Send me pricing and case studies, will get back in Q3.',
        'Not interested, please remove me from your list.',
        'We are not ready to buy anything this quarter, just looking.',
      ];
      return `
        <section class="card rounded-xl border border-violet-200/60 bg-white p-5 dark:border-violet-900/40 dark:bg-slate-900">
          <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div class="flex items-center gap-2">
              <span class="text-violet-500">${icon('flask', 'h-5 w-5')}</span>
              <div>
                <h2 class="text-base font-semibold">Try it live</h2>
                <p class="text-[11px] text-slate-500 dark:text-slate-400">Type a lead message and run the real <code class="font-mono text-violet-600 dark:text-violet-400">classify_lead</code> MCP tool. No mock — this hits the live cache → Groq → fallback chain.</p>
              </div>
            </div>
            ${r ? `<span class="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[10px] font-medium uppercase tracking-wide text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400">source: ${escapeHtml(r.source || '—')}</span>` : ''}
          </div>

          <div class="flex flex-col gap-2 sm:flex-row">
            <textarea data-action="classify-input" placeholder="Type or paste a lead message…  (⌘/Ctrl+Enter to classify)" class="min-h-[80px] flex-1 rounded-md border border-slate-200 bg-white p-3 text-sm dark:border-slate-800 dark:bg-slate-800 dark:placeholder-slate-500">${escapeHtml(STATE.classifyInput)}</textarea>
            <button data-action="classify-run" class="inline-flex items-center justify-center gap-1.5 self-end rounded-md bg-violet-600 px-4 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-violet-700 disabled:opacity-50 ${STATE.classifying ? 'opacity-60' : ''}">
              ${STATE.classifying
                ? `<svg class="h-4 w-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg><span>Classifying…</span>`
                : `<svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg><span>Classify Now</span>`
              }
            </button>
          </div>

          <div class="mt-2 flex flex-wrap gap-1.5">
            <span class="text-[10px] font-medium uppercase tracking-wide text-slate-500 self-center mr-1">Samples:</span>
            ${samples.map(s => {
              // P0-3: truncate at word boundary (not mid-word); keep title attr for full text on hover.
              const max = 64;
              let label = s;
              if (s.length > max) {
                const slice = s.slice(0, max);
                const lastSpace = slice.lastIndexOf(' ');
                label = (lastSpace > 30 ? slice.slice(0, lastSpace) : slice) + '…';
              }
              return `
              <button data-action="classify-sample" data-text="${escapeHtml(s)}" title="${escapeHtml(s)}" class="sample-chip rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] text-slate-600 hover:bg-violet-50 hover:text-violet-700 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-violet-950/40 dark:hover:text-violet-300">${escapeHtml(label)}</button>
            `;
            }).join('')}
          </div>

          ${r ? `
            <div class="mt-4 rounded-lg border border-slate-200 bg-gradient-to-br from-slate-50 to-white p-4 dark:border-slate-800 dark:from-slate-800/40 dark:to-slate-900">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div class="flex items-center gap-3">
                  <span class="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm font-semibold ${cfg.badge}">
                    <span class="h-2 w-2 rounded-full ${cfg.dot}"></span>${escapeHtml(r.status)}
                  </span>
                  <div>
                    <div class="text-[10px] font-medium uppercase tracking-wide text-slate-500">${cfg.desc}</div>
                    <div class="text-[11px] text-slate-500">Confidence:
                      <span class="font-mono font-semibold tabular-nums ${confidenceColor(r.confidence)}">${((r.confidence ?? 0) * 100).toFixed(0)}%</span>
                      <span class="ml-1 inline-flex items-center rounded border border-slate-200 px-1 py-0 text-[9px] uppercase tracking-wide ${confidenceBg(r.confidence)} ${confidenceColor(r.confidence)}">${confidenceLabel(r.confidence)}</span>
                    </div>
                  </div>
                </div>
                <div class="text-right text-[10px] text-slate-500">
                  <div>via <span class="font-mono font-medium text-slate-700 dark:text-slate-300">${escapeHtml(r.source || '—')}</span></div>
                  ${STATE.lastClassifyLatencyMs != null ? `<div class="mt-0.5 tabular-nums">${STATE.lastClassifyLatencyMs}ms</div>` : ''}
                  ${isCacheHit ? `<div class="mt-0.5 inline-flex items-center gap-1 rounded bg-sky-50 px-1.5 py-0.5 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300"><span class="h-1 w-1 rounded-full bg-sky-500"></span>cache hit</div>` : ''}
                </div>
              </div>
              <div class="mt-3 rounded-md border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900">
                <div class="mb-1 text-[10px] font-medium uppercase tracking-wide text-slate-500">Reasoning</div>
                <p class="text-sm leading-relaxed">${escapeHtml(r.reasoning || '—')}</p>
              </div>
              ${r.keywords && r.keywords.length ? `
                <div class="mt-2 flex flex-wrap items-center gap-1.5">
                  <span class="text-[10px] font-medium uppercase tracking-wide text-slate-500">Keywords</span>
                  ${r.keywords.map(k => `<span class="inline-flex items-center rounded border border-violet-200 bg-violet-50 px-1.5 py-0.5 text-[10px] font-mono text-violet-700 dark:border-violet-900 dark:bg-violet-950/40 dark:text-violet-300">${escapeHtml(k)}</span>`).join('')}
                </div>
              ` : ''}
            </div>
          ` : STATE.classifying ? `
            <div class="mt-4 flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 p-4 text-xs text-slate-500 dark:border-slate-800 dark:bg-slate-800/40">
              <svg class="h-4 w-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
              Calling classify_lead tool…
            </div>
          ` : `
            <div class="mt-4 flex flex-col items-center justify-center rounded-lg border border-dashed border-slate-200 bg-slate-50/40 p-6 text-center dark:border-slate-700 dark:bg-slate-800/20">
              <span class="text-violet-500 opacity-60">${icon('chat', 'h-7 w-7')}</span>
              <p class="mt-1.5 text-sm font-medium text-slate-600 dark:text-slate-300">Run a classification to see results here</p>
              <p class="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">Click a sample chip above, or type your own lead message.</p>
            </div>
          `}
        </section>
      `;
    }

    function renderStatsGrid() {
      const s = STATE.stats || { total_leads: 0, by_status: {}, by_source: {}, conversion_rate_percent: 0, average_response_time_minutes: 0, groq_usage: {} };
      const hot = s.by_status?.Hot ?? 0;
      const warm = s.by_status?.Warm ?? 0;
      const cold = s.by_status?.Cold ?? 0;
      const converted = s.by_status?.Converted ?? 0;
      const groqCalls = s.groq_usage?.in_memory_calls_this_session ?? 0;
      const cards = [
        { label: 'Total Leads', value: s.total_leads, icon: icon('users', 'h-4 w-4'), hint: `${Object.keys(s.by_source || {}).length} sources`, accent: 'text-violet-600' },
        { label: 'Hot Leads', value: hot, icon: icon('flame', 'h-4 w-4'), hint: `${warm} warm · ${cold} cold`, accent: 'text-red-600' },
        { label: 'Conversion Rate', value: `${s.conversion_rate_percent}%`, icon: icon('chart', 'h-4 w-4'), hint: `${converted} converted`, accent: 'text-emerald-600' },
        { label: 'Avg Response', value: s.average_response_time_minutes > 0 ? `${s.average_response_time_minutes}m` : '—', icon: icon('clock', 'h-4 w-4'), hint: 'creation → first status change', accent: 'text-sky-600' },
        { label: 'Groq Calls', value: groqCalls, icon: icon('sparkles', 'h-4 w-4'), hint: 'free-tier usage this session', accent: 'text-amber-600' },
        { label: 'Sources', value: Object.keys(s.by_source || {}).length, icon: icon('check', 'h-4 w-4'), hint: 'acquisition channels', accent: 'text-fuchsia-600' },
      ];
      return `
        <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          ${cards.map(c => `
            <div class="card rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
              <div class="flex items-center justify-between pb-2">
                <span class="text-[11px] font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">${c.label}</span>
                <span class="${c.accent}">${c.icon}</span>
              </div>
              <div class="text-2xl font-semibold tracking-tight tabular-nums">${c.value}</div>
              <div class="mt-0.5 truncate text-[11px] text-slate-500 dark:text-slate-400">${c.hint}</div>
            </div>
          `).join('')}
        </div>
      `;
    }

    function renderMainGrid() {
      return `
        <div class="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_360px]">
          <div class="card rounded-lg border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
            <div class="flex items-center justify-between border-b border-slate-200 p-4 dark:border-slate-800">
              <div class="flex items-center gap-2">
                <span class="text-violet-500">${icon('list', 'h-4 w-4')}</span>
                <span class="text-sm font-medium">Leads</span>
                <span class="text-xs text-slate-500">${STATE.leads.length} total</span>
                ${STATE.selectedLeadIds.size > 0 ? `<span class="ml-2 inline-flex items-center rounded bg-violet-100 px-1.5 py-0.5 text-[10px] font-medium text-violet-700 dark:bg-violet-950/60 dark:text-violet-300">${STATE.selectedLeadIds.size} selected</span>` : ''}
              </div>
              <div class="flex items-center gap-1.5">
                ${STATE.selectedLeadIds.size > 0 ? `
                  <button data-action="bulk-classify" class="inline-flex items-center gap-1 rounded-md bg-violet-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-violet-700 ${STATE.bulkClassifying ? 'opacity-60' : ''}">
                    ${STATE.bulkClassifying ? `<svg class="h-3 w-3 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>` : icon('sparkles', 'h-3 w-3')}
                    Classify Selected
                  </button>
                  <button data-action="clear-selection" class="inline-flex items-center rounded-md border border-slate-200 bg-white px-2 py-1 text-xs font-medium hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:hover:bg-slate-800">Clear</button>
                ` : ''}
                <button data-action="export-csv" title="Export current view as CSV" class="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:hover:bg-slate-800">
                  ${icon('download', 'h-3 w-3')}
                  CSV
                </button>
              </div>
            </div>
            <div class="p-4">
              ${renderLeadsTable()}
            </div>
          </div>
          <div class="space-y-4">
            ${renderDonutChart()}
            ${renderLineChart()}
            ${renderSourceBreakdown()}
            ${renderMcpPanel()}
          </div>
        </div>
      `;
    }

    function renderLeadsTable() {
      const filtered = STATE.leads.filter(l => {
        if (STATE.filter !== 'all' && l.status !== STATE.filter) return false;
        if (STATE.search.trim()) {
          const q = STATE.search.toLowerCase();
          return (l.name || '').toLowerCase().includes(q) ||
                 (l.contact_info || '').toLowerCase().includes(q) ||
                 (l.message || '').toLowerCase().includes(q) ||
                 (l.source || '').toLowerCase().includes(q);
        }
        return true;
      });
      const counts = { all: STATE.leads.length };
      for (const l of STATE.leads) counts[l.status] = (counts[l.status] || 0) + 1;
      const tabs = ['all', 'Hot', 'Warm', 'Cold', 'Converted', 'Lost'];
      const allVisibleSelected = filtered.length > 0 && filtered.every(l => STATE.selectedLeadIds.has(l.id));
      return `
        <div class="space-y-3">
          <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div class="flex flex-wrap gap-1">
              ${tabs.map(t => `
                <button data-action="filter" data-filter="${t}" class="rounded-md px-2.5 py-1 text-xs font-medium ${STATE.filter === t ? 'bg-violet-100 text-violet-700 dark:bg-violet-950/60 dark:text-violet-300' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800'}">
                  ${t === 'all' ? 'All' : t} <span class="opacity-50">${counts[t] || 0}</span>
                </button>
              `).join('')}
            </div>
            <div class="relative w-full sm:w-80 sm:max-w-[320px]">
              <svg class="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
              <input data-action="search" type="text" value="${escapeHtml(STATE.search)}" placeholder="Search leads…" class="h-8 w-full rounded-md border border-slate-200 bg-white pl-8 pr-3 text-xs dark:border-slate-800 dark:bg-slate-900" />
            </div>
          </div>
          <div class="rounded-lg border border-slate-200 dark:border-slate-800 overflow-hidden">
            <div class="max-h-[460px] overflow-auto">
              <table class="w-full text-sm">
                <thead class="sticky top-0 bg-white dark:bg-slate-900 z-10">
                  <tr class="border-b border-slate-200 dark:border-slate-800 text-left">
                    <th class="px-3 py-2 w-[40px]">
                      <input type="checkbox" data-action="select-all" ${allVisibleSelected ? 'checked' : ''} class="h-3.5 w-3.5 rounded border-slate-300 text-violet-600 focus:ring-violet-500 dark:border-slate-600 dark:bg-slate-800" />
                    </th>
                    <th class="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-slate-500 w-[60px]">#</th>
                    <th class="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-slate-500">Lead</th>
                    <th class="hidden md:table-cell px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-slate-500">Source</th>
                    <th class="px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-slate-500">Status</th>
                    <th class="hidden sm:table-cell px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-slate-500">Created</th>
                    <th class="w-[40px]"></th>
                  </tr>
                </thead>
                <tbody>
                  ${filtered.length === 0 ? `
                    <tr><td colspan="7" class="py-8 text-center text-xs text-slate-500">No leads match this filter.</td></tr>
                  ` : filtered.map(l => {
                    const cfg = STATUS_CONFIG[l.status] || STATUS_CONFIG.Warm;
                    const selected = STATE.selectedLead?.id === l.id;
                    const checked = STATE.selectedLeadIds.has(l.id);
                    return `
                      <tr data-action="select-lead" data-id="${l.id}" class="cursor-pointer border-b border-slate-100 dark:border-slate-800/50 hover:bg-slate-50 dark:hover:bg-slate-800/50 ${selected ? 'bg-violet-50 dark:bg-violet-950/30' : ''} ${checked ? 'bg-violet-50/50 dark:bg-violet-950/20' : ''}">
                        <td class="px-3 py-2" onclick="event.stopPropagation()">
                          <input type="checkbox" data-action="select-lead-checkbox" data-id="${l.id}" ${checked ? 'checked' : ''} class="h-3.5 w-3.5 rounded border-slate-300 text-violet-600 focus:ring-violet-500 dark:border-slate-600 dark:bg-slate-800" />
                        </td>
                        <td class="px-3 py-2 font-mono text-[11px] text-slate-500">${l.id}</td>
                        <td class="px-3 py-2">
                          <div class="font-medium">${escapeHtml(l.name)}</div>
                          <div class="text-[11px] text-slate-500">${escapeHtml(l.contact_info) || '—'}</div>
                        </td>
                        <td class="hidden md:table-cell px-3 py-2 text-xs text-slate-500">${escapeHtml(l.source) || '—'}</td>
                        <td class="px-3 py-2">
                          <span class="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${cfg.badge}">
                            <span class="h-1.5 w-1.5 rounded-full ${cfg.dot}"></span>${l.status}
                          </span>
                        </td>
                        <td class="hidden sm:table-cell px-3 py-2 text-xs text-slate-500">${fmtRelative(l.created_at)}</td>
                        <td class="px-3 py-2"><svg class="h-3.5 w-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg></td>
                      </tr>
                    `;
                  }).join('')}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      `;
    }

    // -------------------------------------------------------------------------
    // NEW: Donut chart for pipeline distribution (replaces bars)
    // -------------------------------------------------------------------------
    function renderDonutChart() {
      const byStatus = STATE.stats?.by_status || {};
      const order = ['Hot', 'Warm', 'Cold', 'Converted', 'Lost'];
      const total = order.reduce((sum, s) => sum + (byStatus[s] || 0), 0);
      return `
        <div class="card rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div class="mb-3 flex items-center justify-between">
            <div class="text-sm font-medium">Pipeline Distribution</div>
            <span class="text-[10px] text-slate-500">${total} leads</span>
          </div>
          <div class="relative h-[200px]">
            <canvas id="chart-donut"></canvas>
            <div class="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
              <div class="text-2xl font-semibold tabular-nums">${total}</div>
              <div class="text-[10px] uppercase tracking-wide text-slate-500">total</div>
            </div>
          </div>
          <div class="mt-3 grid grid-cols-2 gap-1.5 sm:grid-cols-3">
            ${order.map(s => {
              const count = byStatus[s] || 0;
              const cfg = STATUS_CONFIG[s];
              const pct = total > 0 ? Math.round((count / total) * 100) : 0;
              return `
                <div class="flex items-center gap-1.5 text-[11px]">
                  <span class="h-2 w-2 rounded-full" style="background:${cfg.chart}"></span>
                  <span class="font-medium">${s}</span>
                  <span class="ml-auto tabular-nums text-slate-500">${count}</span>
                  <span class="text-slate-400">${pct}%</span>
                </div>
              `;
            }).join('')}
          </div>
        </div>
      `;
    }

    // -------------------------------------------------------------------------
    // NEW: Line chart for "Leads Created Over Time"
    // -------------------------------------------------------------------------
    function renderLineChart() {
      return `
        <div class="card rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div class="mb-3 flex items-center justify-between">
            <div class="text-sm font-medium">Leads Created Over Time</div>
            <span class="text-[10px] text-slate-500">by hour</span>
          </div>
          <div class="relative h-[180px]">
            <canvas id="chart-line"></canvas>
          </div>
        </div>
      `;
    }

    function renderSourceBreakdown() {
      const bySource = STATE.stats?.by_source || {};
      const entries = Object.entries(bySource).sort((a, b) => b[1] - a[1]);
      const max = Math.max(1, ...entries.map(([, c]) => c));
      return `
        <div class="card rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div class="mb-3 text-sm font-medium">Leads by Source</div>
          <div class="space-y-2">
            ${entries.length === 0 ? '<p class="text-xs text-slate-500">No sources yet.</p>' : ''}
            ${entries.map(([source, count]) => {
              const pct = (count / max) * 100;
              return `
                <div class="space-y-1">
                  <div class="flex items-center justify-between text-xs"><span class="font-medium">${escapeHtml(source)}</span><span class="tabular-nums text-slate-500">${count}</span></div>
                  <div class="h-1.5 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                    <div class="h-full bg-gradient-to-r from-violet-500 to-fuchsia-500 transition-all" style="width: ${pct}%"></div>
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        </div>
      `;
    }

    function renderMcpPanel() {
      const tools = [
        ['get_leads', 'List leads, filter by status'],
        ['classify_lead', 'Hot/Warm/Cold + reasoning'],
        ['add_lead', 'Add + auto-classify on insert'],
        ['update_lead_status', 'Manual override + history log'],
        ['get_lead_stats', 'Pipeline aggregate stats'],
        ['get_lead_history', 'Full timeline per lead'],
        ['suggest_next_action', 'AI-recommended next step'],
        ['bulk_import_leads', 'CSV parse + batch classify'],
      ];
      const resources = [
        ['leads://dashboard', 'Live pipeline snapshot'],
        ['audit://recent', 'Recent tool-call audit log'],
      ];
      const prompts = [['weekly_lead_review', 'Structured weekly summary']];
      return `
        <div class="card rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
          <div class="mb-3 flex items-center gap-2 text-sm font-medium"><span class="text-violet-500">🔧</span> MCP Primitives Exposed</div>
          <div class="space-y-3">
            <div>
              <div class="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-slate-500">Tools (${tools.length})</div>
              <div class="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                ${tools.map(([name, desc]) => `
                  <div class="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-2 py-1.5 dark:border-slate-800 dark:bg-slate-800/40">
                    <code class="font-mono text-[11px] font-medium text-violet-700 dark:text-violet-300">${name}</code>
                    <span class="text-[10px] text-slate-500">${desc}</span>
                  </div>
                `).join('')}
              </div>
            </div>
            <div>
              <div class="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-slate-500">Resources (${resources.length})</div>
              <div class="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                ${resources.map(([uri, desc]) => `
                  <div class="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-2 py-1.5 dark:border-slate-800 dark:bg-slate-800/40">
                    <code class="font-mono text-[11px] font-medium text-fuchsia-700 dark:text-fuchsia-300">${uri}</code>
                    <span class="text-[10px] text-slate-500">${desc}</span>
                  </div>
                `).join('')}
              </div>
            </div>
            <div>
              <div class="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-slate-500">Prompt Templates (${prompts.length})</div>
              <div class="grid grid-cols-1 gap-1.5">
                ${prompts.map(([name, desc]) => `
                  <div class="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-2 py-1.5 dark:border-slate-800 dark:bg-slate-800/40">
                    <code class="font-mono text-[11px] font-medium text-emerald-700 dark:text-emerald-300">${name}</code>
                    <span class="text-[10px] text-slate-500">${desc}</span>
                  </div>
                `).join('')}
              </div>
            </div>
            <div class="border-t border-slate-200 pt-3 dark:border-slate-800">
              <div class="mb-1.5 text-[10px] font-medium uppercase tracking-wide text-slate-500">Reliability Engineering</div>
              <div class="flex flex-wrap gap-1.5">
                <span class="inline-flex items-center gap-1 rounded-full border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-600 dark:border-slate-700 dark:text-slate-400">${icon('clock', 'h-3 w-3')} TTL cache</span>
                <span class="inline-flex items-center gap-1 rounded-full border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-600 dark:border-slate-700 dark:text-slate-400">${icon('shield', 'h-3 w-3')} Rule-based fallback</span>
                <span class="inline-flex items-center gap-1 rounded-full border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-600 dark:border-slate-700 dark:text-slate-400">${icon('bolt', 'h-3 w-3')} Rate-limit handler</span>
                <span class="inline-flex items-center gap-1 rounded-full border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-600 dark:border-slate-700 dark:text-slate-400">${icon('refresh', 'h-3 w-3')} Demo auto-reset</span>
                <span class="inline-flex items-center gap-1 rounded-full border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-600 dark:border-slate-700 dark:text-slate-400">${icon('database', 'h-3 w-3')} SQLite + WAL</span>
              </div>
            </div>
          </div>
        </div>
      `;
    }

    // -------------------------------------------------------------------------
    // NEW: Collapsible "How This Works" architecture diagram
    // -------------------------------------------------------------------------
    function renderHowItWorks() {
      const open = STATE.howItWorksOpen;
      return `
        <section class="card rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <button data-action="toggle-howitworks" class="flex w-full items-center justify-between gap-3 p-4 text-left">
            <div class="flex items-center gap-3">
              <span class="text-lg">🧭</span>
              <div>
                <h2 class="text-base font-semibold">How This Works</h2>
                <p class="text-[11px] text-slate-500 dark:text-slate-400">Architecture: MCP client → MCP server → FastAPI + SQLite, with Groq LLM → fallback classifier decision path</p>
              </div>
            </div>
            <svg class="h-4 w-4 collapse-arrow ${open ? 'open' : ''} text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
          </button>
          <div class="collapse-content ${open ? 'open' : ''}">
            <div class="border-t border-slate-200 p-5 dark:border-slate-800">
              ${renderArchitectureDiagram()}
              ${renderPipelineSteps()}
            </div>
          </div>
        </section>
      `;
    }

    function renderArchitectureDiagram() {
      const isDark = STATE.theme === 'dark';
      const lineColor = isDark ? '#a78bfa' : '#7c3aed';
      const lineColorFaint = isDark ? '#475569' : '#cbd5e1';
      const labelColor = isDark ? '#e2e8f0' : '#0f172a';
      const subColor = isDark ? '#94a3b8' : '#64748b';
      return `
        <div class="mb-4 overflow-x-auto">
          <svg viewBox="0 0 920 280" class="w-full" style="min-width: 720px;">
            <!-- Layer labels -->
            <text x="80"  y="20" font-size="10" fill="${subColor}" font-family="ui-sans-serif" font-weight="600" letter-spacing="1">CLIENT</text>
            <text x="380" y="20" font-size="10" fill="${subColor}" font-family="ui-sans-serif" font-weight="600" letter-spacing="1">MCP SERVER</text>
            <text x="700" y="20" font-size="10" fill="${subColor}" font-family="ui-sans-serif" font-weight="600" letter-spacing="1">BACKEND</text>

            <!-- 1. MCP Client (Claude Desktop) -->
            <g class="arch-node">
              <rect x="20" y="40" width="180" height="80" rx="10" fill="${isDark ? '#1e1b2e' : '#faf5ff'}" stroke="${lineColor}" stroke-width="1.5"/>
              <text x="110" y="68" text-anchor="middle" font-size="13" font-weight="600" fill="${labelColor}" font-family="ui-sans-serif">Claude Desktop</text>
              <text x="110" y="86" text-anchor="middle" font-size="10" fill="${subColor}" font-family="ui-sans-serif">MCP Client</text>
              <text x="110" y="102" text-anchor="middle" font-size="9" fill="${subColor}" font-family="ui-monospace">stdio / SSE</text>
            </g>

            <!-- Arrow: client → server -->
            <line x1="200" y1="80" x2="280" y2="80" stroke="${lineColor}" stroke-width="2" class="arch-arrow"/>
            <polygon points="280,80 272,76 272,84" fill="${lineColor}"/>
            <text x="240" y="70" text-anchor="middle" font-size="9" fill="${subColor}" font-family="ui-monospace">JSON-RPC</text>

            <!-- 2. MCP Server (FastMCP) -->
            <g class="arch-node">
              <rect x="280" y="40" width="220" height="80" rx="10" fill="${isDark ? '#1e1b2e' : '#faf5ff'}" stroke="${lineColor}" stroke-width="1.5"/>
              <text x="390" y="62" text-anchor="middle" font-size="13" font-weight="600" fill="${labelColor}" font-family="ui-sans-serif">FastMCP Server</text>
              <text x="390" y="78" text-anchor="middle" font-size="10" fill="${subColor}" font-family="ui-sans-serif">8 tools · 2 resources · 1 prompt</text>
              <line x1="300" y1="88" x2="480" y2="88" stroke="${lineColorFaint}" stroke-width="0.5" stroke-dasharray="2 2"/>
              <text x="390" y="104" text-anchor="middle" font-size="9" fill="${subColor}" font-family="ui-monospace">mcp_server.py</text>
            </g>

            <!-- Arrow: server → backend -->
            <line x1="500" y1="80" x2="580" y2="80" stroke="${lineColor}" stroke-width="2" class="arch-arrow"/>
            <polygon points="580,80 572,76 572,84" fill="${lineColor}"/>

            <!-- 3. Backend: FastAPI + SQLite -->
            <g class="arch-node">
              <rect x="580" y="40" width="180" height="80" rx="10" fill="${isDark ? '#1e1b2e' : '#faf5ff'}" stroke="${lineColor}" stroke-width="1.5"/>
              <text x="670" y="62" text-anchor="middle" font-size="13" font-weight="600" fill="${labelColor}" font-family="ui-sans-serif">FastAPI + SQLite</text>
              <text x="670" y="78" text-anchor="middle" font-size="10" fill="${subColor}" font-family="ui-sans-serif">WAL · thread-safe writes</text>
              <text x="670" y="104" text-anchor="middle" font-size="9" fill="${subColor}" font-family="ui-monospace">db.py · tools.py</text>
            </g>

            <!-- Web dashboard side note -->
            <line x1="670" y1="120" x2="670" y2="145" stroke="${lineColorFaint}" stroke-width="1" stroke-dasharray="3 3"/>
            <text x="670" y="160" text-anchor="middle" font-size="10" fill="${subColor}" font-family="ui-sans-serif">↑ this dashboard reads from /api/*</text>

            <!-- ===== Classification decision path (below) ===== -->
            <text x="20" y="190" font-size="10" fill="${subColor}" font-family="ui-sans-serif" font-weight="600" letter-spacing="1">CLASSIFY_LEAD() — RELIABILITY CHAIN</text>

            <!-- Step 1: Cache -->
            <g class="arch-node">
              <rect x="20" y="205" width="140" height="60" rx="8" fill="${isDark ? '#0c1f2e' : '#f0f9ff'}" stroke="#0ea5e9" stroke-width="1.5"/>
              <text x="90" y="227" text-anchor="middle" font-size="12" font-weight="600" fill="${labelColor}" font-family="ui-sans-serif">① TTL + LRU Cache</text>
              <text x="90" y="245" text-anchor="middle" font-size="9" fill="${subColor}" font-family="ui-monospace">SHA-256 keyed · 5min</text>
            </g>

            <!-- Arrow cache → groq (hit/miss) -->
            <line x1="160" y1="235" x2="220" y2="235" stroke="${lineColorFaint}" stroke-width="1.5"/>
            <text x="190" y="227" text-anchor="middle" font-size="9" fill="${subColor}" font-family="ui-monospace">miss</text>
            <polygon points="220,235 213,231 213,239" fill="${lineColorFaint}"/>

            <!-- Step 2: Groq -->
            <g class="arch-node">
              <rect x="220" y="205" width="180" height="60" rx="8" fill="${isDark ? '#2a1a0a' : '#fffbeb'}" stroke="#f59e0b" stroke-width="1.5"/>
              <text x="310" y="227" text-anchor="middle" font-size="12" font-weight="600" fill="${labelColor}" font-family="ui-sans-serif">② Groq LLM</text>
              <text x="310" y="245" text-anchor="middle" font-size="9" fill="${subColor}" font-family="ui-monospace">Llama-3.3-70b · free tier</text>
            </g>

            <!-- Arrow groq → fallback (on rate-limit/error) -->
            <line x1="400" y1="235" x2="460" y2="235" stroke="${lineColorFaint}" stroke-width="1.5"/>
            <text x="430" y="227" text-anchor="middle" font-size="9" fill="${subColor}" font-family="ui-monospace">429 / err</text>
            <polygon points="460,235 453,231 453,239" fill="${lineColorFaint}"/>

            <!-- Step 3: Fallback -->
            <g class="arch-node">
              <rect x="460" y="205" width="220" height="60" rx="8" fill="${isDark ? '#0f291d' : '#ecfdf5'}" stroke="#10b981" stroke-width="1.5"/>
              <text x="570" y="227" text-anchor="middle" font-size="12" font-weight="600" fill="${labelColor}" font-family="ui-sans-serif">③ Rule-based Fallback</text>
              <text x="570" y="245" text-anchor="middle" font-size="9" fill="${subColor}" font-family="ui-monospace">weighted keywords · negation-aware</text>
            </g>

            <!-- Result -->
            <line x1="680" y1="235" x2="740" y2="235" stroke="${lineColor}" stroke-width="2" class="arch-arrow"/>
            <polygon points="740,235 732,231 732,239" fill="${lineColor}"/>
            <g>
              <rect x="740" y="210" width="160" height="50" rx="8" fill="${isDark ? '#1e1b2e' : '#faf5ff'}" stroke="${lineColor}" stroke-width="1.5"/>
              <text x="820" y="230" text-anchor="middle" font-size="11" font-weight="600" fill="${labelColor}" font-family="ui-sans-serif">{ Hot | Warm | Cold }</text>
              <text x="820" y="246" text-anchor="middle" font-size="9" fill="${subColor}" font-family="ui-monospace">+ confidence + reasoning</text>
            </g>
          </svg>
        </div>
      `;
    }

    function renderPipelineSteps() {
      const steps = [
        { n: 1, title: 'Lead arrives', desc: 'Web form, webhook (n8n/Gmail bridge), or MCP client calls add_lead.', color: 'violet' },
        { n: 2, title: 'Classify', desc: 'classify_lead routes through cache → Groq → fallback. Result includes status, confidence, and human-readable reasoning.', color: 'amber' },
        { n: 3, title: 'Persist', desc: 'Lead + initial classification written to SQLite. Event logged in lead_history + audit_log.', color: 'sky' },
        { n: 4, title: 'Act', desc: 'suggest_next_action generates the next best step. update_lead_status records manual overrides.', color: 'emerald' },
        { n: 5, title: 'Review', desc: 'weekly_lead_review prompt template + leads://dashboard resource surface pipeline health to any MCP client.', color: 'fuchsia' },
      ];
      const colorMap = {
        violet: 'border-violet-200 bg-violet-50 text-violet-700 dark:border-violet-900 dark:bg-violet-950/40 dark:text-violet-300',
        amber: 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300',
        sky: 'border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-300',
        emerald: 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300',
        fuchsia: 'border-fuchsia-200 bg-fuchsia-50 text-fuchsia-700 dark:border-fuchsia-900 dark:bg-fuchsia-950/40 dark:text-fuchsia-300',
      };
      return `
        <div class="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-5">
          ${steps.map(s => `
            <div class="rounded-lg border p-3 ${colorMap[s.color]}">
              <div class="mb-1 flex items-center gap-2">
                <span class="flex h-5 w-5 items-center justify-center rounded-full bg-white text-[10px] font-bold dark:bg-slate-900">${s.n}</span>
                <span class="text-xs font-semibold">${s.title}</span>
              </div>
              <p class="text-[11px] leading-relaxed opacity-90">${s.desc}</p>
            </div>
          `).join('')}
        </div>
      `;
    }

    function renderAuditPanel() {
      const audit = STATE.audit;
      const recent = audit.slice(0, 10);  // Polish-pass: show last 10 only
      const groqCalls = audit.filter(a => a.used_groq).length;
      const fallbackCalls = audit.filter(a => a.used_fallback).length;
      const cacheHits = audit.filter(a => a.used_cache).length;
      const failures = audit.filter(a => !a.success).length;
      const u = STATE.groqUsage || {};
      const open = STATE.auditOpen;
      return `
        <section class="card rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <button data-action="toggle-audit" class="flex w-full items-center justify-between gap-3 p-4 text-left">
            <div class="flex items-center gap-3">
              <span class="text-violet-500">${icon('activity', 'h-5 w-5')}</span>
              <div>
                <h2 class="text-base font-semibold">Recent Activity — Audit Log</h2>
                <p class="text-[11px] text-slate-500 dark:text-slate-400">Last ${recent.length} tool calls (of ${audit.length} total · ${failures} failed) — every MCP tool call is persisted to the audit_log table.</p>
              </div>
            </div>
            <div class="flex items-center gap-3">
              <div class="hidden sm:flex items-center gap-2 text-[11px]">
                <span class="inline-flex items-center gap-1 rounded bg-amber-50 px-1.5 py-0.5 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">Groq ${groqCalls}</span>
                <span class="inline-flex items-center gap-1 rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">Fallback ${fallbackCalls}</span>
                <span class="inline-flex items-center gap-1 rounded bg-sky-50 px-1.5 py-0.5 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300">Cache ${cacheHits}</span>
              </div>
              <svg class="h-4 w-4 collapse-arrow ${open ? 'open' : ''} text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
            </div>
          </button>
          <div class="collapse-content ${open ? 'open' : ''}">
            <div class="border-t border-slate-200 p-4 dark:border-slate-800">
              ${u ? `
                <div class="mb-3 rounded-lg border border-amber-200/60 bg-amber-50/40 p-3 dark:border-amber-900/60 dark:bg-amber-950/20">
                  <div class="mb-1 text-[10px] font-medium uppercase tracking-wide text-amber-700 dark:text-amber-300">Free-tier monitoring</div>
                  <div class="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
                    ${statRow('Session calls', u.in_memory_calls_this_session)}
                    ${statRow('Total logged', u.total_logged_calls)}
                    ${statRow('Rate-limited (429)', u.logged_rate_limited, u.logged_rate_limited > 0)}
                    ${statRow('Errors', u.logged_errors, u.logged_errors > 0)}
                  </div>
                </div>
              ` : ''}
              <div class="rounded-lg border border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-800/20">
                ${recent.length === 0 ? '<div class="p-4 text-center text-xs text-slate-500">No tool calls yet — interact with the dashboard to populate this.</div>' : ''}
                <div class="max-h-[320px] overflow-auto">
                  ${recent.map(a => {
                    const flags = [];
                    if (a.used_groq) flags.push('groq');
                    if (a.used_fallback) flags.push('fallback');
                    if (a.used_cache) flags.push('cache');
                    const flagStr = flags.join(',') || '—';
                    return `
                      <div class="flex items-center gap-2 border-b border-slate-200 px-3 py-2 text-[11px] dark:border-slate-800">
                        <span class="font-mono text-slate-500">#${a.id}</span>
                        <span class="font-medium">${escapeHtml(a.tool_name)}</span>
                        <span class="inline-flex items-center rounded border px-1 py-0 text-[9px] ${a.success ? 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300' : 'border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300'}">${flagStr}</span>
                        ${a.duration_ms != null ? `<span class="ml-auto tabular-nums text-slate-500">${a.duration_ms}ms</span>` : ''}
                        <span class="text-slate-500">${fmtRelative(a.created_at)}</span>
                      </div>
                    `;
                  }).join('')}
                </div>
              </div>
            </div>
          </div>
        </section>
      `;
    }

    function usageStat(label, value, color) {
      return `
        <div class="rounded-lg border border-slate-200 bg-white p-2.5 dark:border-slate-800 dark:bg-slate-900">
          <div class="text-[10px] font-medium uppercase tracking-wide text-slate-500">${label}</div>
          <div class="mt-0.5 text-lg font-semibold tabular-nums">${value}</div>
        </div>
      `;
    }

    function statRow(label, value, warn) {
      return `
        <div class="flex items-center justify-between">
          <span class="text-slate-500">${label}</span>
          <span class="font-mono font-semibold tabular-nums ${warn ? 'text-amber-700 dark:text-amber-400' : ''}">${value}</span>
        </div>
      `;
    }

    // -------------------------------------------------------------------------
    // NEW (polish pass): Webhook receiver display — last 5 payloads
    // -------------------------------------------------------------------------
    function renderWebhookPanel() {
      const hooks = STATE.webhooks || [];
      const open = STATE.webhookOpen;
      return `
        <section class="card rounded-xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <button data-action="toggle-webhook" class="flex w-full items-center justify-between gap-3 p-4 text-left">
            <div class="flex items-center gap-3">
              <span class="text-violet-500">${icon('webhook', 'h-5 w-5')}</span>
              <div>
                <h2 class="text-base font-semibold">Webhook Receiver</h2>
                <p class="text-[11px] text-slate-500 dark:text-slate-400">Integration entry point — POST to <code class="font-mono text-violet-600 dark:text-violet-400">/api/webhook/lead</code> to ingest leads from n8n, Zapier, Gmail bridges.</p>
              </div>
            </div>
            <div class="flex items-center gap-3">
              <span class="inline-flex items-center rounded bg-violet-100 px-1.5 py-0.5 text-[10px] font-medium text-violet-700 dark:bg-violet-950/60 dark:text-violet-300">${hooks.length} received</span>
              <svg class="h-4 w-4 collapse-arrow ${open ? 'open' : ''} text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
            </div>
          </button>
          <div class="collapse-content ${open ? 'open' : ''}">
            <div class="border-t border-slate-200 p-4 dark:border-slate-800">
              <div class="mb-3 flex flex-wrap items-center gap-2">
                <button data-action="send-test-webhook" class="inline-flex items-center gap-1 rounded-md border border-violet-200 bg-violet-50 px-2.5 py-1 text-xs font-medium text-violet-700 hover:bg-violet-100 dark:border-violet-900 dark:bg-violet-950/40 dark:text-violet-300 dark:hover:bg-violet-950/60">
                  ${icon('bolt', 'h-3 w-3')}
                  Send test webhook
                </button>
                <code class="font-mono text-[10px] text-slate-500 dark:text-slate-400">curl -X POST ${window.location.origin}/api/webhook/lead -H "Content-Type: application/json" -d '{"name":"...","message":"..."}'</code>
              </div>
              ${hooks.length === 0 ? `
                <div class="rounded-lg border border-dashed border-slate-200 bg-slate-50/40 p-6 text-center dark:border-slate-700 dark:bg-slate-800/20">
                  <span class="text-violet-500 opacity-60">${icon('inbox_empty', 'h-7 w-7')}</span>
                  <p class="mt-1.5 text-sm font-medium text-slate-600 dark:text-slate-300">No webhooks received yet</p>
                  <p class="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">Click "Send test webhook" above to ingest a sample lead.</p>
                </div>
              ` : `
                <div class="space-y-2">
                  ${hooks.map(h => `
                    <div class="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs dark:border-slate-800 dark:bg-slate-800/40">
                      <div class="flex flex-wrap items-center gap-2">
                        <span class="inline-flex items-center gap-1 rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-medium text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">${escapeHtml(h.method || 'POST')}</span>
                        <code class="font-mono text-violet-700 dark:text-violet-300">${escapeHtml(h.path || '/api/webhook/lead')}</code>
                        <span class="ml-auto text-[10px] text-slate-500">${fmtRelative(h.received_at)}</span>
                      </div>
                      <div class="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-3">
                        <div><span class="text-[10px] uppercase tracking-wide text-slate-500">Name</span><div class="font-medium">${escapeHtml(h.payload?.name || '—')}</div></div>
                        <div><span class="text-[10px] uppercase tracking-wide text-slate-500">Source</span><div class="font-medium">${escapeHtml(h.payload?.source || '—')}</div></div>
                        <div><span class="text-[10px] uppercase tracking-wide text-slate-500">Result</span><div class="font-medium">${escapeHtml(h.result?.status || '—')} → #${h.result?.id || '?'}</div></div>
                      </div>
                      ${h.payload?.message ? `<div class="mt-2 text-[11px] italic text-slate-600 dark:text-slate-400">"${escapeHtml(h.payload.message.slice(0, 120))}${h.payload.message.length > 120 ? '…' : ''}"</div>` : ''}
                    </div>
                  `).join('')}
                </div>
              `}
            </div>
          </div>
        </section>
      `;
    }

    function renderFooter() {
      return `
        <footer class="mt-8 border-t border-slate-200 pt-6 text-center text-xs text-slate-500 dark:border-slate-800">
          <p><span class="font-medium text-slate-900 dark:text-slate-100">LeadMind MCP</span> · Free-tier stack: Groq Llama-3.3-70b + SQLite + Python MCP SDK · Built with caching, fallback &amp; demo-safe reliability engineering</p>
          <p class="mt-1 opacity-70">Connect from Claude Desktop to control this CRM conversationally — see <code class="rounded bg-slate-100 px-1 py-0.5 dark:bg-slate-800">leadmind-mcp/README.md</code></p>
        </footer>
      `;
    }

    // -------------------------------------------------------------------------
    // Slide-over drawer (lead detail) — verified & enhanced
    // -------------------------------------------------------------------------
    function renderDrawer() {
      const lead = STATE.selectedLead;
      const cfg = STATUS_CONFIG[lead.status] || STATUS_CONFIG.Warm;
      const detail = STATE.leadDetail;
      const nextAction = STATE.nextAction;
      // Look up the most recent classification event to surface its confidence + source
      let lastClassification = null;
      if (detail && detail.history) {
        for (let i = detail.history.length - 1; i >= 0; i--) {
          const h = detail.history[i];
          if (h.event_type === 'classified') { lastClassification = h; break; }
        }
      }
      const naSource = nextAction?.source;
      const naSourceBadge = naSource === 'groq'
        ? '<span class="ml-1 inline-flex items-center gap-1 rounded border border-amber-200 bg-amber-50 px-1 py-0 text-[9px] font-medium text-amber-700 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">via Groq</span>'
        : naSource === 'fallback'
          ? '<span class="ml-1 inline-flex items-center gap-1 rounded border border-emerald-200 bg-emerald-50 px-1 py-0 text-[9px] font-medium text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">via fallback</span>'
          : naSource
            ? `<span class="ml-1 inline-flex items-center gap-1 rounded border border-slate-200 bg-slate-50 px-1 py-0 text-[9px] font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400">via ${escapeHtml(naSource)}</span>`
            : '';
      return `
        <div class="fixed inset-0 z-50 flex justify-end">
          <div data-action="close-drawer" class="absolute inset-0 bg-black/30 modal-backdrop"></div>
          <div class="slide-over relative w-full max-w-[560px] overflow-y-auto bg-white shadow-xl modal-content dark:bg-slate-900">
            <div class="sticky top-0 border-b border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
              <div class="flex items-start justify-between gap-3 pr-6">
                <div class="min-w-0 flex-1">
                  <div class="text-lg font-semibold">${escapeHtml(lead.name)}</div>
                  <div class="flex flex-wrap items-center gap-2 pt-1 text-xs text-slate-500">
                    <span>${icon('mail', 'h-3 w-3 inline')} ${escapeHtml(lead.contact_info) || '—'}</span>
                    <span class="opacity-50">·</span>
                    <span>via ${escapeHtml(lead.source) || 'unknown'}</span>
                  </div>
                </div>
                <span class="inline-flex items-center gap-1.5 rounded-full border px-2 py-1 text-xs font-medium ${cfg.badge}">
                  <span class="h-1.5 w-1.5 rounded-full ${cfg.dot}"></span>${lead.status}
                </span>
              </div>
            </div>
            <div class="space-y-5 p-4 pb-6">
              <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div class="space-y-1.5">
                  <label class="text-[11px] font-medium uppercase tracking-wide text-slate-500">Update status</label>
                  <select data-action="change-status" class="h-9 w-full rounded-md border border-violet-300 bg-violet-100 px-2 text-xs font-semibold text-violet-800 hover:bg-violet-200 focus:bg-violet-200 dark:border-violet-700 dark:bg-violet-900/50 dark:text-violet-200 dark:hover:bg-violet-900/70">
                    ${['Hot', 'Warm', 'Cold', 'Converted', 'Lost'].map(s => `
                      <option value="${s}" ${s === lead.status ? 'selected' : ''}>${s}</option>
                    `).join('')}
                  </select>
                </div>
                <div class="space-y-1.5">
                  <label class="text-[11px] font-medium uppercase tracking-wide text-slate-500">AI next action</label>
                  <button data-action="next-action" data-id="${lead.id}" class="inline-flex h-9 w-full items-center justify-center gap-1.5 rounded-md border border-violet-300 bg-violet-100 text-xs font-semibold text-violet-800 hover:bg-violet-200 focus:bg-violet-200 dark:border-violet-700 dark:bg-violet-900/50 dark:text-violet-200 dark:hover:bg-violet-900/70 ${STATE.loadingAction ? 'opacity-50' : ''}">
                    ${STATE.loadingAction ? `<svg class="h-3.5 w-3.5 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>` : icon('sparkles', 'h-3.5 w-3.5')}
                    Suggest next action
                  </button>
                </div>
              </div>
              ${nextAction ? `
                <div class="rounded-lg border border-violet-200 bg-violet-50/50 p-3 dark:border-violet-900 dark:bg-violet-950/30">
                  <div class="mb-1.5 flex flex-wrap items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-violet-700 dark:text-violet-300">
                    ${icon('sparkles', 'h-3 w-3 inline')}
                    Recommended Next Action
                    ${naSourceBadge}
                  </div>
                  <p class="text-sm leading-relaxed">${escapeHtml(nextAction.suggestion || nextAction.recommendation || '—')}</p>
                </div>
              ` : ''}
              <div class="space-y-1.5">
                <div class="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-500">${icon('chat', 'h-3 w-3')} Original message</div>
                <div class="drawer-message rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-800/40">
                  <p class="text-sm">${escapeHtml(lead.message) || '—'}</p>
                </div>
              </div>
              <div class="grid grid-cols-2 gap-3 text-xs">
                <div class="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                  <div class="text-[10px] uppercase tracking-wide text-slate-500">Created</div>
                  <div class="mt-1 font-medium">${fmtDateTime(lead.created_at)}</div>
                  <div class="text-[11px] text-slate-500">${fmtRelative(lead.created_at)}</div>
                </div>
                <div class="rounded-lg border border-slate-200 p-3 dark:border-slate-800">
                  <div class="text-[10px] uppercase tracking-wide text-slate-500">Last contacted</div>
                  ${lead.last_contacted_at
                    ? `<div class="mt-1 font-medium">${fmtDateTime(lead.last_contacted_at)}</div><div class="text-[11px] text-slate-500">${fmtRelative(lead.last_contacted_at)}</div>`
                    : `<div class="mt-1 text-slate-400 dark:text-slate-500 italic">Never contacted</div>`
                  }
                </div>
              </div>
              <div class="space-y-2">
                <div class="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-slate-500">
                  ${icon('list', 'h-3 w-3')} Timeline ${detail ? `<span class="ml-1 text-[10px] opacity-60">(${detail.history.length} events)</span>` : ''}
                </div>
                ${STATE.loadingDetail ? `
                  <div class="flex items-center gap-2 p-4 text-xs text-slate-500">
                    <svg class="h-3 w-3 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
                    Loading timeline…
                  </div>
                ` : detail && detail.history.length > 0 ? `
                  <ol class="relative space-y-4 border-l border-slate-200 pl-4 dark:border-slate-800">
                    ${detail.history.map(h => {
                      const dotMap = { created: 'bg-violet-500', classified: 'bg-amber-500', status_change: 'bg-sky-500', contacted: 'bg-emerald-500', note: 'bg-zinc-400' };
                      const dot = dotMap[h.event_type] || 'bg-slate-400';
                      // P0-4: parse raw "Auto-classified as X (reason) [source=fallback] [score=3]"
                      // into a clean short reason + source badge + collapsible details.
                      const parsed = parseTimelineDescription(h.event_description);
                      const hasDetails = parsed.detail || parsed.score;
                      const detailId = 'tl-detail-' + h.id + '-' + Math.random().toString(36).slice(2, 8);
                      return `
                        <li class="relative">
                          <span class="absolute -left-[21px] top-1 h-2 w-2 rounded-full ring-2 ring-white dark:ring-slate-900 ${dot}"></span>
                          <div class="flex flex-wrap items-center gap-2">
                            <span class="inline-flex items-center rounded border px-1.5 py-0 text-[10px] font-medium uppercase tracking-wide">${escapeHtml(h.event_type.replace(/_/g, ' '))}</span>
                            <span class="text-[10px] text-slate-500">${fmtRelative(h.created_at)}</span>
                            ${parsed.source ? `<span class="inline-flex items-center gap-1 rounded border px-1 py-0 text-[9px] font-medium ${parsed.source === 'groq' ? 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300' : parsed.source === 'cache' ? 'border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-300' : 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300'}">via ${escapeHtml(parsed.source)}</span>` : ''}
                            ${parsed.score ? `<span class="inline-flex items-center rounded border border-slate-200 bg-slate-50 px-1 py-0 text-[9px] font-medium text-slate-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400">score: ${escapeHtml(parsed.score)}</span>` : ''}
                            ${hasDetails ? `<button data-action="toggle-timeline-details" data-target="${detailId}" class="inline-flex items-center gap-0.5 text-[10px] font-medium text-violet-600 hover:text-violet-700 dark:text-violet-400"><svg class="h-3 w-3 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>details</button>` : ''}
                          </div>
                          ${parsed.short ? `<p class="mt-1 text-xs leading-relaxed text-slate-700 dark:text-slate-300">${escapeHtml(parsed.short)}</p>` : ''}
                          ${hasDetails ? `<div id="${detailId}" class="timeline-details mt-1.5 rounded border border-slate-200 bg-slate-50 p-2 text-[11px] font-mono text-slate-600 dark:border-slate-700 dark:bg-slate-800/40 dark:text-slate-400">${parsed.detail ? `<div>${escapeHtml(parsed.detail)}</div>` : ''}${parsed.original && parsed.original !== parsed.short && !parsed.detail ? `<div class="opacity-70">${escapeHtml(parsed.original)}</div>` : ''}</div>` : ''}
                          ${h.old_value && h.new_value ? `
                            <div class="mt-1 flex items-center gap-1.5 text-[11px] text-slate-500">
                              <span class="rounded bg-slate-100 px-1 py-0.5 dark:bg-slate-800">${escapeHtml(h.old_value)}</span>
                              <svg class="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14 5l7 7m0 0l-7 7m7-7H3"/></svg>
                              <span class="rounded bg-slate-100 px-1 py-0.5 dark:bg-slate-800">${escapeHtml(h.new_value)}</span>
                            </div>
                          ` : ''}
                        </li>
                      `;
                    }).join('')}
                  </ol>
                ` : '<p class="text-xs text-slate-500">No history yet.</p>'}
              </div>
            </div>
          </div>
        </div>
      `;
    }

    function renderAddModal() {
      return `
        <div class="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div data-action="close-add" class="absolute inset-0 bg-black/40 modal-backdrop"></div>
          <div class="relative w-full max-w-[520px] rounded-lg bg-white shadow-xl modal-content dark:bg-slate-900">
            <div class="border-b border-slate-200 p-4 dark:border-slate-800">
              <div class="flex items-center gap-2 text-base font-semibold">${icon('plus', 'h-4 w-4')} Add New Lead</div>
              <p class="mt-1 text-xs text-slate-500">The message will be auto-classified by the AI pipeline (cache → Groq → fallback).</p>
            </div>
            <form data-action="submit-add" class="space-y-4 p-4">
              <div class="grid grid-cols-2 gap-3">
                <div class="space-y-1.5">
                  <label class="text-xs font-medium">Name <span class="text-red-500">*</span></label>
                  <input name="name" type="text" placeholder="Jane Doe" class="h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm dark:border-slate-800 dark:bg-slate-800" required />
                </div>
                <div class="space-y-1.5">
                  <label class="text-xs font-medium">Contact info</label>
                  <input name="contact_info" type="text" placeholder="jane@example.com" class="h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm dark:border-slate-800 dark:bg-slate-800" />
                </div>
              </div>
              <div class="space-y-1.5">
                <label class="text-xs font-medium">Source</label>
                <select name="source" class="h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm dark:border-slate-800 dark:bg-slate-800">
                  ${['LinkedIn', 'Webhook', 'Referral', 'Webinar', 'Cold Email', 'Demo Request'].map(s => `<option value="${s}">${s}</option>`).join('')}
                </select>
              </div>
              <div class="space-y-1.5">
                <label class="text-xs font-medium">Message <span class="text-red-500">*</span> <span class="ml-2 font-normal text-slate-500">(used for AI classification)</span></label>
                <textarea name="message" placeholder="e.g. We urgently need a CRM, budget approved, ready to sign this week." class="min-h-[100px] w-full rounded-md border border-slate-200 bg-white p-2 text-sm dark:border-slate-800 dark:bg-slate-800" required></textarea>
              </div>
              <div class="flex justify-end gap-2">
                <button type="button" data-action="close-add" class="rounded-md border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-800 dark:hover:bg-slate-700">Cancel</button>
                <button type="submit" class="inline-flex items-center gap-1.5 rounded-md bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700">
                  ${icon('sparkles', 'h-3.5 w-3.5')}
                  Add &amp; Classify
                </button>
              </div>
            </form>
          </div>
        </div>
      `;
    }

    // -------------------------------------------------------------------------
    // P0-4: Timeline description parser
    // Splits raw "Auto-classified as X (reasoning) [source=fallback] [score=3]"
    // into a clean short reason + metadata badges + full detail string.
    // -------------------------------------------------------------------------
    function parseTimelineDescription(desc) {
      if (!desc) return { short: '', source: null, score: null, detail: '' };
      const original = desc;
      let s = String(desc);
      // Extract [source=xxx] tag
      let source = null;
      const srcMatch = s.match(/\[source=([^\]]+)\]/i);
      if (srcMatch) { source = srcMatch[1]; s = s.replace(srcMatch[0], '').trim(); }
      // Extract [score=xxx] tag
      let score = null;
      const scoreMatch = s.match(/\[score=([^\]]+)\]/i);
      if (scoreMatch) { score = scoreMatch[1]; s = s.replace(scoreMatch[0], '').trim(); }
      // If it starts with "Auto-classified as X (reason)" keep just the leading
      // clause "Auto-classified as X" as the short text, and put the (reason)
      // into the detail section.
      let short = s;
      let detail = '';
      const autoMatch = s.match(/^(Auto-classified as \w+)\s*\((.*)\)\s*$/i);
      if (autoMatch) {
        short = autoMatch[1];
        detail = autoMatch[2];
      } else {
        // Fallback: if the text is very long, truncate at ~100 chars (word boundary)
        if (s.length > 100) {
          const slice = s.slice(0, 100);
          const lastSpace = slice.lastIndexOf(' ');
          short = (lastSpace > 60 ? slice.slice(0, lastSpace) : slice) + '…';
          detail = s;
        }
      }
      return { short, source, score, detail, original };
    }

    function initCharts() {
      if (typeof Chart === 'undefined') return;
      const isDark = STATE.theme === 'dark';
      const gridColor = isDark ? 'rgba(148,163,184,0.15)' : 'rgba(15,23,42,0.08)';
      const textColor = isDark ? '#94a3b8' : '#64748b';

      // ---- Donut: pipeline distribution ----
      const donutCanvas = document.getElementById('chart-donut');
      if (donutCanvas) {
        const byStatus = STATE.stats?.by_status || {};
        const order = ['Hot', 'Warm', 'Cold', 'Converted', 'Lost'];
        const labels = order.filter(s => (byStatus[s] || 0) > 0);
        const data = labels.map(s => byStatus[s]);
        const colors = labels.map(s => STATUS_CONFIG[s].chart);
        if (labels.length > 0) {
          __charts.donut = new Chart(donutCanvas, {
            type: 'doughnut',
            data: {
              labels,
              datasets: [{
                data,
                backgroundColor: colors,
                borderColor: isDark ? '#0f172a' : '#ffffff',
                borderWidth: 3,
                hoverOffset: 8,
              }],
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              cutout: '70%',
              plugins: {
                legend: { display: false },
                tooltip: {
                  callbacks: {
                    label: (ctx) => {
                      const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
                      const pct = total > 0 ? Math.round((ctx.parsed / total) * 100) : 0;
                      return `${ctx.label}: ${ctx.parsed} (${pct}%)`;
                    },
                  },
                },
              },
            },
          });
        }
      }

      // ---- Line: leads created over time (grouped by hour) ----
      const lineCanvas = document.getElementById('chart-line');
      if (lineCanvas) {
        // Group leads by hour bucket derived from created_at ("YYYY-MM-DD HH:MM:SS")
        const buckets = {};
        for (const l of STATE.leads) {
          if (!l.created_at) continue;
          const ts = String(l.created_at).replace(' ', 'T');
          const d = new Date(ts.length === 19 ? ts + 'Z' : ts);
          if (isNaN(d.getTime())) continue;
          const key = d.getFullYear() + '-' +
                      String(d.getMonth() + 1).padStart(2, '0') + '-' +
                      String(d.getDate()).padStart(2, '0') + ' ' +
                      String(d.getHours()).padStart(2, '0') + ':00';
          buckets[key] = (buckets[key] || 0) + 1;
        }
        const sortedKeys = Object.keys(buckets).sort();
        const labels = sortedKeys.length > 0 ? sortedKeys : ['(no data)'];
        const data = sortedKeys.length > 0 ? sortedKeys.map(k => buckets[k]) : [0];

        __charts.line = new Chart(lineCanvas, {
          type: 'line',
          data: {
            labels,
            datasets: [{
              label: 'Leads created',
              data,
              borderColor: '#8b5cf6',
              backgroundColor: (ctx) => {
                const c = ctx.chart.ctx;
                const g = c.createLinearGradient(0, 0, 0, 180);
                g.addColorStop(0, 'rgba(139,92,246,0.30)');
                g.addColorStop(1, 'rgba(139,92,246,0.00)');
                return g;
              },
              borderWidth: 2,
              fill: true,
              tension: 0.35,
              pointBackgroundColor: '#8b5cf6',
              pointBorderColor: isDark ? '#0f172a' : '#ffffff',
              pointBorderWidth: 2,
              pointRadius: 4,
              pointHoverRadius: 6,
            }],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
              legend: { display: false },
              tooltip: {
                callbacks: {
                  title: (items) => items[0].label,
                  label: (ctx) => `${ctx.parsed.y} lead${ctx.parsed.y === 1 ? '' : 's'}`,
                },
              },
            },
            scales: {
              x: {
                grid: { display: false },
                ticks: {
                  color: textColor,
                  font: { size: 9 },
                  maxRotation: 0,
                  callback: function(val) {
                    const lbl = this.getLabelForValue(val);
                    return lbl.length > 10 ? lbl.slice(11) : lbl;
                  },
                },
              },
              y: {
                beginAtZero: true,
                grid: { color: gridColor, drawBorder: false },
                ticks: { color: textColor, font: { size: 9 }, precision: 0 },
              },
            },
          },
        });
      }
    }

    // -------------------------------------------------------------------------
    // Event handlers
    // -------------------------------------------------------------------------
    function attachHandlers() {
      // Theme toggle
      document.querySelectorAll('[data-action="toggle-theme"]').forEach(el => {
        el.addEventListener('click', toggleTheme);
      });
      // How it works toggle
      document.querySelectorAll('[data-action="toggle-howitworks"]').forEach(el => {
        el.addEventListener('click', () => { STATE.howItWorksOpen = !STATE.howItWorksOpen; render(); });
      });
      // Audit panel toggle (polish pass)
      document.querySelectorAll('[data-action="toggle-audit"]').forEach(el => {
        el.addEventListener('click', () => { STATE.auditOpen = !STATE.auditOpen; render(); });
      });
      // Webhook panel toggle (polish pass)
      document.querySelectorAll('[data-action="toggle-webhook"]').forEach(el => {
        el.addEventListener('click', () => { STATE.webhookOpen = !STATE.webhookOpen; render(); });
      });
      // Timeline details toggle (P0-4) — expand/collapse the technical details of a timeline entry
      document.querySelectorAll('[data-action="toggle-timeline-details"]').forEach(el => {
        el.addEventListener('click', () => {
          const target = document.getElementById(el.dataset.target);
          if (!target) return;
          target.classList.toggle('open');
          const svg = el.querySelector('svg');
          if (svg) svg.style.transform = target.classList.contains('open') ? 'rotate(180deg)' : '';
        });
      });
      // Send test webhook (polish pass)
      document.querySelectorAll('[data-action="send-test-webhook"]').forEach(el => {
        el.addEventListener('click', async () => {
          const samples = [
            { name: 'Webhook Test Lead', message: 'We urgently need a CRM, budget approved, ready to sign this week.', source: 'Webhook' },
            { name: 'Webhook Curious', message: 'Just researching options for next year, not ready to buy.', source: 'Webhook' },
            { name: 'Webhook Eval', message: 'Interested but need to compare with two other vendors first.', source: 'Webhook' },
          ];
          const p = samples[Math.floor(Math.random() * samples.length)];
          try {
            const r = await apiWebhookSend(p);
            toast(`Webhook received: ${r.name} → ${r.status}`, 'success');
            await loadAll(true);
          } catch (e) { toast(e.message, 'error'); }
        });
      });
      // CSV export (polish pass)
      document.querySelectorAll('[data-action="export-csv"]').forEach(el => {
        el.addEventListener('click', () => {
          const filtered = STATE.leads.filter(l => {
            if (STATE.filter !== 'all' && l.status !== STATE.filter) return false;
            if (STATE.search.trim()) {
              const q = STATE.search.toLowerCase();
              return (l.name || '').toLowerCase().includes(q) ||
                     (l.contact_info || '').toLowerCase().includes(q) ||
                     (l.message || '').toLowerCase().includes(q) ||
                     (l.source || '').toLowerCase().includes(q);
            }
            return true;
          });
          const escape = (v) => {
            const s = String(v == null ? '' : v).replace(/"/g, '""');
            return /[",\n\r]/.test(s) ? `"${s}"` : s;
          };
          const headers = ['id', 'name', 'contact_info', 'message', 'status', 'source', 'created_at', 'last_contacted_at'];
          const rows = [headers.join(',')].concat(
            filtered.map(l => headers.map(h => escape(l[h])).join(','))
          );
          const csv = rows.join('\r\n');
          const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `leadmind-leads-${new Date().toISOString().slice(0,10)}.csv`;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
          toast(`Exported ${filtered.length} leads to CSV`, 'success');
        });
      });
      // Select-all checkbox (polish pass)
      document.querySelectorAll('[data-action="select-all"]').forEach(el => {
        el.addEventListener('change', (e) => {
          e.stopPropagation();
          const filtered = STATE.leads.filter(l => {
            if (STATE.filter !== 'all' && l.status !== STATE.filter) return false;
            if (STATE.search.trim()) {
              const q = STATE.search.toLowerCase();
              return (l.name || '').toLowerCase().includes(q) ||
                     (l.contact_info || '').toLowerCase().includes(q) ||
                     (l.message || '').toLowerCase().includes(q) ||
                     (l.source || '').toLowerCase().includes(q);
            }
            return true;
          });
          if (e.target.checked) {
            filtered.forEach(l => STATE.selectedLeadIds.add(l.id));
          } else {
            filtered.forEach(l => STATE.selectedLeadIds.delete(l.id));
          }
          render();
        });
      });
      // Per-row checkbox (polish pass)
      document.querySelectorAll('[data-action="select-lead-checkbox"]').forEach(el => {
        el.addEventListener('change', (e) => {
          e.stopPropagation();
          const id = parseInt(el.dataset.id, 10);
          if (e.target.checked) STATE.selectedLeadIds.add(id);
          else STATE.selectedLeadIds.delete(id);
          render();
        });
      });
      // Clear selection (polish pass)
      document.querySelectorAll('[data-action="clear-selection"]').forEach(el => {
        el.addEventListener('click', () => {
          STATE.selectedLeadIds.clear();
          render();
        });
      });
      // Bulk classify (polish pass) — re-classify each selected lead's message
      document.querySelectorAll('[data-action="bulk-classify"]').forEach(el => {
        el.addEventListener('click', async () => {
          if (STATE.selectedLeadIds.size === 0) return;
          STATE.bulkClassifying = true;
          render();
          const ids = Array.from(STATE.selectedLeadIds);
          let ok = 0, fail = 0;
          for (const id of ids) {
            const lead = STATE.leads.find(l => l.id === id);
            if (!lead) { fail++; continue; }
            try {
              // Re-classify via the same /api/classify endpoint that the
              // bulk_import_leads tool uses internally. Then update the
              // lead's status via PATCH so the change persists + is audited.
              const r = await apiClassify(lead.message);
              await apiUpdateStat(id, r.status);
              ok++;
            } catch (e) {
              fail++;
            }
          }
          STATE.bulkClassifying = false;
          STATE.selectedLeadIds.clear();
          toast(`Bulk-classified ${ok} lead${ok === 1 ? '' : 's'}${fail ? `, ${fail} failed` : ''}`, ok > 0 ? 'success' : 'error');
          await loadAll(true);
        });
      });
      // Refresh
      document.querySelectorAll('[data-action="refresh"]').forEach(el => {
        el.addEventListener('click', () => loadAll());
      });
      // Reset demo
      document.querySelectorAll('[data-action="reset-demo"]').forEach(el => {
        el.addEventListener('click', async () => {
          try {
            await apiResetDemo();
            toast('Demo database reset to seed data.', 'success');
            STATE.selectedLead = null;
            STATE.selectedLeadIds.clear();
            await loadAll(true);
          } catch (e) { toast(e.message, 'error'); }
        });
      });
      // Open add modal
      document.querySelectorAll('[data-action="open-add"]').forEach(el => {
        el.addEventListener('click', () => { STATE.addModalOpen = true; render(); });
      });
      // Close add modal
      document.querySelectorAll('[data-action="close-add"]').forEach(el => {
        el.addEventListener('click', () => { STATE.addModalOpen = false; render(); });
      });
      // Submit add
      document.querySelectorAll('[data-action="submit-add"]').forEach(el => {
        el.addEventListener('submit', async (e) => {
          e.preventDefault();
          const fd = new FormData(e.target);
          try {
            const r = await apiAddLead({
              name: fd.get('name'),
              contact_info: fd.get('contact_info'),
              message: fd.get('message'),
              source: fd.get('source'),
            });
            toast(`Added ${r.name} → classified as ${r.status}`, 'success');
            STATE.addModalOpen = false;
            await loadAll(true);
          } catch (err) { toast(err.message, 'error'); }
        });
      });
      // Filter tabs
      document.querySelectorAll('[data-action="filter"]').forEach(el => {
        el.addEventListener('click', () => { STATE.filter = el.dataset.filter; render(); });
      });
      // Search
      const searchEl = document.querySelector('[data-action="search"]');
      if (searchEl) {
        searchEl.addEventListener('input', (e) => { STATE.search = e.target.value; render(); });
        const v = STATE.search;
        if (v) {
          searchEl.focus();
          searchEl.setSelectionRange(v.length, v.length);
        }
      }
      // Try it live — input (no re-render on every keystroke; preserve cursor)
      const classifyInputEl = document.querySelector('[data-action="classify-input"]');
      if (classifyInputEl) {
        classifyInputEl.addEventListener('input', (e) => { STATE.classifyInput = e.target.value; });
        // Cmd/Ctrl+Enter shortcut (polish pass)
        classifyInputEl.addEventListener('keydown', (e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
            e.preventDefault();
            const runBtn = document.querySelector('[data-action="classify-run"]');
            if (runBtn) runBtn.click();
          }
        });
      }
      // Try it live — sample chips
      document.querySelectorAll('[data-action="classify-sample"]').forEach(el => {
        el.addEventListener('click', () => {
          STATE.classifyInput = el.dataset.text;
          render();
          const ta = document.querySelector('[data-action="classify-input"]');
          if (ta) ta.focus();
        });
      });
      // Try it live — run
      document.querySelectorAll('[data-action="classify-run"]').forEach(el => {
        el.addEventListener('click', async () => {
          const text = (STATE.classifyInput || '').trim();
          if (!text) { toast('Type a lead message first.', 'error'); return; }
          STATE.classifying = true;
          STATE.classifyResult = null;
          STATE.lastClassifyLatencyMs = null;
          render();
          const t0 = performance.now();
          try {
            const r = await apiClassify(text);
            STATE.classifyResult = r;
            const dtMs = Math.round(performance.now() - t0);
            STATE.lastClassifyLatencyMs = dtMs;
            const dt = (dtMs / 1000).toFixed(2);
            const cacheNote = r.source === 'cache' ? ' (cache hit)' : '';
            toast(`Classified as ${r.status} in ${dt}s via ${r.source}${cacheNote}`, 'success');
          } catch (e) {
            toast(e.message, 'error');
          } finally {
            STATE.classifying = false;
            render();
          }
        });
      });
      // Select lead (row click — but not when clicking the checkbox)
      document.querySelectorAll('[data-action="select-lead"]').forEach(el => {
        el.addEventListener('click', async (e) => {
          // If the click target was inside the checkbox cell, ignore — the
          // checkbox's own change handler will manage selection.
          if (e.target.closest('[data-action="select-lead-checkbox"]')) return;
          const id = parseInt(el.dataset.id, 10);
          const lead = STATE.leads.find(l => l.id === id);
          if (!lead) return;
          STATE.selectedLead = lead;
          STATE.leadDetail = null;
          STATE.nextAction = null;
          STATE.loadingDetail = true;
          render();
          try {
            const d = await apiGetLead(id);
            STATE.leadDetail = d;
          } catch (e) { toast(e.message, 'error'); }
          finally { STATE.loadingDetail = false; render(); }
        });
      });
      // Close drawer
      document.querySelectorAll('[data-action="close-drawer"]').forEach(el => {
        el.addEventListener('click', () => { STATE.selectedLead = null; render(); });
      });
      // Change status
      document.querySelectorAll('[data-action="change-status"]').forEach(el => {
        el.addEventListener('change', async (e) => {
          const newStatus = e.target.value;
          const id = STATE.selectedLead.id;
          try {
            await apiUpdateStat(id, newStatus);
            toast(`Marked ${STATE.selectedLead.name} as ${newStatus}`, 'success');
            STATE.selectedLead = { ...STATE.selectedLead, status: newStatus };
            await loadAll(true);
            STATE.loadingDetail = true; render();
            try { STATE.leadDetail = await apiGetLead(id); } finally { STATE.loadingDetail = false; render(); }
          } catch (err) { toast(err.message, 'error'); }
        });
      });
      // Next action
      document.querySelectorAll('[data-action="next-action"]').forEach(el => {
        el.addEventListener('click', async () => {
          const id = parseInt(el.dataset.id, 10);
          STATE.loadingAction = true; render();
          try { STATE.nextAction = await apiNextAction(id); }
          catch (e) { toast(e.message, 'error'); }
          finally { STATE.loadingAction = false; render(); }
        });
      });
      // ESC closes drawer/modal
      document.onkeydown = (e) => {
        if (e.key === 'Escape') {
          if (STATE.addModalOpen) { STATE.addModalOpen = false; render(); }
          else if (STATE.selectedLead) { STATE.selectedLead = null; render(); }
        }
      };
    }

    // -------------------------------------------------------------------------
    // Init
    // -------------------------------------------------------------------------
    loadAll();
    // Poll for live updates every 15s
    setInterval(() => loadAll(true), 15000);
  </script>
</body>
</html>
"""




# ---------------------------------------------------------------------------
# HTML dashboard (server-rendered, calls /api/* via JS)
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def dashboard_html() -> str:
    """Serve the single-page dashboard. All data is fetched client-side via /api/*."""
    import os
    # DEBUG: log what we're returning
    print(f"[DEBUG dashboard_html] DASHBOARD_HTML length={len(DASHBOARD_HTML)} has_toggle_theme={DASHBOARD_HTML.count('toggle-theme')} file_mtime={os.path.getmtime(__file__)}", flush=True)
    return DASHBOARD_HTML


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "leadmind-dashboard",
        "demo_mode": DEMO_MODE,
        "demo_reset_interval_sec": DEMO_RESET_INTERVAL_SEC,
        "auth_enabled": LEADMIND_AUTH_ENABLED,
        "groq_key_configured": bool(os.getenv("GROQ_API_KEY")),
    }


@app.get("/api/health")
def api_health() -> Dict[str, Any]:
    return health()


@app.get("/api/stats")
def api_stats() -> Dict[str, Any]:
    """Aggregate pipeline stats + Groq usage monitoring."""
    return get_lead_stats()


@app.get("/api/leads")
def api_list_leads(
    status: Optional[str] = Query(default=None, description="Filter by Hot/Warm/Cold/Converted/Lost"),
) -> Dict[str, Any]:
    leads = fetch_leads(status=status if status else None)
    return {"count": len(leads), "filter": status or "all", "leads": leads}


@app.get("/api/leads/{lead_id}")
def api_get_lead(lead_id: int) -> Dict[str, Any]:
    lead = fetch_lead(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")
    history = fetch_lead_history(lead_id)
    return {"lead": lead, "history": history}


@app.post("/api/leads")
async def api_create_lead(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> Dict[str, Any]:
    _check_auth(x_api_key)
    payload = await request.json()
    name = payload.get("name")
    contact_info = payload.get("contact_info", "")
    message = payload.get("message", "")
    source = payload.get("source", "Web Form")
    if not name or not message:
        raise HTTPException(status_code=400, detail="Fields 'name' and 'message' are required.")
    return add_lead(name=name, contact_info=contact_info, message=message, source=source)


@app.patch("/api/leads/{lead_id}/status")
async def api_patch_status(
    lead_id: int,
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> Dict[str, Any]:
    _check_auth(x_api_key)
    payload = await request.json()
    new_status = payload.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="Field 'status' is required.")
    return update_lead_status(id=lead_id, status=new_status)


@app.get("/api/leads/{lead_id}/next-action")
def api_next_action(lead_id: int) -> Dict[str, Any]:
    return suggest_next_action(id=lead_id)


@app.post("/api/classify")
async def api_classify(request: Request) -> Dict[str, Any]:
    """Classify a message without saving it to the DB. Useful for the demo 'try it' panel."""
    _check_auth(None)
    payload = await request.json()
    text = payload.get("text", "")
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="Field 'text' is required.")
    return classify_lead(text)


@app.post("/api/leads/bulk-csv", response_class=PlainTextResponse)
async def api_bulk_csv(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> str:
    _check_auth(x_api_key)
    csv_data = (await request.body()).decode("utf-8")
    result = bulk_import_leads(csv_data=csv_data)
    return (
        f"Imported {result['imported']} leads, {len(result['errors'])} errors.\n"
        + "\n".join(result["errors"])
    )


@app.get("/api/audit")
def api_audit(limit: int = Query(default=50, ge=1, le=500)) -> Dict[str, Any]:
    return {"count": limit, "entries": fetch_audit_summary(limit=limit)}


# ---------------------------------------------------------------------------
# Webhook receiver (polish pass) — in-memory ring buffer of recent payloads
# ---------------------------------------------------------------------------
# We keep the last 5 webhook payloads in-process so the dashboard can render
# them. This is purely an observability surface — the leads themselves are
# persisted to SQLite via add_lead(), same as the MCP /api/leads endpoint.
from collections import deque as _deque  # noqa: E402
import threading as _threading  # noqa: E402
import time as _time  # noqa: E402

_WEBHOOK_LOG: "_deque[Dict[str, Any]]" = _deque(maxlen=5)
_WEBHOOK_LOCK = _threading.Lock()


@app.post("/api/webhook/lead")
async def api_webhook_lead(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> Dict[str, Any]:
    """Accept a single lead as JSON. Same as POST /api/leads but also records
    the payload in an in-memory ring buffer so the dashboard's "Webhook
    Receiver" panel can display recent activity."""
    _check_auth(x_api_key)
    payload = await request.json()
    name = payload.get("name")
    contact_info = payload.get("contact_info", "")
    message = payload.get("message", "")
    source = payload.get("source", "webhook")
    if not name or not message:
        raise HTTPException(status_code=400, detail="Fields 'name' and 'message' are required.")
    result = add_lead(name=name, contact_info=contact_info, message=message, source=source)
    # Record this webhook for the dashboard's Webhook Receiver panel.
    entry = {
        "received_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
        "method": "POST",
        "path": "/api/webhook/lead",
        "payload": {"name": name, "contact_info": contact_info, "message": message, "source": source},
        "result": result,
    }
    with _WEBHOOK_LOCK:
        _WEBHOOK_LOG.append(entry)
    return result


@app.get("/api/webhooks/recent")
def api_webhooks_recent() -> Dict[str, Any]:
    """Return the last 5 webhook payloads received (for the dashboard panel)."""
    with _WEBHOOK_LOCK:
        payloads = list(_WEBHOOK_LOG)
    # Return most-recent-first for display.
    payloads.reverse()
    return {"count": len(payloads), "payloads": payloads}


@app.get("/api/dashboard")
def api_dashboard() -> Dict[str, Any]:
    """Composite endpoint: stats + recent leads + audit in one call (used by the dashboard initial load)."""
    stats = fetch_stats()
    recent = fetch_recent_leads(limit=10)
    usage = get_usage_snapshot()
    audit = fetch_audit_summary(limit=30)
    return {
        "stats": stats,
        "recent_leads": recent,
        "groq_usage": usage,
        "audit": audit,
    }


@app.post("/api/demo/reset")
def api_demo_reset(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> Dict[str, Any]:
    _check_auth(x_api_key)
    result = seed_database(force=True)
    return {"reset": result, "message": "Database reset to seed data."}


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")



