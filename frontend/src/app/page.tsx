"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { Check, Download, FileText, Keyboard, Radio, Rows3, ShieldCheck, Table2, X } from "lucide-react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { BriefInput, EXAMPLES } from "@/components/brief";
import { Trace } from "@/components/trace";
import { Dossier } from "@/components/dossier";
import { CompareTable, ShortlistRows, type Row, type SortKey } from "@/components/shortlist";
import { API_URL, streamRun, type RunMode } from "@/lib/stream";
import { claimCounts, evidenceStrength, initialRun, runReducer } from "@/lib/run-state";
import { download, toCSV, toMarkdown } from "@/lib/export";
import type { Criteria } from "@/lib/types";
import { cn } from "@/lib/utils";

function useWide() {
  const [wide, setWide] = useState(true);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1280px)");
    const on = () => setWide(mq.matches);
    on();
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return wide;
}

const toggle = (s: Set<string>, id: string) => {
  const n = new Set(s);
  if (n.has(id)) n.delete(id);
  else n.add(id);
  return n;
};

export default function Home() {
  const [brief, setBrief] = useState(EXAMPLES[0].brief);
  const [lastBrief, setLastBrief] = useState("");
  const [mode, setMode] = useState<RunMode>(process.env.NEXT_PUBLIC_DEFAULT_MODE === "live" ? "live" : "replay");
  const [run, dispatch] = useReducer(runReducer, initialRun);
  const [selected, setSelected] = useState<string>();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [pinned, setPinned] = useState<Set<string>>(new Set());
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [view, setView] = useState<"list" | "compare">("list");
  const [hideContra, setHideContra] = useState(false);
  const [sort, setSort] = useState<SortKey>("rank");
  const [dir, setDir] = useState<1 | -1>(1);
  const [help, setHelp] = useState(false);
  const [now, setNow] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const briefRef = useRef<HTMLTextAreaElement>(null);
  const wide = useWide();

  useEffect(() => {
    const m = new URLSearchParams(window.location.search).get("mode");
    if (m === "live" || m === "replay") setMode(m);
  }, []);

  useEffect(() => {
    if (!run.running) return;
    const id = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(id);
  }, [run.running]);

  const start = useCallback(async () => {
    if (!brief.trim()) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setSelected(undefined);
    setSheetOpen(false);
    setPinned(new Set());
    setDismissed(new Set());
    setDrafts({});
    setLastBrief(brief);
    setNow(Date.now());
    dispatch({ type: "start", at: Date.now() });
    try {
      for await (const ev of streamRun(brief, mode, ctrl.signal)) dispatch({ type: "event", ev, at: Date.now() });
      dispatch({ type: "stop", at: Date.now() });
    } catch (e) {
      if (ctrl.signal.aborted) return dispatch({ type: "stop", at: Date.now() });
      const msg = e instanceof Error ? e.message : String(e);
      dispatch({ type: "fatal", at: Date.now(), message: mode === "live" ? `Couldn't reach the agent at ${API_URL}. ${msg}` : msg });
    }
  }, [brief, mode]);

  const stop = () => {
    abortRef.current?.abort();
    dispatch({ type: "stop", at: Date.now() });
  };

  // Rank = backend order if given, else score. Pinned float up, passed sink down.
  const rows: Row[] = useMemo(() => {
    const pos = new Map((run.order ?? []).map((id, i) => [id, i]));
    const base = Object.values(run.candidates).sort(
      (a, b) => (pos.get(a.id) ?? 1e9) - (pos.get(b.id) ?? 1e9) || (b.score ?? -1) - (a.score ?? -1),
    );
    const ranked = base.map((c, i) => ({ c, rank: i + 1, pinned: pinned.has(c.id), dismissed: dismissed.has(c.id), fresh: false }));
    const val = (r: Row): number | string => {
      switch (sort) {
        case "fit": return r.c.score ?? -1;
        case "evidence": return evidenceStrength(r.c);
        case "contradicted": return claimCounts(r.c).contradicted;
        case "name": return r.c.name.toLowerCase();
        default: return r.rank;
      }
    };
    const desc = sort === "fit" || sort === "evidence" || sort === "contradicted";
    return ranked
      .filter((r) => !(hideContra && claimCounts(r.c).contradicted > 0))
      .sort((a, b) => {
        const g = (r: Row) => (r.pinned ? 0 : r.dismissed ? 2 : 1);
        if (g(a) !== g(b)) return g(a) - g(b);
        const va = val(a), vb = val(b);
        const cmp = va < vb ? -1 : va > vb ? 1 : 0;
        return cmp * (desc ? -1 : 1) * dir;
      });
  }, [run.candidates, run.order, pinned, dismissed, hideContra, sort, dir]);

  // Auto-select the top candidate on wide screens so the dossier is never empty.
  useEffect(() => {
    if (wide && !selected && rows.length) setSelected(rows[0].c.id);
  }, [wide, selected, rows]);

  const select = (id: string) => {
    setSelected(id);
    if (!wide) setSheetOpen(true);
  };

  const move = useCallback(
    (delta: number) => {
      if (!rows.length) return;
      const i = rows.findIndex((r) => r.c.id === selected);
      const next = rows[Math.max(0, Math.min(rows.length - 1, (i < 0 ? -1 : i) + delta))];
      setSelected(next.c.id);
      document.querySelector(`[data-row="${next.c.id}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    },
    [rows, selected],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "TEXTAREA" || t.tagName === "INPUT") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key;
      if (k === "j" || k === "ArrowDown") { e.preventDefault(); move(1); }
      else if (k === "k" || k === "ArrowUp") { e.preventDefault(); move(-1); }
      else if (k === "/") { e.preventDefault(); briefRef.current?.focus(); }
      else if (k === "?") setHelp((h) => !h);
      else if (k === "v") setView((v) => (v === "list" ? "compare" : "list"));
      else if (k === "h") setHideContra((h) => !h);
      else if (k === "Enter" && selected && !wide) setSheetOpen(true);
      else if (k === "p" && selected) setPinned((s) => toggle(s, selected));
      else if (k === "x" && selected) setDismissed((s) => toggle(s, selected));
      else if (k === "c" && selected) {
        const txt = drafts[selected] ?? run.candidates[selected]?.outreach_draft;
        if (txt) navigator.clipboard.writeText(txt).catch(() => {});
      } else if (k === "Escape") { setHelp(false); setSheetOpen(false); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [move, selected, wide, drafts, run.candidates]);

  const exportRows = () =>
    rows.filter((r) => !r.dismissed).map((r) => ({ ...r.c, outreach_draft: drafts[r.c.id] ?? r.c.outreach_draft }));

  const onSort = (k: SortKey) => {
    if (k === sort) setDir((d) => (d === 1 ? -1 : 1));
    else { setSort(k); setDir(1); }
  };

  const started = run.running || run.log.length > 0 || !!run.fatal;
  const elapsed = run.startedAt ? Math.max(0, (run.endedAt ?? (run.running ? now : run.startedAt)) - run.startedAt) / 1000 : 0;
  const cur = selected ? run.candidates[selected] : undefined;
  const curRow = rows.find((r) => r.c.id === selected);
  const totals = rows.reduce(
    (t, r) => {
      const k = claimCounts(r.c);
      return { v: t.v + k.verified, x: t.x + k.contradicted, u: t.u + k.unverifiable };
    },
    { v: 0, x: 0, u: 0 },
  );

  const dossier = cur && curRow && (
    <Dossier
      candidate={cur}
      rank={curRow.rank}
      pinned={pinned.has(cur.id)}
      dismissed={dismissed.has(cur.id)}
      draft={drafts[cur.id]}
      onDraft={(t) => setDrafts((d) => ({ ...d, [cur.id]: t }))}
      onPin={() => setPinned((s) => toggle(s, cur.id))}
      onDismiss={() => setDismissed((s) => toggle(s, cur.id))}
    />
  );

  return (
    <div className="min-h-screen">
      <TopBar mode={mode} setMode={setMode} running={run.running} done={run.done} elapsed={elapsed} started={started} onHelp={() => setHelp((h) => !h)} />

      {!started ? (
        <Hero brief={brief} setBrief={setBrief} onRun={start} briefRef={briefRef} mode={mode} />
      ) : (
        <main className="mx-auto grid max-w-[1680px] lg:grid-cols-[300px_minmax(0,1fr)] xl:grid-cols-[300px_minmax(0,1fr)_minmax(0,500px)] 2xl:grid-cols-[320px_minmax(0,1fr)_minmax(0,560px)]">
          <aside className="order-last border-t border-border px-4 py-4 lg:order-none lg:sticky lg:border-t-0 lg:top-12 lg:h-[calc(100vh-3rem)] lg:overflow-y-auto lg:border-r">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-[12px] font-[510] text-muted-foreground">Agent run</h2>
              <span className="rounded-full border border-border-strong px-1.5 font-mono text-[10.5px] text-muted-foreground">
                {mode === "live" ? "live · crustdata" : "replay"}
              </span>
            </div>
            <Trace run={run} now={now} />
          </aside>

          <section className="min-w-0">
            <div className="sticky top-12 z-20 border-b border-border bg-background/80 px-4 py-3 backdrop-blur-xl">
              <BriefInput ref={briefRef} value={brief} onChange={setBrief} onRun={start} onStop={stop} running={run.running} compact />
              {run.criteria && <CriteriaChips criteria={run.criteria} />}
            </div>

            {run.fatal && (
              <div className="mx-4 mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-contradicted/30 bg-contradicted/[0.08] px-3 py-2.5 text-[13px]">
                <span>
                  <span className="font-[510] text-contradicted">Run failed.</span> <span className="text-secondary">{run.fatal}</span>
                </span>
                {mode === "live" && (
                  <button onClick={() => setMode("replay")} className="h-7 rounded-md border border-border-strong bg-elevated px-2.5 text-[12px] font-[510] hover:bg-hover">
                    Switch to replay
                  </button>
                )}
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-2 px-4 pb-2 pt-4">
              <div className="flex items-baseline gap-2">
                <h1 className="text-[15px] font-[590]">Shortlist</h1>
                <span className="font-mono text-[12px] text-muted-foreground tabular-nums">{rows.length}</span>
                <Funnel summary={run.summary} totals={totals} />
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <Seg
                  value={view}
                  onChange={setView}
                  options={[
                    { v: "list", label: "List", icon: <Rows3 className="size-3.5" /> },
                    { v: "compare", label: "Compare", icon: <Table2 className="size-3.5" /> },
                  ]}
                />
                <button
                  onClick={() => setHideContra((h) => !h)}
                  className={cn(
                    "inline-flex h-7 items-center gap-1.5 rounded-md border px-2.5 text-[12px] font-[510] transition",
                    hideContra ? "border-contradicted/40 bg-contradicted/10 text-contradicted" : "border-border-strong bg-elevated text-secondary hover:bg-hover",
                  )}
                  title="Hide candidates with any contradicted claim (H)"
                >
                  {hideContra ? <X className="size-3.5" /> : <ShieldCheck className="size-3.5" />}
                  {hideContra ? "Contradicted hidden" : "Clean records only"}
                </button>
                <ExportMenu
                  disabled={!rows.length}
                  onMd={() => download("shortlist.md", toMarkdown(lastBrief, run.criteria, exportRows()), "text/markdown")}
                  onCsv={() => download("shortlist.csv", toCSV(exportRows()), "text/csv")}
                  onJson={() => download("shortlist.json", JSON.stringify({ brief: lastBrief, criteria: run.criteria, candidates: exportRows() }, null, 2), "application/json")}
                />
              </div>
            </div>

            <div className="border-t border-border">
              {rows.length ? (
                view === "list" ? (
                  <ShortlistRows rows={rows} selected={selected} onSelect={select} />
                ) : (
                  <CompareTable rows={rows} selected={selected} onSelect={select} sort={sort} dir={dir} onSort={onSort} />
                )
              ) : (
                <Empty running={run.running} done={run.done} filtered={hideContra && Object.keys(run.candidates).length > 0} />
              )}
            </div>
            {rows.length > 0 && (
              <p className="hidden flex-wrap items-center gap-x-4 gap-y-1 whitespace-nowrap px-4 py-3 text-[11.5px] text-faint sm:flex">
                <span className="inline-flex items-center gap-1"><kbd>J</kbd><kbd>K</kbd> move</span>
                <span className="inline-flex items-center gap-1"><kbd>P</kbd> pin</span>
                <span className="inline-flex items-center gap-1"><kbd>X</kbd> pass</span>
                <span className="inline-flex items-center gap-1"><kbd>C</kbd> copy outreach</span>
                <span className="inline-flex items-center gap-1"><kbd>V</kbd> compare</span>
                <span className="inline-flex items-center gap-1"><kbd>?</kbd> shortcuts</span>
              </p>
            )}
          </section>

          {wide && (
            <aside className="sticky top-12 hidden h-[calc(100vh-3rem)] overflow-y-auto border-l border-border bg-panel xl:block">
              {dossier ?? (
                <div className="grid h-full place-items-center p-8 text-center text-[13px] text-faint">
                  {run.running ? "The top candidate opens here as soon as their claims are checked." : "Select a candidate."}
                </div>
              )}
            </aside>
          )}
        </main>
      )}

      {!wide && (
        <Sheet open={sheetOpen && !!dossier} onOpenChange={setSheetOpen}>
          <SheetContent className="border-border bg-panel">
            <SheetTitle className="sr-only">{cur?.name ?? "Candidate"}</SheetTitle>
            <div className="h-full overflow-y-auto pt-6">{dossier}</div>
          </SheetContent>
        </Sheet>
      )}

      {help && <Shortcuts onClose={() => setHelp(false)} />}
    </div>
  );
}

function Logo() {
  return (
    <span className="relative grid size-6 place-items-center rounded-md bg-gradient-to-br from-primary to-primary-strong shadow-[inset_0_1px_0_rgba(255,255,255,0.25)]">
      <Check className="size-3.5 text-white" strokeWidth={3} />
    </span>
  );
}

function TopBar({
  mode, setMode, running, done, elapsed, started, onHelp,
}: { mode: RunMode; setMode: (m: RunMode) => void; running: boolean; done: boolean; elapsed: number; started: boolean; onHelp: () => void }) {
  return (
    <header className="sticky top-0 z-30 h-12 border-b border-border bg-background/80 backdrop-blur-xl">
      <div className="mx-auto flex h-full max-w-[1680px] items-center justify-between gap-4 px-4">
        <Link href="/" className="flex items-center gap-2">
          <Logo />
          <span className="text-[14px] font-[590] tracking-[-0.01em]">Sourced</span>
          <span className="hidden rounded-full border border-border-strong px-1.5 text-[10.5px] font-[510] text-muted-foreground sm:inline">on Crustdata</span>
        </Link>
        <div className="flex items-center gap-2.5">
          {started && (
            <span className="hidden items-center gap-1.5 font-mono text-[11px] text-muted-foreground tabular-nums sm:flex">
              <span className={cn("size-1.5 rounded-full", running ? "animate-pulse bg-primary" : done ? "bg-verified" : "bg-faint")} />
              {running ? "running" : done ? "done" : "stopped"} · {elapsed.toFixed(1)}s
            </span>
          )}
          <Seg
            value={mode}
            onChange={(m) => !running && setMode(m)}
            options={[
              { v: "replay", label: "Replay" },
              { v: "live", label: "Live", icon: <Radio className="size-3" /> },
            ]}
          />
          <button onClick={onHelp} className="hidden size-7 place-items-center rounded-md text-muted-foreground hover:bg-elevated hover:text-foreground sm:grid" aria-label="Keyboard shortcuts">
            <Keyboard className="size-4" />
          </button>
        </div>
      </div>
    </header>
  );
}

function Hero({ brief, setBrief, onRun, briefRef, mode }: { brief: string; setBrief: (s: string) => void; onRun: () => void; briefRef: React.Ref<HTMLTextAreaElement>; mode: RunMode }) {
  return (
    <main className="relative overflow-hidden">
      <div className="hero-grid pointer-events-none absolute inset-0" />
      <div className="pointer-events-none absolute left-1/2 top-[-240px] h-[520px] w-[900px] -translate-x-1/2 rounded-full bg-[radial-gradient(closest-side,var(--glow),transparent)]" />
      <div className="relative mx-auto flex max-w-[760px] flex-col items-center px-4 pb-24 pt-20 text-center sm:pt-28">
        <span className="inline-flex items-center gap-2 rounded-full border border-border-strong bg-panel/70 py-1 pl-1 pr-3 text-[12px] text-secondary backdrop-blur">
          <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[11px] font-[590] text-primary">New</span>
          Every claim checked against Crustdata&apos;s people graph
        </span>
        <h1 className="mt-6 text-[44px] font-[590] leading-[1.02] tracking-[-0.035em] sm:text-[64px]">
          Hire from evidence,
          <br />
          <span className="bg-gradient-to-b from-foreground to-muted-foreground bg-clip-text text-transparent">not from profiles.</span>
        </h1>
        <p className="mt-5 max-w-[520px] text-[16px] leading-relaxed text-muted-foreground">
          Paste any hiring brief. The agent searches, enriches and verifies every candidate, then gives you a ranked shortlist where each line cites its source.
        </p>
        <div className="mt-9 w-full text-left">
          <BriefInput
            ref={briefRef}
            value={brief}
            onChange={setBrief}
            onRun={onRun}
            onStop={() => {}}
            running={false}
            footer={
              <span className="inline-flex items-center gap-1.5 text-[11.5px] text-faint">
                <span className={cn("size-1.5 rounded-full", mode === "live" ? "bg-verified" : "bg-flag")} />
                {mode === "live" ? "Live: calls the agent backend" : "Replay: recorded run, no backend needed"}
              </span>
            }
          />
        </div>
        <div className="mt-3 flex flex-wrap justify-center gap-1.5">
          {EXAMPLES.map((ex) => (
            <button
              key={ex.label}
              onClick={() => setBrief(ex.brief)}
              className={cn(
                "h-7 rounded-full border px-3 text-[12px] font-[510] transition",
                brief === ex.brief ? "border-primary/50 bg-primary/10 text-foreground" : "border-border-strong bg-panel/60 text-muted-foreground hover:text-foreground",
              )}
              title={ex.brief}
            >
              {ex.label}
            </button>
          ))}
        </div>

        <div className="mt-20 grid w-full overflow-hidden rounded-xl border border-border bg-panel/60 text-left backdrop-blur sm:grid-cols-3">
          {[
            ["Search", "Expands the brief into title variants and searches the people graph. If nothing comes back it broadens the search instead of giving up.", "person/search"],
            ["Verify", "Checks employer, tenure, location and company stage against enrich data, and marks each claim verified, contradicted or unverifiable.", "person/enrich · company/enrich"],
            ["Cite", "Ranks candidates with reasons that link to the evidence, then drafts outreach. Nothing is ever sent.", "claim ids → sources"],
          ].map(([t, d, tool], i) => (
            <div key={t} className={cn("p-5", i > 0 && "border-t border-border sm:border-l sm:border-t-0")}>
              <div className="font-mono text-[10.5px] text-faint">0{i + 1}</div>
              <h3 className="mt-2 text-[15px] font-[590]">{t}</h3>
              <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">{d}</p>
              <p className="mt-3 font-mono text-[10.5px] text-primary/80">{tool}</p>
            </div>
          ))}
        </div>
      </div>
    </main>
  );
}

function Funnel({ summary, totals }: { summary?: Record<string, number | undefined>; totals: { v: number; x: number; u: number } }) {
  const parts: string[] = [];
  if (summary?.searched !== undefined) parts.push(`${summary.searched} searched`);
  if (summary?.enriched !== undefined) parts.push(`${summary.enriched} enriched`);
  return (
    <span className="ml-2 hidden items-center gap-2 text-[12px] text-faint md:inline-flex">
      {parts.length > 0 && <span>{parts.join(" → ")}</span>}
      {totals.v + totals.x + totals.u > 0 && (
        <span className="inline-flex items-center gap-2">
          <span className="inline-flex items-center gap-1"><span className="size-1.5 rounded-full bg-verified" />{totals.v}</span>
          <span className="inline-flex items-center gap-1"><span className="size-1.5 rounded-full bg-contradicted" />{totals.x}</span>
          <span className="inline-flex items-center gap-1"><span className="size-1.5 rounded-full bg-faint" />{totals.u}</span>
        </span>
      )}
    </span>
  );
}

function CriteriaChips({ criteria: c }: { criteria: Criteria }) {
  const chips: { k: string; v: string }[] = [];
  if (c.role) chips.push({ k: "Role", v: c.role + (c.seniority ? ` · ${c.seniority}` : "") });
  for (const l of c.locations ?? []) chips.push({ k: "in", v: l });
  for (const s of c.skills ?? []) chips.push({ k: "skill", v: s });
  for (const s of c.company_preferences ?? []) chips.push({ k: "from", v: s });
  for (const s of c.must_haves ?? []) chips.push({ k: "must", v: s });
  const extra = (c.title_variants?.length ?? 0) + (c.nice_to_haves?.length ?? 0);
  const shown = chips.slice(0, 7);
  const more = chips.length - shown.length + extra;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5 animate-fade">
      <span className="text-[11.5px] text-faint">Understood as</span>
      {shown.map((ch, i) => (
        <span key={i} className="inline-flex h-6 items-center gap-1 rounded-md border border-border-strong bg-panel px-2 text-[12px]">
          <span className="text-faint">{ch.k}</span>
          <span className="font-[510]">{ch.v}</span>
        </span>
      ))}
      {more > 0 && (
        <span
          className="inline-flex h-6 items-center rounded-md border border-dashed border-border-strong px-2 text-[12px] text-muted-foreground"
          title={[...(c.title_variants ?? []).map((t) => `title: ${t}`), ...(c.nice_to_haves ?? []).map((t) => `nice: ${t}`)].join("\n")}
        >
          +{more} more
        </span>
      )}
    </div>
  );
}

function Seg<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: { v: T; label: string; icon?: React.ReactNode }[] }) {
  return (
    <div className="inline-flex h-7 items-center rounded-md border border-border-strong bg-panel p-0.5 text-[12px]" role="radiogroup">
      {options.map((o) => (
        <button
          key={o.v}
          role="radio"
          aria-checked={value === o.v}
          onClick={() => onChange(o.v)}
          className={cn(
            "inline-flex h-full items-center gap-1.5 rounded px-2 font-[510] transition",
            value === o.v ? "bg-elevated text-foreground shadow-[0_0_0_1px_var(--border-strong)]" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.icon}
          {o.label}
        </button>
      ))}
    </div>
  );
}

function ExportMenu({ disabled, onMd, onCsv, onJson }: { disabled: boolean; onMd: () => void; onCsv: () => void; onJson: () => void }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, [open]);
  return (
    <div className="relative">
      <button
        disabled={disabled}
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o); }}
        className="inline-flex h-7 items-center gap-1.5 rounded-md border border-border-strong bg-elevated px-2.5 text-[12px] font-[510] text-secondary hover:bg-hover disabled:opacity-40"
      >
        <Download className="size-3.5" /> Export
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-1 w-60 overflow-hidden rounded-lg border border-border-strong bg-elevated p-1 shadow-[var(--shadow)] animate-fade">
          {[
            ["Markdown report", "Every claim with its source", onMd],
            ["CSV", "For a spreadsheet or ATS", onCsv],
            ["JSON", "Raw shortlist", onJson],
          ].map(([l, d, fn]) => (
            <button key={l as string} onClick={fn as () => void} className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-hover">
              <FileText className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
              <span>
                <span className="block text-[13px] font-[510]">{l as string}</span>
                <span className="block text-[11.5px] text-muted-foreground">{d as string}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Empty({ running, done, filtered }: { running: boolean; done: boolean; filtered: boolean }) {
  if (running)
    return (
      <div className="flex flex-col">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-3 border-b border-border px-4 py-3.5">
            <div className="size-8 animate-pulse rounded-full bg-elevated" style={{ animationDelay: `${i * 120}ms` }} />
            <div className="flex-1 space-y-1.5">
              <div className="h-3 w-40 animate-pulse rounded bg-elevated" style={{ animationDelay: `${i * 120}ms` }} />
              <div className="h-2.5 w-64 animate-pulse rounded bg-elevated/70" style={{ animationDelay: `${i * 120}ms` }} />
            </div>
          </div>
        ))}
        <p className="px-4 py-4 text-[12.5px] text-faint">Candidates show up here as soon as their claims have been checked.</p>
      </div>
    );
  return (
    <div className="px-4 py-16 text-center">
      {filtered ? (
        <p className="text-[13px] text-muted-foreground">Every candidate has at least one contradicted claim. Press <kbd>H</kbd> to show them.</p>
      ) : done ? (
        <>
          <p className="text-[15px] font-[590]">No one matched.</p>
          <p className="mt-1 text-[13px] text-muted-foreground">Try fewer must-haves or a wider location.</p>
        </>
      ) : (
        <p className="text-[13px] text-faint">No candidates yet.</p>
      )}
    </div>
  );
}

function Shortcuts({ onClose }: { onClose: () => void }) {
  const keys: [string, string][] = [
    ["⌘ ↵", "Run the brief"],
    ["/", "Edit the brief"],
    ["J / ↓", "Next candidate"],
    ["K / ↑", "Previous candidate"],
    ["P", "Pin candidate to top"],
    ["X", "Pass on candidate"],
    ["C", "Copy outreach draft"],
    ["V", "Switch list / compare"],
    ["H", "Clean records only"],
    ["Esc", "Close"],
  ];
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-sm animate-fade" onClick={onClose}>
      <div className="w-full max-w-sm rounded-xl border border-border-strong bg-elevated p-5 shadow-[var(--shadow)]" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-[15px] font-[590]">Keyboard shortcuts</h3>
        <dl className="mt-4 grid grid-cols-[72px_1fr] gap-y-2 text-[13px]">
          {keys.map(([k, d]) => (
            <div key={k} className="contents">
              <dt><kbd>{k}</kbd></dt>
              <dd className="text-secondary">{d}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
