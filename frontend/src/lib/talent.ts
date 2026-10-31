// Client for the hiring-at-volume routes (backend/app/talent/api.py): campaigns (brief to signed offer) and shift
// staffing. Reads need nothing; anything that changes state sends the Countersign admin token when one is set.
import type { Claim, Source } from "./types";
import { API_URL } from "./stream";
import { getAdminToken } from "@/app/console/api";

// ---- campaigns ----------------------------------------------------------------------------------------------------

export type Stage =
  | "contacted" | "screening" | "scheduling" | "interview" | "offer_pending" | "offer" | "offer_held" | "signed"
  | "declined" | "ghosted" | "rejected" | "unsubscribed" | "closed" | "blocked";

export const OPEN_STAGES: Stage[] = ["contacted", "screening", "scheduling", "interview", "offer_pending", "offer", "offer_held"];
export const CLOSED_STAGES: Stage[] = ["declined", "ghosted", "rejected", "unsubscribed", "closed", "blocked"];

/** Plain-language name and one-line meaning for every stage, so nobody has to know the engine's vocabulary. */
export const STAGE: Record<Stage, { label: string; what: string; tone: "open" | "good" | "bad" | "muted" | "hold" }> = {
  contacted: { label: "Messaged", what: "First message sent. Follow-ups go out after 3 and 7 days of silence; no reply in 14 days counts as ghosted.", tone: "open" },
  screening: { label: "Screening", what: "Said yes. Sourced is asking for notice period and expected pay.", tone: "open" },
  scheduling: { label: "Scheduling", what: "Passed screening. Three interview slots offered; waiting for a pick.", tone: "open" },
  interview: { label: "Interview", what: "Interview booked. Waiting for the panel's verdict.", tone: "open" },
  offer_pending: { label: "Passed", what: "Passed the interview. Waiting while the slate fills, best record first.", tone: "open" },
  offer: { label: "Offer out", what: "Offer letter sent. Nudged after 3 days, expires after 5. Accepting means typing \"Signed: <full name>\".", tone: "open" },
  offer_held: { label: "Offer held", what: "The offer was blocked for scope: it waits until the sponsor countersigns.", tone: "hold" },
  signed: { label: "Signed", what: "Signed the offer. The signature, the offer's hash and the time are on the ledger.", tone: "good" },
  declined: { label: "Declined", what: "Said no. Closed politely.", tone: "muted" },
  ghosted: { label: "Ghosted", what: "No reply after two follow-ups and 14 days.", tone: "muted" },
  rejected: { label: "Not a fit", what: "Out of the pay band or notice limit, or failed the interview. Closed with a kind note.", tone: "muted" },
  unsubscribed: { label: "Unsubscribed", what: "Asked not to be contacted. All contact stopped at once.", tone: "muted" },
  closed: { label: "Closed", what: "Closed after the role was filled.", tone: "muted" },
  blocked: { label: "Blocked", what: "Send Guard refused a message to this person, so the conversation ended. The reasons are in the transcript.", tone: "bad" },
};

export const stageLabel = (s?: string) => (s && s in STAGE ? STAGE[s as Stage].label : s ?? "–");

/** The funnel in the order a candidate moves through it, with the question each step answers. */
export const FUNNEL: { key: keyof Funnel; label: string; what: string }[] = [
  { key: "contacted", label: "Messaged", what: "Got a first message that passed Send Guard" },
  { key: "screening", label: "Said yes", what: "Replied with interest and started screening" },
  { key: "scheduling", label: "Screened", what: "Notice and pay fit the brief" },
  { key: "interview", label: "Interviewed", what: "Booked an interview slot" },
  { key: "offer_pending", label: "Passed", what: "Passed the interview panel" },
  { key: "offer", label: "Offered", what: "Got an offer letter" },
  { key: "signed", label: "Signed", what: "Signed the offer" },
];

export interface Funnel {
  contacted: number; screening: number; scheduling: number; interview: number; offer_pending: number; offer: number; signed: number;
}

export interface Job {
  role: string; city?: string | null; band_low?: number | null; band_high?: number | null; notice_max_days?: number | null;
  openings?: number; company?: string; recruiter?: string; start?: string | null;
}

export interface CampaignStats { guard_allowed: number; guard_blocked: number; replies: number; offers: number }

export interface Hire { cid: string; name: string; at?: string; doc_sha256?: string; ctc_lpa?: number; ledger_entry?: string }

