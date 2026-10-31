import { NextRequest, NextResponse } from "next/server";
import { BACKEND_URL, SESSION_COOKIE } from "@/lib/auth";

export const dynamic = "force-dynamic";

// Proxies /api/auth/* to the FastAPI backend and keeps the session token in an httpOnly cookie,
// so browser JavaScript never sees it.
const POST_ACTIONS = new Set(["lookup", "signup", "login", "demo", "logout", "forgot", "reset"]);
const GET_ACTIONS = new Set(["me", "options"]);

async function forward(path: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(`${BACKEND_URL}/api/auth/${path}`, { ...init, cache: "no-store" });
  } catch {
    return Response.json(
      { error: "backend_unreachable", message: `Can't reach the Sourced backend at ${BACKEND_URL}. Is it running?` },
      { status: 503 },
    );
  }
}

function withSession(res: NextResponse, token: string, expiresAt: string, req: NextRequest) {
  res.cookies.set(SESSION_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: req.nextUrl.protocol === "https:",
    path: "/",
    expires: new Date(expiresAt),
  });
  return res;
}

export async function POST(req: NextRequest, { params }: { params: Promise<{ action: string }> }) {
  const { action } = await params;
  if (!POST_ACTIONS.has(action)) return NextResponse.json({ error: "not_found" }, { status: 404 });
  const token = req.cookies.get(SESSION_COOKIE)?.value;

  if (action === "logout") {
    if (token) await forward("logout", { method: "POST", headers: { Authorization: `Bearer ${token}` } });
    const res = NextResponse.json({ ok: true });
    res.cookies.delete(SESSION_COOKIE);
    return res;
  }

  const body = action === "demo" ? "{}" : await req.text();
  const upstream = await forward(action, {
    method: "POST",
    headers: { "Content-Type": "application/json", "User-Agent": req.headers.get("user-agent") || "" },
    body,
  });
  const data = await upstream.json().catch(() => ({ error: "bad_response", message: "Unexpected reply from the backend." }));

  if (upstream.ok && data.token) {
    const { token: t, expires_at, ...rest } = data;
    return withSession(NextResponse.json(rest), t, expires_at, req);
  }
  return NextResponse.json(data, { status: upstream.status });
}

export async function GET(req: NextRequest, { params }: { params: Promise<{ action: string }> }) {
  const { action } = await params;
  if (!GET_ACTIONS.has(action)) return NextResponse.json({ error: "not_found" }, { status: 404 });
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  const upstream = await forward(action, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  const data = await upstream.json().catch(() => ({}));
  return NextResponse.json(data, { status: upstream.status });
}
