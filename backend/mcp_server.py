"""
LeadMind MCP — Model Context Protocol server for an AI lead management CRM.

Exposes 8 tools, 1 resource, and 1 prompt template using the official
Python MCP SDK (modelcontextprotocol/python-sdk, FastMCP).

Transports:
    - stdio (default, for Claude Desktop) — `python mcp_server.py`
    - SSE   (for web/remote clients)      — `MCP_TRANSPORT=sse python mcp_server.py`

Run-time safety:
    - On startup: initializes DB + seeds demo data if empty
    - On every tool call: lazily resets demo data every DEMO_RESET_INTERVAL_SEC
    - Every tool call is recorded in audit_log with the path used (groq/fallback/cache)

Connect from Claude Desktop — add to claude_desktop_config.json:
    {
      "mcpServers": {
        "leadmind": {
          "command": "python",
          "args": ["/absolute/path/to/leadmind-mcp/mcp_server.py"],
          "env": { "GROQ_API_KEY": "your_key", "DEMO_MODE": "true" }
        }
      }
    }
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional

# Ensure local imports work when run as `python mcp_server.py`
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from config import (  # noqa: E402
    LEADMIND_API_KEY,
    LEADMIND_AUTH_ENABLED,
    DEMO_MODE,
    MCP_PORT,
    MCP_TRANSPORT,
)
from db import (  # noqa: E402
    fetch_audit_summary,
    fetch_groq_usage_counts,
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
    get_lead_history,
    get_lead_stats,
    get_leads,
    suggest_next_action,
    update_lead_status,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,  # MCP stdio uses stdout for protocol — logs go to stderr
)
logger = logging.getLogger("leadmind")


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
def _startup() -> None:
    init_db()
    # Always run the seeder on startup; it's a no-op if DB already has data
    # unless demo mode wants a reset.
    if DEMO_MODE:
        seed_database(force=True)
        logger.info("Demo mode ON: database reset to seed data on startup.")
    else:
        seed_database(force=False)
        logger.info("Demo mode OFF: seeded only if DB was empty.")


_startup()


# ---------------------------------------------------------------------------
# Auth (optional, SSE only)
# ---------------------------------------------------------------------------
# FastMCP does not yet expose a clean header middleware hook for stdio.
# For SSE deployments with auth enabled, put the server behind a reverse
# proxy (nginx/caddy) that validates `Authorization: Bearer <key>` and
# only then forwards to the FastMCP SSE endpoint. The API key is exposed
# here so the README / health endpoint can confirm whether auth is on.
_AUTH_NOTE = (
    f"Auth enabled={LEADMIND_AUTH_ENABLED}. "
    f"When enabled, gate the SSE endpoint behind a proxy that checks "
    f"'Authorization: Bearer <{LEADMIND_API_KEY[:8]}...>' (key from LEADMIND_API_KEY env var)."
)
logger.info(_AUTH_NOTE)


# ---------------------------------------------------------------------------
# FastMCP instance
# ---------------------------------------------------------------------------
mcp = FastMCP(
    "LeadMind MCP",
    instructions=(
        "LeadMind is an AI lead-management CRM exposed as an MCP server. "
        "Use the tools to fetch, classify, add, update, and analyze leads. "
        "Read the leads://dashboard resource for a live pipeline snapshot. "
        "Use the 'weekly_lead_review' prompt template to generate a weekly summary."
    ),
    dependencies=["requests"],
)


# ---------------------------------------------------------------------------
# TOOLS (8)
# ---------------------------------------------------------------------------

@mcp.tool()
def tool_get_leads(status: str = "") -> Dict[str, Any]:
    """Get all leads, optionally filtered by status.

    Args:
        status: One of Hot | Warm | Cold | Converted | Lost. Empty string returns all.

    Returns:
        {count, filter, leads: [...]}
    """
    return get_leads(status=status if status else None)


@mcp.tool()
def tool_classify_lead(text: str) -> Dict[str, Any]:
    """Classify a lead message into Hot / Warm / Cold with confidence + reasoning.

    Uses a TTL cache first, then Groq (Llama-3.3-70b-versatile, free tier),
    then a rule-based fallback if the API limit is hit — so this tool never
    fails under public load.

    Args:
        text: The lead's message text.

    Returns:
        {status, confidence, reasoning, source}
    """
    return classify_lead(text)


@mcp.tool()
def tool_add_lead(
    name: str, contact_info: str, message: str, source: str = "manual"
) -> Dict[str, Any]:
    """Add a new lead. The message is auto-classified and the lead is saved
    to the DB with full history.

    Args:
        name: Lead's name.
        contact_info: Email / phone / handle.
        message: The lead's inquiry message (used for classification).
        source: Where the lead came from (e.g. 'Website Form', 'Referral').

    Returns:
        {id, name, status, classification}
    """
    return add_lead(name=name, contact_info=contact_info, message=message, source=source)


@mcp.tool()
def tool_update_lead_status(id: int, status: str) -> Dict[str, Any]:
    """Manually override a lead's status. Logs the change with timestamp.

    Args:
        id: Lead ID.
        status: One of Hot | Warm | Cold | Converted | Lost.

    Returns:
        {id, old_status, new_status, updated_at}
    """
    return update_lead_status(id=id, status=status)


@mcp.tool()
def tool_get_lead_stats() -> Dict[str, Any]:
    """Get aggregate pipeline stats: total leads, breakdown by status and
    source, average response time, conversion rate, and Groq usage counts
    for free-tier monitoring.
    """
    return get_lead_stats()


@mcp.tool()
def tool_get_lead_history(id: int) -> Dict[str, Any]:
    """Get the full timeline of status changes and interactions for one lead.

    Args:
        id: Lead ID.

    Returns:
        {lead: {...}, history: [...]}
    """
    return get_lead_history(id=id)


@mcp.tool()
def tool_suggest_next_action(id: int) -> Dict[str, Any]:
    """Generate an AI-recommended next action for a lead based on its history
    and current status. Falls back to rule-based suggestion if Groq limit hit.

    Args:
        id: Lead ID.

    Returns:
        {lead_id, lead_name, current_status, suggestion, source}
    """
    return suggest_next_action(id=id)


@mcp.tool()
def tool_bulk_import_leads(csv_data: str) -> Dict[str, Any]:
    """Bulk import leads from CSV text. Required columns: name, message.
    Optional: contact_info, source. Uses caching to avoid redundant API calls
    on duplicate-looking entries.

    Args:
        csv_data: CSV text with header row. Example:
            name,contact_info,message,source
            John Doe,john@example.com,"Interested in pricing",Website Form

    Returns:
        {imported, errors, leads: [...]}
    """
    return bulk_import_leads(csv_data=csv_data)


# ---------------------------------------------------------------------------
# RESOURCE (1) — leads://dashboard
# ---------------------------------------------------------------------------

@mcp.resource("leads://dashboard")
def dashboard_resource() -> str:
    """Live-updating summary snapshot of the whole pipeline.

    An MCP client can 'read' this resource like a file to get the current
    CRM state without calling individual tools.
    """
    stats = fetch_stats()
    recent = fetch_recent_leads(limit=10)
    usage = get_usage_snapshot()
    audit_counts = fetch_groq_usage_counts()

    lines = [
        "LeadMind CRM — Live Dashboard Snapshot",
        "=" * 50,
        f"Generated: {datetime.utcnow().isoformat()}Z",
        f"Demo Mode: {'ON' if DEMO_MODE else 'OFF'}",
        "",
        "PIPELINE TOTALS",
        f"  Total Leads:        {stats['total_leads']}",
        f"  Conversion Rate:    {stats['conversion_rate_percent']}%",
        f"  Avg Response Time:  {stats['average_response_time_minutes']} min",
        "",
        "BY STATUS",
    ]
    for s in ("Hot", "Warm", "Cold", "Converted", "Lost"):
        lines.append(f"  {s:<10} {stats['by_status'].get(s, 0)}")
    lines.append("")
    lines.append("BY SOURCE")
    for s, c in sorted(stats["by_source"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {s:<20} {c}")
    lines.append("")
    lines.append("RECENT LEADS (last 10)")
    for r in recent:
        lines.append(
            f"  #{r['id']:<3} [{r['status']:<10}] {r['name']:<25} via {r['source']}  ({r['created_at']})"
        )
    lines.append("")
    lines.append("FREE-TIER USAGE MONITORING")
    lines.append(f"  Groq calls this session:    {usage['in_memory_calls_this_session']}")
    lines.append(f"  Total logged Groq calls:    {usage['total_logged_calls']}")
    lines.append(f"  Logged successes:           {usage['logged_success']}")
    lines.append(f"  Logged rate-limited (429):  {usage['logged_rate_limited']}")
    lines.append(f"  Logged errors:              {usage['logged_errors']}")
    lines.append("")
    lines.append("AUDIT (last 50 tool calls — by classification path)")
    lines.append(f"  Used Groq:      {audit_counts['groq_calls']}")
    lines.append(f"  Used Fallback:  {audit_counts['fallback_calls']}")
    lines.append(f"  Cache hits:     {audit_counts['cache_hits']}")
    lines.append(f"  Total AI-tool calls: {audit_counts['total_tool_calls']}")
    lines.append("=" * 50)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PROMPT TEMPLATE (1) — weekly_lead_review
# ---------------------------------------------------------------------------

@mcp.prompt()
def weekly_lead_review() -> str:
    """Pre-packaged prompt template for generating a weekly lead performance summary.

    When an MCP client (e.g. Claude Desktop) opens this prompt, it gets a
    fully-formed system + user prompt that includes current pipeline stats
    and instructs the AI to fetch more details via the available tools.
    """
    stats = fetch_stats()
    return f"""You are a sales manager reviewing this week's lead pipeline performance for LeadMind CRM.

