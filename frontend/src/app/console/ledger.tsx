"use client";
import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, FileClock, Loader2, Plus, RefreshCw, ShieldAlert, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { api, type Agent, type LedgerEntry, type LedgerView, type Scope } from "./api";
import { Button, DecisionBadge, EmptyState, PageHead, ScopeChip, SourceChip, cardCls, inputCls } from "./parts";

const KIND_LABEL: Record<string, string> = {
  "passport.issued": "Passport issued",
  "passport.verified": "Passport checked",
  "passport.revoked": "Passport revoked",
  "passport.reinstated": "Passport reinstated",
  "guard.verdict": "Message checked by the Send Guard",
  "agent.onboarded": "Onboarded",
  "agent.offboarded": "Offboarded",
  "agent.reviewed": "Reviewed",
  "agent.scopes_changed": "Scopes changed",
  "agent.scope_denied": "Scope refused",
  "agent.scopes_checked": "Sponsor checked for new scopes",
  "work.outreach_run": "Work filed: outreach run",
  "work.vendor_brief": "Work filed: vendor brief",
  "work.resume_check": "Work filed: resume check",
  "run.started": "Hiring run started",
  "run.finished": "Hiring run finished",
  "resume.verified": "Resume checked",
};

const kindLabel = (k: string) => KIND_LABEL[k] ?? (k.startsWith("work.") ? `Work filed: ${k.slice(5).replace(/_/g, " ")}` : k);

// ---- independent check in the browser --------------------------------------------------------
// Mirrors backend/app/agents/ledger.py: hash = sha256(canonical JSON of every field except "hash"),
// canonical = sorted keys, no spaces, UTF-8. Re-deriving it here means the console doesn't just trust the server.

// Python writes 55.0 where JavaScript would write 55, so numbers keep the exact text the server sent. The ledger is
// re-parsed with a small JSON reader that leaves each number as its original lexeme.
class Num {
  constructor(public raw: string) {}
}

function parseLossless(text: string): unknown {
  let i = 0;
  const ws = () => {
    while (i < text.length && " \t\n\r".includes(text[i])) i++;
  };
  const value = (): unknown => {
    ws();
    const c = text[i];
    if (c === "{") {
      i++;
      const o: Record<string, unknown> = {};
      ws();
      if (text[i] === "}") return i++, o;
      while (true) {
        ws();
        const k = value() as string;
        ws();
        i++; // :
        o[k] = value();
        ws();
        if (text[i++] === "}") return o;
      }
    }
    if (c === "[") {
      i++;
      const a: unknown[] = [];
      ws();
      if (text[i] === "]") return i++, a;
      while (true) {
        a.push(value());
        ws();
        if (text[i++] === "]") return a;
      }
    }
    if (c === '"') {
      const start = i++;
      while (text[i] !== '"') i += text[i] === "\\" ? 2 : 1;
      i++;
      return JSON.parse(text.slice(start, i));
    }
    const m = /^(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null)/.exec(text.slice(i, i + 64));
    if (!m) throw new Error(`Unexpected ${c} at ${i}`);
    i += m[0].length;
    return m[0] === "true" ? true : m[0] === "false" ? false : m[0] === "null" ? null : new Num(m[0]);
  };
  return value();
}

function canonical(v: unknown): string {
  if (v instanceof Num) return v.raw;
  if (v === null || typeof v !== "object") return JSON.stringify(v);
  if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
  const o = v as Record<string, unknown>;
  return `{${Object.keys(o).sort().map((k) => `${JSON.stringify(k)}:${canonical(o[k])}`).join(",")}}`;
}

