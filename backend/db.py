"""
SQLite database layer for LeadMind MCP.

Schema:
    leads          - the CRM lead records
    lead_history   - append-only timeline of every status change / interaction
    audit_log      - structured log of every MCP tool call (observability)
    meta           - simple key/value store (demo-reset timestamp, etc.)

All writes go through `get_db()` which commits on success and rolls back on
exception, so partial updates never leave the DB in a weird state.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from config import DB_PATH, DEMO_MODE, DEMO_RESET_INTERVAL_SEC

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT NOT NULL,
    contact_info       TEXT,
    message            TEXT,
    status             TEXT DEFAULT 'Warm',          -- Hot | Warm | Cold | Converted | Lost
    source             TEXT,
    created_at         TEXT DEFAULT (datetime('now')),
    last_contacted_at  TEXT,
    converted_at       TEXT
);

CREATE TABLE IF NOT EXISTS lead_history (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id           INTEGER NOT NULL,
    event_type        TEXT NOT NULL,                 -- created | status_change | classified | contacted | note
    event_description TEXT,
    old_value         TEXT,
    new_value         TEXT,
    created_at        TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name      TEXT NOT NULL,
    params         TEXT,                              -- JSON of input params (truncated for safety)
    used_groq      INTEGER DEFAULT 0,
    used_fallback  INTEGER DEFAULT 0,
    used_cache     INTEGER DEFAULT 0,
    success        INTEGER DEFAULT 1,
    error_message  TEXT,
    duration_ms    INTEGER,
    created_at     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_leads_status    ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_source    ON leads(source);
CREATE INDEX IF NOT EXISTS idx_leads_created   ON leads(created_at);
CREATE INDEX IF NOT EXISTS idx_history_lead    ON lead_history(lead_id);
CREATE INDEX IF NOT EXISTS idx_audit_created   ON audit_log(created_at);
"""

# SQLite connection lock — the stdio MCP server is single-process, but
# FastMCP may dispatch concurrent tool calls on a thread pool, so we
# serialize writes to be safe with SQLite's single-writer model.
_write_lock = threading.Lock()


@contextmanager
def get_db():
    """Yield a connection that commits on success / rolls back on error."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        with _write_lock:
            yield conn
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create all tables if they don't exist. Safe to call repeatedly."""
    with get_db() as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# CRUD helpers (used by tools.py)
# ---------------------------------------------------------------------------

