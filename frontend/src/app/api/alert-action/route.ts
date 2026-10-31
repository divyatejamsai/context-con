import { NextRequest } from "next/server";
import { BACKEND_URL } from "@/lib/auth";

export const dynamic = "force-dynamic";

// Public, no session: the one-click Approve / Reject links in alert emails and Slack (backend app/alerts).
// The signed token in the link is the only credential. GET shows what it would do; only POST acts.
const clean = (t: string | null) => (t || "").replace(/[^A-Za-z0-9_.-]/g, "");

export async function GET(req: NextRequest) {
  return forward(`${BACKEND_URL}/api/alerts/action/${clean(req.nextUrl.searchParams.get("t"))}`, { method: "GET" });
}

export async function POST(req: NextRequest) {
  const origin = req.headers.get("origin");
  if (origin && origin !== req.nextUrl.origin) return Response.json({ detail: { code: "cross_origin", message: "Open the link itself to decide." } }, { status: 403 });
  const t = clean(req.nextUrl.searchParams.get("t"));
  return forward(`${BACKEND_URL}/api/alerts/action/${t}`, { method: "POST", body: await req.text(), headers: { "content-type": "application/json" } });
}

async function forward(url: string, init: RequestInit) {
  try {
    const r = await fetch(url, { ...init, cache: "no-store" });
    return new Response(await r.text(), { status: r.status, headers: { "content-type": "application/json" } });
  } catch {
    return Response.json({ detail: { code: "unreachable", message: "Agaxes can't be reached right now. Try again shortly." } }, { status: 503 });
  }
}
