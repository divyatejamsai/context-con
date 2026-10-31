import { canonicalStep, type Candidate, type ClaimStatus, type Criteria, type PassportCheck, type RunEvent, type Summary } from "./types";

export interface LogItem {
  kind: "step" | "error";
  step?: string;
  message: string;
  t: number; // ms since run start
}

export interface StepState {
  status: "pending" | "active" | "done" | "warn";
  startedAt?: number;
  endedAt?: number;
  count?: number;
  errors: number;
}

export interface RunState {
  running: boolean;
  startedAt?: number;
  endedAt?: number;
  log: LogItem[];
  steps: Record<string, StepState>;
  currentStep?: string;
  criteria?: Criteria;
  candidates: Record<string, Candidate>;
  arrival: string[]; // candidate ids in arrival order
  order?: string[];
  shortlist?: string[]; // ids the backend shortlisted (score above threshold)
  nearMiss?: string[]; // ids just under the threshold
  passport?: PassportCheck; // agent runs: the live passport check that gates the run
  summary?: Summary;
  done: boolean;
  fatal?: string;
}

export type RunAction =
  | { type: "start"; at: number }
  | { type: "event"; ev: RunEvent; at: number }
  | { type: "fatal"; message: string; at: number }
  | { type: "stop"; at: number }
  | { type: "reset" };

export const initialRun: RunState = { running: false, log: [], steps: {}, candidates: {}, arrival: [], done: false };

function enterStep(s: RunState, step: string, at: number): Record<string, StepState> {
  const steps = { ...s.steps };
  if (s.currentStep && s.currentStep !== step && steps[s.currentStep]) {
    const prev = steps[s.currentStep];
    steps[s.currentStep] = { ...prev, status: prev.errors ? "warn" : "done", endedAt: prev.endedAt ?? at };
  }
  const cur = steps[step] ?? { status: "active", errors: 0 };
  steps[step] = { ...cur, status: "active", startedAt: cur.startedAt ?? at, endedAt: undefined };
  return steps;
}

export function runReducer(s: RunState, a: RunAction): RunState {
  switch (a.type) {
    case "start":
      return { ...initialRun, running: true, startedAt: a.at };
    case "reset":
      return initialRun;
    case "stop":
      return { ...s, running: false, endedAt: s.endedAt ?? a.at };
    case "fatal":
      return { ...s, running: false, endedAt: a.at, fatal: a.message };
    case "event": {
      const ev = a.ev;
      const t = a.at - (s.startedAt ?? a.at);
      switch (ev.type) {
        case "step": {
          const step = canonicalStep(ev.step) ?? "step";
          const steps = enterStep(s, step, a.at);
          const count = typeof ev.data?.count === "number" ? (ev.data.count as number) : undefined;
          if (count !== undefined) steps[step] = { ...steps[step], count };
          return {
            ...s,
            steps,
            currentStep: step,
            criteria: ev.data?.criteria ?? s.criteria,
            order: Array.isArray(ev.data?.order) ? (ev.data.order as string[]) : s.order,
            shortlist: Array.isArray(ev.data?.shortlist) ? (ev.data.shortlist as string[]) : s.shortlist,
            nearMiss: Array.isArray(ev.data?.near_miss) ? (ev.data.near_miss as string[]) : s.nearMiss,
            passport:
              step === "passport" && (ev.data?.decision === "allow" || ev.data?.decision === "block")
                ? ({ ...(ev.data as object), message: ev.message } as PassportCheck)
                : s.passport,
            log: [...s.log, { kind: "step", step, message: ev.message, t }],
          };
        }
        case "error": {
          const step = canonicalStep(ev.step);
          const steps = { ...s.steps };
          if (step) {
            const cur = steps[step] ?? { status: "active", errors: 0, startedAt: a.at };
            steps[step] = { ...cur, errors: cur.errors + 1 };
          }
          // An error on the passport step means the agent was refused before any search.
          const passport = step === "passport" ? { ...s.passport, decision: "block" as const, error: ev.message } : s.passport;
          return { ...s, steps, passport, log: [...s.log, { kind: "error", step, message: ev.message, t }] };
        }
        case "criteria":
          return { ...s, criteria: ev.criteria };
        case "candidate": {
          const c = ev.candidate;
          if (!c?.id) return s;
          const known = c.id in s.candidates;
          return {
            ...s,
            candidates: { ...s.candidates, [c.id]: { ...s.candidates[c.id], ...c } },
            arrival: known ? s.arrival : [...s.arrival, c.id],
          };
        }
        case "done": {
          const steps = { ...s.steps };
          for (const k of Object.keys(steps)) {
            const st = steps[k];
            if (st.status === "active") steps[k] = { ...st, status: st.errors ? "warn" : "done", endedAt: a.at };
          }
          return { ...s, steps, done: true, running: false, endedAt: a.at, summary: ev.summary };
        }
        default:
          return s;
      }
    }
  }
}

export function normalizeStatus(s: string | undefined, hasSource = true): ClaimStatus {
  if (!hasSource) return "unverifiable";
  return s === "verified" || s === "contradicted" ? s : "unverifiable";
}

export function claimCounts(c: Candidate): Record<ClaimStatus, number> & { total: number } {
  const out = { verified: 0, contradicted: 0, unverifiable: 0, total: 0 };
  for (const k of c.claims ?? []) {
    out[normalizeStatus(k.status, !!k.source?.endpoint)]++;
    out.total++;
  }
  return out;
}

/** Share of claims that are verified, 0-100. Separate from fit score: how much can we trust this record. */
export function evidenceStrength(c: Candidate): number {
  const k = claimCounts(c);
  return k.total ? Math.round((k.verified / k.total) * 100) : 0;
}
