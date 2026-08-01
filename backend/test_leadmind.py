"""
End-to-end test for LeadMind MCP.

Runs every tool, resource, and prompt directly (bypassing the MCP transport
layer) to verify the full pipeline works without a Groq API key configured.

Usage:
    python test_leadmind.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Force fallback mode (no Groq key) to test the reliability chain
os.environ.pop("GROQ_API_KEY", None)

from db import init_db  # noqa: E402
from seed_data import seed_database  # noqa: E402
from cache import cache  # noqa: E402
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
from groq_classifier import get_usage_snapshot  # noqa: E402


def _print(title: str, payload) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print("=" * 70)
    if isinstance(payload, (dict, list)):
        print(json.dumps(payload, indent=2, default=str)[:2000])
    else:
        print(str(payload)[:2000])


def main() -> int:
    failures = 0

    # Fresh DB
    if os.path.exists("leadmind.db"):
        os.remove("leadmind.db")
    if os.path.exists("groq_usage.log"):
        os.remove("groq_usage.log")
    cache.clear()

    init_db()
    seed_database(force=False)
    print("Seeded DB with demo leads.")

    # --- 1. get_leads ---
    try:
        all_leads = get_leads()
        _print("1. get_leads() — all leads", {"count": all_leads["count"]})
        assert all_leads["count"] >= 18, f"Expected >=18 leads, got {all_leads['count']}"

        hot_leads = get_leads(status="Hot")
        _print("1b. get_leads(status='Hot')", {"count": hot_leads["count"]})
        assert hot_leads["count"] > 0
        assert all(l["status"] == "Hot" for l in hot_leads["leads"])
        print("  PASS")
    except Exception as e:
        failures += 1
        print(f"  FAIL: {e}")

    # --- 2. classify_lead (with cache hit on second call) ---
    try:
        text = "We need a CRM urgently, budget approved, ready to sign this week."
        r1 = classify_lead(text)
        _print("2. classify_lead(text) — first call (fallback)", r1)
        assert r1["source"] in ("fallback", "groq", "cache")
        assert r1["status"] in ("Hot", "Warm", "Cold")

        r2 = classify_lead(text)
        _print("2b. classify_lead(text) — second call (cache hit)", r2)
        assert r2["source"] == "cache", f"Expected cache hit, got source={r2['source']}"
        print("  PASS — cache hit confirmed")
    except Exception as e:
        failures += 1
        print(f"  FAIL: {e}")

    # --- 3. add_lead ---
    try:
        new_lead = add_lead(
            name="Test Lead",
            contact_info="test@example.com",
            message="Just looking around, maybe next year, no rush.",
            source="Test",
        )
        _print("3. add_lead(...) — should be Cold", new_lead)
        assert new_lead["status"] == "Cold", f"Expected Cold, got {new_lead['status']}"
        new_lead_id = new_lead["id"]
        print("  PASS")
    except Exception as e:
        failures += 1
        print(f"  FAIL: {e}")
        new_lead_id = None

    # --- 4. update_lead_status ---
    if new_lead_id:
        try:
            upd = update_lead_status(id=new_lead_id, status="Converted")
            _print("4. update_lead_status(id, 'Converted')", upd)
            assert upd["new_status"] == "Converted"
            print("  PASS")
        except Exception as e:
            failures += 1
            print(f"  FAIL: {e}")

    # --- 5. get_lead_stats ---
    try:
        stats = get_lead_stats()
        _print("5. get_lead_stats()", stats)
        assert stats["total_leads"] >= 19  # 18 seed + 1 added
        assert "groq_usage" in stats
        print("  PASS")
    except Exception as e:
        failures += 1
        print(f"  FAIL: {e}")

    # --- 6. get_lead_history ---
    if new_lead_id:
        try:
            history = get_lead_history(id=new_lead_id)
            _print("6. get_lead_history(id)", {
                "lead_name": history["lead"]["name"],
                "history_count": len(history["history"]),
                "events": [h["event_type"] for h in history["history"]],
            })
            assert len(history["history"]) >= 3  # created, classified, status_change
            print("  PASS")
        except Exception as e:
            failures += 1
            print(f"  FAIL: {e}")

    # --- 7. suggest_next_action ---
    if new_lead_id:
        try:
            # Update back to Hot so suggestion logic kicks in
            update_lead_status(id=new_lead_id, status="Hot")
            suggestion = suggest_next_action(id=new_lead_id)
            _print("7. suggest_next_action(id)", suggestion)
            assert "suggestion" in suggestion
            assert suggestion["source"] in ("groq", "fallback")
            print("  PASS")
        except Exception as e:
            failures += 1
            print(f"  FAIL: {e}")

    # --- 8. bulk_import_leads ---
    try:
        csv_data = (
            "name,contact_info,message,source\n"
            "Bulk One,bulk1@example.com,\"Need this ASAP, budget approved, sign today\",CSV Import\n"
            "Bulk Two,bulk2@example.com,\"Just browsing, maybe next year\",CSV Import\n"
            "Bulk Three,bulk3@example.com,\"Evaluating vendors, send pricing\",CSV Import\n"
        )
        result = bulk_import_leads(csv_data=csv_data)
        _print("8. bulk_import_leads(csv_data)", {
            "imported": result["imported"],
            "errors": result["errors"],
            "statuses": [{"name": l["name"], "status": l["status"]} for l in result["leads"]],
        })
        assert result["imported"] == 3
        print("  PASS")
    except Exception as e:
        failures += 1
        print(f"  FAIL: {e}")

    # --- Resources & Prompts (call functions directly) ---
    try:
        # Import after server module loads (it imports tools, etc.)
        import mcp_server  # noqa: F401
        # FastMCP stores resources/prompts internally; we test by calling the
        # decorated functions directly through the module's namespace.
        dashboard = mcp_server.dashboard_resource()
        _print("Resource: leads://dashboard", dashboard)
        assert "Total Leads" in dashboard
        assert "Groq calls" in dashboard

        prompt = mcp_server.weekly_lead_review()
        _print("Prompt: weekly_lead_review", prompt)
        assert "Pipeline Overview" in prompt
        assert "Recommended Actions" in prompt

        audit_text = mcp_server.audit_resource()
        _print("Resource: audit://recent", audit_text)
        assert "Recent Tool Calls" in audit_text
        print("  PASS — resources + prompt templates work")
    except Exception as e:
        failures += 1
        print(f"  FAIL: {e}")

    # --- Usage snapshot ---
    _print("Groq usage snapshot", get_usage_snapshot())

    # --- Summary ---
    print(f"\n{'=' * 70}")
    if failures == 0:
        print(f"  ALL TESTS PASSED")
    else:
        print(f"  {failures} TEST(S) FAILED")
    print("=" * 70)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
