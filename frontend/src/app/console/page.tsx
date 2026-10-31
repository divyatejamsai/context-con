"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft, BadgeCheck, Play, KeyRound, Moon, Sun, Ban, ClipboardCheck, FileClock, IdCard, Link2, Loader2, MousePointerClick, Plus, RefreshCw, RotateCcw, Send,
  ShieldAlert, ShieldCheck, SlidersHorizontal, UserMinus, Users, X,
} from "lucide-react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { API_URL } from "@/lib/stream";
import { cn } from "@/lib/utils";
import {
  ApiError, SCOPE_INFO, api, getAdminToken, setAdminToken, type Agent, type LedgerView, type ReviewDecision, type Role, type Scenario, type Scope, type Sponsor,
  type Verdict,
} from "./api";
import {
  AgentMark, Button, DecisionBadge, EmptyState, Field, RuntimeBadge, ScopeChip, ScopeToggle, SectionHead, StatusPill, TERMS, Term, VerdictList, ago, cardCls,
  checkLabel, day, inputCls,
} from "./parts";
import { VerifyView } from "./verify";
import { GuardView } from "./guard";
import { LedgerExplorer, LedgerTimeline } from "./ledger";

type Mode = "loading" | "live" | "offline";
type View = "employees" | "verify" | "guard" | "ledger";
type Tab = "passport" | "permissions" | "reviews" | "ledger";
type Flash = { tone: "ok" | "bad" | "info"; title: string; body?: string; verdict?: Verdict } | null;
export type Chain = { chain_ok: boolean; first_bad_seq: number | null; count: number };

const VIEWS: { v: View; label: string; icon: React.ElementType; desc: string }[] = [
  { v: "employees", label: "AI employees", icon: Users, desc: "Onboard agents, see their passports, and suspend or retire them" },
  { v: "verify", label: "Verify passport", icon: ShieldCheck, desc: "Check whether an agent that contacts you can be trusted" },
  { v: "guard", label: "Send Guard", icon: Send, desc: "Check a drafted message before an agent can send it" },
  { v: "ledger", label: "Ledger", icon: Link2, desc: "The tamper-evident record of every check and decision" },
];
const ALL_SCOPES = Object.keys(SCOPE_INFO) as Scope[];

