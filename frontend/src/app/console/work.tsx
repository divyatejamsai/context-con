"use client";
// The Work view: the employer's live control plane over running AI employees (backend/app/runtime).
// Everything here is read from /api/runtime/state every 1.5s; every button changes the real runtime.
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity as ActivityIcon, Ban, Check as CheckIcon, Clock, ExternalLink, Gauge, Loader2, Pause, Play, Plus, Receipt,
  RefreshCw, Repeat, Settings2, ShieldAlert, Trash2, X,
} from "lucide-react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import {
  ApiError, receiptUrl, runtime, type Approval, type LiveAgent, type RuntimeState, type Task, type TaskKind,
} from "./api";
import { Button, EmptyState, Field, PageHead, ScopeChip, SectionHead, VerdictList, ago, cardCls, checkLabel, inputCls } from "./parts";

const ACTIVITY: Record<string, { label: string; cls: string; dot: string }> = {
  working: { label: "Working", cls: "border-sky/40 bg-sky/10 text-foreground", dot: "bg-sky animate-pulse" },
  idle: { label: "Idle", cls: "border-border-strong bg-elevated text-muted-foreground", dot: "bg-faint" },
  waiting_on_you: { label: "Waiting on you", cls: "border-yellow/50 bg-yellow/15 text-foreground", dot: "bg-yellow" },
  paused: { label: "Paused", cls: "border-unverifiable/40 bg-unverifiable/10 text-foreground", dot: "bg-unverifiable" },
  suspended: { label: "Suspended", cls: "border-contradicted/40 bg-contradicted/10 text-contradicted", dot: "bg-contradicted" },
  offboarded: { label: "Offboarded", cls: "border-border bg-elevated text-faint", dot: "bg-faint" },
};

const TASK_STATUS: Record<string, string> = {
  queued: "text-muted-foreground", running: "text-sky", done: "text-verified", failed: "text-contradicted",
  refused: "text-contradicted", cancelled: "text-faint",
};

const SEND_STATE: Record<string, { label: string; cls: string }> = {
  blocked: { label: "Blocked by Send Guard", cls: "text-contradicted" },
  pending_approval: { label: "Waiting for approval", cls: "text-flag" },
  sent: { label: "Sent (outbox)", cls: "text-verified" },
  rejected: { label: "Rejected by you", cls: "text-muted-foreground" },
  blocked_at_send: { label: "Blocked at send time", cls: "text-contradicted" },
  expired: { label: "Expired", cls: "text-faint" },
};

const pct = (x: number | null | undefined) => (x == null ? "–" : `${Math.round(x * 100)}%`);
const secs = (x: number | null | undefined) => (x == null ? "–" : x < 90 ? `${Math.round(x)}s` : `${Math.round(x / 60)}m`);
const errMsg = (e: unknown) => (e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e));

