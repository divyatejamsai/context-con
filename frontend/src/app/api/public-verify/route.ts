import { NextRequest } from "next/server";
import { BACKEND_URL } from "@/lib/auth";

export const dynamic = "force-dynamic";

// Public, no session: the receiving end of an agent's message checks its seal (backend app/agents/seal.py).
export async function GET(req: NextRequest) {
  const id = (req.nextUrl.searchParams.get("id") || "").replace(/[^a-f0-9]/g, "");
  return forward(`${BACKEND_URL}/api/verify/${id}`, { method: "GET" });
}

export async function POST(req: NextRequest) {
  const body = await req.text();
  return forward(`${BACKEND_URL}/api/verify`, { method: "POST", body, headers: { "content-type": "application/json" } });
}

async function forward(url: string, init: RequestInit) {
  try {
    const r = await fetch(url, { ...init, cache: "no-store" });
    return new Response(await r.text(), { status: r.status, headers: { "content-type": "application/json" } });
  } catch {
    return Response.json({ verdict: "unconfirmed", headline: "Agaxes can't be reached right now. Try again shortly.", checks: [] }, { status: 503 });
  }
}