export default function Console() {
  const [mode, setMode] = useState<Mode>("loading");
  const [view, setViewState] = useState<View>("employees");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [chain, setChain] = useState<Chain>();
  const [selected, setSelected] = useState<string>();
  const [tab, setTab] = useState<Tab>("passport");
  const [busy, setBusy] = useState<string | null>(null);
  const [flash, setFlash] = useState<Flash>(null);
  const [payroll, setPayroll] = useState<{ verdicts: Verdict[]; suspended: string[] } | null>(null);
  const [onboarding, setOnboarding] = useState(false);

  const setView = (v: View) => {
    setViewState(v);
    const u = new URL(window.location.href);
    u.searchParams.set("view", v);
    window.history.replaceState(null, "", u);
  };

  const refresh = useCallback(async () => {
    const [list, l] = await Promise.all([api.agents(), api.ledger()]);
    setAgents(list);
    setChain({ chain_ok: l.chain_ok, first_bad_seq: l.first_bad_seq, count: l.entries.length });
    return list;
  }, []);

  const connect = useCallback(() => {
    setMode("loading");
    Promise.all([refresh(), api.roles(), api.scenarios().catch(() => [])])
      .then(([, r, s]) => {
        setRoles(r.roles);
        setScenarios(s);
        setMode("live");
      })
      .catch(() => setMode("offline"));
  }, [refresh]);

  useEffect(() => {
    const v = new URLSearchParams(window.location.search).get("view") as View | null;
    if (v && VIEWS.some((x) => x.v === v)) setViewState(v);
    connect();
  }, [connect]);

  useEffect(() => {
    if (!selected && agents.length) setSelected(agents[0].agent_id);
  }, [agents, selected]);

  const cur = agents.find((a) => a.agent_id === selected);
  const counts = useMemo(
    () => agents.reduce((c, a) => ({ ...c, [a.status]: (c[a.status] ?? 0) + 1 }), {} as Record<string, number>),
    [agents],
  );

  /** Runs a backend action, refreshes the list, and turns errors (including scope denials) into a flash. */
  const act = async <T,>(key: string, fn: () => Promise<T>, ok?: (r: T) => Flash) => {
    setBusy(key);
    setFlash(null);
    try {
      const r = await fn();
      await refresh();
      if (ok) setFlash(ok(r));
      return r;
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(String(e), 0);
      setFlash(
        err.status === 401
          ? { tone: "bad", title: "Admin token needed", body: "This backend requires an admin token for changes. Add it with the key button at the top right." }
          : { tone: "bad", title: err.status === 403 ? "Refused" : "Couldn't do that", body: err.message, verdict: err.verdict },
      );
    } finally {
      setBusy(null);
    }
  };

  const startOnboarding = () => {
    setView("employees");
    setOnboarding(true);
  };

  const runPayroll = async () => {
    const before = new Map(agents.map((a) => [a.agent_id, a.status]));
    setBusy("payroll");
    setFlash(null);
    try {
      const verdicts = await api.payroll();
      const list = await refresh();
      const suspended = list.filter((a) => a.status === "suspended" && before.get(a.agent_id) === "active").map((a) => a.agent_id);
      setPayroll({ verdicts, suspended });
    } catch (e) {
      setFlash({ tone: "bad", title: "Sponsor re-check failed", body: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-border bg-background/90 backdrop-blur-xl">
        <div className="mx-auto flex h-12 max-w-[1680px] items-center justify-between gap-3 px-4">
          <div className="flex min-w-0 items-center gap-1.5">
            <Link
              href="/"
              title="Back to Sourced, the hiring agent: paste a brief and get a verified shortlist"
              className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2 text-[12.5px] text-muted-foreground hover:bg-elevated hover:text-foreground"
            >
              <ArrowLeft className="size-3.5" /> Sourced
              <span className="hidden text-faint 2xl:inline">· find candidates</span>
            </Link>
            <span className="text-faint">/</span>
            <span className="flex min-w-0 items-center gap-2 px-1" title="Countersign checks that an AI agent is vouched for by a real person before anyone trusts it">
              <IdCard className="size-4 shrink-0 text-primary" />
              <span className="text-[14px] font-[620] tracking-[-0.01em]">Countersign</span>
            </span>
            <nav className="ml-4 hidden items-center gap-0.5 md:flex" aria-label="Countersign">
              {VIEWS.map((x) => <NavItem key={x.v} {...x} active={view === x.v} onClick={() => setView(x.v)} />)}
              <Link
                href="/console/demo"
                title="Watch six AI employees go through seven situations, with every decision and its source"
                className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-[12.5px] font-[510] text-muted-foreground transition hover:text-foreground"
              >
                <Play className="size-3.5" /> Guided demo
              </Link>
            </nav>
          </div>
          <div className="flex items-center gap-2">
            <AdminToken />
            <ThemeToggle />
            {chain && (
              <button onClick={() => setView("ledger")} title="Open the ledger: every passport, check and decision, hash-chained so edits are detectable">
                <ChainPill {...chain} />
              </button>
            )}
            <span
              className={cn(
                "inline-flex h-6 items-center gap-1.5 rounded-full border px-2 font-mono text-[10.5px]",
                mode === "live" ? "border-verified/30 text-verified" : mode === "offline" ? "border-contradicted/30 text-contradicted" : "border-border-strong text-faint",
              )}
              title={mode === "live" ? `Connected to the Countersign backend at ${API_URL}. Everything here is real data.` : `Can't reach the backend at ${API_URL}`}
            >
              <span className={cn("size-1.5 rounded-full", mode === "live" ? "bg-verified" : mode === "offline" ? "bg-contradicted" : "bg-faint")} />
              {mode === "loading" ? "connecting" : mode === "live" ? "live" : "offline"}
            </span>
          </div>
        </div>
        <nav className="flex gap-0.5 overflow-x-auto px-3 pb-2 md:hidden" aria-label="Countersign">
          {VIEWS.map((x) => <NavItem key={x.v} {...x} active={view === x.v} onClick={() => setView(x.v)} />)}
          <Link
            href="/console/demo"
            title="Watch six AI employees go through seven situations, with every decision and its source"
            className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-[12.5px] font-[510] text-muted-foreground transition hover:text-foreground"
          >
            <Play className="size-3.5" /> Guided demo
          </Link>
        </nav>
      </header>

      {mode === "offline" ? (
        <Offline onRetry={connect} />
      ) : mode === "loading" ? (
        <div className="grid min-h-[60vh] place-items-center text-[13px] text-faint">
          <span className="inline-flex items-center gap-2">
            <Loader2 className="size-4 animate-spin" /> Connecting to the Countersign backend…
          </span>
        </div>
      ) : view === "verify" ? (
        <VerifyView agents={agents} scenarios={scenarios} onOnboard={startOnboarding} />
      ) : view === "guard" ? (
        <GuardView agents={agents} onSent={refresh} onOnboard={startOnboarding} />
      ) : view === "ledger" ? (
        <LedgerExplorer agents={agents} onChain={setChain} onOnboard={startOnboarding} />
      ) : (
        <main className="mx-auto grid max-w-[1680px] grid-cols-[minmax(0,1fr)] lg:grid-cols-[minmax(360px,440px)_minmax(0,1fr)]">
          <section className="min-w-0 border-border lg:sticky lg:top-12 lg:h-[calc(100vh-3rem)] lg:overflow-y-auto lg:border-r">
            <div className="px-4 pb-4 pt-6">
              <h1 className="text-[22px] font-[620] tracking-[-0.02em]">AI employees</h1>
              <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
                The AI agents that work for your company. Each carries a <Term tip={TERMS.passport}>passport</Term> naming the real person it
                acts for, its <Term tip={TERMS.sponsor}>sponsor</Term>. An agent is trusted only while Crustdata confirms that sponsor still
                works there and can delegate the work.
              </p>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <Button variant="primary" onClick={() => setOnboarding(true)} title="Issue a passport for a new AI agent and check its sponsor in Crustdata">
                  <Plus className="size-3.5" /> Onboard an agent
                </Button>
                <Button
                  onClick={runPayroll}
                  disabled={busy === "payroll" || !agents.length}
                  title="Payroll check: looks up every sponsor in Crustdata again and suspends any agent whose sponsor has left or lost authority"
                >
                  {busy === "payroll" ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
                  Re-check all sponsors
                </Button>
                <span className="ml-auto flex items-center gap-3 text-[11.5px] text-muted-foreground tabular-nums">
                  <span className="inline-flex items-center gap-1.5"><span className="size-1.5 rounded-full bg-verified" />{counts.active ?? 0} active</span>
                  {!!counts.suspended && <span className="inline-flex items-center gap-1.5"><span className="size-1.5 rounded-full bg-contradicted" />{counts.suspended} suspended</span>}
                </span>
              </div>
              {agents.length > 0 && (
                <p className="mt-3 flex items-center gap-1.5 text-[11.5px] text-faint">
                  <MousePointerClick className="size-3.5 shrink-0" /> Pick an agent to see its passport, permissions, reviews and history.
                </p>
              )}
            </div>

            {payroll && <PayrollBanner run={payroll} agents={agents} onClose={() => setPayroll(null)} onPick={setSelected} />}

            <ul className="border-t border-border">
              {!agents.length && (
                <li>
                  <EmptyState
                    icon={Users}
                    title="No AI employees yet"
                    action={
                      <Button variant="primary" onClick={() => setOnboarding(true)}>
                        <Plus className="size-3.5" /> Onboard Sourced as employee #1
                      </Button>
                    }
                  >
                    Onboarding issues the agent a passport and checks its sponsor in Crustdata straight away. Start with Sourced, the hiring agent.
                  </EmptyState>
                </li>
              )}
              {agents.map((a) => (
                <AgentRow key={a.agent_id} agent={a} selected={a.agent_id === selected} onClick={() => setSelected(a.agent_id)} />
              ))}
            </ul>
          </section>

          <section className="min-w-0">
            {flash && <FlashBar flash={flash} onClose={() => setFlash(null)} />}
            {cur ? (
              <AgentDetail key={cur.agent_id} agent={cur} role={roles.find((r) => r.title === cur.role)} tab={tab} setTab={setTab} busy={busy} act={act} />
            ) : (
              <EmptyState icon={MousePointerClick} title="Select an AI employee" className="min-h-[50vh] justify-center">
                Its passport, permissions, reviews and history open here.
              </EmptyState>
            )}
          </section>
        </main>
      )}

      <Sheet open={onboarding} onOpenChange={setOnboarding}>
        <SheetContent className="border-border bg-panel">
          <SheetTitle className="sr-only">Onboard an AI employee</SheetTitle>
          <OnboardForm
            roles={roles}
            scenarios={scenarios}
            first={!agents.length}
            onDone={async (agentId) => {
              await refresh();
              setSelected(agentId);
              setTab("passport");
              setView("employees");
            }}
          />
        </SheetContent>
      </Sheet>
    </div>
  );
}

/** Same switch as the Sourced header: data-theme on <html>, remembered under "theme". */
function ThemeToggle() {
  const [dark, setDark] = useState(false);
  useEffect(() => setDark(document.documentElement.dataset.theme === "dark"), []);
  const flip = () => {
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch {}
    setDark(!dark);
  };
  return (
    <button onClick={flip} className="grid size-7 place-items-center rounded-md text-muted-foreground hover:bg-hover hover:text-foreground" aria-label={dark ? "Light theme" : "Dark theme"}>
      {dark ? <Sun className="size-3.5" /> : <Moon className="size-3.5" />}
    </button>
  );
}

function AdminToken() {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [has, setHas] = useState(false);
  useEffect(() => setHas(!!getAdminToken()), []);
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className={cn("grid size-7 place-items-center rounded-md hover:bg-elevated", has ? "text-foreground" : "text-muted-foreground")}
        title={has ? "Admin token set. Changes to agents are sent with it." : "Set the admin token (only needed if the backend asks for one)"}
        aria-label="Admin token"
      >
        <KeyRound className="size-3.5" />
      </button>
      {open && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setAdminToken(value.trim());
            setHas(!!value.trim());
            setValue("");
            setOpen(false);
          }}
          className={cn(cardCls, "absolute right-0 top-9 z-40 w-72 p-3 shadow-lg animate-fade")}
        >
          <p className="text-[12.5px] font-[510]">Admin token</p>
          <p className="mt-0.5 text-[11.5px] text-muted-foreground">Needed to change agents when the backend sets COUNTERSIGN_ADMIN_TOKEN. Stored in this browser only.</p>
          <input type="password" value={value} onChange={(e) => setValue(e.target.value)} placeholder={has ? "•••••• (set)" : "Paste token"} className={cn(inputCls, "mt-2")} />
          <div className="mt-2 flex justify-end gap-1.5">
            {has && (
              <Button variant="ghost" onClick={() => { setAdminToken(""); setHas(false); setOpen(false); }}>Clear</Button>
            )}
            <Button type="submit" variant="primary">Save</Button>
          </div>
        </form>
      )}
    </div>
  );
}

