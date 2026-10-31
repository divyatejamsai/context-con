"use client";
// Emergency stop (backend/app/runtime/freeze.py): freeze one agent, every agent a person vouched for, or all of them,
// see what each one touched in the last 24 hours, and lift the stop after a fresh sponsor check.
import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, OctagonX, RotateCcw, ShieldOff, UserRound, Users, X } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  ApiError, estop, type Agent, type Blast, type BlastAgent, type Freeze, type FreezePreview, type FreezeScope, type Person, type SponsorGroup,
} from "./api";
import { Button, EmptyState, PageHead, SectionHead, StatusPill, ago, cardCls, inputCls, plain } from "./parts";

type Pick = { scope: FreezeScope; target: string | null };
type Note = { tone: "ok" | "bad" | "info"; title: string; body?: string } | null;

const OUTCOME: Record<string, { label: string; cls: string }> = {
  restored: { label: "Back to work", cls: "text-verified" },
  still_suspended: { label: "Still suspended: sponsor check failed", cls: "text-contradicted" },
  was_suspended_before: { label: "Was suspended before the stop, left as is", cls: "text-muted-foreground" },
  held_elsewhere: { label: "Still held by another stop", cls: "text-flag" },
  gone: { label: "No longer in the registry", cls: "text-muted-foreground" },
};

