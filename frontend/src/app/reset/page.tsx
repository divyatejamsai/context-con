"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AuthShell, Button, Field, Notice, PasswordInput, postJSON } from "@/components/auth/ui";

function ResetForm() {
  const router = useRouter();
  const token = useSearchParams().get("token") || "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ message: string; expired: boolean } | null>(null);
  const mismatch = confirm.length > 0 && confirm !== password;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const r = await postJSON("/api/auth/reset", { token, password });
    if (r.ok) {
      router.replace("/");
      router.refresh();
    } else {
      setBusy(false);
      setError({ message: r.err.message, expired: r.err.error === "reset_invalid" });
    }
  }

  if (!token) {
    return (
      <>
        <h1 className="text-[22px] font-semibold tracking-[-0.02em]">This link is incomplete</h1>
        <p className="mt-2 text-[14px] text-muted-foreground">Open the link from your email again, or <Link href="/forgot" className="text-foreground underline-offset-4 hover:underline">ask for a new one</Link>.</p>
      </>
    );
  }

  return (
    <>
      <h1 className="text-[22px] font-semibold tracking-[-0.02em]">Choose a new password</h1>
      <p className="mt-1 text-[14px] text-muted-foreground">You&apos;ll be signed in, and every other session will be signed out.</p>
      <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
        {error && (
          <Notice tone="error">
            {error.message} {error.expired && <Link href="/forgot" className="font-medium underline-offset-4 hover:underline">Send a new link</Link>}
          </Notice>
        )}
        <Field label="New password" htmlFor="password" hint="At least 10 characters.">
          <PasswordInput id="password" autoComplete="new-password" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <Field label="Confirm password" htmlFor="confirm" error={mismatch ? "Passwords don't match." : null}>
          <PasswordInput id="confirm" autoComplete="new-password" value={confirm} aria-invalid={mismatch} onChange={(e) => setConfirm(e.target.value)} />
        </Field>
        <Button type="submit" loading={busy} disabled={busy || password.length < 10 || confirm !== password}>Set password and log in</Button>
      </form>
    </>
  );
}

export default function ResetPage() {
  return (
    <AuthShell switchTo="login">
      <Suspense>
        <ResetForm />
      </Suspense>
    </AuthShell>
  );
}
