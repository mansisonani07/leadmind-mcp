"""
The 8 MCP tool implementations.

Each function is a thin wrapper around db.* / groq_classifier.* that:
  - measures wall-clock duration
  - writes a structured audit_log row (which path was used: groq/fallback/cache)
  - raises on hard errors so the MCP server can surface them to the client

These functions are imported and registered by mcp_server.py.
"""
from __future__ import annotations

import csv
import io
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from db import (
    clear_all_leads,
    fetch_lead,
    fetch_lead_history,
    fetch_leads,
    fetch_recent_leads,
    fetch_stats,
    insert_audit,
    insert_lead,
    maybe_reset_demo,
    update_lead_status_row,
)
from groq_classifier import classify_lead as _classify
from groq_classifier import suggest_next_action as _groq_suggest
from groq_classifier import get_usage_snapshot

logger = logging.getLogger("leadmind.tools")

VALID_STATUSES = {"Hot", "Warm", "Cold", "Converted", "Lost"}


def _ensure_demo_ready() -> None:
    """If demo mode says it's time to reset, trigger a seed reset (lazy import
    to avoid circular import with seed_data -> db)."""
    if maybe_reset_demo():
        # Only reset if we actually have leads already — otherwise the initial
        # seeding on startup already handles it.
        from seed_data import seed_database
        try:
            seed_database(force=True)
            logger.info("Demo mode: database reset to seed data.")
        except Exception as e:
            logger.error("Demo reset failed: %s", e)


# ---------------------------------------------------------------------------
# 1. get_leads
# ---------------------------------------------------------------------------

def get_leads(status: Optional[str] = None) -> Dict[str, Any]:
    """Return all leads, optionally filtered by status (Hot/Warm/Cold/Converted/Lost)."""
    start = time.time()
    params: Dict[str, Any] = {"status": status}
    _ensure_demo_ready()
    try:
        if status and status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}'. Valid: {sorted(VALID_STATUSES)}")
        leads = fetch_leads(status=status)
        result = {
            "count": len(leads),
            "filter": status or "all",
            "leads": leads,
        }
        insert_audit("get_leads", params, success=True, duration_ms=int((time.time() - start) * 1000))
        return result
    except Exception as e:
        insert_audit("get_leads", params, success=False, error_message=str(e),
                     duration_ms=int((time.time() - start) * 1000))
        raise


# ---------------------------------------------------------------------------
# 2. classify_lead
# ---------------------------------------------------------------------------

def classify_lead(text: str) -> Dict[str, Any]:
    """Classify a lead message. Uses cache -> Groq -> fallback in that order."""
    start = time.time()
    params: Dict[str, Any] = {"text_preview": (text or "")[:200]}
    _ensure_demo_ready()
    used_cache_before = False
    try:
        if not text or not text.strip():
            raise ValueError("text must be a non-empty string")
        # Probe cache to log whether this call would hit
        from cache import cache as _cache
        cache_key = _cache.make_key(text)
        if _cache.get(cache_key) is not None:
            used_cache_before = True
        result = _classify(text)
        insert_audit(
            "classify_lead",
            params,
            used_groq=result.get("source") == "groq",
            used_fallback=result.get("source") == "fallback",
            used_cache=result.get("source") == "cache" or used_cache_before,
            success=True,
            duration_ms=int((time.time() - start) * 1000),
        )
        return result
    except Exception as e:
        insert_audit("classify_lead", params, success=False, error_message=str(e),
                     duration_ms=int((time.time() - start) * 1000))
        raise


# ---------------------------------------------------------------------------
# 3. add_lead
# ---------------------------------------------------------------------------

