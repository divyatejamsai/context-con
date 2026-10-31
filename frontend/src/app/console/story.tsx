"use client";
// Turns raw ledger entries into plain sentences: who did what, to whom, with what outcome. The raw entry (hash, ids,
// sources) stays one click away under "Details", so nothing is hidden from an auditor.
import { useState } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { brandText } from "@/lib/brand";
import { SCOPE_INFO, type Agent, type LedgerEntry, type Scope } from "./api";
import { checkLabel, plain } from "./parts";
import { EntryDetail, duration } from "./ledger-detail";

/** run.finished carries the run's counts as an object ({searched, enriched, shortlisted, elapsed_ms}), not a sentence. */
function runSummary(p: Record<string, unknown>): string | undefined {
  const s = p.summary;
  if (typeof s === "string") return s ? brandText(s) : undefined;
  const n = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : undefined);
  const o = s && typeof s === "object" ? (s as Record<string, unknown>) : {};
  const shortlisted = n(o.shortlisted) ?? (Array.isArray(p.shortlist) ? p.shortlist.length : undefined);
  const searched = n(o.searched), enriched = n(o.enriched), ms = n(p.elapsed_ms) ?? n(o.elapsed_ms);
  const parts = [
    shortlisted !== undefined && `${shortlisted} shortlisted${searched ? ` from ${searched} found` : ""}`,
    enriched && `${enriched} checked against Crustdata`,
    ms !== undefined && `took ${duration(ms)}`,
  ].filter(Boolean);
  return parts.length ? parts.join(", ") : undefined;
}

const KIND_LABEL: Record<string, string> = {
  "passport.issued": "Passport issued",
  "passport.verified": "Passport checked",
  "passport.revoked": "Passport revoked",
  "passport.reinstated": "Passport reinstated",
  "guard.verdict": "Message checked by the Send Guard",
  "agent.onboarded": "Onboarded",
  "agent.offboarded": "Offboarded",
  "agent.reviewed": "Reviewed",
  "agent.scopes_changed": "Scopes changed",
  "agent.scope_denied": "Scope refused",
  "agent.scopes_checked": "Sponsor checked for new scopes",
  "work.outreach_run": "Work filed: outreach run",
  "work.vendor_brief": "Work filed: vendor brief",
  "work.resume_check": "Work filed: resume check",
  "run.started": "Hiring run started",
  "run.finished": "Hiring run finished",
  "resume.verified": "Resume checked",
  "agent.enrollment_created": "Outside agent invited",
  "agent.enrollment_revoked": "Invite cancelled",
  "agent.enrolled": "Outside agent connected with its own key",
  "agent.paused": "Paused",
  "agent.resumed": "Resumed",
  "passport.key_rotated": "Signing key rotated",
  "ledger.exported": "Audit log exported",
  "workspace.role_changed": "Member's role changed",
  "workspace.member_removed": "Member removed",
  "task.assigned": "Task assigned",
  "task.started": "Task started",
  "task.retry": "Task retried",
  "task.interrupted": "Task interrupted",
  "runtime.approval": "Send approval decided",
  "runtime.payroll": "Payroll run",
  "runtime.policy": "Policy changed",
  "runtime.schedule": "Schedule changed",
  "message.sent": "Message sent",
  "message.reply": "Reply received",
  "message.status": "Message status",
  "campaign.started": "Campaign started",
  "offer.signed": "Offer signed",
};

export const kindLabel = (k: string) => KIND_LABEL[k] ?? (k.startsWith("work.") ? `Work filed: ${k.slice(5).replace(/_/g, " ")}` : k);

export type Category = "messages" | "trust" | "work" | "access" | "system";
export const CATEGORIES: { k: Category | ""; label: string }[] = [
  { k: "", label: "Everything" },
  { k: "messages", label: "Messages" },
  { k: "trust", label: "Trust checks" },
  { k: "work", label: "Work" },
  { k: "access", label: "Agents & access" },
];

type Tone = "ok" | "bad" | "warn" | "neutral";
type P = Record<string, unknown> & {
  agent_id?: string; subject?: string; decision?: string; reason?: string; by?: string; scope?: string | null; summary?: string;
  to?: unknown; from?: unknown; checks?: { name: string; status: string; detail: string }[]; title?: string; note?: string;
};
interface Line { text: React.ReactNode; detail?: React.ReactNode; tone: Tone; cat: Category; noise?: boolean }

