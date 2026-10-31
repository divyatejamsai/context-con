"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { Check, ChevronDown, Plus, Download, FileText, Keyboard, Moon, Radio, Rows3, ShieldCheck, Sun, Table2, X } from "lucide-react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { BriefInput, EXAMPLES } from "@/components/brief";
import { Trace } from "@/components/trace";
import { Dossier } from "@/components/dossier";
import { CompareTable, ShortlistRows, type Row, type SortKey } from "@/components/shortlist";
import { AGENT_ID, API_URL, streamRun, type RunMode } from "@/lib/stream";
import { claimCounts, evidenceStrength, initialRun, runReducer } from "@/lib/run-state";
import { download, toCSV, toMarkdown } from "@/lib/export";
import { AGENT_STEPS, AUTOSEND_STEPS, PIPELINE_STEPS, type Criteria } from "@/lib/types";
import { cn } from "@/lib/utils";
import { AgaxesCrumb, ConsoleLink, ProductNav } from "@/components/app-header";
import { AccountMenu } from "@/components/account-menu";
import { BRAND } from "@/lib/brand";

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
  const [autosend, setAutosend] = useState(false);
  const [lastBrief, setLastBrief] = useState("");
  const [mode, setMode] = useState<RunMode>(process.env.NEXT_PUBLIC_DEFAULT_MODE === "replay" ? "replay" : "live");
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
  const [guideSeen, setGuideSeen] = useState(true);
  const [now, setNow] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const briefRef = useRef<HTMLTextAreaElement>(null);
  const wide = useWide();

  useEffect(() => {
    try { setGuideSeen(localStorage.getItem("guide-seen") === "1"); } catch { setGuideSeen(false); }
  }, []);
  const dismissGuide = () => {
    setGuideSeen(true);
    try { localStorage.setItem("guide-seen", "1"); } catch {}
  };

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
      for await (const ev of streamRun(brief, mode, ctrl.signal, autosend)) dispatch({ type: "event", ev, at: Date.now() });
      dispatch({ type: "stop", at: Date.now() });
    } catch (e) {
      if (ctrl.signal.aborted) return dispatch({ type: "stop", at: Date.now() });
      const msg = e instanceof Error ? e.message : String(e);
      dispatch({ type: "fatal", at: Date.now(), message: mode === "live" ? `Couldn't reach the agent at ${API_URL}. ${msg}` : msg });
    }
  }, [brief, mode, autosend]);

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
  // Rows reachable by keyboard: the shortlist plus any tier the user has opened.
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
      <TopBar
        mode={mode}
        setMode={setMode}
        running={run.running}
        done={run.done}
        elapsed={elapsed}
        started={started}
        onHelp={() => setHelp((h) => !h)}
        onNew={() => {
          abortRef.current?.abort();
          setSelected(undefined);
          setSheetOpen(false);
          dispatch({ type: "reset" });
          setTimeout(() => briefRef.current?.focus(), 0);
        }}
      />

      {!started ? (
        <Hero brief={brief} setBrief={setBrief} onRun={start} briefRef={briefRef} mode={mode} autosend={autosend} setAutosend={setAutosend} />
      ) : (
        <main className="mx-auto grid max-w-[1680px] grid-cols-[minmax(0,1fr)] lg:grid-cols-[300px_minmax(0,1fr)] xl:grid-cols-[300px_minmax(0,1fr)_minmax(0,500px)] 2xl:grid-cols-[320px_minmax(0,1fr)_minmax(0,560px)]">
          <aside className="order-last min-w-0 border-t border-border px-4 py-4 lg:order-none lg:sticky lg:border-t-0 lg:top-12 lg:h-[calc(100vh-3rem)] lg:overflow-y-auto lg:border-r">
            <div className="mb-3">
              <div className="flex items-center justify-between gap-2">
                <h2 className="text-[13px] font-[590]">What the agent did</h2>
                <span className="shrink-0 whitespace-nowrap rounded-full border border-border-strong px-1.5 font-mono text-[10.5px] text-muted-foreground">
                  {mode === "live" ? (AGENT_ID ? "live · agent" : "live") : "sample run"}
                </span>
              </div>
              <p className="mt-0.5 text-[12px] leading-snug text-muted-foreground">Every step, with the Crustdata call behind it. Click a step to read its log.</p>
            </div>
            <Trace run={run} now={now} pipeline={mode === "live" && AGENT_ID ? (autosend ? AUTOSEND_STEPS : AGENT_STEPS) : PIPELINE_STEPS} />
          </aside>

          <section className="min-w-0">
            <div className="sticky top-12 z-20 border-b border-border bg-background/80 px-4 py-3 backdrop-blur-xl">
              <BriefInput ref={briefRef} value={brief} onChange={setBrief} onRun={start} onStop={stop} running={run.running} compact />
              {run.criteria && <CriteriaChips criteria={run.criteria} />}
            </div>

            {run.passport?.decision === "block" && (
              <div className="mx-4 mt-3 rounded-lg border border-contradicted/30 bg-contradicted/[0.06] px-3 py-2.5 text-[13px]">
                <span className="font-[510] text-contradicted">Run refused by {BRAND.name}.</span>{" "}
                <span className="text-secondary">{run.passport.error ?? run.passport.message}</span>
                <p className="mt-0.5 text-[12px] text-muted-foreground">The agent&apos;s passport did not pass its live check, so nothing was searched. Re-onboard it with a sponsor Crustdata can vouch for.</p>
              </div>
            )}

            {run.fatal && (
              <div className="mx-4 mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-contradicted/30 bg-contradicted/[0.08] px-3 py-2.5 text-[13px]">
                <span>
                  <span className="font-[510] text-contradicted">Run failed.</span> <span className="text-secondary">{run.fatal}</span>
                </span>
                {mode === "live" && (
                  <button onClick={() => setMode("replay")} className="h-7 rounded-md border border-border-strong bg-elevated px-2.5 text-[12px] font-[510] hover:bg-hover">
                    Use the sample run instead
                  </button>
                )}
              </div>
            )}

            <div className="flex flex-wrap items-end justify-between gap-2 px-4 pb-3 pt-4">
              <div className="min-w-0">
                <div className="flex items-baseline gap-2">
                  <h1 className="text-[15px] font-[590]">Shortlist</h1>
                  <span className="font-mono text-[12px] text-muted-foreground tabular-nums">{tiers.main.length}</span>
                  <Funnel summary={run.summary} totals={totals} />
                </div>
                <p className="mt-0.5 text-[12px] text-muted-foreground">Ranked by fit to your brief. Click a candidate to see the evidence.</p>
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
                  title="Hide anyone with a claim that Crustdata contradicts (H)"
                  aria-pressed={hideContra}
                >
                  {hideContra ? <X className="size-3.5" /> : <ShieldCheck className="size-3.5" />}
                  {hideContra ? "Showing clean records · undo" : "Hide contradicted"}
                </button>
                <ExportMenu
                  disabled={!tiers.main.length}
                  onMd={() => download("shortlist.md", toMarkdown(lastBrief, run.criteria, exportRows()), "text/markdown")}
                  onCsv={() => download("shortlist.csv", toCSV(exportRows()), "text/csv")}
                  onJson={() => download("shortlist.json", JSON.stringify({ brief: lastBrief, criteria: run.criteria, candidates: exportRows() }, null, 2), "application/json")}
                />
              </div>
            </div>

            {!guideSeen && run.done && tiers.main.length > 0 && <Guide onClose={dismissGuide} />}

            <div className="border-t border-border">
              {tiers.main.length || tiers.near.length || tiers.other.length ? (
                <>
                  {tiers.main.length > 0 &&
                    (view === "list" ? (
                      <ShortlistRows rows={tiers.main} selected={selected} onSelect={select} />
                    ) : (
                      <CompareTable rows={tiers.main} selected={selected} onSelect={select} sort={sort} dir={dir} onSort={onSort} />
                    ))}
                  {!tiers.main.length && !run.running && (
                    <p className="px-4 py-6 text-[13px] text-secondary">Nobody cleared the bar for this brief. Open the near misses below, or loosen the must-haves.</p>
                  )}
                  {(
                    [
                      ["near", "Near misses", "Just under the bar. Worth a look if the shortlist is thin."],
                      ["other", "Below the bar", "Searched and checked, but not a fit for this brief."],
                    ] as const
                  ).map(([key, title, sub]) =>
                    tiers[key].length ? (
                      <div key={key} className={cn("border-t border-border", key === "other" && "opacity-70")}>
                        <button
                          onClick={() => setOpenTiers((t) => ({ ...t, [key]: !t[key] }))}
                          className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left transition hover:bg-hover"
                          aria-expanded={openTiers[key]}
                        >
                          <span className="flex min-w-0 items-baseline gap-2">
                            <span className="text-[13px] font-[590]">{title}</span>
                            <span className="font-mono text-[12px] text-muted-foreground tabular-nums">{tiers[key].length}</span>
                            <span className="hidden truncate text-[12px] text-faint sm:inline">{sub}</span>
                          </span>
                          <ChevronDown className={cn("size-4 shrink-0 text-muted-foreground transition-transform", openTiers[key] && "rotate-180")} />
                        </button>
                        {openTiers[key] && (
                          <div className="border-t border-border">
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
                </>
              ) : (
                <Empty
                  running={run.running}
                  done={run.done}
                  filtered={hideContra && Object.keys(run.candidates).length > 0}
                  onEdit={() => briefRef.current?.focus()}
                  onSample={mode === "live" ? () => setMode("replay") : undefined}
                />
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
                  {run.running ? (
                    "The top candidate opens here as soon as their claims are checked."
                  ) : (
                    <span className="max-w-[300px]">
                      <span className="block text-[14px] font-[590] text-secondary">Pick a candidate</span>
                      <span className="mt-1 block">You&apos;ll see why they were ranked, every claim that was checked with its source, and a draft message you can copy.</span>
                    </span>
                  )}
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
    <span className="grid size-6 place-items-center rounded-[5px] bg-foreground">
      <Check className="size-3.5 text-background" strokeWidth={3} />
    </span>
  );
}

function ThemeToggle() {
  const [dark, setDark] = useState(false);
  useEffect(() => setDark(document.documentElement.dataset.theme === "dark"), []);
  const flip = () => {
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch {}
    setDark(!dark);
  };
  return (
    <button onClick={flip} className="grid size-7 place-items-center rounded-md text-muted-foreground hover:bg-hover hover:text-foreground" aria-label={dark ? "Light theme" : "Dark theme"}>
      {dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  );
}

function TopBar({
  mode, setMode, running, done, elapsed, started, onHelp, onNew,
}: { mode: RunMode; setMode: (m: RunMode) => void; running: boolean; done: boolean; elapsed: number; started: boolean; onHelp: () => void; onNew: () => void }) {
  return (
    <header className="sticky top-0 z-30 h-12 border-b border-border bg-background/80 backdrop-blur-xl">
      <div className="mx-auto flex h-full max-w-[1680px] items-center justify-between gap-3 px-4">
        <AgaxesCrumb />
        <Link href="/sourced" className="flex items-center gap-2">
          <Logo />
          <span className="text-[14px] font-semibold tracking-[-0.01em]">Sourced</span>
        </Link>
        <span className="hidden text-[14px] text-border-strong sm:inline">/</span>
        <div className="mr-auto hidden min-w-0 sm:block">
          <ProductNav active="/sourced" />
        </div>
        <div className="flex items-center gap-2.5">
          {started && (
            <span className="hidden items-center gap-1.5 text-[12px] text-muted-foreground tabular-nums md:flex">
              <span className={cn("size-1.5 rounded-full", running ? "animate-pulse bg-primary" : done ? "bg-verified" : "bg-faint")} />
              {running ? "Searching" : done ? "Finished" : "Stopped"} · <span className="font-mono">{elapsed.toFixed(1)}s</span>
            </span>
          )}
          {started && !running && (
            <button
              onClick={onNew}
              className="inline-flex h-7 items-center gap-1.5 rounded-md border border-border-strong bg-panel px-2.5 text-[12px] font-[510] hover:bg-hover"
              title="Clear these results and write a new brief"
            >
              <Plus className="size-3.5" /> New search
            </button>
          )}
          <span className="hidden text-[12px] text-faint lg:inline">Data</span>
          <Seg
            value={mode}
            onChange={(m) => !running && setMode(m)}
            options={[
              { v: "live", label: "Live", icon: <Radio className="size-3" />, title: "Search real people on Crustdata through the backend" },
              { v: "replay", label: "Sample", title: "Play back a recorded run. Use this when the backend is offline." },
            ]}
          />
          <ConsoleLink />
          <button onClick={onHelp} className="hidden size-7 place-items-center rounded-md text-muted-foreground hover:bg-hover hover:text-foreground sm:grid" aria-label="Keyboard shortcuts">
            <Keyboard className="size-4" />
          </button>
          <ThemeToggle />
          <AccountMenu />
        </div>
      </div>
    </header>
  );
}

function Hero({ brief, setBrief, onRun, briefRef, mode, autosend, setAutosend }: { brief: string; setBrief: (s: string) => void; onRun: () => void; briefRef: React.Ref<HTMLTextAreaElement>; mode: RunMode; autosend: boolean; setAutosend: (b: boolean) => void }) {
  return (
    <main>
      <div className="mx-auto flex max-w-[760px] flex-col px-4 pb-24 pt-16 sm:pt-24">
        <h1 className="text-[28px] font-[590] leading-tight tracking-[-0.025em] sm:text-[32px]">What role are you hiring for?</h1>
        <p className="mt-2 max-w-[580px] text-[14px] leading-relaxed text-muted-foreground">
          Describe the role and Sourced finds matching people on Crustdata. It checks each person&apos;s employer, tenure and location, and gives you a ranked shortlist where every claim shows its source.
        </p>
        <label htmlFor="brief" className="mt-7 block text-[13px] font-[510]">
          Hiring brief
        </label>
        <p className="mb-2 mt-0.5 text-[12px] text-muted-foreground">Role, seniority, location and any must-haves. Plain language is fine, even a messy note.</p>
        <div className="w-full">
          <BriefInput
            ref={briefRef}
            value={brief}
            onChange={setBrief}
            onRun={onRun}
            onStop={() => {}}
            running={false}
            footer={
              <span className="inline-flex items-center gap-1.5 text-[11.5px] text-faint">
                <span className={cn("size-1.5 rounded-full", mode === "live" ? "bg-primary" : "bg-faint")} />
                {mode === "live" ? (AGENT_ID ? "Live data · runs as a verified AI employee, drafts checked by Send Guard" : "Live data · searches Crustdata through the backend") : "Sample run · plays back a recorded search, no backend needed"}
              </span>
            }
          />
        </div>
        {mode === "live" && AGENT_ID && (
          <label className="mt-3 flex cursor-pointer items-start gap-2 rounded-lg border border-border bg-panel px-3 py-2.5 text-[12.5px]">
            <input type="checkbox" checked={autosend} onChange={(e) => setAutosend(e.target.checked)} className="mt-0.5 accent-[var(--primary)]" />
            <span>
              <span className="font-[510]">Email the shortlist for me</span>
              <span className="block text-muted-foreground">
                Sourced finds each person&apos;s email on Crustdata and sends every message Send Guard clears, with nobody at the keyboard. They
                all go to your own test inbox, never to the candidates. Leave it off to review and send each one yourself.
              </span>
            </span>
          </label>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-[12px] text-faint">Or try an example:</span>
          {EXAMPLES.map((ex) => (
            <button
              key={ex.label}
              onClick={() => setBrief(ex.brief)}
              className={cn(
                "h-7 rounded-md border px-2.5 text-[12px] font-[510] transition",
                brief === ex.brief ? "border-border-strong bg-elevated text-foreground" : "border-border bg-panel text-muted-foreground hover:bg-hover hover:text-foreground",
              )}
              title={ex.brief}
            >
              {ex.label}
            </button>
          ))}
        </div>

        <h2 className="mt-14 text-[13px] font-[590]">What happens when you click Find candidates</h2>
        <div className="mt-3 grid w-full overflow-hidden rounded-lg border border-border bg-panel sm:grid-cols-3">
          {[
            ["Search", "The agent turns your brief into search filters and looks for people on Crustdata. If nothing comes back, it widens the search.", "About 5 seconds"],
            ["Check", "For each person it compares their employer, tenure, location and company against Crustdata records. Each claim is marked verified, contradicted or unverifiable.", "Every claim gets a source"],
            ["Reach out", "You get a ranked shortlist with each person's email from Crustdata. Send the drafted email (Send Guard checks it first), then watch it get delivered and replied to.", "Sent, delivered, replied"],
          ].map(([t, d, note], i) => (
            <div key={t} className={cn("p-5", i > 0 && "border-t border-border sm:border-l sm:border-t-0")}>
              <span className="grid size-6 place-items-center rounded-full border border-border-strong font-mono text-[11px] text-muted-foreground">{i + 1}</span>
              <h3 className="mt-3 text-[14px] font-[590]">{t}</h3>
              <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{d}</p>
              <p className="mt-3 text-[11.5px] text-faint">{note}</p>
            </div>
          ))}
        </div>
        <h2 className="mt-12 text-[13px] font-[590]">Hiring more than one person?</h2>
        <div className="mt-3 grid w-full gap-3 sm:grid-cols-2">
          {[
            ["/campaigns", "Campaigns", "Take one brief to a signed offer. Sourced runs about 100 conversations at once: outreach, follow-ups, screening, interviews and the offer."],
            ["/staffing", "Shift staffing", "Fill 1,000 shifts from applicants. Every application is checked against Crustdata, so the ones who lie are caught before they get a shift."],
          ].map(([href, t, d]) => (
            <Link key={href} href={href} prefetch={false} className="group rounded-lg border border-border bg-panel p-4 transition hover:border-border-strong hover:bg-elevated">
              <span className="flex items-center justify-between text-[14px] font-[590]">
                {t} <span className="text-faint transition group-hover:translate-x-0.5 group-hover:text-foreground">→</span>
              </span>
              <span className="mt-1 block text-[13px] leading-relaxed text-muted-foreground">{d}</span>
            </Link>
          ))}
        </div>
        <p className="mt-6 text-[12.5px] text-muted-foreground">
          Sourced runs as an AI employee with a passport. To see who it acts for and what it was allowed to send, open the{" "}
          <Link href="/console" prefetch={false} className="text-primary hover:underline">
            {BRAND.name} console
          </Link>
          , or{" "}
          <Link href="/console?view=demo" prefetch={false} className="text-primary hover:underline">
            watch the guided demo
          </Link>
          .
        </p>
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
          <span className="inline-flex items-center gap-1" title="Claims that match Crustdata"><span className="size-1.5 rounded-full bg-verified" />{totals.v} verified</span>
          <span className="inline-flex items-center gap-1" title="Claims Crustdata says are wrong"><span className="size-1.5 rounded-full bg-contradicted" />{totals.x} contradicted</span>
          <span className="inline-flex items-center gap-1" title="Claims with no source to check against"><span className="size-1.5 rounded-full bg-faint" />{totals.u} unverifiable</span>
        </span>
      )}
    </span>
  );
}

function CriteriaChips({ criteria: c }: { criteria: Criteria }) {
  const chips: { k: string; v: string; warn?: boolean; title?: string }[] = [];
  if (c.role) chips.push({ k: "Role", v: c.role + (c.seniority ? ` · ${c.seniority}` : "") });
  else chips.push({ k: "Role", v: "unclear, name it in the brief", warn: true });
  for (const l of c.locations ?? []) chips.push({ k: "in", v: l });
  // Education: the brief's wording, read as concrete schools (short names first; full names in the tooltip)
  const schools = c.schools ?? [];
  if (schools.length) {
    const short = schools.filter((s) => s.length <= 12 || s.split(" ").length <= 2);
    const shown = (short.length ? short : schools).slice(0, 4);
    const rest = (short.length ? short : schools).length - shown.length;
    chips.push({
      k: "school",
      v: shown.join(", ") + (rest > 0 ? ` +${rest}` : ""),
      title: (c.education_note ? `"${c.education_note}" read as:\n` : "") + schools.join("\n"),
    });
  } else if (c.education_note) {
    chips.push({ k: "school", v: `${c.education_note} (not filtered)`, warn: true, title: "Couldn't name specific schools for this, so it isn't used as a filter" });
  }
  for (const d of c.degrees ?? []) chips.push({ k: "degree", v: d });
  for (const s of c.skills ?? []) chips.push({ k: "skill", v: s });
  for (const s of c.company_preferences ?? []) chips.push({ k: "from", v: s });
  for (const s of c.must_haves ?? []) chips.push({ k: "must", v: s });
  const extra = (c.title_variants?.length ?? 0) + (c.nice_to_haves?.length ?? 0);
  const shown = chips.slice(0, 7);
  const more = chips.length - shown.length + extra;
  return (
    <div className="mt-2 flex flex-wrap items-center gap-1.5 animate-fade">
      <span className="text-[11.5px] text-faint" title="How the agent read your brief. If it's wrong, edit the brief and run it again.">Understood as</span>
      {shown.map((ch, i) => (
        <span
          key={i}
          title={ch.title}
          className={cn(
            "inline-flex h-6 items-center gap-1 rounded-md border bg-panel px-2 text-[12px]",
            ch.warn ? "border-dashed border-border-strong text-muted-foreground" : "border-border-strong",
          )}
        >
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

function Seg<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: { v: T; label: string; icon?: React.ReactNode; title?: string }[] }) {
  return (
    <div className="inline-flex h-7 items-center rounded-md border border-border-strong bg-panel p-0.5 text-[12px]" role="radiogroup">
      {options.map((o) => (
        <button
          key={o.v}
          role="radio"
          aria-checked={value === o.v}
          onClick={() => onChange(o.v)}
          title={o.title}
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

function Empty({ running, done, filtered, onEdit, onSample }: { running: boolean; done: boolean; filtered: boolean; onEdit: () => void; onSample?: () => void }) {
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
          <p className="text-[15px] font-[590]">No one matched this brief</p>
          <p className="mx-auto mt-1 max-w-[380px] text-[13px] text-muted-foreground">
            The agent widened the search and still found nobody. Try fewer must-haves or a wider location, then search again. The steps on the left show what it tried.
          </p>
          <div className="mt-4 flex justify-center gap-2">
            <button onClick={onEdit} className="h-7 rounded-md bg-foreground px-2.5 text-[12px] font-[510] text-background hover:opacity-85">
              Edit the brief
            </button>
            {onSample && (
              <button onClick={onSample} className="h-7 rounded-md border border-border-strong bg-panel px-2.5 text-[12px] font-[510] hover:bg-hover" title="Switch to a recorded run so you can see what results look like">
                Switch to the sample run
              </button>
            )}
          </div>
        </>
      ) : (
        <p className="text-[13px] text-faint">No candidates yet.</p>
      )}
    </div>
  );
}

function Guide({ onClose }: { onClose: () => void }) {
  const steps = [
    ["Open a candidate", "Click a row to see why they rank where they do."],
    ["Check the claims", "Red means Crustdata says the claim is wrong. Grey means there was nothing to check it against."],
    ["Send the email", "Each draft has the email Crustdata holds for that person. Edit it if you like, then press Send: Send Guard checks it first, and you see it delivered and replied to."],
  ];
  return (
    <div className="mx-4 mb-3 rounded-lg border border-border bg-elevated px-4 py-3 animate-fade">
      <div className="flex items-start justify-between gap-3">
        <p className="text-[13px] font-[590]">How to use this shortlist</p>
        <button onClick={onClose} className="h-6 shrink-0 rounded-md border border-border-strong bg-panel px-2 text-[12px] font-[510] hover:bg-hover">
          Got it
        </button>
      </div>
      <ol className="mt-2 grid gap-3 sm:grid-cols-3">
        {steps.map(([t, d], i) => (
          <li key={t} className="flex gap-2.5">
            <span className="grid size-5 shrink-0 place-items-center rounded-full border border-border-strong bg-panel font-mono text-[10.5px] text-muted-foreground">{i + 1}</span>
            <span className="text-[12.5px] leading-snug">
              <span className="font-[510]">{t}</span>
              <span className="block text-muted-foreground">{d}</span>
            </span>
          </li>
        ))}
      </ol>
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
      <div className="w-full max-w-sm rounded-lg border border-border-strong bg-elevated p-5 shadow-[var(--shadow)]" onClick={(e) => e.stopPropagation()}>
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
