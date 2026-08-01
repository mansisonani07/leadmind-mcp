"""
Real MCP protocol smoke test.

Spawns mcp_server.py as a subprocess, speaks the MCP JSON-RPC protocol over
stdio, and verifies that:
  1. initialize handshake succeeds
  2. tools/list returns 8 tools
  3. resources/list returns 2 resources
  4. prompts/list returns 1 prompt
  5. tools/call works end-to-end (calls tool_get_leads and gets real data)
  6. resources/read works (reads leads://dashboard)
  7. prompts/get works (gets weekly_lead_review)

This proves the server is connectable from any MCP client, not just callable
as Python functions.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent


def send(proc: subprocess.Popen, msg: dict) -> None:
    line = json.dumps(msg) + "\n"
    proc.stdin.write(line)
    proc.stdin.flush()


def recv(proc: subprocess.Popen, timeout: float = 10.0) -> dict:
    """Read one JSON-RPC message. Lines that aren't valid JSON (log output
    on stderr) are skipped."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.05)
            continue
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            # could be log line on stdout — skip
            continue
    raise TimeoutError("Timed out waiting for MCP response")


def main() -> int:
    env = os.environ.copy()
    env.pop("GROQ_API_KEY", None)
    env["DEMO_MODE"] = "true"
    env["PYTHONUNBUFFERED"] = "1"

    # Clean DB before test
    db_path = PROJECT_DIR / "leadmind.db"
    if db_path.exists():
        db_path.unlink()

    proc = subprocess.Popen(
        [sys.executable, str(PROJECT_DIR / "mcp_server.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=str(PROJECT_DIR),
    )

    try:
        # 1. initialize
        send(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke-test", "version": "1.0"},
            },
        })
        init_resp = recv(proc)
        assert "result" in init_resp, f"No result in init: {init_resp}"
        print(f"[OK] initialize -> server={init_resp['result'].get('serverInfo', {}).get('name')}")

        # initialized notification (no response expected)
        send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        # 2. tools/list
        send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools_resp = recv(proc)
        tools = tools_resp["result"]["tools"]
        print(f"[OK] tools/list -> {len(tools)} tools: {[t['name'] for t in tools]}")
        assert len(tools) == 8

        # 3. resources/list
        send(proc, {"jsonrpc": "2.0", "id": 3, "method": "resources/list"})
        res_resp = recv(proc)
        resources = res_resp["result"]["resources"]
        print(f"[OK] resources/list -> {len(resources)} resources: {[r['uri'] for r in resources]}")
        assert len(resources) == 2

        # 4. prompts/list
        send(proc, {"jsonrpc": "2.0", "id": 4, "method": "prompts/list"})
        pr_resp = recv(proc)
        prompts = pr_resp["result"]["prompts"]
        print(f"[OK] prompts/list -> {len(prompts)} prompts: {[p['name'] for p in prompts]}")
        assert len(prompts) == 1

        # 5. tools/call — tool_get_leads(status="Hot")
        send(proc, {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "tool_get_leads",
                "arguments": {"status": "Hot"},
            },
        })
        call_resp = recv(proc)
        result = call_resp["result"]
        # Result is a list of content items; the text is JSON-encoded
        text_content = next(c["text"] for c in result["content"] if c["type"] == "text")
        parsed = json.loads(text_content)
        print(f"[OK] tools/call tool_get_leads(status='Hot') -> {parsed['count']} hot leads")
        assert parsed["count"] > 0
        assert all(l["status"] == "Hot" for l in parsed["leads"])

        # 6. resources/read — leads://dashboard
        send(proc, {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "resources/read",
            "params": {"uri": "leads://dashboard"},
        })
        rd_resp = recv(proc)
        contents = rd_resp["result"]["contents"]
        dashboard_text = contents[0]["text"]
        print(f"[OK] resources/read leads://dashboard -> {len(dashboard_text)} chars")
        assert "Total Leads" in dashboard_text
        assert "Groq calls" in dashboard_text

        # 7. prompts/get — weekly_lead_review
        send(proc, {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "prompts/get",
            "params": {"name": "weekly_lead_review"},
        })
        pg_resp = recv(proc)
        prompt_msgs = pg_resp["result"]["messages"]
        print(f"[OK] prompts/get weekly_lead_review -> {len(prompt_msgs)} message(s)")
        assert len(prompt_msgs) >= 1
        prompt_text = prompt_msgs[0]["content"]["text"]
        assert "Pipeline Overview" in prompt_text

        # 8. tools/call — tool_add_lead (exercises classify -> fallback chain)
        send(proc, {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "tool_add_lead",
                "arguments": {
                    "name": "Protocol Test Lead",
                    "contact_info": "proto@test.com",
                    "message": "We need this URGENTLY, budget approved, ready to sign today.",
                    "source": "Protocol Test",
                },
            },
        })
        add_resp = recv(proc)
        add_text = next(c["text"] for c in add_resp["result"]["content"] if c["type"] == "text")
        add_parsed = json.loads(add_text)
        print(f"[OK] tools/call tool_add_lead -> id={add_parsed['id']}, status={add_parsed['status']}")
        assert add_parsed["status"] == "Hot"

        print("\n=== ALL PROTOCOL TESTS PASSED ===")
        return 0

    except Exception as e:
        print(f"\n=== TEST FAILED: {e} ===")
        # Dump stderr for debugging
        try:
            err = proc.stderr.read() if proc.stderr else ""
            if err:
                print("\n--- server stderr ---")
                print(err[-3000:])
        except Exception:
            pass
        return 1
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
