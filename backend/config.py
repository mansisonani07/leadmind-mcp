"""
Central configuration for LeadMind MCP.

All environment-driven settings live here so every module reads from one source
of truth. This keeps the free-tier constraints (no paid services, demo-safe
defaults) explicit and easy to audit.
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------------
BASE_DIR: Path = Path(__file__).resolve().parent
DB_PATH: Path = Path(os.getenv("LEADMIND_DB_PATH", str(BASE_DIR / "leadmind.db")))
GROQ_USAGE_LOG: Path = BASE_DIR / "groq_usage.log"

# ---------------------------------------------------------------------------
# Groq API (free tier — Llama-3.3-70b-versatile)
# ---------------------------------------------------------------------------
# Get a free key at https://console.groq.com/keys
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_API_URL: str = "https://api.groq.com/openai/v1/chat/completions"
GROQ_REQUEST_TIMEOUT_SEC: int = 20

# ---------------------------------------------------------------------------
# Authentication (optional — for SSE transport / public deployment)
# ---------------------------------------------------------------------------
# When LEADMIND_AUTH_ENABLED=true, incoming MCP requests must carry
# `Authorization: Bearer <LEADMIND_API_KEY>`. For stdio (Claude Desktop)
# this is typically disabled because the transport is local.
LEADMIND_API_KEY: str = os.getenv("LEADMIND_API_KEY", "demo-key-please-change")
LEADMIND_AUTH_ENABLED: bool = os.getenv("LEADMIND_AUTH_ENABLED", "false").lower() == "true"

# ---------------------------------------------------------------------------
# Response cache
# ---------------------------------------------------------------------------
# 5-minute TTL keeps identical classify_lead(text) calls free.
CACHE_TTL_SEC: int = int(os.getenv("CACHE_TTL_SEC", "300"))
CACHE_MAX_ENTRIES: int = int(os.getenv("CACHE_MAX_ENTRIES", "500"))

# ---------------------------------------------------------------------------
# Demo mode — keeps the public GitHub demo populated & self-healing
# ---------------------------------------------------------------------------
# When true, the DB is reset to seed data every DEMO_RESET_INTERVAL_SEC seconds
# so repeated public testing never corrupts or empties the dataset.
DEMO_MODE: bool = os.getenv("DEMO_MODE", "true").lower() == "true"
DEMO_RESET_INTERVAL_SEC: int = int(os.getenv("DEMO_RESET_INTERVAL_SEC", str(6 * 60 * 60)))  # 6h

# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------
MCP_TRANSPORT: str = os.getenv("MCP_TRANSPORT", "stdio").lower()  # "stdio" | "sse"
MCP_PORT: int = int(os.getenv("MCP_PORT", "8080"))

# ---------------------------------------------------------------------------
# Optional integrations
# ---------------------------------------------------------------------------
N8N_WEBHOOK_URL: str = os.getenv("N8N_WEBHOOK_URL", "")  # outbound n8n trigger (optional)
GMAIL_NOTIFY_TO: str = os.getenv("GMAIL_NOTIFY_TO", "")  # optional Gmail notification target
