/**
 * Next.js instrumentation hook — runs once when the Next.js server starts.
 *
 * Spawns the LeadMind Python dashboard (web_dashboard.py) as a child process
 * of Next.js.
 *
 * PLATFORM PYTHON SUPPORT
 * -----------------------
 * The Space-Z platform natively supports Python via:
 *   - .zscripts/python-runtime-build.sh: installs requirements.txt (at
 *     PROJECT ROOT) into /app/python-runtime/site-packages/ during build
 *   - .zscripts/start.sh: sets PYTHONPATH=/app/python-runtime/site-packages:/app/next-service-dist
 *     and PATH to include the python bin — so `import fastapi` just works
 *
 * So at runtime, the inherited environment already has Python + deps.
 * We just need to find web_dashboard.py and spawn it.
 *
 * PATH RESOLUTION
 * ---------------
 * In dev: process.cwd() = /home/z/my-project, so leadmind-mcp/ is at
 * <cwd>/leadmind-mcp/.
 *
 * In production: the platform copies .py files to /app/next-service-dist/
 * preserving relative paths, so web_dashboard.py is at
 * /app/next-service-dist/leadmind-mcp/web_dashboard.py. The Next.js
 * server runs from /app/next-service-dist/ (per start.sh line 72:
 * `cd next-service-dist/`), so process.cwd() = /app/next-service-dist/,
 * and leadmind-mcp/ is again at <cwd>/leadmind-mcp/.
 */

import { spawn } from "node:child_process";
import { existsSync, mkdirSync, createWriteStream, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const LOG_FILE = "/tmp/leadmind-dashboard.log";
const STATUS_FILE = "/tmp/leadmind-backend-status.json";

function findLeadmindRoot(): string | null {
  const candidates: string[] = [
    join(process.cwd(), "leadmind-mcp"),
    // Fallback: relative to this compiled file's location
    join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..", "leadmind-mcp"),
    // Dev container fallback
    "/home/z/my-project/leadmind-mcp",
    // Production fallback (platform copies .py here)
    "/app/next-service-dist/leadmind-mcp",
  ];
  for (const c of candidates) {
    if (existsSync(join(c, "web_dashboard.py"))) {
      return c;
    }
  }
  return null;
}

let started = false;
let childPid: number | null = null;

function writeStatus(status: "starting" | "running" | "failed", detail: unknown) {
  try {
    writeFileSync(
      STATUS_FILE,
      JSON.stringify(
        {
          status,
          pid: childPid,
          detail,
          ts: new Date().toISOString(),
          cwd: process.cwd(),
        },
        null,
        2
      )
    );
  } catch {
    // ignore — best-effort status file
  }
}

export async function register() {
  if (started) return;
  started = true;

  // Only run in the server runtime (not during build)
  if (process.env.NEXT_RUNTIME !== "nodejs") return;

  try {
    mkdirSync("/tmp", { recursive: true });
  } catch {
    // already exists
  }

  const logStream = createWriteStream(LOG_FILE, { flags: "a" });
  const log = (msg: string) => {
    const line = `[${new Date().toISOString()}] [leadmind] ${msg}\n`;
    logStream.write(line);
    console.log(msg);
  };

  log("=".repeat(60));
  log("Instrumentation hook: starting LeadMind Python backend");
  log(`process.cwd() = ${process.cwd()}`);
  log(`PYTHONPATH = ${process.env.PYTHONPATH ?? "(not set)"}`);
  log(`PATH includes python-runtime: ${(process.env.PATH ?? "").includes("python-runtime")}`);

  const leadmindRoot = findLeadmindRoot();
  if (!leadmindRoot) {
    log(
      "ERROR: could not find leadmind-mcp/web_dashboard.py. Tried: " +
        [
          join(process.cwd(), "leadmind-mcp"),
          "/home/z/my-project/leadmind-mcp",
          "/app/next-service-dist/leadmind-mcp",
        ].join(", ")
    );
    writeStatus("failed", "leadmind-mcp/web_dashboard.py not found");
    return;
  }
  log(`Found leadmind-mcp at: ${leadmindRoot}`);

  // The platform's start.sh already sets PYTHONPATH and PATH correctly.
  // We just spawn python (inherited env has the right paths).
  // In dev, we fall back to the venv python if `python` isn't on PATH.
  const pythonCmd = "python3";
  log(`Using Python: ${pythonCmd} (from PATH, set by platform's start.sh)`);

  try {
    // Inherit process.env — this carries the platform's PYTHONPATH/PATH
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      DEMO_MODE: "true",
      DEMO_RESET_INTERVAL_SEC: "14400", // 4 hours
      PORT: "8000",
      PYTHONUNBUFFERED: "1",
    };

    const child = spawn(pythonCmd, ["-u", "web_dashboard.py"], {
      cwd: leadmindRoot,
      env,
      stdio: ["ignore", "pipe", "pipe"],
      detached: false,
    });
    childPid = child.pid;

    child.stdout?.pipe(logStream);
    child.stderr?.pipe(logStream);

    child.on("error", (err: Error) => {
      log(`Failed to spawn web_dashboard.py: ${err.message}`);
      writeStatus("failed", `spawn error: ${err.message}`);
    });

    child.on("exit", (code: number | null, signal: NodeJS.Signals | null) => {
      log(`web_dashboard.py exited (code=${code}, signal=${signal}). Restarting in 3s...`);
      writeStatus("failed", `exited code=${code} signal=${signal}`);
      setTimeout(() => {
        started = false;
        childPid = null;
        register();
      }, 3000);
    });

    log(`web_dashboard.py spawned as PID ${child.pid}`);
    writeStatus("running", {
      pid: child.pid,
      python: pythonCmd,
      cwd: leadmindRoot,
      pythonpath: process.env.PYTHONPATH ?? "(inherited)",
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    log(`Instrumentation hook error: ${msg}`);
    writeStatus("failed", msg);
  }
}
