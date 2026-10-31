"use client";
import Link from "next/link";
import { BRAND, brandText } from "@/lib/brand";
import { appFor } from "@/lib/apps";
import { Logo } from "@/components/app-header";
import { useCallback, useEffect, useState } from "react";
import {
  ArrowLeft, Ban, Check, Copy, FileClock, IdCard, KeyRound, Loader2, Plus, RefreshCw, RotateCcw, ShieldAlert, ShieldCheck, UserMinus, X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  ApiError, SCOPE_INFO, api, type Access, type Agent, type Member, type LedgerView, type ReviewDecision, type Role, type Scenario, type Scope, type Sponsor,
  type Verdict,
} from "./api";
import {
  AgentMark, Button, DecisionBadge, EmptyState, Field, RuntimeBadge, ScopeChip, ScopeToggle, SectionHead, StatusPill, VerdictList, ago, cardCls,
  checkLabel, day, inputCls, plain, until
} from "./parts";
import { ExportButtons, LedgerTimeline } from "./ledger";
import { GuardView } from "./guard";
import { WorkView } from "./work";

export type Tab = "overview" | "passport" | "messages" | "work" | "reviews" | "ledger";
export type Flash = { tone: "ok" | "bad" | "info"; title: string; body?: string; verdict?: Verdict } | null;
export type Act = <T>(key: string, fn: () => Promise<T>, ok?: (r: T) => Flash) => Promise<T | undefined>;
const ALL_SCOPES = Object.keys(SCOPE_INFO) as Scope[];

/** Suspension reasons arrive as "check_name: detail"; show the check's plain name instead of its id. */
export const reasonText = (r?: string | null) => plain(r);

