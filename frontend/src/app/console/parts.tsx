"use client";
import { CheckCircle2, CircleDashed, Lock, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Source } from "@/lib/types";
import { SCOPE_INFO, type Agent, type AgentStatus, type Check, type Scope, type Verdict } from "./api";

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
  active: { label: "Active", cls: "bg-lime text-on-color", dot: "bg-[#111]" },
  suspended: { label: "Suspended", cls: "bg-coral text-on-color", dot: "bg-[#111]" },
  offboarded: { label: "Offboarded", cls: "bg-elevated text-muted-foreground", dot: "bg-faint" },
};

export function StatusPill({ status, className }: { status: AgentStatus; className?: string }) {
  const s = STATUS[status];
  return (
    <span className={cn("inline-flex h-6 shrink-0 items-center gap-1.5 rounded-full border-2 border-ink px-2 text-[11px] font-extrabold uppercase tracking-wide shadow-brut-sm", s.cls, className)}>
      <span className={cn("size-1.5 rounded-full", s.dot, status === "active" && "animate-pulse")} />
      {s.label}
    </span>
  );
}

export function ScopeChip({ scope, muted }: { scope: Scope; muted?: boolean }) {
  return (
    <span
      title={SCOPE_INFO[scope]?.detail}
      className={cn(
        "inline-flex h-5 items-center rounded-md border-[1.5px] border-ink px-1.5 font-mono text-[10.5px] font-bold",
        muted ? "text-faint line-through" : "bg-panel text-foreground",
      )}
    >
      {scope}
    </span>
  );
}

const MARK = ["var(--lime)", "var(--sky)", "var(--pink)", "var(--lavender)", "var(--yellow)", "var(--coral)"];

/** Monogram avatar for an AI employee: a colour derived from its id so each one is recognisable in the list. */
export function AgentMark({ agent, size = "md" }: { agent: Pick<Agent, "agent_id" | "name" | "status">; size?: "md" | "lg" }) {
  const hue = [...agent.agent_id].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
  return (
    <span
      className={cn(
        "font-display relative grid shrink-0 place-items-center rounded-xl border-2 border-ink font-extrabold text-[#111] shadow-brut-sm",
        size === "lg" ? "size-12 text-[22px]" : "size-10 text-[17px]",
        agent.status !== "active" && "grayscale-[0.7] opacity-70",
      )}
      style={{ background: MARK[hue % MARK.length] }}
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
      <span>{source.endpoint}</span>
      {source.field && <span className="truncate font-medium opacity-70"> · {source.field}</span>}
    </>
  );
  const cls = "inline-flex max-w-full items-center truncate rounded-md border-[1.5px] border-ink bg-lavender px-1.5 py-px font-mono text-[10.5px] font-bold text-on-color";
  return source.url ? (
    <a href={source.url} target="_blank" rel="noreferrer" className={cn(cls, "hover:shadow-brut-sm")} title={source.url}>
      {body}
    </a>
  ) : (
    <span className={cls}>{body}</span>
  );
}

export function CheckRow({ check }: { check: Check }) {
  const I = ICON[check.status];
  return (
    <li className="grid grid-cols-[16px_minmax(0,1fr)] gap-x-2.5 py-2">
      <I className={cn("mt-0.5 size-4", TONE[check.status])} strokeWidth={2.5} />
      <div className="min-w-0">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <span className="text-[13.5px] font-bold">{checkLabel(check.name)}</span>
          <SourceChip source={check.source} />
        </div>
        <p className={cn("mt-0.5 text-[12.5px] leading-snug", check.status === "pass" ? "text-muted-foreground" : "font-medium text-foreground")}>
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
  return <ul className={cn("divide-y-2 divide-dashed divide-hairline", className)}>{checks.map((c) => <CheckRow key={c.id + c.name} check={c} />)}</ul>;
}

export function DecisionBadge({ decision }: { decision: "allow" | "block" }) {
  return (
    <span
      className={cn(
        "inline-flex h-5 items-center rounded-md border-[1.5px] border-ink px-1.5 font-mono text-[10.5px] font-extrabold uppercase tracking-wide text-on-color",
        decision === "allow" ? "bg-lime" : "bg-coral",
      )}
    >
      {decision}
    </span>
  );
}

export function ScopeToggle({
  scope, checked, locked, onChange, disabled,
}: { scope: Scope; checked: boolean; locked?: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  const info = SCOPE_INFO[scope];
  return (
    <label
      className={cn(
        "flex items-start gap-3 rounded-xl border-2 border-ink px-3 py-2.5 transition",
        locked ? "cursor-not-allowed border-dashed opacity-45" : "press cursor-pointer bg-panel shadow-brut-sm",
        checked && !locked && "bg-yellow text-on-color",
      )}
      title={locked ? "Outside this role's ceiling" : info.detail}
    >
      <input
        type="checkbox"
        className="mt-0.5 size-4 accent-[#111]"
        checked={checked}
        disabled={locked || disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="text-[13.5px] font-bold">{info.label}</span>
          <span className="font-mono text-[10.5px] opacity-60">{scope}</span>
        </span>
        <span className="block text-[12px] opacity-75">{info.detail}</span>
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
        "inline-flex h-8 items-center justify-center gap-1.5 rounded-lg px-3 text-[12.5px] font-bold disabled:cursor-not-allowed disabled:opacity-40",
        variant !== "ghost" && "press border-2 border-ink shadow-brut-sm",
        variant === "primary" && "bg-yellow text-on-color",
        variant === "secondary" && "bg-panel text-foreground",
        variant === "danger" && "bg-coral text-on-color",
        variant === "ghost" && "text-muted-foreground underline-offset-4 hover:text-foreground hover:underline",
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
      <span className="mb-1 block text-[11px] font-extrabold uppercase tracking-wider">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-faint">{hint}</span>}
    </label>
  );
}

export const inputCls =
  "h-9 w-full rounded-lg border-2 border-ink bg-panel px-2.5 text-[13.5px] font-medium outline-none transition placeholder:text-faint focus:shadow-brut-sm";