def add_lead(name: str, contact_info: str, message: str, source: str = "manual") -> Dict[str, Any]:
    """Add a lead with automatic classification on insert."""
    start = time.time()
    params: Dict[str, Any] = {
        "name": name,
        "contact_info": contact_info,
        "message_preview": (message or "")[:200],
        "source": source,
    }
    _ensure_demo_ready()
    try:
        if not name or not name.strip():
            raise ValueError("name is required")
        if not message or not message.strip():
            raise ValueError("message is required (needed for classification)")
        classification = _classify(message)
        history_entries = [
            {
                "event_type": "created",
                "event_description": f"Lead added from source: {source}",
                "new_value": classification["status"],
            },
            {
                "event_type": "classified",
                "event_description": (
                    f"Auto-classified as {classification['status']} "
                    f"({classification['reasoning']}) [source={classification['source']}]"
                ),
                "old_value": None,
                "new_value": classification["status"],
            },
        ]
        lead_id = insert_lead(
            name=name.strip(),
            contact_info=(contact_info or "").strip(),
            message=message.strip(),
            status=classification["status"],
            source=(source or "manual").strip() or "manual",
            history_entries=history_entries,
        )
        insert_audit(
            "add_lead",
            params,
            used_groq=classification.get("source") == "groq",
            used_fallback=classification.get("source") == "fallback",
            used_cache=classification.get("source") == "cache",
            success=True,
            duration_ms=int((time.time() - start) * 1000),
        )
        return {
            "id": lead_id,
            "name": name.strip(),
            "status": classification["status"],
            "classification": classification,
        }
    except Exception as e:
        insert_audit("add_lead", params, success=False, error_message=str(e),
                     duration_ms=int((time.time() - start) * 1000))
        raise


# ---------------------------------------------------------------------------
# 4. update_lead_status
# ---------------------------------------------------------------------------