export function FlashBar({ flash, onClose }: { flash: NonNullable<Flash>; onClose: () => void }) {
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

// Work first: it's what you come to an agent's page to do. Trust (Passport, Messages) next, then the record.
// "overview" is kept in the Tab type so old links (?tab=overview) still open, on Work.
const TABS: { k: Tab; label: string; what: string }[] = [
  { k: "work", label: "Work", what: "What it's doing, what's waiting on you, and every task it finished" },
  { k: "passport", label: "Passport", what: "Who vouches for it, its signed ID and what it may do. Check it live against Crustdata" },
  { k: "messages", label: "Messages", what: "Every message it tried to send and what Send Guard decided. Try one yourself" },
  { k: "ledger", label: "History", what: "Every ledger entry about it, with the Crustdata sources behind each one" },
  { k: "reviews", label: "Reviews", what: "Its track record, and your keep, restrict or offboard decisions" },
];

export function AgentDetail({
  agent: a, agents, role, tab: tab0, setTab, busy, act, flash, onFlashClose, onBack, onChanged, access,
}: {
  agent: Agent; agents: Agent[]; role?: Role; scenarios: Scenario[]; tab: Tab; setTab: (t: Tab) => void; busy: string | null; act: Act;
  flash: Flash; onFlashClose: () => void; onBack: () => void; onChanged: () => void; access?: Access;
}) {
  // A recruiter works with the agent; changing it (sponsor checks, suspend, reviews) and its full history are for admins.
  const own = access?.level === "own_work";
  const tab: Tab = tab0 === "overview" ? "work" : tab0;
  const tabs = own ? TABS.filter((t) => t.k !== "ledger" && t.k !== "reviews") : TABS;
  const [confirm, setConfirm] = useState<"suspend" | "offboard" | null>(null);
  const [reason, setReason] = useState("");
  const gone = a.status === "offboarded";
  const s = a.passport.sponsor;

  const recheck = () =>
    act("recheck", () => api.recheck(a.agent_id), (r) =>
      r.verdict.decision === "allow"
        ? { tone: "ok", title: "Still trusted", body: `${s.name} still vouches for ${a.name}. Every check passed.` }
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
    <main className="mx-auto max-w-[1120px] px-4 pb-20 pt-5 sm:px-8 sm:pt-7">
      <nav className="flex items-center gap-1.5 text-[12.5px] text-muted-foreground" aria-label="Breadcrumb">
        <button onClick={onBack} className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 -ml-1.5 hover:bg-hover hover:text-foreground">
          <ArrowLeft className="size-3.5" /> {own ? "My agents" : "Agents"}
        </button>
        <span className="text-faint">/</span>
        <span className="truncate text-foreground">{a.name}</span>
      </nav>

      <header className="mt-5 flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3.5">
          <AgentMark agent={a} size="lg" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-[22px] font-[620] tracking-[-0.02em]">{a.name}</h1>
              <StatusPill status={a.status} />
              <RuntimeBadge runtime={a.runtime} />
            </div>
            <p className="mt-0.5 text-[13px] text-muted-foreground">
              {a.role} · acts for <span className="text-secondary">{s.name}</span>, {s.title ? `${s.title} at ` : ""}{s.company}
            </p>
          </div>
        </div>
        {!gone && (
          <div className="flex flex-wrap items-center gap-1.5">
            {appFor(a) && (
              <Link href={appFor(a)!.href} prefetch={false} title={appFor(a)!.what}
                className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border-strong bg-panel px-3 text-[13px] font-[510] transition hover:bg-hover">
                <Logo /> Open {appFor(a)!.name}
              </Link>
            )}
            {a.status === "active" && tab !== "work" && (
              <Button variant="primary" onClick={() => setTab("work")} title="Open its Work tab to assign a task">
                <Plus className="size-3.5" /> Give it work
              </Button>
            )}
            {!own && <>
            <Button onClick={recheck} disabled={!!busy} title={`Look up ${s.name} in Crustdata now. If they have left or lost authority, ${a.name} is suspended.`}>
              {busy === "recheck" ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />} Re-check sponsor
            </Button>
            {a.status === "suspended" ? (
              <Button onClick={reinstate} disabled={!!busy} title="Run a fresh sponsor check. If it passes, the passport is valid again.">
                {busy === "reinstate" ? <Loader2 className="size-3.5 animate-spin" /> : <RotateCcw className="size-3.5" />} Reinstate
              </Button>
            ) : (
              <Button variant="ghost" onClick={() => setConfirm("suspend")} disabled={!!busy} title="Stop it now: its passport is revoked until you reinstate it">
                <Ban className="size-3.5" /> Suspend
              </Button>
            )}
            <Button variant="ghost" className="text-contradicted hover:bg-contradicted/10 hover:text-contradicted" onClick={() => setConfirm("offboard")} disabled={!!busy} title="Retire it for good: its passport is revoked permanently">
              <UserMinus className="size-3.5" /> Offboard
            </Button>
            </>}
          </div>
        )}
      </header>

      {confirm && (
        <div className={cn(cardCls, "mt-5 p-4 animate-rise", confirm === "offboard" && "border-contradicted/35")}>
          <p className="text-[13.5px] font-[590]">{confirm === "suspend" ? `Suspend ${a.name}?` : `Offboard ${a.name}? This can't be undone.`}</p>
          <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">
            {confirm === "suspend"
              ? "Its passport is revoked right away, so anyone who checks it, and Send Guard, will refuse it. Its running task stops. You can reinstate it after a fresh sponsor check."
              : "Its passport is revoked permanently and it leaves the active roster. Its history stays on the ledger."}{" "}
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

      {flash && <FlashBar flash={flash} onClose={onFlashClose} />}

      <TrustStrip agent={a} />

      <nav className="mt-6 flex gap-5 overflow-x-auto border-b border-border" role="tablist">
        {tabs.map((t) => (
          <button
            key={t.k}
            role="tab"
            aria-selected={tab === t.k}
            title={t.what}
            onClick={() => setTab(t.k)}
            className={cn(
              "-mb-px inline-flex h-9 shrink-0 items-center gap-1.5 border-b-[1.5px] px-0.5 text-[13px] transition",
              tab === t.k ? "border-foreground font-[510] text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {t.label}
            {t.k === "reviews" && a.reviews.length > 0 && <span className="font-mono text-[10.5px] text-faint">{a.reviews.length}</span>}
          </button>
        ))}
      </nav>
      <p className="mt-3 text-[12.5px] text-muted-foreground">{TABS.find((t) => t.k === tab)?.what}.</p>

      <div className="mt-6 animate-fade" key={tab}>
        {tab === "passport" && (
          <div className="space-y-10">
            <AgentFacts agent={a} />
            {access?.level === "company" && <Assignees agent={a} onChanged={onChanged} />}
            <PassportTab agent={a} />
            <PassportCheck agent={a} onChecked={onChanged} />
            <div>
              <SectionHead title="What it may do">Two things limit it: its role, and what its sponsor is allowed to delegate.</SectionHead>
              <div className="mt-3"><PermissionsTab agent={a} role={role} busy={busy} act={act} /></div>
            </div>
          </div>
        )}
        {tab === "messages" && <GuardView agents={agents} lockedAgentId={a.agent_id} onSent={onChanged} onOnboard={() => {}} />}
        {tab === "work" && (
          <>
            <WorkView agentId={a.agent_id} onChanged={onChanged} />
            {appFor(a) && <div className="mt-10"><AppCard agent={a} /></div>}
          </>
        )}
        {tab === "reviews" && <ReviewsTab agent={a} busy={busy} act={act} />}
        {tab === "ledger" && <AgentHistory agent={a} />}
      </div>
    </main>
  );
}

/** One line above the tabs: can you trust it right now, and why. The full checks are on the Passport tab. */
function TrustStrip({ agent: a }: { agent: Agent }) {
  const s = a.passport.sponsor;
  const v = a.last_verdict;
  const trusted = a.status === "active" && v?.decision !== "block";
  const fail = v?.checks.find((c) => c.status === "fail") ?? v?.checks.find((c) => c.status !== "pass");
  return (
    <section className={cn("mt-5 flex items-start gap-2.5 rounded-lg border px-3.5 py-2.5",
      trusted ? "border-verified/30 bg-verified/[0.05]" : "border-contradicted/30 bg-contradicted/[0.05]")}>
      {trusted ? <ShieldCheck className="mt-px size-4 shrink-0 text-verified" /> : <ShieldAlert className="mt-px size-4 shrink-0 text-contradicted" />}
      <p className="min-w-0 text-[12.5px] leading-snug text-secondary">
        <b className="font-[590] text-foreground">
          {a.status === "offboarded" ? "Offboarded." : trusted ? "Trusted right now." : "Not trusted right now."}
        </b>{" "}
        {a.status === "offboarded"
          ? reasonText(a.reason) || "It was retired and its passport revoked."
          : trusted
            ? `${s.name} still works at ${s.company}${s.title ? ` as ${s.title}` : ""} and can delegate this work, according to Crustdata.`
            : reasonText(a.reason) || (fail ? `${checkLabel(fail.name)}: ${fail.detail}` : "Its last check failed.")}
        <span className="text-faint"> · {a.last_checked ? `checked ${ago(a.last_checked)}` : "not checked yet"}</span>
      </p>
    </section>
  );
}

/** Passport tab, top: what the passport card below doesn't say, its job and where it runs. */
function AgentFacts({ agent: a }: { agent: Agent }) {
  return (
    <section>
      <dl className="grid gap-x-8 gap-y-5 sm:grid-cols-3">
        <Fact k="Its job" v={brandText(a.job) || a.role} sub={a.role} />
        <Fact k="Runs" v={a.runtime === "external" ? "On its own machine" : `Inside ${BRAND.name}`} sub={`Connected ${day(a.onboarded_at)}`} />
        <Fact
          k="Signing key"
          v={a.key_custody === "agent" ? "Held by the agent" : `Held by ${BRAND.name}`}
          sub={a.key_custody === "agent" ? `${BRAND.name} only has the public half` : `${BRAND.name} signs for it`}
        />
      </dl>
    </section>
  );
}

/** Who at the company works with this agent. A recruiter sees only the agents assigned to them. */
function Assignees({ agent: a, onChanged }: { agent: Agent; onChanged: () => void }) {
  const [members, setMembers] = useState<Member[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.members().then(setMembers).catch(() => setMembers([]));
  }, []);
  const ids = a.assignees ?? [];
  const toggle = async (m: Member) => {
    setBusy(m.id);
    setErr(null);
    try {
      await api.setAssignees(a.agent_id, ids.includes(m.id) ? ids.filter((x) => x !== m.id) : [...ids, m.id]);
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };
  // Admins and owners already see every agent; this is for the people who only see what they're given.
  const people = (members ?? []).filter((m) => m.workspace_role === "member" || m.workspace_role === "viewer");
  return (
    <section>
      <SectionHead title="Who works with it">
        People who see {a.name} under My agents, give it tasks and approve its sends. Admins see every agent anyway.
      </SectionHead>
      {members === null ? (
        <p className="mt-3 flex items-center gap-2 text-[12.5px] text-faint"><Loader2 className="size-3.5 animate-spin" /> Loading people</p>
      ) : people.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {people.map((m) => {
            const on = ids.includes(m.id);
            return (
              <button key={m.id} type="button" onClick={() => toggle(m)} disabled={!!busy} aria-pressed={on}
                title={on ? `Take ${a.name} away from ${m.email}` : `Give ${a.name} to ${m.email}`}
                className={cn("inline-flex h-8 items-center gap-2 rounded-full border pl-1 pr-3 text-[12.5px] transition",
                  on ? "border-foreground/40 bg-elevated font-[510]" : "border-border-strong text-muted-foreground hover:bg-hover")}>
                <span className={cn("grid size-6 place-items-center rounded-full text-[10.5px] font-[590]", on ? "bg-foreground text-background" : "bg-elevated")}>
                  {busy === m.id ? <Loader2 className="size-3 animate-spin" /> : on ? <Check className="size-3" /> : (m.full_name || m.email)[0]?.toUpperCase()}
                </span>
                {m.full_name || m.email}
                <span className="text-[11px] font-normal text-faint">{m.job_role ?? m.workspace_role}</span>
              </button>
            );
          })}
        </div>
      ) : (
        <p className="mt-3 text-[12.5px] text-muted-foreground">No recruiters in your company yet. People who sign up with your email domain join as members.</p>
      )}
      {err && <p className="mt-2 text-[12px] text-contradicted">{err}</p>}
    </section>
  );
}

/** The agent's own app, opened from Agaxes. Everything it does there is still checked and logged here. */
function AppCard({ agent: a }: { agent: Agent }) {
  const app = appFor(a)!;
  return (
    <section className={cn(cardCls, "overflow-hidden")}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4">
        <div className="flex min-w-0 items-center gap-3">
          <Logo />
          <div className="min-w-0">
            <p className="text-[14px] font-[590]">{app.name}&apos;s dashboard</p>
            <p className="text-[12.5px] text-muted-foreground">{app.what} Every message it sends from there still passes Send Guard and lands on this page&apos;s history.</p>
          </div>
        </div>
        <Link href={app.href} prefetch={false} className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md bg-foreground px-3 text-[13px] font-[510] text-background transition hover:opacity-90">
          Open {app.name} <span aria-hidden>→</span>
        </Link>
      </div>
      <div className="grid grid-cols-1 divide-y divide-border sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        {app.pages.map((pg) => (
          <Link key={pg.href} href={pg.href} prefetch={false} className="group px-5 py-3.5 transition hover:bg-elevated">
            <span className="flex items-center justify-between text-[13px] font-[510]">
              {pg.label} <span className="text-faint transition group-hover:translate-x-0.5 group-hover:text-foreground">→</span>
            </span>
            <span className="mt-0.5 block text-[12px] leading-snug text-muted-foreground">{pg.what}</span>
          </Link>
        ))}
      </div>
    </section>
  );
}

function Fact({ k, v, sub }: { k: string; v: string; sub?: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11.5px] text-faint">{k}</dt>
      <dd className="mt-1 truncate text-[13.5px] font-[510]" title={v}>{v}</dd>
      {sub && <dd className="truncate text-[12px] text-muted-foreground" title={sub}>{sub}</dd>}
    </div>
  );
}

