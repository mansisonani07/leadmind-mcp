import { redirect } from "next/navigation";
import { existsSync, readFileSync } from "fs";

/**
 * The LeadMind dashboard is served by the Python FastAPI app
 * (leadmind-mcp/web_dashboard.py) on port 8000.
 *
 * Routing chain:
 *   1. This route checks the backend status file. If the backend is
 *      "failed", render a diagnostic page explaining the situation.
 *   2. Otherwise, return a 307 redirect to /?XTransformPort=8000.
 *   3. The Caddy gateway sees the XTransformPort query param and proxies
 *      the request to localhost:8000 (the Python backend).
 *   4. The Python backend serves the dashboard HTML at /.
 *
 * `force-dynamic` is required because we read the filesystem at runtime
 * to decide which branch to render. Without it, Next.js would statically
 * prerender only the redirect branch at build time.
 */
export const dynamic = "force-dynamic";
export const revalidate = 0;

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

export default function Home() {
  const status = readBackendStatus();
  // Only render the diagnostic page if we KNOW the backend failed.
  // In all other cases (starting, running, unknown), proceed with the
  // redirect so the normal flow works.
  if (status?.status === "failed") {
    return (
      <main
        style={{
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
          maxWidth: 720,
          margin: "80px auto",
          padding: "0 24px",
          color: "#0f172a",
          lineHeight: 1.6,
        }}
      >
        <h1 style={{ fontSize: 28, marginBottom: 8, fontWeight: 600 }}>
          LeadMind dashboard backend is not running
        </h1>
        <p style={{ color: "#475569", marginBottom: 24 }}>
          The Next.js frontend loaded successfully, but the Python FastAPI
          backend that serves the dashboard UI and the API could not be
          started on this server.
        </p>
        <div
          style={{
            background: "#f8fafc",
            border: "1px solid #e2e8f0",
            borderRadius: 8,
            padding: 16,
            marginBottom: 24,
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            fontSize: 13,
            whiteSpace: "pre-wrap",
            overflowX: "auto",
          }}
        >
          {`status: ${status.status}\ndetail: ${JSON.stringify(status.detail, null, 2)}\ntimestamp: ${status.ts ?? "unknown"}`}
        </div>
        <h2 style={{ fontSize: 18, marginTop: 32, marginBottom: 12 }}>
          What this means
        </h2>
        <p style={{ color: "#475569", marginBottom: 12 }}>
          The Space-Z <strong>Publish</strong> feature deploys the Next.js
          standalone build, but the Python backend (<code>web_dashboard.py</code>)
          must be spawned as a child process by the Next.js{" "}
          <code>instrumentation.ts</code> hook. The hook reported a failure
          when trying to start Python.
        </p>
        <p style={{ color: "#475569", marginBottom: 12 }}>
          Common causes:
        </p>
        <ul style={{ color: "#475569", paddingLeft: 20, marginBottom: 24 }}>
          <li>The publish container does not have Python 3 installed.</li>
          <li>
            The publish container has Python but is missing FastAPI / uvicorn
            and the runtime <code>pip install</code> fallback also failed.
          </li>
          <li>
            The <code>leadmind-mcp/</code> directory was not bundled into the
            standalone build.
          </li>
        </ul>
        <h2 style={{ fontSize: 18, marginTop: 32, marginBottom: 12 }}>
          How to fix
        </h2>
        <p style={{ color: "#475569", marginBottom: 12 }}>Two options:</p>
        <ol style={{ color: "#475569", paddingLeft: 20, marginBottom: 24 }}>
          <li>
            <strong>Re-deploy elsewhere.</strong> Run the Python app on a
            host that supports Python + SQLite natively (Render, Railway,
            Fly.io, a small VPS). The LeadMind codebase is a single-file
            FastAPI app — see <code>leadmind-mcp/README.md</code> for
            one-command deployment instructions.
          </li>
          <li>
            <strong>Contact the platform team.</strong> Ask whether the
            Space-Z publish container supports spawning Python child
            processes, or whether only Next.js / static sites are
            supported.
          </li>
        </ol>
        <p style={{ color: "#94a3b8", fontSize: 12, marginTop: 32 }}>
          Status file: <code>/tmp/leadmind-backend-status.json</code> &middot;
          Backend log: <code>/tmp/leadmind-dashboard.log</code>
        </p>
      </main>
    );
  }
  redirect("/?XTransformPort=8000");
}
