// Past searches (backend app/talent/searches.py): every shortlist run and campaign, and where each candidate stands.
// Goes through the same-origin proxy so it sees the signed-in user's workspace.
import { BASE, getAdminToken } from "@/app/console/api";

export type PipelineStage = "shortlisted" | "contacted" | "replied" | "interviewing" | "offered" | "hired" | "rejected" | "dropped";

export const PIPELINE: { key: PipelineStage; label: string; what: string; tone: "open" | "good" | "bad" | "muted" }[] = [
  { key: "shortlisted", label: "Shortlisted", what: "On the shortlist, not contacted yet", tone: "muted" },
  { key: "contacted", label: "Contacted", what: "First message sent, waiting for a reply", tone: "open" },
  { key: "replied", label: "Replied", what: "Replied with interest and is being screened", tone: "open" },
  { key: "interviewing", label: "Interviewing", what: "Interview booked or done", tone: "open" },
  { key: "offered", label: "Offered", what: "An offer is out", tone: "open" },
  { key: "hired", label: "Hired", what: "Signed the offer", tone: "good" },
  { key: "rejected", label: "Rejected", what: "We said no", tone: "bad" },
  { key: "dropped", label: "Dropped", what: "They left the process, or it ended for another reason", tone: "muted" },
];
export const PIPELINE_BY_KEY = Object.fromEntries(PIPELINE.map((p) => [p.key, p])) as Record<PipelineStage, (typeof PIPELINE)[number]>;
export const needsReason = (s: PipelineStage) => s === "rejected" || s === "dropped";

export type StageCounts = Record<PipelineStage, number>;

export interface SearchSummary {
  id: string;
  kind: "shortlist" | "campaign";
  title: string;
  brief: string;
  at: string | null;
  counts: StageCounts;
  candidates_total: number;
  simulated: boolean;
  status?: string;
}

export interface StageStep { at?: string | null; stage: PipelineStage; reason?: string | null; by?: string | null }

export interface SearchCandidate {
  key: string;
  name: string;
  title?: string | null;
  company?: string | null;
  profile_url?: string | null;
  score?: number | null;
  tier: "shortlist" | "near_miss" | "below";
  stage: PipelineStage | null;
  reason?: string | null;
  detail?: string | null;
  set_by: "you" | "Sourced";
  updated_at?: string | null;
  why: string[];
  history: StageStep[];
}

export interface SearchDetail extends SearchSummary {
  agent_id?: string;
  understood?: { locations?: string[]; skills?: string[]; seniority?: string; min_years?: number };
  job?: { city?: string | null; band_low?: number | null; band_high?: number | null; openings?: number };
  candidates: SearchCandidate[];
}

export class SearchError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAdminToken();
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...init,
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...(token ? { "x-admin-token": token } : {}), ...(init?.headers ?? {}) },
    });
  } catch {
    throw new SearchError("Can't reach the backend", 0);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const d = body?.detail;
    const msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((x: { msg?: string }) => x.msg).join("; ") : `Backend returned ${res.status}`;
    throw new SearchError(res.status === 404 && msg === "Not Found" ? "This backend doesn't have past searches yet. Restart it on the latest code." : msg, res.status);
  }
  return body as T;
}

export const searches = {
  list: () => req<SearchSummary[]>("/searches"),
  get: (id: string) => req<SearchDetail>(`/searches/${encodeURIComponent(id)}`),
  setStage: (id: string, key: string, stage: PipelineStage, reason = "") =>
    req<SearchCandidate>(`/searches/${encodeURIComponent(id)}/candidates/${encodeURIComponent(key)}/stage`, {
      method: "POST",
      body: JSON.stringify({ stage, reason }),
    }),
};
