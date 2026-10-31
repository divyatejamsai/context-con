"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUpRight, CalendarClock, CircleAlert, CircleDot, FastForward, FileSignature, Inbox, Loader2, MessagesSquare,
  Pause, Play, Plus, Search, Send, ShieldCheck, ShieldX, SkipForward,
} from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { Avatar, FitBadge, StatusPill as ClaimPill } from "@/components/evidence";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Button, EmptyState, HowTo, SectionHead, SourceChip, Term, TERMS, cardCls } from "@/app/console/parts";
import {
  CLOSED_STAGES, FUNNEL, OPEN_STAGES, STAGE, TalentError, band, shortDay, sse, stageLabel, talent, when,
  type Campaign, type CampaignEvent, type CampaignSummary, type Conversation, type ConversationRow, type Message, type Stage,
} from "@/lib/talent";
import { cn } from "@/lib/utils";
import { BRAND } from "@/lib/brand";

const EXAMPLE = "Senior backend engineer, payments, Bangalore\nBudget 40-55 LPA, notice under 60 days\nOne hire, start by January";

const MESSAGE_KIND: Record<string, string> = {
  outreach: "First message", followup: "Follow-up", welcome: "Welcome back", screening: "Screening questions",
  screening_nudge: "Screening reminder", clarify: "Clarifying question", answer: "Answer", slots: "Interview slots",
  interview_confirm: "Interview confirmed", offer: "Offer letter", offer_final: "Best and final offer", offer_nudge: "Offer reminder",
  sign_request: "Signature request", rejection: "Not moving forward", close: "Closing note", role_filled: "Role filled",
};

const TIMER: Record<string, string> = {
  followup: "Follow-up", re_engage: "Re-engage after snooze", screening_nudge: "Screening reminder", screening_timeout: "Screening times out",
  slots_timeout: "Slot pick times out", interview_done: "Panel verdict due", offer_nudge: "Offer reminder", offer_expire: "Offer expires",
};

type Filter = "all" | "open" | "signed" | "closed";

const setUrl = (id: string | null) => {
  const u = new URL(window.location.href);
  if (id) u.searchParams.set("id", id);
  else u.searchParams.delete("id");
  window.history.replaceState(null, "", u);
};

