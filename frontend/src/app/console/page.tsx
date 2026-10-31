"use client";
import Link from "next/link";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, ArrowUpRight, Play, KeyRound, Moon, Sun, ClipboardCheck, Link2, Loader2, Plus, RefreshCw, 
  Building2, LayoutDashboard, ShieldAlert, ShieldCheck, UserCog, Users, X,
} from "lucide-react";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { API_URL } from "@/lib/stream";
import { cn } from "@/lib/utils";
import {
  ApiError, api, runtime, getAdminToken, setAdminToken, type Agent, type Enrollment, type Role, type Scenario,
  type Verdict, type Workspace, type Me,
} from "./api";
import {
  AgentMark, Button, DecisionBadge, EmptyState, PageHead, RuntimeBadge, ScopeChip, StatusPill, TERMS, Term, ago, cardCls, until,
  checkLabel, inputCls, plain,
} from "./parts";
import { VerifyView } from "./verify";
import { GuardView } from "./guard";
import { LedgerExplorer } from "./ledger";
import { DemoView } from "./demo";
import { AgentDetail, FlashBar, OnboardForm, reasonText, type Flash, type Tab } from "./agent";
import { WorkView } from "./work";
import { MembersView } from "./members";
import { CompaniesView } from "./companies";
import { DashboardView } from "./dashboard";
import { AccountMenu } from "@/components/account-menu";
import { NotificationBell } from "@/components/notification-bell";
import { BrandMark } from "@/components/brand-mark";
import { BRAND, brandText } from "@/lib/brand";
import { AGENT_APPS, appFor } from "@/lib/apps";
import { Logo } from "@/components/app-header";

type Mode = "loading" | "live" | "offline";
type View = "home" | "companies" | "employees" | "work" | "verify" | "guard" | "ledger" | "members" | "demo";
export type Chain = { chain_ok: boolean; first_bad_seq: number | null; count: number };

type Group = "Platform" | "Workforce" | "Tools" | "Audit" | "Workspace" | "Learn";
const GROUPS: Group[] = ["Platform", "Workforce", "Tools", "Audit", "Workspace", "Learn"];

// The sidebar renders this list, grouped. Add a view here and it shows up in the nav.
// Passport checks and Send Guard live on each agent's page; "Check a passport" is for agents that contact you from outside.
const VIEWS: { v: View; label: string; icon: React.ElementType; desc: string; group: Group }[] = [
  { v: "companies", label: "Companies", icon: Building2, desc: "Every company on the platform, its people and its agents", group: "Platform" },
  { v: "home", label: "Dashboard", icon: LayoutDashboard, desc: "Every agent at a glance, what needs you, and the main actions", group: "Workforce" },
  { v: "employees", label: "Agents", icon: Users, desc: "Connect agents, check their passports, and manage their work", group: "Workforce" },
  { v: "work", label: "Live work", icon: Activity, desc: "Everything your agents are doing right now, and what's waiting for your approval", group: "Workforce" },
  { v: "verify", label: "Check a passport", icon: ShieldCheck, desc: "An agent from another company contacted you? Check whether it can be trusted", group: "Tools" },
  { v: "ledger", label: "Ledger", icon: Link2, desc: "The tamper-evident record of every check and decision", group: "Audit" },
  { v: "members", label: "Members", icon: UserCog, desc: "Who at your company can see and control agents, and their roles", group: "Workspace" },
  { v: "demo", label: "Guided demo", icon: Play, desc: "Watch six agents go through seven situations, with every decision and its source", group: "Learn" },
];

/** Which console views this person may open, from GET /api/auth/me -> access.views. The backend enforces the same lines. */
function allowed(v: View, me: Me | null): boolean {
  const a = me?.access;
  if (!a) return v !== "companies"; // no access info (older backend): everything but the platform view
  const has = (k: string) => a.views.includes(k);
  switch (v) {
    case "companies": return has("companies");
    case "employees": return has("agents") || has("my_agents");
    case "work": return has("work");
    case "ledger": return has("ledger");
    case "members": return has("members");
    case "demo": return a.level === "platform";
    default: return true; // Check a passport works for anyone
  }
}

