"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bot, Check, CheckCircle2, CircleDashed, Copy, Globe, KeyRound, Loader2, Lock, Plug, Search, ShieldAlert, ShieldCheck,
  Sparkles, Terminal, UserRound, XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { BRAND } from "@/lib/brand";
import {
  ApiError, connectApi, type AgentTypeKey, type Budget, type Catalog, type CatalogScope, type ConnectRequest, type IssueResult,
  type Me, type Person, type Risk, type Scenario, type Scope, type Sponsor, type SponsorMatch,
} from "./api";
import { Button, VerdictList, ago, inputCls, until } from "./parts";

// Connect an agent the way a company onboards any non-human identity: what it is, who owns it and vouches for it,
// what it may do (with risk), which tools it may call and how much, a second admin for high-risk access, then
// enrollment and its first signed call. Every step is a real backend call (backend/app/agents/connect.py).

type StepKey = "agent" | "owner" | "access" | "tools" | "review" | "connect";
const STEPS: { k: StepKey; label: string; hint: string }[] = [
  { k: "agent", label: "Agent", hint: "What kind of agent" },
  { k: "owner", label: "Owner and sponsor", hint: "Who answers for it" },
  { k: "access", label: "Permissions", hint: "What it may do" },
  { k: "tools", label: "Tools and limits", hint: "What it may call, how much" },
  { k: "review", label: "Review", hint: "Approval if high risk" },
  { k: "connect", label: "Connect", hint: "Enroll and first call" },
];

const RISK: Record<Risk, { label: string; cls: string }> = {
  low: { label: "Low risk", cls: "border-border-strong text-muted-foreground" },
  medium: { label: "Medium risk", cls: "border-flag/40 text-flag" },
  high: { label: "High risk", cls: "border-contradicted/40 text-contradicted" },
  critical: { label: "Critical", cls: "border-contradicted/60 bg-contradicted/10 text-contradicted" },
};
const TYPE_ICON: Record<AgentTypeKey, typeof Bot> = { template: Sparkles, claude_code: Terminal, mcp: Plug, http: Globe };
const BUDGET_LABEL: Record<keyof Budget, string> = {
  tasks_per_day: "Tasks a day",
  sends_per_day: "Messages sent a day",
  crustdata_calls_per_day: "Crustdata calls a day",
  llm_calls_per_day: "Model calls a day",
};
const ROLE_FOR_TYPE = "researcher";

export function RiskPill({ risk, className }: { risk: Risk; className?: string }) {
  return <span className={cn("inline-flex h-5 shrink-0 items-center rounded-full border px-2 text-[10.5px] font-[560]", RISK[risk].cls, className)}>{RISK[risk].label}</span>;
}

const STATUS_TEXT: Record<ConnectRequest["status"], string> = {
  pending_review: "Waiting for approval",
  approved: "Approved, not issued",
  rejected: "Rejected",
  awaiting_agent: "Waiting for the agent",
  enrolled: "Waiting for its first call",
  connected: "Connected",
  failed: "Sponsor check failed",
  cancelled: "Cancelled",
};
export const connectStatusText = (s: ConnectRequest["status"]) => STATUS_TEXT[s] ?? s;

const errText = (e: unknown) =>
  e instanceof ApiError && e.status === 401 ? "Sign in as an admin to connect agents." : e instanceof Error ? e.message : String(e);