async function sha256(s: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** First seq whose hash or link doesn't hold, or null if the whole chain checks out. */
async function verifyInBrowser(raw: string): Promise<number | null> {
  const entries = (parseLossless(raw) as { entries: Record<string, unknown>[] }).entries;
  let prev = "0".repeat(64);
  for (let i = 0; i < entries.length; i++) {
    const { hash, ...body } = entries[i];
    const seq = body.seq instanceof Num ? Number(body.seq.raw) : NaN;
    if (seq !== i || body.prev_hash !== prev || (await sha256(canonical(body))) !== hash) return Number.isNaN(seq) ? i : seq;
    prev = hash as string;
  }
  return null;
}

// ---- views -----------------------------------------------------------------------------------

export function LedgerExplorer({
  agents, onChain, onOnboard,
}: { agents: Agent[]; onChain: (c: { chain_ok: boolean; first_bad_seq: number | null; count: number }) => void; onOnboard: () => void }) {
  const [view, setView] = useState<LedgerView | null>(null);
  const [browserBad, setBrowserBad] = useState<number | null | undefined>();
  const [agentId, setAgentId] = useState("");
  const [kind, setKind] = useState("");
  const [follow, setFollow] = useState(true);
  const [loading, setLoading] = useState(false);
  const [checkedAt, setCheckedAt] = useState<Date>();
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const raw = await api.ledgerText();
      const v = JSON.parse(raw) as LedgerView;
      setView(v);
      setFailed(false);
      setBrowserBad(await verifyInBrowser(raw).catch(() => 0));
      setCheckedAt(new Date());
      onChain({ chain_ok: v.chain_ok, first_bad_seq: v.first_bad_seq, count: v.entries.length });
    } catch (e) {
      setFailed(true);
      throw e;
    } finally {
      setLoading(false);
    }
  }, [onChain]);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);
  useEffect(() => {
    if (!follow) return;
    const id = setInterval(() => load().catch(() => {}), 3000);
    return () => clearInterval(id);
  }, [follow, load]);

  const names = new Map(agents.map((a) => [a.agent_id, a.name]));
  const kinds = view ? [...new Set(view.entries.map((e) => e.kind))].sort() : [];
  const shown = (view?.entries ?? [])
    .filter((e) => !kind || e.kind === kind)
    .filter((e) => !agentId || mentions(e, agentId))
    .reverse();

  return (
    <main className="mx-auto max-w-[1100px] px-4 py-6 sm:px-8 sm:py-8">
      <PageHead title="Ledger">
        The permanent record of every passport, check, verdict and suspension, with the Crustdata sources behind each one. Use it to
        prove later why an agent was trusted or stopped. Each entry includes the hash of the one before it, so editing, deleting or
        reordering any line breaks the chain from that point on, and both checks below turn red.
      </PageHead>

      {view && (
        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          <Integrity label="Server check" detail="The backend re-hashed every entry (verify_chain)." bad={view.chain_ok ? null : view.first_bad_seq} />
          <Integrity label="Browser check" detail="This page re-hashed every entry itself, so you don't have to trust the server." bad={browserBad} />
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <select value={agentId} onChange={(e) => setAgentId(e.target.value)} className={cn(inputCls, "w-full sm:w-auto sm:min-w-[180px]")} aria-label="Filter by agent" title="Show entries about one agent">
          <option value="">All agents</option>
          {agents.map((a) => <option key={a.agent_id} value={a.agent_id}>{a.name}</option>)}
        </select>
        <select value={kind} onChange={(e) => setKind(e.target.value)} className={cn(inputCls, "w-full sm:w-auto sm:min-w-[180px]")} aria-label="Filter by event type" title="Show one kind of event">
          <option value="">All events</option>
          {kinds.map((k) => <option key={k} value={k}>{kindLabel(k)}</option>)}
        </select>
        <label className="flex items-center gap-2 text-[12.5px] text-muted-foreground sm:ml-auto" title="Re-read and re-hash the ledger every 3 seconds, so tampering shows up live">
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} className="accent-[var(--primary)]" />
          Re-check every 3s
        </label>
        <Button onClick={() => load().catch(() => {})} disabled={loading} title="Re-read the ledger and re-hash every entry now">
          {loading ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />} Re-check now
        </Button>
      </div>
      <p className="mt-2 text-[11.5px] text-faint">
        {view ? `${view.entries.length} entries` : "Loading"}
        {checkedAt && ` · checked ${checkedAt.toLocaleTimeString("en-GB")}`} · try editing a line of backend/data/ledger.jsonl and watch both checks fail.
      </p>

      <div className={cn(cardCls, "mt-4 px-5 py-4")}>
        {failed && !view ? (
          <EmptyState icon={ShieldAlert} tone="bad" title="Couldn't read the ledger" action={<Button onClick={() => load().catch(() => {})}><RefreshCw className="size-3.5" /> Try again</Button>}>
            The backend didn&apos;t answer. Check that it is running, then try again.
          </EmptyState>
        ) : !view ? (
          <p className="inline-flex items-center gap-2 py-6 text-[12.5px] text-faint"><Loader2 className="size-3.5 animate-spin" /> Reading the ledger…</p>
        ) : shown.length ? (
          <LedgerTimeline entries={shown} firstBad={browserBad ?? (view?.chain_ok ? null : view?.first_bad_seq ?? null)} names={names} />
        ) : view.entries.length ? (
          <EmptyState icon={FileClock} title="No entries match these filters" action={<Button onClick={() => { setAgentId(""); setKind(""); }}>Clear filters</Button>} />
        ) : (
          <EmptyState icon={FileClock} title="The ledger is empty" action={<Button variant="primary" onClick={onOnboard}><Plus className="size-3.5" /> Onboard an agent</Button>}>
            Onboarding an AI employee writes the first entry: its passport being issued.
          </EmptyState>
        )}
      </div>
    </main>
  );
}

