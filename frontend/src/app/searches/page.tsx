"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpRight, Check, ChevronDown, ChevronRight, CircleAlert, History, Loader2, Search, SearchX } from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { Avatar } from "@/components/evidence";
import { Button, EmptyState, ago, cardCls } from "@/app/console/parts";
import {
  PIPELINE, PIPELINE_BY_KEY, SearchError, needsReason, searches,
  type PipelineStage, type SearchCandidate, type SearchDetail, type SearchSummary, type StageCounts,
} from "@/lib/searches";
import { cn } from "@/lib/utils";

type Kind = "all" | "shortlist" | "campaign";

const REASONS: Record<"rejected" | "dropped", string[]> = {
  rejected: ["Not a fit for the role", "Didn't pass the interview", "Pay expectation out of band", "Notice period too long"],
  dropped: ["Took another offer", "Not interested", "Stopped replying", "Withdrew"],
};

const setUrl = (id: string | null) => {
  const u = new URL(window.location.href);
  if (id) u.searchParams.set("id", id);
  else u.searchParams.delete("id");
  window.history.replaceState(null, "", u);
};

const stamp = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "–";

const dotCls = (s: PipelineStage | null) => {
  const tone = s ? PIPELINE_BY_KEY[s].tone : "muted";
  return tone === "good" ? "bg-verified" : tone === "bad" ? "bg-contradicted" : tone === "open" ? "bg-primary" : "bg-faint";
};

function errText(e: unknown) {
  if (e instanceof SearchError && e.status === 401) return "Sign in to see your searches.";
  return e instanceof Error ? e.message : String(e);
}