export function ConnectWizard({
  scenarios, me, first, resume, onChanged, onOpen,
}: {
  scenarios: Scenario[];
  me: Me | null;
  first: boolean;
  /** Open an existing request (from the list of requests) instead of starting a new one. */
  resume?: string;
  onChanged: () => void;
  onOpen: (agentId: string) => void;
}) {
  const [cat, setCat] = useState<Catalog>();
  const [people, setPeople] = useState<Person[]>([]);
  const [step, setStep] = useState<StepKey>("agent");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState<string | null>(null);

  // the agent
  const [type, setType] = useState<AgentTypeKey>("template");
  const [tpl, setTpl] = useState<string>(first ? "sourced" : "");
  const [name, setName] = useState(first ? "Sourced" : "");
  const [job, setJob] = useState("");
  const [role, setRole] = useState(ROLE_FOR_TYPE);
  // owner and sponsor
  const [ownerId, setOwnerId] = useState<string>("");
  const [sponsor, setSponsor] = useState<Sponsor>({ name: "", profile_url: "", company: me?.company?.name ?? "", company_domain: me?.company?.domain ?? "", title: "" });
  const [check, setCheck] = useState<SponsorMatch>();
  const [matches, setMatches] = useState<SponsorMatch[]>();
  const [findNote, setFindNote] = useState<string>();
  // access, tools, limits
  const [scopes, setScopes] = useState<Scope[]>([]);
  const [days, setDays] = useState(30);
  const [tools, setTools] = useState<string[]>([]);
  const [budget, setBudget] = useState<Partial<Budget>>({});
  const [approvals, setApprovals] = useState(true);
  const [ttl, setTtl] = useState(60);
  // after submit
  const [req, setReq] = useState<ConnectRequest>();
  const [issued, setIssued] = useState<IssueResult>();
  const [copied, setCopied] = useState<string>();

  const company = me?.company?.name ?? "";
  const owner = people.find((p) => p.user_id === ownerId);
  const template = cat?.templates.find((t) => t.key === tpl);
  const runtimeOwn = type !== "template";
  const roleObj = cat?.roles.find((r) => r.key === (template?.role ?? role));
  const ceiling = roleObj?.ceiling ?? (cat?.scopes.map((s) => s.key) ?? []);

  useEffect(() => {
    connectApi.catalog().then((c) => {
      setCat(c);
      setBudget(c.budget_defaults);
      if (first) {
        const t = c.templates.find((x) => x.key === "sourced");
        if (t) {
          setScopes(t.scopes);
          setTools(t.tools);
          setJob(t.job);
        }
      }
    }).catch((e) => setError(errText(e)));
    connectApi.people().then((r) => {
      setPeople(r.members);
      const mine = r.members.find((m) => m.user_id === r.me && m.can_own);
      if (mine) setOwnerId(mine.user_id);
    }).catch(() => setPeople([]));
  }, [first]);

  useEffect(() => {
    if (!resume) return;
    connectApi.get(resume).then((r) => {
      setReq(r);
      setName(r.name);
      setStep(["pending_review", "approved", "rejected", "cancelled"].includes(r.status) ? "review" : "connect");
    }).catch((e) => setError(errText(e)));
  }, [resume]);

  // live status while waiting on the agent or its first call
  const poll = useCallback(async (id: string, was: string) => {
    const r = await connectApi.get(id).catch(() => null);
    if (r) setReq(r);
    if (r && r.status !== was) onChanged(); // the agents list behind the sheet picks up the new agent
    return r;
  }, [onChanged]);
  useEffect(() => {
    if (!req || !["awaiting_agent", "enrolled"].includes(req.status) || req.runtime !== "own") return;
    const t = setInterval(() => void poll(req.request_id, req.status), 2500);
    return () => clearInterval(t);
  }, [req, poll]);

  const pickTemplate = (k: string) => {
    const t = cat?.templates.find((x) => x.key === k);
    if (!t) return;
    setTpl(k);
    setName(t.name);
    setJob(t.job);
    setScopes(t.scopes);
    setTools(t.tools);
  };
  const pickType = (k: AgentTypeKey) => {
    setType(k);
    if (k === "template") return;
    setTpl("");
    if (!name || cat?.templates.some((t) => t.name === name)) setName(k === "claude_code" ? "Claude Code" : "");
    setJob("");
    setScopes(["data.read"]);
    setTools(["crustdata.people"]);
  };
  const toggleScope = (s: Scope, on: boolean) => {
    const next = on ? [...scopes, s] : scopes.filter((x) => x !== s);
    setScopes(next);
    setTools((cur) => cur.filter((t) => (cat?.tools.find((x) => x.key === t)?.needs ?? []).some((n) => next.includes(n))));
  };

  const findOwner = async () => {
    const who = owner?.name ?? sponsor.name;
    if (!who.trim() || !(sponsor.company || company)) return;
    setBusy("find");
    setFindNote(undefined);
    setMatches(undefined);
    try {
      const r = await connectApi.findSponsor({ name: who, company: sponsor.company || company });
      setMatches(r.matches);
      setFindNote(r.error ?? r.note ?? (r.matches.length ? undefined : `Crustdata has no one called ${who}. Paste their LinkedIn URL instead.`));
    } catch (e) {
      setFindNote(errText(e));
    } finally {
      setBusy(null);
    }
  };
  const pickMatch = (m: SponsorMatch) => {
    setSponsor((s) => ({ ...s, name: m.name ?? s.name, profile_url: m.profile_url, title: m.title ?? s.title, company: m.company ?? s.company, company_domain: m.domain ?? s.company_domain }));
    setCheck(m);
  };
  const checkUrl = async () => {
    if (!sponsor.profile_url.trim() || !sponsor.company.trim()) return;
    setBusy("check");
    try {
      const r = await connectApi.checkSponsor({ profile_url: sponsor.profile_url, company: sponsor.company });
      setCheck(r);
      if (r.found) setSponsor((s) => ({ ...s, name: r.name ?? s.name, title: r.title ?? s.title }));
    } catch (e) {
      setCheck({ found: false, error: errText(e), name: null, profile_url: sponsor.profile_url, title: null, company: null, works_there: false, grants: {} });
    } finally {
      setBusy(null);
    }
  };

  const reviewScopes = (cat?.scopes ?? []).filter((s) => scopes.includes(s.key) && s.needs_review);
  const risk: Risk = (cat?.scopes ?? []).filter((s) => scopes.includes(s.key)).reduce<Risk>(
    (r, s) => (["low", "medium", "high", "critical"].indexOf(s.risk) > ["low", "medium", "high", "critical"].indexOf(r) ? s.risk : r), "low");

  const canNext: Record<StepKey, boolean> = {
    agent: !!name.trim() && (type !== "template" || !!tpl),
    owner: (!people.length || !!owner?.can_own) && !!sponsor.name.trim() && !!sponsor.profile_url.trim() && !!sponsor.company.trim(),
    access: scopes.length > 0,
    tools: true,
    review: true,
    connect: true,
  };
  const idx = STEPS.findIndex((s) => s.k === step);
  const locked = !!req; // once submitted, the form can't change

  const submit = async () => {
    setBusy("submit");
    setError(undefined);
    try {
      const r = await connectApi.create({
        agent_type: type, template: type === "template" ? tpl : null, name, job: job || null, role: template?.role ?? role,
        scopes, tools, budget, require_approval: approvals, days, ttl_minutes: ttl, owner_user_id: ownerId || null,
        sponsor: { ...sponsor, company_domain: sponsor.company_domain || null, title: sponsor.title || null },
        sponsor_check: check?.found !== false && check ? { title: check.title, works_there: check.works_there, grants: check.grants } : null,
      });
      setReq(r);
      onChanged();
      if (r.status === "approved") await issue(r.request_id);
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(null);
    }
  };
  const issue = async (id: string) => {
    setBusy("issue");
    setError(undefined);
    try {
      const r = await connectApi.issue(id);
      setIssued(r);
      setReq(r.request);
      setStep("connect");
      onChanged();
      if (r.request.runtime === "in-house" && r.agent?.status === "active") {
        const t = await connectApi.test(id);
        setReq(t.request);
      }
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(null);
    }
  };
  const decide = async (approve: boolean) => {
    if (!req) return;
    setBusy(approve ? "approve" : "reject");
    setError(undefined);
    try {
      const r = approve ? await connectApi.approve(req.request_id) : await connectApi.reject(req.request_id);
      setReq(r);
      onChanged();
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(null);
    }
  };
  const runTest = async () => {
    if (!req) return;
    setBusy("test");
    try {
      const t = await connectApi.test(req.request_id);
      setReq(t.request);
      if (!t.connected && t.error) setError(t.error);
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(null);
    }
  };
  const copy = (k: string, text: string) => {
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(k);
      setTimeout(() => setCopied(undefined), 1500);
    }).catch(() => {});
  };

  if (!cat) {
    return (
      <div className="grid h-full place-items-center p-6 text-[13px] text-muted-foreground">
        {error ? <p className="max-w-sm text-center text-contradicted">{error}</p> : <Loader2 className="size-4 animate-spin" />}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-border px-5 pb-3 pt-5 sm:px-6">
        <h2 className="text-[17px] font-[620] tracking-[-0.01em]">{req ? `Connect ${req.name}` : "Connect an agent"}</h2>
        <p className="mt-0.5 text-[12.5px] text-muted-foreground">
          {req ? <>Request {req.request_id} · {STATUS_TEXT[req.status]}</> : <>A signed passport, an accountable owner, scoped permissions and budgets. Every step is written to the ledger.</>}
        </p>
        <ol className="mt-3 flex gap-1 md:hidden">
          {STEPS.map((s, i) => <li key={s.k} className={cn("h-1 flex-1 rounded-full", i <= idx ? "bg-foreground" : "bg-border-strong")} />)}
        </ol>
      </div>

      <div className="flex min-h-0 flex-1">
        <nav className="hidden w-[190px] shrink-0 border-r border-border p-3 md:block" aria-label="Steps">
          <ol className="space-y-0.5">
            {STEPS.map((s, i) => {
              const done = i < idx || (s.k === "connect" && req?.status === "connected");
              const reachable = !locked ? i <= idx || STEPS.slice(0, i).every((x) => canNext[x.k]) : s.k === "review" || (s.k === "connect" && !!req?.agent_id || s.k === "connect" && req?.status === "awaiting_agent");
              return (
                <li key={s.k}>
                  <button type="button" disabled={!reachable} onClick={() => setStep(s.k)}
                    className={cn("flex w-full items-start gap-2.5 rounded-md px-2 py-1.5 text-left transition disabled:cursor-default",
                      step === s.k ? "bg-elevated" : reachable && "hover:bg-hover")}>
                    <span className={cn("mt-px grid size-[18px] shrink-0 place-items-center rounded-full border text-[10px] font-[600]",
                      done ? "border-foreground bg-foreground text-background" : step === s.k ? "border-foreground text-foreground" : "border-border-strong text-faint")}>
                      {done ? <Check className="size-3" /> : i + 1}
                    </span>
                    <span className="min-w-0">
                      <span className={cn("block text-[12.5px] leading-tight", step === s.k ? "font-[560] text-foreground" : "text-secondary")}>{s.label}</span>
                      <span className="block text-[11px] leading-tight text-faint">{s.hint}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </nav>

        <div key={step} className="min-w-0 flex-1 overflow-y-auto px-5 py-5 animate-fade sm:px-6">
          {step === "agent" && (
            <div className="space-y-5">
              <Section title="What are you connecting?">
                <div className="grid gap-2 sm:grid-cols-2">
                  {cat.agent_types.map((t) => {
                    const Icon = TYPE_ICON[t.key];
                    return (
                      <Choice key={t.key} on={type === t.key} onClick={() => pickType(t.key)}>
                        <span className="flex items-center gap-2 text-[13px] font-[560]"><Icon className="size-3.5 text-muted-foreground" /> {t.label}</span>
                        <span className="mt-0.5 block text-[11.5px] leading-snug text-muted-foreground">{t.detail}</span>
                        <span className="mt-1.5 block text-[10.5px] text-faint">{t.runtime === "own" ? "Holds its own key" : `${BRAND.name} holds the key`}</span>
                      </Choice>
                    );
                  })}
                </div>
              </Section>
              {type === "template" && (
                <Section title="Template" hint="Each one runs real jobs on Crustdata. You can narrow its permissions next.">
                  <div className="grid gap-2 sm:grid-cols-2">
                    {cat.templates.map((t) => (
                      <Choice key={t.key} on={tpl === t.key} onClick={() => pickTemplate(t.key)}>
                        <span className="flex items-center justify-between gap-2">
                          <span className="text-[13px] font-[560]">{t.name}</span>
                          <RiskPill risk={maxRisk(cat.scopes, t.scopes)} />
                        </span>
                        <span className="mt-0.5 block text-[11.5px] leading-snug text-muted-foreground">{t.job}</span>
                        {!!t.jobs.length && <span className="mt-1.5 block text-[10.5px] text-faint">Jobs: {t.jobs.join(", ")}</span>}
                      </Choice>
                    ))}
                  </div>
                </Section>
              )}
              <div className="grid gap-3 sm:grid-cols-2">
                <Labeled label="Name"><input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} placeholder={type === "claude_code" ? "Claude Code" : "Vendor research bot"} /></Labeled>
                {type !== "template" && (
                  <Labeled label="Role" hint="The most it could ever be allowed to do">
                    <select value={role} onChange={(e) => { setRole(e.target.value); setScopes(["data.read"]); }} className={inputCls}>
                      {cat.roles.map((r) => <option key={r.key} value={r.key}>{r.title}</option>)}
                      <option value="researcher">Researcher (custom)</option>
                    </select>
                  </Labeled>
                )}
                <Labeled label="Its job" hint="One line, shown on its page" className="sm:col-span-2">
                  <input value={job} onChange={(e) => setJob(e.target.value)} className={inputCls} placeholder="Researches vendors before procurement calls" />
                </Labeled>
              </div>
            </div>
          )}

          {step === "owner" && (
            <div className="space-y-6">
              <Section title="Owner" hint={`The person in ${company || "your company"} accountable for ${name || "this agent"}. They see its work and get its approvals.`}>
                {people.length ? (
                  <div className="grid gap-1.5">
                    {people.map((p) => (
                      <button type="button" key={p.user_id} disabled={!p.can_own} onClick={() => { setOwnerId(p.user_id); setMatches(undefined); }}
                        className={cn("flex items-center gap-3 rounded-lg border px-3 py-2 text-left transition disabled:cursor-not-allowed disabled:opacity-50",
                          ownerId === p.user_id ? "border-foreground/40 bg-elevated" : "border-border-strong hover:bg-hover")}>
                        <span className="grid size-7 shrink-0 place-items-center rounded-full bg-elevated text-[11.5px] font-[600]">{p.name.slice(0, 1).toUpperCase()}</span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-[510]">{p.name} <span className="font-normal text-muted-foreground">· {p.email}</span></span>
                          <span className="block text-[11.5px] text-muted-foreground">{p.job_role || "No job title"}{p.why_not ? ` · ${p.why_not}` : ""}</span>
                        </span>
                        <span className="rounded border border-border-strong px-1.5 py-px text-[10.5px] capitalize text-secondary">{p.workspace_role}</span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="rounded-lg border border-border bg-elevated px-3 py-2.5 text-[12.5px] text-muted-foreground">No company accounts are signed in here, so the sponsor below is the owner too.</p>
                )}
              </Section>

              <Section title="Sponsor" hint="The real person it acts for. Crustdata confirms they work there now and that their title can grant each permission.">
                <div className="flex flex-wrap gap-2">
                  {owner && (
                    <Button onClick={findOwner} disabled={!!busy}>
                      {busy === "find" ? <Loader2 className="size-3.5 animate-spin" /> : <Search className="size-3.5" />} Find {owner.name.split(" ")[0]} in Crustdata
                    </Button>
                  )}
                </div>
                {findNote && <p className="mt-2 text-[12px] text-muted-foreground">{findNote}</p>}
                {!!matches?.length && (
                  <div className="mt-2 grid gap-1.5">
                    {matches.map((m) => (
                      <button type="button" key={m.profile_url} onClick={() => pickMatch(m)}
                        className={cn("rounded-lg border px-3 py-2 text-left transition", sponsor.profile_url === m.profile_url ? "border-foreground/40 bg-elevated" : "border-border-strong hover:bg-hover")}>
                        <span className="flex items-center justify-between gap-2">
                          <span className="text-[13px] font-[510]">{m.name} <span className="font-normal text-muted-foreground">· {[m.title, m.company].filter(Boolean).join(", ")}</span></span>
                          {m.works_there ? <span className="text-[11px] text-verified">Works there</span> : <span className="text-[11px] text-faint">Elsewhere</span>}
                        </span>
                        <span className="block truncate font-mono text-[10.5px] text-faint">{m.profile_url}</span>
                      </button>
                    ))}
                  </div>
                )}
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  <input value={sponsor.name} onChange={(e) => setSponsor({ ...sponsor, name: e.target.value })} placeholder="Full name" className={inputCls} />
                  <input value={sponsor.title ?? ""} onChange={(e) => setSponsor({ ...sponsor, title: e.target.value })} placeholder="Title, e.g. Head of Talent" className={inputCls} />
                  <input value={sponsor.company} onChange={(e) => { setSponsor({ ...sponsor, company: e.target.value }); setCheck(undefined); }} placeholder="Company" className={inputCls} />
                  <input value={sponsor.company_domain ?? ""} onChange={(e) => setSponsor({ ...sponsor, company_domain: e.target.value })} placeholder="Company domain" className={inputCls} />
                  <span className="flex gap-2 sm:col-span-2">
                    <input value={sponsor.profile_url} onChange={(e) => { setSponsor({ ...sponsor, profile_url: e.target.value }); setCheck(undefined); }} placeholder="LinkedIn profile URL" className={inputCls} />
                    <Button onClick={checkUrl} disabled={!!busy || !sponsor.profile_url.trim() || !sponsor.company.trim()}>
                      {busy === "check" ? <Loader2 className="size-3.5 animate-spin" /> : <ShieldCheck className="size-3.5" />} Check
                    </Button>
                  </span>
                </div>
                {check && <SponsorCard m={check} catScopes={cat.scopes} />}
                {scenarios.length > 0 && (
                  <details className="mt-3 text-[12px]">
                    <summary className="cursor-pointer text-muted-foreground hover:text-foreground">Use a sample sponsor</summary>
                    <div className="mt-2 grid gap-1.5">
                      {scenarios.map((s) => (
                        <button type="button" key={s.id} onClick={() => { setSponsor(s.sponsor); setCheck(undefined); }}
                          className={cn("rounded-lg border px-3 py-2 text-left transition", sponsor.profile_url === s.sponsor.profile_url ? "border-foreground/40 bg-elevated" : "border-border-strong hover:bg-hover")}>
                          <span className="block text-[12.5px] font-[510]">{s.sponsor.name} <span className="font-normal text-muted-foreground">· {[s.sponsor.title, s.sponsor.company].filter(Boolean).join(", ")}</span></span>
                          <span className="block text-[11.5px] leading-snug text-muted-foreground">{s.story}</span>
                        </button>
                      ))}
                    </div>
                  </details>
                )}
              </Section>
            </div>
          )}

          {step === "access" && (
            <div className="space-y-5">
              <Section title="Permissions" hint={`Locked ones are outside the ${roleObj?.title ?? "chosen"} role. High-risk ones need another admin to approve.`}>
                <div className="grid gap-2">
                  {cat.scopes.map((s) => {
                    const off = !ceiling.includes(s.key);
                    const on = scopes.includes(s.key);
                    const grant = check?.grants?.[s.key];
                    return (
                      <label key={s.key} className={cn("flex gap-3 rounded-lg border px-3 py-2.5 transition",
                        off ? "cursor-not-allowed border-border opacity-50" : "cursor-pointer border-border-strong hover:bg-hover",
                        on && !off && "border-primary/50 bg-primary/[0.05]")}>
                        <input type="checkbox" className="mt-1 size-3.5 accent-[var(--primary)]" checked={on} disabled={off} onChange={(e) => toggleScope(s.key, e.target.checked)} />
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                            <span className="text-[13px] font-[560]">{s.label}</span>
                            <span className="font-mono text-[10.5px] text-faint">{s.key}</span>
                            <RiskPill risk={s.risk} />
                            {s.needs_review && <span className="inline-flex items-center gap-1 text-[10.5px] text-muted-foreground"><ShieldAlert className="size-3" /> Needs approval</span>}
                            {off && <Lock className="size-3 text-faint" />}
                          </span>
                          <span className="mt-1 block text-[12px] leading-snug text-secondary">{s.allows}</span>
                          <span className="block text-[11.5px] leading-snug text-muted-foreground">Never: {s.never}</span>
                          <span className={cn("mt-1 block text-[11px]", grant === true ? "text-verified" : grant === false ? "text-contradicted" : "text-faint")}>
                            {grant === true ? `${sponsor.name || "The sponsor"} can grant this (checked in Crustdata)` : grant === false ? `${sponsor.name || "The sponsor"} can't grant this: needs ${s.who_can_grant}` : `Granted by ${s.who_can_grant}`}
                          </span>
                        </span>
                      </label>
                    );
                  })}
                </div>
              </Section>
              <Labeled label="Passport valid for" hint="Then it must be renewed. The sponsor is re-checked on every payroll run in between.">
                <span className="flex items-center gap-2">
                  <input type="number" min={1} max={365} value={days} onChange={(e) => setDays(Number(e.target.value) || 30)} className={cn(inputCls, "w-24")} />
                  <span className="text-[12.5px] text-muted-foreground">days</span>
                </span>
              </Labeled>
            </div>
          )}

          {step === "tools" && (
            <div className="space-y-6">
              <Section title="Tools" hint="What it may call. Data tools are enforced on every call; sending also goes through Send Guard.">
                <div className="grid gap-1.5">
                  {cat.tools.map((t) => {
                    const ok = t.needs.some((n) => scopes.includes(n));
                    const on = tools.includes(t.key);
                    return (
                      <label key={t.key} className={cn("flex gap-3 rounded-lg border px-3 py-2.5 transition", ok ? "cursor-pointer border-border-strong hover:bg-hover" : "cursor-not-allowed border-border opacity-50", on && ok && "border-primary/50 bg-primary/[0.05]")}>
                        <input type="checkbox" className="mt-1 size-3.5 accent-[var(--primary)]" checked={on && ok} disabled={!ok}
                          onChange={(e) => setTools((cur) => (e.target.checked ? [...cur, t.key] : cur.filter((x) => x !== t.key)))} />
                        <span className="min-w-0">
                          <span className="block text-[13px] font-[560]">{t.label}</span>
                          <span className="block text-[11.5px] leading-snug text-muted-foreground">{t.detail}</span>
                          {!ok && <span className="block text-[11px] text-faint">Needs {t.needs.join(" or ")}</span>}
                        </span>
                      </label>
                    );
                  })}
                </div>
              </Section>
              <Section title="Daily limits" hint="It stops for the day when it reaches one.">
                <div className="grid gap-3 sm:grid-cols-2">
                  {(Object.keys(BUDGET_LABEL) as (keyof Budget)[]).map((k) => (
                    <Labeled key={k} label={BUDGET_LABEL[k]}>
                      <input type="number" min={0} max={cat.budget_limits[k]} value={budget[k] ?? cat.budget_defaults[k]}
                        onChange={(e) => setBudget({ ...budget, [k]: Math.max(0, Math.min(cat.budget_limits[k], Number(e.target.value) || 0)) })} className={cn(inputCls, "w-32")} />
                    </Labeled>
                  ))}
                </div>
              </Section>
              <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-border-strong px-3 py-2.5">
                <input type="checkbox" className="mt-1 size-3.5 accent-[var(--primary)]" checked={approvals} onChange={(e) => setApprovals(e.target.checked)} />
                <span>
                  <span className="block text-[13px] font-[560]">A person approves every message before it goes out</span>
                  <span className="block text-[11.5px] text-muted-foreground">Drafts that pass Send Guard wait in {owner ? `${owner.name.split(" ")[0]}'s` : "the"} approval inbox.</span>
                </span>
              </label>
              {runtimeOwn && (
                <Labeled label="Enrollment command works for" hint="It works once, then expires.">
                  <select value={ttl} onChange={(e) => setTtl(Number(e.target.value))} className={cn(inputCls, "w-40")}>
                    <option value={60}>1 hour</option>
                    <option value={24 * 60}>1 day</option>
                    <option value={7 * 24 * 60}>7 days</option>
                  </select>
                </Labeled>
              )}
            </div>
          )}

          {step === "review" && (
            <div className="space-y-5">
              {req ? <RequestSummary r={req} cat={cat} /> : (
                <dl className="divide-y divide-border rounded-lg border border-border-strong text-[12.5px]">
                  <Row k="Agent" v={<>{name} <span className="text-muted-foreground">· {type === "template" ? `${template?.name} template, runs in ${BRAND.name}` : cat.agent_types.find((t) => t.key === type)?.label}</span></>} />
                  <Row k="Owner" v={owner ? `${owner.name} (${owner.workspace_role})` : "The sponsor"} />
                  <Row k="Sponsor" v={<>{sponsor.name}{sponsor.title ? `, ${sponsor.title}` : ""} at {sponsor.company}{check?.works_there ? <span className="ml-1.5 text-verified">· confirmed in Crustdata</span> : null}</>} />
                  <Row k="Permissions" v={<span className="flex flex-wrap items-center gap-1.5">{scopes.map((s) => <span key={s} className="font-mono text-[11px]">{s}</span>)}<RiskPill risk={risk} /></span>} />
                  <Row k="Tools" v={tools.length ? tools.map((t) => cat.tools.find((x) => x.key === t)?.label).join(", ") : "None"} />
                  <Row k="Daily limits" v={(Object.keys(BUDGET_LABEL) as (keyof Budget)[]).map((k) => `${budget[k] ?? cat.budget_defaults[k]} ${BUDGET_LABEL[k].toLowerCase().replace(" a day", "")}`).join(" · ")} />
                  <Row k="Messages" v={approvals ? "A person approves each one" : "Sent once Send Guard clears them"} />
                  <Row k="Passport" v={`Valid ${days} days${runtimeOwn ? ", bound to a key the agent makes itself" : ""}`} />
                </dl>
              )}
              {!req && reviewScopes.length > 0 && (
                <Callout tone="warn" icon={ShieldAlert} title="Another admin has to approve this">
                  {reviewScopes.map((s) => s.label.toLowerCase()).join(" and ")} {reviewScopes.length > 1 ? "are" : "is"} high risk. The passport is issued only after an admin other than you approves it.
                </Callout>
              )}
              {req?.status === "pending_review" && (
                <Callout tone="warn" icon={ShieldAlert} title="Waiting for approval">
                  {req.requested_by} asked for {req.review.scopes.join(", ")}. An admin other than the requester approves or rejects it here.
                  <span className="mt-2.5 flex gap-2">
                    <Button variant="primary" onClick={() => decide(true)} disabled={!!busy}>{busy === "approve" ? <Loader2 className="size-3.5 animate-spin" /> : <Check className="size-3.5" />} Approve</Button>
                    <Button variant="danger" onClick={() => decide(false)} disabled={!!busy}>Reject</Button>
                  </span>
                </Callout>
              )}
              {req?.status === "approved" && (
                <Callout tone="ok" icon={ShieldCheck} title={req.review.required ? `Approved by ${req.review.by}` : "Ready to issue"}>
                  {req.review.sole_admin ? "Approved by the only admin in the company; recorded as such on the ledger." : "Issue the passport to continue."}
                </Callout>
              )}
              {req?.status === "rejected" && <Callout tone="bad" icon={XCircle} title={`Rejected by ${req.review.by}`}>{req.review.note || "Nothing was issued."}</Callout>}
            </div>
          )}

          {step === "connect" && req && (
            <div className="space-y-5">
              <ConnectSteps r={req} />
              {issued?.command && req.status === "awaiting_agent" && (
                <div className="space-y-3">
                  <CodeBlock label={`1. On ${req.name}'s machine: enroll (works once, expires ${until(req.expires_at)})`} text={issued.command} copied={copied === "cmd"} onCopy={() => copy("cmd", issued.command!)} />
                  {issued.mcp_command && <CodeBlock label="2. Give Claude Code the Agaxes tools" text={issued.mcp_command} copied={copied === "mcp"} onCopy={() => copy("mcp", issued.mcp_command!)} />}
                  {!issued.mcp_command && issued.mcp_config && <CodeBlock label="2. Add Agaxes to the agent's MCP config" text={issued.mcp_config} copied={copied === "mcpc"} onCopy={() => copy("mcpc", issued.mcp_config!)} />}
                  <p className="text-[11.5px] leading-relaxed text-faint">
                    The command makes a key pair on that machine, proves it holds it, collects the passport and sends a signed heartbeat. {BRAND.name} only sees the public key. This is the only time the command is shown.
                  </p>
                </div>
              )}
              {!issued?.command && req.status === "awaiting_agent" && (
                <p className="text-[12.5px] text-muted-foreground">The one-time command was shown when it was made. Cancel this request and start again if it was lost.</p>
              )}
              {(issued?.verdict ?? req.verdict) && (
                <div>
                  <span className="mb-1 block text-[12px] font-[510] text-muted-foreground">Sponsor check at issue</span>
                  <VerdictList verdict={(issued?.verdict ?? req.verdict)!} />
                </div>
              )}
              {req.agent_id && !req.first_seen_at && req.runtime === "in-house" && (
                <Button onClick={runTest} disabled={!!busy}>{busy === "test" ? <Loader2 className="size-3.5 animate-spin" /> : <Plug className="size-3.5" />} Run connection test</Button>
              )}
            </div>
          )}

          {error && <p className="mt-4 rounded-md border border-contradicted/30 bg-contradicted/[0.06] px-3 py-2 text-[12.5px] text-contradicted">{error}</p>}
        </div>
      </div>

      <div className="flex items-center justify-between gap-2 border-t border-border px-5 py-3 sm:px-6">
        {!locked ? (
          <Button variant="ghost" onClick={() => setStep(STEPS[Math.max(0, idx - 1)].k)} disabled={idx === 0 || !!busy}>Back</Button>
        ) : req && ["pending_review", "approved", "awaiting_agent"].includes(req.status) ? (
          <Button variant="ghost" onClick={async () => { setReq(await connectApi.cancel(req.request_id)); onChanged(); }} disabled={!!busy}>Cancel request</Button>
        ) : <span />}
        {!locked && step !== "review" && (
          <Button variant="primary" onClick={() => setStep(STEPS[idx + 1].k)} disabled={!canNext[step]}>Continue</Button>
        )}
        {!locked && step === "review" && (
          <Button variant="primary" onClick={submit} disabled={!!busy || !canNext.agent || !canNext.owner || !canNext.access}>
            {busy ? <Loader2 className="size-3.5 animate-spin" /> : reviewScopes.length ? <ShieldAlert className="size-3.5" /> : runtimeOwn ? <KeyRound className="size-3.5" /> : <ShieldCheck className="size-3.5" />}
            {reviewScopes.length ? "Request approval" : runtimeOwn ? "Make enrollment command" : "Issue passport"}
          </Button>
        )}
        {locked && req?.status === "approved" && (
          <Button variant="primary" onClick={() => issue(req.request_id)} disabled={!!busy}>
            {busy === "issue" ? <Loader2 className="size-3.5 animate-spin" /> : <KeyRound className="size-3.5" />} {req.runtime === "own" ? "Make enrollment command" : "Issue passport"}
          </Button>
        )}
        {locked && req?.agent_id && (
          <Button variant="primary" onClick={() => onOpen(req.agent_id!)}>Open {req.name}</Button>
        )}
      </div>
    </div>
  );
}

function maxRisk(all: CatalogScope[], keys: Scope[]): Risk {
  const order: Risk[] = ["low", "medium", "high", "critical"];
  return all.filter((s) => keys.includes(s.key)).reduce<Risk>((r, s) => (order.indexOf(s.risk) > order.indexOf(r) ? s.risk : r), "low");
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="text-[13px] font-[590]">{title}</h3>
      {hint && <p className="mb-2 mt-0.5 text-[12px] leading-snug text-muted-foreground">{hint}</p>}
      {!hint && <div className="mb-2" />}
      {children}
    </section>
  );
}

function Labeled({ label, hint, children, className }: { label: string; hint?: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={cn("block", className)}>
      <span className="mb-1 block text-[12px] font-[510] text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-faint">{hint}</span>}
    </label>
  );
}

function Choice({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick}
      className={cn("rounded-lg border px-3 py-2.5 text-left transition", on ? "border-foreground/40 bg-elevated ring-1 ring-foreground/10" : "border-border-strong hover:bg-hover")}>
      {children}
    </button>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="grid gap-1 px-3 py-2 sm:grid-cols-[120px_1fr]">
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="min-w-0 text-foreground">{v}</dd>
    </div>
  );
}

function Callout({ tone, icon: Icon, title, children }: { tone: "ok" | "warn" | "bad"; icon: typeof Bot; title: string; children: React.ReactNode }) {
  return (
    <div className={cn("rounded-lg border px-3.5 py-3 text-[12.5px] leading-relaxed",
      tone === "ok" && "border-verified/30 bg-verified/[0.06]", tone === "warn" && "border-flag/35 bg-flag/[0.06]", tone === "bad" && "border-contradicted/30 bg-contradicted/[0.06]")}>
      <span className={cn("flex items-center gap-1.5 font-[590]", tone === "ok" ? "text-verified" : tone === "warn" ? "text-flag" : "text-contradicted")}><Icon className="size-3.5" /> {title}</span>
      <div className="mt-1 text-secondary">{children}</div>
    </div>
  );
}

function SponsorCard({ m, catScopes }: { m: SponsorMatch; catScopes: CatalogScope[] }) {
  if (m.found === false) return <p className="mt-2 text-[12px] text-contradicted">{m.error}</p>;
  return (
    <div className="mt-3 rounded-lg border border-border-strong bg-elevated px-3 py-2.5">
      <span className="flex items-center gap-2 text-[13px] font-[560]"><UserRound className="size-3.5 text-muted-foreground" /> {m.name}</span>
      <span className="block text-[12px] text-muted-foreground">{[m.title, m.company].filter(Boolean).join(" at ") || "No current job on record"}</span>
      <span className={cn("mt-1 block text-[11.5px]", m.works_there ? "text-verified" : "text-contradicted")}>
        {m.works_there ? "Crustdata confirms they work there now" : "Crustdata doesn't show them at this company now"}
      </span>
      <span className="mt-1.5 flex flex-wrap gap-1">
        {catScopes.map((s) => (
          <span key={s.key} className={cn("inline-flex h-5 items-center gap-1 rounded border px-1.5 font-mono text-[10.5px]", m.grants[s.key] ? "border-verified/40 text-verified" : "border-border text-faint line-through")}>{s.key}</span>
        ))}
      </span>
    </div>
  );
}

function RequestSummary({ r, cat }: { r: ConnectRequest; cat: Catalog }) {
  return (
    <dl className="divide-y divide-border rounded-lg border border-border-strong text-[12.5px]">
      <Row k="Agent" v={<>{r.name} <span className="text-muted-foreground">· {r.template ? `${cat.templates.find((t) => t.key === r.template)?.name ?? r.template} template` : cat.agent_types.find((t) => t.key === r.agent_type)?.label}</span></>} />
      <Row k="Requested by" v={`${r.requested_by} · ${ago(r.created_at)}`} />
      <Row k="Owner" v={r.owner ? `${r.owner.name} (${r.owner.workspace_role})` : "The sponsor"} />
      <Row k="Sponsor" v={`${r.sponsor.name}${r.sponsor.title ? `, ${r.sponsor.title}` : ""} at ${r.sponsor.company}`} />
      <Row k="Permissions" v={<span className="flex flex-wrap items-center gap-1.5">{r.scopes.map((s) => <span key={s} className="font-mono text-[11px]">{s}</span>)}<RiskPill risk={r.risk} /></span>} />
      <Row k="Tools" v={r.tools.length ? r.tools.map((t) => cat.tools.find((x) => x.key === t)?.label ?? t).join(", ") : "None"} />
      <Row k="Messages" v={r.require_approval ? "A person approves each one" : "Sent once Send Guard clears them"} />
    </dl>
  );
}

function ConnectSteps({ r }: { r: ConnectRequest }) {
  const own = r.runtime === "own";
  const issued = !!r.agent_id;
  const first = !!r.first_seen_at || r.status === "connected";
  const failed = r.status === "failed";
  const rows: { label: string; detail: string; state: "done" | "wait" | "todo" | "bad" }[] = [
    { label: own ? "Enrollment command made" : "Passport issued", detail: own ? "One-time, shown once" : `Signed by ${BRAND.name}; key held by ${BRAND.name}`, state: own ? (r.enrollment_id ? "done" : "todo") : issued ? "done" : "todo" },
    ...(own ? [{ label: "Agent made its own key", detail: issued ? "Passport bound to its public key" : r.enrollment_status === "expired" ? "The command expired" : "Waiting for the command to run", state: (issued ? "done" : r.enrollment_status === "expired" ? "bad" : "wait") as "done" | "wait" | "bad" }] : []),
    { label: "Sponsor checked in Crustdata", detail: failed ? "Refused: the agent starts suspended" : issued ? "Passed" : "After the passport is issued", state: failed ? "bad" : issued ? "done" : "todo" },
    { label: "First signed call", detail: first ? `Verified ${ago(r.first_seen_at ?? r.test?.at)}${r.test?.ledger_entry ? ` · ledger ${r.test.ledger_entry.slice(0, 10)}` : ""}` : issued && !failed ? "Waiting for a heartbeat signed with its key" : "Not yet", state: first ? "done" : issued && !failed ? "wait" : "todo" },
  ];
  return (
    <ol className="space-y-2.5">
      {rows.map((x) => (
        <li key={x.label} className="flex items-start gap-2.5">
          {x.state === "done" ? <CheckCircle2 className="mt-px size-4 text-verified" /> : x.state === "bad" ? <XCircle className="mt-px size-4 text-contradicted" /> : x.state === "wait" ? <Loader2 className="mt-px size-4 animate-spin text-muted-foreground" /> : <CircleDashed className="mt-px size-4 text-faint" />}
          <span>
            <span className="block text-[13px] font-[510]">{x.label}</span>
            <span className="block text-[11.5px] text-muted-foreground">{x.detail}</span>
          </span>
        </li>
      ))}
    </ol>
  );
}

function CodeBlock({ label, text, copied, onCopy }: { label: string; text: string; copied: boolean; onCopy: () => void }) {
  return (
    <div className="rounded-lg border border-border-strong bg-elevated">
      <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-1.5">
        <span className="text-[11.5px] text-muted-foreground">{label}</span>
        <button type="button" onClick={onCopy} className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11.5px] font-[510] text-secondary hover:bg-hover">
          {copied ? <Check className="size-3.5 text-verified" /> : <Copy className="size-3.5" />} {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto whitespace-pre-wrap break-all px-3 py-2.5 font-mono text-[11.5px] leading-relaxed">{text}</pre>
    </div>
  );
}

/** Requests in flight on the Agents page: approvals waiting, agents that haven't made their first call. */
export function ConnectRequests({ requests, onOpen }: { requests: ConnectRequest[]; onOpen: (id: string) => void }) {
  const open = requests.filter((r) => ["pending_review", "approved", "awaiting_agent", "enrolled"].includes(r.status));
  const shown = useMemo(() => open.slice(0, 8), [open]);
  if (!open.length) return null;
  return (
    <section className="mt-8">
      <h3 className="text-[14px] font-[590]">Connection requests ({open.length})</h3>
      <p className="mt-0.5 text-[12px] text-muted-foreground">High-risk access waiting for an admin, and agents that haven&apos;t made their first signed call yet.</p>
      <ul className="mt-3 divide-y divide-border rounded-xl border border-border-strong bg-panel">
        {shown.map((r) => (
          <li key={r.request_id} className="flex flex-wrap items-center gap-3 px-4 py-3">
            <span className="min-w-0 flex-1">
              <span className="flex flex-wrap items-center gap-2 text-[13.5px] font-[510]">{r.name} <RiskPill risk={r.risk} /></span>
              <span className="block text-[12px] text-muted-foreground">{STATUS_TEXT[r.status]} · asked by {r.requested_by} {ago(r.created_at)} · {r.scopes.join(", ")}</span>
            </span>
            <Button variant={r.status === "pending_review" ? "primary" : "secondary"} onClick={() => onOpen(r.request_id)}>
              {r.status === "pending_review" ? "Review" : "Open"}
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}
