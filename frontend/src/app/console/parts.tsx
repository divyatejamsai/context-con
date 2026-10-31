"use client";
import { CheckCircle2, CircleDashed, Lock, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Source } from "@/lib/types";
import { SCOPE_INFO, type Agent, type AgentStatus, type Check, type Scope, type Verdict } from "./api";

// Styling uses only the shared semantic tokens (panel, elevated, border, primary, verified, contradicted, flag...),
// so the console follows whatever look globals.css gives the Sourced app.

export const CHECK_LABEL: Record<string, string> = {
  signature_valid: "Passport signature",
  not_expired: "Not expired",
  not_revoked: "Not revoked",
  scope_in_passport: "Scope in passport",
  sponsor_exists: "Sponsor is a real person",
  sponsor_still_employed: "Sponsor still works there",
  domain_matches_company: "Domain matches company",
  sponsor_title_current: "Sponsor's title is current",
  sponsor_can_grant_scope: "Sponsor can grant this",
  message_signature_valid: "Message signed by the agent",
  recipient_exists: "Recipient is a real person",
  recipient_still_at_company: "Recipient still works there",
  claims_in_body_true: "Claim in the message",
};

export const checkLabel = (name: string) => CHECK_LABEL[name] ?? name.replace(/_/g, " ");

export function ago(iso?: string | null) {
  if (!iso) return "never";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export const day = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "–";

const STATUS: Record<AgentStatus, { label: string; cls: string; dot: string }> = {
  active: { label: "Active", cls: "border-verified/30 bg-verified/10 text-verified", dot: "bg-verified" },
  suspended: { label: "Suspended", cls: "border-contradicted/30 bg-contradicted/10 text-contradicted", dot: "bg-contradicted" },
  offboarded: { label: "Offboarded", cls: "border-border-strong text-muted-foreground", dot: "bg-faint" },
};

export function StatusPill({ status, className }: { status: AgentStatus; className?: string }) {
  const s = STATUS[status];
  return (
    <span className={cn("inline-flex h-5 shrink-0 items-center gap-1.5 rounded-full border px-2 text-[11px] font-[510]", s.cls, className)}>
      <span className={cn("size-1.5 rounded-full", s.dot)} />
      {s.label}
    </span>
  );
}

export function ScopeChip({ scope, muted }: { scope: Scope; muted?: boolean }) {
  return (
    <span
      title={SCOPE_INFO[scope]?.detail}
      className={cn(
        "inline-flex h-5 items-center rounded border px-1.5 font-mono text-[10.5px]",
        muted ? "border-border text-faint line-through" : "border-border-strong bg-elevated text-secondary",
      )}
    >
      {scope}
    </span>
  );
}

export function RuntimeBadge({ runtime }: { runtime?: string }) {
  if (runtime !== "external") return null;
  return (
    <span className="inline-flex h-[18px] items-center rounded border border-border-strong px-1 text-[10.5px] font-[510] text-muted-foreground" title="Runs outside Countersign and reaches it over MCP">
      External
    </span>
  );
}

/** Monogram for an AI employee. Neutral by default; tinted by status so a suspended agent reads at a glance. */
export function AgentMark({ agent, size = "md" }: { agent: Pick<Agent, "name" | "status">; size?: "md" | "lg" }) {
  return (
    <span
      className={cn(
        "grid shrink-0 place-items-center rounded-lg border font-[590]",
        size === "lg" ? "size-11 text-[17px]" : "size-8 text-[13px]",
        agent.status === "active" && "border-border-strong bg-elevated text-foreground",
        agent.status === "suspended" && "border-contradicted/40 bg-contradicted/10 text-contradicted",
        agent.status === "offboarded" && "border-border bg-transparent text-faint",
      )}
    >
      {agent.name.slice(0, 1).toUpperCase()}
    </span>
  );
}

const ICON = { pass: CheckCircle2, fail: XCircle, unverifiable: CircleDashed } as const;
const TONE = { pass: "text-verified", fail: "text-contradicted", unverifiable: "text-unverifiable" } as const;

export function SourceChip({ source }: { source?: Source | null }) {
  if (!source?.endpoint) return <span className="font-mono text-[10.5px] text-faint">no source</span>;
  const body = (
    <>
      <span className="text-secondary">{source.endpoint}</span>
      {source.field && <span className="truncate text-faint"> · {source.field}</span>}
    </>
  );
  const cls = "inline-flex max-w-full items-center truncate rounded border border-border px-1.5 py-px font-mono text-[10.5px]";
  return source.url ? (
    <a href={source.url} target="_blank" rel="noreferrer" className={cn(cls, "hover:border-border-strong")} title={source.url}>
      {body}
    </a>
  ) : (
    <span className={cls}>{body}</span>
  );
}

export function CheckRow({ check }: { check: Check }) {
  const I = ICON[check.status];
  return (
    <li className="grid grid-cols-[16px_minmax(0,1fr)] gap-x-2.5 py-2.5">
      <I className={cn("mt-0.5 size-4", TONE[check.status])} />
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <span className="text-[13px] font-[510]">{checkLabel(check.name)}</span>
          <SourceChip source={check.source} />
        </div>
        <p className={cn("mt-0.5 text-[12.5px] leading-snug", check.status === "pass" ? "text-muted-foreground" : "text-secondary")}>
          {check.detail}
        </p>
      </div>
    </li>
  );
}

export function VerdictList({ verdict, className }: { verdict: Verdict; className?: string }) {
  // Failures first: the reason something was blocked is the first thing to read.
  const order = { fail: 0, unverifiable: 1, pass: 2 } as const;
  const checks = [...verdict.checks].sort((a, b) => order[a.status] - order[b.status]);
  return <ul className={cn("divide-y divide-border", className)}>{checks.map((c) => <CheckRow key={c.id + c.name} check={c} />)}</ul>;
}

export function DecisionBadge({ decision }: { decision: "allow" | "block" }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded px-1.5 font-mono text-[10.5px] font-medium uppercase tracking-wide",
        decision === "allow" ? "bg-verified/15 text-verified" : "bg-contradicted/15 text-contradicted",
      )}
    >
      {decision}
    </span>
  );
}