export default function CampaignsPage() {
  const [list, setList] = useState<CampaignSummary[] | null>(null);
  const [listErr, setListErr] = useState<string | null>(null);
  const [id, setId] = useState<string | null>(null);
  const [camp, setCamp] = useState<Campaign | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [events, setEvents] = useState<CampaignEvent[]>([]);
  const [running, setRunning] = useState<null | "stream" | "advance">(null);
  const [open, setOpen] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  const loadList = useCallback(() => {
    talent
      .campaigns()
      .then((l) => {
        setList(l.filter((c) => c.conversations > 0).sort((a, b) => b.started_at.localeCompare(a.started_at) || b.id.localeCompare(a.id)));
        setListErr(null);
      })
      .catch((e) => setListErr(e instanceof Error ? e.message : String(e)));
  }, []);

  const loadCamp = useCallback((cid: string) => {
    talent
      .campaign(cid)
      .then((c) => {
        setCamp(c);
        setErr(null);
      })
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    loadList();
    const q = new URLSearchParams(window.location.search).get("id");
    if (q) setId(q);
  }, [loadList]);

  useEffect(() => {
    abort.current?.abort();
    setEvents([]);
    setCamp(null);
    setOpen(null);
    if (id) loadCamp(id);
  }, [id, loadCamp]);

  const pick = (cid: string | null) => {
    setUrl(cid);
    setId(cid);
  };

  // Run the simulated clock forward a day at a time, applying each day's summary as it lands.
  const runClock = async (days: number) => {
    if (!camp) return;
    const ctl = new AbortController();
    abort.current = ctl;
    setRunning("stream");
    setErr(null);
    try {
      for await (const ev of sse<CampaignEvent>(`/campaigns/${camp.id}/stream`, { days }, ctl.signal)) {
        if (ev.type === "day") {
          setCamp((c) => (c ? { ...c, day: ev.day, clock: ev.clock, stages: ev.stages, funnel: ev.funnel, status: ev.status, stats: ev.stats } : c));
        } else if (ev.type === "done") {
          break;
        } else if (ev.type === "error") {
          setErr(ev.message);
        } else {
          setEvents((e) => [ev, ...e].slice(0, 600));
        }
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(null);
      abort.current = null;
      loadCamp(camp.id);
      loadList();
    }
  };

  const advance = async (days: number) => {
    if (!camp) return;
    setRunning("advance");
    setErr(null);
    try {
      const r = await talent.advance(camp.id, days);
      setEvents((e) => [...r.events.filter((x) => x.type !== "day" && x.type !== "done").reverse(), ...e].slice(0, 600));
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(null);
      loadCamp(camp.id);
      loadList();
    }
  };

  return (
    <div className="min-h-screen">
      <AppHeader active="/campaigns" />
      <div className="mx-auto grid max-w-[1680px] lg:grid-cols-[272px_minmax(0,1fr)]">
        <aside className="border-b border-border px-3 py-4 lg:sticky lg:top-12 lg:h-[calc(100vh-3rem)] lg:overflow-y-auto lg:border-b-0 lg:border-r">
          <div className="flex items-center justify-between px-1">
            <h2 className="text-[13px] font-[590]">Your campaigns</h2>
            <button
              onClick={() => pick(null)}
              className="inline-flex h-7 items-center gap-1 rounded-md border border-border-strong bg-panel px-2 text-[12px] font-[510] hover:bg-hover"
              title="Write a new brief and start another campaign"
            >
              <Plus className="size-3.5" /> New
            </button>
          </div>
          <p className="mt-1 px-1 text-[11.5px] leading-snug text-faint">One campaign per role. Each runs its own conversations until the role is filled.</p>
          <div className="mt-3 space-y-1">
            {listErr && <p className="px-1 text-[12px] text-contradicted">{listErr}</p>}
            {list === null && !listErr && <p className="px-1 text-[12px] text-faint">Loading…</p>}
            {list?.length === 0 && <p className="px-1 text-[12px] text-muted-foreground">None yet. Start one with the form.</p>}
            {list?.map((c) => (
              <button
                key={c.id}
                onClick={() => pick(c.id)}
                className={cn(
                  "w-full rounded-md border px-2.5 py-2 text-left transition",
                  id === c.id ? "border-border-strong bg-elevated" : "border-transparent hover:bg-hover",
                )}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate text-[13px] font-[510]">{c.role}</span>
                  <CampaignStatus status={c.status} />
                </span>
                <span className="mt-0.5 block truncate text-[11.5px] text-muted-foreground">
                  {[c.job?.city, `day ${c.day}`, `${c.conversations} conversations`].filter(Boolean).join(" · ")}
                </span>
              </button>
            ))}
          </div>
        </aside>

        <main className="min-w-0 px-4 py-6 sm:px-6">
          {!id ? (
            <NewCampaign
              onCreated={(c) => {
                setCamp(c);
                setUrl(c.id);
                setId(c.id);
                loadList();
              }}
            />
          ) : !camp ? (
            err ? (
              <EmptyState icon={CircleAlert} tone="bad" title="Couldn't load this campaign" action={<Button onClick={() => pick(null)}>Start a new one</Button>}>
                {err}
              </EmptyState>
            ) : (
              <p className="flex items-center gap-2 text-[13px] text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Loading campaign…</p>
            )
          ) : (
            <CampaignView
              camp={camp}
              events={events}
              running={running}
              err={err}
              onRun={() => runClock(60)}
              onPause={() => abort.current?.abort()}
              onAdvance={advance}
              onOpen={setOpen}
            />
          )}
        </main>
      </div>

      {camp && (
        <Sheet open={!!open} onOpenChange={(o) => !o && setOpen(null)}>
          <SheetContent className="sm:max-w-2xl">
            {open && (
              <Transcript
                campId={camp.id}
                cid={open}
                live={running !== null}
                onChanged={() => {
                  loadCamp(camp.id);
                  loadList();
                }}
              />
            )}
          </SheetContent>
        </Sheet>
      )}
    </div>
  );
}

function CampaignStatus({ status }: { status: string }) {
  const filled = status === "filled";
  return (
    <span
      className={cn(
        "inline-flex h-5 shrink-0 items-center gap-1 rounded-full border px-1.5 text-[10.5px] font-[510]",
        filled ? "border-verified/30 bg-verified/10 text-verified" : "border-primary/25 bg-primary/[0.06] text-primary",
      )}
    >
      <span className={cn("size-1.5 rounded-full", filled ? "bg-verified" : "bg-primary")} />
      {filled ? "Filled" : "Hiring"}
    </span>
  );
}

// ---- new campaign -------------------------------------------------------------------------------------------------

function NewCampaign({ onCreated }: { onCreated: (c: Campaign) => void }) {
  const [brief, setBrief] = useState("");
  const [size, setSize] = useState(100);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const start = async () => {
    setBusy(true);
    setErr(null);
    try {
      onCreated(await talent.create({ brief: brief.trim(), size }));
    } catch (e) {
      const m = e instanceof Error ? e.message : String(e);
      setErr(
        e instanceof TalentError && e.status === 401
          ? `The backend needs an admin token for this. Set it with the key icon in the ${BRAND.name} console, then try again.`
          : e instanceof TalentError && e.status === 422
            ? "No candidates matched this brief. Try a broader role or city."
            : m,
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-[760px] pb-16 pt-4 sm:pt-10">
      <h1 className="text-[26px] font-[590] leading-tight tracking-[-0.025em]">Take a brief to a signed offer</h1>
      <p className="mt-2 max-w-[600px] text-[14px] leading-relaxed text-muted-foreground">
        Write three lines. Sourced finds matching people, messages each one, and keeps every conversation going: follow-ups, screening, interview
        slots, offers and counter-offers, until someone signs. Every message passes <Term tip={TERMS.guard}>Send Guard</Term> before it goes out.
      </p>

      <HowTo
        className="mt-6"
        steps={[
          <>Write the brief: <b className="font-[510]">role and city</b>, <b className="font-[510]">pay band and notice limit</b>, <b className="font-[510]">openings and start</b>.</>,
          <>Click <b className="font-[510]">Start campaign</b>. Sourced opens up to {size} conversations and sends each first message.</>,
          <>Run the clock. Watch the funnel fill day by day and open any conversation to read it.</>,
        ]}
      />

      <label htmlFor="campaign-brief" className="mt-8 block text-[13px] font-[510]">Brief</label>
      <p className="mb-2 mt-0.5 text-[12px] text-muted-foreground">Line 1: role, team, city. Line 2: budget in LPA and notice limit. Line 3: openings and start date.</p>
      <div className="rounded-lg border border-border-strong bg-panel focus-within:border-primary/60 focus-within:ring-2 focus-within:ring-primary/15">
        <textarea
          id="campaign-brief"
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && brief.trim() && !busy) start();
          }}
          rows={4}
          placeholder={EXAMPLE}
          className="block w-full resize-none rounded-lg bg-transparent px-3.5 py-3 font-mono text-[13px] leading-relaxed outline-none placeholder:text-faint"
        />
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-3 py-2">
          <div className="flex items-center gap-2">
            <button onClick={() => setBrief(EXAMPLE)} className="h-7 rounded-md border border-border px-2.5 text-[12px] font-[510] text-muted-foreground hover:bg-hover hover:text-foreground" title={EXAMPLE}>
              Use the example
            </button>
            <label className="flex items-center gap-1.5 text-[12px] text-muted-foreground" title="How many matching people Sourced opens a conversation with">
              Conversations
              <select value={size} onChange={(e) => setSize(Number(e.target.value))} className="h-7 rounded-md border border-border-strong bg-panel px-1.5 text-[12px] text-foreground">
                {[25, 50, 100, 200].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </label>
          </div>
          <Button variant="primary" onClick={start} disabled={!brief.trim() || busy} title="Find candidates and send each one a first message">
            {busy ? <><Loader2 className="size-3.5 animate-spin" /> Finding people and sending first messages…</> : <><Play className="size-3.5" /> Start campaign</>}
          </Button>
        </div>
      </div>
      {err && <p className="mt-3 rounded-md border border-contradicted/30 bg-contradicted/[0.06] px-3 py-2 text-[12.5px] text-contradicted">{err}</p>}

      <p className="mt-5 flex gap-2 rounded-lg border border-border bg-elevated px-3.5 py-3 text-[12.5px] leading-relaxed text-secondary">
        <ShieldCheck className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
        <span>
          <b className="font-[590]">Nothing is emailed.</b> Messages stay in this app and candidates&apos; replies come from a simulator, so you can watch weeks of hiring in
          seconds. Offers need the <span className="font-mono text-[11.5px]">contract.sign</span> permission on Sourced&apos;s passport; without it they wait for the sponsor to countersign.
        </span>
      </p>
    </div>
  );
}

// ---- campaign ------------------------------------------------------------------------------------------------------

function CampaignView({
  camp, events, running, err, onRun, onPause, onAdvance, onOpen,
}: {
  camp: Campaign; events: CampaignEvent[]; running: null | "stream" | "advance"; err: string | null;
  onRun: () => void; onPause: () => void; onAdvance: (days: number) => void; onOpen: (cid: string) => void;
}) {
  const j = camp.job;
  const filled = camp.status === "filled";
  const facts = [
    j?.city,
    band(j),
    j?.notice_max_days ? `notice under ${j.notice_max_days} days` : null,
    j?.openings ? `${j.openings} opening${j.openings > 1 ? "s" : ""}` : null,
    j?.company ? `for ${j.company}` : null,
  ].filter(Boolean);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[11.5px] font-[510] text-faint">Campaign · started {shortDay(camp.started_at)} · run by {j?.recruiter ?? "Sourced"}</p>
          <h1 className="mt-1 flex flex-wrap items-center gap-2.5 text-[22px] font-[620] tracking-[-0.02em]">
            {camp.role} <CampaignStatus status={camp.status} />
          </h1>
          <p className="mt-1 text-[13px] text-muted-foreground">{facts.join(" · ")}</p>
        </div>
        {camp.brief && (
          <pre className="max-w-[420px] whitespace-pre-wrap rounded-md border border-border bg-elevated px-3 py-2 font-mono text-[11.5px] leading-relaxed text-muted-foreground" title="The brief this campaign was started from">
            {camp.brief}
          </pre>
        )}
      </div>

      {/* clock */}
      <div className={cn(cardCls, "flex flex-wrap items-center justify-between gap-3 px-4 py-3")}>
        <div className="flex items-center gap-3">
          <span className="grid size-9 place-items-center rounded-lg border border-border-strong bg-elevated">
            <CalendarClock className="size-4 text-muted-foreground" />
          </span>
          <div>
            <p className="text-[13.5px] font-[590] tabular-nums">
              Day {camp.day} <span className="font-normal text-muted-foreground">· {when(camp.clock)}</span>
              {running === "stream" && <span className="ml-2 inline-flex items-center gap-1 text-[12px] font-[510] text-primary"><span className="size-1.5 animate-pulse rounded-full bg-primary" /> running</span>}
            </p>
            <p className="text-[12px] text-muted-foreground">
              {filled
                ? `Role filled${camp.filled_at ? ` on ${shortDay(camp.filled_at)}` : ""}. Every other conversation was closed with a note, so the clock stops here.`
                : "Simulated clock. Each day Sourced reads replies, follows up, books interviews and makes offers."}
            </p>
          </div>
        </div>
        {!filled && (
          <div className="flex flex-wrap items-center gap-1.5">
            <Button onClick={() => onAdvance(1)} disabled={!!running} title="Move the clock forward one day and stop">
              <SkipForward className="size-3.5" /> 1 day
            </Button>
            <Button onClick={() => onAdvance(7)} disabled={!!running} title="Move the clock forward a week and stop">
              <FastForward className="size-3.5" /> 1 week
            </Button>
            {running === "stream" ? (
              <Button variant="secondary" onClick={onPause} title="Stop after the current day">
                <Pause className="size-3.5" /> Pause
              </Button>
            ) : (
              <Button variant="primary" onClick={onRun} disabled={!!running} title="Run day by day until every opening is signed (at most 60 days)">
                {running === "advance" ? <Loader2 className="size-3.5 animate-spin" /> : <Play className="size-3.5" />} Run until someone signs
              </Button>
            )}
          </div>
        )}
      </div>
      {err && <p className="rounded-md border border-contradicted/30 bg-contradicted/[0.06] px-3 py-2 text-[12.5px] text-contradicted">{err}</p>}

      {camp.hires.map((h) => (
        <div key={h.cid} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-verified/30 bg-verified/[0.06] px-4 py-3">
          <div className="flex min-w-0 items-center gap-3">
            <FileSignature className="size-5 shrink-0 text-verified" />
            <div className="min-w-0">
              <p className="text-[13.5px] font-[590]">
                {h.name} signed{h.ctc_lpa ? ` at ${h.ctc_lpa} LPA` : ""}{h.at ? ` on ${shortDay(h.at)}` : ""}
              </p>
              <p className="mt-0.5 flex flex-wrap gap-x-3 font-mono text-[11px] text-muted-foreground">
                {h.doc_sha256 && <span title={`SHA-256 of the signed offer letter: ${h.doc_sha256}`}>offer {h.doc_sha256.slice(0, 12)}</span>}
                {h.ledger_entry && (
                  <Link href="/console?view=ledger" prefetch={false} className="hover:text-foreground hover:underline" title={`Ledger entry ${h.ledger_entry}. Open the ledger.`}>
                    ledger {h.ledger_entry.slice(0, 12)}
                  </Link>
                )}
              </p>
            </div>
          </div>
          <Button onClick={() => onOpen(h.cid)}>Read the conversation</Button>
        </div>
      ))}

      <FunnelView camp={camp} />

      <div className="grid gap-px overflow-hidden rounded-xl border border-border-strong bg-border sm:grid-cols-5">
        <Stat k="Messages sent" v={camp.stats.guard_allowed} sub="each passed Send Guard" />
        <Stat k="Blocked by Send Guard" v={camp.stats.guard_blocked} sub="never left" tone={camp.stats.guard_blocked ? "text-contradicted" : undefined} />
        <Stat k="Replies received" v={camp.stats.replies} sub="read and answered" />
        <Stat k="Offers made" v={camp.stats.offers} sub="incl. revised offers" />
        <Stat k="Still talking" v={OPEN_STAGES.reduce((n, s) => n + (camp.stages[s] ?? 0), 0)} sub={`of ${camp.conversations} conversations`} />
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Conversations camp={camp} onOpen={onOpen} />
        <Activity events={events} running={running === "stream"} onOpen={onOpen} />
      </div>
    </div>
  );
}