export function category(kind: string): Category {
  if (kind === "guard.verdict" || kind.startsWith("message.") || kind === "runtime.approval") return "messages";
  if (kind.startsWith("passport.") && kind !== "passport.key_rotated") return "trust";
  if (kind === "agent.scopes_checked" || kind === "agent.checked" || kind === "runtime.payroll" || kind === "agent.scope_denied") return "trust";
  if (kind.startsWith("task.") || kind.startsWith("work.") || kind.startsWith("run.") || kind.startsWith("campaign.") || kind === "offer.signed" || kind === "resume.verified") return "work";
  if (kind === "ledger.exported") return "system";
  return "access";
}

const scopeName = (s?: string | null) => (s ? SCOPE_INFO[s as Scope]?.label.toLowerCase() ?? s : "");
const person = (to: unknown) => {
  const t = to as { name?: string; company?: string } | undefined;
  return t?.name ? `${t.name}${t.company ? ` (${t.company})` : ""}` : "someone";
};
const firstFail = (p: P) => p.checks?.find((c) => c.status === "fail") ?? p.checks?.find((c) => c.status !== "pass");
const failText = (p: P) => {
  const f = firstFail(p);
  return f ? plain(f.detail) || checkLabel(f.name) : undefined;
};
const isSetup = (p: P) => typeof p.by === "string" && /demo setup|seed|fixture/i.test(p.by);

