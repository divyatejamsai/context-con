import { NextRequest, NextResponse } from "next/server";
import { BACKEND_URL, SESSION_COOKIE } from "@/lib/auth";

// Every page and API route except the auth pages needs a live session. The cookie alone isn't trusted:
// each request checks the token against the backend's session table, so logging out, expiry or a deleted
// session take effect immediately.
const PUBLIC = ["/login", "/signup", "/forgot", "/reset", "/api/auth/"];

export async function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  const isPublic = PUBLIC.some((p) => pathname === p || pathname.startsWith(p));

  let valid = false;
  let unreachable = false;
  if (token) {
    try {
      const r = await fetch(`${BACKEND_URL}/api/auth/me`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
      valid = r.ok;
    } catch {
      unreachable = true;
    }
  }

  if (isPublic) {
    // Already signed in: skip the login and sign-up pages.
    if (valid && (pathname === "/login" || pathname === "/signup")) return NextResponse.redirect(new URL("/", req.url));
    return NextResponse.next();
  }
  if (valid) return NextResponse.next();

  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ error: "unauthenticated", message: "Log in to continue." }, { status: 401 });
  }
  const url = new URL("/login", req.url);
  if (pathname !== "/") url.searchParams.set("next", pathname + search);
  if (unreachable) url.searchParams.set("reason", "backend");
  else if (token) url.searchParams.set("reason", "expired");
  const res = NextResponse.redirect(url);
  if (token && !unreachable) res.cookies.delete(SESSION_COOKIE);
  return res;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|svg|ico|webp)$).*)"],
};
