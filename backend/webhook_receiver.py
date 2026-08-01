"""
Optional FastAPI webhook receiver for n8n / Gmail integration.

This is a SEPARATE process from the MCP server. It exposes a small HTTP API
so external automation (n8n workflows, Zapier, Gmail forwarding rules) can
push new leads into LeadMind without speaking MCP.

Run separately:
    pip install fastapi uvicorn
    uvicorn webhook_receiver:app --host 0.0.0.0 --port 8000

Endpoints:
    POST /webhook/lead        — accepts JSON {name, contact_info, message, source}
    POST /webhook/lead/csv    — accepts CSV text in body, bulk-imports
    GET  /health              — basic health check
    GET  /stats               — pipeline stats (cached)

Auth:
    Set LEADMIND_AUTH_ENABLED=true and LEADMIND_API_KEY=<secret>.
    All webhook requests must then carry `X-API-Key: <secret>`.

Gmail integration (free tier):
    Use a Gmail filter that forwards matching emails to a Gmail-to-webhook
    bridge (e.g. an Apps Script or n8n Gmail trigger), which then POSTs the
    parsed message here. Gmail's free tier allows ~20k emails/day — plenty
    for a public demo.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict, Optional

# Allow `python webhook_receiver.py` from the project dir
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from fastapi import FastAPI, Header, HTTPException, Request, Response
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
)
from db import init_db  # noqa: E402
from seed_data import seed_database  # noqa: E402
from tools import add_lead, bulk_import_leads, get_lead_stats  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("leadmind.webhook")

# Initialize DB on startup
init_db()
seed_database(force=False)

app = FastAPI(title="LeadMind Webhook Receiver", version="1.0.0")


def _check_auth(x_api_key: Optional[str]) -> None:
    if LEADMIND_AUTH_ENABLED:
        if not x_api_key or x_api_key != LEADMIND_API_KEY:
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "auth_enabled": LEADMIND_AUTH_ENABLED,
        "n8n_webhook_configured": bool(N8N_WEBHOOK_URL),
        "gmail_notify_configured": bool(GMAIL_NOTIFY_TO),
    }


@app.post("/webhook/lead")
async def webhook_lead(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> Dict[str, Any]:
    """Accept a single lead as JSON. Triggers optional n8n + Gmail notifications."""
    _check_auth(x_api_key)
    payload = await request.json()
    name = payload.get("name")
    contact_info = payload.get("contact_info", "")
    message = payload.get("message", "")
    source = payload.get("source", "webhook")

    if not name or not message:
        raise HTTPException(status_code=400, detail="Fields 'name' and 'message' are required.")

    result = add_lead(name=name, contact_info=contact_info, message=message, source=source)

    # Best-effort outbound n8n trigger (free, self-hosted n8n)
    if N8N_WEBHOOK_URL:
        try:
            import requests
            requests.post(N8N_WEBHOOK_URL, json=result, timeout=5)
        except Exception as e:
            logger.warning("n8n webhook call failed: %s", e)

    # Gmail notification hook would go here (omitted to keep zero-config).
    # See README for the Gmail-Apps-Script pattern.
    if GMAIL_NOTIFY_TO:
        logger.info("Gmail notify target set to %s (notification skipped in demo).", GMAIL_NOTIFY_TO)

    return result


@app.post("/webhook/lead/csv", response_class=PlainTextResponse)
async def webhook_lead_csv(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> str:
    """Accept CSV text in the body and bulk-import."""
    _check_auth(x_api_key)
    csv_data = (await request.body()).decode("utf-8")
    result = bulk_import_leads(csv_data=csv_data)
    return (
        f"Imported {result['imported']} leads, {len(result['errors'])} errors.\n"
        + "\n".join(result["errors"])
    )


@app.get("/stats")
def stats() -> Dict[str, Any]:
    """Pipeline stats (read-only, safe for unauthenticated GET if auth is off)."""
    if LEADMIND_AUTH_ENABLED:
        # For demo simplicity, /stats is public even when auth is on
        pass
    return get_lead_stats()


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("WEBHOOK_PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