export interface CampaignSummary {
  id: string; status: "open" | "filled" | string; role: string; job?: Job; clock: string; day: number; started_at: string;
  filled_at?: string | null; conversations: number; open: number; stages: Partial<Record<Stage, number>>; funnel: Funnel;
  hires: Hire[]; stats: CampaignStats; mode?: "sim" | "live"; messages: number; brief?: string; agent_id?: string;
}

export interface ConversationRow {
  id: string; name: string; title?: string | null; company?: string | null; score?: number; profile_url: string;
  stage: Stage; open: boolean; messages: number; timer?: { kind: string; at: string } | null;
  last?: { dir: "in" | "out"; at: string; kind?: string; body: string } | null;
}

export interface Campaign extends CampaignSummary { conversations_list: ConversationRow[] }

export interface GuardVerdict {
  decision: "allow" | "block"; ledger_entry?: string | null; failed?: (string | { name?: string; detail?: string })[];
  checks?: { name: string; status: string; detail?: string; source?: Source | null }[];
}

/** Where a message actually went. Filled in by real email sending; absent means it stayed in this transcript. */
export interface Delivery { status?: "sent" | "draft" | "held" | "failed" | string; channel?: string; to?: string; at?: string; detail?: string }

export interface Message {
  dir: "in" | "out"; at: string; kind?: string; body: string; scope?: string; guard?: GuardVerdict | null;
  read_as?: { intent?: string; question?: string | null; by?: string } | null; delivery?: Delivery | null;
}

export interface Conversation {
  id: string; name: string; profile_url: string; company?: string | null; title?: string | null; score?: number;
  reasons?: { text: string; claim_ids?: string[] }[]; claims?: Claim[]; hook?: string | null; stage: Stage;
  messages: Message[]; history?: { at: string; from: string; to: string; why: string }[]; followups?: number;
  timer?: { kind: string; at: string } | null;
  screening?: { notice_days?: number | null; expected_lpa?: number | null; asked_again?: boolean } | null;
  interview?: { rounds?: number; options?: string[]; slot?: string | null; passed?: boolean | null; notes?: string; at?: string } | null;
  offer?: { version?: number; ctc_lpa?: number; sent_at?: string; doc_sha256?: string; expires_at?: string } | null;
  signature?: Hire | null;
}

export type CampaignEvent =
  | { type: "message"; at: string; cid: string; name: string; text: string; dir: "in" | "out"; intent?: string; body?: string; message_kind?: string; decision?: "allow" | "block"; failed?: unknown[] }
  | { type: "stage"; at: string; cid: string; name: string; text: string; stage: Stage; previous: string }
  | { type: "snooze" | "decide" | "filled" | "campaign"; at: string; cid?: string | null; name?: string | null; text: string }
  | { type: "day"; day: number; clock: string; stages: Partial<Record<Stage, number>>; funnel: Funnel; status: string; stats: CampaignStats }
  | { type: "done"; summary: CampaignSummary }
  | { type: "error"; message: string };

// ---- staffing -----------------------------------------------------------------------------------------------------

export interface FillRow { filled: number; fill_rate: number; open?: number; shifts?: number }

export interface LieType { planted: number; caught: number; recall: number | null }

export interface Slot { start: string; end: string }

/** One role the company is hiring for at volume, with its own requirements (backend: app/talent/staffing.py Role). */
export interface Role {
  id: string; title: string; cities: string[]; slots: Slot[]; days: number[]; headcount: number; city_headcount?: Record<string, number>;
  min_years: number; max_years?: number | null; related_experience: boolean; keywords: string[];
  skills: string[]; certifications: string[]; languages: string[];
}

export interface RoleTemplate { id: string; label: string; blurb: string; roles: Role[] }

export interface StaffingTemplates {
  templates: RoleTemplate[]; default: string; cities: string[]; csv_columns: string[]; recorded_roles: string[];
  pool_by_role?: Record<string, number>; pool_total?: number;
}

export type GrowEvent =
  | { type: "role"; role: string; found: number }
  | { type: "done"; found: number; new: number; total: number; by_role: Record<string, number>; new_by_role: Record<string, number> }
  | { type: "error"; message: string };

export interface Upload {
  upload_id: string; name?: string | null; applications: number; errors: { row: number; error: string }[]; error_count: number;
  roles: Record<string, number>; cities: Record<string, number>; in_recorded_data: number; no_profile_url: number;
}

export interface Bench {
  rate: number; shift_times: number; standby_wanted: number; standby_found: number; shift_times_covered: number;
  coverage: number | null; people_on_standby: number;
}

