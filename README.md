# LeadMind MCP

> An MCP server that turns a CRM into a conversation — reads, scores, and prioritizes every lead the instant it arrives, then exposes the entire pipeline to any MCP client (like Claude Desktop) through natural language.

| What | Where | Status |
| --- | --- | --- |
| Live Dashboard | https://leadmind-mcp.space-z.ai | Live |
| Source Code | [GITHUB_URL] | Public |
| MCP Server | stdio/SSE via Claude Desktop | Healthy |
| License | MIT | — |

---

Picture a five-person sales team at a Series B SaaS company. Their leads arrive from three places: a Gmail inbox, a Stripe webhook, and a "Contact Us" form on the marketing site. Each lead looks identical at first glance — a name, an email, a message — and there are forty of them stacked up by lunchtime. The SDR on duty opens them one at a time, reading every message in full, mentally scoring urgency, and dropping the result into a spreadsheet. By the time she reaches lead number thirty, lead number three — the one from a Fortune 500 CTO asking about enterprise pricing — has gone cold. Nobody replied for six hours. The deal walked.

That pattern repeats itself in every sales org small enough to lack a dedicated RevOps team. Leads are not the problem; triage is. The information is already there, but it arrives faster than a human can thoughtfully sort it, and the cost of a slow reply compounds hour by hour. The fix is not another dashboard — dashboards only show you the fire after it has spread. The fix is a system that reads, classifies, and prioritizes every lead the instant it arrives, and that lets the human operator act on it through whatever interface they already live in.

LeadMind does exactly that, and it goes one step further: it exposes the entire capability set — classification, retrieval, status mutation, AI-suggested next actions, audit history — as a Model Context Protocol server. Plug it into Claude Desktop and you can say *"show me every hot lead from yesterday that hasn't been contacted yet"* or *"what should I do next on the Acme lead?"* and get a structured, sourced answer back. It is a CRM you can talk to, not just click through.

<details>
<summary><strong>Table of Contents</strong></summary>

