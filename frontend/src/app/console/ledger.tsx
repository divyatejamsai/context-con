"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Download, FileClock, Loader2, Plus, RefreshCw, ShieldAlert, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { api, type Agent, type LedgerEntry, type LedgerView } from "./api";
import { Button, EmptyState, PageHead, cardCls, inputCls } from "./parts";
import { CATEGORIES, LedgerTimeline, describe, type Category } from "./story";


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
  // A signed-in user sees only their workspace's entries, so there can be gaps. Every entry must hash to itself, and
  // wherever two shown entries are consecutive (or the first is #0) the link between them must hold.
  let prevSeq = -1;
  let prev = "0".repeat(64);
  for (let i = 0; i < entries.length; i++) {
    const { hash, ...body } = entries[i];
    const seq = body.seq instanceof Num ? Number(body.seq.raw) : NaN;
    const linked = seq === prevSeq + 1;
    if (Number.isNaN(seq) || seq <= prevSeq || (linked && body.prev_hash !== prev) || (await sha256(canonical(body))) !== hash)
      return Number.isNaN(seq) ? i : seq;
    prevSeq = seq;
    prev = hash as string;
  }
  return null;
}

// ---- views -----------------------------------------------------------------------------------

export { LedgerTimeline } from "./story";

export function LedgerExplorer({
  agents, onChain, onOnboard,
}: { agents: Agent[]; onChain: (c: { chain_ok: boolean; first_bad_seq: number | null; count: number }) => void; onOnboard: () => void }) {
  const [view, setView] = useState<LedgerView | null>(null);
  const [browserBad, setBrowserBad] = useState<number | null | undefined>();
  const [agentId, setAgentId] = useState("");
  const [cat, setCat] = useState<Category | "">("");
  const [routine, setRoutine] = useState(false);
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
    const id = setInterval(() => load().catch(() => {}), 5000);
    return () => clearInterval(id);
  }, [follow, load]);

  const names = useMemo(() => new Map(agents.map((a) => [a.agent_id, a.name])), [agents]);
  const all = view?.entries ?? [];
  const forAgent = all.filter((e) => !agentId || mentions(e, agentId));
  const lines = forAgent.map((e) => ({ e, d: describe(e, names) }));
  const hidden = lines.filter((l) => l.d.noise).length;
  const counts = lines.reduce<Record<string, number>>((m, l) => ((m[l.d.cat] = (m[l.d.cat] ?? 0) + 1), m), {});
  const shown = lines.filter((l) => (routine || !l.d.noise) && (!cat || l.d.cat === cat)).map((l) => l.e).reverse();
  const firstBad = browserBad ?? (view?.chain_ok ? null : view?.first_bad_seq ?? null);
  const blocked = lines.filter((l) => l.d.tone === "bad").length;

  return (
    <main className="mx-auto max-w-[1000px] px-4 py-6 sm:px-8 sm:py-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PageHead title="Ledger">
          Everything your agents did and every decision about them, in plain words, newest first. Nothing here can be quietly edited:
          each entry is chained to the one before it, so a changed line breaks the chain and the badge below turns red.
        </PageHead>
        <ExportButtons agentId={agentId || undefined} />
      </div>

      {view && <ChainBadge bad={firstBad} server={view.chain_ok} count={all.length} checkedAt={checkedAt} loading={loading} onRecheck={() => load().catch(() => {})} follow={follow} setFollow={setFollow} />}

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Kind of event">
          {CATEGORIES.map((c) => (
            <button key={c.k} role="tab" aria-selected={cat === c.k} onClick={() => setCat(c.k)}
              className={cn("h-8 rounded-md px-2.5 text-[12.5px] font-[510] transition", cat === c.k ? "bg-foreground text-background" : "text-muted-foreground hover:bg-hover hover:text-foreground")}>
              {c.label}
              {c.k && counts[c.k] ? <span className={cn("ml-1.5 tabular-nums", cat === c.k ? "opacity-70" : "text-faint")}>{counts[c.k]}</span> : null}
            </button>
          ))}
        </div>
        <select value={agentId} onChange={(e) => setAgentId(e.target.value)} className={cn(inputCls, "h-8 w-full sm:ml-auto sm:w-auto sm:min-w-[170px]")} aria-label="Filter by agent">
          <option value="">All agents</option>
          {agents.map((a) => <option key={a.agent_id} value={a.agent_id}>{a.name}</option>)}
        </select>
      </div>
      <p className="mt-2 text-[11.5px] text-faint">
        {view ? `${forAgent.length} entries${agentId ? ` about ${names.get(agentId)}` : ""}${blocked ? `, ${blocked} blocked or revoked` : ""}. Routine checks are folded together.` : "Loading"}
        {hidden > 0 && (
          <>
            {" "}
            <button onClick={() => setRoutine(!routine)} className="font-[510] text-primary hover:underline">
              {routine ? "Hide" : "Show"} {hidden} setup and routine entries
            </button>
          </>
        )}
      </p>

      <div className={cn(cardCls, "mt-3 px-4 py-1.5 sm:px-5")}>
        {failed && !view ? (
          <EmptyState icon={ShieldAlert} tone="bad" title="Couldn't read the ledger" action={<Button onClick={() => load().catch(() => {})}><RefreshCw className="size-3.5" /> Try again</Button>}>
            The backend didn&apos;t answer. Check that it is running, then try again.
          </EmptyState>
        ) : !view ? (
          <p className="inline-flex items-center gap-2 py-6 text-[12.5px] text-faint"><Loader2 className="size-3.5 animate-spin" /> Reading the ledger…</p>
        ) : shown.length ? (
          <LedgerTimeline entries={shown} firstBad={firstBad} names={names} />
        ) : all.length ? (
          <EmptyState icon={FileClock} title="Nothing matches" action={<Button onClick={() => { setAgentId(""); setCat(""); setRoutine(true); }}>Show everything</Button>} />
        ) : (
          <EmptyState icon={FileClock} title="The ledger is empty" action={<Button variant="primary" onClick={onOnboard}><Plus className="size-3.5" /> Connect an agent</Button>}>
            Connecting an agent writes the first entry: its passport being issued.
          </EmptyState>
        )}
      </div>
      <p className="mt-3 text-[11.5px] leading-relaxed text-faint">
        Open any entry with the arrow to see its hash, the hash it links to, and the Crustdata sources behind it. The audit export is
        signed and can be checked offline with <code className="font-mono">scripts/verify_export.py</code>.
      </p>
    </main>
  );
}

