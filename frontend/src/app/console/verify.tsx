"use client";
import { useEffect, useState } from "react";
import { IdCard, Loader2, Plus, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import { ApiError, SCOPE_INFO, api, type Agent, type Passport, type Scenario, type Scope, type Verdict } from "./api";
import { Button, EmptyState, HowTo, PageHead, TERMS, Term, VerdictHeader, VerdictList, inputCls } from "./parts";
import { BRAND } from "@/lib/brand";

const SCOPES = Object.keys(SCOPE_INFO) as Scope[];

/** What any inbox or agent on the receiving end does: paste a passport, check it live. */
export function VerifyView({ agents, scenarios, onOnboard }: { agents: Agent[]; scenarios: Scenario[]; onOnboard: () => void }) {
  const [source, setSource] = useState<string>(agents[0]?.agent_id ?? "");
  const [text, setText] = useState("");
  const [scope, setScope] = useState<Scope | "">("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [result, setResult] = useState<{ verdict: Verdict; edited: boolean }>();

  useEffect(() => {
    const a = agents.find((x) => x.agent_id === source);
    if (a) setText(JSON.stringify(a.passport, null, 2));
  }, [source, agents]);

  const original = agents.find((x) => x.agent_id === source)?.passport;
  let parsed: Passport | null = null;
  try {
    parsed = text.trim() ? (JSON.parse(text) as Passport) : null;
  } catch {
    parsed = null;
  }
  const edited = !!original && !!parsed && JSON.stringify(parsed) !== JSON.stringify(original);

  const verify = async () => {
    if (!parsed) return setError("That isn't valid passport JSON.");
    setBusy(true);
    setError(undefined);
    try {
      setResult({ verdict: await api.verify(parsed, scope || undefined), edited });
    } catch (e) {
      setError(e instanceof ApiError && e.status === 401 ? "Admin token needed: add it with the key button at the top right." : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const story = (a: Agent) => scenarios.find((s) => s.sponsor.profile_url === a.passport.sponsor.profile_url)?.story;

  return (
    <main className="mx-auto grid max-w-[1320px] grid-cols-[minmax(0,1fr)] gap-8 px-4 py-6 sm:px-8 sm:py-8 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <section className="min-w-0">
        <PageHead title="Check an agent's passport">
          Use this when an AI agent contacts you. It checks that the <Term tip={TERMS.passport}>passport</Term> was signed by {BRAND.name}{" "}
          and not edited, then looks up its <Term tip={TERMS.sponsor}>sponsor</Term> in Crustdata: are they real, do they still work
          there, and can they delegate this work.
        </PageHead>
        <HowTo
          className="mt-4"
          steps={[
            <>Pick one of your agents, or paste a passport you received.</>,
            <>Optionally choose the permission it wants to use.</>,
            <>Press <span className="font-[590] text-foreground">Verify live</span>. Allow means trust it. Block means refuse it.</>,
          ]}
        />

        <div className="mt-5 rounded-xl border border-border-strong bg-panel p-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className="min-w-[220px] flex-1">
              <span className="mb-1 block text-[12px] font-[510] text-muted-foreground">Passport from</span>
              <select value={source} onChange={(e) => setSource(e.target.value)} className={inputCls}>
                {agents.map((a) => (
                  <option key={a.agent_id} value={a.agent_id}>
                    #{a.employee_no} {a.name} · for {a.passport.sponsor.name} ({a.status})
                  </option>
                ))}
                <option value="">Paste a passport…</option>
              </select>
            </label>
            <label>
              <span className="mb-1 block text-[12px] font-[510] text-muted-foreground" title={TERMS.scope}>Permission it wants to use</span>
              <select value={scope} onChange={(e) => setScope(e.target.value as Scope | "")} className={cn(inputCls, "w-48")}>
                <option value="">every permission it claims</option>
                {SCOPES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </label>
          </div>
          {source && agents.find((a) => a.agent_id === source) && (
            <p className="mt-2 text-[12px] font-medium text-muted-foreground">{story(agents.find((a) => a.agent_id === source)!)}</p>
          )}
          <textarea
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              if (!e.target.value.trim()) setSource("");
            }}
            spellCheck={false}
            rows={16}
            placeholder='{"agent_id": "...", "sponsor": {...}, "issuer_signature": "..."}'
            className={cn(inputCls, "mt-3 h-auto resize-y py-2 font-mono text-[11.5px] leading-relaxed")}
          />
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button variant="primary" onClick={verify} disabled={busy || !parsed} title="Check the signature, then look the sponsor up in Crustdata right now">
              {busy ? <Loader2 className="size-3.5 animate-spin" /> : <ShieldCheck className="size-3.5" />} Verify live
            </Button>
            {edited && (
              <span className="rounded border border-flag/40 bg-flag/10 px-1.5 py-0.5 text-[11.5px] font-[510] text-flag">
                Edited since it was issued
              </span>
            )}
            <span className="text-[12px] text-muted-foreground">
              {parsed ? "Tip: change a scope or the sponsor's title in the JSON, then verify, to see tampering caught." : "Paste a passport (JSON) to enable Verify."}
            </span>
          </div>
          {error && <p className="mt-3 rounded-md border border-contradicted/30 bg-contradicted/[0.06] px-3 py-2 text-[12.5px] text-contradicted">{error}</p>}
        </div>
      </section>

      <section className="min-w-0 self-start rounded-xl border border-border-strong bg-panel">
        {result ? (
          <div className="animate-fade">
            <VerdictHeader verdict={result.verdict} title={result.verdict.decision === "allow" ? "Trust this agent" : "Refuse this agent"} meta={result.edited && <span className="text-[12px] font-[510]">(edited passport)</span>} />
            <div className="px-5 pb-4 pt-2">
              <p className="pt-2 text-[12.5px] text-muted-foreground">
                {result.verdict.decision === "allow"
                  ? "Every check passed. It's safe to deal with this agent. "
                  : "At least one check failed, listed first. Don't act on what this agent asks. "}
                {result.verdict.checks.filter((c) => c.status === "pass").length} of {result.verdict.checks.length} checks passed.
                Each one names the Crustdata field it read.
                {result.verdict.ledger_entry && <span className="font-mono"> Ledger {result.verdict.ledger_entry.slice(0, 12)}.</span>}
              </p>
              <VerdictList verdict={result.verdict} className="mt-2" />
            </div>
          </div>
        ) : agents.length ? (
          <EmptyState icon={ShieldCheck} title="The result appears here" className="min-h-80 justify-center">
            You&apos;ll get Allow or Block, with every check and the Crustdata field it read. Try an agent whose sponsor has left their company
            to see a refusal.
          </EmptyState>
        ) : (
          <EmptyState
            icon={IdCard}
            title="No passports to check yet"
            className="min-h-80 justify-center"
            action={<Button variant="primary" onClick={onOnboard}><Plus className="size-3.5" /> Onboard an agent</Button>}
          >
            Onboard an AI employee to issue its first passport, or paste a passport you received on the left.
          </EmptyState>
        )}
      </section>
    </main>
  );
}
