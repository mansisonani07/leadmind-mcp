.PHONY: help install test run run-sse run-webhook clean demo

help:
	@echo "LeadMind MCP — available commands:"
	@echo ""
	@echo "  make install     — create venv + install dependencies"
	@echo "  make test        — run end-to-end Python tests (no Groq key needed)"
	@echo "  make test-proto  — run real MCP protocol smoke test over stdio"
	@echo "  make run         — start MCP server on stdio (for Claude Desktop)"
	@echo "  make run-sse     — start MCP server on SSE (port 8080)"
	@echo "  make run-webhook — start FastAPI webhook receiver (port 8000)"
	@echo "  make clean       — remove DB, logs, venv"
	@echo "  make demo        — print the demo script location"

install:
	python3 -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt
	@echo ""
	@echo "Install complete. Next:"
	@echo "  cp .env.example .env   # and edit if needed"
	@echo "  make test              # verify everything works"
	@echo "  make run               # start the MCP server"

test:
	. .venv/bin/activate && python test_leadmind.py

test-proto:
	. .venv/bin/activate && python test_mcp_protocol.py

run:
	. .venv/bin/activate && python mcp_server.py

run-sse:
	MCP_TRANSPORT=sse MCP_PORT=8080 . .venv/bin/activate && python mcp_server.py

run-webhook:
	. .venv/bin/activate && python webhook_receiver.py

clean:
	rm -f leadmind.db groq_usage.log
	rm -rf .venv __pycache__ .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

demo:
	@echo "Demo script: demo_script.md"
	@echo "Open it to follow the example conversation flow."
