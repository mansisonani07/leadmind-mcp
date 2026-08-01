/**
 * Next.js instrumentation hook.
 * 
 * On Render, the Python backend runs as a separate service.
 * No child process spawning needed — this is a no-op.
 */

export async function register() {
  console.log("[leadmind] Instrumentation: running on external backend mode");
}
