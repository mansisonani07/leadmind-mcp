import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  /* config options here */
  typescript: {
    ignoreBuildErrors: true,
  },
  reactStrictMode: false,
  // The instrumentation.ts file (at src/instrumentation.ts) is automatically
  // detected by Next.js 16 — no experimental flag needed. It runs on server
  // startup and spawns the LeadMind Python dashboard as a child process.
  //
  // Exclude the bundled Python backend from Turbopack's output file tracing
  // so it doesn't try to resolve .venv symlinks (which are absolute and
  // would panic the bundler). The leadmind-mcp/ directory is copied into
  // .next/standalone/ by the `build` script in package.json after the
  // Next.js build completes — Turbopack doesn't need to trace it.
  outputFileTracingExcludes: ["leadmind-mcp/**/*"],
};

export default nextConfig;