export default function SearchesPage() {
  const [list, setList] = useState<SearchSummary[] | null>(null);
  const [listErr, setListErr] = useState<string | null>(null);
  const [id, setId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SearchDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [kind, setKind] = useState<Kind>("all");
  const [q, setQ] = useState("");

  const loadList = useCallback(() => {
    searches
      .list()
      .then((l) => {
        setList(l);
        setListErr(null);
      })
      .catch((e) => setListErr(errText(e)));
  }, []);

  const loadDetail = useCallback((sid: string) => {
    searches
      .get(sid)
      .then((d) => {
        setDetail(d);
        setErr(null);
      })
      .catch((e) => setErr(errText(e)));
  }, []);

  useEffect(() => {
    loadList();
    const qid = new URLSearchParams(window.location.search).get("id");
    if (qid) setId(qid);
  }, [loadList]);

  // Open the newest search when nothing is picked, on wide screens only (on a phone the list is the first screen).
  useEffect(() => {
    if (!id && list?.length && window.matchMedia("(min-width: 1024px)").matches) setId(list[0].id);
  }, [id, list]);

  useEffect(() => {
    setDetail(null);
    setErr(null);
    if (id) loadDetail(id);
  }, [id, loadDetail]);

  const pick = (sid: string | null) => {
    setUrl(sid);
    setId(sid);
  };

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (list ?? [])
      .filter((s) => kind === "all" || s.kind === kind)
      .filter((s) => !needle || `${s.title} ${s.brief}`.toLowerCase().includes(needle));
  }, [list, kind, q]);

  const onChanged = (c: SearchCandidate) => {
    setDetail((d) => (d ? { ...d, candidates: d.candidates.map((x) => (x.key === c.key ? c : x)) } : d));
    loadList();
  };

  return (
    <div className="min-h-screen">
      <AppHeader active="/searches" />
      <div className="mx-auto grid max-w-[1680px] lg:grid-cols-[320px_minmax(0,1fr)]">
        <aside
          className={cn(
            "border-border px-3 py-4 lg:sticky lg:top-12 lg:block lg:h-[calc(100vh-3rem)] lg:overflow-y-auto lg:border-r",
            id ? "hidden" : "block",
          )}
        >
          <div className="px-1">
            <h1 className="text-[15px] font-[590] tracking-[-0.01em]">Searches</h1>
            <p className="mt-0.5 text-[12px] leading-snug text-muted-foreground">Every brief you&apos;ve run, newest first. Open one to see its shortlist and where each person is now.</p>
          </div>
          <div className="mt-3 flex items-center gap-2 px-1">
            <label className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-faint" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Find a search"
                className="h-7 w-full rounded-md border border-border-strong bg-panel pl-7 pr-2 text-[12px] outline-none focus:border-primary/60"
              />
            </label>
          </div>
          <div className="mt-2 flex gap-0.5 px-1" role="tablist">
            {(
              [
                ["all", "All"],
                ["shortlist", "Shortlists"],
                ["campaign", "Campaigns"],
              ] as [Kind, string][]
            ).map(([v, l]) => (
              <button
                key={v}
                role="tab"
                aria-selected={kind === v}
                onClick={() => setKind(v)}
                className={cn("h-6 rounded px-2 text-[12px] font-[510]", kind === v ? "bg-elevated text-foreground" : "text-muted-foreground hover:text-foreground")}
              >
                {l}
              </button>
            ))}
          </div>

          <div className="mt-2 space-y-px">
            {listErr && <p className="px-1 py-2 text-[12px] text-contradicted">{listErr}</p>}
            {list === null && !listErr && <p className="flex items-center gap-2 px-1 py-2 text-[12px] text-faint"><Loader2 className="size-3.5 animate-spin" /> Loading…</p>}
            {list && shown.length === 0 && (
              <p className="px-1 py-2 text-[12px] text-muted-foreground">
                {list.length ? "Nothing matches." : <>No searches yet. Run a brief on the <Link href="/sourced" className="underline underline-offset-2">Shortlist</Link> page and it shows up here.</>}
              </p>
            )}
            {shown.map((s) => (
              <button
                key={s.id}
                onClick={() => pick(s.id)}
                className={cn("block w-full rounded-md px-2.5 py-2 text-left transition", id === s.id ? "bg-elevated" : "hover:bg-hover")}
              >
                <span className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-[13px] font-[510]">{s.title}</span>
                  <span className="shrink-0 text-[11px] tabular-nums text-faint">{ago(s.at)}</span>
                </span>
                <span className="mt-0.5 flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
                  <span className="shrink-0 whitespace-nowrap">{s.kind === "campaign" ? (s.simulated ? "Campaign · simulated" : "Campaign") : "Shortlist"}</span>
                  <span className="text-faint">·</span>
                  <span className="truncate">{countLine(s.counts, s.candidates_total)}</span>
                </span>
                <MiniBar counts={s.counts} className="mt-1.5" />
              </button>
            ))}
          </div>
        </aside>

        <main className={cn("min-w-0 px-4 py-5 sm:px-6", !id && "hidden lg:block")}>
          {id && (
            <button onClick={() => pick(null)} className="mb-3 inline-flex items-center gap-1 text-[12.5px] text-muted-foreground hover:text-foreground lg:hidden">
              <ChevronRight className="size-3.5 rotate-180" /> All searches
            </button>
          )}
          {!id ? (
            list && list.length === 0 ? (
              <EmptyState icon={SearchX} title="No searches yet" action={<Link href="/sourced"><Button variant="primary">Run a brief</Button></Link>}>
                Each brief you run on the Shortlist page, and each campaign you start, is kept here with its candidates.
              </EmptyState>
            ) : null
          ) : err ? (
            <EmptyState icon={CircleAlert} tone="bad" title="Couldn't open this search" action={<Button onClick={() => pick(null)}>Back to searches</Button>}>
              {err}
            </EmptyState>
          ) : !detail ? (
            <p className="flex items-center gap-2 text-[13px] text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Loading…</p>
          ) : (
            <Detail d={detail} onChanged={onChanged} />
          )}
        </main>
      </div>
    </div>
  );
}

function countLine(c: StageCounts, total: number) {
  const parts = PIPELINE.filter((p) => c[p.key]).map((p) => `${c[p.key]} ${p.label.toLowerCase()}`);
  return parts.length ? parts.slice(0, 3).join(", ") + (parts.length > 3 ? "…" : "") : `${total} candidates`;
}

function MiniBar({ counts, className }: { counts: StageCounts; className?: string }) {
  const total = PIPELINE.reduce((n, p) => n + (counts[p.key] ?? 0), 0);
  if (!total) return null;
  return (
    <span className={cn("flex h-1 w-full overflow-hidden rounded-full bg-elevated", className)}>
      {PIPELINE.map((p) =>
        counts[p.key] ? <span key={p.key} className={cn("h-full", dotCls(p.key))} style={{ width: `${(counts[p.key] / total) * 100}%` }} /> : null,
      )}
    </span>
  );
}