export interface StaffingReport {
  today?: string; screening: { cleared: number; flagged: number; not_qualified?: number; duplicate?: number; held?: number };
  flag_kinds?: Record<string, number>; not_qualified_kinds?: Record<string, number>; held_kinds?: Record<string, number>;
  shifts: number; filled: number; fill_rate: number; workers_used?: number; workers_cleared?: number; people?: number;
  duplicates?: { repeat_applications: number; shared_contact: number }; double_bookings?: number; rest_hours?: number;
  bench?: Bench; lookups?: { recorded: number; live: number };
  onboarding_checks?: { workers: number; top: Record<string, number> };
  roles?: Record<string, { title: string; cities: string[]; slots: string[]; needs: string[]; seats: number; filled: number; applied: number; cleared: number }>;
  by_city: Record<string, FillRow>; by_role: Record<string, FillRow>; open_reasons: Record<string, number>;
  fake_catch?: {
    applications: number; fakes_planted: number; flagged: number; true_positives: number; false_positives: number;
    false_negatives: number; precision: number | null; recall: number | null; by_lie_type: Record<string, LieType>;
    fakes_staffed: unknown[]; missed?: unknown[]; false_alarms?: unknown[];
    duplicates_planted?: number; duplicates_caught?: number;
  } | null;
  no_show_drill?: { rate: number; no_shows: number; from_bench: number; from_pool: number; uncovered: number; double_bookings_after: number };
  pool?: { records: number; source: string; file?: string | null; rows?: number };
  test_mode?: boolean; horizon?: { start: string; days: number };
}

export interface Screening {
  app_id: string; name: string; profile_url: string; role: string; city: string; outcome: "cleared" | "flagged" | "not_qualified" | "duplicate" | "held" | string;
  reason?: string; kind?: string; record_name?: string | null; home_city?: string | null; claims?: Claim[]; checks?: string[]; person?: string | null;
}

export interface RosterRow {
  id: string; role: string; role_label: string; city: string; date: string; weekday: string; slot?: string; start?: string; end?: string;
  worker: string | null; worker_name: string | null; person?: string | null; open_reason?: string | null; no_show?: string | null;
  bench?: { worker: string; name?: string | null }[];
}

export interface StaffingRunRequest {
  roles?: Role[]; template?: string; start?: string; days?: number; source: "recorded" | "upload" | "live"; upload_id?: string;
  test_mode?: boolean; fake_rate?: number; duplicate_rate?: number; no_show_rate?: number; seed?: number;
  bench_rate?: number; rest_hours?: number; live_lookups?: number;
}

export type StaffingEvent =
  | { type: "step"; step: string; message: string; data?: Record<string, number> }
  | { type: "flagged"; screening: Screening }
  | { type: "done"; report: StaffingReport }
  | { type: "error"; message: string };

/** What each planted lie looks like, in words a staffing manager would use. */
export const LIE_LABEL: Record<string, string> = {
  fake_employer: "Made-up employer",
  ghost_profile: "Profile that doesn't exist",
  identity_mismatch: "Someone else's profile",
  inflated_experience: "Inflated years of experience",
  inflated_title: "Inflated job title",
  stale_current_job: "Left the job they claim",
  stretched_tenure: "Stretched time at a job",
  wrong_location: "Doesn't live where they say",
};

export const FLAG_LABEL: Record<string, string> = {
  identity_unverifiable: "Identity can't be confirmed",
  identity_mismatch: "Name doesn't match the profile",
  false_claim: "Claim contradicted by the record",
  shared_contact: "One phone or email, several people",
  role_mismatch: "No related work on the record",
  under_experience: "Not enough experience",
  over_experience: "More experience than the role is for",
  missing_requirement: "Missing a requirement",
  role_not_open: "Role isn't open there",
  wrong_city: "Lives in another city",
  repeat_application: "Applied twice",
  needs_lookup: "Not in the recorded data",
  lookup_failed: "Lookup failed",
};

export const label = (map: Record<string, string>, k: string) => map[k] ?? k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

// ---- transport ----------------------------------------------------------------------------------------------------

export class TalentError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

/** The backend's own reason when it gives one; a bare 404 means this backend doesn't have the hiring-at-volume routes yet. */
const detail = (body: { detail?: unknown } | null, status: number) =>
  Array.isArray(body?.detail)
    ? ((body?.detail ?? []) as { loc?: (string | number)[]; msg?: string }[]).map((d) => `${(d.loc ?? []).slice(1).join(" ")}: ${d.msg}`).join("; ")
    : typeof body?.detail === "string" && body.detail !== "Not Found"
    ? body.detail
    : status === 404
      ? "This backend doesn't have campaigns and shift staffing yet. They arrive with the brief-to-offer backend (PR #18)."
      : `Backend returned ${status}`;

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAdminToken();
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(token ? { "x-admin-token": token } : {}), ...(init?.headers ?? {}) },
    });
  } catch {
    throw new TalentError(`Can't reach the backend at ${API_URL}`, 0);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new TalentError(detail(body, res.status), res.status);
  return body as T;
}

