"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AuthShell, Button, Field, Input, Notice, postJSON } from "@/components/auth/ui";

function ForgotForm() {
  const params = useSearchParams();
  const [email, setEmail] = useState(params.get("email") || "");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const r = await postJSON<{ message: string }>("/api/auth/forgot", { email });
    setBusy(false);
    if (r.ok) setSent(r.data.message);
    else setError(r.err.message);
  }

  return (
    <>
      <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Reset your password</h1>
      <p className="mt-1 text-[14px] text-muted-foreground">We&apos;ll email a link to the address you signed up with.</p>
      <div className="mt-6 space-y-4">
        {sent ? (
          <Notice tone="success">{sent}</Notice>
        ) : (
          <form onSubmit={submit} className="space-y-4" noValidate>
            {error && <Notice tone="error">{error}</Notice>}
            <Field label="Work email" htmlFor="email">
              <Input id="email" type="email" autoComplete="username" autoFocus value={email} placeholder="you@company.com"
                onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Button type="submit" loading={busy} disabled={!email || busy}>Send reset link</Button>
          </form>
        )}
        <Link href="/login" className="block text-center text-[13px] text-muted-foreground hover:text-foreground">Back to log in</Link>
      </div>
    </>
  );
}

export default function ForgotPage() {
  return (
    <AuthShell switchTo="login">
      <Suspense>
        <ForgotForm />
      </Suspense>
    </AuthShell>
  );
}
