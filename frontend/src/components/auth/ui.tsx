"use client";

import { forwardRef, useState } from "react";
import Link from "next/link";
import { BadgeCheck, Check, Eye, EyeOff, Loader2, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";

export function Logo() {
  return (
    <span className="grid size-6 place-items-center rounded-[5px] bg-foreground">
      <Check className="size-3.5 text-background" strokeWidth={3} />
    </span>
  );
}

/** Two-column auth layout: the form on the left, what the workspace gives you on the right. */
export function AuthShell({ children, aside, switchTo }: { children: React.ReactNode; aside?: React.ReactNode; switchTo?: "login" | "signup" }) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1fr)_minmax(0,520px)]">
      <div className="flex flex-col px-5 py-6 sm:px-10">
        <div className="flex items-center justify-between">
          <Link href="/login" className="flex items-center gap-2">
            <Logo />
            <span className="text-[14px] font-semibold tracking-[-0.01em]">Sourced</span>
          </Link>
          {switchTo && (
            <Link href={`/${switchTo}`} className="inline-flex h-8 items-center rounded-md border border-border-strong px-3 text-[13px] font-medium transition hover:bg-hover">
              {switchTo === "signup" ? "Sign up" : "Log in"}
            </Link>
          )}
        </div>
        <div className="mx-auto flex w-full max-w-[400px] flex-1 flex-col justify-center py-10">{children}</div>
        <p className="text-[12px] text-faint">Runs under Countersign: every agent action is passport-checked and logged.</p>
      </div>
      <aside className="hidden border-l border-border bg-elevated lg:flex lg:flex-col lg:justify-center lg:px-12">
        {aside ?? <ProductAside />}
      </aside>
    </div>
  );
}

function ProductAside() {
  const points = [
    { icon: BadgeCheck, title: "Every claim cited", body: "Titles, tenure and employers are checked against Crustdata's live graph, with the source on every line." },
    { icon: ShieldCheck, title: "Agents with a passport", body: "Sourced acts for a named person at your company. If they leave, it stops." },
    { icon: Check, title: "Nothing is sent without a check", body: "Send Guard re-verifies each outreach draft before it can go out." },
  ];
  return (
    <div className="max-w-[400px]">
      <p className="text-[12px] font-medium uppercase tracking-[0.08em] text-faint">Verified sourcing</p>
      <h2 className="mt-2 text-[22px] font-semibold leading-tight tracking-[-0.02em]">A shortlist you can defend, in minutes.</h2>
      <ul className="mt-8 space-y-5">
        {points.map(({ icon: Icon, title, body }) => (
          <li key={title} className="flex gap-3">
            <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-md border border-border bg-panel">
              <Icon className="size-3.5 text-primary" />
            </span>
            <div>
              <p className="text-[13.5px] font-medium">{title}</p>
              <p className="mt-0.5 text-[13px] leading-relaxed text-muted-foreground">{body}</p>
            </div>
          </li>
        ))}
      </ul>
      <div className="mt-10 rounded-lg border border-border bg-panel p-4">
        <p className="text-[12px] font-medium text-faint">Built from ATS reviews</p>
        <p className="mt-1.5 text-[13px] leading-relaxed text-secondary">
          Reviewers of Greenhouse, Lever and Ashby ask for self-serve setup instead of a sales call, fewer settings
          before the first result, and data they can trust. Sign-up takes two steps and fills in your company for you.
        </p>
      </div>
    </div>
  );
}

export function Field({ label, hint, error, optional, htmlFor, children }: {
  label: string; hint?: string; error?: string | null; optional?: boolean; htmlFor?: string; children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="flex items-baseline justify-between text-[13px] font-medium">
        {label}
        {optional && <span className="text-[12px] font-normal text-faint">Optional</span>}
      </label>
      {children}
      {error ? (
        <p className="text-[12.5px] text-contradicted" role="alert">{error}</p>
      ) : hint ? (
        <p className="text-[12.5px] text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  );
}

const inputCls =
  "h-9 w-full rounded-md border border-border-strong bg-panel px-3 text-[14px] outline-none transition placeholder:text-faint " +
  "focus:border-primary focus:ring-[3px] focus:ring-[var(--glow)] disabled:opacity-60 aria-[invalid=true]:border-contradicted";

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props }, ref,
) {
  return <input ref={ref} className={cn(inputCls, className)} {...props} />;
});

export function PasswordInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <Input {...props} type={show ? "text" : "password"} className="pr-9" />
      <button
        type="button"
        onClick={() => setShow((s) => !s)}
        className="absolute inset-y-0 right-0 grid w-9 place-items-center text-faint hover:text-foreground"
        aria-label={show ? "Hide password" : "Show password"}
      >
        {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  );
}

export function Select({ options, placeholder, className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement> & {
  options: string[]; placeholder?: string;
}) {
  return (
    <select className={cn(inputCls, "pr-2", className)} {...props}>
      {placeholder && <option value="">{placeholder}</option>}
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  );
}

export function Button({ loading, variant = "primary", className, children, ...props }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean; variant?: "primary" | "secondary" | "ghost" }) {
  return (
    <button
      className={cn(
        "inline-flex h-9 w-full items-center justify-center gap-2 rounded-md px-3 text-[14px] font-medium transition disabled:cursor-not-allowed disabled:opacity-60",
        variant === "primary" && "bg-foreground text-background hover:opacity-90",
        variant === "secondary" && "border border-border-strong bg-panel hover:bg-hover",
        variant === "ghost" && "text-muted-foreground hover:bg-hover hover:text-foreground",
        className,
      )}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading && <Loader2 className="size-4 animate-spin" />}
      {children}
    </button>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "error" | "success"; children: React.ReactNode }) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn(
        "rounded-md border px-3 py-2.5 text-[13px] leading-relaxed",
        tone === "info" && "border-border bg-elevated text-secondary",
        tone === "error" && "border-[color-mix(in_oklab,var(--contradicted)_35%,transparent)] bg-coral text-foreground",
        tone === "success" && "border-[color-mix(in_oklab,var(--verified)_35%,transparent)] bg-lime text-foreground",
      )}
    >
      {children}
    </div>
  );
}

export function Divider({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 text-[12px] text-faint">
      <span className="h-px flex-1 bg-border" />
      {label}
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}

export interface ApiError { error: string; message: string; field?: string | null }

export async function postJSON<T>(path: string, body?: unknown): Promise<{ ok: true; data: T } | { ok: false; err: ApiError }> {
  try {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}) });
    const data = await r.json().catch(() => ({}));
    if (r.ok) return { ok: true, data: data as T };
    return { ok: false, err: { error: data.error || "error", message: data.message || `Request failed (${r.status})`, field: data.field } };
  } catch {
    return { ok: false, err: { error: "network", message: "Network error. Check your connection and try again." } };
  }
}

export function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}