// ---- one search ------------------------------------------------------------------------------------------------------

function Detail({ d, onChanged }: { d: SearchDetail; onChanged: (c: SearchCandidate) => void }) {
  const [filter, setFilter] = useState<PipelineStage | "all">("all");
  const [showOthers, setShowOthers] = useState(false);
  useEffect(() => {
    setFilter("all");
    setShowOthers(false);
  }, [d.id]);

  const inPipeline = d.candidates.filter((c) => c.stage);
  const others = d.candidates.filter((c) => !c.stage);
  const rows = filter === "all" ? inPipeline : inPipeline.filter((c) => c.stage === filter);
  const facts = [
    d.kind === "campaign" ? d.job?.city : d.understood?.locations?.join(", "),
    d.job?.band_low && d.job?.band_high ? `${d.job.band_low}–${d.job.band_high} LPA` : null,
    d.understood?.seniority,
    d.understood?.min_years ? `${d.understood.min_years}+ years` : null,
  ].filter(Boolean);

  return (
    <div className="mx-auto max-w-[1080px] space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[11.5px] font-[510] text-faint">
            {d.kind === "campaign" ? "Campaign" : "Shortlist"} · {stamp(d.at)}
            {d.kind === "campaign" && d.simulated && <span title="Candidates' replies in this campaign come from the simulator. Nothing was emailed."> · simulated replies</span>}
          </p>
          <h2 className="mt-1 text-[22px] font-[620] leading-tight tracking-[-0.02em]">{d.title}</h2>
          {facts.length > 0 && <p className="mt-1 text-[13px] text-muted-foreground">{facts.join(" · ")}</p>}
        </div>
        {d.kind === "campaign" && (
          <Link
            href={`/campaigns?id=${d.id}`}
            prefetch={false}
            className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border-strong bg-panel px-3 text-[12.5px] font-[510] text-secondary hover:bg-hover hover:text-foreground"
          >
            Open campaign <ArrowUpRight className="size-3.5" />
          </Link>
        )}
      </div>

      {d.brief && (
        <p className="whitespace-pre-line border-l-2 border-border-strong pl-3 text-[13px] leading-relaxed text-secondary">{d.brief}</p>
      )}

      <div className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1" role="tablist" aria-label="Filter by stage">
        <StageTab active={filter === "all"} onClick={() => setFilter("all")} label="All" n={inPipeline.length} />
        {PIPELINE.map((p) => (
          <StageTab key={p.key} active={filter === p.key} onClick={() => setFilter(p.key)} label={p.label} n={d.counts[p.key] ?? 0} dot={dotCls(p.key)} title={p.what} />
        ))}
      </div>

      <section className={cn(cardCls, "overflow-visible")}>
        <div className="hidden grid-cols-[minmax(0,1.4fr)_150px_minmax(0,1.2fr)_56px_84px] gap-3 border-b border-border px-4 py-2 text-[11px] font-[510] text-faint md:grid">
          <span>Candidate</span>
          <span>Stage</span>
          <span>Why</span>
          <span className="text-right" title="How well their record matches the brief">Fit</span>
          <span className="text-right">Updated</span>
        </div>
        {rows.length === 0 ? (
          <p className="px-4 py-8 text-center text-[12.5px] text-muted-foreground">
            {inPipeline.length ? "Nobody at this stage." : "Nobody made the shortlist on this search."}
          </p>
        ) : (
          rows.map((c) => <CandidateRow key={c.key} sid={d.id} c={c} campaign={d.kind === "campaign"} onChanged={onChanged} />)
        )}
      </section>

      {others.length > 0 && (
        <div>
          <button onClick={() => setShowOthers((v) => !v)} className="inline-flex items-center gap-1 text-[12.5px] font-[510] text-muted-foreground hover:text-foreground">
            <ChevronDown className={cn("size-3.5 transition", !showOthers && "-rotate-90")} />
            Didn&apos;t make the shortlist <span className="tabular-nums text-faint">{others.length}</span>
          </button>
          {showOthers && (
            <section className={cn(cardCls, "mt-2 overflow-visible")}>
              {others.map((c) => <CandidateRow key={c.key} sid={d.id} c={c} campaign={false} onChanged={onChanged} />)}
            </section>
          )}
        </div>
      )}
    </div>
  );
}

