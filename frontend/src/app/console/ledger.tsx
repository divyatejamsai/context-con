"use client";
import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Loader2, RefreshCw, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { api, type Agent, type LedgerEntry, type LedgerView, type Scope } from "./api";
import { Button, DecisionBadge, PageHead, ScopeChip, SourceChip, cardCls, inputCls } from "./parts";

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
};

// ---- independent check in the browser --------------------------------------------------------
// Mirrors backend/app/agents/ledger.py: hash = sha256(canonical JSON of every field except "hash"),
// canonical = sorted keys, no spaces, UTF-8. Re-deriving it here means the console doesn't just trust the server.

function canonical(v: unknown): string {
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
async function verifyInBrowser(entries: LedgerEntry[]): Promise<number | null> {
  let prev = "0".repeat(64);
  for (let i = 0; i < entries.length; i++) {
    const e = entries[i];
    const { hash, ...body } = e;
    if (e.seq !== i || e.prev_hash !== prev || (await sha256(canonical(body))) !== hash) return i;
    prev = hash;
  }
  return null;
}

// ---- views -----------------------------------------------------------------------------------

export function LedgerExplorer({ agents, onChain }: { agents: Agent[]; onChain: (c: { chain_ok: boolean; first_bad_seq: number | null; count: number }) => void }) {
  const [view, setView] = useState<LedgerView | null>(null);
  const [browserBad, setBrowserBad] = useState<number | null | undefined>();
  const [agentId, setAgentId] = useState("");
  const [kind, setKind] = useState("");
  const [follow, setFollow] = useState(true);
  const [loading, setLoading] = useState(false);
  const [checkedAt, setCheckedAt] = useState<Date>();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const v = await api.ledger();
      setView(v);
      setBrowserBad(await verifyInBrowser(v.entries));
      setCheckedAt(new Date());
      onChain({ chain_ok: v.chain_ok, first_bad_seq: v.first_bad_seq, count: v.entries.length });
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
    <main className="mx-auto max-w-[1100px] px-4 py-6">
      <PageHead title="Ledger">
        An append-only record of every passport, check, verdict and suspension, with the Crustdata sources behind each one. Every entry
        includes the hash of the one before it, so editing, deleting or reordering any line breaks the chain from that point on.
      </PageHead>

      {view && (
        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          <Integrity label="Server check" detail="backend verify_chain()" bad={view.chain_ok ? null : view.first_bad_seq} />
          <Integrity label="Browser check" detail="re-hashed here with Web Crypto" bad={browserBad} />
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <select value={agentId} onChange={(e) => setAgentId(e.target.value)} className={cn(inputCls, "w-auto min-w-[180px]")}>
          <option value="">All agents</option>
          {agents.map((a) => <option key={a.agent_id} value={a.agent_id}>{a.name}</option>)}
        </select>
        <select value={kind} onChange={(e) => setKind(e.target.value)} className={cn(inputCls, "w-auto min-w-[180px]")}>
          <option value="">All events</option>
          {kinds.map((k) => <option key={k} value={k}>{KIND_LABEL[k] ?? k}</option>)}
        </select>
        <label className="ml-auto flex items-center gap-2 text-[12.5px] text-muted-foreground">
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} className="accent-[var(--primary)]" />
          Re-check every 3s
        </label>
        <Button onClick={() => load()} disabled={loading}>
          {loading ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />} Re-check now
        </Button>
      </div>
      <p className="mt-2 text-[11.5px] text-faint">
        {view ? `${view.entries.length} entries` : "Loading"}
        {checkedAt && ` · checked ${checkedAt.toLocaleTimeString("en-GB")}`} · try editing a line of backend/data/ledger.jsonl and watch both checks fail.
      </p>

      <div className={cn(cardCls, "mt-4 px-5 py-4")}>
        {shown.length ? (
          <LedgerTimeline entries={shown} firstBad={browserBad ?? (view?.chain_ok ? null : view?.first_bad_seq ?? null)} names={names} />
        ) : (
          <p className="text-[12.5px] text-faint">No entries yet.</p>
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
          notes?: string;
        };
        const bad = firstBad !== null && firstBad !== undefined && e.seq >= firstBad;
        const who = p.agent_id && names?.get(p.agent_id);
        const recipient = p.to && !Array.isArray(p.to) ? p.to : null;
        return (
          <li key={`${e.seq}-${e.hash}`} className={cn("relative pb-4 last:pb-0", bad && "opacity-90")}>
            <span className={cn("absolute -left-[24.5px] top-1.5 size-2 rounded-full ring-4 ring-panel", bad ? "bg-contradicted" : e.kind.includes("revoked") ? "bg-contradicted" : "bg-border-strong")} />
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[10.5px] text-faint">#{e.seq}</span>
              <span className="text-[13px] font-[510]">{KIND_LABEL[e.kind] ?? e.kind}</span>
              {who && <span className="text-[12px] text-muted-foreground">{who}</span>}
              {p.decision && <DecisionBadge decision={p.decision} />}
              {p.scope && <ScopeChip scope={p.scope as Scope} />}
              {bad && e.seq === firstBad && <span className="rounded bg-contradicted/15 px-1.5 font-mono text-[10.5px] text-contradicted">chain breaks here</span>}
              <span className="ml-auto text-[11px] text-faint">{new Date(e.ts).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}</span>
            </div>
            {recipient && <p className="mt-0.5 text-[12.5px] text-secondary">to {recipient.name} at {recipient.company}</p>}
            {p.reason && <p className="mt-0.5 text-[12.5px] text-secondary">{p.reason}</p>}
            {p.notes && <p className="mt-0.5 text-[12.5px] text-secondary">{p.notes}</p>}
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