/** Header strip for a verdict panel: one line that says what happened. */
export function VerdictHeader({ verdict, title, meta }: { verdict: Verdict; title: string; meta?: React.ReactNode }) {
  const ok = verdict.decision === "allow";
  return (
    <div className={cn("flex flex-wrap items-center gap-2.5 border-b px-5 py-3.5", ok ? "border-verified/25 bg-verified/[0.06]" : "border-contradicted/25 bg-contradicted/[0.06]")}>
      <DecisionBadge decision={verdict.decision} />
      <span className="text-[15px] font-[590]">{title}</span>
      {meta && <span className="ml-auto text-[12px] text-muted-foreground">{meta}</span>}
    </div>
  );
}

export function ScopeToggle({
  scope, checked, locked, onChange, disabled,
}: { scope: Scope; checked: boolean; locked?: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  const info = SCOPE_INFO[scope];
  return (
    <label
      className={cn(
        "flex items-start gap-3 rounded-lg border px-3 py-2.5 transition",
        locked ? "cursor-not-allowed border-border opacity-50" : "cursor-pointer border-border-strong hover:bg-hover",
        checked && !locked && "border-primary/50 bg-primary/[0.06]",
      )}
      title={locked ? "Outside this role's ceiling" : info.detail}
    >
      <input
        type="checkbox"
        className="mt-0.5 size-3.5 accent-[var(--primary)]"
        checked={checked}
        disabled={locked || disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="text-[13px] font-[510]">{info.label}</span>
          <span className="font-mono text-[10.5px] text-faint">{scope}</span>
        </span>
        <span className="block text-[12px] text-muted-foreground">{info.detail}</span>
      </span>
      {locked && <Lock className="mt-0.5 size-3.5 text-faint" />}
    </label>
  );
}

export function Button({
  children, onClick, variant = "secondary", disabled, type = "button", title, className,
}: {
  children: React.ReactNode; onClick?: () => void; variant?: "primary" | "secondary" | "danger" | "ghost";
  disabled?: boolean; type?: "button" | "submit"; title?: string; className?: string;
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cn(
        "inline-flex h-8 items-center justify-center gap-1.5 rounded-md px-3 text-[12.5px] font-[510] transition disabled:cursor-not-allowed disabled:opacity-40",
        variant === "primary" && "bg-primary text-primary-foreground hover:bg-primary-strong",
        variant === "secondary" && "border border-border-strong bg-panel text-secondary hover:bg-hover hover:text-foreground",
        variant === "danger" && "border border-contradicted/35 text-contradicted hover:bg-contradicted/10",
        variant === "ghost" && "text-muted-foreground hover:bg-elevated hover:text-foreground",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function Field({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[12px] font-[510] text-muted-foreground">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-faint">{hint}</span>}
    </label>
  );
}

export const inputCls =
  "h-8 w-full rounded-md border border-border-strong bg-panel px-2.5 text-[13px] text-foreground outline-none transition placeholder:text-faint focus:border-primary/60 focus:ring-2 focus:ring-primary/15";

export const cardCls = "rounded-xl border border-border-strong bg-panel";

/** Page heading used by every console view: what the page is for, in one or two sentences. */
export function PageHead({ title, children, eyebrow }: { title: string; children?: React.ReactNode; eyebrow?: string }) {
  return (
    <div>
      {eyebrow && <p className="mb-1 text-[11.5px] font-[510] text-faint">{eyebrow}</p>}
      <h1 className="text-[22px] font-[620] tracking-[-0.02em]">{title}</h1>
      {children && <p className="mt-1.5 max-w-[640px] text-[13px] leading-relaxed text-muted-foreground">{children}</p>}
    </div>
  );
}

/** Numbered "how to use this page" steps, so a first-time user knows where to start. */
export function HowTo({ steps, className }: { steps: React.ReactNode[]; className?: string }) {
  return (
    <ol className={cn("grid gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-3", className)}>
      {steps.map((s, i) => (
        <li key={i} className="flex gap-2.5 bg-elevated px-3 py-2.5 text-[12.5px] leading-snug text-secondary">
          <span className="grid size-5 shrink-0 place-items-center rounded-full border border-border-strong bg-panel font-mono text-[10.5px] text-muted-foreground">
            {i + 1}
          </span>
          <span className="min-w-0">{s}</span>
        </li>
      ))}
    </ol>
  );
}

/** Jargon with its meaning on hover (dotted underline), e.g. <Term tip="...">sponsor</Term>. */
export function Term({ children, tip }: { children: React.ReactNode; tip: string }) {
  return (
    <span title={tip} className="cursor-help underline decoration-border-strong decoration-dotted underline-offset-[3px]">
      {children}
    </span>
  );
}

export const TERMS = {
  passport: "A signed ID card for an AI agent. It names the agent, the person it acts for, and what it may do. Anyone it contacts can check it.",
  sponsor: "The real person the agent acts for. Countersign checks in Crustdata that they exist, still work at the company, and have the authority they delegate.",
  scope: "A permission written into the passport, such as sending hiring outreach or reading data.",
  ledger: "An append-only log of every passport, check and decision. Each entry includes the hash of the one before it, so edits are detectable.",
  guard: "Checks a drafted message before it can leave: the agent's passport, its signature on the text, and every fact about the recipient.",
} as const;

/** Empty or error state with a clear next step. */
export function EmptyState({
  icon: I, title, children, action, tone = "muted", className,
}: { icon?: React.ElementType; title: string; children?: React.ReactNode; action?: React.ReactNode; tone?: "muted" | "bad"; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center px-6 py-10 text-center", className)}>
      {I && (
        <span className={cn("grid size-9 place-items-center rounded-lg border", tone === "bad" ? "border-contradicted/30 bg-contradicted/[0.06] text-contradicted" : "border-border-strong bg-elevated text-muted-foreground")}>
          <I className="size-4" />
        </span>
      )}
      <p className="mt-3 text-[13.5px] font-[590]">{title}</p>
      {children && <p className="mt-1 max-w-[360px] text-[12.5px] leading-relaxed text-muted-foreground">{children}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/** Section heading inside a page, with an optional one-line explanation. */
export function SectionHead({ title, children, aside }: { title: string; children?: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-2">
      <div className="min-w-0">
        <h3 className="text-[14px] font-[590]">{title}</h3>
        {children && <p className="mt-0.5 text-[12px] leading-relaxed text-muted-foreground">{children}</p>}
      </div>
      {aside}
    </div>
  );
}
