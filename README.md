
# 🧠 LeadMind MCP — AI Lead Management CRM

<div align="center">

![Version](https://img.shields.io/badge/version-1.0.0-violet?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-emerald?style=flat-square)
![Python](https://img.shields.io/badge/python-3.12-blue?style=flat-square)
![Next.js](https://img.shields.io/badge/next.js-16-black?style=flat-square)
![Groq](https://img.shields.io/badge/groq-llama_3.3_70b-orange?style=flat-square)
![MCP](https://img.shields.io/badge/MCP-1.2-fuchsia?style=flat-square)

**Conversational AI lead management powered by the Model Context Protocol.**
Free-tier only — Groq LLM + SQLite. Zero paid APIs.

[🌐 Live Dashboard](https://leadmind-frontend.onrender.com) · [🐍 Backend API](https://leadmind-mcp-1.onrender.com) · [📖 MCP Docs](https://modelcontextprotocol.io) · [📧 Claude Desktop Config](#-claude-desktop-integration)

</div>

---

## ✨ Live Demo

> Try it right now — no login required. Dashboard resets every 4 hours.

| | |
|---|---|
| **Frontend Dashboard** | [https://leadmind-frontend.onrender.com](https://leadmind-frontend.onrender.com) |
| **Backend REST API** | [https://leadmind-mcp-1.onrender.com](https://leadmind-mcp-1.onrender.com) |
| **API Health Check** | [https://leadmind-mcp-1.onrender.com/health](https://leadmind-mcp-1.onrender.com/health) |
| **API Stats** | [https://leadmind-mcp-1.onrender.com/stats](https://leadmind-mcp-1.onrender.com/stats) |

---

## 🎯 What is LeadMind?

LeadMind MCP is a complete AI-powered CRM that:

- **Auto-classifies leads** as Hot / Warm / Cold using Groq's Llama-3.3-70b
- **Suggests next actions** for each lead (AI-powered coaching)
- **Tracks full history** — every status change, classification, and note is audited
- **Works with Claude Desktop** via the Model Context Protocol — manage leads conversationally
- **Runs on free-tier everything** — Groq free API + SQLite + Render free hosting

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────┐
│                  Claude Desktop                   │
│              (MCP Client — stdio)                 │
└──────────────────────┬──────────────────────────┘
                       │ MCP Protocol (stdio)
                       ▼
┌─────────────────────────────────────────────────┐
│            leadmind-mcp/mcp_server.py             │
│         MCP Server — 8 Tools + 3 Resources       │
│                                                   │
│  ┌─────────┐  ┌──────────┐  ┌─────────────────┐ │
│  │ Groq    │  │  Fallback│  │  Cache (5 min) │ │
│  │ Llama   │→ │  Rules   │→ │  TTL + SQLite  │ │
│  │ 70b     │  │  Engine  │  │  persistent    │ │
│  └─────────┘  └──────────┘  └─────────────────┘ │
│                       │                           │
│                       ▼                           │
│              ┌─────────────────┐                  │
│              │  SQLite (WAL)   │                  │
│              │  leadmind.db    │                  │
│              └────────┬────────┘                  │
└───────────────────────┼──────────────────────────┘
                        │
          ┌─────────────┼─────────────┐
          │             │             │
          ▼             ▼             ▼
   ┌────────────┐ ┌──────────┐ ┌──────────────┐
   │  MCP CLI   │ │ FastAPI  │ │  Next.js     │
   │  (Claude)  │ │ REST API │ │  Dashboard   │
   │  stdio     │ │ :8000    │ │  (Render)    │
   └────────────┘ └──────────┘ └──────────────┘
```

---

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Groq API key (free at [console.groq.com](https://console.groq.com/keys)) — optional, fallback works without it

### 1. Clone & Install

```bash
git clone https://github.com/mansisonani07/leadmind-mcp.git
cd leadmind-mcp
pip install -r requirements.txt
```

### 2. Run the MCP Server (Claude Desktop)

```bash
python mcp_server.py
```

### 3. Run the REST API

```bash
python api_server.py          # http://localhost:8000
```

### 4. Run the Web Dashboard

```bash
python web_dashboard.py       # http://localhost:8000 (HTML + API combined)
```

### 5. Run the Next.js Frontend

```bash
cd ..
npm install
LEADMIND_BACKEND_URL=http://localhost:8000 npm run dev
```

---

## 🤖 Claude Desktop Integration

Add this to your Claude Desktop config file:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "leadmind": {
      "command": "python",
      "args": ["/path/to/leadmind-mcp/mcp_server.py"],
      "env": {
        "GROQ_API_KEY": "gsk_your_key_here"
      }
    }
  }
}
```

Then ask Claude things like:
- *"Show me all hot leads"*
- *"Add a new lead: Sarah Chen, sarah@acme.com, interested in enterprise plan"*
- *"What should I do next with lead #5?"*
- *"Classify this: We need a CRM solution, budget approved, looking to sign next week"*

---

## 🛠 MCP Tools Exposed

| Tool | Description |
|------|-------------|
| `get_leads` | List leads, filter by status |
| `classify_lead` | AI classification — Hot/Warm/Cold with reasoning |
| `add_lead` | Add a lead + auto-classify on insert |
| `update_lead_status` | Manual status override + history log |
| `get_lead_stats` | Pipeline aggregate statistics |
| `get_lead_history` | Full event timeline per lead |
| `suggest_next_action` | AI-recommended next step for a lead |
| `bulk_import_leads` | CSV parse + batch classify |

### MCP Resources
| URI | Description |
|-----|-------------|
| `leads://dashboard` | Live pipeline snapshot |
| `audit://recent` | Recent tool-call audit log |

### MCP Prompts
| Name | Description |
|------|-------------|
| `weekly_lead_review` | Structured weekly summary |

---

## 📡 REST API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check + service info |
| `GET` | `/stats` | Pipeline stats + Groq usage |
| `GET` | `/leads?status=Hot` | List leads (optional status filter) |
| `GET` | `/leads/{id}` | Single lead + history timeline |
| `POST` | `/leads` | Add a lead (auto-classifies) |
| `PATCH` | `/leads/{id}/status` | Update lead status |
| `GET` | `/leads/{id}/next-action` | AI next-action suggestion |
| `POST` | `/leads/bulk-csv` | Bulk import from CSV |
| `GET` | `/audit?limit=50` | Recent tool-call audit log |
| `GET` | `/dashboard` | Full dashboard snapshot |
| `POST` | `/demo/reset` | Reset database to seed data |

**Try it:**
```bash
curl https://leadmind-mcp-1.onrender.com/health
curl https://leadmind-mcp-1.onrender.com/leads?status=Hot
curl https://leadmind-mcp-1.onrender.com/stats
```

---

## ⚡ Reliability Engineering

LeadMind is built with production-grade resilience:

| Feature | Description |
|---------|-------------|
| 🔄 **Three-tier classification** | Cache → Groq LLM → Rule-based fallback |
| 📦 **TTL Cache** | 5-minute cache avoids redundant Groq calls |
| 🛡️ **Rate-limit handler** | Graceful degradation on Groq 429 errors |
| 🔁 **Auto-restart** | Dashboard auto-restarts Python if it crashes |
| 🗄️ **SQLite WAL mode** | Concurrent reads + atomic writes |
| 🔄 **Demo auto-reset** | Fresh data every 4 hours (configurable) |
| 📊 **Audit logging** | Every tool call tracked with duration |

---

## 🎨 Dashboard Features

- **6 KPI cards** — Total leads, Hot leads, Conversion rate, Avg response, Groq calls, Sources
- **Pipeline distribution** — Visual bar chart by status
- **Source breakdown** — Leads by acquisition channel
- **Full leads table** — Search, filter by status, sort
- **Lead detail drawer** — Status update, AI next action, message, timeline
- **Add lead modal** — Auto-classifies with AI on submit
- **Audit log** — Every tool call with Groq/fallback/cache flags
- **MCP primitives panel** — Shows all exposed tools, resources, and prompts
- **Dark mode** — Toggle between light and dark themes

---

## 🔑 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GROQ_API_KEY` | — | Free Groq API key |
| `DEMO_MODE` | `true` | Auto-reset DB to seed data |
| `DEMO_RESET_INTERVAL_SEC` | `14400` | Reset interval (4 hours) |
| `LEADMIND_AUTH_ENABLED` | `false` | Enable API key auth |
| `LEADMIND_API_KEY` | — | API secret key when auth enabled |
| `PORT` | `8000` | Backend listen port |
| `NEXT_PUBLIC_LEADMIND_BACKEND_URL` | — | Backend URL for Next.js frontend |

---

## 📂 Project Structure

```
leadmind-mcp/
├── mcp_server.py          # MCP server (stdio) — used by Claude Desktop
├── api_server.py          # REST API server — used by Next.js frontend
├── web_dashboard.py       # Self-contained HTML dashboard + API
├── tools.py               # MCP tool implementations
├── db.py                  # SQLite database layer
├── groq_classifier.py     # Groq LLM classification + caching
├── fallback_classifier.py # Rule-based fallback classifier
├── seed_data.py           # Demo seed data (22 leads)
├── config.py              # Configuration from env vars
├── cache.py               # TTL cache implementation
├── webhook_receiver.py    # n8n / Gmail webhook receiver
├── requirements.txt        # Python dependencies
└── claude_desktop_config.example.json

src/                        # Next.js frontend (React + TypeScript)
├── app/
│   ├── page.tsx            # Dashboard entry point
│   ├── api/leadmind/[...path]/route.ts  # API proxy
│   └── layout.tsx          # Root layout with fonts + toasters
├── components/leadmind/
│   ├── DashboardPage.tsx   # Main dashboard orchestrator
│   ├── Header.tsx          # App header with branding
│   ├── StatsGrid.tsx       # KPI cards + charts
│   ├── LeadsTable.tsx      # Searchable leads table
│   ├── LeadDetailDrawer.tsx # Slide-out lead detail
│   ├── AddLeadDialog.tsx   # Add lead modal
│   ├── AuditPanel.tsx      # Tool call audit log
│   └── McpPrimitivesPanel.tsx # MCP tools/resources display
├── lib/
│   ├── leadmind-api.ts     # API client (fetch wrapper)
│   └── leadmind-ui.ts      # Status colors, formatters
└── components/ui/          # shadcn/ui components
```

---

## 🚢 Deployment

### Render (Free Tier)

**Backend:** `render.com` → New Web Service
- Build: `pip install -r requirements.txt`
- Start: `python api_server.py`
- Set `GROQ_API_KEY` env var

**Frontend:** `render.com` → New Web Service
- Build: `npm install && npm run build`
- Start: `next start -p $PORT`
- Set `NEXT_PUBLIC_LEADMIND_BACKEND_URL=https://your-backend.onrender.com`

---

## 📄 License

MIT License — free for personal and commercial use.

---

## 🙏 Credits

- [Groq](https://groq.com) — Free LLM inference (Llama-3.3-70b)
- [Model Context Protocol](https://modelcontextprotocol.io) by Anthropic
- [FastAPI](https://fastapi.tiangolo.com) — Python web framework
- [Next.js](https://nextjs.org) — React framework
- [shadcn/ui](https://ui.shadcn.com) — UI component library

---

<div align="center">

**Built with ❤️ by [mansisonani07](https://github.com/mansisonani07)**

⭐ If you find this useful, give it a star!

</div>
```