Generate a structured weekly review with these sections:

1. **Pipeline Overview** — total leads, breakdown by status, top sources
2. **Hot Leads Highlight** — list every Hot lead that needs immediate attention (use the `tool_get_leads` tool with status="Hot")
3. **Conversion Analysis** — current conversion rate ({stats['conversion_rate_percent']}%), what's working, what's not
4. **At-Risk Leads** — warm/cold leads that have gone stale (no recent status_change events). Use `tool_get_lead_history` to inspect.
5. **Recommended Actions** — top 3 priorities for next week, with specific lead IDs and the suggested next action (use `tool_suggest_next_action`)

Current pipeline snapshot:
- Total leads: {stats['total_leads']}
- By status: {stats['by_status']}
- By source: {stats['by_source']}
- Average response time: {stats['average_response_time_minutes']} minutes
- Conversion rate: {stats['conversion_rate_percent']}%

You have access to the LeadMind MCP tools (tool_get_leads, tool_get_lead_history, tool_suggest_next_action, tool_get_lead_stats). Use them as needed. Also read the `leads://dashboard` resource for a live snapshot.

Format the final review in clean markdown with clear section headers. Be specific: cite lead IDs and names. Keep it under 600 words.
"""


# ---------------------------------------------------------------------------
# Bonus resource: audit log (observability)
# ---------------------------------------------------------------------------

@mcp.resource("audit://recent")
def audit_resource() -> str:
    """Recent tool-call audit log — useful for demos to show observability."""
    rows = fetch_audit_summary(limit=30)
    if not rows:
        return "Audit log is empty."
    lines = ["Recent Tool Calls (last 30)", "=" * 50]
    for r in rows:
        flags = []
        if r["used_groq"]:
            flags.append("groq")
        if r["used_fallback"]:
            flags.append("fallback")
        if r["used_cache"]:
            flags.append("cache")
        flag_str = ",".join(flags) or "none"
        status_str = "OK" if r["success"] else f"FAIL({r['error_message'] or '?'})"
        lines.append(
            f"  #{r['id']:<4} {r['created_at']}  {r['tool_name']:<22} "
            f"[{flag_str:<14}] {status_str}  {r['duration_ms']}ms"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    if MCP_TRANSPORT == "sse":
        logger.info("Starting LeadMind MCP server on SSE transport (port %s)", MCP_PORT)
        mcp.run(transport="sse")
    else:
        logger.info("Starting LeadMind MCP server on stdio transport")
        mcp.run()


if __name__ == "__main__":
    main()
