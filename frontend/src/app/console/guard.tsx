"use client";
import { useCallback, useEffect, useState } from "react";
import { Loader2, Plus, Send, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { ApiError, SCOPE_INFO, api, type Agent, type LedgerEntry, type Recipient, type Scope, type Verdict } from "./api";
import { Button, DecisionBadge, EmptyState, HowTo, PageHead, SectionHead, TERMS, Term, VerdictHeader, Field, VerdictList, checkLabel, inputCls } from "./parts";

const SCOPES = Object.keys(SCOPE_INFO) as Scope[];

// People with Person Enrich records in fixtures/ (replay mode works offline); any LinkedIn URL works live.
const PEOPLE: (Recipient & { label: string })[] = [
  { label: "Vinod · Fam", name: "Vinod Sonagara", profile_url: "https://www.linkedin.com/in/vinod-sonagara", company: "Fam" },
  { label: "Vinod · Trinkerr (old job)", name: "Vinod Sonagara", profile_url: "https://www.linkedin.com/in/vinod-sonagara", company: "Trinkerr" },
  { label: "Charish · SpotDraft", name: "Charish Anumukonda", profile_url: "https://www.linkedin.com/in/charish-anumukonda-80b459140", company: "SpotDraft" },
  { label: "Vinayak · KIoT", name: "Vinayak Kalushe", profile_url: "https://www.linkedin.com/in/vinayakkalushe", company: "KIoT" },
];

interface Result {
  verdict: Verdict;
  sent: boolean;
  agent: string;
  to: Recipient;
}

/** Draft a message as one of the AI employees and run it through the Send Guard before it can leave. */
export function GuardView({ agents, onSent, onOnboard, lockedAgentId }: { agents: Agent[]; onSent: () => void; onOnboard: () => void; lockedAgentId?: string }) {
  const senders = agents.filter((a) => a.status !== "offboarded");
  const [agentId, setAgentId] = useState(lockedAgentId ?? senders[0]?.agent_id ?? "");
  const embedded = !!lockedAgentId;
  const [to, setTo] = useState<Recipient>(PEOPLE[0]);
  const [body, setBody] = useState("Hi Vinod, your work on backend systems at Fam caught our eye. Open to a chat about a role?");
  const [scope, setScope] = useState<Scope>("outreach.hiring");
  const [tamper, setTamper] = useState(false);
  const [signed, setSigned] = useState("Hi Vinod, open to a chat about a backend role?");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [result, setResult] = useState<Result>();
  const [history, setHistory] = useState<LedgerEntry[]>([]);

  const loadHistory = useCallback(() => {
    api
      .ledger(lockedAgentId)
      .then((l) => setHistory(l.entries.filter((e) => e.kind === "guard.verdict" && (!lockedAgentId || (e.payload as { agent_id?: string }).agent_id === lockedAgentId)).reverse().slice(0, 12)))
      .catch(() => {});
  }, [lockedAgentId]);
  useEffect(loadHistory, [loadHistory]);

  const send = async () => {
    setBusy(true);
    setError(undefined);
    try {
      const r = await api.send(agentId, { to, body, scope, signed_body: tamper ? signed : undefined });
      setResult({ ...r, agent: agentId, to });
      loadHistory();
      onSent();
    } catch (e) {
      setError(e instanceof ApiError && e.status === 401 ? "Admin token needed: add it with the key button at the top right." : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const name = (id: string) => agents.find((a) => a.agent_id === id)?.name ?? id;

  return (
    <div className={cn("grid grid-cols-[minmax(0,1fr)] gap-8 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]", !embedded && "mx-auto max-w-[1320px] px-4 py-6 sm:px-8 sm:py-8")}>
      <section className="min-w-0">
        {embedded ? (
          <SectionHead title="Try a message">
            Write what {name(agentId)} would send and to whom. <Term tip={TERMS.guard}>Send Guard</Term> checks its passport, its signature on the text,
            that the person still works where the message says, and every fact in it. Nothing is emailed.
          </SectionHead>
        ) : (<>
        <PageHead title="Check a message before an agent sends it">
          The <Term tip={TERMS.guard}>Send Guard</Term> sits between an agent and the outside world. It checks the agent&apos;s passport, its
          signature on the text, that the recipient still works where the draft says, and every fact about them, in Crustdata. Nothing is
          ever emailed: allowed messages go to an outbox file.
        </PageHead>
        <HowTo
          className="mt-4"
          steps={[
            <>Choose which agent is sending and the permission it&apos;s using.</>,
            <>Pick a recipient and write the draft, or use one of the sample drafts.</>,
            <>Press <span className="font-[590] text-foreground">Sign and check</span>. Allow means it could go out. Block means it was stopped.</>,
          ]}
        />
        </>)}

        <div className={cn("space-y-4 rounded-xl border border-border-strong bg-panel p-4", embedded ? "mt-3" : "mt-5")}>
          {!senders.length && (
            <EmptyState
              icon={Users}
              title="No agent can send yet"
              className="py-6"
              action={<Button variant="primary" onClick={onOnboard}><Plus className="size-3.5" /> Onboard an agent</Button>}
            >
              Only an onboarded AI employee with a passport can sign a draft.
            </EmptyState>
          )}
          <div className={cn("grid gap-3", !embedded && "sm:grid-cols-[minmax(0,1fr)_200px]")}>
            {!embedded && <Field label="Sent by">
              <select value={agentId} onChange={(e) => setAgentId(e.target.value)} className={inputCls}>
                {senders.map((a) => (
                  <option key={a.agent_id} value={a.agent_id}>#{a.employee_no} {a.name} · for {a.passport.sponsor.name} ({a.status})</option>
                ))}
              </select>
            </Field>}
            <Field label="What kind of message" hint={SCOPE_INFO[scope]?.detail}>
              <select value={scope} onChange={(e) => setScope(e.target.value as Scope)} className={inputCls}>
                {SCOPES.map((s) => <option key={s} value={s}>{SCOPE_INFO[s].label}</option>)}
              </select>
            </Field>
          </div>

          <div>
            <span className="mb-1.5 block text-[12px] font-[510] text-muted-foreground">To</span>
            <div className="mb-2 flex flex-wrap gap-1.5">
              {PEOPLE.map((p) => (
                <button
                  key={p.label}
                  onClick={() => setTo(p)}
                  className={cn(
                    "h-7 rounded-full border border-border-strong px-2.5 text-[11.5px] font-[510] transition",
                    to.profile_url === p.profile_url && to.company === p.company ? "border-primary/50 bg-primary/10 text-foreground" : "bg-panel hover:bg-hover",
                  )}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <input value={to.name} onChange={(e) => setTo({ ...to, name: e.target.value })} placeholder="Name" className={inputCls} />
              <input value={to.company} onChange={(e) => setTo({ ...to, company: e.target.value })} placeholder="Company the draft assumes" className={inputCls} />
              <input value={to.profile_url} onChange={(e) => setTo({ ...to, profile_url: e.target.value })} placeholder="LinkedIn URL" className={cn(inputCls, "sm:col-span-2")} />
            </div>
          </div>

          <Field label="Draft">
            <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={4} className={cn(inputCls, "h-auto py-2")} />
          </Field>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[11.5px] text-faint">Sample drafts:</span>
            {[
              ["Clean", "Hi Vinod, your work on backend systems at Fam caught our eye. Open to a chat about a role?"],
              ["False claim", "Hi Vinod, congrats on 5 years at Fam! Open to a chat?"],
              ["Old employer", "Hi Vinod, how is everything at Trinkerr?"],
            ].map(([label, t]) => (
              <button
                key={t}
                onClick={() => setBody(t)}
                title={t}
                className={cn(
                  "h-6 rounded-md border px-2 text-[11.5px] font-[510] transition",
                  body === t ? "border-primary/50 bg-primary/10 text-foreground" : "border-border-strong text-muted-foreground hover:bg-hover hover:text-foreground",
                )}
              >
                {label}
              </button>
            ))}
          </div>

          <details className="group rounded-lg border border-border px-3 py-2" open={tamper}>
          <summary className="cursor-pointer list-none text-[12px] font-[510] text-muted-foreground">Advanced: test a tampered message</summary>
          <label className="mt-2 flex items-start gap-2 text-[12.5px] font-[510]">
            <input type="checkbox" checked={tamper} onChange={(e) => setTamper(e.target.checked)} className="mt-0.5 accent-[var(--primary)]" />
            <span>
              Simulate tampering
              <span className="block text-[11.5px] font-normal text-muted-foreground">The agent signs the text below, but the draft above is what gets sent. The guard should block it.</span>
            </span>
          </label>
          {tamper && <textarea value={signed} onChange={(e) => setSigned(e.target.value)} rows={2} className={cn(inputCls, "mt-2 h-auto py-2")} />}
          </details>

          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="primary"
              onClick={send}
              disabled={busy || !agentId || !body.trim()}
              title="The agent signs the draft with its key, then the Send Guard checks it. Nothing is emailed."
            >
              {busy ? <Loader2 className="size-3.5 animate-spin" /> : <Send className="size-3.5" />} Sign and check
            </Button>
            <span className="text-[11.5px] text-faint">Nothing is emailed. Allowed drafts go to the outbox file.</span>
          </div>
          {error && <p className="rounded-md border border-contradicted/30 bg-contradicted/[0.06] px-3 py-2 text-[12.5px] text-contradicted">{error}</p>}
        </div>
      </section>

      <section className="min-w-0 space-y-6">
        <div className="rounded-xl border border-border-strong bg-panel">
          {result ? (
            <div className="animate-fade">
              <VerdictHeader verdict={result.verdict} title={result.sent ? "Sent to the outbox" : "Blocked before sending"} meta={<><span className="text-[12px] font-[510] opacity-80">{name(result.agent)} → {result.to.name}</span></>} />
              <div className="px-5 pb-4 pt-2">
                <p className="pt-2 text-[12.5px] text-muted-foreground">
                  {result.sent
                    ? "Every check passed, so the message went to the outbox file. It was not emailed to anyone."
                    : "At least one check failed, listed first. The message never left and is not in the outbox."}
                </p>
                <VerdictList verdict={result.verdict} className="mt-1" />
              </div>
            </div>
          ) : (
            <EmptyState icon={Send} title="The verdict appears here" className="min-h-60 justify-center">
              Check the Clean sample first, then try False claim, Old employer, or an agent whose sponsor left, to see what gets stopped.
            </EmptyState>
          )}
        </div>

        <div>
          <SectionHead title={embedded ? `Messages ${name(agentId)} tried to send` : "Recent verdicts"}>
            {embedded ? "Newest first, from the ledger. Blocked ones never left." : "The last messages any agent tried to send, read from the ledger."}
          </SectionHead>
          {history.length ? (
            <ul className="mt-2 divide-y divide-border rounded-xl border border-border-strong bg-panel">
              {history.map((e) => {
                const p = e.payload as { agent_id?: string; decision?: "allow" | "block"; to?: Recipient; checks?: { name: string; status: string; detail: string }[] };
                const fail = p.checks?.find((c) => c.status !== "pass");
                return (
                  <li key={e.hash} className="flex items-start gap-2.5 px-3 py-2.5">
                    {p.decision && <DecisionBadge decision={p.decision} />}
                    <span className="min-w-0 flex-1">
                      <span className="text-[13px] font-[510]">{name(p.agent_id ?? "")} → {p.to?.name} <span className="font-medium text-muted-foreground">at {p.to?.company}</span></span>
                      {fail && <span className="block truncate text-[12px] font-medium text-muted-foreground">{checkLabel(fail.name)}: {fail.detail}</span>}
                    </span>
                    <span className="font-mono text-[10.5px] font-[510] text-muted-foreground">#{e.seq}</span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="mt-2 rounded-lg border border-dashed border-border-strong px-3 py-3 text-[12.5px] text-muted-foreground">
              No messages checked yet. Use Sign and check to see the first verdict here.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