function NavItem({ label, icon: I, desc, active, onClick }: { label: string; icon: React.ElementType; desc: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      title={desc}
      aria-current={active ? "page" : undefined}
      className={cn(
        "inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-[12.5px] font-[510] transition",
        active ? "bg-elevated text-foreground shadow-[0_0_0_1px_var(--border-strong)]" : "text-muted-foreground hover:text-foreground",
      )}
    >
      <I className="size-3.5" /> {label}
    </button>
  );
}

function Offline({ onRetry }: { onRetry: () => void }) {
  return (
    <main className="mx-auto max-w-[600px] px-4 py-20">
      <div className={cn(cardCls, "p-6")}>
        <ShieldAlert className="size-5 text-contradicted" />
        <h1 className="mt-3 text-[18px] font-[600]">The Countersign backend is offline</h1>
        <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
          The console only shows real state. Every passport, check and ledger entry comes from the backend at{" "}
          <span className="font-mono text-secondary">{API_URL}</span>. Start it, then retry.
        </p>
        <pre className="mt-4 overflow-x-auto rounded-lg border border-border bg-background p-3 font-mono text-[12px] leading-relaxed text-secondary">
          {"cd backend\nuvicorn app.main:app --reload --port 8000"}
        </pre>
        <Button variant="primary" onClick={onRetry} className="mt-4">
          <RefreshCw className="size-3.5" /> Retry
        </Button>
      </div>
    </main>
  );
}

// ---- list ------------------------------------------------------------------------------------

function AgentRow({ agent: a, selected, onClick }: { agent: Agent; selected: boolean; onClick: () => void }) {
  const s = a.passport.sponsor;
  return (
    <li>
      <button
        onClick={onClick}
        className={cn(
          "relative grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-3 border-b border-border px-4 py-3.5 text-left transition",
          selected ? "bg-elevated" : "hover:bg-hover/60",
          a.status === "offboarded" && "opacity-60",
        )}
      >
        {selected && <span className="absolute inset-y-0 left-0 w-0.5 bg-primary" />}
        <AgentMark agent={a} />
        <span className="min-w-0">
          <span className="flex items-baseline gap-2">
            <span className="truncate text-[14px] font-[590]">{a.name}</span>
            <span className="font-mono text-[10.5px] text-faint">#{a.employee_no}</span>
            <RuntimeBadge runtime={a.runtime} />
          </span>
          {a.job && <span className="block truncate text-[12px] text-secondary">{a.job}</span>}
          <span className="block truncate text-[12px] text-muted-foreground">
            {a.role} · for <span className="text-secondary">{s.name}</span>, {s.company}
          </span>
          {a.status !== "active" && a.reason ? (
            <span className={cn("mt-1 line-clamp-2 text-[11.5px] leading-snug", a.status === "suspended" ? "text-contradicted" : "text-faint")}>{a.reason}</span>
          ) : (
            <span className="mt-1.5 flex flex-wrap gap-1">{a.passport.scopes.map((sc) => <ScopeChip key={sc} scope={sc} />)}</span>
          )}
        </span>
        <span className="flex flex-col items-end gap-1.5">
          <StatusPill status={a.status} />
          <span className="text-[10.5px] text-faint">checked {ago(a.last_checked)}</span>
        </span>
      </button>
    </li>
  );
}