function ChainBadge({
  bad, server, count, checkedAt, loading, onRecheck, follow, setFollow,
}: { bad: number | null | undefined; server: boolean; count: number; checkedAt?: Date; loading: boolean; onRecheck: () => void; follow: boolean; setFollow: (v: boolean) => void }) {
  const checking = bad === undefined;
  const ok = bad === null && server;
  return (
    <div className={cn("mt-5 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border px-4 py-3",
      checking ? "border-border-strong" : ok ? "border-verified/30 bg-verified/[0.05]" : "border-contradicted/35 bg-contradicted/[0.06]")}>
      {checking ? <Loader2 className="size-5 animate-spin text-faint" /> : ok ? <CheckCircle2 className="size-5 text-verified" /> : <XCircle className="size-5 text-contradicted" />}
      <div className="min-w-[200px] flex-1">
        <p className={cn("text-[14px] font-[620]", ok ? "text-verified" : !checking && "text-contradicted")}>
          {checking ? "Checking the chain…" : ok ? "Chain intact" : `Tampering detected at entry #${bad ?? "?"}`}
        </p>
        <p className="text-[12px] text-muted-foreground">
          {ok
            ? `All ${count} entries re-hashed in your browser and by the server${checkedAt ? ` at ${checkedAt.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}` : ""}. Nothing was changed, removed or reordered.`
            : checking ? "Re-hashing every entry in your browser." : "An entry was changed, removed or reordered. Everything from that point on can't be trusted."}
        </p>
      </div>
      <label className="flex items-center gap-2 text-[12px] text-muted-foreground" title="Re-read and re-hash the ledger every few seconds, so tampering shows up live">
        <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} className="accent-[var(--primary)]" /> Live
      </label>
      <Button onClick={onRecheck} disabled={loading}>
        {loading ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />} Re-check
      </Button>
    </div>
  );
}

/** Downloads the signed audit export (GET /api/ledger/export). Filtered to one agent when agentId is set. */
export function ExportButtons({ agentId }: { agentId?: string }) {
  const [busy, setBusy] = useState<"jsonl" | "csv" | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const run = async (f: "jsonl" | "csv") => {
    setBusy(f);
    setMsg(null);
    try {
      const name = await api.exportLedger(f, agentId);
      setMsg({ ok: true, text: `Saved ${name}` });
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  };
  return (
    <span className="flex flex-wrap items-center gap-2">
      {msg && <span className={cn("text-[11.5px]", msg.ok ? "text-verified" : "text-contradicted")}>{msg.text}</span>}
      <Button onClick={() => run("jsonl")} disabled={!!busy} title="Signed manifest plus every entry, exactly as stored. This is the evidence.">
        {busy === "jsonl" ? <Loader2 className="size-3.5 animate-spin" /> : <Download className="size-3.5" />} Export audit log
      </Button>
      <Button variant="ghost" onClick={() => run("csv")} disabled={!!busy} title="One row per entry, for a spreadsheet">
        {busy === "csv" ? <Loader2 className="size-3.5 animate-spin" /> : null} CSV
      </Button>
    </span>
  );
}


function mentions(e: LedgerEntry, agentId: string) {
  const p = e.payload as { agent_id?: string; subject?: string; passport?: { agent_id?: string } };
  return p.agent_id === agentId || p.subject === agentId || p.passport?.agent_id === agentId;
}
