"use client";

import { use, useEffect, useState } from "react";

// The page behind an alert's Approve / Reject button (email or Slack). Public: the signed, single-use link is the
// credential (backend app/alerts/links.py). Opening it only shows what you're deciding; pressing the button acts.

type Check = { name: string; status: "pass" | "fail" | "unverifiable"; detail: string };
type Approval = {
  approval_id: string; action: "send" | "sign_offer"; agent_name: string; agent_status?: string; sponsor?: string;
  to: { name?: string; company?: string }; body: string; scope: string; status: string; created_at: string;
  decided_by?: string | null; checks: Check[]; approvals_needed: number; approvals: { by: string }[];
  rules: { name?: string; sentence?: string; effect?: string; detail?: string }[];
  result: { sent?: boolean; signed?: boolean; error?: string | null; verify_url?: string | null };
};
type Preview = { action: "approve" | "reject"; state: string; message: string | null; for: { email: string; name?: string | null };
  expires_at?: string; approval: Approval };
type Problem = { code: string; message: string };

const OUTCOME: Record<string, { word: string; tone: string }> = {
  sent: { word: "Approved and sent", tone: "text-verified" },
  signed: { word: "Approved and signed", tone: "text-verified" },
  rejected: { word: "Rejected", tone: "text-muted-foreground" },
  blocked_at_send: { word: "Approved, but blocked at send", tone: "text-contradicted" },
  pending: { word: "Your approval is recorded", tone: "text-verified" },
  expired: { word: "Expired", tone: "text-muted-foreground" },
};