function ChainPill({ chain_ok, first_bad_seq, count }: Chain) {
  return (
    <span
      className={cn(
        "hidden h-6 items-center gap-1.5 rounded-full border px-2 text-[11px] font-[510] sm:inline-flex",
        chain_ok ? "border-border-strong text-muted-foreground hover:text-foreground" : "border-contradicted/40 bg-contradicted/10 text-contradicted",
      )}
    >
      <Link2 className="size-3" />
      {chain_ok ? `Ledger intact · ${count}` : `Ledger broken at #${first_bad_seq}`}
    </span>
  );
}

function PayrollBanner({
  run, agents, onClose, onPick,
}: { run: { verdicts: Verdict[]; suspended: string[] }; agents: Agent[]; onClose: () => void; onPick: (id: string) => void }) {
  const blocked = run.verdicts.filter((v) => v.decision === "block");
  const byId = new Map(agents.map((a) => [a.agent_id, a]));
  return (
    <div className={cn(cardCls, "mx-4 mb-4 overflow-hidden animate-rise")}>
      <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-2">
        <span className="flex items-center gap-2 text-[12.5px] font-[590]">
          <ClipboardCheck className="size-3.5 text-primary" /> Sponsor re-check
          <span className="font-normal text-muted-foreground">
            {run.verdicts.length} checked, {blocked.length} blocked{run.suspended.length ? `, ${run.suspended.length} suspended now` : ""}
          </span>
        </span>
        <button onClick={onClose} className="rounded p-0.5 text-faint hover:bg-hover hover:text-foreground" aria-label="Dismiss">
          <X className="size-3.5" />
        </button>
      </div>
      <p className="border-b border-border px-3 py-2 text-[11.5px] text-muted-foreground">
        Every sponsor was looked up in Crustdata again. Agents whose sponsor left or lost authority are suspended. Click one to see why.
      </p>
      <ul className="divide-y divide-border">
        {run.verdicts.map((v) => {
          const a = byId.get(v.subject);
          const fail = v.checks.find((c) => c.status !== "pass" && c.name !== "not_revoked") ?? v.checks.find((c) => c.status !== "pass");
          return (
            <li key={v.subject}>
              <button onClick={() => a && onPick(a.agent_id)} className="flex w-full items-start gap-2.5 px-3 py-2 text-left hover:bg-hover/60">
                <DecisionBadge decision={v.decision} />
                <span className="min-w-0 flex-1">
                  <span className="text-[12.5px] font-[510]">{a?.name ?? v.subject}</span>
                  {run.suspended.includes(v.subject) && <span className="ml-2 text-[11px] text-contradicted">suspended now</span>}
                  {fail && <span className="block truncate text-[11.5px] text-muted-foreground">{checkLabel(fail.name)}: {fail.detail}</span>}
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
        "mx-4 mt-4 rounded-lg border px-3 py-2.5 animate-rise sm:mx-6",
        flash.tone === "bad" && "border-contradicted/30 bg-contradicted/[0.06]",
        flash.tone === "ok" && "border-verified/30 bg-verified/[0.06]",
        flash.tone === "info" && "border-border-strong bg-elevated",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-[13px]">
          <span className={cn("font-[590]", flash.tone === "bad" ? "text-contradicted" : flash.tone === "ok" ? "text-verified" : "text-foreground")}>{flash.title}.</span>{" "}
          <span className="text-secondary">{flash.body}</span>
        </p>
        <button onClick={onClose} className="rounded p-0.5 text-faint hover:text-foreground" aria-label="Dismiss">
          <X className="size-3.5" />
        </button>
      </div>
      {flash.verdict && <VerdictList verdict={flash.verdict} className="mt-1" />}
    </div>
  );
}

// ---- detail ----------------------------------------------------------------------------------

type Act = <T>(key: string, fn: () => Promise<T>, ok?: (r: T) => Flash) => Promise<T | undefined>;

function AgentDetail({
  agent: a, role, tab, setTab, busy, act,
}: { agent: Agent; role?: Role; tab: Tab; setTab: (t: Tab) => void; busy: string | null; act: Act }) {
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
        ? { tone: "ok", title: "Reinstated", body: "A fresh check passed, so the passport is valid again." }
        : { tone: "bad", title: "Still suspended", body: "The sponsor check still fails.", verdict: r.verdict },
    );
  const doConfirm = async () => {
    const kind = confirm;
    if (!kind) return;
    await act(kind, () => (kind === "suspend" ? api.suspend(a.agent_id, reason) : api.offboard(a.agent_id, reason)), () => ({
      tone: "info",
      title: kind === "suspend" ? "Suspended" : "Offboarded",
      body: "The passport is revoked on the ledger, so anyone who checks it will refuse it.",
    }));
    setConfirm(null);
    setReason("");
  };

  return (
    <div className="px-4 pb-16 pt-6 sm:px-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <AgentMark agent={a} size="lg" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-[20px] font-[620] tracking-[-0.02em]">{a.name}</h2>
              <StatusPill status={a.status} />
              <RuntimeBadge runtime={a.runtime} />
            </div>
            <p className="text-[12.5px] text-muted-foreground">
              {a.role} · employee #{a.employee_no} · onboarded {day(a.onboarded_at)}
            </p>
            {a.job && <p className="mt-0.5 text-[12.5px] text-secondary">{a.job}</p>}
          </div>
        </div>
        {!gone && (
          <div className="flex flex-wrap items-center gap-1.5">
            <Button
              onClick={recheck}
              disabled={!!busy}
              title={`Look up ${a.passport.sponsor.name} in Crustdata now. If they have left or lost authority, ${a.name} is suspended.`}
            >
              {busy === "recheck" ? <Loader2 className="size-3.5 animate-spin" /> : <ShieldCheck className="size-3.5" />} Re-check sponsor
            </Button>
            {a.status === "suspended" ? (
              <Button onClick={reinstate} disabled={!!busy} title="Run a fresh sponsor check. If it passes, the passport is valid again.">
                {busy === "reinstate" ? <Loader2 className="size-3.5 animate-spin" /> : <RotateCcw className="size-3.5" />} Reinstate
              </Button>
            ) : (
              <Button onClick={() => setConfirm("suspend")} disabled={!!busy} title="Pause this agent: its passport is revoked until you reinstate it">
                <Ban className="size-3.5" /> Suspend
              </Button>
            )}
            <Button variant="danger" onClick={() => setConfirm("offboard")} disabled={!!busy} title="Retire this agent for good: its passport is revoked permanently">
              <UserMinus className="size-3.5" /> Offboard
            </Button>
          </div>
        )}
      </div>

      {a.status !== "active" && a.reason && (
        <div className={cn("mt-4 flex items-start gap-2.5 rounded-lg border px-3 py-2.5", a.status === "suspended" ? "border-contradicted/30 bg-contradicted/[0.06]" : "border-border-strong bg-elevated")}>
          <ShieldAlert className={cn("mt-0.5 size-4 shrink-0", a.status === "suspended" ? "text-contradicted" : "text-faint")} />
          <p className="text-[13px]">
            <span className="font-[590]">{a.status === "suspended" ? `Suspended${a.suspended_by ? ` by ${a.suspended_by}` : ""}.` : "Offboarded."}</span>{" "}
            <span className="text-secondary">{a.reason}</span>
          </p>
        </div>
      )}

      {confirm && (
        <div className={cn(cardCls, "mt-4 p-4 animate-rise", confirm === "offboard" && "border-contradicted/35")}>
          <p className="text-[13.5px] font-[590]">{confirm === "suspend" ? `Suspend ${a.name}?` : `Offboard ${a.name}? This can't be undone.`}</p>
          <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">
            {confirm === "suspend"
              ? `Its passport is revoked right away, so anyone who checks it, and the Send Guard, will refuse it. You can reinstate it later after a fresh sponsor check.`
              : `Its passport is revoked permanently and it leaves the active roster. Its history stays on the ledger.`}{" "}
            Your reason is recorded on the ledger.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <input
              autoFocus
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={confirm === "suspend" ? "Reason, e.g. sponsor on leave" : "Reason, e.g. project finished"}
              className={cn(inputCls, "min-w-0 flex-1 sm:min-w-[240px]")}
            />
            <Button variant={confirm === "offboard" ? "danger" : "primary"} onClick={doConfirm} disabled={!!busy}>
              {busy === confirm && <Loader2 className="size-3.5 animate-spin" />}
              {confirm === "suspend" ? "Suspend and revoke passport" : "Offboard permanently"}
            </Button>
            <Button variant="ghost" onClick={() => setConfirm(null)}>Cancel</Button>
          </div>
        </div>
      )}

      <nav className="mt-6 flex gap-0.5 overflow-x-auto border-b border-border sm:gap-1" role="tablist">
        {([
          ["passport", "Passport", IdCard],
          ["permissions", "Permissions", SlidersHorizontal],
          ["reviews", "Reviews", BadgeCheck],
          ["ledger", "History", FileClock],
        ] as const).map(([k, label, I]) => (
          <button
            key={k}
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={cn(
              "-mb-px inline-flex shrink-0 items-center gap-1.5 border-b-2 px-2 pb-2 pt-1 text-[12.5px] font-[510] transition sm:px-2.5",
              tab === k ? "border-primary text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            <I className="size-3.5" /> {label}
            {k === "reviews" && a.reviews.length > 0 && <span className="font-mono text-[10.5px] text-faint">{a.reviews.length}</span>}
          </button>
        ))}
      </nav>

      <p className="mt-3 text-[12.5px] text-muted-foreground">{TAB_DESC[tab](a)}</p>

      <div className="mt-5">
        {tab === "passport" && <PassportTab agent={a} />}
        {tab === "permissions" && <PermissionsTab agent={a} role={role} busy={busy} act={act} />}
        {tab === "reviews" && <ReviewsTab agent={a} busy={busy} act={act} />}
        {tab === "ledger" && <AgentHistory agent={a} />}
      </div>
    </div>
  );
}

const TAB_DESC: Record<Tab, (a: Agent) => string> = {
  passport: (a) => `The signed ID ${a.name} shows to anyone it contacts, and what Crustdata said about its sponsor at the last check.`,
  permissions: (a) => `What ${a.name} is allowed to do. Adding a permission checks ${a.passport.sponsor.name}'s authority in Crustdata first.`,
  reviews: (a) => `${a.name}'s track record from the ledger, and human reviews where you keep, restrict or offboard it.`,
  ledger: (a) => `Every ledger entry about ${a.name}, newest first. Each one lists the Crustdata sources behind it.`,
};

function PassportTab({ agent: a }: { agent: Agent }) {
  const p = a.passport;
  const s = p.sponsor;
  const mrz = `P<CSN<${p.agent_name}<<${s.company}<<${p.agent_id}`.toUpperCase().replace(/[^A-Z0-9<]/g, "<").padEnd(60, "<").slice(0, 60);
  return (
    <div className="grid gap-6 2xl:grid-cols-[minmax(0,500px)_minmax(0,1fr)]">
      <div className={cn(cardCls, "relative overflow-hidden")}>
        <div className="flex items-center justify-between border-b border-border px-5 py-2.5">
          <span className="font-mono text-[10.5px] tracking-[0.16em] text-muted-foreground">AGENT PASSPORT</span>
          <span className="font-mono text-[10.5px] text-faint">No. {String(a.employee_no).padStart(3, "0")}</span>
        </div>
        <div className="p-5">
          <div className="text-[20px] font-[620] leading-tight tracking-[-0.02em]">{p.agent_name}</div>
          <div className="text-[12.5px] text-muted-foreground">{p.role}</div>
          <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-3 text-[12.5px]">
            <PField k="Acts for" v={s.name} />
            <PField k="Sponsor title" v={s.title ?? "–"} />
            <PField k="Company" v={s.company} />
            <PField k="Domain" v={s.company_domain ?? "–"} mono />
            <PField k="Issued" v={day(p.issued_at)} />
            <PField k="Expires" v={day(p.expires_at)} />
            <div className="col-span-2">
              <dt className="text-[11px] text-faint">Scopes</dt>
              <dd className="mt-1 flex flex-wrap gap-1">{p.scopes.map((sc) => <ScopeChip key={sc} scope={sc} />)}</dd>
            </div>
            <PField k="Agent key" v={`ed25519:${p.public_key.slice(0, 16)}…`} mono />
            <PField k="Issuer key" v={p.issuer_key_id || "–"} mono />
          </dl>
          <div className="mt-5 border-t border-dashed border-border-strong pt-3 font-mono text-[10.5px] leading-relaxed tracking-[0.1em] text-faint">
            <div className="truncate">{mrz}</div>
            <div className="truncate">SIG {p.issuer_signature?.slice(0, 48)}</div>
          </div>
        </div>
        {a.status !== "active" && (
          <span
            className={cn(
              "pointer-events-none absolute right-5 top-14 rotate-[-10deg] rounded border-2 px-2.5 py-0.5 font-mono text-[15px] font-semibold tracking-[0.18em]",
              a.status === "suspended" ? "border-contradicted/70 text-contradicted" : "border-faint text-faint",
            )}
          >
            {a.status === "suspended" ? "REVOKED" : "OFFBOARDED"}
          </span>
        )}
      </div>

      <div>
        <SectionHead
          title="Last sponsor check"
          aside={<span className="text-[11.5px] text-faint">{a.last_checked ? `${ago(a.last_checked)} · ${day(a.last_checked)}` : "not checked yet"}</span>}
        >
          Allow means every check passed and the agent can be trusted. Block means at least one failed, shown first.
        </SectionHead>
        {a.last_verdict ? (
          <>
            <div className="mt-2 flex items-center gap-2 text-[12px] text-muted-foreground">
              <DecisionBadge decision={a.last_verdict.decision} />
              {a.last_verdict.checks.filter((c) => c.status === "pass").length} of {a.last_verdict.checks.length} checks passed, each with its source
            </div>
            <VerdictList verdict={a.last_verdict} className="mt-2" />
          </>
        ) : (
          <p className="mt-2 text-[12.5px] text-faint">Not checked yet. Use Re-check sponsor above to see what Crustdata says about {s.name}.</p>
        )}
      </div>
    </div>
  );
}

function PField({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-faint">{k}</dt>
      <dd className={cn("mt-0.5 truncate", mono ? "font-mono text-[11.5px] text-secondary" : "font-[510]")} title={v}>{v}</dd>
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
      body: r.verdict ? `${a.passport.sponsor.name}'s authority was checked live for the new scopes.` : "Removing scopes needs no sponsor check.",
      verdict: r.verdict ?? undefined,
    })).then((r) => {
      if (!r) setScopes(a.passport.scopes);
    });
  return (
    <div className="max-w-[640px]">
      <p className="text-[13px] leading-relaxed text-muted-foreground">
        Two things limit what {a.name} may do. The role sets a ceiling ({role?.title ?? a.role}). The sponsor must also hold that authority,
        which is checked against their current title in Crustdata whenever a scope is added.
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
        <span className="text-[11.5px] text-faint">{widening ? `Adding a permission checks ${a.passport.sponsor.name} in Crustdata, then re-issues the passport.` : "Saving re-issues the passport with these permissions."}</span>
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
    api.agent(a.agent_id).then((r) => setCard(r.scorecard)).catch(() => {});
  }, [a.agent_id, a.reviews.length, a.ledger_entries.length]);

  const submit = async () => {
    const r = await act("review", () => api.review(a.agent_id, { reviewer, decision, notes, scopes: decision === "restrict" ? keep : undefined }), () => ({
      tone: "ok",
      title: "Review recorded",
      body: decision === "keep" ? "No changes." : decision === "restrict" ? "Scopes narrowed and passport re-issued." : `${a.name} is offboarded.`,
    }));
    if (r) setNotes("");
  };

  return (
    <div className="grid gap-8 2xl:grid-cols-[minmax(0,1fr)_minmax(0,400px)]">
      <div>
        <SectionHead title="Scorecard">Counted from the ledger: what the Send Guard let through, what it stopped, and the work this agent filed.</SectionHead>
        <div className="mt-3 grid grid-cols-2 overflow-hidden rounded-lg border border-border-strong sm:grid-cols-4">
          <Tile k="Messages checked" v={card?.messages_checked} />
          <Tile k="Allowed" v={card?.allowed} tone="text-verified" />
          <Tile k="Blocked" v={card?.blocked} tone={card?.blocked ? "text-contradicted" : undefined} />
          <Tile k="Sponsor checks" v={card?.sponsor_checks} sub={card?.sponsor_checks_failed ? `${card.sponsor_checks_failed} failed` : undefined} />
        </div>
        {!!card?.recent_work?.length && (
          <div className="mt-4">
            <div className="flex items-baseline justify-between">
              <span className="text-[12.5px] font-[590]">Work filed</span>
              <span className="text-[11.5px] text-faint">
                {card.work_filed} total{card.work_by_kind?.length ? ` · ${card.work_by_kind.map(([k, n]) => `${n} ${k.replace(/_/g, " ")}`).join(", ")}` : ""}
              </span>
            </div>
            <ul className="mt-1.5 divide-y divide-border rounded-lg border border-border-strong">
              {card.recent_work.map((w) => (
                <li key={w.seq} className="flex items-start gap-3 px-3 py-2">
                  <span className="mt-px rounded border border-border-strong px-1 font-mono text-[10.5px] text-muted-foreground">{w.kind.replace(/_/g, " ")}</span>
                  <span className="min-w-0 flex-1 text-[12.5px] text-secondary">{w.summary}</span>
                  <span className="shrink-0 text-[11px] text-faint">{w.sources} sources · #{w.seq}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {!!card?.block_reasons.length && (
          <ul className="mt-3 space-y-1">
            <li className="text-[11.5px] font-[510] text-muted-foreground">Why messages were blocked</li>
            {card.block_reasons.map(([name, n]) => (
              <li key={name} className="flex items-center justify-between text-[12.5px]">
                <span className="text-secondary">{checkLabel(name)}</span>
                <span className="font-mono text-faint">{n}×</span>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-8">
          <SectionHead title="Past reviews">Decisions a person made about this agent, newest first.</SectionHead>
        </div>
        {a.reviews.length ? (
          <ol className="mt-2 space-y-2">
            {[...a.reviews].reverse().map((r) => (
              <li key={r.id} className={cn(cardCls, "px-3 py-2.5")}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="flex items-center gap-2 text-[12.5px]">
                    <span className={cn("rounded px-1.5 py-px font-mono text-[10.5px] uppercase", r.decision === "keep" ? "bg-verified/15 text-verified" : r.decision === "restrict" ? "bg-flag/15 text-flag" : "bg-contradicted/15 text-contradicted")}>
                      {r.decision}
                    </span>
                    <span className="font-[510]">{r.reviewer}</span>
                  </span>
                  <span className="text-[11px] text-faint">{day(r.at)}</span>
                </div>
                {r.notes && <p className="mt-1.5 text-[12.5px] text-secondary">{r.notes}</p>}
                <p className="mt-1.5 font-mono text-[10.5px] text-faint">
                  at review: {r.scorecard.messages_checked} messages, {r.scorecard.blocked} blocked, {r.scorecard.sponsor_checks} sponsor checks
                  {r.scopes ? `, kept ${r.scopes.join(", ")}` : ""}
                </p>
              </li>
            ))}
          </ol>
        ) : (
          <p className="mt-2 rounded-lg border border-dashed border-border-strong px-3 py-3 text-[12.5px] text-muted-foreground">
            No reviews yet. Once {a.name} has done some work, record one with the New review form.
          </p>
        )}
      </div>

      {a.status !== "offboarded" && (
        <div className={cn(cardCls, "h-fit p-4")}>
          <SectionHead title="New review">Look at the scorecard, then decide what happens next.</SectionHead>
          <div className="mt-3 grid grid-cols-3 gap-0.5 rounded-md border border-border-strong bg-background p-0.5 text-[12px]">
            {(["keep", "restrict", "offboard"] as const).map((d) => (
              <button
                key={d}
                onClick={() => setDecision(d)}
                className={cn("h-7 rounded font-[510] capitalize transition", decision === d ? "bg-elevated text-foreground shadow-[0_0_0_1px_var(--border-strong)]" : "text-muted-foreground hover:text-foreground")}
              >
                {d}
              </button>
            ))}
          </div>
          <p className="mt-2 text-[12px] text-muted-foreground">{REVIEW_HELP[decision]}</p>
          {decision === "restrict" && (
            <div className="mt-3 space-y-1.5">
              <span className="text-[12px] font-[510] text-muted-foreground">Scopes to keep</span>
              {a.passport.scopes.map((sc) => (
                <label key={sc} className="flex items-center gap-2 text-[12.5px]">
                  <input type="checkbox" className="accent-[var(--primary)]" checked={keep.includes(sc)} onChange={(e) => setKeep((k) => (e.target.checked ? [...k, sc] : k.filter((x) => x !== sc)))} />
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
              {busy === "review" && <Loader2 className="size-3.5 animate-spin" />}
              {decision === "keep" ? "Record review" : decision === "restrict" ? "Record review and narrow permissions" : "Record review and offboard"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

const REVIEW_HELP: Record<ReviewDecision, string> = {
  keep: "No change to the agent. The review is recorded on the ledger.",
  restrict: "Keep the agent but take away some permissions. The passport is re-issued.",
  offboard: "Retire the agent and revoke its passport permanently.",
};

function Tile({ k, v, tone, sub }: { k: string; v?: number; tone?: string; sub?: string }) {
  return (
    <div className="border-border bg-panel px-3 py-3 [&:not(:first-child)]:border-l">
      <div className={cn("font-mono text-[22px] font-medium tabular-nums", tone)}>{v ?? "–"}</div>
      <div className="text-[11.5px] text-muted-foreground">{k}</div>
      {sub && <div className="text-[10.5px] text-contradicted">{sub}</div>}
    </div>
  );
}

function AgentHistory({ agent: a }: { agent: Agent }) {
  const [view, setView] = useState<LedgerView | null>(null);
  const [failed, setFailed] = useState(false);
  const load = useCallback(() => {
    setFailed(false);
    api.ledger(a.agent_id).then(setView).catch(() => setFailed(true));
  }, [a.agent_id]);
  useEffect(load, [load, a.ledger_entries.length]);
  if (failed)
    return (
      <EmptyState icon={ShieldAlert} tone="bad" title="Couldn't load the history" action={<Button onClick={load}><RefreshCw className="size-3.5" /> Try again</Button>}>
        The backend didn&apos;t answer. Check that it is running, then try again.
      </EmptyState>
    );
  if (!view)
    return (
      <p className="inline-flex items-center gap-2 text-[12.5px] text-faint">
        <Loader2 className="size-3.5 animate-spin" /> Loading history…
      </p>
    );
  if (!view.entries.length) return <EmptyState icon={FileClock} title="No history yet">Entries appear here as soon as {a.name} is checked or does any work.</EmptyState>;
  return (
    <div className="max-w-[760px]">
      <LedgerTimeline entries={[...view.entries].reverse()} firstBad={view.first_bad_seq} />
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
  const [job, setJob] = useState(first ? "Sources candidates for open roles and drafts outreach" : "");
  const [runtime, setRuntime] = useState<"in-house" | "external">("in-house");
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
      const r = await api.onboard({ name, role: roleKey, sponsor: { ...sponsor, company_domain: sponsor.company_domain || null, title: sponsor.title || null }, scopes, days, job: job.trim() || undefined, runtime });
      setResult(r);
      onDone(r.agent.agent_id);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? "Admin token needed: add it with the key button at the top right." : err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    const ok = result.agent.status === "active";
    return (
      <div className="h-full overflow-y-auto p-6">
        {ok ? <ShieldCheck className="size-6 text-verified" /> : <ShieldAlert className="size-6 text-contradicted" />}
        <h2 className="mt-3 text-[18px] font-[600]">{ok ? `${result.agent.name} is on the team` : `${result.agent.name} starts suspended`}</h2>
        <p className="mt-1 text-[13px] text-muted-foreground">
          {ok
            ? `Passport issued. ${sponsor.name}'s identity, employment and authority all checked out against Crustdata.`
            : `The passport was issued, but ${sponsor.name} can't vouch for it right now, so it was revoked straight away.`}
        </p>
        <p className="mt-3 text-[12px] text-faint">
          {ok ? "Next: close this panel to see its passport, or try it in Verify passport and Send Guard." : "Next: fix the sponsor details and onboard again, or pick a sponsor Crustdata can vouch for."}
        </p>
        <VerdictList verdict={result.verdict} className="mt-4" />
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="flex h-full flex-col">
      <div className="flex-1 space-y-5 overflow-y-auto p-6">
        <div>
          <h2 className="text-[18px] font-[600] tracking-[-0.01em]">Onboard an AI employee</h2>
          <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">
            Fill this in from top to bottom. The agent gets a signed passport tied to a real person, its sponsor, who is checked in Crustdata
            as soon as you submit. If the check fails, the agent starts suspended.
          </p>
        </div>

        <Field label="Name">
          <input required value={name} onChange={(e) => setName(e.target.value)} className={inputCls} placeholder="Sourced" />
        </Field>

        <Field label="Job" hint="One line on what it does. Shown in the roster.">
          <input value={job} onChange={(e) => setJob(e.target.value)} className={inputCls} placeholder="Researches vendors before procurement calls" />
        </Field>

        <div>
          <span className="mb-1 block text-[12px] font-[510] text-muted-foreground">Where it runs</span>
          <div className="inline-flex rounded-md border border-border-strong bg-background p-0.5 text-[12px]">
            {(["in-house", "external"] as const).map((r) => (
              <button
                type="button"
                key={r}
                onClick={() => setRuntime(r)}
                className={cn("h-7 rounded px-3 font-[510] transition", runtime === r ? "bg-elevated text-foreground shadow-[0_0_0_1px_var(--border-strong)]" : "text-muted-foreground hover:text-foreground")}
              >
                {r === "in-house" ? "In-house" : "External (over MCP)"}
              </button>
            ))}
          </div>
        </div>

        <div>
          <span className="mb-0.5 block text-[12px] font-[510] text-muted-foreground">Role</span>
          <span className="mb-1.5 block text-[11px] text-faint">Sets the most this agent could ever be allowed to do.</span>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {roles.map((r) => (
              <button
                type="button"
                key={r.key}
                onClick={() => pickRole(r.key)}
                className={cn("rounded-lg border px-3 py-2 text-left transition", roleKey === r.key ? "border-primary/50 bg-primary/[0.06]" : "border-border-strong hover:bg-hover")}
              >
                <span className="block text-[13px] font-[510]">{r.title}</span>
                <span className="block text-[11.5px] leading-snug text-muted-foreground">{r.summary}</span>
              </button>
            ))}
          </div>
        </div>

        <div>
          <span className="mb-0.5 block text-[12px] font-[510] text-muted-foreground">Sponsor, the person it acts for</span>
          <span className="mb-1.5 block text-[11px] text-faint">Pick a sample person or enter a real one. Their LinkedIn URL is what Crustdata looks up.</span>
          {scenarios.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1">
              {scenarios.map((s) => (
                <button
                  type="button"
                  key={s.id}
                  title={s.story}
                  onClick={() => setSponsor(s.sponsor)}
                  className={cn(
                    "h-6 rounded-full border px-2 text-[11px] font-[510] transition",
                    sponsor.profile_url === s.sponsor.profile_url ? "border-primary/50 bg-primary/10 text-foreground" : "border-border-strong text-muted-foreground hover:text-foreground",
                  )}
                >
                  {s.sponsor.name} · {s.sponsor.company}
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
            return sc ? <p className="mt-1.5 text-[11.5px] text-faint">{sc.story}</p> : null;
          })()}
        </div>

        <div>
          <span className="mb-0.5 block text-[12px] font-[510] text-muted-foreground">Permissions</span>
          <span className="mb-1.5 block text-[11px] text-faint">Locked ones are outside this role. The sponsor&apos;s title must also allow each one.</span>
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

        {error && <p className="rounded-md border border-contradicted/30 bg-contradicted/[0.06] px-3 py-2 text-[12.5px] text-contradicted">{error}</p>}
      </div>
      <div className="flex items-center justify-end gap-2 border-t border-border p-4">
        <Button type="submit" variant="primary" disabled={busy || !scopes.length}>
          {busy ? <Loader2 className="size-3.5 animate-spin" /> : <IdCard className="size-3.5" />} Issue passport and check sponsor
        </Button>
      </div>
    </form>
  );
}