function Integrity({ label, detail, bad }: { label: string; detail: string; bad: number | null | undefined }) {
  const ok = bad === null;
  return (
    <div className={cn("flex items-start gap-3 rounded-xl border px-4 py-3", bad === undefined ? "border-border-strong" : ok ? "border-verified/30 bg-verified/[0.05]" : "border-contradicted/35 bg-contradicted/[0.06]")}>
      {bad === undefined ? <Loader2 className="mt-0.5 size-4 animate-spin text-faint" /> : ok ? <CheckCircle2 className="mt-0.5 size-4 text-verified" /> : <XCircle className="mt-0.5 size-4 text-contradicted" />}
      <div>
        <div className="text-[13px] font-[590]">
          {label}: {bad === undefined ? "checking" : ok ? "chain intact" : `tampering detected at entry #${bad}`}
        </div>
        <div className="text-[11.5px] text-muted-foreground">{detail}</div>
      </div>
    </div>
  );
}

// Countersign's own fields (issuer key, passport, ledger) sort after the Crustdata citations, which are the evidence.
const isInternal = (endpoint: string) => endpoint.startsWith("countersign/") || endpoint === "passport";

function mentions(e: LedgerEntry, agentId: string) {
  const p = e.payload as { agent_id?: string; subject?: string; passport?: { agent_id?: string } };
  return p.agent_id === agentId || p.subject === agentId || p.passport?.agent_id === agentId;
}

/** Entries in the order given. Anything at or after `firstBad` is marked as no longer trustworthy. */
export function LedgerTimeline({
  entries, firstBad, names, className,
}: { entries: LedgerEntry[]; firstBad: number | null; names?: Map<string, string>; className?: string }) {
  return (
    <ol className={cn("relative border-l border-border-strong pl-5", className)}>
      {entries.map((e) => {
        const p = e.payload as {
          agent_id?: string; decision?: "allow" | "block"; reason?: string; scope?: string | null; from?: string[]; to?: string[] | { name?: string; company?: string };
          notes?: string; summary?: string; signed?: boolean;
        };
        const bad = firstBad !== null && firstBad !== undefined && e.seq >= firstBad;
        const who = p.agent_id && names?.get(p.agent_id);
        const recipient = p.to && !Array.isArray(p.to) ? p.to : null;
        return (
          <li key={`${e.seq}-${e.hash}`} className={cn("relative pb-4 last:pb-0", bad && "opacity-90")}>
            <span className={cn("absolute -left-[24.5px] top-1.5 size-2 rounded-full ring-4 ring-panel", bad ? "bg-contradicted" : e.kind.includes("revoked") ? "bg-contradicted" : "bg-border-strong")} />
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[10.5px] text-faint">#{e.seq}</span>
              <span className="text-[13px] font-[510]">{kindLabel(e.kind)}</span>
              {who && <span className="text-[12px] text-muted-foreground">{who}</span>}
              {p.decision && <DecisionBadge decision={p.decision} />}
              {p.scope && <ScopeChip scope={p.scope as Scope} />}
              {bad && e.seq === firstBad && <span className="rounded bg-contradicted/15 px-1.5 font-mono text-[10.5px] text-contradicted">chain breaks here</span>}
              <span className="ml-auto text-[11px] text-faint">{new Date(e.ts).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}</span>
            </div>
            {recipient && <p className="mt-0.5 text-[12.5px] text-secondary">to {recipient.name} at {recipient.company}</p>}
            {p.reason && <p className="mt-0.5 text-[12.5px] text-secondary">{p.reason}</p>}
            {p.notes && <p className="mt-0.5 text-[12.5px] text-secondary">{p.notes}</p>}
            {e.kind.startsWith("work.") && p.summary && (
              <p className="mt-0.5 text-[12.5px] text-secondary">
                {p.summary}
                {p.signed && <span className="ml-2 font-mono text-[10.5px] text-faint">signed by the agent</span>}
              </p>
            )}
            {p.from && Array.isArray(p.to) && <p className="mt-0.5 font-mono text-[11px] text-secondary">{p.from.join(", ")} → {p.to.join(", ")}</p>}
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <span className={cn("font-mono text-[10.5px]", bad ? "text-contradicted" : "text-faint")} title={`hash ${e.hash}\nprev ${e.prev_hash}`}>
                {e.hash.slice(0, 12)}
              </span>
              {[...e.sources].sort((a, b) => Number(isInternal(a.endpoint)) - Number(isInternal(b.endpoint))).slice(0, 3).map((s, i) => <SourceChip key={i} source={s} />)}
              {e.sources.length > 3 && <span className="text-[10.5px] text-faint">+{e.sources.length - 3} sources</span>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
