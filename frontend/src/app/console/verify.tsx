"use client";
import { useMemo, useState } from "react";
import { ClipboardPaste, IdCard, Loader2, Pencil, Plus, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import { ApiError, SCOPE_INFO, api, type Agent, type Passport, type Scenario, type Scope, type Verdict } from "./api";
import { AgentMark, Button, DecisionBadge, EmptyState, PageHead, SectionHead, TERMS, Term, VerdictList, cardCls, day, inputCls } from "./parts";
import { BRAND, brandText } from "@/lib/brand";

const SCOPES = Object.keys(SCOPE_INFO) as Scope[];

/** For the receiving end: an agent from somewhere else contacted you. Is its passport genuine, and does its sponsor still vouch for it? */
export function VerifyView({ agents, scenarios, onOnboard }: { agents: Agent[]; scenarios: Scenario[]; onOnboard: () => void }) {
  const [source, setSource] = useState<string>(agents[0]?.agent_id ?? "paste");
  const [pasted, setPasted] = useState("");
  const [edits, setEdits] = useState<{ title?: string; extra?: Scope }>({});
  const [tamper, setTamper] = useState(false);
  const [scope, setScope] = useState<Scope | "">("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [result, setResult] = useState<{ verdict: Verdict; edited: boolean; name: string }>();

  const picked = agents.find((x) => x.agent_id === source);
  const base: Passport | null = useMemo(() => {
    if (picked) return picked.passport;
    try {
      const p = JSON.parse(pasted) as Passport;
      return p && typeof p === "object" && p.sponsor && p.agent_id ? p : null;
    } catch {
      return null;
    }
  }, [picked, pasted]);

  // "Try tampering" changes the passport the way a forger would, without anyone touching JSON.
  const passport: Passport | null = useMemo(() => {
    if (!base || !tamper) return base;
    return {
      ...base,
      sponsor: { ...base.sponsor, title: edits.title ?? base.sponsor.title },
      scopes: edits.extra && !base.scopes.includes(edits.extra) ? [...base.scopes, edits.extra] : base.scopes,
    };
  }, [base, tamper, edits]);
  const edited = !!tamper && !!base && JSON.stringify(passport) !== JSON.stringify(base);

  const verify = async () => {
    if (!passport) return;
    setBusy(true);
    setError(undefined);
    try {
      setResult({ verdict: await api.verify(passport, scope || undefined), edited, name: passport.agent_name });
    } catch (e) {
      setError(e instanceof ApiError && e.status === 401 ? "Admin token needed: add it with the key button in the sidebar." : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const story = (a: Agent) => scenarios.find((s) => s.sponsor.profile_url === a.passport.sponsor.profile_url)?.story;
  const reset = (id: string) => {
    setSource(id);
    setResult(undefined);
    setTamper(false);
    setEdits({});
  };

  return (
    <main className="mx-auto max-w-[1180px] px-4 pb-20 pt-6 sm:px-8 sm:pt-8">
      <PageHead title="Check a passport">
        An AI agent from another company contacted you? Check its <Term tip={TERMS.passport}>passport</Term> before you reply. {BRAND.name} confirms the
        passport is genuine and unedited, then asks Crustdata whether its <Term tip={TERMS.sponsor}>sponsor</Term> is real, still works there, and
        can hand it this kind of work. To check one of your own agents, open it from Agents.
      </PageHead>

      <div className="mt-8 grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section className="min-w-0 space-y-6">
          <div>
            <SectionHead title="1. Whose passport?">Pick a sample, or paste the passport text an agent sent you.</SectionHead>
            <div className="mt-3 grid grid-cols-1 gap-1.5">
              {agents.map((a) => (
                <button key={a.agent_id} onClick={() => reset(a.agent_id)}
                  className={cn("flex items-center gap-3 rounded-lg border px-3 py-2.5 text-left transition", source === a.agent_id ? "border-foreground/40 bg-elevated" : "border-border-strong hover:bg-hover")}>
                  <AgentMark agent={a} />
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-[510]">{a.name} <span className="font-normal text-muted-foreground">· for {a.passport.sponsor.name}, {a.passport.sponsor.company}</span></span>
                    <span className="block truncate text-[11.5px] text-muted-foreground">{story(a) ?? (brandText(a.job) || a.role)}</span>
                  </span>
                </button>
              ))}
              <button onClick={() => reset("paste")}
                className={cn("flex items-center gap-3 rounded-lg border px-3 py-2.5 text-left transition", source === "paste" ? "border-foreground/40 bg-elevated" : "border-dashed border-border-strong hover:bg-hover")}>
                <span className="grid size-7 place-items-center rounded-md border border-border-strong text-muted-foreground"><ClipboardPaste className="size-3.5" /></span>
                <span className="text-[13px] font-[510]">Paste one you received</span>
              </button>
            </div>
            {source === "paste" && (
              <div className="mt-3">
                <textarea value={pasted} onChange={(e) => setPasted(e.target.value)} rows={5} spellCheck={false}
                  placeholder="Paste the passport the agent attached to its message"
                  className={cn(inputCls, "h-auto py-2 font-mono text-[11.5px] leading-relaxed")} />
                {pasted.trim() && !base && <p className="mt-1.5 text-[12px] text-contradicted">That doesn&apos;t look like an {BRAND.name} passport.</p>}
              </div>
            )}
          </div>

          {passport && (
            <div>
              <SectionHead title="2. What it says">Read it like an ID card. Every field here is covered by the issuer&apos;s signature.</SectionHead>
              <div className={cn(cardCls, "mt-3 overflow-hidden")}>
                <div className="flex items-center justify-between gap-3 border-b border-border bg-elevated/60 px-4 py-2.5">
                  <span className="flex items-center gap-2 text-[12.5px] font-[510]"><IdCard className="size-4 text-muted-foreground" /> {passport.agent_name}</span>
                  {edited && <span className="rounded-full border border-flag/40 bg-flag/10 px-2 py-0.5 text-[11px] font-[510] text-flag">Edited after it was signed</span>}
                </div>
                <dl className="grid grid-cols-2 gap-x-6 gap-y-3.5 px-4 py-4 text-[13px]">
                  <Row k="Role" v={passport.role} />
                  <Row k="Acts for" v={passport.sponsor.name} />
                  <Row k="Their title" v={passport.sponsor.title ?? "–"} changed={tamper && edits.title !== undefined && edits.title !== base?.sponsor.title} />
                  <Row k="Company" v={passport.sponsor.company} />
                  <Row k="Issued" v={day(passport.issued_at)} />
                  <Row k="Expires" v={day(passport.expires_at)} />
                  <div className="col-span-2">
                    <dt className="text-[11.5px] text-faint">May do</dt>
                    <dd className="mt-1.5 flex flex-wrap gap-1.5">
                      {passport.scopes.map((sc) => (
                        <span key={sc} className={cn("inline-flex h-6 items-center rounded-md border px-2 text-[12px]", base?.scopes.includes(sc) ? "border-border-strong bg-elevated" : "border-flag/40 bg-flag/10 text-flag")}>
                          {SCOPE_INFO[sc]?.label ?? sc}
                        </span>
                      ))}
                    </dd>
                  </div>
                </dl>
              </div>

              <details className="mt-3 rounded-lg border border-border px-3 py-2" open={tamper} onToggle={(e) => setTamper((e.target as HTMLDetailsElement).open)}>
                <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[12.5px] font-[510] text-muted-foreground">
                  <Pencil className="size-3.5" /> Try tampering with it
                </summary>
                <p className="mt-1.5 text-[12px] text-muted-foreground">Change what a forger might change. The check should then refuse it, because the signature no longer matches.</p>
                <div className="mt-2.5 grid gap-2 sm:grid-cols-2">
                  <label className="text-[12px] text-muted-foreground">
                    Sponsor&apos;s title
                    <input value={edits.title ?? base?.sponsor.title ?? ""} onChange={(e) => setEdits((x) => ({ ...x, title: e.target.value }))} className={cn(inputCls, "mt-1")} />
                  </label>
                  <label className="text-[12px] text-muted-foreground">
                    Add a permission
                    <select value={edits.extra ?? ""} onChange={(e) => setEdits((x) => ({ ...x, extra: (e.target.value || undefined) as Scope | undefined }))} className={cn(inputCls, "mt-1")}>
                      <option value="">None</option>
                      {SCOPES.filter((s) => !base?.scopes.includes(s)).map((s) => <option key={s} value={s}>{SCOPE_INFO[s].label}</option>)}
                    </select>
                  </label>
                </div>
              </details>
            </div>
          )}

          {passport && (
            <div>
              <SectionHead title="3. Check it">Optionally, check it for the one thing it&apos;s asking you to accept.</SectionHead>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <select value={scope} onChange={(e) => setScope(e.target.value as Scope | "")} className={cn(inputCls, "w-auto")} aria-label="Check it for">
                  <option value="">For everything it claims</option>
                  {SCOPES.map((s) => <option key={s} value={s}>For {SCOPE_INFO[s].label.toLowerCase()}</option>)}
                </select>
                <Button variant="primary" onClick={verify} disabled={busy}>
                  {busy ? <Loader2 className="size-3.5 animate-spin" /> : <ShieldCheck className="size-3.5" />} Check passport
                </Button>
              </div>
              {error && <p className="mt-3 rounded-md border border-contradicted/30 bg-contradicted/[0.06] px-3 py-2 text-[12.5px] text-contradicted">{error}</p>}
            </div>
          )}
        </section>

        <section className="min-w-0 self-start lg:sticky lg:top-6">
          {result ? (
            <div className={cn(cardCls, "overflow-hidden animate-rise")}>
              <div className={cn("border-b px-5 py-4", result.verdict.decision === "allow" ? "border-verified/25 bg-verified/[0.06]" : "border-contradicted/25 bg-contradicted/[0.06]")}>
                <DecisionBadge decision={result.verdict.decision} />
                <p className="mt-2 text-[16px] font-[620] tracking-[-0.01em]">
                  {result.verdict.decision === "allow" ? `You can trust ${result.name}` : `Don't trust ${result.name}`}
                </p>
                <p className="mt-1 text-[12.5px] text-secondary">
                  {result.verdict.decision === "allow"
                    ? "The passport is genuine, still valid, and its sponsor checks out in Crustdata right now."
                    : `${result.edited ? "This passport was edited after it was signed. " : ""}At least one check failed, shown first. Don't act on what it asks.`}
                </p>
                <p className="mt-2 text-[11.5px] text-muted-foreground">
                  {result.verdict.checks.filter((c) => c.status === "pass").length} of {result.verdict.checks.length} checks passed · each names the record it read
                </p>
              </div>
              <div className="px-5 pb-3"><VerdictList verdict={result.verdict} /></div>
            </div>
          ) : agents.length ? (
            <div className={cardCls}>
              <EmptyState icon={ShieldCheck} title="The answer appears here" className="min-h-72 justify-center">
                Trust it or refuse it, with every check in plain words and the record behind it. Try Closer, whose sponsor left the company, or tamper with a passport to see a refusal.
              </EmptyState>
            </div>
          ) : (
            <div className={cardCls}>
              <EmptyState icon={IdCard} title="No passports to try yet" className="min-h-72 justify-center"
                action={<Button variant="primary" onClick={onOnboard}><Plus className="size-3.5" /> Connect an agent</Button>}>
                Connect an agent to issue its first passport, or paste one you received.
              </EmptyState>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

function Row({ k, v, changed }: { k: string; v: string; changed?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11.5px] text-faint">{k}</dt>
      <dd className={cn("mt-0.5 truncate font-[510]", changed && "text-flag")} title={v}>{v}</dd>
    </div>
  );
}