function Stat({ k, v, sub, tone }: { k: string; v: number; sub?: string; tone?: string }) {
  return (
    <div className="bg-panel px-4 py-3">
      <p className="text-[11.5px] text-muted-foreground">{k}</p>
      <p className={cn("mt-0.5 text-[20px] font-[620] tabular-nums tracking-[-0.02em]", tone)}>{v}</p>
      {sub && <p className="text-[11px] text-faint">{sub}</p>}
    </div>
  );
}

function FunnelView({ camp }: { camp: Campaign }) {
  const top = Math.max(1, camp.funnel.contacted);
  return (
    <section className={cn(cardCls, "p-4")}>
      <SectionHead title="How far candidates got">
        Each column counts everyone who reached that step at any point, so people who later dropped out still count. Hover a column for what it means.
      </SectionHead>
      <ol className="mt-4 grid grid-cols-4 gap-x-2 gap-y-4 sm:grid-cols-7">
        {FUNNEL.map((f, i) => {
          const n = camp.funnel[f.key] ?? 0;
          const prev = i ? camp.funnel[FUNNEL[i - 1].key] ?? 0 : null;
          const last = f.key === "signed";
          return (
            <li key={f.key} title={f.what} className="min-w-0">
              <div className="flex h-20 items-end rounded-md bg-elevated">
                <div
                  className={cn("w-full rounded-md transition-[height] duration-500", last && n ? "bg-verified" : "bg-primary/80")}
                  style={{ height: `${Math.max(n ? 4 : 0, (n / top) * 100)}%` }}
                />
              </div>
              <p className="mt-2 text-[18px] font-[620] tabular-nums leading-none">{n}</p>
              <p className="mt-1 truncate text-[12px] font-[510]">{f.label}</p>
              <p className="text-[11px] tabular-nums text-faint">{prev ? `${Math.round((n / prev) * 100)}% of previous` : i ? "–" : "first step"}</p>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function StagePill({ stage, className }: { stage: Stage; className?: string }) {
  const s = STAGE[stage];
  const tone = s?.tone ?? "muted";
  return (
    <span
      title={s?.what}
      className={cn(
        "inline-flex h-5 shrink-0 items-center rounded-full border px-1.5 text-[11px] font-[510]",
        tone === "open" && "border-primary/25 bg-primary/[0.06] text-primary",
        tone === "good" && "border-verified/30 bg-verified/10 text-verified",
        tone === "bad" && "border-contradicted/30 bg-contradicted/10 text-contradicted",
        tone === "hold" && "border-flag/30 bg-flag/10 text-flag",
        tone === "muted" && "border-border-strong text-muted-foreground",
        className,
      )}
    >
      {stageLabel(stage)}
    </span>
  );
}

function Conversations({ camp, onOpen }: { camp: Campaign; onOpen: (cid: string) => void }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(25);
  const rows = camp.conversations_list;
  const counts = useMemo(
    () => ({
      all: rows.length,
      open: rows.filter((r) => r.open).length,
      signed: rows.filter((r) => r.stage === "signed").length,
      closed: rows.filter((r) => CLOSED_STAGES.includes(r.stage)).length,
    }),
    [rows],
  );
  const order = (r: ConversationRow) => (r.stage === "signed" ? 0 : r.open ? 1 + OPEN_STAGES.length - OPEN_STAGES.indexOf(r.stage) : 20);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return rows
      .filter((r) => (filter === "all" ? true : filter === "open" ? r.open : filter === "signed" ? r.stage === "signed" : CLOSED_STAGES.includes(r.stage)))
      .filter((r) => !needle || `${r.name} ${r.company ?? ""} ${r.title ?? ""}`.toLowerCase().includes(needle))
      .sort((a, b) => order(a) - order(b) || (b.score ?? 0) - (a.score ?? 0));
  }, [rows, filter, q]);

  return (
    <section className={cn(cardCls, "min-w-0 overflow-hidden")}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
        <SectionHead title="Conversations">Click a row to read the whole thread and see what Send Guard decided on every message.</SectionHead>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2">
        <div className="flex gap-0.5 rounded-md border border-border bg-elevated p-0.5" role="tablist">
          {(
            [
              ["all", "All"],
              ["open", "In progress"],
              ["signed", "Signed"],
              ["closed", "Closed"],
            ] as [Filter, string][]
          ).map(([v, l]) => (
            <button
              key={v}
              role="tab"
              aria-selected={filter === v}
              onClick={() => {
                setFilter(v);
                setLimit(25);
              }}
              className={cn("h-6 rounded px-2 text-[12px] font-[510]", filter === v ? "bg-panel text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}
            >
              {l} <span className="tabular-nums text-faint">{counts[v]}</span>
            </button>
          ))}
        </div>
        <label className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-faint" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a person or company" className="h-7 w-52 rounded-md border border-border-strong bg-panel pl-7 pr-2 text-[12px] outline-none focus:border-primary/60" />
        </label>
      </div>
      {shown.length === 0 ? (
        <EmptyState icon={Inbox} title="No conversations here">Try another filter.</EmptyState>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-left">
            <thead className="text-[11px] text-faint">
              <tr className="border-b border-border">
                <th className="px-4 py-2 font-[510]">Candidate</th>
                <th className="px-2 py-2 font-[510]">Stage</th>
                <th className="px-2 py-2 font-[510]" title="How well their Crustdata record matches the brief">Fit</th>
                <th className="px-2 py-2 font-[510]">Last message</th>
                <th className="px-4 py-2 font-[510]">Next step</th>
              </tr>
            </thead>
            <tbody>
              {shown.slice(0, limit).map((r) => (
                <tr key={r.id} onClick={() => onOpen(r.id)} className="cursor-pointer border-b border-border last:border-0 hover:bg-hover">
                  <td className="max-w-[240px] px-4 py-2.5">
                    <div className="flex items-center gap-2.5">
                      <Avatar name={r.name} size={26} />
                      <div className="min-w-0">
                        <p className="truncate text-[13px] font-[510]">{r.name}</p>
                        <p className="truncate text-[11.5px] text-muted-foreground">{[r.title, r.company].filter(Boolean).join(" at ")}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-2 py-2.5"><StagePill stage={r.stage} /></td>
                  <td className="px-2 py-2.5 text-[12.5px] tabular-nums text-secondary">{r.score ?? "–"}</td>
                  <td className="max-w-[300px] px-2 py-2.5">
                    {r.last ? (
                      <p className="truncate text-[12px] text-muted-foreground">
                        <span className={cn("mr-1 font-[510]", r.last.dir === "in" ? "text-foreground" : "text-faint")}>{r.last.dir === "in" ? "They:" : "Sourced:"}</span>
                        {r.last.body.replace(/\s+/g, " ")}
                      </p>
                    ) : (
                      <span className="text-[12px] text-faint">–</span>
                    )}
                    <p className="text-[11px] text-faint">{r.messages} message{r.messages === 1 ? "" : "s"}{r.last ? ` · ${when(r.last.at)}` : ""}</p>
                  </td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-[12px] text-muted-foreground">
                    {r.timer ? (
                      <>
                        {TIMER[r.timer.kind] ?? r.timer.kind.replace(/_/g, " ")}
                        <span className="block text-[11px] text-faint">{when(r.timer.at)}</span>
                      </>
                    ) : r.open ? "Waiting on them" : <span className="text-faint">Done</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {shown.length > limit && (
            <button onClick={() => setLimit((l) => l + 50)} className="w-full border-t border-border py-2.5 text-[12.5px] font-[510] text-muted-foreground hover:bg-hover hover:text-foreground">
              Show {Math.min(50, shown.length - limit)} more of {shown.length - limit}
            </button>
          )}
        </div>
      )}
    </section>
  );
}

function Activity({ events, running, onOpen }: { events: CampaignEvent[]; running: boolean; onOpen: (cid: string) => void }) {
  return (
    <section className={cn(cardCls, "flex max-h-[720px] min-w-0 flex-col overflow-hidden xl:sticky xl:top-16")}>
      <div className="border-b border-border px-4 py-3">
        <SectionHead title="What Sourced just did" aside={running ? <Loader2 className="size-3.5 animate-spin text-primary" /> : undefined}>
          Newest first. Fills in while the clock runs.
        </SectionHead>
      </div>
      {events.length === 0 ? (
        <EmptyState icon={MessagesSquare} title="Nothing yet">Click Run until someone signs, or move the clock a day, to watch every reply, follow-up and stage change.</EmptyState>
      ) : (
        <ol className="min-h-0 flex-1 overflow-y-auto px-2 py-1.5">
          {events.map((e, i) => {
            if (e.type === "day" || e.type === "done" || e.type === "error") return null;
            const cid = "cid" in e ? e.cid : null;
            const blocked = e.type === "message" && e.dir === "out" && e.decision === "block";
            const major = e.type === "filled" || e.type === "decide" || (e.type === "stage" && e.stage === "signed");
            return (
              <li key={i}>
                <button
                  disabled={!cid}
                  onClick={() => cid && onOpen(cid)}
                  className={cn("flex w-full gap-2 rounded-md px-2 py-1.5 text-left enabled:hover:bg-hover", major && "bg-elevated")}
                >
                  <span className="mt-[3px] shrink-0">
                    {blocked ? <ShieldX className="size-3.5 text-contradicted" />
                      : e.type === "message" ? (e.dir === "in" ? <Inbox className="size-3.5 text-foreground" /> : <Send className="size-3.5 text-faint" />)
                        : major ? <FileSignature className="size-3.5 text-verified" />
                          : <CircleDot className="size-3.5 text-faint" />}
                  </span>
                  <span className="min-w-0">
                    <span className={cn("block text-[12px] leading-snug", major ? "font-[590]" : "text-secondary")}>{eventText(e)}</span>
                    {e.type === "message" && e.dir === "in" && e.body && <span className="block truncate text-[11.5px] text-muted-foreground">&ldquo;{e.body}&rdquo;</span>}
                    <span className="block font-mono text-[10.5px] text-faint">{when(e.at)}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

function eventText(e: CampaignEvent): string {
  if (e.type === "message") {
    if (e.dir === "in") return `${e.name} replied${e.intent ? `: ${e.intent.replace(/_/g, " ")}` : ""}`;
    const kind = MESSAGE_KIND[e.message_kind ?? ""] ?? e.message_kind ?? "message";
    return e.decision === "block" ? `Send Guard blocked a ${kind.toLowerCase()} to ${e.name}` : `${kind} sent to ${e.name}`;
  }
  if (e.type === "stage") return `${e.name}: ${stageLabel(e.previous)} → ${stageLabel(e.stage)}`;
  if ("text" in e) return e.text;
  return "";
}

// ---- transcript ----------------------------------------------------------------------------------------------------

function Transcript({ campId, cid, live, onChanged }: { campId: string; cid: string; live: boolean; onChanged: () => void }) {
  const [c, setC] = useState<Conversation | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    talent.conversation(campId, cid).then(setC).catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, [campId, cid]);
  useEffect(load, [load]);
  // While the clock runs, keep the open thread current.
  useEffect(() => {
    if (!live) return;
    const t = setInterval(load, 1500);
    return () => clearInterval(t);
  }, [live, load]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
      setReply("");
      load();
      onChanged();
      setTimeout(() => end.current?.scrollIntoView({ behavior: "smooth" }), 150);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!c) {
    return (
      <div className="p-6">
        <SheetTitle className="text-[15px] font-[590]">Conversation</SheetTitle>
        <SheetDescription className="mt-2 text-[13px] text-muted-foreground">{err ?? "Loading…"}</SheetDescription>
      </div>
    );
  }

  const open = !["signed", "declined", "ghosted", "rejected", "unsubscribed", "closed", "blocked"].includes(c.stage);
  const facts: [string, string][] = [];
  if (c.screening?.notice_days != null) facts.push(["Notice", `${c.screening.notice_days} days`]);
  if (c.screening?.expected_lpa != null) facts.push(["Expects", `${c.screening.expected_lpa} LPA`]);
  if (c.interview?.slot) facts.push(["Interview", when(c.interview.slot)]);
  if (c.interview?.passed != null) facts.push(["Panel", `${c.interview.passed ? "passed" : "didn't pass"}${c.interview.notes ? ` (${c.interview.notes})` : ""}`]);
  if (c.offer?.ctc_lpa != null) facts.push(["Offer", `${c.offer.ctc_lpa} LPA${c.offer.version && c.offer.version > 1 ? ` (v${c.offer.version})` : ""}`]);
  if (c.offer?.expires_at && c.stage === "offer") facts.push(["Offer expires", when(c.offer.expires_at)]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-border px-5 py-4 pr-12">
        <div className="flex items-start gap-3">
          <Avatar name={c.name} size={36} />
          <div className="min-w-0 flex-1">
            <SheetTitle className="flex flex-wrap items-center gap-2 text-[16px] font-[590]">
              {c.name} <StagePill stage={c.stage} />
            </SheetTitle>
            <SheetDescription className="truncate text-[12.5px] text-muted-foreground">{[c.title, c.company].filter(Boolean).join(" at ")}</SheetDescription>
            <p className="mt-1 text-[12px] text-secondary">{STAGE[c.stage]?.what}</p>
          </div>
          <FitBadge score={c.score} />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <a href={c.profile_url} target="_blank" rel="noreferrer" className="inline-flex h-7 items-center gap-1 rounded-md border border-border-strong px-2 text-[12px] font-[510] hover:bg-hover" title="Open their public profile in a new tab">
            Open profile <ArrowUpRight className="size-3.5" />
          </a>
          {facts.map(([k, v]) => (
            <span key={k} className="inline-flex h-7 items-center gap-1 rounded-md bg-elevated px-2 text-[12px]">
              <span className="text-muted-foreground">{k}</span> <span className="font-[510]">{v}</span>
            </span>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {(c.claims?.length ?? 0) > 0 && (
          <details className="group mb-5 rounded-lg border border-border">
            <summary className="flex cursor-pointer list-none items-center justify-between px-3 py-2 text-[12.5px] font-[510]">
              <span>Why Sourced messaged them: {c.claims!.length} claims checked against Crustdata</span>
              <span className="text-faint group-open:rotate-90">›</span>
            </summary>
            <ul className="divide-y divide-border border-t border-border">
              {c.claims!.map((cl) => (
                <li key={cl.id} className="flex flex-wrap items-start justify-between gap-2 px-3 py-2">
                  <span className="min-w-0 flex-1">
                    <span className="block text-[12.5px]">{cl.claim}</span>
                    {cl.evidence && <span className="block text-[11.5px] text-muted-foreground">{cl.evidence}</span>}
                  </span>
                  <span className="flex flex-col items-end gap-1">
                    <ClaimPill status={cl.source?.endpoint ? cl.status : "unverifiable"} />
                    <SourceChip source={cl.source} />
                  </span>
                </li>
              ))}
            </ul>
          </details>
        )}

        <ol className="space-y-4">
          {c.messages.map((m, i) => <Bubble key={i} m={m} name={c.name} />)}
        </ol>
        {c.history && c.history.length > 0 && (
          <details className="mt-6 rounded-lg border border-border">
            <summary className="cursor-pointer list-none px-3 py-2 text-[12.5px] font-[510]">Stage history ({c.history.length} moves)</summary>
            <ol className="border-t border-border px-3 py-2">
              {c.history.map((h, i) => (
                <li key={i} className="flex gap-3 py-1 text-[12px]">
                  <span className="w-28 shrink-0 font-mono text-[11px] text-faint">{when(h.at)}</span>
                  <span className="text-secondary">{stageLabel(h.from === "new" ? undefined : h.from)} → <b className="font-[510]">{stageLabel(h.to)}</b> <span className="text-muted-foreground">({h.why})</span></span>
                </li>
              ))}
            </ol>
          </details>
        )}
        <div ref={end} />
      </div>

      {open && (
        <div className="border-t border-border bg-elevated px-5 py-3">
          {c.stage === "interview" && (
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <span className="text-[12px] text-muted-foreground">Record the panel&apos;s verdict:</span>
              <Button disabled={busy || live} onClick={() => act(() => talent.feedback(campId, cid, true, "passed (entered in the UI)"))} title="Passed: Sourced moves them toward an offer">Passed</Button>
              <Button disabled={busy || live} variant="danger" onClick={() => act(() => talent.feedback(campId, cid, false, "did not pass (entered in the UI)"))} title="Didn't pass: Sourced sends a kind rejection">Didn&apos;t pass</Button>
            </div>
          )}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (reply.trim()) act(() => talent.reply(campId, cid, reply.trim()));
            }}
            className="flex gap-2"
          >
            <input
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              disabled={busy || live}
              placeholder={c.stage === "offer" ? `Reply as ${c.name.split(" ")[0]}, e.g. "Signed: ${c.name}"` : `Reply as ${c.name.split(" ")[0]}, e.g. "Sounds good, tell me more"`}
              className="h-8 min-w-0 flex-1 rounded-md border border-border-strong bg-panel px-2.5 text-[13px] outline-none focus:border-primary/60"
            />
            <Button type="submit" variant="primary" disabled={!reply.trim() || busy || live}>
              {busy ? <Loader2 className="size-3.5 animate-spin" /> : <Send className="size-3.5" />} Send as candidate
            </Button>
          </form>
          <p className="mt-1.5 text-[11px] text-faint">
            {live ? "Pause the clock to reply by hand." : "Simulation: you play the candidate. Sourced reads your reply and answers through Send Guard."}
          </p>
          {err && <p className="mt-1.5 text-[12px] text-contradicted">{err}</p>}
        </div>
      )}
    </div>
  );
}

function Bubble({ m, name }: { m: Message; name: string }) {
  const out = m.dir === "out";
  const blocked = out && m.guard?.decision === "block";
  return (
    <li className={cn("flex flex-col", out ? "items-end" : "items-start")}>
      <p className="mb-1 text-[11px] text-faint">
        <span className="font-[510] text-muted-foreground">{out ? "Sourced" : name.split(" ")[0]}</span>
        {out && m.kind && ` · ${MESSAGE_KIND[m.kind] ?? m.kind.replace(/_/g, " ")}`} · {when(m.at)}
      </p>
      <div
        className={cn(
          "max-w-[88%] whitespace-pre-wrap rounded-lg border px-3 py-2 text-[13px] leading-relaxed",
          out ? "border-border-strong bg-panel" : "border-transparent bg-elevated",
          blocked && "border-contradicted/40 bg-contradicted/[0.04] text-muted-foreground line-through decoration-contradicted/40",
        )}
      >
        {m.body}
      </div>
      {out && m.guard && (
        <div className={cn("mt-1 max-w-[88%] text-right text-[11px]", blocked ? "text-contradicted" : "text-muted-foreground")}>
          <span className="inline-flex items-center gap-1" title={blocked ? "Send Guard refused this message, so it was never sent" : "Send Guard checked the passport, the agent's signature on this text, the recipient and every fact in it"}>
            {blocked ? <ShieldX className="size-3" /> : <ShieldCheck className="size-3 text-verified" />}
            {blocked ? "Blocked by Send Guard" : "Send Guard allowed"}
          </span>
          {m.guard.ledger_entry && (
            <Link href="/console?view=ledger" prefetch={false} className="ml-2 font-mono text-faint hover:text-foreground hover:underline" title={`Ledger entry ${m.guard.ledger_entry}`}>
              ledger {m.guard.ledger_entry.slice(0, 10)}
            </Link>
          )}
          <span className="ml-2 text-faint" title={m.delivery?.detail}>{deliveryText(m)}</span>
          {blocked && (m.guard.failed?.length ?? 0) > 0 && (
            <ul className="mt-1 space-y-0.5 text-left">
              {m.guard.failed!.map((f, i) => <li key={i}>· {typeof f === "string" ? f : [f.name, f.detail].filter(Boolean).join(": ")}</li>)}
            </ul>
          )}
        </div>
      )}
      {!out && m.read_as?.intent && (
        <p className="mt-1 text-[11px] text-faint" title={m.read_as.by ? `Classified by ${m.read_as.by}` : undefined}>
          Sourced read this as <span className="font-[510] text-muted-foreground">{m.read_as.intent.replace(/_/g, " ")}</span>
          {m.read_as.question && <> · asked &ldquo;{m.read_as.question}&rdquo;</>}
        </p>
      )}
    </li>
  );
}

function deliveryText(m: Message): string {
  if (m.guard?.decision === "block") return "not sent";
  const d = m.delivery;
  if (!d?.status) return "kept in this transcript, not emailed";
  if (d.status === "sent") return `emailed${d.to ? ` to ${d.to}` : ""}${d.at ? ` · ${when(d.at)}` : ""}`;
  if (d.status === "draft" || d.status === "held") return "draft, waiting for a person to send";
  if (d.status === "failed") return "email failed";
  return d.status;
}