export function WorkView({ onChanged }: { onChanged?: () => void }) {
  const [st, setSt] = useState<RuntimeState | null>(null);
  const [kinds, setKinds] = useState<TaskKind[]>([]);
  const [err, setErr] = useState<string>();
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const [assignFor, setAssignFor] = useState<string | null>(null);
  const [openTask, setOpenTask] = useState<string | null>(null);
  const [settingsFor, setSettingsFor] = useState<string | null>(null);
  const [allPending, setAllPending] = useState(false);

  const load = useCallback(async () => {
    try {
      setSt(await runtime.state());
      setErr(undefined);
    } catch (e) {
      setErr(errMsg(e));
    }
  }, []);

  useEffect(() => {
    load();
    runtime.kinds().then(setKinds).catch(() => {});
    const t = setInterval(load, 1500);
    return () => clearInterval(t);
  }, [load]);

  const act = useCallback(async (key: string, fn: () => Promise<unknown>, ok?: string) => {
    setBusy(key);
    try {
      await fn();
      if (ok) setToast({ tone: "ok", text: ok });
      await load();
      onChanged?.();
      return true;
    } catch (e) {
      setToast({ tone: "bad", text: errMsg(e) });
      return false;
    } finally {
      setBusy(null);
    }
  }, [load, onChanged]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 5000);
    return () => clearTimeout(t);
  }, [toast]);

  if (!st) {
    return (
      <main className="mx-auto max-w-[1280px] px-4 py-8 sm:px-6">
        {err ? (
          <EmptyState icon={ShieldAlert} tone="bad" title="Can't reach the agent runtime">{err}</EmptyState>
        ) : (
          <div className="grid min-h-[40vh] place-items-center text-[13px] text-faint">
            <span className="inline-flex items-center gap-2"><Loader2 className="size-4 animate-spin" /> Loading live work…</span>
          </div>
        )}
      </main>
    );
  }

  const live = st.agents.filter((a) => a.status !== "offboarded" && a.runtime !== "external");
  const outside = st.agents.filter((a) => a.status !== "offboarded" && a.runtime === "external");

  return (
    <main className="mx-auto max-w-[1280px] px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <PageHead title="Work" eyebrow="Live">
          Your AI employees and the tasks they&apos;re running. Give them work, approve what they want to send, pause or stop
          them mid-task, and set their budgets. Every change is written to the ledger.
        </PageHead>
        <div className="flex items-center gap-2">
          <span className={cn("inline-flex h-6 items-center gap-1.5 rounded-full border px-2.5 text-[11.5px] font-[510]",
            st.runtime.alive ? "border-verified/40 bg-verified/10" : "border-contradicted/40 bg-contradicted/10 text-contradicted")}>
            <span className={cn("size-1.5 rounded-full", st.runtime.alive ? "bg-verified animate-pulse" : "bg-contradicted")} />
            {st.runtime.alive ? `Runtime on · ${st.runtime.running}/${st.runtime.max_concurrent} running` : "Runtime off"}
          </span>
          <span className="hidden font-mono text-[11px] text-faint sm:inline">
            crustdata {st.runtime.modes.crustdata} · llm {st.runtime.modes.llm}
          </span>
          <Button onClick={() => setAssignFor("")} variant="primary"><Plus className="size-3.5" /> Assign work</Button>
        </div>
      </div>

      {toast && (
        <div className={cn("mt-4 rounded-lg border px-3 py-2 text-[12.5px]",
          toast.tone === "ok" ? "border-verified/40 bg-verified/10" : "border-contradicted/40 bg-contradicted/10 text-contradicted")}>
          {toast.text}
        </div>
      )}

      <section className="mt-5 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border-strong bg-border sm:grid-cols-4 lg:grid-cols-7">
        <Kpi label="Working now" value={st.totals.working} />
        <Kpi label="Queued" value={st.totals.queued} />
        <Kpi label="Waiting on you" value={st.totals.pending_approvals} tone={st.totals.pending_approvals ? "warn" : undefined} />
        <Kpi label="Done today" value={st.totals.done_today} />
        <Kpi label="Failed / refused" value={st.totals.failed_today} tone={st.totals.failed_today ? "bad" : undefined} />
        <Kpi label="Sent today" value={st.totals.sent_today} />
        <Kpi label="Ledger" value={st.ledger.chain_ok ? "Intact" : `Broken #${st.ledger.first_bad_seq}`} tone={st.ledger.chain_ok ? "ok" : "bad"} />
      </section>

      <section className="mt-7">
        <SectionHead title={`Waiting on you (${st.approvals.pending.length})`}>
          Messages Send Guard has already cleared. Nothing leaves until you approve it, and approving runs the guard again
          at send time.
        </SectionHead>
        {st.approvals.pending.length ? (
          <div className="mt-3 grid gap-3 lg:grid-cols-2">
            {(allPending ? st.approvals.pending : st.approvals.pending.slice(0, 4)).map((a) => (
              <ApprovalCard key={a.approval_id} a={a} busy={busy}
                onApprove={() => act(`apv:${a.approval_id}`, () => runtime.approve(a.approval_id), `Approved: message to ${a.to.name}`)}
                onReject={() => act(`apv:${a.approval_id}`, () => runtime.reject(a.approval_id), `Rejected: message to ${a.to.name}`)} />
            ))}
            {st.approvals.pending.length > 4 && (
              <button onClick={() => setAllPending(!allPending)} className="text-left text-[12.5px] font-[510] text-primary hover:underline lg:col-span-2">
                {allPending ? "Show fewer" : `Show all ${st.approvals.pending.length} waiting`}
              </button>
            )}
          </div>
        ) : (
          <p className="mt-3 rounded-lg border border-dashed border-border-strong px-4 py-3 text-[12.5px] text-muted-foreground">
            Nothing waiting. When an agent drafts a message that clears Send Guard, it shows up here for you to approve or reject.
          </p>
        )}
      </section>

      <section className="mt-8">
        <SectionHead title="AI employees">Each one&apos;s live status, what it&apos;s doing now, its report card, and today&apos;s budget.</SectionHead>
        {live.length ? (
          <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {live.map((a) => (
              <AgentCard key={a.agent_id} a={a} busy={busy} kinds={kinds}
                onAssign={() => setAssignFor(a.agent_id)}
                onOpen={(id) => setOpenTask(id)}
                onSettings={() => setSettingsFor(a.agent_id)}
                onPause={() => act(`ag:${a.agent_id}`, () => runtime.pause(a.agent_id, "paused from the Work view"), `${a.name} paused`)}
                onResume={() => act(`ag:${a.agent_id}`, () => runtime.resume(a.agent_id), `${a.name} resumed`)}
                onSuspend={() => {
                  const reason = window.prompt(`Suspend ${a.name}? Its running task stops now and its passport is revoked until reinstated. Reason:`, "suspended by the employer");
                  if (reason) act(`ag:${a.agent_id}`, () => runtime.suspend(a.agent_id, reason), `${a.name} suspended`);
                }} />
            ))}
          </div>
        ) : (
          <EmptyState title="No AI employees yet">Onboard one in AI employees (or run the guided demo), then give it work here.</EmptyState>
        )}
        {outside.length > 0 && (
          <p className="mt-3 text-[12px] text-muted-foreground">
            Outside agents ({outside.map((a) => a.name).join(", ")}) run on their own machines and reach Agaxes over MCP.
            Their checks and sends show up in the ledger. You can suspend them from AI employees.
          </p>
        )}
      </section>

      <section className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0">
          <SectionHead title="Tasks">Newest first. Open one to see every step, its output, and a receipt for each ledger entry.</SectionHead>
          <div className={cn(cardCls, "mt-3 divide-y divide-border overflow-hidden")}>
            {st.tasks.length ? st.tasks.slice(0, 40).map((t) => (
              <button key={t.task_id} onClick={() => setOpenTask(t.task_id)} className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left hover:bg-hover">
                <span className={cn("w-[74px] shrink-0 text-[11.5px] font-[590] capitalize", TASK_STATUS[t.status])}>
                  {t.status === "running" && <Loader2 className="mr-1 inline size-3 animate-spin" />}{t.status}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] font-[510]">{t.title}</span>
                  <span className="block truncate text-[11.5px] text-muted-foreground">
                    {t.agent_name} · {t.result || t.error || t.waiting_on || t.last_step || ""}
                  </span>
                </span>
                {t.schedule_id && <Repeat className="size-3.5 shrink-0 text-faint" aria-label="from a schedule" />}
                <span className="shrink-0 text-[11px] tabular-nums text-faint">{ago(t.finished_at || t.started_at || t.created_at)}</span>
              </button>
            )) : <p className="px-4 py-6 text-center text-[12.5px] text-muted-foreground">No tasks yet. Use Assign work to give an agent its first job.</p>}
          </div>
        </div>
        <div className="space-y-6">
          <PayrollCard p={st.payroll} busy={busy}
            onRun={() => act("payroll", () => runtime.runPayroll(), "Payroll run finished")}
            onToggle={() => act("payroll", () => runtime.setPayroll({ enabled: !st.payroll.enabled }))}
            onEvery={(m) => act("payroll", () => runtime.setPayroll({ every_minutes: m }), `Payroll every ${m} min`)} />
          <SchedulesCard schedules={st.schedules} kinds={kinds} busy={busy}
            onToggle={(id) => act(`sch:${id}`, () => runtime.toggleSchedule(id))}
            onDelete={(id) => act(`sch:${id}`, () => runtime.deleteSchedule(id), "Schedule deleted")} />
          <DecidedCard decided={st.approvals.decided} />
        </div>
      </section>

      <AssignSheet open={assignFor !== null} initialAgent={assignFor || undefined} agents={live} kinds={kinds} busy={busy}
        onClose={() => setAssignFor(null)}
        onAssign={async (b, every) => {
          const ok = await act("assign", () => (every ? runtime.schedule({ ...b, every_minutes: every }) : runtime.assign(b)),
            every ? `Scheduled every ${every} min` : "Task assigned: it starts as soon as the agent is free");
          if (ok) setAssignFor(null);
        }} />
      <TaskSheet id={openTask} version={st.version} busy={busy} onClose={() => setOpenTask(null)}
        onCancel={(id) => act(`task:${id}`, () => runtime.cancel(id), "Task stopped")}
        onRetry={(id) => act(`task:${id}`, () => runtime.retry(id), "Queued again")} />
      <PolicySheet agent={st.agents.find((a) => a.agent_id === settingsFor) ?? null} busy={busy} onClose={() => setSettingsFor(null)}
        onSave={(b) => act("policy", () => runtime.policy(settingsFor!, b), "Saved").then((ok) => ok && setSettingsFor(null))} />
    </main>
  );
}

