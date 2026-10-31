"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft, BadgeCheck, Ban, ClipboardCheck, FileClock, IdCard, Link2, Loader2, Plus, RefreshCw, RotateCcw, ShieldAlert,
  ShieldCheck, SlidersHorizontal, UserMinus, X,
} from "lucide-react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import {
  ApiError, SCOPE_INFO, api, snapshot, type Agent, type LedgerView, type ReviewDecision, type Role, type Scenario, type Scope,
  type Sponsor, type Verdict,
} from "./api";
import {
  AgentMark, Button, DecisionBadge, Field, ScopeChip, ScopeToggle, SourceChip, StatusPill, VerdictList, ago, checkLabel, day,
  inputCls,
} from "./parts";

type Mode = "loading" | "live" | "demo";
type Tab = "passport" | "permissions" | "reviews" | "ledger";
type Flash = { tone: "ok" | "bad" | "info"; title: string; body?: string; verdict?: Verdict } | null;

const ALL_SCOPES = Object.keys(SCOPE_INFO) as Scope[];

export default function Console() {
  const [mode, setMode] = useState<Mode>("loading");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [chain, setChain] = useState<Pick<LedgerView, "chain_ok" | "first_bad_seq"> & { count: number }>();
  const [selected, setSelected] = useState<string>();
  const [tab, setTab] = useState<Tab>("passport");
  const [busy, setBusy] = useState<string | null>(null);
  const [flash, setFlash] = useState<Flash>(null);
  const [payroll, setPayroll] = useState<{ at: string; verdicts: Verdict[]; suspended: string[] } | null>(null);
  const [onboarding, setOnboarding] = useState(false);

  const refresh = useCallback(async () => {
    const [list, l] = await Promise.all([api.agents(), api.ledger()]);
    setAgents(list);
    setChain({ chain_ok: l.chain_ok, first_bad_seq: l.first_bad_seq, count: l.entries.length });
    return list;
  }, []);

  useEffect(() => {
    const forceDemo = new URLSearchParams(window.location.search).get("mode") === "demo";
    const showSnapshot = () => {
      setMode("demo");
      setAgents(snapshot.agents);
      setRoles(snapshot.roles);
      setScenarios(snapshot.scenarios);
      setChain({ chain_ok: snapshot.ledger.chain_ok, first_bad_seq: snapshot.ledger.first_bad_seq, count: snapshot.ledger.entries.length });
    };
    if (forceDemo) return showSnapshot();
    Promise.all([refresh(), api.roles(), api.scenarios().catch(() => [])])
      .then(([, r, s]) => {
        setRoles(r.roles);
        setScenarios(s);
        setMode("live");
      })
      .catch(showSnapshot);
  }, [refresh]);

  useEffect(() => {
    if (!selected && agents.length) setSelected(agents[0].agent_id);
  }, [agents, selected]);

  const live = mode === "live";
  const cur = agents.find((a) => a.agent_id === selected);
  const counts = useMemo(
    () => agents.reduce((c, a) => ({ ...c, [a.status]: (c[a.status] ?? 0) + 1 }), {} as Record<string, number>),
    [agents],
  );

  /** Runs a backend action, refreshes the list, and turns errors (including scope denials) into a flash. */
  const act = async <T,>(key: string, fn: () => Promise<T>, ok?: (r: T) => Flash) => {
    if (!live) {
      setFlash({ tone: "info", title: "This is a recorded snapshot", body: "Start the backend to onboard, check or change AI employees." });
      return;
    }
    setBusy(key);
    setFlash(null);
    try {
      const r = await fn();
      await refresh();
      if (ok) setFlash(ok(r));
      return r;
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(String(e), 0);
      setFlash({ tone: "bad", title: err.status === 403 ? "Refused" : "Couldn't do that", body: err.message, verdict: err.verdict });
    } finally {
      setBusy(null);
    }
  };

  const runPayroll = async () => {
    if (!live) {
      const suspended = snapshot.agents.filter((a) => a.suspended_by === "payroll").map((a) => a.agent_id);
      setPayroll({ at: new Date().toISOString(), verdicts: snapshot.payroll, suspended });
      return;
    }
    const before = new Map(agents.map((a) => [a.agent_id, a.status]));
    setBusy("payroll");
    setFlash(null);
    try {
      const verdicts = await api.payroll();
      const list = await refresh();
      const suspended = list.filter((a) => a.status === "suspended" && before.get(a.agent_id) === "active").map((a) => a.agent_id);
      setPayroll({ at: new Date().toISOString(), verdicts, suspended });
    } catch (e) {
      setFlash({ tone: "bad", title: "Payroll check failed", body: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 h-14 border-b-2 border-ink bg-background/95 backdrop-blur">
        <div className="mx-auto flex h-full max-w-[1680px] items-center justify-between gap-3 px-4">
          <div className="flex min-w-0 items-center gap-2">
            <Link href="/" className="press flex h-8 items-center gap-1.5 rounded-lg border-2 border-ink bg-panel px-2.5 text-[12.5px] font-bold shadow-brut-sm">
              <ArrowLeft className="size-3.5" strokeWidth={2.5} /> Sourced
            </Link>
            <span className="flex items-center gap-2.5 pl-1">
              <span className="grid size-8 -rotate-6 place-items-center rounded-lg border-2 border-ink bg-lavender shadow-brut-sm">
                <IdCard className="size-4 text-[#111]" strokeWidth={2.5} />
              </span>
              <span className="font-display truncate text-[22px] font-extrabold tracking-[-0.03em]">AI employees</span>
            </span>
            <span className="hidden rotate-2 rounded-md border-2 border-ink bg-yellow px-1.5 text-[10.5px] font-extrabold uppercase tracking-wider text-on-color sm:inline">Countersign</span>
          </div>
          <div className="flex items-center gap-2">
            {chain && <ChainPill {...chain} />}
            <span
              className={cn(
                "inline-flex h-7 items-center gap-1.5 rounded-full border-2 border-ink px-2.5 font-mono text-[10.5px] font-bold uppercase text-on-color",
                live ? "bg-lime" : "bg-yellow",
              )}
              title={live ? "Connected to the backend" : "Backend unreachable: showing a recorded snapshot"}
            >
              <span className={cn("size-2 rounded-full border border-[#111]", live ? "animate-pulse bg-[#111]" : "bg-white")} />
              {mode === "loading" ? "connecting" : live ? "live" : "snapshot"}
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-[1680px] grid-cols-[minmax(0,1fr)] gap-6 px-4 py-6 lg:grid-cols-[minmax(360px,460px)_minmax(0,1fr)]">
        <section className="min-w-0 lg:sticky lg:top-[80px] lg:max-h-[calc(100vh-100px)] lg:self-start lg:overflow-y-auto lg:pb-3 lg:pl-3 lg:pr-2">
          <div className="pb-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h1 className="font-display text-[34px] font-extrabold leading-[0.95] tracking-[-0.03em]">
                  Your AI <span className="relative inline-block -rotate-1 rounded-lg border-2 border-ink bg-yellow px-1.5 text-on-color shadow-brut-sm">workforce</span>
                </h1>
                <p className="mt-3 text-[13px] font-medium leading-relaxed text-muted-foreground">
                  Every AI employee acts for a real person. We check that person against Crustdata before it&apos;s trusted.
                </p>
              </div>
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Button variant="primary" onClick={() => (live ? setOnboarding(true) : act("onboard", async () => null))}>
                <Plus className="size-3.5" /> Onboard
              </Button>
              <Button onClick={runPayroll} disabled={busy === "payroll" || !agents.length} title="Re-check every sponsor against Crustdata">
                {busy === "payroll" ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
                Run payroll check
              </Button>
              <span className="ml-auto flex items-center gap-1.5 font-mono text-[11px] font-bold tabular-nums">
                <span className="rounded-full border-2 border-ink bg-lime px-1.5 text-on-color" title="Active">{counts.active ?? 0}</span>
                <span className="rounded-full border-2 border-ink bg-coral px-1.5 text-on-color" title="Suspended">{counts.suspended ?? 0}</span>
                <span className="rounded-full border-2 border-ink bg-elevated px-1.5" title="Offboarded">{counts.offboarded ?? 0}</span>
              </span>
            </div>
          </div>

          {payroll && <PayrollBanner run={payroll} agents={agents} onClose={() => setPayroll(null)} onPick={setSelected} />}

          <ul className="flex flex-col gap-4 pt-2">
            {mode === "loading" && <li className="px-4 py-10 text-center text-[13px] font-semibold text-muted-foreground">Loading…</li>}
            {mode !== "loading" && !agents.length && (
              <li className="rounded-xl border-2 border-dashed border-ink bg-panel px-4 py-10 text-center">
                <p className="font-display text-[18px] font-extrabold">No AI employees yet.</p>
                <p className="mt-1 text-[12px] text-faint">Onboard Sourced, the hiring agent, as employee #1.</p>
              </li>
            )}
            {agents.map((a, i) => (
              <AgentRow key={a.agent_id} agent={a} i={i} selected={a.agent_id === selected} onClick={() => setSelected(a.agent_id)} />
            ))}
          </ul>
        </section>

        <section className="min-w-0 self-start overflow-hidden rounded-xl border-2 border-ink bg-panel shadow-brut-lg">
          {flash && <FlashBar flash={flash} onClose={() => setFlash(null)} />}
          {cur ? (
            <AgentDetail
              key={cur.agent_id}
              agent={cur}
              role={roles.find((r) => r.title === cur.role)}
              tab={tab}
              setTab={setTab}
              busy={busy}
              live={live}
              act={act}
            />
          ) : (
            <div className="grid min-h-[50vh] place-items-center p-8 text-center text-[13px] text-faint">
              {mode === "loading" ? "" : "Select an AI employee."}
            </div>
          )}
        </section>
      </main>

      <Sheet open={onboarding} onOpenChange={setOnboarding}>
        <SheetContent className="border-l-2 border-ink bg-panel">
          <SheetTitle className="sr-only">Onboard an AI employee</SheetTitle>
          <OnboardForm
            roles={roles}
            scenarios={scenarios}
            first={!agents.length}
            onDone={async (agentId) => {
              await refresh();
              setSelected(agentId);
              setTab("passport");
            }}
          />
        </SheetContent>
      </Sheet>
    </div>
  );
}

// ---- list ------------------------------------------------------------------------------------

function AgentRow({ agent: a, i, selected, onClick }: { agent: Agent; i: number; selected: boolean; onClick: () => void }) {
  const s = a.passport.sponsor;
  return (
    <li style={{ animationDelay: `${Math.min(i, 8) * 50}ms` }} className="animate-rise">
      <button
        onClick={onClick}
        className={cn(
          "press relative grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-3 rounded-xl border-2 border-ink p-3 text-left shadow-brut",
          selected ? "bg-yellow text-on-color" : "bg-panel",
          a.status === "offboarded" && "opacity-55",
        )}
      >
        <span
          className={cn(
            "font-display absolute -left-2.5 -top-2.5 grid size-7 place-items-center rounded-full border-2 border-ink text-[12px] font-extrabold shadow-brut-sm",
            a.employee_no === 1 ? "bg-lime text-on-color" : "bg-panel text-foreground",
          )}
          title={`Employee #${a.employee_no}`}
        >
          {a.employee_no}
        </span>
        <AgentMark agent={a} />
        <span className="min-w-0">
          <span className="font-display block truncate text-[18px] font-extrabold tracking-tight">{a.name}</span>
          <span className={cn("block truncate text-[12.5px] font-medium", selected ? "text-on-color/80" : "text-muted-foreground")}>
            {a.role} · for <span className="font-bold">{s.name}</span>, {s.title ? `${s.title}, ` : ""}{s.company}
          </span>
          {a.status !== "active" && a.reason ? (
            <span className="mt-1.5 line-clamp-2 rounded-md border-[1.5px] border-ink bg-coral/80 px-1.5 py-0.5 text-[11.5px] font-bold text-on-color">{a.reason}</span>
          ) : (
            <span className="mt-2 flex flex-wrap gap-1">{a.passport.scopes.map((sc) => <ScopeChip key={sc} scope={sc} />)}</span>
          )}
        </span>
        <span className="flex flex-col items-end gap-2">
          <StatusPill status={a.status} />
          <span className={cn("font-mono text-[10.5px] font-bold", selected ? "text-on-color/70" : "text-muted-foreground")}>checked {ago(a.last_checked)}</span>
        </span>
      </button>
    </li>
  );
}

function ChainPill({ chain_ok, first_bad_seq, count }: { chain_ok: boolean; first_bad_seq: number | null; count: number }) {
  return (
    <span
      className={cn(
        "hidden h-7 items-center gap-1.5 rounded-full border-2 border-ink px-2.5 text-[11px] font-bold sm:inline-flex",
        chain_ok ? "bg-panel" : "bg-coral text-on-color",
      )}
      title="Hash-chained ledger of every passport, check and decision"
    >
      <Link2 className="size-3.5" strokeWidth={2.5} />
      {chain_ok ? `Ledger intact · ${count}` : `Chain broken at #${first_bad_seq}`}
    </span>
  );
}

function PayrollBanner({
  run, agents, onClose, onPick,
}: { run: { at: string; verdicts: Verdict[]; suspended: string[] }; agents: Agent[]; onClose: () => void; onPick: (id: string) => void }) {
  const blocked = run.verdicts.filter((v) => v.decision === "block");
  const byId = new Map(agents.map((a) => [a.agent_id, a]));
  return (
    <div className="mb-4 overflow-hidden rounded-xl border-2 border-ink bg-panel shadow-brut animate-pop">
      <div className="flex items-center justify-between gap-2 border-b-2 border-ink bg-lavender px-3 py-2 text-on-color">
        <span className="flex flex-wrap items-center gap-x-2 text-[13px] font-extrabold">
          <ClipboardCheck className="size-4" strokeWidth={2.5} /> Payroll check
          <span className="font-semibold opacity-80">
            {run.verdicts.length} checked · {run.verdicts.length - blocked.length} cleared · {blocked.length} blocked
          </span>
        </span>
        <button onClick={onClose} className="rounded p-0.5 hover:bg-white/40" aria-label="Dismiss">
          <X className="size-4" strokeWidth={2.5} />
        </button>
      </div>
      <ul className="divide-y-2 divide-dashed divide-hairline">
        {run.verdicts.map((v) => {
          const a = byId.get(v.subject);
          const fail = v.checks.find((c) => c.status !== "pass" && c.name !== "not_revoked") ?? v.checks.find((c) => c.status !== "pass");
          return (
            <li key={v.subject}>
              <button onClick={() => a && onPick(a.agent_id)} className="flex w-full items-start gap-2.5 px-3 py-2.5 text-left hover:bg-hover">
                <DecisionBadge decision={v.decision} />
                <span className="min-w-0 flex-1">
                  <span className="text-[13px] font-bold">{a?.name ?? v.subject}</span>
                  {run.suspended.includes(v.subject) && <span className="ml-2 rounded border-[1.5px] border-ink bg-coral px-1 text-[10.5px] font-extrabold uppercase text-on-color">suspended now</span>}
                  {fail && <span className="block truncate text-[12px] font-medium text-muted-foreground">{checkLabel(fail.name)}: {fail.detail}</span>}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function FlashBar({ flash, onClose }: { flash: NonNullable<Flash>; onClose: () => void }) {
  return (
    <div
      className={cn(
        "border-b-2 border-ink px-4 py-3 text-on-color animate-fade sm:px-6",
        flash.tone === "bad" && "bg-coral",
        flash.tone === "ok" && "bg-lime",
        flash.tone === "info" && "bg-yellow",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-[13px]">
          <span className="font-extrabold">{flash.title}.</span> <span className="font-medium">{flash.body}</span>
        </p>
        <button onClick={onClose} className="rounded p-0.5 hover:bg-white/40" aria-label="Dismiss">
          <X className="size-4" strokeWidth={2.5} />
        </button>
      </div>
      {flash.verdict && <VerdictList verdict={flash.verdict} className="mt-2 rounded-lg border-2 border-ink bg-panel px-3 text-foreground" />}
    </div>
  );
}

// ---- detail ----------------------------------------------------------------------------------

type Act = <T>(key: string, fn: () => Promise<T>, ok?: (r: T) => Flash) => Promise<T | undefined>;

function AgentDetail({
  agent: a, role, tab, setTab, busy, live, act,
}: { agent: Agent; role?: Role; tab: Tab; setTab: (t: Tab) => void; busy: string | null; live: boolean; act: Act }) {
  const [confirm, setConfirm] = useState<"suspend" | "offboard" | null>(null);
  const [reason, setReason] = useState("");
  const gone = a.status === "offboarded";

  const recheck = () =>
    act("recheck", () => api.recheck(a.agent_id), (r) =>
      r.verdict.decision === "allow"
        ? { tone: "ok", title: "All checks passed", body: `${a.passport.sponsor.name} still vouches for ${a.name}.` }
        : { tone: "bad", title: "Check failed", body: r.agent.status === "suspended" ? `${a.name} is suspended.` : undefined, verdict: r.verdict },
    );
  const reinstate = () =>
    act("reinstate", () => api.reinstate(a.agent_id), (r) =>
      r.agent.status === "active"
        ? { tone: "ok", title: "Reinstated", body: "A fresh check passed, so the passport is live again." }
        : { tone: "bad", title: "Still suspended", body: "The sponsor check still fails.", verdict: r.verdict },
    );
  const doConfirm = async () => {
    const kind = confirm;
    if (!kind) return;
    await act(kind, () => (kind === "suspend" ? api.suspend(a.agent_id, reason) : api.offboard(a.agent_id, reason)), () => ({
      tone: "info",
      title: kind === "suspend" ? "Suspended" : "Offboarded",
      body: "The passport is revoked on the ledger, so any agent or inbox checking it will refuse it.",
    }));
    setConfirm(null);
    setReason("");
  };

  return (
    <div className="px-4 pb-10 pt-5 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <AgentMark agent={a} size="lg" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-display truncate text-[30px] font-extrabold leading-none tracking-[-0.03em]">{a.name}</h2>
              <StatusPill status={a.status} />
            </div>
            <p className="mt-1 text-[13px] font-medium text-muted-foreground">
              {a.role} · employee #{a.employee_no} · onboarded {day(a.onboarded_at)}
            </p>
          </div>
        </div>
        {!gone && (
          <div className="flex flex-wrap items-center gap-1.5">
            <Button onClick={recheck} disabled={!!busy}>
              {busy === "recheck" ? <Loader2 className="size-3.5 animate-spin" /> : <ShieldCheck className="size-3.5" />} Re-check sponsor
            </Button>
            {a.status === "suspended" ? (
              <Button onClick={reinstate} disabled={!!busy}>
                {busy === "reinstate" ? <Loader2 className="size-3.5 animate-spin" /> : <RotateCcw className="size-3.5" />} Reinstate
              </Button>
            ) : (
              <Button onClick={() => setConfirm("suspend")} disabled={!!busy}>
                <Ban className="size-3.5" /> Suspend
              </Button>
            )}
            <Button variant="danger" onClick={() => setConfirm("offboard")} disabled={!!busy}>
              <UserMinus className="size-3.5" /> Offboard
            </Button>
          </div>
        )}
      </div>

      {a.status !== "active" && a.reason && (
        <div className={cn("mt-5 flex items-start gap-2.5 rounded-xl border-2 border-ink px-3 py-2.5 shadow-brut-sm", a.status === "suspended" ? "bg-coral text-on-color" : "bg-elevated")}>
          <ShieldAlert className="mt-0.5 size-4 shrink-0" strokeWidth={2.5} />
          <p className="text-[13.5px] font-medium">
            <span className="font-extrabold">{a.status === "suspended" ? `Suspended${a.suspended_by ? ` by ${a.suspended_by}` : ""}.` : "Offboarded."}</span>{" "}
            {a.reason}
          </p>
        </div>
      )}

      {confirm && (
        <div className="mt-5 rounded-xl border-2 border-ink bg-elevated p-3 shadow-brut-sm animate-pop">
          <p className="text-[13.5px] font-bold">
            {confirm === "suspend" ? `Suspend ${a.name}?` : `Offboard ${a.name}? This can't be undone.`}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (goes on the ledger)" className={cn(inputCls, "min-w-[240px] flex-1")} />
            <Button variant={confirm === "offboard" ? "danger" : "primary"} onClick={doConfirm} disabled={!!busy}>
              {confirm === "suspend" ? "Suspend" : "Offboard"}
            </Button>
            <Button variant="ghost" onClick={() => setConfirm(null)}>Cancel</Button>
          </div>
        </div>
      )}

      <nav className="mt-6 flex flex-wrap gap-2" role="tablist">
        {([
          ["passport", "Passport", IdCard],
          ["permissions", "Permissions", SlidersHorizontal],
          ["reviews", "Reviews", BadgeCheck],
          ["ledger", "Ledger", FileClock],
        ] as const).map(([k, label, I]) => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={cn(
              "press inline-flex h-8 items-center gap-1.5 rounded-lg border-2 border-ink px-3 text-[12.5px] font-bold shadow-brut-sm",
              tab === k ? "bg-ink text-background" : "bg-panel",
            )}
          >
            <I className="size-3.5" strokeWidth={2.5} /> {label}
            {k === "reviews" && a.reviews.length > 0 && <span className="font-mono text-[10.5px] opacity-70">{a.reviews.length}</span>}
          </button>
        ))}
      </nav>

      <div className="mt-6">
        {tab === "passport" && <PassportTab agent={a} />}
        {tab === "permissions" && <PermissionsTab agent={a} role={role} busy={busy} act={act} />}
        {tab === "reviews" && <ReviewsTab agent={a} busy={busy} act={act} />}
        {tab === "ledger" && <LedgerTab agent={a} live={live} />}
      </div>
    </div>
  );
}

function PassportTab({ agent: a }: { agent: Agent }) {
  const p = a.passport;
  const s = p.sponsor;
  const mrz = `P<CSN<${p.agent_name}<<${s.company}<<${p.agent_id}`.toUpperCase().replace(/[^A-Z0-9<]/g, "<").padEnd(60, "<").slice(0, 60);
  return (
    <div className="grid gap-6 2xl:grid-cols-[minmax(0,520px)_minmax(0,1fr)]">
      <div
        className={cn(
          "relative overflow-hidden rounded-2xl border-2 border-ink bg-panel shadow-brut-lg",
        )}
      >
        <div className="flex items-center justify-between border-b-2 border-ink bg-yellow px-5 py-2 text-on-color">
          <span className="font-mono text-[10.5px] font-extrabold tracking-[0.18em]">COUNTERSIGN · AGENT PASSPORT</span>
          <span className="font-mono text-[10.5px] font-bold">#{String(a.employee_no).padStart(3, "0")}</span>
        </div>
        <div className="p-5">
        <div className="relative flex items-center gap-3">
          <AgentMark agent={a} size="lg" />
          <div>
            <div className="font-display text-[26px] font-extrabold leading-tight tracking-[-0.03em]">{p.agent_name}</div>
            <div className="text-[13px] font-medium text-muted-foreground">{p.role}</div>
          </div>
        </div>
        <dl className="relative mt-5 grid grid-cols-2 gap-x-4 gap-y-3 text-[12.5px]">
          <PField k="Acts for" v={s.name} />
          <PField k="Sponsor title" v={s.title ?? "–"} />
          <PField k="Company" v={s.company} />
          <PField k="Domain" v={s.company_domain ?? "–"} mono />
          <PField k="Issued" v={day(p.issued_at)} />
          <PField k="Expires" v={day(p.expires_at)} />
          <div className="col-span-2">
            <dt className="text-[10.5px] font-extrabold uppercase tracking-wider text-muted-foreground">Scopes</dt>
            <dd className="mt-1 flex flex-wrap gap-1">{p.scopes.map((sc) => <ScopeChip key={sc} scope={sc} />)}</dd>
          </div>
          <PField k="Agent key" v={`ed25519:${p.public_key.slice(0, 16)}…`} mono />
          <PField k="Issuer key" v={p.issuer_key_id || "–"} mono />
        </dl>
        <div className="relative mt-5 border-t-2 border-dashed border-ink pt-3 font-mono text-[10.5px] font-bold leading-relaxed tracking-[0.12em] text-muted-foreground">
          <div className="truncate">{mrz}</div>
          <div className="truncate">SIG {p.issuer_signature?.slice(0, 48)}</div>
        </div>
        </div>
        {a.status !== "active" && (
          <span
            className={cn(
              "font-display pointer-events-none absolute right-5 top-20 rotate-[-12deg] rounded-lg border-[3px] border-ink px-3 py-1 text-[22px] font-extrabold tracking-[0.12em] text-on-color shadow-brut animate-pop",
              a.status === "suspended" ? "bg-coral" : "bg-elevated",
            )}
          >
            {a.status === "suspended" ? "REVOKED" : "OFFBOARDED"}
          </span>
        )}
      </div>

      <div>
        <div className="flex items-baseline justify-between gap-2">
          <h3 className="font-display text-[19px] font-extrabold tracking-tight">Last sponsor check</h3>
          <span className="font-mono text-[11px] font-bold text-muted-foreground">{a.last_checked ? `${ago(a.last_checked)} · ${day(a.last_checked)}` : "not checked yet"}</span>
        </div>
        {a.last_verdict ? (
          <>
            <div className="mt-2 flex items-center gap-2 text-[12.5px] font-semibold text-muted-foreground">
              <DecisionBadge decision={a.last_verdict.decision} />
              {a.last_verdict.checks.filter((c) => c.status === "pass").length}/{a.last_verdict.checks.length} checks passed, each cited
            </div>
            <VerdictList verdict={a.last_verdict} className="mt-2" />
          </>
        ) : (
          <p className="mt-2 text-[12.5px] text-faint">Run a check to see what Crustdata says about the sponsor.</p>
        )}
      </div>
    </div>
  );
}

function PField({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-[10.5px] font-extrabold uppercase tracking-wider text-muted-foreground">{k}</dt>
      <dd className={cn("mt-0.5 truncate", mono ? "font-mono text-[11.5px] font-bold" : "font-bold")} title={v}>{v}</dd>
    </div>
  );
}

function PermissionsTab({ agent: a, role, busy, act }: { agent: Agent; role?: Role; busy: string | null; act: Act }) {
  const [scopes, setScopes] = useState<Scope[]>(a.passport.scopes);
  const ceiling = role?.ceiling ?? ALL_SCOPES;
  const dirty = scopes.length !== a.passport.scopes.length || scopes.some((s) => !a.passport.scopes.includes(s));
  const widening = scopes.some((s) => !a.passport.scopes.includes(s));
  const save = () =>
    act("scopes", () => api.scopes(a.agent_id, scopes), (r) => ({
      tone: "ok",
      title: "Passport re-issued",
      body: r.verdict ? `${a.passport.sponsor.name}'s authority was checked live for the new scopes.` : "Narrowing needs no sponsor check.",
      verdict: r.verdict ?? undefined,
    })).then((r) => {
      if (!r) setScopes(a.passport.scopes);
    });
  return (
    <div className="max-w-[640px]">
      <p className="text-[13px] font-medium leading-relaxed text-muted-foreground">
        Two gates decide what {a.name} may do. The <span className="rounded border-[1.5px] border-ink bg-sky px-1 font-bold text-on-color">role</span> sets a ceiling ({role?.title ?? a.role}). The{" "}
        <span className="rounded border-[1.5px] border-ink bg-pink px-1 font-bold text-on-color">sponsor</span> must hold the authority themselves, checked live against their current title in Crustdata.
      </p>
      <div className="mt-4 grid gap-2">
        {ALL_SCOPES.map((sc) => (
          <ScopeToggle
            key={sc}
            scope={sc}
            checked={scopes.includes(sc)}
            locked={!ceiling.includes(sc)}
            disabled={a.status === "offboarded"}
            onChange={(on) => setScopes((cur) => (on ? [...cur, sc] : cur.filter((x) => x !== sc)))}
          />
        ))}
      </div>
      <div className="mt-4 flex items-center gap-2">
        <Button variant="primary" onClick={save} disabled={!dirty || !scopes.length || !!busy}>
          {busy === "scopes" && <Loader2 className="size-3.5 animate-spin" />}
          {widening ? "Check sponsor and grant" : "Save"}
        </Button>
        {dirty && <Button variant="ghost" onClick={() => setScopes(a.passport.scopes)}>Reset</Button>}
        <span className="text-[12px] font-medium text-muted-foreground">Changing scopes re-issues the passport.</span>
      </div>
    </div>
  );
}

function ReviewsTab({ agent: a, busy, act }: { agent: Agent; busy: string | null; act: Act }) {
  const [card, setCard] = useState(a.scorecard);
  const [decision, setDecision] = useState<ReviewDecision>("keep");
  const [notes, setNotes] = useState("");
  const [reviewer, setReviewer] = useState(a.passport.sponsor.name);
  const [keep, setKeep] = useState<Scope[]>(a.passport.scopes.slice(0, -1));

  useEffect(() => {
    if (!a.scorecard) api.agent(a.agent_id).then((r) => setCard(r.scorecard)).catch(() => {});
  }, [a.agent_id, a.scorecard, a.reviews.length]);

  const submit = async () => {
    const r = await act("review", () => api.review(a.agent_id, { reviewer, decision, notes, scopes: decision === "restrict" ? keep : undefined }), () => ({
      tone: "ok",
      title: "Review recorded",
      body: decision === "keep" ? "No changes." : decision === "restrict" ? "Scopes narrowed and passport re-issued." : `${a.name} is offboarded.`,
    }));
    if (r) setNotes("");
  };

  return (
    <div className="grid gap-8 2xl:grid-cols-[minmax(0,1fr)_minmax(0,420px)]">
      <div>
        <h3 className="font-display text-[19px] font-extrabold tracking-tight">Scorecard</h3>
        <p className="text-[12.5px] font-medium text-muted-foreground">Read from the ledger: what the Send Guard let through and what it stopped.</p>
        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Tile k="Messages checked" v={card?.messages_checked} />
          <Tile k="Allowed" v={card?.allowed} bg="bg-lime" />
          <Tile k="Blocked" v={card?.blocked} bg={card?.blocked ? "bg-coral" : undefined} />
          <Tile k="Sponsor checks" v={card?.sponsor_checks} sub={card?.sponsor_checks_failed ? `${card.sponsor_checks_failed} failed` : undefined} />
        </div>
        {!!card?.block_reasons.length && (
          <ul className="mt-3 space-y-1">
            {card.block_reasons.map(([name, n]) => (
              <li key={name} className="flex items-center justify-between text-[12.5px]">
                <span className="font-semibold">{checkLabel(name)}</span>
                <span className="font-mono font-bold">{n}×</span>
              </li>
            ))}
          </ul>
        )}

        <h3 className="font-display mt-8 text-[19px] font-extrabold tracking-tight">History</h3>
        {a.reviews.length ? (
          <ol className="mt-2 space-y-2">
            {[...a.reviews].reverse().map((r) => (
              <li key={r.id} className="rounded-xl border-2 border-ink bg-panel px-3 py-2.5 shadow-brut-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="flex items-center gap-2 text-[12.5px]">
                    <span className={cn("rounded-md border-[1.5px] border-ink px-1.5 py-px font-mono text-[10.5px] font-extrabold uppercase text-on-color", r.decision === "keep" ? "bg-lime" : r.decision === "restrict" ? "bg-yellow" : "bg-coral")}>
                      {r.decision}
                    </span>
                    <span className="font-bold">{r.reviewer}</span>
                  </span>
                  <span className="text-[11px] text-faint">{day(r.at)}</span>
                </div>
                {r.notes && <p className="mt-1.5 text-[13px] font-medium">{r.notes}</p>}
                <p className="mt-1.5 font-mono text-[10.5px] font-bold text-muted-foreground">
                  at review: {r.scorecard.messages_checked} msgs · {r.scorecard.blocked} blocked · {r.scorecard.sponsor_checks} sponsor checks
                  {r.scopes ? ` · kept ${r.scopes.join(", ")}` : ""}
                </p>
              </li>
            ))}
          </ol>
        ) : (
          <p className="mt-2 text-[12.5px] text-faint">No reviews yet.</p>
        )}
      </div>

      {a.status !== "offboarded" && (
        <div className="h-fit rounded-xl border-2 border-ink bg-elevated p-4 shadow-brut">
          <h3 className="font-display text-[19px] font-extrabold tracking-tight">New review</h3>
          <div className="mt-3 grid grid-cols-3 gap-1 rounded-lg border-2 border-ink bg-panel p-0.5 text-[12.5px]">
            {(["keep", "restrict", "offboard"] as const).map((d) => (
              <button
                key={d}
                onClick={() => setDecision(d)}
                className={cn("h-7 rounded-md font-bold capitalize transition", decision === d ? (d === "offboard" ? "bg-coral text-on-color" : d === "restrict" ? "bg-yellow text-on-color" : "bg-lime text-on-color") : "text-muted-foreground hover:text-foreground")}
              >
                {d}
              </button>
            ))}
          </div>
          {decision === "restrict" && (
            <div className="mt-3 space-y-1.5">
              <span className="text-[11px] font-extrabold uppercase tracking-wider">Scopes to keep</span>
              {a.passport.scopes.map((sc) => (
                <label key={sc} className="flex items-center gap-2 text-[12.5px]">
                  <input type="checkbox" className="accent-[#111]" checked={keep.includes(sc)} onChange={(e) => setKeep((k) => (e.target.checked ? [...k, sc] : k.filter((x) => x !== sc)))} />
                  <span className="font-mono text-[11.5px]">{sc}</span>
                </label>
              ))}
            </div>
          )}
          <div className="mt-3 space-y-3">
            <Field label="Reviewer">
              <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} className={inputCls} />
            </Field>
            <Field label="Notes">
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} className={cn(inputCls, "h-auto py-2")} placeholder="What went well, what to change" />
            </Field>
            <Button
              variant={decision === "offboard" ? "danger" : "primary"}
              onClick={submit}
              disabled={!!busy || (decision === "restrict" && (!keep.length || keep.length === a.passport.scopes.length))}
              className="w-full"
            >
              {busy === "review" && <Loader2 className="size-3.5 animate-spin" />} Record review
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function Tile({ k, v, bg, sub }: { k: string; v?: number; bg?: string; sub?: string }) {
  return (
    <div className={cn("rounded-xl border-2 border-ink px-3 py-3 shadow-brut-sm", bg ? `${bg} text-on-color` : "bg-panel")}>
      <div className="font-display text-[32px] font-extrabold leading-none tabular-nums">{v ?? "–"}</div>
      <div className="mt-1 text-[11.5px] font-bold uppercase tracking-wide opacity-80">{k}</div>
      {sub && <div className="text-[11px] font-bold text-contradicted">{sub}</div>}
    </div>
  );
}

const KIND_LABEL: Record<string, string> = {
  "passport.issued": "Passport issued",
  "passport.verified": "Sponsor checked",
  "passport.revoked": "Passport revoked",
  "passport.reinstated": "Passport reinstated",
  "agent.onboarded": "Onboarded",
  "agent.offboarded": "Offboarded",
  "agent.reviewed": "Reviewed",
  "agent.scopes_changed": "Scopes changed",
  "agent.scope_denied": "Scope refused",
  "agent.scopes_checked": "Scopes checked",
};

function LedgerTab({ agent: a, live }: { agent: Agent; live: boolean }) {
  const [view, setView] = useState<LedgerView | null>(null);
  useEffect(() => {
    if (live) {
      api.ledger(a.agent_id).then(setView).catch(() => setView(null));
      return;
    }
    const mine = snapshot.ledger.entries.filter((e) => {
      const p = e.payload as { agent_id?: string; subject?: string; passport?: { agent_id?: string } };
      return p.agent_id === a.agent_id || p.subject === a.agent_id || p.passport?.agent_id === a.agent_id;
    });
    setView({ ...snapshot.ledger, entries: mine });
  }, [a.agent_id, a.ledger_entries.length, live]);

  if (!view) return <p className="text-[12.5px] text-faint">Loading the ledger…</p>;
  return (
    <div className="max-w-[760px]">
      <p className={cn("inline-flex items-center gap-2 rounded-lg border-2 border-ink px-2.5 py-1 text-[12.5px] font-bold shadow-brut-sm", view.chain_ok ? "bg-lime text-on-color" : "bg-coral text-on-color")}>
        <Link2 className="size-3.5" strokeWidth={2.5} />
        {view.chain_ok ? "Every entry hashes the one before it. The chain is intact." : `Tampering detected: the chain breaks at entry #${view.first_bad_seq}.`}
      </p>
      <ol className="relative ml-1 mt-5 border-l-2 border-ink pl-5">
        {[...view.entries].reverse().map((e) => {
          const p = e.payload as { decision?: "allow" | "block"; reason?: string; scope?: string | null; from?: string[]; to?: string[] };
          const bad = view.first_bad_seq !== null && e.seq >= view.first_bad_seq;
          return (
            <li key={e.hash} className="relative pb-4">
              <span className={cn("absolute -left-[28px] top-1 size-3.5 rounded-full border-2 border-ink", bad ? "bg-coral" : e.kind.includes("revoked") ? "bg-coral" : e.kind.includes("verified") ? "bg-lavender" : "bg-yellow")} />
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-[10.5px] font-bold text-muted-foreground">#{e.seq}</span>
                <span className="text-[13.5px] font-bold">{KIND_LABEL[e.kind] ?? e.kind}</span>
                {p.decision && <DecisionBadge decision={p.decision} />}
                {p.scope && <ScopeChip scope={p.scope as Scope} />}
                <span className="ml-auto font-mono text-[10.5px] font-bold text-muted-foreground">{new Date(e.ts).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}</span>
              </div>
              {p.reason && <p className="mt-0.5 text-[13px] font-medium">{p.reason}</p>}
              {p.from && p.to && <p className="mt-0.5 font-mono text-[11px] font-bold">{p.from.join(", ")} → {p.to.join(", ")}</p>}
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <span className="font-mono text-[10.5px] font-bold text-muted-foreground" title={e.hash}>{e.hash.slice(0, 12)}</span>
                {e.sources.slice(0, 3).map((s, i) => <SourceChip key={i} source={s} />)}
                {e.sources.length > 3 && <span className="text-[10.5px] text-faint">+{e.sources.length - 3}</span>}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

// ---- onboarding ------------------------------------------------------------------------------

function OnboardForm({ roles, scenarios, first, onDone }: { roles: Role[]; scenarios: Scenario[]; first: boolean; onDone: (agentId: string) => void }) {
  const [name, setName] = useState(first ? "Sourced" : "");
  const [roleKey, setRoleKey] = useState(roles[0]?.key ?? "recruiter");
  const role = roles.find((r) => r.key === roleKey);
  const [scopes, setScopes] = useState<Scope[]>(role?.default_scopes ?? []);
  const [sponsor, setSponsor] = useState<Sponsor>(scenarios[0]?.sponsor ?? { name: "", profile_url: "", company: "", company_domain: "", title: "" });
  const [days, setDays] = useState(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [result, setResult] = useState<{ agent: Agent; verdict: Verdict }>();

  const pickRole = (k: string) => {
    setRoleKey(k);
    setScopes(roles.find((r) => r.key === k)?.default_scopes ?? []);
  };
  const set = (k: keyof Sponsor) => (e: React.ChangeEvent<HTMLInputElement>) => setSponsor((s) => ({ ...s, [k]: e.target.value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    try {
      const r = await api.onboard({ name, role: roleKey, sponsor: { ...sponsor, company_domain: sponsor.company_domain || null, title: sponsor.title || null }, scopes, days });
      setResult(r);
      onDone(r.agent.agent_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    const ok = result.agent.status === "active";
    return (
      <div className="h-full overflow-y-auto p-6">
        <span className={cn("grid size-12 -rotate-6 place-items-center rounded-xl border-2 border-ink text-[#111] shadow-brut animate-pop", ok ? "bg-lime" : "bg-coral")}>
          {ok ? <ShieldCheck className="size-6" strokeWidth={2.5} /> : <ShieldAlert className="size-6" strokeWidth={2.5} />}
        </span>
        <h2 className="font-display mt-4 text-[26px] font-extrabold leading-tight tracking-tight">{ok ? `${result.agent.name} is on the team` : `${result.agent.name} was onboarded suspended`}</h2>
        <p className="mt-1 text-[13.5px] font-medium text-muted-foreground">
          {ok
            ? `Passport issued. ${sponsor.name}'s identity, employment and authority all checked out against Crustdata.`
            : `The passport was issued, but ${sponsor.name} can't vouch for it right now, so it starts revoked.`}
        </p>
        <VerdictList verdict={result.verdict} className="mt-4" />
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="flex h-full flex-col">
      <div className="flex-1 space-y-5 overflow-y-auto p-6">
        <div>
          <h2 className="font-display text-[28px] font-extrabold leading-tight tracking-[-0.03em]">Onboard an AI employee</h2>
          <p className="mt-1 text-[13px] font-medium text-muted-foreground">It gets a signed passport tied to a real person, who is checked against Crustdata right away.</p>
        </div>

        <Field label="Name">
          <input required value={name} onChange={(e) => setName(e.target.value)} className={inputCls} placeholder="Sourced" />
        </Field>

        <div>
          <span className="mb-1.5 block text-[11px] font-extrabold uppercase tracking-wider">Role</span>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {roles.map((r) => (
              <button
                type="button"
                key={r.key}
                onClick={() => pickRole(r.key)}
                className={cn("press rounded-xl border-2 border-ink px-3 py-2 text-left shadow-brut-sm", roleKey === r.key ? "bg-yellow text-on-color" : "bg-panel")}
              >
                <span className="block text-[13.5px] font-bold">{r.title}</span>
                <span className="block text-[11.5px] font-medium leading-snug opacity-75">{r.summary}</span>
              </button>
            ))}
          </div>
        </div>

        <div>
          <span className="mb-1.5 block text-[11px] font-extrabold uppercase tracking-wider">Sponsor (the human it acts for)</span>
          {scenarios.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1">
              {scenarios.map((s) => (
                <button
                  type="button"
                  key={s.id}
                  title={s.story}
                  onClick={() => setSponsor(s.sponsor)}
                  className={cn(
                    "h-7 rounded-full border-2 border-ink px-2.5 text-[11.5px] font-bold transition",
                    sponsor.profile_url === s.sponsor.profile_url ? "bg-lavender text-on-color shadow-brut-sm" : "bg-panel hover:bg-hover",
                  )}
                >
                  {s.sponsor.name.split(" ")[0]} · {s.id.replace(/_/g, " ")}
                </button>
              ))}
            </div>
          )}
          <div className="grid gap-2 sm:grid-cols-2">
            <input required value={sponsor.name} onChange={set("name")} placeholder="Full name" className={inputCls} />
            <input value={sponsor.title ?? ""} onChange={set("title")} placeholder="Title (e.g. Head of Talent)" className={inputCls} />
            <input required value={sponsor.company} onChange={set("company")} placeholder="Company" className={inputCls} />
            <input value={sponsor.company_domain ?? ""} onChange={set("company_domain")} placeholder="Sending domain" className={inputCls} />
            <input required value={sponsor.profile_url} onChange={set("profile_url")} placeholder="LinkedIn profile URL" className={cn(inputCls, "sm:col-span-2")} />
          </div>
          {(() => {
            const sc = scenarios.find((s) => s.sponsor.profile_url === sponsor.profile_url);
            return sc ? <p className="mt-2 text-[12px] font-medium text-muted-foreground">{sc.story}</p> : null;
          })()}
        </div>

        <div>
          <span className="mb-1.5 block text-[11px] font-extrabold uppercase tracking-wider">Scopes</span>
          <div className="grid gap-1.5">
            {ALL_SCOPES.map((sc) => (
              <ScopeToggle
                key={sc}
                scope={sc}
                checked={scopes.includes(sc)}
                locked={!!role && !role.ceiling.includes(sc)}
                onChange={(on) => setScopes((cur) => (on ? [...cur, sc] : cur.filter((x) => x !== sc)))}
              />
            ))}
          </div>
        </div>

        <Field label="Passport valid for (days)">
          <input type="number" min={1} max={365} value={days} onChange={(e) => setDays(Number(e.target.value) || 30)} className={cn(inputCls, "w-28")} />
        </Field>

        {error && <p className="rounded-xl border-2 border-ink bg-coral px-3 py-2 text-[13px] font-bold text-on-color shadow-brut-sm">{error}</p>}
      </div>
      <div className="flex items-center justify-end gap-2 border-t-2 border-ink bg-elevated p-4">
        <Button type="submit" variant="primary" disabled={busy || !scopes.length}>
          {busy ? <Loader2 className="size-3.5 animate-spin" /> : <IdCard className="size-3.5" />} Issue passport and check sponsor
        </Button>
      </div>
    </form>
  );
}