/** One plain sentence for an entry. `who` is the agent's name, `sponsor` the person it acts for. */
export function describe(e: LedgerEntry, names: Map<string, string>): Line {
  const p = e.payload as P;
  const id = p.agent_id ?? p.subject ?? ((p.passport as { agent_id?: string } | undefined)?.agent_id);
  const who = <b className="font-[590]">{(id && names.get(id)) || (p.agent_name as string) || "An agent"}</b>;
  const by = e.actor?.email ?? (typeof p.by === "string" && p.by !== "employer" ? p.by : undefined);
  const cat = category(e.kind);
  const noise = isSetup(p) || e.kind === "ledger.exported" || e.kind === "message.status" || e.kind === "task.started";

  switch (e.kind) {
    case "guard.verdict":
      return p.decision === "allow"
        ? { cat, noise, tone: "ok", text: <>Send Guard let {who}&apos;s {scopeName(p.scope) || "message"} to {person(p.to)} through</> }
        : { cat, noise, tone: "bad", text: <>Send Guard blocked {who}&apos;s {scopeName(p.scope) || "message"} to {person(p.to)}</>, detail: failText(p) };
    case "passport.verified":
      return p.decision === "allow"
        ? { cat, noise, tone: "ok", text: <>{who}&apos;s passport was checked{p.scope ? ` for ${scopeName(p.scope)}` : ""}: trusted</> }
        : { cat, noise, tone: "bad", text: <>{who}&apos;s passport was checked{p.scope ? ` for ${scopeName(p.scope)}` : ""}: not trusted</>, detail: failText(p) };
    case "passport.issued": {
      const sp = (p.passport as { sponsor?: { name?: string; company?: string } } | undefined)?.sponsor;
      return { cat, noise, tone: "neutral", text: <>{who} was issued a passport{sp?.name ? <>, vouched for by {sp.name}{sp.company ? ` at ${sp.company}` : ""}</> : null}</> };
    }
    case "passport.revoked":
      return { cat, noise, tone: "bad", text: <>{who}&apos;s passport was revoked</>, detail: p.reason ? plain(p.reason) : undefined };
    case "passport.reinstated":
      return { cat, noise, tone: "ok", text: <>{who}&apos;s passport was reinstated after a fresh sponsor check</>, detail: p.reason ? plain(p.reason) : undefined };
    case "passport.key_rotated":
      return { cat, noise, tone: "neutral", text: <>{who} rotated its signing key. Anything signed with the old key no longer verifies</> };
    case "agent.onboarded": {
      const sp = p.sponsor as { name?: string; company?: string } | undefined;
      return { cat, noise, tone: "neutral", text: <>{who} was connected as {String(p.role ?? "an agent")}{sp?.name ? ` for ${sp.name}${sp.company ? `, ${sp.company}` : ""}` : ""}{p.runtime === "external" ? ", running on its own machine" : ""}</> };
    }
    case "agent.enrolled":
      return { cat, noise, tone: "ok", text: <>{who} connected from its own machine and proved it holds its own key</> };
    case "agent.enrollment_created":
      return { cat, noise, tone: "neutral", text: <>{by ?? "An admin"} invited an outside agent, <b className="font-[590]">{String(p.name ?? "")}</b>, with a one-time command</> };
    case "agent.enrollment_revoked":
      return { cat, noise, tone: "neutral", text: <>{by ?? "An admin"} cancelled an outside agent&apos;s invite</> };
    case "agent.offboarded":
      return { cat, noise, tone: "bad", text: <>{who} was offboarded{by ? ` by ${by}` : ""}</>, detail: p.reason ? plain(p.reason) : undefined };
    case "agent.reviewed":
      return { cat, noise, tone: p.decision === "keep" ? "ok" : "warn", text: <>{String(p.reviewer ?? by ?? "Someone")} reviewed {who}: {String(p.decision ?? "")}</>, detail: p.notes ? String(p.notes) : undefined };
    case "agent.scopes_changed": {
      const to = (p.to as string[] | undefined) ?? [];
      const from = (p.from as string[] | undefined) ?? [];
      const added = to.filter((s) => !from.includes(s)).map(scopeName);
      const removed = from.filter((s) => !to.includes(s)).map(scopeName);
      return { cat, noise, tone: "neutral", text: <>{who}&apos;s permissions changed{added.length ? `: may now ${added.join(", ")}` : ""}{removed.length ? `${added.length ? ";" : ":"} no longer ${removed.join(", ")}` : ""}</> };
    }
    case "agent.scopes_checked":
      return { cat, noise, tone: p.decision === "allow" ? "ok" : "bad", text: <>{who}&apos;s sponsor was checked for new permissions: {p.decision === "allow" ? "approved" : "refused"}</>, detail: p.decision === "allow" ? undefined : failText(p) };
    case "agent.scope_denied":
      return { cat, noise, tone: "bad", text: <>{who} tried to {scopeName(p.scope) || "act"} without permission and was refused</> };
    case "agent.paused":
      return { cat, noise, tone: "warn", text: <>{by ?? "Someone"} paused {who}</>, detail: p.reason ? String(p.reason) : undefined };
    case "agent.resumed":
      return { cat, noise, tone: "neutral", text: <>{by ?? "Someone"} resumed {who}</> };
    case "agent.workspace_changed":
      return { cat, noise, tone: "neutral", text: <>{who} was {p.to ? "placed in a company" : "moved back to the platform"}{by ? ` by ${by}` : ""}</> };
    case "agent.assignees_changed":
      return { cat, noise, tone: "neutral", text: <>The people who work with {who} changed ({((p.to as string[]) ?? []).length} assigned)</> };
    case "runtime.payroll":
      return {
        cat, noise, tone: ((p.suspended as string[]) ?? []).length ? "bad" : "ok",
        text: <>Payroll re-checked {String(p.checked ?? "every")} sponsors: {String(p.allowed ?? 0)} still valid, {((p.suspended as string[]) ?? []).length} newly suspended{Number(p.checked) - Number(p.allowed) - ((p.suspended as string[]) ?? []).length > 0 ? `, ${Number(p.checked) - Number(p.allowed) - ((p.suspended as string[]) ?? []).length} already suspended` : ""}</>,
      };
    case "runtime.approval":
      return p.decision === "approved"
        ? { cat, noise, tone: p.outcome === "sent" ? "ok" : "bad", text: <>{by ?? "Someone"} approved {who}&apos;s message to {person(p.to)}{p.edited ? " after editing it" : ""}{p.outcome === "sent" ? ": sent to the outbox" : `: ${String(p.outcome ?? "not sent")}`}</> }
        : { cat, noise, tone: "warn", text: <>{by ?? "Someone"} rejected {who}&apos;s message to {person(p.to)}</>, detail: p.note ? String(p.note) : undefined };
    case "runtime.policy":
      return { cat, noise, tone: "neutral", text: <>{by ?? "Someone"} changed {who}&apos;s rules{p.require_approval ? ": sends need approval" : ""}</> };
    case "runtime.schedule":
      return { cat, noise, tone: "neutral", text: <>{who}&apos;s recurring work was {String(p.action ?? "changed")}{p.every_minutes ? `, every ${p.every_minutes} min` : ""}</> };
    case "task.assigned":
      return { cat, noise, tone: "neutral", text: <>{by ?? "Someone"} gave {who} a task: {String(p.title ?? p.kind ?? "")}</> };
    case "task.started":
      return { cat, noise, tone: "neutral", text: <>{who} started: {String(p.title ?? "")}</> };
    case "task.retry":
      return { cat, noise, tone: "warn", text: <>{who} hit an error and will retry</>, detail: p.error ? String(p.error) : undefined };
    case "task.interrupted":
      return { cat, noise, tone: "warn", text: <>{who}&apos;s task was stopped</>, detail: p.why ? String(p.why) : undefined };
    case "run.started":
      return { cat, noise, tone: "neutral", text: <>{who} started a candidate search</>, detail: p.brief ? `“${String(p.brief).split("\n")[0]}”` : undefined };
    case "run.finished":
      return { cat, noise, tone: "ok", text: <>{who} finished a candidate search{typeof (p.understood as { role?: unknown } | undefined)?.role === "string" ? <> for {String((p.understood as { role: string }).role)}</> : null}</>, detail: runSummary(p) };
    case "campaign.started":
      return { cat, noise, tone: "neutral", text: <>{who} started a hiring campaign with {String(p.candidates ?? "")} candidates</>, detail: p.brief ? `“${String(p.brief).split("\n")[0]}”` : undefined };
    case "offer.signed":
      return { cat, noise, tone: "ok", text: <>{String(p.candidate ?? "The candidate")} signed {who}&apos;s offer{p.ctc_lpa ? ` at ${p.ctc_lpa} LPA` : ""}</> };
    case "resume.verified": {
      const bad = ((p.contradicted as string[]) ?? []).length;
      return { cat, noise, tone: bad ? "warn" : "ok", text: <>{String(p.name ?? "A candidate")}&apos;s resume was checked: {String(p.verified ?? 0)} of {String(p.total ?? 0)} claims verified{bad ? `, ${bad} false` : ""}</> };
    }
    case "message.sent":
      return { cat, noise, tone: "ok", text: <>{who}&apos;s email to {person(p.to)} went out{p.delivered_to ? ` (delivered to the test inbox ${String(p.delivered_to)}, not the person)` : ""}</> };
    case "connect.requested": {
      const risky = (p.needs_review as string[] | undefined) ?? [];
      return { cat, noise, tone: risky.length ? "warn" : "neutral", text: <>{by ?? String(p.requested_by ?? "An admin")} asked to connect <b className="font-[590]">{String(p.name ?? "an agent")}</b>{risky.length ? `, with high-risk ${risky.join(", ")} that needs another admin` : ""}</>,
        detail: `Owner ${String(p.owner ?? "the sponsor")} · sponsor ${String(p.sponsor ?? "")} · ${((p.scopes as string[]) ?? []).join(", ")}` };
    }
    case "connect.approved":
      return { cat, noise, tone: "ok", text: <>{by ?? "An admin"} approved connecting <b className="font-[590]">{String(p.name ?? "an agent")}</b>{p.sole_admin ? " (the only admin in the company)" : ""}</>, detail: p.note ? String(p.note) : undefined };
    case "connect.rejected":
      return { cat, noise, tone: "bad", text: <>{by ?? "An admin"} rejected connecting <b className="font-[590]">{String(p.name ?? "an agent")}</b></>, detail: p.note ? String(p.note) : undefined };
    case "connect.cancelled":
      return { cat, noise, tone: "neutral", text: <>{by ?? "An admin"} cancelled connecting <b className="font-[590]">{String(p.name ?? "an agent")}</b></> };
    case "connect.issued":
      return { cat, noise, tone: p.decision === "allow" ? "ok" : "bad", text: <>{who}&apos;s passport was issued{p.decision === "allow" ? " and its sponsor checked out" : ", but its sponsor check failed"}</> };
    case "connect.policy":
      return { cat, noise: true, tone: "neutral", text: <>{who} got its tools and daily limits</>, detail: ((p.tools as string[]) ?? []).join(", ") || undefined };
    case "agent.first_heartbeat":
      return { cat, noise, tone: "ok", text: <>{who} made its first signed call{p.via === "agent" ? " from its own machine" : ""}</> };
    case "message.reply":
      return { cat, noise, tone: "ok", text: <>{person(p.from ?? p.to)} replied to {who}</> };
    case "message.status":
      return { cat, noise, tone: p.status === "bounced" ? "bad" : "neutral", text: <>{who}&apos;s email was {String(p.status ?? "updated")}</> };
    case "ledger.exported":
      return { cat, noise, tone: "neutral", text: <>{by ?? "Someone"} exported the audit log ({String(p.count ?? "")} entries)</> };
    case "workspace.role_changed":
      return { cat, noise, tone: "neutral", text: <>{by ?? "An owner"} made {String(p.email ?? "someone")} {String(p.to ?? "")}</> };
    case "workspace.member_removed":
      return { cat, noise, tone: "warn", text: <>{by ?? "An admin"} removed {String(p.email ?? "someone")} from the company</> };
  }
  if (e.kind.startsWith("work.")) {
    const verb = WORK_VERB[e.kind.slice(5)] ?? `filed a ${e.kind.slice(5).replace(/_/g, " ")}`;
    return { cat, noise, tone: "ok", text: <>{who} {verb}{p.signed ? " and signed it with its own key" : ""}</>, detail: p.summary ? brandText(String(p.summary)) : undefined };
  }
  return { cat, noise, tone: "neutral", text: <>{who}: {kindLabel(e.kind).toLowerCase()}</> };
}

