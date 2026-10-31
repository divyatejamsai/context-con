"use client";
// What an opened ledger entry shows: the decision in plain language first (what was asked, what was checked, what was
// decided and why), then the sources it relied on folded into one short list, then the hash for an auditor.
// Payloads are never shown as raw JSON: known kinds get a layout, anything else becomes labelled facts.
import { useState } from "react";
import { CheckCircle2, ChevronRight, CircleDashed, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { brandText } from "@/lib/brand";
import type { Source } from "@/lib/types";
import { SCOPE_INFO, type Check, type LedgerEntry, type Scope } from "./api";
import { checkLabel, plain } from "./parts";

type P = Record<string, unknown>;
const str = (v: unknown) => (typeof v === "string" ? v : typeof v === "number" ? String(v) : undefined);
const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : undefined);
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const strs = (v: unknown): string[] => arr(v).map((x) => str(x)).filter((x): x is string => !!x);
const obj = (v: unknown): P => (v && typeof v === "object" && !Array.isArray(v) ? (v as P) : {});
const scopeLabel = (s: unknown) => (typeof s === "string" ? SCOPE_INFO[s as Scope]?.label ?? s : undefined);
const personText = (to: unknown) => {
  const t = obj(to);
  const n = str(t.name) ?? str(to);
  return n ? `${n}${str(t.company) ? `, ${t.company}` : ""}` : undefined;
};
export const duration = (ms?: number) =>
  ms === undefined ? undefined : ms < 1000 ? "under a second" : ms < 60_000 ? `${Math.round(ms / 1000)}s` : `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1000)}s`;

/* ---------- building blocks ---------- */

function Section({ title, children, aside }: { title: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section className="min-w-0">
      <div className="mb-1.5 flex items-baseline justify-between gap-3">
        <h4 className="text-[11.5px] font-[590] tracking-[0.01em] text-muted-foreground">{title}</h4>
        {aside && <span className="text-[11.5px] text-faint">{aside}</span>}
      </div>
      {children}
    </section>
  );
}