def update_lead_status(id: int, status: str) -> Dict[str, Any]:
    """Manually override a lead's status. Logs the change with timestamp."""
    start = time.time()
    params: Dict[str, Any] = {"id": id, "status": status}
    _ensure_demo_ready()
    try:
        if not isinstance(id, int) or id <= 0:
            raise ValueError("id must be a positive integer")
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{status}'. Valid: {sorted(VALID_STATUSES)}")
        lead = fetch_lead(id)
        if not lead:
            raise ValueError(f"Lead {id} not found")
        old_status = lead["status"]
        description = f"Status manually updated from {old_status} to {status}"
        update_lead_status_row(lead_id=id, new_status=status, old_status=old_status, description=description)
        insert_audit("update_lead_status", params, success=True,
                     duration_ms=int((time.time() - start) * 1000))
        return {
            "id": id,
            "old_status": old_status,
            "new_status": status,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e:
        insert_audit("update_lead_status", params, success=False, error_message=str(e),
                     duration_ms=int((time.time() - start) * 1000))
        raise


# ---------------------------------------------------------------------------
# 5. get_lead_stats
# ---------------------------------------------------------------------------

def get_lead_stats() -> Dict[str, Any]:
    """Aggregate pipeline stats."""
    start = time.time()
    _ensure_demo_ready()
    try:
        stats = fetch_stats()
        # Include Groq usage monitoring so the operator can see free-tier burn rate
        stats["groq_usage"] = get_usage_snapshot()
        insert_audit("get_lead_stats", {}, success=True,
                     duration_ms=int((time.time() - start) * 1000))
        return stats
    except Exception as e:
        insert_audit("get_lead_stats", {}, success=False, error_message=str(e),
                     duration_ms=int((time.time() - start) * 1000))
        raise


# ---------------------------------------------------------------------------
# 6. get_lead_history
# ---------------------------------------------------------------------------

def get_lead_history(id: int) -> Dict[str, Any]:
    """Full timeline of a single lead."""
    start = time.time()
    params: Dict[str, Any] = {"id": id}
    _ensure_demo_ready()
    try:
        lead = fetch_lead(id)
        if not lead:
            raise ValueError(f"Lead {id} not found")
        history = fetch_lead_history(id)
        insert_audit("get_lead_history", params, success=True,
                     duration_ms=int((time.time() - start) * 1000))
        return {"lead": lead, "history": history}
    except Exception as e:
        insert_audit("get_lead_history", params, success=False, error_message=str(e),
                     duration_ms=int((time.time() - start) * 1000))
        raise


# ---------------------------------------------------------------------------
# 7. suggest_next_action
# ---------------------------------------------------------------------------

def suggest_next_action(id: int) -> Dict[str, Any]:
    """Groq-generated next-action recommendation with rule-based fallback."""
    start = time.time()
    params: Dict[str, Any] = {"id": id}
    _ensure_demo_ready()
    try:
        lead = fetch_lead(id)
        if not lead:
            raise ValueError(f"Lead {id} not found")
        history = fetch_lead_history(id)
        result = _groq_suggest(lead, history)
        insert_audit(
            "suggest_next_action",
            params,
            used_groq=result.get("source") == "groq",
            used_fallback=result.get("source") == "fallback",
            success=True,
            duration_ms=int((time.time() - start) * 1000),
        )
        return {
            "lead_id": id,
            "lead_name": lead["name"],
            "current_status": lead["status"],
            **result,
        }
    except Exception as e:
        insert_audit("suggest_next_action", params, success=False, error_message=str(e),
                     duration_ms=int((time.time() - start) * 1000))
        raise


# ---------------------------------------------------------------------------
# 8. bulk_import_leads
# ---------------------------------------------------------------------------

def bulk_import_leads(csv_data: str) -> Dict[str, Any]:
    """Parse CSV text and batch-classify + insert multiple leads.

    Expected columns: name, message (required); contact_info, source (optional).
    Identical messages hit the cache, so duplicate-looking rows are free.
    """
    start = time.time()
    params: Dict[str, Any] = {"csv_length": len(csv_data or "")}
    _ensure_demo_ready()
    inserted: List[Dict[str, Any]] = []
    errors: List[str] = []
    try:
        if not csv_data or not csv_data.strip():
            raise ValueError("csv_data is empty")
        reader = csv.DictReader(io.StringIO(csv_data))
        required = {"name", "message"}
        if not required.issubset({(k or "").strip() for k in (reader.fieldnames or [])}):
            raise ValueError(
                f"CSV must include columns: name, message. Found: {reader.fieldnames}"
            )
        for i, row in enumerate(reader, start=1):
            try:
                name = (row.get("name") or "").strip()
                message = (row.get("message") or "").strip()
                contact_info = (row.get("contact_info") or "").strip()
                source = (row.get("source") or "csv_import").strip() or "csv_import"
                if not name or not message:
                    errors.append(f"Row {i}: empty name or message — skipped.")
                    continue
                classification = _classify(message)
                history_entries = [
                    {
                        "event_type": "created",
                        "event_description": f"Bulk-imported lead (row {i}) from source: {source}",
                        "new_value": classification["status"],
                    },
                    {
                        "event_type": "classified",
                        "event_description": (
                            f"Auto-classified as {classification['status']} "
                            f"({classification['reasoning']}) [source={classification['source']}]"
                        ),
                        "old_value": None,
                        "new_value": classification["status"],
                    },
                ]
                lead_id = insert_lead(
                    name=name,
                    contact_info=contact_info,
                    message=message,
                    status=classification["status"],
                    source=source,
                    history_entries=history_entries,
                )
                inserted.append({
                    "id": lead_id,
                    "name": name,
                    "status": classification["status"],
                    "classification_source": classification["source"],
                })
            except Exception as row_err:
                errors.append(f"Row {i}: {row_err}")
        insert_audit(
            "bulk_import_leads",
            params,
            success=True,
            duration_ms=int((time.time() - start) * 1000),
        )
        return {
            "imported": len(inserted),
            "errors": errors,
            "leads": inserted,
        }
    except Exception as e:
        insert_audit("bulk_import_leads", params, success=False, error_message=str(e),
                     duration_ms=int((time.time() - start) * 1000))
        raise


# ---------------------------------------------------------------------------
# Bonus introspection helpers (exposed via resource/prompt, not as MCP tools)
# ---------------------------------------------------------------------------

def get_recent_leads_for_dashboard(limit: int = 10) -> List[Dict[str, Any]]:
    return fetch_recent_leads(limit=limit)
