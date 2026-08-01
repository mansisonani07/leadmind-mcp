"""
Groq-powered lead classifier with caching + rule-based fallback.

Reliability chain (called from `classify_lead`):
    1. Check TTL cache         ->  return cached result (source: "cache")
    2. Call Groq API           ->  return LLM result   (source: "groq")
    3. On 429 / timeout / err  ->  fallback classifier (source: "fallback")

Every Groq call is counted and logged to groq_usage.log so the operator can
monitor free-tier consumption at a glance.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from typing import Dict, List

import requests

from cache import cache
from config import (
    GROQ_API_KEY,
    GROQ_API_URL,
    GROQ_MODEL,
    GROQ_REQUEST_TIMEOUT_SEC,
    GROQ_USAGE_LOG,
)
from fallback_classifier import classify as fallback_classify
from fallback_classifier import suggest_next_action as fallback_suggest

logger = logging.getLogger("leadmind.groq")

# ---------------------------------------------------------------------------
# In-process usage counter (per server lifetime; persisted to log file)
# ---------------------------------------------------------------------------
_groq_call_count = 0
_groq_call_count_lock = threading.Lock()


def get_call_count() -> int:
    with _groq_call_count_lock:
        return _groq_call_count


def _bump_call_count() -> None:
    global _groq_call_count
    with _groq_call_count_lock:
        _groq_call_count += 1


def _log_usage(status: str, detail: str = "") -> None:
    """Append a single line to groq_usage.log for offline monitoring."""
    try:
        with open(GROQ_USAGE_LOG, "a", encoding="utf-8") as f:
            f.write(
                f"{datetime.utcnow().isoformat()}Z\t{status}\t{detail}\n"
            )
    except Exception:
        pass  # logging must never break the request


class GroqRateLimitError(Exception):
    """Raised when Groq returns 429 — triggers the fallback path."""


# ---------------------------------------------------------------------------
# Classification prompts
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM_PROMPT = (
    "You are a lead-scoring assistant for a B2B SaaS CRM. "
    "Classify the incoming lead message into exactly one of: Hot, Warm, Cold.\n"
    "Definitions:\n"
    "  Hot   = urgent language, budget mentioned, decision-ready, near-term purchase intent.\n"
    "  Warm  = interested and evaluating, but no urgency or committed timeline.\n"
    "  Cold  = passive, future-only, browsing, no commitment signals.\n"
    "Return STRICT JSON with keys:\n"
    '  {"status": "Hot|Warm|Cold", "confidence": 0.0-1.0, "reasoning": "one short sentence"}\n'
    "The reasoning MUST start with the chosen status word (e.g. 'Hot because ...'). "
    "Keep reasoning under 25 words. Do not include any text outside the JSON object."
)


def _build_classify_messages(text: str) -> list:
    return [
        {"role": "system", "content": _CLASSIFY_SYSTEM_PROMPT},
        {"role": "user", "content": f'Lead message:\n"""\n{text}\n"""'},
    ]


def _build_next_action_messages(lead: dict, history: list) -> list:
    history_lines: List[str] = []
    for h in (history or [])[-10:]:
        history_lines.append(
            f"- {h.get('created_at','?')} [{h.get('event_type','?')}] "
            f"{h.get('event_description','') or ''}".rstrip()
        )
    history_text = "\n".join(history_lines) or "(no prior history)"
    return [
        {
            "role": "system",
            "content": (
                "You are a senior sales development representative. Given a lead's data and "
                "interaction history, recommend ONE specific next action in 1-2 sentences. "
                "Be concrete: name the channel (call/email/LinkedIn), the goal, and the timing. "
                "Do not invent facts not present in the lead data."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Lead: {lead.get('name','?')} (status: {lead.get('status','?')}, "
                f"source: {lead.get('source','?')})\n"
                f"Message: \"{lead.get('message','')}\"\n"
                f"Created: {lead.get('created_at','?')}\n"
                f"Last contacted: {lead.get('last_contacted_at','never')}\n\n"
                f"Recent history:\n{history_text}\n\n"
                "Recommended next action:"
            ),
        },
    ]


# ---------------------------------------------------------------------------
# Low-level Groq call
# ---------------------------------------------------------------------------

def _call_groq_chat(messages: list, temperature: float, max_tokens: int, json_mode: bool) -> str:
    """Single Groq chat completion. Returns the assistant message content.
    Raises GroqRateLimitError on 429, otherwise raises for HTTP errors."""
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload: dict = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    resp = requests.post(
        GROQ_API_URL,
        headers=headers,
        json=payload,
        timeout=GROQ_REQUEST_TIMEOUT_SEC,
    )
    if resp.status_code == 429:
        raise GroqRateLimitError("Groq free-tier rate limit hit (429).")
    if resp.status_code >= 400:
        # Surface the body so debugging is easier
        raise RuntimeError(f"Groq HTTP {resp.status_code}: {resp.text[:300]}")
    resp.raise_for_status()
    _bump_call_count()
    return resp.json()["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_lead(text: str) -> Dict[str, object]:
    """
    Classify a lead message with caching + Groq + fallback chain.

    Returns a dict with keys: status, confidence, reasoning, source
    (and optionally `keywords` when the fallback path was used).
    """
    if not text or not text.strip():
        return {
            "status": "Warm",
            "confidence": 0.30,
            "reasoning": "Empty message — defaulting to Warm.",
            "source": "fallback",
        }

    cache_key = cache.make_key(text)
    cached = cache.get(cache_key)
    if cached is not None:
        # Mark that this came from cache so audit + UI can show it.
        cached = dict(cached)
        cached["source"] = "cache"
        return cached

    # No key configured -> straight to fallback (zero-config local dev)
    if not GROQ_API_KEY:
        result = fallback_classify(text)
        cache.set(cache_key, result)
        return result

    try:
        content = _call_groq_chat(
            messages=_build_classify_messages(text),
            temperature=0.2,
            max_tokens=200,
            json_mode=True,
        )
        _log_usage("success", "classify")
        parsed = json.loads(content)
        # Normalize + validate
        status = str(parsed.get("status", "Warm")).strip().capitalize()
        if status not in ("Hot", "Warm", "Cold"):
            status = "Warm"
        try:
            confidence = float(parsed.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))
        reasoning = str(parsed.get("reasoning", f"{status} (classified by Groq LLM).")).strip()
        if not reasoning.lower().startswith(status.lower()):
            reasoning = f"{status} because {reasoning}"
        result = {
            "status": status,
            "confidence": round(confidence, 2),
            "reasoning": reasoning,
            "source": "groq",
        }
        cache.set(cache_key, result)
        return result

    except GroqRateLimitError as e:
        _log_usage("rate_limited", str(e))
        logger.warning("Groq rate-limited; falling back to rule-based classifier.")
        result = fallback_classify(text)
        cache.set(cache_key, result)
        return result

    except Exception as e:
        _log_usage("error", f"classify: {e}")
        logger.warning("Groq classify failed (%s); falling back.", e)
        result = fallback_classify(text)
        cache.set(cache_key, result)
        return result


def suggest_next_action(lead: dict, history: list) -> Dict[str, str]:
    """Generate an AI next-action suggestion, with rule-based fallback."""
    if not GROQ_API_KEY:
        return fallback_suggest(lead, history)

    try:
        content = _call_groq_chat(
            messages=_build_next_action_messages(lead, history),
            temperature=0.4,
            max_tokens=250,
            json_mode=False,
        )
        _log_usage("success", "suggest_next_action")
        suggestion = content.strip()
        if not suggestion:
            return fallback_suggest(lead, history)
        return {"suggestion": suggestion, "source": "groq"}
    except GroqRateLimitError as e:
        _log_usage("rate_limited", f"suggest: {e}")
        logger.warning("Groq rate-limited; falling back to rule-based suggestion.")
        return fallback_suggest(lead, history)
    except Exception as e:
        _log_usage("error", f"suggest: {e}")
        logger.warning("Groq suggest failed (%s); falling back.", e)
        return fallback_suggest(lead, history)


def get_usage_snapshot() -> dict:
    """Combined in-memory + on-disk usage snapshot for monitoring."""
    in_memory = get_call_count()
    disk_lines = 0
    success = 0
    rate_limited = 0
    errors = 0
    try:
        if GROQ_USAGE_LOG.exists():
            with open(GROQ_USAGE_LOG, "r", encoding="utf-8") as f:
                for line in f:
                    disk_lines += 1
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        if parts[1] == "success":
                            success += 1
                        elif parts[1] == "rate_limited":
                            rate_limited += 1
                        elif parts[1] == "error":
                            errors += 1
    except Exception:
        pass
    return {
        "in_memory_calls_this_session": in_memory,
        "total_logged_calls": disk_lines,
        "logged_success": success,
        "logged_rate_limited": rate_limited,
        "logged_errors": errors,
    }