export function EmergencyStopView({ agents, onChanged }: { agents: Agent[]; onChanged: () => void }) {
  const [active, setActive] = useState<Freeze[]>([]);
  const [history, setHistory] = useState<Freeze[]>([]);
  const [sponsors, setSponsors] = useState<SponsorGroup[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [pick, setPick] = useState<Pick | null>(null);
  const [preview, setPreview] = useState<FreezePreview | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<Note>(null);
  const live = useMemo(() => agents.filter((a) => a.status !== "offboarded"), [agents]);
  const [agentSel, setAgentSel] = useState("");
  const [sponsorSel, setSponsorSel] = useState("");

  const load = useCallback(async () => {
    try {
      const o = await estop.overview();
      setActive(o.active);
      setHistory(o.history);
      setSponsors(o.sponsors);
    } catch (e) {
      setNote({ tone: "bad", title: "Couldn't load emergency stops", body: e instanceof Error ? e.message : String(e) });
    } finally {
      setLoaded(true);
    }
  }, []);

  const review = useCallback(async (p: Pick) => {
    setPick(p);
    setPreview(null);
    setNote(null);
    setBusy("preview");
    try {
      setPreview(await estop.preview(p.scope, p.target));
    } catch (e) {
      setPick(null);
      setNote({ tone: "bad", title: "Couldn't prepare the stop", body: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  }, []);

  useEffect(() => {
    load();
    // /console?view=estop&freeze=<agent id or name>: an agent's page links here with that agent picked
    const t = new URLSearchParams(window.location.search).get("freeze");
    if (t) {
      setAgentSel(t);
      review({ scope: "agent", target: t });
    }
  }, [load, review]);


  const fail = (title: string, e: unknown) => {
    const err = e instanceof ApiError ? e : new ApiError(String(e), 0);
    setNote({
      tone: "bad",
      title: err.status === 403 ? "Only an admin can do this" : err.status === 401 ? "Log in first" : title,
      body: err.message,
    });
  };

  const doFreeze = async () => {
    if (!pick || !preview) return;
    setBusy("freeze");
    setNote(null);
    try {
      const f = await estop.freeze(pick.scope, pick.target, reason);
      const n = f.agents.length;
      setNote({
        tone: "info",
        title: `Stopped ${f.label}`,
        body: `${n} agent${n === 1 ? "" : "s"} frozen. Passports revoked, ${f.stopped_tasks.length} task${f.stopped_tasks.length === 1 ? "" : "s"} stopped, ${f.pulled_approvals.length} draft${f.pulled_approvals.length === 1 ? "" : "s"} pulled. Written to the ledger.`,
      });
      setPick(null);
      setPreview(null);
      setReason("");
      await load();
      onChanged();
    } catch (e) {
      fail("Couldn't stop them", e);
    } finally {
      setBusy(null);
    }
  };

  const lift = async (f: Freeze, bringBack: boolean) => {
    setBusy(`lift:${f.freeze_id}`);
    setNote(null);
    try {
      const r = await estop.restore(f.freeze_id, bringBack);
      const back = r.agents.filter((a) => a.outcome === "restored").map((a) => a.name);
      const still = r.agents.filter((a) => a.outcome === "still_suspended").map((a) => a.name);
      setNote({
        tone: still.length ? "bad" : "ok",
        title: back.length ? `Lifted: ${back.join(", ")} ${back.length === 1 ? "is" : "are"} back` : "Lifted, but nobody came back",
        body: [
          still.length ? `${still.join(", ")} stayed suspended because a fresh sponsor check failed.` : "",
          r.bring_back ? `${r.requeued_tasks?.length ?? 0} task(s) re-queued, ${r.returned_approvals?.length ?? 0} draft(s) back for approval.` : "",
        ].filter(Boolean).join(" ") || undefined,
      });
      await load();
      onChanged();
    } catch (e) {
      fail("Couldn't lift the stop", e);
    } finally {
      setBusy(null);
    }
  };

  const sponsor = sponsors.find((s) => s.key === sponsorSel) ?? sponsors[0];
  const agentId = (live.find((a) => a.agent_id === agentSel || a.name.toLowerCase() === agentSel.toLowerCase()) ?? live[0])?.agent_id ?? "";

  return (
    <main className="mx-auto max-w-[1120px] px-4 pb-20 pt-6 sm:px-8 sm:pt-8">
      <PageHead title="Emergency stop">
        Freeze one agent, every agent a person vouched for, or all of them, in one click. Their passports are revoked so every verify
        link turns red, running work stops, and drafts waiting for approval are pulled. You see what each one touched in the last 24 hours,
        and you can lift the stop once a fresh sponsor check passes.
      </PageHead>

      {note && <NoteBar note={note} onClose={() => setNote(null)} />}

      {active.length > 0 && (
        <section className="mt-6 space-y-3">
          <SectionHead title={`${active.length} stop${active.length === 1 ? "" : "s"} in force`}>
            These agents can&apos;t work, send or sign until you lift the stop.
          </SectionHead>
          {active.map((f) => (
            <ActiveStop key={f.freeze_id} f={f} busy={busy} onLift={lift} />
          ))}
        </section>
      )}

      <section className="mt-8">
        <SectionHead title="Stop agents now">Pick who to stop. You&apos;ll see exactly what happens before anything changes.</SectionHead>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <Choice icon={UserRound} title="One agent" body="Freeze a single agent that's misbehaving.">
            <select value={agentId} onChange={(e) => setAgentSel(e.target.value)} className={inputCls} aria-label="Agent to stop" disabled={!live.length}>
              {live.map((a) => (
                <option key={a.agent_id} value={a.agent_id}>
                  {a.name}{a.status === "suspended" ? " (suspended)" : ""}
                </option>
              ))}
            </select>
            <Button variant="danger" className="w-full" disabled={!agentId || busy === "preview"} onClick={() => review({ scope: "agent", target: agentId })}>
              <OctagonX className="size-3.5" /> Review stop
            </Button>
          </Choice>
          <Choice icon={Users} title="Everyone a person vouched for" body="Their account may be compromised, or they just left.">
            <select value={sponsor?.key ?? ""} onChange={(e) => setSponsorSel(e.target.value)} className={inputCls} aria-label="Sponsor" disabled={!sponsors.length}>
              {sponsors.map((s) => (
                <option key={s.key} value={s.key}>
                  {s.name} ({s.agents.length} agent{s.agents.length === 1 ? "" : "s"})
                </option>
              ))}
            </select>
            <Button variant="danger" className="w-full" disabled={!sponsor || busy === "preview"}
              onClick={() => sponsor && review({ scope: "sponsor", target: sponsor.profile_url || sponsor.name })}>
              <OctagonX className="size-3.5" /> Review stop
            </Button>
          </Choice>
          <Choice icon={ShieldOff} title="Every agent" body={`All ${live.length} agent${live.length === 1 ? "" : "s"} you can see. Use it when you don't know yet what went wrong.`} strong>
            <div className="h-8" />
            <Button variant="danger" className="w-full border-contradicted bg-contradicted text-white hover:bg-contradicted/90 hover:text-white"
              disabled={!live.length || busy === "preview"} onClick={() => review({ scope: "all", target: null })}>
              <OctagonX className="size-3.5" /> Review stop for all
            </Button>
          </Choice>
        </div>
      </section>

      {pick && (
        <section className={cn(cardCls, "mt-5 animate-rise border-contradicted/40 p-4 sm:p-5")}>
          {!preview ? (
            <p className="inline-flex items-center gap-2 text-[13px] text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Working out who this stops and what they touched…
            </p>
          ) : (
            <Confirm preview={preview} reason={reason} setReason={setReason} busy={busy === "freeze"} onGo={doFreeze}
              onCancel={() => { setPick(null); setPreview(null); }} />
          )}
        </section>
      )}

      {loaded && !active.length && !pick && !history.length && (
        <div className={cn(cardCls, "mt-8")}>
          <EmptyState icon={OctagonX} title="No stops yet">
            When you stop agents, the stop shows here with what each agent touched, and stays on the ledger after you lift it.
          </EmptyState>
        </div>
      )}

      {history.length > 0 && (
        <section className="mt-10">
          <SectionHead title="Past stops">Lifted stops, newest first. Each one is on the ledger with who stopped it and who lifted it.</SectionHead>
          <ul className={cn(cardCls, "mt-3 divide-y divide-border")}>
            {history.map((f) => (
              <li key={f.freeze_id} className="px-4 py-3 text-[12.5px]">
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                  <p className="font-[590] text-foreground">{f.label}</p>
                  <p className="text-faint">
                    stopped {ago(f.at)} by {f.by} · lifted {ago(f.restored_at)} by {f.restored_by}
                  </p>
                </div>
                <p className="mt-0.5 text-muted-foreground">{plain(f.reason)}</p>
                <p className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
                  {f.agents.map((a) => (
                    <span key={a.agent_id} className={OUTCOME[a.outcome ?? ""]?.cls}>
                      <b className="font-[560]">{a.name}</b>: {OUTCOME[a.outcome ?? ""]?.label ?? a.outcome}
                    </span>
                  ))}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}

function Choice({ icon: I, title, body, children, strong }: { icon: React.ElementType; title: string; body: string; children: React.ReactNode; strong?: boolean }) {
  return (
    <div className={cn(cardCls, "flex flex-col gap-2.5 p-4", strong && "border-contradicted/35 bg-contradicted/[0.03]")}>
      <div className="flex items-start gap-2.5">
        <span className="grid size-8 shrink-0 place-items-center rounded-lg border border-contradicted/30 bg-contradicted/[0.06] text-contradicted">
          <I className="size-4" />
        </span>
        <div className="min-w-0">
          <p className="text-[13.5px] font-[590]">{title}</p>
          <p className="mt-0.5 text-[12px] leading-snug text-muted-foreground">{body}</p>
        </div>
      </div>
      <div className="mt-auto space-y-2">{children}</div>
    </div>
  );
}

function plural(n: number, one: string, many = `${one}s`) {
  return `${n} ${n === 1 ? one : many}`;
}

function Confirm({
  preview: p, reason, setReason, busy, onGo, onCancel,
}: { preview: FreezePreview; reason: string; setReason: (s: string) => void; busy: boolean; onGo: () => void; onCancel: () => void }) {
  const w = p.will;
  const n = p.agents.length;
  return (
    <div>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[15px] font-[620] tracking-[-0.01em]">Stop {p.label}?</p>
          <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">
            {w.suspend.length ? <>Suspends {w.suspend.join(", ")} and revokes {w.suspend.length === 1 ? "its passport" : "their passports"}, so Send Guard, MCP calls and every verify link refuse {w.suspend.length === 1 ? "it" : "them"}. </> : null}
            {w.already_suspended.length ? <>{w.already_suspended.join(", ")} {w.already_suspended.length === 1 ? "is" : "are"} already suspended and stay{w.already_suspended.length === 1 ? "s" : ""} that way. </> : null}
            Stops {plural(w.running_tasks, "running task")} and cancels {plural(w.queued_tasks, "queued task")}, pulls {plural(w.pending_approvals, "draft")} waiting for approval, and switches off {plural(w.schedules, "schedule")}.
          </p>
        </div>
        <button onClick={onCancel} className="rounded-md p-1 text-faint hover:bg-hover hover:text-foreground" aria-label="Cancel">
          <X className="size-4" />
        </button>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {p.agents.map((a) => (
          <span key={a.agent_id} className="inline-flex items-center gap-1.5 rounded-md border border-border-strong bg-elevated px-2 py-1 text-[12px]">
            <b className="font-[560]">{a.name}</b>
            <span className="text-faint">for {a.sponsor.name}</span>
            <StatusPill status={a.status} />
          </span>
        ))}
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} onKeyDown={(e) => e.key === "Enter" && !busy && onGo()}
          placeholder="Why, e.g. emailed the wrong list" className={cn(inputCls, "min-w-0 flex-1 sm:min-w-[260px]")} aria-label="Reason" />
        <Button variant="danger" className="border-contradicted bg-contradicted text-white hover:bg-contradicted/90 hover:text-white" onClick={onGo} disabled={busy}>
          {busy ? <Loader2 className="size-3.5 animate-spin" /> : <OctagonX className="size-3.5" />} Stop {n === 1 ? p.agents[0].name : `${n} agents`} now
        </Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
      <p className="mt-1.5 text-[11.5px] text-faint">Your reason and name go on the ledger. You can lift the stop later from this page.</p>
      <div className="mt-6">
        <BlastView blast={p.blast} title="What they touched in the last 24 hours" />
      </div>
    </div>
  );
}

function ActiveStop({ f, busy, onLift }: { f: Freeze; busy: string | null; onLift: (f: Freeze, bringBack: boolean) => void }) {
  const [bring, setBring] = useState(true);
  const [open, setOpen] = useState(false);
  const working = busy === `lift:${f.freeze_id}`;
  const comeBack = f.agents.filter((a) => a.prior_status === "active").length;
  return (
    <div className={cn(cardCls, "border-contradicted/40 bg-contradicted/[0.03] p-4")}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-[14px] font-[620]">
            <span className="relative flex size-2"><span className="absolute inset-0 animate-ping rounded-full bg-contradicted/60" /><span className="relative size-2 rounded-full bg-contradicted" /></span>
            Stopped: {f.label}
          </p>
          <p className="mt-0.5 text-[12.5px] text-muted-foreground">
            {plain(f.reason)} · by {f.by} · {ago(f.at)}
          </p>
          <p className="mt-1.5 text-[12px] text-secondary">
            {plural(f.agents.length, "agent")} frozen · {plural(f.stopped_tasks.length, "task")} stopped · {plural(f.pulled_approvals.length, "draft")} pulled
            {f.schedules_off.length ? ` · ${plural(f.schedules_off.length, "schedule")} off` : ""}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {f.agents.map((a) => (
              <span key={a.agent_id} className="inline-flex items-center gap-1 rounded-md border border-border-strong bg-panel px-2 py-0.5 text-[12px]">
                <b className="font-[560]">{a.name}</b>
                {a.prior_status !== "active" && <span className="text-faint">(already suspended)</span>}
              </span>
            ))}
          </div>
        </div>
        <div className="flex flex-col items-end gap-2">
          <Button onClick={() => onLift(f, bring)} disabled={!!busy || !comeBack} title="Runs a fresh sponsor check for each agent; only the ones that pass come back">
            {working ? <Loader2 className="size-3.5 animate-spin" /> : <RotateCcw className="size-3.5" />} Lift stop
          </Button>
          <label className="flex max-w-[260px] items-start gap-1.5 text-right text-[11.5px] leading-snug text-muted-foreground">
            <input type="checkbox" checked={bring} onChange={(e) => setBring(e.target.checked)} className="mt-0.5 accent-[var(--primary)]" />
            Also bring back the stopped work: re-queue {plural(f.stopped_tasks.length, "task")}, return {plural(f.pulled_approvals.length, "draft")} for approval
          </label>
        </div>
      </div>
      <button onClick={() => setOpen((o) => !o)} className="mt-3 text-[12px] font-[510] text-primary hover:underline">
        {open ? "Hide" : "Show"} what they touched in the 24 hours before the stop
      </button>
      {open && <div className="mt-3"><BlastView blast={f.blast} /></div>}
    </div>
  );
}

function who(p?: Person | null) {
  if (!p) return "someone";
  return [p.name || p.email || "someone", p.company].filter(Boolean).join(", ");
}

function hhmm(iso?: string | null) {
  return iso ? new Date(iso).toLocaleString("en-GB", { hour: "2-digit", minute: "2-digit", day: "numeric", month: "short" }) : "";
}

export function BlastView({ blast: b, title }: { blast: Blast; title?: string }) {
  const t = b.totals;
  const tiles: [string, string | number, string][] = [
    ["Messages sent", t.messages_sent, t.offers_signed ? `incl. ${plural(t.offers_signed, "signed offer")}` : "emails, approved drafts, offers"],
    ["People contacted", t.people, "distinct recipients and repliers"],
    ["Data read", t.crustdata_calls, `Crustdata calls · ${plural(t.records, "record")} produced`],
    ["Approvals", t.approvals, t.pending_approvals ? `${t.pending_approvals} still waiting` : "asked of a person"],
    ["Spend", t.crustdata_calls + t.llm_calls, `${t.crustdata_calls} Crustdata + ${t.llm_calls} LLM calls`],
  ];
  return (
    <div>
      <SectionHead title={title ?? "What they touched"}>
        {hhmm(b.since)} to {hhmm(b.until)}, from the ledger and the runtime. {plural(t.ledger_entries, "ledger entry", "ledger entries")}
        {t.guard_blocked ? `, ${t.guard_blocked} blocked by Send Guard` : ""}{t.rules_blocked ? `, ${t.rules_blocked} blocked by a rule` : ""}.
      </SectionHead>
      <div className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-5">
        {tiles.map(([k, v, d]) => (
          <div key={k} className="bg-panel px-3 py-2.5">
            <p className="text-[11.5px] text-muted-foreground">{k}</p>
            <p className="mt-0.5 text-[20px] font-[620] tabular-nums tracking-[-0.02em]">{v}</p>
            <p className="text-[11px] leading-snug text-faint">{d}</p>
          </div>
        ))}
      </div>
      <div className="mt-3 space-y-2">
        {b.agents.map((a) => <AgentBlast key={a.agent_id} a={a} />)}
      </div>
    </div>
  );
}

function AgentBlast({ a }: { a: BlastAgent }) {
  const quiet = !a.messages_sent.length && !a.people.length && !a.data.reads.length && !a.approvals.length;
  return (
    <details className={cn(cardCls, "group")}>
      <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-2 px-3.5 py-2.5 text-[12.5px]">
        <span className="flex items-center gap-2">
          <b className="font-[590]">{a.name}</b>
          {a.sponsor && <span className="text-faint">for {a.sponsor.name}</span>}
        </span>
        <span className="text-muted-foreground tabular-nums">
          {quiet ? "nothing in this window" : `${plural(a.messages_sent.length, "message")} · ${plural(a.people.length, "person", "people")} · ${a.data.crustdata_calls} reads · ${plural(a.approvals.length, "approval")}`}
          <span className="ml-2 text-faint group-open:hidden">Show</span>
          <span className="ml-2 hidden text-faint group-open:inline">Hide</span>
        </span>
      </summary>
      {!quiet && (
        <div className="grid gap-4 border-t border-border px-3.5 py-3 text-[12px] md:grid-cols-2">
          <List title="Messages sent" empty="None">
            {a.messages_sent.map((m, i) => (
              <li key={i}><span className="text-faint">{hhmm(m.ts)}</span> {m.what} to <b className="font-[560]">{who(m.to)}</b>{m.how ? <span className="text-faint"> · {m.how}</span> : null}</li>
            ))}
          </List>
          <List title="People contacted" empty="Nobody">
            {a.people.map((p, i) => (
              <li key={i}>
                {p.profile_url ? <a href={p.profile_url} target="_blank" rel="noreferrer" className="font-[560] hover:underline">{who(p)}</a> : <b className="font-[560]">{who(p)}</b>}
                {p.events && p.events > 1 ? <span className="text-faint"> · {p.events} times</span> : null}
              </li>
            ))}
          </List>
          <List title={`Data read (${a.data.crustdata_calls} Crustdata calls, ${a.data.llm_calls} LLM calls)`} empty="No reads">
            {a.data.reads.map((r, i) => (
              <li key={i}><span className="text-faint">{hhmm(r.ts)}</span> {plain(r.what)}{r.crustdata ? <span className="text-faint"> · {r.crustdata} calls</span> : null}{r.status ? <span className="text-faint"> · {r.status}</span> : null}</li>
            ))}
          </List>
          <List title="Approvals" empty="None asked">
            {a.approvals.map((x) => (
              <li key={x.approval_id}>
                <span className="text-faint">{hhmm(x.created_at)}</span> {x.action === "sign_offer" ? "Offer for" : "Draft to"} <b className="font-[560]">{who(x.to)}</b>: {x.status.replace(/_/g, " ")}
                {x.decided_by ? <span className="text-faint"> · {x.decided_by}</span> : null}
              </li>
            ))}
          </List>
        </div>
      )}
    </details>
  );
}

function List({ title, empty, children }: { title: string; empty: string; children: React.ReactNode[] }) {
  return (
    <div className="min-w-0">
      <p className="mb-1 font-[560] text-secondary">{title}</p>
      {children.length ? <ul className="space-y-1 break-words text-muted-foreground">{children}</ul> : <p className="text-faint">{empty}</p>}
    </div>
  );
}

function NoteBar({ note, onClose }: { note: NonNullable<Note>; onClose: () => void }) {
  return (
    <div className={cn("mt-5 flex items-start justify-between gap-3 rounded-lg border px-3.5 py-2.5 text-[12.5px] animate-rise",
      note.tone === "ok" ? "border-verified/30 bg-verified/[0.06]" : note.tone === "bad" ? "border-contradicted/30 bg-contradicted/[0.06]" : "border-border-strong bg-elevated")}>
      <div className="min-w-0">
        <p className="font-[590]">{note.title}</p>
        {note.body && <p className="mt-0.5 text-muted-foreground">{note.body}</p>}
      </div>
      <button onClick={onClose} className="rounded p-0.5 text-faint hover:text-foreground" aria-label="Dismiss"><X className="size-3.5" /></button>
    </div>
  );
}
