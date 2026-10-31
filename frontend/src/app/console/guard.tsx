"use client";
import { useCallback, useEffect, useState } from "react";
import { Inbox, Loader2, Send } from "lucide-react";
import { cn } from "@/lib/utils";
import { ApiError, SCOPE_INFO, api, type Agent, type LedgerEntry, type Recipient, type Scope, type Verdict } from "./api";
import { Button, DecisionBadge, PageHead, VerdictHeader, Field, VerdictList, checkLabel, inputCls } from "./parts";

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
export function GuardView({ agents, onSent }: { agents: Agent[]; onSent: () => void }) {
  const senders = agents.filter((a) => a.status !== "offboarded");
  const [agentId, setAgentId] = useState(senders[0]?.agent_id ?? "");
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
    api.ledger().then((l) => setHistory(l.entries.filter((e) => e.kind === "guard.verdict").reverse().slice(0, 12))).catch(() => {});
  }, []);
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
    <main className="mx-auto grid max-w-[1680px] grid-cols-[minmax(0,1fr)] gap-6 px-4 py-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] ">
      <section className="min-w-0">
        <PageHead title="Stop the wrong email before it's sent">
          The agent signs its draft with its own key. The Send Guard checks the passport, the signature, that the recipient still works
          where the draft says, and every factual claim about them, against Crustdata. Allowed messages go to the outbox file. Nothing is
          emailed.
        </PageHead>

        <div className="mt-5 space-y-4 rounded-xl border border-border-strong bg-panel p-4">
          {!senders.length && <p className="text-[13px] font-[510] text-muted-foreground">Onboard an AI employee first.</p>}
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_200px]">
            <Field label="Sent by">
              <select value={agentId} onChange={(e) => setAgentId(e.target.value)} className={inputCls}>
                {senders.map((a) => (
                  <option key={a.agent_id} value={a.agent_id}>#{a.employee_no} {a.name} · for {a.passport.sponsor.name} ({a.status})</option>
                ))}
              </select>
            </Field>
            <Field label="Scope">
              <select value={scope} onChange={(e) => setScope(e.target.value as Scope)} className={inputCls}>
                {SCOPES.map((s) => <option key={s} value={s}>{s}</option>)}
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
          <div className="flex flex-wrap gap-1.5">
            {[
              "Hi Vinod, congrats on 5 years at Fam! Open to a chat?",
              "Hi Vinod, how is everything at Trinkerr?",
              "Hi Vinod, your work on backend systems at Fam caught our eye. Open to a chat about a role?",
            ].map((t) => (
              <button key={t} onClick={() => setBody(t)} className="rounded-md border border-dashed border-border-strong px-2 py-0.5 text-left text-[11.5px] font-medium hover:bg-hover">
                {t.length > 48 ? `${t.slice(0, 48)}…` : t}
              </button>
            ))}
          </div>

          <label className="flex items-start gap-2 text-[12.5px] font-[510]">
            <input type="checkbox" checked={tamper} onChange={(e) => setTamper(e.target.checked)} className="mt-0.5 accent-[var(--primary)]" />
            <span>
              Alter the message after signing
              <span className="block text-[11.5px] font-medium text-muted-foreground">The agent signs the text below, but the draft above is what gets sent.</span>
            </span>
          </label>
          {tamper && <textarea value={signed} onChange={(e) => setSigned(e.target.value)} rows={2} className={cn(inputCls, "h-auto py-2")} />}

          <Button variant="primary" onClick={send} disabled={busy || !agentId || !body.trim()}>
            {busy ? <Loader2 className="size-3.5 animate-spin" /> : <Send className="size-3.5" />} Sign and send through the guard
          </Button>
          {error && <p className="rounded-md border border-contradicted/30 bg-contradicted/[0.06] px-3 py-2 text-[12.5px] text-contradicted">{error}</p>}
        </div>
      </section>

      <section className="min-w-0 space-y-6">
        <div className="rounded-xl border border-border-strong bg-panel">
          {result ? (
            <div className="animate-fade">
              <VerdictHeader verdict={result.verdict} title={result.sent ? "Sent to the outbox" : "Blocked before sending"} meta={<><span className="text-[12px] font-[510] opacity-80">{name(result.agent)} → {result.to.name}</span></>} />
              <div className="px-5 pb-4 pt-2">
                <VerdictList verdict={result.verdict} />
              </div>
            </div>
          ) : (
            <div className="grid min-h-60 place-items-center p-8 text-center">
              <p className="max-w-[340px] text-[13.5px] font-[510] text-muted-foreground">
                Send a clean draft, then try a false claim, a recipient who has moved on, or an agent whose sponsor left.
              </p>
            </div>
          )}
        </div>

        <div>
          <h2 className="flex items-center gap-2 text-[14px] font-[590]">
            <Inbox className="size-4" strokeWidth={2.25} /> Recent verdicts
          </h2>
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
            <p className="mt-2 text-[12.5px] font-medium text-muted-foreground">No messages checked yet.</p>
          )}
        </div>
      </section>
    </main>
  );
}
