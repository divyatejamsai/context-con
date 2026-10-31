"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { Download, FileText, Keyboard, Radio, Rows3, Table2 } from "lucide-react";
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
      <TopBar
        mode={mode}
        setMode={setMode}
        running={run.running}
        done={run.done}
        elapsed={elapsed}
        started={started}
        onHelp={() => setHelp((h) => !h)}
      />

      {!started ? (
        <Hero brief={brief} setBrief={setBrief} onRun={start} briefRef={briefRef} />
      ) : (
        <main className="mx-auto max-w-[1600px] px-4 pb-16 sm:px-6">
          <div className="sticky top-14 z-20 -mx-4 bg-background/85 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6">
            <BriefInput ref={briefRef} value={brief} onChange={setBrief} onRun={start} onStop={stop} running={run.running} compact />
          </div>

          {run.fatal && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-md border border-contradicted/50 bg-contradicted/[0.06] px-4 py-3 text-sm">
              <span><span className="font-medium text-contradicted">Run failed.</span> {run.fatal}</span>
              {mode === "live" && (
                <button onClick={() => setMode("replay")} className="rounded-full border border-rule px-3 py-1 text-xs font-medium hover:border-foreground">
                  Switch to replay
                </button>
              )}
            </div>
          )}

          <div className="mt-4 grid gap-6 lg:grid-cols-[280px_minmax(0,1fr)] xl:grid-cols-[260px_minmax(0,1fr)_minmax(0,520px)] 2xl:grid-cols-[280px_minmax(0,1fr)_minmax(0,600px)]">
            <aside className="flex flex-col gap-6 lg:sticky lg:top-32 lg:max-h-[calc(100vh-9rem)] lg:self-start lg:overflow-y-auto">
              <Trace run={run} now={now} />
              {run.criteria && <Understood criteria={run.criteria} />}
            </aside>

            <section className="min-w-0">
              <div className="flex flex-wrap items-end justify-between gap-3 border-b border-foreground/80 pb-3">
                <div>
                  <h2 className="font-display text-3xl font-medium tracking-tight">
                    Shortlist <span className="font-light text-muted-foreground">{rows.length}</span>
                  </h2>
                  <Funnel summary={run.summary} shortlisted={Object.keys(run.candidates).length} totals={totals} />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Seg
                    value={view}
                    onChange={setView}
                    options={[
                      { v: "list", label: "Dossiers", icon: <Rows3 className="size-3.5" /> },
                      { v: "compare", label: "Compare", icon: <Table2 className="size-3.5" /> },
                    ]}
                  />
                  <button
                    onClick={() => setHideContra((h) => !h)}
                    className={cn(
                      "rounded-full border px-3 py-1 text-xs font-medium transition",
                      hideContra ? "border-contradicted bg-contradicted text-white" : "border-rule hover:border-foreground",
                    )}
                    title="Hide candidates with any contradicted claim (h)"
                  >
                    {hideContra ? "Contradicted hidden" : "Hide contradicted"}
                  </button>
                  <ExportMenu
                    disabled={!rows.length}
                    onMd={() => download("shortlist.md", toMarkdown(lastBrief, run.criteria, exportRows()), "text/markdown")}
                    onCsv={() => download("shortlist.csv", toCSV(exportRows()), "text/csv")}
                    onJson={() => download("shortlist.json", JSON.stringify({ brief: lastBrief, criteria: run.criteria, candidates: exportRows() }, null, 2), "application/json")}
                  />
                </div>
              </div>

              {rows.length ? (
                view === "list" ? (
                  <ShortlistRows rows={rows} selected={selected} onSelect={select} />
                ) : (
                  <CompareTable rows={rows} selected={selected} onSelect={select} sort={sort} dir={dir} onSort={onSort} />
                )
              ) : (
                <Empty running={run.running} done={run.done} filtered={hideContra && Object.keys(run.candidates).length > 0} />
              )}
              {rows.length > 0 && (
                <p className="mt-4 hidden flex-wrap items-center gap-x-4 gap-y-1 whitespace-nowrap font-mono text-[11px] text-muted-foreground sm:flex">
                  <span><kbd>j</kbd> <kbd>k</kbd> move</span>
                  <span><kbd>p</kbd> pin</span>
                  <span><kbd>x</kbd> pass</span>
                  <span><kbd>c</kbd> copy outreach</span>
                  <span><kbd>v</kbd> compare</span>
                  <span><kbd>?</kbd> all shortcuts</span>
                </p>
              )}
            </section>

            {wide && (
              <aside className="sticky top-32 hidden max-h-[calc(100vh-9rem)] self-start overflow-y-auto rounded-lg border border-rule bg-paper shadow-[0_24px_48px_-32px_rgba(0,0,0,0.35)] xl:block">
                {dossier ?? <p className="p-8 text-sm text-muted-foreground">{run.running ? "The top candidate's dossier opens here as soon as they're verified." : "Select a candidate to open their dossier."}</p>}
              </aside>
            )}
          </div>
        </main>
      )}

      {!wide && (
        <Sheet open={sheetOpen && !!dossier} onOpenChange={setSheetOpen}>
          <SheetContent className="bg-paper">
            <SheetTitle className="sr-only">{cur?.name ?? "Candidate"}</SheetTitle>
            <div className="h-full overflow-y-auto pt-6">{dossier}</div>
          </SheetContent>
        </Sheet>
      )}

      {help && <Shortcuts onClose={() => setHelp(false)} />}
    </div>
  );
}

