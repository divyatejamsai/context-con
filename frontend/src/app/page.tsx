"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { Check, ChevronDown, Download, FileText, Keyboard, Radio, Rows3, ShieldCheck, Table2, X } from "lucide-react";
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
  const [openTiers, setOpenTiers] = useState({ near: false, other: false });
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
    setOpenTiers({ near: false, other: false });
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
  const allRows: Row[] = useMemo(() => {
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

  // Backend splits the ranked pool into a shortlist and near misses; anything else is below the bar.
  // Without those fields every candidate counts as shortlisted.
  const tiers = useMemo(() => {
    const sl = run.shortlist ? new Set(run.shortlist) : null;
    const nm = new Set(run.nearMiss ?? []);
    const tier = (id: string) => (!sl || sl.has(id) ? "main" : nm.has(id) ? "near" : "other");
    return {
      main: allRows.filter((r) => tier(r.c.id) === "main"),
      near: allRows.filter((r) => tier(r.c.id) === "near"),
      other: allRows.filter((r) => tier(r.c.id) === "other"),
    };
  }, [allRows, run.shortlist, run.nearMiss]);
  const rows = useMemo(
    () => [...tiers.main, ...(openTiers.near ? tiers.near : []), ...(openTiers.other ? tiers.other : [])],
    [tiers, openTiers],
  );

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
    tiers.main.filter((r) => !r.dismissed).map((r) => ({ ...r.c, outreach_draft: drafts[r.c.id] ?? r.c.outreach_draft }));

  const onSort = (k: SortKey) => {
    if (k === sort) setDir((d) => (d === 1 ? -1 : 1));
    else { setSort(k); setDir(1); }
  };

  const started = run.running || run.log.length > 0 || !!run.fatal;
  const elapsed = run.startedAt ? Math.max(0, (run.endedAt ?? (run.running ? now : run.startedAt)) - run.startedAt) / 1000 : 0;
  const cur = selected ? run.candidates[selected] : undefined;
  const curRow = rows.find((r) => r.c.id === selected);
  const totals = tiers.main.reduce(
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
        <main className="mx-auto grid max-w-[1680px] grid-cols-[minmax(0,1fr)] gap-5 px-4 py-5 lg:grid-cols-[300px_minmax(0,1fr)] xl:grid-cols-[300px_minmax(0,1fr)_minmax(0,500px)] 2xl:grid-cols-[320px_minmax(0,1fr)_minmax(0,560px)]">
          <aside className="order-last min-w-0 lg:order-none lg:sticky lg:top-[76px] lg:max-h-[calc(100vh-96px)] lg:self-start lg:overflow-y-auto lg:pb-2 lg:pr-1">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="font-display text-[20px] font-extrabold tracking-tight">Agent run</h2>
              <span className="rounded-full border-2 border-ink bg-panel px-2 font-mono text-[10.5px] font-bold">{mode === "live" ? "LIVE · CRUSTDATA" : "REPLAY"}</span>
            </div>
            <Trace run={run} now={now} />
          </aside>

          <section className="min-w-0">
            <BriefInput ref={briefRef} value={brief} onChange={setBrief} onRun={start} onStop={stop} running={run.running} compact />
            {run.criteria && <CriteriaChips criteria={run.criteria} />}

            {run.fatal && (
              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border-2 border-ink bg-coral px-4 py-3 text-[13.5px] font-semibold text-on-color shadow-brut">
                <span>
                  <span className="font-extrabold">Run failed.</span> {run.fatal}
                </span>
                {mode === "live" && (
                  <button onClick={() => setMode("replay")} className="press h-8 rounded-lg border-2 border-[#111] bg-white px-3 text-[12.5px] font-bold text-[#111] shadow-[2px_2px_0_0_#111]">
                    Switch to replay
                  </button>
                )}
              </div>
            )}

            <Stats summary={run.summary} shortlisted={tiers.main.length} totals={totals} running={run.running} />

            <div className="mb-4 mt-6 flex flex-wrap items-center justify-between gap-2">
              <h1 className="font-display flex items-baseline gap-2 text-[26px] font-extrabold tracking-tight">
                Shortlist
                <span className="rounded-full border-2 border-ink bg-yellow px-2 text-[14px] text-on-color tabular-nums">{tiers.main.length}</span>
              </h1>
              <div className="flex flex-wrap items-center gap-2">
                <Seg
                  value={view}
                  onChange={setView}
                  options={[
                    { v: "list", label: "Cards", icon: <Rows3 className="size-3.5" /> },
                    { v: "compare", label: "Compare", icon: <Table2 className="size-3.5" /> },
                  ]}
                />
                <button
                  onClick={() => setHideContra((h) => !h)}
                  className={cn("press inline-flex h-8 items-center gap-1.5 rounded-lg border-2 border-ink px-2.5 text-[12.5px] font-bold shadow-brut-sm", hideContra ? "bg-coral text-on-color" : "bg-panel")}
                  title="Hide candidates with any contradicted claim (H)"
                >
                  {hideContra ? <X className="size-3.5" /> : <ShieldCheck className="size-3.5" />}
                  {hideContra ? "Contradicted hidden" : "Clean records only"}
                </button>
                <ExportMenu
                  disabled={!tiers.main.length}
                  onMd={() => download("shortlist.md", toMarkdown(lastBrief, run.criteria, exportRows()), "text/markdown")}
                  onCsv={() => download("shortlist.csv", toCSV(exportRows()), "text/csv")}
                  onJson={() => download("shortlist.json", JSON.stringify({ brief: lastBrief, criteria: run.criteria, candidates: exportRows() }, null, 2), "application/json")}
                />
              </div>
            </div>

            <div className="pl-2.5 pt-2.5">
              {tiers.main.length || tiers.near.length || tiers.other.length ? (
                <div className="flex flex-col gap-6">
                  {tiers.main.length > 0 &&
                    (view === "list" ? (
                      <ShortlistRows rows={tiers.main} selected={selected} onSelect={select} />
                    ) : (
                      <CompareTable rows={tiers.main} selected={selected} onSelect={select} sort={sort} dir={dir} onSort={onSort} />
                    ))}
                  {(
                    [
                      ["near", "Near misses", "Just under the bar. Worth a look if the shortlist is thin.", "bg-yellow"],
                      ["other", "Below the bar", "Searched and checked, but not a fit for this brief.", "bg-elevated"],
                    ] as const
                  ).map(([key, title, sub, bg]) =>
                    tiers[key].length ? (
                      <div key={key} className={cn(key === "other" && "opacity-70")}>
                        <button
                          onClick={() => setOpenTiers((t) => ({ ...t, [key]: !t[key] }))}
                          className="press flex w-full items-center justify-between gap-3 rounded-xl border-2 border-dashed border-ink bg-panel px-4 py-3 text-left"
                          aria-expanded={openTiers[key]}
                        >
                          <span>
                            <span className="font-display flex items-center gap-2 text-[17px] font-extrabold">
                              {title}
                              <span className={cn("rounded-full border-2 border-ink px-1.5 text-[12px] text-[#111] tabular-nums", bg)}>{tiers[key].length}</span>
                            </span>
                            <span className="text-[12.5px] font-medium text-muted-foreground">{sub}</span>
                          </span>
                          <ChevronDown className={cn("size-5 shrink-0 transition-transform", openTiers[key] && "rotate-180")} strokeWidth={2.5} />
                        </button>
                        {openTiers[key] && (
                          <div className="mt-4 animate-fade">
                            {view === "list" ? (
                              <ShortlistRows rows={tiers[key]} selected={selected} onSelect={select} />
                            ) : (
                              <CompareTable rows={tiers[key]} selected={selected} onSelect={select} sort={sort} dir={dir} onSort={onSort} />
                            )}
                          </div>
                        )}
                      </div>
                    ) : null,
                  )}
                  {!tiers.main.length && !run.running && (
                    <p className="text-[13.5px] font-semibold">Nobody cleared the bar for this brief. Open the near misses above, or loosen the must-haves.</p>
                  )}
                </div>
              ) : (
                <Empty running={run.running} done={run.done} filtered={hideContra && Object.keys(run.candidates).length > 0} />
              )}
            </div>
            {rows.length > 0 && (
              <p className="mt-5 hidden flex-wrap items-center gap-x-4 gap-y-1 whitespace-nowrap text-[12px] font-medium text-muted-foreground sm:flex">
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
            <aside className="sticky top-[76px] hidden max-h-[calc(100vh-96px)] self-start overflow-hidden rounded-xl border-2 border-ink bg-panel shadow-brut-lg xl:block">
              <div className="max-h-[calc(100vh-100px)] overflow-y-auto">
                {dossier ?? (
                  <div className="grid min-h-80 place-items-center p-8 text-center">
                    <div>
                      <div className="font-display text-[44px] font-extrabold leading-none">👀</div>
                      <p className="mt-3 text-[14px] font-semibold">{run.running ? "The top candidate lands here once their claims are checked." : "Pick a candidate."}</p>
                    </div>
                  </div>
                )}
              </div>
            </aside>
          )}
        </main>
      )}

      {!wide && (
        <Sheet open={sheetOpen && !!dossier} onOpenChange={setSheetOpen}>
          <SheetContent className="border-l-2 border-ink bg-panel">
            <SheetTitle className="sr-only">{cur?.name ?? "Candidate"}</SheetTitle>
            <div className="h-full overflow-y-auto">{dossier}</div>
          </SheetContent>
        </Sheet>
      )}

      {help && <Shortcuts onClose={() => setHelp(false)} />}
    </div>
  );
}