/** A short name for the person's level, shown under the logo. */
function levelLabel(me: Me | null): string | undefined {
  const a = me?.access;
  if (!a) return me?.company?.name;
  if (a.level === "platform") return "Platform operator";
  if (a.level === "company") return `${me?.company?.name ?? "Your company"} · ${a.role}`;
  return `Your work · ${me?.company?.name ?? ""}`.replace(/ · $/, "");
}

export default function Console() {
  const [mode, setMode] = useState<Mode>("loading");
  const [view, setViewState] = useState<View>("home");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [chain, setChain] = useState<Chain>();
  const [selected, setSelected] = useState<string>();
  const [tab, setTabState] = useState<Tab>("work");
  const [busy, setBusy] = useState<string | null>(null);
  const [flash, setFlash] = useState<Flash>(null);
  const [payroll, setPayroll] = useState<{ verdicts: Verdict[]; suspended: string[] } | null>(null);
  const [onboarding, setOnboarding] = useState(false);
  const [ws, setWs] = useState<Workspace | null>(null);
  const [invites, setInvites] = useState<Enrollment[]>([]);
  const [pending, setPending] = useState(0);
  const [me, setMe] = useState<Me | null>(null);
  const own = me?.access?.level === "own_work";

  const setView = (v: View) => {
    setViewState(v);
    const u = new URL(window.location.href);
    u.searchParams.set("view", v);
    u.searchParams.delete("agent");
    u.searchParams.delete("tab");
    window.history.replaceState(null, "", u);
    if (v === "employees") setSelected(undefined);
  };

  const refresh = useCallback(async () => {
    // Recruiters can't read the ledger (403), so the chain badge is simply left out for them.
    const [list, l] = await Promise.all([api.agents(), api.ledger().catch(() => null)]);
    api.enrollments().then(setInvites).catch(() => setInvites([]));
    runtime.state().then((st) => setPending(st.approvals.pending.length)).catch(() => setPending(0));
    setAgents(list);
    setChain(l ? { chain_ok: l.chain_ok, first_bad_seq: l.first_bad_seq, count: l.entries.length } : undefined);
    return list;
  }, []);

  const connect = useCallback(() => {
    setMode("loading");
    api.workspace().then(setWs).catch(() => setWs(null));
    api.me().then(setMe).catch(() => setMe(null));
    Promise.all([refresh(), api.roles(), api.scenarios().catch(() => [])])
      .then(([, r, s]) => {
        setRoles(r.roles);
        setScenarios(s);
        setMode("live");
      })
      .catch(() => setMode("offline"));
  }, [refresh]);

  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const v = q.get("view") as View | null;
    // Old links to the Send Guard page land on the agents list, where each agent has its own Messages tab.
    if (v && VIEWS.some((x) => x.v === v)) setViewState(v);
    const id = q.get("agent");
    if (id) {
      setSelected(id);
      setViewState("employees");
      const t = q.get("tab") as Tab | null;
      if (t) setTabState(t);
    }
    connect();
  }, [connect]);

  /** Opens an agent's page (or the list, with no id) and keeps it in the URL so it can be shared and reloaded. */
  const openAgent = (id?: string, t: Tab = "work") => {
    setSelected(id);
    setTabState(t);
    setViewState("employees");
    const u = new URL(window.location.href);
    u.searchParams.delete("view");
    if (id) {
      u.searchParams.set("agent", id);
      if (t !== "work" && t !== "overview") u.searchParams.set("tab", t);
      else u.searchParams.delete("tab");
    } else {
      u.searchParams.delete("agent");
      u.searchParams.delete("tab");
    }
    window.history.replaceState(null, "", u);
    window.scrollTo({ top: 0 });
  };
  const setTab = (t: Tab) => openAgent(selected, t);

  // ?agent= takes an id, or an agent's name (so other apps can link to "/console?agent=Sourced").
  const cur = agents.find((a) => a.agent_id === selected) ?? agents.find((a) => !!selected && a.name.toLowerCase() === selected.toLowerCase());
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
          ? { tone: "bad", title: "Log in first", body: "This backend only lets signed-in people (or the admin token, under the key button) make changes." }
          : { tone: "bad", title: err.status === 403 ? "Your role can't do this" : "Couldn't do that", body: err.message, verdict: err.verdict },
      );
    } finally {
      setBusy(null);
    }
  };

  const startOnboarding = () => setOnboarding(true);

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
    <div className="min-h-screen lg:grid lg:grid-cols-[232px_minmax(0,1fr)]">
      <Sidebar view={view} setView={setView} mode={mode} chain={chain} counts={counts} agents={agents} ws={ws} pending={pending} me={me} onConnect={startOnboarding}
        current={view === "employees" ? cur?.agent_id : undefined} onPick={(id) => openAgent(id)} />

      <div className="min-w-0">
        {mode === "offline" ? (
          <Offline onRetry={connect} />
        ) : mode === "loading" ? (
          <div className="grid min-h-[70vh] place-items-center text-[13px] text-faint">
            <span className="inline-flex items-center gap-2">
              <Loader2 className="size-4 animate-spin" /> Connecting to {BRAND.name}…
            </span>
          </div>
        ) : !allowed(view, me) ? (
          <NotYours onBack={() => setView("employees")} label={levelLabel(me)} />
        ) : view === "home" && !cur ? (
          <DashboardView agents={agents} chain={chain} pending={pending} access={me?.access} company={me?.company?.name}
            onConnect={startOnboarding} onPick={(id) => openAgent(id)} onGo={(v) => setView(v)} />
        ) : view === "companies" ? (
          <CompaniesView onPick={(id) => openAgent(id)} onChanged={refresh} />
        ) : view === "work" ? (
          <WorkView onChanged={refresh} />
        ) : view === "verify" ? (
          <VerifyView agents={agents} scenarios={scenarios} onOnboard={startOnboarding} />
        ) : view === "guard" ? (
          <GuardView agents={agents} onSent={refresh} onOnboard={startOnboarding} />
        ) : view === "members" ? (
          <MembersView ws={ws} />
        ) : view === "demo" ? (
          <DemoView onChanged={refresh} onOpen={setView} />
        ) : view === "ledger" ? (
          <LedgerExplorer agents={agents} onChain={setChain} onOnboard={startOnboarding} />
        ) : cur ? (
          <AgentDetail
            key={cur.agent_id}
            agent={cur}
            agents={agents}
            role={roles.find((r) => r.title === cur.role)}
            scenarios={scenarios}
            tab={tab}
            setTab={setTab}
            busy={busy}
            act={act}
            flash={flash}
            onFlashClose={() => setFlash(null)}
            onBack={() => openAgent(undefined)}
            onChanged={refresh}
            access={me?.access}
          />
        ) : (
          <main className="mx-auto max-w-[1320px] px-4 pb-16 pt-6 sm:px-8 sm:pt-8">
            <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
              {own ? (
                <PageHead title="My agents">
                  The agents your company has given you to work with. Give them tasks and approve what they want to send. Your company&apos;s admins
                  connect agents and decide who works with which.
                </PageHead>
              ) : (
              <PageHead title="Agents">
                The AI agents that act for your company. Each one carries a <Term tip={TERMS.passport}>passport</Term> naming the real person it works
                for, and is trusted only while Crustdata confirms that <Term tip={TERMS.sponsor}>sponsor</Term> still works here and can delegate the job.
              </PageHead>
              )}
              {!own && <div className="flex shrink-0 items-center gap-2">
                <Button
                  onClick={runPayroll}
                  disabled={busy === "payroll" || !agents.length}
                  title="Looks up every sponsor in Crustdata again and suspends any agent whose sponsor has left or lost authority"
                >
                  {busy === "payroll" ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
                  Re-check sponsors
                </Button>
                <Button variant="primary" onClick={() => setOnboarding(true)} title="Give a new agent a passport, vouched for by a real person at your company">
                  <Plus className="size-3.5" /> Connect an agent
                </Button>
              </div>}
            </div>

            {agents.length > 0 && !own && <Flow />}

            {agents.length > 0 && (
              <div className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-2 text-[12.5px] text-muted-foreground tabular-nums">
                <Count dot="bg-verified" n={counts.active ?? 0} label="active" />
                <Count dot="bg-contradicted" n={counts.suspended ?? 0} label="suspended" />
                <Count dot="bg-faint" n={counts.offboarded ?? 0} label="offboarded" />
                <span className="ml-auto text-[12px] text-faint">Click an agent to open it</span>
              </div>
            )}

            {flash && <FlashBar flash={flash} onClose={() => setFlash(null)} />}
            {payroll && <PayrollBanner run={payroll} agents={agents} onClose={() => setPayroll(null)} onPick={(id) => openAgent(id)} />}

            <div className={cn(cardCls, "mt-3 overflow-hidden")}>
              {!agents.length && own ? (
                <EmptyState icon={Users} title="No agents assigned to you yet">
                  Ask your company admin to give you one. They do it from the agent&apos;s page in {BRAND.name}.
                </EmptyState>
              ) : !agents.length ? (
                <EmptyState
                  icon={Users}
                  title="No agents yet"
                  action={
                    <Button variant="primary" onClick={() => setOnboarding(true)}>
                      <Plus className="size-3.5" /> Connect Sourced as your first agent
                    </Button>
                  }
                >
                  Connecting an agent gives it a passport and checks the person who vouches for it in Crustdata straight away. Start with Sourced, the hiring agent.
                </EmptyState>
              ) : (
                <AgentTable agents={agents} onPick={(id) => openAgent(id)} />
              )}
            </div>

            {(!me?.access || me.access.views.includes("enrollments")) && <Invites invites={invites} onRevoke={(id) => act(`inv:${id}`, () => api.revokeEnrollment(id), () => ({ tone: "ok", title: "Invite cancelled", body: "That one-time command no longer works." }))} busy={busy} />}
          </main>
        )}
      </div>

      <Sheet open={onboarding} onOpenChange={setOnboarding}>
        <SheetContent className="border-border bg-panel sm:max-w-xl">
          <SheetTitle className="sr-only">Connect an agent</SheetTitle>
          <OnboardForm
            roles={roles}
            scenarios={scenarios}
            first={!agents.length}
            onDone={async () => {
              await refresh();
            }}
            onOpen={(agentId) => {
              setOnboarding(false);
              openAgent(agentId);
            }}
          />
        </SheetContent>
      </Sheet>
    </div>
  );
}

