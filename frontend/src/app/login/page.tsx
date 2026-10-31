"use client";

import { BRAND } from "@/lib/brand";
import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AuthShell, Button, Divider, Field, Input, Notice, PasswordInput, postJSON, safeNext } from "@/components/auth/ui";

const REASONS: Record<string, string> = {
  expired: "Your session ended. Log in again to pick up where you left off.",
  backend: `Can't reach the ${BRAND.name} backend right now. Start it (backend/scripts/demo_up.sh) and try again.`,
  logout: "You're logged out.",
  reset: "Password updated. Every other session was signed out.",
};

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = safeNext(params.get("next"));
  const reason = params.get("reason");
  const [email, setEmail] = useState(params.get("email") || "");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"login" | "demo" | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy("login");
    const r = await postJSON("/api/auth/login", { email, password });
    if (r.ok) {
      router.replace(next);
      router.refresh();
    } else {
      setError(r.err.message);
      setBusy(null);
    }
  }

  async function demo() {
    setError(null);
    setBusy("demo");
    const r = await postJSON("/api/auth/demo");
    if (r.ok) {
      router.replace(next);
      router.refresh();
    } else {
      setError(r.err.message);
      setBusy(null);
    }
  }

  return (
    <>
      <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Log in to {BRAND.name}</h1>
      <p className="mt-1 text-[14px] text-muted-foreground">
        New here? <Link href="/signup" className="font-medium text-foreground underline-offset-4 hover:underline">Create a company workspace</Link>
      </p>

      <div className="mt-6 space-y-4">
        {reason && REASONS[reason] && !error && <Notice tone={reason === "logout" || reason === "reset" ? "success" : "info"}>{REASONS[reason]}</Notice>}
        {error && <Notice tone="error">{error}</Notice>}

        <form onSubmit={submit} className="space-y-4" noValidate>
          <Field label="Work email" htmlFor="email">
            <Input id="email" type="email" autoComplete="username" autoFocus value={email}
              onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" required />
          </Field>
          <Field label="Password" htmlFor="password"
            labelAside={<Link href={`/forgot${email ? `?email=${encodeURIComponent(email)}` : ""}`} className="text-[12.5px] font-normal text-muted-foreground hover:text-foreground hover:underline">Forgot password?</Link>}>
            <PasswordInput id="password" autoComplete="current-password" value={password}
              onChange={(e) => setPassword(e.target.value)} required />
          </Field>
          <Button type="submit" loading={busy === "login"} disabled={!email || !password || busy !== null}>Log in</Button>
          <p className="text-[12.5px] text-muted-foreground">You stay signed in on this browser for 14 days of use. Five wrong passwords lock the account for 10 minutes.</p>
        </form>

        <Divider label="or" />
        <Button variant="secondary" onClick={demo} loading={busy === "demo"} disabled={busy !== null}>
          Use the demo workspace
        </Button>

        <div className="mt-2 rounded-lg border border-border bg-elevated p-4">
          <p className="text-[13.5px] font-medium">New to Sourced?</p>
          <p className="mt-0.5 text-[13px] text-muted-foreground">Set up a workspace for your company in two steps. No sales call.</p>
          <Link href="/signup" className="mt-3 inline-flex h-9 w-full items-center justify-center rounded-md bg-primary px-3 text-[14px] font-medium text-primary-foreground transition hover:bg-primary-strong">
            Sign up your company
          </Link>
        </div>
      </div>
    </>
  );
}

export default function LoginPage() {
  return (
    <AuthShell switchTo="signup">
      <Suspense>
        <LoginForm />
      </Suspense>
    </AuthShell>
  );
}
