import type { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const fetchCache = "force-no-store";

const BACKEND = process.env.FLARE_API_URL ?? "http://localhost:8000";

export async function GET(
  request: NextRequest,
  context: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await context.params;

  const upstream = await fetch(`${BACKEND}/api/v1/incidents/${id}/stream`, {
    headers: { accept: "text/event-stream", "accept-encoding": "identity" },
    signal: request.signal,
    cache: "no-store",
  });

  if (!upstream.ok || upstream.body === null) {
    return new Response(null, { status: upstream.status });
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      "x-accel-buffering": "no",
    },
  });
}