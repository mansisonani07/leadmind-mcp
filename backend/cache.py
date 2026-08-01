"""
Thread-safe TTL cache for classification results.

Why: Groq's free tier has tight rate limits (~30 req/min on many plans).
Identical `classify_lead(text)` calls within a short window should not burn
quota. The cache also keeps bulk imports cheap when multiple similar messages
arrive (a common pattern in real CRM data).
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict
from typing import Any, Optional

from config import CACHE_MAX_ENTRIES, CACHE_TTL_SEC


class TTLCache:
    """In-memory LRU + TTL cache. One instance shared across the process."""

    def __init__(self, ttl_sec: int = CACHE_TTL_SEC, max_entries: int = CACHE_MAX_ENTRIES):
        self.ttl_sec = ttl_sec
        self.max_entries = max_entries
        self._store: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def make_key(text: str) -> str:
        """Stable, case-insensitive hash key. Trims whitespace so small
        formatting differences don't defeat the cache."""
        normalized = " ".join(text.strip().lower().split())
        return "cls:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        with self._lock:
            tup = self._store.get(key)
            if tup is None:
                self._misses += 1
                return None
            expires_at, value = tup
            if now >= expires_at:
                # expired — evict and treat as miss
                self._store.pop(key, None)
                self._misses += 1
                return None
            # mark as recently used
            self._store.move_to_end(key)
            self._hits += 1
            return value

    def set(self, key: str, value: Any) -> None:
        now = time.time()
        with self._lock:
            self._store[key] = (now + self.ttl_sec, value)
            self._store.move_to_end(key)
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)  # evict oldest

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict:
        with self._lock:
            return {
                "entries": len(self._store),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / max(1, self._hits + self._misses), 3),
            }


# Shared singleton — imported by groq_classifier and tools.py
cache = TTLCache()