const WORK_VERB: Record<string, string> = {
  outreach_run: "finished an outreach run",
  resume_check: "checked a resume against the employment records",
  vendor_brief: "wrote a vendor brief",
  candidate_search: "finished a candidate search",
};

/** Routine checks (messages Send Guard let through, passport checks) that run back to back fold into one summary row.
 * Anything that changes the story, like a block, a revocation or a payroll run, breaks the run and stays on its own line. */
const routine = (e: LedgerEntry) =>
  e.kind === "passport.verified" || (e.kind === "guard.verdict" && (e.payload as P).decision === "allow");

export function LedgerTimeline({
  entries, firstBad, names, className, limit = 80,
}: { entries: LedgerEntry[]; firstBad: number | null; names?: Map<string, string>; agents?: Agent[]; className?: string; limit?: number }) {
  const [more, setMore] = useState(1);
  const n = names ?? new Map<string, string>();
  const rows: LedgerEntry[][] = [];
  for (const e of entries) {
    const last = rows[rows.length - 1];
    if (routine(e) && last && routine(last[0])) last.push(e);
    else rows.push([e]);
  }
  const shown = rows.slice(0, limit * more);
  return (
    <div className={className}>
      <ol className="divide-y divide-border">
        {shown.map((g) => (g.length > 2 ? <GroupRow key={`${g[0].seq}-g`} group={g} names={n} firstBad={firstBad} /> : g.map((e) => <EntryRow key={`${e.seq}-${e.hash}`} e={e} names={n} firstBad={firstBad} />)))}
      </ol>
      {rows.length > shown.length && (
        <button onClick={() => setMore((m) => m + 1)} className="mt-3 text-[12.5px] font-[510] text-primary hover:underline">
          Show older ({rows.length - shown.length} more)
        </button>
      )}
    </div>
  );
}


