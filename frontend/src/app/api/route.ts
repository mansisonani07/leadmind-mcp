import { NextResponse } from "next/server";
import { existsSync, readFileSync } from "fs";

/**
 * Next.js-side health endpoint.
 *
 * Reports the status of the Python backend as seen by the instrumentation
 * hook. Useful for debugging 502 errors on the published URL without
 * needing shell access to the container.
 *
 *   GET /api
 *   -> {
 *        "frontend": "ok",
 *        "backend_status": "running" | "starting" | "failed" | "unknown",
 *        "backend_detail": {...},
 *        "backend_pid": 12345,
 *        "timestamp": "..."
 *      }
 */
const STATUS_FILE = "/tmp/leadmind-backend-status.json";

type BackendStatus = {
  status: "starting" | "running" | "failed";
  pid?: number;
  detail?: unknown;
  ts?: string;
};

function readBackendStatus(): BackendStatus | null {
  try {
    if (!existsSync(STATUS_FILE)) return null;
    const raw = readFileSync(STATUS_FILE, "utf-8");
    return JSON.parse(raw) as BackendStatus;
  } catch {
    return null;
  }
}

export async function GET() {
  const status = readBackendStatus();
  return NextResponse.json({
    frontend: "ok",
    backend_status: status?.status ?? "unknown",
    backend_detail: status?.detail ?? null,
    backend_pid: status?.pid ?? null,
    backend_last_update: status?.ts ?? null,
    timestamp: new Date().toISOString(),
    hint:
      status?.status === "running"
        ? "Backend reports running. If you still see 502, check that port 8000 is actually listening."
        : status?.status === "failed"
        ? "Backend failed to start. See /tmp/leadmind-dashboard.log on the server."
        : "Backend status unknown. The instrumentation hook may not have run yet.",
  });
}