function Logo() {
  return (
    <span className="grid size-8 -rotate-6 place-items-center rounded-lg border-2 border-ink bg-yellow shadow-brut-sm">
      <Check className="size-4 text-[#111]" strokeWidth={4} />
    </span>
  );
}

function TopBar({
  mode, setMode, running, done, elapsed, started, onHelp,
}: { mode: RunMode; setMode: (m: RunMode) => void; running: boolean; done: boolean; elapsed: number; started: boolean; onHelp: () => void }) {
  return (
    <header className="sticky top-0 z-30 h-14 border-b-2 border-ink bg-background/95 backdrop-blur">
      <div className="mx-auto flex h-full max-w-[1680px] items-center justify-between gap-4 px-4">
        <Link href="/" className="flex items-center gap-2.5">
          <Logo />
          <span className="font-display text-[22px] font-extrabold tracking-[-0.03em]">Sourced</span>
          <span className="hidden rotate-2 rounded-md border-2 border-ink bg-lavender px-1.5 text-[10.5px] font-extrabold uppercase tracking-wider text-on-color sm:inline">on Crustdata</span>
        </Link>
        <div className="flex items-center gap-2.5">
          {started && (
            <span className="hidden items-center gap-1.5 rounded-full border-2 border-ink bg-panel px-2.5 py-0.5 font-mono text-[11px] font-bold tabular-nums sm:flex">
              <span className={cn("size-2 rounded-full border border-ink", running ? "animate-pulse bg-yellow" : done ? "bg-lime" : "bg-elevated")} />
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
          <button onClick={onHelp} className="press hidden size-8 place-items-center rounded-lg border-2 border-ink bg-panel shadow-brut-sm sm:grid" aria-label="Keyboard shortcuts">
            <Keyboard className="size-4" />
          </button>
        </div>
      </div>
    </header>
  );
}

const TICKER = [
  ["verified", "Works at the company they say · person/enrich"],
  ["contradicted", "Says Bengaluru, graph says Pune · person/enrich"],
  ["verified", "5+ yrs in payments · company/enrich"],
  ["unverifiable", "“Led the rewrite”, no second source · web/search"],
  ["verified", "Changed jobs 3 weeks ago · person/enrich"],
  ["contradicted", "“Ex-startup”, every employer 5k+ staff · company/enrich"],
  ["verified", "Team is hiring right now · job/search"],
] as const;

function Hero({ brief, setBrief, onRun, briefRef, mode }: { brief: string; setBrief: (s: string) => void; onRun: () => void; briefRef: React.Ref<HTMLTextAreaElement>; mode: RunMode }) {
  return (
    <main>
      <section className="relative mx-auto max-w-[1100px] px-4 pb-14 pt-14 sm:pt-20">
        <span className="absolute right-4 top-10 hidden animate-wiggle rounded-full border-2 border-ink bg-pink px-3 py-1.5 text-[13px] font-extrabold text-on-color shadow-brut md:block">
          0 humans in the loop
        </span>
        <span className="absolute left-2 top-48 hidden -rotate-12 rounded-lg border-2 border-ink bg-sky px-2.5 py-1 text-[12px] font-extrabold text-on-color shadow-brut-sm lg:block">
          ✦ every claim cited
        </span>
        <div className="mx-auto max-w-[860px] text-center">
          <span className="inline-flex items-center gap-2 rounded-full border-2 border-ink bg-panel px-3 py-1 text-[12.5px] font-bold shadow-brut-sm">
            <span className="size-2 rounded-full border border-ink bg-lime" /> Recruiting agent · built on Crustdata&apos;s people graph
          </span>
          <h1 className="font-display mt-6 text-[52px] font-extrabold leading-[0.92] tracking-[-0.045em] sm:text-[92px]">
            Hire on{" "}
            <span className="relative inline-block">
              <span className="absolute inset-x-[-6px] bottom-[8%] top-[18%] -z-10 -rotate-2 rounded-lg border-2 border-ink bg-lime sm:bottom-[10%]" />
              receipts,
            </span>
            <br />
            not résumés.
          </h1>
          <p className="mx-auto mt-6 max-w-[560px] text-[17px] font-medium leading-relaxed text-secondary">
            Paste any brief, however messy. The agent finds people, checks every claim on their record against live data, and gives you a ranked shortlist where each line shows its source.
          </p>
        </div>

        <div className="mx-auto mt-10 max-w-[780px]">
          <BriefInput
            ref={briefRef}
            value={brief}
            onChange={setBrief}
            onRun={onRun}
            onStop={() => {}}
            running={false}
            footer={
              <span className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-muted-foreground">
                <span className={cn("size-2 rounded-full border border-ink", mode === "live" ? "bg-lime" : "bg-yellow")} />
                {mode === "live" ? "Live: calls the agent" : "Replay: recorded run, no backend needed"}
              </span>
            }
          />
          <div className="mt-5 flex flex-wrap justify-center gap-2">
            {EXAMPLES.map((ex, i) => (
              <button
                key={ex.label}
                onClick={() => setBrief(ex.brief)}
                className={cn(
                  "press h-9 rounded-full border-2 border-ink px-3.5 text-[13px] font-bold shadow-brut-sm",
                  brief === ex.brief ? "bg-yellow text-on-color" : "bg-panel",
                )}
                style={{ rotate: `${[-1.5, 1, -0.5, 1.5][i % 4]}deg` }}
                title={ex.brief}
              >
                {ex.label}
              </button>
            ))}
          </div>
        </div>
      </section>

      <div className="relative -rotate-1 overflow-hidden border-y-2 border-ink bg-ink py-3 text-background">
        <div className="flex w-max animate-marquee gap-8 whitespace-nowrap">
          {[...TICKER, ...TICKER].map(([s, t], i) => (
            <span key={i} className="inline-flex items-center gap-2 text-[14px] font-bold">
              <span
                className={cn(
                  "grid size-5 place-items-center rounded-full border-2 border-background text-[11px] font-extrabold text-[#111]",
                  s === "verified" ? "bg-lime" : s === "contradicted" ? "bg-coral" : "bg-[#d9d4c7]",
                )}
              >
                {s === "verified" ? "✓" : s === "contradicted" ? "✗" : "?"}
              </span>
              {t}
            </span>
          ))}
        </div>
      </div>

      <section className="mx-auto grid max-w-[1100px] gap-4 px-4 py-16 sm:grid-cols-6">
        <Bento className="bg-lavender sm:col-span-4" n="01" title="Search like a sourcer" body="Expands the brief into title variants and searches the people graph. Zero results? It broadens the search on its own instead of giving up.">
          <div className="mt-4 flex flex-wrap gap-1.5">
            {["Senior Backend Engineer", "SDE III", "Backend Lead", "+ Bengaluru", "+ payments"].map((t) => (
              <span key={t} className="rounded-md border-2 border-[#111] bg-white px-2 py-0.5 text-[12px] font-bold text-[#111]">{t}</span>
            ))}
          </div>
        </Bento>
        <Bento className="bg-lime sm:col-span-2" n="02" title="Verify everything" body="Employer, tenure, location and company stage, each checked against enrich data.">
          <div className="mt-4 flex flex-wrap gap-1.5">
            {(["verified", "contradicted", "unverifiable"] as const).map((s, i) => (
              <span key={s} className="rounded-full border-2 border-[#111] bg-white px-2 text-[11px] font-extrabold uppercase text-[#111]" style={{ rotate: `${[-3, 2, -1][i]}deg` }}>
                {s === "verified" ? "✓" : s === "contradicted" ? "✗" : "?"} {s}
              </span>
            ))}
          </div>
        </Bento>
        <Bento className="bg-sky sm:col-span-3" n="03" title="Cite every line" body="Each ranking reason links to the claim behind it, and each claim names the exact Crustdata endpoint and field it came from." />
        <Bento className="bg-coral sm:col-span-3" n="04" title="Draft, never send" body="Outreach is written for strong matches only, and it stays a draft. The agent never contacts anyone.">
          <span className="mt-4 inline-block rotate-3 rounded-md border-2 border-[#111] bg-yellow px-2 py-0.5 text-[12px] font-extrabold uppercase tracking-wider text-[#111]">Draft · not sent</span>
        </Bento>
      </section>
    </main>
  );
}

function Bento({ className, n, title, body, children }: { className?: string; n: string; title: string; body: string; children?: React.ReactNode }) {
  return (
    <div className={cn("rounded-2xl border-2 border-ink p-6 text-[#111] shadow-brut-lg", className)}>
      <div className="font-display text-[13px] font-extrabold">{n}</div>
      <h3 className="font-display mt-2 text-[28px] font-extrabold leading-tight tracking-tight">{title}</h3>
      <p className="mt-2 max-w-[520px] text-[14.5px] font-medium leading-relaxed">{body}</p>
      {children}
    </div>
  );
}

function useCountUp(target: number) {
  const [v, setV] = useState(target);
  const prev = useRef(target);
  useEffect(() => {
    const from = prev.current;
    prev.current = target;
    if (from === target) return;
    const t0 = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / 600);
      setV(Math.round(from + (target - from) * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target]);
  return v;
}

function Stat({ label, value, sub, className }: { label: string; value?: number; sub: string; className: string }) {
  const n = useCountUp(value ?? 0);
  return (
    <div className={cn("rounded-xl border-2 border-ink p-3 text-[#111] shadow-brut", className)}>
      <div className="text-[11px] font-extrabold uppercase tracking-wider">{label}</div>
      <div className="font-display text-[34px] font-extrabold leading-none tabular-nums">{value === undefined ? "–" : n}</div>
      <div className="mt-1 text-[11.5px] font-semibold opacity-75">{sub}</div>
    </div>
  );
}

function Stats({ summary, shortlisted, totals, running }: { summary?: Record<string, number | undefined>; shortlisted: number; totals: { v: number; x: number; u: number }; running: boolean }) {
  return (
    <div className="mt-5 grid grid-cols-2 gap-3 md:grid-cols-4">
      <Stat label="Searched" value={summary?.searched} sub={running && summary?.searched === undefined ? "counting…" : "profiles found"} className="bg-lavender" />
      <Stat label="Shortlisted" value={shortlisted} sub={summary?.enriched !== undefined ? `of ${summary.enriched} enriched` : "candidates"} className="bg-sky" />
      <Stat label="Verified" value={totals.v} sub={`claims · ${totals.u} unverifiable`} className="bg-lime" />
      <Stat label="Contradicted" value={totals.x} sub={totals.x ? "caught on the record" : "nothing caught yet"} className={totals.x ? "bg-coral" : "bg-[#e9e4d6]"} />
    </div>
  );
}

function CriteriaChips({ criteria: c }: { criteria: Criteria }) {
  const chips: { k: string; v: string; bg: string }[] = [];
  if (c.role) chips.push({ k: "role", v: c.role + (c.seniority ? ` · ${c.seniority}` : ""), bg: "bg-yellow" });
  for (const l of c.locations ?? []) chips.push({ k: "in", v: l, bg: "bg-sky" });
  for (const s of c.skills ?? []) chips.push({ k: "skill", v: s, bg: "bg-lavender" });
  for (const s of c.company_preferences ?? []) chips.push({ k: "from", v: s, bg: "bg-pink" });
  for (const s of c.must_haves ?? []) chips.push({ k: "must", v: s, bg: "bg-lime" });
  const extra = (c.title_variants?.length ?? 0) + (c.nice_to_haves?.length ?? 0);
  const shown = chips.slice(0, 8);
  const more = chips.length - shown.length + extra;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-1.5 animate-fade">
      <span className="mr-1 text-[12px] font-bold">Understood as →</span>
      {shown.map((ch, i) => (
        <span key={i} className={cn("inline-flex h-7 animate-pop items-center gap-1 rounded-md border-2 border-ink px-2 text-[12px] text-[#111]", ch.bg)} style={{ animationDelay: `${i * 40}ms` }}>
          <span className="opacity-60">{ch.k}</span>
          <span className="font-bold">{ch.v}</span>
        </span>
      ))}
      {more > 0 && (
        <span
          className="inline-flex h-7 items-center rounded-md border-2 border-dashed border-ink px-2 text-[12px] font-bold"
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
    <div className="inline-flex h-8 items-center overflow-hidden rounded-lg border-2 border-ink bg-panel text-[12.5px] shadow-brut-sm" role="radiogroup">
      {options.map((o, i) => (
        <button
          key={o.v}
          role="radio"
          aria-checked={value === o.v}
          onClick={() => onChange(o.v)}
          className={cn(
            "inline-flex h-full items-center gap-1.5 px-2.5 font-bold transition-colors",
            i > 0 && "border-l-2 border-ink",
            value === o.v ? "bg-ink text-background" : "hover:bg-hover",
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
        className="press inline-flex h-8 items-center gap-1.5 rounded-lg border-2 border-ink bg-panel px-2.5 text-[12.5px] font-bold shadow-brut-sm disabled:opacity-40"
      >
        <Download className="size-3.5" /> Export
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-2 w-64 overflow-hidden rounded-xl border-2 border-ink bg-panel shadow-brut-lg animate-pop">
          {[
            ["Markdown report", "Every claim with its source", onMd, "bg-lime"],
            ["CSV", "For a spreadsheet or ATS", onCsv, "bg-sky"],
            ["JSON", "Raw shortlist", onJson, "bg-lavender"],
          ].map(([l, d, fn, bg], i) => (
            <button key={l as string} onClick={fn as () => void} className={cn("flex w-full items-center gap-2.5 px-3 py-2.5 text-left hover:bg-hover", i > 0 && "border-t-2 border-ink")}>
              <span className={cn("grid size-7 shrink-0 place-items-center rounded-md border-2 border-ink text-[#111]", bg as string)}>
                <FileText className="size-3.5" />
              </span>
              <span>
                <span className="block text-[13px] font-bold">{l as string}</span>
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
      <div className="flex flex-col gap-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex animate-pulse items-center gap-3 rounded-xl border-2 border-dashed border-ink/50 p-3" style={{ animationDelay: `${i * 150}ms` }}>
            <div className="size-[42px] rounded-full border-2 border-dashed border-ink/50" />
            <div className="flex-1 space-y-2">
              <div className="h-3.5 w-40 rounded bg-ink/15" />
              <div className="h-3 w-64 rounded bg-ink/10" />
            </div>
            <div className="h-[52px] w-[60px] rounded-lg border-2 border-dashed border-ink/50" />
          </div>
        ))}
        <p className="text-[13px] font-semibold text-muted-foreground">Candidates drop in here as soon as their claims have been checked.</p>
      </div>
    );
  return (
    <div className="rounded-xl border-2 border-dashed border-ink p-10 text-center">
      {filtered ? (
        <p className="text-[14px] font-semibold">Every candidate has at least one contradicted claim. Press <kbd>H</kbd> to show them.</p>
      ) : done ? (
        <>
          <p className="font-display text-[28px] font-extrabold">No one matched 🤷</p>
          <p className="mt-1 text-[14px] text-muted-foreground">Try fewer must-haves or a wider location.</p>
        </>
      ) : (
        <p className="text-[14px] text-faint">No candidates yet.</p>
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
    ["V", "Switch cards / compare"],
    ["H", "Clean records only"],
    ["Esc", "Close"],
  ];
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4 animate-fade" onClick={onClose}>
      <div className="w-full max-w-sm animate-pop rounded-2xl border-2 border-ink bg-panel p-6 shadow-brut-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-display text-[24px] font-extrabold">Shortcuts</h3>
        <dl className="mt-4 grid grid-cols-[76px_1fr] gap-y-2.5 text-[14px]">
          {keys.map(([k, d]) => (
            <div key={k} className="contents">
              <dt><kbd>{k}</kbd></dt>
              <dd className="font-medium">{d}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