function StageTab({ active, onClick, label, n, dot, title }: { active: boolean; onClick: () => void; label: string; n: number; dot?: string; title?: string }) {
  return (
    <button
      role="tab"
      aria-selected={active}
      onClick={onClick}
      title={title}
      className={cn(
        "inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md border px-2.5 text-[12px] font-[510] transition",
        active ? "border-border-strong bg-elevated text-foreground" : "border-transparent text-muted-foreground hover:bg-hover hover:text-foreground",
        !n && !active && "opacity-50",
      )}
    >
      {dot && <span className={cn("size-1.5 rounded-full", dot)} />}
      {label}
      <span className="tabular-nums text-faint">{n}</span>
    </button>
  );
}

function CandidateRow({ sid, c, campaign, onChanged }: { sid: string; c: SearchCandidate; campaign: boolean; onChanged: (c: SearchCandidate) => void }) {
  const [open, setOpen] = useState(false);
  const why = c.reason || c.detail || c.why[0] || null;
  return (
    <div className="border-b border-border last:border-0">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 px-4 py-2.5 md:grid-cols-[minmax(0,1.4fr)_150px_minmax(0,1.2fr)_56px_84px]">
        <button onClick={() => setOpen((v) => !v)} className="flex min-w-0 items-center gap-2.5 text-left" aria-expanded={open} title="Show how this person moved">
          <Avatar name={c.name} size={28} />
          <span className="min-w-0">
            <span className="flex items-center gap-1 truncate text-[13px] font-[510]">
              {c.name}
              {c.profile_url && (
                <a href={c.profile_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="text-faint hover:text-foreground" title="Open their profile">
                  <ArrowUpRight className="size-3" />
                </a>
              )}
            </span>
            <span className="block truncate text-[11.5px] text-muted-foreground">{[c.title, c.company].filter(Boolean).join(" at ") || "–"}</span>
          </span>
        </button>
        <StageMenu sid={sid} c={c} campaign={campaign} onChanged={onChanged} />
        <p className={cn("col-span-2 min-w-0 text-[12px] leading-snug md:col-span-1", c.reason ? "text-secondary" : "text-muted-foreground")}>
          {why ? <span className="line-clamp-2">{why}</span> : <span className="text-faint">–</span>}
        </p>
        <span className="hidden text-right text-[12.5px] tabular-nums text-secondary md:block">{c.score ?? "–"}</span>
        <span className="hidden text-right text-[11.5px] tabular-nums text-faint md:block" title={c.set_by === "you" ? "Set by hand" : "Set by Sourced"}>
          {c.set_by === "you" ? ago(c.updated_at) : stamp(c.updated_at).split(",")[0]}
        </span>
      </div>
      {open && <Timeline c={c} />}
    </div>
  );
}

function Timeline({ c }: { c: SearchCandidate }) {
  if (!c.history.length) return <p className="px-4 pb-3 pl-[54px] text-[12px] text-faint">No stage changes yet.</p>;
  return (
    <ol className="px-4 pb-3 pl-[54px]">
      {c.history.map((h, i) => (
        <li key={i} className="relative flex gap-2.5 pb-2 last:pb-0">
          {i < c.history.length - 1 && <span className="absolute left-[3px] top-3 h-full w-px bg-border" />}
          <span className={cn("relative mt-[5px] size-[7px] shrink-0 rounded-full", dotCls(h.stage))} />
          <span className="min-w-0 text-[12px] leading-snug">
            <span className="font-[510]">{PIPELINE_BY_KEY[h.stage]?.label ?? h.stage}</span>
            {h.reason && <span className="text-muted-foreground"> · {h.reason}</span>}
            <span className="block text-[11px] text-faint">
              {h.by === "Sourced" ? "Sourced" : h.by || "You"} · {stamp(h.at)}
            </span>
          </span>
        </li>
      ))}
      <li className="flex items-center gap-1.5 pt-1 text-[11px] text-faint">
        <History className="size-3" /> Stage changes you make are written to the ledger.
      </li>
    </ol>
  );
}

// ---- stage picker ----------------------------------------------------------------------------------------------------

function StageMenu({ sid, c, campaign, onChanged }: { sid: string; c: SearchCandidate; campaign: boolean; onChanged: (c: SearchCandidate) => void }) {
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState<"rejected" | "dropped" | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && close();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const close = () => {
    setOpen(false);
    setPending(null);
    setReason("");
    setErr(null);
  };

  const save = async (stage: PipelineStage, why = "") => {
    setBusy(true);
    setErr(null);
    try {
      onChanged(await searches.setStage(sid, c.key, stage, why));
      close();
    } catch (e) {
      setErr(e instanceof SearchError && e.status === 401 ? "Sign in to change stages." : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const meta = c.stage ? PIPELINE_BY_KEY[c.stage] : null;
  return (
    <div ref={ref} className="relative justify-self-end md:justify-self-start">
      <button
        onClick={() => (open ? close() : setOpen(true))}
        aria-haspopup="menu"
        aria-expanded={open}
        title={meta ? `${meta.what}. Click to change.` : "Not on the shortlist. Click to add a stage."}
        className={cn(
          "inline-flex h-6 items-center gap-1.5 rounded-full border px-2 text-[11.5px] font-[510] transition hover:bg-hover",
          meta?.tone === "good" && "border-verified/30 text-verified",
          meta?.tone === "bad" && "border-contradicted/30 text-contradicted",
          meta?.tone === "open" && "border-primary/25 text-primary",
          (!meta || meta.tone === "muted") && "border-border-strong text-secondary",
        )}
      >
        <span className={cn("size-1.5 rounded-full", dotCls(c.stage))} />
        {meta?.label ?? "Not shortlisted"}
        <ChevronDown className="size-3 opacity-60" />
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-40 mt-1 w-[248px] rounded-lg border border-border-strong bg-panel p-1 shadow-lg md:left-0 md:right-auto">
          {!pending ? (
            PIPELINE.map((p) => (
              <button
                key={p.key}
                role="menuitem"
                disabled={busy}
                onClick={() => (needsReason(p.key) ? setPending(p.key as "rejected" | "dropped") : save(p.key))}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[12.5px] hover:bg-hover disabled:opacity-50"
              >
                <span className={cn("size-1.5 shrink-0 rounded-full", dotCls(p.key))} />
                <span className="min-w-0 flex-1">
                  <span className="block font-[510]">{p.label}</span>
                  <span className="block truncate text-[11px] text-faint">{p.what}</span>
                </span>
                {c.stage === p.key && <Check className="size-3.5 shrink-0 text-muted-foreground" />}
              </button>
            ))
          ) : (
            <form
              className="p-1.5"
              onSubmit={(e) => {
                e.preventDefault();
                if (reason.trim()) save(pending, reason.trim());
              }}
            >
              <p className="text-[12.5px] font-[590]">{pending === "rejected" ? "Why are we rejecting them?" : "Why did they drop out?"}</p>
              <div className="mt-2 flex flex-wrap gap-1">
                {REASONS[pending].map((r) => (
                  <button
                    type="button"
                    key={r}
                    onClick={() => setReason(r)}
                    className={cn("rounded-full border px-2 py-0.5 text-[11px]", reason === r ? "border-border-strong bg-elevated text-foreground" : "border-border text-muted-foreground hover:text-foreground")}
                  >
                    {r}
                  </button>
                ))}
              </div>
              <input
                autoFocus
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                maxLength={300}
                placeholder="Or write a reason"
                className="mt-2 h-8 w-full rounded-md border border-border-strong bg-panel px-2.5 text-[12.5px] outline-none focus:border-primary/60"
              />
              {campaign && <p className="mt-1.5 text-[11px] leading-snug text-faint">This also ends their conversation, so Sourced stops messaging them.</p>}
              <div className="mt-2 flex justify-end gap-1.5">
                <Button variant="ghost" onClick={() => setPending(null)}>Back</Button>
                <Button type="submit" variant="primary" disabled={!reason.trim() || busy}>
                  {busy && <Loader2 className="size-3.5 animate-spin" />} Save
                </Button>
              </div>
            </form>
          )}
          {err && <p className="px-2 pb-1.5 pt-1 text-[11.5px] text-contradicted">{err}</p>}
        </div>
      )}
    </div>
  );
}