/** The whole job in four steps, so a first-time user sees how the pieces fit before clicking anything. */
function Flow() {
  const steps = [
    ["Connect", "Give an agent a passport. A real person at your company vouches for it."],
    ["Check", "Its sponsor is looked up in Crustdata now, and again on every payroll run."],
    ["Put to work", "Assign tasks. Every message it drafts passes Send Guard, and you approve sends."],
    ["Audit", "Each check and decision lands on the ledger, so you can prove later what happened."],
  ];
  return (
    <ol className="mt-6 grid gap-px overflow-hidden rounded-xl border border-border bg-border sm:grid-cols-4">
      {steps.map(([t, d], i) => (
        <li key={t} className="bg-panel px-4 py-3">
          <p className="flex items-center gap-2 text-[12.5px] font-[590]">
            <span className="grid size-5 place-items-center rounded-full bg-elevated font-mono text-[10.5px] text-muted-foreground">{i + 1}</span>
            {t}
          </p>
          <p className="mt-1 text-[12px] leading-snug text-muted-foreground">{d}</p>
        </li>
      ))}
    </ol>
  );
}

function Count({ dot, n, label }: { dot: string; n: number; label: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5", !n && "text-faint")}>
      <span className={cn("size-1.5 rounded-full", n ? dot : "bg-border-strong")} />
      <b className="font-[590] text-foreground">{n}</b> {label}
    </span>
  );
}

