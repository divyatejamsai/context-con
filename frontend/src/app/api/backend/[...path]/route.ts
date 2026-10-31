import { NextRequest } from "next/server";
import { BACKEND_URL, SESSION_COOKIE } from "@/lib/auth";

export const dynamic = "force-dynamic";

// Same-origin proxy to the FastAPI backend that adds the signed-in user's session (from the httpOnly cookie) as
// Authorization: Bearer, so the console can call Agaxes as that user and only sees their workspace. Point the
// console's API base at "/api/backend" to use it. Streams responses (SSE) through unchanged.
// Auth routes are not proxied here (they would hand the session token to browser JavaScript): use /api/auth/*.
const HOP = new Set(["host", "connection", "content-length", "cookie", "authorization", "accept-encoding"]);

async function proxy(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  const { path } = await params;
  if (!path?.length || path[0] === "auth") return Response.json({ error: "not_found" }, { status: 404 });
  const origin = req.headers.get("origin");
  if (origin && origin !== req.nextUrl.origin) return Response.json({ error: "cross_origin" }, { status: 403 });

  const headers = new Headers();
  req.headers.forEach((v, k) => { if (!HOP.has(k.toLowerCase())) headers.set(k, v); });
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const url = `${BACKEND_URL}/api/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const hasBody = !["GET", "HEAD"].includes(req.method);
  try {
    const res = await fetch(url, {
      method: req.method, headers, cache: "no-store", redirect: "manual",
      body: hasBody ? await req.arrayBuffer() : undefined,
    });
    const out = new Headers(res.headers);
    out.delete("content-encoding");
    out.delete("content-length");
    return new Response(res.body, { status: res.status, headers: out });
  } catch {
    return Response.json({ detail: `Can't reach the Agaxes backend at ${BACKEND_URL}. Is it running?` }, { status: 503 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const DELETE = proxy;
