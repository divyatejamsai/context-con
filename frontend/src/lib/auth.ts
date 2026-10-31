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
  workspace_role: "owner" | "admin" | "member" | "viewer";
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

// What the signed-in person may see (GET /api/auth/me -> access). The backend enforces the same lines.
//   platform  the Agaxes operator: every company, its people and AI employees
//   company   a company owner/admin: everything in their own company only
//   own_work  a recruiter (member/viewer): only the AI employees assigned to them, their tasks and approvals
export interface AuthAccess {
  level: "platform" | "company" | "own_work";
  role: "operator" | "owner" | "admin" | "member" | "viewer";
  views: string[];
  summary: string;
}
