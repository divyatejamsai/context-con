// Shared by the auth route handlers and middleware (server side only).
export const SESSION_COOKIE = "sourced_session";

// Server-to-server base URL for the FastAPI backend. AUTH_API_URL wins so the server can use an internal
// address; otherwise the same URL the browser uses.
export const BACKEND_URL = (process.env.AUTH_API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

export interface AuthUser {
  id: string;
  email: string;
  full_name: string;
  job_role: string | null;
  workspace_role: "owner" | "member";
  company_id: string;
}

export interface AuthCompany {
  id: string;
  name: string;
  domain: string;
  size_band: string | null;
  industry: string | null;
  verified_via: "crustdata" | "self_reported" | "demo";
  crustdata_company_id: number | null;
}
