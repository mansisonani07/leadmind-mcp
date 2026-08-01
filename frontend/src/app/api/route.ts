import { NextRequest, NextResponse } from "next/server";

/**
 * Catch-all proxy: forwards /api/leadmind/* to the Python FastAPI backend
 * on port 8000. Connects directly to localhost:8000.
 *
 * Example: GET /api/leadmind/leads?status=Hot
 *   -> proxied to http://localhost:8000/api/leads?status=Hot
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

  const incomingUrl = new URL(req.url);
  const targetUrl = new URL(`http://localhost:${BACKEND_PORT}/api/${path}`);
  incomingUrl.searchParams.forEach((value, key) => {
    if (key !== "XTransformPort") {
      targetUrl.searchParams.set(key, value);
    }
  });

  let body: BodyInit | undefined = undefined;
  const method = req.method;
  if (method !== "GET" && method !== "HEAD") {
    body = await req.text();
  }

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
      redirect: "manual",
    });

    const responseHeaders = new Headers();
    upstream.headers.forEach((value, key) => {
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
        hint: "Make sure the Python web_dashboard.py is running: cd leadmind-mcp && python web_dashboard.py",
      },
      { status: 502 }
    );
  }
}