function Kpi({ label, value, tone }: { label: string; value: React.ReactNode; tone?: "ok" | "bad" | "warn" }) {
  return (
    <div className="bg-panel px-3.5 py-3">
      <p className="text-[11px] font-[510] text-muted-foreground">{label}</p>
      <p className={cn("mt-0.5 text-[20px] font-[620] tabular-nums tracking-[-0.02em]",
        tone === "bad" && "text-contradicted", tone === "ok" && "text-verified", tone === "warn" && "text-flag")}>{value}</p>
    </div>
  );
}

function ApprovalCard({ a, busy, onApprove, onReject }: { a: Approval; busy: string | null; onApprove: () => void; onReject: () => void }) {
  const [why, setWhy] = useState(false);
  const passed = a.preview.checks.filter((c) => c.status === "pass").length;
  const b = busy === `apv:${a.approval_id}`;
  return (
    <div className={cn(cardCls, "p-3.5")}>
      <div className="flex flex-wrap items-center gap-2 text-[12px]">
        <span className="font-[590]">{a.agent_name}</span>
        <span className="text-faint">wants to message</span>
        <span className="font-[590]">{a.to.name}</span>
        <span className="text-muted-foreground">at {a.to.company}</span>
        <span className="ml-auto"><ScopeChip scope={a.scope} muted /></span>
      </div>
      <pre className="mt-2.5 max-h-40 overflow-auto whitespace-pre-wrap rounded-md border border-border bg-elevated px-3 py-2 font-sans text-[12.5px] leading-relaxed">{a.body}</pre>
      <button onClick={() => setWhy(!why)} className="mt-2 inline-flex items-center gap-1 text-[11.5px] text-verified hover:underline">
        <CheckIcon className="size-3" /> Send Guard: {passed}/{a.preview.checks.length} checks passed {why ? "(hide)" : "(show)"}
      </button>
      {why && <VerdictList verdict={{ subject: a.approval_id, decision: a.preview.decision, checks: a.preview.checks }} className="mt-2" />}
      <div className="mt-3 flex items-center gap-2">
        <Button variant="primary" onClick={onApprove} disabled={!!busy}>{b ? <Loader2 className="size-3.5 animate-spin" /> : <CheckIcon className="size-3.5" />} Approve and send</Button>
        <Button variant="secondary" onClick={onReject} disabled={!!busy}><X className="size-3.5" /> Reject</Button>
        <span className="ml-auto text-[11px] text-faint">{ago(a.created_at)}</span>
      </div>
    </div>
  );
}