def insert_lead(
    name: str,
    contact_info: str,
    message: str,
    status: str,
    source: str,
    history_entries: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Insert a lead and its initial history rows. Returns new lead id."""
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO leads (name, contact_info, message, status, source)
               VALUES (?, ?, ?, ?, ?)""",
            (name, contact_info, message, status, source),
        )
        lead_id = cur.lastrowid
        for entry in history_entries or []:
            conn.execute(
                """INSERT INTO lead_history
                   (lead_id, event_type, event_description, old_value, new_value)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    lead_id,
                    entry["event_type"],
                    entry.get("event_description", ""),
                    entry.get("old_value"),
                    entry.get("new_value"),
                ),
            )
        return lead_id


def fetch_leads(status: Optional[str] = None) -> List[Dict[str, Any]]:
    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM leads WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM leads ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def fetch_lead(lead_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return dict(row) if row else None


def fetch_lead_history(lead_id: int) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM lead_history WHERE lead_id = ? ORDER BY id ASC",
            (lead_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def update_lead_status_row(
    lead_id: int, new_status: str, old_status: str, description: str
) -> None:
    """Update a lead's status and append a history row in one transaction."""
    with get_db() as conn:
        if new_status == "Converted":
            conn.execute(
                """UPDATE leads
                   SET status = ?, last_contacted_at = datetime('now'), converted_at = datetime('now')
                   WHERE id = ?""",
                (new_status, lead_id),
            )
        else:
            conn.execute(
                """UPDATE leads
                   SET status = ?, last_contacted_at = datetime('now')
                   WHERE id = ?""",
                (new_status, lead_id),
            )
        conn.execute(
            """INSERT INTO lead_history
               (lead_id, event_type, event_description, old_value, new_value)
               VALUES (?, 'status_change', ?, ?, ?)""",
            (lead_id, description, old_status, new_status),
        )


# ---------------------------------------------------------------------------
# Stats aggregation
# ---------------------------------------------------------------------------

def fetch_stats() -> Dict[str, Any]:
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM leads").fetchone()["c"]
        by_status = {
            r["status"]: r["c"]
            for r in conn.execute(
                "SELECT status, COUNT(*) AS c FROM leads GROUP BY status"
            ).fetchall()
        }
        by_source = {
            r["source"]: r["c"]
            for r in conn.execute(
                "SELECT source, COUNT(*) AS c FROM leads GROUP BY source"
            ).fetchall()
        }
        # Average time between lead creation and first status change (in minutes)
        avg_rows = conn.execute(
            """
            SELECT AVG((julianday(h.created_at) - julianday(l.created_at)) * 24 * 60) AS avg_min
            FROM leads l
            JOIN (
                SELECT lead_id, MIN(created_at) AS created_at
                FROM lead_history
                WHERE event_type = 'status_change'
                GROUP BY lead_id
            ) h ON h.lead_id = l.id
            """
        ).fetchall()
        avg_min = avg_rows[0]["avg_min"] if avg_rows and avg_rows[0]["avg_min"] is not None else 0.0
        converted = by_status.get("Converted", 0)
        conversion_rate = (converted / total * 100.0) if total else 0.0
    return {
        "total_leads": total,
        "by_status": by_status,
        "by_source": by_source,
        "average_response_time_minutes": round(avg_min, 2),
        "conversion_rate_percent": round(conversion_rate, 2),
    }


def fetch_recent_leads(limit: int = 10) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, status, source, created_at FROM leads ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

def insert_audit(
    tool_name: str,
    params: Dict[str, Any],
    used_groq: bool = False,
    used_fallback: bool = False,
    used_cache: bool = False,
    success: bool = True,
    error_message: str = "",
    duration_ms: int = 0,
) -> None:
    """Persist a single tool-call audit row. Failures here are swallowed —
    auditing must never break a tool call."""
    try:
        # Truncate params to avoid blowing up the column on huge CSV imports.
        params_json = json.dumps(params, default=str)
        if len(params_json) > 2000:
            params_json = params_json[:2000] + "...[truncated]"
        with get_db() as conn:
            conn.execute(
                """INSERT INTO audit_log
                   (tool_name, params, used_groq, used_fallback, used_cache,
                    success, error_message, duration_ms)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    tool_name,
                    params_json,
                    int(used_groq),
                    int(used_fallback),
                    int(used_cache),
                    int(success),
                    error_message,
                    duration_ms,
                ),
            )
    except Exception:
        pass  # audit must not break tool calls


def fetch_audit_summary(limit: int = 50) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def fetch_groq_usage_counts() -> Dict[str, int]:
    """Count of audit rows that used each path — useful for free-tier monitoring."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT
                SUM(used_groq)     AS groq_calls,
                SUM(used_fallback) AS fallback_calls,
                SUM(used_cache)    AS cache_hits,
                COUNT(*)           AS total_calls
            FROM audit_log
            WHERE tool_name IN ('classify_lead', 'add_lead', 'bulk_import_leads', 'suggest_next_action')
            """
        ).fetchone()
    return {
        "groq_calls": int(rows["groq_calls"] or 0),
        "fallback_calls": int(rows["fallback_calls"] or 0),
        "cache_hits": int(rows["cache_hits"] or 0),
        "total_tool_calls": int(rows["total_calls"] or 0),
    }


# ---------------------------------------------------------------------------
# Demo-mode reset
# ---------------------------------------------------------------------------

def maybe_reset_demo() -> bool:
    """If demo mode is on and the last reset was older than the interval,
    reset DB to seed data. Returns True if a reset occurred."""
    if not DEMO_MODE:
        return False
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'last_demo_reset'"
        ).fetchone()
        now = datetime.utcnow()
        if not row:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('last_demo_reset', ?)",
                (now.isoformat(),),
            )
            return True  # caller (seed_database) will populate
        try:
            last = datetime.fromisoformat(row["value"])
        except Exception:
            last = datetime.min
        if (now - last).total_seconds() > DEMO_RESET_INTERVAL_SEC:
            conn.execute(
                "UPDATE meta SET value = ? WHERE key = 'last_demo_reset'",
                (now.isoformat(),),
            )
            return True
        return False


def clear_all_leads() -> None:
    """Wipe leads + history (used by demo reset). Audit log is preserved so
    observability data survives across demo resets."""
    with get_db() as conn:
        conn.execute("DELETE FROM lead_history")
        conn.execute("DELETE FROM leads")
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('leads', 'lead_history')")