const DOT: Record<Tone, string> = { ok: "bg-verified", bad: "bg-contradicted", warn: "bg-flag", neutral: "bg-border-strong" };
const when = (ts: string) => new Date(ts).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

function EntryRow({ e, names, firstBad, nested }: { e: LedgerEntry; names: Map<string, string>; firstBad: number | null; nested?: boolean }) {
  const [open, setOpen] = useState(false);
  const line = describe(e, names);
  const broken = firstBad !== null && firstBad !== undefined && e.seq >= firstBad;
  return (
    <li className={cn("py-2.5", nested && "py-1.5")}>
      <div className="flex items-start gap-3">
        <span className={cn("mt-[7px] size-2 shrink-0 rounded-full", broken ? "bg-contradicted" : DOT[line.tone])} />
        <div className="min-w-0 flex-1">
          <p className={cn("cursor-pointer text-[13px] leading-snug", nested && "text-[12.5px]")} onClick={() => setOpen(!open)}>{line.text}</p>
          {line.detail && <p className="mt-0.5 break-words text-[12.5px] leading-snug text-muted-foreground">{line.detail}</p>}
          {e.actor?.email && !nested && <p className="mt-0.5 text-[11.5px] text-faint">by {e.actor.email}{e.actor.role ? ` (${e.actor.role})` : ""}</p>}
          {broken && e.seq === firstBad && <p className="mt-1 text-[12px] font-[510] text-contradicted">The chain breaks here: this entry or the one before it was changed.</p>}
        </div>
        <span className="flex shrink-0 items-center gap-1">
          <span className="text-[11.5px] tabular-nums text-faint" title={e.ts}>{when(e.ts)}</span>
          <button onClick={() => setOpen(!open)} aria-expanded={open} title={open ? "Hide details" : "What happened, what was checked, and the sources"}
            className="grid size-6 place-items-center rounded text-faint hover:bg-hover hover:text-foreground">
            <ChevronRight className={cn("size-3.5 transition", open && "rotate-90")} />
          </button>
        </span>
      </div>
      {/* Full width under the row (indented past the dot on wider screens), so it isn't squeezed beside the time on a phone. */}
      {open && <div className="sm:pl-5"><EntryDetail e={e} names={names} /></div>}
    </li>
  );
}