const post = <T,>(path: string, body?: unknown) => req<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const talent = {
  campaigns: () => req<CampaignSummary[]>("/campaigns"),
  campaign: (id: string) => req<Campaign>(`/campaigns/${id}`),
  create: (b: { brief: string; size?: number; agent_id?: string; seed?: number }) => post<Campaign>("/campaigns", { mode: "sim", ...b }),
  conversation: (id: string, cid: string) => req<Conversation>(`/campaigns/${id}/conversations/${cid}`),
  advance: (id: string, days: number) => post<{ summary: CampaignSummary; events: CampaignEvent[] }>(`/campaigns/${id}/advance`, { days }),
  reply: (id: string, cid: string, text: string) => post<{ read_as: Message["read_as"]; conversation: ConversationRow }>(`/campaigns/${id}/conversations/${cid}/reply`, { text }),
  feedback: (id: string, cid: string, passed: boolean, notes = "") => post<ConversationRow>(`/campaigns/${id}/conversations/${cid}/feedback`, { passed, notes }),
  staffingLast: () => req<{ report: StaffingReport }>("/staffing/last"),
  staffingTemplates: () => req<StaffingTemplates>("/staffing/templates"),
  staffingUpload: (csv: string, name?: string) => post<Upload>("/staffing/applications", { csv, name }),
  staffingRoster: (p: { role?: string; city?: string; status?: string; q?: string; offset?: number; limit?: number }) =>
    req<{ total: number; rows: RosterRow[] }>(`/staffing/roster?${new URLSearchParams(Object.entries(p).filter(([, v]) => v !== undefined && v !== "").map(([k, v]) => [k, String(v)]))}`),
  staffingScreenings: (outcome: string, limit = 2000) => req<{ total: number; rows: Screening[] }>(`/staffing/screenings?outcome=${outcome}&limit=${limit}`),
  staffingNoShow: (shift_id: string) => post<{ no_show: string | null; backup: string | null; from: "bench" | "pool" | null; shift: RosterRow; double_bookings: number }>("/staffing/no-show", { shift_id }),
};

export const staffingUrl = (path: string) => `${API_URL}/api${path}`;

/** GET an SSE route and yield each `data:` frame as JSON. The token goes in the query because EventSource-style GETs carry no headers. */
export async function* sse<T>(path: string, params: Record<string, string | number>, signal: AbortSignal): AsyncGenerator<T> {
  const q = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]));
  const token = getAdminToken();
  if (token) q.set("token", token);
  yield* sseFetch<T>(`${API_URL}/api${path}?${q}`, { headers: { Accept: "text/event-stream" }, signal });
}

/** POST a JSON body to an SSE route (the staffing run carries its roles in the body) and yield each frame. */
export async function* ssePost<T>(path: string, body: unknown, signal: AbortSignal): AsyncGenerator<T> {
  const token = getAdminToken();
  yield* sseFetch<T>(`${API_URL}/api${path}`, {
    method: "POST", body: JSON.stringify(body), signal,
    headers: { Accept: "text/event-stream", "Content-Type": "application/json", ...(token ? { "x-admin-token": token } : {}) },
  });
}

async function* sseFetch<T>(url: string, init: RequestInit): AsyncGenerator<T> {
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new TalentError(`Can't reach the backend at ${API_URL}`, 0);
  }
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => null);
    throw new TalentError(detail(body, res.status), res.status);
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value;
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const frame = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const data = frame.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5).trimStart()).join("\n");
      if (!data) continue;
      try {
        yield JSON.parse(data) as T;
      } catch {
        // a malformed frame is skipped rather than ending the stream
      }
    }
  }
}

// ---- formatting ---------------------------------------------------------------------------------------------------

export const pct = (x?: number | null, digits = 0) => (x == null ? "–" : `${(x * 100).toFixed(digits)}%`);

export const when = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "–";

export const shortDay = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "–");

export const band = (j?: Job) =>
  j?.band_low != null && j?.band_high != null ? `${j.band_low}–${j.band_high} LPA` : j?.band_high != null ? `up to ${j.band_high} LPA` : null;