function Bar({ used, cap, label }: { used: number; cap: number; label: string }) {
  const f = cap ? Math.min(1, used / cap) : 0;
  return (
    <div>
      <div className="flex justify-between text-[10.5px] text-muted-foreground"><span>{label}</span><span className="tabular-nums">{used}/{cap}</span></div>
      <div className="mt-0.5 h-1 overflow-hidden rounded-full bg-elevated">
        <div className={cn("h-full rounded-full", f >= 1 ? "bg-contradicted" : f > 0.8 ? "bg-yellow" : "bg-primary")} style={{ width: `${f * 100}%` }} />
      </div>
    </div>
  );
}

function AgentCard({ a, busy, kinds, onAssign, onOpen, onPause, onResume, onSuspend, onSettings }: {
  a: LiveAgent; busy: string | null; kinds: TaskKind[]; onAssign: () => void; onOpen: (id: string) => void;
  onPause: () => void; onResume: () => void; onSuspend: () => void; onSettings: () => void;
}) {
  const s = ACTIVITY[a.activity] ?? ACTIVITY.idle;
  const m = a.metrics;
  const cur = a.current;
  const b = busy === `ag:${a.agent_id}`;
  const canWork = a.status === "active" && a.kinds.length > 0;
  return (
    <div className={cn(cardCls, "flex flex-col p-3.5")}>
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-[14px] font-[620]">{a.name} <span className="font-[450] text-muted-foreground">· {a.role}</span></p>
          <p className="truncate text-[11.5px] text-muted-foreground">for {a.sponsor.name} ({a.sponsor.title}, {a.sponsor.company})</p>
        </div>
        <span className={cn("inline-flex h-5 shrink-0 items-center gap-1.5 rounded-full border px-2 text-[11px] font-[510]", s.cls)}>
          <span className={cn("size-1.5 rounded-full", s.dot)} />{s.label}
        </span>
      </div>

      <div className="mt-3 min-h-[64px] rounded-lg border border-border bg-elevated px-3 py-2">
        {cur ? (
          <button onClick={() => onOpen(cur.task_id)} className="block w-full text-left">
            <p className="truncate text-[12.5px] font-[560]">{cur.title}</p>
            <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-border">
              <div className="h-full rounded-full bg-sky transition-all" style={{ width: cur.progress.total ? `${(100 * cur.progress.done) / cur.progress.total}%` : "30%" }} />
            </div>
            <p className="mt-1 truncate font-mono text-[10.5px] text-muted-foreground">{cur.last_step?.trim() || cur.progress.label}</p>
          </button>
        ) : a.status !== "active" ? (
          <p className="text-[12px] text-contradicted">{a.reason || a.status}</p>
        ) : a.policy.paused ? (
          <p className="text-[12px] text-muted-foreground">Paused: {a.policy.paused_reason}. {a.queued ? `${a.queued} task(s) held in the queue.` : ""}</p>
        ) : (
          <p className="text-[12px] text-muted-foreground">
            {a.queued ? `${a.queued} task(s) queued.` : "No task right now."} {a.job}
          </p>
        )}
      </div>

      <dl className="mt-3 grid grid-cols-4 gap-x-2 gap-y-2 text-center">
        <Stat k="Done" v={m.done} />
        <Stat k="Success" v={pct(m.success_rate)} />
        <Stat k="Avg time" v={secs(m.avg_seconds)} />
        <Stat k="Approved" v={pct(m.approval_rate)} title="Share of its drafts you approved" />
        <Stat k="Drafts" v={m.drafts} />
        <Stat k="Blocked" v={m.guard_blocked} title="Drafts Send Guard blocked" bad={m.guard_blocked > 0} />
        <Stat k="Sent" v={m.sent} />
        <Stat k="Lies caught" v={m.false_claims} title="False claims found in resumes it checked" />
      </dl>

      <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5">
        <Bar label="Tasks today" used={a.usage_today.tasks} cap={a.policy.budget.tasks_per_day} />
        <Bar label="Sends today" used={a.usage_today.sends} cap={a.policy.budget.sends_per_day} />
        <Bar label="Crustdata calls" used={a.usage_today.crustdata} cap={a.policy.budget.crustdata_calls_per_day} />
        <Bar label="Gemini calls" used={a.usage_today.llm} cap={a.policy.budget.llm_calls_per_day} />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-border pt-3">
        <Button variant="primary" onClick={onAssign} disabled={!canWork}
          title={canWork ? `Jobs: ${a.kinds.map((k) => kinds.find((x) => x.kind === k)?.label ?? k).join(", ")}` : "Not active, or no job fits its passport"}>
          <Plus className="size-3.5" /> Assign
        </Button>
        {a.policy.paused ? (
          <Button onClick={onResume} disabled={!!busy}>{b ? <Loader2 className="size-3.5 animate-spin" /> : <Play className="size-3.5" />} Resume</Button>
        ) : (
          <Button onClick={onPause} disabled={!!busy || a.status !== "active"} title="Stops the running task now and holds the queue">
            {b ? <Loader2 className="size-3.5 animate-spin" /> : <Pause className="size-3.5" />} Pause
          </Button>
        )}
        <Button variant="danger" onClick={onSuspend} disabled={!!busy || a.status !== "active"} title="Stop now and revoke its passport">
          <Ban className="size-3.5" /> Suspend
        </Button>
        <Button variant="ghost" onClick={onSettings} className="ml-auto" title="Approvals and budgets"><Settings2 className="size-3.5" /></Button>
      </div>
      <p className="mt-2 text-[10.5px] text-faint">
        {a.policy.require_approval ? "Sends need your approval" : "Sends go out once Send Guard clears them"} · last active {ago(m.last_active)}
      </p>
    </div>
  );
}

