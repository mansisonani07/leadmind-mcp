"""
FastAPI REST API for LeadMind MCP.

This is a SEPARATE process from the MCP server. It exposes a complete HTTP API
so the Next.js frontend (and external automation like n8n / Gmail bridges) can
read and write lead data without speaking MCP.

Run:
    pip install fastapi uvicorn
    python api_server.py             # listens on :8000

Endpoints:
    GET  /                           — root (service info + route list)
    GET  /health                     — basic health check
    GET  /stats                      — aggregate pipeline stats + Groq usage
    GET  /leads?status=Hot           — list leads, optional status filter
    GET  /leads/{id}                 — single lead + history timeline
    POST /leads                      — add a lead (auto-classifies)
    PATCH /leads/{id}/status         — update lead status
    GET  /leads/{id}/next-action     — AI next-action suggestion
    POST /leads/bulk-csv             — bulk import from CSV text
    GET  /audit                      — recent tool-call audit log
    GET  /dashboard                  — full dashboard snapshot (text + JSON)
    POST /demo/reset                 — force reset DB to seed data

Auth:
    Set LEADMIND_AUTH_ENABLED=true and LEADMIND_API_KEY=<secret>.
    All non-GET requests must then carry `X-API-Key: <secret>`.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict, Optional

# Allow `python api_server.py` from the project dir
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from fastapi import FastAPI, Header, HTTPException, Query, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import PlainTextResponse
except ImportError as e:  # pragma: no cover
    raise SystemExit(
        "FastAPI not installed. Install with: pip install fastapi uvicorn\n"
        f"Original error: {e}"
    )

from config import (  # noqa: E402
    LEADMIND_AUTH_ENABLED,
    LEADMIND_API_KEY,
    N8N_WEBHOOK_URL,
    GMAIL_NOTIFY_TO,
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
    get_lead_stats,
    suggest_next_action,
    update_lead_status,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("leadmind.api")

# Initialize DB on startup
init_db()
seed_database(force=False)

app = FastAPI(
    title="LeadMind MCP — REST API",
    version="1.0.0",
    description="HTTP API for the LeadMind CRM. The MCP server (mcp_server.py) writes to the same SQLite DB.",
)

# CORS — allow the Next.js frontend (port 3000) and any origin for the public demo
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _check_auth(x_api_key: Optional[str], require_auth: bool = False) -> None:
    """Auth check. GETs are public for demo readability; writes can be gated."""
    if LEADMIND_AUTH_ENABLED or require_auth:
        if not x_api_key or x_api_key != LEADMIND_API_KEY:
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")


# ---------------------------------------------------------------------------
# Root & health
# ---------------------------------------------------------------------------

@app.get("/")
def root() -> Dict[str, Any]:
    """Root endpoint — confirms the API is alive and lists available routes."""
    return {
        "service": "LeadMind MCP — REST API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "health": "GET /health",
            "stats": "GET /stats",
            "leads": "GET /leads?status=Hot",
            "add_lead": "POST /leads",
            "lead_detail": "GET /leads/{id}",
            "next_action": "GET /leads/{id}/next-action",
            "bulk_import": "POST /leads/bulk-csv",
            "audit": "GET /audit",
            "dashboard": "GET /dashboard",
        },
    }


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "leadmind-api",
        "demo_mode": DEMO_MODE,
        "auth_enabled": LEADMIND_AUTH_ENABLED,
        "n8n_webhook_configured": bool(N8N_WEBHOOK_URL),
        "gmail_notify_configured": bool(GMAIL_NOTIFY_TO),
    }


@app.get("/stats")
def stats() -> Dict[str, Any]:
    """Aggregate pipeline stats + Groq free-tier usage monitoring."""
    return get_lead_stats()


@app.get("/dashboard")
def dashboard() -> Dict[str, Any]:
    """Full dashboard snapshot — used by the Next.js frontend dashboard view."""
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


# ---------------------------------------------------------------------------
# Leads CRUD
# ---------------------------------------------------------------------------

@app.get("/leads")
def list_leads(
    status: Optional[str] = Query(default=None, description="Filter by Hot/Warm/Cold/Converted/Lost"),
) -> Dict[str, Any]:
    """List all leads, optionally filtered by status."""
    leads = fetch_leads(status=status if status else None)
    return {"count": len(leads), "filter": status or "all", "leads": leads}


@app.get("/leads/{lead_id}")
def get_lead_endpoint(lead_id: int) -> Dict[str, Any]:
    """Get a single lead with its full history timeline."""
    lead = fetch_lead(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")
    history = fetch_lead_history(lead_id)
    return {"lead": lead, "history": history}


@app.post("/leads")
async def create_lead(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> Dict[str, Any]:
    """Add a new lead. The message is auto-classified (cache -> Groq -> fallback)."""
    _check_auth(x_api_key)
    payload = await request.json()
    name = payload.get("name")
    contact_info = payload.get("contact_info", "")
    message = payload.get("message", "")
    source = payload.get("source", "Web Form")
    if not name or not message:
        raise HTTPException(status_code=400, detail="Fields 'name' and 'message' are required.")
    return add_lead(name=name, contact_info=contact_info, message=message, source=source)


@app.patch("/leads/{lead_id}/status")
async def patch_lead_status(
    lead_id: int,
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> Dict[str, Any]:
    """Update a lead's status. Body: {"status": "Hot|Warm|Cold|Converted|Lost"}."""
    _check_auth(x_api_key)
    payload = await request.json()
    new_status = payload.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="Field 'status' is required.")
    return update_lead_status(id=lead_id, status=new_status)


@app.get("/leads/{lead_id}/next-action")
def next_action(lead_id: int) -> Dict[str, Any]:
    """Get an AI-recommended next action for a lead (with rule-based fallback)."""
    return suggest_next_action(id=lead_id)


@app.post("/leads/bulk-csv", response_class=PlainTextResponse)
async def bulk_csv(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> str:
    """Bulk import leads from CSV text in the body."""
    _check_auth(x_api_key)
    csv_data = (await request.body()).decode("utf-8")
    result = bulk_import_leads(csv_data=csv_data)
    return (
        f"Imported {result['imported']} leads, {len(result['errors'])} errors.\n"
        + "\n".join(result["errors"])
    )


# ---------------------------------------------------------------------------
# Audit & demo control
# ---------------------------------------------------------------------------

@app.get("/audit")
def audit(limit: int = Query(default=50, ge=1, le=500)) -> Dict[str, Any]:
    """Recent tool-call audit log — observability for the demo."""
    return {"count": limit, "entries": fetch_audit_summary(limit=limit)}


@app.post("/demo/reset")
def demo_reset(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> Dict[str, Any]:
    """Force a reset of the DB to seed data. Useful for the demo 'Reset' button."""
    _check_auth(x_api_key)
    result = seed_database(force=True)
    return {"reset": result, "message": "Database reset to seed data."}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("API_PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
