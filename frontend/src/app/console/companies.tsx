"use client";
// The platform operator's view: every company on Agaxes, its people and its agents (GET /api/platform/companies).
import { useCallback, useEffect, useState } from "react";
import { Building2, Loader2, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { BRAND } from "@/lib/brand";
import { ApiError, api, type AgentStub, type Company } from "./api";
import { Button, EmptyState, PageHead, SectionHead, StatusPill, cardCls, day } from "./parts";

export function CompaniesView({ onPick, onChanged }: { onPick: (agentId: string) => void; onChanged: () => void }) {
  const [data, setData] = useState<{ companies: Company[]; unassigned_agents: AgentStub[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    setError(null);
    api.companies().then(setData).catch((e) => setError(e instanceof ApiError && e.status === 403 ? "Only the platform operator can see every company." : String(e instanceof Error ? e.message : e)));
  }, []);
  useEffect(load, [load]);

  const move = async (agentId: string, workspaceId: string) => {
    setBusy(agentId);
    try {
      await api.moveAgent(agentId, workspaceId || null);
      load();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const companies = data?.companies.filter((c) => c.members.length || c.agents.length) ?? [];

  return (
    <main className="mx-auto w-full max-w-[1100px] px-4 py-6 sm:px-8 sm:py-8">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <PageHead title="Companies" eyebrow="Platform">
          Every company on {BRAND.name}, the people in it and the agents it runs. Only you, the platform operator, see across companies:
          each company&apos;s admins see their own, and recruiters see only the agents assigned to them.
        </PageHead>
        <Button onClick={load}><RefreshCw className="size-3.5" /> Refresh</Button>
      </div>

      {error && <p className="mt-5 rounded-lg border border-contradicted/30 bg-contradicted/[0.06] px-3 py-2 text-[12.5px] text-contradicted">{error}</p>}

      {!data && !error ? (
        <p className="mt-8 flex items-center gap-2 text-[13px] text-faint"><Loader2 className="size-4 animate-spin" /> Loading companies</p>
      ) : data ? (
        <>
          <div className="mt-6 flex flex-wrap gap-x-6 gap-y-1 text-[12.5px] text-muted-foreground tabular-nums">
            <span><b className="font-[590] text-foreground">{companies.length}</b> companies</span>
            <span><b className="font-[590] text-foreground">{companies.reduce((n, c) => n + c.members.length, 0)}</b> people</span>
            <span><b className="font-[590] text-foreground">{companies.reduce((n, c) => n + c.agents.length, 0) + data.unassigned_agents.length}</b> agents</span>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
            {companies.map((c) => (
              <section key={c.id} className={cn(cardCls, "overflow-hidden")}>
                <header className="flex items-center gap-3 border-b border-border px-4 py-3">
                  <span className="grid size-8 shrink-0 place-items-center rounded-lg border border-border-strong bg-elevated text-muted-foreground"><Building2 className="size-4" /></span>
                  <span className="min-w-0">
                    <span className="block truncate text-[14px] font-[590]">{c.name}</span>
                    <span className="block truncate text-[12px] text-muted-foreground">{c.domain}{c.created_at ? ` · joined ${day(c.created_at)}` : ""}</span>
                  </span>
                </header>
                <div className="grid grid-cols-1 divide-y divide-border sm:grid-cols-2 sm:divide-x sm:divide-y-0">
                  <div className="min-w-0 px-4 py-3">
                    <p className="text-[11.5px] text-faint">People ({c.members.length})</p>
                    <ul className="mt-1.5 space-y-1">
                      {c.members.slice(0, 6).map((m) => (
                        <li key={m.id} className="flex items-baseline justify-between gap-2 text-[12.5px]">
                          <span className="truncate">{m.full_name || m.email}</span>
                          <span className="shrink-0 text-[11.5px] capitalize text-muted-foreground">{m.workspace_role}</span>
                        </li>
                      ))}
                      {!c.members.length && <li className="text-[12.5px] text-faint">No one yet</li>}
                      {c.members.length > 6 && <li className="text-[11.5px] text-faint">+{c.members.length - 6} more</li>}
                    </ul>
                  </div>
                  <div className="min-w-0 px-4 py-3">
                    <p className="text-[11.5px] text-faint">Agents ({c.agents.length})</p>
                    <ul className="mt-1.5 space-y-1">
                      {c.agents.map((a) => (
                        <li key={a.agent_id}>
                          <button onClick={() => onPick(a.agent_id)} className="flex w-full items-center justify-between gap-2 rounded text-left text-[12.5px] hover:underline">
                            <span className="truncate">{a.name}</span>
                            <StatusPill status={a.status} />
                          </button>
                        </li>
                      ))}
                      {!c.agents.length && <li className="text-[12.5px] text-faint">None yet</li>}
                    </ul>
                  </div>
                </div>
              </section>
            ))}
          </div>

          <section className="mt-8">
            <SectionHead title={`On the platform, not in a company (${data.unassigned_agents.length})`}>
              Agents onboarded before accounts existed, or by scripts. Only you see them. Place one in a company to hand it over.
            </SectionHead>
            {data.unassigned_agents.length ? (
              <ul className={cn(cardCls, "mt-3 divide-y divide-border")}>
                {data.unassigned_agents.map((a) => (
                  <li key={a.agent_id} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
                    <button onClick={() => onPick(a.agent_id)} className="min-w-0 flex-1 truncate text-left text-[13px] font-[510] hover:underline">{a.name}</button>
                    <StatusPill status={a.status} />
                    <span className="flex items-center gap-2">
                      {busy === a.agent_id && <Loader2 className="size-3.5 animate-spin text-faint" />}
                      <select
                        defaultValue=""
                        disabled={!!busy}
                        onChange={(e) => e.target.value && move(a.agent_id, e.target.value)}
                        aria-label={`Place ${a.name} in a company`}
                        className="h-8 rounded-md border border-border-strong bg-panel px-2 text-[12.5px]"
                      >
                        <option value="">Place in a company…</option>
                        {companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                      </select>
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="Every agent belongs to a company" className={cn(cardCls, "mt-3")} />
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}