/** Runs the same check anyone it contacts would run, for one permission or all of them, and explains the answer. */
function PassportCheck({ agent: a, onChecked }: { agent: Agent; onChecked: () => void }) {
  const [scope, setScope] = useState<Scope | "">("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string>();
  const [v, setV] = useState<Verdict>();
  const run = async () => {
    setBusy(true);
    setErr(undefined);
    try {
      setV(await api.verify(a.passport, scope || undefined));
      onChecked();
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 401 ? "Admin token needed: add it with the key button in the sidebar." : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  const passed = v?.checks.filter((c) => c.status === "pass").length ?? 0;
  return (
    <section>
      <SectionHead title="Check this passport now">
        The same check anyone {a.name} contacts would run: is the signature genuine, is it still valid, and does Crustdata confirm {a.passport.sponsor.name} can vouch for it.
      </SectionHead>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <select value={scope} onChange={(e) => setScope(e.target.value as Scope | "")} className={cn(inputCls, "w-auto")} aria-label="Check it for">
          <option value="">For everything it may do</option>
          {a.passport.scopes.map((sc) => <option key={sc} value={sc}>For {SCOPE_INFO[sc]?.label.toLowerCase() ?? sc}</option>)}
        </select>
        <Button variant="primary" onClick={run} disabled={busy}>
          {busy ? <Loader2 className="size-3.5 animate-spin" /> : <ShieldCheck className="size-3.5" />} Run the check
        </Button>
      </div>
      {err && <p className="mt-3 rounded-md border border-contradicted/30 bg-contradicted/[0.06] px-3 py-2 text-[12.5px] text-contradicted">{err}</p>}
      {v && (
        <div className={cn(cardCls, "mt-4 overflow-hidden animate-rise")}>
          <div className={cn("flex flex-wrap items-center gap-2.5 border-b px-4 py-3", v.decision === "allow" ? "border-verified/25 bg-verified/[0.06]" : "border-contradicted/25 bg-contradicted/[0.06]")}>
            <DecisionBadge decision={v.decision} />
            <span className="text-[14px] font-[590]">{v.decision === "allow" ? "Safe to trust" : "Refuse it"}</span>
            <span className="ml-auto text-[12px] text-muted-foreground">{passed} of {v.checks.length} checks passed</span>
          </div>
          <div className="px-4 pb-2"><VerdictList verdict={v} /></div>
        </div>
      )}
    </section>
  );
}

function PassportTab({ agent: a }: { agent: Agent }) {
  const p = a.passport;
  const s = p.sponsor;
  const revoked = a.status !== "active";
  return (
    <div className="space-y-8">
      <div className={cn(cardCls, "overflow-hidden")}>
        <div className="flex items-center justify-between gap-3 border-b border-border bg-elevated/60 px-5 py-3">
          <span className="flex items-center gap-2 text-[12.5px] font-[510]">
            <IdCard className="size-4 text-muted-foreground" /> Passport
            <span className="font-mono text-[11px] font-normal text-faint">{p.agent_id}</span>
          </span>
          <span className={cn("text-[11.5px] font-[510]", revoked ? "text-contradicted" : "text-verified")}>
            {a.status === "suspended" ? "Revoked while suspended" : a.status === "offboarded" ? "Revoked for good" : `Valid until ${day(p.expires_at)}`}
          </span>
        </div>
        <dl className={cn("grid grid-cols-2 gap-x-6 gap-y-4 px-5 py-5 text-[13px] sm:grid-cols-3", revoked && "opacity-60")}>
          <PField k="Acts for" v={s.name} />
          <PField k="Their title" v={s.title ?? "–"} />
          <PField k="Company" v={s.company} />
          <PField k="Domain" v={s.company_domain ?? "–"} mono />
          <PField k="Issued" v={day(p.issued_at)} />
          <PField k="Expires" v={day(p.expires_at)} />
          <div className="col-span-2 sm:col-span-3">
            <dt className="text-[11.5px] text-faint">May do</dt>
            <dd className="mt-1.5 flex flex-wrap gap-1">{p.scopes.map((sc) => <ScopeChip key={sc} scope={sc} />)}</dd>
          </div>
        </dl>
        <div className="grid gap-x-6 gap-y-1 border-t border-border px-5 py-3 sm:grid-cols-2">
          <PField k="Agent key" v={`ed25519:${p.public_key}`} mono small />
          <PField k="Signed by issuer key" v={p.issuer_key_id || "–"} mono small />
        </div>
      </div>

      <div>
        <SectionHead
          title="Last sponsor check"
          aside={<span className="text-[11.5px] text-faint">{a.last_checked ? `${ago(a.last_checked)} · ${day(a.last_checked)}` : "not checked yet"}</span>}
        >
          {a.last_verdict
            ? `${a.last_verdict.checks.filter((c) => c.status === "pass").length} of ${a.last_verdict.checks.length} checks passed. Each line shows the record it was checked against.`
            : `Not checked yet. Use Re-check sponsor above to see what Crustdata says about ${s.name}.`}
        </SectionHead>
        {a.last_verdict && (
          <>
            <div className="mt-3"><DecisionBadge decision={a.last_verdict.decision} /></div>
            <VerdictList verdict={a.last_verdict} className="mt-1" />
          </>
        )}
      </div>
    </div>
  );
}

function PField({ k, v, mono, small }: { k: string; v: string; mono?: boolean; small?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11.5px] text-faint">{k}</dt>
      <dd className={cn("mt-0.5 truncate", mono ? "font-mono text-[11.5px] text-secondary" : "font-[510]", small && "text-[11px]")} title={v}>{v}</dd>
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
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <p className="text-[12.5px] text-muted-foreground">{view.entries.length} entries about {a.name}, newest first.</p>
        <ExportButtons agentId={a.agent_id} />
      </div>
      <LedgerTimeline entries={[...view.entries].reverse()} firstBad={view.first_bad_seq} names={new Map([[a.agent_id, a.name]])} />
    </div>
  );
}

// ---- onboarding ------------------------------------------------------------------------------

/** Connect an agent in three short steps: what it is, who vouches for it, what it may do. Then the passport is issued and checked. */
export function OnboardForm({
  roles, scenarios, first, onDone, onOpen,
}: { roles: Role[]; scenarios: Scenario[]; first: boolean; onDone: (agentId: string) => void; onOpen: (agentId: string) => void }) {
  const [step, setStep] = useState(0);
  const [name, setName] = useState(first ? "Sourced" : "");
  const [roleKey, setRoleKey] = useState(roles[0]?.key ?? "recruiter");
  const role = roles.find((r) => r.key === roleKey);
  const [scopes, setScopes] = useState<Scope[]>(role?.default_scopes ?? []);
  const [sponsor, setSponsor] = useState<Sponsor>(scenarios[0]?.sponsor ?? { name: "", profile_url: "", company: "", company_domain: "", title: "" });
  const [days, setDays] = useState(30);
  const [job, setJob] = useState(first ? "Sources candidates for open roles and drafts outreach" : "");
  // "own": it runs on its own machine and makes its own key; Agaxes issues a one-time command instead of a key.
  const [runtime, setRuntime] = useState<"in-house" | "own">("in-house");
  const [ttl, setTtl] = useState(60);
  const [invite, setInvite] = useState<{ command: string; expires_at: string; note?: string }>();
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [result, setResult] = useState<{ agent: Agent; verdict: Verdict }>();

  const pickRole = (k: string) => {
    setRoleKey(k);
    setScopes(roles.find((r) => r.key === k)?.default_scopes ?? []);
  };
  const set = (k: keyof Sponsor) => (e: React.ChangeEvent<HTMLInputElement>) => setSponsor((s) => ({ ...s, [k]: e.target.value }));
  const story = scenarios.find((s) => s.sponsor.profile_url === sponsor.profile_url)?.story;

  const STEPS = ["The agent", "Who vouches for it", "What it may do"];
  const canNext = step === 0 ? !!name.trim() && !!roleKey : step === 1 ? !!sponsor.name.trim() && !!sponsor.company.trim() && !!sponsor.profile_url.trim() : scopes.length > 0;

  const submit = async () => {
    setBusy(true);
    setError(undefined);
    const sp = { ...sponsor, company_domain: sponsor.company_domain || null, title: sponsor.title || null };
    try {
      if (runtime === "own") {
        const r = await api.enroll({ name, role: roleKey, sponsor: sp, scopes, days, job: job.trim() || undefined, ttl_minutes: ttl });
        setInvite({ command: r.command, expires_at: r.enrollment.expires_at, note: r.note });
        onDone("");
        return;
      }
      const r = await api.onboard({ name, role: roleKey, sponsor: sp, scopes, days, job: job.trim() || undefined, runtime: "in-house" });
      setResult(r);
      onDone(r.agent.agent_id);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? "Admin token needed: add it with the key button in the sidebar." : err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (invite) {
    const copy = () => {
      navigator.clipboard?.writeText(invite.command).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1600);
      }).catch(() => {});
    };
    return (
      <div className="flex h-full flex-col">
        <div className="flex-1 overflow-y-auto p-6">
          <span className="grid size-10 place-items-center rounded-full bg-elevated"><KeyRound className="size-5 text-foreground" /></span>
          <h2 className="mt-4 text-[19px] font-[620] tracking-[-0.01em]">Run this on {name}&apos;s machine</h2>
          <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
            The command makes {name} its own signing key, proves it holds it, and collects its passport. {BRAND.name} only ever sees the public half.
            Then {sponsor.name} is checked in Crustdata, the same as any other agent.
          </p>
          <div className="mt-4 rounded-lg border border-border-strong bg-elevated">
            <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-1.5">
              <span className="text-[11.5px] text-muted-foreground">Works once · expires {until(invite.expires_at)}</span>
              <button type="button" onClick={copy} className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11.5px] font-[510] text-secondary hover:bg-hover">
                {copied ? <Check className="size-3.5 text-verified" /> : <Copy className="size-3.5" />} {copied ? "Copied" : "Copy"}
              </button>
            </div>
            <pre className="overflow-x-auto whitespace-pre-wrap break-all px-3 py-2.5 font-mono text-[11.5px] leading-relaxed">{invite.command}</pre>
          </div>
          <p className="mt-3 text-[12px] leading-relaxed text-faint">
            This is the only time the command is shown. If it&apos;s lost or expires, cancel the invite from Agents and make a new one.
          </p>
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-border p-4">
          <Button variant="primary" onClick={() => onOpen("")}>Done</Button>
        </div>
      </div>
    );
  }

  if (result) {
    const ok = result.agent.status === "active";
    return (
      <div className="flex h-full flex-col">
        <div className="flex-1 overflow-y-auto p-6">
          <span className={cn("grid size-10 place-items-center rounded-full", ok ? "bg-verified/10" : "bg-contradicted/10")}>
            {ok ? <ShieldCheck className="size-5 text-verified" /> : <ShieldAlert className="size-5 text-contradicted" />}
          </span>
          <h2 className="mt-4 text-[19px] font-[620] tracking-[-0.01em]">{ok ? `${result.agent.name} is connected` : `${result.agent.name} starts suspended`}</h2>
          <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
            {ok
              ? `Its passport is issued and signed. Crustdata confirms ${sponsor.name} is real, still works at ${sponsor.company}, and can delegate this work.`
              : `The passport was issued, but ${sponsor.name} can't vouch for it right now, so it was revoked straight away. The failing check is first below.`}
          </p>
          <VerdictList verdict={result.verdict} className="mt-4" />
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-border p-4">
          <Button variant="primary" onClick={() => onOpen(result.agent.agent_id)}>Open {result.agent.name}</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-6 pb-4 pt-6">
        <h2 className="text-[18px] font-[620] tracking-[-0.01em]">Connect an agent</h2>
        <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">
          It gets a signed passport tied to a real person at your company. That person is checked in Crustdata as soon as you finish.
        </p>
        <ol className="mt-4 flex gap-1.5">
          {STEPS.map((t, i) => (
            <li key={t} className="flex-1">
              <button type="button" onClick={() => i < step && setStep(i)} disabled={i > step} className="w-full text-left">
                <span className={cn("block h-1 rounded-full transition", i <= step ? "bg-foreground" : "bg-border-strong")} />
                <span className={cn("mt-1.5 block text-[11.5px]", i === step ? "font-[510] text-foreground" : "text-faint")}>{i + 1}. {t}</span>
              </button>
            </li>
          ))}
        </ol>
      </div>

      <div key={step} className="flex-1 space-y-5 overflow-y-auto p-6 animate-fade">
        {step === 0 && (
          <>
            <Field label="Name">
              <input autoFocus value={name} onChange={(e) => setName(e.target.value)} className={inputCls} placeholder="Sourced" />
            </Field>
            <Field label="Its job" hint="One line on what it does. Shown on its page and in the list.">
              <input value={job} onChange={(e) => setJob(e.target.value)} className={inputCls} placeholder="Researches vendors before procurement calls" />
            </Field>
            <div>
              <span className="mb-0.5 block text-[12px] font-[510] text-muted-foreground">Role</span>
              <span className="mb-2 block text-[11.5px] text-faint">The most this agent could ever be allowed to do.</span>
              <div className="grid gap-1.5 sm:grid-cols-2">
                {roles.map((r) => (
                  <button
                    type="button"
                    key={r.key}
                    onClick={() => pickRole(r.key)}
                    className={cn("rounded-lg border px-3 py-2.5 text-left transition", roleKey === r.key ? "border-foreground/40 bg-elevated" : "border-border-strong hover:bg-hover")}
                  >
                    <span className="block text-[13px] font-[510]">{r.title}</span>
                    <span className="block text-[11.5px] leading-snug text-muted-foreground">{r.summary}</span>
                  </button>
                ))}
              </div>
            </div>
            <div>
              <span className="mb-1.5 block text-[12px] font-[510] text-muted-foreground">Where it runs</span>
              <div className="grid gap-1.5 sm:grid-cols-2">
                {([
                  ["in-house", `Inside ${BRAND.name}`, `${BRAND.name} runs its tasks for you and holds its signing key.`],
                  ["own", "On its own machine", `Like Claude Code on a laptop. It makes and keeps its own key; you get a one-time command to run there.`],
                ] as const).map(([k, t, d]) => (
                  <button type="button" key={k} onClick={() => setRuntime(k)}
                    className={cn("rounded-lg border px-3 py-2.5 text-left transition", runtime === k ? "border-foreground/40 bg-elevated" : "border-border-strong hover:bg-hover")}>
                    <span className="block text-[13px] font-[510]">{t}</span>
                    <span className="block text-[11.5px] leading-snug text-muted-foreground">{d}</span>
                  </button>
                ))}
              </div>
            </div>
          </>
        )}

        {step === 1 && (
          <>
            <p className="text-[13px] leading-relaxed text-secondary">
              The sponsor is the real person {name || "the agent"} acts for. Anyone it contacts can check that they exist, still work at {sponsor.company || "the company"}, and are senior enough to hand it this work.
            </p>
            {scenarios.length > 0 && (
              <div>
                <span className="mb-1.5 block text-[12px] font-[510] text-muted-foreground">Pick a sample person</span>
                <div className="grid gap-1.5">
                  {scenarios.map((s) => (
                    <button type="button" key={s.id} onClick={() => setSponsor(s.sponsor)}
                      className={cn("rounded-lg border px-3 py-2 text-left transition", sponsor.profile_url === s.sponsor.profile_url ? "border-foreground/40 bg-elevated" : "border-border-strong hover:bg-hover")}>
                      <span className="block text-[13px] font-[510]">{s.sponsor.name} <span className="font-normal text-muted-foreground">· {[s.sponsor.title, s.sponsor.company].filter(Boolean).join(", ")}</span></span>
                      <span className="block text-[11.5px] leading-snug text-muted-foreground">{s.story}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
            <div>
              <span className="mb-1.5 block text-[12px] font-[510] text-muted-foreground">{scenarios.length ? "Or enter a real person" : "Their details"}</span>
              <div className="grid gap-2 sm:grid-cols-2">
                <input value={sponsor.name} onChange={set("name")} placeholder="Full name" className={inputCls} />
                <input value={sponsor.title ?? ""} onChange={set("title")} placeholder="Title, e.g. Head of Talent" className={inputCls} />
                <input value={sponsor.company} onChange={set("company")} placeholder="Company" className={inputCls} />
                <input value={sponsor.company_domain ?? ""} onChange={set("company_domain")} placeholder="Company email domain" className={inputCls} />
                <input value={sponsor.profile_url} onChange={set("profile_url")} placeholder="LinkedIn profile URL (what Crustdata looks up)" className={cn(inputCls, "sm:col-span-2")} />
              </div>
              {story && <p className="mt-2 text-[11.5px] text-faint">{story}</p>}
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <div>
              <span className="mb-0.5 block text-[12px] font-[510] text-muted-foreground">Permissions</span>
              <span className="mb-2 block text-[11.5px] text-faint">Locked ones are outside the {role?.title ?? "chosen"} role. {sponsor.name || "The sponsor"}&apos;s title must also allow each one.</span>
              <div className="grid gap-1.5">
                {ALL_SCOPES.map((sc) => (
                  <ScopeToggle key={sc} scope={sc} checked={scopes.includes(sc)} locked={!!role && !role.ceiling.includes(sc)}
                    onChange={(on) => setScopes((cur) => (on ? [...cur, sc] : cur.filter((x) => x !== sc)))} />
                ))}
              </div>
            </div>
            <Field label="Passport valid for" hint="After this it must be renewed. Payroll checks the sponsor again in the meantime.">
              <span className="flex items-center gap-2">
                <input type="number" min={1} max={365} value={days} onChange={(e) => setDays(Number(e.target.value) || 30)} className={cn(inputCls, "w-24")} />
                <span className="text-[12.5px] text-muted-foreground">days</span>
              </span>
            </Field>
            {runtime === "own" && (
              <Field label="The command works for" hint="It works once. After this it expires and you'd make a new one.">
                <select value={ttl} onChange={(e) => setTtl(Number(e.target.value))} className={cn(inputCls, "w-40")}>
                  <option value={60}>1 hour</option>
                  <option value={24 * 60}>1 day</option>
                  <option value={7 * 24 * 60}>7 days</option>
                </select>
              </Field>
            )}
            <div className="rounded-lg border border-border bg-elevated px-3.5 py-3 text-[12.5px] leading-relaxed text-secondary">
              <b className="font-[590]">{name || "This agent"}</b> will act for <b className="font-[590]">{sponsor.name || "…"}</b> at {sponsor.company || "…"} as a {role?.title ?? roleKey},
              and may {scopes.length ? scopes.map((s) => SCOPE_INFO[s].label.toLowerCase()).join(", ") : "do nothing yet"}.
            </div>
          </>
        )}
        {error && <p className="rounded-md border border-contradicted/30 bg-contradicted/[0.06] px-3 py-2 text-[12.5px] text-contradicted">{error}</p>}
      </div>

      <div className="flex items-center justify-between gap-2 border-t border-border p-4">
        <Button variant="ghost" onClick={() => setStep((s) => Math.max(0, s - 1))} disabled={step === 0 || busy}>Back</Button>
        {step < 2 ? (
          <Button variant="primary" onClick={() => setStep((s) => s + 1)} disabled={!canNext}>Continue</Button>
        ) : (
          <Button variant="primary" onClick={submit} disabled={busy || !canNext}>
            {busy ? <Loader2 className="size-3.5 animate-spin" /> : runtime === "own" ? <KeyRound className="size-3.5" /> : <IdCard className="size-3.5" />}
            {runtime === "own" ? "Make the one-time command" : "Issue passport and check sponsor"}
          </Button>
        )}
      </div>
    </div>
  );
}
