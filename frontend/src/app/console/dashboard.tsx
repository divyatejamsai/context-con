"use client";
// The console's home: the state of every agent you can see, what needs you, and the main actions, on one screen.
import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, Building2, CheckCircle2, Link2, Plus, ShieldCheck, Users, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { BRAND } from "@/lib/brand";
import { AGENT_APPS, appFor } from "@/lib/apps";
import { Logo } from "@/components/app-header";
import { runtime, type Access, type Agent, type RuntimeState } from "./api";
import { AgentMark, Button, SectionHead, StatusPill, ago, cardCls, plain } from "./parts";

type Go = "employees" | "work" | "verify" | "ledger" | "members" | "companies";

export function DashboardView({
  agents, chain, pending, access, company, onConnect, onPick, onGo,
}: {
  agents: Agent[]; chain?: { chain_ok: boolean; count: number }; pending: number; access?: Access; company?: string;
  onConnect: () => void; onPick: (id: string) => void; onGo: (v: Go) => void;
}) {
  const [st, setSt] = useState<RuntimeState | null>(null);
  useEffect(() => {
    runtime.state().then(setSt).catch(() => setSt(null));
  }, [agents.length]);
  const own = access?.level === "own_work";
  const admin = !own;
  const active = agents.filter((a) => a.status === "active").length;
  const suspended = agents.filter((a) => a.status === "suspended");
  const apps = Object.values(AGENT_APPS).filter((a) => !access || access.views.includes(a.name.toLowerCase()));
  const has = (v: string) => !access || access.views.includes(v);

  const actions: { t: string; d: string; icon: React.ElementType; on: () => void; show: boolean; primary?: boolean }[] = [
    { t: "Connect an agent", d: "Give a new agent a passport, vouched for by a real person at your company.", icon: Plus, on: onConnect, show: admin, primary: true },
    { t: "Check a passport", d: "An agent from another company contacted you? See whether to trust it.", icon: ShieldCheck, on: () => onGo("verify"), show: true },
    { t: "Live work", d: "Assign tasks, approve sends, pause or stop an agent mid-task.", icon: CheckCircle2, on: () => onGo("work"), show: has("work") },
    { t: "Ledger", d: "The tamper-evident record of every check and decision. Export it for an audit.", icon: Link2, on: () => onGo("ledger"), show: has("ledger") },
    { t: "Members", d: "Who at your company can see and control agents, and their roles.", icon: Users, on: () => onGo("members"), show: has("members") },
    { t: "Companies", d: "Every company on the platform, its people and its agents.", icon: Building2, on: () => onGo("companies"), show: has("companies") },
  ];

  return (
    <main className="mx-auto max-w-[1320px] px-4 pb-16 pt-6 sm:px-8 sm:pt-8">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div>
          <p className="mb-1 text-[11.5px] font-[510] text-faint">{access?.level === "platform" ? "Platform" : company ?? BRAND.name}</p>
          <h1 className="text-[22px] font-[620] tracking-[-0.02em]">Dashboard</h1>
          <p className="mt-1.5 max-w-[640px] text-[13px] leading-relaxed text-muted-foreground">
            {own
              ? "The agents you work with, what they're doing, and what's waiting for your approval."
              : `Every agent ${access?.level === "platform" ? "on the platform" : "your company runs"}, whether it can be trusted right now, and what needs you.`}
          </p>
        </div>
        {admin && (
          <Button variant="primary" onClick={onConnect}>
            <Plus className="size-3.5" /> Connect an agent
          </Button>
        )}
      </div>

      <section className="mt-6 grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border-strong bg-border sm:grid-cols-3 lg:grid-cols-6">
        <Kpi label="Agents" value={agents.length} sub={`${active} active`} onClick={() => onGo("employees")} />
        <Kpi label="Suspended" value={suspended.length} tone={suspended.length ? "bad" : undefined} sub={suspended.length ? (suspended.some((a) => a.suspended_by?.startsWith("emergency stop")) ? "incl. an emergency stop" : "sponsor checks failed") : "none"} onClick={() => onGo("employees")} />
        <Kpi label="Waiting on you" value={pending} tone={pending ? "warn" : undefined} sub="sends to approve" onClick={() => onGo("work")} />
        <Kpi label="Working now" value={st?.totals.working ?? "–"} sub={st ? `${st.totals.queued} queued` : ""} onClick={() => onGo("work")} />
        <Kpi label="Sent today" value={st?.totals.sent_today ?? "–"} sub={st ? `${st.totals.blocked_today} blocked by Send Guard` : ""} onClick={() => onGo("work")} />
        {chain ? (
          <Kpi label="Ledger" value={chain.chain_ok ? "Intact" : "Broken"} tone={chain.chain_ok ? "ok" : "bad"} sub={`${chain.count} entries`} onClick={() => onGo("ledger")} />
        ) : (
          <Kpi label="Done today" value={st?.totals.done_today ?? "–"} sub="tasks finished" onClick={() => onGo("work")} />
        )}
      </section>

      <div className="mt-8 grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_360px]">
        <section className="min-w-0">
          <SectionHead title={own ? "My agents" : "Agents"} aside={<button onClick={() => onGo("employees")} className="text-[12.5px] font-[510] text-primary hover:underline">See all</button>}>
            Click one to open its page: passport, messages, work and history.
          </SectionHead>
          <ul className={cn(cardCls, "mt-3 divide-y divide-border")}>
            {agents.length ? agents.slice(0, 8).map((a) => (
              <li key={a.agent_id}>
                <button onClick={() => onPick(a.agent_id)} className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-hover">
                  <AgentMark agent={a} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2 text-[13.5px] font-[590]">
                      {a.name}
                      {appFor(a) && <span className="rounded border border-border px-1 text-[10.5px] font-[510] text-muted-foreground">app</span>}
                    </span>
                    <span className={cn("block truncate text-[12px]", a.status === "suspended" ? "text-contradicted" : "text-muted-foreground")}>
                      {a.status !== "active" && a.reason ? plain(a.reason) : `for ${a.passport.sponsor.name}, ${a.passport.sponsor.company} · checked ${ago(a.last_checked)}`}
                    </span>
                  </span>
                  <StatusPill status={a.status} />
                </button>
              </li>
            )) : (
              <li className="px-4 py-8 text-center text-[13px] text-muted-foreground">
                {own ? "No agents are assigned to you yet. Ask your company admin." : "No agents yet. Connect one to give it a passport."}
              </li>
            )}
          </ul>
        </section>

        <aside className="min-w-0 space-y-6">
          <div>
            <SectionHead title="Do something" />
            <ul className="mt-3 grid gap-2">
              {actions.filter((x) => x.show).map((x) => (
                <li key={x.t}>
                  <button onClick={x.on} className={cn(cardCls, "group flex w-full items-start gap-3 p-3.5 text-left transition hover:border-foreground/20 hover:bg-elevated", x.primary && "border-primary/40")}>
                    <span className={cn("grid size-8 shrink-0 place-items-center rounded-lg", x.primary ? "bg-primary text-primary-foreground" : "border border-border-strong bg-elevated text-muted-foreground")}>
                      <x.icon className="size-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[13.5px] font-[590]">{x.t}</span>
                      <span className="block text-[12px] leading-snug text-muted-foreground">{x.d}</span>
                    </span>
                    <ArrowRight className="mt-1 size-3.5 shrink-0 text-faint transition group-hover:translate-x-0.5 group-hover:text-foreground" />
                  </button>
                </li>
              ))}
            </ul>
          </div>
          {apps.length > 0 && (
            <div>
              <SectionHead title="Agent apps">Each one opens its own dashboard. Everything it does is still checked and logged here.</SectionHead>
              <ul className="mt-3 grid gap-2">
                {apps.map((app) => (
                  <li key={app.href}>
                    <Link href={app.href} prefetch={false} className={cn(cardCls, "group flex items-start gap-3 p-3.5 transition hover:border-foreground/20 hover:bg-elevated")}>
                      <Logo />
                      <span className="min-w-0 flex-1">
                        <span className="block text-[13.5px] font-[590]">Open {app.name}</span>
                        <span className="block text-[12px] leading-snug text-muted-foreground">{app.what}</span>
                      </span>
                      <ArrowRight className="mt-1 size-3.5 shrink-0 text-faint transition group-hover:translate-x-0.5 group-hover:text-foreground" />
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </aside>
      </div>
    </main>
  );
}

function Kpi({ label, value, sub, tone, onClick }: { label: string; value: number | string; sub?: string; tone?: "ok" | "bad" | "warn"; onClick: () => void }) {
  return (
    <button onClick={onClick} className="bg-panel px-4 py-3.5 text-left transition hover:bg-elevated">
      <span className="block text-[11.5px] text-muted-foreground">{label}</span>
      <span className={cn("mt-1 flex items-center gap-1.5 text-[22px] font-[620] tabular-nums tracking-[-0.02em]",
        tone === "ok" && "text-verified", tone === "bad" && "text-contradicted", tone === "warn" && "text-flag")}>
        {tone === "bad" && typeof value === "string" && <XCircle className="size-4" />}
        {value}
      </span>
      {sub && <span className="block truncate text-[11.5px] text-faint">{sub}</span>}
    </button>
  );
}