function Stat({ k, v, title, bad }: { k: string; v: React.ReactNode; title?: string; bad?: boolean }) {
  return (
    <div title={title}>
      <dd className={cn("text-[15px] font-[620] tabular-nums", bad && "text-contradicted")}>{v}</dd>
      <dt className="text-[10.5px] text-muted-foreground">{k}</dt>
    </div>
  );
}

function PayrollCard({ p, busy, onRun, onToggle, onEvery }: {
  p: RuntimeState["payroll"]; busy: string | null; onRun: () => void; onToggle: () => void; onEvery: (m: number) => void;
}) {
  const r = p.last_result;
  return (
    <div className={cn(cardCls, "p-3.5")}>
      <SectionHead title="Payroll run" aside={<Gauge className="size-4 text-faint" />}>
        Re-checks every sponsor live against Crustdata. An agent whose sponsor left or lost authority is frozen on the spot.
      </SectionHead>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[12px]">
        <label className="inline-flex items-center gap-1.5">
          <input type="checkbox" checked={p.enabled} onChange={onToggle} disabled={!!busy} /> Every
        </label>
        <select className={cn(inputCls, "h-7 w-auto")} value={p.every_minutes} onChange={(e) => onEvery(Number(e.target.value))}>
          {[5, 15, 30, 60, 240, 1440].map((m) => <option key={m} value={m}>{m < 60 ? `${m} min` : `${m / 60} h`}</option>)}
        </select>
        <Button onClick={onRun} disabled={!!busy || p.running} className="ml-auto">
          {busy === "payroll" || p.running ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />} Run now
        </Button>
      </div>
      <p className="mt-2 text-[11.5px] text-muted-foreground">
        {r ? <>Last: {ago(r.at)}, {r.checked} checked{r.suspended.length ? <>, <span className="text-contradicted">froze {r.suspended.join(", ")}</span></> : ", all passed"}{r.error ? ` (${r.error})` : ""}.</> : "Not run yet."}
        {p.enabled && p.next_run_at ? ` Next ${new Date(p.next_run_at).toLocaleTimeString()}.` : ""}
      </p>
    </div>
  );
}

function SchedulesCard({ schedules, kinds, busy, onToggle, onDelete }: {
  schedules: RuntimeState["schedules"]; kinds: TaskKind[]; busy: string | null; onToggle: (id: string) => void; onDelete: (id: string) => void;
}) {
  return (
    <div className={cn(cardCls, "p-3.5")}>
      <SectionHead title="Recurring work" aside={<Repeat className="size-4 text-faint" />}>Tasks that run on a schedule. Add one from Assign work.</SectionHead>
      <div className="mt-2 divide-y divide-border">
        {schedules.length ? schedules.map((s) => (
          <div key={s.schedule_id} className="flex items-center gap-2 py-2 text-[12px]">
            <input type="checkbox" checked={s.enabled} onChange={() => onToggle(s.schedule_id)} disabled={!!busy} aria-label="enabled" />
            <span className="min-w-0 flex-1">
              <span className="block truncate font-[560]">{s.agent_name}: {kinds.find((k) => k.kind === s.kind)?.label ?? s.kind}</span>
              <span className="block truncate text-[11px] text-muted-foreground">
                every {s.every_minutes} min · {s.runs} run(s){s.last_skip ? ` · skipped: ${s.last_skip}` : ""}
              </span>
            </span>
            <button onClick={() => onDelete(s.schedule_id)} className="rounded p-1 text-faint hover:bg-hover hover:text-contradicted" aria-label="Delete schedule">
              <Trash2 className="size-3.5" />
            </button>
          </div>
        )) : <p className="py-2 text-[12px] text-muted-foreground">None yet.</p>}
      </div>
    </div>
  );
}