// ---- shell -----------------------------------------------------------------------------------

function Sidebar({
  view, setView, mode, chain, counts, agents, ws, pending, current, onPick, me, onConnect,
}: {
  view: View; setView: (v: View) => void; mode: Mode; chain?: Chain; counts: Record<string, number>; agents: Agent[]; ws: Workspace | null;
  pending: number; current?: string; onPick: (id: string) => void; me: Me | null; onConnect: () => void;
}) {
  const badge = (v: View) =>
    v === "employees" ? (agents.length ? String(agents.length) : undefined)
      : v === "work" ? (pending ? `${pending} waiting` : undefined)
      : v === "ledger" && chain ? (chain.chain_ok ? String(chain.count) : "broken") : undefined;
  const apps = Object.values(AGENT_APPS).filter((a) => !me?.access || me.access.views.includes(a.name.toLowerCase()));
  const views = VIEWS.filter((x) => allowed(x.v, me));
  return (
    <aside className="sticky top-0 z-30 flex flex-col border-b border-border bg-elevated/70 backdrop-blur-xl lg:h-screen lg:border-b-0 lg:border-r lg:bg-elevated/40">
      <div className="flex h-12 items-center justify-between gap-2 px-4 lg:h-14">
        <span className="flex min-w-0 items-center gap-2" title={`${BRAND.name}: ${BRAND.tagline.toLowerCase()}. Checks that every AI agent is vouched for by a real person before anyone trusts it.`}>
          <BrandMark />
          <span className="min-w-0 leading-none">
            <span className="block text-[14px] font-[620] tracking-[-0.01em]">{BRAND.name}</span>
            <span className="mt-0.5 hidden truncate text-[11px] text-faint lg:block" title={me?.access?.summary}>{levelLabel(me) ?? ws?.company?.name ?? BRAND.tagline}</span>
          </span>
        </span>
        <div className="flex items-center gap-1 lg:hidden">
          <AdminToken />
          <NotificationBell />
          <ThemeToggle />
          <AccountMenu />
        </div>
      </div>

      <nav className="flex gap-0.5 overflow-x-auto px-3 pb-2 lg:mt-2 lg:flex-1 lg:flex-col lg:gap-4 lg:overflow-y-auto lg:pb-4" aria-label={BRAND.name}>
        {GROUPS.filter((g) => views.some((x) => x.group === g)).map((g) => (
          <div key={g} className="flex gap-0.5 lg:flex-col">
            <p className="hidden px-2 pb-1 text-[11px] font-[510] text-faint lg:block">{g}</p>
            {views.filter((x) => x.group === g).map((x) => (
              <Fragment key={x.v}>
                <NavItem {...x} label={x.v === "employees" && me?.access?.level === "own_work" ? "My agents" : x.label} badge={badge(x.v)} bad={x.v === "ledger" && chain ? !chain.chain_ok : false}
                  alert={x.v === "employees" && !!counts.suspended ? `${counts.suspended} suspended` : x.v === "work" && pending ? `${pending} sends waiting for your approval` : undefined}
                  active={view === x.v && !(x.v === "employees" && current)} onClick={() => setView(x.v)} />
                {x.v === "employees" && agents.length > 0 && (
                  <ul className="ml-[15px] hidden border-l border-border pl-2 lg:block" aria-label="Your agents">
                    {agents.filter((a) => a.status !== "offboarded").slice(0, 8).map((a) => (
                      <li key={a.agent_id}>
                        <button
                          onClick={() => onPick(a.agent_id)}
                          aria-current={current === a.agent_id ? "page" : undefined}
                          title={`${a.name}: ${a.status}${a.reason ? `. ${plain(a.reason)}` : ""}`}
                          className={cn(
                            "flex h-7 w-full items-center gap-2 rounded-md px-2 text-left text-[12.5px] transition",
                            current === a.agent_id ? "bg-panel font-[510] text-foreground shadow-[var(--shadow)]" : "text-muted-foreground hover:bg-hover hover:text-foreground",
                          )}
                        >
                          <span className={cn("size-1.5 shrink-0 rounded-full", a.status === "active" ? "bg-verified" : "bg-contradicted")} />
                          <span className="truncate">{a.name}</span>
                          {appFor(a) && <span className="ml-auto text-[10.5px] text-faint">app</span>}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </Fragment>
            ))}
            {g === "Workforce" && me?.access?.level !== "own_work" && (
              <button onClick={onConnect} title="Give a new agent a passport, vouched for by a real person at your company"
                className="group inline-flex h-8 shrink-0 items-center gap-2 rounded-md px-2 text-[13px] font-[510] text-primary transition hover:bg-primary/10 lg:w-full">
                <Plus className="size-4 shrink-0" /> <span className="truncate">Connect an agent</span>
              </button>
            )}
          </div>
        ))}
        {apps.map((app) => (
          <Link key={`m-${app.href}`} href={app.href} prefetch={false} className="inline-flex h-8 shrink-0 items-center gap-2 rounded-md px-2 text-[13px] text-muted-foreground hover:bg-hover hover:text-foreground lg:hidden">
            <Logo /> {app.name}
          </Link>
        ))}
        {apps.length > 0 && (
          <div className="hidden lg:flex lg:flex-col lg:gap-0.5">
            <p className="px-2 pb-1 text-[11px] font-[510] text-faint">Agent apps</p>
            {apps.map((app) => (
              <div key={app.href}>
                <Link href={app.href} prefetch={false} title={app.what}
                  className="group flex h-8 items-center gap-2 rounded-md px-2 text-[13px] text-muted-foreground transition hover:bg-hover hover:text-foreground">
                  <Logo />
                  <span className="truncate">{app.name}</span>
                  <ArrowUpRight className="ml-auto size-3.5 text-faint opacity-0 transition group-hover:opacity-100" />
                </Link>
                <ul className="ml-[15px] border-l border-border pl-2">
                  {app.pages.map((pg) => (
                    <li key={pg.href}>
                      <Link href={pg.href} prefetch={false} title={pg.what}
                        className="flex h-7 items-center rounded-md px-2 text-[12.5px] text-muted-foreground transition hover:bg-hover hover:text-foreground">
                        {pg.label}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </nav>

      <div className="hidden border-t border-border p-3 lg:block">
        {ws && <AccessNote ws={ws} />}
        {/* relative: the token and account popovers open upward across this whole row, so they stay inside the sidebar */}
        <div className="relative mt-2 flex items-center justify-between gap-2 px-1">
          <BackendDot mode={mode} />
          <div className="flex items-center gap-0.5">
            <AdminToken up />
            <NotificationBell up />
            <ThemeToggle />
            <AccountMenu up />
          </div>
        </div>
      </div>
    </aside>
  );
}

/** How this console is protected, from GET /api/workspace. Open access is called out, because anyone on the network could act. */
function AccessNote({ ws }: { ws: Workspace }) {
  if (ws.auth_mode === "open")
    return (
      <p
        className="mt-2 flex items-start gap-1.5 rounded-md border border-flag/30 bg-flag/[0.07] px-2 py-1.5 text-[11.5px] leading-snug text-secondary"
        title="The backend is running without a login. Start it with AGAXES_REQUIRE_LOGIN=1 (or set an admin token) before real use."
      >
        <ShieldAlert className="mt-px size-3.5 shrink-0 text-flag" />
        <span><b className="font-[590]">Open access.</b> Anyone on this network can control agents.</span>
      </p>
    );
  const who = ws.via === "session" ? ws.role === "operator" ? "You're the platform operator" : `You're ${ws.role === "admin" || ws.role === "owner" ? "an" : "a"} ${ws.role}` : ws.via === "admin_token" ? "Using the admin token" : "Read-only";
  return (
    <p className="mt-2 flex items-center gap-1.5 px-2 text-[11.5px] text-muted-foreground" title={ws.auth_mode === "login_required" ? "Everyone must log in, and their role decides what they can do." : "Changes need a login or the admin token. Anyone can read."}>
      <ShieldCheck className="size-3.5 shrink-0 text-verified" />
      <span className="truncate">{ws.auth_mode === "login_required" ? "Login required" : "Changes need a login"} · {who}</span>
    </p>
  );
}

/** Outside agents invited with a one-time command that haven't connected yet. */
function Invites({ invites, onRevoke, busy }: { invites: Enrollment[]; onRevoke: (id: string) => void; busy: string | null }) {
  const pending = invites.filter((i) => i.status === "pending");
  if (!pending.length) return null;
  return (
    <section className="mt-8">
      <h3 className="text-[14px] font-[590]">Waiting to connect ({pending.length})</h3>
      <p className="mt-0.5 text-[12px] text-muted-foreground">Outside agents you invited. Each one gets its passport when it runs its one-time command and proves it holds its own key.</p>
      <ul className={cn(cardCls, "mt-3 divide-y divide-border")}>
        {pending.map((i) => (
          <li key={i.enrollment_id} className="flex flex-wrap items-center gap-3 px-4 py-3">
            <span className="min-w-0 flex-1">
              <span className="block text-[13.5px] font-[510]">{i.name} <span className="font-normal text-muted-foreground">· for {i.sponsor.name}, {i.sponsor.company}</span></span>
              <span className="block text-[12px] text-muted-foreground">Invited by {i.created_by} {ago(i.created_at)} · command expires {until(i.expires_at)}</span>
            </span>
            <Button variant="ghost" onClick={() => onRevoke(i.enrollment_id)} disabled={!!busy}>
              {busy === `inv:${i.enrollment_id}` ? <Loader2 className="size-3.5 animate-spin" /> : <X className="size-3.5" />} Cancel invite
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function NotYours({ onBack, label }: { onBack: () => void; label?: string }) {
  return (
    <main className="mx-auto max-w-[560px] px-4 py-24">
      <ShieldAlert className="size-5 text-muted-foreground" />
      <h1 className="mt-3 text-[20px] font-[620] tracking-[-0.02em]">This page isn&apos;t part of your access</h1>
      <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">
        You&apos;re signed in as {label ?? "a member"}. Your company&apos;s admins can change what you can see.
      </p>
      <Button className="mt-5" onClick={onBack}>Back to your agents</Button>
    </main>
  );
}

function BackendDot({ mode }: { mode: Mode }) {
  return (
    <span
      className="inline-flex min-w-0 items-center gap-1.5 text-[11.5px] text-muted-foreground"
      title={mode === "live" ? `Connected to the backend at ${API_URL}. Everything here is real data.` : `Can't reach the backend at ${API_URL}`}
    >
      <span className={cn("size-1.5 shrink-0 rounded-full", mode === "live" ? "bg-verified" : mode === "offline" ? "bg-contradicted" : "animate-pulse bg-faint")} />
      <span className="truncate">{mode === "loading" ? "Connecting" : mode === "live" ? "Connected" : "Offline"}</span>
    </span>
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

function AdminToken({ up }: { up?: boolean }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [has, setHas] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => setHas(!!getAdminToken()), []);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    // In the sidebar footer (up) the popover anchors to the footer row, not this button, so it can't run off the left edge.
    <div ref={ref} className={up ? undefined : "relative"}>
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
          className={cn(cardCls, up ? "absolute inset-x-0 bottom-9 z-40 p-3 shadow-lg animate-fade" : "absolute right-0 top-9 z-40 w-72 max-w-[calc(100vw-2rem)] p-3 shadow-lg animate-fade")}
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

function NavItem({
  label, icon: I, desc, active, onClick, badge, bad,
  alert,
}: { label: string; icon: React.ElementType; desc: string; active: boolean; onClick: () => void; badge?: string; bad?: boolean; alert?: string }) {
  return (
    <button
      onClick={onClick}
      title={desc}
      aria-current={active ? "page" : undefined}
      className={cn(
        "group inline-flex h-8 shrink-0 items-center gap-2 rounded-md px-2 text-[13px] transition lg:w-full",
        active ? "bg-panel font-[510] text-foreground shadow-[var(--shadow)]" : "text-muted-foreground hover:bg-hover hover:text-foreground",
      )}
    >
      <I className={cn("size-4 shrink-0", active ? "text-foreground" : "text-faint group-hover:text-muted-foreground")} />
      <span className="truncate">{label}</span>
      {alert && <span className="size-1.5 shrink-0 rounded-full bg-contradicted" title={alert} aria-label={alert} />}
      {badge && (
        <span className={cn("ml-auto hidden font-mono text-[10.5px] tabular-nums lg:inline", bad ? "text-contradicted" : "text-faint")}>{badge}</span>
      )}
    </button>
  );
}

function Offline({ onRetry }: { onRetry: () => void }) {
  return (
    <main className="mx-auto max-w-[560px] px-4 py-24">
      <ShieldAlert className="size-5 text-contradicted" />
      <h1 className="mt-3 text-[20px] font-[620] tracking-[-0.02em]">Can&apos;t reach the {BRAND.name} backend</h1>
      <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted-foreground">
        This console only shows real state: every passport, check and ledger entry comes from the backend at{" "}
        <span className="font-mono text-[12.5px] text-secondary">{API_URL}</span>. Start it, then retry.
      </p>
      <pre className="mt-5 overflow-x-auto rounded-lg border border-border bg-elevated p-3 font-mono text-[12px] leading-relaxed text-secondary">
        {"cd backend\nuvicorn app.main:app --reload --port 8000"}
      </pre>
      <Button variant="primary" onClick={onRetry} className="mt-4">
        <RefreshCw className="size-3.5" /> Retry
      </Button>
    </main>
  );
}

// ---- list ------------------------------------------------------------------------------------


function AgentTable({ agents, onPick }: { agents: Agent[]; onPick: (id: string) => void }) {
  const selected: string | undefined = undefined;
  const compact = false;
  return (
    <table className="w-full table-fixed text-left">
      <thead>
        <tr className="border-b border-border text-[11.5px] text-faint">
          <th className="px-4 py-2 font-[510]">Agent</th>
          {!compact && <th className="hidden w-[24%] px-3 py-2 font-[510] md:table-cell">Acts for</th>}
          {!compact && <th className="hidden w-[22%] px-3 py-2 font-[510] 2xl:table-cell">Permissions</th>}
          <th className="w-[104px] px-3 py-2 font-[510]">Status</th>
          {!compact && <th className="hidden w-[112px] px-4 py-2 text-right font-[510] sm:table-cell">Last check</th>}
        </tr>
      </thead>
      <tbody>
        {agents.map((a) => {
          const s = a.passport.sponsor;
          const on = a.agent_id === selected;
          return (
            <tr
              key={a.agent_id}
              onClick={() => onPick(a.agent_id)}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onPick(a.agent_id))}
              tabIndex={0}
              aria-selected={on}
              className={cn(
                "group cursor-pointer border-b border-border outline-none transition-colors last:border-0 focus-visible:bg-hover",
                on ? "bg-primary/[0.05]" : "hover:bg-hover",
                a.status === "offboarded" && "text-muted-foreground",
              )}
            >
              <td className="relative px-4 py-3">
                {on && <span className="absolute inset-y-0 left-0 w-0.5 bg-primary" />}
                <div className="flex min-w-0 items-center gap-3">
                  <AgentMark agent={a} />
                  <div className="min-w-0">
                    <p className="flex items-baseline gap-1.5">
                      <span className="truncate text-[13.5px] font-[590]">{a.name}</span>
                      <RuntimeBadge runtime={a.runtime} />
                    </p>
                    <p className="truncate text-[12px] text-muted-foreground">
                      {a.status !== "active" && a.reason ? (
                        <span className={a.status === "suspended" ? "text-contradicted" : undefined}>{reasonText(a.reason)}</span>
                      ) : (
                        brandText(a.job) || a.role
                      )}
                    </p>
                  </div>
                </div>
              </td>
              {!compact && (
                <td className="hidden px-3 py-3 md:table-cell">
                  <p className="truncate text-[13px]">{s.name}</p>
                  <p className="truncate text-[12px] text-muted-foreground">{[s.title, s.company].filter(Boolean).join(", ")}</p>
                </td>
              )}
              {!compact && (
                <td className="hidden px-3 py-3 2xl:table-cell">
                  <span className="flex flex-wrap gap-1">{a.passport.scopes.map((sc) => <ScopeChip key={sc} scope={sc} muted={a.status === "offboarded"} />)}</span>
                </td>
              )}
              <td className="px-3 py-3"><StatusPill status={a.status} /></td>
              {!compact && <td className="hidden px-4 py-3 text-right text-[12px] text-muted-foreground tabular-nums sm:table-cell">{ago(a.last_checked)}</td>}
            </tr>
          );
        })}
      </tbody>
    </table>
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