- [What This Demonstrates](#what-this-demonstrates)
- [Screenshots](#screenshots)
- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Setup / Run Locally](#setup--run-locally)
- [Connect to Claude Desktop](#connect-to-claude-desktop)
- [License](#license)

</details>

---

## What This Demonstrates

This is not a wrapper around an existing CRM API. It is a from-scratch MCP server built to demonstrate what a production-grade MCP deployment actually looks like. A recruiter or hiring manager skimming this section in thirty seconds should walk away with four takeaways:

- **Implements all three MCP primitives — tools, resources, and prompts.** Most portfolio MCP projects stop at `@mcp.tool` and call it a day. LeadMind ships eight tools, two resources (`leads://dashboard`, `audit://recent`), and one reusable prompt template (`weekly_lead_review`). Resources and prompts are first-class MCP primitives with distinct semantics — resources expose addressable data, prompts expose parameterized conversation starters — and using all three correctly is a stronger signal of protocol fluency than yet another tool function.
- **Agentic reasoning, not just CRUD.** The `suggest_next_action` tool goes beyond read/write operations. It pulls the full history of a lead, passes that context to the Groq LLM, and returns a concrete recommendation ("Call within 4 hours; the prospect asked for a security questionnaire and hasn't received one"). That is the boundary between a database-with-an-API and an actual agent backend.
- **Production-grade reliability engineering.** A 30-day TTL cache in front of the LLM means the same lead message never gets classified twice. When Groq rate-limits or goes down, the server silently falls back to a deterministic rule-based classifier (keyword-weighted Hot/Warm/Cold scoring) so the service never returns an error to the user. Every tool call is written to an audit log with timestamp and arguments — observable by design, not by accident.
- **Built entirely on a free-tier stack, engineered for public demo traffic.** Groq's free tier handles LLM calls, SQLite (with WAL mode) handles persistence, the official Python MCP SDK handles transport, and FastAPI serves the webhook receiver. No paid APIs, no managed database, no credit card required — and the architecture is shaped to survive being posted on a public URL without collapsing on the first spike of traffic.

---

## Screenshots

![Dashboard](screenshots/dashboard.png)

![Architecture](screenshots/how-it-works.png)

![Webhook Receiver](screenshots/webhook-receiver.png)

---

## Features

### MCP Tools (8)

| Tool | Description |
| --- | --- |
| `get_leads` | List all leads, optionally filtered by status (`hot` / `warm` / `cold`). |
| `classify_lead` | Score a free-text lead message into Hot / Warm / Cold with confidence score and human-readable reasoning. |
| `add_lead` | Insert a new lead (name, contact, message, source); auto-classifies on insert. |
| `update_lead_status` | Manually override a lead's status; change is written to the audit log with a timestamp. |
| `get_lead_stats` | Aggregate pipeline snapshot — total counts, breakdown by status and source. |
| `get_lead_history` | Full timeline of status changes and interactions for one lead by ID. |
| `suggest_next_action` | Generate an AI-recommended next action for a lead, grounded in its full history. |
| `bulk_import_leads` | Ingest leads from CSV text; required columns are `name` and `message`. |

### MCP Resources (2)

| URI | Description |
| --- | --- |
| `leads://dashboard` | Live-updating summary snapshot of the whole pipeline — total counts, status mix, recent activity. |
| `audit://recent` | Recent tool-call audit log — useful for demos to show observability and traceability. |

### MCP Prompt (1)

| Prompt | Description |
| --- | --- |
| `weekly_lead_review` | Pre-packaged prompt template for generating a weekly lead performance summary — drops the user straight into a structured retrospective conversation. |

---

## Architecture

```
┌────────────────────┐     MCP (stdio / SSE)     ┌────────────────────────────────────────┐
│  MCP Client        │  ───────────────────────►  │  LeadMind MCP Server                   │
│  (Claude Desktop)  │                            │  ┌──────────────────────────────────┐  │
│                    │                            │  │  8 tools  •  2 resources  •  1 prompt │
└────────────────────┘                            │  └──────────────────────────────────┘  │
                                                  │             │                            │
                                                  │             ▼                            │
                                                  │  ┌──────────────────────────────────┐  │
                                                  │  │  FastAPI + SQLite (WAL mode)     │  │
                                                  │  │  • classify_lead pipeline        │  │
                                                  │  │  • audit log (every tool call)   │  │
                                                  │  │  • webhook receiver (/webhook)   │  │
                                                  │  └──────────────────────────────────┘  │
                                                  └────────────────────────────────────────┘
```

### `classify_lead` decision chain

Every call to `classify_lead` walks the same chain, stopping at the first layer that returns an answer:

```
                   ┌───────────────────────┐
   classify_lead ─►│  1. TTL Cache lookup  │  hit?  ──► return cached label + reasoning
                   └───────────┬───────────┘
                               │ miss
                               ▼
                   ┌───────────────────────┐
                   │  2. Groq LLM call     │  200?  ──► persist + cache + return
                   │     (Llama 3.x)       │
                   └───────────┬───────────┘
                               │ 429 / 5xx / timeout
                               ▼
                   ┌───────────────────────┐
                   │  3. Rule-based        │  always ─► return weighted Hot/Warm/Cold
                   │     fallback          │           (keyword scoring, deterministic)
                   └───────────────────────┘
```

This chain is the reason the service never returns an error to the caller: the LLM is a performance optimization, not a single point of failure. If Groq is unavailable, the user still gets a defensible answer — just one produced by a simpler model.

---

## Tech Stack

Every dependency below has a functional free tier. No paid APIs, no managed services, no credit card required to run or demo this project.

- **Python 3.12** — runtime
- **[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)** (`mcp >= 1.2.0`) — official FastMCP implementation, stdio + SSE transports
- **[Groq](https://groq.com/)** — LLM inference (Llama 3.x) on the free tier
- **SQLite** (with WAL mode enabled) — single-file persistence, zero ops overhead
- **[FastAPI](https://fastapi.tiangolo.com/)** (`>= 0.110.0`) — webhook receiver and dashboard API
- **[Uvicorn](https://www.uvicorn.org/)** (`>= 0.27.0`) — ASGI server
- **`requests`** (`>= 2.31.0`) — Groq HTTP client
- **Claude Desktop** — reference MCP client for end-to-end testing

---

## Setup / Run Locally

```bash
# 1. Clone
git clone [GITHUB_URL]
cd leadmind-mcp

# 2. Install dependencies (Python 3.10+)
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env and set GROQ_API_KEY (free at https://console.groq.com/keys)

# 4. Run the MCP server (stdio transport, for Claude Desktop)
python mcp_server.py

# 5. (Optional) Run the web dashboard + webhook receiver
./run_dashboard.sh
#   → Dashboard:  http://localhost:8000
#   → Webhook:    http://localhost:8000/webhook
```

If `GROQ_API_KEY` is unset or invalid, the server still runs — `classify_lead` automatically falls back to the rule-based scorer, so you can develop and demo without an API key.

---

## Connect to Claude Desktop

Add the following to your `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "leadmind": {
      "command": "python",
      "args": ["/absolute/path/to/leadmind-mcp/mcp_server.py"],
      "env": {
        "GROQ_API_KEY": "your_groq_api_key_here",
        "DEMO_MODE": "true",
        "MCP_TRANSPORT": "stdio"
      }
    }
  }
}
```

Restart Claude Desktop, then try:

> *"Use LeadMind to show me every hot lead added in the last 24 hours, then suggest the next action for the most recent one."*

Claude will chain `get_leads` → `suggest_next_action` automatically and return a structured, sourced answer.

---

## License

Released under the **MIT License**.

```
MIT License

Copyright (c) 2025 LeadMind MCP contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

Built as a demonstration of production-grade MCP server engineering, not just an API wrapper.
