import { NextRequest, NextResponse } from "next/server";

/**
 * Catch-all proxy: forwards /api/leadmind/* to the Python FastAPI backend
 * on port 8000. The Caddy gateway requires us to specify the backend port
 * via the XTransformPort query parameter.
 *
 * Example: GET /api/leadmind/leads?status=Hot
 *   -> proxied to http://localhost:8000/leads?status=Hot&XTransformPort=8000
 */
const BACKEND_PORT = "8000";

export async function GET(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxy(req, params);
}

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxy(req, params);
}

export async function PATCH(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxy(req, params);
}

export async function PUT(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxy(req, params);
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  return proxy(req, params);
}

async function proxy(
  req: NextRequest,
  paramsPromise: Promise<{ path: string[] }>
) {
  const { path: pathSegments } = await paramsPromise;
  const path = pathSegments.join("/");

  // Build the target URL on localhost with the XTransformPort query
  // so the Caddy gateway forwards to port 8000.
  const incomingUrl = new URL(req.url);
  const targetUrl = new URL(`http://localhost/${path}`);
  targetUrl.searchParams.set("XTransformPort", BACKEND_PORT);
  // Copy through any existing query params (e.g. ?status=Hot)
  incomingUrl.searchParams.forEach((value, key) => {
    if (key !== "XTransformPort") {
      targetUrl.searchParams.set(key, value);
    }
  });

  // Forward the body (if any)
  let body: BodyInit | undefined = undefined;
  const method = req.method;
  if (method !== "GET" && method !== "HEAD") {
    body = await req.text();
  }

  // Forward headers, but strip hop-by-hop ones
  const headers = new Headers();
  const skipHeaders = new Set([
    "host",
    "connection",
    "content-length",
    "transfer-encoding",
    "keep-alive",
  ]);
  req.headers.forEach((value, key) => {
    if (!skipHeaders.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  });

  try {
    const upstream = await fetch(targetUrl, {
      method,
      headers,
      body,
      // Don't follow redirects — pass them through
      redirect: "manual",
    });

    // Copy the response back
    const responseHeaders = new Headers();
    upstream.headers.forEach((value, key) => {
      // Skip transfer-encoding since Next will set its own
      if (key.toLowerCase() !== "transfer-encoding" && key.toLowerCase() !== "content-length") {
        responseHeaders.set(key, value);
      }
    });

    const responseBody = await upstream.arrayBuffer();
    return new NextResponse(responseBody, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json(
      {
        error: "Failed to reach LeadMind backend on port 8000",
        detail: message,
        hint: "Make sure the Python api_server.py is running: cd leadmind-mcp && python api_server.py",
      },
      { status: 502 }
    );
  }
}