function TopBar({
  mode, setMode, running, done, elapsed, started, onHelp,
}: { mode: RunMode; setMode: (m: RunMode) => void; running: boolean; done: boolean; elapsed: number; started: boolean; onHelp: () => void }) {
  return (
    <header className="sticky top-0 z-30 border-b border-rule bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1600px] items-center justify-between gap-4 px-4 sm:px-6">
        <Link href="/" className="flex items-baseline gap-2">
          <span className="font-display text-2xl font-semibold italic tracking-tight">Dossier</span>
          <span className="hidden font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground sm:inline">verified shortlists · on Crustdata</span>
        </Link>
        <div className="flex items-center gap-3">
          {started && (
            <span className="flex items-center gap-2 font-mono text-xs tabular-nums">
              <span className={cn("size-2 rounded-full", running ? "animate-pulse bg-primary" : done ? "bg-verified" : "bg-unverifiable")} />
              {running ? "working" : done ? "done" : "stopped"} · {elapsed.toFixed(1)}s
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
          <button onClick={onHelp} className="hidden rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground sm:block" aria-label="Keyboard shortcuts">
            <Keyboard className="size-4" />
          </button>
        </div>
      </div>
    </header>
  );
}

function Hero({ brief, setBrief, onRun, briefRef }: { brief: string; setBrief: (s: string) => void; onRun: () => void; briefRef: React.Ref<HTMLTextAreaElement> }) {
  return (
    <main className="mx-auto flex max-w-3xl flex-col px-4 pb-20 pt-14 sm:px-6 sm:pt-24">
      <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">No human in the loop · every claim cited</p>
      <h1 className="font-display mt-3 text-5xl font-light leading-[1.02] tracking-tight sm:text-7xl">
        Who are you <em className="font-normal">hiring?</em>
      </h1>
      <p className="mt-4 max-w-xl text-[17px] leading-relaxed text-muted-foreground">
        Write the brief however it comes out. The agent finds people on Crustdata, checks what their profiles claim, and hands back a ranked shortlist with a source for every line.
      </p>
      <div className="mt-8">
        <BriefInput ref={briefRef} value={brief} onChange={setBrief} onRun={onRun} onStop={() => {}} running={false} />
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {EXAMPLES.map((ex) => (
          <button
            key={ex.label}
            onClick={() => setBrief(ex.brief)}
            className={cn(
              "rounded-full border px-3 py-1.5 text-left text-xs transition",
              brief === ex.brief ? "border-foreground bg-foreground text-background" : "border-rule text-muted-foreground hover:border-foreground hover:text-foreground",
            )}
            title={ex.brief}
          >
            {ex.label}
          </button>
        ))}
      </div>
      <ol className="mt-16 grid gap-6 border-t border-rule pt-8 sm:grid-cols-3">
        {[
          ["01", "Search", "Expands your brief into title variants and searches Crustdata's people graph, broadening if it comes up empty."],
          ["02", "Verify", "Checks employer, tenure, location and company stage against enrich data. Each claim is stamped verified, contradicted or unverifiable."],
          ["03", "Cite", "Ranks candidates with reasons that footnote the evidence, then drafts outreach. Nothing is ever sent."],
        ].map(([n, t, d]) => (
          <li key={n}>
            <span className="font-mono text-[11px] text-muted-foreground">{n}</span>
            <h3 className="font-display mt-1 text-xl font-medium">{t}</h3>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{d}</p>
          </li>
        ))}
      </ol>
    </main>
  );
}

function Funnel({ summary, shortlisted, totals }: { summary?: Record<string, number | undefined>; shortlisted: number; totals: { v: number; x: number; u: number } }) {
  const steps: [string, number | undefined][] = [
    ["searched", summary?.searched],
    ["enriched", summary?.enriched],
    ["shortlisted", summary?.shortlisted ?? (shortlisted || undefined)],
  ];
  return (
    <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[11px] text-muted-foreground">
      {steps
        .filter(([, n]) => n !== undefined)
        .map(([l, n], i, a) => (
          <span key={l}>
            <span className="font-medium tabular-nums text-foreground">{n}</span> {l}
            {i < a.length - 1 && <span className="ml-2">→</span>}
          </span>
        ))}
      {totals.v + totals.x + totals.u > 0 && (
        <span className="ml-1">
          · <span className="text-verified">{totals.v} verified</span> · <span className="text-contradicted">{totals.x} contradicted</span> · {totals.u} unverifiable
        </span>
      )}
    </p>
  );
}

function Understood({ criteria: c }: { criteria: Criteria }) {
  const rows: [string, string[] | undefined][] = [
    ["Titles", c.title_variants],
    ["Skills", c.skills],
    ["Where", c.locations],
    ["Companies", c.company_preferences],
    ["Must", c.must_haves],
    ["Nice", c.nice_to_haves],
  ];
  return (
    <div className="animate-rise">
      <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">What the agent understood</div>
      {c.role && (
        <p className="font-display text-lg leading-tight">
          {c.role}
          {c.seniority && <span className="text-muted-foreground">, {c.seniority}</span>}
        </p>
      )}
      <dl className="mt-2 flex flex-col gap-1.5">
        {rows
          .filter(([, v]) => v?.length)
          .map(([label, v]) => (
            <div key={label} className="grid grid-cols-[64px_1fr] gap-2 text-xs">
              <dt className="pt-0.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">{label}</dt>
              <dd className="flex flex-wrap gap-1">
                {v!.map((x) => (
                  <span key={x} className="rounded-sm border border-rule bg-paper px-1.5 py-0.5">{x}</span>
                ))}
              </dd>
            </div>
          ))}
      </dl>
    </div>
  );
}

function Seg<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: { v: T; label: string; icon?: React.ReactNode }[] }) {
  return (
    <div className="inline-flex rounded-full border border-rule bg-paper p-0.5 text-xs" role="radiogroup">
      {options.map((o) => (
        <button
          key={o.v}
          role="radio"
          aria-checked={value === o.v}
          onClick={() => onChange(o.v)}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-full px-3 py-1 font-medium transition",
            value === o.v ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground",
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
        className="inline-flex items-center gap-1.5 rounded-full border border-rule px-3 py-1 text-xs font-medium hover:border-foreground disabled:opacity-40"
      >
        <Download className="size-3.5" /> Export
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-1 w-56 overflow-hidden rounded-md border border-rule bg-paper py-1 text-sm shadow-lg animate-fade">
          {[
            ["Markdown report", "every claim with its source", onMd],
            ["CSV", "for a spreadsheet or ATS", onCsv],
            ["JSON", "raw shortlist", onJson],
          ].map(([l, d, fn]) => (
            <button key={l as string} onClick={fn as () => void} className="flex w-full items-start gap-2 px-3 py-2 text-left hover:bg-muted">
              <FileText className="mt-0.5 size-3.5 shrink-0" />
              <span>
                <span className="block font-medium">{l as string}</span>
                <span className="block text-xs text-muted-foreground">{d as string}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Empty({ running, done, filtered }: { running: boolean; done: boolean; filtered: boolean }) {
  return (
    <div className="py-16 text-center">
      {running ? (
        <div className="mx-auto flex max-w-sm flex-col gap-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-16 animate-pulse rounded-md bg-muted" style={{ animationDelay: `${i * 150}ms` }} />
          ))}
          <p className="mt-2 text-sm text-muted-foreground">Candidates appear here as soon as their claims are checked.</p>
        </div>
      ) : filtered ? (
        <p className="text-sm text-muted-foreground">Every candidate has a contradicted claim. Press <kbd>h</kbd> to show them.</p>
      ) : done ? (
        <>
          <p className="font-display text-2xl">No one matched.</p>
          <p className="mt-1 text-sm text-muted-foreground">Try fewer must-haves or a wider location.</p>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">No candidates yet.</p>
      )}
    </div>
  );
}

function Shortcuts({ onClose }: { onClose: () => void }) {
  const keys: [string, string][] = [
    ["⌘ ↵", "Run the brief"],
    ["/", "Edit the brief"],
    ["j / ↓", "Next candidate"],
    ["k / ↑", "Previous candidate"],
    ["p", "Pin candidate to top"],
    ["x", "Pass on candidate"],
    ["c", "Copy outreach draft"],
    ["v", "Switch dossiers / compare"],
    ["h", "Hide contradicted"],
    ["esc", "Close"],
  ];
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4 animate-fade" onClick={onClose}>
      <div className="w-full max-w-sm rounded-lg border border-rule bg-paper p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-display text-2xl">Shortcuts</h3>
        <dl className="mt-4 grid grid-cols-[80px_1fr] gap-y-2 text-sm">
          {keys.map(([k, d]) => (
            <div key={k} className="contents">
              <dt><kbd>{k}</kbd></dt>
              <dd>{d}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
