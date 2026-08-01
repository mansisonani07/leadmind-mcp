# LeadMind MCP — Demo Script

This walkthrough shows the end-to-end experience of using LeadMind MCP from
**Claude Desktop** (or any other MCP-compatible client).

## Prerequisites

1. Install dependencies: `pip install -r requirements.txt`
2. (Optional) Set `GROQ_API_KEY` in `.env` for LLM-powered classification.
   Without a key, the server still works using the rule-based fallback classifier.
3. Add the server to Claude Desktop — edit `claude_desktop_config.json`:
   ```json
   {
     "mcpServers": {
       "leadmind": {
         "command": "python",
         "args": ["/absolute/path/to/leadmind-mcp/mcp_server.py"],
         "env": { "DEMO_MODE": "true" }
       }
     }
   }
   ```
4. Restart Claude Desktop. The `leadmind` server will appear under
   **Settings → Developer → MCP Servers** with a green "connected" indicator.

---

## Demo Flow

### Step 1 — Live Dashboard Snapshot (Resource)

**You say:**
> "Read the LeadMind dashboard and tell me the current state of the pipeline."

**What happens:**
- Claude reads the `leads://dashboard` resource.
- The MCP server returns a live text snapshot: total leads, breakdown by
  status and source, recent leads, and Groq usage monitoring.
- Claude summarizes: *"You have 18 leads — 4 Hot, 7 Warm, 7 Cold. Top source
  is 'Website Form' with 4 leads. Conversion rate is 0%. Groq has been called
  0 times this session."*

### Step 2 — Fetch Hot Leads

**You say:**
> "Show me all hot leads and suggest the next action for the top one."

**What happens:**
1. Claude calls `tool_get_leads(status="Hot")`.
2. The server returns the 4 Hot leads: Sarah Chen, James O'Connor, David Kim,
   Sophia Rossi, Yuki Tanaka.
3. Claude picks the top one (Sarah Chen, id=1) and calls
   `tool_suggest_next_action(id=1)`.
4. Groq (or the fallback if rate-limited) returns a specific recommendation:
   *"Call Sarah Chen within 24 hours — hot leads decay fast. Confirm budget
   and Q3 timeline, then send a tailored 50-seat proposal."*
5. Claude formats the answer with the lead name, message preview, and the
   recommendation.

### Step 3 — Add a New Lead

**You say:**
> "Add a new lead: name is 'Alex Rivera', email alex@startupx.com, message is
> 'We need a CRM urgently, budget approved, ready to sign this week', source
> is 'Cold Outreach'."

**What happens:**
- Claude calls `tool_add_lead(name="Alex Rivera", contact_info="alex@startupx.com",
  message="...", source="Cold Outreach")`.
- The server classifies the message (Groq + cache + fallback chain) — it
  should come back as `Hot` because of "urgently", "budget approved", "ready
  to sign", "this week".
- The lead is inserted into the DB with full history.
- Claude responds: *"Added Alex Rivera as a Hot lead (id=19). Classification
  confidence 0.85. Reasoning: 'Hot because urgent language and budget
  mentioned'."*

### Step 4 — Bulk Import

**You say:**
> "Bulk import these leads from CSV:
> ```csv
> name,contact_info,message,source
> Maria Garcia,maria@garcia.io,"Just looking, maybe next year",Newsletter
> Tom Lee,tom@leeco.com,"URGENT: need pricing for 200 seats today",Referral
> ```"

**What happens:**
- Claude calls `tool_bulk_import_leads(csv_data="...")`.
- Both leads are classified and inserted. Maria → Cold, Tom → Hot.
- Claude confirms: *"Imported 2 leads. Maria Garcia → Cold. Tom Lee → Hot."*

### Step 5 — Update Status Manually

**You say:**
> "Mark lead id=1 as Converted."