/** Label / value rows. Empty values are left out, so a sparse payload doesn't leave blank lines. */
function Facts({ rows }: { rows: [string, React.ReactNode][] }) {
  const shown = rows.filter(([, v]) => v !== undefined && v !== null && v !== "" && !(Array.isArray(v) && !v.length));
  if (!shown.length) return null;
  return (
    <dl className="grid grid-cols-1 gap-x-4 gap-y-1 text-[12.5px] leading-snug sm:grid-cols-[132px_minmax(0,1fr)]">
      {shown.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="pt-1 text-muted-foreground sm:pt-0">{k}</dt>
          <dd className="min-w-0 break-words text-foreground">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function Chips({ items, tone }: { items: string[]; tone?: "muted" }) {
  if (!items.length) return null;
  return (
    <span className="flex flex-wrap gap-1">
      {items.map((x, i) => (
        <span key={i} className={cn("rounded border border-border bg-panel px-1.5 py-px text-[11.5px]", tone === "muted" ? "text-muted-foreground" : "text-secondary")}>
          {x}
        </span>
      ))}
    </span>
  );
}

function Bullets({ items, tone }: { items: React.ReactNode[]; tone?: "bad" | "ok" | "warn" | "muted" }) {
  if (!items.length) return null;
  const dot = { bad: "bg-contradicted", ok: "bg-verified", warn: "bg-flag", muted: "bg-border-strong" }[tone ?? "muted"];
  return (
    <ul className="space-y-1 text-[12.5px] leading-snug">
      {items.map((x, i) => (
        <li key={i} className="flex gap-2">
          <span className={cn("mt-[6px] size-1.5 shrink-0 rounded-full", dot)} />
          <span className="min-w-0 break-words">{x}</span>
        </li>
      ))}
    </ul>
  );
}

function Quote({ children }: { children: React.ReactNode }) {
  return <blockquote className="whitespace-pre-wrap break-words border-l-2 border-border-strong pl-3 text-[12.5px] leading-relaxed text-secondary">{children}</blockquote>;
}

function CheckItem({ c }: { c: Check }) {
  const I = c.status === "pass" ? CheckCircle2 : c.status === "fail" ? XCircle : CircleDashed;
  return (
    <li className="flex gap-2 py-1.5 text-[12.5px] leading-snug">
      <I className={cn("mt-px size-3.5 shrink-0", c.status === "pass" ? "text-verified" : c.status === "fail" ? "text-contradicted" : "text-unverifiable")} />
      <span className="min-w-0 break-words">
        <span className="font-[510]">{checkLabel(c.name)}</span>
        {c.detail && <span className="text-muted-foreground">: {plain(c.detail)}</span>}
      </span>
    </li>
  );
}

/** Failed or unverifiable checks first, each with its reason; the passes fold into one line that opens. */
function Checks({ checks }: { checks: unknown }) {
  const [open, setOpen] = useState(false);
  const list = arr(checks).filter((c): c is Check => !!c && typeof c === "object" && typeof (c as Check).name === "string");
  if (!list.length) return null;
  const bad = list.filter((c) => c.status !== "pass");
  const ok = list.filter((c) => c.status === "pass");
  return (
    <Section title="What was checked" aside={`${ok.length} of ${list.length} passed`}>
      <div className="rounded-md border border-border bg-panel px-3 py-1">
        {bad.length > 0 && <ul className={cn(ok.length > 0 && "border-b border-border pb-1")}>{bad.map((c, i) => <CheckItem key={`${c.id}-${i}`} c={c} />)}</ul>}
        {ok.length > 0 && (
          <>
            <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-start gap-2 py-1.5 text-left text-[12.5px] leading-snug text-muted-foreground hover:text-foreground">
              <ChevronRight className={cn("mt-px size-3.5 shrink-0 transition", open && "rotate-90")} />
              <span className="min-w-0">{bad.length ? `${ok.length} other checks passed` : `All ${ok.length} checks passed`}{!open && <span className="text-faint">: {ok.map((c) => checkLabel(c.name)).join(", ")}</span>}</span>
            </button>
            {open && <ul className="pb-1 pl-5">{ok.map((c, i) => <CheckItem key={`${c.id}-${i}`} c={c} />)}</ul>}
          </>
        )}
      </div>
    </Section>
  );
}

/* ---------- candidate search ---------- */

const TIER_LABEL = { shortlist: "Shortlisted", near_miss: "Near misses", below: "Below the bar" } as const;
type Tier = keyof typeof TIER_LABEL;
interface RunCand {
  id: string; name?: string; title?: string; company?: string; score?: number; tier?: Tier;
  reasons?: string[]; flags?: string[]; claims?: { verified?: number; contradicted?: number; unverifiable?: number };
  guard?: string; guard_reason?: string; sent?: string;
}

/** The filter object the orchestrator searched with, as "Titles: a, b · Location: c". */
function filterText(f: unknown): string[] {
  const label: Record<string, string> = {
    titles: "Titles", locations: "Location", seniority: "Seniority", skills: "Skills", schools: "Schools",
    companies: "Companies", industries: "Industries", min_years: "Experience", keywords: "Keywords", degrees: "Degrees",
  };
  const rank = Object.keys(label);
  return Object.entries(obj(f))
    .sort((a, b) => (rank.indexOf(a[0]) + 1 || 99) - (rank.indexOf(b[0]) + 1 || 99))
    .filter(([, v]) => v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && !v.length))
    .map(([k, v]) => {
      const val = Array.isArray(v) ? v.map((x) => str(x) ?? "").filter(Boolean).join(", ") : k === "min_years" ? `${v}+ years` : str(v) ?? Object.values(obj(v)).map(str).filter(Boolean).join(", ");
      return `${label[k] ?? k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())}: ${val}`;
    });
}

function CandidateRow({ c, rank }: { c: RunCand; rank: number }) {
  const k = c.claims ?? {};
  const proof = [
    k.verified ? `${k.verified} verified` : null,
    k.contradicted ? `${k.contradicted} contradicted` : null,
    k.unverifiable ? `${k.unverifiable} unverifiable` : null,
  ].filter(Boolean).join(" · ");
  return (
    <li className="py-2.5">
      <div className="flex items-start gap-3">
        <span className="w-4 shrink-0 pt-px text-right font-mono text-[11px] tabular-nums text-faint">{rank}</span>
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-baseline gap-x-2 text-[13px]">
            <span className="font-[590]">{c.name ?? c.id}</span>
            {(c.title || c.company) && <span className="text-[12px] text-muted-foreground">{[c.title, c.company].filter(Boolean).join(" at ")}</span>}
          </p>
          {c.reasons && c.reasons.length > 0 && (
            <ul className="mt-1 space-y-0.5 text-[12px] leading-snug text-secondary">
              {c.reasons.map((r, i) => <li key={i}>{brandText(r)}</li>)}
            </ul>
          )}
          {c.flags && c.flags.length > 0 && <p className="mt-1 text-[12px] leading-snug text-flag">{c.flags.join(" · ")}</p>}
          <p className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11.5px] text-faint">
            {proof && <span className={k.contradicted ? "text-contradicted" : undefined}>{proof}</span>}
            {c.guard === "allow" && <span className="text-verified">Send Guard cleared the outreach</span>}
            {c.guard === "block" && <span className="text-contradicted">Send Guard held the outreach{c.guard_reason ? `: ${plain(c.guard_reason)}` : ""}</span>}
            {c.sent && <span>Email {c.sent}</span>}
          </p>
        </div>
        {c.score !== undefined && (
          <span className={cn("shrink-0 rounded-md border px-1.5 py-px font-mono text-[11.5px] tabular-nums",
            c.tier === "shortlist" ? "border-verified/30 text-verified" : "border-border text-muted-foreground")}>{c.score}</span>
        )}
      </div>
    </li>
  );
}

function SearchStory({ p }: { p: P }) {
  const u = obj(p.understood);
  const sum = obj(p.summary);
  const threshold = num(p.threshold);
  // Entries written before the story fields existed still have the shortlist and the Send Guard outcomes.
  const guard = obj(p.guard);
  const cands: RunCand[] = arr(p.candidates).length
    ? (arr(p.candidates) as RunCand[])
    : arr(p.shortlist).map((x) => ({ ...(obj(x) as unknown as RunCand), tier: "shortlist" as Tier, guard: str(guard[str(obj(x).id) ?? ""]) }));
  const searches = arr(p.searches).map(obj);
  const years = num(u.min_years);
  const education = [...strs(u.schools), ...strs(u.degrees)];
  const ms = num(p.elapsed_ms) ?? num(sum.elapsed_ms);
  const tiers = (Object.keys(TIER_LABEL) as Tier[]).map((t) => [t, cands.filter((c) => (c.tier ?? "shortlist") === t)] as const).filter(([, l]) => l.length);
  const held = cands.filter((c) => c.guard === "block").length;
  const cleared = cands.filter((c) => c.guard === "allow").length;
  let rank = 0;

  return (
    <>
      {str(p.brief) && (
        <Section title="What was asked">
          <Quote>{str(p.brief)}</Quote>
        </Section>
      )}
      {Object.keys(u).length > 0 && (
        <Section title="How Sourced read the brief">
          <Facts rows={[
            ["Role", str(u.role)],
            ["Also searched as", strs(u.title_variants).filter((t) => t !== u.role).length ? <Chips items={strs(u.title_variants).filter((t) => t !== u.role)} tone="muted" /> : undefined],
            ["Seniority", str(u.seniority)],
            ["Experience", years !== undefined ? `${years}+ years` : undefined],
            ["Location", strs(u.locations).join(", ") || undefined],
            ["Skills", strs(u.skills).length ? <Chips items={strs(u.skills)} /> : undefined],
            ["Education", education.length || u.education_note ? <>{education.join(", ")}{u.education_note ? <span className="text-muted-foreground">{education.length ? " · " : ""}“{str(u.education_note)}”</span> : null}</> : undefined],
            ["Companies", strs(u.company_preferences).join(", ") || undefined],
            ["Must have", strs(u.must_haves).join(", ") || undefined],
            ["Nice to have", strs(u.nice_to_haves).join(", ") || undefined],
          ]} />
          {strs(p.assumptions).length > 0 && <p className="mt-2 text-[12px] leading-snug text-muted-foreground">Assumed: {strs(p.assumptions).map((a) => brandText(a)).join("; ")}</p>}
        </Section>
      )}
      {searches.length > 0 && (
        <Section title="Searches on Crustdata" aside={`${searches.length} ${searches.length === 1 ? "query" : "queries"}`}>
          <ol className="space-y-2">
            {searches.map((s, i) => (
              <li key={i} className="rounded-md border border-border bg-panel px-3 py-2">
                <p className="flex items-baseline justify-between gap-3 text-[12.5px]">
                  <span className="font-[510]">{i === 0 ? "" : "Broadened: "}{(str(s.strategy) ?? `search ${i + 1}`).replace(/^./, (c) => (i === 0 ? c.toUpperCase() : c))}</span>
                  {num(s.count) !== undefined && <span className="shrink-0 tabular-nums text-muted-foreground">{num(s.count)} {num(s.count) === 1 ? "profile" : "profiles"}</span>}
                </p>
                <p className="mt-0.5 text-[12px] leading-snug text-muted-foreground">{filterText(s.filters).join(" · ")}</p>
              </li>
            ))}
          </ol>
        </Section>
      )}
      {(num(sum.searched) !== undefined || ms !== undefined) && (
        <Section title="Result">
          <p className="text-[12.5px] leading-snug">
            {[
              num(sum.searched) !== undefined && `${num(sum.searched)} found`,
              num(sum.enriched) !== undefined && `${num(sum.enriched)} enriched and checked claim by claim`,
              num(sum.shortlisted) !== undefined && `${num(sum.shortlisted)} shortlisted${threshold !== undefined ? ` (score ${threshold} or more)` : ""}`,
              held || cleared ? `Send Guard cleared ${cleared}, held ${held}` : null,
              ms !== undefined && `took ${duration(ms)}`,
            ].filter(Boolean).join(" · ")}
          </p>
          {strs(p.notes).length > 0 && <p className="mt-1 text-[12px] text-muted-foreground">{strs(p.notes).map(brandText).join(" · ")}</p>}
        </Section>
      )}
      {tiers.map(([t, list]) => (
        <Section key={t} title={TIER_LABEL[t]} aside={t === "below" && threshold !== undefined ? `scored under ${threshold}` : `${list.length}`}>
          <ol className="divide-y divide-border rounded-md border border-border bg-panel px-3">
            {list.map((c) => <CandidateRow key={c.id} c={c} rank={++rank} />)}
          </ol>
        </Section>
      ))}
    </>
  );
}

/* ---------- other kinds ---------- */

function WorkStory({ kind, p }: { kind: string; p: P }) {
  const d = obj(p.details);
  if (kind === "work.outreach_run") {
    const leads = arr(d.leads).map(obj);
    return (
      <Section title="Leads worked" aside={str(p.summary)}>
        <ul className="divide-y divide-border rounded-md border border-border bg-panel px-3 text-[12.5px]">
          {leads.map((l, i) => (
            <li key={i} className="flex items-baseline justify-between gap-3 py-2">
              <span className="min-w-0"><span className="font-[510]">{str(l.lead)}</span>{str(l.crm_company) && <span className="text-muted-foreground"> · {str(l.crm_company)}</span>}</span>
              <span className={cn("shrink-0", l.decision === "allow" ? "text-verified" : "text-contradicted")}>
                {l.decision === "allow" ? (l.sent ? "Cleared and sent" : "Cleared") : "Held by Send Guard"}
              </span>
            </li>
          ))}
        </ul>
      </Section>
    );
  }
  if (kind === "work.resume_check") {
    const contra = arr(d.contradicted).map(obj);
    return (
      <>
        <Facts rows={[["Candidate", str(d.candidate)], ["Read by", str(d.extracted_by)]]} />
        {contra.length > 0 && (
          <Section title="Contradicted by the records">
            <Bullets tone="bad" items={contra.map((c, i) => <span key={i}><b className="font-[590]">{str(c.claim)}</b><span className="text-muted-foreground">: {plain(str(c.evidence))}</span></span>)} />
          </Section>
        )}
        {strs(d.verified).length > 0 && <Section title="Verified"><Bullets tone="ok" items={strs(d.verified)} /></Section>}
        {strs(d.unverifiable).length > 0 && <Section title="Couldn't be checked"><Bullets items={strs(d.unverifiable)} /></Section>}
      </>
    );
  }
  if (kind === "work.vendor_brief") {
    const b = obj(d.brief);
    return (
      <>
        <Facts rows={[["Vendor", str(d.domain)], ["Verdict", str(b.verdict) ? brandText(str(b.verdict)) : undefined]]} />
        {strs(b.strengths).length > 0 && <Section title="Strengths"><Bullets tone="ok" items={strs(b.strengths)} /></Section>}
        {strs(b.risks).length > 0 && <Section title="Risks"><Bullets tone="warn" items={strs(b.risks)} /></Section>}
        {strs(b.questions_for_vendor).length > 0 && <Section title="Questions for the vendor"><Bullets items={strs(b.questions_for_vendor)} /></Section>}
      </>
    );
  }
  return <GenericFacts p={d && Object.keys(d).length ? d : p} />;
}

function sponsorText(s: unknown) {
  const o = obj(s);
  if (!str(o.name)) return undefined;
  return [str(o.name), str(o.title), str(o.company)].filter(Boolean).join(", ");
}

function KindStory({ e, names }: { e: LedgerEntry; names: Map<string, string> }): React.ReactNode {
  const p = e.payload as P;
  const k = e.kind;
  const agent = (id: unknown) => (typeof id === "string" ? names.get(id) ?? undefined : undefined);
  if (k === "run.finished") return <SearchStory p={p} />;
  if (k === "run.started" || k === "campaign.started" || k === "flow.started")
    return (
      <>
        {str(p.brief) && <Section title="Brief"><Quote>{str(p.brief)}</Quote></Section>}
        <Facts rows={[["Candidates", str(p.candidates)], ["Job", str(p.job)], ["Mode", str(p.mode)], ["Started by", str(p.by)]]} />
      </>
    );
  if (k === "guard.verdict")
    return (
      <>
        <Facts rows={[
          ["Decision", p.decision === "allow" ? <span className="text-verified">Allowed to send</span> : <span className="text-contradicted">Blocked</span>],
          ["To", personText(p.to)],
          ["Purpose", scopeLabel(p.scope)],
          ["Message", str(p.body_sha256) ? <span className="font-mono text-[11px] text-muted-foreground">fingerprint {str(p.body_sha256)!.slice(0, 12)}</span> : undefined],
        ]} />
        <Checks checks={p.checks} />
      </>
    );
  if (k === "passport.verified" || k === "flow.handoff")
    return (
      <>
        <Facts rows={[
          ["Decision", p.decision === undefined ? undefined : p.decision === "allow" ? <span className="text-verified">Trusted</span> : <span className="text-contradicted">Not trusted</span>],
          ["Asked for", scopeLabel(p.scope)],
          ["Stage", str(p.stage)],
          ["Handed to", agent(p.to) ?? str(p.to)],
        ]} />
        <Checks checks={p.checks} />
      </>
    );
  if (k === "passport.issued" || k === "agent.onboarded" || k === "agent.enrolled") {
    const pp = obj(p.passport);
    const sp = p.sponsor ?? pp.sponsor;
    return (
      <Facts rows={[
        ["Role", str(p.role) ?? str(pp.role)],
        ["Vouched for by", sponsorText(sp)],
        ["Can", strs(p.scopes).length || strs(pp.scopes).length ? <Chips items={(strs(p.scopes).length ? strs(p.scopes) : strs(pp.scopes)).map((s) => scopeLabel(s) ?? s)} /> : undefined],
        ["Runs", str(p.runtime)],
        ["Key held by", str(p.key_custody)],
        ["Valid until", str(p.expires_at ?? pp.expires_at)?.slice(0, 10)],
      ]} />
    );
  }
  if (k === "runtime.payroll") {
    const sus = arr(p.suspended).map((x) => agent(obj(x).agent_id) ?? str(obj(x).name) ?? str(x)).filter(Boolean) as string[];
    return (
      <Facts rows={[
        ["Sponsors checked", str(p.checked)],
        ["Still valid", str(p.allowed)],
        ["Suspended", sus.length ? sus.join(", ") : "none"],
        ["Run by", str(p.by)],
      ]} />
    );
  }
  if (k === "message.sent")
    return (
      <Facts rows={[
        ["To", personText(p.to)],
        ["Subject", str(p.subject)],
        ["Delivered to", str(p.delivered_to)],
        ["Purpose", scopeLabel(p.scope)],
        ["How", [str(p.mode), str(p.provider)].filter(Boolean).join(" via ") || undefined],
      ]} />
    );
  if (k === "offer.signed")
    return (
      <Facts rows={[
        ["Candidate", str(p.candidate) ?? personText(p.to)],
        ["Pay", num(p.ctc_lpa) !== undefined ? `${num(p.ctc_lpa)} LPA` : undefined],
        ["Offer version", str(p.offer_version)],
        ["Approved by", str(p.approved_by)],
        ["Edited before signing", p.edited === undefined ? undefined : p.edited ? "yes" : "no"],
      ]} />
    );
  if (k === "resume.verified")
    return (
      <>
        <Facts rows={[["Candidate", str(p.name)], ["Claims verified", num(p.verified) !== undefined ? `${num(p.verified)} of ${num(p.total)}` : undefined]]} />
        {strs(p.contradicted).length > 0 && <Section title="Contradicted"><Bullets tone="bad" items={strs(p.contradicted)} /></Section>}
      </>
    );
  if (k.startsWith("work.")) return <WorkStory kind={k} p={p} />;
  return <GenericFacts p={p} />;
}

// Ids, hashes and keys mean nothing to a reader; the hash line at the bottom is where an auditor finds them.
const HIDDEN = /(^|_)(sha256|hash|entry|signature|public_key|key_id|id|ids|message_id|provider_id|thread_key)$/;
const human = (k: string) => k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

/** Any other entry: its readable fields as label / value rows, one level deep. */
function GenericFacts({ p }: { p: P }) {
  const rows: [string, React.ReactNode][] = [];
  for (const [k, v] of Object.entries(p)) {
    if (HIDDEN.test(k) || k === "checks" || k === "by" && v === "employer") continue;
    if (typeof v === "string" || typeof v === "number") rows.push([human(k), brandText(String(v))]);
    else if (typeof v === "boolean") rows.push([human(k), v ? "yes" : "no"]);
    else if (Array.isArray(v)) {
      const s = v.map((x) => str(x) ?? personText(x)).filter(Boolean) as string[];
      if (s.length) rows.push([human(k), s.join(", ")]);
    } else if (v && typeof v === "object") {
      const t = personText(v) ?? Object.entries(v as P).filter(([kk, x]) => !HIDDEN.test(kk) && (typeof x === "string" || typeof x === "number")).map(([kk, x]) => `${human(kk)}: ${x}`).join(" · ");
      if (t) rows.push([human(k), t]);
    }
  }
  return (
    <>
      <Facts rows={rows.slice(0, 14)} />
      <Checks checks={p.checks} />
    </>
  );
}

/* ---------- sources and the hash ---------- */

// Agaxes' own fields (issuer key, registry) sort after the Crustdata citations, which are the evidence.
const isInternal = (endpoint: string) => endpoint.startsWith("countersign/") || endpoint === "passport";

function SourcesUsed({ sources }: { sources: Source[] }) {
  const [open, setOpen] = useState(false);
  if (!sources.length) return null;
  const groups = new Map<string, { fields: Set<string>; urls: Set<string> }>();
  for (const s of sources) {
    if (!s?.endpoint) continue;
    const g = groups.get(s.endpoint) ?? { fields: new Set(), urls: new Set() };
    // Collapse array positions: past[1].start_date and past[4].start_date are the same field.
    if (s.field) g.fields.add(s.field.replace(/\[\d+\]/g, "[]"));
    if (s.url) g.urls.add(s.url);
    groups.set(s.endpoint, g);
  }
  const list = [...groups].sort((a, b) => Number(isInternal(a[0])) - Number(isInternal(b[0])));
  const fields = list.reduce((n, [, g]) => n + g.fields.size, 0);
  return (
    <section>
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="inline-flex items-center gap-1 text-[12px] font-[510] text-muted-foreground hover:text-foreground">
        <ChevronRight className={cn("size-3.5 transition", open && "rotate-90")} />
        Sources used ({fields || sources.length} {fields === 1 ? "field" : "fields"} from {list.length} {list.length === 1 ? "source" : "sources"})
      </button>
      {open && (
        <ul className="mt-2 space-y-2">
          {list.map(([ep, g]) => (
            <li key={ep} className="text-[12px]">
              <p className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-mono text-[11px] text-secondary">{brandText(ep)}</span>
                <span className="text-faint">
                  {g.fields.size ? `${g.fields.size} ${g.fields.size === 1 ? "field" : "fields"}` : g.urls.size ? "" : "consulted"}
                  {g.urls.size ? `${g.fields.size ? " · " : ""}${g.urls.size} ${g.urls.size === 1 ? "record" : "records"}` : ""}
                </span>
              </p>
              {g.fields.size > 0 && (
                <p className="mt-1 flex flex-wrap gap-1">
                  {[...g.fields].sort().map((f) => <span key={f} className="max-w-full break-all rounded border border-border bg-panel px-1.5 py-px font-mono text-[10.5px] text-muted-foreground">{f}</span>)}
                </p>
              )}
              {g.urls.size > 0 && (
                <p className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
                  {[...g.urls].slice(0, 8).map((u) => (
                    <a key={u} href={u} target="_blank" rel="noreferrer" className="max-w-full truncate text-[11.5px] text-primary hover:underline">{u.replace(/^https?:\/\/(www\.)?/, "")}</a>
                  ))}
                  {g.urls.size > 8 && <span className="text-[11.5px] text-faint">and {g.urls.size - 8} more</span>}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Seal({ e }: { e: LedgerEntry }) {
  const [open, setOpen] = useState(false);
  return (
    <section className="font-mono text-[10.5px] text-faint">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="inline-flex items-center gap-1 hover:text-muted-foreground" title="The hash that chains this entry to the one before it">
        <ChevronRight className={cn("size-3 transition", open && "rotate-90")} />
        Entry #{e.seq} · {e.kind} · {e.hash.slice(0, 12)}
      </button>
      {open && (
        <div className="mt-1 space-y-0.5 pl-4">
          <p>{e.ts}</p>
          <p className="break-all">hash {e.hash}</p>
          <p className="break-all">prev {e.prev_hash}</p>
        </div>
      )}
    </section>
  );
}

export function EntryDetail({ e, names }: { e: LedgerEntry; names: Map<string, string> }) {
  return (
    <div className="mt-2.5 space-y-4 rounded-lg border border-border bg-elevated/60 px-3.5 py-3">
      <KindStory e={e} names={names} />
      <div className="space-y-1.5 border-t border-border pt-2.5">
        <SourcesUsed sources={e.sources} />
        <Seal e={e} />
      </div>
    </div>
  );
}
