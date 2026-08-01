import { NextRequest, NextResponse } from "next/server";

/**
 * Catch-all proxy: forwards /api/leadmind/* to the external Python backend.
 * Uses NEXT_PUBLIC_BACKEND_URL (client) or BACKEND_URL (server) env var.
 */
const BACKEND_URL = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

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
  const targetUrl = new URL(`${BACKEND_URL}/${path}`);
  incomingUrl.searchParams.forEach((value, key) => {
    targetUrl.searchParams.set(key, value);
  });

  let body: BodyInit | undefined = undefined;
  const method = req.method;
  if (method !== "GET" && method !== "HEAD") {
    body = await req.text();
  }

  const headers = new Headers();
  const skipHeaders = new Set(["host", "connection", "content-length", "transfer-encoding", "keep-alive"]);
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
        error: "Failed to reach LeadMind backend",
        detail: message,
        hint: `Backend URL: ${BACKEND_URL}`,
      },
      { status: 502 }
    );
  }
}