**What happens:**
- Claude calls `tool_update_lead_status(id=1, status="Converted")`.
- The server logs the change in `lead_history` with a timestamp.
- Claude confirms: *"Sarah Chen (id=1) marked as Converted. Previously Hot."*

### Step 6 — Lead History Timeline

**You say:**
> "Show me the full history for lead id=1."

**What happens:**
- Claude calls `tool_get_lead_history(id=1)`.
- The server returns the lead record plus a timeline of every event:
  - `created` — Lead added from source: Website Form
  - `classified` — Auto-classified as Hot (Hot because urgent language...)
  - `status_change` — Status manually updated from Hot to Converted
- Claude formats the timeline in markdown.

### Step 7 — Weekly Review (Prompt Template)

**You say:**
> "Generate the weekly lead review using the weekly_lead_review prompt."

**What happens:**
- Claude opens the `weekly_lead_review` prompt template.
- The template auto-injects current pipeline stats and instructions.
- Claude then calls `tool_get_leads(status="Hot")`,
  `tool_get_lead_history(id=...)`, and `tool_suggest_next_action(id=...)`
  as instructed by the template.
- Claude produces a structured weekly review with sections:
  Pipeline Overview, Hot Leads Highlight, Conversion Analysis, At-Risk Leads,
  Recommended Actions.

### Step 8 — Observability Check (Resource)

**You say:**
> "Read the audit://recent resource and tell me how many Groq calls vs.
> fallback calls happened."

**What happens:**
- Claude reads the `audit://recent` resource.
- It returns the last 30 tool calls with flags showing which path was used:
  `[groq]`, `[fallback]`, `[cache]`, or `[none]`.
- Claude summarizes: *"Of the last 30 tool calls, 12 used Groq, 5 used the
  fallback, and 8 were served from cache."*

---

## Demonstrating Resilience (Demo-Safety Showcase)

To prove the system survives public load, you can simulate rate-limiting:

1. **Force rate limit**: Temporarily set `GROQ_API_KEY=invalid_key_xyz` —
   every Groq call will return 401, triggering the fallback path. All tools
   continue to work; classifications come back labeled `source: "fallback"`.

2. **Show caching**: Call `tool_classify_lead` with the same text twice.
   The second call returns `source: "cache"` and is essentially instant.

3. **Show demo reset**: Set `DEMO_RESET_INTERVAL_SEC=60` and wait 1 minute.
   The next tool call will trigger a reset to seed data — the DB returns to
   its known-good state.

4. **Check usage**: Call `tool_get_lead_stats()` — the response includes a
   `groq_usage` block showing calls this session, total logged calls,
   rate-limited count, and error count.

---

## Conversation Snippet (Copy-Paste Ready)

```
You:    Read the leads://dashboard resource and summarize the pipeline.
Claude: Reading leads://dashboard...
        - Total Leads: 18
        - Hot: 5, Warm: 7, Cold: 6
        - Conversion rate: 0%
        - Top source: Referral (4 leads)
        - Groq calls this session: 0 (using fallback classifier)

You:    Show me all Hot leads and suggest next action for the top one.
Claude: Calling tool_get_leads(status="Hot")...
        Found 5 Hot leads: Sarah Chen (id=1), James O'Connor (id=4),
        David Kim (id=6), Sophia Rossi (id=11), Yuki Tanaka (id=16).
        Calling tool_suggest_next_action(id=1) for Sarah Chen...
        Suggestion: Call Sarah Chen within 24 hours — her message mentions
        budget approval and a Friday deadline. Confirm the Q3 timeline and
        send a tailored proposal for 50 seats within 48 hours.
        (Source: Groq)

You:    Add a new lead — John Smith, john@smith.com, message is "Need a CRM
        urgently, have budget, decision needed this week", source: Cold Outreach.
Claude: Calling tool_add_lead(...)...
        Added John Smith as Hot lead (id=19).
        Confidence: 0.88. Reasoning: "Hot because urgent language detected,
        budget mentioned, and near-term decision timeline."
```