function DecidedCard({ decided }: { decided: Approval[] }) {
  if (!decided.length) return null;
  return (
    <div className={cn(cardCls, "p-3.5")}>
      <SectionHead title="Your recent decisions" aside={<Clock className="size-4 text-faint" />} />
      <div className="mt-2 divide-y divide-border">
        {decided.slice(0, 8).map((a) => (
          <div key={a.approval_id} className="flex items-center gap-2 py-1.5 text-[11.5px]">
            <span className={cn("w-[120px] shrink-0 font-[560]", SEND_STATE[a.status]?.cls)}>{SEND_STATE[a.status]?.label ?? a.status}</span>
            <span className="min-w-0 flex-1 truncate">{a.agent_name} → {a.to.name}</span>
            {a.result?.approval_entry && (
              <a href={receiptUrl(a.result.approval_entry)} target="_blank" rel="noreferrer" title="Signed receipt" className="text-faint hover:text-foreground">
                <Receipt className="size-3.5" />
              </a>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function AssignSheet({ open, initialAgent, agents, kinds, busy, onClose, onAssign }: {
  open: boolean; initialAgent?: string; agents: LiveAgent[]; kinds: TaskKind[]; busy: string | null; onClose: () => void;
  onAssign: (b: { agent_id: string; kind: string; input: Record<string, string> }, every?: number) => void;
}) {
  const able = agents.filter((a) => a.status === "active" && a.kinds.length);
  const [agentId, setAgentId] = useState("");
  const [kind, setKind] = useState("");
  const [input, setInput] = useState<Record<string, string>>({});
  const [repeat, setRepeat] = useState(false);
  const [every, setEvery] = useState(60);
  const agent = able.find((a) => a.agent_id === agentId);
  const spec = kinds.find((k) => k.kind === kind);

  useEffect(() => {
    if (!open) return;
    const a = able.find((x) => x.agent_id === initialAgent) ?? able[0];
    setAgentId(a?.agent_id ?? "");
    const hinted = kinds.find((k) => k.agent_hint === a?.name && a?.kinds.includes(k.kind));
    setKind(hinted?.kind ?? a?.kinds[0] ?? "");
    setInput({});
    setRepeat(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialAgent]);

  const missing = spec?.fields.some((f) => f.required && !(input[f.name] ?? "").trim());
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent>
        <div className="flex-1 overflow-y-auto p-5">
          <SheetTitle className="text-[17px] font-[620]">Assign work</SheetTitle>
          <p className="mt-1 text-[12.5px] text-muted-foreground">
            The agent clocks in (passport and live sponsor check), does the job on Crustdata and Gemini, and files its work on
            the ledger. Anything it wants to send waits for you.
          </p>
          {able.length === 0 ? (
            <EmptyState title="No agent can take work">Onboard an agent or reinstate a suspended one first.</EmptyState>
          ) : (
            <div className="mt-4 space-y-3.5">
              <Field label="Agent">
                <select className={inputCls} value={agentId} onChange={(e) => {
                  setAgentId(e.target.value);
                  const a = able.find((x) => x.agent_id === e.target.value);
                  const hinted = kinds.find((k) => k.agent_hint === a?.name && a?.kinds.includes(k.kind));
                  setKind(hinted?.kind ?? a?.kinds[0] ?? "");
                }}>
                  {able.map((a) => <option key={a.agent_id} value={a.agent_id}>{a.name} ({a.role}) for {a.sponsor.name}</option>)}
                </select>
              </Field>
              <Field label="Job" hint={spec?.description}>
                <select className={inputCls} value={kind} onChange={(e) => { setKind(e.target.value); setInput({}); }}>
                  {kinds.filter((k) => agent?.kinds.includes(k.kind)).map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
                </select>
              </Field>
              {spec?.fields.map((f) => (
                <Field key={f.name} label={f.label}>
                  {f.type === "textarea" ? (
                    <textarea className={cn(inputCls, "h-28 py-2 leading-relaxed")} placeholder={f.placeholder} value={input[f.name] ?? ""}
                      onChange={(e) => setInput({ ...input, [f.name]: e.target.value })} />
                  ) : (
                    <input className={inputCls} placeholder={f.placeholder} value={input[f.name] ?? ""}
                      onChange={(e) => setInput({ ...input, [f.name]: e.target.value })} />
                  )}
                </Field>
              ))}
              <label className="flex items-center gap-2 text-[12.5px]">
                <input type="checkbox" checked={repeat} onChange={(e) => setRepeat(e.target.checked)} /> Repeat every
                <input type="number" min={1} className={cn(inputCls, "h-7 w-20")} value={every} onChange={(e) => setEvery(Number(e.target.value))} disabled={!repeat} /> minutes
              </label>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 border-t border-border p-4">
          <Button variant="primary" disabled={!agent || !spec || missing || !!busy}
            onClick={() => onAssign({ agent_id: agentId, kind, input }, repeat ? every : undefined)}>
            {busy === "assign" ? <Loader2 className="size-3.5 animate-spin" /> : repeat ? <Repeat className="size-3.5" /> : <Play className="size-3.5" />}
            {repeat ? "Schedule" : "Start"}
          </Button>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

function TaskSheet({ id, version, busy, onClose, onCancel, onRetry }: {
  id: string | null; version: number; busy: string | null; onClose: () => void; onCancel: (id: string) => void; onRetry: (id: string) => void;
}) {
  const [t, setT] = useState<Task | null>(null);
  useEffect(() => {
    if (!id) return setT(null);
    runtime.task(id).then(setT).catch(() => {});
  }, [id, version]);
  const out = t?.output ?? {};
  const steps = useMemo(() => t?.steps ?? [], [t]);
  return (
    <Sheet open={!!id} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="sm:max-w-2xl">
        <div className="flex-1 overflow-y-auto p-5">
          {!t ? <Loader2 className="size-4 animate-spin text-faint" /> : (
            <>
              <p className={cn("text-[11.5px] font-[590] capitalize", TASK_STATUS[t.status])}>{t.status}{t.waiting_on ? ` · ${t.waiting_on}` : ""}</p>
              <SheetTitle className="mt-0.5 pr-8 text-[17px] font-[620]">{t.title}</SheetTitle>
              <p className="mt-1 text-[12px] text-muted-foreground">
                {t.agent_name} · assigned by {t.assigned_by} {ago(t.created_at)}
                {t.seconds ? ` · took ${secs(t.seconds)}` : ""} · {t.usage.crustdata} Crustdata, {t.usage.llm} Gemini calls
              </p>
              {(t.result || t.error) && (
                <p className={cn("mt-3 rounded-md border px-3 py-2 text-[12.5px]", t.error ? "border-contradicted/40 bg-contradicted/10" : "border-verified/40 bg-verified/10")}>
                  {t.result || t.error}
                </p>
              )}
              {t.status === "running" && (
                <div className="mt-3">
                  <div className="h-1.5 overflow-hidden rounded-full bg-elevated">
                    <div className="h-full bg-sky transition-all" style={{ width: t.progress.total ? `${(100 * t.progress.done) / t.progress.total}%` : "30%" }} />
                  </div>
                  <p className="mt-1 text-[11px] text-muted-foreground">{t.progress.label} {t.progress.total ? `${t.progress.done}/${t.progress.total}` : ""}</p>
                </div>
              )}

              {out.clock_in && out.clock_in.decision === "block" && (
                <Block title="Refused at clock-in">
                  {out.clock_in.failed.map((c) => <p key={c.name} className="text-[12px]"><b>{checkLabel(c.name)}:</b> {c.detail}</p>)}
                </Block>
              )}
              {out.shortlist?.length ? (
                <Block title={`Shortlist (${out.shortlist.length})`}>
                  {out.shortlist.map((c, i) => (
                    <div key={i} className="flex items-baseline gap-2 py-1 text-[12.5px]">
                      <span className="w-8 shrink-0 font-mono tabular-nums text-muted-foreground">{c.score}</span>
                      <span className="min-w-0 flex-1 truncate">
                        {c.profile_url ? <a href={c.profile_url} target="_blank" rel="noreferrer" className="font-[560] hover:underline">{c.name}</a> : c.name}
                        <span className="text-muted-foreground"> · {c.title} at {c.company}</span>
                      </span>
                    </div>
                  ))}
                </Block>
              ) : null}
              {out.sends?.length ? (
                <Block title={`Messages (${out.sends.length})`}>
                  {out.sends.map((s, i) => (
                    <details key={i} className="border-b border-border py-1.5 last:border-0">
                      <summary className="flex cursor-pointer items-center gap-2 text-[12.5px]">
                        <span className={cn("w-[150px] shrink-0 text-[11.5px] font-[560]", SEND_STATE[s.state]?.cls)}>{SEND_STATE[s.state]?.label ?? s.state}</span>
                        <span className="truncate">{s.to.name} ({s.to.company})</span>
                      </summary>
                      <pre className="mt-1.5 whitespace-pre-wrap rounded bg-elevated px-2.5 py-2 font-sans text-[12px]">{s.body}</pre>
                      <VerdictList verdict={{ subject: "", decision: s.decision, checks: s.checks }} className="mt-1.5" />
                    </details>
                  ))}
                </Block>
              ) : null}
              {out.findings?.length ? (
                <Block title={`Resume checks (${out.findings.length})`}>
                  {out.findings.map((f, i) => (
                    <div key={i} className="py-1.5 text-[12.5px]">
                      <p><b>{f.candidate}</b> · {f.verified}/{f.total} verified{f.contradicted.length ? <span className="text-contradicted"> · {f.contradicted.length} false</span> : ""}</p>
                      {f.contradicted.map((c, j) => <p key={j} className="ml-3 text-[12px] text-muted-foreground">✗ {c.claim}: {c.evidence}</p>)}
                    </div>
                  ))}
                </Block>
              ) : null}
              {out.artifacts?.map((a, i) => (
                <Block key={i} title={a.title}>
                  <pre className="max-h-80 overflow-auto whitespace-pre-wrap font-sans text-[12px] leading-relaxed">{a.content}</pre>
                </Block>
              ))}
              {t.ledger.length > 0 && (
                <Block title="On the ledger">
                  <div className="flex flex-wrap gap-1.5">
                    {t.ledger.map((h) => (
                      <a key={h} href={receiptUrl(h)} target="_blank" rel="noreferrer"
                        className="inline-flex items-center gap-1 rounded border border-border-strong px-1.5 py-0.5 font-mono text-[10.5px] text-muted-foreground hover:text-foreground"
                        title="Open a signed receipt anyone can verify against the hash chain">
                        <Receipt className="size-3" />{h.slice(0, 10)}<ExternalLink className="size-2.5" />
                      </a>
                    ))}
                  </div>
                </Block>
              )}
              <Block title={`Steps (${steps.length})`}>
                <div className="max-h-96 overflow-auto font-mono text-[11px] leading-[1.6]">
                  {steps.map((s, i) => (
                    <div key={i} className={cn("whitespace-pre-wrap", s.kind === "control" && "text-contradicted", s.kind === "system" && "text-muted-foreground")}>
                      <span className="text-faint">{new Date(s.ts).toLocaleTimeString()} </span>{s.text}
                    </div>
                  ))}
                </div>
              </Block>
            </>
          )}
        </div>
        {t && (
          <div className="flex items-center gap-2 border-t border-border p-4">
            {(t.status === "running" || t.status === "queued") && (
              <Button variant="danger" onClick={() => onCancel(t.task_id)} disabled={!!busy}><X className="size-3.5" /> Stop task</Button>
            )}
            {["failed", "cancelled", "refused", "done"].includes(t.status) && (
              <Button onClick={() => onRetry(t.task_id)} disabled={!!busy}><RefreshCw className="size-3.5" /> Run again</Button>
            )}
            <span className="ml-auto inline-flex items-center gap-1 text-[11px] text-faint"><ActivityIcon className="size-3" /> live</span>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-5">
      <h4 className="mb-1.5 text-[12px] font-[590] text-muted-foreground">{title}</h4>
      <div className="rounded-lg border border-border bg-panel px-3 py-2">{children}</div>
    </section>
  );
}

function PolicySheet({ agent, busy, onClose, onSave }: {
  agent: LiveAgent | null; busy: string | null; onClose: () => void;
  onSave: (b: { require_approval: boolean; budget: Record<string, number> }) => void;
}) {
  const [req, setReq] = useState(true);
  const [budget, setBudget] = useState<Record<string, number>>({});
  useEffect(() => {
    if (agent) {
      setReq(agent.policy.require_approval);
      setBudget({ ...agent.policy.budget });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agent?.agent_id]);
  const LABELS: Record<string, string> = {
    tasks_per_day: "Tasks per day", sends_per_day: "Messages sent per day",
    crustdata_calls_per_day: "Crustdata calls per day", llm_calls_per_day: "Gemini calls per day",
  };
  return (
    <Sheet open={!!agent} onOpenChange={(o) => !o && onClose()}>
      <SheetContent>
        <div className="flex-1 overflow-y-auto p-5">
          <SheetTitle className="text-[17px] font-[620]">{agent?.name}: rules</SheetTitle>
          <p className="mt-1 text-[12.5px] text-muted-foreground">
            Budgets reset daily. When one runs out the agent stops: queued tasks wait, and a task that goes over is stopped mid-way.
          </p>
          <label className="mt-4 flex items-start gap-2 text-[13px]">
            <input type="checkbox" className="mt-1" checked={req} onChange={(e) => setReq(e.target.checked)} />
            <span><b>Every message needs my approval</b><br />
              <span className="text-[12px] text-muted-foreground">Off: drafts Send Guard clears go straight to the outbox.</span></span>
          </label>
          <div className="mt-4 grid grid-cols-2 gap-3">
            {Object.keys(LABELS).map((k) => (
              <Field key={k} label={LABELS[k]}>
                <input type="number" min={0} className={inputCls} value={budget[k] ?? 0} onChange={(e) => setBudget({ ...budget, [k]: Number(e.target.value) })} />
              </Field>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2 border-t border-border p-4">
          <Button variant="primary" disabled={!!busy} onClick={() => onSave({ require_approval: req, budget })}>Save rules</Button>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