function GroupRow({ group, names, firstBad }: { group: LedgerEntry[]; names: Map<string, string>; firstBad: number | null }) {
  const [open, setOpen] = useState(false);
  const name = (x: LedgerEntry) => names.get(String((x.payload as P).agent_id)) ?? "an agent";
  const sends = group.filter((x) => x.kind === "guard.verdict");
  const checks = group.filter((x) => x.kind === "passport.verified");
  const untrusted = checks.filter((x) => (x.payload as P).decision !== "allow");
  const byAgent = new Map<string, number>();
  for (const x of sends) byAgent.set(name(x), (byAgent.get(name(x)) ?? 0) + 1);
  const senders = [...byAgent].sort((a, b) => b[1] - a[1]);
  const parts: React.ReactNode[] = [];
  if (sends.length)
    parts.push(senders.length === 1
      ? <>Send Guard let {sends.length} of <b className="font-[590]">{senders[0][0]}</b>&apos;s messages through</>
      : <>Send Guard let {sends.length} messages through ({senders.map(([n, c]) => `${n} ${c}`).join(", ")})</>);
  if (checks.length)
    parts.push(<>{checks.length} passport checks, {checks.length - untrusted.length} trusted{untrusted.length ? `, ${untrusted.length} not (${[...new Set(untrusted.map(name))].join(", ")}, already suspended)` : ""}</>);
  const people = [...new Set(sends.map((x) => ((x.payload as P).to as { name?: string } | undefined)?.name).filter(Boolean))] as string[];
  const broken = firstBad !== null && firstBad !== undefined && group.some((x) => x.seq >= firstBad);
  const first = group[group.length - 1].ts;
  const last = group[0].ts;
  return (
    <li className="py-2.5">
      <div className="flex items-start gap-3">
        <span className={cn("mt-[7px] size-2 shrink-0 rounded-full", broken ? "bg-contradicted" : "bg-verified/60")} />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] leading-snug">
            {parts.map((x, i) => <span key={i}>{i ? "; " : ""}{x}</span>)}
          </p>
          {people.length > 0 && (
            <p className="mt-0.5 truncate text-[12.5px] text-muted-foreground">
              to {people.slice(0, 3).join(", ")}{people.length > 3 ? ` and ${people.length - 3} more` : ""}
            </p>
          )}
          <button onClick={() => setOpen(!open)} aria-expanded={open} className="mt-1 inline-flex items-center gap-1 text-[12px] font-[510] text-primary hover:underline">
            <ChevronRight className={cn("size-3.5 transition", open && "rotate-90")} /> {open ? "Hide" : "Show"} all {group.length}
          </button>
          {open && <ol className="mt-1 border-l border-border pl-3">{group.map((x) => <EntryRow key={`${x.seq}-${x.hash}`} e={x} names={names} firstBad={firstBad} nested />)}</ol>}
        </div>
        <span className="shrink-0 text-[11.5px] tabular-nums text-faint" title={`${first} to ${last}`}>{when(last)}</span>
      </div>
    </li>
  );
}