export default function ActPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = use(params);
  const [pv, setPv] = useState<Preview>();
  const [problem, setProblem] = useState<Problem>();
  const [done, setDone] = useState<Approval>();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch(`/api/alert-action?t=${encodeURIComponent(token)}`, { cache: "no-store" })
      .then(async (r) => { const j = await r.json(); if (r.ok) setPv(j); else setProblem(j.detail ?? { code: "error", message: "This link can't be used." }); })
      .catch(() => setProblem({ code: "unreachable", message: "Agaxes can't be reached right now. Try again shortly." }));
  }, [token]);

  const go = async () => {
    setBusy(true);
    try {
      const r = await fetch(`/api/alert-action?t=${encodeURIComponent(token)}`, { method: "POST", body: JSON.stringify({ note: note || null }) });
      const j = await r.json();
      if (r.ok) setDone(j.approval);
      else setProblem(j.detail ?? { code: "error", message: "That didn't go through." });
    } catch {
      setProblem({ code: "unreachable", message: "Agaxes can't be reached right now. Try again shortly." });
    } finally { setBusy(false); }
  };

  const a = done ?? pv?.approval;
  const approve = pv?.action === "approve";
  const what = a ? (a.action === "sign_offer" ? `sign an offer letter for ${a.to.name ?? "a candidate"}` : `send a message to ${a.to.name ?? "someone"}${a.to.company ? ` at ${a.to.company}` : ""}`) : "";
  const outcome = done ? OUTCOME[done.status] ?? { word: done.status, tone: "" } : undefined;

  return (
    <main className="mx-auto max-w-[680px] px-4 py-10 sm:py-14">
      <p className="text-[12px] font-[590] uppercase tracking-wide text-faint">Agaxes · needs you</p>
      {!pv && !problem && <p className="mt-8 text-[14px] text-faint">Opening…</p>}

      {a && (
        <>
          <h1 className="mt-2 text-[22px] font-[640] leading-tight">{a.agent_name} wants to {what}</h1>
          <p className="mt-1 text-[13px] text-muted-foreground">
            {a.sponsor ? `Vouched for by ${a.sponsor} · ` : ""}permission {a.scope} · {new Date(a.created_at).toLocaleString()}
          </p>
        </>
      )}

      {outcome && done && (
        <section className="mt-6 rounded-xl border border-border-strong bg-surface p-5">
          <div className={`text-[19px] font-[680] ${outcome.tone}`}>{outcome.word}</div>
          <p className="mt-1 text-[13.5px] leading-relaxed">
            {done.status === "pending" && done.approvals_needed > 1
              ? `${done.approvals.length} of ${done.approvals_needed} approvals so far. It goes out once a different person approves too.`
              : done.status === "blocked_at_send" ? `Send Guard checked it again at send time and stopped it: ${done.result.error ?? "a check failed"}.`
              : `Recorded on the ledger as ${pv?.for.email}. Nothing else to do.`}
          </p>
          {done.result.verify_url && <a href={done.result.verify_url} className="mt-2 inline-block text-[13px] text-primary underline">See the signed copy</a>}
        </section>
      )}

      {problem && !done && (
        <section className="mt-6 rounded-xl border border-flag/40 bg-flag/[0.07] p-5">
          <div className="text-[17px] font-[640]">{problem.code === "expired" ? "This link has expired" : problem.code === "used" ? "This link was already used" : problem.code === "decided" ? "Already decided" : "This link can't be used"}</div>
          <p className="mt-1 text-[13.5px] leading-relaxed">{problem.message}</p>
          <a href="/console?view=work" className="mt-3 inline-block text-[13px] text-primary underline">Open the console</a>
        </section>
      )}

      {pv && !done && !problem && pv.state !== "ready" && (
        <section className="mt-6 rounded-xl border border-border-strong bg-surface p-5">
          <p className="text-[14px]">{pv.message}</p>
          <a href="/console?view=work" className="mt-3 inline-block text-[13px] text-primary underline">Open the console</a>
        </section>
      )}

      {a && (
        <section className="mt-6">
          <h2 className="text-[13px] font-[620] text-muted-foreground">{a.action === "sign_offer" ? "The offer letter" : "The draft"}</h2>
          <pre className="mt-2 max-h-[340px] overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border-strong bg-surface px-4 py-3 text-[13.5px] leading-relaxed">{a.body}</pre>
          {a.checks.length > 0 && (
            <p className="mt-2 text-[12.5px] text-muted-foreground">
              Send Guard: {a.checks.filter((c) => c.status === "pass").length} of {a.checks.length} checks passed. Approving runs it again before anything leaves.
            </p>
          )}
          {a.rules.length > 0 && (
            <ul className="mt-2 space-y-1 text-[12.5px] text-muted-foreground">
              {a.rules.map((r, i) => <li key={i}>Rule: {r.sentence ?? r.name}{r.detail ? `: ${r.detail}` : ""}</li>)}
            </ul>
          )}
          {a.approvals_needed > 1 && (
            <p className="mt-2 text-[12.5px] text-muted-foreground">
              Needs {a.approvals_needed} different people. {a.approvals.length ? `Approved so far by ${a.approvals.map((x) => x.by).join(", ")}.` : "Nobody has approved yet."}
            </p>
          )}
        </section>
      )}

      {pv && pv.state === "ready" && !done && !problem && (
        <section className="mt-6">
          {!approve && (
            <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="Why not? (optional, goes on the ledger)"
              className="mb-3 w-full rounded-lg border border-border-strong bg-panel px-3 py-2 text-[13.5px] outline-none focus:border-primary" />
          )}
          <button onClick={go} disabled={busy}
            className={`h-11 w-full rounded-lg text-[15px] font-[620] text-white transition disabled:opacity-60 sm:w-auto sm:px-8 ${approve ? "bg-verified hover:brightness-110" : "bg-contradicted hover:brightness-110"}`}>
            {busy ? "Working…" : approve ? (a?.action === "sign_offer" ? "Approve and sign" : "Approve and send") : "Reject"}
          </button>
          <p className="mt-3 text-[12px] text-faint">
            You&apos;re deciding as {pv.for.email}. This link works once{pv.expires_at ? ` and expires ${new Date(pv.expires_at).toLocaleString()}` : ""}; the decision is recorded on the ledger with your name.
          </p>
        </section>
      )}
    </main>
  );
}
